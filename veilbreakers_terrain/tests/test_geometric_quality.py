"""Geometric-quality test stub (T0.5-7 per Y04 v3 §P.8.2).

Why this file shrank
--------------------
Earlier this file defined a 28-line in-test ``_heightmap_to_mesh`` helper
and ~20 test methods that asserted manifold integrity, normal consistency,
degenerate-face absence, mesh connectivity, and vertex-uniqueness against
the helper's output. The audit (Part P §P.3.5 of
``docs/aaa-audit/2026_05_17_ultrafinal/MASTER_FINAL.md``) flagged the
whole file as **tautological**: the helper was defined in the test file
and never exercised production code, so the tests verified properties of
their own construction — not of production mesh generation.

Production analog
-----------------
``veilbreakers_terrain.handlers.environment._create_terrain_mesh_from_heightmap``
(see ``environment.py:1758``) is the real mesh-from-heightmap path. It
returns a ``dict[str, Any]`` payload and uses ``bpy``/``bmesh`` to
materialise a Blender mesh, not a ``(verts, faces)`` tuple. Geometric-
quality regression nets that catch real production bugs belong against
that function and live with the rest of the environment-handler tests
(see ``test_environment*.py``). This stub is intentionally minimal — its
job is to (a) preserve the import path so any external CI shard
referencing it still resolves, and (b) carry the rationale into git
blame.

Per FIX_PATTERN_v1.md §3 C6 + §9 anti-pattern "Bundle a refactor with a
fix": writing the production-targeting replacement is a separate PR
(filed in the cleanup queue as the natural follow-on to T0.5-7).
"""

from __future__ import annotations

import pytest

from veilbreakers_terrain.handlers.environment import (
    _create_terrain_mesh_from_heightmap,
)


def test_production_mesh_from_heightmap_is_importable() -> None:
    """Smoke check: the production analog of the deleted in-test helper is
    importable. Catches refactors that rename/remove the production callable
    without updating the audit-corpus pointer above.
    """
    assert _create_terrain_mesh_from_heightmap is not None
    assert callable(_create_terrain_mesh_from_heightmap)


@pytest.mark.xfail(
    reason=(
        "T0.5-7 follow-on: production mesh-from-heightmap geometric-quality "
        "regression net (manifold integrity, normal orientation, no-degenerate-faces, "
        "connectivity, no-duplicate-verts) has not been re-authored against "
        "_create_terrain_mesh_from_heightmap yet. Tracked as a Tier-4 cleanup "
        "follow-on. Removing this xfail requires landing the real tests."
    ),
    strict=True,
)
def test_production_mesh_geometric_quality_regression_net_exists() -> None:
    """Forcing function (xfail-strict): when the production-targeting
    geometric-quality regression net is authored in a follow-on PR, this
    xfail will flip and force the author to delete the marker.
    """
    raise NotImplementedError(
        "Author production mesh-from-heightmap geometric-quality tests "
        "in a follow-on PR and remove this xfail."
    )
