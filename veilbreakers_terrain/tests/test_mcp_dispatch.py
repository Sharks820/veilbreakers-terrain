"""Tests for the MCP dispatch surfaces (socket_server + blender_server).

Covers:
  - :class:`veilbreakers_terrain.socket_server.BlenderMCPServer`
    execute_command + enqueue/_process_commands/drain_results flow
  - :mod:`veilbreakers_terrain.src.veilbreakers_mcp.blender_server`
    dispatch() + resolve_command() + list_locations()

These tests are bpy-free by design — the dispatchers must remain callable
from CI, and the handlers we pick to exercise the happy path are pure Python
(mesh selection, weathering color math, etc.).
"""
from __future__ import annotations

import pytest

from veilbreakers_terrain.socket_server import (
    BlenderMCPServer,
    TIMER_INTERVAL_S,
)
from veilbreakers_terrain.src.veilbreakers_mcp.blender_server import (
    _LOC_HANDLERS,
    dispatch,
    list_locations,
    resolve_command,
)
from veilbreakers_terrain.handlers import COMMAND_HANDLERS


# ---------------------------------------------------------------------------
# socket_server.BlenderMCPServer
# ---------------------------------------------------------------------------
class TestBlenderMCPServer:
    def test_execute_command_unknown_returns_error_dict(self) -> None:
        s = BlenderMCPServer()
        r = s.execute_command("does_not_exist_zzz", {})
        assert r["status"] == "error"
        assert r["error"] == "unknown_command"
        assert r["command"] == "does_not_exist_zzz"

    def test_execute_command_happy_path_mesh_select_by_box(self) -> None:
        s = BlenderMCPServer()
        r = s.execute_command(
            "mesh_select_by_box",
            {
                "verts": [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (2.0, 2.0, 2.0)],
                "min_pt": (0.0, 0.0, 0.0),
                "max_pt": (1.0, 1.0, 1.0),
            },
        )
        assert r["status"] == "ok"
        assert r["command"] == "mesh_select_by_box"
        # Verts 0 and 1 are inside the box, vert 2 is outside.
        assert r["result"] == [0, 1]

    def test_execute_command_handler_exception_wraps(self) -> None:
        # Inject a custom handler that blows up; assert the wrapper.
        def _boom(params):
            raise ValueError("boom")

        s = BlenderMCPServer(handlers={"boom": _boom})
        r = s.execute_command("boom", {})
        assert r["status"] == "error"
        assert r["error"] == "handler_exception"
        assert r["exception_type"] == "ValueError"
        assert r["message"] == "boom"

    def test_execute_command_none_params(self) -> None:
        # Passing params=None must be coerced to {} without crashing.
        s = BlenderMCPServer()
        r = s.execute_command("does_not_exist_zzz", None)
        assert r["status"] == "error"
        assert r["error"] == "unknown_command"

    def test_enqueue_rejects_non_dict(self) -> None:
        s = BlenderMCPServer()
        with pytest.raises(TypeError):
            s.enqueue("not a dict")  # type: ignore[arg-type]

    def test_queue_flow_drains_on_process_commands(self) -> None:
        s = BlenderMCPServer()
        s.enqueue({"command": "does_not_exist_zzz", "params": {}})
        s.enqueue(
            {
                "command": "mesh_select_by_box",
                "params": {
                    "verts": [(0.0, 0.0, 0.0)],
                    "min_pt": (-1.0, -1.0, -1.0),
                    "max_pt": (1.0, 1.0, 1.0),
                },
            }
        )
        interval = s._process_commands()
        assert interval == TIMER_INTERVAL_S
        results = s.drain_results()
        assert len(results) == 2
        assert results[0]["status"] == "error"
        assert results[1]["status"] == "ok"
        # Second drain is empty (we consumed the results).
        assert s.drain_results() == []


# ---------------------------------------------------------------------------
# blender_server.dispatch
# ---------------------------------------------------------------------------
class TestBlenderServerDispatch:
    def test_loc_handlers_all_resolve_to_registered_command_handlers(self) -> None:
        """Every _LOC_HANDLERS value must be a real COMMAND_HANDLERS key."""
        missing = [
            (loc, cmd)
            for loc, cmd in _LOC_HANDLERS.items()
            if cmd not in COMMAND_HANDLERS
        ]
        assert not missing, (
            "_LOC_HANDLERS entries point at commands not in COMMAND_HANDLERS:\n"
            + "\n".join(f"  {loc} -> {cmd}" for loc, cmd in missing)
        )

    def test_list_locations_is_sorted_and_nonempty(self) -> None:
        locs = list(list_locations())
        assert locs, "list_locations returned empty"
        assert locs == sorted(locs)

    def test_resolve_command_known(self) -> None:
        assert resolve_command("cave") == "terrain_generate_cave"
        assert resolve_command("waterfall") == "env_generate_waterfall"
        assert resolve_command("road") == "env_compute_road_network"
        assert resolve_command("coastline") == "env_generate_coastline"

    def test_resolve_command_unknown_returns_none(self) -> None:
        assert resolve_command("definitely_not_a_location") is None

    def test_dispatch_unknown_location(self) -> None:
        r = dispatch("not_a_location", {})
        assert r["status"] == "error"
        assert r["error"] == "unknown_location"
        assert r["location"] == "not_a_location"

    def test_dispatch_happy_path_mesh_select_box(self) -> None:
        r = dispatch(
            "mesh_select_box",
            {
                "verts": [(0.0, 0.0, 0.0), (5.0, 5.0, 5.0)],
                "min_pt": (-1.0, -1.0, -1.0),
                "max_pt": (1.0, 1.0, 1.0),
            },
        )
        assert r["status"] == "ok"
        assert r["location"] == "mesh_select_box"
        assert r["command"] == "mesh_select_by_box"
        # Only the first vert is inside the (-1,-1,-1)..(1,1,1) box.
        assert r["result"] == [0]

    def test_dispatch_none_params(self) -> None:
        # None params path — resolver should still hit the handler.
        # We pick an unknown location to keep this test free of handler-side
        # requirements.
        r = dispatch("not_real", None)
        assert r["status"] == "error"
        assert r["error"] == "unknown_location"


# ---------------------------------------------------------------------------
# Fix 9.7 — scatter handlers registered in COMMAND_HANDLERS (BUG-S9-015)
# ---------------------------------------------------------------------------
class TestScatterCommandHandlers:
    """Verify scatter_vegetation and scatter_biome_vegetation are in COMMAND_HANDLERS."""

    def test_scatter_vegetation_registered(self) -> None:
        assert "scatter_vegetation" in COMMAND_HANDLERS, (
            "scatter_vegetation missing from COMMAND_HANDLERS"
        )

    def test_scatter_vegetation_callable(self) -> None:
        assert callable(COMMAND_HANDLERS["scatter_vegetation"]), (
            "COMMAND_HANDLERS['scatter_vegetation'] is not callable"
        )

    def test_scatter_biome_vegetation_registered(self) -> None:
        assert "scatter_biome_vegetation" in COMMAND_HANDLERS, (
            "scatter_biome_vegetation missing from COMMAND_HANDLERS"
        )

    def test_scatter_biome_vegetation_callable(self) -> None:
        assert callable(COMMAND_HANDLERS["scatter_biome_vegetation"]), (
            "COMMAND_HANDLERS['scatter_biome_vegetation'] is not callable"
        )

    def test_scatter_props_registered(self) -> None:
        assert "scatter_props" in COMMAND_HANDLERS, (
            "scatter_props missing from COMMAND_HANDLERS"
        )

    def test_scatter_props_callable(self) -> None:
        assert callable(COMMAND_HANDLERS["scatter_props"]), (
            "COMMAND_HANDLERS['scatter_props'] is not callable"
        )


class TestExpandedCommandHandlers:
    """Verify newly bridged public handlers stay exposed on the dispatch table."""

    @pytest.mark.parametrize(
        "command_name",
        [
            "env_generate_terrain",
            "env_generate_terrain_tile",
            "env_generate_world_terrain",
            "env_stitch_terrain_edges",
            "env_paint_terrain",
            "env_carve_river",
            "env_carve_water_basin",
            "env_create_water",
            "env_export_heightmap",
            "env_generate_multi_biome_world",
            "scatter_create_breakable",
            "material_create_procedural",
            "terrain_generate_lods",
            "terrain_setup_biome",
            "terrain_sculpt",
        ],
    )
    def test_command_handler_registered(self, command_name: str) -> None:
        assert command_name in COMMAND_HANDLERS, (
            f"{command_name} missing from COMMAND_HANDLERS"
        )
        assert callable(COMMAND_HANDLERS[command_name]), (
            f"COMMAND_HANDLERS[{command_name!r}] is not callable"
        )
