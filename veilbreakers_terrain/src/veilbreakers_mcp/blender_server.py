"""Blender MCP server — location/action -> COMMAND_HANDLERS dispatcher.

This is the thin MCP-facing shim: callers pass a human/location keyword
(``"cave"``, ``"waterfall"``, ``"road"``, ``"mesh_smooth"``, etc.) plus a
params dict, and the shim resolves it to a registered
``veilbreakers_terrain.handlers.COMMAND_HANDLERS`` entry and invokes it.

The shim exists so the MCP layer can keep a stable, human-centric vocabulary
even as the underlying terrain COMMAND_HANDLERS keys evolve. _LOC_HANDLERS
maps each location/action keyword to the canonical COMMAND_HANDLERS key.

This file must stay bpy-free at import time.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Location / action -> COMMAND_HANDLERS key
# ---------------------------------------------------------------------------
# Keys are human-readable categories. Values must match entries in
# ``veilbreakers_terrain.handlers.COMMAND_HANDLERS``. Unknown keys return an
# error dict rather than raising.
_LOC_HANDLERS: Dict[str, str] = {
    # ------------------------------------------------------------------
    # Terrain generators (locations/archetypes)
    # ------------------------------------------------------------------
    "cave": "terrain_generate_cave",
    "waterfall": "env_generate_waterfall",
    "coastline": "env_generate_coastline",
    "road": "env_compute_road_network",
    "canyon": "env_generate_canyon",
    "cliff_face": "env_generate_cliff_face",
    "swamp": "env_generate_swamp_terrain",
    "world_map": "world_generate_world_map",
    # ------------------------------------------------------------------
    # Terrain advanced edit ops
    # ------------------------------------------------------------------
    "spline_deform": "terrain_spline_deform",
    "terrain_layers": "terrain_layers",
    "erosion_paint": "terrain_erosion_paint",
    "terrain_stamp": "terrain_stamp",
    "snap_to_terrain": "terrain_snap_to_terrain",
    "flatten_zone": "terrain_flatten_zone",
    "run_terrain_pass": "env_run_terrain_pass",
    # ------------------------------------------------------------------
    # Mesh operations
    # ------------------------------------------------------------------
    "mesh_select_box": "mesh_select_by_box",
    "mesh_select_sphere": "mesh_select_by_sphere",
    "mesh_select_plane": "mesh_select_by_plane",
    "mesh_parse_selection": "mesh_parse_selection_criteria",
    "mesh_smooth": "mesh_smooth_assembled",
    # ------------------------------------------------------------------
    # Vertex paint
    # ------------------------------------------------------------------
    "paint_weights": "vertex_paint_compute_weights",
    "paint_weights_uv": "vertex_paint_compute_weights_uv",
    "paint_blend": "vertex_paint_blend_colors",
    # ------------------------------------------------------------------
    # Autonomous mesh-quality loop
    # ------------------------------------------------------------------
    "quality_evaluate": "autonomous_evaluate_mesh_quality",
    "quality_fix_action": "autonomous_select_fix_action",
    # ------------------------------------------------------------------
    # Weathering
    # ------------------------------------------------------------------
    "weather_colors": "weathering_compute_vertex_colors",
    "weather_settling": "weathering_apply_structural_settling",
    # ------------------------------------------------------------------
    # Light + atmosphere
    # ------------------------------------------------------------------
    "light_place": "env_compute_light_placements",
    "light_merge": "env_merge_lights",
    "light_budget": "env_light_budget",
    "atmosphere_place": "env_compute_atmospheric_placements",
    "atmosphere_mesh": "env_volume_mesh_spec",
    "atmosphere_perf": "env_atmosphere_performance",
    # ------------------------------------------------------------------
    # Animation (unified dispatcher + common named generators)
    # ------------------------------------------------------------------
    "animate": "animation_generate_env_keyframes",
    "animate_door_open": "animation_door_open",
    "animate_door_close": "animation_door_close",
    "animate_door_creak": "animation_door_creak",
    "animate_door_slam": "animation_door_slam",
    "animate_chest_open": "animation_chest_open",
    "animate_torch_sway": "animation_torch_sway",
    "animate_fire_flicker": "animation_fire_flicker",
    "animate_candle_flicker": "animation_candle_flicker",
    "animate_chandelier_sway": "animation_chandelier_sway",
    "animate_banner_wind": "animation_banner_wind",
    "animate_flag_wind": "animation_flag_wind",
    "animate_chain_swing": "animation_chain_swing",
    "animate_rope_sway": "animation_rope_sway",
    "animate_water_ripple": "animation_water_ripple",
    "animate_water_wave": "animation_water_wave",
    "animate_waterfall": "animation_waterfall",
    "animate_windmill": "animation_windmill_rotate",
    "animate_drawbridge": "animation_drawbridge",
    "animate_gate_raise": "animation_gate_raise",
    "animate_gate_lower": "animation_gate_lower",
    "animate_lever_pull": "animation_lever_pull",
    "animate_switch_toggle": "animation_switch_toggle",
    "animate_trap_idle": "animation_trap_idle",
    "animate_trap_trigger": "animation_trap_trigger",
    "animate_trap_reset": "animation_trap_reset",
    "animate_shatter": "animation_shatter",
    "animate_wobble_collapse": "animation_wobble_collapse",
}


def list_locations() -> Iterable[str]:
    """Return the sorted list of supported location/action keys."""
    return sorted(_LOC_HANDLERS)


def resolve_command(location_key: str) -> Optional[str]:
    """Resolve a location key to its canonical COMMAND_HANDLERS key.

    Returns ``None`` when the location key is not registered.
    """
    return _LOC_HANDLERS.get(location_key)


def dispatch(
    location_key: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Dispatch a location/action through to the terrain COMMAND_HANDLERS.

    Parameters
    ----------
    location_key:
        Human-readable category in :data:`_LOC_HANDLERS` (e.g. ``"cave"``).
    params:
        Handler kwargs. ``None`` is treated as ``{}``.

    Returns
    -------
    dict
        Shape::

            {"status": "ok", "location": location_key,
             "command": <resolved_cmd>, "result": <handler_return>}

        On unknown location::

            {"status": "error", "error": "unknown_location",
             "location": location_key}

        On unknown command (location resolved but handler missing)::

            {"status": "error", "error": "unknown_command",
             "location": location_key, "command": <resolved_cmd>}

        On handler exception::

            {"status": "error", "error": "handler_exception",
             "location": location_key, "command": <resolved_cmd>,
             "exception_type": "...", "message": "..."}
    """
    if params is None:
        params = {}

    command = _LOC_HANDLERS.get(location_key)
    if command is None:
        logger.warning("blender_server.dispatch: unknown location %r", location_key)
        return {
            "status": "error",
            "error": "unknown_location",
            "location": location_key,
        }

    # Lazy import: keeps this module bpy-free at import time.
    from veilbreakers_terrain.handlers import COMMAND_HANDLERS

    fn = COMMAND_HANDLERS.get(command)
    if fn is None:
        logger.warning(
            "blender_server.dispatch: command %r (from location %r) not in "
            "COMMAND_HANDLERS",
            command,
            location_key,
        )
        return {
            "status": "error",
            "error": "unknown_command",
            "location": location_key,
            "command": command,
        }

    try:
        result = fn(params)
    except Exception as exc:  # noqa: BLE001 — dispatch boundary
        logger.exception(
            "blender_server.dispatch: handler %r raised for location %r",
            command,
            location_key,
        )
        return {
            "status": "error",
            "error": "handler_exception",
            "location": location_key,
            "command": command,
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }

    return {
        "status": "ok",
        "location": location_key,
        "command": command,
        "result": result,
    }


__all__ = [
    "_LOC_HANDLERS",
    "dispatch",
    "list_locations",
    "resolve_command",
]
