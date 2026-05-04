"""Single source of truth for VeilBreakers canonical biome IDs.

All biome name references in the codebase must import from here.

Canonical IDs are the keys used in ``terrain_materials.BIOME_PALETTES``,
which is the authority referenced by ``_biome_grammar.resolve_biome_name``.
Additional VB-specific biomes present in ``vegetation_system.BIOME_VEGETATION_SETS``
are included as canonical IDs with their own BIOME_CLIMATE_PARAMS entries.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical biome IDs (authoritative list)
# ---------------------------------------------------------------------------

CANONICAL_BIOME_IDS: dict[str, str] = {
    # Core forest / wilderness
    "thornwood_forest":  "Thornwood Forest",
    "deep_forest":       "Deep Forest",
    "mushroom_forest":   "Mushroom Forest",
    # Wet / swamp
    "corrupted_swamp":   "Corrupted Swamp",
    "blighted_mire":     "Blighted Mire",
    # Open terrain
    "grasslands":        "Grasslands",
    "desert":            "Desert",
    "coastal":           "Coastal",
    "ashen_wastes":      "Ashen Wastes",
    # Cold / high elevation
    "mountain_pass":     "Mountain Pass",
    "frozen_hollows":    "Frozen Hollows",
    # Ruins / civilisation
    "cemetery":          "Cemetery",
    "ruined_citadel":    "Ruined Citadel",
    "ruined_fortress":   "Ruined Fortress",
    "abandoned_village": "Abandoned Village",
    "battlefield":       "Battlefield",
    # Exotic / supernatural
    "crystal_cavern":    "Crystal Cavern",
    "veil_crack_zone":   "Veil Crack Zone",
}

# ---------------------------------------------------------------------------
# Mapping from legacy / alias names to canonical IDs (for backward compat)
# ---------------------------------------------------------------------------

BIOME_ALIASES: dict[str, str] = {
    # terrain_foliage_catalog legacy names
    "forest":               "thornwood_forest",
    "dark_forest":          "deep_forest",
    "swamp":                "corrupted_swamp",
    "mountain":             "mountain_pass",
    "grassy_plains":        "grasslands",
    "prairie":              "grasslands",
    "corrupted_wasteland":  "veil_crack_zone",
    "dead":                 "battlefield",
    "default":              "thornwood_forest",
    # _biome_grammar.BIOME_ALIASES (kept in sync)
    "volcanic_wastes":      "desert",
    "frozen_tundra":        "mountain_pass",
    "thornwood":            "thornwood_forest",
    # vegetation_system extra name variants
    "ruins":                "ruined_citadel",
    "cave":                 "crystal_cavern",
    "graveyard":            "cemetery",
}


def resolve_to_canonical(name: str) -> str:
    """Return the canonical biome ID for *name*, applying aliases.

    Args:
        name: Any biome string (canonical or legacy alias).

    Returns:
        Canonical ID from CANONICAL_BIOME_IDS.

    Raises:
        ValueError: If *name* is not a known canonical ID or alias.
    """
    if name in CANONICAL_BIOME_IDS:
        return name
    canonical = BIOME_ALIASES.get(name)
    if canonical is not None and canonical in CANONICAL_BIOME_IDS:
        return canonical
    raise ValueError(
        f"Unknown biome name: {name!r}. "
        f"Known canonical IDs: {sorted(CANONICAL_BIOME_IDS)}. "
        f"Known aliases: {sorted(BIOME_ALIASES)}."
    )
