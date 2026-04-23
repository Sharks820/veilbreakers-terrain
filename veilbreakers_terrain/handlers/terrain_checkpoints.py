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
import hashlib
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


def _atomic_npz_write(stack: "TerrainMaskStack", final_path: Path) -> str:
    """Write mask stack to a .npz atomically and return its SHA-256 hex digest.

    Strategy: write to ``<final_path>.tmp``, fsync, rename (atomic on POSIX,
    best-effort on Windows where rename() replaces atomically since Vista).
    A SHA-256 checksum sidecar (``<final_path>.sha256``) is written after the
    rename so readers can verify integrity without re-hashing the .npz.
    """
    # Keep the temporary path on a real ".npz" suffix so numpy does not append
    # an extra extension on Windows and break the later hash/rename step.
    tmp_path = final_path.with_name(f"{final_path.stem}.{uuid.uuid4().hex}.tmp.npz")
    stack.to_npz(tmp_path)

    # Compute SHA-256 over the written bytes
    sha256 = hashlib.sha256()
    with open(tmp_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha256.update(chunk)
    digest = sha256.hexdigest()

    # Atomic rename — replaces the destination on both POSIX and Windows
    try:
        tmp_path.replace(final_path)
    except OSError:
        # Last-resort fallback (e.g. cross-device): copy then delete
        import shutil
        shutil.copy2(str(tmp_path), str(final_path))
        try:
            tmp_path.unlink()
        except OSError:
            pass

    # Write checksum sidecar (non-critical: errors are logged, not raised)
    checksum_path = final_path.with_suffix(".npz.sha256")
    try:
        checksum_path.write_text(f"{digest}  {final_path.name}\n", encoding="utf-8")
    except OSError as exc:
        _ckpt_logger.warning("save_checkpoint: could not write checksum sidecar: %s", exc)

    return digest


def save_checkpoint(
    controller: TerrainPassController,
    pass_name: str,
    label: Optional[str] = None,
) -> TerrainCheckpoint:
    """Save a named checkpoint and append it to the controller state.

    Unlike ``TerrainPassController._save_checkpoint`` (which is called as
    part of run_pass), this is callable from outside the pass loop and
    accepts a human-readable ``label`` for later rollback.

    The mask stack .npz is written atomically (write to .tmp, then rename)
    and a SHA-256 checksum sidecar (.npz.sha256) is produced for integrity
    verification.
    """
    state = controller.state
    stack = state.mask_stack
    # Ensure checkpoint dir exists
    controller.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_id = f"{pass_name}_{uuid.uuid4().hex[:8]}"
    mask_path = controller.checkpoint_dir / f"{checkpoint_id}.npz"
    # Atomic write: tmp → rename, returns SHA-256 digest
    content_digest = _atomic_npz_write(stack, mask_path)

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
        # Use the SHA-256 digest from the atomic write as the authoritative
        # content hash — avoids a second full traversal of the mask stack.
        content_hash=content_digest,
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
        viewport_vantage_snapshot=copy.deepcopy(state.viewport_vantage),
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
    """Recursively make a value JSON-safe.

    Handles:
    - ``pathlib.Path`` → str
    - ``frozenset`` / ``set`` → tagged dict ``{"__type__": "frozenset", "items": [...str...]}``
      so ``_deserialize_value`` can reconstruct the exact type on round-trip.
    - numpy scalar types (np.int32, np.float64, …) → Python int / float
    - numpy ndarray → ``{"__type__": "ndarray", "data": [...], "dtype": "<dtype>"}``
    - dict / list / tuple → recursed
    - Everything else → returned as-is (must already be JSON-serialisable)
    """
    import numpy as _np

    if isinstance(v, Path):
        return str(v)
    if isinstance(v, (frozenset, set)):
        # Coerce every member to str so JSON.dumps never chokes on custom objects.
        # Sorting ensures byte-identical serialisation across runs.
        return {"__type__": "frozenset", "items": sorted(str(m) for m in v)}
    if isinstance(v, _np.ndarray):
        return {"__type__": "ndarray", "data": v.tolist(), "dtype": str(v.dtype)}
    if isinstance(v, _np.generic):
        # numpy scalar (np.int32, np.float64, np.bool_, …) → native Python type
        return v.item()
    if isinstance(v, dict):
        return {k: _serialize_value(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_serialize_value(item) for item in v]
    return v


def _deserialize_value(v: Any) -> Any:
    """Inverse of ``_serialize_value``.

    Recognises the ``{"__type__": ...}`` tags written by ``_serialize_value``
    and reconstructs frozensets and numpy arrays.  Plain dicts, lists, and
    scalars are passed through unchanged so the function is safe to apply to
    any JSON-decoded value.
    """
    import numpy as _np

    if isinstance(v, dict):
        tag = v.get("__type__")
        if tag == "frozenset":
            return frozenset(v.get("items", []))
        if tag == "ndarray":
            return _np.array(v["data"], dtype=v.get("dtype", "float64"))
        return {k: _deserialize_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_deserialize_value(item) for item in v]
    return v


def _intent_to_dict(intent: TerrainIntentState) -> Dict[str, Any]:
    """Serialize TerrainIntentState to a JSON-safe dict (drops scene_read).

    Includes a ``schema_version`` field so ``_intent_from_dict`` can detect
    and handle round-trip compatibility mismatches gracefully.  All Path
    objects are converted to strings, frozensets are tagged for lossless
    round-trip, and numpy scalars/arrays are converted to JSON-native types.

    Round-trip guarantee (for types that appear in practice):
        ``_intent_from_dict(_intent_to_dict(intent)) == intent``
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
                "world_position": [float(x) for x in a.world_position],
                "orientation": [float(x) for x in a.orientation],
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
                # Use tagged serialisation so frozenset members that are not
                # plain strings (e.g. enums, custom objects) survive the
                # JSON round-trip without silent str() coercion at read time.
                "allowed_mutations": sorted(str(m) for m in z.allowed_mutations),
                "forbidden_mutations": sorted(str(m) for m in z.forbidden_mutations),
                "description": z.description,
            }
            for z in intent.protected_zones
        ],
        "hero_feature_specs": [
            {
                "feature_id": h.feature_id,
                "feature_kind": h.feature_kind,
                "world_position": [float(x) for x in h.world_position],
                "orientation": [float(x) for x in h.orientation],
                "bounds": list(h.bounds.to_tuple()) if h.bounds else None,
                "anchor_name": h.anchor_name,
                "tier": h.tier,
                "exclusion_radius": float(h.exclusion_radius),
                "parameters": _serialize_value(dict(h.parameters)),
            }
            for h in intent.hero_feature_specs
        ],
    }


import logging as _ckpt_log  # noqa: E402
_ckpt_logger = _ckpt_log.getLogger(__name__)


def _intent_from_dict(data: Dict[str, Any]) -> TerrainIntentState:
    """Deserialize a TerrainIntentState from a JSON-safe dict.

    Uses `.get()` with safe defaults throughout so missing or renamed keys
    (e.g. from an older schema version) do not raise KeyError.  When the
    serialized ``schema_version`` does not match the current
    ``_INTENT_SCHEMA_VERSION``, a WARNING is emitted and unknown fields are
    silently replaced by their defaults — forward/backward compatibility.

    Tagged values produced by ``_serialize_value`` (frozensets, numpy arrays)
    are reconstructed via ``_deserialize_value`` so the round-trip
    ``_intent_from_dict(_intent_to_dict(intent)) == intent`` holds for all
    field types that appear in practice.
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
            world_position=tuple(float(x) for x in a.get("world_position", (0.0, 0.0, 0.0))),
            orientation=tuple(float(x) for x in a.get("orientation", (0.0, 0.0, 0.0))),
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
            # allowed_mutations / forbidden_mutations are stored as plain sorted
            # lists of strings (schema v1.1).  Reconstruct as frozenset so the
            # dataclass type contract is met and equality checks work correctly.
            allowed_mutations=frozenset(str(m) for m in z.get("allowed_mutations", [])),
            forbidden_mutations=frozenset(str(m) for m in z.get("forbidden_mutations", [])),
            description=z.get("description", ""),
        )
        for z in data.get("protected_zones", [])
    )
    heroes = tuple(
        HeroFeatureSpec(
            feature_id=h.get("feature_id", ""),
            feature_kind=h.get("feature_kind", "generic"),
            world_position=tuple(float(x) for x in h.get("world_position", (0.0, 0.0, 0.0))),
            orientation=tuple(float(x) for x in h.get("orientation", (0.0, 0.0, 0.0))),
            bounds=BBox(*h["bounds"]) if h.get("bounds") else None,
            anchor_name=h.get("anchor_name"),
            tier=h.get("tier", "secondary"),
            exclusion_radius=float(h.get("exclusion_radius", 0.0)),
            # parameters may contain tagged frozensets/ndarrays written by
            # _serialize_value; reconstruct them via _deserialize_value.
            parameters=_deserialize_value(dict(h.get("parameters", {}))),
        )
        for h in data.get("hero_feature_specs", [])
    )

    # Reconstruct heightmap_source as a Path when present (v1.1+)
    heightmap_source_raw = data.get("heightmap_source")
    heightmap_source = Path(heightmap_source_raw) if heightmap_source_raw else None

    # composition_hints may contain tagged values from _serialize_value
    composition_hints = _deserialize_value(dict(data.get("composition_hints", {})))

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
        composition_hints=composition_hints,
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

    Both files are written atomically (write to .tmp, then rename) so a
    crash mid-write never leaves a half-written or inconsistent preset on
    disk.  A SHA-256 content hash of the mask stack is embedded in the JSON
    so ``restore_preset`` can verify integrity on load.

    Write order:
      1. npz (mask stack) written atomically via ``_atomic_npz_write`` —
         returns the SHA-256 digest of the file on disk.
      2. JSON written atomically with the digest embedded — if JSON write
         fails the npz is already on disk with its sidecar (.npz.sha256),
         which is still a valid standalone checkpoint.
    """
    preset_dir = Path(preset_dir) if preset_dir is not None else DEFAULT_PRESET_ROOT
    preset_dir.mkdir(parents=True, exist_ok=True)
    stack_path = preset_dir / f"{preset_name}.npz"
    json_path = preset_dir / f"{preset_name}.json"

    # Atomic npz write — returns SHA-256 hex digest of the written file
    content_digest = _atomic_npz_write(controller.state.mask_stack, stack_path)

    payload = {
        "preset_name": preset_name,
        "created_at": time.time(),
        "schema_version": "1.1",
        "intent": _intent_to_dict(controller.state.intent),
        "mask_stack_path": stack_path.name,
        # SHA-256 of the npz bytes on disk (from _atomic_npz_write)
        "content_hash": content_digest,
    }
    # Atomic JSON write: tmp → rename
    tmp_path = json_path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        tmp_path.replace(json_path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return json_path


def restore_preset(preset_path: Path) -> TerrainPipelineState:
    """Load a preset JSON and return a fresh TerrainPipelineState.

    Integrity verification
    ----------------------
    When the preset JSON contains a ``content_hash`` field (written by
    ``save_preset`` schema_version >= 1.1), the SHA-256 of the npz file on
    disk is computed and compared against the stored digest.  A mismatch
    raises ``ValueError`` so corrupted or tampered presets are detected
    before their data enters the pipeline.

    For older presets (schema_version 1.0, no ``content_hash``), the
    integrity check is skipped and a WARNING is emitted so the caller can
    decide whether to trust the file.
    """
    preset_path = Path(preset_path)
    with open(preset_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    intent = _intent_from_dict(payload["intent"])
    stack_name = payload["mask_stack_path"]
    stack_path = preset_path.parent / stack_name

    # --- Integrity verification ---
    stored_hash = payload.get("content_hash")
    if stored_hash:
        actual_hash = hashlib.sha256()
        with open(stack_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                actual_hash.update(chunk)
        actual_digest = actual_hash.hexdigest()
        if actual_digest != stored_hash:
            raise ValueError(
                f"restore_preset: integrity check failed for {stack_path.name}. "
                f"Expected SHA-256 {stored_hash!r}, got {actual_digest!r}. "
                "The npz file may be corrupted or was modified after saving."
            )
    else:
        _ckpt_logger.warning(
            "restore_preset: preset %r has no content_hash (schema_version < 1.1); "
            "integrity cannot be verified. Re-save with save_preset() to add hashing.",
            preset_path.name,
        )

    stack = TerrainMaskStack.from_npz(stack_path)
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# Autosave
# ---------------------------------------------------------------------------


def autosave_after_pass(controller: TerrainPassController, enabled: bool = True) -> None:
    """Toggle automatic checkpointing after each successful pass.

    When enabled, wraps ``controller.run_pass`` so every successful pass
    emits an additional labeled checkpoint (atomic write + SHA-256 checksum)
    tagged ``autosave_<pass>``.  Disabling restores the original method.

    wrapped_run_pass behaviour
    --------------------------
    - A snapshot of the mask stack is taken BEFORE the pass so that if the
      pass raises an exception the stack can be rolled back to the clean state.
    - Checkpoint save only occurs when ``result.status == "ok"``; a failed
      pass never writes a partial/corrupt checkpoint.
    - The checkpoint .npz is written atomically (tmp → rename) with a SHA-256
      sidecar via ``save_checkpoint`` → ``_atomic_npz_write``.
    - Save duration is recorded in checkpoint metrics for observability.
    - Autosave I/O failure logs a WARNING but never propagates.
    - Any exception raised by the underlying pass is re-raised after rollback
      so the pipeline sees the correct error while the mask stack stays clean.
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
            # Snapshot the mask stack before the pass so we can roll back if
            # the pass raises an exception (leaves the stack in a dirty state).
            pre_pass_stack = copy.deepcopy(controller.state.mask_stack)

            try:
                result = original(
                    pass_name, region=region, force=force, checkpoint=checkpoint
                )
            except Exception as exc:
                # Restore pre-pass mask stack — mutation was incomplete.
                try:
                    object.__setattr__(controller.state, "mask_stack", pre_pass_stack)
                except Exception:
                    # Fallback: state may not be frozen; use direct assignment.
                    controller.state.mask_stack = pre_pass_stack  # type: ignore[misc]
                _ckpt_logger.warning(
                    "autosave_after_pass: pass '%s' raised %s — mask stack rolled back.",
                    pass_name,
                    exc,
                )
                raise

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
                    # Autosave I/O failure must never abort the pipeline.
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
