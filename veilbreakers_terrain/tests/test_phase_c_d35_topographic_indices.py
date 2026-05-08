"""Phase C D35 / GATE D35 — pass_topographic_indices regression tests.

Per docs/IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md §17 Phase C D35:
``pass_topographic_indices`` produces all four spec channels and the
foliage-stack consumer wiring is complete.

GATE D35 = every test in this module passes.

Pinned invariants:
    1. ``produces_channels`` declares all 4 of vb_aspect_deg /
       vb_aspect_north / vb_canopy_openness / vb_TWI.
    2. Output shape == input heightmap shape.
    3. Output dtype == float32 for every channel.
    4. vb_aspect_deg in [0, 360).
    5. vb_aspect_north in [-1, +1].
    6. vb_canopy_openness in [0, 1].
    7. vb_TWI is finite (no NaN / +Inf / -Inf) for non-flat input —
       checked via ``terrain_io.assert_finite_array``.
    8. Determinism — running the pass twice on identical input yields
       byte-identical output for all 4 channels.
    9. Foliage-catalog / scatter consumer passes declare the new channels
       in their ``optional_channels`` (or ``requires_channels``) set.
"""

from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_io import (
    FiniteArrayError,
    assert_finite_array,
)
from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
)
from veilbreakers_terrain.handlers.terrain_topographic_indices import (
    pass_topographic_indices,
    register_topographic_indices_pass,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_TILE_SIZE: int = 32


def _build_heightmap(seed: int = 1234) -> np.ndarray:
    """Return a deterministic non-flat heightmap of shape (33, 33)."""
    rng = np.random.RandomState(seed)
    rows, cols = _TILE_SIZE + 1, _TILE_SIZE + 1
    yy, xx = np.mgrid[0:rows, 0:cols].astype(np.float32)
    # Sloped + sinusoidal + small noise: produces meaningful aspect/slope/TWI.
    h = (
        0.3 * yy
        + 5.0 * np.sin(xx * 0.4)
        + 4.0 * np.cos(yy * 0.3)
        + 0.5 * rng.standard_normal(yy.shape).astype(np.float32)
    )
    return np.ascontiguousarray(h.astype(np.float32))


def _build_state(height: np.ndarray) -> TerrainPipelineState:
    rows, cols = height.shape
    cell = 1.0
    region_bounds = BBox(0.0, 0.0, float(cols - 1) * cell, float(rows - 1) * cell)
    stack = TerrainMaskStack(
        tile_size=_TILE_SIZE,
        cell_size=cell,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    intent = TerrainIntentState(
        seed=42,
        region_bounds=region_bounds,
        tile_size=_TILE_SIZE,
        cell_size=cell,
        quality_profile="aaa_open_world",
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


@pytest.fixture(autouse=True)
def _registry_isolation():  # pyright: ignore[reportUnusedFunction]
    """Snapshot/restore the pass registry around each test for hygiene."""
    snapshot = dict(TerrainPassController.PASS_REGISTRY)
    try:
        yield
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(snapshot)


# ---------------------------------------------------------------------------
# 1 — produces_channels declares all 4 channels
# ---------------------------------------------------------------------------


def test_pass_definition_declares_all_4_produced_channels() -> None:
    """The PassDefinition must declare all 4 spec channels in produces_channels."""
    TerrainPassController.PASS_REGISTRY.pop("topographic_indices", None)
    register_topographic_indices_pass()
    defn = TerrainPassController.get_pass("topographic_indices")
    assert set(defn.produces_channels) == {
        "vb_aspect_deg",
        "vb_aspect_north",
        "vb_canopy_openness",
        "vb_TWI",
    }, (
        f"produces_channels mismatch: {defn.produces_channels!r}; "
        f"expected exactly the 4 D35 spec channels."
    )


def test_pass_definition_requires_height() -> None:
    """The PassDefinition must declare height as a hard requirement."""
    TerrainPassController.PASS_REGISTRY.pop("topographic_indices", None)
    register_topographic_indices_pass()
    defn = TerrainPassController.get_pass("topographic_indices")
    assert "height" in defn.requires_channels, (
        f"requires_channels must contain 'height'; got {defn.requires_channels!r}"
    )


# ---------------------------------------------------------------------------
# 2-3 — Shape and dtype contracts
# ---------------------------------------------------------------------------


def test_output_shape_matches_input_heightmap() -> None:
    """All 4 output channels must have the same (H, W) as the input heightmap."""
    height = _build_heightmap()
    state = _build_state(height)
    pass_topographic_indices(state, None)
    stack = state.mask_stack
    for ch in ("vb_aspect_deg", "vb_aspect_north", "vb_canopy_openness", "vb_TWI"):
        arr = stack.get(ch)
        assert arr is not None, f"channel {ch!r} not written"
        assert arr.shape == height.shape, (
            f"channel {ch!r} shape {arr.shape} != heightmap shape {height.shape}"
        )


def test_output_dtype_is_float32() -> None:
    """All 4 output channels must be float32."""
    height = _build_heightmap()
    state = _build_state(height)
    pass_topographic_indices(state, None)
    stack = state.mask_stack
    for ch in ("vb_aspect_deg", "vb_aspect_north", "vb_canopy_openness", "vb_TWI"):
        arr = stack.get(ch)
        assert arr.dtype == np.float32, (
            f"channel {ch!r} dtype {arr.dtype} != float32"
        )


# ---------------------------------------------------------------------------
# 4-6 — Range invariants
# ---------------------------------------------------------------------------


def test_vb_aspect_deg_in_0_360_range() -> None:
    """vb_aspect_deg must lie in [0, 360)."""
    height = _build_heightmap()
    state = _build_state(height)
    pass_topographic_indices(state, None)
    arr = state.mask_stack.get("vb_aspect_deg")
    assert float(arr.min()) >= 0.0, f"aspect_deg min {float(arr.min())} < 0"
    assert float(arr.max()) < 360.0, f"aspect_deg max {float(arr.max())} >= 360"


def test_vb_aspect_north_in_neg1_pos1_range() -> None:
    """vb_aspect_north must lie in [-1, +1]."""
    height = _build_heightmap()
    state = _build_state(height)
    pass_topographic_indices(state, None)
    arr = state.mask_stack.get("vb_aspect_north")
    assert float(arr.min()) >= -1.0, f"aspect_north min {float(arr.min())} < -1"
    assert float(arr.max()) <= 1.0, f"aspect_north max {float(arr.max())} > +1"


def test_vb_canopy_openness_in_0_1_range() -> None:
    """vb_canopy_openness must lie in [0, 1]."""
    height = _build_heightmap()
    state = _build_state(height)
    pass_topographic_indices(state, None)
    arr = state.mask_stack.get("vb_canopy_openness")
    assert float(arr.min()) >= 0.0, f"canopy_openness min {float(arr.min())} < 0"
    assert float(arr.max()) <= 1.0, f"canopy_openness max {float(arr.max())} > 1"


# ---------------------------------------------------------------------------
# 7 — Finiteness for non-flat inputs
# ---------------------------------------------------------------------------


def test_vb_TWI_is_finite_for_nonflat_input() -> None:
    """vb_TWI must be finite (no NaN/Inf) on non-flat heightmaps."""
    height = _build_heightmap()
    state = _build_state(height)
    pass_topographic_indices(state, None)
    arr = state.mask_stack.get("vb_TWI")
    # Use the canonical assertion from terrain_io — raises FiniteArrayError
    # on any NaN or +/-Inf with channel + pass attribution.
    assert_finite_array(arr, channel="vb_TWI", pass_name="topographic_indices")


def test_all_4_channels_are_finite_for_nonflat_input() -> None:
    """Same finiteness check for the other three channels."""
    height = _build_heightmap()
    state = _build_state(height)
    pass_topographic_indices(state, None)
    stack = state.mask_stack
    for ch in ("vb_aspect_deg", "vb_aspect_north", "vb_canopy_openness", "vb_TWI"):
        arr = stack.get(ch)
        assert_finite_array(arr, channel=ch, pass_name="topographic_indices")


# ---------------------------------------------------------------------------
# 8 — Determinism (byte-identical output on re-run)
# ---------------------------------------------------------------------------


def test_byte_identical_output_on_repeat_run() -> None:
    """Running the pass twice on identical input must produce byte-identical channels."""
    height = _build_heightmap()
    state_a = _build_state(height.copy())
    state_b = _build_state(height.copy())
    pass_topographic_indices(state_a, None)
    pass_topographic_indices(state_b, None)
    for ch in ("vb_aspect_deg", "vb_aspect_north", "vb_canopy_openness", "vb_TWI"):
        a = state_a.mask_stack.get(ch)
        b = state_b.mask_stack.get(ch)
        # Byte-identical: convert to bytes and compare. np.array_equal is
        # NaN-unsafe; tobytes is exact.
        assert a.tobytes() == b.tobytes(), (
            f"channel {ch!r} not byte-identical across two runs"
        )


# ---------------------------------------------------------------------------
# 9 — Foliage / scatter consumers declare the new channels
# ---------------------------------------------------------------------------


def _registered_consumer_definitions() -> "dict[str, PassDefinition]":
    """Register topo + every consumer pass and return their PassDefinitions."""
    TerrainPassController.PASS_REGISTRY.clear()
    register_topographic_indices_pass()
    # Foliage / scatter consumer passes — register each via its public registrar.
    from veilbreakers_terrain.handlers.terrain_assets import (
        register_bundle_e_passes,
    )
    from veilbreakers_terrain.handlers.procedural_grass import (
        register_procedural_grass_pass,
    )
    from veilbreakers_terrain.handlers.terrain_vegetation_depth import (
        register_vegetation_depth_pass,
    )
    register_bundle_e_passes()
    register_procedural_grass_pass()
    register_vegetation_depth_pass()
    return {
        name: TerrainPassController.PASS_REGISTRY[name]
        for name in (
            "scatter_intelligent",
            "pass_procedural_grass",
            "vegetation_depth",
        )
    }


@pytest.mark.parametrize(
    "consumer_pass_name",
    ["scatter_intelligent", "pass_procedural_grass", "vegetation_depth"],
)
def test_foliage_consumer_declares_new_channels(consumer_pass_name: str) -> None:
    """Every foliage-stack consumer must declare the 4 D35 channels.

    The channels can appear in either ``requires_channels`` (hard) or
    ``optional_channels`` (soft) — the spec only mandates declaration so
    the DAG knows to schedule the producer first when the consumer runs.
    """
    consumers = _registered_consumer_definitions()
    defn = consumers[consumer_pass_name]
    declared = set(defn.requires_channels) | set(defn.optional_channels) | set(
        getattr(defn, "requires_channels_optional", ()) or ()
    )
    expected = {
        "vb_aspect_deg",
        "vb_aspect_north",
        "vb_canopy_openness",
        "vb_TWI",
    }
    missing = expected - declared
    assert not missing, (
        f"Consumer pass {consumer_pass_name!r} does not declare D35 channels "
        f"{sorted(missing)} in requires_channels / optional_channels. "
        f"Declared set = {sorted(declared)!r}."
    )


# ---------------------------------------------------------------------------
# Bonus — pass returns ok PassResult with all 4 channels in produced_channels
# ---------------------------------------------------------------------------


def test_pass_result_reports_all_4_produced_channels() -> None:
    """The returned PassResult must list all 4 D35 channels in produced_channels."""
    height = _build_heightmap()
    state = _build_state(height)
    result = pass_topographic_indices(state, None)
    assert isinstance(result, PassResult)
    assert result.status == "ok"
    assert set(result.produced_channels) == {
        "vb_aspect_deg",
        "vb_aspect_north",
        "vb_canopy_openness",
        "vb_TWI",
    }


# ---------------------------------------------------------------------------
# Sanity — assert_finite_array imported from canonical location
# ---------------------------------------------------------------------------


def test_finite_array_error_is_value_error_subclass() -> None:
    """Smoke check: FiniteArrayError remains a ValueError subclass."""
    assert issubclass(FiniteArrayError, ValueError)


# ---------------------------------------------------------------------------
# Direct helper-function behavior tests (matrix verification: HIGH -> LOW)
# ---------------------------------------------------------------------------


def test_compute_slope_aspect_helper_returns_radians_for_simple_ramp() -> None:
    """``_compute_slope_aspect`` must return slope and aspect in radians for a known ramp.

    Direct unit test for the private helper so the verification matrix
    detects ``direct_test`` evidence on ``_compute_slope_aspect`` and drops
    its verification risk from HIGH to LOW.
    """
    from veilbreakers_terrain.handlers.terrain_topographic_indices import (
        _compute_slope_aspect,
    )

    # 5x5 ramp going up to the south (rows increase going south in our convention).
    rows, cols = 5, 5
    height = np.tile(np.arange(rows, dtype=np.float32).reshape(-1, 1), (1, cols))
    slope_rad, aspect_rad = _compute_slope_aspect(height, cell_size_m=1.0)

    assert slope_rad.shape == height.shape
    assert aspect_rad.shape == height.shape
    assert slope_rad.dtype == np.float32
    assert aspect_rad.dtype == np.float32
    # Slope of a 1-unit-per-1-cell ramp is atan(1) = pi/4 in the interior.
    assert np.isclose(float(slope_rad[2, 2]), float(np.arctan(1.0)), atol=1e-5)
    # Aspect of a uphill-to-south slope: downhill faces north (compass 0).
    # arctan2(0, +1) = 0 radians (north).
    assert np.isclose(float(aspect_rad[2, 2]), 0.0, atol=1e-5)


def test_compute_canopy_openness_helper_returns_full_sky_for_flat_input() -> None:
    """``_compute_canopy_openness`` must return ~1.0 everywhere on a perfectly flat heightmap.

    Direct unit test for the private helper so the verification matrix
    detects ``direct_test`` evidence on ``_compute_canopy_openness`` and
    drops its verification risk from HIGH to LOW.
    """
    from veilbreakers_terrain.handlers.terrain_topographic_indices import (
        _compute_canopy_openness,
    )

    flat = np.zeros((16, 16), dtype=np.float32)
    openness = _compute_canopy_openness(flat, cell_size_m=1.0)

    assert openness.shape == flat.shape
    assert openness.dtype == np.float32
    assert float(openness.min()) >= 0.0
    assert float(openness.max()) <= 1.0
    # Flat ground -> every horizon-elevation angle is 0 -> sin(0)=0 -> openness=1.
    assert np.isclose(float(openness.mean()), 1.0, atol=1e-3)


def test_compute_twi_helper_returns_finite_floats_with_explicit_flow_acc() -> None:
    """``_compute_twi`` must return a finite float32 array sized like the heightmap.

    Direct unit test for the private helper so the verification matrix
    detects ``direct_test`` evidence on ``_compute_twi`` and drops its
    verification risk from HIGH to LOW.
    """
    from veilbreakers_terrain.handlers.terrain_topographic_indices import (
        _compute_twi,
    )

    height = _build_heightmap(seed=4321)
    rng = np.random.RandomState(99)
    flow_acc = rng.uniform(1.0, 100.0, size=height.shape).astype(np.float32)
    slope_rad = np.full(height.shape, np.float32(0.1))  # ~5.7 deg

    twi = _compute_twi(
        height=height,
        slope_rad=slope_rad,
        flow_accumulation=flow_acc,
        cell_size_m=1.0,
    )

    assert twi.shape == height.shape
    assert twi.dtype == np.float32
    assert np.isfinite(twi).all(), "TWI must be finite for valid inputs"
    # Sanity: TWI = ln(area / tan(slope)). With area in [1, 100] and tan(0.1)=0.1003,
    # the bounds become roughly ln(10/0.1) ~ 4.6 to ln(1000/0.1) ~ 9.2 in raw units.
    assert float(twi.min()) > 0.0
    assert float(twi.max()) < 20.0


def test_compute_twi_helper_falls_back_when_flow_accumulation_absent() -> None:
    """``_compute_twi`` must fall back to a height-rank approximation when
    ``flow_accumulation`` is None, and still produce finite float32 output."""
    from veilbreakers_terrain.handlers.terrain_topographic_indices import (
        _compute_twi,
    )

    height = _build_heightmap(seed=11)
    slope_rad = np.full(height.shape, np.float32(0.05))

    twi = _compute_twi(
        height=height,
        slope_rad=slope_rad,
        flow_accumulation=None,
        cell_size_m=1.0,
    )

    assert twi.shape == height.shape
    assert twi.dtype == np.float32
    assert np.isfinite(twi).all()
