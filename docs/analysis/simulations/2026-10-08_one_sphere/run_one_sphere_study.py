"""
One-sphere plan study: does the actual 200-pose plan let the fit recover the error field?

Run from the repository root:

    python3 docs/analysis/simulations/2026-10-08_one_sphere/run_one_sphere_study.py
    python3 docs/analysis/simulations/2026-10-08_one_sphere/run_one_sphere_study.py --cases A --frames 3

What it does
------------
Every earlier simulation used two sphere radii and random poses. The calibration
now uses ONE sphere (radius 76.2 mm) swept through a geometric ladder of nine
stations, plus a tilted flat board. This script simulates exactly that plan with
the production fit and asks how well the fitted map recovers the injected error,
in particular for planar surfaces at 40 to 55 degrees incidence.

Cases (the injected error field differs, the planar part is always the same):
    A  "physical": planar part + K_W * kappa_m * F  (a matching-window bias that is a
       function of the measurement-space curvature kappa_m, as the map assumes)
    B  "physical + millimeter effect": A + E * c * F  (a bias with a fixed footprint in
       millimeters: depends on 1/R but not on range, so NOT a function of kappa_m alone)
    C  "two-radius comparison": A's field, but the OLD plan (two sphere radii, four board
       depths), approximated with the same planner

For each case the script
    1. plans the poses with sphcal.cli.plan_poses, converts them to synthetic poses,
    2. renders 5 frames per pose (synthetic sensor with block averaging and noise),
    3. fits the correction map with the PRODUCTION defaults (fit_correction),
    4. measures gauge-invariant recovery on the held-out poses against the TRUE targets
       (rays intersected with the true sphere or plane, never derived from the injected
       field, because the renderer's block averaging adds a real bias on spheres),
    5. renders and evaluates probe boards (tilts 30 to 55 degrees, not used in the fit)
       and probe spheres (depths between the ladder stations).

Outputs (study folder = the folder of this script): results.json, one log per case,
fig_probe_boards.png, fig_sphere_recovery.png and summary_tables.md. Large generated
data goes under SCRATCH_ROOT and is deleted after each case unless --keep-data is given.

Units: millimeters, degrees at interfaces, pixels for image coordinates.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

# The package is not installed; make the repository root importable when the script is
# started as "python3 docs/.../run_one_sphere_study.py" (Python only puts the script's
# own folder on the path).
STUDY_FOLDER = Path(__file__).resolve().parent
REPOSITORY_ROOT = STUDY_FOLDER.parents[3]
"""docs/analysis/simulations/<study>/ -> four levels up is the repository root."""
sys.path.insert(0, str(REPOSITORY_ROOT))

from sphcal.calibration.correction import CorrectionFitParameters, fit_correction  # noqa: E402
from sphcal.calibration.extrinsic import rigid_component_of_displacements  # noqa: E402
from sphcal.calibration.samples import build_correction_samples, sample_weight_factor  # noqa: E402
from sphcal.cli.plan_poses import (  # noqa: E402
    DEFAULT_SPHERE_RADIUS_MM, PlanParameters, PlannedPose, plan_boards, plan_spheres, sphere_center_room_mm, sphere_fits_in_image,
)
from sphcal.cli.simulate import DEFAULT_SENSOR_TO_POSITIONER  # noqa: E402
from sphcal.geometry.targets import cos_incidence, ray_plane_range, ray_sphere_near_range, \
    sphere_surface_normal  # noqa: E402
from sphcal.geometry.transforms import RigidTransform  # noqa: E402
from sphcal.io.capture_set import CaptureSet  # noqa: E402
from sphcal.io.poses import TARGET_KIND_BOARD, TARGET_KIND_SPHERE, load_manifest  # noqa: E402
from sphcal.simulate.synthetic import (  # noqa: E402
    BOWL_CENTER_U_PX, BOWL_CENTER_V_PX, SyntheticSensorParameters, _error_field, render_board_frame,
    render_sphere_frame, write_synthetic_dataset,
)

# ---------------------------------------------------------------------------
# Where things are written
# ---------------------------------------------------------------------------
SCRATCH_ROOT = Path("/tmp/claude-0/-home-user-depth-calibration-from-spherical-target/"
                    "6fdf0d91-fa81-54f4-b7f8-6ea57d1b7db0/scratchpad/one_sphere_study")
"""Large generated data (rendered .mc files); kept out of the repository."""
RESULTS_FILE_NAME = "results.json"
SUMMARY_TABLES_FILE_NAME = "summary_tables.md"
LOG_FILE_NAME_FORMAT = "log_case_{case}.txt"
PROBE_FIGURE_NAME = "fig_probe_boards.png"
SPHERE_FIGURE_NAME = "fig_sphere_recovery.png"
FIT_DATASET_FOLDER = "fit_dataset"
PROBE_DATASET_FOLDER = "probe_dataset"
MANIFEST_FILE_NAME = "manifest.json"
"""Name of the manifest written by write_synthetic_dataset."""

# ---------------------------------------------------------------------------
# Random seeds and frames
# ---------------------------------------------------------------------------
SYNTHETIC_RNG_SEED = 2026
"""Seed of the synthetic-data random generator of the fit dataset, the same in every case (the brief)."""
PROBE_RNG_SEED = 2027
"""Seed of the probe dataset's generator: a different stream, so the probe noise is independent
of the fit data's noise."""
PREFLIGHT_RNG_SEED = 0
"""Seed of the throw-away generator of the preflight render (only the geometry is checked)."""
FRAMES_PER_POSE = 5
"""Frames per pose, the procedure's value."""

# ---------------------------------------------------------------------------
# The plan (the procedure's example settings)
# ---------------------------------------------------------------------------
PLAN_FOV_FILL = 0.7
"""Fraction of the half field covered by sphere centers (procedure example)."""
PLAN_BOARD_HALF_SIZE_MM = (100.0, 75.0)
"""Board half width and half height, the plan's board (procedure example)."""
PLAN_BOARD_LATERAL_FILL = 0.2
"""Fraction of the half field covered by board centers (procedure example)."""

# Old two-sphere plan, approximated with the same planner (case C).
OLD_SMALL_SPHERE_RADIUS_MM = 38.1
"""Radius of the small sphere of the old plan (a 3 inch diameter sphere)."""
OLD_SMALL_SPHERE_DEPTHS_MM = (300.0, 425.0, 550.0)
"""Explicit stations of the small sphere in the old plan."""
OLD_LARGE_SPHERE_DEPTHS_MM = (500.0, 700.0, 900.0, 1100.0)
"""Explicit stations of the large (76.2 mm) sphere in the old plan."""
OLD_BOARD_DEPTHS_MM = (350.0, 550.0, 800.0, 1050.0)
"""Board depths of the old plan."""
OLD_SPACING_IN_RADII = 1.5
"""Lateral spacing in radii, as in the new plan."""
OLD_MIN_POSITIONS_PER_AXIS = 1
"""1 keeps the radius-based spacing (the near-range spacing shrink is a feature of the new planner only)."""

# ---------------------------------------------------------------------------
# Injected error field
# ---------------------------------------------------------------------------
MATCHING_WINDOW_MEAN_SQUARE_WIDTH_PX2 = 8.0
"""W: mean-square width of the stereo-matching window, px^2. A 7 x 7 matching window has
mean-square width 2 * 49 / 12 = 8.2 px^2, so 8.0 stands for a stereo-matching window larger than
the effective cell (the 4 x 4 cell alone has 2.67 px^2)."""
MATCHING_WINDOW_COEFFICIENT_PX2 = MATCHING_WINDOW_MEAN_SQUARE_WIDTH_PX2 / 2.0
"""K_W = W / 2: the pole bias of an averaging kernel on a curved surface is kappa_m * W / 2
(analysis document, section 4b), so this multiplies kappa_m (mm/px^2) to give mm."""
MILLIMETER_EFFECT_COEFFICIENT_MM2 = 2.0
"""E: coefficient of the effect with a FIXED footprint in millimeters, mm^2. A processing step
with a fixed footprint in millimeters gives a bias proportional to 1/R but independent of the range,
so it is not a function of kappa_m alone and the map's curvature axis cannot represent it exactly."""

# ---------------------------------------------------------------------------
# Accuracy target (decision D-11)
# ---------------------------------------------------------------------------
TARGET_AT_REFERENCE_MM = 0.1
"""D-11: the accuracy target at the reference depth, mm."""
TARGET_REFERENCE_DEPTH_MM = 500.0
"""D-11: the reference depth, mm."""
TARGET_DEPTH_EXPONENT = 2.0
"""D-11: the target scales like the noise law, as depth squared."""

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
INCIDENCE_BIN_EDGES_DEG = (0.0, 20.0, 40.0, 55.0, 90.0)
"""Edges of the incidence bins, degrees. The brief's bins are 0-20, 20-40 and 40-55; the last bin
(55-90) collects samples whose TRUE incidence is above the 55 degree cut-off although the cut-off
was applied to the incidence predicted with the fitted transform; it is reported so that the counts
are honest."""
STATION_MATCH_TOLERANCE_MM = 0.5
"""Two station depths closer than this are the same station."""
MIN_FOOTPRINT_READ_FRACTION = 0.2
"""Preflight: a rendered pose must deliver at least this fraction of the expected footprint (brief)."""
GAUGE_ROTATION_STEP_RAD = 1.0e-5
"""Finite-difference step of the rotation parameters of the range-consistent gauge fit, radians
(1e-5 rad moves a point at 1,000 mm by 0.01 mm, far above rounding and far below nonlinearity)."""
GAUGE_TRANSLATION_STEP_MM = 0.01
"""Finite-difference step of the translation parameters, mm."""
GAUGE_ITERATIONS = 4
"""Gauss-Newton iterations of the range-consistent gauge fit; the problem is nearly linear, so the
second iteration already changes nothing visible."""
GAUGE_LSTSQ_RCOND = 1.0e-6
"""Singular values below this fraction of the largest are dropped in the gauge fit: a single board
cannot determine the in-plane translations and the rotation about its normal."""
SMALL_ANGLE_LIMIT_DEG = 5.0
"""The gauge removal is a small-angle (linear) rigid motion; a fitted rotation above this would
make that linearization doubtful, so a warning is logged."""

# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------
PROBE_BOARD_TILTS_DEG = (30.0, 45.0, 50.0, 55.0)
"""Probe board tilts, degrees; 45 to 55 lie beyond the fitted boards (maximum 40)."""
PROBE_BOARD_AZIMUTHS_DEG = (0.0, 90.0)
"""Probe board tilt-axis azimuths, degrees."""
PROBE_BOARD_DEPTHS_MM = (425.0, 600.0, 850.0, 1050.0)
"""Probe board center depths, mm; none is a fitted board depth except 425 and 1050."""
PROBE_SPHERE_DEPTHS_MM = (330.0, 465.0, 650.0, 950.0)
"""Probe sphere depths, mm: between the ladder stations (300, 357, 424, 505, 600, 714, 849, 1009, 1100)."""
PROBE_SPHERE_ROOM_FRACTION = 0.6
"""Probe sphere lateral offsets are this fraction of the room the planner allows (brief)."""
PROBE_SPHERE_OFFSET_SIGNS = ((0.0, 0.0), (1.0, 1.0), (1.0, -1.0), (-1.0, 1.0), (-1.0, -1.0))
"""Signs of the (x, y) offsets: centered, and the four diagonal corners at plus/minus the room fraction."""

# ---------------------------------------------------------------------------
# Figure style
# ---------------------------------------------------------------------------
FIGURE_DPI = 150
"""Resolution of the PNG figures."""
PROBE_FIGURE_SIZE_IN = (15.0, 9.0)
SPHERE_FIGURE_SIZE_IN = (13.0, 5.5)
"""Figure sizes, inches (width, height)."""
SERIES_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7")
"""Categorical colors in fixed order (blue, orange, aqua, violet) from the dataviz reference palette."""
SERIES_MARKERS = ("o", "s", "^", "D")
"""One marker per series so that identity does not rely on color alone."""
TARGET_COLOR = "#222222"
"""Ink color of the D-11 target curve."""
LINE_WIDTH = 2.0
MARKER_SIZE = 7.0
TARGET_LINE_WIDTH = 1.4
GRID_ALPHA = 0.3
"""Line width of data lines, marker size, line width of target lines, alpha of the grid."""

LOGGER = logging.getLogger("one_sphere_study")


# ---------------------------------------------------------------------------
# Case definitions
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CaseDefinition:
    key: str
    title: str
    plan: str
    """"one_sphere" (the actual plan) or "two_radius" (the old plan)."""
    millimeter_effect: bool
    """Add the fixed-footprint term E * c * F to the injected field."""


CASES = {
    "A": CaseDefinition("A", "physical", "one_sphere", False),
    "B": CaseDefinition("B", "physical + millimeter effect", "one_sphere", True),
    "C": CaseDefinition("C", "two-radius comparison", "two_radius", False),
}


@dataclass
class PoseInfo:
    """What the analysis needs to know about a pose beyond the capture record."""

    kind: str
    radius_mm: float | None
    station_depth_mm: float
    """Sphere station or board depth plane (the planner's plane_depth_mm)."""
    tilt_deg: float | None = None
    azimuth_deg: float | None = None


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def d11_target_mm(depth_mm):
    """D-11 accuracy target at a depth: 0.1 mm * (z / 500 mm)^2."""
    return TARGET_AT_REFERENCE_MM * (np.asarray(depth_mm, dtype=np.float64) / TARGET_REFERENCE_DEPTH_MM) ** TARGET_DEPTH_EXPONENT


def to_jsonable(value):
    """Convert numpy scalars and arrays (and NaN) for json.dump."""
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return to_jsonable(value.tolist())
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def weighted_rms(values: np.ndarray, weights: np.ndarray) -> float:
    return float(np.sqrt(np.average(values ** 2, weights=weights)))


def noise_floor_rms(weights: np.ndarray, weight_factor: float) -> float:
    """RMS of the sample noise implied by the sample weights.

    A sample's weight is weight_factor / variance, with variance the pooled temporal variance of
    the mean range of the pose's frames, so the variance is weight_factor / weight. For a weighted
    mean square, sum(w e^2) / sum(w), whose expectation is N / sum(w) * weight_factor when
    E[e^2] = variance, this is the RMS that pure frame noise would give (block correlation and
    systematic parts are not in it)."""
    return float(np.sqrt(weight_factor * weights.size / weights.sum()))


def incidence_bin_labels() -> list[str]:
    edges = INCIDENCE_BIN_EDGES_DEG
    return [f"{edges[i]:g}-{edges[i + 1]:g}" for i in range(len(edges) - 1)]


# ---------------------------------------------------------------------------
# Poses
# ---------------------------------------------------------------------------
def base_plan_parameters() -> PlanParameters:
    """The procedure's example settings; everything else default."""
    return PlanParameters(fov_fill=PLAN_FOV_FILL, board_half_size_mm=PLAN_BOARD_HALF_SIZE_MM,
                          board_lateral_fill=PLAN_BOARD_LATERAL_FILL)


def plan_for_case(case: CaseDefinition, camera) -> tuple[list[PlannedPose], dict]:
    """Planned poses (sensor frame) of a case and a dictionary of plan counts."""
    base = base_plan_parameters()
    if case.plan == "one_sphere":
        spheres, sphere_counts = plan_spheres(base, camera)
        boards, board_counts = plan_boards(base, camera)
        sphere_counts_by_radius = {base.sphere_radius_mm: sphere_counts}
    else:
        small = replace(base, sphere_radius_mm=OLD_SMALL_SPHERE_RADIUS_MM, sphere_depths_mm=OLD_SMALL_SPHERE_DEPTHS_MM,
                        min_positions_per_axis=OLD_MIN_POSITIONS_PER_AXIS, spacing_in_radii=OLD_SPACING_IN_RADII)
        large = replace(base, sphere_depths_mm=OLD_LARGE_SPHERE_DEPTHS_MM,
                        min_positions_per_axis=OLD_MIN_POSITIONS_PER_AXIS, spacing_in_radii=OLD_SPACING_IN_RADII)
        small_poses, small_counts = plan_spheres(small, camera)
        large_poses, large_counts = plan_spheres(large, camera)
        spheres = small_poses + large_poses
        boards, board_counts = plan_boards(replace(base, board_depths_mm=OLD_BOARD_DEPTHS_MM), camera)
        sphere_counts_by_radius = {small.sphere_radius_mm: small_counts, large.sphere_radius_mm: large_counts}
    planned = spheres + boards
    ids = [pose.pose_id for pose in planned]
    if len(set(ids)) != len(ids):
        raise RuntimeError("two planned poses share an id")
    counts = {
        "n_sphere_poses": len(spheres), "n_board_poses": len(boards), "n_poses": len(planned),
        "sphere_poses_per_station": {f"r{radius:g}": {f"{depth:.0f}": int(c[0] - c[1]) for depth, c in table.items()}
                                     for radius, table in sphere_counts_by_radius.items()},
        "board_poses_per_depth": {f"{depth:.0f}": int(c[0] - c[1]) for depth, c in board_counts.items()},
        "board_combinations_skipped": {f"{depth:.0f}": int(c[1]) for depth, c in board_counts.items()},
    }
    return planned, counts


def synthetic_pose(planned: PlannedPose):
    """The tuple write_synthetic_dataset expects, with DEFAULT_SENSOR_TO_POSITIONER as the true transform.

    Sphere: ("sphere", radius, RigidTransform(identity, center in the positioner frame)).
    Board:  ("board", (half_w, half_h), sensor_to_positioner o pose_sensor), the board frame's z axis
    being the outward normal facing the camera (plan_poses builds it that way: facing = frame whose
    z axis is minus the viewing ray)."""
    if planned.kind == TARGET_KIND_SPHERE:
        center_positioner = DEFAULT_SENSOR_TO_POSITIONER.apply_points(planned.center_sensor)
        return ("sphere", float(planned.radius_mm), RigidTransform(np.eye(3), center_positioner))
    pose_sensor = RigidTransform(planned.tool_to_sensor, planned.center_sensor)
    return ("board", tuple(planned.half_size_mm), DEFAULT_SENSOR_TO_POSITIONER.compose(pose_sensor))


def board_tilt_deg(planned: PlannedPose) -> float:
    """Angle between the board normal and the direction back to the camera at the board center."""
    normal = planned.tool_to_sensor[:, 2]
    toward_camera = -planned.center_sensor / np.linalg.norm(planned.center_sensor)
    return float(np.degrees(np.arccos(np.clip(normal @ toward_camera, -1.0, 1.0))))


def pose_infos(planned: list[PlannedPose]) -> dict[str, PoseInfo]:
    """PoseInfo by synthetic pose id (pose0000, pose0001, ... in planned order)."""
    infos = {}
    for index, pose in enumerate(planned):
        pose_id = f"pose{index:04d}"
        infos[pose_id] = PoseInfo(pose.kind, pose.radius_mm, float(pose.plane_depth_mm),
                                  tilt_deg=board_tilt_deg(pose) if pose.kind == TARGET_KIND_BOARD else None)
    return infos


# ---------------------------------------------------------------------------
# Error field
# ---------------------------------------------------------------------------
def build_error_field(camera, millimeter_effect: bool):
    """Injected error (mm added to range): planar part + K_W kappa_m F [+ E c F].

    planar part: the default bowl (centered on the camera principal point) and slope terms of
    sphcal.simulate.synthetic._error_field, called with zero curvature so that its D * curvature
    term vanishes.
    F = (sec^3 alpha + sec alpha) / 2 with sec alpha = sqrt(1 + s_u^2 + s_v^2).
    kappa_m = (rho / f_mean)^2 * c with c = 1/R the PHYSICAL curvature (0 on boards)."""
    focal = camera.mean_focal_px

    def field(u, v, rho, s_u, s_v, curvature_per_mm):
        planar = _error_field(u, v, rho, s_u, s_v, np.zeros_like(rho), camera.principal_x_px, camera.principal_y_px)
        secant = np.sqrt(1.0 + s_u ** 2 + s_v ** 2)
        incidence_factor = (secant ** 3 + secant) / 2.0
        kappa_m = (rho / focal) ** 2 * curvature_per_mm
        error = planar + MATCHING_WINDOW_COEFFICIENT_PX2 * kappa_m * incidence_factor
        if millimeter_effect:
            error = error + MILLIMETER_EFFECT_COEFFICIENT_MM2 * curvature_per_mm * incidence_factor
        return error

    field.description = (  # type: ignore[attr-defined]
        f"planar bowl+slope part (no curvature term) + K_W kappa_m F with K_W={MATCHING_WINDOW_COEFFICIENT_PX2} px^2"
        + (f" + E c F with E={MILLIMETER_EFFECT_COEFFICIENT_MM2} mm^2" if millimeter_effect else "")
        + "; F=(sec^3+sec)/2, sec=sqrt(1+s_u^2+s_v^2), kappa_m=(rho/f_mean)^2 c; mm added to range")
    return field


# ---------------------------------------------------------------------------
# Preflight: is the board orientation convention right, do poses fill the image?
# ---------------------------------------------------------------------------
def polygon_area(points_uv: np.ndarray) -> float:
    """Shoelace area of a polygon given as (n, 2) vertices."""
    x, y = points_uv[:, 0], points_uv[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def expected_footprint_px(params: SyntheticSensorParameters, planned: PlannedPose) -> float:
    """Expected image area (pixels) of a planned target, from the geometry alone.

    Board: the shoelace area of its four projected corners (a planar quadrilateral stays one under
    perspective). Sphere: the circle of radius f R / sqrt(rho^2 - R^2) (the on-axis silhouette); off
    axis the silhouette is stretched by perspective, so this is approximate for off-axis spheres."""
    camera = params.camera
    if planned.kind == TARGET_KIND_BOARD:
        half_w, half_h = planned.half_size_mm
        corners = np.array([planned.center_sensor + planned.tool_to_sensor @ np.array([sx * half_w, sy * half_h, 0.0])
                            for sx, sy in ((1.0, 1.0), (1.0, -1.0), (-1.0, -1.0), (-1.0, 1.0))])
        u, v, _ = camera.project(corners)
        return polygon_area(np.column_stack([u, v]))
    rho = float(np.linalg.norm(planned.center_sensor))
    radius_px = camera.mean_focal_px * planned.radius_mm / np.sqrt(rho ** 2 - planned.radius_mm ** 2)
    return float(np.pi * radius_px ** 2)


def run_preflight(params: SyntheticSensorParameters, planned: list[PlannedPose], error_field) -> dict:
    """Render ONE frame of every planned pose and compare hit and read pixels with the expected footprint.

    Also renders the first board with its normal flipped (the back face), which must give no hit at
    all: that proves the renderer's front-face convention and the planner's agree (z toward the camera)."""
    rng = np.random.default_rng(PREFLIGHT_RNG_SEED)
    rows = []
    for pose in planned:
        expected = expected_footprint_px(params, pose)
        if pose.kind == TARGET_KIND_BOARD:
            frame = render_board_frame(params, RigidTransform(pose.tool_to_sensor, pose.center_sensor),
                                       pose.half_size_mm, error_field, rng)
        else:
            frame = render_sphere_frame(params, pose.center_sensor, pose.radius_mm, error_field, rng)
        rows.append({"pose_id": pose.pose_id, "kind": pose.kind, "expected_px": expected,
                     "hit_px": int(frame.hit_mask.sum()), "read_px": int(frame.read_mask.sum()),
                     "hit_ratio": frame.hit_mask.sum() / expected, "read_ratio": frame.read_mask.sum() / expected})
    first_board = next(p for p in planned if p.kind == TARGET_KIND_BOARD)
    flip_x = np.diag([1.0, -1.0, -1.0])  # a 180 degree rotation about x: z (the normal) now points away
    flipped = render_board_frame(params, RigidTransform(first_board.tool_to_sensor @ flip_x, first_board.center_sensor),
                                 first_board.half_size_mm, error_field, rng)
    result = {"n_poses_checked": len(rows),
              "flipped_board_hit_px": int(flipped.hit_mask.sum()),
              "min_read_ratio": min(r["read_ratio"] for r in rows),
              "min_read_ratio_board": min(r["read_ratio"] for r in rows if r["kind"] == TARGET_KIND_BOARD),
              "min_read_ratio_sphere": min(r["read_ratio"] for r in rows if r["kind"] == TARGET_KIND_SPHERE),
              "min_hit_ratio_board": min(r["hit_ratio"] for r in rows if r["kind"] == TARGET_KIND_BOARD),
              "median_hit_ratio_board": float(np.median([r["hit_ratio"] for r in rows if r["kind"] == TARGET_KIND_BOARD])),
              "median_hit_ratio_sphere": float(np.median([r["hit_ratio"] for r in rows if r["kind"] == TARGET_KIND_SPHERE])),
              "worst_poses": sorted(rows, key=lambda r: r["read_ratio"])[:3]}
    LOGGER.info("preflight: %s", json.dumps(to_jsonable({k: v for k, v in result.items() if k != "worst_poses"})))
    if result["flipped_board_hit_px"] != 0:
        raise RuntimeError("a board with its normal pointing away from the camera was rendered: convention mismatch")
    if result["min_read_ratio"] <= MIN_FOOTPRINT_READ_FRACTION:
        raise RuntimeError(f"a pose delivers only {result['min_read_ratio']:.2f} of its expected footprint: {result['worst_poses']}")
    return result


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------
def build_probe_poses(camera) -> tuple[list[PlannedPose], dict[str, PoseInfo], dict]:
    """Probe boards (tilt, azimuth, depth) and probe spheres, in the sensor frame.

    Boards are centered on the optical axis (planner convention: center (0, 0, depth)); a
    combination whose tilted corners leave the image is dropped by the planner's own corner test
    (plan_boards with one lateral position). Spheres sit at the probe depths, centered and at plus/minus
    PROBE_SPHERE_ROOM_FRACTION of the room the planner allows (sphere_center_room_mm)."""
    base = base_plan_parameters()
    planned, infos, dropped = [], {}, []
    for depth in PROBE_BOARD_DEPTHS_MM:
        for tilt in PROBE_BOARD_TILTS_DEG:
            for azimuth in PROBE_BOARD_AZIMUTHS_DEG:
                poses, _ = plan_boards(replace(base, board_depths_mm=(depth,), board_tilts_deg=(tilt,),
                                               board_azimuths_deg=(azimuth,), board_lateral_positions=1), camera)
                if not poses:
                    dropped.append({"depth_mm": depth, "tilt_deg": tilt, "azimuth_deg": azimuth})
                    continue
                infos[f"pose{len(planned):04d}"] = PoseInfo(TARGET_KIND_BOARD, None, depth, tilt, azimuth)
                planned.append(poses[0])
    for depth in PROBE_SPHERE_DEPTHS_MM:
        room_x, room_y = sphere_center_room_mm(camera, depth, base.sphere_radius_mm, base.edge_margin_px,
                                               base.room_bisection_tolerance_mm)
        for sign_x, sign_y in PROBE_SPHERE_OFFSET_SIGNS:
            center = np.array([sign_x * PROBE_SPHERE_ROOM_FRACTION * room_x, sign_y * PROBE_SPHERE_ROOM_FRACTION * room_y, depth])
            if not sphere_fits_in_image(camera, center, base.sphere_radius_mm, base.edge_margin_px):
                raise RuntimeError(f"probe sphere at {center} leaves the image")
            infos[f"pose{len(planned):04d}"] = PoseInfo(TARGET_KIND_SPHERE, base.sphere_radius_mm, depth)
            planned.append(PlannedPose(pose_id=f"probe_s_z{depth:.0f}_{sign_x:+.0f}{sign_y:+.0f}", kind=TARGET_KIND_SPHERE,
                                       radius_mm=base.sphere_radius_mm, half_size_mm=None, center_sensor=center,
                                       tool_to_sensor=np.eye(3), plane_depth_mm=depth))
    info = {"n_board_probes": sum(p.kind == TARGET_KIND_BOARD for p in planned),
            "n_sphere_probes": sum(p.kind == TARGET_KIND_SPHERE for p in planned),
            "board_combinations_dropped_by_corner_test": dropped}
    return planned, infos, info

# ---------------------------------------------------------------------------
# Truth: evaluation sets
# ---------------------------------------------------------------------------
@dataclass
class TrueTarget:
    """A target at its TRUE pose in the TRUE sensor frame."""

    kind: str
    point: np.ndarray               # sphere center or board origin, mm
    radius_mm: float | None         # spheres
    normal: np.ndarray | None       # boards: outward unit normal (toward the camera)


ARRAY_FIELDS = ("rays", "measured_point", "measured_range", "delta", "weight", "true_points", "incidence_deg", "kind",
                "pose_id", "fitted_target_range")
"""Names of the per-sample arrays of EvaluationSet (the others are shared by subsets)."""


@dataclass
class EvaluationSet:
    """Samples with their TRUE points (true sensor frame), ready for recovery metrics."""

    rays: np.ndarray                 # (N, 3) unit pixel rays
    measured_point: np.ndarray       # (N, 3) temporal-mean measured points
    measured_range: np.ndarray       # (N,)
    delta: np.ndarray                # (N,) fitted correction at the measured inputs
    weight: np.ndarray               # (N,)
    true_points: np.ndarray          # (N, 3) ray intersected with the true target at its true pose
    incidence_deg: np.ndarray        # (N,) true incidence
    kind: np.ndarray                 # (N,) "sphere" or "board"
    pose_id: np.ndarray              # (N,)
    fitted_target_range: np.ndarray  # (N,) range to the target as the fit believes it (fitted transform)
    targets: dict                    # pose id -> TrueTarget (shared by subsets)

    def subset(self, mask: np.ndarray) -> "EvaluationSet":
        return replace(self, **{name: getattr(self, name)[mask] for name in ARRAY_FIELDS})


def build_evaluation_set(samples, capture_set: CaptureSet, model) -> EvaluationSet:
    """True points by intersecting each sample's pixel ray with the TRUE target at its TRUE pose.

    The true pose is the record's target pose carried into the true sensor frame with
    DEFAULT_SENSOR_TO_POSITIONER. Samples whose ray misses the true target are dropped (counted in the log)."""
    n = samples.n_samples
    true_range = np.full(n, np.nan)
    true_cos = np.full(n, np.nan)
    targets = {}
    for pose_number, pose_id in enumerate(samples.pose_ids):
        rows = np.nonzero(samples.pose_index == pose_number)[0]
        record = capture_set.records_for(pose_id)[0]
        pose_sensor = DEFAULT_SENSOR_TO_POSITIONER.inverse().compose(record.target_pose_positioner)
        rays = samples.ray_direction[rows]
        if record.target_kind == TARGET_KIND_SPHERE:
            targets[pose_id] = TrueTarget(record.target_kind, pose_sensor.translation, float(record.sphere_radius_mm), None)
            hit_range, hit = ray_sphere_near_range(rays, pose_sensor.translation, record.sphere_radius_mm)
            normals = sphere_surface_normal(rays * hit_range[:, None], pose_sensor.translation)
        else:
            normal = pose_sensor.rotation[:, 2]
            targets[pose_id] = TrueTarget(record.target_kind, pose_sensor.translation, None, normal)
            hit_range, hit = ray_plane_range(rays, pose_sensor.translation, normal)
            normals = np.broadcast_to(normal, rays.shape)
        true_range[rows] = hit_range
        true_cos[rows] = np.where(hit, cos_incidence(normals, rays), np.nan)
    keep = np.isfinite(true_range)
    if not keep.all():
        LOGGER.warning("%d of %d samples miss the true target and are dropped", int((~keep).sum()), n)
    kinds = np.array(samples.pose_kinds)[samples.pose_index]
    ids = np.array(samples.pose_ids)[samples.pose_index]
    delta = model.evaluate(samples.inputs)
    return EvaluationSet(
        rays=samples.ray_direction[keep], measured_point=samples.measured_point[keep],
        measured_range=samples.inputs[keep, 2], delta=delta[keep], weight=samples.weight[keep],
        true_points=samples.ray_direction[keep] * true_range[keep][:, None],
        incidence_deg=np.degrees(np.arccos(np.clip(true_cos[keep], -1.0, 1.0))), kind=kinds[keep], pose_id=ids[keep],
        fitted_target_range=(samples.target + samples.inputs[:, 2])[keep], targets=targets)


# ---------------------------------------------------------------------------
# Recovery metrics (both remove the unobservable rigid motion, the gauge)
# ---------------------------------------------------------------------------
class BriefRecoveryMetric:
    """The metric of the brief and of tests/test_end_to_end.py ("recovery").

    Corrected points are carried into the true sensor frame with relative = true^-1 o fitted (uncorrected points
    are used as measured), the best rigid motion between them and the TRUE points (the ray's intersection with
    the true target) is removed in 3-D with rigid_component_of_displacements, and the along-ray component
    of what remains is the error.

    Known limitation, measured by the "perfect_map" mode: the true point of a pixel and the carried corrected
    point of the same pixel lie at different places on the target when the fitted transform differs from the true
    one (the fitted transform absorbs a rigid motion G of a fraction of a millimeter), because the carried point
    has been moved by G along the target while the true point has not. That sliding is not a rigid motion of the
    point set, so removing the best rigid motion does not remove it, and it leaves a floor that grows with the
    incidence angle. The mode "perfect_map" evaluates the metric for a map that is exactly right
    (corrected range = range to the target as the fit believes it) and reports that floor."""

    def __init__(self, relative: RigidTransform) -> None:
        self.relative = relative

    def carried(self, ev: EvaluationSet, corrected: bool) -> np.ndarray:
        if corrected:
            return self.relative.apply_points(ev.rays * (ev.measured_range + ev.delta)[:, None])
        return ev.measured_point

    def estimate(self, ev: EvaluationSet, corrected: bool):
        return rigid_component_of_displacements(ev.true_points, self.carried(ev, corrected) - ev.true_points, ev.weight)

    def errors(self, ev: EvaluationSet, corrected: bool, gauge) -> np.ndarray:
        translation, rotation_vector = gauge
        mismatch = self.carried(ev, corrected) - ev.true_points
        non_rigid = mismatch - (translation + np.cross(rotation_vector, ev.true_points))
        return np.sum(non_rigid * ev.rays, axis=1)

    @staticmethod
    def describe(gauge) -> dict:
        return {"translation_mm": gauge[0], "rotation_deg": np.degrees(gauge[1])}


class RangeConsistentMetric:
    """A sliding-free alternative ("range_consistent"), built like the fit's own residual.

    The believed target is the TRUE target moved by a rigid motion G' (a transform T_true o G' would believe: the
    target in the sensor frame is G'^-1 applied to the true target). For every sample the range along its pixel ray
    to that moved target is compared with the corrected range (measured + map); the error is
    (measured + map) - range_to_moved_target. G' (6 parameters: rotation vector in radians and translation in mm)
    minimizes the weighted sum of squares of this error over the given samples (Gauss-Newton with finite-difference
    derivatives, started at relative = true^-1 o fitted). With G' = relative this is exactly the fit's own residual
    (sign aside); G' is then free to absorb the part of the error that is a rigid motion. The error is an along-ray
    range, the quantity the map corrects, and the truth enters only through the true target pose."""

    def __init__(self, relative: RigidTransform) -> None:
        self.start = np.concatenate([Rotation.from_matrix(relative.rotation).as_rotvec(), relative.translation])

    @staticmethod
    def moved_target_ranges(ev: EvaluationSet, parameters: np.ndarray) -> np.ndarray:
        rotation = Rotation.from_rotvec(parameters[:3]).as_matrix()
        translation = parameters[3:]
        ranges = np.full(ev.weight.size, np.nan)
        pose_ids, inverse = np.unique(ev.pose_id, return_inverse=True)
        for index, pose_id in enumerate(pose_ids):
            rows = inverse == index
            target = ev.targets[pose_id]
            point = rotation.T @ (target.point - translation)
            if target.kind == TARGET_KIND_SPHERE:
                ranges[rows], _ = ray_sphere_near_range(ev.rays[rows], point, target.radius_mm)
            else:
                ranges[rows], _ = ray_plane_range(ev.rays[rows], point, rotation.T @ target.normal)
        return ranges

    def residuals(self, ev: EvaluationSet, corrected: bool, parameters: np.ndarray) -> np.ndarray:
        corrected_range = ev.measured_range + (ev.delta if corrected else 0.0)
        return np.nan_to_num(corrected_range - self.moved_target_ranges(ev, parameters), nan=0.0)

    def estimate(self, ev: EvaluationSet, corrected: bool) -> np.ndarray:
        parameters = self.start.copy()
        steps = np.array([GAUGE_ROTATION_STEP_RAD] * 3 + [GAUGE_TRANSLATION_STEP_MM] * 3)
        root_weight = np.sqrt(ev.weight)
        for _ in range(GAUGE_ITERATIONS):
            base = self.residuals(ev, corrected, parameters)
            jacobian = np.empty((base.size, parameters.size))
            for column, step in enumerate(steps):
                shifted = parameters.copy()
                shifted[column] += step
                jacobian[:, column] = (self.residuals(ev, corrected, shifted) - base) / step
            update, *_ = np.linalg.lstsq(jacobian * root_weight[:, None], -base * root_weight, rcond=GAUGE_LSTSQ_RCOND)
            parameters = parameters + update
        return parameters

    def errors(self, ev: EvaluationSet, corrected: bool, gauge) -> np.ndarray:
        return self.residuals(ev, corrected, gauge)

    @staticmethod
    def describe(gauge) -> dict:
        return {"translation_mm": gauge[3:], "rotation_deg": np.degrees(gauge[:3])}


METRIC_RECOVERY = "recovery"
METRIC_RANGE_CONSISTENT = "range_consistent"
MODE_AFTER, MODE_BEFORE, MODE_PERFECT = "after", "before", "perfect_map"
MODES_BY_METRIC = {METRIC_RECOVERY: (MODE_AFTER, MODE_BEFORE, MODE_PERFECT),
                   METRIC_RANGE_CONSISTENT: (MODE_AFTER, MODE_BEFORE)}
"""Modes evaluated per metric: after correction, before correction (delta = 0), and for the brief's metric
the perfect-map floor. The range-consistent metric is zero for a perfect map by construction."""
VARIANT_HELDOUT, VARIANT_POOLED, VARIANT_PER_PROBE = "heldout", "pooled_probes", "per_probe"


def mode_set(ev: EvaluationSet, mode: str) -> EvaluationSet:
    """The set whose map is exactly right (mode perfect_map), or the set itself."""
    if mode == MODE_PERFECT:
        return replace(ev, delta=ev.fitted_target_range - ev.measured_range)
    return ev


def error_arrays(metrics: dict, held: EvaluationSet, evaluated: EvaluationSet, probe_board_mask: np.ndarray | None,
                 variants: tuple[str, ...]):
    """Per-sample recovery errors of `evaluated` for every metric, mode and gauge variant.

    heldout:       the rigid motion estimated on the held-out samples of the fit (one gauge per fit; primary);
    pooled_probes: one rigid motion estimated on all probe-board samples together;
    per_probe:     a separate rigid motion per pose (lenient: one board's tilt error can be absorbed).
    Returns ({variant: {metric: {mode: errors}}}, {metric: {mode: description of the held-out gauge}})."""
    arrays = {variant: {name: {} for name in metrics} for variant in variants}
    gauges = {name: {} for name in metrics}
    for name, metric in metrics.items():
        for mode in MODES_BY_METRIC[name]:
            corrected = mode != MODE_BEFORE
            held_mode, evaluated_mode = mode_set(held, mode), mode_set(evaluated, mode)
            held_gauge = metric.estimate(held_mode, corrected)
            gauges[name][mode] = metric.describe(held_gauge)
            if VARIANT_HELDOUT in variants:
                arrays[VARIANT_HELDOUT][name][mode] = metric.errors(evaluated_mode, corrected, held_gauge)
            if VARIANT_POOLED in variants:
                pooled_gauge = metric.estimate(evaluated_mode.subset(probe_board_mask), corrected)
                arrays[VARIANT_POOLED][name][mode] = metric.errors(evaluated_mode, corrected, pooled_gauge)
            if VARIANT_PER_PROBE in variants:
                errors = np.full(evaluated.weight.size, np.nan)
                for pose_id in np.unique(evaluated.pose_id):
                    mask = evaluated.pose_id == pose_id
                    sub = evaluated_mode.subset(mask)
                    errors[mask] = metric.errors(sub, corrected, metric.estimate(sub, corrected))
                arrays[VARIANT_PER_PROBE][name][mode] = errors
    return arrays, gauges


def stats_for(mask: np.ndarray, ev: EvaluationSet, arrays: dict, weight_factor: float) -> dict:
    """Weighted RMS of the recovery errors of a group of samples, per metric and mode."""
    n = int(mask.sum())
    entry = {"n_samples": n, "n_poses": int(np.unique(ev.pose_id[mask]).size) if n else 0,
             "noise_floor_mm": noise_floor_rms(ev.weight[mask], weight_factor) if n else None}
    for name, modes in arrays.items():
        entry[name] = {f"rms_{mode}_mm": (weighted_rms(errors[mask], ev.weight[mask]) if n else None)
                       for mode, errors in modes.items()}
    return entry


def incidence_masks(ev: EvaluationSet) -> dict[str, np.ndarray]:
    edges = INCIDENCE_BIN_EDGES_DEG
    return {label: (ev.incidence_deg >= edges[i]) & (ev.incidence_deg < edges[i + 1])
            for i, label in enumerate(incidence_bin_labels())}


def station_key(info: PoseInfo) -> str:
    return f"r{info.radius_mm:g}_z{info.station_depth_mm:.0f}"


# ---------------------------------------------------------------------------
# Held-out recovery
# ---------------------------------------------------------------------------
def heldout_metrics(ev: EvaluationSet, arrays: dict, infos: dict[str, PoseInfo], weight_factor: float) -> dict:
    """Recovery on held-out samples (gauge removed over ALL held-out samples), by kind, station, incidence."""
    is_sphere, is_board = ev.kind == TARGET_KIND_SPHERE, ev.kind == TARGET_KIND_BOARD
    stats = lambda mask: stats_for(mask, ev, arrays, weight_factor)
    stations = np.array([station_key(infos[p]) if infos[p].kind == TARGET_KIND_SPHERE else "" for p in ev.pose_id])
    by_station = {}
    for key in sorted({s for s in stations if s}, key=lambda s: (float(s.split("_")[0][1:]), float(s.split("_z")[1]))):
        entry = stats(stations == key)
        entry["station_depth_mm"] = float(key.split("_z")[1])
        entry["radius_mm"] = float(key.split("_")[0][1:])
        entry["target_mm"] = float(d11_target_mm(entry["station_depth_mm"]))
        by_station[key] = entry
    incidence = incidence_masks(ev)
    return {
        "all": stats(np.ones(ev.weight.size, dtype=bool)),
        "sphere": stats(is_sphere), "board": stats(is_board),
        "sphere_by_station": by_station,
        "sphere_by_incidence_deg": {label: stats(is_sphere & mask) for label, mask in incidence.items()},
        "board_by_incidence_deg": {label: stats(is_board & mask) for label, mask in incidence.items()},
    }


# ---------------------------------------------------------------------------
# Probe recovery
# ---------------------------------------------------------------------------
def probe_metrics(ev: EvaluationSet, arrays_by_variant: dict, infos: dict[str, PoseInfo], weight_factor: float) -> dict:
    is_board, is_sphere = ev.kind == TARGET_KIND_BOARD, ev.kind == TARGET_KIND_SPHERE
    depth = np.array([infos[p].station_depth_mm for p in ev.pose_id])
    tilt = np.array([infos[p].tilt_deg if infos[p].tilt_deg is not None else np.nan for p in ev.pose_id])
    result = {"boards": {}, "spheres": {}}
    for variant, arrays in arrays_by_variant.items():
        stats = lambda mask, a=arrays: stats_for(mask, ev, a, weight_factor)
        board = {"per_probe": [], "by_tilt_and_depth": {}, "by_tilt": {}, "by_depth": {}, "by_incidence_deg": {}}
        for pose_id in sorted({p for p, k in zip(ev.pose_id, ev.kind) if k == TARGET_KIND_BOARD}):
            entry = stats(ev.pose_id == pose_id)
            entry.update(pose_id=pose_id, tilt_deg=infos[pose_id].tilt_deg, azimuth_deg=infos[pose_id].azimuth_deg,
                         depth_mm=infos[pose_id].station_depth_mm, target_mm=float(d11_target_mm(infos[pose_id].station_depth_mm)))
            board["per_probe"].append(entry)
        for t in PROBE_BOARD_TILTS_DEG:
            board["by_tilt"][f"{t:g}"] = stats(is_board & (tilt == t))
            for d in PROBE_BOARD_DEPTHS_MM:
                entry = stats(is_board & (tilt == t) & (depth == d))
                entry["target_mm"] = float(d11_target_mm(d))
                board["by_tilt_and_depth"][f"t{t:g}_z{d:g}"] = entry
        for d in PROBE_BOARD_DEPTHS_MM:
            entry = stats(is_board & (depth == d))
            entry["target_mm"] = float(d11_target_mm(d))
            board["by_depth"][f"{d:g}"] = entry
        for label, mask in incidence_masks(ev).items():
            board["by_incidence_deg"][label] = stats(is_board & mask)
        result["boards"][variant] = board
    # Probe spheres: held-out gauge only (a sphere's own rigid component is not a meaningful option).
    arrays = arrays_by_variant[VARIANT_HELDOUT]
    stats = lambda mask: stats_for(mask, ev, arrays, weight_factor)
    sphere = {"overall": stats(is_sphere), "by_depth": {}, "by_incidence_deg": {}, "by_depth_and_incidence_deg": {}}
    for d in PROBE_SPHERE_DEPTHS_MM:
        entry = stats(is_sphere & (depth == d))
        entry["target_mm"] = float(d11_target_mm(d))
        sphere["by_depth"][f"{d:g}"] = entry
        for label, mask in incidence_masks(ev).items():
            sphere["by_depth_and_incidence_deg"][f"z{d:g}_{label}"] = stats(is_sphere & (depth == d) & mask)
    for label, mask in incidence_masks(ev).items():
        sphere["by_incidence_deg"][label] = stats(is_sphere & mask)
    result["spheres"] = sphere
    return result

# ---------------------------------------------------------------------------
# One case
# ---------------------------------------------------------------------------
def setup_case_logging(case_key: str) -> logging.FileHandler:
    handler = logging.FileHandler(STUDY_FOLDER / LOG_FILE_NAME_FORMAT.format(case=case_key), mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    return handler


def run_case(case: CaseDefinition, params: SyntheticSensorParameters, frames: int, keep_data: bool,
             probe_poses: list[PlannedPose], probe_infos: dict[str, PoseInfo]) -> dict:
    handler = setup_case_logging(case.key)
    try:
        return _run_case(case, params, frames, keep_data, probe_poses, probe_infos)
    finally:
        LOGGER.removeHandler(handler)
        handler.close()


def _run_case(case, params, frames, keep_data, probe_poses, probe_infos) -> dict:
    camera = params.camera
    case_root = SCRATCH_ROOT / f"case_{case.key}"
    shutil.rmtree(case_root, ignore_errors=True)
    timings = {}
    LOGGER.info("=== case %s: %s (plan %s, millimeter effect %s) ===", case.key, case.title, case.plan, case.millimeter_effect)
    planned, counts = plan_for_case(case, camera)
    LOGGER.info("planned %d poses (%d sphere, %d board); per station %s; boards %s", counts["n_poses"], counts["n_sphere_poses"],
                counts["n_board_poses"], counts["sphere_poses_per_station"], counts["board_poses_per_depth"])
    infos = pose_infos(planned)
    error_field = build_error_field(camera, case.millimeter_effect)

    # 1. Render the fit dataset.
    started = time.perf_counter()
    write_synthetic_dataset(case_root / FIT_DATASET_FOLDER, params, [synthetic_pose(p) for p in planned],
                            DEFAULT_SENSOR_TO_POSITIONER, frames, error_field, np.random.default_rng(SYNTHETIC_RNG_SEED))
    timings["render_fit_dataset_s"] = time.perf_counter() - started
    LOGGER.info("rendered %d poses x %d frames in %.1f s", len(planned), frames, timings["render_fit_dataset_s"])

    # 2. Fit with the production defaults (same holdout fraction and seed in every case).
    capture_set = CaptureSet(load_manifest(case_root / FIT_DATASET_FOLDER / MANIFEST_FILE_NAME))
    fit_parameters = CorrectionFitParameters()
    started = time.perf_counter()
    result = fit_correction(capture_set, fit_parameters)
    timings["fit_s"] = time.perf_counter() - started
    LOGGER.info("fit done in %.1f s; %d training poses, %d held-out poses; held-out RMS before %.4f after %.4f mm",
                timings["fit_s"], len(result.training_poses), len(result.holdout_poses),
                result.holdout_residual_before_rms_mm, result.holdout_residual_after_rms_mm)
    for r in result.rounds:
        LOGGER.info("  alternation round %d: transform change %.4f mm %.4f deg, training RMS %.4f mm",
                    r.round_index, r.translation_change_mm, r.rotation_change_deg, r.training_residual_rms_mm)
    transform_error = result.sensor_to_positioner.difference_from(DEFAULT_SENSOR_TO_POSITIONER)
    LOGGER.info("fitted transform differs from the true one by %.3f mm, %.4f deg (includes the gauge)", *transform_error)
    holdout_kinds = [infos[p].kind for p in result.holdout_poses]
    fit_summary = {
        "n_training_poses": len(result.training_poses), "n_holdout_poses": len(result.holdout_poses),
        "n_holdout_sphere_poses": holdout_kinds.count(TARGET_KIND_SPHERE),
        "n_holdout_board_poses": holdout_kinds.count(TARGET_KIND_BOARD),
        "n_training_samples": result.training_samples.n_samples,
        "n_holdout_samples": result.holdout_samples.n_samples,
        "holdout_residual_rms_before_mm": result.holdout_residual_before_rms_mm,
        "holdout_residual_rms_after_mm": result.holdout_residual_after_rms_mm,
        "alternation_rounds": len(result.rounds),
        "final_round_transform_change": {"translation_mm": result.rounds[-1].translation_change_mm,
                                         "rotation_deg": result.rounds[-1].rotation_change_deg},
        "training_weighted_residual_rms_mm": result.rounds[-1].training_residual_rms_mm,
        "effective_degrees_of_freedom": result.model.metadata.get("effective_degrees_of_freedom"),
        "retarget_misses_last_round": result.model.metadata.get("retarget_misses_last_round"),
        "smoothing_multipliers": result.model.metadata.get("smoothing_multipliers"),
        "fitted_transform_vs_true": {"translation_mm": transform_error[0], "rotation_deg": transform_error[1]},
    }
    if transform_error[1] > SMALL_ANGLE_LIMIT_DEG:
        LOGGER.warning("fitted rotation differs by %.2f deg: the small-angle gauge removal is doubtful", transform_error[1])

    # 3. Held-out recovery against the true targets.
    started = time.perf_counter()
    weight_factor = sample_weight_factor(fit_parameters.samples)
    relative = DEFAULT_SENSOR_TO_POSITIONER.inverse().compose(result.sensor_to_positioner)
    held = build_evaluation_set(result.holdout_samples, capture_set, result.model)
    metrics = {METRIC_RECOVERY: BriefRecoveryMetric(relative), METRIC_RANGE_CONSISTENT: RangeConsistentMetric(relative)}
    held_arrays, held_gauges = error_arrays(metrics, held, held, None, (VARIANT_HELDOUT,))
    heldout = heldout_metrics(held, held_arrays[VARIANT_HELDOUT], infos, weight_factor)
    heldout["gauges_removed"] = held_gauges
    timings["heldout_metrics_s"] = time.perf_counter() - started
    for name in ("all", "sphere", "board"):
        entry = heldout[name]
        LOGGER.info("held-out %-6s n=%7d  recovery after %.4f before %.4f perfect-map floor %.4f | range-consistent after %.4f "
                    "before %.4f | noise floor %.4f mm", name, entry["n_samples"], entry[METRIC_RECOVERY]["rms_after_mm"],
                    entry[METRIC_RECOVERY]["rms_before_mm"], entry[METRIC_RECOVERY]["rms_perfect_map_mm"],
                    entry[METRIC_RANGE_CONSISTENT]["rms_after_mm"], entry[METRIC_RANGE_CONSISTENT]["rms_before_mm"],
                    entry["noise_floor_mm"])

    # 4. Probes: a separate dataset, never seen by the fit.
    started = time.perf_counter()
    write_synthetic_dataset(case_root / PROBE_DATASET_FOLDER, params, [synthetic_pose(p) for p in probe_poses],
                            DEFAULT_SENSOR_TO_POSITIONER, frames, error_field, np.random.default_rng(PROBE_RNG_SEED))
    probe_set = CaptureSet(load_manifest(case_root / PROBE_DATASET_FOLDER / MANIFEST_FILE_NAME))
    probe_samples = build_correction_samples(probe_set, result.sensor_to_positioner, fit_parameters.samples)
    probe_ev = build_evaluation_set(probe_samples, probe_set, result.model)
    probe_arrays, _ = error_arrays(metrics, held, probe_ev, probe_ev.kind == TARGET_KIND_BOARD,
                                   (VARIANT_HELDOUT, VARIANT_POOLED, VARIANT_PER_PROBE))
    probes = probe_metrics(probe_ev, probe_arrays, probe_infos, weight_factor)
    timings["probes_s"] = time.perf_counter() - started
    for entry in probes["boards"][VARIANT_HELDOUT]["by_tilt_and_depth"].values():
        LOGGER.info("probe boards %s", json.dumps(to_jsonable(entry)))
    timings["total_s"] = sum(timings.values())
    LOGGER.info("timings: %s", json.dumps(timings))
    if not keep_data:
        shutil.rmtree(case_root, ignore_errors=True)
    return {"title": case.title, "plan": case.plan, "millimeter_effect": case.millimeter_effect,
            "error_field": error_field.description, "frames_per_pose": frames, "plan_counts": counts,
            "fit": fit_summary, "heldout_recovery": heldout, "probes": probes, "wall_times_s": timings}

# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
METRIC_TITLES = {METRIC_RECOVERY: "metric of the brief (3-D rigid removal, along-ray)",
                 METRIC_RANGE_CONSISTENT: "range-consistent metric (gauge-adjusted target, along-ray)"}
"""Row titles of the figures and table headings, per metric."""


def make_probe_figure(results: dict, path: Path) -> None:
    """Recovery RMS of the probe boards after correction vs tilt, one line per depth; one column per case,
    one row per metric."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    keys = [k for k in CASES if k in results]
    figure, axes = plt.subplots(len(METRIC_TITLES), len(keys), figsize=PROBE_FIGURE_SIZE_IN, sharey="row", squeeze=False)
    for row, metric in enumerate(METRIC_TITLES):
        for axis, key in zip(axes[row], keys):
            cells = results[key]["probes"]["boards"][VARIANT_HELDOUT]["by_tilt_and_depth"]
            for index, depth in enumerate(PROBE_BOARD_DEPTHS_MM):
                tilts = [t for t in PROBE_BOARD_TILTS_DEG if cells[f"t{t:g}_z{depth:g}"][metric]["rms_after_mm"] is not None]
                values = [cells[f"t{t:g}_z{depth:g}"][metric]["rms_after_mm"] for t in tilts]
                color, marker = SERIES_COLORS[index], SERIES_MARKERS[index]
                axis.plot(tilts, values, color=color, marker=marker, linewidth=LINE_WIDTH, markersize=MARKER_SIZE,
                          label=f"{depth:g} mm (target {float(d11_target_mm(depth)):.3f} mm)")
                axis.axhline(float(d11_target_mm(depth)), color=color, linestyle=":", linewidth=TARGET_LINE_WIDTH)
            axis.set_yscale("log")
            axis.set_xticks(PROBE_BOARD_TILTS_DEG)
            axis.grid(True, alpha=GRID_ALPHA)
            if row == 0:
                axis.set_title(f"Case {key}: {results[key]['title']}")
            if row == len(METRIC_TITLES) - 1:
                axis.set_xlabel("probe board tilt (degrees)")
        axes[row][0].set_ylabel(f"recovery RMS after correction (mm)\n{METRIC_TITLES[metric]}", fontsize="small")
    axes[0][0].legend(title="board depth (D-11 target, dotted)", fontsize="small", loc="upper left")
    figure.suptitle("Probe boards not used in the fit: along-ray recovery error after correction vs tilt")
    figure.tight_layout()
    figure.savefig(path, dpi=FIGURE_DPI)
    plt.close(figure)


def make_sphere_figure(results: dict, path: Path) -> None:
    """Held-out sphere recovery RMS vs station depth for each case, with the D-11 target curve; one panel per metric."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, len(METRIC_TITLES), figsize=SPHERE_FIGURE_SIZE_IN, sharey=True, squeeze=False)
    for axis, metric in zip(axes[0], METRIC_TITLES):
        all_depths = []
        for case_index, key in enumerate(k for k in CASES if k in results):
            stations = list(results[key]["heldout_recovery"]["sphere_by_station"].values())
            radii = sorted({s["radius_mm"] for s in stations})
            for radius in radii:
                chosen = sorted((s for s in stations if s["radius_mm"] == radius), key=lambda s: s["station_depth_mm"])
                all_depths += [s["station_depth_mm"] for s in chosen]
                label = f"Case {key}" + (f", r = {radius:g} mm" if len(radii) > 1 else "")
                axis.plot([s["station_depth_mm"] for s in chosen], [s[metric]["rms_after_mm"] for s in chosen],
                          "-" if radius == DEFAULT_SPHERE_RADIUS_MM else "--", color=SERIES_COLORS[case_index],
                          marker=SERIES_MARKERS[case_index], linewidth=LINE_WIDTH, markersize=MARKER_SIZE, label=label)
        depth_curve = np.linspace(min(all_depths), max(all_depths), 100)
        axis.plot(depth_curve, d11_target_mm(depth_curve), color=TARGET_COLOR, linestyle=":",
                  linewidth=TARGET_LINE_WIDTH + 0.6, label="D-11 target 0.1 mm (z / 500 mm)^2")
        axis.set_yscale("log")
        axis.set_xlabel("sphere station depth (mm)")
        axis.set_title(METRIC_TITLES[metric], fontsize="small")
        axis.grid(True, alpha=GRID_ALPHA)
    axes[0][0].set_ylabel("recovery RMS after correction (mm, along the ray)")
    axes[0][0].legend(fontsize="small")
    figure.suptitle("Held-out sphere samples: along-ray recovery error per station")
    figure.tight_layout()
    figure.savefig(path, dpi=FIGURE_DPI)
    plt.close(figure)


# ---------------------------------------------------------------------------
# Tables for summary.md
# ---------------------------------------------------------------------------
def fmt(value, digits=4) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def metric_cell(entry: dict, metric: str, with_count: bool = True) -> str:
    """'after (before)' and, for the brief's metric, the perfect-map floor; n/a when the group is empty."""
    if entry is None or entry["n_samples"] == 0:
        return "n/a"
    values = entry[metric]
    text = f"{fmt(values['rms_after_mm'])} ({fmt(values['rms_before_mm'])})"
    if metric == METRIC_RECOVERY:
        text += f" floor {fmt(values['rms_perfect_map_mm'])}"
    return text + (f" n={entry['n_samples']}" if with_count else "")


def summary_tables(results: dict) -> str:
    keys = [k for k in CASES if k in results]
    lines = []
    add = lines.append
    add("### Plan and fit")
    add("")
    add("| Case | poses (sphere + board) | held-out poses (sphere + board) | held-out samples | held-out residual RMS before / after (mm) | rounds | fitted vs true transform |")
    add("|---|---|---|---|---|---|---|")
    for k in keys:
        r, c = results[k]["fit"], results[k]["plan_counts"]
        add(f"| {k} | {c['n_poses']} ({c['n_sphere_poses']} + {c['n_board_poses']}) | {r['n_holdout_poses']} "
            f"({r['n_holdout_sphere_poses']} + {r['n_holdout_board_poses']}) | {r['n_holdout_samples']} | "
            f"{fmt(r['holdout_residual_rms_before_mm'])} / {fmt(r['holdout_residual_rms_after_mm'])} | {r['alternation_rounds']} | "
            f"{fmt(r['fitted_transform_vs_true']['translation_mm'], 3)} mm, {fmt(r['fitted_transform_vs_true']['rotation_deg'])} deg |")
    for metric, title in METRIC_TITLES.items():
        add("")
        add(f"### Held-out recovery RMS (mm), after (before){' and perfect-map floor' if metric == METRIC_RECOVERY else ''}: {title}")
        add("")
        add("| Group | " + " | ".join(f"Case {k}" for k in keys) + " |")
        add("|---|" + "---|" * len(keys))
        for name in ("all", "sphere", "board"):
            add(f"| {name} | " + " | ".join(metric_cell(results[k]["heldout_recovery"][name], metric) for k in keys) + " |")
        for label in incidence_bin_labels():
            add(f"| sphere incidence {label} deg | " + " | ".join(
                metric_cell(results[k]["heldout_recovery"]["sphere_by_incidence_deg"][label], metric) for k in keys) + " |")
        for label in incidence_bin_labels():
            add(f"| board incidence {label} deg | " + " | ".join(
                metric_cell(results[k]["heldout_recovery"]["board_by_incidence_deg"][label], metric) for k in keys) + " |")
    add("")
    add("### Noise floor of the held-out groups (mm; RMS of the frame noise implied by the weights)")
    add("")
    add("| Group | " + " | ".join(f"Case {k}" for k in keys) + " |")
    add("|---|" + "---|" * len(keys))
    for name in ("all", "sphere", "board"):
        add(f"| {name} | " + " | ".join(fmt(results[k]["heldout_recovery"][name]["noise_floor_mm"]) for k in keys) + " |")
    add("")
    add("### Held-out sphere recovery per station (mm)")
    add("")
    add("| Case | radius (mm) | station (mm) | held-out poses | samples | recovery after (before), floor | range-consistent after (before) | noise floor | D-11 target |")
    add("|---|---|---|---|---|---|---|---|---|")
    for k in keys:
        for s in results[k]["heldout_recovery"]["sphere_by_station"].values():
            add(f"| {k} | {s['radius_mm']:g} | {s['station_depth_mm']:.0f} | {s['n_poses']} | {s['n_samples']} | "
                f"{metric_cell(s, METRIC_RECOVERY, False)} | {metric_cell(s, METRIC_RANGE_CONSISTENT, False)} | "
                f"{fmt(s['noise_floor_mm'])} | {fmt(s['target_mm'])} |")
    for variant, description in ((VARIANT_HELDOUT, "gauge estimated on the held-out samples (primary)"),
                                 (VARIANT_POOLED, "one gauge fitted on all probe boards together"),
                                 (VARIANT_PER_PROBE, "a separate gauge per probe board (lenient)")):
        for metric, title in METRIC_TITLES.items():
            add("")
            add(f"### Probe boards, recovery RMS (mm), after (before){' and floor' if metric == METRIC_RECOVERY else ''}; "
                f"{description}; {title}")
            add("")
            add("| tilt (deg) | depth (mm) | D-11 target | " + " | ".join(f"Case {k}" for k in keys) + " |")
            add("|---|---|---|" + "---|" * len(keys))
            for t in PROBE_BOARD_TILTS_DEG:
                for d in PROBE_BOARD_DEPTHS_MM:
                    row = [results[k]["probes"]["boards"][variant]["by_tilt_and_depth"][f"t{t:g}_z{d:g}"] for k in keys]
                    add(f"| {t:g} | {d:g} | {fmt(float(d11_target_mm(d)))} | " + " | ".join(metric_cell(e, metric) for e in row) + " |")
            add("")
            add("| pooled over | " + " | ".join(f"Case {k}" for k in keys) + " |")
            add("|---|" + "---|" * len(keys))
            for t in PROBE_BOARD_TILTS_DEG:
                add(f"| tilt {t:g} deg | " + " | ".join(
                    metric_cell(results[k]["probes"]["boards"][variant]["by_tilt"][f"{t:g}"], metric) for k in keys) + " |")
            for d in PROBE_BOARD_DEPTHS_MM:
                add(f"| depth {d:g} mm (target {fmt(float(d11_target_mm(d)))}) | " + " | ".join(
                    metric_cell(results[k]["probes"]["boards"][variant]["by_depth"][f"{d:g}"], metric) for k in keys) + " |")
            for label in incidence_bin_labels():
                add(f"| true incidence {label} deg | " + " | ".join(
                    metric_cell(results[k]["probes"]["boards"][variant]["by_incidence_deg"][label], metric) for k in keys) + " |")
    for metric, title in METRIC_TITLES.items():
        add("")
        add(f"### Probe spheres (held-out gauge), recovery RMS (mm), after (before){' and floor' if metric == METRIC_RECOVERY else ''}; {title}")
        add("")
        add("| group | D-11 target | " + " | ".join(f"Case {k}" for k in keys) + " |")
        add("|---|---|" + "---|" * len(keys))
        add("| overall | | " + " | ".join(metric_cell(results[k]["probes"]["spheres"]["overall"], metric) for k in keys) + " |")
        for d in PROBE_SPHERE_DEPTHS_MM:
            add(f"| depth {d:g} mm | {fmt(float(d11_target_mm(d)))} | " + " | ".join(
                metric_cell(results[k]["probes"]["spheres"]["by_depth"][f"{d:g}"], metric) for k in keys) + " |")
        for label in incidence_bin_labels():
            add(f"| incidence {label} deg | | " + " | ".join(
                metric_cell(results[k]["probes"]["spheres"]["by_incidence_deg"][label], metric) for k in keys) + " |")
    add("")
    add("### Wall times (seconds)")
    add("")
    add("| Case | render fit data | fit | held-out metrics | probes (render + metrics) | total |")
    add("|---|---|---|---|---|---|")
    for k in keys:
        t = results[k]["wall_times_s"]
        add(f"| {k} | {t['render_fit_dataset_s']:.0f} | {t['fit_s']:.0f} | {t['heldout_metrics_s']:.0f} | {t['probes_s']:.0f} | {t['total_s']:.0f} |")
    return "\n".join(lines) + "\n"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-sphere plan simulation study (see the module docstring).")
    parser.add_argument("--cases", nargs="+", choices=sorted(CASES), default=sorted(CASES), help="cases to run (default all)")
    parser.add_argument("--frames", type=int, default=FRAMES_PER_POSE, help="frames per pose (default 5)")
    parser.add_argument("--keep-data", action="store_true", help="keep the rendered datasets under the scratch folder")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    results_path = STUDY_FOLDER / RESULTS_FILE_NAME
    results = json.loads(results_path.read_text()) if results_path.exists() else {}

    params = SyntheticSensorParameters.vsx3000_indicative()
    probe_poses, probe_infos, probe_summary = build_probe_poses(params.camera)
    LOGGER.info("probe set: %s", json.dumps(to_jsonable(probe_summary)))
    preflight = run_preflight(params, plan_for_case(CASES["A"], params.camera)[0], build_error_field(params.camera, False))
    results["_study"] = {"frames_per_pose": args.frames, "synthetic_rng_seed": SYNTHETIC_RNG_SEED, "probe_rng_seed": PROBE_RNG_SEED,
                         "preflight": {k: v for k, v in preflight.items()}, "probe_set": probe_summary,
                         "camera": params.camera.map_block()}
    for key in args.cases:
        results[key] = run_case(CASES[key], params, args.frames, args.keep_data, probe_poses, probe_infos)
        results_path.write_text(json.dumps(to_jsonable(results), indent=1))
        LOGGER.info("case %s written to %s", key, results_path)
    results = json.loads(results_path.read_text())
    if any(k in results for k in CASES):
        (STUDY_FOLDER / SUMMARY_TABLES_FILE_NAME).write_text(summary_tables(results))
        make_probe_figure(results, STUDY_FOLDER / PROBE_FIGURE_NAME)
        make_sphere_figure(results, STUDY_FOLDER / SPHERE_FIGURE_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
