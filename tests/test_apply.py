"""Tests of sphcal.calibration.apply.correct_frame: the caller gives PHYSICAL
curvature (1/R) and the function converts it to the map's measurement-space
curvature, per pixel, with each pixel's measured range."""
from __future__ import annotations

import numpy as np

from sphcal.calibration.apply import correct_frame
from sphcal.calibration.model_config import ModelConfiguration, TermSpec, build_model
from sphcal.calibration.samples import INPUT_UNITS
from sphcal.features.depth_features import SlopeParameters, range_from_depth
from sphcal.geometry.camera import PinholeCamera
from sphcal.spline.basis import BSplineBasis1D
from sphcal.spline.model import InputSpec, SumOfTermsSpline
from sphcal.spline.term import TensorTerm

CAMERA = PinholeCamera(64, 48, 700.0, 679.0, 32.0, 24.0)
"""A small camera with unequal focal lengths, so that the geometric mean matters."""
CURVATURE_AXIS_UPPER_MM_PER_PX2 = 0.5
"""Upper bound of the test model's curvature axis."""
DELTA_PER_MM_PER_PX2 = 3.0
"""Slope of the test model: the correction in mm per mm/px^2 of measurement-space curvature."""
PHYSICAL_CURVATURE_PER_MM = 1.0 / 76.2
"""Curvature of the 76.2 mm sphere."""
PLANE_DEPTHS_MM = (500.0, 1000.0)
"""Two ranges at which the conversion is checked; the same physical curvature must give different corrections."""
TOLERANCE = 1.0e-9
SLOPE_PARAMETERS = SlopeParameters(window_px=5)


def linear_in_measurement_curvature_model() -> SumOfTermsSpline:
    """A model whose only term is linear in the sixth input: delta = DELTA_PER_MM_PER_PX2 * kappa_m, exactly
    (one interval, degree 1, coefficients 0 and slope * upper bound)."""
    inputs = [InputSpec(name, 0.0, 1.0, unit) for name, unit in zip(
        ("u", "v", "range", "slope_u", "slope_v", "curvature"), INPUT_UNITS)]
    basis = BSplineBasis1D.uniform(0.0, CURVATURE_AXIS_UPPER_MM_PER_PX2, 1, 1)
    term = TensorTerm("curvature", (5,), [basis])
    coefficients = np.array([0.0, DELTA_PER_MM_PER_PX2 * CURVATURE_AXIS_UPPER_MM_PER_PX2])
    return SumOfTermsSpline(inputs, [term], coefficients)


def fronto_parallel_frame(depth_mm: float) -> tuple[np.ndarray, np.ndarray]:
    """xyz (H, W, 3) of a plane at camera-z depth_mm, and an all-true validity mask."""
    u, v = CAMERA.pixel_grid()
    xyz = CAMERA.back_project(u, v, np.full(u.shape, depth_mm))
    return xyz, np.ones(u.shape, dtype=bool)


def test_correct_frame_converts_physical_curvature_per_pixel_at_two_ranges():
    model = linear_in_measurement_curvature_model()
    deltas = []
    for depth_mm in PLANE_DEPTHS_MM:
        xyz, valid = fronto_parallel_frame(depth_mm)
        result = correct_frame(xyz, valid, CAMERA, model, SLOPE_PARAMETERS, PHYSICAL_CURVATURE_PER_MM)
        measured_range = range_from_depth(xyz[..., 2], CAMERA)
        expected = DELTA_PER_MM_PER_PX2 * (measured_range / CAMERA.mean_focal_px) ** 2 * PHYSICAL_CURVATURE_PER_MM
        assert result.valid.any()
        np.testing.assert_allclose(result.delta_range[result.valid], expected[result.valid], rtol=TOLERANCE, atol=TOLERANCE)
        deltas.append(float(result.delta_range[result.valid].mean()))
    # The same physical curvature gives a correction four times larger at twice the range.
    assert np.isclose(deltas[1] / deltas[0], (PLANE_DEPTHS_MM[1] / PLANE_DEPTHS_MM[0]) ** 2, rtol=1.0e-3)


def test_correct_frame_scalar_and_per_pixel_curvature_agree_and_zero_means_no_correction():
    model = linear_in_measurement_curvature_model()
    xyz, valid = fronto_parallel_frame(PLANE_DEPTHS_MM[0])
    scalar = correct_frame(xyz, valid, CAMERA, model, SLOPE_PARAMETERS, PHYSICAL_CURVATURE_PER_MM)
    image = correct_frame(xyz, valid, CAMERA, model, SLOPE_PARAMETERS,
                          np.full(valid.shape, PHYSICAL_CURVATURE_PER_MM))
    np.testing.assert_allclose(image.delta_range[image.valid], scalar.delta_range[scalar.valid], rtol=0.0, atol=TOLERANCE)
    flat = correct_frame(xyz, valid, CAMERA, model, SLOPE_PARAMETERS)          # default: physical curvature 0
    assert np.all(flat.delta_range[flat.valid] == 0.0)
    # Half the image with the curvature, half without.
    half = np.zeros(valid.shape)
    half[:, : valid.shape[1] // 2] = PHYSICAL_CURVATURE_PER_MM
    mixed = correct_frame(xyz, valid, CAMERA, model, SLOPE_PARAMETERS, half)
    assert np.all(mixed.delta_range[mixed.valid & (half == 0.0)] == 0.0)
    assert np.all(mixed.delta_range[mixed.valid & (half > 0.0)] > 0.0)


def test_default_configuration_curvature_axis_is_measurement_space():
    """The default model's sixth input has the measurement-space bound and unit, and the curvature term is
    linear in curvature and cubic in range and the slopes."""
    from sphcal.calibration.model_config import default_configuration
    configuration = default_configuration()
    assert configuration.curvature_upper_mm_per_px2 == 0.5
    inputs = np.column_stack([np.zeros(10), np.zeros(10), np.linspace(300.0, 1100.0, 10), np.zeros(10), np.zeros(10),
                              np.zeros(10)])
    model = build_model(configuration, inputs, CAMERA.width, CAMERA.height, camera=CAMERA)
    assert model.inputs[5].upper == 0.5 and "mm/px^2" in model.inputs[5].unit
    curvature_term = next(t for t in model.terms if t.name == "curvature")
    assert curvature_term.input_indices == (5, 2, 3, 4)
    assert [b.degree for b in curvature_term.bases] == [1, 3, 3, 3]
    assert curvature_term.dimension_sizes == [2, 7, 7, 7]
    assert model.camera == CAMERA.map_block()
    spec = ModelConfiguration((TermSpec("t", (0, 1), (2, 2), degree=(1, 3)),)).terms[0]
    assert spec.degrees == (1, 3) and TermSpec("t", (0, 1), (2, 2)).degrees == (3, 3)
