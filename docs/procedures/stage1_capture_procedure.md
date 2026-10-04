# Stage-1 calibration captures: step-by-step procedure

Audience: the robot technician who will set up the fixtures, program the
robot, and record the captures. No knowledge of the calibration math is
needed. Where a step says "run", a computer with Python and this repository
is needed; the engineer can run those steps for you if you send the files.

What you are producing: a folder of sensor capture files (`.mc`), one group of
files per robot pose, plus a small table (the manifest) that says, for every
file, which target was in view and exactly where the robot had put it. The
calibration software uses that table to work out the sensor's errors. If the
table is wrong, the calibration is wrong, so most of this procedure is about
getting the table right.

Figure 1 (`figures/fig_fixtures.png`) shows the three fixtures; figure 2 (section 6) shows an example pose plan; figure 3 (section 3a) shows the sphere mounting in section.

![fixtures](figures/fig_fixtures.png)

---

## 1. Equipment

| Item | Requirement | Notes |
|---|---|---|
| Sensor | The depth sensor to be calibrated, rigidly mounted; it must not move during the whole session | Mount on a stiff bracket, not a tripod; mark its position so a bump is noticed |
| Robot | Six-axis industrial robot, absolute positioning accuracy 0.1 mm or better over the working volume, with a 50 mm or larger ISO flange | A robot that has been calibrated by its maker ("absolute accuracy" option) is needed; repeatability alone is not enough |
| Sphere A | Precision sphere, 3 inch (76.2 mm) diameter, matte, with a threaded hole or a bonded stem | Ceramic (zirconia or alumina) with a matte finish, or a steel sphere bead-blasted and matte-painted; certificate stating the diameter to 0.01 mm |
| Sphere B | Precision sphere, 6 inch (152.4 mm) diameter, matte, same construction | Same supplier if possible so the finish matches |
| Stems | One stem per sphere, ground steel, 16 mm diameter for sphere A and 30 mm for sphere B, length at least 2R + 50 mm from the adapter face to the sphere surface (130 mm for A, 205 mm for B), turned shoulder at the adapter end, matte black | Section 3a gives the design; a slender stem sags and moves the sphere center |
| Adapter plates | One per sphere; bolts to the robot flange on its dowel pin, central tapped hole (M12 for A, M20 for B) machined square to the mounting face | Section 3a; use the dowel every time, so the adapter goes back in the same place |
| Board | Flat plate 200 mm x 150 mm, at least 15 mm thick, front face matte and light gray, flat to 0.05 mm | Ground aluminum tooling plate, bead-blasted and matte-painted; or float glass with matte paint; ask the supplier for a flatness report |
| Board adapter | Plate that bolts to the flange with the dowel pins and holds the board with its front face perpendicular to the flange axis and its center on the flange axis | Three-point mounting (two dowels and a clamp) so the board goes back in the same place |
| Three-ball nest | Three hardened balls, about 24 mm diameter, pressed into a base, bolted to the table within reach of the robot | Used once per sphere to find the tool center point (section 3b) |
| Dial indicator with magnetic base | 0.01 mm resolution | Board runout check |
| Capture computer | Runs the sensor's capture software, writes `.mc` files with the sensor's own name in the file name | Must have at least 10 GB free per 1,000 frames |

Optional: a certified two-sphere bar (two matte spheres on a rigid bar, center-to-center distance known to 0.02 mm). It gives an independent check of the result (section 9).

## 2. Before anything else

1. Switch the sensor on and leave it running for at least 30 minutes before the first capture, and leave it running for the whole session. Note the time it was switched on.
2. Fix the sensor's exposure and gain to the values that will be used in production. Write them down. Do not use automatic exposure.
3. Switch off or block any sunlight or lamps that fall on the targets. Room light is fine if it is constant.
4. Confirm with the engineer what the robot base frame is (which frame the robot's position readout is in). Every pose in this procedure is recorded in that frame. Do not change the active base frame during the session.
5. Record in a text file (`session_notes.txt`): date, sensor serial number, exposure and gain, robot model and controller software version, the active base frame name, the sphere and board certificates (diameter, flatness), room temperature, and anything unusual.

## 3. Mounting the spheres and finding their tool center points

### 3a. Suggested mounting: flange, adapter, stem, sphere

Figure 1a shows the arrangement and figure 3 the joint details. The goal is a
stiff, repeatable chain from the robot flange to the sphere center; where the
center ends up does not need to be known from drawings, because the tool
center point routine (3b) measures it, but it must not move afterwards.

![mounting](figures/fig_mounting_detail.png)

Figure 3. Section through the sphere mounting: adapter plate on the flange's dowel and bolts, stem with a turned shoulder seated on the adapter face, and the sphere end either threaded into the sphere's insert (ceramic spheres) or bonded into a reamed blind hole (steel spheres).

1. Adapter plate. One plate per sphere, steel or aluminum, 12 mm thick, drilled to the robot's flange pattern (for a 50 mm ISO 9409-1 flange: four M6 on a 50 mm circle and one 6 mm dowel) with a central tapped hole for the stem: M12 for sphere A, M20 for sphere B. Have the plate's mounting face, its outer face and the tapped hole machined in one lathe setup, located on the flange pilot diameter, so the hole is perpendicular to the mounting face within 0.02 mm over 100 mm. Always mount it on the dowel; the dowel is what makes a remount land in the same place.
2. Stem. Ground steel rod (drill rod or silver steel): 16 mm diameter for sphere A, 30 mm for sphere B. These are thicker than the earlier rule of thumb on purpose: the sphere's weight at the end of a slender stem sags by about 0.07 mm on a 12 mm stem for sphere A and 0.1 mm on a 25 mm stem for sphere B, which would change with the robot's orientation; at 16 and 30 mm the sag is 0.02 to 0.05 mm. Length from the adapter face to the sphere surface at least 2R plus 50 mm (130 mm for A, 205 mm for B). At the adapter end turn a threaded spigot (M12 x 15 mm, M20 x 25 mm) behind a shoulder at least 1.5 times the stem diameter across; the shoulder face, machined square to the stem axis in the same setup as the thread, seats on the adapter and sets the stem perpendicular. Tighten to a moderate, recorded torque; a jam nut is optional. Make a witness mark across stem and adapter so a loosened joint is visible. Finish the stem matte black (bluing or matte paint).
3. Sphere end, ceramic spheres (preferred). Precision ceramic spheres are sold with a threaded insert (typically M6 or M8) bonded in by the maker. Turn the stem tip to a matching threaded spigot with a small shoulder that seats on the flat around the insert; add a drop of medium-strength thread locker and tighten by hand plus a quarter turn. Do not clamp the sphere in a vise; hold the stem.
4. Sphere end, steel spheres. Drill and ream a blind hole along any radius to about 0.6 R deep, sized for a light press fit on the stem tip (H7/p6), and bond with an anaerobic retaining compound (for example a high-strength bearing retainer). Do not weld or braze; the heat distorts the sphere. The hole does not have to be exactly radial, since the routine of 3b measures the center wherever it ends up.
5. Weight. Sphere A in ceramic weighs about 0.9 kg, in steel 1.8 kg. Sphere B in steel weighs 14.5 kg and is not recommended; in alumina ceramic about 7 kg; a precision-turned aluminum sphere with a matte hard-anodized surface weighs about 5 kg and is the practical choice if a supplier can certify its radius to 0.01 mm. Check the robot's payload rating against the sphere, stem and adapter together.
6. Finish. A matte, light, uniform surface on both spheres, the same finish on both. Polished steel is unusable (it returns one bright highlight from the sensor's projector and little else); if a steel sphere is used, have it bead-blasted and matte-painted, and re-measure its radius afterwards, since paint adds thickness.
7. Handling. Keep each sphere in a padded case with its stem fitted. Never set a sphere down on its surface on a hard table. Wipe with isopropyl alcohol before a session.
8. Repeatability. After any remount of the adapter or stem, re-run the nest check (3b, step 8) before capturing. The joint is good if the two readings agree within 0.1 mm.

### 3b. Finding the tool center point of each sphere

The calibration needs to know where the center of the sphere is for every robot pose. The robot reports where its tool center point (TCP) is, so the TCP must be set to the center of the sphere. The robot cannot see the sphere, so the TCP is found mechanically, with the three-ball nest.

Why the nest works: a sphere resting on three fixed balls always has its center at the same point in space, whatever direction its stem points. The robot's built-in multi-orientation TCP routine ("4-point method", "TCP by touch-up", or similar name depending on the robot brand) finds the one point on the tool that stays still while the wrist turns. Seating the sphere in the nest from several directions makes that point the sphere's center.

1. Bolt the nest to the table at a height the robot reaches comfortably with the wrist pointing down and tilted about 40 degrees to either side.
2. Mount sphere A's adapter and stem on the flange with the dowel pins. Tighten to the normal torque.
3. Enter a rough TCP first so the robot moves sensibly: the TCP is on the flange axis at a distance from the flange face equal to adapter thickness plus stem length plus the sphere radius. Measure these with calipers and enter the sum as the tool z offset, x and y zero.
4. Start the robot's multi-orientation TCP routine. For each of its points (use at least six if the controller allows more than four): jog the robot so that the sphere settles into the nest, touching all three balls, with the stem in a different direction each time: straight up, tilted 40 degrees forward, backward, left, right, and one twisted about the stem. Settle the sphere by lowering it slowly the last millimeter; do not press down hard, the stem will bend. Confirm the point.
5. The routine reports a TCP and usually an error figure. Accept it only if the error is 0.1 mm or less. If it is larger, repeat; the usual causes are the sphere not fully seated, or a loose adapter.
6. Save the TCP under a clear name, for example `TCP_SPHERE_A_76mm`. Write the numbers in the session notes.
7. Repeat steps 2 to 6 for sphere B, saving `TCP_SPHERE_B_152mm`.
8. Check: with the TCP active, seat the sphere in the nest and read the robot's position. Lift out, re-seat with a very different wrist orientation, read again. The two positions must agree within 0.1 mm. If they do not, the TCP is wrong; repeat the routine.

## 4. Setting up the board and its tool frame

The board's "tool frame" is a coordinate frame at the center of the board's front face, with its z axis pointing straight out of the face (toward the sensor when the board faces it), x along the long edge, y along the short edge. The robot must report the board's pose in this frame.

1. Mount the board adapter and the board on the flange with the dowel pins.
2. Runout check (figure 1c): fix the dial indicator to the table with its tip on the board's front face about 20 mm from an edge. Slowly rotate the flange about its own axis (robot joint 6) through 360 degrees. The reading must stay within 0.05 mm. If it does not, the board face is not perpendicular to the flange axis: shim the adapter and repeat.
3. Measure the distance from the flange face to the board's front face with a depth gauge or calipers at four places around the board; they should agree within 0.05 mm. Record the average as D.
4. Measure the board's width and height with calipers and record them. The half-sizes go in the manifest (100 and 75 mm for the recommended board).
5. Define the tool frame in the robot: position (0, 0, D) from the flange, orientation: z along the flange axis pointing out of the board, x along the board's long edge. How to set x: with the robot's "tool orientation by points" function, teach a point at the center of the long edge, or enter the rotation about z that aligns x with the long edge, after measuring with a square against the adapter. An error of a few degrees in x is harmless (the board is symmetric); an error in z is not.
6. Save as `TOOL_BOARD` and write the numbers in the session notes.

## 5. Finding where the sensor is (rough)

The software works out the exact position of the sensor from the captures. It only needs a rough idea first, so that the robot poses land in the sensor's field of view. This step takes a few captures of sphere A at hand-chosen positions.

1. With sphere A and its TCP active, jog the sphere to a point roughly in front of the sensor, about 500 mm away, near the middle of the picture. Check on the capture computer's live view that the whole sphere is visible with margin.
2. Record a capture (one frame is enough) and write down the robot's reported TCP position (x, y, z in the base frame). Name the file `boot01_Index00.mc`.
3. Move the sphere about 150 mm to the robot's left (as seen in the sensor image), still fully in view; capture `boot02_Index00.mc`, record the position. Then about 150 mm up: `boot03`. Then about 250 mm farther from the sensor: `boot04`. Four points, not in a line.
4. Run the sphere-center fit on these files and the plan tool in bootstrap mode (the engineer can do this):

```
python3 -m sphcal.cli.check_captures --manifest boot_manifest.csv --out boot_check.json
python3 -m sphcal.cli.plan_poses --sensor-in-base boot.json --camera boot01_Index00.mc \
    --near-radius-mm 38.1 --far-radius-mm 76.2 --fov-fill 0.7 \
    --board-half-size-mm 100 75 --board-lateral-fill 0.2 --out plan/
```

(Use the certified radii of your spheres in place of 38.1 and 76.2, and your board's half-sizes in place of 100 75.)

`boot.json` lists, for each bootstrap capture, the robot position you wrote down and the sphere center the check tool found in the sensor's frame:

```json
{"bootstrap": [
  {"pose_id": "boot01", "base_xyz": [812.4, -103.2, 455.0], "sensor_xyz": [12.1, -4.4, 498.7]},
  {"pose_id": "boot02", "base_xyz": [812.9, 46.5, 455.3], "sensor_xyz": [-137.6, -4.1, 499.2]},
  {"pose_id": "boot03", "base_xyz": [811.8, -103.0, 605.1], "sensor_xyz": [12.6, -154.2, 497.9]},
  {"pose_id": "boot04", "base_xyz": [1061.7, -102.8, 456.2], "sensor_xyz": [11.9, -4.9, 748.3]}
]}
```

The plan tool prints the residual of each pair. They should be a few millimeters at most; a residual of tens of millimeters means a position was copied wrongly or the TCP is wrong.

## 6. The pose plan

The plan tool writes `plan/poses.csv`, `plan/plan_summary.txt` and a picture `plan/plan.png` of where the targets will be (figure 2 shows the picture for the settings above and the sensor's 49.9 x 38.5 degree field). The plan with the settings above is:

- Sphere A (76.2 mm diameter) on three depth planes at 300, 425 and 550 mm from the sensor, centers on a grid with a spacing of 1.5 radii (57 mm) covering 70 percent of the field of view at each depth: 90 poses.
- Sphere B (152.4 mm diameter) on four depth planes at 500, 700, 900 and 1,100 mm, grid spacing 114 mm: 57 poses. Both spheres are used around 500 to 550 mm.
- The board at four depths (350, 550, 800, 1,050 mm), facing the sensor and tilted 0, 20 and 40 degrees about two directions, at two lateral positions per depth: 39 poses. Tilted boards that would leave the field of view are dropped automatically (one at 350 mm with these settings).
- About 20 percent of poses are marked `holdout` in the table; capture them like all the others, the software keeps them for checking.

The total is 186 poses. A handful of the outermost sphere poses (6 with these settings) may have their silhouette touching the image border; the check in section 8 flags them, and they are simply left out of the fit. At about 8 seconds per pose the robot time is about 25 minutes, so plan on about two hours including fixture changes and the checks.

![plan](figures/fig_plan_example.png)

Figure 2. The planned sphere centers and board centers for the settings above, in the sensor's frame: side view (left) and front view (right), with the field of view drawn.

Every row of `poses.csv` gives: `pose_id`, `kind` (sphere or board), the target size, the position of the TCP in the base frame (`base_x_mm`, `base_y_mm`, `base_z_mm`), and the tool orientation three ways (rotation matrix `r00..r22`, quaternion `quat_w..quat_z`, rotation vector `rotvec_x_deg..`); use whichever your robot program accepts. For spheres the orientation points the stem away from the sensor so that the sphere hides it; for boards it is the board frame orientation, tilt included. Hand the file to whoever writes the robot program, or import it directly if the controller can read CSV.

Robot program outline, for each row of the file:

1. Move to the pose (joint move to a point 100 mm short of it along the stem axis, then a linear move onto it, so the approach is the same every time).
2. Wait 1.5 seconds for vibration to settle.
3. Trigger the capture of 5 frames; file names `<pose_id>_Index00.mc` to `<pose_id>_Index04.mc`.
4. Read the robot's actual reported TCP pose (not the commanded one, the reported one) and append it to the pose log (section 7).
5. Move on.

Do all sphere A poses, change to sphere B (remember to activate `TCP_SPHERE_B_152mm`), do all sphere B poses, change to the board (activate `TOOL_BOARD`), do all board poses. Do not move the sensor between these.

## 7. Recording the poses: the pose log and the manifest

The capture software writes the sensor data. The pose must be recorded separately, in one of two ways. Both are supported; use the first if the capture software can do it.

Option A, pose in the file header. If the capture software can be given the robot's pose at capture time, it writes it into the file's header under the key `robotPose` as a 4 x 4 matrix (16 numbers, row by row: rotation in the top-left 3 x 3, position in the right column, last row 0 0 0 1), tool frame to base frame. Then no separate log is needed beyond the target sizes, and the software reads the poses from the files.

Option B, pose log plus manifest (preferred when option A is not available, and recommended anyway as a backup). The robot program appends one line per pose to a CSV file, the pose log, with these columns:

```
pose_id, kind, radius_mm, half_width_mm, half_height_mm, x_mm, y_mm, z_mm, rotation_type, r1, r2, r3, r4
```

- `pose_id`: exactly the id from `poses.csv`, which is also the start of the file names.
- `kind`: `sphere` or `board`.
- `radius_mm`: the certified radius for a sphere (38.10 for sphere A, 76.20 for sphere B), empty for a board.
- `half_width_mm`, `half_height_mm`: half the measured board size, empty for a sphere.
- `x_mm`, `y_mm`, `z_mm`: the reported TCP position in the base frame.
- `rotation_type` and `r1..r4`: the reported tool orientation, in whatever form the controller gives, named by one of: `quaternion_wxyz`, `quaternion_xyzw`, `euler_zyx_deg` (KUKA A, B, C), `fixed_xyz_deg` (FANUC W, P, R), `euler_xyz_deg`, `rotvec_deg`, or `none` for a sphere (its orientation does not matter). Fill unused r columns with nothing.

Example lines:

```
s038_z0425_017,sphere,38.10,,,812.40,-33.21,455.02,none,,,,
b_z0550_t20_a090_1,board,,100.0,75.0,850.11,-12.70,470.55,euler_zyx_deg,-91.3,19.8,0.4,
```

After the session, the manifest is built from the pose log and the capture folder:

```
python3 -m sphcal.cli.make_manifest --pose-log pose_log.csv --captures captures/ --format csv --out captures/manifest.csv
```

The tool matches every file to its pose id, converts the orientation to the standard matrix form, and complains, by name, about any pose without files, any file without a pose, and any missing size. A pose without files or a file without a pose is a warning and the pose is left out; add `--strict` to make them errors. Row problems (a sphere without a radius, a board without a size or with rotation type `none`) stop the tool and nothing is written. Fix what it names and run it again. A `poses.csv` from the plan tool is also accepted directly as the pose log if your robot program cannot write one; then the commanded poses stand in for the reported ones, which is acceptable only for a robot with absolute accuracy better than 0.1 mm. The manifest it writes is the file the calibration reads; keep the pose log too.

What the manifest contains, for reference: one line per frame, with the file name, the pose id, the frame number, the target kind and size, and the pose as the twelve numbers of the top three rows of the 4 x 4 matrix (`m00..m23`), tool frame to base frame. A JSON form of the same content exists for software that prefers it.

## 8. Checking the captures before the fit

Run the quick check as soon as the captures are complete, while the robot and fixtures are still set up:

```
python3 -m sphcal.cli.check_captures --manifest captures/manifest.csv --out captures/check.json
```

It prints one line per pose and a verdict. Things it flags, and what they mean:

- Low valid fraction (below 50 percent of frames): the target was not read; check exposure, or the target was outside the field.
- Valid region touching the image border: the target is partly out of view; the pose is unusable, re-plan it slightly inward.
- Sphere center residual above 2 mm against the commanded position: either the robot position was copied wrongly for that pose, or, if it affects every pose of one sphere, that sphere's TCP is wrong (section 3b); or, if it grows steadily across the volume, the robot's base frame or its absolute accuracy is off.
- Board normal more than 2 degrees from the commanded direction: the board tool frame's orientation is wrong (section 4, step 5) or the rotation type in the pose log is misnamed.

Re-capture flagged poses after fixing the cause; do not delete the lines from the log, add corrected lines with a new pose id (for example `s038_z0425_017r`). The check tool's exit code is 0 when nothing is flagged, 1 when something is, and 2 when it cannot read the manifest.

## 9. Optional independent check with a two-sphere bar

If a certified ball bar is available: mount it on the flange in place of a sphere (no TCP needed), and capture it at five poses spread over the volume, two frames each, with pose ids `bar01` to `bar05` and `kind` set to `sphere` with the radius of its spheres and the position left at zero. The engineer will fit both spheres in each capture before and after correction; the corrected center-to-center distance must agree with the certificate to within the stated target. This check is independent of the robot's accuracy, which is why it is worth the extra half hour.

## 10. Deliverables checklist

- [ ] `captures/` with all `.mc` files, named `<pose_id>_Index<nn>.mc`
- [ ] `pose_log.csv` (option B) or confirmation that headers carry `robotPose` (option A)
- [ ] `captures/manifest.csv` produced by `make_manifest` without errors
- [ ] `captures/check.json` with no flags, or a note explaining each remaining flag
- [ ] `plan/poses.csv`, `plan/plan_summary.txt`, `plan/plan.png` as used
- [ ] `boot.json` and the bootstrap captures
- [ ] `session_notes.txt` with: sensor serial, warm-up time, exposure and gain, base frame name, TCP values and their routine errors, board D and runout reading, board dimensions, sphere certificates, temperature, fixture changes with times
- [ ] Photos of the setup: sensor mount, each fixture on the flange, the nest

## 11. Things that spoil a session

- Moving or bumping the sensor. If it happens, everything after it is a new session.
- Changing exposure, gain, or the base frame mid-session.
- Using the commanded pose instead of the reported pose in the log.
- A loose adapter or a bent stem: check the stem is straight by rolling it on a flat surface before mounting.
- Fingerprints or gloss on the sphere or board: wipe with isopropyl alcohol; a shiny spot returns a bright highlight and a bad read.
- Letting the stem point toward the sensor: the sphere must hide the stem. The plan sets the orientation for this; do not override it.
- Mixing up the two spheres' radii in the pose log.
