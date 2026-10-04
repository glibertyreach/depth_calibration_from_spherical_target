"""
Capture records: which file shows which target at which commanded pose.

A CaptureRecord ties one depth capture (a ``.mc`` file) to the target it
shows and to that target's pose in the positioner frame (design document,
section 4):

- For a sphere the pose is the center in the positioner frame. It is carried
  as a RigidTransform whose translation is the center; the rotation is
  irrelevant for a sphere and defaults to the identity.
- For a board the pose is the RigidTransform board -> positioner, the board
  being the rectangle |x| <= half_width, |y| <= half_height in its own z = 0
  plane with outward normal +z.

Records come from two sources:

1. A manifest file (JSON or CSV), see :func:`load_manifest`. Relative paths in
   a manifest are relative to the manifest's own directory.
2. The ``robotPose`` entry of each capture file's header, see
   :func:`records_from_headers`. That entry is a 16-float row-major 4x4 matrix
   and is interpreted as the target-to-positioner transform.

Several captures (frames) of the same commanded pose share a ``pose_id``.

Units: millimeters. Pose matrices are row-major.

Pose-id rule for file names (see :func:`split_pose_id_and_frame`)
-----------------------------------------------------------------
The extension is removed. If the remaining stem ends in ``_Index<digits>``
or in ``_<digits>``, that suffix is removed to give the pose id and the digits
give the frame index. Otherwise the pose id is the whole stem and the frame
index is unknown (it then falls back to the order of appearance within the
pose). Examples: ``board_Index07.mc`` -> ("board", 7); ``pose0003_12.mc`` ->
("pose0003", 12); ``scan.mc`` -> ("scan", None).
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from sphcal.geometry.transforms import RigidTransform
from sphcal.io.matcloud import read_matcloud

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TARGET_KIND_SPHERE = "sphere"
"""Target kind string for a sphere."""

TARGET_KIND_BOARD = "board"
"""Target kind string for a flat rectangular board."""

TARGET_KINDS = (TARGET_KIND_SPHERE, TARGET_KIND_BOARD)
"""All accepted target kind strings."""

HOMOGENEOUS_MATRIX_SIZE = 4
"""Side length of a homogeneous 4 x 4 pose matrix."""

HOMOGENEOUS_MATRIX_ENTRIES = HOMOGENEOUS_MATRIX_SIZE * HOMOGENEOUS_MATRIX_SIZE
"""Number of floats in a row-major 4 x 4 pose list (16)."""

CSV_POSE_ROWS = HOMOGENEOUS_MATRIX_SIZE - 1
"""Number of matrix rows stored in the CSV columns m00..m23 (the top three)."""

CSV_POSE_ENTRIES = CSV_POSE_ROWS * HOMOGENEOUS_MATRIX_SIZE
"""Number of CSV pose columns (12): the top three rows of the 4 x 4 pose."""

CENTER_ENTRIES = 3
"""Number of floats in a sphere center ``center_mm`` (x, y, z)."""

DEFAULT_POSE_KEY = "robotPose"
"""Header key holding the 16-float row-major target-to-positioner pose."""

MANIFEST_RECORDS_KEY = "records"
"""Top-level key of the JSON manifest holding the list of records."""

CSV_POSE_COLUMNS = tuple(
    f"m{row}{col}" for row in range(CSV_POSE_ROWS) for col in range(HOMOGENEOUS_MATRIX_SIZE)
)
"""CSV pose column names m00, m01, ..., m23 (row-major top three rows)."""

CSV_BASE_COLUMNS = (
    "file", "pose_id", "frame", "target_kind", "radius_mm", "half_width_mm", "half_height_mm",
) + CSV_POSE_COLUMNS
"""All CSV columns that have a defined meaning; any further columns are
copied into the record's ``metadata`` as strings."""

# Trailing frame-index pattern of a file-name stem: "_Index<digits>" or "_<digits>".
# The pose id must be non-empty (".+?" is a lazy match so the shortest id wins).
_FRAME_SUFFIX_PATTERN = re.compile(r"(?P<pose_id>.+?)(?:_Index(?P<index_a>\d+)|_(?P<index_b>\d+))")


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------
@dataclass
class CaptureRecord:
    """One capture file, the target it shows and the target's commanded pose."""

    path: Path
    pose_id: str
    frame_index: int
    target_kind: str                                  # "sphere" | "board"
    sphere_radius_mm: float | None
    board_half_size_mm: tuple[float, float] | None    # (half_width, half_height)
    target_pose_positioner: RigidTransform            # for a sphere only the translation is used
    metadata: dict = field(default_factory=dict)      # unit id, exposure, anything else


# ---------------------------------------------------------------------------
# File-name rule
# ---------------------------------------------------------------------------
def split_pose_id_and_frame(file_name: str | Path) -> tuple[str, int | None]:
    """Split a capture file name into (pose_id, frame_index) by the rule in
    the module docstring. ``frame_index`` is None when the name carries no
    trailing index pattern."""
    stem = Path(file_name).stem
    match = _FRAME_SUFFIX_PATTERN.fullmatch(stem)
    if match is None:
        return stem, None
    digits = match.group("index_a") or match.group("index_b")
    return match.group("pose_id"), int(digits)


def default_pose_id_from_name(file_name: str | Path) -> str:
    """The pose id of a capture file name: the stem with a trailing
    ``_Index<digits>`` or ``_<digits>`` removed (see module docstring)."""
    return split_pose_id_and_frame(file_name)[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validate_kind_and_target(
    index: int,
    kind: Any,
    radius_mm: float | None,
    half_width_mm: float | None,
    half_height_mm: float | None,
) -> tuple[str, float | None, tuple[float, float] | None]:
    """Check target kind and its size parameters; raise ValueError (mentioning
    the record index) on any problem. Returns (kind, radius, half sizes)."""
    if kind not in TARGET_KINDS:
        raise ValueError(f"record {index}: unknown target kind {kind!r}; expected one of {TARGET_KINDS}")
    if kind == TARGET_KIND_SPHERE:
        if radius_mm is None:
            raise ValueError(f"record {index}: a sphere target needs radius_mm")
        if not radius_mm > 0.0:
            raise ValueError(f"record {index}: sphere radius_mm must be positive, got {radius_mm}")
        return kind, float(radius_mm), None
    if half_width_mm is None or half_height_mm is None:
        raise ValueError(f"record {index}: a board target needs half_width_mm and half_height_mm")
    if not (half_width_mm > 0.0 and half_height_mm > 0.0):
        raise ValueError(f"record {index}: board half sizes must be positive")
    return kind, None, (float(half_width_mm), float(half_height_mm))


def _optional_float(index: int, name: str, value: Any) -> float | None:
    """Convert a manifest value to float; None or an empty string gives None."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"record {index}: {name} is not a number: {value!r}") from error


def _float_list(index: int, name: str, values: Any, expected_count: int) -> list[float]:
    """Convert to a list of exactly ``expected_count`` floats or raise ValueError."""
    try:
        floats = [float(x) for x in values]
    except (TypeError, ValueError) as error:
        raise ValueError(f"record {index}: {name} must be a list of numbers") from error
    if len(floats) != expected_count:
        raise ValueError(f"record {index}: {name} needs {expected_count} numbers, got {len(floats)}")
    return floats


def _identity_for_center(center_mm: Sequence[float]) -> RigidTransform:
    """A pose with identity rotation and the given translation (sphere center)."""
    return RigidTransform(np.eye(HOMOGENEOUS_MATRIX_SIZE - 1), np.asarray(center_mm, dtype=np.float64))


class _IdentityResolver:
    """Fills in pose ids and frame indices not given explicitly: from the file
    name by the module rule, and, if the name carries no index, from the order
    of appearance within the pose."""

    def __init__(self, pose_id_from_name: Callable[[str], str] | None = None) -> None:
        self._pose_id_from_name = pose_id_from_name
        self._count_per_pose: dict[str, int] = {}

    def resolve(self, file_name: str, pose_id: str | None, frame: int | None) -> tuple[str, int]:
        name_pose_id, name_frame = split_pose_id_and_frame(file_name)
        if pose_id is None:
            pose_id = self._pose_id_from_name(file_name) if self._pose_id_from_name else name_pose_id
        if frame is None:
            frame = name_frame
        seen = self._count_per_pose.get(pose_id, 0)
        if frame is None:
            frame = seen  # order of appearance within this pose
        self._count_per_pose[pose_id] = seen + 1
        return pose_id, int(frame)


# ---------------------------------------------------------------------------
# Manifest readers
# ---------------------------------------------------------------------------
def load_manifest(path: str | Path) -> list[CaptureRecord]:
    """Read a JSON (``.json``) or CSV (``.csv``) manifest into records.

    JSON schema::

        {"records": [{"file": "...", "pose_id": "...", "frame": 0,
                      "target": {"kind": "sphere", "radius_mm": 50.0}
                              | {"kind": "board", "half_width_mm": .., "half_height_mm": ..},
                      "pose": {"matrix": [16 floats, row-major]} | {"center_mm": [x, y, z]},
                      "metadata": {...}}, ...]}

    ``pose_id``, ``frame`` and ``metadata`` are optional (defaults: the
    file-name rule, then order of appearance). ``center_mm`` is allowed for
    spheres only. CSV columns: file, pose_id, frame, target_kind, radius_mm,
    half_width_mm, half_height_mm, m00..m23 (the top three rows of the 4 x 4
    pose, row-major); a sphere row leaves the half-size columns empty and a
    board row leaves radius_mm empty; other columns go into ``metadata``.

    Relative file paths are relative to the manifest's directory. Raises
    ValueError, with the record index in the message, for an unknown target
    kind, a missing radius or size, a pose given both ways or not at all, or
    malformed numbers.
    """
    manifest_path = Path(path)
    suffix = manifest_path.suffix.lower()
    if suffix == ".json":
        return _load_manifest_json(manifest_path)
    if suffix == ".csv":
        return _load_manifest_csv(manifest_path)
    raise ValueError(f"unsupported manifest type {manifest_path.suffix!r}; use .json or .csv")


def _resolve_path(manifest_dir: Path, file_entry: str) -> Path:
    """Absolute paths stay as they are; relative ones are relative to the manifest."""
    candidate = Path(file_entry)
    return candidate if candidate.is_absolute() else manifest_dir / candidate


def _load_manifest_json(manifest_path: Path) -> list[CaptureRecord]:
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = document.get(MANIFEST_RECORDS_KEY) if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"{manifest_path}: expected an object with a '{MANIFEST_RECORDS_KEY}' list")
    resolver = _IdentityResolver()
    records: list[CaptureRecord] = []
    for index, entry in enumerate(entries):
        if "file" not in entry:
            raise ValueError(f"record {index}: missing 'file'")
        target = entry.get("target") or {}
        kind, radius, half_size = _validate_kind_and_target(
            index,
            target.get("kind"),
            _optional_float(index, "radius_mm", target.get("radius_mm")),
            _optional_float(index, "half_width_mm", target.get("half_width_mm")),
            _optional_float(index, "half_height_mm", target.get("half_height_mm")),
        )
        pose = entry.get("pose") or {}
        has_matrix = "matrix" in pose
        has_center = "center_mm" in pose
        if has_matrix and has_center:
            raise ValueError(f"record {index}: pose gives both 'matrix' and 'center_mm'; give exactly one")
        if has_matrix:
            matrix = _float_list(index, "pose.matrix", pose["matrix"], HOMOGENEOUS_MATRIX_ENTRIES)
            pose_transform = RigidTransform.from_matrix(np.asarray(matrix).reshape(
                HOMOGENEOUS_MATRIX_SIZE, HOMOGENEOUS_MATRIX_SIZE))
        elif has_center:
            if kind != TARGET_KIND_SPHERE:
                raise ValueError(f"record {index}: 'center_mm' is only valid for a sphere; a board needs a matrix")
            pose_transform = _identity_for_center(_float_list(index, "pose.center_mm", pose["center_mm"], CENTER_ENTRIES))
        else:
            raise ValueError(f"record {index}: pose needs 'matrix' or 'center_mm'")
        frame_value = entry.get("frame")
        pose_id, frame_index = resolver.resolve(
            str(entry["file"]),
            None if entry.get("pose_id") is None else str(entry["pose_id"]),
            None if frame_value is None else int(frame_value),
        )
        records.append(CaptureRecord(
            path=_resolve_path(manifest_path.parent, str(entry["file"])),
            pose_id=pose_id, frame_index=frame_index, target_kind=kind,
            sphere_radius_mm=radius, board_half_size_mm=half_size,
            target_pose_positioner=pose_transform, metadata=dict(entry.get("metadata") or {}),
        ))
    return records


def _load_manifest_csv(manifest_path: Path) -> list[CaptureRecord]:
    resolver = _IdentityResolver()
    records: list[CaptureRecord] = []
    with manifest_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in ("file", "target_kind") + CSV_POSE_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{manifest_path}: missing CSV columns {missing}")
        for index, row in enumerate(reader):
            kind, radius, half_size = _validate_kind_and_target(
                index,
                (row.get("target_kind") or "").strip() or None,
                _optional_float(index, "radius_mm", row.get("radius_mm")),
                _optional_float(index, "half_width_mm", row.get("half_width_mm")),
                _optional_float(index, "half_height_mm", row.get("half_height_mm")),
            )
            top_rows = [_optional_float(index, name, row.get(name)) for name in CSV_POSE_COLUMNS]
            if any(value is None for value in top_rows):
                raise ValueError(f"record {index}: all pose columns m00..m23 are required")
            matrix = np.eye(HOMOGENEOUS_MATRIX_SIZE)
            matrix[:CSV_POSE_ROWS, :] = np.asarray(top_rows, dtype=np.float64).reshape(
                CSV_POSE_ROWS, HOMOGENEOUS_MATRIX_SIZE)
            file_entry = (row.get("file") or "").strip()
            if not file_entry:
                raise ValueError(f"record {index}: missing 'file'")
            frame_text = (row.get("frame") or "").strip()
            pose_id_text = (row.get("pose_id") or "").strip()
            pose_id, frame_index = resolver.resolve(
                file_entry, pose_id_text or None, int(frame_text) if frame_text else None)
            metadata = {k: v for k, v in row.items()
                        if k not in CSV_BASE_COLUMNS and k is not None and v not in (None, "")}
            records.append(CaptureRecord(
                path=_resolve_path(manifest_path.parent, file_entry),
                pose_id=pose_id, frame_index=frame_index, target_kind=kind,
                sphere_radius_mm=radius, board_half_size_mm=half_size,
                target_pose_positioner=RigidTransform.from_matrix(matrix), metadata=metadata,
            ))
    return records


# ---------------------------------------------------------------------------
# Manifest writers
# ---------------------------------------------------------------------------
def _manifest_file_entry(manifest_dir: Path, record_path: Path) -> str:
    """The file entry to write: relative to the manifest directory when the
    capture lies below it, otherwise the absolute path (POSIX separators)."""
    try:
        return record_path.resolve().relative_to(manifest_dir.resolve()).as_posix()
    except ValueError:
        return record_path.resolve().as_posix()


def write_manifest_json(path: str | Path, records: Iterable[CaptureRecord]) -> Path:
    """Write records as a JSON manifest (schema in :func:`load_manifest`).
    The pose is always written as a full 16-float ``matrix``. Returns the path."""
    manifest_path = Path(path)
    entries = []
    for record in records:
        if record.target_kind == TARGET_KIND_SPHERE:
            target: dict[str, Any] = {"kind": TARGET_KIND_SPHERE, "radius_mm": record.sphere_radius_mm}
        else:
            half_width, half_height = record.board_half_size_mm
            target = {"kind": TARGET_KIND_BOARD, "half_width_mm": half_width, "half_height_mm": half_height}
        entry: dict[str, Any] = {
            "file": _manifest_file_entry(manifest_path.parent, record.path),
            "pose_id": record.pose_id,
            "frame": record.frame_index,
            "target": target,
            "pose": {"matrix": [float(x) for x in record.target_pose_positioner.as_matrix().reshape(-1)]},
        }
        if record.metadata:
            entry["metadata"] = record.metadata
        entries.append(entry)
    manifest_path.write_text(json.dumps({MANIFEST_RECORDS_KEY: entries}, indent=2), encoding="utf-8")
    return manifest_path


def write_manifest_csv(path: str | Path, records: Iterable[CaptureRecord]) -> Path:
    """Write records as a CSV manifest (columns in :func:`load_manifest`);
    metadata keys become extra columns. Returns the path."""
    manifest_path = Path(path)
    records = list(records)
    metadata_columns = sorted({key for record in records for key in record.metadata})
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(CSV_BASE_COLUMNS) + metadata_columns)
        for record in records:
            top_rows = record.target_pose_positioner.as_matrix()[:CSV_POSE_ROWS, :].reshape(-1)
            half = record.board_half_size_mm
            writer.writerow(
                [_manifest_file_entry(manifest_path.parent, record.path), record.pose_id, record.frame_index,
                 record.target_kind,
                 "" if record.sphere_radius_mm is None else repr(float(record.sphere_radius_mm)),
                 "" if half is None else repr(float(half[0])),
                 "" if half is None else repr(float(half[1]))]
                + [repr(float(x)) for x in top_rows]
                + [record.metadata.get(key, "") for key in metadata_columns]
            )
    return manifest_path


# ---------------------------------------------------------------------------
# Records from capture-file headers
# ---------------------------------------------------------------------------
def records_from_headers(
    paths: Iterable[str | Path],
    target_kind: str,
    sphere_radius_mm: float | None = None,
    board_half_size_mm: tuple[float, float] | None = None,
    pose_key: str = DEFAULT_POSE_KEY,
    pose_id_from_name: Callable[[str], str] | None = None,
) -> list[CaptureRecord]:
    """Build records from capture files whose header carries the target pose.

    The header entry ``pose_key`` (default ``robotPose``) is a 16-float
    row-major 4 x 4 list, interpreted as the target-to-positioner transform
    (for a sphere its translation is the center). All files show the same
    kind of target with the same size.

    pose_id: by default :func:`default_pose_id_from_name` (trailing
    ``_Index<digits>`` or ``_<digits>`` removed from the stem); the frame
    index is those digits, else the order of appearance within the pose.
    ``pose_id_from_name`` overrides the pose id; it receives the file name
    (with extension, no directory).

    Raises ValueError (with the record index) for a bad target description or
    a header without a valid pose.
    """
    resolver = _IdentityResolver(pose_id_from_name)
    records: list[CaptureRecord] = []
    for index, raw_path in enumerate(paths):
        file_path = Path(raw_path)
        kind, radius, half_size = _validate_kind_and_target(
            index, target_kind, sphere_radius_mm,
            None if board_half_size_mm is None else board_half_size_mm[0],
            None if board_half_size_mm is None else board_half_size_mm[1],
        )
        # Only the header is needed. read_matcloud decodes the arrays too and we
        # discard them; a header-only reader would be a pure optimization.
        header = read_matcloud(file_path).header
        if pose_key not in header:
            raise ValueError(f"record {index}: {file_path} has no header entry {pose_key!r}")
        flat = _float_list(index, f"header[{pose_key!r}]", header[pose_key], HOMOGENEOUS_MATRIX_ENTRIES)
        pose = RigidTransform.from_matrix(np.asarray(flat).reshape(HOMOGENEOUS_MATRIX_SIZE, HOMOGENEOUS_MATRIX_SIZE))
        pose_id, frame_index = resolver.resolve(file_path.name, None, None)
        metadata: dict[str, Any] = {}
        if "cameraName" in header:
            metadata["cameraName"] = header["cameraName"]
        records.append(CaptureRecord(
            path=file_path, pose_id=pose_id, frame_index=frame_index, target_kind=kind,
            sphere_radius_mm=radius, board_half_size_mm=half_size,
            target_pose_positioner=pose, metadata=metadata,
        ))
    return records
