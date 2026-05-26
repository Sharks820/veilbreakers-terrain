"""Phase 10 architecture polish guardrails."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


def _stack(tile_size: int = 16, cell_size: float = 2.0):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    return TerrainMaskStack(
        tile_size=tile_size,
        cell_size=cell_size,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((tile_size + 1, tile_size + 1), dtype=np.float32),
    )


def test_phase10_scatter_budget_supports_100k_instances_per_tile():
    from veilbreakers_terrain.handlers.terrain_budget_enforcer import (
        TerrainBudget,
        compute_budget_report,
    )

    stack = _stack(tile_size=10, cell_size=100.0)
    stack.set("tree_instance_points", np.zeros((100_000, 5), dtype=np.float32), "test")

    report = compute_budget_report(stack, budget=TerrainBudget())

    assert report.scatter_instances == 100_000
    assert report.scatter_instances_max >= 100_000
    assert report.scatter_over is False


def test_phase10_ecotone_width_table_and_blend_weight_channel():
    from veilbreakers_terrain.handlers.terrain_ecotone_graph import (
        FALLBACK_ECOTONE_WIDTH_M,
        build_ecotone_graph,
        pass_ecotones,
        rasterize_ecotone_blend_weights,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainPipelineState,
    )

    stack = _stack(tile_size=32, cell_size=1.0)
    biome = np.zeros_like(stack.height, dtype=np.int32)
    biome[:, :16] = 7
    biome[:, 16:] = 8
    stack.set("biome_id", biome, "test")

    graph = build_ecotone_graph(stack)
    assert graph["edges"][0]["transition_width_m"] == pytest.approx(FALLBACK_ECOTONE_WIDTH_M)

    weights = rasterize_ecotone_blend_weights(stack, graph)
    assert weights.shape == (33, 33, 1)
    assert float(weights[:, 15:17, 0].max()) == pytest.approx(1.0)
    assert float(weights[:, 0, 0].max()) > 0.0

    state = TerrainPipelineState(
        intent=TerrainIntentState(
            seed=1,
            region_bounds=BBox(0.0, 0.0, 32.0, 32.0),
            tile_size=32,
            cell_size=1.0,
        ),
        mask_stack=stack,
    )
    result = pass_ecotones(state, None)
    assert "ecotone_blend_weights" in result.produced_channels
    assert state.mask_stack.ecotone_blend_weights is not None


def test_phase10_keyframes_are_json_serialisable_and_unity_anim_writes(tmp_path: Path):
    from veilbreakers_terrain.handlers.animation_environment import generate_env_keyframes
    from veilbreakers_terrain.handlers.animation_gaits import Keyframe, keyframe_to_dict
    from veilbreakers_terrain.handlers.terrain_unity_export import write_animation_clip_yaml

    kf = Keyframe(frame=0, value=1.25, channel="location", axis=2, time=0.0)
    payload = keyframe_to_dict(kf)
    json.dumps(payload)

    dicts = generate_env_keyframes({"env_type": "door_open", "frame_count": 12, "as_dicts": True})
    json.dumps(dicts)
    assert isinstance(dicts[0], dict)

    keyframes = generate_env_keyframes({"env_type": "door_open", "frame_count": 12})
    out = tmp_path / "door_open.anim"
    descriptor = write_animation_clip_yaml(keyframes, out, clip_name="DoorOpen", frame_rate=60.0)
    text = out.read_text(encoding="utf-8")
    assert descriptor["encoding"] == "unity_anim_yaml"
    assert descriptor["curve_count"] > 0
    assert "AnimationClip:" in text
    assert "m_PositionCurves:" in text or "m_EulerCurves:" in text
    assert "m_Name: DoorOpen" in text


def test_phase10_feature_budget_skips_overbudget_feature_and_keeps_later_fit():
    from veilbreakers_terrain.handlers.terrain_hierarchy import (
        FeatureBudget,
        FeatureTier,
        enforce_feature_budget,
    )

    budget = FeatureBudget(
        tier=FeatureTier.PRIMARY,
        max_features_per_km2=10.0,
        max_total_tris=1_000,
        max_footprint_m=100.0,
    )
    kept = enforce_feature_budget(
        [
            {"feature_id": "a_big", "tier": "primary", "tri_count": 2_000, "footprint_m": 10.0},
            {"feature_id": "b_fit", "tier": "primary", "tri_count": 500, "footprint_m": 10.0},
        ],
        budget,
    )

    assert [f["feature_id"] for f in kept] == ["b_fit"]


def test_phase10_mesh_bridge_uses_blender_41_normals_api():
    source = Path("veilbreakers_terrain/handlers/_mesh_bridge.py").read_text(encoding="utf-8")

    assert "normals_split_custom_set_from_vertices" in source
    assert "use_auto_smooth" in source


def test_phase10_meshy_init_is_keyless_but_submit_requires_key(monkeypatch):
    from veilbreakers_terrain.providers.external_asset_provider import AssetGenerationRequest
    from veilbreakers_terrain.providers.meshy_provider import MeshyProvider

    monkeypatch.delenv("MESHY_API_KEY", raising=False)
    provider = MeshyProvider()

    with pytest.raises(RuntimeError, match="MESHY_API_KEY not set"):
        provider.submit(AssetGenerationRequest(species_id="oak", prompt="oak"))
