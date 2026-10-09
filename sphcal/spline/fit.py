"""
Penalized fitting of spline models: least squares, robust IRLS, logistic IRLS, GCV.

What this module computes
-------------------------
* fit_penalized_least_squares: minimizes sum_i w_i (y_i - (A c)_i)^2 + c^T P c.
* fit_robust: the same with Huber weights found by iteratively reweighted least squares.
* fit_logistic: penalized logistic regression, minimizing
  -sum_i w_i [y_i log p_i + (1 - y_i) log(1 - p_i)] + c^T P c / 2 with
  p = sigmoid(A c), by penalized IRLS (Newton steps) with step halving.
* select_smoothing_by_gcv: chooses each term's smoothing by minimizing generalized
  cross-validation over a logarithmic grid.

Conventions
-----------
* A is the (N, n) design matrix, y the targets, w >= 0 the sample weights, P the
  (n, n) symmetric positive semi-definite penalty (smoothing already included).
* Normal equations: (A^T W A + P) c = A^T W y with W = diag(w), plus a tiny
  diagonal jitter (relative_diagonal_jitter times the mean diagonal) so a system
  whose penalty null space is not constrained by data stays solvable.
* Solvers. "direct" factors the sparse normal matrix with scipy.sparse.linalg.splu.
  "iterative" runs scipy.sparse.linalg.cg on the same normal equations with a
  Jacobi (inverse diagonal) preconditioner, matrix-free: it never forms A^T W A.
  (CG on the normal equations was chosen over lsqr because the penalty enters the
  system directly, with no square root of P needed.) "auto" picks direct when the
  coefficient count is at most SolverOptions.direct_max_coefficients.
* effective_degrees_of_freedom is the trace of the hat matrix,
  tr[(A^T W A + P)^-1 A^T W A]. It is computed exactly when the solve is direct and
  the coefficient count is at most SolverOptions.exact_trace_max_coefficients;
  otherwise by the Hutchinson estimator with Rademacher probes.
* residual_rms is the weighted root-mean-square residual sqrt(sum w r^2 / sum w).
* gcv_score = N * weighted RSS / (N - edof)^2, N being the number of samples with
  positive weight (infinite when N <= edof). For logistic fits the RSS is
  replaced by the weighted deviance.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.special import expit, xlogy

# Gaussian-consistency factor: for normal data the standard deviation is 1.4826
# times the median absolute deviation (1 / Phi^-1(3/4)).
MEDIAN_ABSOLUTE_DEVIATION_TO_SIGMA = 1.4826

# Smallest positive double: floor for a robust scale or a norm used as a divisor,
# so an exact fit or an all-zero coefficient vector does not divide by zero.
SMALLEST_POSITIVE_FLOAT = float(np.finfo(np.float64).tiny)

# Factor by which the Newton step of the logistic IRLS is shortened when it does
# not decrease the penalized objective.
LOGISTIC_STEP_HALVING_FACTOR = 0.5

# Base of the logarithmic smoothing grid: grid value g means a multiplier 10 ** g.
SMOOTHING_GRID_BASE = 10.0

# Diagonal scale used for the jitter when the normal matrix has a non-positive
# mean diagonal (an all-zero system).
FALLBACK_DIAGONAL_SCALE = 1.0

SOLVER_DIRECT = "direct"
SOLVER_ITERATIVE = "iterative"
SOLVER_AUTO = "auto"


@dataclass(frozen=True)
class SolverOptions:
    """Numerical options of the linear solves."""

    direct_max_coefficients: int = 20000  # "auto" is direct up to this many coefficients
    exact_trace_max_coefficients: int = 3000  # exact edof (dense solve) up to this many, direct only
    hutchinson_probes: int = 30  # number of Rademacher probe vectors of the stochastic edof
    hutchinson_seed: int = 0  # seed of the probe generator (results are reproducible)
    cg_relative_tolerance: float = 1e-10  # CG stopping tolerance on the relative residual
    cg_max_iterations: int = 5000  # CG iteration cap per right-hand side
    relative_diagonal_jitter: float = 1e-10  # jitter as a fraction of the mean diagonal


DEFAULT_SOLVER_OPTIONS = SolverOptions()


@dataclass(frozen=True)
class RobustParameters:
    """Huber IRLS settings."""

    huber_delta_in_sigmas: float = 2.5  # residuals beyond this many sigmas are down-weighted
    max_iterations: int = 10  # reweighting iterations after the initial plain fit
    convergence_tolerance: float = 1e-4  # relative change of the coefficients that stops IRLS


@dataclass(frozen=True)
class LogisticParameters:
    """Logistic IRLS settings."""

    max_iterations: int = 25  # Newton iterations
    convergence_tolerance: float = 1e-6  # relative change of the coefficients that stops
    probability_clip: float = 1e-6  # probabilities are clipped to [clip, 1 - clip]
    max_step_halvings: int = 10  # step shortenings tried before giving up on a Newton step


@dataclass(frozen=True)
class SmoothingGrid:
    """Logarithmic grid of the GCV smoothing search."""

    log10_min: float = -4.0  # smallest multiplier is 10 ** log10_min
    log10_max: float = 4.0  # largest multiplier is 10 ** log10_max
    n_values: int = 9  # grid points per term per round
    n_rounds: int = 2  # passes over all terms (stops early when nothing changes)


@dataclass
class FitResult:
    """Outcome of a fit.

    coefficients, effective_degrees_of_freedom, residual_rms and gcv_score are
    defined in the module docstring. The remaining fields describe how the fit
    was obtained: the solver actually used, whether the iterative parts
    converged, the number of reweighting iterations (robust and logistic fits),
    and the final sample weights (the robust fit's reweighted weights; for a
    logistic fit the final IRLS weights w * p * (1 - p)).
    """

    coefficients: np.ndarray
    effective_degrees_of_freedom: float
    residual_rms: float
    gcv_score: float
    solver_used: str = SOLVER_DIRECT
    converged: bool = True
    iterations: int = 0
    weights: np.ndarray = None


# ---------------------------------------------------------------------- linear algebra


def _resolve_solver(solver: str, n_coefficients: int, options: SolverOptions) -> str:
    """Map "auto" to "direct" or "iterative" by the coefficient count."""
    if solver == SOLVER_AUTO:
        return SOLVER_DIRECT if n_coefficients <= options.direct_max_coefficients else SOLVER_ITERATIVE
    if solver not in (SOLVER_DIRECT, SOLVER_ITERATIVE):
        raise ValueError(f"unknown solver {solver!r}")
    return solver


def _gram_matrix(design: sp.csr_matrix, weights: np.ndarray) -> sp.csc_matrix:
    """A^T W A as a sparse CSC matrix."""
    return (design.T @ sp.diags(weights) @ design).tocsc()


class _NormalEquations:
    """The system (A^T W A + P + jitter I) c = rhs with a direct or iterative solver."""

    def __init__(self, design, weights, penalty, solver, options, gram=None) -> None:
        self.design = sp.csr_matrix(design)
        self.weights = np.asarray(weights, dtype=np.float64)
        self.penalty = sp.csr_matrix(penalty)
        self.options = options
        self.n_coefficients = self.design.shape[1]
        self.solver = _resolve_solver(solver, self.n_coefficients, options)
        self.converged = True
        if self.solver == SOLVER_DIRECT:
            self.gram = _gram_matrix(self.design, self.weights) if gram is None else gram
            diagonal = self.gram.diagonal() + self.penalty.diagonal()
        else:
            self.gram = None
            squared = self.design.multiply(self.design).tocsr()
            diagonal = np.asarray(squared.T @ self.weights).ravel() + self.penalty.diagonal()
        scale = float(np.mean(diagonal))
        if not scale > 0:
            scale = FALLBACK_DIAGONAL_SCALE
        self.jitter = options.relative_diagonal_jitter * scale
        if self.solver == SOLVER_DIRECT:
            system = self.gram + self.penalty + self.jitter * sp.identity(self.n_coefficients, format="csc")
            self._factor = spla.splu(sp.csc_matrix(system))
        else:
            self._operator = spla.LinearOperator(
                (self.n_coefficients, self.n_coefficients),
                matvec=lambda v: self.gram_apply(v) + self.penalty @ v + self.jitter * v,
                dtype=np.float64,
            )
            self._preconditioner = spla.LinearOperator(
                (self.n_coefficients, self.n_coefficients),
                matvec=lambda v: v / (diagonal + self.jitter),
                dtype=np.float64,
            )

    def gram_apply(self, vectors: np.ndarray) -> np.ndarray:
        """A^T W A v for a vector (n,) or a matrix of column vectors (n, k)."""
        if vectors.ndim == 1:
            return self.design.T @ (self.weights * (self.design @ vectors))
        return self.design.T @ (self.weights[:, None] * (self.design @ vectors))

    def right_hand_side(self, targets: np.ndarray) -> np.ndarray:
        """A^T W z for targets z."""
        return self.design.T @ (self.weights * targets)

    def solve(self, rhs: np.ndarray) -> np.ndarray:
        """Solve the system for a right-hand side (n,) or (n, k)."""
        if self.solver == SOLVER_DIRECT:
            return self._factor.solve(rhs)
        if rhs.ndim == 1:
            return self._cg(rhs)
        return np.column_stack([self._cg(rhs[:, k]) for k in range(rhs.shape[1])])

    def _cg(self, rhs: np.ndarray) -> np.ndarray:
        solution, info = spla.cg(
            self._operator,
            rhs,
            rtol=self.options.cg_relative_tolerance,
            maxiter=self.options.cg_max_iterations,
            M=self._preconditioner,
        )
        if info != 0:
            self.converged = False
        return solution

    def effective_degrees_of_freedom(self) -> float:
        """tr[(A^T W A + P)^-1 A^T W A]: exact if direct and small, else Hutchinson."""
        n = self.n_coefficients
        if self.solver == SOLVER_DIRECT and n <= self.options.exact_trace_max_coefficients:
            return float(np.trace(self.solve(self.gram.toarray())))
        generator = np.random.default_rng(self.options.hutchinson_seed)
        probes = generator.choice([-1.0, 1.0], size=(n, self.options.hutchinson_probes))
        solved = self.solve(self.gram_apply(probes))
        return float(np.mean(np.sum(probes * solved, axis=0)))


def _validate(design, y, weights):
    """Coerce inputs to (csr matrix, float arrays) and check consistency."""
    design = sp.csr_matrix(design)
    y = np.asarray(y, dtype=np.float64).reshape(-1)
    weights = np.asarray(weights, dtype=np.float64).reshape(-1)
    if y.size != design.shape[0] or weights.size != design.shape[0]:
        raise ValueError("design, y and weights must have the same number of rows")
    if not (np.all(np.isfinite(y)) and np.all(np.isfinite(weights))):
        raise ValueError("y and weights must be finite")
    if np.any(weights < 0):
        raise ValueError("weights must be non-negative")
    if not np.any(weights > 0):
        raise ValueError("at least one weight must be positive")
    return design, y, weights


def _gcv(n_samples: int, edof: float, discrepancy: float) -> float:
    """N * discrepancy / (N - edof)^2, infinite when N <= edof."""
    if n_samples - edof <= 0:
        return float("inf")
    return n_samples * discrepancy / (n_samples - edof) ** 2


def _fit_core(design, y, weights, penalty, solver, options, gram=None) -> FitResult:
    """One penalized weighted least-squares solve with its diagnostics."""
    design, y, weights = _validate(design, y, weights)
    system = _NormalEquations(design, weights, penalty, solver, options, gram=gram)
    coefficients = system.solve(system.right_hand_side(y))
    residual = y - design @ coefficients
    weighted_rss = float(np.sum(weights * residual**2))
    edof = system.effective_degrees_of_freedom()
    n_samples = int(np.count_nonzero(weights))
    return FitResult(
        coefficients=coefficients,
        effective_degrees_of_freedom=edof,
        residual_rms=float(np.sqrt(weighted_rss / np.sum(weights))),
        gcv_score=_gcv(n_samples, edof, weighted_rss),
        solver_used=system.solver,
        converged=system.converged,
        weights=weights,
    )


# ---------------------------------------------------------------------- public fits


def fit_penalized_least_squares(
    design, y, weights, penalty, solver: str = SOLVER_AUTO, options: SolverOptions = DEFAULT_SOLVER_OPTIONS
) -> FitResult:
    """Minimize sum w (y - A c)^2 + c^T P c; see the module docstring for solvers and diagnostics."""
    return _fit_core(design, y, weights, penalty, solver, options)


def fit_robust(
    design,
    y,
    weights,
    penalty,
    robust: RobustParameters = RobustParameters(),
    solver: str = SOLVER_AUTO,
    options: SolverOptions = DEFAULT_SOLVER_OPTIONS,
) -> FitResult:
    """Penalized least squares with Huber weights by IRLS.

    A plain fit starts the iteration. Each iteration forms the standardized
    residuals e_i = sqrt(w_i) r_i (the plain residuals for unit weights), estimates
    sigma = MEDIAN_ABSOLUTE_DEVIATION_TO_SIGMA * median(|e_i|) over samples with
    positive weight, gives sample i the Huber factor min(1, delta sigma / |e_i|)
    (delta = huber_delta_in_sigmas), multiplies it into the original weight, and
    refits. It stops when the relative change of the coefficient vector is below
    convergence_tolerance or after max_iterations iterations. The returned
    diagnostics (residual_rms, edof, gcv_score) use the final reweighted weights,
    which are also returned in FitResult.weights.
    """
    design, y, base_weights = _validate(design, y, weights)
    result = _fit_core(design, y, base_weights, penalty, solver, options)
    positive = base_weights > 0
    converged = False
    iteration = 0
    for iteration in range(1, robust.max_iterations + 1):
        standardized = np.abs(np.sqrt(base_weights) * (y - design @ result.coefficients))
        sigma = MEDIAN_ABSOLUTE_DEVIATION_TO_SIGMA * float(np.median(standardized[positive]))
        if sigma <= SMALLEST_POSITIVE_FLOAT:
            huber = np.ones_like(standardized)  # an essentially exact fit has no outliers
        else:
            threshold = robust.huber_delta_in_sigmas * sigma
            huber = np.ones_like(standardized)
            beyond = standardized > threshold
            huber[beyond] = threshold / standardized[beyond]
        updated = _fit_core(design, y, base_weights * huber, penalty, solver, options)
        change = np.linalg.norm(updated.coefficients - result.coefficients) / max(
            np.linalg.norm(result.coefficients), SMALLEST_POSITIVE_FLOAT
        )
        result = updated
        if change < robust.convergence_tolerance:
            converged = True
            break
    result.converged = result.converged and converged
    result.iterations = iteration
    return result


def _logistic_negative_log_likelihood_terms(y, probability) -> np.ndarray:
    """Per-sample -[y log p + (1 - y) log(1 - p)]."""
    return -(xlogy(y, probability) + xlogy(1.0 - y, 1.0 - probability))


def _logistic_negative_log_likelihood(y, probability, weights) -> float:
    """-sum w [y log p + (1 - y) log(1 - p)]."""
    return float(np.sum(weights * _logistic_negative_log_likelihood_terms(y, probability)))


def fit_logistic(
    design,
    y_binary,
    weights,
    penalty,
    params: LogisticParameters = LogisticParameters(),
    solver: str = SOLVER_AUTO,
    options: SolverOptions = DEFAULT_SOLVER_OPTIONS,
) -> FitResult:
    """Penalized logistic regression by IRLS; the coefficients are those of the logit.

    y_binary holds 0/1 labels (fractions in [0, 1] are accepted). Each iteration is
    a Newton step for the penalized negative log-likelihood: with p = clipped
    sigmoid(A c), IRLS weights w p (1 - p) and working response eta + (y - p) /
    (p (1 - p)), it solves the penalized weighted least-squares system. A step
    that does not lower the objective is halved up to max_step_halvings times;
    if none helps the iteration stops. Starting point c = 0 (p = 1/2).
    The reported residual_rms is the weighted RMS of y - p, effective degrees of
    freedom use the final IRLS weights, and gcv_score uses the weighted deviance.
    """
    design, y, weights = _validate(design, y_binary, weights)
    if np.any(y < 0) or np.any(y > 1):
        raise ValueError("y_binary must lie in [0, 1]")
    penalty = sp.csr_matrix(penalty)
    clip = params.probability_clip

    def probability_of(coefficients):
        return np.clip(expit(design @ coefficients), clip, 1.0 - clip)

    def objective_of(coefficients):
        p = probability_of(coefficients)
        return _logistic_negative_log_likelihood(y, p, weights) + float(coefficients @ (penalty @ coefficients)) / 2.0

    coefficients = np.zeros(design.shape[1])
    converged = False
    iteration = 0
    for iteration in range(1, params.max_iterations + 1):
        eta = design @ coefficients
        p = probability_of(coefficients)
        variance = p * (1.0 - p)
        system = _NormalEquations(design, weights * variance, penalty, solver, options)
        candidate = system.solve(system.right_hand_side(eta + (y - p) / variance))
        step = candidate - coefficients
        current_objective = objective_of(coefficients)
        scale = 1.0
        accepted = False
        for _ in range(params.max_step_halvings + 1):
            trial = coefficients + scale * step
            if objective_of(trial) <= current_objective:
                accepted = True
                break
            scale *= LOGISTIC_STEP_HALVING_FACTOR
        if not accepted:
            converged = True  # no descent direction left at working precision
            break
        change = np.linalg.norm(trial - coefficients) / max(np.linalg.norm(trial), SMALLEST_POSITIVE_FLOAT)
        coefficients = trial
        if change < params.convergence_tolerance:
            converged = True
            break

    p = probability_of(coefficients)
    final_weights = weights * p * (1.0 - p)
    system = _NormalEquations(design, final_weights, penalty, solver, options)
    edof = system.effective_degrees_of_freedom()
    saturated = xlogy(y, y) + xlogy(1.0 - y, 1.0 - y)
    deviance = 2.0 * float(np.sum(weights * (saturated + _logistic_negative_log_likelihood_terms(y, p))))
    n_samples = int(np.count_nonzero(weights))
    return FitResult(
        coefficients=coefficients,
        effective_degrees_of_freedom=edof,
        residual_rms=float(np.sqrt(np.sum(weights * (y - p) ** 2) / np.sum(weights))),
        gcv_score=_gcv(n_samples, edof, deviance),
        solver_used=system.solver,
        converged=converged and system.converged,
        iterations=iteration,
        weights=final_weights,
    )


# ---------------------------------------------------------------------- GCV smoothing


@dataclass
class GcvSearchResult:
    """Outcome of the GCV smoothing search.

    model: copy of the input model with the selected smoothing and fitted coefficients.
    fit: the final FitResult (includes the minimized GCV score).
    log10_multipliers: per term, log10 of the factor applied to the term's initial smoothing.
    """

    model: object
    fit: FitResult
    log10_multipliers: list = field(default_factory=list)


def _embed(matrix: sp.spmatrix, offset: int, total: int) -> sp.csr_matrix:
    """Place a square block at [offset, offset + size) of a (total, total) zero matrix."""
    block = matrix.tocoo()
    return sp.coo_matrix(
        (block.data, (block.row + offset, block.col + offset)), shape=(total, total)
    ).tocsr()


def search_smoothing_by_gcv(
    model,
    X,
    y,
    weights,
    grid: SmoothingGrid = SmoothingGrid(),
    solver: str = SOLVER_AUTO,
    options: SolverOptions = DEFAULT_SOLVER_OPTIONS,
) -> GcvSearchResult:
    """Coordinate-wise GCV search; see select_smoothing_by_gcv. Also returns the final fit."""
    design = model.design(X)
    design, y, weights = _validate(design, y, weights)
    gram = _gram_matrix(design, weights)
    total = model.n_coefficients

    # Penalty of each term at its initial smoothing, embedded in the full
    # coefficient space. A term's grid value multiplies all its smoothing
    # parameters together, so the term's penalty is multiplier * this matrix.
    term_penalties = [
        _embed(term.penalty(), term_slice.start, total)
        for term, term_slice in zip(model.terms, model.term_slices())
    ]
    log10_values = np.linspace(grid.log10_min, grid.log10_max, grid.n_values)
    log10_selected = [0.0] * len(model.terms)  # multiplier 1: the model's own smoothing

    def fit_for(log10_multipliers) -> FitResult:
        penalty = sp.csr_matrix((total, total))
        for matrix, log10_multiplier in zip(term_penalties, log10_multipliers):
            penalty = penalty + (SMOOTHING_GRID_BASE**log10_multiplier) * matrix
        return _fit_core(design, y, weights, penalty, solver, options, gram=gram)

    for _ in range(grid.n_rounds):
        changed = False
        for t in range(len(model.terms)):
            best_value = log10_selected[t]
            best_score = float("inf")
            for candidate in log10_values:
                trial = list(log10_selected)
                trial[t] = float(candidate)
                score = fit_for(trial).gcv_score
                if score < best_score:
                    best_score, best_value = score, float(candidate)
            if best_value != log10_selected[t]:
                log10_selected[t] = best_value
                changed = True
        if not changed:
            break

    final_fit = fit_for(log10_selected)
    selected = model.copy()
    for term, log10_multiplier in zip(selected.terms, log10_selected):
        term.smoothing = [s * SMOOTHING_GRID_BASE**log10_multiplier for s in term.smoothing]
    selected.coefficients = final_fit.coefficients.copy()
    return GcvSearchResult(model=selected, fit=final_fit, log10_multipliers=log10_selected)


def select_smoothing_by_gcv(model, X, y, weights, grid: SmoothingGrid = SmoothingGrid()):
    """Choose each term's smoothing by minimizing GCV; returns a new fitted model.

    Each term's smoothing parameters are scaled together: the grid value g gives
    the term smoothing[d] = initial_smoothing[d] * 10 ** g for every dimension d,
    where initial_smoothing is the model's smoothing on entry (so relative
    smoothing between a term's dimensions is kept). The search starts at g = 0 for
    every term, then makes grid.n_rounds passes over the terms; in a pass each
    term in turn tries all grid values with the other terms held fixed and keeps
    the one with the lowest GCV score (ties go to the earlier grid value). It
    stops early after a pass in which nothing changed. The input model is not
    modified; the result has the selected smoothing on its terms and the
    coefficients fitted with it.
    """
    return search_smoothing_by_gcv(model, X, y, weights, grid).model
