# Chat record (compacted): stage-1 depth-sensor calibration

Repository `glibertyreach/depth_calibration_from_spherical_target`, branch
`claude/vibrant-bardeen-160g78`. Session of 2026-10-03 to 2026-10-07.

This is a compacted record of the discussion: what was asked, what was
decided and what was delivered. The full text of every message, without tool
calls, is in `archive/2026-10-07_stage1_full_text_transcript.md`.

## 1. Outcome in brief

- A problem analysis for correcting the depth sensor's range and normals from
  spheres and a commanded flat board, with a numbered decision log (D-1 to
  D-14), a literature review of active-stereo error models, and a theory-neutral
  B-spline correction model.
- A Python data-analysis package (`sphcal`): capture reading, sample building,
  a penalized B-spline fit with pose-grouped cross-validation, the
  sensor-to-robot transform alternation, a no-read model, a validation report
  including robot-independent shape checks, and command-line tools for
  planning poses, building the manifest and checking captures. Fit time was
  cut from 577 s to about 64 s for the full-resolution synthetic set. Test
  suite: 142 passed, 2 skipped.
- A stage-1 capture procedure for a robot technician, whose section 1 is the
  complete scope of work (in hand, build, buy, purchase specifications,
  run-out fixture, preparation), with appendices for suppliers, software,
  installation and six dimensioned shop drawings (SC1-01 to SC1-06).
- Two PowerPoint decks of 15 slides each: procurement and mechanical build;
  test procedure and robot program.
- A reusable skill, `procedure-docs`, carrying the method to two similar
  projects.

## 2. The discussion in order

### Analysis (2026-10-03 to 2026-10-04)

1. The user posed the problem: systematic depth and normal errors of a
   binocular active-stereo sensor on sloped surfaces, to be corrected from
   observations of a sphere of known radius at known poses, as a fast
   high-dimensional B-spline over (h, v, z, normal). Asked for ambiguities,
   differences of opinion, measurement density and B-spline complexity.
   Later points: normal bias follows from slope-dependent depth error;
   rectification errors also tilt normals; no-reads beyond about 55 degrees;
   the specification's sensor model is indicative only; the method and the
   correction model must be theory-neutral; the input set is presumed general.
   Also asked for a literature search and the best sphere radius.
2. Decisions given by the user and recorded as D-1 to D-12: sensor-frame
   output; tilted board acceptable; staged acquisition (hundreds, then
   thousands); native pixels; 0.1 mm at 500 mm, scaling with standoff; board
   pose commanded; full frustum 300 to 1,100 mm; 5 x 5 plane-fit normals;
   positioner accuracy 0.1 mm; two radii with curvature as an input;
   normal-bias acceptance 0.5 degrees to 45 degrees and 1.0 degree to 60.
   A French-curve target was assessed and set aside.
3. Code: Python for analysis, Lisp later for map evaluation; both pose
   sources (header and separate manifest). The fitting method was explained
   (cubic tensor-product terms, second-difference penalties, sparse solve,
   robust reweighting, pose-grouped cross-validation).
4. Fit time reduced to about 64 s; the GPU in the pose-determination
   specification was found unnecessary for the fit.

### Capture procedure (2026-10-04 to 2026-10-06)

5. A cookbook stage-1 procedure: manifest format, robot poses, sphere tool
   center point by a three-ball nest, sphere-stem-flange mounting. Tools
   finished, docx versions with explicit figure widths, analysis docx,
   supplier list, software appendix with the exact file set, and a
   step-by-step install appendix.
6. Sphere specifications and prices were researched. Findings: no
   pre-tapped precision sphere exists above 1.5 inch; hardened balls cannot
   be tapped; "chrome steel" is an alloy name, but every bearing ball is
   mirror-bright and must be made matte. The Rothbucher RSLB10M (145 mm,
   sphericity 0.3 mm) was assessed as at most a provisional far-range sphere.
7. Decisions of 2026-10-06: sphere choice waits for a market canvass;
   diameter known to 0.025 mm (D-13); a cost column; no two-sphere ball bar
   (D-14), so robot-independent shape checks were added to the validation
   report (free-radius sphere fit with its standard error, board flatness).
   The user's own 6 mm board-thickness change was kept.

### Decks and scope of work (2026-10-07)

8. One overview deck was built, then reshaped by review into two decks:
   procurement and mechanical build; test procedure and robot program.
   Figures enlarged (the mounting slide split in two, panel titles cropped
   off); no ball-bar mention; no open-items, decided or next-steps slide;
   suppliers slide in deck 1; tool-center-point and board-frame setup in
   deck 2; a robot-program slide stating that the program can be written with
   Claude Code once the robot is settled.
9. Second review round, collected and then executed together:
   - "(found in 3b)" removed from the sphere-end drawings;
   - sphere diameters measured in-house by outside micrometer, not by a
     laboratory, in the decks, the procedure and D-13;
   - sphericity 0.02 mm for both spheres;
   - dimensioned shop drawings to ISO 9409-1-50-4-M6 (read from ISO
     9409-1:1996 table 1), as PNG files outside the decks, with the speaker
     notes saying where they are;
   - purchase specifications for the spheres and the flat plate;
   - sourcing and mounting for the run-out dial indicator;
   - one consolidated list of everything to build and buy, including the
     rigid sensor mount (from the user's existing drawing);
   - every preparation item made explicit: robot accuracy checked against its
     documented specification; tool load data; robot program; capture trigger
     through the user's communication software; pose-log location noted; dry
     run; safety review; exposure, gain and SGM parameters (smoothing filters
     off, installation patch size); disk space; analysis software; layout
     study; table holes; base frame; micrometer setting standards; a phone
     camera. Lighting control and file transfer were dropped as unnecessary
     in the user's lab.
10. Review of the delivered drawings corrected the board-adapter flange
    screws to M6 x 12 and stated the stem stock (25 and 46 mm bar, body
    ground). Review of the decks placed the plate drawing's pads as on SC1-05.
11. The method was captured in a skill for the user's two similar projects,
    first named `calibration-docs`, then renamed `procedure-docs`, with a
    suggested starting prompt that points new sessions at this repository.

## 3. Decisions in force

| Id | Decision |
|---|---|
| D-1 to D-12 | As listed in section 2, item 2 |
| D-13 | Sphere diameters known to 0.025 mm, measured in-house by outside micrometer at six or more orientations after the matte finish; sphericity 0.02 mm for both spheres |
| D-14 | No two-sphere ball bar; robot-independent shape checks on the held-out poses instead |
| Open | Which precision spheres to buy, pending a market canvass |

## 4. Deliverables and where they are

| Deliverable | Path |
|---|---|
| Problem analysis (Markdown, docx, figures) | `docs/analysis/` |
| Code design | `docs/design/code_design.md` |
| Python package and tests | `sphcal/`, `tests/` |
| Stage-1 capture procedure (Markdown, docx) | `docs/procedures/stage1_capture_procedure.md`, `.docx` |
| Shop drawings SC1-01 to SC1-06 and their scripts | `docs/procedures/drawings/` |
| Procurement and build deck | `docs/presentations/stage1_procurement_build.pptx` |
| Test procedure deck | `docs/presentations/stage1_test_procedure.pptx` |
| Deck generator, content files, rebuild notes | `docs/presentations/build/` |
| Archived earlier versions and render checks | `archive/` folders beside each document |
| `procedure-docs` skill | delivered as `procedure-docs.skill`; not in the repository |

## 5. Known limitations and points to confirm

- The no-read onset reads about 8 degrees high on spheres (exact on boards).
- The fit has been run on synthetic data only.
- Drawing points for the machine shop: DIN 76 thread undercuts and lead
  chamfers; on SC1-02 the screws go in before the stem; SC1-05 uses general
  tolerances for pins and pads.
- Deck renders were checked with metric-compatible stand-ins for Cambria and
  Calibri, not in PowerPoint itself.
- The `procedure-docs` skill has not yet been tested on a real prompt.

## 6. Commits on the branch

| Commit | Date | Message |
|---|---|---|
| `a9afb3a` | 2026-10-03 | Add problem analysis for sphere-based depth and normal calibration |
| `658b812` | 2026-10-03 | Refine sphere-radius bounds: show relaxed design and near-range conflict |
| `ad02be6` | 2026-10-03 | Add literature review of active-stereo error models with design implications |
| `9a882cb` | 2026-10-04 | Record decisions: sensor-frame output, board target accepted, staged acquisition |
| `26a8630` | 2026-10-04 | Record decisions: native-pixel correction, 0.1 mm target at 500 mm, commanded board pose |
| `0b62789` | 2026-10-04 | Record decisions: full-frustum volume and 5x5 normal estimator; regenerate coverage figure |
| `2a29d1a` | 2026-10-04 | Record decisions: positioner accuracy 0.1 mm, two sphere radii with curvature input |
| `b8cc640` | 2026-10-04 | Assess varying-slope profile targets against sphere plus board |
| `bd0e3ed` | 2026-10-04 | Record decisions: target scaling and normal-bias acceptance criterion |
| `9530e12` | 2026-10-04 | Start sphcal package: vendored .mc reader, geometry modules, code design contract |
| `ccf5f66` | 2026-10-04 | Add targets, features, pose I/O, synthetic data, and the calibration integration layer |
| `38a5f51` | 2026-10-04 | Add spline engine, end-to-end fit test, gauge alternation, pooled weights, pose-grouped CV |
| `ea10a3a` | 2026-10-04 | Ignore bytecode caches and remove them from the index |
| `b73e228` | 2026-10-04 | Record integration status and the no-read onset limitation |
| `7fd9c19` | 2026-10-04 | Fixed-design solver: Gram-matrix reuse for CV, robust IRLS and the gauge alternation |
| `500f9e0` | 2026-10-04 | Speed: single edof computation, cached rays, process pool for per-pose features, thinner no-read table |
| `425bea3` | 2026-10-04 | Correct the measured run time in the design note |
| `cc38378` | 2026-10-04 | Add the stage-1 capture procedure for the robot technician, with fixture figure |
| `196c866` | 2026-10-04 | WIP: capture-support tools (plan_poses, make_manifest, check_captures), tests pending |
| `8f6be5f` | 2026-10-04 | Capture-support tools with tests; procedure tuned to the planner output; Word version of the procedure |
| `76301a5` | 2026-10-04 | Procedure docx: explicit figure widths via a pandoc filter and a reproducible build script |
| `1b6269c` | 2026-10-04 | Analysis document as docx with embedded figures; sphere mounting method and detail drawing in the procedure |
| `cc1454b` | 2026-10-04 | Mounting figure: stem label placement |
| `9a145ec` | 2026-10-04 | Procedure: supplier appendix and software reference appendix |
| `364128a` | 2026-10-04 | Track the docx build scripts; declare PNG content type so the docx validates as built |
| `601eabe` | 2026-10-04 | Capture tools no longer import the fit code; appendix B lists their exact file set |
| `f3c9406` | 2026-10-04 | Procedure appendix C: installing and running the tools step by step |
| `540abec` | 2026-10-05 | Relax the board thickness to 6 mm with a finishing caveat |
| `f14eea1` | 2026-10-05 | Procedure: tapping and hardness note, matte finish guidance, pre-tapped availability, Rothbucher sphere assessment |
| `854eeba` | 2026-10-05 | Stage-1 figure: draw the board 6 mm thick, as the procedure specifies |
| `a85d0fa` | 2026-10-06 | Record decisions D-13 and D-14; add estimated costs to the equipment table |
| `e9425bb` | 2026-10-06 | Robot-independent shape checks in the validation report (D-14) |
| `4daaa68` | 2026-10-07 | Fixtures figure: draw sphere A at its 38.1 mm radius |
| `bb27173` | 2026-10-07 | Stage-1 overview deck: slide content and figure panels |
| `fd5336d` | 2026-10-07 | Stage-1 capture overview deck (18 slides, speaker notes) |
| `3901e63` | 2026-10-07 | Split the overview deck: content for a build deck and a test-procedure deck |
| `caa5811` | 2026-10-07 | Two stage-1 decks: procurement and build; test procedure and robot program |
| `5c5ca71` | 2026-10-07 | Scope of work: procedure section 1, micrometer method, specifications, preparation |
| `70b531e` | 2026-10-07 | Interim snapshot: deck generator and decks while new slides are added (unreviewed) |
| `5093525` | 2026-10-07 | Interim snapshot: deck generator iteration (unreviewed) |
| `d13197a` | 2026-10-07 | Decks reviewed: build, buy, specification, run-out and preparation slides |
| `d4285d4` | 2026-10-07 | Interim snapshot: shop-drawing helper module (in progress, unreviewed) |
| `6445334` | 2026-10-07 | Shop drawings SC1-01 to SC1-06 and procedure appendix D |
