"""Tests of sphcal.geometry.targets: ray intersections against closed forms and
the predicted-coverage masks."""
import numpy as np
from scipy.spatial import cKDTree

from sphcal.geometry.camera import PinholeCamera
from sphcal.geometry.targets import (
    BoardTarget, CoverageParameters, cos_incidence, predict_board_coverage,
    predict_sphere_coverage, ray_plane_range, ray_sphere_near_range, sphere_surface_normal)
from sphcal.geometry.transforms import RigidTransform

# Test camera: the principal point is on a pixel center so that pixel (CX, CY)
# looks exactly along the optical axis.
IMAGE_WIDTH_PX = 320
IMAGE_HEIGHT_PX = 240
FOCAL_PX = 400.0
CX = 160.0
CY = 120.0
CAMERA = PinholeCamera(IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX, FOCAL_PX, FOCAL_PX, CX, CY)

SPHERE_RADIUS_MM = 60.0
SPHERE_DISTANCE_MM = 500.0
OFFSET_SPHERE_CENTER = np.array([30.0, -20.0, SPHERE_DISTANCE_MM])
BOARD_DISTANCE_MM = 600.0
BOARD_HALF_WIDTH_MM = 100.0
BOARD_HALF_HEIGHT_MM = 50.0
BOARD = BoardTarget(BOARD_HALF_WIDTH_MM, BOARD_HALF_HEIGHT_MM)
# Board rotated half a turn about y: its outward normal (+z in its frame) then
# points along -z of the sensor, i.e. toward the camera.
FACING_ROTATION = np.diag([-1.0, 1.0, -1.0])
HALF_TURN_DEG = 180.0
ONE_PIXEL = 1.0
SPHERE_MARGIN_PX = 6.0
BOARD_MARGIN_MM = 10.0
CUTOFFS_DEG = [80.0, 65.0, 50.0, 35.0, 20.0]       # decreasing
CLOSED_FORM_TOLERANCE_MM = 1e-9
ANGLE_GUARD_FACTOR = 0.01       # stay this fraction away from the silhouette angle when checking hit/miss


def _facing_board_pose(rotation=FACING_ROTATION, center=(0.0, 0.0, BOARD_DISTANCE_MM)) -> RigidTransform:
    return RigidTransform(rotation, np.array(center))


def test_ray_sphere_on_axis_matches_closed_form():
    rays = CAMERA.ray_directions()
    center = np.array([0.0, 0.0, SPHERE_DISTANCE_MM])
    range_mm, hit = ray_sphere_near_range(rays, center, SPHERE_RADIUS_MM)
    # Center ray: center distance minus radius.
    assert hit[int(CY), int(CX)]
    assert abs(range_mm[int(CY), int(CX)] - (SPHERE_DISTANCE_MM - SPHERE_RADIUS_MM)) < CLOSED_FORM_TOLERANCE_MM
    # Elsewhere: angle phi from the axis; hit iff sin(phi) <= R / D.
    phi = np.arccos(np.clip(rays[..., 2], -1.0, 1.0))
    silhouette_angle = np.arcsin(SPHERE_RADIUS_MM / SPHERE_DISTANCE_MM)
    assert hit[phi < silhouette_angle * (1.0 - ANGLE_GUARD_FACTOR)].all()
    assert not hit[phi > silhouette_angle * (1.0 + ANGLE_GUARD_FACTOR)].any()
    assert np.isnan(range_mm[~hit]).all() and np.isfinite(range_mm[hit]).all()
    chord_term = SPHERE_RADIUS_MM ** 2 - (SPHERE_DISTANCE_MM * np.sin(phi)) ** 2
    expected = SPHERE_DISTANCE_MM * np.cos(phi) - np.sqrt(np.maximum(chord_term, 0.0))
    assert np.allclose(range_mm[hit], expected[hit], atol=CLOSED_FORM_TOLERANCE_MM)
    # The hit point lies on the sphere.
    points = rays[hit] * range_mm[hit][:, None]
    assert np.allclose(np.linalg.norm(points - center, axis=-1), SPHERE_RADIUS_MM, atol=1e-6)


def test_ray_sphere_behind_and_inside():
    d = np.array([[0.0, 0.0, 1.0]])
    _, hit_behind = ray_sphere_near_range(d, np.array([0.0, 0.0, -SPHERE_DISTANCE_MM]), SPHERE_RADIUS_MM)
    assert not hit_behind[0]
    # Camera inside the sphere: smaller root is negative, reported as no hit.
    _, hit_inside = ray_sphere_near_range(d, np.array([0.0, 0.0, 0.0]), SPHERE_RADIUS_MM)
    assert not hit_inside[0]


def test_ray_plane_frontal_range_is_depth_over_cos():
    rays = CAMERA.ray_directions()
    facing_normal = np.array([0.0, 0.0, -1.0])
    range_mm, hit = ray_plane_range(rays, np.array([0.0, 0.0, BOARD_DISTANCE_MM]), facing_normal)
    assert hit.all()
    assert np.allclose(range_mm, BOARD_DISTANCE_MM / rays[..., 2], atol=CLOSED_FORM_TOLERANCE_MM)
    # Equivalently the hit point has z equal to the plane depth.
    assert np.allclose((rays * range_mm[..., None])[..., 2], BOARD_DISTANCE_MM)


def test_ray_plane_rejects_back_facing_behind_and_parallel():
    rays = CAMERA.ray_directions()
    _, hit_back = ray_plane_range(rays, np.array([0.0, 0.0, BOARD_DISTANCE_MM]), np.array([0.0, 0.0, 1.0]))
    assert not hit_back.any()                    # outward normal points away from the camera
    _, hit_behind = ray_plane_range(rays, np.array([0.0, 0.0, -BOARD_DISTANCE_MM]), np.array([0.0, 0.0, -1.0]))
    assert not hit_behind.any()                  # plane behind the camera
    range_mm, hit_parallel = ray_plane_range(np.array([[1.0, 0.0, 0.0]]), np.array([0.0, 0.0, BOARD_DISTANCE_MM]),
                                             np.array([0.0, 0.0, -1.0]))
    assert not hit_parallel[0] and np.isnan(range_mm[0])


def test_normal_and_incidence_of_sphere():
    center = OFFSET_SPHERE_CENTER
    rays = CAMERA.ray_directions()
    range_mm, hit = ray_sphere_near_range(rays, center, SPHERE_RADIUS_MM)
    points = rays[hit] * range_mm[hit][:, None]
    normals = sphere_surface_normal(points, center)
    assert np.allclose(np.linalg.norm(normals, axis=-1), 1.0)
    assert (np.sum(normals * (points - center), axis=-1) > 0.0).all()      # outward
    cos_inc = cos_incidence(normals, rays[hit])
    assert (cos_inc >= 0.0).all() and (cos_inc <= 1.0).all()
    # A normal pointing straight back along the ray is head-on incidence.
    assert cos_incidence(np.array([0.0, 0.0, -1.0]), np.array([0.0, 0.0, 1.0])) == 1.0


def test_sphere_coverage_shrinks_with_cutoff_and_respects_margin():
    usable_counts = []
    for cutoff in CUTOFFS_DEG:
        coverage = predict_sphere_coverage(CAMERA, OFFSET_SPHERE_CENTER, SPHERE_RADIUS_MM,
                                           CoverageParameters(cutoff, SPHERE_MARGIN_PX, BOARD_MARGIN_MM))
        usable_counts.append(int(coverage.usable.sum()))
        assert (coverage.usable <= coverage.covered).all()
        assert coverage.curvature_per_mm == 1.0 / SPHERE_RADIUS_MM
        assert np.isnan(coverage.range_mm[~coverage.covered]).all()
        assert np.isnan(coverage.cos_incidence[~coverage.covered]).all()
        # Every usable pixel is within the incidence cutoff...
        assert (coverage.cos_incidence[coverage.usable] >= np.cos(np.radians(cutoff)) - 1e-12).all()
        # ...and farther than the margin from every non-hit pixel (brute-force check).
        non_hit = np.argwhere(~coverage.covered)
        usable = np.argwhere(coverage.usable)
        nearest, _ = cKDTree(non_hit).query(usable)
        assert (nearest > SPHERE_MARGIN_PX).all()
    assert all(a >= b for a, b in zip(usable_counts, usable_counts[1:]))   # monotone as the cutoff decreases
    assert usable_counts[0] > usable_counts[-1] > 0                        # and the cutoff actually bites
    # Covered area is independent of the cutoff and about the sphere's apparent disc.
    covered = coverage.covered.sum()
    apparent_radius_px = FOCAL_PX * SPHERE_RADIUS_MM / SPHERE_DISTANCE_MM
    assert abs(covered - np.pi * apparent_radius_px ** 2) / covered < 0.1


def test_sphere_coverage_margin_monotone():
    counts = [int(predict_sphere_coverage(CAMERA, OFFSET_SPHERE_CENTER, SPHERE_RADIUS_MM,
                                          CoverageParameters(CUTOFFS_DEG[0], margin, BOARD_MARGIN_MM)).usable.sum())
              for margin in (0.0, SPHERE_MARGIN_PX, 2.0 * SPHERE_MARGIN_PX)]
    assert counts[0] > counts[1] > counts[2]


def test_board_coverage_frontal_extent():
    coverage = predict_board_coverage(CAMERA, _facing_board_pose(), BOARD,
                                      CoverageParameters(CUTOFFS_DEG[2], SPHERE_MARGIN_PX, BOARD_MARGIN_MM))
    expected_width = 2.0 * FOCAL_PX * BOARD_HALF_WIDTH_MM / BOARD_DISTANCE_MM
    expected_height = 2.0 * FOCAL_PX * BOARD_HALF_HEIGHT_MM / BOARD_DISTANCE_MM
    columns = np.flatnonzero(coverage.covered.any(axis=0))
    rows = np.flatnonzero(coverage.covered.any(axis=1))
    assert abs(columns.size - expected_width) <= ONE_PIXEL
    assert abs(rows.size - expected_height) <= ONE_PIXEL
    assert abs((columns.mean()) - CX) <= ONE_PIXEL and abs(rows.mean() - CY) <= ONE_PIXEL
    # Usable region is the board shrunk by the edge margin on every side.
    usable_columns = np.flatnonzero(coverage.usable.any(axis=0)).size
    usable_rows = np.flatnonzero(coverage.usable.any(axis=1)).size
    assert abs(usable_columns - 2.0 * FOCAL_PX * (BOARD_HALF_WIDTH_MM - BOARD_MARGIN_MM) / BOARD_DISTANCE_MM) <= ONE_PIXEL
    assert abs(usable_rows - 2.0 * FOCAL_PX * (BOARD_HALF_HEIGHT_MM - BOARD_MARGIN_MM) / BOARD_DISTANCE_MM) <= ONE_PIXEL
    # Frontal board: range is depth over cos of the ray angle.
    rays = CAMERA.ray_directions()
    assert np.allclose(coverage.range_mm[coverage.covered],
                       BOARD_DISTANCE_MM / rays[..., 2][coverage.covered])
    assert coverage.curvature_per_mm == 0.0


def test_board_back_facing_has_no_coverage():
    away = predict_board_coverage(CAMERA, _facing_board_pose(np.eye(3)), BOARD, CoverageParameters())
    assert not away.covered.any() and not away.usable.any()
    assert np.isnan(away.range_mm).all()


def test_board_tilted_cutoff_and_edge_margin_in_board_coordinates():
    tilt_deg = 60.0                                  # cos = 0.5 at the center, beyond the default 55 degree cutoff
    tilt = RigidTransform.from_rotation_vector_degrees([0.0, tilt_deg, 0.0], np.zeros(3)).rotation
    pose = _facing_board_pose(tilt @ FACING_ROTATION)
    default_cutoff = predict_board_coverage(CAMERA, pose, BOARD, CoverageParameters())
    assert default_cutoff.covered.any() and not default_cutoff.usable.any()
    relaxed = predict_board_coverage(CAMERA, pose, BOARD, CoverageParameters(80.0, SPHERE_MARGIN_PX, BOARD_MARGIN_MM))
    assert relaxed.usable.any()
    assert abs(relaxed.cos_incidence[int(CY), int(CX)] - np.cos(np.radians(tilt_deg))) < 1e-9
    # Edge distance of usable points, in board coordinates, exceeds the margin.
    rays = CAMERA.ray_directions()
    points = rays[relaxed.usable] * relaxed.range_mm[relaxed.usable][:, None]
    board_xy = pose.inverse().apply_points(points)
    edge_distance = np.minimum(BOARD_HALF_WIDTH_MM - np.abs(board_xy[:, 0]),
                               BOARD_HALF_HEIGHT_MM - np.abs(board_xy[:, 1]))
    assert (edge_distance > BOARD_MARGIN_MM).all()
    assert np.allclose(board_xy[:, 2], 0.0, atol=1e-6)
    # A ring of covered but not usable pixels (the edge margin) exists.
    assert (relaxed.covered & ~relaxed.usable).any()
