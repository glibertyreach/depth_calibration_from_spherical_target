"""Tests of TensorTerm and SumOfTermsSpline: designs, penalties, recovery, JSON round trip."""
import json
import math

import numpy as np
import pytest
import scipy.sparse as sp

from sphcal.spline.basis import BSplineBasis1D
from sphcal.spline.fit import fit_penalized_least_squares
from sphcal.spline.model import FORMAT_NAME, FORMAT_VERSION, InputSpec, SumOfTermsSpline
from sphcal.spline.term import TensorTerm

RANDOM_SEED = 2024  # seed of every random draw in this file
N_TRAIN = 3000  # training samples of the 2-D recovery test
N_TEST = 2000  # held-out samples of the 2-D recovery test
RECOVERY_INTERVALS = 8  # intervals per dimension in the recovery test ("modest knots")
RECOVERY_TOLERANCE = 1e-2  # required held-out RMS error of the recovery test
RECOVERY_SMOOTHING = 1e-6  # very light smoothing: the data are noise free
EXACT_TOLERANCE = 1e-12  # tolerance for identities that hold to rounding
N_ROUND_TRIP_POINTS = 300  # evaluation points of the JSON round-trip test
OUTSIDE_MARGIN = 0.5  # fraction of the domain width by which round-trip points leave the domain
UPPER_BOUND_X = 3.0  # upper bound of every test input
LOWER_BOUND_X = -1.0  # lower bound of every test input
SMOOTHING_VALUES = [0.7, 2.5, 11.0]  # distinct per-dimension smoothing values
DEGREE = 3  # cubic bases


def make_basis(n_intervals, degree=DEGREE):
    return BSplineBasis1D.uniform(LOWER_BOUND_X, UPPER_BOUND_X, n_intervals, degree)


def make_inputs(n):
    return [InputSpec(f"x{i}", LOWER_BOUND_X, UPPER_BOUND_X, "unit") for i in range(n)]


def make_model(rng):
    """Three terms over four inputs with different dimensionality and degree, random coefficients."""
    terms = [
        TensorTerm("one", (2,), [make_basis(5, 2)]),
        TensorTerm("two", (0, 3), [make_basis(4), make_basis(3)], smoothing=[1.5, 0.25]),
        TensorTerm("three", (1, 0, 2), [make_basis(2), make_basis(3), make_basis(2)], penalty_order=1),
    ]
    model = SumOfTermsSpline(make_inputs(4), terms, metadata={"unit_id": "test", "nested": {"a": [1, 2.5, None]}})
    model.coefficients = rng.normal(size=model.n_coefficients)
    return model


def test_term_design_matches_explicit_kronecker_with_row_major_order():
    rng = np.random.default_rng(RANDOM_SEED)
    bases = [make_basis(4), make_basis(3), make_basis(2, 2)]
    term = TensorTerm("t", (1, 0, 2), bases)
    assert term.n_coefficients == math.prod(b.n_coefficients for b in bases)
    X = rng.uniform(LOWER_BOUND_X, UPPER_BOUND_X, size=(50, 3))
    design = term.design(X)
    assert sp.isspmatrix_csr(design)
    assert design.shape == (50, term.n_coefficients)
    np.testing.assert_array_equal(np.diff(design.indptr), math.prod(b.degree + 1 for b in bases))
    np.testing.assert_allclose(design.sum(axis=1).A.ravel(), 1.0, atol=EXACT_TOLERANCE)
    for row in range(X.shape[0]):
        rows = [b.design(X[row : row + 1, i]).toarray().ravel() for b, i in zip(bases, term.input_indices)]
        expected = np.kron(np.kron(rows[0], rows[1]), rows[2])  # first index slowest
        np.testing.assert_allclose(design[row].toarray().ravel(), expected, atol=EXACT_TOLERANCE)


def test_term_penalty_is_sum_of_weighted_kronecker_products():
    bases = [make_basis(4), make_basis(3, 2)]
    term = TensorTerm("t", (0, 1), bases, penalty_order=2, smoothing=SMOOTHING_VALUES[:2])
    n0, n1 = (b.n_coefficients for b in bases)
    p0 = bases[0].difference_penalty(2).toarray()
    p1 = bases[1].difference_penalty(2).toarray()
    expected = SMOOTHING_VALUES[0] * np.kron(p0, np.eye(n1)) + SMOOTHING_VALUES[1] * np.kron(np.eye(n0), p1)
    penalty = term.penalty()
    np.testing.assert_allclose(penalty.toarray(), expected, atol=EXACT_TOLERANCE)
    np.testing.assert_allclose(penalty.toarray(), penalty.toarray().T, atol=EXACT_TOLERANCE)
    ones = np.ones(term.n_coefficients)
    assert abs(ones @ (penalty @ ones)) < EXACT_TOLERANCE  # constants are unpenalized


def test_term_validation_and_defaults():
    term = TensorTerm("t", (0, 1), [make_basis(3), make_basis(3)])
    assert len(term.smoothing) == 2
    with pytest.raises(ValueError):
        TensorTerm("t", (0,), [make_basis(3), make_basis(3)])
    with pytest.raises(ValueError):
        TensorTerm("t", (0,), [make_basis(3)], smoothing=[-1.0])
    with pytest.raises(ValueError):
        term.design(np.zeros((4, 1)))  # missing input column


def test_two_dimensional_term_recovers_sin_x_cos_y():
    rng = np.random.default_rng(RANDOM_SEED)
    lower, upper = 0.0, 2 * math.pi
    basis = lambda: BSplineBasis1D.uniform(lower, upper, RECOVERY_INTERVALS, DEGREE)
    term = TensorTerm("f", (0, 1), [basis(), basis()], smoothing=[RECOVERY_SMOOTHING] * 2)
    model = SumOfTermsSpline([InputSpec("x", lower, upper, "rad"), InputSpec("y", lower, upper, "rad")], [term])
    X = rng.uniform(lower, upper, size=(N_TRAIN, 2))
    truth = lambda P: np.sin(P[:, 0]) * np.cos(P[:, 1])
    fit = fit_penalized_least_squares(model.design(X), truth(X), np.ones(N_TRAIN), model.penalty())
    model.coefficients = fit.coefficients
    X_test = rng.uniform(lower, upper, size=(N_TEST, 2))
    rms = np.sqrt(np.mean((model.evaluate(X_test) - truth(X_test)) ** 2))
    assert rms < RECOVERY_TOLERANCE


def test_evaluate_is_sum_of_term_evaluations_and_slices():
    rng = np.random.default_rng(RANDOM_SEED)
    model = make_model(rng)
    X = rng.uniform(LOWER_BOUND_X, UPPER_BOUND_X, size=(40, 4))
    slices = model.term_slices()
    assert slices[0].start == 0 and slices[-1].stop == model.n_coefficients
    assert all(a.stop == b.start for a, b in zip(slices[:-1], slices[1:]))
    by_term = sum(t.evaluate(X, model.coefficients[s]) for t, s in zip(model.terms, slices))
    np.testing.assert_allclose(model.evaluate(X), by_term, atol=EXACT_TOLERANCE)
    np.testing.assert_allclose(model.design(X) @ model.coefficients, by_term, atol=EXACT_TOLERANCE)
    penalty = model.penalty()
    assert penalty.shape == (model.n_coefficients, model.n_coefficients)
    assert (penalty[slices[1], slices[1]] - model.terms[1].penalty()).count_nonzero() == 0
    assert penalty[slices[0], slices[1]].count_nonzero() == 0  # block diagonal


def reference_basis_value(knots, i, degree, x, upper):
    """Independent recursive definition of B_{i,degree}(x) used to check the JSON rule."""
    if degree == 0:
        inside = knots[i] <= x < knots[i + 1]
        at_upper = x == upper and knots[i] < knots[i + 1] == upper
        return 1.0 if (inside or at_upper) else 0.0
    value = 0.0
    left = knots[i + degree] - knots[i]
    if left > 0:
        value += (x - knots[i]) / left * reference_basis_value(knots, i, degree - 1, x, upper)
    right = knots[i + degree + 1] - knots[i + 1]
    if right > 0:
        value += (knots[i + degree + 1] - x) / right * reference_basis_value(knots, i + 1, degree - 1, x, upper)
    return value


def reference_term_value(entry, x_row):
    """Evaluate one JSON term entry literally by the rule of section 7, with the recursive basis."""
    degree = entry["degree"]
    knots = [np.asarray(k) for k in entry["knots"]]
    sizes = [k.size - degree - 1 for k in knots]
    coefficients = np.asarray(entry["coefficients"]).reshape(sizes)  # row-major over dimensions
    per_dimension = []
    for k, index in zip(knots, entry["input_indices"]):
        x = min(max(x_row[index], k[0]), k[-1])
        per_dimension.append([reference_basis_value(k, j, degree, x, k[-1]) for j in range(k.size - degree - 1)])
    total = 0.0
    for flat in np.ndindex(*sizes):
        weight = math.prod(per_dimension[d][flat[d]] for d in range(len(sizes)))
        total += coefficients[flat] * weight
    return total


def test_json_rule_agrees_with_independent_reference(tmp_path):
    rng = np.random.default_rng(RANDOM_SEED)
    model = make_model(rng)
    document = model.to_dict()
    span = UPPER_BOUND_X - LOWER_BOUND_X
    X = rng.uniform(LOWER_BOUND_X - OUTSIDE_MARGIN * span, UPPER_BOUND_X + OUTSIDE_MARGIN * span, size=(25, 4))
    X[0] = LOWER_BOUND_X  # exactly at the bounds
    X[1] = UPPER_BOUND_X
    expected = [sum(reference_term_value(t, row) for t in document["terms"]) for row in X]
    np.testing.assert_allclose(model.evaluate(X), expected, atol=EXACT_TOLERANCE)


def test_json_round_trip_reproduces_evaluate(tmp_path):
    rng = np.random.default_rng(RANDOM_SEED)
    model = make_model(rng)
    path = tmp_path / "map.json"
    model.to_json(path)
    loaded = SumOfTermsSpline.from_json(path)
    span = UPPER_BOUND_X - LOWER_BOUND_X
    X = rng.uniform(
        LOWER_BOUND_X - OUTSIDE_MARGIN * span, UPPER_BOUND_X + OUTSIDE_MARGIN * span, size=(N_ROUND_TRIP_POINTS, 4)
    )
    np.testing.assert_allclose(loaded.evaluate(X), model.evaluate(X), rtol=0, atol=EXACT_TOLERANCE)
    assert loaded.metadata == model.metadata  # stored verbatim
    assert loaded.inputs == model.inputs
    for original, restored in zip(model.terms, loaded.terms):
        assert restored.input_indices == original.input_indices
        assert restored.penalty_order == original.penalty_order
        assert restored.smoothing == original.smoothing
        for a, b in zip(original.bases, restored.bases):
            assert a.degree == b.degree
            np.testing.assert_array_equal(a.knots, b.knots)
    np.testing.assert_array_equal(loaded.coefficients, model.coefficients)


def test_json_document_structure(tmp_path):
    model = make_model(np.random.default_rng(RANDOM_SEED))
    path = tmp_path / "map.json"
    model.to_json(path)
    document = json.loads(path.read_text())
    assert document["format"] == FORMAT_NAME and document["version"] == FORMAT_VERSION
    assert [i["name"] for i in document["inputs"]] == ["x0", "x1", "x2", "x3"]
    assert set(document["inputs"][0]) == {"name", "lower", "upper", "unit"}
    assert {"name", "unit", "applies_to"} <= set(document["output"])
    assert "domain_note" in document and "metadata" in document
    term = document["terms"][1]
    assert term["input_indices"] == [0, 3] and term["degree"] == DEGREE
    assert len(term["knots"]) == 2 and len(term["coefficients"]) == model.terms[1].n_coefficients


def test_json_rejects_foreign_documents_and_mixed_degrees(tmp_path):
    with pytest.raises(ValueError):
        SumOfTermsSpline.from_dict({"format": "something-else", "version": FORMAT_VERSION})
    with pytest.raises(ValueError):
        SumOfTermsSpline.from_dict({"format": FORMAT_NAME, "version": FORMAT_VERSION + 1})
    model = make_model(np.random.default_rng(RANDOM_SEED))
    model.coefficients[0] = np.nan
    with pytest.raises(ValueError):
        model.to_json(tmp_path / "bad.json")  # NaN would not be strict JSON
    mixed = SumOfTermsSpline(
        make_inputs(2), [TensorTerm("m", (0, 1), [make_basis(3, 3), make_basis(3, 2)])]
    )
    with pytest.raises(ValueError):
        mixed.to_dict()
