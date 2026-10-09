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
from sphcal.calibration.fast_solve import FixedDesignSystem, HuberParameters, PoseFoldCrossValidator
from sphcal.calibration.samples import SampleParameters, SampleTable, build_correction_samples, retarget_samples
from sphcal.features.depth_features import temporal_mean_points
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
    """Multipliers 10^g applied to each term's smoothing vector, searched term by term, in
    one-decade steps from 10^-3 to 10^4. In the simulation of 2026-10-08 the search chose
    the 10^4 ceiling for the position and slope terms. Raising the ceiling to 10^6 was
    tried and withdrawn: the search then chose 10^6 and the far range got worse (probe
    spheres at 950 mm 0.106 mm against 0.072 mm), because the pose-fold score is dominated
    by the many near-range samples. The edge choice is a property of that score, not of
    the grid; see docs/design/code_design.md, section 12."""
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
        mean_xyz = temporal_mean_points(stack.xyz, stack.valid, params.samples.min_temporal_valid_fraction)
        points = mean_xyz[np.isfinite(mean_xyz[..., 2])]
        center = fit_sphere_center(points, record.sphere_radius_mm, params.extrinsic.sphere_fit)
        centers_sensor.append(center)
        centers_positioner.append(record.target_pose_positioner.translation)
    if len(centers_sensor) < params.extrinsic.min_sphere_poses:
        raise ValueError("not enough sphere poses to solve the sensor-to-positioner transform")
    return solve_sensor_to_positioner(np.array(centers_sensor), np.array(centers_positioner),
                                      params=params.extrinsic.transform_solve)




def select_smoothing_by_pose_cv(model: SumOfTermsSpline, samples: SampleTable, selection: SmoothingSelection,
                                system: FixedDesignSystem | None = None) -> SumOfTermsSpline:
    """
    Choose each term's smoothing multiplier by K-fold cross-validation with
    whole poses held out: for each term in turn and each grid value, the
    penalized least-squares fit on the other folds is scored by its weighted
    mean squared residual on the held fold; the multiplier with the smallest
    score is kept. All fits share the fixed design through per-fold Gram
    matrices (fast_solve.PoseFoldCrossValidator), so one score costs one sparse
    factorization per fold.
    """
    rng = np.random.default_rng(selection.seed)
    n_poses = len(samples.pose_ids)
    fold_of_pose = rng.permutation(n_poses) % selection.folds
    fold = fold_of_pose[samples.pose_index]
    system = system or FixedDesignSystem(model.design(samples.inputs), samples.weight)
    validator = PoseFoldCrossValidator(system, samples.target, fold)
    grid = selection.grid
    multipliers = np.logspace(grid.log10_min, grid.log10_max, grid.n_values)
    base = [list(term.smoothing) for term in model.terms]
    chosen = [1.0] * len(model.terms)
    for _ in range(grid.n_rounds):
        for t_index, term in enumerate(model.terms):
            best_score, best_multiplier = np.inf, chosen[t_index]
            for multiplier in multipliers:
                term.smoothing = [b * multiplier for b in base[t_index]]
                score = validator.score(model.penalty())
                if score < best_score:
                    best_score, best_multiplier = score, multiplier
            chosen[t_index] = best_multiplier
            term.smoothing = [b * best_multiplier for b in base[t_index]]
    model.metadata["smoothing_multipliers"] = {term.name: float(m) for term, m in zip(model.terms, chosen)}
    return model


def _fit_model_on(samples: SampleTable, model: SumOfTermsSpline, params: CorrectionFitParameters,
                  select_smoothing: bool) -> SumOfTermsSpline:
    """S3 for callers without a fixed-design system: the penalized robust fit, with an optional smoothing search."""
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
    """
    Run S1 to S4 and evaluate on the held-out poses.

    The design matrix is built once from the measured inputs of the training
    samples; the alternation only re-targets the same rows under each new
    transform and re-solves on the fixed design (fast_solve.FixedDesignSystem).
    """
    training_ids, holdout_ids = split_poses(capture_set, params.holdout)
    training_set = subset_capture_set(capture_set, training_ids)
    transform = sensor_to_positioner or initial_transform(training_set, training_ids, params)
    first_stack = training_set.load_stack(training_ids[0])
    camera = first_stack.camera
    width, height = camera.width, camera.height
    samples = build_correction_samples(training_set, transform, params.samples)
    model = build_model(params.model, samples.inputs, width, height,
                        metadata={"gauge": "sensor frame; the map's rigid component is folded into the transform"},
                        camera=camera)
    system = FixedDesignSystem(model.design(samples.inputs), samples.weight)
    if params.smoothing.method == "pose_cv":
        model = select_smoothing_by_pose_cv(model, samples, params.smoothing, system)
    elif params.smoothing.method == "gcv":
        model = select_smoothing_by_gcv(model, samples.inputs, samples.target, samples.weight, params.smoothing.grid)
    penalty = model.penalty()
    huber = HuberParameters(params.robust.huber_delta_in_sigmas, params.robust.max_iterations,
                            params.robust.convergence_tolerance)
    rounds: list[AlternationRound] = []
    robust_weights = None
    for round_index in range(params.extrinsic.max_alternation_rounds):
        fit = system.robust_solve(samples.target, penalty, huber, robust_weights)
        robust_weights = fit.robust_weights
        model.coefficients = fit.coefficients
        delta = system.design @ fit.coefficients
        t_rigid, omega_rigid = rigid_component_of_displacements(samples.measured_point,
                                                                samples.ray_direction * delta[:, None],
                                                                samples.weight * robust_weights)
        # Gauge (D-1): the map must carry no rigid motion. Its best-fitting rigid
        # component G (p -> p + t + omega x p) is folded into the transform, the
        # targets are rebuilt under transform o G, and the next fit no longer
        # needs that component. The fixed point is G = identity.
        rigid_part = RigidTransform.from_rotation_vector_degrees(np.degrees(omega_rigid), t_rigid)
        new_transform = transform.compose(rigid_part)
        dt, drot = new_transform.difference_from(transform)
        rounds.append(AlternationRound(round_index, new_transform, dt, drot, fit.weighted_residual_rms,
                                       t_rigid, np.degrees(omega_rigid)))
        transform = new_transform
        samples = retarget_samples(samples, training_set, camera, transform, params.samples)
        if dt < params.extrinsic.convergence_translation_mm and drot < params.extrinsic.convergence_rotation_deg:
            break
    fit = system.robust_solve(samples.target, penalty, huber, robust_weights, compute_edof=True)
    model.coefficients = fit.coefficients
    model.metadata["effective_degrees_of_freedom"] = fit.effective_degrees_of_freedom
    model.metadata["retarget_misses_last_round"] = samples.retarget_misses
    holdout_samples = None
    before = after = None
    if holdout_ids:
        holdout_samples = build_correction_samples(subset_capture_set(capture_set, holdout_ids), transform, params.samples)
        residual_before = holdout_samples.target
        residual_after = holdout_samples.target - model.evaluate(holdout_samples.inputs)
        before = float(np.sqrt(np.average(residual_before ** 2, weights=holdout_samples.weight)))
        after = float(np.sqrt(np.average(residual_after ** 2, weights=holdout_samples.weight)))
    return CorrectionFitResult(model, transform, training_ids, holdout_ids, rounds, samples, holdout_samples, before, after)
