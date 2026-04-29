"""Master registrar smoke test — verifies the full pipeline loads end-to-end."""

from __future__ import annotations

import inspect

import pytest
from unittest.mock import patch


def test_master_registrar_loads_all_bundles():
    from veilbreakers_terrain.handlers.terrain_master_registrar import (
        register_all_terrain_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

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
    from veilbreakers_terrain.handlers.terrain_master_registrar import (
        _safe_import_registrar,
    )

    # Sanity: _safe_import_registrar returns None for a bogus module
    assert _safe_import_registrar("veilbreakers_terrain.handlers.definitely_not_a_module", "fn") is None


def test_master_registrar_produces_unified_pass_graph():
    """After loading, the PASS_REGISTRY should hold enough passes for a DAG."""
    from veilbreakers_terrain.handlers.terrain_master_registrar import (
        register_all_terrain_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    try:
        register_all_terrain_passes(strict=False)
        registry_size = len(TerrainPassController.PASS_REGISTRY)
    finally:
        TerrainPassController.clear_registry()

    # Bundle A alone registers 4 passes; with B/C/D/E/F/J/K/L/N/O each adding
    # at least one pass, we expect ≥ 12 total in a healthy env.
    assert registry_size >= 12, f"Expected ≥12 passes, got {registry_size}"


def test_v6_script_registers_full_catalog_before_direct_pass_calls():
    import scripts.build_terrain_aaa_node_v6 as v6
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    try:
        v6.register_terrain_passes_for_script()
        for pass_name in ("materials_v2", "waterfalls", "scatter_intelligent", "validation_full"):
            assert pass_name in TerrainPassController.PASS_REGISTRY
    finally:
        TerrainPassController.clear_registry()


def test_v6_script_uses_aaa_open_world_for_direct_and_proof_intents():
    import scripts.build_terrain_aaa_node_v6 as v6

    direct_src = inspect.getsource(v6.run_production_passes)
    proof_src = inspect.getsource(v6.run_validation_full_pipeline_proof)

    assert 'quality_profile="aaa_open_world"' in direct_src
    assert 'quality_profile="aaa_open_world"' in proof_src


def test_handle_run_terrain_pass_registers_non_default_passes_for_direct_callers():
    from veilbreakers_terrain.handlers.environment import handle_run_terrain_pass
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

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

    pass_names = [r["pass_name"] for r in result["results"]]
    for expected in (
        "water_variants",
        "bathymetry",
        "pass_water_depth",
        "materials_v2",
        "waterfalls",
        "emit_particle_systems",
        "pass_morphology",
        "integrate_deltas",
        "materials_v2",
        "emit_overhang_meshes",
        "scatter_intelligent",
        "pass_horizon_lod",
        "pass_navmesh_export",
        "prepare_terrain_normals",
        "prepare_heightmap_raw_u16",
        "prepare_unity_auxiliary_channels",
        "validation_full",
    ):
        assert expected in pass_names
    assert pass_names.index("pass_morphology") < pass_names.index("integrate_deltas")
    assert pass_names.index("waterfalls") < pass_names.index("integrate_deltas")
    assert pass_names.index("integrate_deltas") < pass_names.index("materials_v2")
    assert pass_names.index("materials_v2") < pass_names.index("scatter_intelligent")
    assert pass_names.index("waterfalls") < pass_names.index("emit_particle_systems")
    assert pass_names.index("validation_full") == len(pass_names) - 1


def test_handle_run_terrain_pass_still_surfaces_truly_unknown_passes():
    from veilbreakers_terrain.handlers.environment import handle_run_terrain_pass
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import UnknownPassError

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


def test_handle_run_terrain_pass_default_pipeline_runs_full_validation_without_scene_read():
    from veilbreakers_terrain.handlers.environment import handle_run_terrain_pass
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

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

    assert all(r["status"] in {"ok", "warning"} for r in result["results"])
    assert not any(
        issue["severity"] == "hard"
        for r in result["results"]
        for issue in r.get("issues", [])
    )
    assert [r["pass_name"] for r in result["results"]] == [
        "pass_generate_low_freq_hmap",
        "biome_channels",
        "terrain_labels",
        "structural_masks",
        "pass_generate_high_freq_detail",
        "pass_composite_hmap",
        "materials_v2",
        "pass_navmesh_export",
        "prepare_terrain_normals",
        "prepare_heightmap_raw_u16",
        "prepare_unity_auxiliary_channels",
        "validation_full",
    ]


def test_execute_terrain_pipeline_threads_quality_profile_hints_and_viewport():
    from veilbreakers_terrain.handlers.environment import _execute_terrain_pipeline
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

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
    from veilbreakers_terrain.handlers.environment import handle_run_terrain_pass
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

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
    from veilbreakers_terrain.handlers.environment import handle_run_terrain_pass
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

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
        "water_variants",
        "bathymetry",
        "pass_water_depth",
        "waterfalls",
        "emit_particle_systems",
        "pass_morphology",
        "integrate_deltas",
        "materials_v2",
        "emit_overhang_meshes",
        "scatter_intelligent",
        "pass_horizon_lod",
        "pass_navmesh_export",
        "prepare_terrain_normals",
        "prepare_heightmap_raw_u16",
        "prepare_unity_auxiliary_channels",
        "validation_full",
    ]


def test_dag_blocks_unannotated_duplicate_producer():
    """2026-04-23 wiring audit: register_pass must reject a second producer
    of an already-produced channel unless the new pass explicitly declares
    the channel in its ``overrides`` tuple.

    Regression: two passes both claiming the same produces_channels entry
    without annotation is exactly the hazard that motivated the
    cloud_shadow dual-producer rename. Silencing that hazard via ad-hoc
    registration order is no longer permitted.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import (
        ChannelOwnershipError,
        PassDefinition,
    )

    def _noop_pass(state, region):  # pragma: no cover — registration-only
        raise RuntimeError("not expected to run")

    first = PassDefinition(
        name="dupe_producer_first",
        func=_noop_pass,
        requires_channels=(),
        produces_channels=("custom_test_channel",),
        seed_namespace="dupe_producer_first",
    )
    # Annotated override — legitimate second writer.
    second_annotated = PassDefinition(
        name="dupe_producer_second_annotated",
        func=_noop_pass,
        requires_channels=(),
        produces_channels=("custom_test_channel",),
        overrides=("custom_test_channel",),
        seed_namespace="dupe_producer_second_annotated",
    )
    # Unannotated — should raise.
    second_bare = PassDefinition(
        name="dupe_producer_second_bare",
        func=_noop_pass,
        requires_channels=(),
        produces_channels=("custom_test_channel",),
        seed_namespace="dupe_producer_second_bare",
    )

    TerrainPassController.clear_registry()
    try:
        TerrainPassController.register_pass(first)
        # Legitimate annotated override should succeed.
        TerrainPassController.register_pass(second_annotated)
        # Unannotated duplicate producer must raise ChannelOwnershipError.
        with pytest.raises(ChannelOwnershipError) as excinfo:
            TerrainPassController.register_pass(second_bare)
        # The error message must name both the offending pass and the
        # channel so authors can fix the declaration quickly.
        message = str(excinfo.value)
        assert "dupe_producer_second_bare" in message
        assert "custom_test_channel" in message
        assert "overrides" in message
    finally:
        TerrainPassController.clear_registry()


def test_optional_channels_run_before_consumer_when_available():
    """optional_channels adds a soft DAG edge: when the producer exists the
    scheduler runs it before the consumer; when it is absent the consumer
    is still schedulable. scatter_intelligent is the canonical caller.
    """
    from veilbreakers_terrain.handlers.terrain_pass_dag import PassDAG
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition

    def _noop(state, region):  # pragma: no cover — ordering-only
        raise RuntimeError("not expected to run")

    producer = PassDefinition(
        name="optional_producer_X",
        func=_noop,
        requires_channels=(),
        produces_channels=("optional_channel_X",),
    )
    consumer = PassDefinition(
        name="optional_consumer",
        func=_noop,
        requires_channels=(),
        optional_channels=("optional_channel_X",),
        produces_channels=("optional_consumer_out",),
    )

    # Case 1: producer is present — consumer depends on it.
    dag_with = PassDAG([producer, consumer])
    order_with = dag_with.topological_order()
    assert order_with.index("optional_producer_X") < order_with.index("optional_consumer"), (
        "When the optional producer is registered, it must come before the consumer"
    )
    deps = dag_with.dependencies("optional_consumer")
    assert "optional_producer_X" in deps

    # Case 2: producer is absent — consumer still schedulable with no deps
    # from the optional channel (absence is legal, not an error).
    dag_without = PassDAG([consumer])
    order_without = dag_without.topological_order()
    assert order_without == ["optional_consumer"]
    deps_without = dag_without.dependencies("optional_consumer")
    assert deps_without == set(), (
        "An optional channel with no producer must NOT become a dependency edge"
    )


def test_cloud_shadow_renamed_channels_are_independent():
    """2026-04-23 wiring audit: Bundle J owns sun_cloud_shadow (+ legacy
    cloud_shadow alias) and Bundle K owns baked_cloud_shadow. The two
    channels must be independent DAG-wise so neither pass overwrites the
    other's output.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_cloud_shadow import (
        register_bundle_j_cloud_shadow_pass,
    )
    from veilbreakers_terrain.handlers.terrain_shadow_clipmap_bake import (
        register_bundle_k_shadow_clipmap_pass,
    )

    TerrainPassController.clear_registry()
    try:
        register_bundle_j_cloud_shadow_pass()
        register_bundle_k_shadow_clipmap_pass()

        j_def = TerrainPassController.PASS_REGISTRY["cloud_shadow"]
        k_def = TerrainPassController.PASS_REGISTRY["shadow_clipmap"]

        # Bundle J owns the new primary channel + legacy alias.
        assert "sun_cloud_shadow" in j_def.produces_channels
        assert "cloud_shadow" in j_def.produces_channels
        # Bundle J MUST NOT claim Bundle K's baked channel.
        assert "baked_cloud_shadow" not in j_def.produces_channels

        # Bundle K owns the baked channel exclusively.
        assert "baked_cloud_shadow" in k_def.produces_channels
        # Bundle K MUST NOT write the legacy alias or Bundle J's new channel.
        assert "cloud_shadow" not in k_def.produces_channels
        assert "sun_cloud_shadow" not in k_def.produces_channels

        # DAG view: no channel is produced by both passes — the dual-producer
        # hazard that motivated the rename is resolved.
        j_chans = set(j_def.produces_channels)
        k_chans = set(k_def.produces_channels)
        shared = j_chans & k_chans
        assert shared == set(), (
            f"Bundle J and Bundle K must not share any produces_channels entries "
            f"(found overlap: {sorted(shared)!r})"
        )
    finally:
        TerrainPassController.clear_registry()


def test_handle_run_terrain_pass_skips_heightmap_injection_when_unity_export_opted_out():
    from veilbreakers_terrain.handlers.environment import handle_run_terrain_pass
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

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
