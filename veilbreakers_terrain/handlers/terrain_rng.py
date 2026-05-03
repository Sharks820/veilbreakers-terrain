"""
terrain_rng.py — deterministic, per-tile, parallel-safe RNG factory.

Follows NumPy 2.4 parallel seeding guidance:
  default_rng([worker_id, root_seed])  — list form, worker ID FIRST.

All terrain code should use make_rng() or tile_rng() instead of
np.random.RandomState, random.Random(), or any other bare/unseeded random
call.  Both functions hash their inputs via SHA-256 so results are stable
across Python runs regardless of PYTHONHASHSEED.

Closes BUG-48, BUG-49, BUG-81, BUG-91, BUG-92, BUG-96.
FIX-10-18: tile_rng promoted to production API; FUTURE USE comments removed.
"""
from __future__ import annotations
import hashlib
import numpy as np
from typing import Union


def make_rng(*keys: Union[int, str, float]) -> np.random.Generator:
    """Create a deterministic Generator seeded from an ordered sequence of keys.

    Usage:
        rng = make_rng(world_origin_x, world_origin_y, root_seed)
        rng = make_rng(tile_id, "pass_name")

    Keys are hashed to uint32 values via SHA-256, then passed as list to
    default_rng — list form is required for safe parallel seeding per NumPy docs.
    """
    seed_ints = []
    for k in keys:
        raw = str(k).encode("utf-8")
        digest = hashlib.sha256(raw).digest()
        seed_ints.append(int.from_bytes(digest[:4], "big"))
    return np.random.default_rng(seed_ints if seed_ints else [0])


def tile_rng(tile_id: str) -> np.random.Generator:
    """Return a deterministic per-tile RNG seeded from *tile_id*.

    ``tile_id`` should be a stable string that uniquely identifies the tile,
    e.g. ``f"{tile_x}_{tile_y}"`` or ``state.tile_id``.  The seed is derived
    via SHA-256 so it is PYTHONHASHSEED-independent and safe for parallel
    workers.

    Usage::

        rng = tile_rng(state.tile_id)
        value = rng.uniform(0.0, 1.0)
        indices = rng.integers(0, len(candidates), size=n)
    """
    raw = tile_id.encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    seed = int.from_bytes(digest[:4], "big") & 0xFFFFFFFF
    return np.random.default_rng(seed)
