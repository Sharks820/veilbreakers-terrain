"""Pure-logic biome world map composer.

NO bpy/bmesh imports. All functions operate on numpy arrays and return
numpy arrays or plain Python data structures. Fully testable without Blender.

Provides:
  - WorldMapSpec: Dataclass describing a full multi-biome world map.
  - generate_world_map_spec: Main entry point for multi-biome world generation.
  - resolve_biome_name: Alias resolution for biome names.
  - BIOME_CLIMATE_PARAMS: Per-biome temperature/moisture/elevation parameters.
  - BIOME_ALIASES: Maps non-palette biome names to closest BIOME_PALETTES keys.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np

try:
    import scipy.ndimage as _scipy_ndimage
    from scipy.ndimage import distance_transform_edt as _edt
    _HAS_SCIPY = True
    _HAS_SCIPY_EDT = True
except ImportError:
    _scipy_ndimage = None  # type: ignore[assignment]
    _HAS_SCIPY = False
    _HAS_SCIPY_EDT = False


# ---------------------------------------------------------------------------
# Biome alias table
# Maps success-criteria biome names -> BIOME_PALETTES keys
# ---------------------------------------------------------------------------

BIOME_ALIASES: dict[str, str] = {
    "volcanic_wastes": "desert",          # hot, barren -- closest palette
    "frozen_tundra":   "mountain_pass",   # cold, rocky -- closest palette
    "thornwood":       "thornwood_forest",
    "swamp":           "corrupted_swamp",
}


def _rng_from_seed(seed: int, seed_namespace: str) -> np.random.Generator:
    from .terrain_pipeline import derive_pass_seed

    return np.random.default_rng(
        derive_pass_seed(int(seed), seed_namespace, 0, 0, None)
    )


def resolve_biome_name(name: str) -> str:
    """Return canonical BIOME_PALETTES key for name, applying aliases.

    Args:
        name: Biome name (canonical or aliased).

    Returns:
        Canonical BIOME_PALETTES key.

    Raises:
        ValueError: If name is not a known biome or alias.
    """
    from .terrain_materials import BIOME_PALETTES
    if name in BIOME_PALETTES:
        return name
    alias = BIOME_ALIASES.get(name)
    if alias and alias in BIOME_PALETTES:
        return alias
    raise ValueError(f"Unknown biome: '{name}'. Known: {sorted(BIOME_PALETTES.keys())}")


# ---------------------------------------------------------------------------
# Per-biome climate parameter table
# temperature: 0=freezing, 1=scorching
# moisture: 0=arid, 1=saturated
# elevation: 0=sea level, 1=high mountain
# ---------------------------------------------------------------------------

BIOME_CLIMATE_PARAMS: dict[str, dict] = {
    "thornwood_forest":  {"temperature": 0.45, "moisture": 0.70, "elevation": 0.30},
    "corrupted_swamp":   {"temperature": 0.50, "moisture": 0.90, "elevation": 0.10},
    "mountain_pass":     {"temperature": 0.20, "moisture": 0.35, "elevation": 0.80},
    "desert":            {"temperature": 0.85, "moisture": 0.05, "elevation": 0.30},
    "grasslands":        {"temperature": 0.60, "moisture": 0.55, "elevation": 0.25},
    "deep_forest":       {"temperature": 0.50, "moisture": 0.80, "elevation": 0.40},
    "coastal":           {"temperature": 0.65, "moisture": 0.85, "elevation": 0.05},
    "cemetery":          {"temperature": 0.30, "moisture": 0.40, "elevation": 0.20},
    "battlefield":       {"temperature": 0.40, "moisture": 0.30, "elevation": 0.25},
    "ruined_fortress":   {"temperature": 0.35, "moisture": 0.25, "elevation": 0.55},
    "abandoned_village": {"temperature": 0.50, "moisture": 0.50, "elevation": 0.20},
    "veil_crack_zone":   {"temperature": 0.10, "moisture": 0.20, "elevation": 0.60},
    "mushroom_forest":   {"temperature": 0.55, "moisture": 0.85, "elevation": 0.30},
    "crystal_cavern":    {"temperature": 0.15, "moisture": 0.40, "elevation": 0.70},
    "blighted_mire":     {"temperature": 0.40, "moisture": 0.95, "elevation": 0.05},
    "ashen_wastes":      {"temperature": 0.75, "moisture": 0.10, "elevation": 0.40},
    "frozen_hollows":    {"temperature": 0.05, "moisture": 0.45, "elevation": 0.55},
    "ruined_citadel":    {"temperature": 0.40, "moisture": 0.30, "elevation": 0.65},
}

# Frozen set of all canonical VeilBreakers biome IDs — the single source of truth.
# Use this to validate biome whitelist fields (e.g. GrassSpecies.biomes) so that
# entries from different vocab sets (e.g. "forest" vs "thornwood_forest") are
# caught at import time rather than silently producing zero placements at runtime.
CANONICAL_BIOME_IDS: frozenset[str] = frozenset(BIOME_CLIMATE_PARAMS.keys())


# ---------------------------------------------------------------------------
# WorldMapSpec dataclass
# ---------------------------------------------------------------------------

@dataclass
class WorldMapSpec:
    """Full specification for a multi-biome world map.

    All fields are pure-logic (no bpy). Consumed by handle_generate_multi_biome_world.
    """

    width: int                           # grid cells (e.g. 256)
    height: int                          # grid cells (e.g. 256)
    world_size: float                    # meters (e.g. 512.0)
    seed: int
    biome_ids: np.ndarray                # (height, width) int32, values 0..biome_count-1
    biome_weights: np.ndarray            # (height, width, biome_count) float64, sum=1
    biome_names: list[str]               # length == biome_count, canonical BIOME_PALETTES keys
    corruption_map: np.ndarray           # (height, width) float64 in [0, 1]
    flatten_zones: list[dict]            # normalized coords, one per building_plot
    cell_params: list[dict]              # per-biome climate params (temperature, moisture, elevation)
    transition_width_m: float            # meters (e.g. 15.0)


# ---------------------------------------------------------------------------
# Default biome list (6 VeilBreakers presets)
# ---------------------------------------------------------------------------

_DEFAULT_BIOMES = [
    "thornwood_forest", "corrupted_swamp", "mountain_pass",
    "desert", "grasslands", "deep_forest",
]


# ---------------------------------------------------------------------------
# generate_world_map_spec: Main entry point
# ---------------------------------------------------------------------------

def generate_world_map_spec(
    width: int = 256,
    height: int = 256,
    world_size: float = 512.0,
    biome_count: int = 6,
    biomes: list[str] | None = None,
    seed: int = 42,
    corruption_level: float = 0.0,
    building_plots: list[dict] | None = None,
    transition_width_m: float = 15.0,
) -> WorldMapSpec:
    """Compose a WorldMapSpec for multi-biome world generation.

    Args:
        width: Grid resolution (cells).
        height: Grid resolution (cells).
        world_size: World extent in meters. Used to normalize flatten zones.
        biome_count: Number of Voronoi biome regions.
        biomes: List of biome names (canonical or alias). Defaults to 6 VB presets.
        seed: Master seed.
        corruption_level: Global corruption intensity [0, 1].
        building_plots: List of dicts with world-space keys: x, y, width, depth.
            Used to compute flatten zones. Coords in meters [0, world_size].
        transition_width_m: Blend zone width in meters.

    Returns:
        WorldMapSpec with all fields populated.

    Raises:
        ValueError: If biome names are invalid or count mismatch.
    """
    rng = random.Random(seed)

    # --- Resolve and validate biome names ---
    if biomes is None:
        chosen = list(_DEFAULT_BIOMES[:biome_count])
        if len(chosen) < biome_count:
            from .terrain_materials import BIOME_PALETTES
            extras = [b for b in BIOME_PALETTES if b not in chosen]
            chosen = chosen + extras[:biome_count - len(chosen)]
    else:
        chosen = [resolve_biome_name(b) for b in biomes]

    if len(chosen) != biome_count:
        raise ValueError(f"Expected {biome_count} biome names, got {len(chosen)}")

    # --- Normalized transition width ---
    transition_width_norm = transition_width_m / world_size

    # --- Voronoi distribution ---
    from ._terrain_noise import voronoi_biome_distribution
    biome_ids, biome_weights = voronoi_biome_distribution(
        width=width,
        height=height,
        biome_count=biome_count,
        transition_width=transition_width_norm,
        seed=seed,
        biome_names=chosen,
    )

    # --- Corruption map: fBm noise scaled by corruption_level ---
    # Use a separate seed offset so corruption pattern != biome distribution
    corruption_map = _generate_corruption_map(
        width, height, seed=seed + 7919, scale=corruption_level
    )

    # --- Flatten zones from building plots ---
    flatten_zones = []
    for plot in (building_plots or []):
        # Convert world-space to normalized [0, 1]
        cx = plot["x"] / world_size
        cy = plot["y"] / world_size
        # Radius = half of largest footprint dimension, with 20% padding
        max_dim = max(plot.get("width", 8.0), plot.get("depth", 8.0))
        radius = (max_dim / 2.0) / world_size * 1.2
        blend_width = radius * 0.5
        flatten_zones.append({
            "center_x": cx,
            "center_y": cy,
            "radius": radius,
            "blend_width": blend_width,
            "seed": rng.randint(0, 99999),
        })

    # --- Per-biome climate params ---
    cell_params = [
        BIOME_CLIMATE_PARAMS.get(
            name, {"temperature": 0.5, "moisture": 0.5, "elevation": 0.5}
        )
        for name in chosen
    ]

    # --- Climate-sorted biome ordering (AAA fix) ---
    # Pure geometric Voronoi places biomes randomly regardless of elevation or
    # temperature gradient, producing geologically implausible adjacencies
    # (e.g. arctic tundra bordering desert on a flat map with no altitude
    # gradient). We post-process the biome_ids so that the Voronoi cell whose
    # seed point sits at the highest normalised Y position (north = cold) gets
    # the coldest biome, and the lowest Y position gets the warmest.
    # This is equivalent to Houdini's "Layer" biome distribution strategy:
    # Voronoi cells are assigned biomes according to their seed-point latitude
    # rather than draw order, preserving spatial coherence from Voronoi while
    # adding climate plausibility.
    #
    # Implementation: sort the Voronoi seed points by their Y coordinate
    # (as computed inside voronoi_biome_distribution — we recompute the sort
    # order from the seed since we don't expose the seed points externally).
    # Then remap biome_ids through a permutation that maps Voronoi-cell index
    # → climate-sorted biome index.
    _climate_rng = random.Random(seed ^ 0xFACEB00C)
    grid_side_c = max(1, int(math.ceil(math.sqrt(biome_count))))
    cell_w_c = 1.0 / grid_side_c
    cell_h_c = 1.0 / grid_side_c
    seed_ys: list[float] = []
    for _bi in range(biome_count):
        _row = _bi // grid_side_c
        _sy = (_row + 0.2 + _climate_rng.random() * 0.6) * cell_h_c
        seed_ys.append(_sy)
        _climate_rng.random()   # consume the x draw so the RNG stream matches voronoi_biome_distribution

    # Sort biomes by seed Y (descending = north/cold → south/warm).
    # Sort chosen biomes by their temperature parameter (descending = cold first).
    sorted_by_temp = sorted(
        range(biome_count),
        key=lambda i: cell_params[i].get("temperature", 0.5),
    )   # index 0 = coldest biome
    # Sort Voronoi cell indices by seed Y (descending = northernmost first)
    sorted_by_y = sorted(range(biome_count), key=lambda i: seed_ys[i], reverse=True)
    # Permutation: Voronoi cell sorted_by_y[k] → biome sorted_by_temp[k]
    cell_to_biome = [0] * biome_count
    for _k in range(biome_count):
        cell_to_biome[sorted_by_y[_k]] = sorted_by_temp[_k]
    # Remap biome_ids through the permutation (vectorised)
    cell_to_biome_arr = np.array(cell_to_biome, dtype=np.int32)
    biome_ids = cell_to_biome_arr[biome_ids]
    # Reorder biome_weights axis-2 to match the permuted biome ordering.
    # biome_weights[..., k] holds the weight for Voronoi cell k; after
    # cell_to_biome remapping, axis-2 must follow the same permutation so
    # downstream splat code finds weight[k] == weight for biome k.
    inv_perm = np.empty(biome_count, dtype=np.int32)
    inv_perm[cell_to_biome_arr] = np.arange(biome_count, dtype=np.int32)
    biome_weights = biome_weights[..., inv_perm]

    return WorldMapSpec(
        width=width,
        height=height,
        world_size=world_size,
        seed=seed,
        biome_ids=biome_ids,
        biome_weights=biome_weights,
        biome_names=chosen,
        corruption_map=corruption_map,
        flatten_zones=flatten_zones,
        cell_params=cell_params,
        transition_width_m=transition_width_m,
    )


# ---------------------------------------------------------------------------
# _generate_corruption_map: fBm noise corruption intensity
# ---------------------------------------------------------------------------

def _generate_corruption_map(
    width: int,
    height: int,
    seed: int,
    scale: float,
    octaves: int = 4,
    warp_strength: float = 0.45,
) -> np.ndarray:
    """Generate a per-cell corruption intensity map using Perlin domain-warp fBm.

    Corruption spreads in organic, non-repetitive tendrils rather than banded
    concentric rings because the input coordinates are domain-warped before
    the fBm evaluation.  Two passes of Perlin warp (IQ-style) are applied:

        q  = fBm(p)                      # first pass — coarse warp field
        r  = fBm(p + q * warp_strength)  # second pass — refine warp
        result = fBm(p + r * warp_strength)  # final sample at warped coord

    Each fBm call uses a fresh generator derived from the master seed with an
    offset prime so the three noise layers are decorrelated.

    Returns np.ndarray (height, width) in [0, 1]. Values scaled by `scale`
    so corruption_level=0.0 returns all-zeros, 1.0 returns full noise range.

    Args:
        width: Grid width in cells.
        height: Grid height in cells.
        seed: RNG seed for this corruption pattern.
        scale: Global multiplier [0, 1]. If 0, returns all-zeros.
        octaves: Number of fBm octaves.
        warp_strength: Coordinate offset amplitude for each domain-warp pass.
            0.45 produces organic corruption tendrils without over-distorting
            the underlying noise structure.

    Returns:
        np.ndarray (height, width) float64 clipped to [0, 1].
    """
    if scale <= 0.0:
        return np.zeros((height, width), dtype=np.float64)

    from ._terrain_noise import _make_noise_generator

    # Three decorrelated generators — prime offsets prevent correlated warp paths
    gen_base  = _make_noise_generator(seed)
    gen_warp1 = _make_noise_generator(seed ^ 0x6C62272E)   # XOR with large prime
    gen_warp2 = _make_noise_generator(seed ^ 0xA5A5A5A5)

    ys = np.arange(height, dtype=np.float64) / height
    xs = np.arange(width,  dtype=np.float64) / width
    yy, xx = np.meshgrid(ys, xs, indexing="ij")   # (H, W)

    def _fbm_grid(gen, x_grid: np.ndarray, y_grid: np.ndarray) -> np.ndarray:
        """Vectorised fBm over coordinate grids using the noise generator."""
        noise = np.zeros_like(x_grid, dtype=np.float64)
        amp   = 1.0
        freq  = 3.0
        total = 0.0
        for _ in range(octaves):
            noise += gen.noise2_array(x_grid * freq, y_grid * freq) * amp
            total += amp
            amp  *= 0.5
            freq *= 2.0
        return noise / max(total, 1e-9)  # in ~[-1, 1]

    # --- Pass 1: coarse warp field — two independent components q_x, q_y ---
    # IQ-style domain warp requires INDEPENDENT x and y warp fields so the
    # corruption tendrils are genuinely 2D-anisotropic (different curvature in
    # x vs y). Using a single scalar q for both axes collapses the warp to a
    # diagonal-only distortion. We obtain independence by offsetting the second
    # sample by a large incommensurable constant (1.7, 9.2 — same offsets used
    # in domain_warp_array for consistency across the noise pipeline).
    q_x = _fbm_grid(gen_base, xx, yy)
    q_y = _fbm_grid(gen_base, xx + 1.7, yy + 9.2)   # independent y component

    # --- Pass 2: refined warp r = fBm(p + q * s + fixed_offset) ---
    # Fixed offset (5.2, 1.3) breaks diagonal symmetry (IQ reference).
    # Use independent gen_warp1 for x and gen_warp2 for y so the three
    # warp fields are fully decorrelated.
    r_x = _fbm_grid(
        gen_warp1,
        xx + q_x * warp_strength + 5.2,
        yy + q_y * warp_strength + 1.3,
    )
    r_y = _fbm_grid(
        gen_warp2,
        xx + q_x * warp_strength + 1.7,
        yy + q_y * warp_strength + 9.2,
    )

    # --- Final sample at double-warped coordinates ---
    # Re-use gen_base with a third prime XOR offset for the final evaluation
    gen_final = _make_noise_generator(seed ^ 0x3C3C3C3C)
    noise = _fbm_grid(
        gen_final,
        xx + r_x * warp_strength,
        yy + r_y * warp_strength,
    )

    noise = (noise + 1.0) / 2.0  # remap to [0, 1]
    return np.clip(noise * scale, 0.0, 1.0)


def _box_filter_2d(
    arr: np.ndarray,
    radius: int,
    mode: str = "reflect",
) -> np.ndarray:
    """Box-mean filter with configurable edge handling.

    Fast path: ``scipy.ndimage.uniform_filter`` — a C-extension running
    separable 1-D convolutions, ~500x faster than a Python loop and
    correct at every edge mode.

    Fallback (no scipy): fully vectorised summed-area-table.  No Python
    output loop — all indexing is done with numpy broadcasting in one shot.
    The SAT fallback handles the ``mode`` argument via explicit array
    padding before the integral-image is built:
      - ``"reflect"``   — mirror at boundaries (default, matches scipy)
      - ``"wrap"``      — periodic / toroidal wrap
      - ``"constant"``  — zero-pad (equivalent to 'constant, cval=0')
    Any unrecognised mode silently falls back to ``"reflect"``.

    Args:
        arr: 2-D float array to smooth.
        radius: Box half-width in pixels; kernel size = 2*radius+1.
            radius <= 0 returns a copy unchanged.
        mode: Edge-handling mode string.  One of "reflect", "wrap",
            "constant".  Passed directly to ``scipy.ndimage.uniform_filter``
            on the fast path or handled manually on the fallback path.

    Returns:
        Smoothed array, same shape and dtype as *arr*.
    """
    if radius <= 0:
        return arr.copy()
    arr = np.asarray(arr, dtype=np.float64)
    if _HAS_SCIPY:
        return _scipy_ndimage.uniform_filter(
            arr, size=2 * radius + 1, mode=mode
        ).astype(arr.dtype)

    # --- Vectorised SAT fallback (no Python inner loop) -------------------
    H, W = arr.shape
    # Pad the input array to implement the requested edge mode, then build
    # an integral image over the padded area.  We pad by exactly *radius*
    # on each side so that every output cell has a full (2r+1)^2 kernel.
    r = radius
    if mode == "wrap":
        padded = np.pad(arr, r, mode="wrap")
    elif mode == "constant":
        padded = np.pad(arr, r, mode="constant", constant_values=0.0)
    else:  # "reflect" or anything else
        padded = np.pad(arr, r, mode="reflect")

    # Build summed area table over the padded array
    PH, PW = padded.shape                  # (H+2r, W+2r)
    sat_full = np.zeros((PH + 1, PW + 1), dtype=np.float64)
    sat_full[1:, 1:] = np.cumsum(np.cumsum(padded, axis=0), axis=1)

    # For each output cell (i,j) the box spans padded rows [i, i+2r+1) and
    # padded cols [j, j+2r+1), which after the leading pad are always full.
    rows = np.arange(H, dtype=np.int64)    # output row indices
    cols = np.arange(W, dtype=np.int64)    # output col indices
    # Padded coordinates of box corners (no clamping needed — padding ensures
    # all boxes lie fully inside the padded array)
    r0 = rows                              # top row in padded array
    r1 = rows + 2 * r + 1                 # one past bottom row
    c0 = cols
    c1 = cols + 2 * r + 1
    # Use broadcasting to compute all box sums simultaneously: O(1) Python
    R0 = r0[:, None]; R1 = r1[:, None]    # (H, 1)
    C0 = c0[None, :]; C1 = c1[None, :]   # (1, W)
    box_sums = (
        sat_full[R1, C1]
        - sat_full[R0, C1]
        - sat_full[R1, C0]
        + sat_full[R0, C0]
    )
    kernel_area = float((2 * r + 1) ** 2)
    return (box_sums / kernel_area).astype(arr.dtype)


_CHAMFER_DIAG = math.sqrt(2.0)


def _distance_from_mask(mask: np.ndarray, cell_size: float = 1.0) -> np.ndarray:
    """Euclidean distance from every cell to the nearest True cell, in world metres.

    Interface matches ``terrain_wildlife_zones._distance_to_mask`` exactly:
    True cells are distance-0 sources; every other cell gets the distance
    (in world metres) to the nearest True cell.

    Fast path: ``scipy.ndimage.distance_transform_edt`` — exact Euclidean,
    O(N), result multiplied by *cell_size* to convert cells → metres.

    Fallback (no scipy): two-pass 8-connected chamfer with weights
    axial=1 cell, diagonal=√2 cells.  Greatly outperforms the previous
    4-neighbour Manhattan scan (the old BUG-07 41 % error on diagonals).

    Args:
        mask: (H, W) bool array.  True cells are distance-0 sources.
        cell_size: World metres per grid cell.  Output distances are in
            world metres.  Defaults to 1.0 (pixel distances).

    Returns:
        np.ndarray float64, shape (H, W).  Source cells → 0.0; cells with
        no reachable source → ``np.inf``.  Values are in world metres.
    """
    if not np.any(mask):
        return np.full(mask.shape, np.inf, dtype=np.float64)

    if _HAS_SCIPY_EDT:
        # distance_transform_edt measures distance from False background to
        # nearest True foreground.  Invert mask: background = non-source.
        dist = _edt(~mask).astype(np.float64) * float(cell_size)
        dist[mask] = 0.0
        return dist

    # --- Two-pass 8-connected chamfer fallback ----------------------------
    # Chamfer weights: axial = 1 cell, diagonal = √2 cells.
    SQRT2 = math.sqrt(2.0)
    INF = float(mask.shape[0] + mask.shape[1] + 2)
    h, w = mask.shape
    dist = np.where(mask, 0.0, INF).astype(np.float64)

    # Forward pass (top-left → bottom-right): check N, NW, NE, W neighbours
    for y in range(h):
        for x in range(w):
            if dist[y, x] == 0.0:
                continue
            best = dist[y, x]
            if y > 0:
                best = min(best, dist[y - 1, x] + 1.0)
                if x > 0:
                    best = min(best, dist[y - 1, x - 1] + SQRT2)
                if x < w - 1:
                    best = min(best, dist[y - 1, x + 1] + SQRT2)
            if x > 0:
                best = min(best, dist[y, x - 1] + 1.0)
            dist[y, x] = best

    # Backward pass (bottom-right → top-left): check S, SE, SW, E neighbours
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            if dist[y, x] == 0.0:
                continue
            best = dist[y, x]
            if y < h - 1:
                best = min(best, dist[y + 1, x] + 1.0)
                if x < w - 1:
                    best = min(best, dist[y + 1, x + 1] + SQRT2)
                if x > 0:
                    best = min(best, dist[y + 1, x - 1] + SQRT2)
            if x < w - 1:
                best = min(best, dist[y, x + 1] + 1.0)
            dist[y, x] = best

    dist *= float(cell_size)
    dist[dist >= INF * float(cell_size) * 0.5] = np.inf
    return dist


# ===========================================================================
# Geology Feature Generators  (Clusters L-P gap fills)
#
# Each function is pure numpy — accepts a (H, W) heightmap + params,
# returns a modified heightmap or a feature mask. Deterministic given seed.
# ===========================================================================


def apply_periglacial_patterns(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
    frost_heave_scale: float = 0.02,
    cell_spacing: int = 0,
    jitter: float = 0.65,
) -> np.ndarray:
    """Apply periglacial patterned-ground features to a heightmap.

    Simulates frost heave polygon patterns (sorted circles / stone stripes)
    using a jittered-grid Voronoi cell structure that produces regular polygon
    networks matching real periglacial stone polygon fields.  A jittered regular
    grid ensures spacing that mirrors freeze-thaw sorting (typically 0.5–2 m
    centre spacing), unlike purely random seeds which cannot produce the
    characteristic regularity.

    Higher-elevation cells get stronger displacement, mimicking permafrost
    processes. A slope-aligned striping term adds stone-stripe texture in the
    dominant downhill direction.

    Args:
        heightmap: (H, W) float64 terrain heights.
        seed: Deterministic RNG seed.
        intensity: Feature strength multiplier [0, 1].
        frost_heave_scale: Amplitude of frost-heave bumps (metres).
        cell_spacing: Target polygon diameter in grid cells.  0 = auto
            (roughly sqrt(H*W) / 12, clamped to [4, 40]).
        jitter: Fraction of cell_spacing by which centres are randomly
            displaced from the grid vertices [0 = regular, 1 = full jitter].

    Returns:
        Modified (H, W) heightmap with periglacial micro-relief.
    """
    if intensity <= 0.0:
        return heightmap.copy()
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_periglacial")

    # --- Jittered-grid Voronoi centres -------------------------------------------
    # Auto-size: aim for ~12 polygon rows across the shorter axis.
    if cell_spacing <= 0:
        cell_spacing = int(np.clip(min(h, w) / 12.0, 4, 40))
    spacing = max(cell_spacing, 1)

    # Grid vertex positions
    gy_grid = np.arange(0, h + spacing, spacing, dtype=np.float64)
    gx_grid = np.arange(0, w + spacing, spacing, dtype=np.float64)
    gxx, gyy_grid = np.meshgrid(gx_grid, gy_grid)  # (rows, cols)
    n_pts = gxx.size
    jitter_amp = spacing * jitter
    center_y = (gyy_grid.ravel() + rng.uniform(-jitter_amp, jitter_amp, n_pts)).clip(0, h - 1)
    center_x = (gxx.ravel() + rng.uniform(-jitter_amp, jitter_amp, n_pts)).clip(0, w - 1)

    # Distance to nearest Voronoi centre
    ys = np.arange(h, dtype=np.float64)
    xs = np.arange(w, dtype=np.float64)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")  # (H, W)

    n_centers = len(center_y)
    if _HAS_SCIPY:
        from scipy.spatial import KDTree
        pts = np.stack([center_y, center_x], axis=1)
        query_pts = np.stack([yy.ravel(), xx.ravel()], axis=1)
        tree = KDTree(pts)
        # k=2 lets us build a boundary sharpness map (ratio of 2nd/1st dist)
        dists, _ = tree.query(query_pts, k=min(2, n_centers))
        if dists.ndim == 1:
            min_dist = dists.reshape(h, w)
            second_dist = min_dist  # degenerate: only one centre
        else:
            min_dist = dists[:, 0].reshape(h, w)
            second_dist = dists[:, 1].reshape(h, w)
    else:
        dy = yy[np.newaxis] - center_y[:, np.newaxis, np.newaxis]
        dx = xx[np.newaxis] - center_x[:, np.newaxis, np.newaxis]
        all_dists = np.sqrt(dy ** 2 + dx ** 2)
        sorted_d = np.sort(all_dists, axis=0)
        min_dist = sorted_d[0]
        second_dist = sorted_d[1] if n_centers > 1 else sorted_d[0]

    # Boundary sharpness: cells close to a polygon edge (min ≈ second)
    # produce ridge, cell interiors produce plateau — matches real stone rings.
    boundary_ratio = np.where(second_dist > 1e-6, min_dist / (second_dist + 1e-9), 1.0)
    # boundary_ratio → 0 near edges (ridge), → 1 deep inside polygon (flat)
    ridge = 1.0 - np.clip(boundary_ratio * 2.0, 0.0, 1.0)  # high at boundary

    # Normalize continuous interior distance for the heave plateau
    max_d = min_dist.max() or 1.0
    interior = min_dist / max_d  # 0 near centres, 1 far from centres

    # AAA fix: real periglacial stone-polygon networks have DEPRESSED centres
    # (ice-wedge polygon interior thaw-lakes/troughs) and RAISED stone-rim
    # boundaries (frost-sorted coarse clasts pushed to polygon edges).
    # Previous formula raised both centres and boundaries — geometrically
    # incoherent. Corrected formula:
    #   - interior (near centre): depression (negative displacement)
    #   - ridge (at boundary): raised stone rim (positive displacement)
    # The net pattern produces the characteristic "cracked mud-flat" look of
    # arctic patterned ground visible in satellite imagery and Horizon/Halo
    # arctic biome references.
    polygon_displacement = ridge * 0.8 - (1.0 - interior) * 0.3
    # Clamp so we never push the surface far below zero
    polygon_displacement = np.clip(polygon_displacement, -0.5, 1.0)
    heave = polygon_displacement * frost_heave_scale * intensity

    # Scale by elevation — stronger at high points (permafrost zone)
    elev_range = max(heightmap.max() - heightmap.min(), 1e-6)
    elev_mask = np.clip((heightmap - heightmap.min()) / elev_range * 2.0, 0.0, 1.0)

    # Slope-aligned striping: dominant gradient direction drives stone-stripe freq
    grad_y, grad_x = np.gradient(heightmap)
    mean_gy = float(grad_y.mean())
    mean_gx = float(grad_x.mean())
    dir_mag = math.sqrt(mean_gx ** 2 + mean_gy ** 2) or 1.0
    cos_dir = mean_gx / dir_mag
    sin_dir = mean_gy / dir_mag
    stripe_freq = 2.0 * math.pi / max(max(h, w) * 0.08, 1.0)
    stripe_angle = np.arctan2(grad_y, grad_x)  # local aspect
    stripe = np.sin((xx * cos_dir + yy * sin_dir) * stripe_freq + stripe_angle)
    stripe_weight = frost_heave_scale * intensity * 0.25
    heave = heave + stripe_weight * stripe

    return heightmap + heave * elev_mask


def apply_desert_pavement(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
    smoothing_radius: int = 3,
    stone_density: float = 1.0,
    moat_width: float = 0.6,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate desert pavement (reg / hamada) on low-slope areas.

    Produces a physically accurate cracked-desert-pavement surface using:

    1. **Voronoi stone cells** — jittered-grid Voronoi seeds approximate
       the naturally sorted, roughly polygonal clasts of a reg pavement.
       Each Voronoi cell becomes a rounded stone whose top sits slightly
       above the deflated substrate.

    2. **Erosion-moat ring** — a narrow trough carved around each stone
       boundary mimics the wind-deflation hollow that isolates each clast
       from its neighbours.  The moat depth scales with *intensity* and
       its width in Voronoi-distance units is controlled by *moat_width*.

    3. **Wind-deflation substrate** — pavement zones are box-filtered
       (wind polishes exposed surfaces flat) before the stone micro-relief
       is overlaid.

    The function returns the modified heightmap and a float pavement_mask
    (H, W) in [0, 1] that can drive a rock / gravel material shader.

    Args:
        heightmap: (H, W) float64 terrain heights.
        seed: Deterministic RNG seed.
        intensity: Overall feature strength [0, 1].
        smoothing_radius: Kernel half-width for wind-deflation substrate
            smoothing (cells).
        stone_density: Relative density of Voronoi stones.  1.0 = one
            stone per ~(min(H,W)/16)^2 cells; higher values pack more
            stones.
        moat_width: Width of the erosion moat in normalised Voronoi
            distance units [0, 1].  0.3–0.7 is visually realistic.

    Returns:
        Tuple of (modified heightmap, pavement_mask).
    """
    h, w = heightmap.shape
    if intensity <= 0.0:
        return heightmap.copy(), np.zeros((h, w), dtype=np.float64)

    rng = _rng_from_seed(seed, "biome_desert_pavement")

    # ---- Pavement eligibility: flat + low-elevation zones ---------------
    gy_g, gx_g = np.gradient(heightmap)
    slope = np.sqrt(gx_g ** 2 + gy_g ** 2)
    flat_mask = 1.0 - np.clip(slope / max(float(slope.max()), 1e-6) * 4.0, 0.0, 1.0)
    elev_norm = (heightmap - float(heightmap.min())) / max(
        float(heightmap.max() - heightmap.min()), 1e-6
    )
    low_mask = 1.0 - np.clip(elev_norm * 2.0, 0.0, 1.0)
    eligibility = flat_mask * low_mask  # [0,1], high where pavement can form

    # ---- Wind-deflation substrate ---------------------------------------
    smoothed_base = _box_filter_2d(heightmap.astype(np.float64), smoothing_radius)

    # ---- Jittered-grid Voronoi stones -----------------------------------
    # Target: one stone per cell_sz × cell_sz pixel block.
    # stone_density scales the block size (higher density → smaller blocks).
    base_cell = max(int(min(h, w) / (16.0 * max(stone_density, 0.1))), 3)
    cell_sz = max(base_cell, 3)

    gy_grid = np.arange(cell_sz // 2, h + cell_sz, cell_sz, dtype=np.float64)
    gx_grid = np.arange(cell_sz // 2, w + cell_sz, cell_sz, dtype=np.float64)
    gxx, gyy = np.meshgrid(gx_grid, gy_grid)
    n_pts = gxx.size
    jitter = cell_sz * 0.42
    cy = np.clip(gyy.ravel() + rng.uniform(-jitter, jitter, n_pts), 0.0, h - 1.0)
    cx = np.clip(gxx.ravel() + rng.uniform(-jitter, jitter, n_pts), 0.0, w - 1.0)

    # Pixel coordinate grids
    ys = np.arange(h, dtype=np.float64)
    xs = np.arange(w, dtype=np.float64)
    yy_grid, xx_grid = np.meshgrid(ys, xs, indexing="ij")   # (H, W)

    # Compute distance to nearest and second-nearest Voronoi centre.
    # Use KDTree when scipy is available; otherwise brute-force in chunks.
    if _HAS_SCIPY:
        from scipy.spatial import KDTree
        pts = np.stack([cy, cx], axis=1)
        qpts = np.stack([yy_grid.ravel(), xx_grid.ravel()], axis=1)
        tree = KDTree(pts)
        k = min(2, n_pts)
        dists, _ = tree.query(qpts, k=k)
        if dists.ndim == 1 or k == 1:
            d1 = dists.ravel().reshape(h, w)
            d2 = d1
        else:
            d1 = dists[:, 0].reshape(h, w)
            d2 = dists[:, 1].reshape(h, w)
    else:
        # Brute-force: process in row-batches to cap peak memory
        batch = max(1, 512 * 512 // max(n_pts, 1))
        flat_y = yy_grid.ravel()
        flat_x = xx_grid.ravel()
        d1_flat = np.empty(h * w, dtype=np.float64)
        d2_flat = np.empty(h * w, dtype=np.float64)
        for start in range(0, h * w, batch):
            end = min(start + batch, h * w)
            dy = flat_y[start:end, np.newaxis] - cy[np.newaxis, :]
            dx = flat_x[start:end, np.newaxis] - cx[np.newaxis, :]
            d = np.sqrt(dy ** 2 + dx ** 2)
            d_sorted = np.sort(d, axis=1)
            d1_flat[start:end] = d_sorted[:, 0]
            d2_flat[start:end] = d_sorted[:, 1] if d_sorted.shape[1] > 1 else d_sorted[:, 0]
        d1 = d1_flat.reshape(h, w)
        d2 = d2_flat.reshape(h, w)

    # ---- Voronoi edge distance in normalised units ----------------------
    # At the cell boundary d1 == d2; normalise so the boundary is at 1.0.
    d_sum = d1 + d2
    # edge_t = 0 at stone centres, 1 at Voronoi boundaries
    edge_t = np.ones_like(d1, dtype=np.float64)
    np.divide(d1, d_sum * 0.5, out=edge_t, where=d_sum > 1e-6)
    edge_t = np.clip(edge_t, 0.0, 1.0)

    # ---- Stone top surface: slightly raised, rounded polygon shape ------
    # Rounded stone: height rises as a smooth cosine from 0 (boundary)
    # to stone_bump at centre, giving a convex cobble profile.
    stone_bump = 0.004 * intensity
    # Smoothstep from edge inward: full bump for edge_t < (1 - moat_width)
    inner_t = np.clip(
        (edge_t - float(moat_width)) / max(1.0 - float(moat_width), 1e-6),
        0.0, 1.0,
    )
    stone_profile = stone_bump * (inner_t * inner_t * (3.0 - 2.0 * inner_t))

    # ---- Erosion moat: trough at Voronoi boundaries ---------------------
    # moat_t = 1 at the exact Voronoi edge, 0 outside the moat width.
    moat_t = np.clip(1.0 - edge_t / max(float(moat_width), 1e-6), 0.0, 1.0)
    moat_depth = 0.006 * intensity
    moat_profile = moat_depth * (moat_t ** 2)

    # ---- Pavement coverage mask ----------------------------------------
    pavement_mask = np.clip(eligibility * intensity, 0.0, 1.0)

    # ---- Combine layers -------------------------------------------------
    # 1. Start from wind-deflated substrate inside pavement zones.
    result = (
        heightmap * (1.0 - pavement_mask)
        + smoothed_base * pavement_mask
    )
    # 2. Overlay stone bumps and erosion moats, gated by pavement eligibility.
    result = result + (stone_profile - moat_profile) * eligibility * intensity
    result = np.clip(result, 0.0, 1.0)

    return result, pavement_mask


def compute_spring_line_mask(
    heightmap: np.ndarray,
    geology_layers: int = 3,
    seed: int = 0,
) -> np.ndarray:
    """Identify spring line positions where water emerges at geological layer boundaries.

    Returns a (H, W) float mask [0, 1] where 1 marks likely spring locations.
    Springs form at the intersection of two conditions:
      1. Geological stratum boundaries (impermeable/permeable contact zones).
      2. Topographic convergence — hollows and valley axes where subsurface
         flow accumulates before surfacing.

    Topographic convergence is computed via a D8 multi-directional flow
    accumulation pass: each cell drains to its lowest neighbour; accumulated
    upslope cell count is log-normalised so valley-bottom convergence zones
    score near 1.0 and divergent ridgelines score near 0.0.

    Args:
        heightmap: (H, W) float64 terrain heights.
        geology_layers: Number of geological strata to simulate.
        seed: Deterministic RNG seed (for layer offset noise).

    Returns:
        Spring-line mask (H, W) float64 in [0, 1].
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_spring_line")

    elev_norm = (heightmap - heightmap.min()) / max((heightmap.max() - heightmap.min()), 1e-6)

    # ------------------------------------------------------------------
    # 1. Slope — springs emerge on mid-range slopes (not flats/cliffs)
    # ------------------------------------------------------------------
    gy, gx = np.gradient(heightmap)
    slope = np.sqrt(gx ** 2 + gy ** 2)
    slope_norm = slope / max(slope.max(), 1e-6)
    slope_band = np.exp(-((slope_norm - 0.3) ** 2) / 0.02)

    # ------------------------------------------------------------------
    # 2. Flow accumulation (D8) — topographic convergence
    #    Each cell routes to its single steepest-descent neighbour.
    #    Accumulation = number of upstream contributing cells (log-scaled).
    # ------------------------------------------------------------------
    # 8-directional neighbour offsets (row, col)
    _D8_ROWS = np.array([-1, -1, -1,  0,  0,  1,  1,  1], dtype=np.int32)
    _D8_COLS = np.array([-1,  0,  1, -1,  1, -1,  0,  1], dtype=np.int32)

    # For each cell find index of lowest neighbour (steepest descent D8)
    flat_h = heightmap.ravel()
    n_cells = h * w

    # Build row/col index arrays
    row_idx = np.repeat(np.arange(h, dtype=np.int32), w)
    col_idx = np.tile(np.arange(w, dtype=np.int32), h)

    # Receiver array: initially self (outlet/boundary cells)
    receiver = np.arange(n_cells, dtype=np.int32)
    min_elev = flat_h.copy()

    for dr, dc in zip(_D8_ROWS, _D8_COLS):
        nr = row_idx + dr
        nc = col_idx + dc
        valid = (nr >= 0) & (nr < h) & (nc >= 0) & (nc < w)
        nb_flat = np.where(valid, nr * w + nc, -1)
        nb_elev = np.where(valid, flat_h[np.clip(nb_flat, 0, n_cells - 1)], np.inf)
        lower = nb_elev < min_elev
        receiver = np.where(lower, nb_flat.astype(np.int32), receiver)
        min_elev = np.where(lower, nb_elev, min_elev)

    # FIX-B14-P1-11: Replace O(N) Python topo loop with depth-level vectorized
    # accumulation.  The original loop visited ~1.05 M cells one at a time in
    # Python; this version groups cells by topological depth and processes each
    # depth level with a single np.add.at scatter call.
    #
    # D8 flow accumulation is sequentially dependent — a cell can only donate its
    # full accumulated count after all its upstream cells have donated to it.
    # Grouping by topological depth (longest upstream hop count) makes cells at
    # the same depth mutually independent, so one np.add.at call handles the
    # whole level.  max_depth is typically 50-200 for real terrain, so the outer
    # Python loop runs ~50-200 iterations instead of ~1 M.
    accumulation = np.ones(n_cells, dtype=np.float64)  # each cell contributes 1

    # Identify outlet cells (receiver == self — local sinks or boundary).
    is_outlet_mask = receiver == np.arange(n_cells, dtype=np.int32)  # (n_cells,)
    non_outlets = np.where(~is_outlet_mask)[0]  # indices of cells that drain

    # Compute topological depth fully vectorized using np.maximum.at.
    # depth[i] = longest upstream chain length (0 for outlets).
    # Strategy: process cells from highest to lowest elevation (sort_order).
    # Each non-outlet cell propagates (its own depth + 1) to its receiver via
    # np.maximum.at, which keeps the maximum depth seen at each receiver.
    # Because sort_order is high-to-low, every donor is processed before its
    # receiver appears as a donor — so depths propagate correctly in one pass.
    sort_order = np.argsort(-flat_h)  # descending elevation (high → low)
    depth = np.zeros(n_cells, dtype=np.int32)
    non_outlet_sorted = sort_order[~is_outlet_mask[sort_order]]  # non-outlets in topo order
    np.maximum.at(depth, receiver[non_outlet_sorted], depth[non_outlet_sorted] + 1)

    max_depth = int(depth.max()) if n_cells > 0 else 0

    # Scatter accumulation level by level from deepest (farthest from outlet)
    # down to depth 1.  At each depth d, all cells are topologically independent
    # (no cell at depth d drains to another cell at depth d), so np.add.at is
    # safe to call once per level.
    for d in range(max_depth, 0, -1):
        level_cells = non_outlets[depth[non_outlets] == d]
        if level_cells.size:
            np.add.at(accumulation, receiver[level_cells], accumulation[level_cells])

    # Log-normalise to [0, 1]: high accumulation = convergence zones
    log_acc = np.log1p(accumulation)
    convergence = log_acc.reshape(h, w)
    convergence /= max(convergence.max(), 1e-9)

    # ------------------------------------------------------------------
    # 3. Geological layer boundaries
    # ------------------------------------------------------------------
    layer_thickness = 1.0 / max(geology_layers, 1)
    offsets = rng.uniform(-0.02, 0.02, size=geology_layers)
    strata_mask = np.zeros((h, w), dtype=np.float64)
    for i in range(geology_layers):
        boundary = layer_thickness * (i + 1) + offsets[i]
        dist_to_boundary = np.abs(elev_norm - boundary)
        strata_mask += np.exp(-(dist_to_boundary ** 2) / 0.001)
    strata_mask = np.clip(strata_mask, 0.0, 1.0)

    # ------------------------------------------------------------------
    # 4. Combine: stratum contact × convergence × slope suitability
    # ------------------------------------------------------------------
    spring_mask = strata_mask * convergence * slope_band
    return np.clip(spring_mask, 0.0, 1.0)


def apply_landslide_scars(
    heightmap: np.ndarray,
    seed: int = 0,
    num_slides: int = 3,
    scar_depth: float = 0.05,
    runout_factor: float = 2.5,
    taper_ratio: float = 0.35,
) -> np.ndarray:
    """Carve landslide scars and deposit runout fans into a heightmap.

    Real landslide scars are gradient-oriented elongated erosion features that
    taper from a wide headscarp at the top to a narrow toe at the base.
    Material excavated from the scar is deposited along the steepest-descent
    path below the origin as a runout fan, with deposition decaying with
    distance.

    Improvements over the previous version:
    - Scar is oriented along the actual terrain gradient (slope direction), not
      just an uphill ellipse.  The headscarp half (uphill) is wider; the toe
      half (downhill) tapers to ``taper_ratio * scar_r``, matching observed
      geometry of translational slides.
    - Cross-sectional width varies linearly along the scar length (widest at
      the crown, narrowest at the toe) via a per-pixel taper weight.
    - Erosion depth applied to the heightmap is proportional to the scar mask
      so the scar floor curves (concave bowl) rather than flat-bottoms.
    - Runout fan width grows with step index (debris spreading), matching
      observed runout-fan morphology.

    Args:
        heightmap: (H, W) float64 terrain heights.
        seed: Deterministic RNG seed.
        num_slides: Number of landslide features to generate.
        scar_depth: Maximum depth of the scar (metres, relative).
        runout_factor: Length of runout path relative to scar_r.
        taper_ratio: Cross-width at toe as a fraction of crown width [0–1].
            0.35 matches field measurements for typical translational slides.

    Returns:
        Modified (H, W) heightmap with landslide features.
    """
    h, w = heightmap.shape
    result = heightmap.copy()
    rng = _rng_from_seed(seed, "biome_landslide_scars")

    gy, gx = np.gradient(heightmap)
    slope = np.sqrt(gx ** 2 + gy ** 2)

    ys = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xs = np.arange(w, dtype=np.float64).reshape(1, -1)

    n_walk_steps = max(8, int(max(h, w) * 0.12))
    deposit_per_step = scar_depth * 0.6 / max(n_walk_steps, 1)

    for _ in range(num_slides):
        flat_slope = slope.ravel()
        prob = flat_slope / max(flat_slope.sum(), 1e-12)
        idx = rng.choice(len(prob), p=prob)
        oy, ox = divmod(idx, w)

        scar_r = rng.uniform(max(3, h * 0.03), max(5, h * 0.08))
        crown_width = scar_r          # cross-width at headscarp
        toe_width   = scar_r * taper_ratio  # cross-width at toe

        # ---- Gradient-oriented scar axes ----------------------------------------
        # Downhill unit vector at origin (steepest descent direction)
        raw_dy = -gy[oy, ox]
        raw_dx = -gx[oy, ox]
        grad_norm = math.sqrt(raw_dx ** 2 + raw_dy ** 2) or 1.0
        # downhill axis (positive = toward toe)
        d_hat_y = raw_dy / grad_norm
        d_hat_x = raw_dx / grad_norm
        # uphill axis (positive = toward crown)
        u_hat_y = -d_hat_y
        u_hat_x = -d_hat_x
        # cross-slope (perpendicular to downhill, right-hand)
        c_hat_y =  d_hat_x   # 90° rotation
        c_hat_x = -d_hat_y

        # Project every grid cell onto scar axes
        rel_y = ys - oy
        rel_x = xs - ox
        along_up   = rel_y * u_hat_y + rel_x * u_hat_x   # + toward crown
        along_down = rel_y * d_hat_y + rel_x * d_hat_x   # + toward toe
        cross      = rel_y * c_hat_y + rel_x * c_hat_x   # ± lateral

        # ---- Tapered scar shape -------------------------------------------------
        # Scar length uphill = scar_r * 1.6 (headscarp region)
        scar_len_up = scar_r * 1.6
        # t ∈ [0, 1]: 0 at crown, 1 at toe (below origin)
        # We split scar into uphill half (crown) and a short downhill heel.
        uphill_half = np.clip(along_up / scar_len_up, 0.0, 1.0)   # 0 at origin, 1 at crown
        # For the toe region (below origin), extend a short heel
        scar_len_down = scar_r * 0.4
        downhill_heel = np.clip(along_down / scar_len_down, 0.0, 1.0)

        # Taper: cross half-width varies from crown_width (at t=0 uphill) to toe_width
        # For uphill region: width = lerp(crown_width, toe_width, uphill_half)
        # For downhill heel: width = lerp(crown_width, toe_width, downhill_heel) — narrows fast
        width_uphill   = crown_width * (1.0 - uphill_half)   + toe_width * uphill_half
        width_downhill = crown_width * (1.0 - downhill_heel) + toe_width * downhill_heel

        # Normalised distance within each half
        norm_dist_up   = np.where(width_uphill   > 1e-9, np.abs(cross) / width_uphill,   1.0)
        norm_dist_down = np.where(width_downhill > 1e-9, np.abs(cross) / width_downhill, 1.0)

        # Combine: uphill half active where along_up >= 0, downhill heel otherwise
        norm_dist = np.where(along_up >= 0, norm_dist_up, norm_dist_down)
        # Also require that we are within the scar length boundaries
        in_bounds  = (along_up <= scar_len_up) & (along_down <= scar_len_down)
        scar_mask  = np.clip(1.0 - norm_dist, 0.0, 1.0) ** 2 * in_bounds.astype(np.float64)

        # Apply erosion: concave bowl shape (deeper at centre)
        result -= scar_mask * scar_depth

        # ---- Lateral ridges (levees) ----------------------------------------
        # Real translational slides push material sideways along the failure
        # plane boundaries, forming raised lateral ridges (lateral scarps).
        # Each lateral ridge runs along the uphill half of the scar, parallel
        # to the downhill axis, offset ±crown_width from the centre.
        lateral_offset = crown_width * 0.9       # ridge crest sits just inside crown
        lateral_width  = scar_r * 0.20            # narrow raised welt
        for sign_lr in (-1.0, 1.0):
            # Distance from the lateral-ridge centreline
            lat_cross_dist = np.abs(cross - sign_lr * lateral_offset)
            # Ridge is only in the uphill half (headscarp region)
            lat_along_mask = (along_up >= 0) & (along_up <= scar_len_up)
            lat_mask = (
                np.clip(1.0 - lat_cross_dist / max(lateral_width, 1e-9), 0.0, 1.0) ** 2
                * lat_along_mask.astype(np.float64)
            )
            # Ridge height ≈ 25% of scar depth — compressed material pile
            result += lat_mask * scar_depth * 0.25

        # ---- Downslope runout deposit -------------------------------------------
        # Walk steepest-descent from slide origin; fan spreads wider with distance.
        py, px = float(oy), float(ox)
        for step in range(n_walk_steps):
            iy = int(np.clip(round(py), 0, h - 1))
            ix = int(np.clip(round(px), 0, w - 1))
            step_dy = -gy[iy, ix]
            step_dx = -gx[iy, ix]
            step_norm = math.sqrt(step_dx ** 2 + step_dy ** 2) or 1.0
            step_dy /= step_norm
            step_dx /= step_norm
            py += step_dy
            px += step_dx
            # Fan widens with distance (debris spreads laterally)
            spread = step / max(n_walk_steps - 1, 1)           # 0→1
            fan_r  = scar_r * (0.5 + spread * runout_factor * 0.4)
            # Deposition decays with step distance (exponential tail)
            decay = math.exp(-3.0 * step / n_walk_steps)
            fan_dist = np.sqrt((ys - py) ** 2 + (xs - px) ** 2)
            fan_mask = np.clip(1.0 - fan_dist / fan_r, 0.0, 1.0)
            result += fan_mask * deposit_per_step * decay

    return result


def apply_hot_spring_features(
    heightmap: np.ndarray,
    seed: int = 0,
    num_springs: int = 2,
    pool_radius: float = 5.0,
    pool_depth: float = 0.03,
    terrace_rings: int = 4,
    hot_radius: float = 0.0,
    heat_sigma: float = 0.0,
) -> tuple[np.ndarray, list[dict]]:
    """Create hot spring pools with travertine terraces and radial heat gradients.

    Returns the modified heightmap and a list of spring location dicts for
    downstream VFX placement (steam, mineral colouring, vegetation suppression).

    Each spring now emits a radial heat field modelled as a Gaussian that:
    - Suppresses vegetation density within ``hot_radius`` (heat stress kills
      ground cover — logged as ``veg_density_suppression`` in the spring dict).
    - Raises humidity in the surrounding zone (evaporation from hot water —
      logged as ``humidity_boost``), which affects shader wetness masks.

    The heat gradient is stored in the returned spring dicts so downstream
    scatter and shader systems can query it without re-computing.

    Args:
        heightmap: (H, W) float64 terrain heights.
        seed: Deterministic RNG seed.
        num_springs: Number of hot spring pools to place.
        pool_radius: Radius of the main pool (in grid cells).
        pool_depth: Depth of pool depression (metres, relative).
        terrace_rings: Number of travertine terrace steps.
        hot_radius: Radius of the high-temperature kill zone in grid cells.
            Vegetation density is suppressed here.  0 = auto (3 × pool_radius).
        heat_sigma: Sigma of the Gaussian heat falloff in grid cells.
            0 = auto (2 × pool_radius), giving a smooth gradient that reaches
            near-zero at ~2 sigma (≈ 4 × pool_radius from the vent).

    Returns:
        Tuple of (modified heightmap, list of spring info dicts).

        Each spring dict contains:
            grid_y, grid_x       — integer cell coordinates of vent
            pool_radius          — as passed
            elevation            — heightmap value at vent
            heat_map             — (H, W) float64 in [0, 1], 1 = hottest
            veg_density_suppression — (H, W) float64 in [0, 1],
                                       1 = fully suppressed (at vent centre)
            humidity_boost       — (H, W) float64 in [0, 1],
                                   higher in warm mist annulus around vent
    """
    h, w = heightmap.shape
    result = heightmap.copy()
    rng = _rng_from_seed(seed, "biome_hot_spring_features")
    springs: list[dict] = []

    ys = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xs = np.arange(w, dtype=np.float64).reshape(1, -1)

    # Compute gradient once — used to skew ring centres downhill
    gy, gx = np.gradient(heightmap)
    downhill_bias = pool_radius * 0.5

    # Precompute ring radii and widths — loop invariants
    ring_rs = np.array([pool_radius + r * pool_radius * 0.4 for r in range(1, terrace_rings + 1)])
    ring_width = pool_radius * 0.15
    ring_step_hs = np.array([
        pool_depth * 0.15 * (1.0 - r / (terrace_rings + 1))
        for r in range(1, terrace_rings + 1)
    ])

    # Resolve auto defaults once
    _hot_radius  = hot_radius  if hot_radius  > 0.0 else pool_radius * 3.0
    _heat_sigma  = heat_sigma  if heat_sigma  > 0.0 else pool_radius * 2.0
    sigma_sq = max(_heat_sigma ** 2, 1e-6)

    for _ in range(num_springs):
        # Place springs in mid-elevation zones
        elev_norm = (heightmap - heightmap.min()) / max((heightmap.max() - heightmap.min()), 1e-6)
        mid_mask = np.exp(-((elev_norm - 0.4) ** 2) / 0.05)
        flat_mid = mid_mask.ravel()
        prob = flat_mid / max(flat_mid.sum(), 1e-12)
        idx = rng.choice(len(prob), p=prob)
        sy, sx = divmod(idx, w)

        # Skew pool centre downhill
        grad_y = gy[sy, sx]
        grad_x = gx[sy, sx]
        grad_mag = math.sqrt(grad_x ** 2 + grad_y ** 2) or 1.0
        ring_cy = sy - grad_y / grad_mag * downhill_bias
        ring_cx = sx - grad_x / grad_mag * downhill_bias

        dist_pool  = np.sqrt((ys - sy) ** 2 + (xs - sx) ** 2)
        dist_rings = np.sqrt((ys - ring_cy) ** 2 + (xs - ring_cx) ** 2)

        # Main pool depression
        pool_mask = np.clip(1.0 - dist_pool / pool_radius, 0.0, 1.0) ** 2
        result -= pool_mask * pool_depth

        # Travertine terraces — vectorised over all rings at once.
        # AAA fix: each ring radius is noise-perturbed so terraces are
        # asymmetric and irregular like real Yellowstone/Pamukkale travertine
        # rather than perfect concentric circles.  We use a low-frequency
        # angular variation (4–6 lobes) to simulate lobate terrace geometry.
        dist_rings_full = np.sqrt((ys - ring_cy) ** 2 + (xs - ring_cx) ** 2)
        theta = np.arctan2(ys - ring_cy, xs - ring_cx)   # (H, W) angle field
        # Angular lobes: amplitude = 15% of ring spacing, 4 lobes ± random phase
        lobe_phases = rng.uniform(0.0, 2.0 * math.pi, len(ring_rs))
        lobe_amps   = ring_rs * 0.15  # 15% of ring radius
        lobe_counts = rng.integers(3, 7, size=len(ring_rs))
        # Vectorised per-ring radius perturbation
        perturbed_rs = (
            ring_rs[:, np.newaxis, np.newaxis]
            + lobe_amps[:, np.newaxis, np.newaxis]
            * np.sin(
                lobe_counts[:, np.newaxis, np.newaxis] * theta[np.newaxis, :, :]
                + lobe_phases[:, np.newaxis, np.newaxis]
            )
        )   # shape (terrace_rings, H, W)
        ring_dist = np.abs(
            dist_rings_full[np.newaxis, :, :] - perturbed_rs
        )
        terrace_masks = np.clip(1.0 - ring_dist / ring_width, 0.0, 1.0)
        result += (terrace_masks * ring_step_hs[:, np.newaxis, np.newaxis]).sum(axis=0)

        # ---- Radial heat gradient (Gaussian falloff) ----------------------------
        dist_sq   = (ys - sy) ** 2 + (xs - sx) ** 2
        heat_map  = np.exp(-dist_sq / (2.0 * sigma_sq))   # 1.0 at vent, 0 far away

        # Vegetation suppression: strongest within hot_radius, tapers beyond
        # Use complementary logistic so the kill zone has a sharp inner edge
        # but a smooth outer gradient.
        norm_dist = dist_pool / max(_hot_radius, 1e-6)     # 0 at vent, 1 at hot_radius
        veg_suppression = np.clip(1.0 - norm_dist, 0.0, 1.0) ** 0.5
        # Also apply the wider Gaussian falloff for a smooth outer skirt
        veg_suppression = np.maximum(veg_suppression, heat_map * 0.4)
        veg_suppression = np.clip(veg_suppression, 0.0, 1.0)

        # Humidity boost: peaks in the warm annulus just outside the pool
        # (steam zone), not at the vent itself (too hot, water vaporises fast)
        annulus_r   = pool_radius * 2.5
        annulus_sig = pool_radius * 1.2
        humidity_boost = np.exp(-((dist_pool - annulus_r) ** 2) / (2.0 * annulus_sig ** 2))
        humidity_boost = np.clip(humidity_boost, 0.0, 1.0)

        springs.append({
            "grid_y":                  int(sy),
            "grid_x":                  int(sx),
            "pool_radius":             float(pool_radius),
            "elevation":               float(heightmap[sy, sx]),
            "heat_map":                heat_map.astype(np.float64),
            "veg_density_suppression": veg_suppression.astype(np.float64),
            "humidity_boost":          humidity_boost.astype(np.float64),
        })

    return result, springs


def apply_reef_platform(
    heightmap: np.ndarray,
    sea_level: float = 0.0,
    seed: int = 0,
    reef_width: float = 8.0,
    reef_height: float = 0.01,
    tidal_range: float | None = None,
    tidal_threshold: float = 0.1,
    max_reef_distance_m: float = 200.0,
    cell_size: float = 1.0,
    stack: object | None = None,
) -> np.ndarray:
    """Build fringing reef platforms at the coastline with coral buildup zones
    and wave-exposure gradient.

    AAA improvements over the previous uniform reef band:

    1. **Reef crest / back-reef / fore-reef geometry** — the platform is
       split into three bathymetric zones keyed to shore distance:
       - *Back-reef lagoon* (inner half-width): shallow, calm, low buildup.
       - *Reef crest* (peak near half-width): highest point, breaks waves.
       - *Fore-reef slope* (outer half-width): steeply descending, moderate
         buildup from coral growth on the wave-facing face.

    2. **Coral buildup zones** — Voronoi-clustered micro-relief (small
       raised mounds) models individual coral heads in the back-reef and
       crest zones.  Buildup amplitude falls off sharply in the fore-reef
       where wave energy inhibits massive coral growth.

    3. **Wave-exposure gradient** — the coastline orientation is derived
       from the land-mask gradient.  Exposed (windward) shores get stronger
       reef accretion; leeward shores get weaker accretion, matching
       real-world fringing reef asymmetry.

    4. **Depth-adjusted clamping** — result is clamped to sea_level only
       inside the underwater mask, preserving any above-water rim detail.

    Args:
        heightmap: (H, W) float64 terrain heights.
        sea_level: Water surface elevation.
        seed: Deterministic RNG seed.
        reef_width: Half-width of reef platform band in grid cells.
            Full platform width = 2 × reef_width.
        reef_height: Peak reef crest height above ambient seabed.
        tidal_range: Optional scalar or (H, W) tidal amplitude array.
            If None, ``stack.tidal`` is checked, then a distance guard
            based on ``max_reef_distance_m`` / ``cell_size`` is used.
        tidal_threshold: Minimum tidal value for reef formation.
        max_reef_distance_m: Maximum land-distance (metres) for reef
            formation when no tidal data is available.
        cell_size: Metres per grid cell.  Used for the distance guard and
            the ``_distance_from_mask`` world-metre conversion.
        stack: Optional data stack; checked for a ``.tidal`` attribute.

    Returns:
        Modified (H, W) heightmap with fringing reef features.
    """
    h, w = heightmap.shape
    result = heightmap.copy().astype(np.float64)
    rng = _rng_from_seed(seed, "biome_reef_platform")

    underwater = heightmap < sea_level
    above = ~underwater

    if not underwater.any() or not above.any():
        return result

    # ---- Shore distance in world metres (exact Euclidean via EDT) -------
    # distance_from_mask(underwater, cell_size) returns metres from each
    # underwater cell to the nearest land cell — i.e., distance offshore.
    shore_dist_m = _distance_from_mask(above, cell_size=cell_size)
    # Convert to grid cells for reef geometry (reef_width is in cells)
    shore_dist_cells = shore_dist_m / max(float(cell_size), 1e-6)

    # ---- Tidal / proximity gate -----------------------------------------
    tidal = tidal_range
    if tidal is None and stack is not None:
        tidal = stack.get("tidal")

    if tidal is not None:
        tidal_arr = np.broadcast_to(np.asarray(tidal, dtype=np.float64), (h, w))
        tidal_gate = (tidal_arr > tidal_threshold).astype(np.float64)
    else:
        max_reef_cells = max_reef_distance_m / max(float(cell_size), 1e-6)
        tidal_gate = (shore_dist_cells <= max_reef_cells).astype(np.float64)

    # Only underwater cells inside the tidal gate can host reefs
    base_gate = underwater.astype(np.float64) * tidal_gate

    # ---- Wave-exposure gradient (windward vs leeward) -------------------
    # Derive shore-normal direction from land-mask gradient.
    land_float = above.astype(np.float64)
    grad_y_land, grad_x_land = np.gradient(land_float)
    # Gradient of land mask points from sea toward land — "onshore" direction.
    # Exposure is high where there is a strong gradient (open ocean front).
    exposure = np.sqrt(grad_y_land ** 2 + grad_x_land ** 2)
    exp_max = float(exposure.max()) or 1.0
    # Smooth exposure to spread the windward signal beyond the coastline edge
    if _HAS_SCIPY:
        exposure_smooth = _scipy_ndimage.uniform_filter(
            exposure, size=max(3, int(reef_width)), mode="reflect"
        )
    else:
        exposure_smooth = _box_filter_2d(exposure, radius=max(1, int(reef_width // 2)))
    exposure_norm = np.clip(exposure_smooth / max(float(exposure_smooth.max()), 1e-6), 0.0, 1.0)
    # Accrection multiplier: windward [1.0, 1.4], leeward [0.6, 1.0]
    accretion = 0.6 + 0.8 * exposure_norm

    # ---- Three-zone reef cross-section profile --------------------------
    # t = shore_dist_cells / reef_width  → 0 = at shore, 1 = at crest, 2+ = fore-reef
    # Normalise so t=1 is the reef crest (peak height).
    t = shore_dist_cells / max(float(reef_width), 1e-6)

    # Back-reef lagoon (0 ≤ t ≤ 1): gentle ramp up to crest
    back_reef = np.clip(t, 0.0, 1.0)                                  # 0→1
    back_reef_profile = back_reef ** 1.5                               # concave ramp

    # Reef crest band (0.8 ≤ t ≤ 1.2): peaked Gaussian
    crest_profile = np.exp(-((t - 1.0) ** 2) / 0.04)                  # peak at t=1

    # Fore-reef slope (t > 1): steep dropoff
    fore_reef_t = np.clip(t - 1.0, 0.0, None)
    fore_reef_profile = np.exp(-fore_reef_t * 2.5) * np.clip(t > 1.0, 0.0, 1.0)

    # Combine: weighted sum of the three zones
    reef_profile = np.maximum(
        back_reef_profile * 0.45,
        np.maximum(crest_profile, fore_reef_profile * 0.55),
    )
    # Gate to underwater band only
    reef_profile *= base_gate

    # ---- Coral buildup zones (Voronoi micro-mounds) --------------------
    # Coral heads cluster in the back-reef and crest zones (t ≤ 1.3).
    buildup_zone = np.clip(1.0 - np.abs(t - 0.7) / 0.7, 0.0, 1.0) * base_gate

    # Sparse jittered-grid Voronoi for coral head positions
    coral_cell = max(int(reef_width * 0.8), 3)
    gy_pts = np.arange(coral_cell // 2, h + coral_cell, coral_cell, dtype=np.float64)
    gx_pts = np.arange(coral_cell // 2, w + coral_cell, coral_cell, dtype=np.float64)
    gxx_c, gyy_c = np.meshgrid(gx_pts, gy_pts)
    n_corals = gxx_c.size
    jitter_c = coral_cell * 0.45
    coral_cy = np.clip(
        gyy_c.ravel() + rng.uniform(-jitter_c, jitter_c, n_corals), 0.0, h - 1.0
    )
    coral_cx = np.clip(
        gxx_c.ravel() + rng.uniform(-jitter_c, jitter_c, n_corals), 0.0, w - 1.0
    )

    ys_g = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xs_g = np.arange(w, dtype=np.float64).reshape(1, -1)

    # Coral radius: small Gaussian mounds, randomly sized
    coral_r = rng.uniform(0.4, 1.2, n_corals)           # per-head radius (cells)
    coral_h = rng.uniform(0.3, 1.0, n_corals)           # per-head height scale

    # Vectorised: sum all coral mound contributions in one operation
    # Shape broadcast: (n, H, W) — only feasible for moderate n_corals.
    # For large grids cap at 200 mounds to avoid OOM.
    n_use = min(n_corals, 200)
    dy_c = ys_g[np.newaxis, :, :] - coral_cy[:n_use, np.newaxis, np.newaxis]
    dx_c = xs_g[np.newaxis, :, :] - coral_cx[:n_use, np.newaxis, np.newaxis]
    r2_c = dy_c ** 2 + dx_c ** 2
    sigma_c = coral_r[:n_use, np.newaxis, np.newaxis] ** 2 + 1e-9
    coral_mounds = (
        coral_h[:n_use, np.newaxis, np.newaxis]
        * np.exp(-r2_c / (2.0 * sigma_c))
    ).sum(axis=0)                                        # (H, W)

    # Normalise and scale coral mounds relative to reef_height
    coral_max = float(coral_mounds.max()) or 1.0
    coral_mounds = (coral_mounds / coral_max) * (reef_height * 0.4)

    # ---- Apply all layers -----------------------------------------------
    result += reef_profile * reef_height * accretion
    result += coral_mounds * buildup_zone

    # Clamp underwater cells to sea_level (reefs must stay submerged)
    np.minimum(result, sea_level, out=result, where=underwater)

    return result


def apply_tafoni_weathering(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
    cavity_scale: float = 0.01,
    num_cavities: int = 50,
    slope_threshold_deg: float = 50.0,
    contagion_passes: int = 2,
    contagion_radius: float = 4.0,
) -> np.ndarray:
    """Apply tafoni (honeycomb weathering) erosion pits to rock surfaces.

    Tafoni are cavernous weathering pockets that form exclusively on steep,
    exposed rock faces via salt crystallisation or differential moisture
    retention.  Four AAA-quality features:

    1. **Slope gate** — cavities are only seeded where the terrain slope
       exceeds ``slope_threshold_deg`` (default 50°).  Gentler terrain is
       skipped entirely, preventing tafoni on valley floors or hillsides.

    2. **Contagion clustering** — ``contagion_passes`` rounds of biased
       spread simulate the observed behaviour where early pockets focus
       moisture and accelerate adjacent weathering ("tafoni attract
       tafoni"), producing dense honeycomb clusters.

    3. **Void depth variation** — each cavity receives an independent depth
       multiplier drawn from a log-normal distribution (σ = 0.4) so pits
       vary from shallow dimples to deep voids, matching the multi-scale
       depth distribution seen on real honeycomb rock faces.  Cavity aspect
       ratio (rx vs ry) is also randomised to produce elliptical rather than
       perfectly round pits.

    4. **Surface contamination ring** — a positive-height annulus is raised
       around each macro-cavity.  In real tafoni, salt and moisture
       concentration raises a thin precipitation crust at the pit rim.
       This "contamination ring" elevates the rim by ~15 % of cavity depth,
       giving each pit a distinctive raised lip that catches shadow in
       renders.

    Args:
        heightmap: (H, W) float64 terrain heights.
        seed: Deterministic RNG seed.
        intensity: Weathering strength [0, 1].
        cavity_scale: Depth of individual cavities (metres, relative).
        num_cavities: Base number of tafoni cavities (scaled by the
            fraction of the map that qualifies as steep).
        slope_threshold_deg: Minimum slope in degrees for tafoni
            formation.  Cells below this threshold are excluded.
        contagion_passes: Number of attraction-spread rounds.  Each pass
            adds new cavities biased toward existing ones.  0 = off.
        contagion_radius: Attraction radius in grid cells for contagion.

    Returns:
        Modified (H, W) heightmap with tafoni pits and contamination rims.
    """
    h, w = heightmap.shape
    if intensity <= 0.0:
        return heightmap.copy()
    result = heightmap.copy()
    rng = _rng_from_seed(seed, "biome_tafoni_weathering")

    # ---- Slope gate -------------------------------------------------------
    gy, gx = np.gradient(heightmap)
    slope_mag = np.sqrt(gx ** 2 + gy ** 2)
    slope_deg = np.degrees(np.arctan(slope_mag))

    slope_max = float(slope_mag.max())
    steep_gate = (slope_deg >= slope_threshold_deg).astype(np.float64)
    if steep_gate.sum() < 1.0:
        if slope_max <= 1e-9:
            return result
        # Normalized 0-1 heightfields rarely reach literal cliff angles even
        # when they represent the steepest surface available, so fall back to
        # an adaptive gate over the non-flat slope population.
        nonflat = slope_deg[slope_deg > 1e-9]
        if nonflat.size == 0:
            return result
        adaptive_threshold = float(np.percentile(nonflat, 70.0))
        steep_gate = (slope_deg >= adaptive_threshold).astype(np.float64)

    steep_weight = np.clip(slope_mag / max(slope_max, 1e-6), 0.0, 1.0) * steep_gate

    prob_sum = float(steep_weight.sum())
    if prob_sum < 1e-12:
        return result
    base_prob = steep_weight.ravel() / prob_sum

    steep_fraction = float(steep_gate.sum()) / steep_gate.size
    effective_cavities = max(1, int(num_cavities * max(steep_fraction, 0.05)))

    ys = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xs = np.arange(w, dtype=np.float64).reshape(1, -1)

    # Pre-compute flat coordinate arrays once (hoisted from inner loops)
    _all_ys = np.broadcast_to(ys, (h, w)).ravel()
    _all_xs = np.broadcast_to(xs, (h, w)).ravel()

    # Pre-compute contagion sigma squared once
    _sigma_c_sq = max(contagion_radius ** 2, 1.0)

    placed_cy: list[int] = []
    placed_cx: list[int] = []

    def _place_cavities(
        n: int,
        rx_range: tuple,
        ry_range: tuple,
        depth_scale: float,
        prob: np.ndarray,
        add_rim: bool = False,
    ) -> None:
        """Place n cavities with depth variation and optional contamination rim.

        Depth variation: each cavity depth is scaled by an independent
        log-normal multiplier (median=1, σ=0.4) so pits range from shallow
        dimples to deep voids.

        Contamination rim (when add_rim=True): a narrow annulus at
        radius ≈ 1.5–2.5 × cavity sigma is raised by rim_fraction of the
        cavity depth, simulating the salt/moisture precipitation crust.
        """
        # Draw all random parameters up front (no per-iteration rng calls
        # inside the numpy expressions)
        indices = rng.choice(len(prob), size=n, p=prob)
        rxs = rng.uniform(*rx_range, size=n)
        rys = rng.uniform(*ry_range, size=n)
        # Log-normal depth multipliers: median=1, σ_log=0.4
        depth_mults = np.exp(rng.normal(0.0, 0.4, size=n))
        # Rim annulus radii: inner = 1.5σ, outer = 2.8σ
        rim_inner_scale = 1.5
        rim_outer_scale = 2.8
        rim_fraction = 0.15  # rim height = 15 % of cavity depth

        for k in range(n):
            cy, cx = divmod(int(indices[k]), w)
            rx = float(rxs[k])
            ry = float(rys[k])
            # Anisotropic Gaussian pit (rx ≠ ry → elliptical void)
            sigma_x_sq = max(rx ** 2, 1e-9)
            sigma_y_sq = max(ry ** 2, 1e-9)
            dist_sq_aniso = (ys - cy) ** 2 / sigma_y_sq + (xs - cx) ** 2 / sigma_x_sq
            cavity = np.exp(-0.5 * dist_sq_aniso)

            effective_depth = depth_scale * intensity * float(depth_mults[k])
            result[:] -= cavity * effective_depth

            if add_rim:
                # Contamination ring: raised annulus at Gaussian tail
                sigma_mean = (rx + ry) * 0.5
                rim_inner_sq = (rim_inner_scale * sigma_mean) ** 2
                rim_outer_sq = (rim_outer_scale * sigma_mean) ** 2
                dist_from_centre = (ys - cy) ** 2 + (xs - cx) ** 2
                rim_mask = (
                    (dist_from_centre >= rim_inner_sq)
                    & (dist_from_centre <= rim_outer_sq)
                ).astype(np.float64)
                # Smooth ring with a Gaussian cross-section
                ring_sigma_sq = max(((rim_outer_scale - rim_inner_scale) * sigma_mean * 0.5) ** 2, 1e-9)
                ring_centre_r_sq = ((rim_inner_scale + rim_outer_scale) * 0.5 * sigma_mean) ** 2
                ring_profile = np.exp(
                    -(dist_from_centre - ring_centre_r_sq) ** 2 / (2.0 * ring_sigma_sq * ring_centre_r_sq)
                )
                result[:] += rim_mask * ring_profile * effective_depth * rim_fraction

            placed_cy.append(cy)
            placed_cx.append(cx)

    def _contagion_prob(base: np.ndarray) -> np.ndarray:
        """Blend base prob with Gaussian attraction map from placed cavities."""
        if not placed_cy:
            return base
        n_placed = len(placed_cy)
        cy_arr = np.array(placed_cy, dtype=np.float64)
        cx_arr = np.array(placed_cx, dtype=np.float64)
        # Vectorised: (n_placed, h*w) distance matrix — feasible for n_placed ≤ ~500
        dy = _all_ys[np.newaxis, :] - cy_arr[:, np.newaxis]
        dx = _all_xs[np.newaxis, :] - cx_arr[:, np.newaxis]
        d2 = dy ** 2 + dx ** 2
        attraction = np.exp(-d2 / (2.0 * _sigma_c_sq)).sum(axis=0)  # (h*w,)
        att_flat = attraction * steep_gate.ravel()
        att_sum = float(att_flat.sum())
        if att_sum > 1e-12:
            att_flat /= att_sum
        blended = 0.5 * base + 0.5 * att_flat
        b_sum = float(blended.sum())
        return blended / b_sum if b_sum > 1e-12 else base

    # ---- Initial macro-cavity placement (with contamination rims) --------
    _place_cavities(
        effective_cavities, (2.5, 5.0), (2.5, 5.0),
        cavity_scale, base_prob, add_rim=True,
    )

    # ---- Contagion spread passes -----------------------------------------
    cavities_per_pass = max(1, effective_cavities // 2)
    for _ in range(contagion_passes):
        spread_prob = _contagion_prob(base_prob)
        _place_cavities(
            cavities_per_pass, (1.5, 4.0), (1.5, 4.0),
            cavity_scale * 0.7, spread_prob, add_rim=True,
        )

    # ---- Micro cavity pass (honeycomb texture density) -------------------
    # Micro-pits are too small for rims but inherit the contagion bias.
    micro_prob = _contagion_prob(base_prob)
    _place_cavities(
        effective_cavities * 2, (0.8, 2.2), (0.8, 2.2),
        cavity_scale * 0.35, micro_prob, add_rim=False,
    )

    # ---- Interconnected wall thinning (AAA fix) --------------------------
    # Real tafoni honeycombs have SHARED walls between adjacent cavities —
    # the wall between two pits is thinner than the surrounding rock because
    # moisture concentrates there from both sides.  Simulate by building a
    # proximity map of all placed cavity centres and carving a shallow
    # connecting groove between pairs closer than 2× the mean cavity radius.
    # This creates the "cavernous face" topology that distinguishes tafoni
    # from isolated random pits.
    if len(placed_cy) >= 2:
        cy_arr_f = np.array(placed_cy, dtype=np.float64)
        cx_arr_f = np.array(placed_cx, dtype=np.float64)
        n_placed = len(cy_arr_f)
        # Mean cavity radius from macro pass defaults (~3.75 cells)
        mean_r = 3.75
        connect_thresh = mean_r * 3.0   # max centre-to-centre for wall thinning
        groove_depth = cavity_scale * 0.18 * intensity

        # For each pair (i < j) within threshold, carve a linear groove
        # along the inter-cavity axis using a thin Gaussian cross-section.
        # Cap at 200 pairs to avoid O(N²) blow-up on dense tafoni fields.
        pair_count = 0
        for i in range(min(n_placed, 40)):
            for j in range(i + 1, min(n_placed, 40)):
                dy_pair = cy_arr_f[j] - cy_arr_f[i]
                dx_pair = cx_arr_f[j] - cx_arr_f[i]
                dist_pair = math.sqrt(dy_pair ** 2 + dx_pair ** 2)
                if dist_pair < 1e-3 or dist_pair > connect_thresh:
                    continue
                # Direction along the inter-cavity axis
                ax = dx_pair / dist_pair
                ay = dy_pair / dist_pair
                # Perpendicular axis for groove width
                px_ax = -ay
                py_ax = ax
                # Midpoint groove parameters
                mid_y = 0.5 * (cy_arr_f[i] + cy_arr_f[j])
                mid_x = 0.5 * (cx_arr_f[i] + cx_arr_f[j])
                # Project all grid cells onto the along-axis and perp-axis
                rel_ys = _all_ys - mid_y
                rel_xs = _all_xs - mid_x
                along = rel_ys * ay + rel_xs * ax
                perp  = rel_ys * py_ax + rel_xs * px_ax
                # Groove extends ±half the inter-cavity distance, width ~ mean_r*0.4
                groove_half = dist_pair * 0.45
                groove_w_sq = max((mean_r * 0.4) ** 2, 1.0)
                along_gate = (np.abs(along) <= groove_half).astype(np.float64)
                groove_profile = np.exp(-perp ** 2 / (2.0 * groove_w_sq)) * along_gate
                result.ravel()[:] -= groove_profile * groove_depth
                pair_count += 1
                if pair_count >= 200:
                    break
            if pair_count >= 200:
                break

    return result


def apply_geological_folds(
    heightmap: np.ndarray,
    seed: int = 0,
    num_folds: int = 3,
    amplitude: float = 0.05,
    wavelength_cells: float = 30.0,
    fold_type: str = "syncline",
) -> np.ndarray:
    """Apply geological fold deformation (anticline/syncline) to terrain.

    Simulates tectonic folding with physically correct periclinal geometry:
    - "anticline": upward arch (rock bends up), convex toward viewer
    - "syncline": downward trough (rock bends down), concave toward viewer
    - "chevron": angular V-shaped folds

    AAA geometry — three physically motivated upgrades over a simple sine:

    1. **Plunging hinge axis** (3–15° plunge angle, per Davis & Reynolds 1996):
       The fold axis trends downward at a small angle along the strike direction.
       This is modelled by adding a plunge-phase shift to the cross-strike
       projection: as you move a distance ``s`` along strike, the wave phase
       shifts by ``s * tan(plunge_angle) / wavelength * 2π``.  The result is
       a periclinal nose where the fold axis terminates at depth rather than
       extending infinitely as a horizontal line — matching doubly-plunging
       anticlines visible in Witcher 3 mountain ranges.

    2. **Gaussian amplitude envelope along strike** (periclinal shape):
       Amplitude is multiplied by ``exp(-proj_strike² / 2σ²)`` so each fold
       has a maximum-amplitude hinge and tapers to zero at both ends.
       ``sigma = 1.5 * wavelength`` gives a realistic periclinal extent
       (~3 wavelengths full-width at half-maximum).

    3. **Cumulative strain scaling** (Ramsay 1967):
       Each fold's effective amplitude scales with a strain factor derived from
       the local curvature already accumulated in ``result`` at the fold's
       hinge location.  High pre-existing curvature (many overlapping folds)
       reduces the marginal amplitude of the new fold — reflecting how rocks
       reach a mechanical limit under repeated folding.  The strain factor is
       clamped to [0.3, 1.0] so even highly deformed areas retain some relief.

    Args:
        heightmap: (H, W) float64 terrain heights.
        seed: Deterministic RNG seed.
        num_folds: Number of fold axes.
        amplitude: Peak fold displacement at fold hinge (metres, relative).
        wavelength_cells: Wavelength of fold in grid cells.
        fold_type: "anticline", "syncline", or "chevron".

    Returns:
        Modified (H, W) heightmap with fold deformation.
    """
    h, w = heightmap.shape
    result = heightmap.copy()
    rng = _rng_from_seed(seed, "biome_geological_folds")

    ys = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xs = np.arange(w, dtype=np.float64).reshape(1, -1)

    sign = -1.0 if fold_type == "syncline" else 1.0

    for _ in range(num_folds):
        # Random strike direction (perpendicular to dip direction)
        angle = rng.uniform(0, math.pi)
        # dip vector (perpendicular to strike, pointing down-dip)
        dip_x = math.cos(angle)
        dip_y = math.sin(angle)
        # strike vector (along the fold axis)
        strike_x = -dip_y
        strike_y = dip_x

        # Centre of this fold's hinge along strike
        cx = rng.uniform(0.1 * w, 0.9 * w)
        cy = rng.uniform(0.1 * h, 0.9 * h)

        # Project coordinates onto the dip direction (cross-strike distance)
        # — this drives the sinusoidal wave profile.
        proj_dip = (xs - cx) * (-dip_y) + (ys - cy) * dip_x

        # Project onto the strike direction (along-axis distance from hinge)
        # — this drives the plunge-amplitude envelope.
        proj_strike = (xs - cx) * strike_x + (ys - cy) * strike_y

        # Phase offset (random starting phase so folds don't all peak at hinge)
        phase = rng.uniform(0, 2 * math.pi)

        # -----------------------------------------------------------------
        # Plunge angle: the hinge axis dips at plunge_deg below horizontal
        # (Davis & Reynolds 1996 — typical range 3–15°).
        # The phase of the cross-strike wave shifts by
        #   Δφ = 2π * s * tan(plunge_angle) / wavelength
        # as you move distance s along the strike direction.
        # This causes the fold crest to trace a plunging line, producing
        # the characteristic periclinal closure / nose geometry.
        # -----------------------------------------------------------------
        plunge_deg = rng.uniform(3.0, 15.0)
        plunge_rad = math.radians(plunge_deg)
        plunge_phase_shift = (
            2.0 * math.pi * proj_strike * math.tan(plunge_rad) / max(wavelength_cells, 1.0)
        )

        # Effective cross-strike coordinate after plunge correction
        proj_dip_plunged = proj_dip + plunge_phase_shift * (wavelength_cells / (2.0 * math.pi))

        if fold_type == "chevron":
            # Triangular wave for angular folds
            t = (proj_dip_plunged / wavelength_cells + phase / (2 * math.pi)) % 1.0
            wave = 2.0 * np.abs(2.0 * (t - np.floor(t + 0.5))) - 1.0
        else:
            wave = np.sin(2.0 * math.pi * proj_dip_plunged / wavelength_cells + phase)

        # -----------------------------------------------------------------
        # Plunge-amplitude Gaussian envelope along strike
        # sigma = 1.5 * wavelength → periclinal shape, fold terminates at
        # both ends along the axis (doubly-plunging geometry).
        # -----------------------------------------------------------------
        plunge_sigma = wavelength_cells * 1.5
        plunge_envelope = np.exp(
            -(proj_strike ** 2) / (2.0 * max(plunge_sigma ** 2, 1e-9))
        )

        # -----------------------------------------------------------------
        # Cumulative strain scaling (Ramsay 1967)
        # Measure local curvature in the current result at the hinge location.
        # The Laplacian (∇²h) proxies differential strain — high values mean
        # the terrain is already highly deformed by previous folds.
        # Strain factor = 1 / (1 + k * |curvature_at_hinge|) where k is a
        # sensitivity constant tuned so that 2× the wave amplitude at the
        # hinge reduces subsequent fold contribution by ~40%.
        # Clamped to [0.3, 1.0] to prevent complete suppression.
        # -----------------------------------------------------------------
        h_idx = int(np.clip(round(float(cy)), 0, h - 1))
        w_idx = int(np.clip(round(float(cx)), 0, w - 1))
        # 3-point Laplacian at hinge location (finite difference)
        _lap = 0.0
        if 1 <= h_idx <= h - 2 and 1 <= w_idx <= w - 2:
            _lap = float(
                result[h_idx - 1, w_idx]
                + result[h_idx + 1, w_idx]
                + result[h_idx, w_idx - 1]
                + result[h_idx, w_idx + 1]
                - 4.0 * result[h_idx, w_idx]
            )
        _curvature_mag = abs(_lap)
        # k chosen so that curvature = 2*amplitude halves the strain factor
        _k_strain = 1.0 / max(2.0 * amplitude, 1e-9)
        strain_factor = float(np.clip(1.0 / (1.0 + _k_strain * _curvature_mag), 0.3, 1.0))

        result += wave * amplitude * sign * plunge_envelope * strain_factor

    return result


# ---------------------------------------------------------------------------
# FIX-B14-4: Biome surface-feature dispatch
#
# Previous code used generic dark-fantasy substring matching which missed 6/14
# canonical VeilBreakers biome IDs.  This replaces it with an explicit lookup
# dict keyed on BIOME_CLIMATE_PARAMS keys (the sole canonical source of truth).
# ---------------------------------------------------------------------------

def _apply_forest_debris(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.6,
) -> np.ndarray:
    """Scatter fallen-log divots and twig mounds across forest floor.

    Returns delta array (H, W) float64 — non-zero on all non-trivial inputs.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_forest_debris")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.005 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    radii = rng.integers(2, max(3, h // 16), n)
    depths = rng.uniform(0.002, 0.012 * intensity, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / max(radii[i] ** 2, 1.0))
        result += mask * depths[i]
    return result


def _apply_root_network(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
) -> np.ndarray:
    """Raise sinuous root ridges along random radial paths.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_root_network")
    result = np.zeros((h, w), dtype=np.float64)
    n_roots = max(1, int(4 * max(intensity, 0.01)))
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for _ in range(n_roots):
        cy = rng.uniform(0.1 * h, 0.9 * h)
        cx = rng.uniform(0.1 * w, 0.9 * w)
        angle = rng.uniform(0, 2 * math.pi)
        length = rng.uniform(0.15, 0.4) * min(h, w)
        width_sq = max((min(h, w) * 0.02) ** 2, 1.0)
        # Project distance along the root axis
        dx = math.cos(angle)
        dy = math.sin(angle)
        # Along-axis (t) and cross-axis (u) distances
        t = (xx - cx) * dx + (yy - cy) * dy
        u = (xx - cx) * (-dy) + (yy - cy) * dx
        # Gaussian bump confined to the root length and width
        t_mask = np.exp(-((t - length / 2) ** 2) / max((length / 2) ** 2, 1.0))
        u_mask = np.exp(-(u ** 2) / width_sq)
        result += t_mask * u_mask * 0.008 * intensity
    return result


def _apply_swamp_muck(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.7,
) -> np.ndarray:
    """Depress low-lying areas into stagnant muck pools.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_swamp_muck")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.003 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max((rng.integers(3, max(4, h // 12))) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result -= mask * rng.uniform(0.005, 0.015) * intensity
    return result


def _apply_toxic_tendrils(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.6,
) -> np.ndarray:
    """Add raised toxic-slime ridges typical of corrupted swamp edges.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_toxic_tendrils")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(3 * max(intensity, 0.01)))
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for _ in range(n):
        cy = rng.uniform(0.2 * h, 0.8 * h)
        cx = rng.uniform(0.2 * w, 0.8 * w)
        angle = rng.uniform(0, 2 * math.pi)
        length = rng.uniform(0.1, 0.3) * min(h, w)
        width_sq = max((min(h, w) * 0.015) ** 2, 1.0)
        dx = math.cos(angle)
        dy = math.sin(angle)
        t = (xx - cx) * dx + (yy - cy) * dy
        u = (xx - cx) * (-dy) + (yy - cy) * dx
        t_mask = np.exp(-((t - length / 2) ** 2) / max((length / 2) ** 2, 1.0))
        u_mask = np.exp(-(u ** 2) / width_sq)
        result += t_mask * u_mask * 0.006 * intensity
    return result


def _apply_scree_fields(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.6,
) -> np.ndarray:
    """Place loose-stone scree clusters on mountain terrain.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_scree_fields")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.004 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(1, max(2, h // 20)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result += mask * rng.uniform(0.003, 0.010) * intensity
    return result


def _apply_frost_crack_network(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
) -> np.ndarray:
    """Carve shallow frost-crack patterns on cold rocky terrain.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_frost_crack")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(6 * max(intensity, 0.01)))
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for _ in range(n):
        cy = rng.uniform(0, h)
        cx = rng.uniform(0, w)
        angle = rng.uniform(0, math.pi)
        length = rng.uniform(0.05, 0.25) * min(h, w)
        width_sq = max(1.5 ** 2, 1.0)
        dx = math.cos(angle)
        dy = math.sin(angle)
        t = (xx - cx) * dx + (yy - cy) * dy
        u = (xx - cx) * (-dy) + (yy - cy) * dx
        t_mask = np.clip(1.0 - np.abs(t - length / 2) / max(length / 2, 1.0), 0.0, 1.0)
        u_mask = np.exp(-(u ** 2) / width_sq)
        result -= t_mask * u_mask * 0.004 * intensity
    return result


def _apply_sand_ripples(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.7,
) -> np.ndarray:
    """Add aeolian sand-ripple micro-relief to desert terrain.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_sand_ripples")
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    angle = rng.uniform(0, math.pi)
    wavelength = max(min(h, w) / 8.0, 4.0)
    proj = xx * math.cos(angle) + np.arange(h, dtype=np.float64).reshape(-1, 1) * math.sin(angle)
    ripple = np.sin(2.0 * math.pi * proj / wavelength)
    phase2 = rng.uniform(0, 2 * math.pi)
    ripple2 = np.sin(2.0 * math.pi * proj / (wavelength * 0.6) + phase2)
    return (ripple * 0.006 + ripple2 * 0.003) * intensity


def _apply_grass_tufts(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.6,
) -> np.ndarray:
    """Raise small grass-tuft mounds across open grassland.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_grass_tufts")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.006 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(1, max(2, h // 24)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result += mask * rng.uniform(0.002, 0.007) * intensity
    return result


def _apply_wildflower_scatter(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
) -> np.ndarray:
    """Add micro-undulation from wildflower root masses in grassland.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_wildflower_scatter")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.003 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(1, max(2, h // 30)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result += mask * 0.003 * intensity
    return result


def _apply_tide_pool_pocking(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.6,
) -> np.ndarray:
    """Depress shallow tide-pool basins along coastal terrain.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_tide_pools")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.003 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(2, max(3, h // 16)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result -= mask * rng.uniform(0.004, 0.012) * intensity
    return result


def _apply_beach_strand_lines(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
) -> np.ndarray:
    """Add low parallel strand-line ridges left by receding tides.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_strand_lines")
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    n_lines = max(1, int(3 * max(intensity, 0.01)))
    result = np.zeros((h, w), dtype=np.float64)
    for _ in range(n_lines):
        y_centre = rng.uniform(0.1 * h, 0.9 * h)
        sigma_sq = max((h * 0.03) ** 2, 1.0)
        ridge = np.exp(-((yy - y_centre) ** 2) / sigma_sq)
        result += ridge * 0.004 * intensity
    return result


def _apply_grave_markers(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.7,
) -> np.ndarray:
    """Raise burial-mound hillocks representing grave markers.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_grave_markers")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.003 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(2, max(3, h // 18)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result += mask * rng.uniform(0.005, 0.015) * intensity
    return result


def _apply_bone_fragments(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
) -> np.ndarray:
    """Scatter micro-protrusions representing surface bone fragments.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_bone_fragments")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.004 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(1.5 ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result += mask * 0.004 * intensity
    return result


def _apply_battlefield_craters(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.8,
) -> np.ndarray:
    """Depress shallow impact craters across battlefield terrain.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_battlefield_craters")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.004 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(3, max(4, h // 10)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        bowl = np.exp(-d2 / r2)
        # Rim is a thin raised ring just outside the bowl
        rim = np.exp(-((np.sqrt(d2) - math.sqrt(r2)) ** 2) / max(r2 * 0.05, 1.0))
        result -= bowl * rng.uniform(0.008, 0.018) * intensity
        result += rim * 0.006 * intensity
    return result


def _apply_weapon_debris(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
) -> np.ndarray:
    """Scatter small protrusions representing embedded weapons and armour shards.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_weapon_debris")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.003 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(1.2 ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result += mask * 0.003 * intensity
    return result


def _apply_fortress_rubble(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.7,
) -> np.ndarray:
    """Scatter collapsed-wall rubble mounds across ruined fortress terrain.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_fortress_rubble")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.004 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(2, max(3, h // 12)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result += mask * rng.uniform(0.006, 0.016) * intensity
    return result


def _apply_cracked_stone_paving(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
) -> np.ndarray:
    """Add cracked-flagstone relief to ruined fortress courtyards.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_cracked_paving")
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    # Sinusoidal grid at a rotated angle
    angle = rng.uniform(0, math.pi / 4)
    cell = max(min(h, w) // 8, 4)
    proj_a = yy * math.cos(angle) + xx * math.sin(angle)
    proj_b = -yy * math.sin(angle) + xx * math.cos(angle)
    grid = (
        np.sin(2.0 * math.pi * proj_a / cell) * 0.003
        + np.sin(2.0 * math.pi * proj_b / cell) * 0.003
    )
    return grid * intensity


def _apply_crumbling_wall_stumps(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.6,
) -> np.ndarray:
    """Raise linear wall-stump ridges typical of abandoned village foundations.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_wall_stumps")
    result = np.zeros((h, w), dtype=np.float64)
    n_walls = max(1, int(2 * max(intensity, 0.01)))
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for _ in range(n_walls):
        cy = rng.uniform(0.2 * h, 0.8 * h)
        cx = rng.uniform(0.2 * w, 0.8 * w)
        angle = rng.choice([0.0, math.pi / 2])  # axis-aligned walls
        length = rng.uniform(0.1, 0.3) * min(h, w)
        width_sq = max((min(h, w) * 0.015) ** 2, 1.0)
        dx = math.cos(angle)
        dy = math.sin(angle)
        t = (xx - cx) * dx + (yy - cy) * dy
        u = (xx - cx) * (-dy) + (yy - cy) * dx
        t_mask = np.clip(1.0 - np.abs(t - length / 2) / max(length / 2, 1.0), 0.0, 1.0)
        u_mask = np.exp(-(u ** 2) / width_sq)
        result += t_mask * u_mask * 0.010 * intensity
    return result


def _apply_overgrown_paths(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.5,
) -> np.ndarray:
    """Depress shallow path-ruts typical of abandoned village trackways.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_overgrown_paths")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(2 * max(intensity, 0.01)))
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for _ in range(n):
        angle = rng.uniform(0, math.pi)
        cy = rng.uniform(0.3 * h, 0.7 * h)
        cx = rng.uniform(0.3 * w, 0.7 * w)
        dx = math.cos(angle)
        dy = math.sin(angle)
        u = (xx - cx) * (-dy) + (yy - cy) * dx
        width_sq = max((min(h, w) * 0.025) ** 2, 1.0)
        track = np.exp(-(u ** 2) / width_sq)
        result -= track * 0.005 * intensity
    return result


def _apply_void_fissures(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.8,
) -> np.ndarray:
    """Carve deep reality-torn fissures in veil crack zones.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_void_fissures")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(3 * max(intensity, 0.01)))
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for _ in range(n):
        cy = rng.uniform(0.1 * h, 0.9 * h)
        cx = rng.uniform(0.1 * w, 0.9 * w)
        angle = rng.uniform(0, math.pi)
        length = rng.uniform(0.2, 0.5) * min(h, w)
        width_sq = max((min(h, w) * 0.008) ** 2, 1.0)
        dx = math.cos(angle)
        dy = math.sin(angle)
        t = (xx - cx) * dx + (yy - cy) * dy
        u = (xx - cx) * (-dy) + (yy - cy) * dx
        t_mask = np.clip(1.0 - np.abs(t - length / 2) / max(length / 2, 1.0), 0.0, 1.0)
        u_mask = np.exp(-(u ** 2) / width_sq)
        result -= t_mask * u_mask * 0.020 * intensity
    return result


def _apply_void_crystal_spires(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.7,
) -> np.ndarray:
    """Raise jagged void-crystal spire clusters in veil crack terrain.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_void_crystal_spires")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.002 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(1, max(2, h // 20)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        # Sharp spike profile: 1/(1+d2/r2) decays slower than Gaussian
        spike = 1.0 / (1.0 + d2 / r2)
        result += spike * rng.uniform(0.008, 0.020) * intensity
    return result


def _apply_mycelium_humps(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.7,
) -> np.ndarray:
    """Raise mycelium-mat mounds on mushroom forest floor.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_mycelium_humps")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.005 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(2, max(3, h // 14)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result += mask * rng.uniform(0.005, 0.014) * intensity
    return result


def _apply_spore_cap_clusters(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.6,
) -> np.ndarray:
    """Raise small cap-cluster bumps representing mushroom stands.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_spore_caps")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.003 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(1, max(2, h // 24)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result += mask * 0.007 * intensity
    return result


def _apply_crystal_formations(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.8,
) -> np.ndarray:
    """Raise prismatic crystal-cluster spires in crystal cavern terrain.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_crystal_formations")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.003 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(1, max(2, h // 18)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        spike = 1.0 / (1.0 + d2 / r2)
        result += spike * rng.uniform(0.010, 0.025) * intensity
    return result


def _apply_cave_drip_basins(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.6,
) -> np.ndarray:
    """Depress shallow stalactite-drip basins in crystal cavern terrain.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_cave_drip_basins")
    result = np.zeros((h, w), dtype=np.float64)
    n = max(1, int(h * w * 0.004 * max(intensity, 0.01)))
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for i in range(n):
        r2 = max(rng.integers(2, max(3, h // 16)) ** 2, 1.0)
        d2 = (yy - ys[i]) ** 2 + (xx - xs[i]) ** 2
        mask = np.exp(-d2 / r2)
        result -= mask * rng.uniform(0.005, 0.012) * intensity
    return result


def _apply_deep_forest_moss_carpet(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.6,
) -> np.ndarray:
    """Raise low undulating moss-carpet micro-relief on deep forest floor.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_deep_forest_moss")
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    freq_y = rng.uniform(0.04, 0.08)
    freq_x = rng.uniform(0.04, 0.08)
    phase_y = rng.uniform(0, 2 * math.pi)
    phase_x = rng.uniform(0, 2 * math.pi)
    carpet = (
        np.sin(freq_y * yy + phase_y) * 0.004
        + np.sin(freq_x * xx + phase_x) * 0.004
    )
    return carpet * intensity


def _apply_ancient_root_buttresses(
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.7,
) -> np.ndarray:
    """Raise massive root-buttress ridges around ancient deep-forest trees.

    Returns delta array (H, W) float64.
    """
    h, w = heightmap.shape
    rng = _rng_from_seed(seed, "biome_ancient_root_buttresses")
    result = np.zeros((h, w), dtype=np.float64)
    n_trees = max(1, int(2 * max(intensity, 0.01)))
    yy = np.arange(h, dtype=np.float64).reshape(-1, 1)
    xx = np.arange(w, dtype=np.float64).reshape(1, -1)
    for _ in range(n_trees):
        cy = rng.uniform(0.2 * h, 0.8 * h)
        cx = rng.uniform(0.2 * w, 0.8 * w)
        n_buttresses = rng.integers(4, 8)
        for b in range(n_buttresses):
            angle = 2 * math.pi * b / n_buttresses + rng.uniform(-0.2, 0.2)
            length = rng.uniform(0.05, 0.12) * min(h, w)
            width_sq = max((min(h, w) * 0.012) ** 2, 1.0)
            dx = math.cos(angle)
            dy = math.sin(angle)
            t = (xx - cx) * dx + (yy - cy) * dy
            u = (xx - cx) * (-dy) + (yy - cy) * dx
            t_mask = np.clip(t / max(length, 1.0), 0.0, 1.0)
            t_mask = t_mask * (1.0 - t_mask)  # quadratic taper
            u_mask = np.exp(-(u ** 2) / width_sq)
            result += t_mask * u_mask * 0.012 * intensity
    return result


# ---------------------------------------------------------------------------
# Feature function registry — maps internal key to callable
# ---------------------------------------------------------------------------

_FEATURE_FN_REGISTRY: dict[str, object] = {
    "forest_debris":           _apply_forest_debris,
    "root_network":            _apply_root_network,
    "swamp_muck":              _apply_swamp_muck,
    "toxic_tendrils":          _apply_toxic_tendrils,
    "scree_fields":            _apply_scree_fields,
    "frost_crack_network":     _apply_frost_crack_network,
    "periglacial_patterns":    apply_periglacial_patterns,
    "desert_pavement":         apply_desert_pavement,
    "sand_ripples":            _apply_sand_ripples,
    "grass_tufts":             _apply_grass_tufts,
    "wildflower_scatter":      _apply_wildflower_scatter,
    "tide_pool_pocking":       _apply_tide_pool_pocking,
    "beach_strand_lines":      _apply_beach_strand_lines,
    "grave_markers":           _apply_grave_markers,
    "bone_fragments":          _apply_bone_fragments,
    "battlefield_craters":     _apply_battlefield_craters,
    "weapon_debris":           _apply_weapon_debris,
    "fortress_rubble":         _apply_fortress_rubble,
    "cracked_stone_paving":    _apply_cracked_stone_paving,
    "crumbling_wall_stumps":   _apply_crumbling_wall_stumps,
    "overgrown_paths":         _apply_overgrown_paths,
    "void_fissures":           _apply_void_fissures,
    "void_crystal_spires":     _apply_void_crystal_spires,
    "mycelium_humps":          _apply_mycelium_humps,
    "spore_cap_clusters":      _apply_spore_cap_clusters,
    "crystal_formations":      _apply_crystal_formations,
    "cave_drip_basins":        _apply_cave_drip_basins,
    "deep_forest_moss_carpet": _apply_deep_forest_moss_carpet,
    "ancient_root_buttresses": _apply_ancient_root_buttresses,
    "tafoni_weathering":       apply_tafoni_weathering,
}


# ---------------------------------------------------------------------------
# Canonical biome → feature-key dispatch table
# Keys are exactly the BIOME_CLIMATE_PARAMS keys — no substring matching.
# ---------------------------------------------------------------------------

_BIOME_FEATURES: dict[str, tuple[str, ...]] = {
    "thornwood_forest":  ("forest_debris", "root_network"),
    "corrupted_swamp":   ("swamp_muck", "toxic_tendrils"),
    "mountain_pass":     ("scree_fields", "frost_crack_network", "periglacial_patterns"),
    "desert":            ("desert_pavement", "sand_ripples"),
    "grasslands":        ("grass_tufts", "wildflower_scatter"),
    "deep_forest":       ("deep_forest_moss_carpet", "ancient_root_buttresses", "forest_debris"),
    "coastal":           ("tide_pool_pocking", "beach_strand_lines"),
    "cemetery":          ("grave_markers", "bone_fragments"),
    "battlefield":       ("battlefield_craters", "weapon_debris"),
    "ruined_fortress":   ("fortress_rubble", "cracked_stone_paving", "tafoni_weathering"),
    "abandoned_village": ("crumbling_wall_stumps", "overgrown_paths"),
    "veil_crack_zone":   ("void_fissures", "void_crystal_spires"),
    "mushroom_forest":   ("mycelium_humps", "spore_cap_clusters"),
    "crystal_cavern":    ("crystal_formations", "cave_drip_basins"),
    "blighted_mire":     ("swamp_muck", "toxic_tendrils", "bone_fragments"),
    "ashen_wastes":      ("desert_pavement", "sand_ripples", "tafoni_weathering"),
    "frozen_hollows":    ("frost_crack_network", "periglacial_patterns", "cave_drip_basins"),
    "ruined_citadel":    ("fortress_rubble", "cracked_stone_paving", "overgrown_paths"),
}


def _dispatch_biome_surface_features(
    biome_id: str,
    heightmap: np.ndarray,
    seed: int = 0,
    intensity: float = 0.6,
) -> list[np.ndarray]:
    """Return a list of delta arrays for all surface features of *biome_id*.

    Each element is a (H, W) float64 delta produced by one registered feature
    function.  The list is empty only when *biome_id* is unknown.

    Some registered functions (``apply_desert_pavement``, ``apply_hot_spring_features``)
    return tuples rather than bare arrays; this wrapper unpacks those to extract
    the first element (the delta/heightmap).

    Args:
        biome_id: Canonical VeilBreakers biome identifier.
        heightmap: (H, W) float64 baseline terrain heights.
        seed: Deterministic RNG seed forwarded to each feature function.
        intensity: Feature strength [0, 1].

    Returns:
        List of (H, W) float64 delta arrays, one per feature.
    """
    feature_keys = _BIOME_FEATURES.get(biome_id, ())
    results: list[np.ndarray] = []
    for key in feature_keys:
        fn = _FEATURE_FN_REGISTRY.get(key)
        if fn is None:  # defensive: unknown key
            continue
        raw = fn(heightmap, seed=seed, intensity=intensity)  # type: ignore[call-arg]
        if isinstance(raw, tuple):
            # apply_desert_pavement returns (heightmap, mask); hot_spring returns
            # (heightmap, list).  We take only the first element (the array).
            raw = raw[0]
        # Convert to delta by subtracting the original
        delta = np.asarray(raw, dtype=np.float64) - heightmap
        results.append(delta)
    return results


def pass_biome_surface_features(
    state: object,
    region: object,
) -> object:
    """Apply per-biome micro-feature surface passes to the active heightmap.

    Dispatches using the explicit ``_BIOME_FEATURES`` lookup dict which covers
    all 14 canonical VeilBreakers biome IDs.  The previous substring-match
    approach missed cemetery, ashen_wastes (now ruined_fortress), blighted_mire
    (now corrupted_swamp), ruined_citadel (now ruined_fortress), crystal_cavern,
    and grasslands.

    Contract:
        Requires: height, biome_id (optional — falls back to composition_hints)
        Produces: biome_surface_feature_delta

    Args:
        state: TerrainPipelineState (typed as object to avoid circular import).
        region: Optional BBox (typed as object to avoid circular import).

    Returns:
        PassResult with pass_name="biome_surface_features".
    """
    import time

    from .terrain_semantics import PassResult

    t0 = time.perf_counter()

    stack = state.mask_stack  # type: ignore[attr-defined]
    height = np.asarray(stack.height, dtype=np.float64)
    seed = int(getattr(getattr(state, "intent", None) or object(), "seed", 0))

    # Determine active biome name from composition_hints or biome_id channel.
    biome_name: str = ""
    intent = getattr(state, "intent", None)
    if intent is not None:
        hints = dict(getattr(intent, "composition_hints", {}) or {})
        biome_name = str(hints.get("biome", "") or "")

    if not biome_name:
        # Fall back to dominant biome from biome_id channel if present
        biome_id_channel = stack.get("biome_id")
        if biome_id_channel is not None:
            biome_index = int(np.bincount(np.asarray(biome_id_channel).ravel().astype(np.int32)).argmax())
            # Map index to biome name using the pipeline's biome list
            biome_list = list(BIOME_CLIMATE_PARAMS.keys())
            if 0 <= biome_index < len(biome_list):
                biome_name = biome_list[biome_index]

    intensity = float(
        dict(getattr(intent, "composition_hints", {}) or {}).get("surface_feature_intensity", 0.6)
        if intent is not None else 0.6
    )

    deltas = _dispatch_biome_surface_features(
        biome_id=biome_name,
        heightmap=height,
        seed=seed,
        intensity=max(intensity, 0.01),
    )

    # Aggregate all feature deltas into a single combined delta channel.
    if deltas:
        combined_delta = sum(deltas)
    else:
        combined_delta = np.zeros_like(height)

    stack.set("biome_surface_feature_delta", combined_delta.astype(np.float32), "biome_surface_features")

    return PassResult(
        pass_name="biome_surface_features",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("biome_surface_feature_delta",),
        metrics={
            "biome": biome_name or "<unknown>",
            "feature_count": len(deltas),
            "delta_mean": float(combined_delta.mean()),
            "delta_max_abs": float(np.abs(combined_delta).max()),
        },
        issues=[],
    )


def register_biome_surface_features_pass() -> None:
    """Register the biome_surface_features pass on TerrainPassController."""
    from .terrain_pipeline import TerrainPassController
    from .terrain_semantics import PassDefinition

    TerrainPassController.register_pass(
        PassDefinition(
            name="biome_surface_features",
            func=pass_biome_surface_features,
            requires_channels=("height",),
            produces_channels=("biome_surface_feature_delta",),
            seed_namespace="biome_surface_features",
            requires_scene_read=False,
            may_modify_geometry=True,
            respects_protected_zones=True,
            protocol_enforced=True,
            description=(
                "Apply biome-specific surface micro-features using explicit VB biome "
                "registry (cemetery, ashen_wastes, blighted_mire, crystal_cavern, etc.)."
            ),
        )
    )


__all__ = [
    "WorldMapSpec",
    "generate_world_map_spec",
    "resolve_biome_name",
    "BIOME_CLIMATE_PARAMS",
    "BIOME_ALIASES",
    "apply_periglacial_patterns",
    "apply_desert_pavement",
    "compute_spring_line_mask",
    "apply_landslide_scars",
    "apply_hot_spring_features",
    "apply_reef_platform",
    "apply_tafoni_weathering",
    "apply_geological_folds",
    "pass_biome_surface_features",
    "register_biome_surface_features_pass",
]
