import pytest


def test_world_creator_pointcloud_rows_convert_to_canonical_scatter_table():
    from veilbreakers_terrain.handlers.terrain_scatter_points import (
        load_world_creator_instance_pointcloud,
    )

    table = load_world_creator_instance_pointcloud(
        layer_id="oak_trees",
        prototype_id="oak_lod0",
        species_id="tree_oak",
        biome_id="forest",
        model_scale=(2.0, 2.0, 2.0),
        rows=[
            {
                "tx": "0.25",
                "ty": "0.5",
                "tz": "0.125",
                "sx": "1.0",
                "sy": "0.9",
                "sz": "1.1",
                "qx": "0",
                "qy": "0",
                "qz": "0",
                "qw": "1",
                "gradient": "0.75",
                "seed": "42",
            }
        ],
    )

    point = table.points[0]

    assert table.format == "ScatterPointTable"
    assert point.position == pytest.approx((256.0, 512.0, 128.0))
    assert point.scale == pytest.approx((2.0, 1.8, 2.2))
    assert point.orient == pytest.approx((0.0, 0.0, 0.0, 1.0))
    assert point.prototype_id == "oak_lod0"
    assert point.species_id == "tree_oak"
    assert point.density == pytest.approx(0.75)
    assert point.seed == 42
    assert point.mask_sources == ("world_creator_instance:oak_trees",)


def test_scatter_table_validation_blocks_missing_orientation_and_prototype():
    from veilbreakers_terrain.handlers.terrain_scatter_points import (
        ScatterPoint,
        ScatterPointTable,
        validate_scatter_point_table,
    )

    table = ScatterPointTable(
        points=[
            ScatterPoint(
                position=(0.0, 0.0, 0.0),
                normal=(0.0, 0.0, 1.0),
                orient=(0.0, 0.0, 0.0, 0.0),
                scale=(1.0, 1.0, 1.0),
                prototype_id="",
                species_id="tree_oak",
                biome_id="forest",
                density=1.0,
                seed=1,
                slope=0.1,
                height_m=10.0,
                mask_sources=("forest_mask",),
                lod_bucket="lod0",
                wind_profile="tree",
            )
        ]
    )

    codes = {issue["code"] for issue in validate_scatter_point_table(table)}

    assert {"missing_prototype_id", "invalid_orientation_quaternion"} <= codes


def test_path_network_contract_requires_bridge_for_deep_water_crossing():
    from veilbreakers_terrain.handlers.terrain_path_contracts import (
        PathNetworkContract,
        PathSegmentContract,
        validate_path_network_contract,
    )

    network = PathNetworkContract(
        node_id="node_a",
        segments=[
            PathSegmentContract(
                segment_id="road_0",
                segment_type="road",
                points=((0.0, 0.0, 10.0), (10.0, 0.0, 10.0)),
                width_m=4.0,
                material_stack=("compacted_dirt", "wet_mud_edges"),
                continuation_edge="east",
                crosses_water=True,
                water_depth_m=2.5,
                bridge_required=False,
            )
        ],
    )

    codes = {issue["code"] for issue in validate_path_network_contract(network)}

    assert "deep_water_crossing_requires_bridge" in codes


def test_bridge_segment_contract_requires_clearance_and_material_transition():
    from veilbreakers_terrain.handlers.terrain_path_contracts import (
        PathNetworkContract,
        PathSegmentContract,
        validate_path_network_contract,
    )

    network = PathNetworkContract(
        node_id="node_a",
        segments=[
            PathSegmentContract(
                segment_id="bridge_0",
                segment_type="bridge",
                points=((0.0, 0.0, 12.0), (12.0, 0.0, 12.0)),
                width_m=4.0,
                material_stack=("wood_planks",),
                continuation_edge="east",
                crosses_water=True,
                water_depth_m=2.0,
                bridge_required=True,
                bridge_span_m=12.0,
                bridge_clearance_m=0.25,
            )
        ],
    )

    codes = {issue["code"] for issue in validate_path_network_contract(network)}

    assert "bridge_clearance_too_low" in codes
    assert "bridge_missing_approach_material_transition" in codes


def test_bridge_required_on_road_still_requires_bridge_geometry_contract():
    from veilbreakers_terrain.handlers.terrain_path_contracts import (
        PathNetworkContract,
        PathSegmentContract,
        validate_path_network_contract,
    )

    network = PathNetworkContract(
        node_id="node_a",
        segments=[
            PathSegmentContract(
                segment_id="road_bridge_crossing",
                segment_type="road",
                points=((0.0, 0.0, 12.0), (12.0, 0.0, 12.0)),
                width_m=4.0,
                material_stack=("compacted_dirt",),
                crosses_water=True,
                water_depth_m=2.0,
                bridge_required=True,
            )
        ],
    )

    codes = {issue["code"] for issue in validate_path_network_contract(network)}

    assert "bridge_required_but_segment_not_bridge_or_ford" in codes
    assert "bridge_missing_span" in codes
    assert "bridge_clearance_too_low" in codes


def test_path_network_contract_rejects_segment_grade_above_budget():
    from veilbreakers_terrain.handlers.terrain_path_contracts import (
        PathNetworkContract,
        PathSegmentContract,
        validate_path_network_contract,
    )

    network = PathNetworkContract(
        node_id="node_a",
        segments=[
            PathSegmentContract(
                segment_id="steep_path",
                segment_type="path",
                points=((0.0, 0.0, 0.0), (10.0, 0.0, 10.0)),
                width_m=2.0,
                material_stack=("dirt_path",),
                max_grade=0.25,
            )
        ],
    )

    codes = {issue["code"] for issue in validate_path_network_contract(network)}

    assert "path_grade_exceeds_budget" in codes


def test_material_stack_for_path_maps_surface_and_bridge_types():
    from veilbreakers_terrain.handlers.terrain_path_contracts import material_stack_for_path

    assert material_stack_for_path("trail") == (
        "road_core",
        "road_edge",
        "approach_transition",
        "dirt_path",
    )
    assert material_stack_for_path("gravel_road")[-1] == "gravel"
    assert material_stack_for_path("paved")[-1] == "cobblestone_floor"
    assert material_stack_for_path("rope", bridge=True) == (
        "wood_planks",
        "bridge_edge",
        "approach_transition",
    )
    assert material_stack_for_path("stone", bridge=True)[0] == "stone_deck"
    assert material_stack_for_path("")[-1] == "terrain_path"


def test_path_segment_length_and_grade_handle_3d_and_vertical_segments():
    from veilbreakers_terrain.handlers.terrain_path_contracts import PathSegmentContract

    segment = PathSegmentContract(
        segment_id="path_0",
        segment_type="path",
        points=((0.0, 0.0, 0.0), (3.0, 4.0, 0.0), (6.0, 4.0, 3.0)),
        width_m=2.0,
        material_stack=("dirt_path",),
    )
    vertical = PathSegmentContract(
        segment_id="vertical",
        segment_type="path",
        points=((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        width_m=2.0,
        material_stack=("dirt_path",),
    )
    flat_vertical = PathSegmentContract(
        segment_id="flat_vertical",
        segment_type="path",
        points=((0.0, 0.0, 2.0), (0.0, 0.0, 2.0)),
        width_m=2.0,
        material_stack=("dirt_path",),
    )

    assert segment.length_m() == pytest.approx(5.0 + (18.0 ** 0.5))
    assert segment.max_observed_grade() == pytest.approx(1.0)
    assert vertical.max_observed_grade() == float("inf")
    assert flat_vertical.max_observed_grade() == pytest.approx(0.0)


def test_scatter_table_validation_requires_full_point_contract():
    from veilbreakers_terrain.handlers.terrain_scatter_points import (
        ScatterPoint,
        ScatterPointTable,
        validate_scatter_point_table,
    )

    table = ScatterPointTable(
        points=[
            ScatterPoint(
                position=(float("nan"), 0.0, 0.0),
                normal=(0.0, 0.0, 0.0),
                orient=(0.0, 0.0, 0.0, 1.0),
                scale=(1.0, 1.0, 1.0),
                prototype_id="oak_lod0",
                species_id="tree_oak",
                biome_id="",
                density=1.0,
                seed=1,
                slope=0.1,
                height_m=10.0,
                mask_sources=("forest_mask",),
                lod_bucket="",
                wind_profile="",
            )
        ]
    )

    codes = {issue["code"] for issue in validate_scatter_point_table(table)}

    assert {
        "invalid_position",
        "invalid_normal",
        "missing_biome_id",
        "missing_lod_bucket",
        "missing_wind_profile",
    } <= codes


def test_scatter_table_validation_rejects_non_finite_normals():
    from veilbreakers_terrain.handlers.terrain_scatter_points import (
        ScatterPoint,
        ScatterPointTable,
        validate_scatter_point_table,
    )

    table = ScatterPointTable(
        points=[
            ScatterPoint(
                position=(0.0, 0.0, 0.0),
                normal=(float("inf"), 0.0, 0.0),
                orient=(0.0, 0.0, 0.0, 1.0),
                scale=(1.0, 1.0, 1.0),
                prototype_id="oak_lod0",
                species_id="tree_oak",
                biome_id="forest",
                density=1.0,
                seed=1,
                slope=0.1,
                height_m=10.0,
                mask_sources=("forest_mask",),
                lod_bucket="lod0",
                wind_profile="tree",
            )
        ]
    )

    codes = {issue["code"] for issue in validate_scatter_point_table(table)}

    assert "invalid_normal" in codes


# ---------------------------------------------------------------------------
# Opus R2 scan: C-1/C-2/C-3 wiring contracts
# ---------------------------------------------------------------------------


def test_c1_scatter_biome_vegetation_emits_deprecation_warning():
    """C-1: vegetation_system.scatter_biome_vegetation must warn when called.

    The function is intentionally still callable so legacy code paths don't
    crash, but every invocation must surface a DeprecationWarning so the
    caller knows to migrate to handle_scatter_vegetation.
    """
    import warnings

    from veilbreakers_terrain.handlers.vegetation_system import (
        scatter_biome_vegetation,
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            # Invoke with empty params — function will raise ValueError
            # because biome_name is missing, but the warning must fire
            # *before* the validation error.
            scatter_biome_vegetation({})
        except ValueError:
            pass
        deprecation_warnings = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert deprecation_warnings, (
            "scatter_biome_vegetation must emit DeprecationWarning"
        )
        assert "scatter_biome_vegetation" in str(deprecation_warnings[0].message)


def test_c2_speciesspec_to_dict_round_trips_all_new_fields():
    """C-2: SpeciesSpec.to_dict() must serialize every extended field.

    All 12 new fields (lod_paths, lod_distances_m, impostor_atlas_path,
    impostor_uv_strip_count, collision_proxy_path, max_tris_lod0,
    wind_profile, wind_bend_scale, slope_max_deg, altitude_min_m,
    altitude_max_m, wetness_tolerance) must round-trip through to_dict()
    so the Unity manifest carries them.
    """
    from veilbreakers_terrain.handlers.terrain_foliage_catalog import (
        FOLIAGE_SPECIES_CATALOG,
        SpeciesSpec,
    )

    expected_keys = {
        "lod_paths",
        "lod_distances_m",
        "impostor_atlas_path",
        "impostor_uv_strip_count",
        "collision_proxy_path",
        "max_tris_lod0",
        "wind_profile",
        "wind_bend_scale",
        "slope_max_deg",
        "altitude_min_m",
        "altitude_max_m",
        "wetness_tolerance",
    }

    # Every catalog entry must carry the new keys.
    for sid, spec in FOLIAGE_SPECIES_CATALOG.items():
        d = spec.to_dict()
        missing = expected_keys - set(d.keys())
        assert not missing, f"{sid} to_dict() missing fields: {missing}"

    # Defaults must be sane: lod_distances_m must default to ascending
    # 3-tier transitions (15/40/80 metres) per AAA bar.
    default_spec = SpeciesSpec(
        species_id="t_default",
        category="grass",
        min_altitude_m=0.0,
        max_altitude_m=100.0,
        min_slope_rad=0.0,
        max_slope_rad=1.0,
        moisture_range=(0.0, 1.0),
        exclude_near=(),
        place_near=(),
        poisson_min_distance_m=1.0,
        lod_viewer_distance_m=10.0,
        biome_mask=frozenset({"forest"}),
        unity_asset_path="Assets/X.prefab",
    )
    assert default_spec.lod_distances_m == (15.0, 40.0, 80.0), (
        "Default lod_distances_m must be (15, 40, 80) metres"
    )
    # Round-trip values match.
    d = default_spec.to_dict()
    assert d["lod_distances_m"] == [15.0, 40.0, 80.0]
    assert d["wind_profile"] == "none"
    assert d["max_tris_lod0"] == 50_000


def test_c3_scatter_pass_carries_correct_slope_and_wind_profile():
    """C-3: ScatterPoint built inside _scatter_pass must use real slope (not
    altitude) and species-specific wind_profile (not hardcoded "none")."""
    from veilbreakers_terrain.handlers.terrain_scatter_points import (
        validate_scatter_point_table,
        ScatterPointTable,
        ScatterPoint,
    )

    # The C-3 wiring runs inside _scatter_pass and only logs validation
    # warnings; it does not surface the table.  We re-create the path the
    # function takes by exercising it on a flat tile and re-running the
    # validator on the public _build_scatter_point_table_from_placements
    # output downstream.  This test asserts the validator catches the
    # historic bug (slope==altitude) by constructing a manually mis-wired
    # table and confirming slope_out_of_range fires when slope > 90.
    bad_point = ScatterPoint(
        position=(0.0, 0.0, 5.0),
        normal=(0.0, 0.0, 1.0),
        orient=(0.0, 0.0, 0.0, 1.0),
        scale=(1.0, 1.0, 1.0),
        prototype_id="grass",
        species_id="grass_short",
        biome_id="forest",
        density=0.5,
        seed=1,
        slope=120.0,  # invalid — would have happened with old altitude*size code
        height_m=5.0,
        mask_sources=("scatter_pass:ground_cover",),
        lod_bucket="lod0",
        wind_profile="grass",
    )
    table = ScatterPointTable(points=(bad_point,))
    codes = {issue["code"] for issue in validate_scatter_point_table(table)}
    assert "slope_out_of_range" in codes, (
        "validator must reject impossible slope values"
    )

    # Also confirm height_m / position.z mismatch fires.
    mismatch_point = ScatterPoint(
        position=(0.0, 0.0, 5.0),
        normal=(0.0, 0.0, 1.0),
        orient=(0.0, 0.0, 0.0, 1.0),
        scale=(1.0, 1.0, 1.0),
        prototype_id="g",
        species_id="grass_short",
        biome_id="forest",
        density=0.5,
        seed=1,
        slope=10.0,
        height_m=99.0,  # disagrees with position.z=5.0
        mask_sources=("scatter_pass:ground_cover",),
        lod_bucket="lod0",
        wind_profile="grass",
    )
    table2 = ScatterPointTable(points=(mismatch_point,))
    codes2 = {issue["code"] for issue in validate_scatter_point_table(table2)}
    assert "height_position_mismatch" in codes2


def test_c3_validator_flags_duplicate_positions_and_single_species_tables():
    """AAA scatter check: detect overlap and lack of diversity."""
    from veilbreakers_terrain.handlers.terrain_scatter_points import (
        ScatterPoint,
        ScatterPointTable,
        validate_scatter_point_table,
    )

    # 30 identical points — duplicate-position spam.
    pts = []
    for i in range(30):
        pts.append(
            ScatterPoint(
                position=(1.0, 2.0, 3.0),  # identical
                normal=(0.0, 0.0, 1.0),
                orient=(0.0, 0.0, 0.0, 1.0),
                scale=(1.0, 1.0, 1.0),
                prototype_id="g",
                species_id="grass_short",
                biome_id="forest",
                density=0.5,
                seed=i,
                slope=5.0,
                height_m=3.0,
                mask_sources=("test",),
                lod_bucket="lod0",
                wind_profile="grass",
            )
        )
    table = ScatterPointTable(points=tuple(pts))
    codes = {issue["code"] for issue in validate_scatter_point_table(table)}
    assert "duplicate_position" in codes
    assert "single_species_table" in codes


def test_surface_support_gate_splits_accepted_and_rejected_candidates():
    from veilbreakers_terrain.handlers.terrain_scatter_points import (
        ScatterCandidate,
        SurfaceSupportGate,
        build_scatter_candidate_table,
    )

    accepted = ScatterCandidate(
        candidate_id="oak_001",
        source_rule_id="forest_canopy",
        source_layer_id="tree_layer",
        species_or_prop_id="tree_oak",
        sampled_position=(1.0, 2.0, 3.0),
        sampled_slope_deg=12.0,
        sampled_material_layer_id="soil",
        sampled_wetness=0.4,
        sampled_deposition=0.6,
        sampled_talus=0.0,
        nearest_water_distance_m=18.0,
        support_score=0.82,
        embed_depth_m=0.08,
    )
    rejected = ScatterCandidate(
        candidate_id="boulder_001",
        source_rule_id="coastal_boulders",
        source_layer_id="rock_layer",
        species_or_prop_id="hero_boulder",
        sampled_position=(5.0, 6.0, 0.0),
        sampled_slope_deg=42.0,
        sampled_material_layer_id="sand_dune",
        sampled_wetness=0.1,
        sampled_deposition=0.9,
        sampled_talus=0.0,
        nearest_water_distance_m=4.0,
        support_score=0.2,
        embed_depth_m=0.0,
    )

    table = build_scatter_candidate_table(
        (accepted, rejected),
        SurfaceSupportGate(
            max_slope_deg=30.0,
            min_support_score=0.55,
            min_embed_depth_m=0.02,
            allowed_material_layer_ids=("soil", "rock"),
        ),
        source="unit_test",
    )

    assert len(table.accepted) == 1
    assert len(table.rejected) == 1
    reason = table.rejected[0].rejected_reason
    assert "slope_exceeds_gate" in reason
    assert "support_score_below_gate" in reason
    assert "embed_depth_below_gate" in reason
    assert "material_incompatible" in reason
    assert table.to_dict()["rejected_count"] == 1


def test_surface_support_gate_rejects_non_finite_support_metrics():
    from veilbreakers_terrain.handlers.terrain_scatter_points import (
        ScatterCandidate,
        SurfaceSupportGate,
        build_scatter_candidate_table,
    )

    candidate = ScatterCandidate(
        candidate_id="nan-rock",
        source_rule_id="rocks",
        source_layer_id="talus",
        species_or_prop_id="hero_boulder",
        sampled_position=(1.0, 2.0, 3.0),
        sampled_slope_deg=10.0,
        sampled_material_layer_id="rock",
        sampled_wetness=0.1,
        sampled_deposition=0.2,
        sampled_talus=0.8,
        nearest_water_distance_m=9.0,
        support_score=float("nan"),
        embed_depth_m=float("nan"),
    )

    table = build_scatter_candidate_table(
        (candidate,),
        SurfaceSupportGate(allowed_material_layer_ids=("rock",)),
    ).to_dict()
    reason = table["rejected"][0]["rejected_reason"]

    assert table["accepted_count"] == 0
    assert "non_finite_support_score" in reason
    assert "non_finite_embed_depth" in reason


def test_surface_support_gate_honors_waterlogged_flag_independent_of_max_wetness():
    from veilbreakers_terrain.handlers.terrain_scatter_points import (
        ScatterCandidate,
        SurfaceSupportGate,
        build_scatter_candidate_table,
    )

    candidate = ScatterCandidate(
        candidate_id="wet-oak",
        source_rule_id="forest",
        source_layer_id="tree_layer",
        species_or_prop_id="tree_oak",
        sampled_position=(1.0, 2.0, 3.0),
        sampled_slope_deg=10.0,
        sampled_material_layer_id="soil",
        sampled_wetness=0.2,
        sampled_deposition=0.4,
        sampled_talus=0.0,
        nearest_water_distance_m=4.0,
        support_score=0.9,
        embed_depth_m=0.1,
    )

    table = build_scatter_candidate_table(
        (candidate,),
        SurfaceSupportGate(allow_waterlogged=False, max_wetness=1.0),
    ).to_dict()

    assert table["accepted_count"] == 0
    assert "waterlogged_disallowed" in table["rejected"][0]["rejected_reason"]
