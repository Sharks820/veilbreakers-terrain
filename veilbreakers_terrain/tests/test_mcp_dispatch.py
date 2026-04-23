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

import numpy as np
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

    def test_execute_command_invalid_params_returns_error_dict(self) -> None:
        s = BlenderMCPServer()
        r = s.execute_command("mesh_select_by_box", "not a dict")  # type: ignore[arg-type]
        assert r["status"] == "error"
        assert r["error"] == "invalid_params"

    def test_execute_command_preserves_handler_error_payload(self) -> None:
        def _fail_closed(params):
            return {"status": "error", "error": "no_active_controller"}

        s = BlenderMCPServer(handlers={"preview_state": _fail_closed})
        r = s.execute_command("preview_state", {})
        assert r["status"] == "error"
        assert r["error"] == "no_active_controller"
        assert r["command"] == "preview_state"

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

    def test_queue_flow_preserves_handler_error_payload(self) -> None:
        def _fail_closed(params):
            return {"status": "error", "error": "no_active_controller"}

        s = BlenderMCPServer(handlers={"preview_state": _fail_closed})
        s.enqueue({"command": "preview_state", "params": {}})
        s._process_commands()
        results = s.drain_results()
        assert results == [
            {
                "status": "error",
                "error": "no_active_controller",
                "command": "preview_state",
            }
        ]


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

    def test_dispatch_invalid_params_returns_error_dict(self) -> None:
        r = dispatch("mesh_select_box", "not a dict")  # type: ignore[arg-type]
        assert r["status"] == "error"
        assert r["error"] == "invalid_params"

    def test_dispatch_preserves_handler_error_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fail_closed(params):
            return {"status": "error", "error": "no_active_controller"}

        monkeypatch.setitem(COMMAND_HANDLERS, "mesh_select_by_box", _fail_closed)
        r = dispatch("mesh_select_box", {})
        assert r["status"] == "error"
        assert r["error"] == "no_active_controller"
        assert r["location"] == "mesh_select_box"
        assert r["command"] == "mesh_select_by_box"


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
            "env_export_unity_bundle",
            "env_generate_multi_biome_world",
            "scatter_create_breakable",
            "material_create_procedural",
            "terrain_generate_lods",
            "terrain_setup_biome",
            "terrain_sculpt",
            "terrain_preview_apply",
            "terrain_preview_state",
            "terrain_preview_reset",
            "terrain_preview_diff",
            "terrain_preview_render_thumbnail",
            "terrain_hot_reload_start",
            "terrain_hot_reload_check",
            "terrain_hot_reload_stop",
            "terrain_check_addon_health",
            "terrain_detect_stale_addon",
            "terrain_force_addon_reload",
            "terrain_boolean_safety_check",
            "terrain_convert_yup_to_zup",
            "terrain_clamp_screenshot_size",
            "terrain_load_quality_profile",
            "terrain_list_quality_profiles",
            "terrain_apply_quality_profile",
            "mesh_select_by_sphere",
            "mesh_select_by_plane",
            "mesh_parse_selection_criteria",
            "mesh_smooth_assembled",
            "vertex_paint_compute_weights",
            "vertex_paint_compute_weights_uv",
            "vertex_paint_blend_colors",
            "weathering_compute_vertex_colors",
            "weathering_apply_structural_settling",
            "animation_generate_env_keyframes",
        ],
    )
    def test_command_handler_registered(self, command_name: str) -> None:
        assert command_name in COMMAND_HANDLERS, (
            f"{command_name} missing from COMMAND_HANDLERS"
        )
        assert callable(COMMAND_HANDLERS[command_name]), (
            f"COMMAND_HANDLERS[{command_name!r}] is not callable"
        )


class TestObservationAndSafetyDispatch:
    @pytest.mark.parametrize(
        ("location_key", "command_name"),
        [
            ("scene_read", "terrain_capture_scene_read"),
            ("viewport_read", "terrain_read_viewport_vantage"),
            ("viewport_fresh", "terrain_assert_vantage_fresh"),
            ("frustum_check", "terrain_is_in_frustum"),
            ("preview_diff", "terrain_preview_diff"),
            ("preview_render", "terrain_preview_render_thumbnail"),
            ("hot_reload_start", "terrain_hot_reload_start"),
            ("hot_reload_check", "terrain_hot_reload_check"),
            ("hot_reload_stop", "terrain_hot_reload_stop"),
            ("validation", "terrain_validation"),
            ("perf_report", "terrain_performance_report"),
            ("navmesh_export", "terrain_navmesh_export"),
            ("unity_export", "env_export_unity_bundle"),
            ("addon_health", "terrain_check_addon_health"),
            ("addon_stale", "terrain_detect_stale_addon"),
            ("addon_reload", "terrain_force_addon_reload"),
            ("safety_boolean", "terrain_boolean_safety_check"),
            ("safety_convert_yup", "terrain_convert_yup_to_zup"),
            ("safety_screenshot_size", "terrain_clamp_screenshot_size"),
            ("terrain_sculpt", "terrain_sculpt"),
            ("terrain_lods", "terrain_generate_lods"),
            ("terrain_biome_setup", "terrain_setup_biome"),
            ("material_procedural", "material_create_procedural"),
        ],
    )
    def test_loc_handler_maps_to_registered_command(self, location_key: str, command_name: str) -> None:
        assert resolve_command(location_key) == command_name
        assert command_name in COMMAND_HANDLERS

    def test_dispatch_scene_read_happy_path(self) -> None:
        r = dispatch("scene_read", {"reviewer": "pytest"})
        assert r["status"] == "ok"
        assert r["command"] == "terrain_capture_scene_read"
        assert r["result"]["ok"] is True

    def test_dispatch_viewport_read_happy_path(self) -> None:
        r = dispatch("viewport_read", {})
        assert r["status"] == "ok"
        assert r["command"] == "terrain_read_viewport_vantage"
        vantage = r["result"]["vantage"]
        assert "camera_position" in vantage
        assert "visible_bounds" in vantage

    def test_dispatch_viewport_fresh_happy_path(self) -> None:
        vantage = dispatch("viewport_read", {})["result"]["vantage"]
        r = dispatch("viewport_fresh", {"vantage": vantage, "max_age_seconds": 300.0})
        assert r["status"] == "ok"
        assert r["result"]["fresh"] is True

    def test_dispatch_safety_convert_yup_happy_path(self) -> None:
        r = dispatch(
            "safety_convert_yup",
            {"position": [1.0, 2.0, 3.0], "orientation": [0.0, 0.0, 0.0]},
        )
        assert r["status"] == "ok"
        assert r["result"]["position"] == [1.0, -3.0, 2.0]

    def test_dispatch_safety_screenshot_size_happy_path(self) -> None:
        r = dispatch("safety_screenshot_size", {"requested": 999})
        assert r["status"] == "ok"
        assert r["result"]["clamped"] == 507

    def test_preview_handler_error_contracts_without_controller(self) -> None:
        for command_name in (
            "terrain_preview_apply",
            "terrain_preview_state",
            "terrain_preview_diff",
            "terrain_preview_render_thumbnail",
        ):
            result = COMMAND_HANDLERS[command_name]({})
            assert result["status"] == "error"
            assert result["error"] == "no_active_controller"

    def test_preview_reset_handler(self) -> None:
        result = COMMAND_HANDLERS["terrain_preview_reset"]({})
        assert result == {"status": "ok", "reset": True}

    def test_hot_reload_handlers_happy_path(self) -> None:
        start = COMMAND_HANDLERS["terrain_hot_reload_start"]({})
        assert start["status"] == "ok"
        assert isinstance(start["watched"], list)

        check = COMMAND_HANDLERS["terrain_hot_reload_check"]({})
        assert check["status"] == "ok"
        assert isinstance(check["reloaded"], list)

        stop = COMMAND_HANDLERS["terrain_hot_reload_stop"]({})
        assert stop == {"status": "ok", "stopped": True}

    def test_addon_health_handlers_happy_path(self) -> None:
        health = COMMAND_HANDLERS["terrain_check_addon_health"]({})
        assert health["status"] == "ok"
        assert health["loaded"] is True

        stale = COMMAND_HANDLERS["terrain_detect_stale_addon"]({})
        assert stale["status"] == "ok"
        assert isinstance(stale["stale"], bool)

        reload_result = COMMAND_HANDLERS["terrain_force_addon_reload"]({})
        assert reload_result["status"] == "ok"
        assert isinstance(reload_result["reloaded"], bool)

    def test_safety_handlers_happy_path(self) -> None:
        boolean_result = COMMAND_HANDLERS["terrain_boolean_safety_check"]({})
        assert boolean_result["status"] == "ok"
        assert "recommended_solver" in boolean_result

        convert_result = COMMAND_HANDLERS["terrain_convert_yup_to_zup"](
            {"position": [1.0, 2.0, 3.0], "orientation": [0.0, 0.0, 0.0]}
        )
        assert convert_result["status"] == "ok"
        assert convert_result["position"] == [1.0, -3.0, 2.0]

        clamp_result = COMMAND_HANDLERS["terrain_clamp_screenshot_size"]({"requested": 999})
        assert clamp_result["status"] == "ok"
        assert clamp_result["clamped"] == 507

    def test_quality_profile_handlers_happy_path(self) -> None:
        listed = COMMAND_HANDLERS["terrain_list_quality_profiles"]({})
        assert listed["status"] == "ok"
        assert "production" in listed["profiles"]

        loaded = COMMAND_HANDLERS["terrain_load_quality_profile"]({"name": "production"})
        assert loaded["status"] == "ok"
        assert loaded["profile"]["name"] == "production"

        applied = COMMAND_HANDLERS["terrain_apply_quality_profile"]({"name": "production"})
        assert applied["status"] == "ok"
        assert applied["profile"]["name"] == "production"

    def test_mesh_bridge_handlers_happy_path(self) -> None:
        verts = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0)]
        sphere = COMMAND_HANDLERS["mesh_select_by_sphere"](
            {"verts": verts, "center": [0.0, 0.0, 0.0], "radius": 0.5}
        )
        assert sphere == [0]

        plane = COMMAND_HANDLERS["mesh_select_by_plane"](
            {"verts": verts, "plane_point": [0.0, 0.0, 0.0], "plane_normal": [1.0, 0.0, 0.0], "side": "above"}
        )
        assert 1 in plane

        parsed = COMMAND_HANDLERS["mesh_parse_selection_criteria"](
            {"criteria": {"mode": "vertex"}, "strict": False}
        )
        assert isinstance(parsed, dict)

    def test_vertex_paint_bridge_handlers_happy_path(self) -> None:
        weights = COMMAND_HANDLERS["vertex_paint_compute_weights"](
            {
                "verts": [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)],
                "brush_center": [0.0, 0.0, 0.0],
                "radius": 2.0,
                "falloff_mode": "SMOOTH",
            }
        )
        assert isinstance(weights, list)
        assert weights == [(0, 1.0)]

        weights_uv = COMMAND_HANDLERS["vertex_paint_compute_weights_uv"](
            {
                "uvs": [(0.5, 0.5), (0.9, 0.9)],
                "brush_center_uv": [0.5, 0.5],
                "radius": 0.3,
                "falloff_mode": "SMOOTH",
            }
        )
        assert isinstance(weights_uv, list)
        assert weights_uv == [(0, 1.0)]

        blended = COMMAND_HANDLERS["vertex_paint_blend_colors"](
            {
                "existing": [0.0, 0.0, 0.0, 1.0],
                "new_color": [1.0, 0.0, 0.0, 1.0],
                "strength": 0.5,
                "mode": "MIX",
            }
        )
        assert isinstance(blended, tuple)
        assert blended[0] > 0.0

    def test_weathering_and_animation_bridge_handlers_happy_path(self) -> None:
        colors = COMMAND_HANDLERS["weathering_compute_vertex_colors"](
            {
                "mesh_data": {
                    "vertices": [
                        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5),
                        (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
                        (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5),
                        (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
                    ],
                    "faces": [
                        (0, 1, 2, 3), (4, 7, 6, 5),
                        (0, 4, 5, 1), (2, 6, 7, 3),
                        (0, 3, 7, 4), (1, 5, 6, 2),
                    ],
                    "face_normals": [
                        (0, 0, -1), (0, 0, 1),
                        (0, -1, 0), (0, 1, 0),
                        (-1, 0, 0), (1, 0, 0),
                    ],
                    "vertex_normals": [
                        (-0.577, -0.577, -0.577), (0.577, -0.577, -0.577),
                        (0.577, 0.577, -0.577), (-0.577, 0.577, -0.577),
                        (-0.577, -0.577, 0.577), (0.577, -0.577, 0.577),
                        (0.577, 0.577, 0.577), (-0.577, 0.577, 0.577),
                    ],
                    "edges": [
                        (0, 1), (1, 2), (2, 3), (3, 0),
                        (4, 5), (5, 6), (6, 7), (7, 4),
                        (0, 4), (1, 5), (2, 6), (3, 7),
                    ],
                },
                "base_color": [0.5, 0.5, 0.5, 1.0],
            }
        )
        assert isinstance(colors, list)

        settled = COMMAND_HANDLERS["weathering_apply_structural_settling"](
            {"verts": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], "strength": 0.01, "seed": 42}
        )
        assert isinstance(settled, list)

        keyframes = COMMAND_HANDLERS["animation_generate_env_keyframes"](
            {"env_type": "fire_flicker", "frame_count": 8}
        )
        assert isinstance(keyframes, list)

    def test_validation_and_navmesh_bridge_missing_param_contracts(self) -> None:
        validation = COMMAND_HANDLERS["terrain_validation"]({})
        assert validation["status"] == "error"
        assert validation["error"] == "missing_params"

        navmesh = COMMAND_HANDLERS["terrain_navmesh_export"]({})
        assert navmesh["status"] == "error"
        assert navmesh["error"] == "missing_params"

    def test_validation_bridge_uses_overall_status(self) -> None:
        from blender_addon.handlers.terrain_semantics import BBox, TerrainIntentState, TerrainMaskStack

        stack = TerrainMaskStack(
            tile_size=4,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
            height=np.full((4, 4), 10.0, dtype=np.float64),
        )
        intent = TerrainIntentState(
            seed=1,
            region_bounds=BBox(0.0, 0.0, 4.0, 4.0),
            tile_size=4,
            cell_size=1.0,
        )

        validation = COMMAND_HANDLERS["terrain_validation"](
            {"mask_stack": stack, "intent": intent}
        )

        assert validation["status"] in {"ok", "warning", "failed"}
