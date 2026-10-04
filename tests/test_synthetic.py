"""Tests for sphcal.simulate.synthetic."""
import dataclasses
import json

import numpy as np

from sphcal.geometry.camera import PinholeCamera
from sphcal.geometry.transforms import RigidTransform
from sphcal.io.capture_set import CaptureSet
from sphcal.io.matcloud import read_matcloud
from sphcal.io.poses import load_manifest
from sphcal.simulate.synthetic import (
    SyntheticSensorParameters, default_injected_error_field, default_injected_error_field_for_camera,
    render_board_frame, render_sphere_frame, write_synthetic_dataset,
)

SCALE = 80.0 / 640.0                      # small test image: proportionally scaled indicative intrinsics
TEST_WIDTH_PX = 80
TEST_HEIGHT_PX = 60
INDICATIVE = SyntheticSensorParameters.vsx3000_indicative()
TEST_CAMERA = PinholeCamera(
    TEST_WIDTH_PX, TEST_HEIGHT_PX,
    INDICATIVE.camera.focal_x_px * SCALE, INDICATIVE.camera.focal_y_px * SCALE,
    TEST_WIDTH_PX / 2.0, TEST_HEIGHT_PX / 2.0)          # principal point on a pixel center
CENTER_ROW = TEST_HEIGHT_PX // 2
CENTER_COL = TEST_WIDTH_PX // 2
PARAMS = dataclasses.replace(INDICATIVE, camera=TEST_CAMERA)
SPHERE_RADIUS_MM = 100.0
SPHERE_DISTANCE_MM = 600.0
SPHERE_CENTER = np.array([0.0, 0.0, SPHERE_DISTANCE_MM])
RANGE_TOLERANCE_MM = 1e-6
FLOAT32_ROUNDING_FACTOR = 1.0             # float32 rounding error is at most half a spacing; the factor allows for the ray product
NO_READ_DISABLED_ONSET_DEG = 1.0e4        # read probability 1 at every incidence
SEED = 1234
N_REPEAT_FRAMES = 20
ALPHA_BIN_LOW_DEG = 30.0
ALPHA_BIN_HIGH_DEG = 70.0
SLOPE_FD_TOLERANCE = 1e-2                 # finite differences vs. the definition (differs off-axis by 1/d_z, under 1 percent here)
PLANE_SLOPE = 0.4                         # m in the plane z = z0 + m x


FLIP_TOWARD_SENSOR_DEG = [180.0, 0.0, 0.0]   # a board's outward normal +z must point toward the camera (-z)


def facing_board_rotation(tilt_deg) -> np.ndarray:
    """Board->sensor rotation of a board facing the sensor, then tilted by tilt_deg (rotation vector)."""
    tilt = RigidTransform.from_rotation_vector_degrees(tilt_deg, [0.0, 0.0, 0.0]).rotation
    flip = RigidTransform.from_rotation_vector_degrees(FLIP_TOWARD_SENSOR_DEG, [0.0, 0.0, 0.0]).rotation
    return tilt @ flip


def zero_field(u, v, rho, s_u, s_v, curvature):
    """Zero error field."""
    return np.zeros_like(rho)


def test_default_vsx3000_indicative_values():
    p = SyntheticSensorParameters.vsx3000_indicative()
    assert (p.camera.width, p.camera.height) == (640, 480)
    assert p.camera.focal_x_px == 688.1552734375 and p.camera.principal_y_px == 256.7590026855469
    assert p.effective_block_px == 4 and p.noise_coefficient_per_mm == 1.79e-7
    assert p.noise_incidence_exponent == 1.3 and p.noread_onset_deg == 55.0 and p.noread_width_deg == 5.0
    assert p.fixed_pattern_amplitude_mm == 0.0 and p.fixed_pattern_seed == 0


def test_default_error_field_values():
    # Bowl is zero at the center pixel; curvature term is 0.4 mm at R = 50 mm.
    cx, cy = 292.3155517578125, 256.7590026855469
    assert abs(default_injected_error_field(cx, cy, 1000.0, 0.0, 0.0, 1.0 / 50.0) - 0.4) < 1e-12
    # Slope terms: 0.3 * (0.25 + 0.04) + 0.15 * 0.5
    expected = 0.3 * (0.5 ** 2 + 0.2 ** 2) + 0.15 * 0.5
    assert abs(default_injected_error_field(cx, cy, 1000.0, 0.5, 0.2, 0.0) - expected) < 1e-12
    # Bowl at u = 0, v = cy and rho = rho_ref equals A.
    assert abs(default_injected_error_field(0.0, cy, 1000.0, 0.0, 0.0, 0.0) - 0.6) < 1e-12


def test_sphere_frame_silhouette_and_center_ray():
    params = dataclasses.replace(PARAMS, noread_onset_deg=NO_READ_DISABLED_ONSET_DEG)
    frame = render_sphere_frame(params, SPHERE_CENTER, SPHERE_RADIUS_MM, zero_field, np.random.default_rng(SEED))
    assert frame.xyz.shape == (TEST_HEIGHT_PX, TEST_WIDTH_PX, 3) and frame.xyz.dtype == np.float32
    # Zeros (all three components) outside the silhouette; nonzero inside.
    assert np.all(frame.xyz[~frame.hit_mask] == 0.0)
    assert np.all(frame.xyz[frame.read_mask][:, 2] > 0.0)
    # Silhouette matches the analytic cone: half angle asin(R / |c|).
    rays = TEST_CAMERA.ray_directions()
    inside = np.degrees(np.arccos(rays @ (SPHERE_CENTER / SPHERE_DISTANCE_MM))) < np.degrees(
        np.arcsin(SPHERE_RADIUS_MM / SPHERE_DISTANCE_MM))
    assert np.array_equal(inside, frame.hit_mask)
    # Center ray: range = |center| - R, cos incidence = 1.
    assert abs(frame.true_range[CENTER_ROW, CENTER_COL] - (SPHERE_DISTANCE_MM - SPHERE_RADIUS_MM)) < RANGE_TOLERANCE_MM
    assert abs(frame.true_cos_incidence[CENTER_ROW, CENTER_COL] - 1.0) < RANGE_TOLERANCE_MM
    assert abs(frame.true_s_u[CENTER_ROW, CENTER_COL]) < RANGE_TOLERANCE_MM
    assert np.all(np.isnan(frame.true_range[~frame.hit_mask]))


def test_zero_noise_zero_error_block_one_recovers_true_depth():
    params = dataclasses.replace(PARAMS, effective_block_px=1, noise_coefficient_per_mm=0.0,
                                 noread_onset_deg=NO_READ_DISABLED_ONSET_DEG)
    rng = np.random.default_rng(SEED)
    rays = TEST_CAMERA.ray_directions()
    for frame in (render_sphere_frame(params, SPHERE_CENTER, SPHERE_RADIUS_MM, zero_field, rng),
                  render_board_frame(params, RigidTransform(
                      facing_board_rotation([20.0, -10.0, 0.0]), [0.0, 0.0, SPHERE_DISTANCE_MM]),
                      (150.0, 100.0), zero_field, rng)):
        assert frame.hit_mask.sum() > 0 and np.array_equal(frame.read_mask, frame.hit_mask)
        true_depth = frame.true_range * rays[..., 2]
        # Output is float32 (the file format), so agreement is limited by float32 rounding of z (about 3e-5 mm at 560 mm).
        stored_z = frame.xyz[..., 2][frame.hit_mask].astype(np.float64)
        assert np.all(np.abs(stored_z - true_depth[frame.hit_mask]) <= FLOAT32_ROUNDING_FACTOR * np.spacing(frame.xyz[..., 2][frame.hit_mask]))
        # x, y consistent with z: the point lies on the pixel ray.
        range_from_xyz = np.linalg.norm(frame.xyz.astype(np.float64), axis=-1)
        assert np.max(np.abs(range_from_xyz[frame.hit_mask] - frame.true_range[frame.hit_mask])) < 1e-3


def test_error_field_is_added_to_range():
    constant_mm = 0.7
    params = dataclasses.replace(PARAMS, effective_block_px=1, noise_coefficient_per_mm=0.0,
                                 noread_onset_deg=NO_READ_DISABLED_ONSET_DEG)
    frame = render_sphere_frame(params, SPHERE_CENTER, SPHERE_RADIUS_MM,
                                lambda u, v, rho, su, sv, k: np.full_like(rho, constant_mm), np.random.default_rng(SEED))
    measured_range = np.linalg.norm(frame.xyz.astype(np.float64), axis=-1)
    diff = (measured_range - frame.true_range)[frame.hit_mask]
    assert np.max(np.abs(diff - constant_mm)) < 1e-3          # float32 storage


def test_read_fraction_falls_with_incidence():
    rng = np.random.default_rng(SEED)
    cos_all, read_all = [], []
    for _ in range(N_REPEAT_FRAMES):
        frame = render_sphere_frame(PARAMS, SPHERE_CENTER, SPHERE_RADIUS_MM, zero_field, rng)
        cos_all.append(frame.true_cos_incidence[frame.hit_mask])
        read_all.append(frame.read_mask[frame.hit_mask])
    alpha_deg = np.degrees(np.arccos(np.concatenate(cos_all)))
    read = np.concatenate(read_all)
    low = read[alpha_deg < ALPHA_BIN_LOW_DEG]
    high = read[alpha_deg > ALPHA_BIN_HIGH_DEG]
    assert low.size > 0 and high.size > 0
    assert low.mean() > 0.9 and high.mean() < 0.3 and low.mean() > high.mean()


def test_true_slopes_match_image_slopes_on_a_tilted_plane():
    # Compare the analytic s_u, s_v (definition: module docstring) with dz/du * fx / z, dz/dv * fy / z from central differences of the true depth.
    params = dataclasses.replace(PARAMS, effective_block_px=1, noise_coefficient_per_mm=0.0,
                                 noread_onset_deg=NO_READ_DISABLED_ONSET_DEG)
    tilt = RigidTransform(facing_board_rotation([25.0, 30.0, 0.0]), [0.0, 0.0, SPHERE_DISTANCE_MM])
    frame = render_board_frame(params, tilt, (400.0, 400.0), zero_field, np.random.default_rng(SEED))
    z = frame.true_range * TEST_CAMERA.ray_directions()[..., 2]
    r, c = CENTER_ROW + 5, CENTER_COL - 7
    dz_du = (z[r, c + 1] - z[r, c - 1]) / 2.0
    dz_dv = (z[r + 1, c] - z[r - 1, c]) / 2.0
    s_u = dz_du * TEST_CAMERA.focal_x_px / z[r, c]
    s_v = dz_dv * TEST_CAMERA.focal_y_px / z[r, c]
    assert abs(s_u - frame.true_s_u[r, c]) < SLOPE_FD_TOLERANCE * max(1.0, abs(s_u))
    assert abs(s_v - frame.true_s_v[r, c]) < SLOPE_FD_TOLERANCE * max(1.0, abs(s_v))
    cos_from_slopes = 1.0 / np.sqrt(1.0 + frame.true_s_u ** 2 + frame.true_s_v ** 2)
    assert np.all(frame.true_cos_incidence[frame.hit_mask] > 0.0) and np.all(cos_from_slopes[frame.hit_mask] > 0.0)


def test_slope_sign_convention_on_plane_z_equals_z0_plus_m_x():
    # A plane z = z0 + m x has camera-facing normal proportional to (m, 0, -1) and s_u = m, s_v = 0 on the axis.
    from scipy.spatial.transform import Rotation
    normal = np.array([PLANE_SLOPE, 0.0, -1.0])
    normal /= np.linalg.norm(normal)
    rotation = Rotation.align_vectors([normal], [[0.0, 0.0, 1.0]])[0].as_matrix()   # board +z -> normal
    params = dataclasses.replace(PARAMS, effective_block_px=1, noise_coefficient_per_mm=0.0,
                                 noread_onset_deg=NO_READ_DISABLED_ONSET_DEG)
    pose = RigidTransform(rotation, [0.0, 0.0, SPHERE_DISTANCE_MM])
    frame = render_board_frame(params, pose, (400.0, 400.0), zero_field, np.random.default_rng(SEED))
    assert abs(frame.true_s_u[CENTER_ROW, CENTER_COL] - PLANE_SLOPE) < RANGE_TOLERANCE_MM
    assert abs(frame.true_s_v[CENTER_ROW, CENTER_COL]) < RANGE_TOLERANCE_MM
    # Depth increases to the right on this plane: z at larger u is larger.
    z = frame.true_range * TEST_CAMERA.ray_directions()[..., 2]
    assert z[CENTER_ROW, CENTER_COL + 1] > z[CENTER_ROW, CENTER_COL - 1]


def test_fixed_pattern_identical_across_frames_and_noise_differs():
    params = dataclasses.replace(PARAMS, noise_coefficient_per_mm=0.0, noread_onset_deg=NO_READ_DISABLED_ONSET_DEG,
                                 fixed_pattern_amplitude_mm=0.5, fixed_pattern_seed=7)
    first = render_sphere_frame(params, SPHERE_CENTER, SPHERE_RADIUS_MM, zero_field, np.random.default_rng(1))
    second = render_sphere_frame(params, SPHERE_CENTER, SPHERE_RADIUS_MM, zero_field, np.random.default_rng(2))
    assert np.array_equal(first.xyz, second.xyz) and np.any(first.xyz[..., 2] != 0)
    noisy = dataclasses.replace(PARAMS, noread_onset_deg=NO_READ_DISABLED_ONSET_DEG)
    a = render_sphere_frame(noisy, SPHERE_CENTER, SPHERE_RADIUS_MM, zero_field, np.random.default_rng(1))
    b = render_sphere_frame(noisy, SPHERE_CENTER, SPHERE_RADIUS_MM, zero_field, np.random.default_rng(2))
    assert not np.array_equal(a.xyz, b.xyz)


def test_write_synthetic_dataset(tmp_path):
    sensor_to_positioner = RigidTransform.from_rotation_vector_degrees([2.0, -3.0, 1.0], [100.0, -50.0, 20.0])
    positioner_to_sensor = sensor_to_positioner.inverse()
    # Targets defined in the positioner frame, in front of the sensor.
    def positioner_pose(point_in_sensor, rotation_deg):
        center = sensor_to_positioner.apply_points(point_in_sensor)
        rotation = facing_board_rotation(rotation_deg)
        return RigidTransform(sensor_to_positioner.rotation @ rotation, center)
    poses = [
        ("sphere", SPHERE_RADIUS_MM, positioner_pose([0.0, 0.0, SPHERE_DISTANCE_MM], [0.0, 0.0, 0.0])),
        ("sphere", SPHERE_RADIUS_MM, positioner_pose([30.0, -20.0, 700.0], [0.0, 0.0, 0.0])),
        ("board", (150.0, 100.0), positioner_pose([0.0, 0.0, 800.0], [10.0, 15.0, 0.0])),
    ]
    frames_per_pose = 2
    out = write_synthetic_dataset(tmp_path / "data", PARAMS, poses, sensor_to_positioner, frames_per_pose,
                                  default_injected_error_field_for_camera(TEST_CAMERA), np.random.default_rng(SEED))
    assert len(sorted(out.glob("*.mc"))) == len(poses) * frames_per_pose
    assert (out / "pose0001_Index01.mc").exists()
    records = load_manifest(out / "manifest.json")
    assert len(records) == len(poses) * frames_per_pose
    capture_set = CaptureSet(records)
    assert capture_set.pose_ids() == ["pose0000", "pose0001", "pose0002"]
    for record in records:
        header = read_matcloud(record.path).header
        pose_index = int(record.pose_id[-4:])
        assert np.allclose(np.asarray(header["robotPose"]).reshape(4, 4), record.target_pose_positioner.as_matrix())
        assert np.allclose(record.target_pose_positioner.as_matrix(), poses[pose_index][2].as_matrix())
        assert header["cameraName"] == "synthetic" and header["version"] == 2
        assert (header["h"], header["v"]) == (TEST_WIDTH_PX, TEST_HEIGHT_PX)
    stack = capture_set.load_stack("pose0002")
    assert stack.xyz.shape == (frames_per_pose, TEST_HEIGHT_PX, TEST_WIDTH_PX, 3)
    assert stack.valid.any() and stack.camera.focal_x_px == TEST_CAMERA.focal_x_px
    # Sphere seen where expected: the sphere on the optical axis shows a read pixel at the image center.
    assert capture_set.load_stack("pose0000").valid[0, CENTER_ROW, CENTER_COL]
    # Truth file.
    truth = json.loads((out / "truth.json").read_text())
    assert np.allclose(truth["sensor_to_positioner"], sensor_to_positioner.as_matrix())
    assert len(truth["poses"]) == len(poses) and truth["error_field"]
    assert truth["parameters"]["effective_block_px"] == PARAMS.effective_block_px
    # The sphere center in the sensor frame follows from the manifest pose and the transform.
    center_sensor = positioner_to_sensor.apply_points(records[0].target_pose_positioner.translation)
    assert np.allclose(center_sensor, [0.0, 0.0, SPHERE_DISTANCE_MM])


def test_write_options_disable_header_pose_and_manifest(tmp_path):
    poses = [("sphere", SPHERE_RADIUS_MM, RigidTransform(np.eye(3), SPHERE_CENTER))]
    out = write_synthetic_dataset(tmp_path / "d", PARAMS, poses, RigidTransform.identity(), 1, zero_field,
                                  np.random.default_rng(SEED), write_header_pose=False, write_manifest=False)
    assert not (out / "manifest.json").exists() and (out / "truth.json").exists()
    assert "robotPose" not in read_matcloud(out / "pose0000_Index00.mc").header
