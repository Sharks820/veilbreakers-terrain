"""TerrainTextureLayerStack — per-layer PBR texture management.

Holds the per-layer albedo / normal / roughness / displacement / AO arrays
for a terrain tile alongside a weight map that drives splatmap blending.
Used by terrain_quixel_ingest, terrain_materials_v2, and terrain_unity_export
to express the full PBR texture stack as typed Python dataclasses rather than
loose dict keys on the mask stack.

Pure numpy — no bpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class TextureLayer:
    layer_id: str
    terrain_mask_source: str           # channel name driving this layer
    weight_map: Optional[np.ndarray]   # normalized [0,1] per-pixel weight
    albedo: Optional[np.ndarray] = None
    normal: Optional[np.ndarray] = None
    roughness: Optional[np.ndarray] = None
    height_displacement: Optional[np.ndarray] = None
    ambient_occlusion: Optional[np.ndarray] = None
    metallic: float = 0.0
    color_space: str = "sRGB"          # "sRGB" for albedo, "Linear" for others
    tiling_scale: float = 1.0
    texel_density_m: float = 0.1       # meters per texel
    no_displacement_reason: str = ""   # if height_displacement is None, why


@dataclass
class TerrainTextureLayerStack:
    # FUTURE USE: PBR layer stack consumed by terrain_quixel_ingest,
    # terrain_materials_v2, and terrain_unity_export — no direct production
    # callers outside those modules yet; wiring is in progress as part of the
    # MicroSplat texturing upgrade (see docs/AAA_MASTER_IMPLEMENTATION_GUIDE_2026_04_27.md).
    layers: list[TextureLayer] = field(default_factory=list)

    def add_layer(self, layer: TextureLayer) -> None:
        self.layers.append(layer)

    def validate(self) -> list[str]:
        issues = []
        for layer in self.layers:
            if layer.weight_map is None:
                issues.append(f"{layer.layer_id}: missing weight_map")
            if layer.normal is None:
                issues.append(f"{layer.layer_id}: missing normal map")
            if layer.roughness is None:
                issues.append(f"{layer.layer_id}: missing roughness")
            if layer.ambient_occlusion is None:
                issues.append(f"{layer.layer_id}: missing AO (recommend adding)")
            if layer.height_displacement is None and not layer.no_displacement_reason:
                issues.append(f"{layer.layer_id}: missing displacement, set no_displacement_reason if intentional")
            if layer.weight_map is not None:
                w = layer.weight_map
                if not (-1e-5 <= w.min() and w.max() <= 1.0 + 1e-5):
                    issues.append(f"{layer.layer_id}: weight_map out of [0,1] range")
        return issues

    def normalized_weights(self) -> np.ndarray:
        """Return per-pixel normalized weight array (H, W, N_layers)."""
        if not self.layers:
            return np.zeros((1, 1, 0), dtype=np.float32)
        h, w = self.layers[0].weight_map.shape[:2]
        stack = np.stack([
            l.weight_map if l.weight_map is not None else np.zeros((h, w), dtype=np.float32)
            for l in self.layers
        ], axis=-1)
        total = stack.sum(axis=-1, keepdims=True)
        total = np.where(total < 1e-8, 1.0, total)
        return stack / total


__all__ = [
    "TextureLayer",
    "TerrainTextureLayerStack",
]
