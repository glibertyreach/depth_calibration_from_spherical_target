"""
fig_mounting_detail.png -- section through the mounting of the calibration
sphere (sphere B, 152.4 mm diameter; decision D-15): robot flange, doweled
adapter plate SC1-02 with its centering spigot and central M20 thread, stem
SC1-04 with a turned shoulder seated on the adapter face, and the two
sphere-end options: the M20 thread cut into the turned aluminum sphere (the
chosen design) and, as the alternative for a steel or ceramic sphere, a bonded
blind hole. Dimensions follow drawings SC1-02 and SC1-04.

    python3 docs/procedures/figures/make_fig_mounting_detail.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon, Rectangle, Wedge

SPHERE_RADIUS_MM = 76.2
STEM_DIAMETER_MM = 30.0          # ground body, SC1-04
SHOULDER_DIAMETER_MM = 45.0      # 1.5 x stem diameter, SC1-04
SHOULDER_THICKNESS_MM = 10.0     # SC1-04
SPIGOT_THREAD = "M20 x 25"
SPIGOT_LENGTH_MM = 25.0
SPIGOT_DIAMETER_MM = 20.0
ADAPTER_THICKNESS_MM = 22.0      # adapter body, SC1-02
ADAPTER_DIAMETER_MM = 63.0       # SC1-02, the ISO 9409-1-50 flange diameter
CENTERING_SPIGOT_DIAMETER_MM = 31.5   # fits the flange's centering recess, SC1-02
CENTERING_SPIGOT_HEIGHT_MM = 5.0
FLANGE_THICKNESS_MM = 14.0
FLANGE_DIAMETER_MM = 63.0
DOWEL_DIAMETER_MM = 6.0
DOWEL_OFFSET_MM = 25.0           # on the 50 mm bolt circle
DOWEL_PROTRUSION_MM = 5.0        # into the flange's pin hole
STEM_STUB_LENGTH_MM = 70.0       # length of stem drawn in panel (a); the stem continues off the panel
STEM_STUB_IN_SPHERE_PANEL_MM = 60.0
TIP_THREAD = "M20 x 25"
TIP_LENGTH_MM = 25.0
TIP_DIAMETER_MM = 20.0
TAPPED_HOLE_DEPTH_MM = 30.0      # M20 x 30 in the sphere, SC1-04 detail H
SPOT_FACE_DIAMETER_MM = 32.0
SPOT_FACE_DEPTH_MM = 2.0         # below the pole, so the flat is complete
BONDED_HOLE_DIAMETER_MM = 16.0   # alternative tip for a steel or ceramic sphere B, SC1-04 note 9
BONDED_HOLE_DEPTH_MM = 46.0
# Label placement in panel (a), in mm of drawing space, so labels clear each other at this geometry.
LABEL_DOWEL_Y_MM = 50.0          # dowel label baseline, above the adapter
LABEL_SHOULDER_DX_MM = 22.0      # shoulder label start, right of the shoulder face
LABEL_SHOULDER_DY_MM = 12.0      # shoulder label bottom, above the stem
LABEL_BELOW_STEM_MM = 4.0        # gap between the stem and its label below it
LABEL_SPIGOT_Y_MM = -38.0        # spigot label top, below the adapter
LABEL_BOLT_Y_MM = -52.0          # bolt label top, below the spigot label
LABEL_BOLT_X_MM = -6.0           # bolt label center, under the flange joint, so its leader stays clear of the spigot's
LABEL_X_MM = 40.0                # left edge of the lower labels, right of the flange face
PANEL_A_TOP_MARGIN_MM = 42.0     # room above the adapter for the labels and the title
PANEL_A_BOTTOM_MARGIN_MM = 32.0  # room below the adapter for the lower labels
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
    # Centering spigot of the adapter, seated in the flange's centering recess.
    ax.add_patch(Rectangle((x0 - CENTERING_SPIGOT_HEIGHT_MM, -CENTERING_SPIGOT_DIAMETER_MM / 2), CENTERING_SPIGOT_HEIGHT_MM,
                           CENTERING_SPIGOT_DIAMETER_MM, facecolor=STEEL, edgecolor="black", hatch=HATCH))
    # Dowel pin crossing the flange/adapter joint, off-axis.
    ax.add_patch(Rectangle((x0 - DOWEL_PROTRUSION_MM, DOWEL_OFFSET_MM - DOWEL_DIAMETER_MM / 2),
                           DOWEL_PROTRUSION_MM + ADAPTER_THICKNESS_MM / 2, DOWEL_DIAMETER_MM, facecolor="white", edgecolor="black"))
    ax.annotate("dowel pin (locates the adapter)", (x0 - 1, DOWEL_OFFSET_MM), (x0 + LABEL_X_MM, LABEL_DOWEL_Y_MM),
                fontsize=7, color=DARK, va="bottom", arrowprops=dict(arrowstyle="-", color=DARK, lw=0.7))
    # Bolt (schematic) on the other side.
    ax.add_patch(Rectangle((x0 - 10, -DOWEL_OFFSET_MM - 3), 20, 6, facecolor="white", edgecolor="black"))
    ax.annotate("flange bolt (one of four)", (x0 - 6, -DOWEL_OFFSET_MM - 3), (x0 + LABEL_BOLT_X_MM, LABEL_BOLT_Y_MM),
                fontsize=7, color=DARK, va="top", ha="center", arrowprops=dict(arrowstyle="-", color=DARK, lw=0.7))
    # Tapped hole through the adapter with the spigot in it.
    ax.add_patch(Rectangle((x0 - CENTERING_SPIGOT_HEIGHT_MM, -SPIGOT_DIAMETER_MM / 2),
                           ADAPTER_THICKNESS_MM + CENTERING_SPIGOT_HEIGHT_MM, SPIGOT_DIAMETER_MM, facecolor="white",
                           edgecolor="black", ls="--"))
    spigot_x0 = x0 + ADAPTER_THICKNESS_MM - SPIGOT_LENGTH_MM
    ax.add_patch(Rectangle((spigot_x0, -SPIGOT_DIAMETER_MM / 2), SPIGOT_LENGTH_MM, SPIGOT_DIAMETER_MM, facecolor=DARK,
                           edgecolor="black"))
    # Shoulder seated on the adapter's outer face.
    shoulder_x0 = x0 + ADAPTER_THICKNESS_MM
    ax.add_patch(Rectangle((shoulder_x0, -SHOULDER_DIAMETER_MM / 2), SHOULDER_THICKNESS_MM, SHOULDER_DIAMETER_MM,
                           facecolor=DARK, edgecolor="black"))
    stem_x0 = shoulder_x0 + SHOULDER_THICKNESS_MM
    ax.add_patch(Rectangle((stem_x0, -STEM_DIAMETER_MM / 2), STEM_STUB_LENGTH_MM, STEM_DIAMETER_MM, facecolor=DARK,
                           edgecolor="black"))
    ax.plot([shoulder_x0, shoulder_x0], [-SHOULDER_DIAMETER_MM / 2 - 4, SHOULDER_DIAMETER_MM / 2 + 4], color=ACCENT, lw=2)
    ax.annotate("shoulder face seats here:\nsquare to the stem, sets it\nperpendicular to the adapter",
                (shoulder_x0, SHOULDER_DIAMETER_MM / 2),
                (stem_x0 + LABEL_SHOULDER_DX_MM, STEM_DIAMETER_MM / 2 + LABEL_SHOULDER_DY_MM),
                fontsize=7, color=ACCENT, va="bottom", arrowprops=dict(arrowstyle="-", color=ACCENT, lw=0.7))
    ax.annotate(f"threaded spigot {SPIGOT_THREAD}\nin the adapter's tapped hole", (x0 + ADAPTER_THICKNESS_MM / 2, -SPIGOT_DIAMETER_MM / 2),
                (x0 + LABEL_X_MM, LABEL_SPIGOT_Y_MM), fontsize=7, color=DARK, va="top",
                arrowprops=dict(arrowstyle="-", color=DARK, lw=0.7))
    ax.text(stem_x0 + STEM_STUB_LENGTH_MM / 2, -STEM_DIAMETER_MM / 2 - LABEL_BELOW_STEM_MM,
            f"stem, ground steel, {STEM_DIAMETER_MM:.0f} mm", fontsize=7, ha="center", va="top", color=DARK)
    ax.text(x0 - FLANGE_THICKNESS_MM - 2, 0.0, "robot\nflange", fontsize=7, ha="right", va="center")
    ax.text(x0 + ADAPTER_THICKNESS_MM / 2, ADAPTER_DIAMETER_MM / 2 + 4, "adapter plate", fontsize=7, ha="center")
    ax.set_xlim(x0 - FLANGE_THICKNESS_MM - 28, stem_x0 + STEM_STUB_LENGTH_MM + 50)
    ax.set_ylim(-ADAPTER_DIAMETER_MM / 2 - PANEL_A_BOTTOM_MARGIN_MM, ADAPTER_DIAMETER_MM / 2 + PANEL_A_TOP_MARGIN_MM)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("(a) flange, adapter and stem shoulder, in section", fontsize=9)


def draw_sphere_end(ax, tapped: bool):
    """The stem tip in sphere B, in section: the M20 thread cut into the turned
    aluminum sphere (tapped=True, the chosen design) or the bonded blind hole
    used if sphere B is steel or ceramic instead (tapped=False)."""
    cx = 0.0
    ax.add_patch(Circle((cx, 0.0), SPHERE_RADIUS_MM, facecolor=CERAMIC if tapped else STEEL, edgecolor="black", lw=1.2,
                        hatch=HATCH))
    pole_x = cx - SPHERE_RADIUS_MM
    if tapped:
        # Spot face at the pole: the stem's body end seats on it; the tip threads into the tapped hole.
        face_x = pole_x + SPOT_FACE_DEPTH_MM
        ax.add_patch(Rectangle((pole_x - 1, -SPOT_FACE_DIAMETER_MM / 2), SPOT_FACE_DEPTH_MM + 1, SPOT_FACE_DIAMETER_MM,
                               facecolor="white", edgecolor="none"))
        ax.plot([face_x, face_x], [-SPOT_FACE_DIAMETER_MM / 2, SPOT_FACE_DIAMETER_MM / 2], color="black", lw=1.0)
        ax.add_patch(Rectangle((face_x, -TIP_DIAMETER_MM / 2 - 1.5), TAPPED_HOLE_DEPTH_MM, TIP_DIAMETER_MM + 3,
                               facecolor="white", edgecolor="black"))
        ax.add_patch(Rectangle((face_x, -TIP_DIAMETER_MM / 2), TIP_LENGTH_MM, TIP_DIAMETER_MM, facecolor=DARK,
                               edgecolor="black"))
        stem_end_x = face_x
        note = (f"M20 x {TAPPED_HOLE_DEPTH_MM:.0f} tapped hole and \u00d8{SPOT_FACE_DIAMETER_MM:.0f} spot face cut when the sphere is turned;\n"
                f"stem tip {TIP_THREAD} threads in, body end seats on the spot face")
        title = "(b) aluminum sphere B: thread cut at the pole"
    else:
        ax.add_patch(Rectangle((pole_x, -BONDED_HOLE_DIAMETER_MM / 2 - 1.5), BONDED_HOLE_DEPTH_MM,
                               BONDED_HOLE_DIAMETER_MM + 3, facecolor="white", edgecolor="black"))
        ax.add_patch(Rectangle((pole_x, -BONDED_HOLE_DIAMETER_MM / 2), BONDED_HOLE_DEPTH_MM, BONDED_HOLE_DIAMETER_MM,
                               facecolor=DARK, edgecolor="black"))
        stem_end_x = pole_x
        note = (f"alternative for a steel or ceramic sphere: blind hole \u00d8{BONDED_HOLE_DIAMETER_MM:.0f} H7 x "
                f"{BONDED_HOLE_DEPTH_MM:.0f},\nlight press fit, anaerobic retaining compound; no welding or brazing")
        title = "(c) alternative: bonded blind hole"
    ax.add_patch(Rectangle((stem_end_x - STEM_STUB_IN_SPHERE_PANEL_MM, -STEM_DIAMETER_MM / 2), STEM_STUB_IN_SPHERE_PANEL_MM,
                           STEM_DIAMETER_MM, facecolor=DARK, edgecolor="black"))
    ax.text(cx, -SPHERE_RADIUS_MM - 8, note, fontsize=7, ha="center", va="top")
    ax.plot([cx], [0.0], marker="+", color=ACCENT, markersize=12, mew=2)
    ax.annotate("center = TCP", (cx, 0.0), (cx, SPHERE_RADIUS_MM + 6), fontsize=7, color=ACCENT,
                ha="center", arrowprops=dict(arrowstyle="-", color=ACCENT, lw=0.7))
    ax.set_xlim(pole_x - STEM_STUB_IN_SPHERE_PANEL_MM - 5, cx + SPHERE_RADIUS_MM + 10)
    ax.set_ylim(-SPHERE_RADIUS_MM - 34, SPHERE_RADIUS_MM + 16)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=9)


def main() -> None:
    fig, axes = plt.subplots(1, 3, figsize=FIGURE_SIZE_IN, dpi=OUTPUT_DPI, gridspec_kw={"width_ratios": [1.4, 1, 1]})
    draw_joint(axes[0])
    draw_sphere_end(axes[1], tapped=True)
    draw_sphere_end(axes[2], tapped=False)
    fig.tight_layout()
    out = Path(__file__).with_name("fig_mounting_detail.png")
    fig.savefig(out, facecolor="white")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
