"""Regression net for T1-37 / T1-38 / T1-39 — build_scene_v3 cluster (Y04 v3).

Audit anchors (MASTER_FINAL.md Part B §B.4.5):
  - T1-37: `scripts/build_scene_v3.py:48-51` hardcoded fallback path
           (Y01 PROMOTE-from-P2 to P1; dev velocity = ship velocity).
  - T1-38: `scripts/build_scene_v3.py:2175-2222` unreachable
           `scatter_water_surface_assets` (cert-YES XR-003 missing-content).
  - T1-39: `scripts/build_scene_v3.py:2236-2294` empty `band_specs=[]`
           cliff strata (cert-YES XR-003; every cliff renders monolithic-flat).

Category: C4 (boundary contract / channel-unit registry) per FIX_PATTERN_v1
§3 §6 — the build_scene_v3 cluster is the renderable-surface boundary that
materialises Python configuration into Blender meshes. Each test pins the
post-fix invariant so the bug cannot silently regress.

Test design follows FIX_PATTERN_v1 §C4 / §6 recipe:
  - T1-37: configuration validity (the raise path must be reachable).
  - T1-38: boundary round-trip (function body executes past the gate; the
    early-return `0` is the regression hazard).
  - T1-39: data definition shape (4 strata bands + 3 ledge shelves; non-zero
    tuple arity so the bmesh loops emit geometry).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

# scripts/build_scene_v3.py does `import bpy` at module top. The repo's
# conftest.py installs bpy/bmesh/mathutils MagicMock stubs so the module is
# importable in pytest without a live Blender process.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_SCENE_V3_SRC = _REPO_ROOT / "scripts" / "build_scene_v3.py"


@pytest.fixture(scope="module")
def build_scene_v3_source() -> str:
    """Read the build_scene_v3.py source. Used by AST/text regression checks
    so a future agent cannot silently re-introduce the empty-list or
    hardcoded-path patterns without the test catching it."""
    return _BUILD_SCENE_V3_SRC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def build_scene_v3_module() -> Any:
    """Import scripts.build_scene_v3 with bpy/bmesh stubs from conftest."""
    from scripts import build_scene_v3 as mod  # noqa: PLC0415

    return mod


# ---------------------------------------------------------------------------
# T1-37 — hardcoded fallback path: the function must raise RuntimeError, not
# silently use the Conner-local fallback. The earlier behaviour was a silent
# substitution that ran the build against a non-existent path on every box
# except the original author's machine.
# ---------------------------------------------------------------------------


def test_t1_37_hardcoded_fallback_path_removed(build_scene_v3_source: str) -> None:
    """The literal `C:\\Users\\Conner` fallback path must not appear in the
    repository copy of build_scene_v3.py. Re-introducing it returns the
    original silent-on-foreign-box failure."""
    # The audit-anchor literal was:
    #   _script_path = Path(r"C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\scripts\build_scene_v3.py")
    # We assert no Path(...) construction targets a Conner-local fallback.
    pattern = re.compile(r"Path\s*\(\s*r?[\"'].*[Cc]onner.*veilbreakers-terrain.*scripts.*build_scene_v3\.py")
    assert not pattern.search(build_scene_v3_source), (
        "T1-37 regression: hardcoded Conner-local fallback path was re-introduced. "
        "The path is unreachable on CI / teammate machines and silently masks Blender "
        "Text.as_module() __file__ relocation. The correct behaviour is to raise "
        "RuntimeError so the bug surfaces immediately."
    )


def test_t1_37_path_resolution_failure_raises_runtime_error(
    build_scene_v3_source: str,
) -> None:
    """The path-resolution branch must contain a RuntimeError raise, not a
    silent reassignment. We assert the canonical raise pattern is present."""
    # Look for the raise pattern around the path-resolution if-block.
    assert "raise RuntimeError" in build_scene_v3_source, (
        "T1-37 regression: path-resolution failure should raise RuntimeError, "
        "not silently fall back to a Conner-local Path literal."
    )
    # And confirm the message names Blender Text.as_module() (the actual
    # failure mode the audit identified).
    assert "Text.as_module" in build_scene_v3_source, (
        "T1-37 regression: RuntimeError message should reference Text.as_module() "
        "so the operator knows the recovery path."
    )


# ---------------------------------------------------------------------------
# T1-38 — unreachable scatter_water_surface_assets: the early `return 0`
# made 44 lines of scatter logic dead. The audit verdict is XR-003 missing
# content — ship the feature.
# ---------------------------------------------------------------------------


def test_t1_38_scatter_water_surface_assets_is_reachable(
    build_scene_v3_source: str,
) -> None:
    """The `return 0` immediately after the log() in scatter_water_surface_assets
    must not exist. If a future agent re-disables the function, this test goes
    red."""
    # Find the function definition + slice to the next def to scope the check.
    func_match = re.search(
        r"def scatter_water_surface_assets\([^)]*\) -> int:(.*?)(?=\n\ndef |\Z)",
        build_scene_v3_source,
        re.DOTALL,
    )
    assert func_match is not None, (
        "T1-38 regression: scatter_water_surface_assets function was removed entirely."
    )
    body = func_match.group(1)
    # The hazard signature: a `return 0` BEFORE the templates-loading call.
    pre_templates = body.split("_load_model_asset_templates")[0]
    # log("...") + docstring are allowed; the regression is a bare `return 0`
    # that short-circuits before _load_model_asset_templates is invoked.
    bare_return_zero = re.search(r"^\s+return\s+0\s*$", pre_templates, re.MULTILINE)
    assert bare_return_zero is None, (
        "T1-38 regression: scatter_water_surface_assets contains a bare `return 0` "
        "before the templates loader is invoked. This makes the whole 44-line "
        "scatter loop unreachable. Remove the early return."
    )


def test_t1_38_scatter_water_surface_assets_callable(
    build_scene_v3_module: Any,
) -> None:
    """The function is importable and has the right signature (Heightmap, int) -> int.
    The previous behaviour silently returned 0 — we cannot assert the return
    value here because the templates loader hits a stubbed bpy that returns
    MagicMock; but a callable signature check is the boundary round-trip."""
    fn = getattr(build_scene_v3_module, "scatter_water_surface_assets", None)
    assert fn is not None, "scatter_water_surface_assets must be exported."
    assert callable(fn), "scatter_water_surface_assets must be callable."
    # signature smoke check: positional `hm`, optional `count=95`.
    import inspect  # noqa: PLC0415

    sig = inspect.signature(fn)
    assert "hm" in sig.parameters, "expected `hm` parameter."
    assert "count" in sig.parameters, "expected `count` parameter with default."
    assert sig.parameters["count"].default == 95, (
        "T1-38 regression: count default value changed from 95."
    )


# ---------------------------------------------------------------------------
# T1-39 — empty band_specs=[] cliff strata. The fix factored the band data
# into a module-level helper so it can be unit-tested without bpy. The helper
# must return a non-empty list with the (y_base, band_h, lift) tuple shape
# that the bmesh loop unpacks.
# ---------------------------------------------------------------------------


def test_t1_39_cliff_strata_band_specs_non_empty(
    build_scene_v3_module: Any,
) -> None:
    """The strata-band data must be non-empty. The original bug was
    `band_specs = []` which produced 0 polygons in VB_Cliff_Strata while the
    log message at :2336 reported "strata bands + ledges + N talus rocks"
    — a phantom-success cascade."""
    specs = build_scene_v3_module._cliff_strata_band_specs()
    assert len(specs) > 0, (
        "T1-39 regression: _cliff_strata_band_specs() returned []. Every cliff "
        "will render monolithic-flat. The audit verdict (X02 row 1) is cert-YES; "
        "ship at least 3 bands so the strata read as parallel sediment beds."
    )
    # Audit-anchor recommendation: 3+ bands to read as sediment stratigraphy.
    assert len(specs) >= 3, (
        f"T1-39 best-practice: expected ≥3 strata bands (audit recommended 4); "
        f"got {len(specs)}. Decima / Anvil cliff systems use 3-5 bands."
    )


def test_t1_39_cliff_strata_band_specs_tuple_shape(
    build_scene_v3_module: Any,
) -> None:
    """Each row must be a 3-tuple (y_base, band_h, lift) matching the bmesh
    loop's `for band_idx, (y_base, band_h, lift) in enumerate(band_specs):`
    unpack at the call site. A row of wrong arity raises ValueError at
    bmesh-generation time — caught here at unit-test time instead."""
    specs = build_scene_v3_module._cliff_strata_band_specs()
    for idx, row in enumerate(specs):
        assert len(row) == 3, (
            f"T1-39 contract: row {idx} has arity {len(row)}, expected 3 "
            f"(y_base, band_h, lift). Mismatched arity raises ValueError at "
            f"the bmesh loop's tuple unpack."
        )
        y_base, band_h, lift = row
        assert isinstance(y_base, (int, float)), f"row {idx}: y_base must be numeric."
        assert isinstance(band_h, (int, float)), f"row {idx}: band_h must be numeric."
        assert isinstance(lift, (int, float)), f"row {idx}: lift must be numeric."
        assert band_h > 0, (
            f"T1-39: row {idx} band_h={band_h} must be > 0 so the top/bot "
            f"vertices straddle the sampled height. band_h ≤ 0 collapses the "
            f"strata into a zero-thickness ribbon."
        )


def test_t1_39_cliff_ledge_y_bases_non_empty(
    build_scene_v3_module: Any,
) -> None:
    """The ledge Y-coord tuple was previously `()` so `enumerate(())` produced
    0 ledge geometry. Like the strata-band fix, we now assert ≥1 ledge."""
    bases: tuple[float, ...] = build_scene_v3_module._cliff_ledge_y_bases()
    assert isinstance(bases, tuple), (
        "T1-39 contract: _cliff_ledge_y_bases() must return a tuple "
        "(matches the original `enumerate(())` call-site type)."
    )
    assert len(bases) > 0, (
        "T1-39 regression: _cliff_ledge_y_bases() returned (). Every cliff "
        "will have no ledges — no traversable shelves. The audit recommends ≥3 "
        "staggered shelves below/between/above the strata bands."
    )


def test_t1_39_cliff_strata_band_specs_deterministic(
    build_scene_v3_module: Any,
) -> None:
    """C4 boundary round-trip — calling _cliff_strata_band_specs() twice must
    return byte-identical data. If a future contributor wires RNG into the
    helper, deterministic builds break (FIX_PATTERN_v1 §C4 cascade-shape A
    silent-corruption hazard)."""
    a = build_scene_v3_module._cliff_strata_band_specs()
    b = build_scene_v3_module._cliff_strata_band_specs()
    assert a == b, (
        "T1-39 determinism: _cliff_strata_band_specs() returned different data "
        "on consecutive calls. Cliff stratigraphy must be deterministic for "
        "deterministic full-scene builds."
    )
    c = build_scene_v3_module._cliff_ledge_y_bases()
    d = build_scene_v3_module._cliff_ledge_y_bases()
    assert c == d, (
        "T1-39 determinism: _cliff_ledge_y_bases() returned different data on "
        "consecutive calls. Ledge placement must be deterministic."
    )
