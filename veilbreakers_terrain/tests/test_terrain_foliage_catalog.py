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
import json
import random

import numpy as np
import pytest

import veilbreakers_terrain.handlers.terrain_foliage_catalog as foliage_catalog
from veilbreakers_terrain.handlers.terrain_foliage_catalog import (
    AssetManifest,
    EXPECTED_CATEGORIES,
    FOLIAGE_SPECIES_CATALOG,
    categories_covered,
    external_model_assets_required,
    default_asset_catalog_path,
    get_default_asset_manifest,
    manifest_entries,
    resolve_model_asset,
    set_default_asset_manifest,
    species_for_biome,
    species_ids_by_category,
    validate_asset_manifest_entry,
    validate_asset_manifest_entries,
    _derive_species_constraints,
    _slope,
)
from veilbreakers_terrain.handlers.environment_scatter import (
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

    def test_external_model_asset_list_non_empty_and_documented(self):
        required = external_model_assets_required()
        assert len(required) > 0, "Expected external model handoff species"
        for sid in required:
            assert FOLIAGE_SPECIES_CATALOG[sid].notes, (
                f"{sid} flagged for external modeling but missing handoff notes"
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

    def test_slope_helper_converts_degrees_to_radians(self):
        lo, hi = _slope(15.0, 45.0)

        assert lo == pytest.approx(math.radians(15.0))
        assert hi == pytest.approx(math.radians(45.0))

    def test_species_for_biome_filters_catalog_by_mask(self):
        forest_species = species_for_biome("forest")
        swamp_species = species_for_biome("swamp")

        assert forest_species
        assert swamp_species
        assert all("forest" in spec.biome_mask for spec in forest_species)
        assert any(spec.species_id == "grass_lush" for spec in swamp_species)

    def test_derive_species_constraints_normalizes_catalog_ranges(self):
        constraints = _derive_species_constraints()
        pine = constraints["tree_pine"]

        assert set(constraints) == set(FOLIAGE_SPECIES_CATALOG)
        assert pine["alt_min"] == pytest.approx(
            FOLIAGE_SPECIES_CATALOG["tree_pine"].min_altitude_m / 3000.0
        )
        assert pine["max_slope"] == pytest.approx(
            math.degrees(FOLIAGE_SPECIES_CATALOG["tree_pine"].max_slope_rad)
        )
        assert pine["moisture_min"] <= pine["moisture_max"]

    def test_asset_manifest_entry_requires_source_license_lod_and_qa_fields(self):
        issues = validate_asset_manifest_entry(
            "plantcatalog_oak_01",
            {
                "asset_id": "plantcatalog_oak_01",
                "category": "tree",
                "lods": [{"path": "assets/foliage/oak_lod0.glb"}],
                "bbox": {"min": [-1, -1, 0], "max": [1, 1, 6]},
                "pivot": [0, 0, 0],
                "source_tool": "PlantCatalog",
                "source_version": "2023",
                "source_url": "https://example.invalid/oak",
                "source_file": "oak.fbx",
                "license_origin": "PlantCatalog",
                "license_allows_commercial": True,
                "resale_allowed": True,
                "plantcatalog_derivative": True,
                "triangle_budget_lod0": 45000,
                "collider_policy": "capsule",
                "wind_profile": "tree",
                "impostor_policy": "required",
                "blender_qa_render": "qa/oak.png",
                "unity_import_status": "pending",
            },
        )

        codes = {issue["code"] for issue in issues}

        assert "plantcatalog_resale_policy_invalid" in codes

    def test_asset_manifest_entry_blocks_placeholder_asset_without_lods(self):
        issues = validate_asset_manifest_entry(
            "bad_tree",
            {
                "category": "tree",
                "bbox": {"min": [-1, -1, 0], "max": [1, 1, 6]},
                "pivot": [0, 0, 0],
            },
        )

        codes = {issue["code"] for issue in issues}

        assert "missing_asset_id" in codes
        assert "missing_lods" in codes
        assert "missing_source_tool" in codes
        assert "commercial_license_not_confirmed" in codes

    def test_asset_manifest_entry_rejects_asset_id_key_mismatch(self):
        issues = validate_asset_manifest_entry(
            "oak_key",
            {
                "asset_id": "oak_payload",
                "category": "tree",
                "fallback": True,
                "bbox": {"min": [-1, -1, 0], "max": [1, 1, 6]},
                "pivot": [0, 0, 0],
            },
        )

        codes = {issue["code"] for issue in issues}

        assert "asset_id_mismatch" in codes

    def test_asset_manifest_entries_batches_all_asset_contract_issues(self):
        report = validate_asset_manifest_entries(
            {
                "bad_tree": {
                    "asset_id": "bad_tree",
                    "category": "tree",
                    "bbox": {"min": [-1, -1, 0], "max": [1, 1, 6]},
                    "pivot": [0, 0, 0],
                },
                "bad_rock": {
                    "asset_id": "bad_rock",
                    "category": "boulder",
                    "source_tool": "mesh_authoring",
                    "license_allows_commercial": True,
                    "resale_allowed": False,
                },
            }
        )

        bad_tree_codes = {
            issue["code"] for issue in report if "asset[bad_tree]" in issue["message"]
        }
        bad_rock_codes = {
            issue["code"] for issue in report if "asset[bad_rock]" in issue["message"]
        }

        assert bad_tree_codes >= {
            "missing_lods",
            "missing_source_tool",
            "commercial_license_not_confirmed",
        }
        assert bad_rock_codes >= {
            "missing_lods",
            "missing_bounds",
            "missing_pivot_policy",
        }


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
        from veilbreakers_terrain.handlers.terrain_unity_export import (
            _build_foliage_scatter_manifest,
        )
        out = _build_foliage_scatter_manifest()
        assert "species" in out
        assert "categories_covered" in out
        assert "external_model_assets_required" in out
        assert set(out["species"].keys()) == set(FOLIAGE_SPECIES_CATALOG.keys())
        # Categories must be complete
        assert set(out["categories_covered"]) >= set(EXPECTED_CATEGORIES)


class TestAssetManifestRuntimeContract:
    def _catalog_path(self, tmp_path):
        path = tmp_path / "catalog.json"
        path.write_text(
            json.dumps(
                {
                    "assets": {
                        "oak_lod0": {
                            "asset_id": "oak_lod0",
                            "category": "oak",
                            "display_category": "tree",
                            "lods": [
                                {"path": "Assets/Oak_LOD0.glb"},
                                {"path": "Assets/Oak_LOD1.glb"},
                            ],
                            "pbr_maps": {"base_color": "oak.png"},
                        },
                        "boulder_lod0": {
                            "asset_id": "boulder_lod0",
                            "category": "boulder",
                            "display_category": "rock",
                            "lods": [{"path": "Assets/Boulder_LOD0.glb"}],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_default_asset_catalog_path_points_to_repo_assets_folder(self):
        path = default_asset_catalog_path()

        assert path.name == "catalog.json"
        assert path.parent.name == "foliage"
        assert path.parent.parent.name == "assets"

    def test_asset_manifest_reload_lookup_species_choice_and_lods(self, tmp_path):
        manifest = AssetManifest(path=self._catalog_path(tmp_path))
        manifest._maybe_reload()

        assert set(manifest.asset_ids()) == {"oak_lod0", "boulder_lod0"}
        assert manifest.get_asset("oak_lod0")["category"] == "oak"
        assert manifest.get_asset("_fallback_tree")["fallback"] is True
        species_asset_ids = [a["asset_id"] for a in manifest.assets_for_species("tree_oak")]
        assert set(species_asset_ids) == {"oak_lod0"}
        assert manifest.choose_for_species("tree_oak", rng=random.Random(1))["asset_id"] == "oak_lod0"
        assert manifest.choose_for_species("unknown_species")["fallback"] is True
        assert manifest.lod_paths("oak_lod0") == ["Assets/Oak_LOD0.glb", "Assets/Oak_LOD1.glb"]

        stats = manifest.stats()
        assert stats["asset_count"] == 2
        assert stats["categories"]["oak"] == 1

        manifest.reload()
        assert "oak_lod0" in manifest.asset_ids()

    def test_asset_manifest_load_locked_merges_overrides_without_file(self, tmp_path):
        manifest = AssetManifest(
            path=tmp_path / "missing.json",
            overrides={
                "fern_lod0": {
                    "asset_id": "fern_lod0",
                    "category": "fern",
                    "display_category": "grass",
                    "lods": [],
                }
            },
        )

        manifest._load_locked(123.0)

        assert manifest._loaded is True
        assert manifest.asset_ids() == ["fern_lod0"]
        assert manifest.assets_for_category("grass")[0]["asset_id"] == "fern_lod0"

    def test_default_asset_manifest_set_get_and_reset(self):
        original = foliage_catalog._DEFAULT_MANIFEST
        custom = AssetManifest(overrides={"oak_lod0": {"asset_id": "oak_lod0", "category": "oak"}})

        try:
            set_default_asset_manifest(custom)
            assert get_default_asset_manifest() is custom
            set_default_asset_manifest(None)
            assert get_default_asset_manifest() is not custom
        finally:
            set_default_asset_manifest(original)

    def test_asset_manifest_returns_defensive_copies_for_category_lookups(self):
        manifest = AssetManifest(
            overrides={
                "oak_lod0": {
                    "asset_id": "oak_lod0",
                    "category": "oak",
                    "display_category": "tree",
                    "lods": [{"path": "Assets/Oak_LOD0.glb"}],
                    "pbr_maps": {
                        "base_color": "oak_base.png",
                        "normal": "oak_n.png",
                        "roughness": "oak_r.png",
                    },
                }
            }
        )

        first = manifest.assets_for_category("oak")[0]
        first["category"] = "corrupted"
        first["lods"][0]["path"] = "corrupted.glb"

        second = manifest.assets_for_category("oak")[0]

        assert second["category"] == "oak"
        assert second["lods"][0]["path"] == "Assets/Oak_LOD0.glb"

    def test_resolve_model_asset_returns_defensive_copy(self):
        manifest = AssetManifest(
            overrides={
                "oak_lod0": {
                    "asset_id": "oak_lod0",
                    "category": "oak",
                    "display_category": "tree",
                    "lods": [{"path": "Assets/Oak_LOD0.glb"}],
                }
            }
        )

        resolved = resolve_model_asset("tree_oak", manifest=manifest)
        resolved["asset_id"] = "corrupted"

        again = resolve_model_asset("tree_oak", manifest=manifest)

        assert again["asset_id"] == "oak_lod0"

    def test_asset_manifest_stats_reports_catalog_readiness(self):
        manifest = AssetManifest(
            overrides={
                "oak_lod0": {
                    "asset_id": "oak_lod0",
                    "category": "oak",
                    "display_category": "tree",
                    "lods": [{"path": "Assets/Oak_LOD0.glb"}],
                    "pbr_maps": {
                        "base_color": "oak_base.png",
                        "normal": "oak_n.png",
                        "roughness": "oak_r.png",
                        "height": "oak_h.png",
                    },
                }
            }
        )

        stats = manifest.stats()

        assert stats["asset_count"] == 1
        assert stats["species_total"] >= len(FOLIAGE_SPECIES_CATALOG)
        assert stats["species_bound"] >= 1
        assert "oak" in stats["categories"]

    def test_asset_manifest_deep_copies_constructor_overrides(self):
        overrides = {
            "oak_lod0": {
                "asset_id": "oak_lod0",
                "category": "oak",
                "display_category": "tree",
                "lods": [{"path": "Assets/Oak_LOD0.glb"}],
            }
        }
        manifest = AssetManifest(overrides=overrides)

        overrides["oak_lod0"]["lods"][0]["path"] = "corrupted.glb"
        resolved = resolve_model_asset("tree_oak", manifest=manifest)

        assert resolved["lods"][0]["path"] == "Assets/Oak_LOD0.glb"
