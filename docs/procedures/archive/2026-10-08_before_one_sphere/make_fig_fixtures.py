"""
fig_fixtures.png -- the three fixtures of the stage-1 capture procedure, drawn
to scale for sphere A (radius 38.1 mm):

 (a) the sphere on its stem, seen from the side, with the sensor's viewing
     direction: the stem points away from the sensor so that the sphere hides
     it, and the tool center point is the sphere's center;
 (b) the three-ball nest used to find the tool center point: the sphere seats
     on three fixed balls, so its center is at the same point in space whatever
     the robot's wrist orientation, which is what the robot's multi-orientation
     TCP routine solves for;
 (c) the board on its adapter plate, with the dial indicator sweep that checks
     the board face is perpendicular to the flange axis.

All dimensions are named constants and are suggestions, not requirements.

    python3 docs/procedures/figures/make_fig_fixtures.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Rectangle

SPHERE_RADIUS_MM = 38.1
STEM_LENGTH_MM = 130.0          # flange face to sphere surface
STEM_DIAMETER_MM = 16.0
ADAPTER_THICKNESS_MM = 12.0
ADAPTER_WIDTH_MM = 80.0
FLANGE_WIDTH_MM = 63.0          # a common ISO 9409 flange pattern size
NEST_BALL_RADIUS_MM = 12.0
NEST_BASE_WIDTH_MM = 110.0
BOARD_THICKNESS_MM = 6.0
BOARD_WIDTH_MM = 200.0
BOARD_ADAPTER_THICKNESS_MM = 20.0
OUTPUT_DPI = 200
FIGURE_SIZE_IN = (13.0, 4.6)
STEEL = "#8c8c8c"
DARK = "#444444"
SPHERE_COLOR = "#dcdcdc"
ACCENT = "#b03030"
BLUE = "#1f5fa8"


def draw_sphere_mount(ax):
    # Flange and adapter at the left, stem to the right, sphere at the end.
    flange_x = 0.0
    ax.add_patch(Rectangle((flange_x - 14, -FLANGE_WIDTH_MM / 2), 14, FLANGE_WIDTH_MM, color=DARK))
    ax.add_patch(Rectangle((flange_x, -ADAPTER_WIDTH_MM / 2), ADAPTER_THICKNESS_MM, ADAPTER_WIDTH_MM, color=STEEL))
    stem_x0 = flange_x + ADAPTER_THICKNESS_MM
    ax.add_patch(Rectangle((stem_x0, -STEM_DIAMETER_MM / 2), STEM_LENGTH_MM, STEM_DIAMETER_MM, color=DARK))
    center_x = stem_x0 + STEM_LENGTH_MM + SPHERE_RADIUS_MM
    ax.add_patch(Circle((center_x, 0.0), SPHERE_RADIUS_MM, facecolor=SPHERE_COLOR, edgecolor=DARK, lw=1.2))
    ax.plot([center_x], [0.0], marker="+", color=ACCENT, markersize=14, mew=2)
    ax.annotate("tool center point\n= sphere center", (center_x, 0.0), (center_x + 30, -SPHERE_RADIUS_MM - 48),
                ha="center", fontsize=8, color=ACCENT, arrowprops=dict(arrowstyle="-", color=ACCENT, lw=0.8))
    # Sensor far to the right, looking left along the stem axis.
    sensor_x = center_x + SPHERE_RADIUS_MM + 95
    ax.add_patch(Rectangle((sensor_x, -22), 28, 44, color=BLUE))
    ax.text(sensor_x + 14, 30, "sensor", ha="center", fontsize=8, color=BLUE)
    ax.add_patch(FancyArrowPatch((sensor_x, 0), (center_x + SPHERE_RADIUS_MM + 6, 0), arrowstyle="->", color=BLUE,
                                 mutation_scale=14, lw=1.2))
    ax.text((sensor_x + center_x) / 2 + 20, 8, "viewing direction", fontsize=7, color=BLUE, ha="center")
    ax.text(center_x - 10, SPHERE_RADIUS_MM + 12, "stem hidden behind\nthe sphere", fontsize=7, ha="center", color=DARK)
    # Dimension lines.
    y_dim = -ADAPTER_WIDTH_MM / 2 - 30
    ax.annotate("", (stem_x0, y_dim), (stem_x0 + STEM_LENGTH_MM, y_dim), arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text(stem_x0 + STEM_LENGTH_MM / 2, y_dim - 10, f"stem {STEM_LENGTH_MM:.0f} mm (at least 2R + 50)",
            ha="center", fontsize=7)
    ax.annotate("", (center_x, 0), (center_x, SPHERE_RADIUS_MM), arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text(center_x + 6, SPHERE_RADIUS_MM / 2, f"R = {SPHERE_RADIUS_MM:.1f}", fontsize=7)
    ax.text(flange_x - 7, -FLANGE_WIDTH_MM / 2 - 8, "robot flange", fontsize=7, ha="center", va="top", color=DARK)
    ax.text(flange_x + ADAPTER_THICKNESS_MM / 2 + 10, ADAPTER_WIDTH_MM / 2 + 6, "adapter (doweled)", fontsize=6.5,
            ha="left", va="bottom", color=DARK)
    ax.set_xlim(-40, sensor_x + 45)
    ax.set_ylim(-130, 80)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("(a) sphere on its stem, side view", fontsize=9)


def draw_nest(ax):
    # Side view: two of the three nest balls visible, sphere seated on them.
    base_y = 0.0
    ax.add_patch(Rectangle((-NEST_BASE_WIDTH_MM / 2, base_y - 14), NEST_BASE_WIDTH_MM, 14, color=STEEL))
    ball_dx = SPHERE_RADIUS_MM * 0.75
    for x in (-ball_dx, ball_dx):
        ax.add_patch(Circle((x, base_y + NEST_BALL_RADIUS_MM), NEST_BALL_RADIUS_MM, facecolor="#bbbbbb", edgecolor=DARK))
    # Sphere center height: distance between ball centers and sphere center is R + r.
    contact = SPHERE_RADIUS_MM + NEST_BALL_RADIUS_MM
    center_y = base_y + NEST_BALL_RADIUS_MM + (contact ** 2 - ball_dx ** 2) ** 0.5
    ax.add_patch(Circle((0.0, center_y), SPHERE_RADIUS_MM, facecolor=SPHERE_COLOR, edgecolor=DARK, lw=1.2))
    ax.plot([0.0], [center_y], marker="+", color=ACCENT, markersize=14, mew=2)
    # Stems in several orientations (the robot re-seats the sphere from different wrist angles).
    for angle_deg, label in ((90, "pose 1"), (55, "pose 2"), (125, "pose 3"), (35, "pose 4")):
        import math
        a = math.radians(angle_deg)
        x0 = SPHERE_RADIUS_MM * math.cos(a)
        y0 = center_y + SPHERE_RADIUS_MM * math.sin(a)
        x1 = (SPHERE_RADIUS_MM + 70) * math.cos(a)
        y1 = center_y + (SPHERE_RADIUS_MM + 70) * math.sin(a)
        ax.plot([x0, x1], [y0, y1], color=DARK, lw=2.5, alpha=0.55)
        ax.text(x1 * 1.08, y1 + 4, label, fontsize=6.5, ha="center", color=DARK)
    ax.text(0, base_y - 24, "three-ball nest (two balls visible), bolted down", fontsize=7, ha="center")
    ax.text(0, center_y + SPHERE_RADIUS_MM + 90, "the center stays put while the wrist turns:\n"
            "the robot's TCP routine solves for that point", fontsize=7.5, ha="center", color=ACCENT)
    ax.set_xlim(-110, 110)
    ax.set_ylim(-40, center_y + SPHERE_RADIUS_MM + 110)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("(b) finding the tool center point", fontsize=9)


def draw_board(ax):
    # Side view: flange at left, adapter, board face at right; dial indicator sweeps the face.
    flange_x = 0.0
    ax.add_patch(Rectangle((flange_x - 14, -FLANGE_WIDTH_MM / 2), 14, FLANGE_WIDTH_MM, color=DARK))
    ax.add_patch(Rectangle((flange_x, -ADAPTER_WIDTH_MM / 2), BOARD_ADAPTER_THICKNESS_MM, ADAPTER_WIDTH_MM, color=STEEL))
    board_x = flange_x + BOARD_ADAPTER_THICKNESS_MM
    ax.add_patch(Rectangle((board_x, -BOARD_WIDTH_MM / 2), BOARD_THICKNESS_MM, BOARD_WIDTH_MM, facecolor=SPHERE_COLOR,
                           edgecolor=DARK, lw=1.2))
    face_x = board_x + BOARD_THICKNESS_MM
    ax.plot([face_x, face_x], [-BOARD_WIDTH_MM / 2, BOARD_WIDTH_MM / 2], color=ACCENT, lw=2)
    ax.text(face_x + 6, 0, "matte front face:\nboard frame origin at its center,\nz = outward normal (toward the sensor)",
            fontsize=7, va="center", color=ACCENT)
    # Dial indicator fixed in space, touching the face; the flange rotates about its axis.
    ind_y = BOARD_WIDTH_MM / 2 - 25
    ax.add_patch(Rectangle((face_x + 2, ind_y - 3), 30, 6, color=BLUE))
    ax.add_patch(Circle((face_x + 44, ind_y), 12, facecolor="white", edgecolor=BLUE, lw=1.5))
    ax.text(face_x + 44, ind_y + 18, "dial indicator, fixed", fontsize=7, ha="center", color=BLUE)
    ax.add_patch(FancyArrowPatch((flange_x - 30, -FLANGE_WIDTH_MM / 2 - 10), (flange_x - 30, -FLANGE_WIDTH_MM / 2 - 40),
                                 arrowstyle="<->", color=DARK, mutation_scale=10, lw=0.8))
    ax.text(flange_x - 30, -FLANGE_WIDTH_MM / 2 - 50, "rotate the flange\nabout its axis:\nreading must stay\nwithin 0.05 mm",
            fontsize=6.5, ha="center", va="top", color=DARK)
    ax.annotate("", (flange_x, BOARD_WIDTH_MM / 2 + 14), (face_x, BOARD_WIDTH_MM / 2 + 14),
                arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text((flange_x + face_x) / 2, BOARD_WIDTH_MM / 2 + 20, "flange face to board face: measure, record", fontsize=7,
            ha="center")
    ax.set_xlim(-75, face_x + 150)
    ax.set_ylim(-BOARD_WIDTH_MM / 2 - 95, BOARD_WIDTH_MM / 2 + 40)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("(c) board on its adapter, runout check", fontsize=9)


def main() -> None:
    fig, axes = plt.subplots(1, 3, figsize=FIGURE_SIZE_IN, dpi=OUTPUT_DPI)
    draw_sphere_mount(axes[0])
    draw_nest(axes[1])
    draw_board(axes[2])
    fig.tight_layout()
    out = Path(__file__).with_name("fig_fixtures.png")
    fig.savefig(out, facecolor="white")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
