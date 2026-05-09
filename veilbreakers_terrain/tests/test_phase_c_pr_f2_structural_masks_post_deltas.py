"""PR-F2 (cross-audit P0 2026-05-09): structural_masks_post_deltas.

Pins the contract that after ``integrate_deltas`` mutates ``height``,
``structural_masks_post_deltas`` recomputes slope / curvature / ridge
fields so downstream materials_v2 / scatter_intelligent / label_stamping
/ topographic_indices consume the POST-delta surface, not stale
pre-delta values.

The audit-reported pass-order rot was: integrate_deltas at idx 23,
pass_road_network at idx 24, materials_v2 at idx 25, scatter at idx 27 —
materials/scatter read slope/curvature derived from PRE-integrate_deltas
height. Without this recompute pass, the rot persists on every default
pipeline run.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainSceneRead


FloatArray = NDArray[np.float32]


def _make_state_with_height(rows: int = 16, cols: int = 16) -> Any:
    """Stack with a slanted ridge so structural_masks produces non-trivial
    slope and curvature, then we can verify a height delta perturbs them."""
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    h = np.tile(
        np.linspace(0.0, 50.0, cols, dtype=np.float32).reshape(1, -1),
        (rows, 1),
    )
    stack = TerrainMaskStack(
        tile_size=int(rows),
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )
    region = BBox(0.0, 0.0, float(rows), float(cols))
    intent = TerrainIntentState(
        seed=42,
        region_bounds=region,
        tile_size=rows,
        cell_size=1.0,
        composition_hints={},
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_structural_masks_post_deltas_pass_definition_registered():
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )

    register_default_passes()
    assert "structural_masks_post_deltas" in TerrainPassController.PASS_REGISTRY, (
        "PR-F2: structural_masks_post_deltas must be registered alongside "
        "structural_masks_post_erosion / _post_talus."
    )


def test_structural_masks_post_deltas_in_default_sequence_when_scene_read():
    """The recompute must be scheduled when has_scene_read=True (the
    canonical AAA pipeline). Without scene_read there is no integrate_deltas
    to recompute after, so the pass is correctly absent."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
    )

    region = BBox(0.0, 0.0, 16.0, 16.0)
    intent_with_scene = TerrainIntentState(
        seed=42,
        region_bounds=region,
        tile_size=16,
        cell_size=1.0,
        composition_hints={},
        scene_read=cast("TerrainSceneRead", object()),
        quality_profile="aaa_open_world",
    )

    seq = build_default_pass_sequence(intent_with_scene)

    assert "structural_masks_post_deltas" in seq, (
        f"structural_masks_post_deltas missing from scene-read sequence: {seq}"
    )
    # Must come AFTER integrate_deltas
    integrate_idx = seq.index("integrate_deltas")
    post_deltas_idx = seq.index("structural_masks_post_deltas")
    assert post_deltas_idx > integrate_idx, (
        f"structural_masks_post_deltas (idx {post_deltas_idx}) must come AFTER "
        f"integrate_deltas (idx {integrate_idx}); got order: {seq[integrate_idx:post_deltas_idx+2]}"
    )


def test_structural_masks_post_deltas_runs_before_materials_and_scatter():
    """The recompute must be scheduled BEFORE the consumers it protects:
    materials_v2 and scatter_intelligent. Otherwise it runs after they
    read slope/curvature and the protection is hollow."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        build_default_pass_sequence,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
    )

    region = BBox(0.0, 0.0, 16.0, 16.0)
    intent_with_scene = TerrainIntentState(
        seed=42,
        region_bounds=region,
        tile_size=16,
        cell_size=1.0,
        composition_hints={},
        scene_read=cast("TerrainSceneRead", object()),
        quality_profile="aaa_open_world",
    )

    seq = build_default_pass_sequence(intent_with_scene)

    post_deltas_idx = seq.index("structural_masks_post_deltas")

    if "materials_v2" in seq:
        assert seq.index("materials_v2") > post_deltas_idx, (
            f"materials_v2 must come AFTER structural_masks_post_deltas so "
            f"it reads post-delta slope/curvature; got "
            f"materials_v2 at {seq.index('materials_v2')}, "
            f"post_deltas at {post_deltas_idx}"
        )
    if "scatter_intelligent" in seq:
        assert seq.index("scatter_intelligent") > post_deltas_idx, (
            "scatter_intelligent must come AFTER structural_masks_post_deltas"
        )


def test_structural_masks_post_deltas_recomputes_slope_after_height_mutation():
    """Behavioral: after a height mutation, calling pass_structural_masks
    again produces a slope field that REFLECTS the mutation. Without the
    recompute, downstream consumers would see the pre-mutation slope.
    """
    from veilbreakers_terrain.handlers._terrain_world import pass_structural_masks

    state = _make_state_with_height(rows=16, cols=16)

    # First recompute: capture initial slope.
    pass_structural_masks(state, None)
    slope_before = state.mask_stack.slope
    assert slope_before is not None
    slope_before_copy = slope_before.copy()

    # Simulate integrate_deltas: bump height in a localized region.
    new_height = state.mask_stack.height.copy()
    new_height[6:10, 6:10] += 30.0  # 30m delta in a 4x4 patch
    state.mask_stack.set("height", new_height, "test_delta_integrator")

    # Without a post-delta recompute, slope would still be slope_before.
    # Run the recompute pass (this is what structural_masks_post_deltas does).
    pass_structural_masks(state, None)
    slope_after = state.mask_stack.slope
    assert slope_after is not None

    # Assert the slope field changed in the perturbed region.
    diff = np.abs(slope_after - slope_before_copy)
    assert diff[6:10, 6:10].max() > 0.01, (
        "post-delta slope recompute should produce a non-trivial change "
        f"in the perturbed region; max diff = {diff[6:10, 6:10].max():.4f}"
    )


def test_structural_masks_post_deltas_in_label_stamping_deferrable_set():
    """PR-F2 + PR #57 round-4 invariant: any pass that mutates structural
    masks must be in _LABEL_STAMPING_DEFERRABLE_PASSES so label_stamping
    runs AFTER it. structural_masks_post_deltas changes slope/curvature/
    ridge/etc., so it must be in the set."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        _LABEL_STAMPING_DEFERRABLE_PASSES,
    )

    assert "structural_masks_post_deltas" in _LABEL_STAMPING_DEFERRABLE_PASSES, (
        "structural_masks_post_deltas overrides slope/curvature/ridge/etc., "
        "so it MUST be in _LABEL_STAMPING_DEFERRABLE_PASSES so label_stamping "
        "runs after it. Missing from set."
    )
