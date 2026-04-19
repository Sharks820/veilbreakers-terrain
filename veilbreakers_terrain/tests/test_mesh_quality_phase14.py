"""Phase 14 Wave 3 mesh quality + BUG-87 + stratigraphy + water tests."""
from __future__ import annotations

import math
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fix 7.8 — generate_waterfall_mesh: 8-seg ribbon, sinusoidal Y, spray_points
# ---------------------------------------------------------------------------


class TestFix78Waterfall:
    def test_vertex_count_greater_than_100(self):
        from veilbreakers_terrain.handlers._terrain_depth import generate_waterfall_mesh

        spec = generate_waterfall_mesh(width=5.0, height=15.0, steps=4, seed=0)
        n_verts = len(spec["vertices"])
        assert n_verts > 100, (
            f"8-seg ribbon waterfall should have >100 verts, got {n_verts}"
        )

    def test_spray_points_in_metadata(self):
        from veilbreakers_terrain.handlers._terrain_depth import generate_waterfall_mesh

        spec = generate_waterfall_mesh(width=5.0, height=10.0, seed=1)
        meta = spec.get("metadata", {})
        assert "spray_points" in meta, "Foam spray points must be in metadata"
        assert len(meta["spray_points"]) >= 4


# ---------------------------------------------------------------------------
# Fix 7.9 — generate_cliff_face_mesh: strata banding + triplanar UV
# ---------------------------------------------------------------------------


class TestFix79Cliff:
    def test_strata_bands_in_metadata(self):
        from veilbreakers_terrain.handlers._terrain_depth import generate_cliff_face_mesh

        spec = generate_cliff_face_mesh(width=20.0, height=15.0, seed=0)
        meta = spec.get("metadata", {})
        assert "strata_bands" in meta, "strata_bands count must be in metadata"
        assert int(meta["strata_bands"]) >= 2

    def test_triplanar_uv_flag(self):
        from veilbreakers_terrain.handlers._terrain_depth import generate_cliff_face_mesh

        spec = generate_cliff_face_mesh(width=20.0, height=15.0, seed=0)
        meta = spec.get("metadata", {})
        assert meta.get("has_triplanar_uv") is True, "has_triplanar_uv must be True"


# ---------------------------------------------------------------------------
# Fix 7.10 — generate_cave_entrance_mesh: noise-displaced ellipse N=16, stalactites
# ---------------------------------------------------------------------------


class TestFix710Cave:
    def test_vertex_count_positive(self):
        from veilbreakers_terrain.handlers._terrain_depth import generate_cave_entrance_mesh

        spec = generate_cave_entrance_mesh(width=4.0, height=4.0, depth=3.0, seed=0)
        assert len(spec["vertices"]) > 0 and len(spec["faces"]) > 0

    def test_stalactite_hints_in_metadata(self):
        from veilbreakers_terrain.handlers._terrain_depth import generate_cave_entrance_mesh

        spec = generate_cave_entrance_mesh(width=4.0, height=4.0, depth=3.0, seed=0)
        meta = spec.get("metadata", {})
        assert "stalactite_hints" in meta, "stalactite_hints must be in metadata"
        assert len(meta["stalactite_hints"]) >= 1


# ---------------------------------------------------------------------------
# Fix 7.11 — generate_biome_transition_mesh: Z from heightmap (already done)
# ---------------------------------------------------------------------------


class TestFix711BiomeTransition:
    def test_z_set_from_heightmap(self):
        from veilbreakers_terrain.handlers._terrain_depth import generate_biome_transition_mesh

        hmap_a = np.full((8, 8), 5.0, dtype=np.float64)
        hmap_b = np.full((8, 8), 0.0, dtype=np.float64)
        spec = generate_biome_transition_mesh(
            heightmap_a=hmap_a,
            heightmap_b=hmap_b,
            heightmap_scale=1.0,
            segments=6,
            seed=0,
        )
        verts = spec["vertices"]
        # biome_a side (x < -1 after centering, blend ~ 0) should have z near 5.0
        a_side = [v[2] for v in verts if v[0] < -1.0]
        assert len(a_side) > 0
        assert max(a_side) > 1.0, (
            f"biome_a z should come from heightmap_a (5.0), got max={max(a_side):.2f}"
        )

    def test_flat_when_no_heightmap(self):
        from veilbreakers_terrain.handlers._terrain_depth import generate_biome_transition_mesh

        spec = generate_biome_transition_mesh(segments=4, seed=0)
        z_vals = [v[2] for v in spec["vertices"]]
        assert all(abs(z) < 1e-9 for z in z_vals), "Without heightmap, mesh must be flat at z=0"


# ---------------------------------------------------------------------------
# BUG-87 — carve_u_valley: scipy EDT replaces nested Python loop
# ---------------------------------------------------------------------------


class TestBug87CarveUValley:
    def test_carve_u_valley_produces_nonzero_delta(self):
        from veilbreakers_terrain.handlers.terrain_glacial import carve_u_valley
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

        stack = TerrainMaskStack(
            height=np.zeros((64, 64), dtype=np.float32),
            tile_size=64,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
        )
        path = [(10, 10), (20, 30), (30, 50), (40, 54)]  # world-space coords
        delta = carve_u_valley(stack, path, width_m=10.0, depth_m=5.0)
        assert delta.shape == (64, 64)
        assert float(delta.min()) < -0.1, "U-valley must carve negative delta"

    def test_carve_u_valley_profile_width(self):
        from veilbreakers_terrain.handlers.terrain_glacial import carve_u_valley
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

        stack = TerrainMaskStack(
            height=np.zeros((64, 64), dtype=np.float32),
            tile_size=64,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
        )
        # Straight path along row 32 (world-space: x=0..63, y=32 → col 0..63, row 32)
        path = [(0, 32), (63, 32)]
        delta = carve_u_valley(stack, path, width_m=10.0, depth_m=5.0)
        # Center of path (row 32) should be carved; far corners should be zero
        assert delta[32, 32] < -1.0, "Path center must be carved"
        assert abs(delta[0, 0]) < 0.01, "Far corner must be zero"


# ---------------------------------------------------------------------------
# BUG-98 — pass_stratigraphy sets strat_erosion_delta
# ---------------------------------------------------------------------------


class TestBug98Stratigraphy:
    def test_strat_erosion_delta_on_stack(self):
        from veilbreakers_terrain.handlers.terrain_stratigraphy import pass_stratigraphy
        from veilbreakers_terrain.handlers.terrain_semantics import (
            BBox,
            TerrainIntentState,
            TerrainMaskStack,
            TerrainPipelineState,
        )

        h = np.linspace(0, 200, 32 * 32, dtype=np.float32).reshape(32, 32)
        stack = TerrainMaskStack(
            height=h, tile_size=32, cell_size=5.0,
            world_origin_x=0.0, world_origin_y=0.0, tile_x=0, tile_y=0,
        )
        region_bounds = BBox(0.0, 0.0, 160.0, 160.0)
        intent = TerrainIntentState(
            seed=1,
            region_bounds=region_bounds,
            tile_size=32,
            cell_size=5.0,
            composition_hints={},
        )
        state = TerrainPipelineState(intent=intent, mask_stack=stack)
        pass_stratigraphy(state, None)
        assert stack.get("strat_erosion_delta") is not None, (
            "strat_erosion_delta must be set by pass_stratigraphy"
        )
        assert stack.get("strat_erosion_delta").shape == (32, 32)


# ---------------------------------------------------------------------------
# BUG-99 — pass_erosion applies rock_hardness K modifier
# ---------------------------------------------------------------------------


class TestBug99ErosionKMap:
    def test_rock_hardness_reduces_erosion(self):
        from veilbreakers_terrain.handlers._terrain_world import pass_erosion
        from veilbreakers_terrain.handlers.terrain_semantics import (
            BBox,
            TerrainIntentState,
            TerrainMaskStack,
            TerrainPipelineState,
        )

        # Use a single fixed height for both cases so terrain shape is identical;
        # only rock_hardness differs. This isolates the K modifier effect.
        h_base = np.random.default_rng(0).uniform(100, 200, (32, 32)).astype(np.float32)

        def _make_erosion_state(hardness_val: float):
            stack = TerrainMaskStack(
                height=h_base.copy(), tile_size=32, cell_size=5.0,
                world_origin_x=0.0, world_origin_y=0.0, tile_x=0, tile_y=0,
            )
            stack.set(
                "rock_hardness",
                np.full((32, 32), hardness_val, dtype=np.float32),
                "test",
            )
            stack.set(
                "strat_erosion_delta",
                np.zeros((32, 32), dtype=np.float64),
                "test",
            )
            region_bounds = BBox(0.0, 0.0, 160.0, 160.0)
            intent = TerrainIntentState(
                seed=2,
                region_bounds=region_bounds,
                tile_size=32,
                cell_size=5.0,
                composition_hints={"erosion_profile": "temperate"},
            )
            return TerrainPipelineState(intent=intent, mask_stack=stack), h_base.copy()

        state_soft, h_soft = _make_erosion_state(0.0)
        state_hard, h_hard = _make_erosion_state(1.0)

        pass_erosion(state_soft, None)
        pass_erosion(state_hard, None)

        delta_soft = float(
            np.abs(np.asarray(state_soft.mask_stack.height) - h_soft).mean()
        )
        delta_hard = float(
            np.abs(np.asarray(state_hard.mask_stack.height) - h_hard).mean()
        )

        assert delta_soft >= delta_hard, (
            f"Hard rock must resist erosion (soft_delta={delta_soft:.4f} "
            f">= hard_delta={delta_hard:.4f})"
        )


# ---------------------------------------------------------------------------
# Fix 7.20a — water source sort is descending (reverse=True)
# ---------------------------------------------------------------------------


class TestFix720aSourceSort:
    def test_sources_sorted_descending(self):
        import inspect

        import veilbreakers_terrain.handlers._water_network as wn

        src = inspect.getsource(wn)
        assert "reverse=True" in src, "sources.sort must use reverse=True (descending)"


# ---------------------------------------------------------------------------
# Fix 7.20b — pass_macro_world generates height for zero-init stack
# ---------------------------------------------------------------------------


class TestFix720bMacroWorld:
    def test_pass_macro_world_generates_height_on_zero_stack(self):
        from veilbreakers_terrain.handlers._terrain_world import pass_macro_world
        from veilbreakers_terrain.handlers.terrain_semantics import (
            BBox,
            TerrainIntentState,
            TerrainMaskStack,
            TerrainPipelineState,
        )

        stack = TerrainMaskStack(
            height=np.zeros((32, 32), dtype=np.float32),
            tile_size=32,
            cell_size=5.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
        )
        region_bounds = BBox(0.0, 0.0, 160.0, 160.0)
        intent = TerrainIntentState(
            seed=99,
            region_bounds=region_bounds,
            tile_size=32,
            cell_size=5.0,
            composition_hints={},
        )
        state = TerrainPipelineState(intent=intent, mask_stack=stack)
        pass_macro_world(state, None)
        h_range = float(stack.height.max()) - float(stack.height.min())
        assert h_range > 1.0, (
            f"pass_macro_world must generate non-flat height for zero-init stack, "
            f"range={h_range:.2f}"
        )


# ---------------------------------------------------------------------------
# Fix 7.12 — _compute_tile_contracts AABB slab intersection
# ---------------------------------------------------------------------------


class TestFix712TileContracts:
    def test_segment_crossing_tile(self):
        from veilbreakers_terrain.handlers.terrain_chunking import _compute_tile_contracts

        # Horizontal line from (0,32) to (128,32) through a 64x64 tile at origin
        ts = _compute_tile_contracts(
            tile_origin=(0.0, 0.0),
            tile_size_m=64.0,
            line_start=(0.0, 32.0),
            line_end=(128.0, 32.0),
        )
        # Starts on left edge (x=0, y=32 is within y=[0,64]), exits at x=64 (t=0.5)
        assert len(ts) >= 1, f"Expected at least 1 crossing, got ts={ts}"

    def test_segment_missing_tile(self):
        from veilbreakers_terrain.handlers.terrain_chunking import _compute_tile_contracts

        # Diagonal segment far from tile at (200,200)
        ts = _compute_tile_contracts(
            tile_origin=(200.0, 200.0),
            tile_size_m=64.0,
            line_start=(0.0, 0.0),
            line_end=(64.0, 64.0),
        )
        assert len(ts) == 0, f"Segment should miss tile, got ts={ts}"
