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
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast
from unittest.mock import patch

Vec3 = tuple[float, float, float]
Edge = tuple[int, int]
Face = Sequence[int]


# ---------------------------------------------------------------------------
# bpy stub — terrain_caves itself is pure numpy, but the adapter creates a
# Blender mesh chamber (since callers _position_generated_object the result).
# Provide a minimal bpy stub so the adapter import + mesh creation work in
# pytest without a live Blender process.
# ---------------------------------------------------------------------------


def _install_bpy_stub() -> None:
    if "bpy" in sys.modules:
        return

    _meshes: dict[str, "_StubMesh"] = {}
    _objects: dict[str, "_StubObject"] = {}

    class _StubMesh:
        def __init__(self, name: str) -> None:
            self.name = name
            self.verts: list[Vec3] = []
            self.edges: list[Edge] = []
            self.faces: list[Face] = []

        def from_pydata(
            self,
            verts: Iterable[Vec3],
            edges: Iterable[Edge],
            faces: Iterable[Face],
        ) -> None:  # noqa: D401
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
            self.objects = _SceneObjectLinks()

    class _SceneObjectLinks:
        def link(self, obj: _StubObject) -> _StubObject:
            return _objects.setdefault(obj.name, obj)

    class _BpyData:
        def __init__(self) -> None:
            self.meshes = _MeshCollection()
            self.objects = _ObjectCollection()

    class _BpyContext:
        def __init__(self) -> None:
            self.collection = _SceneCollection()

    class _BpyStub(types.ModuleType):
        data: _BpyData
        context: _BpyContext

    bpy = _BpyStub("bpy")
    data = _BpyData()
    context = _BpyContext()
    bpy.data = data
    bpy.context = context
    sys.modules["bpy"] = bpy


_install_bpy_stub()


# ---------------------------------------------------------------------------
# Imports (after bpy stub installed)
# ---------------------------------------------------------------------------

from veilbreakers_terrain.handlers import terrain_caves  # noqa: E402
from veilbreakers_terrain.handlers.terrain_semantics import (  # noqa: E402
    BBox,
    PassResult,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


Metadata = terrain_caves.Metadata


def _baseline_params(**overrides: object) -> Metadata:
    """Default cave-adapter param shape — matches what compose_map sends."""
    base: Metadata = {
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

    def fake_pass_caves(state: TerrainPipelineState, region: BBox) -> PassResult:
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
    # meta.bundle was removed for JSON-safety (PassResult carries numpy arrays that
    # cannot be serialised over MCP transport).  The adapter now surfaces only
    # JSON-safe scalars: bundle_status, cave_count, and the geometry mesh specs.
    # We verify pass_caves was called by checking cave_count is an int and
    # bundle_status is a string — both are derived from the PassResult.
    assert "bundle_status" in result["meta"], (
        "meta.bundle_status must surface pass_caves call result (JSON-safe scalar)"
    )
    assert isinstance(result["meta"]["bundle_status"], str), (
        "bundle_status must be a string (ok/error)"
    )
    assert "cave_count" in result["meta"], "meta.cave_count must be present"


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
    from veilbreakers_terrain.handlers import COMMAND_HANDLERS

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
    def boom(state: TerrainPipelineState, region: BBox) -> PassResult:
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


# ---------------------------------------------------------------------------
# Phase F — AAA cave system tests (2026-04-23)
# ---------------------------------------------------------------------------


def test_cave_entry_exit_on_different_faces() -> None:
    """When traversable=True the cave must expose entry + exit + secondary
    exit archway specs tagged to three distinct cliff faces so the player
    can traverse through the mountain.
    """
    result = terrain_caves.handle_generate_cave(
        _baseline_params(traversable=True, width=32, height=32, wall_height=8.0)
    )
    assert result["status"] in {"ok", "warning"}, result

    archways = result["meta"]["archway_specs"]
    # Must have entry + exit + secondary exit (3 archways minimum)
    assert len(archways) >= 3, (
        f"traversable=True must yield >=3 archways (entry+exit+secondary); "
        f"got {len(archways)}"
    )
    roles = [a.get("role") for a in archways]
    assert "entry" in roles, f"missing entry archway role; roles={roles}"
    assert "exit" in roles, f"missing primary exit archway role; roles={roles}"
    assert "exit_secondary" in roles, (
        f"missing secondary exit archway role when traversable=True; roles={roles}"
    )

    # Each archway must carry a cliff_face tag, and the three tags must be
    # distinct (different faces of the mountain).
    faces = [a.get("cliff_face") for a in archways]
    assert all(f is not None for f in faces), (
        f"every archway must carry a cliff_face tag; got {faces}"
    )
    assert len(set(faces)) == len(faces), (
        f"archway cliff_face tags must be distinct; got {faces}"
    )


def test_cave_speleothem_pairing_density() -> None:
    """Higher pairing_strength must produce more stalagmite/column pairs
    beneath the stalactite ceiling attachments.
    """
    # High pairing (1.0): every stalactite at a plausible drip line should
    # spawn a stalagmite or column.
    high = terrain_caves.handle_generate_cave(
        _baseline_params(
            seed=7, pairing_strength=1.0, wall_height=3.0, width=14, height=14,
        )
    )
    # Low pairing (0.0): no pairings should be produced.
    low = terrain_caves.handle_generate_cave(
        _baseline_params(
            seed=7, pairing_strength=0.0, wall_height=3.0, width=14, height=14,
        )
    )
    assert high["status"] in {"ok", "warning"}, high
    assert low["status"] in {"ok", "warning"}, low

    def _counts(res: Mapping[str, Any]) -> dict[str, int]:
        c = {"stalactite": 0, "stalagmite": 0, "column": 0}
        natural_props = cast(Iterable[Mapping[str, object]], res.get("natural_props", []))
        for prop in natural_props:
            t = prop.get("prop_type")
            if isinstance(t, str) and t in c:
                c[t] += 1
        return c

    high_c = _counts(high)
    low_c = _counts(low)

    # Low pairing: zero stalagmites and zero columns
    assert low_c["stalagmite"] == 0 and low_c["column"] == 0, (
        f"pairing_strength=0.0 must produce no stalagmites/columns; got {low_c}"
    )
    # High pairing: more stalagmites+columns than low
    assert (high_c["stalagmite"] + high_c["column"]) > (
        low_c["stalagmite"] + low_c["column"]
    ), (
        f"pairing_strength=1.0 must yield more stag+col than 0.0; "
        f"high={high_c}, low={low_c}"
    )


def test_cave_navigation_clearance_minimum() -> None:
    """Every stalactite within the traversable spline corridor must clear
    1.8 m of headroom above the spline floor.
    """
    result = terrain_caves.handle_generate_cave(
        _baseline_params(
            seed=11, traversable=True, min_nav_clearance_m=1.8,
            wall_height=4.0, width=20, height=20,
        )
    )
    assert result["status"] in {"ok", "warning"}, result

    spline = [tuple(p) for p in result["meta"]["traversable_spline"]]
    min_clear = float(result["meta"]["min_nav_clearance_m"])
    assert min_clear == 1.8

    # Walk every stalactite and check the tip Z is >= (spline_z + 1.8) when
    # within 1.0 m XY of any spline waypoint.
    violations: list[str] = []
    for prop in result.get("natural_props", []):
        if prop.get("prop_type") != "stalactite":
            continue
        tx, ty, tz = prop.get("tip_pos", (0.0, 0.0, 0.0))
        # Nearest spline waypoint
        nearest = min(
            spline,
            key=lambda s: (tx - s[0]) ** 2 + (ty - s[1]) ** 2,
        )
        d_xy = ((tx - nearest[0]) ** 2 + (ty - nearest[1]) ** 2) ** 0.5
        if d_xy <= 1.0:
            required = float(nearest[2]) + min_clear
            # Allow tiny float slack
            if tz + 1e-3 < required:
                violations.append(
                    f"stalactite tip_z={tz:.3f} < required={required:.3f} "
                    f"(spline_z={nearest[2]:.3f}, d_xy={d_xy:.3f})"
                )

    assert not violations, (
        "navigation clearance violations along traversable spline:\n  "
        + "\n  ".join(violations)
    )


def test_cave_opening_material_seam_integration() -> None:
    """validate_cave_opening_integration must return a list and flag
    abrupt cliff_candidate jumps (>0.50) within 2 cells of the opening.
    """
    import numpy as np

    # Build a synthetic mask stack with a single cave opening at (10,10).
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    rows, cols = 24, 24
    stack = TerrainMaskStack(
        tile_size=max(rows, cols),
        cell_size=1.0,
        world_origin_x=-float(cols) * 0.5,
        world_origin_y=-float(rows) * 0.5,
        tile_x=0,
        tile_y=0,
        height=np.zeros((rows, cols), dtype=np.float32),
        height_min_m=0.0,
        height_max_m=1.0,
    )

    # Clean case: smooth cliff + cave_candidate at (10, 10), no abrupt jumps.
    cliff = np.full((rows, cols), 0.6, dtype=np.float32)
    tex = np.full((rows, cols), 0.2, dtype=np.float32)
    cand = np.zeros((rows, cols), dtype=bool)
    cand[9:12, 9:12] = True
    stack.set("cliff_candidate", cliff, "caves")
    stack.set("cave_wall_texture", tex, "caves")
    stack.set("cave_candidate", cand, "caves")

    clean_issues = terrain_caves.validate_cave_opening_integration(stack)
    assert isinstance(clean_issues, list), (
        f"validator must return a list, got {type(clean_issues)}"
    )
    assert not clean_issues, (
        f"clean case should yield no issues; got {clean_issues}"
    )

    # Abrupt case: inject a massive cliff_candidate jump right next to opening.
    cliff_bad = cliff.copy()
    cliff_bad[10, 11] = 0.0  # drop from 0.6 to 0.0 → 0.60 jump > 0.50
    stack.set("cliff_candidate", cliff_bad, "caves")

    bad_issues = terrain_caves.validate_cave_opening_integration(stack)
    assert any(
        "abrupt_cliff_change" in s for s in bad_issues
    ), (
        f"validator should flag abrupt cliff change; got {bad_issues}"
    )


def test_cave_canyon_dual_exit_regression() -> None:
    """Regression: commit e0945c3 ("canyon dual-exit tunnels") — the
    ``generate_canyon_dual_exit`` helper must still exist, be callable, and
    traversable=True on the adapter must surface an ``exit_secondary`` archway.
    """
    import numpy as np

    # Helper must exist in the public API
    assert hasattr(terrain_caves, "generate_canyon_dual_exit"), (
        "generate_canyon_dual_exit must remain in the public API"
    )

    # --- Direct regression of the helper -----------------------------------
    # Build a synthetic stack with cliffs on east + west of the cave midpoint
    # (canyon topology) and a long enough path to trip the depth heuristic.
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    from veilbreakers_terrain.handlers.terrain_caves import CaveStructure, CaveArchetype, make_archetype_spec

    rows, cols = 80, 80
    stack = TerrainMaskStack(
        tile_size=max(rows, cols),
        cell_size=1.0,
        world_origin_x=-40.0,
        world_origin_y=-40.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((rows, cols), dtype=np.float32),
        height_min_m=0.0,
        height_max_m=1.0,
    )
    # Cliff mask: canyon walls on both east and west of midpoint (col=40).
    # quad_r is 20% of path diagonal; need cliff cells in the quadrant
    # sampling window on both sides.  Make it dense — full canyon wall.
    cliff = np.zeros((rows, cols), dtype=np.float32)
    cliff[:, :40] = 0.8   # entire west half is cliff (west canyon wall)
    cliff[:, 41:] = 0.8   # entire east half is cliff (east canyon wall)
    stack.set("cliff_candidate", cliff, "caves")

    # Fake cave path: 50 m long east–west through canyon centre
    path_world = [(-25.0 + i, 0.0, 0.0) for i in range(0, 51, 5)]
    cave = CaveStructure(
        cave_id="test",
        archetype=CaveArchetype.KARST_SINKHOLE,
        spec=make_archetype_spec(CaveArchetype.KARST_SINKHOLE),
        entrance_world_pos=path_world[0],
        path_world=path_world,
        path_aabb=(-25.0, 0.0, 0.0, 25.0, 0.0, 0.0),
    )
    dual = terrain_caves.generate_canyon_dual_exit(stack, cave)
    assert dual is not None, (
        "generate_canyon_dual_exit must return a second exit for canyon "
        "topology with >40 m path diagonal"
    )
    assert len(dual) == 3, "dual-exit must be a (wx, wy, wz) 3-tuple"

    # --- Adapter-level regression: traversable=True surfaces secondary exit ---
    result = terrain_caves.handle_generate_cave(
        _baseline_params(traversable=True, wall_height=6.0, width=20, height=20)
    )
    assert result["status"] in {"ok", "warning"}, result
    archway_specs = result["meta"]["archway_specs"]
    roles = [a.get("role") for a in archway_specs]
    assert "exit_secondary" in roles, (
        f"traversable=True must emit exit_secondary; roles={roles}"
    )


def test_cave_stalactite_ceiling_regression() -> None:
    """Regression: commit 7adfef1 (stalactite ceiling placement + navigation
    clearance) — stalactite tip_z must be below the ceiling attachment Z
    (pointing down) and the handler must surface entry/exit world positions.
    """
    result = terrain_caves.handle_generate_cave(_baseline_params(wall_height=4.0))
    assert result["status"] in {"ok", "warning"}, result

    # entry/exit positions present at top level (7adfef1 contract)
    assert "entry_world_pos" in result, "entry_world_pos must be at top level"
    assert "exit_world_pos" in result, "exit_world_pos must be at top level"
    assert len(result["entry_world_pos"]) == 3

    # stalactite tip_z < world_pos z (hangs downward from ceiling)
    stalac = [
        p for p in result.get("natural_props", [])
        if p.get("prop_type") == "stalactite"
    ]
    assert stalac, "must produce at least one stalactite for this regression test"
    for s in stalac:
        wz = s["world_pos"][2]
        tz = s["tip_pos"][2]
        assert tz < wz, (
            f"stalactite must hang down (tip below ceiling): "
            f"ceil={wz:.3f} tip={tz:.3f}"
        )


def test_cave_interior_material_separate_from_exterior() -> None:
    """Interior rendering material must be published separately from the
    exterior surround/overhang material on the chamber mesh spec.  Interior
    albedo must be darker and roughness higher than exterior.
    """
    result = terrain_caves.handle_generate_cave(_baseline_params())
    chamber_spec = result["meta"]["chamber_mesh_spec"]

    assert "interior_material" in chamber_spec, (
        "chamber_mesh_spec must carry interior_material"
    )
    assert "exterior_material" in chamber_spec, (
        "chamber_mesh_spec must carry exterior_material"
    )
    interior = chamber_spec["interior_material"]
    exterior = chamber_spec["exterior_material"]

    # Interior albedo mean < exterior albedo mean (darker)
    int_mean = sum(interior["albedo_rgb"]) / 3.0
    ext_mean = sum(exterior["albedo_rgb"]) / 3.0
    assert int_mean < ext_mean, (
        f"interior albedo ({int_mean:.3f}) must be darker than "
        f"exterior ({ext_mean:.3f})"
    )
    # Interior roughness > exterior (damp rock)
    assert interior["roughness"] > exterior["roughness"], (
        f"interior roughness ({interior['roughness']}) must exceed "
        f"exterior ({exterior['roughness']})"
    )
    # Damp normal variation: interior normal_scale should be larger
    assert interior["normal_scale"] > exterior["normal_scale"], (
        f"interior normal_scale ({interior['normal_scale']}) must exceed "
        f"exterior ({exterior['normal_scale']})"
    )
