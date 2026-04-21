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
