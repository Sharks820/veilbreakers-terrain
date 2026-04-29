"""Bundle H — Composition & Intent tests.

Covers saliency refinement, morphology templates, framing sightlines,
feature hierarchy/budget, rhythm analysis, and negative-space enforcement.
"""

from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    HeroFeatureSpec,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
    TerrainSceneRead,
)
from veilbreakers_terrain.handlers import terrain_masks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_height(tile: int = 32, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # Low frequency hill plus noise
    xs = np.linspace(-1.0, 1.0, tile + 1)
    ys = np.linspace(-1.0, 1.0, tile + 1)
    xv, yv = np.meshgrid(xs, ys)
    base = 50.0 * np.exp(-(xv ** 2 + yv ** 2) * 2.0)
    noise = rng.standard_normal((tile + 1, tile + 1)) * 1.5
    return (base + noise).astype(np.float64)


def _make_stack(tile: int = 32) -> TerrainMaskStack:
    h = _make_height(tile)
    stack = TerrainMaskStack(
        tile_size=tile,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )
    terrain_masks.compute_base_masks(h, 1.0, (0, 0), stack=stack, pass_name="test")
    return stack


def _set_channel(stack: TerrainMaskStack, channel: str, value):
    stack.set(channel, value, "test_fixture")
    return value


def _make_intent(
    *,
    vantages=(),
    hero_features=(),
    framing_clearance=3.0,
) -> TerrainIntentState:
    return TerrainIntentState(
        seed=1234,
        region_bounds=BBox(0.0, 0.0, 32.0, 32.0),
        tile_size=32,
        cell_size=1.0,
        hero_feature_specs=tuple(hero_features),
        composition_hints={
            "vantages": list(vantages),
            "framing_clearance_m": framing_clearance,
        },
        scene_read=TerrainSceneRead(
            timestamp=0.0,
            major_landforms=("hill",),
            focal_point=(16.0, 16.0, 50.0),
            hero_features_present=(),
            hero_features_missing=(),
            waterfall_chains=(),
            cave_candidates=(),
            protected_zones_in_region=(),
            edit_scope=BBox(0.0, 0.0, 32.0, 32.0),
            success_criteria=(),
            reviewer="test",
        ),
    )


def _make_state(stack: TerrainMaskStack, intent: TerrainIntentState) -> TerrainPipelineState:
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# Structural mask direct behavior tests
# ---------------------------------------------------------------------------


class TestStructuralMasks:
    def test_slope_and_curvature_match_analytic_plane_and_bowl(self):
        from veilbreakers_terrain.handlers.terrain_masks import (
            compute_curvature,
            compute_slope,
        )

        rows, cols = np.mgrid[0:5, 0:5].astype(np.float64)
        plane = cols * 2.0
        slope = compute_slope(plane, cell_size=1.0)
        np.testing.assert_allclose(slope, np.arctan(2.0), atol=1e-9)

        bowl = rows**2 + cols**2
        curvature = compute_curvature(bowl, cell_size=1.0)
        np.testing.assert_allclose(curvature[1:-1, 1:-1], 4.0, atol=1e-9)

    def test_concavity_convexity_ridge_basin_and_saliency_are_bounded(self):
        from veilbreakers_terrain.handlers.terrain_masks import (
            compute_concavity,
            compute_convexity,
            compute_curvature,
            compute_macro_saliency,
            detect_basins,
            extract_ridge_mask,
        )

        h = np.array(
            [
                [5.0, 4.0, 5.0, 8.0, 9.0],
                [4.0, 1.0, 4.0, 7.0, 8.0],
                [5.0, 4.0, 5.0, 6.0, 7.0],
                [8.0, 7.0, 6.0, 3.0, 6.0],
                [9.0, 8.0, 7.0, 6.0, 9.0],
            ],
            dtype=np.float64,
        )
        curvature = compute_curvature(h, 1.0)
        concavity = compute_concavity(curvature)
        convexity = compute_convexity(curvature)
        ridge = extract_ridge_mask(h, 1.0)
        basins = detect_basins(h, min_area=1)
        saliency = compute_macro_saliency(h, curvature, ridge)

        assert concavity.shape == h.shape
        assert convexity.shape == h.shape
        assert concavity.max() <= 1.0 and concavity.min() >= 0.0
        assert convexity.max() <= 1.0 and convexity.min() >= 0.0
        assert ridge.dtype == bool
        assert basins.dtype == np.int32
        assert basins[1, 1] != 0
        assert saliency.max() <= 1.0 and saliency.min() >= 0.0

    def test_compute_base_masks_populates_protocol_channels(self):
        from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks

        h = _make_height(tile=8)
        stack = compute_base_masks(h, 2.0, (2, 3), pass_name="mask_test")

        assert stack.tile_x == 2
        assert stack.tile_y == 3
        for channel in (
            "slope",
            "curvature",
            "concavity",
            "convexity",
            "ridge",
            "basin",
            "saliency_macro",
        ):
            assert getattr(stack, channel) is not None
            assert stack.populated_by_pass[channel] == "mask_test"


# ---------------------------------------------------------------------------
# Saliency tests
# ---------------------------------------------------------------------------


class TestSaliency:
    def test_sample_height_bilinear_interpolates_and_clamps_edges(self):
        from veilbreakers_terrain.handlers.terrain_saliency import _sample_height_bilinear

        height = np.array([[0.0, 10.0], [20.0, 30.0]], dtype=np.float64)

        assert _sample_height_bilinear(height, 0.5, 0.5) == pytest.approx(15.0)
        assert _sample_height_bilinear(height, -10.0, -10.0) == pytest.approx(0.0)
        assert _sample_height_bilinear(height, 99.0, 99.0) == pytest.approx(30.0)
        assert _sample_height_bilinear(np.array([[7.0]], dtype=np.float64), 0.5, 0.5) == pytest.approx(7.0)

    def test_compute_vantage_silhouettes_shape(self):
        from veilbreakers_terrain.handlers.terrain_saliency import compute_vantage_silhouettes

        stack = _make_stack()
        vantages = [(0.0, 0.0, 60.0), (30.0, 30.0, 60.0)]
        s = compute_vantage_silhouettes(stack, vantages, ray_count=32)
        assert s.shape == (2, 32)
        assert s.dtype == np.float64
        assert np.all(s >= 0.0)

    def test_compute_vantage_silhouettes_empty(self):
        from veilbreakers_terrain.handlers.terrain_saliency import compute_vantage_silhouettes

        stack = _make_stack()
        s = compute_vantage_silhouettes(stack, [], ray_count=16)
        assert s.shape == (0, 16)

    def test_rasterize_vantage_silhouettes_normalizes_ray_contributions(self):
        from veilbreakers_terrain.handlers.terrain_saliency import (
            _rasterize_vantage_silhouettes_onto_grid,
        )

        stack = _make_stack(tile=8)
        empty = _rasterize_vantage_silhouettes_onto_grid(stack, [], np.zeros((0, 0)))
        silhouettes = np.full((1, 8), 0.5, dtype=np.float64)
        raster = _rasterize_vantage_silhouettes_onto_grid(
            stack,
            [(0.0, 0.0, 20.0)],
            silhouettes,
        )

        assert empty.shape == stack.height.shape
        assert np.count_nonzero(empty) == 0
        assert raster.shape == stack.height.shape
        assert raster.max() == pytest.approx(1.0)
        assert raster.min() >= 0.0

    def test_compute_8factor_saliency_uses_vantage_mask_and_clamps(self):
        from veilbreakers_terrain.handlers.terrain_saliency import _compute_8factor_saliency

        stack = _make_stack(tile=12)
        zeros = np.zeros_like(stack.height, dtype=np.float64)
        ones = np.ones_like(stack.height, dtype=np.float64)

        sal_zero = _compute_8factor_saliency(stack, zeros)
        sal_one = _compute_8factor_saliency(stack, ones)

        assert sal_zero.shape == stack.height.shape
        assert sal_zero.min() >= 0.0
        assert sal_zero.max() <= 1.0
        assert float(sal_one.mean()) > float(sal_zero.mean())

    def test_auto_sculpt_positive_kind(self):
        from veilbreakers_terrain.handlers.terrain_saliency import auto_sculpt_around_feature

        stack = _make_stack()
        delta = auto_sculpt_around_feature(stack, (16.0, 16.0, 50.0), "pinnacle", 10.0)
        # Max is at the feature center region — must be positive
        assert float(delta.max()) > 0.0
        assert float(delta.min()) >= 0.0

    def test_auto_sculpt_negative_kind(self):
        from veilbreakers_terrain.handlers.terrain_saliency import auto_sculpt_around_feature

        stack = _make_stack()
        delta = auto_sculpt_around_feature(stack, (16.0, 16.0, 50.0), "canyon", 15.0)
        assert float(delta.min()) < 0.0

    def test_pass_saliency_refine_noop_without_vantages(self):
        from veilbreakers_terrain.handlers.terrain_saliency import pass_saliency_refine

        stack = _make_stack()
        intent = _make_intent(vantages=())
        state = _make_state(stack, intent)
        before = stack.saliency_macro.copy()
        result = pass_saliency_refine(state, None)
        assert result.status == "ok"
        assert result.metrics["vantage_count"] == 0
        assert result.metrics["scoring_factors"] == 8
        assert not np.allclose(stack.saliency_macro, before)
        assert stack.saliency_macro.max() <= 1.0
        assert stack.saliency_macro.min() >= 0.0

    def test_pass_saliency_refine_changes_with_vantages(self):
        from veilbreakers_terrain.handlers.terrain_saliency import pass_saliency_refine

        stack = _make_stack()
        intent = _make_intent(vantages=[(0.0, 0.0, 70.0), (32.0, 32.0, 70.0)])
        state = _make_state(stack, intent)
        before = stack.saliency_macro.copy()
        result = pass_saliency_refine(state, None)
        assert result.status == "ok"
        assert result.metrics["vantage_count"] == 2
        # Should modify saliency meaningfully
        assert not np.allclose(stack.saliency_macro, before)
        assert stack.saliency_macro.max() <= 1.0
        assert stack.saliency_macro.min() >= 0.0

    def test_register_saliency_pass(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        from veilbreakers_terrain.handlers.terrain_saliency import register_saliency_pass

        TerrainPassController.clear_registry()
        register_saliency_pass()
        assert "saliency_refine" in TerrainPassController.PASS_REGISTRY
        TerrainPassController.clear_registry()

    def test_saliency_quality_gate_flags_missing_flat_and_clipped_maps(self):
        from veilbreakers_terrain.handlers.terrain_saliency import _saliency_quality_gate

        missing = _make_stack(tile=8)
        object.__setattr__(missing, "saliency_macro", None)
        missing_issues = _saliency_quality_gate(None, missing)

        flat = _make_stack(tile=8)
        flat.set("saliency_macro", np.full_like(flat.height, 0.5, dtype=np.float64), "fixture")
        flat_issues = _saliency_quality_gate(None, flat)

        clipped = _make_stack(tile=8)
        clipped.set("saliency_macro", np.full_like(clipped.height, 0.99, dtype=np.float64), "fixture")
        clipped_issues = _saliency_quality_gate(None, clipped)

        varied = _make_stack(tile=8)
        varied.set(
            "saliency_macro",
            np.linspace(0.1, 0.9, varied.height.size, dtype=np.float64).reshape(varied.height.shape),
            "fixture",
        )
        varied_issues = _saliency_quality_gate(None, varied)

        assert {issue.code for issue in missing_issues} == {"SALIENCY_MACRO_MISSING"}
        assert "SALIENCY_FLAT" in {issue.code for issue in flat_issues}
        assert "SALIENCY_CLIPPED" in {issue.code for issue in clipped_issues}
        assert varied_issues == []


# ---------------------------------------------------------------------------
# Morphology tests
# ---------------------------------------------------------------------------


class TestMorphology:
    def test_template_param_helpers_set_sign_and_shape_fields(self):
        from veilbreakers_terrain.handlers.terrain_morphology import (
            _canyon_params,
            _mesa_params,
            _pinnacle_params,
            _ridge_params,
            _spur_params,
            _valley_params,
        )

        assert _ridge_params(10.0, 0.2) == {"height_m": 10.0, "jaggedness": 0.2, "sign": 1.0}
        assert _canyon_params(20.0, 0.7) == {"depth_m": 20.0, "rim_sharpness": 0.7, "sign": -1.0}
        assert _mesa_params(30.0, 0.8) == {"height_m": 30.0, "flat_top": 0.8, "sign": 1.0}
        assert _pinnacle_params(40.0, 0.9) == {"height_m": 40.0, "spike": 0.9, "sign": 1.0}
        assert _spur_params(50.0, 0.4) == {"height_m": 50.0, "taper": 0.4, "sign": 1.0}
        assert _valley_params(60.0, 0.5) == {"depth_m": 60.0, "broadness": 0.5, "sign": -1.0}

    def test_rng_template_lookup_and_default_world_pos_are_deterministic(self):
        from veilbreakers_terrain.handlers.terrain_morphology import (
            _default_world_pos,
            _rng_from_seed,
            _template_by_id,
        )

        stack = _make_stack(tile=8)
        rng_a = _rng_from_seed(123)
        rng_b = _rng_from_seed(123)

        np.testing.assert_array_equal(rng_a.integers(0, 100, size=5), rng_b.integers(0, 100, size=5))
        assert _template_by_id("ridge_low_rolling").template_id == "ridge_low_rolling"
        assert _template_by_id("missing") is None
        assert _default_world_pos(stack) == pytest.approx((4.5, 4.5, float(stack.height.mean())))

    def test_default_templates_count(self):
        from veilbreakers_terrain.handlers.terrain_morphology import DEFAULT_TEMPLATES

        assert len(DEFAULT_TEMPLATES) >= 30
        # Ensure we have the 6 required kinds
        kinds = {t.kind for t in DEFAULT_TEMPLATES}
        for k in ("ridge_spur", "canyon", "mesa", "pinnacle", "spur", "valley"):
            assert k in kinds, f"missing kind {k}"

    def test_template_ids_unique(self):
        from veilbreakers_terrain.handlers.terrain_morphology import DEFAULT_TEMPLATES

        ids = [t.template_id for t in DEFAULT_TEMPLATES]
        assert len(ids) == len(set(ids))

    def test_apply_ridge_produces_positive_delta(self):
        from veilbreakers_terrain.handlers.terrain_morphology import (
            DEFAULT_TEMPLATES,
            apply_morphology_template,
        )

        stack = _make_stack(tile=48)
        ridge = next(t for t in DEFAULT_TEMPLATES if t.kind == "ridge_spur")
        delta = apply_morphology_template(stack, ridge, (24.0, 24.0, 50.0), seed=42)
        assert delta.shape == stack.height.shape
        assert float(delta.max()) > 0.0

    def test_apply_canyon_produces_negative_delta(self):
        from veilbreakers_terrain.handlers.terrain_morphology import (
            DEFAULT_TEMPLATES,
            apply_morphology_template,
        )

        stack = _make_stack(tile=48)
        canyon = next(t for t in DEFAULT_TEMPLATES if t.kind == "canyon")
        delta = apply_morphology_template(stack, canyon, (24.0, 24.0, 50.0), seed=42)
        assert float(delta.min()) < 0.0

    def test_template_deterministic(self):
        from veilbreakers_terrain.handlers.terrain_morphology import (
            DEFAULT_TEMPLATES,
            apply_morphology_template,
        )

        stack = _make_stack(tile=32)
        t = DEFAULT_TEMPLATES[0]
        d1 = apply_morphology_template(stack, t, (16.0, 16.0, 50.0), seed=100)
        d2 = apply_morphology_template(stack, t, (16.0, 16.0, 50.0), seed=100)
        np.testing.assert_array_equal(d1, d2)

    def test_pass_morphology_writes_deferred_delta_from_intent_template(self):
        from veilbreakers_terrain.handlers.terrain_morphology import pass_morphology

        stack = _make_stack(tile=48)
        intent = TerrainIntentState(
            seed=42,
            region_bounds=BBox(0.0, 0.0, 48.0, 48.0),
            tile_size=48,
            cell_size=1.0,
            morphology_templates=("ridge_low_rolling",),
        )
        state = _make_state(stack, intent)

        result = pass_morphology(state, None)

        assert result.status == "ok"
        assert result.metrics["applied_template_count"] == 1
        assert result.metrics["unknown_template_count"] == 0
        assert "morphology_delta" in result.produced_channels
        assert stack.morphology_delta is not None
        assert stack.morphology_delta.dtype == np.float32
        assert float(np.max(np.abs(stack.morphology_delta))) > 0.0

    def test_pass_morphology_warns_and_keeps_channel_for_unknown_template(self):
        from veilbreakers_terrain.handlers.terrain_morphology import pass_morphology

        stack = _make_stack(tile=32)
        intent = TerrainIntentState(
            seed=99,
            region_bounds=BBox(0.0, 0.0, 32.0, 32.0),
            tile_size=32,
            cell_size=1.0,
            composition_hints={
                "morphology_specs": [
                    {"template_id": "missing_template", "world_pos": (16.0, 16.0, 20.0)}
                ]
            },
        )
        state = _make_state(stack, intent)

        result = pass_morphology(state, None)

        assert result.status == "warning"
        assert result.metrics["applied_template_count"] == 0
        assert result.metrics["unknown_template_count"] == 1
        assert result.warnings and result.warnings[0].code == "UNKNOWN_MORPHOLOGY_TEMPLATE"
        assert stack.morphology_delta is not None
        assert np.count_nonzero(stack.morphology_delta) == 0

    def test_list_templates_for_biome(self):
        from veilbreakers_terrain.handlers.terrain_morphology import list_templates_for_biome

        alpine = list_templates_for_biome("alpine")
        desert = list_templates_for_biome("desert")
        unknown = list_templates_for_biome("???")
        assert len(alpine) > 0
        assert len(desert) > 0
        # Desert should contain at least one mesa
        assert any(t.kind == "mesa" for t in desert)
        # Unknown returns the full catalog
        assert len(unknown) >= 30

    def test_register_morphology_pass(self):
        from veilbreakers_terrain.handlers.terrain_morphology import register_morphology_pass
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

        TerrainPassController.clear_registry()
        register_morphology_pass()
        assert "pass_morphology" in TerrainPassController.PASS_REGISTRY
        pass_def = TerrainPassController.PASS_REGISTRY["pass_morphology"]
        assert pass_def.produces_channels == ("morphology_delta",)
        TerrainPassController.clear_registry()

    def test_get_natural_arch_specs_places_mesh_specs(self, monkeypatch):
        import veilbreakers_terrain.handlers.terrain_features as terrain_features
        from veilbreakers_terrain.handlers.terrain_morphology import get_natural_arch_specs

        monkeypatch.setattr(
            terrain_features,
            "generate_natural_arch",
            lambda **kwargs: {"vertices": [(0, 0, 0)], "faces": [], "metadata": kwargs},
        )
        stack = _make_stack(tile=12)

        specs = get_natural_arch_specs(stack, max_arches=2, seed=1)

        assert 0 < len(specs) <= 2
        assert specs[0]["mesh_spec"]["vertices"] == [(0, 0, 0)]
        assert len(specs[0]["world_pos"]) == 3


# ---------------------------------------------------------------------------
# Framing tests
# ---------------------------------------------------------------------------


class TestFraming:
    def test_enforce_sightline_nonzero_for_obstructed(self):
        from veilbreakers_terrain.handlers.terrain_framing import enforce_sightline

        stack = _make_stack(tile=48)
        # Vantage at low altitude looking at a target across the hill crest
        delta = enforce_sightline(stack, (4.0, 24.0, 20.0), (44.0, 24.0, 20.0), clearance_m=2.0)
        assert delta.shape == stack.height.shape
        # Should cut something (hill in the middle is ~50m tall)
        assert float(delta.min()) < 0.0

    def test_enforce_sightline_zero_for_coincident(self):
        from veilbreakers_terrain.handlers.terrain_framing import enforce_sightline

        stack = _make_stack()
        delta = enforce_sightline(stack, (5.0, 5.0, 10.0), (5.0, 5.0, 10.0), clearance_m=2.0)
        assert float(np.abs(delta).max()) == 0.0

    def test_pass_framing_noop_when_no_features(self):
        from veilbreakers_terrain.handlers.terrain_framing import pass_framing

        stack = _make_stack()
        intent = _make_intent(vantages=[(0.0, 0.0, 20.0)], hero_features=())
        state = _make_state(stack, intent)
        before = stack.height.copy()
        result = pass_framing(state, None)
        assert result.status == "ok"
        assert result.metrics.get("noop") is True
        np.testing.assert_array_equal(stack.height, before)

    def test_pass_framing_cuts_obstacles(self):
        from veilbreakers_terrain.handlers.terrain_framing import pass_framing

        stack = _make_stack(tile=48)
        hero = HeroFeatureSpec(
            feature_id="h1",
            feature_kind="pinnacle",
            world_position=(44.0, 24.0, 20.0),
        )
        intent = _make_intent(
            vantages=[(4.0, 24.0, 20.0)],
            hero_features=(hero,),
            framing_clearance=3.0,
        )
        state = _make_state(stack, intent)
        before = stack.height.copy()
        result = pass_framing(state, None)
        assert result.status == "ok"
        assert result.metrics["sightlines_applied"] == 1
        assert result.metrics["max_cut_m"] >= 0.0
        # Height must not have risen anywhere
        assert float((stack.height - before).max()) <= 1e-9

    def test_register_framing_pass(self):
        from veilbreakers_terrain.handlers.terrain_framing import register_framing_pass
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

        TerrainPassController.clear_registry()
        register_framing_pass()
        assert "framing" in TerrainPassController.PASS_REGISTRY
        TerrainPassController.clear_registry()


# ---------------------------------------------------------------------------
# Hierarchy tests
# ---------------------------------------------------------------------------


class TestHierarchy:
    def test_feature_tier_from_str(self):
        from veilbreakers_terrain.handlers.terrain_hierarchy import FeatureTier

        assert FeatureTier.from_str("primary") == FeatureTier.PRIMARY
        assert FeatureTier.from_str("AMBIENT") == FeatureTier.AMBIENT
        assert FeatureTier.from_str("nonsense") == FeatureTier.SECONDARY

    def test_classify_cinematic_kind_forced_primary(self):
        from veilbreakers_terrain.handlers.terrain_hierarchy import FeatureTier, classify_feature_tier

        f = HeroFeatureSpec(
            feature_id="c",
            feature_kind="canyon",
            world_position=(1.0, 1.0, 1.0),
            tier="tertiary",
        )
        tier = classify_feature_tier(f)
        assert tier == FeatureTier.PRIMARY

    def test_classify_saliency_promotion(self):
        from veilbreakers_terrain.handlers.terrain_hierarchy import FeatureTier, classify_feature_tier

        stack = _make_stack()
        # Force saliency high at a known position
        stack.saliency_macro[16, 16] = 0.95
        f = HeroFeatureSpec(
            feature_id="s",
            feature_kind="spire",
            world_position=(16.0, 16.0, 50.0),
            tier="tertiary",
        )
        tier = classify_feature_tier(f, stack=stack)
        # Expect promotion from tertiary -> secondary
        assert tier in (FeatureTier.SECONDARY, FeatureTier.PRIMARY)

    def test_enforce_feature_budget_prunes(self):
        from veilbreakers_terrain.handlers.terrain_hierarchy import (
            DEFAULT_BUDGETS,
            FeatureTier,
            enforce_feature_budget,
        )

        features = [
            {"feature_id": f"f{i}", "footprint_m": 50.0} for i in range(50)
        ]
        pruned = enforce_feature_budget(features, DEFAULT_BUDGETS[FeatureTier.PRIMARY])
        # Primary tier max is 0.5 per km² -> rounds to 1
        assert len(pruned) <= 1

    def test_enforce_feature_budget_drops_oversized(self):
        from veilbreakers_terrain.handlers.terrain_hierarchy import (
            DEFAULT_BUDGETS,
            FeatureTier,
            enforce_feature_budget,
        )

        features = [
            {"feature_id": "small", "footprint_m": 20.0},
            {"feature_id": "giant", "footprint_m": 9999.0},
        ]
        pruned = enforce_feature_budget(features, DEFAULT_BUDGETS[FeatureTier.AMBIENT])
        ids = {f["feature_id"] for f in pruned}
        assert "giant" not in ids
        assert "small" in ids


# ---------------------------------------------------------------------------
# Rhythm tests
# ---------------------------------------------------------------------------


class TestRhythm:
    def test_empty_rhythm(self):
        from veilbreakers_terrain.handlers.terrain_rhythm import analyze_feature_rhythm

        bounds = BBox(0.0, 0.0, 1000.0, 1000.0)
        result = analyze_feature_rhythm([], bounds)
        assert result["count"] == 0
        assert result["rhythm"] == 0.0

    def test_regular_grid_has_high_rhythm(self):
        from veilbreakers_terrain.handlers.terrain_rhythm import analyze_feature_rhythm

        # 5x5 perfect grid
        pts = [(float(x * 100), float(y * 100)) for x in range(5) for y in range(5)]
        bounds = BBox(0.0, 0.0, 500.0, 500.0)
        result = analyze_feature_rhythm(pts, bounds)
        # Perfectly regular grid nn distances are all equal -> cv ~0 -> rhythm ~1
        assert result["rhythm"] > 0.9

    def test_random_has_lower_rhythm(self):
        from veilbreakers_terrain.handlers.terrain_rhythm import analyze_feature_rhythm

        rng = np.random.default_rng(99)
        pts = [(float(x), float(y)) for x, y in rng.uniform(0, 500, size=(25, 2))]
        bounds = BBox(0.0, 0.0, 500.0, 500.0)
        result = analyze_feature_rhythm(pts, bounds)
        assert result["rhythm"] < 0.9

    def test_enforce_rhythm_with_dicts(self):
        from veilbreakers_terrain.handlers.terrain_rhythm import enforce_rhythm

        rng = np.random.default_rng(5)
        features = [
            {"feature_id": f"f{i}", "world_position": (float(x), float(y), 0.0)}
            for i, (x, y) in enumerate(rng.uniform(0, 200, size=(10, 2)))
        ]
        out = enforce_rhythm(features)
        assert len(out) == len(features)
        assert all("world_position" in f for f in out)

    def test_validate_rhythm_flags_random(self):
        from veilbreakers_terrain.handlers.terrain_rhythm import validate_rhythm

        rng = np.random.default_rng(1)
        pts = [(float(x), float(y)) for x, y in rng.uniform(0, 500, size=(30, 2))]
        bounds = BBox(0.0, 0.0, 500.0, 500.0)
        # validate_rhythm returns a per-type dict: {feature_type: [ValidationIssue]}
        result = validate_rhythm(pts, bounds, min_rhythm=0.99)
        assert isinstance(result, dict)
        all_issues = [issue for issues in result.values() for issue in issues]
        assert len(all_issues) >= 1
        codes = {i.code for i in all_issues}
        assert "rhythm.too_random" in codes


# ---------------------------------------------------------------------------
# Negative space tests
# ---------------------------------------------------------------------------


class TestNegativeSpace:
    def test_compute_quiet_zone_ratio_empty(self):
        from veilbreakers_terrain.handlers.terrain_negative_space import compute_quiet_zone_ratio

        tile = 16
        stack = TerrainMaskStack(
            tile_size=tile,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
            height=np.zeros((tile + 1, tile + 1), dtype=np.float64),
        )
        # No saliency_macro yet -> 0
        assert compute_quiet_zone_ratio(stack) == 0.0

    def test_quiet_zone_ratio_with_saliency(self):
        from veilbreakers_terrain.handlers.terrain_negative_space import compute_quiet_zone_ratio

        stack = _make_stack()
        _set_channel(stack, "saliency_macro", np.zeros_like(stack.saliency_macro))
        stack.saliency_macro[:16, :] = 0.9  # half busy
        ratio = compute_quiet_zone_ratio(stack)
        assert ratio == pytest.approx(
            (stack.saliency_macro < 0.3).sum() / stack.saliency_macro.size
        )

    def test_enforce_quiet_zone_meets_min_ratio(self):
        from veilbreakers_terrain.handlers.terrain_negative_space import enforce_quiet_zone

        stack = _make_stack()
        # Force everything busy
        _set_channel(stack, "saliency_macro", np.ones_like(stack.saliency_macro) * 0.9)
        mask = enforce_quiet_zone(stack, min_ratio=0.5)
        assert mask.dtype == bool
        assert mask.sum() / mask.size >= 0.5

    def test_validate_negative_space_passes_when_quiet(self):
        from veilbreakers_terrain.handlers.terrain_negative_space import validate_negative_space

        stack = _make_stack()
        _set_channel(stack, "saliency_macro", np.zeros_like(stack.saliency_macro))
        issues = validate_negative_space(stack, min_ratio=0.4)
        # A fully quiet saliency map must not trip any validator:
        # no insufficient quiet zone, no density budget overflow, no
        # peak-spacing violation (there are no peaks at all).
        assert issues == []

    def test_validate_negative_space_flags_busy(self):
        from veilbreakers_terrain.handlers.terrain_negative_space import validate_negative_space

        stack = _make_stack()
        _set_channel(stack, "saliency_macro", np.ones_like(stack.saliency_macro) * 0.9)
        issues = validate_negative_space(stack, min_ratio=0.4)
        # A fully busy map trips quiet-zone, feature-density, AND
        # peak-spacing validators — all three signals are legitimate
        # for a "wall of detail" scene.
        codes = {i.code for i in issues}
        assert "negative_space.insufficient" in codes
        assert "negative_space.feature_density_too_high" in codes
        assert "negative_space.peaks_too_close" in codes
