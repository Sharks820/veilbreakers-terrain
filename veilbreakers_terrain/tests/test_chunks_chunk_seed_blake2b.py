"""Phase B D17-18 regression tests — chunks/chunk_seed.py BLAKE2b API + Bug-A unification.

Pins two contracts:

1. The new ``chunks.chunk_seed`` BLAKE2b primitives are deterministic,
   length-prefix-collision-safe, and produce 32-bit seed integers
   compatible with ``np.random.default_rng`` and ``random.Random``.

2. Bug-A fix: ``terrain_rng.derive_pass_seed`` now re-exports the
   canonical ``terrain_pipeline.derive_pass_seed`` rather than
   defining its own incompatible second implementation. Both module
   paths produce IDENTICAL output for the same arguments, so the
   scatter pass (which imports from terrain_rng) is no longer
   deterministically out-of-sync with the 21+ files that import from
   terrain_pipeline.
"""

from __future__ import annotations

from veilbreakers_terrain.chunks.chunk_seed import (
    chunk_seed,
    chunk_seed_bytes,
    derive_pass_seed_blake2b,
)


# ---------------------------------------------------------------------------
# chunks.chunk_seed BLAKE2b primitives
# ---------------------------------------------------------------------------


def test_chunk_seed_returns_uint32():
    seed = chunk_seed(42, "pass_water_flow_speed", 0, 0)
    assert isinstance(seed, int)
    assert 0 <= seed <= 0xFFFFFFFF


def test_chunk_seed_deterministic_across_calls():
    a = chunk_seed(42, "pass_water_flow_speed", 3, 7)
    b = chunk_seed(42, "pass_water_flow_speed", 3, 7)
    assert a == b


def test_chunk_seed_changes_with_namespace():
    a = chunk_seed(42, "pass_water_flow_speed", 0, 0)
    b = chunk_seed(42, "pass_erosion", 0, 0)
    assert a != b


def test_chunk_seed_changes_with_intent_seed():
    a = chunk_seed(42, "pass_x", 0, 0)
    b = chunk_seed(43, "pass_x", 0, 0)
    assert a != b


def test_chunk_seed_changes_with_tile_coords():
    base = chunk_seed(42, "pass_x", 0, 0)
    shifted_x = chunk_seed(42, "pass_x", 1, 0)
    shifted_y = chunk_seed(42, "pass_x", 0, 1)
    assert base != shifted_x
    assert base != shifted_y
    assert shifted_x != shifted_y


def test_chunk_seed_region_affects_output():
    no_region = chunk_seed(42, "pass_x", 0, 0, region_bounds=None)
    region_a = chunk_seed(42, "pass_x", 0, 0, region_bounds=(0.0, 0.0, 32.0, 32.0))
    region_b = chunk_seed(42, "pass_x", 0, 0, region_bounds=(0.0, 0.0, 64.0, 64.0))
    assert no_region != region_a
    assert region_a != region_b


def test_chunk_seed_extra_salt_separates_outputs():
    a = chunk_seed(42, "ns", 0, 0, extra=b"\x00")
    b = chunk_seed(42, "ns", 0, 0, extra=b"\x01")
    c = chunk_seed(42, "ns", 0, 0, extra=b"")
    assert a != b
    assert a != c
    assert b != c


def test_chunk_seed_length_prefix_defeats_boundary_collision():
    """Length-prefixing must distinguish ('aa', 'b') from ('a', 'ab')."""
    a = chunk_seed(0, "aa", 0, 0)
    b = chunk_seed(0, "a", ord("a"), 0)
    assert a != b


def test_chunk_seed_bytes_returns_full_16_bytes():
    digest = chunk_seed_bytes(42, "ns", 0, 0)
    assert isinstance(digest, bytes)
    assert len(digest) == 16


def test_chunk_seed_bytes_first_4_match_chunk_seed():
    digest = chunk_seed_bytes(42, "ns", 0, 0)
    seed_int = int.from_bytes(digest[:4], "little") & 0xFFFFFFFF
    assert seed_int == chunk_seed(42, "ns", 0, 0)


# ---------------------------------------------------------------------------
# derive_pass_seed_blake2b drop-in
# ---------------------------------------------------------------------------


def test_derive_pass_seed_blake2b_signature_matches_canonical():
    """Public signature must match terrain_pipeline.derive_pass_seed kwargs."""
    import inspect

    sig = inspect.signature(derive_pass_seed_blake2b)
    params = list(sig.parameters.keys())
    assert "intent_seed" in params
    assert "seed_namespace" in params
    assert "tile_x" in params
    assert "tile_y" in params
    assert "region" in params


def test_derive_pass_seed_blake2b_deterministic_with_bbox():
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    region = BBox(0.0, 0.0, 32.0, 32.0)
    a = derive_pass_seed_blake2b(42, "ns", 0, 0, region=region)
    b = derive_pass_seed_blake2b(42, "ns", 0, 0, region=region)
    assert a == b


def test_derive_pass_seed_blake2b_handles_none_region():
    a = derive_pass_seed_blake2b(42, "ns", 0, 0, region=None)
    assert isinstance(a, int)
    assert 0 <= a <= 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Bug-A unification: terrain_rng now delegates to terrain_pipeline
# ---------------------------------------------------------------------------


def test_bug_a_terrain_rng_no_longer_uses_string_concat_hash():
    """terrain_rng.derive_pass_seed must NOT use plain string concat."""
    import inspect

    from veilbreakers_terrain.handlers import terrain_rng

    src = inspect.getsource(terrain_rng.derive_pass_seed)
    assert 'f"{seed}:' not in src, (
        "Bug-A REGRESSION — terrain_rng.derive_pass_seed reintroduced "
        "the plain-string-concat hash payload that diverges from the "
        "canonical terrain_pipeline implementation"
    )
    assert "hashlib.sha256(raw.encode" not in src, (
        "Bug-A REGRESSION — terrain_rng.derive_pass_seed reintroduced "
        "its own SHA-256 hash; must delegate to terrain_pipeline"
    )


def test_bug_a_terrain_rng_and_terrain_pipeline_produce_same_output():
    """Identical args must produce identical seed across both module paths."""
    from veilbreakers_terrain.handlers import terrain_pipeline, terrain_rng
    from veilbreakers_terrain.handlers.terrain_semantics import BBox

    region = BBox(0.0, 0.0, 32.0, 32.0)
    rng_seed = terrain_rng.derive_pass_seed(
        seed=42, pass_name="pass_water_flow_speed", tile_x=3, tile_y=7, region=region,
    )
    pipeline_seed = terrain_pipeline.derive_pass_seed(
        intent_seed=42,
        seed_namespace="pass_water_flow_speed",
        tile_x=3,
        tile_y=7,
        region=region,
    )
    assert rng_seed == pipeline_seed, (
        f"terrain_rng / terrain_pipeline derive_pass_seed produced different "
        f"output: rng={rng_seed}, pipeline={pipeline_seed}. Bug-A reintroduced."
    )


def test_bug_a_scatter_engine_import_path_still_works():
    """_scatter_engine imports derive_pass_seed from terrain_rng — must still resolve."""
    from veilbreakers_terrain.handlers.terrain_rng import derive_pass_seed

    seed = derive_pass_seed(seed=42, pass_name="scatter", tile_x=0, tile_y=0, region="")
    assert isinstance(seed, int)


def test_bug_a_terrain_rng_empty_string_region_does_not_crash():
    """Historical callers passed ``region=""`` (default); must still work."""
    from veilbreakers_terrain.handlers.terrain_rng import derive_pass_seed

    seed = derive_pass_seed(seed=42, pass_name="x", tile_x=0, tile_y=0, region="")
    assert isinstance(seed, int)


# ---------------------------------------------------------------------------
# BLAKE2b output distribution sanity
# ---------------------------------------------------------------------------


def test_blake2b_output_distribution_no_obvious_clumping():
    """Smoke test: 1000 nearby seeds shouldn't collide in 32-bit space.

    Expected collisions for 1000 values in 2^32 space ≈ 0.0001 — vanishingly
    small. Any duplicate in a 1000-sample run signals a hash bug.
    """
    seeds = {chunk_seed(42, "ns", x, 0) for x in range(1000)}
    assert len(seeds) == 1000, (
        f"BLAKE2b chunk_seed produced collisions in 1000-sample run "
        f"({1000 - len(seeds)} duplicates) — hash distribution broken"
    )
