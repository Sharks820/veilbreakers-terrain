from __future__ import annotations

from typing import Any

import numpy as np


class _Stack:
    def __init__(self) -> None:
        self.height: np.ndarray[Any, Any] = np.zeros((3, 3), dtype=np.float32)
        self.water_surface_elevation_m: np.ndarray[Any, Any] = np.ones(
            (3, 3), dtype=np.float32
        )
        self.water_depth_m: np.ndarray[Any, Any] | None = (
            np.ones((3, 3), dtype=np.float32) * 0.5
        )
        self.flow_direction: np.ndarray[Any, Any] = np.zeros((3, 3), dtype=np.float32)
        self.flow_speed: np.ndarray[Any, Any] = (
            np.ones((3, 3), dtype=np.float32) * 0.25
        )
        self.flow_accumulation: np.ndarray[Any, Any] = np.ones(
            (3, 3), dtype=np.float32
        )
        self.foam: np.ndarray[Any, Any] = np.zeros((3, 3), dtype=np.float32)
        self.mist: np.ndarray[Any, Any] = np.zeros((3, 3), dtype=np.float32)
        self.wet_rock: np.ndarray[Any, Any] = np.zeros((3, 3), dtype=np.float32)

    def get(self, key: str) -> object | None:
        return getattr(self, key, None)


def test_water_contract_private_accessors_support_mapping_and_stack_shapes():
    from veilbreakers_terrain.handlers.terrain_water_contracts import _get, _shape_of_height

    stack = _Stack()

    assert _get({"height": "mapped"}, "height") == "mapped"
    assert _get(stack, "height") is stack.height
    assert _shape_of_height(stack) == (3, 3)
    assert _shape_of_height({"height": np.zeros((2, 4), dtype=np.float32)}) == (2, 4)


def test_water_contract_private_array_checker_reports_shape_and_negative_values():
    from veilbreakers_terrain.handlers.terrain_water_contracts import _check_array

    issues: list[dict[str, str]] = []
    stack = _Stack()
    stack.foam = np.array([[0.0, -0.25]], dtype=np.float32)

    _check_array(
        issues,
        stack=stack,
        channel="foam",
        expected_shape=(3, 3),
        nonnegative=True,
    )

    codes = {issue["code"] for issue in issues}

    assert "water_channel_shape_mismatch" in codes
    assert "water_channel_negative" in codes


def test_water_contract_private_array_checker_reports_nonnumeric_payloads():
    from veilbreakers_terrain.handlers.terrain_water_contracts import _check_array

    issues: list[dict[str, str]] = []
    stack = _Stack()
    stack.foam = np.array([["bad"]], dtype=object)

    _check_array(
        issues,
        stack=stack,
        channel="foam",
        expected_shape=(3, 3),
        nonnegative=True,
    )

    codes = {issue["code"] for issue in issues}

    assert "water_channel_shape_mismatch" in codes
    assert "water_channel_non_numeric" in codes


def test_water_runtime_contract_accepts_canonical_channels_and_manifest():
    from veilbreakers_terrain.handlers.terrain_water_contracts import (
        validate_water_runtime_contract,
    )

    # Hardening PR B Fix #10 (VA finding): URP-first fixture (was HDRP/Water).
    manifest = {
        "materials": {"lake": {"shader": "Universal Render Pipeline/Water"}},
        "shader_textures": {"_FoamTex": "foam.png"},
        "water_level_m": 1.0,
    }

    assert validate_water_runtime_contract(_Stack(), water_shader_manifest=manifest) == []


def test_water_runtime_contract_accepts_export_manifest_material_list():
    from veilbreakers_terrain.handlers.terrain_water_contracts import (
        validate_water_runtime_contract,
    )

    # Hardening PR B Fix #10: URP-first fixture (Boat Attack default).
    manifest = {
        "materials": [
            {
                "material_id": "lake",
                "shader_target": {"unity": "Universal Render Pipeline/Water"},
            }
        ],
        "shader_textures": {"_FoamTex": "foam.png"},
    }

    assert validate_water_runtime_contract(_Stack(), water_shader_manifest=manifest) == []


def test_water_runtime_contract_accepts_baseline_depth_and_flow_channels():
    from veilbreakers_terrain.handlers.terrain_water_contracts import (
        validate_water_runtime_contract,
    )

    stack = _Stack()
    del stack.flow_speed
    del stack.foam
    del stack.mist
    del stack.wet_rock
    manifest = {
        "materials": [{"material_id": "lake"}],
        "shader_textures": {"_WaterDepthTex": "water_depth.png"},
    }

    assert validate_water_runtime_contract(stack, water_shader_manifest=manifest) == []


def test_water_runtime_contract_blocks_missing_depth_and_shader_manifest():
    from veilbreakers_terrain.handlers.terrain_water_contracts import (
        validate_water_runtime_contract,
    )

    stack = _Stack()
    stack.water_depth_m = None

    codes = {issue["code"] for issue in validate_water_runtime_contract(stack)}

    assert "missing_water_depth_contract" in codes
    assert "missing_water_shader_manifest" in codes


def test_water_runtime_contract_blocks_shape_mismatch_and_negative_depth():
    from veilbreakers_terrain.handlers.terrain_water_contracts import (
        validate_water_runtime_contract,
    )

    stack = _Stack()
    stack.water_depth_m = np.array([[0.0, -1.0]], dtype=np.float32)

    issues = validate_water_runtime_contract(
        stack,
        water_shader_manifest={
            "materials": {"lake": {}},
            "shader_textures": {"_WaterDepthTex": "water_depth.png"},
        },
    )
    codes = {issue["code"] for issue in issues}

    assert "water_channel_shape_mismatch" in codes
    assert "water_channel_negative" in codes


# ---------------------------------------------------------------------------
# FIX-B14-2: seasonal mutation downstream channels are fresh
# ---------------------------------------------------------------------------


def _build_terrain_stack(size: int = 8):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    h = np.zeros((size, size), dtype=np.float64)
    return TerrainMaskStack(
        tile_size=size - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )


def test_seasonal_mutation_downstream_channels_are_fresh():
    """FIX-B14-2: wetness after WET seasonal pass equals clip(original*1.5+0.2, 0, 1)."""
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        SeasonalState,
        apply_seasonal_water_state,
    )

    stack = _build_terrain_stack()
    shape = stack.height.shape

    # Pre-populate wetness with a known value so we can verify the WET mutation.
    initial_wetness = np.full(shape, 0.4, dtype=np.float32)
    stack.set("wetness", initial_wetness, "test_setup")
    stack.set("water_surface_mask", np.zeros(shape, dtype=np.float32), "test_setup")

    apply_seasonal_water_state(stack, SeasonalState.WET)

    result_wetness = np.asarray(stack.get("wetness"), dtype=np.float32)
    expected = np.clip(0.4 * 1.5 + 0.2, 0.0, 1.0)
    assert np.allclose(result_wetness, expected, atol=1e-5), (
        f"WET wetness should be {expected:.4f}, got {result_wetness.mean():.4f}"
    )
    # Confirm water_surface_mask was also updated.
    assert stack.get("water_surface_mask") is not None
    assert stack.populated_by_pass.get("wetness") == "water_variants_seasonal"


# ---------------------------------------------------------------------------
# FIX-B14-3: seasonal pass does NOT write legacy water_surface channel
# ---------------------------------------------------------------------------


def test_seasonal_water_state_does_not_write_legacy_water_surface():
    """FIX-B14-3: apply_seasonal_water_state must not populate water_surface."""
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        SeasonalState,
        apply_seasonal_water_state,
    )

    stack = _build_terrain_stack()
    shape = stack.height.shape

    stack.set("wetness", np.full(shape, 0.5, dtype=np.float32), "test_setup")
    stack.set("water_surface_mask", np.zeros(shape, dtype=np.float32), "test_setup")

    # Record which pass last wrote water_surface before the seasonal call.
    pre_writer = stack.populated_by_pass.get("water_surface")

    apply_seasonal_water_state(stack, SeasonalState.WET)

    post_writer = stack.populated_by_pass.get("water_surface")

    # water_surface populated_by_pass must NOT have changed to water_variants_seasonal.
    assert post_writer != "water_variants_seasonal", (
        "apply_seasonal_water_state must not write to the legacy water_surface channel"
    )
    # Either unchanged from pre-call or absent.
    assert post_writer == pre_writer, (
        f"water_surface populated_by_pass changed from {pre_writer!r} to {post_writer!r}"
    )
    # Canonical channel must be populated.
    assert stack.get("water_surface_mask") is not None
    assert stack.populated_by_pass.get("water_surface_mask") == "water_variants_seasonal"
