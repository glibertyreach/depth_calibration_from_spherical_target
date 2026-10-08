"""Regenerate the four active Stage-1 fixture shop drawings (SC1-02, SC1-04, SC1-05, SC1-06).

Usage (from anywhere):

    python3 docs/procedures/drawings/make_all.py
    python3 docs/procedures/drawings/make_all.py --archived   # also redraw SC1-01 and SC1-03

The active PNG files are written next to this script.  SC1-01 and SC1-03 (sphere A)
were archived when the calibration moved to one sphere (decision D-15); with
``--archived`` they are redrawn into the ``archive`` subdirectory.  The numbers are
not reused, because other projects cite SC1-02, SC1-04 and SC1-05.  The script prints, for every
drawing, the number of layout problems found by the automatic overlap check and
exits with status 1 if any were found.
"""

from __future__ import annotations

import os
import sys

# Make the sibling modules importable regardless of the working directory.
HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_DIR = os.path.join(HERE, "archive")  # where the archived sphere A sheets live
ARCHIVED_FLAG = "--archived"  # command-line flag that also redraws the archived sheets
sys.path.insert(0, HERE)

import part_01_02_adapter_plates  # noqa: E402
import part_03_04_stems  # noqa: E402
import part_05_board_adapter  # noqa: E402
import part_06_nest_base  # noqa: E402


def main(argv: list[str]) -> int:
    """Draw the active sheets (and the archived ones on request); return the process exit code."""
    results: dict[str, list[str]] = {}
    results.update(part_01_02_adapter_plates.build_all(HERE))
    results.update(part_03_04_stems.build_all(HERE))
    if ARCHIVED_FLAG in argv:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        archived = {**part_01_02_adapter_plates.build_all(ARCHIVE_DIR, include_archived=True),
                    **part_03_04_stems.build_all(ARCHIVE_DIR, include_archived=True)}
        # build_all also redraws the active sheet of each pair; keep only the archived ones there.
        for number in ("SC1-02", "SC1-04"):
            archived.pop(number)
        for name in os.listdir(ARCHIVE_DIR):
            if name.startswith(("SC1-02", "SC1-04")):
                os.remove(os.path.join(ARCHIVE_DIR, name))
        results.update(archived)
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
    raise SystemExit(main(sys.argv[1:]))
