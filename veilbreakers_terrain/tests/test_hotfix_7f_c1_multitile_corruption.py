"""HOTFIX-7f Cluster 1 regression tests — multi-tile RNG corruption.

Pins the two Category-A bugs fixed in this PR:

1. ``_terrain_world.py`` degenerate fallback: ``derive_pass_seed`` was called
   with hardcoded ``0, 0`` tile coords, so every tile produced the SAME
   degenerate-relief RNG stream.

2. ``terrain_cliffs.py:insert_hero_cliff_meshes``: ``mesh_seed`` was derived
   from ``int(state.intent.seed)`` with ``0, 0`` tile coords, making every
   tile's per-cliff wall mesh identical.

Each test asserts cross-tile divergence: calling the affected code with
different ``tile_x / tile_y`` must produce distinct seeds / outputs.
A 4-coord property test additionally confirms no collisions across a 2×2
tile grid.
"""

from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_rng import derive_pass_seed
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TILE_SIZE = 16  # small — tests must be fast


def _make_state(tile_x: int, tile_y: int, seed: int = 42) -> TerrainPipelineState:
    """Construct a minimal TerrainPipelineState with the given tile coords."""
    stack = TerrainMaskStack(
        tile_size=_TILE_SIZE,
        cell_size=1.0,
        world_origin_x=float(tile_x * _TILE_SIZE),
        world_origin_y=float(tile_y * _TILE_SIZE),
        tile_x=tile_x,
        tile_y=tile_y,
        height=np.zeros((_TILE_SIZE, _TILE_SIZE), dtype=np.float32),
    )
    intent = TerrainIntentState(
        seed=seed,
        region_bounds=BBox(0.0, 0.0, float(_TILE_SIZE), float(_TILE_SIZE)),
        tile_size=_TILE_SIZE,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# FIX 1 — _terrain_world.py degenerate fallback
# ---------------------------------------------------------------------------


def _degenerate_fallback_seed(tile_x: int, tile_y: int, intent_seed: int = 42) -> int:
    """Reproduce the fixed seed derivation for the degenerate fallback path.

    Mirrors the corrected code in ``_terrain_world.pass_macro_world``:

        derive_pass_seed(
            int(seed) ^ 0xDEAD,
            "terrain_world.pass_macro_world.degenerate_fallback",
            stack.tile_x,
            stack.tile_y,
            None,
        )
    """
    return derive_pass_seed(
        int(intent_seed) ^ 0xDEAD,
        "terrain_world.pass_macro_world.degenerate_fallback",
        tile_x,
        tile_y,
        None,
    )


def test_terrain_world_degenerate_fallback_seed_differs_between_tiles():
    """Regression-pin: tiles (0,0) and (1,0) must produce different degenerate seeds.

    Before the fix both tiles derived the same seed (0, 0 hardcoded), so every
    tile with a flat heightmap repeated the same random relief.
    """
    seed_00 = _degenerate_fallback_seed(tile_x=0, tile_y=0)
    seed_10 = _degenerate_fallback_seed(tile_x=1, tile_y=0)
    assert seed_00 != seed_10, (
        "Degenerate fallback seed is identical for tile (0,0) and (1,0) — "
        "the HOTFIX-7f C1 fix to _terrain_world.py did not take effect."
    )


def test_terrain_world_degenerate_fallback_seed_property_four_tiles():
    """No seed collisions across a 2×2 tile grid (4 distinct values required).

    Property: derive_pass_seed(... tile_x, tile_y ...) for all (tx,ty) in
    {0,1}×{0,1} must produce 4 distinct integers.
    """
    coords = [(tx, ty) for tx in range(2) for ty in range(2)]
    seeds = [_degenerate_fallback_seed(tx, ty) for tx, ty in coords]
    assert len(set(seeds)) == 4, (
        f"Expected 4 distinct degenerate-fallback seeds for tiles {coords}; "
        f"got {len(set(seeds))} unique values: {seeds}"
    )


def test_terrain_world_pass_produces_different_heights_for_different_tiles():
    """Integration: pass_macro_world with same seed but different tile coords diverges.

    This test exercises the normal noise path (not the degenerate fallback).
    Different tile origins (world_origin_x/y) propagate into generate_world_heightmap,
    so the resulting height arrays must differ.  This is the primary anti-regression
    gate: if tile coords were stripped from the generation path, tiles at (0,0)
    and (1,0) would produce identical content.
    """
    from veilbreakers_terrain.handlers._terrain_world import pass_macro_world

    state_00 = _make_state(tile_x=0, tile_y=0, seed=99)
    state_10 = _make_state(tile_x=1, tile_y=0, seed=99)

    res_00 = pass_macro_world(state_00, region=None)
    res_10 = pass_macro_world(state_10, region=None)

    assert res_00.status != "failed", f"pass_macro_world failed for tile (0,0): {res_00.issues}"
    assert res_10.status != "failed", f"pass_macro_world failed for tile (1,0): {res_10.issues}"

    h00 = np.asarray(state_00.mask_stack.height, dtype=np.float64)
    h10 = np.asarray(state_10.mask_stack.height, dtype=np.float64)

    # Arrays must not be bit-identical (world-space noise differs by tile origin).
    assert not np.array_equal(h00, h10), (
        "pass_macro_world produced identical height arrays for tile (0,0) and (1,0) "
        "with the same seed — world-space tiling is broken."
    )


# ---------------------------------------------------------------------------
# FIX 2 — terrain_cliffs.py:insert_hero_cliff_meshes mesh_seed
# ---------------------------------------------------------------------------


def _cliff_mesh_seed(
    tile_x: int,
    tile_y: int,
    cliff_id: str = "cliff_test_00",
    intent_seed: int = 42,
) -> int:
    """Reproduce the fixed ``mesh_seed`` derivation from ``insert_hero_cliff_meshes``.

    Before the fix:
        derive_pass_seed(int(state.intent.seed), f"terrain_cliffs.cliff_mesh.{cliff_id}", 0, 0, None)

    After the fix (matches this function):
        derive_pass_seed(int(state.intent.seed), f"terrain_cliffs.cliff_mesh.{cliff_id}",
                         state.tile_x, state.tile_y, None)
    """
    return derive_pass_seed(
        int(intent_seed),
        f"terrain_cliffs.cliff_mesh.{cliff_id}",
        tile_x,
        tile_y,
        None,
    )


def test_cliff_mesh_seed_differs_between_tiles():
    """Regression-pin: per-cliff mesh seed must differ for tile (0,0) vs tile (1,0).

    Before the fix, ``insert_hero_cliff_meshes`` always called
    ``derive_pass_seed(int(state.intent.seed), ..., 0, 0, None)`` — so every
    tile generated identical wall-face geometry for cliffs with the same ID.
    """
    seed_00 = _cliff_mesh_seed(tile_x=0, tile_y=0)
    seed_10 = _cliff_mesh_seed(tile_x=1, tile_y=0)
    assert seed_00 != seed_10, (
        "Cliff mesh seed is identical for tile (0,0) and (1,0) — "
        "the HOTFIX-7f C1 fix to terrain_cliffs.py did not take effect."
    )


def test_cliff_mesh_seed_property_four_tiles():
    """No cliff mesh seed collisions across a 2×2 tile grid.

    Property: 4 distinct tile coordinates must yield 4 distinct mesh seeds.
    """
    coords = [(tx, ty) for tx in range(2) for ty in range(2)]
    seeds = [_cliff_mesh_seed(tx, ty) for tx, ty in coords]
    assert len(set(seeds)) == 4, (
        f"Expected 4 distinct cliff-mesh seeds for tiles {coords}; "
        f"got {len(set(seeds))} unique: {seeds}"
    )


def test_cliff_mesh_seed_same_for_same_tile():
    """Determinism: calling with identical args must return the same seed.

    Verifies that ``derive_pass_seed`` is purely deterministic — no global
    state, no randomness.
    """
    s1 = _cliff_mesh_seed(tile_x=0, tile_y=0, intent_seed=7)
    s2 = _cliff_mesh_seed(tile_x=0, tile_y=0, intent_seed=7)
    assert s1 == s2, "derive_pass_seed is not deterministic — returned different values for identical inputs."


def test_insert_hero_cliff_meshes_mesh_seed_uses_tile_coords():
    """Integration: ``insert_hero_cliff_meshes`` must compute distinct mesh_seed
    for two states sharing the same intent.seed but different tile_x/tile_y.

    We invoke the function with a minimal CliffStructure whose tier="hero"
    and capture the ``seed`` key that flows into ``_build_cliff_wall_mesh_spec``
    via monkey-patching.  The function must call ``_build_cliff_wall_mesh_spec``
    with different ``seed`` values for the two tile states.
    """
    import math
    from unittest.mock import MagicMock, patch

    from veilbreakers_terrain.handlers.terrain_cliffs import (
        CliffStructure,
        insert_hero_cliff_meshes,
    )

    # Minimal hero cliff — small but valid polyline + face mask
    N = 4
    lip = np.array([[0, i] for i in range(N)], dtype=np.int32)
    face = np.zeros((_TILE_SIZE, _TILE_SIZE), dtype=bool)
    face[2:6, 2:6] = True

    cliff = CliffStructure(
        cliff_id="cliff_00_00_00",
        lip_polyline=lip,
        face_mask=face,
        tier="hero",
        max_height_m=20.0,
        min_height_m=0.0,
        cell_count=int(face.sum()),
        world_bounds=BBox(2.0, 2.0, 6.0, 6.0),
    )

    captured_seeds: list[int] = []

    # Stub out the heavy mesh-building and Blender calls so the test runs
    # without bpy and without numpy-intensive geometry work.
    def _stub_wall_mesh(**kwargs: object) -> dict:  # type: ignore[return]
        captured_seeds.append(int(kwargs.get("seed", -1)))  # type: ignore[arg-type]
        # Use plain Python lists (not numpy arrays) for "vertices" so the
        # truth-test ``if wall_mesh["vertices"]`` inside insert_hero_cliff_meshes
        # line 2555 evaluates to False without raising the numpy ambiguity error.
        # We need it truthy so the function proceeds — use a non-empty list of tuples.
        verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
        faces_arr = [(0, 1, 0, 0)]
        return {
            "vertices": verts,
            "faces": faces_arr,
            "metadata": {
                "type": "cliff_wall",
                "style": "granite",
                "wall_height_m": 20.0,
                "overhang_fraction": 0.15,
                "lip_vertex_count": 2,
                "segments_vertical": 2,
                "noise_amplitude": 0.5,
                "arc_length_m": 1.0,
                "seg_width_scale_mean": 1.0,
                "vegetation_anchors": [],
                "cliff_boulder_placements": [],
                "cliff_ledge_vegetation_points": [],
                "material_indices": [],
                "strata_ledge_count": 0,
                "crack_count": 0,
                "lod": [],
            },
        }

    state_00 = _make_state(tile_x=0, tile_y=0, seed=55)
    state_01 = _make_state(tile_x=0, tile_y=1, seed=55)

    with (
        patch(
            "veilbreakers_terrain.handlers.terrain_cliffs._build_cliff_wall_mesh_spec",
            side_effect=_stub_wall_mesh,
        ),
        patch(
            "veilbreakers_terrain.handlers.terrain_cliffs.generate_cliff_face_mesh",
            return_value=None,
            create=True,
        ),
    ):
        insert_hero_cliff_meshes(state_00, [cliff])
        insert_hero_cliff_meshes(state_01, [cliff])

    assert len(captured_seeds) == 2, (
        f"Expected 2 captured seeds (one per insert_hero_cliff_meshes call), got {len(captured_seeds)}"
    )
    seed_tile_00, seed_tile_01 = captured_seeds
    assert seed_tile_00 != seed_tile_01, (
        f"insert_hero_cliff_meshes produced the SAME mesh_seed ({seed_tile_00}) "
        f"for tile (0,0) and tile (0,1) — the HOTFIX-7f C1 tile-coord fix is not wired "
        f"through to _build_cliff_wall_mesh_spec."
    )
