"""
fig_sphere_radius_choice.png -- the constraints that bound the radius of the
calibration sphere.

Panel (a): the depth bias that 4 x 4 cell averaging produces on a sphere at the
incidence cut-off, divided by the temporal depth noise of one cell. With the
indicative laws (cell footprint proportional to z, noise proportional to z^2)
the ratio depends on the radius alone, not on the distance: bias / noise =
footprint_per_mm^2 * (sec^3 a + sec a) / (24 k R). This gives a LOWER bound on
R for a chosen cut-off and a chosen tolerated ratio.

Panel (b): bounds on R versus standoff. Lower bound from curvature (panel a, at
ratio 1/2); lower bound from sampling (the sphere's visible disk must span a
minimum number of effective cells so that the slope dimensions are resolved);
upper bound from the field of view (the sphere's image must leave room for
several distinct lateral positions across the short axis of the field). The
feasible region is shaded.

    python3 docs/analysis/figures/make_fig_sphere_radius_choice.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---- Indicative sensor constants (specification, section 3.1) ---------------
FOCAL_LENGTH_PX = 688.16
EFFECTIVE_CELL_PX = 4.0
NOISE_COEFFICIENT_PER_MM = 1.79e-7     # per 4 x 4 block
FOV_SHORT_AXIS_DEG = 38.5

# ---- Design parameters ---------------------------------------------------------
CUTOFF_CANDIDATES_DEG = (45.0, 55.0, 60.0, 65.0)
TOLERATED_BIAS_TO_NOISE = 0.5          # curvature bias allowed at the cut-off, as a fraction of sigma_z
DESIGN_CUTOFF_DEG = 60.0
RELAXED_CUTOFF_DEG = 55.0              # the recommended design: cut-off near the reported no-read onset
RELAXED_BIAS_TO_NOISE = 1.0            # and curvature bias tolerated up to one sigma_z, to be removed via two radii
MIN_CELLS_ACROSS_VISIBLE_RADIUS = 12   # so that incidence from 0 to the cut-off is sampled at ~5 deg steps
POSITIONS_ACROSS_SHORT_AXIS = 3        # distinct, non-overlapping lateral placements the sphere image must allow
STANDOFF_RANGE_MM = (300.0, 1100.0)
RADIUS_RANGE_MM = (10.0, 300.0)

OUTPUT_DPI = 200
FIGURE_SIZE_IN = (11.0, 4.2)


def footprint_per_mm_of_standoff() -> float:
    return EFFECTIVE_CELL_PX / FOCAL_LENGTH_PX


def bias_to_noise_ratio(radius_mm: np.ndarray, cutoff_deg: float) -> np.ndarray:
    a = np.radians(cutoff_deg)
    geometric = 1.0 / np.cos(a) ** 3 + 1.0 / np.cos(a)
    return footprint_per_mm_of_standoff() ** 2 * geometric / (24.0 * NOISE_COEFFICIENT_PER_MM * radius_mm)


def radius_lower_bound_curvature(cutoff_deg: float, ratio: float) -> float:
    a = np.radians(cutoff_deg)
    geometric = 1.0 / np.cos(a) ** 3 + 1.0 / np.cos(a)
    return footprint_per_mm_of_standoff() ** 2 * geometric / (24.0 * NOISE_COEFFICIENT_PER_MM * ratio)


def radius_lower_bound_sampling(standoff_mm: np.ndarray, cutoff_deg: float) -> np.ndarray:
    footprint = standoff_mm * footprint_per_mm_of_standoff()
    return MIN_CELLS_ACROSS_VISIBLE_RADIUS * footprint / np.sin(np.radians(cutoff_deg))


def radius_upper_bound_fov(standoff_mm: np.ndarray) -> np.ndarray:
    short_axis_width = 2.0 * standoff_mm * np.tan(np.radians(FOV_SHORT_AXIS_DEG / 2.0))
    return short_axis_width / (2.0 * POSITIONS_ACROSS_SHORT_AXIS)


def main() -> None:
    fig, axes = plt.subplots(1, 2, figsize=FIGURE_SIZE_IN, dpi=OUTPUT_DPI)
    radius = np.linspace(*RADIUS_RANGE_MM, 400)

    ax = axes[0]
    for cutoff, color in zip(CUTOFF_CANDIDATES_DEG, ("#999999", "#1f5fa8", "#d9731a", "#b03030")):
        ax.plot(radius, bias_to_noise_ratio(radius, cutoff), color=color, label=f"cut-off {cutoff:.0f} deg")
    ax.axhline(TOLERATED_BIAS_TO_NOISE, color="#555555", lw=1, ls="-.")
    ax.text(RADIUS_RANGE_MM[1] - 5, TOLERATED_BIAS_TO_NOISE * 1.1, "tolerated ratio", fontsize=7, ha="right", color="#555555")
    ax.set_yscale("log")
    ax.set_xlabel("sphere radius R (mm)", fontsize=8)
    ax.set_ylabel("cell-averaging bias at cut-off / sigma_z", fontsize=8)
    ax.set_title("(a) curvature bias relative to noise\n(independent of standoff under the indicative laws)", fontsize=9)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=7)

    ax = axes[1]
    standoff = np.linspace(*STANDOFF_RANGE_MM, 300)
    lower_curv_strict = radius_lower_bound_curvature(DESIGN_CUTOFF_DEG, TOLERATED_BIAS_TO_NOISE)
    lower_curv_relaxed = radius_lower_bound_curvature(RELAXED_CUTOFF_DEG, RELAXED_BIAS_TO_NOISE)
    lower_samp = radius_lower_bound_sampling(standoff, RELAXED_CUTOFF_DEG)
    upper_fov = radius_upper_bound_fov(standoff)
    lower = np.maximum(lower_curv_relaxed, lower_samp)
    ax.plot(standoff, upper_fov, color="#b03030", label=f"upper: {POSITIONS_ACROSS_SHORT_AXIS} placements across the short axis")
    ax.axhline(lower_curv_strict, color="#1f5fa8", ls="--",
               label=f"lower, strict: bias <= {TOLERATED_BIAS_TO_NOISE:.1f} sigma_z at {DESIGN_CUTOFF_DEG:.0f} deg")
    ax.axhline(lower_curv_relaxed, color="#1f5fa8",
               label=f"lower, relaxed: bias <= {RELAXED_BIAS_TO_NOISE:.0f} sigma_z at {RELAXED_CUTOFF_DEG:.0f} deg")
    ax.plot(standoff, lower_samp, color="#d9731a", label=f"lower: {MIN_CELLS_ACROSS_VISIBLE_RADIUS} cells across the visible radius")
    feasible = upper_fov > lower
    ax.fill_between(standoff, lower, upper_fov, where=feasible, color="#e3f1dc", label="feasible under the relaxed bound")
    ax.set_xlabel("standoff z (mm)", fontsize=8)
    ax.set_ylabel("sphere radius R (mm)", fontsize=8)
    ax.set_ylim(0, 200)
    ax.set_title("(b) radius bounds versus standoff", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=6, loc="upper left")
    for a in axes:
        a.tick_params(labelsize=7)
    fig.tight_layout()
    out = Path(__file__).with_name("fig_sphere_radius_choice.png")
    fig.savefig(out, facecolor="white")
    for cutoff in CUTOFF_CANDIDATES_DEG:
        for ratio in (1.0, 0.5, 0.25):
            print(f"cut-off {cutoff:.0f} deg, ratio {ratio}: R >= {radius_lower_bound_curvature(cutoff, ratio):.0f} mm")
    for z in (310.0, 500.0, 700.0, 1000.0):
        print(f"z={z:.0f}: sampling lower bound {radius_lower_bound_sampling(np.array(z), DESIGN_CUTOFF_DEG):.0f} mm, "
              f"FOV upper bound {radius_upper_bound_fov(np.array(z)):.0f} mm")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
