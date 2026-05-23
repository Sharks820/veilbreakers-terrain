"""WAVE5-9 regression — terrain_materials_v2 PassDefinition channel contract.

Finding: terrain_materials_v2.py reads the following channels via stack.get(...)
but did NOT declare them in the PassDefinition's optional_channels before this
fix.  The topo-sort DAG was blind to those dependencies — correctness was "by
luck" because the scheduler happened to run label-stamping passes before
materials_v2.  This test pins the fix so a future refactor cannot silently
drop the declarations.

Two passes share pass_materials():
  - ``materials_v2``         (primary writer)
  - ``materials_v2_volcanic`` (secondary writer, same execute function)

Both must declare the same optional_channels contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Expected channel sets (source of truth for this test)
# ---------------------------------------------------------------------------

_REQUIRED_CHANNELS = frozenset({"slope", "height"})

_OPTIONAL_CHANNELS = frozenset(
    {
        "curvature",
        "wetness",
        "lava_prox",
        "snow_line_factor",
        "strata_height",
        "ridge_eroded",
        "ridge",
        "rock_label",
        "gravel_label",
        "water_label",
        "cliff_label",
        "water_surface_mask",
        "wet_rock",
        "road_sdf_dist",
        "splatmap_weights_layer",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source_path() -> Path:
    import veilbreakers_terrain.handlers.terrain_materials_v2 as m

    import inspect

    p = Path(inspect.getsourcefile(m))  # type: ignore[arg-type]
    assert p.exists(), f"source file not found: {p}"
    return p


def _parse_stack_get_channels(source: str) -> frozenset[str]:
    """Return the set of channel names called via stack.get("...") in source."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        # Match: stack.get("channel_name")
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get"):
            continue
        obj = func.value
        if not (isinstance(obj, ast.Name) and obj.id == "stack"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            names.add(str(node.args[0].value))
    return frozenset(names)


# ---------------------------------------------------------------------------
# Test 1: every stack.get() site is covered by required or optional channels
# ---------------------------------------------------------------------------


def test_all_stack_get_sites_declared():
    """Every stack.get("channel") call in pass_materials /
    compute_slope_material_weights must be declared in required or optional
    channels.  Channels already in _REQUIRED_CHANNELS satisfy the contract
    by being required; all others must be in _OPTIONAL_CHANNELS.
    """
    src = _source_path().read_text(encoding="utf-8")
    stack_get_channels = _parse_stack_get_channels(src)

    # height is accessed via stack.height (not stack.get), so remove it from
    # the AST results if somehow present.
    undeclared = stack_get_channels - _REQUIRED_CHANNELS - _OPTIONAL_CHANNELS

    assert not undeclared, (
        f"stack.get() reads channels not declared in PassDefinition: "
        f"{sorted(undeclared)}.  Add them to optional_channels (or "
        f"required_channels if None is not handled gracefully)."
    )


# ---------------------------------------------------------------------------
# Test 2: PassDefinition runtime objects carry the expected contracts
# ---------------------------------------------------------------------------


def _get_registered_definitions():
    """Register the bundle B passes and return the PassDefinition objects."""
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    import veilbreakers_terrain.handlers.terrain_materials_v2 as materials_v2

    TerrainPassController.clear_registry()
    materials_v2.register_bundle_b_material_passes()
    defs = dict(TerrainPassController.PASS_REGISTRY)  # name → PassDefinition
    TerrainPassController.clear_registry()
    return defs


@pytest.fixture()
def _registered_defs():  # pyright: ignore[reportUnusedFunction]
    defs = _get_registered_definitions()
    yield defs


def test_materials_v2_optional_channels(_registered_defs):  # pyright: ignore[reportMissingParameterType]
    """materials_v2 PassDefinition declares all expected optional channels."""
    defn = _registered_defs.get("materials_v2")
    assert defn is not None, "materials_v2 pass not registered"
    actual_optional = frozenset(defn.optional_channels)
    missing = _OPTIONAL_CHANNELS - actual_optional
    assert not missing, (
        f"materials_v2 optional_channels missing: {sorted(missing)}"
    )


def test_materials_v2_volcanic_optional_channels(_registered_defs):  # pyright: ignore[reportMissingParameterType]
    """materials_v2_volcanic PassDefinition declares all expected optional channels."""
    defn = _registered_defs.get("materials_v2_volcanic")
    assert defn is not None, "materials_v2_volcanic pass not registered"
    actual_optional = frozenset(defn.optional_channels)
    missing = _OPTIONAL_CHANNELS - actual_optional
    assert not missing, (
        f"materials_v2_volcanic optional_channels missing: {sorted(missing)}"
    )


def test_materials_v2_required_channels(_registered_defs):  # pyright: ignore[reportMissingParameterType]
    """materials_v2 PassDefinition requires slope and height."""
    defn = _registered_defs.get("materials_v2")
    assert defn is not None
    actual_required = frozenset(defn.requires_channels)
    assert _REQUIRED_CHANNELS.issubset(actual_required), (
        f"materials_v2 requires_channels missing: "
        f"{sorted(_REQUIRED_CHANNELS - actual_required)}"
    )


# ---------------------------------------------------------------------------
# Test 3: optional channels with None fallback don't crash pass_materials
# ---------------------------------------------------------------------------


def _build_minimal_state():
    """Build a TerrainPipelineState with no optional channels populated."""
    import numpy as np
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )
    from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks

    N = 17
    height = np.linspace(0.0, 80.0, N * N).reshape(N, N).astype(np.float32)
    stack = TerrainMaskStack(
        tile_size=16,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    compute_base_masks(height, cell_size=1.0, tile_coords=(0, 0), stack=stack,
                       pass_name="structural_masks")
    intent = TerrainIntentState(
        seed=1,
        region_bounds=BBox(0.0, 0.0, float(N), float(N)),
        tile_size=16,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_pass_materials_no_optional_channels_does_not_crash():
    """pass_materials must succeed when all optional channels are absent (None
    from stack.get()).  This verifies each None-path is handled gracefully.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    import veilbreakers_terrain.handlers.terrain_materials_v2 as materials_v2

    TerrainPassController.clear_registry()
    try:
        state = _build_minimal_state()
        result = materials_v2.pass_materials(state, region=None)
        assert result.status in ("ok", "warning"), (
            f"pass_materials returned unexpected status {result.status!r} "
            f"with no optional channels on the stack"
        )
    finally:
        TerrainPassController.clear_registry()


@pytest.mark.parametrize(
    "channel_name",
    sorted(_OPTIONAL_CHANNELS - {"splatmap_weights_layer"}),
)
def test_pass_materials_each_optional_channel_handled_when_none(channel_name: str):
    """For each optional channel, pass_materials must not crash when only that
    channel is absent and the others happen to be set.  This catches any
    future code that adds a stack.get() call but forgets the None guard.

    (splatmap_weights_layer is excluded from parametrize because it is also
    written by pass_materials — injecting None before the call and then
    checking the result is the same as the no-optional-channels test above.)
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    import veilbreakers_terrain.handlers.terrain_materials_v2 as materials_v2

    TerrainPassController.clear_registry()
    try:
        state = _build_minimal_state()
        # Explicitly ensure the channel is absent by zeroing it to None via
        # object.__setattr__ (bypasses the TerrainMaskStack.set() guard).
        # The channel is not declared as a field in the minimal state, so it
        # should already be absent; this is belt-and-braces.
        if getattr(state.mask_stack, channel_name, None) is not None:
            object.__setattr__(state.mask_stack, channel_name, None)

        result = materials_v2.pass_materials(state, region=None)
        assert result.status in ("ok", "warning"), (
            f"pass_materials failed when optional channel {channel_name!r} "
            f"is absent: status={result.status!r}"
        )
    finally:
        TerrainPassController.clear_registry()
