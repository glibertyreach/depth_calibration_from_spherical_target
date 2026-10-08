"""Shop drawing SC1-06: three-ball nest base.

Plan view from the top (x right, y up, origin at the plate center).  The elevation
is SECTION A-A through the center and the ball at 90 degrees; viewed from the +x
side, so +y is to the right.  In the elevation, u = y (horizontal, from the center)
and v = height above the plate top, so the plate occupies v from -PLATE_T to 0.

The sphere's seating height is computed, not typed:  a sphere of radius R resting on the
three balls (radius r, center height h_b, on a pitch circle of radius p) has its
center at   z = h_b + sqrt((R + r)^2 - p^2)   above the plate top.
"""

from __future__ import annotations

import math
import os

import drafting as d
from drafting import Sheet, TitleInfo, View, polar

# ---------------------------------------------------------------------------
# Part dimensions (mm)
# ---------------------------------------------------------------------------
PLATE_W = 120.0  # plate size, square
PLATE_T = 20.0  # plate thickness
POCKET_D = 24.0  # ball pocket diameter (H7)
POCKET_DEPTH = 10.0  # pocket depth
POCKET_PCD = 60.0  # pocket pitch circle diameter
POCKET_ANGLES = (90.0, 210.0, 330.0)  # pocket angles from +x
BALL_D = 24.0  # bearing ball diameter, grade 25 (52100)
BALL_CENTER_H = 2.0  # ball center above the plate top
BOLT_SQUARE = 100.0  # bolt hole square
BOLT_HOLE_D = 9.0  # through hole for M8
BOLT_CBORE_D = 15.0  # counterbore diameter
BOLT_CBORE_DEPTH = 9.0  # counterbore depth from the top
SPHERE_B_R = 76.2  # sphere B radius (Ø152.4), the only calibration sphere (decision D-15)
TOL_POCKET = "H7"  # pocket tolerance
TILT_NOTE_ANGLE = 40  # wrist tilt used to choose the bolt-down location, degrees


def sphere_center_height(sphere_r: float) -> float:
    """Height of a seated sphere's center above the plate top (see module docstring)."""
    return BALL_CENTER_H + math.sqrt((sphere_r + BALL_D / 2) ** 2 - (POCKET_PCD / 2) ** 2)


# ---------------------------------------------------------------------------
# Sheet layout (paper mm)
# ---------------------------------------------------------------------------
SCALE = 1.0
SCALE_TEXT = "1:1"
PLAN_CENTER = (88.0, 180.0)  # paper position of the plate center in the plan
ELEV_ORIGIN = (258.0, 96.0)  # paper position of (u = 0, v = 0): axis at the plate top
PLAN_LABEL_Y = 96.0  # baseline of the plan label
ELEV_LABEL = (342.0, 72.0)  # left end and baseline of the elevation label
NOTES_X = 12.0  # notes left edge
NOTES_TOP = 88.0  # notes top
NOTES_COLUMN_W = 84.0
NOTES_SIZE = 9.0  # notes text size (the minimum allowed)  # notes column width
NOTES_COLUMN_GAP = 6.0  # gap between notes columns
RIGHT_TEXT_X = 342.0  # x of the callout text in the right-hand column
POCKET_CALLOUT_END = (72.0, 251.0)  # right end x and y of the pocket callout text (paper)
BOLT_CALLOUT_START = (150.0, 251.0)  # left end x and y of the bolt callout text (paper)
CUT_END_Y = 64.0  # cutting-plane end distance from the plan center (model)
DIM_BOTTOM = -9.0  # overall width dimension below the plan (paper)
DIM_LEFT = -9.0  # overall height dimension left of the plan (paper)
DIM_BOTTOM_2 = -17.0  # bolt spacing dimension, second row below the plan (paper)
DIM_RIGHT = 6.0  # bolt spacing dimension right of the plan (paper)
ELEV_DIM_BOTTOM = -8.0  # plate width dimension below the plate (paper)
ELEV_DIM_THICK = -8.0  # plate thickness dimension left of the plate (paper)
ELEV_DIM_B = -22.0  # sphere B center height dimension, left of the plate edge (paper)
ELEV_DIM_BASE_U = -PLATE_W / 2  # u used as the base of the left dimension columns
CENTER_EXT_PLAN = 5.0  # plan centerlines extend this far past the plate (model mm)
TEXT_POS_DIM = 0.3  # position of dimension text along its dimension line
POCKET_LEADER_ANGLE = 135.0  # angle on the pocket circle where its callout lands
BOLT_LEADER_ANGLE = 45.0  # angle on the counterbore circle where its callout lands
BALL_LEADER_ANGLE = 40.0  # angle on the ball where its callout lands
BALL_OUTLINE_STEP_DEG = 3  # angular step of the ball outline
CENTER_V_EXT = 4.0  # elevation axis extends this far below the plate (model mm)
UPPER_RIGHT_BOLT = 3  # index of the (+x, +y) bolt hole in the bolt list
CALLOUT_Y = {"sphere_b": 200.0, "ball": 118.0, "pocket": 88.0}  # paper y of the callout texts
CENTER_MARK_R = 3.0  # half size of a sphere center cross, model mm
SIGHT_LEFT = (-1.0, 0.0)  # viewing direction arrows (looking toward -x)

MATERIAL = "Steel S235 / AISI 1018"
FINISH = "Black oxide"


def _fmt(x: float) -> str:
    return f"{x:g}"


def build(out_dir: str) -> list[str]:
    """Draw SC1-06 and save it.  Returns the QA issues found."""
    sh = Sheet("SC1-06")
    sh.border()
    hw = PLATE_W / 2
    pr = POCKET_PCD / 2
    br = BALL_D / 2
    half_sq = BOLT_SQUARE / 2
    z_b = sphere_center_height(SPHERE_B_R)
    pockets = [polar((0, 0), pr, a) for a in POCKET_ANGLES]
    bolts = [(sx * half_sq, sy * half_sq) for sx in (-1, 1) for sy in (-1, 1)]

    # =====================================================================
    # PLAN VIEW FROM THE TOP
    # =====================================================================
    plan = View(sh, PLAN_CENTER, SCALE)
    plan.polyline([(-hw, -hw), (hw, -hw), (hw, hw), (-hw, hw)], "outline", closed=True)
    plan.center_h(-hw - CENTER_EXT_PLAN, hw + CENTER_EXT_PLAN, 0.0)
    plan.center_v(-hw - CENTER_EXT_PLAN, hw + CENTER_EXT_PLAN, 0.0)
    plan.circle((0, 0), pr, "center")
    for p in pockets:
        plan.circle(p, POCKET_D / 2, "outline")
        plan.center_cross(p, POCKET_D / 2)
    for p in bolts:
        plan.circle(p, BOLT_HOLE_D / 2, "outline")
        plan.circle(p, BOLT_CBORE_D / 2, "outline")
        plan.center_cross(p, BOLT_CBORE_D / 2)
    plan.cutting_plane([(0.0, CUT_END_Y), (0.0, -CUT_END_Y)], sight=SIGHT_LEFT, label="A")
    # dimensions
    plan.dim_h(-hw, hw, -hw, -hw, DIM_BOTTOM, _fmt(PLATE_W), text_pos=TEXT_POS_DIM)
    plan.dim_v(-hw, -hw, -hw, hw, DIM_LEFT, _fmt(PLATE_W), text_pos=TEXT_POS_DIM)
    plan.dim_h(-half_sq, half_sq, -half_sq, -half_sq, DIM_BOTTOM_2, _fmt(BOLT_SQUARE), base_v=-hw, text_pos=TEXT_POS_DIM)
    plan.dim_v(half_sq, half_sq, -half_sq, half_sq, DIM_RIGHT, _fmt(BOLT_SQUARE), base_u=hw, text_pos=TEXT_POS_DIM)
    # callouts
    t = plan.P(*polar(pockets[0], POCKET_D / 2, POCKET_LEADER_ANGLE))
    plan.leader(polar(pockets[0], POCKET_D / 2, POCKET_LEADER_ANGLE),
                f"3 × POCKET Ø{_fmt(POCKET_D)} {TOL_POCKET} × {_fmt(POCKET_DEPTH)} DEEP\n"
                f"ON PCD Ø{_fmt(POCKET_PCD)} AT 90°, 210°, 330°",
                POCKET_CALLOUT_END[0] - t[0] + d.LEADER_SHOULDER + d.LEADER_TEXT_GAP, POCKET_CALLOUT_END[1] - t[1])
    t = plan.P(*polar(bolts[UPPER_RIGHT_BOLT], BOLT_CBORE_D / 2, BOLT_LEADER_ANGLE))
    plan.leader(polar(bolts[UPPER_RIGHT_BOLT], BOLT_CBORE_D / 2, BOLT_LEADER_ANGLE),
                f"4 × Ø{_fmt(BOLT_HOLE_D)} THRU\n"
                f"CBORE Ø{_fmt(BOLT_CBORE_D)} × {_fmt(BOLT_CBORE_DEPTH)} DEEP FROM TOP\nFOR M8 SOCKET CAP SCREWS",
                BOLT_CALLOUT_START[0] - t[0] - d.LEADER_SHOULDER - d.LEADER_TEXT_GAP, BOLT_CALLOUT_START[1] - t[1])

    # =====================================================================
    # ELEVATION: SECTION A-A
    # =====================================================================
    el = View(sh, ELEV_ORIGIN, SCALE)
    pk = pr  # u of the ball center in the section (ball at 90 degrees is at y = +pr)
    plate = [(-hw, -PLATE_T), (hw, -PLATE_T), (hw, 0.0), (pk + POCKET_D / 2, 0.0),
             (pk + POCKET_D / 2, -POCKET_DEPTH), (pk - POCKET_D / 2, -POCKET_DEPTH),
             (pk - POCKET_D / 2, 0.0), (-hw, 0.0)]
    el.section_region(plate)
    # ball, cut through its center (second hatch), outline of the full circle
    ball_pts = [(pk + br * math.cos(math.radians(a)), BALL_CENTER_H + br * math.sin(math.radians(a)))
                for a in range(0, int(d.FULL_CIRCLE_DEG) + 1, BALL_OUTLINE_STEP_DEG)]
    el.hatch(ball_pts, other=True)
    el.polyline(ball_pts, "outline", closed=True)
    el.center_cross((pk, BALL_CENTER_H), 0.0)
    # phantom sphere B, seated on the three balls
    el.circle((0.0, z_b), SPHERE_B_R, "phantom")
    el.line((-CENTER_MARK_R, z_b), (CENTER_MARK_R, z_b), "center")
    el.line((0.0, z_b - CENTER_MARK_R), (0.0, z_b + CENTER_MARK_R), "center")
    el.center_v(-PLATE_T - CENTER_V_EXT, z_b + 2 * CENTER_MARK_R, 0.0)

    # dimensions
    el.dim_h(-hw, hw, -PLATE_T, -PLATE_T, ELEV_DIM_BOTTOM, _fmt(PLATE_W), text_pos=TEXT_POS_DIM)
    el.dim_v(-hw, -hw, -PLATE_T, 0.0, ELEV_DIM_THICK, _fmt(PLATE_T), text_pos=0.5)
    el.dim_v(-hw, 0.0, 0.0, z_b, ELEV_DIM_B, f"{z_b:.1f}", base_u=-hw, text_pos=0.5)
    # callouts in the right-hand column
    def right_callout(target, text, y_text):
        tp = el.P(*target)
        return el.leader(target, text, RIGHT_TEXT_X - tp[0] - d.LEADER_SHOULDER - d.LEADER_TEXT_GAP, y_text - tp[1])
    right_callout((SPHERE_B_R, z_b), f"SPHERE B R{_fmt(SPHERE_B_R)} (PHANTOM)\nCENTER {z_b:.1f} ABOVE PLATE TOP", CALLOUT_Y["sphere_b"])
    right_callout((pk + br * math.cos(math.radians(BALL_LEADER_ANGLE)), BALL_CENTER_H + br * math.sin(math.radians(BALL_LEADER_ANGLE))),
                  f"BALL Ø{_fmt(BALL_D)}, GRADE 25 (52100), 3 OFF\nBONDED WITH ANAEROBIC\n"
                  f"RETAINING COMPOUND\nCENTER {_fmt(BALL_CENTER_H)} ABOVE PLATE TOP", CALLOUT_Y["ball"])
    right_callout((pk + POCKET_D / 2, -POCKET_DEPTH / 2),
                  f"POCKET Ø{_fmt(POCKET_D)} {TOL_POCKET} × {_fmt(POCKET_DEPTH)} DEEP", CALLOUT_Y["pocket"])

    # ---- labels, notes, title block ------------------------------------------------
    sh.text(PLAN_CENTER[0], PLAN_LABEL_Y, f"PLAN VIEW FROM TOP   SCALE {SCALE_TEXT}", size=d.FONT_LABEL,
            ha="center", weight="bold")
    sh.text(ELEV_LABEL[0], ELEV_LABEL[1], f"SECTION A-A   SCALE {SCALE_TEXT}", size=d.FONT_LABEL, weight="bold")
    notes = [
        f"Balls: Ø{_fmt(BALL_D)} grade 25 bearing balls (52100), 3 off, bonded into the pockets with anaerobic "
        f"retaining compound. Ball center is {_fmt(BALL_CENTER_H)} above the plate top.",
        f"Seating height of the sphere center above the plate top, z = {_fmt(BALL_CENTER_H)} + "
        f"√((R + {_fmt(br)})² − {_fmt(pr)}²): sphere B (R {_fmt(SPHERE_B_R)}) {z_b:.1f}. "
        f"The sphere is shown phantom.",
        f"Fasten with M8 socket cap screws into tapped holes in the cell table (4 × Ø{_fmt(BOLT_HOLE_D)} on a "
        f"{_fmt(BOLT_SQUARE)} × {_fmt(BOLT_SQUARE)} square).",
        f"Bolt down where the robot reaches with the wrist down and tilted {TILT_NOTE_ANGLE} degrees to either side.",
        "Section A-A passes through the plate center and the ball at 90°.",
    ]
    sh.notes_columns(NOTES_X, NOTES_TOP, NOTES_COLUMN_W, NOTES_COLUMN_GAP, notes, 2, size=NOTES_SIZE)
    sh.title_block(TitleInfo("SC1-06", "Three-ball nest base", "1", MATERIAL, FINISH, SCALE_TEXT))
    return sh.save(os.path.join(out_dir, "SC1-06_three_ball_nest_base.png"))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    issues = build(here)
    print("SC1-06 issues:", len(issues))
    for i in issues:
        print("   ", i)
