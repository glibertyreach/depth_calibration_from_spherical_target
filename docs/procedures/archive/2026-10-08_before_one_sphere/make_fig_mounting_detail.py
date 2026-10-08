"""
fig_mounting_detail.png -- section through the suggested sphere mounting for
sphere A (76.2 mm diameter): robot flange, doweled adapter plate with a central
tapped hole, stem with a turned shoulder seated on the adapter face, and the
two sphere-end options (threaded insert of a ceramic sphere; bonded blind hole
in a steel sphere). Dimensions are the procedure's suggestions, named below.

    python3 docs/procedures/figures/make_fig_mounting_detail.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, Rectangle, Wedge

SPHERE_RADIUS_MM = 38.1
STEM_DIAMETER_MM = 16.0
STEM_LENGTH_MM = 130.0           # adapter face to sphere surface
SHOULDER_DIAMETER_MM = 26.0      # at least 1.5 x stem diameter
SHOULDER_THICKNESS_MM = 6.0
SPIGOT_THREAD = "M12 x 15"
SPIGOT_LENGTH_MM = 15.0
SPIGOT_DIAMETER_MM = 12.0
ADAPTER_THICKNESS_MM = 12.0
ADAPTER_DIAMETER_MM = 80.0
FLANGE_THICKNESS_MM = 14.0
FLANGE_DIAMETER_MM = 63.0
DOWEL_DIAMETER_MM = 6.0
DOWEL_OFFSET_MM = 25.0           # on the 50 mm bolt circle
INSERT_THREAD = "M8"
INSERT_DEPTH_MM = 14.0
BLIND_HOLE_FRACTION = 0.6        # depth of the bonded hole as a fraction of R
TIP_DIAMETER_MM = 8.0
OUTPUT_DPI = 200
FIGURE_SIZE_IN = (12.5, 4.8)
STEEL = "#8c8c8c"
DARK = "#444444"
CERAMIC = "#e8e8e8"
HATCH = "////"
ACCENT = "#b03030"
BLUE = "#1f5fa8"


def draw_joint(ax):
    """Flange, adapter and stem shoulder, in section (axis horizontal)."""
    x0 = 0.0
    ax.add_patch(Rectangle((x0 - FLANGE_THICKNESS_MM, -FLANGE_DIAMETER_MM / 2), FLANGE_THICKNESS_MM, FLANGE_DIAMETER_MM,
                           facecolor=DARK, edgecolor="black"))
    ax.add_patch(Rectangle((x0, -ADAPTER_DIAMETER_MM / 2), ADAPTER_THICKNESS_MM, ADAPTER_DIAMETER_MM, facecolor=STEEL,
                           edgecolor="black", hatch=HATCH))
    # Dowel pin crossing the flange/adapter joint, off-axis.
    ax.add_patch(Rectangle((x0 - 8, DOWEL_OFFSET_MM - DOWEL_DIAMETER_MM / 2), 14, DOWEL_DIAMETER_MM, facecolor="white",
                           edgecolor="black"))
    ax.annotate("dowel pin (locates the adapter)", (x0 - 1, DOWEL_OFFSET_MM), (x0 + 40, DOWEL_OFFSET_MM + 24),
                fontsize=7, color=DARK, arrowprops=dict(arrowstyle="-", color=DARK, lw=0.7))
    # Bolt (schematic) on the other side.
    ax.add_patch(Rectangle((x0 - 10, -DOWEL_OFFSET_MM - 3), 20, 6, facecolor="white", edgecolor="black"))
    ax.annotate("flange bolt (one of four)", (x0 + 10, -DOWEL_OFFSET_MM), (x0 + 50, -DOWEL_OFFSET_MM - 20),
                fontsize=7, color=DARK, arrowprops=dict(arrowstyle="-", color=DARK, lw=0.7))
    # Tapped hole through the adapter with the spigot in it.
    ax.add_patch(Rectangle((x0, -SPIGOT_DIAMETER_MM / 2), ADAPTER_THICKNESS_MM, SPIGOT_DIAMETER_MM, facecolor="white",
                           edgecolor="black", ls="--"))
    spigot_x0 = x0 + ADAPTER_THICKNESS_MM - SPIGOT_LENGTH_MM
    ax.add_patch(Rectangle((spigot_x0, -SPIGOT_DIAMETER_MM / 2), SPIGOT_LENGTH_MM, SPIGOT_DIAMETER_MM, facecolor=DARK,
                           edgecolor="black"))
    # Shoulder seated on the adapter's outer face.
    shoulder_x0 = x0 + ADAPTER_THICKNESS_MM
    ax.add_patch(Rectangle((shoulder_x0, -SHOULDER_DIAMETER_MM / 2), SHOULDER_THICKNESS_MM, SHOULDER_DIAMETER_MM,
                           facecolor=DARK, edgecolor="black"))
    stem_x0 = shoulder_x0 + SHOULDER_THICKNESS_MM
    ax.add_patch(Rectangle((stem_x0, -STEM_DIAMETER_MM / 2), 60, STEM_DIAMETER_MM, facecolor=DARK, edgecolor="black"))
    ax.plot([shoulder_x0, shoulder_x0], [-SHOULDER_DIAMETER_MM / 2 - 4, SHOULDER_DIAMETER_MM / 2 + 4], color=ACCENT, lw=2)
    ax.annotate("shoulder face seats here:\nsquare to the stem, sets it\nperpendicular to the adapter",
                (shoulder_x0, SHOULDER_DIAMETER_MM / 2), (shoulder_x0 + 40, SHOULDER_DIAMETER_MM / 2 + 10),
                fontsize=7, color=ACCENT, arrowprops=dict(arrowstyle="-", color=ACCENT, lw=0.7))
    ax.annotate(f"threaded spigot {SPIGOT_THREAD}\nin the adapter's tapped hole", (x0 + ADAPTER_THICKNESS_MM / 2, -SPIGOT_DIAMETER_MM / 2),
                (x0 + 45, -SHOULDER_DIAMETER_MM / 2 - 24), fontsize=7, color=DARK,
                arrowprops=dict(arrowstyle="-", color=DARK, lw=0.7))
    ax.text(stem_x0 + 32, STEM_DIAMETER_MM / 2 + 5, f"stem, ground steel, {STEM_DIAMETER_MM:.0f} mm", fontsize=7,
            ha="center", va="bottom", color=DARK)
    ax.text(x0 - FLANGE_THICKNESS_MM - 2, 0.0, "robot\nflange", fontsize=7, ha="right", va="center")
    ax.text(x0 + ADAPTER_THICKNESS_MM / 2, ADAPTER_DIAMETER_MM / 2 + 4, "adapter plate", fontsize=7, ha="center")
    ax.set_xlim(x0 - FLANGE_THICKNESS_MM - 28, stem_x0 + 110)
    ax.set_ylim(-ADAPTER_DIAMETER_MM / 2 - 20, ADAPTER_DIAMETER_MM / 2 + 14)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("(a) flange, adapter and stem shoulder, in section", fontsize=9)


def draw_sphere_end(ax, ceramic: bool):
    """The stem tip in the sphere: threaded insert (ceramic) or bonded blind hole (steel)."""
    cx = 0.0
    face = CERAMIC if ceramic else STEEL
    ax.add_patch(Circle((cx, 0.0), SPHERE_RADIUS_MM, facecolor=face, edgecolor="black", lw=1.2, hatch=None if ceramic else HATCH))
    # Stem comes from the left.
    stem_x1 = cx - SPHERE_RADIUS_MM
    ax.add_patch(Rectangle((stem_x1 - 50, -STEM_DIAMETER_MM / 2), 50, STEM_DIAMETER_MM, facecolor=DARK, edgecolor="black"))
    if ceramic:
        # A flat spot with a bonded insert; the stem's tip threads into it.
        ax.add_patch(Rectangle((stem_x1 - 2, -7), INSERT_DEPTH_MM + 2, 14, facecolor="white", edgecolor="black"))
        ax.add_patch(Rectangle((stem_x1 - 2, -TIP_DIAMETER_MM / 2), INSERT_DEPTH_MM + 2, TIP_DIAMETER_MM, facecolor=DARK,
                               edgecolor="black"))
        ax.text(cx, -SPHERE_RADIUS_MM - 8, f"maker's threaded insert {INSERT_THREAD}; stem tip threaded to match,\n"
                "small shoulder seats on the flat; drop of thread locker", fontsize=7, ha="center", va="top")
        title = "(b) ceramic sphere: threaded insert"
    else:
        depth = BLIND_HOLE_FRACTION * SPHERE_RADIUS_MM
        ax.add_patch(Rectangle((stem_x1, -TIP_DIAMETER_MM / 2 - 1.5), depth, TIP_DIAMETER_MM + 3, facecolor="white",
                               edgecolor="black"))
        ax.add_patch(Rectangle((stem_x1, -TIP_DIAMETER_MM / 2), depth, TIP_DIAMETER_MM, facecolor=DARK, edgecolor="black"))
        ax.text(cx, -SPHERE_RADIUS_MM - 8, f"reamed blind hole, depth {BLIND_HOLE_FRACTION:.1f} R, light press fit,\n"
                "anaerobic retaining compound; no welding or brazing", fontsize=7, ha="center", va="top")
        title = "(c) steel sphere: bonded blind hole"
    ax.plot([cx], [0.0], marker="+", color=ACCENT, markersize=12, mew=2)
    ax.annotate("center = TCP", (cx, 0.0), (cx, SPHERE_RADIUS_MM + 6), fontsize=7, color=ACCENT,
                ha="center", arrowprops=dict(arrowstyle="-", color=ACCENT, lw=0.7))
    ax.set_xlim(stem_x1 - 55, cx + SPHERE_RADIUS_MM + 10)
    ax.set_ylim(-SPHERE_RADIUS_MM - 30, SPHERE_RADIUS_MM + 16)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=9)


def main() -> None:
    fig, axes = plt.subplots(1, 3, figsize=FIGURE_SIZE_IN, dpi=OUTPUT_DPI, gridspec_kw={"width_ratios": [1.4, 1, 1]})
    draw_joint(axes[0])
    draw_sphere_end(axes[1], ceramic=True)
    draw_sphere_end(axes[2], ceramic=False)
    fig.tight_layout()
    out = Path(__file__).with_name("fig_mounting_detail.png")
    fig.savefig(out, facecolor="white")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
