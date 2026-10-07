# Stage-1 calibration captures: step-by-step procedure

Audience: the robot technician who will set up the fixtures, program the
robot, and record the captures. No knowledge of the calibration math is
needed. Where a step says "run", a computer with Python and this repository
is needed (appendix C says how to set it up); the engineer can run those steps for you if you send the files.

What you are producing: a folder of sensor capture files (`.mc`), one group of
files per robot pose, plus a small table (the manifest) that says, for every
file, which target was in view and exactly where the robot had put it. The
calibration software uses that table to work out the sensor's errors. If the
table is wrong, the calibration is wrong, so most of this procedure is about
getting the table right.

Figure 1 (`figures/fig_fixtures.png`) shows the three fixtures; figure 2 (section 6) shows an example pose plan; figure 3 (section 3a) shows the sphere mounting in section.

![fixtures](figures/fig_fixtures.png)

---

## 1. Scope of work and equipment

This section is the complete list of what must exist before the first session: what is already in hand, what must be built, what must be bought, and what must be prepared. Nothing outside this list is needed. Appendix D holds the shop drawings; appendix A lists suppliers.

### 1a. Already in hand

| Item | Requirement |
|---|---|
| Sensor | The depth sensor to be calibrated |
| Robot | Six-axis industrial robot with an ISO 9409-1-50-4-M6 tool flange; its documented absolute positioning accuracy must be 0.1 mm or better over the working volume (check the maker's specification sheet; repeatability alone is not enough) |
| Capture computer and software | Runs the sensor's capture and communication software, which also accepts the capture trigger from the robot program; writes `.mc` files; at least 10 GB free per 1,000 frames |
| Analysis computer | Any computer with Python 3.10 or later and the calibration software installed, its self-test passed (appendix C) |

### 1b. What must be built

| Item | Quantity | Description | Drawing | Estimated cost (USD) |
|---|---|---|---|---|
| Sphere A with mounting interface | 1 | 76.2 mm matte sphere; specification in 1d; steel ball with a bonded stem, or ceramic with the maker's insert | SC1-03 (hole detail) | $250 to $550 |
| Sphere B with mounting interface | 1 | 152.4 mm matte sphere; specification in 1d; turned aluminum with the M20 thread cut in | SC1-04 (interface detail) | $500 to $1,500 |
| Sphere-flange mounts | 2 adapter plates, 2 stems | Doweled adapter plate on the ISO flange, shouldered ground stem; section 3a | SC1-01, SC1-02, SC1-03, SC1-04 | $400 to $1,000 |
| Flat target (board) | 1 | 200 x 150 mm plate; specification in 1d | SC1-05 (outline) | $50 to $400 |
| Flat-target mount (board adapter) | 1 | Plate on the ISO flange with three support pads, three edge pins and three clamp fingers; holds the board square to the flange axis and centered on it | SC1-05 | $250 to $600 |
| Three-ball bed (nest) | 1 | Steel base with three 24 mm balls, bolted to the cell table; section 3b | SC1-06 | $150 to $450 |
| Run-out fixture | 1 | Dial indicator on a magnetic base, standing on a steel base plate bolted to the table; section 1e | none needed | $240 to $570 |
| Rigid sensor mount | 1 | Stiff bracket holding the sensor for the whole session, not a tripod; position marked so a bump is noticed | Existing drawing from previous work | not estimated |

### 1c. What must be bought

| Item | Purpose | Estimated cost (USD) |
|---|---|---|
| Outside micrometers, 75 to 100 mm and 150 to 175 mm (for example Mitutoyo 103-140-10 and 103-143-10), with their setting standards | Sphere diameters, measured in-house after the matte finish; the setting standards check the micrometers before use | $405 to $520 |
| Calipers with depth rod, 150 mm | Rough TCP length; board distance D | $30 to $150 |
| Precision straightedge, 300 mm (DIN 874 grade 0 or better), and feeler gauges | Board flatness after painting and mounting (a 0.05 mm leaf must not pass under the edge); stem straightness | $75 to $240 |
| Thermometer | Room temperature at sphere measurement and during the session | $15 to $40 |
| Machinist's square | Board x axis against the adapter | $30 to $80 |
| Torque wrench | Recorded stem and adapter torques | $80 to $250 |
| Consumables | Medium-strength thread locker, anaerobic retaining compound, shim stock, isopropyl alcohol and wipes, padded cases for the spheres | $50 to $150 |
| Phone camera | Setup photos for the deliverables (section 10) | in hand |

Cost estimates (October 2026): building $1,840 to $5,070, buying $685 to $1,430, total $2,525 to $6,500 with a bearing-ball sphere A and an aluminum sphere B, or $4,375 to $11,950 with both spheres made to order by a ball or ceramics maker. They come from suppliers' list prices where these exist (appendix A) and otherwise from typical United States job-shop rates of about $80 to $150 per hour. Treat them as plus or minus 50 percent and get quotes. Sphere B is the least certain figure.

### 1d. Purchase specifications for the spheres and the flat plate

| Requirement | Sphere A | Sphere B |
|---|---|---|
| Nominal diameter | 76.2 mm (3 inch) | 152.4 mm (6 inch) |
| Diameter | Known to 0.025 mm, measured in-house by outside micrometer at no fewer than six orientations after the matte finish; the mean goes in the pose log | Same; aluminum grows 0.0035 mm in diameter per degree C, so measure at the session's room temperature and record it |
| Sphericity | 0.02 mm or better (the spread of the micrometer readings must not exceed it) | 0.02 mm or better |
| Material | Bearing-grade steel ball (52100 or 440C, grade 25 or better) or ceramic (zirconia or alumina) | Turned aluminum (6061-T6 or similar), solid or hollow with at least 6 mm wall; ceramic as an alternative |
| Surface | Matte, light, uniform, free of highlights: fine glass-bead blast (preferred) or thin matte light-gray paint | Matte hard anodize, light gray or natural; same appearance as sphere A |
| Mounting interface | Steel: blind hole 10 H7 x 23 mm along any radius, stem bonded (drawing SC1-03). Ceramic: maker's M8 insert | M20 x 30 mm blind tapped hole at a pole with a 32 mm spot face, cut when the sphere is turned (drawing SC1-04) |
| Approximate mass | 0.9 kg (ceramic) to 1.8 kg (steel) | about 5 kg solid aluminum |

| Requirement | Flat plate (board) |
|---|---|
| Size | 200 x 150 mm, at least 6 mm thick |
| Material | Ground aluminum tooling plate (for example MIC-6, finish-ground) or float glass |
| Flatness | 0.05 mm over the front face, checked with the straightedge and a 0.05 mm feeler leaf after painting and after mounting on the board adapter |
| Front face | Matte light-gray paint, thin and even; do not bead-blast a plate thinner than about 10 mm, since peening one face bows it |
| Edges | Square and clean on the bottom long edge and the left short edge, which rest against the board adapter's edge pins |
| Documents | Supplier's flatness report, kept with the session notes |

### 1e. Run-out fixture: dial indicator and its mounting

The run-out check of section 4 needs the dial indicator held still while the robot turns the board. Use a dial indicator with 0.01 mm graduation and about 10 mm travel (for example Mitutoyo 2046 series, about $50 to $150) on an articulating magnetic base with fine adjustment (for example Noga MG71003 or DG-61003, about $140 to $320). Stand the magnetic base on a steel base plate about 150 x 100 x 12 mm bolted to the cell table with two M8 screws, so the base holds on a non-magnetic table and does not creep. Place the plate where the indicator tip reaches the board's front face about 20 mm from an edge with the robot in its run-out pose. McMaster-Carr and the usual tool suppliers stock all three items.

### 1f. Preparation before the first session

Robot:

- Check the robot's documented absolute-accuracy specification: 0.1 mm or better over the working volume.
- Weigh each fixture (sphere A with stem and adapter, sphere B with stem and adapter, board with its adapter) and enter its tool load data (mass and center of gravity) in the controller; wrong load data shifts every pose.
- Write the robot program to the interface in section 6: it reads `poses.csv`, triggers captures through the capture computer's communication software, and writes `pose_log.csv`. Note where the program writes `pose_log.csv` (controller storage or a network location) so it can be collected after the session. Once the robot model and controller are settled, the program can be written with Claude Code.
- Dry-run every planned pose at reduced speed, without capturing, to confirm each is reachable and clears the sensor, its mount and its cables.
- Review the new program under the cell's safety rules.

Sensor and computers:

- Set up the capture software for the robot's trigger and the `<pose_id>_IndexNN` file names (writing the robot pose into the header is optional, section 7).
- Choose and record the production exposure and gain, and the SGM parameters: all smoothing filters off, and the patch size the same as in installations.
- Free at least 10 GB per 1,000 frames on the capture computer (a session is about 930 frames).
- Install the calibration software on the analysis computer and pass its self-test (appendix C).

Cell:

- Layout study: place the sensor so that the 300 to 1,100 mm volume lies inside the robot's reach at the orientations the plan needs; do this before the sensor mount is fixed.
- Drill and tap the cell table for the nest (four M8) and the run-out base plate (two M8).
- Identify and record the robot base frame used for the session.

No two-sphere ball bar is used; section 9 describes the checks that take its place.

## 2. Before anything else

1. Switch the sensor on and leave it running for at least 30 minutes before the first capture, and leave it running for the whole session. Note the time it was switched on.
2. Fix the sensor's exposure and gain to the values that will be used in production, and set the SGM (semi-global matching) parameters: all smoothing filters off, and the patch size the same as in installations. Write all of them down. Do not use automatic exposure.
3. Keep direct sunlight off the targets. The lab's normal, constant room light is fine; no other lighting control is needed.
4. Confirm with the engineer what the robot base frame is (which frame the robot's position readout is in). Every pose in this procedure is recorded in that frame. Do not change the active base frame during the session.
5. Record in a text file (`session_notes.txt`): date, sensor serial number, exposure, gain and SGM parameters, robot model and controller software version, the active base frame name, the measured sphere diameters with the room temperature at measurement, the board's flatness report, room temperature, and anything unusual.

## 3. Mounting the spheres and finding their tool center points

### 3a. Suggested mounting: flange, adapter, stem, sphere

Figure 1a shows the arrangement and figure 3 the joint details; the dimensioned shop drawings SC1-01 to SC1-04 in appendix D are the ones to build from. The goal is a
stiff, repeatable chain from the robot flange to the sphere center; where the
center ends up does not need to be known from drawings, because the tool
center point routine (3b) measures it, but it must not move afterwards.

![mounting](figures/fig_mounting_detail.png)

Figure 3. Section through the sphere mounting: adapter plate on the flange's dowel and bolts, stem with a turned shoulder seated on the adapter face, and the sphere end either threaded into the sphere's insert (ceramic spheres) or bonded into a reamed blind hole (steel spheres).

1. Adapter plate (drawings SC1-01 and SC1-02). One plate per sphere, steel or aluminum, 63 mm diameter, 16 mm thick for sphere A and 22 mm for sphere B, with a 31.5 mm centering spigot 5 mm high that fits the flange's centering recess (ISO 9409-1-50-4-M6: four M6 on a 50 mm circle, one 6 mm locating pin hole on that circle, 31.5 mm H7 recess). One 6 mm dowel pin pressed into the plate engages the flange's pin hole; four counterbored holes take M6 x 16 low-head screws. The central thread for the stem is M12 for sphere A and M20 for sphere B. Have the faces, the spigot and the thread machined in one setup, so the thread is perpendicular to the stem-side face within 0.02 mm over 100 mm. Always mount the plate on its dowel; the dowel is what makes a remount land in the same place.
2. Stem. Steel (silver steel 1.2210 or 4140 pre-hardened), turned from 25 mm bar for sphere A and 46 mm bar for sphere B, with the body ground to 16 mm h6 and 30 mm h6 after turning, so the shoulder and the ground body come from one piece. These are thicker than the earlier rule of thumb on purpose: the sphere's weight at the end of a slender stem sags by about 0.07 mm on a 12 mm stem for sphere A and 0.1 mm on a 25 mm stem for sphere B, which would change with the robot's orientation; at 16 and 30 mm the sag is 0.02 to 0.05 mm. Length from the adapter face to the sphere surface at least 2R plus 50 mm (130 mm for A, 205 mm for B; drawings SC1-03 and SC1-04). At the adapter end turn a threaded spigot (M12 x 15 mm, M20 x 25 mm) behind a shoulder at least 1.5 times the stem diameter across; the shoulder face, machined square to the stem axis in the same setup as the thread, seats on the adapter and sets the stem perpendicular. Tighten to a moderate, recorded torque; a jam nut is optional. Make a witness mark across stem and adapter so a loosened joint is visible. Finish the stem matte black (bluing or matte paint).
3. Sphere end, ceramic spheres (preferred). Precision ceramic spheres are sold with a threaded insert (typically M6 or M8) bonded in by the maker. Turn the stem tip to a matching threaded spigot with a small shoulder that seats on the flat around the insert; add a drop of medium-strength thread locker and tighten by hand plus a quarter turn. Do not clamp the sphere in a vise; hold the stem.
4. Sphere end, steel spheres. Bearing-grade balls (52100 "chrome steel" or 440C stainless) are through-hardened to about 60 HRC, so they cannot be tapped with ordinary tooling, and no supplier found stocks a tapped precision ball above 1.5 inch (appendix A). Do not ask a shop to tap one. Instead have a blind hole made along any radius to about 0.6 R deep (10 mm H7 x 23 mm for sphere A, drawing SC1-03) by carbide drilling or electrical discharge machining, sized for a light press fit on the stem tip (H7/p6), and bond the stem in with an anaerobic retaining compound (for example a high-strength bearing retainer). Do not weld or braze; the heat distorts the sphere. The hole does not have to be exactly radial, since the routine of 3b measures the center wherever it ends up. A tapped hole is possible only as a custom order from a ball maker, who taps before hardening.
5. Weight. Sphere A in ceramic weighs about 0.9 kg, in steel 1.8 kg. Sphere B in steel weighs 14.5 kg and is not recommended; in alumina ceramic about 7 kg; a precision-turned aluminum sphere with a matte hard-anodized surface weighs about 5 kg and is the practical choice. Have the shop that turns it cut the M20 thread for the stem into the sphere in the same setup, as a blind tapped hole M20 x 30 mm with a 32 mm spot face at the pole (drawing SC1-04); the sphere then arrives tapped by construction and the stem design of item 2 is used unchanged. Specify sphericity 0.02 mm or better (the same as for sphere A, section 1d) and measure the diameter and roundness in-house after hard anodizing, which adds about 0.025 to 0.05 mm to the radius. The diameter must be known to 0.025 mm; aluminum grows 0.0035 mm in diameter per degree C at this size, so measure at the session's room temperature or record the temperature and correct. A hollow sphere (two spun hemispheres welded and finish-turned) is lighter still, but its wall must be thick enough to turn true; 6 mm is a reasonable minimum. Check the robot's payload rating against the sphere, stem and adapter together.
6. Finish. A matte, light, uniform surface on both spheres, the same finish on both. Every bearing-grade ball, steel or ceramic, is delivered lapped to a mirror finish, and a mirror sphere is unusable (it returns one bright highlight from the sensor's projector and little else). Note that "chrome steel" is the trade name of the 52100 alloy, about 1.5 percent chromium; it is not chrome-plated, but it is just as bright as delivered. The preferred treatment is bead-blasting with fine glass bead, which turns the surface a diffuse gray and removes only micrometers, so the certified diameter stays usable within about 0.01 mm; this is how commercial matte reference spheres are made. A thin matte gray paint is the second choice, since each coat adds 0.02 to 0.05 mm. In either case measure the diameter afterwards in-house with the outside micrometer, checked first against its setting standard, at no fewer than six orientations; the spread of the readings is the sphericity check (0.02 mm or better), and their mean, not any certificate, goes in the pose log.
7. Handling. Keep each sphere in a padded case with its stem fitted. Never set a sphere down on its surface on a hard table. Wipe with isopropyl alcohol before a session.
8. Repeatability. After any remount of the adapter or stem, re-run the nest check (3b, step 8) before capturing. The joint is good if the two readings agree within 0.1 mm.

### 3b. Finding the tool center point of each sphere

The calibration needs to know where the center of the sphere is for every robot pose. The robot reports where its tool center point (TCP) is, so the TCP must be set to the center of the sphere. The robot cannot see the sphere, so the TCP is found mechanically, with the three-ball nest.

Why the nest works: a sphere resting on three fixed balls always has its center at the same point in space, whatever direction its stem points. The robot's built-in multi-orientation TCP routine ("4-point method", "TCP by touch-up", or similar name depending on the robot brand) finds the one point on the tool that stays still while the wrist turns. Seating the sphere in the nest from several directions makes that point the sphere's center.

1. Bolt the nest to the table at a height the robot reaches comfortably with the wrist pointing down and tilted about 40 degrees to either side.
2. Mount sphere A's adapter and stem on the flange on its dowel pin. Tighten to the normal torque.
3. Enter a rough TCP first so the robot moves sensibly: the TCP is on the flange axis at a distance from the flange face equal to adapter thickness plus stem length plus the sphere radius. Measure these with calipers and enter the sum as the tool z offset, x and y zero. Also enter the tool's load data: the weighed mass of sphere, stem and adapter together, with its center of gravity on the flange axis near the sphere center.
4. Start the robot's multi-orientation TCP routine. For each of its points (use at least six if the controller allows more than four): jog the robot so that the sphere settles into the nest, touching all three balls, with the stem in a different direction each time: straight up, tilted 40 degrees forward, backward, left, right, and one twisted about the stem. Settle the sphere by lowering it slowly the last millimeter; do not press down hard, the stem will bend. Confirm the point.
5. The routine reports a TCP and usually an error figure. Accept it only if the error is 0.1 mm or less. If it is larger, repeat; the usual causes are the sphere not fully seated, or a loose adapter.
6. Save the TCP under a clear name, for example `TCP_SPHERE_A_76mm`. Write the numbers in the session notes.
7. Repeat steps 2 to 6 for sphere B, saving `TCP_SPHERE_B_152mm`.
8. Check: with the TCP active, seat the sphere in the nest and read the robot's position. Lift out, re-seat with a very different wrist orientation, read again. The two positions must agree within 0.1 mm. If they do not, the TCP is wrong; repeat the routine.

## 4. Setting up the board and its tool frame

The board's "tool frame" is a coordinate frame at the center of the board's front face, with its z axis pointing straight out of the face (toward the sensor when the board faces it), x along the long edge, y along the short edge. The robot must report the board's pose in this frame.

1. Mount the board adapter (drawing SC1-05) on the flange on its dowel pin. Seat the board on the three support pads against the three edge pins and tighten the three clamp fingers.
2. Runout check (figure 1c): fix the dial indicator to the table with its tip on the board's front face about 20 mm from an edge. Slowly rotate the flange about its own axis (robot joint 6) through 360 degrees. The reading must stay within 0.05 mm. If it does not, the board face is not perpendicular to the flange axis: shim the adapter and repeat.
3. Measure the distance from the flange face to the board's front face with a depth gauge or calipers at four places around the board; they should agree within 0.05 mm. Record the average as D.
4. Measure the board's width and height with calipers and record them. The half-sizes go in the manifest (100 and 75 mm for the recommended board).
5. Define the tool frame in the robot: position (0, 0, D) from the flange, orientation: z along the flange axis pointing out of the board, x along the board's long edge. How to set x: with the robot's "tool orientation by points" function, teach a point at the center of the long edge, or enter the rotation about z that aligns x with the long edge, after measuring with a square against the adapter. An error of a few degrees in x is harmless (the board is symmetric); an error in z is not.
6. Save as `TOOL_BOARD`, enter its load data (weighed mass of board and adapter, center of gravity on the flange axis), and write the numbers in the session notes.

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

(Use the measured radii of your spheres in place of 38.1 and 76.2, and your board's half-sizes in place of 100 75.)

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

The robot program is written before the first session (section 1f), once the robot model and controller are settled; it can be written with Claude Code, because both sides of its interface are fixed: `poses.csv` coming in, and the capture trigger and `pose_log.csv` going out. The capture trigger goes through the capture computer's communication software, whose interface the program uses. Before the first session, dry-run every pose at reduced speed without capturing, to confirm reach and clearance from the sensor, its mount and its cables.

Robot program outline, for each row of the file:

1. Move to the pose (joint move to a point 100 mm short of it along the stem axis, then a linear move onto it, so the approach is the same every time).
2. Wait 1.5 seconds for vibration to settle.
3. Trigger the capture of 5 frames through the communication software; file names `<pose_id>_Index00.mc` to `<pose_id>_Index04.mc`.
4. Read the robot's actual reported TCP pose (not the commanded one, the reported one) and append it to the pose log (section 7).
5. Move on.

Do all sphere A poses, change to sphere B (remember to activate `TCP_SPHERE_B_152mm`), do all sphere B poses, change to the board (activate `TOOL_BOARD`), do all board poses. Do not move the sensor between these.

## 7. Recording the poses: the pose log and the manifest

The capture software writes the sensor data. The pose must be recorded separately, in one of two ways. Both are supported; use the first if the capture software can do it.

Option A, pose in the file header. If the capture software can be given the robot's pose at capture time, it writes it into the file's header under the key `robotPose` as a 4 x 4 matrix (16 numbers, row by row: rotation in the top-left 3 x 3, position in the right column, last row 0 0 0 1), tool frame to base frame. Then no separate log is needed beyond the target sizes, and the software reads the poses from the files.

Option B, pose log plus manifest (preferred when option A is not available, and recommended anyway as a backup). The robot program appends one line per pose to a CSV file, the pose log, with the columns below. Note in the session notes where the program writes it (controller storage or a network location), so it can be collected after the session.

Columns:

```
pose_id, kind, radius_mm, half_width_mm, half_height_mm, x_mm, y_mm, z_mm, rotation_type, r1, r2, r3, r4
```

- `pose_id`: exactly the id from `poses.csv`, which is also the start of the file names.
- `kind`: `sphere` or `board`.
- `radius_mm`: the measured radius for a sphere, half the diameter measured after the matte finish (nominally 38.10 for sphere A, 76.20 for sphere B), empty for a board.
- `half_width_mm`, `half_height_mm`: half the measured board size, empty for a sphere.
- `x_mm`, `y_mm`, `z_mm`: the reported TCP position in the base frame.
- `rotation_type` and `r1..r4`: the reported tool orientation, in whatever form the controller gives, named by one of: `quaternion_wxyz`, `quaternion_xyzw`, `euler_zyx_deg` (KUKA A, B, C), `fixed_xyz_deg` (FANUC W, P, R), `euler_xyz_deg`, `rotvec_deg`, `matrix` (nine numbers, the rotation matrix row by row), or `none` for a sphere (its orientation does not matter). When the `matrix` form is used, the r columns run to `r9` (`r1..r9`). Fill unused r columns with nothing.

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

## 9. Checks that do not depend on the robot

No certified ball bar is available, so the session contains no artifact whose geometry is known independently of the robot. Two checks that do not use the robot's positions come from the captures already planned, and the fit's report computes them on the held-out poses; nothing extra has to be captured.

- Sphere shape. Each held-out sphere is fitted with its radius left free. After correction, the fitted radius should agree with the measured radius, and the points should lie closer to the fitted sphere than before. The report gives each fitted radius with its standard error, which is large for a small or distant sphere (the sensor sees only a cap, on which radius and distance trade off); judge each radius error against its own standard error.
- Board flatness. Each held-out board's points are fitted with a plane of their own. After correction, their spread about that plane should fall toward the plate's measured flatness. This check sees only errors that bend the board's image; an error that shifts or tilts the whole board leaves its flatness unchanged, so it is weaker than the sphere check and mainly catches the fixed pattern.

Your part is to make the references good: measure the sphere diameters carefully (section 3a, items 5 and 6) and keep the board's flatness report with the session notes.

What these checks cannot do is what the ball bar did best: test the scale of the volume. A uniform range-scale error changes a sphere's fitted radius only by the scale error times the radius (a 0.1 percent error changes sphere A's radius by 0.04 mm), whereas a bar shows it over its full length. Scale is therefore checked mainly by the held-out sphere centers against the robot, which are limited by the robot's 0.1 mm accuracy. If a coordinate measuring machine becomes available later, two spheres on a rigid bar measured on it restore the full check.

## 10. Deliverables checklist

- [ ] `captures/` with all `.mc` files, named `<pose_id>_Index<nn>.mc`
- [ ] `pose_log.csv` (option B) or confirmation that headers carry `robotPose` (option A)
- [ ] `captures/manifest.csv` produced by `make_manifest` without errors
- [ ] `captures/check.json` with no flags, or a note explaining each remaining flag
- [ ] `plan/poses.csv`, `plan/plan_summary.txt`, `plan/plan.png` as used
- [ ] `boot.json` and the bootstrap captures
- [ ] `session_notes.txt` with: sensor serial, warm-up time, exposure, gain and SGM parameters, where `pose_log.csv` was written, base frame name, TCP values and their routine errors, board D and runout reading, board dimensions, sphere diameter measurements, temperature, fixture changes with times
- [ ] Photos of the setup (a phone camera is fine): sensor mount, each fixture on the flange, the nest, the run-out fixture

## 11. Things that spoil a session

- Moving or bumping the sensor. If it happens, everything after it is a new session.
- Changing exposure, gain, or the base frame mid-session.
- Using the commanded pose instead of the reported pose in the log.
- A loose adapter or a bent stem: check the stem is straight by rolling it on a flat surface before mounting.
- Fingerprints or gloss on the sphere or board: wipe with isopropyl alcohol; a shiny spot returns a bright highlight and a bad read.
- Letting the stem point toward the sensor: the sphere must hide the stem. The plan sets the orientation for this; do not override it.
- Mixing up the two spheres' radii in the pose log.

---

## Appendix A. Suppliers

This list was assembled from the suppliers' web pages in October 2026. It is a starting point, not an endorsement: confirm the diameter, the finish, how the diameter is measured, and the mounting thread with the supplier before ordering, because catalogs change and several of the items below are made to order. The sizes this procedure asks for (3 inch and 6 inch matte spheres with a threaded hole) are not stock items at most metrology suppliers, whose standard reference spheres are either small (up to about 50 mm, for probing machines) or large but magnet-based (145 to 200 mm, for laser scanners).

Pre-tapped spheres. None was found at the specified sizes and precision. Precision tapped balls (Bal-tec, hardened 440C, diameter within 0.0025 mm) stop at 1.0 inch with threads to 1/4-20; matte 440C reference spheres with a female M8 (MetrologyWorks) stop at 1.5 inch; the laser-scanner target spheres below carry an M8 insert in the right sizes but with form errors of 0.3 to 2 mm. Hardened balls cannot be tapped after the fact (section 3a, item 4), so a tapped 3 inch sphere is a custom order from a ball maker, and a tapped 6 inch sphere is a turned aluminum sphere with the thread cut at manufacture (section 3a, item 5). The bonded blind hole of section 3a, item 4 is the cheaper route for steel.

Spheres, made to order in the sizes needed:

- Bal-tec, a division of Micro Surface Engineering, Los Angeles, California (precisionballs.com). Custom precision balls in any material and size, including hollow spheres and satin (non-glossy) finishes in titanium and other metals; threaded mounting holes and stems on request. The most direct route to a 3 inch and a 6 inch matte sphere with a certificate.
- RGP Balls, Italy (rgpballs.com), and Industrial Tectonics, Dexter, Michigan (itiball.com): precision ceramic and steel balls, large diameters on request. Confirm the largest ceramic diameter they will make; 6 inch may exceed it.
- Morgan Advanced Materials: large ceramic balls (alumina, zirconia) for grinding and valves; a 6 inch alumina ball is a stock-like item from such makers, but the sphericity grade and the certificate must be asked for, and a blind hole must be bonded or drilled by a ceramics shop.

Spheres, stock items, useful for a smaller sphere A or the three-ball nest:

- MetrologyWorks (metrologyworks.com): matte-finish 440C stainless reference spheres, 0.5, 1 and 1.5 inch diameter, with a female M8 x 1.25 thread. The finish is the one wanted here; the sizes are below the 3 inch recommended for sphere A, so use them only if a smaller near-range sphere is accepted by the engineer.
- Hexagon Manufacturing Intelligence: ceramic calibration spheres, 15 to 25 mm, M8 thread, with an ISO/IEC 17025 certificate. Suitable for the nest balls; too small for the targets.
- Renishaw: datum spheres in polished tungsten carbide, 12 to 25 mm. The polished finish is unsuitable for the targets (bright highlight, bad reads); fine for the nest.
- Laser-scanner target spheres (Laserscanning Europe and Goecke in Germany, Scan & Go in Italy, Tiger Supplies and Mount Laser in the United States): 100, 145, 150 and 200 mm spheres in coated aluminum, stainless steel, carbon fiber or plastic, matte, on a magnetic base with a female M8 or 1/4 inch insert, about $100 to $150 per sphere in sets of six. Where a form figure is stated it is 0.5 to 2 mm, fifty to two hundred times too coarse for either target. Not usable as specified.
- Rothbucher Systeme (Germany) RSLB10M, sold in the United States by Baseline Equipment Company and others, about $150 to $200: 145 mm plastic sphere with a matte textured lacquer, sphericity 0.3 mm and radius within 0.15 mm at 20 degrees C, 250 g, magnetic base. This is the best-specified laser-scanner sphere found and is light enough for a slender stem, but its form error is still three times the 0.1 mm target at 500 mm. It could serve as a provisional far-range sphere B (700 mm and beyond, where the depth-scaled target is 0.2 to 0.4 mm) during stage 1 if its diameter is first measured in-house with an outside micrometer (a 125 to 150 mm one, since 145 mm is below the range of the 150 to 175 mm micrometer of section 1c) and that value goes in the pose log, and if the far-range hold-out residuals are read with its 0.3 mm form error in mind. It is not adequate as sphere A or as the final sphere B. Remove the magnetic base and bond a stem into the insert (section 3a).

A low-cost alternative for sphere A is a bearing-grade ball (grade 25 or better; 52100 alloy steel, sold as "chrome steel" although it is not plated, or 440C stainless) from Bal-tec or an industrial supplier, about $30 to $60 at 3 inch; a shop puts in the blind hole by carbide drilling or electrical discharge machining and bonds the stem (it cannot be tapped, section 3a item 4), then bead-blasts it matte. Bead-blasting keeps the certified diameter within about 0.01 mm; if paint is used instead, each coat adds 0.02 to 0.05 mm. Either way the diameter is measured afterwards, with a micrometer at several orientations, and that value, not the ball's certificate, goes in the pose log. Weight is the other constraint: a solid 6 inch steel ball weighs about 14.5 kg and is not recommended on a stem; alumina is about half that, and a hollow or aluminum sphere lighter again (section 3a).

Board:

- McMaster-Carr: MIC-6 cast aluminum tooling plate, sold with mill certificates and a stated flatness (about 0.13 mm over the sheet for the thicknesses of interest). That is coarser than the 0.05 mm asked for here, so order the plate oversize and have a local grinding shop finish-grind the front face flat to 0.05 mm, then matte-paint it (bead-blast only a plate 10 mm or thicker; peening one face of a thinner plate bows it). Alternatively, ask the grinding shop for a flatness report directly.
- Any float-glass or optical-flat supplier (Edmund Optics sells ground and polished flats): a 6 to 10 mm float glass plate is flat to better than 0.05 mm over 200 mm as delivered; it must be matte-painted on the front face and bonded or clamped to the board adapter. Glass is the better choice when no grinding shop is at hand.
- A small granite surface plate (Starrett or Mitutoyo, grade A or AA) is flat to a few micrometers but black and heavy; it works if the front is painted matte light gray and the robot carries the weight (a 200 x 150 x 50 mm plate is about 4 kg).

For the three-ball nest, the hardened balls can be ordinary grade-25 bearing balls (McMaster-Carr, Bal-tec); the nest's quality comes from the balls being rigidly fixed, not from their grade.

Measuring instruments (section 1c), all stocked by McMaster-Carr, Transcat, MSI-Viking and the usual tool suppliers:

- Outside micrometers: Mitutoyo 103-140-10 (75 to 100 mm, about $170 to $220) and 103-143-10 (150 to 175 mm, about $235 to $300), each supplied with its setting standard; Starrett makes equivalents.
- Dial indicator: Mitutoyo 2046 series, 0.01 mm graduation, 10 mm travel, about $50 to $150.
- Magnetic base: Noga MG71003 or DG-61003 with fine adjustment, about $140 to $320.
- Straightedge: 300 mm, DIN 874 grade 0 or better, about $60 to $200; feeler gauge set with a 0.05 mm leaf.

Machine shop: the adapter plates, stems, board adapter, nest base and run-out base plate (drawings in appendix D), and the blind hole in a steel sphere (carbide drilling or electrical discharge machining).

## Appendix B. Software reference: where the capture tools are in the repository

The code that supports this procedure lives in the repository `depth_calibration_from_spherical_target`, in the Python package `sphcal/`. The three command-line tools are each a single file, but they import other modules of the package, so they cannot be copied out on their own. The complete set of files the three tools load is the 17 files below (about 3,400 lines, which is too long to reproduce here); this appendix gives their locations, the tools' built-in help, and their default settings.

What to ship to the capture computer. Ship the whole `sphcal/` directory together with `requirements.txt` and the `tests/` directory, either as a clone of the repository or as a copy of those three items with the directory layout kept. The package is about 6,700 lines in all, so trimming it to the 17 files saves little and loses the self-test (the test in `tests/test_cli_tools.py` makes its synthetic captures with `sphcal/simulate/synthetic.py`, which is not otherwise needed). If a trimmed copy is nevertheless wanted, it must contain exactly the files marked "tools" in the table, with their directories and the six `__init__.py` files; Python finds the modules through the directory layout, so the files must stay where they are shown.

| File | Lines | Needed by | What it does |
|---|---|---|---|
| `sphcal/__init__.py` | 6 | tools | Package marker (a docstring only); Python needs it to import anything under `sphcal` |
| `sphcal/cli/__init__.py` | 1 | tools | Package marker for the tools directory |
| `sphcal/cli/plan_poses.py` | 645 | tools | Sections 5 and 6: turns the bootstrap captures into a rough sensor position and writes the pose plan (`poses.csv`, `plan_summary.txt`, `plan.png`) |
| `sphcal/cli/make_manifest.py` | 415 | tools | Section 7: matches the pose log to the capture files, converts every orientation form to a matrix, writes the manifest |
| `sphcal/cli/check_captures.py` | 386 | tools | Section 8: the quick-look check of valid pixels, border contact, sphere and plane fits, and agreement with the commanded poses |
| `sphcal/io/__init__.py` | 1 | tools | Package marker |
| `sphcal/io/poses.py` | 454 | tools | The manifest and pose-log record format, the readers and writers, and the orientation conversions used by the two tools above |
| `sphcal/io/capture_set.py` | 77 | tools | Groups the `.mc` files of a pose into frame stacks for the check tool |
| `sphcal/io/matcloud.py` | 402 | tools | Reads the sensor's `.mc` capture files (header and array) |
| `sphcal/io/qt_datastream.py` | 431 | tools | Decodes the Qt serialization the `.mc` files are written in; used only through `matcloud.py` |
| `sphcal/geometry/__init__.py` | 1 | tools | Package marker |
| `sphcal/geometry/camera.py` | 87 | tools | Pinhole camera model: pixel to ray, point to pixel, from the file header |
| `sphcal/geometry/transforms.py` | 93 | tools | Rigid transforms and the fit of a rigid transform to point pairs (the bootstrap of section 5) |
| `sphcal/features/__init__.py` | 1 | tools | Package marker |
| `sphcal/features/depth_features.py` | 208 | tools | Frame averaging and per-pixel depth statistics; the check tool uses the frame averaging |
| `sphcal/calibration/__init__.py` | 1 | tools | Package marker |
| `sphcal/calibration/extrinsic.py` | 179 | tools | Sphere center fit with outlier trimming and the sensor-to-robot transform solve, used by the check tool for its residuals |
| `tests/test_cli_tools.py` | 355 | self-test | Exercises the three tools end to end on synthetic captures; a worked example of the expected inputs |
| `sphcal/simulate/__init__.py`, `sphcal/simulate/synthetic.py` | 541 | self-test | Makes the synthetic captures the self-test uses |

The fit itself (`sphcal/cli/fit.py`, with the rest of `sphcal/calibration/` and `sphcal/spline/`) is not part of the capture procedure; the engineer runs it on the deliverables of section 10. The design document `docs/design/code_design.md` describes it.

Installing and running the tools is spelled out step by step in appendix C. Every tool prints the help below with `--help`.

Default settings. The plan tool's defaults are: depth range 300 to 1,100 mm; near sphere radius 40 mm, far sphere radius 80 mm, switching at 550 mm with a 50 mm overlap band; grid spacing 1.5 radii; 80 percent field fill; 3 near and 4 far depth planes; board half-size 120 x 90 mm at depths 350, 550, 800 and 1,050 mm, tilts 0, 20 and 40 degrees about two azimuths (0 and 90 degrees), 2 lateral positions at 50 percent field fill; 10 pixel edge margin; 20 percent hold-out; bootstrap residual warning at 5 mm. The commands in section 5 override the radii, the field fill and the board size for the fixtures of section 1. The check tool's defaults are: sphere fit or center residual warning at 2 mm; plane residual warning at 2 mm; minimum valid fraction 0.5; border margin 4 pixels; board normal warning at 2 degrees. The manifest tool writes CSV unless `--format json` is given.

Output of `python3 -m sphcal.cli.plan_poses --help`:

```
usage: plan_poses.py [-h] --sensor-in-base PATH [--camera PATH]
                     [--fov-deg H V] [--image-size W H]
                     [--depth-min-mm DEPTH_MIN_MM]
                     [--depth-max-mm DEPTH_MAX_MM]
                     [--near-radius-mm NEAR_RADIUS_MM]
                     [--far-radius-mm FAR_RADIUS_MM]
                     [--radius-switch-depth-mm RADIUS_SWITCH_DEPTH_MM]
                     [--overlap-band-mm OVERLAP_BAND_MM]
                     [--spacing-in-radii SPACING_IN_RADII]
                     [--fov-fill FOV_FILL]
                     [--depth-planes-near DEPTH_PLANES_NEAR]
                     [--depth-planes-far DEPTH_PLANES_FAR]
                     [--board-half-size-mm HALF_WIDTH HALF_HEIGHT]
                     [--board-depths-mm BOARD_DEPTHS_MM [BOARD_DEPTHS_MM ...]]
                     [--board-tilts-deg BOARD_TILTS_DEG [BOARD_TILTS_DEG ...]]
                     [--board-azimuths-deg BOARD_AZIMUTHS_DEG [BOARD_AZIMUTHS_DEG ...]]
                     [--board-lateral-positions BOARD_LATERAL_POSITIONS]
                     [--board-lateral-fill BOARD_LATERAL_FILL]
                     [--edge-margin-px EDGE_MARGIN_PX]
                     [--holdout-fraction HOLDOUT_FRACTION] [--seed SEED]
                     [--bootstrap-residual-warn-mm BOOTSTRAP_RESIDUAL_WARN_MM]
                     --out DIR

Plan the robot poses of a stage-1 capture: sphere and board poses spread
through the depth sensor's working volume, written as poses.csv,
plan_summary.txt and plan.png.

options:
  -h, --help            show this help message and exit
  --sensor-in-base PATH
                        JSON with {"matrix": [16 floats, row-major 4x4 sensor-
                        to-base]} or {"bootstrap": [{"pose_id", "base_xyz",
                        "sensor_xyz"}, ... at least 3 non-collinear]}
  --camera PATH         .mc capture file whose header gives fx, fy, cx, cy and
                        whose array gives the image size
  --fov-deg H V         full horizontal and vertical field of view in degrees
                        (with --image-size)
  --image-size W H      image width and height in pixels
  --depth-min-mm DEPTH_MIN_MM
  --depth-max-mm DEPTH_MAX_MM
  --near-radius-mm NEAR_RADIUS_MM
  --far-radius-mm FAR_RADIUS_MM
  --radius-switch-depth-mm RADIUS_SWITCH_DEPTH_MM
  --overlap-band-mm OVERLAP_BAND_MM
                        both radii are planned in this band below the switch
                        depth
  --spacing-in-radii SPACING_IN_RADII
                        grid spacing as a multiple of the radius in use
  --fov-fill FOV_FILL   fraction of the half field covered by sphere centers
                        at each depth
  --depth-planes-near DEPTH_PLANES_NEAR
  --depth-planes-far DEPTH_PLANES_FAR
  --board-half-size-mm HALF_WIDTH HALF_HEIGHT
  --board-depths-mm BOARD_DEPTHS_MM [BOARD_DEPTHS_MM ...]
  --board-tilts-deg BOARD_TILTS_DEG [BOARD_TILTS_DEG ...]
  --board-azimuths-deg BOARD_AZIMUTHS_DEG [BOARD_AZIMUTHS_DEG ...]
  --board-lateral-positions BOARD_LATERAL_POSITIONS
                        board positions spread across the field at each depth
  --board-lateral-fill BOARD_LATERAL_FILL
                        fraction of the half field covered by board centers at
                        each depth
  --edge-margin-px EDGE_MARGIN_PX
                        board corners must project this far inside the image
  --holdout-fraction HOLDOUT_FRACTION
  --seed SEED           seed of the random held-out subset
  --bootstrap-residual-warn-mm BOOTSTRAP_RESIDUAL_WARN_MM
  --out DIR             output directory
```

Output of `python3 -m sphcal.cli.make_manifest --help`:

```
usage: make_manifest.py [-h] --pose-log PATH --captures DIR
                        [--format {csv,json}] --out PATH [--strict]

Build the capture manifest from a pose log (CSV) and a directory of .mc
capture files. The poses.csv written by plan_poses is accepted as a pose log.

options:
  -h, --help           show this help message and exit
  --pose-log PATH      CSV with pose_id, kind, radius_mm, half_width_mm,
                       half_height_mm, x_mm, y_mm, z_mm, rotation_type, r1..r4
                       (rotation_type: none, quaternion_wxyz, quaternion_xyzw,
                       euler_zyx_deg, euler_xyz_deg, fixed_xyz_deg,
                       rotvec_deg, matrix)
  --captures DIR       directory of .mc files named <pose_id>_Index<frame>.mc
  --format {csv,json}  manifest format
  --out PATH           manifest file to write
  --strict             treat warnings (missing or unmatched captures, non-unit
                       quaternions) as errors
```

Output of `python3 -m sphcal.cli.check_captures --help`:

```
usage: check_captures.py [-h] --manifest PATH
                         [--sphere-residual-warn-mm SPHERE_RESIDUAL_WARN_MM]
                         [--plane-residual-warn-mm PLANE_RESIDUAL_WARN_MM]
                         [--min-valid-fraction MIN_VALID_FRACTION]
                         [--border-margin-px BORDER_MARGIN_PX]
                         [--board-normal-warn-deg BOARD_NORMAL_WARN_DEG]
                         [--out PATH]

Quick-look check of a capture set before the long fit: valid pixels, border
contact, sphere and plane fit residuals, and agreement with the commanded
poses.

options:
  -h, --help            show this help message and exit
  --manifest PATH       manifest CSV or JSON
  --sphere-residual-warn-mm SPHERE_RESIDUAL_WARN_MM
                        flag a sphere whose surface fit RMS or center residual
                        exceeds this
  --plane-residual-warn-mm PLANE_RESIDUAL_WARN_MM
                        flag a board whose RMS distance to its fitted plane
                        exceeds this
  --min-valid-fraction MIN_VALID_FRACTION
                        flag a pose valid in a smaller fraction of its frames
  --border-margin-px BORDER_MARGIN_PX
                        valid pixels within this many pixels of the border
                        mean the target is cut off
  --board-normal-warn-deg BOARD_NORMAL_WARN_DEG
                        flag a board whose fitted and commanded normals differ
                        by more than this
  --out PATH            write a JSON report here
```

## Appendix C. Installing and running the software, step by step

These steps were checked on Linux with Python 3.11 in a fresh environment; the Windows commands follow the same pattern and differ only where noted. Allow about 20 minutes, most of it download time. Nothing here needs administrator rights.

C.1 Install Python. Python 3.10 or newer is required.

- Windows: download the installer for the latest Python 3 from python.org/downloads and run it. On the first screen tick "Add python.exe to PATH" before clicking Install. When it finishes, open a new Command Prompt (Start menu, type `cmd`) and type `python --version`; it must print `Python 3.10` or higher. If it prints nothing or an error, the PATH box was not ticked: run the installer again and choose Modify.
- Linux (Debian or Ubuntu): in a terminal, `sudo apt install python3 python3-venv python3-pip`, then `python3 --version`.

On Windows the Python command is `python`; on Linux it is `python3`. The commands below are written with `python3`; on Windows type `python` instead. Everything else is identical.

C.2 Get the code. Either unzip the archive the engineer sent, or, if `git` is installed, clone the repository. Put it somewhere without spaces in the path, for example `C:\cal\depth_calibration` on Windows or `~/cal/depth_calibration` on Linux. Inside that folder you must see `pyproject.toml`, `requirements.txt`, the folder `sphcal` and the folder `tests`. That folder is called the repository folder below.

C.3 Open a terminal in the repository folder. Windows: in File Explorer, open the repository folder, click in the address bar, type `cmd` and press Enter; a Command Prompt opens already in that folder. Linux: `cd ~/cal/depth_calibration`. Check with `dir` (Windows) or `ls` (Linux) that `pyproject.toml` is listed; if it is not, you are in the wrong folder and every later step will fail with "No module named sphcal".

C.4 Make a private Python environment and install into it. This keeps the tools' packages separate from anything else on the computer. In the terminal from C.3:

```
python3 -m venv .venv
```

then activate it, which you must do again in every new terminal before using the tools:

```
.venv\Scripts\activate          (Windows)
source .venv/bin/activate       (Linux)
```

The prompt now starts with `(.venv)`. Then install the package and everything it needs (numpy, scipy, matplotlib, pytest; about 150 MB, downloaded from the internet):

```
python3 -m pip install -e ".[figures,test]"
```

The `-e` installs the code in place, so the tools can be run from any folder once the environment is active, and a corrected file from the engineer takes effect by simply replacing it. If the computer has no internet, the engineer can supply the packages as files; ask.

C.5 Run the self-test. Still in the repository folder:

```
python3 -m pytest -q tests/test_cli_tools.py
```

After about ten seconds it must end with a line like `21 passed in 2.3s`. Any line containing `FAILED` or `ERROR` means the installation is not right; copy the whole output into a text file and send it to the engineer. Do not start capturing until this passes.

C.6 Run the tools. Every tool is run as `python3 -m sphcal.cli.<tool>` followed by its options, as in sections 5, 7 and 8. With the environment active (C.4) this works from any folder, so it is simplest to keep a working folder for the session, for example `C:\cal\session_2026_10_14`, put `boot.json`, `pose_log.csv` and the `captures` folder in it, open the terminal there (C.3) and give file names relative to it. Each tool prints what it wrote. Three things to know:

- A message starting with `ERROR:` means the tool stopped and wrote nothing; it says what is wrong in the input and which pose or file it concerns. Fix that and run it again.
- A message starting with `WARNING:` means the tool finished but something should be looked at; the plan tool, for example, still writes `poses.csv` without matplotlib and only skips the picture.
- `python3 -m sphcal.cli.<tool> --help` prints the option list (appendix B).

C.7 If something goes wrong.

- "No module named sphcal": the environment is not active (the prompt does not start with `(.venv)`), or step C.4 was done in a different folder. Activate it and retry; if that fails, redo C.3 and C.4.
- "python3 is not recognized" on Windows: type `python` instead; if that also fails, redo C.1.
- "pip install" fails with a network or certificate error: the computer's internet access is blocked; ask the engineer for the package files or for the proxy settings.
- A traceback (many lines ending in an exception name) from any tool is a software fault, not an input fault: save the whole output and the input files and send them to the engineer.

## Appendix D. Shop drawings

The six drawings below are the ones to build from. Each shows a plan view and an elevation in section, with every feature dimensioned and toleranced, the material, the finish and the quantity. The flange interface on SC1-01, SC1-02 and SC1-05 follows ISO 9409-1-50-4-M6 (ISO 9409-1:1996, table 1: 50 mm pitch circle, 31.5 mm H7 centering recess, four M6, one 6 mm H7 pin hole on the pitch circle at +Xm); confirm it against the chosen robot's flange drawing before machining. The rigid sensor mount is built from the existing drawing from previous work and is not repeated here. The run-out fixture needs no drawing (section 1e).

The drawings are generated by scripts in `docs/procedures/drawings/` (regenerate all six with `python3 docs/procedures/drawings/make_all.py`); the PNG files there print at full size and are the copies to send to the shop.

| Drawing | Part | Quantity | File |
|---|---|---|---|
| SC1-01 | Adapter plate, sphere A | 1 | `SC1-01_adapter_plate_sphere_A.png` |
| SC1-02 | Adapter plate, sphere B | 1 | `SC1-02_adapter_plate_sphere_B.png` |
| SC1-03 | Stem, sphere A, with the hole detail for a steel sphere A | 1 | `SC1-03_stem_sphere_A.png` |
| SC1-04 | Stem, sphere B, with the interface detail for sphere B | 1 | `SC1-04_stem_sphere_B.png` |
| SC1-05 | Board adapter, with the board outline | 1 | `SC1-05_board_adapter.png` |
| SC1-06 | Three-ball nest base | 1 | `SC1-06_three_ball_nest_base.png` |

Points for the machine shop to confirm: the DIN 76 thread undercuts and lead chamfers on SC1-03 and SC1-04; on SC1-02, the 47 mm spot face overlaps the screw counterbores, so the four flange screws are fitted before the stem; on SC1-05, the pin and pad positions carry the general tolerance ISO 2768-mK, which is enough because the board's position within its own plane does not affect the calibration.

![SC1-01](drawings/SC1-01_adapter_plate_sphere_A.png)

Drawing SC1-01. Adapter plate, sphere A.

![SC1-02](drawings/SC1-02_adapter_plate_sphere_B.png)

Drawing SC1-02. Adapter plate, sphere B.

![SC1-03](drawings/SC1-03_stem_sphere_A.png)

Drawing SC1-03. Stem, sphere A.

![SC1-04](drawings/SC1-04_stem_sphere_B.png)

Drawing SC1-04. Stem, sphere B.

![SC1-05](drawings/SC1-05_board_adapter.png)

Drawing SC1-05. Board adapter.

![SC1-06](drawings/SC1-06_three_ball_nest_base.png)

Drawing SC1-06. Three-ball nest base.
