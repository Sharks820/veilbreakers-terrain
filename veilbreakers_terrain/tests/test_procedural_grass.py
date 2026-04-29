"""Unit tests for veilbreakers_terrain.handlers.procedural_grass."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from veilbreakers_terrain.handlers.procedural_grass import (
    DEFAULT_BIOME_ID_MAP,
    GrassPlacementRecord,
    GrassSpecies,
    ProceduralGrassSystem,
    VEILBREAKERS_GRASS_SPECIES,
    pass_procedural_grass,
    register_procedural_grass_pass,
)
from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
from veilbreakers_terrain.handlers.terrain_semantics import BBox, TerrainIntentState, TerrainMaskStack, TerrainPipelineState


# ---------------------------------------------------------------------------
# Minimal stack stand-in
# ---------------------------------------------------------------------------


def _set_channel(stack: TerrainMaskStack, channel: str, value):
    stack.set(channel, value, "test_fixture")
    return value


def _flat_stack(size: int = 32, cell_size: float = 1.0) -> TerrainMaskStack:
    height = np.zeros((size, size), dtype=np.float32) + 50.0
    slope = np.zeros((size, size), dtype=np.float32)
    drainage = np.full((size, size), 0.3, dtype=np.float32)
    biome_id = np.full((size, size), DEFAULT_BIOME_ID_MAP["thornwood_forest"], dtype=np.uint8)
    stack = TerrainMaskStack(
        tile_size=size,
        cell_size=cell_size,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    _set_channel(stack, "slope", slope)
    _set_channel(stack, "drainage", drainage)
    _set_channel(stack, "biome_id", biome_id)
    return stack


# ---------------------------------------------------------------------------
# Species library smoke
# ---------------------------------------------------------------------------


def test_default_species_library_complete():
    names = {s.name for s in VEILBREAKERS_GRASS_SPECIES}
    assert {"dead_withered_grass", "swamp_reeds", "dark_moss_patches",
            "twisted_fern", "ash_grass", "blood_moss"} <= names


def test_grass_species_matches_biome_wildcard():
    s = GrassSpecies(name="x", biomes=("*",))
    assert s.matches_biome("any_biome")


def test_grass_species_matches_biome_explicit():
    s = GrassSpecies(name="x", biomes=("thornwood_forest",))
    assert s.matches_biome("thornwood_forest")
    assert not s.matches_biome("desert")


# ---------------------------------------------------------------------------
# Placement on a flat stack — must produce instances
# ---------------------------------------------------------------------------


def test_generate_grass_placement_basic():
    stack = _flat_stack()
    species = (GrassSpecies(name="test_grass", density_per_sqm=0.5,
                            wetness_affinity=0.3, biomes=("*",)),)
    sys_ = ProceduralGrassSystem(rng_seed=1)
    records = sys_.generate_grass_placement(stack, species, cell_size_m=1.0)
    assert len(records) > 0
    for r in records:
        assert r.species == "test_grass"
        for n in r.position_terrain_norm:
            assert 0.0 <= n <= 1.0


def test_generate_grass_placement_requires_height():
    stack = _flat_stack()
    object.__setattr__(stack, "height", None)
    sys_ = ProceduralGrassSystem()
    with pytest.raises(ValueError, match="height"):
        sys_.generate_grass_placement(stack, [GrassSpecies(name="x")])


# ---------------------------------------------------------------------------
# Slope SDF / cliff exclusion
# ---------------------------------------------------------------------------


def test_slope_excludes_steep_cells():
    stack = _flat_stack()
    # Make right half of terrain steep.
    stack.slope[:, stack.slope.shape[1] // 2:] = 80.0
    species = (GrassSpecies(name="g", density_per_sqm=2.0, slope_max_deg=30.0, biomes=("*",)),)
    sys_ = ProceduralGrassSystem(rng_seed=2)
    records = sys_.generate_grass_placement(stack, species, cell_size_m=1.0)
    # All survivors should be on the flat half (col index < 16).
    for r in records:
        col_world_x = r.position_world[0]
        assert col_world_x < 16.0


def test_cliff_label_excludes_cliff_cells():
    stack = _flat_stack()
    cliff = np.zeros_like(stack.height, dtype=np.uint8)
    cliff[10:14, 10:14] = 1  # 4x4 cliff patch
    _set_channel(stack, "cliff_label", cliff)
    species = (GrassSpecies(name="g", density_per_sqm=4.0, biomes=("*",)),)
    sys_ = ProceduralGrassSystem(rng_seed=3)
    records = sys_.generate_grass_placement(stack, species, cell_size_m=1.0,
                                            sdf_cliff_min_m=0.0)
    # No records should land in the cliff cells (1 m cell size, world coords).
    for r in records:
        wx, wy, _ = r.position_world
        cx = int(wx)
        cy = int(wy)
        if 10 <= cx < 14 and 10 <= cy < 14:
            pytest.fail(f"Placement on cliff cell at ({cx},{cy})")


def test_road_sdf_excludes_near_road():
    stack = _flat_stack()
    sdf = np.full(stack.height.shape, 100.0, dtype=np.float32)
    sdf[:, 16] = 0.0  # vertical road line
    sdf[:, 15] = 1.0
    sdf[:, 17] = 1.0
    sdf[:, 14] = 2.0
    sdf[:, 18] = 2.0
    _set_channel(stack, "road_sdf_dist", sdf)
    species = (GrassSpecies(name="g", density_per_sqm=4.0, biomes=("*",), min_spacing_m=0.0),)
    sys_ = ProceduralGrassSystem(rng_seed=4)
    records = sys_.generate_grass_placement(stack, species, cell_size_m=1.0,
                                            sdf_road_min_m=1.5)
    for r in records:
        col = int(r.position_world[0])
        # Must not be within sdf < 1.5 m (cols 15, 16, 17).
        assert col not in (15, 16, 17)


def test_water_excludes_submerged_cells():
    stack = _flat_stack()
    ws = np.zeros_like(stack.height, dtype=np.float32)
    ws[:8, :] = 1000.0  # massive water elevation in top strip
    _set_channel(stack, "water_surface", ws)
    species = (GrassSpecies(name="g", density_per_sqm=4.0, biomes=("*",)),)
    sys_ = ProceduralGrassSystem(rng_seed=5)
    records = sys_.generate_grass_placement(stack, species, cell_size_m=1.0)
    for r in records:
        wy = r.position_world[1]
        assert wy >= 8.0  # not in submerged top strip


def test_pass_procedural_grass_writes_density_and_placement_channels():
    stack = _flat_stack(size=16)
    hero = np.zeros_like(stack.height, dtype=np.float32)
    hero[:, :8] = 1.0
    _set_channel(stack, "hero_exclusion", hero)
    intent = TerrainIntentState(
        seed=123,
        region_bounds=BBox(0.0, 0.0, 16.0, 16.0),
        tile_size=16,
        cell_size=1.0,
        composition_hints={
            "grass_species_library": (
                GrassSpecies(name="pass_grass", density_per_sqm=1.0, biomes=("*",), min_spacing_m=0.0),
            ),
            "grass_max_instances_per_species": 256,
        },
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    result = pass_procedural_grass(state, region=None)

    assert result.status == "ok"
    assert stack.grass_density_map is not None
    assert stack.detail_density is not None
    assert "pass_grass" in stack.detail_density
    assert stack.grass_placement_records
    assert np.count_nonzero(stack.grass_density_map[:, :8]) == 0
    assert np.count_nonzero(stack.grass_density_map[:, 8:]) > 0


def test_register_procedural_grass_pass_adds_controller_entry():
    TerrainPassController.PASS_REGISTRY.clear()
    register_procedural_grass_pass()
    definition = TerrainPassController.PASS_REGISTRY["pass_procedural_grass"]
    assert "grass_density_map" in definition.produces_channels
    assert "height" in definition.requires_channels


def test_biome_filter_drops_wrong_biome():
    stack = _flat_stack()
    _set_channel(stack, "biome_id", np.full(stack.height.shape, DEFAULT_BIOME_ID_MAP["desert"], dtype=np.uint8))
    species = (GrassSpecies(name="forest_only",
                            density_per_sqm=4.0,
                            biomes=("thornwood_forest",)),)
    sys_ = ProceduralGrassSystem(rng_seed=6)
    records = sys_.generate_grass_placement(stack, species, cell_size_m=1.0)
    assert records == []


def test_wetness_affinity_prefers_drainage_match():
    stack = _flat_stack()
    # Half dry, half wet
    drainage = np.zeros_like(stack.height, dtype=np.float32)
    drainage[:, : drainage.shape[1] // 2] = 0.05
    drainage[:, drainage.shape[1] // 2 :] = 0.95
    _set_channel(stack, "drainage", drainage)

    dry_species = (GrassSpecies(name="dry", density_per_sqm=2.0, wetness_affinity=0.0, biomes=("*",)),)
    wet_species = (GrassSpecies(name="wet", density_per_sqm=2.0, wetness_affinity=1.0, biomes=("*",)),)
    sys_ = ProceduralGrassSystem(rng_seed=7)
    dry_recs = sys_.generate_grass_placement(stack, dry_species, cell_size_m=1.0)
    wet_recs = sys_.generate_grass_placement(stack, wet_species, cell_size_m=1.0)

    if dry_recs:
        avg_x_dry = sum(r.position_world[0] for r in dry_recs) / len(dry_recs)
        assert avg_x_dry < drainage.shape[1] / 2  # skewed toward dry half
    if wet_recs:
        avg_x_wet = sum(r.position_world[0] for r in wet_recs) / len(wet_recs)
        assert avg_x_wet > drainage.shape[1] / 2


# ---------------------------------------------------------------------------
# Manifest writing
# ---------------------------------------------------------------------------


def test_write_grass_manifest_atomic(tmp_path: Path):
    rec = GrassPlacementRecord(
        species="test_grass",
        position_world=(1.0, 2.0, 3.0),
        position_terrain_norm=(0.1, 0.2, 0.3),
        rotation_y_rad=0.5,
        scale=1.0,
        biome="thornwood_forest",
        moisture=0.4,
    )
    sys_ = ProceduralGrassSystem()
    out = tmp_path / "grass_manifest.json"
    written = sys_.write_grass_manifest([rec], out, biome="thornwood_forest")
    assert written == out
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == "1.0"
    assert payload["instance_count"] == 1
    assert payload["mesh_library"][0]["species_key"] == "test_grass"
    assert payload["instances"][0]["position_world"] == [1.0, 2.0, 3.0]
    assert payload["instances"][0]["position_terrain_norm"] == [0.1, 0.2, 0.3]


def test_geometry_nodes_script_written(tmp_path: Path):
    sys_ = ProceduralGrassSystem()
    out = tmp_path / "grass_node.py"
    p = sys_.generate_ground_cover_geometry_nodes_script(
        VEILBREAKERS_GRASS_SPECIES[0], out
    )
    assert p == out
    text = out.read_text(encoding="utf-8")
    assert "GeometryNodeTree" in text
    assert "DistributePointsOnFaces" in text
    assert VEILBREAKERS_GRASS_SPECIES[0].name in text
