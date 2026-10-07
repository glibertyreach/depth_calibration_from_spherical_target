"""Shop drawing SC1-05: board adapter (flange plate with pads, stops and clamp fingers).

Plan view: looked at from the FRONT (board side), x to the right (the long edge, the
+Xm direction of the board frame), y up, origin at the plate center.

Elevation: SECTION A-A, an aligned section.  The cutting plane runs down the vertical
center line (through the top support pad, finger and screw) and bends at the axis
toward +Xm so that the dowel hole is shown rotated into the section.  In the
elevation u is the distance from the plate FRONT face toward the back (flange side),
so the pads, board and fingers are at negative u and the spigot at positive u.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import drafting as d
from drafting import RED, Sheet, TitleInfo, View, polar, thread_minor_diameter

# ---------------------------------------------------------------------------
# Part dimensions (mm)
# ---------------------------------------------------------------------------
PLATE_W = 220.0  # plate length along x
PLATE_H = 170.0  # plate height along y
PLATE_T = 12.0  # plate thickness
BOARD_W = 200.0  # board outline, along x
BOARD_H = 150.0  # board outline, along y
BOARD_T_NOMINAL = 6.0  # minimum board thickness t, drawn as the nominal
FLANGE_PCD = 50.0  # flange bolt circle diameter
SPIGOT_D = 31.5  # back-side centering spigot diameter
SPIGOT_H = 5.0  # spigot height
SPIGOT_CHAMFER = 0.5  # spigot chamfer 0.5 x 45
DOWEL_D = 6.0  # dowel hole / pin diameter
DOWEL_PIN_LEN = 16.0  # dowel pin length
DOWEL_PROTRUSION = 5.0  # dowel pin protrusion toward the flange
BOLT_HOLE_D = 6.6  # clearance hole for M6
CBORE_D = 11.0  # counterbore diameter
CBORE_DEPTH = 6.5  # counterbore depth, from the FRONT
FLANGE_SCREW_ENGAGEMENT = 6.5  # thread engagement in the robot flange, the same as on SC1-01 and SC1-02
# M6 DIN 7984 screw length: the grip under the counterbore plus the engagement (12 - 6.5 + 6.5 = 12)
FLANGE_SCREW_LEN = PLATE_T - CBORE_DEPTH + FLANGE_SCREW_ENGAGEMENT
POSITION_TOL = 0.1  # Ø position tolerance of the bolt holes
BOLT_ANGLES = (45.0, 135.0, 225.0, 315.0)  # bolt hole angles from +Xm
PAD_D = 15.0  # support pad diameter
PAD_H = 1.0  # support pad height above the front face
PADS = {"P1": (-92.0, -67.0), "P2": (92.0, -67.0), "P3": (0.0, 67.0)}  # pad centers (x, y)
STOP_D = 6.0  # edge-locating pin diameter
STOP_LEN = 10.0  # edge-locating pin length
STOP_PROTRUSION = 4.0  # edge-locating pin protrusion above the front face
STOPS = {"S1": (-60.0, -78.0), "S2": (60.0, -78.0), "S3": (-103.0, 0.0)}  # pin centers
FINGER_W = 12.0  # clamp finger width
FINGER_T = 3.0  # clamp finger thickness
FINGER_OVERLAP = 12.0  # finger overlap onto the board edge
SCREW_OUTSIDE = 6.0  # M4 hole center outside the board edge
FINGER_BEYOND = 6.0  # finger length beyond the M4 hole center (chosen)
M4_D = 4.0  # screw thread diameter
M4_PITCH = 0.7  # coarse pitch of M4
M4_DEPTH = 8.0  # tapped thread depth
M4_DRILL_D = 3.3  # tap drill diameter
M4_DRILL_EXTRA = 2.0  # drill deeper than the thread (chosen)
M4_CLEAR_D = 4.5  # clearance hole in the finger and spacer
NYLON_D = 6.0  # nylon pad diameter (chosen)
NYLON_T = 2.0  # nylon pad thickness (chosen)
NYLON_FROM_TIP = 4.0  # nylon pad center distance from the finger tip (chosen, over the support pad)
SPACER_D = 8.0  # spacer sleeve outer diameter (chosen)
SCREW_HEAD_D = 7.0  # socket head diameter of M4 (DIN 912)
SCREW_HEAD_H = 4.0  # socket head height of M4 (DIN 912)
TAPPED_FINGERS = {"F1": (-92.0, -1.0), "F2": (92.0, -1.0), "F3": (0.0, 1.0)}  # x of finger, side (+1 top / -1 bottom)

TOL_SPIGOT = "g6"  # spigot tolerance
TOL_DOWEL_HOLE = "H7"  # dowel hole tolerance
TOL_PIN = "m6"  # pin tolerance
TOL_PADS_COPLANAR = "0.01"  # pad tops lapped coplanar
TOL_PADS_PARALLEL = "0.02"  # pad tops parallel to the back face
DATUM_BACK = "C"  # back (flange) face

# ---------------------------------------------------------------------------
# Sheet layout (paper mm)
# ---------------------------------------------------------------------------
SCALE = 1.0
SCALE_TEXT = "1:1"
PLAN_CENTER = (127.0, 160.0)  # paper position of the plate center in the plan
ELEV_ORIGIN = (316.0, 160.0)  # paper position of (u = 0, v = 0): plate front face, axis
PLAN_LABEL = (15.0, 253.0)  # left end and baseline of the plan label
ELEV_LABEL = (316.0, 253.0)  # center and baseline of the elevation label
DIM_OVERALL_OFFSET = -9.0  # overall width dimension below the plate (paper)
DIM_HEIGHT_OFFSET = 10.0  # overall height dimension right of the plate (paper)
BOARD_LABEL_Y = 40.0  # y (model) where the board outline label attaches
NOTES_X = 12.0  # notes block left edge
NOTES_TOP = 60.0  # notes block top
NOTES_COLUMN_W = 72.0  # width of each of the three notes columns
NOTES_COLUMN_GAP = 4.0  # gap between notes columns
RIGHT_X = 350.0  # left edge of the right-hand column
RIGHT_W = 59.0  # width of the right-hand column
TAP_CALLOUT_Y = 246.0  # y of the tapped hole callout text
FLANGE_NOTE_TOP = 236.0  # top of the boxed flange note
DOWEL_CALLOUT_Y = 188.0  # y of the dowel pin callout text
TABLE_TOP = 168.0  # top of the position table
TABLE_WIDTHS = (9.5, 29.0, 10.5, 10.0)  # table column widths: tag, feature, x, y
TABLE_FONT = 9.5  # table text size
TAG_SIZE = 10.0  # size of the feature tags in the plan
NOTES_SIZE = 9.0  # notes text size (the minimum allowed)
XM_ARROW = ((45.0, -9.0), (75.0, -9.0))  # +Xm key arrow start and end (model, plan)
CUT_TOP_Y = 92.0  # cutting-plane top end (model y)
CUT_DOWEL_X = 40.0  # cutting-plane end of the dowel leg (model x)
FINGER_CHAIN_X = 24.0  # x (model) of the finger dimension chain in the plan
CENTER_EXT_PLAN = 6.0  # plan centerlines extend this far past the plate (model)
BOTTOM_ROW_1 = -8.0  # elevation bottom dimension row 1 offset (paper)
RIGHT_DIM_1 = 8.0  # elevation vertical dimension offset right of the spigot (paper)
PIN_DIM_OFFSET = 12.0  # pin protrusion dimension offset above the dowel (paper)
STACK_LEADER_DX = -6.0  # leaders from the finger stack run this far left (paper)
FRAME_PAD_X = -62.0  # x (model) of the pad flatness frames in the plan
FRAME_PAD_Y = (69.0, 61.0)  # y (model) of the two pad frames
PAD_FRAME_TARGETS = ((-7.5, 67.0), (-5.5, 62.2))  # frame leader targets on pad P3 (model)
DATUM_C_V = -50.0  # v where datum C is attached to the back face
TAG_POS = {"P1": (-83.0, -66.0), "P2": (76.0, -66.0), "P3": (9.0, 54.0),
           "S1": (-72.0, -72.0), "S2": (50.0, -72.0), "S3": (-98.0, 4.0),
           "F1": (-84.0, -84.0), "F2": (76.0, -84.0), "F3": (9.0, 76.0)}  # tag text positions (model)
SIGHT_UP = (0.0, 1.0)  # arrow direction of the dowel leg of the cutting plane
SIGHT_LEFT = (-1.0, 0.0)  # arrow direction of the vertical leg of the cutting plane
XM_LABEL_DY = -5.0  # +Xm label baseline relative to its arrow (paper)
DIM_TEXT_POS_WIDTH = 0.27  # text position along the overall width dimension
DIM_TEXT_POS_HEIGHT = 0.25  # text position along the overall height dimension
BOARD_LABEL_DX = 4.0  # board outline label offset from its dot (paper)
BOLT_LEADER = (40.0, 20.0, 22.0)  # angle, dx, dy of the bolt hole callout
BOLT_FRAME_DY = -6.0  # position frame offset below the bolt callout text (paper)
PCD_LEADER = (150.0, -14.0, 14.0)  # angle, dx, dy of the pitch circle leader
DOWEL_LEADER = (300.0, 12.0, -22.0)  # angle, dx, dy of the dowel hole callout
SPIGOT_LEADER = (200.0, -30.0, -12.0)  # angle, dx, dy of the spigot callout
PAD_LABEL_DY = -6.5  # "PAD TOPS" text offset below the lower pad frame (paper)
ELEV_CENTER_EXT = 3.0  # elevation centerlines extend this far past the part (model mm)
HEAD_CENTER_EXT = 4.0  # axis centerline extends this far past the screw head (model mm)
FINGER_LEADER_DY = -4.0  # finger callout vertical offset (paper)
NYLON_LEADER_DY = -14.0  # nylon callout vertical offset (paper)
BOARD_LEADER_V = 40.0  # v where the board callout lands (model mm)
CALLOUT_ELBOW_GAP = 8.0  # gap between the right-hand callout elbow and the column (paper)
NOTES_COLUMNS = 3  # number of notes columns
WHITE_MASK_Z = 3.4  # z-order of white masking fills (above hatch and lines, below outlines drawn after)
FINGER_Z = 4.0  # z-order of finger outlines in the plan

MATERIAL = "Aluminum 6061-T6 or MIC-6 cast plate"
FINISH = "Black anodize, matte"


def _fmt(x: float) -> str:
    return f"{x:g}"


def build(out_dir: str) -> list[str]:
    """Draw SC1-05 and save it.  Returns the QA issues found."""
    sh = Sheet("SC1-05")
    sh.border()
    t = BOARD_T_NOMINAL
    hw, hh = PLATE_W / 2, PLATE_H / 2
    bw, bh = BOARD_W / 2, BOARD_H / 2
    pr = FLANGE_PCD / 2
    rs = SPIGOT_D / 2
    rd0, rd1 = pr - DOWEL_D / 2, pr + DOWEL_D / 2
    cb_pts = [polar((0, 0), pr, a) for a in BOLT_ANGLES]
    # u positions of the finger stack (negative = in front of the plate)
    u_board_bot = -PAD_H
    u_board_top = u_board_bot - t
    u_nyl_top = u_board_top - NYLON_T
    u_fing_top = u_nyl_top - FINGER_T
    u_head_top = u_fing_top - SCREW_HEAD_H
    spacer_len = -u_nyl_top  # plate front face to finger underside = t + 3
    screw_len = spacer_len + FINGER_T + M4_DEPTH  # M4 x (t + 14)
    tip_y = bh - FINGER_OVERLAP  # finger tip (model y, top finger)
    screw_y = bh + SCREW_OUTSIDE  # M4 axis
    end_y = screw_y + FINGER_BEYOND  # finger end
    nyl_y = tip_y + NYLON_FROM_TIP  # nylon pad center
    finger_len = end_y - tip_y

    # =====================================================================
    # PLAN VIEW FROM THE FRONT
    # =====================================================================
    plan = View(sh, PLAN_CENTER, SCALE)
    plan.polyline([(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)], "outline", closed=True)
    plan.polyline([(-bw, -bh), (bw, -bh), (bw, bh), (-bw, bh)], "phantom", closed=True)
    plan.center_h(-hw - CENTER_EXT_PLAN, hw + CENTER_EXT_PLAN, 0.0)
    plan.center_v(-hh - CENTER_EXT_PLAN, hh + CENTER_EXT_PLAN, 0.0)
    plan.circle((0, 0), pr, "center")
    plan.circle((0, 0), rs, "hidden")  # back-side spigot
    plan.circle((pr, 0.0), DOWEL_D / 2, "hidden")  # back-side dowel hole at +Xm
    for p in cb_pts:  # counterbored holes, visible from the front
        plan.circle(p, BOLT_HOLE_D / 2, "outline")
        plan.circle(p, CBORE_D / 2, "outline")
        plan.center_cross(p, CBORE_D / 2)
    for x, y in PADS.values():
        plan.circle((x, y), PAD_D / 2, "outline")
    for x, y in STOPS.values():
        plan.circle((x, y), STOP_D / 2, "outline")
        plan.center_cross((x, y), STOP_D / 2)
    # clamp fingers lie over the pads: white fill hides what is under them
    for fx, side in TAPPED_FINGERS.values():
        y0, y1 = side * tip_y, side * end_y
        pts = [plan.P(fx - FINGER_W / 2, y0), plan.P(fx + FINGER_W / 2, y0),
               plan.P(fx + FINGER_W / 2, y1), plan.P(fx - FINGER_W / 2, y1)]
        sh.polygon_fill(pts, d.WHITE, zorder=WHITE_MASK_Z)
        sh.line(pts + [pts[0]], "outline", zorder=FINGER_Z)
        sh.circle(plan.P(fx, side * screw_y), SCREW_HEAD_D / 2 * SCALE, "outline")
        sh.circle(plan.P(fx, side * screw_y), M4_D / 2 * SCALE, "thin")
    # +Xm key (red)
    (kx0, ky0), (kx1, ky1) = XM_ARROW
    a0, a1 = plan.P(kx0, ky0), plan.P(kx1, ky1)
    sh.line([a0, a1], "outline", RED)
    sh.arrow(a1, (1, 0), RED)
    sh.text(a0[0], a0[1] + XM_LABEL_DY, "+Xm", size=d.FONT_NOTE, color=RED, weight="bold")
    # cutting plane A-A (aligned): top leg down the center, then toward +Xm
    plan.cutting_plane([(0.0, CUT_TOP_Y), (0.0, 0.0), (CUT_DOWEL_X, 0.0)], sight=SIGHT_LEFT, label="A",
                       sight_end=SIGHT_UP)
    # dimensions: overall size, board outline, finger chain
    plan.dim_h(-hw, hw, -hh, -hh, DIM_OVERALL_OFFSET, _fmt(PLATE_W), text_pos=DIM_TEXT_POS_WIDTH)
    plan.dim_v(hw, hw, -hh, hh, DIM_HEIGHT_OFFSET, _fmt(PLATE_H), text_pos=DIM_TEXT_POS_HEIGHT)
    plan.leader((-bw, BOARD_LABEL_Y), f"BOARD OUTLINE (PHANTOM)\n{_fmt(BOARD_W)} × {_fmt(BOARD_H)} × t", BOARD_LABEL_DX, 0.0,
                terminator="dot")
    cx = FINGER_CHAIN_X
    fx_edge = FINGER_W / 2  # right edge of the top finger, where the extension lines start
    plan.dim_v(fx_edge, cx, tip_y, bh, 0.0, _fmt(FINGER_OVERLAP), outside="down", base_u=cx, ext1=False)
    plan.dim_v(cx, fx_edge, bh, screw_y, 0.0, _fmt(SCREW_OUTSIDE), outside="up", base_u=cx, ext0=False)
    # feature tags
    for tag, (x, y) in TAG_POS.items():
        px, py = plan.P(x, y)
        sh.text(px, py, tag, size=TAG_SIZE, weight="bold")
    # callouts
    box = plan.leader_circle(cb_pts[0], CBORE_D / 2, BOLT_LEADER[0],
                             f"4 × Ø{_fmt(BOLT_HOLE_D)} THRU AT 45°,\n135°, 225°, 315° FROM +Xm\n"
                             f"CBORE Ø{_fmt(CBORE_D)} × {_fmt(CBORE_DEPTH)} DEEP\nFROM THE FRONT", *BOLT_LEADER[1:])
    sh.fcf(box[0], box[1] + BOLT_FRAME_DY, "position", f"Ø{_fmt(POSITION_TOL)}", ())
    plan.leader_circle((0, 0), pr, PCD_LEADER[0], f"Ø{_fmt(FLANGE_PCD)} PCD", *PCD_LEADER[1:])
    plan.leader_circle((pr, 0.0), DOWEL_D / 2, DOWEL_LEADER[0],
                       f"DOWEL HOLE Ø{_fmt(DOWEL_D)} {TOL_DOWEL_HOLE} THRU\nAT +Xm (HIDDEN)", *DOWEL_LEADER[1:])
    plan.leader_circle((0, 0), rs, SPIGOT_LEADER[0],
                       f"SPIGOT Ø{_fmt(SPIGOT_D)} {TOL_SPIGOT} × {_fmt(SPIGOT_H)}\n{_fmt(SPIGOT_CHAMFER)} × 45° CHAMFER\nON BACK (HIDDEN)", *SPIGOT_LEADER[1:])
    # pad flatness / parallelism frames, leader to pad P3
    fy1, fy2 = FRAME_PAD_Y
    f1 = sh.fcf(*plan.P(FRAME_PAD_X, fy1), "flat", TOL_PADS_COPLANAR)
    f2 = sh.fcf(*plan.P(FRAME_PAD_X, fy2), "para", TOL_PADS_PARALLEL, (DATUM_BACK,))
    sh.frame_leader(f1["right"], plan.P(*PAD_FRAME_TARGETS[0]))
    sh.frame_leader(f2["right"], plan.P(*PAD_FRAME_TARGETS[1]))
    sh.text(f2["left"][0], f2["left"][1] + PAD_LABEL_DY, "PAD TOPS P1-P3", size=d.FONT_NOTE)

    # =====================================================================
    # ELEVATION: SECTION A-A
    # =====================================================================
    el = View(sh, ELEV_ORIGIN, SCALE)
    c_sp = SPIGOT_CHAMFER
    back = PLATE_T + SPIGOT_H  # u of the spigot end
    main = [(0.0, -hh), (PLATE_T, -hh), (PLATE_T, -rs), (back - c_sp, -rs), (back, -rs + c_sp),
            (back, rs - c_sp), (back - c_sp, rs), (PLATE_T, rs), (PLATE_T, rd0), (0.0, rd0)]
    r_dr = M4_DRILL_D / 2
    pad_v0, pad_v1 = PADS["P3"][1] - PAD_D / 2, PADS["P3"][1] + PAD_D / 2
    drill_u = M4_DEPTH + M4_DRILL_EXTRA
    top = [(0.0, rd1), (PLATE_T, rd1), (PLATE_T, hh), (0.0, hh), (0.0, screw_y + r_dr),
           (drill_u, screw_y + r_dr), (drill_u, screw_y - r_dr), (0.0, screw_y - r_dr),
           (0.0, pad_v1), (-PAD_H, pad_v1), (-PAD_H, pad_v0), (0.0, pad_v0)]
    el.section_region(main)
    el.section_region(top)
    pin_u0 = back - DOWEL_PIN_LEN
    el.section_region([(pin_u0, rd0), (back, rd0), (back, rd1), (pin_u0, rd1)], other=True)
    el.polyline([(u_board_bot, -bh), (u_board_top, -bh), (u_board_top, bh), (u_board_bot, bh)], "phantom",
                closed=True)
    fh = M4_CLEAR_D / 2
    for v0, v1 in ((tip_y, screw_y - fh), (screw_y + fh, end_y)):  # finger, cut by the clearance hole
        el.section_region([(u_nyl_top, v0), (u_fing_top, v0), (u_fing_top, v1), (u_nyl_top, v1)])
    el.section_region([(u_board_top, nyl_y - NYLON_D / 2), (u_nyl_top, nyl_y - NYLON_D / 2),
                       (u_nyl_top, nyl_y + NYLON_D / 2), (u_board_top, nyl_y + NYLON_D / 2)], other=True)
    for v0, v1 in ((screw_y - SPACER_D / 2, screw_y - fh), (screw_y + fh, screw_y + SPACER_D / 2)):
        el.section_region([(0.0, v0), (u_nyl_top, v0), (u_nyl_top, v1), (0.0, v1)], other=True)
    sr, hr = M4_D / 2, SCREW_HEAD_D / 2
    u_end = u_fing_top + screw_len
    screw_poly = [(u_fing_top, screw_y - hr), (u_head_top, screw_y - hr), (u_head_top, screw_y + hr),
                  (u_fing_top, screw_y + hr), (u_fing_top, screw_y + sr), (u_end, screw_y + sr),
                  (u_end, screw_y - sr), (u_fing_top, screw_y - sr)]
    sh.polygon_fill([el.P(*p) for p in screw_poly], d.WHITE, zorder=WHITE_MASK_Z)
    el.polyline(screw_poly, "outline", closed=True)
    el.center_h(u_head_top - HEAD_CENTER_EXT, back + ELEV_CENTER_EXT, 0.0)
    el.center_h(-ELEV_CENTER_EXT, back + ELEV_CENTER_EXT, pr)

    # ---- elevation dimensions ----------------------------------------------
    el.dim_h(0, PLATE_T, -hh, -hh, BOTTOM_ROW_1, _fmt(PLATE_T))
    el.dim_h(PLATE_T, back, -rs, -rs, BOTTOM_ROW_1, _fmt(SPIGOT_H), outside="right")
    el.dim_v(back, back, -rs, rs, RIGHT_DIM_1, f"Ø{_fmt(SPIGOT_D)} {TOL_SPIGOT}")
    el.dim_h(PLATE_T, back, rd1, rd1, PIN_DIM_OFFSET, _fmt(DOWEL_PROTRUSION), outside="right")
    # datum C on the back face
    sh.datum_feature(el.P(PLATE_T, DATUM_C_V), (1.0, 0.0), DATUM_BACK)

    # ---- elevation callouts -----------------------------------------------------
    el.leader((u_fing_top, (tip_y + screw_y - SCREW_HEAD_D / 2 - 1.0) / 2),
              f"CLAMP FINGER AL\n{_fmt(FINGER_W)} × {_fmt(FINGER_T)} × {_fmt(finger_len)}", STACK_LEADER_DX, FINGER_LEADER_DY)
    el.leader((u_head_top, screw_y), f"SCREW M4 × (t + {_fmt(screw_len - t)})\nSOCKET HEAD",
              STACK_LEADER_DX, 0.0)
    el.leader((u_board_top, BOARD_LEADER_V), "BOARD t ≥ 6\n(PHANTOM)", STACK_LEADER_DX, 0.0)
    el.leader(((u_board_top + u_nyl_top) / 2, nyl_y - NYLON_D / 2),
              f"NYLON Ø{_fmt(NYLON_D)} × {_fmt(NYLON_T)}", STACK_LEADER_DX, NYLON_LEADER_DY)
    el.leader((drill_u, screw_y), f"TAPPED M4 × {_fmt(M4_DEPTH)}\n(DRILL Ø{_fmt(M4_DRILL_D)} × {_fmt(drill_u)})",
              RIGHT_X - el.P(drill_u, screw_y)[0] - CALLOUT_ELBOW_GAP, TAP_CALLOUT_Y - el.P(drill_u, screw_y)[1])
    el.leader((back, pr - DOWEL_D / 2), f"DOWEL PIN Ø{_fmt(DOWEL_D)} {TOL_PIN} × {_fmt(DOWEL_PIN_LEN)}\n"
              f"PRESSED IN", RIGHT_X - el.P(back, pr)[0] - CALLOUT_ELBOW_GAP, DOWEL_CALLOUT_Y - el.P(back, pr)[1])
    # dimension: board face to flange face D
    # (stated in the notes)

    # =====================================================================
    # Right column: boxed flange note and position table
    # =====================================================================
    sh.boxed_note(RIGHT_X, FLANGE_NOTE_TOP, RIGHT_W, d.TEXT_FLANGE_NOTE)
    rows = [("TAG", "FEATURE", "X", "Y")]
    for tag, (x, y) in PADS.items():
        rows.append((tag, f"Pad Ø{_fmt(PAD_D)} × {PAD_H:.1f}", _fmt(x), _fmt(y)))
    for tag, (x, y) in STOPS.items():
        rows.append((tag, f"Pin Ø{_fmt(STOP_D)} {TOL_PIN} × {_fmt(STOP_LEN)}", _fmt(x), _fmt(y)))
    for tag, (fx, side) in TAPPED_FINGERS.items():
        rows.append((tag, f"M4 × {_fmt(M4_DEPTH)} tapped", _fmt(fx), _fmt(side * screw_y)))
    sh.table(RIGHT_X, TABLE_TOP, TABLE_WIDTHS, rows, "FEATURE POSITIONS", size=TABLE_FONT)

    # ---- labels, notes, title block ------------------------------------------------
    sh.text(PLAN_LABEL[0], PLAN_LABEL[1], f"PLAN VIEW FROM FRONT   SCALE {SCALE_TEXT}", size=d.FONT_LABEL,
            weight="bold")
    sh.text(ELEV_LABEL[0], ELEV_LABEL[1], f"SECTION A-A   SCALE {SCALE_TEXT}", size=d.FONT_LABEL,
            ha="center", weight="bold")
    notes = [
        f"Board: {_fmt(BOARD_W)} × {_fmt(BOARD_H)} × t (t ≥ 6), front face matte light gray; phantom line = board "
        f"outline. Flange face to board face D = {_fmt(PLATE_T + PAD_H)} + t.",
        f"Datum C = back face. Pad tops P1-P3 lapped coplanar within {TOL_PADS_COPLANAR} and parallel to C "
        f"within {TOL_PADS_PARALLEL}.",
        f"Pins S1-S3: Ø{_fmt(STOP_D)} {TOL_PIN} × {_fmt(STOP_LEN)}, pressed in, {_fmt(STOP_PROTRUSION)} "
        f"proud; they stop a {_fmt(BOARD_W)} × {_fmt(BOARD_H)} board so that it rests centered on the flange axis.",
        f"Fingers F1-F3, one over each pad: aluminum {_fmt(FINGER_W)} × {_fmt(FINGER_T)} × "
        f"{_fmt(finger_len)}, matte black, {_fmt(FINGER_OVERLAP)} over the board edge, held by one M4 screw in a "
        f"tapped M4 × {_fmt(M4_DEPTH)} hole {_fmt(SCREW_OUTSIDE)} outside the board edge, on the pad's line. "
        f"Nylon pad Ø{_fmt(NYLON_D)} × {_fmt(NYLON_T)} under the tip.",
        f"Per finger: spacer Ø{_fmt(SPACER_D)} × (t + {_fmt(NYLON_T + PAD_H)}), screw M4 × "
        f"(t + {_fmt(screw_len - t)}).",
        f"Dowel pin Ø{_fmt(DOWEL_D)} {TOL_PIN} × {_fmt(DOWEL_PIN_LEN)} pressed into the Ø{_fmt(DOWEL_D)} "
        f"{TOL_DOWEL_HOLE} hole, {_fmt(DOWEL_PROTRUSION)} proud toward the flange.",
        f"Counterbores are cut from the FRONT for 4 × M6 × {_fmt(FLANGE_SCREW_LEN)} DIN 7984 screws "
        f"({_fmt(FLANGE_SCREW_ENGAGEMENT)} thread engagement in the flange); fit them before the board is "
        f"mounted. Position tolerance Ø{_fmt(POSITION_TOL)}; Ø{_fmt(FLANGE_PCD)} and 45° are basic.",
        "Section A-A is an aligned section: the dowel hole at +Xm is rotated into the cutting plane.",
        "Dimensions apply after finishing: mask the spigot, the dowel hole and the tapped holes when anodizing.",
    ]
    sh.notes_columns(NOTES_X, NOTES_TOP, NOTES_COLUMN_W, NOTES_COLUMN_GAP, notes, NOTES_COLUMNS, size=NOTES_SIZE)
    sh.title_block(TitleInfo("SC1-05", "Board adapter", "1", MATERIAL, FINISH, SCALE_TEXT))
    return sh.save(os.path.join(out_dir, "SC1-05_board_adapter.png"))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    issues = build(here)
    print("SC1-05 issues:", len(issues))
    for i in issues:
        print("   ", i)
