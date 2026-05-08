"""Phase C D26-27 — delta integrator wiring regression tests.

Per ``docs/IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md`` §17 Phase C D26-27
(spec §11.1 PRs #16 + #17): two delta integrators were registered but the
producing passes were either not in the default sequence (stratigraphy,
deferred from Phase A D8) or not paired with their integrator at the
correct position.

This phase wires both integrators in. The fix has three parts:

  1. ``register_bundle_i_passes`` (terrain_geology_validator.py) declares
     the missing aux-height channels (``sediment_height``, ``bedrock_height``,
     ``strata_height``) and ``overrides=("height",)`` for the fold
     deformation overwrite.

  2. ``build_default_pass_sequence`` (terrain_pipeline.py) inserts
     ``stratigraphy`` after ``wind_erosion`` and before
     ``pass_terrain_features`` so its ``strat_erosion_delta`` is composed
     into ``height`` by the integrator. ``pass_morphology`` was already
     scheduled in the early validation_full block; D26-27 also pins that
     position invariant.

  3. ``_normalize_delta_integration_sequence`` is a no-op shift on the
     final sequence — but D26-27 verifies it lands ``integrate_deltas``
     after the LAST delta producer (stratigraphy) so neither morphology
     nor stratigraphy outputs are stranded.

Running order is the contract: producer-pass → integrator → consumer.
Without it the next pass that overrides ``height`` (e.g. composite,
talus, lava) silently drops the delta, which is the exact failure mode
the F820-F825 dead-delta epidemic encoded.
"""

from __future__ import annotations

import numpy as np

from veilbreakers_terrain.handlers.terrain_pipeline import (
    TerrainPassController,
    _normalize_delta_integration_sequence,
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
# Fixtures
# ---------------------------------------------------------------------------


def _intent_with_scene_read(quality_profile: str = "aaa_open_world") -> TerrainIntentState:
    """Return an intent that triggers the has_scene_read=True branch.

    Phase C D26-27 schedules stratigraphy + morphology only when scene_read
    is attached (their delta outputs need integrate_deltas, which is itself
    scene_read-gated).
    """
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
        success_criteria=("phase_c_d26_27_test",),
        reviewer="pytest",
    )
    return TerrainIntentState(
        seed=42,
        region_bounds=region_bounds,
        tile_size=32,
        cell_size=1.0,
        quality_profile=quality_profile,
        scene_read=scene_read,
    )


def _intent_without_scene_read() -> TerrainIntentState:
    """Return an intent without scene_read (delta passes should NOT schedule)."""
    region_bounds = BBox(0.0, 0.0, 32.0, 32.0)
    return TerrainIntentState(
        seed=42,
        region_bounds=region_bounds,
        tile_size=32,
        cell_size=1.0,
    )


def _make_stack(size: int = 16, base_height: float = 100.0) -> TerrainMaskStack:
    """Build a flat mask stack at ``base_height``."""
    return TerrainMaskStack(
        tile_size=size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.full((size, size), base_height, dtype=np.float64),
    )


def _make_state(stack: TerrainMaskStack) -> TerrainPipelineState:
    """Build a pipeline state with scene_read attached for delta-pass gating."""
    bounds = BBox(0.0, 0.0, float(stack.tile_size), float(stack.tile_size))
    scene_read = TerrainSceneRead(
        timestamp=0.0,
        major_landforms=("flat",),
        focal_point=(float(stack.tile_size) * 0.5, float(stack.tile_size) * 0.5, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=bounds,
        success_criteria=("phase_c_d26_27_test",),
        reviewer="pytest",
    )
    intent = TerrainIntentState(
        seed=42,
        region_bounds=bounds,
        tile_size=stack.tile_size,
        cell_size=1.0,
        scene_read=scene_read,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# 1. Default-sequence membership
# ---------------------------------------------------------------------------


def test_pass_morphology_in_default_sequence_with_scene_read():
    """``pass_morphology`` must be in the default sequence when scene_read present.

    PR #17 (morphology delta integrator wiring): pass_morphology produces
    ``morphology_delta``. If it's missing from the sequence, the integrator
    has nothing to compose. This pin protects against accidental removal.
    """
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "pass_morphology" in seq, (
        f"pass_morphology missing from default sequence; "
        f"PR #17 morphology delta integrator wiring regressed. seq={seq!r}"
    )


def test_stratigraphy_in_default_sequence_with_scene_read():
    """``stratigraphy`` must be in the default sequence when scene_read present.

    PR #16 (stratigraphy delta integrator wiring): pass_stratigraphy
    produces ``strat_erosion_delta``. Phase A D8 deferred this scheduling
    until the produces_channels gap was fixed in Phase C D26-27.
    """
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "stratigraphy" in seq, (
        f"stratigraphy missing from default sequence; "
        f"PR #16 stratigraphy delta integrator wiring regressed. seq={seq!r}"
    )


def test_integrate_deltas_in_default_sequence_with_scene_read():
    """``integrate_deltas`` must be in the default sequence when scene_read present.

    Without the integrator the producer outputs (morphology_delta,
    strat_erosion_delta, etc.) accumulate on the mask stack but never
    reach ``height``. This is the F820-F825 dead-delta failure mode.
    """
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "integrate_deltas" in seq, (
        f"integrate_deltas missing from default sequence; "
        f"deltas would be stranded. seq={seq!r}"
    )


def test_delta_passes_skipped_without_scene_read():
    """The delta producer/integrator passes are scene_read-gated.

    Their outputs require ``integrate_deltas`` which itself only schedules
    with ``has_scene_read=True``. Scheduling them without scene_read
    produces stranded deltas (same anti-pattern Phase A D8-9 corrected).
    """
    intent = _intent_without_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "stratigraphy" not in seq, (
        f"stratigraphy must be gated on has_scene_read; got it in {seq!r}"
    )
    assert "integrate_deltas" not in seq, (
        f"integrate_deltas must be gated on has_scene_read; got it in {seq!r}"
    )


# ---------------------------------------------------------------------------
# 2. Position invariants — producers MUST precede integrate_deltas
# ---------------------------------------------------------------------------


def test_pass_morphology_precedes_integrate_deltas():
    """``pass_morphology`` (producer) must run BEFORE ``integrate_deltas``.

    morphology_delta is a *deferred* delta that integrate_deltas composes
    into ``height``. If pass_morphology runs after the integrator the
    delta sits on the stack until the next pass overrides ``height`` and
    silently discards it.
    """
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "pass_morphology" in seq and "integrate_deltas" in seq, (
        f"missing producer/integrator; seq={seq!r}"
    )
    morph_idx = seq.index("pass_morphology")
    deltas_idx = seq.index("integrate_deltas")
    assert morph_idx < deltas_idx, (
        f"pass_morphology must precede integrate_deltas; got "
        f"morph at {morph_idx}, integrate_deltas at {deltas_idx}, seq={seq!r}"
    )


def test_stratigraphy_precedes_integrate_deltas():
    """``stratigraphy`` (producer) must run BEFORE ``integrate_deltas``.

    strat_erosion_delta is the deferred channel pass_stratigraphy writes
    in lieu of mutating height directly. integrate_deltas composes it
    into the final heightfield — so the producer must precede it.
    """
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "stratigraphy" in seq and "integrate_deltas" in seq, (
        f"missing producer/integrator; seq={seq!r}"
    )
    strat_idx = seq.index("stratigraphy")
    deltas_idx = seq.index("integrate_deltas")
    assert strat_idx < deltas_idx, (
        f"stratigraphy must precede integrate_deltas; got "
        f"strat at {strat_idx}, integrate_deltas at {deltas_idx}, seq={seq!r}"
    )


def test_integrate_deltas_precedes_consumers():
    """``integrate_deltas`` must run BEFORE consumers that read final ``height``.

    materials_v2 + scatter + horizon_lod + structural_masks_post_talus all
    read post-integrated height. If integrate_deltas runs after them the
    composition collapses.
    """
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "integrate_deltas" in seq, f"integrate_deltas missing; seq={seq!r}"
    deltas_idx = seq.index("integrate_deltas")
    # materials_v2 is the canonical post-integration height consumer.
    assert "materials_v2" in seq, f"materials_v2 missing; seq={seq!r}"
    materials_idx = seq.index("materials_v2")
    assert deltas_idx < materials_idx, (
        f"integrate_deltas must precede materials_v2; got "
        f"integrate_deltas at {deltas_idx}, materials_v2 at {materials_idx}"
    )


def test_each_producer_appears_exactly_once():
    """Producer + integrator passes must each appear exactly once.

    Duplicate scheduling would re-run the producer and overwrite its
    delta channel, or re-integrate already-applied delta into height
    (double-application bug pattern).
    """
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    for pass_name in ("pass_morphology", "stratigraphy", "integrate_deltas"):
        count = seq.count(pass_name)
        assert count == 1, (
            f"{pass_name} appears {count} times in default sequence; "
            f"expected exactly 1. seq={seq!r}"
        )


# ---------------------------------------------------------------------------
# 3. Delta-channel registry — both deltas must be known to integrator
# ---------------------------------------------------------------------------


def test_morphology_delta_in_known_delta_channels():
    """``morphology_delta`` is in the integrator's known delta-channel set."""
    from veilbreakers_terrain.handlers.terrain_delta_integrator import _DELTA_CHANNELS

    assert "morphology_delta" in _DELTA_CHANNELS, (
        f"morphology_delta missing from _DELTA_CHANNELS={_DELTA_CHANNELS!r}; "
        "PR #17 wiring regressed."
    )


def test_strat_erosion_delta_in_known_delta_channels():
    """``strat_erosion_delta`` is in the integrator's known delta-channel set."""
    from veilbreakers_terrain.handlers.terrain_delta_integrator import _DELTA_CHANNELS

    assert "strat_erosion_delta" in _DELTA_CHANNELS, (
        f"strat_erosion_delta missing from _DELTA_CHANNELS={_DELTA_CHANNELS!r}; "
        "PR #16 wiring regressed."
    )


# ---------------------------------------------------------------------------
# 4. Registration contracts — strat overrides + aux channels declared
# ---------------------------------------------------------------------------


def test_stratigraphy_registration_declares_height_override():
    """``stratigraphy`` PassDefinition must declare ``overrides=("height",)``.

    pass_stratigraphy.simulate_fold_deformation writes ``stack.height`` when
    ``hints.fold_enabled`` is True (default). Without overrides=("height",)
    the ChannelOwnershipError check at register time would refuse the
    duplicate-producer registration.
    """
    snapshot = dict(TerrainPassController.PASS_REGISTRY)
    try:
        TerrainPassController.PASS_REGISTRY.clear()
        from veilbreakers_terrain.handlers.terrain_geology_validator import (
            register_bundle_i_passes,
        )

        # register_bundle_i_passes requires terrain_pipeline default passes
        # to be registered first so duplicate-producer detection has a
        # baseline. Use the master registrar to populate the registry.
        from veilbreakers_terrain.handlers.terrain_pipeline import (
            register_default_passes,
        )

        register_default_passes(strict=False)
        register_bundle_i_passes()
        defn = TerrainPassController.PASS_REGISTRY["stratigraphy"]
        assert "height" in defn.overrides, (
            f"stratigraphy must declare overrides=('height',); "
            f"got overrides={defn.overrides!r}"
        )
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(snapshot)


def test_stratigraphy_registration_declares_aux_height_channels():
    """``stratigraphy`` must declare sediment/bedrock/strata heights as produced.

    pass_stratigraphy writes 3 aux height channels (``sediment_height``,
    ``bedrock_height``, ``strata_height``) at lines 1081-1083 of
    terrain_stratigraphy.py. Phase A D8 had them missing from the
    registration; Phase C D26-27 closes the gap so that
    ``terrain_unity_export`` (sediment_height + bedrock_height) and any
    geology-aware downstream consumer sees a registered producer.
    """
    snapshot = dict(TerrainPassController.PASS_REGISTRY)
    try:
        TerrainPassController.PASS_REGISTRY.clear()
        from veilbreakers_terrain.handlers.terrain_geology_validator import (
            register_bundle_i_passes,
        )
        from veilbreakers_terrain.handlers.terrain_pipeline import (
            register_default_passes,
        )

        register_default_passes(strict=False)
        register_bundle_i_passes()
        defn = TerrainPassController.PASS_REGISTRY["stratigraphy"]
        for ch in ("sediment_height", "bedrock_height", "strata_height"):
            assert ch in defn.produces_channels, (
                f"stratigraphy must declare {ch!r} in produces_channels; "
                f"got produces_channels={defn.produces_channels!r}"
            )
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(snapshot)


def test_pass_morphology_registration_produces_morphology_delta():
    """``pass_morphology`` PassDefinition must produce ``morphology_delta``.

    Pin the contract so a refactor that renames the delta channel
    triggers an explicit failure rather than silently breaking the
    integrator pipeline.
    """
    snapshot = dict(TerrainPassController.PASS_REGISTRY)
    try:
        TerrainPassController.PASS_REGISTRY.clear()
        from veilbreakers_terrain.handlers.terrain_morphology import (
            register_morphology_pass,
        )

        register_morphology_pass()
        defn = TerrainPassController.PASS_REGISTRY["pass_morphology"]
        assert "morphology_delta" in defn.produces_channels, (
            f"pass_morphology must produce morphology_delta; "
            f"got produces_channels={defn.produces_channels!r}"
        )
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(snapshot)


# ---------------------------------------------------------------------------
# 5. _normalize_delta_integration_sequence — landed-position pin
# ---------------------------------------------------------------------------


def test_normalize_places_integrator_after_morphology_when_only_producer():
    """When morphology is the only delta producer, integrate_deltas lands after it."""
    snapshot = dict(TerrainPassController.PASS_REGISTRY)
    try:
        TerrainPassController.PASS_REGISTRY.clear()
        from veilbreakers_terrain.handlers.terrain_delta_integrator import (
            register_integrator_pass,
        )
        from veilbreakers_terrain.handlers.terrain_morphology import (
            register_morphology_pass,
        )

        register_integrator_pass()
        register_morphology_pass()

        seq = ["pass_morphology", "integrate_deltas", "downstream_consumer"]
        normalised = _normalize_delta_integration_sequence(seq)
        # integrate_deltas must end up at index 1 (after pass_morphology).
        assert normalised.index("integrate_deltas") == 1, (
            f"integrate_deltas must land directly after pass_morphology; "
            f"got normalised={normalised!r}"
        )
        # The single-producer test also pins that morph runs first.
        assert normalised.index("pass_morphology") < normalised.index("integrate_deltas")
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(snapshot)


def test_normalize_places_integrator_after_stratigraphy_when_last_producer():
    """When stratigraphy is the LAST delta producer, integrator follows it.

    Pins the placement contract: integrate_deltas always lands after the
    last delta-producing pass in the registry — never before.
    """
    snapshot = dict(TerrainPassController.PASS_REGISTRY)
    try:
        TerrainPassController.PASS_REGISTRY.clear()
        from veilbreakers_terrain.handlers.terrain_delta_integrator import (
            register_integrator_pass,
        )
        from veilbreakers_terrain.handlers.terrain_morphology import (
            register_morphology_pass,
        )
        from veilbreakers_terrain.handlers.terrain_pipeline import (
            register_default_passes,
        )
        from veilbreakers_terrain.handlers.terrain_geology_validator import (
            register_bundle_i_passes,
        )

        register_default_passes(strict=False)
        register_morphology_pass()
        register_bundle_i_passes()
        register_integrator_pass()

        # Sequence with stratigraphy as the LAST producer (after morphology).
        seq = [
            "pass_morphology",
            "stratigraphy",
            "integrate_deltas",
            "downstream_consumer",
        ]
        normalised = _normalize_delta_integration_sequence(seq)
        strat_idx = normalised.index("stratigraphy")
        deltas_idx = normalised.index("integrate_deltas")
        assert strat_idx < deltas_idx, (
            f"integrate_deltas must follow stratigraphy (last producer); "
            f"got strat at {strat_idx}, integrate_deltas at {deltas_idx}, "
            f"normalised={normalised!r}"
        )
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(snapshot)


# ---------------------------------------------------------------------------
# 6. End-to-end: deltas flow through integrator into height
# ---------------------------------------------------------------------------


def test_morphology_delta_integrates_into_height_end_to_end():
    """Inject a morphology_delta and confirm integrate_deltas applies it.

    Models the full PR #17 contract: a deferred morphology delta on the
    mask stack is composed into ``stack.height`` by ``pass_integrate_deltas``.
    """
    from veilbreakers_terrain.handlers.terrain_delta_integrator import (
        pass_integrate_deltas,
    )

    stack = _make_stack(size=12, base_height=50.0)
    h_before = stack.height.copy()

    delta = np.zeros_like(stack.height, dtype=np.float32)
    delta[5:7, 5:7] = -1.5  # carve a 2x2 dip
    stack.set("morphology_delta", delta, "pass_morphology")

    state = _make_state(stack)
    result = pass_integrate_deltas(state, None)

    assert result.status == "ok", f"integrate_deltas failed: {result!r}"
    assert "morphology_delta" in result.metrics["delta_channels_applied"], (
        f"morphology_delta not applied; metrics={result.metrics!r}"
    )
    # The 4 carved cells dropped 1.5m; surrounding cells unchanged.
    np.testing.assert_array_almost_equal(
        stack.height[5:7, 5:7], h_before[5:7, 5:7] - 1.5,
        err_msg="morphology_delta did not subtract from height in carved region",
    )
    np.testing.assert_array_almost_equal(
        stack.height[0:5, :], h_before[0:5, :],
        err_msg="morphology_delta leaked into uncarved region",
    )


def test_strat_erosion_delta_integrates_into_height_end_to_end():
    """Inject a strat_erosion_delta and confirm integrate_deltas applies it.

    Models the full PR #16 contract: pass_stratigraphy writes
    ``strat_erosion_delta`` (NOT directly mutating height — height is
    mutated only via the fold deformation path). The integrator composes
    that delta into ``height`` so downstream materials/scatter/export
    consumers see the eroded surface.
    """
    from veilbreakers_terrain.handlers.terrain_delta_integrator import (
        pass_integrate_deltas,
    )

    stack = _make_stack(size=12, base_height=80.0)
    h_before = stack.height.copy()

    # Stratigraphy erosion always lowers height (negative delta).
    delta = np.full_like(stack.height, -0.75, dtype=np.float32)
    stack.set("strat_erosion_delta", delta, "stratigraphy")

    state = _make_state(stack)
    result = pass_integrate_deltas(state, None)

    assert result.status == "ok", f"integrate_deltas failed: {result!r}"
    assert "strat_erosion_delta" in result.metrics["delta_channels_applied"], (
        f"strat_erosion_delta not applied; metrics={result.metrics!r}"
    )
    # Every cell should be 0.75m lower.
    np.testing.assert_array_almost_equal(
        stack.height, h_before - 0.75,
        err_msg="strat_erosion_delta did not lower height uniformly",
    )


def test_both_deltas_compose_additively_in_single_integration():
    """morphology_delta AND strat_erosion_delta both integrate in one pass.

    The integrator is additive — both deltas land in ``height`` after one
    pass_integrate_deltas call. This pins the composition contract that
    keeps PR #16 + PR #17 from interfering with each other.
    """
    from veilbreakers_terrain.handlers.terrain_delta_integrator import (
        pass_integrate_deltas,
    )

    stack = _make_stack(size=12, base_height=100.0)
    h_before = stack.height.copy()

    morph_delta = np.zeros_like(stack.height, dtype=np.float32)
    morph_delta[2:4, 2:4] = +2.0  # raise a corner

    strat_delta = np.full_like(stack.height, -0.5, dtype=np.float32)  # global lowering

    stack.set("morphology_delta", morph_delta, "pass_morphology")
    stack.set("strat_erosion_delta", strat_delta, "stratigraphy")

    state = _make_state(stack)
    result = pass_integrate_deltas(state, None)

    assert result.status == "ok"
    applied = set(result.metrics["delta_channels_applied"])
    assert {"morphology_delta", "strat_erosion_delta"}.issubset(applied), (
        f"both deltas must be applied; got {applied!r}"
    )

    # In the morph-raised square: +2.0 from morph, -0.5 from strat = +1.5 net
    np.testing.assert_array_almost_equal(
        stack.height[2:4, 2:4], h_before[2:4, 2:4] + 1.5,
        err_msg="composed delta wrong in morph-raised region",
    )
    # Outside morph zone: -0.5 from strat only
    np.testing.assert_array_almost_equal(
        stack.height[8:10, 8:10], h_before[8:10, 8:10] - 0.5,
        err_msg="strat-only region lost the strat delta",
    )


# ---------------------------------------------------------------------------
# 7. Position-relative-to-other-producers — coherence with Phase A D8 wiring
# ---------------------------------------------------------------------------


def test_stratigraphy_follows_pass_morphology_in_default_sequence():
    """``stratigraphy`` runs after ``pass_morphology``.

    Both are delta producers; both feed integrate_deltas. Phase A D8
    inserted morphology in the early validation_full block; Phase C D26-27
    inserts stratigraphy in the late prereq block (after wind_erosion).
    Position is contract because stratigraphy's height fold path may
    operate on the morphology-augmented height (when integrated) and
    downstream contract assumes morph runs first.
    """
    intent = _intent_with_scene_read()
    seq = build_default_pass_sequence(intent)
    assert "pass_morphology" in seq and "stratigraphy" in seq, (
        f"both producers must be scheduled; seq={seq!r}"
    )
    morph_idx = seq.index("pass_morphology")
    strat_idx = seq.index("stratigraphy")
    assert morph_idx < strat_idx, (
        f"pass_morphology must precede stratigraphy in default sequence; "
        f"got morph at {morph_idx}, strat at {strat_idx}"
    )
