"""
Calibration targets (spheres and flat rectangular boards), exact ray
intersections, and the per-pixel prediction of where a target will be seen.

Conventions
-----------
- All geometry here is in the sensor (camera) frame unless a name says
  otherwise: x right, y down, z along the optical axis, millimeters. Rays start
  at the camera center (the origin) and have unit direction, so the "range" of a
  hit is the Euclidean distance from the camera center to the hit point.
- Sphere normals are outward (from the center to the surface point).
- A board is the rectangle |x| <= half_width, |y| <= half_height in its own
  z = 0 plane. Its outward normal is +z of the board frame, and "facing the
  camera" means the outward normal points toward the camera, so that
  n . d < 0 for a ray direction d leaving the camera. A ray that reaches the
  plane from behind (n . d > 0) is a miss. This is the same rule in
  ray_plane_range and predict_board_coverage.
- The cosine of the incidence angle is the cosine of the angle between the
  outward normal and the reversed ray, -d, clipped to [0, 1].
- Missed pixels carry NaN range and NaN incidence cosine and False masks.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from sphcal.geometry.camera import PinholeCamera
from sphcal.geometry.transforms import RigidTransform

PARALLEL_TOLERANCE = 1e-12
"""Smallest |d . n| treated as a ray that is not parallel to a plane. Rays with
|d . n| at or below it are reported as misses instead of dividing by ~0."""

ZERO_LENGTH_TOLERANCE_MM = 1e-12
"""Smallest vector length (mm) treated as nonzero when normalizing a vector."""

BOARD_NORMAL_IN_BOARD_FRAME = (0.0, 0.0, 1.0)
"""The outward normal of a board expressed in the board's own frame (+z)."""

MAX_INCIDENCE_CUTOFF_DEG = 90.0
"""Largest meaningful incidence cutoff in degrees (grazing incidence); the
cutoff is validated against it."""


@dataclass(frozen=True)
class SphereTarget:
    """A sphere of known radius (its center is given per pose, not stored here)."""

    radius_mm: float


@dataclass(frozen=True)
class BoardTarget:
    """A flat rectangle |x| <= half_width_mm, |y| <= half_height_mm at z = 0 of
    the board frame, outward normal +z."""

    half_width_mm: float
    half_height_mm: float


@dataclass(frozen=True)
class CoverageParameters:
    """Exclusion rules that turn predicted coverage into usable samples."""

    incidence_cutoff_deg: float = 55.0
    """Samples whose incidence angle exceeds this are not usable (D-10 discussion)."""
    silhouette_margin_px: float = 6.0
    """Sphere pixels within this many pixels of the silhouette are not usable."""
    board_edge_margin_mm: float = 10.0
    """Board points within this many millimeters of the board edge (measured in
    board coordinates, not in pixels) are not usable."""


@dataclass
class PredictedCoverage:
    """One target in one frame, per native pixel."""

    range_mm: np.ndarray            # (H, W), NaN where the ray misses
    cos_incidence: np.ndarray       # (H, W), NaN where miss
    usable: np.ndarray              # (H, W) bool: hit, inside cut-off, outside margins
    covered: np.ndarray             # (H, W) bool: hit at all (predicted coverage regardless of cut-off)
    curvature_per_mm: float         # 1/R for a sphere, 0 for a board


# ---------------------------------------------------------------------------
# Ray intersections
# ---------------------------------------------------------------------------

def ray_sphere_near_range(ray_dirs, center, radius) -> tuple[np.ndarray, np.ndarray]:
    """
    Near intersection of rays from the origin with a sphere.

    ray_dirs: (..., 3) unit directions. center: (3,) sphere center (mm).
    radius: sphere radius (mm).
    Solves |t d - c|^2 = R^2, i.e. t^2 - 2 t (d . c) + (|c|^2 - R^2) = 0, and
    takes the smaller root t = (d . c) - sqrt((d . c)^2 - |c|^2 + R^2).
    Returns (range_mm, hit): hit is False where the discriminant is negative or
    the smaller root is not positive (sphere behind the camera, or camera inside
    the sphere); range_mm is NaN where hit is False. Shape is ray_dirs.shape[:-1].
    """
    d = np.asarray(ray_dirs, dtype=np.float64)
    c = np.asarray(center, dtype=np.float64).reshape(3)
    projection = d @ c                                   # d . c
    discriminant = projection ** 2 - (c @ c - float(radius) ** 2)
    has_roots = discriminant >= 0.0
    root = np.sqrt(np.where(has_roots, discriminant, 0.0))
    near = projection - root
    hit = has_roots & (near > 0.0)
    return np.where(hit, near, np.nan), hit


def ray_plane_range(ray_dirs, plane_point, plane_normal) -> tuple[np.ndarray, np.ndarray]:
    """
    Intersection of rays from the origin with the plane through plane_point
    with outward unit normal plane_normal.

    t = (p0 . n) / (d . n). hit requires |d . n| > PARALLEL_TOLERANCE (not
    parallel), t > 0 (in front of the camera) and n . d < 0 (the surface faces
    the camera: the outward normal points toward it). Returns (range_mm, hit)
    with NaN range where hit is False. Shape is ray_dirs.shape[:-1].
    """
    d = np.asarray(ray_dirs, dtype=np.float64)
    p0 = np.asarray(plane_point, dtype=np.float64).reshape(3)
    n = np.asarray(plane_normal, dtype=np.float64).reshape(3)
    denominator = d @ n
    facing = denominator < -PARALLEL_TOLERANCE           # n . d < 0 and not parallel
    safe_denominator = np.where(facing, denominator, 1.0)
    t = (p0 @ n) / safe_denominator
    hit = facing & (t > 0.0)
    return np.where(hit, t, np.nan), hit


def sphere_surface_normal(points, center) -> np.ndarray:
    """Outward unit normals (..., 3) at surface points (..., 3) of a sphere with
    the given center. NaN points give NaN normals."""
    p = np.asarray(points, dtype=np.float64)
    radial = p - np.asarray(center, dtype=np.float64).reshape(3)
    length = np.linalg.norm(radial, axis=-1, keepdims=True)
    safe_length = np.where(length > ZERO_LENGTH_TOLERANCE_MM, length, np.nan)
    return radial / safe_length


def cos_incidence(normals, ray_dirs) -> np.ndarray:
    """Cosine of the angle between the normal and the reversed ray, -d, clipped
    to [0, 1] (surfaces seen from behind clip to 0). NaN stays NaN."""
    n = np.asarray(normals, dtype=np.float64)
    d = np.asarray(ray_dirs, dtype=np.float64)
    return np.clip(-np.sum(n * d, axis=-1), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Coverage prediction
# ---------------------------------------------------------------------------

def _cos_cutoff(params: CoverageParameters) -> float:
    """Cosine of the incidence cutoff, validating the cutoff is in [0, 90] degrees."""
    if not 0.0 <= params.incidence_cutoff_deg <= MAX_INCIDENCE_CUTOFF_DEG:
        raise ValueError("incidence_cutoff_deg must be within [0, 90]")
    return float(np.cos(np.radians(params.incidence_cutoff_deg)))


def _distance_from_non_hit_px(hit: np.ndarray) -> np.ndarray:
    """Distance in pixels from each hit pixel to the nearest non-hit pixel (the
    silhouette is the boundary of the hit mask inside the image; the image
    border itself is not a silhouette). Non-hit pixels get 0. If every pixel is
    a hit there is no silhouette and the distance is infinite."""
    if hit.all():
        return np.full(hit.shape, np.inf)
    return ndimage.distance_transform_edt(hit)


def predict_sphere_coverage(camera: PinholeCamera, center_sensor, radius_mm: float,
                            params: CoverageParameters) -> PredictedCoverage:
    """
    Predicted view of a sphere (center in the sensor frame, mm) on the native
    pixel grid. covered = the pixel ray hits the sphere. usable = covered, with
    cos(incidence) >= cos(cutoff), and farther than silhouette_margin_px from
    the nearest non-hit pixel. Incidence is evaluated at the near hit point from
    the outward normal.
    """
    cos_cutoff = _cos_cutoff(params)
    rays = camera.ray_directions()                                   # (H, W, 3)
    range_mm, covered = ray_sphere_near_range(rays, center_sensor, radius_mm)
    points = rays * range_mm[..., None]                              # NaN where miss
    normals = sphere_surface_normal(points, center_sensor)
    cos_inc = np.where(covered, cos_incidence(normals, rays), np.nan)
    far_from_silhouette = _distance_from_non_hit_px(covered) > params.silhouette_margin_px
    with np.errstate(invalid="ignore"):
        inside_cutoff = cos_inc >= cos_cutoff
    usable = covered & inside_cutoff & far_from_silhouette
    return PredictedCoverage(range_mm, cos_inc, usable, covered, 1.0 / float(radius_mm))


def predict_board_coverage(camera: PinholeCamera, board_pose_sensor: RigidTransform,
                           board: BoardTarget, params: CoverageParameters) -> PredictedCoverage:
    """
    Predicted view of a board on the native pixel grid. board_pose_sensor maps
    board-frame points to sensor-frame points. The plane passes through the
    board origin with outward normal R @ (0, 0, 1); rays must reach it from the
    front (n . d < 0). covered = the plane intersection, expressed in the board
    frame, lies inside the rectangle. usable = covered, with
    cos(incidence) >= cos(cutoff), and farther than board_edge_margin_mm from
    the rectangle's edge (distance in board coordinates, mm).
    """
    cos_cutoff = _cos_cutoff(params)
    rays = camera.ray_directions()
    normal_sensor = board_pose_sensor.apply_directions(np.asarray(BOARD_NORMAL_IN_BOARD_FRAME))
    plane_range, plane_hit = ray_plane_range(rays, board_pose_sensor.translation, normal_sensor)
    points_sensor = rays * plane_range[..., None]                    # NaN where no plane hit
    points_board = board_pose_sensor.inverse().apply_points(points_sensor)
    margin_x = board.half_width_mm - np.abs(points_board[..., 0])    # > 0 inside, along x
    margin_y = board.half_height_mm - np.abs(points_board[..., 1])
    distance_to_edge_mm = np.minimum(margin_x, margin_y)
    with np.errstate(invalid="ignore"):
        covered = plane_hit & (distance_to_edge_mm >= 0.0)
    range_mm = np.where(covered, plane_range, np.nan)
    cos_inc = np.where(covered, np.clip(-(rays @ normal_sensor), 0.0, 1.0), np.nan)
    with np.errstate(invalid="ignore"):
        usable = (covered & (cos_inc >= cos_cutoff)
                  & (distance_to_edge_mm > params.board_edge_margin_mm))
    return PredictedCoverage(range_mm, cos_inc, usable, covered, 0.0)
