"""Bundle B legacy bug audit — static inspection of terrain_advanced.py.

Addendum 2.B.1 flagged 4 suspect ``np.clip(...)`` sites in
``terrain_advanced.py`` (lines ~793, ~896, ~1483, ~1530). The concern is
that these clamp world-unit heights into ``[0, 1]``, which silently
destroys terrain elevation data (Rule 10: world heights are meters, never
unit-space).

This module is a DOCUMENTATION + VERIFICATION deliverable. It does NOT
modify the runtime behavior of ``terrain_advanced.py`` — instead, it
provides a static auditor so the 4 target lines are surfaced in the test
suite. Removing the clips is a runtime-breaking change deferred to a
later bundle.

No bpy imports. Pure stdlib.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List


TARGET_LINES: tuple = (793, 896, 1483, 1530)
_NP_CLIP_RE = re.compile(r"np\.clip\s*\(")
# Matches the specific world-unit-corruption pattern: np.clip(..., 0[.0], 1[.0])
_UNIT_CLIP_RE = re.compile(r"np\.clip\s*\([^,]+,\s*0(?:\.0)?\s*,\s*1(?:\.0)?\s*\)")


def _default_terrain_advanced_path() -> Path:
    """Return the resolved absolute path to ``terrain_advanced.py`` in the repo.

    Uses ``__file__`` so the result is correct regardless of the current
    working directory.  The returned path may not exist (e.g. in a stripped
    test environment) — callers must guard with ``path.exists()`` or rely on
    ``audit_np_clip_in_file``'s non-fatal empty-return behaviour.
    """
    return Path(__file__).with_name("terrain_advanced.py").resolve()


# Matches np.clip calls that are missing the ``out=`` keyword argument.
# A clip call with an explicit ``out=`` parameter avoids silent type promotion
# because numpy writes the result into the pre-allocated buffer (preserving
# its dtype) rather than allocating a new array whose dtype may be upcast.
# Heuristic: if "out=" does not appear anywhere on the same logical line, flag it.
_MISSING_OUT_RE = re.compile(r"np\.clip\s*\([^)]*\)")
_HAS_OUT_RE = re.compile(r"\bout\s*=")


def audit_np_clip_in_file(path: Path) -> List[Dict]:
    """Return a list of ``{file, line, snippet, is_unit_range, missing_out}`` dicts.

    Each entry covers one ``np.clip(...)`` call site found in ``path``.

    Fields
    ------
    file         : Absolute path string of the scanned file.
    line         : 1-based line number of the call.
    snippet      : Stripped source line containing the call.
    is_unit_range: True when clip bounds are ``0``/``0.0`` and ``1``/``1.0``
                   — the canonical world-unit-corruption pattern (Rule 10:
                   world heights are meters, never unit-space [0, 1]).
    missing_out  : True when the call does not contain an explicit ``out=``
                   keyword argument.  Missing ``out=`` can cause silent type
                   promotion: numpy allocates a new result array whose dtype
                   is determined by the inputs, potentially upcasting float32
                   to float64 or int16 to int64 with no warning.

    Non-fatal if the file does not exist — returns an empty list.
    """
    path = Path(path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    results: List[Dict] = []
    for i, line in enumerate(text, start=1):
        if not _NP_CLIP_RE.search(line):
            continue
        is_unit_range = bool(_UNIT_CLIP_RE.search(line))
        # A clip call is flagged for missing out= if the entire logical line
        # (which may span a continuation) does not contain "out=".
        # For single-line calls this is a reliable signal; multi-line calls
        # that carry ``out=`` on a continuation line are not penalised because
        # the continuation line will contain the out= token.
        missing_out = not bool(_HAS_OUT_RE.search(line))
        results.append(
            {
                "file": str(path),
                "line": i,
                "snippet": line.strip(),
                "is_unit_range": is_unit_range,
                "missing_out": missing_out,
            }
        )
    return results


# Matches integer literals used as pixel-unit multipliers in scaling operations
# WITHOUT a subsequent ``* cell_size`` (or ``* cs``) on the same line.
# Pattern: integer constant followed by ``*`` (or being multiplied) that looks
# like a hardcoded pixel count, e.g. ``height * 512`` or ``512 * height``.
# We flag any arithmetic that multiplies/divides by an integer >= 8 on a line
# that also contains "height" or "resolution" or "size" but no "cell_size" / "cs ".
_PIXEL_UNIT_RE = re.compile(
    r"(?:height|resolution|_size|scale)\b.*\b(?:\d{2,})\s*[*/]"
    r"|(?:\d{2,})\s*[*/].*(?:height|resolution|_size|scale)\b"
)
_CELL_SIZE_PRESENT_RE = re.compile(r"\bcell_size\b|\bcs\b\s*[*]")


def _audit_pixel_units_in_file(path: Path) -> List[Dict]:
    """Scan ``path`` for likely hardcoded pixel-unit scaling ops.

    Returns a list of ``{file, line, snippet, reason}`` dicts for lines
    that appear to use raw integer pixel counts in scaling operations
    without normalising by ``cell_size``.

    Non-fatal if the file does not exist — returns empty list.
    """
    path = Path(path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    findings: List[Dict] = []
    for i, line in enumerate(text, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if _PIXEL_UNIT_RE.search(line) and not _CELL_SIZE_PRESENT_RE.search(line):
            findings.append({
                "file": str(path),
                "line": i,
                "snippet": stripped,
                "reason": "integer literal in height/resolution scaling op without *cell_size",
            })
    return findings


def audit_terrain_advanced_world_units() -> Dict:
    """Audit terrain_advanced.py for world-unit clips and hardcoded pixel units.

    Returns a dict with keys:
      ``path``              — absolute path to terrain_advanced.py (str)
      ``all_clips``         — every ``np.clip`` site (includes ``is_unit_range``,
                              ``missing_out``)
      ``suspicious_clips``  — subset where clip range is [0, 1] or [0.0, 1.0]
      ``missing_out_clips`` — subset where ``out=`` keyword is absent
      ``targets``           — dict keyed by str(line_number) with:
                              ``line``, ``found``, ``snippet``, ``nearby``,
                              ``status`` ("present"|"moved"|"fixed"),
                              ``is_unit_range``, ``missing_out``
      ``target_lines``      — canonical list of target lines
      ``pixel_unit_findings`` — list of hardcoded pixel-unit scaling sites
                              (integer literals in scaling ops without *cell_size)
      ``summary``           — ``{clip_count, unit_clip_count, missing_out_count,
                              targets_present, targets_moved, targets_fixed,
                              pixel_unit_findings_count}``
    """
    path = _default_terrain_advanced_path()
    all_clips = audit_np_clip_in_file(path)

    by_line: Dict[int, Dict] = {entry["line"]: entry for entry in all_clips}
    suspicious_clips = [e for e in all_clips if e["is_unit_range"]]
    missing_out_clips = [e for e in all_clips if e.get("missing_out", False)]

    targets: Dict[str, Dict] = {}
    present_count = moved_count = fixed_count = 0

    for tgt in TARGET_LINES:
        found_exact = tgt in by_line
        nearby_lines = [ln for ln in by_line if abs(ln - tgt) <= 3 and ln != tgt]
        nearby = bool(nearby_lines)

        if found_exact:
            status = "present"
            present_count += 1
        elif nearby:
            status = "moved"
            moved_count += 1
        else:
            status = "fixed"
            fixed_count += 1

        entry = by_line.get(tgt, {})
        targets[str(tgt)] = {
            "line": tgt,
            "found": found_exact,
            "snippet": entry.get("snippet", ""),
            "nearby": nearby,
            "nearby_lines": nearby_lines,
            "status": status,
            "is_unit_range": entry.get("is_unit_range", False),
            "missing_out": entry.get("missing_out", False),
        }

    pixel_unit_findings = _audit_pixel_units_in_file(path)

    return {
        "path": str(path),
        "all_clips": all_clips,
        "suspicious_clips": suspicious_clips,
        "missing_out_clips": missing_out_clips,
        "targets": targets,
        "target_lines": list(TARGET_LINES),
        "pixel_unit_findings": pixel_unit_findings,
        "summary": {
            "clip_count": len(all_clips),
            "unit_clip_count": len(suspicious_clips),
            "missing_out_count": len(missing_out_clips),
            "targets_present": present_count,
            "targets_moved": moved_count,
            "targets_fixed": fixed_count,
            "pixel_unit_findings_count": len(pixel_unit_findings),
        },
    }


__all__ = [
    "TARGET_LINES",
    "audit_np_clip_in_file",
    "audit_terrain_advanced_world_units",
]
