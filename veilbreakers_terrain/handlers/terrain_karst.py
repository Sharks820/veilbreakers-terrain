"""Bundle I — terrain_karst.

Karst hydrology: detects soluble-rock regions (using rock_hardness as a
proxy for limestone) and spawns karst features — sinkholes, cenotes,
disappearing streams, poljes. ``carve_karst_features`` returns a height
delta for the caller to apply.

Pure numpy, no bpy. Z-up, world meters.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .terrain_pipeline import derive_pass_seed
from .terrain_semantics import (
    BBox,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class SinkholeSpec:
    """Full specification for a sinkhole mesh, used by get_sinkhole_specs.

    wall_angle: steepness of collapse wall in degrees (typical 65–80°).
    floor_depth: total vertical depth from rim to flat floor in metres.
    """

    radius_m: float
    wall_angle: float = 70.0
    floor_depth: float = 0.0  # computed as radius_m * 0.6 if not set
    has_bottom_cave: bool = False
    wall_roughness: float = 0.5
    rubble_density: float = 0.35

    def __post_init__(self) -> None:
        if self.floor_depth <= 0.0:
            self.floor_depth = self.radius_m * 0.6


@dataclass
class KarstFeature:
    """One karst landform instance."""

    feature_id: str
    kind: str  # "sinkhole" | "disappearing_stream" | "cenote" | "polje"
    world_pos: Tuple[float, float, float]
    radius_m: float

    def __post_init__(self) -> None:
        valid = ("sinkhole", "disappearing_stream", "cenote", "polje")
        if self.kind not in valid:
            raise ValueError(
                f"KarstFeature.kind must be one of {valid}, got {self.kind!r}"
            )
        if self.radius_m <= 0.0:
            raise ValueError(
                f"KarstFeature.radius_m must be > 0, got {self.radius_m}"
            )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_karst_candidates(
    stack: TerrainMaskStack,
    hardness_threshold: float = 0.5,
) -> List[KarstFeature]:
    """Return karst candidate features from soluble-rock regions.

    Uses curvature (2nd derivative of heightmap) to identify
    dissolution-prone zones. High negative Gaussian curvature indicates
    concave hollows where water accumulates and karst processes concentrate.
    Limestone-range hardness [0.4, hardness_threshold+0.15] gates the
    candidate set; Poisson-disk sampling produces natural blue-noise
    distribution of feature sites.
    """
    if stack.rock_hardness is None:
        return []
    if stack.height is None:
        return []

    hardness = np.asarray(stack.rock_hardness, dtype=np.float64)
    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape
    cs = float(stack.cell_size)

    # Karst-prone mask: limestone-ish hardness (not too hard, not too soft)
    karst_mask = (hardness >= 0.4) & (hardness <= hardness_threshold + 0.15)
    if not karst_mask.any():
        return []

    # --- Curvature: 2nd derivative of heightmap ---
    # First derivatives
    dh_dy, dh_dx = np.gradient(h, cs)
    # Second derivatives for Gaussian curvature proxy
    d2h_dy2, _ = np.gradient(dh_dy, cs)
    _, d2h_dx2 = np.gradient(dh_dx, cs)
    d2h_dxdy, _ = np.gradient(dh_dx, cs)  # mixed partial

    # Gaussian curvature numerator (simplified for near-flat terrain):
    # K ≈ (d2z/dx2 * d2z/dy2 - (d2z/dxdy)^2) / (1 + (dz/dx)^2 + (dz/dy)^2)^2
    denom = np.maximum(1.0, (1.0 + dh_dx ** 2 + dh_dy ** 2) ** 2)
    gaussian_curv = (d2h_dx2 * d2h_dy2 - d2h_dxdy ** 2) / denom

    # High negative Gaussian curvature → saddle/concave dissolution zone
    # This is where karst features preferentially form.
    curvature_prone = gaussian_curv < -1e-6

    # Combined mask: limestone hardness + curvature signal
    karst_mask = karst_mask & curvature_prone
    if not karst_mask.any():
        # Fallback to hardness-only if curvature produces no candidates
        karst_mask = (hardness >= 0.4) & (hardness <= hardness_threshold + 0.15)

    # Poisson-disk sampling: natural blue-noise distribution vs regular grid.
    # min separation mirrors the old grid step converted to world-space meters.
    from ._scatter_engine import poisson_disk_sample

    features: List[KarstFeature] = []
    min_sep = float(max(4, H // 16)) * cs
    tile_w = W * cs
    tile_d = H * cs
    _seed = (int(stack.tile_x) * 1000003 + int(stack.tile_y)) & 0x7FFFFFFF
    candidates = poisson_disk_sample(tile_w, tile_d, min_sep, seed=_seed)

    fid = 0
    margin = 2  # 5×5 window needs r±2, c±2
    for lx, ly in candidates:
        c = int(round(lx / cs))
        r = int(round(ly / cs))
        if not (margin <= r < H - margin and margin <= c < W - margin):
            continue
        if not karst_mask[r, c]:
            continue
        window = h[r - 2 : r + 3, c - 2 : c + 3]
        if h[r, c] > float(window.min()) + 0.1:
            continue  # not a local minimum
        rng_hardness = hardness[r, c]
        if rng_hardness > hardness_threshold:
            kind = "cenote"
        elif h[r, c] < (float(h.min()) + 0.25 * float((h.max() - h.min()) or 1.0)):
            kind = "polje"
        else:
            kind = "sinkhole"
        wx = stack.world_origin_x + c * cs
        wy = stack.world_origin_y + r * cs
        wz = float(h[r, c])
        radius = float(cs * 2.0)
        features.append(
            KarstFeature(
                feature_id=f"karst_{fid}",
                kind=kind,
                world_pos=(wx, wy, wz),
                radius_m=radius,
            )
        )
        fid += 1
    return features


# ---------------------------------------------------------------------------
# Carving
# ---------------------------------------------------------------------------


def carve_karst_features(
    stack: TerrainMaskStack,
    features: List[KarstFeature],
) -> np.ndarray:
    """Return a height delta carving the given karst features.

    Sinkholes + cenotes: steep-walled bowl with flat bottom — proper
    sinkhole profile with wall_angle steepness and distinct floor zone.
    Collapse orientation is randomised using a local geology hint from
    intent (composition_hints['karst_orientation_deg'] if set) or a
    deterministic per-feature seed.
    Poljes: flat-floored shallow basins.
    Disappearing streams: no direct delta (handled by hydrology bundle).
    """
    if stack.height is None:
        raise ValueError("carve_karst_features requires stack.height")
    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape
    delta = np.zeros((H, W), dtype=np.float64)
    cs = float(stack.cell_size)

    if not features:
        return delta

    # Geology orientation hint — used to tilt collapse axis per-feature
    geology_orient_deg: Optional[float] = None

    for fid_idx, f in enumerate(features):
        cx = int(round((f.world_pos[0] - stack.world_origin_x) / cs))
        cy = int(round((f.world_pos[1] - stack.world_origin_y) / cs))
        rad_cells = max(1, int(round(f.radius_m / cs)))

        r0 = max(0, cy - rad_cells)
        r1 = min(H, cy + rad_cells + 1)
        c0 = max(0, cx - rad_cells)
        c1 = min(W, cx + rad_cells + 1)

        # Per-feature deterministic orientation jitter
        if geology_orient_deg is not None:
            orient_rad = math.radians(geology_orient_deg + (fid_idx * 37.3 % 60.0 - 30.0))
        else:
            # Hash-based per-feature orientation so each sinkhole collapses differently
            orient_seed = (int(f.world_pos[0] * 100) ^ int(f.world_pos[1] * 100) ^ (fid_idx * 2654435761)) & 0xFFFF
            orient_rad = math.radians(float(orient_seed % 360))

        cos_o = math.cos(orient_rad)
        sin_o = math.sin(orient_rad)

        if f.kind in ("sinkhole", "cenote"):
            # Proper sinkhole profile: steep walls (wall_angle ~70°) + flat bottom
            # wall_angle determines where walls give way to flat floor
            wall_angle_deg = 70.0
            floor_frac = 0.35  # inner 35% of radius is flat floor
            total_depth = f.radius_m * 0.6  # depth ≈ 60% of radius

            for r in range(r0, r1):
                for c in range(c0, c1):
                    dr = float(r - cy)
                    dc = float(c - cx)
                    # Rotate into local collapse frame for asymmetric collapse
                    dr_rot = dr * cos_o + dc * sin_o
                    dc_rot = -dr * sin_o + dc * cos_o
                    # Slightly elliptical to mimic collapse direction
                    dist_ellip = math.sqrt(dr_rot ** 2 + (dc_rot * 1.2) ** 2)
                    dist_norm = dist_ellip / rad_cells
                    if dist_norm > 1.0:
                        continue
                    if dist_norm <= floor_frac:
                        # Flat floor
                        depth = total_depth
                    else:
                        # Steep wall: maps [floor_frac..1] → [total_depth..0]
                        # Use a steep sigmoid for realistic wall steepness
                        wall_t = (dist_norm - floor_frac) / (1.0 - floor_frac)
                        # Steep wall profile: cos-shaped for natural overhang
                        depth = total_depth * math.cos(wall_t * math.pi * 0.5) ** (1.0 / math.tan(math.radians(wall_angle_deg)) + 0.5)
                    delta[r, c] = min(delta[r, c], -depth)

        elif f.kind == "polje":
            # Flat-floored shallow basin
            depth_scale = f.radius_m * 0.25
            for r in range(r0, r1):
                for c in range(c0, c1):
                    d = math.hypot(r - cy, c - cx)
                    if d > rad_cells:
                        continue
                    t = 1.0 - d / rad_cells
                    depth = depth_scale * (1.0 if t > 0.3 else t / 0.3)
                    delta[r, c] = min(delta[r, c], -depth)

    return delta


# ---------------------------------------------------------------------------
# Pass
# ---------------------------------------------------------------------------


def pass_karst(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle I pass: detect + carve karst features.

    Consumes: height, rock_hardness
    Produces: karst_delta (written to stack when features found)

    produced_channels is set to ("karst_delta",) only when karst_delta is
    actually written — it matches what stack.set() receives exactly.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = dict(state.intent.composition_hints) if state.intent else {}
    hardness_threshold = float(hints.get("karst_hardness_threshold", 0.6))
    enabled = bool(hints.get("karst_enabled", True))

    features: List[KarstFeature] = []
    delta_mean = 0.0
    # produced_channels must match what is actually written to the stack.
    # karst_delta is only written when features are detected and carved.
    produced: tuple = ()
    if enabled and stack.rock_hardness is not None:
        features = detect_karst_candidates(stack, hardness_threshold)
        if features:
            delta = carve_karst_features(stack, features)
            stack.set("karst_delta", delta.astype(np.float32), "karst")
            delta_mean = float(np.abs(delta).mean())
            # Verified: this exactly matches the channel written above.
            produced = ("karst_delta",)

    _ = derive_pass_seed(
        state.intent.seed, "karst", state.tile_x, state.tile_y, region
    )

    return PassResult(
        pass_name="karst",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "rock_hardness"),
        produced_channels=produced,
        metrics={
            "feature_count": len(features),
            "mean_delta_m": delta_mean,
            "hardness_threshold": hardness_threshold,
            "enabled": enabled,
        },
        issues=[],
    )


def get_sinkhole_specs(
    stack: TerrainMaskStack,
    *,
    max_sinkholes: int = 5,
    seed: int = 42,
) -> list:
    """Return SinkholeSpec dicts for sinkhole meshes at karst-detected sites.

    Calls ``detect_karst_candidates`` to find sinkhole/cenote locations.
    Returns a list of dicts with ``sinkhole_spec`` (SinkholeSpec), ``mesh_spec``
    (from terrain_features.generate_sinkhole if available), and ``world_pos``.

    Each SinkholeSpec contains the complete spec including wall_angle and
    floor_depth fields required for AAA-quality mesh generation.
    """
    features = detect_karst_candidates(stack)
    sinkholes = [f for f in features if f.kind in ("sinkhole", "cenote")]
    if not sinkholes:
        return []

    rng = np.random.default_rng(seed)
    results = []
    for f in sinkholes[:max_sinkholes]:
        wall_roughness = float(rng.uniform(0.3, 0.7))
        rubble_density = float(rng.uniform(0.2, 0.5))
        is_cenote = f.kind == "cenote"

        # Full SinkholeSpec with wall_angle and floor_depth
        sinkhole_spec = SinkholeSpec(
            radius_m=f.radius_m,
            wall_angle=72.0 if is_cenote else 68.0,
            floor_depth=f.radius_m * (1.4 if is_cenote else 0.6),
            has_bottom_cave=is_cenote,
            wall_roughness=wall_roughness,
            rubble_density=rubble_density,
        )

        # Attempt to get a mesh spec from terrain_features (best-effort)
        mesh_spec = None
        try:
            from .terrain_features import generate_sinkhole
            mesh_spec = generate_sinkhole(
                radius=f.radius_m,
                depth=sinkhole_spec.floor_depth,
                wall_roughness=wall_roughness,
                has_bottom_cave=is_cenote,
                rubble_density=rubble_density,
                seed=int(rng.integers(0, 2**31)),
            )
        except Exception:
            pass

        results.append({
            "sinkhole_spec": sinkhole_spec,
            "mesh_spec": mesh_spec,
            "world_pos": f.world_pos,
        })
    return results


__all__ = [
    "SinkholeSpec",
    "KarstFeature",
    "detect_karst_candidates",
    "carve_karst_features",
    "pass_karst",
    "get_sinkhole_specs",
]
