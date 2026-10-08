"""
Command line: plan the robot poses of a stage-1 capture (one calibration sphere
and boards spread through the working volume of the depth sensor).

    python3 -m sphcal.cli.plan_poses --sensor-in-base sensor_in_base.json \\
        --camera capture.mc --out plan/

What it computes
----------------
The poses are laid out in the SENSOR frame and carried into the robot BASE
frame (the "positioner frame" of the design document) with the sensor-to-base
transform, which is either given or solved from a few bootstrap measurements.

Frames and conventions (millimeters, degrees at the interface)
    sensor frame  the depth camera frame: z optical axis (depth), x right, y down.
    base frame    the robot base frame; all commanded poses are in it.
    sphere pose   the position of the sphere center, which is the tool center
                  point (TCP) when the sphere TCP is active. The tool z axis is
                  the stem direction, pointing from the flange toward the
                  sphere center. It is set along the sensor's viewing ray at
                  the center, away from the sensor, so the stem hides behind the
                  sphere. The tool x axis is the sensor x axis made
                  perpendicular to z; y = z cross x (right-handed).
    board pose    the board frame: origin at the board center, x along the long
                  edge, y along the short edge, z the outward normal, which must
                  face the sensor. It is the robot tool frame when the board
                  tool frame is active. The board starts facing the sensor
                  (normal = minus the viewing ray, x along the sensor x axis made
                  perpendicular to z), then is tilted by the tilt angle about an
                  axis in the board plane at the given azimuth (azimuth 0 is the
                  board x axis, azimuth 90 the board y axis).

Sphere stations. Only ONE sphere is used (decision D-15): radius
``sphere_radius_mm`` (76.2 mm, sphere B). It is swept through a geometric ladder
of depths ("stations"): ``depth_min_mm``, then each next station the previous one
times ``sphere_depth_ratio`` (2 ** 0.25, so the depth doubles every four
stations), up to ``depth_max_mm``. ``depth_max_mm`` is appended as the last
station when the ladder stops short of it by more than ``ladder_end_tolerance_mm``.
The default stations are 300, 357, 424, 505, 600, 714, 849, 1009 and 1100 mm. A
geometric ladder spaces the stations evenly in the logarithm of the depth; the
measurement-space curvature of the sphere, (range / f)^2 / R, then changes by
the same factor (the ratio squared) from one station to the next. An explicit
list ``sphere_depths_mm`` replaces the ladder.

Sphere grid. Each station is a lateral grid of centers in the sensor frame with x
and y spacing equal to ``spacing_in_radii`` times the radius, covering plus/minus
``fov_fill`` times the half field width at that depth. A grid pose whose
predicted silhouette (the exactly projected silhouette circle, see
``silhouette_leaves_image``, kept ``edge_margin_px`` inside the border) would
leave the image is DROPPED, so a large sphere at near range keeps only the poses
it can fit. The center pose (0, 0, depth) is always
planned and always kept, even if the lattice has no point at the center and even
if the sphere is large in the image at that depth.

Board poses. Centers lie on the diagonal of the field at each board depth,
spread over plus/minus ``board_lateral_fill`` times the half field at that depth
(one position is on the optical axis). A combination whose tilted corners
project outside the image (with the edge margin) is skipped and counted.

Outputs in the output directory: ``poses.csv`` (one row per pose, see
``POSE_CSV_COLUMNS``), ``plan_summary.txt`` and ``plan.png``.

Exit code: 0 on success, 2 when an input must be fixed (the message says what).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from sphcal.geometry.camera import PinholeCamera
from sphcal.geometry.transforms import RigidTransform, fit_rigid_transform
from sphcal.io.matcloud import read_matcloud
from sphcal.io.poses import HOMOGENEOUS_MATRIX_ENTRIES, HOMOGENEOUS_MATRIX_SIZE, TARGET_KIND_BOARD, TARGET_KIND_SPHERE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EXIT_OK = 0
"""Exit code when the plan was written."""
EXIT_INPUT_ERROR = 2
"""Exit code when an input has to be fixed by the technician."""

MIN_VECTOR_NORM = 1.0e-9
"""Numerical guard: a vector shorter than this (mm or unitless) is treated as zero."""
ROTATION_ORTHONORMALITY_TOLERANCE = 1.0e-3
"""Largest deviation of R R^T from the identity accepted in a given transform."""
COLLINEARITY_RATIO = 1.0e-3
"""Bootstrap points whose second principal spread is below this fraction of the
first are treated as collinear (the rotation about their line is undetermined)."""
GRID_ROUNDING_TOLERANCE = 1.0e-9
"""Added before flooring the number of grid steps so exact multiples are kept."""
MAX_BOARD_TILT_DEG = 90.0
"""A board tilted this far from facing the sensor is edge-on; tilts must be smaller."""
MIN_BOOTSTRAP_PAIRS = 3
"""A rigid transform needs at least three non-collinear point pairs."""

SENSOR_X_AXIS = np.array([1.0, 0.0, 0.0])
"""Sensor x axis, the reference for the in-plane orientation of tools."""
SENSOR_Y_AXIS = np.array([0.0, 1.0, 0.0])
"""Sensor y axis, used to build a basis of the plane perpendicular to a viewing ray."""
SILHOUETTE_SAMPLES = 180
"""Points on a sphere's silhouette circle that are projected to test whether it
leaves the image (at 2 degrees apart, the sampling error is well below a pixel)."""
BOARD_CORNER_SIGNS = ((1.0, 1.0), (1.0, -1.0), (-1.0, -1.0), (-1.0, 1.0))
"""Signs (x, y) of the four board corners in board coordinates, in drawing order."""

SPHERE_ID_FORMAT = "s{radius:03.0f}_z{depth:04.0f}_{index:03d}"
"""Pose id of a sphere pose: radius, station depth, index within the station.
The radius stays in the id (76.2 mm gives s076) so that a plan with more than
one radius, or a later sphere, cannot collide."""

LADDER_STEPS_PER_OCTAVE = 4
"""Stations per doubling of the depth in the default geometric ladder."""
DEFAULT_SPHERE_DEPTH_RATIO = 2.0 ** (1.0 / LADDER_STEPS_PER_OCTAVE)
"""Default ratio between consecutive sphere stations (about 1.189)."""
DEFAULT_SPHERE_RADIUS_MM = 76.2
"""Radius of the single calibration sphere (sphere B, a 6 inch diameter sphere)."""
BOARD_ID_FORMAT = "b_z{depth:04.0f}_t{tilt:02.0f}_a{azimuth:03.0f}_{index}"
"""Pose id of a board pose: depth, tilt, azimuth, lateral position index."""

POSE_CSV_COLUMNS = (
    ("pose_id", "kind", "radius_mm", "half_width_mm", "half_height_mm", "holdout",
     "base_x_mm", "base_y_mm", "base_z_mm")
    + tuple(f"r{row}{col}" for row in range(3) for col in range(3))
    + ("quat_w", "quat_x", "quat_y", "quat_z",
       "rotvec_x_deg", "rotvec_y_deg", "rotvec_z_deg",
       "sensor_x_mm", "sensor_y_mm", "sensor_z_mm"))
"""Columns of poses.csv. r00..r22 is the tool-to-base rotation matrix row-major;
quat_* is the same rotation as a unit quaternion (w >= 0); rotvec_*_deg is the
rotation vector in degrees; sensor_*_mm is the center in the sensor frame."""

PLAN_CSV_NAME = "poses.csv"
PLAN_SUMMARY_NAME = "plan_summary.txt"
PLAN_FIGURE_NAME = "plan.png"
"""File names written into the output directory."""

PLOT_DPI = 130
"""Resolution of plan.png."""
PLOT_FIGURE_SIZE_IN = (12.0, 6.0)
"""Figure size of plan.png in inches (width, height)."""
PLOT_MARKER_SIZE = 22.0
"""Scatter marker area in points squared."""
PLOT_COLOR_SPHERE = "#0072B2"
PLOT_COLOR_BOARD = "#009E73"
PLOT_COLOR_FRUSTUM = "#444444"
"""Colorblind-safe colors (Okabe-Ito) for the sphere poses, board poses, and the
frustum lines."""
PLOT_HOLDOUT_EDGE_COLOR = "#000000"
"""Edge color of the markers of held-out poses."""
PLOT_FRUSTUM_LINE_WIDTH = 1.0
PLOT_HOLDOUT_LINE_WIDTH = 1.2


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PlanParameters:
    """Every number of the plan; the command-line defaults come from here."""

    depth_min_mm: float = 300.0
    """Nearest sphere station (sensor z); the first rung of the ladder."""
    depth_max_mm: float = 1100.0
    """Farthest sphere station (sensor z); the ladder stops at or below it."""
    sphere_radius_mm: float = DEFAULT_SPHERE_RADIUS_MM
    """Radius of the single calibration sphere."""
    sphere_depth_ratio: float = DEFAULT_SPHERE_DEPTH_RATIO
    """Ratio of consecutive ladder stations; must exceed 1."""
    ladder_end_tolerance_mm: float = 20.0
    """depth_max_mm is appended as a last station when the ladder's last rung is
    below it by more than this. About 2 percent of the far end: a closer rung is
    not worth a separate station."""
    sphere_depths_mm: tuple[float, ...] | None = None
    """Explicit station depths; when given they replace the ladder entirely."""
    spacing_in_radii: float = 1.5
    """Lateral grid spacing as a multiple of the sphere radius."""
    fov_fill: float = 0.8
    """Fraction of the half field covered by sphere centers at each depth, before
    the limit set by the room the sphere's image leaves (see min_positions_per_axis)."""
    min_positions_per_axis: int = 3
    """Least number of sphere-center positions along each image axis at a station.
    The grid never extends past the room the sphere's image leaves inside the image
    border; where that room is shorter than spacing_in_radii allows for this many
    positions, the spacing shrinks instead, so that a near-range station still shows
    the sphere off axis. Such placements overlap in the image, which the curvature
    sweep accepts (decision D-16). Set it to 1 to keep the radius-based spacing."""
    room_bisection_tolerance_mm: float = 0.5
    """Precision of the room search (mm of sphere-center offset). The room is found
    with the same exact silhouette test that drops poses, so a coarser tolerance only
    makes the room slightly smaller, never too large."""
    board_half_size_mm: tuple[float, float] = (120.0, 90.0)
    """Board half width and half height."""
    board_depths_mm: tuple[float, ...] = (350.0, 425.0, 550.0, 800.0, 1050.0)
    """Sensor-z depths of the board centers. The extra near-range depth (425 mm)
    compensates for the single large sphere, which places few distinct poses at
    near range."""
    board_tilts_deg: tuple[float, ...] = (0.0, 20.0, 40.0)
    """Board tilts away from facing the sensor."""
    board_azimuths_deg: tuple[float, ...] = (0.0, 90.0)
    """Azimuths of the tilt axis in the board plane (0 = board x axis)."""
    board_lateral_positions: int = 2
    """Board center positions across the field at each depth."""
    board_lateral_fill: float = 0.5
    """Fraction of the half field covered by board centers at each depth."""
    edge_margin_px: float = 10.0
    """Board corners and sphere silhouettes must project at least this far inside the image."""
    holdout_fraction: float = 0.2
    """Fraction of poses tagged as held out in the holdout column (informational)."""
    seed: int = 0
    """Seed of the random held-out subset."""
    bootstrap_residual_warn_mm: float = 5.0
    """Warn when a bootstrap pair disagrees with the solved transform by more than this."""


@dataclass
class PlannedPose:
    """One planned pose in the sensor frame; converted to the base frame on output."""

    pose_id: str
    kind: str
    radius_mm: float | None
    half_size_mm: tuple[float, float] | None
    center_sensor: np.ndarray
    tool_to_sensor: np.ndarray
    plane_depth_mm: float
    """Station depth (spheres) or board depth plane; the key of the per-depth counts."""
    holdout: bool = False


class PlanInputError(Exception):
    """An input the technician has to fix; the message says what to change."""


# ---------------------------------------------------------------------------
# Inputs: the sensor-to-base transform and the camera
# ---------------------------------------------------------------------------
def _float_vector(value, count: int, what: str) -> np.ndarray:
    try:
        vector = np.asarray([float(x) for x in value], dtype=np.float64)
    except (TypeError, ValueError):
        raise PlanInputError(f"{what} must be a list of {count} numbers, got {value!r}") from None
    if vector.shape != (count,):
        raise PlanInputError(f"{what} must have exactly {count} numbers, got {len(vector)}")
    return vector


def solve_bootstrap(entries: list[dict]) -> tuple[RigidTransform, list[tuple[str, float]]]:
    """Solve the sensor-to-base transform from commanded sphere centers (base
    frame) paired with the same centers measured in the sensor frame. Returns
    the transform and (pose_id, residual in mm) per pair."""
    if len(entries) < MIN_BOOTSTRAP_PAIRS:
        raise PlanInputError(
            f"bootstrap needs at least {MIN_BOOTSTRAP_PAIRS} pairs of base/sensor sphere centers, got "
            f"{len(entries)}; command the sphere to more positions and add them to the file")
    ids, base_points, sensor_points = [], [], []
    for index, entry in enumerate(entries):
        ids.append(str(entry.get("pose_id", f"pair{index}")))
        base_points.append(_float_vector(entry.get("base_xyz"), 3, f"bootstrap[{index}].base_xyz"))
        sensor_points.append(_float_vector(entry.get("sensor_xyz"), 3, f"bootstrap[{index}].sensor_xyz"))
    base = np.array(base_points)
    sensor = np.array(sensor_points)
    spread = np.linalg.svd(base - base.mean(axis=0), compute_uv=False)
    if spread[1] < COLLINEARITY_RATIO * max(spread[0], MIN_VECTOR_NORM):
        raise PlanInputError(
            "the bootstrap points lie on a line, so the rotation about that line is undetermined; "
            "command at least one sphere position well off the line through the others")
    transform = fit_rigid_transform(sensor, base)
    residuals = np.linalg.norm(transform.apply_points(sensor) - base, axis=1)
    return transform, list(zip(ids, (float(r) for r in residuals)))


def load_sensor_in_base(path: Path, residual_warn_mm: float) -> tuple[RigidTransform, str, list[str]]:
    """Read the --sensor-in-base file. Returns the sensor-to-base transform, a
    description of where it came from, and report lines (bootstrap residuals)."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise PlanInputError(f"cannot read --sensor-in-base file {path}: {error.strerror}") from None
    except json.JSONDecodeError as error:
        raise PlanInputError(f"{path} is not valid JSON ({error}); fix the file") from None
    if not isinstance(document, dict) or (("matrix" in document) == ("bootstrap" in document)):
        raise PlanInputError(
            f"{path} must contain exactly one of \"matrix\" (16 numbers, row-major 4x4 sensor-to-base transform) "
            f"or \"bootstrap\" (a list of {{pose_id, base_xyz, sensor_xyz}})")
    if "matrix" in document:
        matrix = _float_vector(document["matrix"], HOMOGENEOUS_MATRIX_ENTRIES, "\"matrix\"").reshape(
            HOMOGENEOUS_MATRIX_SIZE, HOMOGENEOUS_MATRIX_SIZE)
        rotation = matrix[:3, :3]
        if (np.abs(rotation @ rotation.T - np.eye(3)).max() > ROTATION_ORTHONORMALITY_TOLERANCE
                or np.linalg.det(rotation) < 0.0):
            raise PlanInputError(
                f"the rotation block of \"matrix\" in {path} is not a proper rotation; check that the 16 numbers are "
                f"row-major and that the translation (last column) is in millimeters")
        return RigidTransform.from_matrix(matrix), f"matrix from {path}", []
    transform, residuals = solve_bootstrap(document["bootstrap"])
    lines = ["Bootstrap residuals (|T(sensor) - base| per pair):"]
    for pose_id, residual in residuals:
        lines.append(f"  {pose_id}: {residual:.3f} mm")
    worst = max(r for _, r in residuals)
    if worst > residual_warn_mm:
        lines.append(f"WARNING: the worst bootstrap residual is {worst:.2f} mm, above {residual_warn_mm:g} mm. "
                     "Check the sphere center measurements and that the sphere TCP was active during the commands.")
    return transform, f"bootstrap solved from {len(residuals)} pairs in {path}", lines


def camera_from_arguments(args: argparse.Namespace) -> PinholeCamera:
    """The camera from --camera (an .mc capture) or from --fov-deg and --image-size."""
    if args.camera is not None:
        try:
            capture = read_matcloud(args.camera)
        except (OSError, ValueError) as error:
            raise PlanInputError(f"cannot read --camera file {args.camera}: {error}") from None
        if not capture.matrices:
            raise PlanInputError(f"--camera file {args.camera} holds no image array to take the image size from")
        array = capture.matrices.get("XYZ", next(iter(capture.matrices.values())))
        missing = [key for key in ("fx", "fy", "cx", "cy") if key not in capture.header]
        if missing:
            raise PlanInputError(
                f"--camera file {args.camera} has no header entries {missing}; use --fov-deg and --image-size instead")
        return PinholeCamera.from_matcloud_header(capture.header, width_px=array.shape[1], height_px=array.shape[0])
    if args.fov_deg is None or args.image_size is None:
        raise PlanInputError("give the camera either as --camera FILE.mc, or as both --fov-deg H V and --image-size W H")
    width, height = args.image_size
    fov_h, fov_v = args.fov_deg
    # Full field of view angles: focal length = half image size / tan(half angle). Principal point at the center.
    return PinholeCamera(int(width), int(height), (width / 2.0) / np.tan(np.radians(fov_h) / 2.0),
                         (height / 2.0) / np.tan(np.radians(fov_v) / 2.0), width / 2.0, height / 2.0)


def validate_parameters(p: PlanParameters) -> None:
    """Raise PlanInputError, saying what to change, for inconsistent parameters."""
    checks = [
        (0.0 < p.depth_min_mm < p.depth_max_mm, "--depth-min-mm must be positive and smaller than --depth-max-mm"),
        (p.sphere_radius_mm > 0.0, "--sphere-radius-mm must be positive"),
        (p.sphere_depth_ratio > 1.0, "--sphere-depth-ratio must be greater than 1"),
        (p.ladder_end_tolerance_mm >= 0.0, "--ladder-end-tolerance-mm must be zero or more"),
        (p.sphere_depths_mm is None or (len(p.sphere_depths_mm) > 0 and all(d > 0.0 for d in p.sphere_depths_mm)),
         "--sphere-depths-mm must be a list of positive numbers"),
        (p.spacing_in_radii > 0.0, "--spacing-in-radii must be positive"),
        (0.0 < p.fov_fill <= 1.0, "--fov-fill must be in (0, 1]"),
        (p.min_positions_per_axis >= 1, "--min-positions-per-axis must be at least 1"),
        (p.room_bisection_tolerance_mm > 0.0, "--room-bisection-tolerance-mm must be positive"),
        (p.board_lateral_positions >= 1, "--board-lateral-positions must be at least 1"),
        (0.0 <= p.board_lateral_fill <= 1.0, "--board-lateral-fill must be in [0, 1]"),
        (0.0 <= p.holdout_fraction <= 1.0, "--holdout-fraction must be in [0, 1]"),
        (all(d > 0.0 for d in p.board_depths_mm) and len(p.board_depths_mm) > 0, "--board-depths-mm must be positive numbers"),
        (len(p.board_tilts_deg) > 0 and len(p.board_azimuths_deg) > 0, "give at least one board tilt and one azimuth"),
        (all(0.0 <= t < MAX_BOARD_TILT_DEG for t in p.board_tilts_deg), f"--board-tilts-deg must be in [0, {MAX_BOARD_TILT_DEG:g})"),
        (all(h > 0.0 for h in p.board_half_size_mm), "--board-half-size-mm must be positive"),
    ]
    for ok, message in checks:
        if not ok:
            raise PlanInputError(message)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def half_field_at_depth_mm(camera: PinholeCamera, depth_mm: float) -> tuple[float, float]:
    """Half width and half height (mm, sensor x and y) of the image footprint at sensor depth z."""
    return (depth_mm * (camera.width / 2.0) / camera.focal_x_px,
            depth_mm * (camera.height / 2.0) / camera.focal_y_px)


def grid_positions(half_extent_mm: float, spacing_mm: float) -> np.ndarray:
    """Symmetric grid positions with the given spacing inside +/- half_extent
    (a single position at 0 when the extent is shorter than one spacing)."""
    steps = int(np.floor(2.0 * half_extent_mm / spacing_mm + GRID_ROUNDING_TOLERANCE))
    count = steps + 1
    return (np.arange(count) - (count - 1) / 2.0) * spacing_mm


def sphere_fits_in_image(camera: PinholeCamera, center: np.ndarray, radius_mm: float, margin_px: float) -> bool:
    """True when the whole silhouette of a sphere at this center lies margin_px inside the image."""
    probe = PlannedPose(pose_id="probe", kind=TARGET_KIND_SPHERE, radius_mm=radius_mm, half_size_mm=None,
                        center_sensor=center, tool_to_sensor=np.eye(3), plane_depth_mm=float(center[2]))
    return not silhouette_leaves_image(camera, probe, margin_px)


def _largest_fitting_scale(fits, upper: float, tolerance: float) -> float:
    """Largest s in [0, upper] with fits(s) true, by bisection, assuming fits is true
    up to some s* and false beyond it; 0 when even s = 0 does not fit."""
    if not fits(0.0):
        return 0.0
    if fits(upper):
        return upper
    low, high = 0.0, upper
    while high - low > tolerance:
        middle = 0.5 * (low + high)
        if fits(middle):
            low = middle
        else:
            high = middle
    return low


def sphere_center_room_mm(camera: PinholeCamera, depth_mm: float, radius_mm: float, margin_px: float,
                          tolerance_mm: float) -> tuple[float, float]:
    """Half extents (mm, sensor x and y, at sensor depth z) of the rectangle of sphere
    centers whose silhouettes all lie margin_px inside the image.

    Each axis is searched on its own with the exact silhouette test (both signs,
    since the principal point need not be centered); the two extents are then
    shrunk together until the rectangle's corners fit too. Zero when not even the
    center fits."""
    half_x, half_y = half_field_at_depth_mm(camera, depth_mm)

    def fits_at(x: float, y: float) -> bool:
        return all(sphere_fits_in_image(camera, np.array([sx * x, sy * y, depth_mm]), radius_mm, margin_px)
                   for sx in (-1.0, 1.0) for sy in (-1.0, 1.0))

    room_x = _largest_fitting_scale(lambda x: fits_at(x, 0.0), half_x, tolerance_mm)
    room_y = _largest_fitting_scale(lambda y: fits_at(0.0, y), half_y, tolerance_mm)
    if room_x == 0.0 or room_y == 0.0:
        return room_x, room_y
    # Shrink both extents by a common factor until the corners fit; the factor's
    # tolerance is expressed relative to the larger extent.
    scale = _largest_fitting_scale(lambda t: fits_at(t * room_x, t * room_y), 1.0,
                                   tolerance_mm / max(room_x, room_y))
    return scale * room_x, scale * room_y


def station_axis_grid(fov_half_mm: float, room_half_mm: float, radius_spacing_mm: float,
                      min_positions: int) -> np.ndarray:
    """Center positions along one axis of a station: the radius-based spacing over
    the smaller of the field-fill extent and the room, with the spacing shrunk when
    fewer than min_positions would fit (and the room is not zero)."""
    extent = min(fov_half_mm, room_half_mm)
    spacing = radius_spacing_mm
    if min_positions > 1 and extent > 0.0:
        spacing = min(spacing, 2.0 * extent / (min_positions - 1))
    return grid_positions(extent, spacing)


def frame_from_z_axis(z_axis: np.ndarray) -> np.ndarray:
    """Right-handed rotation matrix (columns x, y, z) whose z axis is the given
    unit vector and whose x axis is the sensor x axis made perpendicular to it."""
    x_axis = SENSOR_X_AXIS - (SENSOR_X_AXIS @ z_axis) * z_axis
    norm = np.linalg.norm(x_axis)
    if norm < MIN_VECTOR_NORM:
        raise PlanInputError("a viewing ray is parallel to the sensor x axis; check the camera model")
    x_axis = x_axis / norm
    return np.column_stack([x_axis, np.cross(z_axis, x_axis), z_axis])


def sphere_stations(p: PlanParameters) -> list[float]:
    """Sensor-z depths of the sphere stations, nearest first: the explicit list when
    given, otherwise the geometric ladder depth_min * ratio ** k up to depth_max,
    with depth_max appended when the last rung is more than ladder_end_tolerance_mm
    below it."""
    if p.sphere_depths_mm is not None:
        return [float(depth) for depth in p.sphere_depths_mm]
    stations = []
    rung = 0
    while True:
        # Computed from the rung number, not by repeated multiplication, so rounding does not accumulate.
        depth = p.depth_min_mm * p.sphere_depth_ratio ** rung
        if depth > p.depth_max_mm + GRID_ROUNDING_TOLERANCE:
            break
        stations.append(float(depth))
        rung += 1
    if p.depth_max_mm - stations[-1] > p.ladder_end_tolerance_mm:
        stations.append(float(p.depth_max_mm))
    return stations


def plan_spheres(p: PlanParameters, camera: PinholeCamera) -> tuple[list[PlannedPose], dict[float, list[int]]]:
    """Sphere poses (sensor frame) and, per station depth, [planned, dropped] counts.

    Each station is a lateral grid; rows are visited in a serpentine order so
    consecutive poses are neighbors. Grid poses whose silhouette would leave the
    image are dropped (and counted). The center pose (0, 0, depth) is added when
    the lattice has no point there, is listed first, and is never dropped."""
    poses: list[PlannedPose] = []
    counts: dict[float, list[int]] = {}
    for depth in sphere_stations(p):
        half_x, half_y = half_field_at_depth_mm(camera, depth)
        room_x, room_y = sphere_center_room_mm(camera, depth, p.sphere_radius_mm, p.edge_margin_px,
                                               p.room_bisection_tolerance_mm)
        spacing = p.spacing_in_radii * p.sphere_radius_mm
        xs = station_axis_grid(p.fov_fill * half_x, room_x, spacing, p.min_positions_per_axis)
        ys = station_axis_grid(p.fov_fill * half_y, room_y, spacing, p.min_positions_per_axis)
        candidates = [(float(x), float(y)) for row, y in enumerate(ys) for x in (xs if row % 2 == 0 else xs[::-1])]
        if (0.0, 0.0) not in candidates:
            candidates.insert(0, (0.0, 0.0))
        counts[depth] = [len(candidates), 0]
        index = 0
        for x, y in candidates:
            center = np.array([x, y, depth])
            ray = center / np.linalg.norm(center)
            pose = PlannedPose(
                pose_id=SPHERE_ID_FORMAT.format(radius=p.sphere_radius_mm, depth=depth, index=index),
                kind=TARGET_KIND_SPHERE, radius_mm=p.sphere_radius_mm, half_size_mm=None, center_sensor=center,
                tool_to_sensor=frame_from_z_axis(ray), plane_depth_mm=depth)
            is_center = (x, y) == (0.0, 0.0)
            if not is_center and silhouette_leaves_image(camera, pose, p.edge_margin_px):
                counts[depth][1] += 1
                continue
            poses.append(pose)
            index += 1
    return poses, counts


def board_corners_in_view(camera: PinholeCamera, center: np.ndarray, rotation: np.ndarray,
                          half_size_mm: tuple[float, float], margin_px: float) -> bool:
    """True when all four corners are in front of the camera and project at least
    margin_px inside the image."""
    corners = np.array([center + rotation @ np.array([sx * half_size_mm[0], sy * half_size_mm[1], 0.0])
                        for sx, sy in BOARD_CORNER_SIGNS])
    u, v, in_front = camera.project(corners)
    if not in_front.all():
        return False
    last_column, last_row = camera.width - 1, camera.height - 1
    return bool(np.all((u >= margin_px) & (u <= last_column - margin_px)
                       & (v >= margin_px) & (v <= last_row - margin_px)))


def plan_boards(p: PlanParameters, camera: PinholeCamera) -> tuple[list[PlannedPose], dict[float, list[int]]]:
    """Board poses (sensor frame) and, per depth, [planned, skipped] counts.
    A tilt of zero is planned once (the azimuth does not matter)."""
    poses: list[PlannedPose] = []
    counts: dict[float, list[int]] = {}
    fractions = np.linspace(-1.0, 1.0, p.board_lateral_positions) if p.board_lateral_positions > 1 else np.zeros(1)
    for depth in p.board_depths_mm:
        half_x, half_y = half_field_at_depth_mm(camera, depth)
        counts[depth] = [0, 0]
        for tilt in p.board_tilts_deg:
            azimuths = p.board_azimuths_deg[:1] if tilt == 0.0 else p.board_azimuths_deg
            for azimuth in azimuths:
                for index, fraction in enumerate(fractions):
                    counts[depth][0] += 1
                    center = np.array([fraction * p.board_lateral_fill * half_x,
                                       fraction * p.board_lateral_fill * half_y, depth])
                    ray = center / np.linalg.norm(center)
                    facing = frame_from_z_axis(-ray)
                    axis = np.cos(np.radians(azimuth)) * facing[:, 0] + np.sin(np.radians(azimuth)) * facing[:, 1]
                    rotation = Rotation.from_rotvec(axis * np.radians(tilt)).as_matrix() @ facing
                    if not board_corners_in_view(camera, center, rotation, p.board_half_size_mm, p.edge_margin_px):
                        counts[depth][1] += 1
                        continue
                    poses.append(PlannedPose(
                        pose_id=BOARD_ID_FORMAT.format(depth=depth, tilt=tilt, azimuth=azimuth, index=index),
                        kind=TARGET_KIND_BOARD, radius_mm=None, half_size_mm=p.board_half_size_mm,
                        center_sensor=center, tool_to_sensor=rotation, plane_depth_mm=depth))
    return poses, counts


def silhouette_leaves_image(camera: PinholeCamera, pose: PlannedPose, margin_px: float) -> bool:
    """True when a sphere's silhouette would cross the image border, or come
    closer to it than margin_px.

    The silhouette of a sphere of radius R seen from the camera center at range
    rho is a circle of radius R sqrt(1 - R^2/rho^2) centered at (1 - R^2/rho^2)
    times the sphere center, in the plane perpendicular to the viewing ray. The
    circle is sampled at SILHOUETTE_SAMPLES points and projected exactly. (The
    first version scaled a circle of radius f R / sqrt(rho^2 - R^2) around the
    projected center, which understates the perspective stretching of the
    silhouette away from the optical axis by up to a few pixels.) A camera
    inside the sphere counts as leaving the image."""
    center = pose.center_sensor
    rho = float(np.linalg.norm(center))
    if rho <= pose.radius_mm:
        return True
    axis = center / rho
    first = np.cross(axis, SENSOR_Y_AXIS)
    if np.linalg.norm(first) < MIN_VECTOR_NORM:
        first = np.cross(axis, SENSOR_X_AXIS)
    first = first / np.linalg.norm(first)
    second = np.cross(axis, first)
    shrink = 1.0 - (pose.radius_mm / rho) ** 2
    angles = np.linspace(0.0, 2.0 * np.pi, SILHOUETTE_SAMPLES, endpoint=False)
    points = (center * shrink + pose.radius_mm * np.sqrt(shrink)
              * (np.cos(angles)[:, None] * first + np.sin(angles)[:, None] * second))
    u, v, in_front = camera.project(points)
    if not in_front.all():
        return True
    return bool(u.min() < margin_px or u.max() > camera.width - 1 - margin_px
                or v.min() < margin_px or v.max() > camera.height - 1 - margin_px)


def tag_holdout(poses: list[PlannedPose], fraction: float, seed: int) -> None:
    """Tag a random subset (fraction of all poses) as held out; informational only."""
    count = int(round(fraction * len(poses)))
    chosen = np.random.default_rng(seed).choice(len(poses), size=count, replace=False) if poses else []
    for index in chosen:
        poses[int(index)].holdout = True


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
def pose_row(pose: PlannedPose, sensor_to_base: RigidTransform) -> list:
    """One poses.csv row (see POSE_CSV_COLUMNS) in the base frame."""
    center_base = sensor_to_base.apply_points(pose.center_sensor)
    rotation = sensor_to_base.rotation @ pose.tool_to_sensor
    quat_xyzw = Rotation.from_matrix(rotation).as_quat()
    quat_wxyz = np.roll(quat_xyzw, 1)
    if quat_wxyz[0] < 0.0:
        quat_wxyz = -quat_wxyz
    rotvec_deg = np.degrees(Rotation.from_matrix(rotation).as_rotvec())
    half = pose.half_size_mm
    return ([pose.pose_id, pose.kind, "" if pose.radius_mm is None else pose.radius_mm,
             "" if half is None else half[0], "" if half is None else half[1], int(pose.holdout)]
            + [float(x) for x in np.concatenate([center_base, rotation.reshape(-1), quat_wxyz, rotvec_deg,
                                                 pose.center_sensor])])


def write_poses_csv(path: Path, poses: list[PlannedPose], sensor_to_base: RigidTransform) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(POSE_CSV_COLUMNS)
        for pose in poses:
            writer.writerow(pose_row(pose, sensor_to_base))


def summary_text(p: PlanParameters, camera: PinholeCamera, poses: list[PlannedPose],
                 sphere_counts: dict[float, list[int]], board_counts: dict[float, list[int]], source: str,
                 bootstrap_lines: list[str]) -> str:
    """The plan summary: counts per sphere station and board depth, dropped spheres, skipped boards, total."""
    lines = ["Stage-1 pose plan", f"Sensor-to-base transform: {source}"]
    lines += bootstrap_lines
    half_h, half_v = camera.half_angles_degrees()
    lines.append(f"Camera: {camera.width} x {camera.height} px, half field {half_h:.1f} x {half_v:.1f} deg")
    lines.append("")
    lines.append("Sphere poses per station:")
    lines.append(f"  {'radius_mm':>9} {'depth_mm':>9} {'planned':>8} {'kept':>6} {'dropped':>8} {'held out':>9}")
    spheres = [q for q in poses if q.kind == TARGET_KIND_SPHERE]
    dropped_total = 0
    for depth, (planned, dropped) in sphere_counts.items():
        station = [q for q in spheres if q.plane_depth_mm == depth]
        dropped_total += dropped
        lines.append(f"  {p.sphere_radius_mm:9.1f} {depth:9.0f} {planned:8d} {len(station):6d} {dropped:8d} "
                     f"{sum(q.holdout for q in station):9d}")
    if dropped_total:
        lines.append(f"  {dropped_total} sphere poses were dropped because the sphere would be partly outside the "
                     f"image (margin {p.edge_margin_px:g} px); the center pose of each station is always kept.")
    lines.append("")
    lines.append("Board poses per depth:")
    lines.append(f"  {'depth_mm':>9} {'planned':>8} {'kept':>6} {'skipped':>8} {'held out':>9}")
    boards = [q for q in poses if q.kind == TARGET_KIND_BOARD]
    skipped_total = 0
    for depth, (planned, skipped) in board_counts.items():
        kept = [q for q in boards if q.plane_depth_mm == depth]
        skipped_total += skipped
        lines.append(f"  {depth:9.0f} {planned:8d} {len(kept):6d} {skipped:8d} {sum(q.holdout for q in kept):9d}")
    if skipped_total:
        lines.append(f"  {skipped_total} board combinations were skipped because a corner would leave the field of "
                     f"view (margin {p.edge_margin_px:g} px); use fewer lateral positions, a smaller tilt, "
                     "or a larger depth to keep them.")
    clipped = sum(silhouette_leaves_image(camera, q, p.edge_margin_px) for q in spheres)
    lines.append("")
    if clipped:
        lines.append(f"{clipped} of {len(spheres)} sphere poses (center poses, which are always kept) would still be "
                     f"partly outside the image (margin {p.edge_margin_px:g} px); the sphere is too "
                     "large for the field at those depths, so move the nearest station back or accept the clipping.")
    lines.append(f"Total: {len(poses)} poses ({len(spheres)} sphere, {len(boards)} board), "
                 f"{sum(q.holdout for q in poses)} tagged held out (seed {p.seed}).")
    return "\n".join(lines) + "\n"


def write_plan_figure(path: Path, p: PlanParameters, camera: PinholeCamera, poses: list[PlannedPose]) -> None:
    """Side view (x versus z) and front view (x versus y, y down as in the image)
    of the planned centers in the sensor frame, with the frustum edges."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, (side, front) = plt.subplots(1, 2, figsize=PLOT_FIGURE_SIZE_IN)
    half_x_max, half_y_max = half_field_at_depth_mm(camera, p.depth_max_mm)
    half_x_min, half_y_min = half_field_at_depth_mm(camera, p.depth_min_mm)
    line = dict(color=PLOT_COLOR_FRUSTUM, linewidth=PLOT_FRUSTUM_LINE_WIDTH)
    # Side view: the two frustum edges in the x-z plane, from the sensor to the maximum depth.
    for sign in (-1.0, 1.0):
        side.plot([0.0, sign * half_x_max], [0.0, p.depth_max_mm], **line)
    side.plot([-half_x_min, half_x_min], [p.depth_min_mm, p.depth_min_mm], linestyle=":", **line)
    side.plot([-half_x_max, half_x_max], [p.depth_max_mm, p.depth_max_mm], linestyle=":", **line)
    # Front view: the image footprint at the minimum and maximum depth, with the corner edges between them.
    for half_x, half_y in ((half_x_min, half_y_min), (half_x_max, half_y_max)):
        front.plot([-half_x, half_x, half_x, -half_x, -half_x], [-half_y, -half_y, half_y, half_y, -half_y], **line)
    for sx, sy in BOARD_CORNER_SIGNS:
        front.plot([sx * half_x_min, sx * half_x_max], [sy * half_y_min, sy * half_y_max], linestyle=":", **line)
    groups = [("sphere r=%g mm" % p.sphere_radius_mm, PLOT_COLOR_SPHERE, "o", lambda q: q.kind == TARGET_KIND_SPHERE),
              ("board", PLOT_COLOR_BOARD, "s", lambda q: q.kind == TARGET_KIND_BOARD)]
    for label, color, marker, selector in groups:
        chosen = [q for q in poses if selector(q)]
        if not chosen:
            continue
        centers = np.array([q.center_sensor for q in chosen])
        edges = [PLOT_HOLDOUT_EDGE_COLOR if q.holdout else color for q in chosen]
        widths = [PLOT_HOLDOUT_LINE_WIDTH if q.holdout else 0.0 for q in chosen]
        for axes, columns in ((side, (0, 2)), (front, (0, 1))):
            axes.scatter(centers[:, columns[0]], centers[:, columns[1]], s=PLOT_MARKER_SIZE, marker=marker,
                         c=color, edgecolors=edges, linewidths=widths, label=label)
    side.set(xlabel="sensor x (mm)", ylabel="sensor z, depth (mm)", title="Side view (x versus z)")
    front.set(xlabel="sensor x (mm)", ylabel="sensor y (mm, down)", title="Front view (x versus y)")
    front.invert_yaxis()
    for axes in (side, front):
        axes.set_aspect("equal", adjustable="datalim")
        axes.grid(True, alpha=0.3)
    side.legend(loc="lower right", fontsize="small", title="black edge = held out")
    figure.tight_layout()
    figure.savefig(path, dpi=PLOT_DPI)
    plt.close(figure)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    d = PlanParameters()
    parser = argparse.ArgumentParser(
        description="Plan the robot poses of a stage-1 capture: sphere and board poses spread through the depth "
                    "sensor's working volume, written as poses.csv, plan_summary.txt and plan.png.")
    parser.add_argument("--sensor-in-base", required=True, type=Path, metavar="PATH",
                        help="JSON with {\"matrix\": [16 floats, row-major 4x4 sensor-to-base]} or {\"bootstrap\": "
                             "[{\"pose_id\", \"base_xyz\", \"sensor_xyz\"}, ... at least 3 non-collinear]}")
    parser.add_argument("--camera", type=Path, metavar="PATH",
                        help=".mc capture file whose header gives fx, fy, cx, cy and whose array gives the image size")
    parser.add_argument("--fov-deg", type=float, nargs=2, metavar=("H", "V"),
                        help="full horizontal and vertical field of view in degrees (with --image-size)")
    parser.add_argument("--image-size", type=int, nargs=2, metavar=("W", "H"), help="image width and height in pixels")
    parser.add_argument("--depth-min-mm", type=float, default=d.depth_min_mm)
    parser.add_argument("--depth-max-mm", type=float, default=d.depth_max_mm)
    parser.add_argument("--sphere-radius-mm", type=float, default=d.sphere_radius_mm,
                        help="radius of the single calibration sphere")
    parser.add_argument("--sphere-depth-ratio", type=float, default=d.sphere_depth_ratio,
                        help="ratio of consecutive sphere stations of the geometric ladder from --depth-min-mm")
    parser.add_argument("--ladder-end-tolerance-mm", type=float, default=d.ladder_end_tolerance_mm,
                        help="--depth-max-mm is appended as a last station when the ladder ends further below it")
    parser.add_argument("--sphere-depths-mm", type=float, nargs="+", default=None,
                        help="explicit sphere station depths; replaces the ladder")
    parser.add_argument("--spacing-in-radii", type=float, default=d.spacing_in_radii,
                        help="grid spacing as a multiple of the sphere radius")
    parser.add_argument("--fov-fill", type=float, default=d.fov_fill,
                        help="fraction of the half field covered by sphere centers at each depth")
    parser.add_argument("--min-positions-per-axis", type=int, default=d.min_positions_per_axis,
                        help="least number of sphere positions along each image axis at a station; the spacing "
                             "shrinks where the sphere's image leaves little room")
    parser.add_argument("--room-bisection-tolerance-mm", type=float, default=d.room_bisection_tolerance_mm,
                        help="precision of the search for the room the sphere's image leaves inside the border")
    parser.add_argument("--board-half-size-mm", type=float, nargs=2, default=d.board_half_size_mm,
                        metavar=("HALF_WIDTH", "HALF_HEIGHT"))
    parser.add_argument("--board-depths-mm", type=float, nargs="+", default=d.board_depths_mm)
    parser.add_argument("--board-tilts-deg", type=float, nargs="+", default=d.board_tilts_deg)
    parser.add_argument("--board-azimuths-deg", type=float, nargs="+", default=d.board_azimuths_deg)
    parser.add_argument("--board-lateral-positions", type=int, default=d.board_lateral_positions,
                        help="board positions spread across the field at each depth")
    parser.add_argument("--board-lateral-fill", type=float, default=d.board_lateral_fill,
                        help="fraction of the half field covered by board centers at each depth")
    parser.add_argument("--edge-margin-px", type=float, default=d.edge_margin_px,
                        help="board corners and sphere silhouettes must project this far inside the image")
    parser.add_argument("--holdout-fraction", type=float, default=d.holdout_fraction)
    parser.add_argument("--seed", type=int, default=d.seed, help="seed of the random held-out subset")
    parser.add_argument("--bootstrap-residual-warn-mm", type=float, default=d.bootstrap_residual_warn_mm)
    parser.add_argument("--out", required=True, type=Path, metavar="DIR", help="output directory")
    return parser


def parameters_from_arguments(args: argparse.Namespace) -> PlanParameters:
    return PlanParameters(
        depth_min_mm=args.depth_min_mm, depth_max_mm=args.depth_max_mm, sphere_radius_mm=args.sphere_radius_mm,
        sphere_depth_ratio=args.sphere_depth_ratio, ladder_end_tolerance_mm=args.ladder_end_tolerance_mm,
        sphere_depths_mm=None if args.sphere_depths_mm is None else tuple(args.sphere_depths_mm),
        spacing_in_radii=args.spacing_in_radii, fov_fill=args.fov_fill,
        min_positions_per_axis=args.min_positions_per_axis, room_bisection_tolerance_mm=args.room_bisection_tolerance_mm,
        board_half_size_mm=tuple(args.board_half_size_mm), board_depths_mm=tuple(args.board_depths_mm),
        board_tilts_deg=tuple(args.board_tilts_deg), board_azimuths_deg=tuple(args.board_azimuths_deg),
        board_lateral_positions=args.board_lateral_positions, board_lateral_fill=args.board_lateral_fill,
        edge_margin_px=args.edge_margin_px, holdout_fraction=args.holdout_fraction, seed=args.seed,
        bootstrap_residual_warn_mm=args.bootstrap_residual_warn_mm)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        params = parameters_from_arguments(args)
        validate_parameters(params)
        sensor_to_base, source, bootstrap_lines = load_sensor_in_base(args.sensor_in_base,
                                                                      params.bootstrap_residual_warn_mm)
        camera = camera_from_arguments(args)
        poses, sphere_counts = plan_spheres(params, camera)
        board_poses, board_counts = plan_boards(params, camera)
        poses += board_poses
        ids = [q.pose_id for q in poses]
        if len(set(ids)) != len(ids):
            raise PlanInputError("two planned poses got the same pose id (stations, depths or tilts that round to the "
                                 "same whole millimeter or degree); space the depths and angles further apart")
    except PlanInputError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    tag_holdout(poses, params.holdout_fraction, params.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    write_poses_csv(args.out / PLAN_CSV_NAME, poses, sensor_to_base)
    text = summary_text(params, camera, poses, sphere_counts, board_counts, source, bootstrap_lines)
    (args.out / PLAN_SUMMARY_NAME).write_text(text, encoding="utf-8")
    print(text, end="")
    try:
        write_plan_figure(args.out / PLAN_FIGURE_NAME, params, camera, poses)
    except ModuleNotFoundError as error:
        # The picture is a convenience; the plan itself is complete without it.
        print(f"WARNING: {PLAN_FIGURE_NAME} not written because the plotting package is missing "
              f"({error}); install matplotlib (pip install matplotlib) to get the picture.", file=sys.stderr)
        print(f"Wrote {args.out / PLAN_CSV_NAME} and {args.out / PLAN_SUMMARY_NAME}")
        return EXIT_OK
    print(f"Wrote {args.out / PLAN_CSV_NAME}, {args.out / PLAN_SUMMARY_NAME} and {args.out / PLAN_FIGURE_NAME}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
