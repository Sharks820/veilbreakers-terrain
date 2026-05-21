"""T0-8 regression — deepcopy 4-site content-hash split + lightweight state copy.

Y04 v2-ord 10 / Tier-0 (HW unlock 24-28 GB peak → <500 MB peak).

Pin BEFORE fix: 4 ``copy.deepcopy()`` calls inside ``TerrainPassController``:
  * :1337 mask_stack baseline (P0-RT-03a)
  * :1353 Bundle-N full state (P0-RT-03d)
  * :1535/1536 _save_checkpoint water_network + viewport_vantage (P0-RT-03b)
  * :1598/1599 rollback_to water_network + viewport_vantage (P0-RT-03c)

Pin AFTER fix: zero ``copy.deepcopy(...)`` in those leak ranges.  Replaced
with:
  * content-hash + on-disk snapshot (``_snapshot_mask_stack_to_disk`` /
    ``_load_baseline_snapshot``) for the mask_stack baseline,
  * ``_lightweight_state_copy`` from ``terrain_pass_dag.py`` for Bundle-N,
  * ``_lightweight_water_network_copy`` for the small metadata snapshots.

Outermost ``finally`` block in ``run_pipeline`` unlinks the temp snapshot,
drops every baseline attribute, and calls ``gc.collect()`` so 50× soak
loops no longer monotonically grow.

Determinism preserved: same byte-for-byte content_hash before/after.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# AST pinning tests — fast, deterministic, no Blender / numpy fixtures
# ---------------------------------------------------------------------------

_PIPELINE_SRC = Path(
    "veilbreakers_terrain/handlers/terrain_pipeline.py"
).read_text(encoding="utf-8")
_VALIDATION_SRC = Path(
    "veilbreakers_terrain/handlers/terrain_validation.py"
).read_text(encoding="utf-8")
_PIPELINE_TREE = ast.parse(_PIPELINE_SRC)


def test_no_deepcopy_in_run_pipeline_or_save_checkpoint_or_rollback() -> None:
    """The 4 historic T0-8 leak call sites must no longer call copy.deepcopy.

    We walk each function body individually so the test is robust to line
    shifts from future refactors — what matters is the *function*, not the
    physical line number.
    """
    offenders: dict[str, list[int]] = {}
    for node in ast.walk(_PIPELINE_TREE):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in {"run_pipeline", "_save_checkpoint", "rollback_to"}:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "deepcopy"
                and isinstance(func.value, ast.Name)
                and func.value.id == "copy"
            ):
                offenders.setdefault(node.name, []).append(sub.lineno)
    assert not offenders, (
        f"copy.deepcopy still present in T0-8 leak sites: {offenders}. "
        "Use _snapshot_mask_stack_to_disk / _lightweight_state_copy / "
        "_lightweight_water_network_copy instead."
    )


def test_t0_8_helpers_defined() -> None:
    """The three new T0-8 helpers must be module-level callables."""
    module_defs = {
        node.name
        for node in _PIPELINE_TREE.body
        if isinstance(node, ast.FunctionDef)
    }
    for required in (
        "_snapshot_mask_stack_to_disk",
        "_load_baseline_snapshot",
        "_lightweight_water_network_copy",
    ):
        assert required in module_defs, (
            f"T0-8 helper missing from terrain_pipeline.py: {required}"
        )


def test_run_pipeline_uses_snapshot_helper() -> None:
    """run_pipeline must invoke _snapshot_mask_stack_to_disk + record hash."""
    body = ""
    for node in ast.walk(_PIPELINE_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "run_pipeline":
            body = ast.unparse(node)
            break
    assert body, "run_pipeline FunctionDef not found"
    assert "_snapshot_mask_stack_to_disk" in body, (
        "run_pipeline must call _snapshot_mask_stack_to_disk for the baseline"
    )
    assert "_pre_pipeline_baseline_hash" in body, (
        "run_pipeline must store _pre_pipeline_baseline_hash"
    )
    assert "_pre_pipeline_baseline_snapshot_path" in body, (
        "run_pipeline must store _pre_pipeline_baseline_snapshot_path"
    )


def test_bundle_n_path_uses_lightweight_state_copy() -> None:
    """Bundle-N determinism path must use _lightweight_state_copy."""
    body = ""
    for node in ast.walk(_PIPELINE_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "run_pipeline":
            body = ast.unparse(node)
            break
    assert "_lightweight_state_copy" in body, (
        "Bundle-N path must use _lightweight_state_copy from terrain_pass_dag.py"
    )


def test_save_checkpoint_and_rollback_use_lightweight_water_network_copy() -> None:
    """_save_checkpoint and rollback_to must use the lightweight helper."""
    for fname in ("_save_checkpoint", "rollback_to"):
        body = ""
        for node in ast.walk(_PIPELINE_TREE):
            if isinstance(node, ast.FunctionDef) and node.name == fname:
                body = ast.unparse(node)
                break
        assert body, f"{fname} FunctionDef not found"
        assert "_lightweight_water_network_copy" in body, (
            f"{fname} must use _lightweight_water_network_copy"
        )


def test_finally_cleanup_present_in_run_pipeline() -> None:
    """run_pipeline must del baseline attrs + gc.collect() in a finally."""
    body = ""
    for node in ast.walk(_PIPELINE_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "run_pipeline":
            body = ast.unparse(node)
            break
    assert "gc.collect" in body, "run_pipeline must call gc.collect() on cleanup"
    assert "_pre_pipeline_baseline_snapshot_path" in body, "cleanup must mention snapshot path"
    # delattr or del-statement on _pre_pipeline_baseline_*
    assert (
        "delattr(self, attr)" in body
        or "del self._pre_pipeline_baseline" in body
    ), "cleanup must drop _pre_pipeline_baseline_* attrs"
    assert ".unlink(missing_ok=True)" in body, (
        "cleanup must unlink the on-disk baseline snapshot (missing_ok=True)"
    )


def test_terrain_validation_uses_loader_helper() -> None:
    """pass_validation_full must call the controller's _load_pre_pipeline_baseline_stack."""
    assert "_load_pre_pipeline_baseline_stack" in _VALIDATION_SRC, (
        "terrain_validation.py must hydrate the baseline via the lazy loader"
    )
    # Backwards-compat fallback to the old eager attribute still allowed but
    # must NOT be the ONLY accessor.
    assert "_load_pre_pipeline_baseline_stack" in _VALIDATION_SRC


def test_gc_module_imported_in_pipeline() -> None:
    """terrain_pipeline.py must import gc at module top."""
    found_gc_import = False
    for node in _PIPELINE_TREE.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "gc":
                    found_gc_import = True
        if isinstance(node, ast.ImportFrom) and node.module == "gc":
            found_gc_import = True
    assert found_gc_import, "terrain_pipeline.py must import the gc module"


# ---------------------------------------------------------------------------
# Snapshot round-trip — determinism + HW-unlock smoke (skips without numpy)
# ---------------------------------------------------------------------------


def make_controller_with_baseline(tmp_path: Path):
    """Construct a tiny TerrainPassController + write a baseline snapshot.

    Mirrors the smallest viable shape used by ``test_terrain_checkpoints.py``
    so the round-trip exercises the same TerrainMaskStack code path that
    AAA pipelines use, just at 16² instead of 4096².
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        _load_baseline_snapshot,
        _snapshot_mask_stack_to_disk,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    rng = np.random.default_rng(123)
    tile = 16
    h = rng.normal(100.0, 5.0, (tile, tile)).astype(np.float64)
    stack = TerrainMaskStack(
        tile_size=tile,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )
    intent = TerrainIntentState(
        seed=42,
        region_bounds=BBox(0.0, 0.0, float(tile), float(tile)),
        tile_size=tile,
        cell_size=1.0,
        anchors=(),
        protected_zones=(),
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)
    controller = TerrainPassController(state, checkpoint_dir=tmp_path)
    return controller, _snapshot_mask_stack_to_disk, _load_baseline_snapshot


def test_snapshot_round_trip_preserves_content_hash(tmp_path: Path) -> None:
    """Baseline snapshot round-trip must preserve the SHA-256 content hash."""
    pytest.importorskip("numpy")
    controller, snap, load = make_controller_with_baseline(tmp_path)
    pre_hash = controller.state.mask_stack.compute_hash()
    snapshot_path = snap(
        controller.state.mask_stack,
        checkpoint_dir=controller.checkpoint_dir,
    )
    try:
        assert snapshot_path.exists(), "snapshot file was not created"
        rehydrated = load(snapshot_path)
        assert rehydrated.compute_hash() == pre_hash, (
            "round-trip must preserve content_hash byte-for-byte"
        )
        np.testing.assert_array_equal(
            rehydrated.height,
            controller.state.mask_stack.height,
            err_msg="round-trip height array drift",
        )
    finally:
        snapshot_path.unlink(missing_ok=True)


def test_lightweight_water_network_copy_independent_arrays(tmp_path: Path) -> None:
    """_lightweight_water_network_copy must return a value whose ndarray
    fields are independent buffers from the source's."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        _lightweight_water_network_copy,
    )

    # Build a duck-typed water_network-like object with an array attribute
    # and a dict-of-arrays attribute, mirroring WaterNetwork._velocity_field.
    class _FakeWN:
        def __init__(self) -> None:
            self.flow_field = np.ones((8, 8), dtype=np.float32)
            self._velocity_field = {
                "u": np.full((8, 8), 2.0, dtype=np.float32),
                "v": np.full((8, 8), 3.0, dtype=np.float32),
            }
            self.network_id = 7  # primitive — should be preserved

    src = _FakeWN()
    clone = _lightweight_water_network_copy(src)
    assert clone is not src, "must return a fresh object, not the same alias"
    # Mutating the clone's arrays must not affect the source.
    clone.flow_field[0, 0] = -1.0
    assert src.flow_field[0, 0] == 1.0, "ndarray fields must be independent"
    clone._velocity_field["u"][0, 0] = -2.0
    assert src._velocity_field["u"][0, 0] == 2.0, (
        "dict-of-ndarrays values must be independent"
    )
    assert clone.network_id == 7, "primitives must round-trip"


def test_lightweight_water_network_copy_handles_none() -> None:
    """A None water_network/viewport_vantage must round-trip as None."""
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        _lightweight_water_network_copy,
    )

    assert _lightweight_water_network_copy(None) is None


def test_run_pipeline_finally_cleans_up_snapshot(tmp_path: Path) -> None:
    """End-to-end: after run_pipeline, no baseline attrs + no .npz left."""
    pytest.importorskip("numpy")
    controller, _snap, _load = make_controller_with_baseline(tmp_path)
    # Run an empty pass_sequence — finally must still execute its cleanup.
    # (intent is positional-or-kwarg; passing pass_sequence by keyword
    # avoids the type-collision trap where ``run_pipeline([])`` would
    # bind the empty list to ``intent``.)
    controller.run_pipeline(pass_sequence=[])
    for attr in (
        "_pre_pipeline_baseline_stack",
        "_pre_pipeline_baseline_snapshot_path",
        "_pre_pipeline_baseline_hash",
    ):
        assert not hasattr(controller, attr), (
            f"baseline attr {attr} must be cleaned up after run_pipeline"
        )
    leftover = list(tmp_path.glob("pre_pipeline_baseline_*.npz"))
    assert not leftover, (
        f"finally block must unlink the temp baseline snapshot; leftover: {leftover}"
    )


def test_load_pre_pipeline_baseline_stack_returns_none_when_no_snapshot(
    tmp_path: Path,
) -> None:
    """The lazy-hydration helper returns None when run_pipeline hasn't fired."""
    pytest.importorskip("numpy")
    controller, _snap, _load = make_controller_with_baseline(tmp_path)
    # No baseline set up yet — helper must return None, not raise.
    assert controller._load_pre_pipeline_baseline_stack() is None
