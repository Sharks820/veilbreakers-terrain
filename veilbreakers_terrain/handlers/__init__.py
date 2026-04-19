"""veilbreakers_terrain.handlers — terrain handler registration surface.

The 105 handler modules live alongside this file. Registration is delegated
to ``terrain_master_registrar.register_all_terrain_passes``; this module just
re-exports a slim ``register_all()`` that the toolkit's preflight hook (D-07)
and downstream tooling can call without knowing the registrar's internals.

``COMMAND_HANDLERS`` is the canonical MCP/addon dispatch table mapping
command-name strings to callable handler functions. Every handler that needs
to be reachable at runtime must have an entry here.
"""

from __future__ import annotations

from typing import Any, Callable, Dict


def register_all(strict: bool = False) -> Any:
    """Register all terrain passes.

    Replaces the legacy
    ``blender_addon.handlers.terrain_master_registrar.register_all_terrain_passes``
    call site used by the toolkit prior to Phase 50.

    Parameters
    ----------
    strict:
        If True, raise on first registration error. If False (default),
        swallow per-pass failures and log — matches legacy behaviour.

    Returns
    -------
    Whatever ``register_all_terrain_passes`` returns (currently a
    registration report; see ``terrain_master_registrar``).
    """
    # Lazy import so importing this package does not require bpy at collect-time.
    from .terrain_master_registrar import register_all_terrain_passes

    return register_all_terrain_passes(strict=strict)


def _build_command_handlers() -> Dict[str, Callable]:
    """Build and return the COMMAND_HANDLERS dispatch table.

    Imports are deferred so that loading this package never pulls in bpy
    at collection time.  Each handler is imported from its canonical module;
    any module that fails to import (e.g. missing optional dependency) is
    skipped with a warning rather than killing the whole table.
    """
    import logging
    _log = logging.getLogger(__name__)

    handlers: Dict[str, Callable] = {}

    def _try_register(key: str, module_path: str, fn_name: str) -> None:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            fn = getattr(mod, fn_name)
            handlers[key] = fn
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "COMMAND_HANDLERS: failed to register %r from %s.%s: %r",
                key, module_path, fn_name, exc,
            )

    _pkg = "veilbreakers_terrain.handlers"

    # ------------------------------------------------------------------
    # terrain_advanced.py — 6 previously-orphaned handlers (GAP-44/45/46/
    # 28/30/flatten_zone).  Wired here to make them reachable at runtime.
    # ------------------------------------------------------------------
    _try_register(
        "terrain_spline_deform",
        f"{_pkg}.terrain_advanced",
        "handle_spline_deform",
    )
    _try_register(
        "terrain_layers",
        f"{_pkg}.terrain_advanced",
        "handle_terrain_layers",
    )
    _try_register(
        "terrain_erosion_paint",
        f"{_pkg}.terrain_advanced",
        "handle_erosion_paint",
    )
    _try_register(
        "terrain_stamp",
        f"{_pkg}.terrain_advanced",
        "handle_terrain_stamp",
    )
    _try_register(
        "terrain_snap_to_terrain",
        f"{_pkg}.terrain_advanced",
        "handle_snap_to_terrain",
    )
    _try_register(
        "terrain_flatten_zone",
        f"{_pkg}.terrain_advanced",
        "handle_terrain_flatten_zone",
    )

    # ------------------------------------------------------------------
    # terrain_caves.py
    # ------------------------------------------------------------------
    _try_register(
        "terrain_generate_cave",
        f"{_pkg}.terrain_caves",
        "handle_generate_cave",
    )

    # ------------------------------------------------------------------
    # environment.py — waterfall + run_terrain_pass
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # road_network.py — road network generation
    # ------------------------------------------------------------------
    _try_register(
        "env_compute_road_network",
        f"{_pkg}.road_network",
        "handle_compute_road_network",
    )

    _try_register(
        "env_generate_waterfall",
        f"{_pkg}.environment",
        "handle_generate_waterfall",
    )
    _try_register(
        "env_run_terrain_pass",
        f"{_pkg}.environment",
        "handle_run_terrain_pass",
    )

    # ------------------------------------------------------------------
    # coastline.py — coastline generation
    # ------------------------------------------------------------------
    try:
        import importlib as _il_coast
        _coast = _il_coast.import_module(f"{_pkg}.coastline")
        _gen_coastline = _coast.generate_coastline

        def _handle_generate_coastline(params: dict) -> dict:
            return _gen_coastline(
                length=params.get("length", 200.0),
                width=params.get("width", 50.0),
                style=params.get("style", "rocky"),
                resolution=params.get("resolution", 64),
                seed=params.get("seed", 42),
            )

        handlers["env_generate_coastline"] = _handle_generate_coastline
    except Exception as exc:  # noqa: BLE001
        _log.warning("COMMAND_HANDLERS: failed to register coastline handler: %r", exc)

    # Fail-closed stubs for unimplemented terrain generators
    def _fail_closed(command_name: str) -> Callable:
        def _handler(params: dict) -> dict:
            return {"status": "error", "fail_closed": True, "command": command_name}
        return _handler

    handlers["env_generate_canyon"] = _fail_closed("env_generate_canyon")
    handlers["env_generate_cliff_face"] = _fail_closed("env_generate_cliff_face")
    handlers["env_generate_swamp_terrain"] = _fail_closed("env_generate_swamp_terrain")

    # ------------------------------------------------------------------
    # world_map.py — world map generation (Task #45-46)
    # ------------------------------------------------------------------
    try:
        import importlib as _il
        _wm = _il.import_module(f"{_pkg}.world_map")
        _generate_world_map = _wm.generate_world_map
        _world_map_to_dict = _wm.world_map_to_dict

        def _handle_generate_world_map(params: dict) -> dict:
            wm = _generate_world_map(
                num_regions=params.get("num_regions", 6),
                map_size=params.get("map_size", 2000.0),
                seed=params.get("seed", 42),
                min_pois=params.get("min_pois", 0),
            )
            return _world_map_to_dict(wm)

        handlers["world_generate_world_map"] = _handle_generate_world_map
    except Exception as exc:  # noqa: BLE001
        _log.warning("COMMAND_HANDLERS: failed to register world_map handlers: %r", exc)

    # ------------------------------------------------------------------
    # light_integration.py — light placement (Task #50)
    # ------------------------------------------------------------------
    try:
        _li = _il.import_module(f"{_pkg}.light_integration")

        def _handle_compute_light_placements(params: dict) -> list:
            props = params.get("props") or params.get("prop_positions") or []
            return _li.compute_light_placements(props)

        def _handle_merge_lights(params: dict) -> list:
            return _li.merge_nearby_lights(params.get("lights", []))

        def _handle_light_budget(params: dict) -> dict:
            return _li.compute_light_budget(params.get("lights", []))

        handlers["env_compute_light_placements"] = _handle_compute_light_placements
        handlers["env_merge_lights"] = _handle_merge_lights
        handlers["env_light_budget"] = _handle_light_budget
    except Exception as exc:  # noqa: BLE001
        _log.warning("COMMAND_HANDLERS: failed to register light_integration handlers: %r", exc)

    # ------------------------------------------------------------------
    # atmospheric_volumes.py — atmospheric placements (Task #51)
    # ------------------------------------------------------------------
    try:
        _av = _il.import_module(f"{_pkg}.atmospheric_volumes")

        def _handle_compute_atmospheric_placements(params: dict) -> list:
            return _av.compute_atmospheric_placements(
                biome_name=params.get("biome_name", "dark_forest"),
                area_bounds=tuple(params.get("area_bounds", [0, 0, 100, 100])),
                seed=params.get("seed", 42),
            )

        def _handle_volume_mesh_spec(params: dict) -> dict:
            return _av.compute_volume_mesh_spec(params.get("volume_type", "ground_fog"))

        def _handle_atmosphere_performance(params: dict) -> dict:
            return _av.estimate_atmosphere_performance(params.get("placements", []))

        handlers["env_compute_atmospheric_placements"] = _handle_compute_atmospheric_placements
        handlers["env_volume_mesh_spec"] = _handle_volume_mesh_spec
        handlers["env_atmosphere_performance"] = _handle_atmosphere_performance
    except Exception as exc:  # noqa: BLE001
        _log.warning("COMMAND_HANDLERS: failed to register atmospheric_volumes handlers: %r", exc)

    # ------------------------------------------------------------------
    # mesh.py — precision mesh editing helpers (GAP-01..GAP-05)
    # Public surface uses a leading-underscore naming convention (module
    # convention, not visibility), so we reach into the module directly
    # rather than relying on __all__.
    # ------------------------------------------------------------------
    try:
        _mesh = _il.import_module(f"{_pkg}.mesh")

        def _handle_select_by_box(params: dict) -> list:
            return _mesh._select_by_box(
                params.get("verts", []),
                tuple(params.get("min_pt", (0.0, 0.0, 0.0))),
                tuple(params.get("max_pt", (0.0, 0.0, 0.0))),
            )

        def _handle_select_by_sphere(params: dict) -> list:
            return _mesh._select_by_sphere(
                params.get("verts", []),
                tuple(params.get("center", (0.0, 0.0, 0.0))),
                float(params.get("radius", 0.0)),
            )

        def _handle_select_by_plane(params: dict) -> list:
            return _mesh._select_by_plane(
                params.get("verts", []),
                tuple(params.get("plane_point", (0.0, 0.0, 0.0))),
                tuple(params.get("plane_normal", (0.0, 0.0, 1.0))),
            )

        def _handle_parse_selection_criteria(params: dict) -> dict:
            return _mesh._parse_selection_criteria(
                params.get("criteria", {}),
                strict=bool(params.get("strict", False)),
            )

        handlers["mesh_select_by_box"] = _handle_select_by_box
        handlers["mesh_select_by_sphere"] = _handle_select_by_sphere
        handlers["mesh_select_by_plane"] = _handle_select_by_plane
        handlers["mesh_parse_selection_criteria"] = _handle_parse_selection_criteria
    except Exception as exc:  # noqa: BLE001
        _log.warning("COMMAND_HANDLERS: failed to register mesh handlers: %r", exc)

    # ------------------------------------------------------------------
    # mesh_smoothing.py — Taubin smoothing (session-6)
    # ------------------------------------------------------------------
    try:
        _ms = _il.import_module(f"{_pkg}.mesh_smoothing")

        def _handle_smooth_assembled_mesh(params: dict) -> list:
            return _ms.smooth_assembled_mesh(
                params.get("verts", []),
                params.get("faces", []),
                smooth_iterations=int(params.get("smooth_iterations", 3)),
                blend_factor=float(params.get("blend_factor", 0.5)),
                taubin_mu=float(params.get("taubin_mu", -0.53)),
            )

        handlers["mesh_smooth_assembled"] = _handle_smooth_assembled_mesh
    except Exception as exc:  # noqa: BLE001
        _log.warning("COMMAND_HANDLERS: failed to register mesh_smoothing handlers: %r", exc)

    # ------------------------------------------------------------------
    # vertex_paint_live.py — live vertex paint brush helpers (GAP-06/07/08)
    # ------------------------------------------------------------------
    try:
        _vpl = _il.import_module(f"{_pkg}.vertex_paint_live")

        def _handle_compute_paint_weights(params: dict) -> list:
            return _vpl.compute_paint_weights(
                params.get("verts", []),
                tuple(params.get("brush_center", (0.0, 0.0, 0.0))),
                float(params.get("radius", 0.0)),
                str(params.get("falloff_mode", "SMOOTH")),
            )

        def _handle_compute_paint_weights_uv(params: dict) -> list:
            return _vpl.compute_paint_weights_uv(
                params.get("uvs", []),
                tuple(params.get("brush_center_uv", (0.0, 0.0))),
                float(params.get("radius", 0.0)),
                str(params.get("falloff_mode", "SMOOTH")),
            )

        def _handle_blend_colors(params: dict) -> tuple:
            return _vpl.blend_colors(
                tuple(params.get("existing", (0.0, 0.0, 0.0, 1.0))),
                tuple(params.get("new_color", (0.0, 0.0, 0.0, 1.0))),
                float(params.get("strength", 1.0)),
                str(params.get("mode", "MIX")),
            )

        handlers["vertex_paint_compute_weights"] = _handle_compute_paint_weights
        handlers["vertex_paint_compute_weights_uv"] = _handle_compute_paint_weights_uv
        handlers["vertex_paint_blend_colors"] = _handle_blend_colors
    except Exception as exc:  # noqa: BLE001
        _log.warning("COMMAND_HANDLERS: failed to register vertex_paint_live handlers: %r", exc)

    # ------------------------------------------------------------------
    # autonomous_loop.py — mesh quality evaluation + fix-action dispatch
    # (GAP-17). Public surface: evaluate_mesh_quality, select_fix_action.
    # ------------------------------------------------------------------
    try:
        _al = _il.import_module(f"{_pkg}.autonomous_loop")

        def _handle_evaluate_mesh_quality(params: dict) -> dict:
            return _al.evaluate_mesh_quality(
                params.get("verts", []),
                params.get("faces", []),
                uvs=params.get("uvs"),
            )

        def _handle_select_fix_action(params: dict):
            return _al.select_fix_action(
                params.get("quality", {}),
                params.get("targets", {}),
                params.get("actions", []),
            )

        handlers["autonomous_evaluate_mesh_quality"] = _handle_evaluate_mesh_quality
        handlers["autonomous_select_fix_action"] = _handle_select_fix_action
    except Exception as exc:  # noqa: BLE001
        _log.warning("COMMAND_HANDLERS: failed to register autonomous_loop handlers: %r", exc)

    # ------------------------------------------------------------------
    # weathering.py — surface weathering colors + structural settling
    # ------------------------------------------------------------------
    try:
        _weath = _il.import_module(f"{_pkg}.weathering")

        def _handle_compute_weathered_vertex_colors(params: dict) -> list:
            return _weath.compute_weathered_vertex_colors(
                params.get("mesh_data", {}),
                tuple(params.get("base_color", (0.5, 0.5, 0.5, 1.0))),
                preset_name=str(params.get("preset_name", "medium")),
            )

        def _handle_apply_structural_settling(params: dict) -> list:
            return _weath.apply_structural_settling(
                params.get("verts", []),
                strength=float(params.get("strength", 0.01)),
                seed=int(params.get("seed", 42)),
            )

        handlers["weathering_compute_vertex_colors"] = _handle_compute_weathered_vertex_colors
        handlers["weathering_apply_structural_settling"] = _handle_apply_structural_settling
    except Exception as exc:  # noqa: BLE001
        _log.warning("COMMAND_HANDLERS: failed to register weathering handlers: %r", exc)

    # ------------------------------------------------------------------
    # animation_environment.py — 27 environment keyframe generators.
    # Wire the unified dispatcher (generate_env_keyframes) plus every
    # individual generate_*_keyframes function, so callers can either
    # dispatch by env_type string or invoke a specific generator directly.
    # ------------------------------------------------------------------
    try:
        _ae = _il.import_module(f"{_pkg}.animation_environment")

        def _handle_generate_env_keyframes(params: dict) -> list:
            return _ae.generate_env_keyframes(params)

        handlers["animation_generate_env_keyframes"] = _handle_generate_env_keyframes

        # Wire every public generate_*_keyframes function listed in __all__.
        import inspect as _inspect

        def _make_generator_handler(fn):
            sig = _inspect.signature(fn)

            def _h(params: dict):
                kwargs = {k: v for k, v in (params or {}).items() if k in sig.parameters}
                return fn(**kwargs)
            return _h

        for _export_name in getattr(_ae, "__all__", ()):
            if not (
                _export_name.startswith("generate_")
                and _export_name.endswith("_keyframes")
                and _export_name != "generate_env_keyframes"
            ):
                continue
            _fn = getattr(_ae, _export_name, None)
            if _fn is None or not callable(_fn):
                continue
            # Command key: animation_door_open, animation_fire_flicker, etc.
            _cmd_suffix = _export_name[len("generate_"):-len("_keyframes")]
            handlers[f"animation_{_cmd_suffix}"] = _make_generator_handler(_fn)
    except Exception as exc:  # noqa: BLE001
        _log.warning("COMMAND_HANDLERS: failed to register animation_environment handlers: %r", exc)

    return handlers


# Build the table at import time (deferred internally via importlib).
COMMAND_HANDLERS: Dict[str, Callable] = _build_command_handlers()


# ---------------------------------------------------------------------------
# Module-level lazy exports from world_map, light_integration, atmospheric_volumes
# ---------------------------------------------------------------------------

def __getattr__(name: str):  # noqa: N807
    """Lazy top-level attribute access for handler submodule symbols."""
    _WORLD_MAP_EXPORTS = frozenset({
        "generate_world_map", "place_landmarks", "generate_storytelling_scene",
        "world_map_to_dict", "BIOME_TYPES", "POI_TYPES", "LANDMARK_TYPES",
        "STORYTELLING_PATTERNS",
    })
    _LIGHT_EXPORTS = frozenset({
        "compute_light_placements", "merge_nearby_lights", "compute_light_budget",
        "LIGHT_PROP_MAP", "FLICKER_PRESETS",
    })
    _ATMO_EXPORTS = frozenset({
        "ATMOSPHERIC_VOLUMES", "BIOME_ATMOSPHERE_RULES", "compute_atmospheric_placements",
        "compute_volume_mesh_spec", "estimate_atmosphere_performance",
    })

    import importlib as _il2
    _pkg2 = "veilbreakers_terrain.handlers"
    if name in _WORLD_MAP_EXPORTS:
        mod = _il2.import_module(f"{_pkg2}.world_map")
        return getattr(mod, name)
    if name in _LIGHT_EXPORTS:
        mod = _il2.import_module(f"{_pkg2}.light_integration")
        return getattr(mod, name)
    if name in _ATMO_EXPORTS:
        mod = _il2.import_module(f"{_pkg2}.atmospheric_volumes")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "register_all",
    "COMMAND_HANDLERS",
    # world_map
    "generate_world_map", "place_landmarks", "generate_storytelling_scene",
    "world_map_to_dict", "BIOME_TYPES", "POI_TYPES", "LANDMARK_TYPES",
    "STORYTELLING_PATTERNS",
    # light_integration
    "compute_light_placements", "merge_nearby_lights", "compute_light_budget",
    "LIGHT_PROP_MAP", "FLICKER_PRESETS",
    # atmospheric_volumes
    "ATMOSPHERIC_VOLUMES", "BIOME_ATMOSPHERE_RULES", "compute_atmospheric_placements",
    "compute_volume_mesh_spec", "estimate_atmosphere_performance",
]
