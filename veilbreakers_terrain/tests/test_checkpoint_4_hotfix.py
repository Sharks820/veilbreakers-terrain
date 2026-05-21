"""Regression tests for the CHECKPOINT-4 V2 hotfix PR.

Closes 4 P0/P1 bugs found by the CHECKPOINT-4 V2 adversarial sweep across
PRs #110-#117. Each bug surfaced a silent-corruption mode at the adjacent
call site of a prior hotfix (the "every silent-corruption fix surfaces a
new silent-corruption mode" cross-PR pattern).

* **ADV-CP4-01** (P0) — ``terrain_cliffs.py`` strata_orientation consumer.
  PR #113 retagged ``Channel.STRATA_ORIENTATION_XYZ`` to ``unit_normal_xyz``
  to surface that the producer writes (H, W, 3) direction cosines, not
  scalar degrees. Two consumer sites (``carve_cliff_system`` line ~825 and
  ``insert_hero_cliff_meshes`` line ~2375) still treated the channel as a
  scalar — calling ``.mean()`` over the (H,W,3) cosine field produced
  ≈0 → ``math.radians(0) = 0`` → strata tilt silently nil for every cliff.

* **ADV-CP4-02** (P0) — ``terrain_assets.py:_build_tree_instance_array``
  wrote ``rng.uniform(0, 2*pi)`` into column 3 of tree_instance_points.
  Column 3 is contractually ``yaw_degrees`` per ``Channel.YAW_DEG`` and
  ``Quaternion.Euler(0, yaw_degrees, 0)`` in
  ``VbFoliageManifestRenderer.cs``. Every tree got rotation in [0, 6.28°]
  → forests faced approximately north.

* **ADV-CP4-03** (P1) — ``foam.generate_foam_mask`` zero-flow guard used
  the GLOBAL water-mask mean speed to decide whether to emit Kelvin wakes
  at any rock. Silenced all wakes in rivers with eddies; spuriously
  generated wakes around stagnant rocks in turbulent reaches. Fixed to
  per-rock local-flow sampling.

* **ADV-CP4-04** (P1) — ``_mesh_bridge.mesh_from_spec`` category-material
  block only assigned ``obj.data.materials[0] = mat``, leaving PR #110's
  placeholder ``None`` slots at indices [1..N-1]. Any face with
  ``material_index >= 1`` rendered as Blender's magenta debug material.

Each test below fails on ``origin/main`` (pre-fix) and passes after the
hotfix lands.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Bug 1 — ADV-CP4-01: strata_orientation consumer raises on scalar drift
# ---------------------------------------------------------------------------


def test_bug1_strata_orientation_consumer_uses_direction_cosines() -> None:
    """``carve_cliff_system`` must read the (H,W,3) direction-cosine channel
    and derive the azimuth via ``atan2(ny_mean, nx_mean)`` rather than
    averaging the cosine field as scalar degrees.

    Pre-fix: ``_arr.mean()`` of a unit-normal field ~ 0 (X/Y components
    cancel, Z dominates but averaged in with X/Y) → ``math.radians(0) = 0``
    → ``strata_cos=1, strata_sin=0`` → strata tilt silently zero regardless
    of the producer's actual bedding direction.

    Round-2 verifier follow-up: this test now exercises the LIVE
    ``carve_cliff_system`` end-to-end and asserts on the resulting
    ``cliff_strata:...:orient_deg=...`` side-effect message emitted at
    ``terrain_cliffs.py:1077``. A revert to ``_arr.mean()`` would emit
    ``orient_deg=0.0`` for a bedding field whose true azimuth is 45°
    (NE), which is exactly what this test now catches.
    """
    from veilbreakers_terrain.handlers.terrain_cliffs import carve_cliff_system
    from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    # Build the standard cliff stack used elsewhere in test_terrain_cliffs.
    tile_size = 48
    N = tile_size + 1
    height = np.zeros((N, N), dtype=np.float64)
    half = N // 2
    height[:half, :] = 40.0
    height[half:, :] = 5.0
    rng = np.random.default_rng(42)
    height += rng.normal(0.0, 0.05, size=height.shape)

    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    compute_base_masks(
        height,
        cell_size=1.0,
        tile_coords=(0, 0),
        stack=stack,
        pass_name="structural_masks",
    )

    # Wire a known bedding orientation: 45° NE azimuth, 30° dip.
    # nx = sin(dip)*cos(az), ny = sin(dip)*sin(az), nz = cos(dip)
    dip_rad = math.radians(30.0)
    az_rad = math.radians(45.0)
    nx = math.sin(dip_rad) * math.cos(az_rad)
    ny = math.sin(dip_rad) * math.sin(az_rad)
    nz = math.cos(dip_rad)
    orient = np.zeros((N, N, 3), dtype=np.float32)
    orient[..., 0] = nx
    orient[..., 1] = ny
    orient[..., 2] = nz
    stack.set("strata_orientation", orient, "test_fixture")

    region_bounds = BBox(0.0, 0.0, float(N), float(N))
    intent = TerrainIntentState(
        seed=1234,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    cliffs = carve_cliff_system(state, region=None)
    assert len(cliffs) >= 1, "synthetic cliff state must yield ≥ 1 cliff"

    # The side-effect format from terrain_cliffs.py is (round-3 split):
    #   cliff_strata:<id>:orient_deg=<dip_deg>:dip_deg=<deg>:azimuth_deg=<deg>:...
    # Find at least one such effect.
    strata_effects = [
        s for s in state.side_effects
        if "cliff_strata:" in s and "orient_deg=" in s
    ]
    assert strata_effects, (
        f"carve_cliff_system did not emit any cliff_strata:...:orient_deg=... "
        f"side effect. side_effects={state.side_effects!r}"
    )
    # Parse all three fields from the first effect.
    import re
    orient_match = re.search(r"orient_deg=(-?\d+(?:\.\d+)?)", strata_effects[0])
    dip_match = re.search(r"dip_deg=(-?\d+(?:\.\d+)?)", strata_effects[0])
    az_match = re.search(r"azimuth_deg=(-?\d+(?:\.\d+)?)", strata_effects[0])
    assert orient_match is not None, (
        f"could not parse orient_deg from {strata_effects[0]!r}"
    )
    assert dip_match is not None, (
        f"PR #118 round-3: cliff_strata side effect must include dip_deg; "
        f"got {strata_effects[0]!r}"
    )
    assert az_match is not None, (
        f"PR #118 round-3: cliff_strata side effect must include azimuth_deg; "
        f"got {strata_effects[0]!r}"
    )
    orient_deg = float(orient_match.group(1))
    dip_deg = float(dip_match.group(1))
    azimuth_deg = float(az_match.group(1))

    # Pre-fix (_arr.mean()) for this unit-normal field would yield
    # mean ≈ (nx+ny+nz)/3 ≈ (0.35+0.35+0.87)/3 ≈ 0.52, then
    # math.radians(0.52) ≈ 0.009 rad → orient_deg ≈ 0.52° (NOT 45°).
    #
    # Round-2 fix (PR #118 round-1/round-2) computed azimuth via
    # atan2(ny_mean, nx_mean) and stored ~45° as "orient_deg", but
    # ``_build_strata_layers`` consumes that value as the DIP angle —
    # for E-facing beds (az ≈ 90°) the layers would dip near-vertical
    # regardless of actual bedding tilt (copilot PRRT_kwDOSDBoMs6DpwYS,
    # codex PRRT_kwDOSDBoMs6DpwdH).
    #
    # Round-3 fix (PR #118 round-3): derive dip from ``acos(nz_mean)``
    # (the geologically-correct interpretation per Channel.STRATA_ORIENTATION_XYZ
    # unit_normal_xyz contract) and pass THAT into ``_build_strata_layers``.
    # The legacy ``orient_deg`` key is rebound to the dip scalar so the
    # side_effects log matches what is actually baked into strata metadata.
    # The azimuth is logged separately for the band-projection trace.
    assert abs(dip_deg - 30.0) < 1.0, (
        f"strata dip_deg={dip_deg:.2f}° but expected ~30° (input fixture "
        f"set dip=30°). Round-3 must derive dip from acos(nz_mean); a "
        f"regression to azimuth-as-dip would give ~45° (the NE azimuth)."
    )
    assert abs(azimuth_deg - 45.0) < 1.0, (
        f"strata azimuth_deg={azimuth_deg:.2f}° but expected ~45° (input "
        f"fixture set az=45° NE). Either the azimuth extraction reverted "
        f"to scalar _arr.mean() (would give ~0°), or atan2 broke."
    )
    # Back-compat: ``orient_deg`` MUST equal ``dip_deg`` post round-3
    # (it is what ``_build_strata_layers`` consumes; the round-2 alias
    # to azimuth was a silent semantic flip).
    assert abs(orient_deg - dip_deg) < 1e-3, (
        f"PR #118 round-3: legacy orient_deg ({orient_deg:.2f}°) must "
        f"equal dip_deg ({dip_deg:.2f}°) — both name the same scalar "
        f"that flows into _build_strata_layers as base_dip."
    )


def test_bug1_strata_orientation_consumer_returns_zero_for_axial_aligned_field() -> None:
    """Sanity counter-test: a bedding field with az=0 (east) must yield
    ``orient_deg ≈ 0`` from the LIVE consumer, demonstrating the test
    above is sensitive to direction not just magnitude.
    """
    from veilbreakers_terrain.handlers.terrain_cliffs import carve_cliff_system
    from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    tile_size = 48
    N = tile_size + 1
    height = np.zeros((N, N), dtype=np.float64)
    half = N // 2
    height[:half, :] = 40.0
    height[half:, :] = 5.0
    rng = np.random.default_rng(42)
    height += rng.normal(0.0, 0.05, size=height.shape)

    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    compute_base_masks(
        height,
        cell_size=1.0,
        tile_coords=(0, 0),
        stack=stack,
        pass_name="structural_masks",
    )

    dip_rad = math.radians(30.0)
    az_rad = 0.0  # east → atan2(0, +) = 0
    nx = math.sin(dip_rad) * math.cos(az_rad)
    ny = math.sin(dip_rad) * math.sin(az_rad)
    nz = math.cos(dip_rad)
    orient = np.zeros((N, N, 3), dtype=np.float32)
    orient[..., 0] = nx
    orient[..., 1] = ny
    orient[..., 2] = nz
    stack.set("strata_orientation", orient, "test_fixture")

    region_bounds = BBox(0.0, 0.0, float(N), float(N))
    intent = TerrainIntentState(
        seed=1234,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    carve_cliff_system(state, region=None)

    import re
    strata_effects = [
        s for s in state.side_effects
        if "cliff_strata:" in s and "orient_deg=" in s
    ]
    assert strata_effects, (
        f"carve_cliff_system did not emit any cliff_strata side effect; "
        f"side_effects={state.side_effects!r}"
    )
    dip_match = re.search(r"dip_deg=(-?\d+(?:\.\d+)?)", strata_effects[0])
    az_match = re.search(r"azimuth_deg=(-?\d+(?:\.\d+)?)", strata_effects[0])
    assert dip_match is not None, (
        f"PR #118 round-3: missing dip_deg in {strata_effects[0]!r}"
    )
    assert az_match is not None, (
        f"PR #118 round-3: missing azimuth_deg in {strata_effects[0]!r}"
    )
    dip_deg = float(dip_match.group(1))
    azimuth_deg = float(az_match.group(1))
    # East-pointing bedding (az=0, dip=30°): the dip is non-zero (input
    # fixture sets it explicitly), but the azimuth is the axis-aligned
    # reference and must be ≈ 0°. This is the counter-test that prevents
    # the regression from re-collapsing dip and azimuth into the same
    # scalar: a code path that fed azimuth into _build_strata_layers
    # would yield base_dip ≈ 0 and pass the older "orient_deg≈0" test,
    # but the actual bedding tilt would not show up in the strata layers.
    # Round-3 splits the two so this test asserts BOTH.
    assert abs(azimuth_deg) < 1.0, (
        f"East-pointing bedding (az=0) must yield azimuth_deg≈0°, "
        f"got {azimuth_deg:.2f}°"
    )
    assert abs(dip_deg - 30.0) < 1.0, (
        f"East-pointing bedding (dip=30°) must yield dip_deg≈30° from "
        f"acos(nz_mean=cos(30°)); got {dip_deg:.2f}°. A regression here "
        f"likely indicates _strata_orient_deg is bound to azimuth (would "
        f"give ~0°) instead of dip."
    )


def test_bug1_strata_orientation_raises_on_scalar_shape() -> None:
    """The consumer must REJECT a scalar (H,W) strata_orientation channel
    instead of silently averaging it. The producer contract is
    ``unit_normal_xyz`` per ``Channel.STRATA_ORIENTATION_XYZ``; any
    upstream regression writing scalar degrees must fail loudly.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )
    from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks
    from veilbreakers_terrain.handlers.terrain_cliffs import carve_cliff_system

    # Build a tiny cliff state mirroring test_terrain_cliffs._build_cliff_state
    tile_size = 16
    N = tile_size + 1
    height = np.zeros((N, N), dtype=np.float64)
    half = N // 2
    height[:half, :] = 40.0
    height[half:, :] = 5.0
    rng = np.random.default_rng(42)
    height += rng.normal(0.0, 0.05, size=height.shape)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    compute_base_masks(
        height,
        cell_size=1.0,
        tile_coords=(0, 0),
        stack=stack,
        pass_name="structural_masks",
    )
    # Write a (H, W) scalar field — the WRONG shape post-PR #113.
    bad_orient = np.full((N, N), 30.0, dtype=np.float32)
    stack.set("strata_orientation", bad_orient, "test_fixture")

    region_bounds = BBox(0.0, 0.0, float(N), float(N))
    intent = TerrainIntentState(
        seed=1234,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    with pytest.raises(ValueError, match=r"strata_orientation must be \(H, W, 3\)"):
        carve_cliff_system(state, region=None)


def _build_cliff_state_with_strata(tile_size: int, dip_deg: float, az_deg: float = 0.0):
    """Build a TerrainPipelineState with a synthetic cliff and a uniform
    strata_orientation channel set to the given dip/azimuth (degrees).

    Mirrors test_terrain_cliffs._build_cliff_state but adds the
    direction-cosine bedding field that the round-2 tests assert against.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )
    from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks

    N = tile_size + 1
    height = np.zeros((N, N), dtype=np.float64)
    half = N // 2
    height[:half, :] = 40.0
    height[half:, :] = 5.0
    rng = np.random.default_rng(42)
    height += rng.normal(0.0, 0.05, size=height.shape)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    compute_base_masks(
        height,
        cell_size=1.0,
        tile_coords=(0, 0),
        stack=stack,
        pass_name="structural_masks",
    )

    dip_rad = math.radians(dip_deg)
    az_rad = math.radians(az_deg)
    nx = math.sin(dip_rad) * math.cos(az_rad)
    ny = math.sin(dip_rad) * math.sin(az_rad)
    nz = math.cos(dip_rad)
    orient = np.zeros((N, N, 3), dtype=np.float32)
    orient[..., 0] = nx
    orient[..., 1] = ny
    orient[..., 2] = nz
    stack.set("strata_orientation", orient, "test_fixture")

    region_bounds = BBox(0.0, 0.0, float(N), float(N))
    intent = TerrainIntentState(
        seed=1234,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def test_bug1b_insert_hero_cliff_mesh_uses_dip_for_style_hint() -> None:
    """Round-2 verifier follow-up: ``insert_hero_cliff_meshes`` (the SECOND
    consumer of strata_orientation, line ~2400) must derive the dip
    angle from the (H,W,3) bedding field via ``acos(nz)`` and bucket
    into ``granite`` / ``fractured_granite`` / ``layered_shale``.

    Pre-fix: ``_arr.mean()`` over the cosine field → ≈ 0 → style fell
    through to default ``granite`` for every cliff regardless of the
    bedding dip. Round-1 PR #118 fixed the code path but added no
    regression test that wires a known dip and checks the chosen style.

    This test wires three dip buckets (10°, 45°, 75°) and asserts the
    side-effect ``insert_hero_cliff_mesh:...:style=<style>`` matches the
    expected bucket. The 45° → fractured_granite and 75° → layered_shale
    cases would silently fall back to ``granite`` if the consumer
    regressed.
    """
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        carve_cliff_system,
        insert_hero_cliff_meshes,
    )
    import re

    cases = [
        (10.0, "granite"),            # < 30°
        (45.0, "fractured_granite"),  # 30 < dip <= 60
        (75.0, "layered_shale"),      # > 60
    ]
    for dip_deg, expected_style in cases:
        state = _build_cliff_state_with_strata(tile_size=48, dip_deg=dip_deg)
        cliffs = carve_cliff_system(state, region=None)
        assert cliffs, f"dip={dip_deg}°: expected ≥ 1 cliff to be carved"

        before = len(state.side_effects)
        insert_hero_cliff_meshes(state, cliffs)
        new_effects = state.side_effects[before:]

        hero_effects = [s for s in new_effects if "insert_hero_cliff_mesh:" in s]
        assert hero_effects, (
            f"dip={dip_deg}°: no insert_hero_cliff_mesh side-effect; "
            f"new_effects={new_effects!r}"
        )
        m = re.search(r":style=(\w+):", hero_effects[0])
        assert m is not None, (
            f"dip={dip_deg}°: could not parse style from {hero_effects[0]!r}"
        )
        actual_style = m.group(1)
        assert actual_style == expected_style, (
            f"dip={dip_deg}°: expected style={expected_style!r} but got "
            f"{actual_style!r}. If actual=='granite' for all dips, the "
            f"consumer reverted to _arr.mean() and silently lost the "
            f"bedding dip signal."
        )


def test_bug1c_mean_of_degrees_correct_for_mixed_dip_face() -> None:
    """Round-2 verifier P2 follow-up: the dip-extraction site at
    ``terrain_cliffs.py:2400+`` must use mean-of-degrees rather than
    ``acos(mean(nz))`` (mean-of-cosines) to avoid biasing the style
    bucket on faces with mixed dips.

    Bias mechanic: acos is non-linear, so on a face with mixed dips
    ``acos(mean(nz))`` biases away from the true mean. With half cells
    at 30° and half at 85°:
      - true mean dip = (30 + 85)/2 = 57.5° → ``fractured_granite`` (bucket [30, 60])
      - mean(nz) = (cos30 + cos85)/2 ≈ (0.866 + 0.087)/2 ≈ 0.477
        → acos(0.477) ≈ 61.5° → ``layered_shale`` (WRONG BUCKET — biased
        above the 60° threshold by the non-linearity)
      - mean of per-cell dip degrees ≈ 58.4° (live cliff face is
        slightly weighted by face_mask shape) → ``fractured_granite``
        (still below 60°)

    The live cliff system's face_mask is not perfectly 50/50 across
    the field but the spread is large enough that the two methods land
    in different style buckets: pre-fix → ``layered_shale``, post-fix
    → ``fractured_granite``.
    """
    from veilbreakers_terrain.handlers.terrain_cliffs import (
        carve_cliff_system,
        insert_hero_cliff_meshes,
    )
    from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )
    import re

    tile_size = 48
    N = tile_size + 1
    height = np.zeros((N, N), dtype=np.float64)
    half = N // 2
    height[:half, :] = 40.0
    height[half:, :] = 5.0
    rng = np.random.default_rng(42)
    height += rng.normal(0.0, 0.05, size=height.shape)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    compute_base_masks(
        height,
        cell_size=1.0,
        tile_coords=(0, 0),
        stack=stack,
        pass_name="structural_masks",
    )

    # Half the field at dip=30°, half at dip=85° (azimuth=0 for both,
    # so the azimuth path is unaffected — we isolate the dip-style path).
    orient = np.zeros((N, N, 3), dtype=np.float32)
    dip_a, dip_b = math.radians(30.0), math.radians(85.0)
    az_rad = 0.0
    nx_a = math.sin(dip_a) * math.cos(az_rad)
    ny_a = math.sin(dip_a) * math.sin(az_rad)
    nz_a = math.cos(dip_a)
    nx_b = math.sin(dip_b) * math.cos(az_rad)
    ny_b = math.sin(dip_b) * math.sin(az_rad)
    nz_b = math.cos(dip_b)
    orient[:, : N // 2, 0] = nx_a
    orient[:, : N // 2, 1] = ny_a
    orient[:, : N // 2, 2] = nz_a
    orient[:, N // 2 :, 0] = nx_b
    orient[:, N // 2 :, 1] = ny_b
    orient[:, N // 2 :, 2] = nz_b
    stack.set("strata_orientation", orient, "test_fixture")

    region_bounds = BBox(0.0, 0.0, float(N), float(N))
    intent = TerrainIntentState(
        seed=1234,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    cliffs = carve_cliff_system(state, region=None)
    assert cliffs, "synthetic cliff state must yield ≥ 1 cliff"

    before = len(state.side_effects)
    insert_hero_cliff_meshes(state, cliffs)
    new_effects = state.side_effects[before:]

    hero_effects = [s for s in new_effects if "insert_hero_cliff_mesh:" in s]
    assert hero_effects, f"no insert_hero_cliff_mesh side-effect; {new_effects!r}"
    m = re.search(r":style=(\w+):", hero_effects[0])
    assert m is not None
    actual_style = m.group(1)
    # mean of per-cell dips (post-fix) ≈ 58.4° → ≤ 60.0 → fractured_granite.
    # mean of cosines (pre-fix) → acos(0.47) ≈ 62° → layered_shale.
    assert actual_style == "fractured_granite", (
        f"mixed 30°/85° dip face produced style={actual_style!r}; if "
        f"style=='layered_shale' the consumer reverted to acos(mean(nz)) "
        f"and biased above the 60° boundary."
    )


# ---------------------------------------------------------------------------
# Bug 2 — ADV-CP4-02: yaw_degrees [0, 360) contract
# ---------------------------------------------------------------------------


def test_bug2_tree_yaw_is_degrees_not_radians() -> None:
    """``_build_tree_instance_array`` column 3 must be degrees in
    ``[0, 360)`` per ``Channel.YAW_DEG`` contract — not radians in
    ``[0, 2*pi)``.

    Pre-fix the producer wrote ``rng.uniform(0, 2*math.pi)`` so every tree
    got rotation in ``[0, 6.28]`` degrees → forests faced approximately
    north (Unity's ``Quaternion.Euler(0, yaw_degrees, 0)`` interprets
    column 3 as degrees).
    """
    from veilbreakers_terrain.handlers.terrain_assets import (
        AssetContextRule,
        AssetRole,
        _build_tree_instance_array,
    )

    placements: Dict[str, List[Tuple[float, float, float]]] = {
        "oak_tree": [(float(i), 0.0, 0.0) for i in range(2000)],
    }
    rules = [AssetContextRule("oak_tree", AssetRole.VEGETATION_LARGE)]
    rng = np.random.default_rng(42)

    arr = _build_tree_instance_array(placements, rules, rng)

    # Column 3 = yaw_degrees
    yaws = arr[:, 3]
    assert np.all(yaws >= 0.0), f"yaws must be >= 0; min={yaws.min()}"
    assert np.all(yaws <= 360.0), (
        f"yaws must be <= 360 degrees per Channel.YAW_DEG contract; "
        f"max={yaws.max()}. If max < 2*pi ≈ 6.28, the producer is "
        f"still writing radians — restore the rng.uniform(0, 360.0) fix."
    )
    # With 2000 samples uniformly distributed in [0, 360), at least one
    # value must exceed 2*pi ≈ 6.28. If every value is below 2*pi the
    # producer is silently emitting radians.
    assert yaws.max() > 2.0 * math.pi, (
        f"yaws.max()={yaws.max()} ≤ 2*pi — the radians regression is back."
    )
    # Mean should be ~180° for a uniform [0, 360) distribution.
    assert 150.0 < float(yaws.mean()) < 210.0, (
        f"yaws.mean()={yaws.mean()} not in [150, 210] — distribution looks "
        f"wrong for uniform [0, 360)."
    )


def test_bug2_environment_scatter_wind_yaw_is_degrees_after_conversion() -> None:
    """Round-2 verifier follow-up: ``environment_scatter._scatter_inner``
    (the canonical scatter producer used by ``handle_scatter_vegetation``)
    must convert the radians return value of ``_wind_rotation_y`` to
    degrees at the assignment site before it lands in
    ``tree_instance_points[:, 3]``.

    The verifier proved that PR #118 round-1 only fixed the
    ``terrain_assets._build_tree_instance_array`` producer (random yaw)
    but missed the CANONICAL scatter pipeline that writes wind-derived
    yaw. ``_wind_rotation_y`` returns RADIANS (pinned by
    test_environment_scatter_handlers.py:975 and its own docstring) so a
    naive assignment ``p["rotation_y"] = _wind_rotation_y(...)`` puts
    radians in [0, 2*pi] into a column the Unity exporter labels
    ``yaw_degrees`` → trees faced ~north.

    This test simulates the data flow at the assignment site:
    radians from _wind_rotation_y → conversion → column 3 of the
    (N, 5) tree_instance_points array → assertion that column 3 is
    in degrees ([0, 360)).
    """
    from veilbreakers_terrain.handlers.environment_scatter import (
        _wind_rotation_y,
        _write_tree_instance_points,
    )
    from types import SimpleNamespace

    # Build a non-trivial wind field with directional variation across
    # the grid so different (lx, ly) sample points yield different
    # radians values spanning a wide range.
    H = W = 8
    wind = np.zeros((H, W, 2), dtype=np.float32)
    # Quadrant-varying wind direction: NE, NW, SE, SW.
    wind[: H // 2, : W // 2, 0] = 1.0   # wx > 0
    wind[: H // 2, : W // 2, 1] = 1.0   # wy > 0 → atan2(1,1) =  pi/4
    wind[: H // 2, W // 2 :, 0] = -1.0
    wind[: H // 2, W // 2 :, 1] = 1.0   # atan2(-1,1) = -pi/4
    wind[H // 2 :, : W // 2, 0] = 1.0
    wind[H // 2 :, : W // 2, 1] = -1.0  # atan2(1,-1) =  3*pi/4
    wind[H // 2 :, W // 2 :, 0] = -1.0
    wind[H // 2 :, W // 2 :, 1] = -1.0  # atan2(-1,-1) = -3*pi/4

    terrain_w = terrain_h = 100.0
    # Sample 200 random placements across the terrain — enough to exercise
    # every quadrant and produce a wide spread of yaw values.
    rng = np.random.default_rng(42)
    sample_xy = rng.uniform(0.0, 100.0, size=(200, 2)).astype(np.float64)

    placements: List[Dict[str, Any]] = []
    for (lx, ly) in sample_xy:
        # Mirror the EXACT assignment site at environment_scatter.py:3462+:
        _wind_rot_rad = _wind_rotation_y(wind, float(lx), float(ly), terrain_w, terrain_h)
        _rot_deg = math.degrees(_wind_rot_rad) % 360.0
        placements.append({
            "vegetation_type": "tree",
            "base_type": "tree",
            "position": (float(lx), float(ly)),
            "world_position": (float(lx), float(ly), 0.0),
            "rotation_y": _rot_deg,
            "prototype_id": 0,
        })

    # Mirror the _tree_rows assembly at environment_scatter.py:3554-3577
    # exactly: float(p.get("rotation_y", 0.0)) into column 3.
    rows: List[Tuple[float, float, float, float, float]] = []
    for p in placements:
        wp = p["world_position"]
        rows.append((
            float(wp[0]),
            float(wp[1]),
            float(wp[2]),
            float(p.get("rotation_y", 0.0)),
            float(p.get("prototype_id", 0)),
        ))
    arr = np.array(rows, dtype=np.float32).reshape(-1, 5)

    # Stub stack to capture the write
    stack = SimpleNamespace(tree_instance_points=None)
    _write_tree_instance_points(arr, stack)
    assert stack.tree_instance_points is not None
    yaws = stack.tree_instance_points[:, 3]

    # Pre-fix (radians) max ≤ 2*pi ≈ 6.28. Post-fix degrees: max should
    # be well above 6.28 — for our wind field spanning all 4 quadrants
    # the values cluster around {45, 135, 225, 315} so we expect max
    # near 315.
    assert np.all(yaws >= 0.0), f"yaws must be >= 0; min={yaws.min()}"
    assert np.all(yaws < 360.0), (
        f"yaws must be in [0, 360) per Channel.YAW_DEG contract; "
        f"max={yaws.max()}"
    )
    assert yaws.max() > 90.0, (
        f"yaws.max()={yaws.max()} is suspiciously low — if max ≤ 2*pi ≈ "
        f"6.28 the conversion site is missing math.degrees() and the "
        f"forest will face ~north in Unity."
    )
    # Sanity: with 4-quadrant wind we expect spread across at least
    # 180° (we get 4 clusters at 45/135/225/315 so peak-to-peak ≈ 270°).
    assert yaws.max() - yaws.min() > 180.0, (
        f"yaws spread={yaws.max() - yaws.min()} < 180° — wind-field "
        f"yaw distribution is too tight; conversion or sampling broken."
    )


# ---------------------------------------------------------------------------
# Bug 3 — ADV-CP4-03: Kelvin wake per-rock local-flow gate
# ---------------------------------------------------------------------------


def test_bug3_stagnant_rock_in_fast_river_skips_wake() -> None:
    """A stagnant rock cell in a globally fast river must NOT emit a wake.

    Pre-fix: the global ``avg_speed = float(speed[water_mask].mean())`` gate
    used the river-wide mean. If the mean was > 1e-3 (typical for a fast
    river) every rock — including ones in stagnant pool cells — got a wake.
    Post-fix: per-rock local-flow sampling correctly skips the stagnant
    rock.
    """
    from veilbreakers_terrain.sim.foam import generate_foam_mask

    H = W = 32
    height = np.zeros((H, W), dtype=np.float32)
    water_mask = np.ones((H, W), dtype=bool)
    water_depth = np.full((H, W), 1.0, dtype=np.float32)
    rock_mask = np.zeros((H, W), dtype=bool)

    # Fast river everywhere EXCEPT a 5×5 stagnant pool around (16, 16).
    flow_speed = np.full((H, W), 5.0, dtype=np.float32)
    flow_speed[14:19, 14:19] = 0.0
    # Need flow_dir so the wake math has a direction; east-pointing.
    flow_dir = np.zeros((H, W, 2), dtype=np.float32)
    flow_dir[..., 0] = 1.0

    # Rock IN the stagnant pool centre.
    rock_positions = [(16.0, 16.0)]

    foam = generate_foam_mask(
        height=height,
        flow_speed=flow_speed,
        water_mask=water_mask,
        water_depth=water_depth,
        rock_mask=rock_mask,
        cell_size=1.0,
        flow_depth=0.3,
        rock_positions=rock_positions,
        flow_dir=flow_dir,
        noise_seed=42,
    )

    # The wake band is the ONLY foam source that responds to rock_positions.
    # The Kelvin contribution is multiplied by 0.10 and added to the rest.
    # If the per-rock guard fires the stagnant-cell rock contributes 0 to
    # kelvin_foam; if the global gate is still in play the rock emits a
    # wake band even though the local cell is stagnant.
    # Inspect a band ~3-15 cells EAST of the rock (along the flow direction,
    # within the wake cone but outside the rock cell itself).
    wake_band = foam[16, 19:30]
    # Subtract baseline foam (proximity + shore + froude + churn) from
    # the same band where the rock contribution should be zero. Easiest:
    # rerun with no rock_positions and diff.
    foam_no_rock = generate_foam_mask(
        height=height,
        flow_speed=flow_speed,
        water_mask=water_mask,
        water_depth=water_depth,
        rock_mask=rock_mask,
        cell_size=1.0,
        flow_depth=0.3,
        rock_positions=None,
        flow_dir=flow_dir,
        noise_seed=42,
    )
    rock_contribution = wake_band - foam_no_rock[16, 19:30]
    # Per-rock guard fires → rock_contribution should be ≈ 0 (gaussian
    # smoothing slightly bleeds but bound the magnitude).
    assert np.all(np.abs(rock_contribution) < 0.05), (
        f"Stagnant-pool rock in a fast river emitted a Kelvin wake "
        f"(max delta={float(np.abs(rock_contribution).max()):.4f}). "
        f"Per-rock local-flow gate failed; the prior global-mean gate is "
        f"back."
    )


def test_bug3_fast_rock_in_stagnant_pool_emits_wake() -> None:
    """A rock in a fast-flow CELL (within a globally stagnant pool) MUST
    emit a wake.

    Pre-fix global-mean gate: pool mean ≈ 0 → wake suppressed everywhere,
    including the fast cell. Post-fix per-rock gate: local cell has speed
    ≥ 1e-3 → wake emits.
    """
    from veilbreakers_terrain.sim.foam import generate_foam_mask

    H = W = 32
    height = np.zeros((H, W), dtype=np.float32)
    water_mask = np.ones((H, W), dtype=bool)
    water_depth = np.full((H, W), 1.0, dtype=np.float32)
    rock_mask = np.zeros((H, W), dtype=bool)

    # Stagnant pool everywhere except a 3×3 fast jet around (16, 16).
    flow_speed = np.zeros((H, W), dtype=np.float32)
    flow_speed[15:18, 15:18] = 5.0
    flow_dir = np.zeros((H, W, 2), dtype=np.float32)
    flow_dir[..., 0] = 1.0

    rock_positions = [(16.0, 16.0)]  # rock IN the fast jet cell

    foam = generate_foam_mask(
        height=height,
        flow_speed=flow_speed,
        water_mask=water_mask,
        water_depth=water_depth,
        rock_mask=rock_mask,
        cell_size=1.0,
        flow_depth=0.3,
        rock_positions=rock_positions,
        flow_dir=flow_dir,
        noise_seed=42,
    )
    foam_no_rock = generate_foam_mask(
        height=height,
        flow_speed=flow_speed,
        water_mask=water_mask,
        water_depth=water_depth,
        rock_mask=rock_mask,
        cell_size=1.0,
        flow_depth=0.3,
        rock_positions=None,
        flow_dir=flow_dir,
        noise_seed=42,
    )

    # Wake should appear east of the rock (along flow). Compare a few cells
    # within the wake cone.
    wake_band = foam[16, 19:25]
    no_rock_band = foam_no_rock[16, 19:25]
    rock_contribution = wake_band - no_rock_band
    assert float(rock_contribution.max()) > 0.005, (
        f"Fast-jet rock in stagnant pool emitted NO Kelvin wake "
        f"(max delta={float(rock_contribution.max()):.6f}). "
        f"Per-rock local-flow gate failed; the prior global-mean gate "
        f"silenced the wake."
    )


# ---------------------------------------------------------------------------
# Bug 4 — ADV-CP4-04: _mesh_bridge fills ALL material slots
# ---------------------------------------------------------------------------


def test_bug4_mesh_bridge_fills_all_material_slots() -> None:
    """When ``mesh_from_spec`` allocates ``num_slots`` placeholder slots
    via ``mesh_data.materials.append(None)``, every slot must be filled
    by the category-material auto-assign block — not just slot 0.

    Pre-fix the loop only wrote ``obj.data.materials[0] = mat``; slots
    [1..N-1] stayed ``None`` and any face with ``material_index >= 1``
    rendered as Blender's magenta debug material.

    Uses a stub bpy module so the test runs in CI without Blender.
    """
    import types
    from veilbreakers_terrain.handlers import _mesh_bridge

    # Build a minimal bpy stub so the Blender path executes.
    class _StubMaterials:
        def __init__(self) -> None:
            self._slots: List[Any] = []

        def append(self, mat: Any) -> None:
            self._slots.append(mat)

        def __iter__(self):
            return iter(self._slots)

        def __len__(self) -> int:
            return len(self._slots)

        def __getitem__(self, i: int) -> Any:
            return self._slots[i]

        def __setitem__(self, i: int, value: Any) -> None:
            self._slots[i] = value

        def __bool__(self) -> bool:
            return bool(self._slots)

    class _StubPoly:
        def __init__(self) -> None:
            self.material_index = 0
            self.use_smooth = False

    class _StubMesh:
        def __init__(self, name: str) -> None:
            self.name = name
            self.materials = _StubMaterials()
            self.polygons: List[_StubPoly] = []

        def update(self) -> None: pass

    class _StubObject:
        def __init__(self, name: str, data: _StubMesh) -> None:
            self.name = name
            self.data = data
            self.location = (0, 0, 0)
            self.rotation_euler = (0, 0, 0)
            self.scale = (1, 1, 1)
            self.parent = None

    class _StubMeshes:
        def new(self, name: str) -> _StubMesh:
            return _StubMesh(name)

    class _StubObjects:
        def new(self, name: str, data: _StubMesh) -> _StubObject:
            return _StubObject(name, data)

    class _StubCollection:
        def __init__(self) -> None:
            def _link(obj: Any) -> None:
                return None
            self.objects = types.SimpleNamespace(link=_link)

    class _StubContext:
        def __init__(self) -> None:
            self.collection = _StubCollection()

    class _StubBpyData:
        def __init__(self) -> None:
            self.meshes = _StubMeshes()
            self.objects = _StubObjects()

    class _StubBpy:
        def __init__(self) -> None:
            self.data = _StubBpyData()
            self.context = _StubContext()

    # Material-stub captures all slot writes for our assertion.
    captured_mats: List[Any] = []

    def _fake_create_procedural_material(name: str, mat_type: str) -> Any:
        m = types.SimpleNamespace(name=name, mat_type=mat_type)
        captured_mats.append(m)
        return m

    # Hard-patch into _mesh_bridge.
    import importlib
    mesh_bridge_module = importlib.reload(_mesh_bridge)

    # Stub bpy + bmesh inside the module.
    stub_bpy = _StubBpy()

    class _StubBMVert:
        def __init__(self, co: Tuple[float, float, float], index: int) -> None:
            self.co = co
            self.index = index
            self.normal = (0.0, 0.0, 1.0)

    class _StubBMFaces:
        def __init__(self) -> None:
            self._faces: List[Any] = []

        def new(self, verts: List[Any]) -> Any:
            f = types.SimpleNamespace(verts=verts, loops=[
                types.SimpleNamespace(vert=v, _uv=None) for v in verts
            ])
            for loop in f.loops:
                class _UV:
                    def __init__(self) -> None:
                        self.uv = (0.0, 0.0)
                loop._uv = _UV()
            self._faces.append(f)
            return f

        def ensure_lookup_table(self) -> None: pass

        def __iter__(self):
            return iter(self._faces)

        def __getitem__(self, key: Any) -> Any:
            if isinstance(key, slice):
                return self._faces[key]
            return self._faces[key]

    class _StubBMVerts:
        def __init__(self) -> None:
            self._verts: List[_StubBMVert] = []

        def new(self, co: Tuple[float, float, float]) -> _StubBMVert:
            v = _StubBMVert(co, len(self._verts))
            self._verts.append(v)
            return v

        def ensure_lookup_table(self) -> None: pass

    class _StubBMEdges:
        def __init__(self) -> None:
            self._edges: List[Any] = []

            def _get(key: Any) -> Any:
                return None

            def _new(key: Any) -> Any:
                return None

            self.layers = types.SimpleNamespace(
                float=types.SimpleNamespace(get=_get, new=_new)
            )

        def ensure_lookup_table(self) -> None: pass

        def __iter__(self):
            return iter(self._edges)

    class _StubBM:
        def __init__(self) -> None:
            self.verts = _StubBMVerts()
            self.faces = _StubBMFaces()
            self.edges = _StubBMEdges()

            def _new_uv(name: Any) -> Any:
                return None

            self.loops = types.SimpleNamespace(layers=types.SimpleNamespace(
                uv=types.SimpleNamespace(new=_new_uv)
            ))

        def to_mesh(self, mesh: _StubMesh) -> None:
            # Mirror the face count from our stub bm onto mesh.polygons.
            mesh.polygons = [_StubPoly() for _ in self.faces]

        def normal_update(self) -> None: pass

        def free(self) -> None: pass

    class _StubBmesh:
        @staticmethod
        def new() -> _StubBM:
            return _StubBM()

        class ops:
            @staticmethod
            def recalc_face_normals(bm: Any, faces: Any) -> None: pass

    with patch.object(mesh_bridge_module, "bpy", stub_bpy), \
         patch.object(mesh_bridge_module, "bmesh", _StubBmesh), \
         patch.object(mesh_bridge_module, "_HAS_BPY", True), \
         patch("veilbreakers_terrain.handlers.procedural_materials.create_procedural_material",
               _fake_create_procedural_material), \
         patch("veilbreakers_terrain.handlers.procedural_materials.MATERIAL_LIBRARY",
               {"rough_timber": {"node_recipe": {}}}):
        # 3-material spec: 4 faces with material_ids [0, 1, 2, 1]
        # → num_slots = max+1 = 3 → 3 slots get allocated as None.
        verts = [
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
        ]
        faces = [
            (0, 1, 2),
            (0, 2, 3),
            (4, 5, 6),
            (4, 6, 7),
        ]
        spec = {
            "vertices": verts,
            "faces": faces,
            "material_ids": [0, 1, 2, 1],
            "metadata": {"category": "furniture"},  # → "rough_timber"
        }

        obj = mesh_bridge_module.mesh_from_spec(spec, name="TestMultiMat")

        # The bug: only slot[0] would be the material; slots [1] and [2]
        # would still be None.
        assert len(obj.data.materials) == 3, (
            f"Expected 3 material slots (num_slots = max([0,1,2,1])+1=3); "
            f"got {len(obj.data.materials)}"
        )
        # Every slot must be the rough_timber material — no None slots.
        for i, slot in enumerate(obj.data.materials):
            assert slot is not None, (
                f"slot[{i}] is None — the PR #110 placeholder was never "
                f"filled. Faces with material_index={i} would render as "
                f"Blender's magenta debug material."
            )
        # All slots reference the same material (single-category spec).
        slot_names = {obj.data.materials[i].name for i in range(3)}
        assert len(slot_names) == 1, (
            f"All slots in a single-category spec must share one material "
            f"(name); got distinct names {slot_names}"
        )
