"""Bundle K — terrain_shadow_clipmap_bake.

Bakes a per-cell sun-shadow mask by ray-marching the heightmap along the
sun direction. Produces a float32 (clipmap_res, clipmap_res) mask in [0, 1]
(1 = fully lit, 0 = in shadow). Populates ``cloud_shadow`` channel when
sun occlusion is used as a multiplier on top of cloud shadows (both fold
into the shader AO path in Unity).

Pure numpy ray march — not production-fast, but deterministic and
dependency-free. For production bakes use a Houdini/Bake shader.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


def _resample_height(h: np.ndarray, target: int) -> np.ndarray:
    """Bilinear resample a heightmap to (target, target)."""
    rows, cols = h.shape
    if rows == target and cols == target:
        return h.astype(np.float64)
    ys = np.linspace(0.0, rows - 1.0, target)
    xs = np.linspace(0.0, cols - 1.0, target)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, rows - 1)
    x1 = np.clip(x0 + 1, 0, cols - 1)
    ty = (ys - y0).reshape(-1, 1)
    tx = (xs - x0).reshape(1, -1)
    a = h[np.ix_(y0, x0)]
    b = h[np.ix_(y0, x1)]
    c = h[np.ix_(y1, x0)]
    d = h[np.ix_(y1, x1)]
    top = a * (1 - tx) + b * tx
    bot = c * (1 - tx) + d * tx
    return (top * (1 - ty) + bot * ty).astype(np.float64)


def bake_shadow_clipmap(
    stack: TerrainMaskStack,
    sun_dir_rad: Tuple[float, float],
    clipmap_res: int = 512,
    num_steps: int = 24,
) -> np.ndarray:
    """Ray-march sun shadows across the heightmap using a vectorised horizon scan.

    Parameters
    ----------
    sun_dir_rad : (azimuth_rad, elevation_rad)
        Azimuth is measured from world +X toward world +Y (counter-clockwise
        in XY plane). Elevation is angle above horizon in radians (must be > 0
        for the sun to cast shadows; <= 0 means everything is in shadow).
    clipmap_res : int
        Output resolution. The heightmap is bilinearly resampled to this size
        before the horizon scan.
    num_steps : int
        Number of ray-march steps cast from each cell toward the sun. More
        steps = softer penumbra and fewer missed occlusions at the cost of
        compute time.

    Algorithm
    ---------
    For each cell (r, c) we cast a ray in the horizontal direction opposite
    to the sun (i.e. toward where the sun is) and track a running maximum
    height along that ray. A cell is in shadow if any terrain sample along
    its sun-ray exceeds the height the ray would need to clear given the sun
    elevation. This is equivalent to the standard horizon-angle shadow test:

        shadow if  max_terrain_height_along_ray > h[r,c] + dist * tan(el)

    The implementation is fully numpy-vectorised — no Python loop over cells.
    The outer loop is only over ray steps (``num_steps`` iterations).

    Returns
    -------
    np.ndarray
        (clipmap_res, clipmap_res) float32 in [0, 1].
        1.0 = fully lit, 0.0 = fully in hard shadow.
    """
    if stack.height is None:
        raise ValueError("bake_shadow_clipmap requires stack.height")
    if clipmap_res <= 0:
        raise ValueError(f"clipmap_res must be > 0, got {clipmap_res}")

    az, el = float(sun_dir_rad[0]), float(sun_dir_rad[1])
    if el <= 0.0:
        # Sun at or below horizon — entire map in shadow
        return np.zeros((clipmap_res, clipmap_res), dtype=np.float32)

    h = _resample_height(np.asarray(stack.height, dtype=np.float64), clipmap_res)
    rows, cols = h.shape

    # World-space cell size at clipmap resolution
    tile_extent_m = float(stack.tile_size) * float(stack.cell_size)
    cell_m = tile_extent_m / max(clipmap_res, 1)

    # Sun direction in the horizontal plane (unit vector pointing toward sun)
    # dx/dy are in cell-index units; we walk opposite to the sun direction
    # to find what casts shadow onto each receiver cell.
    sun_dx = float(np.cos(az))   # column offset per step
    sun_dy = float(np.sin(az))   # row offset per step

    tan_el = float(np.tan(el))

    # Step size: aim for sub-cell resolution — ~0.5 cell per step up to 1 cell
    step_cells = max(0.5, cols / max(num_steps * 2, 1))

    # Receiver grid (all cells simultaneously)
    rr, cc = np.mgrid[0:rows, 0:cols].astype(np.float64)

    # Running maximum terrain horizon height seen along each cell's sun-ray.
    # Initialised to -inf so the first valid step always has a chance to shadow.
    running_max_h = np.full((rows, cols), -np.inf, dtype=np.float64)

    # Shadow accumulator: True where any step found the terrain above the ray
    shadowed = np.zeros((rows, cols), dtype=bool)

    for step in range(1, num_steps + 1):
        # World-space horizontal distance to this step along the sun ray
        dist_cells = step * step_cells
        dist_m = dist_cells * cell_m

        # Sample coordinates: walk in the direction of the sun from each cell
        sx = cc + sun_dx * dist_cells
        sy = rr + sun_dy * dist_cells

        # Only process in-bounds samples
        in_bounds = (sx >= 0) & (sx < cols - 1) & (sy >= 0) & (sy < rows - 1)

        sxi = np.clip(sx.astype(np.int32), 0, cols - 1)
        syi = np.clip(sy.astype(np.int32), 0, rows - 1)

        # Terrain height at the sampled location
        sampled_h = h[syi, sxi]

        # Update running max only for in-bounds cells
        np.maximum(running_max_h, np.where(in_bounds, sampled_h, running_max_h),
                   out=running_max_h)

        # A cell is occluded if the maximum sampled terrain height exceeds the
        # height the sun-ray would be at that horizontal distance:
        #   ray_height_at_dist = h[receiver] + dist_m * tan(el)
        ray_height = h + dist_m * tan_el
        newly_shadowed = in_bounds & (running_max_h > ray_height)
        shadowed |= newly_shadowed

    shadow_mask = np.where(shadowed, 0.0, 1.0).astype(np.float32)
    return shadow_mask


def export_shadow_clipmap_exr(mask: np.ndarray, output_path: Path) -> None:
    """Write a shadow clipmap to disk as a proper image file.

    Format priority (best to fallback):
      1. 16-bit half-float EXR via ``imageio`` (if available and path ends
         with ``.exr``).
      2. 16-bit half-float EXR via the ``OpenEXR`` + ``Imath`` package (if
         available).
      3. 16-bit PNG via ``imageio`` (normalised to uint16 range).
      4. Raw float32 ``.npy`` with a ``.json`` sidecar as a last resort
         (clearly labelled, not silently masquerading as EXR).

    The function *never* writes a raw binary blob without a format header —
    the old npy-with-.exr-extension behaviour is replaced by this hierarchy.

    A ``.json`` sidecar is always written alongside the output file recording
    the schema, actual format used, shape, dtype, and value range.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    arr_f16 = np.ascontiguousarray(mask, dtype=np.float16)
    arr_f32 = np.ascontiguousarray(mask, dtype=np.float32)
    rows, cols = arr_f32.shape
    written_format: str = "unknown"
    actual_path = output_path

    # --- Attempt 1: imageio EXR (half-float) ----------------------------
    _imageio_ok = False
    if output_path.suffix.lower() == ".exr":
        try:
            import imageio  # type: ignore[import]
            imageio.imwrite(str(output_path), arr_f16)
            written_format = "exr_float16_imageio"
            _imageio_ok = True
        except Exception:
            pass

    # --- Attempt 2: OpenEXR + Imath ------------------------------------
    if not _imageio_ok and output_path.suffix.lower() == ".exr":
        try:
            import OpenEXR  # type: ignore[import]
            import Imath  # type: ignore[import]
            header = OpenEXR.Header(cols, rows)
            header["channels"] = {"Y": Imath.Channel(Imath.PixelType(Imath.PixelType.HALF))}
            exr_file = OpenEXR.OutputFile(str(output_path), header)
            exr_file.writePixels({"Y": arr_f16.tobytes()})
            exr_file.close()
            written_format = "exr_float16_openexr"
            _imageio_ok = True
        except Exception:
            pass

    # --- Attempt 3: 16-bit PNG via imageio -----------------------------
    if not _imageio_ok:
        png_path = output_path.with_suffix(".png")
        try:
            import imageio  # type: ignore[import]
            # Normalise float [0,1] → uint16 [0, 65535]
            arr_u16 = (np.clip(arr_f32, 0.0, 1.0) * 65535.0).astype(np.uint16)
            imageio.imwrite(str(png_path), arr_u16)
            actual_path = png_path
            written_format = "png_uint16_imageio"
            _imageio_ok = True
        except Exception:
            pass

    # --- Fallback: float32 .npy with honest labelling ------------------
    if not _imageio_ok:
        npy_path = output_path.with_suffix(".npy")
        np.save(str(npy_path), arr_f32)
        actual_path = npy_path
        written_format = "float32_npy"

    sidecar = actual_path.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "schema": "veilbreakers.terrain.shadow_clipmap/v1",
                "format": written_format,
                "path": str(actual_path),
                "shape": list(arr_f32.shape),
                "dtype": "float16" if "float16" in written_format else "float32",
                "value_min": float(arr_f32.min()),
                "value_max": float(arr_f32.max()),
                "lit_fraction": float((arr_f32 > 0.5).mean()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def pass_shadow_clipmap(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle K pass: bake directional sun shadow clipmap.

    Sun direction is read from ``intent.composition_hints`` under the keys
    ``sun_azimuth_rad`` and ``sun_elevation_rad``.  Defaults are a
    mid-afternoon angle (az=0.6 rad ≈ 34°, el=0.85 rad ≈ 49°) that gives
    visible shadow contrast without being at zenith.

    Consumes: height
    Produces: shadow_map  — (H, W) float32 [0,1] hard shadow mask stored on
                            the stack under "shadow_map".
              cloud_shadow — if a cloud_shadow channel already exists it is
                            multiplied by the terrain shadow so both signals
                            compose correctly for the Unity AO shader path.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = state.intent.composition_hints if state.intent else {}

    # Sun direction: prefer composition_hints, then sensible defaults
    sun_az = float(hints.get("sun_azimuth_rad", 0.6))
    sun_el = float(hints.get("sun_elevation_rad", 0.85))

    h_arr = np.asarray(stack.height)
    rows, cols = h_arr.shape
    clipmap_res = int(hints.get("shadow_clipmap_res", max(32, rows)))
    num_steps = int(hints.get("shadow_clipmap_steps", 24))

    shadow_map = bake_shadow_clipmap(
        stack,
        sun_dir_rad=(sun_az, sun_el),
        clipmap_res=clipmap_res,
        num_steps=num_steps,
    )

    # Resample shadow_map back to heightmap resolution (rows x cols)
    if shadow_map.shape != (rows, cols):
        resampled = _resample_height(shadow_map.astype(np.float64), max(rows, cols))
        resampled = resampled[:rows, :cols].astype(np.float32)
    else:
        resampled = shadow_map.astype(np.float32)

    # Store dedicated shadow_map channel
    stack.set("shadow_map", resampled, "shadow_clipmap")

    # Compose with cloud_shadow if present; otherwise initialise from shadow_map.
    # Both signals contribute to sky occlusion in the Unity AO shader path.
    existing_cloud = stack.get("cloud_shadow")
    if existing_cloud is not None:
        combined = (np.asarray(existing_cloud, dtype=np.float32) * resampled).astype(np.float32)
    else:
        combined = resampled.copy()
    stack.set("cloud_shadow", combined, "shadow_clipmap")
    produced = ("shadow_map", "cloud_shadow")

    return PassResult(
        pass_name="shadow_clipmap",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=produced,
        metrics={
            "sun_azimuth_rad": sun_az,
            "sun_elevation_rad": sun_el,
            "clipmap_res": int(clipmap_res),
            "num_steps": num_steps,
            "lit_fraction": float((resampled > 0.5).mean()),
            "shadow_min": float(resampled.min()),
            "shadow_max": float(resampled.max()),
        },
        issues=[],
    )


def register_bundle_k_shadow_clipmap_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="shadow_clipmap",
            func=pass_shadow_clipmap,
            requires_channels=("height",),
            produces_channels=("shadow_map", "cloud_shadow"),
            seed_namespace="shadow_clipmap",
            requires_scene_read=False,
            description="Bundle K: vectorised horizon-scan sun shadow clipmap bake",
        )
    )


__all__ = [
    "bake_shadow_clipmap",
    "export_shadow_clipmap_exr",
    "pass_shadow_clipmap",
    "register_bundle_k_shadow_clipmap_pass",
]
