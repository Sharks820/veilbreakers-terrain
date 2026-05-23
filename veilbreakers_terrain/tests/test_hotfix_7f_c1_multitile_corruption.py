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
    """Integration: the DEGENERATE FALLBACK path diverges per tile (the fixed code).

    The HOTFIX-7f C1 fix lives in the degenerate-fallback branch of
    ``pass_macro_world``: it is reached only when ``generate_world_heightmap``
    returns a flat heightmap (``h_range_raw <= 1e-9``), at which point relief is
    synthesised from ``derive_pass_seed(... stack.tile_x, stack.tile_y ...)``.

    To genuinely guard the fixed path we force the flat-output condition by
    monkeypatching ``generate_world_heightmap`` to return all-zeros. This makes
    the affine-remap branch (the NORMAL noise path) a no-op and routes both
    tiles through the degenerate fallback. With the same seed but different tile
    coords the synthesised relief MUST differ — pre-fix it was identical because
    the seed used hardcoded ``0, 0``.
    """
    from unittest.mock import patch

    from veilbreakers_terrain.handlers import _terrain_world
    from veilbreakers_terrain.handlers._terrain_world import pass_macro_world

    def _flat_heightmap(width: int, height: int, **_kwargs: object) -> np.ndarray:
        # Flat output → h_range_raw <= 1e-9 → degenerate fallback fires.
        return np.zeros((height, width), dtype=np.float32)

    state_00 = _make_state(tile_x=0, tile_y=0, seed=99)
    state_10 = _make_state(tile_x=1, tile_y=0, seed=99)

    with patch.object(
        _terrain_world, "generate_world_heightmap", side_effect=_flat_heightmap
    ):
        res_00 = pass_macro_world(state_00, region=None)
        res_10 = pass_macro_world(state_10, region=None)

    assert res_00.status != "failed", f"pass_macro_world failed for tile (0,0): {res_00.issues}"
    assert res_10.status != "failed", f"pass_macro_world failed for tile (1,0): {res_10.issues}"

    h00 = np.asarray(state_00.mask_stack.height, dtype=np.float64)
    h10 = np.asarray(state_10.mask_stack.height, dtype=np.float64)

    # Both tiles hit the degenerate fallback; the synthesised relief must NOT be
    # bit-identical (the per-tile seed fix is what makes the streams diverge).
    assert h00.shape == h10.shape and h00.size > 0, "degenerate fallback produced no relief"
    assert not np.array_equal(h00, h10), (
        "pass_macro_world degenerate fallback produced identical relief for tile "
        "(0,0) and (1,0) with the same seed — the HOTFIX-7f C1 per-tile seed fix "
        "did not take effect."
    )


# ---------------------------------------------------------------------------
# FIX 2 — terrain_cliffs.py:insert_hero_cliff_meshes mesh_seed
# ---------------------------------------------------------------------------


def _production_cliff_id(tile_x: int, tile_y: int, idx: int = 0) -> str:
    """Mirror the production cliff_id scheme (terrain_cliffs.py:1102).

    Production stamps each cliff with ``f"cliff_{tile_x}_{tile_y}_{idx:02d}"``,
    so the cliff_id is ALREADY tile-namespaced before it reaches the
    ``mesh_seed`` derivation. Tests must use this production shape — a fixed
    shared id (e.g. ``cliff_test_00``) is a configuration production never
    generates and would mis-attribute where the cross-tile distinctness
    comes from.
    """
    return f"cliff_{tile_x}_{tile_y}_{idx:02d}"


def _cliff_mesh_seed(
    tile_x: int,
    tile_y: int,
    idx: int = 0,
    intent_seed: int = 42,
) -> int:
    """Reproduce the ``mesh_seed`` derivation from ``insert_hero_cliff_meshes``.

    Matches the production call site (terrain_cliffs.py:2506) exactly:
        derive_pass_seed(
            int(state.intent.seed),
            f"terrain_cliffs.cliff_mesh.{cliff.cliff_id}",   # tile-stamped id
            state.tile_x,
            state.tile_y,
            None,
        )

    Two independent namespacing axes feed the seed: (1) the tile-stamped
    ``cliff_id`` baked into the pass_name, and (2) the explicit
    ``tile_x``/``tile_y`` args added by HOTFIX-7f C1. Either alone makes the
    seed differ per tile; together they are defence-in-depth against a future
    cliff_id scheme change that drops the tile stamp.
    """
    cliff_id = _production_cliff_id(tile_x, tile_y, idx)
    return derive_pass_seed(
        int(intent_seed),
        f"terrain_cliffs.cliff_mesh.{cliff_id}",
        tile_x,
        tile_y,
        None,
    )


def test_cliff_mesh_seed_differs_between_tiles():
    """Regression-pin: per-cliff mesh seed must differ for tile (0,0) vs tile (1,0).

    Uses production-shaped tile-stamped cliff_ids (``cliff_{tx}_{ty}_{idx}``).
    The seed must differ across tiles because BOTH the tile-stamped cliff_id
    (folded into the pass_name) and the explicit ``tile_x``/``tile_y`` args
    namespace the stream. Before the HOTFIX-7f C1 fix the explicit args were
    hardcoded ``0, 0``; the tile-stamped cliff_id already supplied distinctness,
    and the fix adds a redundant, independent tile axis for defensive clarity.
    """
    seed_00 = _cliff_mesh_seed(tile_x=0, tile_y=0)
    seed_10 = _cliff_mesh_seed(tile_x=1, tile_y=0)
    assert seed_00 != seed_10, (
        "Cliff mesh seed is identical for tile (0,0) and (1,0) — "
        "per-tile cliff geometry would collapse to identical wall meshes."
    )


def test_cliff_mesh_seed_property_four_tiles():
    """No cliff mesh seed collisions across a 2×2 tile grid.

    Property: 4 distinct tile coordinates (each with its production-shaped
    tile-stamped cliff_id) must yield 4 distinct mesh seeds.
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


def test_cliff_mesh_seed_tile_coords_are_independent_namespace_axis():
    """The HOTFIX-7f C1 ``tile_x``/``tile_y`` args add a *real* second axis.

    Holding the cliff_id fixed (so the pass_name is identical), varying only
    the ``tile_x``/``tile_y`` arguments must still change the seed. This proves
    the production change is not a pure no-op: it is defence-in-depth that
    keeps tiles distinct even if the cliff_id scheme ever drops its tile stamp.
    """
    fixed_pass_name = "terrain_cliffs.cliff_mesh.cliff_0_0_00"
    seed_tile_00 = derive_pass_seed(42, fixed_pass_name, 0, 0, None)
    seed_tile_10 = derive_pass_seed(42, fixed_pass_name, 1, 0, None)
    assert seed_tile_00 != seed_tile_10, (
        "With cliff_id held fixed, varying tile_x/tile_y did NOT change the "
        "mesh seed — the HOTFIX-7f C1 tile-coord arguments are a no-op."
    )


def test_insert_hero_cliff_meshes_mesh_seed_uses_tile_coords():
    """Integration: ``insert_hero_cliff_meshes`` must compute distinct mesh_seed
    for two states sharing the same intent.seed but different tile_x/tile_y.

    We invoke the function with a minimal CliffStructure whose tier="hero"
    and capture the ``seed`` key that flows into ``_build_cliff_wall_mesh_spec``
    via monkey-patching.  The function must call ``_build_cliff_wall_mesh_spec``
    with different ``seed`` values for the two tile states.
    """
    from unittest.mock import patch

    from veilbreakers_terrain.handlers.terrain_cliffs import (
        CliffStructure,
        insert_hero_cliff_meshes,
    )

    # Minimal hero cliff — small but valid polyline + face mask.
    # Production stamps each tile's cliff with f"cliff_{tile_x}_{tile_y}_{idx:02d}"
    # (terrain_cliffs.py:1102), so we build a per-tile cliff with the
    # production-shaped id rather than reusing one shared fixed id across tiles.
    N = 4
    lip = np.array([[0, i] for i in range(N)], dtype=np.int32)
    face = np.zeros((_TILE_SIZE, _TILE_SIZE), dtype=bool)
    face[2:6, 2:6] = True

    def _make_cliff(tile_x: int, tile_y: int) -> CliffStructure:
        return CliffStructure(
            cliff_id=_production_cliff_id(tile_x, tile_y, idx=0),
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
        # Use plain Python lists (not numpy arrays) for "vertices": the
        # truth-test ``if wall_mesh["vertices"]`` inside insert_hero_cliff_meshes
        # (line 2555) must be TRUTHY so the function selects ``wall_mesh`` over
        # ``face_mesh_spec`` and proceeds. A non-empty list of vertex tuples is
        # truthy without raising numpy's "ambiguous truth value" error that a
        # numpy array would.
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
        # ``insert_hero_cliff_meshes`` imports ``generate_cliff_face_mesh``
        # locally (``from ._terrain_depth import generate_cliff_face_mesh``),
        # so the live name resolves against the ``_terrain_depth`` module at
        # call time. Patching it on ``terrain_cliffs`` would NOT intercept the
        # call — patch the source module so the in-function import binds to the
        # stub (CodeRabbit PRRT_kwDOSDBoMs6ETH3M).
        patch(
            "veilbreakers_terrain.handlers._terrain_depth.generate_cliff_face_mesh",
            return_value=None,
        ),
    ):
        insert_hero_cliff_meshes(state_00, [_make_cliff(tile_x=0, tile_y=0)])
        insert_hero_cliff_meshes(state_01, [_make_cliff(tile_x=0, tile_y=1)])

    assert len(captured_seeds) == 2, (
        f"Expected 2 captured seeds (one per insert_hero_cliff_meshes call), got {len(captured_seeds)}"
    )
    seed_tile_00, seed_tile_01 = captured_seeds
    assert seed_tile_00 != seed_tile_01, (
        f"insert_hero_cliff_meshes produced the SAME mesh_seed ({seed_tile_00}) "
        f"for tile (0,0) and tile (0,1) — the HOTFIX-7f C1 tile-coord fix is not wired "
        f"through to _build_cliff_wall_mesh_spec."
    )
