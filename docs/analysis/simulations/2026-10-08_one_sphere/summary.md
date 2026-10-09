# One-sphere plan simulation

Script: `run_one_sphere_study.py`, run from the repository root (about 20 minutes for the three cases).
Full results: `results.json`; one log per case, `log_case_*.txt`; every table, including the other gauge
variants and the probe spheres by depth and incidence, in `summary_tables.md`. Figures:
`fig_probe_boards.png`, `fig_sphere_recovery.png`.

The setup, the cases and the two recovery metrics are described in full in the first run's summary,
`archive/run1_tilt40_grid1e4/summary.md`. In short: the planned session is rendered on the indicative
640 x 480 camera, five frames per pose, and fitted with the production settings. Case A injects a
curvature bias shaped like a 7 x 7 matching window. Case B adds a millimeter-domain effect. Case C uses an
approximation of the former two-sphere plan. Truth comes from the exact sphere and plane geometry. The
numbers below use the range-consistent metric: the range error along each pixel ray, after removing the
rigid gauge estimated on the held-out samples. RMS values are in mm, after correction, with the value
before correction in brackets.

## History of the runs

| Run | Board tilts | Smoothing ceiling | Outputs |
|---|---|---|---|
| 1 (2026-10-08) | 0, 20, 40 deg | 10^4 | `archive/run1_tilt40_grid1e4/` |
| 2 (2026-10-09) | 0, 20, 40, 50 deg | 10^6 | `archive/run2_tilt50_grid1e6/` |
| Diagnostic, case A only | one change at a time | | `archive/diagnostic_tilt_vs_grid/` |
| 3, final (2026-10-09) | 0, 20, 40, 50 deg | 10^4 | this folder |

Run 1 found the plan sufficient, with two weak points. First, the board stopped at 40 degrees, so the planar
correction between 40 degrees and the 55 degree cut-off was inferred from the sphere. Second, the smoothing
search chose its 10^4 ceiling for the position and slope terms. Run 2 added a 50 degree board tilt and raised
the ceiling to 10^6. The steep probe boards improved, but the far range got worse. The diagnostic separated
the two changes:

| Case A variant | Smoothing chosen (position, slope, curvature) | Probe spheres at 950 mm | Probe board 55 deg, 850 mm | Probe board 55 deg, 1050 mm |
|---|---|---|---|---|
| Run 1: tilts to 40, ceiling 10^4 | 1e4, 1e4, 1e1 | 0.066 | 0.170 | 0.197 |
| Tilts to 50, ceiling 10^4 | 1e4, 1e4, 1e4 | 0.072 | 0.105 | 0.141 |
| Tilts to 40, ceiling 10^6 | 1e5, 1e4, 1e2 | 0.078 | 0.178 | 0.239 |
| Run 2: tilts to 50, ceiling 10^6 | 1e6, 1e6, 1e4 | 0.106 | 0.104 | 0.135 |

The 50 degree tilt gives all of the improvement at steep incidence. The higher ceiling, combined with it,
oversmooths the far range. The pose-fold score is dominated by the many near-range samples, so it keeps
choosing the ceiling whatever the ceiling is. The ceiling was therefore restored to 10^4, and a score that
weights poses or depth bands equally is left as an open design item (`docs/design/code_design.md`,
section 12).

## Final run

| Case | Poses (sphere + board) | Held-out poses | Held-out residual RMS before / after | Smoothing chosen (position, slope, curvature) |
|---|---|---|---|---|
| A | 210 (145 + 65) | 42 (29 + 13) | 0.103 / 0.0135 | 1e4, 1e4, 1e4 |
| B | 210 (145 + 65) | 42 (29 + 13) | 0.111 / 0.0141 | 1e4, 1e4, 1e4 |
| C | 194 (143 + 51) | 39 (29 + 10) | 0.199 / 0.0240 | 1e2, 1e4, 1e3 |

The indicative camera's principal point is off center, so the plan has 210 poses here. The procedure's
example, which assumes a centered camera, has 217.

Held-out recovery:

| Group | A | B | C |
|---|---|---|---|
| all | 0.013 (0.099) | 0.014 (0.108) | 0.022 (0.119) |
| spheres | 0.013 (0.105) | 0.013 (0.113) | 0.024 (0.154) |
| boards | 0.014 (0.090) | 0.015 (0.098) | 0.021 (0.073) |
| spheres, 40-55 deg incidence | 0.017 (0.161) | 0.017 (0.180) | 0.033 (0.215) |
| boards, 40-55 deg incidence | 0.017 (0.151) | 0.017 (0.139) | 0.017 (0.055) |

Sphere recovery per station, case A: 0.007 mm at 300 mm, 0.012 at 357, 0.015 at 424, 0.019 at 505,
0.025 at 600, 0.038 at 714, 0.053 at 849, 0.101 at 1009 and 0.134 at 1100. Every station is below its
D-11 target, 0.1 mm x (z / 500 mm)^2. The far stations have few held-out poses (4 and 7), so their numbers
move by tens of percent with the choice of held-out poses. The probe spheres at 950 mm are a fixed test set
and give 0.072 mm against a target of 0.361 mm.

Probe boards not used in the fit, case A: after correction (before correction). Each column heading gives the depth and, in brackets, its target.

| Tilt | 425 mm (0.072) | 600 mm (0.144) | 850 mm (0.289) | 1050 mm (0.441) |
|---|---|---|---|---|
| 30 deg | 0.015 (0.033) | 0.028 (0.041) | 0.055 (0.077) | 0.082 (0.115) |
| 45 deg | 0.018 (0.156) | 0.037 (0.213) | 0.077 (0.286) | 0.109 (0.348) |
| 50 deg | 0.018 (0.240) | 0.037 (0.301) | 0.085 (0.382) | 0.127 (0.459) |
| 55 deg | 0.018 (0.344) | 0.044 (0.412) | 0.105 (0.501) | 0.141 (0.520) |

Every cell is below its target, and none is worse after correction than before. The 55 degree cells at 850
and 1050 mm rest on 12 and 10 samples.

## Limits

- The injected planar field is one the map can represent exactly. The study tests whether the plan
  identifies a known field, not whether the real sensor's errors have the map's form; only the real
  held-out residuals show that.
- RMS values are inverse-variance weighted, which favors the low-noise near samples.
- The smoothing search still chooses its ceiling in cases A and B (see the history above).
