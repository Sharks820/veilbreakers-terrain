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

import time
from enum import IntEnum
from typing import Dict, List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _audio_cc_filter(mask: np.ndarray, min_cells: int) -> np.ndarray:
    """Return mask with small isolated components removed."""
    if not mask.any():
        return mask
    try:
        from scipy.ndimage import label as _sclabel
        labeled, n = _sclabel(mask, structure=np.ones((3, 3), dtype=int))
        if n == 0:
            return mask
        cleaned = np.zeros_like(mask)
        for cid in range(1, n + 1):
            comp = labeled == cid
            if int(comp.sum()) >= min_cells:
                cleaned |= comp
        return cleaned
    except ImportError:
        return mask


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


def _sabine_rt60(
    cell_count: int,
    cell_size: float,
    mean_height_delta: float,
    absorption: float,
) -> float:
    """Sabine equation: T60 = 0.161 * V / (α * S).

    Estimates the volume V from cell footprint * mean enclosure height,
    and surface area S from cell perimeter + top/bottom faces.

    Parameters
    ----------
    cell_count      : number of grid cells in the zone
    cell_size       : metres per cell
    mean_height_delta : average height variance within the zone (proxy for
                       wall height in enclosed spaces)
    absorption      : Sabine absorption coefficient α ∈ (0, 1]

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
    rt60 = 0.161 * volume / (absorption * surface)
    return float(np.clip(rt60, 0.05, 10.0))


def _cliff_echo_delay(
    shape: Tuple[int, int],
    cliff_mask: np.ndarray,
    cell_size: float,
) -> np.ndarray:
    """Per-cell cliff echo delay in seconds.

    Echo delay = 2 * distance_to_nearest_cliff / speed_of_sound.
    Cells without a reachable cliff get delay = 0 (no echo).

    Returns
    -------
    np.ndarray float32 (H, W) — echo delay in seconds per cell.
    """
    if not cliff_mask.any():
        return np.zeros(shape, dtype=np.float32)
    try:
        from scipy.ndimage import distance_transform_edt as _edt
        dist_cells = _edt(~cliff_mask).astype(np.float64)
    except ImportError:
        dist_cells = np.zeros(shape, dtype=np.float64)

    dist_m = dist_cells * float(cell_size)
    # Max echo range: 200 m (beyond that, echo is inaudible)
    dist_m = np.clip(dist_m, 0.0, 200.0)
    delay = (2.0 * dist_m / _SPEED_OF_SOUND_MS).astype(np.float32)
    return delay


def _classify_raster(stack: TerrainMaskStack) -> np.ndarray:
    """Build the (H, W) int8 AudioReverbClass raster from stack channels.

    Priority order (highest last): OPEN_FIELD < FOREST_SPARSE < FOREST_DENSE
    < MOUNTAIN_HIGH < WATER_NEAR < CANYON < CAVE < INTERIOR.

    Classification model:
    Cave / overhang
        cave_candidate (explicit) OR (cliff_candidate AND concavity).
        Sabine RT60 > 2 s — hard reflective surfaces, enclosed geometry.
    Water surface
        water_surface > 0 OR wetness > 0.6.  Specular flat reflector.
    Canyon / valley
        Strong concavity (curv < -0.15) AND high slope (> 25°) without cave.
        Parallel hard walls → flutter echo.
    Forest
        detail_density sum > 0.6 → DENSE.  Sum > 0.2 → SPARSE.
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

    # Canyon: strong concavity + high slope
    canyon = np.zeros(shape, dtype=bool)
    curv = stack.curvature
    if curv is None:
        curv = stack.concavity
    if curv is not None:
        curv_np = np.asarray(curv, dtype=np.float64)
        canyon = _audio_cc_filter(
            (curv_np < -0.15) & (slope > np.radians(25.0)), min_cells
        )

    # Cave / overhang
    cave = np.zeros(shape, dtype=bool)
    if stack.cave_candidate is not None:
        cave = np.asarray(stack.cave_candidate) > 0.5
    if stack.cliff_candidate is not None and stack.concavity is not None:
        cliff_np = np.asarray(stack.cliff_candidate, dtype=np.float64)
        conc_np = np.asarray(stack.concavity, dtype=np.float64)
        overhang = _audio_cc_filter(
            (cliff_np > 0.5) & (conc_np > 0.3), min_cells
        )
        cave = cave | overhang

    # Water surface
    water_near = np.zeros(shape, dtype=bool)
    if stack.water_surface is not None:
        water_near |= np.asarray(stack.water_surface) > 0.0
    if stack.wetness is not None:
        water_near |= np.asarray(stack.wetness) > 0.6
    water_near = _audio_cc_filter(water_near, min_cells)

    # Interior (physics_collider_mask == 2)
    interior = np.zeros(shape, dtype=bool)
    if stack.physics_collider_mask is not None:
        interior = np.asarray(stack.physics_collider_mask) == 2

    # Priority paint (lowest first, highest last)
    out[forest_sparse] = AudioReverbClass.FOREST_SPARSE.value
    out[forest_dense] = AudioReverbClass.FOREST_DENSE.value
    out[mountain] = AudioReverbClass.MOUNTAIN_HIGH.value
    out[water_near] = AudioReverbClass.WATER_NEAR.value
    out[canyon] = AudioReverbClass.CANYON.value
    out[cave] = AudioReverbClass.CAVE.value
    out[interior] = AudioReverbClass.INTERIOR.value

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


def compute_audio_zone_list(
    stack: TerrainMaskStack,
) -> List[Dict]:
    """Return a list of physically-based audio reverb zone dicts.

    Each zone dict contains:
        boundary_polygon : List[Tuple[int, int]] — convex hull cell coords
        reverb_preset    : str — key into REVERB_PRESETS
        dry_wet_ratio    : float in [0, 1]
        class_id         : int (AudioReverbClass value)
        rt60             : float — Sabine-estimated RT60 for this zone (seconds)
        echo_delay_mean  : float — mean cliff echo delay (seconds)
        cell_count       : int

    RT60 is estimated per zone using the Sabine equation with local volume
    and surface area derived from the zone's cell footprint and height variance.
    Cliff echo delay is computed from EDT distance to the nearest cliff cell.
    """
    reverb_class_raster = _classify_raster(stack)
    h = np.asarray(stack.height, dtype=np.float64)
    shape = h.shape

    # Pre-compute cliff echo delay field
    cliff_mask = np.zeros(shape, dtype=bool)
    if stack.cliff_candidate is not None:
        cliff_mask = np.asarray(stack.cliff_candidate, dtype=np.float64) > 0.5
    echo_delay_field = _cliff_echo_delay(shape, cliff_mask, float(stack.cell_size))

    zones: List[Dict] = []

    try:
        from scipy.ndimage import label as _sclabel
        has_scipy = True
    except ImportError:
        has_scipy = False

    unique_classes = np.unique(reverb_class_raster)
    all_non_open = [
        cls for cls in unique_classes
        if cls != AudioReverbClass.OPEN_FIELD.value
    ]

    for cls_val in unique_classes:
        cls_mask = reverb_class_raster == cls_val
        if cls_val == AudioReverbClass.OPEN_FIELD.value and len(all_non_open) > 0:
            continue

        if has_scipy:
            from scipy.ndimage import label as _sclabel
            labeled, n_comp = _sclabel(
                cls_mask, structure=np.ones((3, 3), dtype=int)
            )
        else:
            labeled = cls_mask.astype(np.int32)
            n_comp = 1 if cls_mask.any() else 0

        preset_name = _CLASS_PRESET.get(int(cls_val), "open_field")
        preset = REVERB_PRESETS[preset_name]
        base_dry_wet = _CLASS_DRY_WET.get(int(cls_val), 0.10)
        absorption = preset["absorption"]

        for cid in range(1, n_comp + 1):
            comp_mask = labeled == cid
            cell_count = int(comp_mask.sum())
            if cell_count == 0:
                continue

            # Sabine RT60 estimate for this specific zone instance
            h_comp = h[comp_mask]
            mean_height_delta = float(h_comp.std()) if len(h_comp) > 1 else 1.0
            rt60 = _sabine_rt60(
                cell_count,
                float(stack.cell_size),
                mean_height_delta,
                absorption,
            )

            # Cliff echo delay mean for this zone
            echo_delay_mean = float(echo_delay_field[comp_mask].mean())

            boundary_polygon = _component_boundary_polygon(cls_mask, labeled, cid)

            # Forest zone: modulate dry_wet by local density
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

            zones.append({
                "boundary_polygon": boundary_polygon,
                "reverb_preset": preset_name,
                "dry_wet_ratio": round(dry_wet, 4),
                "class_id": int(cls_val),
                "rt60": round(rt60, 4),
                "echo_delay_mean": round(echo_delay_mean, 4),
                "cell_count": cell_count,
            })

    zones.sort(key=lambda z: z["cell_count"], reverse=True)
    return zones


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
        produced_channels=("audio_reverb_class",),
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


def register_bundle_j_audio_zones_pass() -> None:
    """Register the audio_zones pass on TerrainPassController."""
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="audio_zones",
            func=pass_audio_zones,
            requires_channels=("height",),
            produces_channels=("audio_reverb_class",),
            seed_namespace="audio_zones",
            requires_scene_read=False,
            may_modify_geometry=False,
            description="Bundle J: classify audio reverb zones from mask stack",
        )
    )


__all__ = [
    "AudioReverbClass",
    "REVERB_PRESETS",
    "compute_audio_reverb_zones",
    "compute_audio_zone_list",
    "pass_audio_zones",
    "register_bundle_j_audio_zones_pass",
]
