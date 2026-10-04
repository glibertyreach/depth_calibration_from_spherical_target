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

import os
from concurrent.futures import ProcessPoolExecutor
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
    1 / block^2 (times stride^2 when the stride below skips pixels)."""
    pixel_stride: int = 4
    """Take every stride-th pixel in u and in v as a sample. With the stride
    equal to the effective block, one sample per block carries the block's
    information and the design matrix is stride^2 times smaller; the
    correction is still evaluated at every native pixel (D-4)."""
    noread_pixel_stride: int = 8
    """Stride for the read-probability samples, which vary slowly across the
    image and need far fewer rows than the correction samples."""
    workers: int = 0
    """Processes used for the per-pose feature extraction; 0 means all cores."""
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
    max_abs_slope: float = 1.5
    """Samples whose measured slope component exceeds this (tan of about 56
    degrees) are outside the map's slope domain and are excluded; the window
    estimator can report such values near a sphere's limb."""
    variance_pooling_incidence_bin_deg: float = 10.0
    """Per-pixel variances from a handful of frames are far too noisy to serve
    as weights one by one (a sample variance from three frames scatters by a
    factor of several). They are therefore pooled within each pose over bins of
    predicted incidence of this width, and every pixel of a bin gets the bin's
    pooled variance."""
    variance_pooling_min_pixels: int = 30
    """A bin with fewer pixels than this takes the pose-wide pooled variance."""
    variance_trim_fraction: float = 0.05
    """Fraction of the largest per-pixel variances dropped before pooling, so
    that flying pixels do not inflate the pooled value."""


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
    range_variance: np.ndarray | None = None   # (N,) per-pixel variance of the mean range, before pooling
    retarget_misses: int = 0                   # rows whose ray missed the target at the last retargeting

    def subset(self, mask: np.ndarray) -> "SampleTable":
        return SampleTable(self.inputs[mask], self.target[mask], self.weight[mask], self.pose_index[mask],
                           self.pixel_index[mask], self.ray_direction[mask], self.measured_point[mask],
                           self.predicted_cos_incidence[mask], self.pose_ids, self.pose_kinds, self.frames_per_pose,
                           None if self.range_variance is None else self.range_variance[mask])

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


def pooled_variance(variance: np.ndarray, cos_incidence: np.ndarray, selection: np.ndarray,
                    params: SampleParameters) -> np.ndarray:
    """
    Replace per-pixel variances by their trimmed mean over incidence bins of the
    pose (see SampleParameters.variance_pooling_incidence_bin_deg). Returns an
    image of pooled variances over the selected pixels, NaN elsewhere.
    """
    pooled = np.full(variance.shape, np.nan)
    values = variance[selection]
    finite = np.isfinite(values)
    if not finite.any():
        return pooled

    def trimmed_mean(v: np.ndarray) -> float:
        v = np.sort(v[np.isfinite(v)])
        keep = max(1, int(round(v.size * (1.0 - params.variance_trim_fraction))))
        return float(v[:keep].mean())

    pose_wide = trimmed_mean(values)
    incidence = np.degrees(np.arccos(np.clip(cos_incidence[selection], -1.0, 1.0)))
    bins = np.floor(incidence / params.variance_pooling_incidence_bin_deg).astype(int)
    result = np.full(values.shape, pose_wide)
    for b in np.unique(bins):
        in_bin = (bins == b) & finite
        if in_bin.sum() >= params.variance_pooling_min_pixels:
            result[bins == b] = trimmed_mean(values[in_bin])
    pooled[selection] = result
    return pooled


def stride_mask(shape: tuple[int, int], stride: int) -> np.ndarray:
    """True on every stride-th pixel in both directions, starting at the half-stride offset."""
    mask = np.zeros(shape, dtype=bool)
    offset = stride // 2
    mask[offset::stride, offset::stride] = True
    return mask


def sample_weight_factor(params: SampleParameters) -> float:
    """Block-independence factor adjusted for the stride: stride^2 / block^2, at most 1."""
    return min(1.0, block_independence_weight(params.effective_block_px) * params.pixel_stride ** 2)


def _pose_correction_rows(args) -> dict:
    """Per-pose worker for build_correction_samples (module-level so that it can be pickled)."""
    capture_set, pose_number, pose_id, sensor_to_positioner, params = args
    block_weight = sample_weight_factor(params)
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
    usable &= (np.abs(slope_u) <= params.max_abs_slope) & (np.abs(slope_v) <= params.max_abs_slope)
    usable &= stride_mask(usable.shape, params.pixel_stride)
    n_frames = depth_stack.shape[0]
    if n_frames > 1:
        per_pixel = measured_range_variance(stats.variance, mean_depth, measured_range)
        # The variance of the temporal MEAN is the per-frame variance over the frame count.
        per_pixel = per_pixel / n_frames
        variance = pooled_variance(per_pixel, coverage.cos_incidence, usable, params)
        variance = np.where(np.isfinite(variance), variance, params.single_frame_variance_mm2)
    else:
        per_pixel = np.full(mean_depth.shape, params.single_frame_variance_mm2)
        variance = per_pixel
    variance = np.maximum(variance, params.variance_floor_mm2)
    u_grid, v_grid = camera.pixel_grid()
    rays = camera.ray_directions()
    sel = np.nonzero(usable)
    n = sel[0].size
    return {
        "inputs": np.column_stack([u_grid[sel], v_grid[sel], measured_range[sel], slope_u[sel], slope_v[sel],
                                   np.full(n, coverage.curvature_per_mm)]),
        "target": residual[sel], "weight": block_weight / variance[sel],
        "pose": np.full(n, pose_number, dtype=np.int64),
        "pixel": (sel[0] * camera.width + sel[1]).astype(np.int64),
        "ray": rays[sel], "point": rays[sel] * measured_range[sel][:, None],
        "cos": coverage.cos_incidence[sel], "var": per_pixel[sel],
        "pose_id": pose_id, "kind": record.target_kind, "frames": n_frames,
    }


def _map_over_poses(function, capture_set: CaptureSet, sensor_to_positioner: RigidTransform,
                    params: SampleParameters) -> list[dict]:
    """Run a per-pose worker over all poses, in processes when more than one is allowed."""
    tasks = [(capture_set, number, pose_id, sensor_to_positioner, params)
             for number, pose_id in enumerate(capture_set.pose_ids())]
    workers = params.workers or (os.cpu_count() or 1)
    if workers <= 1 or len(tasks) <= 1:
        return [function(task) for task in tasks]
    with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
        return list(pool.map(function, tasks))


def build_correction_samples(capture_set: CaptureSet, sensor_to_positioner: RigidTransform,
                             params: SampleParameters) -> SampleTable:
    """Assemble the correction-sample table over every pose of the capture set."""
    results = _map_over_poses(_pose_correction_rows, capture_set, sensor_to_positioner, params)
    if not results or sum(r["inputs"].shape[0] for r in results) == 0:
        raise ValueError("the capture set produced no samples")
    cat = lambda key: np.concatenate([r[key] for r in results])
    return SampleTable(cat("inputs"), cat("target"), cat("weight"), cat("pose"), cat("pixel"), cat("ray"),
                       cat("point"), cat("cos"), [r["pose_id"] for r in results], [r["kind"] for r in results],
                       [r["frames"] for r in results], cat("var"))


def retarget_samples(samples: SampleTable, capture_set: CaptureSet, camera: PinholeCamera,
                     sensor_to_positioner: RigidTransform, params: SampleParameters) -> SampleTable:
    """
    Recompute the residual targets of an EXISTING sample table under a new
    sensor-to-positioner transform, keeping the rows (and therefore the design
    matrix and the weights) fixed. Only the predicted range changes with the
    transform; the measured inputs do not. A row whose ray no longer meets its
    target under the new transform keeps its previous target and is counted.
    The transform changes between alternation rounds are a fraction of a
    millimeter, so such rows are rare.
    """
    target = samples.target.copy()
    cos_incidence = samples.predicted_cos_incidence.copy()
    misses = 0
    for pose_number, pose_id in enumerate(samples.pose_ids):
        rows = np.nonzero(samples.pose_index == pose_number)[0]
        if rows.size == 0:
            continue
        record = capture_set.records_for(pose_id)[0]
        coverage = predict_coverage_for(record, camera, sensor_to_positioner, params.coverage)
        predicted = coverage.range_mm.ravel()[samples.pixel_index[rows]]
        new_target = predicted - samples.inputs[rows, 2]
        hit = np.isfinite(new_target)
        misses += int((~hit).sum())
        target[rows[hit]] = new_target[hit]
        cos_incidence[rows[hit]] = coverage.cos_incidence.ravel()[samples.pixel_index[rows]][hit]
    return SampleTable(samples.inputs, target, samples.weight, samples.pose_index, samples.pixel_index,
                       samples.ray_direction, samples.measured_point, cos_incidence, samples.pose_ids,
                       samples.pose_kinds, samples.frames_per_pose, samples.range_variance, misses)


def _pose_noread_rows(args) -> dict:
    """Per-pose worker for build_noread_samples."""
    capture_set, pose_number, pose_id, sensor_to_positioner, params = args
    block_weight = sample_weight_factor(params)
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
    usable = covered & np.isfinite(slope_u) & np.isfinite(slope_v) & stride_mask(covered.shape, params.noread_pixel_stride)
    sel = np.nonzero(usable)
    n = sel[0].size
    return {"inputs": np.column_stack([u_grid[sel], v_grid[sel], coverage.range_mm[sel], slope_u[sel], slope_v[sel],
                                       np.full(n, coverage.curvature_per_mm)]),
            "fraction": read_fraction[sel], "trials": np.full(n, n_frames * block_weight),
            "pose": np.full(n, pose_number, dtype=np.int64), "cos": coverage.cos_incidence[sel]}


def build_noread_samples(capture_set: CaptureSet, sensor_to_positioner: RigidTransform,
                         params: SampleParameters) -> NoReadTable:
    """
    Assemble read-fraction samples over every pixel the known target covers,
    whether or not it read. Inputs are predicted: the predicted range, and the
    slopes of the PREDICTED depth image computed with the same window estimator
    as the measured slopes, so that the two maps index slope the same way.
    """
    results = _map_over_poses(_pose_noread_rows, capture_set, sensor_to_positioner, params)
    cat = lambda key: np.concatenate([r[key] for r in results])
    return NoReadTable(cat("inputs"), cat("fraction"), cat("trials"), cat("pose"), cat("cos"))
