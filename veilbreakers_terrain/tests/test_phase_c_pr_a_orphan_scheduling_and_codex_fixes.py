"""PR-A (cross-audit P0 2026-05-09): orphan scheduling + Codex P1 water fixes.

Pins:
1. pass_water_flow_speed scheduled in default sequence — closes 5 dead
   stack.get("flow_speed") reads in terrain_waterfalls.py.
2. pass_river_convergence scheduled — produces river_mouth_mask /
   confluence_foam / delta_fan_direction (consumed by Unity export +
   waterfall foam shader once wired).
3. B15-P0-32: banded_macro declares requires_channels=("height",) so the
   pass cannot fire before any height producer in parallel waves.
4. Codex PR-60 P1-A: pass_water_variants region merge recomputes
   spill-rim on the FULL merged mask so wet bodies that span region
   boundaries get a consistent wsfm.
5. Codex PR-60 P1-B: pass_bathymetry prefers water_surface_mask when
   present (absolute-WSE branch), so dry below-zero terrain no longer
   falsely gets flagged wet.
"""
from __future__ import annotations

from typing import Any, cast

import numpy as np
from numpy.typing import NDArray


FloatArray = NDArray[np.float32]


def _intent_with_scene(rows: int = 16, cols: int = 16, **hints: Any) -> Any:
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
    )
    return TerrainIntentState(
        seed=42,
        region_bounds=BBox(0.0, 0.0, float(rows), float(cols)),
        tile_size=rows,
        cell_size=1.0,
        composition_hints=dict(hints),
        scene_read=cast(Any, object()),
        quality_profile="aaa_open_world",
    )


def test_pass_water_flow_speed_scheduled_when_scene_read():
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    seq = build_default_pass_sequence(_intent_with_scene())
    assert "pass_water_flow_speed" in seq, (
        f"pass_water_flow_speed must be scheduled in scene-read pipeline; "
        f"sequence: {seq}"
    )
    fs_idx = seq.index("pass_water_flow_speed")
    if "pass_water_depth" in seq:
        assert fs_idx > seq.index("pass_water_depth")
    if "waterfalls" in seq:
        assert fs_idx < seq.index("waterfalls")


def test_pass_river_convergence_scheduled_when_scene_read():
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    seq = build_default_pass_sequence(_intent_with_scene())
    assert "pass_river_convergence" in seq
    rc_idx = seq.index("pass_river_convergence")
    if "pass_water_depth" in seq:
        assert rc_idx > seq.index("pass_water_depth")
    if "pass_water_flow_speed" in seq:
        assert rc_idx > seq.index("pass_water_flow_speed")


def test_pass_water_flow_speed_not_scheduled_without_scene_read():
    """The orphan should ONLY be scheduled in scene-read pipelines —
    headless / pure-noise pipelines don't have flow_accumulation."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
    )

    intent_no_scene = TerrainIntentState(
        seed=42,
        region_bounds=BBox(0.0, 0.0, 16.0, 16.0),
        tile_size=16,
        cell_size=1.0,
        composition_hints={},
        scene_read=None,
    )
    seq = build_default_pass_sequence(intent_no_scene)
    assert "pass_water_flow_speed" not in seq
    assert "pass_river_convergence" not in seq


def test_b15_p0_32_banded_macro_requires_height_channel():
    """B15-P0-32 fix: banded_macro reads stack.height (line ~1024 of
    terrain_banded.py) but previously declared requires_channels=().
    The empty declaration was a wave-0 parallel race risk: a parallel
    scheduler honoring the contract could fire banded_macro before any
    height producer, silently corrupting the composition.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )
    from veilbreakers_terrain.handlers.terrain_banded import (
        register_bundle_g_passes,
    )
    register_default_passes()
    register_bundle_g_passes()
    defn = TerrainPassController.PASS_REGISTRY.get("banded_macro")
    assert defn is not None, "banded_macro must be registered"
    assert "height" in defn.requires_channels, (
        f"banded_macro must declare requires_channels=('height',) so the "
        f"parallel scheduler honors the producer-consumer edge. "
        f"Got: {defn.requires_channels}"
    )


def test_codex_p1_a_region_merge_recomputes_full_spill_rim():
    """Codex PR-60 P1-A: when pass_water_variants is called with a
    region, after merging the slice mask into the existing tile-wide
    mask, the helper must recompute spill-rim on the FULL merged mask
    so wet bodies spanning region boundaries get a consistent wsfm.

    This test verifies the helper's correctness on a wet body that
    spans the full grid: spill rim must be the highest dry rim across
    the entire body, not a per-region partial rim.
    """
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        _compute_spill_rim_elevation,
    )

    h = np.full((8, 8), 5.0, dtype=np.float32)
    h[:, 0] = 20.0
    h[:, -1] = 25.0

    wet_full = np.zeros_like(h, dtype=bool)
    wet_full[1:7, 1:7] = True

    out = _compute_spill_rim_elevation(h, wet_full)

    # max rim = 25.0; body height max = 5.0; spill rim = 25.0.
    assert np.all(out[wet_full] == 25.0), (
        f"spill-rim must use the highest dry rim across the full body; got: {out[wet_full]}"
    )


def test_codex_p1_b_bathymetry_prefers_water_surface_mask_when_present():
    """Codex PR-60 P1-B: pass_bathymetry's absolute-WSE branch should
    prefer water_surface_mask when present, so dry below-zero terrain
    no longer falsely gets flagged wet by the ``ws >= h - 0.05``
    heuristic.

    Construct a stack where:
    - terrain has below-zero cells (e.g., basin at h=-5)
    - WSE has been set elsewhere to something > 0 in those cells
    - water_surface_mask explicitly says those cells are DRY
    The fix: bathymetry must respect the mask, not the WSE heuristic.
    """
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        pass_bathymetry,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    # Stress fixture (Verifier 1 finding: prior fixture was tautological —
    # heuristic and mask agreed). Construct a case where the heuristic
    # WOULD say wet but the mask says DRY: stale WSE much higher than
    # terrain everywhere with mask=0 in only a sub-region.
    h = np.full((8, 8), 10.0, dtype=np.float32)
    # Stale WSE = 15 across the entire tile (the prior heuristic
    # 15 >= 10 - 0.05 = 9.95 evaluates True everywhere → flags ALL cells
    # wet, even on the high terrain). The mask is the source of truth.
    wse = np.full((8, 8), 15.0, dtype=np.float32)

    stack = TerrainMaskStack(
        tile_size=8, cell_size=1.0,
        world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0, height=h,
    )
    stack.set("water_surface_elevation_m", wse, "test_setup")
    # Canonical mask: ONLY a 2x2 region in the corner is wet.
    mask = np.zeros((8, 8), dtype=np.float32)
    mask[0:2, 0:2] = 1.0
    stack.set("water_surface_mask", mask, "test_setup")
    stack.set("water_surface", mask.copy(), "test_setup")

    intent = TerrainIntentState(
        seed=42, region_bounds=BBox(0.0, 0.0, 8.0, 8.0),
        tile_size=8, cell_size=1.0, composition_hints={},
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    pass_bathymetry(state, region=None)

    bathy = stack.bathymetry
    zone = stack.water_depth_zone
    assert bathy is not None and zone is not None
    # Cells flagged DRY by the mask must be dry — even though stale
    # WSE=15 vs h=10 satisfies the OLD `ws >= h - 0.05` heuristic.
    assert bathy[5, 5] == 0.0, (
        f"dry cell at (5,5) must be dry per mask; old heuristic would "
        f"have made it wet (ws=15 >= h=10-0.05); got bathy={bathy[5,5]}"
    )
    assert zone[5, 5] == 0, (
        f"dry cell must be zone=0; old heuristic would force wade/swim/dive; "
        f"got zone={zone[5,5]}"
    )
    # Wet cells (mask=1) must have proper bathymetry.
    # bathy = max(0, ws - h) = max(0, 15 - 10) = 5.0
    assert abs(float(bathy[0, 0]) - 5.0) < 1e-5, (
        f"wet cell at (0,0) must have bathymetry = ws-h = 5; got {bathy[0,0]}"
    )
