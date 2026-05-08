"""GATE D25 — subprocess-determinism harness.

Closes Phase B by providing a single CLI entry-point used by the
``subprocess_determinism.yml`` GitHub Actions matrix to assert that the
deterministic terrain bake is **byte-identical** across two independent
subprocess invocations on the same OS / Python / seed.

Why subprocess instead of in-process?
-------------------------------------
The in-process determinism check (``run_determinism_check``) cannot detect
non-determinism caused by:

* Module-level globals seeded from time / PID / `os.urandom`.
* numpy's per-process default RNG state (``np.random.default_rng()``
  without a seed leaks state between calls).
* PYTHONHASHSEED-randomised ``hash()`` of strings/tuples used as set/dict
  keys when iteration order leaks into output (the previous "in-process
  determinism CI was theatre" critique — see
  ``feedback_audit_strictness.md``).

A subprocess matrix is the only reliable check: each call starts a fresh
interpreter, fresh module imports, fresh RNG state, and a fresh
PYTHONHASHSEED draw (when set to a fixed value, identical; when unset,
randomised — both reproducible across runs only if the bake is genuinely
seed-pure).

CLI contract
------------
::

    python -m veilbreakers_terrain.deterministic_bake_harness \\
        --seed=42 --tile=0,0 [--runs=2] [--size=32] [--scale=50.0] \\
        [--terrain-type=mountains]

Exit 0 if all ``runs`` independent subprocess bakes produce byte-identical
outputs; exit 1 if any pair diverges; exit 2 on configuration error.

Output is a JSON record on stdout::

    {
      "deterministic": true,
      "seed": 42,
      "tile": [0, 0],
      "run_count": 2,
      "hashes": ["<sha256>", "<sha256>"],
      "platform": "linux",
      "python_version": "3.12.5"
    }

This is the artefact the CI workflow's ``subprocess-determinism (18/18)``
matrix-summary check consumes.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from typing import Sequence

from .handlers.terrain_determinism_ci import run_determinism_check_subprocess


_EXIT_OK = 0
_EXIT_NONDETERMINISTIC = 1
_EXIT_CONFIG_ERROR = 2


def _parse_tile(value: str) -> tuple[int, int]:
    """Parse ``--tile=X,Y`` into a ``(tile_x, tile_y)`` int tuple."""
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"--tile must be 'X,Y' integer pair, got {value!r}"
        )
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--tile values must be integers, got {value!r}"
        ) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veilbreakers_terrain.deterministic_bake_harness",
        description=(
            "GATE D25 subprocess-determinism harness — runs the deterministic "
            "tile bake twice (or N times) in fresh subprocess interpreters and "
            "asserts byte-identical output across runs."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        required=True,
        help="Master RNG seed for the bake (e.g. 42, 7777).",
    )
    parser.add_argument(
        "--tile",
        type=_parse_tile,
        default=(0, 0),
        help="Tile coordinates as 'X,Y' (default: 0,0).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=2,
        help="Number of independent subprocess bakes to compare (default: 2).",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=32,
        help="Tile size in cells (default: 32 — keeps CI matrix runs <30s).",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=50.0,
        help="World-scale multiplier passed to the tile generator.",
    )
    parser.add_argument(
        "--terrain-type",
        default="mountains",
        help="Terrain archetype id (mountains / hills / coastal / etc.).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits with 2 on parse error — preserve that.
        return int(exc.code) if exc.code is not None else _EXIT_CONFIG_ERROR

    if args.runs < 2:
        print(
            json.dumps(
                {
                    "error": "--runs must be >= 2 to compare bakes",
                    "deterministic": False,
                }
            ),
            file=sys.stderr,
        )
        return _EXIT_CONFIG_ERROR

    # PR #46 thread 8: surface configuration errors (invalid --terrain-type,
    # malformed --size, etc.) as a structured JSON payload + exit code 2 so
    # the CLI contract is consistently enforced.  Without this wrap a bad
    # ``--terrain-type`` would propagate ``CalledProcessError`` and exit
    # with an unstructured Python traceback + code 1 — indistinguishable
    # from a real non-determinism failure.
    try:
        result = run_determinism_check_subprocess(
            seed=int(args.seed),
            runs=int(args.runs),
            size=int(args.size),
            scale=float(args.scale),
            terrain_type=str(args.terrain_type),
            tile_x=int(args.tile[0]),
            tile_y=int(args.tile[1]),
        )
    except subprocess.CalledProcessError as exc:
        # ``generate_tile`` exited non-zero — bubble up its stderr (truncated)
        # so CI logs show why without the raw traceback.
        stderr_text = (exc.stderr or "").strip()
        # Cap the captured stderr to keep the JSON payload bounded for log
        # consumers.  The underlying CalledProcessError still references the
        # full stream if a developer needs it locally.
        stderr_excerpt = stderr_text if len(stderr_text) <= 2000 else (
            stderr_text[:2000] + "...[truncated]"
        )
        print(
            json.dumps(
                {
                    "error": "subprocess generate_tile failed",
                    "exit_code": int(exc.returncode),
                    "stderr": stderr_excerpt,
                    "deterministic": False,
                    "seed": int(args.seed),
                    "tile": [int(args.tile[0]), int(args.tile[1])],
                    "platform": platform.system().lower(),
                    "python_version": platform.python_version(),
                },
                sort_keys=True,
                indent=2,
            ),
            file=sys.stderr,
        )
        return _EXIT_CONFIG_ERROR
    except (ValueError, TypeError, OSError) as exc:
        # Configuration / I/O errors: surface as structured JSON + exit 2
        # so callers can distinguish "bake bug" from "user passed garbage".
        print(
            json.dumps(
                {
                    "error": f"{type(exc).__name__}: {exc}",
                    "deterministic": False,
                    "seed": int(args.seed),
                    "tile": [int(args.tile[0]), int(args.tile[1])],
                    "platform": platform.system().lower(),
                    "python_version": platform.python_version(),
                },
                sort_keys=True,
                indent=2,
            ),
            file=sys.stderr,
        )
        return _EXIT_CONFIG_ERROR

    payload = {
        "deterministic": bool(result["deterministic"]),
        "seed": int(args.seed),
        "tile": [int(args.tile[0]), int(args.tile[1])],
        "run_count": int(result["run_count"]),
        "hashes": list(result["hashes"]),
        "platform": platform.system().lower(),
        "python_version": platform.python_version(),
    }
    print(json.dumps(payload, sort_keys=True, indent=2))

    return _EXIT_OK if payload["deterministic"] else _EXIT_NONDETERMINISTIC


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
