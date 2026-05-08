"""Phase B D25 — GATE D25 subprocess-determinism harness regression tests.

The CI matrix at ``.github/workflows/subprocess_determinism.yml`` (3 OS × 3
Py × 2 seed-seq = 18 cells) invokes
``python -m veilbreakers_terrain.deterministic_bake_harness ...`` and
parses the resulting JSON to decide pass/fail.  These tests pin the CLI
contract so a refactor cannot silently break the gate.

Notes
-----
Each test uses ``size=16`` to keep the underlying tile bake well under
1 second per run on slow CI runners.  The harness itself spawns 2 fresh
subprocess bakes per invocation (default ``--runs=2``), so the wall-clock
cost is roughly ``2 × tile_bake_time``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


def _run_harness(
    *args: str, expect_exit: int = 0
) -> dict[str, Any]:
    """Invoke the harness CLI in a subprocess and parse its JSON output.

    Returns the parsed payload on success.  Asserts the exit code matches
    ``expect_exit`` so the caller doesn't have to check it manually.
    """
    cmd = [
        sys.executable,
        "-m",
        "veilbreakers_terrain.deterministic_bake_harness",
        *args,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == expect_exit, (
        f"harness exit code {proc.returncode} != expected {expect_exit}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    if expect_exit == 0:
        try:
            parsed: dict[str, Any] = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"harness stdout is not valid JSON:\n{proc.stdout!r}"
            ) from exc
        return parsed
    return {}


def test_harness_reports_deterministic_for_fixed_seed():
    """Two subprocess bakes at the same seed must produce identical hashes."""
    payload = _run_harness("--seed=42", "--tile=0,0", "--runs=2", "--size=16")

    assert payload["deterministic"] is True
    assert payload["seed"] == 42
    assert payload["tile"] == [0, 0]
    assert payload["run_count"] == 2
    assert len(payload["hashes"]) == 2
    assert payload["hashes"][0] == payload["hashes"][1], (
        "subprocess bakes at fixed seed must produce byte-identical output"
    )
    # Each hash is a 64-char SHA-256 hex digest.
    for h in payload["hashes"]:
        assert isinstance(h, str)
        assert len(h) == 64


def test_harness_reports_deterministic_for_alternate_seed():
    """Second seed in the CI matrix (7777) must also be deterministic."""
    payload = _run_harness("--seed=7777", "--tile=0,0", "--runs=2", "--size=16")

    assert payload["deterministic"] is True
    assert payload["seed"] == 7777
    assert payload["hashes"][0] == payload["hashes"][1]


def test_harness_different_seeds_produce_different_hashes():
    """Sanity: distinct seeds must NOT produce identical bakes.

    This guards against a no-op bake that hashes to the same constant
    regardless of seed (which would falsely pass GATE D25).
    """
    p1 = _run_harness("--seed=42", "--tile=0,0", "--runs=2", "--size=16")
    p2 = _run_harness("--seed=7777", "--tile=0,0", "--runs=2", "--size=16")

    assert p1["hashes"][0] != p2["hashes"][0], (
        "distinct seeds produced identical bakes — bake is seed-insensitive!"
    )


def test_harness_rejects_runs_less_than_two():
    """``--runs=1`` is a configuration error (no comparison possible)."""
    cmd = [
        sys.executable,
        "-m",
        "veilbreakers_terrain.deterministic_bake_harness",
        "--seed=42",
        "--runs=1",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 2, (
        f"--runs=1 must exit 2 (config error), got {proc.returncode}\n"
        f"stderr: {proc.stderr}"
    )


def test_harness_parses_tile_coordinates():
    """``--tile=X,Y`` round-trips into the JSON payload as ``[X, Y]``."""
    payload = _run_harness("--seed=42", "--tile=3,5", "--runs=2", "--size=16")
    assert payload["tile"] == [3, 5]


def test_harness_rejects_malformed_tile():
    """Malformed ``--tile`` value must exit with config-error code."""
    cmd = [
        sys.executable,
        "-m",
        "veilbreakers_terrain.deterministic_bake_harness",
        "--seed=42",
        "--tile=not-a-pair",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 2, (
        f"malformed --tile must exit 2, got {proc.returncode}"
    )
