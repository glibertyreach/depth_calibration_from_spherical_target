"""
Assembly of calibration samples from a CaptureSet and a sensor-to-positioner
transform.

One sample is one native pixel of one pose: its map inputs (u, v, measured
range, slope components, curvature), its residual target (true range along the
pixel ray minus measured range), and its weight. The true range comes from the
known target (sphere or board) at its commanded pose, transformed into the
sensor frame. Section 4 of docs/design/code_design.md defines every quantity.

Two kinds of tables are produced:
- correction samples, indexed by MEASURED quantities (what is available at
  runtime), for the correction map;
- no-read samples, indexed by PREDICTED quantities (a pixel that did not read
  has no measurement), for the read-probability map.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sphcal.features.depth_features import SlopeParameters, image_slopes, range_from_depth, temporal_statistics, \
    block_independence_weight
from sphcal.geometry.camera import PinholeCamera
from sphcal.geometry.targets import BoardTarget, CoverageParameters, PredictedCoverage, predict_board_coverage, \
    predict_sphere_coverage
from sphcal.geometry.transforms import RigidTransform
from sphcal.io.capture_set import CaptureSet
from sphcal.io.poses import CaptureRecord

INPUT_NAMES = ("u", "v", "range", "slope_u", "slope_v", "curvature")
"""Order of the map inputs; fixed by the design document, section 4."""

INPUT_UNITS = ("px", "px", "mm", "dimensionless", "dimensionless", "1/mm")


@dataclass(frozen=True)
class SampleParameters:
    """Everything that decides which pixels become samples and how they are weighted."""

    coverage: CoverageParameters = field(default_factory=CoverageParameters)
    slope: SlopeParameters = field(default_factory=SlopeParameters)
    effective_block_px: int = 4
    """Lateral pitch of one independent depth sample in native pixels (D-4):
    native pixels within a block are not independent, so each gets the weight
    1 / block^2."""
    min_temporal_valid_fraction: float = 0.8
    """A pixel must have read in at least this fraction of a pose's frames to be a sample."""
    variance_floor_mm2: float = 1.0e-4
    """Lower bound on the per-pixel range variance used for weighting, so that a
    pixel whose frames happened to agree exactly does not get an unbounded weight."""
    single_frame_variance_mm2: float = 1.0e-2
    """Variance assumed when a pose has only one frame and no temporal variance exists."""
    max_abs_residual_mm: float = 20.0
    """Gross-error gate: a residual larger than this is a mixed pixel or a wrong
    pose, not a calibration error, and is excluded before any fitting."""


@dataclass
class SampleTable:
    """Correction samples. Rows are native pixels of poses."""

    inputs: np.ndarray            # (N, 6) in INPUT_NAMES order
    target: np.ndarray            # (N,) true range minus measured range, mm
    weight: np.ndarray            # (N,) inverse variance times block factor
    pose_index: np.ndarray        # (N,) index into the pose id list
    pixel_index: np.ndarray       # (N,) v * width + u
    ray_direction: np.ndarray     # (N, 3) unit ray of the pixel (for displacement fields and corrected points)
    measured_point: np.ndarray    # (N, 3) temporal-mean measured point, sensor frame
    predicted_cos_incidence: np.ndarray  # (N,)
    pose_ids: list[str]
    pose_kinds: list[str]
    frames_per_pose: list[int]

    def subset(self, mask: np.ndarray) -> "SampleTable":
        return SampleTable(self.inputs[mask], self.target[mask], self.weight[mask], self.pose_index[mask],
                           self.pixel_index[mask], self.ray_direction[mask], self.measured_point[mask],
                           self.predicted_cos_incidence[mask], self.pose_ids, self.pose_kinds, self.frames_per_pose)

    @property
    def n_samples(self) -> int:
        return int(self.inputs.shape[0])


@dataclass
class NoReadTable:
    """Read-probability samples, indexed by predicted geometry."""

    inputs: np.ndarray            # (N, 6), predicted
    read_fraction: np.ndarray     # (N,) in [0, 1]
    trials: np.ndarray            # (N,) number of frames, times the block factor
    pose_index: np.ndarray
    predicted_cos_incidence: np.ndarray


def target_in_sensor_frame(record: CaptureRecord, sensor_to_positioner: RigidTransform) -> RigidTransform:
    """The target's pose expressed in the sensor frame."""
    return sensor_to_positioner.inverse().compose(record.target_pose_positioner)


def predict_coverage_for(record: CaptureRecord, camera: PinholeCamera, sensor_to_positioner: RigidTransform,
                         params: CoverageParameters) -> PredictedCoverage:
    """Predicted range, incidence and masks of the record's target in this frame."""
    pose_sensor = target_in_sensor_frame(record, sensor_to_positioner)
    if record.target_kind == "sphere":
        return predict_sphere_coverage(camera, pose_sensor.translation, record.sphere_radius_mm, params)
    if record.target_kind == "board":
        half_w, half_h = record.board_half_size_mm
        return predict_board_coverage(camera, pose_sensor, BoardTarget(half_w, half_h), params)
    raise ValueError(f"unknown target kind {record.target_kind!r}")


def measured_range_variance(depth_variance: np.ndarray, depth_mean: np.ndarray, measured_range: np.ndarray) -> np.ndarray:
    """Variance of the range along the ray from the variance of camera-z depth: the
    range is depth times a fixed per-pixel factor, so the variance scales by its square."""
    with np.errstate(divide="ignore", invalid="ignore"):
        factor = np.where(depth_mean > 0, measured_range / depth_mean, np.nan)
    return depth_variance * factor ** 2


def build_correction_samples(capture_set: CaptureSet, sensor_to_positioner: RigidTransform,
                             params: SampleParameters) -> SampleTable:
    """Assemble the correction-sample table over every pose of the capture set."""
    block_weight = block_independence_weight(params.effective_block_px)
    rows_inputs, rows_target, rows_weight, rows_pose, rows_pixel = [], [], [], [], []
    rows_ray, rows_point, rows_cos = [], [], []
    pose_ids, pose_kinds, frames_per_pose = [], [], []
    for pose_number, pose_id in enumerate(capture_set.pose_ids()):
        stack = capture_set.load_stack(pose_id)
        record = stack.records[0]
        camera = stack.camera
        depth_stack = stack.xyz[..., 2].astype(np.float64)
        stats = temporal_statistics(depth_stack, stack.valid, params.min_temporal_valid_fraction)
        mean_depth = stats.mean_depth
        valid = np.isfinite(mean_depth)
        coverage = predict_coverage_for(record, camera, sensor_to_positioner, params.coverage)
        measured_range = range_from_depth(np.where(valid, mean_depth, np.nan), camera)
        slope_u, slope_v = image_slopes(mean_depth, valid, camera, params.slope)
        residual = coverage.range_mm - measured_range
        usable = coverage.usable & valid & np.isfinite(slope_u) & np.isfinite(slope_v) & np.isfinite(residual)
        usable &= np.abs(residual) <= params.max_abs_residual_mm
        n_frames = depth_stack.shape[0]
        if n_frames > 1:
            variance = measured_range_variance(stats.variance, mean_depth, measured_range)
            variance = np.where(np.isfinite(variance), variance, params.single_frame_variance_mm2)
        else:
            variance = np.full(mean_depth.shape, params.single_frame_variance_mm2)
        variance = np.maximum(variance, params.variance_floor_mm2)
        u_grid, v_grid = camera.pixel_grid()
        rays = camera.ray_directions()
        curvature = coverage.curvature_per_mm
        sel = np.nonzero(usable)
        n = sel[0].size
        inputs = np.column_stack([u_grid[sel], v_grid[sel], measured_range[sel], slope_u[sel], slope_v[sel],
                                  np.full(n, curvature)])
        rows_inputs.append(inputs)
        rows_target.append(residual[sel])
        rows_weight.append(block_weight / variance[sel])
        rows_pose.append(np.full(n, pose_number, dtype=np.int64))
        rows_pixel.append((sel[0] * camera.width + sel[1]).astype(np.int64))
        rows_ray.append(rays[sel])
        rows_point.append(rays[sel] * measured_range[sel][:, None])
        rows_cos.append(coverage.cos_incidence[sel])
        pose_ids.append(pose_id)
        pose_kinds.append(record.target_kind)
        frames_per_pose.append(n_frames)
    if not rows_inputs:
        raise ValueError("the capture set produced no samples")
    return SampleTable(np.concatenate(rows_inputs), np.concatenate(rows_target), np.concatenate(rows_weight),
                       np.concatenate(rows_pose), np.concatenate(rows_pixel), np.concatenate(rows_ray),
                       np.concatenate(rows_point), np.concatenate(rows_cos), pose_ids, pose_kinds, frames_per_pose)


def build_noread_samples(capture_set: CaptureSet, sensor_to_positioner: RigidTransform,
                         params: SampleParameters) -> NoReadTable:
    """
    Assemble read-fraction samples over every pixel the known target covers,
    whether or not it read. Inputs are predicted: the predicted range, and the
    slopes of the PREDICTED depth image computed with the same window estimator
    as the measured slopes, so that the two maps index slope the same way.
    """
    block_weight = block_independence_weight(params.effective_block_px)
    rows_inputs, rows_fraction, rows_trials, rows_pose, rows_cos = [], [], [], [], []
    for pose_number, pose_id in enumerate(capture_set.pose_ids()):
        stack = capture_set.load_stack(pose_id)
        record = stack.records[0]
        camera = stack.camera
        n_frames = stack.valid.shape[0]
        read_fraction = stack.valid.sum(axis=0) / float(n_frames)
        coverage = predict_coverage_for(record, camera, sensor_to_positioner, params.coverage)
        covered = coverage.covered & np.isfinite(coverage.range_mm)
        u_grid, v_grid = camera.pixel_grid()
        rays = camera.ray_directions()
        predicted_depth = np.where(covered, coverage.range_mm * rays[..., 2], np.nan)
        slope_u, slope_v = image_slopes(predicted_depth, covered, camera, params.slope)
        usable = covered & np.isfinite(slope_u) & np.isfinite(slope_v)
        sel = np.nonzero(usable)
        n = sel[0].size
        rows_inputs.append(np.column_stack([u_grid[sel], v_grid[sel], coverage.range_mm[sel], slope_u[sel],
                                            slope_v[sel], np.full(n, coverage.curvature_per_mm)]))
        rows_fraction.append(read_fraction[sel])
        rows_trials.append(np.full(n, n_frames * block_weight))
        rows_pose.append(np.full(n, pose_number, dtype=np.int64))
        rows_cos.append(coverage.cos_incidence[sel])
    return NoReadTable(np.concatenate(rows_inputs), np.concatenate(rows_fraction), np.concatenate(rows_trials),
                       np.concatenate(rows_pose), np.concatenate(rows_cos))
