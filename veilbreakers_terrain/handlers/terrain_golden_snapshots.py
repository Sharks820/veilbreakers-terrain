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

from .terrain_io import atomic_write_text
from .terrain_pipeline import TerrainPassController
from .terrain_semantics import (
    TerrainIntentState,
    TerrainMaskStack,
    ValidationIssue,
)


PIPELINE_VERSION = "bundle_n_1.0"

_STRICT_GOLDEN_CHANNELS = frozenset(
    {
        "height",
        "slope",
        "flow_accumulation",
        "wetness",
        "water_surface_mask",
        "water_surface_elevation_m",
        "water_depth_m",
        "cliff_mask",
        "talus_mask",
        "strata_mask",
        "splatmap_weights_layer",
        "heightmap_raw_u16",
        "terrain_normals",
        "navmesh_area_id",
        "traversability",
        "road_mask",
    }
)


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
    npz_path: str = ""

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
            npz_path=str(data.get("npz_path", "")),
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
    snap.npz_path = str(npz_path)
    # FIX-D24-PR12: atomic write so a crash mid-bake can never leave a
    # half-written golden manifest that downstream comparators would
    # parse as corrupt.
    # T0.5-8b (Y04 v3 §P.8.2): allow_nan=False — loud-at-source per ZZ4-A6 R3;
    # NaN in a golden snapshot would silently mask determinism drift.
    atomic_write_text(
        json_path,
        json.dumps(snap.to_dict(), sort_keys=True, indent=2, allow_nan=False),
    )
    return snap


def load_golden_snapshot(path: Path) -> GoldenSnapshot:
    """Load a previously-saved golden snapshot."""
    raw = json.loads(Path(path).read_text())
    return GoldenSnapshot.from_dict(raw)


# P1-34: Per-channel tolerance defaults.  Heights are in metres (large
# absolute values), slopes in radians (small), wetness in [0,1] (small).
# Using one tolerance for all channels caused round-trip tests to either
# pass trivially (tolerance too loose) or fail on numeric noise (too tight).
_DEFAULT_CHANNEL_TOLERANCES: dict[str, float] = {
    "height":   0.01,    # metres — sub-centimetre is negligible
    "slope":    0.001,   # radians
    "wetness":  0.001,
    "curvature": 0.001,
    "drainage": 0.001,
    "erosion_amount": 0.001,
    "deposition_amount": 0.001,
}
_DEFAULT_RTOL: float = 1e-5


def compare_against_golden(
    stack: TerrainMaskStack,
    golden: GoldenSnapshot,
    tolerance: float = 0.0,
    *,
    golden_dir: Optional[Path] = None,
    strict_contract: bool = False,
    rtol: float = _DEFAULT_RTOL,
    channel_tolerances: Optional[dict] = None,
) -> List[ValidationIssue]:
    """Compare a fresh stack against a stored golden.

    BUG-R8-A9-025: when ``tolerance > 0`` and hashes differ, load the
    companion ``.golden.npz`` and use ``np.allclose(atol=tolerance)`` per
    channel before raising a hard failure — allowing intentional minor
    floating-point drift to pass.

    BUG-R8-A9-024: channels present in ``current`` but absent in ``golden``
    are emitted as soft ``GOLDEN_CHANNEL_NEW`` issues.

    P1-34: ``channel_tolerances`` is a dict keyed by channel name with
    channel-appropriate absolute tolerances.  Falls back to ``tolerance``
    (scalar) for channels not in the dict.  ``rtol`` defaults to ``1e-5``.
    """
    # Build the effective per-channel tolerance map.
    _ch_tol: dict[str, float] = dict(_DEFAULT_CHANNEL_TOLERANCES)
    if channel_tolerances:
        _ch_tol.update(channel_tolerances)
    issues: List[ValidationIssue] = []
    current_hash = stack.compute_hash()
    hash_match = current_hash == golden.content_hash
    tolerance_close_channels: set[str] = set()

    if not hash_match:
        # BUG-R8-A9-025: tolerance path — load npz and compare with np.allclose
        tolerance_passed = False
        if tolerance > 0.0:
            npz_path = (
                Path(golden.npz_path)
                if golden.npz_path
                else (
                    Path(golden_dir) / f"{golden.snapshot_id}.golden.npz"
                    if golden_dir is not None
                    else Path(f"{golden.snapshot_id}.golden.npz")
                )
            )
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
                        # P1-34: use per-channel atol; fall back to scalar tolerance.
                        _atol = _ch_tol.get(ch, tolerance)
                        if not np.allclose(np.asarray(cur_arr), np.asarray(gld_arr), atol=_atol, rtol=rtol):
                            all_close = False
                            break
                        tolerance_close_channels.add(ch)
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
            if tolerance > 0.0 and ch in tolerance_close_channels:
                continue
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

    # BUG-R8-A9-024: emit drift issue for channels in current but absent in golden.
    # In strict release gates, export/semantic channels are hard failures because
    # a stale golden can otherwise bless a tile that lost water/material/nav data.
    for ch in current_channels:
        if ch not in golden.channel_hashes:
            severity = "hard" if strict_contract and ch in _STRICT_GOLDEN_CHANNELS else "soft"
            issues.append(
                ValidationIssue(
                    code="GOLDEN_NEW_CHANNEL",
                    severity=severity,
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
                severity="hard" if strict_contract else "soft",
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
    # FIX-D24-PR12: atomic write so partial library-bake crashes don't
    # leave a corrupt golden_library_manifest.json on disk.
    atomic_write_text(
        manifest_path,
        # T0.5-8b (Y04 v3 §P.8.2): allow_nan=False — loud-at-source for the
        # golden-library manifest (sibling to the per-snapshot json above).
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
            allow_nan=False,
        ),
    )
    return snapshots


# ---------------------------------------------------------------------------
# V-2: Scenario-based golden checks
# ---------------------------------------------------------------------------

# Each entry is a scenario spec.  Older specs may still use one channel plus a
# named scenario; structured specs use required_channels, channel_assertions,
# and semantic_assertions.  The structured path is the release-grade gate: it
# catches pretty-but-wrong terrain where channels exist but do not agree.
_CHANNEL_ALIASES: Dict[str, Tuple[str, ...]] = {
    "heightmap": ("height",),
    "cliff_mask": ("cliff_candidate",),
    "water_surface": ("water_surface_elevation_m", "water_surface_mask"),
}


SCENARIO_GOLDENS: Dict[str, Dict[str, Any]] = {
    "water_present": {
        "description": "Water has presence, depth, elevation, and mask/depth agreement.",
        "required_channels": [
            "height",
            "water_surface_mask",
            "water_surface_elevation_m",
            "water_depth_m",
        ],
        "channel_assertions": {
            "water_surface_mask": {"range": [0.0, 1.0], "min_nonzero_cells": 1},
            "water_depth_m": {"range": [0.0, 500.0], "min_peak": 0.01},
            "water_surface_elevation_m": {"range": [0.0, 9000.0]},
        },
        "semantic_assertions": [
            {
                "type": "depth_requires_water_mask",
                "depth_channel": "water_depth_m",
                "mask_channel": "water_surface_mask",
                "depth_threshold": 0.01,
                "mask_threshold": 0.01,
                "min_ratio": 0.98,
            },
            {
                "type": "water_surface_above_terrain",
                "height_channel": "height",
                "surface_channel": "water_surface_elevation_m",
                "mask_channel": "water_surface_mask",
                "min_ratio": 0.98,
            },
        ],
    },
    "cliff_present": {
        "description": "Cliffs have footprint and slope alignment.",
        "required_channels": ["height", "cliff_mask", "slope"],
        "channel_assertions": {
            "height": {"min_relief_m": 1.0},
            "cliff_mask": {"range": [0.0, 1.0], "min_nonzero_cells": 1},
            "slope": {"range": [0.0, 90.0]},
        },
        "semantic_assertions": [
            {
                "type": "cliff_slope_alignment",
                "cliff_channel": "cliff_mask",
                "slope_channel": "slope",
                "min_slope": 30.0,
                "min_ratio": 0.5,
            },
        ],
    },
    "heightmap_range": {
        "description": "Terrain has non-flat world-unit relief and slope energy.",
        "required_channels": ["height"],
        "channel_assertions": {
            "height": {"range": [0.0, 9000.0], "min_relief_m": 50.0, "min_gradient_p95": 0.25},
        },
    },
    "no_water_seam": {
        "description": "Water depth edges are continuous enough for adjacent tiles.",
        "required_channels": ["water_depth_m"],
        "channel_assertions": {
            "water_depth_m": {"range": [0.0, 500.0], "max_edge_std": 0.2},
        },
    },
}


def _stack_channel(stack: Any, channel: str) -> tuple[Optional[np.ndarray], str, Optional[str]]:
    """Resolve a named channel with canonical aliases and return array/error."""
    candidates = (channel, *_CHANNEL_ALIASES.get(channel, ()))
    for candidate in candidates:
        value = None
        if hasattr(stack, "get"):
            try:
                value = stack.get(candidate)
            except Exception:
                value = None
        if value is None:
            value = getattr(stack, candidate, None)
        if value is None:
            continue
        try:
            arr = np.asarray(value, dtype=np.float64)
        except Exception as exc:
            return None, candidate, f"channel '{candidate}' is not array-like: {exc}"
        if arr.size == 0:
            return None, candidate, f"channel '{candidate}' is empty"
        if not np.isfinite(arr).all():
            return None, candidate, f"channel '{candidate}' contains non-finite values"
        return arr, candidate, None
    return None, channel, f"channel '{channel}' missing from stack"


def _edge_values(arr: np.ndarray) -> np.ndarray:
    if arr.ndim < 2:
        return arr.ravel()
    return np.concatenate(
        [arr[0, :].ravel(), arr[-1, :].ravel(), arr[:, 0].ravel(), arr[:, -1].ravel()]
    )


def _gradient_p95(arr: np.ndarray) -> float:
    if arr.ndim != 2 or min(arr.shape) < 2:
        return 0.0
    gy, gx = np.gradient(arr)
    mag = np.hypot(gx, gy)
    return float(np.percentile(mag, 95))


# ---------------------------------------------------------------------------
# T0.5-5 (Y04 v3 §P.8.2 / Part P §P.3): per-channel unit normaliser
#
# Closes ZZ4-A6 R5 (Shape C — "misdirected"). Assertion keys like
# ``max_value_m`` / ``min_value_m`` / ``min_relief_m`` carry an implicit unit
# (the ``_m`` suffix = meters). If a channel is documented in a different
# unit (e.g. ``slope`` in radians, ``rotation_y_rad`` in radians,
# ``vb_aspect_deg`` in degrees), comparing the raw channel value against a
# meters-suffixed threshold silently misdirects the assertion.
#
# This registry pins the canonical unit per channel. The
# ``_channel_unit_mismatch`` helper (paired with ``_assertion_unit_for_key``)
# below is wired into ``_evaluate_channel_assertion`` so a mismatch is
# flagged LOUDLY rather than silently producing a wrong-unit pass/fail
# verdict.
#
# Adding a new channel: append to ``_CHANNEL_CANONICAL_UNITS``. If the unit
# is unknown / dimensionless, use ``"dimensionless"`` so the helper can
# distinguish "registered with no unit" from "not registered".
_CHANNEL_CANONICAL_UNITS: dict[str, str] = {
    # Heights / depths / elevations — all meters.
    "height": "m",
    "water_depth_m": "m",
    "water_surface_elevation_m": "m",
    "bathymetry": "m",
    "terrain_displacement": "m",
    "sediment_height": "m",
    "bedrock_height": "m",
    # Rotation / angular — radians (Python-side; rad↔deg conversion happens
    # at the Unity boundary per T0-4.5 / T0.5-4).
    "slope": "rad",
    "rotation_y_rad": "rad",
    "strata_orientation": "rad",
    "flow_direction": "rad",
    # Degrees — degrees-native channels.
    "vb_aspect_deg": "deg",
    # Per-cell counts and densities — dimensionless [0, 1] or counts.
    "wetness": "dimensionless",
    "drainage": "dimensionless",
    "foam": "dimensionless",
    "mist": "dimensionless",
    "wet_rock": "dimensionless",
    "macro_color": "dimensionless",
    "talus": "dimensionless",
    "grass_density_map": "dimensionless",
    "snow_coverage": "dimensionless",
    "terrain_brucks_weight": "dimensionless",
    "cliff_candidate": "dimensionless",
    "cliff_mask": "dimensionless",
    "biome_id": "dimensionless",
    "navmesh_area_id": "dimensionless",
}

# Map assertion-key suffix → canonical unit string.
_ASSERTION_SUFFIX_TO_UNIT: dict[str, str] = {
    "_m": "m",
    "_rad": "rad",
    "_deg": "deg",
}


def _assertion_unit_for_key(key: str) -> str | None:
    """Return the unit declared by the assertion key suffix, or None."""
    for suffix, unit in _ASSERTION_SUFFIX_TO_UNIT.items():
        if key.endswith(suffix):
            return unit
    return None


def _channel_unit_mismatch(channel: str, assertion_key: str) -> str | None:
    """Return a diagnostic if the assertion key's unit mismatches the
    channel's canonical unit; ``None`` if units match OR channel is not in
    the registry (untracked channels default to legacy-permissive).
    """
    expected = _CHANNEL_CANONICAL_UNITS.get(channel)
    if expected is None:
        return None  # unregistered — legacy-permissive (do not break)
    asserted = _assertion_unit_for_key(assertion_key)
    if asserted is None:
        return None  # assertion key has no unit-bearing suffix
    if expected == asserted:
        return None
    return (
        f"channel '{channel}' is registered as unit={expected!r} but the "
        f"assertion key {assertion_key!r} declares unit={asserted!r} via "
        f"its suffix — unit drift hazard per ZZ4-A6 R5 (Shape C). "
        f"Use the matching-suffix key or update _CHANNEL_CANONICAL_UNITS "
        f"in terrain_golden_snapshots.py if the channel's unit changed."
    )


def _within_radius(source_mask: np.ndarray, target_mask: np.ndarray, radius: int) -> np.ndarray:
    source = np.asarray(source_mask, dtype=bool)
    target = np.asarray(target_mask, dtype=bool)
    if source.shape != target.shape:
        return np.zeros_like(source, dtype=bool)
    radius = max(0, int(radius))
    if radius == 0:
        return source & target
    padded = np.pad(target, radius, mode="constant", constant_values=False)
    near = np.zeros_like(target, dtype=bool)
    rows, cols = target.shape
    for dr in range(2 * radius + 1):
        for dc in range(2 * radius + 1):
            near |= padded[dr : dr + rows, dc : dc + cols]
    return source & near


def _evaluate_channel_assertion(
    stack: Any,
    channel: str,
    assertion: Dict[str, Any],
) -> tuple[bool, List[str], Dict[str, Any]]:
    arr, resolved, error = _stack_channel(stack, channel)
    if error is not None or arr is None:
        return False, [error or f"channel '{channel}' missing from stack"], {}

    stats: Dict[str, Any] = {
        "channel": resolved,
        "min": float(np.nanmin(arr)),
        "max": float(np.nanmax(arr)),
        "mean": float(np.nanmean(arr)),
        "nonzero_cells": int(np.count_nonzero(arr > float(assertion.get("nonzero_threshold", 0.0)))),
        "relief": float(np.nanmax(arr) - np.nanmin(arr)),
    }
    issues: List[str] = []

    # T0.5-5 (Y04 v3 §P.8.2 / Part P §P.3): unit-drift gate.
    # Scan every assertion key for a unit-bearing suffix and confirm the
    # channel's canonical unit matches. Catches Shape C "misdirected"
    # assertions where e.g. a radians-channel gets compared against a
    # meters-suffixed threshold.
    #
    # Check BOTH the requested ``channel`` name AND the alias-resolved
    # ``resolved`` name. ``_CHANNEL_ALIASES`` lets callers ask for e.g.
    # ``heightmap`` while the stack stores ``height``; we want unit-drift
    # protection regardless of which name the caller used. First match
    # wins; both ``None`` returns mean no drift.
    for assertion_key in assertion:
        mismatch = _channel_unit_mismatch(channel, assertion_key)
        if mismatch is None and resolved != channel:
            mismatch = _channel_unit_mismatch(resolved, assertion_key)
        if mismatch is not None:
            issues.append(f"{channel}:unit_drift {mismatch}")

    if "range" in assertion:
        lo, hi = assertion["range"]
        if stats["min"] < float(lo) or stats["max"] > float(hi):
            issues.append(
                f"{channel}:range [{stats['min']:.4f},{stats['max']:.4f}] outside [{float(lo):.4f},{float(hi):.4f}]"
            )
    if "min_nonzero_cells" in assertion and stats["nonzero_cells"] < int(assertion["min_nonzero_cells"]):
        issues.append(f"{channel}:nonzero_cells {stats['nonzero_cells']} < {int(assertion['min_nonzero_cells'])}")
    if "min_nonzero_ratio" in assertion:
        ratio = stats["nonzero_cells"] / float(arr.size)
        stats["nonzero_ratio"] = ratio
        if ratio < float(assertion["min_nonzero_ratio"]):
            issues.append(f"{channel}:nonzero_ratio {ratio:.4f} < {float(assertion['min_nonzero_ratio']):.4f}")
    # T0.5-5 codex P1 follow-up: also evaluate ``_rad`` / ``_deg`` keys so
    # callers who follow the unit-drift diagnostic and rename to a matching
    # angular suffix actually get their bound checked. Previously only
    # ``_m`` keys were evaluated, so a renamed ``max_value_rad`` silently
    # stopped enforcing any bound on the channel.
    if "max_value_m" in assertion and stats["max"] > float(assertion["max_value_m"]):
        issues.append(f"{channel}:max {stats['max']:.4f} > {float(assertion['max_value_m']):.4f}")
    if "min_value_m" in assertion and stats["min"] < float(assertion["min_value_m"]):
        issues.append(f"{channel}:min {stats['min']:.4f} < {float(assertion['min_value_m']):.4f}")
    if "max_value_rad" in assertion and stats["max"] > float(assertion["max_value_rad"]):
        issues.append(f"{channel}:max {stats['max']:.4f} > {float(assertion['max_value_rad']):.4f}")
    if "min_value_rad" in assertion and stats["min"] < float(assertion["min_value_rad"]):
        issues.append(f"{channel}:min {stats['min']:.4f} < {float(assertion['min_value_rad']):.4f}")
    if "max_value_deg" in assertion and stats["max"] > float(assertion["max_value_deg"]):
        issues.append(f"{channel}:max {stats['max']:.4f} > {float(assertion['max_value_deg']):.4f}")
    if "min_value_deg" in assertion and stats["min"] < float(assertion["min_value_deg"]):
        issues.append(f"{channel}:min {stats['min']:.4f} < {float(assertion['min_value_deg']):.4f}")
    if "min_peak" in assertion and stats["max"] < float(assertion["min_peak"]):
        issues.append(f"{channel}:peak {stats['max']:.4f} < {float(assertion['min_peak']):.4f}")
    if "min_mean" in assertion and stats["mean"] < float(assertion["min_mean"]):
        issues.append(f"{channel}:mean {stats['mean']:.4f} < {float(assertion['min_mean']):.4f}")
    if "max_mean" in assertion and stats["mean"] > float(assertion["max_mean"]):
        issues.append(f"{channel}:mean {stats['mean']:.4f} > {float(assertion['max_mean']):.4f}")
    if "min_relief_m" in assertion and stats["relief"] < float(assertion["min_relief_m"]):
        issues.append(f"{channel}:relief {stats['relief']:.4f} < {float(assertion['min_relief_m']):.4f}")
    if "max_edge_std" in assertion:
        edge_std = float(np.nanstd(_edge_values(arr)))
        stats["edge_std"] = edge_std
        if edge_std > float(assertion["max_edge_std"]):
            issues.append(f"{channel}:edge_std {edge_std:.4f} > {float(assertion['max_edge_std']):.4f}")
    if "min_gradient_p95" in assertion:
        grad = _gradient_p95(arr)
        stats["gradient_p95"] = grad
        if grad < float(assertion["min_gradient_p95"]):
            issues.append(f"{channel}:gradient_p95 {grad:.4f} < {float(assertion['min_gradient_p95']):.4f}")
    if "min_band_count" in assertion:
        threshold = float(assertion.get("band_threshold", 0.01))
        bins = int(assertion.get("band_bins", 16))
        active = arr[arr > threshold]
        band_count = int(np.unique(np.round(active * bins)).size) if active.size else 0
        stats["band_count"] = band_count
        if band_count < int(assertion["min_band_count"]):
            issues.append(f"{channel}:band_count {band_count} < {int(assertion['min_band_count'])}")

    return not issues, issues, stats


def _evaluate_semantic_assertion(stack: Any, assertion: Dict[str, Any]) -> tuple[bool, str, Dict[str, Any]]:
    kind = str(assertion.get("type", ""))

    def channel(name: str) -> tuple[Optional[np.ndarray], Optional[str]]:
        arr, _, err = _stack_channel(stack, name)
        return arr, err

    if kind == "depth_requires_water_mask":
        depth, err = channel(str(assertion.get("depth_channel", "water_depth_m")))
        if err or depth is None:
            return False, err or "missing depth channel", {}
        mask, err = channel(str(assertion.get("mask_channel", "water_surface_mask")))
        if err or mask is None:
            return False, err or "missing mask channel", {}
        if depth.shape != mask.shape:
            return False, f"depth/mask shape mismatch {depth.shape} != {mask.shape}", {}
        wet_depth = depth > float(assertion.get("depth_threshold", 0.01))
        if not wet_depth.any():
            return False, "no depth cells above threshold", {"depth_cells": 0}
        ratio = float((mask[wet_depth] > float(assertion.get("mask_threshold", 0.01))).mean())
        ok = ratio >= float(assertion.get("min_ratio", 0.98))
        return ok, f"depth_mask_ratio={ratio:.4f}", {"ratio": ratio, "depth_cells": int(wet_depth.sum())}

    if kind == "water_surface_above_terrain":
        height, err = channel(str(assertion.get("height_channel", "height")))
        if err or height is None:
            return False, err or "missing height channel", {}
        surface, err = channel(str(assertion.get("surface_channel", "water_surface_elevation_m")))
        if err or surface is None:
            return False, err or "missing surface channel", {}
        mask, err = channel(str(assertion.get("mask_channel", "water_surface_mask")))
        if err or mask is None:
            return False, err or "missing mask channel", {}
        if height.shape != surface.shape or height.shape != mask.shape:
            return False, "height/surface/mask shape mismatch", {}
        wet = mask > float(assertion.get("mask_threshold", 0.01))
        if not wet.any():
            return False, "no wet cells for surface/terrain comparison", {"wet_cells": 0}
        tolerance = float(assertion.get("tolerance_m", 0.05))
        ratio = float((surface[wet] + tolerance >= height[wet]).mean())
        ok = ratio >= float(assertion.get("min_ratio", 0.98))
        return ok, f"surface_above_height_ratio={ratio:.4f}", {"ratio": ratio, "wet_cells": int(wet.sum())}

    if kind == "shoreline_borders_water":
        water, err = channel(str(assertion.get("water_channel", "water_surface_mask")))
        if err or water is None:
            return False, err or "missing water channel", {}
        shore, err = channel(str(assertion.get("shoreline_channel", "shoreline_blend")))
        if err or shore is None:
            return False, err or "missing shoreline channel", {}
        if water.shape != shore.shape or water.ndim != 2:
            return False, "water/shoreline shape mismatch or non-2D", {}
        wet = water > float(assertion.get("water_threshold", 0.01))
        if not wet.any() or wet.all():
            return False, "water mask has no shoreline boundary", {"wet_cells": int(wet.sum())}
        padded = np.pad(wet, 1, mode="edge")
        neighbor_wet = np.zeros_like(wet, dtype=bool)
        neighbor_dry = np.zeros_like(wet, dtype=bool)
        rows, cols = wet.shape
        for dr in range(3):
            for dc in range(3):
                window = padded[dr : dr + rows, dc : dc + cols]
                neighbor_wet |= window
                neighbor_dry |= ~window
        boundary = neighbor_wet & neighbor_dry
        min_cells = int(assertion.get("min_boundary_cells", 1))
        if int(boundary.sum()) < min_cells:
            return False, f"shoreline boundary cells {int(boundary.sum())} < {min_cells}", {}
        ratio = float((shore[boundary] > float(assertion.get("shoreline_threshold", 0.01))).mean())
        ok = ratio >= float(assertion.get("min_ratio", 0.5))
        return ok, f"shoreline_boundary_ratio={ratio:.4f}", {"ratio": ratio, "boundary_cells": int(boundary.sum())}

    if kind == "cliff_slope_alignment":
        cliff, err = channel(str(assertion.get("cliff_channel", "cliff_mask")))
        if err or cliff is None:
            return False, err or "missing cliff channel", {}
        slope, err = channel(str(assertion.get("slope_channel", "slope")))
        if err or slope is None:
            return False, err or "missing slope channel", {}
        if cliff.shape != slope.shape:
            return False, f"cliff/slope shape mismatch {cliff.shape} != {slope.shape}", {}
        cliff_cells = cliff > float(assertion.get("cliff_threshold", 0.5))
        if not cliff_cells.any():
            return False, "no cliff cells above threshold", {"cliff_cells": 0}
        ratio = float((slope[cliff_cells] >= float(assertion.get("min_slope", 30.0))).mean())
        ok = ratio >= float(assertion.get("min_ratio", 0.5))
        return ok, f"cliff_slope_ratio={ratio:.4f}", {"ratio": ratio, "cliff_cells": int(cliff_cells.sum())}

    if kind in {"talus_near_cliff", "cave_framed_by_cliff", "pool_near_cliff", "foam_near_water"}:
        source_name = str(
            assertion.get(
                "source_channel",
                {
                    "talus_near_cliff": "talus_mask",
                    "cave_framed_by_cliff": "cave_candidate",
                    "pool_near_cliff": "water_depth_m",
                    "foam_near_water": "foam",
                }[kind],
            )
        )
        target_name = str(
            assertion.get(
                "target_channel",
                {
                    "talus_near_cliff": "cliff_mask",
                    "cave_framed_by_cliff": "cliff_mask",
                    "pool_near_cliff": "cliff_mask",
                    "foam_near_water": "water_surface_mask",
                }[kind],
            )
        )
        source, err = channel(source_name)
        if err or source is None:
            return False, err or f"missing {source_name}", {}
        target, err = channel(target_name)
        if err or target is None:
            return False, err or f"missing {target_name}", {}
        if source.shape != target.shape or source.ndim != 2:
            return False, f"{source_name}/{target_name} shape mismatch or non-2D", {}
        source_mask = source > float(assertion.get("source_threshold", 0.01))
        if not source_mask.any():
            return False, f"no {source_name} cells above threshold", {"source_cells": 0}
        target_mask = target > float(assertion.get("target_threshold", 0.01))
        near = _within_radius(source_mask, target_mask, int(assertion.get("radius", 2)))
        ratio = float(near.sum()) / float(source_mask.sum())
        ok = ratio >= float(assertion.get("min_ratio", 0.75))
        return ok, f"{kind}_ratio={ratio:.4f}", {"ratio": ratio, "source_cells": int(source_mask.sum())}

    if kind == "flow_reaches_pool":
        flow, err = channel(str(assertion.get("flow_channel", "flow_accumulation")))
        if err or flow is None:
            return False, err or "missing flow channel", {}
        pool, err = channel(str(assertion.get("pool_channel", "water_depth_m")))
        if err or pool is None:
            return False, err or "missing pool channel", {}
        if flow.shape != pool.shape:
            return False, "flow/pool shape mismatch", {}
        pool_mask = pool > float(assertion.get("pool_depth_threshold", 0.01))
        if not pool_mask.any():
            return False, "no pool cells above threshold", {"pool_cells": 0}
        flow_near_pool = _within_radius(pool_mask, flow > float(assertion.get("min_flow", 0.01)), int(assertion.get("radius", 2)))
        ratio = float(flow_near_pool.sum()) / float(pool_mask.sum())
        ok = ratio >= float(assertion.get("min_ratio", 0.5))
        return ok, f"flow_pool_ratio={ratio:.4f}", {"ratio": ratio, "pool_cells": int(pool_mask.sum())}

    if kind == "strata_band_count":
        ch = str(assertion.get("channel", "strata_mask"))
        ok, issues, stats = _evaluate_channel_assertion(
            stack,
            ch,
            {
                "range": assertion.get("range", [0.0, 1.0]),
                "min_band_count": assertion.get("min_band_count", assertion.get("min_bands", 3)),
                "band_threshold": assertion.get("band_threshold", 0.01),
                "band_bins": assertion.get("band_bins", 16),
            },
        )
        return ok, "; ".join(issues) if issues else f"band_count={stats.get('band_count', 0)}", stats

    return False, f"unknown semantic assertion type '{kind}'", {}


def _run_scenario(name: str, spec: Dict[str, Any], stack: Any) -> Dict[str, Any]:
    """Run a single named scenario check against *stack*; return {ok, reason}."""
    if "required_channels" in spec or "channel_assertions" in spec or "semantic_assertions" in spec:
        issues: List[str] = []
        metrics: Dict[str, Any] = {}

        for channel in spec.get("required_channels", []):
            _, resolved, error = _stack_channel(stack, str(channel))
            if error is not None:
                issues.append(f"required:{channel}:{error}")
            else:
                metrics.setdefault("required_channels", {})[str(channel)] = resolved

        for channel, assertion in dict(spec.get("channel_assertions", {})).items():
            ok, channel_issues, stats = _evaluate_channel_assertion(stack, str(channel), dict(assertion or {}))
            metrics.setdefault("channels", {})[str(channel)] = stats
            if not ok:
                issues.extend(channel_issues)

        for assertion in list(spec.get("semantic_assertions", [])):
            ok, reason, assertion_metrics = _evaluate_semantic_assertion(stack, dict(assertion or {}))
            assertion_name = str((assertion or {}).get("type", "semantic"))
            metrics.setdefault("semantic", {})[assertion_name] = assertion_metrics
            if not ok:
                issues.append(f"{assertion_name}:{reason}")

        return {
            "ok": not issues,
            "reason": "pass" if not issues else "; ".join(issues[:8]),
            "issues": issues,
            "metrics": metrics,
            "description": spec.get("description", ""),
        }

    channel: str = spec["channel"]
    arr, _, error = _stack_channel(stack, channel)
    if error is not None or arr is None:
        return {"ok": False, "reason": error or f"channel '{channel}' missing from stack"}

    if name == "water_present":
        mean_val = float(np.nanmean(arr))
        ok = mean_val > 0.01
        reason = f"mean={mean_val:.4f} ({'pass' if ok else 'fail, need > 0.01'})"
        return {"ok": ok, "reason": reason}

    if name == "cliff_present":
        max_val = float(np.nanmax(arr))
        ok = max_val > 0.5
        reason = f"max={max_val:.4f} ({'pass' if ok else 'fail, need > 0.5'})"
        return {"ok": ok, "reason": reason}

    if name == "heightmap_range":
        relief = float(np.nanmax(arr)) - float(np.nanmin(arr))
        ok = relief > 50.0
        reason = f"relief={relief:.2f} ({'pass' if ok else 'fail, need > 50.0'})"
        return {"ok": ok, "reason": reason}

    if name == "no_water_seam":
        # Check that edge rows/cols have low std (no abrupt discontinuity)
        if arr.ndim < 2:
            return {"ok": False, "reason": "array must be 2-D for seam check"}
        edge_values = np.concatenate([
            arr[0, :].ravel(),
            arr[-1, :].ravel(),
            arr[:, 0].ravel(),
            arr[:, -1].ravel(),
        ])
        edge_std = float(np.nanstd(edge_values))
        ok = edge_std < 0.2
        reason = f"edge_std={edge_std:.4f} ({'pass' if ok else 'fail, need < 0.2'})"
        return {"ok": ok, "reason": reason}

    return {"ok": False, "reason": f"unknown scenario '{name}'"}


def run_scenario_goldens(
    stack: Any,
    scenarios: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Iterate scenario goldens, run each check, and return a summary dict."""
    if scenarios is None:
        scenarios = SCENARIO_GOLDENS

    results: Dict[str, Dict[str, Any]] = {}
    passed = 0
    failed = 0

    for name, spec in scenarios.items():
        outcome = _run_scenario(name, spec, stack)
        results[name] = outcome
        if outcome.get("ok"):
            passed += 1
        else:
            failed += 1

    return {
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "results": results,
    }


def handle_run_scenario_goldens(
    stack: Any,
    scenarios: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Handler wrapper for run_scenario_goldens with try/except."""
    try:
        result = run_scenario_goldens(stack, scenarios=scenarios)
        return {
            "status": "ok",
            **result,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc), "passed": 0, "failed": 0, "total": 0, "results": {}}


__all__ = [
    "PIPELINE_VERSION",
    "GoldenSnapshot",
    "save_golden_snapshot",
    "load_golden_snapshot",
    "compare_against_golden",
    "seed_golden_library",
    "SCENARIO_GOLDENS",
    "run_scenario_goldens",
    "handle_run_scenario_goldens",
]
