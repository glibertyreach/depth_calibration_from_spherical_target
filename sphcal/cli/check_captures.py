"""
Command line: a quick-look check of a capture set before the long fit.

    python3 -m sphcal.cli.check_captures --manifest manifest.csv --out check.json

What it checks, per pose (stack of frames of one commanded pose)
    frames          number of capture files of the pose.
    valid fraction  temporal read rate: over the pixels that are valid in at least
                    one frame, the mean fraction of frames in which they are
                    valid. A target that flickers in and out scores low.
    valid pixels    pixels valid in at least ``min_valid_fraction`` of the frames;
                    these form the temporal-mean point image used for the fits.
    border          whether those pixels come within ``border_margin_px`` of the
                    image border, which means the sphere or board is partly out
                    of view.
    sphere          the center fitted to the temporal-mean points with the known
                    radius (sensor frame) and the RMS of |p - c| - R.
    board           a plane fitted to the temporal-mean points (the singular
                    vector of the smallest singular value of the centered
                    points) and the RMS distance of the points to it.
    outliers        flying pixels (residual beyond ``outlier_sigma_multiple`` robust
                    scales) are left out of those two RMS values and counted.

After all poses, if at least three sphere centers were fitted, a rough
sensor-to-base transform is solved from the fitted centers and the commanded
centers (poses whose residual exceeds the sphere residual threshold are left
out of the solve but still reported). Then for each sphere pose the distance
between the transformed fitted center and the commanded center is reported, and
for each board the angle between the fitted plane normal (oriented toward the
sensor) and the commanded board normal (the z axis of the commanded board pose)
carried into the sensor frame.

Output: a table on the console and, with --out, a JSON report.

Exit code: 0 when no pose is flagged, 1 when at least one is, 2 when the
manifest cannot be read.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from sphcal.calibration.extrinsic import SphereFitParameters, TransformSolveParameters, fit_sphere_center, \
    solve_sensor_to_positioner
from sphcal.features.depth_features import temporal_mean_points
from sphcal.geometry.transforms import RigidTransform
from sphcal.io.capture_set import CaptureSet
from sphcal.io.poses import TARGET_KIND_SPHERE, load_manifest

EXIT_OK = 0
EXIT_FLAGGED = 1
EXIT_INPUT_ERROR = 2
"""Exit codes: nothing flagged, something flagged, manifest unreadable."""

MIN_SPHERE_POSES_FOR_TRANSFORM = 3
"""A rigid transform needs at least three non-collinear sphere centers."""
MIN_PLANE_POINTS = 3
"""A plane needs at least three points."""
MEDIAN_ABSOLUTE_TO_SIGMA = 1.4826
"""Factor converting a median absolute residual into a Gaussian sigma."""
MIN_ROBUST_SCALE_MM = 1.0e-6
"""Numerical guard: smallest robust residual scale, so a perfect fit does not reject everything."""
MATRIX_PRINT_DECIMALS = 3
"""Decimals printed for the rough transform."""
REPORT_JSON_INDENT = 2
"""Indentation of the JSON report."""
ADVICE = "re-capture the flagged poses or check the tool center point / tool frame"
"""Advice printed when anything is flagged."""

FLAG_UNREADABLE = "capture files could not be read"
FLAG_LOW_VALID = "low valid fraction (target flickers or is not read)"
FLAG_BORDER = "touches the image border (target partly out of view)"
FLAG_TOO_FEW_POINTS = "too few valid points for a fit"
FLAG_SPHERE_RMS = "sphere surface fit residual too large"
FLAG_PLANE_RMS = "board plane fit residual too large"
FLAG_CENTER = "fitted center disagrees with the commanded center"
FLAG_NORMAL = "fitted board normal disagrees with the commanded normal"
FLAG_TRANSFORM = "transform solve failed"


@dataclass(frozen=True)
class CheckParameters:
    """Thresholds of the check; the command-line defaults come from here."""

    sphere_residual_warn_mm: float = 2.0
    """Flag a sphere whose surface fit RMS or whose center residual exceeds this."""
    plane_residual_warn_mm: float = 2.0
    """Flag a board whose RMS distance to its fitted plane exceeds this."""
    min_valid_fraction: float = 0.5
    """Flag a pose whose temporal valid fraction is below this; pixels valid in fewer
    frames than this fraction are left out of the temporal-mean image."""
    border_margin_px: int = 4
    """Valid pixels this close to the image border mean the target is cut off."""
    outlier_sigma_multiple: float = 5.0
    """Residual RMS values leave out flying pixels: points whose residual exceeds this
    multiple of the robust scale (median absolute residual times the Gaussian factor).
    Their number is reported as ``outliers``."""
    outlier_rounds: int = 3
    """Rounds of plane fit and outlier removal for a board."""
    board_normal_warn_deg: float = 2.0
    """Flag a board whose fitted and commanded normals differ by more than this."""


@dataclass
class PoseCheck:
    """Measurements and flags of one pose."""

    pose_id: str
    kind: str
    frames: int = 0
    valid_fraction: float = float("nan")
    valid_pixels: int = 0
    outliers: int = 0                             # flying pixels left out of the residual RMS
    touches_border: bool = False
    fit_rms_mm: float = float("nan")              # sphere surface residual or board plane residual
    center_sensor_mm: np.ndarray | None = None    # sphere only
    plane_normal_sensor: np.ndarray | None = None  # board only, facing the sensor
    center_residual_mm: float = float("nan")      # sphere only, after the transform solve
    normal_error_deg: float = float("nan")        # board only, after the transform solve
    flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-pose measurements
# ---------------------------------------------------------------------------
def border_touched(valid: np.ndarray, margin_px: int) -> bool:
    """True when any True pixel of the (H, W) mask lies within margin_px of the border."""
    if margin_px <= 0:
        return False
    inner = valid[margin_px:valid.shape[0] - margin_px, margin_px:valid.shape[1] - margin_px]
    return bool(valid.sum() > inner.sum())


def temporal_valid_fraction(valid_stack: np.ndarray) -> float:
    """Mean, over pixels valid in at least one frame, of the fraction of frames in which they are valid."""
    per_pixel = valid_stack.mean(axis=0)
    seen = per_pixel > 0.0
    return float(per_pixel[seen].mean()) if seen.any() else 0.0


def inlier_mask(residuals: np.ndarray, sigma_multiple: float) -> np.ndarray:
    """Points whose |residual| is within sigma_multiple robust scales of zero. The
    scale is the median absolute residual times the Gaussian factor; it is taken
    about zero, so a constant offset (a wrong radius) is not hidden by it."""
    scale = max(MEDIAN_ABSOLUTE_TO_SIGMA * float(np.median(np.abs(residuals))), MIN_ROBUST_SCALE_MM)
    return np.abs(residuals) <= sigma_multiple * scale


def sphere_surface_rms(points: np.ndarray, center: np.ndarray, radius_mm: float,
                       sigma_multiple: float) -> tuple[float, int]:
    """RMS of |p - c| - R over the inlier points (mm) and the number of outliers left out."""
    residuals = np.linalg.norm(points - center, axis=1) - radius_mm
    keep = inlier_mask(residuals, sigma_multiple)
    return float(np.sqrt(np.mean(residuals[keep] ** 2))), int((~keep).sum())


def fit_plane(points: np.ndarray, sigma_multiple: float, rounds: int) -> tuple[np.ndarray, np.ndarray, float, int]:
    """Plane through points by the smallest-singular-vector method, refitted on the
    inliers for ``rounds`` rounds. Returns (centroid, unit normal, RMS distance of
    the inliers to the plane in mm, number of outliers left out)."""
    keep = np.ones(points.shape[0], dtype=bool)
    for _ in range(max(rounds, 1)):
        centroid = points[keep].mean(axis=0)
        _, _, vt = np.linalg.svd(points[keep] - centroid, full_matrices=False)
        normal = vt[-1]
        distance = (points - centroid) @ normal
        new_keep = inlier_mask(distance, sigma_multiple)
        if new_keep.sum() < MIN_PLANE_POINTS or np.array_equal(new_keep, keep):
            break
        keep = new_keep
    return centroid, normal, float(np.sqrt(np.mean(distance[keep] ** 2))), int((~keep).sum())


def check_pose(capture_set: CaptureSet, pose_id: str, params: CheckParameters) -> PoseCheck:
    """Load one pose's frames and measure it (the first record gives the target kind and radius)."""
    record = capture_set.records_for(pose_id)[0]
    check = PoseCheck(pose_id=pose_id, kind=record.target_kind, frames=len(capture_set.records_for(pose_id)))
    try:
        stack = capture_set.load_stack(pose_id)
    except (OSError, ValueError, KeyError) as error:
        check.flags.append(f"{FLAG_UNREADABLE}: {error}")
        return check
    mean_xyz = temporal_mean_points(stack.xyz, stack.valid, params.min_valid_fraction)
    mean_valid = np.isfinite(mean_xyz[..., 2])
    points = mean_xyz[mean_valid].astype(np.float64)
    check.frames = stack.xyz.shape[0]
    check.valid_fraction = temporal_valid_fraction(stack.valid)
    check.valid_pixels = int(mean_valid.sum())
    check.touches_border = border_touched(mean_valid, params.border_margin_px)
    if check.valid_fraction < params.min_valid_fraction:
        check.flags.append(FLAG_LOW_VALID)
    if check.touches_border:
        check.flags.append(FLAG_BORDER)
    if record.target_kind == TARGET_KIND_SPHERE:
        center = fit_sphere_center(points, record.sphere_radius_mm, SphereFitParameters())
        if not np.isfinite(center).all():
            check.flags.append(FLAG_TOO_FEW_POINTS)
            return check
        check.center_sensor_mm = center
        check.fit_rms_mm, check.outliers = sphere_surface_rms(points, center, record.sphere_radius_mm,
                                                              params.outlier_sigma_multiple)
        if check.fit_rms_mm > params.sphere_residual_warn_mm:
            check.flags.append(FLAG_SPHERE_RMS)
    else:
        if points.shape[0] < MIN_PLANE_POINTS:
            check.flags.append(FLAG_TOO_FEW_POINTS)
            return check
        centroid, normal, check.fit_rms_mm, check.outliers = fit_plane(
            points, params.outlier_sigma_multiple, params.outlier_rounds)
        # Orient the normal toward the sensor (the sensor is at the origin, so toward -centroid).
        check.plane_normal_sensor = normal if normal @ centroid < 0.0 else -normal
        if check.fit_rms_mm > params.plane_residual_warn_mm:
            check.flags.append(FLAG_PLANE_RMS)
    return check


# ---------------------------------------------------------------------------
# Comparison with the commanded poses
# ---------------------------------------------------------------------------
def compare_with_commands(checks: list[PoseCheck], capture_set: CaptureSet,
                          params: CheckParameters) -> tuple[RigidTransform | None, str | None, bool]:
    """Solve the rough sensor-to-base transform from the fitted sphere centers and
    fill in each sphere's center residual and each board's normal error. Returns
    (transform or None, note or None, True when the solve failed because the
    commanded and measured centers disagree)."""
    spheres = [c for c in checks if c.center_sensor_mm is not None]
    if len(spheres) < MIN_SPHERE_POSES_FOR_TRANSFORM:
        return None, (f"only {len(spheres)} sphere pose(s) could be fitted; at least "
                      f"{MIN_SPHERE_POSES_FOR_TRANSFORM} are needed to compare with the commanded poses"), False
    commanded = np.array([capture_set.records_for(c.pose_id)[0].target_pose_positioner.translation for c in spheres])
    fitted = np.array([c.center_sensor_mm for c in spheres])
    gate = TransformSolveParameters(max_center_residual_mm=params.sphere_residual_warn_mm)
    try:
        transform = solve_sensor_to_positioner(fitted, commanded, params=gate)
    except ValueError as error:
        return None, (f"{error}: most commanded sphere centers disagree with the measured ones by more than "
                      f"{params.sphere_residual_warn_mm:g} mm; check the tool center point (TCP) of the sphere tool"), True
    residuals = np.linalg.norm(transform.apply_points(fitted) - commanded, axis=1)
    for check, residual in zip(spheres, residuals):
        check.center_residual_mm = float(residual)
        if residual > params.sphere_residual_warn_mm:
            check.flags.append(FLAG_CENTER)
    base_to_sensor = transform.inverse()
    for check in checks:
        if check.plane_normal_sensor is None:
            continue
        commanded_normal_base = capture_set.records_for(check.pose_id)[0].target_pose_positioner.rotation[:, 2]
        commanded_normal = base_to_sensor.apply_directions(commanded_normal_base)
        cosine = float(np.clip(commanded_normal @ check.plane_normal_sensor, -1.0, 1.0))
        check.normal_error_deg = float(np.degrees(np.arccos(cosine)))
        if check.normal_error_deg > params.board_normal_warn_deg:
            check.flags.append(FLAG_NORMAL)
    return transform, None, False


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _number(value: float, spec: str) -> str:
    return "-" if not np.isfinite(value) else format(value, spec)


def format_table(checks: list[PoseCheck]) -> str:
    """Console table of all poses."""
    width = max([len("pose_id")] + [len(c.pose_id) for c in checks])
    header = (f"{'pose_id':<{width}}  {'kind':<6} {'frames':>6} {'valid':>6} {'pixels':>7} {'outl':>5} {'border':>6} "
              f"{'fit_rms_mm':>10} {'center_mm':>9} {'normal_deg':>10}  flags")
    lines = [header, "-" * len(header)]
    for c in checks:
        lines.append(
            f"{c.pose_id:<{width}}  {c.kind:<6} {c.frames:>6d} {_number(c.valid_fraction, '.2f'):>6} "
            f"{c.valid_pixels:>7d} {c.outliers:>5d} {'yes' if c.touches_border else 'no':>6} {_number(c.fit_rms_mm, '.3f'):>10} "
            f"{_number(c.center_residual_mm, '.3f'):>9} {_number(c.normal_error_deg, '.2f'):>10}  "
            f"{'; '.join(c.flags) if c.flags else 'ok'}")
    return "\n".join(lines)


def verdict_line(checks: list[PoseCheck], extra_reasons: list[str]) -> str:
    """The final verdict: how many poses are flagged and why."""
    flagged = [c for c in checks if c.flags]
    if not flagged and not extra_reasons:
        return f"VERDICT: all {len(checks)} poses passed."
    reasons: dict[str, int] = {}
    for check in flagged:
        for flag in check.flags:
            key = flag.split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
    parts = [f"{count} x {reason}" for reason, count in reasons.items()] + extra_reasons
    return f"VERDICT: {len(flagged)} of {len(checks)} poses flagged ({'; '.join(parts)}). Advice: {ADVICE}."


def _json_safe(value):
    """Convert numpy values to JSON types; NaN and infinity become null."""
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def report_dictionary(checks: list[PoseCheck], transform: RigidTransform | None, params: CheckParameters,
                      verdict: str, notes: list[str]) -> dict:
    return {
        "parameters": params.__dict__,
        "poses": [{"pose_id": c.pose_id, "kind": c.kind, "frames": c.frames, "valid_fraction": c.valid_fraction,
                   "valid_pixels": c.valid_pixels, "outliers": c.outliers, "touches_border": c.touches_border, "fit_rms_mm": c.fit_rms_mm,
                   "center_sensor_mm": c.center_sensor_mm, "plane_normal_sensor": c.plane_normal_sensor,
                   "center_residual_mm": c.center_residual_mm, "normal_error_deg": c.normal_error_deg,
                   "flags": c.flags} for c in checks],
        "sensor_to_base_rough": None if transform is None else transform.as_matrix(),
        "notes": notes,
        "n_flagged": sum(bool(c.flags) for c in checks),
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    d = CheckParameters()
    parser = argparse.ArgumentParser(
        description="Quick-look check of a capture set before the long fit: valid pixels, border contact, sphere and "
                    "plane fit residuals, and agreement with the commanded poses.")
    parser.add_argument("--manifest", required=True, type=Path, metavar="PATH", help="manifest CSV or JSON")
    parser.add_argument("--sphere-residual-warn-mm", type=float, default=d.sphere_residual_warn_mm,
                        help="flag a sphere whose surface fit RMS or center residual exceeds this")
    parser.add_argument("--plane-residual-warn-mm", type=float, default=d.plane_residual_warn_mm,
                        help="flag a board whose RMS distance to its fitted plane exceeds this")
    parser.add_argument("--min-valid-fraction", type=float, default=d.min_valid_fraction,
                        help="flag a pose valid in a smaller fraction of its frames")
    parser.add_argument("--border-margin-px", type=int, default=d.border_margin_px,
                        help="valid pixels within this many pixels of the border mean the target is cut off")
    parser.add_argument("--board-normal-warn-deg", type=float, default=d.board_normal_warn_deg,
                        help="flag a board whose fitted and commanded normals differ by more than this")
    parser.add_argument("--out", type=Path, metavar="PATH", help="write a JSON report here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    params = CheckParameters(
        sphere_residual_warn_mm=args.sphere_residual_warn_mm, plane_residual_warn_mm=args.plane_residual_warn_mm,
        min_valid_fraction=args.min_valid_fraction, border_margin_px=args.border_margin_px,
        board_normal_warn_deg=args.board_normal_warn_deg)
    try:
        capture_set = CaptureSet(load_manifest(args.manifest))
    except (OSError, ValueError) as error:
        print(f"ERROR: cannot read the manifest {args.manifest}: {error}. Fix the manifest "
              "(make_manifest.py writes a valid one) and run again.", file=sys.stderr)
        return EXIT_INPUT_ERROR
    if not capture_set.records:
        print(f"ERROR: the manifest {args.manifest} lists no captures.", file=sys.stderr)
        return EXIT_INPUT_ERROR
    checks = [check_pose(capture_set, pose_id, params) for pose_id in capture_set.pose_ids()]
    transform, note, solve_failed = compare_with_commands(checks, capture_set, params)
    notes = [] if note is None else [note]
    extra_reasons = [FLAG_TRANSFORM] if solve_failed else []
    print(format_table(checks))
    for note in notes:
        print(f"NOTE: {note}")
    if transform is not None:
        print("Rough sensor-to-base transform (row-major 4x4):")
        print(np.array2string(transform.as_matrix(), precision=MATRIX_PRINT_DECIMALS, suppress_small=True))
    verdict = verdict_line(checks, extra_reasons)
    print(verdict)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(_json_safe(report_dictionary(checks, transform, params, verdict, notes)),
                                       indent=REPORT_JSON_INDENT), encoding="utf-8")
    return EXIT_FLAGGED if (any(c.flags for c in checks) or extra_reasons) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
