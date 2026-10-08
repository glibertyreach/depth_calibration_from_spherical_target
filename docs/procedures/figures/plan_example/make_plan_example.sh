#!/usr/bin/env bash
# Regenerates the example plan of the procedure (figure 2): docs/procedures/figures/fig_plan_example.png
# and docs/procedures/figures/plan_example_summary.txt.
#
# Run from anywhere; the script changes to the repository root. The sensor-to-base transform is the
# identity, so base-frame and sensor-frame coordinates coincide in the example. The sensor is the
# 49.9 x 38.5 degree, 640 x 480 px camera of the procedure; one 76.2 mm sphere is swept through the
# default geometric ladder of depths, and the boards are the 200 x 150 mm boards of the procedure.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

FIGURES_DIR=docs/procedures/figures
EXAMPLE_DIR="$FIGURES_DIR/plan_example"
SENSOR_IN_BASE="$EXAMPLE_DIR/sensor_in_base_identity.json"
SCRATCH_DIR="$(mktemp -d)"
trap 'rm -rf "$SCRATCH_DIR"' EXIT

python3 -m sphcal.cli.plan_poses \
    --sensor-in-base "$SENSOR_IN_BASE" \
    --fov-deg 49.9 38.5 --image-size 640 480 \
    --sphere-radius-mm 76.2 --fov-fill 0.7 \
    --board-half-size-mm 100 75 --board-lateral-fill 0.2 \
    --out "$SCRATCH_DIR"

cp "$SCRATCH_DIR/plan.png" "$FIGURES_DIR/fig_plan_example.png"
# The summary names the transform file by its scratch-independent relative path.
sed "s#matrix from .*sensor_in_base_identity.json#matrix from $SENSOR_IN_BASE#" \
    "$SCRATCH_DIR/plan_summary.txt" > "$FIGURES_DIR/plan_example_summary.txt"
echo "Wrote $FIGURES_DIR/fig_plan_example.png and $FIGURES_DIR/plan_example_summary.txt"
