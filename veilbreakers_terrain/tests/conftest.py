"""Pytest configuration for veilbreakers-terrain tests.

Extracted from veilbreakers-gamedev-toolkit Tools/mcp-toolkit/tests/conftest.py
during Phase 50 split. Adapted for the standalone terrain repo layout:

- Adds the terrain package root to sys.path (so ``veilbreakers_terrain.handlers.*``
  imports resolve against the in-repo sources during tests).
- Provides mock modules for bpy / bmesh / mathutils / gpu / etc. so pure-logic
  tests run without a live Blender.
- Installs a ``blender_addon.handlers.*`` -> ``veilbreakers_terrain.handlers.*``
  import alias so test files inherited from the monorepo collect without
  mass source rewriting (Phase 50 Plan 50-04 Rule 3 deviation).

Live-Blender tests (integration/smoke) still require a real bpy; those are
gated by ``pytest.importorskip('bpy')`` in the test files themselves.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Repo root (one level above veilbreakers_terrain/). Let ``import
# veilbreakers_terrain`` resolve to the in-repo source tree whether this repo
# was installed editable or just cloned.
_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def _make_stub(name: str) -> types.ModuleType:
    """Create a stub module that returns MagicMock for any attribute access."""
    mod = types.ModuleType(name)

    class _AttrProxy(MagicMock):
        """MagicMock that also works as a class base (for dataclass/enum)."""

        def __mro_entries__(self, bases):
            return (object,)

    mod.__dict__["__getattr__"] = lambda attr: _AttrProxy(name=f"{name}.{attr}")

    if name == "bpy":
        mod.types = _AttrProxy(name="bpy.types")
        mod.data = _AttrProxy(name="bpy.data")
        mod.context = _AttrProxy(name="bpy.context")
        mod.ops = _AttrProxy(name="bpy.ops")
        mod.props = _AttrProxy(name="bpy.props")
        mod.utils = _AttrProxy(name="bpy.utils")
        mod.app = _AttrProxy(name="bpy.app")
        for prop_fn in (
            "StringProperty", "IntProperty", "FloatProperty",
            "BoolProperty", "EnumProperty", "CollectionProperty",
            "PointerProperty", "FloatVectorProperty",
            "IntVectorProperty", "BoolVectorProperty",
        ):
            setattr(mod.props, prop_fn, lambda **kw: None)
            setattr(mod, prop_fn, lambda **kw: None)
    elif name == "bmesh":
        mod.types = _AttrProxy(name="bmesh.types")
        mod.ops = _AttrProxy(name="bmesh.ops")
        mod.new = MagicMock
    elif name == "mathutils":
        mod.Vector = MagicMock
        mod.Matrix = MagicMock
        mod.Euler = MagicMock
        mod.Quaternion = MagicMock
        mod.Color = MagicMock
        mod.noise = _AttrProxy(name="mathutils.noise")

    return mod


_BLENDER_MODS = (
    "bpy", "bpy.types", "bpy.props", "bpy.utils", "bpy.app",
    "bmesh", "bmesh.types", "bmesh.ops",
    "mathutils", "mathutils.noise",
    "bpy_extras", "bpy_extras.io_utils",
    "gpu", "gpu_extras", "bl_math", "idprop",
)

for _mod_name in _BLENDER_MODS:
    if _mod_name not in sys.modules:
        _parts = _mod_name.split(".")
        if len(_parts) > 1:
            _parent_name = _parts[0]
            if _parent_name not in sys.modules:
                sys.modules[_parent_name] = _make_stub(_parent_name)
            _parent = sys.modules[_parent_name]
            _child = getattr(_parent, _parts[1], None)
            if _child is not None:
                sys.modules[_mod_name] = _child
            else:
                sys.modules[_mod_name] = _make_stub(_mod_name)
        else:
            sys.modules[_mod_name] = _make_stub(_mod_name)


# ---------------------------------------------------------------------------
# blender_addon.handlers.* -> veilbreakers_terrain.handlers.* alias
#
# Test files inherited from the monorepo still write
# ``from blender_addon.handlers.terrain_X import ...``. The sources they refer
# to now live at ``veilbreakers_terrain.handlers.terrain_X``. Rather than
# rewrite 24 files, install a meta_path finder that transparently redirects
# any ``blender_addon.handlers.NAME`` import to
# ``veilbreakers_terrain.handlers.NAME`` and caches the result in sys.modules
# under BOTH names so subsequent imports (including submodule chains) stay
# consistent.
#
# Phase 50 Plan 50-04 Rule 3 deviation — blocks D-10 test invariant until
# terrain tests are mass-migrated in a follow-up.
# ---------------------------------------------------------------------------


class _BlenderAddonHandlersAliasFinder:
    """Import-alias finder for ``blender_addon.handlers.*`` -> terrain pkg."""

    _PREFIX = "blender_addon.handlers"
    _TARGET_PREFIX = "veilbreakers_terrain.handlers"

    def find_spec(self, fullname, path, target=None):  # noqa: D401, ARG002
        if fullname == "blender_addon":
            # Top-level stub package; create a bare module so "handlers" lookup works.
            return None  # Handled by the namespace shim below.
        if not fullname.startswith(self._PREFIX):
            return None
        # Translate name and try to import the real module.
        suffix = fullname[len(self._PREFIX):]
        target_name = self._TARGET_PREFIX + suffix
        try:
            real = importlib.import_module(target_name)
        except ModuleNotFoundError:
            return None
        # Cache under both names and return a spec that loads the cached module.
        sys.modules[fullname] = real
        import importlib.util as _ilutil

        spec = _ilutil.spec_from_loader(
            fullname,
            loader=_AliasLoader(real),
            origin=getattr(real, "__file__", None),
            is_package=bool(getattr(real, "__path__", None)),
        )
        return spec


class _AliasLoader:
    def __init__(self, real_module):
        self._real = real_module

    def create_module(self, spec):  # noqa: D401, ARG002
        return self._real

    def exec_module(self, module):  # noqa: D401, ARG002
        # Module already fully executed (it was real-imported first).
        return None


def _install_blender_addon_alias() -> None:
    # Provide a top-level ``blender_addon`` namespace package so attribute
    # access (``import blender_addon.handlers.foo``) works. We deliberately
    # point ``blender_addon.handlers`` at the terrain package's handlers
    # module so ``from blender_addon.handlers import environment`` resolves.
    if "blender_addon" not in sys.modules:
        addon = types.ModuleType("blender_addon")
        addon.__path__ = []  # type: ignore[attr-defined]  # namespace-like
        sys.modules["blender_addon"] = addon
    try:
        real_handlers = importlib.import_module("veilbreakers_terrain.handlers")
    except ModuleNotFoundError:
        return
    sys.modules["blender_addon.handlers"] = real_handlers
    sys.modules["blender_addon"].handlers = real_handlers  # type: ignore[attr-defined]

    # Install the finder if not already present.
    if not any(isinstance(f, _BlenderAddonHandlersAliasFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _BlenderAddonHandlersAliasFinder())


_install_blender_addon_alias()
