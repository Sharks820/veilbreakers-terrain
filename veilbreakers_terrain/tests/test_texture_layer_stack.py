"""Terrain texture layer stack contract tests."""

from __future__ import annotations

import numpy as np

from veilbreakers_terrain.handlers.terrain_texture_layer_stack import (
    TerrainTextureLayerStack,
    TextureLayer,
)


def _layer(layer_id: str, weight: np.ndarray | None) -> TextureLayer:
    shape = (2, 2) if weight is None else weight.shape
    return TextureLayer(
        layer_id=layer_id,
        terrain_mask_source=f"{layer_id}_mask",
        weight_map=weight,
        normal=np.zeros((*shape, 3), dtype=np.float32),
        roughness=np.full(shape, 0.5, dtype=np.float32),
        ambient_occlusion=np.ones(shape, dtype=np.float32),
        no_displacement_reason="flat reference test layer",
    )


def test_normalized_weights_sum_to_one_per_nonzero_pixel():
    stack = TerrainTextureLayerStack(
        layers=[
            _layer("rock", np.array([[1.0, 0.0], [2.0, 1.0]], dtype=np.float32)),
            _layer("moss", np.array([[1.0, 3.0], [2.0, 0.0]], dtype=np.float32)),
        ]
    )

    weights = stack.normalized_weights()

    assert weights.shape == (2, 2, 2)
    assert weights.dtype == np.float32
    assert np.allclose(weights.sum(axis=-1), 1.0)
    assert np.allclose(weights[0, 0], [0.5, 0.5])
    assert np.allclose(weights[0, 1], [0.0, 1.0])


def test_normalized_weights_zero_total_pixel_stays_zero():
    stack = TerrainTextureLayerStack(
        layers=[
            _layer("rock", np.zeros((2, 2), dtype=np.float32)),
            _layer("moss", None),
        ]
    )

    weights = stack.normalized_weights()

    assert weights.shape == (2, 2, 2)
    assert np.all(weights == 0.0)


def test_normalized_weights_empty_stack_has_zero_layer_axis():
    stack = TerrainTextureLayerStack()

    weights = stack.normalized_weights()

    assert weights.shape == (1, 1, 0)
    assert weights.dtype == np.float32


def test_validate_uses_stack_get_for_mask_sources():
    class GetOnlyStack:
        def __init__(self) -> None:
            self._channels = {"rock_mask": np.ones((2, 2), dtype=np.float32)}

        def get(self, name: str):
            return self._channels.get(name)

    stack = TerrainTextureLayerStack(layers=[_layer("rock", np.ones((2, 2), dtype=np.float32))])

    assert stack.validate(GetOnlyStack()) == []
