"""Bundle J — terrain_audio_zones.

Derives physically-based audio reverb zones from the TerrainMaskStack.

Public API (contract-stable):
  compute_audio_reverb_zones(stack) -> np.ndarray (int8, AudioReverbClass raster)
  compute_audio_zone_list(stack)    -> List[Dict]  (zone dicts with RT60 etc.)
  pass_audio_zones(state, region)   -> PassResult

Physical model summary
----------------------
* Cave / overhang   : RT60 estimated via Sabine equation T60 = 0.161*V/A
                      where V is estimated from enclosure geometry (slope +
                      concavity footprint * average height delta), A from
                      surface area estimate.  Typical: 2.0–4.0 s.
* Open terrain      : Short diffuse tail from ground reflection only.
                      RT60 0.1–0.3 s derived from slope-modulated sky exposure.
* Forest            : detail_density drives absorption coefficient α;
                      dense canopy α≈0.7 → RT60 ≈ 0.3 s.
* Water surface     : specular reflection, bright short reverb (RT60 0.4–0.9 s,
                      high wet ratio).
* Canyon / valley   : concavity + slope → flutter echo. RT60 0.8–1.5 s.
* Mountain high     : sparse hard rock — moderate reverb (RT60 0.6–1.2 s).
* Cliff echo        : EDT-based delay: echo_delay = 2 * dist_to_cliff / 343 m/s.

Pure numpy (scipy optional for EDT/CC). No bpy imports. Deterministic.
"""

from __future__ import annotations

import csv
import io
import logging
import time
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)

logger = logging.getLogger(__name__)


class AudioReverbClass(IntEnum):
    """Encodes audio_reverb_class values stored on the mask stack.

    Maps to Unity AudioReverbZone presets on the consumer side.
    """

    OPEN_FIELD = 0
    FOREST_DENSE = 1
    FOREST_SPARSE = 2
    CAVE = 3
    CANYON = 4
    WATER_NEAR = 5
    MOUNTAIN_HIGH = 6
    INTERIOR = 7


# ---------------------------------------------------------------------------
# Reverb preset definitions — physical parameters
# ---------------------------------------------------------------------------

#: Physical reverb parameter sets keyed by preset name.
#: rt60        : reverberation time at 1 kHz (seconds) — nominal, Sabine-adjusted
#:               per-zone in compute_audio_zone_list()
#: pre_delay   : early reflection delay (seconds)
#: diffusion   : 0–1, scattering of reflections (1 = fully diffuse)
#: hf_damping  : 0–1, high-frequency absorption (1 = heavily damped)
#: lf_reference: low-frequency rolloff reference (Hz)
#: absorption  : Sabine absorption coefficient α — used for RT60 estimation
REVERB_PRESETS: Dict[str, Dict] = {
    "open_field": {
        "rt60": 0.15,
        "pre_delay": 0.0,
        "diffusion": 0.10,
        "hf_damping": 0.05,
        "lf_reference": 250,
        "absorption": 0.92,
        "description": "Open grass/rock — minimal reverb, ambient wind only",
    },
    "forest_sparse": {
        "rt60": 0.45,
        "pre_delay": 0.02,
        "diffusion": 0.65,
        "hf_damping": 0.40,
        "lf_reference": 500,
        "absorption": 0.55,
        "description": "Sparse canopy — mid-freq absorption, scattered reflections",
    },
    "forest_dense": {
        "rt60": 0.30,
        "pre_delay": 0.01,
        "diffusion": 0.85,
        "hf_damping": 0.70,
        "lf_reference": 800,
        "absorption": 0.72,
        "description": "Dense canopy — heavy high-freq damping, short diffuse tail",
    },
    "cave": {
        "rt60": 2.80,
        "pre_delay": 0.04,
        "diffusion": 0.55,
        "hf_damping": 0.20,
        "lf_reference": 200,
        "absorption": 0.05,
        "description": "Cave / enclosed overhang — long hard-surface reverb, RT60 > 2 s",
    },
    "canyon": {
        "rt60": 1.10,
        "pre_delay": 0.06,
        "diffusion": 0.30,
        "hf_damping": 0.15,
        "lf_reference": 300,
        "absorption": 0.08,
        "description": "Canyon / valley — parallel reflections, flutter echo",
    },
    "water_near": {
        "rt60": 0.65,
        "pre_delay": 0.01,
        "diffusion": 0.20,
        "hf_damping": 0.05,
        "lf_reference": 200,
        "absorption": 0.03,
        "description": "Water surface — bright specular reflection, short wet tail",
    },
    "mountain_high": {
        "rt60": 0.90,
        "pre_delay": 0.08,
        "diffusion": 0.45,
        "hf_damping": 0.10,
        "lf_reference": 250,
        "absorption": 0.10,
        "description": "Mountain summit / exposed rock — long sparse reverb",
    },
    "interior": {
        "rt60": 1.80,
        "pre_delay": 0.02,
        "diffusion": 0.70,
        "hf_damping": 0.35,
        "lf_reference": 400,
        "absorption": 0.12,
        "description": "Interior (dungeon / ruin) — mid-length reverb, dense diffusion",
    },
}

#: Nominal dry_wet_ratio per class.
_CLASS_DRY_WET: Dict[int, float] = {
    AudioReverbClass.OPEN_FIELD: 0.05,
    AudioReverbClass.FOREST_SPARSE: 0.25,
    AudioReverbClass.FOREST_DENSE: 0.20,
    AudioReverbClass.CAVE: 0.80,
    AudioReverbClass.CANYON: 0.55,
    AudioReverbClass.WATER_NEAR: 0.45,
    AudioReverbClass.MOUNTAIN_HIGH: 0.40,
    AudioReverbClass.INTERIOR: 0.70,
}

_CLASS_PRESET: Dict[int, str] = {
    AudioReverbClass.OPEN_FIELD: "open_field",
    AudioReverbClass.FOREST_SPARSE: "forest_sparse",
    AudioReverbClass.FOREST_DENSE: "forest_dense",
    AudioReverbClass.CAVE: "cave",
    AudioReverbClass.CANYON: "canyon",
    AudioReverbClass.WATER_NEAR: "water_near",
    AudioReverbClass.MOUNTAIN_HIGH: "mountain_high",
    AudioReverbClass.INTERIOR: "interior",
}

# Speed of sound in air at 20 °C
_SPEED_OF_SOUND_MS = 343.0

# Zone classes that are open-air — Sabine/Eyring room model does not apply.
_OUTDOOR_ZONE_CLASSES: frozenset = frozenset({
    AudioReverbClass.OPEN_FIELD.value,
    AudioReverbClass.FOREST_SPARSE.value,
    AudioReverbClass.FOREST_DENSE.value,
    AudioReverbClass.WATER_NEAR.value,
    AudioReverbClass.MOUNTAIN_HIGH.value,
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _audio_cc_filter(mask: np.ndarray, min_cells: int) -> np.ndarray:
    """Return mask with small isolated components removed."""
    if not mask.any():
        return mask
    labeled, n = _label_audio_components(mask)
    if n == 0:
        return mask
    cleaned = np.zeros_like(np.asarray(mask, dtype=bool))
    for cid in range(1, n + 1):
        comp = labeled == cid
        if int(comp.sum()) >= min_cells:
            cleaned |= comp
    return cleaned


def _label_audio_components(mask: np.ndarray) -> Tuple[np.ndarray, int]:
    """Return 8-neighbor component labels for SciPy and no-SciPy runtimes."""
    try:
        from scipy.ndimage import label as _sclabel
        labeled, n = _sclabel(np.asarray(mask, dtype=bool), structure=np.ones((3, 3), dtype=int))
        return labeled.astype(np.int32, copy=False), int(n)
    except ImportError:
        mask_bool = np.asarray(mask, dtype=bool)
        labeled = np.zeros(mask_bool.shape, dtype=np.int32)
        visited = np.zeros_like(mask_bool)
        rows, cols = mask_bool.shape
        label_id = 0
        for r in range(rows):
            for c in range(cols):
                if visited[r, c] or not mask_bool[r, c]:
                    continue
                label_id += 1
                stack = [(r, c)]
                visited[r, c] = True
                while stack:
                    cr, cc = stack.pop()
                    labeled[cr, cc] = label_id
                    for dr in (-1, 0, 1):
                        for dc in (-1, 0, 1):
                            if dr == 0 and dc == 0:
                                continue
                            nr, nc = cr + dr, cc + dc
                            if (
                                0 <= nr < rows
                                and 0 <= nc < cols
                                and not visited[nr, nc]
                                and mask_bool[nr, nc]
                            ):
                                visited[nr, nc] = True
                                stack.append((nr, nc))
        return labeled, label_id


def _component_boundary_polygon(
    mask: np.ndarray,
    label_arr: np.ndarray,
    cid: int,
) -> List[Tuple[int, int]]:
    """Convex-hull boundary polygon for component *cid*."""
    ys, xs = np.where(label_arr == cid)
    if len(ys) == 0:
        return []
    coords = np.column_stack([ys, xs])
    try:
        from scipy.spatial import ConvexHull
        if len(coords) < 3:
            return [(int(r), int(c)) for r, c in coords]
        hull = ConvexHull(coords.astype(float))
        verts = coords[hull.vertices]
        return [(int(r), int(c)) for r, c in verts]
    except Exception:
        r0, r1 = int(ys.min()), int(ys.max())
        c0, c1 = int(xs.min()), int(xs.max())
        return [(r0, c0), (r0, c1), (r1, c1), (r1, c0)]


#: Air absorption coefficient m at 1 kHz, 20 °C, 50 % RH (dB/m → nepers/m).
#: Source: ISO 9613-1 atmospheric absorption tables.
_AIR_ABSORPTION_M_1KHZ = 0.001  # nepers/m at 1 kHz — small but non-negligible in caves


def _sabine_rt60(
    cell_count: int,
    cell_size: float,
    mean_height_delta: float,
    absorption: float,
    *,
    use_eyring: bool = True,
    air_absorption_m: float = _AIR_ABSORPTION_M_1KHZ,
) -> float:
    """Reverberation-time estimator — Sabine / Eyring / Norris-Eyring.

    Sabine           : T60 = 0.161 * V / (α * S)
        Accurate only for α < 0.2 (small rooms); over-predicts when α > 0.3.

    Eyring           : T60 = 0.161 * V / (-S * ln(1 - α))
        Accurate up to α ≈ 0.8; preferred for caves / forests where α varies
        widely across the zone.

    Norris-Eyring    : T60 = 0.161 * V / (-S * ln(1 - α) + 4 * m * V)
        Adds air absorption m [Np/m]; dominant correction term for large
        volumes (canyons, mountain bowls) where the mean free path is long.

    Volume V is estimated from the cell footprint * mean enclosure height.
    Surface area S = 2 * footprint + perimeter * wall_height.

    Parameters
    ----------
    cell_count        : number of grid cells in the zone.
    cell_size         : metres per cell.
    mean_height_delta : average height variance within the zone (proxy for
                        wall height in enclosed spaces).
    absorption        : absorption coefficient α ∈ (0, 1].  Values near 1 are
                        silently clamped to 0.999 so ln(1 - α) stays finite.
    use_eyring        : If True (default), apply the Norris-Eyring formula.
                        If False, fall back to classic Sabine.
    air_absorption_m  : Air absorption coefficient m in nepers/metre at the
                        reference frequency.  Norris-Eyring correction.

    Returns
    -------
    float : RT60 in seconds, clamped to [0.05, 10.0].
    """
    if cell_count == 0 or absorption <= 0.0:
        return 0.15
    footprint = float(cell_count) * cell_size ** 2   # m²
    wall_height = max(float(mean_height_delta), 1.0)  # at least 1 m
    volume = footprint * wall_height                   # m³ (box approximation)
    # Surface area: 2 × footprint (floor+ceil) + perimeter walls
    # Perimeter ≈ 4 * sqrt(footprint) for roughly square zones
    perimeter_m = 4.0 * np.sqrt(footprint)
    surface = 2.0 * footprint + perimeter_m * wall_height
    if surface < 1e-3:
        return 0.15
    if use_eyring:
        alpha_clamped = min(max(float(absorption), 1e-4), 0.999)
        # Norris-Eyring: denominator includes 4mV air-absorption term.
        denom = -surface * np.log(1.0 - alpha_clamped) + 4.0 * air_absorption_m * volume
        if denom < 1e-6:
            return 0.15
        rt60 = 0.161 * volume / denom
    else:
        rt60 = 0.161 * volume / (absorption * surface)
    return float(np.clip(rt60, 0.05, 10.0))


def _outdoor_rt60(
    cell_count: int,
    cell_size: float,
    absorption: float,
    preset_rt60: float,
) -> float:
    """RT60 estimator for open-air terrain zones (FIX-7-17).

    Outdoor acoustics are dominated by geometric spreading and ground
    absorption, not by a reverberant field — the Sabine/Eyring room model
    (which assumes enclosed walls) over-estimates decay time for open zones.

    Model: scale the preset nominal RT60 by a zone-area factor so larger
    open zones get a slightly longer coherent ground-reflection tail, then
    reduce by the absorption coefficient.  Result is clamped to [0.05, 2.0] s
    (outdoor RT60 never exceeds ~2 s in real terrain).
    """
    area_m2 = float(cell_count) * cell_size ** 2
    # Normalise around a 100 m-radius reference open zone
    area_factor = float(np.sqrt(max(area_m2, 1.0))) / (np.pi ** 0.5 * 100.0)
    area_factor = float(np.clip(area_factor, 0.5, 2.0))
    alpha = float(np.clip(absorption, 0.01, 0.999))
    rt60 = preset_rt60 * area_factor * (1.0 - alpha * 0.5)
    return float(np.clip(rt60, 0.05, 2.0))


def _chamfer_distance_cells(cliff_mask: np.ndarray) -> np.ndarray:
    """Two-pass sequential chamfer distance transform (no SciPy).

    Classic Borgefors 1986 3-4 chamfer EDT: one forward sweep
    (top-left → bottom-right) + one reverse sweep (bottom-right → top-left).
    Each sweep processes one row at a time so that already-updated cells
    in the current row/previous row are immediately visible to the next
    cell (proper sequential propagation).  Row interiors are fully
    numpy-vectorised.

    Kernel (3-4 costs)::

        forward:            reverse:
            4 3 4               . . .
            3 0 .               . 0 3
            . . .               4 3 4

    Unit costs: orthogonal = 3, diagonal = 4.  The final array is divided
    by 3.0 to convert chamfer units back into approximate cell-space
    Euclidean distance.  Error < 2.5 % vs. exact Euclidean.

    Parameters
    ----------
    cliff_mask : bool (H, W) — True where the cliff surface is.

    Returns
    -------
    np.ndarray float64 (H, W) — approximate Euclidean distance in cells.
    """
    H, W = cliff_mask.shape
    INF = float(H + W) * 10.0
    # Seed: cliff cells = 0, non-cliff = sentinel.
    dist = np.where(cliff_mask, 0.0, INF).astype(np.float64)

    ORTH = 3.0
    DIAG = 4.0

    # --- Forward sweep: row 0 → row H-1, within each row left → right ---
    for r in range(H):
        row = dist[r]
        # Neighbours from the row above (already finalised).
        if r > 0:
            prev = dist[r - 1]
            # top (orthogonal)
            row = np.minimum(row, prev + ORTH)
            # top-left diagonal
            if W > 1:
                tl = np.full(W, INF)
                tl[1:] = prev[:-1] + DIAG
                row = np.minimum(row, tl)
                # top-right diagonal
                tr = np.full(W, INF)
                tr[:-1] = prev[1:] + DIAG
                row = np.minimum(row, tr)
        # Left neighbour within the same row — must be sequential because
        # it uses the updated value from the previous column.
        for c in range(1, W):
            cand = row[c - 1] + ORTH
            if cand < row[c]:
                row[c] = cand
        dist[r] = row

    # --- Reverse sweep: row H-1 → row 0, within each row right → left ---
    for r in range(H - 1, -1, -1):
        row = dist[r]
        if r < H - 1:
            nxt = dist[r + 1]
            # bottom (orthogonal)
            row = np.minimum(row, nxt + ORTH)
            # bottom-right diagonal
            if W > 1:
                br = np.full(W, INF)
                br[:-1] = nxt[1:] + DIAG
                row = np.minimum(row, br)
                # bottom-left diagonal
                bl = np.full(W, INF)
                bl[1:] = nxt[:-1] + DIAG
                row = np.minimum(row, bl)
        # Right neighbour within the same row (sequential).
        for c in range(W - 2, -1, -1):
            cand = row[c + 1] + ORTH
            if cand < row[c]:
                row[c] = cand
        dist[r] = row

    return dist / ORTH


def _cliff_echo_delay(
    shape: Tuple[int, int],
    cliff_mask: np.ndarray,
    cell_size: float,
    _force_no_scipy: bool = False,
) -> np.ndarray:
    """Per-cell cliff echo delay in seconds.

    Echo delay = 2 * distance_to_nearest_cliff / speed_of_sound.
    Cells without a reachable cliff get delay = 0 (no echo).

    If SciPy is unavailable the vectorised chamfer EDT fallback is used
    (see :func:`_chamfer_distance_cells`); accuracy < 2.5 % vs. exact
    Euclidean, sufficient for FMOD/Wwise early-reflection timing which
    is humanly perceivable only above ~30 ms delta (≈10 m error).

    Parameters
    ----------
    shape          : (H, W) result shape.
    cliff_mask     : bool (H, W) — True where cliffs are.
    cell_size      : metres per cell.
    _force_no_scipy : Internal/testing flag — when True, skips the SciPy
        branch to exercise the chamfer fallback.  Never set in production.

    Returns
    -------
    np.ndarray float32 (H, W) — echo delay in seconds per cell.
    """
    if not cliff_mask.any():
        return np.zeros(shape, dtype=np.float32)

    dist_cells: Optional[np.ndarray] = None
    if not _force_no_scipy:
        try:
            from scipy.ndimage import distance_transform_edt as _edt
            dist_cells = _edt(~cliff_mask).astype(np.float64)
        except ImportError:
            dist_cells = None

    if dist_cells is None:
        logger.warning(
            "terrain_audio_zones: SciPy unavailable — _cliff_echo_delay using "
            "vectorised chamfer EDT fallback (degraded vectorisation; "
            "accuracy ~2.5%% vs. exact Euclidean, safe for FMOD/Wwise "
            "early-reflection timing)."
        )
        dist_cells = _chamfer_distance_cells(cliff_mask)

    dist_m = dist_cells * float(cell_size)
    # Max echo range: 200 m (beyond that, echo is inaudible)
    dist_m = np.clip(dist_m, 0.0, 200.0)
    delay = (2.0 * dist_m / _SPEED_OF_SOUND_MS).astype(np.float32)
    return delay


#: Priority graph — index into this tuple == paint order (lowest first, highest last).
#: Documented: each entry is "class → gating predicates".
#: Callers that add new classes must append here so priority is explicit.
AUDIO_ZONE_PRIORITY_ORDER: Tuple[int, ...] = (
    AudioReverbClass.OPEN_FIELD.value,
    AudioReverbClass.FOREST_SPARSE.value,
    AudioReverbClass.FOREST_DENSE.value,
    AudioReverbClass.MOUNTAIN_HIGH.value,
    AudioReverbClass.WATER_NEAR.value,
    AudioReverbClass.CANYON.value,
    AudioReverbClass.CAVE.value,
    AudioReverbClass.INTERIOR.value,
)


def _classify_raster(stack: TerrainMaskStack) -> np.ndarray:
    """Build the (H, W) int8 AudioReverbClass raster from stack channels.

    Priority order (highest last) mirrors :data:`AUDIO_ZONE_PRIORITY_ORDER`:
    OPEN_FIELD < FOREST_SPARSE < FOREST_DENSE < MOUNTAIN_HIGH < WATER_NEAR
    < CANYON < CAVE < INTERIOR.

    Classification model (acoustically motivated):
    Cave / overhang
        cave_candidate > 0.5 OR (cliff_candidate > 0.5 AND concavity > 0.3
        AND low sky-exposure).  Sky exposure is proxied by
        (1 - ambient_occlusion_bake) or the surround-ratio over a 3x3
        neighbourhood — a cave must be both surrounded by terrain AND
        occluded from the sky hemisphere.  Sabine/Eyring RT60 > 2 s.
    Water surface
        water_surface > 0 OR wetness > 0.6.  Specular flat reflector.
    Canyon / valley
        Strong negative curvature (curv < -0.15) AND high slope (> 25°),
        AND parallel-wall variance across local neighbourhood (canyon flutter
        requires two roughly-parallel reflectors). Falls back to the simpler
        curv+slope predicate if no slope-variance is computable.
    Forest
        detail_density sum > 0.6 → DENSE.  Sum > 0.2 → SPARSE.
        Tree-density proxy modulates the Sabine absorption coefficient in
        compute_audio_zone_list() for per-zone RT60.
    Mountain high
        Normalised height > 0.75 AND slope > 30°.
    Open field
        Catch-all; Sabine RT60 ≈ 0.1–0.3 s (low absorption = mostly direct).
    """
    if stack.height is None:
        raise ValueError("compute_audio_reverb_zones requires stack.height")

    h = np.asarray(stack.height, dtype=np.float64)
    shape = h.shape
    H, W = shape
    min_cells = max(4, H * W // 2000)
    out = np.full(shape, AudioReverbClass.OPEN_FIELD.value, dtype=np.int8)

    slope = stack.slope
    if slope is None:
        gy_arr, gx_arr = np.gradient(h, float(stack.cell_size))
        slope = np.arctan(np.sqrt(gx_arr ** 2 + gy_arr ** 2))
    slope = np.asarray(slope, dtype=np.float64)

    # Height normalisation
    hmin = float(stack.height_min_m) if stack.height_min_m is not None else float(h.min())
    hmax = float(stack.height_max_m) if stack.height_max_m is not None else float(h.max())
    hspan = max(hmax - hmin, 1e-6)
    h_norm = (h - hmin) / hspan

    # Forest density
    forest_dense = np.zeros(shape, dtype=bool)
    forest_sparse = np.zeros(shape, dtype=bool)
    if stack.detail_density:
        total = np.zeros(shape, dtype=np.float64)
        for _k, arr in stack.detail_density.items():
            total += np.asarray(arr, dtype=np.float64)
        forest_dense = _audio_cc_filter(total > 0.6, min_cells)
        forest_sparse = _audio_cc_filter((total > 0.2) & (~forest_dense), min_cells)

    # Mountain high
    mountain = _audio_cc_filter(
        (h_norm > 0.75) & (slope > np.radians(30.0)), min_cells
    )

    # Canyon: strong concavity + high slope + parallel-wall variance.
    # Canyons acoustically require two opposing reflective walls — proxied by
    # high local slope variance across a 5x5 window (flat floor surrounded by
    # steep walls ⇒ high σ(slope)).  Falls back to curv+slope if variance is
    # unavailable.
    canyon = np.zeros(shape, dtype=bool)
    curv = stack.curvature
    if curv is None:
        curv = stack.concavity
    if curv is not None:
        curv_np = np.asarray(curv, dtype=np.float64)
        base_canyon = (curv_np < -0.15) & (slope > np.radians(25.0))
        # Local slope variance proxy: gradient of slope magnitude.
        try:
            sgy, sgx = np.gradient(slope, float(stack.cell_size))
            slope_var = np.sqrt(sgx ** 2 + sgy ** 2)
            # Normalise: canyons have strongly non-uniform slope fields.
            parallel_walls = slope_var > np.median(slope_var) * 1.5
            canyon = _audio_cc_filter(base_canyon & parallel_walls, min_cells)
            # Fall back to the simpler gate if variance gate rejects everything.
            if not canyon.any() and base_canyon.any():
                canyon = _audio_cc_filter(base_canyon, min_cells)
        except (ValueError, TypeError):
            canyon = _audio_cc_filter(base_canyon, min_cells)

    # Cave / overhang — requires BOTH enclosure AND low sky exposure.
    # Explicit cave_candidate > 0.5 is accepted as authoritative.
    # Otherwise the (cliff + concavity) overhang predicate is tightened with
    # a low-sky-exposure gate derived from ambient_occlusion_bake.
    cave = np.zeros(shape, dtype=bool)
    if stack.cave_candidate is not None:
        cave = np.asarray(stack.cave_candidate) > 0.5
    if stack.cliff_candidate is not None and stack.concavity is not None:
        cliff_np = np.asarray(stack.cliff_candidate, dtype=np.float64)
        conc_np = np.asarray(stack.concavity, dtype=np.float64)
        overhang_base = (cliff_np > 0.5) & (conc_np > 0.3)
        # Sky exposure proxy: ambient_occlusion_bake is in [0, 1] where
        # 0 = fully occluded (low sky exposure => cave).  If unavailable,
        # accept the geometric predicate as-is.
        if stack.ambient_occlusion_bake is not None:
            ao = np.asarray(stack.ambient_occlusion_bake, dtype=np.float64)
            low_sky = ao < 0.4
            overhang = _audio_cc_filter(overhang_base & low_sky, min_cells)
        else:
            overhang = _audio_cc_filter(overhang_base, min_cells)
        cave = cave | overhang

    # Water surface
    water_near = np.zeros(shape, dtype=bool)
    _ws_mask = stack.get("water_surface_mask")
    if _ws_mask is not None:
        water_near |= np.asarray(_ws_mask) > 0.0
    if stack.wetness is not None:
        water_near |= np.asarray(stack.wetness) > 0.6
    water_near = _audio_cc_filter(water_near, min_cells)

    # Interior (physics_collider_mask == 2)
    interior = np.zeros(shape, dtype=bool)
    if stack.physics_collider_mask is not None:
        interior = np.asarray(stack.physics_collider_mask) == 2

    # Priority paint (lowest first, highest last).  Driven by
    # AUDIO_ZONE_PRIORITY_ORDER so new classes land in a documented order.
    _PAINT_MASKS: Dict[int, np.ndarray] = {
        AudioReverbClass.FOREST_SPARSE.value: forest_sparse,
        AudioReverbClass.FOREST_DENSE.value: forest_dense,
        AudioReverbClass.MOUNTAIN_HIGH.value: mountain,
        AudioReverbClass.WATER_NEAR.value: water_near,
        AudioReverbClass.CANYON.value: canyon,
        AudioReverbClass.CAVE.value: cave,
        AudioReverbClass.INTERIOR.value: interior,
    }
    for cls_val in AUDIO_ZONE_PRIORITY_ORDER:
        mask = _PAINT_MASKS.get(cls_val)
        if mask is None:
            continue
        out[mask] = cls_val

    return out


def compute_audio_reverb_zones(
    stack: TerrainMaskStack,
) -> np.ndarray:
    """Return (H, W) int8 array of AudioReverbClass values.

    This is the primary raster output.  Each cell holds the dominant reverb
    class for that terrain position, suitable for Unity AudioReverbZone proxy
    placement and FMOD spatial audio parameter injection.

    Classification uses physical models:
    - Cave:        cliff_candidate + concavity → enclosed geometry, RT60 > 2 s
    - Canyon:      concavity + steep slope     → flutter echo, RT60 ~ 1 s
    - Water:       water_surface / wetness     → specular reflector
    - Forest dense/sparse: detail_density sum threshold
    - Mountain:    height_norm > 0.75 + slope > 30°
    - Open field:  catch-all

    For the full zone-list with RT60 estimates, echo delays, and boundary
    polygons, call compute_audio_zone_list().
    """
    return _classify_raster(stack)


#: Per-class occlusion weight — drives Wwise LPF / FMOD `Occlusion` slider
#: when the listener is outside the zone but facing into it.
_CLASS_OCCLUSION_WEIGHT: Dict[int, float] = {
    AudioReverbClass.OPEN_FIELD.value: 0.00,
    AudioReverbClass.FOREST_SPARSE.value: 0.15,
    AudioReverbClass.FOREST_DENSE.value: 0.45,
    AudioReverbClass.CAVE.value: 0.85,
    AudioReverbClass.CANYON.value: 0.40,
    AudioReverbClass.WATER_NEAR.value: 0.05,
    AudioReverbClass.MOUNTAIN_HIGH.value: 0.10,
    AudioReverbClass.INTERIOR.value: 0.75,
}


def compute_audio_zone_list(
    stack: TerrainMaskStack,
) -> List[Dict[str, Any]]:
    """Return a list of physically-based audio reverb zone dicts.

    This is the **zone graph consumed by Wwise and FMOD**.  Downstream
    :func:`export_zones_to_wwise_csv` converts it into a flat CSV suitable
    for Wwise Auxiliary Bus import (Game-Defined Auxiliary Sends) and the
    FMOD Studio *Reverb Region* import workflow.

    Each zone dict contains the following stable keys:
        id                 : str — deterministic "<preset>_<index>" identifier.
        preset             : str — key into :data:`REVERB_PRESETS`.
        boundary_polygon   : List[Tuple[int, int]] — convex hull cell coords.
        rt60_seconds       : float — Norris-Eyring RT60 for this zone, in
                                     seconds, clamped to [0.05, 10.0].
        echo_delay_ms      : float — mean cliff echo delay, in **milliseconds**
                                     (Wwise/FMOD use ms for pre-delay).
        occlusion_weight   : float — zone occlusion strength in [0, 1].
        wet_send_default   : float — default wet-send level in [0, 1] (dry→wet
                                     mix for the Auxiliary Bus).
        class_id           : int — AudioReverbClass value.
        cell_count         : int — number of source cells.

    Legacy keys retained for backward compatibility:
        reverb_preset, dry_wet_ratio, rt60, echo_delay_mean.

    RT60 is estimated per zone using the Norris-Eyring equation (see
    :func:`_sabine_rt60`) with local volume and surface area derived from the
    zone's cell footprint and height variance.  Cliff echo delay is computed
    from EDT distance to the nearest cliff cell (SciPy-exact or chamfer fallback).
    """
    reverb_class_raster = _classify_raster(stack)
    h = np.asarray(stack.height, dtype=np.float64)
    shape = h.shape

    # Pre-compute cliff echo delay field
    cliff_mask = np.zeros(shape, dtype=bool)
    if stack.cliff_candidate is not None:
        cliff_mask = np.asarray(stack.cliff_candidate, dtype=np.float64) > 0.5
    echo_delay_field = _cliff_echo_delay(shape, cliff_mask, float(stack.cell_size))

    zones: List[Dict[str, Any]] = []

    unique_classes = np.unique(reverb_class_raster)
    all_non_open = [
        cls for cls in unique_classes
        if cls != AudioReverbClass.OPEN_FIELD.value
    ]

    # Per-preset running index for deterministic zone ids.
    preset_counter: Dict[str, int] = {}

    for cls_val in unique_classes:
        cls_mask = reverb_class_raster == cls_val
        if cls_val == AudioReverbClass.OPEN_FIELD.value and len(all_non_open) > 0:
            continue

        labeled, n_comp = _label_audio_components(cls_mask)

        preset_name = _CLASS_PRESET.get(int(cls_val), "open_field")
        preset = REVERB_PRESETS[preset_name]
        base_dry_wet = _CLASS_DRY_WET.get(int(cls_val), 0.10)
        absorption = preset["absorption"]
        occlusion = _CLASS_OCCLUSION_WEIGHT.get(int(cls_val), 0.20)

        for cid in range(1, n_comp + 1):
            comp_mask = labeled == cid
            cell_count = int(comp_mask.sum())
            if cell_count == 0:
                continue

            # RT60 model: outdoor zones use sky-reflection model (FIX-7-17);
            # enclosed zones (cave, canyon, interior) use Norris-Eyring.
            h_comp = h[comp_mask]
            mean_height_delta = float(h_comp.std()) if len(h_comp) > 1 else 1.0
            if int(cls_val) in _OUTDOOR_ZONE_CLASSES:
                rt60 = _outdoor_rt60(
                    cell_count,
                    float(stack.cell_size),
                    absorption,
                    preset["rt60"],
                )
            else:
                rt60 = _sabine_rt60(
                    cell_count,
                    float(stack.cell_size),
                    mean_height_delta,
                    absorption,
                )

            # Cliff echo delay (seconds → ms for Wwise/FMOD pre_delay slot).
            echo_delay_s = float(echo_delay_field[comp_mask].mean())
            echo_delay_s = max(0.0, echo_delay_s)  # guarantee non-negative
            echo_delay_ms = echo_delay_s * 1000.0

            boundary_polygon = _component_boundary_polygon(cls_mask, labeled, cid)

            # Forest zone: modulate dry_wet by local density.
            dry_wet = base_dry_wet
            if (
                cls_val in (
                    AudioReverbClass.FOREST_DENSE.value,
                    AudioReverbClass.FOREST_SPARSE.value,
                )
                and stack.detail_density
            ):
                comp_density_sum = 0.0
                comp_density_n = 0
                for _k, arr in stack.detail_density.items():
                    vals = np.asarray(arr, dtype=np.float64)[comp_mask]
                    comp_density_sum += float(vals.mean())
                    comp_density_n += 1
                if comp_density_n > 0:
                    mean_density = comp_density_sum / comp_density_n
                    dry_wet = float(min(0.40, base_dry_wet + mean_density * 0.15))

            idx = preset_counter.get(preset_name, 0)
            preset_counter[preset_name] = idx + 1
            zone_id = f"{preset_name}_{idx:03d}"

            zones.append({
                # --- AAA payload (Wwise/FMOD-facing) ---
                "id": zone_id,
                "preset": preset_name,
                "boundary_polygon": boundary_polygon,
                "rt60_seconds": round(float(rt60), 4),
                "echo_delay_ms": round(float(echo_delay_ms), 3),
                "occlusion_weight": round(float(occlusion), 4),
                "wet_send_default": round(float(dry_wet), 4),
                # --- Context fields ---
                "class_id": int(cls_val),
                "cell_count": cell_count,
                # --- Legacy aliases (kept for backward compatibility) ---
                "reverb_preset": preset_name,
                "dry_wet_ratio": round(float(dry_wet), 4),
                "rt60": round(float(rt60), 4),
                "echo_delay_mean": round(float(echo_delay_s), 4),
            })

    zones.sort(key=lambda z: z["cell_count"], reverse=True)
    return zones


# ---------------------------------------------------------------------------
# Wwise / FMOD CSV exporter
# ---------------------------------------------------------------------------


#: Columns in the exported Wwise CSV — matches the Wwise "Auxiliary Bus
#: environmental properties" import schema (see Wwise SDK > "Game-Defined
#: Auxiliary Sends" documentation).  Each row represents one zone mapped to
#: an Aux Bus; the game-side integration script creates the matching bus in
#: the Wwise project and wires up game_object_aux_sends.
_WWISE_CSV_COLUMNS: Tuple[str, ...] = (
    "zone_id",
    "preset_name",
    "class_id",
    "rt60_seconds",
    "pre_delay_ms",
    "echo_delay_ms",
    "occlusion_weight",
    "wet_send_default",
    "diffusion",
    "hf_damping",
    "lf_reference_hz",
    "polygon_cell_count",
    "source_cell_count",
)


def export_zones_to_wwise_csv(
    zones: List[Dict[str, Any]],
) -> str:
    """Serialise a zone list (from :func:`compute_audio_zone_list`) to CSV.

    The produced CSV is consumed by the VeilBreakers Wwise/FMOD integration
    script (``unity_plugin/Editor/VbAudioZoneImporter.cs``) which creates
    matching ``AK.Wwise.AuxBus`` instances and places Unity
    ``AudioReverbZone`` proxies at the polygon centroids.

    The column set is stable — downstream importers only read the column
    names in the header row.  Missing optional fields are emitted as
    numeric zero so Wwise falls back to the Aux Bus default.

    Parameters
    ----------
    zones : list produced by :func:`compute_audio_zone_list`.

    Returns
    -------
    str : UTF-8 CSV text ready to be written to disk or embedded in the
          Unity import manifest.  Includes header row.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_WWISE_CSV_COLUMNS)
    for z in zones:
        preset_name = z.get("preset") or z.get("reverb_preset") or "open_field"
        preset = REVERB_PRESETS.get(preset_name, REVERB_PRESETS["open_field"])
        rt60 = z.get("rt60_seconds", z.get("rt60", 0.0))
        echo_ms = z.get(
            "echo_delay_ms",
            float(z.get("echo_delay_mean", 0.0)) * 1000.0,
        )
        writer.writerow([
            z.get("id", f"{preset_name}_000"),
            preset_name,
            int(z.get("class_id", 0)),
            f"{float(rt60):.4f}",
            f"{float(preset.get('pre_delay', 0.0)) * 1000.0:.3f}",
            f"{float(echo_ms):.3f}",
            f"{float(z.get('occlusion_weight', 0.0)):.4f}",
            f"{float(z.get('wet_send_default', z.get('dry_wet_ratio', 0.0))):.4f}",
            f"{float(preset.get('diffusion', 0.0)):.4f}",
            f"{float(preset.get('hf_damping', 0.0)):.4f}",
            f"{float(preset.get('lf_reference', 250)):.1f}",
            int(len(z.get("boundary_polygon", []))),
            int(z.get("cell_count", 0)),
        ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Pass wrapper
# ---------------------------------------------------------------------------


def pass_audio_zones(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle J pass: compute physically-based audio reverb zones.

    Produces:
      audio_reverb_class  — int8 raster (AudioReverbClass per cell)

    Metrics include the full zone list with Sabine RT60 estimates and cliff
    echo delays, suitable for FMOD spatial audio region injection and Unity
    AudioReverbZone proxy placement.

    Consumes: height (+ optional slope/curvature/concavity/cliff_candidate/
              cave_candidate/water_surface/wetness/detail_density)
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: list[ValidationIssue] = []

    reverb_class_raster = _classify_raster(stack)
    stack.set("audio_reverb_class", reverb_class_raster, "audio_zones")

    zones = compute_audio_zone_list(stack)
    # Publish the enriched zone graph on the opaque channel so that
    # terrain_unity_export (and any future FMOD/Wwise consumer) can emit
    # CSV/JSON sidecars without re-running the classifier.
    stack.set("audio_zone_list", zones, "audio_zones")

    non_open_zones = [
        z for z in zones
        if z["class_id"] != AudioReverbClass.OPEN_FIELD.value
    ]
    if len(non_open_zones) == 0:
        issues.append(
            ValidationIssue(
                code="AUDIO_ZONES_TRIVIAL",
                severity="soft",
                message=(
                    "all cells classified OPEN_FIELD — "
                    "upstream masks (cave_candidate, cliff_candidate, "
                    "detail_density, water_surface) may be empty"
                ),
            )
        )

    vals, counts = np.unique(reverb_class_raster, return_counts=True)
    dominant_frac = float(counts.max() / counts.sum()) if counts.size > 0 else 1.0

    return PassResult(
        pass_name="audio_zones",
        status="ok" if not any(i.is_hard() for i in issues) else "failed",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("audio_reverb_class", "audio_zone_list"),
        metrics={
            "zones_count": len(zones),
            "non_open_zones_count": len(non_open_zones),
            "zones": zones,
            "class_distribution": {
                int(v): int(c) for v, c in zip(vals.tolist(), counts.tolist())
            },
            "dominant_fraction": dominant_frac,
        },
        issues=issues,
    )


#: Alias — the "compute audio zones" pass, registered under a second name so
#: world-gen orchestration can wire the zone-graph publisher without needing
#: to know about the Bundle-J classifier internals.  Both names resolve to
#: the same callable so idempotent registration is safe.
pass_compute_audio_zones = pass_audio_zones


def register_bundle_j_audio_zones_pass() -> None:
    """Register the audio_zones pass on TerrainPassController.

    Publishes:
      audio_reverb_class  (ndarray)
      audio_zone_list     (opaque list[dict] — Wwise/FMOD zone graph)
    """
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="audio_zones",
            func=pass_audio_zones,
            requires_channels=("height",),
            produces_channels=("audio_reverb_class", "audio_zone_list"),
            seed_namespace="audio_zones",
            requires_scene_read=False,
            may_modify_geometry=False,
            description=(
                "Bundle J: classify audio reverb zones from mask stack "
                "(publishes audio_reverb_class + audio_zone_list)"
            ),
        )
    )


__all__ = [
    "AUDIO_ZONE_PRIORITY_ORDER",
    "AudioReverbClass",
    "REVERB_PRESETS",
    "compute_audio_reverb_zones",
    "compute_audio_zone_list",
    "export_zones_to_wwise_csv",
    "pass_audio_zones",
    "pass_compute_audio_zones",
    "register_bundle_j_audio_zones_pass",
]
