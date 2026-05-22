"""Command-line entry points for deterministic terrain artifact generation."""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from hashlib import sha256
from pathlib import Path
from typing import Sequence

import numpy as np

from .handlers._terrain_noise import compute_slope_map_degrees, generate_heightmap


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind)
    crc = zlib.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _write_rgba_png(path: Path, rgba: np.ndarray) -> None:
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("rgba PNG input must have shape (H, W, 4)")
    image = np.ascontiguousarray(rgba, dtype=np.uint8)
    height, width, _ = image.shape
    raw = b"".join(b"\x00" + image[row].tobytes() for row in range(height))
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0),
        )
        + _png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + _png_chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def _normalize_u16(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    lo = float(np.nanmin(arr))
    hi = float(np.nanmax(arr))
    if not np.isfinite(lo) or not np.isfinite(hi):
        raise ValueError("heightmap contains non-finite values")
    if hi <= lo:
        return np.zeros(arr.shape, dtype="<u2")
    norm = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    return np.rint(norm * 65535.0).astype("<u2")


def _artifact_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# T0-2 (Y04 v3 / S01-P0-RT-02 / γ3 D-01): CLI pipeline rewire
# ---------------------------------------------------------------------------
# Prior CLI called ``generate_heightmap`` + ``compute_slope_map_degrees``
# directly. This bypassed the entire ``TerrainPassController.run_pipeline()``
# orchestrator — biome channels, structural masks, validation, provenance,
# and the populated_by_pass ledger were never produced when invoking
# ``python -m veilbreakers_terrain.cli generate_tile``. Tests against the
# CLI therefore only asserted determinism of the stub path, never of the
# real pipeline.
#
# Per FIX_PATTERN_v1 §C7 small, we now route every CLI bake through the
# real controller using a minimal scene-read-free pass sequence (the same
# 6-pass default selected by ``_execute_terrain_pipeline`` when no
# scene_read is attached, see ``handlers/environment.py:2852-2859``). The
# heightmap that was previously written verbatim becomes the input to the
# pipeline's ``TerrainMaskStack.height`` channel; the final stack's
# ``compute_hash()`` is recorded in the manifest as
# ``final_mask_stack_hash`` so callers can verify the orchestrator
# actually ran (a stub bypass would either fail to produce the hash or
# emit one whose constituent channels are missing).
def _run_real_pipeline_for_cli(
    *,
    height: np.ndarray,
    seed: int,
    tile_size: int,
    cell_size: float,
    world_origin_x: float,
    world_origin_y: float,
    tile_x: int,
    tile_y: int,
) -> dict[str, object]:
    """Execute the real ``TerrainPassController.run_pipeline()`` for the CLI.

    Returns a dict with:

    - ``final_mask_stack_hash`` -- ``stack.compute_hash()`` after the
      pipeline finishes. Deterministic for fixed inputs.
    - ``pass_sequence`` -- ordered list of pass names that were actually
      executed by the orchestrator (proof the controller ran, not a stub).
    - ``populated_channels`` -- sorted channel names that any pass wrote
      to ``populated_by_pass`` (further proof channels exist beyond the
      caller-provided height).
    - ``pipeline_status`` -- terminal status of the last pass.
    """
    # Local imports to keep ``argparse`` startup cheap and to avoid hard
    # dependencies on the handlers package at module import time (the CLI
    # is also imported by tests that monkey-patch handler internals).
    from .handlers.terrain_master_registrar import register_all_terrain_passes
    from .handlers.terrain_pipeline import TerrainPassController
    from .handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    # Ensure the canonical pass registry is loaded.  ``strict=False`` so
    # repeat CLI invocations in the same Python session do not crash on
    # duplicate registration.
    register_all_terrain_passes(strict=False)

    region_bounds = BBox(
        min_x=float(world_origin_x),
        min_y=float(world_origin_y),
        max_x=float(world_origin_x) + float(tile_size) * float(cell_size),
        max_y=float(world_origin_y) + float(tile_size) * float(cell_size),
    )

    mask_stack = TerrainMaskStack(
        tile_size=int(tile_size),
        cell_size=float(cell_size),
        world_origin_x=float(world_origin_x),
        world_origin_y=float(world_origin_y),
        tile_x=int(tile_x),
        tile_y=int(tile_y),
        height=np.ascontiguousarray(np.asarray(height, dtype=np.float64)),
    )

    intent = TerrainIntentState(
        seed=int(seed),
        region_bounds=region_bounds,
        tile_size=int(tile_size),
        cell_size=float(cell_size),
        quality_profile="preview",  # CLI bakes don't have scene_read; use preview profile.
        noise_profile="mountains",
        erosion_profile="temperate",
    )

    state = TerrainPipelineState(intent=intent, mask_stack=mask_stack)
    controller = TerrainPassController(state)

    # Minimal scene-read-free pass sequence (mirrors the default selected
    # by environment.py:_execute_terrain_pipeline when scene_read is None).
    #
    # Round-2 (#119): sourced from the single-source-of-truth in
    # ``handlers._default_pass_sequences`` so the CLI runtime pipeline
    # cannot silently desync from the canonical extraction. The previous
    # inline literal was the third copy of this sequence in the codebase
    # (introduced post-V8-audit by PR #102 T0-2 CLI rewire) and was being
    # consumed as the actual runtime pipeline by ``run_pipeline``, not
    # just for registry pre-warm.
    from .handlers._default_pass_sequences import DEFAULT_CLI_PASS_SEQUENCE
    pass_sequence = list(DEFAULT_CLI_PASS_SEQUENCE)

    # checkpoint=False: do not write filesystem-side checkpoints from the
    # CLI bake (the manifest+heightmap+splatmap are the only artifacts the
    # CLI contract owns).
    results = controller.run_pipeline(
        intent=intent,
        pass_sequence=pass_sequence,
        checkpoint=False,
    )

    final_hash = controller.state.mask_stack.compute_hash()
    populated_channels = sorted(controller.state.mask_stack.populated_by_pass.keys())
    executed = [r.pass_name for r in results]
    terminal_status = results[-1].status if results else "no_passes_executed"

    return {
        "final_mask_stack_hash": final_hash,
        "pass_sequence": executed,
        "populated_channels": populated_channels,
        "pipeline_status": str(terminal_status),
    }


def _generate_tile(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Tile coordinates translate into a world-space origin offset so the
    # noise field samples the correct slice for this tile.  Without this
    # plumbing, --tile-x / --tile-y would be metadata-only and bakes for
    # different tiles would hash identically (PR #46 Codex/Copilot threads
    # 2 + 6).
    tile_x = int(getattr(args, "tile_x", 0) or 0)
    tile_y = int(getattr(args, "tile_y", 0) or 0)
    world_origin_x = float(tile_x) * float(args.size) * float(args.scale)
    world_origin_y = float(tile_y) * float(args.size) * float(args.scale)

    height = generate_heightmap(
        int(args.size),
        int(args.size),
        scale=float(args.scale),
        seed=int(args.seed),
        terrain_type=str(args.terrain_type),
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        normalize=True,
    )
    height_u16 = _normalize_u16(height)
    height_path = out_dir / "heightmap.bin"
    height_path.write_bytes(height_u16.tobytes(order="C"))

    slope = compute_slope_map_degrees(height.astype(np.float64))
    slope_u8 = np.clip(slope / max(float(np.max(slope)), 1e-6), 0.0, 1.0)
    h_u8 = (height_u16.astype(np.uint32) >> 8).astype(np.uint8)
    rgba = np.stack(
        [
            h_u8,
            np.rint(slope_u8 * 255.0).astype(np.uint8),
            np.uint8(255) - h_u8,
            np.full(height_u16.shape, 255, dtype=np.uint8),
        ],
        axis=-1,
    )
    splat_path = out_dir / "splatmap_0.png"
    _write_rgba_png(splat_path, rgba)

    # T0-2: route through the REAL TerrainPassController.run_pipeline()
    # so the CLI is no longer a noise-only stub.  Failure to load the
    # pass registry or execute the pipeline now hard-fails the CLI
    # (rather than silently producing artifacts that bypass every pass).
    # ``cell_size=1.0`` matches the default used by
    # ``handlers/environment.py:_execute_terrain_pipeline`` when callers
    # do not override it.
    pipeline_summary = _run_real_pipeline_for_cli(
        height=height.astype(np.float64),
        seed=int(args.seed),
        tile_size=int(args.size),
        cell_size=1.0,
        world_origin_x=world_origin_x,
        world_origin_y=world_origin_y,
        tile_x=tile_x,
        tile_y=tile_y,
    )

    manifest = {
        "seed": int(args.seed),
        "size": int(args.size),
        "scale": float(args.scale),
        "terrain_type": str(args.terrain_type),
        "tile_x": tile_x,
        "tile_y": tile_y,
        "world_origin_x": world_origin_x,
        "world_origin_y": world_origin_y,
        "artifacts": {
            "heightmap.bin": _artifact_sha256(height_path),
            "splatmap_0.png": _artifact_sha256(splat_path),
        },
        # T0-2: orchestrator-coverage proof.  Stub-bypass CLIs cannot
        # populate these fields, so a non-empty ``final_mask_stack_hash``
        # plus a non-empty ``pass_sequence`` is the regression-test
        # discriminator that the real pipeline executed.
        "final_mask_stack_hash": pipeline_summary["final_mask_stack_hash"],
        "pipeline_pass_sequence": pipeline_summary["pass_sequence"],
        "pipeline_populated_channels": pipeline_summary["populated_channels"],
        "pipeline_status": pipeline_summary["pipeline_status"],
    }
    manifest_path = out_dir / "manifest.json"
    # T1-4 (Y04 v3 ord 13 / γ1 ZZ3-NEW-P1-04): allow_nan=False — tile-bake
    # manifest is Unity-consumed; NaN/Inf in seed/size/scale/origin would
    # silently corrupt the artefact registry and produce mis-aligned tiles.
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    # REL-PR102-USERVIS-01 (CHECKPOINT-OPUS-ULTRA hotfix): the CLI previously
    # returned 0 unconditionally even when the orchestrator reported
    # ``pipeline_status == "failed"`` or ``"no_passes_executed"``. Manifest
    # is written for forensic purposes regardless (so downstream debuggers
    # can see what was attempted), but the exit code MUST surface the
    # failure to the calling shell / CI / make harness. Without this, a
    # broken pipeline pass appears to ship a green tile.
    failure_statuses = {"failed", "no_passes_executed"}
    if pipeline_summary.get("pipeline_status") in failure_statuses:
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="veilbreakers_terrain.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate_tile")
    gen.add_argument("--seed", type=int, required=True)
    gen.add_argument("--output-dir", required=True)
    gen.add_argument("--size", type=int, default=32)
    gen.add_argument("--scale", type=float, default=50.0)
    gen.add_argument("--terrain-type", default="mountains")
    # PR #46 threads 2 + 6: --tile-x / --tile-y must influence the bake so
    # different tile coordinates produce different artifact bytes.  Default
    # 0,0 keeps the existing call-site behaviour for the (0, 0) cell of
    # the GATE D25 matrix.
    gen.add_argument("--tile-x", dest="tile_x", type=int, default=0)
    gen.add_argument("--tile-y", dest="tile_y", type=int, default=0)
    gen.set_defaults(func=_generate_tile)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
