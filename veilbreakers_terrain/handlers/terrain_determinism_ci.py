"""Bundle N — determinism CI regression harness.

Re-runs a deterministic pipeline N times against the same seed/intent and
asserts that the resulting ``TerrainMaskStack`` content hashes are
bit-identical. Detects mid-pipeline non-determinism (stray ``hash()``,
``random.random()``, wall-clock seeds) before it ships.

Pure Python + numpy — no bpy. See
docs/terrain_ultra_implementation_plan_2026-04-08.md §19 Bundle N.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .terrain_pipeline import TerrainPassController
from .terrain_semantics import (
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


@dataclass
class DeterminismRun:
    """Result of one deterministic pipeline replay."""

    run_index: int
    content_hash: str
    per_channel_hashes: Dict[str, str] = field(default_factory=dict)
    duration_seconds: float = 0.0
    pass_hashes: Tuple[str, ...] = ()
    full_state_hash: str = ""  # SHA-256 over mask stack + intent + pass history


def _snapshot_channel_hashes(stack: TerrainMaskStack) -> Dict[str, str]:
    """Return per-channel SHA-256 (truncated) for a stack."""
    import hashlib

    out: Dict[str, str] = {}
    for name in stack._ARRAY_CHANNELS:
        val = getattr(stack, name, None)
        if val is None:
            continue
        import numpy as np

        arr = np.ascontiguousarray(val)
        h = hashlib.sha256()
        h.update(name.encode("utf-8"))
        h.update(str(arr.dtype).encode("utf-8"))
        h.update(repr(arr.shape).encode("utf-8"))
        h.update(arr.tobytes())
        out[name] = h.hexdigest()
    return out


def _clone_state(state: TerrainPipelineState) -> TerrainPipelineState:
    """Clone a pipeline state so a replay starts from an independent mask stack.

    FIX-9-32: uses _shallow_stack_clone instead of copy.deepcopy to avoid the
    4–8 GB allocation at 4k tile. intent is immutable and safe to share.
    pass_history, checkpoints, side_effects, and particle_layer_specs are reset
    to empty lists so each CI run starts from a clean slate.
    """
    import dataclasses as _dc
    from .terrain_pipeline import _shallow_stack_clone
    return _dc.replace(
        state,
        mask_stack=_shallow_stack_clone(state.mask_stack),
        pass_history=[],
        checkpoints=[],
        side_effects=[],
        particle_layer_specs=[],
        water_network=None,
        viewport_vantage=None,
        texture_layer_stack=None,
    )


def _hash_full_state(state: TerrainPipelineState) -> str:
    """Produce a SHA-256 over the complete pipeline state, not just the mask stack.

    Covers:
      * The mask stack content hash (all array channels + coordinate contract).
      * The intent dict (serialised via JSON so nested mutable fields are included).
      * pass_history length (structural change indicator).

    Intent serialisation uses ``repr()`` as fallback for non-JSON-serialisable
    values so the hash never silently drops a nested mutable field.
    """
    h = hashlib.sha256()

    # 1. Mask stack — already a thorough SHA-256 over all array channels.
    h.update(state.mask_stack.compute_hash().encode("utf-8"))

    # 2. Intent — full recursive serialisation.
    try:
        intent_bytes = json.dumps(
            state.intent.__dict__ if hasattr(state.intent, "__dict__") else repr(state.intent),
            sort_keys=True,
            default=repr,
        ).encode("utf-8")
    except Exception:
        intent_bytes = repr(state.intent).encode("utf-8")
    h.update(intent_bytes)

    # 3. Structural pass-history indicator (length only — content is pass-specific).
    h.update(str(len(state.pass_history)).encode("utf-8"))

    return h.hexdigest()


def run_determinism_check(
    controller: TerrainPassController,
    seed: int,
    runs: int = 3,
    *,
    pass_sequence: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Execute the same pipeline ``runs`` times and assert bit-identical outputs.

    The controller's current state is used as the baseline. Each run deep-copies
    the baseline and executes ``pass_sequence`` (or the default pipeline). The
    returned dict has keys:

        ``deterministic`` : bool
        ``runs``          : list[DeterminismRun]
        ``reference_hash``: str
        ``mismatches``    : list[(run_index, hash)]
        ``channel_divergences`` : list[(run_index, channel_name)]
    """
    if runs < 2:
        raise ValueError("run_determinism_check requires runs >= 2")

    baseline_state = _clone_state(controller.state)

    run_records: List[DeterminismRun] = []
    for i in range(runs):
        # Fresh state + fresh controller (new checkpoint_dir not needed — we
        # pass checkpoint=False to avoid polluting disk).
        replay_state = _clone_state(baseline_state)
        replay_ctrl = TerrainPassController(replay_state, checkpoint_dir=controller.checkpoint_dir)
        t0 = time.perf_counter()
        results = replay_ctrl.run_pipeline(
            pass_sequence=list(pass_sequence) if pass_sequence else None,
            checkpoint=False,
        )
        dt = time.perf_counter() - t0
        content_hash = replay_state.mask_stack.compute_hash()
        channel_hashes = _snapshot_channel_hashes(replay_state.mask_stack)
        pass_hashes = tuple(r.content_hash_after or "" for r in results)
        full_state_hash = _hash_full_state(replay_state)
        run_records.append(
            DeterminismRun(
                run_index=i,
                content_hash=content_hash,
                per_channel_hashes=channel_hashes,
                duration_seconds=dt,
                pass_hashes=pass_hashes,
                full_state_hash=full_state_hash,
            )
        )

    reference = run_records[0]
    mismatches: List[Tuple[int, str]] = []
    channel_divergences: List[Tuple[int, str]] = []
    full_state_mismatches: List[Tuple[int, str]] = []
    for rec in run_records[1:]:
        # Check mask-stack hash (output channels).
        if rec.content_hash != reference.content_hash:
            mismatches.append((rec.run_index, rec.content_hash))
            for ch, h in rec.per_channel_hashes.items():
                if reference.per_channel_hashes.get(ch) != h:
                    channel_divergences.append((rec.run_index, ch))
        # Check full state hash (catches intent mutation + pass-history drift
        # that would be invisible from mask-stack output alone).
        if rec.full_state_hash and reference.full_state_hash:
            if rec.full_state_hash != reference.full_state_hash:
                full_state_mismatches.append((rec.run_index, rec.full_state_hash))

    # Identify the *first* pass where non-determinism appears by walking the
    # per-pass hash sequences for any mismatch runs and recording the earliest
    # diverging index.  This lets callers bisect the problem without re-running.
    suspect_passes: List[Tuple[int, str]] = []
    for rec in run_records[1:]:
        if rec.content_hash == reference.content_hash:
            continue
        ref_hashes = reference.pass_hashes
        rec_hashes = rec.pass_hashes
        for idx, (rh, ch) in enumerate(zip(ref_hashes, rec_hashes)):
            if rh != ch and rh and ch:
                # Recover pass name from pass_sequence if available
                pass_name = (
                    list(pass_sequence)[idx]
                    if pass_sequence and idx < len(list(pass_sequence))
                    else f"pass_index_{idx}"
                )
                entry = (idx, pass_name)
                if entry not in suspect_passes:
                    suspect_passes.append(entry)
                break

    durations = [r.duration_seconds for r in run_records]
    dur_stdev = 0.0
    if len(durations) >= 2:
        mean = sum(durations) / len(durations)
        dur_stdev = (sum((d - mean) ** 2 for d in durations) / len(durations)) ** 0.5

    return {
        "deterministic": not mismatches and not full_state_mismatches,
        "runs": run_records,
        "reference_hash": reference.content_hash,
        "reference_full_state_hash": reference.full_state_hash,
        "mismatches": mismatches,
        "full_state_mismatches": full_state_mismatches,
        "channel_divergences": channel_divergences,
        "suspect_passes": suspect_passes,
        "duration_stdev_s": dur_stdev,
        "avg_duration_s": sum(durations) / len(durations) if durations else 0.0,
        "seed": int(seed),
        "run_count": runs,
    }


def detect_determinism_regressions(
    baseline_hash: str,
    current_hash: str,
) -> List[ValidationIssue]:
    """Compare a freshly-computed content hash against a stored baseline."""
    issues: List[ValidationIssue] = []
    if not baseline_hash or not current_hash:
        issues.append(
            ValidationIssue(
                code="DETERMINISM_HASH_MISSING",
                severity="soft",
                message=(
                    f"one or both hashes missing — baseline={baseline_hash!r}, "
                    f"current={current_hash!r}"
                ),
            )
        )
        return issues
    if baseline_hash != current_hash:
        issues.append(
            ValidationIssue(
                code="DETERMINISM_REGRESSION",
                severity="hard",
                message=(
                    "mask stack hash diverged from baseline: "
                    f"baseline={baseline_hash[:16]}... current={current_hash[:16]}..."
                ),
                remediation=(
                    "Audit recently-touched passes for hash()/random.random()/"
                    "time.time() and replace with derive_pass_seed."
                ),
            )
        )
    return issues


def _hash_tile_output(tdir: str) -> str:
    """SHA-256 over all deterministic artifact bytes in *tdir*, sorted by name."""
    import hashlib
    from pathlib import Path as _Path

    root = _Path(tdir)
    if not root.exists():
        raise FileNotFoundError(f"determinism output directory missing: {tdir}")
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            h.update(rel.encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


def run_determinism_check_subprocess(
    seed: int,
    runs: int = 2,
    *,
    size: int = 32,
    scale: float = 50.0,
    terrain_type: str = "mountains",
) -> Dict[str, Any]:
    """Run ``generate_tile`` ``runs`` times in isolated subprocesses, compare output hashes.

    Each run starts a fresh interpreter so module-level globals, numpy RNG
    state, and threading locals cannot leak between runs — the in-process
    ``run_determinism_check`` cannot guarantee this.

    Returns the same shape dict as ``run_determinism_check`` so callers are
    interchangeable::

        {"deterministic": bool, "hashes": list[str], "seed": int}
    """
    import subprocess
    import sys
    import tempfile

    hashes: List[str] = []
    for i in range(runs):
        with tempfile.TemporaryDirectory(prefix=f"vb_det_{i}_") as tdir:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "veilbreakers_terrain.cli",
                    "generate_tile",
                    "--seed",
                    str(seed),
                    "--output-dir",
                    tdir,
                    "--size",
                    str(size),
                    "--scale",
                    str(scale),
                    "--terrain-type",
                    terrain_type,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            hashes.append(_hash_tile_output(tdir))

    return {
        "deterministic": all(h == hashes[0] for h in hashes),
        "hashes": hashes,
        "seed": int(seed),
        "run_count": runs,
        "requires_subprocess": True,
    }


__all__ = [
    "DeterminismRun",
    "run_determinism_check",
    "run_determinism_check_subprocess",
    "detect_determinism_regressions",
]
