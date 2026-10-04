"""
Fast solves for a FIXED design matrix.

In the correction fit the design matrix (B-spline basis products at the
measured inputs) never changes: the sensor-to-positioner transform changes
only the residual targets, cross-validation changes only the penalty, and the
robust iteration changes only a minority of the weights. Everything is
therefore organized around Gram matrices A^T W A accumulated once:

- the penalized normal equations (G + P) c = A^T W y are re-solved for new
  targets y or a new penalty P without touching A again;
- cross-validation over pose folds uses per-fold Gram matrices, so a held-out
  score is a quadratic form, not a matrix-vector product over the fold's rows;
- the Huber iteration updates G by subtracting the contribution of the
  down-weighted rows only.

Sizes: with about 1,500 coefficients, G is a 1,500-square sparse matrix whose
sparse LU factorization takes a fraction of a second, against seconds for a
fresh accumulation of A^T W A over 10^5 rows.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

MEDIAN_ABSOLUTE_DEVIATION_TO_SIGMA = 1.4826
"""Factor converting a median absolute deviation into a Gaussian sigma."""

RELATIVE_DIAGONAL_JITTER = 1.0e-10
"""Added to the diagonal, as a fraction of its mean, so that a penalty null
space unconstrained by data does not make the system singular."""

MAX_COEFFICIENTS_FOR_EXACT_EDOF = 4000
"""Up to this many coefficients the effective degrees of freedom are computed
exactly as trace((G + P)^-1 G); beyond it they are not computed (NaN)."""


@dataclass(frozen=True)
class HuberParameters:
    delta_in_sigmas: float = 2.5
    """Standardized residuals beyond this are down-weighted."""
    max_iterations: int = 10
    convergence_tolerance: float = 1.0e-4
    """Relative change of the coefficient vector below which the iteration stops."""


@dataclass
class FastFitResult:
    coefficients: np.ndarray
    robust_weights: np.ndarray       # Huber factors in (0, 1], one per row
    iterations: int
    weighted_residual_rms: float
    effective_degrees_of_freedom: float


class FixedDesignSystem:
    """Gram-matrix machinery for one design matrix and one base weight vector."""

    def __init__(self, design: sp.csr_matrix, weights: np.ndarray) -> None:
        self.design = sp.csr_matrix(design)
        self.weights = np.asarray(weights, dtype=np.float64)
        self.n_rows, self.n_coefficients = self.design.shape
        self.gram = self._gram(np.arange(self.n_rows), self.weights)
        diagonal = self.gram.diagonal()
        self.jitter = RELATIVE_DIAGONAL_JITTER * float(diagonal.mean()) if diagonal.size else 0.0

    def _gram(self, rows: np.ndarray, weights: np.ndarray) -> sp.csc_matrix:
        """A_rows^T diag(weights) A_rows as CSC."""
        a = self.design[rows]
        return sp.csc_matrix((a.T @ sp.diags(weights[rows] if weights.shape[0] == self.n_rows else weights)) @ a)

    def rhs(self, y: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
        """A^T W y for the given targets (and optional per-row weights)."""
        w = self.weights if weights is None else weights
        return self.design.T @ (w * y)

    def factor(self, gram: sp.spmatrix, penalty: sp.spmatrix):
        system = sp.csc_matrix(gram + penalty + self.jitter * sp.identity(self.n_coefficients, format="csc"))
        return spla.splu(system)

    def solve(self, y: np.ndarray, penalty: sp.spmatrix, factor=None) -> np.ndarray:
        """Plain penalized weighted least squares with the base weights."""
        factor = factor or self.factor(self.gram, penalty)
        return factor.solve(self.rhs(y))

    def effective_degrees_of_freedom(self, gram: sp.spmatrix, factor) -> float:
        """trace((G + P)^-1 G), the trace of the hat matrix in coefficient space."""
        if self.n_coefficients > MAX_COEFFICIENTS_FOR_EXACT_EDOF:
            return float("nan")
        return float(np.trace(factor.solve(np.asarray(gram.todense()))))

    def robust_solve(self, y: np.ndarray, penalty: sp.spmatrix, params: HuberParameters,
                     initial_robust_weights: np.ndarray | None = None) -> FastFitResult:
        """
        Huber IRLS. Each iteration the Gram matrix is G_base minus the
        contribution of the rows whose Huber factor h is below one,
        A_d^T diag(w_d (1 - h_d)) A_d, so only the outlying rows are revisited.
        """
        h = np.ones(self.n_rows) if initial_robust_weights is None else np.asarray(initial_robust_weights, dtype=np.float64)
        coefficients = np.zeros(self.n_coefficients)
        gram = self.gram
        factor = None
        iterations = 0
        for iterations in range(1, params.max_iterations + 1):
            down = np.nonzero(h < 1.0)[0]
            if down.size:
                gram = self.gram - self._gram(down, (self.weights * (1.0 - h))[down])
            else:
                gram = self.gram
            factor = self.factor(gram, penalty)
            new_coefficients = factor.solve(self.rhs(y, self.weights * h))
            change = np.linalg.norm(new_coefficients - coefficients) / max(np.linalg.norm(new_coefficients), 1e-300)
            coefficients = new_coefficients
            standardized = (y - self.design @ coefficients) * np.sqrt(self.weights)
            sigma = MEDIAN_ABSOLUTE_DEVIATION_TO_SIGMA * np.median(np.abs(standardized))
            sigma = max(sigma, 1e-300)
            ratio = np.abs(standardized) / (params.delta_in_sigmas * sigma)
            h = np.where(ratio <= 1.0, 1.0, 1.0 / ratio)
            if change < params.convergence_tolerance:
                break
        residual = y - self.design @ coefficients
        rms = float(np.sqrt(np.average(residual ** 2, weights=self.weights * h)))
        edof = self.effective_degrees_of_freedom(gram, factor)
        return FastFitResult(coefficients, h, iterations, rms, edof)


class PoseFoldCrossValidator:
    """Held-out-pose cross-validation on a fixed design via per-fold Gram matrices."""

    def __init__(self, system: FixedDesignSystem, y: np.ndarray, fold: np.ndarray) -> None:
        self.system = system
        self.y = np.asarray(y, dtype=np.float64)
        self.fold = np.asarray(fold)
        self.folds = np.unique(self.fold)
        self.fold_gram, self.fold_rhs, self.fold_yy, self.fold_weight = {}, {}, {}, {}
        for k in self.folds:
            rows = np.nonzero(self.fold == k)[0]
            w = system.weights[rows]
            a = system.design[rows]
            self.fold_gram[k] = sp.csc_matrix((a.T @ sp.diags(w)) @ a)
            self.fold_rhs[k] = a.T @ (w * self.y[rows])
            self.fold_yy[k] = float(np.sum(w * self.y[rows] ** 2))
            self.fold_weight[k] = float(w.sum())
        self.total_rhs = sum(self.fold_rhs.values())

    def score(self, penalty: sp.spmatrix) -> float:
        """Weighted mean squared held-out residual, summed over folds, for one penalty."""
        total, weight = 0.0, 0.0
        for k in self.folds:
            gram_train = self.system.gram - self.fold_gram[k]
            rhs_train = self.total_rhs - self.fold_rhs[k]
            c = self.system.factor(gram_train, penalty).solve(rhs_train)
            # sum_test w (y - A c)^2 = y^T W y - 2 c^T A^T W y + c^T (A^T W A) c, all per fold.
            total += self.fold_yy[k] - 2.0 * float(c @ self.fold_rhs[k]) + float(c @ (self.fold_gram[k] @ c))
            weight += self.fold_weight[k]
        return total / weight
