"""Regenerate all six Stage-1 fixture shop drawings (SC1-01 .. SC1-06).

Usage (from anywhere):

    python3 docs/procedures/drawings/make_all.py

The PNG files are written next to this script.  The script prints, for every
drawing, the number of layout problems found by the automatic overlap check and
exits with status 1 if any were found.
"""

from __future__ import annotations

import os
import sys

# Make the sibling modules importable regardless of the working directory.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import part_01_02_adapter_plates  # noqa: E402
import part_03_04_stems  # noqa: E402
import part_05_board_adapter  # noqa: E402
import part_06_nest_base  # noqa: E402


def main() -> int:
    """Draw all six sheets; return the process exit code."""
    results: dict[str, list[str]] = {}
    results.update(part_01_02_adapter_plates.build_all(HERE))
    results.update(part_03_04_stems.build_all(HERE))
    results["SC1-05"] = part_05_board_adapter.build(HERE)
    results["SC1-06"] = part_06_nest_base.build(HERE)
    problems = 0
    for number in sorted(results):
        issues = results[number]
        print(f"{number}: {len(issues)} layout problem(s)")
        for issue in issues:
            print(f"    {issue}")
        problems += len(issues)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
