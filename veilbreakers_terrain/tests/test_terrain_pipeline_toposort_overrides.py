"""Regression tests for §11.1 PR #3 — topo-sort consumes ``overrides=``.

Verifies that ``_toposort_passes`` suppresses an edge ``A→B`` for channel
``c`` when ``c`` is declared in ``B.overrides``. This is the mechanism that
breaks dual-cycles between secondary writers (e.g. ``terrain_banded`` ↔
``terrain_morphology`` on ``height``) so that ``register_default_passes``
no longer raises ``ValueError`` on full registry load.
"""

from __future__ import annotations

import pytest

from veilbreakers_terrain.handlers.terrain_pipeline import _toposort_passes
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainPipelineState,
)


def _make_pass(
    name: str,
    *,
    requires: tuple[str, ...] = (),
    produces: tuple[str, ...] = (),
    overrides: tuple[str, ...] = (),
) -> PassDefinition:
    """Build a no-op PassDefinition with only contract metadata populated."""

    def _noop(
        _state: TerrainPipelineState,
        _bbox: BBox | None = None,
    ) -> PassResult:  # pragma: no cover — never invoked in toposort tests
        return PassResult(pass_name=name, status="ok", duration_seconds=0.0)

    return PassDefinition(
        name=name,
        func=_noop,
        requires_channels=requires,
        produces_channels=produces,
        overrides=overrides,
    )


def _names(ordered: list[PassDefinition]) -> list[str]:
    return [d.name for d in ordered]


# ---------------------------------------------------------------------------
# Override suppression — the core PR #3 contract
# ---------------------------------------------------------------------------


def test_overrides_breaks_cycle_when_required_and_overridden():
    """Edge A→B is suppressed when B requires c AND c in B.overrides.

    Without the suppression: A→B (B requires c that A produces) AND B→A
    (A requires d that B produces) creates a cycle that toposort cannot
    resolve. With override-aware suppression, the A→B edge for c drops,
    leaving only B→A — a clean ordering.
    """
    a = _make_pass("a", requires=("d",), produces=("height",))
    b = _make_pass(
        "b",
        requires=("height",),
        produces=("d", "height"),
        overrides=("height",),
    )
    ordered = _toposort_passes([a, b])
    # b runs first (no surviving edge into b after override suppression),
    # then a (depends on d that b produces).
    assert _names(ordered) == ["b", "a"]


def test_no_override_keeps_edge():
    """Sanity: without override declared, the edge A→B remains in place.

    If B requires c that A produces and B does NOT declare overrides=(c,),
    the original prerequisite edge stands and A orders before B as usual.
    """
    a = _make_pass("a", produces=("height",))
    b = _make_pass("b", requires=("height",))
    ordered = _toposort_passes([a, b])
    assert _names(ordered) == ["a", "b"]


def test_partial_override_only_suppresses_listed_channel():
    """Override suppression is per-channel, not per-edge.

    If B requires (c, d) with overrides=(c,) and A produces both, A→B
    edge survives via channel d — the override only nullifies the c
    requirement.
    """
    a = _make_pass("a", produces=("height", "wetness"))
    b = _make_pass(
        "b",
        requires=("height", "wetness"),
        overrides=("height",),  # only height is overridden, not wetness
    )
    ordered = _toposort_passes([a, b])
    # Edge survives via wetness — A still orders before B.
    assert _names(ordered) == ["a", "b"]


def test_override_breaks_dual_cycle_two_secondary_writers():
    """Dual-cycle: A and B both override height and require each other's primary channel.

    Models the real ``terrain_banded`` ↔ ``terrain_morphology`` cycle that
    motivated this fix. Without override-aware suppression both edges
    exist (A→B via height, B→A via the other primary channel) — cycle.
    With it, both height-edges drop and the surviving primary-channel
    edges form a clean DAG.
    """
    a = _make_pass(
        "banded",
        requires=("height",),
        produces=("height", "banded_macro"),
        overrides=("height",),
    )
    b = _make_pass(
        "morphology",
        requires=("height", "banded_macro"),
        produces=("height", "morphology_delta"),
        overrides=("height",),
    )
    ordered = _toposort_passes([a, b])
    # banded runs first because morphology requires banded_macro;
    # the height-cycle is gone via override suppression on both sides.
    assert _names(ordered) == ["banded", "morphology"]


def test_override_does_not_suppress_edge_via_unrelated_channel():
    """Override on c does not affect edges that exist via other channels.

    A produces both height and biome_id. B requires (height, biome_id) but
    only overrides height. The biome_id edge survives — B still orders
    after A. This confirms override suppression is surgical.
    """
    a = _make_pass("a", produces=("height", "biome_id"))
    b = _make_pass(
        "b",
        requires=("height", "biome_id"),
        overrides=("height",),
    )
    ordered = _toposort_passes([a, b])
    assert _names(ordered) == ["a", "b"]


def test_override_with_three_passes_chain():
    """Three-pass chain where the middle pass overrides — order is preserved
    via the surviving (non-overridden) edges.

    A → B → C where B overrides height (which it requires from A) but C
    requires banded_macro from B. The A→B edge for height drops; the B→C
    edge for banded_macro stays. A is still ordered before B because A
    has no incoming edges, B follows once B's degree hits zero, C last.
    """
    a = _make_pass("a", produces=("height",))
    b = _make_pass(
        "b",
        requires=("height",),
        produces=("banded_macro",),
        overrides=("height",),
    )
    c = _make_pass("c", requires=("banded_macro",))
    ordered = _toposort_passes([a, b, c])
    # B has no incoming edge after override suppression, A has none either,
    # both pop in registration order; C requires banded_macro from B and
    # comes last.
    assert _names(ordered)[-1] == "c"
    assert _names(ordered).index("b") < _names(ordered).index("c")


# ---------------------------------------------------------------------------
# Survival of unsuppressable cycles
# ---------------------------------------------------------------------------


def test_genuine_cycle_still_raises_when_overrides_do_not_break_it():
    """If neither pass declares overrides, a real cycle still raises ValueError.

    The override mechanism is opt-in; a missing override declaration on
    a genuine secondary writer still surfaces the cycle as a ValueError
    (registration-time signal that the spec author needs to add overrides=).
    """
    a = _make_pass("a", requires=("d",), produces=("height",))
    b = _make_pass("b", requires=("height",), produces=("d",))
    with pytest.raises(ValueError, match="cycle detected"):
        _toposort_passes([a, b])


# ---------------------------------------------------------------------------
# Integration: the real default registry must load without ValueError
# ---------------------------------------------------------------------------


def test_register_default_passes_loads_without_cycle_error():
    """The full default registry topologically sorts cleanly under override-aware edges.

    Before PR #3 this raised ``ValueError: cycle detected in pass dependency
    graph involving: [...]`` because passes like ``terrain_banded``,
    ``terrain_morphology``, ``terrain_glacial`` all override ``height`` and
    require it — a dual-cycle the old toposort could not resolve. With the
    override-aware edge build this is now a clean DAG.
    """
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )

    # Reset the registry so this test is hermetic regardless of import order.
    TerrainPassController.PASS_REGISTRY.clear()

    # Should not raise. Specifically must not raise ValueError("cycle detected").
    register_default_passes(strict=False)

    # And the registry should actually contain passes after a successful load.
    assert len(TerrainPassController.PASS_REGISTRY) > 0
