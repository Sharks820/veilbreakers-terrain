"""Compatibility wrapper for the canonical grade-gap audit."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "build_verified_grades_gap_report.py"
    sys.argv = [str(target), *sys.argv[1:]]
    runpy.run_path(str(target), run_name="__main__")
