"""
fig_sphere_view_effects.png -- what one view of a calibration sphere gives the
calibration, as a function of the incidence angle alpha between the sphere's
surface normal and the line of sight.

Three panels:
 (a) The depth bias that 4 x 4 cell averaging alone introduces on a sphere,
     because the sphere's depth is convex within a cell. This bias exists even
     for a perfect sensor; it depends on the sphere radius and on the cell
     footprint, and it is NOT a slope effect that transfers to planar parts.
 (b) The two factors that degrade a sample as a constraint on the range
     correction: the noise multiplier sec^m(alpha) (sensor model, m = 1.3) and
     the geometric leverage sec(alpha) with which a center-position error
     enters the range residual. Their product is the effective noise of one
     sample's range-correction estimate relative to a face-on sample.
 (c) Number of effective 4 x 4 depth cells one sphere view contributes below
     the incidence cut-off, versus standoff, for three sphere radii.

All sensor constants are taken from the XSearch+1UN/2UN specification Draft 0.9,
section 3.1 (VSX3000 unit VSm01).

    python3 docs/analysis/figures/make_fig_sphere_view_effects.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---- Sensor constants (specification, section 3.1) -------------------------
FOCAL_LENGTH_PX = 688.16            # fx, pixels
EFFECTIVE_CELL_PX = 4.0             # side of one effective depth cell, native pixels
NOISE_COEFFICIENT_PER_MM = 1.79e-7  # k in sigma_z = k z^2, per 4 x 4 block, 1/mm
INCIDENCE_NOISE_EXPONENT = 1.3      # m in sec^m(alpha)
NO_READ_BASELINE_SLOPE_DEG = 67.5   # no depth read beyond this slope along the baseline
NO_READ_INCIDENCE_DEG = 80.0        # no depth read beyond this incidence (signal loss)

# ---- Calibration design choices used for illustration ----------------------
SPHERE_RADII_MM = (25.0, 50.0, 100.0)
STANDOFFS_MM = (310.0, 500.0, 1000.0)
INCIDENCE_CUTOFF_DEG = 65.0         # samples beyond this are discarded by the calibration
INCIDENCE_MAX_PLOT_DEG = 80.0
STANDOFF_RANGE_MM = (300.0, 1100.0)

# ---- Figure constants ---------------------------------------------------------
OUTPUT_DPI = 200
FIGURE_SIZE_IN = (13.0, 4.2)
LINE_STYLES = ("-", "--", ":")


def cell_footprint_mm(standoff_mm: float) -> float:
    """Lateral size, on a face-on surface at the given depth, of one effective cell."""
    return standoff_mm * EFFECTIVE_CELL_PX / FOCAL_LENGTH_PX


def cell_averaging_depth_bias_mm(alpha_rad: np.ndarray, radius_mm: float, standoff_mm: float) -> np.ndarray:
    """Mean depth over a square cell minus the depth at the cell center, on a sphere.

    For a sphere seen along z, the depth of the near surface as a function of the
    lateral offset rho from the center ray is z(rho) = z_c - sqrt(R^2 - rho^2), whose
    second derivative along rho is 1/(R cos^3 alpha) with sin alpha = rho / R.
    Averaging a quadratic over a square of side b gives the center value plus
    (second derivative) * b^2 / 24 along each of the two axes; along the
    tangential axis the second derivative is 1/(R cos alpha). The cell side b is
    the footprint of one effective cell projected onto the face-on plane.
    """
    footprint = cell_footprint_mm(standoff_mm)
    curvature_radial = 1.0 / (radius_mm * np.cos(alpha_rad) ** 3)
    curvature_tangential = 1.0 / (radius_mm * np.cos(alpha_rad))
    return footprint ** 2 / 24.0 * (curvature_radial + curvature_tangential)


def cells_per_view(radius_mm: np.ndarray | float, standoff_mm: np.ndarray, cutoff_deg: float) -> np.ndarray:
    """Effective cells covered by the sphere's image within the incidence cut-off.

    The part of the sphere with incidence below the cut-off projects to a disk of
    radius R sin(cutoff); its area divided by the cell footprint area is the count.
    """
    projected_radius = radius_mm * np.sin(np.radians(cutoff_deg))
    return np.pi * projected_radius ** 2 / cell_footprint_mm(standoff_mm) ** 2


def main() -> None:
    alpha_deg = np.linspace(0.0, INCIDENCE_MAX_PLOT_DEG, 400)
    alpha = np.radians(alpha_deg)
    fig, axes = plt.subplots(1, 3, figsize=FIGURE_SIZE_IN, dpi=OUTPUT_DPI)

    # (a) cell-averaging bias on a sphere
    ax = axes[0]
    for radius, style in zip(SPHERE_RADII_MM, LINE_STYLES):
        for standoff, color in zip(STANDOFFS_MM, ("#1f5fa8", "#d9731a", "#b03030")):
            ax.plot(alpha_deg, cell_averaging_depth_bias_mm(alpha, radius, standoff), style, color=color,
                    label=f"R = {radius:.0f} mm, z = {standoff:.0f} mm")
    for standoff, color in zip(STANDOFFS_MM, ("#1f5fa8", "#d9731a", "#b03030")):
        sigma = NOISE_COEFFICIENT_PER_MM * standoff ** 2
        ax.axhline(sigma, color=color, lw=0.8, alpha=0.5)
        ax.text(INCIDENCE_MAX_PLOT_DEG - 1, sigma * 1.15, f"sigma_z at {standoff:.0f} mm", fontsize=6, color=color,
                ha="right", bbox=dict(facecolor="white", edgecolor="none", pad=0.5))
    ax.axvline(INCIDENCE_CUTOFF_DEG, color="#555555", lw=1, ls="-.")
    ax.set_yscale("log")
    ax.set_ylim(1e-3, 10)
    ax.set_xlim(0, INCIDENCE_MAX_PLOT_DEG)
    ax.set_xlabel("incidence angle alpha (deg)", fontsize=8)
    ax.set_ylabel("depth bias from 4 x 4 cell averaging (mm)", fontsize=8)
    ax.set_title("(a) curvature bias of cell averaging on a sphere\n(a target effect, not a sensor effect)", fontsize=9)
    ax.legend(fontsize=5.5, ncol=1, loc="upper left")

    # (b) noise multiplier, geometric leverage, product
    ax = axes[1]
    noise_multiplier = np.cos(alpha) ** (-INCIDENCE_NOISE_EXPONENT)
    leverage = 1.0 / np.cos(alpha)
    ax.plot(alpha_deg, noise_multiplier, color="#1f5fa8", label=f"noise multiplier sec^{INCIDENCE_NOISE_EXPONENT}(alpha) (spec, indicative)")
    ax.plot(alpha_deg, leverage, color="#d9731a", label="center-error leverage sec(alpha)")
    ax.plot(alpha_deg, noise_multiplier * leverage, color="#b03030", lw=2,
            label="product: relative noise of one range-correction sample")
    ax.axvline(INCIDENCE_CUTOFF_DEG, color="#555555", lw=1, ls="-.")
    ax.text(INCIDENCE_CUTOFF_DEG - 1, 60, "calibration cut-off", rotation=90, fontsize=6, color="#555555", ha="right")
    ax.axvline(NO_READ_BASELINE_SLOPE_DEG, color="#fc8d59", lw=1, ls="--")
    ax.axvline(NO_READ_INCIDENCE_DEG, color="#d7301f", lw=1, ls="--")
    ax.text(NO_READ_BASELINE_SLOPE_DEG + 0.5, 60, "no-read along baseline (spec, indicative)", rotation=90, fontsize=6, color="#fc8d59")
    ax.text(NO_READ_INCIDENCE_DEG - 1, 60, "no-read, signal (spec, indicative)", rotation=90, fontsize=6, color="#d7301f", ha="right")
    ax.set_yscale("log")
    ax.set_ylim(0.8, 150)
    ax.set_xlim(0, INCIDENCE_MAX_PLOT_DEG)
    ax.set_xlabel("incidence angle alpha (deg)", fontsize=8)
    ax.set_ylabel("factor relative to a face-on sample", fontsize=8)
    ax.set_title("(b) how a sample's value as a constraint\ndegrades with incidence", fontsize=9)
    ax.legend(fontsize=6, loc="upper left")

    # (c) cells per view versus standoff
    ax = axes[2]
    standoff = np.linspace(*STANDOFF_RANGE_MM, 200)
    for radius, style in zip(SPHERE_RADII_MM, LINE_STYLES):
        ax.plot(standoff, cells_per_view(radius, standoff, INCIDENCE_CUTOFF_DEG), style, color="#1f5fa8",
                label=f"R = {radius:.0f} mm")
    ax.set_yscale("log")
    ax.set_xlabel("standoff z (mm)", fontsize=8)
    ax.set_ylabel(f"effective cells per view below {INCIDENCE_CUTOFF_DEG:.0f} deg", fontsize=8)
    ax.set_title("(c) samples one sphere view yields", fontsize=9)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=7)

    for a in axes:
        a.tick_params(labelsize=7)
    fig.tight_layout()
    out = Path(__file__).with_name("fig_sphere_view_effects.png")
    fig.savefig(out, facecolor="white")
    # Print the numbers quoted in the analysis document.
    for radius in SPHERE_RADII_MM:
        for standoff in STANDOFFS_MM:
            for a_deg in (45.0, 60.0, 75.0):
                bias = cell_averaging_depth_bias_mm(np.radians(a_deg), radius, standoff)
                print(f"R={radius:5.0f} z={standoff:5.0f} alpha={a_deg:4.0f}: cell-averaging bias {bias:.4f} mm")
    for radius in SPHERE_RADII_MM:
        for standoff in STANDOFFS_MM:
            print(f"R={radius:5.0f} z={standoff:5.0f}: {cells_per_view(radius, np.array(standoff), INCIDENCE_CUTOFF_DEG):.0f} cells/view")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
