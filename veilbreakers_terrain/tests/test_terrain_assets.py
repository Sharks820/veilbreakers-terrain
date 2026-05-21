"""Bundle E — Scatter Intelligence tests.

Covers:
    - compute_viability filters by slope / altitude / required_masks
    - place_assets_by_zone is deterministic and respects viability
    - cluster_rocks_for_* concentrate around hero candidate cells
    - validate_asset_density_and_overlap flags over-dense scatter
    - pass_scatter_intelligent populates tree_instance_points (N, 5)
      and detail_density
    - Region scoping + protected zones zero out placements there
    - Poisson disk respects cluster_radius_m
    - AssetRole round-trip via classify_asset_role
"""

from __future__ import annotations

import math
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from numpy.typing import NDArray

from veilbreakers_terrain.handlers.terrain_assets import (
    AssetContextRule,
    AssetRole,
    _build_detail_density,
    _build_tree_instance_array,
    _cell_to_world,
    _cluster_around,
    _poisson_in_mask,
    _region_mask,
    _water_exclusion_mask,
    build_asset_context_rules,
    classify_asset_role,
    cluster_rocks_for_cliffs,
    cluster_rocks_for_waterfalls,
    compute_viability,
    place_assets_by_zone,
    register_bundle_e_passes,
    scatter_debris_for_caves,
    validate_asset_density_and_overlap,
)
from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    ProtectedZoneSpec,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
    TerrainSceneRead,
)


Point3 = tuple[float, float, float]
PlacementMap = Mapping[str, Sequence[Point3]]
FloatArray = NDArray[np.float32]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_stack(tile_size: int = 32, seed: int = 0) -> TerrainMaskStack:
    rng = np.random.default_rng(seed)
    height = (rng.random((tile_size + 1, tile_size + 1)).astype(np.float64) * 100.0)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    # Populate baseline masks so viability logic has signals
    h = stack.height.shape
    stack.set("slope", np.full(h, math.radians(10.0), dtype=np.float32), "test_fixture")
    stack.set("wetness", np.full(h, 0.5, dtype=np.float32), "test_fixture")
    return stack


def _make_intent(
    stack: TerrainMaskStack,
    seed: int = 1234,
    protected_zones: Sequence[ProtectedZoneSpec] = (),
) -> TerrainIntentState:
    region_bounds = BBox(
        0.0, 0.0,
        float(stack.tile_size) * stack.cell_size,
        float(stack.tile_size) * stack.cell_size,
    )
    scene_read = TerrainSceneRead(
        timestamp=0.0,
        major_landforms=("flatland",),
        focal_point=(0.0, 0.0, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=tuple(z.zone_id for z in protected_zones),
        edit_scope=region_bounds,
        success_criteria=("scatter_test",),
        reviewer="pytest",
    )
    return TerrainIntentState(
        seed=seed,
        region_bounds=region_bounds,
        tile_size=stack.tile_size,
        cell_size=stack.cell_size,
        protected_zones=tuple(protected_zones),
        scene_read=scene_read,
    )


@pytest.fixture
def stack() -> TerrainMaskStack:
    return _make_stack()


@pytest.fixture
def intent(stack: TerrainMaskStack) -> TerrainIntentState:
    return _make_intent(stack)


@pytest.fixture(autouse=True)
def register_bundle_e_fixture() -> Iterator[None]:
    TerrainPassController.clear_registry()
    register_bundle_e_passes()
    yield
    TerrainPassController.clear_registry()


# ---------------------------------------------------------------------------
# compute_viability
# ---------------------------------------------------------------------------


def test_compute_viability_zeros_wrong_slope(stack: TerrainMaskStack) -> None:
    # All cells have slope = 10 deg; require 30..60 deg => zero
    rule = AssetContextRule(
        asset_id="cliff_only",
        role=AssetRole.ROCK_CLIFF_BASE,
        min_slope_rad=math.radians(30.0),
        max_slope_rad=math.radians(60.0),
    )
    viab = compute_viability(rule, stack)
    assert viab.shape == stack.height.shape
    assert np.all(viab == 0.0)


def test_compute_viability_zeros_wrong_altitude(stack: TerrainMaskStack) -> None:
    # Stack altitudes are [0, 100]; require 1000..2000 => zero
    rule = AssetContextRule(
        asset_id="highland",
        role=AssetRole.VEGETATION_LARGE,
        min_altitude_m=1000.0,
        max_altitude_m=2000.0,
    )
    viab = compute_viability(rule, stack)
    assert np.all(viab == 0.0)


def test_compute_viability_respects_required_masks(stack: TerrainMaskStack) -> None:
    # No cliff_candidate channel set at all → viability must be zero
    rule = AssetContextRule(
        asset_id="cliff_boulder",
        role=AssetRole.ROCK_CLIFF_BASE,
        required_masks=("cliff_candidate",),
    )
    viab = compute_viability(rule, stack)
    assert np.all(viab == 0.0)

    # Populate half of the map with cliff_candidate => that half viable
    h, w = stack.height.shape
    cliff = np.zeros((h, w), dtype=np.float32)
    cliff[:, w // 2 :] = 1.0
    stack.set("cliff_candidate", cliff, "test")
    viab2 = compute_viability(rule, stack)
    assert np.all(viab2[:, : w // 2] == 0.0)
    assert np.any(viab2[:, w // 2 :] > 0.0)


def test_compute_viability_respects_forbidden_masks(stack: TerrainMaskStack) -> None:
    h, w = stack.height.shape
    hero_excl = np.zeros((h, w), dtype=np.float32)
    hero_excl[: h // 2, :] = 1.0
    stack.set("hero_exclusion", hero_excl, "test")
    rule = AssetContextRule(
        asset_id="grass_clump",
        role=AssetRole.GROUND_COVER,
        max_slope_rad=math.radians(25.0),
        forbidden_masks=("hero_exclusion",),
    )
    viab = compute_viability(rule, stack)
    assert np.all(viab[: h // 2, :] == 0.0)
    assert np.any(viab[h // 2 :, :] > 0.0)


def test_compute_viability_excludes_water_surface_elevation_cells(stack: TerrainMaskStack) -> None:
    _, w = stack.height.shape
    water_elev = np.asarray(stack.height, dtype=np.float32).copy()
    water_elev[:, : w // 2] += 2.0
    stack.set("water_surface_elevation_m", water_elev, "test")
    rule = AssetContextRule(
        asset_id="grass_clump",
        role=AssetRole.GROUND_COVER,
        max_slope_rad=math.radians(25.0),
    )

    viab = compute_viability(rule, stack)

    assert np.all(viab[:, : w // 2] == 0.0)
    assert np.any(viab[:, w // 2 :] > 0.0)


def test_water_exclusion_mask_merges_authoritative_water_channels() -> None:
    stack = _make_stack(tile_size=3)
    height = np.full((4, 4), 10.0, dtype=np.float32)
    stack.height[...] = height
    stack.set("water_surface_elevation_m", height.copy(), "test")
    stack.get("water_surface_elevation_m")[0, 0] = 10.2
    depth = np.zeros_like(height)
    depth[1, 1] = 0.2
    stack.set("water_depth_m", depth, "test")
    surface_mask = np.zeros_like(height)
    surface_mask[2, 2] = 1.0
    surface_mask[3, 3] = 1.0  # W-1: legacy water_surface no longer read; use water_surface_mask
    stack.set("water_surface_mask", surface_mask, "test")

    water = _water_exclusion_mask(stack, height)

    assert water.dtype == bool
    assert water.shape == height.shape
    assert water[0, 0]
    assert water[1, 1]
    assert water[2, 2]
    assert water[3, 3]
    assert not water[0, 1]


def test_cell_to_world_uses_cell_centres_and_height_channel(stack: TerrainMaskStack) -> None:
    stack.cell_size = 2.0
    stack.world_origin_x = 100.0
    stack.world_origin_y = -50.0
    stack.height[3, 4] = 77.0

    np.testing.assert_allclose(_cell_to_world(stack, 3, 4), (109.0, -43.0, 77.0))


def test_region_mask_selects_world_space_cell_centres() -> None:
    stack = _make_stack(tile_size=3)
    stack.cell_size = 2.0
    stack.world_origin_x = 10.0
    stack.world_origin_y = 20.0
    stack.height[...] = 0.0

    mask = _region_mask(stack, BBox(13.0, 23.0, 17.0, 27.0))

    assert mask is not None
    assert mask.shape == (4, 4)
    assert mask[1, 1]
    assert mask[2, 3]
    assert not mask[0, 0]
    assert not mask[3, 0]


def test_region_mask_none_returns_none(stack: TerrainMaskStack) -> None:
    assert _region_mask(stack, None) is None


def test_poisson_in_mask_is_deterministic_and_respects_region() -> None:
    viability = np.ones((8, 8), dtype=np.float32)
    region = np.zeros_like(viability, dtype=bool)
    region[2:6, 3:7] = True

    cells_a = _poisson_in_mask(viability, 1.0, 2.0, seed=44, region_mask=region)
    cells_b = _poisson_in_mask(viability, 1.0, 2.0, seed=44, region_mask=region)

    assert cells_a == cells_b
    assert cells_a
    for row, col in cells_a:
        assert region[row, col]
    for idx, (row_a, col_a) in enumerate(cells_a):
        for row_b, col_b in cells_a[idx + 1 :]:
            distance = math.hypot(col_a - col_b, row_a - row_b)
            assert distance >= 2.0 - 1e-6


def test_poisson_in_mask_rejects_empty_or_invalid_inputs() -> None:
    viability = np.zeros((4, 4), dtype=np.float32)

    assert _poisson_in_mask(viability, 1.0, 1.0, seed=1) == []
    assert _poisson_in_mask(np.ones((4, 4), dtype=np.float32), 1.0, 0.0, seed=1) == []
    assert _poisson_in_mask(
        np.ones((4, 4), dtype=np.float32),
        1.0,
        1.0,
        seed=1,
        region_mask=np.zeros((4, 4), dtype=bool),
    ) == []


# ---------------------------------------------------------------------------
# place_assets_by_zone
# ---------------------------------------------------------------------------


def test_place_assets_by_zone_deterministic(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    rules = [
        AssetContextRule(
            asset_id="grass_clump",
            role=AssetRole.GROUND_COVER,
            max_slope_rad=math.radians(25.0),
            cluster_radius_m=1.5,
        )
    ]
    a = place_assets_by_zone(stack, intent, rules)
    b = place_assets_by_zone(stack, intent, rules)
    assert a == b
    assert len(a["grass_clump"]) > 0


def test_place_assets_by_zone_only_viable_cells(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    # Restrict by altitude window: only cells with height in [40, 60]
    rule = AssetContextRule(
        asset_id="bush",
        role=AssetRole.VEGETATION_SMALL,
        min_altitude_m=40.0,
        max_altitude_m=60.0,
        max_slope_rad=math.radians(30.0),
        cluster_radius_m=1.2,
    )
    placements = place_assets_by_zone(stack, intent, [rule])
    for (_x, _y, z) in placements["bush"]:
        assert 40.0 <= z <= 60.0


def test_place_assets_uses_height_channel_for_z(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    """Z value MUST come from stack.height — not a re-sampled scene function."""
    # Overwrite height with a constant 42m to prove z reads from channel.
    stack.height[:] = 42.0
    rule = AssetContextRule(
        asset_id="grass_clump",
        role=AssetRole.GROUND_COVER,
        max_slope_rad=math.radians(25.0),
        cluster_radius_m=1.5,
    )
    placements = place_assets_by_zone(stack, intent, [rule])
    assert len(placements["grass_clump"]) > 0
    for (_x, _y, z) in placements["grass_clump"]:
        assert math.isclose(z, 42.0)


def test_poisson_disk_honors_cluster_radius(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    rule = AssetContextRule(
        asset_id="oak_tree",
        role=AssetRole.VEGETATION_LARGE,
        max_slope_rad=math.radians(35.0),
        cluster_radius_m=3.5,
    )
    placements = place_assets_by_zone(stack, intent, [rule])
    pts = placements["oak_tree"]
    assert len(pts) >= 2
    arr = np.array([(p[0], p[1]) for p in pts])
    diffs = arr[:, None, :] - arr[None, :, :]
    dist_sq = (diffs ** 2).sum(-1)
    np.fill_diagonal(dist_sq, np.inf)
    # All pair distances >= cluster_radius_m (with tiny epsilon for fp)
    assert dist_sq.min() >= (3.5 ** 2) - 1e-6


def test_region_scoped_scatter_leaves_outside_empty(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    rule = AssetContextRule(
        asset_id="grass_clump",
        role=AssetRole.GROUND_COVER,
        max_slope_rad=math.radians(25.0),
        cluster_radius_m=1.0,
    )
    region = BBox(5.0, 5.0, 12.0, 12.0)
    placements = place_assets_by_zone(stack, intent, [rule], region=region)
    for (x, y, _z) in placements["grass_clump"]:
        assert 5.0 <= x <= 12.0
        assert 5.0 <= y <= 12.0
    assert len(placements["grass_clump"]) > 0


def test_protected_zones_zero_placements(stack: TerrainMaskStack) -> None:
    # Protect the whole region — no placements should occur.
    full_bounds = BBox(
        0.0, 0.0,
        stack.tile_size * stack.cell_size,
        stack.tile_size * stack.cell_size,
    )
    zone = ProtectedZoneSpec(
        zone_id="noscatter",
        bounds=full_bounds,
        kind="hero_mesh",
        forbidden_mutations=frozenset({"scatter_intelligent"}),
    )
    intent = _make_intent(stack, protected_zones=(zone,))
    rules = build_asset_context_rules()
    h, w = stack.height.shape
    protected = np.ones((h, w), dtype=bool)
    placements = place_assets_by_zone(stack, intent, rules, protected=protected)
    total = sum(len(v) for v in placements.values())
    assert total == 0


# ---------------------------------------------------------------------------
# Cluster helpers
# ---------------------------------------------------------------------------


def test_cluster_rocks_for_cliffs_concentrates_near_cliff_cells(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    h, w = stack.height.shape
    cliff = np.zeros((h, w), dtype=np.float32)
    cliff[h // 2, w // 2] = 1.0
    points = cluster_rocks_for_cliffs(stack, cliff, intent)
    assert len(points) >= 3
    cx = stack.world_origin_x + (w // 2 + 0.5) * stack.cell_size
    cy = stack.world_origin_y + (h // 2 + 0.5) * stack.cell_size
    for (x, y, _z) in points:
        assert abs(x - cx) <= 5.0
        assert abs(y - cy) <= 5.0


def test_cluster_rocks_for_waterfalls_concentrates_near_lip(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    h, w = stack.height.shape
    lip = np.zeros((h, w), dtype=np.float32)
    lip[8, 8] = 1.0
    points = cluster_rocks_for_waterfalls(stack, lip, intent)
    assert len(points) >= 3
    cx = stack.world_origin_x + 8.5 * stack.cell_size
    cy = stack.world_origin_y + 8.5 * stack.cell_size
    for (x, y, _z) in points:
        assert math.hypot(x - cx, y - cy) <= 5.0


def test_scatter_debris_for_caves_clusters_near_mouth(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    h, w = stack.height.shape
    cave = np.zeros((h, w), dtype=np.float32)
    cave[4, 4] = 1.0
    points = scatter_debris_for_caves(stack, cave, intent)
    assert len(points) >= 3


def test_cluster_around_is_deterministic_and_region_scoped(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    hot = np.zeros(stack.height.shape, dtype=np.float32)
    hot[3, 3] = 1.0
    hot[20, 20] = 1.0
    region = BBox(0.0, 0.0, 8.0, 8.0)

    points_a = _cluster_around(
        stack,
        hot,
        intent,
        namespace="audit_cluster",
        min_per_center=2,
        max_per_center=2,
        radius_m=2.0,
        region=region,
    )
    points_b = _cluster_around(
        stack,
        hot,
        intent,
        namespace="audit_cluster",
        min_per_center=2,
        max_per_center=2,
        radius_m=2.0,
        region=region,
    )

    assert points_a == points_b
    assert len(points_a) == 2
    for x, y, _z in points_a:
        assert 0.0 <= x <= 8.0
        assert 0.0 <= y <= 8.0


def test_cluster_around_rejects_missing_bad_shape_and_bad_cell_size(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    assert _cluster_around(
        stack,
        cast(FloatArray, None),
        intent,
        namespace="empty",
        min_per_center=1,
        max_per_center=1,
        radius_m=1.0,
    ) == []
    assert _cluster_around(
        stack,
        np.ones((2, 2), dtype=np.float32),
        intent,
        namespace="bad_shape",
        min_per_center=1,
        max_per_center=1,
        radius_m=1.0,
    ) == []

    stack.cell_size = 0.0
    assert _cluster_around(
        stack,
        np.ones(stack.height.shape, dtype=np.float32),
        intent,
        namespace="bad_cell",
        min_per_center=1,
        max_per_center=1,
        radius_m=1.0,
    ) == []


def test_build_tree_instance_array_flattens_tree_like_roles_only() -> None:
    placements: PlacementMap = {
        "oak_tree": [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)],
        "bush": [(7.0, 8.0, 9.0)],
        "grass": [(10.0, 11.0, 12.0)],
        "unknown": [(13.0, 14.0, 15.0)],
    }
    rules = [
        AssetContextRule("oak_tree", AssetRole.VEGETATION_LARGE),
        AssetContextRule("bush", AssetRole.VEGETATION_SMALL),
        AssetContextRule("grass", AssetRole.GROUND_COVER),
    ]
    rng = np.random.default_rng(7)

    arr = _build_tree_instance_array(placements, rules, rng)

    assert arr.shape == (3, 5)
    np.testing.assert_allclose(arr[:, :3], np.array(placements["oak_tree"] + placements["bush"]))
    assert np.all(arr[:, 3] >= 0.0)
    # ADV-CP4-02: column 3 is ``yaw_degrees`` per Channel.YAW_DEG contract;
    # range is [0, 360) degrees (was [0, 2*pi] radians pre-hotfix).
    assert np.all(arr[:, 3] <= 360.0)
    # PR #118 round-3 (copilot PRRT_kwDOSDBoMs6DpwYo): the prototype-id
    # column assertion was dropped during round-1's degrees-contract refit.
    # Restore it so a regression in ``_build_tree_instance_array`` that
    # scrambles or collapses ``prototype_id`` values (e.g. all rows getting
    # the same stable id 0.0, or a sort order that breaks role grouping)
    # is caught at the smallest possible witness.
    #
    # Expected mapping for the 3 input placements (after role filter +
    # tree-like role grouping by oak_tree → bush):
    #   row 0: oak_tree #1 (1, 2, 3)  → prototype_id 0.0
    #   row 1: oak_tree #2 (4, 5, 6)  → prototype_id 0.0  (same prototype)
    #   row 2: bush      (7, 8, 9)    → prototype_id 1.0
    # ``grass`` (GROUND_COVER) is excluded from this builder by role; the
    # "unknown" id has no rule entry so the role lookup defaults to a
    # non-tree role and it is also filtered out.
    assert arr[:, 4].tolist() == [0.0, 0.0, 1.0]


def test_build_tree_instance_array_returns_empty_contract_for_non_tree_roles() -> None:
    arr = _build_tree_instance_array(
        {"grass": [(1.0, 1.0, 0.0)]},
        [AssetContextRule("grass", AssetRole.GROUND_COVER)],
        np.random.default_rng(1),
    )

    assert arr.shape == (0, 5)
    assert arr.dtype == np.float32


def test_build_detail_density_bins_ground_cover_by_cell() -> None:
    stack = _make_stack(tile_size=3)
    stack.height[...] = 0.0
    stack.cell_size = 2.0
    stack.world_origin_x = 10.0
    stack.world_origin_y = 20.0
    placements: PlacementMap = {
        "grass": [(11.0, 21.0, 0.0), (11.5, 21.5, 0.0), (17.9, 27.9, 0.0)],
        "oak": [(13.0, 23.0, 0.0)],
    }
    rules = [
        AssetContextRule("grass", AssetRole.GROUND_COVER),
        AssetContextRule("oak", AssetRole.VEGETATION_LARGE),
    ]

    density = _build_detail_density(placements, rules, stack)

    assert set(density) == {"grass"}
    assert density["grass"].shape == (4, 4)
    assert density["grass"].dtype == np.float32
    assert math.isclose(float(density["grass"][0, 0]), 2.0)
    assert math.isclose(float(density["grass"][3, 3]), 1.0)
    assert math.isclose(float(density["grass"].sum()), 3.0)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_flags_overdense(stack: TerrainMaskStack) -> None:
    # Dense cluster of 100 grass points in a 1m^2 area.
    pts = [(float(i) * 0.05, 0.0, 0.0) for i in range(100)]
    placements: PlacementMap = {"grass_clump": pts}
    rules = [
        AssetContextRule(
            asset_id="grass_clump",
            role=AssetRole.GROUND_COVER,
            cluster_radius_m=0.5,
        )
    ]
    issues = validate_asset_density_and_overlap(
        placements, rules, max_density_per_m2=1.0, area_m2=10.0,
    )
    codes = {i.code for i in issues}
    assert "SCATTER_OVERDENSE" in codes or "SCATTER_OVERLAP" in codes


# ---------------------------------------------------------------------------
# classify_asset_role
# ---------------------------------------------------------------------------


def test_asset_role_roundtrip() -> None:
    assert classify_asset_role("oak_tree") == AssetRole.VEGETATION_LARGE
    assert classify_asset_role("grass_clump") == AssetRole.GROUND_COVER
    assert classify_asset_role("cliff_boulder") == AssetRole.ROCK_CLIFF_BASE
    assert classify_asset_role("cave_rubble") == AssetRole.ROCK_CAVE_DEBRIS
    assert classify_asset_role("ambient_wind") == AssetRole.AUDIO_SOURCE
    # Unknown → heuristic: "mystery_tree" matches "tree"
    assert classify_asset_role("mystery_tree") == AssetRole.VEGETATION_LARGE
    # Override mapping
    override = {"oak_tree": AssetRole.HERO_PROP}
    assert classify_asset_role("oak_tree", overrides=override) == AssetRole.HERO_PROP


# ---------------------------------------------------------------------------
# pass_scatter_intelligent
# ---------------------------------------------------------------------------


def test_pass_populates_tree_instance_points(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        result = controller.run_pass("scatter_intelligent", checkpoint=False)
    # T0.5-2 (Y04 v3 §P.8.2): strict-"ok" — scatter_intelligent happy path,
    # any "warning" today is a latent regression in tree-instance-point shape.
    assert result.status == "ok", result
    tp = state.mask_stack.tree_instance_points
    assert tp is not None
    assert tp.ndim == 2
    assert tp.shape[1] == 5  # Unity contract: (x, y, z, rot, prototype_id)
    assert tp.shape[0] > 0


def test_pass_populates_detail_density(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        controller.run_pass("scatter_intelligent", checkpoint=False)
    detail = state.mask_stack.detail_density
    assert detail is not None
    assert isinstance(detail, dict)
    assert len(detail) >= 1
    for _name, arr in detail.items():
        assert arr.shape == state.mask_stack.height.shape
        assert arr.dtype == np.float32


def test_pass_preserves_existing_detail_density(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    sentinel = np.full(stack.height.shape, 0.5, dtype=np.float32)
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    state.mask_stack.set("detail_density", {"canopy": sentinel.copy()}, "test_fixture")
    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        controller.run_pass("scatter_intelligent", checkpoint=False)
    detail = state.mask_stack.detail_density
    assert detail is not None
    np.testing.assert_array_equal(detail["canopy"], sentinel)


def test_scatter_registration_declares_detail_density_output() -> None:
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    definition = TerrainPassController.get_pass("scatter_intelligent")
    assert "detail_density" in definition.produces_channels
    assert "detail_density" in definition.optional_channels
    assert "detail_density" in definition.overrides


def test_pass_unity_ready_shape(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
) -> None:
    """Explicit Unity contract check: tree_instance_points is (N, 5)."""
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        controller.run_pass("scatter_intelligent", checkpoint=False)
    tp = state.mask_stack.tree_instance_points
    assert tp is not None
    assert tp.shape[1] == 5
    # All rotations in valid range
    assert np.all(tp[:, 3] >= 0.0)
    # ADV-CP4-02: column 3 is yaw_degrees (degrees) post-PR #114 retag; the
    # producer ``_build_tree_instance_array`` now writes ``rng.uniform(0, 360)``
    # rather than radians ``rng.uniform(0, 2*pi)``.
    assert np.all(tp[:, 3] <= 360.0 + 1e-6)
    # Prototype IDs are non-negative integers-as-float
    assert np.all(tp[:, 4] >= 0.0)
