"""Bundle N — golden snapshot library.

Canonical reference tiles for deep regression testing. Each golden
snapshot captures the mask stack's content hash plus per-channel hashes
and the pipeline version. A freshly-generated tile is compared against a
stored golden; any mismatch raises a hard ``ValidationIssue``.

Pure numpy + stdlib — no bpy. See plan §19.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .terrain_pipeline import TerrainPassController
from .terrain_semantics import (
    TerrainIntentState,
    TerrainMaskStack,
    ValidationIssue,
)


PIPELINE_VERSION = "bundle_n_1.0"


@dataclass
class GoldenSnapshot:
    """A canonical reference tile hash record."""

    snapshot_id: str
    content_hash: str
    channel_hashes: Dict[str, str] = field(default_factory=dict)
    timestamp: float = 0.0
    pipeline_version: str = PIPELINE_VERSION
    seed: int = 0
    tile_coords: Tuple[int, int] = (0, 0)
    tile_size: int = 0
    cell_size: float = 1.0
    populated_by_pass: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tile_coords"] = list(self.tile_coords)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoldenSnapshot":
        coords = data.get("tile_coords", [0, 0])
        return cls(
            snapshot_id=str(data["snapshot_id"]),
            content_hash=str(data["content_hash"]),
            channel_hashes=dict(data.get("channel_hashes", {})),
            timestamp=float(data.get("timestamp", 0.0)),
            pipeline_version=str(data.get("pipeline_version", PIPELINE_VERSION)),
            seed=int(data.get("seed", 0)),
            tile_coords=(int(coords[0]), int(coords[1])),
            tile_size=int(data.get("tile_size", 0)),
            cell_size=float(data.get("cell_size", 1.0)),
            populated_by_pass=dict(data.get("populated_by_pass", {})),
        )


def _channel_hashes(stack: TerrainMaskStack) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name in stack._ARRAY_CHANNELS:
        val = getattr(stack, name, None)
        if val is None:
            continue
        arr = np.ascontiguousarray(val)
        h = hashlib.sha256()
        h.update(name.encode("utf-8"))
        h.update(str(arr.dtype).encode("utf-8"))
        h.update(repr(arr.shape).encode("utf-8"))
        h.update(arr.tobytes())
        out[name] = h.hexdigest()
    return out


def save_golden_snapshot(
    stack: TerrainMaskStack,
    output_dir: Path,
    snapshot_id: str,
    *,
    seed: int = 0,
) -> GoldenSnapshot:
    """Hash the stack, persist a .json record and companion .npz, and return the GoldenSnapshot.

    BUG-R8-A9-026: also writes a companion .golden.npz so tolerance-based
    comparisons can load actual array data.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    snap = GoldenSnapshot(
        snapshot_id=snapshot_id,
        content_hash=stack.compute_hash(),
        channel_hashes=_channel_hashes(stack),
        timestamp=time.time(),
        pipeline_version=PIPELINE_VERSION,
        seed=int(seed),
        tile_coords=(int(stack.tile_x), int(stack.tile_y)),
        tile_size=int(stack.tile_size),
        cell_size=float(stack.cell_size),
        populated_by_pass=dict(stack.populated_by_pass),
    )
    json_path = output_dir / f"{snapshot_id}.golden.json"
    # BUG-R8-A9-026: write companion .npz for tolerance-based comparison
    npz_path = json_path.with_suffix(".npz")
    stack.to_npz(npz_path)
    snap_dict = snap.to_dict()
    snap_dict["npz_path"] = str(npz_path)
    json_path.write_text(json.dumps(snap_dict, sort_keys=True, indent=2))
    return snap


def load_golden_snapshot(path: Path) -> GoldenSnapshot:
    """Load a previously-saved golden snapshot."""
    raw = json.loads(Path(path).read_text())
    return GoldenSnapshot.from_dict(raw)


def compare_against_golden(
    stack: TerrainMaskStack,
    golden: GoldenSnapshot,
    tolerance: float = 0.0,
    *,
    golden_dir: Optional[Path] = None,
) -> List[ValidationIssue]:
    """Compare a fresh stack against a stored golden.

    BUG-R8-A9-025: when ``tolerance > 0`` and hashes differ, load the
    companion ``.golden.npz`` and use ``np.allclose(atol=tolerance)`` per
    channel before raising a hard failure — allowing intentional minor
    floating-point drift to pass.

    BUG-R8-A9-024: channels present in ``current`` but absent in ``golden``
    are emitted as soft ``GOLDEN_CHANNEL_NEW`` issues.
    """
    issues: List[ValidationIssue] = []
    current_hash = stack.compute_hash()
    hash_match = current_hash == golden.content_hash

    if not hash_match:
        # BUG-R8-A9-025: tolerance path — load npz and compare with np.allclose
        tolerance_passed = False
        if tolerance > 0.0 and golden_dir is not None:
            npz_path = Path(golden_dir) / f"{golden.snapshot_id}.golden.npz"
            if npz_path.exists():
                try:
                    golden_stack = TerrainMaskStack.from_npz(npz_path)
                    all_close = True
                    for ch in golden.channel_hashes:
                        cur_arr = stack.get(ch)
                        gld_arr = golden_stack.get(ch)
                        if cur_arr is None or gld_arr is None:
                            all_close = False
                            break
                        if not np.allclose(np.asarray(cur_arr), np.asarray(gld_arr), atol=tolerance):
                            all_close = False
                            break
                    tolerance_passed = all_close
                except Exception:
                    tolerance_passed = False

        if not tolerance_passed:
            issues.append(
                ValidationIssue(
                    code="GOLDEN_HASH_MISMATCH",
                    severity="hard",
                    message=(
                        f"golden '{golden.snapshot_id}' content hash diverged: "
                        f"expected {golden.content_hash[:16]}..., "
                        f"got {current_hash[:16]}..."
                    ),
                    remediation=(
                        "Regenerate the golden if the change is intentional, "
                        "otherwise audit the offending pass."
                    ),
                )
            )

    current_channels = _channel_hashes(stack)
    divergences: List[str] = []
    for ch, h in golden.channel_hashes.items():
        if current_channels.get(ch) != h:
            divergences.append(ch)

    if divergences:
        issues.append(
            ValidationIssue(
                code="GOLDEN_CHANNEL_DIVERGENCE",
                severity="hard",
                message=(
                    f"channels diverged from golden '{golden.snapshot_id}': "
                    f"{divergences[:6]}"
                ),
            )
        )

    # BUG-R8-A9-024: emit soft issue for channels in current but absent in golden
    for ch in current_channels:
        if ch not in golden.channel_hashes:
            issues.append(
                ValidationIssue(
                    code="GOLDEN_NEW_CHANNEL",
                    severity="soft",
                    message=(
                        f"channel '{ch}' present in current stack but absent in "
                        f"golden '{golden.snapshot_id}' — update the golden if intentional."
                    ),
                )
            )

    if golden.pipeline_version != PIPELINE_VERSION:
        issues.append(
            ValidationIssue(
                code="GOLDEN_PIPELINE_VERSION_DRIFT",
                severity="soft",
                message=(
                    f"golden pipeline_version={golden.pipeline_version!r} "
                    f"does not match current {PIPELINE_VERSION!r}"
                ),
            )
        )
    return issues


def _seed_one(
    i: int,
    count: int,
    controller: "TerrainPassController",
    output_dir: Path,
    base_intent: Optional[TerrainIntentState],
    build_state_fn: Optional[Any],
) -> Tuple[Optional[GoldenSnapshot], Optional[Tuple[int, str]]]:
    """Worker for one golden snapshot generation. Returns (snap, None) or (None, (i, reason))."""
    import copy
    from dataclasses import replace as _replace

    print(f"Seeding {i}/{count}...")
    try:
        if build_state_fn is not None:
            state = build_state_fn(
                seed=(base_intent.seed if base_intent else 0) + i,
                tile_x=i % 8,
                tile_y=i // 8,
            )
        else:
            state = copy.deepcopy(controller.state)
            new_seed = int(state.intent.seed) + i
            state.intent = _replace(state.intent, seed=new_seed)

        replay_ctrl = TerrainPassController(
            state, checkpoint_dir=controller.checkpoint_dir
        )
        replay_ctrl.run_pipeline(checkpoint=False)
        snap_id = f"golden_{i:04d}_seed{state.intent.seed}"
        snap = save_golden_snapshot(
            state.mask_stack,
            output_dir,
            snap_id,
            seed=int(state.intent.seed),
        )
        return snap, None
    except Exception as exc:  # noqa: BLE001
        return None, (i, str(exc))


def seed_golden_library(
    controller: TerrainPassController,
    output_dir: Path,
    count: int = 120,
    *,
    base_intent: Optional[TerrainIntentState] = None,
    build_state_fn: Optional[Any] = None,
) -> List[GoldenSnapshot]:
    """Generate ``count`` canonical golden snapshots.

    Strategy: for i in [0, count), deep-copy the controller's baseline state,
    override the seed to ``baseline_seed + i`` (modulo tile coords also
    offset), run the default pipeline, and save the result.

    ``build_state_fn`` is an optional callable ``(seed, tile_x, tile_y) ->
    TerrainPipelineState`` allowing tests to inject lightweight state
    construction without requiring a fully-populated controller. If not
    provided, the controller's current state is cloned via deepcopy.

    BUG-R8-A9-027: uses ProcessPoolExecutor when count > 4 for parallelism.
    BUG-R8-A9-028: collects failures; raises RuntimeError if > 10% fail.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots: List[GoldenSnapshot] = []
    # BUG-R8-A9-028: collect failures instead of silently continuing
    failures: List[Tuple[int, str]] = []

    # BUG-R8-A9-027: parallel path when count > 4; fall back to sequential on
    # pickling errors (e.g. when running under module-alias test environments).
    _use_parallel = count > 4
    if _use_parallel:
        try:
            with concurrent.futures.ProcessPoolExecutor() as executor:
                futures = {
                    executor.submit(
                        _seed_one, i, count, controller, output_dir, base_intent, build_state_fn
                    ): i
                    for i in range(count)
                }
                for fut in concurrent.futures.as_completed(futures):
                    snap, failure = fut.result()
                    if snap is not None:
                        snapshots.append(snap)
                    elif failure is not None:
                        failures.append(failure)
        except Exception as _parallel_exc:  # noqa: BLE001
            # Pickling or spawn failure — fall back to sequential execution
            snapshots.clear()
            failures.clear()
            _use_parallel = False

    if not _use_parallel:
        for i in range(count):
            snap, failure = _seed_one(i, count, controller, output_dir, base_intent, build_state_fn)
            if snap is not None:
                snapshots.append(snap)
            elif failure is not None:
                failures.append(failure)

    # BUG-R8-A9-028: raise if failure rate exceeds 10%; else include in manifest
    if count > 0 and len(failures) > count * 0.1:
        raise RuntimeError(
            f"seed_golden_library: {len(failures)}/{count} tiles failed "
            f"(>{count * 0.1:.0f} threshold). First failures: {failures[:5]}"
        )

    manifest_path = output_dir / "golden_library_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "pipeline_version": PIPELINE_VERSION,
                "count": len(snapshots),
                "snapshot_ids": [s.snapshot_id for s in snapshots],
                "timestamp": time.time(),
                "failures": failures,
            },
            sort_keys=True,
            indent=2,
        )
    )
    return snapshots


__all__ = [
    "PIPELINE_VERSION",
    "GoldenSnapshot",
    "save_golden_snapshot",
    "load_golden_snapshot",
    "compare_against_golden",
    "seed_golden_library",
]
