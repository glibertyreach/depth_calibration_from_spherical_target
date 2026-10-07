"""Shop drawings SC1-03 and SC1-04: stems that carry spheres A and B.

Sheet layout: an END VIEW from the adapter end at the left (third angle: the left
view sits left of the front view) and a full-length SIDE VIEW at its right, both
at 1:1 and sharing the same axis height.  The side view carries a partial
(half) section at each end: the lower half is cut and hatched between the free end
and a break line.  Detail views at 2:1 show the sphere-end tips and the mating
hole in the sphere.

Axial coordinate u (mm) in the side view is measured from the shoulder face that
seats on the adapter (datum B): the threaded spigot is at negative u, the shoulder
runs from u = 0 to u = SHOULDER_LEN and the body ends at u = SHOULDER_LEN + BODY_LEN.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import drafting as d
from drafting import RED, Sheet, TitleInfo, View, polar, thread_minor_diameter

# ---------------------------------------------------------------------------
# Tolerance annotations and datum letters
# ---------------------------------------------------------------------------
TOL_BODY = "h6"  # ground body diameter
TOL_TIP_STEEL = "p6"  # press-fit tip, variant S
TOL_HOLE_STEEL = "H7"  # mating hole in a steel sphere
TOL_PERP_SHOULDER = "0.01"  # shoulder face perpendicular to the stem axis
TOL_STRAIGHT = "0.02"  # straightness of the body over its length
TOL_SPOT_B = "0.02"  # spot face on sphere B square to the hole axis
THREAD_TOL_EXTERNAL = "6g"  # external thread tolerance class (chosen, ISO default)
THREAD_TOL_INTERNAL = "6H"  # internal thread tolerance class (chosen, ISO default)
DATUM_AXIS = "A"  # stem axis (the ground body axis)
DATUM_SHOULDER = "B"  # shoulder face that seats on the adapter
DATUM_HOLE = "C"  # axis of the tapped hole in sphere B

# ---------------------------------------------------------------------------
# Sheet layout (paper mm), common to both stems
# ---------------------------------------------------------------------------
SCALE = 1.0  # end view and side view at 1:1
SCALE_TEXT = "1:1"
DETAIL_SCALE = 2.0  # detail views at 2:1
DETAIL_SCALE_TEXT = "2:1"
AXIS_Y = 200.0  # paper y of the stem axis
ROW_1, ROW_2, ROW_3 = 6.0, 13.0, 20.0  # dimension rows above the part (paper mm)
LEFT_DIM_1 = -8.0  # first vertical dimension column left of the spigot
LEFT_DIM_2 = -20.0  # second vertical dimension column
RIGHT_DIM = 9.0  # vertical dimension column right of the body end
SECTION_LEN = 20.0  # partial section length (model mm) beyond the shoulder / before the tip
VIEW_LABEL_Y = 252.0  # baseline of the two main view labels
DETAIL_ROW_Y = 120.0  # paper y of the axis of the two tip details (SC1-03)
DETAIL_S_X = 70.0  # paper x of the body end face in detail S
DETAIL_C_X = 190.0  # paper x of the body end face in detail C
DETAIL_BODY_SHOWN = 14.0  # length of body shown in the tip details (model mm)
DETAIL_LABEL_DY = -32.0  # detail label baseline relative to the detail axis
NOTES_WIDTH = 108.0  # width of one notes column
NOTES_COLUMN_GAP = 6.0  # gap between the notes columns
NOTES_SIZE = 9.0  # notes text size (the minimum allowed)
PHANTOM_TIP_LEN_S = 22.0  # tip length shown phantom in the side view of SC1-03 (variant S)
SHOULDER_EXT_LEN = 12.0  # shoulder-face extension line length below the part (paper)
SHOULDER_FRAME_DX = 8.0  # frame offset right of the shoulder extension line
STRAIGHT_FRAME_DY = -16.0  # straightness frame below the body (paper)
STRAIGHT_FRAME_U = 0.30  # fraction along the body where the straightness frame attaches
DATUM_A_U = 0.78  # fraction along the body where datum A is attached
TIP_LABEL_OFFSET = (6.0, -22.0)  # offset of the phantom-tip label (paper)
SPHERE_LEADER_OFFSET = (8.0, 10.0)  # offset of the sphere name leader above the detail arc
UNDERCUT_ARC_STEP_DEG = 10.0  # angular step of the undercut radius polyline
QUARTER_CIRCLE_DEG = 90.0  # quarter turn
THREAD_ARC_END_DEG = 270.0  # the thin minor-diameter arc of an end-on thread spans 3/4 of a turn
SPIGOT_CALLOUT_FRACTION = 0.6  # where along the spigot the thread callout lands
TIP_LABEL_FRACTION = 0.6  # where along the phantom tip its label lands
BODY_LEADER_FRACTION = 0.55  # where along the shown body the body diameter leader lands
SPHERE_A_LEADER_FRACTION = 0.45  # fraction of the shown half width for the sphere A name leader
SCALE_LABEL_DY = 5.0  # distance between a view label and its scale line (paper)
DETAIL_CENTER_EXT = 3.0  # detail centerlines extend this far past the cut (model mm)
HOLE_LEADER_HEIGHT = 6.0  # height above the hole bottom where the diameter leader lands (model mm)
HOLE_LEADER_DX = -6.0  # horizontal offset of the hole diameter leader elbow (paper)
HOLE_LABEL_ABOVE_POLE = 8.0  # the hole diameter text sits this far above the pole (paper)
FRAME_ARROW_GAP = 0.3  # gap between a frame leader arrow and the flat it points at (paper)


@dataclass(frozen=True)
class StemSpec:
    """Dimensions of one stem."""

    number: str
    name: str
    file_name: str
    thread_d: float  # spigot thread nominal diameter
    thread_pitch: float  # coarse pitch
    spigot_len: float  # spigot length from the shoulder face
    undercut_d: float  # DIN 76 undercut diameter
    undercut_w: float  # DIN 76 undercut width
    undercut_r: float  # DIN 76 undercut radius at the shoulder
    spigot_chamfer: float  # lead chamfer at the free end, 45 degrees
    shoulder_d: float
    shoulder_len: float
    body_d: float
    body_len: float  # from the shoulder's far face to the body end
    material: str
    stock_note: str  # note about the bar stock for the shoulder
    x_origin: float  # paper x of u = 0
    x_end_view: float  # paper x of the end view center
    hole_pole: tuple[float, float]  # paper position of the sphere pole in the sphere detail
    notes_pos: tuple[float, float]  # paper position (x, top y) of the notes block
    end_view_body_leader: tuple[float, float, float]  # angle, dx, dy of the hidden body leader
    end_view_dia_leader: tuple[float, float, float]  # angle, dx, dy of the shoulder diameter leader
    end_view_thread_leader: tuple[float, float, float]  # angle, dx, dy of the thread leader
    spigot_callout: tuple[float, float, bool]  # dx, dy of the spigot callout, include undercut lines
    notes_width: float  # width of one notes column
    hidden_text: str  # text of the hidden body leader

    @property
    def minor_d(self) -> float:
        return thread_minor_diameter(self.thread_d, self.thread_pitch)

    @property
    def body_end(self) -> float:
        """u of the body end face: shoulder face to body end."""
        return self.shoulder_len + self.body_len


# Tip variants for SC1-03 (steel sphere S, ceramic sphere C)
TIP_S_D = 10.0  # variant S tip diameter (p6)
TIP_S_LEN = 22.0  # variant S tip length
TIP_S_CHAMFER = 0.5  # lead chamfer 0.5 x 45
TIP_C_D = 8.0  # variant C tip thread M8
TIP_C_PITCH = 1.25  # coarse pitch of M8
TIP_C_LEN = 12.0  # variant C tip length
TIP_C_CHAMFER = 0.5  # lead chamfer (chosen to match variant S)
# Mating hole in steel sphere A
SPHERE_A_D = 76.2  # steel sphere A diameter
HOLE_A_D = 10.0  # blind hole diameter (H7)
HOLE_A_DEPTH = 23.0  # blind hole depth
SPHERE_A_SHOWN_HALF = 26.0  # half width of the sphere region shown in the detail
SPHERE_A_SHOWN_DEPTH = 31.0  # depth below the pole shown in the detail
# Sphere B interface (SC1-04)
SPHERE_B_D = 152.4  # turned aluminum sphere B diameter
TIP_B_THREAD_DEPTH = 30.0  # tapped hole thread depth
TIP_B_DRILL_EXTRA = 5.0  # drill deeper than the thread (chosen)
SPOT_B_D = 32.0  # spot face diameter at the pole
SPOT_B_DEPTH = 2.0  # spot face depth below the pole (chosen so that the Ø32 flat is complete)
SPHERE_B_SHOWN_HALF = 26.0  # half width of the sphere region shown in the detail
SPHERE_B_SHOWN_DEPTH = 48.0  # depth below the pole shown in the detail
# Alternate tip for a bonded sphere B
ALT_TIP_B_D = 16.0
ALT_TIP_B_LEN = 45.0
ALT_HOLE_B_DEPTH = 46.0
# Tip of SC1-04 (turned aluminum sphere B)
TIP_04_LEN = 25.0  # M20 tip length
TIP_04_CHAMFER = 1.5  # lead chamfer of the M20 tip (chosen)

SPEC_03 = StemSpec(
    number="SC1-03", name="Stem, sphere A", file_name="SC1-03_stem_sphere_A.png",
    thread_d=12.0, thread_pitch=1.75, spigot_len=15.0, undercut_d=9.4, undercut_w=5.25,
    undercut_r=0.9, spigot_chamfer=1.0, shoulder_d=24.0, shoulder_len=8.0, body_d=16.0,
    body_len=122.0,
    material="Ø25 bar, 1.2210 or 4140 pre-hard.; body ground Ø16 h6",
    stock_note="turn the Ø24 shoulder from Ø25 bar",
    x_origin=135.0, x_end_view=62.0, hole_pole=(325.0, 150.0), notes_pos=(12.0, 77.0),
    end_view_body_leader=(225.0, -10.0, -8.0), end_view_dia_leader=(135.0, -10.0, 8.0),
    end_view_thread_leader=(40.0, 10.0, 14.0), spigot_callout=(-6.0, -34.0, True),
    notes_width=108.0, hidden_text="Ø16 h6 (HIDDEN)",
)
SPEC_04 = StemSpec(
    number="SC1-04", name="Stem, sphere B", file_name="SC1-04_stem_sphere_B.png",
    thread_d=20.0, thread_pitch=2.5, spigot_len=25.0, undercut_d=16.4, undercut_w=7.5,
    undercut_r=1.2, spigot_chamfer=1.5, shoulder_d=45.0, shoulder_len=10.0, body_d=30.0,
    body_len=195.0,
    material="Ø46 bar, 1.2210 or 4140 pre-hard.; body ground Ø30 h6",
    stock_note="turn the Ø45 shoulder from Ø46 bar",
    x_origin=130.0, x_end_view=48.0, hole_pole=(140.0, 125.0), notes_pos=(225.0, 158.0),
    end_view_body_leader=(225.0, -6.0, -6.0), end_view_dia_leader=(135.0, -6.0, 6.0),
    end_view_thread_leader=(-40.0, 10.0, -8.0), spigot_callout=(-6.0, -32.0, True),
    notes_width=88.0, hidden_text="Ø30 h6",
)
FINISH = "Black oxide, matte"


def _fmt(x: float) -> str:
    """Format a dimension without trailing zeros."""
    return f"{x:g}"


def _profile(spec: StemSpec, tip_d: float, tip_len: float, tip_chamfer: float) -> list[tuple[float, float]]:
    """Upper outline (u, r) from the free end of the spigot to the end of the tip.

    Includes the DIN 76 undercut, shoulder, body and (if ``tip_len`` > 0) the tip.
    """
    r_maj = spec.thread_d / 2
    c = spec.spigot_chamfer
    r_dg = spec.undercut_d / 2
    rr = spec.undercut_r
    pts: list[tuple[float, float]] = [
        (-spec.spigot_len, r_maj - c), (-spec.spigot_len + c, r_maj),
        (-spec.undercut_w, r_maj), (-spec.undercut_w, r_dg),
    ]
    # radius of the undercut where it meets the shoulder face (quarter circle)
    for a in range(0, int(QUARTER_CIRCLE_DEG) + 1, int(UNDERCUT_ARC_STEP_DEG)):  # quarter circle, center at (-rr, r_dg + rr)
        pts.append((-rr + rr * math.sin(math.radians(a)), r_dg + rr - rr * math.cos(math.radians(a))))
    pts += [(0.0, spec.shoulder_d / 2), (spec.shoulder_len, spec.shoulder_d / 2),
            (spec.shoulder_len, spec.body_d / 2), (spec.body_end, spec.body_d / 2)]
    if tip_len > 0:
        pts += [(spec.body_end, tip_d / 2), (spec.body_end + tip_len - tip_chamfer, tip_d / 2),
                (spec.body_end + tip_len, tip_d / 2 - tip_chamfer)]
    return pts


def _tip_end_u(spec: StemSpec, tip_len: float) -> float:
    return spec.body_end + tip_len


def _draw_stem_side(sh: Sheet, spec: StemSpec, el: View, tip_len: float, tip_d: float,
                    tip_chamfer: float, tip_is_thread: bool, tip_phantom: bool) -> None:
    """Draw the full-length side view with partial sections at both ends."""
    upper = _profile(spec, tip_d, 0.0 if tip_phantom else tip_len, tip_chamfer)
    lower = [(u, -r) for u, r in upper]
    end_u = upper[-1][0] if not tip_phantom else spec.body_end
    # Outline: upper, lower, and the vertical end faces
    el.polyline(upper, "outline")
    el.polyline(lower, "outline")
    el.line(upper[0], lower[0], "outline")
    el.line(upper[-1], lower[-1], "outline")
    # Partial sections (lower half): left end and right end
    left_break = SECTION_LEN + spec.shoulder_len
    left = [(u, r) for u, r in lower if u <= left_break]
    left += [(left_break, -spec.body_d / 2) if left[-1][0] < left_break else left[-1]]
    poly_left = left + [(left_break, 0.0), (-spec.spigot_len, 0.0)]
    el.hatch(poly_left)
    el.polyline([(left_break, 0.0), (left_break, -spec.body_d / 2)], "thin")
    sh.wavy(el.P(left_break, 0.0), el.P(left_break, -spec.body_d / 2))
    right_break = spec.body_end - SECTION_LEN
    if tip_len > 0 and not tip_phantom:
        right = [(right_break, -spec.body_d / 2)] + [(u, r) for u, r in lower if u >= spec.body_end]
        poly_right = right + [(end_u, 0.0), (right_break, 0.0)]
    else:  # SC1-03: the tip is drawn in the details, so the section ends at the body end face
        poly_right = [(right_break, -spec.body_d / 2), (spec.body_end, -spec.body_d / 2),
                      (spec.body_end, 0.0), (right_break, 0.0)]
        end_u = spec.body_end
    el.hatch(poly_right)
    sh.wavy(el.P(right_break, 0.0), el.P(right_break, -spec.body_d / 2))
    # Thread minor-diameter thin lines on the upper (external) half
    r_min = spec.minor_d / 2
    el.line((-spec.spigot_len + spec.spigot_chamfer, r_min), (-spec.undercut_w, r_min), "thin")
    if tip_is_thread and tip_len > 0 and not tip_phantom:
        el.line((spec.body_end, spec.minor_d / 2), (end_u - tip_chamfer, spec.minor_d / 2), "thin")
    # Axis
    ext = d.CENTER_EXT / SCALE
    el.center_h(-spec.spigot_len - ext, end_u + ext, 0.0)
    if tip_phantom:  # variant S tip as a phantom outline
        el.polyline([(spec.body_end, TIP_S_D / 2), (spec.body_end + TIP_S_LEN, TIP_S_D / 2),
                     (spec.body_end + TIP_S_LEN, -TIP_S_D / 2), (spec.body_end, -TIP_S_D / 2)], "phantom")


def build_stem(spec: StemSpec, out_dir: str, is_a: bool) -> list[str]:
    """Draw one stem sheet.  ``is_a`` selects SC1-03 (tip variants, steel sphere
    hole detail) or SC1-04 (M20 tip and the aluminum sphere interface)."""
    sh = Sheet(spec.number)
    sh.border()
    ox = spec.x_origin
    el = View(sh, (ox, AXIS_Y), SCALE)
    ev = View(sh, (spec.x_end_view, AXIS_Y), SCALE)
    r_maj = spec.thread_d / 2
    r_min = spec.minor_d / 2
    r_sh = spec.shoulder_d / 2
    r_body = spec.body_d / 2
    Ls = spec.spigot_len
    Hs = spec.shoulder_len
    Lb = spec.body_end
    tip_len = 0.0 if is_a else TIP_04_LEN
    tip_d = 0.0 if is_a else spec.thread_d
    tip_chamfer = TIP_04_CHAMFER

    # ---- side view -------------------------------------------------------
    _draw_stem_side(sh, spec, el, tip_len, tip_d, tip_chamfer, tip_is_thread=True, tip_phantom=is_a)
    end_u = Lb + (PHANTOM_TIP_LEN_S if is_a else tip_len)

    # ---- end view (from adapter end) -------------------------------------
    ev.circle((0, 0), r_sh, "outline")  # shoulder
    ev.circle((0, 0), r_body, "hidden")  # body behind the shoulder
    ev.circle((0, 0), r_maj, "outline")  # thread major diameter
    ev.circle((0, 0), r_min, "thin", 0, THREAD_ARC_END_DEG)  # thread minor diameter, 3/4 arc
    ec = d.CENTER_EXT / SCALE
    ev.center_h(-r_sh - ec, r_sh + ec, 0.0)
    ev.center_v(-r_sh - ec, r_sh + ec, 0.0)
    ang, ldx, ldy = spec.end_view_dia_leader
    ev.leader_circle((0, 0), r_sh, ang, f"Ø{_fmt(spec.shoulder_d)}", ldx, ldy)
    ang, ldx, ldy = spec.end_view_body_leader
    ev.leader_circle((0, 0), r_body, ang, spec.hidden_text, ldx, ldy)
    ang, ldx, ldy = spec.end_view_thread_leader
    ev.leader_circle((0, 0), r_maj, ang, f"M{_fmt(spec.thread_d)} {THREAD_TOL_EXTERNAL}", ldx, ldy)

    # ---- dimensions above the part -------------------------------------------
    el.dim_h(-Ls, 0, r_maj, r_sh, ROW_1, _fmt(Ls), base_v=r_sh)
    el.dim_h(0, Hs, r_sh, r_sh, ROW_1, _fmt(Hs), outside="right", base_v=r_sh)
    el.dim_h(Hs, Lb, r_sh, r_body, ROW_1, _fmt(spec.body_len), base_v=r_sh)
    el.dim_h(0, Lb, r_sh, r_body, ROW_2, _fmt(Lb), base_v=r_sh)
    if is_a:
        el.dim_h(-Ls, Lb, r_maj, r_body, ROW_3, f"({_fmt(Ls + Lb)} WITHOUT TIP)", base_v=r_sh)
    else:
        el.dim_h(-Ls, end_u, r_maj, tip_d / 2 - tip_chamfer, ROW_3, f"({_fmt(Ls + end_u)} OVERALL)", base_v=r_sh)
        el.dim_h(Lb, end_u, r_body, tip_d / 2, ROW_1, _fmt(TIP_04_LEN), base_v=r_sh)
    # ---- vertical dimensions ------------------------------------------------
    el.dim_v(-Ls, -Ls, -r_maj, r_maj, LEFT_DIM_1, f"Ø{_fmt(spec.thread_d)}")
    el.dim_v(0, 0, -r_sh, r_sh, LEFT_DIM_2, f"Ø{_fmt(spec.shoulder_d)}", base_u=-Ls)
    el.dim_v(Lb, Lb, -r_body, r_body, RIGHT_DIM, f"Ø{_fmt(spec.body_d)} {TOL_BODY}", base_u=end_u)

    # ---- callouts: spigot thread, undercut ---------------------------------------
    cdx, cdy, with_undercut = spec.spigot_callout
    call_text = (f"M{_fmt(spec.thread_d)} × {_fmt(Ls)} LONG, {THREAD_TOL_EXTERNAL}\n"
                 f"LEAD CHAMFER {_fmt(spec.spigot_chamfer)} × 45°")
    if with_undercut:
        call_text += f"\nUNDERCUT Ø{_fmt(spec.undercut_d)} × {_fmt(spec.undercut_w)}, R{_fmt(spec.undercut_r)}"
    el.leader((-Ls * SPIGOT_CALLOUT_FRACTION, -r_maj), call_text, cdx, cdy)

    # ---- tolerance frames and datums -------------------------------------------
    x_face, y_face_bottom = el.P(0, -r_sh)
    y_frame = y_face_bottom - SHOULDER_EXT_LEN
    sh.line([(x_face, y_face_bottom - d.EXT_GAP), (x_face, y_frame - d.EXT_OVERSHOOT)], "thin")
    sh.datum_feature((x_face, y_frame - d.EXT_OVERSHOOT), (0.0, -1.0), DATUM_SHOULDER)
    perp = sh.fcf(x_face + SHOULDER_FRAME_DX, y_frame, "perp", TOL_PERP_SHOULDER, (DATUM_AXIS,))
    sh.frame_leader(perp["left"], (x_face, y_frame))
    # straightness of the body over its length
    u_s = Hs + STRAIGHT_FRAME_U * spec.body_len
    st_pt = el.P(u_s, -r_body)
    st = sh.fcf(st_pt[0], st_pt[1] + STRAIGHT_FRAME_DY, "straight", TOL_STRAIGHT)
    sh.frame_leader(st["top"], st_pt)
    # datum A on the ground body
    u_a = Hs + DATUM_A_U * spec.body_len
    sh.datum_feature(el.P(u_a, -r_body), (0.0, -1.0), DATUM_AXIS)

    # ---- phantom tip label (SC1-03) ------------------------------------------------
    if is_a:
        el.leader((Lb + TIP_S_LEN * TIP_LABEL_FRACTION, -TIP_S_D / 2), "TIP: DETAIL S OR DETAIL C", *TIP_LABEL_OFFSET)

    # =====================================================================
    # DETAIL VIEWS
    # =====================================================================
    if is_a:
        _detail_tip_s(sh, DETAIL_S_X, DETAIL_ROW_Y, spec)
        _detail_tip_c(sh, DETAIL_C_X, DETAIL_ROW_Y, spec)
        _detail_sphere_a(sh, spec.hole_pole)
    else:
        _detail_sphere_b(sh, spec.hole_pole)

    # ---- labels, notes, title block ---------------------------------------------------
    sh.text(spec.x_end_view, VIEW_LABEL_Y, "END VIEW FROM ADAPTER END", size=d.FONT_LABEL,
            ha="center", weight="bold")
    sh.text(spec.x_end_view, VIEW_LABEL_Y - SCALE_LABEL_DY, f"SCALE {SCALE_TEXT}", size=d.FONT_LABEL,
            ha="center", weight="bold")
    sh.text(ox + (Lb - Ls) / 2, VIEW_LABEL_Y,
            f"SIDE VIEW WITH PARTIAL SECTIONS AT BOTH ENDS   SCALE {SCALE_TEXT}", size=d.FONT_LABEL,
            ha="center", weight="bold")

    notes = _notes(spec, is_a)
    width = spec.notes_width
    nx, ny = spec.notes_pos
    sh.notes_columns(nx, ny, width, NOTES_COLUMN_GAP, notes, 2, size=NOTES_SIZE)
    sh.title_block(TitleInfo(spec.number, spec.name, "1", spec.material, FINISH, SCALE_TEXT))
    return sh.save(os.path.join(out_dir, spec.file_name))


def _notes(spec: StemSpec, is_a: bool) -> list[str]:
    """Numbered notes for the stem sheet."""
    notes = [
        f"Machine the shoulder face (datum B), the M{_fmt(spec.thread_d)} spigot thread and the DIN 76-1 "
        f"undercut in one setup.",
        f"Datum A = axis of the ground body Ø{_fmt(spec.body_d)} {TOL_BODY}. Shoulder face perpendicular to A "
        f"within {TOL_PERP_SHOULDER}. Body straight within {TOL_STRAIGHT} over its full length.",
        f"Thread M{_fmt(spec.thread_d)} is ISO metric coarse (pitch {_fmt(spec.thread_pitch)}), class "
        f"{THREAD_TOL_EXTERNAL}. Undercut Ø{_fmt(spec.undercut_d)} × {_fmt(spec.undercut_w)} wide, "
        f"R{_fmt(spec.undercut_r)} (DIN 76-1 form A).",
        f"Shoulder face to body end = {_fmt(spec.body_end)}. This equals the distance from the adapter face "
        f"to the sphere surface.",
        f"The ground bar is smaller than the shoulder: {spec.stock_note}, then grind the body to "
        f"Ø{_fmt(spec.body_d)} {TOL_BODY} after turning and any heat treatment.",
        "Mark a witness line across stem and adapter after tightening.",
    ]
    if is_a:
        notes += [
            "Make the variant that matches sphere A: variant S for the steel sphere, variant C for the "
            "ceramic sphere with maker's insert.",
            f"Mating hole in steel sphere A (Ø{_fmt(SPHERE_A_D)}): blind hole Ø{_fmt(HOLE_A_D)} {TOL_HOLE_STEEL} × "
            f"{_fmt(HOLE_A_DEPTH)} deep along any radius, by carbide drilling or EDM. Bond the stem with "
            f"anaerobic retaining compound. No welding or brazing.",
        ]
    else:
        notes += [
            "Tip M20 × 25 screws into the tapped hole in sphere B (detail H). "
            "Do not bond or weld the tip.",
            f"Sphere B interface: the Ø{_fmt(SPOT_B_D)} spot face must be square to the tapped hole axis within "
            f"{TOL_SPOT_B}; cut it in the same setup as the sphere is turned.",
            f"Alternate tip for a bonded steel or ceramic sphere B: tip Ø{_fmt(ALT_TIP_B_D)} {TOL_TIP_STEEL} × "
            f"{_fmt(ALT_TIP_B_LEN)}, mating hole Ø{_fmt(ALT_TIP_B_D)} {TOL_HOLE_STEEL} × {_fmt(ALT_HOLE_B_DEPTH)} deep.",
        ]
    return notes


# ---------------------------------------------------------------------------
# Detail views
# ---------------------------------------------------------------------------
DETAIL_TIP_DIM_OFFSET = 9.0  # tip length dimension offset above the body (paper)
DETAIL_DIA_DIM_OFFSET = 8.0  # tip diameter dimension offset right of the tip (paper)
BODY_LEADER = (-6.0, 10.0)  # offset of the body diameter leader
CHAMFER_LEADER = (6.0, -14.0)  # offset of the chamfer leader
FACE_LEADER = (-4.0, -9.0)  # offset of the body end face leader


def _detail_tip(sh: Sheet, x: float, y: float, spec: StemSpec, tip_d: float, tip_len: float,
                chamfer: float, thread_pitch: float | None, dia_text: str, title: str) -> None:
    """Tip detail at 2:1: body end region and the tip, both halves cut."""
    v = View(sh, (x, y), DETAIL_SCALE)
    rb = spec.body_d / 2
    rt = tip_d / 2
    s = DETAIL_BODY_SHOWN
    outline = [(-s, rb), (0.0, rb), (0.0, rt), (tip_len - chamfer, rt), (tip_len, rt - chamfer),
               (tip_len, -(rt - chamfer)), (tip_len - chamfer, -rt), (0.0, -rt), (0.0, -rb), (-s, -rb)]
    v.hatch(outline)
    v.polyline(outline, "outline")
    sh.wavy(v.P(-s, rb), v.P(-s, -rb))
    if thread_pitch is not None:
        r_min = thread_minor_diameter(tip_d, thread_pitch) / 2
        for sgn in (1.0, -1.0):
            v.line((0.0, sgn * r_min), (tip_len - chamfer, sgn * r_min), "thin")
    v.center_h(-s - 2.0, tip_len + 1.0, 0.0)
    sh.text(x + DETAIL_LABEL_X_SHIFT, y + DETAIL_LABEL_DY, title, size=d.FONT_LABEL, ha="center",
            weight="bold")
    sh.text(x + DETAIL_LABEL_X_SHIFT, y + DETAIL_LABEL_DY - SCALE_LABEL_DY, f"SCALE {DETAIL_SCALE_TEXT}",
            size=d.FONT_LABEL, ha="center", weight="bold")
    v.dim_h(0, tip_len, rb, rt, DETAIL_TIP_DIM_OFFSET, _fmt(tip_len), base_v=rb)
    v.dim_v(tip_len, tip_len, -rt, rt, DETAIL_DIA_DIM_OFFSET, dia_text, base_u=tip_len)
    v.leader((-s * BODY_LEADER_FRACTION, rb), f"Ø{_fmt(spec.body_d)} {TOL_BODY}", *BODY_LEADER)
    v.leader((tip_len - chamfer / 2, -(rt - chamfer / 2)), f"{_fmt(chamfer)} × 45°", *CHAMFER_LEADER)
    v.leader((0.0, -(rb + rt) / 2), "SEATING FACE", *FACE_LEADER)


DETAIL_LABEL_X_SHIFT = 22.0  # shift of the detail label right of the detail's body end face


def _detail_tip_s(sh: Sheet, x: float, y: float, spec: StemSpec) -> None:
    """Detail S: tip for the steel sphere (press fit and bond)."""
    _detail_tip(sh, x, y, spec, TIP_S_D, TIP_S_LEN, TIP_S_CHAMFER, None, f"Ø{_fmt(TIP_S_D)} {TOL_TIP_STEEL}",
                "DETAIL S: VARIANT S (STEEL)")


def _detail_tip_c(sh: Sheet, x: float, y: float, spec: StemSpec) -> None:
    """Detail C: M8 tip for the ceramic sphere with the maker's insert."""
    _detail_tip(sh, x, y, spec, TIP_C_D, TIP_C_LEN, TIP_C_CHAMFER, TIP_C_PITCH, f"M{_fmt(TIP_C_D)}",
                "DETAIL C: VARIANT C (CERAMIC)")


def _sphere_section(v: View, radius: float, half: float, depth: float,
                    notch: list[tuple[float, float]]) -> None:
    """Hatch and outline a sphere region near the pole.

    ``notch`` lists the profile points (u, v) of the pole feature (hole / spot face)
    from left to right, in model coordinates; the sphere arc is sampled on either side.
    """
    n = SPHERE_ARC_STEPS

    def arc_pts(u0: float, u1: float) -> list[tuple[float, float]]:
        return [(u0 + (u1 - u0) * i / n, math.sqrt(radius ** 2 - (u0 + (u1 - u0) * i / n) ** 2))
                for i in range(n + 1)]

    top = arc_pts(-half, notch[0][0]) + notch + arc_pts(notch[-1][0], half)
    bottom_v = radius - depth
    v.hatch(top + [(half, bottom_v), (-half, bottom_v)])
    v.polyline(top, "outline")
    v.sheet.wavy(v.P(-half, bottom_v), v.P(half, bottom_v))
    v.sheet.wavy(v.P(-half, bottom_v), v.P(-half, top[0][1]))
    v.sheet.wavy(v.P(half, bottom_v), v.P(half, top[-1][1]))


SPHERE_ARC_STEPS = 30  # samples per sphere arc segment
THREAD_TARGET_DEPTH = 5.0  # callout arrow lands this deep below the spot face flat (model mm)
THREAD_CALLOUT_OFFSET = (-4.0, 30.0)  # offset of the tapped hole callout (paper)
SPOT_CALLOUT_OFFSET = (-18.0, 6.0)  # offset of the spot face callout (paper)
SPHERE_NAME_OFFSET = (-10.0, -2.0)  # offset of the sphere name callout (paper)
FLAT_TARGET_FRACTION = 0.8  # frame leader lands this fraction of the spot radius from the axis
SPOT_FRAME_DX = 18.0  # spot face frame offset right of its target (paper)
SPOT_FRAME_DY = 14.0  # spot face frame offset above its target (paper)
DETAIL_H_LABEL_DY = -12.0  # detail H label below the lowest cut edge (paper)
HOLE_DIM_OFFSET = 18.0  # depth dimension offset right of the section edge (paper)


def _detail_sphere_a(sh: Sheet, pole: tuple[float, float]) -> None:
    """Detail H: blind mating hole in steel sphere A."""
    rs = SPHERE_A_D / 2
    v = View(sh, (pole[0], pole[1] - rs * DETAIL_SCALE), DETAIL_SCALE)
    rh = HOLE_A_D / 2
    z_edge = math.sqrt(rs ** 2 - rh ** 2)  # sphere surface at the hole edge
    z_bot = rs - HOLE_A_DEPTH
    notch = [(-rh, z_edge), (-rh, z_bot), (rh, z_bot), (rh, z_edge)]
    _sphere_section(v, rs, SPHERE_A_SHOWN_HALF, SPHERE_A_SHOWN_DEPTH, notch)
    v.center_v(z_bot - DETAIL_CENTER_EXT, rs + DETAIL_CENTER_EXT, 0.0)
    v.dim_v(SPHERE_A_SHOWN_HALF, SPHERE_A_SHOWN_HALF, z_bot, rs, HOLE_DIM_OFFSET,
            f"{_fmt(HOLE_A_DEPTH)} DEEP", base_u=SPHERE_A_SHOWN_HALF)
    # hole diameter: leader from above, down through the open hole, onto its wall
    tgt = (rh, z_bot + HOLE_LEADER_HEIGHT)
    v.leader(tgt, f"Ø{_fmt(HOLE_A_D)} {TOL_HOLE_STEEL}", HOLE_LEADER_DX, pole[1] + HOLE_LABEL_ABOVE_POLE - v.P(*tgt)[1])
    u_l = SPHERE_A_SHOWN_HALF * SPHERE_A_LEADER_FRACTION
    v.leader((u_l, math.sqrt(rs ** 2 - u_l ** 2)), f"SPHERE A Ø{_fmt(SPHERE_A_D)} (STEEL)", *SPHERE_LEADER_OFFSET)
    y_label = pole[1] - SPHERE_A_SHOWN_DEPTH * DETAIL_SCALE + DETAIL_H_LABEL_DY
    sh.text(pole[0], y_label, f"DETAIL H: MATING HOLE IN STEEL SPHERE A (Ø{_fmt(SPHERE_A_D)})",
            size=d.FONT_LABEL, ha="center", weight="bold")
    sh.text(pole[0], y_label - SCALE_LABEL_DY, f"SCALE {DETAIL_SCALE_TEXT}", size=d.FONT_LABEL, ha="center",
            weight="bold")


def _detail_sphere_b(sh: Sheet, pole: tuple[float, float]) -> None:
    """Detail H: tapped hole and spot face at the pole of aluminum sphere B."""
    rs = SPHERE_B_D / 2
    v = View(sh, (pole[0], pole[1] - rs * DETAIL_SCALE), DETAIL_SCALE)
    r_maj = SPEC_04.thread_d / 2
    r_min = SPEC_04.minor_d / 2
    r_spot = SPOT_B_D / 2
    z_flat = rs - SPOT_B_DEPTH
    z_wall = math.sqrt(rs ** 2 - r_spot ** 2)  # sphere surface at the spot face wall
    z_thread = z_flat - TIP_B_THREAD_DEPTH
    z_drill = z_thread - TIP_B_DRILL_EXTRA
    notch = [(-r_spot, z_wall), (-r_spot, z_flat), (-r_min, z_flat), (-r_min, z_drill),
             (r_min, z_drill), (r_min, z_flat), (r_spot, z_flat), (r_spot, z_wall)]
    _sphere_section(v, rs, SPHERE_B_SHOWN_HALF, SPHERE_B_SHOWN_DEPTH, notch)
    for sgn in (1.0, -1.0):  # thread major diameter (thin line in the hatch)
        v.line((sgn * r_maj, z_flat), (sgn * r_maj, z_thread), "thin")
    v.center_v(z_drill - DETAIL_CENTER_EXT, rs + DETAIL_CENTER_EXT, 0.0)
    v.dim_v(SPHERE_B_SHOWN_HALF, SPHERE_B_SHOWN_HALF, z_thread, z_flat, HOLE_DIM_OFFSET,
            f"{_fmt(TIP_B_THREAD_DEPTH)}", base_u=SPHERE_B_SHOWN_HALF)
    # thread callout from above, down into the open hole
    v.leader((r_min, z_flat - THREAD_TARGET_DEPTH),
             f"M{_fmt(SPEC_04.thread_d)} {THREAD_TOL_INTERNAL} × {_fmt(TIP_B_THREAD_DEPTH)} DEEP "
             f"(DRILL {_fmt(TIP_B_THREAD_DEPTH + TIP_B_DRILL_EXTRA)} DEEP)", *THREAD_CALLOUT_OFFSET)
    # spot face callout to the left, sphere name above-left
    v.leader((-r_spot, z_wall), f"SPOT FACE Ø{_fmt(SPOT_B_D)} × {SPOT_B_DEPTH:.1f} BELOW POLE",
             *SPOT_CALLOUT_OFFSET)
    u_l = SPHERE_B_SHOWN_HALF
    v.leader((-u_l, math.sqrt(rs ** 2 - u_l ** 2)), f"SPHERE B Ø{_fmt(SPHERE_B_D)} (ALUMINUM)",
             *SPHERE_NAME_OFFSET)
    # perpendicularity of the spot face to the hole axis (datum C)
    flat_pt = v.P(r_spot * FLAT_TARGET_FRACTION, z_flat)
    fr = sh.fcf(flat_pt[0] + SPOT_FRAME_DX, flat_pt[1] + SPOT_FRAME_DY, "perp", TOL_SPOT_B, (DATUM_HOLE,))
    sh.frame_leader(fr["bottom"], (flat_pt[0], flat_pt[1] + FRAME_ARROW_GAP))
    sh.datum_feature(v.P(0.0, z_drill), (0.0, -1.0), DATUM_HOLE)
    y_label = pole[1] - SPHERE_B_SHOWN_DEPTH * DETAIL_SCALE + DETAIL_H_LABEL_DY
    sh.text(pole[0], y_label, f"DETAIL H: SPHERE B INTERFACE (TURNED ALUMINUM SPHERE Ø{_fmt(SPHERE_B_D)})",
            size=d.FONT_LABEL, ha="center", weight="bold")
    sh.text(pole[0], y_label - SCALE_LABEL_DY, f"SCALE {DETAIL_SCALE_TEXT}", size=d.FONT_LABEL, ha="center",
            weight="bold")


def build_all(out_dir: str) -> dict[str, list[str]]:
    """Draw SC1-03 and SC1-04."""
    return {SPEC_03.number: build_stem(SPEC_03, out_dir, True),
            SPEC_04.number: build_stem(SPEC_04, out_dir, False)}


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for k, v in build_all(here).items():
        print(k, "issues:", len(v))
        for i in v:
            print("   ", i)
