"""Tests for terrain_biome_registry.py and biome name unification.

Covers:
  - CANONICAL_BIOME_IDS contains all expected VB biome IDs
  - BIOME_ALIASES map to valid canonical IDs
  - resolve_to_canonical handles canonical IDs, aliases, and raises on unknown
  - terrain_foliage_catalog biome_mask values are all canonical IDs
  - species_for_biome returns at least 1 species for every canonical biome
    (the core fix for FIX-B14-5 — zero placements for VB biomes)
  - vegetation_system.BIOME_VEGETATION_SETS keys are all canonical IDs
  - procedural_grass VEILBREAKERS_GRASS_SPECIES biome whitelists use canonical IDs
"""

from __future__ import annotations

import pytest

from veilbreakers_terrain.handlers.terrain_biome_registry import (
    BIOME_ALIASES,
    CANONICAL_BIOME_IDS,
    resolve_to_canonical,
)


# ---------------------------------------------------------------------------
# TestCanonicalBiomeIDs — registry invariants
# ---------------------------------------------------------------------------

class TestCanonicalBiomeIDs:
    def test_contains_expected_vb_biomes(self):
        """The 14 core VB biomes must all be canonical."""
        expected = {
            "thornwood_forest",
            "deep_forest",
            "corrupted_swamp",
            "grasslands",
            "mountain_pass",
            "cemetery",
            "desert",
            "coastal",
            "mushroom_forest",
            "crystal_cavern",
            "blighted_mire",
            "ruined_citadel",
            "ashen_wastes",
            "frozen_hollows",
        }
        missing = expected - set(CANONICAL_BIOME_IDS)
        assert not missing, f"Missing canonical biome IDs: {sorted(missing)}"

    def test_all_values_are_nonempty_strings(self):
        for k, v in CANONICAL_BIOME_IDS.items():
            assert isinstance(v, str) and v.strip(), (
                f"CANONICAL_BIOME_IDS[{k!r}] must be a non-empty label string"
            )

    def test_no_legacy_names_as_keys(self):
        """Legacy / alias names must NOT appear as canonical IDs."""
        legacy = {"forest", "dark_forest", "swamp", "mountain", "grassy_plains",
                  "prairie", "corrupted_wasteland", "dead", "default"}
        overlap = legacy & set(CANONICAL_BIOME_IDS)
        assert not overlap, f"Legacy names found as canonical IDs: {sorted(overlap)}"


class TestBiomeAliases:
    def test_all_alias_targets_are_canonical(self):
        for alias, target in BIOME_ALIASES.items():
            assert target in CANONICAL_BIOME_IDS, (
                f"BIOME_ALIASES[{alias!r}] = {target!r} is not a canonical ID"
            )

    def test_legacy_names_covered(self):
        """The legacy names that existed in terrain_foliage_catalog must be aliased."""
        required_aliases = {
            "forest", "dark_forest", "swamp", "mountain",
            "grassy_plains", "prairie", "corrupted_wasteland", "dead",
        }
        missing = required_aliases - set(BIOME_ALIASES)
        assert not missing, f"Legacy aliases not covered: {sorted(missing)}"


class TestResolveToCanonical:
    def test_canonical_id_passthrough(self):
        for biome_id in CANONICAL_BIOME_IDS:
            assert resolve_to_canonical(biome_id) == biome_id

    def test_alias_resolves(self):
        assert resolve_to_canonical("forest") == "thornwood_forest"
        assert resolve_to_canonical("dark_forest") == "deep_forest"
        assert resolve_to_canonical("swamp") == "corrupted_swamp"
        assert resolve_to_canonical("mountain") == "mountain_pass"
        assert resolve_to_canonical("grassy_plains") == "grasslands"
        assert resolve_to_canonical("prairie") == "grasslands"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown biome name"):
            resolve_to_canonical("nonexistent_biome_xyz")


# ---------------------------------------------------------------------------
# TestFoliageCatalogBiomeMasks — FIX-B14-5 core assertion
# ---------------------------------------------------------------------------

class TestFoliageCatalogBiomeMasks:
    def test_all_biome_mask_values_are_canonical(self):
        """Every biome_mask value in FOLIAGE_SPECIES_CATALOG must be a canonical ID."""
        from veilbreakers_terrain.handlers.terrain_foliage_catalog import (
            FOLIAGE_SPECIES_CATALOG,
        )
        bad: list[str] = []
        for species_id, spec in FOLIAGE_SPECIES_CATALOG.items():
            for biome in spec.biome_mask:
                if biome not in CANONICAL_BIOME_IDS:
                    bad.append(f"{species_id}: {biome!r}")
        assert not bad, (
            f"Non-canonical biome_mask values found ({len(bad)} total):\n"
            + "\n".join(f"  {b}" for b in sorted(bad))
        )

    def test_vb_biomes_produce_nonzero_placements(self):
        """Every canonical biome must have at least 1 species in the catalog.

        This is the direct regression test for FIX-B14-5: the biome_mask desync
        was causing zero catalog species to match for any VB biome, so no foliage
        was ever placed.
        """
        from veilbreakers_terrain.handlers.terrain_foliage_catalog import (
            species_for_biome,
        )
        empty: list[str] = []
        for biome_id in CANONICAL_BIOME_IDS:
            matches = species_for_biome(biome_id)
            if not matches:
                empty.append(biome_id)
        assert not empty, (
            f"The following canonical biomes have ZERO catalog species "
            f"(foliage placement will be silent for them): {sorted(empty)}"
        )


# ---------------------------------------------------------------------------
# TestVegetationSystemKeys
# ---------------------------------------------------------------------------

class TestVegetationSystemKeys:
    def test_biome_vegetation_sets_keys_are_canonical(self):
        """All BIOME_VEGETATION_SETS keys must be canonical biome IDs."""
        from veilbreakers_terrain.handlers.vegetation_system import (
            BIOME_VEGETATION_SETS,
        )
        bad = [k for k in BIOME_VEGETATION_SETS if k not in CANONICAL_BIOME_IDS]
        assert not bad, (
            f"BIOME_VEGETATION_SETS has non-canonical keys: {sorted(bad)}"
        )


# ---------------------------------------------------------------------------
# TestProceduralGrassBiomes
# ---------------------------------------------------------------------------

class TestProceduralGrassBiomes:
    def test_grass_species_biomes_are_canonical(self):
        """VEILBREAKERS_GRASS_SPECIES biome whitelists must use canonical IDs."""
        from veilbreakers_terrain.handlers.procedural_grass import (
            VEILBREAKERS_GRASS_SPECIES,
        )
        bad: list[str] = []
        for species in VEILBREAKERS_GRASS_SPECIES:
            for biome in species.biomes:
                if biome == "*":
                    continue  # wildcard is always valid
                if biome not in CANONICAL_BIOME_IDS:
                    bad.append(f"{species.name}: {biome!r}")
        assert not bad, (
            f"Non-canonical biome names in VEILBREAKERS_GRASS_SPECIES:\n"
            + "\n".join(f"  {b}" for b in sorted(bad))
        )
