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


# ---------------------------------------------------------------------------
# Hardening PR B Fix #5 — VC finding: same-platform baseline + tile-shift hash
# ---------------------------------------------------------------------------
#
# Per-platform baseline hashes — captured 2026-05-08 on the development host
# and re-validated locally on each contributor's machine.  Different operating
# systems may serialise files with platform-dependent byte order (Windows CRLF
# vs POSIX LF in JSON manifests, file-listing iteration order on case-
# insensitive filesystems).  The hash is therefore platform-tagged.  When a
# new bake-side change shifts the baseline, regenerate by running:
#
#     python -m veilbreakers_terrain.deterministic_bake_harness \
#         --seed=42 --tile=0,0 --runs=2 --size=16
#
# and copy the first hash into the dict below for the matching ``platform``
# string (``windows`` / ``linux`` / ``darwin``).  CI cells on the unset
# platform will fall through to the "any-deterministic" assertion (i.e. the
# pair-equal check still runs, just no baseline pin).
_BASELINE_HASHES_BY_PLATFORM: dict[str, str] = {
    "windows": "3f67a95b666f3ce102053915e64250dd7b208be667b89ffec7ac81b1345b9311",
}


def test_harness_baseline_hash_unchanged():
    """Pin the SHA-256 baseline for (seed=42, tile=0,0, size=16).

    Closes PR #46 thread 6: a regression that breaks deterministic ordering
    in any pass would otherwise silently flip every CI cell at once.  By
    pinning the baseline value we get a *named* failure ("baseline hash
    drifted") that points at the responsible commit.
    """
    import platform as _platform

    payload = _run_harness("--seed=42", "--tile=0,0", "--runs=2", "--size=16")
    assert payload["deterministic"] is True
    actual_hash = payload["hashes"][0]
    plat = _platform.system().lower()  # 'windows' / 'linux' / 'darwin'
    expected = _BASELINE_HASHES_BY_PLATFORM.get(plat)
    if expected is None:
        # Platform not yet baselined — capture the hash value as a hint
        # for follow-up.  The pair-equal subprocess check above is still
        # exercised, so this branch keeps determinism-CI green while the
        # baseline catalogue catches up to a new OS.
        import warnings

        warnings.warn(
            f"No baseline hash pinned for platform={plat!r}; observed "
            f"{actual_hash}.  Add to _BASELINE_HASHES_BY_PLATFORM if stable.",
            stacklevel=2,
        )
        return
    assert actual_hash == expected, (
        f"baseline hash drifted on {plat}: got {actual_hash!r}, expected "
        f"{expected!r}.  A bake-side change broke deterministic ordering — "
        f"identify the offending commit before re-baselining."
    )


def test_harness_tile_coords_actually_shift_bake_hash():
    """``(0,0)`` and ``(3,5)`` must produce DIFFERENT baseline hashes.

    Closes PR #46 thread 6 regression: when ``--tile`` was first plumbed
    through ``run_determinism_check_subprocess`` the integration silently
    used ``tile_x=tile_y=0`` for every cell.  Every CI matrix cell hashed
    identically, falsely confirming "deterministic across tile coords"
    when in fact the harness was tile-blind.  This guard prevents the
    same regression from recurring.
    """
    p_origin = _run_harness("--seed=42", "--tile=0,0", "--runs=2", "--size=16")
    p_shifted = _run_harness("--seed=42", "--tile=3,5", "--runs=2", "--size=16")

    assert p_origin["deterministic"] is True
    assert p_shifted["deterministic"] is True
    # Same-tile pair-equal (each subprocess run reproduces).
    assert p_origin["hashes"][0] == p_origin["hashes"][1]
    assert p_shifted["hashes"][0] == p_shifted["hashes"][1]
    # Cross-tile non-equal — the bake samples a tile-specific slice of
    # world space, so different tile coords MUST produce different bytes.
    assert p_origin["hashes"][0] != p_shifted["hashes"][0], (
        "tile=(0,0) and tile=(3,5) hashed identically — harness regressed "
        "to tile-blind mode (PR #46 thread 6 regression)."
    )
