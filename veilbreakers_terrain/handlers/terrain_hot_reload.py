"""Hot-reload watcher for terrain rule modules (Bundle M).

Re-imports biome-rule / material-rule modules when their source files
change on disk, so tuning iteration doesn't require a Blender restart.

Pure Python. No bpy.
"""

from __future__ import annotations

import importlib
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _rebind_pass_funcs_for_module(module_name: str) -> int:
    """Re-bind ``PassDefinition.func`` for every pass whose function came from
    *module_name*, using the freshly-reloaded module object.

    After ``importlib.reload()``, already-registered ``PassDefinition`` objects
    still hold stale function references — the function object identity changes
    even though the name is the same.  This helper iterates the module-level
    ``_PASS_MODULE_REGISTRY`` (a WeakValueDictionary keyed by
    ``(module_name, attr_name)``) and calls ``setattr(definition, "func",
    getattr(reloaded_module, attr_name))`` for every matching entry.

    Returns the number of ``PassDefinition`` objects successfully rebound.
    Failures are logged at WARNING and skipped — a partial rebind is safer
    than aborting the entire reload.
    """
    try:
        from .terrain_pipeline import _PASS_MODULE_REGISTRY
    except ImportError:
        logger.debug("hot-reload: terrain_pipeline not importable — skipping func rebind")
        return 0

    reloaded_mod = sys.modules.get(module_name)
    if reloaded_mod is None:
        logger.debug("hot-reload: %s not in sys.modules after reload — skipping rebind", module_name)
        return 0

    rebound = 0
    # Snapshot keys to avoid mutating the WeakValueDictionary during iteration
    keys = list(_PASS_MODULE_REGISTRY.keys())
    for key in keys:
        mod_name, attr_name = key
        if mod_name != module_name:
            continue
        definition = _PASS_MODULE_REGISTRY.get(key)
        if definition is None:
            continue  # already GC'd
        new_func = getattr(reloaded_mod, attr_name, None)
        if new_func is None:
            logger.warning(
                "hot-reload: module %r no longer exports %r — PassDefinition %r "
                "func left stale",
                module_name, attr_name, definition.name,
            )
            continue
        try:
            object.__setattr__(definition, "func", new_func)
            rebound += 1
            logger.debug(
                "hot-reload: rebound PassDefinition %r func from %s.%s",
                definition.name, module_name, attr_name,
            )
        except Exception as exc:
            logger.warning(
                "hot-reload: failed to rebind PassDefinition %r func: %s",
                definition.name, exc,
            )
    return rebound


# Modules we will attempt to reload. Missing modules are silently skipped.
_BIOME_RULE_MODULES = (
    "veilbreakers_terrain.handlers.terrain_ecotone_graph",
    "veilbreakers_terrain.handlers.terrain_materials_v2",
    "veilbreakers_terrain.handlers.terrain_banded",
)

_MATERIAL_RULE_MODULES = (
    "veilbreakers_terrain.handlers.terrain_materials",
    "veilbreakers_terrain.handlers.terrain_materials_v2",
)


def _module_path(mod: ModuleType) -> Optional[Path]:
    f = getattr(mod, "__file__", None)
    return Path(f) if f else None


def _safe_reload(name: str) -> Tuple[bool, Optional[Exception]]:
    """Attempt to import or reload *name*.

    Returns ``(success, exc)`` where *exc* is the caught exception on failure
    or ``None`` on success. Callers that only need the boolean can do::

        ok, _ = _safe_reload(name)

    Failures are logged at WARNING so they are never silently swallowed.
    """
    mod = sys.modules.get(name)
    if mod is None:
        try:
            importlib.import_module(name)
            logger.debug("hot-reload: imported %s", name)
            rebound = _rebind_pass_funcs_for_module(name)
            if rebound:
                logger.debug("hot-reload: rebound %d PassDefinition(s) for %s", rebound, name)
            return True, None
        except Exception as exc:
            logger.warning(
                "hot-reload: failed to import module %r: %s: %s",
                name, type(exc).__name__, exc,
            )
            return False, exc
    try:
        importlib.reload(mod)
        logger.debug("hot-reload: reloaded %s", name)
        rebound = _rebind_pass_funcs_for_module(name)
        if rebound:
            logger.debug("hot-reload: rebound %d PassDefinition(s) for %s", rebound, name)
        return True, None
    except Exception as exc:
        logger.warning(
            "hot-reload: failed to reload module %r: %s: %s",
            name, type(exc).__name__, exc,
        )
        return False, exc


def reload_biome_rules() -> List[str]:
    """Reload biome-rule modules. Returns list of successfully reloaded names."""
    ok: List[str] = []
    for name in _BIOME_RULE_MODULES:
        success, _ = _safe_reload(name)
        if success:
            ok.append(name)
    return ok


def reload_material_rules() -> List[str]:
    """Reload material-rule modules. Returns list of successfully reloaded names."""
    ok: List[str] = []
    for name in _MATERIAL_RULE_MODULES:
        success, _ = _safe_reload(name)
        if success:
            ok.append(name)
    return ok


@dataclass
class HotReloadWatcher:
    """Watches rule-module source files and reloads them when mtime changes.

    Usage::

        watcher = HotReloadWatcher()
        watcher.watch_biome_rules()
        watcher.watch_material_rules()

        # In the Blender timer / background thread:
        changed = watcher.check_and_reload()
        if changed:
            logger.info("hot-reload: reloaded %s", changed)

    All reload failures are logged at WARNING and included in the
    ``last_errors`` dict so callers can surface them to the user without
    needing to re-raise.
    """

    watched_modules: List[str] = field(default_factory=list)
    _mtimes: Dict[str, float] = field(default_factory=dict)
    last_errors: Dict[str, Exception] = field(default_factory=dict)

    def add(self, module_name: str) -> None:
        """Register a module for file-watching. Idempotent."""
        if module_name not in self.watched_modules:
            self.watched_modules.append(module_name)
            mod = sys.modules.get(module_name)
            if mod is not None:
                p = _module_path(mod)
                if p and p.exists():
                    self._mtimes[module_name] = p.stat().st_mtime

    def watch_biome_rules(self) -> None:
        """Register all biome-rule modules for watching."""
        for m in _BIOME_RULE_MODULES:
            self.add(m)

    def watch_material_rules(self) -> None:
        """Register all material-rule modules for watching."""
        for m in _MATERIAL_RULE_MODULES:
            self.add(m)

    def check_and_reload(self) -> List[str]:
        """Check mtimes and reload any module whose source file changed.

        Returns list of successfully reloaded module names. Any failures
        are stored in ``self.last_errors`` and logged at WARNING.
        """
        reloaded: List[str] = []
        for name in list(self.watched_modules):
            mod = sys.modules.get(name)
            if mod is None:
                success, exc = _safe_reload(name)
                if success:
                    reloaded.append(name)
                    self.last_errors.pop(name, None)
                    new_mod = sys.modules.get(name)
                    if new_mod:
                        p = _module_path(new_mod)
                        if p and p.exists():
                            self._mtimes[name] = p.stat().st_mtime
                elif exc is not None:
                    self.last_errors[name] = exc
                continue
            p = _module_path(mod)
            if p is None or not p.exists():
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError as exc:
                logger.warning("hot-reload: cannot stat %r: %s", p, exc)
                continue
            prev = self._mtimes.get(name)
            if prev is None:
                self._mtimes[name] = mtime
                continue
            if mtime > prev:
                success, exc = _safe_reload(name)
                if success:
                    reloaded.append(name)
                    self._mtimes[name] = mtime
                    self.last_errors.pop(name, None)
                elif exc is not None:
                    self.last_errors[name] = exc
        return reloaded

    def force_reload_all(self) -> List[str]:
        """Force-reload every watched module regardless of mtime.

        Returns list of successfully reloaded names. Failures are stored
        in ``self.last_errors`` and logged at WARNING.
        """
        out: List[str] = []
        for name in list(self.watched_modules):
            success, exc = _safe_reload(name)
            if success:
                out.append(name)
                self.last_errors.pop(name, None)
            elif exc is not None:
                self.last_errors[name] = exc
        return out

    def clear_errors(self) -> None:
        """Reset the error log (e.g. after the user has acknowledged them)."""
        self.last_errors.clear()


def force_reload_all(module_names: Optional[List[str]] = None) -> List[str]:
    """Module-level convenience: force-reload a list of modules (or all watched defaults).

    If *module_names* is None, reloads the union of all biome-rule and
    material-rule modules.  Returns the list of successfully reloaded names.
    Failures are logged at WARNING; they do not raise.

    This is distinct from ``HotReloadWatcher.force_reload_all`` which only
    operates on the modules registered with a specific watcher instance.
    """
    targets = list(module_names) if module_names is not None else list(
        dict.fromkeys(list(_BIOME_RULE_MODULES) + list(_MATERIAL_RULE_MODULES))
    )
    out: List[str] = []
    for name in targets:
        success, _ = _safe_reload(name)
        if success:
            out.append(name)
    return out


__all__ = [
    "HotReloadWatcher",
    "force_reload_all",
    "reload_biome_rules",
    "reload_material_rules",
    "_rebind_pass_funcs_for_module",
]
