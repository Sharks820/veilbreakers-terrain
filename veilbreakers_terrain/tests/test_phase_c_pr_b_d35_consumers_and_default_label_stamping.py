"""PR-B (cross-audit P0 2026-05-09): D35 consumer wiring + label_stamping default-on.

Pins:
1. ``vb_TWI`` is consumed by ``pass_procedural_grass``: when present,
   replaces ``drainage`` as the moisture source for wetness affinity
   masks (TWI = ln(area / tan(slope)) is the canonical AAA wetland
   proxy used by Horizon FW + Death Stranding).  Closes Phase C D35
   "produced but no consumer" gap (Codex audit + Opus fleet Agent 1/2/4).
2. Default-on ``label_stamping`` for AAA quality profile.  PR #57
   shipped ``pass_label_stamping`` opt-in via
   ``composition_hints["label_stamping"]=True``, OFF by default —
   meaning the structural label investment was shelfware in every
   default AAA run (Agent 5 verifier finding).  Now flipped: AAA
   quality profile defaults to ON; preview / mobile / low stay OFF
   for byte-identical legacy fixtures.
"""
from __future__ import annotations

from typing import Any, cast

import numpy as np
from numpy.typing import NDArray


FloatArray = NDArray[np.float32]


def _intent(rows: int = 16, *, scene_read: bool = True, **hints: Any) -> Any:
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
    )
    return TerrainIntentState(
        seed=42,
        region_bounds=BBox(0.0, 0.0, float(rows), float(rows)),
        tile_size=rows,
        cell_size=1.0,
        composition_hints=dict(hints),
        scene_read=cast(Any, object()) if scene_read else None,
        quality_profile=str(hints.pop("quality_profile", "aaa_open_world")),
    )


# ---------------------------------------------------------------------------
# 1. vb_TWI -> procedural_grass moisture
# ---------------------------------------------------------------------------


def test_pass_procedural_grass_prefers_vb_twi_when_present():
    """When vb_TWI is on the stack, pass_procedural_grass uses it as the
    wetness affinity source instead of drainage. Verified by injecting
    diverging TWI and drainage fields with a wetland-affinity species
    and asserting the produced grass density tracks the TWI signal,
    not drainage.
    """
    from veilbreakers_terrain.handlers.procedural_grass import (
        ProceduralGrassSystem,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import (
        TerrainMaskStack,
    )

    rows = 16
    h = np.zeros((rows, rows), dtype=np.float32)
    stack = TerrainMaskStack(
        tile_size=rows, cell_size=1.0,
        world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0, height=h,
    )
    # Set drainage HIGH everywhere (would predict wetland everywhere
    # under old code) and vb_TWI HIGH only on the right half (the
    # signal we want to track). Using >= 8 puts the boundary at idx 8.
    drainage = np.ones((rows, rows), dtype=np.float32) * 0.9
    twi = np.zeros((rows, rows), dtype=np.float32)
    twi[:, 8:] = 5.0  # large positive TWI on right half only
    stack.set("drainage", drainage, "test_setup")
    stack.set("vb_TWI", twi, "test_setup")
    # Slope and biome required by pass_procedural_grass surface checks.
    stack.set("slope", np.zeros((rows, rows), dtype=np.float32), "test_setup")
    biome_id = np.zeros((rows, rows), dtype=np.int32)
    stack.set("biome_id", biome_id, "test_setup")

    # Synthesize a wetland species without biome restrictions so the
    # test focuses cleanly on the moisture-source behaviour. Density is
    # set low enough that target_count < grid_size, otherwise
    # _sample_positions falls back to uniform sampling (replace=False
    # with target_count == nonzero ignores weights).
    from veilbreakers_terrain.handlers.procedural_grass import GrassSpecies
    wetland_species = (
        GrassSpecies(
            name="test_wetland",
            wetness_affinity=0.95,
            density_per_sqm=0.2,
            slope_max_deg=90.0,
            biomes=("*",),
            min_spacing_m=0.0,  # disable poisson thinning so we don't lose right-half samples
        ),
    )

    system = ProceduralGrassSystem(rng_seed=42)
    records = system.generate_grass_placement(
        stack,
        wetland_species,
        1.0,
        sdf_road_min_m=0.0,
        sdf_cliff_min_m=0.0,
        water_edge_min_m=0.0,
        max_instances_per_species=10_000,
    )

    assert records, "procedural_grass should produce some wetland records given high TWI"

    # All wetland-species records should be on the right half (cols >= 8)
    # because that's where vb_TWI is high. If drainage were used (uniform
    # 0.9), records would scatter across the whole tile.
    right_half_count = sum(
        1 for r in records if r.position_world[0] >= 8.0
    )
    total = len(records)
    right_share = right_half_count / float(total)
    assert right_share >= 0.85, (
        f"vb_TWI signal (right half) should drive >= 85% of wetland-species "
        f"placements; got {right_share:.2%} ({right_half_count}/{total})"
    )


def test_pass_procedural_grass_falls_back_to_drainage_when_no_vb_twi():
    """Backwards compatibility: when vb_TWI is absent, behaviour matches
    legacy drainage-driven wetness affinity. Pre-PR-B fixtures with no
    D35 producer should emit identical results."""
    from veilbreakers_terrain.handlers.procedural_grass import (
        ProceduralGrassSystem,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import (
        TerrainMaskStack,
    )

    rows = 16
    h = np.zeros((rows, rows), dtype=np.float32)
    stack = TerrainMaskStack(
        tile_size=rows, cell_size=1.0,
        world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0, height=h,
    )
    # Drainage HIGH on the right half (legacy signal we want to track).
    drainage = np.zeros((rows, rows), dtype=np.float32)
    drainage[:, 8:] = 0.9
    stack.set("drainage", drainage, "test_setup")
    # NO vb_TWI on the stack — the fallback path should engage.
    stack.set("slope", np.zeros((rows, rows), dtype=np.float32), "test_setup")
    stack.set("biome_id", np.zeros((rows, rows), dtype=np.int32), "test_setup")

    from veilbreakers_terrain.handlers.procedural_grass import GrassSpecies
    wetland_species = (
        GrassSpecies(
            name="test_wetland",
            wetness_affinity=0.95,
            density_per_sqm=0.2,
            slope_max_deg=90.0,
            biomes=("*",),
            min_spacing_m=0.0,
        ),
    )

    system = ProceduralGrassSystem(rng_seed=42)
    records = system.generate_grass_placement(
        stack,
        wetland_species,
        1.0,
        sdf_road_min_m=0.0,
        sdf_cliff_min_m=0.0,
        water_edge_min_m=0.0,
        max_instances_per_species=10_000,
    )

    assert records, "fallback drainage path should still produce records"
    # Right-half share should still be high under drainage signal
    right_share = sum(
        1 for r in records if r.position_world[0] >= 8.0
    ) / float(len(records))
    assert right_share >= 0.85, (
        f"drainage fallback should still drive >= 85% on right half; "
        f"got {right_share:.2%}"
    )


# ---------------------------------------------------------------------------
# 2. Default-on label_stamping for AAA quality
# ---------------------------------------------------------------------------


def test_label_stamping_scheduled_by_default_on_aaa_quality():
    """PR-B: AAA quality profile defaults composition_hints['label_stamping']
    to True so pass_label_stamping is scheduled in the default sequence."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    seq = build_default_pass_sequence(_intent(quality_profile="aaa_open_world"))
    assert "label_stamping" in seq, (
        f"label_stamping must be scheduled by default for AAA quality; "
        f"got: {[name for name in seq if 'label' in name]}"
    )


def test_label_stamping_skipped_for_preview_quality():
    """Backwards compatibility: preview / mobile / low quality profiles
    keep label_stamping OFF so existing legacy fixtures stay
    byte-identical."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    seq_preview = build_default_pass_sequence(_intent(quality_profile="preview"))
    assert "label_stamping" not in seq_preview, (
        f"label_stamping must be OFF for preview quality; got: {seq_preview}"
    )
    seq_mobile = build_default_pass_sequence(_intent(quality_profile="mobile"))
    assert "label_stamping" not in seq_mobile, (
        f"label_stamping must be OFF for mobile quality; got: {seq_mobile}"
    )


def test_label_stamping_explicit_hint_overrides_default():
    """Caller can still explicitly opt OUT of label_stamping even on AAA
    by passing composition_hints['label_stamping']=False."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    seq = build_default_pass_sequence(
        _intent(quality_profile="aaa_open_world", label_stamping=False)
    )
    assert "label_stamping" not in seq, (
        "explicit composition_hints['label_stamping']=False must override "
        "the AAA default"
    )


def test_label_stamping_explicit_hint_overrides_preview_off():
    """Caller can still explicitly opt IN to label_stamping on preview
    by passing composition_hints['label_stamping']=True."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    seq = build_default_pass_sequence(
        _intent(quality_profile="preview", label_stamping=True)
    )
    assert "label_stamping" in seq, (
        "explicit composition_hints['label_stamping']=True must override "
        "the preview default"
    )
