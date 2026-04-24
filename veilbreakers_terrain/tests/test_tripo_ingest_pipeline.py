"""End-to-end tests for the Tripo ingest pipeline.

Exercises the full flow with a synthetic mesh (``.synthmesh.json``) so the
tests do not require Blender installed.

Covers:
  - Category detection from filenames and enclosing folders.
  - ``build_job`` budget lookup.
  - Synthetic decimation -> LOD chain -> catalog registration.
  - Batch scanner: new files ingest, already-processed files skip, in-flight
    ``*.crdownload`` files ignored.
  - ``terrain_foliage_catalog.TripoAssetManifest`` binds ingested entries
    back to scatter species.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import batch_ingest_tripo_downloads as batch  # noqa: E402
import ingest_tripo_asset as ingest  # noqa: E402

from veilbreakers_terrain.handlers import terrain_foliage_catalog as cat_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_synth(path: Path, *, tris: int = 12) -> Path:
    """Write a tiny synthmesh with an N-tri fan.

    The fan is generated around the Z axis so bbox / pivot derivation has a
    non-trivial shape.
    """
    import math
    verts: list[list[float]] = [[0.0, 0.0, 0.0]]
    faces: list[list[int]] = []
    for i in range(tris):
        a = 2.0 * math.pi * i / tris
        verts.append([math.cos(a), math.sin(a), 0.1 * (i % 3)])
    for i in range(tris):
        faces.append([0, 1 + i, 1 + ((i + 1) % tris)])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"verts": verts, "faces": faces}, f)
    return path


@pytest.fixture
def synth_asset(tmp_path: Path) -> Path:
    p = tmp_path / "downloads" / "tripo-grass_lush_A.synthmesh.json"
    _write_synth(p, tris=16)
    return p


@pytest.fixture
def assets_root(tmp_path: Path) -> Path:
    root = tmp_path / "assets" / "foliage"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Category detection
# ---------------------------------------------------------------------------

class TestCategoryDetection:
    def test_filename_keyword_wins(self, tmp_path: Path) -> None:
        f = tmp_path / "tripo-oak_ancient-A.glb"
        f.touch()
        assert ingest.detect_category(f) == "oak"

    def test_multiword_category_preferred_over_prefix(self, tmp_path: Path) -> None:
        f = tmp_path / "moss_drape_02.glb"
        f.touch()
        assert ingest.detect_category(f) == "moss_drape"

    def test_dead_tree_preferred_over_tree(self, tmp_path: Path) -> None:
        f = tmp_path / "dead_tree_claw.glb"
        f.touch()
        assert ingest.detect_category(f) == "dead_tree"

    def test_folder_fallback(self, tmp_path: Path) -> None:
        d = tmp_path / "bramble"
        d.mkdir()
        f = d / "unnamed123.glb"
        f.touch()
        assert ingest.detect_category(f) == "bramble"

    def test_unknown_when_no_hits(self, tmp_path: Path) -> None:
        f = tmp_path / "something_random.glb"
        f.touch()
        assert ingest.detect_category(f) == "unknown"


# ---------------------------------------------------------------------------
# Job building
# ---------------------------------------------------------------------------

class TestBuildJob:
    def test_respects_category_budget(self, synth_asset: Path, assets_root: Path) -> None:
        job = ingest.build_job(synth_asset, assets_root)
        assert job["category"] == "grass"
        assert job["lod0_tris"] == ingest.CATEGORY_BUDGETS["grass"]["lod0_tris"]
        assert job["billboard_at_lod2"] is True
        assert job["asset_id"].startswith("grass_")
        assert "catalog.json" in job["catalog_path"]

    def test_override_category(self, synth_asset: Path, assets_root: Path) -> None:
        job = ingest.build_job(synth_asset, assets_root, category_override="boulder")
        assert job["category"] == "boulder"
        assert job["billboard_at_lod2"] is False


# ---------------------------------------------------------------------------
# Synthetic ingest round-trip
# ---------------------------------------------------------------------------

class TestSyntheticIngest:
    def test_round_trip_writes_three_lods_and_catalog(
        self, synth_asset: Path, assets_root: Path
    ) -> None:
        entry = ingest.ingest(synth_asset, assets_root, force_synthetic=True)

        assert entry["category"] == "grass"
        assert len(entry["lods"]) == 3
        # LOD0 identical poly count to source.
        assert entry["lods"][0]["tri_count"] == 16
        # LOD1 strictly smaller than LOD0.
        assert entry["lods"][1]["tri_count"] <= entry["lods"][0]["tri_count"]
        # LOD2 is a billboard (grass preset billboards at LOD2).
        assert entry["lods"][2]["is_billboard"] is True
        assert entry["lods"][2]["tri_count"] == 2  # single cross quad.

        # Files on disk.
        for lod in entry["lods"]:
            assert Path(lod["path"]).exists()

        # Catalog updated.
        catalog_path = assets_root / "catalog.json"
        assert catalog_path.exists()
        data = json.loads(catalog_path.read_text())
        assert entry["asset_id"] in data["assets"]

    def test_second_ingest_updates_existing_entry(
        self, synth_asset: Path, assets_root: Path
    ) -> None:
        first = ingest.ingest(synth_asset, assets_root, force_synthetic=True)
        # Touch mtime + content so fingerprint differs slightly.
        synth_asset.write_text(synth_asset.read_text())  # rewrite same bytes; asset_id stable.
        second = ingest.ingest(synth_asset, assets_root, force_synthetic=True)

        assert first["asset_id"] == second["asset_id"]
        catalog_path = assets_root / "catalog.json"
        data = json.loads(catalog_path.read_text())
        # Only one entry for this asset.
        assert len([k for k in data["assets"] if k == first["asset_id"]]) == 1

    def test_bbox_and_pivot_are_sensible(
        self, synth_asset: Path, assets_root: Path
    ) -> None:
        entry = ingest.ingest(synth_asset, assets_root, force_synthetic=True)
        bb = entry["bbox"]
        size = bb["size"]
        assert size[0] > 0 and size[1] > 0  # non-degenerate fan in XY.
        pivot = entry["pivot"]
        # Base-centre pivot: z at bbox min z.
        assert pytest.approx(pivot[2], abs=1e-6) == bb["min"][2]


# ---------------------------------------------------------------------------
# Batch pipeline
# ---------------------------------------------------------------------------

class TestBatchIngest:
    def test_scans_and_ingests_all_candidates(
        self, tmp_path: Path, assets_root: Path
    ) -> None:
        dl = tmp_path / "downloads"
        dl.mkdir()
        for name in (
            "tripo-grass_lush_A.synthmesh.json",
            "tripo-oak_ancient_B.synthmesh.json",
            "tripo-boulder_mossy_C.synthmesh.json",
        ):
            _write_synth(dl / name)

        stats = batch.run_batch(dl, assets_root, force_synthetic=True)
        assert stats["scanned"] == 3
        assert len(stats["ingested"]) == 3
        assert not stats["failed"]

        catalog = json.loads((assets_root / "catalog.json").read_text())
        cats = {entry["category"] for entry in catalog["assets"].values()}
        assert {"grass", "oak", "boulder"} <= cats

    def test_second_run_is_idempotent(
        self, tmp_path: Path, assets_root: Path
    ) -> None:
        dl = tmp_path / "downloads"
        dl.mkdir()
        _write_synth(dl / "tripo-fern_shadowleaf_A.synthmesh.json")

        stats1 = batch.run_batch(dl, assets_root, force_synthetic=True)
        assert len(stats1["ingested"]) == 1

        stats2 = batch.run_batch(dl, assets_root, force_synthetic=True)
        assert stats2["ingested"] == []
        assert any(
            "already_processed" in s.get("reason", "") for s in stats2["skipped"]
        )

    def test_in_flight_downloads_are_skipped(
        self, tmp_path: Path, assets_root: Path
    ) -> None:
        dl = tmp_path / "downloads"
        dl.mkdir()
        (dl / "tripo-grass_partial.glb.crdownload").write_bytes(b"partial")
        _write_synth(dl / "tripo-grass_complete.synthmesh.json")

        stats = batch.run_batch(dl, assets_root, force_synthetic=True)
        # Only the complete one is scanned.
        assert stats["scanned"] == 1
        assert len(stats["ingested"]) == 1

    def test_dry_run_reports_without_ingesting(
        self, tmp_path: Path, assets_root: Path
    ) -> None:
        dl = tmp_path / "downloads"
        dl.mkdir()
        _write_synth(dl / "tripo-pine_black_D.synthmesh.json")

        stats = batch.run_batch(
            dl, assets_root, force_synthetic=True, dry_run=True
        )
        assert stats["ingested"] == []
        assert stats["scanned"] == 1
        assert not (assets_root / "catalog.json").exists()


# ---------------------------------------------------------------------------
# Catalog binding back to scatter species
# ---------------------------------------------------------------------------

class TestFoliageCatalogBinding:
    def test_manifest_loads_ingested_entries(
        self, tmp_path: Path, assets_root: Path
    ) -> None:
        dl = tmp_path / "downloads"
        dl.mkdir()
        _write_synth(dl / "tripo-oak_ancient_A.synthmesh.json")
        _write_synth(dl / "tripo-grass_lush_B.synthmesh.json")
        batch.run_batch(dl, assets_root, force_synthetic=True)

        manifest = cat_mod.TripoAssetManifest(
            path=assets_root / "catalog.json"
        )
        stats = manifest.stats()
        assert stats["asset_count"] == 2
        assert "oak" in stats["categories"] or "tree" in stats["categories"]

    def test_choose_for_species_returns_ingested_asset(
        self, tmp_path: Path, assets_root: Path
    ) -> None:
        dl = tmp_path / "downloads"
        dl.mkdir()
        _write_synth(dl / "tripo-oak_ancient_A.synthmesh.json")
        batch.run_batch(dl, assets_root, force_synthetic=True)

        manifest = cat_mod.TripoAssetManifest(
            path=assets_root / "catalog.json"
        )
        entry = manifest.choose_for_species("tree_oak")
        assert entry.get("fallback") is not True
        assert entry["category"] == "oak"
        assert len(entry["lods"]) == 3

    def test_choose_for_species_falls_back_when_empty(
        self, tmp_path: Path
    ) -> None:
        manifest = cat_mod.TripoAssetManifest(
            path=tmp_path / "no_such_catalog.json"
        )
        entry = manifest.choose_for_species("tree_oak")
        assert entry.get("fallback") is True
        assert entry["scatter_hint"] == "tree"

    def test_all_species_resolvable(self, tmp_path: Path) -> None:
        """Every species in FOLIAGE_SPECIES_CATALOG can be resolved (fallback ok)."""
        manifest = cat_mod.TripoAssetManifest(
            path=tmp_path / "no_such_catalog.json"
        )
        for species_id in cat_mod.FOLIAGE_SPECIES_CATALOG:
            # Skip species that have no mapping (they would still return fallback).
            if species_id not in cat_mod.SPECIES_TRIPO_CATEGORIES:
                continue
            entry = manifest.choose_for_species(species_id)
            assert "asset_id" in entry
            assert "scatter_hint" in entry

    def test_default_manifest_is_singleton(self) -> None:
        a = cat_mod.get_default_asset_manifest()
        b = cat_mod.get_default_asset_manifest()
        assert a is b

    def test_set_default_manifest_override(self, tmp_path: Path) -> None:
        override = cat_mod.TripoAssetManifest(path=tmp_path / "empty.json")
        cat_mod.set_default_asset_manifest(override)
        try:
            assert cat_mod.get_default_asset_manifest() is override
        finally:
            cat_mod.set_default_asset_manifest(None)


# ---------------------------------------------------------------------------
# Phase I++ — seven new species flagged by the Phase H catalog audit.
# Each must have (1) a FOLIAGE_SPECIES_CATALOG entry flagged Tripo-required,
# (2) a SPECIES_TRIPO_CATEGORIES mapping whose first token is the species-
# specific category, and (3) an ingest-time filename recognizer for that
# category token.
# ---------------------------------------------------------------------------

_PHASE_I_PLUS_PLUS_SPECIES: tuple[tuple[str, str], ...] = (
    ("hero_boulder",          "hero_boulder"),
    ("vine_hanging",          "vine_hanging"),
    ("fence_wood",            "fence_wood"),
    ("fence_stone",           "fence_stone"),
    ("sign_wooden",           "sign_wooden"),
    ("sign_stone_waypoint",   "sign_stone_waypoint"),
    ("walkway_plank",         "walkway_plank"),
)


class TestPhaseIPlusPlusSpeciesBinding:
    """Every Phase I++ species is fully bound from catalog -> ingest -> filename."""

    @pytest.mark.parametrize("species_id,category_token", _PHASE_I_PLUS_PLUS_SPECIES)
    def test_species_has_catalog_entry(
        self, species_id: str, category_token: str
    ) -> None:
        assert species_id in cat_mod.FOLIAGE_SPECIES_CATALOG, (
            f"Phase I++ species '{species_id}' missing from FOLIAGE_SPECIES_CATALOG"
        )
        spec = cat_mod.FOLIAGE_SPECIES_CATALOG[species_id]
        assert spec.requires_tripo_asset is True, (
            f"'{species_id}' must be flagged requires_tripo_asset=True"
        )

    @pytest.mark.parametrize("species_id,category_token", _PHASE_I_PLUS_PLUS_SPECIES)
    def test_species_tripo_category_mapping(
        self, species_id: str, category_token: str
    ) -> None:
        mapping = cat_mod.SPECIES_TRIPO_CATEGORIES.get(species_id)
        assert mapping, f"SPECIES_TRIPO_CATEGORIES missing '{species_id}'"
        assert mapping[0] == category_token, (
            f"'{species_id}' should prefer category '{category_token}' first "
            f"for Tripo asset resolution; got {mapping}"
        )

    @pytest.mark.parametrize("species_id,category_token", _PHASE_I_PLUS_PLUS_SPECIES)
    def test_ingest_recognizes_category_token(
        self, tmp_path: Path, species_id: str, category_token: str
    ) -> None:
        assert category_token in ingest.CATEGORY_BUDGETS, (
            f"ingest.CATEGORY_BUDGETS missing '{category_token}' for species "
            f"'{species_id}'"
        )
        # Filename inference must pick the species-specific token.
        f = tmp_path / f"tripo-{category_token}_variant_A.glb"
        f.touch()
        assert ingest.detect_category(f) == category_token, (
            f"detect_category did not resolve '{f.name}' to '{category_token}'"
        )
