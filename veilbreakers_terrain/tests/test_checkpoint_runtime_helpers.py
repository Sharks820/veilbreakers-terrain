"""Direct tests for checkpoint atomic write and JSON serialization helpers."""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np


def _stack():
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    stack = TerrainMaskStack(
        tile_size=3,
        cell_size=2.0,
        world_origin_x=10.0,
        world_origin_y=20.0,
        tile_x=1,
        tile_y=2,
        height=np.arange(9, dtype=np.float32).reshape(3, 3),
    )
    stack.set("slope", np.ones((3, 3), dtype=np.float32), pass_name="test")
    return stack


def test_atomic_npz_write_creates_final_npz_and_sha_sidecar():
    from veilbreakers_terrain.handlers.terrain_checkpoints import _atomic_npz_write

    out_dir = Path("output") / "test_artifacts" / "checkpoint_helpers" / uuid.uuid4().hex
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / "stack.npz"

    digest = _atomic_npz_write(_stack(), final_path)
    leftovers = list(out_dir.glob("*.tmp.npz"))

    assert final_path.exists()
    assert len(digest) == 64
    assert (out_dir / "stack.npz.sha256").read_text(encoding="utf-8").startswith(digest)
    assert leftovers == []
    loaded = np.load(final_path)
    assert np.allclose(loaded["height"], np.arange(9, dtype=np.float32).reshape(3, 3))


def test_checkpoint_serialize_deserialize_round_trips_tagged_values():
    from veilbreakers_terrain.handlers.terrain_checkpoints import (
        _deserialize_value,
        _serialize_value,
    )

    payload = {
        "path": Path("assets") / "height.npy",
        "tags": {"b", "a"},
        "array": np.array([[1, 2], [3, 4]], dtype=np.int16),
        "scalar": np.float32(1.5),
        "nested": [{"locked": frozenset({"north", "east"})}],
    }

    encoded = _serialize_value(payload)
    decoded = _deserialize_value(encoded)

    assert encoded["path"] == str(Path("assets") / "height.npy")
    assert encoded["tags"] == {"__type__": "frozenset", "items": ["a", "b"]}
    assert decoded["tags"] == frozenset({"a", "b"})
    assert decoded["array"].dtype == np.int16
    assert np.array_equal(decoded["array"], payload["array"])
    assert decoded["scalar"] == np.float32(1.5).item()
    assert decoded["nested"][0]["locked"] == frozenset({"north", "east"})
