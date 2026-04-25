"""Direct tests for pipeline sequencing and Unity export contract helpers."""

from __future__ import annotations


def test_normalize_delta_integration_sequence_moves_integrator_after_last_delta_producer():
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        _normalize_delta_integration_sequence,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition, PassResult

    def _noop(state, region):
        return PassResult(pass_name="noop", status="ok", duration_seconds=0.01)

    original_registry = dict(TerrainPassController.PASS_REGISTRY)
    try:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(
            {
                "plain": PassDefinition(name="plain", func=_noop, produces_channels=("height",)),
                "wind": PassDefinition(name="wind", func=_noop, produces_channels=("wind_erosion_delta",)),
                "water": PassDefinition(name="water", func=_noop, produces_channels=("coastline_delta",)),
                "integrate_deltas": PassDefinition(name="integrate_deltas", func=_noop),
            }
        )

        assert _normalize_delta_integration_sequence(["integrate_deltas", "plain", "wind", "water"]) == [
            "plain",
            "wind",
            "water",
            "integrate_deltas",
        ]
        assert _normalize_delta_integration_sequence(["plain", "integrate_deltas"]) == ["plain", "integrate_deltas"]
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(original_registry)


def test_unity_export_attribute_contract_validators_report_missing_names():
    from veilbreakers_terrain.handlers.terrain_unity_export_contracts import (
        REQUIRED_MESH_ATTRIBUTES,
        REQUIRED_VERTEX_ATTRIBUTES,
        validate_mesh_attributes_present,
        validate_vertex_attributes_present,
    )

    assert validate_mesh_attributes_present(REQUIRED_MESH_ATTRIBUTES) == []
    mesh_issues = validate_mesh_attributes_present(["slope_angle"])
    assert {issue.affected_feature for issue in mesh_issues} == set(REQUIRED_MESH_ATTRIBUTES) - {"slope_angle"}
    assert {issue.code for issue in mesh_issues} == {"MESH_ATTR_MISSING"}

    assert validate_vertex_attributes_present(REQUIRED_VERTEX_ATTRIBUTES) == []
    vertex_issues = validate_vertex_attributes_present(["position", "normal"])
    assert {issue.affected_feature for issue in vertex_issues} == set(REQUIRED_VERTEX_ATTRIBUTES) - {
        "position",
        "normal",
    }
    assert {issue.code for issue in vertex_issues} == {"VERTEX_ATTR_MISSING"}
