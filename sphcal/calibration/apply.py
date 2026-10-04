"""
Applying a fitted correction map to a depth frame: the reference evaluator
that the later Lisp implementation must reproduce.

For every valid native pixel: assemble the six inputs from the frame (pixel
coordinates, measured range, slope components from the configured window,
and the caller's curvature estimate), evaluate the map, add the correction to
the range along the pixel ray, and rebuild the point. Normals, if wanted, are
re-estimated on the corrected points by the downstream estimator.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sphcal.features.depth_features import SlopeParameters, image_slopes, range_from_depth
from sphcal.geometry.camera import PinholeCamera
from sphcal.spline.model import SumOfTermsSpline


@dataclass
class CorrectedFrame:
    xyz: np.ndarray            # (H, W, 3) corrected points; zeros where the input was invalid
    delta_range: np.ndarray    # (H, W) correction applied, NaN where not applied
    valid: np.ndarray          # (H, W) pixels that were corrected


def correct_frame(xyz: np.ndarray, valid: np.ndarray, camera: PinholeCamera, model: SumOfTermsSpline,
                  slope_params: SlopeParameters, curvature_per_mm: np.ndarray | float = 0.0) -> CorrectedFrame:
    """Correct one frame. curvature_per_mm may be a scalar or a per-pixel image."""
    depth = np.where(valid, xyz[..., 2].astype(np.float64), np.nan)
    measured_range = range_from_depth(depth, camera)
    slope_u, slope_v = image_slopes(depth, valid, camera, slope_params)
    usable = valid & np.isfinite(slope_u) & np.isfinite(slope_v) & np.isfinite(measured_range)
    u_grid, v_grid = camera.pixel_grid()
    curvature = np.broadcast_to(np.asarray(curvature_per_mm, dtype=np.float64), depth.shape)
    sel = np.nonzero(usable)
    inputs = np.column_stack([u_grid[sel], v_grid[sel], measured_range[sel], slope_u[sel], slope_v[sel], curvature[sel]])
    delta = np.full(depth.shape, np.nan)
    delta[sel] = model.evaluate(inputs)
    rays = camera.ray_directions()
    corrected_range = np.where(usable, measured_range + delta, np.nan)
    corrected = np.where(usable[..., None], rays * corrected_range[..., None], 0.0)
    return CorrectedFrame(corrected.astype(np.float64), delta, usable)
