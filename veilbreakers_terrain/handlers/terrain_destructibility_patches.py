"""Bundle Q — Destructibility patch detection.

Seeds destructible patches from ``rock_hardness`` and ``wetness``. Low
hardness + high wetness => soft patches that break quickly; high
hardness => durable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np

from .terrain_semantics import BBox, TerrainMaskStack


@dataclass
class DestructibilityPatch:
    """A single destructible terrain patch."""

    bounds: BBox
    hp: float
    material_id: int
    debris_type: str


def detect_destructibility_patches(
    stack: TerrainMaskStack,
    *,
    min_patch_area: int = 4,
    hardness_threshold: float = 0.6,
    wetness_threshold: float = 0.65,
    slope_threshold_rad: float = 0.61,  # ~35°
) -> List[DestructibilityPatch]:
    """Detect destructible patches using connected-component segmentation.

    Builds a soft-terrain mask combining low rock hardness, high wetness,
    and steep slopes (fragile on precipices). Segments the mask via
    scipy.ndimage.label (4-connected) so each returned patch represents a
    physically contiguous destructible region rather than an arbitrary grid cell.
    Falls back to 8x8 grid scan when scipy is absent.

    Args:
        min_patch_area: Minimum cell count; smaller components are discarded.
        hardness_threshold: Rock hardness below which a cell is soft.
        wetness_threshold: Wetness above which a cell is considered saturated.
        slope_threshold_rad: Slope (radians) above which steep cells augment
            the soft mask when hardness < 0.8 (rockfall-prone).
    """
    if stack.rock_hardness is None or stack.height is None:
        return []

    hardness = np.asarray(stack.rock_hardness, dtype=np.float32)
    wetness = (
        np.asarray(stack.wetness, dtype=np.float32)
        if stack.wetness is not None
        else np.zeros_like(hardness)
    )

    soft_mask = (hardness < hardness_threshold) | (wetness > wetness_threshold)

    if stack.slope is not None:
        steep = np.asarray(stack.slope) > slope_threshold_rad
        soft_mask = soft_mask | (steep & (hardness < 0.8))

    patches: List[DestructibilityPatch] = []

    try:
        from scipy.ndimage import label as _label

        struct4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.int32)
        labeled, n_labels = _label(soft_mask, structure=struct4)
        region_rows = np.where(labeled > 0)
        if n_labels == 0 or region_rows[0].size == 0:
            return patches

        # Vectorised stats per label using np.bincount
        flat = labeled.ravel()
        h_flat = hardness.ravel()
        w_flat = wetness.ravel()
        counts = np.bincount(flat, minlength=n_labels + 1)
        h_sums = np.bincount(flat, weights=h_flat.astype(np.float64), minlength=n_labels + 1)
        w_sums = np.bincount(flat, weights=w_flat.astype(np.float64), minlength=n_labels + 1)

        for lid in range(1, n_labels + 1):
            count = int(counts[lid])
            if count < min_patch_area:
                continue
            avg_h = float(h_sums[lid] / count)
            avg_w = float(w_sums[lid] / count)
            rows_idx, cols_idx = np.where(labeled == lid)
            r0, r1 = int(rows_idx.min()), int(rows_idx.max()) + 1
            c0, c1 = int(cols_idx.min()), int(cols_idx.max()) + 1

            hp = max(5.0, 10.0 + 190.0 * avg_h) * max(0.3, 1.0 - avg_w * 0.5)
            debris = "mud" if avg_w > 0.5 else ("gravel" if avg_h < 0.3 else "rock_chunk")
            material_id = (
                int(stack.biome_id[rows_idx[0], cols_idx[0]])
                if stack.biome_id is not None
                else 0
            )
            patches.append(
                DestructibilityPatch(
                    bounds=BBox(
                        stack.world_origin_x + c0 * stack.cell_size,
                        stack.world_origin_y + r0 * stack.cell_size,
                        stack.world_origin_x + c1 * stack.cell_size,
                        stack.world_origin_y + r1 * stack.cell_size,
                    ),
                    hp=float(hp),
                    material_id=material_id,
                    debris_type=debris,
                )
            )
    except ImportError:
        # Fallback: coarse 8x8 grid scan
        h_arr, w_arr = hardness.shape
        cell = max(1, min(8, min(h_arr, w_arr) // 4))
        for r0 in range(0, h_arr, cell):
            for c0 in range(0, w_arr, cell):
                r1, c1 = min(h_arr, r0 + cell), min(w_arr, c0 + cell)
                avg_h = float(hardness[r0:r1, c0:c1].mean())
                if avg_h >= hardness_threshold:
                    continue
                avg_w = float(wetness[r0:r1, c0:c1].mean())
                hp = max(5.0, 10.0 + 190.0 * avg_h) * max(0.3, 1.0 - avg_w * 0.5)
                debris = "mud" if avg_w > 0.5 else ("gravel" if avg_h < 0.3 else "rock_chunk")
                material_id = (
                    int(stack.biome_id[r0:r1, c0:c1].reshape(-1)[0])
                    if stack.biome_id is not None
                    else 0
                )
                patches.append(
                    DestructibilityPatch(
                        bounds=BBox(
                            stack.world_origin_x + c0 * stack.cell_size,
                            stack.world_origin_y + r0 * stack.cell_size,
                            stack.world_origin_x + c1 * stack.cell_size,
                            stack.world_origin_y + r1 * stack.cell_size,
                        ),
                        hp=float(hp),
                        material_id=material_id,
                        debris_type=debris,
                    )
                )
    return patches


def export_destructibility_json(
    patches: List[DestructibilityPatch],
    output_path: Path,
) -> None:
    """Write destructibility patches to JSON."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0",
        "patches": [
            {
                "bounds": list(p.bounds.to_tuple()),
                "hp": p.hp,
                "material_id": p.material_id,
                "debris_type": p.debris_type,
            }
            for p in patches
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2))
