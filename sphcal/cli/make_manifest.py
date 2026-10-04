"""
Command line: build the capture manifest (design document section 5,
``sphcal/io/poses.py`` schema) from the robot's pose log and a directory of
capture files.

    python3 -m sphcal.cli.make_manifest --pose-log pose_log.csv --captures captures/ --out manifest.csv

Pose log (CSV, one row per commanded pose, positions in millimeters in the
robot base frame)
    pose_id, kind, radius_mm, half_width_mm, half_height_mm,
    x_mm, y_mm, z_mm, rotation_type, r1, r2, r3, r4 (r5..r9 for a matrix)

    kind          sphere or board.
    radius_mm     sphere radius (sphere rows).
    half_width_mm, half_height_mm   board half sizes (board rows): half the long
                  edge (board x) and half the short edge (board y).
    x_mm..z_mm    for a sphere the center (the TCP when the sphere TCP is
                  active); for a board the origin of the board frame (the tool
                  frame when the board tool frame is active).
    rotation_type, r1..r9   the tool orientation in the base frame, read as in
                  the table below. A sphere may use ``none`` (identity); a
                  board needs a real orientation, its z axis being the outward
                  normal that must face the sensor.

The ``poses.csv`` written by ``sphcal.cli.plan_poses`` is accepted as it is: it
is recognized by its columns base_x_mm, base_y_mm, base_z_mm and r00..r22 (the
tool-to-base rotation matrix, row-major) and is read as rotation_type matrix.

Rotation conventions (all through scipy.spatial.transform.Rotation; the
result is the tool-to-base rotation matrix; angles in degrees)

    rotation_type      r1 r2 r3 (r4 ...)      meaning                        scipy call
    none               (unused)               identity (sphere only)         Rotation.identity()
    quaternion_wxyz    w x y z                unit quaternion, scalar first  from_quat([x, y, z, w])
    quaternion_xyzw    x y z w                unit quaternion, scalar last   from_quat([x, y, z, w])
    euler_zyx_deg      A B C                  intrinsic Z-Y-X: rotate about    from_euler("ZYX", [A, B, C])
                                              tool z by A, then about the new
                                              y by B, then about the new x by
                                              C (KUKA A, B, C)
    euler_xyz_deg      a b c                  intrinsic X-Y-Z: about x by a,   from_euler("XYZ", [a, b, c])
                                              then new y by b, then new z by c
    fixed_xyz_deg      W P R                  extrinsic x-y-z: about the       from_euler("xyz", [W, P, R])
                                              fixed base x by W, then fixed
                                              y by P, then fixed z by R
                                              (FANUC W, P, R)
    rotvec_deg         x y z                  rotation vector, direction =    from_rotvec(radians(v))
                                              axis, length = angle in degrees
    matrix             m00 m01 m02 m10 ... m22   row-major 3x3 rotation       from_matrix(M)
                                              matrix (r1..r9)

A quaternion that is not of unit length is normalized and reported as a
warning; a rotation matrix that is not orthonormal is also reported and
re-orthonormalized.

Capture files are matched to pose ids by their names: the stem minus a
trailing ``_Index<digits>`` or ``_<digits>`` is the pose id and the digits are
the frame index (``sphcal.io.poses.split_pose_id_and_frame``). Pose ids that
themselves end in digits, as those of plan_poses do, therefore need a frame
suffix, for example ``s040_z0300_000_Index00.mc``. A file whose whole stem is
a pose id is also accepted (one frame).

Exit code: 0 on success (warnings are listed but do not fail unless --strict),
2 when the log or the captures must be fixed (every problem is listed).
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from sphcal.geometry.transforms import RigidTransform
from sphcal.io.poses import (CaptureRecord, TARGET_KIND_BOARD, TARGET_KIND_SPHERE, TARGET_KINDS,
                             split_pose_id_and_frame, write_manifest_csv, write_manifest_json)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_INPUT_ERROR = 2
"""Exit codes: success, and an input the technician must fix."""

QUATERNION_NORM_WARN_TOLERANCE = 1.0e-3
"""A quaternion whose norm differs from 1 by more than this is reported as non-unit
(it is normalized in any case)."""
MATRIX_ORTHONORMALITY_WARN_TOLERANCE = 1.0e-3
"""A rotation matrix whose R R^T differs from the identity by more than this is
reported (it is re-orthonormalized in any case)."""
MIN_QUATERNION_NORM = 1.0e-9
"""A quaternion shorter than this has no direction and is an error."""

ROTATION_NONE = "none"
ROTATION_QUATERNION_WXYZ = "quaternion_wxyz"
ROTATION_QUATERNION_XYZW = "quaternion_xyzw"
ROTATION_EULER_ZYX = "euler_zyx_deg"
ROTATION_EULER_XYZ = "euler_xyz_deg"
ROTATION_FIXED_XYZ = "fixed_xyz_deg"
ROTATION_ROTVEC = "rotvec_deg"
ROTATION_MATRIX = "matrix"

ROTATION_VALUE_COUNTS = {
    ROTATION_NONE: 0, ROTATION_QUATERNION_WXYZ: 4, ROTATION_QUATERNION_XYZW: 4, ROTATION_EULER_ZYX: 3,
    ROTATION_EULER_XYZ: 3, ROTATION_FIXED_XYZ: 3, ROTATION_ROTVEC: 3, ROTATION_MATRIX: 9,
}
"""How many r columns each rotation_type reads."""

EULER_SEQUENCES = {ROTATION_EULER_ZYX: "ZYX", ROTATION_EULER_XYZ: "XYZ", ROTATION_FIXED_XYZ: "xyz"}
"""scipy sequences: upper case is intrinsic (rotating axes), lower case extrinsic (fixed axes)."""

LOG_REQUIRED_COLUMNS = ("pose_id", "kind", "x_mm", "y_mm", "z_mm", "rotation_type")
"""Columns every pose log needs; radius/half-size columns may be absent when no row needs them."""
PLAN_TRANSLATION_COLUMNS = ("base_x_mm", "base_y_mm", "base_z_mm")
PLAN_MATRIX_COLUMNS = tuple(f"r{row}{col}" for row in range(3) for col in range(3))
"""Columns by which a poses.csv from plan_poses.py is recognized."""
LOG_VALUE_COLUMNS = tuple(f"r{index}" for index in range(1, ROTATION_VALUE_COUNTS[ROTATION_MATRIX] + 1))
"""The rotation value columns r1..r9 of a pose log."""

FORMAT_CSV = "csv"
FORMAT_JSON = "json"
MAX_FILE_NAMES_SHOWN = 3
"""Capture file names quoted in a message about unmatched files."""
CAPTURE_PATTERN = "*.mc"
"""Capture files looked for in --captures."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class LoggedPose:
    """One validated row of the pose log: target description and tool pose in the base frame."""

    pose_id: str
    kind: str
    radius_mm: float | None
    half_size_mm: tuple[float, float] | None
    pose: RigidTransform


@dataclass
class Messages:
    """Problems found while reading; errors stop the run, warnings do not (unless --strict)."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rotation conversion
# ---------------------------------------------------------------------------
def rotation_from_values(rotation_type: str, values: list[float], where: str,
                         messages: Messages) -> np.ndarray | None:
    """The 3 x 3 tool-to-base rotation matrix for a rotation_type and its r values
    (conventions in the module docstring). Returns None, after recording an
    error, when the row cannot be converted. ``where`` names the row for messages."""
    if rotation_type == ROTATION_NONE:
        return Rotation.identity().as_matrix()
    if rotation_type in (ROTATION_QUATERNION_WXYZ, ROTATION_QUATERNION_XYZW):
        quaternion = np.asarray(values, dtype=np.float64)
        norm = float(np.linalg.norm(quaternion))
        if norm < MIN_QUATERNION_NORM:
            messages.errors.append(f"{where}: the quaternion is all zeros; enter the robot's quaternion values")
            return None
        if abs(norm - 1.0) > QUATERNION_NORM_WARN_TOLERANCE:
            messages.warnings.append(
                f"{where}: the quaternion has length {norm:.5f}, not 1; it was normalized. If the robot reports "
                "a unit quaternion, check that the four values are in the order given by rotation_type")
        quaternion = quaternion / norm
        if rotation_type == ROTATION_QUATERNION_WXYZ:
            quaternion = np.roll(quaternion, -1)    # scipy wants x, y, z, w
        return Rotation.from_quat(quaternion).as_matrix()
    if rotation_type in EULER_SEQUENCES:
        return Rotation.from_euler(EULER_SEQUENCES[rotation_type], values, degrees=True).as_matrix()
    if rotation_type == ROTATION_ROTVEC:
        return Rotation.from_rotvec(np.radians(values)).as_matrix()
    if rotation_type == ROTATION_MATRIX:
        matrix = np.asarray(values, dtype=np.float64).reshape(3, 3)
        determinant = float(np.linalg.det(matrix))
        if determinant <= 0.0:
            messages.errors.append(f"{where}: the 3x3 matrix is not a proper rotation (determinant "
                                   f"{determinant:.3f}, it must be +1); check that r1..r9 are row-major")
            return None
        if np.abs(matrix @ matrix.T - np.eye(3)).max() > MATRIX_ORTHONORMALITY_WARN_TOLERANCE:
            messages.warnings.append(f"{where}: the matrix is not orthonormal (rows are not perpendicular unit "
                                     "vectors); it was re-orthonormalized. Check the number of digits logged.")
        return Rotation.from_matrix(matrix).as_matrix()
    messages.errors.append(f"{where}: unknown rotation_type {rotation_type!r}; use one of "
                           f"{', '.join(ROTATION_VALUE_COUNTS)}")
    return None


# ---------------------------------------------------------------------------
# Pose log
# ---------------------------------------------------------------------------
def _number(row: dict, column: str) -> float | None:
    """A float from a CSV cell; None when the column is absent or the cell empty.
    Raises ValueError for text that is not a number."""
    text = (row.get(column) or "").strip()
    return float(text) if text else None


def read_pose_log(path: Path, messages: Messages) -> list[LoggedPose]:
    """Read the pose log (or a plan_poses poses.csv) into validated poses; every
    problem found is appended to ``messages`` with the row it came from."""
    try:
        handle = Path(path).open("r", newline="", encoding="utf-8-sig")
    except OSError as error:
        messages.errors.append(f"cannot read the pose log {path}: {error.strerror}")
        return []
    with handle:
        reader = csv.DictReader(handle)
        columns = [name.strip() for name in (reader.fieldnames or [])]
        rows = [{(key or "").strip(): value for key, value in row.items()} for row in reader]
    from_plan = all(name in columns for name in PLAN_TRANSLATION_COLUMNS + PLAN_MATRIX_COLUMNS)
    if from_plan:
        translation_columns, required = PLAN_TRANSLATION_COLUMNS, ("pose_id", "kind")
    else:
        translation_columns, required = ("x_mm", "y_mm", "z_mm"), LOG_REQUIRED_COLUMNS
    missing = [name for name in required + translation_columns if name not in columns]
    if missing:
        messages.errors.append(
            f"the pose log {path} lacks the columns {sorted(set(missing))}. Expected "
            f"{', '.join(LOG_REQUIRED_COLUMNS)}, radius_mm, half_width_mm, half_height_mm, r1..r4 "
            "(or the poses.csv written by plan_poses)")
        return []
    poses: list[LoggedPose] = []
    seen: set[str] = set()
    for line_number, row in enumerate(rows, start=2):       # line 1 is the header
        pose_id = (row.get("pose_id") or "").strip()
        where = f"pose log line {line_number} (pose {pose_id or '?'})"
        try:
            pose = _read_pose_row(row, pose_id, where, translation_columns, from_plan, messages)
        except ValueError as error:
            messages.errors.append(f"{where}: {error}; enter plain numbers")
            continue
        if pose is None:
            continue
        if pose_id in seen:
            messages.errors.append(f"{where}: the pose id appears more than once; pose ids must be unique")
            continue
        seen.add(pose_id)
        poses.append(pose)
    if not rows:
        messages.errors.append(f"the pose log {path} has no data rows")
    return poses


def _read_pose_row(row: dict, pose_id: str, where: str, translation_columns: tuple[str, ...], from_plan: bool,
                   messages: Messages) -> LoggedPose | None:
    """One validated log row, or None after recording an error. May raise ValueError for bad numbers."""
    errors_before = len(messages.errors)
    if not pose_id:
        messages.errors.append(f"{where}: the pose_id is empty")
    kind = (row.get("kind") or "").strip().lower()
    if kind not in TARGET_KINDS:
        messages.errors.append(f"{where}: kind {kind!r} is not one of {', '.join(TARGET_KINDS)}")
    radius = _number(row, "radius_mm")
    half_width, half_height = _number(row, "half_width_mm"), _number(row, "half_height_mm")
    if kind == TARGET_KIND_SPHERE and (radius is None or not radius > 0.0):
        messages.errors.append(f"{where}: a sphere needs a positive radius_mm; fill in the sphere radius")
    if kind == TARGET_KIND_BOARD and (half_width is None or half_height is None
                                       or not (half_width > 0.0 and half_height > 0.0)):
        messages.errors.append(f"{where}: a board needs positive half_width_mm and half_height_mm "
                               "(half the long and half the short edge of the board)")
    translation = [_number(row, name) for name in translation_columns]
    if any(value is None for value in translation):
        messages.errors.append(f"{where}: the position {', '.join(translation_columns)} must all be filled in")
    if from_plan:
        rotation_type = ROTATION_MATRIX
        values = [_number(row, name) for name in PLAN_MATRIX_COLUMNS]
    else:
        rotation_type = (row.get("rotation_type") or "").strip().lower()
        count = ROTATION_VALUE_COUNTS.get(rotation_type)
        values = [_number(row, name) for name in LOG_VALUE_COLUMNS[:count or 0]]
        if kind == TARGET_KIND_BOARD and rotation_type == ROTATION_NONE:
            messages.errors.append(f"{where}: a board needs its orientation, so rotation_type none is not allowed; "
                                   "log the tool orientation (the board normal must be known)")
    if any(value is None for value in values):
        messages.errors.append(f"{where}: rotation_type {rotation_type} needs the values r1..r"
                               f"{ROTATION_VALUE_COUNTS.get(rotation_type, 0)} to be filled in")
    if len(messages.errors) > errors_before:
        return None
    rotation = rotation_from_values(rotation_type, values, where, messages)
    if rotation is None:
        return None
    return LoggedPose(pose_id=pose_id, kind=kind, radius_mm=radius if kind == TARGET_KIND_SPHERE else None,
                      half_size_mm=(half_width, half_height) if kind == TARGET_KIND_BOARD else None,
                      pose=RigidTransform(rotation, np.asarray(translation, dtype=np.float64)))


# ---------------------------------------------------------------------------
# Capture files
# ---------------------------------------------------------------------------
def match_capture_files(directory: Path, known_ids: set[str], messages: Messages) -> dict[str, list[tuple[int | None, Path]]]:
    """Group the .mc files of a directory by pose id. A file name is split by
    split_pose_id_and_frame; when that id is unknown but the whole stem is a
    known pose id, the stem is used. Returns {pose_id: [(frame or None, path)]}
    including ids not in the log, which the caller reports."""
    files = sorted(Path(directory).glob(CAPTURE_PATTERN))
    if not files:
        messages.errors.append(f"no {CAPTURE_PATTERN} capture files found in {directory}; check the --captures path")
    grouped: dict[str, list[tuple[int | None, Path]]] = defaultdict(list)
    for file in files:
        pose_id, frame = split_pose_id_and_frame(file.name)
        if pose_id not in known_ids and file.stem in known_ids:
            pose_id, frame = file.stem, None
        grouped[pose_id].append((frame, file))
    return grouped


def build_records(poses: list[LoggedPose], grouped: dict[str, list[tuple[int | None, Path]]],
                  captures_dir: Path, messages: Messages) -> list[CaptureRecord]:
    """Capture records for every logged pose that has capture files, in log order.
    Records problems with the pose/file correspondence in ``messages``."""
    logged = {pose.pose_id for pose in poses}
    for pose_id in sorted(set(grouped) - logged):
        names = ", ".join(path.name for _, path in grouped[pose_id][:MAX_FILE_NAMES_SHOWN])
        messages.warnings.append(
            f"capture files for pose id '{pose_id}' ({names}{', ...' if len(grouped[pose_id]) > MAX_FILE_NAMES_SHOWN else ''}) have no "
            "row in the pose log, so they were left out; add the pose to the log or rename the files")
    records: list[CaptureRecord] = []
    for pose in poses:
        entries = grouped.get(pose.pose_id)
        if not entries:
            messages.warnings.append(
                f"pose '{pose.pose_id}' is in the pose log but no capture file in {captures_dir} matches it; "
                f"name its files {pose.pose_id}_Index00.mc, {pose.pose_id}_Index01.mc, ... or remove the pose from the log")
            continue
        # Frames without an index in their name follow the numbered ones in file-name order.
        ordered = sorted(entries, key=lambda item: (item[0] is None, item[0] if item[0] is not None else 0, item[1].name))
        used: set[int] = set()
        next_free = 0
        for frame, path in ordered:
            if frame is None:
                while next_free in used:
                    next_free += 1
                frame = next_free
            if frame in used:
                messages.warnings.append(f"pose '{pose.pose_id}': more than one file has frame index {frame} "
                                         f"(for example {path.name}); check the file names")
            used.add(frame)
            records.append(CaptureRecord(
                path=path, pose_id=pose.pose_id, frame_index=int(frame), target_kind=pose.kind,
                sphere_radius_mm=pose.radius_mm, board_half_size_mm=pose.half_size_mm,
                target_pose_positioner=pose.pose, metadata={}))
    return records


def count_summary(records: list[CaptureRecord]) -> str:
    """Final count line: poses by kind and frames per pose (min/max)."""
    frames: dict[str, int] = defaultdict(int)
    kinds: dict[str, str] = {}
    for record in records:
        frames[record.pose_id] += 1
        kinds[record.pose_id] = record.target_kind
    if not frames:
        return "No poses with captures."
    spheres = sum(kind == TARGET_KIND_SPHERE for kind in kinds.values())
    return (f"{len(frames)} poses ({spheres} sphere, {len(frames) - spheres} board), "
            f"{len(records)} capture files, frames per pose min {min(frames.values())} / max {max(frames.values())}")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the capture manifest from a pose log (CSV) and a directory of .mc capture files. "
                    "The poses.csv written by plan_poses is accepted as a pose log.")
    parser.add_argument("--pose-log", required=True, type=Path, metavar="PATH",
                        help="CSV with pose_id, kind, radius_mm, half_width_mm, half_height_mm, x_mm, y_mm, z_mm, "
                             "rotation_type, r1..r4 (rotation_type: " + ", ".join(ROTATION_VALUE_COUNTS) + ")")
    parser.add_argument("--captures", required=True, type=Path, metavar="DIR",
                        help="directory of .mc files named <pose_id>_Index<frame>.mc")
    parser.add_argument("--format", choices=(FORMAT_CSV, FORMAT_JSON), default=FORMAT_CSV, help="manifest format")
    parser.add_argument("--out", required=True, type=Path, metavar="PATH", help="manifest file to write")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings (missing or unmatched captures, non-unit quaternions) as errors")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    messages = Messages()
    poses = read_pose_log(args.pose_log, messages)
    records: list[CaptureRecord] = []
    if not args.captures.is_dir():
        messages.errors.append(f"--captures {args.captures} is not a directory; give the folder holding the .mc files")
    elif poses:
        grouped = match_capture_files(args.captures, {pose.pose_id for pose in poses}, messages)
        records = build_records(poses, grouped, args.captures, messages)
    if not records and not messages.errors:
        messages.errors.append("no pose has capture files, so there is nothing to write; check that the file names "
                               "start with the pose ids of the log")
    for warning in messages.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in messages.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if messages.errors or (args.strict and messages.warnings):
        print(f"Manifest not written: {len(messages.errors)} error(s), {len(messages.warnings)} warning(s). "
              "Fix the items above and run again.", file=sys.stderr)
        return EXIT_INPUT_ERROR
    args.out.parent.mkdir(parents=True, exist_ok=True)
    (write_manifest_json if args.format == FORMAT_JSON else write_manifest_csv)(args.out, records)
    print(f"Wrote {args.out} ({args.format}): {count_summary(records)}; {len(messages.warnings)} warning(s).")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
