"""Wave 5 — foliage placement manifest emission tests.

These cover the new symbols added to ``handlers.vegetation_system``:

* ``load_mesh_library``
* ``build_foliage_placement_manifest``
* ``write_foliage_placement_manifest``
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pytest

from veilbreakers_terrain.handlers.vegetation_system import (
    build_foliage_placement_manifest,
    load_mesh_library,
    write_foliage_placement_manifest,
)


# ---------------------------------------------------------------------------
# Stack fixture
# ---------------------------------------------------------------------------


@dataclass
class FakeStack:
    height: np.ndarray
    cell_size: float = 1.0
    world_origin_x: float = 0.0
    world_origin_y: float = 0.0
    tile_x: int = 0
    tile_y: int = 0
    tile_size: int = 32
    slope: Optional[np.ndarray] = None
    drainage: Optional[np.ndarray] = None
    cliff_label: Optional[np.ndarray] = None
    bathymetry: Optional[np.ndarray] = None
    road_sdf_dist: Optional[np.ndarray] = None
    hero_exclusion: Optional[np.ndarray] = None

    def get(self, channel_name: str):
        return getattr(self, channel_name, None)


def _stack(size: int = 16) -> FakeStack:
    return FakeStack(
        height=np.full((size, size), 50.0, dtype=np.float32),
        tile_size=size,
    )


# ---------------------------------------------------------------------------
# Mesh library fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mesh_library_file(tmp_path: Path) -> Path:
    p = tmp_path / "mesh_library.json"
    payload = {
        "tree_veil_healthy": {
            "mesh_asset_path": "Assets/Foliage/trees/veil_healthy.fbx",
            "category": "trees",
            "lod_meshes": [
                "Assets/Foliage/trees/veil_healthy_lod0.fbx",
                "Assets/Foliage/trees/veil_healthy_lod1.fbx",
            ],
            "unity_render_mode": "terrain_tree",
        },
        "rock_boulder": {
            "mesh_asset_path": "Assets/Foliage/rocks/boulder.fbx",
            "category": "rocks",
            "unity_render_mode": "gpu_instancer",
        },
    }
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# load_mesh_library
# ---------------------------------------------------------------------------


def test_load_mesh_library_dict_form(mesh_library_file: Path):
    lib = load_mesh_library(mesh_library_file)
    assert "tree_veil_healthy" in lib
    assert lib["tree_veil_healthy"]["category"] == "trees"
    assert lib["tree_veil_healthy"]["unity_render_mode"] == "terrain_tree"


def test_load_mesh_library_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_mesh_library(tmp_path / "no_such.json")


def test_load_mesh_library_invalid_json_raises(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_mesh_library(p)


def test_load_mesh_library_missing_required_field_raises(tmp_path: Path):
    p = tmp_path / "incomplete.json"
    p.write_text(json.dumps({"only": {"category": "trees"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="mesh_asset_path"):
        load_mesh_library(p)


# ---------------------------------------------------------------------------
# build_foliage_placement_manifest
# ---------------------------------------------------------------------------


def _spec(placements):
    return {
        "placements": placements,
        "biome": "thornwood_forest",
        "instance_count": len(placements),
        "species_density": {},
        "lod_distribution": {0: len(placements), 1: 0, 2: 0, 3: 0},
        "lod_distances": [15.0, 35.0, 60.0],
    }


def test_manifest_schema_basic(mesh_library_file: Path):
    lib = load_mesh_library(mesh_library_file)
    placements = [
        {
            "position": (5.0, 5.0, 50.0),
            "rotation": 30.0,
            "scale": 1.5,
            "type": "tree",
            "style": "veil_healthy",
            "mesh_name": "tree_veil_healthy",
            "lod_level": 0,
            "lod_hint": 0,
            "category": "trees",
        }
    ]
    spec = _spec(placements)
    manifest = build_foliage_placement_manifest(
        spec=spec,
        mesh_library=lib,
        stack=_stack(),
        biome_name="thornwood_forest",
    )
    assert manifest["schema_version"] == "1.0"
    assert manifest["instance_count"] == 1
    assert manifest["mesh_library"][0]["species_key"] == "tree_veil_healthy"
    inst = manifest["instances"][0]
    assert inst["mesh_id"] == 0
    assert math.isclose(inst["rotation_y_rad"], math.radians(30.0))


def test_manifest_position_norm_in_range(mesh_library_file: Path):
    lib = load_mesh_library(mesh_library_file)
    stack = _stack(size=16)
    placements = [
        {"position": (0.0, 0.0, 50.0), "rotation": 0.0, "scale": 1.0,
         "type": "tree", "style": "veil_healthy", "mesh_name": "tree_veil_healthy", "lod_level": 0},
        {"position": (15.0, 15.0, 50.0), "rotation": 90.0, "scale": 1.0,
         "type": "tree", "style": "veil_healthy", "mesh_name": "tree_veil_healthy", "lod_level": 1},
    ]
    manifest = build_foliage_placement_manifest(
        spec=_spec(placements),
        mesh_library=lib,
        stack=stack,
        biome_name="thornwood_forest",
    )
    for inst in manifest["instances"]:
        for n in inst["position_terrain_norm"]:
            assert 0.0 <= n <= 1.0


def test_manifest_road_sdf_exclusion(mesh_library_file: Path):
    lib = load_mesh_library(mesh_library_file)
    stack = _stack(size=16)
    sdf = np.full(stack.height.shape, 100.0, dtype=np.float32)
    sdf[5, 5] = 0.0
    stack.road_sdf_dist = sdf
    placements = [
        {"position": (5.0, 5.0, 50.0), "rotation": 0.0, "scale": 1.0,
         "type": "tree", "style": "veil_healthy", "mesh_name": "tree_veil_healthy", "lod_level": 0},
        {"position": (10.0, 10.0, 50.0), "rotation": 0.0, "scale": 1.0,
         "type": "tree", "style": "veil_healthy", "mesh_name": "tree_veil_healthy", "lod_level": 0},
    ]
    manifest = build_foliage_placement_manifest(
        spec=_spec(placements),
        mesh_library=lib,
        stack=stack,
        biome_name="thornwood_forest",
        sdf_road_min_m=1.0,
    )
    # First placement was right on the road → should be dropped.
    assert manifest["instance_count"] == 1
    assert manifest["instances"][0]["position_world"][0] == 10.0


def test_manifest_drops_unknown_species(mesh_library_file: Path):
    lib = load_mesh_library(mesh_library_file)
    placements = [
        {"position": (1.0, 1.0, 50.0), "rotation": 0.0, "scale": 1.0,
         "type": "fern", "style": "ghost", "mesh_name": "fern_ghost", "lod_level": 0},
    ]
    manifest = build_foliage_placement_manifest(
        spec=_spec(placements),
        mesh_library=lib,
        stack=_stack(),
        biome_name="thornwood_forest",
    )
    assert manifest["instance_count"] == 0
    assert manifest["mesh_library"] == []


def test_manifest_mesh_id_integrity(mesh_library_file: Path):
    lib = load_mesh_library(mesh_library_file)
    placements = [
        {"position": (1.0, 1.0, 50.0), "rotation": 0.0, "scale": 1.0,
         "type": "tree", "style": "veil_healthy", "mesh_name": "tree_veil_healthy", "lod_level": 0},
        {"position": (2.0, 2.0, 50.0), "rotation": 0.0, "scale": 1.0,
         "type": "rock", "style": "boulder", "mesh_name": "rock_boulder", "lod_level": 1},
    ]
    manifest = build_foliage_placement_manifest(
        spec=_spec(placements),
        mesh_library=lib,
        stack=_stack(),
        biome_name="thornwood_forest",
    )
    valid_ids = {m["mesh_id"] for m in manifest["mesh_library"]}
    for inst in manifest["instances"]:
        assert inst["mesh_id"] in valid_ids


# ---------------------------------------------------------------------------
# write_foliage_placement_manifest round-trip
# ---------------------------------------------------------------------------


def test_manifest_roundtrip(tmp_path: Path, mesh_library_file: Path):
    lib = load_mesh_library(mesh_library_file)
    placements = [
        {"position": (1.0, 1.0, 50.0), "rotation": 0.0, "scale": 1.2,
         "type": "tree", "style": "veil_healthy", "mesh_name": "tree_veil_healthy", "lod_level": 0},
    ]
    manifest = build_foliage_placement_manifest(
        spec=_spec(placements),
        mesh_library=lib,
        stack=_stack(),
        biome_name="thornwood_forest",
    )
    out = tmp_path / "foliage_placement_manifest.json"
    written = write_foliage_placement_manifest(manifest, out)
    assert written == out
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["instance_count"] == manifest["instance_count"]
    assert loaded["species_density"] == manifest["species_density"]
