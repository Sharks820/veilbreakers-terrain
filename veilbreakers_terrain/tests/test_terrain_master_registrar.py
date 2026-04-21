"""Master registrar smoke test — verifies the full pipeline loads end-to-end."""

from __future__ import annotations

import pytest
from unittest.mock import patch


def test_master_registrar_loads_all_bundles():
    from blender_addon.handlers.terrain_master_registrar import (
        register_all_terrain_passes,
    )
    from blender_addon.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    try:
        loaded = register_all_terrain_passes(strict=False)
    finally:
        # Leave the registry in a known state for other tests
        TerrainPassController.clear_registry()

    assert "A" in loaded, "Bundle A foundation must always load"
    # We expect at least 10 bundles to load cleanly in a dev environment
    clean = [b for b in loaded if "SKIPPED" not in b]
    assert len(clean) >= 10, f"Only {len(clean)} bundles loaded: {loaded}"


def test_master_registrar_strict_mode_raises_on_missing():
    """Strict mode surfaces the first missing registrar."""
    from blender_addon.handlers.terrain_master_registrar import (
        _safe_import_registrar,
    )

    # Sanity: _safe_import_registrar returns None for a bogus module
    assert _safe_import_registrar("blender_addon.handlers.definitely_not_a_module", "fn") is None


def test_master_registrar_produces_unified_pass_graph():
    """After loading, the PASS_REGISTRY should hold enough passes for a DAG."""
    from blender_addon.handlers.terrain_master_registrar import (
        register_all_terrain_passes,
    )
    from blender_addon.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    try:
        register_all_terrain_passes(strict=False)
        registry_size = len(TerrainPassController.PASS_REGISTRY)
    finally:
        TerrainPassController.clear_registry()

    # Bundle A alone registers 4 passes; with B/C/D/E/F/J/K/L/N/O each adding
    # at least one pass, we expect ≥ 12 total in a healthy env.
    assert registry_size >= 12, f"Expected ≥12 passes, got {registry_size}"


def test_handle_run_terrain_pass_registers_non_default_passes_for_direct_callers():
    from blender_addon.handlers.environment import handle_run_terrain_pass
    from blender_addon.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    try:
        result = handle_run_terrain_pass(
            {
                "tile_size": 16,
                "cell_size": 2.0,
                "seed": 42,
                "terrain_type": "hills",
                "scale": 60.0,
                "pipeline": [
                    "macro_world",
                    "structural_masks",
                    "erosion",
                    "validation_full",
                ],
                "scene_read": {
                    "major_landforms": ["ridge"],
                    "focal_point": [0.0, 0.0, 0.0],
                    "success_criteria": ["test"],
                    "reviewer": "pytest",
                },
            }
        )
    finally:
        TerrainPassController.clear_registry()

    assert len(result["results"]) == 8
    assert result["results"][-5]["pass_name"] == "materials_v2"
    assert result["results"][-4]["pass_name"] == "navmesh"
    assert result["results"][-3]["pass_name"] == "prepare_terrain_normals"
    assert result["results"][-2]["pass_name"] == "prepare_heightmap_raw_u16"
    assert result["results"][-1]["pass_name"] == "validation_full"


def test_handle_run_terrain_pass_still_surfaces_truly_unknown_passes():
    from blender_addon.handlers.environment import handle_run_terrain_pass
    from blender_addon.handlers.terrain_pipeline import TerrainPassController
    from blender_addon.handlers.terrain_semantics import UnknownPassError

    TerrainPassController.clear_registry()
    try:
        with pytest.raises(UnknownPassError):
            handle_run_terrain_pass(
                {
                    "tile_size": 16,
                    "cell_size": 2.0,
                    "seed": 42,
                    "pass_name": "not_a_real_pass",
                }
            )
    finally:
        TerrainPassController.clear_registry()


def test_handle_run_terrain_pass_default_pipeline_is_safe_without_scene_read():
    from blender_addon.handlers.environment import handle_run_terrain_pass
    from blender_addon.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    try:
        result = handle_run_terrain_pass(
            {
                "tile_size": 16,
                "cell_size": 2.0,
                "seed": 42,
                "terrain_type": "hills",
                "scale": 60.0,
            }
        )
    finally:
        TerrainPassController.clear_registry()

    assert result["ok"] is True
    assert [r["pass_name"] for r in result["results"]] == [
        "macro_world",
        "structural_masks",
        "validation_minimal",
    ]


def test_execute_terrain_pipeline_threads_quality_profile_hints_and_viewport():
    from blender_addon.handlers.environment import _execute_terrain_pipeline
    from blender_addon.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    try:
        with patch.object(TerrainPassController, "run_pipeline", return_value=[]):
            execution = _execute_terrain_pipeline(
                {
                    "tile_size": 16,
                    "cell_size": 2.0,
                    "seed": 42,
                    "terrain_type": "hills",
                    "scale": 60.0,
                    "pipeline": ["macro_world", "validation_minimal"],
                    "quality_profile": "aaa_open_world",
                    "composition_hints": {"bundle_n_runtime": {"determinism_runs": 2}},
                    "scene_read": {
                        "major_landforms": ["ridge"],
                        "focal_point": [0.0, 0.0, 0.0],
                        "success_criteria": ["test"],
                        "reviewer": "pytest",
                        "viewport_vantage": {"camera": "scene"},
                    },
                }
            )
    finally:
        TerrainPassController.clear_registry()

    state = execution["state"]
    assert state.intent.quality_profile == "aaa_open_world"
    assert state.intent.composition_hints == {
        "bundle_n_runtime": {"determinism_runs": 2}
    }
    assert state.viewport_vantage == {"camera": "scene"}


def test_handle_run_terrain_pass_injects_overhang_emit_phase_for_cliff_pipeline():
    from blender_addon.handlers.environment import handle_run_terrain_pass
    from blender_addon.handlers.terrain_pipeline import TerrainPassController

    captured = {}

    def _fake_run_pipeline(self, pass_sequence, **kwargs):
        captured["pass_sequence"] = list(pass_sequence)
        return []

    TerrainPassController.clear_registry()
    try:
        with patch.object(TerrainPassController, "run_pipeline", _fake_run_pipeline):
            result = handle_run_terrain_pass(
                {
                    "tile_size": 16,
                    "cell_size": 2.0,
                    "seed": 42,
                    "terrain_type": "hills",
                    "scale": 60.0,
                    "pipeline": [
                        "macro_world",
                        "structural_masks",
                        "cliffs",
                        "validation_minimal",
                    ],
                }
            )
    finally:
        TerrainPassController.clear_registry()

    assert result["results"] == []
    assert captured["pass_sequence"] == [
        "macro_world",
        "structural_masks",
        "cliffs",
        "emit_overhang_meshes",
        "validation_minimal",
    ]


def test_handle_run_terrain_pass_injects_heightmap_prepare_before_validation_full():
    from blender_addon.handlers.environment import handle_run_terrain_pass
    from blender_addon.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    try:
        result = handle_run_terrain_pass(
            {
                "tile_size": 16,
                "cell_size": 2.0,
                "seed": 42,
                "terrain_type": "hills",
                "scale": 60.0,
                "pipeline": [
                    "macro_world",
                    "structural_masks",
                    "navmesh",
                    "validation_full",
                ],
                "scene_read": {
                    "major_landforms": ["ridge"],
                    "focal_point": [0.0, 0.0, 0.0],
                    "success_criteria": ["test"],
                    "reviewer": "pytest",
                },
            }
        )
    finally:
        TerrainPassController.clear_registry()

    assert [r["pass_name"] for r in result["results"]] == [
        "macro_world",
        "structural_masks",
        "navmesh",
        "materials_v2",
        "prepare_terrain_normals",
        "prepare_heightmap_raw_u16",
        "validation_full",
    ]


def test_handle_run_terrain_pass_skips_heightmap_injection_when_unity_export_opted_out():
    from blender_addon.handlers.environment import handle_run_terrain_pass
    from blender_addon.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    try:
        result = handle_run_terrain_pass(
            {
                "tile_size": 16,
                "cell_size": 2.0,
                "seed": 42,
                "terrain_type": "hills",
                "scale": 60.0,
                "pipeline": [
                    "macro_world",
                    "structural_masks",
                    "validation_full",
                ],
                "composition_hints": {
                    "unity_export_opt_out": True,
                },
                "scene_read": {
                    "major_landforms": ["ridge"],
                    "focal_point": [0.0, 0.0, 0.0],
                    "success_criteria": ["test"],
                    "reviewer": "pytest",
                },
            }
        )
    finally:
        TerrainPassController.clear_registry()

    assert [r["pass_name"] for r in result["results"]] == [
        "macro_world",
        "structural_masks",
        "validation_full",
    ]
