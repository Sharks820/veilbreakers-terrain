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
    # FUTURE USE: intended as the canonical deterministic RNG factory for all
    # scatter, erosion, and noise passes — replaces ad-hoc np.random.RandomState
    # calls across the codebase (tracked under BUG-48/49/81/91/92/96).
    # Currently called from tests only; production passes should migrate to this.
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
    # FUTURE USE: per-tile RNG convenience wrapper for terrain chunking and
    # parallel tile generation — no production callers yet; referenced by tests only.
    """Convenience: make a per-tile RNG from world origin + root seed."""
    return make_rng(int(world_origin_x * 1000), int(world_origin_y * 1000), root_seed)

# Bug-A canonical fix (Phase B D17-18): the second `derive_pass_seed`
# definition formerly here used plain string concatenation
# (collision-prone) and produced DIFFERENT seeds than the canonical
# JSON-encoded SHA-256 implementation in `terrain_pipeline.py`. The
# scatter pass imported from this module while 21+ other files imported
# from terrain_pipeline — scatter was deterministically out-of-sync
# with everything else. The wrapper below resolves the canonical
# function on first call and caches the lookup. Direct re-export
# `from terrain_pipeline import derive_pass_seed` would create a
# circular import, so the lookup is deferred via a function call.
from typing import Any as _Any, Optional as _Optional


def _resolve_canonical_derive_pass_seed():  # pragma: no cover - trivial dispatch
    """Lazy lookup of the canonical derive_pass_seed in terrain_pipeline.

    Defined as a module-level function so the import is deferred past
    module-load circular-import risk and so cached on first call.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        derive_pass_seed as _canonical,
    )
    return _canonical


_CANONICAL_DERIVE_PASS_SEED: _Optional[_Any] = None


def derive_pass_seed(
    seed: int,
    pass_name: str,
    tile_x: float = 0.0,
    tile_y: float = 0.0,
    region: _Any = "",
) -> int:
    """Re-export of the canonical ``terrain_pipeline.derive_pass_seed``.

    Bug-A fix: this module previously defined a *second*
    ``derive_pass_seed`` with INCOMPATIBLE hash payload (plain string
    concat vs. JSON-encoded). All importers now share a single
    canonical hash via this thin wrapper.

    Public signature is preserved (positional/keyword args identical to
    the historical terrain_rng definition) so existing callers do not
    need to change. ``region`` is forwarded as-is — terrain_pipeline's
    canonical helper accepts ``Optional[BBox]``; passing a plain string
    (the historical default) is coerced to ``None`` so empty-string
    callers do not crash on ``.to_tuple()`` access.
    """
    global _CANONICAL_DERIVE_PASS_SEED
    if _CANONICAL_DERIVE_PASS_SEED is None:
        _CANONICAL_DERIVE_PASS_SEED = _resolve_canonical_derive_pass_seed()
    canonical_region: _Any = region
    if isinstance(region, str):
        # Historical str regions were never meaningful; treat as None
        # to avoid the canonical helper trying to call .to_tuple().
        canonical_region = None
    return int(
        _CANONICAL_DERIVE_PASS_SEED(
            int(seed),
            str(pass_name),
            int(tile_x),
            int(tile_y),
            canonical_region,
        )
    )
