"""Extended AST regression: _BIOME_RULE_MODULES must not contain any module
with pydantic.BaseModel or typing.NamedTuple class definitions.

Background (WAVE5-5, extending WAVE4-HOT-RELOAD-DATACLASS-001):
  PR #137 (branch fix/wave4-hot-reload-and-navmesh-docstring) added
  ``test_wave4_hot_reload_no_dataclass_modules.py`` which guards against
  ``@dataclass`` at module scope.  The same isinstance-breakage hazard exists
  for two more inheritance patterns NOT covered by PR #137:

  * ``pydantic.BaseModel`` subclasses — pydantic v2 uses __class_getitem__
    and model reconstruction mechanisms that are equally fragile under
    importlib.reload().  Reloading creates a new class object; existing
    instances no longer pass isinstance() against the reloaded class.

  * ``typing.NamedTuple`` subclasses — these create a custom tuple subclass
    at class-definition time.  Reloading creates a new (distinct) tuple
    subclass.  isinstance(existing_instance, ReloadedNamedTuple) returns
    False because the identity of the class object changed.

  Both patterns carry the same silent-corruption risk as @dataclass.
  This file specifically adds the pydantic and NamedTuple guards that
  PR #137 did not include.

  The @dataclass check is handled by the companion test in
  ``test_wave4_hot_reload_no_dataclass_modules.py`` (from PR #137).
  Both tests must pass on main; this file does NOT duplicate the @dataclass
  check so it does not conflict with or supersede PR #137.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import List, Tuple


def _module_to_path(module_name: str) -> Path | None:
    """Resolve a dotted module name to its source .py file, or None."""
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        return None
    p = Path(spec.origin)
    return p if p.suffix == ".py" else None


def _top_level_reload_fragile_new_patterns(source: str) -> List[Tuple[str, str]]:
    """Return (class_name, reason) for module-scope classes with the two NEW
    reload-fragile patterns NOT guarded by PR #137.

    Checks for:
    1. pydantic.BaseModel subclass — direct parent is ``BaseModel`` (bare) or
       ``pydantic.BaseModel`` (qualified).  Also catches ``BaseModel``
       originating from ``pydantic.v1`` or ``pydantic_v1`` for compat layers.
    2. typing.NamedTuple subclass — parent is ``NamedTuple`` (bare) or
       ``typing.NamedTuple`` (qualified).

    @dataclass is NOT checked here — PR #137's
    ``test_wave4_hot_reload_no_dataclass_modules.py`` covers it.

    Only top-level (module-scope) class definitions are checked; nested
    classes (e.g. a NamedTuple inside a function body) are NOT reload targets.
    """
    tree = ast.parse(source)
    hits: List[Tuple[str, str]] = []

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # pydantic.BaseModel subclass
        for base in node.bases:
            if _is_pydantic_base_model(base):
                hits.append((node.name, "pydantic.BaseModel"))
                break
        else:
            # typing.NamedTuple subclass
            for base in node.bases:
                if _is_named_tuple(base):
                    hits.append((node.name, "typing.NamedTuple"))
                    break

    return hits


def _is_pydantic_base_model(base: ast.expr) -> bool:
    """True if *base* is BaseModel / pydantic.BaseModel / pydantic.v1.BaseModel."""
    # Bare name
    if isinstance(base, ast.Name) and base.id == "BaseModel":
        return True
    # Qualified: pydantic.BaseModel, pydantic.v1.BaseModel, pydantic_v1.BaseModel
    if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
        return True
    return False


def _is_named_tuple(base: ast.expr) -> bool:
    """True if *base* is NamedTuple / typing.NamedTuple."""
    # Bare name
    if isinstance(base, ast.Name) and base.id == "NamedTuple":
        return True
    # Qualified: typing.NamedTuple
    if (
        isinstance(base, ast.Attribute)
        and base.attr == "NamedTuple"
        and isinstance(base.value, ast.Name)
        and base.value.id == "typing"
    ):
        return True
    return False


def test_biome_rule_modules_contain_no_pydantic_or_namedtuple_classes() -> None:
    """Assert _BIOME_RULE_MODULES has no pydantic.BaseModel / NamedTuple classes.

    For each module name in the list this test:
      1. Resolves the dotted name to a .py source file.
      2. AST-parses the file (no import side-effects).
      3. Checks for pydantic.BaseModel and typing.NamedTuple inheritance at
         module scope.
      4. Fails with a detailed message if any are found.

    A module that cannot be resolved (e.g. not yet created) is silently
    skipped — mirrors runtime _safe_reload behaviour.

    @dataclass is not checked here; that is covered by the companion test
    ``test_wave4_hot_reload_no_dataclass_modules.py`` added by PR #137.
    """
    from veilbreakers_terrain.handlers.terrain_hot_reload import _BIOME_RULE_MODULES

    violations: List[Tuple[str, List[Tuple[str, str]]]] = []

    for mod_name in _BIOME_RULE_MODULES:
        path = _module_to_path(mod_name)
        if path is None or not path.exists():
            continue  # Missing module — skip (mirrors _safe_reload)
        source = path.read_text(encoding="utf-8")
        fragile = _top_level_reload_fragile_new_patterns(source)
        if fragile:
            violations.append((mod_name, fragile))

    assert not violations, (
        "WAVE5-5 regression: the following modules in _BIOME_RULE_MODULES "
        "define pydantic.BaseModel or typing.NamedTuple classes at module "
        "scope.\n"
        "Reloading these modules via importlib.reload() creates new class "
        "objects, silently breaking isinstance() checks for all existing "
        "instances across the pipeline (silent contract failure).\n\n"
        "Resolution: move the class to a dedicated non-reloaded '_types.py' "
        "sibling module, or remove the module from _BIOME_RULE_MODULES.\n\n"
        + "\n".join(
            f"  {mod}:\n"
            + "\n".join(
                f"    class {cls_name!r}  [{reason}]" for cls_name, reason in classes
            )
            for mod, classes in violations
        )
    )
