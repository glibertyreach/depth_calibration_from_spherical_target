"""
Tests of the three technician command-line tools (plan_poses, make_manifest,
check_captures), run through their main(argv) functions on a small synthetic
dataset with a known sensor-to-base transform.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from sphcal.cli import check_captures, make_manifest, plan_poses
from sphcal.geometry.camera import PinholeCamera
from sphcal.geometry.transforms import RigidTransform
from sphcal.io.poses import load_manifest
from sphcal.simulate.synthetic import SyntheticSensorParameters, default_injected_error_field_for_camera, \
    write_synthetic_dataset

TEST_CAMERA = PinholeCamera(160, 120, 172.04, 172.02, 73.08, 64.19)
TEST_BLOCK_PX = 2
TEST_SENSOR_TO_BASE = RigidTransform.from_rotation_vector_degrees([3.0, -2.0, 1.5], [120.0, -40.0, 600.0])
SPHERE_RADII_MM = (40.0, 60.0)
SPHERE_DEPTHS_MM = (450.0, 550.0, 650.0, 750.0, 500.0, 600.0, 700.0, 800.0)
SPHERE_FIELD_FRACTIONS = ((-0.4, -0.3), (0.4, -0.3), (0.4, 0.3), (-0.4, 0.3),
                          (0.0, 0.0), (-0.2, 0.15), (0.2, -0.15), (0.0, 0.3))
"""Sphere centers as fractions of the half field at their depth; inside the image with room for the silhouette."""
BOARD_HALF_SIZE_MM = (120.0, 90.0)
BOARD_DEPTHS_MM = (850.0, 950.0)
BOARD_TILTS_DEG = (10.0, 25.0)
BOARD_AZIMUTHS_DEG = (30.0, 120.0)
FRAMES_PER_POSE = 2
SHIFT_MM = 10.0
"""Deliberate error added to one commanded center."""
POSITION_TOLERANCE_MM = 1.0e-6
ROTATION_TOLERANCE = 1.0e-9
POSE_ID_FORMAT = "pose{index:04d}"
SPHERE_RESIDUAL_WARN_MM = 2.0
PLAN_FOV_DEG = (60.0, 45.0)
PLAN_IMAGE_SIZE = (640, 480)
PLAN_DEPTH_RANGE_MM = (300.0, 1100.0)
"""The default planning depth range, used to check that planned centers lie in the frustum."""
BOOTSTRAP_PAIR_COUNT = 3
BAD_BOOTSTRAP_SHIFT_MM = 20.0
"""Shift of one bootstrap pair that must trigger the residual warning."""


def make_test_poses() -> list:
    half_h, half_v = np.tan(np.radians(TEST_CAMERA.half_angles_degrees()))
    poses = []
    for index, (depth, (fx, fy)) in enumerate(zip(SPHERE_DEPTHS_MM, SPHERE_FIELD_FRACTIONS)):
        center_sensor = np.array([fx * depth * half_h, fy * depth * half_v, depth])
        radius = SPHERE_RADII_MM[index % len(SPHERE_RADII_MM)]
        poses.append(("sphere", radius, RigidTransform(np.eye(3), TEST_SENSOR_TO_BASE.apply_points(center_sensor))))
    for depth, tilt, azimuth in zip(BOARD_DEPTHS_MM, BOARD_TILTS_DEG, BOARD_AZIMUTHS_DEG):
        axis = np.array([np.cos(np.radians(azimuth)), np.sin(np.radians(azimuth)), 0.0])
        facing = RigidTransform.from_rotation_vector_degrees([180.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        tilted = RigidTransform.from_rotation_vector_degrees(axis * tilt, [0.0, 0.0, 0.0]).compose(facing)
        pose_sensor = RigidTransform(tilted.rotation, np.array([0.0, 0.0, depth]))
        poses.append(("board", BOARD_HALF_SIZE_MM, TEST_SENSOR_TO_BASE.compose(pose_sensor)))
    return poses


@pytest.fixture(scope="module")
def dataset(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("cli_dataset")
    base = SyntheticSensorParameters.vsx3000_indicative()
    params = SyntheticSensorParameters(**{**base.__dict__, "camera": TEST_CAMERA, "effective_block_px": TEST_BLOCK_PX})
    write_synthetic_dataset(out, params, make_test_poses(), TEST_SENSOR_TO_BASE, FRAMES_PER_POSE,
                            default_injected_error_field_for_camera(TEST_CAMERA), np.random.default_rng(5))
    return out


# ---------------------------------------------------------------------------
# plan_poses
# ---------------------------------------------------------------------------
def read_csv_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return list(reader.fieldnames), rows


def bootstrap_document(dataset: Path, shift_last_mm: float = 0.0) -> dict:
    """Bootstrap pairs: commanded centers of the first sphere poses with their true sensor-frame centers."""
    truth = json.loads((dataset / "truth.json").read_text())
    entries = []
    for pose in truth["poses"][:BOOTSTRAP_PAIR_COUNT]:
        base_xyz = np.array(pose["target_pose_positioner"])[:3, 3]
        sensor_xyz = TEST_SENSOR_TO_BASE.inverse().apply_points(base_xyz)
        entries.append({"pose_id": pose["pose_id"], "base_xyz": base_xyz.tolist(), "sensor_xyz": sensor_xyz.tolist()})
    entries[-1]["base_xyz"][0] += shift_last_mm
    return {"bootstrap": entries}


def test_plan_poses_bootstrap_inside_frustum(dataset: Path, tmp_path: Path, capsys):
    sensor_file = tmp_path / "sensor_in_base.json"
    sensor_file.write_text(json.dumps(bootstrap_document(dataset)))
    out = tmp_path / "plan"
    camera_file = sorted(dataset.glob("*.mc"))[0]
    assert plan_poses.main(["--sensor-in-base", str(sensor_file), "--camera", str(camera_file), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Bootstrap residuals" in printed and "WARNING" not in printed
    for name in (plan_poses.PLAN_CSV_NAME, plan_poses.PLAN_SUMMARY_NAME, plan_poses.PLAN_FIGURE_NAME):
        assert (out / name).stat().st_size > 0
    columns, rows = read_csv_rows(out / plan_poses.PLAN_CSV_NAME)
    assert columns == list(plan_poses.POSE_CSV_COLUMNS)
    assert columns[:9] == ["pose_id", "kind", "radius_mm", "half_width_mm", "half_height_mm", "holdout",
                           "base_x_mm", "base_y_mm", "base_z_mm"]
    kinds = {row["kind"] for row in rows}
    assert kinds == {"sphere", "board"}
    assert len({row["pose_id"] for row in rows}) == len(rows)
    base_to_sensor = TEST_SENSOR_TO_BASE.inverse()
    for row in rows:
        base = np.array([float(row[f"base_{axis}_mm"]) for axis in "xyz"])
        sensor = base_to_sensor.apply_points(base)
        reference = np.array([float(row[f"sensor_{axis}_mm"]) for axis in "xyz"])
        assert np.allclose(sensor, reference, atol=1.0e-6)          # the solved transform is the true one
        assert PLAN_DEPTH_RANGE_MM[0] - 1.0e-6 <= sensor[2] <= 1.05 * PLAN_DEPTH_RANGE_MM[1]
        u, v, in_front = TEST_CAMERA.project(sensor)
        assert in_front and 0.0 <= u <= TEST_CAMERA.width - 1 and 0.0 <= v <= TEST_CAMERA.height - 1, row["pose_id"]
        rotation = np.array([float(row[f"r{i}{j}"]) for i in range(3) for j in range(3)]).reshape(3, 3)
        assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1.0e-9) and np.linalg.det(rotation) > 0.0
        quaternion = np.array([float(row[f"quat_{c}"]) for c in "wxyz"])
        assert quaternion[0] >= 0.0 and np.isclose(np.linalg.norm(quaternion), 1.0)
        assert np.allclose(Rotation.from_quat(np.roll(quaternion, -1)).as_matrix(), rotation, atol=1.0e-9)
        rotvec = np.radians([float(row[f"rotvec_{c}_deg"]) for c in "xyz"])
        assert np.allclose(Rotation.from_rotvec(rotvec).as_matrix(), rotation, atol=1.0e-9)
        ray = sensor / np.linalg.norm(sensor)
        z_axis_sensor = base_to_sensor.rotation @ rotation[:, 2]
        if row["kind"] == "sphere":
            assert np.allclose(z_axis_sensor, ray, atol=1.0e-9)             # stem along the viewing ray, away from the sensor
            assert float(row["radius_mm"]) > 0.0 and row["half_width_mm"] == ""
        else:
            assert z_axis_sensor @ ray < 0.0                                # board normal faces the sensor
            assert float(row["half_width_mm"]) > 0.0 and row["radius_mm"] == ""
    holdout_count = sum(int(row["holdout"]) for row in rows)
    assert holdout_count == round(plan_poses.PlanParameters().holdout_fraction * len(rows))
    summary = (out / plan_poses.PLAN_SUMMARY_NAME).read_text()
    assert f"Total: {len(rows)} poses" in summary


def test_plan_poses_warns_on_inconsistent_bootstrap(dataset: Path, tmp_path: Path, capsys):
    sensor_file = tmp_path / "sensor_in_base.json"
    sensor_file.write_text(json.dumps(bootstrap_document(dataset, shift_last_mm=BAD_BOOTSTRAP_SHIFT_MM)))
    code = plan_poses.main(["--sensor-in-base", str(sensor_file), "--fov-deg", *map(str, PLAN_FOV_DEG),
                            "--image-size", *map(str, PLAN_IMAGE_SIZE), "--out", str(tmp_path / "plan")])
    assert code == 0
    assert "WARNING: the worst bootstrap residual" in capsys.readouterr().out


def test_plan_poses_matrix_input_and_errors(dataset: Path, tmp_path: Path, capsys):
    sensor_file = tmp_path / "matrix.json"
    sensor_file.write_text(json.dumps({"matrix": TEST_SENSOR_TO_BASE.as_matrix().reshape(-1).tolist()}))
    out = tmp_path / "plan"
    assert plan_poses.main(["--sensor-in-base", str(sensor_file), "--fov-deg", *map(str, PLAN_FOV_DEG),
                            "--image-size", *map(str, PLAN_IMAGE_SIZE), "--out", str(out)]) == 0
    _, rows = read_csv_rows(out / plan_poses.PLAN_CSV_NAME)
    first = next(row for row in rows if row["kind"] == "sphere")
    assert first["pose_id"] == "s076_z0300_000"          # the one sphere (76.2 mm) at the first ladder station
    # No camera given: the message says what to supply.
    assert plan_poses.main(["--sensor-in-base", str(sensor_file), "--out", str(out)]) == plan_poses.EXIT_INPUT_ERROR
    assert "--camera" in capsys.readouterr().err
    # Collinear bootstrap points: the message says what to change.
    line = {"bootstrap": [{"pose_id": str(i), "base_xyz": [i * 100.0, 0.0, 0.0], "sensor_xyz": [0.0, 0.0, 300.0 + i]}
                          for i in range(4)]}
    sensor_file.write_text(json.dumps(line))
    assert plan_poses.main(["--sensor-in-base", str(sensor_file), "--fov-deg", *map(str, PLAN_FOV_DEG),
                            "--image-size", *map(str, PLAN_IMAGE_SIZE), "--out", str(out)]) == plan_poses.EXIT_INPUT_ERROR
    assert "lie on a line" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# make_manifest
# ---------------------------------------------------------------------------
def rotation_values(rotation_type: str, rotation: np.ndarray) -> list[float]:
    """The r values a robot would log for a rotation under each convention (inverse of make_manifest)."""
    r = Rotation.from_matrix(rotation)
    xyzw = r.as_quat()
    return {
        make_manifest.ROTATION_QUATERNION_WXYZ: list(np.roll(xyzw, 1)),
        make_manifest.ROTATION_QUATERNION_XYZW: list(xyzw),
        make_manifest.ROTATION_EULER_ZYX: list(r.as_euler("ZYX", degrees=True)),
        make_manifest.ROTATION_EULER_XYZ: list(r.as_euler("XYZ", degrees=True)),
        make_manifest.ROTATION_FIXED_XYZ: list(r.as_euler("xyz", degrees=True)),
        make_manifest.ROTATION_ROTVEC: list(np.degrees(r.as_rotvec())),
        make_manifest.ROTATION_MATRIX: list(rotation.reshape(-1)),
    }[rotation_type]


def write_pose_log(path: Path, dataset: Path, rotation_type: str, sphere_rotation_type: str = "none",
                   scale: float = 1.0) -> None:
    truth = json.loads((dataset / "truth.json").read_text())
    columns = ["pose_id", "kind", "radius_mm", "half_width_mm", "half_height_mm", "x_mm", "y_mm", "z_mm",
               "rotation_type"] + [f"r{i}" for i in range(1, 10)]
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for pose in truth["poses"]:
            matrix = np.array(pose["target_pose_positioner"])
            is_sphere = pose["kind"] == "sphere"
            kind_rotation = sphere_rotation_type if is_sphere else rotation_type
            values = [] if kind_rotation == "none" else [v * scale for v in rotation_values(kind_rotation, matrix[:3, :3])]
            writer.writerow([pose["pose_id"], pose["kind"], pose.get("radius_mm", ""), pose.get("half_width_mm", ""),
                             pose.get("half_height_mm", ""), *matrix[:3, 3], kind_rotation, *values,
                             *[""] * (9 - len(values))])


def assert_records_equal(actual, expected) -> None:
    key = lambda record: (record.pose_id, record.frame_index)
    actual, expected = sorted(actual, key=key), sorted(expected, key=key)
    assert [key(r) for r in actual] == [key(r) for r in expected]
    for a, e in zip(actual, expected):
        assert a.target_kind == e.target_kind
        assert Path(a.path).resolve() == Path(e.path).resolve()
        assert a.sphere_radius_mm == e.sphere_radius_mm and a.board_half_size_mm == e.board_half_size_mm
        assert np.allclose(a.target_pose_positioner.translation, e.target_pose_positioner.translation,
                           atol=POSITION_TOLERANCE_MM)
        if a.target_kind == "board":
            assert np.allclose(a.target_pose_positioner.rotation, e.target_pose_positioner.rotation,
                               atol=ROTATION_TOLERANCE)


@pytest.mark.parametrize("rotation_type", list(make_manifest.ROTATION_VALUE_COUNTS)[1:])
@pytest.mark.parametrize("manifest_format", ["csv", "json"])
def test_make_manifest_reproduces_synthetic_manifest(dataset: Path, tmp_path: Path, rotation_type: str,
                                                     manifest_format: str):
    log = tmp_path / "pose_log.csv"
    write_pose_log(log, dataset, rotation_type)
    out = tmp_path / f"manifest.{manifest_format}"
    assert make_manifest.main(["--pose-log", str(log), "--captures", str(dataset), "--format", manifest_format,
                               "--out", str(out)]) == 0
    assert_records_equal(load_manifest(out), load_manifest(dataset / "manifest.json"))


def test_make_manifest_accepts_plan_poses_csv(dataset: Path, tmp_path: Path):
    """A poses.csv from plan_poses is read directly; files are named after its pose ids."""
    sensor_file = tmp_path / "matrix.json"
    sensor_file.write_text(json.dumps({"matrix": TEST_SENSOR_TO_BASE.as_matrix().reshape(-1).tolist()}))
    plan_dir = tmp_path / "plan"
    assert plan_poses.main(["--sensor-in-base", str(sensor_file), "--camera", str(sorted(dataset.glob("*.mc"))[0]),
                            "--sphere-depths-mm", "600", "900", "--board-depths-mm", "900",
                            "--board-tilts-deg", "0", "--out", str(plan_dir)]) == 0
    _, rows = read_csv_rows(plan_dir / plan_poses.PLAN_CSV_NAME)
    captures = tmp_path / "captures"
    captures.mkdir()
    for row in rows[:3] + rows[-1:]:
        (captures / f"{row['pose_id']}_Index00.mc").write_bytes(b"")     # content is not read by make_manifest
    out = tmp_path / "manifest.csv"
    assert make_manifest.main(["--pose-log", str(plan_dir / plan_poses.PLAN_CSV_NAME), "--captures", str(captures),
                               "--out", str(out)]) == 0                  # warnings about missing captures only
    records = load_manifest(out)
    assert {r.pose_id for r in records} == {row["pose_id"] for row in rows[:3] + rows[-1:]}
    for record in records:
        row = next(r for r in rows if r["pose_id"] == record.pose_id)
        assert np.allclose(record.target_pose_positioner.translation, [float(row[f"base_{a}_mm"]) for a in "xyz"])
        assert np.isclose(np.linalg.det(record.target_pose_positioner.rotation), 1.0)


def test_make_manifest_messages(dataset: Path, tmp_path: Path, capsys):
    log = tmp_path / "pose_log.csv"
    write_pose_log(log, dataset, make_manifest.ROTATION_QUATERNION_WXYZ)
    out = tmp_path / "manifest.csv"
    # Non-unit quaternions are normalized and reported; the result is unchanged.
    write_pose_log(log, dataset, make_manifest.ROTATION_QUATERNION_WXYZ, scale=2.0)
    assert make_manifest.main(["--pose-log", str(log), "--captures", str(dataset), "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert "not 1; it was normalized" in captured.err
    assert "10 poses (8 sphere, 2 board)" in captured.out
    assert f"frames per pose min {FRAMES_PER_POSE} / max {FRAMES_PER_POSE}" in captured.out
    assert_records_equal(load_manifest(out), load_manifest(dataset / "manifest.json"))
    # --strict turns warnings into a failure.
    assert make_manifest.main(["--pose-log", str(log), "--captures", str(dataset), "--out", str(out),
                               "--strict"]) == make_manifest.EXIT_INPUT_ERROR
    capsys.readouterr()
    # A logged pose without captures and captures without a log row are named.
    other = tmp_path / "captures"
    other.mkdir()
    for path in sorted(dataset.glob("pose000[0-3]_*.mc")):
        (other / path.name).write_bytes(b"")
    (other / "stray_Index00.mc").write_bytes(b"")
    write_pose_log(log, dataset, make_manifest.ROTATION_QUATERNION_WXYZ)
    assert make_manifest.main(["--pose-log", str(log), "--captures", str(other), "--out", str(out)]) == 0
    err = capsys.readouterr().err
    assert "pose 'pose0004' is in the pose log but no capture file" in err
    assert "capture files for pose id 'stray'" in err
    # Missing radius, board without size, board with rotation_type none: all listed, nothing written.
    with log.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["pose_id", "kind", "radius_mm", "half_width_mm", "half_height_mm", "x_mm", "y_mm", "z_mm",
                         "rotation_type", "r1", "r2", "r3", "r4"])
        writer.writerow(["pose0000", "sphere", "", "", "", 0, 0, 500, "none", "", "", "", ""])
        writer.writerow(["pose0001", "board", "", "", "", 0, 0, 500, "quaternion_wxyz", 1, 0, 0, 0])
        writer.writerow(["pose0002", "board", "", 120, 90, 0, 0, 500, "none", "", "", "", ""])
    out.unlink()
    assert make_manifest.main(["--pose-log", str(log), "--captures", str(dataset), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "a sphere needs a positive radius_mm" in err
    assert "a board needs positive half_width_mm" in err
    assert "rotation_type none is not allowed" in err
    assert not out.exists()


# ---------------------------------------------------------------------------
# check_captures
# ---------------------------------------------------------------------------
def test_check_captures_clean_and_shifted(dataset: Path, tmp_path: Path, capsys):
    report_path = tmp_path / "report.json"
    assert check_captures.main(["--manifest", str(dataset / "manifest.json"), "--out", str(report_path),
                                "--sphere-residual-warn-mm", str(SPHERE_RESIDUAL_WARN_MM)]) == 0
    printed = capsys.readouterr().out
    assert "VERDICT: all 10 poses passed" in printed
    report = json.loads(report_path.read_text())
    spheres = [p for p in report["poses"] if p["kind"] == "sphere"]
    boards = [p for p in report["poses"] if p["kind"] == "board"]
    assert len(spheres) == len(SPHERE_DEPTHS_MM) and len(boards) == len(BOARD_DEPTHS_MM)
    assert all(p["fit_rms_mm"] < SPHERE_RESIDUAL_WARN_MM and p["center_residual_mm"] < SPHERE_RESIDUAL_WARN_MM
               for p in spheres)
    assert all(p["normal_error_deg"] < check_captures.CheckParameters().board_normal_warn_deg for p in boards)
    assert report["n_flagged"] == 0 and report["sensor_to_base_rough"] is not None

    # Shift one commanded center in the manifest by 10 mm: that pose is flagged, the exit code is 1.
    document = json.loads((dataset / "manifest.json").read_text())
    shifted_id = "pose0002"
    for record in document["records"]:
        if record["pose_id"] == shifted_id:
            record["pose"]["matrix"][3] += SHIFT_MM
    shifted_manifest = dataset / "manifest_shifted.json"
    shifted_manifest.write_text(json.dumps(document))
    assert check_captures.main(["--manifest", str(shifted_manifest), "--out", str(report_path)]) == 1
    printed = capsys.readouterr().out
    assert "VERDICT: 1 of 10 poses flagged" in printed
    assert "re-capture the flagged poses or check the tool center point / tool frame" in printed
    report = json.loads(report_path.read_text())
    flagged = [p for p in report["poses"] if p["flags"]]
    assert [p["pose_id"] for p in flagged] == [shifted_id]
    assert flagged[0]["center_residual_mm"] > 0.5 * SHIFT_MM


def test_check_captures_flags_board_normal_and_unreadable_manifest(dataset: Path, tmp_path: Path, capsys):
    document = json.loads((dataset / "manifest.json").read_text())
    for record in document["records"]:
        if record["pose_id"] == "pose0008":          # tip the commanded board by 20 degrees about the base x axis
            matrix = np.array(record["pose"]["matrix"]).reshape(4, 4)
            matrix[:3, :3] = Rotation.from_euler("x", 20.0, degrees=True).as_matrix() @ matrix[:3, :3]
            record["pose"]["matrix"] = matrix.reshape(-1).tolist()
    manifest = dataset / "manifest_tilted.json"
    manifest.write_text(json.dumps(document))
    assert check_captures.main(["--manifest", str(manifest)]) == 1
    assert "fitted board normal disagrees" in capsys.readouterr().out
    assert check_captures.main(["--manifest", str(tmp_path / "missing.csv")]) == check_captures.EXIT_INPUT_ERROR
    assert "cannot read the manifest" in capsys.readouterr().err
