"""Phase A D14-15 / GATE D15 regression tests.

Pins four bake-side P0 fixes that close out Phase A:

  * B15-P0-17 — stratigraphy bedrock_height computed POST-integration
                so consumers reading between stratigraphy and
                integrate_deltas see a value consistent with the
                post-integrated surface (not the pre-integration
                height).
  * B15-P0-18 — apply_differential_erosion.hardness_above shifts in
                world Z (gravity-up) via the strat_stack layer table,
                NOT in row direction. Pre-fix: horizontally bedded
                mesas with hard caprock above soft shale produced
                zero undercut because adjacent rows had identical
                hardness.
  * B15-P0-21 — pass_horizon_lod registration declares
                overrides=("lod_bias","horizon_elevation_angles") on
                BOTH primary and alias names so the topo-sort edge
                suppression treats both as canonical writers. Pre-fix
                only the alias had overrides; primary was silently
                dropped via ChannelOwnershipError if any other pass
                touched horizon_elevation_angles first.
  * Foam Beaufort cubic — bake_foam_vertex_alpha implements the
                Monahan & O'Muircheartaigh 1986 whitecap formula with
                a cubic open-water term, replacing the inverted
                pre-fix `1 - flow_speed/max_speed` that suppressed
                foam at high flow.

These tests are the GATE D15 ratchet — bake-side P0 fixes landed.
"""

from __future__ import annotations

import inspect

import numpy as np


# ---------------------------------------------------------------------------
# B15-P0-17 — bedrock_height post-integration
# ---------------------------------------------------------------------------


def test_b15_p0_17_bedrock_height_uses_predicted_post_integration():
    """Stratigraphy must compute bedrock_height from height + erosion_delta.

    Pre-fix the formula was `height - sediment_height` using the
    pre-integration `stack.height`. Consumers running between
    stratigraphy and integrate_deltas saw a value that differed from
    the eventually-integrated surface.
    """
    import re

    from veilbreakers_terrain.handlers import terrain_stratigraphy as mod

    src = inspect.getsource(mod)
    assert "predicted_post_height" in src, (
        "stratigraphy: predicted_post_height variable missing — "
        "B15-P0-17 fix not applied"
    )
    # Pin the additive prediction: predicted_post_height = height + erosion_delta
    # (allow either inline `+ np.asarray(erosion_delta...)` or assignment to an
    # intermediate variable like `erosion_delta_arr` that is then added).
    pattern = re.compile(
        r"predicted_post_height\s*=\s*\(\s*"
        r"np\.asarray\(\s*height[^)]*\)\s*\+\s*"
        r"(?:np\.asarray\(\s*erosion_delta[^)]*\)|erosion_delta_arr)"
    )
    assert pattern.search(src) is not None, (
        "stratigraphy: predicted_post_height does not add erosion_delta "
        "to pre-integration height — B15-P0-17 regression"
    )


# ---------------------------------------------------------------------------
# B15-P0-18 — hardness_above via strat_stack layer table (Z-axis)
# ---------------------------------------------------------------------------


def test_b15_p0_18_hardness_above_uses_strat_stack_layer_table():
    """apply_differential_erosion: hardness_above must look up by elevation."""
    from veilbreakers_terrain.handlers import terrain_stratigraphy as mod

    src = inspect.getsource(mod.apply_differential_erosion)
    # The pre-fix row-shift pattern must be ABSENT.
    assert "np.pad(hardness, ((0, 1), (0, 0)), mode=\"edge\")[1:]" not in src, (
        "B15-P0-18 REGRESSION — row-shift hardness_above reintroduced; "
        "horizontal-bedded mesas will silently lose undercut."
    )
    # The strat_stack-driven Z-axis lookup must be PRESENT.
    assert "strat_stack" in src and "cum_tops" in src, (
        "B15-P0-18 fix missing — apply_differential_erosion does not "
        "use strat_stack.layers for the hardness_above lookup"
    )
    assert "h + 1.0" in src, (
        "B15-P0-18 fix missing — hardness_above lookup does not "
        "offset by 1m above current surface"
    )


def test_b15_p0_18_hardness_above_horizontal_bed_produces_undercut():
    """Hard caprock above soft shale must produce non-zero undercut."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    from veilbreakers_terrain.handlers.terrain_stratigraphy import (
        StratigraphyLayer,
        StratigraphyStack,
        apply_differential_erosion,
    )

    # 8x8 mesa with relief: stepped surface from z=8 (edges) to z=12 (centre)
    # so `relief_span > 0` and `relief_norm > 0` for interior cells. Without
    # relief the function short-circuits to zeros regardless of hardness
    # contrast (apply_differential_erosion only erodes proportional to local
    # height above min). Soft shale 0-9m, hard caprock 9-12m.
    rows, cols = 8, 8
    height = np.full((rows, cols), 8.0, dtype=np.float32)
    height[2:6, 2:6] = 12.0  # raised central plateau crests above caprock
    # rock_hardness at the surface — caprock is hard.
    rock_hardness = np.full((rows, cols), 0.9, dtype=np.float32)
    stack = TerrainMaskStack(
        height=height,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_size=rows,
        tile_x=0,
        tile_y=0,
    )
    stack.set("rock_hardness", rock_hardness, "test_setup")

    strat_stack = StratigraphyStack(
        base_elevation_m=0.0,
        layers=[
            StratigraphyLayer(
                layer_id="shale",
                hardness=0.2,  # soft
                thickness_m=9.0,
                rock_type="sedimentary",
            ),
            StratigraphyLayer(
                layer_id="caprock",
                hardness=0.95,  # hard
                thickness_m=3.0,
                rock_type="igneous",
            ),
        ],
    )

    delta = apply_differential_erosion(
        stack,
        strat_stack=strat_stack,
        max_erosion_fraction=0.12,
        undercutting_strength=0.4,
    )
    assert delta.shape == (rows, cols)
    assert np.all(np.isfinite(delta)), "delta must be finite"
    # PR #39 Copilot review: assert NON-ZERO undercut. The pre-fix
    # row-shift bug produced exactly delta == 0 everywhere on
    # horizontal-bedded mesas because hardness_above == hardness for
    # every row pair. The Z-axis lookup must produce some erosion at
    # the soft layer when the hard cap sits above it.
    assert np.any(np.abs(delta) > 0.0), (
        "B15-P0-18 REGRESSION — horizontal-bedded mesa with hard cap "
        "above soft shale produced ZERO undercut everywhere; the "
        "Z-axis hardness lookup is not engaged"
    )
    # Erosion delta must be non-positive (erosion only — no deposition
    # in this pass).
    assert np.all(delta <= 1e-6), f"delta should be <=0; max={delta.max():.4f}"


# ---------------------------------------------------------------------------
# B15-P0-21 — horizon_lod overrides on primary registration
# ---------------------------------------------------------------------------


def test_b15_p0_21_horizon_lod_primary_has_overrides():
    """Both `horizon_lod` and `pass_horizon_lod` registrations must declare overrides."""
    from veilbreakers_terrain.handlers import terrain_horizon_lod as mod

    src = inspect.getsource(mod.register_bundle_l_horizon_lod_pass)
    # Pre-fix: only the alias `pass_horizon_lod` had overrides via a
    # ternary `if name == "pass_horizon_lod" else ()`. Pin the absence
    # of that conditional shape; both names must declare the same tuple.
    assert "if name == \"pass_horizon_lod\" else ()" not in src, (
        "B15-P0-21 REGRESSION — primary `horizon_lod` registration "
        "missing overrides; bundle silently dropped via "
        "ChannelOwnershipError on contention"
    )
    assert (
        "overrides=(\"lod_bias\", \"horizon_elevation_angles\")" in src
    ), (
        "B15-P0-21 fix missing — horizon_lod registrations do not "
        "declare overrides=(lod_bias, horizon_elevation_angles)"
    )


def test_b15_p0_21_horizon_lod_both_definitions_have_same_overrides():
    """Verify the registered PassDefinition objects carry overrides on both names."""
    from veilbreakers_terrain.handlers.terrain_horizon_lod import (
        register_bundle_l_horizon_lod_pass,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
    )

    # Snapshot + restore the registry around our re-registration so we
    # don't pollute other tests in the same process.
    original = dict(TerrainPassController.PASS_REGISTRY)
    try:
        # Force a fresh re-registration by removing prior entries.
        for name in ("horizon_lod", "pass_horizon_lod"):
            TerrainPassController.PASS_REGISTRY.pop(name, None)
        register_bundle_l_horizon_lod_pass()
        primary = TerrainPassController.PASS_REGISTRY.get("horizon_lod")
        alias = TerrainPassController.PASS_REGISTRY.get("pass_horizon_lod")
        assert primary is not None, "horizon_lod registration missing"
        assert alias is not None, "pass_horizon_lod registration missing"
        expected_overrides = ("lod_bias", "horizon_elevation_angles")
        assert tuple(primary.overrides) == expected_overrides, (
            f"horizon_lod overrides={primary.overrides!r}, expected "
            f"{expected_overrides!r}"
        )
        assert tuple(alias.overrides) == expected_overrides, (
            f"pass_horizon_lod overrides={alias.overrides!r}, expected "
            f"{expected_overrides!r}"
        )
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(original)


# ---------------------------------------------------------------------------
# Foam Beaufort cubic — bake_foam_vertex_alpha
# ---------------------------------------------------------------------------


def test_foam_beaufort_cubic_speed_ratio_is_direct_not_inverted():
    """speed_ratio must be `flow_speed/max` — not `1 - flow_speed/max`."""
    from veilbreakers_terrain.handlers import terrain_waterfalls as mod

    src = inspect.getsource(mod.bake_foam_vertex_alpha)
    assert "speed_ratio = saturate(flow_speed / max(max_foam_speed" in src, (
        "Foam regression — speed_ratio must use direct flow_speed/max, "
        "not the inverted (1 - x) form. Beaufort/Monahan: foam scales "
        "WITH flow speed."
    )
    # The pre-fix inverted form must be ABSENT.
    assert "1.0 - flow_speed / max(max_foam_speed" not in src, (
        "Foam regression — inverted speed_ratio (1 - flow_speed/max) "
        "reintroduced; foam will vanish at high flow against AAA physics"
    )


def test_foam_beaufort_cubic_whitecap_term_present():
    """bake_foam_vertex_alpha must include the cubic whitecap_term."""
    from veilbreakers_terrain.handlers import terrain_waterfalls as mod

    src = inspect.getsource(mod.bake_foam_vertex_alpha)
    assert "whitecap_term" in src, (
        "Foam fix missing — whitecap_term not present in "
        "bake_foam_vertex_alpha"
    )
    assert "** 3" in src, (
        "Foam fix missing — Beaufort cubic exponent (** 3) absent; "
        "Monahan/O'Muircheartaigh whitecap formula requires cubic falloff"
    )


def test_foam_beaufort_cubic_whitecap_scales_with_cube_of_speed():
    """Open-water foam (no obstacle) doubles flow ⇒ ~8x foam (cubic)."""
    from veilbreakers_terrain.handlers.terrain_waterfalls import (
        FOAM_RADIUS_DEFAULT,
        bake_foam_vertex_alpha,
    )

    # Far from obstacle, foam == whitecap term only.
    far = FOAM_RADIUS_DEFAULT
    low_speed = 0.85  # well below 3.4 m/s reference
    high_speed = 1.7  # 2x low
    foam_low = bake_foam_vertex_alpha(obstacle_proximity=far, flow_speed=low_speed)
    foam_high = bake_foam_vertex_alpha(
        obstacle_proximity=far, flow_speed=high_speed
    )
    ratio = foam_high / max(float(foam_low), 1e-9)
    assert 7.2 < ratio < 8.8, (
        f"Cubic regime: doubling speed should ~8x whitecap foam; "
        f"got low={foam_low}, high={foam_high}, ratio={ratio:.3f}"
    )


def test_foam_still_water_at_obstacle_produces_no_foam():
    """Zero motion near obstacle: NO foam (still water doesn't whitecap)."""
    from veilbreakers_terrain.handlers.terrain_waterfalls import (
        bake_foam_vertex_alpha,
    )

    foam = bake_foam_vertex_alpha(obstacle_proximity=0.0, flow_speed=0.0)
    assert abs(float(foam)) < 1e-9, (
        f"Still water at obstacle must produce zero foam; got {foam}"
    )
