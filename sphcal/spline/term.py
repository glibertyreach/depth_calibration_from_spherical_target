"""
Tensor-product B-spline term.

What this module computes
-------------------------
A TensorTerm is one additive component of the correction map: a function of a
subset of the model inputs, represented as a tensor product of 1-D B-spline
bases (one per input dimension of the term) with a coefficient array.

Conventions
-----------
* The term's coefficients are flattened row-major over its dimensions: the first
  input dimension of the term varies slowest, the last fastest. The flat index
  of coefficient (i_0, i_1, ..., i_{D-1}) is ((i_0 * n_1 + i_1) * n_2 + i_2) ...
* design(X) is the row-wise Kronecker product of the 1-D designs, so a row has
  prod(degree_d + 1) stored entries (16 for a 2-D cubic term, 64 for a 3-D one).
  This grows quickly with the number of dimensions; high-dimensional terms need
  many rows' worth of memory (rows * prod(degree_d + 1) entries).
* The penalty is the anisotropic P-spline penalty: the sum over dimensions d of
  smoothing[d] * kron(I, ..., D_d^T D_d, ..., I), where D_d is the difference
  operator of order penalty_order along dimension d.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp

from .basis import BSplineBasis1D

# Default P-spline difference order (second differences penalize curvature).
DEFAULT_PENALTY_ORDER = 2

# Default smoothing parameter of every dimension before a fit selects it.
DEFAULT_SMOOTHING = 1.0


@dataclass
class TensorTerm:
    """Tensor-product B-spline term over a subset of the model inputs.

    Attributes
    ----------
    name : str
        Identifier of the term (for example "position").
    input_indices : tuple[int, ...]
        Columns of the full input matrix X used by this term, one per basis.
    bases : list[BSplineBasis1D]
        One 1-D basis per input dimension of the term.
    penalty_order : int
        Order of the difference penalty along each dimension.
    smoothing : list[float]
        One non-negative smoothing parameter per dimension. Empty means all
        DEFAULT_SMOOTHING.
    """

    name: str
    input_indices: tuple
    bases: list
    penalty_order: int = DEFAULT_PENALTY_ORDER
    smoothing: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.input_indices = tuple(int(i) for i in self.input_indices)
        self.bases = list(self.bases)
        if len(self.input_indices) != len(self.bases) or not self.bases:
            raise ValueError("a term needs one basis per input index, and at least one")
        if not self.smoothing:
            self.smoothing = [DEFAULT_SMOOTHING] * len(self.bases)
        self.smoothing = [float(s) for s in self.smoothing]
        if len(self.smoothing) != len(self.bases):
            raise ValueError("a term needs one smoothing parameter per dimension")
        if any(s < 0 for s in self.smoothing):
            raise ValueError("smoothing parameters must be non-negative")

    @property
    def dimension_sizes(self) -> list:
        """Number of coefficients along each dimension."""
        return [basis.n_coefficients for basis in self.bases]

    @property
    def n_coefficients(self) -> int:
        """Total coefficient count: the product of the per-dimension counts."""
        return math.prod(self.dimension_sizes)

    def design(self, X) -> sp.csr_matrix:
        """Row-wise Kronecker product of the 1-D designs, shape (N, n_coefficients).

        X is the full input matrix (N, n_inputs); this term reads the columns in
        input_indices. Values outside a basis's domain are clamped by that basis.
        """
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2:
            raise ValueError("X must be a two-dimensional array (samples, inputs)")
        if max(self.input_indices) >= X.shape[1]:
            raise ValueError("X has fewer columns than the term's input indices require")
        n_rows = X.shape[0]
        columns = None  # (N, width) coefficient indices of the entries of each row
        values = None  # (N, width) their values
        for basis, input_index in zip(self.bases, self.input_indices):
            one_d = basis.design(X[:, input_index])
            width = basis.degree + 1
            # Every row of a 1-D design has exactly `width` stored entries in
            # ascending column order, so the arrays reshape to (N, width).
            one_d_columns = one_d.indices.reshape(n_rows, width).astype(np.int64)
            one_d_values = one_d.data.reshape(n_rows, width)
            if columns is None:
                columns, values = one_d_columns, one_d_values
            else:
                # Row-major: the new dimension varies fastest.
                columns = (columns[:, :, None] * basis.n_coefficients + one_d_columns[:, None, :]).reshape(n_rows, -1)
                values = (values[:, :, None] * one_d_values[:, None, :]).reshape(n_rows, -1)
        width = columns.shape[1]
        indptr = np.arange(n_rows + 1) * width
        return sp.csr_matrix(
            (values.ravel(), columns.ravel(), indptr), shape=(n_rows, self.n_coefficients)
        )

    def dimension_penalties(self) -> list:
        """Per-dimension penalties with unit smoothing, each (n_coefficients, n_coefficients).

        Entry d is kron(I, ..., D_d^T D_d, ..., I) with identities of the sizes of
        the dimensions before and after d.
        """
        sizes = self.dimension_sizes
        penalties = []
        for d, basis in enumerate(self.bases):
            before = sp.identity(math.prod(sizes[:d]), format="csr")
            after = sp.identity(math.prod(sizes[d + 1 :]), format="csr")
            along = basis.difference_penalty(self.penalty_order)
            penalties.append(sp.kron(sp.kron(before, along), after, format="csr"))
        return penalties

    def penalty(self) -> sp.csr_matrix:
        """Sum over dimensions of smoothing[d] * kron(I, ..., D_d^T D_d, ..., I)."""
        total = sp.csr_matrix((self.n_coefficients, self.n_coefficients))
        for weight, penalty in zip(self.smoothing, self.dimension_penalties()):
            total = total + weight * penalty
        return total.tocsr()

    def evaluate(self, X, coefficients) -> np.ndarray:
        """Term value at each row of X for the given coefficients, shape (N,)."""
        coefficients = np.asarray(coefficients, dtype=np.float64)
        if coefficients.shape != (self.n_coefficients,):
            raise ValueError(
                f"expected {self.n_coefficients} coefficients, got shape {coefficients.shape}"
            )
        return self.design(X) @ coefficients
