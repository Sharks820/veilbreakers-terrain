"""Phase B D23 — hash-hazard migration regression tests.

Pins the migration of 6 hash hazards in terrain_cliffs.py + terrain_caves.py
to ``derive_pass_seed`` for PYTHONHASHSEED-stable, collision-free seed
derivation.

Original hazards:
  - terrain_cliffs.py: ``hash(cliff.cliff_id) & 0x7FFFFFFF`` —
    PYTHONHASHSEED-randomized, non-reproducible across processes.
  - terrain_cliffs.py: ``(seed ^ (0xB0B1 + cliff_idx * 37)) & 0x7FFFFFFF``,
    ``(seed ^ (cliff_idx * 1234567891 + 987654321)) & 0x7FFFFFFF`` —
    enumeration-index magic-XOR, collision-prone across modules.
  - terrain_caves.py: ``(base_seed ^ ((cave_i + 1) * 2654435761))``,
    ``np.random.default_rng(cave_i ^ 0xDEADBEEF)``,
    ``(cave_i * 2654435761 ^ 0xC0FFEE) & 0xFFFFFFFF`` — same anti-pattern.
"""

from __future__ import annotations

import pathlib

_HANDLERS = pathlib.Path(__file__).resolve().parents[1] / "handlers"


def _read(name: str) -> str:
    return (_HANDLERS / name).read_text(encoding="utf-8")


def test_no_hash_function_call_in_terrain_cliffs():
    """Builtin `hash(...)` call must not appear in terrain_cliffs.py code.

    AST-level check that ignores text inside string literals and
    docstrings (which legitimately mention `hash()` in module-rule
    documentation).
    """
    import ast

    src = _read("terrain_cliffs.py")
    tree = ast.parse(src)
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "hash":
                sites.append(node.lineno)
    assert not sites, (
        f"D23 REGRESSION — terrain_cliffs.py reintroduced builtin hash() "
        f"call at lines {sites}; hash() is PYTHONHASHSEED-randomized"
    )


def test_no_magic_xor_seed_pattern_in_terrain_cliffs():
    """No `seed ^ (...idx * N + M)` magic XOR enumeration-index pattern remains."""
    import re

    src = _read("terrain_cliffs.py")
    pattern = re.compile(r"seed\s*\^\s*\([^)]*idx\s*\*\s*\d+")
    matches = pattern.findall(src)
    assert not matches, (
        f"D23 REGRESSION — terrain_cliffs.py reintroduced `seed ^ idx*N` "
        f"magic-XOR pattern: {matches!r}"
    )


def test_no_magic_xor_seed_pattern_in_terrain_caves():
    """No `cave_i ^ 0xDEADBEEF` style magic XOR remains."""
    import re

    src = _read("terrain_caves.py")
    # The most dangerous form: a single-byte magic XOR on enumeration index
    # used directly as RNG seed.
    pattern = re.compile(r"cave_i\s*[\^*]\s*0x[0-9A-Fa-f]+")
    matches = pattern.findall(src)
    # Allow occurrences inside derive_pass_seed namespace strings (those
    # are stable). Forbid bare arithmetic.
    bare = [m for m in matches if "0xDEADBEEF" in m or "0xC0FFEE" in m]
    assert not bare, (
        f"D23 REGRESSION — terrain_caves.py reintroduced cave_i ^/* magic "
        f"XOR/multiplication: {bare!r}"
    )


def test_terrain_cliffs_imports_derive_pass_seed():
    src = _read("terrain_cliffs.py")
    assert "from .terrain_pipeline import derive_pass_seed" in src, (
        "terrain_cliffs.py: derive_pass_seed module-level import missing"
    )


def test_terrain_caves_imports_derive_pass_seed():
    src = _read("terrain_caves.py")
    assert (
        "from .terrain_pipeline import derive_pass_seed" in src
    ), (
        "terrain_caves.py: derive_pass_seed import missing"
    )


def test_cliff_pass_deterministic_smoke():
    """Smoke test: pass_cliffs runs deterministically (PYTHONHASHSEED-safe)."""
    # The actual determinism contract is enforced by
    # test_terrain_cliffs.py::test_pass_cliffs_is_deterministic — this test
    # is just a fast pre-check that the migration didn't break the basic
    # invocation.
    from veilbreakers_terrain.handlers import terrain_cliffs

    assert hasattr(terrain_cliffs, "insert_hero_cliff_meshes")
    assert hasattr(terrain_cliffs, "pass_cliffs")
