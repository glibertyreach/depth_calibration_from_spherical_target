"""Tests of the single-sphere geometric-ladder pose planner (sphcal.cli.plan_poses):
the ladder stations, the always-kept center pose, the grid fitted to the room the sphere's image leaves, the
board depths, the explicit station list and the removal of the two-radius mode."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from sphcal.cli import plan_poses
from sphcal.cli.plan_poses import PlanParameters
from sphcal.geometry.camera import PinholeCamera

IMAGE_WIDTH_PX = 640
IMAGE_HEIGHT_PX = 480
FOV_DEG = (49.9, 38.5)
CAMERA = PinholeCamera(IMAGE_WIDTH_PX, IMAGE_HEIGHT_PX,
                       (IMAGE_WIDTH_PX / 2.0) / np.tan(np.radians(FOV_DEG[0]) / 2.0),
                       (IMAGE_HEIGHT_PX / 2.0) / np.tan(np.radians(FOV_DEG[1]) / 2.0),
                       IMAGE_WIDTH_PX / 2.0, IMAGE_HEIGHT_PX / 2.0)
"""The camera of the procedure's example plan."""
EXPECTED_LADDER_MM = (300, 357, 424, 505, 600, 714, 849, 1009, 1100)
"""Default stations rounded to whole millimeters: 300 * 2^(k/4) for k = 0..7, then depth_max."""
EXPECTED_SPHERE_RADIUS_MM = 76.2
EXAMPLE_FOV_FILL = 0.7
EXAMPLE_BOARD_HALF_SIZE_MM = (100.0, 75.0)
EXAMPLE_BOARD_LATERAL_FILL = 0.2
"""The example plan's board size and spread (the defaults are larger and skip the nearest depths)."""
LARGE_SPHERE_RADIUS_MM = 200.0
"""A sphere too large for the field at 300 mm: its center pose is clipped but must still be kept."""


def example_parameters(**overrides) -> PlanParameters:
    return replace(PlanParameters(fov_fill=EXAMPLE_FOV_FILL), **overrides)


def sphere_poses(poses):
    return [q for q in poses if q.kind == "sphere"]


def border_rays_miss_sphere(camera: PinholeCamera, center: np.ndarray, radius: float) -> bool:
    """Independent of the planner's silhouette projection: the ray through every pixel on the image border must
    miss the sphere (pass it at a distance from the center greater than the radius), so no part of the sphere
    reaches the border or crosses it."""
    last_column, last_row = camera.width - 1, camera.height - 1
    columns = np.arange(camera.width, dtype=np.float64)
    rows = np.arange(camera.height, dtype=np.float64)
    u = np.concatenate([columns, columns, np.zeros(camera.height), np.full(camera.height, last_column)])
    v = np.concatenate([np.zeros(camera.width), np.full(camera.width, last_row), rows, rows])
    rays = camera.ray_directions_at(u, v)
    distance = np.linalg.norm(center - (rays @ center)[:, None] * rays, axis=1)
    return bool(np.all(distance > radius))


def test_default_ladder_stations_are_exactly_the_specified_ones():
    p = example_parameters()
    assert p.sphere_radius_mm == EXPECTED_SPHERE_RADIUS_MM
    stations = plan_poses.sphere_stations(p)
    assert tuple(int(round(d)) for d in stations) == EXPECTED_LADDER_MM
    # Geometric from the minimum up to the last rung below depth_max, which is appended as the last station.
    ratio = 2.0 ** 0.25
    assert np.allclose(stations[:-1], [300.0 * ratio ** k for k in range(len(stations) - 1)])
    assert stations[-1] == p.depth_max_mm


def test_ladder_end_is_appended_only_beyond_the_tolerance():
    # The ladder 300 * 2^k reaches exactly 600 and 1200; with depth_max 610 the last rung is within the tolerance.
    close = plan_poses.sphere_stations(example_parameters(sphere_depth_ratio=2.0, depth_max_mm=610.0))
    assert close == [300.0, 600.0]
    far = plan_poses.sphere_stations(example_parameters(sphere_depth_ratio=2.0, depth_max_mm=700.0))
    assert far == [300.0, 600.0, 700.0]
    explicit = plan_poses.sphere_stations(example_parameters(sphere_depths_mm=(450.0, 380.0, 900.0)))
    assert explicit == [450.0, 380.0, 900.0]            # the explicit list replaces the ladder, order kept


def test_every_station_has_a_center_pose_and_the_stations_are_the_ladder():
    p = example_parameters()
    poses, counts = plan_poses.plan_spheres(p, CAMERA)
    stations = plan_poses.sphere_stations(p)
    assert list(counts) == stations
    for depth in stations:
        centers = [q.center_sensor for q in poses if q.plane_depth_mm == depth]
        assert any(np.allclose(c, [0.0, 0.0, depth]) for c in centers), depth
    assert {q.radius_mm for q in poses} == {EXPECTED_SPHERE_RADIUS_MM}
    assert all(q.pose_id.startswith("s076_z") for q in poses)
    # Counts: planned = kept + dropped at every station.
    for depth, (planned, dropped) in counts.items():
        assert planned == dropped + sum(q.plane_depth_mm == depth for q in poses)


def test_no_planned_sphere_pose_clips_the_image():
    poses, counts = plan_poses.plan_spheres(example_parameters(), CAMERA)
    # The grid is fitted to the room the sphere's image leaves, so nothing has to be dropped.
    assert sum(dropped for _, dropped in counts.values()) == 0
    for q in poses:
        assert not plan_poses.silhouette_leaves_image(CAMERA, q, PlanParameters().edge_margin_px), q.pose_id
        assert border_rays_miss_sphere(CAMERA, q.center_sensor, q.radius_mm), q.pose_id


def test_near_stations_keep_off_axis_positions():
    p = example_parameters()
    poses, counts = plan_poses.plan_spheres(p, CAMERA)
    minimum = p.min_positions_per_axis
    for depth in counts:
        centers = np.array([q.center_sensor for q in poses if q.plane_depth_mm == depth])
        # At least the minimum number of distinct positions along each axis, on both sides of the center.
        assert len(np.unique(np.round(centers[:, 0], 6))) >= minimum, depth
        assert len(np.unique(np.round(centers[:, 1], 6))) >= minimum, depth
        assert centers[:, 0].min() < 0.0 < centers[:, 0].max(), depth
        assert centers[:, 1].min() < 0.0 < centers[:, 1].max(), depth
    # The nearest station, where the sphere's image leaves the least room, has exactly the minimum grid.
    nearest = min(counts)
    assert counts[nearest][0] == minimum ** 2


def test_room_is_the_largest_rectangle_that_fits():
    p = example_parameters()
    depth = plan_poses.sphere_stations(p)[0]
    room_x, room_y = plan_poses.sphere_center_room_mm(CAMERA, depth, p.sphere_radius_mm, p.edge_margin_px,
                                                       p.room_bisection_tolerance_mm)
    assert room_x > 0.0 and room_y > 0.0
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            inside = np.array([sx * room_x, sy * room_y, depth])
            assert plan_poses.sphere_fits_in_image(CAMERA, inside, p.sphere_radius_mm, p.edge_margin_px)
    # Scaled out by two bisection tolerances, the rectangle's corners no longer all fit.
    scale = 1.0 + 2.0 * p.room_bisection_tolerance_mm / max(room_x, room_y)
    corners_fit = [plan_poses.sphere_fits_in_image(CAMERA, np.array([sx * room_x * scale, sy * room_y * scale, depth]),
                                                   p.sphere_radius_mm, p.edge_margin_px)
                   for sx in (-1.0, 1.0) for sy in (-1.0, 1.0)]
    assert not all(corners_fit)


def test_center_pose_is_kept_even_when_the_sphere_clips_there():
    p = example_parameters(sphere_radius_mm=LARGE_SPHERE_RADIUS_MM, sphere_depths_mm=(300.0,))
    poses, counts = plan_poses.plan_spheres(p, CAMERA)
    assert len(poses) == 1 and np.allclose(poses[0].center_sensor, [0.0, 0.0, 300.0])
    assert plan_poses.silhouette_leaves_image(CAMERA, poses[0], p.edge_margin_px)     # clipped, and still kept
    assert counts[300.0][1] == counts[300.0][0] - 1


def test_default_board_depths_include_the_extra_near_depth():
    p = PlanParameters()
    assert p.board_depths_mm == (350.0, 425.0, 550.0, 800.0, 1050.0)
    poses, counts = plan_poses.plan_boards(example_parameters(board_half_size_mm=EXAMPLE_BOARD_HALF_SIZE_MM,
                                                              board_lateral_fill=EXAMPLE_BOARD_LATERAL_FILL), CAMERA)
    assert 425.0 in counts and any(q.plane_depth_mm == 425.0 for q in poses)


def test_two_radius_mode_is_gone():
    for name in ("near_radius_mm", "far_radius_mm", "radius_switch_depth_mm", "overlap_band_mm",
                 "depth_planes_near", "depth_planes_far"):
        assert not hasattr(PlanParameters(), name), name
    with pytest.raises(SystemExit):
        plan_poses.build_parser().parse_args(["--sensor-in-base", "x", "--out", "y", "--near-radius-mm", "40"])


def test_invalid_ladder_parameters_are_refused():
    for bad in (dict(sphere_depth_ratio=1.0), dict(sphere_radius_mm=0.0), dict(ladder_end_tolerance_mm=-1.0),
                dict(sphere_depths_mm=())):
        with pytest.raises(plan_poses.PlanInputError):
            plan_poses.validate_parameters(example_parameters(**bad))


def test_command_line_example_plan(tmp_path: Path, capsys):
    """The command of the procedure's example (figure 2) runs and reports one sphere series and per-station counts."""
    sensor_file = tmp_path / "identity.json"
    sensor_file.write_text(json.dumps({"matrix": list(np.eye(4).reshape(-1))}))
    out = tmp_path / "plan"
    code = plan_poses.main(["--sensor-in-base", str(sensor_file), "--fov-deg", *map(str, FOV_DEG), "--image-size",
                            str(IMAGE_WIDTH_PX), str(IMAGE_HEIGHT_PX), "--sphere-radius-mm", "76.2", "--fov-fill",
                            str(EXAMPLE_FOV_FILL), "--board-half-size-mm", "100", "75", "--board-lateral-fill", "0.2",
                            "--out", str(out)])
    assert code == 0
    summary = (out / plan_poses.PLAN_SUMMARY_NAME).read_text()
    assert "Sphere poses per station" in summary and "dropped" in summary
    for depth in EXPECTED_LADDER_MM:
        assert any(line.split()[:2] == ["76.2", str(depth)] for line in summary.splitlines()), depth
    assert (out / plan_poses.PLAN_FIGURE_NAME).stat().st_size > 0
    rows = (out / plan_poses.PLAN_CSV_NAME).read_text().splitlines()[1:]
    assert len({row.split(",")[0] for row in rows}) == len(rows)         # unique pose ids
    explicit = plan_poses.main(["--sensor-in-base", str(sensor_file), "--fov-deg", *map(str, FOV_DEG), "--image-size",
                                str(IMAGE_WIDTH_PX), str(IMAGE_HEIGHT_PX), "--sphere-depths-mm", "500", "900",
                                "--out", str(tmp_path / "explicit")])
    assert explicit == 0
    explicit_summary = (tmp_path / "explicit" / plan_poses.PLAN_SUMMARY_NAME).read_text()
    assert " 500 " in explicit_summary and " 900 " in explicit_summary and " 300 " not in explicit_summary.split("Board")[0]
