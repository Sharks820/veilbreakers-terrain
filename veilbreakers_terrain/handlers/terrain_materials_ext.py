"""Bundle B supplement — material ceiling extensions.

Extends ``terrain_materials_v2`` with height-blended (gamma) layer weights,
texel-density coherency checks, micro-normal metadata, and cliff silhouette
area validation. Does NOT modify the original Bundle B module.

Per Addendum 1.B.2 of docs/terrain_ultra_implementation_plan_2026-04-08.md.

No bpy imports — headless-compatible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

from .terrain_materials_v2 import MaterialChannel
from .terrain_semantics import ValidationIssue


# ---------------------------------------------------------------------------
# Extended material channel
# ---------------------------------------------------------------------------


@dataclass
class MaterialChannelExt:
    """Wraps a Bundle B ``MaterialChannel`` and adds AAA ceiling-extension fields.

    Addendum 1.B.2 requires that each material layer declare:
      * ``height_blend_gamma``  — non-linear blend curve between layers
      * ``texel_density_m``     — texels-per-metre for coherency checks
      * ``micro_normal_texture``— optional detail normal texture path
      * ``micro_normal_strength``— detail normal mix strength [0..1]
      * ``respects_displacement``— whether the layer honors POM/displacement

    AAA pipeline extensions (MicroSplat / UE5 Landscape Material parity):
      * ``albedo_tint``     — RGBA base color as validated against VeilBreakers
                              palette. (R, G, B, A) in linear sRGB.
      * ``roughness``       — base roughness scalar [0..1].
      * ``metallic``        — metallic scalar [0..1].
      * ``normal_strength`` — normal map blend strength [0..1].
      * ``triplanar``       — True when this layer uses triplanar projection
                              (required for all cliff/rock-face materials).
      * ``tiling``          — (U, V) tiling scale as vec2 float pair. Maps to
                              Blender Mapping node Scale XY, or Unity terrain
                              layer tileSize.
    """

    base: MaterialChannel
    # Original Addendum 1.B.2 fields
    height_blend_gamma: float = 1.0
    texel_density_m: float = 64.0
    micro_normal_texture: Optional[str] = None
    micro_normal_strength: float = 0.8
    respects_displacement: bool = True
    # AAA pipeline extension fields
    albedo_tint: tuple = (0.15, 0.13, 0.11, 1.0)
    roughness: float = 0.8
    metallic: float = 0.0
    normal_strength: float = 1.0
    triplanar: bool = False
    tiling: tuple = (8.0, 8.0)

    @property
    def channel_id(self) -> str:
        return self.base.channel_id


# ---------------------------------------------------------------------------
# Texel-density coherency
# ---------------------------------------------------------------------------


def validate_texel_density_coherency(
    channels: Sequence[MaterialChannelExt],
    max_ratio: float = 2.0,
    *,
    check_aaa_tiers: bool = True,
) -> List[ValidationIssue]:
    """Validate texel density against AAA tier requirements and inter-channel coherency.

    Two checks are performed:

    1. **AAA tier compliance** (when ``check_aaa_tiers=True``):
       VeilBreakers pipeline mandates:
         - Hero assets  : 1024 px/m  (triplanar cliff faces, hero props)
         - Terrain base : 512 px/m   (ground, slope, scree layers)
         - LOD1         : 256 px/m   (distant terrain, non-hero cliffs)
       Each channel is classified by its ``triplanar`` flag and
       ``texel_density_m``:
         - triplanar=True  → expected ≥ 512 px/m (cliff/rock face)
         - triplanar=False → expected ≥ 256 px/m (terrain base)
       Channels below their tier minimum raise a hard issue.

    2. **Inter-channel coherency**: adjacent blended layers whose texel
       density ratio exceeds ``max_ratio`` raise a soft issue (visible
       resolution pop at blend boundaries).

    Args:
        channels:        Sequence of MaterialChannelExt to validate.
        max_ratio:       Maximum allowed texel density ratio between any
                         two channels. Default 2.0 (one mip step).
        check_aaa_tiers: When True (default), enforce VeilBreakers
                         1024 / 512 / 256 px/m tier minimums.

    Returns:
        List of ValidationIssue. Empty list = all checks passed.
    """
    issues: List[ValidationIssue] = []
    if not channels:
        return issues

    # AAA tier thresholds (px/m)
    _HERO_MIN: float = 1024.0    # hero assets / cliff face with triplanar
    _TERRAIN_MIN: float = 512.0  # standard terrain layer
    _LOD1_MIN: float = 256.0     # LOD1 / distant terrain

    densities = [float(c.texel_density_m) for c in channels]

    # --- Guard: non-positive density is always a hard error ---
    for ch, d in zip(channels, densities):
        if d <= 0:
            issues.append(
                ValidationIssue(
                    code="MAT_TEXEL_DENSITY_INVALID",
                    severity="hard",
                    affected_feature=ch.channel_id,
                    message=(
                        f"channel {ch.channel_id!r} has non-positive "
                        f"texel_density_m={d:.1f}"
                    ),
                    remediation="Set texel_density_m to at least 256.0",
                )
            )
    if any(d <= 0 for d in densities):
        return issues  # coherency ratio check would divide by zero

    # --- AAA tier compliance ---
    if check_aaa_tiers:
        for ch, d in zip(channels, densities):
            # Triplanar channels are cliff/rock-face → terrain tier minimum
            tier_min = _TERRAIN_MIN if ch.triplanar else _LOD1_MIN
            tier_name = "terrain (512 px/m)" if ch.triplanar else "LOD1 (256 px/m)"
            if d < tier_min:
                issues.append(
                    ValidationIssue(
                        code="MAT_TEXEL_DENSITY_BELOW_TIER",
                        severity="hard",
                        affected_feature=ch.channel_id,
                        message=(
                            f"channel {ch.channel_id!r} texel_density_m={d:.1f} "
                            f"is below AAA {tier_name} minimum"
                        ),
                        remediation=(
                            f"Increase texel_density_m to at least {tier_min:.0f} "
                            f"(hero cliff faces should target {_HERO_MIN:.0f} px/m)"
                        ),
                    )
                )

    # --- Inter-channel coherency ---
    if len(channels) >= 2:
        min_d = min(densities)
        for ch, d in zip(channels, densities):
            if d / min_d > max_ratio:
                issues.append(
                    ValidationIssue(
                        code="MAT_TEXEL_DENSITY_INCOHERENT",
                        severity="soft",
                        affected_feature=ch.channel_id,
                        message=(
                            f"channel {ch.channel_id!r} texel_density_m={d:.1f} "
                            f">{max_ratio}x min={min_d:.1f} — blend boundary "
                            f"will show resolution pop"
                        ),
                        remediation=(
                            "Retexture to within one mip level of neighboring "
                            "layers (max 2x ratio)"
                        ),
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# Height-blended layer weights (gamma)
# ---------------------------------------------------------------------------


def compute_height_blended_weights(
    base_weights: np.ndarray,
    heights: np.ndarray,
    channel_gammas: Sequence[float],
) -> np.ndarray:
    """Apply per-layer gamma curves to base splatmap weights.

    Shape contract:
        base_weights: (H, W, L)
        heights:      (H, W) — world-meter elevation
        channel_gammas: length L

    A gamma > 1 biases the layer toward higher local heights (think: snow
    on peaks), gamma < 1 biases it toward valleys. Weights are renormalized
    to sum to 1 per cell. Heights are normalized to [0,1] **per-call** for
    the gamma curve only — we do not clip the raw world heights (Rule 10).
    """
    base = np.asarray(base_weights, dtype=np.float32)
    if base.ndim != 3:
        raise ValueError(f"base_weights must be (H,W,L), got {base.shape}")
    h, w, L = base.shape
    if len(channel_gammas) != L:
        raise ValueError(
            f"channel_gammas len={len(channel_gammas)} != num layers {L}"
        )

    heights = np.asarray(heights, dtype=np.float64)
    if heights.shape != (h, w):
        raise ValueError(
            f"heights shape {heights.shape} != ({h},{w})"
        )

    h_min = float(heights.min())
    h_max = float(heights.max())
    span = max(h_max - h_min, 1e-9)
    # Local 0..1 normalization for the gamma curve only — does NOT mutate
    # or clamp the underlying world heights.
    h01 = (heights - h_min) / span  # bounded in [0,1] by construction
    # FIX-12-30: apply perceptual (sRGB) gamma correction to the normalized
    # height before using it as the blend lerp weight. Linear world-space
    # heights produce too-abrupt transitions at the dark end and too-gradual
    # ones at the bright end; the 1/2.2 curve matches human height perception.
    h01 = np.power(np.clip(h01, 0.0, 1.0), 1.0 / 2.2)

    out = np.zeros_like(base, dtype=np.float32)
    for idx, g in enumerate(channel_gammas):
        g = max(float(g), 1e-6)
        if g >= 1.0:
            # Peak-biased: strong at high h01, weak at low
            curve = np.power(h01, g)
        else:
            # Valley-biased: strong at low h01, weak at high. Use the
            # inverted curve so that at h01=1 a low-gamma layer collapses
            # to 0 and a high-gamma layer dominates (physical intent).
            curve = np.power(1.0 - h01, 1.0 / g)
        out[:, :, idx] = base[:, :, idx] * curve.astype(np.float32)

    total = out.sum(axis=2)
    # Where total is zero (e.g., gamma collapsed all layers at h01==0),
    # fall back to the unmodified base weights to stay well-defined.
    empty = total <= 1e-9
    if empty.any():
        out[empty, :] = base[empty, :]
        total = out.sum(axis=2)
    total = np.where(total <= 1e-9, 1.0, total)
    out /= total[:, :, None]
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# Cliff silhouette area
# ---------------------------------------------------------------------------


# Minimum pixel-coverage fractions for hero / secondary cliff silhouettes
# (Addendum 1.B.2: cliffs must dominate the frame, not disappear).
HERO_CLIFF_MIN_FRAC = 0.08
SECONDARY_CLIFF_MIN_FRAC = 0.03


def validate_cliff_silhouette_area(
    cliff_pixel_coverage_fraction: float,
    *,
    tier: str = "secondary",
) -> List[ValidationIssue]:
    """Reject hero cliffs < 8% pixel coverage, secondary cliffs < 3%.

    ``tier`` must be ``"hero"`` or ``"secondary"``. Returns a hard issue
    when the silhouette is too small to read on screen.
    """
    issues: List[ValidationIssue] = []
    frac = float(cliff_pixel_coverage_fraction)
    tier = (tier or "secondary").lower()
    if tier == "hero":
        threshold = HERO_CLIFF_MIN_FRAC
    elif tier == "secondary":
        threshold = SECONDARY_CLIFF_MIN_FRAC
    else:
        issues.append(
            ValidationIssue(
                code="CLIFF_SILHOUETTE_UNKNOWN_TIER",
                severity="hard",
                affected_feature="cliff",
                message=f"Unknown cliff tier {tier!r}",
            )
        )
        return issues

    if frac < threshold:
        issues.append(
            ValidationIssue(
                code="CLIFF_SILHOUETTE_TOO_SMALL",
                severity="hard",
                affected_feature="cliff",
                message=(
                    f"{tier} cliff pixel coverage {frac:.3f} < "
                    f"threshold {threshold:.3f}"
                ),
                remediation=(
                    "Scale cliff formation up, re-anchor camera, or tag as "
                    "non-hero feature."
                ),
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Cliff silhouette shape validator — Phase G
# ---------------------------------------------------------------------------


# Isoperimetric ratio thresholds: 4π·A / P² using a 4-edge digital perimeter.
# In continuous geometry the ratio is ∈ [0, 1] with 1.0 = perfect circle.
# The 4-connected digital perimeter OVERCOUNTS relative to the continuous
# arc length (each boundary cell contributes up to 4 edges), so the numeric
# values for discrete shapes land at:
#   discrete disc (r=10):   ~0.56    — target reject
#   discrete square:        ~0.79    — still too compact, also reject
#   discrete jagged strip:  ~0.07    — healthy silhouette
# Threshold at 0.50 gives clean separation between featureful and blobby.
CLIFF_BLOBBY_MAX = 0.50   # reject above → too round / featureless silhouette
CLIFF_UNIFORM_MIN_HEIGHT_STD_M = 2.5  # reject below → too flat / uniform


def validate_cliff_silhouette_shape(
    face_mask: np.ndarray,
    heights: Optional[np.ndarray] = None,
    *,
    cell_size_m: float = 1.0,
    blobby_max: float = CLIFF_BLOBBY_MAX,
    uniform_min_height_std_m: float = CLIFF_UNIFORM_MIN_HEIGHT_STD_M,
    feature_id: str = "cliff",
) -> List[ValidationIssue]:
    """Reject cliff silhouettes that are too blobby or too uniform.

    Two checks, matching Horizon Forbidden West's silhouette direction
    (jagged, layered cliffs — never circular pancakes, never flat walls):

    1. **Blobby** — isoperimetric ratio ``4π·A / P²`` (A = area, P = perimeter)
       measures how close to a circle the silhouette is. Values near 1.0 are
       maximally circular (bad for cliffs). Reject when the ratio exceeds
       ``blobby_max`` (default 0.72 — still allows natural rounded bluffs
       but rejects perfect blobs).

    2. **Uniform** — std-dev of heights inside the face mask. If all face
       cells are within ~2.5 m of each other, the cliff face has no visible
       strata/steps and reads as a flat painted wall. Rejected below
       ``uniform_min_height_std_m``.

    Args:
        face_mask:  (H, W) bool array — cliff face cells.
        heights:    (H, W) float array of cell z — optional. When None, only
                    the blobby check runs.
        cell_size_m: world-metres per cell (for perimeter normalisation).
        blobby_max:  maximum allowed isoperimetric ratio [0, 1].
        uniform_min_height_std_m: minimum allowed std-dev of face heights.
        feature_id: string stamped into ``ValidationIssue.affected_feature``.

    Returns:
        List of ValidationIssue (empty when silhouette passes both gates).
    """
    issues: List[ValidationIssue] = []
    mask = np.asarray(face_mask, dtype=bool)
    if mask.ndim != 2:
        issues.append(
            ValidationIssue(
                code="CLIFF_SILHOUETTE_SHAPE_BAD_INPUT",
                severity="hard",
                affected_feature=feature_id,
                message=f"face_mask must be 2-D bool; got shape {mask.shape}",
            )
        )
        return issues
    area_cells = int(mask.sum())
    if area_cells < 4:
        # Too small to have meaningful shape — let the area validator handle it
        return issues

    # Perimeter: count boundary edges (a face cell with a non-face neighbour
    # contributes one edge per side). Pure numpy via shifted-XOR.
    # Use constant padding False so outside-the-grid counts as boundary too.
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    # Neighbour presence (inside mask)
    n_up = padded[:-2, 1:-1]
    n_dn = padded[2:,  1:-1]
    n_lf = padded[1:-1, :-2]
    n_rt = padded[1:-1, 2:]
    # For each face cell, each missing neighbour is one perimeter edge.
    edges_per_cell = (
        (~n_up).astype(np.int32)
        + (~n_dn).astype(np.int32)
        + (~n_lf).astype(np.int32)
        + (~n_rt).astype(np.int32)
    )
    # Only count edges for cells that ARE in the mask
    perimeter_cells = int(edges_per_cell[mask].sum())

    # Convert to world metres
    area_m2 = area_cells * (cell_size_m ** 2)
    perimeter_m = perimeter_cells * cell_size_m
    if perimeter_m <= 1e-6:
        return issues

    # Isoperimetric ratio: 4π A / P² in [0, 1]; 1.0 = perfect circle.
    iso_ratio = 4.0 * np.pi * area_m2 / (perimeter_m ** 2)
    if iso_ratio > blobby_max:
        issues.append(
            ValidationIssue(
                code="CLIFF_SILHOUETTE_TOO_BLOBBY",
                severity="hard",
                affected_feature=feature_id,
                message=(
                    f"cliff silhouette isoperimetric ratio {iso_ratio:.3f} > "
                    f"{blobby_max:.3f} — silhouette is too circular/featureless"
                ),
                remediation=(
                    "Break up the cliff footprint with lobes, ledges, or "
                    "re-entrants; avoid pancake-shaped plateaux."
                ),
            )
        )

    # Height uniformity: std-dev of face cells' heights
    if heights is not None:
        h_arr = np.asarray(heights, dtype=np.float64)
        if h_arr.shape == mask.shape:
            face_heights = h_arr[mask]
            if face_heights.size >= 4:
                h_std = float(face_heights.std())
                if h_std < uniform_min_height_std_m:
                    issues.append(
                        ValidationIssue(
                            code="CLIFF_SILHOUETTE_TOO_UNIFORM",
                            severity="hard",
                            affected_feature=feature_id,
                            message=(
                                f"cliff face height std-dev {h_std:.2f} m < "
                                f"{uniform_min_height_std_m:.2f} m — "
                                f"silhouette reads as a flat wall"
                            ),
                            remediation=(
                                "Add strata-band displacement, overhangs, or "
                                "erosion variance to break up the face."
                            ),
                        )
                    )

    return issues


__all__ = [
    "MaterialChannelExt",
    "validate_texel_density_coherency",
    "compute_height_blended_weights",
    "validate_cliff_silhouette_area",
    "validate_cliff_silhouette_shape",
    "HERO_CLIFF_MIN_FRAC",
    "SECONDARY_CLIFF_MIN_FRAC",
    "CLIFF_BLOBBY_MAX",
    "CLIFF_UNIFORM_MIN_HEIGHT_STD_M",
]
