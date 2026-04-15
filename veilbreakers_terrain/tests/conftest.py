"""Pytest configuration for veilbreakers-terrain tests.

Extracted from veilbreakers-gamedev-toolkit Tools/mcp-toolkit/tests/conftest.py
during Phase 50 split. Adapted for the standalone terrain repo layout:

- Adds the terrain package root to sys.path (so ``veilbreakers_terrain.handlers.*``
  imports resolve against the in-repo sources during tests).
- Provides mock modules for bpy / bmesh / mathutils / gpu / etc. so pure-logic
  tests run without a live Blender.

Live-Blender tests (integration/smoke) still require a real bpy; those are
gated by ``pytest.importorskip('bpy')`` in the test files themselves.
"""

from __future__ import annotations

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
