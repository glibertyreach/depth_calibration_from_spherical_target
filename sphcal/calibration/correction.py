"""
Fitting the correction map: the orchestration of steps S1 to S4 of the
analysis document.

    S1  initial sensor-to-positioner transform from uncorrected sphere fits
    S2  per-sample residual targets against the known targets under that transform
    S3  penalized, robust, weighted least-squares fit of the sum-of-terms B-spline
    S4  correct the points, refit the sphere centers, re-solve the transform,
        rebuild the targets, refit; repeat until the transform settles

Poses are split into a training set and a held-out set BY POSE (never by
pixel), so the held-out error measures generalization to unseen placements.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sphcal.calibration.extrinsic import ExtrinsicParameters, fit_sphere_center, rigid_component_of_displacements, \
    solve_sensor_to_positioner
from sphcal.calibration.model_config import ModelConfiguration, build_model, default_configuration
from sphcal.calibration.samples import SampleParameters, SampleTable, build_correction_samples
from sphcal.geometry.transforms import RigidTransform
from sphcal.io.capture_set import CaptureSet
from sphcal.spline.fit import RobustParameters, SmoothingGrid, fit_penalized_least_squares, fit_robust, select_smoothing_by_gcv
from sphcal.spline.model import SumOfTermsSpline


@dataclass(frozen=True)
class HoldoutParameters:
    fraction: float = 0.2
    """Fraction of poses held out, chosen at random with the seed below."""
    seed: int = 12345
    min_training_sphere_poses: int = 3
    """The split must leave at least this many sphere poses for the transform solve."""


@dataclass(frozen=True)
class SmoothingSelection:
    """How the smoothing parameters are chosen."""

    method: str = "pose_cv"
    """"pose_cv": cross-validation with whole poses held out, which respects the
    correlation of native pixels within a pose and within an effective block;
    "gcv": the generalized cross-validation of the spline module, which counts
    every row as independent and therefore undersmooths correlated pixels;
    "none": keep the configured initial smoothing."""
    folds: int = 3
    """Number of pose folds for "pose_cv"."""
    grid: SmoothingGrid = field(default_factory=lambda: SmoothingGrid(log10_min=-3.0, log10_max=4.0, n_values=8, n_rounds=1))
    """Multipliers 10^g applied to each term's smoothing vector, searched term by term."""
    seed: int = 7


@dataclass(frozen=True)
class CorrectionFitParameters:
    samples: SampleParameters = field(default_factory=SampleParameters)
    extrinsic: ExtrinsicParameters = field(default_factory=ExtrinsicParameters)
    model: ModelConfiguration = field(default_factory=default_configuration)
    robust: RobustParameters = field(default_factory=RobustParameters)
    smoothing: SmoothingSelection = field(default_factory=SmoothingSelection)
    holdout: HoldoutParameters = field(default_factory=HoldoutParameters)
    select_smoothing_every_round: bool = False
    """GCV selection is costly; by default it runs in the first round only and the
    selected values are kept for the later rounds of the alternation."""


@dataclass
class AlternationRound:
    round_index: int
    transform: RigidTransform
    translation_change_mm: float
    rotation_change_deg: float
    training_residual_rms_mm: float
    rigid_translation_mm: np.ndarray
    rigid_rotation_deg: np.ndarray


@dataclass
class CorrectionFitResult:
    model: SumOfTermsSpline
    sensor_to_positioner: RigidTransform
    training_poses: list[str]
    holdout_poses: list[str]
    rounds: list[AlternationRound]
    training_samples: SampleTable
    holdout_samples: SampleTable | None
    holdout_residual_before_rms_mm: float | None
    holdout_residual_after_rms_mm: float | None


def subset_capture_set(capture_set: CaptureSet, pose_ids: list[str]) -> CaptureSet:
    """A CaptureSet holding only the records of the given poses, in the given order."""
    wanted = set(pose_ids)
    return CaptureSet([record for record in capture_set.records if record.pose_id in wanted])


def split_poses(capture_set: CaptureSet, params: HoldoutParameters) -> tuple[list[str], list[str]]:
    """Random split of pose ids into training and held-out lists."""
    rng = np.random.default_rng(params.seed)
    pose_ids = capture_set.pose_ids()
    kinds = {pid: capture_set.records_for(pid)[0].target_kind for pid in pose_ids}
    # Stratified by target kind, so that both spheres and boards appear in the
    # held-out set whenever the capture holds both.
    holdout, training = [], []
    for kind in sorted(set(kinds.values())):
        of_kind = [pid for pid in pose_ids if kinds[pid] == kind]
        order = rng.permutation(len(of_kind))
        n_holdout = int(round(params.fraction * len(of_kind)))
        holdout.extend(of_kind[i] for i in order[:n_holdout])
        training.extend(of_kind[i] for i in order[n_holdout:])
    training = [pid for pid in pose_ids if pid in set(training)]
    holdout = [pid for pid in pose_ids if pid in set(holdout)]
    n_training_spheres = sum(1 for pid in training if kinds[pid] == "sphere")
    if n_training_spheres < params.min_training_sphere_poses:
        raise ValueError(f"only {n_training_spheres} sphere poses would remain for training; "
                         f"need {params.min_training_sphere_poses}")
    return training, holdout


def initial_transform(capture_set: CaptureSet, pose_ids: list[str], params: CorrectionFitParameters) -> RigidTransform:
    """S1: transform from the centers of spheres fitted to the uncorrected points."""
    centers_sensor, centers_positioner = [], []
    for pid in pose_ids:
        records = capture_set.records_for(pid)
        record = records[0]
        if record.target_kind != "sphere":
            continue
        stack = capture_set.load_stack(pid)
        mean_xyz = _temporal_mean_points(stack.xyz, stack.valid, params.samples.min_temporal_valid_fraction)
        points = mean_xyz[np.isfinite(mean_xyz[..., 2])]
        center = fit_sphere_center(points, record.sphere_radius_mm, params.extrinsic.sphere_fit)
        centers_sensor.append(center)
        centers_positioner.append(record.target_pose_positioner.translation)
    if len(centers_sensor) < params.extrinsic.min_sphere_poses:
        raise ValueError("not enough sphere poses to solve the sensor-to-positioner transform")
    return solve_sensor_to_positioner(np.array(centers_sensor), np.array(centers_positioner),
                                      params=params.extrinsic.transform_solve)


def _temporal_mean_points(xyz_stack: np.ndarray, valid_stack: np.ndarray, min_valid_fraction: float) -> np.ndarray:
    """Per-pixel mean point over the frames in which the pixel was valid; NaN elsewhere."""
    count = valid_stack.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = (xyz_stack * valid_stack[..., None]).sum(axis=0) / count[..., None]
    enough = count >= min_valid_fraction * valid_stack.shape[0]
    return np.where(enough[..., None], mean, np.nan)


def select_smoothing_by_pose_cv(model: SumOfTermsSpline, samples: SampleTable, selection: SmoothingSelection) -> SumOfTermsSpline:
    """
    Choose each term's smoothing multiplier by K-fold cross-validation with
    whole poses held out: for each term in turn and each grid value, fit (plain
    penalized least squares) on the other folds and score the weighted RMS on
    the held fold; keep the multiplier with the smallest total score.
    """
    rng = np.random.default_rng(selection.seed)
    n_poses = len(samples.pose_ids)
    fold_of_pose = rng.permutation(n_poses) % selection.folds
    fold = fold_of_pose[samples.pose_index]
    design = model.design(samples.inputs)
    grid = selection.grid
    multipliers = np.logspace(grid.log10_min, grid.log10_max, grid.n_values)
    base = [list(term.smoothing) for term in model.terms]
    chosen = [1.0] * len(model.terms)

    def cv_score() -> float:
        penalty = model.penalty()
        total, count = 0.0, 0.0
        for k in range(selection.folds):
            train, test = fold != k, fold == k
            if not test.any() or not train.any():
                continue
            fit = fit_penalized_least_squares(design[train], samples.target[train], samples.weight[train], penalty)
            residual = samples.target[test] - design[test] @ fit.coefficients
            total += float(np.sum(samples.weight[test] * residual ** 2))
            count += float(np.sum(samples.weight[test]))
        return total / count

    for _ in range(grid.n_rounds):
        for t_index, term in enumerate(model.terms):
            best_score, best_multiplier = np.inf, chosen[t_index]
            for multiplier in multipliers:
                term.smoothing = [b * multiplier for b in base[t_index]]
                score = cv_score()
                if score < best_score:
                    best_score, best_multiplier = score, multiplier
            chosen[t_index] = best_multiplier
            term.smoothing = [b * best_multiplier for b in base[t_index]]
    model.metadata["smoothing_multipliers"] = {term.name: float(m) for term, m in zip(model.terms, chosen)}
    return model


def _fit_model_on(samples: SampleTable, model: SumOfTermsSpline, params: CorrectionFitParameters,
                  select_smoothing: bool) -> SumOfTermsSpline:
    """S3: the penalized robust fit, with an optional search over smoothing."""
    if select_smoothing and params.smoothing.method == "pose_cv":
        model = select_smoothing_by_pose_cv(model, samples, params.smoothing)
    elif select_smoothing and params.smoothing.method == "gcv":
        model = select_smoothing_by_gcv(model, samples.inputs, samples.target, samples.weight, params.smoothing.grid)
    design = model.design(samples.inputs)
    result = fit_robust(design, samples.target, samples.weight, model.penalty(), params.robust)
    model.coefficients = result.coefficients
    return model


def _refit_transform(capture_set: CaptureSet, samples: SampleTable, model: SumOfTermsSpline,
                     params: CorrectionFitParameters) -> RigidTransform:
    """Diagnostic form of S4: correct the sample points with the current map,
    refit the sphere centers, re-solve the transform. The fitting loop uses the
    rigid component of the map instead (see fit_correction), which has a
    definite fixed point; this function is kept for reports and tests."""
    delta = model.evaluate(samples.inputs)
    corrected_points = samples.ray_direction * (samples.inputs[:, 2] + delta)[:, None]
    centers_sensor, centers_positioner = [], []
    for pose_number, pose_id in enumerate(samples.pose_ids):
        if samples.pose_kinds[pose_number] != "sphere":
            continue
        mask = samples.pose_index == pose_number
        if mask.sum() < 4:
            continue
        record = capture_set.records_for(pose_id)[0]
        center = fit_sphere_center(corrected_points[mask], record.sphere_radius_mm, params.extrinsic.sphere_fit,
                                   weights=samples.weight[mask])
        centers_sensor.append(center)
        centers_positioner.append(record.target_pose_positioner.translation)
    return solve_sensor_to_positioner(np.array(centers_sensor), np.array(centers_positioner),
                                      params=params.extrinsic.transform_solve)


def fit_correction(capture_set: CaptureSet, params: CorrectionFitParameters,
                   sensor_to_positioner: RigidTransform | None = None) -> CorrectionFitResult:
    """Run S1 to S4 and evaluate on the held-out poses."""
    training_ids, holdout_ids = split_poses(capture_set, params.holdout)
    training_set = subset_capture_set(capture_set, training_ids)
    transform = sensor_to_positioner or initial_transform(training_set, training_ids, params)
    first_stack = training_set.load_stack(training_ids[0])
    width, height = first_stack.camera.width, first_stack.camera.height
    rounds: list[AlternationRound] = []
    model: SumOfTermsSpline | None = None
    samples = build_correction_samples(training_set, transform, params.samples)
    for round_index in range(params.extrinsic.max_alternation_rounds):
        if model is None:
            model = build_model(params.model, samples.inputs, width, height,
                                metadata={"gauge": "sensor frame; transform re-solved from corrected sphere centers"})
        select = round_index == 0 or params.select_smoothing_every_round
        model = _fit_model_on(samples, model, params, select)
        residual_after = samples.target - model.evaluate(samples.inputs)
        rms = float(np.sqrt(np.average(residual_after ** 2, weights=samples.weight)))
        delta = model.evaluate(samples.inputs)
        t_rigid, omega_rigid = rigid_component_of_displacements(samples.measured_point,
                                                                samples.ray_direction * delta[:, None], samples.weight)
        # Gauge (D-1): the map must carry no rigid motion. Its best-fitting rigid
        # component G (p -> p + t + omega x p) is folded into the transform: a
        # point the map would move by G and the old transform would then carry
        # into the positioner frame is carried there by transform o G instead,
        # and the next map fit, against targets rebuilt under the new transform,
        # no longer needs that component. The fixed point is G = identity.
        rigid_part = RigidTransform.from_rotation_vector_degrees(np.degrees(omega_rigid), t_rigid)
        new_transform = transform.compose(rigid_part)
        dt, drot = new_transform.difference_from(transform)
        rounds.append(AlternationRound(round_index, new_transform, dt, drot, rms, t_rigid, np.degrees(omega_rigid)))
        transform = new_transform
        converged = dt < params.extrinsic.convergence_translation_mm and drot < params.extrinsic.convergence_rotation_deg
        samples = build_correction_samples(training_set, transform, params.samples)
        if converged:
            model = _fit_model_on(samples, model, params, select_smoothing=False)
            break
    holdout_samples = None
    before = after = None
    if holdout_ids:
        holdout_samples = build_correction_samples(subset_capture_set(capture_set, holdout_ids), transform, params.samples)
        residual_before = holdout_samples.target
        residual_after = holdout_samples.target - model.evaluate(holdout_samples.inputs)
        before = float(np.sqrt(np.average(residual_before ** 2, weights=holdout_samples.weight)))
        after = float(np.sqrt(np.average(residual_after ** 2, weights=holdout_samples.weight)))
    return CorrectionFitResult(model, transform, training_ids, holdout_ids, rounds, samples, holdout_samples, before, after)
