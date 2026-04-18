"""Bundle K — terrain_stochastic_shader.

Implements stochastic (histogram-preserving) tile-sampling offsets used to
break visible tiling in terrain PBR layers. The core idea is from Heitz &
Neyret 2018 "High-Performance By-Example Noise using a Histogram-Preserving
Blending Operator" — we don't reproduce the full shader here, but we:

1. Compute a per-cell UV offset vector (float32) that a Shader Graph sampler
   can use to shift a tileable texture.
2. Provide a `StochasticShaderTemplate` dataclass that carries the shader
   parameters Unity needs to reconstruct the sampling mask.
3. Export a minimal Shader Graph JSON stub (schema-v1) that documents the
   template for the Unity importer.

Pure numpy, no bpy.
"""

from __future__ import annotations

import json
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
)


@dataclass
class StochasticShaderTemplate:
    """Parameters describing a stochastic-tiling shader configuration.

    Consumed by the Unity Shader Graph importer. ``tile_size_m`` is the
    world-space extent of one texture tile. ``randomness_strength`` scales
    the per-cell UV offset (0 = pure tiling, 1 = full Heitz-Neyret offset).

    ``blend_weights`` must sum to 1.0 (validated in ``__post_init__``).
    ``stochastic_seed`` drives the per-tile random hash fed to the sampler.
    ``blend_sharpness`` controls the triangular-basis blend kernel width.
    """

    template_id: str
    tile_size_m: float = 4.0
    randomness_strength: float = 0.75
    histogram_preserving: bool = True
    layer_index: int = 0
    notes: str = ""
    stochastic_seed: int = 0
    blend_sharpness: float = 2.0
    blend_weights: List[float] = field(default_factory=lambda: [1.0])

    def __post_init__(self) -> None:
        if self.tile_size_m <= 0.0:
            raise ValueError(f"tile_size_m must be > 0, got {self.tile_size_m}")
        if not (0.0 <= self.randomness_strength <= 1.0):
            raise ValueError(
                f"randomness_strength must be in [0, 1], got {self.randomness_strength}"
            )
        if self.blend_sharpness <= 0.0:
            raise ValueError(f"blend_sharpness must be > 0, got {self.blend_sharpness}")
        if not self.blend_weights:
            raise ValueError("blend_weights must be a non-empty list")
        total = sum(self.blend_weights)
        if abs(total - 1.0) > 1e-4:
            raise ValueError(
                f"blend_weights must sum to 1.0, got sum={total:.6f}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "tile_size_m": float(self.tile_size_m),
            "randomness_strength": float(self.randomness_strength),
            "histogram_preserving": bool(self.histogram_preserving),
            "layer_index": int(self.layer_index),
            "notes": self.notes,
            "stochastic_seed": int(self.stochastic_seed),
            "blend_sharpness": float(self.blend_sharpness),
            "blend_weights": [float(w) for w in self.blend_weights],
        }


def _fbm_noise_array(
    rows: int,
    cols: int,
    seed: int,
    octaves: int = 4,
    frequency: float = 1.0,
    persistence: float = 0.5,
    lacunarity: float = 2.0,
) -> np.ndarray:
    """Generate a (rows, cols) fBm noise array in [0, 1] using the project
    permutation-table noise backend. Deterministic for fixed seed/params."""
    from ._terrain_noise import _make_noise_generator

    gen = _make_noise_generator(int(seed) & 0x7FFFFFFF)
    # Coordinate grids — one unit = one cell at base frequency
    yr = np.linspace(0.0, rows * frequency, rows, endpoint=False, dtype=np.float64)
    xr = np.linspace(0.0, cols * frequency, cols, endpoint=False, dtype=np.float64)
    xs, ys = np.meshgrid(xr, yr)

    result = np.zeros((rows, cols), dtype=np.float64)
    amplitude = 1.0
    max_amp = 0.0
    freq = 1.0
    for _ in range(octaves):
        result += amplitude * gen.noise2_array(xs * freq, ys * freq)
        max_amp += amplitude
        amplitude *= persistence
        freq *= lacunarity

    # Normalise to [0, 1]
    result /= max(max_amp, 1e-12)
    result = (result + 1.0) * 0.5
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def build_stochastic_sampling_mask(
    stack: TerrainMaskStack,
    tile_size_m: float,
    seed: int,
    coverage_fraction: float = 0.5,
    use_voronoi: bool = False,
) -> np.ndarray:
    """Return a (H, W, 2) float32 UV-offset mask that breaks visible tiling.

    Strategy A (default, ``use_voronoi=False``):
      Build an fBm noise map at tile frequency (4 octaves).  Threshold it so
      that ``coverage_fraction`` of cells are in the "active" zone
      (noise_map > threshold).  The (u, v) channels carry bilinear-upsampled
      per-tile random offsets in [-0.5, 0.5]; the mask selects which cells
      receive the full offset vs a reduced version, giving locality-coherent
      stochastic sampling as in Heitz-Neyret 2018.

    Strategy B (``use_voronoi=True``):
      Partition the tile into a Voronoi grid (one seed point per tile cell).
      Each Voronoi cell gets a random (u, v) offset.  This gives hard-cell
      boundaries, matching UE5's "Voronoi stochastic tiling" node.

    Parameters
    ----------
    stack : TerrainMaskStack
        Must have ``height`` populated (used for shape/cell_size only).
    tile_size_m : float
        World-space size of one tileable texture tile.
    seed : int
        Deterministic seed.
    coverage_fraction : float
        Target fraction of cells in the active mask zone (fBm path only).
    use_voronoi : bool
        If True, use grid-based Voronoi cell assignment instead of fBm.

    Returns
    -------
    np.ndarray
        Shape (H, W, 2), dtype float32. Channel 0 = U offset, channel 1 = V
        offset, both in [-0.5, 0.5].
    """
    if stack.height is None:
        raise ValueError("build_stochastic_sampling_mask requires stack.height")
    if tile_size_m <= 0.0:
        raise ValueError(f"tile_size_m must be > 0, got {tile_size_m}")
    if not (0.0 < coverage_fraction <= 1.0):
        raise ValueError(f"coverage_fraction must be in (0, 1], got {coverage_fraction}")

    h = np.asarray(stack.height)
    rows, cols = h.shape
    cell_m = float(stack.cell_size)

    # Number of tile repetitions across the heightmap
    tiles_y = max(2, int(np.ceil(rows * cell_m / tile_size_m)) + 2)
    tiles_x = max(2, int(np.ceil(cols * cell_m / tile_size_m)) + 2)

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)

    if use_voronoi:
        # --- Voronoi cell-pattern mask -----------------------------------
        # Place one random seed point per tile cell, assign each pixel to its
        # nearest tile-seed, then read the offset stored at that seed.
        tile_seed_u = rng.uniform(-0.5, 0.5, size=(tiles_y, tiles_x)).astype(np.float32)
        tile_seed_v = rng.uniform(-0.5, 0.5, size=(tiles_y, tiles_x)).astype(np.float32)

        # Cell-index grid: which tile does each pixel belong to?
        row_tile_idx = np.floor(
            np.arange(rows, dtype=np.float64) * cell_m / tile_size_m
        ).astype(np.int32)
        col_tile_idx = np.floor(
            np.arange(cols, dtype=np.float64) * cell_m / tile_size_m
        ).astype(np.int32)
        row_tile_idx = np.clip(row_tile_idx, 0, tiles_y - 1)
        col_tile_idx = np.clip(col_tile_idx, 0, tiles_x - 1)

        u = tile_seed_u[np.ix_(row_tile_idx, col_tile_idx)]
        v = tile_seed_v[np.ix_(row_tile_idx, col_tile_idx)]
    else:
        # --- fBm noise mask (default) ------------------------------------
        # Tile frequency: one noise cycle per tile footprint
        tile_freq = cell_m / tile_size_m  # cycles per cell
        noise_map = _fbm_noise_array(
            rows, cols, seed=seed, octaves=4, frequency=tile_freq,
            persistence=0.5, lacunarity=2.0,
        )
        # Threshold calibrated to cover coverage_fraction of cells
        threshold = float(np.percentile(noise_map, (1.0 - coverage_fraction) * 100.0))
        active = (noise_map > threshold).astype(np.float32)  # noqa: F841 (kept for callers)

        # Per-tile bilinear offset grid (matches Heitz-Neyret triangular basis)
        grid_u = rng.uniform(-0.5, 0.5, size=(tiles_y, tiles_x)).astype(np.float64)
        grid_v = rng.uniform(-0.5, 0.5, size=(tiles_y, tiles_x)).astype(np.float64)

        ys_lin = np.linspace(0.0, tiles_y - 1.0, rows)
        xs_lin = np.linspace(0.0, tiles_x - 1.0, cols)
        y0 = np.floor(ys_lin).astype(np.int32)
        x0 = np.floor(xs_lin).astype(np.int32)
        y1 = np.clip(y0 + 1, 0, tiles_y - 1)
        x1 = np.clip(x0 + 1, 0, tiles_x - 1)
        ty = (ys_lin - y0).reshape(-1, 1)
        tx = (xs_lin - x0).reshape(1, -1)

        def _bilinear(g: np.ndarray) -> np.ndarray:
            a = g[np.ix_(y0, x0)]
            b = g[np.ix_(y0, x1)]
            c = g[np.ix_(y1, x0)]
            d = g[np.ix_(y1, x1)]
            return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty

        base_u = _bilinear(grid_u).astype(np.float32)
        base_v = _bilinear(grid_v).astype(np.float32)

        # Cells outside active zone get a half-strength offset for smoothness
        u = base_u * (active * 1.0 + (1.0 - active) * 0.5)
        v = base_v * (active * 1.0 + (1.0 - active) * 0.5)

    return np.stack([u, v], axis=-1).astype(np.float32)


_REQUIRED_UNITY_SHADER_PROPERTIES = {
    "_BaseMap",
    "_BumpMap",
    "_MetallicGlossMap",
    "_OcclusionMap",
    "_StochasticSeed",
    "_BlendSharpness",
    "_RandomnessStrength",
    "_TileSize",
}


def export_unity_shader_template(
    template: StochasticShaderTemplate,
    output_path: Path,
) -> Dict[str, Any]:
    """Emit a Unity Shader Graph JSON manifest for the stochastic template.

    Produces a schema-v1 manifest that the Unity-side terrain importer reads
    to reconstruct the stochastic sampler node graph.  All required Unity
    shader property names are validated before writing.

    Required properties (Unity naming convention):
      _BaseMap, _BumpMap, _MetallicGlossMap, _OcclusionMap,
      _StochasticSeed, _BlendSharpness, _RandomnessStrength, _TileSize

    Returns the dict that was written so callers can inspect without re-reading
    the file.

    Raises
    ------
    ValueError
        If any required Unity shader property is absent from the generated
        payload.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tpl = template.to_dict()

    properties: Dict[str, Any] = {
        "_BaseMap": {"type": "Texture2D", "default": "white"},
        "_BumpMap": {"type": "Texture2D", "default": "bump"},
        "_MetallicGlossMap": {"type": "Texture2D", "default": "white"},
        "_OcclusionMap": {"type": "Texture2D", "default": "white"},
        "_StochasticSeed": {"type": "Float", "default": tpl["stochastic_seed"]},
        "_BlendSharpness": {"type": "Float", "default": tpl["blend_sharpness"]},
        "_RandomnessStrength": {"type": "Float", "default": tpl["randomness_strength"]},
        "_TileSize": {"type": "Float", "default": tpl["tile_size_m"]},
    }

    stochastic_params: Dict[str, Any] = {
        "histogram_preserving": tpl["histogram_preserving"],
        "blend_weights": tpl["blend_weights"],
        "layer_index": tpl["layer_index"],
    }

    texture_channels: List[str] = ["Albedo", "Normal", "MetallicSmoothness", "AO"]

    payload: Dict[str, Any] = {
        "schema": "veilbreakers.terrain.stochastic_shader/v1",
        "shader_name": f"VeilBreakers/TerrainLit_Stochastic_{tpl['template_id']}",
        "shader_graph_type": "ShaderGraph/TerrainLit_Stochastic",
        "template": tpl,
        "properties": properties,
        "stochastic_params": stochastic_params,
        "texture_channels": texture_channels,
        "inputs": {
            "SamplingMask": "Texture2D_float2",
            "TileSize": "Float",
            "RandomnessStrength": "Float",
        },
        "outputs": {
            "Albedo": "Vector3",
            "Roughness": "Float",
            "Normal": "Vector3",
            "Metallic": "Float",
            "AO": "Float",
        },
    }

    # Validate all required Unity shader properties are present
    missing = _REQUIRED_UNITY_SHADER_PROPERTIES - set(payload["properties"].keys())
    if missing:
        raise ValueError(
            f"export_unity_shader_template: missing required Unity shader "
            f"properties: {sorted(missing)}"
        )

    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def pass_stochastic_shader(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle K pass: build stochastic UV offset mask and store on the stack.

    Consumes: height
    Produces: stochastic_uv_mask (H, W, 2) float32 UV offsets stored on the
              stack via stack.set(); roughness_variation updated with offset
              magnitude as a perceptible downstream signal.

    The full (H, W, 2) mask is stored under ``stochastic_uv_mask`` so the
    Unity exporter can retrieve it directly.  A scalar offset-magnitude layer
    is folded into ``roughness_variation`` so later passes see the stochastic
    signal without needing to know about the 2-channel mask format.
    """
    from .terrain_pipeline import derive_pass_seed

    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = state.intent.composition_hints if state.intent else {}
    tile_size_m = float(hints.get("stochastic_tile_size_m", 4.0))
    coverage_fraction = float(hints.get("stochastic_coverage_fraction", 0.5))
    use_voronoi = bool(hints.get("stochastic_use_voronoi", False))

    seed = derive_pass_seed(
        state.intent.seed if state.intent else 0,
        "stochastic_shader",
        state.tile_x,
        state.tile_y,
        region,
    )

    mask = build_stochastic_sampling_mask(
        stack,
        tile_size_m,
        seed,
        coverage_fraction=coverage_fraction,
        use_voronoi=use_voronoi,
    )

    # Store the full 2-channel UV mask on the stack
    # TerrainMaskStack.set accepts any ndarray; downstream exporters key on
    # "stochastic_uv_mask" to retrieve the (H, W, 2) float32 array.
    stack.set("stochastic_uv_mask", mask, "stochastic_shader")

    # Fold offset magnitude as a perturbation into roughness_variation so
    # downstream passes see the stochastic signal through normal channels.
    magnitude = np.sqrt(mask[..., 0] ** 2 + mask[..., 1] ** 2).astype(np.float32)
    existing = stack.get("roughness_variation")
    if existing is None:
        rough = magnitude * 0.1
    else:
        rough = np.asarray(existing, dtype=np.float32) + magnitude * 0.02
    stack.set("roughness_variation", rough.astype(np.float32), "stochastic_shader")

    return PassResult(
        pass_name="stochastic_shader",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("stochastic_uv_mask", "roughness_variation"),
        metrics={
            "tile_size_m": tile_size_m,
            "coverage_fraction": coverage_fraction,
            "use_voronoi": use_voronoi,
            "mask_shape": list(mask.shape),
            "offset_mean_abs": float(np.mean(np.abs(mask))),
            "seed_used": int(seed),
        },
        issues=[],
        seed_used=int(seed),
    )


def register_bundle_k_stochastic_shader_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="stochastic_shader",
            func=pass_stochastic_shader,
            requires_channels=("height",),
            produces_channels=("stochastic_uv_mask", "roughness_variation"),
            seed_namespace="stochastic_shader",
            requires_scene_read=False,
            description="Bundle K: stochastic tile-sampling UV offsets (fBm + Voronoi)",
        )
    )


__all__ = [
    "StochasticShaderTemplate",
    "build_stochastic_sampling_mask",
    "export_unity_shader_template",
    "pass_stochastic_shader",
    "register_bundle_k_stochastic_shader_pass",
]
