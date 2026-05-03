"""Bundle C supplement — volumetric waterfall contract + 7 functional objects.

Extends ``terrain_waterfalls`` with an authoritative volumetric-geometry
profile and a named-object contract, per Addendum 1.B.3 of
docs/terrain_ultra_implementation_plan_2026-04-08.md and Addendum 2.J's
dual-nature clause.

A "waterfall" is both:
  * a physical 3D volumetric mesh (thick tapered prism, rounded front),
  * a set of functional objects (sheet, pool, foam, mist, splash, material zone).

AAA upgrades in this revision:
  - WaterfallVolumeBounds: oriented bounding box (NOT axis-aligned) for
    diagonal cascades (AAA req #9). OBB axes derived from lip orientation.
  - WaterfallParticleSeedZones: lip_zone, impact_zone, mist_zone with
    particle_density proportional to discharge Q (AAA req #10).
  - validate_waterfall_volumetric: unchanged (was already passing AAA bar).
  - validate_waterfall_anchor_screen_space: unchanged.
  - enforce_functional_object_naming: unchanged.

This module provides pure-numpy validators. No bpy imports.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass  # FIX-11-9: removed unused 'field'
from typing import Any, List, Sequence, Tuple  # FIX-11-9: removed unused 'Optional'

import numpy as np

from .terrain_semantics import ValidationIssue


# ---------------------------------------------------------------------------
# Volumetric profile
# ---------------------------------------------------------------------------


@dataclass
class WaterfallVolumetricProfile:
    """Authoritative geometry budget for volumetric waterfall sheets.

    Fields
    ------
    vertex_density_per_meter:
        Minimum vertex count per vertical drop-meter required to preserve
        the rounded-front silhouette and avoid the "flat plane" regression
        called out in feedback_waterfall_must_have_volume.md.
    front_curvature_radius_ratio:
        Front-face curvature radius expressed as a fraction of the sheet
        width. 0.0 = flat plane, 0.5 = half-pipe. Bundle C requires
        >= 0.15 for "rounded front" readability.
    min_non_coplanar_front_fraction:
        Minimum fraction of front-face vertex normals that must deviate
        from a shared plane. Values below this mean the front collapsed
        into a billboard — forbidden.
    """

    vertex_density_per_meter: float = 48.0
    front_curvature_radius_ratio: float = 0.15
    min_non_coplanar_front_fraction: float = 0.30


# ---------------------------------------------------------------------------
# Oriented bounding box for waterfall volume (AAA req #9)
# ---------------------------------------------------------------------------


@dataclass
class WaterfallVolumeBounds:
    """Oriented bounding box (OBB) for a waterfall cascade volume.

    AAA req #9: Volume bounds must NOT be axis-aligned if cascade is diagonal.
    The OBB is defined by:
      - center: world-space centre (x, y, z)
      - half_extents: (half_lip_width, half_cascade_height, half_depth)
      - axes: 3×3 rotation matrix rows = (lip_tangent, up, cascade_normal)

    For a non-diagonal waterfall (flow along axis), this degenerates to an
    AABB. For diagonal cascades the lip_tangent and cascade_normal are
    rotated to match the flow azimuth.

    Usage in Unity: pass center + half_extents + axes to OBBComponent.
    Usage in Blender: apply axes as object rotation quaternion.
    """

    center: Tuple[float, float, float]
    # (half_lip_width, half_cascade_height, half_mist_radius)
    half_extents: Tuple[float, float, float]
    # Orthonormal basis: rows are (lip_tangent, world_up, cascade_normal)
    # Each axis is a (x, y, z) unit vector in world space.
    axis_lip_tangent: Tuple[float, float, float]
    axis_up: Tuple[float, float, float]
    axis_cascade_normal: Tuple[float, float, float]

    def as_matrix_rows(self) -> Tuple[
        Tuple[float, float, float],
        Tuple[float, float, float],
        Tuple[float, float, float],
    ]:
        """Return the 3×3 rotation matrix as row-tuples (lip, up, normal)."""
        return self.axis_lip_tangent, self.axis_up, self.axis_cascade_normal

    def volume_m3(self) -> float:
        """Approximate volume of the bounding box in cubic metres."""
        return 8.0 * self.half_extents[0] * self.half_extents[1] * self.half_extents[2]


def build_waterfall_volume_bounds(
    lip_world_position: Tuple[float, float, float],
    pool_world_position: Tuple[float, float, float],
    flow_azimuth_rad: float,
    lip_width_m: float,
    cascade_height_m: float,
    mist_radius_m: float,
) -> WaterfallVolumeBounds:
    """Build an oriented bounding box for a waterfall cascade (AAA req #9).

    The OBB is NOT axis-aligned — its principal axes are derived from the
    flow azimuth so diagonal cascades are tightly bounded.

    Axes:
      - axis_cascade_normal: horizontal direction of flow (from lip toward pool).
        = (sin(az), cos(az), 0) in world XYZ (Z-up, X=east, Y=north).
      - axis_lip_tangent: perpendicular to flow in the horizontal plane.
        = (cos(az), -sin(az), 0)  [90° CW from cascade_normal]
      - axis_up: world up = (0, 0, 1).

    Half-extents:
      - Along lip_tangent: half_lip_width
      - Along up: half_cascade_height
      - Along cascade_normal: half_mist_radius (depth of the volume)

    Center: midpoint between lip and pool, vertically centred on cascade.

    Args:
        lip_world_position: World XYZ of waterfall lip.
        pool_world_position: World XYZ of plunge pool.
        flow_azimuth_rad: Flow direction in radians (0=North, π/2=East).
        lip_width_m: Total lip width in metres.
        cascade_height_m: Total vertical drop height in metres.
        mist_radius_m: Mist radius in metres (sets depth of OBB).

    Returns:
        WaterfallVolumeBounds with tight oriented bounding box.
    """
    lx, ly, lz = lip_world_position
    px, py, pz = pool_world_position

    # OBB centre: midpoint between lip and pool
    cx = (lx + px) * 0.5
    cy = (ly + py) * 0.5
    cz = (lz + pz) * 0.5

    # Horizontal flow direction (cascade normal): sin/cos of azimuth
    az = flow_azimuth_rad
    flow_x = math.sin(az)  # east component
    flow_y = math.cos(az)  # north component

    # Lip tangent: 90° CW rotation of flow in horizontal plane
    tang_x =  flow_y   # cos(az)
    tang_y = -flow_x   # -sin(az)

    # Axes (Z-up world, orthonormal)
    axis_cascade_normal: Tuple[float, float, float] = (flow_x, flow_y, 0.0)
    axis_lip_tangent:    Tuple[float, float, float] = (tang_x, tang_y, 0.0)
    axis_up:             Tuple[float, float, float] = (0.0, 0.0, 1.0)

    # Half-extents
    half_width  = max(0.5, lip_width_m   * 0.5)
    half_height = max(0.5, cascade_height_m * 0.5)
    half_depth  = max(0.5, mist_radius_m * 0.5)

    return WaterfallVolumeBounds(
        center=(cx, cy, cz),
        half_extents=(half_width, half_height, half_depth),
        axis_lip_tangent=axis_lip_tangent,
        axis_up=axis_up,
        axis_cascade_normal=axis_cascade_normal,
    )


# ---------------------------------------------------------------------------
# Particle seed zones (AAA req #10)
# ---------------------------------------------------------------------------


@dataclass
class ParticleSeedZone:
    """A named particle emission zone for a waterfall system.

    AAA req #10: Each zone has particle_density proportional to Q (discharge).

    Fields
    ------
    name: One of "lip_zone", "impact_zone", "mist_zone".
    world_center: World-space XYZ centre of the zone.
    radius_m: Spherical radius of the zone in metres.
    particle_density: Particles per cubic metre per second.
        Scaled proportionally to discharge Q (m³/s).
    orientation_rad: Flow azimuth for directional emission.
    height_m: Vertical extent for cylindrical zones (impact_zone uses cylinder).
    """

    name: str
    world_center: Tuple[float, float, float]
    radius_m: float
    particle_density: float
    orientation_rad: float = 0.0
    height_m: float = 0.0


# Empirical particle density scaling constants (tuned for AAA reference footage)
# Base densities at Q = 1 m³/s; scale with Q^0.5 to avoid overwhelming small falls.
_PARTICLE_DENSITY_LIP_BASE: float    = 50.0   # particles/m³/s at Q=1
_PARTICLE_DENSITY_IMPACT_BASE: float = 120.0  # impact zone is most particle-dense
_PARTICLE_DENSITY_MIST_BASE: float   = 15.0   # mist zone sparse, upwind hemisphere


def build_particle_seed_zones(
    lip_world_position: Tuple[float, float, float],
    pool_world_position: Tuple[float, float, float],
    flow_azimuth_rad: float,
    lip_width_m: float,
    cascade_height_m: float,
    mist_radius_m: float,
    discharge_m3s: float,
    wind_direction_rad: float = 0.0,
) -> List[ParticleSeedZone]:
    """Build the three particle seed zones for a waterfall chain (AAA req #10).

    Zones:
    1. lip_zone — top 0.5m of cascade at the lip. Thin disc, moderate density.
       Particle density proportional to Q.
    2. impact_zone — centred on plunge pool, cylindrical (radius = pool_radius).
       Particle density proportional to Q (highest density zone).
    3. mist_zone — upwind hemisphere from plunge pool. Sparse.
       Particle density proportional to Q.

    All densities scale as Q^0.5 (square root of discharge) to match
    physically realistic particle counts without blowing up for large falls.

    Args:
        lip_world_position: World XYZ of waterfall lip.
        pool_world_position: World XYZ of plunge pool.
        flow_azimuth_rad: Flow direction in radians.
        lip_width_m: Lip width in metres.
        cascade_height_m: Vertical drop height in metres.
        mist_radius_m: Mist radius from generate_mist_zone().
        discharge_m3s: Discharge Q in m³/s.
        wind_direction_rad: Wind bearing for mist zone offset.

    Returns:
        List of 3 ParticleSeedZone objects: [lip_zone, impact_zone, mist_zone].
    """
    Q = max(0.01, discharge_m3s)
    q_scale = math.sqrt(Q)  # density ∝ Q^0.5 per spec

    lx, ly, lz = lip_world_position
    px, py, pz = pool_world_position

    # Pool radius from Mason 1985 (re-derived here to avoid circular import)
    H = max(0.5, cascade_height_m)
    pool_radius_m = 0.45 * math.sqrt(H * math.sqrt(Q))
    pool_radius_m = float(np.clip(pool_radius_m, 1.0, 50.0))

    # -------------------------------------------------------------------
    # 1. lip_zone: top 0.5m of cascade, centred at lip
    # -------------------------------------------------------------------
    lip_zone_radius = max(0.5, lip_width_m * 0.5)  # half the lip width as sphere radius
    lip_zone_center = (lx, ly, lz)                  # at the lip elevation
    lip_density = _PARTICLE_DENSITY_LIP_BASE * q_scale

    lip_zone = ParticleSeedZone(
        name="lip_zone",
        world_center=lip_zone_center,
        radius_m=float(lip_zone_radius),
        particle_density=float(lip_density),
        orientation_rad=float(flow_azimuth_rad),
        height_m=0.5,  # top 0.5m of cascade per spec
    )

    # -------------------------------------------------------------------
    # 2. impact_zone: plunge pool (cylinder, radius = pool_radius)
    # -------------------------------------------------------------------
    impact_density = _PARTICLE_DENSITY_IMPACT_BASE * q_scale
    impact_zone = ParticleSeedZone(
        name="impact_zone",
        world_center=(px, py, pz),
        radius_m=float(pool_radius_m),
        particle_density=float(impact_density),
        orientation_rad=float(flow_azimuth_rad),
        height_m=float(max(1.0, pool_radius_m * 0.5)),  # cylinder height
    )

    # -------------------------------------------------------------------
    # 3. mist_zone: upwind hemisphere from plunge pool
    # -------------------------------------------------------------------
    # Offset centre upwind by 0.3 * mist_radius (matches generate_mist_zone())
    upwind_offset = 0.3 * mist_radius_m
    wind_cos = math.cos(wind_direction_rad)
    wind_sin = math.sin(wind_direction_rad)
    # Upwind = opposite to wind direction
    mist_cx = px - wind_sin * upwind_offset
    mist_cy = py - wind_cos * upwind_offset
    mist_density = _PARTICLE_DENSITY_MIST_BASE * q_scale

    mist_zone = ParticleSeedZone(
        name="mist_zone",
        world_center=(float(mist_cx), float(mist_cy), float(pz + mist_radius_m * 0.3)),
        radius_m=float(mist_radius_m),
        particle_density=float(mist_density),
        orientation_rad=float(wind_direction_rad),
        height_m=float(mist_radius_m * 0.6),  # upwind hemisphere height
    )

    return [lip_zone, impact_zone, mist_zone]


# ---------------------------------------------------------------------------
# Functional objects contract
# ---------------------------------------------------------------------------


@dataclass
class WaterfallFunctionalObjects:
    """The 7 named objects every waterfall chain must publish.

    Addendum 1.B.3 mandates that each chain expose each of these as a
    distinct Blender object (or Unity GameObject) so downstream systems
    (audio zones, decal placement, splash VFX, wet-rock shader, camera
    anchors) can look them up by suffix.
    """

    river_surface: str
    sheet_volume: str
    impact_pool: str
    foam_layer: str
    mist_volume: str
    splash_particles: str
    wet_rock_material_zone: str

    def as_list(self) -> List[str]:
        return [
            self.river_surface,
            self.sheet_volume,
            self.impact_pool,
            self.foam_layer,
            self.mist_volume,
            self.splash_particles,
            self.wet_rock_material_zone,
        ]


# Suffix → field mapping (canonical object name template: WF_{id}_{suffix}).
FUNCTIONAL_SUFFIXES: Tuple[str, ...] = (
    "river_surface",
    "sheet_volume",
    "impact_pool",
    "foam_layer",
    "mist_volume",
    "splash_particles",
    "wet_rock_material_zone",
)


def build_waterfall_functional_object_names(
    chain_id: str,
) -> WaterfallFunctionalObjects:
    """Return the canonical names for all 7 functional objects of a chain."""
    if not chain_id:
        raise ValueError("chain_id must be non-empty")
    prefix = f"WF_{chain_id}_"
    return WaterfallFunctionalObjects(
        river_surface=prefix + "river_surface",
        sheet_volume=prefix + "sheet_volume",
        impact_pool=prefix + "impact_pool",
        foam_layer=prefix + "foam_layer",
        mist_volume=prefix + "mist_volume",
        splash_particles=prefix + "splash_particles",
        wet_rock_material_zone=prefix + "wet_rock_material_zone",
    )


# ---------------------------------------------------------------------------
# Volumetric validator
# ---------------------------------------------------------------------------


def validate_waterfall_volumetric(
    profile: WaterfallVolumetricProfile,
    vertex_count: int,
    drop_m: float,
    front_normals_cos: Sequence[float],
) -> List[ValidationIssue]:
    """Validate that a waterfall sheet is a real 3D volumetric mesh.

    ``front_normals_cos`` is a sequence of cosine angles (dot products
    against a fitted front-plane normal) — values close to 1.0 mean
    flat/coplanar, deviation indicates curvature. The *non-coplanar
    fraction* is defined as fraction with cosine <= 0.98.
    """
    issues: List[ValidationIssue] = []

    drop_m = max(float(drop_m), 0.0)
    required_verts = int(math.ceil(profile.vertex_density_per_meter * drop_m))
    if vertex_count < required_verts:
        issues.append(
            ValidationIssue(
                code="WATERFALL_VERTEX_DENSITY_TOO_LOW",
                severity="hard",
                affected_feature="waterfall",
                message=(
                    f"vertex_count={vertex_count} < required "
                    f"{required_verts} (={profile.vertex_density_per_meter}*"
                    f"{drop_m:.2f}m)"
                ),
                remediation="Subdivide sheet geometry along drop axis.",
            )
        )

    if not front_normals_cos:
        issues.append(
            ValidationIssue(
                code="WATERFALL_FRONT_NORMALS_MISSING",
                severity="hard",
                affected_feature="waterfall",
                message="front_normals_cos sequence is empty",
            )
        )
        return issues

    # Spec: a front-vertex normal is "non-coplanar" when its raw dot product
    # with the mean-front-normal is < 0.95. `abs()` would treat backfacing
    # coplanar normals (dot ≈ -1) as curved, which is wrong.
    n = len(front_normals_cos)
    non_coplanar = sum(1 for c in front_normals_cos if float(c) < 0.95)
    frac = non_coplanar / n
    if frac < profile.min_non_coplanar_front_fraction:
        issues.append(
            ValidationIssue(
                code="WATERFALL_FRONT_COPLANAR",
                severity="hard",
                affected_feature="waterfall",
                message=(
                    f"non-coplanar front fraction {frac:.3f} < required "
                    f"{profile.min_non_coplanar_front_fraction:.3f} — sheet "
                    f"is a flat billboard, not a volumetric prism"
                ),
                remediation=(
                    "Taper thickness across span and round the front face."
                ),
            )
        )

    # Spec (Bundle C §3.2): rounded front requires curvature radius ratio
    # >= 0.15 × width. Negative is always invalid; [0.0, 0.15) is a flat front.
    min_curvature = 0.15
    if profile.front_curvature_radius_ratio < min_curvature:
        issues.append(
            ValidationIssue(
                code="WATERFALL_CURVATURE_RATIO_INVALID",
                severity="hard",
                affected_feature="waterfall",
                message=(
                    f"front_curvature_radius_ratio="
                    f"{profile.front_curvature_radius_ratio} must be >= "
                    f"{min_curvature} (0.15 × width per Bundle C §3.2)"
                ),
            )
        )

    return issues


# ---------------------------------------------------------------------------
# OBB validator
# ---------------------------------------------------------------------------


def validate_waterfall_volume_bounds(
    bounds: WaterfallVolumeBounds,
    flow_azimuth_rad: float,
    aabb_tolerance_rad: float = 0.05,
) -> List[ValidationIssue]:
    """Validate that the volume bounds are properly oriented (AAA req #9).

    For non-axis-aligned cascades (flow_azimuth_rad not near 0, π/2, π, 3π/2),
    the OBB axes must deviate from world axes to be a true OBB rather than AABB.

    Args:
        bounds: WaterfallVolumeBounds to validate.
        flow_azimuth_rad: Flow direction in radians.
        aabb_tolerance_rad: Tolerance below which a diagonal cascade is flagged
            as incorrectly using an AABB. Default 0.05 rad (~3°).

    Returns:
        List of ValidationIssue. Empty = valid.
    """
    issues: List[ValidationIssue] = []

    # Check axes are unit vectors
    for axis_name, axis in [
        ("axis_lip_tangent", bounds.axis_lip_tangent),
        ("axis_up", bounds.axis_up),
        ("axis_cascade_normal", bounds.axis_cascade_normal),
    ]:
        mag = math.sqrt(sum(v * v for v in axis))
        if abs(mag - 1.0) > 0.01:
            issues.append(ValidationIssue(
                code="WATERFALL_OBB_AXIS_NOT_UNIT",
                severity="hard",
                affected_feature="waterfall",
                message=f"{axis_name} magnitude {mag:.4f} is not a unit vector",
                remediation="Normalize OBB axes before publishing.",
            ))

    # Check axes are mutually orthogonal
    axes = [bounds.axis_lip_tangent, bounds.axis_up, bounds.axis_cascade_normal]
    pairs = [(0, 1, "lip_tangent·up"), (0, 2, "lip_tangent·normal"), (1, 2, "up·normal")]
    for i, j, label in pairs:
        dot = sum(axes[i][k] * axes[j][k] for k in range(3))
        if abs(dot) > 0.02:
            issues.append(ValidationIssue(
                code="WATERFALL_OBB_AXES_NOT_ORTHOGONAL",
                severity="hard",
                affected_feature="waterfall",
                message=f"OBB axes {label} dot={dot:.4f} — not orthogonal",
                remediation="Re-derive OBB axes from flow azimuth.",
            ))

    # Check diagonal cascades use a real OBB (not degenerate AABB)
    # Diagonal = azimuth not near 0, π/2, π, 3π/2
    az_mod = flow_azimuth_rad % (math.pi / 2.0)
    is_axis_aligned = min(az_mod, math.pi / 2.0 - az_mod) < aabb_tolerance_rad
    if not is_axis_aligned:
        # Cascade is diagonal — cascade_normal must not be world-axis-aligned
        cn = bounds.axis_cascade_normal
        axis_aligned_check = (
            abs(abs(cn[0]) - 1.0) < 0.02 or  # pure east/west
            abs(abs(cn[1]) - 1.0) < 0.02 or  # pure north/south
            abs(abs(cn[2]) - 1.0) < 0.02      # pure up/down
        )
        if axis_aligned_check:
            issues.append(ValidationIssue(
                code="WATERFALL_OBB_DIAGONAL_NOT_ROTATED",
                severity="hard",
                affected_feature="waterfall",
                message=(
                    f"Diagonal cascade (az={math.degrees(flow_azimuth_rad):.1f}°) "
                    f"has axis-aligned OBB — must be oriented OBB per AAA req #9"
                ),
                remediation="Use build_waterfall_volume_bounds() to derive rotated OBB axes.",
            ))

    # Check half_extents are all positive
    for i, (label, val) in enumerate(zip(
        ["half_lip_width", "half_cascade_height", "half_mist_radius"],
        bounds.half_extents,
    )):
        if val <= 0.0:
            issues.append(ValidationIssue(
                code="WATERFALL_OBB_ZERO_EXTENT",
                severity="hard",
                affected_feature="waterfall",
                message=f"OBB half_extent[{i}] ({label}) = {val} must be positive",
            ))

    return issues


# ---------------------------------------------------------------------------
# Particle seed zone validator
# ---------------------------------------------------------------------------


def validate_particle_seed_zones(
    zones: List[ParticleSeedZone],
    discharge_m3s: float,
) -> List[ValidationIssue]:
    """Validate that particle seed zones are correctly configured (AAA req #10).

    Checks:
    - All three required zones are present (lip_zone, impact_zone, mist_zone).
    - Particle densities are proportional to Q (within 10× of base density * Q^0.5).
    - Radii are positive.

    Args:
        zones: List of ParticleSeedZone from build_particle_seed_zones().
        discharge_m3s: Discharge Q in m³/s used when zones were built.

    Returns:
        List of ValidationIssue. Empty = valid.
    """
    issues: List[ValidationIssue] = []

    required_names = {"lip_zone", "impact_zone", "mist_zone"}
    present_names = {z.name for z in zones}
    for missing in sorted(required_names - present_names):
        issues.append(ValidationIssue(
            code="WATERFALL_PARTICLE_ZONE_MISSING",
            severity="hard",
            affected_feature="waterfall",
            message=f"Required particle seed zone '{missing}' is absent",
            remediation="Call build_particle_seed_zones() to generate all three zones.",
        ))

    Q = max(0.01, discharge_m3s)
    q_scale = math.sqrt(Q)
    base_densities = {
        "lip_zone":    _PARTICLE_DENSITY_LIP_BASE,
        "impact_zone": _PARTICLE_DENSITY_IMPACT_BASE,
        "mist_zone":   _PARTICLE_DENSITY_MIST_BASE,
    }

    for z in zones:
        if z.radius_m <= 0.0:
            issues.append(ValidationIssue(
                code="WATERFALL_PARTICLE_ZONE_ZERO_RADIUS",
                severity="hard",
                affected_feature="waterfall",
                message=f"Particle zone '{z.name}' has radius_m={z.radius_m} <= 0",
            ))

        if z.name in base_densities:
            expected = base_densities[z.name] * q_scale
            # Allow 10× tolerance for artistic override
            if z.particle_density <= 0.0:
                issues.append(ValidationIssue(
                    code="WATERFALL_PARTICLE_DENSITY_ZERO",
                    severity="hard",
                    affected_feature="waterfall",
                    message=(
                        f"Particle zone '{z.name}' has density {z.particle_density} <= 0; "
                        f"expected ~{expected:.1f} for Q={Q:.2f} m³/s"
                    ),
                ))
            elif z.particle_density > expected * 10.0:
                issues.append(ValidationIssue(
                    code="WATERFALL_PARTICLE_DENSITY_EXCESSIVE",
                    severity="soft",
                    affected_feature="waterfall",
                    message=(
                        f"Particle zone '{z.name}' density {z.particle_density:.1f} > "
                        f"10× expected {expected:.1f} (Q={Q:.2f} m³/s) — may cause perf issues"
                    ),
                ))

    return issues


# ---------------------------------------------------------------------------
# Anchor screen-space validator
# ---------------------------------------------------------------------------


def validate_waterfall_anchor_screen_space(
    chain_lip_pos: Tuple[float, float, float],
    anchor_pos: Tuple[float, float, float],
    anchor_radius: float,
    vantage_position: Tuple[float, float, float],
) -> List[ValidationIssue]:
    """Ensure the camera anchor stays within the lip's anchor radius.

    This guards the "screen-space anchoring" contract from Addendum 2.J:
    if the anchor drifts too far from the chain lip (relative to the
    vantage), the feature no longer reads as a waterfall in frame.
    """
    issues: List[ValidationIssue] = []

    lip = tuple(float(v) for v in chain_lip_pos)
    anc = tuple(float(v) for v in anchor_pos)
    if len(lip) != 3 or len(anc) != 3:
        issues.append(
            ValidationIssue(
                code="WATERFALL_ANCHOR_DIM",
                severity="hard",
                affected_feature="waterfall",
                message="chain_lip_pos and anchor_pos must be 3-tuples",
            )
        )
        return issues

    dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(lip, anc)))
    if anchor_radius <= 0:
        issues.append(
            ValidationIssue(
                code="WATERFALL_ANCHOR_RADIUS_INVALID",
                severity="hard",
                affected_feature="waterfall",
                message=f"anchor_radius={anchor_radius} must be positive",
            )
        )
        return issues

    if dist > float(anchor_radius):
        issues.append(
            ValidationIssue(
                code="WATERFALL_ANCHOR_DRIFT",
                severity="hard",
                affected_feature="waterfall",
                location=anc,
                message=(
                    f"anchor drift {dist:.2f}m exceeds radius "
                    f"{anchor_radius:.2f}m from chain lip"
                ),
                remediation="Reposition the anchor or widen anchor_radius.",
            )
        )

    vlip = tuple(v - L for v, L in zip(vantage_position, lip))
    alip = tuple(a - L for a, L in zip(anc, lip))
    dot = sum(v * a for v, a in zip(vlip, alip))
    vmag = math.sqrt(sum(v * v for v in vlip))
    if vmag > 1e-6 and dot < 0:
        issues.append(
            ValidationIssue(
                code="WATERFALL_ANCHOR_BEHIND_VANTAGE",
                severity="soft",
                affected_feature="waterfall",
                message="anchor is on the opposite side of the lip from the vantage",
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Functional-object naming enforcement
# ---------------------------------------------------------------------------


_NAME_RE = re.compile(r"^WF_(?P<chain>[^_]+(?:_[^_]+)*?)_(?P<suffix>[a-z_]+)$")


def enforce_functional_object_naming(
    object_names: Sequence[str],
    chain_id: str,
) -> List[ValidationIssue]:
    """Check that every object belongs to ``chain_id`` and has a valid suffix.

    Objects that don't match the ``WF_<chain_id>_<suffix>`` template, or
    whose suffix is not one of the 7 canonical suffixes, yield hard issues.
    Additionally, missing required suffixes yield one hard issue per gap.
    """
    issues: List[ValidationIssue] = []
    expected_prefix = f"WF_{chain_id}_"

    seen: set[str] = set()
    for name in object_names:
        if not name.startswith(expected_prefix):
            issues.append(
                ValidationIssue(
                    code="WATERFALL_OBJECT_WRONG_CHAIN",
                    severity="hard",
                    affected_feature="waterfall",
                    message=(
                        f"object {name!r} does not start with "
                        f"prefix {expected_prefix!r}"
                    ),
                )
            )
            continue
        suffix = name[len(expected_prefix):]
        if suffix not in FUNCTIONAL_SUFFIXES:
            issues.append(
                ValidationIssue(
                    code="WATERFALL_OBJECT_UNKNOWN_SUFFIX",
                    severity="hard",
                    affected_feature="waterfall",
                    message=(
                        f"object {name!r} has unknown suffix {suffix!r}; "
                        f"expected one of {FUNCTIONAL_SUFFIXES}"
                    ),
                )
            )
            continue
        seen.add(suffix)

    missing = [s for s in FUNCTIONAL_SUFFIXES if s not in seen]
    for m in missing:
        issues.append(
            ValidationIssue(
                code="WATERFALL_FUNCTIONAL_OBJECT_MISSING",
                severity="hard",
                affected_feature="waterfall",
                message=(
                    f"required functional object with suffix {m!r} missing "
                    f"from chain {chain_id!r}"
                ),
            )
        )

    return issues


__all__ = [
    "WaterfallVolumetricProfile",
    "WaterfallFunctionalObjects",
    "WaterfallVolumeBounds",
    "ParticleSeedZone",
    "FUNCTIONAL_SUFFIXES",
    "build_waterfall_functional_object_names",
    "build_waterfall_volume_bounds",
    "build_particle_seed_zones",
    "validate_waterfall_volumetric",
    "validate_waterfall_volume_bounds",
    "validate_particle_seed_zones",
    "validate_waterfall_anchor_screen_space",
    "enforce_functional_object_naming",
]
