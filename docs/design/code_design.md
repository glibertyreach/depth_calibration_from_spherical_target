# sphcal: code design for the data-analysis phase

Status: interfaces fixed for implementation, 2026-10-04. This document is the
contract every module is written against. The analysis it implements is
`docs/analysis/calibration_from_spherical_target_analysis.md`, whose decisions
D-1 to D-12 are binding here.

## 1. Scope and non-goals

In scope: reading captures and commanded poses; computing per-pixel residuals
against known spheres and boards; fitting the correction map as a sum of
tensor-product B-spline terms; alternating with the sensor-to-positioner
transform under the sensor-frame gauge; fitting the no-read probability map;
validation reports; a synthetic data generator for end-to-end tests; a map file
format readable by a later Lisp evaluator.

Out of scope: data acquisition; the runtime evaluator (to be written in Lisp
later; the Python evaluator here is the reference); any physical sensor model
in the fit (the synthetic generator may use one to make test data, and labels
it indicative).

## 2. Coding rules

- Python 3.10+, numpy, scipy only (matplotlib for figures, pytest for tests).
- Clarity over terseness. Every module has a docstring saying what it computes
  and in which conventions; every function with more than a trivial body says
  what it returns and in which units.
- No magic numbers. Every arbitrary constant is a named parameter of a
  dataclass or a module-level constant with a docstring saying what it is for.
  Numerical guards (tolerances for zero-length vectors and the like) are named
  constants too.
- Units: millimeters, degrees at public interfaces, pixels for image
  coordinates. Angles inside numerics may be radians.
- Image arrays are (height, width[, channels]); pixel (u, v) = (column, row).
- Invalid depth is z <= 0 (verified sentinel: the whole XYZ point is zero).
- U.S. spelling in comments and docstrings.

## 3. Module map

```
sphcal/
  io/qt_datastream.py    vendored, verified; do not edit
  io/matcloud.py         vendored, verified; do not edit
  io/poses.py            CaptureRecord, manifest readers, header-pose reader
  io/capture_set.py      CaptureSet: records grouped by pose, lazy stacks
  geometry/camera.py     PinholeCamera (done)
  geometry/transforms.py RigidTransform, fit_rigid_transform (done)
  geometry/targets.py    SphereTarget, BoardTarget, ray intersections, predicted coverage
  features/depth_features.py  temporal statistics, image slope inputs, block weights
  features/normals.py    plane-fit normals over an N x N window (the downstream 5 x 5 estimator)
  spline/basis.py        BSplineBasis1D
  spline/term.py         TensorTerm
  spline/model.py        SumOfTermsSpline, InputSpec, JSON I/O
  spline/fit.py          penalized weighted least squares, robust IRLS, logistic IRLS, GCV
  calibration/samples.py assemble samples (inputs, residual targets, weights) from a CaptureSet
  calibration/extrinsic.py  sphere center fit, transform solve, alternation
  calibration/correction.py fit the correction map (the orchestration of S1-S4)
  calibration/noread.py  fit the no-read probability map (S5)
  validation/report.py   held-out statistics, normal error on boards, figures (S6)
  simulate/synthetic.py  synthetic captures with an injected error field
  cli/                   fit, validate, simulate entry points
tests/
```

## 4. Frames and quantities

- Sensor frame: the camera frame of the depth image (D-1: outputs live here).
- Positioner frame: where commanded poses are given. T_sp: RigidTransform
  mapping sensor-frame points to positioner-frame points. The code estimates
  T_sp unless given.
- Target pose: for a sphere, its center in the positioner frame (3 numbers);
  for a board, a RigidTransform board->positioner, the board being the
  rectangle |x| <= half_width, |y| <= half_height in its own z = 0 plane with
  outward normal +z (toward the sensor when the board faces it).
- Measured range rho_m: the Euclidean distance from the camera center to the
  measured point along the pixel's ray. The correction output is delta_rho,
  to be added to rho_m (D-4: evaluated at native pixels).
- Map inputs, in this order, all from measured quantities at runtime:
  0 u (px), 1 v (px), 2 rho_m (mm), 3 s_u, 4 s_v, 5 kappa_m (mm/px^2).
  s_u and s_v are the dimensionless slope components of the measured surface
  in the local ray frame: with dz/du and dz/dv the depth gradients in mm per
  pixel from a plane fit over the slope window, s_u = (dz/du) * f_x / z and
  s_v = (dz/dv) * f_y / z. For a surface tilted by angle theta along u this
  is tan(theta) (small-field approximation; the exact form is a coordinate
  choice and does not need to be physical). Incidence cos(alpha) =
  1 / sqrt(1 + s_u^2 + s_v^2).
  The sixth input, named "curvature", is the MEASUREMENT-SPACE curvature
  kappa_m = (rho_m / f_mean)^2 * (1 / R), in millimeters of depth per pixel
  squared, where R is the physical radius of curvature of the surface (1 / R is
  0 for a plane) and f_mean = sqrt(fx * fy) is the geometric mean of the
  camera's focal lengths in pixels. Reason (D-15 to D-17): the sensor averages
  depth over a kernel fixed in PIXELS, so the bias it causes on a curved
  surface depends on the curvature of the depth profile per pixel, which is
  (Z / f)^2 / R, not on 1 / R. With the physical curvature as input and one
  calibration sphere (radius 76.2 mm), the input would take two values (0 on
  boards, 1 / 76.2 on the sphere) at every range, so a sweep through ranges
  could not inform the term; kappa_m varies with range even for one sphere.
  Range stays a separate axis of the curvature term. During calibration 1 / R
  is the known target's curvature (a sphere's reciprocal radius, 0 for a
  board) and rho_m is the sample's measured range. At runtime the caller
  supplies the physical curvature estimate or 0 (`correct_frame` takes it per
  pixel or as a scalar) and the evaluator forms kappa_m per pixel with that
  pixel's measured range. The no-read samples, indexed by predicted geometry,
  use the predicted range.
- Residual target for a sample on a sphere: rho_true - rho_m, where rho_true
  is the near intersection of the pixel ray with the known sphere (center
  transformed into the sensor frame by T_sp^-1). For a board: intersection
  with the known plane, inside the rectangle. Samples whose ray misses the
  target, or whose predicted incidence exceeds the cut-off, or that lie within
  the silhouette margin, are excluded.
- Sample weights: inverse temporal variance of the pixel's range across the
  frames of its pose, times the block-independence factor
  1 / effective_block_px^2 (D-4), times a robust weight from IRLS.

## 5. Interfaces (signatures are binding; bodies are the implementer's)

### geometry/targets.py
```python
@dataclass(frozen=True)
class SphereTarget:
    radius_mm: float
@dataclass(frozen=True)
class BoardTarget:
    half_width_mm: float
    half_height_mm: float

def ray_sphere_near_range(ray_dirs, center, radius) -> tuple[np.ndarray, np.ndarray]
    # ray_dirs (..., 3) unit, from the origin; returns (range, hit) with range NaN where no hit
def ray_plane_range(ray_dirs, plane_point, plane_normal) -> tuple[np.ndarray, np.ndarray]
    # positive-range intersections only; hit False for parallel or behind
def sphere_surface_normal(points, center) -> np.ndarray   # outward unit normals
def cos_incidence(normals, ray_dirs) -> np.ndarray         # cos of angle between normal and -ray, clipped to [0, 1]

@dataclass(frozen=True)
class CoverageParameters:
    incidence_cutoff_deg: float       # samples beyond this are excluded (default 55.0, D-10 discussion)
    silhouette_margin_px: float       # exclude pixels within this distance of the predicted silhouette (default 6.0)
    board_edge_margin_mm: float       # exclude board points within this distance of the board edge (default 10.0)

@dataclass
class PredictedCoverage:             # one target in one frame, per native pixel
    range_mm: np.ndarray             # (H, W), NaN where the ray misses
    cos_incidence: np.ndarray        # (H, W), NaN where miss
    usable: np.ndarray               # (H, W) bool: hit, inside cut-off, outside margins
    covered: np.ndarray              # (H, W) bool: hit at all (for the no-read model: predicted coverage regardless of cut-off)
    curvature_per_mm: float          # 1/R or 0

def predict_sphere_coverage(camera, center_sensor, radius_mm, params) -> PredictedCoverage
def predict_board_coverage(camera, board_pose_sensor: RigidTransform, board: BoardTarget, params) -> PredictedCoverage
```

### features/depth_features.py
```python
@dataclass(frozen=True)
class SlopeParameters:
    window_px: int                   # odd; default 13 (at least three effective cells, D-8)
    min_valid_fraction: float        # fraction of window pixels that must be valid (default 0.6)

def temporal_statistics(depth_stack, valid_stack, min_valid_fraction) -> TemporalStatistics
    # depth_stack (F, H, W) camera-z in mm; valid_stack (F, H, W) bool
    # returns mean_depth (H, W) (NaN where invalid), variance (H, W), valid_count (H, W), read_fraction (H, W)
def image_slopes(depth_image, valid, camera, params) -> tuple[np.ndarray, np.ndarray]
    # s_u, s_v per the definition in section 4, NaN where the window fit is not possible
    # implemented as a least-squares plane fit of z over (u, v) in the window, vectorized (integral images or
    # scipy.ndimage.uniform_filter on the normal-equation sums), masked by validity
def range_from_depth(depth_image, camera) -> np.ndarray      # rho = z * |ray| per pixel
def measurement_space_curvature(curvature_per_mm, range_mm, focal_px)
    # (range_mm / focal_px)^2 * curvature_per_mm, mm/px^2, elementwise with broadcasting; the camera's focal_px
    # is PinholeCamera.mean_focal_px = sqrt(fx * fy)
def block_independence_weight(effective_block_px: int) -> float   # 1 / block^2
```

### features/normals.py
```python
@dataclass(frozen=True)
class NormalEstimatorParameters:
    window_px: int                   # default 5 (D-8)
    min_valid_fraction: float        # default 0.6
def plane_fit_normals(xyz, valid, params) -> np.ndarray
    # (H, W, 3) unit normals from a least-squares plane fit over the window of camera-frame points,
    # oriented toward the camera (negative dot with the ray), NaN where not computable; vectorized
```

### spline/basis.py, term.py, model.py, fit.py
```python
class BSplineBasis1D:
    degree: int; knots: np.ndarray  # full clamped (open) knot vector of length n_coefficients + degree + 1
    @classmethod uniform(cls, lower, upper, n_intervals, degree)
    @classmethod from_quantiles(cls, samples, n_intervals, degree, lower=None, upper=None)
    @classmethod from_interior_knots(cls, lower, upper, interior_knots, degree)
    n_coefficients: int
    design(x) -> scipy.sparse.csr_matrix (N, n_coefficients)       # values outside [lower, upper] clamp to the boundary
    design_derivative(x, order=1) -> csr_matrix
    difference_penalty(order) -> scipy.sparse matrix (n_coefficients, n_coefficients)  # D^T D, P-spline penalty

class TensorTerm:
    name: str; input_indices: tuple[int, ...]; bases: list[BSplineBasis1D]   # the bases may differ in degree
    penalty_order: int; smoothing: list[float]   # one smoothing parameter per dimension
    n_coefficients: int
    design(X) -> csr_matrix (N, n_coefficients)   # X (N, D) full input matrix; row-wise Kronecker of the 1-D designs
    penalty() -> sparse (n, n)                   # sum over dimensions of smoothing_d * kron(I, ..., D_d^T D_d, ..., I)
    evaluate(X, coefficients) -> np.ndarray (N,)

@dataclass(frozen=True)
class InputSpec:
    name: str; lower: float; upper: float; unit: str

class SumOfTermsSpline:
    inputs: list[InputSpec]; terms: list[TensorTerm]; coefficients: np.ndarray (sum of term sizes)
    metadata: dict
    design(X) -> csr_matrix (N, total)
    penalty() -> sparse (total, total)
    evaluate(X) -> np.ndarray (N,)
    term_slices() -> list[slice]
    to_json(path), from_json(path)   # format in section 7

def fit_penalized_least_squares(design, y, weights, penalty, solver="auto") -> FitResult
    # minimizes sum w (y - A c)^2 + c^T P c; solver "direct" (sparse Cholesky via splu/spsolve on A^T W A + P),
    # "iterative" (scipy.sparse.linalg.cg or lsqr), "auto" by size (direct below a named coefficient-count threshold)
    # FitResult: coefficients, effective_degrees_of_freedom (trace of the hat matrix, estimated stochastically for large
    # systems), residual_rms, gcv_score
def fit_robust(design, y, weights, penalty, robust: RobustParameters) -> FitResult
    # IRLS with Huber weights; RobustParameters(huber_delta_in_sigmas, max_iterations, convergence_tolerance)
def fit_logistic(design, y_binary, weights, penalty, params: LogisticParameters) -> FitResult
    # penalized logistic regression by IRLS; returns coefficients of the logit
def select_smoothing_by_gcv(model, X, y, weights, grid: SmoothingGrid) -> SumOfTermsSpline
    # coordinate-wise search over a log grid of smoothing values per term, minimizing GCV
```

### io/poses.py, io/capture_set.py
```python
@dataclass
class CaptureRecord:
    path: Path; pose_id: str; frame_index: int
    target_kind: str                      # "sphere" | "board"
    sphere_radius_mm: float | None
    board_half_size_mm: tuple[float, float] | None
    target_pose_positioner: RigidTransform   # for a sphere only the translation is used
    metadata: dict                        # unit id, exposure, anything else from the manifest or header

def load_manifest(path) -> list[CaptureRecord]
    # JSON: {"records": [{"file": "...", "pose_id": "...", "frame": 0,
    #          "target": {"kind": "sphere", "radius_mm": 50.0} | {"kind": "board", "half_width_mm": .., "half_height_mm": ..},
    #          "pose": {"matrix": [16 floats row-major]} | {"center_mm": [x, y, z]}}, ...]}
    # CSV: columns file,pose_id,frame,target_kind,radius_mm,half_width_mm,half_height_mm,m00..m23 (12 floats, row-major 3x4)
def records_from_headers(paths, target_kind, sphere_radius_mm=None, board_half_size_mm=None, pose_key="robotPose") -> list[CaptureRecord]
    # reads the 4x4 row-major list under pose_key in each file's header; pose_id derived from the file name by a
    # documented rule (strip a trailing frame index pattern) unless a group_by callable is supplied
class CaptureSet:
    records: list[CaptureRecord]
    pose_ids() -> list[str]
    records_for(pose_id) -> list[CaptureRecord]
    load_stack(pose_id) -> PoseStack   # xyz (F, H, W, 3) float32, valid (F, H, W) bool, header dict, camera PinholeCamera
```

### simulate/synthetic.py
```python
@dataclass(frozen=True)
class SyntheticSensorParameters:
    camera: PinholeCamera
    effective_block_px: int                   # 4
    noise_coefficient_per_mm: float           # sigma_z = k z^2 per block (indicative, 1.79e-7)
    noise_incidence_exponent: float           # sec^m multiplier (indicative 1.3)
    noread_onset_deg: float                   # 50 % read probability (55.0)
    noread_width_deg: float                   # logistic width in degrees (5.0)
    fixed_pattern_amplitude_mm: float         # amplitude of a fixed, high-frequency per-block pattern (optional, 0 disables)
    fixed_pattern_seed: int
def default_injected_error_field(u, v, rho, s_u, s_v, curvature) -> np.ndarray
    # a smooth, deliberately non-physical test field in mm: a low-order bowl in (u, v) scaled by rho^2, plus a term in
    # s_u, s_v that grows toward the cut-off, plus a term linear in curvature; coefficients are named constants
def render_sphere_frame(params, center_sensor, radius_mm, error_field, rng) -> SyntheticFrame
def render_board_frame(params, board_pose_sensor, board, error_field, rng) -> SyntheticFrame
    # SyntheticFrame: xyz (H, W, 3) float32 with zeros for no-reads, truth: true range (H, W), true cos incidence, read mask
    # pipeline: exact ray intersection on the native grid -> true range -> add error_field(at true inputs) ->
    # convert to depth -> average over effective blocks and interpolate back (bilinear) -> add block noise
    # (one draw per block, sigma = k z^2 sec^m) -> apply no-read by a logistic in incidence -> zero outside
def write_synthetic_dataset(out_dir, params, poses, sensor_to_positioner, frames_per_pose, error_field, rng,
                            write_header_pose=True, write_manifest=True) -> Path
    # poses: list of (target_kind, target params, target pose in positioner frame); writes .mc files with the
    # vendored writer, the manifest JSON, and truth.json with the injected field's description and T_sp
```

### calibration/*.py and validation/report.py
Written by the integrator after the modules above exist; their outline is
steps S1 to S7 of the analysis document.

## 6. Default model configuration (a-theoretical; the data choose by GCV and held-out error)

Terms, each a tensor-product B-spline with second-order difference penalties.
`TermSpec.degree` is one integer for all axes of a term or one integer per axis:
- position: inputs (u, v, rho), cubic, intervals (8, 6, 6)
- slope: inputs (s_u, s_v, rho), cubic, intervals (6, 6, 4), with s bounded by tan of the cut-off
- curvature: inputs (kappa_m, rho, s_u, s_v), degrees (1, 3, 3, 3), intervals (1, 4, 4, 4): linear in
  measurement-space curvature (one interval, two coefficients along that axis) and cubic in range and in
  the two slopes. Range is a separate axis because the bias of the pixel-fixed averaging kernel depends on
  range as well as on kappa_m. Range knots follow the quantile placement used for the range input in every
  term. The kappa_m axis spans [0, `curvature_upper_mm_per_px2`], default 0.5 mm/px^2, which covers a 20 mm
  radius out to about 2,200 mm at a 688 px focal length ((2200 / 688)^2 / 20 = 0.51); the axis is linear, so
  a generous bound costs nothing.
- optional full interaction: inputs (u, v, rho, s_u, s_v), intervals (4, 3, 3, 3, 3), off by default
The read-probability (no-read) map uses position (4, 3, 4), slope (8, 8, 3) and the same curvature term
with intervals (1, 3, 3, 3). It was checked on the synthetic campaign: the fit stays stable and the
onsets move by at most 1 degree against the previous inputs.
The comparison between configurations is by held-out residual (section 7.6 of
the analysis).

## 7. Map file format (JSON; the contract with the later Lisp evaluator)

```json
{
  "format": "sphcal-map", "version": 1,
  "inputs": [{"name": "u", "lower": 0, "upper": 639, "unit": "px"}, ...],
  "output": {"name": "delta_range", "unit": "mm", "applies_to": "range along the pixel ray, added to the measured range"},
  "terms": [{"name": "position", "input_indices": [0, 1, 2], "degrees": [3, 3, 3], "degree": 3,
             "knots": [[...], [...], [...]], "coefficients": [... row-major over the term's dimensions ...]},
            {"name": "curvature", "input_indices": [5, 2, 3, 4], "degrees": [1, 3, 3, 3],
             "knots": [[...], [...], [...], [...]], "coefficients": [...]}, ...],
  "camera": {"width": 640, "height": 480, "fx": 688.155, "fy": 688.083, "cx": 292.316, "cy": 256.759},
  "domain_note": "evaluate only inside the input bounds; outside, clamp inputs to the bounds",
  "metadata": {"unit_id": "...", "fitted_on": "...", "gauge": "sensor frame, zero mean displacement and rotation", ...}
}
```
"degrees" has one B-spline degree per dimension of the term, in the order of "input_indices" and "knots"; the
single integer "degree" is written in addition only when all dimensions share it, and an evaluator reads
"degrees" when present, otherwise "degree". Older files with only "degree" still load.

Camera block and the sixth input. The evaluator must form input 5 itself. With the camera block it
computes, per pixel, f_mean = sqrt(fx * fy) once, then

    kappa_m = (rho_m / f_mean)^2 * physical_curvature        (mm/px^2; physical_curvature = 1 / R in 1/mm, 0 for a plane)

where rho_m is that pixel's measured range (input 2) and physical_curvature is what the caller supplies (a
scalar or per pixel). The block is written for the correction map and the no-read map; it is absent only
when a map was built without a camera.
Evaluation rule: for each term, for each dimension find the knot span of the
(clamped) input, evaluate the degree+1 nonzero B-spline basis values by the
Cox-de Boor recursion, multiply the basis values across dimensions, and sum
coefficient times product over the (degree+1)^D nonzero combinations; the map
value is the sum over terms.

## 8. Tests (pytest)

- Vendored reader: write then read a synthetic .mc file; header and arrays round-trip.
- Basis: partition of unity; derivative against finite differences; clamped evaluation at bounds.
- Term and model: a known smooth function on random inputs is recovered to a stated tolerance; JSON round-trip
  reproduces evaluations to machine precision.
- Fit: penalized least squares recovers a known function under noise; GCV minimum lies near the truth-optimal
  smoothing; logistic fit recovers a known logit.
- Targets: ray-sphere and ray-plane intersections against closed forms; coverage masks have the expected sizes.
- Features: slopes on a synthetic tilted plane equal tan of the tilt within tolerance; normals on a plane equal
  the plane normal; temporal statistics on a stack with known variance.
- Synthetic: a dataset of a few poses is written and read back through CaptureSet; truth is consistent.
- End to end (integrator): fit on synthetic data recovers the injected field on held-out poses to a stated
  tolerance, and the no-read map recovers the injected onset.

## 9. Status after the first integration (2026-10-04)

All modules exist and 111 tests pass. On a full-resolution synthetic campaign
(40 poses of two sphere radii and tilted boards, 3 frames each, indicative
sensor model, injected non-physical error field) the held-out range residual
fell from 0.24 mm to 0.036 mm against a noise floor of about 0.03 mm, held-out
sphere-center errors from about 1 mm to 0.06 to 0.33 mm, and held-out board
normal bias from 0.10 to 0.15 degrees to under 0.02 degrees; the gauge
alternation converged in nine rounds. The no-read onset converted from window
slope reads about 8 degrees high on spheres (see the noread module docstring);
planar targets give it exactly.

Deviations from the first version of this document that the integration
forced: per-pixel variances are pooled over incidence bins within a pose
(three frames cannot support per-pixel weights); smoothing is selected by
cross-validation with whole poses held out rather than by GCV, which counts
correlated native pixels as independent; samples are taken at one pixel per
effective block (the correction is still evaluated at every native pixel); the
transform is re-solved from the map's rigid component rather than from refitted
sphere centers, which gives the alternation a definite fixed point; the
hold-out split is stratified by target kind; sphere fits are trimmed and the
transform solve gates poses by center residual.

## 10. Run time (2026-10-04, 4-core container, 40 poses x 3 frames at 640 x 480)

The first integration took 577 s. Three changes brought it to 64 s with
identical results: the design matrix is built once and the transform changes
only the targets, so cross-validation, the robust iteration and every
alternation round reuse Gram matrices (calibration/fast_solve.py); the exact
effective degrees of freedom are computed once at the end; per-pose feature
extraction runs in a process pool and the read-probability table is sampled
at twice the correction stride. Cost scales linearly with the pose count in
the per-pose parts (about 0.3 s per pose on one core) and not at all with it
in the factorizations (fixed coefficient count), so a few hundred stage-1
poses take a few minutes on a 4-core machine. No GPU is involved in the fit;
the target GPU named in the pose-determination specification (GTX 1660 Ti
class, Turing, compute capability 7.5, 6 GB, single precision) is relevant to
the runtime evaluator, whose per-pixel work is trivially parallel.

## 11. Changes of 2026-10-08 (one calibration sphere; measurement-space curvature)

- One calibration sphere, radius 76.2 mm (sphere B), swept through a geometric ladder of depths (D-15 to
  D-17). `sphcal.cli.plan_poses` plans one sphere radius at stations 300 mm times (2^(1/4))^k up to 1100 mm,
  with 1100 mm appended when the last rung is more than 20 mm short of it (300, 357, 424, 505, 600, 714, 849,
  1009, 1100 mm); `--sphere-depths-mm` replaces the ladder. Each station is a lateral grid, fitted to the
  room the sphere's image leaves inside the image border (found by bisection with the exact silhouette test):
  the grid spans the smaller of `fov_fill` of the half field and that room, at a spacing of 1.5 radii shrunk
  where needed so that at least `min_positions_per_axis` (default 3) positions lie along each image axis. Near
  range therefore keeps a 3 x 3 grid of overlapping placements instead of only the center. Grid poses whose
  silhouette would still leave the image are dropped, and the center pose (0, 0, depth) is always kept. The default
  board depths gain 425 mm. The two-radius mode is removed. The clipping test projects the exact silhouette
  circle (the earlier radius-scaled approximation let through poses that overshot the border by up to about
  3 px at the 424 mm station).
- The map's sixth input is measurement-space curvature (section 4); `correct_frame` still takes the physical
  curvature and converts it per pixel. The map JSON stores per-dimension degrees and a camera block
  (section 7). The end-to-end synthetic test's injected field still uses the physical curvature 1/R; the test
  converts the sample input back with the measured range before calling it.

## 12. Changes of 2026-10-09 (after the one-sphere simulation)

- The simulation of the planned session (`docs/analysis/simulations/2026-10-08_one_sphere/`) found the
  one-sphere plan sufficient, with two weak points: the board's 40 degree limit, addressed below, and the
  smoothing search's choice of its grid ceiling, which is explained below and left open.
- `PlanParameters.board_tilts_deg` gains 50 degrees (0, 20, 40, 50). Without it no board sample lies between
  40 degrees and the 55 degree incidence cut-off, so the planar correction there was inferred from the sphere
  alone. The example plan grows from 200 to 217 poses (66 board poses).
- The smoothing search grids stay at 10^4. In the simulation the pose-fold search chose that ceiling for the
  position and slope terms. Raising the ceiling to 10^6 was tried and withdrawn: the search then chose 10^6,
  and the far range got worse (probe spheres at 950 mm 0.106 mm against 0.072 mm with the 50 degree tilt and
  the 10^4 ceiling), while the 50 degree tilt alone gave all of the improvement at steep incidence. The cause
  is the pose-fold score: it sums inverse-variance-weighted squared errors over samples, and the near range,
  where a pose covers many more pixels, dominates it, so the score keeps rewarding smoothing that costs the
  far range little in the sum. A score that gives each pose, or each depth band, equal weight would remove
  that bias; it is an open design item, not yet implemented. The outputs of the trial are archived in
  `docs/analysis/simulations/2026-10-08_one_sphere/archive/`.
