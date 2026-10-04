"""
fig_pose_grid_coverage.png -- how densely the sphere centers must be placed so
that the position-dependent and the slope-dependent parts of the correction can
be separated.

On a single sphere view the incidence angle is a deterministic function of the
image position (it grows from the sphere's center to its limb), so one view
cannot tell a position-dependent error from a slope-dependent one. Only when the
same region of the measurement volume is seen on different spheres at different
incidence angles are the two separable. This script places sphere centers on a
cubic grid of spacing s inside a frustum-shaped working volume, divides the
volume into cubic voxels (the resolution at which the position-dependent part of
the correction is to be resolved), and counts, for every voxel, how many distinct
incidence-angle bins the visible sphere surfaces passing through it present.

Panel (a): fraction of voxels that see at least k distinct incidence bins versus
the center spacing in units of the sphere radius. Panel (b): the number of sphere
poses in the grid. Monte Carlo is not needed: the geometry is exact, evaluated at
voxel centers.

    python3 docs/analysis/figures/make_fig_pose_grid_coverage.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial import cKDTree

# ---- Working volume (sensor frame, mm). A frustum: lateral extent grows with z.
DEPTH_RANGE_MM = (300.0, 1100.0)   # decided working volume: the full frustum
HALF_FOV_H_DEG = 49.9 / 2.0           # specification, indicative
HALF_FOV_V_DEG = 38.5 / 2.0
CENTER_OVERHANG_MM = 50.0             # centers may lie this far outside the frustum: a partly visible sphere still yields samples

# ---- Calibration design -------------------------------------------------------
SPHERE_RADIUS_MM = 50.0
VOXEL_SIZE_MM = 40.0                  # resolution of the position-dependent correction
INCIDENCE_BIN_DEG = 10.0
INCIDENCE_CUTOFF_DEG = 60.0           # samples beyond this are not used
CENTER_SPACING_OVER_RADIUS = np.array([0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0])
COVERAGE_THRESHOLDS = (1, 2, 3, 4)    # at least this many distinct incidence bins
SHELL_HALF_THICKNESS_MM = VOXEL_SIZE_MM / 2.0

# ---- Figure -------------------------------------------------------------------
OUTPUT_DPI = 200
FIGURE_SIZE_IN = (11.0, 4.2)


def frustum_half_widths(z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return z * np.tan(np.radians(HALF_FOV_H_DEG)), z * np.tan(np.radians(HALF_FOV_V_DEG))


def voxel_centers() -> np.ndarray:
    """Centers of the cubic voxels that lie inside the working frustum."""
    z = np.arange(DEPTH_RANGE_MM[0] + VOXEL_SIZE_MM / 2, DEPTH_RANGE_MM[1], VOXEL_SIZE_MM)
    half_w, half_h = frustum_half_widths(np.array(DEPTH_RANGE_MM[1]))
    x = np.arange(-half_w, half_w + VOXEL_SIZE_MM, VOXEL_SIZE_MM)
    y = np.arange(-half_h, half_h + VOXEL_SIZE_MM, VOXEL_SIZE_MM)
    X, Y, Z = np.meshgrid(x, y, z, indexing="ij")
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    hw, hh = frustum_half_widths(pts[:, 2])
    inside = (np.abs(pts[:, 0]) <= hw) & (np.abs(pts[:, 1]) <= hh)
    return pts[inside]


def sphere_centers(spacing_mm: float) -> np.ndarray:
    """Cubic grid of sphere centers covering the frustum, with an overhang beyond its edges.

    Only the near hemisphere of a sphere is visible, so to cover the volume between
    z_min and z_max the centers must span z_min to z_max + R. Laterally the centers may
    overhang the frustum, since the part of a sphere inside the field of view is
    still measured.
    """
    z = np.arange(DEPTH_RANGE_MM[0], DEPTH_RANGE_MM[1] + SPHERE_RADIUS_MM + 1e-9, spacing_mm)
    half_w, half_h = frustum_half_widths(np.array(DEPTH_RANGE_MM[1] + SPHERE_RADIUS_MM))
    x = np.arange(-half_w - CENTER_OVERHANG_MM, half_w + CENTER_OVERHANG_MM + 1e-9, spacing_mm)
    y = np.arange(-half_h - CENTER_OVERHANG_MM, half_h + CENTER_OVERHANG_MM + 1e-9, spacing_mm)
    X, Y, Z = np.meshgrid(x - x.mean(), y - y.mean(), z, indexing="ij")
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    hw, hh = frustum_half_widths(pts[:, 2])
    inside = (np.abs(pts[:, 0]) <= hw + CENTER_OVERHANG_MM) & (np.abs(pts[:, 1]) <= hh + CENTER_OVERHANG_MM)
    return pts[inside]


def distinct_incidence_bins(voxels: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """For each voxel, the number of distinct incidence bins presented by visible sphere surfaces through it."""
    tree = cKDTree(centers)
    n_bins = int(np.ceil(INCIDENCE_CUTOFF_DEG / INCIDENCE_BIN_DEG))
    counts = np.zeros(len(voxels), dtype=int)
    neighbors = tree.query_ball_point(voxels, r=SPHERE_RADIUS_MM + SHELL_HALF_THICKNESS_MM)
    for i, (v, idx) in enumerate(zip(voxels, neighbors)):
        if not idx:
            continue
        c = centers[idx]
        offset = v - c                                   # from sphere center to voxel center
        dist = np.linalg.norm(offset, axis=1)
        on_shell = np.abs(dist - SPHERE_RADIUS_MM) <= SHELL_HALF_THICKNESS_MM
        if not on_shell.any():
            continue
        normal = offset[on_shell] / dist[on_shell, None]
        ray = v / np.linalg.norm(v)                      # line of sight through the voxel
        cos_incidence = -(normal @ ray)                  # normal must face the sensor
        visible = cos_incidence > np.cos(np.radians(INCIDENCE_CUTOFF_DEG))
        if not visible.any():
            continue
        alpha = np.degrees(np.arccos(np.clip(cos_incidence[visible], -1, 1)))
        bins = np.unique(np.minimum((alpha / INCIDENCE_BIN_DEG).astype(int), n_bins - 1))
        counts[i] = len(bins)
    return counts


def main() -> None:
    voxels = voxel_centers()
    fractions = {k: [] for k in COVERAGE_THRESHOLDS}
    n_poses = []
    for ratio in CENTER_SPACING_OVER_RADIUS:
        centers = sphere_centers(ratio * SPHERE_RADIUS_MM)
        counts = distinct_incidence_bins(voxels, centers)
        n_poses.append(len(centers))
        for k in COVERAGE_THRESHOLDS:
            fractions[k].append(np.mean(counts >= k))
        print(f"spacing {ratio:.2f} R = {ratio * SPHERE_RADIUS_MM:5.1f} mm: {len(centers):5d} poses; "
              + ", ".join(f">= {k} bins: {fractions[k][-1]:.2f}" for k in COVERAGE_THRESHOLDS))

    fig, axes = plt.subplots(1, 2, figsize=FIGURE_SIZE_IN, dpi=OUTPUT_DPI)
    ax = axes[0]
    for k, color in zip(COVERAGE_THRESHOLDS, ("#999999", "#1f5fa8", "#d9731a", "#b03030")):
        ax.plot(CENTER_SPACING_OVER_RADIUS, fractions[k], "o-", color=color, label=f"at least {k} distinct incidence bins")
    ax.set_xlabel("sphere-center grid spacing / sphere radius", fontsize=8)
    ax.set_ylabel(f"fraction of {VOXEL_SIZE_MM:.0f} mm voxels covered", fontsize=8)
    ax.set_ylim(0, 1.02)
    ax.set_title(f"(a) separability of position and slope effects\n(R = {SPHERE_RADIUS_MM:.0f} mm, "
                 f"{INCIDENCE_BIN_DEG:.0f} deg bins to {INCIDENCE_CUTOFF_DEG:.0f} deg)", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7)
    ax = axes[1]
    ax.plot(CENTER_SPACING_OVER_RADIUS, n_poses, "o-", color="#1f5fa8")
    ax.set_yscale("log")
    ax.set_xlabel("sphere-center grid spacing / sphere radius", fontsize=8)
    ax.set_ylabel("sphere poses in the grid", fontsize=8)
    ax.set_title(f"(b) poses needed for the volume\n(z {DEPTH_RANGE_MM[0]:.0f} to {DEPTH_RANGE_MM[1]:.0f} mm, full field of view)", fontsize=9)
    ax.grid(True, which="both", alpha=0.3)
    for a in axes:
        a.tick_params(labelsize=7)
    fig.tight_layout()
    out = Path(__file__).with_name("fig_pose_grid_coverage.png")
    fig.savefig(out, facecolor="white")
    print(f"wrote {out}; voxels {len(voxels)}")


if __name__ == "__main__":
    main()
