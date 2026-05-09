"""PR-E (cross-audit P0 2026-05-09): vegetation orphan scheduling.

Pins:
- vegetation_depth scheduled in default sequence after materials_v2 and
  before scatter_intelligent. Produces detail_density which scatter
  consumes via overrides.
- emergent_grass scheduled likewise. Produces grass_density_map which
  procedural_grass consumes.

Closes Agent 2 verifier finding: "vegetation_depth + emergent_grass
registered but never scheduled."
"""
from __future__ import annotations

from typing import Any, cast


def _intent(scene_read: bool = True, **hints: Any) -> Any:
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
    )
    quality_profile = str(hints.pop("quality_profile", "aaa_open_world"))
    return TerrainIntentState(
        seed=42,
        region_bounds=BBox(0.0, 0.0, 16.0, 16.0),
        tile_size=16,
        cell_size=1.0,
        composition_hints=dict(hints),
        scene_read=cast(Any, object()) if scene_read else None,
        quality_profile=quality_profile,
    )


def test_vegetation_depth_scheduled_when_scene_read():
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    seq = build_default_pass_sequence(_intent())
    assert "vegetation_depth" in seq, (
        f"vegetation_depth must be scheduled in scene-read pipeline; got: {seq}"
    )
    # Must run AFTER materials_v2 (its consumer scatter_intelligent reads
    # detail_density which vegetation_depth overrides).
    assert seq.index("vegetation_depth") > seq.index("materials_v2")
    # Must run BEFORE scatter_intelligent (the consumer).
    if "scatter_intelligent" in seq:
        assert seq.index("vegetation_depth") < seq.index("scatter_intelligent")


def test_emergent_grass_scheduled_when_scene_read():
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    seq = build_default_pass_sequence(_intent())
    assert "emergent_grass" in seq
    assert seq.index("emergent_grass") > seq.index("materials_v2"), (
        "emergent_grass requires splatmap_weights_layer produced by "
        "materials_v2"
    )
    if "pass_procedural_grass" in seq:
        assert seq.index("emergent_grass") < seq.index("pass_procedural_grass")


def test_vegetation_orphans_not_scheduled_without_scene_read():
    """Both orphans only run in scene-read pipelines (canonical AAA).
    Headless / pure-noise pipelines don't have biome_id reliably."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    seq = build_default_pass_sequence(_intent(scene_read=False))
    assert "vegetation_depth" not in seq
    assert "emergent_grass" not in seq
