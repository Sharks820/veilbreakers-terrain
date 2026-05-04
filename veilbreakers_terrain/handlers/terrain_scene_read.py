"""Bundle R — capture_scene_read handler.

Produces ``TerrainSceneRead`` snapshots per §5.3 of the implementation
plan. Headless mode accepts supplied kwargs; real Blender would walk the
current scene via ``bpy.data``.

See Addendum 1.A.7.
"""

from __future__ import annotations

import importlib
import time
import weakref as _weakref
from collections.abc import Iterable, Mapping, Sequence as RuntimeSequence
from typing import Any, Optional, Sequence, Tuple, TypedDict, cast

from .terrain_semantics import (
    BBox,
    ChannelNotWrittenError,
    HeroFeatureRef,
    TerrainSceneRead,
    WaterfallChainRef,
)

Vec3 = Tuple[float, float, float]
AddonVersion = Tuple[int, int, int]


def _iter_objects(raw: object) -> Optional[Iterable[object]]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
        return None
    return cast(Iterable[object], raw)


def _to_float(raw: object) -> Optional[float]:
    try:
        return float(cast(Any, raw))
    except (TypeError, ValueError):
        return None


def _to_int(raw: object) -> Optional[int]:
    try:
        return int(cast(Any, raw))
    except (TypeError, ValueError):
        return None


class _LiveHeroFeature(TypedDict):
    id: object
    type: object
    location: Vec3
    name: object


class _LivePointFeature(TypedDict):
    name: object
    location: Vec3
    type: object


class _LiveScene(TypedDict, total=False):
    hero_features: list[_LiveHeroFeature]
    focal_point: Vec3
    focal_direction: Vec3
    waterfall_chains: list[_LivePointFeature]
    cave_candidates: list[_LivePointFeature]
    timestamp: str


def _coerce_vec3(raw: object) -> Optional[Vec3]:
    iterable = _iter_objects(raw)
    if iterable is None:
        return None
    values: list[float] = []
    for value in iterable:
        coerced = _to_float(value)
        if coerced is None:
            return None
        values.append(coerced)
        if len(values) == 3:
            break
    if len(values) != 3:
        return None
    return (values[0], values[1], values[2])


def _coerce_vec3_sequence(raw: object) -> tuple[Vec3, ...]:
    iterable = _iter_objects(raw)
    if iterable is None:
        return ()
    built: list[Vec3] = []
    for entry in iterable:
        vec = _coerce_vec3(entry)
        if vec is not None:
            built.append(vec)
    return tuple(built)


def _coerce_str_tuple(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    iterable = _iter_objects(raw)
    if iterable is None:
        return ()
    return tuple(str(value) for value in iterable if value is not None)


def _coerce_addon_version(raw: object) -> Optional[AddonVersion]:
    iterable = _iter_objects(raw)
    if iterable is None:
        return None
    values: list[int] = []
    for value in iterable:
        coerced = _to_int(value)
        if coerced is None:
            return None
        values.append(coerced)
        if len(values) == 3:
            break
    if len(values) != 3:
        return None
    return (values[0], values[1], values[2])


def _coerce_hero_feature_refs(raw: object) -> tuple[HeroFeatureRef, ...]:
    iterable = _iter_objects(raw)
    if iterable is None:
        return ()
    refs: list[HeroFeatureRef] = []
    for entry in iterable:
        if isinstance(entry, HeroFeatureRef):
            refs.append(entry)
        elif isinstance(entry, Mapping):
            entry_map = cast(Mapping[str, object], entry)
            loc = _coerce_vec3(
                entry_map.get("world_position", entry_map.get("location"))
            )
            if loc is None:
                continue
            feature_id = entry_map.get(
                "feature_id",
                entry_map.get("id", entry_map.get("name")),
            )
            if feature_id is None:
                continue
            object_name = entry_map.get("blender_object_name", entry_map.get("name"))
            refs.append(
                HeroFeatureRef(
                    feature_id=str(feature_id),
                    feature_kind=str(
                        entry_map.get("feature_kind", entry_map.get("type", "unknown"))
                    ),
                    world_position=loc,
                    blender_object_name=str(object_name) if object_name is not None else None,
                )
            )
    return tuple(refs)


def _coerce_waterfall_chain_refs(raw: object) -> tuple[WaterfallChainRef, ...]:
    iterable = _iter_objects(raw)
    if iterable is None:
        return ()
    refs: list[WaterfallChainRef] = []
    for entry in iterable:
        if isinstance(entry, WaterfallChainRef):
            refs.append(entry)
        elif isinstance(entry, Mapping):
            entry_map = cast(Mapping[str, object], entry)
            chain_id = entry_map.get("chain_id", entry_map.get("name"))
            if chain_id is None:
                continue
            fallback = _coerce_vec3(entry_map.get("location"))
            lip = _coerce_vec3(entry_map.get("lip_position")) or fallback
            pool = _coerce_vec3(entry_map.get("pool_position")) or fallback
            if lip is None or pool is None:
                continue
            drop_raw = entry_map.get("drop_height", 0.0)
            drop_height = _to_float(drop_raw) or 0.0
            refs.append(
                WaterfallChainRef(
                    chain_id=str(chain_id),
                    lip_position=lip,
                    pool_position=pool,
                    drop_height=drop_height,
                )
            )
    return tuple(refs)


def _walk_scene() -> _LiveScene:
    """Walk bpy.data to extract real scene state when running in Blender."""
    result: _LiveScene = {}

    try:
        bpy = cast(Any, importlib.import_module("bpy"))
        # Collect objects with vb_feature_id custom property
        hero_features: list[_LiveHeroFeature] = []
        for obj in bpy.data.objects:
            if "vb_feature_id" in obj:
                loc = _coerce_vec3(obj.location)
                if loc is None:
                    continue
                hero_features.append({
                    "id": obj["vb_feature_id"],
                    "type": obj.get("vb_feature_type", "unknown"),
                    "location": loc,
                    "name": obj.name,
                })
        result["hero_features"] = hero_features

        # Find focal point from active camera. Blender cameras look along
        # local -Z; matrix_world.col[2] is local +Z and points backward.
        cam = bpy.context.scene.camera
        if cam:
            backward = _coerce_vec3(cam.matrix_world.col[2][:3])
            loc = _coerce_vec3(cam.location)
            # Pytest's MagicMock bpy stubs evaluate truthy but do not expose
            # real 3D vectors. Treat that as headless/no-live-scene data.
            if backward is not None and loc is not None:
                forward = (-backward[0], -backward[1], -backward[2])
                result["focal_direction"] = forward
                result["focal_point"] = (
                    loc[0] + forward[0] * 10.0,
                    loc[1] + forward[1] * 10.0,
                    loc[2] + forward[2] * 10.0,
                )

        # Waterfall chain empties
        waterfall_chains: list[_LivePointFeature] = []
        for obj in bpy.data.objects:
            if obj.name.startswith("vb_waterfall_chain_"):
                loc = _coerce_vec3(obj.location)
                if loc is None:
                    continue
                waterfall_chains.append({
                    "name": obj.name,
                    "location": loc,
                    "type": "waterfall_chain",
                })
        result["waterfall_chains"] = waterfall_chains

        # Cave candidates
        cave_candidates: list[_LivePointFeature] = []
        for obj in bpy.data.objects:
            if obj.name.startswith("vb_cave_"):
                loc = _coerce_vec3(obj.location)
                if loc is None:
                    continue
                cave_candidates.append({
                    "name": obj.name,
                    "location": loc,
                    "type": obj.get("vb_cave_type", "unknown"),
                })
        result["cave_candidates"] = cave_candidates

        result["timestamp"] = bpy.data.scenes[0].name  # use scene name as identifier
    except ChannelNotWrittenError:
        raise  # Rule-1: phantom channel reads must propagate
    except (ImportError, AttributeError):
        pass  # bpy unavailable outside Blender — non-fatal for headless mode
    return result


def capture_scene_read(
    *,
    reviewer: str,
    focal_point_hint: Optional[Vec3] = None,
    major_landforms: Sequence[str] = (),
    hero_features_present: Sequence[HeroFeatureRef] = (),
    hero_features_missing: Sequence[str] = (),
    waterfall_chains: Sequence[WaterfallChainRef] = (),
    cave_candidates: Sequence[Vec3] = (),
    protected_zones_in_region: Sequence[str] = (),
    edit_scope: Optional[BBox] = None,
    success_criteria: Sequence[str] = ("scene_understood",),
    viewport_vantage: Optional[object] = None,
    addon_version: Optional[AddonVersion] = None,
    terrain_content_hash: Optional[str] = None,
    lockable_anchors: Sequence[str] = (),
) -> TerrainSceneRead:
    """Build a valid ``TerrainSceneRead`` snapshot.

    Rule 1 of the protocol requires one of these to exist before any
    mutation. In headless tests the caller supplies the content; real
    Blender would populate ``major_landforms`` by scanning ``bpy.data``,
    etc.

    The optional ``viewport_vantage``, ``addon_version``,
    ``terrain_content_hash``, and ``lockable_anchors`` parameters carry
    the Addendum 1.A.7 extended metadata. They are stashed onto the
    returned ``TerrainSceneRead`` via monkey-patch attributes so the
    frozen dataclass surface stays stable while new consumers can
    read them without another contract break.
    """
    # When running inside Blender, merge real scene state over kwargs.
    _live = _walk_scene()
    if _live:
        if focal_point_hint is None and "focal_point" in _live:
            focal_point_hint = _live["focal_point"]
        live_hero_features = _live.get("hero_features", ())
        if not hero_features_present and live_hero_features:
            # Convert raw dicts to HeroFeatureRef instances where possible
            _built: list[HeroFeatureRef] = []
            for _hf in live_hero_features:
                loc = _hf["location"]
                _built.append(
                    HeroFeatureRef(
                        feature_id=str(_hf["id"] or _hf["name"]),
                        feature_kind=str(_hf["type"]),
                        world_position=loc,
                        blender_object_name=str(_hf["name"]),
                    )
                )
            hero_features_present = _built
        live_waterfall_chains = _live.get("waterfall_chains", ())
        if not waterfall_chains and live_waterfall_chains:
            # Waterfall chains from scene are location-only empties; build
            # minimal WaterfallChainRef stubs so they are visible in the snapshot.
            _wf_built: list[WaterfallChainRef] = []
            for _wf in live_waterfall_chains:
                _loc = _wf["location"]
                _wf_built.append(
                    WaterfallChainRef(
                        chain_id=str(_wf["name"]),
                        lip_position=_loc,
                        pool_position=_loc,
                        drop_height=0.0,
                    )
                )
            waterfall_chains = _wf_built
        live_cave_candidates = _live.get("cave_candidates", ())
        if not cave_candidates and live_cave_candidates:
            cave_candidates = tuple(c["location"] for c in live_cave_candidates)

    focal = (
        focal_point_hint
        if focal_point_hint is not None
        else (0.0, 0.0, 0.0)
    )
    scope = edit_scope if edit_scope is not None else BBox(
        min_x=focal[0] - 25.0,
        min_y=focal[1] - 25.0,
        max_x=focal[0] + 25.0,
        max_y=focal[1] + 25.0,
    )
    # BUG-R8-A9-020: store Addendum 1.A.7 fields directly on the dataclass
    # instead of a sidecar id()-keyed dict (id() is reused after GC).
    sr = TerrainSceneRead(
        timestamp=time.time(),
        major_landforms=tuple(major_landforms),
        focal_point=focal,
        hero_features_present=tuple(hero_features_present),
        hero_features_missing=tuple(hero_features_missing),
        waterfall_chains=tuple(waterfall_chains),
        cave_candidates=tuple(cave_candidates),
        protected_zones_in_region=tuple(protected_zones_in_region),
        edit_scope=scope,
        success_criteria=tuple(success_criteria),
        reviewer=str(reviewer),
        addon_version=addon_version,
        lockable_anchors=tuple(lockable_anchors),
        extended_at=time.time(),
        terrain_content_hash=terrain_content_hash,
        focal_direction=_live.get("focal_direction"),
    )
    # Keep viewport_vantage in a WeakKeyDictionary sidecar — it is an
    # arbitrary object that may not be picklable, so it stays off the frozen
    # dataclass. The frozen dataclass is now weakly referenceable because it
    # has no __slots__.
    _VIEWPORT_VANTAGE[sr] = viewport_vantage
    return sr


# BUG-R8-A9-020: WeakKeyDictionary for the one non-serialisable field.
_VIEWPORT_VANTAGE: "_weakref.WeakKeyDictionary[TerrainSceneRead, Optional[object]]" = (
    _weakref.WeakKeyDictionary()
)


def get_extended_metadata(sr: TerrainSceneRead) -> dict[str, object]:
    """Return the Addendum 1.A.7 extended metadata for ``sr``, if any."""
    return {
        "viewport_vantage": _VIEWPORT_VANTAGE.get(sr),
        "addon_version": sr.addon_version,
        "terrain_content_hash": sr.terrain_content_hash,
        "lockable_anchors": sr.lockable_anchors,
        "focal_direction": sr.focal_direction,
    }


def _coerce_bbox(raw: object) -> Optional[BBox]:
    if raw is None:
        return None
    if isinstance(raw, BBox):
        return raw
    if isinstance(raw, Mapping):
        raw_map = cast(Mapping[str, object], raw)
        min_x = _to_float(raw_map.get("min_x", 0.0))
        min_y = _to_float(raw_map.get("min_y", 0.0))
        max_x = _to_float(raw_map.get("max_x", 0.0))
        max_y = _to_float(raw_map.get("max_y", 0.0))
        if min_x is None or min_y is None or max_x is None or max_y is None:
            return None
        return BBox(
            min_x=min_x,
            min_y=min_y,
            max_x=max_x,
            max_y=max_y,
        )
    if isinstance(raw, (str, bytes)) or not isinstance(raw, RuntimeSequence):
        return None
    raw_sequence = cast(RuntimeSequence[object], raw)
    if len(raw_sequence) != 4:
        return None
    min_x = _to_float(raw_sequence[0])
    min_y = _to_float(raw_sequence[1])
    max_x = _to_float(raw_sequence[2])
    max_y = _to_float(raw_sequence[3])
    if min_x is None or min_y is None or max_x is None or max_y is None:
        return None
    return BBox(
        min_x,
        min_y,
        max_x,
        max_y,
    )


def _coerce_success_criteria(raw: object) -> tuple[str, ...]:
    criteria = _coerce_str_tuple(raw)
    return criteria if criteria else ("scene_understood",)


def _sequence_param(params: Mapping[str, object], key: str) -> object:
    value = params.get(key)
    return () if value is None else value


def _focal_point_param(params: Mapping[str, object]) -> Optional[Vec3]:
    return _coerce_vec3(params.get("focal_point"))


def _terrain_content_hash_param(params: Mapping[str, object]) -> Optional[str]:
    value = params.get("terrain_content_hash")
    if value is None:
        return None
    return str(value)


def _addon_version_param(params: Mapping[str, object]) -> Optional[AddonVersion]:
    return _coerce_addon_version(params.get("addon_version"))


def _viewport_vantage_param(params: Mapping[str, object]) -> object:
    return params.get("viewport_vantage")


def _reviewer_param(params: Mapping[str, object]) -> str:
    return str(params.get("reviewer", "unknown"))


def _empty_result_metadata() -> dict[str, object]:
    return {}


def _coerce_result_list(raw: object) -> list[object]:
    if raw is None:
        return []
    iterable = _iter_objects(raw)
    if iterable is None:
        return [raw]
    return list(iterable)


def _metadata_tuple_as_list(metadata: Mapping[str, object], key: str) -> Optional[list[object]]:
    raw = metadata.get(key)
    if raw is None:
        return None
    return _coerce_result_list(raw)


def _metadata_sequence_as_list(metadata: Mapping[str, object], key: str) -> list[object]:
    return _coerce_result_list(metadata.get(key, ()))


def _metadata_has_value(metadata: Mapping[str, object], key: str) -> bool:
    return metadata.get(key) is not None


def _scene_response(sr: TerrainSceneRead, extended: Mapping[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "timestamp": sr.timestamp,
        "reviewer": sr.reviewer,
        "focal_point": list(sr.focal_point),
        "major_landforms": list(sr.major_landforms),
        "hero_features_present_count": len(sr.hero_features_present),
        "hero_features_missing": list(sr.hero_features_missing),
        "waterfall_chains_count": len(sr.waterfall_chains),
        "cave_candidates_count": len(sr.cave_candidates),
        "protected_zones_in_region": list(sr.protected_zones_in_region),
        "edit_scope": list(sr.edit_scope.to_tuple()),
        "success_criteria": list(sr.success_criteria),
        "addon_version": _metadata_tuple_as_list(extended, "addon_version"),
        "terrain_content_hash": extended.get("terrain_content_hash"),
        "focal_direction": _metadata_tuple_as_list(extended, "focal_direction"),
        "lockable_anchors": _metadata_sequence_as_list(extended, "lockable_anchors"),
        "has_viewport_vantage": _metadata_has_value(extended, "viewport_vantage"),
    }


def handle_capture_scene_read(params: Mapping[str, object]) -> dict[str, object]:
    """MCP-style handler that wraps ``capture_scene_read`` for the bridge.

    Passes through the full parameter surface from Addendum 1.A.7 so
    bridge callers can produce a full-fidelity ``TerrainSceneRead`` with
    hero feature refs, waterfall chains, cave candidates, protected
    zones, and an explicit edit scope.
    """
    sr = capture_scene_read(
        reviewer=_reviewer_param(params),
        focal_point_hint=_focal_point_param(params),
        major_landforms=_coerce_str_tuple(_sequence_param(params, "major_landforms")),
        hero_features_present=_coerce_hero_feature_refs(
            _sequence_param(params, "hero_features_present")
        ),
        hero_features_missing=_coerce_str_tuple(
            _sequence_param(params, "hero_features_missing")
        ),
        waterfall_chains=_coerce_waterfall_chain_refs(
            _sequence_param(params, "waterfall_chains")
        ),
        cave_candidates=_coerce_vec3_sequence(
            _sequence_param(params, "cave_candidates")
        ),
        protected_zones_in_region=tuple(
            _coerce_str_tuple(_sequence_param(params, "protected_zones_in_region"))
        ),
        edit_scope=_coerce_bbox(params.get("edit_scope")),
        success_criteria=_coerce_success_criteria(params.get("success_criteria")),
        viewport_vantage=_viewport_vantage_param(params),
        addon_version=_addon_version_param(params),
        terrain_content_hash=_terrain_content_hash_param(params),
        lockable_anchors=_coerce_str_tuple(_sequence_param(params, "lockable_anchors")),
    )
    extended = get_extended_metadata(sr) or _empty_result_metadata()
    return _scene_response(sr, extended)


__all__ = [
    "capture_scene_read",
    "handle_capture_scene_read",
    "get_extended_metadata",
]
