"""Bundle B — tests for terrain_cliffs.py.

Pure-numpy cliff analysis. All fixtures construct a synthetic heightmap
that guarantees a deterministic cliff signature.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from types import SimpleNamespace

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


def _build_cliff_state(tile_size: int = 48):
    """Build a state with a single synthetic cliff in the centre.

    The heightmap has:
      - a flat plateau at z = 40 in the top half
      - a flat plain at z = 5 in the bottom half
      - a sharp vertical drop between them
    This gives a single connected cliff region with high slope and
    clear lip geometry.
    """
    from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    N = tile_size + 1
    height = np.zeros((N, N), dtype=np.float64)
    # Top half (rows < N/2): high plateau; bottom half: low plain
    half = N // 2
    height[:half, :] = 40.0
    height[half:, :] = 5.0
    # Add a little noise so slope + curvature don't degenerate at edges
    rng = np.random.default_rng(42)
    height += rng.normal(0.0, 0.05, size=height.shape)

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
        seed=1234,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def _build_two_cliff_state(tile_size: int = 48):
    """Two isolated high plateaus separated by low ground — two cliffs."""
    from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    N = tile_size + 1
    height = np.full((N, N), 5.0, dtype=np.float64)
    # Left plateau
    height[10:22, 5:15] = 35.0
    # Right plateau (disconnected from the left)
    height[10:22, 30:40] = 35.0
    rng = np.random.default_rng(7)
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
        seed=1,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# Helper contracts
# ---------------------------------------------------------------------------


def test_repose_for_material_is_deterministic_and_material_bounded():
    from veilbreakers_terrain.handlers.terrain_cliffs import _repose_for_material

    loose = _repose_for_material("loose_rock", rng_seed=11)
    loose_again = _repose_for_material("loose_rock", rng_seed=11)
    fallback = _repose_for_material("unknown_material", rng_seed=11)

    assert loose == pytest.approx(loose_again)
    assert math.radians(30.0) <= loose <= math.radians(35.0)
    assert math.radians(32.0) <= fallback <= math.radians(36.0)


def test_contour_smoothing_and_bspline_preserve_shape_contracts():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        _fit_bspline_contour,
        _smooth_contour_gaussian,
    )

    pts = np.array(
        [[0.0, 0.0], [0.0, 4.0], [2.0, 6.0], [4.0, 4.0], [4.0, 0.0]],
        dtype=np.float64,
    )

    smoothed = _smooth_contour_gaussian(pts, sigma=1.0, closed=True)
    spline = _fit_bspline_contour(smoothed, n_samples=17, closed=True)
    short = _fit_bspline_contour(pts[:3], n_samples=20, closed=False)

    assert smoothed.shape == pts.shape
    assert smoothed.dtype == np.float64
    assert spline.shape == (17, 2)
    np.testing.assert_array_equal(short, pts[:3])


def test_bspline_no_scipy_fallback_returns_exact_requested_sample_count(monkeypatch):
    from veilbreakers_terrain.handlers.terrain_cliffs import _fit_bspline_contour

    import builtins

    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "scipy" or name.startswith("scipy."):
            raise ImportError("blocked scipy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    pts = np.array(
        [[0.0, 0.0], [0.0, 4.0], [2.0, 6.0], [4.0, 4.0], [4.0, 0.0]],
        dtype=np.float64,
    )

    spline = _fit_bspline_contour(pts, n_samples=17, closed=True)

    assert spline.shape == (17, 2)
    assert np.isfinite(spline).all()


def test_moore_contour_helpers_cover_components_and_empty_masks():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        _moore_contour_all_components,
        _trace_moore_boundary,
    )

    empty = np.zeros((6, 6), dtype=bool)
    mask = empty.copy()
    mask[1:3, 1:3] = True
    mask[4:6, 4:6] = True

    assert _trace_moore_boundary(empty).shape == (0, 2)
    boundary = _trace_moore_boundary(mask[:3, :3])
    all_components = _moore_contour_all_components(mask)

    assert boundary.ndim == 2
    assert boundary.shape[1] == 2
    assert all_components.shape[1] == 2
    assert {tuple(p) for p in all_components}.issuperset({(1, 1), (4, 4)})


def test_strata_layers_are_seeded_bounded_and_colored():
    from veilbreakers_terrain.handlers.terrain_cliffs import _build_strata_layers

    layers_a = _build_strata_layers(40.0, 12.0, cliff_seed=99, n_layers=4)
    layers_b = _build_strata_layers(40.0, 12.0, cliff_seed=99, n_layers=4)

    assert len(layers_a) == 4
    assert [layer.thickness_m for layer in layers_a] == pytest.approx(
        [layer.thickness_m for layer in layers_b]
    )
    for layer in layers_a:
        assert layer.thickness_m >= 0.3
        assert 0.2 <= layer.hardness <= 0.9
        assert len(layer.rgb_color) == 3
        assert all(0.0 <= channel <= 1.0 for channel in layer.rgb_color)


def test_apply_micro_erosion_only_erodes_faces_above_repose():
    from veilbreakers_terrain.handlers.terrain_cliffs import _apply_micro_erosion

    height = np.full((3, 3), 10.0, dtype=np.float64)
    face = np.zeros((3, 3), dtype=bool)
    face[1, 1] = True
    face[1, 2] = True
    slope = np.full((3, 3), math.radians(20.0), dtype=np.float64)
    slope[1, 1] = math.radians(70.0)

    delta = _apply_micro_erosion(height, face, slope, math.radians(35.0), k=1.0)

    assert delta[1, 1] < 0.0
    assert delta[1, 2] == pytest.approx(0.0)
    assert np.all(delta[~face] == 0.0)


def test_region_to_slice_clamps_world_bounds_to_grid():
    from veilbreakers_terrain.handlers.terrain_cliffs import _region_to_slice
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    state = _build_cliff_state(tile_size=8)
    region = BBox(-50.0, -50.0, 500.0, 500.0)

    rows, cols = _region_to_slice(state.mask_stack, region)

    assert rows.start == 0
    assert cols.start == 0
    assert rows.stop == state.mask_stack.height.shape[0]
    assert cols.stop == state.mask_stack.height.shape[1]


def test_lip_polyline_postprocess_removes_duplicates_and_handles_empty():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        _extract_lip_polyline,
        _postprocess_lip_polyline,
    )

    empty = np.zeros((5, 5), dtype=bool)
    mask = empty.copy()
    mask[1:4, 1:4] = True
    raw = np.array([[1, 1], [1, 1], [1, 2], [2, 2]], dtype=np.int32)

    assert _extract_lip_polyline(empty, np.zeros((5, 5))).shape == (0, 2)
    lip = _extract_lip_polyline(mask, np.zeros((5, 5)))
    processed = _postprocess_lip_polyline(raw)

    assert lip.ndim == 2
    assert lip.shape[1] == 2
    assert processed.shape[0] <= raw.shape[0]


def test_cliff_base_trigger_accepts_degree_and_radian_slope_channels():
    from veilbreakers_terrain.handlers.terrain_cliffs import _cliff_base_trigger_mask

    state = _build_cliff_state(tile_size=8)
    slope_deg = np.full(state.mask_stack.height.shape, 5.0, dtype=np.float32)
    slope_deg[2:4, 2:4] = 70.0
    state.mask_stack.set("slope", slope_deg, "fixture")

    degree_trigger = _cliff_base_trigger_mask(state.mask_stack, search_cells=2)
    state.mask_stack.set("slope", np.radians(slope_deg), "fixture")
    radian_trigger = _cliff_base_trigger_mask(state.mask_stack, search_cells=2)

    assert degree_trigger.any()
    np.testing.assert_array_equal(degree_trigger, radian_trigger)


def test_generate_cliff_overhang_marks_drip_edges_deterministically():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        CliffStructure,
        _generate_cliff_overhang,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    cliff = CliffStructure(
        cliff_id="cliff_overhang",
        lip_polyline=np.array([[2, 2], [2, 5], [3, 6]], dtype=np.int32),
        face_mask=np.ones((8, 8), dtype=bool),
        world_bounds=BBox(0.0, 0.0, 8.0, 4.0),
        min_height_m=0.0,
        max_height_m=20.0,
    )

    spec_a = _generate_cliff_overhang(cliff, overhang_probability=1.0, seed=5)
    spec_b = _generate_cliff_overhang(cliff, overhang_probability=1.0, seed=5)

    assert spec_a == spec_b
    assert spec_a["total_segments"] == 2
    assert spec_a["overhang_count"] == 2
    assert len(spec_a["drip_edge_verts"]) == 4
    assert all(segment["is_drip_edge"] for segment in spec_a["segments"])


def test_cell_center_world_converts_grid_to_z_up_xy():
    from veilbreakers_terrain.handlers.terrain_cliffs import _cell_center_world

    state = _build_cliff_state(tile_size=8)
    state.mask_stack.cell_size = 2.0
    state.mask_stack.world_origin_x = 10.0
    state.mask_stack.world_origin_y = -4.0

    assert _cell_center_world(state.mask_stack, 3, 4) == pytest.approx((19.0, 3.0))


def test_fbm2_is_deterministic_and_seed_sensitive():
    from veilbreakers_terrain.handlers.terrain_cliffs import _fbm2

    value_a = _fbm2(1.25, 3.5, octaves=3, amplitude=0.5, scale=1.0, seed=123)
    value_b = _fbm2(1.25, 3.5, octaves=3, amplitude=0.5, scale=1.0, seed=123)
    value_c = _fbm2(1.25, 3.5, octaves=3, amplitude=0.5, scale=1.0, seed=456)

    assert value_a == pytest.approx(value_b)
    assert value_a != pytest.approx(value_c)
    assert -1.0 <= value_a <= 1.0


def test_build_cliff_wall_mesh_spec_exports_geometry_and_metadata():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        StrataLayer,
        _build_cliff_wall_mesh_spec,
    )

    state = _build_cliff_state(tile_size=8)
    lip = np.array([[2, 2], [2, 5], [3, 6]], dtype=np.int32)
    strata = [
        StrataLayer(thickness_m=4.0, hardness=0.8, rgb_color=(0.2, 0.2, 0.2)),
        StrataLayer(thickness_m=4.0, hardness=0.3, rgb_color=(0.7, 0.6, 0.5)),
    ]

    spec = _build_cliff_wall_mesh_spec(
        lip,
        wall_height=8.0,
        stack=state.mask_stack,
        segments_vertical=4,
        noise_amplitude=0.0,
        seed=12,
        strata_layers=strata,
    )

    assert len(spec["vertices"]) == 15
    assert len(spec["faces"]) == 8
    assert spec["metadata"]["type"] == "cliff_wall"
    assert spec["metadata"]["arc_length_m"] > 0.0
    assert len(spec["metadata"]["material_indices"]) == len(spec["faces"])
    assert spec["metadata"]["vegetation_anchors"]
    assert spec["metadata"]["lod"][0]["level"] == 0


def test_emit_overhang_meshes_directly_publishes_layer_cache():
    from veilbreakers_terrain.handlers.terrain_cliffs import pass_emit_overhang_meshes

    state = _build_cliff_state(tile_size=8)
    state.mask_stack.set("cliff_mesh_specs", [{"mesh_id": "cliff_a"}], "fixture")
    state.mask_stack.set("cave_mesh_specs", [{"mesh_id": "cave_a"}], "fixture")

    result = pass_emit_overhang_meshes(state, region=None)

    assert result.status == "ok"
    assert result.metrics["mesh_spec_count"] == 2
    assert len(state.mesh_layer_specs) == 1
    assert list(state.mesh_layer_specs.values())[0] == [
        {"mesh_id": "cliff_a"},
        {"mesh_id": "cave_a"},
    ]


def test_protected_mask_for_cliffs_respects_zone_permissions():
    from dataclasses import replace

    from veilbreakers_terrain.handlers.terrain_cliffs import _protected_mask_for_cliffs
    from veilbreakers_terrain.handlers.terrain_semantics import ProtectedZoneSpec

    state = _build_cliff_state(tile_size=8)
    zone = ProtectedZoneSpec(
        zone_id="hero",
        bounds=state.intent.region_bounds,
        kind="hero_mesh",
        forbidden_mutations=frozenset({"cliffs"}),
    )
    state.intent = replace(state.intent, protected_zones=(zone,))

    mask = _protected_mask_for_cliffs(state, state.mask_stack.height.shape)

    assert mask.shape == state.mask_stack.height.shape
    assert mask.any()


def test_pass_cliffs_direct_region_scope_publishes_contract_channels():
    from veilbreakers_terrain.handlers.terrain_cliffs import pass_cliffs
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    state = _build_cliff_state(tile_size=32)
    region = BBox(0.0, 0.0, 33.0, 33.0)

    result = pass_cliffs(state, region=region)

    assert result.status in ("ok", "warning")
    assert state.mask_stack.cliff_candidate is not None
    assert state.mask_stack.get("cliff_mask") is not None
    assert state.mask_stack.get("talus_mask") is not None
    assert state.mask_stack.get("strata_mask") is not None
    assert isinstance(state.mask_stack.get("cliff_mesh_specs"), list)


# ---------------------------------------------------------------------------
# Candidate mask
# ---------------------------------------------------------------------------


def test_candidate_mask_respects_slope_threshold():
    from veilbreakers_terrain.handlers.terrain_cliffs import build_cliff_candidate_mask

    state = _build_cliff_state()
    low = build_cliff_candidate_mask(state.mask_stack, slope_threshold_deg=20.0)
    high = build_cliff_candidate_mask(state.mask_stack, slope_threshold_deg=85.0)
    # A lower threshold must produce AT LEAST as many candidate cells
    assert int(low.sum()) >= int(high.sum())
    assert int(low.sum()) > 0, "cliff heightmap should produce candidates at 20 deg"


def test_candidate_mask_excludes_hero_exclusion():
    from veilbreakers_terrain.handlers.terrain_cliffs import build_cliff_candidate_mask

    state = _build_cliff_state()
    # Exclude the upper half of the grid — should eliminate the cliff
    excl = np.zeros_like(state.mask_stack.height, dtype=bool)
    excl[:] = True
    state.mask_stack.set("hero_exclusion", excl, "fixture")
    mask = build_cliff_candidate_mask(state.mask_stack, slope_threshold_deg=20.0)
    assert int(mask.sum()) == 0


def test_candidate_mask_drops_small_clusters():
    from veilbreakers_terrain.handlers.terrain_cliffs import build_cliff_candidate_mask

    state = _build_cliff_state()
    mask = build_cliff_candidate_mask(
        state.mask_stack,
        slope_threshold_deg=20.0,
        min_cluster_size=10000,  # too large — should drop everything
    )
    assert int(mask.sum()) == 0


# ---------------------------------------------------------------------------
# Connected components / carving
# ---------------------------------------------------------------------------


def test_carve_cliff_system_finds_single_cliff():
    from veilbreakers_terrain.handlers.terrain_cliffs import carve_cliff_system

    state = _build_cliff_state()
    cliffs = carve_cliff_system(state, region=None)
    assert len(cliffs) >= 1
    top = cliffs[0]
    assert top.face_mask.any()
    assert top.cell_count > 0
    assert top.max_height_m > top.min_height_m


def test_carve_cliff_system_separates_two_components():
    from veilbreakers_terrain.handlers.terrain_cliffs import carve_cliff_system

    state = _build_two_cliff_state()
    cliffs = carve_cliff_system(state, region=None, min_component_size=5)
    # Two plateaus -> at least two cliff components
    assert len(cliffs) >= 2
    # Component face masks must be disjoint
    a = cliffs[0].face_mask
    b = cliffs[1].face_mask
    assert int((a & b).sum()) == 0


def test_carve_cliff_system_respects_max_cliff_count():
    from veilbreakers_terrain.handlers.terrain_cliffs import carve_cliff_system

    state = _build_two_cliff_state()
    cliffs = carve_cliff_system(
        state, region=None, max_cliff_count=1, min_component_size=5
    )
    assert len(cliffs) == 1


# ---------------------------------------------------------------------------
# Ledges
# ---------------------------------------------------------------------------


def test_add_cliff_ledges_scales_with_span():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        add_cliff_ledges,
        carve_cliff_system,
    )

    state = _build_cliff_state()
    cliffs = carve_cliff_system(state, region=None)
    assert cliffs
    cliff = cliffs[0]
    # span is ~35m => count should be 3
    add_cliff_ledges(cliff, height=state.mask_stack.height)
    assert len(cliff.ledges) == 3


def test_add_cliff_ledges_honors_explicit_count():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        add_cliff_ledges,
        carve_cliff_system,
    )

    state = _build_cliff_state()
    cliffs = carve_cliff_system(state, region=None)
    cliff = cliffs[0]
    add_cliff_ledges(cliff, count=2, height=state.mask_stack.height)
    assert len(cliff.ledges) <= 2


# ---------------------------------------------------------------------------
# Talus
# ---------------------------------------------------------------------------


def test_talus_field_disjoint_from_face_mask():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        build_talus_field,
        carve_cliff_system,
    )

    state = _build_cliff_state()
    cliffs = carve_cliff_system(state, region=None)
    cliff = cliffs[0]
    talus = build_talus_field(cliff, state.mask_stack)
    # Non-overlap with face mask
    overlap = int((talus.mask & cliff.face_mask).sum())
    assert overlap == 0
    # Default material now uses a deterministic value within the upgraded
    # 32-36 degree default repose band.
    assert math.radians(32.0) <= talus.angle_of_repose_radians <= math.radians(36.0)


# ---------------------------------------------------------------------------
# pass_cliffs
# ---------------------------------------------------------------------------


def test_pass_cliffs_populates_cliff_candidate_channel():
    from veilbreakers_terrain.handlers.terrain_cliffs import register_bundle_b_passes
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    register_bundle_b_passes()
    state = _build_cliff_state()
    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        result = controller.run_pass("cliffs", checkpoint=False)
    assert result.status in ("ok", "warning")
    assert state.mask_stack.cliff_candidate is not None
    assert state.mask_stack.cliff_candidate.dtype == bool
    assert isinstance(state.mask_stack.get("cliff_mesh_specs"), list)
    assert result.metrics["cliff_count"] >= 1


def test_pass_cliffs_records_structure_side_effects():
    from veilbreakers_terrain.handlers.terrain_cliffs import register_bundle_b_passes
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    register_bundle_b_passes()
    state = _build_cliff_state()
    with tempfile.TemporaryDirectory() as td:
        controller = TerrainPassController(state, checkpoint_dir=Path(td))
        controller.run_pass("cliffs", checkpoint=False)
    effects_text = " ".join(state.side_effects)
    assert "cliff_structure:" in effects_text


def test_pass_cliffs_is_deterministic():
    from veilbreakers_terrain.handlers.terrain_cliffs import register_bundle_b_passes
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    register_bundle_b_passes()
    state_a = _build_cliff_state()
    state_b = _build_cliff_state()
    with tempfile.TemporaryDirectory() as td:
        ca = TerrainPassController(state_a, checkpoint_dir=Path(td))
        cb = TerrainPassController(state_b, checkpoint_dir=Path(td))
        ra = ca.run_pass("cliffs", checkpoint=False)
        rb = cb.run_pass("cliffs", checkpoint=False)
    assert ra.metrics["cliff_count"] == rb.metrics["cliff_count"]
    np.testing.assert_array_equal(
        state_a.mask_stack.cliff_candidate, state_b.mask_stack.cliff_candidate
    )


# ---------------------------------------------------------------------------
# validate_cliff_readability
# ---------------------------------------------------------------------------


def test_validate_cliff_readability_flags_small_face():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        CliffStructure,
        validate_cliff_readability,
    )

    state = _build_cliff_state()
    empty_face = np.zeros_like(state.mask_stack.height, dtype=bool)
    empty_face[0, 0] = True
    cliff = CliffStructure(
        cliff_id="dummy",
        lip_polyline=np.zeros((0, 2), dtype=np.int32),
        face_mask=empty_face,
    )
    issues = validate_cliff_readability(cliff, state.mask_stack)
    codes = {i.code for i in issues}
    assert "CLIFF_FACE_TOO_SMALL" in codes
    assert "CLIFF_LIP_MISSING" in codes


def test_validate_cliff_readability_passes_for_real_cliff():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        add_cliff_ledges,
        build_talus_field,
        carve_cliff_system,
        validate_cliff_readability,
    )

    state = _build_cliff_state()
    cliffs = carve_cliff_system(state, region=None)
    cliff = cliffs[0]
    add_cliff_ledges(cliff, height=state.mask_stack.height)
    build_talus_field(cliff, state.mask_stack)
    issues = validate_cliff_readability(cliff, state.mask_stack)
    hard = [i for i in issues if i.is_hard()]
    assert hard == [], f"unexpected hard issues: {hard}"


def test_hero_mesh_insertion_records_intent():
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        carve_cliff_system,
        insert_hero_cliff_meshes,
    )

    state = _build_cliff_state()
    cliffs = carve_cliff_system(state, region=None)
    # Mark first cliff as hero (carve_cliff_system already does this)
    intents = insert_hero_cliff_meshes(state, cliffs)
    assert len(intents) >= 1
    assert any("insert_hero_cliff_mesh" in s for s in state.side_effects)


def test_emit_overhang_meshes_publishes_mesh_layer_cache():
    from veilbreakers_terrain.handlers.terrain_cliffs import register_bundle_b_passes
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    register_bundle_b_passes()
    state = _build_cliff_state()
    controller = TerrainPassController(state)
    controller.run_pass("cliffs", checkpoint=False)
    result = controller.run_pass("emit_overhang_meshes", checkpoint=False)
    assert result.status == "ok"
    assert hasattr(state, "mesh_layer_specs")


def test_build_cliff_overhang_mesh_specs_uses_local_lip_heights():
    from veilbreakers_terrain.handlers.terrain_cliffs import _build_cliff_overhang_mesh_specs

    state = _build_cliff_state()
    state.mask_stack.height[10, 12] = 14.0
    state.mask_stack.height[10, 13] = 18.0
    cliff = SimpleNamespace(
        cliff_id="cliff_test",
        tier="hero",
        max_height_m=99.0,
        overhang_spec={
            "outward_normal_xy": (0.0, 1.0),
            "segments": [
                {
                    "seg_i": 0,
                    "has_overhang": True,
                    "depth_m": 2.0,
                    "base_cells": ((10, 12), (10, 13)),
                }
            ],
        },
    )

    specs = _build_cliff_overhang_mesh_specs([cliff], state.mask_stack)

    assert len(specs) == 1
    vertices = specs[0]["vertices"]
    assert vertices[0][2] == pytest.approx(14.0)
    assert vertices[1][2] == pytest.approx(18.0)
    assert vertices[2][2] == pytest.approx(18.0)
    assert vertices[3][2] == pytest.approx(14.0)
    assert specs[0]["uvs"][2] == (1.0, 1.0)


# ---------------------------------------------------------------------------
# Phase G — stratigraphy color, cliff silhouette, talus boulders,
# height-blend regression, cave strata alignment.
# ---------------------------------------------------------------------------


def test_strata_color_bands_visible_in_macro_color():
    """Per-cell strata palette is blended into macro_color when a
    stratigraphy cross-section is published on the stack."""
    from veilbreakers_terrain.handlers.terrain_macro_color import compute_macro_color
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    # Build a simple height grid with two bands
    N = 32
    height = np.zeros((N, N), dtype=np.float64)
    height[: N // 2, :] = 10.0
    height[N // 2 :, :] = 40.0

    stack = TerrainMaskStack(
        tile_size=N - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )

    baseline = compute_macro_color(stack)

    # Publish a cross-section that maps the lower band to red and the
    # upper band to blue
    surface_mat_id = np.zeros((N, N), dtype=np.int32)
    surface_mat_id[N // 2 :, :] = 1
    cross_section = {
        "layer_table": [
            {"layer_id": "red_stratum", "color_rgb": [1.0, 0.0, 0.0]},
            {"layer_id": "blue_stratum", "color_rgb": [0.0, 0.0, 1.0]},
        ],
        "surface_material_id": surface_mat_id.tolist(),
    }
    wrapper = np.empty((1,), dtype=object)
    wrapper[0] = cross_section
    stack.set("strata_cross_section", wrapper, "stratigraphy")

    stamped = compute_macro_color(stack)

    # Lower half pixel red channel must be pushed higher than baseline,
    # upper half blue channel must be pushed higher than baseline.
    assert stamped[0, 0, 0] > baseline[0, 0, 0] + 0.1
    assert stamped[N - 1, 0, 2] > baseline[N - 1, 0, 2] + 0.1


def test_cliff_silhouette_rejects_blobby():
    """A filled circular disc (maximally blobby) is rejected by
    validate_cliff_silhouette_shape."""
    from veilbreakers_terrain.handlers.terrain_materials_ext import (
        validate_cliff_silhouette_shape,
    )

    # Render a filled disc of radius 10 in a 32x32 grid — perfectly blobby
    N = 40
    yy, xx = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    centre = N // 2
    radius = 10
    mask = ((yy - centre) ** 2 + (xx - centre) ** 2) <= radius ** 2
    # Simulate a tall face — vary heights so uniformity check does not also fire
    heights = np.zeros((N, N), dtype=np.float64)
    heights[mask] = np.linspace(0, 40, int(mask.sum()))

    issues = validate_cliff_silhouette_shape(
        mask, heights=heights, cell_size_m=1.0
    )
    codes = {i.code for i in issues}
    assert "CLIFF_SILHOUETTE_TOO_BLOBBY" in codes

    # A long jagged strip should NOT be flagged blobby.
    jagged = np.zeros((N, N), dtype=bool)
    for row in range(5, 35):
        jagged[row, 10 + (row % 3) : 14 + (row % 3)] = True
    jagged_heights = np.zeros((N, N), dtype=np.float64)
    jagged_heights[jagged] = np.linspace(0, 30, int(jagged.sum()))
    jagged_issues = validate_cliff_silhouette_shape(
        jagged, heights=jagged_heights, cell_size_m=1.0
    )
    jagged_codes = {i.code for i in jagged_issues}
    assert "CLIFF_SILHOUETTE_TOO_BLOBBY" not in jagged_codes


def test_cliff_silhouette_rejects_uniform_face():
    """A cliff whose face cells all sit at nearly the same height fails
    the uniformity gate."""
    from veilbreakers_terrain.handlers.terrain_materials_ext import (
        validate_cliff_silhouette_shape,
    )

    N = 40
    mask = np.zeros((N, N), dtype=bool)
    mask[10:30, 10:30] = True
    # Flat heights — all face cells at ~20 m
    heights = np.zeros((N, N), dtype=np.float64)
    heights[mask] = 20.0

    issues = validate_cliff_silhouette_shape(mask, heights=heights, cell_size_m=1.0)
    codes = {i.code for i in issues}
    assert "CLIFF_SILHOUETTE_TOO_UNIFORM" in codes


def test_talus_boulder_power_law_distribution():
    """Boulder radii produced by place_talus_boulders_power_law follow a
    Korcak power law: N(>r) ∝ r^-D with D≈2.3, so small boulders
    dominate the count."""
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        CliffStructure,
        _sample_korcak_radii,
    )

    rng = np.random.default_rng(123)
    radii = _sample_korcak_radii(5000, rng=rng, d_exponent=2.3)

    assert radii.shape == (5000,)
    # Bounded between clamp values
    assert radii.min() >= 0.15
    assert radii.max() <= 2.75

    # Power-law heavy tail: the count of boulders with radius > 1.0 must be
    # substantially smaller than the count with radius > 0.3.
    big = int((radii > 1.0).sum())
    small = int((radii > 0.3).sum())
    assert small > big * 3, (
        f"expected heavy tail (small >> big); got small={small} big={big}"
    )

    # Monotonic cumulative count: more boulders above a smaller threshold.
    for thresh_a, thresh_b in [(0.3, 0.6), (0.6, 1.2), (1.2, 2.0)]:
        assert int((radii > thresh_a).sum()) > int((radii > thresh_b).sum())


def test_talus_boulder_placement_gated_by_slope_trigger():
    """place_talus_boulders_power_law produces no boulders when the slope
    trigger (steep >60° within 10 cells of gentle <15°) is absent."""
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        CliffStructure,
        place_talus_boulders_power_law,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    N = 32
    heights = np.zeros((N, N), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=N - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=heights,
    )
    # Slope field: everywhere gentle — no steep cells → no trigger
    stack.set("slope", np.full((N, N), 5.0, dtype=np.float32), "fixture")

    face = np.zeros((N, N), dtype=bool)
    face[5:10, 5:10] = True
    talus = np.zeros((N, N), dtype=bool)
    talus[10:20, 5:20] = True

    cliff = CliffStructure(
        cliff_id="cliff_0",
        lip_polyline=np.zeros((4, 2), dtype=np.int32),
        face_mask=face,
        talus_mask=talus,
    )
    placements = place_talus_boulders_power_law(cliff, stack)
    assert placements == []


def test_talus_boulder_placement_emits_species_tag():
    """When slope trigger is satisfied, placements carry species='talus_boulder'."""
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        CliffStructure,
        place_talus_boulders_power_law,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    N = 48
    heights = np.zeros((N, N), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=N - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=heights,
    )
    slope = np.full((N, N), 5.0, dtype=np.float32)  # gentle baseline
    slope[10:20, 5:35] = 70.0  # steep cliff band
    stack.set("slope", slope, "fixture")

    face = np.zeros((N, N), dtype=bool)
    face[10:20, 5:35] = True
    # Apron in the transition zone — some cells near the steep band
    talus = np.zeros((N, N), dtype=bool)
    talus[20:28, 5:35] = True

    cliff = CliffStructure(
        cliff_id="cliff_g",
        lip_polyline=np.zeros((4, 2), dtype=np.int32),
        face_mask=face,
        talus_mask=talus,
    )
    placements = place_talus_boulders_power_law(cliff, stack, density_per_100_m2=4.0)
    assert len(placements) > 0
    for p in placements:
        assert p["species"] == "talus_boulder"
        assert p["cliff_id"] == "cliff_g"
        assert 0.15 <= p["radius_m"] <= 2.75


def test_height_blend_weights_active_in_materials():
    """Regression guard: pass_materials (terrain_materials_v2) must call
    compute_height_blended_weights whenever a non-unity gamma is
    configured on any material channel. P1-8 was marked resolved —
    this test prevents silent regression."""
    import inspect
    from veilbreakers_terrain.handlers import terrain_materials_v2

    src = inspect.getsource(terrain_materials_v2.pass_materials)
    assert "compute_height_blended_weights" in src
    assert "height_blend_gammas" in src


def test_cave_opening_crosses_strata_flag():
    """validate_cave_opening_integration flags cave openings whose 2-cell
    ring touches > 2 distinct surface strata IDs."""
    from veilbreakers_terrain.handlers.terrain_caves import validate_cave_opening_integration
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    N = 32
    heights = np.zeros((N, N), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=N - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=heights,
    )
    # Single cave opening via cave_candidate; boundary at center
    cave = np.zeros((N, N), dtype=bool)
    cave[14:18, 14:18] = True
    stack.set("cave_candidate", cave, "fixture")
    # Cliff continuity around the opening so the cliff-side checks pass
    stack.set("cliff_candidate", np.full((N, N), 0.5, dtype=np.float32), "fixture")

    # Striated strata: each row is a different material_id → any 5x5 ring
    # will intersect many distinct IDs.
    surface = np.tile(np.arange(N, dtype=np.int32).reshape(N, 1), (1, N))
    cross_section = {
        "layer_table": [
            {"layer_id": f"s_{i}", "color_rgb": [i / N, 0.3, 0.2]} for i in range(N)
        ],
        "surface_material_id": surface.tolist(),
    }
    wrapper = np.empty((1,), dtype=object)
    wrapper[0] = cross_section
    stack.set("strata_cross_section", wrapper, "fixture")

    issues = validate_cave_opening_integration(stack)
    assert any("cave_opening_crosses_strata" in i for i in issues)
