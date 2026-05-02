"""Bundle R — addon version + handler registration integrity checks.

Headless-safe: real Blender would read ``bl_info`` via ``importlib.reload``
and check the live module. In headless mode we grep the source file for
``bl_info`` so the contract still holds on CI.

See Addendum 1.A.5.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

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


def _import_addon_package() -> object:
    """Return the live addon package object, or raise ``ImportError``.

    Resolves the package name from ``_addon_init_path()``'s grandparent
    directory name so this works regardless of how the package was installed.
    Uses ``importlib.import_module`` rather than relative-import gymnastics —
    ``from .. import __init__`` is not valid Python (``__init__`` is not an
    importable attribute of a package object) and raises ``ImportError`` in
    all Blender versions.
    """
    import importlib

    # The addon package lives two levels up from this handlers sub-package:
    #   <pkg_root>/__init__.py   ← what we want
    #   <pkg_root>/handlers/terrain_addon_health.py  ← __file__
    pkg_root = Path(__file__).resolve().parent.parent
    pkg_name = pkg_root.name  # e.g. "veilbreakers_terrain"
    return importlib.import_module(pkg_name)


def detect_stale_addon() -> bool:
    """Return True if the on-disk ``__init__.py`` differs from the running module.

    Detection runs two checks in priority order:
    1. SHA-256 content hash: disk source bytes vs. the source file the live
       module was loaded from.  This is reliable on all platforms including
       Windows (no mtime-precision issues).
    2. ``bl_info['version']`` string comparison (legacy fallback for cases
       where the live module's ``__file__`` is unavailable, e.g. frozen builds).

    The old ``.pyc`` mtime check has been removed: mtime resolution on Windows
    NTFS is 100 ns but FAT32/exFAT (USB, some CI runners) is 2 s, making the
    check unreliable. Content hash covers the same signal without the platform
    hazard.

    Returns ``False`` in fully headless mode where the addon module is not
    importable (nothing to be stale against).
    """
    import hashlib

    disk_path = _addon_init_path()
    if not disk_path.exists():
        return False

    try:
        _live = _import_addon_package()
    except Exception:
        return False

    # 1. Content hash — primary check
    live_file = getattr(_live, "__file__", None)
    if live_file:
        live_p = Path(live_file)
        if live_p.exists():
            disk_hash = hashlib.sha256(disk_path.read_bytes()).hexdigest()
            live_hash = hashlib.sha256(live_p.read_bytes()).hexdigest()
            if disk_hash != live_hash:
                return True
            # Hashes match → definitely not stale; skip version fallback.
            return False

    # 2. Version fallback (frozen / no __file__)
    on_disk_ver = _read_bl_info_version()
    live_bl = getattr(_live, "bl_info", None)
    if isinstance(live_bl, dict) and on_disk_ver is not None:
        live_ver = live_bl.get("version")
        if live_ver is not None:
            return tuple(on_disk_ver) != tuple(live_ver)

    return False


def _is_live_blender() -> bool:
    """Return True only when running inside a real Blender session.

    Detects stub/mock bpy by checking that bpy.app.version is an actual
    integer tuple — stubs return MagicMock objects for attribute access.
    """
    import sys
    bpy_mod = sys.modules.get("bpy")
    if bpy_mod is None:
        return False
    try:
        ver = bpy_mod.app.version
        return (
            isinstance(ver, tuple)
            and len(ver) == 3
            and isinstance(ver[0], int)
        )
    except Exception:
        return False


def force_addon_reload() -> bool:
    """Reload the addon package in dependency order and re-register handlers.

    Sub-modules are reloaded in forward discovery order (leaves-first:
    sys.modules preserves insertion order and base modules like
    terrain_semantics are inserted before dependents like terrain_pipeline).
    The package root is reloaded last. If the package exposes ``register()``
    it is called after reload to re-bind any Blender operators.

    In a live Blender session this is equivalent to disabling and re-enabling
    the addon via ``bpy.ops.preferences.addon_disable`` /
    ``bpy.ops.preferences.addon_enable``.

    Returns:
        ``True`` on success, ``False`` in headless/stub mode or on error.
    """
    import importlib
    import sys

    # Guard: skip entirely when bpy is a test stub. Reloading modules in
    # headless mode corrupts class identity (e.g. PassResult gets two
    # instances across terrain_semantics and terrain_pipeline) and causes
    # isinstance checks to fail in subsequent tests.
    if not _is_live_blender():
        return False

    try:
        _live = _import_addon_package()

        pkg_name = _live.__name__
        pkg_prefix = pkg_name + "."

        # Collect sub-modules in sys.modules insertion order — base modules
        # (leaves) appear first because they were imported earliest.
        sub_mods = [
            m
            for name, m in list(sys.modules.items())
            if name.startswith(pkg_prefix) and m is not None
        ]
        # Reload leaves-first (forward order): base modules like
        # terrain_semantics reload before dependents like terrain_pipeline,
        # so dependents pick up the freshly re-created class objects.
        for mod in sub_mods:
            try:
                importlib.reload(mod)
            except Exception:
                logger.debug("importlib.reload failed for module %s", getattr(mod, '__name__', mod), exc_info=True)

        importlib.reload(_live)

        # Re-bind Blender operators/handlers if the package exposes register().
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
