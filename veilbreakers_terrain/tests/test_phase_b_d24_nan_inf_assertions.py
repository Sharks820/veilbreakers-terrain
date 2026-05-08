"""Phase B D24 / PR #13 — NaN/Inf assertion tests.

Pins the runtime finiteness contract added in FIX-D24-PR13: every channel
declared in ``PassDefinition.produces_channels`` (and every channel
declared in ``overrides``) is checked for NaN / +Inf / -Inf at the end
of ``TerrainPassController.run_pass`` so numerical corruption is caught
at the producing pass instead of being smuggled downstream into water
depth / scatter / Unity heightmap export.

Three contract layers:

  1. ``terrain_io.assert_finite_array`` itself
     - Raises ``FiniteArrayError`` (subclass of ``ValueError``) on
       NaN/Inf with channel + pass attribution and a count breakdown.
     - Is a no-op for None inputs and for non-floating-point arrays
       (ints / bools cannot represent NaN/Inf).

  2. Pipeline integration
     - A poisoned pass that writes NaN into its declared
       ``produces_channels`` triggers ``FiniteArrayError`` inside
       ``run_pass``; the error propagates out so callers stop on the
       first bad pass instead of running 50 more passes on poison.
     - A pass that writes a clean float array passes through unchanged.
     - Integer channels do not trigger the check even with weird
       values (sanity — proves we don't over-fire on int dtypes).

  3. Source-level pin
     - ``terrain_pipeline.run_pass`` imports + calls
       ``assert_finite_array`` on produces_channels and overrides.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_io import (
    FiniteArrayError,
    assert_finite_array,
)


# ---------------------------------------------------------------------------
# Layer 1 — assert_finite_array contract
# ---------------------------------------------------------------------------


class TestAssertFiniteArrayContract:

    def test_clean_float_array_passes(self) -> None:
        arr = np.linspace(0.0, 100.0, 256, dtype=np.float32).reshape(16, 16)
        # Should not raise.
        assert_finite_array(arr, channel="height", pass_name="pass_test")

    def test_nan_raises_finite_array_error(self) -> None:
        arr = np.zeros((4, 4), dtype=np.float32)
        arr[1, 1] = np.nan
        with pytest.raises(FiniteArrayError) as excinfo:
            assert_finite_array(arr, channel="height", pass_name="pass_poison")
        err = excinfo.value
        assert err.channel == "height"
        assert err.pass_name == "pass_poison"
        assert err.nan_count == 1
        assert err.posinf_count == 0
        assert err.neginf_count == 0
        # Message attribution
        msg = str(err)
        assert "'height'" in msg
        assert "'pass_poison'" in msg
        assert "1 NaN" in msg

    def test_posinf_raises_with_correct_count(self) -> None:
        arr = np.zeros((4, 4), dtype=np.float64)
        arr[0, 0] = np.inf
        arr[3, 3] = np.inf
        with pytest.raises(FiniteArrayError) as excinfo:
            assert_finite_array(arr, channel="erosion_amount", pass_name="pass_erosion")
        err = excinfo.value
        assert err.posinf_count == 2
        assert err.nan_count == 0

    def test_neginf_raises_with_correct_count(self) -> None:
        arr = np.zeros((4, 4), dtype=np.float64)
        arr[0, 0] = -np.inf
        with pytest.raises(FiniteArrayError) as excinfo:
            assert_finite_array(
                arr, channel="hydraulic_potential", pass_name="pass_water"
            )
        err = excinfo.value
        assert err.neginf_count == 1
        assert err.posinf_count == 0
        assert err.nan_count == 0

    def test_mixed_corruption_counts_each_class(self) -> None:
        arr = np.zeros((10, 10), dtype=np.float32)
        arr[0, 0] = np.nan
        arr[1, 0] = np.nan
        arr[2, 0] = np.inf
        arr[3, 0] = -np.inf
        arr[4, 0] = -np.inf
        with pytest.raises(FiniteArrayError) as excinfo:
            assert_finite_array(arr, channel="x", pass_name="p")
        err = excinfo.value
        assert err.nan_count == 2
        assert err.posinf_count == 1
        assert err.neginf_count == 2

    def test_int_array_is_skipped(self) -> None:
        # Integer arrays cannot represent NaN/Inf; no check applies.
        arr = np.full((4, 4), -1, dtype=np.int32)
        # Should not raise even with sentinel values.
        assert_finite_array(arr, channel="navmesh_area_id", pass_name="pass_test")

    def test_bool_array_is_skipped(self) -> None:
        arr = np.zeros((4, 4), dtype=bool)
        assert_finite_array(arr, channel="cliff_mask", pass_name="pass_test")

    def test_none_is_skipped(self) -> None:
        # No channel populated yet — no-op.
        assert_finite_array(None, channel="x", pass_name="p")

    def test_finite_array_error_is_value_error_subclass(self) -> None:
        """Subclassing ValueError keeps existing handlers working."""
        assert issubclass(FiniteArrayError, ValueError)

    def test_message_includes_shape_and_dtype(self) -> None:
        arr = np.full((3, 5), np.nan, dtype=np.float32)
        with pytest.raises(FiniteArrayError) as excinfo:
            assert_finite_array(arr, channel="ch", pass_name="p")
        msg = str(excinfo.value)
        assert "(3, 5)" in msg
        assert "float32" in msg


# ---------------------------------------------------------------------------
# Layer 2 — pipeline integration
# ---------------------------------------------------------------------------


def _make_pipeline_state(tile_size: int = 8):
    """Return a minimal TerrainPipelineState wrapping a clean mask stack."""
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    rng = np.random.default_rng(123)
    height = rng.uniform(0.0, 100.0, (tile_size, tile_size)).astype(np.float32)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    region_bounds = BBox(0.0, 0.0, float(tile_size), float(tile_size))
    intent = TerrainIntentState(
        seed=42,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


class TestPipelineIntegration:
    """A pass that writes NaN to produces_channels must raise inside run_pass."""

    def setup_method(self) -> None:
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

        TerrainPassController.clear_registry()

    def teardown_method(self) -> None:
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

        TerrainPassController.clear_registry()

    def test_poisoned_pass_raises_finite_array_error(self) -> None:
        """A pass writing NaN into ``slope`` must trip the assertion."""
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        from veilbreakers_terrain.handlers.terrain_semantics import (
            PassDefinition,
            PassResult,
        )

        def _poison(state, region):  # type: ignore[no-untyped-def]
            stack = state.mask_stack
            poisoned = np.zeros(stack.height.shape, dtype=np.float32)
            poisoned[0, 0] = np.nan
            poisoned[1, 1] = np.inf
            stack.set("slope", poisoned, "pass_poison")
            return PassResult(
                pass_name="pass_poison",
                status="ok",
                duration_seconds=0.001,
                metrics={},
                seed_used=0,
            )

        TerrainPassController.register_pass(
            PassDefinition(
                name="pass_poison",
                func=_poison,
                requires_channels=(),
                produces_channels=("slope",),
                seed_namespace="",
            )
        )

        state = _make_pipeline_state()
        controller = TerrainPassController(state)

        with pytest.raises(FiniteArrayError) as excinfo:
            controller.run_pass("pass_poison", checkpoint=False)

        err = excinfo.value
        assert err.channel == "slope"
        assert err.pass_name == "pass_poison"
        assert err.nan_count == 1
        assert err.posinf_count == 1

    def test_clean_pass_passes_through(self) -> None:
        """A pass writing only finite floats must run cleanly to completion."""
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        from veilbreakers_terrain.handlers.terrain_semantics import (
            PassDefinition,
            PassResult,
        )

        def _clean(state, region):  # type: ignore[no-untyped-def]
            stack = state.mask_stack
            arr = np.linspace(0.0, 1.0, stack.height.size, dtype=np.float32).reshape(
                stack.height.shape
            )
            stack.set("slope", arr, "pass_clean")
            return PassResult(
                pass_name="pass_clean",
                status="ok",
                duration_seconds=0.001,
                metrics={},
                seed_used=0,
            )

        TerrainPassController.register_pass(
            PassDefinition(
                name="pass_clean",
                func=_clean,
                requires_channels=(),
                produces_channels=("slope",),
                seed_namespace="",
            )
        )

        state = _make_pipeline_state()
        controller = TerrainPassController(state)

        result = controller.run_pass("pass_clean", checkpoint=False)
        assert result.status == "ok"
        # And the channel really is finite on the stack:
        slope = controller.state.mask_stack.get("slope")
        assert slope is not None
        assert np.all(np.isfinite(np.asarray(slope)))

    def test_int_produces_channel_skipped(self) -> None:
        """Integer-dtype channel writes are NOT checked (cannot carry NaN/Inf).

        Sanity — proves the assertion doesn't fire spuriously on int channels
        such as ``navmesh_area_id`` or ``biome_id``.
        """
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        from veilbreakers_terrain.handlers.terrain_semantics import (
            PassDefinition,
            PassResult,
        )

        def _int_writer(state, region):  # type: ignore[no-untyped-def]
            stack = state.mask_stack
            # navmesh_area_id channel is constrained to dtype kind 'u'
            # (unsigned int) by terrain_semantics; uint8 matches Recast's
            # area-id encoding.
            arr = np.full(stack.height.shape, 5, dtype=np.uint8)
            stack.set("navmesh_area_id", arr, "pass_int")
            return PassResult(
                pass_name="pass_int",
                status="ok",
                duration_seconds=0.001,
                metrics={},
                seed_used=0,
            )

        TerrainPassController.register_pass(
            PassDefinition(
                name="pass_int",
                func=_int_writer,
                requires_channels=(),
                produces_channels=("navmesh_area_id",),
                seed_namespace="",
            )
        )

        state = _make_pipeline_state()
        controller = TerrainPassController(state)

        # Should not raise.
        result = controller.run_pass("pass_int", checkpoint=False)
        assert result.status == "ok"

    def test_failed_pass_skips_finite_check(self) -> None:
        """A pass returning status='failed' must not be checked.

        Failed passes have rolled back and their channels may be in any
        state; the assertion only applies to the success contract.
        """
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        from veilbreakers_terrain.handlers.terrain_semantics import (
            PassDefinition,
            PassResult,
        )

        def _failer(state, region):  # type: ignore[no-untyped-def]
            # Note: even a failed pass might leave half-written channels.
            # The assertion must NOT fire on status="failed".
            return PassResult(
                pass_name="pass_failer",
                status="failed",
                duration_seconds=0.001,
                metrics={"error": "intentional"},
                seed_used=0,
            )

        TerrainPassController.register_pass(
            PassDefinition(
                name="pass_failer",
                func=_failer,
                requires_channels=(),
                produces_channels=(),  # no produces_channels → trivially clean
                seed_namespace="",
            )
        )

        state = _make_pipeline_state()
        controller = TerrainPassController(state)
        result = controller.run_pass("pass_failer", checkpoint=False)
        assert result.status == "failed"

    def test_overrides_channel_also_checked(self) -> None:
        """Channels in ``overrides`` (secondary writers) are checked too.

        Some passes write the same channel as a primary author plus an
        override; the assertion must catch NaN smuggled through the
        override path as well.
        """
        from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
        from veilbreakers_terrain.handlers.terrain_semantics import (
            PassDefinition,
            PassResult,
        )

        # Pre-populate the channel so the override is legitimate.
        state = _make_pipeline_state()
        clean = np.zeros(state.mask_stack.height.shape, dtype=np.float32)
        state.mask_stack.set("slope", clean, "primary_writer")

        def _override_with_nan(state, region):  # type: ignore[no-untyped-def]
            stack = state.mask_stack
            arr = np.zeros(stack.height.shape, dtype=np.float32)
            arr[0, 0] = np.nan
            stack.set("slope", arr, "pass_override")
            return PassResult(
                pass_name="pass_override",
                status="ok",
                duration_seconds=0.001,
                metrics={},
                seed_used=0,
            )

        TerrainPassController.register_pass(
            PassDefinition(
                name="pass_override",
                func=_override_with_nan,
                requires_channels=(),
                produces_channels=(),
                overrides=("slope",),
                seed_namespace="",
            )
        )

        controller = TerrainPassController(state)
        with pytest.raises(FiniteArrayError) as excinfo:
            controller.run_pass("pass_override", checkpoint=False)
        assert excinfo.value.channel == "slope"
        assert excinfo.value.pass_name == "pass_override"


# ---------------------------------------------------------------------------
# Layer 3 — source-level pin
# ---------------------------------------------------------------------------


class TestSourcePin:
    """Defensive: re-rolls of run_pass can't accidentally drop the assertion."""

    def test_run_pass_imports_assert_finite_array(self) -> None:
        from veilbreakers_terrain.handlers import terrain_pipeline

        src = inspect.getsource(terrain_pipeline)
        # Pyright strict-mode forbids unused imports, so the pipeline only
        # imports the symbol it actually calls. ``FiniteArrayError`` lives
        # in terrain_io and is consumed by tests / downstream catchers.
        assert "from .terrain_io import assert_finite_array" in src, (
            "terrain_pipeline must import assert_finite_array from terrain_io "
            "(FIX-D24-PR13 regression)"
        )

    def test_run_pass_calls_assert_finite_array(self) -> None:
        from veilbreakers_terrain.handlers import terrain_pipeline

        src = inspect.getsource(terrain_pipeline.TerrainPassController.run_pass)
        # Must call the helper inside run_pass.
        assert "assert_finite_array(" in src, (
            "run_pass must call assert_finite_array on produces_channels "
            "(FIX-D24-PR13 regression)"
        )
        # Must iterate over produces_channels.
        assert "definition.produces_channels" in src
        # Must also iterate over overrides for secondary writers.
        assert "definition.overrides" in src
