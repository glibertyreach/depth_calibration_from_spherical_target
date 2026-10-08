"""
Synthetic captures of spheres and boards with a known injected range error.

Purpose: test the fitting code end to end. The injected error is a known
function of the map inputs (u, v, rho, s_u, s_v, curvature) of the design
document (section 4), so a correct fit must recover it. The "curvature" given
to the injected field is the PHYSICAL curvature 1/R (0 on boards); the map's
sixth input is the measurement-space curvature (range / f)^2 / R, so the map
recovers the injected curvature term through its range axis. The generator also
imitates the main gross features of the real sensor (effective resolution
coarser than the pixel grid, depth noise growing with depth squared and with
incidence, no-reads at grazing incidence, an optional fixed pattern) so that
the fit is exercised on data with realistic statistics. These sensor-like
features are INDICATIVE only; the fit must not rely on them (design document,
section 1).

Rendering pipeline for one frame (all distances in mm, sensor frame):

1. For every native pixel, intersect the pixel ray exactly with the target.
2. True range rho, true cosine of incidence, and true slope inputs s_u, s_v
   follow analytically from the true surface normal (see "Slope inputs").
3. The injected error field, evaluated at the true inputs, is added to rho.
4. The range is converted to camera-z depth.
5. The effective resolution is imposed: z is averaged over
   effective_block_px x effective_block_px blocks of valid pixels and the block
   values are interpolated bilinearly back to the native grid, with weights
   proportional to each block's valid count (blocks without valid pixels
   contribute nothing).
6. Noise is drawn once per block with sigma = k z_block^2 cos(alpha_block)^(-m)
   and interpolated back the same way; the optional fixed pattern (a per-block
   random offset, identical in every frame) is added likewise.
7. The no-read decision is drawn once per block with read probability
   1 / (1 + exp((alpha_deg - onset) / width)).
8. Pixels that are not hit or not read get the zero sentinel in all three XYZ
   components; otherwise XYZ is the unit ray times the final range, so x and y
   are consistent with the final z.

Slope inputs. The map inputs s_u, s_v are the dimensionless slopes of the
measured surface, s_u = dz/du * f_x / z and s_v = dz/dv * f_y / z (design
document, section 4), positive where depth increases toward larger u (right)
and larger v (down). For the true surface they are defined from the outward
unit normal n (pointing toward the camera, so n . (-d) > 0), the unit ray d
(pointing away from the camera) and e_u, e_v, the camera x and y axes (the
directions of increasing image u and v):

    s_u = (n . e_u) * d_z / (n . (-d)),    s_v = (n . e_v) * d_z / (n . (-d))

with d_z the z component of the unit ray. Derivation: along the unnormalized
ray r = d / d_z = (x/z, y/z, 1), the depth where the ray meets the tangent
plane n . (p - p0) = 0 is z = (n . p0) / (n . r); differentiating with respect
to the normalized image coordinate u' = (u - c_x) / f_x gives
dz/du' = -z (n . e_u) / (n . r), hence dz/du * f_x / z = (n . e_u) d_z / (n . (-d)).
This is EXACTLY the measured estimator's quantity for a locally planar
surface, so the injected field is a function of the same inputs the fit
indexes. Check: a plane z = z0 + m x has the camera-facing normal
proportional to (m, 0, -1) and gives s_u = m on the optical axis.
Incidence is cos(alpha) = n . (-d).

Units: millimeters, degrees at public interfaces, pixels for image coordinates.
Image arrays are (height, width); pixel (u, v) = (column, row).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from scipy.special import expit

from sphcal.geometry.camera import PinholeCamera
from sphcal.geometry.transforms import RigidTransform
from sphcal.io.capture_set import XYZ_CHANNEL_NAME
from sphcal.io.matcloud import write_matcloud
from sphcal.io.poses import (
    CaptureRecord, TARGET_KIND_BOARD, TARGET_KIND_SPHERE, write_manifest_json,
)

# ---------------------------------------------------------------------------
# Indicative sensor values (VSX3000 specification; not used by the fit)
# ---------------------------------------------------------------------------
INDICATIVE_IMAGE_WIDTH_PX = 640
"""Indicative sensor image width in pixels (specification)."""
INDICATIVE_IMAGE_HEIGHT_PX = 480
"""Indicative sensor image height in pixels (specification)."""
INDICATIVE_FOCAL_X_PX = 688.1552734375
"""Indicative focal length along u in pixels (specification)."""
INDICATIVE_FOCAL_Y_PX = 688.083251953125
"""Indicative focal length along v in pixels (specification)."""
INDICATIVE_PRINCIPAL_X_PX = 292.3155517578125
"""Indicative principal point u in pixels (specification)."""
INDICATIVE_PRINCIPAL_Y_PX = 256.7590026855469
"""Indicative principal point v in pixels (specification)."""
INDICATIVE_EFFECTIVE_BLOCK_PX = 4
"""Indicative effective resolution: independent depth values per 4 x 4 pixels."""
INDICATIVE_NOISE_COEFFICIENT_PER_MM = 1.79e-7
"""Indicative noise coefficient k in sigma_z = k z^2, in 1/mm."""
INDICATIVE_NOISE_INCIDENCE_EXPONENT = 1.3
"""Indicative exponent m of the incidence multiplier cos(alpha)^(-m)."""
INDICATIVE_NOREAD_ONSET_DEG = 55.0
"""Indicative incidence at which the read probability is 50 percent."""
INDICATIVE_NOREAD_WIDTH_DEG = 5.0
"""Indicative logistic width of the read probability in incidence, degrees."""

# ---------------------------------------------------------------------------
# Default injected error field (deliberately NOT a physical model)
# ---------------------------------------------------------------------------
BOWL_AMPLITUDE_MM = 0.6
"""A: amplitude of the bowl term A ((u-cx)^2/cx^2 + (v-cy)^2/cy^2)(rho/rho_ref)^2, mm."""
BOWL_REFERENCE_RANGE_MM = 1000.0
"""rho_ref: range at which the bowl term has its nominal amplitude, mm."""
BOWL_CENTER_U_PX = INDICATIVE_PRINCIPAL_X_PX
"""cx of the bowl term: the u pixel where the bowl is zero (and its u scale), px."""
BOWL_CENTER_V_PX = INDICATIVE_PRINCIPAL_Y_PX
"""cy of the bowl term: the v pixel where the bowl is zero (and its v scale), px."""
SLOPE_QUADRATIC_AMPLITUDE_MM = 0.3
"""B: amplitude of the slope term B (s_u^2 + s_v^2), mm."""
SLOPE_ASYMMETRIC_AMPLITUDE_MM = 0.15
"""C: amplitude of the asymmetric slope term C s_u, mm."""
CURVATURE_AMPLITUDE_MM2 = 20.0
"""D: coefficient of the curvature term D * curvature, mm^2 (0.4 mm at R = 50 mm)."""

DEFAULT_ERROR_FIELD_DESCRIPTION = (
    "A*((u-cx)^2/cx^2+(v-cy)^2/cy^2)*(rho/rho_ref)^2 + B*(s_u^2+s_v^2) + C*s_u + D*curvature; "
    f"A={BOWL_AMPLITUDE_MM} mm, rho_ref={BOWL_REFERENCE_RANGE_MM} mm, cx={BOWL_CENTER_U_PX} px, "
    f"cy={BOWL_CENTER_V_PX} px, B={SLOPE_QUADRATIC_AMPLITUDE_MM} mm, C={SLOPE_ASYMMETRIC_AMPLITUDE_MM} mm, "
    f"D={CURVATURE_AMPLITUDE_MM2} mm^2; units: mm added to the range; deliberately not a physical model"
)
"""Human-readable description of :func:`default_injected_error_field`, written to truth.json."""

# ---------------------------------------------------------------------------
# Numerical guards and file-format constants
# ---------------------------------------------------------------------------
MINIMUM_NOISE_COSINE = 1e-3
"""Floor on cos(alpha) in the noise multiplier cos^(-m), to avoid division by zero."""
PLANE_PARALLEL_TOLERANCE = 1e-9
"""Rays with -n.d below this are treated as parallel to (or behind) a board plane."""
WEIGHT_SUM_TOLERANCE = 1e-12
"""Interpolation weight sums below this count as 'no valid block nearby'."""
SYNTHETIC_CAMERA_NAME = "synthetic"
"""Value of the header key cameraName in synthetic files."""
SYNTHETIC_HEADER_VERSION = 2
"""Value of the header key version in synthetic files (matches real files)."""
POSE_ID_FORMAT = "pose{index:04d}"
"""Pose id format of the synthetic dataset."""
FILE_NAME_FORMAT = "{pose_id}_Index{frame:02d}.mc"
"""File name format of the synthetic dataset."""
MANIFEST_FILE_NAME = "manifest.json"
"""Name of the manifest written by write_synthetic_dataset."""
TRUTH_FILE_NAME = "truth.json"
"""Name of the truth file written by write_synthetic_dataset."""
HEADER_POSE_KEY = "robotPose"
"""Header key of the target pose written to each file."""


# ---------------------------------------------------------------------------
# Parameters and result containers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SyntheticSensorParameters:
    """Sensor-like behavior of the generator. See the module docstring."""

    camera: PinholeCamera
    effective_block_px: int                   # independent depth values per block x block pixels
    noise_coefficient_per_mm: float           # k in sigma_z = k z^2 per block (1/mm)
    noise_incidence_exponent: float           # m in the multiplier cos(alpha)^(-m)
    noread_onset_deg: float                   # incidence with 50 % read probability
    noread_width_deg: float                   # logistic width in degrees
    fixed_pattern_amplitude_mm: float         # amplitude of the per-block fixed pattern, 0 disables
    fixed_pattern_seed: int                   # seed of the fixed pattern (same in every frame)

    @classmethod
    def vsx3000_indicative(cls) -> "SyntheticSensorParameters":
        """INDICATIVE values from the sensor specification (640 x 480, block 4,
        k = 1.79e-7 per mm, exponent 1.3, no-read onset 55 deg, width 5 deg,
        fixed pattern off, seed 0). They are NOT a model the fit relies on; they
        only make synthetic data look statistically like the real sensor."""
        camera = PinholeCamera(
            INDICATIVE_IMAGE_WIDTH_PX, INDICATIVE_IMAGE_HEIGHT_PX,
            INDICATIVE_FOCAL_X_PX, INDICATIVE_FOCAL_Y_PX,
            INDICATIVE_PRINCIPAL_X_PX, INDICATIVE_PRINCIPAL_Y_PX)
        return cls(
            camera=camera,
            effective_block_px=INDICATIVE_EFFECTIVE_BLOCK_PX,
            noise_coefficient_per_mm=INDICATIVE_NOISE_COEFFICIENT_PER_MM,
            noise_incidence_exponent=INDICATIVE_NOISE_INCIDENCE_EXPONENT,
            noread_onset_deg=INDICATIVE_NOREAD_ONSET_DEG,
            noread_width_deg=INDICATIVE_NOREAD_WIDTH_DEG,
            fixed_pattern_amplitude_mm=0.0,
            fixed_pattern_seed=0,
        )


@dataclass
class SyntheticFrame:
    """One rendered frame and its truth, all (H, W).

    xyz:                 (H, W, 3) float32, zeros where not hit or not read
    true_range:          exact range to the target, NaN where the ray misses
    true_cos_incidence:  exact cos(alpha) = n . (-d), NaN where the ray misses
    true_s_u, true_s_v:  exact slope inputs (module docstring), NaN where the ray misses
    read_mask:           True where a point was delivered (hit and read)
    hit_mask:            True where the pixel ray hits the target
    """

    xyz: np.ndarray
    true_range: np.ndarray
    true_cos_incidence: np.ndarray
    true_s_u: np.ndarray
    true_s_v: np.ndarray
    read_mask: np.ndarray
    hit_mask: np.ndarray


ErrorField = Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray], np.ndarray]
"""Signature of an injected error field: (u, v, rho, s_u, s_v, curvature) -> mm."""


# ---------------------------------------------------------------------------
# Default injected error field
# ---------------------------------------------------------------------------
def default_injected_error_field(u, v, rho, s_u, s_v, curvature) -> np.ndarray:
    """Default injected range error in mm (added to the range along the ray).

    error = A ((u-cx)^2/cx^2 + (v-cy)^2/cy^2) (rho/rho_ref)^2   (bowl)
          + B (s_u^2 + s_v^2) + C s_u                            (slope, one asymmetric part)
          + D curvature                                          (curvature)

    with the named module constants A, rho_ref, cx, cy, B, C, D. This field is
    deliberately NOT a physical model of any sensor; it is a smooth, known test
    function, chosen so that every input of the correction map matters.
    """
    return _error_field(u, v, rho, s_u, s_v, curvature, BOWL_CENTER_U_PX, BOWL_CENTER_V_PX)


default_injected_error_field.description = DEFAULT_ERROR_FIELD_DESCRIPTION  # type: ignore[attr-defined]


def _error_field(u, v, rho, s_u, s_v, curvature, center_u_px, center_v_px) -> np.ndarray:
    """Shared body of the default field, with the bowl center as arguments."""
    bowl = (BOWL_AMPLITUDE_MM
            * (((u - center_u_px) / center_u_px) ** 2 + ((v - center_v_px) / center_v_px) ** 2)
            * (rho / BOWL_REFERENCE_RANGE_MM) ** 2)
    slope = SLOPE_QUADRATIC_AMPLITUDE_MM * (s_u ** 2 + s_v ** 2) + SLOPE_ASYMMETRIC_AMPLITUDE_MM * s_u
    return bowl + slope + CURVATURE_AMPLITUDE_MM2 * curvature


def default_injected_error_field_for_camera(camera: PinholeCamera) -> ErrorField:
    """The default field with the bowl centered on and scaled by the given
    camera's principal point (useful for a small test camera whose principal
    point is not the 640 x 480 sensor's)."""
    def field_for_camera(u, v, rho, s_u, s_v, curvature):
        return _error_field(u, v, rho, s_u, s_v, curvature, camera.principal_x_px, camera.principal_y_px)
    field_for_camera.description = (  # type: ignore[attr-defined]
        DEFAULT_ERROR_FIELD_DESCRIPTION.replace(f"cx={BOWL_CENTER_U_PX} px", f"cx={camera.principal_x_px} px")
        .replace(f"cy={BOWL_CENTER_V_PX} px", f"cy={camera.principal_y_px} px"))
    return field_for_camera


def describe_error_field(error_field: ErrorField) -> str:
    """Description string of an error field: its ``description`` attribute if
    present, else the first line of its docstring, else its name."""
    description = getattr(error_field, "description", None)
    if description:
        return str(description)
    doc = getattr(error_field, "__doc__", None)
    if doc:
        return doc.strip().splitlines()[0]
    return getattr(error_field, "__name__", repr(error_field))


# ---------------------------------------------------------------------------
# Exact ray-target intersections (local, vectorized)
# ---------------------------------------------------------------------------
def _sphere_hits(ray_dirs: np.ndarray, center: np.ndarray, radius: float):
    """Near ray-sphere intersection for unit rays from the origin.
    Returns (range, hit, outward unit normal); range is NaN where no hit."""
    b = ray_dirs @ center
    discriminant = b ** 2 - (center @ center - radius ** 2)
    hit = (discriminant >= 0.0)
    near = b - np.sqrt(np.where(hit, discriminant, 0.0))
    hit &= near > 0.0
    rng_true = np.where(hit, near, np.nan)
    points = ray_dirs * np.where(hit, near, 0.0)[..., None]
    normals = (points - center) / radius
    return rng_true, hit, normals


def _board_hits(ray_dirs: np.ndarray, board_pose_sensor: RigidTransform, half_width: float, half_height: float):
    """Ray-rectangle intersection for unit rays from the origin; only the
    front face (the side the outward normal +z points to) is visible.
    Returns (range, hit, outward unit normal (broadcast))."""
    normal = board_pose_sensor.rotation[:, 2]
    origin = board_pose_sensor.translation
    facing = ray_dirs @ normal                         # n . d, negative for a front-facing hit
    front = facing < -PLANE_PARALLEL_TOLERANCE
    safe_facing = np.where(front, facing, -1.0)
    t = (normal @ origin) / safe_facing
    hit = front & (t > 0.0)
    points = ray_dirs * np.where(hit, t, 0.0)[..., None]
    local = (points - origin) @ board_pose_sensor.rotation   # board-frame coordinates R^T (p - t)
    hit &= (np.abs(local[..., 0]) <= half_width) & (np.abs(local[..., 1]) <= half_height)
    rng_true = np.where(hit, t, np.nan)
    normals = np.broadcast_to(normal, ray_dirs.shape)
    return rng_true, hit, normals


# ---------------------------------------------------------------------------
# Block averaging and interpolation
# ---------------------------------------------------------------------------
def _block_layout(length: int, block: int) -> tuple[int, np.ndarray]:
    """Number of blocks along an axis of ``length`` pixels (the last block may be
    partial) and the pixel coordinate of each block's center."""
    count = -(-length // block)
    starts = np.arange(count) * block
    sizes = np.minimum(block, length - starts)
    return count, starts + (sizes - 1) / 2.0


def _interpolation_matrix(length: int, centers: np.ndarray) -> np.ndarray:
    """(length, n_blocks) matrix of 1-D linear interpolation weights from block
    centers to pixel coordinates 0..length-1 (clamped at the ends)."""
    n_blocks = centers.size
    weights = np.zeros((length, n_blocks))
    if n_blocks == 1:
        weights[:, 0] = 1.0
        return weights
    pixels = np.arange(length, dtype=np.float64)
    lower = np.clip(np.searchsorted(centers, pixels, side="right") - 1, 0, n_blocks - 2)
    fraction = np.clip((pixels - centers[lower]) / (centers[lower + 1] - centers[lower]), 0.0, 1.0)
    rows = np.arange(length)
    weights[rows, lower] = 1.0 - fraction
    weights[rows, lower + 1] = fraction
    return weights


class _BlockGrid:
    """Block structure of one image size: block sums of pixel images and the
    count-weighted bilinear interpolation of block values back to pixels."""

    def __init__(self, height: int, width: int, block: int, valid: np.ndarray) -> None:
        if block < 1:
            raise ValueError("effective_block_px must be at least 1")
        self.height, self.width, self.block = height, width, block
        self.n_rows, row_centers = _block_layout(height, block)
        self.n_cols, col_centers = _block_layout(width, block)
        self.row_weights = _interpolation_matrix(height, row_centers)
        self.col_weights = _interpolation_matrix(width, col_centers)
        self.valid = valid
        self.count = self.block_sum(valid.astype(np.float64))
        self.has_valid = self.count > 0.0

    def block_sum(self, image: np.ndarray) -> np.ndarray:
        """(n_rows, n_cols) sums of an (H, W) image over blocks."""
        pad_rows = self.n_rows * self.block - self.height
        pad_cols = self.n_cols * self.block - self.width
        padded = np.pad(image, ((0, pad_rows), (0, pad_cols)))
        return padded.reshape(self.n_rows, self.block, self.n_cols, self.block).sum(axis=(1, 3))

    def block_mean_of_valid(self, image: np.ndarray) -> np.ndarray:
        """Mean over the valid pixels of each block (0 for blocks without any)."""
        total = self.block_sum(np.where(self.valid, image, 0.0))
        return np.where(self.has_valid, total / np.where(self.has_valid, self.count, 1.0), 0.0)

    def interpolate(self, block_values: np.ndarray) -> np.ndarray:
        """Bilinear interpolation of block values to the native grid with weights
        proportional to each block's valid count; empty blocks contribute nothing.
        Pixels with no contributing block get 0."""
        weighted = self.row_weights @ (self.count * block_values) @ self.col_weights.T
        total = self.row_weights @ self.count @ self.col_weights.T
        return np.where(total > WEIGHT_SUM_TOLERANCE, weighted / np.where(total > WEIGHT_SUM_TOLERANCE, total, 1.0), 0.0)

    def upsample_nearest(self, block_values: np.ndarray) -> np.ndarray:
        """Each pixel takes the value of its own block."""
        rows = np.arange(self.height) // self.block
        cols = np.arange(self.width) // self.block
        return block_values[np.ix_(rows, cols)]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _render(params: SyntheticSensorParameters, ray_dirs, rng_true, hit, normals, curvature_per_mm,
            error_field: ErrorField, rng: np.random.Generator) -> SyntheticFrame:
    """Shared pipeline after the geometric intersection (module docstring, steps 2-8)."""
    camera = params.camera
    height, width = camera.height, camera.width
    u, v = camera.pixel_grid()
    ray_z = ray_dirs[..., 2]

    # Truth from the exact normal. cos(alpha) = n . (-d), clipped to [0, 1].
    cos_incidence = np.where(hit, np.clip(np.sum(normals * -ray_dirs, axis=-1), 0.0, 1.0), np.nan)
    safe_cos = np.where(hit, cos_incidence, 1.0)
    # Slope inputs s = (n . e) * d_z / (n . (-d)): see the module docstring ("Slope inputs").
    true_s_u = np.where(hit, normals[..., 0] * ray_z / np.maximum(safe_cos, MINIMUM_NOISE_COSINE), np.nan)
    true_s_v = np.where(hit, normals[..., 1] * ray_z / np.maximum(safe_cos, MINIMUM_NOISE_COSINE), np.nan)

    # Injected error at the true inputs, added to the true range.
    error_mm = np.zeros((height, width))
    if np.any(hit):
        n_hit = int(np.count_nonzero(hit))
        error_mm[hit] = error_field(u[hit], v[hit], rng_true[hit], true_s_u[hit], true_s_v[hit],
                                    np.full(n_hit, curvature_per_mm))
    range_with_error = np.where(hit, rng_true + error_mm, 0.0)
    z_native = range_with_error * ray_z

    # Effective resolution: block averages of valid pixels, interpolated back.
    grid = _BlockGrid(height, width, params.effective_block_px, hit)
    z_block = grid.block_mean_of_valid(z_native)
    cos_block = grid.block_mean_of_valid(np.where(hit, cos_incidence, 0.0))
    z_final = grid.interpolate(z_block)

    # Noise, one draw per block; always draw so the random stream is reproducible.
    noise_draw = rng.standard_normal((grid.n_rows, grid.n_cols))
    read_draw = rng.random((grid.n_rows, grid.n_cols))
    sigma_block = (params.noise_coefficient_per_mm * z_block ** 2
                   * np.maximum(cos_block, MINIMUM_NOISE_COSINE) ** (-params.noise_incidence_exponent))
    z_final = z_final + grid.interpolate(sigma_block * noise_draw)

    # Fixed pattern: per-block offsets from a fixed seed, identical in every frame.
    if params.fixed_pattern_amplitude_mm != 0.0:
        pattern_rng = np.random.default_rng(params.fixed_pattern_seed)
        pattern = params.fixed_pattern_amplitude_mm * pattern_rng.uniform(-1.0, 1.0, (grid.n_rows, grid.n_cols))
        z_final = z_final + grid.interpolate(pattern)

    # No-read per block, logistic in the block's incidence angle.
    alpha_block_deg = np.degrees(np.arccos(np.clip(cos_block, 0.0, 1.0)))
    read_probability = expit(-(alpha_block_deg - params.noread_onset_deg) / params.noread_width_deg)
    block_read = grid.has_valid & (read_draw < read_probability)
    read_mask = hit & grid.upsample_nearest(block_read) & (z_final > 0.0)

    # Final points: unit ray times final range, with z equal to the final depth.
    final_range = np.where(read_mask, z_final / np.where(read_mask, ray_z, 1.0), 0.0)
    xyz = (ray_dirs * final_range[..., None]).astype(np.float32)
    xyz[~read_mask] = 0.0
    return SyntheticFrame(
        xyz=xyz, true_range=rng_true, true_cos_incidence=cos_incidence,
        true_s_u=true_s_u, true_s_v=true_s_v, read_mask=read_mask, hit_mask=hit)


def render_sphere_frame(params: SyntheticSensorParameters, center_sensor, radius_mm: float,
                        error_field: ErrorField, rng: np.random.Generator) -> SyntheticFrame:
    """Render one frame of a sphere (center in the sensor frame, mm). The
    curvature input passed to the error field is 1 / radius_mm."""
    center = np.asarray(center_sensor, dtype=np.float64).reshape(3)
    ray_dirs = params.camera.ray_directions()
    rng_true, hit, normals = _sphere_hits(ray_dirs, center, float(radius_mm))
    return _render(params, ray_dirs, rng_true, hit, normals, 1.0 / float(radius_mm), error_field, rng)


def render_board_frame(params: SyntheticSensorParameters, board_pose_sensor: RigidTransform, board,
                       error_field: ErrorField, rng: np.random.Generator) -> SyntheticFrame:
    """Render one frame of a board. ``board_pose_sensor`` maps board coordinates
    to the sensor frame; ``board`` has attributes half_width_mm and
    half_height_mm (e.g. BoardTarget) or is a (half_width, half_height) tuple.
    Only the front face (outward normal +z toward the camera) is visible. The
    curvature input is 0."""
    if hasattr(board, "half_width_mm"):
        half_width, half_height = float(board.half_width_mm), float(board.half_height_mm)
    else:
        half_width, half_height = (float(board[0]), float(board[1]))
    ray_dirs = params.camera.ray_directions()
    rng_true, hit, normals = _board_hits(ray_dirs, board_pose_sensor, half_width, half_height)
    return _render(params, ray_dirs, rng_true, hit, normals, 0.0, error_field, rng)


# ---------------------------------------------------------------------------
# Dataset writer
# ---------------------------------------------------------------------------
def _flat_matrix(transform: RigidTransform) -> list[float]:
    """Row-major 16-float list of a transform's 4 x 4 matrix."""
    return [float(x) for x in transform.as_matrix().reshape(-1)]


def write_synthetic_dataset(out_dir, params: SyntheticSensorParameters, poses, sensor_to_positioner: RigidTransform,
                            frames_per_pose: int, error_field: ErrorField, rng: np.random.Generator,
                            write_header_pose: bool = True, write_manifest: bool = True) -> Path:
    """Render and write a synthetic dataset; returns ``out_dir``.

    poses: list of ("sphere", radius_mm, RigidTransform) or
           ("board", (half_width_mm, half_height_mm), RigidTransform), the
           transform being target -> positioner (a sphere's center is its
           translation). Targets are moved into the sensor frame with
           sensor_to_positioner.inverse() before rendering.

    Writes ``<pose_id>_Index<frame:02d>.mc`` (pose_id = pose0000, pose0001, ...)
    with header keys fx, fy, cx, cy, h (image width), v (image height),
    cameraName, version, and (if write_header_pose) robotPose, the 16-float
    row-major target pose in the positioner frame; matrix XYZ float32. Also
    writes manifest.json (design document schema, if write_manifest) and
    truth.json (parameters, sensor_to_positioner, error-field description,
    per-pose target description).
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    positioner_to_sensor = sensor_to_positioner.inverse()
    camera = params.camera
    records: list[CaptureRecord] = []
    truth_poses = []
    for pose_index, (kind, target_params, target_to_positioner) in enumerate(poses):
        pose_id = POSE_ID_FORMAT.format(index=pose_index)
        target_in_sensor = positioner_to_sensor.compose(target_to_positioner)
        if kind == TARGET_KIND_SPHERE:
            radius_mm, half_size = float(target_params), None
            description = {"kind": kind, "radius_mm": radius_mm}
        elif kind == TARGET_KIND_BOARD:
            radius_mm, half_size = None, (float(target_params[0]), float(target_params[1]))
            description = {"kind": kind, "half_width_mm": half_size[0], "half_height_mm": half_size[1]}
        else:
            raise ValueError(f"pose {pose_index}: unknown target kind {kind!r}")
        description.update(pose_id=pose_id, target_pose_positioner=target_to_positioner.as_matrix().tolist())
        truth_poses.append(description)
        for frame in range(frames_per_pose):
            if kind == TARGET_KIND_SPHERE:
                rendered = render_sphere_frame(params, target_in_sensor.translation, radius_mm, error_field, rng)
            else:
                rendered = render_board_frame(params, target_in_sensor, half_size, error_field, rng)
            header = {
                "fx": camera.focal_x_px, "fy": camera.focal_y_px,
                "cx": camera.principal_x_px, "cy": camera.principal_y_px,
                "h": camera.width, "v": camera.height,      # image width and height in pixels
                "cameraName": SYNTHETIC_CAMERA_NAME, "version": SYNTHETIC_HEADER_VERSION,
            }
            if write_header_pose:
                header[HEADER_POSE_KEY] = _flat_matrix(target_to_positioner)
            file_path = out_path / FILE_NAME_FORMAT.format(pose_id=pose_id, frame=frame)
            write_matcloud(file_path, header, {XYZ_CHANNEL_NAME: rendered.xyz})
            records.append(CaptureRecord(
                path=file_path, pose_id=pose_id, frame_index=frame, target_kind=kind,
                sphere_radius_mm=radius_mm, board_half_size_mm=half_size,
                target_pose_positioner=target_to_positioner, metadata={}))
    if write_manifest:
        write_manifest_json(out_path / MANIFEST_FILE_NAME, records)
    truth = {
        "parameters": asdict(params),
        "sensor_to_positioner": sensor_to_positioner.as_matrix().tolist(),
        "error_field": describe_error_field(error_field),
        "frames_per_pose": frames_per_pose,
        "poses": truth_poses,
    }
    (out_path / TRUTH_FILE_NAME).write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return out_path
