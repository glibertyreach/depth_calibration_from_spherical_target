"""
One-dimensional B-spline basis on a clamped (open) knot vector.

What this module computes
-------------------------
BSplineBasis1D evaluates the B-spline basis functions of a given degree on a
clamped knot vector, their derivatives, and the P-spline difference penalty
(Eilers and Marx) on the coefficient vector.

Conventions
-----------
* The knot vector is full and clamped: the first degree + 1 knots are all equal
  to the lower bound and the last degree + 1 knots are all equal to the upper
  bound. Its length is n_coefficients + degree + 1.
* The domain is [lower, upper] = [knots[0], knots[-1]]. Inputs outside the
  domain are clamped to the nearest bound before evaluation, so the spline is
  constant-extrapolated in its input (not in its value for derivatives: the
  derivative at a clamped input is the boundary derivative).
* The knot span of an input x is the index i with knots[i] <= x < knots[i + 1],
  restricted to degree <= i <= n_coefficients - 1. An input exactly at the
  upper bound therefore uses the last span, so the basis is right-continuous
  everywhere and the partition of unity also holds at the upper bound.
* The degree + 1 nonzero basis values of a span are computed by the Cox-de Boor
  recursion (Piegl and Tiller, algorithm A2.2). This is exactly the evaluation
  rule of the JSON map format (design document section 7).
* design(x) is a sparse CSR matrix with exactly degree + 1 stored entries per
  row (some may be exactly zero, for example at a knot).
* Input values that are NaN propagate as NaN rows; callers filter them first.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

# Interior knots closer than this fraction of the domain width to a neighbor
# (or to a bound) are dropped by from_quantiles. This is a numerical guard
# against near-duplicate knots that arise from tied sample values; such knots
# would produce nearly empty spans and an ill-conditioned basis.
MINIMUM_KNOT_SEPARATION_FRACTION = 1e-9


class BSplineBasis1D:
    """B-spline basis of a given degree on a clamped knot vector.

    Attributes
    ----------
    degree : int
        Polynomial degree (3 is cubic).
    knots : np.ndarray
        Full clamped knot vector, length n_coefficients + degree + 1.
    """

    def __init__(self, degree: int, knots) -> None:
        degree = int(degree)
        knots = np.asarray(knots, dtype=np.float64)
        if degree < 0:
            raise ValueError("degree must be non-negative")
        if knots.ndim != 1:
            raise ValueError("knots must be a one-dimensional array")
        order = degree + 1  # number of equal knots required at each end
        if knots.size < 2 * order:
            raise ValueError(
                f"a degree-{degree} clamped knot vector needs at least {2 * order} knots"
            )
        if np.any(np.diff(knots) < 0):
            raise ValueError("knots must be non-decreasing")
        if not (np.all(knots[:order] == knots[0]) and np.all(knots[-order:] == knots[-1])):
            raise ValueError("knot vector must be clamped: degree + 1 equal knots at each end")
        if not knots[-1] > knots[0]:
            raise ValueError("upper bound must exceed lower bound")
        self.degree = degree
        self.knots = knots

    # ------------------------------------------------------------------ constructors

    @classmethod
    def uniform(cls, lower: float, upper: float, n_intervals: int, degree: int) -> "BSplineBasis1D":
        """Equally spaced interior knots giving n_intervals intervals on [lower, upper]."""
        n_intervals = int(n_intervals)
        if n_intervals < 1:
            raise ValueError("n_intervals must be at least 1")
        edges = np.linspace(lower, upper, n_intervals + 1)
        return cls.from_interior_knots(lower, upper, edges[1:-1], degree)

    @classmethod
    def from_interior_knots(cls, lower: float, upper: float, interior_knots, degree: int) -> "BSplineBasis1D":
        """Clamp the given interior knots with degree + 1 copies of each bound."""
        interior = np.sort(np.asarray(interior_knots, dtype=np.float64).reshape(-1))
        if interior.size and not (interior[0] > lower and interior[-1] < upper):
            raise ValueError("interior knots must lie strictly inside (lower, upper)")
        order = int(degree) + 1
        knots = np.concatenate([np.full(order, float(lower)), interior, np.full(order, float(upper))])
        return cls(degree, knots)

    @classmethod
    def from_quantiles(
        cls, samples, n_intervals: int, degree: int, lower: float | None = None, upper: float | None = None
    ) -> "BSplineBasis1D":
        """Interior knots at equally spaced quantiles of the samples.

        The domain defaults to the sample minimum and maximum. Only samples inside
        the domain contribute. Quantile knots that coincide (tied samples) or fall
        within MINIMUM_KNOT_SEPARATION_FRACTION of the domain width of a neighbor or
        a bound are dropped, so the result can have fewer than n_intervals intervals.
        """
        n_intervals = int(n_intervals)
        if n_intervals < 1:
            raise ValueError("n_intervals must be at least 1")
        values = np.asarray(samples, dtype=np.float64).reshape(-1)
        values = values[np.isfinite(values)]
        if values.size == 0:
            raise ValueError("no finite samples")
        lower = float(values.min()) if lower is None else float(lower)
        upper = float(values.max()) if upper is None else float(upper)
        if not upper > lower:
            raise ValueError("upper bound must exceed lower bound")
        values = values[(values >= lower) & (values <= upper)]
        if values.size == 0:
            raise ValueError("no samples inside [lower, upper]")
        levels = np.arange(1, n_intervals) / n_intervals
        candidates = np.quantile(values, levels)
        separation = MINIMUM_KNOT_SEPARATION_FRACTION * (upper - lower)
        kept: list[float] = []
        previous = lower
        for knot in candidates:
            if knot - previous > separation and upper - knot > separation:
                kept.append(float(knot))
                previous = knot
        return cls.from_interior_knots(lower, upper, kept, degree)

    # ------------------------------------------------------------------ properties

    @property
    def n_coefficients(self) -> int:
        """Number of basis functions (columns of the design matrix)."""
        return self.knots.size - self.degree - 1

    @property
    def lower(self) -> float:
        """Lower bound of the domain (first distinct knot)."""
        return float(self.knots[0])

    @property
    def upper(self) -> float:
        """Upper bound of the domain (last distinct knot)."""
        return float(self.knots[-1])

    # ------------------------------------------------------------------ evaluation

    def _prepare(self, x) -> tuple[np.ndarray, np.ndarray]:
        """Clamp x to the domain and find each value's knot span.

        Returns (clamped x, span index), both 1-D. The span index is the last
        index i with knots[i] <= x, limited to [degree, n_coefficients - 1], so
        x at the upper bound falls in the last span.
        """
        values = np.asarray(x, dtype=np.float64)
        if values.ndim > 1:
            raise ValueError("x must be a scalar or a one-dimensional array")
        values = np.atleast_1d(values)
        clamped = np.clip(values, self.lower, self.upper)
        span = np.searchsorted(self.knots, clamped, side="right") - 1
        span = np.clip(span, self.degree, self.n_coefficients - 1)
        return clamped, span

    def _nonzero_values(self, x: np.ndarray, span: np.ndarray) -> np.ndarray:
        """The degree + 1 nonzero basis values per input by the Cox-de Boor recursion.

        Column r of the result is the value of basis function (span - degree + r).
        The recursion builds the degree-j values from the degree-(j - 1) values,
        keeping the distances to the left and right knots (Piegl and Tiller A2.2).
        """
        n_values = x.size
        values = np.zeros((n_values, self.degree + 1))
        values[:, 0] = 1.0
        left = np.zeros((n_values, self.degree + 1))
        right = np.zeros((n_values, self.degree + 1))
        for j in range(1, self.degree + 1):
            left[:, j] = x - self.knots[span + 1 - j]
            right[:, j] = self.knots[span + j] - x
            saved = np.zeros(n_values)
            for r in range(j):
                # The denominator is a knot difference spanning the nonempty
                # span, so it is strictly positive.
                ratio = values[:, r] / (right[:, r + 1] + left[:, j - r])
                values[:, r] = saved + right[:, r + 1] * ratio
                saved = left[:, j - r] * ratio
            values[:, j] = saved
        return values

    def design(self, x) -> sp.csr_matrix:
        """Sparse design matrix B with B[i, j] = value of basis function j at x[i].

        Shape (N, n_coefficients) with exactly degree + 1 stored entries per row.
        Inputs outside [lower, upper] are clamped to the boundary.
        """
        clamped, span = self._prepare(x)
        values = self._nonzero_values(clamped, span)
        width = self.degree + 1
        columns = (span - self.degree)[:, None] + np.arange(width)[None, :]
        indptr = np.arange(clamped.size + 1) * width
        return sp.csr_matrix(
            (values.ravel(), columns.ravel(), indptr), shape=(clamped.size, self.n_coefficients)
        )

    def _derivative_operator(self, order: int) -> sp.csr_matrix:
        """Matrix M with (d^order/dx^order) sum_j c_j B_j = sum_k (M c)_k B'_k.

        B' are the basis functions of degree (degree - order) on the knot vector
        with `order` knots removed from each end. One differentiation step maps the
        coefficients c (degree q, knots t) to q * (c[j + 1] - c[j]) / (t[j + q + 1]
        - t[j + 1]); a zero denominator contributes zero (the 0/0 = 0 convention).
        """
        operator = sp.identity(self.n_coefficients, format="csr")
        for step in range(order):
            current_degree = self.degree - step
            current_knots = self.knots[step : self.knots.size - step]
            n_current = current_knots.size - current_degree - 1
            j = np.arange(n_current - 1)
            denominators = current_knots[j + current_degree + 1] - current_knots[j + 1]
            factors = np.zeros(n_current - 1)
            np.divide(current_degree, denominators, out=factors, where=denominators > 0)
            difference = sp.diags([-factors, factors], [0, 1], shape=(n_current - 1, n_current))
            operator = difference @ operator
        return operator.tocsr()

    def design_derivative(self, x, order: int = 1) -> sp.csr_matrix:
        """Sparse matrix of the order-th derivatives of the basis functions at x.

        Shape (N, n_coefficients). Inputs are clamped as in design(), so outside the
        domain the result is the boundary derivative. order 0 equals design(); an
        order above the degree gives an all-zero matrix.
        """
        order = int(order)
        if order < 0:
            raise ValueError("order must be non-negative")
        if order == 0:
            return self.design(x)
        clamped, _ = self._prepare(x)
        if order > self.degree:
            return sp.csr_matrix((clamped.size, self.n_coefficients))
        reduced = BSplineBasis1D(self.degree - order, self.knots[order : self.knots.size - order])
        return (reduced.design(clamped) @ self._derivative_operator(order)).tocsr()

    # ------------------------------------------------------------------ penalty

    def difference_operator(self, order: int) -> sp.csr_matrix:
        """The order-th finite-difference operator D acting on the coefficient vector.

        Shape (max(n_coefficients - order, 0), n_coefficients); order 0 is the identity.
        """
        order = int(order)
        if order < 0:
            raise ValueError("order must be non-negative")
        operator = sp.identity(self.n_coefficients, format="csr")
        for _ in range(order):
            operator = (operator[1:] - operator[:-1]).tocsr()
        return operator

    def difference_penalty(self, order: int) -> sp.csr_matrix:
        """P-spline penalty D^T D (Eilers and Marx), shape (n_coefficients, n_coefficients).

        c^T (D^T D) c is the squared norm of the order-th differences of the
        coefficients. Its null space is the polynomials of degree below `order`
        (constants and linear sequences for order 2).
        """
        operator = self.difference_operator(order)
        return (operator.T @ operator).tocsr()

    def __repr__(self) -> str:
        return (
            f"BSplineBasis1D(degree={self.degree}, n_coefficients={self.n_coefficients}, "
            f"domain=[{self.lower}, {self.upper}])"
        )
