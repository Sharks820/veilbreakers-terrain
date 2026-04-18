"""Bundle D — terrain checkpoint + preset management.

Thin layer on top of ``TerrainPassController._save_checkpoint``. Adds:

- Named/labeled checkpoints
- Rollback to last checkpoint or by label/id
- Checkpoint listing with serialized summaries
- Preset save/restore (intent + mask stack to a reusable bundle)
- Autosave toggle after each pass

Storage: ``.planning/terrain_checkpoints/`` under the repo root. Presets go
under ``.planning/terrain_checkpoints/presets/``.

No Blender / bpy imports. Pure Python + numpy — fully unit-testable.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .terrain_pipeline import TerrainPassController
from .terrain_semantics import (
    BBox,
    PassResult,
    ProtectedZoneSpec,
    TerrainAnchor,
    TerrainCheckpoint,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CHECKPOINT_ROOT = Path(".planning") / "terrain_checkpoints"
DEFAULT_PRESET_ROOT = DEFAULT_CHECKPOINT_ROOT / "presets"

# Label registry keyed by id(controller) so multiple controllers don't
# collide. Labels map to checkpoint_ids.
_LABEL_REGISTRY: Dict[int, Dict[str, str]] = {}

# Autosave registry: controllers that are actively autosaving.
_AUTOSAVE_CONTROLLERS: Dict[int, bool] = {}
# Monkey-patched original run_pass, keyed by controller id.
_ORIGINAL_RUN_PASS: Dict[int, Callable[..., PassResult]] = {}


# ---------------------------------------------------------------------------
# Save / load checkpoints
# ---------------------------------------------------------------------------


def save_checkpoint(
    controller: TerrainPassController,
    pass_name: str,
    label: Optional[str] = None,
) -> TerrainCheckpoint:
    """Save a named checkpoint and append it to the controller state.

    Unlike ``TerrainPassController._save_checkpoint`` (which is called as
    part of run_pass), this is callable from outside the pass loop and
    accepts a human-readable ``label`` for later rollback.
    """
    state = controller.state
    stack = state.mask_stack
    # Ensure checkpoint dir exists
    controller.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_id = f"{pass_name}_{uuid.uuid4().hex[:8]}"
    mask_path = controller.checkpoint_dir / f"{checkpoint_id}.npz"
    stack.to_npz(mask_path)

    parent_id = state.checkpoints[-1].checkpoint_id if state.checkpoints else None
    world_tile_extent = float(stack.tile_size) * float(stack.cell_size)
    world_bounds = BBox(
        min_x=float(stack.world_origin_x),
        min_y=float(stack.world_origin_y),
        max_x=float(stack.world_origin_x) + world_tile_extent,
        max_y=float(stack.world_origin_y) + world_tile_extent,
    )
    ckpt = TerrainCheckpoint(
        checkpoint_id=checkpoint_id,
        pass_name=pass_name,
        timestamp=time.time(),
        intent_hash=state.intent.intent_hash(),
        mask_stack_path=mask_path,
        geometry_snapshot_path=None,
        content_hash=stack.compute_hash(),
        parent_checkpoint_id=parent_id,
        metrics={"label": label} if label else {},
        world_bounds=world_bounds,
        height_min_m=stack.height_min_m,
        height_max_m=stack.height_max_m,
        cell_size_m=float(stack.cell_size),
        tile_size=int(stack.tile_size),
        coordinate_system=stack.coordinate_system,
        unity_export_schema_version=stack.unity_export_schema_version,
        water_network_snapshot=copy.deepcopy(state.water_network),
        side_effects_snapshot=list(state.side_effects),
        pass_history_len=len(state.pass_history),
    )
    state.checkpoints.append(ckpt)
    if label:
        _LABEL_REGISTRY.setdefault(id(controller), {})[label] = checkpoint_id
    return ckpt


def rollback_last_checkpoint(controller: TerrainPassController) -> None:
    """Rewind the mask stack to the most recent checkpoint."""
    if not controller.state.checkpoints:
        raise RuntimeError("No checkpoints available to roll back to.")
    last_id = controller.state.checkpoints[-1].checkpoint_id
    controller.rollback_to(last_id)


def rollback_to(controller: TerrainPassController, checkpoint_id_or_label: str) -> None:
    """Rewind by checkpoint id OR by a previously-assigned label."""
    labels = _LABEL_REGISTRY.get(id(controller), {})
    target_id = labels.get(checkpoint_id_or_label, checkpoint_id_or_label)
    controller.rollback_to(target_id)


def list_checkpoints(controller: TerrainPassController) -> List[Dict[str, Any]]:
    """Return a JSON-serializable summary of every checkpoint on state."""
    labels = _LABEL_REGISTRY.get(id(controller), {})
    # Reverse-lookup id -> label
    id_to_label = {cid: lbl for lbl, cid in labels.items()}
    out: List[Dict[str, Any]] = []
    for ckpt in controller.state.checkpoints:
        out.append(
            {
                "checkpoint_id": ckpt.checkpoint_id,
                "pass_name": ckpt.pass_name,
                "timestamp": ckpt.timestamp,
                "intent_hash": ckpt.intent_hash,
                "content_hash": ckpt.content_hash,
                "parent_checkpoint_id": ckpt.parent_checkpoint_id,
                "mask_stack_path": str(ckpt.mask_stack_path),
                "label": id_to_label.get(ckpt.checkpoint_id),
                "world_bounds": (
                    ckpt.world_bounds.to_tuple() if ckpt.world_bounds else None
                ),
                "height_min_m": ckpt.height_min_m,
                "height_max_m": ckpt.height_max_m,
                "cell_size_m": ckpt.cell_size_m,
                "tile_size": ckpt.tile_size,
                "coordinate_system": ckpt.coordinate_system,
                "unity_export_schema_version": ckpt.unity_export_schema_version,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Presets — serialize intent + mask stack to a reusable bundle
# ---------------------------------------------------------------------------


_INTENT_SCHEMA_VERSION = "1.1"


def _serialize_value(v: Any) -> Any:
    """Recursively make a value JSON-safe: convert Path objects to strings."""
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, dict):
        return {k: _serialize_value(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_serialize_value(item) for item in v]
    return v


def _intent_to_dict(intent: TerrainIntentState) -> Dict[str, Any]:
    """Serialize TerrainIntentState to a JSON-safe dict (drops scene_read).

    Includes a ``schema_version`` field so ``_intent_from_dict`` can detect
    and handle round-trip compatibility mismatches gracefully.  All Path
    objects are converted to strings via ``_serialize_value``.
    """
    return {
        "schema_version": _INTENT_SCHEMA_VERSION,
        "seed": int(intent.seed),
        "region_bounds": list(intent.region_bounds.to_tuple()),
        "tile_size": int(intent.tile_size),
        "cell_size": float(intent.cell_size),
        "quality_profile": str(intent.quality_profile) if intent.quality_profile is not None else None,
        "biome_rules": _serialize_value(intent.biome_rules),
        "noise_profile": str(intent.noise_profile) if intent.noise_profile is not None else None,
        "erosion_profile": str(intent.erosion_profile) if intent.erosion_profile is not None else None,
        "morphology_templates": [str(t) for t in intent.morphology_templates],
        "composition_hints": _serialize_value(dict(intent.composition_hints)),
        # heightmap_source may be a Path; serialize to string
        "heightmap_source": str(intent.heightmap_source) if getattr(intent, "heightmap_source", None) is not None else None,
        "anchors": [
            {
                "name": a.name,
                "world_position": list(a.world_position),
                "orientation": list(a.orientation),
                "anchor_kind": a.anchor_kind,
                "radius": float(a.radius),
                "blender_object_name": a.blender_object_name,
            }
            for a in intent.anchors
        ],
        "protected_zones": [
            {
                "zone_id": z.zone_id,
                "bounds": list(z.bounds.to_tuple()),
                "kind": z.kind,
                "allowed_mutations": sorted(z.allowed_mutations),
                "forbidden_mutations": sorted(z.forbidden_mutations),
                "description": z.description,
            }
            for z in intent.protected_zones
        ],
        "hero_feature_specs": [
            {
                "feature_id": h.feature_id,
                "feature_kind": h.feature_kind,
                "world_position": list(h.world_position),
                "orientation": list(h.orientation),
                "bounds": list(h.bounds.to_tuple()) if h.bounds else None,
                "anchor_name": h.anchor_name,
                "tier": h.tier,
                "exclusion_radius": float(h.exclusion_radius),
                "parameters": _serialize_value(dict(h.parameters)),
            }
            for h in intent.hero_feature_specs
        ],
    }


import logging as _ckpt_log
_ckpt_logger = _ckpt_log.getLogger(__name__)


def _intent_from_dict(data: Dict[str, Any]) -> TerrainIntentState:
    """Deserialize a TerrainIntentState from a JSON-safe dict.

    Uses `.get()` with safe defaults throughout so missing or renamed keys
    (e.g. from an older schema version) do not raise KeyError.  When the
    serialized ``schema_version`` does not match the current
    ``_INTENT_SCHEMA_VERSION``, a WARNING is emitted and unknown fields are
    silently replaced by their defaults — forward/backward compatibility.
    """
    from .terrain_semantics import HeroFeatureSpec  # local to avoid cycles

    stored_version = data.get("schema_version", "1.0")
    if stored_version != _INTENT_SCHEMA_VERSION:
        _ckpt_logger.warning(
            "_intent_from_dict: schema version mismatch (stored=%r, current=%r). "
            "Unknown fields will use defaults.",
            stored_version,
            _INTENT_SCHEMA_VERSION,
        )

    region_raw = data.get("region_bounds", [0.0, 0.0, 1.0, 1.0])
    region = BBox(*region_raw)

    anchors = tuple(
        TerrainAnchor(
            name=a.get("name", ""),
            world_position=tuple(a.get("world_position", (0.0, 0.0, 0.0))),
            orientation=tuple(a.get("orientation", (0.0, 0.0, 0.0))),
            anchor_kind=a.get("anchor_kind", "generic"),
            radius=float(a.get("radius", 0.0)),
            blender_object_name=a.get("blender_object_name"),
        )
        for a in data.get("anchors", [])
    )
    protected = tuple(
        ProtectedZoneSpec(
            zone_id=z.get("zone_id", ""),
            bounds=BBox(*z.get("bounds", [0.0, 0.0, 1.0, 1.0])),
            kind=z.get("kind", "generic"),
            allowed_mutations=frozenset(z.get("allowed_mutations", [])),
            forbidden_mutations=frozenset(z.get("forbidden_mutations", [])),
            description=z.get("description", ""),
        )
        for z in data.get("protected_zones", [])
    )
    heroes = tuple(
        HeroFeatureSpec(
            feature_id=h.get("feature_id", ""),
            feature_kind=h.get("feature_kind", "generic"),
            world_position=tuple(h.get("world_position", (0.0, 0.0, 0.0))),
            orientation=tuple(h.get("orientation", (0.0, 0.0, 0.0))),
            bounds=BBox(*h["bounds"]) if h.get("bounds") else None,
            anchor_name=h.get("anchor_name"),
            tier=h.get("tier", "secondary"),
            exclusion_radius=float(h.get("exclusion_radius", 0.0)),
            parameters=dict(h.get("parameters", {})),
        )
        for h in data.get("hero_feature_specs", [])
    )

    # Reconstruct heightmap_source as a Path when present (v1.1+)
    heightmap_source_raw = data.get("heightmap_source")
    heightmap_source = Path(heightmap_source_raw) if heightmap_source_raw else None

    kwargs: Dict[str, Any] = dict(
        seed=int(data.get("seed", 0)),
        region_bounds=region,
        tile_size=int(data.get("tile_size", 512)),
        cell_size=float(data.get("cell_size", 1.0)),
        anchors=anchors,
        protected_zones=protected,
        hero_feature_specs=heroes,
        quality_profile=data.get("quality_profile", "production"),
        biome_rules=data.get("biome_rules"),
        morphology_templates=tuple(data.get("morphology_templates", [])),
        noise_profile=data.get("noise_profile", "dark_fantasy_default"),
        erosion_profile=data.get("erosion_profile", "temperate"),
        composition_hints=dict(data.get("composition_hints", {})),
    )
    # Only pass heightmap_source if the dataclass accepts it (v1.1+ field)
    if heightmap_source is not None:
        try:
            return TerrainIntentState(**kwargs, heightmap_source=heightmap_source)
        except TypeError:
            _ckpt_logger.warning(
                "_intent_from_dict: TerrainIntentState does not accept "
                "'heightmap_source'; ignoring field from stored preset."
            )
    return TerrainIntentState(**kwargs)


def save_preset(
    controller: TerrainPassController,
    preset_name: str,
    preset_dir: Optional[Path] = None,
) -> Path:
    """Export intent + mask stack as a reusable preset.

    Writes ``<preset_dir>/<preset_name>.json`` and
    ``<preset_dir>/<preset_name>.npz`` atomically.
    """
    preset_dir = Path(preset_dir) if preset_dir is not None else DEFAULT_PRESET_ROOT
    preset_dir.mkdir(parents=True, exist_ok=True)
    stack_path = preset_dir / f"{preset_name}.npz"
    json_path = preset_dir / f"{preset_name}.json"

    controller.state.mask_stack.to_npz(stack_path)
    payload = {
        "preset_name": preset_name,
        "created_at": time.time(),
        "schema_version": "1.0",
        "intent": _intent_to_dict(controller.state.intent),
        "mask_stack_path": stack_path.name,
        "content_hash": controller.state.mask_stack.compute_hash(),
    }
    # Atomic write
    tmp_path = json_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    tmp_path.replace(json_path)
    return json_path


def restore_preset(preset_path: Path) -> TerrainPipelineState:
    """Load a preset JSON and return a fresh TerrainPipelineState."""
    preset_path = Path(preset_path)
    with open(preset_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    intent = _intent_from_dict(payload["intent"])
    stack_name = payload["mask_stack_path"]
    stack_path = preset_path.parent / stack_name
    stack = TerrainMaskStack.from_npz(stack_path)
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# Autosave
# ---------------------------------------------------------------------------


def autosave_after_pass(controller: TerrainPassController, enabled: bool = True) -> None:
    """Toggle automatic checkpointing after each successful pass.

    When enabled, wraps ``controller.run_pass`` so every successful pass
    emits an additional labeled checkpoint tagged ``autosave_<pass>``.
    Disabling restores the original method.

    Upgrade notes (C+→B):
    - Checkpoint save happens AFTER PassResult is returned from the original
      run_pass, so a failed pass never saves a partial checkpoint.
    - Save duration is recorded in checkpoint metrics.
    - Autosave failure logs a WARNING but never propagates the exception.
    """
    key = id(controller)
    if enabled:
        if key in _AUTOSAVE_CONTROLLERS and _AUTOSAVE_CONTROLLERS[key]:
            return  # already enabled
        original = controller.run_pass
        _ORIGINAL_RUN_PASS[key] = original

        def wrapped_run_pass(
            pass_name: str,
            region: Optional[BBox] = None,
            *,
            force: bool = False,
            checkpoint: bool = True,
        ) -> PassResult:
            # Run the pass first — checkpoint only happens on success so a
            # failed pass never writes a partial/corrupt checkpoint.
            result = original(
                pass_name, region=region, force=force, checkpoint=checkpoint
            )
            if result.status == "ok":
                save_t0 = time.time()
                try:
                    ckpt = save_checkpoint(
                        controller,
                        pass_name=pass_name,
                        label=f"autosave_{pass_name}_{uuid.uuid4().hex[:4]}",
                    )
                    save_duration = time.time() - save_t0
                    # Record save duration in the checkpoint metrics for observability.
                    ckpt.metrics["autosave_duration_s"] = round(save_duration, 4)
                except Exception as exc:
                    # Autosave failure must never abort the pipeline.
                    _ckpt_logger.warning(
                        "autosave_after_pass: checkpoint save failed for pass '%s': %s",
                        pass_name,
                        exc,
                    )
            return result

        controller.run_pass = wrapped_run_pass  # type: ignore[method-assign]
        _AUTOSAVE_CONTROLLERS[key] = True
    else:
        if key in _ORIGINAL_RUN_PASS:
            controller.run_pass = _ORIGINAL_RUN_PASS.pop(key)  # type: ignore[method-assign]
        _AUTOSAVE_CONTROLLERS[key] = False


__all__ = [
    "save_checkpoint",
    "rollback_last_checkpoint",
    "rollback_to",
    "list_checkpoints",
    "save_preset",
    "restore_preset",
    "autosave_after_pass",
    "DEFAULT_CHECKPOINT_ROOT",
    "DEFAULT_PRESET_ROOT",
]
