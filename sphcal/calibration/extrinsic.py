"""
The sensor-to-positioner transform: sphere center fitting in the sensor frame,
the rigid solve against commanded centers, and the alternation with the
correction map (steps S1 and S4 of the analysis).

Gauge (decision D-1): the corrected output lives in the sensor frame, so the
correction map must carry no rigid motion. Re-solving the transform from the
centers of the CORRECTED points after each map fit is what enforces that: any
rigid component the map picks up shifts the fitted centers, the transform
absorbs it, the targets move, and the next map fit no longer needs it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from sphcal.geometry.transforms import RigidTransform, fit_rigid_transform

ALGEBRAIC_FIT_MIN_POINTS = 4
"""An algebraic sphere fit with known radius has three unknowns (the center)
plus one auxiliary; fewer points than this cannot determine it."""


MEDIAN_ABSOLUTE_DEVIATION_TO_SIGMA = 1.4826
"""Factor converting a median absolute deviation into a Gaussian sigma."""

MINIMUM_DISTANCE_MM = 1.0e-12
"""Guard against division by zero for a point lying exactly at a trial center;
far below any physical distance, so it never changes a real fit."""


@dataclass(frozen=True)
class SphereFitParameters:
    max_iterations: int = 20
    """Gauss-Newton iterations on the geometric residual |p - c| - R."""
    convergence_mm: float = 1.0e-4
    """Stop when the center moves less than this between iterations."""
    huber_delta_mm: float = 1.0
    """Residuals beyond this get a Huber down-weighting; mixed pixels and
    specular points are the targets of this."""
    trimming_rounds: int = 3
    """Rounds of algebraic fit, residual scale estimate, and removal of gross
    outliers before the geometric fit starts. Flying pixels at a sphere's limb
    can be hundreds of millimeters off and would otherwise ruin the start."""
    trimming_sigma_multiple: float = 5.0
    """A point whose algebraic residual exceeds this multiple of the robust
    residual scale (median absolute deviation times the Gaussian factor) is
    removed during trimming."""
    min_points: int = 12
    """Fewer points than this and the fit is refused (returns NaN center)."""


@dataclass(frozen=True)
class TransformSolveParameters:
    max_center_residual_mm: float = 2.0
    """A sphere pose whose fitted center disagrees with the solved transform by
    more than this is dropped and the transform re-solved; such a pose is a
    failed fit or a wrong commanded position, not a calibration signal."""
    max_rounds: int = 3
    """Rounds of solve, gate, re-solve."""


@dataclass(frozen=True)
class ExtrinsicParameters:
    sphere_fit: SphereFitParameters = SphereFitParameters()
    transform_solve: TransformSolveParameters = TransformSolveParameters()
    min_sphere_poses: int = 3
    """A rigid transform needs at least three non-collinear sphere centers."""
    max_alternation_rounds: int = 12
    """Rounds of (fit map, fold its rigid component into the transform, rebuild
    targets); the transform change contracts by roughly half per round."""
    convergence_translation_mm: float = 0.005
    convergence_rotation_deg: float = 0.002
    """The alternation stops when the transform changes by less than both."""


def algebraic_sphere_center(points: np.ndarray, radius_mm: float, weights: np.ndarray | None = None) -> np.ndarray:
    """
    Linear least-squares center of a sphere of known radius through points:
    |p|^2 - 2 p.c + (|c|^2 - R^2) = 0 is linear in (c, k) with k = |c|^2 - R^2.
    Used only to start the geometric fit.
    """
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if p.shape[0] < ALGEBRAIC_FIT_MIN_POINTS:
        raise ValueError("too few points for a sphere fit")
    w = np.ones(p.shape[0]) if weights is None else np.sqrt(np.asarray(weights, dtype=np.float64))
    design = np.column_stack([-2.0 * p, np.ones(p.shape[0])]) * w[:, None]
    rhs = -(p ** 2).sum(axis=1) * w
    solution, *_ = np.linalg.lstsq(design, rhs, rcond=None)
    return solution[:3]


def algebraic_sphere_center_and_radius(points: np.ndarray, weights: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """
    Linear least-squares center AND radius of a sphere through points:
    |p|^2 = 2 p.c + k is linear in (c, k) with k = R^2 - |c|^2, so R^2 = k + |c|^2.
    Used only to start the free-radius geometric fit.

    The points are shifted to their weighted centroid before solving and the
    center is shifted back afterwards: a sensor sees a sphere hundreds of
    millimeters away, so without the shift |c|^2 dwarfs R^2 and the unknown k
    is a small difference of large numbers. The shift does not change the
    solution, only its conditioning.

    Returns (center, NaN) when the fitted R^2 is not positive (a degenerate
    point set), which the callers treat as a refused fit.
    """
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if p.shape[0] < ALGEBRAIC_FIT_MIN_POINTS:
        raise ValueError("too few points for a sphere fit")
    w = np.ones(p.shape[0]) if weights is None else np.asarray(weights, dtype=np.float64)
    centroid = np.average(p, axis=0, weights=w)
    shifted = p - centroid
    sqrt_w = np.sqrt(w)
    design = np.column_stack([2.0 * shifted, np.ones(p.shape[0])]) * sqrt_w[:, None]
    rhs = (shifted ** 2).sum(axis=1) * sqrt_w
    solution, *_ = np.linalg.lstsq(design, rhs, rcond=None)
    center_shifted, k = solution[:3], solution[3]
    radius_squared = k + float(center_shifted @ center_shifted)
    radius = float(np.sqrt(radius_squared)) if radius_squared > 0.0 else float("nan")
    return center_shifted + centroid, radius


def _trimmed_algebraic_start(p: np.ndarray, base_weights: np.ndarray, params: SphereFitParameters,
                             algebraic_fit: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, float]]
                             ) -> tuple[np.ndarray, float, np.ndarray]:
    """
    Robust algebraic start shared by the known-radius and free-radius fits.
    `algebraic_fit(points, weights)` returns (center, radius) -- the known
    radius simply echoed back in the known-radius case. Rounds of fit,
    robust residual scale (median absolute deviation times the Gaussian
    factor, floored at the convergence tolerance so a noiseless set does not
    trim on rounding noise) and removal of points beyond
    trimming_sigma_multiple scales remove gross outliers such as flying
    pixels before the geometric refinement begins.

    Returns (center, radius, keep) with `keep` the boolean mask of surviving
    points; at least params.min_points survive.
    """
    keep = np.ones(p.shape[0], dtype=bool)
    center, radius = algebraic_fit(p, base_weights)
    for _ in range(params.trimming_rounds):
        residual = np.linalg.norm(p - center, axis=1) - radius
        scale = MEDIAN_ABSOLUTE_DEVIATION_TO_SIGMA * np.median(np.abs(residual[keep] - np.median(residual[keep])))
        scale = max(scale, params.convergence_mm)
        new_keep = np.abs(residual - np.median(residual[keep])) <= params.trimming_sigma_multiple * scale
        if new_keep.sum() < params.min_points or np.array_equal(new_keep, keep):
            break
        keep = new_keep
        center, radius = algebraic_fit(p[keep], base_weights[keep])
    return center, radius, keep


def _huber_weights(residual: np.ndarray, params: SphereFitParameters) -> np.ndarray:
    """Huber down-weighting: 1 inside huber_delta_mm, delta / |residual| beyond."""
    return np.where(np.abs(residual) <= params.huber_delta_mm, 1.0,
                    params.huber_delta_mm / np.maximum(np.abs(residual), params.huber_delta_mm))


def fit_sphere_center(points: np.ndarray, radius_mm: float, params: SphereFitParameters,
                      weights: np.ndarray | None = None, initial_center: np.ndarray | None = None) -> np.ndarray:
    """
    Center of a sphere of known radius minimizing the (Huber-weighted) sum of
    squared geometric distances |p - c| - R. Gauss-Newton with the exact
    Jacobian of the distance, d|p - c|/dc = -(p - c)/|p - c|.
    """
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    base_weights = np.ones(p.shape[0]) if weights is None else np.asarray(weights, dtype=np.float64)
    if p.shape[0] < params.min_points:
        return np.full(3, np.nan)
    if initial_center is None:
        # Trimmed algebraic start: gross outliers (flying pixels) are removed
        # by a robust scale test before the geometric refinement begins.
        center, _, keep = _trimmed_algebraic_start(
            p, base_weights, params,
            lambda pts, w: (algebraic_sphere_center(pts, radius_mm, w), radius_mm))
        base_weights = np.where(keep, base_weights, 0.0)
    else:
        center = np.asarray(initial_center, dtype=np.float64)
    for _ in range(params.max_iterations):
        offsets = p - center
        distances = np.linalg.norm(offsets, axis=1)
        residual = distances - radius_mm
        w = base_weights * _huber_weights(residual, params)
        jacobian = -offsets / np.maximum(distances, MINIMUM_DISTANCE_MM)[:, None]
        normal_matrix = (jacobian * w[:, None]).T @ jacobian
        gradient = (jacobian * w[:, None]).T @ residual
        step = np.linalg.solve(normal_matrix, -gradient)
        center = center + step
        if np.linalg.norm(step) < params.convergence_mm:
            break
    return center


def fit_sphere_free_radius(points: np.ndarray, params: SphereFitParameters) -> tuple[np.ndarray, float, float]:
    """
    Center AND radius of a sphere through points, with the radius free:
    the robust shape check that does not depend on any commanded pose.

    Algebraic start (|p|^2 = 2 p.c + k, k = R^2 - |c|^2) with the same robust
    trimming scheme as fit_sphere_center, then Gauss-Newton over (c, R) on the
    Huber-weighted geometric residual |p - c| - R, whose Jacobian rows are
    (-(p - c)/|p - c|, -1). max_iterations and convergence_mm (applied to the
    norm of the whole (c, R) step) are those of the known-radius fit.

    Because the algebraic fit of a cap with unknown radius is ill-conditioned,
    a few percent of gross outliers can leave some of them past the algebraic
    trimming (the start radius can be off by tens of millimeters). The
    geometric fit is far better anchored, so the same trimming test is then
    repeated on ITS residuals, refitting after each round, for at most
    trimming_rounds rounds or until no point changes.

    Conditioning: a sensor sees only a cap of the sphere (incidence up to
    about 55 degrees), over which the radius and the center's along-view
    coordinate are strongly correlated (a bigger sphere further away looks
    alike). The fit is still well posed with thousands of points, but a small
    radius error should not be read as independent of a center shift along the
    view ray.

    Returns (center, radius, rms_residual_mm), the RMS being of the geometric
    residual over the points surviving trimming (unweighted by Huber, so it
    reports the actual shape error). Returns (NaN center, NaN, NaN) when fewer
    than params.min_points points are given or survive, or the fit degenerates.
    """
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    refused = (np.full(3, np.nan), float("nan"), float("nan"))
    if p.shape[0] < params.min_points:
        return refused
    center, radius, keep = _trimmed_algebraic_start(p, np.ones(p.shape[0]), params, algebraic_sphere_center_and_radius)
    if not np.isfinite(radius):
        return refused

    def gauss_newton(q: np.ndarray, center: np.ndarray, radius: float) -> tuple[np.ndarray, float] | None:
        """Huber-weighted Gauss-Newton on (c, R) over q; None if the normal equations are singular."""
        for _ in range(params.max_iterations):
            offsets = q - center
            distances = np.linalg.norm(offsets, axis=1)
            residual = distances - radius
            w = _huber_weights(residual, params)
            jacobian = np.column_stack([-offsets / np.maximum(distances, MINIMUM_DISTANCE_MM)[:, None], -np.ones(q.shape[0])])
            normal_matrix = (jacobian * w[:, None]).T @ jacobian
            gradient = (jacobian * w[:, None]).T @ residual
            try:
                step = np.linalg.solve(normal_matrix, -gradient)
            except np.linalg.LinAlgError:
                return None
            center = center + step[:3]
            radius = radius + step[3]
            if np.linalg.norm(step) < params.convergence_mm:
                break
        return center, float(radius)

    # One fit on the algebraic survivors, then up to trimming_rounds rounds of re-trim and refit.
    for _ in range(params.trimming_rounds + 1):
        fitted = gauss_newton(p[keep], center, radius)
        if fitted is None:
            return refused
        center, radius = fitted
        residual = np.linalg.norm(p - center, axis=1) - radius
        median = np.median(residual[keep])
        scale = MEDIAN_ABSOLUTE_DEVIATION_TO_SIGMA * np.median(np.abs(residual[keep] - median))
        scale = max(scale, params.convergence_mm)
        new_keep = np.abs(residual - median) <= params.trimming_sigma_multiple * scale
        if new_keep.sum() < params.min_points or np.array_equal(new_keep, keep):
            break
        keep = new_keep
    final_residual = np.linalg.norm(p[keep] - center, axis=1) - radius
    return center, radius, float(np.sqrt(np.mean(final_residual ** 2)))


def free_radius_standard_error(points: np.ndarray, center: np.ndarray, radius: float, rms_residual_mm: float) -> float:
    """
    Standard error of the radius from fit_sphere_free_radius, from the
    Gauss-Newton covariance rms^2 (J^T J)^-1 of the (c, R) fit, J's rows being
    (-(p - c)/|p - c|, -1). On a small cap the radius is strongly correlated
    with the center's along-view coordinate, so this error grows quickly as the
    cap's point count or angular width shrinks; the report prints it next to
    each fitted radius so that a radius error can be judged against it. Pass
    the points the fit kept (or all points, when outliers are few). Returns NaN
    for a refused fit or a singular normal matrix.
    """
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if not (np.isfinite(radius) and np.isfinite(rms_residual_mm)) or p.shape[0] < ALGEBRAIC_FIT_MIN_POINTS:
        return float("nan")
    offsets = p - np.asarray(center, dtype=np.float64)
    distances = np.linalg.norm(offsets, axis=1)
    jacobian = np.column_stack([-offsets / np.maximum(distances, MINIMUM_DISTANCE_MM)[:, None], -np.ones(p.shape[0])])
    try:
        covariance = np.linalg.inv(jacobian.T @ jacobian) * rms_residual_mm ** 2
    except np.linalg.LinAlgError:
        return float("nan")
    return float(np.sqrt(covariance[3, 3]))


def solve_sensor_to_positioner(centers_sensor: np.ndarray, centers_positioner: np.ndarray,
                               weights: np.ndarray | None = None,
                               params: TransformSolveParameters = TransformSolveParameters()) -> RigidTransform:
    """
    Rigid transform mapping sensor-frame centers onto commanded positioner-frame
    centers, with poses whose center residual exceeds the gate dropped and the
    solve repeated. Poses with a NaN center (refused fits) are ignored.
    """
    source = np.asarray(centers_sensor, dtype=np.float64).reshape(-1, 3)
    target = np.asarray(centers_positioner, dtype=np.float64).reshape(-1, 3)
    w = np.ones(source.shape[0]) if weights is None else np.asarray(weights, dtype=np.float64)
    keep = np.isfinite(source).all(axis=1)
    transform = None
    for _ in range(params.max_rounds):
        if keep.sum() < 3:
            raise ValueError("fewer than three usable sphere centers for the transform solve")
        transform = fit_rigid_transform(source[keep], target[keep], w[keep])
        residual = np.linalg.norm(transform.apply_points(source) - target, axis=1)
        new_keep = keep & (residual <= params.max_center_residual_mm)
        if np.array_equal(new_keep, keep):
            break
        keep = new_keep
    return transform


def rigid_component_of_displacements(points: np.ndarray, displacements: np.ndarray,
                                     weights: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """
    The small rigid motion (translation t, rotation vector omega in radians)
    that best explains a displacement field, d_i ~ t + omega x p_i, in the
    weighted least-squares sense. Reported as a diagnostic of how much rigid
    motion the correction map still carries after the alternation.
    """
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    d = np.asarray(displacements, dtype=np.float64).reshape(-1, 3)
    w = np.ones(p.shape[0]) if weights is None else np.asarray(weights, dtype=np.float64)
    # omega x p = -[p]_x omega, with [p]_x the cross-product matrix.
    cross = np.zeros((p.shape[0], 3, 3))
    cross[:, 0, 1], cross[:, 0, 2] = -p[:, 2], p[:, 1]
    cross[:, 1, 0], cross[:, 1, 2] = p[:, 2], -p[:, 0]
    cross[:, 2, 0], cross[:, 2, 1] = -p[:, 1], p[:, 0]
    design = np.concatenate([np.tile(np.eye(3), (p.shape[0], 1, 1)), -cross], axis=2).reshape(-1, 6)
    sqrt_w = np.repeat(np.sqrt(w), 3)
    solution, *_ = np.linalg.lstsq(design * sqrt_w[:, None], d.reshape(-1) * sqrt_w, rcond=None)
    return solution[:3], solution[3:]
