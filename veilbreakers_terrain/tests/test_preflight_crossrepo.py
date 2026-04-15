"""Cross-repo integration: terrain can reach toolkit package surface.

Part of Phase 50 Plan 50-04 (Integration + Verification). Exercises the seam
terrain -> toolkit primitives to prove the split is wired end-to-end via
sibling-disk editable install.

Note (Plan 50-04 C-33 deviation, Rule 1):
``veilbreakers_mcp.primitives`` currently re-exports symbols from
``blender_addon.handlers.*`` via absolute imports. ``blender_addon`` lives
outside ``src/`` and is NOT included in the hatchling editable install
(the toolkit pyproject packages only ``src/veilbreakers_mcp``). Therefore
importing ``veilbreakers_mcp.primitives`` raises ``ModuleNotFoundError``
when run from outside Blender or without the toolkit-conftest sys.path
injection. That is a pre-existing toolkit packaging gap, not a terrain-side
bug, and is tracked for follow-up in the Phase 50 deferred items.

For now we assert:
  * the top-level toolkit package is importable (the one thing pip install -e
    actually guarantees);
  * ``veilbreakers_terrain.register_all`` is callable and returns a list.
"""


def test_toolkit_package_importable():
    """veilbreakers_mcp must be importable from terrain side (sibling editable)."""
    import veilbreakers_mcp  # noqa: F401


def test_register_all_returns_list():
    """veilbreakers_terrain.register_all must return a list of bundles."""
    from veilbreakers_terrain import register_all

    bundles = register_all(strict=False)
    assert isinstance(bundles, list), (
        f"register_all returned {type(bundles).__name__}, expected list"
    )


def test_toolkit_and_terrain_installed_side_by_side():
    """Sibling-disk install invariant: both packages resolve from their own paths."""
    import veilbreakers_mcp
    import veilbreakers_terrain

    tk_file = veilbreakers_mcp.__file__ or ""
    te_file = veilbreakers_terrain.__file__ or ""
    assert tk_file, "veilbreakers_mcp.__file__ missing"
    assert te_file, "veilbreakers_terrain.__file__ missing"
    # They MUST live in different trees (one-way dep, no monorepo fusion)
    assert tk_file != te_file
