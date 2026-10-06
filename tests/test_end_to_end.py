"""
End-to-end test: a synthetic dataset with a known injected error field is
written, read back through the capture-set interface, fitted, and the fitted
map is compared with the injected field on held-out poses. The sensor model
used to make the data is indicative only; the fit never sees it.
"""
from __future__ import annotations

from pathlib import Path

import json

import numpy as np
import pytest

from sphcal.calibration.correction import CorrectionFitParameters, HoldoutParameters, SmoothingSelection, fit_correction
from sphcal.calibration.extrinsic import ExtrinsicParameters, rigid_component_of_displacements
from sphcal.calibration.model_config import ModelConfiguration, TermSpec
from sphcal.calibration.noread import NoReadFitParameters, fit_noread
from sphcal.calibration.samples import SampleParameters
from sphcal.features.depth_features import SlopeParameters
from sphcal.geometry.camera import PinholeCamera
from sphcal.geometry.targets import CoverageParameters
from sphcal.geometry.transforms import RigidTransform
from sphcal.io.capture_set import CaptureSet
from sphcal.io.poses import load_manifest
from sphcal.cli import fit as fit_cli
from sphcal.simulate.synthetic import SyntheticSensorParameters, default_injected_error_field_for_camera, \
    write_synthetic_dataset
from sphcal.spline.fit import RobustParameters, SmoothingGrid
from sphcal.validation.report import ReportParameters, shape_checks

# A small camera keeps the test fast: the indicative 640 x 480 geometry scaled by 1/4.
TEST_SCALE = 0.25
TEST_CAMERA = PinholeCamera(160, 120, 688.1552734375 * TEST_SCALE, 688.083251953125 * TEST_SCALE,
                            292.3155517578125 * TEST_SCALE, 256.7590026855469 * TEST_SCALE)
TEST_BLOCK_PX = 2
"""Effective block in the scaled image (4 native pixels at full scale)."""
TEST_SENSOR_TO_POSITIONER = RigidTransform.from_rotation_vector_degrees([3.0, -2.0, 1.5], [120.0, -40.0, 600.0])
N_SPHERE_POSES = 36
N_BOARD_POSES = 10
FRAMES_PER_POSE = 3
DEPTH_RANGE_MM = (350.0, 900.0)
SPHERE_RADII_MM = (40.0, 80.0)
BOARD_HALF_SIZE_MM = (120.0, 90.0)
HOLDOUT_FRACTION = 0.25
MAX_HOLDOUT_RMS_RATIO_AFTER_TO_BEFORE = 0.5
"""The fit must remove at least half of the held-out residual RMS."""
MAX_FIELD_RECOVERY_RMS_MM = 0.08
"""RMS distance, in the positioner frame, between corrected held-out points and
the true surface points, which is invariant to the gauge choice."""
MAX_TRANSFORM_TRANSLATION_SLACK_MM = 3.0
MAX_TRANSFORM_ROTATION_SLACK_DEG = 0.3
"""Loose sanity bounds on the raw transform; the gauge can move it by about the
mean of the injected field (section 3, A1 of the analysis)."""
NOREAD_ONSET_TOLERANCE_DEG = 6.0


def make_poses(rng: np.random.Generator):
    half_h, half_v = TEST_CAMERA.half_angles_degrees()
    poses = []
    for index in range(N_SPHERE_POSES + N_BOARD_POSES):
        z = rng.uniform(*DEPTH_RANGE_MM)
        x = rng.uniform(-0.7, 0.7) * z * np.tan(np.radians(half_h))
        y = rng.uniform(-0.7, 0.7) * z * np.tan(np.radians(half_v))
        center_sensor = np.array([x, y, z])
        if index < N_SPHERE_POSES:
            radius = SPHERE_RADII_MM[index % 2]
            center_positioner = TEST_SENSOR_TO_POSITIONER.apply_points(center_sensor)
            poses.append(("sphere", radius, RigidTransform(np.eye(3), center_positioner)))
        else:
            tilt = rng.uniform(0.0, 40.0)
            azimuth = rng.uniform(0.0, 360.0)
            axis = np.array([np.cos(np.radians(azimuth)), np.sin(np.radians(azimuth)), 0.0])
            facing = RigidTransform.from_rotation_vector_degrees([180.0, 0.0, 0.0], [0.0, 0.0, 0.0])
            tilted = RigidTransform.from_rotation_vector_degrees(axis * tilt, [0.0, 0.0, 0.0]).compose(facing)
            pose_sensor = RigidTransform(tilted.rotation, center_sensor)
            poses.append(("board", BOARD_HALF_SIZE_MM, TEST_SENSOR_TO_POSITIONER.compose(pose_sensor)))
    return poses


@pytest.fixture(scope="module")
def synthetic_dataset(tmp_path_factory) -> Path:
    rng = np.random.default_rng(2026)
    base = SyntheticSensorParameters.vsx3000_indicative()
    params = SyntheticSensorParameters(**{**base.__dict__, "camera": TEST_CAMERA, "effective_block_px": TEST_BLOCK_PX})
    out = tmp_path_factory.mktemp("synthetic")
    write_synthetic_dataset(out, params, make_poses(rng), TEST_SENSOR_TO_POSITIONER, FRAMES_PER_POSE,
                            default_injected_error_field_for_camera(TEST_CAMERA), rng)
    return out


def small_model_configuration() -> ModelConfiguration:
    return ModelConfiguration((TermSpec("position", (0, 1, 2), (4, 3, 4)),
                               TermSpec("slope", (3, 4, 2), (4, 4, 2)),
                               TermSpec("curvature", (5, 3, 4), (1, 2, 2), degree=1)))


def fit_parameters() -> CorrectionFitParameters:
    samples = SampleParameters(coverage=CoverageParameters(incidence_cutoff_deg=55.0, silhouette_margin_px=3.0,
                                                           board_edge_margin_mm=8.0),
                               slope=SlopeParameters(window_px=7), effective_block_px=TEST_BLOCK_PX,
                               pixel_stride=TEST_BLOCK_PX, noread_pixel_stride=TEST_BLOCK_PX)
    return CorrectionFitParameters(samples=samples, extrinsic=ExtrinsicParameters(max_alternation_rounds=6),
                                   model=small_model_configuration(), robust=RobustParameters(max_iterations=3),
                                   smoothing=SmoothingSelection(method="pose_cv", folds=2,
                                                                grid=SmoothingGrid(log10_min=-2.0, log10_max=4.0, n_values=4, n_rounds=1)),
                                   holdout=HoldoutParameters(fraction=HOLDOUT_FRACTION, seed=1))


def test_fit_recovers_injected_field(synthetic_dataset: Path):
    capture_set = CaptureSet(load_manifest(synthetic_dataset / "manifest.json"))
    result = fit_correction(capture_set, fit_parameters())
    assert result.holdout_samples is not None
    assert result.holdout_residual_after_rms_mm < MAX_HOLDOUT_RMS_RATIO_AFTER_TO_BEFORE * result.holdout_residual_before_rms_mm
    # Gauge: a near-constant range offset in the injected field is close to a
    # translation along the optical axis, and the sensor-frame gauge lets the
    # transform absorb it. The raw transform is therefore only loosely checked;
    # the real test is gauge-invariant: corrected held-out points carried into
    # the positioner frame by the FITTED transform must land where the TRUE
    # transform carries the TRUE surface points.
    dt, drot = result.sensor_to_positioner.difference_from(TEST_SENSOR_TO_POSITIONER)
    assert dt < MAX_TRANSFORM_TRANSLATION_SLACK_MM and drot < MAX_TRANSFORM_ROTATION_SLACK_DEG, (dt, drot)
    injected = default_injected_error_field_for_camera(TEST_CAMERA)
    held = result.holdout_samples
    error_mm = injected(held.inputs[:, 0], held.inputs[:, 1], held.inputs[:, 2], held.inputs[:, 3], held.inputs[:, 4],
                        held.inputs[:, 5])
    true_points = held.ray_direction * (held.inputs[:, 2] - error_mm)[:, None]
    corrected_points = held.ray_direction * (held.inputs[:, 2] + result.model.evaluate(held.inputs))[:, None]
    # Carry both into the TRUE sensor frame and remove the best rigid motion
    # between them, which is the part the data cannot determine (gauge); what
    # remains is the non-rigid field error, judged on the board samples because
    # the synthetic sensor's block averaging adds a curvature bias on spheres
    # that is not part of the injected field (analysis section 4b) and that the
    # map absorbs through its curvature term. Sphere surfaces are covered by the
    # held-out residual criterion above.
    relative = TEST_SENSOR_TO_POSITIONER.inverse().compose(result.sensor_to_positioner)
    mismatch = relative.apply_points(corrected_points) - true_points
    on_board = np.array([held.pose_kinds[i] == "board" for i in held.pose_index])
    assert on_board.any()
    t_rigid, omega_rigid = rigid_component_of_displacements(true_points[on_board], mismatch[on_board], held.weight[on_board])
    non_rigid = mismatch[on_board] - (t_rigid + np.cross(omega_rigid, true_points[on_board]))
    # The map corrects range along the ray, so its field error is the along-ray component.
    along_ray = np.sum(non_rigid * held.ray_direction[on_board], axis=1)
    recovery_rms = float(np.sqrt(np.average(along_ray ** 2, weights=held.weight[on_board])))
    assert recovery_rms < MAX_FIELD_RECOVERY_RMS_MM, recovery_rms


def test_noread_onset_recovered(synthetic_dataset: Path):
    capture_set = CaptureSet(load_manifest(synthetic_dataset / "manifest.json"))
    params = fit_parameters()
    noread_params = NoReadFitParameters(samples=params.samples,
                                        model=ModelConfiguration((TermSpec("slope", (3, 4, 2), (6, 6, 2)),), slope_bound=4.0))
    result = fit_noread(capture_set, TEST_SENSOR_TO_POSITIONER, noread_params)
    onsets = [v for v in result.onset_by_azimuth_deg.values() if v is not None]
    assert onsets, result.onset_by_azimuth_deg
    assert all(abs(o - 55.0) < NOREAD_ONSET_TOLERANCE_DEG for o in onsets), result.onset_by_azimuth_deg


@pytest.fixture(scope="module")
def fitted(synthetic_dataset: Path):
    """The capture set and its fit, shared by the tests of held-out report content."""
    capture_set = CaptureSet(load_manifest(synthetic_dataset / "manifest.json"))
    return capture_set, fit_correction(capture_set, fit_parameters())


def test_shape_checks_improve_on_held_out_poses(fitted):
    """Robot-independent checks: flatness of held-out boards and free-radius spheres must improve after correction."""
    capture_set, result = fitted
    rows = shape_checks(capture_set, result.holdout_poses, result.model, result.sensor_to_positioner,
                        fit_parameters().samples, ReportParameters())
    boards = [r for r in rows if r["kind"] == "board"]
    spheres = [r for r in rows if r["kind"] == "sphere"]
    assert boards and spheres, rows
    flatness_before = float(np.mean([r["flatness_rms_before_mm"] for r in boards]))
    flatness_after = float(np.mean([r["flatness_rms_after_mm"] for r in boards]))
    radius_error_before = float(np.mean([abs(r["radius_error_before_mm"]) for r in spheres]))
    radius_error_after = float(np.mean([abs(r["radius_error_after_mm"]) for r in spheres]))
    print(f"held-out boards ({len(boards)}): mean flatness RMS before {flatness_before:.4f} mm, after {flatness_after:.4f} mm")
    print(f"held-out spheres ({len(spheres)}): mean |radius error| before {radius_error_before:.4f} mm, "
          f"after {radius_error_after:.4f} mm")
    assert flatness_after < flatness_before
    assert radius_error_after < radius_error_before


def test_fit_cli_report_contains_shape_checks(fitted, synthetic_dataset: Path, tmp_path: Path, monkeypatch):
    """The command line writes the shape checks next to the sphere-center errors."""
    capture_set, result = fitted
    monkeypatch.setattr(fit_cli, "fit_correction", lambda *args, **kwargs: result)
    monkeypatch.setattr(fit_cli, "CorrectionFitParameters", lambda **kwargs: fit_parameters())
    fit_cli.main(["--manifest", str(synthetic_dataset / "manifest.json"), "--out", str(tmp_path), "--skip-noread"])
    report = json.loads((tmp_path / "report.json").read_text())
    assert "holdout_sphere_centers" in report
    assert {row["kind"] for row in report["holdout_shape_checks"]} == {"sphere", "board"}
