"""
Command line: plan the robot poses of a stage-1 capture (sphere and board
targets spread through the working volume of the depth sensor).

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

Sphere grid. Each depth plane is a lateral grid of centers in the sensor frame
with x and y spacing equal to ``spacing_in_radii`` times the radius in use,
covering plus/minus ``fov_fill`` times the half field width at that depth. The
near radius is planned from the minimum depth up to the switch depth and the
far radius from the overlap band below the switch depth up to the maximum depth,
so both radii are captured inside the overlap band.

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
BOARD_CORNER_SIGNS = ((1.0, 1.0), (1.0, -1.0), (-1.0, -1.0), (-1.0, 1.0))
"""Signs (x, y) of the four board corners in board coordinates, in drawing order."""

SPHERE_ID_FORMAT = "s{radius:03.0f}_z{depth:04.0f}_{index:03d}"
"""Pose id of a sphere pose: radius, depth plane, index within the plane."""
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
PLOT_COLOR_NEAR_SPHERE = "#0072B2"
PLOT_COLOR_FAR_SPHERE = "#D55E00"
PLOT_COLOR_BOARD = "#009E73"
PLOT_COLOR_FRUSTUM = "#444444"
"""Colorblind-safe colors (Okabe-Ito) for the near-radius spheres, far-radius
spheres, boards, and the frustum lines."""
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
    """Nearest sphere depth plane (sensor z)."""
    depth_max_mm: float = 1100.0
    """Farthest sphere depth plane (sensor z)."""
    near_radius_mm: float = 40.0
    """Radius of the small sphere, planned from depth_min up to the switch depth."""
    far_radius_mm: float = 80.0
    """Radius of the large sphere, planned from the overlap band up to depth_max."""
    radius_switch_depth_mm: float = 550.0
    """Depth at which the plan changes from the near to the far radius."""
    overlap_band_mm: float = 50.0
    """Width of the band below the switch depth in which both radii are planned."""
    spacing_in_radii: float = 1.5
    """Lateral grid spacing as a multiple of the radius in use."""
    fov_fill: float = 0.8
    """Fraction of the half field covered by sphere centers at each depth."""
    depth_planes_near: int = 3
    """Number of depth planes for the near radius (switch depth included)."""
    depth_planes_far: int = 4
    """Number of depth planes for the far radius (overlap band start included)."""
    board_half_size_mm: tuple[float, float] = (120.0, 90.0)
    """Board half width and half height."""
    board_depths_mm: tuple[float, ...] = (350.0, 550.0, 800.0, 1050.0)
    """Sensor-z depths of the board centers."""
    board_tilts_deg: tuple[float, ...] = (0.0, 20.0, 40.0)
    """Board tilts away from facing the sensor."""
    board_azimuths_deg: tuple[float, ...] = (0.0, 90.0)
    """Azimuths of the tilt axis in the board plane (0 = board x axis)."""
    board_lateral_positions: int = 2
    """Board center positions across the field at each depth."""
    board_lateral_fill: float = 0.5
    """Fraction of the half field covered by board centers at each depth."""
    edge_margin_px: float = 10.0
    """Board corners must project at least this far inside the image."""
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
        (p.depth_min_mm < p.radius_switch_depth_mm < p.depth_max_mm,
         "--radius-switch-depth-mm must lie between --depth-min-mm and --depth-max-mm"),
        (0.0 <= p.overlap_band_mm < p.radius_switch_depth_mm - p.depth_min_mm,
         "--overlap-band-mm must be zero or more and smaller than the distance from the minimum depth to the switch depth"),
        (p.near_radius_mm > 0.0 and p.far_radius_mm > 0.0, "sphere radii must be positive"),
        (p.spacing_in_radii > 0.0, "--spacing-in-radii must be positive"),
        (0.0 < p.fov_fill <= 1.0, "--fov-fill must be in (0, 1]"),
        (p.depth_planes_near >= 1 and p.depth_planes_far >= 1, "depth plane counts must be at least 1"),
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


def frame_from_z_axis(z_axis: np.ndarray) -> np.ndarray:
    """Right-handed rotation matrix (columns x, y, z) whose z axis is the given
    unit vector and whose x axis is the sensor x axis made perpendicular to it."""
    x_axis = SENSOR_X_AXIS - (SENSOR_X_AXIS @ z_axis) * z_axis
    norm = np.linalg.norm(x_axis)
    if norm < MIN_VECTOR_NORM:
        raise PlanInputError("a viewing ray is parallel to the sensor x axis; check the camera model")
    x_axis = x_axis / norm
    return np.column_stack([x_axis, np.cross(z_axis, x_axis), z_axis])


def sphere_depth_planes(p: PlanParameters) -> list[tuple[float, float]]:
    """(radius, depth) of every sphere plane. The near radius covers depth_min
    to the switch depth; the far radius starts one overlap band below the switch depth."""
    near = [(p.near_radius_mm, d) for d in np.linspace(p.depth_min_mm, p.radius_switch_depth_mm, p.depth_planes_near)]
    far = [(p.far_radius_mm, d) for d in np.linspace(p.radius_switch_depth_mm - p.overlap_band_mm,
                                                     p.depth_max_mm, p.depth_planes_far)]
    return [(float(r), float(d)) for r, d in near + far]


def plan_spheres(p: PlanParameters, camera: PinholeCamera) -> list[PlannedPose]:
    """Sphere poses on a lateral grid at each depth plane (sensor frame). Rows are
    visited in a serpentine order so consecutive poses are neighbors."""
    poses: list[PlannedPose] = []
    for radius, depth in sphere_depth_planes(p):
        half_x, half_y = half_field_at_depth_mm(camera, depth)
        spacing = p.spacing_in_radii * radius
        xs = grid_positions(p.fov_fill * half_x, spacing)
        ys = grid_positions(p.fov_fill * half_y, spacing)
        index = 0
        for row, y in enumerate(ys):
            for x in (xs if row % 2 == 0 else xs[::-1]):
                center = np.array([x, y, depth])
                ray = center / np.linalg.norm(center)
                poses.append(PlannedPose(
                    pose_id=SPHERE_ID_FORMAT.format(radius=radius, depth=depth, index=index),
                    kind=TARGET_KIND_SPHERE, radius_mm=radius, half_size_mm=None, center_sensor=center,
                    tool_to_sensor=frame_from_z_axis(ray), plane_depth_mm=depth))
                index += 1
    return poses


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
    """Approximate test whether a sphere's silhouette would cross the image border:
    the apparent radius in pixels is f R / sqrt(rho^2 - R^2) for range rho."""
    rho = float(np.linalg.norm(pose.center_sensor))
    apparent = camera.focal_x_px * pose.radius_mm / np.sqrt(max(rho ** 2 - pose.radius_mm ** 2, MIN_VECTOR_NORM))
    u, v, _ = camera.project(pose.center_sensor)
    apparent_y = apparent * camera.focal_y_px / camera.focal_x_px
    return bool(u - apparent < margin_px or u + apparent > camera.width - 1 - margin_px
                or v - apparent_y < margin_px or v + apparent_y > camera.height - 1 - margin_px)


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
                 board_counts: dict[float, list[int]], source: str, bootstrap_lines: list[str]) -> str:
    """The plan summary: counts per depth plane and kind, skipped boards, total."""
    lines = ["Stage-1 pose plan", f"Sensor-to-base transform: {source}"]
    lines += bootstrap_lines
    half_h, half_v = camera.half_angles_degrees()
    lines.append(f"Camera: {camera.width} x {camera.height} px, half field {half_h:.1f} x {half_v:.1f} deg")
    lines.append("")
    lines.append("Sphere poses per depth plane:")
    lines.append(f"  {'radius_mm':>9} {'depth_mm':>9} {'count':>6} {'held out':>9}")
    spheres = [q for q in poses if q.kind == TARGET_KIND_SPHERE]
    for radius, depth in sphere_depth_planes(p):
        plane = [q for q in spheres if q.radius_mm == radius and q.plane_depth_mm == depth]
        lines.append(f"  {radius:9.0f} {depth:9.0f} {len(plane):6d} {sum(q.holdout for q in plane):9d}")
    lines.append("")
    lines.append("Board poses per depth plane:")
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
        lines.append(f"{clipped} of {len(spheres)} sphere poses would be partly outside the image (approximate, "
                     f"margin {p.edge_margin_px:g} px); lower --fov-fill if the sphere must be fully visible.")
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
    groups = [("sphere r=%g mm" % p.near_radius_mm, PLOT_COLOR_NEAR_SPHERE, "o",
               lambda q: q.kind == TARGET_KIND_SPHERE and q.radius_mm == p.near_radius_mm),
              ("sphere r=%g mm" % p.far_radius_mm, PLOT_COLOR_FAR_SPHERE, "^",
               lambda q: q.kind == TARGET_KIND_SPHERE and q.radius_mm == p.far_radius_mm),
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
    parser.add_argument("--near-radius-mm", type=float, default=d.near_radius_mm)
    parser.add_argument("--far-radius-mm", type=float, default=d.far_radius_mm)
    parser.add_argument("--radius-switch-depth-mm", type=float, default=d.radius_switch_depth_mm)
    parser.add_argument("--overlap-band-mm", type=float, default=d.overlap_band_mm,
                        help="both radii are planned in this band below the switch depth")
    parser.add_argument("--spacing-in-radii", type=float, default=d.spacing_in_radii,
                        help="grid spacing as a multiple of the radius in use")
    parser.add_argument("--fov-fill", type=float, default=d.fov_fill,
                        help="fraction of the half field covered by sphere centers at each depth")
    parser.add_argument("--depth-planes-near", type=int, default=d.depth_planes_near)
    parser.add_argument("--depth-planes-far", type=int, default=d.depth_planes_far)
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
                        help="board corners must project this far inside the image")
    parser.add_argument("--holdout-fraction", type=float, default=d.holdout_fraction)
    parser.add_argument("--seed", type=int, default=d.seed, help="seed of the random held-out subset")
    parser.add_argument("--bootstrap-residual-warn-mm", type=float, default=d.bootstrap_residual_warn_mm)
    parser.add_argument("--out", required=True, type=Path, metavar="DIR", help="output directory")
    return parser


def parameters_from_arguments(args: argparse.Namespace) -> PlanParameters:
    return PlanParameters(
        depth_min_mm=args.depth_min_mm, depth_max_mm=args.depth_max_mm, near_radius_mm=args.near_radius_mm,
        far_radius_mm=args.far_radius_mm, radius_switch_depth_mm=args.radius_switch_depth_mm,
        overlap_band_mm=args.overlap_band_mm, spacing_in_radii=args.spacing_in_radii, fov_fill=args.fov_fill,
        depth_planes_near=args.depth_planes_near, depth_planes_far=args.depth_planes_far,
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
        poses = plan_spheres(params, camera)
        board_poses, board_counts = plan_boards(params, camera)
        poses += board_poses
        ids = [q.pose_id for q in poses]
        if len(set(ids)) != len(ids):
            raise PlanInputError("two planned poses got the same pose id (depth planes or tilts that round to the "
                                 "same whole millimeter or degree); space the depths and angles further apart")
    except PlanInputError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    tag_holdout(poses, params.holdout_fraction, params.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    write_poses_csv(args.out / PLAN_CSV_NAME, poses, sensor_to_base)
    text = summary_text(params, camera, poses, board_counts, source, bootstrap_lines)
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
