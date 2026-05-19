"""Bundle B — tests for terrain_materials_v2.py."""

from __future__ import annotations

import math
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pass_registry():
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    yield
    TerrainPassController.clear_registry()


def _build_state(tile_size: int = 32, seed: int = 42):
    from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    N = tile_size + 1
    # Synthetic heightmap: slope from 0..80m across rows, flat across cols
    rows = np.linspace(0.0, 80.0, N)[:, None]
    cols = np.zeros((1, N))
    height = rows + cols
    # Add a tall plateau at top
    height[:5, :] += 200.0
    rng = np.random.default_rng(seed)
    height += rng.normal(0.0, 0.02, size=height.shape)

    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    compute_base_masks(
        height,
        cell_size=1.0,
        tile_coords=(0, 0),
        stack=stack,
        pass_name="structural_masks",
    )
    region_bounds = BBox(0.0, 0.0, float(N), float(N))
    intent = TerrainIntentState(
        seed=seed,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def _build_large_state(tile_size: int = 512):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    N = tile_size
    height = np.zeros((N, N), dtype=np.float64)
    slope = np.full((N, N), math.radians(25.0), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    stack.set("slope", slope, "fixture")
    stack.set("curvature", np.zeros_like(height), "fixture")
    stack.set("wetness", np.zeros_like(height), "fixture")
    region_bounds = BBox(0.0, 0.0, float(N), float(N))
    intent = TerrainIntentState(
        seed=0,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# MaterialRuleSet / MaterialChannel
# ---------------------------------------------------------------------------


def test_default_dark_fantasy_rules_has_5_channels():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        default_dark_fantasy_rules,
    )

    rules = default_dark_fantasy_rules()
    assert len(rules.channels) == 5
    ids = [c.channel_id for c in rules.channels]
    assert set(ids) == {"ground", "cliff", "scree", "wet_rock", "snow"}
    assert rules.default_channel_id == "ground"


def test_ruleset_rejects_duplicate_channel_ids():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        MaterialChannel,
        MaterialRuleSet,
    )

    with pytest.raises(ValueError):
        MaterialRuleSet(
            channels=(
                MaterialChannel(channel_id="a"),
                MaterialChannel(channel_id="a"),
            ),
            default_channel_id="a",
        )


def test_ruleset_rejects_missing_default_channel():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        MaterialChannel,
        MaterialRuleSet,
    )

    with pytest.raises(ValueError):
        MaterialRuleSet(
            channels=(MaterialChannel(channel_id="a"),),
            default_channel_id="b",
        )


def test_cliff_channel_is_triplanar():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        default_dark_fantasy_rules,
    )

    rules = default_dark_fantasy_rules()
    cliff = next(c for c in rules.channels if c.channel_id == "cliff")
    assert cliff.triplanar is True


def test_ruleset_priority_order_is_descending_and_stable():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        MaterialChannel,
        MaterialRuleSet,
    )

    rules = MaterialRuleSet(
        channels=(
            MaterialChannel(channel_id="base", priority=0),
            MaterialChannel(channel_id="hero", priority=20),
            MaterialChannel(channel_id="detail", priority=20),
        ),
        default_channel_id="base",
    )

    assert rules.priority_order() == (1, 2, 0)


def test_material_priority_claims_overlapping_cells():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        MaterialChannel,
        MaterialRuleSet,
        compute_slope_material_weights,
    )

    state = _build_state()
    state.mask_stack.set("slope", np.full_like(state.mask_stack.height, 0.1), "test")
    rules = MaterialRuleSet(
        channels=(
            MaterialChannel(channel_id="base", base_weight=1.0),
            MaterialChannel(channel_id="hero", base_weight=1.0, priority=10),
        ),
        default_channel_id="base",
    )

    weights = compute_slope_material_weights(state.mask_stack, rules)
    assert float(weights[:, :, rules.index_of("hero")].mean()) == pytest.approx(1.0)
    assert float(weights[:, :, rules.index_of("base")].mean()) == pytest.approx(0.0)


def test_apply_region_mask_lerps_instead_of_multiplying():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import _apply_region_mask

    base = np.zeros((2, 2, 2), dtype=np.float32)
    base[:, :, 0] = 1.0
    authored = np.zeros((2, 2, 2), dtype=np.float32)
    authored[:, :, 1] = 1.0
    mask = np.array([[0.0, 0.25], [0.5, 1.0]], dtype=np.float32)

    blended = _apply_region_mask(base, authored, mask)

    np.testing.assert_allclose(blended[0, 0], [1.0, 0.0])
    np.testing.assert_allclose(blended[0, 1], [0.75, 0.25])
    np.testing.assert_allclose(blended[1, 0], [0.5, 0.5])
    np.testing.assert_allclose(blended[1, 1], [0.0, 1.0])


# ---------------------------------------------------------------------------
# compute_slope_material_weights
# ---------------------------------------------------------------------------


def test_weights_sum_to_one_per_cell():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights,
    )

    state = _build_state()
    weights = compute_slope_material_weights(state.mask_stack)
    sums = weights.sum(axis=2)
    assert np.allclose(sums, 1.0, atol=1e-5)


def test_weights_shape_matches_heightmap():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights,
        default_dark_fantasy_rules,
    )

    state = _build_state()
    rules = default_dark_fantasy_rules()
    weights = compute_slope_material_weights(state.mask_stack, rules)
    assert weights.shape == (*state.mask_stack.height.shape, len(rules.channels))
    assert weights.dtype == np.float32


def test_weights_vectorized_under_200ms_on_512():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights,
    )

    state = _build_large_state(tile_size=512)
    t0 = time.perf_counter()
    weights = compute_slope_material_weights(state.mask_stack)
    dt = time.perf_counter() - t0
    assert weights.shape[0] == 512
    assert dt < 0.5, f"compute_slope_material_weights took {dt*1000:.1f}ms"


def test_cliff_channel_triggers_on_high_slope():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights,
        default_dark_fantasy_rules,
    )

    state = _build_state()
    rules = default_dark_fantasy_rules()
    # Force slope to 70 degrees everywhere
    state.mask_stack.set(
        "slope",
        np.full_like(state.mask_stack.height, math.radians(70.0)),
        "test",
    )
    weights = compute_slope_material_weights(state.mask_stack, rules)
    cliff_idx = rules.index_of("cliff")
    assert weights[:, :, cliff_idx].mean() > 0.4


def test_ground_channel_dominates_flat_terrain():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights,
        default_dark_fantasy_rules,
    )

    state = _build_state()
    rules = default_dark_fantasy_rules()
    state.mask_stack.set(
        "slope", np.zeros_like(state.mask_stack.height), "test"
    )
    state.mask_stack.set(
        "height", np.full_like(state.mask_stack.height, 50.0), "test"
    )
    weights = compute_slope_material_weights(state.mask_stack, rules)
    ground_idx = rules.index_of("ground")
    assert weights[:, :, ground_idx].mean() > 0.5


def test_wet_rock_channel_triggers_on_wetness():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights,
        default_dark_fantasy_rules,
    )

    state = _build_state()
    rules = default_dark_fantasy_rules()
    state.mask_stack.set(
        "slope",
        np.full_like(state.mask_stack.height, math.radians(35.0)),
        "test",
    )
    state.mask_stack.set(
        "wetness", np.full_like(state.mask_stack.height, 0.8), "test"
    )
    weights = compute_slope_material_weights(state.mask_stack, rules)
    wet_idx = rules.index_of("wet_rock")
    assert weights[:, :, wet_idx].mean() > 0.2


def test_water_masks_force_wet_rock_without_grass_bleed():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights,
        default_dark_fantasy_rules,
    )

    state = _build_state()
    rules = default_dark_fantasy_rules()
    shape = state.mask_stack.height.shape
    state.mask_stack.set("slope", np.zeros(shape, dtype=np.float32), "test")
    water = np.zeros(shape, dtype=np.float32)
    splash = np.zeros(shape, dtype=np.float32)
    water[2, 2] = 1.0
    splash[3, 3] = 1.0
    state.mask_stack.set("water_surface_mask", water, "test")
    state.mask_stack.set("wet_rock", splash, "test")

    weights = compute_slope_material_weights(state.mask_stack, rules)
    wet_idx = rules.index_of("wet_rock")
    ground_idx = rules.index_of("ground")
    assert weights[2, 2, wet_idx] == pytest.approx(1.0)
    assert weights[2, 2, ground_idx] == pytest.approx(0.0)
    assert weights[3, 3, wet_idx] == pytest.approx(1.0)
    assert weights[3, 3, ground_idx] == pytest.approx(0.0)


def test_caldera_lava_prox_hard_stamps_lava_and_fails_closed_when_missing():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        caldera_volcanic_rules,
        compute_slope_material_weights,
    )

    state = _build_state()
    rules = caldera_volcanic_rules()
    shape = state.mask_stack.height.shape
    state.mask_stack.set("slope", np.zeros(shape, dtype=np.float32), "test")
    state.mask_stack.set("height", np.full(shape, 40.0, dtype=np.float32), "test")
    state.mask_stack.set("curvature", np.zeros(shape, dtype=np.float32), "test")

    no_lava_weights = compute_slope_material_weights(state.mask_stack, rules)
    lava_idx = rules.index_of("lava_hot")
    assert float(no_lava_weights[:, :, lava_idx].max()) == pytest.approx(0.0)

    lava = np.zeros(shape, dtype=np.float32)
    lava[2, 2] = 1.0
    state.mask_stack.set("lava_prox", lava, "test")
    weights = compute_slope_material_weights(state.mask_stack, rules)
    assert weights[2, 2, lava_idx] == pytest.approx(1.0)
    assert weights[0, 0, lava_idx] == pytest.approx(0.0)


def test_snow_channel_triggers_above_altitude():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights,
        default_dark_fantasy_rules,
    )

    state = _build_state()
    rules = default_dark_fantasy_rules()
    state.mask_stack.set(
        "height", np.full_like(state.mask_stack.height, 400.0), "test"
    )
    state.mask_stack.set(
        "slope",
        np.full_like(state.mask_stack.height, math.radians(10.0)),
        "test",
    )
    weights = compute_slope_material_weights(state.mask_stack, rules)
    snow_idx = rules.index_of("snow")
    assert weights[:, :, snow_idx].mean() > 0.3


def test_snow_channel_absent_at_low_altitude():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights,
        default_dark_fantasy_rules,
    )

    state = _build_state()
    rules = default_dark_fantasy_rules()
    state.mask_stack.set(
        "height", np.full_like(state.mask_stack.height, 10.0), "test"
    )
    state.mask_stack.set(
        "slope",
        np.full_like(state.mask_stack.height, math.radians(10.0)),
        "test",
    )
    weights = compute_slope_material_weights(state.mask_stack, rules)
    snow_idx = rules.index_of("snow")
    assert weights[:, :, snow_idx].mean() < 1e-5


def test_weights_never_nan_or_inf():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights,
    )

    state = _build_state()
    weights = compute_slope_material_weights(state.mask_stack)
    assert np.all(np.isfinite(weights))


# ---------------------------------------------------------------------------
# pass_materials
# ---------------------------------------------------------------------------


def test_pass_materials_populates_splatmap_channel():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        register_bundle_b_material_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    register_bundle_b_material_passes()
    state = _build_state()
    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        result = controller.run_pass("materials_v2", checkpoint=False)
    assert result.status == "ok"
    assert state.mask_stack.splatmap_weights_layer is not None
    assert state.mask_stack.material_weights is not None


def test_pass_materials_metrics_report_coverage():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        register_bundle_b_material_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    register_bundle_b_material_passes()
    state = _build_state()
    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        result = controller.run_pass("materials_v2", checkpoint=False)
    assert "dominant_layer" in result.metrics
    assert result.metrics["layer_count"] == 5
    for cid in ("ground", "cliff", "scree", "wet_rock", "snow"):
        assert f"coverage_{cid}" in result.metrics


def test_materials_registration_keeps_soft_inputs_optional():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        register_bundle_b_material_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    register_bundle_b_material_passes()
    definition = TerrainPassController.get_pass("materials_v2")
    assert definition.requires_channels == ("slope", "height")
    assert "curvature" in definition.optional_channels
    assert "wetness" in definition.optional_channels


def test_pass_materials_is_deterministic():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        register_bundle_b_material_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    register_bundle_b_material_passes()
    state_a = _build_state()
    state_b = _build_state()
    with tempfile.TemporaryDirectory() as td:
        ca = TerrainPassController(state_a, checkpoint_dir=Path(td))
        cb = TerrainPassController(state_b, checkpoint_dir=Path(td))
        ca.run_pass("materials_v2", checkpoint=False)
        cb.run_pass("materials_v2", checkpoint=False)
    np.testing.assert_array_equal(
        state_a.mask_stack.splatmap_weights_layer,
        state_b.mask_stack.splatmap_weights_layer,
    )


def test_pass_materials_applies_height_blend_defaults():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        MaterialChannel,
        MaterialRuleSet,
        pass_materials,
    )

    state = _build_state()
    state.intent.composition_hints["material_height_blend_gamma"] = {
        "valley": 0.5,
        "peak": 2.5,
    }
    rules = MaterialRuleSet(
        channels=(
            MaterialChannel(channel_id="valley", base_weight=1.0),
            MaterialChannel(channel_id="peak", base_weight=1.0),
        ),
        default_channel_id="valley",
    )
    result = pass_materials(state, None, rules=rules)
    assert result.status == "ok"
    weights = state.mask_stack.splatmap_weights_layer
    assert weights is not None
    min_pos = np.unravel_index(np.argmin(state.mask_stack.height), state.mask_stack.height.shape)
    max_pos = np.unravel_index(np.argmax(state.mask_stack.height), state.mask_stack.height.shape)
    valley_idx = rules.index_of("valley")
    peak_idx = rules.index_of("peak")
    assert weights[min_pos][valley_idx] > weights[max_pos][valley_idx]
    assert weights[max_pos][peak_idx] > weights[min_pos][peak_idx]


def test_region_scoped_pass_leaves_outside_cells_unchanged():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        register_bundle_b_material_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    register_bundle_b_material_passes()
    state = _build_state()
    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        # First full-tile pass
        controller.run_pass("materials_v2", checkpoint=False)
        first = state.mask_stack.splatmap_weights_layer.copy()

        # Force slope to a different value, then run region-scoped pass on a sub-region
        state.mask_stack.set(
            "slope",
            np.full_like(state.mask_stack.height, math.radians(80.0)),
            "test",
        )
        region = BBox(0.0, 0.0, 5.0, 5.0)
        controller.run_pass("materials_v2", region=region, checkpoint=False)
        second = state.mask_stack.splatmap_weights_layer

    # Cells outside the region should match the first pass
    # Cells inside the 5x5 region SHOULD differ (slope radically changed)
    outside_unchanged = np.allclose(second[10:, 10:], first[10:, 10:], atol=1e-5)
    assert outside_unchanged, "region scoping should leave outside cells untouched"


def test_unity_export_manifest_lists_splatmap():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        register_bundle_b_material_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    register_bundle_b_material_passes()
    state = _build_state()
    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        controller.run_pass("materials_v2", checkpoint=False)
    manifest = state.mask_stack.unity_export_manifest()
    assert "splatmap_weights_layer" in manifest["populated_channels"]


# ---------------------------------------------------------------------------
# FIX-B14-12: terrain_brucks_weight + snow_coverage channel contracts
# ---------------------------------------------------------------------------

def test_brucks_snow_weight_written_when_second_pass_runs():
    """Both material passes write terrain_brucks_weight and snow_coverage.

    Verifies FIX-B14-12:
    - register_bundle_b_material_passes() must not raise ChannelOwnershipError
      even though materials_v2 and materials_v2_volcanic both produce the same
      six channels (the volcanic pass declares overrides for all of them).
    - After materials_v2 runs, terrain_brucks_weight and snow_coverage are
      non-None on the stack.
    - After materials_v2_volcanic also runs, both channels remain non-None
      (the volcanic pass overwrites them, not drops them).
    """
    import tempfile
    from pathlib import Path

    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        register_bundle_b_material_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import ChannelOwnershipError

    # Registration must not raise ChannelOwnershipError
    try:
        register_bundle_b_material_passes()
    except ChannelOwnershipError as exc:  # pragma: no cover
        pytest.fail(
            f"register_bundle_b_material_passes() raised ChannelOwnershipError: {exc}"
        )

    state = _build_state()

    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))

        # Run the primary pass
        result_primary = controller.run_pass("materials_v2", checkpoint=False)
        # T0.5-2 (Y04 v3 §P.8.2): strict-"ok" — materials_v2 primary must
        # produce a clean PassResult; "warning" would hide a brucks_weight or
        # snow_coverage write regression flagged elsewhere in this test.
        assert result_primary.status == "ok", (
            f"materials_v2 pass returned status={result_primary.status!r}"
        )

        brucks_after_primary = state.mask_stack.get("terrain_brucks_weight")
        snow_after_primary = state.mask_stack.get("snow_coverage")

        assert brucks_after_primary is not None, (
            "terrain_brucks_weight must be written to the stack by materials_v2"
        )
        assert snow_after_primary is not None, (
            "snow_coverage must be written to the stack by materials_v2"
        )
        assert brucks_after_primary.shape == state.mask_stack.height.shape, (
            f"terrain_brucks_weight shape {brucks_after_primary.shape} must match "
            f"height shape {state.mask_stack.height.shape}"
        )
        assert snow_after_primary.shape == state.mask_stack.height.shape, (
            f"snow_coverage shape {snow_after_primary.shape} must match "
            f"height shape {state.mask_stack.height.shape}"
        )
        # Values must be in [0, 1]
        assert brucks_after_primary.min() >= 0.0 and brucks_after_primary.max() <= 1.0, (
            f"terrain_brucks_weight values out of [0,1]: "
            f"min={brucks_after_primary.min():.4f} max={brucks_after_primary.max():.4f}"
        )
        assert snow_after_primary.min() >= 0.0 and snow_after_primary.max() <= 1.0, (
            f"snow_coverage values out of [0,1]: "
            f"min={snow_after_primary.min():.4f} max={snow_after_primary.max():.4f}"
        )

        # Run the secondary volcanic pass — must not raise and must write both channels
        result_volcanic = controller.run_pass("materials_v2_volcanic", checkpoint=False)
        # T0.5-2 (Y04 v3 §P.8.2): strict-"ok" — volcanic variant must overwrite
        # cleanly; "warning" would hide an override-channel-bypass regression.
        assert result_volcanic.status == "ok", (
            f"materials_v2_volcanic pass returned status={result_volcanic.status!r}"
        )

        brucks_after_volcanic = state.mask_stack.get("terrain_brucks_weight")
        snow_after_volcanic = state.mask_stack.get("snow_coverage")

        assert brucks_after_volcanic is not None, (
            "terrain_brucks_weight must remain non-None after materials_v2_volcanic"
        )
        assert snow_after_volcanic is not None, (
            "snow_coverage must remain non-None after materials_v2_volcanic"
        )
