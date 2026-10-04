# depth_calibration_from_spherical_target

Theory-neutral B-spline correction of a depth sensor's range and normal errors,
fitted from observations of spheres and flat boards at commanded poses.

- `docs/analysis/` holds the problem analysis, its figures, and the decisions
  D-1 to D-12 that the code follows.
- `docs/design/code_design.md` is the module and interface contract.
- `sphcal/` is the Python data-analysis package (the runtime evaluator is to be
  written later in Lisp against the JSON map format in the design document).

## Quick start

```
pip install -e ".[figures,test]"   # or: pip install -r requirements.txt, and run from this directory
python3 -m pytest -q
python3 -m sphcal.cli.simulate --out data/synthetic --poses 80 --frames 3
python3 -m sphcal.cli.fit --manifest data/synthetic/manifest.json --out results/synthetic
```

The fit writes `correction_map.json`, `noread_map.json`, `report.json` and a
held-out residual figure into the output directory.
