"""Tests for sphcal.io.poses and sphcal.io.capture_set."""
from pathlib import Path

import numpy as np
import pytest

from sphcal.geometry.transforms import RigidTransform
from sphcal.io.capture_set import CaptureSet
from sphcal.io.matcloud import write_matcloud
from sphcal.io.poses import (
    CaptureRecord, default_pose_id_from_name, load_manifest, records_from_headers,
    split_pose_id_and_frame, write_manifest_csv, write_manifest_json,
)

IMAGE_HEIGHT = 6
IMAGE_WIDTH = 8
FOCAL_PX = 50.0
PRINCIPAL_X = 4.0
PRINCIPAL_Y = 3.0
SPHERE_RADIUS_MM = 40.0
BOARD_HALF_SIZE_MM = (100.0, 75.0)
TOLERANCE = 1e-12


def _pose(angle_deg: float, translation) -> RigidTransform:
    return RigidTransform.from_rotation_vector_degrees([0.0, 0.0, angle_deg], translation)


def _make_records(directory: Path) -> list[CaptureRecord]:
    return [
        CaptureRecord(directory / "a_Index00.mc", "a", 0, "sphere", SPHERE_RADIUS_MM, None,
                      _pose(10.0, [1.0, 2.0, 3.0]), {}),
        CaptureRecord(directory / "a_Index01.mc", "a", 1, "sphere", SPHERE_RADIUS_MM, None,
                      _pose(10.0, [1.0, 2.0, 3.0]), {}),
        CaptureRecord(directory / "sub" / "b_Index00.mc", "b", 0, "board", None, BOARD_HALF_SIZE_MM,
                      _pose(-25.0, [10.0, -20.0, 500.0]), {}),
    ]


def _assert_same_records(first, second):
    assert len(first) == len(second)
    for a, b in zip(first, second):
        assert Path(a.path).resolve() == Path(b.path).resolve()
        assert (a.pose_id, a.frame_index, a.target_kind) == (b.pose_id, b.frame_index, b.target_kind)
        assert a.sphere_radius_mm == b.sphere_radius_mm
        assert a.board_half_size_mm == b.board_half_size_mm
        assert np.allclose(a.target_pose_positioner.as_matrix(), b.target_pose_positioner.as_matrix(),
                           atol=TOLERANCE, rtol=0.0)
        assert a.metadata == b.metadata


def test_manifest_json_and_csv_round_trip(tmp_path):
    records = _make_records(tmp_path)
    write_manifest_json(tmp_path / "m.json", records)
    write_manifest_csv(tmp_path / "m.csv", records)
    from_json = load_manifest(tmp_path / "m.json")
    from_csv = load_manifest(tmp_path / "m.csv")
    _assert_same_records(records, from_json)
    _assert_same_records(records, from_csv)
    _assert_same_records(from_json, from_csv)


def test_manifest_json_center_and_relative_paths(tmp_path):
    (tmp_path / "m.json").write_text(
        '{"records": [{"file": "x_Index03.mc", "target": {"kind": "sphere", "radius_mm": 25},'
        ' "pose": {"center_mm": [1, 2, 3]}}]}')
    (record,) = load_manifest(tmp_path / "m.json")
    assert record.path == tmp_path / "x_Index03.mc"
    assert (record.pose_id, record.frame_index) == ("x", 3)  # file-name rule
    assert np.allclose(record.target_pose_positioner.translation, [1.0, 2.0, 3.0])
    assert np.allclose(record.target_pose_positioner.rotation, np.eye(3))


def _write_json(path: Path, record: dict) -> Path:
    import json
    path.write_text(json.dumps({"records": [record]}))
    return path


GOOD_SPHERE = {"file": "a.mc", "target": {"kind": "sphere", "radius_mm": 10.0}, "pose": {"center_mm": [0, 0, 1]}}


@pytest.mark.parametrize("mutation, fragment", [
    (lambda r: r["target"].update(kind="cube"), "unknown target kind"),
    (lambda r: r["target"].pop("radius_mm"), "radius"),
    (lambda r: r.update(target={"kind": "board", "half_width_mm": 5.0}), "half"),
    (lambda r: r["pose"].update(matrix=list(range(16))), "both"),
    (lambda r: r.update(pose={}), "pose"),
])
def test_manifest_validation_errors_include_record_index(tmp_path, mutation, fragment):
    import copy
    record = copy.deepcopy(GOOD_SPHERE)
    mutation(record)
    manifest = _write_json(tmp_path / "m.json", record)
    with pytest.raises(ValueError, match=r"record 0") as excinfo:
        load_manifest(manifest)
    assert fragment in str(excinfo.value)


def test_csv_validation_error_includes_record_index(tmp_path):
    records = _make_records(tmp_path)
    write_manifest_csv(tmp_path / "m.csv", records)
    text = (tmp_path / "m.csv").read_text().splitlines()
    # Blank the radius of the second data row (index 1), a sphere row.
    header = text[0].split(",")
    cells = text[2].split(",")
    cells[header.index("radius_mm")] = ""
    text[2] = ",".join(cells)
    (tmp_path / "bad.csv").write_text("\n".join(text) + "\n")
    with pytest.raises(ValueError, match=r"record 1"):
        load_manifest(tmp_path / "bad.csv")


def test_file_name_rule():
    assert split_pose_id_and_frame("board_Index07.mc") == ("board", 7)
    assert split_pose_id_and_frame("pose0003_12.mc") == ("pose0003", 12)
    assert split_pose_id_and_frame("scan_12_Index03.mc") == ("scan_12", 3)
    assert split_pose_id_and_frame("scan.mc") == ("scan", None)
    assert default_pose_id_from_name("dir/x_Index00.mc") == "x"


def _write_capture(path: Path, pose_matrix, with_pose=True):
    xyz = np.zeros((IMAGE_HEIGHT, IMAGE_WIDTH, 3), dtype=np.float32)
    xyz[..., 2] = 300.0
    xyz[0, 0] = 0.0  # one unread pixel
    header = {"fx": FOCAL_PX, "fy": FOCAL_PX, "cx": PRINCIPAL_X, "cy": PRINCIPAL_Y,
              "h": IMAGE_WIDTH, "v": IMAGE_HEIGHT}
    if with_pose:
        header["robotPose"] = [float(x) for x in pose_matrix.reshape(-1)]
    write_matcloud(path, header, {"XYZ": xyz})


def test_records_from_headers(tmp_path):
    pose_a = _pose(30.0, [10.0, 20.0, 30.0]).as_matrix()
    pose_b = _pose(-5.0, [-1.0, 2.0, 3.0]).as_matrix()
    paths = [tmp_path / "p1_Index01.mc", tmp_path / "p1_Index00.mc", tmp_path / "p2.mc", tmp_path / "p2_extra.mc"]
    for path, pose in zip(paths, [pose_a, pose_a, pose_b, pose_b]):
        _write_capture(path, pose)
    records = records_from_headers(paths, "sphere", sphere_radius_mm=SPHERE_RADIUS_MM)
    assert [r.pose_id for r in records] == ["p1", "p1", "p2", "p2_extra"]
    assert [r.frame_index for r in records] == [1, 0, 0, 0]       # digits, else order of appearance
    assert np.allclose(records[0].target_pose_positioner.as_matrix(), pose_a)
    assert records[0].sphere_radius_mm == SPHERE_RADIUS_MM and records[0].board_half_size_mm is None
    # Override of the pose id.
    overridden = records_from_headers(paths, "board", board_half_size_mm=BOARD_HALF_SIZE_MM,
                                      pose_id_from_name=lambda name: "all")
    assert {r.pose_id for r in overridden} == {"all"}
    assert [r.frame_index for r in overridden] == [1, 0, 2, 3]    # name digits, else order within pose "all"


def test_records_from_headers_errors(tmp_path):
    _write_capture(tmp_path / "nopose.mc", np.eye(4), with_pose=False)
    with pytest.raises(ValueError, match="record 0"):
        records_from_headers([tmp_path / "nopose.mc"], "sphere", sphere_radius_mm=SPHERE_RADIUS_MM)
    with pytest.raises(ValueError, match="record 0"):
        records_from_headers([tmp_path / "nopose.mc"], "sphere")


def test_capture_set_load_stack(tmp_path):
    pose = _pose(0.0, [0.0, 0.0, 300.0]).as_matrix()
    paths = [tmp_path / "q_Index02.mc", tmp_path / "q_Index00.mc", tmp_path / "r_Index00.mc"]
    for path in paths:
        _write_capture(path, pose)
    capture_set = CaptureSet(records_from_headers(paths, "sphere", sphere_radius_mm=SPHERE_RADIUS_MM))
    assert capture_set.pose_ids() == ["q", "r"]
    assert [r.frame_index for r in capture_set.records_for("q")] == [0, 2]
    stack = capture_set.load_stack("q")
    assert stack.xyz.shape == (2, IMAGE_HEIGHT, IMAGE_WIDTH, 3) and stack.xyz.dtype == np.float32
    assert stack.valid.shape == (2, IMAGE_HEIGHT, IMAGE_WIDTH) and stack.valid.dtype == bool
    assert not stack.valid[0, 0, 0] and stack.valid[0, 1, 1]
    assert (stack.camera.width, stack.camera.height) == (IMAGE_WIDTH, IMAGE_HEIGHT)
    assert stack.camera.focal_x_px == FOCAL_PX and stack.camera.principal_y_px == PRINCIPAL_Y
    assert stack.header["fx"] == FOCAL_PX
    assert [r.path.name for r in stack.records] == ["q_Index00.mc", "q_Index02.mc"]
    with pytest.raises(KeyError):
        capture_set.load_stack("missing")


def test_mixed_image_sizes_raise(tmp_path):
    pose = np.eye(4)
    _write_capture(tmp_path / "m_Index00.mc", pose)
    header = {"fx": FOCAL_PX, "fy": FOCAL_PX, "cx": PRINCIPAL_X, "cy": PRINCIPAL_Y, "robotPose": [float(x) for x in pose.reshape(-1)]}
    write_matcloud(tmp_path / "m_Index01.mc", header, {"XYZ": np.ones((IMAGE_HEIGHT + 1, IMAGE_WIDTH, 3), np.float32)})
    capture_set = CaptureSet(records_from_headers(
        [tmp_path / "m_Index00.mc", tmp_path / "m_Index01.mc"], "sphere", sphere_radius_mm=SPHERE_RADIUS_MM))
    with pytest.raises(ValueError, match="mixed image sizes"):
        capture_set.load_stack("m")
