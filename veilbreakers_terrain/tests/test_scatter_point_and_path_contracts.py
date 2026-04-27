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
