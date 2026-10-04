"""Tests of BSplineBasis1D: partition of unity, derivatives, clamping, penalty, constructors."""
import numpy as np
import pytest
import scipy.sparse as sp
from scipy.interpolate import BSpline

from sphcal.spline.basis import BSplineBasis1D

RANDOM_SEED = 12345  # seed of every random draw in this file
N_RANDOM_POINTS = 200  # random evaluation points per test
DEGREES = (1, 2, 3, 4)  # degrees exercised by the parametrized tests
LOWER = -2.0  # lower bound of the test domain
UPPER = 3.0  # upper bound of the test domain
N_INTERVALS = 7  # intervals of the test bases
UNIT_TOLERANCE = 1e-12  # tolerance for identities that hold to rounding
FIRST_DIFFERENCE_STEP = 1e-6  # step of the central first difference
SECOND_DIFFERENCE_STEP = 1e-3  # step of the central second difference (larger: rounding grows as 1 / step^2)
KNOT_AVOIDANCE_STEPS = 3  # sample points must be at least this many steps from any knot and bound
DERIVATIVE_TOLERANCE = 1e-5  # allowed derivative mismatch relative to the scale of the derivative
DERIVATIVE_SUM_TOLERANCE = 1e-9  # the derivative of a partition of unity sums to zero up to rounding
OUTSIDE_DISTANCE = 4.0  # how far outside the domain the clamping tests probe
INTERIOR_KNOTS = (-1.3, -0.2, 0.1, 1.7)  # an irregular interior knot set
SMOOTH_SAMPLE_COUNT = 500  # samples for the quantile-knot test


def make_bases():
    """One uniform and one irregular basis for every degree."""
    bases = []
    for degree in DEGREES:
        bases.append(BSplineBasis1D.uniform(LOWER, UPPER, N_INTERVALS, degree))
        bases.append(BSplineBasis1D.from_interior_knots(LOWER, UPPER, INTERIOR_KNOTS, degree))
    return bases


@pytest.mark.parametrize("basis", make_bases(), ids=repr)
def test_partition_of_unity_random_and_bounds(basis):
    rng = np.random.default_rng(RANDOM_SEED)
    x = np.concatenate([rng.uniform(LOWER, UPPER, N_RANDOM_POINTS), [LOWER, UPPER]])
    design = basis.design(x)
    assert design.shape == (x.size, basis.n_coefficients)
    np.testing.assert_allclose(design.sum(axis=1).A.ravel(), 1.0, atol=UNIT_TOLERANCE)
    assert design.data.min() >= -UNIT_TOLERANCE  # basis functions are non-negative


@pytest.mark.parametrize("basis", make_bases(), ids=repr)
def test_design_is_csr_with_degree_plus_one_entries_per_row(basis):
    x = np.random.default_rng(RANDOM_SEED).uniform(LOWER, UPPER, N_RANDOM_POINTS)
    design = basis.design(x)
    assert sp.isspmatrix_csr(design)
    np.testing.assert_array_equal(np.diff(design.indptr), basis.degree + 1)


@pytest.mark.parametrize("basis", make_bases(), ids=repr)
def test_matches_scipy_bspline(basis):
    """Cross-check the hand-written Cox-de Boor recursion against scipy."""
    x = np.random.default_rng(RANDOM_SEED).uniform(LOWER, UPPER, N_RANDOM_POINTS)
    x = np.concatenate([x, [LOWER, UPPER]])
    reference = BSpline.design_matrix(x, basis.knots, basis.degree)
    np.testing.assert_allclose(basis.design(x).toarray(), reference.toarray(), atol=UNIT_TOLERANCE)


def test_upper_bound_uses_last_span():
    basis = BSplineBasis1D.uniform(LOWER, UPPER, N_INTERVALS, 3)
    row = basis.design([UPPER]).toarray().ravel()
    assert row[-1] == pytest.approx(1.0)  # the last function is 1 at the upper bound
    assert np.count_nonzero(row) == 1
    row = basis.design([LOWER]).toarray().ravel()
    assert row[0] == pytest.approx(1.0)


@pytest.mark.parametrize("basis", make_bases(), ids=repr)
@pytest.mark.parametrize("order", (1, 2))
def test_derivative_against_central_differences(basis, order):
    if order > basis.degree:
        pytest.skip("derivative of this order is identically zero")
    rng = np.random.default_rng(RANDOM_SEED)
    step = FIRST_DIFFERENCE_STEP if order == 1 else SECOND_DIFFERENCE_STEP
    x = rng.uniform(LOWER + KNOT_AVOIDANCE_STEPS * step, UPPER - KNOT_AVOIDANCE_STEPS * step, N_RANDOM_POINTS)
    # Keep the stencil inside one knot span: a piecewise polynomial is differentiated
    # exactly by a central difference only if no knot lies within the stencil.
    knot_distance = np.min(np.abs(x[:, None] - basis.knots[None, :]), axis=1)
    x = x[knot_distance > KNOT_AVOIDANCE_STEPS * step]
    if order == 1:
        numeric = (basis.design(x + step) - basis.design(x - step)) / (2 * step)
    else:
        numeric = (basis.design(x + step) - 2 * basis.design(x) + basis.design(x - step)) / step**2
    analytic = basis.design_derivative(x, order)
    scale = max(1.0, np.abs(analytic.toarray()).max())
    assert np.abs((analytic - numeric).toarray()).max() <= DERIVATIVE_TOLERANCE * scale


def test_derivative_of_partition_of_unity_is_zero_and_order_zero_is_design():
    basis = BSplineBasis1D.uniform(LOWER, UPPER, N_INTERVALS, 3)
    x = np.random.default_rng(RANDOM_SEED).uniform(LOWER, UPPER, N_RANDOM_POINTS)
    for order in (1, 2, 3):
        np.testing.assert_allclose(basis.design_derivative(x, order).sum(axis=1).A.ravel(), 0.0, atol=DERIVATIVE_SUM_TOLERANCE)
    assert (basis.design_derivative(x, 0) - basis.design(x)).count_nonzero() == 0
    assert basis.design_derivative(x, 4).count_nonzero() == 0  # above the degree


def test_clamping_outside_the_domain():
    basis = BSplineBasis1D.uniform(LOWER, UPPER, N_INTERVALS, 3)
    below = basis.design([LOWER - OUTSIDE_DISTANCE, LOWER]).toarray()
    above = basis.design([UPPER + OUTSIDE_DISTANCE, UPPER]).toarray()
    np.testing.assert_array_equal(below[0], below[1])
    np.testing.assert_array_equal(above[0], above[1])
    # The derivative at a clamped input is the boundary derivative.
    d = basis.design_derivative([LOWER - OUTSIDE_DISTANCE, LOWER, UPPER, UPPER + OUTSIDE_DISTANCE]).toarray()
    np.testing.assert_allclose(d[0], d[1], atol=UNIT_TOLERANCE)
    np.testing.assert_allclose(d[2], d[3], atol=UNIT_TOLERANCE)


def test_difference_penalty_matches_dense_differences_and_null_space():
    basis = BSplineBasis1D.uniform(LOWER, UPPER, N_INTERVALS, 3)
    n = basis.n_coefficients
    for order in (0, 1, 2, 3):
        dense_difference = np.diff(np.eye(n), n=order, axis=0)
        penalty = basis.difference_penalty(order)
        np.testing.assert_allclose(penalty.toarray(), dense_difference.T @ dense_difference, atol=UNIT_TOLERANCE)
    penalty = basis.difference_penalty(2)
    index = np.arange(n, dtype=float)
    assert abs(np.ones(n) @ (penalty @ np.ones(n))) < UNIT_TOLERANCE
    assert abs(index @ (penalty @ index)) < UNIT_TOLERANCE  # linear sequences are unpenalized
    assert index**2 @ (penalty @ index**2) > 0
    assert basis.difference_penalty(n + 1).count_nonzero() == 0  # order beyond the size: no penalty


def test_constructors():
    uniform = BSplineBasis1D.uniform(LOWER, UPPER, N_INTERVALS, 3)
    assert uniform.n_coefficients == N_INTERVALS + 3
    assert uniform.knots.size == uniform.n_coefficients + 3 + 1
    assert (uniform.lower, uniform.upper) == (LOWER, UPPER)
    samples = np.random.default_rng(RANDOM_SEED).normal(size=SMOOTH_SAMPLE_COUNT)
    quantile = BSplineBasis1D.from_quantiles(samples, N_INTERVALS, 3)
    assert quantile.n_coefficients == N_INTERVALS + 3
    assert quantile.lower == samples.min() and quantile.upper == samples.max()
    # Equal numbers of samples in every interval (within one) for quantile knots.
    counts = np.histogram(samples, bins=np.unique(quantile.knots))[0]
    assert counts.max() - counts.min() <= 2
    tied = BSplineBasis1D.from_quantiles(np.repeat([0.0, 1.0], 50), 4, 3)
    assert tied.n_coefficients < 4 + 3  # tied samples collapse the knots
    with pytest.raises(ValueError):
        BSplineBasis1D.from_interior_knots(LOWER, UPPER, [UPPER + 1.0], 3)
    with pytest.raises(ValueError):
        BSplineBasis1D(3, [0.0, 0.0, 1.0, 1.0])  # too short and not clamped for degree 3
    with pytest.raises(ValueError):
        BSplineBasis1D.uniform(LOWER, UPPER, 0, 3)
