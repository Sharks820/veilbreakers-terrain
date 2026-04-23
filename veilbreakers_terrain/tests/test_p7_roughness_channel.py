"""Tests for roughness_variation single-writer invariant (REQ-P7-003 / Fix 7.18)."""
from __future__ import annotations

import re
from pathlib import Path


HANDLERS_DIR = Path(__file__).parent.parent / "handlers"

# Only this file is allowed to call stack.set("roughness_variation", ...)
CANONICAL_WRITER = "terrain_roughness_driver.py"

# These files previously wrote the channel but must no longer do so
FORBIDDEN_WRITERS = [
    "terrain_multiscale_breakup.py",
    "terrain_stochastic_shader.py",
]


def _grep_stack_set_roughness(filepath: Path) -> list[int]:
    """Return line numbers where stack.set('roughness_variation') appears."""
    text = filepath.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(r'stack\.set\s*\(\s*["\']roughness_variation["\']')
    return [i + 1 for i, line in enumerate(text.splitlines()) if pattern.search(line)]


def test_no_roughness_write_in_multiscale_breakup():
    """terrain_multiscale_breakup must not write roughness_variation to the stack."""
    f = HANDLERS_DIR / "terrain_multiscale_breakup.py"
    hits = _grep_stack_set_roughness(f)
    assert hits == [], (
        f"terrain_multiscale_breakup.py still calls stack.set('roughness_variation') "
        f"at lines {hits}. Only terrain_roughness_driver.py may write this channel (Fix 7.18)."
    )


def test_no_roughness_write_in_stochastic_shader():
    """terrain_stochastic_shader must not write roughness_variation to the stack."""
    f = HANDLERS_DIR / "terrain_stochastic_shader.py"
    hits = _grep_stack_set_roughness(f)
    assert hits == [], (
        f"terrain_stochastic_shader.py still calls stack.set('roughness_variation') "
        f"at lines {hits}. Only terrain_roughness_driver.py may write this channel (Fix 7.18)."
    )


def test_canonical_writer_still_writes():
    """terrain_roughness_driver.py must still have exactly one write."""
    f = HANDLERS_DIR / CANONICAL_WRITER
    hits = _grep_stack_set_roughness(f)
    assert len(hits) >= 1, (
        "terrain_roughness_driver.py has NO stack.set('roughness_variation') call! "
        "The canonical writer must be preserved."
    )
