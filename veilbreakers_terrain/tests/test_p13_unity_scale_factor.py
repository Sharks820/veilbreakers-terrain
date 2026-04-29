"""Tests for Fix 13.3: UNITY_SCALE_FACTOR = 0.85 applied to export coordinates.

REQ-P13-003: UNITY_SCALE_FACTOR = 0.85 applied to all exported coordinates.
Rule: scale is applied LAST before serialization; internal computation unchanged.
"""
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_unity_export import (
    UNITY_SCALE_FACTOR,
    _apply_unity_scale,
    export_unity_manifest,
)


class TestUnityScaleFactorConstant:
    """Constant value and helper function contract."""

    def test_constant_value_is_0_85(self):
        assert UNITY_SCALE_FACTOR == 0.85, (
            f"UNITY_SCALE_FACTOR must be 0.85, got {UNITY_SCALE_FACTOR}"
        )

    def test_apply_unity_scale_scalar(self):
        assert abs(_apply_unity_scale(100.0) - 85.0) < 1e-9

    def test_apply_unity_scale_list(self):
        result = _apply_unity_scale([1.0, 2.0, 4.0])
        assert isinstance(result, list)
        assert abs(result[0] - 0.85) < 1e-9
        assert abs(result[1] - 1.70) < 1e-9
        assert abs(result[2] - 3.40) < 1e-9

    def test_apply_unity_scale_zero(self):
        assert _apply_unity_scale(0.0) == 0.0

    def test_clavicle_height_reference(self):
        """1.4 terrain metres must map to 1.19 Unity units (± 0.001 tolerance)."""
        unity_height = _apply_unity_scale(1.4)
        assert abs(unity_height - 1.19) < 0.001, (
            f"Clavicle height 1.4m -> expected 1.19 Unity units, got {unity_height}"
        )


def _make_minimal_stack(tile_size: int = 4):
    """Build a minimal TerrainMaskStack for export tests."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    h = np.ones((tile_size + 1, tile_size + 1), dtype=np.float32) * 50.0
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=4.0,
        world_origin_x=100.0,
        world_origin_y=200.0,
        tile_x=0,
        tile_y=0,
        height=h,
        height_min_m=0.0,
        height_max_m=100.0,
        coordinate_system="z-up",
    )
    return stack


class TestUnityScaleAppliedToManifest:
    """Verify manifest.json coordinate values are scaled by 0.85."""

    def test_world_origin_x_scaled(self):
        stack = _make_minimal_stack()
        with tempfile.TemporaryDirectory() as td:
            manifest = export_unity_manifest(stack, Path(td))
        expected = 100.0 * UNITY_SCALE_FACTOR
        assert abs(manifest["world_origin_x_m"] - expected) < 1e-6, (
            f"world_origin_x_m: expected {expected}, got {manifest['world_origin_x_m']}"
        )

    def test_world_origin_y_scaled(self):
        stack = _make_minimal_stack()
        with tempfile.TemporaryDirectory() as td:
            manifest = export_unity_manifest(stack, Path(td))
        expected = 200.0 * UNITY_SCALE_FACTOR
        assert abs(manifest["world_origin_y_m"] - expected) < 1e-6

    def test_cell_size_scaled(self):
        stack = _make_minimal_stack()
        with tempfile.TemporaryDirectory() as td:
            manifest = export_unity_manifest(stack, Path(td))
        expected = 4.0 * UNITY_SCALE_FACTOR
        assert abs(manifest["cell_size"] - expected) < 1e-6, (
            f"cell_size: expected {expected}, got {manifest['cell_size']}"
        )

    def test_height_min_stays_in_terrain_meters_with_unity_units_sidecar(self):
        stack = _make_minimal_stack()
        with tempfile.TemporaryDirectory() as td:
            manifest = export_unity_manifest(stack, Path(td))
        assert abs(manifest["height_min_m"] - 0.0) < 1e-6
        assert abs(manifest["height_min_unity_units"] - 0.0 * UNITY_SCALE_FACTOR) < 1e-6

    def test_height_max_stays_in_terrain_meters_with_unity_units_sidecar(self):
        stack = _make_minimal_stack()
        with tempfile.TemporaryDirectory() as td:
            manifest = export_unity_manifest(stack, Path(td))
        assert abs(manifest["height_max_m"] - 100.0) < 1e-6, (
            f"height_max_m: expected 100.0, got {manifest['height_max_m']}"
        )
        assert abs(manifest["height_max_unity_units"] - 100.0 * UNITY_SCALE_FACTOR) < 1e-6

    def test_unity_world_origin_scaled(self):
        stack = _make_minimal_stack()
        with tempfile.TemporaryDirectory() as td:
            manifest = export_unity_manifest(stack, Path(td))
        uwo = manifest["unity_world_origin"]
        assert abs(uwo[0] - 100.0 * UNITY_SCALE_FACTOR) < 1e-6
        assert abs(uwo[2] - 200.0 * UNITY_SCALE_FACTOR) < 1e-6

    def test_seam_contract_is_embedded(self):
        stack = _make_minimal_stack()
        with tempfile.TemporaryDirectory() as td:
            manifest = export_unity_manifest(stack, Path(td))
        seam = manifest["seam_contract"]
        assert seam["tile_coords"] == [0, 0]
        assert seam["world_bounds"]["min_x"] == 100.0
        assert seam["edge_contracts"]["north"]["sample_count"] == 5

    def test_world_id_flows_into_manifest_and_seam_contract(self):
        stack = _make_minimal_stack()
        stack.world_id = "veilbreakers_world"
        stack.batch_id = "batch_alpha"
        with tempfile.TemporaryDirectory() as td:
            manifest = export_unity_manifest(stack, Path(td))
        assert manifest["world_id"] == "veilbreakers_world"
        assert manifest["seam_contract"]["world_id"] == "veilbreakers_world"
        assert manifest["seam_contract"]["batch_id"] == "batch_alpha"

    def test_tile_size_not_scaled(self):
        """tile_size is a pixel count — must NOT be scaled."""
        stack = _make_minimal_stack(tile_size=4)
        with tempfile.TemporaryDirectory() as td:
            manifest = export_unity_manifest(stack, Path(td))
        assert manifest["tile_size"] == 4, (
            f"tile_size must remain 4 (not scaled), got {manifest['tile_size']}"
        )


class TestUnityScaleAppliedToTreeInstances:
    """Verify tree instance positions are scaled in tree_instances.json."""

    def test_tree_position_scaled(self):
        stack = _make_minimal_stack()
        # Inject one in-bounds tree at known world position.
        tree_points = np.array([[110.0, 205.0, 50.0, 45.0, 0]], dtype=np.float64)
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
        import dataclasses
        stack = dataclasses.replace(stack, tree_instance_points=tree_points)
        with tempfile.TemporaryDirectory() as td:
            export_unity_manifest(stack, Path(td))
            trees = json.loads((Path(td) / "tree_instances.json").read_text())
        pos = trees["trees"][0]["position"]
        # After _zup_to_unity_vector (Z-up -> Y-up), then scale:
        # terrain(x=110, y=205, z=50) -> unity x=110*0.85, y=50*0.85, z=205*0.85
        assert abs(pos[0] - 110.0 * UNITY_SCALE_FACTOR) < 1e-4, f"Tree X not scaled: {pos}"
        assert abs(pos[1] - 50.0 * UNITY_SCALE_FACTOR) < 1e-4, f"Tree height not scaled: {pos}"


class TestUnityScaleConstantInSource:
    """Grep-style: UNITY_SCALE_FACTOR = 0.85 must appear in source."""

    def test_constant_string_in_source(self):
        import inspect
        import veilbreakers_terrain.handlers.terrain_unity_export as mod
        src = inspect.getsource(mod)
        # Accept either bare or type-annotated form
        assert "UNITY_SCALE_FACTOR" in src and "0.85" in src, (
            "UNITY_SCALE_FACTOR with value 0.85 not found in terrain_unity_export.py"
        )
        # The constant must evaluate to 0.85
        assert UNITY_SCALE_FACTOR == 0.85

    def test_apply_unity_scale_used_in_manifest(self):
        import inspect
        import veilbreakers_terrain.handlers.terrain_unity_export as mod
        src = inspect.getsource(mod)
        assert "_apply_unity_scale" in src
        # Must appear at least 4 times (definition + 4+ application sites)
        count = src.count("_apply_unity_scale")
        assert count >= 4, f"_apply_unity_scale only used {count} times; expected >= 4 application sites"
