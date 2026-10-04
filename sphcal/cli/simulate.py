"""
Command line: write a synthetic calibration dataset (sphere and board poses on
a grid in the full frustum) with an injected, known error field, for testing
the fit end to end.

    python3 -m sphcal.cli.simulate --out data/synthetic --poses 60 --frames 3
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from sphcal.geometry.transforms import RigidTransform
from sphcal.simulate.synthetic import SyntheticSensorParameters, default_injected_error_field, write_synthetic_dataset

DEFAULT_SPHERE_RADII_MM = (40.0, 80.0)
"""The two radii recommended by the analysis (D-10)."""
DEFAULT_DEPTH_RANGE_MM = (300.0, 1100.0)
"""The decided working volume (D-7)."""
DEFAULT_BOARD_HALF_SIZE_MM = (150.0, 100.0)
DEFAULT_BOARD_TILTS_DEG = (0.0, 25.0, 45.0)
DEFAULT_SENSOR_TO_POSITIONER = RigidTransform.from_rotation_vector_degrees([2.0, -3.0, 1.0], [250.0, -120.0, 800.0])
"""An arbitrary transform so that the solve is exercised."""
FRUSTUM_FILL_FRACTION = 0.8
"""Fraction of the half field of view over which pose centers are spread."""


def pose_list(n_poses: int, rng: np.random.Generator, params: SyntheticSensorParameters, board_fraction: float):
    """Random sphere and board poses inside the frustum, in the positioner frame."""
    half_h_deg, half_v_deg = params.camera.half_angles_degrees()
    poses = []
    for index in range(n_poses):
        z = rng.uniform(*DEFAULT_DEPTH_RANGE_MM)
        x = rng.uniform(-1.0, 1.0) * FRUSTUM_FILL_FRACTION * z * np.tan(np.radians(half_h_deg))
        y = rng.uniform(-1.0, 1.0) * FRUSTUM_FILL_FRACTION * z * np.tan(np.radians(half_v_deg))
        center_sensor = np.array([x, y, z])
        center_positioner = DEFAULT_SENSOR_TO_POSITIONER.apply_points(center_sensor)
        if rng.uniform() < board_fraction:
            tilt = rng.choice(DEFAULT_BOARD_TILTS_DEG)
            azimuth = rng.uniform(0.0, 360.0)
            axis = np.array([np.cos(np.radians(azimuth)), np.sin(np.radians(azimuth)), 0.0])
            # Board normal +z faces the sensor when rotated by 180 degrees about x, then tilted.
            facing = RigidTransform.from_rotation_vector_degrees([180.0, 0.0, 0.0], [0.0, 0.0, 0.0])
            tilted = RigidTransform.from_rotation_vector_degrees(axis * tilt, [0.0, 0.0, 0.0]).compose(facing)
            pose_sensor = RigidTransform(tilted.rotation, center_sensor)
            poses.append(("board", DEFAULT_BOARD_HALF_SIZE_MM, DEFAULT_SENSOR_TO_POSITIONER.compose(pose_sensor)))
        else:
            radius = DEFAULT_SPHERE_RADII_MM[0] if z < np.mean(DEFAULT_DEPTH_RANGE_MM) else DEFAULT_SPHERE_RADII_MM[1]
            if rng.uniform() < 0.25:
                radius = DEFAULT_SPHERE_RADII_MM[1 - DEFAULT_SPHERE_RADII_MM.index(radius)]
            poses.append(("sphere", radius, RigidTransform(np.eye(3), center_positioner)))
    return poses


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--poses", type=int, default=60)
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--board-fraction", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--fixed-pattern-mm", type=float, default=0.0)
    args = parser.parse_args(argv)
    rng = np.random.default_rng(args.seed)
    params = SyntheticSensorParameters.vsx3000_indicative()
    if args.fixed_pattern_mm > 0:
        params = SyntheticSensorParameters(**{**params.__dict__, "fixed_pattern_amplitude_mm": args.fixed_pattern_mm})
    poses = pose_list(args.poses, rng, params, args.board_fraction)
    write_synthetic_dataset(Path(args.out), params, poses, DEFAULT_SENSOR_TO_POSITIONER, args.frames,
                            default_injected_error_field, rng)
    print(f"wrote {len(poses)} poses x {args.frames} frames to {args.out}")


if __name__ == "__main__":
    main()
