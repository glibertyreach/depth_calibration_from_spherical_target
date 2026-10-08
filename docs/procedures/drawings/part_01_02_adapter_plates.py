"""Shop drawings SC1-01 and SC1-02: flange adapter plates for spheres A and B.

Both parts are the same design with different thickness, central thread, spot
face, counterbore depth and dowel pin length, so one function draws both from an
:class:`AdapterSpec`.  All dimensions are named constants; nothing is hard-coded
inside the drawing code.

Coordinate systems
------------------
Plan view (model mm): origin at the part axis, +u to the right, +v up.  The plan is
looked at from the STEM side and is rotated so that +Xm of the robot flange points
UP on the sheet.  The dowel hole is therefore at (0, +PCD/2).

Elevation (model mm): u = z, the distance from the stem-side face (datum A) toward
the flange, v = radial distance (positive up).  The section is an ALIGNED section:
the cutting plane runs vertically through the dowel hole and the axis, then bends
along the 135 degree bolt hole radius, and that bolt hole is rotated into the
section so the dowel (top) and a counterbored bolt hole (bottom) both appear.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import drafting as d
from drafting import RED, Sheet, TitleInfo, View, polar, thread_minor_diameter

# ---------------------------------------------------------------------------
# Dimensions common to both plates (mm)
# ---------------------------------------------------------------------------
DISK_D = 63.0  # disk outer diameter (matches flange d2 = 63)
PCD = 50.0  # bolt and dowel pitch circle diameter (flange d1)
SPIGOT_D = 31.5  # centering spigot diameter (fits flange d3 = 31.5 H7)
SPIGOT_H = 5.0  # spigot height on the flange side
SPIGOT_CHAMFER = 0.5  # spigot end chamfer, 0.5 x 45 degrees
DOWEL_D = 6.0  # dowel hole and pin diameter
PIN_PROTRUSION = 5.0  # dowel pin protrusion beyond the flange-side face
BOLT_HOLE_D = 6.6  # M6 clearance holes
CBORE_D = 11.0  # counterbore diameter for DIN 7984 heads
POSITION_TOL = 0.1  # Ø position tolerance of the 4 bolt holes
BOLT_ANGLES = (45.0, 135.0, 225.0, 315.0)  # bolt hole angles from +Xm
CSK = 1.0  # countersink size on the thread, 1 x 45 degrees, both ends
SPOT_DEPTH = 1.0  # spot face depth (chosen, see report)
EDGE_BREAK = 0.3  # edges broken 0.3 x 45 degrees
THREAD_TOL_CLASS = "6H"  # internal thread tolerance class (chosen, ISO default)

# Tolerance annotations
TOL_SPIGOT = "g6"  # spigot diameter tolerance
TOL_DOWEL_HOLE = "H7"  # dowel hole tolerance
TOL_DOWEL_PIN = "m6"  # dowel pin tolerance
TOL_PERP_THREAD = "Ø0.02/100"  # thread axis perpendicular to datum A, per 100 mm
TOL_FLAT_A = "0.01"  # flatness of datum A
TOL_PARALLEL = "0.01"  # flange-side face parallel to A
TOL_COAX = "Ø0.02"  # spigot coaxial with the thread axis
DATUM_FACE = "A"  # stem-side face
DATUM_AXIS = "B"  # thread axis

# ---------------------------------------------------------------------------
# Sheet layout (paper mm)
# ---------------------------------------------------------------------------
SCALE = 2.0  # both views at 2:1
SCALE_TEXT = "2:1"  # scale as printed
PLAN_CENTER = (100.0, 165.0)  # paper position of the part axis in the plan
ELEV_ORIGIN = (290.0, 165.0)  # paper position of (z = 0, v = 0) in the elevation
VIEW_LABEL_DY = -22.0  # view label baseline relative to the plan's lowest point
NOTES_X = 12.0  # left edge of the notes block
NOTES_TOP = 76.0  # top of the notes block
NOTES_WIDTH = 108.0  # width of one notes column
NOTES_COLUMN_GAP = 6.0  # gap between the two notes columns
FLANGE_NOTE_X = 172.0  # boxed flange note position (below the plan callouts)
FLANGE_NOTE_TOP = 114.0
FLANGE_NOTE_W = 68.0
CALL_X = 168.0  # x of the plan leader texts (paper)
SLOT_DOWEL = 228.0  # y of the dowel callout text (paper)
SLOT_BOLT = 206.0  # y of the bolt hole callout text
SLOT_THREAD = 182.0  # y of the thread callout text
SLOT_SPOT = 156.0  # y of the spot face callout text
SLOT_SPIGOT = 134.0  # y of the spigot callout text
CALLOUT_FRAME_DY = 6.0  # frame center below its callout text box
CUT_END_R = 37.5  # cutting-plane line half length in model mm
CUT_BEND_R = 36.0  # length of the bent leg of the cutting plane, model mm
CENTER_LINE_R = 35.0  # plan centerline half length, model mm
XM_KEY_POS = (22.0, 212.0)  # paper position of the +Xm key arrow tail
XM_KEY_LEN = 22.0  # +Xm arrow length, paper mm
ANGLE_ARC_R = 35.0  # radius of the 45 degree angle dimension arc, model mm
ANGLE_DIM_FROM = 90.0  # plan angle of the +Xm axis (it points up), degrees
ANGLE_DIM_TO = 135.0  # plan angle of the neighboring bolt radius, degrees
ANGLE_TEXT_DX = -9.0  # angle dimension text offset (paper)
ANGLE_TEXT_DY = 1.0
PLAN_ROTATION_DEG = 90.0  # plan angle of +Xm: angles from +Xm are measured from here
CUT_LEG_ANGLE_DEG = 45.0  # the bent leg of the cutting plane runs at this angle below the horizontal
THREAD_ARC_END_DEG = 270.0  # the thin major-diameter arc of an end-on thread spans 3/4 of a turn
ARC_TOLERANCE = 1e-9  # tolerance of the circle-inside-circle test
DIA_LEADER = (200.0, -12.0, -6.0)  # angle, dx, dy of the disk diameter leader
PCD_LEADER = (160.0, -16.0, 0.0)  # angle, dx, dy of the pitch circle leader
DOWEL_LEADER_ANGLE = 20.0  # angle on the dowel hole where its leader lands
BOLT_LEADER_ANGLE = 35.0  # angle on the first counterbore for its leader
THREAD_LEADER_ANGLE = 25.0  # angle on the thread minor circle for its leader
SPOT_LEADER_ANGLE_SMALL = 345.0  # spot face leader angle when the spot face is small
SPOT_LEADER_ANGLE_LARGE = 300.0  # spot face leader angle when the spot face is large
SPOT_SMALL_RADIUS = 30.0  # spot faces smaller than this radius use the small-spot angle
SPIGOT_LEADER_ANGLE = 330.0  # angle on the hidden spigot circle for its leader
LEFT_DIM_OFFSET = -12.0  # spot face diameter dimension offset (paper mm)
FLATNESS_FRAME_DX = -40.0  # flatness frame left edge relative to the stem face
PARALLEL_EXT_LEN = 12.0  # extension line below the part for the parallelism frame
PARALLEL_FRAME_DX = 9.0  # parallelism frame offset right of its extension line
ROW_1 = 8.0  # first dimension row distance from the part (paper mm)
ROW_2 = 17.0  # second dimension row distance
BOTTOM_ROW_SPIGOT = -7.0  # spigot height dimension offset
BOTTOM_ROW_CBORE = -9.0  # counterbore depth dimension offset
RIGHT_ROW_1 = 9.0  # first vertical dimension column right of the part
RIGHT_ROW_2 = 19.0  # second vertical dimension column
RIGHT_ROW_3 = 29.0  # third vertical dimension column
SPIGOT_DIM_TEXT_POS = 0.25  # fraction along the spigot diameter dimension for its text
DATUM_B_END_R = 35.0  # datum B symbol sits on the end of the horizontal centerline


@dataclass(frozen=True)
class AdapterSpec:
    """Dimensions that differ between SC1-01 and SC1-02."""

    number: str  # drawing number
    name: str  # part name
    file_name: str  # PNG file name
    body_t: float  # disk body thickness
    thread_d: float  # central thread nominal diameter
    thread_pitch: float  # coarse pitch of that thread
    spot_d: float  # spot face diameter
    cbore_depth: float  # counterbore depth from the stem side
    pin_len: float  # dowel pin length
    stem_name: str  # which stem seats on the spot face
    stem_shoulder_d: float  # shoulder diameter of that stem
    extra_notes: tuple[str, ...]  # notes that only apply to this part

    @property
    def length(self) -> float:
        """Overall length including the spigot (= full thread length)."""
        return self.body_t + SPIGOT_H

    @property
    def minor_d(self) -> float:
        return thread_minor_diameter(self.thread_d, self.thread_pitch)


SPEC_01 = AdapterSpec(
    number="SC1-01", name="Adapter plate, sphere A",
    file_name="SC1-01_adapter_plate_sphere_A.png",
    body_t=16.0, thread_d=12.0, thread_pitch=1.75, spot_d=26.0, cbore_depth=6.5, pin_len=16.0,
    stem_name="SC1-03", stem_shoulder_d=24.0, extra_notes=(),
)
SPEC_02 = AdapterSpec(
    number="SC1-02", name="Adapter plate, sphere B",
    file_name="SC1-02_adapter_plate_sphere_B.png",
    body_t=22.0, thread_d=20.0, thread_pitch=2.5, spot_d=47.0, cbore_depth=12.5, pin_len=22.0,
    stem_name="SC1-04", stem_shoulder_d=45.0,
    extra_notes=(
        "The Ø47 spot face overlaps the Ø11 counterbores and the Ø45 stem shoulder covers "
        "part of the screw heads: fit the four screws to the robot flange before fitting "
        "stem SC1-04.",
    ),
)

MATERIAL = "Steel C45 (AISI 1045) or aluminum 6061-T6"
FINISH = "Black oxide (steel) or black anodize (aluminum), matte"


def _fmt(x: float) -> str:
    """Format a dimension without trailing zeros (16.0 -> '16', 6.5 -> '6.5')."""
    return f"{x:g}"


def _arc_visible(angle: float, center: tuple[float, float], radius: float,
                 holes: list[tuple[tuple[float, float], float]]) -> bool:
    """True if the circle point at ``angle`` is not inside any of ``holes``."""
    p = polar(center, radius, angle)
    return all(math.hypot(p[0] - hc[0], p[1] - hc[1]) >= hr - ARC_TOLERANCE for hc, hr in holes)


def build_adapter(spec: AdapterSpec, out_dir: str) -> list[str]:
    """Draw one adapter plate sheet and save it.  Returns QA issues found."""
    sh = Sheet(spec.number)
    sh.border()

    # ---- derived geometry ------------------------------------------------
    R = DISK_D / 2  # disk radius
    pr = PCD / 2  # pitch circle radius
    rs = SPIGOT_D / 2  # spigot radius
    rd0, rd1 = pr - DOWEL_D / 2, pr + DOWEL_D / 2  # dowel hole radial extent
    rb0, rb1 = pr - BOLT_HOLE_D / 2, pr + BOLT_HOLE_D / 2  # bolt hole radial extent
    cb0, cb1 = pr - CBORE_D / 2, pr + CBORE_D / 2  # counterbore radial extent
    r_maj = spec.thread_d / 2
    r_min = spec.minor_d / 2
    csk_r = r_maj + CSK  # countersink radius at the face
    csk_ax = csk_r - r_min  # axial length of the 45 degree cone down to the minor radius
    r_sf = spec.spot_d / 2
    L = spec.length
    T = spec.body_t
    pin_end = T + PIN_PROTRUSION
    pin_start = pin_end - spec.pin_len
    bolt_pts = [polar((0, 0), pr, PLAN_ROTATION_DEG - a) for a in BOLT_ANGLES]  # plan positions (+Xm up)
    dowel_pt = (0.0, pr)

    # =====================================================================
    # PLAN VIEW (from the stem side)
    # =====================================================================
    plan = View(sh, PLAN_CENTER, SCALE)
    plan.circle((0, 0), R, "outline")  # disk outline
    # Spot face circle, trimmed where it runs through the counterbores / dowel hole.
    holes = [(p, CBORE_D / 2) for p in bolt_pts] + [(dowel_pt, DOWEL_D / 2)]
    n_seg = int(d.FULL_CIRCLE_DEG / d.ARC_STEP_DEG)
    run: list[float] = []
    for i in range(n_seg + 1):
        a = i * d.ARC_STEP_DEG
        if _arc_visible(a, (0, 0), r_sf, holes):
            run.append(a)
        elif run:
            plan.circle((0, 0), r_sf, "outline", run[0], run[-1])
            run = []
    if run:
        plan.circle((0, 0), r_sf, "outline", run[0], run[-1])
    # Thread: countersink edge, major diameter (3/4 arc, thin), minor diameter (thick)
    plan.circle((0, 0), csk_r, "outline")
    plan.circle((0, 0), r_maj, "thin", 0, THREAD_ARC_END_DEG)
    plan.circle((0, 0), r_min, "outline")
    # Bolt holes: through hole and counterbore
    for p in bolt_pts:
        plan.circle(p, BOLT_HOLE_D / 2, "outline")
        plan.circle(p, CBORE_D / 2, "outline")
        plan.center_cross(p, CBORE_D / 2)
    # Dowel hole (pin seen end-on, same circle)
    plan.circle(dowel_pt, DOWEL_D / 2, "outline")
    # Hidden spigot on the far (flange) side
    plan.circle((0, 0), rs, "hidden")
    # Centerlines: axes, pitch circle, radial lines through the bolt holes
    plan.center_v(-CENTER_LINE_R, CENTER_LINE_R, 0.0)
    plan.center_h(-CENTER_LINE_R, CENTER_LINE_R, 0.0)
    plan.circle((0, 0), pr, "center")
    for p in bolt_pts:
        upper_left = p[0] < 0 < p[1]  # this radial line carries the angle dimension
        r_end = ANGLE_ARC_R if upper_left else CENTER_LINE_R
        k = r_end / pr
        plan.line((0, 0), (p[0] * k, p[1] * k), "center")

    # Cutting plane A-A: top leg vertical, then bent along the 225 degree hole radius
    leg = math.radians(CUT_LEG_ANGLE_DEG)
    bend = (-CUT_BEND_R * math.cos(leg), -CUT_BEND_R * math.sin(leg))
    plan.cutting_plane([(0.0, CUT_END_R), (0.0, 0.0), bend], sight=(-1.0, 0.0), label="A",
                       sight_end=(-math.cos(leg), math.sin(leg)))  # the arrow turns with the rotated leg

    # +Xm key (red): arrow pointing up on the sheet
    kx, ky = XM_KEY_POS
    sh.line([(kx, ky), (kx, ky + XM_KEY_LEN)], "outline", RED)
    sh.arrow((kx, ky + XM_KEY_LEN), (0, 1), RED)
    sh.text(kx + 2.0, ky + XM_KEY_LEN - 2.0, "+Xm", size=d.FONT_LABEL, color=RED, weight="bold")

    # Angle dimension: 45 degrees between the +Xm axis and the neighboring bolt hole radius
    plan.dim_angle((0, 0), ANGLE_DIM_FROM, ANGLE_DIM_TO, ANGLE_ARC_R * SCALE, f"{BOLT_ANGLES[0]:g}°",
                   text_dx=ANGLE_TEXT_DX, text_dy=ANGLE_TEXT_DY)

    # Datum B (thread axis) on the left end of the horizontal centerline
    sh.datum_feature(plan.P(-DATUM_B_END_R, 0.0), (-1.0, 0.0), DATUM_AXIS)

    # ---- plan callouts ----------------------------------------------------
    plan.leader_circle((0, 0), R, DIA_LEADER[0], f"Ø{_fmt(DISK_D)}", *DIA_LEADER[1:])
    plan.leader_circle((0, 0), pr, PCD_LEADER[0], f"Ø{_fmt(PCD)} PCD", *PCD_LEADER[1:])

    def callout(center, radius, angle, text, slot_y):
        """Leader from a circle to a text block whose middle sits at (CALL_X, slot_y)."""
        t = plan.P(*polar(center, radius, angle))
        return plan.leader((polar(center, radius, angle)), text,
                           CALL_X - t[0] - d.LEADER_SHOULDER - d.LEADER_TEXT_GAP, slot_y - t[1])

    callout(dowel_pt, DOWEL_D / 2, DOWEL_LEADER_ANGLE,
            f"Ø{_fmt(DOWEL_D)} {TOL_DOWEL_HOLE} THRU, AT +Xm (0°)\n"
            f"DOWEL PIN Ø{_fmt(DOWEL_D)} {TOL_DOWEL_PIN} × {_fmt(spec.pin_len)},\n"
            f"PRESSED IN, {_fmt(PIN_PROTRUSION)} PROUD ON FLANGE SIDE", SLOT_DOWEL)
    box = callout(bolt_pts[0], CBORE_D / 2, BOLT_LEADER_ANGLE,
                  f"4 × Ø{_fmt(BOLT_HOLE_D)} THRU AT 45°, 135°,\n225°, 315° FROM +Xm\n"
                  f"CBORE Ø{_fmt(CBORE_D)} × {_fmt(spec.cbore_depth)} DEEP FROM STEM SIDE", SLOT_BOLT)
    sh.fcf(box[0], box[1] - CALLOUT_FRAME_DY, "position", f"Ø{_fmt(POSITION_TOL)}", (DATUM_AXIS,))
    box = callout((0, 0), r_min, THREAD_LEADER_ANGLE,
                  f"M{_fmt(spec.thread_d)} {THREAD_TOL_CLASS} THRU, LENGTH {_fmt(L)}\n"
                  f"CSK {_fmt(CSK)} × 45° BOTH ENDS", SLOT_THREAD)
    sh.fcf(box[0], box[1] - CALLOUT_FRAME_DY, "perp", TOL_PERP_THREAD, (DATUM_FACE,))
    spot_angle = SPOT_LEADER_ANGLE_SMALL if r_sf < SPOT_SMALL_RADIUS else SPOT_LEADER_ANGLE_LARGE
    callout((0, 0), r_sf, spot_angle,
            f"SPOT FACE Ø{_fmt(spec.spot_d)} × {SPOT_DEPTH:.1f} DEEP\n"
            f"(SEAT FOR {spec.stem_name} SHOULDER Ø{_fmt(spec.stem_shoulder_d)})", SLOT_SPOT)
    box = callout((0, 0), rs, SPIGOT_LEADER_ANGLE,
                  f"SPIGOT Ø{_fmt(SPIGOT_D)} {TOL_SPIGOT} × {_fmt(SPIGOT_H)} HIGH (HIDDEN)\n"
                  f"CHAMFER {_fmt(SPIGOT_CHAMFER)} × 45°", SLOT_SPIGOT)
    sh.fcf(box[0], box[1] - CALLOUT_FRAME_DY, "coax", TOL_COAX, (DATUM_AXIS,))

    # =====================================================================
    # ELEVATION: SECTION A-A
    # =====================================================================
    el = View(sh, ELEV_ORIGIN, SCALE)

    def inner_poly(sign: float, hole_in: float, hole_cbore: float | None) -> list[tuple[float, float]]:
        """Material polygon between the thread bore and the first hole (one side).

        ``hole_in`` is the inner radius of the hole; ``hole_cbore`` is the inner
        radius of its counterbore (None for the plain dowel hole).
        """
        s = sign
        pts: list[tuple[float, float]] = [(SPOT_DEPTH, s * csk_r)]
        wall_r = hole_in if hole_cbore is None else hole_cbore
        pts.append((SPOT_DEPTH, s * min(r_sf, wall_r)))
        if r_sf < wall_r:  # spot face wall is separate from the hole
            pts.append((0.0, s * r_sf))
            pts.append((0.0, s * wall_r))
        if hole_cbore is None:
            pts.append((T, s * wall_r))
        else:
            pts.append((spec.cbore_depth, s * wall_r))
            pts.append((spec.cbore_depth, s * hole_in))
            pts.append((T, s * hole_in))
        pts += [(T, s * rs), (L - SPIGOT_CHAMFER, s * rs), (L, s * (rs - SPIGOT_CHAMFER)),
                (L, s * csk_r), (L - csk_ax, s * r_min), (SPOT_DEPTH + csk_ax, s * r_min)]
        return pts

    top_inner = inner_poly(+1.0, rd0, None)
    top_outer = [(0.0, rd1), (0.0, R), (T, R), (T, rd1)]
    bot_inner = inner_poly(-1.0, rb0, cb0)
    bot_outer = [(0.0, -cb1), (0.0, -R), (T, -R), (T, -rb1), (spec.cbore_depth, -rb1),
                 (spec.cbore_depth, -cb1)]
    pin_poly = [(pin_start, rd0), (pin_end, rd0), (pin_end, rd1), (pin_start, rd1)]
    for poly in (top_inner, top_outer, bot_inner, bot_outer):
        el.section_region(poly)
    el.section_region(pin_poly, other=True)  # pin is a separate part: opposite hatch

    # Thread major diameter (thin) inside the cut, between the countersinks
    for s in (1.0, -1.0):
        el.line((SPOT_DEPTH + CSK, s * r_maj), (L - CSK, s * r_maj), "thin")

    # Centerlines
    cext = d.CENTER_EXT / SCALE
    el.center_h(-cext, L + cext, 0.0)
    el.center_h(-cext, L + cext, pr)
    el.center_h(-cext, L + cext, -pr)

    # ---- elevation dimensions ---------------------------------------------
    # Above the part: body thickness and pin protrusion (chained), overall length
    el.dim_h(0, T, R, R, ROW_1, _fmt(T))
    el.dim_h(T, L, rd1, rd1, ROW_1, _fmt(PIN_PROTRUSION), outside="right", base_v=R)
    el.dim_h(0, L, R, rd1, ROW_2, _fmt(L), base_v=R)
    # Below the part: spigot height and counterbore depth
    el.dim_h(T, L, -rs, -rs, BOTTOM_ROW_SPIGOT, _fmt(SPIGOT_H), outside="right")
    el.dim_h(0, spec.cbore_depth, -R, -cb1, BOTTOM_ROW_CBORE, _fmt(spec.cbore_depth), outside="left")
    # Left: spot face diameter
    el.dim_v(0, 0, -r_sf, r_sf, LEFT_DIM_OFFSET, f"Ø{_fmt(spec.spot_d)}")
    # Right: spigot diameter, pitch circle, disk diameter (all measured from z = L)
    el.dim_v(L, L, -rs, rs, RIGHT_ROW_1, f"Ø{_fmt(SPIGOT_D)} {TOL_SPIGOT}",
             text_pos=SPIGOT_DIM_TEXT_POS, base_u=L)
    el.dim_v(L, L, -pr, pr, RIGHT_ROW_2, f"{_fmt(PCD)} (PCD)", base_u=L)
    el.dim_v(T, T, -R, R, RIGHT_ROW_3, f"Ø{_fmt(DISK_D)}", base_u=L)

    # ---- datum A and geometric tolerance frames ------------------------------
    if r_sf < min(rd0, cb0):  # inner land between spot face and holes exists
        face_top = (r_sf + rd0) / 2.0
        face_bot = (r_sf + cb0) / 2.0
    else:  # spot face reaches the holes: only the outer ring is left as stem face
        face_top = (rd1 + R) / 2.0
        face_bot = (cb1 + R) / 2.0
    sh.datum_feature(el.P(0.0, face_top), (-1.0, 0.0), DATUM_FACE)
    fl = sh.fcf(el.P(0, 0)[0] + FLATNESS_FRAME_DX, el.P(0, -face_bot)[1], "flat", TOL_FLAT_A)
    sh.frame_leader(fl["right"], el.P(0.0, -face_bot))
    # parallelism of the flange-side face to A: frame on an extension line below the part
    x_face = el.P(T, 0)[0]
    y_face_bottom = el.P(0, -R)[1]
    y_frame = y_face_bottom - PARALLEL_EXT_LEN
    sh.line([(x_face, y_face_bottom - d.EXT_GAP), (x_face, y_frame - d.EXT_OVERSHOOT)], "thin")
    par = sh.fcf(x_face + PARALLEL_FRAME_DX, y_frame, "para", TOL_PARALLEL, (DATUM_FACE,))
    sh.frame_leader(par["left"], (x_face, y_frame))

    # =====================================================================
    # Labels, notes, title block
    # =====================================================================
    label_y = PLAN_CENTER[1] - R * SCALE + VIEW_LABEL_DY
    sh.text(PLAN_CENTER[0], label_y, f"PLAN VIEW, FROM STEM SIDE   SCALE {SCALE_TEXT}",
            size=d.FONT_LABEL, ha="center", weight="bold")
    sh.text(ELEV_ORIGIN[0] + SCALE * L / 2, label_y, f"SECTION A-A   SCALE {SCALE_TEXT}",
            size=d.FONT_LABEL, ha="center", weight="bold")

    notes = [
        f"Machine both faces, spigot and M{_fmt(spec.thread_d)} thread in one setup.",
        f"Datum A = stem-side face. Datum B = M{_fmt(spec.thread_d)} thread axis. "
        f"Thread axis perpendicular to A within Ø0.02 per 100 mm (0.02/100). "
        f"Flatness of A {TOL_FLAT_A}; flange-side face parallel to A {TOL_PARALLEL}; "
        f"spigot Ø{_fmt(SPIGOT_D)} coaxial with datum B within {TOL_COAX}.",
        f"Edges broken {_fmt(EDGE_BREAK)} × 45° unless stated.",
        f"Dowel pin Ø{_fmt(DOWEL_D)} {TOL_DOWEL_PIN} × {_fmt(spec.pin_len)} is pressed into the "
        f"Ø{_fmt(DOWEL_D)} {TOL_DOWEL_HOLE} hole and protrudes {_fmt(PIN_PROTRUSION)} on the flange side.",
        f"Position tolerance Ø{_fmt(POSITION_TOL)} of the four Ø{_fmt(BOLT_HOLE_D)} holes applies to the "
        f"pattern relative to datum B and the dowel hole; Ø{_fmt(PCD)} and 45° are basic dimensions.",
        "Fasteners: 4 × M6 × 16 DIN 7984 low-head socket cap screws (not part of this drawing).",
        f"Thread M{_fmt(spec.thread_d)} is ISO metric coarse (pitch {_fmt(spec.thread_pitch)}), "
        f"class {THREAD_TOL_CLASS}. The spot face bottom is the seat for stem {spec.stem_name}.",
        "Section A-A is an aligned section: the counterbored hole at 135° is rotated into the "
        "cutting plane.",
        "Dimensions apply after finishing: mask the thread, the dowel hole and the spigot when "
        "coating, or allow for coating thickness.",
    ] + list(spec.extra_notes)
    sh.notes_columns(NOTES_X, NOTES_TOP, NOTES_WIDTH, NOTES_COLUMN_GAP, notes, 2)
    sh.boxed_note(FLANGE_NOTE_X, FLANGE_NOTE_TOP, FLANGE_NOTE_W, d.TEXT_FLANGE_NOTE)

    sh.title_block(TitleInfo(spec.number, spec.name, "1", MATERIAL, FINISH, SCALE_TEXT))
    return sh.save(os.path.join(out_dir, spec.file_name))


def build_all(out_dir: str, include_archived: bool = False) -> dict[str, list[str]]:
    """Draw SC1-02, and SC1-01 as well when ``include_archived`` is true.

    SC1-01 (sphere A) was archived when the calibration moved to one sphere (decision
    D-15); its specification is kept so that the archived sheet can be regenerated.
    """
    specs = (SPEC_01, SPEC_02) if include_archived else (SPEC_02,)
    return {s.number: build_adapter(s, out_dir) for s in specs}


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for k, v in build_all(here).items():
        print(k, "issues:", len(v))
        for i in v:
            print("   ", i)
