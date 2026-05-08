"""Chunk-level deterministic primitives.

This package houses pure-logic helpers for chunk seeding, ID generation,
and other small utilities that are referenced from many handler modules
but don't belong in any single handler. Adding helpers here keeps
``handlers/`` focused on terrain-domain logic.

Public API surface:

    from veilbreakers_terrain.chunks.chunk_seed import (
        chunk_seed,                # canonical 32-bit chunk seed (BLAKE2b)
        chunk_seed_bytes,          # raw 16-byte digest for higher-bit seeds
        derive_pass_seed_blake2b,  # drop-in replacement for SHA-256 derive_pass_seed
    )

The ``derive_pass_seed_blake2b`` helper has the SAME public signature as
``terrain_pipeline.derive_pass_seed`` so callers can migrate one site at
a time without renaming kwargs.
"""

from veilbreakers_terrain.chunks.chunk_seed import (
    chunk_seed,
    chunk_seed_bytes,
    derive_pass_seed_blake2b,
)

__all__ = [
    "chunk_seed",
    "chunk_seed_bytes",
    "derive_pass_seed_blake2b",
]
