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

    manifest = {
        "materials": {"lake": {"shader": "HDRP/Water"}},
        "shader_textures": {"_FoamTex": "foam.png"},
        "water_level_m": 1.0,
    }

    assert validate_water_runtime_contract(_Stack(), water_shader_manifest=manifest) == []


def test_water_runtime_contract_accepts_export_manifest_material_list():
    from veilbreakers_terrain.handlers.terrain_water_contracts import (
        validate_water_runtime_contract,
    )

    manifest = {
        "materials": [{"material_id": "lake", "shader_target": {"unity": "HDRP/Water"}}],
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
