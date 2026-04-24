"""Phase H — AAA foliage catalog tests.

Covers:
  - test_foliage_catalog_covers_all_expected_species
  - test_scatter_respects_species_altitude_moisture_gating
  - test_water_foliage_only_near_water

The catalog is the single source of truth for scatter species; these
tests guard against silent regressions where a species is dropped from
the catalog, loses biome/altitude gating, or floods dry ground with
water-only foliage.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from blender_addon.handlers.terrain_foliage_catalog import (
    EXPECTED_CATEGORIES,
    FOLIAGE_SPECIES_CATALOG,
    SPECIES_CONSTRAINTS_FROM_CATALOG,
    SpeciesSpec,
    categories_covered,
    manifest_entries,
    species_for_biome,
    species_ids_by_category,
    tripo_assets_required,
)
from blender_addon.handlers.environment_scatter import (
    _SPECIES_CONSTRAINTS,
    _scatter_pass,
)


# ---------------------------------------------------------------------------
# Catalog coverage + structure
# ---------------------------------------------------------------------------

class TestFoliageCatalogCoverage:
    """Verify catalog contents satisfy the 14 AAA category requirements."""

    def test_foliage_catalog_covers_all_expected_species(self):
        """Every expected category must have at least one registered species."""
        covered = categories_covered()
        missing = EXPECTED_CATEGORIES - covered
        assert not missing, (
            f"FOLIAGE_SPECIES_CATALOG missing categories: {sorted(missing)}. "
            f"Covered: {sorted(covered)}"
        )

    def test_four_grass_variants_registered(self):
        """AAA bar requires 4 grass variants (tall/short/dry/lush)."""
        ids = set(species_ids_by_category("grass"))
        assert {"grass_tall", "grass_short", "grass_dry", "grass_lush"}.issubset(ids)

    def test_four_tree_variants_registered(self):
        """AAA bar requires 4 biome-gated tree variants."""
        ids = set(species_ids_by_category("tree"))
        assert {"tree_oak", "tree_birch", "tree_pine", "tree_dead"}.issubset(ids)

    def test_two_boulder_variants_registered(self):
        ids = set(species_ids_by_category("boulder"))
        assert {"talus_boulder", "hero_boulder"}.issubset(ids)

    def test_four_water_foliage_variants_registered(self):
        ids = set(species_ids_by_category("water_foliage"))
        assert {"reeds", "lily_pad", "algae", "submerged_grass"}.issubset(ids)

    def test_three_moss_variants_registered(self):
        ids = set(species_ids_by_category("moss"))
        assert {"moss_rock", "moss_log", "moss_tree_base"}.issubset(ids)

    def test_every_species_has_unity_asset_path(self):
        for sid, spec in FOLIAGE_SPECIES_CATALOG.items():
            assert spec.unity_asset_path.startswith(
                "Assets/VeilBreakersTerrain/Foliage/"
            ), f"{sid} missing or malformed unity_asset_path"

    def test_every_species_has_sane_numeric_bands(self):
        for sid, spec in FOLIAGE_SPECIES_CATALOG.items():
            assert spec.min_altitude_m <= spec.max_altitude_m, sid
            assert spec.min_slope_rad <= spec.max_slope_rad, sid
            lo, hi = spec.moisture_range
            assert 0.0 <= lo <= hi <= 1.0, sid
            assert spec.poisson_min_distance_m > 0.0, sid
            assert spec.lod_viewer_distance_m > 0.0, sid

    def test_manifest_entries_json_serialisable(self):
        import json
        out = manifest_entries()
        json.dumps(out)  # must not raise
        assert set(out.keys()) == set(FOLIAGE_SPECIES_CATALOG.keys())

    def test_tripo_asset_list_non_empty_and_documented(self):
        required = tripo_assets_required()
        assert len(required) > 0, "Expected Phase-I Tripo handoff species"
        for sid in required:
            assert FOLIAGE_SPECIES_CATALOG[sid].notes, (
                f"{sid} flagged for Tripo but missing notes for Phase-I agent"
            )

    def test_species_constraints_merged_into_scatter(self):
        """Every catalog species must appear in environment_scatter._SPECIES_CONSTRAINTS."""
        for sid in FOLIAGE_SPECIES_CATALOG:
            assert sid in _SPECIES_CONSTRAINTS, (
                f"Species {sid!r} not wired into _SPECIES_CONSTRAINTS"
            )
            row = _SPECIES_CONSTRAINTS[sid]
            for key in ("min_sep", "max_slope", "alt_min", "alt_max",
                        "moisture_min", "moisture_max"):
                assert key in row, f"{sid} missing constraint key {key}"


# ---------------------------------------------------------------------------
# Altitude / moisture gating (scatter-pass integration)
# ---------------------------------------------------------------------------

def _flat_terrain(size: int = 33) -> tuple[np.ndarray, np.ndarray]:
    """Return (heightmap, slope_map) for a flat low-altitude tile."""
    heightmap = np.full((size, size), 0.05, dtype=np.float32)
    slope_map = np.zeros((size, size), dtype=np.float32)
    return heightmap, slope_map


def _water_proximity_dry() -> np.ndarray:
    return np.zeros((33, 33), dtype=np.float32)


def _water_proximity_wet() -> np.ndarray:
    # Right half of the map is water edge (value 1.0), left half is dry.
    wpm = np.zeros((33, 33), dtype=np.float32)
    wpm[:, 16:] = 1.0
    return wpm


class TestScatterSpeciesGating:
    """Scatter pass must honour the altitude/moisture constraints."""

    def test_scatter_respects_species_altitude_moisture_gating(self):
        """Tree_pine requires altitude >= 200m; on a low-altitude (0.05 normalised
        → 150m) tile we should still produce tree placements from tree_oak/birch,
        but never tree_pine since our alt_min bound excludes it."""
        hm, sm = _flat_terrain()
        placements = _scatter_pass(
            heightmap=hm,
            slope_map=sm,
            terrain_size=100.0,
            pass_type="structure",
            biome="forest",
            seed=7,
            water_proximity_map=_water_proximity_dry(),
        )
        species_seen = {p.get("species_id") for p in placements if p.get("species_id")}
        # pine has min_altitude_m=200 → alt_min ≈ 0.067 normalised; our flat
        # heightmap is 0.05 < 0.067 so pine should be rejected.
        assert "tree_pine" not in species_seen, (
            "tree_pine must be altitude-gated out of 0.05-normalised tile"
        )
        # oak/birch allow altitude 0 → 900/1200m so should be eligible (some
        # runs may still produce 0 due to density probability; accept either).
        # But we must have *some* placements from the catalog pipeline.
        catalog_placements = [p for p in placements if p.get("species_id")]
        assert catalog_placements, "catalog sub-pass produced zero placements"

    def test_dry_moisture_rejects_lush_grass(self):
        """grass_lush requires moisture ≥0.55; flat dry tile must reject it."""
        hm, sm = _flat_terrain()
        placements = _scatter_pass(
            heightmap=hm,
            slope_map=sm,
            terrain_size=100.0,
            pass_type="ground_cover",
            biome="forest",
            seed=11,
            water_proximity_map=_water_proximity_dry(),
        )
        species_seen = {p.get("species_id") for p in placements if p.get("species_id")}
        assert "grass_lush" not in species_seen, (
            "grass_lush must be moisture-gated out of dry tile"
        )

    def test_slope_clamp_respected_for_boulder(self):
        """talus_boulder has max_slope=70°; a cliff-only tile (80°) must reject it."""
        hm = np.full((33, 33), 0.3, dtype=np.float32)
        sm = np.full((33, 33), 85.0, dtype=np.float32)  # all 85°
        placements = _scatter_pass(
            heightmap=hm,
            slope_map=sm,
            terrain_size=100.0,
            pass_type="structure",
            biome="mountain",
            seed=3,
        )
        species_seen = {p.get("species_id") for p in placements if p.get("species_id")}
        assert "talus_boulder" not in species_seen


# ---------------------------------------------------------------------------
# Water-only foliage must never bleed into dry ground
# ---------------------------------------------------------------------------

class TestWaterFoliageGating:
    """water_foliage species must only appear on water-adjacent cells."""

    def test_water_foliage_only_near_water(self):
        """With a half-wet map, every reeds/lily_pad/algae/submerged_grass
        placement must land on a water-edge cell (x world-coord >= 0)."""
        hm, sm = _flat_terrain()
        placements = _scatter_pass(
            heightmap=hm,
            slope_map=sm,
            terrain_size=100.0,
            pass_type="ground_cover",
            biome="swamp",
            seed=17,
            water_proximity_map=_water_proximity_wet(),
        )
        water_species = {"reeds", "lily_pad", "algae", "submerged_grass"}
        for p in placements:
            if p.get("species_id") in water_species:
                wx, _wy = p["position"]
                # Wet half is x world-coord >= 0 (terrain center is at 0, and
                # wet cells are columns 16..32 which correspond to wx >= 0)
                assert wx >= -1.0, (
                    f"{p['species_id']} placed at wx={wx} — outside water edge"
                )

    def test_dry_tile_has_no_water_foliage(self):
        """Fully dry proximity map must yield zero water_foliage placements."""
        hm, sm = _flat_terrain()
        placements = _scatter_pass(
            heightmap=hm,
            slope_map=sm,
            terrain_size=100.0,
            pass_type="ground_cover",
            biome="swamp",
            seed=23,
            water_proximity_map=_water_proximity_dry(),
        )
        water_species = {"reeds", "lily_pad", "algae", "submerged_grass"}
        observed = [p for p in placements if p.get("species_id") in water_species]
        assert observed == [], (
            f"Dry tile produced water foliage placements: "
            f"{[p['species_id'] for p in observed]}"
        )


# ---------------------------------------------------------------------------
# Manifest integration (Unity export)
# ---------------------------------------------------------------------------

class TestFoliageManifestIntegration:
    def test_unity_manifest_helper_emits_catalog(self):
        from blender_addon.handlers.terrain_unity_export import (
            _build_foliage_scatter_manifest,
        )
        out = _build_foliage_scatter_manifest()
        assert "species" in out
        assert "categories_covered" in out
        assert "tripo_assets_required" in out
        assert set(out["species"].keys()) == set(FOLIAGE_SPECIES_CATALOG.keys())
        # Categories must be complete
        assert set(out["categories_covered"]) >= set(EXPECTED_CATEGORIES)
