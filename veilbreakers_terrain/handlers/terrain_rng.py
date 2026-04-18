"""
terrain_rng.py — deterministic, per-tile, parallel-safe RNG factory.

Follows NumPy 2.4 parallel seeding guidance:
  default_rng([worker_id, root_seed])  — list form, worker ID FIRST.

All terrain code should use make_rng() instead of np.random.RandomState
or random.Random with hash()-based seeds.

Closes BUG-48, BUG-49, BUG-81, BUG-91, BUG-92, BUG-96.
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

def tile_rng(world_origin_x: float, world_origin_y: float,
             root_seed: int = 42) -> np.random.Generator:
    """Convenience: make a per-tile RNG from world origin + root seed."""
    return make_rng(int(world_origin_x * 1000), int(world_origin_y * 1000), root_seed)
