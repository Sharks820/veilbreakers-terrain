"""Compatibility wrapper for legacy coverage-gap entrypoint.

Use scripts/build_verified_grades_gap_report.py for the canonical audit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "build_verified_grades_gap_report.py"
    result = subprocess.run([sys.executable, str(target)], check=False)
    raise SystemExit(result.returncode)
