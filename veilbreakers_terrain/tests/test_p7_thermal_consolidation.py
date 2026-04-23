"""Tests for thermal erosion consolidation (REQ-P7-006 / Fix 7.6 / CONFLICT-11)."""
from __future__ import annotations

import re
import time
from pathlib import Path

import numpy as np

from veilbreakers_terrain.handlers._terrain_erosion import (
    apply_thermal_erosion as canonical_thermal,
)
from veilbreakers_terrain.handlers.terrain_advanced import (
    apply_thermal_erosion as advanced_thermal,
)


HANDLERS_DIR = Path(__file__).parent.parent / "handlers"


def _make_test_dem(size: int = 8, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.uniform(0.0, 1.0, (size, size)).astype(np.float32)


def test_returns_list_of_lists():
    """terrain_advanced.apply_thermal_erosion must return list-of-lists (legacy compat)."""
    dem = _make_test_dem(4)
    result = advanced_thermal(dem, iterations=2)
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert isinstance(result[0], list), f"Expected list-of-lists, got list-of-{type(result[0])}"


def test_delegation_parity():
    """advanced and canonical implementations must agree within 1e-4."""
    dem = _make_test_dem(8)
    # canonical uses degrees; advanced legacy talus 0.5 => arctan(0.5) => 26.57 deg
    import math
    deg = math.degrees(math.atan(0.5))
    ref = canonical_thermal(dem.copy(), iterations=5, talus_angle=deg)
    got = np.array(advanced_thermal(dem.copy(), iterations=5, talus_angle=0.5))
    np.testing.assert_allclose(
        got, ref, atol=1e-4,
        err_msg="advanced and canonical thermal erosion diverge beyond tolerance"
    )


def test_talus_conversion_no_error():
    """Legacy raw talus_angle=0.5 must not raise."""
    dem = _make_test_dem(4)
    result = advanced_thermal(dem, iterations=1, talus_angle=0.5)
    assert result is not None


def test_canonical_speed():
    """Canonical impl on 32x32 must complete in < 5 seconds (no Python triple loop)."""
    dem = _make_test_dem(32)
    t0 = time.perf_counter()
    canonical_thermal(dem, iterations=20)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"Canonical thermal took {elapsed:.2f}s (expected < 5s)"


def test_no_python_loop_in_advanced_thermal():
    """terrain_advanced.apply_thermal_erosion must not contain a Python triple-for loop."""
    src = (HANDLERS_DIR / "terrain_advanced.py").read_text(encoding="utf-8")
    # Find the function body
    fn_match = re.search(
        r"def apply_thermal_erosion\b.*?(?=\ndef |\Z)",
        src,
        re.DOTALL,
    )
    assert fn_match, "apply_thermal_erosion not found in terrain_advanced.py"
    body = fn_match.group()
    # A Python triple-nested loop would have "for r in range" and "for c in range"
    loop_pattern = re.compile(r"for\s+\w+\s+in\s+range\s*\(.*rows", re.DOTALL)
    assert not loop_pattern.search(body), (
        "Python triple-loop still present in terrain_advanced.apply_thermal_erosion. "
        "Should delegate to _terrain_erosion canonical impl (Fix 7.6)."
    )
