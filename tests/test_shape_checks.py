"""
Tests of the robot-independent shape checks: the free-radius sphere fit and
the plane flatness RMS, on synthetic points with known truth.
"""
from __future__ import annotations

import numpy as np

from sphcal.calibration.extrinsic import SphereFitParameters, fit_sphere_center, fit_sphere_free_radius, \
    free_radius_standard_error
from sphcal.validation.report import ReportParameters, plane_flatness_rms_mm

SPHERE_RADIUS_MM = 38.1
SPHERE_CENTER_MM = np.array([30.0, -20.0, 500.0])
CAP_HALF_ANGLE_DEG = 55.0
"""Angular half-width of the visible cap, from the sphere's axis toward the sensor."""
CAP_POINT_COUNT = 2000
NOISELESS_TOLERANCE_MM = 0.01
NOISE_SIGMA_MM = 0.05
OUTLIER_FRACTION = 0.02
OUTLIER_RANGE_OFFSET_MM = (50.0, 300.0)
"""Gross outliers (flying pixels) are pushed this far further along the view ray."""
NOISY_RADIUS_TOLERANCE_MM = 0.02
PLANE_POINT_COUNT = 5000
PLANE_HALF_SIZE_MM = 100.0
PLANE_NORMAL = np.array([0.3, -0.2, 1.0]) / np.linalg.norm([0.3, -0.2, 1.0])
PLANE_CENTER_MM = np.array([10.0, 20.0, 600.0])
NOISELESS_FLATNESS_LIMIT_MM = 1.0e-9
PLANE_NOISE_SIGMA_MM = 0.1
FLATNESS_RELATIVE_TOLERANCE = 0.10
SEED = 7


def sphere_cap_points(rng: np.random.Generator, count: int = CAP_POINT_COUNT) -> np.ndarray:
    """Points uniform in solid angle on the cap of the sphere facing the sensor (at the origin)."""
    axis = -SPHERE_CENTER_MM / np.linalg.norm(SPHERE_CENTER_MM)
    cos_theta = rng.uniform(np.cos(np.radians(CAP_HALF_ANGLE_DEG)), 1.0, count)
    phi = rng.uniform(0.0, 2.0 * np.pi, count)
    helper = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(axis, helper)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    sin_theta = np.sqrt(1.0 - cos_theta ** 2)
    directions = (cos_theta[:, None] * axis + sin_theta[:, None] * (np.cos(phi)[:, None] * u + np.sin(phi)[:, None] * v))
    return SPHERE_CENTER_MM + SPHERE_RADIUS_MM * directions


def test_free_radius_recovers_noiseless_cap():
    points = sphere_cap_points(np.random.default_rng(SEED))
    center, radius, rms = fit_sphere_free_radius(points, SphereFitParameters())
    assert np.linalg.norm(center - SPHERE_CENTER_MM) < NOISELESS_TOLERANCE_MM, center
    assert abs(radius - SPHERE_RADIUS_MM) < NOISELESS_TOLERANCE_MM, radius
    assert rms < NOISELESS_TOLERANCE_MM


def test_free_radius_is_robust_to_noise_and_flying_pixels():
    rng = np.random.default_rng(SEED)
    points = sphere_cap_points(rng) + rng.normal(0.0, NOISE_SIGMA_MM, (CAP_POINT_COUNT, 3))
    outliers = rng.random(CAP_POINT_COUNT) < OUTLIER_FRACTION
    rays = points / np.linalg.norm(points, axis=1, keepdims=True)
    offsets = rng.uniform(*OUTLIER_RANGE_OFFSET_MM, CAP_POINT_COUNT)
    points = points + np.where(outliers, offsets, 0.0)[:, None] * rays
    center, radius, rms = fit_sphere_free_radius(points, SphereFitParameters())
    assert outliers.any()
    assert abs(radius - SPHERE_RADIUS_MM) < NOISY_RADIUS_TOLERANCE_MM, radius
    # The reported RMS is over the surviving points, so it reflects the noise and not the outliers.
    assert abs(rms - NOISE_SIGMA_MM) < FLATNESS_RELATIVE_TOLERANCE * NOISE_SIGMA_MM * 2.0, rms


def test_free_radius_agrees_with_known_radius_fit_on_noiseless_data():
    points = sphere_cap_points(np.random.default_rng(SEED))
    params = SphereFitParameters()
    center_free, _, _ = fit_sphere_free_radius(points, params)
    center_known = fit_sphere_center(points, SPHERE_RADIUS_MM, params)
    assert np.linalg.norm(center_free - center_known) < NOISELESS_TOLERANCE_MM


def test_free_radius_refuses_below_min_points():
    params = SphereFitParameters()
    points = sphere_cap_points(np.random.default_rng(SEED), params.min_points - 1)
    center, radius, rms = fit_sphere_free_radius(points, params)
    assert np.isnan(center).all() and np.isnan(radius) and np.isnan(rms)


def plane_points(rng: np.random.Generator, noise_sigma_mm: float) -> np.ndarray:
    """Points scattered on a tilted plane, with Gaussian noise along its normal."""
    helper = np.array([1.0, 0.0, 0.0])
    u = np.cross(PLANE_NORMAL, helper)
    u /= np.linalg.norm(u)
    v = np.cross(PLANE_NORMAL, u)
    coordinates = rng.uniform(-PLANE_HALF_SIZE_MM, PLANE_HALF_SIZE_MM, (PLANE_POINT_COUNT, 2))
    points = PLANE_CENTER_MM + coordinates[:, :1] * u + coordinates[:, 1:] * v
    return points + rng.normal(0.0, noise_sigma_mm, PLANE_POINT_COUNT)[:, None] * PLANE_NORMAL


def test_flatness_of_noiseless_tilted_plane_is_zero():
    rms = plane_flatness_rms_mm(plane_points(np.random.default_rng(SEED), 0.0), ReportParameters())
    assert rms < NOISELESS_FLATNESS_LIMIT_MM, rms


def test_flatness_equals_injected_noise():
    rms = plane_flatness_rms_mm(plane_points(np.random.default_rng(SEED), PLANE_NOISE_SIGMA_MM), ReportParameters())
    assert abs(rms - PLANE_NOISE_SIGMA_MM) < FLATNESS_RELATIVE_TOLERANCE * PLANE_NOISE_SIGMA_MM, rms


def test_flatness_refuses_below_min_points():
    params = ReportParameters()
    points = plane_points(np.random.default_rng(SEED), 0.0)[: params.sphere_fit.min_points - 1]
    assert np.isnan(plane_flatness_rms_mm(points, params))


STANDARD_ERROR_TRIALS = 200
STANDARD_ERROR_POINT_COUNT = 200
"""A small cap, like a distant sphere's, so the radius error is large enough to measure."""
STANDARD_ERROR_RELATIVE_TOLERANCE = 0.25
"""The predicted standard error must match the scatter over repeated noisy
fits within this fraction (200 trials estimate a sigma to about 5 percent)."""


def test_free_radius_standard_error_matches_scatter():
    """The covariance-based radius standard error agrees with the radius scatter over repeated noisy fits."""
    rng = np.random.default_rng(SEED)
    radii, predicted = [], []
    for _ in range(STANDARD_ERROR_TRIALS):
        points = sphere_cap_points(rng, STANDARD_ERROR_POINT_COUNT) \
            + rng.normal(0.0, NOISE_SIGMA_MM, (STANDARD_ERROR_POINT_COUNT, 3))
        center, radius, rms = fit_sphere_free_radius(points, SphereFitParameters())
        radii.append(radius)
        predicted.append(free_radius_standard_error(points, center, radius, rms))
    observed = float(np.std(radii))
    assert abs(float(np.median(predicted)) - observed) <= STANDARD_ERROR_RELATIVE_TOLERANCE * observed
