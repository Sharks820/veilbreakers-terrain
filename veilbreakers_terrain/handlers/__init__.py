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

    def _make_signature_handler(fn: Callable) -> Callable:
        import inspect

        sig = inspect.signature(fn)

        def _handler(params: dict) -> Any:
            payload = params or {}
            kwargs = {k: v for k, v in payload.items() if k in sig.parameters}
            return fn(**kwargs)

        return _handler

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
        "env_create_cave_entrance",
        f"{_pkg}.environment",
        "handle_create_cave_entrance",
    )
    _try_register(
        "env_run_terrain_pass",
        f"{_pkg}.environment",
        "handle_run_terrain_pass",
    )
    _try_register(
        "env_generate_terrain",
        f"{_pkg}.environment",
        "handle_generate_terrain",
    )
    _try_register(
        "env_generate_terrain_tile",
        f"{_pkg}.environment",
        "handle_generate_terrain_tile",
    )
    _try_register(
        "env_generate_world_terrain",
        f"{_pkg}.environment",
        "handle_generate_world_terrain",
    )
    _try_register(
        "env_stitch_terrain_edges",
        f"{_pkg}.environment",
        "handle_stitch_terrain_edges",
    )
    _try_register(
        "env_paint_terrain",
        f"{_pkg}.environment",
        "handle_paint_terrain",
    )
    _try_register(
        "env_carve_river",
        f"{_pkg}.environment",
        "handle_carve_river",
    )
    _try_register(
        "env_carve_water_basin",
        f"{_pkg}.environment",
        "handle_carve_water_basin",
    )
    _try_register(
        "env_create_water",
        f"{_pkg}.environment",
        "handle_create_water",
    )
    _try_register(
        "env_generate_road",
        f"{_pkg}.environment",
        "handle_generate_road",
    )
    _try_register(
        "env_export_heightmap",
        f"{_pkg}.environment",
        "handle_export_heightmap",
    )
    _try_register(
        "env_export_unity_bundle",
        f"{_pkg}.environment",
        "handle_export_unity_bundle",
    )
    _try_register(
        "env_generate_multi_biome_world",
        f"{_pkg}.environment",
        "handle_generate_multi_biome_world",
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

    # terrain_features.py — pure terrain archetype generators
    try:
        import importlib as _il_features
        _features = _il_features.import_module(f"{_pkg}.terrain_features")
        handlers["env_generate_canyon"] = _make_signature_handler(
            _features.generate_canyon
        )
        handlers["env_generate_cliff_face"] = _make_signature_handler(
            _features.generate_cliff_face
        )
        handlers["env_generate_swamp_terrain"] = _make_signature_handler(
            _features.generate_swamp_terrain
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_features handlers: %r",
            exc,
        )

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
            sun_direction = params.get("sun_direction", (0.5, -0.5, -0.7))
            return _li.compute_light_placements(
                props,
                sun_direction=sun_direction,
            )

        def _handle_merge_lights(params: dict) -> list:
            return _li.merge_nearby_lights(params.get("lights", []))

        def _handle_light_budget(params: dict) -> dict:
            return _li.compute_light_budget(params.get("lights", []))

        def _handle_compute_probe_placements(params: dict) -> list:
            import numpy as _np
            height_raw = params.get("height")
            if height_raw is None:
                return []
            height = _np.asarray(height_raw, dtype=_np.float64)
            water_raw = params.get("water_surface")
            water = _np.asarray(water_raw, dtype=_np.float64) if water_raw is not None else None
            return _li.compute_probe_placements(
                height,
                cell_size=float(params.get("cell_size", 1.0)),
                world_origin_x=float(params.get("world_origin_x", 0.0)),
                world_origin_y=float(params.get("world_origin_y", 0.0)),
                water_surface=water,
                feature_positions=params.get("feature_positions"),
                max_probes=int(params.get("max_probes", 16)),
                min_probe_spacing_m=float(params.get("min_probe_spacing_m", 20.0)),
                height_weight=float(params.get("height_weight", 1.0)),
                water_weight=float(params.get("water_weight", 1.5)),
                feature_weight=float(params.get("feature_weight", 2.0)),
            )

        handlers["env_compute_light_placements"] = _handle_compute_light_placements
        handlers["env_merge_lights"] = _handle_merge_lights
        handlers["env_light_budget"] = _handle_light_budget
        handlers["env_compute_probe_placements"] = _handle_compute_probe_placements
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
                str(params.get("side", "above")),
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

    # ------------------------------------------------------------------
    # terrain_live_preview.py — LivePreviewSession for interactive editing
    # (Bundle M). Exposes apply/snapshot/current-state via the MCP bridge.
    # We hold a single module-level session, lazily built on first call.
    # ------------------------------------------------------------------
    try:
        _lp = _il.import_module(f"{_pkg}.terrain_live_preview")

        _LP_STATE: Dict[str, Any] = {"session": None}

        def _get_or_build_session(params: dict):
            """Return the live-preview session, building it lazily."""
            sess = _LP_STATE.get("session")
            if sess is None:
                # Caller must pass a ``controller`` object in params; this
                # handler is a no-op for environments lacking an active
                # controller (Blender-side wires one in).
                controller = (params or {}).get("controller")
                if controller is None:
                    return None
                sess = _lp.LivePreviewSession(controller=controller)
                _LP_STATE["session"] = sess
            return sess

        def _handle_terrain_preview_apply(params: dict) -> dict:
            sess = _get_or_build_session(params)
            if sess is None:
                return {"status": "error", "error": "no_active_controller"}
            edit = (params or {}).get("edit") or {}
            hash_after = sess.apply_edit(edit)
            return {"status": "ok", "hash_after": hash_after,
                    "history_length": len(sess.history)}

        def _handle_terrain_preview_state(params: dict) -> dict:
            sess = _get_or_build_session(params)
            if sess is None:
                return {"status": "error", "error": "no_active_controller"}
            return {
                "status": "ok",
                "current_hash": sess.current_hash(),
                "history_length": len(sess.history),
            }

        def _handle_terrain_preview_reset(params: dict) -> dict:
            _LP_STATE["session"] = None
            return {"status": "ok", "reset": True}

        def _handle_terrain_preview_diff(params: dict) -> dict:
            sess = _get_or_build_session(params)
            if sess is None:
                return {"status": "error", "error": "no_active_controller"}
            hash_before = (params or {}).get("hash_before")
            hash_after = (params or {}).get("hash_after", sess.current_hash())
            if hash_before is None:
                history = getattr(sess, "history", [])
                if len(history) >= 2:
                    hash_before = history[-2].get("hash_after") or history[-2].get("hash")
                else:
                    return {"status": "error", "error": "missing_hash_before"}
            return {"status": "ok", **sess.diff_preview(str(hash_before), str(hash_after))}

        def _handle_terrain_preview_render_thumbnail(params: dict) -> dict:
            sess = _get_or_build_session(params)
            if sess is None:
                return {"status": "error", "error": "no_active_controller"}
            path = (params or {}).get("path")
            if not path:
                return {"status": "error", "error": "missing_path"}
            view = str((params or {}).get("view", "top"))
            rendered = sess.render_thumbnail_png(str(path), view=view)
            if isinstance(rendered, str) and rendered.startswith("ERROR:"):
                return {"status": "error", "error": "render_failed", "message": rendered}
            return {"status": "ok", "path": str(rendered), "view": view}

        handlers["terrain_preview_apply"] = _handle_terrain_preview_apply
        handlers["terrain_preview_state"] = _handle_terrain_preview_state
        handlers["terrain_preview_reset"] = _handle_terrain_preview_reset
        handlers["terrain_preview_diff"] = _handle_terrain_preview_diff
        handlers["terrain_preview_render_thumbnail"] = _handle_terrain_preview_render_thumbnail
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_live_preview handlers: %r",
            exc,
        )

    # ------------------------------------------------------------------
    # terrain_hot_reload.py — rule-module hot reload for Bundle M
    # ------------------------------------------------------------------
    try:
        _hr = _il.import_module(f"{_pkg}.terrain_hot_reload")

        _HR_STATE: Dict[str, Any] = {"watcher": None}

        def _get_watcher():
            w = _HR_STATE.get("watcher")
            if w is None:
                w = _hr.HotReloadWatcher()
                w.watch_biome_rules()
                w.watch_material_rules()
                _HR_STATE["watcher"] = w
            return w

        def _handle_hot_reload_start(params: dict) -> dict:
            w = _get_watcher()
            return {"status": "ok", "watched": list(w.watched_modules)}

        def _handle_hot_reload_stop(params: dict) -> dict:
            _HR_STATE["watcher"] = None
            return {"status": "ok", "stopped": True}

        def _handle_hot_reload_check(params: dict) -> dict:
            w = _get_watcher()
            reloaded = w.check_and_reload()
            return {"status": "ok", "reloaded": reloaded}

        handlers["terrain_hot_reload_start"] = _handle_hot_reload_start
        handlers["terrain_hot_reload_stop"] = _handle_hot_reload_stop
        handlers["terrain_hot_reload_check"] = _handle_hot_reload_check
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_hot_reload handlers: %r",
            exc,
        )

    # ------------------------------------------------------------------
    # Bundle R observation surfaces: scene read + viewport sync
    # ------------------------------------------------------------------
    try:
        _sr = _il.import_module(f"{_pkg}.terrain_scene_read")
        handlers["terrain_capture_scene_read"] = _sr.handle_capture_scene_read
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_scene_read handler: %r",
            exc,
        )

    try:
        _vs = _il.import_module(f"{_pkg}.terrain_viewport_sync")
        from .terrain_semantics import BBox as _BBox

        def _coerce_bbox(raw):
            if isinstance(raw, _BBox):
                return raw
            if isinstance(raw, dict):
                return _BBox(
                    min_x=float(raw.get("min_x", 0.0)),
                    min_y=float(raw.get("min_y", 0.0)),
                    max_x=float(raw.get("max_x", 0.0)),
                    max_y=float(raw.get("max_y", 0.0)),
                )
            if isinstance(raw, (list, tuple)) and len(raw) == 4:
                return _BBox(
                    min_x=float(raw[0]),
                    min_y=float(raw[1]),
                    max_x=float(raw[2]),
                    max_y=float(raw[3]),
                )
            return None

        def _serialize_vantage(vantage) -> dict:
            return {
                "camera_position": list(vantage.camera_position),
                "camera_direction": list(vantage.camera_direction),
                "camera_up": list(vantage.camera_up),
                "focal_point": list(vantage.focal_point),
                "fov": float(vantage.fov),
                "visible_bounds": list(vantage.visible_bounds.to_tuple()),
                "captured_timestamp": float(vantage.captured_timestamp),
                "view_matrix_hash": str(vantage.view_matrix_hash),
            }

        def _coerce_vantage(raw):
            if isinstance(raw, _vs.ViewportVantage):
                return raw
            if not isinstance(raw, dict):
                return None
            bounds = _coerce_bbox(raw.get("visible_bounds"))
            if bounds is None:
                return None
            return _vs.ViewportVantage(
                camera_position=tuple(float(x) for x in raw.get("camera_position", (0.0, -20.0, 12.0))),
                camera_direction=tuple(float(x) for x in raw.get("camera_direction", (0.0, 1.0, 0.0))),
                camera_up=tuple(float(x) for x in raw.get("camera_up", (0.0, 0.0, 1.0))),
                focal_point=tuple(float(x) for x in raw.get("focal_point", (0.0, 0.0, 0.0))),
                fov=float(raw.get("fov", 0.9)),
                visible_bounds=bounds,
                captured_timestamp=float(raw.get("captured_timestamp", 0.0)),
                view_matrix_hash=str(raw.get("view_matrix_hash", "")),
            )

        def _handle_read_viewport_vantage(params: dict) -> dict:
            bounds = _coerce_bbox((params or {}).get("visible_bounds"))
            vantage = _vs.read_user_vantage(
                camera_position=tuple((params or {}).get("camera_position", (0.0, -20.0, 12.0))),
                focal_point=tuple((params or {}).get("focal_point", (0.0, 0.0, 0.0))),
                up=tuple((params or {}).get("up", (0.0, 0.0, 1.0))),
                fov=float((params or {}).get("fov", 0.9)),
                visible_bounds=bounds,
            )
            return {"status": "ok", "vantage": _serialize_vantage(vantage)}

        def _handle_assert_vantage_fresh(params: dict) -> dict:
            vantage = _coerce_vantage((params or {}).get("vantage"))
            if vantage is None:
                return {"status": "error", "error": "missing_vantage"}
            try:
                _vs.assert_vantage_fresh(
                    vantage,
                    max_age_seconds=float((params or {}).get("max_age_seconds", 300.0)),
                )
            except _vs.ViewportStale as exc:
                return {"status": "error", "error": "viewport_stale", "message": str(exc)}
            return {"status": "ok", "fresh": True}

        def _handle_is_in_frustum(params: dict) -> dict:
            vantage = _coerce_vantage((params or {}).get("vantage"))
            if vantage is None:
                return {"status": "error", "error": "missing_vantage"}
            world_position = tuple(float(x) for x in (params or {}).get("world_position", (0.0, 0.0, 0.0)))
            return {
                "status": "ok",
                "world_position": list(world_position),
                "in_frustum": bool(_vs.is_in_frustum(world_position, vantage)),
            }

        handlers["terrain_read_viewport_vantage"] = _handle_read_viewport_vantage
        handlers["terrain_assert_vantage_fresh"] = _handle_assert_vantage_fresh
        handlers["terrain_is_in_frustum"] = _handle_is_in_frustum
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_viewport_sync handlers: %r",
            exc,
        )

    # ------------------------------------------------------------------
    # Bundle R addon health + Blender safety wrappers
    # ------------------------------------------------------------------
    try:
        _ah = _il.import_module(f"{_pkg}.terrain_addon_health")

        def _handle_addon_health(params: dict) -> dict:
            min_version = tuple((params or {}).get("min_version", _ah.TERRAIN_ADDON_MIN_VERSION))
            allow_missing = bool((params or {}).get("allow_missing", False))
            try:
                _ah.assert_addon_loaded()
                _ah.assert_addon_version_matches(min_version, allow_missing=allow_missing)
            except Exception as exc:
                return {
                    "status": "error",
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "min_version": list(min_version),
                }
            return {
                "status": "ok",
                "loaded": True,
                "stale": bool(_ah.detect_stale_addon()),
                "min_version": list(min_version),
            }

        def _handle_detect_stale_addon(params: dict) -> dict:
            return {"status": "ok", "stale": bool(_ah.detect_stale_addon())}

        def _handle_force_addon_reload(params: dict) -> dict:
            return {"status": "ok", "reloaded": bool(_ah.force_addon_reload())}

        handlers["terrain_check_addon_health"] = _handle_addon_health
        handlers["terrain_detect_stale_addon"] = _handle_detect_stale_addon
        handlers["terrain_force_addon_reload"] = _handle_force_addon_reload
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_addon_health handlers: %r",
            exc,
        )

    try:
        _bs = _il.import_module(f"{_pkg}.terrain_blender_safety")

        def _handle_boolean_safety_check(params: dict) -> dict:
            cutter_vert_count = int((params or {}).get("cutter_vert_count", 0))
            target_vert_count = int((params or {}).get("target_vert_count", 0))
            operation = str((params or {}).get("operation", "DIFFERENCE"))
            result = {
                "recommended_solver": _bs.recommend_boolean_solver(
                    cutter_vert_count,
                    target_vert_count,
                    operation=operation,
                    cutter_is_manifold=bool((params or {}).get("cutter_is_manifold", True)),
                    target_is_manifold=bool((params or {}).get("target_is_manifold", True)),
                ),
                "decimate_ratio": float(
                    _bs.decimate_to_safe_count(max(cutter_vert_count, target_vert_count))
                ),
            }
            try:
                _bs.assert_boolean_safe(
                    cutter_vert_count,
                    target_vert_count,
                    limit=int((params or {}).get("limit", _bs.BOOLEAN_DENSE_MESH_VERT_LIMIT)),
                )
            except _bs.BlenderBooleanUnsafe as exc:
                return {"status": "error", "safe": False, "message": str(exc), **result}
            return {"status": "ok", "safe": True, **result}

        def _handle_convert_yup_to_zup(params: dict) -> dict:
            position = tuple(float(x) for x in (params or {}).get("position", (0.0, 0.0, 0.0)))
            orientation = tuple(float(x) for x in (params or {}).get("orientation", (0.0, 0.0, 0.0)))
            converted_pos, converted_ori = _bs.convert_y_up_to_z_up(
                position,
                orientation,
                str((params or {}).get("euler_order", "XYZ")),
            )
            return {
                "status": "ok",
                "position": list(converted_pos),
                "orientation": list(converted_ori),
            }

        def _handle_clamp_screenshot_size(params: dict) -> dict:
            requested = int((params or {}).get("requested", (params or {}).get("size", _bs.BLENDER_SCREENSHOT_MAX_SIZE)))
            return {
                "status": "ok",
                "requested": requested,
                "clamped": int(_bs.clamp_screenshot_size(requested)),
            }

        handlers["terrain_boolean_safety_check"] = _handle_boolean_safety_check
        handlers["terrain_convert_yup_to_zup"] = _handle_convert_yup_to_zup
        handlers["terrain_clamp_screenshot_size"] = _handle_clamp_screenshot_size
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_blender_safety handlers: %r",
            exc,
        )

    # ------------------------------------------------------------------
    # terrain_performance_report.py — scene-wide perf rollup (Addendum 3.B.4)
    # Prevents Blender crashes by capping triangle/instance/draw-call budgets.
    # ------------------------------------------------------------------
    try:
        _pr = _il.import_module(f"{_pkg}.terrain_performance_report")

        def _handle_performance_report(params: dict) -> dict:
            stack = (params or {}).get("mask_stack")
            budgets = (params or {}).get("budgets")
            report = _pr.collect_performance_report(stack, budgets=budgets)
            return _pr.serialize_performance_report(report)

        handlers["terrain_performance_report"] = _handle_performance_report
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_performance_report handler: %r",
            exc,
        )

    # ------------------------------------------------------------------
    # terrain_navmesh_export.py — navmesh JSON export for Unity consumption
    # ------------------------------------------------------------------
    try:
        _nm = _il.import_module(f"{_pkg}.terrain_navmesh_export")

        def _handle_navmesh_export(params: dict) -> dict:
            from pathlib import Path as _Path
            stack = (params or {}).get("mask_stack")
            output_path = (params or {}).get("output_path")
            if stack is None or output_path is None:
                return {
                    "status": "error",
                    "error": "missing_params",
                    "required": ["mask_stack", "output_path"],
                }
            descriptor = _nm.export_navmesh_json(stack, _Path(output_path))
            return {"status": "ok", "descriptor": descriptor,
                    "output_path": str(output_path)}

        handlers["terrain_navmesh_export"] = _handle_navmesh_export
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_navmesh_export handler: %r",
            exc,
        )

    # ------------------------------------------------------------------
    # terrain_validation.py — full 10-validator suite (Bundle D)
    # ------------------------------------------------------------------
    try:
        _tv = _il.import_module(f"{_pkg}.terrain_validation")

        def _handle_validation(params: dict) -> dict:
            stack = (params or {}).get("mask_stack")
            intent = (params or {}).get("intent")
            if stack is None or intent is None:
                return {
                    "status": "error",
                    "error": "missing_params",
                    "required": ["mask_stack", "intent"],
                }
            report = _tv.run_validation_suite(stack, intent)
            return {
                "status": report.status,
                "hard_count": len(report.hard_issues),
                "soft_count": len(report.soft_issues),
                "info_count": len(report.info_issues),
                "metrics": dict(report.metrics),
                "issues": [
                    {"code": i.code, "severity": i.severity, "message": i.message}
                    for i in report.all_issues
                ],
            }

        handlers["terrain_validation"] = _handle_validation
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_validation handler: %r",
            exc,
        )

    # ------------------------------------------------------------------
    # terrain_quality_profiles.py — profile load/list/apply
    # ------------------------------------------------------------------
    try:
        _qp = _il.import_module(f"{_pkg}.terrain_quality_profiles")

        def _handle_load_quality_profile(params: dict) -> dict:
            name = (params or {}).get("name", "production")
            try:
                profile = _qp.load_quality_profile(name)
            except KeyError as err:
                return {"status": "error", "error": "unknown_profile",
                        "name": name, "message": str(err)}
            except _qp.PresetLocked as err:
                return {"status": "error", "error": "preset_locked",
                        "name": name, "message": str(err)}
            from dataclasses import asdict as _asdict
            payload = _asdict(profile)
            # ErosionStrategy enums don't JSON-serialise — coerce to value.
            strat = payload.get("erosion_strategy")
            if hasattr(strat, "value"):
                payload["erosion_strategy"] = strat.value
            return {"status": "ok", "profile": payload}

        def _handle_list_quality_profiles(params: dict) -> dict:
            return {"status": "ok", "profiles": _qp.list_quality_profiles()}

        def _handle_apply_quality_profile(params: dict) -> dict:
            """Apply a named profile to a target intent/state.

            Returns the resolved profile so the caller (Blender) can wire
            the values into the active ``TerrainIntentState``.
            """
            return _handle_load_quality_profile(params)

        handlers["terrain_load_quality_profile"] = _handle_load_quality_profile
        handlers["terrain_list_quality_profiles"] = _handle_list_quality_profiles
        handlers["terrain_apply_quality_profile"] = _handle_apply_quality_profile
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "COMMAND_HANDLERS: failed to register terrain_quality_profiles handlers: %r",
            exc,
        )

    # ------------------------------------------------------------------
    # environment_scatter.py — scatter vegetation + props (Fix 9.7 / BUG-S9-015)
    # ------------------------------------------------------------------
    _try_register(
        "scatter_vegetation",
        f"{_pkg}.environment_scatter",
        "handle_scatter_vegetation",
    )
    _try_register(
        "scatter_props",
        f"{_pkg}.environment_scatter",
        "handle_scatter_props",
    )
    _try_register(
        "scatter_create_breakable",
        f"{_pkg}.environment_scatter",
        "handle_create_breakable",
    )

    # vegetation_system.py — biome vegetation scatter
    _try_register(
        "scatter_biome_vegetation",
        f"{_pkg}.vegetation_system",
        "scatter_biome_vegetation",
    )

    # ------------------------------------------------------------------
    # Additional public Blender utility handlers
    # ------------------------------------------------------------------
    _try_register(
        "material_create_procedural",
        f"{_pkg}.procedural_materials",
        "handle_create_procedural_material",
    )
    _try_register(
        "terrain_generate_lods",
        f"{_pkg}.lod_pipeline",
        "handle_generate_lods",
    )
    _try_register(
        "terrain_setup_biome",
        f"{_pkg}.terrain_materials",
        "handle_setup_terrain_biome",
    )
    _try_register(
        "terrain_sculpt",
        f"{_pkg}.terrain_sculpt",
        "handle_sculpt_terrain",
    )

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
        "compute_probe_placements",
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
    "compute_probe_placements",
    "LIGHT_PROP_MAP", "FLICKER_PRESETS",
    # atmospheric_volumes
    "ATMOSPHERIC_VOLUMES", "BIOME_ATMOSPHERE_RULES", "compute_atmospheric_placements",
    "compute_volume_mesh_spec", "estimate_atmosphere_performance",
]
