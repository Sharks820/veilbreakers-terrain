"""Regression test: BIOME_ATMOSPHERE_RULES keys must be a subset of
BIOME_CLIMATE_PARAMS keys.

WAVE4-ATMOSPHERIC-BIOME-VOCAB-FRAGMENTATION-001 (P0, 2026-05-22):
Prior to this fix, BIOME_ATMOSPHERE_RULES had 10 keys of which only 1
("corrupted_swamp") was present in BIOME_CLIMATE_PARAMS.  Every call to
compute_atmospheric_placements with a canonical biome name fell through to
_DEFAULT_ATMOSPHERE (fog + dust_motes only), meaning the entire game ran
with fog-only atmospheres.

This test file pins the closed-set membership invariant so that any future
vocabulary drift between the two registries is caught at test time rather
than silently at runtime.
"""

from __future__ import annotations

import warnings

import pytest

from veilbreakers_terrain.handlers.atmospheric_volumes import (
    BIOME_ATMOSPHERE_RULES,
    compute_atmospheric_placements,
)
from veilbreakers_terrain.handlers._biome_grammar import BIOME_CLIMATE_PARAMS


class TestBiomeVocabAlignment:
    """WAVE4-ATMOSPHERIC-BIOME-VOCAB-FRAGMENTATION-001 regression pins."""

    def test_atmosphere_rules_keys_are_subset_of_climate_params(self) -> None:
        """Every BIOME_ATMOSPHERE_RULES key must be a canonical biome ID.

        If this fails, a new entry was added to BIOME_ATMOSPHERE_RULES using a
        non-canonical name.  Either rename the key to the canonical ID or add
        the new biome to BIOME_CLIMATE_PARAMS first.
        """
        canonical = set(BIOME_CLIMATE_PARAMS.keys())
        atmosphere_keys = set(BIOME_ATMOSPHERE_RULES.keys())

        unknown = atmosphere_keys - canonical
        assert unknown == set(), (
            "BIOME_ATMOSPHERE_RULES contains keys not present in "
            f"BIOME_CLIMATE_PARAMS: {sorted(unknown)!r}. "
            "Add these biomes to BIOME_CLIMATE_PARAMS or rename them to the "
            "canonical ID."
        )

    def test_all_atmosphere_rules_produce_non_default_placements(self) -> None:
        """Each canonical biome with atmosphere rules must use those rules.

        Verifies that compute_atmospheric_placements actually dispatches to the
        biome-specific rules rather than the fog-only default fallback.
        """
        bounds = (0.0, 0.0, 100.0, 100.0)
        for biome_name, rules in BIOME_ATMOSPHERE_RULES.items():
            expected_volume_types = {r["volume"] for r in rules}
            placements = compute_atmospheric_placements(
                biome_name, bounds, seed=0
            )
            found_volume_types = {p["volume_type"] for p in placements}
            # At least one biome-specific volume type must appear to confirm
            # we are NOT in the fog-only default fallback.
            assert found_volume_types & expected_volume_types, (
                f"Biome '{biome_name}' produced no volumes from its own rules "
                f"(expected one of {sorted(expected_volume_types)!r}, "
                f"got {sorted(found_volume_types)!r}). "
                "This indicates the biome name is still falling through to "
                "_DEFAULT_ATMOSPHERE."
            )

    def test_biomes_without_atmosphere_rules_warn_not_fail(self) -> None:
        """Canonical biomes that have no explicit atmosphere entry fall back
        to _DEFAULT_ATMOSPHERE gracefully.

        The fallback MUST return non-empty placements (fog + dust), not crash.
        A missing atmosphere entry is a design gap, not a hard error.
        """
        canonical = set(BIOME_CLIMATE_PARAMS.keys())
        atmosphere_keys = set(BIOME_ATMOSPHERE_RULES.keys())
        biomes_without_rules = canonical - atmosphere_keys

        bounds = (0.0, 0.0, 100.0, 100.0)
        for biome_name in sorted(biomes_without_rules):
            # Must not crash and must return at least one placement (fallback).
            placements = compute_atmospheric_placements(biome_name, bounds, seed=0)
            assert len(placements) > 0, (
                f"Biome '{biome_name}' (no explicit rules) produced zero "
                "placements even from the default fallback. "
                "_DEFAULT_ATMOSPHERE must always yield at least one entry."
            )
            # Emit a warning to track design coverage gaps (informational only).
            if biomes_without_rules:
                warnings.warn(
                    f"Biomes with no explicit BIOME_ATMOSPHERE_RULES entry "
                    f"(using default fog fallback): "
                    f"{sorted(biomes_without_rules)!r}. "
                    "Consider adding bespoke atmosphere rules for these biomes.",
                    UserWarning,
                    stacklevel=2,
                )
            break  # warn once per test run, not once per biome

    def test_known_canonical_biomes_present_in_atmosphere_rules(self) -> None:
        """Spot-check that key canonical biomes have explicit atmosphere rules.

        These are the 10 biomes that were mapped from legacy names in the P0
        fix; they must all be present and must NOT fall back to the default.
        """
        required_entries = {
            "deep_forest",
            "corrupted_swamp",
            "ashen_wastes",
            "frozen_hollows",
            "ruined_citadel",
            "cemetery",
            "mushroom_forest",
            "desert",
            "crystal_cavern",
            "blighted_mire",
        }
        missing = required_entries - set(BIOME_ATMOSPHERE_RULES.keys())
        assert missing == set(), (
            f"Expected atmosphere rules for biomes {sorted(missing)!r} "
            "but they are absent from BIOME_ATMOSPHERE_RULES. "
            "These entries were established by the WAVE4-P0 fix and must "
            "not be removed without updating this test."
        )
