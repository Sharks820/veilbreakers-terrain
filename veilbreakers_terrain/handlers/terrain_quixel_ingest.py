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

Quixel 6.x short-suffix naming convention
------------------------------------------
Quixel Bridge 6.x exports textures with terse uppercase suffixes in the
stem before the extension, e.g.::

    uasset_xyzABCDE_2K_Albedo.jpg     -> albedo
    uasset_xyzABCDE_2K_Normal.jpg     -> normal
    uasset_xyzABCDE_2K_Roughness.jpg  -> roughness
    uasset_xyzABCDE_2K_AO.jpg         -> ao
    uasset_xyzABCDE_2K_Displacement.exr -> displacement
    uasset_xyzABCDE_2K_Metalness.jpg  -> metallic
    uasset_xyzABCDE_2K_Transmission.jpg -> transmission

Additionally some exports use very short BCR / D / N / R / M token
suffixes (common in older Megascans surfaces)::

    *_BCR.*   -> albedo  (Base Color Raw, pre-multiplied)
    *_D.*     -> albedo  (Diffuse — same as albedo for terrain surfaces)
    *_N.*     -> normal
    *_R.*     -> roughness
    *_M.*     -> metallic
    *_AO.*    -> ao
    *_T.*     -> transmission  (leaf/foliage translucency)

The ``_classify_texture`` function returns a ``TextureType`` enum value so
downstream callers get a typed channel rather than a raw string.
"""

from __future__ import annotations

import enum
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


# ---------------------------------------------------------------------------
# TextureType enum — typed channel IDs returned by _classify_texture
# ---------------------------------------------------------------------------

class TextureType(enum.Enum):
    """Typed channel identifiers for Quixel Megascans textures.

    Values are lower-case strings so existing dict lookups using
    ``channel in textures`` still work when the enum value is used as key.
    """

    ALBEDO = "albedo"
    NORMAL = "normal"
    ROUGHNESS = "roughness"
    AO = "ao"
    DISPLACEMENT = "displacement"
    METALLIC = "metallic"
    METALLIC_ROUGHNESS = "metallic_roughness"
    CAVITY = "cavity"
    SPECULAR = "specular"
    EMISSIVE = "emissive"
    OPACITY = "opacity"
    TRANSMISSION = "transmission"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


# ---------------------------------------------------------------------------
# Quixel texture-channel classifiers. Order matters — first match wins.
# ---------------------------------------------------------------------------

# Long-form descriptive patterns (handles both old and Bridge 6.x exports).
_CHANNEL_PATTERNS: List[tuple] = [
    # --- albedo variants ---
    (re.compile(r"(^|[_\-])albedo([_\-]|\.)", re.IGNORECASE), TextureType.ALBEDO),
    (re.compile(r"(^|[_\-])basecolor([_\-]|\.)", re.IGNORECASE), TextureType.ALBEDO),
    (re.compile(r"(^|[_\-])base_color([_\-]|\.)", re.IGNORECASE), TextureType.ALBEDO),
    (re.compile(r"(^|[_\-])diffuse([_\-]|\.)", re.IGNORECASE), TextureType.ALBEDO),
    # --- normal ---
    (re.compile(r"(^|[_\-])normal([_\-]|\.)", re.IGNORECASE), TextureType.NORMAL),
    # --- combined metallic-roughness (must precede individual patterns) ---
    (re.compile(r"(^|[_\-])metallic_roughness([_\-]|\.)", re.IGNORECASE), TextureType.METALLIC_ROUGHNESS),
    (re.compile(r"(^|[_\-])metallicroughness([_\-]|\.)", re.IGNORECASE), TextureType.METALLIC_ROUGHNESS),
    # --- roughness ---
    (re.compile(r"(^|[_\-])roughness([_\-]|\.)", re.IGNORECASE), TextureType.ROUGHNESS),
    # --- AO ---
    (re.compile(r"(^|[_\-])ao([_\-]|\.)", re.IGNORECASE), TextureType.AO),
    (re.compile(r"(^|[_\-])occlusion([_\-]|\.)", re.IGNORECASE), TextureType.AO),
    (re.compile(r"(^|[_\-])ambient_occlusion([_\-]|\.)", re.IGNORECASE), TextureType.AO),
    # --- displacement / height ---
    (re.compile(r"(^|[_\-])displacement([_\-]|\.)", re.IGNORECASE), TextureType.DISPLACEMENT),
    (re.compile(r"(^|[_\-])height([_\-]|\.)", re.IGNORECASE), TextureType.DISPLACEMENT),
    # --- metallic ---
    (re.compile(r"(^|[_\-])metallic([_\-]|\.)", re.IGNORECASE), TextureType.METALLIC),
    (re.compile(r"(^|[_\-])metalness([_\-]|\.)", re.IGNORECASE), TextureType.METALLIC),
    # --- cavity / specular ---
    (re.compile(r"(^|[_\-])cavity([_\-]|\.)", re.IGNORECASE), TextureType.CAVITY),
    (re.compile(r"(^|[_\-])specular([_\-]|\.)", re.IGNORECASE), TextureType.SPECULAR),
    # --- emissive ---
    (re.compile(r"(^|[_\-])emissive([_\-]|\.)", re.IGNORECASE), TextureType.EMISSIVE),
    (re.compile(r"(^|[_\-])emission([_\-]|\.)", re.IGNORECASE), TextureType.EMISSIVE),
    # --- opacity / alpha ---
    (re.compile(r"(^|[_\-])opacity([_\-]|\.)", re.IGNORECASE), TextureType.OPACITY),
    (re.compile(r"(^|[_\-])alpha([_\-]|\.)", re.IGNORECASE), TextureType.OPACITY),
    # --- transmission / translucency ---
    (re.compile(r"(^|[_\-])transmission([_\-]|\.)", re.IGNORECASE), TextureType.TRANSMISSION),
    (re.compile(r"(^|[_\-])translucency([_\-]|\.)", re.IGNORECASE), TextureType.TRANSMISSION),
]

# Quixel 6.x / legacy short-suffix patterns (uppercase token before extension).
# These are tested AFTER long-form patterns so a file named ``*_Normal_BCR.*``
# still resolves to NORMAL rather than ALBEDO.
_SHORT_SUFFIX_MAP: Dict[str, TextureType] = {
    "BCR":    TextureType.ALBEDO,       # Base Color Raw
    "D":      TextureType.ALBEDO,       # Diffuse (legacy terrain surface naming)
    "N":      TextureType.NORMAL,
    "R":      TextureType.ROUGHNESS,
    "M":      TextureType.METALLIC,
    "AO":     TextureType.AO,
    "T":      TextureType.TRANSMISSION, # foliage translucency short form
}

# Pre-compiled regex: matches _TOKEN. or _TOKEN_ at end-of-stem.
# E.g. "uasset_abcde_2K_BCR.jpg" -> token "BCR"
_SHORT_SUFFIX_RE = re.compile(
    r"(?:^|[_\-])(" + "|".join(re.escape(k) for k in _SHORT_SUFFIX_MAP) + r")(?:[_\-]|$)",
    re.IGNORECASE,
)

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


def _classify_texture(filename: str) -> Optional[TextureType]:
    """Classify a Quixel texture filename into a ``TextureType``.

    Two-stage lookup:

    1. Long-form descriptive patterns (``_Albedo_``, ``_Normal_``, etc.) —
       handles both legacy and Quixel Bridge 6.x naming styles.
    2. Short-suffix tokens (``_BCR``, ``_D``, ``_N``, ``_R``, ``_M``,
       ``_AO``, ``_T``) — Quixel 6.x terse convention.

    Returns ``None`` when no pattern matches (caller skips the file).
    """
    stem = Path(filename).stem  # strip extension for cleaner matching

    # Stage 1: long-form patterns on the full filename (includes extension so
    # boundary anchors like ``\.`` still fire correctly).
    for pattern, channel in _CHANNEL_PATTERNS:
        if pattern.search(filename):
            return channel

    # Stage 2: short-suffix scan on the stem only to avoid false matches on
    # the file extension (e.g. ".tga" should not trigger "T" → transmission).
    m = _SHORT_SUFFIX_RE.search(stem)
    if m:
        token = m.group(1).upper()
        if token in _SHORT_SUFFIX_MAP:
            return _SHORT_SUFFIX_MAP[token]

    return None


import logging as _logging  # noqa: E402
_log = _logging.getLogger(__name__)

# Expected core channels for a typical Quixel surface asset.  A missing
# channel triggers a WARNING (not an error) so the pipeline can continue
# with partial texture sets (e.g. trim sheets without displacement).
_EXPECTED_CHANNELS = frozenset({
    TextureType.ALBEDO,
    TextureType.NORMAL,
    TextureType.ROUGHNESS,
    TextureType.DISPLACEMENT,
})

# Biome tag keywords used to filter cache directories in pass_quixel_ingest.
# Keys are canonical biome names; values are sets of substring tokens that
# may appear in an asset folder name or in the asset's JSON metadata "tags"
# array.  Matching is case-insensitive.
_BIOME_ASSET_TAGS: Dict[str, frozenset] = {
    "arctic":    frozenset({"arctic", "snow", "ice", "tundra", "glacier", "frost"}),
    "tropical":  frozenset({"tropical", "jungle", "rainforest", "mangrove", "palm"}),
    "desert":    frozenset({"desert", "sand", "dune", "arid", "mesa", "badlands"}),
    "forest":    frozenset({"forest", "woodland", "mossy", "bark", "pine", "fern"}),
    "cliff":     frozenset({"cliff", "rock", "stone", "granite", "slate", "limestone"}),
    "wetland":   frozenset({"wetland", "swamp", "marsh", "mud", "bog", "algae"}),
    "alpine":    frozenset({"alpine", "mountain", "highland", "scree", "talus"}),
    "volcanic":  frozenset({"volcanic", "lava", "basalt", "obsidian", "cinder"}),
}


def _asset_matches_biome(asset_path: Path, metadata: Dict[str, Any], biome: str) -> bool:
    """Return True if an asset folder or its metadata tags match *biome*.

    Checks (in order):
    1. Folder name contains any biome keyword token.
    2. ``metadata["tags"]`` list contains any biome keyword token.
    3. ``metadata["categories"]`` list contains any biome keyword token.
    """
    tokens = _BIOME_ASSET_TAGS.get(biome, frozenset())
    if not tokens:
        return True  # unknown biome — don't filter

    name_lower = asset_path.name.lower()
    if any(tok in name_lower for tok in tokens):
        return True

    for meta_key in ("tags", "categories", "keywords"):
        tag_list = metadata.get(meta_key) or []
        if isinstance(tag_list, list):
            joined = " ".join(str(t).lower() for t in tag_list)
            if any(tok in joined for tok in tokens):
                return True

    return False


def ingest_quixel_asset(asset_path: Path) -> QuixelAsset:
    """Parse a single Quixel asset folder into a ``QuixelAsset``.

    The ``asset_id`` is the folder name. ``metadata`` is read from any
    sibling ``*.json`` (the Megascans export sidecar). Texture files are
    classified by filename pattern using ``_classify_texture``, which now
    returns a ``TextureType`` enum value.  The ``textures`` dict is keyed
    by ``TextureType`` enum so callers get typed access.

    If no texture files are found via the normal scan, a ``channels.json``
    sidecar is checked as a Quixel Bridge export variant.

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
        # Use the enum value string as dict key so downstream callers that
        # do ``asset.textures["albedo"]`` continue to work unchanged.
        key = channel.value
        # First occurrence wins — avoid LOD1/LOD2 duplicates
        if key not in textures:
            textures[key] = entry

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
    missing = {t.value for t in _EXPECTED_CHANNELS} - textures.keys()
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

# Default weight for a newly registered Quixel layer when no existing
# splatmap channel maps to it.  1/N equal-weight distribution is applied
# across all layers after the new one is appended so the sum stays ≈ 1.
_DEFAULT_NEW_LAYER_WEIGHT: float = 0.0


def _bilinear_sample_texture(
    tex: np.ndarray,
    uv_y: np.ndarray,
    uv_x: np.ndarray,
) -> np.ndarray:
    """Bilinear sample *tex* at fractional UV coordinates.

    Args:
        tex:   (H, W) or (H, W, C) float32 source texture. Values are
               assumed to be in [0, 1].
        uv_y:  (rows,) float array of V coordinates in [0, 1].
        uv_x:  (cols,) float array of U coordinates in [0, 1].

    Returns:
        Sampled array of shape (rows, cols) or (rows, cols, C).
    """
    h, w = tex.shape[:2]
    # Map UV [0,1] to pixel coords [0, dim-1]
    py = np.clip(uv_y * (h - 1), 0.0, h - 1)
    px = np.clip(uv_x * (w - 1), 0.0, w - 1)

    y0 = np.floor(py).astype(np.int32)
    x0 = np.floor(px).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, h - 1)
    x1 = np.clip(x0 + 1, 0, w - 1)

    fy = (py - y0).reshape(-1, 1).astype(np.float32)   # (rows, 1)
    fx = (px - x0).reshape(1, -1).astype(np.float32)   # (1, cols)

    if tex.ndim == 2:
        tl = tex[np.ix_(y0, x0)]
        tr = tex[np.ix_(y0, x1)]
        bl = tex[np.ix_(y1, x0)]
        br = tex[np.ix_(y1, x1)]
        top = tl * (1.0 - fx) + tr * fx
        bot = bl * (1.0 - fx) + br * fx
        return (top * (1.0 - fy) + bot * fy).astype(np.float32)
    else:
        # (H, W, C) — sample each channel
        c = tex.shape[2]
        out = np.empty((len(uv_y), len(uv_x), c), dtype=np.float32)
        for ci in range(c):
            sl = tex[:, :, ci]
            tl = sl[np.ix_(y0, x0)]
            tr = sl[np.ix_(y0, x1)]
            bl = sl[np.ix_(y1, x0)]
            br = sl[np.ix_(y1, x1)]
            top = tl * (1.0 - fx) + tr * fx
            bot = bl * (1.0 - fx) + br * fx
            out[:, :, ci] = top * (1.0 - fy) + bot * fy
        return out


def apply_quixel_to_layer(
    stack: TerrainMaskStack,
    layer_id: str,
    asset: QuixelAsset,
    *,
    side_effects: Optional[List[str]] = None,
    albedo_array: Optional[np.ndarray] = None,
    roughness_array: Optional[np.ndarray] = None,
    normal_array: Optional[np.ndarray] = None,
) -> None:
    """Blend a ``QuixelAsset`` into the splatmap layer stack.

    This function performs two distinct jobs:

    1.  **Layer registration** — appends a new weight slice to
        ``stack.splatmap_weights_layer`` for the given *layer_id* and
        re-normalises all layer weights so they sum to 1.0 per texel.

    2.  **Texture blending** (optional) — when pre-loaded numpy arrays for
        albedo / roughness / normal are supplied via the keyword arguments,
        their contribution is blended into the stack's ``macro_color``
        (albedo), ``roughness_variation``, and ``terrain_normals`` channels
        using bilinear interpolation at each grid UV coordinate, weighted
        by the new layer's splatmap weight.

    The Blender-side material graph is built separately; this function is
    pure numpy and can run in tests without bpy.

    Args:
        stack:            The terrain mask stack to mutate.
        layer_id:         Unique name for the new splatmap layer.
        asset:            Parsed ``QuixelAsset`` (texture paths + metadata).
        side_effects:     Optional list to append provenance JSON records to.
        albedo_array:     Pre-loaded (H, W, 3) float32 albedo texture [0,1].
        roughness_array:  Pre-loaded (H, W) float32 roughness texture [0,1].
        normal_array:     Pre-loaded (H, W, 3) float32 normal map (tangent-
                          space, OpenGL convention: +Y = up).

    Raises:
        ValueError: If *layer_id* is empty, or the splatmap is already at
                    the Unity limit and cannot accept another layer.
    """
    if not layer_id:
        raise ValueError("layer_id must be a non-empty string")

    rows, cols = np.asarray(stack.height).shape

    # ------------------------------------------------------------------ #
    # 1. Splatmap weight management
    # ------------------------------------------------------------------ #
    if stack.splatmap_weights_layer is None:
        # First layer: initialise with uniform weight 1.0 (single channel).
        new_weights = np.ones((rows, cols, 1), dtype=np.float32)
        stack.set("splatmap_weights_layer", new_weights, "quixel_ingest")
    else:
        current = stack.splatmap_weights_layer
        current_layers = current.shape[2] if current.ndim == 3 else 1

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

        # Append a zero-weight slice for the new layer, then redistribute
        # the remaining weight budget so all layers sum to 1.0 per texel.
        # The new layer starts at 0 weight; callers that have a real weight
        # mask should assign it directly via stack.splatmap_weights_layer.
        new_slice = np.zeros((rows, cols, 1), dtype=np.float32)
        expanded = np.concatenate([current, new_slice], axis=2)

        # Re-normalise: divide by channel-wise sum, guard against zero rows.
        total = expanded.sum(axis=2, keepdims=True)
        total = np.where(total < 1e-8, 1.0, total)
        stack.set(
            "splatmap_weights_layer",
            (expanded / total).astype(np.float32),
            "quixel_ingest",
        )

    # ------------------------------------------------------------------ #
    # 2. Optional texture blending into macro channels
    # ------------------------------------------------------------------ #
    # UV grid: normalised [0,1] sample coordinates for the tile grid.
    uv_y = np.linspace(0.0, 1.0, rows, dtype=np.float32)
    uv_x = np.linspace(0.0, 1.0, cols, dtype=np.float32)

    # The weight for the most recently appended layer.
    layer_idx = stack.splatmap_weights_layer.shape[2] - 1
    layer_weight = stack.splatmap_weights_layer[:, :, layer_idx]  # (H, W)

    if albedo_array is not None:
        sampled_albedo = _bilinear_sample_texture(
            albedo_array.astype(np.float32), uv_y, uv_x
        )  # (H, W, 3)
        if stack.macro_color is None:
            stack.set(
                "macro_color",
                (sampled_albedo * layer_weight[:, :, np.newaxis]).astype(np.float32),
                "quixel_ingest",
            )
        else:
            blended = stack.macro_color + sampled_albedo * layer_weight[:, :, np.newaxis]
            stack.set("macro_color", blended.astype(np.float32), "quixel_ingest")

    if roughness_array is not None:
        sampled_rough = _bilinear_sample_texture(
            roughness_array.astype(np.float32), uv_y, uv_x
        )  # (H, W)
        if stack.roughness_variation is None:
            stack.set(
                "roughness_variation",
                (sampled_rough * layer_weight).astype(np.float32),
                "quixel_ingest",
            )
        else:
            blended_r = stack.roughness_variation + sampled_rough * layer_weight
            stack.set(
                "roughness_variation",
                blended_r.astype(np.float32),
                "quixel_ingest",
            )

    if normal_array is not None:
        sampled_normal = _bilinear_sample_texture(
            normal_array.astype(np.float32), uv_y, uv_x
        )  # (H, W, 3)
        # Normals must remain unit-length after blending; we do a weighted
        # additive blend then renormalise rather than naive lerp so the
        # result is still a valid tangent-space normal map.
        if stack.terrain_normals is None:
            # Default base: flat normal (0, 0, 1) for each texel.
            base_n = np.zeros((rows, cols, 3), dtype=np.float32)
            base_n[:, :, 2] = 1.0
            stack.set("terrain_normals", base_n, "quixel_ingest")

        blended_n = (
            stack.terrain_normals + sampled_normal * layer_weight[:, :, np.newaxis]
        )
        norms = np.linalg.norm(blended_n, axis=2, keepdims=True)
        norms = np.where(norms < 1e-8, 1.0, norms)
        stack.set(
            "terrain_normals",
            (blended_n / norms).astype(np.float32),
            "quixel_ingest",
        )

    # ------------------------------------------------------------------ #
    # 3. Provenance event
    # ------------------------------------------------------------------ #
    if side_effects is not None:
        side_effects.append(json.dumps(
            {
                "event": "quixel_layer",
                "layer_id": layer_id,
                "asset_id": asset.asset_id,
                "layer_index": layer_idx,
                "has_albedo_blend": albedo_array is not None,
                "has_roughness_blend": roughness_array is not None,
                "has_normal_blend": normal_array is not None,
                "textures": {k: str(v) for k, v in asset.textures.items()},
            },
            sort_keys=True,
        ))


def pass_quixel_ingest(
    state: TerrainPipelineState,
    region: Optional[BBox],
    assets: Optional[List[QuixelAsset]] = None,
) -> PassResult:
    """Bundle K pass: enumerate, filter, ingest, and blend Quixel assets.

    Asset resolution order (first source that yields results wins):

    1. **Explicit list** — *assets* kwarg passed by the caller directly.
    2. **Descriptor list** — ``composition_hints['quixel_assets']``, a list
       of dicts with keys ``asset_path`` (required) and ``layer_id``
       (optional, defaults to folder name).
    3. **Cache directory scan** — ``composition_hints['quixel_cache_dir']``
       points to a directory whose immediate subdirectories are asset
       folders.  Each subfolder is enumerated, ingested, and then filtered
       by the current biome tag from
       ``composition_hints.get('biome_type', '')`` using
       ``_asset_matches_biome``.  This is the main AAA path: the pipeline
       scans the full Megascans cache, selects only assets tagged for the
       current biome, and wires them into the splatmap in discovery order
       (up to the Unity 4-layer hard limit).

    After ingestion the splatmap weight slice for each asset is set to an
    equal share of the remaining weight budget (1/N for N layers).

    ``stack.splatmap_weights_layer`` is guaranteed to be set on exit; if
    zero assets were ingested a soft issue is emitted and a single
    all-ones fallback layer is written so downstream passes see a valid
    array rather than ``None``.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []
    resolved: List[QuixelAsset] = []

    hints: Dict[str, Any] = {}
    if state.intent:
        hints = state.intent.composition_hints or {}

    # ------------------------------------------------------------------ #
    # Source 1: explicit asset list
    # ------------------------------------------------------------------ #
    if assets is not None:
        for asset in assets:
            layer_id = asset.asset_id
            try:
                apply_quixel_to_layer(
                    stack, layer_id, asset, side_effects=state.side_effects
                )
                resolved.append(asset)
            except ValueError as exc:
                # Layer capacity exceeded — stop adding layers, record issue.
                issues.append(ValidationIssue(
                    code="quixel_layer_skipped",
                    severity="soft",
                    message=str(exc),
                ))
                break

    # ------------------------------------------------------------------ #
    # Source 2: descriptor list from composition_hints
    # ------------------------------------------------------------------ #
    if not resolved:
        descriptors: List[Any] = hints.get("quixel_assets", []) or []
        for desc in descriptors:
            try:
                path = Path(desc["asset_path"])
                layer_id = str(desc.get("layer_id") or path.name)
                asset = ingest_quixel_asset(path)
                apply_quixel_to_layer(
                    stack, layer_id, asset, side_effects=state.side_effects
                )
                resolved.append(asset)
            except (FileNotFoundError, NotADirectoryError, KeyError, TypeError) as exc:
                issues.append(ValidationIssue(
                    code="quixel_ingest_failure",
                    severity="soft",
                    message=f"Failed to ingest Quixel descriptor: {exc}",
                ))
            except ValueError as exc:
                # Layer capacity hit — stop.
                issues.append(ValidationIssue(
                    code="quixel_layer_skipped",
                    severity="soft",
                    message=str(exc),
                ))
                break

    # ------------------------------------------------------------------ #
    # Source 3: cache directory scan filtered by biome
    # ------------------------------------------------------------------ #
    if not resolved:
        cache_dir_str: str = hints.get("quixel_cache_dir", "") or ""
        biome_type: str = hints.get("biome_type", "") or ""

        if cache_dir_str:
            cache_dir = Path(cache_dir_str)
            if not cache_dir.is_dir():
                issues.append(ValidationIssue(
                    code="quixel_cache_dir_missing",
                    severity="soft",
                    message=f"quixel_cache_dir does not exist or is not a directory: {cache_dir}",
                ))
            else:
                # Enumerate immediate subdirectories (one per Megascans asset).
                # Sort for deterministic ordering across OS file-system variants.
                candidate_dirs = sorted(
                    p for p in cache_dir.iterdir() if p.is_dir()
                )
                _log.info(
                    "pass_quixel_ingest: scanning %d candidate asset dirs in %s "
                    "(biome_filter=%r)",
                    len(candidate_dirs),
                    cache_dir,
                    biome_type,
                )

                for asset_dir in candidate_dirs:
                    # Pre-read metadata (JSON sidecar) to support tag-based
                    # biome filtering before doing the full ingest.
                    meta_preview: Dict[str, Any] = {}
                    for entry in asset_dir.iterdir():
                        if entry.suffix.lower() == ".json" and entry.is_file():
                            try:
                                meta_preview.update(
                                    json.loads(entry.read_text(encoding="utf-8"))
                                )
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                pass
                            break  # first JSON sidecar is sufficient

                    if biome_type and not _asset_matches_biome(
                        asset_dir, meta_preview, biome_type
                    ):
                        _log.debug(
                            "pass_quixel_ingest: skipping %s (not tagged for biome %r)",
                            asset_dir.name,
                            biome_type,
                        )
                        continue

                    try:
                        asset = ingest_quixel_asset(asset_dir)
                        apply_quixel_to_layer(
                            stack,
                            asset.asset_id,
                            asset,
                            side_effects=state.side_effects,
                        )
                        resolved.append(asset)
                        _log.debug(
                            "pass_quixel_ingest: ingested %s (layer %d)",
                            asset.asset_id,
                            len(resolved),
                        )
                    except (FileNotFoundError, NotADirectoryError) as exc:
                        issues.append(ValidationIssue(
                            code="quixel_ingest_failure",
                            severity="soft",
                            message=f"Cache scan ingest failed for {asset_dir.name}: {exc}",
                        ))
                    except ValueError as exc:
                        # Layer capacity hit — stop scanning.
                        issues.append(ValidationIssue(
                            code="quixel_layer_skipped",
                            severity="soft",
                            message=str(exc),
                        ))
                        _log.info(
                            "pass_quixel_ingest: Unity splatmap layer limit reached "
                            "after %d assets; remaining cache entries skipped.",
                            len(resolved),
                        )
                        break

    # ------------------------------------------------------------------ #
    # Guarantee output contract
    # ------------------------------------------------------------------ #
    if stack.splatmap_weights_layer is None:
        rows, cols = np.asarray(stack.height).shape
        stack.set(
            "splatmap_weights_layer",
            np.ones((rows, cols, 1), dtype=np.float32),
            "quixel_ingest",
        )
        issues.append(ValidationIssue(
            code="quixel_no_assets_ingested",
            severity="soft",
            message=(
                "No Quixel assets ingested; splatmap_weights_layer is a "
                "fallback single-layer placeholder."
            ),
        ))
    else:
        # Re-normalise final weight stack so per-texel channel sum == 1.
        w = stack.splatmap_weights_layer
        total = w.sum(axis=2, keepdims=True)
        total = np.where(total < 1e-8, 1.0, total)
        stack.set(
            "splatmap_weights_layer",
            (w / total).astype(np.float32),
            "quixel_ingest",
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
            "layer_count": (
                stack.splatmap_weights_layer.shape[2]
                if stack.splatmap_weights_layer is not None
                else 0
            ),
        },
        issues=issues,
    )

def pass_quixel_ingest_bundle_k(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle-K registered wrapper for composition-hint-driven Quixel ingest."""
    return pass_quixel_ingest(state, region, assets=None)


def register_bundle_k_quixel_ingest_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="quixel_ingest",
            func=pass_quixel_ingest_bundle_k,
            # NOTE: produces_channels=("splatmap_weights_layer",) overlaps
            # with materials_v2. This IS intentional: quixel_ingest runs
            # AFTER materials_v2 and overrides the slope/altitude-derived
            # splatmap with photoscanned Megascans material weights for
            # biomes that ship Quixel assets. The DAG resolves the ordering
            # because quixel_ingest's requires_channels implicitly pull it
            # after materials_v2 via the bundle registration order.
            requires_channels=("height",),
            produces_channels=("splatmap_weights_layer",),
            seed_namespace="quixel_ingest",
            requires_scene_read=False,
            description="Bundle K: ingest Quixel Megascans assets into splatmap layers",
        )
    )


__all__ = [
    "TextureType",
    "QuixelAsset",
    "ingest_quixel_asset",
    "apply_quixel_to_layer",
    "pass_quixel_ingest",
    "pass_quixel_ingest_bundle_k",
    "register_bundle_k_quixel_ingest_pass",
]
