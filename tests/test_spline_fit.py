"""Tests of the penalized, robust, logistic and GCV fits."""
import dataclasses

import numpy as np
import pytest

from sphcal.spline.basis import BSplineBasis1D
from sphcal.spline.fit import (
    LogisticParameters,
    RobustParameters,
    SmoothingGrid,
    SolverOptions,
    fit_logistic,
    fit_penalized_least_squares,
    fit_robust,
    search_smoothing_by_gcv,
    select_smoothing_by_gcv,
)
from sphcal.spline.model import InputSpec, SumOfTermsSpline
from sphcal.spline.term import TensorTerm

RANDOM_SEED = 777  # seed of every random draw in this file
DEGREE = 3  # cubic bases
N_INTERVALS = 20  # intervals of the 1-D regression basis
N_TRAIN = 500  # training samples of the regression tests
N_TEST = 2000  # held-out samples
NOISE_SIGMA = 0.2  # standard deviation of the Gaussian noise
FIT_SMOOTHING = 1.0  # smoothing used where no search is done
SOLVER_AGREEMENT_TOLERANCE = 1e-6  # relative agreement of the direct and iterative solutions
HUTCHINSON_PROBES = 400  # probes of the stochastic trace in the accuracy test
DEFAULT_PROBES_RELATIVE_TOLERANCE = 0.3  # accuracy expected of the stochastic edof with the default probe count
HUTCHINSON_RELATIVE_TOLERANCE = 0.1  # accuracy required of the stochastic edof
OUTLIER_FRACTION = 0.1  # fraction of contaminated samples in the robust test
OUTLIER_SHIFT = 5.0  # size of the outliers (25 sigma)
ROBUST_IMPROVEMENT_FACTOR = 3.0  # the robust error must be this many times smaller than the plain one
LOGISTIC_SAMPLES = 5000  # samples of the logistic test
LOGISTIC_INTERCEPT = -3.0  # true logit is intercept + slope * x
LOGISTIC_SLOPE = 6.0
LOGISTIC_SLOPE_TOLERANCE = 0.2  # allowed relative slope error
LOGISTIC_INTERVALS = 5  # intervals of the logistic basis
LOGISTIC_PROBE_LOW, LOGISTIC_PROBE_HIGH = 0.2, 0.8  # interior interval where the slope is checked
GCV_FACTOR = 1.5  # GCV-selected held-out RMS must be within this factor of the best grid value
GCV_GRID = SmoothingGrid(log10_min=-4.0, log10_max=4.0, n_values=9, n_rounds=2)
GCV_TRAIN = 300
EDOF_TOLERANCE = 1e-6  # tolerance of edof identities


def truth(x):
    return np.sin(2 * np.pi * x) + 0.5 * x


def make_model(smoothing=FIT_SMOOTHING, n_intervals=N_INTERVALS):
    basis = BSplineBasis1D.uniform(0.0, 1.0, n_intervals, DEGREE)
    return SumOfTermsSpline([InputSpec("x", 0.0, 1.0, "unit")], [TensorTerm("f", (0,), [basis], smoothing=[smoothing])])


def noisy_data(rng, n=N_TRAIN, sigma=NOISE_SIGMA):
    x = rng.uniform(0.0, 1.0, n)
    return x[:, None], truth(x) + rng.normal(0.0, sigma, n)


def test_penalized_fit_recovers_function_below_noise_level():
    rng = np.random.default_rng(RANDOM_SEED)
    X, y = noisy_data(rng)
    model = make_model()
    fit = fit_penalized_least_squares(model.design(X), y, np.ones(N_TRAIN), model.penalty())
    model.coefficients = fit.coefficients
    grid = np.linspace(0.0, 1.0, N_TEST)[:, None]
    error_rms = np.sqrt(np.mean((model.evaluate(grid) - truth(grid[:, 0])) ** 2))
    assert error_rms < NOISE_SIGMA
    assert fit.residual_rms == pytest.approx(NOISE_SIGMA, rel=0.2)
    assert 2 < fit.effective_degrees_of_freedom < model.n_coefficients
    assert fit.solver_used == "direct"


def test_diagnostics_definitions():
    rng = np.random.default_rng(RANDOM_SEED)
    X, y = noisy_data(rng)
    w = rng.uniform(0.5, 2.0, N_TRAIN)
    model = make_model()
    A, P = model.design(X), model.penalty()
    fit = fit_penalized_least_squares(A, y, w, P)
    r = y - A @ fit.coefficients
    assert fit.residual_rms == pytest.approx(np.sqrt(np.sum(w * r**2) / np.sum(w)))
    n, edof = N_TRAIN, fit.effective_degrees_of_freedom
    assert fit.gcv_score == pytest.approx(n * np.sum(w * r**2) / (n - edof) ** 2)
    # Dense reference: edof = trace of the hat matrix, and the weighted normal equations.
    Ad, Pd = A.toarray(), P.toarray()
    M = Ad.T @ (w[:, None] * Ad) + Pd
    np.testing.assert_allclose(fit.coefficients, np.linalg.solve(M, Ad.T @ (w * y)), rtol=SOLVER_AGREEMENT_TOLERANCE, atol=SOLVER_AGREEMENT_TOLERANCE)
    assert edof == pytest.approx(np.trace(np.linalg.solve(M, Ad.T @ (w[:, None] * Ad))), abs=EDOF_TOLERANCE)


def test_edof_limits_with_smoothing():
    rng = np.random.default_rng(RANDOM_SEED)
    X, y = noisy_data(rng)
    weak, strong = make_model(smoothing=1e-8), make_model(smoothing=1e8)
    ones = np.ones(N_TRAIN)
    weak_fit = fit_penalized_least_squares(weak.design(X), y, ones, weak.penalty())
    strong_fit = fit_penalized_least_squares(strong.design(X), y, ones, strong.penalty())
    assert weak_fit.effective_degrees_of_freedom == pytest.approx(weak.n_coefficients, abs=0.1)
    assert strong_fit.effective_degrees_of_freedom == pytest.approx(2.0, abs=0.1)  # a line is unpenalized


def test_zero_weight_samples_are_ignored():
    rng = np.random.default_rng(RANDOM_SEED)
    X, y = noisy_data(rng)
    model = make_model()
    A, P = model.design(X), model.penalty()
    w = np.ones(N_TRAIN)
    w[::2] = 0.0
    full = fit_penalized_least_squares(A, y, w, P)
    kept = fit_penalized_least_squares(A[1::2], y[1::2], np.ones(N_TRAIN // 2), P)
    np.testing.assert_allclose(full.coefficients, kept.coefficients, atol=SOLVER_AGREEMENT_TOLERANCE)
    assert full.gcv_score == pytest.approx(kept.gcv_score)


def test_iterative_solver_matches_direct_and_auto_selection():
    rng = np.random.default_rng(RANDOM_SEED)
    X, y = noisy_data(rng)
    model = make_model()
    A, P, w = model.design(X), model.penalty(), np.ones(N_TRAIN)
    direct = fit_penalized_least_squares(A, y, w, P, solver="direct")
    iterative = fit_penalized_least_squares(A, y, w, P, solver="iterative")
    assert iterative.solver_used == "iterative" and iterative.converged
    np.testing.assert_allclose(iterative.coefficients, direct.coefficients, rtol=SOLVER_AGREEMENT_TOLERANCE, atol=SOLVER_AGREEMENT_TOLERANCE)
    # auto: direct up to the threshold, iterative above it.
    below = fit_penalized_least_squares(A, y, w, P, options=SolverOptions(direct_max_coefficients=model.n_coefficients))
    above = fit_penalized_least_squares(A, y, w, P, options=SolverOptions(direct_max_coefficients=model.n_coefficients - 1))
    assert below.solver_used == "direct" and above.solver_used == "iterative"
    # The stochastic edof (used for iterative solves) is close to the exact one.
    assert iterative.effective_degrees_of_freedom == pytest.approx(
        direct.effective_degrees_of_freedom, rel=DEFAULT_PROBES_RELATIVE_TOLERANCE
    )
    stochastic = fit_penalized_least_squares(
        A, y, w, P, solver="direct", options=SolverOptions(exact_trace_max_coefficients=0, hutchinson_probes=HUTCHINSON_PROBES)
    )
    assert stochastic.effective_degrees_of_freedom == pytest.approx(
        direct.effective_degrees_of_freedom, rel=HUTCHINSON_RELATIVE_TOLERANCE
    )


def test_invalid_inputs_are_rejected():
    model = make_model()
    X = np.linspace(0, 1, 10)[:, None]
    A, P = model.design(X), model.penalty()
    with pytest.raises(ValueError):
        fit_penalized_least_squares(A, np.zeros(9), np.ones(10), P)
    with pytest.raises(ValueError):
        fit_penalized_least_squares(A, np.zeros(10), -np.ones(10), P)
    with pytest.raises(ValueError):
        fit_penalized_least_squares(A, np.zeros(10), np.ones(10), P, solver="nope")


def test_robust_fit_resists_outliers():
    rng = np.random.default_rng(RANDOM_SEED)
    X, y = noisy_data(rng)
    outliers = rng.random(N_TRAIN) < OUTLIER_FRACTION
    y = y + outliers * rng.choice([-OUTLIER_SHIFT, OUTLIER_SHIFT], N_TRAIN)
    model = make_model()
    A, P, w = model.design(X), model.penalty(), np.ones(N_TRAIN)
    grid = np.linspace(0.0, 1.0, N_TEST)[:, None]

    def error_of(result):
        model.coefficients = result.coefficients
        return np.sqrt(np.mean((model.evaluate(grid) - truth(grid[:, 0])) ** 2))

    plain = fit_penalized_least_squares(A, y, w, P)
    robust = fit_robust(A, y, w, P, RobustParameters())
    assert error_of(robust) < NOISE_SIGMA
    assert error_of(robust) * ROBUST_IMPROVEMENT_FACTOR < error_of(plain)
    assert robust.weights[outliers].mean() < robust.weights[~outliers].mean()
    assert 1 <= robust.iterations <= RobustParameters().max_iterations
    assert RobustParameters().huber_delta_in_sigmas == 2.5 and RobustParameters().max_iterations == 10
    assert RobustParameters().convergence_tolerance == 1e-4


def test_robust_equals_plain_fit_on_clean_data_with_huge_delta():
    rng = np.random.default_rng(RANDOM_SEED)
    X, y = noisy_data(rng)
    model = make_model()
    A, P, w = model.design(X), model.penalty(), np.ones(N_TRAIN)
    plain = fit_penalized_least_squares(A, y, w, P)
    huge_delta = dataclasses.replace(RobustParameters(), huber_delta_in_sigmas=1e6)
    robust = fit_robust(A, y, w, P, huge_delta)
    np.testing.assert_allclose(robust.coefficients, plain.coefficients, atol=SOLVER_AGREEMENT_TOLERANCE)
    assert robust.converged


def test_logistic_fit_recovers_known_logit():
    rng = np.random.default_rng(RANDOM_SEED)
    x = rng.uniform(0.0, 1.0, LOGISTIC_SAMPLES)
    probability = 1.0 / (1.0 + np.exp(-(LOGISTIC_INTERCEPT + LOGISTIC_SLOPE * x)))
    y = (rng.random(LOGISTIC_SAMPLES) < probability).astype(float)
    basis = BSplineBasis1D.uniform(0.0, 1.0, LOGISTIC_INTERVALS, DEGREE)
    penalty = basis.difference_penalty(2) * FIT_SMOOTHING
    fit = fit_logistic(basis.design(x), y, np.ones(LOGISTIC_SAMPLES), penalty, LogisticParameters())
    assert fit.converged
    probe = np.linspace(LOGISTIC_PROBE_LOW, LOGISTIC_PROBE_HIGH, N_TEST)
    slope = np.mean(basis.design_derivative(probe) @ fit.coefficients)
    assert slope > 0
    assert slope == pytest.approx(LOGISTIC_SLOPE, rel=LOGISTIC_SLOPE_TOLERANCE)
    logit = basis.design(np.array([0.0, 1.0])) @ fit.coefficients
    assert logit[0] < 0 < logit[1]  # sign of the logit at the two ends
    assert logit[0] == pytest.approx(LOGISTIC_INTERCEPT, abs=1.0)
    assert LogisticParameters().max_iterations == 25 and LogisticParameters().probability_clip == 1e-6
    assert LogisticParameters().convergence_tolerance == 1e-6
    assert fit.effective_degrees_of_freedom > 2 and np.isfinite(fit.gcv_score)


def test_logistic_fit_handles_separable_data():
    x = np.linspace(0.0, 1.0, 200)
    y = (x > 0.5).astype(float)  # perfectly separable: only the penalty and step halving keep it finite
    basis = BSplineBasis1D.uniform(0.0, 1.0, LOGISTIC_INTERVALS, DEGREE)
    fit = fit_logistic(basis.design(x), y, np.ones(x.size), basis.difference_penalty(2) * FIT_SMOOTHING)
    assert np.all(np.isfinite(fit.coefficients))
    assert (basis.design(np.array([0.1, 0.9])) @ fit.coefficients)[0] < 0


def test_gcv_selection_is_near_the_best_held_out_grid_value():
    rng = np.random.default_rng(RANDOM_SEED)
    X, y = noisy_data(rng, n=GCV_TRAIN)
    X_test = np.linspace(0.0, 1.0, N_TEST)[:, None]
    ones = np.ones(GCV_TRAIN)

    def held_out_rms(model):
        return np.sqrt(np.mean((model.evaluate(X_test) - truth(X_test[:, 0])) ** 2))

    errors = []
    for log10_value in np.linspace(GCV_GRID.log10_min, GCV_GRID.log10_max, GCV_GRID.n_values):
        model = make_model(smoothing=10.0**log10_value)
        model.coefficients = fit_penalized_least_squares(model.design(X), y, ones, model.penalty()).coefficients
        errors.append(held_out_rms(model))
    selected = select_smoothing_by_gcv(make_model(), X, y, ones, GCV_GRID)
    assert held_out_rms(selected) <= GCV_FACTOR * min(errors)
    assert held_out_rms(selected) < NOISE_SIGMA
    # The input model is untouched and the result carries the selected smoothing.
    original = make_model()
    assert original.terms[0].smoothing == [FIT_SMOOTHING]
    assert selected.terms[0].smoothing[0] in 10.0 ** np.linspace(GCV_GRID.log10_min, GCV_GRID.log10_max, GCV_GRID.n_values)


def test_gcv_search_scales_term_dimensions_together_and_minimizes_score():
    rng = np.random.default_rng(RANDOM_SEED)
    x = rng.uniform(0.0, 1.0, (GCV_TRAIN, 2))
    y = np.sin(2 * np.pi * x[:, 0]) * np.cos(np.pi * x[:, 1]) + rng.normal(0.0, NOISE_SIGMA, GCV_TRAIN)
    basis = lambda: BSplineBasis1D.uniform(0.0, 1.0, 6, DEGREE)
    inputs = [InputSpec("a", 0.0, 1.0, "u"), InputSpec("b", 0.0, 1.0, "u")]
    term = TensorTerm("ab", (0, 1), [basis(), basis()], smoothing=[1.0, 4.0])
    model = SumOfTermsSpline(inputs, [term])
    result = search_smoothing_by_gcv(model, x, y, np.ones(GCV_TRAIN), GCV_GRID)
    smoothing = result.model.terms[0].smoothing
    assert smoothing[1] / smoothing[0] == pytest.approx(4.0)  # the ratio is kept
    assert smoothing[0] == pytest.approx(10.0 ** result.log10_multipliers[0])
    # No other grid value has a lower GCV score.
    for log10_value in np.linspace(GCV_GRID.log10_min, GCV_GRID.log10_max, GCV_GRID.n_values):
        trial = model.copy()
        trial.terms[0].smoothing = [10.0**log10_value, 4.0 * 10.0**log10_value]
        score = fit_penalized_least_squares(trial.design(x), y, np.ones(GCV_TRAIN), trial.penalty()).gcv_score
        assert result.fit.gcv_score <= score * (1 + EDOF_TOLERANCE)
    np.testing.assert_allclose(result.model.coefficients, result.fit.coefficients)
