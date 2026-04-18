"""Bundle R — capture_scene_read handler.

Produces ``TerrainSceneRead`` snapshots per §5.3 of the implementation
plan. Headless mode accepts supplied kwargs; real Blender would walk the
current scene via ``bpy.data``.

See Addendum 1.A.7.
"""

from __future__ import annotations

import time
import weakref as _weakref
from typing import Optional, Sequence, Tuple

from .terrain_semantics import (
    BBox,
    HeroFeatureRef,
    TerrainSceneRead,
    WaterfallChainRef,
)


def _walk_scene() -> dict:
    """Walk bpy.data to extract real scene state when running in Blender."""
    result = {}
    try:
        import bpy
        # Collect objects with vb_feature_id custom property
        hero_features = []
        for obj in bpy.data.objects:
            if "vb_feature_id" in obj:
                hero_features.append({
                    "id": obj["vb_feature_id"],
                    "type": obj.get("vb_feature_type", "unknown"),
                    "location": list(obj.location),
                    "name": obj.name,
                })
        result["hero_features"] = hero_features

        # Find focal point from active camera
        cam = bpy.context.scene.camera
        if cam:
            result["focal_point"] = list(cam.location)
            result["focal_direction"] = list(cam.matrix_world.col[2][:3])

        # Waterfall chain empties
        waterfall_chains = []
        for obj in bpy.data.objects:
            if obj.name.startswith("vb_waterfall_chain_"):
                waterfall_chains.append({
                    "name": obj.name,
                    "location": list(obj.location),
                })
        result["waterfall_chains"] = waterfall_chains

        # Cave candidates
        cave_candidates = []
        for obj in bpy.data.objects:
            if obj.name.startswith("vb_cave_"):
                cave_candidates.append({
                    "name": obj.name,
                    "location": list(obj.location),
                    "type": obj.get("vb_cave_type", "unknown"),
                })
        result["cave_candidates"] = cave_candidates

        result["timestamp"] = bpy.data.scenes[0].name  # use scene name as identifier
    except Exception:
        pass
    return result


def capture_scene_read(
    *,
    reviewer: str,
    focal_point_hint: Optional[Tuple[float, float, float]] = None,
    major_landforms: Sequence[str] = (),
    hero_features_present: Sequence[HeroFeatureRef] = (),
    hero_features_missing: Sequence[str] = (),
    waterfall_chains: Sequence[WaterfallChainRef] = (),
    cave_candidates: Sequence[Tuple[float, float, float]] = (),
    protected_zones_in_region: Sequence[str] = (),
    edit_scope: Optional[BBox] = None,
    success_criteria: Sequence[str] = ("scene_understood",),
    viewport_vantage: Optional[object] = None,
    addon_version: Optional[Tuple[int, int, int]] = None,
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
            _fp = tuple(_live["focal_point"])
            if len(_fp) >= 2:
                focal_point_hint = _fp
        if not hero_features_present and _live.get("hero_features"):
            # Convert raw dicts to HeroFeatureRef instances where possible
            _built: list = []
            for _hf in _live["hero_features"]:
                loc = _hf.get("location", [0.0, 0.0, 0.0])
                _built.append(
                    HeroFeatureRef(
                        feature_id=str(_hf.get("id", _hf["name"])),
                        feature_kind=str(_hf.get("type", "unknown")),
                        world_position=(float(loc[0]), float(loc[1]), float(loc[2])),
                        blender_object_name=str(_hf["name"]),
                    )
                )
            hero_features_present = _built
        if not waterfall_chains and _live.get("waterfall_chains"):
            # Waterfall chains from scene are location-only empties; build
            # minimal WaterfallChainRef stubs so they are visible in the snapshot.
            _wf_built: list = []
            for _wf in _live["waterfall_chains"]:
                _loc = _wf.get("location", [0.0, 0.0, 0.0])
                _wf_built.append(
                    WaterfallChainRef(
                        chain_id=str(_wf["name"]),
                        lip_position=(float(_loc[0]), float(_loc[1]), float(_loc[2])),
                        pool_position=(float(_loc[0]), float(_loc[1]), float(_loc[2])),
                        drop_height=0.0,
                    )
                )
            waterfall_chains = _wf_built
        if not cave_candidates and _live.get("cave_candidates"):
            cave_candidates = [
                (float(c["location"][0]), float(c["location"][1]), float(c["location"][2]))
                for c in _live["cave_candidates"]
            ]

    focal = (
        tuple(float(x) for x in focal_point_hint)
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
        cave_candidates=tuple(tuple(c) for c in cave_candidates),
        protected_zones_in_region=tuple(protected_zones_in_region),
        edit_scope=scope,
        success_criteria=tuple(success_criteria),
        reviewer=str(reviewer),
        addon_version=tuple(addon_version) if addon_version is not None else None,
        lockable_anchors=tuple(lockable_anchors),
        extended_at=time.time(),
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


def get_extended_metadata(sr: TerrainSceneRead) -> Optional[dict]:
    """Return the Addendum 1.A.7 extended metadata for ``sr``, if any."""
    return {
        "viewport_vantage": _VIEWPORT_VANTAGE.get(sr),
        "addon_version": sr.addon_version,
        "terrain_content_hash": getattr(sr, "terrain_content_hash", None),
        "lockable_anchors": sr.lockable_anchors,
    }


def _coerce_bbox(raw) -> Optional[BBox]:
    if raw is None:
        return None
    if isinstance(raw, BBox):
        return raw
    if isinstance(raw, dict):
        return BBox(
            min_x=float(raw.get("min_x", 0.0)),
            min_y=float(raw.get("min_y", 0.0)),
            max_x=float(raw.get("max_x", 0.0)),
            max_y=float(raw.get("max_y", 0.0)),
        )
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        mn_x, mn_y, mx_x, mx_y = raw
        return BBox(float(mn_x), float(mn_y), float(mx_x), float(mx_y))
    return None


def handle_capture_scene_read(params: dict) -> dict:
    """MCP-style handler that wraps ``capture_scene_read`` for the bridge.

    Passes through the full parameter surface from Addendum 1.A.7 so
    bridge callers can produce a full-fidelity ``TerrainSceneRead`` with
    hero feature refs, waterfall chains, cave candidates, protected
    zones, and an explicit edit scope.
    """
    sr = capture_scene_read(
        reviewer=str(params.get("reviewer", "unknown")),
        focal_point_hint=params.get("focal_point"),
        major_landforms=tuple(params.get("major_landforms", ()) or ()),
        hero_features_present=tuple(params.get("hero_features_present", ()) or ()),
        hero_features_missing=tuple(params.get("hero_features_missing", ()) or ()),
        waterfall_chains=tuple(params.get("waterfall_chains", ()) or ()),
        cave_candidates=tuple(
            tuple(c) for c in (params.get("cave_candidates", ()) or ())
        ),
        protected_zones_in_region=tuple(
            params.get("protected_zones_in_region", ()) or ()
        ),
        edit_scope=_coerce_bbox(params.get("edit_scope")),
        success_criteria=tuple(params.get("success_criteria", ("scene_understood",))),
        viewport_vantage=params.get("viewport_vantage"),
        addon_version=(
            tuple(params.get("addon_version"))
            if params.get("addon_version") is not None
            else None
        ),
        terrain_content_hash=params.get("terrain_content_hash"),
        lockable_anchors=tuple(params.get("lockable_anchors", ()) or ()),
    )
    extended = get_extended_metadata(sr) or {}
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
        "addon_version": (
            list(extended["addon_version"])
            if extended.get("addon_version") is not None
            else None
        ),
        "terrain_content_hash": extended.get("terrain_content_hash"),
        "lockable_anchors": list(extended.get("lockable_anchors", ())),
        "has_viewport_vantage": extended.get("viewport_vantage") is not None,
    }


__all__ = [
    "capture_scene_read",
    "handle_capture_scene_read",
    "get_extended_metadata",
]
