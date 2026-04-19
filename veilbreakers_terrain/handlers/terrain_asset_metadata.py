"""Bundle E supplements — asset metadata taxonomy (Addendum 1.B.5).

Pure python / numpy. No bpy. Headless unit-testable.

Implements the full asset metadata tag taxonomy from master plan §15 plus
the ``AssetContextRuleExt`` extension fields (``scale_variance_by_role``,
``camera_priority_weight``) used by ``place_assets_by_zone`` scoring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .terrain_semantics import ValidationIssue


# ---------------------------------------------------------------------------
# Tag taxonomy (master plan §15, frozen constants)
# ---------------------------------------------------------------------------

LOCATION_TAGS: Tuple[str, ...] = (
    "cliff",
    "riverbank",
    "waterfall_base",
    "cave_entrance",
    "plateau",
    "forest_floor",
    "beach",
    "wetland",
    "alpine",
    "cultivated",
)

ROLE_TAGS: Tuple[str, ...] = ("hero", "support", "filler")

SIZE_TAGS: Tuple[str, ...] = ("large", "medium", "small")

CONTEXT_TAGS: Tuple[str, ...] = (
    "silhouette_critical",
    "foreground_only",
    "mid_distance",
    "background_fill",
)

COLLISION_TYPES: Tuple[str, ...] = (
    "none",      # no physics collision (grass cards, decals)
    "box",       # simple AABB box collider
    "capsule",   # capsule collider (trees, pillars, vertical cylinders)
    "convex",    # convex hull mesh collider (rocks, stumps, generic props)
    "mesh",      # full triangle-mesh collider (hero props, architecture)
)


# ---------------------------------------------------------------------------
# AABB — axis-aligned bounding box
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AABB:
    """Axis-aligned bounding box in local asset space (world-meters at scale=1, Z-up).

    Used for physics clearance, LOD screen-size estimation, and scatter
    distance queries.  All coordinates are in local space; the asset's
    world transform must be applied by the scatter/placement system.
    """

    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    @property
    def size_x(self) -> float:
        return self.max_x - self.min_x

    @property
    def size_y(self) -> float:
        return self.max_y - self.min_y

    @property
    def size_z(self) -> float:
        return self.max_z - self.min_z

    @property
    def diagonal(self) -> float:
        """Length of the space diagonal (metres) — used for size classification."""
        return math.sqrt(self.size_x ** 2 + self.size_y ** 2 + self.size_z ** 2)

    @property
    def volume(self) -> float:
        return max(0.0, self.size_x) * max(0.0, self.size_y) * max(0.0, self.size_z)

    @property
    def center(self) -> Tuple[float, float, float]:
        return (
            (self.min_x + self.max_x) * 0.5,
            (self.min_y + self.max_y) * 0.5,
            (self.min_z + self.max_z) * 0.5,
        )


# ---------------------------------------------------------------------------
# LOD variant descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LodVariant:
    """Descriptor for one LOD level of an asset.

    Attributes:
        lod_index:        0 = highest detail, increasing = coarser.
        screen_height_px: Screen-space height in pixels at which this LOD
                          becomes active (Unity/UE5 screen-relative threshold).
        triangle_count:   Approximate triangle count for this LOD level.
        mesh_asset_path:  Relative path to the mesh file for this LOD (may be
                          empty for billboard/impostor LODs).
        is_impostor:      True if this LOD level is a billboard impostor rather
                          than a full 3-D mesh.
    """

    lod_index: int
    screen_height_px: float
    triangle_count: int
    mesh_asset_path: str = ""
    is_impostor: bool = False


# ---------------------------------------------------------------------------
# AssetMetadata dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssetMetadata:
    """Full per-asset metadata tag container (Addendum 1.B.5).

    All four tag categories must be populated or the asset is rejected
    by ``validate_asset_metadata``.

    Attributes:
        location_tags:   One or more location context tags (see LOCATION_TAGS).
        role_tag:        Asset role — 'hero', 'support', or 'filler'.
        size_tag:        Coarse size bucket — 'large', 'medium', or 'small'.
        context_tags:    One or more visibility context tags (see CONTEXT_TAGS).
        bounds:          Axis-aligned bounding box in local asset space
                         (world-meters at scale=1).  Required for physics
                         clearance, LOD screen-size estimation, and scatter
                         overlap prevention.  Soft-warning if absent.
        lod_variants:    Ordered tuple of LodVariant descriptors (LOD0 first).
                         An empty tuple means the asset has no explicit LOD
                         chain and will be treated as a single-LOD asset.
        material_ids:    Tuple of material slot identifiers (asset-relative
                         paths or UUID strings) in face-order.  Used by the
                         scatter system to validate material presence before
                         GPU instancing.
        collision_type:  Physics collision representation (see COLLISION_TYPES).
                         Defaults to 'convex' which is safe for most props.
    """

    location_tags: Tuple[str, ...]
    role_tag: str
    size_tag: str
    context_tags: Tuple[str, ...]
    bounds: Optional[AABB] = None
    lod_variants: Tuple[LodVariant, ...] = field(default_factory=tuple)
    material_ids: Tuple[str, ...] = field(default_factory=tuple)
    collision_type: str = "convex"


def validate_asset_metadata(meta: AssetMetadata) -> List[ValidationIssue]:
    """Validate an AssetMetadata against the taxonomy.

    Emits hard issues for:
    - ASSET_META_NO_LOCATION: no location tag
    - ASSET_META_INVALID_ROLE: role not in ROLE_TAGS
    - ASSET_META_INVALID_SIZE: size not in SIZE_TAGS
    - ASSET_META_NO_CONTEXT: no context tag
    - ASSET_META_INVALID_LOCATION: unknown location tag
    - ASSET_META_INVALID_CONTEXT: unknown context tag
    - ASSET_META_INVALID_COLLISION: collision_type not in COLLISION_TYPES
    - ASSET_META_INVALID_LOD_ORDER: lod_variants not in ascending lod_index order

    Emits soft issues for:
    - ASSET_META_NO_BOUNDS: bounds is None (legacy assets may lack bounds;
      physics and LOD sizing fall back to engine defaults)
    """
    issues: List[ValidationIssue] = []

    if not meta.location_tags:
        issues.append(
            ValidationIssue(
                code="ASSET_META_NO_LOCATION",
                severity="hard",
                message="Asset metadata missing required location tag",
                remediation="Add at least one tag from LOCATION_TAGS",
            )
        )
    else:
        for tag in meta.location_tags:
            if tag not in LOCATION_TAGS:
                issues.append(
                    ValidationIssue(
                        code="ASSET_META_INVALID_LOCATION",
                        severity="hard",
                        message=f"Unknown location tag {tag!r}",
                        remediation=f"Use one of {LOCATION_TAGS}",
                    )
                )

    if meta.role_tag not in ROLE_TAGS:
        issues.append(
            ValidationIssue(
                code="ASSET_META_INVALID_ROLE",
                severity="hard",
                message=f"Role tag {meta.role_tag!r} not in {ROLE_TAGS}",
                remediation=f"Use one of {ROLE_TAGS}",
            )
        )

    if meta.size_tag not in SIZE_TAGS:
        issues.append(
            ValidationIssue(
                code="ASSET_META_INVALID_SIZE",
                severity="hard",
                message=f"Size tag {meta.size_tag!r} not in {SIZE_TAGS}",
                remediation=f"Use one of {SIZE_TAGS}",
            )
        )

    if not meta.context_tags:
        issues.append(
            ValidationIssue(
                code="ASSET_META_NO_CONTEXT",
                severity="hard",
                message="Asset metadata missing required context tag",
                remediation="Add at least one tag from CONTEXT_TAGS",
            )
        )
    else:
        for tag in meta.context_tags:
            if tag not in CONTEXT_TAGS:
                issues.append(
                    ValidationIssue(
                        code="ASSET_META_INVALID_CONTEXT",
                        severity="hard",
                        message=f"Unknown context tag {tag!r}",
                        remediation=f"Use one of {CONTEXT_TAGS}",
                    )
                )

    if meta.collision_type not in COLLISION_TYPES:
        issues.append(
            ValidationIssue(
                code="ASSET_META_INVALID_COLLISION",
                severity="hard",
                message=f"collision_type {meta.collision_type!r} not in {COLLISION_TYPES}",
                remediation=f"Use one of {COLLISION_TYPES}",
            )
        )

    # Soft warning — legacy assets may not have bounds yet.
    if meta.bounds is None:
        issues.append(
            ValidationIssue(
                code="ASSET_META_NO_BOUNDS",
                severity="soft",
                message=(
                    "Asset metadata has no bounds (AABB). "
                    "Physics clearance and LOD screen-size estimation will use engine defaults."
                ),
                remediation="Supply an AABB via AssetMetadata(bounds=AABB(min_x=..., max_x=..., ...))",
            )
        )

    # LOD variant order: lod_index must be strictly ascending (0, 1, 2, …).
    if meta.lod_variants:
        prev_idx = -1
        for lv in meta.lod_variants:
            if lv.lod_index <= prev_idx:
                issues.append(
                    ValidationIssue(
                        code="ASSET_META_INVALID_LOD_ORDER",
                        severity="hard",
                        message=(
                            f"lod_variants must be in strictly ascending lod_index order; "
                            f"found lod_index={lv.lod_index} after {prev_idx}."
                        ),
                        remediation=(
                            "Sort lod_variants by lod_index ascending before "
                            "constructing AssetMetadata."
                        ),
                    )
                )
                break
            prev_idx = lv.lod_index

    return issues


def classify_size_from_bounds(bbox_meters: "float | AABB") -> str:
    """Map a bounding-box diagonal (meters) to a size tag.

    Accepts either:
    - a pre-computed scalar diagonal length (float), or
    - an ``AABB`` instance (``AABB.diagonal`` is used automatically).

    Thresholds:
        large  > 3 m diagonal
        medium 0.5 – 3 m diagonal
        small  < 0.5 m diagonal
    """
    if isinstance(bbox_meters, AABB):
        diag = bbox_meters.diagonal
    else:
        diag = float(bbox_meters)

    if diag > 3.0:
        return "large"
    if diag >= 0.5:
        return "medium"
    return "small"


# ---------------------------------------------------------------------------
# AssetContextRuleExt — Addendum 1.B.5 scatter-rule extensions
# ---------------------------------------------------------------------------


@dataclass
class AssetContextRuleExt:
    """Extension fields added to AssetContextRule.

    hero assets get lower scale variance (more iconic), filler gets higher
    (breakup). ``camera_priority_weight`` biases placement scoring toward
    the current ViewportVantage frustum.
    """

    asset_id: str
    scale_variance_by_role: float = 0.2
    camera_priority_weight: float = 0.0

    def effective_variance(
        self,
        role_tag: str,
        lod_variants: Optional[Tuple[LodVariant, ...]] = None,
    ) -> float:
        """Return role-adjusted scale variance, optionally modulated by LOD distribution.

        Base role multipliers:
            hero    -> 0.5x baseline (iconic — consistent silhouette)
            support -> 1.0x baseline
            filler  -> 1.5x baseline (breakup — visual diversity)

        LOD-count modulation (when ``lod_variants`` is supplied):
            Assets with many LOD levels already provide implicit visual
            variety through LOD transitions, so random scale variation
            can be reduced.  The factor is:

                lod_factor = 1.0 / (1.0 + 0.1 * max(0, lod_count - 1))

            This gives 1.0 for single-LOD assets, ~0.91 for 2 LODs,
            ~0.67 for 6 LODs — matching SpeedTree Cinema v9 Appendix C
            guidance for hero-tree variance under dense LOD chains.

        Raises ``ValueError`` for unknown role tags so callers discover
        taxonomy violations at scatter time rather than silently applying
        wrong variance.

        Args:
            role_tag:     One of ROLE_TAGS ('hero', 'support', 'filler').
            lod_variants: Optional tuple of LodVariant descriptors from
                          AssetMetadata.lod_variants. Pass None (default)
                          to skip LOD-count modulation.

        Returns:
            Effective scale variance as a non-negative float.
        """
        if role_tag not in ROLE_TAGS:
            raise ValueError(
                f"Unknown role_tag {role_tag!r}; expected one of {ROLE_TAGS}. "
                "Ensure AssetMetadata.role_tag was validated via "
                "validate_asset_metadata() before calling effective_variance()."
            )

        base = float(self.scale_variance_by_role)

        # Role multiplier
        if role_tag == "hero":
            variance = base * 0.5
        elif role_tag == "filler":
            variance = base * 1.5
        else:
            variance = base

        # LOD-count modulation: more LOD levels → slight variance reduction.
        if lod_variants is not None and len(lod_variants) > 1:
            lod_count = len(lod_variants)
            lod_factor = 1.0 / (1.0 + 0.1 * (lod_count - 1))
            variance *= lod_factor

        return max(0.0, variance)

    def blended_score(
        self,
        base_viability: float,
        camera_dot: float = 0.0,
    ) -> float:
        """Return a placement priority score blending viability + camera weight.

        Args:
            base_viability: Raw viability score in [0, 1] from ``compute_viability``.
            camera_dot:     Dot product of the placement→camera vector with the
                            camera forward direction, in [-1, 1]. Pass 0.0 when
                            no viewport vantage is available (headless/CI).

        Returns:
            Score in [0, 1].  When ``camera_priority_weight`` is 0 the result
            equals ``base_viability`` exactly (no camera bias).
        """
        v = float(max(0.0, min(1.0, base_viability)))
        if self.camera_priority_weight == 0.0:
            return v
        # camera_dot is in [-1, 1]; remap to [0, 1] affinity
        cam_affinity = float(max(0.0, min(1.0, (camera_dot + 1.0) * 0.5)))
        w = float(max(0.0, min(1.0, self.camera_priority_weight)))
        return v * (1.0 - w) + cam_affinity * w


__all__ = [
    "LOCATION_TAGS",
    "ROLE_TAGS",
    "SIZE_TAGS",
    "CONTEXT_TAGS",
    "COLLISION_TYPES",
    "AABB",
    "LodVariant",
    "AssetMetadata",
    "validate_asset_metadata",
    "classify_size_from_bounds",
    "AssetContextRuleExt",
]
