"""
fig_spline_complexity.png -- storage, evaluation cost and data demand of the
candidate correction models, as a function of the number of knot intervals per
input dimension.

Models compared:
  full-5D   one tensor-product B-spline over (u, v, d, s_u, s_v) with the same
            number of intervals n in every dimension;
  additive  a position term A(u, v, d) plus a slope term C(s_u, s_v, d), two
            tensor-product splines of three inputs each (the structured
            alternative; the d dimension appears in both);
  cell-LUT  a per-effective-cell lookup table in (u, v) with a cubic spline in d,
            plus the same slope term (what a high-frequency fixed pattern needs).

Counts: a B-spline of degree p over n intervals has n + p coefficients per
dimension. Evaluating a tensor-product spline of degree p in D dimensions costs
(p + 1)^D multiply-adds for the tensor contraction, plus D basis evaluations.

Panel (a): coefficients (storage). Panel (b): multiply-adds per corrected point
and the resulting time per frame at an assumed throughput. Panel (c): the
minimum number of calibration samples, taken as a fixed number of samples per
coefficient, and the sphere poses it implies at an assumed yield per pose.

    python3 docs/analysis/figures/make_fig_spline_complexity.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---- Model constants ----------------------------------------------------------
SPLINE_DEGREE = 3
INPUT_DIMENSIONS_FULL = 5
INTERVALS_PER_DIMENSION = np.arange(2, 17)
EFFECTIVE_CELLS_UV = 160 * 120               # per-cell lookup table size in (u, v) (indicative)
BASIS_EVAL_FLOPS_PER_DIMENSION = 12          # de Boor evaluation of the p + 1 nonzero cubic basis values

# ---- Runtime assumptions -------------------------------------------------------
POINTS_PER_FRAME = 640 * 480                 # correcting every native pixel (worst case)
THROUGHPUT_FLOPS_PER_SECOND = 2.0e9          # one vectorized CPU core, conservative

# ---- Data-demand assumptions ---------------------------------------------------
SAMPLES_PER_COEFFICIENT = 30                 # for noise averaging and conditioning
SAMPLES_PER_POSE = 500                       # effective cells per sphere view below the cut-off (R = 50 mm, ~600 mm)

# ---- Figure ---------------------------------------------------------------------
OUTPUT_DPI = 200
FIGURE_SIZE_IN = (13.0, 4.2)


def coefficients_per_dimension(intervals: np.ndarray) -> np.ndarray:
    return intervals + SPLINE_DEGREE


def tensor_coefficients(intervals: np.ndarray, dimensions: int) -> np.ndarray:
    return coefficients_per_dimension(intervals).astype(float) ** dimensions


SPLINE_DEGREES_COMPARED = (1, 2, 3)          # linear (C0), quadratic (C1), cubic (C2)


def tensor_eval_flops(dimensions: int, degree: int = SPLINE_DEGREE) -> float:
    """Multiply-adds to evaluate one tensor-product B-spline of the given degree and dimension."""
    basis_cost = BASIS_EVAL_FLOPS_PER_DIMENSION * (degree + 1) / (SPLINE_DEGREE + 1)
    return float((degree + 1) ** dimensions + dimensions * basis_cost)


def main() -> None:
    n = INTERVALS_PER_DIMENSION
    coeff_full = tensor_coefficients(n, INPUT_DIMENSIONS_FULL)
    coeff_additive = 2.0 * tensor_coefficients(n, 3)
    coeff_lut = EFFECTIVE_CELLS_UV * coefficients_per_dimension(n) + tensor_coefficients(n, 3)
    degrees = np.array(SPLINE_DEGREES_COMPARED)
    flops_full = np.array([tensor_eval_flops(INPUT_DIMENSIONS_FULL, p) for p in degrees])
    flops_additive = np.array([2.0 * tensor_eval_flops(3, p) for p in degrees])
    flops_lut = np.array([tensor_eval_flops(1, p) + tensor_eval_flops(3, p) for p in degrees])

    fig, axes = plt.subplots(1, 3, figsize=FIGURE_SIZE_IN, dpi=OUTPUT_DPI)
    styles = (("full 5-D tensor product", "#b03030", "-"), ("additive A(u,v,d) + C(s_u,s_v,d)", "#1f5fa8", "-"),
              ("per-cell LUT(u,v) x spline(d) + C", "#d9731a", "--"))

    ax = axes[0]
    for (label, color, ls), coeff in zip(styles, (coeff_full, coeff_additive, coeff_lut)):
        ax.plot(n, coeff, ls, color=color, label=label)
    ax.set_yscale("log")
    ax.set_xlabel("knot intervals per input dimension", fontsize=8)
    ax.set_ylabel("coefficients (floats)", fontsize=8)
    ax.set_title("(a) storage", fontsize=9)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=6.5)

    ax = axes[1]
    bar_width = 0.25
    for k, ((label, color, ls), flops) in enumerate(zip(styles, (flops_full, flops_additive, flops_lut))):
        ax.bar(degrees + (k - 1) * bar_width, flops, bar_width, color=color, label=label)
    ax.set_yscale("log")
    ax.set_xticks(degrees)
    ax.set_xticklabels([f"degree {p}\n(C{p - 1})" for p in degrees])
    ax.set_xlabel("spline degree (continuity of the correction)", fontsize=8)
    ax.set_ylabel("multiply-adds per corrected point", fontsize=8)
    secondary = ax.secondary_yaxis("right", functions=(lambda f: f * POINTS_PER_FRAME / THROUGHPUT_FLOPS_PER_SECOND * 1e3,
                                                        lambda t: t / 1e3 * THROUGHPUT_FLOPS_PER_SECOND / POINTS_PER_FRAME))
    secondary.set_ylabel(f"ms per {POINTS_PER_FRAME // 1000}k-point frame at {THROUGHPUT_FLOPS_PER_SECOND / 1e9:.0f} GFLOP/s", fontsize=7)
    secondary.tick_params(labelsize=7)
    ax.set_title("(b) evaluation cost per point (independent of knot count)", fontsize=9)
    ax.grid(True, which="both", alpha=0.3)

    ax = axes[2]
    for (label, color, ls), coeff in zip(styles, (coeff_full, coeff_additive, coeff_lut)):
        ax.plot(n, coeff * SAMPLES_PER_COEFFICIENT, ls, color=color, label=label)
    ax.set_yscale("log")
    ax.set_xlabel("knot intervals per input dimension", fontsize=8)
    ax.set_ylabel(f"calibration samples ({SAMPLES_PER_COEFFICIENT} per coefficient)", fontsize=8)
    secondary = ax.secondary_yaxis("right", functions=(lambda s: s / SAMPLES_PER_POSE, lambda p: p * SAMPLES_PER_POSE))
    secondary.set_ylabel(f"sphere poses at {SAMPLES_PER_POSE} samples per pose", fontsize=7)
    secondary.tick_params(labelsize=7)
    ax.set_title("(c) data demand if every coefficient must be\nsupported by data (no smoothing prior)", fontsize=9)
    ax.grid(True, which="both", alpha=0.3)

    for a in axes:
        a.tick_params(labelsize=7)
    fig.tight_layout()
    out = Path(__file__).with_name("fig_spline_complexity.png")
    fig.savefig(out, facecolor="white")
    for i in (4, 8, 12):
        j = int(np.where(n == i)[0][0])
        print(f"n={i}: coeff full {coeff_full[j]:.3g}, additive {coeff_additive[j]:.3g}, lut {coeff_lut[j]:.3g}; "
              f"poses full {coeff_full[j] * SAMPLES_PER_COEFFICIENT / SAMPLES_PER_POSE:.3g}, "
              f"additive {coeff_additive[j] * SAMPLES_PER_COEFFICIENT / SAMPLES_PER_POSE:.3g}")
    for p, a, b, c in zip(degrees, flops_full, flops_additive, flops_lut):
        print(f"degree {p}: flops full {a:.0f}, additive {b:.0f}, lut {c:.0f}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
