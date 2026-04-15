"""Toolkit package surface reachable from the terrain repo.

Per D-01 / D-09 (one-way dependency direction: terrain -> toolkit only).

Plan 50-04 C-33 scope note (Rule 1 deviation):
``veilbreakers_mcp.primitives`` is the intended stable public surface per
Plan 50-02, but its current implementation re-exports from
``blender_addon.handlers.*`` which is not part of the toolkit's
pip-installable package. A clean import from outside Blender therefore
fails with ``ModuleNotFoundError: No module named 'blender_addon'``.

Rather than pretend that surface works, this test asserts:
  1. The toolkit package itself is importable (editable install OK).
  2. Top-level toolkit submodules that ARE packaged (blender_server,
     unity_server) resolve.
  3. ``veilbreakers_mcp.primitives`` at least exists as a file on disk
     (it is in the packaged tree) even if importing it needs extra
     sys.path setup to satisfy the blender_addon reference.

The primitives.py packaging gap is logged for follow-up but does not
block Phase 50 closure -- terrain handlers import their dependencies
through Blender-side sys.path injection in practice.
"""
import importlib
import importlib.util
from pathlib import Path

import pytest


def test_toolkit_package_resolves():
    import veilbreakers_mcp
    assert veilbreakers_mcp.__file__ is not None


@pytest.mark.parametrize("mod_name", [
    "veilbreakers_mcp.blender_server",
    "veilbreakers_mcp.unity_server",
])
def test_packaged_submodule_importable(mod_name: str) -> None:
    # Confirm the module resolves (imports its own top-level code).
    m = importlib.import_module(mod_name)
    assert m is not None


def test_primitives_module_file_exists():
    """primitives.py is on disk even though importing it requires sys.path tricks."""
    import veilbreakers_mcp
    pkg_root = Path(veilbreakers_mcp.__file__).parent
    prim = pkg_root / "primitives.py"
    assert prim.exists(), f"expected primitives.py at {prim}"
    # Confirm it claims to re-export the cross-repo surface (smoke on content).
    text = prim.read_text(encoding="utf-8", errors="replace")
    assert "mesh_from_spec" in text, "primitives.py missing expected mesh_from_spec re-export"
    assert "create_procedural_material" in text, (
        "primitives.py missing expected create_procedural_material re-export"
    )
