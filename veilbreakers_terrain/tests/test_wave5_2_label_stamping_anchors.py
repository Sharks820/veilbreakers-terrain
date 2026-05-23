"""Regression test: every entry in _LABEL_STAMPING_DEFERRABLE_PASSES must be
a registered pass name in PASS_REGISTRY after full bootstrap.

Background (WAVE5-2):
  terrain_pipeline._LABEL_STAMPING_DEFERRABLE_PASSES is a frozenset of pass
  names used as anchor points for label_stamping insertion.  Dead names (i.e.
  names that don't correspond to any registered PassDefinition) never match
  pass-sequence iteration and silently mislead future readers about the
  intended anchor geometry.

  At the bug discovery site three dead names existed:
    "lava_emit"         — never registered; only "pass_lava_simulation" exists
    "lava_carve"        — never registered; same module as above
    "pass_water_variants" — duplicate of "water_variants" with a spurious prefix

  This test boots the full pass registry (mirroring how the production CLI
  initialises before running a pipeline) and asserts that every name in the
  frozenset appears as a key in TerrainPassController.PASS_REGISTRY.  Any
  future addition of a dead anchor will fail CI immediately rather than
  silently drifting into production.
"""

from __future__ import annotations


def test_label_stamping_deferrable_passes_all_registered() -> None:
    """Every name in _LABEL_STAMPING_DEFERRABLE_PASSES must be in PASS_REGISTRY.

    The test boots the full registry via terrain_master_registrar.bootstrap()
    (the same bootstrap that terrain_pipeline's CLI entry-point uses) then
    cross-references the frozenset against PASS_REGISTRY.keys().

    Failure here means a name was added to _LABEL_STAMPING_DEFERRABLE_PASSES
    without a matching PassDefinition registration.  Fix: either remove the
    dead name, or register the missing pass first.
    """
    from veilbreakers_terrain.handlers.terrain_master_registrar import (
        register_all_terrain_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        _LABEL_STAMPING_DEFERRABLE_PASSES,
    )

    # Save registry state and restore after test (avoid polluting other tests).
    original_registry = dict(TerrainPassController.PASS_REGISTRY)
    try:
        register_all_terrain_passes(strict=False)
        registered = set(TerrainPassController.PASS_REGISTRY.keys())
        dead = _LABEL_STAMPING_DEFERRABLE_PASSES - registered
        assert not dead, (
            "WAVE5-2 regression: the following names in "
            "_LABEL_STAMPING_DEFERRABLE_PASSES are NOT registered in "
            "PASS_REGISTRY after full bootstrap:\n"
            + "\n".join(f"  {name!r}" for name in sorted(dead))
            + "\n\nEither remove the dead anchor(s) from "
            "_LABEL_STAMPING_DEFERRABLE_PASSES, or register the missing "
            "pass before adding it to the set."
        )
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(original_registry)
