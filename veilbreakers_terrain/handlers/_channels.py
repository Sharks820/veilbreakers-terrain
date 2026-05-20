"""T0.5-1 — Typed Channel registry (Y04 v3 §P.8.2 ord 0.5a).

Closes ZZ4-A6 R1 (Shape A elimination — silent unit drift between
producer and consumer).

This module introduces a strict ``Channel`` enum that names every
canonical channel emitted by the terrain pipeline AND pins its unit.
The enum is the **forward-compatible API** for channel access; the
existing string-keyed ``TerrainMaskStack.get("water_depth_m")`` API
remains in place during migration per FIX_PATTERN_v1.md §3 C4 step 2:

  > Introduce typed-registry ``Channel.WATER_DEPTH_M`` etc. with both
  > old and new accessors during migration; never delete old accessor
  > in same PR.

This PR is the foundational step. Subsequent PRs migrate one producer
at a time to use ``Channel.X`` references, then consumers, then the
final PR removes the string-keyed accessor.

Design choices:
- Enum value is the canonical mask-stack field name (string), so
  ``Channel.HEIGHT.value == "height"`` matches existing ``mask_stack.get()``
  call sites. No translation needed for callers that already pass strings.
- Each enum member carries an ``info`` attribute exposing ``unit`` and
  ``description`` via ``Channel.HEIGHT.info.unit == "m"``. Static type
  checkers can inspect both name and unit at the boundary.
- ``Channel.from_name(s)`` is the safe inverse — raises ``KeyError`` if
  the string is unknown, so a typo at the boundary is loud-at-source.

See also:
- ``terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS`` (T0.5-5 registry
  at the assertion site — overlaps this registry; future PR consolidates).
- ``test_channel_enum_registry.py`` (regression net).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, FrozenSet


@dataclass(frozen=True)
class ChannelInfo:
    """Per-channel metadata bound to a ``Channel`` enum member."""

    unit: str  # canonical unit: 'm' | 'rad' | 'deg' | 'dimensionless' | 'count' | 'id'
    description: str


class Channel(Enum):
    """Typed registry of canonical mask-stack channels.

    Each member's ``value`` is the string field name on
    ``TerrainMaskStack`` (so ``stack.get(Channel.HEIGHT.value)`` works).
    Each member's ``info`` is a ``ChannelInfo`` exposing the canonical
    unit + description.
    """

    # --- Heights / depths / elevations (meters) ---
    HEIGHT = "height"
    WATER_DEPTH_M = "water_depth_m"
    WATER_SURFACE_ELEVATION_M = "water_surface_elevation_m"
    BATHYMETRY = "bathymetry"
    TERRAIN_DISPLACEMENT = "terrain_displacement"
    SEDIMENT_HEIGHT = "sediment_height"
    BEDROCK_HEIGHT = "bedrock_height"

    # --- Rotation / angular (radians) ---
    SLOPE_RAD = "slope"
    STRATA_ORIENTATION_RAD = "strata_orientation"
    ROTATION_Y_RAD = "rotation_y_rad"

    # --- D8 direction indices (int8 -1..7, NOT radians) ---
    # NB: pass_hydrology emits this as priority_flood_d8 integer indices
    # (-1 = pit/border, 0..7 = neighbour index). The angular form
    # ``flow_direction_rad`` only exists at per-lip granularity inside
    # terrain_waterfalls.LipCandidate — it is NOT the mask-stack channel.
    FLOW_DIRECTION = "flow_direction"

    # --- Degrees (export-side / Unity-bound) ---
    YAW_DEG = "yaw_degrees"

    # --- Dimensionless [0, 1] continuous masks ---
    WETNESS = "wetness"
    DRAINAGE = "drainage"
    FOAM = "foam"
    MIST = "mist"
    WET_ROCK = "wet_rock"
    SNOW_COVERAGE = "snow_coverage"
    TERRAIN_BRUCKS_WEIGHT = "terrain_brucks_weight"
    GRASS_DENSITY_MAP = "grass_density_map"
    TALUS = "talus"
    EROSION_AMOUNT = "erosion_amount"
    DEPOSITION_AMOUNT = "deposition_amount"
    CURVATURE = "curvature"
    BANK_INSTABILITY = "bank_instability"

    # --- Binary masks (dimensionless 0/1) ---
    CLIFF_CANDIDATE = "cliff_candidate"
    CLIFF_MASK = "cliff_mask"
    WATER_SURFACE_MASK = "water_surface_mask"
    CAVE_CANDIDATE = "cave_candidate"

    # --- Categorical IDs (uint8/uint16 indices) ---
    BIOME_ID = "biome_id"
    NAVMESH_AREA_ID = "navmesh_area_id"
    TIDAL_ZONE_LABEL = "tidal_zone_label"

    # --- Counts / accumulators ---
    FLOW_ACCUMULATION = "flow_accumulation"

    @property
    def info(self) -> ChannelInfo:
        """Return the ``ChannelInfo`` metadata for this channel."""
        return _CHANNEL_INFO[self]

    @classmethod
    def from_name(cls, name: str) -> "Channel":
        """Return the ``Channel`` enum member matching ``name``.

        Raises ``KeyError`` if ``name`` is not a canonical channel — this
        is the loud-at-source guard against typo-drift at the boundary.
        Callers wanting permissive lookup should use ``maybe_from_name``.
        """
        try:
            return _BY_NAME[name]
        except KeyError:
            raise KeyError(
                f"Channel name {name!r} is not in the canonical Channel "
                f"registry. Add it to veilbreakers_terrain.handlers."
                f"_channels.Channel if it is a new canonical channel, OR "
                f"fix the typo at the call site. Known channels: "
                f"{sorted(_BY_NAME.keys())[:10]}... ({len(_BY_NAME)} total)."
            ) from None

    @classmethod
    def maybe_from_name(cls, name: str) -> "Channel | None":
        """Same as ``from_name`` but returns ``None`` instead of raising."""
        return _BY_NAME.get(name)


_CHANNEL_INFO: Final[dict[Channel, ChannelInfo]] = {
    # Heights / depths / elevations
    Channel.HEIGHT: ChannelInfo("m", "Core terrain heightmap, world-space meters"),
    Channel.WATER_DEPTH_M: ChannelInfo(
        "m", "Water depth above bed, derived from water_surface_elevation_m"
    ),
    Channel.WATER_SURFACE_ELEVATION_M: ChannelInfo(
        "m", "Absolute water surface elevation, world-space meters"
    ),
    Channel.BATHYMETRY: ChannelInfo("m", "Positive meters below water surface"),
    Channel.TERRAIN_DISPLACEMENT: ChannelInfo(
        "m", "Vertex displacement applied to terrain surface, meters"
    ),
    Channel.SEDIMENT_HEIGHT: ChannelInfo(
        "m", "Sediment thickness above bedrock, meters"
    ),
    Channel.BEDROCK_HEIGHT: ChannelInfo(
        "m", "Bedrock elevation under sediment, world-space meters"
    ),
    # Rotation / angular
    Channel.SLOPE_RAD: ChannelInfo("rad", "Slope angle, radians"),
    Channel.STRATA_ORIENTATION_RAD: ChannelInfo(
        "rad", "Strata dip direction, radians"
    ),
    Channel.ROTATION_Y_RAD: ChannelInfo(
        "rad", "Per-instance Y-axis rotation, radians (Python-side)"
    ),
    # D8 direction index (int8 -1..7) — NOT radians. The per-lip radians
    # form is LipCandidate.flow_direction_rad in terrain_waterfalls; the
    # mask-stack channel is integer index emitted by priority_flood_d8.
    # Tagged "dimensionless" to match terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS
    # (T0.5-5 ships first; the index-set semantics are documented inline).
    Channel.FLOW_DIRECTION: ChannelInfo(
        "dimensionless",
        "D8 flow direction, int8 indices (-1=pit/border, 0..7=neighbour) — NOT radians",
    ),
    # Degrees-native (export hop)
    Channel.YAW_DEG: ChannelInfo(
        "deg", "Tree yaw in tree_instance_points export, degrees (Unity-facing)"
    ),
    # Dimensionless
    Channel.WETNESS: ChannelInfo("dimensionless", "Surface wetness [0, 1]"),
    Channel.DRAINAGE: ChannelInfo("dimensionless", "Drainage intensity [0, 1]"),
    Channel.FOAM: ChannelInfo("dimensionless", "Foam coverage [0, 1]"),
    Channel.MIST: ChannelInfo("dimensionless", "Mist density [0, 1]"),
    Channel.WET_ROCK: ChannelInfo("dimensionless", "Wet-rock weight [0, 1]"),
    Channel.SNOW_COVERAGE: ChannelInfo(
        "dimensionless", "Snow weight [0, 1]"
    ),
    Channel.TERRAIN_BRUCKS_WEIGHT: ChannelInfo(
        "dimensionless", "Terrain brucks weight [0, 1]"
    ),
    Channel.GRASS_DENSITY_MAP: ChannelInfo(
        "dimensionless", "Per-cell grass density [0, 1]"
    ),
    Channel.TALUS: ChannelInfo(
        "dimensionless", "Talus accumulation [0, 1]"
    ),
    Channel.EROSION_AMOUNT: ChannelInfo(
        "dimensionless", "Per-cell erosion amount [0, 1]"
    ),
    Channel.DEPOSITION_AMOUNT: ChannelInfo(
        "dimensionless", "Per-cell deposition amount [0, 1]"
    ),
    Channel.CURVATURE: ChannelInfo(
        "dimensionless", "Surface curvature (signed)"
    ),
    Channel.BANK_INSTABILITY: ChannelInfo(
        "dimensionless", "Bank instability factor [0, 1]"
    ),
    # Binary masks
    Channel.CLIFF_CANDIDATE: ChannelInfo(
        "dimensionless", "Binary cliff candidate mask (0/1)"
    ),
    Channel.CLIFF_MASK: ChannelInfo(
        "dimensionless", "Rasterised cliff cells (float32, 0/1)"
    ),
    Channel.WATER_SURFACE_MASK: ChannelInfo(
        "dimensionless", "Binary water surface mask (0/1)"
    ),
    Channel.CAVE_CANDIDATE: ChannelInfo(
        "dimensionless", "Binary cave candidate mask (0/1)"
    ),
    # Categorical IDs — tagged "dimensionless" to match
    # terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS (T0.5-5 ships first;
    # the categorical-label semantics are documented inline).
    Channel.BIOME_ID: ChannelInfo(
        "dimensionless", "Biome label per cell (uint8/16) — categorical ID"
    ),
    Channel.NAVMESH_AREA_ID: ChannelInfo(
        "dimensionless", "Unity navmesh area id per cell (uint8) — categorical ID"
    ),
    Channel.TIDAL_ZONE_LABEL: ChannelInfo(
        "dimensionless",
        "Tidal zone classification (subtidal=0, intertidal=1, ...) — categorical ID",
    ),
    # Counts / accumulators
    Channel.FLOW_ACCUMULATION: ChannelInfo(
        "count", "Upstream cell-count accumulation"
    ),
}

_BY_NAME: Final[dict[str, Channel]] = {ch.value: ch for ch in Channel}


# Convenience frozensets per unit class — useful for callers that need to
# enumerate all meters-channels, all radians-channels, etc. at boundary
# validation time.

CHANNELS_BY_UNIT: Final[dict[str, FrozenSet[Channel]]] = {
    unit: frozenset(ch for ch, info in _CHANNEL_INFO.items() if info.unit == unit)
    for unit in {"m", "rad", "deg", "dimensionless", "id", "count"}
}

# Sanity: every enum member must have a corresponding ChannelInfo entry.
# This catches future drift where a new Channel is added without metadata.
_MISSING_INFO = [ch for ch in Channel if ch not in _CHANNEL_INFO]
assert not _MISSING_INFO, (
    f"Channel members missing ChannelInfo entries: {_MISSING_INFO}. "
    f"Add metadata to _CHANNEL_INFO before merging."
)


__all__ = [
    "Channel",
    "ChannelInfo",
    "CHANNELS_BY_UNIT",
]
