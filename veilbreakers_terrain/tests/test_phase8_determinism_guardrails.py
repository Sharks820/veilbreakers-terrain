"""Phase 8 determinism guardrails for production handler RNG calls."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

# CHECKPOINT-OPUS-ULTRA V8 (2026-05-20): migrated to the shared AST helper.
# The prior local ``_call_name`` was bit-identical to ``dotted_call_name`` in
# ``_ast_helpers`` — verified semantically equivalent on 7 AST shapes during
# PR #116 verifier review (foo(), a.b(), a.b.c(), np.random.choice(),
# self.method(), getattr(...)(), arr[0]()). Aliased import preserves
# call-site line numbers and eliminates the 14-line local duplicate.
from veilbreakers_terrain.tests._ast_helpers import (
    dotted_call_name as _call_name,
)


_FORBIDDEN_RNG_CALLS = {
    "np.random.RandomState",
    "np.random.choice",
    "np.random.randint",
    "np.random.random",
    "np.random.uniform",
    "random.random",
}


def test_production_handlers_do_not_use_legacy_or_bare_rng_calls():
    root = Path(__file__).resolve().parents[1] / "handlers"
    offenders: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name in _FORBIDDEN_RNG_CALLS:
                    rel = path.relative_to(root)
                    offenders.append(f"{rel}:{node.lineno}:{name}")

    assert offenders == []


def test_generate_tile_cli_subprocess_outputs_are_byte_identical(tmp_path):
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"

    for out_dir in (run_a, run_b):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "veilbreakers_terrain.cli",
                "generate_tile",
                "--seed",
                "42",
                "--output-dir",
                str(out_dir),
            ],
            check=True,
            cwd=Path(__file__).resolve().parents[2],
        )

    artifacts = ["manifest.json", "heightmap.bin", "splatmap_0.png"]
    for name in artifacts:
        assert (run_a / name).read_bytes() == (run_b / name).read_bytes()
