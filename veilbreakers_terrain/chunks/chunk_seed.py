"""BLAKE2b-based deterministic chunk-seed primitives.

Provides a NEW alternative-pathway BLAKE2b chunk-seed API alongside
the existing SHA-256 ``terrain_pipeline.derive_pass_seed``. This
module does NOT replace the SHA-256 helpers in this PR — both still
exist; future PRs may opt-in migrate consumers via
``derive_pass_seed_blake2b`` (the drop-in replacement signature).

BLAKE2b is ~1.23×-1.5× faster than SHA-256 in CPython 3.12 on small
(<32-byte) inputs, fully deterministic, no PYTHONHASHSEED randomization,
and provides cryptographic-quality avalanche.

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
  ``terrain_pipeline.derive_pass_seed`` so future callers can opt-in
  migrate to BLAKE2b by changing the import line only.

Bug-A canonical fix
-------------------
``terrain_rng.py`` previously defined a SECOND ``derive_pass_seed``
that used plain string concatenation (collision-prone) instead of the
``terrain_pipeline.py`` JSON-encoded SHA-256 path. This PR also
deletes the duplicate body and re-exports the canonical helper via
a thin lazy-loading wrapper in ``terrain_rng.py``. All 22+ importers
now converge on a shared SHA-256 hash payload (terrain_pipeline.py
remains the canonical surface; this BLAKE2b module is opt-in).
"""

from __future__ import annotations

import hashlib
import struct
from typing import Any, Optional, Tuple


# Maximum 32-bit unsigned value for masking BLAKE2b output to numpy
# RNG-compatible seed range.
_U32_MASK: int = 0xFFFFFFFF


def _frame_namespace(namespace: str) -> bytes:
    """Length-prefix a UTF-8 namespace string to defeat boundary collisions.

    Hardening PR B Fix #8 (VC finding): the ``<I`` (uint32) length-prefix
    silently truncates if ``len(encoded)`` exceeds 4 GiB.  Real callers
    pass <100-byte namespaces, but a defensive assertion catches a
    pathological caller before they produce a colliding hash.
    """
    encoded = str(namespace).encode("utf-8")
    assert len(encoded) < (1 << 32), (
        f"namespace too long: {len(encoded)} bytes exceeds uint32 length-prefix "
        "(2**32-1 == 4 GiB).  This would silently truncate the framing length "
        "and break collision-resistance."
    )
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
    # Pack intent_seed as UNSIGNED 32-bit (`<I`) to accept the full
    # uint32 range that callers may legitimately pass. Signed `<i`
    # would raise struct.error on values >= 2**31. Mask negative
    # input via & 0xFFFFFFFF so signed-int callers (e.g. -1 used as
    # sentinel) still pack cleanly.
    extra_bytes = bytes(extra)
    # Hardening PR B Fix #8 (VC finding): mirror the namespace check —
    # silent uint32 truncation of ``len(extra)`` would break collision-
    # resistance.  Real callers pass <16-byte salt but this catches a
    # pathological caller before the hash silently aliases.
    assert len(extra_bytes) < (1 << 32), (
        f"extra salt too long: {len(extra_bytes)} bytes exceeds uint32 "
        "length-prefix (2**32-1 == 4 GiB)."
    )
    payload = (
        struct.pack("<I", int(intent_seed) & 0xFFFFFFFF)
        + _frame_namespace(namespace)
        + struct.pack("<qq", int(tile_x), int(tile_y))
        + _frame_region(region_bounds)
        + struct.pack("<I", len(extra_bytes))
        + extra_bytes
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
    region: "Any" = None,
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
