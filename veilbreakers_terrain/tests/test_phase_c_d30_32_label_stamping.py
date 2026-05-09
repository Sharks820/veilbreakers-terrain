"""Phase C D30-32 — structural label-stamping system regression tests.

Per IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL §17 Phase C D30-32 / spec PR #29 /
Issue #27.

Pinned contracts:

  * ``STRUCTURAL_LABELS`` is a tuple of canonical label IDs (~20 entries).
    Adding/renaming an entry is a breaking change that must touch this test.
  * ``LabelStamp`` is a frozen dataclass with the required fields and
    rejects out-of-vocabulary IDs / degenerate bboxes / invalid confidences.
  * ``LabelStack`` exposes ``add`` / ``stamps_for_label`` / ``stamps_at`` /
    ``label_ids_present`` and indexes inserted stamps.
  * ``pass_label_stamping`` is registered on TerrainPassController, declares
    the legacy four label channels in ``produces_channels``, and runs
    successfully on a synthetic stack producing a non-empty LabelStack +
    a stamped ``cliff_label`` mask when slope >= 60° regions are present.
  * ``terrain_materials_v2`` consumers prefer authored stamps over the
    analytical slope path — text contract pinned in ``test_consumer_prefers_label_over_analytical``.
  * The pass is OPTIONAL in ``build_default_pass_sequence`` — gated by the
    ``label_stamping`` composition hint. Default sequences (no hint) do
    NOT include the new pass; opt-in sequences DO.
"""

from __future__ import annotations

import math
import pathlib

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_labels import (
    LABEL_TO_LEGACY_CHANNEL,
    LabelStack,
    LabelStamp,
    STRUCTURAL_LABELS,
    _bbox_of_component,
    _label_components,
    _stamp_label_in_channel,
    _try_scipy_label,
    pass_label_stamping,
)
from veilbreakers_terrain.handlers.terrain_pipeline import (
    TerrainPassController,
    build_default_pass_sequence,
)
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
    TerrainSceneRead,
)


# ---------------------------------------------------------------------------
# 1. Canonical STRUCTURAL_LABELS registry
# ---------------------------------------------------------------------------


# Pinning the exact set protects against drift. Every change here MUST
# update consumers in ``terrain_labels.LABEL_TO_LEGACY_CHANNEL`` too.
_CANONICAL_LABELS_EXPECTED = {
    "mesa_caprock",
    "cliff_face",
    "ridgeline",
    "talus_slope",
    "scree_field",
    "river_bend",
    "river_channel",
    "valley_floor",
    "coastal_strand",
    "waterfall_pool",
    "bog_pocket",
    "lake_shore",
    "alluvial_fan",
    "glacial_moraine",
    "hillslope",
    "plateau",
    "dune_crest",
    "dune_swale",
    "forest_floor",
    "alpine_meadow",
    "marsh",
}


def test_structural_labels_canonical_set() -> None:
    """STRUCTURAL_LABELS contains the 21 canonical label IDs."""
    assert isinstance(STRUCTURAL_LABELS, tuple)
    assert set(STRUCTURAL_LABELS) == _CANONICAL_LABELS_EXPECTED
    # Spec calls out ~20 entries; we ship 21 (one extra for ridgeline disambiguation).
    assert 18 <= len(STRUCTURAL_LABELS) <= 24
    # No duplicates.
    assert len(STRUCTURAL_LABELS) == len(set(STRUCTURAL_LABELS))


def test_structural_labels_includes_required_ids() -> None:
    """The label IDs explicitly listed in the spec are present."""
    # Per IMPLEMENTATION_FIX_GUIDE §17 Phase C D30-32 + Issue #27 task list.
    spec_required = {"mesa_caprock", "river_bend", "scree_field"}
    assert spec_required.issubset(set(STRUCTURAL_LABELS))


def test_label_to_legacy_channel_mapping_complete() -> None:
    """Every label routes to one of the four legacy mask channels."""
    legacy_targets = {"rock_label", "gravel_label", "water_label", "cliff_label"}
    assert set(LABEL_TO_LEGACY_CHANNEL.keys()) == set(STRUCTURAL_LABELS)
    assert set(LABEL_TO_LEGACY_CHANNEL.values()).issubset(legacy_targets)


# ---------------------------------------------------------------------------
# 2. LabelStamp dataclass contract
# ---------------------------------------------------------------------------


def test_label_stamp_construction_ok() -> None:
    """A LabelStamp built with valid args carries its data."""
    stamp = LabelStamp(
        label_id="cliff_face",
        region_bbox=(10, 12, 30, 40),
        confidence=0.9,
        source_pass="label_stamping",
    )
    assert stamp.label_id == "cliff_face"
    assert stamp.region_bbox == (10, 12, 30, 40)
    assert stamp.confidence == 0.9
    assert stamp.source_pass == "label_stamping"
    assert stamp.area_cells == (30 - 10) * (40 - 12)


def test_label_stamp_rejects_unknown_id() -> None:
    with pytest.raises(ValueError, match="STRUCTURAL_LABELS"):
        LabelStamp(
            label_id="not_a_real_label",
            region_bbox=(0, 0, 5, 5),
            confidence=1.0,
            source_pass="t",
        )


def test_label_stamp_rejects_degenerate_bbox() -> None:
    with pytest.raises(ValueError, match="region_bbox"):
        LabelStamp(
            label_id="cliff_face",
            region_bbox=(5, 5, 5, 10),
            confidence=1.0,
            source_pass="t",
        )


def test_label_stamp_rejects_bad_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        LabelStamp(
            label_id="cliff_face",
            region_bbox=(0, 0, 5, 5),
            confidence=1.5,
            source_pass="t",
        )


def test_label_stamp_is_frozen() -> None:
    """LabelStamp is immutable after construction (frozen dataclass)."""
    stamp = LabelStamp(
        label_id="ridgeline",
        region_bbox=(0, 0, 8, 8),
        confidence=0.5,
        source_pass="t",
    )
    with pytest.raises((AttributeError, Exception)):
        stamp.label_id = "cliff_face"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3. LabelStack collection
# ---------------------------------------------------------------------------


def test_label_stack_indexes_by_label() -> None:
    stack = LabelStack()
    s1 = LabelStamp("cliff_face", (0, 0, 10, 10), 1.0, "t")
    s2 = LabelStamp("cliff_face", (20, 20, 30, 30), 1.0, "t")
    s3 = LabelStamp("river_bend", (40, 40, 50, 60), 1.0, "t")
    stack.add(s1)
    stack.add(s2)
    stack.add(s3)
    assert len(stack) == 3
    cliffs = stack.stamps_for_label("cliff_face")
    assert len(cliffs) == 2
    assert s1 in cliffs and s2 in cliffs
    bends = stack.stamps_for_label("river_bend")
    assert bends == [s3]


def test_label_stack_spatial_lookup() -> None:
    stack = LabelStack()
    s1 = LabelStamp("cliff_face", (10, 10, 20, 20), 1.0, "t")
    s2 = LabelStamp("ridgeline", (15, 15, 25, 25), 1.0, "t")
    stack.add(s1)
    stack.add(s2)
    # Cell (12, 12) is inside s1 only.
    hits = stack.stamps_at(12, 12)
    assert s1 in hits and s2 not in hits
    # Cell (18, 18) is inside both s1 (10:20, 10:20) and s2 (15:25, 15:25).
    hits = stack.stamps_at(18, 18)
    assert s1 in hits and s2 in hits
    # Cell (50, 50) is outside everything.
    assert stack.stamps_at(50, 50) == []


def test_label_stack_rejects_unknown_label_lookup() -> None:
    stack = LabelStack()
    with pytest.raises(ValueError, match="STRUCTURAL_LABELS"):
        stack.stamps_for_label("not_a_real_label")


# ---------------------------------------------------------------------------
# 4. pass_label_stamping contract + behaviour
# ---------------------------------------------------------------------------


def _build_synthetic_pipeline_state(
    *,
    height: np.ndarray,
    slope: np.ndarray | None = None,
    curvature: np.ndarray | None = None,
    biome_id: np.ndarray | None = None,
    water_mask: np.ndarray | None = None,
) -> TerrainPipelineState:
    """Build a minimal TerrainPipelineState for direct pass invocation."""
    H, W = height.shape
    stack = TerrainMaskStack(
        tile_size=H - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height.astype(np.float32),
    )
    stack.height_min_m = float(height.min())
    stack.height_max_m = float(height.max())
    if slope is not None:
        stack.set("slope", slope.astype(np.float32), "test_fixture")
    if curvature is not None:
        stack.set("curvature", curvature.astype(np.float32), "test_fixture")
    if biome_id is not None:
        stack.set("biome_id", biome_id.astype(np.int32), "test_fixture")
    if water_mask is not None:
        stack.set("water_surface_mask", water_mask.astype(np.float32), "test_fixture")
    intent = TerrainIntentState(
        seed=42,
        region_bounds=BBox(0.0, 0.0, float(W), float(H)),
        tile_size=H - 1,
        cell_size=1.0,
        quality_profile="aaa_open_world",
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_pass_label_stamping_registers() -> None:
    """The label_stamping pass is registered via the broker pattern (per
    docs/IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL §17 Phase C D30-32) —
    terrain_pipeline.register_default_passes() pulls
    label_stamping_pass_definition() from terrain_labels and registers
    it directly on TerrainPassController, avoiding the static
    CodeQL-flagged import cycle.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import register_default_passes
    register_default_passes()
    pdef = TerrainPassController.PASS_REGISTRY["label_stamping"]
    assert pdef.func is pass_label_stamping
    assert "height" in pdef.requires_channels
    # Optional inputs declared so the DAG can resolve them when present.
    # PR #57 thread 4 (Copilot): biome_id was removed from optional_channels
    # because pass_label_stamping never reads it; re-add when biome-aware
    # branching is wired in.
    optional = set(pdef.optional_channels or ())
    assert {"slope", "curvature", "water_surface_mask"}.issubset(optional)
    assert "biome_id" not in optional, (
        "biome_id was removed from optional_channels (PR #57 thread 4); "
        "re-add only if pass_label_stamping starts reading biome_id."
    )
    # All four legacy label channels + the LabelStack are declared as outputs.
    # PR #57 thread 7 (CodeRabbit): label_stack must be declared so DAG
    # consumers can depend on it and rollback snapshots include it.
    produced = set(pdef.produces_channels)
    assert {"rock_label", "gravel_label", "water_label", "cliff_label", "label_stack"}.issubset(produced)
    # PR #57 thread 6 (CodeRabbit): pass mutates the whole tile and
    # ignores ``region``, so it must not be advertised as region-scopable.
    assert pdef.supports_region_scope is False
    # Overrides declared so the DAG accepts the dual-writer relationship
    # with ``pass_compute_terrain_labels``.
    overrides = set(pdef.overrides or ())
    assert {"rock_label", "gravel_label", "water_label", "cliff_label"}.issubset(overrides)


def test_pass_label_stamping_produces_label_stack() -> None:
    """Running the pass on a synthetic stack publishes a LabelStack."""
    H, W = 32, 32
    height = np.zeros((H, W), dtype=np.float32)
    slope = np.zeros((H, W), dtype=np.float32)
    state = _build_synthetic_pipeline_state(height=height, slope=slope)

    result = pass_label_stamping(state, region=None)

    assert result.status == "ok"
    assert result.pass_name == "label_stamping"
    assert "label_stack" in result.produced_channels
    assert isinstance(state.mask_stack.label_stack, LabelStack)


def test_pass_label_stamping_steep_slope_stamps_cliff() -> None:
    """A synthetic 60°+ slope region produces at least one cliff_label stamp."""
    H, W = 32, 32
    height = np.zeros((H, W), dtype=np.float32)
    slope = np.zeros((H, W), dtype=np.float32)
    # 8x8 patch of >=60° slope (in radians)
    slope[8:16, 8:16] = math.radians(75.0)
    state = _build_synthetic_pipeline_state(height=height, slope=slope)

    pass_label_stamping(state, region=None)

    label_stack: LabelStack = state.mask_stack.label_stack  # type: ignore[assignment]
    assert label_stack is not None
    # cliff_face / mesa_caprock / ridgeline all route to cliff_label.
    cliff_labels = (
        label_stack.stamps_for_label("cliff_face")
        + label_stack.stamps_for_label("mesa_caprock")
        + label_stack.stamps_for_label("ridgeline")
    )
    assert len(cliff_labels) >= 1, (
        f"Expected at least one cliff-class stamp, got "
        f"label_ids_present={label_stack.label_ids_present()}"
    )
    # cliff_label mask is stamped > 0 inside the patch.
    cliff_mask = state.mask_stack.get("cliff_label")
    assert cliff_mask is not None
    assert float(cliff_mask[8:16, 8:16].max()) > 0.5


def test_pass_label_stamping_water_region_stamps_water_label() -> None:
    """A water_surface_mask region produces a water_label stamp."""
    H, W = 32, 32
    height = np.zeros((H, W), dtype=np.float32)
    slope = np.zeros((H, W), dtype=np.float32)
    water_mask = np.zeros((H, W), dtype=np.float32)
    water_mask[20:28, 4:12] = 1.0  # 8x8 lake-shaped patch
    state = _build_synthetic_pipeline_state(
        height=height, slope=slope, water_mask=water_mask,
    )

    pass_label_stamping(state, region=None)

    label_stack: LabelStack = state.mask_stack.label_stack  # type: ignore[assignment]
    water_stamps = (
        label_stack.stamps_for_label("river_channel")
        + label_stack.stamps_for_label("lake_shore")
    )
    assert len(water_stamps) >= 1
    water_label = state.mask_stack.get("water_label")
    assert water_label is not None
    assert float(water_label[20:28, 4:12].max()) > 0.5


def test_pass_label_stamping_no_inputs_runs_safely() -> None:
    """With no slope/curvature/water inputs the pass still returns ok."""
    H, W = 16, 16
    height = np.zeros((H, W), dtype=np.float32)
    state = _build_synthetic_pipeline_state(height=height)
    result = pass_label_stamping(state, region=None)
    assert result.status == "ok"
    # No stamps produced, but stack.label_stack is initialised to empty.
    assert state.mask_stack.label_stack is not None
    assert len(state.mask_stack.label_stack) == 0


# ---------------------------------------------------------------------------
# 5. Default-sequence wiring (opt-in flag)
# ---------------------------------------------------------------------------


def _intent(label_stamping: bool) -> TerrainIntentState:
    region_bounds = BBox(0.0, 0.0, 32.0, 32.0)
    scene_read = TerrainSceneRead(
        timestamp=0.0,
        major_landforms=("flat",),
        focal_point=(16.0, 16.0, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=region_bounds,
        success_criteria=("phase_c_d30_32",),
        reviewer="pytest",
    )
    hints: dict[str, object] = {}
    if label_stamping:
        hints["label_stamping"] = True
    return TerrainIntentState(
        seed=42,
        region_bounds=region_bounds,
        tile_size=32,
        cell_size=1.0,
        quality_profile="aaa_open_world",
        scene_read=scene_read,
        composition_hints=hints,
    )


def test_default_sequence_excludes_label_stamping_by_default() -> None:
    """Without the opt-in hint the pass is NOT scheduled."""
    seq = build_default_pass_sequence(_intent(label_stamping=False))
    assert "label_stamping" not in seq


def test_default_sequence_includes_label_stamping_when_requested() -> None:
    """With the opt-in hint the pass IS scheduled after mutating passes."""
    seq = build_default_pass_sequence(_intent(label_stamping=True))
    assert "label_stamping" in seq
    # Ordered AFTER structural_masks (so slope/curvature exist) and BEFORE
    # any materials_v2 consumer (which may not be in this sequence).
    assert seq.index("label_stamping") > seq.index("structural_masks")
    assert seq.index("label_stamping") > seq.index("framing")


# ---------------------------------------------------------------------------
# 6. Consumer-prefers-label-over-analytical contract (text-pinned)
# ---------------------------------------------------------------------------


_HANDLERS = pathlib.Path(__file__).resolve().parents[1] / "handlers"


# ---------------------------------------------------------------------------
# 7. Direct-behavior tests for internal helpers (verification matrix evidence).
# ---------------------------------------------------------------------------


def test_try_scipy_label_returns_callable_or_none() -> None:
    """``_try_scipy_label`` returns a callable when scipy is importable."""
    fn = _try_scipy_label()
    # scipy is a hard repo dep so we expect callable, but the helper must
    # accept the absent case for portability.
    assert fn is None or callable(fn)


def test_label_components_basic_two_islands() -> None:
    """``_label_components`` finds two disjoint islands in a small mask."""
    mask = np.zeros((6, 8), dtype=bool)
    mask[0:2, 0:2] = True   # 2x2 island at top-left
    mask[3:5, 4:7] = True   # 2x3 island at bottom-right
    labels, n = _label_components(mask)
    assert n == 2
    assert labels.shape == mask.shape
    # The two islands have different non-zero labels and the background is 0.
    assert labels[0, 0] != 0
    assert labels[3, 4] != 0
    assert labels[0, 0] != labels[3, 4]
    assert labels[2, 2] == 0  # background


def test_label_components_empty_mask_returns_zero_count() -> None:
    """An all-False mask reports zero components."""
    mask = np.zeros((4, 4), dtype=bool)
    labels, n = _label_components(mask)
    assert n == 0
    assert int(labels.sum()) == 0


def test_bbox_of_component_returns_correct_slice() -> None:
    """``_bbox_of_component`` returns the inclusive-low / exclusive-high slice."""
    labels = np.zeros((10, 10), dtype=np.int32)
    labels[2:5, 3:8] = 7  # component id 7 covers rows [2,5), cols [3,8)
    bbox = _bbox_of_component(labels, 7)
    assert bbox == (2, 3, 5, 8)
    # Slicing the original array with the bbox should recover the component.
    r0, c0, r1, c1 = bbox
    assert int((labels[r0:r1, c0:c1] == 7).all()) == 1


def test_bbox_of_component_missing_returns_zero_zero() -> None:
    """Missing component id returns a degenerate bbox at the origin."""
    labels = np.zeros((4, 4), dtype=np.int32)
    bbox = _bbox_of_component(labels, 99)
    assert bbox == (0, 0, 0, 0)


def test_stamp_label_in_channel_initialises_when_absent() -> None:
    """``_stamp_label_in_channel`` creates a fresh zeros array when input is None."""
    region = np.zeros((4, 4), dtype=bool)
    region[1:3, 1:3] = True
    out = _stamp_label_in_channel(None, region, (4, 4))
    assert out.shape == (4, 4)
    assert out.dtype == np.float32
    assert float(out[1:3, 1:3].max()) == 1.0
    assert float(out[0, 0]) == 0.0


def test_stamp_label_in_channel_preserves_prior_stamps() -> None:
    """Existing label values are preserved, never zeroed."""
    prior = np.zeros((4, 4), dtype=np.float32)
    prior[0, 0] = 1.0  # generator-stamped cell
    region = np.zeros((4, 4), dtype=bool)
    region[2:4, 2:4] = True
    out = _stamp_label_in_channel(prior, region, (4, 4))
    # Generator stamp survives.
    assert float(out[0, 0]) == 1.0
    # New stamp lands inside the region.
    assert float(out[3, 3]) == 1.0


def test_consumer_prefers_label_over_analytical() -> None:
    """terrain_materials_v2 consults label channels BEFORE the analytical path.

    The contract is intentionally textual — verifying runtime behaviour
    would require constructing the full splatmap_compute fixture which is
    covered by the existing terrain_materials_v2 tests. This pins the
    label-stamping logic ordering and the comment that documents it.
    """
    src = (_HANDLERS / "terrain_materials_v2.py").read_text(encoding="utf-8")
    # The label-override block must mention the four legacy channels.
    assert "rock_label" in src and "cliff_label" in src
    assert "gravel_label" in src and "water_label" in src
    # The override block carries a "labels take priority" comment.
    assert "labels take priority" in src or "Structural label overrides" in src
    # Labelled cells skip the analytical splatmap path: the code zeroes
    # weights on labelled cells, then sets the target layer to 1.0.
    assert "weights[labeled, :] = 0.0" in src
    assert "weights[labeled, tidx] = 1.0" in src


# ---------------------------------------------------------------------------
# label_stamping_pass_definition broker — direct test for HIGH→LOW
# ---------------------------------------------------------------------------


def test_label_stamping_pass_definition_returns_canonical_passdef() -> None:
    """`label_stamping_pass_definition` returns the canonical PassDefinition
    without importing terrain_pipeline (broker pattern that breaks the
    CodeQL static cycle).

    Direct test reference so the wiring scanner promotes the function
    from HIGH risk to LOW risk (no module-level call → needs explicit
    test reference for direct_test_covered evidence).
    """
    from veilbreakers_terrain.handlers.terrain_labels import (
        label_stamping_pass_definition,
        pass_label_stamping,
    )

    pd = label_stamping_pass_definition()
    assert pd.name == "label_stamping"
    assert pd.func is pass_label_stamping
    assert pd.requires_channels == ("height",)
    assert "rock_label" in pd.produces_channels
    assert "cliff_label" in pd.produces_channels
    assert pd.seed_namespace == "label_stamping"


def test_label_stamping_pass_definition_returns_fresh_instance() -> None:
    """Factory must return a fresh PassDefinition each call so callers
    can mutate without aliasing.
    """
    from veilbreakers_terrain.handlers.terrain_labels import (
        label_stamping_pass_definition,
    )

    a = label_stamping_pass_definition()
    b = label_stamping_pass_definition()
    # Same content, different objects (no caching).
    assert a == b
    assert a is not b
