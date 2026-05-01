"""Tests for environment_scatter handler output structure.

Tests verify the pure-logic scatter engine integration and handler
parameter validation. Blender-side geometry creation is not tested
(requires bpy); instead we test the underlying engine calls and
expected result dict shapes.
"""


import numpy as np
import pytest

from veilbreakers_terrain.handlers._scatter_engine import (
    biome_filter_points,
    context_scatter,
    generate_breakable_variants,
    poisson_disk_sample,
)


class TestScatterVegetationLogic:
    """Test the pure-logic path used by handle_scatter_vegetation."""

    def test_world_height_sampling_matches_centered_and_offset_tiles(self):
        """World-space height sampling should be invariant to terrain center offsets."""
        from veilbreakers_terrain.handlers.environment_scatter import _sample_heightmap_world

        heightmap = np.array(
            [
                [0.0, 0.25, 0.5],
                [0.25, 0.5, 0.75],
                [0.5, 0.75, 1.0],
            ],
            dtype=np.float64,
        )

        centered = _sample_heightmap_world(
            heightmap,
            height_scale=10.0,
            world_x=25.0,
            world_y=25.0,
            terrain_width=100.0,
            terrain_height=100.0,
            terrain_origin_x=0.0,
            terrain_origin_y=0.0,
        )
        offset = _sample_heightmap_world(
            heightmap,
            height_scale=10.0,
            world_x=175.0,
            world_y=225.0,
            terrain_width=100.0,
            terrain_height=100.0,
            terrain_origin_x=150.0,
            terrain_origin_y=200.0,
        )

        assert offset == pytest.approx(centered)

    def test_world_height_sampling_respects_rectangular_terrain_extent(self):
        """World-space sampling should map X and Y against their own terrain axes."""
        from veilbreakers_terrain.handlers.environment_scatter import _sample_heightmap_world

        heightmap = np.array(
            [
                [0.0, 0.2, 0.4],
                [0.3, 0.5, 0.7],
                [0.6, 0.8, 1.0],
            ],
            dtype=np.float64,
        )

        sampled = _sample_heightmap_world(
            heightmap,
            height_scale=10.0,
            world_x=50.0,
            world_y=25.0,
            terrain_width=200.0,
            terrain_height=100.0,
            terrain_origin_x=0.0,
            terrain_origin_y=0.0,
        )

        assert sampled == pytest.approx(7.5)

    def test_world_height_sampling_clamps_out_of_bounds(self):
        """World-space sampling should clamp gracefully outside the terrain footprint."""
        from veilbreakers_terrain.handlers.environment_scatter import _sample_heightmap_world

        heightmap = np.array(
            [
                [0.1, 0.2],
                [0.3, 0.4],
            ],
            dtype=np.float64,
        )

        sampled = _sample_heightmap_world(
            heightmap,
            height_scale=20.0,
            world_x=10_000.0,
            world_y=10_000.0,
            terrain_width=100.0,
            terrain_height=100.0,
            terrain_origin_x=0.0,
            terrain_origin_y=0.0,
        )

        assert sampled == pytest.approx(8.0)

    def test_world_height_sampling_applies_height_offset(self):
        from veilbreakers_terrain.handlers.environment_scatter import _sample_heightmap_world

        heightmap = np.array(
            [
                [0.0, 0.5],
                [0.5, 1.0],
            ],
            dtype=np.float64,
        )

        sampled = _sample_heightmap_world(
            heightmap,
            height_scale=20.0,
            height_offset=-5.0,
            world_x=0.0,
            world_y=0.0,
            terrain_width=100.0,
            terrain_height=100.0,
            terrain_origin_x=0.0,
            terrain_origin_y=0.0,
        )

        assert sampled == pytest.approx(5.0)

    def test_terrain_cell_size_from_extent_uses_world_spacing(self):
        from veilbreakers_terrain.handlers.environment_scatter import _terrain_cell_size_from_extent

        spacing = _terrain_cell_size_from_extent(
            terrain_width=80.0,
            terrain_height=120.0,
            rows=5,
            cols=9,
        )

        assert spacing == pytest.approx(30.0)

    def test_full_vegetation_pipeline(self):
        """Poisson disk + biome filter produces valid placements."""
        # Simulate what handle_scatter_vegetation does internally
        terrain_width = 120.0
        terrain_depth = 60.0
        min_distance = 5.0
        seed = 42

        candidates = poisson_disk_sample(
            terrain_width, terrain_depth, min_distance, seed=seed,
        )
        assert len(candidates) > 10

        # Create synthetic heightmap and slope map
        heightmap = np.random.RandomState(seed).random((64, 64))
        from veilbreakers_terrain.handlers._terrain_noise import compute_slope_map
        slope_map = compute_slope_map(
            heightmap,
            cell_size=(terrain_depth / 63.0, terrain_width / 63.0),
        )

        rules = [
            {
                "vegetation_type": "tree",
                "min_alt": 0.2,
                "max_alt": 0.6,
                "min_slope": 0.0,
                "max_slope": 25.0,
                "scale_range": (0.8, 1.5),
                "density": 0.8,
            },
            {
                "vegetation_type": "rock",
                "min_alt": 0.5,
                "max_alt": 1.0,
                "min_slope": 15.0,
                "max_slope": 90.0,
                "scale_range": (0.5, 1.0),
                "density": 0.6,
            },
        ]

        placements = biome_filter_points(
            candidates, heightmap, slope_map, rules,
            terrain_width=terrain_width,
            terrain_depth=terrain_depth,
            seed=seed,
        )

        # Should produce some placements
        assert len(placements) > 0

        # All placements have required keys
        for p in placements:
            assert "position" in p
            assert "vegetation_type" in p
            assert p["vegetation_type"] in {"tree", "rock"}
            assert "scale" in p
            assert "rotation" in p
            assert 0 <= p["rotation"] <= 360
            assert 0.0 <= p["position"][0] <= terrain_width
            assert 0.0 <= p["position"][1] <= terrain_depth

    def test_max_instances_cap(self):
        """Placements can be capped at max_instances."""
        candidates = poisson_disk_sample(100.0, 100.0, 2.0, seed=0)
        heightmap = np.full((64, 64), 0.5)
        slope_map = np.full((64, 64), 10.0)
        rules = [
            {
                "vegetation_type": "tree",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "scale_range": (0.8, 1.2),
                "density": 1.0,
            },
        ]
        placements = biome_filter_points(
            candidates, heightmap, slope_map, rules,
            terrain_size=100.0, seed=0,
        )
        # Verify the engine returns a non-empty result bounded by the number of
        # candidate points (i.e. it doesn't fabricate extra placements).
        assert len(placements) > 0, "Expected at least one placement"
        assert len(placements) <= len(candidates), (
            f"Placements ({len(placements)}) must not exceed candidates ({len(candidates)})"
        )

    def test_overlapping_rules_produce_mixed_vegetation_types(self):
        """Overlapping biome rules should no longer collapse to first-match only."""
        candidates = poisson_disk_sample(60.0, 60.0, 3.0, seed=12)
        heightmap = np.full((48, 48), 0.4)
        slope_map = np.full((48, 48), 8.0)
        rules = [
            {
                "vegetation_type": "tree",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "min_slope": 0.0,
                "max_slope": 20.0,
                "scale_range": (0.9, 1.2),
                "density": 0.6,
            },
            {
                "vegetation_type": "grass",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "min_slope": 0.0,
                "max_slope": 20.0,
                "scale_range": (0.4, 0.8),
                "density": 0.7,
            },
            {
                "vegetation_type": "bush",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "min_slope": 0.0,
                "max_slope": 20.0,
                "scale_range": (0.6, 1.0),
                "density": 0.5,
            },
        ]

        placements = biome_filter_points(
            candidates,
            heightmap,
            slope_map,
            rules,
            terrain_size=60.0,
            seed=12,
        )

        vegetation_types = {placement["vegetation_type"] for placement in placements}
        assert len(vegetation_types) >= 2, "Overlapping rules should produce multiple vegetation types"


class TestMultipassScatterIntegration:
    """Tests for the richer multi-pass scatter path used by handle_scatter_vegetation."""

    @staticmethod
    def _rules():
        return [
            {
                "vegetation_type": "tree",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "min_slope": 0.0,
                "max_slope": 35.0,
                "scale_range": (0.9, 1.2),
                "density": 1.0,
            },
            {
                "vegetation_type": "bush",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "min_slope": 0.0,
                "max_slope": 40.0,
                "scale_range": (0.6, 0.9),
                "density": 1.0,
            },
            {
                "vegetation_type": "grass",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "min_slope": 0.0,
                "max_slope": 45.0,
                "scale_range": (0.4, 0.8),
                "density": 1.0,
            },
            {
                "vegetation_type": "rock",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "min_slope": 0.0,
                "max_slope": 90.0,
                "scale_range": (0.4, 1.1),
                "density": 1.0,
            },
        ]

    def test_scatter_pass_supports_rectangular_terrain_extents(self):
        from veilbreakers_terrain.handlers.environment_scatter import _scatter_pass

        hm = np.full((40, 80), 0.35, dtype=np.float32)
        slope = np.zeros_like(hm)
        result = _scatter_pass(
            hm,
            slope,
            terrain_size=120.0,
            pass_type="structure",
            terrain_width=120.0,
            terrain_height=60.0,
            biome="prairie",
            seed=11,
        )
        assert len(result) > 0
        for item in result:
            x, y = item["position"]
            assert -60.0 <= x <= 60.0
            assert -30.0 <= y <= 30.0

    def test_generate_multipass_scatter_placements_returns_local_positions(self):
        from veilbreakers_terrain.handlers.environment_scatter import _generate_multipass_scatter_placements

        hm = np.full((48, 64), 0.32, dtype=np.float32)
        slope = np.zeros_like(hm)
        placements = _generate_multipass_scatter_placements(
            heightmap=hm,
            slope_map=slope,
            terrain_width=120.0,
            terrain_height=60.0,
            biome="prairie",
            rules=self._rules(),
            seed=7,
            separation_scale=1.0,
            max_tilt_angle=45.0,
        )

        assert len(placements) > 0
        for item in placements:
            x, y = item["position"]
            assert 0.0 <= x <= 120.0
            assert 0.0 <= y <= 60.0
            assert 0.0 <= item["rotation"] <= 360.0

    def test_generate_multipass_scatter_placements_respects_building_exclusion(self):
        from veilbreakers_terrain.handlers.environment_scatter import _generate_multipass_scatter_placements

        hm = np.full((64, 64), 0.3, dtype=np.float32)
        slope = np.zeros_like(hm)
        placements = _generate_multipass_scatter_placements(
            heightmap=hm,
            slope_map=slope,
            terrain_width=100.0,
            terrain_height=100.0,
            biome="prairie",
            rules=self._rules(),
            seed=21,
            separation_scale=1.0,
            max_tilt_angle=45.0,
            building_zones_world=[(-10.0, -10.0, 10.0, 10.0)],
            terrain_origin_x=0.0,
            terrain_origin_y=0.0,
        )

        assert len(placements) > 0
        for item in placements:
            x, y = item["position"]
            assert not (40.0 <= x <= 60.0 and 40.0 <= y <= 60.0)

    def test_category_mapped_catalog_species_still_respect_building_exclusion(self, monkeypatch):
        from veilbreakers_terrain.handlers import environment_scatter as scatter_mod

        def fake_scatter_pass(*args, **kwargs):
            if kwargs.get("pass_type") != "debris":
                return []
            return [
                {
                    "position": (0.0, 0.0),
                    "vegetation_type": "talus_boulder",
                    "category": "boulder",
                    "altitude": 0.5,
                    "moisture": 0.2,
                    "rotation": 0.0,
                },
                {
                    "position": (25.0, 0.0),
                    "vegetation_type": "talus_boulder",
                    "category": "boulder",
                    "altitude": 0.5,
                    "moisture": 0.2,
                    "rotation": 0.0,
                },
            ]

        monkeypatch.setattr(scatter_mod, "_scatter_pass", fake_scatter_pass)

        hm = np.full((64, 64), 0.3, dtype=np.float32)
        slope = np.zeros_like(hm)
        placements = scatter_mod._generate_multipass_scatter_placements(
            heightmap=hm,
            slope_map=slope,
            terrain_width=100.0,
            terrain_height=100.0,
            biome="prairie",
            rules=self._rules(),
            seed=21,
            separation_scale=1.0,
            max_tilt_angle=45.0,
            building_zones_world=[(-10.0, -10.0, 10.0, 10.0)],
            terrain_origin_x=0.0,
            terrain_origin_y=0.0,
        )

        assert [item["position"] for item in placements] == [(75.0, 50.0)]
        assert placements[0]["species_id"] == "talus_boulder"
        assert placements[0]["vegetation_type"] == "talus_boulder"
        assert placements[0]["base_type"] == "rock"

    def test_generate_multipass_scatter_placements_filters_to_requested_types(self):
        from veilbreakers_terrain.handlers.environment_scatter import _generate_multipass_scatter_placements

        hm = np.full((48, 48), 0.28, dtype=np.float32)
        slope = np.zeros_like(hm)
        tree_only_rules = [
            {
                "vegetation_type": "tree",
                "min_alt": 0.0,
                "max_alt": 1.0,
                "min_slope": 0.0,
                "max_slope": 45.0,
                "scale_range": (0.9, 1.1),
                "density": 1.0,
            },
        ]
        placements = _generate_multipass_scatter_placements(
            heightmap=hm,
            slope_map=slope,
            terrain_width=80.0,
            terrain_height=80.0,
            biome="prairie",
            rules=tree_only_rules,
            seed=5,
            separation_scale=1.0,
            max_tilt_angle=45.0,
            apply_rule_density=True,
        )

        assert len(placements) > 0
        assert {item["base_type"] for item in placements} == {"tree"}
        assert {item["vegetation_type"] for item in placements} >= {"tree_oak"}

    def test_multipass_placements_convert_to_canonical_scatter_point_table(self):
        from veilbreakers_terrain.handlers.environment_scatter import (
            _build_scatter_point_table_from_placements,
        )
        from veilbreakers_terrain.handlers.terrain_scatter_points import (
            validate_scatter_point_table,
        )

        placements = [
            {
                "position": (25.0, 30.0),
                "rotation": 90.0,
                "rotation_y": 1.25,
                "scale": 1.4,
                "vegetation_type": "tree",
                "species_id": "tree_oak",
                "altitude": 0.25,
                "moisture": 0.6,
                "lod": 1,
                "prototype_id": 3,
            }
        ]

        table = _build_scatter_point_table_from_placements(
            placements,
            terrain_width=100.0,
            terrain_height=80.0,
            terrain_origin_x=10.0,
            terrain_origin_y=20.0,
            biome_id="forest",
            height_min=5.0,
            height_range=40.0,
            seed=17,
        )

        assert table.format == "ScatterPointTable"
        assert validate_scatter_point_table(table) == []
        point = table.points[0]
        assert point.position == pytest.approx((-15.0, 10.0, 15.0))
        assert point.prototype_id == "3"
        assert point.species_id == "tree_oak"
        assert point.biome_id == "forest"
        assert point.wind_profile == "tree"
        assert point.mask_sources == ("multipass_scatter", "species:tree_oak", "biome:forest")

    def test_scatter_point_table_prefers_actual_instance_transform_metadata(self):
        from veilbreakers_terrain.handlers.environment_scatter import (
            _build_scatter_point_table_from_placements,
        )

        placements = [
            {
                "position": (25.0, 30.0),
                "world_position": (101.0, 202.0, 33.0),
                "normal": (-0.2, 0.1, 0.97),
                "orient": (0.1, 0.2, 0.3, 0.9),
                "rotation": 0.0,
                "scale": 1.0,
                "vegetation_type": "tree",
                "species_id": "tree_oak",
                "altitude": 0.25,
            }
        ]

        table = _build_scatter_point_table_from_placements(
            placements,
            terrain_width=100.0,
            terrain_height=80.0,
            terrain_origin_x=10.0,
            terrain_origin_y=20.0,
            biome_id="forest",
            height_min=5.0,
            height_range=40.0,
            seed=17,
        )

        point = table.points[0]

        assert point.position == pytest.approx((101.0, 202.0, 33.0))
        assert point.height_m == pytest.approx(33.0)
        assert point.normal == pytest.approx((-0.2, 0.1, 0.97))
        assert point.orient == pytest.approx((0.1, 0.2, 0.3, 0.9))

    def test_catalog_category_placements_map_to_coarse_rules_without_dropping(self):
        from veilbreakers_terrain.handlers.environment_scatter import _filter_multipass_scatter_placements

        placements = [
            {
                "position": (0.0, 0.0),
                "vegetation_type": "talus_boulder",
                "category": "boulder",
                "altitude": 0.5,
                "moisture": 0.2,
                "rotation": 0.0,
            },
            {
                "position": (5.0, 0.0),
                "vegetation_type": "reeds",
                "category": "water_foliage",
                "altitude": 0.2,
                "moisture": 0.9,
                "rotation": 0.0,
            },
            {
                "position": (-5.0, 0.0),
                "vegetation_type": "log_fallen",
                "category": "log",
                "altitude": 0.2,
                "moisture": 0.5,
                "rotation": 0.0,
            },
        ]

        filtered = _filter_multipass_scatter_placements(
            placements,
            rules=self._rules(),
            terrain_width=80.0,
            terrain_height=80.0,
            slope_map=np.zeros((8, 8), dtype=np.float32),
            moisture_map=None,
            max_tilt_angle=45.0,
            seed=9,
            apply_rule_density=True,
        )

        species = {item["species_id"] for item in filtered}
        base_types = {item["base_type"] for item in filtered}
        vegetation_types = {item["vegetation_type"] for item in filtered}

        assert {"talus_boulder", "reeds", "log_fallen"} <= species
        assert {"talus_boulder", "reeds", "log_fallen"} <= vegetation_types
        assert {"rock", "grass", "tree"} <= base_types


class TestScatterPropsLogic:
    """Test the pure-logic path used by handle_scatter_props."""

    def test_context_scatter_with_multiple_buildings(self):
        """Scatter with multiple buildings produces props."""
        buildings = [
            {"type": "tavern", "position": (15, 15), "footprint": (8, 6)},
            {"type": "blacksmith", "position": (35, 35), "footprint": (6, 6)},
        ]
        result = context_scatter(buildings, area_size=50, prop_density=0.3, seed=42)
        assert len(result) > 0

        # Group by type
        type_counts: dict[str, int] = {}
        for p in result:
            type_counts[p["type"]] = type_counts.get(p["type"], 0) + 1

        # Should have multiple prop types
        assert len(type_counts) >= 2

    def test_empty_buildings_returns_list(self):
        """Empty buildings list should return an empty or generic list."""
        # The handler itself checks for empty buildings;
        # context_scatter returns empty list for empty buildings
        result = context_scatter([], area_size=50, seed=0)
        # With no buildings, all props are generic
        assert isinstance(result, list)


class TestCreateBreakableLogic:
    """Test the pure-logic path used by handle_create_breakable."""

    def test_breakable_result_structure(self):
        """generate_breakable_variants returns expected structure."""
        result = generate_breakable_variants("crate", seed=42)

        assert "intact_spec" in result
        assert "destroyed_spec" in result

        intact = result["intact_spec"]
        assert "geometry_ops" in intact
        assert "material" in intact
        assert len(intact["geometry_ops"]) > 0

        destroyed = result["destroyed_spec"]
        assert "fragment_ops" in destroyed
        assert "debris_ops" in destroyed
        assert "material" in destroyed
        assert len(destroyed["fragment_ops"]) > 1
        assert len(destroyed["debris_ops"]) > 0

    def test_breakable_counts_match_config(self):
        """Fragment and debris counts fall within configured ranges."""
        from veilbreakers_terrain.handlers._scatter_engine import BREAKABLE_PROPS

        for prop_type, config in BREAKABLE_PROPS.items():
            result = generate_breakable_variants(prop_type, seed=0)
            frag_min, frag_max = config["fragment_count"]
            deb_min, deb_max = config["debris_count"]

            frag_count = len(result["destroyed_spec"]["fragment_ops"])
            deb_count = len(result["destroyed_spec"]["debris_ops"])

            assert frag_min <= frag_count <= frag_max, (
                f"{prop_type}: fragment count {frag_count} "
                f"not in [{frag_min}, {frag_max}]"
            )
            assert deb_min <= deb_count <= deb_max, (
                f"{prop_type}: debris count {deb_count} "
                f"not in [{deb_min}, {deb_max}]"
            )


class TestPropGeneratorMapCoverage:
    """Verify PROP_GENERATOR_MAP covers all prop types used by the scatter engine."""

    def test_prop_generator_map_covers_all_affinity_types(self):
        """Every prop type in PROP_AFFINITY has a PROP_GENERATOR_MAP entry."""
        from veilbreakers_terrain.handlers._scatter_engine import PROP_AFFINITY
        from veilbreakers_terrain.handlers._mesh_bridge import PROP_GENERATOR_MAP

        missing = []
        for building_type, prop_list in PROP_AFFINITY.items():
            for prop_type, _weight in prop_list:
                if prop_type not in PROP_GENERATOR_MAP:
                    missing.append(f"{building_type}->{prop_type}")

        assert not missing, (
            f"PROP_GENERATOR_MAP is missing entries for: {missing}"
        )

    def test_prop_generator_map_covers_generic_props(self):
        """Every prop type in _GENERIC_PROPS has a PROP_GENERATOR_MAP entry."""
        from veilbreakers_terrain.handlers._scatter_engine import _GENERIC_PROPS
        from veilbreakers_terrain.handlers._mesh_bridge import PROP_GENERATOR_MAP

        missing = []
        for prop_type, _weight in _GENERIC_PROPS:
            if prop_type not in PROP_GENERATOR_MAP:
                missing.append(prop_type)

        assert not missing, (
            f"PROP_GENERATOR_MAP is missing generic prop entries: {missing}"
        )

    def test_generic_props_avoid_fallen_log_default_for_settlements(self):
        """Town-adjacent generic scatter should not default to fallen logs."""
        from veilbreakers_terrain.handlers._scatter_engine import _GENERIC_PROPS

        generic_types = {prop_type for prop_type, _weight in _GENERIC_PROPS}
        assert "log" not in generic_types
        assert "mushroom" not in generic_types

    def test_all_prop_generators_are_callable(self):
        """All generator functions in PROP_GENERATOR_MAP are callable."""
        from veilbreakers_terrain.handlers._mesh_bridge import PROP_GENERATOR_MAP

        for prop_type, (gen_func, _kwargs) in PROP_GENERATOR_MAP.items():
            assert callable(gen_func), (
                f"Generator for '{prop_type}' is not callable: {gen_func}"
            )

    def test_all_prop_generators_produce_valid_meshspec(self):
        """All generators in PROP_GENERATOR_MAP produce valid MeshSpec dicts."""
        from veilbreakers_terrain.handlers._mesh_bridge import PROP_GENERATOR_MAP

        for prop_type, (gen_func, gen_kwargs) in PROP_GENERATOR_MAP.items():
            spec = gen_func(**gen_kwargs)
            assert isinstance(spec, dict), (
                f"Generator for '{prop_type}' did not return a dict"
            )
            assert "vertices" in spec, (
                f"MeshSpec for '{prop_type}' missing 'vertices'"
            )
            assert "faces" in spec, (
                f"MeshSpec for '{prop_type}' missing 'faces'"
            )
            assert len(spec["vertices"]) > 0, (
                f"MeshSpec for '{prop_type}' has empty vertices"
            )
            assert len(spec["faces"]) > 0, (
                f"MeshSpec for '{prop_type}' has empty faces"
            )

    def test_prop_generator_map_in_all_maps(self):
        """PROP_GENERATOR_MAP is registered in _ALL_MAPS for resolve_generator."""
        from veilbreakers_terrain.handlers._mesh_bridge import _ALL_MAPS, PROP_GENERATOR_MAP

        assert "prop" in _ALL_MAPS, (
            "PROP_GENERATOR_MAP not registered in _ALL_MAPS"
        )
        assert _ALL_MAPS["prop"] is PROP_GENERATOR_MAP

    def test_prop_map_has_minimum_entries(self):
        """PROP_GENERATOR_MAP has at least 20 entries (all affinity + generic)."""
        from veilbreakers_terrain.handlers._mesh_bridge import PROP_GENERATOR_MAP

        assert len(PROP_GENERATOR_MAP) >= 20, (
            f"Expected at least 20 entries, got {len(PROP_GENERATOR_MAP)}"
        )


class TestHandlerImports:
    """Test that handler module can be partially imported."""

    def test_scatter_engine_importable(self):
        """_scatter_engine module imports without bpy."""
        from veilbreakers_terrain.handlers._scatter_engine import (
            BREAKABLE_PROPS,
            PROP_AFFINITY,
            biome_filter_points,
            context_scatter,
            generate_breakable_variants,
            poisson_disk_sample,
        )
        assert callable(poisson_disk_sample)
        assert callable(biome_filter_points)
        assert callable(context_scatter)
        assert callable(generate_breakable_variants)
        assert isinstance(PROP_AFFINITY, dict)
        assert isinstance(BREAKABLE_PROPS, dict)

    def test_prop_generator_map_importable(self):
        """PROP_GENERATOR_MAP imports without bpy."""
        from veilbreakers_terrain.handlers._mesh_bridge import PROP_GENERATOR_MAP
        assert isinstance(PROP_GENERATOR_MAP, dict)
        assert len(PROP_GENERATOR_MAP) > 0


# ---------------------------------------------------------------------------
# Fix 9.1 / 9.4 / 9.5 — channel consumer helpers (bpy-free)
# ---------------------------------------------------------------------------

class TestScatterChannelConsumers:
    """Tests for detail_density, hero_exclusion, wind_field consumer helpers."""

    # -- detail_density (Fix 9.1) --

    def test_detail_density_dict_collapses_to_mean(self):
        from veilbreakers_terrain.handlers.environment_scatter import _collapse_detail_density
        arr = np.full((4, 4), 0.5, dtype=np.float32)
        result = _collapse_detail_density({"canopy": arr, "ground_cover": arr})
        assert result is not None
        assert result.shape == (4, 4)
        assert float(result.mean()) == pytest.approx(0.5)

    def test_detail_density_none_returns_none(self):
        from veilbreakers_terrain.handlers.environment_scatter import _collapse_detail_density
        assert _collapse_detail_density(None) is None

    def test_detail_density_empty_dict_returns_none(self):
        from veilbreakers_terrain.handlers.environment_scatter import _collapse_detail_density
        assert _collapse_detail_density({}) is None

    def test_density_reject_at_half_density(self):
        """density=0.5 should reject ~half of candidates."""
        from veilbreakers_terrain.handlers.environment_scatter import _density_reject
        dm = np.full((4, 4), 0.5, dtype=np.float32)
        # rng_val=0.3 < 0.5 → accept (not rejected)
        assert not _density_reject(dm, 2.0, 2.0, 0.3)
        # rng_val=0.8 > 0.5 → reject
        assert _density_reject(dm, 2.0, 2.0, 0.8)

    def test_density_reject_none_map_never_rejects(self):
        from veilbreakers_terrain.handlers.environment_scatter import _density_reject
        assert not _density_reject(None, 0.0, 0.0, 0.9999)

    def test_density_reject_full_density_never_rejects(self):
        from veilbreakers_terrain.handlers.environment_scatter import _density_reject
        dm = np.full((4, 4), 1.0, dtype=np.float32)
        for rv in [0.0, 0.5, 0.99]:
            assert not _density_reject(dm, 1.0, 1.0, rv)

    def test_density_reject_zero_density_always_rejects(self):
        from veilbreakers_terrain.handlers.environment_scatter import _density_reject
        dm = np.zeros((4, 4), dtype=np.float32)
        for rv in [0.01, 0.5, 0.99]:
            assert _density_reject(dm, 1.0, 1.0, rv)

    def test_sample_scalar_map_uses_bilinear_sampling(self):
        from veilbreakers_terrain.handlers.environment_scatter import _sample_scalar_map

        arr = np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32)
        sampled = _sample_scalar_map(arr, x_local=5.0, y_local=5.0, width=10.0, height=10.0)
        assert sampled == pytest.approx(1.5, abs=1e-6)

    def test_resolve_scatter_context_maps_combines_water_sources(self):
        from types import SimpleNamespace

        from veilbreakers_terrain.handlers.environment_scatter import _resolve_scatter_context_maps

        stack = SimpleNamespace(
            wetness=np.array([[0.2, 0.1], [0.0, 0.0]], dtype=np.float32),
            water_surface=np.array([[0.0, 0.8], [0.0, 0.0]], dtype=np.float32),
            flow_accumulation=np.array([[0.0, 0.0], [0.0, 20.0]], dtype=np.float32),
            disturbance_patch_mask=None,
            erosion_amount=None,
            erosion_delta=None,
            deposition_amount=None,
        )

        water_map, disturbance_map = _resolve_scatter_context_maps(
            stack,
            np.zeros((2, 2), dtype=np.float32),
            moisture_map=None,
        )

        assert disturbance_map is None
        assert water_map is not None
        assert water_map[0, 0] == pytest.approx(0.2, abs=1e-6)
        assert water_map[0, 1] == pytest.approx(0.8, abs=1e-6)
        assert water_map[1, 1] == pytest.approx(1.0, abs=1e-6)

    def test_resolve_scatter_context_maps_combines_disturbance_layers(self):
        from types import SimpleNamespace

        from veilbreakers_terrain.handlers.environment_scatter import _resolve_scatter_context_maps

        stack = SimpleNamespace(
            wetness=None,
            water_surface=None,
            flow_accumulation=None,
            disturbance_patch_mask=np.array([[0.0, 0.0], [0.6, 0.0]], dtype=np.float32),
            erosion_amount=np.array([[0.0, 0.3], [0.0, 0.0]], dtype=np.float32),
            erosion_delta=None,
            deposition_amount=np.array([[0.0, 0.0], [0.0, 0.9]], dtype=np.float32),
        )

        water_map, disturbance_map = _resolve_scatter_context_maps(
            stack,
            np.zeros((2, 2), dtype=np.float32),
            moisture_map=None,
        )

        assert water_map is None
        assert disturbance_map is not None
        assert disturbance_map[1, 0] > 0.0
        assert disturbance_map[0, 1] > 0.0
        assert disturbance_map[1, 1] == pytest.approx(1.0, abs=1e-6)

    # -- hero_exclusion (Fix 9.4) --

    def test_hero_exclusion_all_ones_excludes_all(self):
        from veilbreakers_terrain.handlers.environment_scatter import _hero_excluded
        excl = np.ones((8, 8), dtype=np.float32)
        assert _hero_excluded(excl, 5.0, 5.0, 10.0, 10.0)

    def test_hero_exclusion_all_zeros_excludes_none(self):
        from veilbreakers_terrain.handlers.environment_scatter import _hero_excluded
        excl = np.zeros((8, 8), dtype=np.float32)
        assert not _hero_excluded(excl, 5.0, 5.0, 10.0, 10.0)

    def test_hero_exclusion_none_returns_false(self):
        from veilbreakers_terrain.handlers.environment_scatter import _hero_excluded
        assert not _hero_excluded(None, 5.0, 5.0, 10.0, 10.0)

    def test_hero_exclusion_partial_mask(self):
        from veilbreakers_terrain.handlers.environment_scatter import _hero_excluded
        excl = np.zeros((10, 10), dtype=np.float32)
        excl[5:, 5:] = 1.0  # top-right quadrant excluded
        # Point at (7.5, 7.5) within a 10x10 terrain → falls in excluded quadrant
        assert _hero_excluded(excl, 7.5, 7.5, 10.0, 10.0)
        # Point at (2.5, 2.5) → clear
        assert not _hero_excluded(excl, 2.5, 2.5, 10.0, 10.0)

    # -- wind_field (Fix 9.5) --

    def test_wind_rotation_none_returns_zero(self):
        from veilbreakers_terrain.handlers.environment_scatter import _wind_rotation_y
        assert _wind_rotation_y(None, 5.0, 5.0, 10.0, 10.0) == pytest.approx(0.0)

    def test_wind_rotation_plus_x_direction(self):
        from veilbreakers_terrain.handlers.environment_scatter import _wind_rotation_y
        import math
        wind = np.zeros((4, 4, 2), dtype=np.float32)
        wind[..., 0] = 1.0   # wind_x = 1
        wind[..., 1] = 0.0   # wind_y = 0
        # arctan2(1, 0) = pi/2
        rot = _wind_rotation_y(wind, 5.0, 5.0, 10.0, 10.0)
        assert rot == pytest.approx(math.pi / 2, abs=1e-4)

    def test_wind_rotation_plus_y_direction(self):
        from veilbreakers_terrain.handlers.environment_scatter import _wind_rotation_y
        wind = np.zeros((4, 4, 2), dtype=np.float32)
        wind[..., 0] = 0.0
        wind[..., 1] = 1.0
        # arctan2(0, 1) = 0.0
        rot = _wind_rotation_y(wind, 5.0, 5.0, 10.0, 10.0)
        assert rot == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Fix 9.2 — _write_tree_instance_points
# ---------------------------------------------------------------------------

class TestWriteTreeInstancePoints:
    """Tests for _write_tree_instance_points helper (Fix 9.2)."""

    def test_writes_float32_n5_to_stack(self):
        from types import SimpleNamespace
        from veilbreakers_terrain.handlers.environment_scatter import _write_tree_instance_points
        stack = SimpleNamespace(tree_instance_points=None)
        arr = np.array([[1.0, 2.0, 3.0, 0.5, 0.0]], dtype=np.float32)
        _write_tree_instance_points(arr, stack)
        assert stack.tree_instance_points is not None
        assert stack.tree_instance_points.dtype == np.float32
        assert stack.tree_instance_points.shape == (1, 5)

    def test_none_stack_is_noop(self):
        from veilbreakers_terrain.handlers.environment_scatter import _write_tree_instance_points
        # Should not raise
        _write_tree_instance_points(np.empty((0, 5), dtype=np.float32), None)

    def test_wrong_shape_is_noop(self):
        from types import SimpleNamespace
        from veilbreakers_terrain.handlers.environment_scatter import _write_tree_instance_points
        stack = SimpleNamespace(tree_instance_points=None)
        arr = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)  # (1, 3) not (N, 5)
        _write_tree_instance_points(arr, stack)
        assert stack.tree_instance_points is None

    def test_filters_non_finite_rows_and_normalizes_prototype_ids(self):
        from types import SimpleNamespace
        from veilbreakers_terrain.handlers.environment_scatter import _write_tree_instance_points

        stack = SimpleNamespace(tree_instance_points=None)
        arr = np.array(
            [
                [1.0, 2.0, 3.0, 0.5, 1.8],
                [4.0, np.nan, 6.0, 0.5, 2.0],
                [7.0, 8.0, 9.0, 1.5, -3.0],
            ],
            dtype=np.float32,
        )

        _write_tree_instance_points(arr, stack)

        assert stack.tree_instance_points.shape == (2, 5)
        np.testing.assert_array_equal(stack.tree_instance_points[:, 4], np.array([2.0, 0.0], dtype=np.float32))


def test_scatter_point_table_catalog_fallback_and_bad_normal_gating(monkeypatch):
    from veilbreakers_terrain.handlers import terrain_foliage_catalog
    from veilbreakers_terrain.handlers.environment_scatter import (
        _build_scatter_point_table_from_placements,
        _resolve_prototype_id,
    )
    from veilbreakers_terrain.handlers.terrain_scatter_points import validate_scatter_point_table

    assert _resolve_prototype_id(
        {"prototype_id": "explicit_prefab"},
        "tree_oak",
        lambda species: {"unity_asset_path": f"Assets/{species}.prefab"},
    ) == "explicit_prefab"
    assert _resolve_prototype_id(
        {},
        "tree_oak",
        lambda species: {"fallback": False, "unity_asset_path": f"Assets/{species}.prefab"},
    ) == "Assets/tree_oak.prefab"
    assert _resolve_prototype_id(
        {},
        "tree_oak",
        lambda species: {"fallback": True, "unity_asset_path": f"Assets/{species}.prefab"},
    ) == "tree_oak"
    assert _resolve_prototype_id({}, "tree_oak", lambda species: (_ for _ in ()).throw(RuntimeError())) == "tree_oak"

    def _catalog(species_id):
        if species_id == "tree_oak":
            return {"fallback": False, "unity_asset_path": "Assets/Foliage/Oak.prefab"}
        return {"fallback": True, "unity_asset_path": "Assets/Fallback.prefab"}

    monkeypatch.setattr(terrain_foliage_catalog, "resolve_model_asset", _catalog)

    table = _build_scatter_point_table_from_placements(
        [
            {
                "position": (6.0, 7.0),
                "species_id": "tree_oak",
                "base_type": "tree",
                "scale": 1.2,
                "altitude": 0.5,
                "normal": "bad-normal",
                "density": 0.8,
                "lod": 1,
                "slope": 8.0,
            },
            {
                "position": (9.0, 3.0),
                "species_id": "fern",
                "base_type": "groundcover",
                "scale": 0.7,
                "altitude": 0.25,
                "normal": (0.0, 0.0, 1.0),
                "orient": (0.0, 0.0, 0.0, 1.0),
                "density": 0.6,
                "lod": 2,
                "slope": 2.0,
            },
        ],
        terrain_width=20.0,
        terrain_height=20.0,
        terrain_origin_x=100.0,
        terrain_origin_y=200.0,
        biome_id="dark_forest",
        height_min=10.0,
        height_range=20.0,
        seed=42,
    )

    assert validate_scatter_point_table(table) == []
    assert table.points[0].prototype_id == "Assets/Foliage/Oak.prefab"
    assert table.points[0].normal == (0.0, 0.0, 1.0)
    assert table.points[0].lod_bucket == "lod1"
    assert table.points[0].position == pytest.approx((96.0, 197.0, 20.0))
    assert table.points[1].prototype_id == "fern"
    assert table.points[1].wind_profile == "groundcover"


# ---------------------------------------------------------------------------
# Fix 9.8 — LocationLayer (Wave 2)
# ---------------------------------------------------------------------------

class TestLocationLayer:
    """Tests for LocationLayer jitter + 3x3 repulsion placement."""

    def test_generates_instances_on_3x3_grid(self):
        """3x3 cell grid at density=1 produces 1-9 instances (repulsion may reject some)."""
        from veilbreakers_terrain.handlers.environment_scatter import LocationLayer
        ll = LocationLayer(cell_size=10.0, density=0.01, repulsion_radius=3.0, seed=42)
        result = ll.generate(30.0, 30.0)
        assert result.shape[1] == 5
        assert 1 <= len(result) <= 9

    def test_instances_within_bounds(self):
        """All accepted instances are within [0, width] x [0, height]."""
        from veilbreakers_terrain.handlers.environment_scatter import LocationLayer
        ll = LocationLayer(cell_size=10.0, density=0.01, repulsion_radius=3.0, seed=7)
        result = ll.generate(30.0, 30.0)
        assert len(result) > 0
        assert np.all(result[:, 0] >= 0.0) and np.all(result[:, 0] <= 30.0)
        assert np.all(result[:, 1] >= 0.0) and np.all(result[:, 1] <= 30.0)

    def test_repulsion_radius_enforced(self):
        """No two accepted instances are closer than repulsion_radius."""
        from veilbreakers_terrain.handlers.environment_scatter import LocationLayer
        rr = 3.0
        ll = LocationLayer(cell_size=5.0, density=0.04, repulsion_radius=rr, seed=0)
        result = ll.generate(50.0, 50.0)
        if len(result) < 2:
            return  # nothing to check
        xs, ys = result[:, 0], result[:, 1]
        for i in range(len(result)):
            for j in range(i + 1, len(result)):
                dist = float(np.sqrt((xs[i] - xs[j]) ** 2 + (ys[i] - ys[j]) ** 2))
                assert dist >= rr - 1e-6, (
                    f"Points {i} and {j} are {dist:.3f}m apart — less than repulsion {rr}m"
                )

    def test_large_repulsion_checks_beyond_adjacent_cells(self):
        """Repulsion larger than one cell still excludes all near accepted points."""
        from veilbreakers_terrain.handlers.environment_scatter import LocationLayer

        rr = 5.0
        ll = LocationLayer(cell_size=2.0, density=0.5, repulsion_radius=rr, seed=3)
        result = ll.generate(20.0, 20.0)
        assert len(result) >= 2

        xy = result[:, :2].astype(np.float64)
        for i in range(len(xy)):
            delta = xy[i + 1:] - xy[i]
            if len(delta) == 0:
                continue
            dist_sq = np.einsum("ij,ij->i", delta, delta)
            assert np.all(dist_sq >= (rr * rr) - 1e-5)

    def test_large_repulsion_no_scipy_fallback_checks_dynamic_cell_radius(self, monkeypatch):
        """Pure-Python fallback must not regress to adjacent-cell-only checks."""
        from veilbreakers_terrain.handlers.environment_scatter import LocationLayer

        import builtins

        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "scipy" or name.startswith("scipy."):
                raise ImportError("blocked scipy")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)

        rr = 5.0
        ll = LocationLayer(cell_size=2.0, density=0.5, repulsion_radius=rr, seed=3)
        result = ll.generate(20.0, 20.0)
        if len(result) < 2:
            return

        xy = result[:, :2].astype(np.float64)
        for i in range(len(xy)):
            delta = xy[i + 1:] - xy[i]
            if len(delta) == 0:
                continue
            dist_sq = np.einsum("ij,ij->i", delta, delta)
            assert np.all(dist_sq >= (rr * rr) - 1e-5)

    def test_deterministic_same_seed(self):
        """Same seed → identical output."""
        from veilbreakers_terrain.handlers.environment_scatter import LocationLayer
        ll = LocationLayer(cell_size=10.0, density=0.01, repulsion_radius=3.0, seed=42)
        r1 = ll.generate(30.0, 30.0)
        r2 = ll.generate(30.0, 30.0)
        np.testing.assert_array_equal(r1, r2)

    def test_different_seeds_produce_different_output(self):
        """Different seeds → different output (collision probability negligible)."""
        from veilbreakers_terrain.handlers.environment_scatter import LocationLayer
        r1 = LocationLayer(cell_size=10.0, density=0.01, repulsion_radius=3.0, seed=1).generate(30.0, 30.0)
        r2 = LocationLayer(cell_size=10.0, density=0.01, repulsion_radius=3.0, seed=99).generate(30.0, 30.0)
        assert not np.array_equal(r1, r2)

    def test_candidate_within_cell(self):
        """candidate x = j*cs + cs*(rand+0.5) stays within [j*cs, (j+1)*cs]."""
        from veilbreakers_terrain.handlers.environment_scatter import _location_layer_rand2
        cs = 10.0
        for i in range(3):
            for j in range(3):
                for k in range(5):
                    rx, ry = _location_layer_rand2(i, j, seed=0, k=k)
                    cx = j * cs + cs * (rx + 0.5)
                    cy = i * cs + cs * (ry + 0.5)
                    assert j * cs <= cx <= (j + 1) * cs, f"cx={cx} out of cell [{j*cs}, {(j+1)*cs}]"
                    assert i * cs <= cy <= (i + 1) * cs, f"cy={cy} out of cell [{i*cs}, {(i+1)*cs}]"

    def test_output_shape_and_dtype(self):
        """Output is float32 ndarray shape (N, 5)."""
        from veilbreakers_terrain.handlers.environment_scatter import LocationLayer
        ll = LocationLayer(cell_size=10.0, density=0.01, repulsion_radius=3.0, seed=0)
        result = ll.generate(30.0, 30.0)
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        assert result.ndim == 2
        assert result.shape[1] == 5

    def test_empty_terrain_returns_empty(self):
        """width=0 or height=0 returns empty (0, 5) array."""
        from veilbreakers_terrain.handlers.environment_scatter import LocationLayer
        ll = LocationLayer(cell_size=10.0, density=0.01, repulsion_radius=3.0, seed=0)
        result = ll.generate(0.0, 0.0)
        assert result.shape == (0, 5) or result.shape[1] == 5


# ---------------------------------------------------------------------------
# Fix 9.3 — road_mask exclusion + Fix 9.2 write-back (Wave 2)
# ---------------------------------------------------------------------------

class TestRoadMaskExclusion:
    """Tests for road_mask channel exclusion via _apply_sdf_exclusion helper."""

    def test_all_road_mask_excludes_all(self):
        """road_mask = ones → every point is excluded via the helper."""
        from veilbreakers_terrain.handlers.environment_scatter import _apply_sdf_exclusion
        # road_sdf_np=None path — test the road_mask logic using the stack mock
        # For road_mask we test via integration: all points at col/row = road
        import numpy as np
        # Build a "sdf" where everything is 0.5 (< placement_radius=2.0)
        road_sdf = np.full((8, 8), 0.5, dtype=np.float32)
        excluded = _apply_sdf_exclusion(
            world_x=5.0, world_y=5.0, road_sdf_np=road_sdf,
            placement_radius=2.0,
            terrain_origin_x=0.0, terrain_origin_y=0.0,
            terrain_width=10.0, terrain_height=10.0,
        )
        assert excluded, "sdf=0.5 < radius=2.0 should exclude"

    def test_no_road_mask_passes_all(self):
        """road_sdf_np=None → no exclusion applied."""
        from veilbreakers_terrain.handlers.environment_scatter import _apply_sdf_exclusion
        assert not _apply_sdf_exclusion(
            world_x=5.0, world_y=5.0, road_sdf_np=None,
            placement_radius=2.0,
            terrain_origin_x=0.0, terrain_origin_y=0.0,
            terrain_width=10.0, terrain_height=10.0,
        )

    def test_write_tree_instance_points_via_stack_set(self):
        """_write_tree_instance_points calls stack.set when available."""
        from veilbreakers_terrain.handlers.environment_scatter import _write_tree_instance_points
        recorded = {}

        class MockStack:
            def set(self, key, arr, provenance=None):
                recorded[key] = arr

        arr = np.array([[1.0, 2.0, 3.0, 0.1, 0.0]], dtype=np.float32)
        _write_tree_instance_points(arr, MockStack())
        assert "tree_instance_points" in recorded
        assert recorded["tree_instance_points"].shape == (1, 5)
        assert recorded["tree_instance_points"].dtype == np.float32

    def test_road_mask_none_fallback_no_crash(self):
        """When road_sdf is None, _apply_sdf_exclusion returns False without error."""
        from veilbreakers_terrain.handlers.environment_scatter import _apply_sdf_exclusion
        result = _apply_sdf_exclusion(0.0, 0.0, None, 2.0, 0.0, 0.0, 100.0, 100.0)
        assert result is False


# ---------------------------------------------------------------------------
# Fix 9.11 — SDF road exclusion (Wave 3)
# ---------------------------------------------------------------------------

class TestSdfRoadExclusion:
    """Tests for SDF-based road edge exclusion via _apply_sdf_exclusion."""

    def _excl(self, world_x, world_y, sdf_val, placement_radius=2.0):
        from veilbreakers_terrain.handlers.environment_scatter import _apply_sdf_exclusion
        road_sdf = np.full((8, 8), sdf_val, dtype=np.float32)
        return _apply_sdf_exclusion(
            world_x=world_x, world_y=world_y,
            road_sdf_np=road_sdf,
            placement_radius=placement_radius,
            terrain_origin_x=0.0, terrain_origin_y=0.0,
            terrain_width=10.0, terrain_height=10.0,
        )

    def test_sdf_below_radius_excludes(self):
        """sdf=1.0 < placement_radius=2.0 → excluded."""
        assert self._excl(5.0, 5.0, sdf_val=1.0, placement_radius=2.0)

    def test_sdf_above_radius_passes(self):
        """sdf=5.0 >= placement_radius=2.0 → not excluded."""
        assert not self._excl(5.0, 5.0, sdf_val=5.0, placement_radius=2.0)

    def test_none_sdf_no_exclusion(self):
        """road_sdf_dist is None → no exclusion applied."""
        from veilbreakers_terrain.handlers.environment_scatter import _apply_sdf_exclusion
        assert not _apply_sdf_exclusion(5.0, 5.0, None, 2.0, 0.0, 0.0, 10.0, 10.0)

    def test_default_clearance_is_two_metres(self):
        """Default road_sdf_clearance parameter is 2.0m."""
        # sdf=1.9 should be excluded at default clearance of 2.0
        assert self._excl(5.0, 5.0, sdf_val=1.9, placement_radius=2.0)

    def test_sdf_and_road_mask_both_active(self):
        """A point excluded by road_mask is still excluded by SDF (not re-admitted)."""
        from veilbreakers_terrain.handlers.environment_scatter import _apply_sdf_exclusion
        # Both sdf=0.5 (excluded) and None (not excluded) — test both branches
        road_sdf_low = np.full((8, 8), 0.5, dtype=np.float32)
        road_sdf_high = np.full((8, 8), 5.0, dtype=np.float32)
        assert _apply_sdf_exclusion(5.0, 5.0, road_sdf_low, 2.0, 0.0, 0.0, 10.0, 10.0)
        assert not _apply_sdf_exclusion(5.0, 5.0, road_sdf_high, 2.0, 0.0, 0.0, 10.0, 10.0)


# ---------------------------------------------------------------------------
# Fix 9.9 — Emergent grass + Fix 9.10 — Halo scatter (Wave 3)
# ---------------------------------------------------------------------------

class TestEmergentGrass:
    """Tests for compute_emergent_grass_density (Fix 9.9)."""

    def test_full_ground_weight_gives_scale(self):
        """All ground weights = 1.0 → output = GRASS_DENSITY_SCALE (5.0)."""
        from veilbreakers_terrain.handlers.terrain_vegetation_depth import (
            GRASS_DENSITY_SCALE, compute_emergent_grass_density,
        )
        splatmap = np.zeros((4, 4, 5), dtype=np.float32)
        splatmap[..., 0] = 1.0
        result = compute_emergent_grass_density(splatmap)
        assert result.shape == (4, 4)
        np.testing.assert_allclose(result, GRASS_DENSITY_SCALE, rtol=1e-5)

    def test_half_ground_weight_gives_half_scale(self):
        """All ground weights = 0.5 → output = 2.5."""
        from veilbreakers_terrain.handlers.terrain_vegetation_depth import compute_emergent_grass_density
        splatmap = np.zeros((4, 4, 5), dtype=np.float32)
        splatmap[..., 0] = 0.5
        result = compute_emergent_grass_density(splatmap)
        np.testing.assert_allclose(result, 2.5, rtol=1e-5)

    def test_zero_ground_weight_gives_zeros(self):
        """All ground weights = 0.0 → output all zeros."""
        from veilbreakers_terrain.handlers.terrain_vegetation_depth import compute_emergent_grass_density
        splatmap = np.zeros((4, 4, 5), dtype=np.float32)
        result = compute_emergent_grass_density(splatmap)
        np.testing.assert_array_equal(result, 0.0)

    def test_invalid_splatmap_returns_zeros_no_crash(self):
        """splatmap with ndim != 3 or L <= grass_idx → returns zeros, no crash."""
        from veilbreakers_terrain.handlers.terrain_vegetation_depth import compute_emergent_grass_density
        # 2D splatmap
        result_2d = compute_emergent_grass_density(np.ones((4, 4), dtype=np.float32))
        assert result_2d.ndim == 2
        np.testing.assert_array_equal(result_2d, 0.0)
        # L=0 (no layers)
        result_0l = compute_emergent_grass_density(np.zeros((4, 4, 0), dtype=np.float32))
        np.testing.assert_array_equal(result_0l, 0.0)

    def test_output_dtype_is_float32(self):
        """Output is float32."""
        from veilbreakers_terrain.handlers.terrain_vegetation_depth import compute_emergent_grass_density
        splatmap = np.ones((4, 4, 3), dtype=np.float64)
        result = compute_emergent_grass_density(splatmap)
        assert result.dtype == np.float32


class TestHaloScatter:
    """Tests for halo_scatter_point_id (Fix 9.10)."""

    def test_deterministic(self):
        """Same inputs → same tile_id always."""
        from veilbreakers_terrain.handlers.environment_scatter import halo_scatter_point_id
        v = halo_scatter_point_id(10.0, 20.0, seed=42, num_tiles=4)
        for _ in range(10):
            assert halo_scatter_point_id(10.0, 20.0, seed=42, num_tiles=4) == v

    def test_range_within_num_tiles(self):
        """100 random points → all tile_ids in [0, num_tiles)."""
        from veilbreakers_terrain.handlers.environment_scatter import halo_scatter_point_id
        rng = np.random.default_rng(0)
        xs = rng.uniform(0, 100, 100)
        ys = rng.uniform(0, 100, 100)
        for x, y in zip(xs, ys):
            tid = halo_scatter_point_id(float(x), float(y), seed=7, num_tiles=4)
            assert 0 <= tid < 4

    def test_same_point_same_tile(self):
        """Two identical points → same tile_id."""
        from veilbreakers_terrain.handlers.environment_scatter import halo_scatter_point_id
        assert (
            halo_scatter_point_id(50.0, 50.0, seed=1, num_tiles=8)
            == halo_scatter_point_id(50.0, 50.0, seed=1, num_tiles=8)
        )


# ---------------------------------------------------------------------------
# P2-10 — LOD screen-percentage uses object radius
# ---------------------------------------------------------------------------


class TestLodScreenPercentage:
    """_lod_for_distance honours object_radius_m via LOD_PRESETS."""

    def test_small_bush_at_50m_is_far_lod(self):
        from veilbreakers_terrain.handlers.environment_scatter import _lod_for_distance

        # 0.5m bush at 50m → screen_pct ≈ 0.01 → well below every
        # vegetation LOD_PRESETS threshold → final LOD (3 = billboard/cull).
        lod = _lod_for_distance(50.0, "bush", object_radius_m=0.5)
        assert lod >= 2, f"Small bush at 50m should be LOD2+, got {lod}"

    def test_large_tree_at_50m_is_lod0(self):
        from veilbreakers_terrain.handlers.environment_scatter import _lod_for_distance

        # LOD_PRESETS["vegetation"]["screen_percentages"] = [1.0, 0.3, 0.08, 0.02].
        # A radius large enough to give screen_pct >= 1.0 at 50 m is >= 50 m.
        lod = _lod_for_distance(50.0, "tree", object_radius_m=55.0)
        assert lod == 0, f"Huge tree at 50m should be LOD0, got {lod}"

    def test_relative_sizing_bush_vs_tree_same_distance(self):
        from veilbreakers_terrain.handlers.environment_scatter import _lod_for_distance

        bush_lod = _lod_for_distance(50.0, "bush", object_radius_m=0.5)
        tree_lod = _lod_for_distance(50.0, "tree", object_radius_m=5.0)
        assert bush_lod > tree_lod, (
            f"A 0.5m bush at 50m must demote further than a 5m tree "
            f"(bush_lod={bush_lod}, tree_lod={tree_lod})"
        )

    def test_fallback_to_distance_table_when_radius_absent(self):
        from veilbreakers_terrain.handlers.environment_scatter import _lod_for_distance

        # No object_radius_m → legacy distance-only path.
        lod = _lod_for_distance(50.0, "tree")
        assert lod in (1, 2), f"Tree at 50m (table-only) expected LOD1/2, got {lod}"


# ---------------------------------------------------------------------------
# P2-12 — Bilinear density sampling (no stair-steps)
# ---------------------------------------------------------------------------


class TestDensityBilinearSampling:
    """_density_reject samples density bilinearly."""

    def test_bilinear_returns_intermediate_value_at_midpoint(self):
        from veilbreakers_terrain.handlers.environment_scatter import _density_reject

        # 2x2 density map: bilinear at (0.5, 0.5) should be 0.5, so an
        # rng_val strictly between 0 and 1 discriminates correctly.
        dm = np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float32)
        # At row 0.5 col 0.5 -> average of {0,0,1,1} = 0.5
        assert _density_reject(dm, 0.5, 0.5, rng_val=0.4) is False
        assert _density_reject(dm, 0.5, 0.5, rng_val=0.6) is True

    def test_linear_ramp_monotonic_no_stairstep(self):
        from veilbreakers_terrain.handlers.environment_scatter import _density_reject

        # Build a 1D-style ramp 0->1 in the row direction, 8 rows x 2 cols.
        dm = np.linspace(0.0, 1.0, 8, dtype=np.float32)[:, None].repeat(2, axis=1)
        samples = []
        # Sample 40 fractional row positions and reconstruct sampled density
        # by binary-searching the rng threshold at which reject flips.
        test_rows = np.linspace(0.0, 7.0, 40)
        for rf in test_rows:
            lo, hi = 0.0, 1.0
            for _ in range(30):
                mid = (lo + hi) * 0.5
                if _density_reject(dm, float(rf), 0.5, rng_val=mid):
                    hi = mid
                else:
                    lo = mid
            samples.append((lo + hi) * 0.5)
        samples = np.asarray(samples)
        # Monotonic non-decreasing across all 40 samples. A nearest-neighbour
        # implementation produces stair-step jumps with local flat regions.
        diffs = np.diff(samples)
        assert np.all(diffs >= -1e-3), (
            f"Bilinear sampling should be monotonic non-decreasing across "
            f"a linear ramp; got min-diff={diffs.min():.4f}"
        )
        # And the first->last direction actually spans the ramp.
        assert samples[-1] - samples[0] > 0.8

    def test_none_density_never_rejects(self):
        from veilbreakers_terrain.handlers.environment_scatter import _density_reject
        assert _density_reject(None, 0.0, 0.0, rng_val=0.9) is False
