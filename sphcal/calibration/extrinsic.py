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

import numpy as np

from sphcal.geometry.transforms import RigidTransform, fit_rigid_transform

ALGEBRAIC_FIT_MIN_POINTS = 4
"""An algebraic sphere fit with known radius has three unknowns (the center)
plus one auxiliary; fewer points than this cannot determine it."""


MEDIAN_ABSOLUTE_DEVIATION_TO_SIGMA = 1.4826
"""Factor converting a median absolute deviation into a Gaussian sigma."""


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
        keep = np.ones(p.shape[0], dtype=bool)
        center = algebraic_sphere_center(p, radius_mm, base_weights)
        for _ in range(params.trimming_rounds):
            residual = np.linalg.norm(p - center, axis=1) - radius_mm
            scale = MEDIAN_ABSOLUTE_DEVIATION_TO_SIGMA * np.median(np.abs(residual[keep] - np.median(residual[keep])))
            scale = max(scale, params.convergence_mm)
            new_keep = np.abs(residual - np.median(residual[keep])) <= params.trimming_sigma_multiple * scale
            if new_keep.sum() < params.min_points or np.array_equal(new_keep, keep):
                break
            keep = new_keep
            center = algebraic_sphere_center(p[keep], radius_mm, base_weights[keep])
        base_weights = np.where(keep, base_weights, 0.0)
    else:
        center = np.asarray(initial_center, dtype=np.float64)
    for _ in range(params.max_iterations):
        offsets = p - center
        distances = np.linalg.norm(offsets, axis=1)
        residual = distances - radius_mm
        huber = np.where(np.abs(residual) <= params.huber_delta_mm, 1.0,
                         params.huber_delta_mm / np.maximum(np.abs(residual), params.huber_delta_mm))
        w = base_weights * huber
        jacobian = -offsets / np.maximum(distances, 1e-12)[:, None]
        normal_matrix = (jacobian * w[:, None]).T @ jacobian
        gradient = (jacobian * w[:, None]).T @ residual
        step = np.linalg.solve(normal_matrix, -gradient)
        center = center + step
        if np.linalg.norm(step) < params.convergence_mm:
            break
    return center


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
