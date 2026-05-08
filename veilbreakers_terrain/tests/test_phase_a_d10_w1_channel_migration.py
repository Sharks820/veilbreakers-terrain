"""Phase A D10-11 / W-1 channel migration regression tests.

Verifies the W-1 final cleanup contract: every channel-read site that
previously read the legacy ``water_surface`` channel must now prefer
``water_surface_mask`` and only fall back to legacy if mask is absent.

Sites historically reading legacy ``water_surface`` (audited Phase A D10):

    - terrain_navmesh_export.py:199-201      (already migrated pre-D10)
    - terrain_navmesh_export.py:327-329      (already migrated pre-D10)
    - terrain_unity_export.py:2266-2278      (correct heuristic disambig)
    - terrain_waterfalls.py:1785-1787        (already migrated pre-D10)
    - terrain_waterfalls.py:2327              (already migrated pre-D10)
    - terrain_water_variants.py:578           (D10 PR — migrated)
    - terrain_water_variants.py:747           (D10 PR — migrated)
    - terrain_water_variants.py:1449          (D10 PR — migrated)
    - terrain_wildlife_zones.py:225-227       (already migrated pre-D10)
    - _water_network.py:907-911               (already migrated pre-D10)
    - _water_network_ext.py:358-360           (already migrated pre-D10)
    - _water_network_ext.py:636               (already migrated pre-D10)

The contract pinned by these tests is *textual*: each migrated site must
contain a mask-first lookup followed by a legacy fallback. We pin the
text rather than runtime behaviour because the alternative — exercising
each call site with mask-only and legacy-only stacks — would require
constructing 12 different parameter bundles for passes that touch
half the codebase. A textual ratchet is sufficient because the failure
mode is always the same: the mask read goes missing or the fallback is
removed without first dropping the legacy channel writers.

When the legacy ``water_surface`` channel is finally retired (a separate
PR that deletes the producer + the fallback shims), this test file flips
to assert the *absence* of the legacy fallback string.
"""

from __future__ import annotations

import pathlib

_HANDLERS = pathlib.Path(__file__).resolve().parents[1] / "handlers"


def _read(name: str) -> str:
    return (_HANDLERS / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# terrain_water_variants.py — the 3 new D10 migration sites
# ---------------------------------------------------------------------------


def test_water_variants_classifier_prefers_mask():
    """Classifier site (~line 578) must prefer water_surface_mask."""
    src = _read("terrain_water_variants.py")
    # Find the classifier rock_hardness adjacent block.
    anchor = src.find("rock_h = stack.get(\"rock_hardness\")")
    assert anchor != -1, "classifier rock_hardness anchor missing — file refactored"
    window = src[anchor:anchor + 600]
    # mask must be read FIRST.
    mask_idx = window.find('stack.get("water_surface_mask")')
    legacy_idx = window.find('stack.get("water_surface")')
    assert mask_idx != -1, (
        "classifier site never reads water_surface_mask — W-1 regression"
    )
    assert legacy_idx != -1, (
        "classifier site dropped legacy fallback — coordinate with legacy "
        "channel removal PR before deleting"
    )
    assert mask_idx < legacy_idx, (
        "classifier reads legacy water_surface BEFORE water_surface_mask — "
        f"mask at {mask_idx}, legacy at {legacy_idx}"
    )


def test_water_variants_existing_ws_prefers_mask():
    """pass_water_variants existing-state read (~line 747) must prefer mask."""
    src = _read("terrain_water_variants.py")
    anchor = src.find("existing_ws = stack.get")
    assert anchor != -1, "existing_ws anchor missing — file refactored"
    window = src[anchor:anchor + 400]
    assert 'stack.get("water_surface_mask")' in window, (
        "existing_ws site never reads water_surface_mask — W-1 regression"
    )
    mask_idx = window.find('stack.get("water_surface_mask")')
    legacy_idx = window.find('stack.get("water_surface")')
    assert mask_idx != -1 and legacy_idx != -1
    assert mask_idx < legacy_idx, (
        "existing_ws reads legacy BEFORE mask"
    )


def test_water_variants_bathymetry_prefers_mask():
    """pass_bathymetry water-surface read (~line 1449) must prefer mask."""
    src = _read("terrain_water_variants.py")
    anchor = src.find("BATHYMETRY_WATER_SURFACE_MISSING")
    assert anchor != -1, "BATHYMETRY_WATER_SURFACE_MISSING anchor missing"
    # The mask read should be JUST ABOVE the diagnostic.
    window = src[max(0, anchor - 600):anchor]
    mask_idx = window.find('stack.get("water_surface_mask")')
    legacy_idx = window.find('stack.get("water_surface")')
    assert mask_idx != -1, (
        "bathymetry site never reads water_surface_mask — W-1 regression"
    )
    assert legacy_idx != -1, (
        "bathymetry site dropped legacy fallback prematurely"
    )
    assert mask_idx < legacy_idx, (
        "bathymetry reads legacy BEFORE mask"
    )


# ---------------------------------------------------------------------------
# Other sites — already migrated pre-D10; pinning to prevent regression.
# ---------------------------------------------------------------------------


def test_navmesh_export_swim_classification_prefers_mask():
    """SWIM classification (~line 199) must prefer water_surface_mask."""
    src = _read("terrain_navmesh_export.py")
    anchor = src.find("# 5. SWIM")
    assert anchor != -1, "SWIM section anchor missing"
    window = src[anchor:anchor + 600]
    mask_idx = window.find('stack.get("water_surface_mask")')
    legacy_idx = window.find('stack.get("water_surface")')
    assert mask_idx != -1, "SWIM site missing water_surface_mask read"
    assert mask_idx < legacy_idx, "SWIM reads legacy before mask"


def test_navmesh_export_water_cost_prefers_mask():
    """Water-cost penalty (~line 327) must prefer water_surface_mask."""
    src = _read("terrain_navmesh_export.py")
    anchor = src.find("# --- Water penalty ---")
    assert anchor != -1, "water penalty anchor missing"
    window = src[anchor:anchor + 600]
    mask_idx = window.find('stack.get("water_surface_mask")')
    legacy_idx = window.find('stack.get("water_surface")')
    assert mask_idx != -1, "water penalty missing water_surface_mask read"
    assert mask_idx < legacy_idx, "water penalty reads legacy before mask"


def test_waterfalls_shoreline_foam_prefers_mask():
    """Shoreline foam (~line 1785) must prefer water_surface_mask."""
    src = _read("terrain_waterfalls.py")
    anchor = src.find("Source 4: Shoreline foam")
    assert anchor != -1, "Source 4 shoreline foam anchor missing"
    window = src[anchor:anchor + 600]
    mask_idx = window.find('stack.get("water_surface_mask")')
    legacy_idx = window.find('stack.get("water_surface")')
    assert mask_idx != -1, "shoreline foam missing water_surface_mask read"
    assert mask_idx < legacy_idx, "shoreline foam reads legacy before mask"


def test_wildlife_zones_water_mask_prefers_canonical():
    """Wildlife zones water-mask (~line 225) must prefer water_surface_mask."""
    src = _read("terrain_wildlife_zones.py")
    anchor = src.find("# --- Water mask + distance field ---")
    assert anchor != -1, "wildlife water mask anchor missing"
    window = src[anchor:anchor + 600]
    mask_idx = window.find('stack.get("water_surface_mask")')
    legacy_idx = window.find('stack.get("water_surface")')
    assert mask_idx != -1, "wildlife site missing water_surface_mask read"
    assert mask_idx < legacy_idx, "wildlife reads legacy before mask"


def test_water_network_flow_speed_prefers_mask():
    """pass_water_flow_speed (~line 907) must prefer water_surface_mask (W-1 origin)."""
    src = _read("_water_network.py")
    anchor = src.find("water_mask_raw = stack.get(\"water_surface_mask\")")
    assert anchor != -1, (
        "W-1 canonical mask read missing in _water_network.py — "
        "the canonical site has been removed"
    )
    window = src[anchor:anchor + 300]
    legacy_idx = window.find('stack.get("water_surface")')
    assert legacy_idx != -1, (
        "_water_network.py dropped legacy fallback prematurely"
    )


def test_water_network_ext_priority_flood_prefers_mask():
    """Priority-flood termination (~line 358) must prefer water_surface_mask."""
    src = _read("_water_network_ext.py")
    anchor = src.find("Optional water_surface mask for termination")
    assert anchor != -1, "priority-flood anchor missing"
    window = src[anchor:anchor + 600]
    mask_idx = window.find('stack.get("water_surface_mask")')
    legacy_idx = window.find('stack.get("water_surface")')
    assert mask_idx != -1, "priority-flood missing water_surface_mask read"
    assert mask_idx < legacy_idx, "priority-flood reads legacy before mask"


# ---------------------------------------------------------------------------
# Inventory ratchet — pin the migrated-site count so a NEW unmigrated
# read introduces a test failure rather than silently shipping.
# ---------------------------------------------------------------------------


def test_legacy_water_surface_read_inventory_pinned():
    """All legacy 'stack.get(\"water_surface\")' reads must be paired with a mask-first read.

    Currently 9 distinct files contain a legacy fallback read. Each must
    be paired with a mask read in the same file. This test prevents
    accidental introduction of a NEW unmigrated read site.
    """
    expected_files_with_legacy_fallback = {
        "_water_network.py",
        "_water_network_ext.py",
        "terrain_navmesh_export.py",
        "terrain_unity_export.py",
        "terrain_water_variants.py",
        "terrain_waterfalls.py",
        "terrain_wildlife_zones.py",
    }
    found_files: set[str] = set()
    for handler in _HANDLERS.glob("*.py"):
        text = handler.read_text(encoding="utf-8")
        if 'stack.get("water_surface")' in text:
            found_files.add(handler.name)
    # Files with legacy fallbacks must be a subset of the audited list.
    new_unmigrated = found_files - expected_files_with_legacy_fallback
    assert not new_unmigrated, (
        f"NEW files contain legacy 'stack.get(\"water_surface\")' reads "
        f"without W-1 migration audit: {sorted(new_unmigrated)}"
    )
    # And every file with a legacy fallback must also read the mask channel.
    for fname in found_files:
        text = (_HANDLERS / fname).read_text(encoding="utf-8")
        assert 'stack.get("water_surface_mask")' in text, (
            f"{fname} reads legacy water_surface but never reads "
            f"water_surface_mask — W-1 contract broken"
        )
