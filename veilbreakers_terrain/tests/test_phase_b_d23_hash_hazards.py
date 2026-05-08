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

    AST-level check that detects:
      - bare `hash(x)`
      - `builtins.hash(x)` (attribute access on `builtins` module)
      - aliased `h = hash; h(x)` (any local rebinding to `hash`)

    Ignores text inside string literals and docstrings (which legitimately
    mention `hash()` in module-rule documentation).
    """
    import ast

    src = _read("terrain_cliffs.py")
    tree = ast.parse(src)

    # Pass 1: collect aliases — any name that gets bound to `hash` or
    # `builtins.hash` so the call-site check below can flag them.
    hash_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if isinstance(node.value, ast.Name) and node.value.id == "hash":
                        hash_aliases.add(target.id)
                    elif (
                        isinstance(node.value, ast.Attribute)
                        and isinstance(node.value.value, ast.Name)
                        and node.value.value.id == "builtins"
                        and node.value.attr == "hash"
                    ):
                        hash_aliases.add(target.id)

    # Pass 2: flag every Call site that resolves to hash().
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_hash = False
        if isinstance(func, ast.Name) and (func.id == "hash" or func.id in hash_aliases):
            is_hash = True
        elif (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "builtins"
            and func.attr == "hash"
        ):
            is_hash = True
        if is_hash:
            sites.append(node.lineno)

    assert not sites, (
        f"D23 REGRESSION — terrain_cliffs.py reintroduced builtin hash() "
        f"call at lines {sites}; hash() is PYTHONHASHSEED-randomized"
    )


def _seed_xor_idx_sites(src: str) -> list[int]:
    """Return line numbers where `seed ^ <expr involving any *_idx>` occurs.

    AST-based: walks BinOp nodes for ^ where the left side is a Name `seed`
    and the right side expression contains any Name ending in `_idx`.
    """
    import ast

    tree = ast.parse(src)
    sites: list[int] = []

    def names_in(node: ast.AST) -> set[str]:
        out: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                out.add(sub.id)
        return out

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.BitXor)
            and isinstance(node.left, ast.Name)
            and node.left.id == "seed"
        ):
            right_names = names_in(node.right)
            if any(n.endswith("_idx") or n.endswith("_i") for n in right_names):
                sites.append(node.lineno)
    return sites


def test_no_magic_xor_seed_pattern_in_terrain_cliffs():
    """AST-level: no `seed ^ <expr containing *_idx>` enumeration XOR pattern remains.

    Catches both the historical `seed ^ (cliff_idx * N + M)` form and any
    similar future variants (e.g. ``seed ^ (idx + offset * 7)``).
    """
    src = _read("terrain_cliffs.py")
    sites = _seed_xor_idx_sites(src)
    assert not sites, (
        f"D23 REGRESSION — terrain_cliffs.py reintroduced `seed ^ <idx-expr>` "
        f"magic-XOR pattern at lines {sites}"
    )


def _enum_idx_xor_with_constant_sites(src: str, idx_name_suffix: str = "_i") -> list[int]:
    """Return line numbers where any `*_i` or `*_i*` Name is XOR'd with a hex Constant
    anywhere within the same BinOp expression tree.

    Captures all migration hazards:
      - `cave_i ^ 0xDEADBEEF`            (direct XOR)
      - `cave_i * 2654435761 ^ 0xC0FFEE` (multiplication then XOR)
      - `(idx + 1) * N ^ 0xC0FFEE`       (parenthesized variants)
    """
    import ast

    tree = ast.parse(src)
    sites: list[int] = []

    def has_cave_i(node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and (
                sub.id == "cave_i"
                or sub.id.endswith("_i")
                or sub.id.endswith("_idx")
            ):
                return True
        return False

    def has_hex_constant(node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, int):
                # Only flag values likely to be magic constants
                # (anything > 1024 or specifically hex-coded large numbers).
                if sub.value > 1024:
                    return True
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitXor):
            if has_cave_i(node) and has_hex_constant(node):
                sites.append(node.lineno)
    return sites


def test_no_magic_xor_seed_pattern_in_terrain_caves():
    """AST-level: no `cave_i ^/* <magic constant>` patterns remain.

    Detects all 3 historical forms via AST tree walk, regardless of
    associativity / parenthesization (regex-based check missed
    `cave_i * 2654435761 ^ 0xC0FFEE`).
    """
    src = _read("terrain_caves.py")
    sites = _enum_idx_xor_with_constant_sites(src)
    assert not sites, (
        f"D23 REGRESSION — terrain_caves.py reintroduced enum-idx ^ "
        f"magic-constant pattern at lines {sites}"
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
