"""Tests for FIX-B14-19 (determinism CI subprocess) and FIX-B14-23 (hot-reload func rebind).

FIX-B14-19: run_determinism_check() is in-process and unfalsifiable for
    production use. run_determinism_check_subprocess() spawns isolated
    interpreters so RNG/global leaks are detectable.

FIX-B14-23: After importlib.reload(), already-registered PassDefinitions hold
    stale function references. _rebind_pass_funcs_for_module() re-binds func
    via the module-level _PASS_MODULE_REGISTRY.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# FIX-B14-19: subprocess determinism detects planted non-determinism
# ---------------------------------------------------------------------------


def test_determinism_check_subprocess_detects_planted_rng_nondeterminism(
    monkeypatch, tmp_path
):
    """run_determinism_check_subprocess must return deterministic=False when
    the CLI produces different outputs on each invocation.

    We plant non-determinism by monkeypatching subprocess.run so that the
    first call writes file content "aaa..." and subsequent calls write "bbb...".
    The resulting SHA-256 hashes differ, so the function must return False.
    """
    import subprocess

    from veilbreakers_terrain.handlers import terrain_determinism_ci as det

    call_count = 0

    def _fake_run(cmd, capture_output, text, check):
        nonlocal call_count
        call_count += 1
        out_dir = cmd[cmd.index("--output-dir") + 1]
        # First run: deterministic content; subsequent runs: different content
        content = b"aaa_tile_data" if call_count == 1 else b"bbb_tile_data_different"
        Path(out_dir, "tile.bin").write_bytes(content)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    report = det.run_determinism_check_subprocess(seed=42, runs=2, size=4)

    assert report["deterministic"] is False, (
        "run_determinism_check_subprocess must detect non-determinism when "
        "subprocess outputs differ"
    )
    assert report["run_count"] == 2
    assert len(report["hashes"]) == 2
    assert report["hashes"][0] != report["hashes"][1]


def test_determinism_check_subprocess_passes_when_outputs_identical(
    monkeypatch, tmp_path
):
    """run_determinism_check_subprocess returns deterministic=True when all
    subprocess runs produce byte-identical output.
    """
    import subprocess

    from veilbreakers_terrain.handlers import terrain_determinism_ci as det

    def _fake_run(cmd, capture_output, text, check):
        out_dir = cmd[cmd.index("--output-dir") + 1]
        # Always same content — deterministic
        Path(out_dir, "tile.bin").write_bytes(b"identical_content_every_run")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    report = det.run_determinism_check_subprocess(seed=7, runs=3, size=4)

    assert report["deterministic"] is True
    assert report["run_count"] == 3
    assert len(set(report["hashes"])) == 1, "all hashes must be identical"


def test_run_determinism_check_emits_deprecation_warning_outside_test(monkeypatch):
    """run_determinism_check() must emit DeprecationWarning when called
    outside a pytest session (PYTEST_CURRENT_TEST not set).
    """
    import warnings

    import numpy as np

    from veilbreakers_terrain.handlers.terrain_determinism_ci import run_determinism_check
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    # Temporarily hide the pytest env var so the function thinks it's production
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    tile_size = 8
    height = np.zeros((tile_size, tile_size), dtype=np.float32)
    stack = TerrainMaskStack(
        height=height,
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
    )
    region = BBox(0.0, 0.0, float(tile_size), float(tile_size))
    intent = TerrainIntentState(
        seed=1,
        region_bounds=region,
        tile_size=tile_size,
        cell_size=1.0,
    )
    state = TerrainPipelineState(mask_stack=stack, intent=intent)
    ctrl = TerrainPassController(state)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        report = run_determinism_check(ctrl, seed=1, runs=2)

    deprecation_warnings = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert deprecation_warnings, (
        "run_determinism_check() must emit DeprecationWarning when called "
        "outside a pytest session"
    )
    assert "run_determinism_check_subprocess" in str(deprecation_warnings[0].message)

    # The return dict must include the hard ValidationIssue
    issue = report.get("inprocess_deprecation_issue")
    assert issue is not None, "inprocess_deprecation_issue must be in result dict"
    assert issue.severity == "hard"
    assert issue.code == "DETERMINISM_INPROCESS_REPLAY"


# ---------------------------------------------------------------------------
# FIX-B14-23: hot-reload re-binds PassDefinition.func
# ---------------------------------------------------------------------------


def test_hot_reload_biome_rule_change_takes_effect_in_next_pipeline_run():
    """After hot-reload, the registered PassDefinition.func must point to
    the new function object, not the stale pre-reload one.

    Setup:
      1. Create a synthetic module with a function returning value X.
      2. Register a PassDefinition whose func comes from that module.
      3. Swap the module's function to return Y (simulating a designer edit).
      4. Call _rebind_pass_funcs_for_module for that module.
      5. Assert PassDefinition.func now returns Y.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        _PASS_MODULE_REGISTRY,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition

    # --- 1. Build a synthetic module ---
    fake_mod_name = "veilbreakers_terrain._test_hot_reload_b14_23_fake"
    fake_mod = types.ModuleType(fake_mod_name)

    # Use simple callables that return a distinct marker value
    def func_v1(state, bbox):
        return "value_X"

    def func_v2(state, bbox):
        return "value_Y"

    func_v1.__module__ = fake_mod_name
    func_v1.__name__ = "fake_pass_func"
    func_v1.__qualname__ = "fake_pass_func"

    func_v2.__module__ = fake_mod_name
    func_v2.__name__ = "fake_pass_func"
    func_v2.__qualname__ = "fake_pass_func"

    fake_mod.fake_pass_func = func_v1
    sys.modules[fake_mod_name] = fake_mod

    # --- 2. Register a PassDefinition backed by func_v1 ---
    defn = PassDefinition(
        name="_test_rebind_pass_b14_23",
        func=func_v1,
    )
    # Register directly to populate _PASS_MODULE_REGISTRY
    TerrainPassController.register_pass(defn)

    try:
        # Confirm the registry recorded the module binding
        key = (fake_mod_name, "fake_pass_func")
        assert key in _PASS_MODULE_REGISTRY, (
            "_PASS_MODULE_REGISTRY must contain the (module_name, attr_name) key "
            "after register_pass()"
        )
        assert _PASS_MODULE_REGISTRY[key] is defn

        # Confirm current func is v1
        assert TerrainPassController.PASS_REGISTRY["_test_rebind_pass_b14_23"].func is func_v1
        assert TerrainPassController.PASS_REGISTRY["_test_rebind_pass_b14_23"].func(None, None) == "value_X"

        # --- 3. Simulate designer edit: swap module attribute to func_v2 ---
        fake_mod.fake_pass_func = func_v2

        # --- 4. Call _rebind_pass_funcs_for_module ---
        from veilbreakers_terrain.handlers.terrain_hot_reload import (
            _rebind_pass_funcs_for_module,
        )
        rebound = _rebind_pass_funcs_for_module(fake_mod_name)

        # --- 5. Assert func is now v2 (returns "value_Y") ---
        assert rebound >= 1, "_rebind_pass_funcs_for_module must report at least 1 rebind"
        updated_defn = TerrainPassController.PASS_REGISTRY["_test_rebind_pass_b14_23"]
        assert updated_defn.func is func_v2, (
            "After hot-reload, PassDefinition.func must be rebound to the new "
            "function object from the reloaded module"
        )
        assert updated_defn.func is not func_v1, (
            "Stale func_v1 must no longer be referenced after rebind"
        )
        assert updated_defn.func(None, None) == "value_Y", (
            "Calling the rebound func must return the new value Y, not stale X"
        )

    finally:
        # Clean up synthetic module and registry entry
        TerrainPassController.PASS_REGISTRY.pop("_test_rebind_pass_b14_23", None)
        sys.modules.pop(fake_mod_name, None)


def test_rebind_skips_gracefully_when_module_not_in_sys_modules():
    """_rebind_pass_funcs_for_module must return 0 and not raise when the
    named module is absent from sys.modules (e.g. never imported).
    """
    from veilbreakers_terrain.handlers.terrain_hot_reload import _rebind_pass_funcs_for_module

    result = _rebind_pass_funcs_for_module("veilbreakers_terrain._nonexistent_module_xyz")
    assert result == 0


def test_rebind_skips_gracefully_when_attr_removed_from_module():
    """_rebind_pass_funcs_for_module must log a warning and skip (not raise)
    when the expected attribute no longer exists on the reloaded module.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        _PASS_MODULE_REGISTRY,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import PassDefinition

    fake_mod_name = "veilbreakers_terrain._test_hot_reload_b14_23_missing_attr"
    fake_mod = types.ModuleType(fake_mod_name)

    def func_gone(state, bbox):
        pass

    func_gone.__module__ = fake_mod_name
    func_gone.__name__ = "gone_func"
    func_gone.__qualname__ = "gone_func"
    fake_mod.gone_func = func_gone
    sys.modules[fake_mod_name] = fake_mod

    defn = PassDefinition(name="_test_rebind_missing_attr_b14_23", func=func_gone)
    TerrainPassController.register_pass(defn)

    try:
        # Now remove the attribute (simulating a rename during designer edit)
        del fake_mod.gone_func

        from veilbreakers_terrain.handlers.terrain_hot_reload import (
            _rebind_pass_funcs_for_module,
        )
        # Must not raise — just return 0 rebound (attr missing)
        rebound = _rebind_pass_funcs_for_module(fake_mod_name)
        assert rebound == 0, "No rebinds should succeed when attr is missing from module"

        # Original func must be unchanged (stale but not crashed)
        assert (
            TerrainPassController.PASS_REGISTRY["_test_rebind_missing_attr_b14_23"].func
            is func_gone
        )

    finally:
        TerrainPassController.PASS_REGISTRY.pop("_test_rebind_missing_attr_b14_23", None)
        sys.modules.pop(fake_mod_name, None)
