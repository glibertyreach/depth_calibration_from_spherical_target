"""
Validation report (step S6): residual statistics by incidence and range before
and after correction on held-out poses, sphere-center errors, and the
normal-bias test on boards with the downstream 5 x 5 estimator (D-12).
Numbers go to a JSON file; figures, when matplotlib is available, to PNG.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from sphcal.calibration.apply import correct_frame
from sphcal.calibration.extrinsic import SphereFitParameters, fit_sphere_center
from sphcal.calibration.samples import SampleParameters, SampleTable, predict_coverage_for
from sphcal.features.normals import NormalEstimatorParameters, plane_fit_normals
from sphcal.geometry.transforms import RigidTransform
from sphcal.io.capture_set import CaptureSet
from sphcal.spline.model import SumOfTermsSpline


@dataclass(frozen=True)
class ReportParameters:
    incidence_bin_edges_deg: tuple[float, ...] = (0.0, 15.0, 30.0, 45.0, 55.0, 65.0)
    range_bin_count: int = 4
    normal_estimator: NormalEstimatorParameters = field(default_factory=NormalEstimatorParameters)
    normal_bias_limit_low_deg: float = 0.5
    normal_bias_limit_high_deg: float = 1.0
    normal_bias_split_incidence_deg: float = 45.0
    """D-12: patch-mean normal bias limits below and above the split incidence."""
    sphere_fit: SphereFitParameters = field(default_factory=SphereFitParameters)


def weighted_rms(values: np.ndarray, weights: np.ndarray) -> float:
    return float(np.sqrt(np.average(values ** 2, weights=weights))) if values.size else float("nan")


def binned_residuals(samples: SampleTable, model: SumOfTermsSpline, params: ReportParameters) -> dict:
    """Weighted RMS and mean of the residual before and after correction, by incidence and by range bins."""
    before = samples.target
    after = samples.target - model.evaluate(samples.inputs)
    incidence = np.degrees(np.arccos(np.clip(samples.predicted_cos_incidence, -1.0, 1.0)))
    edges = np.array(params.incidence_bin_edges_deg)
    by_incidence = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (incidence >= lo) & (incidence < hi)
        by_incidence.append({"incidence_deg": [float(lo), float(hi)], "count": int(m.sum()),
                             "rms_before_mm": weighted_rms(before[m], samples.weight[m]),
                             "rms_after_mm": weighted_rms(after[m], samples.weight[m]),
                             "mean_before_mm": float(np.average(before[m], weights=samples.weight[m])) if m.any() else None,
                             "mean_after_mm": float(np.average(after[m], weights=samples.weight[m])) if m.any() else None})
    ranges = samples.inputs[:, 2]
    range_edges = np.quantile(ranges, np.linspace(0.0, 1.0, params.range_bin_count + 1))
    by_range = []
    for lo, hi in zip(range_edges[:-1], range_edges[1:]):
        m = (ranges >= lo) & (ranges <= hi)
        by_range.append({"range_mm": [float(lo), float(hi)], "count": int(m.sum()),
                         "rms_before_mm": weighted_rms(before[m], samples.weight[m]),
                         "rms_after_mm": weighted_rms(after[m], samples.weight[m])})
    return {"overall_rms_before_mm": weighted_rms(before, samples.weight),
            "overall_rms_after_mm": weighted_rms(after, samples.weight),
            "by_incidence": by_incidence, "by_range": by_range}


def sphere_center_errors(capture_set: CaptureSet, pose_ids: list[str], model: SumOfTermsSpline,
                         transform: RigidTransform, sample_params: SampleParameters, params: ReportParameters) -> list[dict]:
    """Fitted center of each sphere pose, from uncorrected and corrected points, against the commanded center."""
    rows = []
    for pid in pose_ids:
        record = capture_set.records_for(pid)[0]
        if record.target_kind != "sphere":
            continue
        stack = capture_set.load_stack(pid)
        mean_valid = stack.valid.mean(axis=0) >= sample_params.min_temporal_valid_fraction
        mean_xyz = np.where(mean_valid[..., None], (stack.xyz * stack.valid[..., None]).sum(axis=0)
                            / np.maximum(stack.valid.sum(axis=0), 1)[..., None], 0.0)
        corrected = correct_frame(mean_xyz, mean_valid, stack.camera, model, sample_params.slope,
                                  1.0 / record.sphere_radius_mm)
        commanded = transform.inverse().apply_points(record.target_pose_positioner.translation)
        raw_center = fit_sphere_center(mean_xyz[mean_valid], record.sphere_radius_mm, params.sphere_fit)
        corr_center = fit_sphere_center(corrected.xyz[corrected.valid], record.sphere_radius_mm, params.sphere_fit)
        rows.append({"pose_id": pid, "center_error_before_mm": float(np.linalg.norm(raw_center - commanded)),
                     "center_error_after_mm": float(np.linalg.norm(corr_center - commanded))})
    return rows


def board_normal_bias(capture_set: CaptureSet, pose_ids: list[str], model: SumOfTermsSpline, transform: RigidTransform,
                      sample_params: SampleParameters, params: ReportParameters) -> list[dict]:
    """
    D-12 test: on each board pose, the angle between the patch-mean of the
    downstream 5 x 5 normals (before and after correction) and the commanded
    board normal, with the pass/fail limit by incidence.
    """
    rows = []
    for pid in pose_ids:
        record = capture_set.records_for(pid)[0]
        if record.target_kind != "board":
            continue
        stack = capture_set.load_stack(pid)
        camera = stack.camera
        mean_valid = stack.valid.mean(axis=0) >= sample_params.min_temporal_valid_fraction
        mean_xyz = np.where(mean_valid[..., None], (stack.xyz * stack.valid[..., None]).sum(axis=0)
                            / np.maximum(stack.valid.sum(axis=0), 1)[..., None], 0.0)
        coverage = predict_coverage_for(record, camera, transform, sample_params.coverage)
        pose_sensor = transform.inverse().compose(record.target_pose_positioner)
        true_normal = pose_sensor.apply_directions(np.array([0.0, 0.0, 1.0]))
        # Orient the commanded normal toward the camera for comparison with camera-facing estimates.
        if true_normal @ pose_sensor.translation > 0:
            true_normal = -true_normal
        corrected = correct_frame(mean_xyz, mean_valid, camera, model, sample_params.slope, 0.0)
        patch = coverage.usable & mean_valid
        def mean_angle(points, valid):
            normals = plane_fit_normals(points, valid, params.normal_estimator)
            ok = patch & np.isfinite(normals[..., 0])
            if not ok.any():
                return None
            mean_n = normals[ok].mean(axis=0)
            mean_n /= np.linalg.norm(mean_n)
            return float(np.degrees(np.arccos(np.clip(abs(mean_n @ true_normal), -1.0, 1.0))))
        incidence = float(np.degrees(np.arccos(np.clip(np.nanmedian(coverage.cos_incidence[patch]), -1, 1)))) if patch.any() else None
        limit = params.normal_bias_limit_low_deg if (incidence is not None and incidence < params.normal_bias_split_incidence_deg) \
            else params.normal_bias_limit_high_deg
        after = mean_angle(corrected.xyz, corrected.valid)
        rows.append({"pose_id": pid, "median_incidence_deg": incidence,
                     "normal_bias_before_deg": mean_angle(mean_xyz, mean_valid),
                     "normal_bias_after_deg": after, "limit_deg": limit,
                     "passes": (after is not None and after <= limit)})
    return rows


def write_report(path: Path, content: dict) -> None:
    Path(path).write_text(json.dumps(content, indent=2, default=_json_default))


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)}")


def plot_residuals_by_incidence(binned: dict, path: Path) -> None:
    """Residual RMS before and after correction versus incidence, as a PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    centers = [0.5 * sum(b["incidence_deg"]) for b in binned["by_incidence"]]
    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
    ax.plot(centers, [b["rms_before_mm"] for b in binned["by_incidence"]], "o-", label="before correction")
    ax.plot(centers, [b["rms_after_mm"] for b in binned["by_incidence"]], "s-", label="after correction")
    ax.set_xlabel("incidence (deg)")
    ax.set_ylabel("held-out range residual RMS (mm)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
