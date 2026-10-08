"""Tests of sphcal.features: temporal statistics, image slopes, range from depth,
block weight, and plane-fit normals."""
import numpy as np

from sphcal.features.depth_features import (
    SlopeParameters, block_independence_weight, image_slopes, measurement_space_curvature, range_from_depth,
    temporal_statistics)
from sphcal.features.normals import NormalEstimatorParameters, plane_fit_normals
from sphcal.geometry.camera import PinholeCamera

IMAGE_WIDTH_PX = 160
IMAGE_HEIGHT_PX = 120
FOCAL_PX = 800.0
CX = 80.0
CY = 60.0
CAMERA = PinholeCamera(IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX, FOCAL_PX, FOCAL_PX, CX, CY)

TILT_DEG = 20.0
AXIS_DEPTH_MM = 1000.0                    # plane depth on the optical axis
SLOPE_TOLERANCE = 1e-3
CENTER_HALF_REGION_PX = 2                 # "center region" is the principal point +- this many pixels
NORMAL_TOLERANCE_DEG = 0.05

FRAMES = 50
STACK_HEIGHT_PX = 20
STACK_WIDTH_PX = 30
SIGMA_LOW_MM = 0.5
SIGMA_HIGH_MM = 2.0
MIN_READ_FRACTION = 0.5
SPARSE_VALID_FRAMES = 10                  # 0.2 read fraction, below the minimum
VARIANCE_MEDIAN_TOLERANCE = 0.2           # median relative error bound at 50 frames
VARIANCE_MEAN_RATIO_TOLERANCE = 0.05
RANDOM_SEED = 12345


def _tilted_plane_depth(tilt_deg=TILT_DEG):
    """Camera-z depth image of the plane z = Z0 + tan(tilt) x (a plane rotated by
    `tilt` about the v axis through the optical-axis point at depth Z0), rendered
    by intersecting each pixel ray with the plane."""
    rays = CAMERA.ray_directions()
    tangent = np.tan(np.radians(tilt_deg))
    normal = np.array([tangent, 0.0, -1.0])                  # plane: n . p = -Z0
    point = np.array([0.0, 0.0, AXIS_DEPTH_MM])
    t = (point @ normal) / (rays @ normal)
    return t * rays[..., 2]


def _plane_normal_toward_camera(tilt_deg=TILT_DEG):
    angle = np.radians(tilt_deg)
    return np.array([np.sin(angle), 0.0, -np.cos(angle)])


def _center_region():
    rows = slice(int(CY) - CENTER_HALF_REGION_PX, int(CY) + CENTER_HALF_REGION_PX + 1)
    cols = slice(int(CX) - CENTER_HALF_REGION_PX, int(CX) + CENTER_HALF_REGION_PX + 1)
    return rows, cols


# --------------------------------------------------------------------------- slopes

def test_image_slopes_on_tilted_plane():
    depth = _tilted_plane_depth()
    valid = np.ones(depth.shape, dtype=bool)
    s_u, s_v = image_slopes(depth, valid, CAMERA, SlopeParameters())
    rows, cols = _center_region()
    assert np.all(np.abs(s_u[rows, cols] - np.tan(np.radians(TILT_DEG))) < SLOPE_TOLERANCE)
    assert np.all(np.abs(s_v[rows, cols]) < SLOPE_TOLERANCE)
    # Away from the axis the exact slope of this plane is tan(tilt) * z / Z0
    # (z the depth at the pixel); the window fit follows it.
    interior = (slice(SlopeParameters().window_px, -SlopeParameters().window_px),) * 2
    exact = np.tan(np.radians(TILT_DEG)) * depth / AXIS_DEPTH_MM
    assert np.nanmax(np.abs(s_u[interior] - exact[interior])) < 2.0 * SLOPE_TOLERANCE
    assert np.nanmax(np.abs(s_v[interior])) < SLOPE_TOLERANCE


def test_image_slopes_sign_follows_depth_gradient():
    # Depth increasing to the right (u) and downward (v), and the opposite.
    u, v = CAMERA.pixel_grid()
    gradient_mm_per_px = 0.5
    depth = AXIS_DEPTH_MM + gradient_mm_per_px * (u - CX) + 2.0 * gradient_mm_per_px * (v - CY)
    valid = np.ones(depth.shape, dtype=bool)
    s_u, s_v = image_slopes(depth, valid, CAMERA, SlopeParameters())
    rows, cols = _center_region()
    # The depth is exactly linear in (u, v), so the fit is exact and the center value
    # of the fitted plane equals the depth at the pixel.
    assert np.allclose(s_u[rows, cols], gradient_mm_per_px * FOCAL_PX / depth[rows, cols], atol=1e-9)
    assert np.allclose(s_v[rows, cols], 2.0 * gradient_mm_per_px * FOCAL_PX / depth[rows, cols], atol=1e-9)
    s_u_neg, s_v_neg = image_slopes(2.0 * AXIS_DEPTH_MM - depth, valid, CAMERA, SlopeParameters())
    assert (s_u_neg[rows, cols] < 0.0).all() and (s_v_neg[rows, cols] < 0.0).all()


def test_image_slopes_nan_where_window_unusable():
    depth = _tilted_plane_depth()
    valid = np.ones(depth.shape, dtype=bool)
    params = SlopeParameters()
    hole_center = (int(CY), int(CX))
    half = params.window_px // 2
    valid[hole_center[0] - half:hole_center[0] + half + 1, hole_center[1] - half:hole_center[1] + half + 1] = False
    s_u, s_v = image_slopes(depth, valid, CAMERA, params)
    assert np.isnan(s_u[hole_center]) and np.isnan(s_v[hole_center])     # window entirely invalid
    assert np.isnan(s_u[0, 0])                                           # corner: window mostly off-image
    assert np.isfinite(s_u[int(CY), 10]) and np.isfinite(s_v[int(CY), 10])
    # Invalid depth (z <= 0) counts as invalid even if the mask says valid.
    zero_depth = depth.copy()
    zero_depth[:] = 0.0
    s_zero, _ = image_slopes(zero_depth, np.ones(depth.shape, dtype=bool), CAMERA, params)
    assert np.isnan(s_zero).all()


def test_image_slopes_singular_window_is_nan():
    depth = _tilted_plane_depth()
    valid = np.zeros(depth.shape, dtype=bool)
    valid[int(CY), :] = True                                             # a single valid row: v offsets all zero
    params = SlopeParameters(window_px=5, min_valid_fraction=0.1)
    s_u, s_v = image_slopes(depth, valid, CAMERA, params)
    assert np.isnan(s_u[int(CY), int(CX)]) and np.isnan(s_v[int(CY), int(CX)])


def test_range_from_depth():
    depth = np.full((IMAGE_HEIGHT_PX, IMAGE_WIDTH_PX), AXIS_DEPTH_MM)
    rho = range_from_depth(depth, CAMERA)
    assert rho[int(CY), int(CX)] == AXIS_DEPTH_MM
    u, v = CAMERA.pixel_grid()
    points = CAMERA.back_project(u, v, depth)
    assert np.allclose(rho, np.linalg.norm(points, axis=-1))
    assert (rho >= depth).all()


def test_block_independence_weight():
    block_px = 4
    assert block_independence_weight(block_px) == 1.0 / (block_px * block_px)


# --------------------------------------------------------------------------- temporal

def test_temporal_statistics_recovers_variance_and_flags_low_read_fraction():
    rng = np.random.default_rng(RANDOM_SEED)
    shape = (STACK_HEIGHT_PX, STACK_WIDTH_PX)
    sigma = np.linspace(SIGMA_LOW_MM, SIGMA_HIGH_MM, shape[0] * shape[1]).reshape(shape)
    mean_true = AXIS_DEPTH_MM + np.arange(shape[1])[None, :] * np.ones(shape)
    stack = mean_true[None] + sigma[None] * rng.standard_normal((FRAMES,) + shape)
    valid = np.ones((FRAMES,) + shape, dtype=bool)
    sparse = (slice(0, 3), slice(0, 4))                      # a block of pixels read in few frames
    valid[SPARSE_VALID_FRAMES:, sparse[0], sparse[1]] = False
    scattered = rng.random(valid.shape) < 0.1                # random dropouts elsewhere
    valid &= ~scattered
    valid[SPARSE_VALID_FRAMES:, sparse[0], sparse[1]] = False
    valid[:SPARSE_VALID_FRAMES, sparse[0], sparse[1]] = True
    stack_with_junk = np.where(valid, stack, 0.0)            # invalid entries carry the sentinel zero

    stats = temporal_statistics(stack_with_junk, valid, MIN_READ_FRACTION)
    assert np.allclose(stats.read_fraction, valid.sum(axis=0) / FRAMES)
    assert (stats.valid_count == valid.sum(axis=0)).all()
    # Low-read pixels are invalid.
    assert stats.read_fraction[sparse].max() < MIN_READ_FRACTION
    assert np.isnan(stats.variance[sparse]).all() and np.isnan(stats.mean_depth[sparse]).all()
    ok = stats.read_fraction >= MIN_READ_FRACTION
    assert np.isfinite(stats.variance[ok]).all() and np.isfinite(stats.mean_depth[ok]).all()
    # Exact agreement with numpy's unbiased variance for a few pixels.
    for row, col in [(5, 5), (10, 20), (19, 29)]:
        samples = stack_with_junk[valid[:, row, col], row, col]
        assert abs(stats.variance[row, col] - np.var(samples, ddof=1)) < 1e-9 * max(1.0, np.var(samples, ddof=1))
        assert abs(stats.mean_depth[row, col] - samples.mean()) < 1e-9
    # Statistical recovery of the known variance (each pixel's estimate has ~20 percent scatter at 50 frames).
    ratio = stats.variance[ok] / (sigma[ok] ** 2)
    assert abs(np.median(np.abs(ratio - 1.0))) < VARIANCE_MEDIAN_TOLERANCE
    assert abs(ratio.mean() - 1.0) < VARIANCE_MEAN_RATIO_TOLERANCE


def test_temporal_statistics_minimum_sample_counts():
    stack = np.arange(3 * 2 * 2, dtype=float).reshape(3, 2, 2) + 1.0
    valid = np.ones(stack.shape, dtype=bool)
    valid[1:, 0, 0] = False          # one valid frame: mean exists, variance does not
    valid[:, 1, 1] = False           # none valid
    stats = temporal_statistics(stack, valid, 0.0)
    assert np.isfinite(stats.mean_depth[0, 0]) and np.isnan(stats.variance[0, 0])
    assert np.isnan(stats.mean_depth[1, 1]) and np.isnan(stats.variance[1, 1])
    assert stats.valid_count[1, 1] == 0 and stats.read_fraction[1, 1] == 0.0
    assert np.isfinite(stats.variance[0, 1])


# --------------------------------------------------------------------------- normals

def _plane_xyz():
    depth = _tilted_plane_depth()
    u, v = CAMERA.pixel_grid()
    return CAMERA.back_project(u, v, depth)


def test_plane_fit_normals_on_tilted_plane():
    xyz = _plane_xyz()
    valid = np.ones(xyz.shape[:2], dtype=bool)
    normals = plane_fit_normals(xyz, valid, NormalEstimatorParameters())
    expected = _plane_normal_toward_camera()
    finite = np.isfinite(normals).all(axis=-1)
    assert finite.mean() > 0.9
    cosines = np.clip(normals[finite] @ expected, -1.0, 1.0)
    assert np.degrees(np.arccos(cosines)).max() < NORMAL_TOLERANCE_DEG
    assert np.allclose(np.linalg.norm(normals[finite], axis=-1), 1.0)
    # Oriented toward the camera: negative dot with the ray.
    rays = CAMERA.ray_directions()
    assert (np.sum(normals[finite] * rays[finite], axis=-1) < 0.0).all()


def test_plane_fit_normals_nan_where_unusable():
    xyz = _plane_xyz()
    valid = np.ones(xyz.shape[:2], dtype=bool)
    params = NormalEstimatorParameters()
    half = params.window_px // 2
    valid[int(CY) - half:int(CY) + half + 1, int(CX) - half:int(CX) + half + 1] = False
    normals = plane_fit_normals(xyz, valid, params)
    assert np.isnan(normals[int(CY), int(CX)]).all()
    assert np.isfinite(normals[int(CY), 10]).all()
    # Collinear valid points (a single valid row): the plane is undetermined.
    row_only = np.zeros(xyz.shape[:2], dtype=bool)
    row_only[int(CY), :] = True
    degenerate = plane_fit_normals(xyz, row_only, NormalEstimatorParameters(window_px=5, min_valid_fraction=0.1))
    assert np.isnan(degenerate[int(CY), int(CX)]).all()
    # Zero-sentinel points are invalid even if the mask says valid.
    assert np.isnan(plane_fit_normals(np.zeros_like(xyz), np.ones(xyz.shape[:2], dtype=bool), params)).all()


def test_plane_fit_normals_orientation_is_independent_of_surface_side():
    # A plane tilted the other way still faces the camera.
    depth = _tilted_plane_depth(-TILT_DEG)
    u, v = CAMERA.pixel_grid()
    xyz = CAMERA.back_project(u, v, depth)
    normals = plane_fit_normals(xyz, np.ones(depth.shape, dtype=bool), NormalEstimatorParameters())
    expected = _plane_normal_toward_camera(-TILT_DEG)
    center = normals[int(CY), int(CX)]
    assert np.degrees(np.arccos(np.clip(center @ expected, -1.0, 1.0))) < NORMAL_TOLERANCE_DEG


MEASUREMENT_CURVATURE_RANGE_MM = 1000.0
MEASUREMENT_CURVATURE_FOCAL_PX = 500.0
MEASUREMENT_CURVATURE_PER_MM = 0.01       # a 100 mm radius
EXPECTED_MEASUREMENT_CURVATURE = 0.04     # (1000 / 500)^2 * 0.01 mm/px^2
UNEQUAL_FOCAL_X_PX = 700.0
UNEQUAL_FOCAL_Y_PX = 700.0 * 0.97


def test_measurement_space_curvature_value():
    """kappa_m = (range / f)^2 / R: a 100 mm radius at 1000 mm range with a 500 px focal length is 0.04 mm/px^2."""
    value = measurement_space_curvature(MEASUREMENT_CURVATURE_PER_MM, MEASUREMENT_CURVATURE_RANGE_MM,
                                        MEASUREMENT_CURVATURE_FOCAL_PX)
    assert np.isclose(value, EXPECTED_MEASUREMENT_CURVATURE, rtol=1e-12, atol=0.0)
    # The project's reference point of the default bound: 20 mm radius, 2200 mm, 688 px gives about 0.51.
    bound_value = measurement_space_curvature(1.0 / 20.0, 2200.0, 688.0)
    assert np.isclose(bound_value, (2200.0 / 688.0) ** 2 / 20.0) and 0.5 < bound_value < 0.52
    assert measurement_space_curvature(0.0, MEASUREMENT_CURVATURE_RANGE_MM, MEASUREMENT_CURVATURE_FOCAL_PX) == 0.0


def test_measurement_space_curvature_broadcasts_and_scales_with_range_squared():
    ranges = np.array([[250.0, 500.0], [1000.0, 2000.0]])
    from_scalar_curvature = measurement_space_curvature(MEASUREMENT_CURVATURE_PER_MM, ranges, MEASUREMENT_CURVATURE_FOCAL_PX)
    assert from_scalar_curvature.shape == ranges.shape
    # Doubling the range quadruples the curvature seen in measurement space.
    np.testing.assert_allclose(from_scalar_curvature[:, 1] / from_scalar_curvature[:, 0], 4.0, rtol=1e-12)
    np.testing.assert_allclose(from_scalar_curvature[1, 0], EXPECTED_MEASUREMENT_CURVATURE, rtol=1e-12)
    # A per-pixel curvature image against a scalar range, and an array against an array.
    curvature_image = np.array([[0.0, MEASUREMENT_CURVATURE_PER_MM], [2 * MEASUREMENT_CURVATURE_PER_MM, 0.0]])
    image_value = measurement_space_curvature(curvature_image, MEASUREMENT_CURVATURE_RANGE_MM, MEASUREMENT_CURVATURE_FOCAL_PX)
    np.testing.assert_allclose(image_value, curvature_image * 4.0, rtol=1e-12)
    both = measurement_space_curvature(curvature_image, ranges, MEASUREMENT_CURVATURE_FOCAL_PX)
    np.testing.assert_allclose(both, curvature_image * (ranges / MEASUREMENT_CURVATURE_FOCAL_PX) ** 2, rtol=1e-12)
    # Plain Python scalars give a scalar-like result.
    assert np.ndim(measurement_space_curvature(MEASUREMENT_CURVATURE_PER_MM, MEASUREMENT_CURVATURE_RANGE_MM,
                                               MEASUREMENT_CURVATURE_FOCAL_PX)) == 0


def test_camera_mean_focal_is_geometric_mean_of_fx_and_fy():
    camera = PinholeCamera(IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX, UNEQUAL_FOCAL_X_PX, UNEQUAL_FOCAL_Y_PX, CX, CY)
    assert np.isclose(camera.mean_focal_px, np.sqrt(UNEQUAL_FOCAL_X_PX * UNEQUAL_FOCAL_Y_PX), rtol=1e-14)
    assert camera.mean_focal_px != 0.5 * (UNEQUAL_FOCAL_X_PX + UNEQUAL_FOCAL_Y_PX)
    block = camera.map_block()
    assert block["fx"] == UNEQUAL_FOCAL_X_PX and block["fy"] == UNEQUAL_FOCAL_Y_PX
    assert (block["width"], block["height"]) == (IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX)
