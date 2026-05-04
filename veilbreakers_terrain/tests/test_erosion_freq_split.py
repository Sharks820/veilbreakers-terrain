"""Tests for Phase 12.1 — low/high-freq heightmap split architecture.

Covers:
- TerrainMaskStack field existence and _ARRAY_CHANNELS membership
- to_npz / from_npz round-trip for new channels
- PassDAG channel contracts for all four new/updated passes
- Pass function behavior: low-freq generation, high-freq detail, composite, erosion fallback
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_stack(tile_size: int = 16) -> TerrainMaskStack:
    h = np.random.rand(tile_size, tile_size).astype(np.float32) * 100.0 + 1.0
    return TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )


def _make_intent(
    seed: int = 42,
    erosion_profile: str = "temperate",
    quality_profile: str = "aaa_open_world",
):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        TerrainIntentState,
        BBox,
        TerrainSceneRead,
    )
    import time

    scene_read = TerrainSceneRead(
        timestamp=time.time(),
        major_landforms=("ridge",),
        focal_point=(0.0, 0.0, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=BBox(0, 0, 100, 100),
        success_criteria=("test",),
        reviewer="pytest",
    )
    return TerrainIntentState(
        seed=seed,
        region_bounds=BBox(0, 0, 100, 100),
        tile_size=16,
        cell_size=1.0,
        erosion_profile=erosion_profile,
        quality_profile=quality_profile,
        scene_read=scene_read,
    )


def _make_state(tile_size: int = 16, with_scene_read: bool = True):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainPipelineState

    stack = _make_minimal_stack(tile_size)
    intent = _make_intent()
    if not with_scene_read:
        from veilbreakers_terrain.handlers.terrain_semantics import (
            TerrainIntentState, BBox,
        )
        intent = TerrainIntentState(
            seed=42,
            region_bounds=BBox(0, 0, 100, 100),
            tile_size=tile_size,
            cell_size=1.0,
        )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# Task 1 — TerrainMaskStack channel fields and _ARRAY_CHANNELS
# ---------------------------------------------------------------------------

class TestTerrainMaskStackFreqChannels:
    """TerrainMaskStack must have hmap_low_freq and hmap_high_freq fields."""

    def test_hmap_low_freq_field_exists(self):
        stack = _make_minimal_stack()
        assert hasattr(stack, "hmap_low_freq")
        assert stack.hmap_low_freq is None

    def test_hmap_high_freq_field_exists(self):
        stack = _make_minimal_stack()
        assert hasattr(stack, "hmap_high_freq")
        assert stack.hmap_high_freq is None

    def test_hmap_low_freq_in_array_channels(self):
        stack = _make_minimal_stack()
        assert "hmap_low_freq" in stack._ARRAY_CHANNELS

    def test_hmap_high_freq_in_array_channels(self):
        stack = _make_minimal_stack()
        assert "hmap_high_freq" in stack._ARRAY_CHANNELS

    def test_set_hmap_low_freq_with_provenance(self):
        stack = _make_minimal_stack()
        arr = np.ones((16, 16), dtype=np.float32) * 5.0
        stack.set("hmap_low_freq", arr, "test_pass")
        assert stack.hmap_low_freq is not None
        assert stack.populated_by_pass.get("hmap_low_freq") == "test_pass"
        np.testing.assert_array_equal(stack.hmap_low_freq, arr)

    def test_npz_roundtrip_preserves_hmap_low_freq(self):
        stack = _make_minimal_stack()
        arr = np.random.rand(16, 16).astype(np.float32) * 50.0
        stack.set("hmap_low_freq", arr, "test_pass")

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stack.npz"
            stack.to_npz(path)
            from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
            restored = TerrainMaskStack.from_npz(path)

        assert restored.hmap_low_freq is not None
        np.testing.assert_allclose(restored.hmap_low_freq, arr, rtol=1e-5)

    def test_npz_roundtrip_preserves_hmap_high_freq(self):
        stack = _make_minimal_stack()
        arr = (np.random.rand(16, 16).astype(np.float32) - 0.5) * 10.0
        stack.set("hmap_high_freq", arr, "test_pass")

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stack.npz"
            stack.to_npz(path)
            from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
            restored = TerrainMaskStack.from_npz(path)

        assert restored.hmap_high_freq is not None
        np.testing.assert_allclose(restored.hmap_high_freq, arr, rtol=1e-5)


# ---------------------------------------------------------------------------
# Task 2 — PassDAG channel contracts
# ---------------------------------------------------------------------------

class TestPassDAGContracts:
    """PassDAG registrations must match the Fix 12.1 spec exactly."""

    def setup_method(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import (
            TerrainPassController,
            register_default_passes,
        )
        TerrainPassController.clear_registry()
        register_default_passes()
        self.reg = TerrainPassController.PASS_REGISTRY

    def teardown_method(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        TerrainPassController.clear_registry()

    def test_pass_generate_low_freq_hmap_registered(self):
        assert "pass_generate_low_freq_hmap" in self.reg

    def test_pass_generate_low_freq_hmap_produces_height_and_hmap_low_freq(self):
        p = self.reg["pass_generate_low_freq_hmap"]
        assert "height" in p.produces_channels
        assert "hmap_low_freq" in p.produces_channels

    def test_pass_generate_high_freq_detail_registered(self):
        assert "pass_generate_high_freq_detail" in self.reg

    def test_pass_generate_high_freq_detail_produces_hmap_high_freq(self):
        p = self.reg["pass_generate_high_freq_detail"]
        assert "hmap_high_freq" in p.produces_channels

    def test_erosion_requires_hmap_low_freq(self):
        p = self.reg["erosion"]
        assert "hmap_low_freq" in p.requires_channels

    def test_erosion_does_not_claim_ridge_channel(self):
        p = self.reg["erosion"]
        assert "ridge" not in p.produces_channels

    def test_pass_composite_hmap_registered(self):
        assert "pass_composite_hmap" in self.reg

    def test_pass_composite_hmap_requires_both_freq_channels(self):
        p = self.reg["pass_composite_hmap"]
        assert "hmap_low_freq" in p.requires_channels
        assert "hmap_high_freq" in p.requires_channels

    def test_pass_composite_hmap_produces_height(self):
        p = self.reg["pass_composite_hmap"]
        assert p.produces_channels == ("height",)


# ---------------------------------------------------------------------------
# Task 2 — Pass function behavior
# ---------------------------------------------------------------------------

class TestPassFunctionBehavior:
    """Individual pass functions must behave per the Fix 12.1 spec."""

    def setup_method(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import (
            TerrainPassController,
            register_default_passes,
        )
        TerrainPassController.clear_registry()
        register_default_passes()

    def teardown_method(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        TerrainPassController.clear_registry()

    def test_pass_generate_low_freq_hmap_sets_hmap_low_freq(self):
        from veilbreakers_terrain.handlers._terrain_world import pass_generate_low_freq_hmap

        state = _make_state()
        result = pass_generate_low_freq_hmap(state, None)
        assert result.status == "ok"
        assert state.mask_stack.hmap_low_freq is not None
        assert state.mask_stack.hmap_low_freq.ndim == 2

    def test_pass_generate_low_freq_hmap_also_sets_height(self):
        from veilbreakers_terrain.handlers._terrain_world import pass_generate_low_freq_hmap

        state = _make_state()
        # Zero out the height to force regeneration
        state.mask_stack.set("height", np.zeros((16, 16), dtype=np.float32), "test")
        pass_generate_low_freq_hmap(state, None)
        assert state.mask_stack.height is not None

    def test_pass_generate_low_freq_hmap_reuses_existing_low_freq_channel(self):
        from veilbreakers_terrain.handlers._terrain_world import pass_generate_low_freq_hmap

        state = _make_state()
        existing = np.full((16, 16), 37.5, dtype=np.float32)
        state.mask_stack.set("hmap_low_freq", existing, "macro_world")
        state.mask_stack.set("height", np.zeros((16, 16), dtype=np.float32), "test")

        result = pass_generate_low_freq_hmap(state, None)

        assert result.metrics["generated"] is False
        assert result.metrics["reused_existing"] is True
        np.testing.assert_array_equal(state.mask_stack.hmap_low_freq, existing)
        np.testing.assert_array_equal(state.mask_stack.height, existing)

    def test_pass_generate_high_freq_detail_sets_hmap_high_freq(self):
        from veilbreakers_terrain.handlers._terrain_world import pass_generate_high_freq_detail

        state = _make_state()
        result = pass_generate_high_freq_detail(state, None)
        assert result.status == "ok"
        assert state.mask_stack.hmap_high_freq is not None
        assert state.mask_stack.hmap_high_freq.ndim == 2

    def test_pass_generate_high_freq_detail_shape_matches_tile(self):
        from veilbreakers_terrain.handlers._terrain_world import pass_generate_high_freq_detail

        state = _make_state(tile_size=16)
        pass_generate_high_freq_detail(state, None)
        h = state.mask_stack.hmap_high_freq
        assert h.shape[0] == h.shape[1]  # square tile

    def test_pass_composite_hmap_computes_correct_formula(self):
        from veilbreakers_terrain.handlers._terrain_world import pass_composite_hmap
        from veilbreakers_terrain.handlers._terrain_world import DETAIL_SCALE

        state = _make_state()
        low = np.ones((16, 16), dtype=np.float32) * 10.0
        high = np.ones((16, 16), dtype=np.float32) * 2.0
        state.mask_stack.set("hmap_low_freq", low, "test")
        state.mask_stack.set("hmap_high_freq", high, "test")

        result = pass_composite_hmap(state, None)
        assert result.status == "ok"
        expected = 10.0 + 2.0 * DETAIL_SCALE
        np.testing.assert_allclose(state.mask_stack.height, expected, rtol=1e-5)

    def test_pass_composite_hmap_detail_scale_is_0_2(self):
        from veilbreakers_terrain.handlers._terrain_world import DETAIL_SCALE
        assert abs(DETAIL_SCALE - 0.2) < 1e-9

    def test_pass_composite_hmap_raises_if_low_freq_missing(self):
        from veilbreakers_terrain.handlers._terrain_world import pass_composite_hmap

        state = _make_state()
        # Only high freq set
        state.mask_stack.set("hmap_high_freq", np.ones((16, 16), dtype=np.float32), "test")
        with pytest.raises(RuntimeError, match="hmap_low_freq"):
            pass_composite_hmap(state, None)

    def test_pass_composite_hmap_raises_if_high_freq_missing(self):
        from veilbreakers_terrain.handlers._terrain_world import pass_composite_hmap

        state = _make_state()
        # Only low freq set
        state.mask_stack.set("hmap_low_freq", np.ones((16, 16), dtype=np.float32) * 5.0, "test")
        with pytest.raises(RuntimeError, match="hmap_high_freq"):
            pass_composite_hmap(state, None)

    def test_pass_erosion_reads_hmap_low_freq_when_set(self):
        """When hmap_low_freq is present, erosion should operate on it (not height)."""
        from veilbreakers_terrain.handlers._terrain_world import pass_erosion

        state = _make_state()
        # Set hmap_low_freq to different values than height
        low_arr = np.random.rand(16, 16).astype(np.float32) * 50.0 + 20.0
        height_arr = np.ones((16, 16), dtype=np.float32) * 999.0  # distinctive value
        state.mask_stack.set("hmap_low_freq", low_arr, "test")
        state.mask_stack.set("height", height_arr, "test")

        result = pass_erosion(state, None)
        assert result.status == "ok"
        # After erosion, height should NOT equal 999 (the original height value)
        # — it was derived from low_arr, not height_arr
        assert not np.allclose(state.mask_stack.height, 999.0)

    def test_pass_erosion_fallback_to_height_when_hmap_low_freq_absent(self):
        """Backward compat: when hmap_low_freq is None, erosion falls back to stack.height."""
        from veilbreakers_terrain.handlers._terrain_world import pass_erosion

        state = _make_state()
        # Ensure hmap_low_freq is None
        assert state.mask_stack.hmap_low_freq is None

        # Set meaningful height
        h = np.random.rand(16, 16).astype(np.float32) * 50.0 + 10.0
        state.mask_stack.set("height", h, "test")

        result = pass_erosion(state, None)
        # Should succeed — fallback path
        assert result.status == "ok"
        assert state.mask_stack.height is not None

    def test_pass_erosion_updates_hmap_low_freq_after_erosion(self):
        """After erosion, hmap_low_freq should be updated to the eroded result."""
        from veilbreakers_terrain.handlers._terrain_world import pass_erosion

        state = _make_state()
        low_arr = np.random.rand(16, 16).astype(np.float32) * 50.0 + 20.0
        state.mask_stack.set("hmap_low_freq", low_arr, "test")

        pass_erosion(state, None)
        # hmap_low_freq should now hold the eroded version (updated by erosion)
        assert state.mask_stack.hmap_low_freq is not None
        # hmap_low_freq should match stack.height after erosion
        np.testing.assert_array_equal(
            state.mask_stack.hmap_low_freq,
            state.mask_stack.height,
        )

    def test_pass_erosion_quality_profile_controls_iteration_budget(self, monkeypatch):
        """AAA quality profiles must drive erosion cost/quality, not dead config."""
        from types import SimpleNamespace

        import veilbreakers_terrain.handlers._terrain_world as world_mod

        hydraulic_iterations: list[int] = []
        thermal_iterations: list[int] = []

        def fake_analytical(height, cfg, seed, cell_size):
            return SimpleNamespace(
                height_delta=np.zeros_like(height, dtype=np.float32),
                ridge_map=np.zeros_like(height, dtype=np.float32),
            )

        def fake_hydraulic(height, iterations, seed, hero_exclusion, erodibility_map):
            hydraulic_iterations.append(int(iterations))
            zeros = np.zeros_like(height, dtype=np.float32)
            return SimpleNamespace(
                height=np.asarray(height, dtype=np.float32),
                erosion_amount=zeros,
                deposition_amount=zeros,
                wetness=zeros,
                drainage=zeros,
                bank_instability=zeros,
                sediment_accumulation_at_base=zeros,
                pool_deepening_delta=zeros,
            )

        def fake_thermal(height, iterations, talus_angle, cell_size):
            thermal_iterations.append(int(iterations))
            return SimpleNamespace(
                height=np.asarray(height, dtype=np.float32),
                talus=np.zeros_like(height, dtype=np.float32),
            )

        monkeypatch.setattr(world_mod, "apply_analytical_erosion", fake_analytical)
        monkeypatch.setattr(world_mod, "apply_hydraulic_erosion_masks", fake_hydraulic)
        monkeypatch.setattr(world_mod, "apply_thermal_erosion_masks", fake_thermal)
        monkeypatch.setattr(
            world_mod,
            "compute_stream_power_erosion",
            lambda height, **_kwargs: np.asarray(height, dtype=np.float32),
        )

        mobile = _make_state()
        mobile.intent = _make_intent(quality_profile="mobile")
        mobile.mask_stack.set("hmap_low_freq", np.ones((16, 16), dtype=np.float32), "test")
        aaa = _make_state()
        aaa.intent = _make_intent(quality_profile="aaa_open_world")
        aaa.mask_stack.set("hmap_low_freq", np.ones((16, 16), dtype=np.float32), "test")

        mobile_result = world_mod.pass_erosion(mobile, None)
        aaa_result = world_mod.pass_erosion(aaa, None)

        assert mobile_result.metrics["quality_profile"] == "mobile"
        assert aaa_result.metrics["quality_profile"] == "aaa_open_world"
        assert hydraulic_iterations[1] > hydraulic_iterations[0]
        assert thermal_iterations[1] > thermal_iterations[0]

    def test_macro_world_pipeline_reapplies_neighbor_seams_after_generation(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

        state = _make_state(with_scene_read=False)
        state.mask_stack.set("height", np.zeros((16, 16), dtype=np.float32), "test")
        object.__setattr__(
            state.mask_stack,
            "north_edge",
            np.full((16,), 7.0, dtype=np.float32),
        )

        controller = TerrainPassController(state)
        controller.run_pipeline(pass_sequence=["macro_world"], checkpoint=False)

        np.testing.assert_allclose(state.mask_stack.height[0, :], 7.0)
        np.testing.assert_allclose(state.mask_stack.hmap_low_freq[0, :], 7.0)

    def test_pass_erosion_runs_exactly_n_iterations(self, monkeypatch):
        """FIX-B14-10: pass_erosion must run exactly hydraulic_erosion_iterations
        droplets — no hidden x25 multiplier.

        Uses a 1024x1024 tile so tile_scale==1.0 and the profile value passes
        through the scaling logic unchanged. Requesting 10 iterations must
        result in exactly 10 calls, never 250 (the old x25 over-application).
        """
        from types import SimpleNamespace

        import veilbreakers_terrain.handlers._terrain_world as world_mod
        from veilbreakers_terrain.handlers.terrain_quality_profiles import (
            TerrainQualityProfile,
            load_quality_profile,
        )
        from veilbreakers_terrain.handlers.terrain_semantics import (
            ErosionStrategy,
        )

        REQUESTED_ITERATIONS = 10

        # Build a 1024x1024 state so tile_scale == 1.0 and no downscaling occurs.
        tile_size = 1024
        stack = _make_minimal_stack(tile_size=tile_size)
        intent = _make_intent(quality_profile="mobile")
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainPipelineState
        state = TerrainPipelineState(intent=intent, mask_stack=stack)
        state.mask_stack.set(
            "hmap_low_freq",
            np.ones((tile_size, tile_size), dtype=np.float32) * 50.0,
            "test",
        )

        # Patch load_quality_profile to return a profile with exactly 10
        # hydraulic_erosion_iterations so the test is self-contained and fast.
        from veilbreakers_terrain.handlers import terrain_quality_profiles as qp_mod

        _real_load = qp_mod.load_quality_profile

        def fake_load_quality_profile(name: str):
            profile = _real_load(name)
            from dataclasses import replace as dc_replace
            return dc_replace(profile, hydraulic_erosion_iterations=REQUESTED_ITERATIONS)

        monkeypatch.setattr(world_mod, "load_quality_profile", fake_load_quality_profile, raising=False)
        # Also patch within the terrain_quality_profiles module in case it's
        # imported directly inside pass_erosion via a local import.
        import importlib
        import veilbreakers_terrain.handlers.terrain_quality_profiles as _qp
        monkeypatch.setattr(_qp, "load_quality_profile", fake_load_quality_profile)

        hydraulic_call_iterations: list[int] = []

        def fake_analytical(height, cfg, seed, cell_size):
            return SimpleNamespace(
                height_delta=np.zeros_like(height, dtype=np.float32),
                ridge_map=np.zeros_like(height, dtype=np.float32),
            )

        def fake_hydraulic(height, iterations, seed, hero_exclusion, erodibility_map):
            hydraulic_call_iterations.append(int(iterations))
            zeros = np.zeros_like(height, dtype=np.float32)
            return SimpleNamespace(
                height=np.asarray(height, dtype=np.float32),
                erosion_amount=zeros,
                deposition_amount=zeros,
                wetness=zeros,
                drainage=zeros,
                bank_instability=zeros,
                sediment_accumulation_at_base=zeros,
                pool_deepening_delta=zeros,
            )

        def fake_thermal(height, iterations, talus_angle, cell_size):
            return SimpleNamespace(
                height=np.asarray(height, dtype=np.float32),
                talus=np.zeros_like(height, dtype=np.float32),
            )

        monkeypatch.setattr(world_mod, "apply_analytical_erosion", fake_analytical)
        monkeypatch.setattr(world_mod, "apply_hydraulic_erosion_masks", fake_hydraulic)
        monkeypatch.setattr(world_mod, "apply_thermal_erosion_masks", fake_thermal)
        monkeypatch.setattr(
            world_mod,
            "compute_stream_power_erosion",
            lambda height, **_kwargs: np.asarray(height, dtype=np.float32),
        )

        result = world_mod.pass_erosion(state, None)

        assert result.status == "ok", f"pass_erosion failed: {result}"
        assert len(hydraulic_call_iterations) == 1, (
            "apply_hydraulic_erosion_masks should be called exactly once per pass_erosion invocation"
        )
        actual = hydraulic_call_iterations[0]
        assert actual == REQUESTED_ITERATIONS, (
            f"FIX-B14-10: expected exactly {REQUESTED_ITERATIONS} hydraulic iterations, "
            f"got {actual}. If this is 250 the x25 multiplier was re-introduced."
        )

    def test_constants_declared(self):
        from veilbreakers_terrain.handlers._terrain_world import (
            LOW_FREQ_OCTAVES,
            HIGH_FREQ_OCTAVES,
            DETAIL_SCALE,
        )
        assert LOW_FREQ_OCTAVES == 3
        assert HIGH_FREQ_OCTAVES == 5
        assert abs(DETAIL_SCALE - 0.2) < 1e-9
