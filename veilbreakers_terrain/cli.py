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


def _generate_tile(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    height = generate_heightmap(
        int(args.size),
        int(args.size),
        scale=float(args.scale),
        seed=int(args.seed),
        terrain_type=str(args.terrain_type),
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

    manifest = {
        "seed": int(args.seed),
        "size": int(args.size),
        "scale": float(args.scale),
        "terrain_type": str(args.terrain_type),
        "artifacts": {
            "heightmap.bin": _artifact_sha256(height_path),
            "splatmap_0.png": _artifact_sha256(splat_path),
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
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
    gen.set_defaults(func=_generate_tile)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
