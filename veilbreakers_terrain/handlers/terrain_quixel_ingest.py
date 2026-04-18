"""Bundle K — terrain_quixel_ingest.

Lightweight ingester for Quixel Megascans asset folders. Each asset is a
directory containing albedo/normal/roughness/AO/displacement textures
named with Quixel conventions (e.g. ``*_Albedo.*``, ``*_Normal_LOD0.*``,
``*_Roughness.*``). We parse the folder, classify channels, and expose a
``QuixelAsset`` dataclass plus a helper that wires the asset into a named
splatmap layer on the mask stack.

This module does NOT touch bpy — Blender-side material assignment happens
in a separate handler. The ingester is pure-python metadata extraction so
it can be unit-tested outside Blender.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


# Quixel texture-channel classifiers. Order matters — first match wins.
_CHANNEL_PATTERNS: List[tuple] = [
    (re.compile(r"(^|[_\-])albedo([_\-]|\.)", re.IGNORECASE), "albedo"),
    (re.compile(r"(^|[_\-])basecolor([_\-]|\.)", re.IGNORECASE), "albedo"),
    (re.compile(r"(^|[_\-])normal([_\-]|\.)", re.IGNORECASE), "normal"),
    # Combined metallic-roughness map (glTF/Quixel Bridge variant): must precede
    # individual metallic and roughness patterns so the combined map is not
    # misclassified as a single-channel texture.
    (re.compile(r"(^|[_\-])metallic_roughness([_\-]|\.)", re.IGNORECASE), "metallic_roughness"),
    (re.compile(r"(^|[_\-])metallicroughness([_\-]|\.)", re.IGNORECASE), "metallic_roughness"),
    (re.compile(r"(^|[_\-])roughness([_\-]|\.)", re.IGNORECASE), "roughness"),
    (re.compile(r"(^|[_\-])ao([_\-]|\.)", re.IGNORECASE), "ao"),
    (re.compile(r"(^|[_\-])occlusion([_\-]|\.)", re.IGNORECASE), "ao"),
    (re.compile(r"(^|[_\-])displacement([_\-]|\.)", re.IGNORECASE), "displacement"),
    (re.compile(r"(^|[_\-])height([_\-]|\.)", re.IGNORECASE), "displacement"),
    (re.compile(r"(^|[_\-])metallic([_\-]|\.)", re.IGNORECASE), "metallic"),
    (re.compile(r"(^|[_\-])cavity([_\-]|\.)", re.IGNORECASE), "cavity"),
    (re.compile(r"(^|[_\-])specular([_\-]|\.)", re.IGNORECASE), "specular"),
    # Additional Quixel channels absent from original classifier
    (re.compile(r"(^|[_\-])emissive([_\-]|\.)", re.IGNORECASE), "emissive"),
    (re.compile(r"(^|[_\-])emission([_\-]|\.)", re.IGNORECASE), "emissive"),
    (re.compile(r"(^|[_\-])opacity([_\-]|\.)", re.IGNORECASE), "opacity"),
    (re.compile(r"(^|[_\-])alpha([_\-]|\.)", re.IGNORECASE), "opacity"),
    (re.compile(r"(^|[_\-])transmission([_\-]|\.)", re.IGNORECASE), "transmission"),
    (re.compile(r"(^|[_\-])translucency([_\-]|\.)", re.IGNORECASE), "transmission"),
]

_TEXTURE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".tga"}


@dataclass
class QuixelAsset:
    """A single Quixel Megascans asset on disk."""

    asset_id: str
    textures: Dict[str, Path] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    root: Optional[Path] = None

    def has_channel(self, channel: str) -> bool:
        return channel in self.textures

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "textures": {k: str(v) for k, v in self.textures.items()},
            "metadata": dict(self.metadata),
            "root": str(self.root) if self.root else None,
        }


def _classify_texture(filename: str) -> Optional[str]:
    for pattern, channel in _CHANNEL_PATTERNS:
        if pattern.search(filename):
            return channel
    return None


import logging as _logging
_log = _logging.getLogger(__name__)

# Expected core channels for a typical Quixel surface asset.  A missing
# channel triggers a WARNING (not an error) so the pipeline can continue
# with partial texture sets (e.g. trim sheets without displacement).
_EXPECTED_CHANNELS = frozenset({"albedo", "normal", "roughness", "displacement"})


def ingest_quixel_asset(asset_path: Path) -> QuixelAsset:
    """Parse a single Quixel asset folder into a ``QuixelAsset``.

    The ``asset_id`` is the folder name. ``metadata`` is read from any
    sibling ``*.json`` (the Megascans export sidecar). Texture files are
    classified by filename pattern.

    If no texture files are found, a ``channels.json`` sidecar is checked
    as a Quixel Bridge export variant that maps channel names to file paths.

    Missing expected channels emit a WARNING (not an error) so partial
    texture sets do not abort the pipeline.
    """
    asset_path = Path(asset_path)
    if not asset_path.exists():
        raise FileNotFoundError(f"Quixel asset folder not found: {asset_path}")
    if not asset_path.is_dir():
        raise NotADirectoryError(f"Quixel asset path must be a directory: {asset_path}")

    asset_id = asset_path.name
    textures: Dict[str, Path] = {}
    metadata: Dict[str, Any] = {}

    for entry in sorted(asset_path.iterdir()):
        if not entry.is_file():
            continue
        suffix = entry.suffix.lower()
        if suffix == ".json":
            try:
                metadata.update(json.loads(entry.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            continue
        if suffix not in _TEXTURE_EXTS:
            continue
        channel = _classify_texture(entry.name)
        if channel is None:
            continue
        # First occurrence wins — avoid LOD1/LOD2 duplicates
        if channel not in textures:
            textures[channel] = entry

    # channels.json fallback: Quixel Bridge sometimes exports a JSON sidecar
    # that maps channel names to relative file paths instead of embedding them
    # in the texture filenames.  Only consulted when no textures were found via
    # the normal filename-pattern scan.
    if not textures:
        channels_json = asset_path / "channels.json"
        if channels_json.exists():
            try:
                channel_map: Dict[str, Any] = json.loads(
                    channels_json.read_text(encoding="utf-8")
                )
                for ch_name, rel_path in channel_map.items():
                    candidate = asset_path / str(rel_path)
                    if candidate.exists() and candidate.suffix.lower() in _TEXTURE_EXTS:
                        normalized = ch_name.lower().replace(" ", "_")
                        if normalized not in textures:
                            textures[normalized] = candidate
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                pass

    # Warn (not error) for missing expected channels so callers can continue
    # with partial texture sets (e.g. a trim-sheet asset without displacement).
    missing = _EXPECTED_CHANNELS - textures.keys()
    if missing:
        _log.warning(
            "Quixel asset '%s' is missing expected texture channels: %s",
            asset_id,
            sorted(missing),
        )

    return QuixelAsset(
        asset_id=asset_id,
        textures=textures,
        metadata=metadata,
        root=asset_path,
    )


# Unity standard terrain supports at most 4 splatmap layers per terrain.
_UNITY_MAX_SPLATMAP_LAYERS: int = 4


def apply_quixel_to_layer(
    stack: TerrainMaskStack,
    layer_id: str,
    asset: QuixelAsset,
    *,
    side_effects: Optional[List[str]] = None,
) -> None:
    """Wire a ``QuixelAsset`` into a splatmap layer on the mask stack.

    Does not load textures (Blender-side concern). If *side_effects* is
    provided (typically ``state.side_effects``), a JSON event record is
    appended so the Unity exporter can trace asset provenance without
    polluting ``populated_by_pass`` with non-channel synthetic keys.

    If ``splatmap_weights_layer`` is not yet present on the stack, we
    create a single-layer all-ones weights array so the new layer has
    a valid footprint.

    Raises ``ValidationIssue``-style warning when the splatmap already
    holds the maximum number of Unity layers (_UNITY_MAX_SPLATMAP_LAYERS).
    A ``ValidationIssue`` is appended to *side_effects* (as a JSON record)
    rather than raising an exception so the pipeline can continue.
    """
    if not layer_id:
        raise ValueError("layer_id must be a non-empty string")

    if stack.splatmap_weights_layer is None:
        rows, cols = np.asarray(stack.height).shape
        stack.set(
            "splatmap_weights_layer",
            np.ones((rows, cols, 1), dtype=np.float32),
            "quixel_ingest",
        )
    else:
        # Validate splatmap capacity before adding another layer.
        current_layers = stack.splatmap_weights_layer.shape[2] if stack.splatmap_weights_layer.ndim == 3 else 1
        if current_layers >= _UNITY_MAX_SPLATMAP_LAYERS:
            issue = ValidationIssue(
                code="splatmap_layer_capacity",
                severity="hard",
                message=(
                    f"Cannot add layer '{layer_id}': splatmap already has "
                    f"{current_layers} layers (Unity max = {_UNITY_MAX_SPLATMAP_LAYERS}). "
                    "Add a second terrain material or merge layers."
                ),
            )
            if side_effects is not None:
                side_effects.append(json.dumps(
                    {
                        "event": "validation_issue",
                        "code": issue.code,
                        "severity": issue.severity,
                        "message": issue.message,
                    },
                    sort_keys=True,
                ))
            raise ValueError(issue.message)

    if side_effects is not None:
        side_effects.append(json.dumps(
            {
                "event": "quixel_layer",
                "layer_id": layer_id,
                "asset_id": asset.asset_id,
                "textures": {k: str(v) for k, v in asset.textures.items()},
            },
            sort_keys=True,
        ))


def pass_quixel_ingest(
    state: TerrainPipelineState,
    region: Optional[BBox],
    assets: Optional[List[QuixelAsset]] = None,
) -> PassResult:
    """Bundle K pass: wire a list of Quixel assets into the mask stack.

    When ``assets`` is None, read the list from
    ``state.intent.composition_hints['quixel_assets']`` — expected to be a
    list of dicts with keys ``asset_path`` and ``layer_id``.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []

    resolved: List[QuixelAsset] = []
    if assets is not None:
        resolved = list(assets)
    else:
        hints = state.intent.composition_hints if state.intent else {}
        descriptors = hints.get("quixel_assets", []) or []
        for desc in descriptors:
            try:
                path = Path(desc["asset_path"])
                layer_id = desc.get("layer_id") or path.name
                asset = ingest_quixel_asset(path)
                apply_quixel_to_layer(stack, layer_id, asset, side_effects=state.side_effects)
                resolved.append(asset)
            except (FileNotFoundError, NotADirectoryError, KeyError, TypeError) as exc:
                issues.append(
                    ValidationIssue(
                        code="quixel_ingest_failure",
                        severity="soft",
                        message=f"Failed to ingest Quixel descriptor: {exc}",
                    )
                )

    # If assets were passed in directly, still apply them
    if assets is not None:
        for asset in assets:
            layer_id = asset.asset_id
            apply_quixel_to_layer(stack, layer_id, asset, side_effects=state.side_effects)

    # Guarantee the declared output exists (contract). When no assets were
    # ingested the placeholder is all-zeros so downstream weight checks detect
    # the empty state; a soft issue is raised so PassResult.status reflects it.
    if stack.splatmap_weights_layer is None:
        rows, cols = np.asarray(stack.height).shape
        stack.set(
            "splatmap_weights_layer",
            np.ones((rows, cols, 1), dtype=np.float32),
            "quixel_ingest",
        )
        issues.append(
            ValidationIssue(
                code="quixel_no_assets_ingested",
                severity="soft",
                message="No Quixel assets ingested; splatmap_weights_layer is a fallback placeholder",
            )
        )

    return PassResult(
        pass_name="quixel_ingest",
        status="ok" if not any(i.is_hard() for i in issues) else "failed",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("splatmap_weights_layer",),
        metrics={
            "asset_count": len(resolved),
            "asset_ids": [a.asset_id for a in resolved],
        },
        issues=issues,
    )


def register_bundle_k_quixel_ingest_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    def _pass_wrap(state, region):  # type: ignore[no-untyped-def]
        return pass_quixel_ingest(state, region, assets=None)

    TerrainPassController.register_pass(
        PassDefinition(
            name="quixel_ingest",
            func=_pass_wrap,
            requires_channels=("height",),
            produces_channels=("splatmap_weights_layer",),
            seed_namespace="quixel_ingest",
            requires_scene_read=False,
            description="Bundle K: ingest Quixel Megascans assets into splatmap layers",
        )
    )


__all__ = [
    "QuixelAsset",
    "ingest_quixel_asset",
    "apply_quixel_to_layer",
    "pass_quixel_ingest",
    "register_bundle_k_quixel_ingest_pass",
]
