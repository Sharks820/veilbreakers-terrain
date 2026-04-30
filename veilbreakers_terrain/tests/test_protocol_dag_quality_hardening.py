from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def _state(*, hints: dict | None = None):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    height = np.zeros((5, 5), dtype=np.float32)
    stack = TerrainMaskStack(
        tile_size=4,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    intent = TerrainIntentState(
        seed=1,
        region_bounds=BBox(0.0, 0.0, 4.0, 4.0),
        tile_size=4,
        cell_size=1.0,
        composition_hints=dict(hints or {}),
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_controller_protocol_rule2_requires_explicit_headless_opt_out(tmp_path: Path):
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_protocol import ProtocolViolation
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition, PassResult

    def _pass(state, region):
        del region
        state.mask_stack.set("wetness", np.ones_like(state.mask_stack.height), "needs_view")
        return PassResult(
            pass_name="needs_view",
            status="ok",
            duration_seconds=0.0,
            produced_channels=("wetness",),
        )

    TerrainPassController.register_pass(
        PassDefinition(
            name="needs_view",
            func=_pass,
            produces_channels=("wetness",),
            protocol_enforced=True,
            protocol_require_rule_2=True,
        )
    )
    with pytest.raises(ProtocolViolation, match="Rule 2"):
        TerrainPassController(_state(), checkpoint_dir=tmp_path).run_pass(
            "needs_view",
            checkpoint=False,
        )

    state = _state(hints={"protocol_out_of_view_ok": True})
    result = TerrainPassController(state, checkpoint_dir=tmp_path).run_pass(
        "needs_view",
        checkpoint=False,
    )
    assert result.status == "ok"


def test_controller_protocol_rule5_blocks_full_tile_bulk_without_policy(tmp_path: Path):
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_protocol import ProtocolViolation
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition, PassResult

    def _pass(state, region):
        del region
        state.mask_stack.set("wetness", np.ones_like(state.mask_stack.height), "bulk_guard")
        return PassResult(
            pass_name="bulk_guard",
            status="ok",
            duration_seconds=0.0,
            produced_channels=("wetness",),
        )

    TerrainPassController.register_pass(
        PassDefinition(
            name="bulk_guard",
            func=_pass,
            produces_channels=("wetness",),
            protocol_enforced=True,
            protocol_require_rule_5=True,
        )
    )
    with pytest.raises(ProtocolViolation, match="rule_5"):
        TerrainPassController(_state(), checkpoint_dir=tmp_path).run_pass(
            "bulk_guard",
            checkpoint=False,
        )

    TerrainPassController.register_pass(
        PassDefinition(
            name="bulk_guard_allowed",
            func=_pass,
            produces_channels=("wetness",),
            overrides=("wetness",),
            protocol_enforced=True,
            protocol_require_rule_5=True,
            protocol_bulk_edit=True,
        )
    )
    result = TerrainPassController(_state(), checkpoint_dir=tmp_path).run_pass(
        "bulk_guard_allowed",
        checkpoint=False,
    )
    assert result.status == "ok"


def test_live_preview_cache_miss_routes_through_controller(monkeypatch, tmp_path: Path):
    from types import MethodType

    from veilbreakers_terrain.handlers.terrain_live_preview import LivePreviewSession
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition, PassResult

    def _raw_pass(state, region):
        raise AssertionError("live preview must not call raw pass function directly")

    TerrainPassController.register_pass(
        PassDefinition(name="preview_guard", func=_raw_pass, produces_channels=("wetness",))
    )
    controller = TerrainPassController(_state(), checkpoint_dir=tmp_path)
    calls: list[str] = []

    def _run_pass(self, pass_name, region=None, *, force=False, checkpoint=True):
        del force, checkpoint
        calls.append(pass_name)
        self.state.mask_stack.set("wetness", np.ones_like(self.state.mask_stack.height), pass_name)
        return PassResult(
            pass_name=pass_name,
            status="ok",
            duration_seconds=0.0,
            produced_channels=("wetness",),
        )

    monkeypatch.setattr(controller, "run_pass", MethodType(_run_pass, controller))
    session = LivePreviewSession(controller)
    session.apply_edit({"passes": ["preview_guard"], "use_cache": True})
    assert calls == ["preview_guard"]


def test_parallel_dag_merge_preserves_side_effects_and_recomputes_height_metadata(tmp_path: Path):
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition, PassResult

    def _height_pass(state, region):
        del region
        state.mask_stack.set("height", np.full_like(state.mask_stack.height, 2.0), "height_pass")
        state.side_effects.append("height_pass side effect")
        return PassResult(
            pass_name="height_pass",
            status="ok",
            duration_seconds=0.0,
            produced_channels=("height",),
        )

    def _wetness_pass(state, region):
        del region
        state.mask_stack.set("wetness", np.ones_like(state.mask_stack.height), "wetness_pass")
        state.side_effects.append("wetness_pass side effect")
        return PassResult(
            pass_name="wetness_pass",
            status="ok",
            duration_seconds=0.0,
            produced_channels=("wetness",),
        )

    TerrainPassController.register_pass(
        PassDefinition(name="height_pass", func=_height_pass, produces_channels=("height",))
    )
    TerrainPassController.register_pass(
        PassDefinition(name="wetness_pass", func=_wetness_pass, produces_channels=("wetness",))
    )
    controller = TerrainPassController(_state(), checkpoint_dir=tmp_path)
    PassDAG.from_registry(["height_pass", "wetness_pass"]).execute_parallel(
        controller,
        max_workers=2,
    )
    assert controller.state.mask_stack.height_min_m == pytest.approx(2.0)
    assert controller.state.mask_stack.height_max_m == pytest.approx(2.0)
    assert "height_pass side effect" in controller.state.side_effects
    assert "wetness_pass side effect" in controller.state.side_effects


def test_canonical_default_sequence_is_dag_addressable_without_duplicate_pass_names():
    from collections import Counter

    from veilbreakers_terrain.handlers.terrain_master_registrar import register_all_terrain_passes
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        build_default_pass_sequence,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import BBox, TerrainIntentState, TerrainSceneRead

    TerrainPassController.clear_registry()
    register_all_terrain_passes(strict=True)
    scene_read = TerrainSceneRead(
        timestamp=0.0,
        major_landforms=(),
        focal_point=(0.0, 0.0, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=BBox(0.0, 0.0, 4.0, 4.0),
        success_criteria=("production_content_pipeline",),
        reviewer="pytest",
    )
    intent = TerrainIntentState(
        seed=1,
        region_bounds=BBox(0.0, 0.0, 4.0, 4.0),
        tile_size=4,
        cell_size=1.0,
        quality_profile="aaa_open_world",
        scene_read=scene_read,
    )
    sequence = build_default_pass_sequence(intent)
    duplicates = [name for name, count in Counter(sequence).items() if count > 1]

    assert duplicates == []
    assert "structural_masks_post_erosion" in sequence
    assert "pass_hydrology_post_erosion" in sequence
    assert set(PassDAG.from_registry(sequence).topological_order()) == set(sequence)


def test_scatter_hard_validation_issue_fails(monkeypatch):
    from veilbreakers_terrain.handlers import terrain_assets
    from veilbreakers_terrain.handlers.terrain_semantics import ValidationIssue

    state = _state()
    monkeypatch.setattr(terrain_assets, "place_assets_by_zone", lambda *a, **k: {})
    monkeypatch.setattr(
        terrain_assets,
        "_build_tree_instance_array",
        lambda *a, **k: np.zeros((0, 5), dtype=np.float32),
    )
    monkeypatch.setattr(terrain_assets, "_build_detail_density", lambda *a, **k: {})
    monkeypatch.setattr(
        terrain_assets,
        "validate_asset_density_and_overlap",
        lambda *a, **k: [
            ValidationIssue(
                code="SCATTER_HARD",
                severity="hard",
                message="forced hard scatter validation issue",
            )
        ],
    )

    result = terrain_assets.pass_scatter_intelligent(state, None)
    assert result.status == "failed"
    assert [issue.code for issue in result.issues] == ["SCATTER_HARD"]
