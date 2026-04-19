"""Bundle R — addon version + handler registration integrity checks.

Headless-safe: real Blender would read ``bl_info`` via ``importlib.reload``
and check the live module. In headless mode we grep the source file for
``bl_info`` so the contract still holds on CI.

See Addendum 1.A.5.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional, Sequence, Tuple

TERRAIN_ADDON_MIN_VERSION: Tuple[int, int, int] = (1, 0, 0)


class AddonVersionMismatch(RuntimeError):
    """Raised when the addon version is below the required floor."""


class AddonNotLoaded(RuntimeError):
    """Raised when the terrain addon is not importable."""


class StaleAddon(RuntimeError):
    """Raised when the on-disk addon differs from the in-memory one."""


def _addon_init_path() -> Path:
    # __init__.py of the blender_addon sibling of this module's parent
    return Path(__file__).resolve().parent.parent / "__init__.py"


def _read_bl_info_version() -> Optional[Tuple[int, ...]]:
    """Parse the ``version`` tuple out of the addon ``bl_info`` dict.

    Returns None if the file or tuple is missing. Pure-AST, so no Blender
    is required.
    """
    p = _addon_init_path()
    if not p.exists():
        return None
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    except Exception:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "bl_info":
                    if isinstance(node.value, ast.Dict):
                        for k, v in zip(node.value.keys, node.value.values):
                            if isinstance(k, ast.Constant) and k.value == "version":
                                if isinstance(v, ast.Tuple):
                                    parts: list[int] = []
                                    for elt in v.elts:
                                        if isinstance(elt, ast.Constant) and isinstance(
                                            elt.value, int
                                        ):
                                            parts.append(elt.value)
                                    return tuple(parts) if parts else None
    # Fallback: regex scan
    m = re.search(r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', p.read_text(encoding="utf-8"))
    if m:
        return tuple(int(x) for x in m.groups())
    return None


def assert_addon_loaded() -> None:
    """Verify that the addon package is present on disk."""
    if not _addon_init_path().exists():
        raise AddonNotLoaded(
            f"blender_addon/__init__.py not found at {_addon_init_path()}"
        )


def assert_addon_version_matches(
    min_version: Tuple[int, ...] = TERRAIN_ADDON_MIN_VERSION,
    *,
    allow_missing: bool = False,
) -> None:
    """Raise ``AddonVersionMismatch`` if the on-disk addon is below min_version.

    Missing ``bl_info`` is a hard-fail by default per Addendum 1.A.5: an addon
    tree with no declared version is treated as version mismatch. Tests that
    intentionally run against a stripped tree may pass ``allow_missing=True``.
    """
    version = _read_bl_info_version()
    if version is None:
        if allow_missing:
            return
        raise AddonVersionMismatch(
            f"terrain addon at {_addon_init_path()} has no bl_info['version']; "
            f"required >= {min_version}. Missing bl_info is a hard-fail — "
            "pass allow_missing=True explicitly if this is intentional."
        )
    if tuple(version) < tuple(min_version):
        raise AddonVersionMismatch(
            f"terrain addon version {version} < required {min_version}. "
            "Upgrade the addon before running terrain passes."
        )


def assert_handlers_registered(required: Sequence[str]) -> None:
    """Check the COMMAND_HANDLERS dict exposes every name in ``required``."""
    from . import COMMAND_HANDLERS  # type: ignore

    missing = [name for name in required if name not in COMMAND_HANDLERS]
    if missing:
        raise AddonNotLoaded(
            f"COMMAND_HANDLERS missing required entries: {missing}"
        )


def detect_stale_addon() -> bool:
    """Return True if the on-disk ``__init__.py`` differs from the running module.

    Detection runs three checks in priority order:
    1. SHA-256 content hash comparison (``__file__`` vs disk path).
    2. .pyc cache-file mtime: disk source newer than compiled cache → stale.
    3. ``bl_info['version']`` string comparison (legacy fallback).

    Returns ``False`` in fully headless mode where the addon module is not
    importable (nothing to be stale against).
    """
    import hashlib

    disk_path = _addon_init_path()
    if not disk_path.exists():
        return False

    try:
        from .. import __init__ as _live  # type: ignore
    except Exception:
        return False

    # 1. Content hash
    live_file = getattr(_live, "__file__", None)
    if live_file:
        from pathlib import Path as _P

        live_p = _P(live_file)
        if live_p.exists():
            disk_hash = hashlib.sha256(disk_path.read_bytes()).hexdigest()
            live_hash = hashlib.sha256(live_p.read_bytes()).hexdigest()
            if disk_hash != live_hash:
                return True

    # 2. .pyc mtime
    try:
        import importlib.util as _ilu

        cached = getattr(_ilu.find_spec(_live.__name__), "cached", None)
        if cached:
            from pathlib import Path as _P

            cached_p = _P(cached)
            if cached_p.exists():
                if disk_path.stat().st_mtime > cached_p.stat().st_mtime:
                    return True
    except Exception:
        pass

    # 3. Version fallback
    on_disk_ver = _read_bl_info_version()
    live_bl = getattr(_live, "bl_info", None)
    if isinstance(live_bl, dict) and on_disk_ver is not None:
        live_ver = live_bl.get("version")
        if live_ver is not None:
            return tuple(on_disk_ver) != tuple(live_ver)

    return False


def force_addon_reload() -> bool:
    """Reload the addon package in dependency order and re-register handlers.

    Sub-modules are reloaded in reverse import order (leaves first) to avoid
    forward-reference errors. The package root is reloaded last. If the
    package exposes ``register()`` it is called after reload to re-bind any
    Blender operators.

    Returns:
        ``True`` on success, ``False`` in headless mode or if an error occurs.
    """
    import importlib
    import sys

    try:
        from .. import __init__ as _live  # type: ignore

        pkg_prefix = (_live.__package__ or _live.__name__) + "."
        sub_mods = [
            m
            for name, m in list(sys.modules.items())
            if name.startswith(pkg_prefix) and m is not None
        ]
        # Reload sub-modules leaves-first (reverse discovery order approximates
        # dependency depth without a full topo-sort).
        for mod in reversed(sub_mods):
            try:
                importlib.reload(mod)
            except Exception:
                pass

        importlib.reload(_live)

        register_fn = getattr(_live, "register", None)
        if callable(register_fn):
            register_fn()

        return True
    except Exception:
        return False


__all__ = [
    "TERRAIN_ADDON_MIN_VERSION",
    "AddonVersionMismatch",
    "AddonNotLoaded",
    "StaleAddon",
    "assert_addon_loaded",
    "assert_addon_version_matches",
    "assert_handlers_registered",
    "detect_stale_addon",
    "force_addon_reload",
]
