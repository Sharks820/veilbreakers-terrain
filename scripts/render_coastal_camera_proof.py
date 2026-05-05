"""Driver: render named cameras in the live Coastal Blender scene to PNGs
with non-black pixel proof. Writes ``RENDER_MANIFEST.json`` next to the PNGs.

Bypasses ``mcp__blender__.get_viewport_screenshot`` which returns black frames
on this Windows 11 + Blender 4.5 + MCP combination.

Plan reference:
    docs/plans/2026-05-04-001-feat-coastal-aaa-perfection-plan.md, U1.

Two run modes:

* **Direct** (default): connects to the live Blender on TCP ``127.0.0.1:9876``
  and dispatches via ``execute_code``. Requires the live Blender to have the
  current Coastal scene loaded.
* **Background**: invoked from inside Blender via
  ``blender --background <blend> --python scripts/render_coastal_camera_proof.py``
  — the script detects ``bpy`` is importable and renders directly.

Usage:

    python scripts/render_coastal_camera_proof.py \
        --unit-id u01_render_harness \
        --cameras VB_CORRECT_COASTAL_FULL_NODE_CAMERA,VB_CORRECT_COASTAL_SHORE_CAMERA,VB_CORRECT_COASTAL_PLAYER_CAMERA \
        --resolution 1600 900 --samples 64

Exit codes:
    0   all renders passed proof
    2   one or more renders failed proof or error
    3   bridge connection failed and bpy not available
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_BASE = REPO_ROOT / "renders" / "coastal"
BLENDER_HOST = "127.0.0.1"
BLENDER_PORT = 9876


def _try_inline_bpy_render(args: argparse.Namespace) -> int:
    """Render directly inside Blender (called when bpy is importable)."""
    from veilbreakers_terrain.handlers.visual_render_camera_proof import (
        render_camera_proof,
    )

    out_dir = (DEFAULT_OUT_BASE / args.unit_id).resolve()
    cameras = [c.strip() for c in args.cameras.split(",") if c.strip()]
    result = render_camera_proof(
        cameras=cameras,
        out_dir=str(out_dir),
        prefix=args.prefix,
        engine=args.engine,
        resolution=(args.resolution[0], args.resolution[1]),
        samples=args.samples,
        view_transform=args.view_transform,
        look=args.look,
        nonblack_threshold=args.nonblack_threshold,
        min_byte_size=args.min_byte_size,
        frame=args.frame,
        unit_id=args.unit_id,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 2


def _try_bridge_render(args: argparse.Namespace) -> int:
    """Dispatch render through the live Blender bridge on port 9876."""
    out_dir = (DEFAULT_OUT_BASE / args.unit_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cameras = [c.strip() for c in args.cameras.split(",") if c.strip()]

    code = textwrap.dedent(f"""
        import sys, json
        sys.path.insert(0, r"{REPO_ROOT.as_posix()}")
        from veilbreakers_terrain.handlers.visual_render_camera_proof import (
            render_camera_proof,
        )
        result = render_camera_proof(
            cameras={cameras!r},
            out_dir=r"{out_dir.as_posix()}",
            prefix={args.prefix!r},
            engine={args.engine!r},
            resolution=({args.resolution[0]}, {args.resolution[1]}),
            samples={args.samples},
            view_transform={args.view_transform!r},
            look={args.look!r},
            nonblack_threshold={args.nonblack_threshold},
            min_byte_size={args.min_byte_size},
            frame={args.frame!r},
            unit_id={args.unit_id!r},
        )
        print("VB_RENDER_PROOF_RESULT", json.dumps(result))
    """).strip()

    payload = {"type": "execute_code", "params": {"code": code}}
    try:
        with socket.create_connection((BLENDER_HOST, BLENDER_PORT), timeout=5) as sock:
            sock.settimeout(600)
            sock.sendall((json.dumps(payload) + "\n").encode())
            buf = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if b"VB_RENDER_PROOF_RESULT" in buf:
                    break
        text = buf.decode("utf-8", errors="replace")
    except OSError as exc:
        print(f"bridge connection failed: {exc}", file=sys.stderr)
        return 3

    print(text)
    # Parse the structured tail to determine pass/fail
    marker = "VB_RENDER_PROOF_RESULT"
    if marker in text:
        tail = text.rsplit(marker, 1)[-1].strip()
        try:
            # pull the first JSON object after the marker
            start = tail.find("{")
            end = tail.rfind("}")
            if 0 <= start < end:
                result = json.loads(tail[start : end + 1])
                return 0 if result.get("ok") else 2
        except json.JSONDecodeError:
            pass
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--unit-id", required=True,
                        help="Unit slug (e.g., u01_render_harness)")
    parser.add_argument("--cameras", required=True,
                        help="Comma-separated camera names")
    parser.add_argument("--prefix", default="",
                        help="Filename prefix prepended to each render")
    parser.add_argument("--engine", default="BLENDER_EEVEE_NEXT")
    parser.add_argument("--resolution", nargs=2, type=int, default=[1600, 900])
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--view-transform", default="Standard")
    parser.add_argument("--look", default="Medium High Contrast")
    parser.add_argument("--nonblack-threshold", type=float, default=0.005)
    parser.add_argument("--min-byte-size", type=int, default=50_000)
    parser.add_argument("--frame", type=int, default=None)
    parser.add_argument("--mode", choices=("auto", "bridge", "inline"), default="auto",
                        help="Force bridge or inline mode (default: auto-detect)")
    args = parser.parse_args(argv)

    inline_available = False
    if args.mode in ("auto", "inline"):
        try:
            import bpy  # noqa: F401  # type: ignore[import-not-found]
            inline_available = True
        except ImportError:
            inline_available = False

    if args.mode == "inline":
        if not inline_available:
            print("inline mode requested but bpy is not importable", file=sys.stderr)
            return 3
        return _try_inline_bpy_render(args)

    if args.mode == "bridge":
        return _try_bridge_render(args)

    # auto: prefer inline if running inside Blender, else bridge
    if inline_available:
        return _try_inline_bpy_render(args)
    return _try_bridge_render(args)


if __name__ == "__main__":
    raise SystemExit(main())
