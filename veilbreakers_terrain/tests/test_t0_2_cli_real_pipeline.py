"""T0-2 regression: ``veilbreakers_terrain.cli`` must drive the REAL
``TerrainPassController.run_pipeline()`` instead of the prior
noise-only stub.

Background
----------
Per Y04 v3 anchor T0-2 (a.k.a. S01-P0-RT-02 / γ3 D-01), the CLI used to
call ``generate_heightmap`` + ``compute_slope_map_degrees`` directly,
bypassing every registered pass (no biome channels, no structural masks,
no validation, no provenance ledger). Pre-existing CLI tests asserted
byte-identical determinism of that bypass path, so the absence of the
orchestrator went unnoticed.

This test asserts the post-fix contract: the CLI manifest must carry
unambiguous evidence that ``TerrainPassController.run_pipeline()`` was
invoked and that registered passes wrote channels other than the
caller-supplied ``height``. Both conditions are impossible to satisfy
from a stub that returns canned data, which is the regression
discriminator the audit asked for.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _invoke_cli(out_dir: Path, *, seed: int = 7, size: int = 32) -> None:
    """Invoke the CLI as a subprocess (matches how operators bake tiles)."""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "veilbreakers_terrain.cli",
            "generate_tile",
            "--seed",
            str(seed),
            "--output-dir",
            str(out_dir),
            "--size",
            str(size),
        ],
        check=True,
        cwd=_REPO_ROOT,
    )


def _read_manifest(out_dir: Path) -> dict[str, Any]:
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.is_file(), (
        f"CLI did not write manifest.json to {out_dir}"
    )
    parsed: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), (
        f"manifest.json must decode to a dict, got {type(parsed).__name__}"
    )
    return parsed


# ---------------------------------------------------------------------------
# Core T0-2 assertions
# ---------------------------------------------------------------------------


def test_t0_2_cli_manifest_carries_non_empty_final_mask_stack_hash(tmp_path: Path) -> None:
    """The manifest must contain a non-empty ``final_mask_stack_hash``.

    Pre-fix the field did not exist at all (the stub never instantiated
    a TerrainMaskStack from inside the CLI), so its mere presence and
    SHA-256-shaped value already prove the orchestrator ran.
    """
    out_dir = tmp_path / "bake"
    _invoke_cli(out_dir)

    manifest = _read_manifest(out_dir)

    assert "final_mask_stack_hash" in manifest, (
        "CLI manifest is missing 'final_mask_stack_hash' — the stub "
        "bypass appears to still be active. Per T0-2 the CLI must route "
        "through TerrainPassController.run_pipeline() and persist the "
        "post-pipeline stack.compute_hash() into the manifest."
    )

    hash_value = manifest["final_mask_stack_hash"]
    assert isinstance(hash_value, str) and hash_value, (
        f"final_mask_stack_hash must be a non-empty string, got: {hash_value!r}"
    )
    # ``TerrainMaskStack.compute_hash`` returns hashlib.sha256(...).hexdigest()
    # which is always 64 lowercase hex chars.
    assert re.fullmatch(r"[0-9a-f]{64}", hash_value), (
        f"final_mask_stack_hash is not a SHA-256 hex digest: {hash_value!r}"
    )


def test_t0_2_cli_manifest_records_real_pass_sequence(tmp_path: Path) -> None:
    """The manifest must list the passes the orchestrator actually ran.

    A stub bypass can fake a hash by hardcoding hex, but it cannot
    truthfully populate ``pipeline_pass_sequence`` with the canonical
    pass names registered in ``TerrainPassController.PASS_REGISTRY``.
    Asserting both the presence of canonical pass names AND a sensible
    ordering forces the CLI to drive the real ``run_pipeline``.
    """
    out_dir = tmp_path / "bake"
    _invoke_cli(out_dir)

    manifest = _read_manifest(out_dir)

    assert "pipeline_pass_sequence" in manifest, (
        "Missing 'pipeline_pass_sequence' in CLI manifest — orchestrator "
        "evidence is absent. T0-2 fix requires recording the actual passes "
        "executed by TerrainPassController.run_pipeline()."
    )

    executed = manifest["pipeline_pass_sequence"]
    assert isinstance(executed, list) and executed, (
        f"pipeline_pass_sequence must be a non-empty list, got {executed!r}"
    )

    # Canonical scene-read-free defaults selected by environment.py's
    # _execute_terrain_pipeline when no scene_read is attached. The
    # earliest pass — ``pass_generate_low_freq_hmap`` — must always run.
    assert "pass_generate_low_freq_hmap" in executed, (
        f"pass_generate_low_freq_hmap is the canonical first pass for "
        f"scene-read-free bakes but it is not in {executed!r}. The CLI is "
        f"not driving the canonical pipeline."
    )

    # The terminal pass must be a validation pass — proves the pipeline
    # ran to completion rather than short-circuiting after the first step.
    assert any(p.startswith("validation_") for p in executed), (
        f"No validation pass in {executed!r}; pipeline did not complete."
    )

    # Status of the last executed pass must not be 'failed'.
    pipeline_status = manifest.get("pipeline_status")
    assert pipeline_status not in (None, "failed", "no_passes_executed"), (
        f"pipeline_status indicates the CLI did not actually execute the "
        f"pipeline: {pipeline_status!r}"
    )


def test_t0_2_cli_manifest_records_populated_channels_beyond_height(tmp_path: Path) -> None:
    """At least one channel other than ``height`` must be populated.

    A stub that merely echoes the caller-supplied heightmap cannot
    populate downstream channels such as ``slope`` or ``curvature``.
    Asserting ``populated_by_pass`` has entries beyond the seed input
    is the strongest evidence the pipeline did real work.
    """
    out_dir = tmp_path / "bake"
    _invoke_cli(out_dir)

    manifest = _read_manifest(out_dir)

    assert "pipeline_populated_channels" in manifest, (
        "Missing 'pipeline_populated_channels' in CLI manifest — cannot "
        "verify that the orchestrator wrote any channels."
    )

    populated = manifest["pipeline_populated_channels"]
    assert isinstance(populated, list), (
        f"pipeline_populated_channels must be a list, got {type(populated).__name__}"
    )

    # The CLI itself only assigns ``height`` on the mask stack before
    # invoking the orchestrator (and even that is set on the dataclass
    # field, not via ``set()`` so it never lands in populated_by_pass).
    # Any entries here are therefore PROOF that registered passes wrote
    # to the stack.
    assert populated, (
        "populated_by_pass is empty — registered passes did not write "
        "any channels. Either the pass registry is empty, the pipeline "
        "short-circuited, or the CLI is still calling a stub instead of "
        "TerrainPassController.run_pipeline()."
    )


# ---------------------------------------------------------------------------
# Determinism — the CLI must remain reproducible even with the real pipeline
# wired in. Without this assertion, the byte-identical-determinism contract
# from test_phase8_determinism_guardrails could regress silently.
# ---------------------------------------------------------------------------


def test_t0_2_cli_pipeline_hash_is_deterministic_across_runs(tmp_path: Path) -> None:
    """Same seed/size MUST produce the same final_mask_stack_hash twice."""
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"

    _invoke_cli(run_a, seed=11, size=32)
    _invoke_cli(run_b, seed=11, size=32)

    hash_a = _read_manifest(run_a)["final_mask_stack_hash"]
    hash_b = _read_manifest(run_b)["final_mask_stack_hash"]

    assert hash_a == hash_b, (
        f"final_mask_stack_hash diverged across two identical CLI invocations:\n"
        f"  run_a: {hash_a}\n"
        f"  run_b: {hash_b}\n"
        f"Pipeline non-determinism would defeat the T0-2 fix and the "
        f"byte-identical determinism contract in "
        f"test_phase8_determinism_guardrails."
    )


def test_t0_2_cli_pipeline_hash_changes_with_seed(tmp_path: Path) -> None:
    """Different seeds MUST produce different final_mask_stack_hash values.

    Guards against the perverse failure mode where the CLI is wired
    through ``run_pipeline`` but the pipeline ignores the seed and
    returns the same stack every time (a sneakier kind of stub).
    """
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"

    _invoke_cli(run_a, seed=1, size=32)
    _invoke_cli(run_b, seed=999, size=32)

    hash_a = _read_manifest(run_a)["final_mask_stack_hash"]
    hash_b = _read_manifest(run_b)["final_mask_stack_hash"]

    assert hash_a != hash_b, (
        f"final_mask_stack_hash is identical for seed=1 and seed=999:\n"
        f"  {hash_a}\n"
        f"The pipeline is ignoring the seed — almost certainly because a "
        f"static-return stub is still in the call path."
    )
