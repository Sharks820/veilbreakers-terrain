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

import inspect

import pytest

from veilbreakers_terrain.handlers.environment import (
    _create_terrain_mesh_from_heightmap,
)


def test_production_mesh_from_heightmap_public_contract() -> None:
    """Behavioral smoke check: the production analog of the deleted in-test
    helper exposes the canonical kwargs-only signature the audit corpus
    points readers at.

    A bare ``assert is not None`` would be redundant with the import at
    line 36 (an ImportError at collection time would already fail the
    suite). Instead, this test introspects the public contract so a future
    refactor that, e.g., re-orders kwargs into positional args or renames
    ``heightmap``/``height_scale`` is caught here.
    """
    assert callable(_create_terrain_mesh_from_heightmap)

    sig = inspect.signature(_create_terrain_mesh_from_heightmap)
    expected_kwargs = {
        "name",
        "heightmap",
        "terrain_size",
        "height_scale",
        "seed",
        "terrain_type",
    }
    actual = set(sig.parameters.keys())
    missing = expected_kwargs - actual
    assert not missing, (
        f"production analog dropped expected kwargs: {sorted(missing)}; "
        f"audit-corpus pointer in this file must be updated to match the new contract"
    )


@pytest.mark.xfail(
    reason=(
        "Forcing-function placeholder per FIX_PATTERN_v1 §3 C6 + Y04 v3 §P.8.5 "
        "Tier-4 cleanup AUGMENTED (this xfail itself is the tracking artifact, "
        "filed as T4-NEW-ZZ4-08 — \"author production mesh-from-heightmap "
        "geometric-quality regression net against environment._create_terrain_mesh_from_heightmap "
        "(manifold integrity, normal orientation, no-degenerate-faces, connectivity, "
        "no-duplicate-verts), gated by pytest.importorskip('bpy') since the "
        "MagicMock bpy stub at conftest.py:55-89 cannot validate bmesh.ops.create_grid "
        "output\"). Removing this xfail in any future PR requires landing the "
        "real production-targeting tests in the same PR. The audit's original "
        "prescription to re-import from handlers.terrain_world_orchestration is "
        "stale (that symbol does not exist); the canonical pointer is "
        "environment._create_terrain_mesh_from_heightmap at environment.py:1758."
    ),
    strict=True,
)
def test_production_mesh_geometric_quality_regression_net_exists() -> None:
    """Forcing function (xfail-strict): when the production-targeting
    geometric-quality regression net is authored in a follow-on PR, this
    xfail will flip and force the author to delete the marker.

    Note (pattern-recognition CE review on PR #76): this xfail-strict has
    INVERTED semantics from the per-raise-path xfail-strict in
    ``test_restore_pass_state.py`` (PR #75 / T0.5-3) — that file uses
    xfail to mark "bug → fix" (production change flips it green); this
    file uses xfail to mark "void → test" (new test authoring flips it
    green). Both are legitimate `xfail(strict=True)` modes; do NOT share
    a helper between them, because the inversion would obscure intent.
    """
    raise NotImplementedError(
        "Author production mesh-from-heightmap geometric-quality tests "
        "in a follow-on PR (T4-NEW-ZZ4-08) and remove this xfail decorator. "
        "Use pytest.importorskip('bpy') to gate on real Blender."
    )
