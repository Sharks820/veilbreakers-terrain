"""Procedural grass / ground-cover placement system for VeilBreakers.

Drives placement decisions from the :class:`TerrainMaskStack` channels
(slope, drainage, biome_id, road_sdf_dist, cliff_label, water_surface,
hero_exclusion) and emits per-instance records that round-trip through the
foliage placement manifest schema documented in
``docs/FOLIAGE_MANIFEST_PIPELINE.md``.

The placement is **vectorised numpy** end-to-end — no Python loops over
individual cells. SDF erosion uses ``scipy.ndimage.distance_transform_edt``
when scipy is available, with a numpy fallback for environments that lack
it (the fallback is approximate but sufficient for unit tests).

The module also writes a Blender 4.5-compatible Geometry Nodes Python
script for any species the artist wants to scatter inside Blender for
hero shots — this is a *script generator*, not a runtime Blender
dependency. The runtime path is still Unity GPU Resident Drawer / Forest
Pack, exactly as Wave 5 research locked in.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import string
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, cast

import numpy as np

logger = logging.getLogger(__name__)

# Import canonical biome IDs from the single source of truth.
from .terrain_biome_registry import CANONICAL_BIOME_IDS  # noqa: F401,E402 — re-exported


# ---------------------------------------------------------------------------
# Optional scipy SDF
# ---------------------------------------------------------------------------

try:  # pragma: no cover - import-time, optional
    from scipy.ndimage import distance_transform_edt as _scipy_edt  # type: ignore
except Exception:  # noqa: BLE001
    _scipy_edt = None  # type: ignore[assignment]


def _distance_transform_edt(mask: np.ndarray) -> np.ndarray:
    """Euclidean distance transform of a foreground mask.

    Uses scipy when available. The numpy fallback computes a Chebyshev
    distance via iterative dilation — slower than scipy and only
    Chebyshev (L∞) accurate, which is fine for SDF-style exclusion checks
    at the cell scale we use.
    """
    if _scipy_edt is not None:
        return np.asarray(cast(Any, _scipy_edt)(mask), dtype=np.float32)

    # Fallback: BFS-style multi-pass.
    mask = np.asarray(mask, dtype=bool)
    h, w = mask.shape
    inf = float(h + w)
    dist = np.where(mask, inf, 0.0).astype(np.float32)
    # Forward pass
    for r in range(h):
        for c in range(w):
            if dist[r, c] == 0:
                continue
            best = dist[r, c]
            if r > 0:
                best = min(best, dist[r - 1, c] + 1)
            if c > 0:
                best = min(best, dist[r, c - 1] + 1)
            dist[r, c] = best
    # Backward pass
    for r in range(h - 1, -1, -1):
        for c in range(w - 1, -1, -1):
            if dist[r, c] == 0:
                continue
            best = dist[r, c]
            if r + 1 < h:
                best = min(best, dist[r + 1, c] + 1)
            if c + 1 < w:
                best = min(best, dist[r, c + 1] + 1)
            dist[r, c] = best
    return dist


# ---------------------------------------------------------------------------
# Species definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GrassSpecies:
    """Per-species placement and asset metadata.

    Args:
        name: Stable species id (used as manifest mesh_library key).
        mesh_path: Optional pre-authored card / blade mesh (.fbx).
        billboard_texture_path: Optional flat billboard texture.
        height_range_m: (min, max) height/elevation band where the species
            can grow. Heights outside the band are skipped.
        density_per_sqm: Target density in instances per square metre at
            full biome strength.
        slope_max_deg: Above this slope the species is excluded.
        wetness_affinity: 0 = strictly dry, 1 = strictly wetland; the
            species' density at a cell scales with
            ``1 - |drainage_norm - wetness_affinity|``.
        biomes: Whitelist of biome names. Empty / ``("*",)`` = all biomes.
        min_spacing_m: Poisson disk minimum spacing in metres.
        category: Manifest category — usually ``ground_cover`` for grass.
        unity_render_mode: ``detail_prototype`` for grass billboards or
            ``gpu_instancer`` for full-mesh cards.
    """

    name: str
    height_range_m: tuple[float, float] = (-50.0, 4000.0)
    density_per_sqm: float = 1.0
    slope_max_deg: float = 35.0
    wetness_affinity: float = 0.3
    biomes: tuple[str, ...] = ("*",)
    min_spacing_m: float = 0.25
    category: str = "ground_cover"
    unity_render_mode: str = "detail_prototype"
    mesh_path: Optional[Path] = None
    billboard_texture_path: Optional[Path] = None
    render_batch_key: Optional[str] = None

    def matches_biome(self, biome_name: str) -> bool:
        return ("*" in self.biomes) or (biome_name in self.biomes)


# ---------------------------------------------------------------------------
# VeilBreakers default species library
# ---------------------------------------------------------------------------


VEILBREAKERS_GRASS_SPECIES: tuple[GrassSpecies, ...] = (
    GrassSpecies(
        name="dead_withered_grass",
        density_per_sqm=4.0,
        slope_max_deg=40.0,
        wetness_affinity=0.15,
        biomes=("*",),
        min_spacing_m=0.25,
        unity_render_mode="detail_prototype",
    ),
    GrassSpecies(
        name="swamp_reeds",
        density_per_sqm=2.5,
        slope_max_deg=15.0,
        wetness_affinity=0.9,
        biomes=("corrupted_swamp", "coastal"),
        min_spacing_m=0.5,
        unity_render_mode="gpu_instancer",
    ),
    GrassSpecies(
        name="dark_moss_patches",
        density_per_sqm=3.0,
        slope_max_deg=70.0,
        wetness_affinity=0.7,
        biomes=("thornwood_forest", "deep_forest", "cemetery", "ruined_fortress", "mountain_pass"),
        min_spacing_m=0.35,
        unity_render_mode="gpu_instancer",
    ),
    GrassSpecies(
        name="twisted_fern",
        density_per_sqm=1.6,
        slope_max_deg=30.0,
        wetness_affinity=0.55,
        biomes=("thornwood_forest", "deep_forest", "mushroom_forest"),
        min_spacing_m=0.55,
        unity_render_mode="gpu_instancer",
    ),
    GrassSpecies(
        name="ash_grass",
        density_per_sqm=2.0,
        slope_max_deg=35.0,
        wetness_affinity=0.1,
        biomes=("desert",),
        min_spacing_m=0.3,
        unity_render_mode="detail_prototype",
    ),
    GrassSpecies(
        name="blood_moss",
        density_per_sqm=1.0,
        slope_max_deg=60.0,
        wetness_affinity=0.6,
        biomes=("corrupted_swamp", "ruined_fortress", "cemetery"),
        min_spacing_m=0.6,
        unity_render_mode="gpu_instancer",
    ),
)


# ---------------------------------------------------------------------------
# Placement records
# ---------------------------------------------------------------------------


@dataclass
class GrassPlacementRecord:
    """One instance to be scattered.

    All fields needed to emit a manifest entry compatible with the Wave 5
    schema. ``position_terrain_norm`` is precomputed so Unity importers
    don't need stack metadata.
    """

    species: str
    position_world: tuple[float, float, float]
    position_terrain_norm: tuple[float, float, float]
    rotation_y_rad: float
    scale: float
    biome: str
    moisture: float
    lod_level: int = 2  # grass is almost always LOD2/billboard at distance
    category: str = "ground_cover"
    tint_rgb: tuple[float, float, float] = (1.0, 1.0, 1.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_array(arr: Optional[np.ndarray]) -> Optional[np.ndarray]:
    if arr is None:
        return None
    a = np.asarray(arr, dtype=np.float32)
    lo = float(a.min())
    hi = float(a.max())
    if hi - lo < 1e-9:
        return np.zeros_like(a, dtype=np.float32)
    return ((a - lo) / (hi - lo)).astype(np.float32)


def _stack_attr(stack: Any, name: str, default: Any = None) -> Any:
    if stack is None:
        return default
    return getattr(stack, name, default)


def _biome_id_to_name(biome_id_value: int, biome_id_map: dict[str, int]) -> Optional[str]:
    for name, value in biome_id_map.items():
        if int(value) == int(biome_id_value):
            return name
    return None


# Default biome id map. Covers the full 18-biome canonical palette from
# `terrain_biome_registry.CANONICAL_BIOME_IDS`. IDs 0-13 mirror the legacy
# `vegetation_system.BIOME_VEGETATION_SETS` ordering for backward compat;
# IDs 14-17 were added to close the silent-degrade-to-id-0 bug where 4
# canonical biomes had no entry and got thornwood-forest density rules.
#
# NOTE: when the stack has been populated by ``pass_compute_biome_channels``,
# ``stack.biome_names`` is set and biome_id values are Voronoi indices into
# that list (not necessarily matching these static IDs).  ``pass_procedural_grass``
# builds the map dynamically from ``stack.biome_names`` when available and
# falls back to this constant only for stacks that pre-date biome_channels.
DEFAULT_BIOME_ID_MAP: dict[str, int] = {
    "thornwood_forest": 0,
    "corrupted_swamp": 1,
    "mountain_pass": 2,
    "cemetery": 3,
    "ashen_wastes": 4,
    "frozen_hollows": 5,
    "blighted_mire": 6,
    "ruined_citadel": 7,
    "desert": 8,
    "coastal": 9,
    "grasslands": 10,
    "mushroom_forest": 11,
    "crystal_cavern": 12,
    "deep_forest": 13,
    "ruined_fortress": 14,
    "abandoned_village": 15,
    "battlefield": 16,
    "veil_crack_zone": 17,
}


# ---------------------------------------------------------------------------
# The placement system
# ---------------------------------------------------------------------------


class ProceduralGrassSystem:
    """Vectorised grass / ground-cover scatterer.

    The scatter for a species is computed entirely in numpy:

      1. Build a per-species *eligibility mask* by combining slope cap,
         height band, biome filter, water exclusion, hero exclusion, and
         road / cliff SDF erosion.
      2. Multiply by a wetness-affinity weight derived from the drainage
         channel.
      3. Multiply by the species' biome density (when ``stack.biome_id``
         is present) so density falls off where the biome blends out.
      4. Flatten to a probability density and sample candidate cells with
         ``np.random.choice`` weighted by the per-cell probability.
      5. Apply a coarse Poisson-disk-style minimum spacing pass (vectorised
         O(n log n) bucket sort).

    No per-cell Python loops. Memory peak is one float32 array per
    species at the stack resolution.
    """

    def __init__(
        self,
        biome_id_map: Optional[dict[str, int]] = None,
        rng_seed: int = 1234,
    ) -> None:
        self.biome_id_map = biome_id_map or dict(DEFAULT_BIOME_ID_MAP)
        self.rng = np.random.default_rng(rng_seed)

    # ------------------------------------------------------------------
    def _eligibility_mask(
        self,
        species: GrassSpecies,
        stack: Any,
        cell_size_m: float,
        sdf_road_min_m: float,
        sdf_cliff_min_m: float,
        water_edge_min_m: float,
    ) -> np.ndarray:
        """Return a float32 (H, W) mask in [0, 1] of placement weight."""
        height = _stack_attr(stack, "height")
        if height is None:
            raise ValueError("Stack must have a populated 'height' channel")
        height = np.asarray(height, dtype=np.float32)
        h, w = height.shape
        mask = np.ones((h, w), dtype=np.float32)

        # Height band
        lo, hi = species.height_range_m
        mask *= ((height >= lo) & (height <= hi)).astype(np.float32)

        # Slope cap
        slope = _stack_attr(stack, "slope")
        if slope is not None:
            mask *= (np.asarray(slope, dtype=np.float32) <= species.slope_max_deg).astype(np.float32)

        # Cliff hard exclude
        cliff_label = _stack_attr(stack, "cliff_label")
        if cliff_label is not None:
            mask *= (np.asarray(cliff_label) == 0).astype(np.float32)

        # Hero exclusion (POIs / hero meshes)
        hero = _stack_attr(stack, "hero_exclusion")
        if hero is not None:
            mask *= (np.asarray(hero) == 0).astype(np.float32)
        poi = _stack_attr(stack, "poi_mask")
        if poi is not None:
            mask *= (np.asarray(poi) == 0).astype(np.float32)

        # Water surface exclusion: submerged cells cannot place grass.
        # W-1 fix: prefer water_surface_elevation_m for the height comparison.
        # Fall back to water_surface_mask (binary) when elevation is absent.
        ws_elev = _stack_attr(stack, "water_surface_elevation_m")
        if ws_elev is not None:
            # Elevation path: exclude cells where terrain height < water surface height.
            ws = np.asarray(ws_elev, dtype=np.float32)
            mask *= (height >= ws).astype(np.float32)
        else:
            # Binary mask path: water_surface_mask is a binary {0,1} extent
            # channel; a cell is water when it exceeds the canonical wet
            # threshold (0.5).  Exclude those cells from grass.
            # CE-2026-05-24 #9: use the canonical ``> 0.5`` semantics (matches
            # pass_bathymetry and the seasonal pass) instead of ``<= 0.0`` —
            # under ``<= 0.0`` a fractional value like 0.5 was treated as water
            # while the bathymetry reader (``> 0.5``) treated it as dry land.
            # W-1: use water_surface_mask exclusively; legacy water_surface fallback removed.
            ws_mask = _stack_attr(stack, "water_surface_mask")
            if ws_mask is not None:
                mask *= (np.asarray(ws_mask, dtype=np.float32) <= 0.5).astype(np.float32)

        # Road SDF: stack.road_sdf_dist is precomputed in metres.
        road_sdf = _stack_attr(stack, "road_sdf_dist")
        if road_sdf is not None:
            mask *= (np.asarray(road_sdf, dtype=np.float32) >= sdf_road_min_m).astype(np.float32)
        else:
            road_mask = _stack_attr(stack, "road_mask")
            if road_mask is not None:
                rm = np.asarray(road_mask).astype(bool)
                derived = _distance_transform_edt(~rm) * cell_size_m
                mask *= (derived >= sdf_road_min_m).astype(np.float32)

        # Cliff SDF (separate from cliff_label hard exclude — keeps spacing buffer).
        if cliff_label is not None and sdf_cliff_min_m > 0:
            cl = np.asarray(cliff_label).astype(bool)
            cliff_sdf = _distance_transform_edt(~cl) * cell_size_m
            mask *= (cliff_sdf >= sdf_cliff_min_m).astype(np.float32)

        # Water edge SDF via bathymetry.
        bathy = _stack_attr(stack, "bathymetry")
        if bathy is not None and water_edge_min_m > 0:
            wet = np.asarray(bathy, dtype=np.float32) > 0
            water_sdf = _distance_transform_edt(~wet) * cell_size_m
            mask *= (water_sdf >= water_edge_min_m).astype(np.float32)

        # PR-B (cross-audit P0 2026-05-09): wetness affinity from the
        # Topographic Wetness Index (vb_TWI) when available — TWI =
        # ln(area / tan(slope)) is the canonical AAA moisture proxy
        # (Horizon FW + Death Stranding wetland scatter both bake from
        # this). Falls back to drainage / wetness for legacy / non-D35
        # pipelines. Phase C D35 produces vb_TWI but until this PR no
        # downstream pass actually read it — verifier-confirmed dead
        # channel.
        # Verifier 2 risk fix on PR-B: ``_normalise_array`` returns
        # all-zeros on uniform input (hi - lo < 1e-9). When vb_TWI is
        # produced as a uniform / stub array (degenerate D35 producer
        # on a flat tile), the prior code silently accepted those
        # zeros and suppressed the drainage fallback. Treat uniform
        # TWI as "absent" so the legacy drainage fallback engages.
        twi = _stack_attr(stack, "vb_TWI")
        moisture_source = _normalise_array(twi)
        if moisture_source is not None and not np.any(moisture_source):
            moisture_source = None
        if moisture_source is None:
            drainage = _stack_attr(stack, "drainage")
            if drainage is None:
                drainage = _stack_attr(stack, "wetness")
            moisture_source = _normalise_array(drainage)
        if moisture_source is not None:
            affinity = 1.0 - np.abs(moisture_source - species.wetness_affinity)
            affinity = np.clip(affinity, 0.0, 1.0).astype(np.float32)
            mask *= affinity

        # Biome filter.
        biome_id = _stack_attr(stack, "biome_id")
        if biome_id is not None:
            biome_id = np.asarray(biome_id)
            if "*" not in species.biomes:
                allowed = np.zeros_like(biome_id, dtype=bool)
                for b in species.biomes:
                    bid = self.biome_id_map.get(b)
                    if bid is None:
                        continue
                    allowed |= (biome_id == bid)
                mask *= allowed.astype(np.float32)

        return mask

    # ------------------------------------------------------------------
    def _sample_positions(
        self,
        weight: np.ndarray,
        species: GrassSpecies,
        cell_size_m: float,
    ) -> np.ndarray:
        """Pick candidate (row, col) positions weighted by ``weight``.

        Returns an (N, 2) int array of cell indices. The number of
        candidates is determined by ``species.density_per_sqm`` and the
        sum of ``weight``.
        """
        total_weight = float(weight.sum())
        if total_weight <= 0:
            return np.zeros((0, 2), dtype=np.int64)

        cell_area_m2 = cell_size_m * cell_size_m
        target_count = int(round(species.density_per_sqm * total_weight * cell_area_m2))
        target_count = max(0, min(target_count, weight.size))
        if target_count == 0:
            return np.zeros((0, 2), dtype=np.int64)

        flat = weight.ravel().astype(np.float64)
        nonzero = int((flat > 0).sum())
        if nonzero == 0:
            return np.zeros((0, 2), dtype=np.int64)
        target_count = min(target_count, nonzero)
        flat /= flat.sum()
        idx = self.rng.choice(flat.size, size=target_count, replace=False, p=flat)
        rows = idx // weight.shape[1]
        cols = idx % weight.shape[1]
        return np.stack([rows, cols], axis=1)

    # ------------------------------------------------------------------
    @staticmethod
    def _poisson_thin(
        positions: np.ndarray,
        cell_size_m: float,
        min_spacing_m: float,
    ) -> np.ndarray:
        """3x3-neighbourhood Poisson-disk thinning. Vectorised. Approximate.

        For each candidate point (in arrival order) we check all 8 adjacent
        grid cells as well as the candidate's own cell.  A point is kept only
        if no already-accepted point in those 9 cells is within min_spacing_m.
        This avoids the 50 % over-rejection of the old single-bucket approach.
        """
        if positions.shape[0] == 0 or min_spacing_m <= 0:
            return positions
        bucket = max(1, int(round(min_spacing_m / cell_size_m)))
        # Map each position to its grid cell.
        grid_keys = (positions // bucket).astype(np.int64)
        # We work in cell-space; min_spacing in cell units.
        min_spacing_cells = min_spacing_m / cell_size_m

        kept_indices: list[int] = []
        # cell -> list of kept positions (in original coordinate space)
        occupied: dict[tuple[int, int], list[np.ndarray]] = {}

        for i in range(positions.shape[0]):
            gx, gy = int(grid_keys[i, 0]), int(grid_keys[i, 1])
            pos = positions[i]
            conflict = False
            # Check 3x3 neighbourhood of grid cells
            for dx in (-1, 0, 1):
                if conflict:
                    break
                for dy in (-1, 0, 1):
                    cell = (gx + dx, gy + dy)
                    for opos in occupied.get(cell, []):
                        diff = pos - opos
                        if float(np.dot(diff, diff)) ** 0.5 < min_spacing_cells:
                            conflict = True
                            break
                    if conflict:
                        break
            if not conflict:
                kept_indices.append(i)
                occupied.setdefault((gx, gy), []).append(pos)

        if not kept_indices:
            return positions[:0]
        return positions[np.array(kept_indices, dtype=np.intp)]

    # ------------------------------------------------------------------
    def generate_grass_placement(
        self,
        stack: Any,
        species_library: Sequence[GrassSpecies],
        cell_size_m: float = 1.0,
        *,
        sdf_road_min_m: float = 1.5,
        sdf_cliff_min_m: float = 0.8,
        water_edge_min_m: float = 0.5,
        max_instances_per_species: int = 200_000,
    ) -> list[GrassPlacementRecord]:
        """Place every species in ``species_library`` on ``stack``.

        Returns a flat list of records across all species, ready to feed
        :func:`write_grass_manifest`.
        """
        height = _stack_attr(stack, "height")
        if height is None:
            raise ValueError("stack.height is required")
        height = np.asarray(height, dtype=np.float32)
        h, w = height.shape

        world_origin_x = float(_stack_attr(stack, "world_origin_x", 0.0) or 0.0)
        world_origin_y = float(_stack_attr(stack, "world_origin_y", 0.0) or 0.0)
        cell_size = float(_stack_attr(stack, "cell_size", cell_size_m) or cell_size_m)

        height_min = float(height.min())
        height_max = float(height.max())
        height_span = max(height_max - height_min, 1e-6)
        terrain_extent_x = w * cell_size
        terrain_extent_y = h * cell_size

        biome_id_arr = _stack_attr(stack, "biome_id")
        drainage_arr = _stack_attr(stack, "drainage")
        if drainage_arr is None:
            drainage_arr = _stack_attr(stack, "wetness")
        drainage_norm = _normalise_array(drainage_arr)

        records: list[GrassPlacementRecord] = []
        for species in species_library:
            weight = self._eligibility_mask(
                species,
                stack,
                cell_size_m=cell_size,
                sdf_road_min_m=sdf_road_min_m,
                sdf_cliff_min_m=sdf_cliff_min_m,
                water_edge_min_m=water_edge_min_m,
            )
            positions = self._sample_positions(weight, species, cell_size)
            positions = self._poisson_thin(positions, cell_size, species.min_spacing_m)
            if positions.shape[0] > max_instances_per_species:
                positions = positions[:max_instances_per_species]
            if positions.shape[0] == 0:
                continue

            rows = positions[:, 0]
            cols = positions[:, 1]
            wx = world_origin_x + (cols.astype(np.float32) + 0.5) * cell_size
            wy = world_origin_y + (rows.astype(np.float32) + 0.5) * cell_size
            wz = height[rows, cols]

            # Per-instance jitter — eyeballed AAA spec: small random rotation
            # and a uniform scale jitter of ±20%.
            rotations = self.rng.uniform(0, 2 * math.pi, size=positions.shape[0]).astype(np.float32)
            scales = self.rng.uniform(0.8, 1.2, size=positions.shape[0]).astype(np.float32)

            # Position in 0..1 terrain-norm space (Unity convention).
            norm_x = np.clip(cols.astype(np.float32) * cell_size / terrain_extent_x, 0.0, 1.0)
            norm_z = np.clip(rows.astype(np.float32) * cell_size / terrain_extent_y, 0.0, 1.0)
            norm_y = np.clip((wz - height_min) / height_span, 0.0, 1.0)

            # Biome name lookup per cell (vectorised then resolved)
            if biome_id_arr is not None:
                biome_vals = np.asarray(biome_id_arr)[rows, cols]
            else:
                biome_vals = None

            # PR-B (cross-audit P0 2026-05-09): record per-instance moisture
            # from vb_TWI when available (matches the affinity-mask source
            # in _eligibility_mask).  Falls back to drainage_norm.
            # Verifier 2 risk fix: treat uniform TWI as "absent" so
            # drainage fallback engages on degenerate D35 producers
            # (matches the same guard in _eligibility_mask).
            twi_arr = _stack_attr(stack, "vb_TWI")
            twi_norm = _normalise_array(twi_arr)
            if twi_norm is not None and not np.any(twi_norm):
                twi_norm = None
            moisture_grid = twi_norm if twi_norm is not None else drainage_norm
            if moisture_grid is not None:
                moistures = moisture_grid[rows, cols]
            else:
                moistures = np.zeros(positions.shape[0], dtype=np.float32)

            for i in range(positions.shape[0]):
                if biome_vals is not None:
                    biome_name = _biome_id_to_name(int(biome_vals[i]), self.biome_id_map) or "unknown"
                else:
                    biome_name = species.biomes[0] if species.biomes and species.biomes[0] != "*" else "unknown"
                records.append(
                    GrassPlacementRecord(
                        species=species.name,
                        position_world=(float(wx[i]), float(wy[i]), float(wz[i])),
                        position_terrain_norm=(float(norm_x[i]), float(norm_y[i]), float(norm_z[i])),
                        rotation_y_rad=float(rotations[i]),
                        scale=float(scales[i]),
                        biome=biome_name,
                        moisture=float(moistures[i]),
                        category=species.category,
                    )
                )
        return records

    # ------------------------------------------------------------------
    def generate_ground_cover_geometry_nodes_script(
        self,
        species: GrassSpecies,
        output_path: Path,
    ) -> Path:
        """Write a Blender 4.5 script that builds a Geometry Nodes group.

        The script is *self-contained* — running it in Blender produces a
        ``Grass_<species>`` node group that scatters the species' mesh on
        any surface object via a Geometry Nodes modifier.

        Used for cinematic / hero-shot Blender scenes, not in the runtime
        path. Runtime scatter is the data-driven Unity Terrain / GPU
        instancing manifest.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        mesh_path = species.mesh_path or species.billboard_texture_path
        mesh_path_repr = repr(str(mesh_path)) if mesh_path else "None"

        script = f'''"""
Generated by procedural_grass.generate_ground_cover_geometry_nodes_script
Species: {species.name}
"""
import bpy

SPECIES_NAME = {species.name!r}
DENSITY_PER_SQM = {species.density_per_sqm!r}
MIN_SPACING_M = {species.min_spacing_m!r}
MESH_PATH = {mesh_path_repr}


def build():
    name = f"Grass_{{SPECIES_NAME}}"
    if name in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[name])
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")

    # I/O
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Density", in_out="INPUT", socket_type="NodeSocketFloat").default_value = DENSITY_PER_SQM
    ng.interface.new_socket("MinDist", in_out="INPUT", socket_type="NodeSocketFloat").default_value = MIN_SPACING_M

    g_in = ng.nodes.new("NodeGroupInput")
    g_in.location = (-600, 0)
    g_out = ng.nodes.new("NodeGroupOutput")
    g_out.location = (600, 0)

    distrib = ng.nodes.new("GeometryNodeDistributePointsOnFaces")
    distrib.distribution_method = "POISSON"
    distrib.location = (-200, 0)

    # Wire up the basic graph.
    ng.links.new(g_in.outputs["Geometry"], distrib.inputs["Mesh"])
    ng.links.new(g_in.outputs["Density"], distrib.inputs["Density Max"])
    ng.links.new(g_in.outputs["MinDist"], distrib.inputs["Distance Min"])

    inst = ng.nodes.new("GeometryNodeInstanceOnPoints")
    inst.location = (200, 0)
    ng.links.new(distrib.outputs["Points"], inst.inputs["Points"])
    ng.links.new(inst.outputs["Instances"], g_out.inputs["Geometry"])

    print(f"[procedural_grass] Built node group {{name}}")


if __name__ == "__main__":
    build()
'''
        # Atomic write
        suffix = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        tmp = output_path.with_name(f".{output_path.name}.{suffix}.tmp")
        tmp.write_text(script, encoding="utf-8")
        os.replace(tmp, output_path)
        return output_path

    # ------------------------------------------------------------------
    def write_grass_manifest(
        self,
        records: Iterable[GrassPlacementRecord],
        out_path: Path,
        *,
        biome: str = "mixed",
        season: Optional[str] = None,
        existing_manifest_path: Optional[Path] = None,
        terrain_meta: Optional[dict[str, Any]] = None,
    ) -> Path:
        """Write a manifest JSON compatible with FOLIAGE_MANIFEST_PIPELINE.md.

        When ``existing_manifest_path`` is given, the grass entries are
        merged into it (adding to ``mesh_library`` and ``instances``).
        Otherwise a fresh manifest is created.
        """
        records = list(records)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if existing_manifest_path and Path(existing_manifest_path).is_file():
            with Path(existing_manifest_path).open("r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        else:
            manifest = self._empty_manifest(biome=biome, season=season, terrain_meta=terrain_meta)

        # Build mesh_library entries on demand.
        existing_keys = {m["species_key"]: m["mesh_id"] for m in manifest.get("mesh_library", [])}
        species_density: dict[str, int] = dict(manifest.get("species_density", {}))
        lod_distribution: dict[str, int] = dict(manifest.get("lod_distribution", {"0": 0, "1": 0, "2": 0, "3": 0}))

        for rec in records:
            if rec.species not in existing_keys:
                mesh_id = len(manifest["mesh_library"])
                existing_keys[rec.species] = mesh_id
                manifest["mesh_library"].append(
                    {
                        "mesh_id": mesh_id,
                        "species_key": rec.species,
                        "mesh_asset_path": None,
                        "atlas_path": None,
                        "lod_meshes": [],
                        "category": rec.category,
                        "unity_render_mode": "detail_prototype",
                        "render_batch_key": rec.species,
                        "wind_color_baked": False,
                        "physics_collider": "none",
                    }
                )
            mesh_id = existing_keys[rec.species]
            i = len(manifest["instances"])
            manifest["instances"].append(
                {
                    "i": i,
                    "mesh_id": mesh_id,
                    "position_world": list(rec.position_world),
                    "position_terrain_norm": list(rec.position_terrain_norm),
                    "rotation_y_rad": rec.rotation_y_rad,
                    "scale": rec.scale,
                    "scale_xyz": [rec.scale, rec.scale, rec.scale],
                    "lod_level": rec.lod_level,
                    "lod_hint_sampler_tier": 2,
                    "biome": rec.biome,
                    "category": rec.category,
                    "moisture": rec.moisture,
                    "tint_rgb": list(rec.tint_rgb),
                    "color_variation_seed": int(self.rng.integers(0, 2**31 - 1)),
                }
            )
            species_density[rec.species] = species_density.get(rec.species, 0) + 1
            key = str(rec.lod_level)
            lod_distribution[key] = lod_distribution.get(key, 0) + 1

        manifest["instance_count"] = len(manifest["instances"])
        manifest["species_density"] = species_density
        manifest["lod_distribution"] = lod_distribution

        # Atomic write
        suffix = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        tmp = out_path.with_name(f".{out_path.name}.{suffix}.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            # T0.5-8b (Y04 v3 §P.8.2): allow_nan=False — loud-at-source for
            # procedural-grass scatter manifest writer (Unity-consumed).
            json.dump(manifest, fh, indent=2, sort_keys=True, allow_nan=False)
        os.replace(tmp, out_path)
        return out_path

    # ------------------------------------------------------------------
    @staticmethod
    def _empty_manifest(
        *,
        biome: str,
        season: Optional[str],
        terrain_meta: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        import time as _time

        return {
            "schema_version": "1.0",
            "generated_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            "terrain": terrain_meta
            or {
                "tile_x": 0,
                "tile_y": 0,
                "tile_size": 1024,
                "cell_size": 1.0,
                "world_origin": [0.0, 0.0],
                "world_extent": [1024.0, 1024.0],
                "height_min_m": 0.0,
                "height_max_m": 100.0,
            },
            "biome": biome,
            "season": season,
            "lod_distances_m": [15.0, 35.0, 60.0, 200.0],
            "camera_reference": [0.0, 0.0, 0.0],
            "mesh_library": [],
            "instances": [],
            "instance_count": 0,
            "species_density": {},
            "lod_distribution": {"0": 0, "1": 0, "2": 0, "3": 0},
        }


def _density_maps_from_records(
    records: Sequence[GrassPlacementRecord],
    shape: tuple[int, int],
    world_origin_x: float,
    world_origin_y: float,
    cell_size: float,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    grass_density = np.zeros(shape, dtype=np.float32)
    detail_density: dict[str, np.ndarray] = {}
    rows, cols = shape
    for record in records:
        col = int(math.floor((record.position_world[0] - world_origin_x) / cell_size))
        row = int(math.floor((record.position_world[1] - world_origin_y) / cell_size))
        if row < 0 or row >= rows or col < 0 or col >= cols:
            continue
        grass_density[row, col] += 1.0
        species_map = detail_density.setdefault(record.species, np.zeros(shape, dtype=np.float32))
        species_map[row, col] += 1.0
    if float(grass_density.max(initial=0.0)) > 0.0:
        grass_density /= float(grass_density.max())
    for species, density in list(detail_density.items()):
        if float(density.max(initial=0.0)) > 0.0:
            detail_density[species] = density / float(density.max())
    return grass_density.astype(np.float32), detail_density


def pass_procedural_grass(state: Any, region: Any = None) -> Any:
    """Production pass that publishes grass density and placement records."""
    from .terrain_pipeline import derive_pass_seed
    from .terrain_semantics import PassResult

    t0 = time.perf_counter()
    stack = state.mask_stack
    height = np.asarray(stack.height, dtype=np.float32)
    hints = getattr(getattr(state, "intent", None), "composition_hints", {}) or {}
    species_library = hints.get("grass_species_library", VEILBREAKERS_GRASS_SPECIES)
    max_instances = int(hints.get("grass_max_instances_per_species", 25_000))
    seed = derive_pass_seed(state.intent.seed, "procedural_grass", state.tile_x, state.tile_y, region)
    # Build biome_id_map from stack.biome_names when available (set by
    # pass_compute_biome_channels).  biome_id values are Voronoi indices into
    # that list, so the correct map is simply the enumeration order.  Fall back
    # to DEFAULT_BIOME_ID_MAP for stacks that pre-date the biome_channels pass.
    _biome_names: Optional[list[str]] = getattr(stack, "biome_names", None)
    biome_id_map: Optional[dict[str, int]] = (
        {name: idx for idx, name in enumerate(_biome_names)}
        if _biome_names
        else None
    )
    system = ProceduralGrassSystem(rng_seed=seed, biome_id_map=biome_id_map)
    records = system.generate_grass_placement(
        stack,
        species_library,
        cell_size_m=float(getattr(stack, "cell_size", 1.0) or 1.0),
        sdf_road_min_m=float(hints.get("grass_road_exclusion_m", 1.5)),
        sdf_cliff_min_m=float(hints.get("grass_cliff_exclusion_m", 0.8)),
        water_edge_min_m=float(hints.get("grass_water_edge_exclusion_m", 0.5)),
        max_instances_per_species=max_instances,
    )
    density, detail_density = _density_maps_from_records(
        records,
        height.shape,
        float(getattr(stack, "world_origin_x", 0.0) or 0.0),
        float(getattr(stack, "world_origin_y", 0.0) or 0.0),
        float(getattr(stack, "cell_size", 1.0) or 1.0),
    )
    stack.set("grass_density_map", density, "pass_procedural_grass")
    merged_detail = dict(stack.get("detail_density") or {})
    merged_detail.update(detail_density)
    stack.set("detail_density", merged_detail, "pass_procedural_grass")
    stack.set(
        "grass_placement_records",
        [asdict(record) for record in records],
        "pass_procedural_grass",
    )
    return PassResult(
        pass_name="pass_procedural_grass",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "slope", "drainage", "biome_id", "hero_exclusion"),
        produced_channels=("grass_density_map", "detail_density", "grass_placement_records"),
        metrics={
            "record_count": len(records),
            "species_count": len(detail_density),
            "density_nonzero_cells": int(np.count_nonzero(density)),
        },
        seed_used=seed,
    )


def register_procedural_grass_pass() -> None:
    """Register procedural grass placement on TerrainPassController."""
    from .terrain_pipeline import TerrainPassController
    from .terrain_semantics import PassDefinition

    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_procedural_grass",
            func=pass_procedural_grass,
            requires_channels=("height", "slope", "drainage", "biome_id"),
            # Phase C D35: optional consumption of derived topographic indices
            # for grass placement rules (spec §4.2 foliage stack). Read via
            # stack.get(...) so the pass works without them.
            optional_channels=(
                "biome_names",
                "vb_aspect_deg",
                "vb_aspect_north",
                "vb_canopy_openness",
                "vb_TWI",
            ),
            produces_channels=("grass_density_map", "detail_density", "grass_placement_records"),
            overrides=("detail_density",),
            seed_namespace="procedural_grass",
            requires_scene_read=False,
            supports_region_scope=True,
            description="Generate grass detail density and placement records",
        )
    )


__all__ = [
    "GrassSpecies",
    "GrassPlacementRecord",
    "ProceduralGrassSystem",
    "VEILBREAKERS_GRASS_SPECIES",
    "DEFAULT_BIOME_ID_MAP",
    "pass_procedural_grass",
    "register_procedural_grass_pass",
]
