"""Tests for the terrain_caves.handle_generate_cave MCP adapter (phase 49 C2).

The adapter wraps ``terrain_caves.pass_caves`` so ``compose_map``'s
``_LOC_HANDLERS["cave"]`` can dispatch to a terrain-side handler instead of
the doomed ``world_generate_cave`` (BSP-based ``_dungeon_gen``).

These tests exercise contract behavior only — no Blender, no bpy. The
adapter MUST be importable and callable without a Blender process.

Phase: 49-architecture-domain-removal-delete-all-architecture-handlers
Plan:  49-01 Task 3 (commit C2)
Decision refs: D-13 (rewire), D-14 (adapter)
"""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# bpy stub — terrain_caves itself is pure numpy, but the adapter creates a
# Blender mesh chamber (since callers _position_generated_object the result).
# Provide a minimal bpy stub so the adapter import + mesh creation work in
# pytest without a live Blender process.
# ---------------------------------------------------------------------------


def _install_bpy_stub() -> None:
    if "bpy" in sys.modules:
        return

    bpy = types.ModuleType("bpy")
    data = types.SimpleNamespace()
    context = types.SimpleNamespace()

    _meshes: dict[str, object] = {}
    _objects: dict[str, object] = {}

    class _StubMesh:
        def __init__(self, name: str) -> None:
            self.name = name

        def from_pydata(self, verts, edges, faces) -> None:  # noqa: D401
            self.verts = list(verts)
            self.edges = list(edges)
            self.faces = list(faces)

        def update(self) -> None:
            pass

    class _StubObject:
        def __init__(self, name: str, mesh: object) -> None:
            self.name = name
            self.data = mesh
            self.location = (0.0, 0.0, 0.0)

    class _MeshCollection:
        def new(self, name: str) -> _StubMesh:
            m = _StubMesh(name)
            _meshes[name] = m
            return m

        def get(self, name: str):
            return _meshes.get(name)

    class _ObjectCollection:
        def new(self, name: str, mesh: object) -> _StubObject:
            o = _StubObject(name, mesh)
            _objects[name] = o
            return o

        def get(self, name: str):
            return _objects.get(name)

    class _SceneCollection:
        def __init__(self) -> None:
            self.objects = types.SimpleNamespace(
                link=lambda obj: _objects.setdefault(obj.name, obj)
            )

    data.meshes = _MeshCollection()
    data.objects = _ObjectCollection()
    context.collection = _SceneCollection()
    bpy.data = data
    bpy.context = context
    sys.modules["bpy"] = bpy


_install_bpy_stub()


# ---------------------------------------------------------------------------
# Imports (after bpy stub installed)
# ---------------------------------------------------------------------------

from blender_addon.handlers import terrain_caves  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _baseline_params(**overrides) -> dict:
    """Default cave-adapter param shape — matches what compose_map sends."""
    base = {
        "name": "TestCave",
        "seed": 42,
        "width": 16,
        "height": 16,
        "cell_size": 1.0,
        "wall_height": 4.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_handle_generate_cave_exists_and_signature() -> None:
    """Test 1 — adapter exists, takes a single dict param, returns a dict."""
    assert hasattr(terrain_caves, "handle_generate_cave"), (
        "terrain_caves.handle_generate_cave must exist (phase 49 C2 adapter)"
    )
    result = terrain_caves.handle_generate_cave(_baseline_params())
    assert isinstance(result, dict), "handler must return dict"
    for key in ("status", "meshes", "meta"):
        assert key in result, f"return dict missing required key '{key}'"
    assert isinstance(result["meshes"], list), "'meshes' must be a list"
    assert isinstance(result["meta"], dict), "'meta' must be a dict"


def test_handle_generate_cave_wraps_pass_caves() -> None:
    """Test 2 — pass_caves is the underlying engine; sentinel surfaces in meta."""
    sentinel_marker = "SENTINEL_BUNDLE_PHASE49_C2"

    real_pass_caves = terrain_caves.pass_caves

    def fake_pass_caves(state, region):
        # Return a sentinel-bearing PassResult — the adapter must surface
        # this through meta (per plan must_haves: "carry sentinel data
        # through meta or an explicit cave_bundle key").
        result = real_pass_caves(state, region)
        # Tag the metrics so the adapter's meta/bundle path proves wrap.
        result.metrics["__sentinel__"] = sentinel_marker
        return result

    with patch.object(terrain_caves, "pass_caves", side_effect=fake_pass_caves):
        result = terrain_caves.handle_generate_cave(_baseline_params())

    assert result["status"] in {"ok", "warning"}, (
        f"adapter must succeed when pass_caves succeeds; got status={result['status']} "
        f"error={result.get('error')!r}"
    )
    bundle = result["meta"].get("bundle")
    assert bundle is not None, "meta.bundle must surface pass_caves return value"
    metrics = getattr(bundle, "metrics", None) or (
        bundle.get("metrics") if isinstance(bundle, dict) else None
    )
    assert metrics is not None, "pass_caves PassResult must carry metrics"
    assert metrics.get("__sentinel__") == sentinel_marker, (
        "adapter must NOT shape-shift the bundle into a BSP payload — sentinel lost"
    )


def test_handle_generate_cave_compose_map_param_shape() -> None:
    """Test 3 — accepts compose_map's actual param keys without TypeError."""
    # These are the exact keys _build_location_generation_params + the cave
    # branch of compose_map populates (Tools/mcp-toolkit/src/veilbreakers_mcp/
    # blender_server.py:6582-6586).
    params = {
        "name": "Hearthvale_Cave_03",
        "seed": 1234,
        "width": 22,
        "height": 22,
        "cell_size": 0.92,
        "wall_height": 5.4,
        "layout_brief": "coastal sea grotto",
        "site_profile": "coastal",
    }
    # Must not raise — extras (layout_brief, site_profile) are forwarded
    # or ignored, but never crash the adapter.
    result = terrain_caves.handle_generate_cave(params)
    assert result["status"] in {"ok", "warning", "error"}
    # If error, it must NOT be TypeError (means kwargs forwarding broke).
    if result["status"] == "error":
        assert "TypeError" not in (result.get("error") or ""), (
            f"adapter rejected compose_map params with TypeError: {result['error']}"
        )


def test_handle_generate_cave_registered_in_command_handlers() -> None:
    """Test 4 — handler registered as terrain_generate_cave in COMMAND_HANDLERS."""
    from blender_addon.handlers import COMMAND_HANDLERS

    assert "terrain_generate_cave" in COMMAND_HANDLERS, (
        "terrain_generate_cave must be registered in COMMAND_HANDLERS "
        "(phase 49 C2 — see handlers/__init__.py)"
    )
    handler = COMMAND_HANDLERS["terrain_generate_cave"]
    assert callable(handler), "registered handler must be callable"


def test_loc_handlers_cave_dispatches_to_terrain_generate_cave() -> None:
    """Test 5 — blender_server._LOC_HANDLERS['cave'] string-dispatches to
    terrain_generate_cave (not the doomed world_generate_cave).
    """
    from pathlib import Path

    server_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "veilbreakers_mcp"
        / "blender_server.py"
    )
    text = server_path.read_text(encoding="utf-8")
    assert '"cave": "terrain_generate_cave"' in text, (
        "_LOC_HANDLERS['cave'] must dispatch to terrain_generate_cave"
    )
    assert '"cave": "world_generate_cave"' not in text, (
        "old _LOC_HANDLERS['cave'] -> world_generate_cave mapping must be gone"
    )


def test_handle_generate_cave_error_path_returns_dict() -> None:
    """Bonus — when params force an internal failure, adapter returns error
    dict (no raise). T-49-01 mitigation: top-level try/except surfaces all
    exceptions as ``{"status": "error", "error": ...}`` instead of letting
    them escape into the MCP framework dispatch loop.
    """
    # Force pass_caves to raise — proves the try/except gate works.
    def boom(state, region):
        raise RuntimeError("synthetic pass_caves failure for adapter error test")

    with patch.object(terrain_caves, "pass_caves", side_effect=boom):
        result = terrain_caves.handle_generate_cave(_baseline_params())
    assert isinstance(result, dict)
    assert result["status"] == "error", (
        f"adapter must surface internal exceptions as status=error; got {result}"
    )
    error_str = result.get("error") or ""
    assert isinstance(error_str, str) and error_str, (
        "error dict must include a non-empty 'error' string"
    )
    assert "RuntimeError" in error_str, (
        f"error string must include the original exception class; got: {error_str!r}"
    )
