"""
End-to-end test: a synthetic dataset with a known injected error field is
written, read back through the capture-set interface, fitted, and the fitted
map is compared with the injected field on held-out poses. The sensor model
used to make the data is indicative only; the fit never sees it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sphcal.calibration.correction import CorrectionFitParameters, HoldoutParameters, fit_correction
from sphcal.calibration.extrinsic import ExtrinsicParameters
from sphcal.calibration.model_config import ModelConfiguration, TermSpec
from sphcal.calibration.noread import NoReadFitParameters, fit_noread
from sphcal.calibration.samples import SampleParameters
from sphcal.features.depth_features import SlopeParameters
from sphcal.geometry.camera import PinholeCamera
from sphcal.geometry.targets import CoverageParameters
from sphcal.geometry.transforms import RigidTransform
from sphcal.io.capture_set import CaptureSet
from sphcal.io.poses import load_manifest
from sphcal.simulate.synthetic import SyntheticSensorParameters, default_injected_error_field_for_camera, \
    write_synthetic_dataset
from sphcal.spline.fit import RobustParameters, SmoothingGrid

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
"""RMS difference between the fitted map and the injected field on held-out samples."""
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
                               slope=SlopeParameters(window_px=7), effective_block_px=TEST_BLOCK_PX)
    return CorrectionFitParameters(samples=samples, extrinsic=ExtrinsicParameters(max_alternation_rounds=4),
                                   model=small_model_configuration(), robust=RobustParameters(max_iterations=3),
                                   smoothing_grid=SmoothingGrid(log10_min=-2.0, log10_max=2.0, n_values=5, n_rounds=1),
                                   holdout=HoldoutParameters(fraction=HOLDOUT_FRACTION, seed=1))


def test_fit_recovers_injected_field(synthetic_dataset: Path):
    capture_set = CaptureSet(load_manifest(synthetic_dataset / "manifest.json"))
    result = fit_correction(capture_set, fit_parameters())
    assert result.holdout_samples is not None
    assert result.holdout_residual_after_rms_mm < MAX_HOLDOUT_RMS_RATIO_AFTER_TO_BEFORE * result.holdout_residual_before_rms_mm
    dt, drot = result.sensor_to_positioner.difference_from(TEST_SENSOR_TO_POSITIONER)
    assert dt < 0.5 and drot < 0.1, (dt, drot)
    injected = default_injected_error_field_for_camera(TEST_CAMERA)
    held = result.holdout_samples
    truth = injected(held.inputs[:, 0], held.inputs[:, 1], held.inputs[:, 2], held.inputs[:, 3], held.inputs[:, 4],
                     held.inputs[:, 5])
    fitted = result.model.evaluate(held.inputs)
    recovery_rms = float(np.sqrt(np.average((fitted - truth) ** 2, weights=held.weight)))
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
