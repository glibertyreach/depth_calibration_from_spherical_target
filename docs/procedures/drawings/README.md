# Stage-1 calibration fixtures: shop drawings

Four active dimensioned shop drawings (millimeters, third-angle projection, general
tolerances ISO 2768-mK) for the robot-held depth-sensor calibration fixtures.
Each sheet is a 3300 x 2100 px PNG (200 dpi, landscape) with a plan view, a
section at the same stated scale, a notes block and a title block.

| Drawing | Part | Qty | Scale | File |
|---------|------|-----|-------|------|
| SC1-02 | Adapter plate, sphere B | 1 | 2:1 | `SC1-02_adapter_plate_sphere_B.png` |
| SC1-04 | Stem, sphere B (M20 tip, sphere B interface detail) | 1 | 1:1, detail 2:1 | `SC1-04_stem_sphere_B.png` |
| SC1-05 | Board adapter | 1 | 1:1 | `SC1-05_board_adapter.png` |
| SC1-06 | Three-ball nest base | 1 | 1:1 | `SC1-06_three_ball_nest_base.png` |

SC1-02 and SC1-05 carry the flange-interface note (ISO 9409-1-50-4-M6,
to be confirmed against the chosen robot's flange drawing before machining).

The purchase order for each active drawing asks the fabricator for an inspection
report of the toleranced features (decision D-18); the in-house checks are listed in
section 1d of the capture procedure.

## Archived drawings

SC1-01 (adapter plate, sphere A) and SC1-03 (stem, sphere A) are in `archive/`.
They were retired on 2026-10-08, when the calibration moved to one sphere, sphere B
(decision D-15 of the analysis). Their numbers are not reused, and the remaining
drawings keep their numbers, because the plane-registration and performance-testing
projects cite SC1-02, SC1-04 and SC1-05.

## Regenerate

```
python3 docs/procedures/drawings/make_all.py
```

Add `--archived` to redraw SC1-01 and SC1-03 into `archive/` as well.

This needs only `matplotlib` (and `numpy`). It rewrites the four active PNG files next to
the scripts and prints the result of an automatic overlap check (text against text
and text against lines); the exit status is 1 if the check finds a problem.

## Layout of the code

| File | Content |
|------|---------|
| `drafting.py` | Shared drafting helpers: sheet, views, dimensions, leaders, hatching, feature control frames, datum symbols, cutting-plane lines, title block, notes, tables |
| `part_01_02_adapter_plates.py` | SC1-02, and archived SC1-01 (one function, two `AdapterSpec` records) |
| `part_03_04_stems.py` | SC1-04, and archived SC1-03 (one function, two `StemSpec` records, plus detail views) |
| `part_05_board_adapter.py` | SC1-05 |
| `part_06_nest_base.py` | SC1-06 (the sphere's seating height is computed from the ball and pitch-circle constants) |
| `make_all.py` | Draws the active sheets; `--archived` also draws SC1-01 and SC1-03 |

Every dimension, tolerance, font size, line width, color and layout coordinate is
a named constant with a comment, at the top of the module that uses it.
