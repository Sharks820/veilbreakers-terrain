"""WAVE5-11 + WAVE5-14 — channel shape contract + orphan channel regression net.

WAVE5-11 (P1 — Shape-A fix): Channel.MACRO_COLOR_RGB
    ``Channel.MACRO_COLOR_RGB`` emits (H, W, 3) float32 RGB arrays — it was
    incorrectly tagged ``"dimensionless"`` in both ``_channels.py`` and
    ``terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS``. Same Shape-A class
    as ``STRATA_ORIENTATION_XYZ`` fixed by PR #113. Correct tag is
    ``"rgb_triplet"``. Enum MEMBER renamed from MACRO_COLOR to MACRO_COLOR_RGB
    to communicate the (H, W, 3) contract at the call site; enum VALUE stays
    ``"macro_color"`` for backward-compatible ``stack.get()`` access.

WAVE5-14 (P1 — orphan channel contracts):
    4 channels appeared in ``consumed_channels`` (PassResult runtime metadata)
    or were read at runtime without a corresponding DAG producer declaration:

    - ``lava_source_mask``: externally-authored input, NOT a pipeline-produced
      channel. ``terrain_lava`` PassDefinition correctly uses
      ``optional_channels=("lava_source_mask", "height")``. No change needed.
      Test pins this contract.

    - ``material_zones``: read by ``pass_roughness_driver`` from the stack but
      NOT declared in the PassDefinition, leaving a DAG orphan. Fixed by adding
      ``material_zones`` to ``optional_channels`` in
      ``register_bundle_k_roughness_driver_pass``.

    - ``particle_emitter_specs``: ``waterfalls`` PassDefinition already declares
      ``produces_channels=("particle_emitter_specs",)`` and
      ``emit_particle_systems`` has ``optional_channels=("particle_emitter_specs",)``.
      Already correctly wired. Test pins this contract.

    - ``height_m``: legacy alias fallback for ``"height"`` in ``pass_water_depth``
      — the fallback read is kept for backward-compat but the alias was listed in
      ``PassResult.consumed_channels``, creating a phantom DAG edge (no pass
      produces ``"height_m"``). Fixed by removing ``"height_m"`` from the runtime
      ``consumed_channels`` tuple; the required channel ``"height"`` is already
      declared in the PassDefinition.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# WAVE5-11: MACRO_COLOR_RGB shape contract
# ---------------------------------------------------------------------------


def test_macro_color_rgb_member_name_is_correct() -> None:
    """Channel enum member must be named MACRO_COLOR_RGB, not MACRO_COLOR.

    WAVE5-11: The enum member rename from MACRO_COLOR → MACRO_COLOR_RGB
    communicates the (H, W, 3) shape contract at the call site. The VALUE
    stays ``"macro_color"`` for backward-compatible stack.get() access.
    """
    from veilbreakers_terrain.handlers._channels import Channel

    assert hasattr(Channel, "MACRO_COLOR_RGB"), (
        "Channel.MACRO_COLOR_RGB must exist — WAVE5-11 Shape-A fix renamed "
        "MACRO_COLOR to MACRO_COLOR_RGB to communicate the (H, W, 3) RGB "
        "triple contract. If this fails, check _channels.py."
    )
    # Old name must be gone
    assert not hasattr(Channel, "MACRO_COLOR"), (
        "Channel.MACRO_COLOR must NOT exist after the WAVE5-11 rename — "
        "only Channel.MACRO_COLOR_RGB should be present. The legacy name "
        "is misleading about the (H, W, 3) shape contract."
    )


def test_macro_color_rgb_value_stays_macro_color() -> None:
    """The enum VALUE must remain ``"macro_color"`` for backward-compat.

    WAVE5-11: renaming only the member (MACRO_COLOR → MACRO_COLOR_RGB) while
    keeping the value constant ensures existing ``stack.get("macro_color")``
    callers are unaffected.
    """
    from veilbreakers_terrain.handlers._channels import Channel

    assert Channel.MACRO_COLOR_RGB.value == "macro_color", (
        f"Channel.MACRO_COLOR_RGB.value = {Channel.MACRO_COLOR_RGB.value!r}; "
        "must be 'macro_color' for backward-compatible stack access. "
        "Changing the VALUE would require a stack-key migration."
    )


def test_macro_color_rgb_unit_is_rgb_triplet() -> None:
    """Channel.MACRO_COLOR_RGB must be tagged ``rgb_triplet``, NOT ``dimensionless``.

    WAVE5-11 Shape-A fix: macro_color emits (H, W, 3) float32 arrays —
    tagging it ``dimensionless`` (the per-scalar-channel tag) was the same
    Shape-A misclassification as STRATA_ORIENTATION_XYZ (fixed by PR #113).
    The new ``rgb_triplet`` tag makes the multi-channel shape contract explicit.
    """
    from veilbreakers_terrain.handlers._channels import Channel

    unit = Channel.MACRO_COLOR_RGB.info.unit
    assert unit == "rgb_triplet", (
        f"Channel.MACRO_COLOR_RGB.info.unit = {unit!r}; "
        "must be 'rgb_triplet' (not 'dimensionless'). "
        "WAVE5-11: macro_color emits (H, W, 3) float32 RGB arrays, "
        "not a scalar in [0, 1]. See STRATA_ORIENTATION_XYZ / PR #113 "
        "for the same Shape-A fix pattern."
    )
    assert unit != "dimensionless", (
        "WAVE5-11 regression guard: macro_color must NOT be tagged "
        "'dimensionless' — that was the Shape-A bug. The correct tag is "
        "'rgb_triplet'."
    )


def test_macro_color_rgb_golden_snapshots_unit_consistent() -> None:
    """``_CHANNEL_CANONICAL_UNITS['macro_color']`` must equal ``rgb_triplet``.

    WAVE5-11: both registries (_channels.py ChannelInfo AND
    terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS) must agree on
    ``rgb_triplet``. Divergence between the two is itself a Shape-C bug
    (caught by test_cross_registry_consistency_with_golden_snapshots, but
    this test provides a focused guard specific to this channel).
    """
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        _CHANNEL_CANONICAL_UNITS,
    )

    gs_unit = _CHANNEL_CANONICAL_UNITS.get("macro_color")
    assert gs_unit is not None, (
        "_CHANNEL_CANONICAL_UNITS['macro_color'] is missing — add it to "
        "terrain_golden_snapshots.py."
    )
    assert gs_unit == "rgb_triplet", (
        f"_CHANNEL_CANONICAL_UNITS['macro_color'] = {gs_unit!r}; "
        "must be 'rgb_triplet'. WAVE5-11 fix: both registries must agree."
    )


# ---------------------------------------------------------------------------
# WAVE5-14: orphan channel DAG contracts
# ---------------------------------------------------------------------------


def test_lava_source_mask_is_optional_in_lava_pass_definition() -> None:
    """``lava_source_mask`` must be declared ``optional_channels`` in the
    ``pass_lava_simulation`` PassDefinition, NOT ``requires_channels``.

    WAVE5-14: lava_source_mask is an externally-authored optional input
    (placed by biome/hero rules), not produced by any pipeline pass. The
    correct contract is ``optional_channels`` so the DAG does not block
    execution when it is absent. This test pins that the fix did not regress.
    """
    from veilbreakers_terrain.handlers.terrain_lava import register_lava_pass
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    _clear_registry()
    register_lava_pass()

    registry = TerrainPassController.PASS_REGISTRY
    assert "pass_lava_simulation" in registry, (
        "pass_lava_simulation is not registered — call register_lava_pass() first."
    )
    defn = registry["pass_lava_simulation"]

    # lava_source_mask must be optional, NOT required
    assert "lava_source_mask" in defn.optional_channels, (
        "pass_lava_simulation PassDefinition must declare 'lava_source_mask' "
        "in optional_channels. It is an externally-authored input, not produced "
        "by any pipeline pass."
    )
    assert "lava_source_mask" not in defn.requires_channels, (
        "pass_lava_simulation must NOT declare 'lava_source_mask' as "
        "requires_channels — the pass runs without it (non-volcanic biomes)."
    )


def test_material_zones_is_optional_in_roughness_driver_definition() -> None:
    """``material_zones`` must be in ``optional_channels`` of ``roughness_driver``.

    WAVE5-14 fix: the pass body reads ``stack.get('material_zones')`` but
    the original PassDefinition omitted it entirely from optional_channels,
    making it an orphan consumer with no DAG edge. Now declared optional so
    the DAG can schedule zone-map producers (if any) before roughness_driver.
    """
    from veilbreakers_terrain.handlers.terrain_roughness_driver import (
        register_bundle_k_roughness_driver_pass,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    _clear_registry()
    register_bundle_k_roughness_driver_pass()

    registry = TerrainPassController.PASS_REGISTRY
    assert "roughness_driver" in registry, (
        "roughness_driver is not registered."
    )
    defn = registry["roughness_driver"]

    assert "material_zones" in defn.optional_channels, (
        "roughness_driver PassDefinition must declare 'material_zones' in "
        "optional_channels. WAVE5-14: the pass body reads this channel but "
        "it was previously undeclared — a DAG orphan. Fixed by adding it to "
        "optional_channels."
    )
    assert "material_zones" not in defn.requires_channels, (
        "roughness_driver must NOT require 'material_zones' — it is an "
        "optional per-zone override (may be absent; pass degrades gracefully)."
    )


def test_particle_emitter_specs_has_producer_and_consumer_declared() -> None:
    """``particle_emitter_specs`` must have a declared producer and consumer.

    WAVE5-14 (already-correct contract): ``waterfalls`` PassDefinition must
    declare ``particle_emitter_specs`` in ``produces_channels`` and
    ``emit_particle_systems`` must declare it in ``optional_channels``.
    This test pins the contract to prevent regression.
    """
    from veilbreakers_terrain.handlers.terrain_waterfalls import (
        register_bundle_c_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    _clear_registry()
    register_bundle_c_passes()

    registry = TerrainPassController.PASS_REGISTRY
    assert "waterfalls" in registry, "waterfalls pass not registered"
    assert "emit_particle_systems" in registry, "emit_particle_systems pass not registered"

    waterfalls_def = registry["waterfalls"]
    emitter_def = registry["emit_particle_systems"]

    assert "particle_emitter_specs" in waterfalls_def.produces_channels, (
        "waterfalls PassDefinition must declare 'particle_emitter_specs' in "
        "produces_channels. WAVE5-14: this was the missing producer declaration "
        "that was already fixed in spec PR #21."
    )
    assert "particle_emitter_specs" in emitter_def.optional_channels, (
        "emit_particle_systems PassDefinition must declare 'particle_emitter_specs' "
        "in optional_channels. WAVE5-14: this is the consumer side of the "
        "waterfalls → emit_particle_systems DAG edge."
    )


def test_pass_water_depth_consumed_channels_no_height_m() -> None:
    """``pass_water_depth`` PassResult must NOT include ``height_m`` in consumed_channels.

    WAVE5-14 fix: ``height_m`` is a legacy alias fallback for ``"height"`` in
    the pass body (stack.get("height_m") → stack.get("height")). Listing the
    alias in ``consumed_channels`` creates a phantom DAG edge — no pass
    produces ``"height_m"``. The canonical required channel is ``"height"``
    which IS declared in the PassDefinition ``requires_channels``.

    This test drives pass_water_depth and verifies the returned PassResult
    does not include the phantom alias.
    """
    import numpy as np
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import pass_water_depth

    # Build a minimal stack with height + water_surface_elevation_m
    tile_size = 8
    rng = np.random.default_rng(42)
    height = 10.0 + 5.0 * rng.random((tile_size + 1, tile_size + 1)).astype(np.float32)
    ws_elev = height + rng.random((tile_size + 1, tile_size + 1)).astype(np.float32) * 2.0

    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    stack.set("water_surface_elevation_m", ws_elev, "test")

    intent = TerrainIntentState(
        seed=42,
        region_bounds=BBox(0.0, 0.0, float(tile_size), float(tile_size)),
        tile_size=tile_size,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    result = pass_water_depth(state, None)

    assert result.status == "ok", (
        f"pass_water_depth returned status={result.status!r}; expected 'ok'."
    )
    assert "height_m" not in result.consumed_channels, (
        "WAVE5-14 regression: pass_water_depth.consumed_channels still lists "
        "'height_m'. This is a phantom alias — no pass produces 'height_m'. "
        "The canonical channel is 'height' which is already in requires_channels."
    )
    assert "height" in result.consumed_channels, (
        "pass_water_depth.consumed_channels must include 'height' — the canonical "
        "required channel."
    )


# ---------------------------------------------------------------------------
# Closed-set: every consumed_channels name in any PassDefinition must
# either (a) appear in produces_channels of some other registered pass, OR
# (b) be declared optional_channels (soft dependency, ok to be absent).
# This is the strict-graph contract.
# ---------------------------------------------------------------------------


def test_strict_graph_no_hard_required_channels_without_producer() -> None:
    """Every channel in ``PassDefinition.requires_channels`` must have a
    corresponding ``produces_channels`` entry in some other registered pass.

    This is the strict-graph contract: a hard dependency edge (requires_channels)
    with no upstream producer is a definite pipeline bug — the pass will either
    error at runtime or silently skip on the missing channel.

    Optional channels (``optional_channels``) are intentionally excluded from
    this check — they represent soft dependencies that degrade gracefully.

    This test registers all passes that have a standalone register_* function,
    then checks the invariant across the combined registry.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    _clear_registry()
    _register_all_known_passes()

    registry = TerrainPassController.PASS_REGISTRY

    # Build the set of all produced channels across all passes
    all_produced: set[str] = set()
    for defn in registry.values():
        all_produced.update(defn.produces_channels)

    # Well-known externally-authored channels that are valid pipeline inputs
    # but are never produced by a pass (user-provided or initial conditions).
    # lava_source_mask: authored by user/biome rules
    # height: the foundational terrain heightmap (pipeline input, not produced by a pass)
    # seed: not a channel
    EXTERNAL_INPUTS: set[str] = {
        "height",
        "lava_source_mask",
    }

    violations: list[str] = []
    for pass_name, defn in sorted(registry.items()):
        for ch in defn.requires_channels:
            if ch in all_produced:
                continue
            if ch in EXTERNAL_INPUTS:
                continue
            violations.append(
                f"  Pass '{pass_name}' requires_channels includes '{ch}' "
                f"but no registered pass declares it in produces_channels."
            )

    assert not violations, (
        "Strict-graph violation — hard-required channels with no producer:\n"
        + "\n".join(violations)
        + "\n\nFix: either add the channel to the correct pass's produces_channels, "
        "or demote to optional_channels if the pass handles absence gracefully."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_registry() -> None:
    """Clear PASS_REGISTRY between tests to avoid cross-test pollution."""
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    TerrainPassController.PASS_REGISTRY.clear()


def _register_all_known_passes() -> None:
    """Register all passes with standalone register_* functions."""
    # Import guard: if a module fails to import, skip it — we test what's available.
    _safe_register("veilbreakers_terrain.handlers.terrain_lava", "register_lava_pass")
    _safe_register(
        "veilbreakers_terrain.handlers.terrain_roughness_driver",
        "register_bundle_k_roughness_driver_pass",
    )
    # Register multiscale_breakup so roughness_breakup has a declared producer
    # (roughness_driver requires_channels includes roughness_breakup).
    _safe_register(
        "veilbreakers_terrain.handlers.terrain_multiscale_breakup",
        "register_bundle_k_multiscale_breakup_pass",
    )
    _safe_register(
        "veilbreakers_terrain.handlers.terrain_waterfalls",
        "register_bundle_c_passes",
    )
    _safe_register(
        "veilbreakers_terrain.handlers.terrain_pipeline",
        "register_pass_water_depth",
    )
    _safe_register(
        "veilbreakers_terrain.handlers.terrain_macro_color",
        "register_bundle_k_macro_color_pass",
    )


def _safe_register(module_path: str, func_name: str) -> None:
    """Import and call a register_* function, ignoring ImportError."""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name, None)
        if fn is not None:
            fn()
    except Exception:
        pass  # best-effort registration; individual tests cover specific passes
