"""Diagnostic: which change made far sphere stations worse in the rerun of case A,
the 50 degree board tilt or the smoothing ceiling of 10^6? Runs case A twice, each
with one of the two changes, and prints per-station sphere recovery and the chosen
smoothing multipliers."""
import importlib.util, json, sys
from dataclasses import replace
from pathlib import Path
REPO = Path("/home/user/depth_calibration_from_spherical_target")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location("study", REPO / "docs/analysis/simulations/2026-10-08_one_sphere/run_one_sphere_study.py")
study = importlib.util.module_from_spec(spec); sys.modules["study"] = study; spec.loader.exec_module(study)
from sphcal.calibration.correction import CorrectionFitParameters, SmoothingSelection
from sphcal.spline.fit import SmoothingGrid
import sphcal.calibration.correction as corr
OLD_GRID = SmoothingGrid(log10_min=-3.0, log10_max=4.0, n_values=8, n_rounds=1)   # before 2026-10-09
NEW_GRID = SmoothingGrid(log10_min=-3.0, log10_max=6.0, n_values=10, n_rounds=1)  # after
OLD_TILTS = (0.0, 20.0, 40.0)
NEW_TILTS = (0.0, 20.0, 40.0, 50.0)
VARIANTS = {"tilt50_grid1e4": (NEW_TILTS, OLD_GRID), "tilt40_grid1e6": (OLD_TILTS, NEW_GRID)}
study.STUDY_FOLDER = OUT
captured = {}
original_fit = corr.fit_correction
def capturing_fit(*a, **k):
    r = original_fit(*a, **k); captured["mult"] = r.model.metadata.get("smoothing_multipliers"); return r
study.fit_correction = capturing_fit
logging = study.logging; logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
params = study.SyntheticSensorParameters.vsx3000_indicative()
probe_poses, probe_infos, _ = study.build_probe_poses(params.camera)
base = study.base_plan_parameters
summary = {}
for name, (tilts, grid) in VARIANTS.items():
    study.base_plan_parameters = lambda tilts=tilts: replace(base(), board_tilts_deg=tilts)
    study.CorrectionFitParameters = lambda grid=grid: CorrectionFitParameters(smoothing=SmoothingSelection(grid=grid))
    r = study.run_case(study.CASES["A"], params, study.FRAMES_PER_POSE, False, probe_poses, probe_infos)
    summary[name] = {"result": r, "multipliers": captured.get("mult")}
    (OUT / f"{name}.json").write_text(json.dumps(study.to_jsonable(summary[name]), indent=1))
    print(name, "multipliers", captured.get("mult"), flush=True)
