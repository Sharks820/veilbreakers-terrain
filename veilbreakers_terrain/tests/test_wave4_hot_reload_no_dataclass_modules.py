"""Regression test: _BIOME_RULE_MODULES must not contain any module that
defines @dataclass classes at module scope.

Background (WAVE4-HOT-RELOAD-DATACLASS-001):
  terrain_hot_reload._BIOME_RULE_MODULES is a list of module names that the
  hot-reload subsystem will importlib.reload() at runtime. If any of those
  modules defines a @dataclass at module scope, reloading creates a *new* class
  object that is not the same as the one imported by already-running code.
  Subsequent isinstance(spec, WorldMapSpec) checks return False for existing
  instances → silent contract failure across the entire biome stack.

  The file already carries a prominent comment warning against adding such
  modules. This test turns that warning into a CI failure.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import List, Tuple


def _module_to_path(module_name: str) -> Path | None:
    """Resolve a dotted module name to its source file, or None if not found."""
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        return None
    p = Path(spec.origin)
    return p if p.suffix == ".py" else None


def _top_level_dataclass_names(source: str) -> List[str]:
    """Return the names of all module-scope classes decorated with @dataclass.

    Accepts both ``@dataclass`` (bare name) and ``@dataclasses.dataclass``
    (qualified) to be robust against import styles.
    """
    tree = ast.parse(source)
    hits: List[str] = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "dataclass":
                hits.append(node.name)
                break
            if (
                isinstance(dec, ast.Attribute)
                and dec.attr == "dataclass"
                and isinstance(dec.value, ast.Name)
                and dec.value.id == "dataclasses"
            ):
                hits.append(node.name)
                break
            # Also catch dataclass(...) call form
            if isinstance(dec, ast.Call):
                func = dec.func
                if isinstance(func, ast.Name) and func.id == "dataclass":
                    hits.append(node.name)
                    break
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "dataclass"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "dataclasses"
                ):
                    hits.append(node.name)
                    break
    return hits


def test_biome_rule_modules_contain_no_dataclass_definitions() -> None:
    """Assert that no module in _BIOME_RULE_MODULES defines @dataclass classes.

    For each module name in the list this test:
      1. Resolves the name to a .py source file.
      2. AST-parses the file (no import side-effects).
      3. Walks top-level class definitions for @dataclass decorators.
      4. Fails with a detailed message if any are found.

    A module that cannot be resolved (e.g. not yet created) is silently skipped —
    this matches the runtime _safe_reload behaviour that already skips missing
    modules.
    """
    from veilbreakers_terrain.handlers.terrain_hot_reload import _BIOME_RULE_MODULES

    violations: List[Tuple[str, List[str]]] = []

    for mod_name in _BIOME_RULE_MODULES:
        path = _module_to_path(mod_name)
        if path is None or not path.exists():
            # Module not present in this env — skip (mirrors _safe_reload behaviour)
            continue
        source = path.read_text(encoding="utf-8")
        dc_names = _top_level_dataclass_names(source)
        if dc_names:
            violations.append((mod_name, dc_names))

    assert not violations, (
        "The following modules in _BIOME_RULE_MODULES define @dataclass classes "
        "at module scope. Reloading them creates new class objects that break "
        "isinstance() checks for existing instances (silent contract failure).\n"
        "Either move the dataclass to a dedicated non-reloaded module, or remove "
        "the module from _BIOME_RULE_MODULES.\n\n"
        + "\n".join(
            f"  {mod}: {', '.join(names)}" for mod, names in violations
        )
    )
