"""Scatter altitude audit linter for CI and code-review checks.

Addendum 3.A + Addendum 3.B.6 + Addendum 3.B.7.

This is intentionally a source linter, not a runtime gate. It scans handler
source for the known bad altitude-normalisation idioms that collapse signed
world elevations into ``[0, 1]`` without a reversible transform.

Use ``terrain_semantics.WorldHeightTransform`` for runtime conversion.
Use this module in tests/CI to keep the forbidden patterns from returning.
"""

from __future__ import annotations

import re
from typing import List, Tuple


WORLD_HEIGHT_TRANSFORM_WARNING = (
    "SCATTER ALTITUDE AUDIT: This code path once used "
    "`heights / heights.max()` or `altitude / height_scale` clamped to "
    "[0, 1], which silently collapses negative-elevation lowlands (basins, "
    "wetlands, underwater valleys) to zero. Use "
    "`terrain_semantics.WorldHeightTransform` instead — it preserves sign "
    "and round-trips signed elevations. This module is a linter only; wire "
    "it into CI/tests, not runtime placement."
)


_BAD_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("heights_div_heights_max", re.compile(r"heights\s*/\s*heights\.max\s*\(")),
    ("heightmap_div_heightmap_max", re.compile(r"heightmap\s*/\s*heightmap\.max\s*\(")),
    ("altitude_div_height_scale", re.compile(r"altitude\s*/\s*height_scale\b")),
    ("center_z_div_height_scale", re.compile(r"center\.z\s*/\s*height_scale\b")),
    ("np_clip_0_1_on_altitude", re.compile(r"np\.clip\s*\(\s*altitude[^,]*,\s*0\.?0?\s*,\s*1\.?0?\s*\)")),
    ("arr_minus_arr_min", re.compile(r"\barr\s*-\s*arr\.min\s*\(")),
    ("array_minus_array_min", re.compile(r"\b(\w+)\s*-\s*\1\.min\s*\(")),
)


def audit_scatter_altitude_conversion(module_source: str) -> List[str]:
    """Return ``<pattern_id>:L<lineno>: <line>`` entries for forbidden idioms."""
    if not module_source:
        return []

    offenders: List[str] = []
    for lineno, line in enumerate(module_source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for pattern_id, regex in _BAD_PATTERNS:
            if regex.search(line):
                offenders.append(f"{pattern_id}:L{lineno}: {stripped}")
                break
    return offenders


__all__ = [
    "WORLD_HEIGHT_TRANSFORM_WARNING",
    "audit_scatter_altitude_conversion",
]


def _cli_main(argv: list[str] | None = None) -> int:
    """Command-line entry point for CI/lint runs.

    Usage::

        python -m veilbreakers_terrain.handlers.terrain_scatter_altitude_audit_linter \\
            veilbreakers_terrain/handlers/environment_scatter.py [...more paths]

    Returns non-zero exit on any forbidden pattern found, so the CI job fails
    loudly. If no paths are given, lints the canonical scatter handlers.
    """
    import sys
    from pathlib import Path

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _handlers_dir = Path(__file__).resolve().parent
        args = [
            str(_handlers_dir / "environment_scatter.py"),
            str(_handlers_dir / "_scatter_engine.py"),
            str(_handlers_dir / "vegetation_system.py"),
        ]

    total_offenders = 0
    for raw_path in args:
        path = Path(raw_path)
        if not path.exists():
            print(f"[altitude-linter] MISSING FILE: {path}", file=sys.stderr)
            total_offenders += 1
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"[altitude-linter] READ FAILED {path}: {exc}", file=sys.stderr)
            total_offenders += 1
            continue
        offenders = audit_scatter_altitude_conversion(src)
        if offenders:
            print(f"[altitude-linter] {path}: {len(offenders)} violation(s)")
            for entry in offenders:
                print(f"  {entry}")
            total_offenders += len(offenders)

    if total_offenders:
        print(
            f"[altitude-linter] FAIL: {total_offenders} violation(s). "
            f"{WORLD_HEIGHT_TRANSFORM_WARNING}",
            file=sys.stderr,
        )
        return 1
    print("[altitude-linter] OK: no forbidden altitude idioms detected.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI glue
    import sys

    sys.exit(_cli_main())
