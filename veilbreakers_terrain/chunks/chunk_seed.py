"""BLAKE2b-based deterministic chunk-seed primitives.

Replaces SHA-256 in `terrain_pipeline.derive_pass_seed` and
`terrain_rng.derive_pass_seed` for chunk-level work where the
input space is small (intent-seed + namespace + tile coords + region
bbox). BLAKE2b is ~1.23×-1.5× faster than SHA-256 in CPython 3.12 on
small (<32-byte) inputs, fully deterministic, no PYTHONHASHSEED
randomization, and provides cryptographic-quality avalanche.

Length-prefixed framing
-----------------------
The hash input is constructed by length-prefixing each component so that
collisions across different field boundaries are impossible:

    BLAKE2b(
        u32(intent_seed) ||
        u32(len(namespace)) || namespace_bytes ||
        i64(tile_x) || i64(tile_y) ||
        u8(has_region) || (i64×4 region_bounds if has_region) ||
        u32(extra_len) || extra_bytes (optional caller-supplied salt)
    )

Without length prefixing, ``("aa", "b")`` and ``("a", "ab")`` would
hash to the same digest. Per the project truth-table memory:
"Length-prefixed framing is canonical pattern."

Output formats
--------------
- ``chunk_seed(...)`` returns a 32-bit unsigned int — drop-in for
  ``np.random.default_rng(seed)`` or ``random.Random(seed)``.
- ``chunk_seed_bytes(...)`` returns the full 16-byte BLAKE2b digest
  for callers that need >32 bits of entropy (e.g. SeedSequence).
- ``derive_pass_seed_blake2b(...)`` matches the public signature of
  ``terrain_pipeline.derive_pass_seed`` so callers can swap the import
  without renaming kwargs.

Bug-A canonical fix
-------------------
``terrain_rng.py`` previously defined a SECOND `derive_pass_seed` that
used plain string concatenation (collision-prone) instead of the
``terrain_pipeline.py`` JSON-encoded SHA-256 path. This module is the
canonical single-source replacement; both old definitions delegate to
it (or re-export from it) so all 22 importers converge on a shared
hash payload.
"""

from __future__ import annotations

import hashlib
import struct
from typing import Optional, Tuple


# Maximum 32-bit unsigned value for masking BLAKE2b output to numpy
# RNG-compatible seed range.
_U32_MASK: int = 0xFFFFFFFF


def _frame_namespace(namespace: str) -> bytes:
    """Length-prefix a UTF-8 namespace string to defeat boundary collisions."""
    encoded = str(namespace).encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def _frame_region(region_bounds: Optional[Tuple[float, float, float, float]]) -> bytes:
    """Length-prefix the region bbox with a presence byte.

    Region is the 4-tuple (x0, y0, x1, y1) in world metres. We pack
    each component as a signed 64-bit fixed-point integer (× 1e6 to
    preserve sub-millimetre resolution while staying integer).
    Floats would introduce platform-dependent IEEE-754 rounding into
    the hash; integers do not.
    """
    if region_bounds is None:
        return b"\x00"  # presence byte = 0
    x0, y0, x1, y1 = region_bounds
    # Fixed-point ×1e6 fits ±9.2e12 metres — far beyond any tile grid.
    return (
        b"\x01"
        + struct.pack(
            "<qqqq",
            int(round(x0 * 1_000_000)),
            int(round(y0 * 1_000_000)),
            int(round(x1 * 1_000_000)),
            int(round(y1 * 1_000_000)),
        )
    )


def chunk_seed_bytes(
    intent_seed: int,
    namespace: str,
    tile_x: int,
    tile_y: int,
    region_bounds: Optional[Tuple[float, float, float, float]] = None,
    extra: bytes = b"",
) -> bytes:
    """Compute the raw 16-byte BLAKE2b digest for a chunk-level seed.

    Returns the full 16-byte digest so callers needing >32 bits (e.g.
    `numpy.random.SeedSequence`) can splice it themselves. Most callers
    want :func:`chunk_seed` which masks to 32 bits.
    """
    payload = (
        struct.pack("<i", int(intent_seed))
        + _frame_namespace(namespace)
        + struct.pack("<qq", int(tile_x), int(tile_y))
        + _frame_region(region_bounds)
        + struct.pack("<I", len(extra))
        + bytes(extra)
    )
    return hashlib.blake2b(payload, digest_size=16).digest()


def chunk_seed(
    intent_seed: int,
    namespace: str,
    tile_x: int,
    tile_y: int,
    region_bounds: Optional[Tuple[float, float, float, float]] = None,
    extra: bytes = b"",
) -> int:
    """Canonical 32-bit deterministic chunk seed (BLAKE2b).

    Args:
        intent_seed: Root world seed from ``TerrainIntentState.seed``.
        namespace: Pass / scatter / RNG-site identifier
            (e.g. ``"pass_water_flow_speed"``, ``"foliage_catalog.scatter"``).
        tile_x, tile_y: Integer tile coordinates.
        region_bounds: Optional 4-tuple ``(x0, y0, x1, y1)`` in world metres
            for region-aware passes; ``None`` for whole-tile work.
        extra: Optional caller-supplied salt bytes for RNG-site separation
            within a single namespace (e.g. droplet index).

    Returns:
        ``int`` in ``[0, 2**32)`` suitable for
        ``np.random.default_rng(seed)`` or ``random.Random(seed)``.
    """
    digest = chunk_seed_bytes(
        intent_seed, namespace, tile_x, tile_y, region_bounds, extra
    )
    return int.from_bytes(digest[:4], "little") & _U32_MASK


def derive_pass_seed_blake2b(
    intent_seed: int,
    seed_namespace: str,
    tile_x: int,
    tile_y: int,
    region: Optional[object] = None,
) -> int:
    """Drop-in replacement for ``terrain_pipeline.derive_pass_seed``.

    Public signature matches the existing SHA-256 helper exactly so
    callers can swap the import without renaming kwargs. Internally
    delegates to :func:`chunk_seed`.

    The ``region`` parameter accepts either:
        - ``None``
        - a ``BBox`` instance with a ``to_tuple()`` method
        - a 4-tuple ``(x0, y0, x1, y1)`` directly

    BLAKE2b output differs from the SHA-256 helper byte-for-byte. Tests
    that pin specific seed integers must update when migrating.
    """
    region_bounds: Optional[Tuple[float, float, float, float]] = None
    if region is not None:
        to_tuple = getattr(region, "to_tuple", None)
        if to_tuple is not None:
            tup = to_tuple()
        else:
            tup = region
        region_bounds = (
            float(tup[0]),
            float(tup[1]),
            float(tup[2]),
            float(tup[3]),
        )
    return chunk_seed(
        int(intent_seed),
        str(seed_namespace),
        int(tile_x),
        int(tile_y),
        region_bounds,
    )
