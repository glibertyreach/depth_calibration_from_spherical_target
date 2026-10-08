"""
Applying a fitted correction map to a depth frame: the reference evaluator
that the later Lisp implementation must reproduce.

For every valid native pixel: assemble the six inputs from the frame (pixel
coordinates, measured range, slope components from the configured window,
and the measurement-space curvature), evaluate the map, add the correction to
the range along the pixel ray, and rebuild the point. Normals, if wanted, are
re-estimated on the corrected points by the downstream estimator.

Curvature convention. Callers give the PHYSICAL curvature 1 / R in 1/mm (0 for
a plane, or when unknown), as a scalar or a per-pixel image. The map's sixth
input is the measurement-space curvature kappa_m = (range / f_mean)^2 / R in
mm/px^2, so this module converts it per pixel with that pixel's own measured
range and the camera's mean focal length sqrt(fx * fy), exactly as the sample
builder does at calibration time and as the runtime evaluator must.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sphcal.features.depth_features import SlopeParameters, image_slopes, measurement_space_curvature, range_from_depth
from sphcal.geometry.camera import PinholeCamera
from sphcal.spline.model import SumOfTermsSpline


@dataclass
class CorrectedFrame:
    xyz: np.ndarray            # (H, W, 3) corrected points; zeros where the input was invalid
    delta_range: np.ndarray    # (H, W) correction applied, NaN where not applied
    valid: np.ndarray          # (H, W) pixels that were corrected


def correct_frame(xyz: np.ndarray, valid: np.ndarray, camera: PinholeCamera, model: SumOfTermsSpline,
                  slope_params: SlopeParameters, curvature_per_mm: np.ndarray | float = 0.0) -> CorrectedFrame:
    """
    Correct one frame. curvature_per_mm is the PHYSICAL curvature 1 / R in 1/mm
    (0 for a plane or when unknown), a scalar or a per-pixel (H, W) image; it is
    converted inside, per pixel, to the map's measurement-space curvature
    (range / f_mean)^2 * curvature_per_mm in mm/px^2 using the pixel's measured
    range (see measurement_space_curvature).
    """
    depth = np.where(valid, xyz[..., 2].astype(np.float64), np.nan)
    measured_range = range_from_depth(depth, camera)
    slope_u, slope_v = image_slopes(depth, valid, camera, slope_params)
    usable = valid & np.isfinite(slope_u) & np.isfinite(slope_v) & np.isfinite(measured_range)
    u_grid, v_grid = camera.pixel_grid()
    physical_curvature = np.broadcast_to(np.asarray(curvature_per_mm, dtype=np.float64), depth.shape)
    sel = np.nonzero(usable)
    curvature_mm_per_px2 = measurement_space_curvature(physical_curvature[sel], measured_range[sel], camera.mean_focal_px)
    inputs = np.column_stack([u_grid[sel], v_grid[sel], measured_range[sel], slope_u[sel], slope_v[sel],
                              curvature_mm_per_px2])
    delta = np.full(depth.shape, np.nan)
    delta[sel] = model.evaluate(inputs)
    rays = camera.ray_directions()
    corrected_range = np.where(usable, measured_range + delta, np.nan)
    corrected = np.where(usable[..., None], rays * corrected_range[..., None], 0.0)
    return CorrectedFrame(corrected.astype(np.float64), delta, usable)
