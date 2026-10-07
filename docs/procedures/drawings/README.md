# Stage-1 calibration fixtures: shop drawings

Six dimensioned shop drawings (millimeters, third-angle projection, general
tolerances ISO 2768-mK) for the robot-held depth-sensor calibration fixtures.
Each sheet is a 3300 x 2100 px PNG (200 dpi, landscape) with a plan view, a
section at the same stated scale, a notes block and a title block.

| Drawing | Part | Qty | Scale | File |
|---------|------|-----|-------|------|
| SC1-01 | Adapter plate, sphere A | 1 | 2:1 | `SC1-01_adapter_plate_sphere_A.png` |
| SC1-02 | Adapter plate, sphere B | 1 | 2:1 | `SC1-02_adapter_plate_sphere_B.png` |
| SC1-03 | Stem, sphere A (tip variants S and C, mating hole detail) | 1 | 1:1, details 2:1 | `SC1-03_stem_sphere_A.png` |
| SC1-04 | Stem, sphere B (M20 tip, sphere B interface detail) | 1 | 1:1, detail 2:1 | `SC1-04_stem_sphere_B.png` |
| SC1-05 | Board adapter | 1 | 1:1 | `SC1-05_board_adapter.png` |
| SC1-06 | Three-ball nest base | 1 | 1:1 | `SC1-06_three_ball_nest_base.png` |

SC1-01, SC1-02 and SC1-05 carry the flange-interface note (ISO 9409-1-50-4-M6,
to be confirmed against the chosen robot's flange drawing before machining).

## Regenerate

```
python3 docs/procedures/drawings/make_all.py
```

This needs only `matplotlib` (and `numpy`). It rewrites the six PNG files next to
the scripts and prints the result of an automatic overlap check (text against text
and text against lines); the exit status is 1 if the check finds a problem.

## Layout of the code

| File | Content |
|------|---------|
| `drafting.py` | Shared drafting helpers: sheet, views, dimensions, leaders, hatching, feature control frames, datum symbols, cutting-plane lines, title block, notes, tables |
| `part_01_02_adapter_plates.py` | SC1-01 and SC1-02 (one function, two `AdapterSpec` records) |
| `part_03_04_stems.py` | SC1-03 and SC1-04 (one function, two `StemSpec` records, plus detail views) |
| `part_05_board_adapter.py` | SC1-05 |
| `part_06_nest_base.py` | SC1-06 (sphere seating heights are computed from the ball and pitch-circle constants) |
| `make_all.py` | Runs everything |

Every dimension, tolerance, font size, line width, color and layout coordinate is
a named constant with a comment, at the top of the module that uses it.
