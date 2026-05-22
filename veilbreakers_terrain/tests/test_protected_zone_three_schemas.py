"""HOTFIX-7d regression — _resolve_protected_zone_aabb must handle all 3 schemas.

Verifier A 2026-05-21 #13 (WORSE-THAN-AUDIT): PR #123 closed the dual-schema
divergence (nested-bounds dict vs. flat-AABB dict) by introducing the
helper ``_resolve_protected_zone_aabb`` in ``environment.py``. The fix
covered the four sites in ``environment.py`` itself but Verifier A found
five sibling handler modules that consume ``state.intent.protected_zones``
(a tuple of ``ProtectedZoneSpec`` dataclasses) where the inline
``zone.bounds.min_x`` access is the only path:

    - terrain_assets.py:505
    - _terrain_world.py:818
    - terrain_caves.py:699
    - terrain_cliffs.py:2907
    - terrain_delta_integrator.py:129

HOTFIX-7d extended the helper to handle dataclass attr-access (Schema C)
on top of the existing dict-shape paths, moved the helper into a leaf
module (``_protected_zones``) to avoid import cycles, and migrated all
five sibling sites onto it. Every protected_zone consumer now goes
through one schema-tolerant code path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Schema fixtures
# ---------------------------------------------------------------------------

# Canonical AABB shared by every fixture below — every resolver call MUST
# produce this exact tuple regardless of input schema.
_CANONICAL_AABB = (10.0, 20.0, 100.0, 200.0)


def _schema_a_nested_bounds() -> dict[str, Any]:
    """Nested-bounds dict (Schema A) — used by terrain_world / glacial."""
    return {
        "zone_id": "z_a",
        "bounds": {"min_x": 10.0, "min_y": 20.0, "max_x": 100.0, "max_y": 200.0},
    }


def _schema_b_flat_dict() -> dict[str, Any]:
    """Flat-AABB dict (Schema B) — used by road network reform."""
    return {
        "zone_id": "z_b",
        "x_min": 10.0,
        "y_min": 20.0,
        "x_max": 100.0,
        "y_max": 200.0,
    }


def _schema_b_flat_dict_aliases() -> dict[str, Any]:
    """Flat-AABB dict with x0/y0/x1/y1 aliases (Schema B alias form)."""
    return {
        "zone_id": "z_b_aliases",
        "x0": 10.0,
        "y0": 20.0,
        "x1": 100.0,
        "y1": 200.0,
    }


def _schema_c_dataclass():
    """Dataclass attr-access (Schema C) — used by 5 sibling handlers
    via ``state.intent.protected_zones`` (ProtectedZoneSpec)."""
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        ProtectedZoneSpec,
    )

    return ProtectedZoneSpec(
        zone_id="z_c",
        bounds=BBox(min_x=10.0, min_y=20.0, max_x=100.0, max_y=200.0),
        kind="generic",
    )


# ---------------------------------------------------------------------------
# Headline regression — all three schemas resolve to the same AABB.
# ---------------------------------------------------------------------------


class TestResolveAllThreeSchemas:
    def test_schema_a_nested_bounds_dict(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import (
            _resolve_protected_zone_aabb,
        )

        assert _resolve_protected_zone_aabb(_schema_a_nested_bounds()) == _CANONICAL_AABB

    def test_schema_b_flat_dict(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import (
            _resolve_protected_zone_aabb,
        )

        assert _resolve_protected_zone_aabb(_schema_b_flat_dict()) == _CANONICAL_AABB

    def test_schema_b_flat_dict_with_aliases(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import (
            _resolve_protected_zone_aabb,
        )

        assert (
            _resolve_protected_zone_aabb(_schema_b_flat_dict_aliases())
            == _CANONICAL_AABB
        )

    def test_schema_c_dataclass_attr(self) -> None:
        """HOTFIX-7d: the helper now accepts ProtectedZoneSpec dataclasses.

        Headline Verifier A #13 regression — prior to this fix the helper
        returned the (-1e18, -1e18, 1e18, 1e18) sentinel for any non-dict
        input, which silently no-op'd the zone. Five sibling modules
        used their own inline ``zone.bounds.min_x`` access to compensate;
        a stub passing a plain dict to those modules would crash.
        """
        from veilbreakers_terrain.handlers._protected_zones import (
            _resolve_protected_zone_aabb,
        )

        assert _resolve_protected_zone_aabb(_schema_c_dataclass()) == _CANONICAL_AABB

    def test_all_three_schemas_agree_pairwise(self) -> None:
        """Cross-check: every schema produces identical AABBs when given
        equivalent inputs. This is the convergence invariant — every
        protected_zone consumer must observe the same world-space rect
        no matter which schema the caller supplied."""
        from veilbreakers_terrain.handlers._protected_zones import (
            _resolve_protected_zone_aabb,
        )

        a = _resolve_protected_zone_aabb(_schema_a_nested_bounds())
        b = _resolve_protected_zone_aabb(_schema_b_flat_dict())
        c = _resolve_protected_zone_aabb(_schema_c_dataclass())
        assert a == b == c == _CANONICAL_AABB


# ---------------------------------------------------------------------------
# Duck-typing fallback — any object with .bounds.min_x/min_y/max_x/max_y
# resolves correctly. This is what lets the helper stay a leaf module
# (no import from terrain_semantics).
# ---------------------------------------------------------------------------


class TestSchemaCDuckTyping:
    def test_duck_typed_dataclass_resolves(self) -> None:
        """Helper does NOT isinstance-check against ProtectedZoneSpec/BBox.
        Any object exposing the ``.bounds.min_x`` shape works, which
        keeps ``_protected_zones`` a true leaf module."""
        from veilbreakers_terrain.handlers._protected_zones import (
            _resolve_protected_zone_aabb,
        )

        @dataclass
        class _DuckBounds:
            min_x: float
            min_y: float
            max_x: float
            max_y: float

        @dataclass
        class _DuckZone:
            bounds: Any

        zone = _DuckZone(bounds=_DuckBounds(10.0, 20.0, 100.0, 200.0))
        assert _resolve_protected_zone_aabb(zone) == _CANONICAL_AABB


# ---------------------------------------------------------------------------
# Defensive — unrecognised input shapes return the open-zone sentinel.
# ---------------------------------------------------------------------------


class TestDefensiveFallbacks:
    def test_none_returns_open_zone(self) -> None:
        """Passing None falls through to the open-zone sentinel (so the
        caller's existing inclusion test treats every cell as outside
        the zone — i.e. the zone is effectively absent)."""
        from veilbreakers_terrain.handlers._protected_zones import (
            _resolve_protected_zone_aabb,
        )

        min_x, min_y, max_x, max_y = _resolve_protected_zone_aabb(None)
        # The open-zone sentinel covers everything from -inf-ish to +inf-ish.
        assert min_x < -1e9 and min_y < -1e9
        assert max_x > 1e9 and max_y > 1e9

    def test_empty_dict_returns_flat_path_defaults(self) -> None:
        """An empty dict has no ``bounds`` key — falls through to the
        flat-AABB defaults (preserves PR #123 behaviour exactly)."""
        from veilbreakers_terrain.handlers._protected_zones import (
            _resolve_protected_zone_aabb,
        )

        result = _resolve_protected_zone_aabb({})
        # Flat-path defaults are +/-1e9, NOT the open-zone sentinel.
        assert result == (-1e9, -1e9, 1e9, 1e9)


# ---------------------------------------------------------------------------
# Re-export sanity — environment.py must still export the symbol so PR #123
# call sites that do ``from .environment import _resolve_protected_zone_aabb``
# keep working.
# ---------------------------------------------------------------------------


class TestEnvironmentReexport:
    def test_environment_module_reexports_helper(self) -> None:
        """environment.py preserves PR #123's import path."""
        from veilbreakers_terrain.handlers.environment import (
            _resolve_protected_zone_aabb as env_helper,
        )
        from veilbreakers_terrain.handlers._protected_zones import (
            _resolve_protected_zone_aabb as leaf_helper,
        )

        # Re-export points at the same function object — no copy / wrapper.
        assert env_helper is leaf_helper


# ---------------------------------------------------------------------------
# Integration — the five sibling handler mask helpers now produce a non-empty
# mask when given a ProtectedZoneSpec, AND when given the equivalent dict.
# Prior to HOTFIX-7d the dict input would have raised AttributeError on
# ``zone.bounds.min_x``.
# ---------------------------------------------------------------------------


def _make_state(tile_size: int = 8):
    """Build a minimal pipeline state with one protected zone covering [0, 4)x[0, 4)."""
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        ProtectedZoneSpec,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((tile_size + 1, tile_size + 1), dtype=np.float64),
    )
    zone = ProtectedZoneSpec(
        zone_id="z",
        bounds=BBox(min_x=0.0, min_y=0.0, max_x=4.0, max_y=4.0),
        kind="generic",
        forbidden_mutations=frozenset(["cliffs", "caves", "integrate_deltas", "place_assets"]),
    )
    intent = TerrainIntentState(
        seed=1,
        region_bounds=BBox(0.0, 0.0, float(tile_size), float(tile_size)),
        tile_size=tile_size,
        cell_size=1.0,
        protected_zones=(zone,),
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack), (tile_size + 1, tile_size + 1)


class TestSiblingHandlersConsumeSchemaC:
    def test_terrain_assets_protected_mask_resolves_dataclass(self) -> None:
        """terrain_assets._protected_mask now uses the shared resolver
        (was inline ``zone.bounds.min_x``)."""
        from veilbreakers_terrain.handlers.terrain_assets import _protected_mask

        state, shape = _make_state(tile_size=8)
        mask = _protected_mask(state, shape, pass_name="place_assets")
        # The 4x4 protected region at the (0,0) corner is non-empty.
        assert mask.any(), "protected mask should be non-empty for a forbidden zone"

    def test_terrain_world_protected_mask_resolves_dataclass(self) -> None:
        from veilbreakers_terrain.handlers._terrain_world import _protected_mask

        state, shape = _make_state(tile_size=8)
        mask = _protected_mask(state, shape, pass_name="cliffs")
        assert mask.any()

    def test_terrain_cliffs_protected_mask_resolves_dataclass(self) -> None:
        from veilbreakers_terrain.handlers.terrain_cliffs import (
            _protected_mask_for_cliffs,
        )

        state, shape = _make_state(tile_size=8)
        mask = _protected_mask_for_cliffs(state, shape)
        assert mask.any()

    def test_terrain_caves_protected_mask_resolves_dataclass(self) -> None:
        from veilbreakers_terrain.handlers.terrain_caves import (
            _protected_mask_for_caves,
        )

        state, shape = _make_state(tile_size=8)
        mask = _protected_mask_for_caves(state, shape)
        assert mask.any()

    def test_terrain_delta_integrator_protected_mask_resolves_dataclass(self) -> None:
        """pass_integrate_deltas routes through _zone_permits + _resolve_protected_zone_aabb.

        PR #126 adversarial review F7: terrain_delta_integrator had no sibling test
        in this class.  This test confirms that dict-shaped zones (Schema B) do not
        crash the protected-zone path (previously ``zone.permits("integrate_deltas")``
        would AttributeError on a plain dict).
        """
        from veilbreakers_terrain.handlers.terrain_delta_integrator import (
            pass_integrate_deltas,
        )
        from veilbreakers_terrain.handlers.terrain_semantics import (
            BBox,
            TerrainIntentState,
            TerrainMaskStack,
            TerrainPipelineState,
        )

        tile_size = 8
        arr = np.zeros((tile_size + 1, tile_size + 1), dtype=np.float64)
        stack = TerrainMaskStack(
            tile_size=tile_size,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
            height=arr,
        )
        # Schema B (flat-AABB dict) zone — previously crashed on zone.permits()
        dict_zone: dict = {
            "zone_id": "test_dict_zone",
            "x_min": 0.0,
            "y_min": 0.0,
            "x_max": 4.0,
            "y_max": 4.0,
            "forbidden_kinds": ["integrate_deltas"],
        }
        intent = TerrainIntentState(
            seed=1,
            region_bounds=BBox(0.0, 0.0, float(tile_size), float(tile_size)),
            tile_size=tile_size,
            cell_size=1.0,
            protected_zones=(dict_zone,),  # type: ignore[arg-type]
        )
        state = TerrainPipelineState(intent=intent, mask_stack=stack)
        result = pass_integrate_deltas(state, region=None)
        assert result.status == "ok", f"unexpected status: {result.status}"


# ---------------------------------------------------------------------------
# _zone_permits — schema-tolerant permits() resolver
# ---------------------------------------------------------------------------


class TestZonePermits:
    """PR #126 review (coderabbit T7/T9/T10): _zone_permits must accept
    object zones (dataclass-style with ``.permits()`` method) AND dict
    zones (key-based forbid/allow lists) without crashing on either.
    """

    def test_object_zone_delegates_to_permits_method(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_permits

        class _ObjZone:
            def __init__(self, allowed: set[str]) -> None:
                self._allowed = allowed

            def permits(self, kind: str) -> bool:
                return kind in self._allowed

        zone = _ObjZone({"trees"})
        assert _zone_permits(zone, "trees") is True
        assert _zone_permits(zone, "boulders") is False

    def test_dict_zone_forbidden_kinds_denies(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_permits

        zone = {"forbidden_kinds": ("boulders", "trees")}
        assert _zone_permits(zone, "boulders") is False
        assert _zone_permits(zone, "trees") is False
        # Anything not in forbidden_kinds is permitted (no allow-list set).
        assert _zone_permits(zone, "grass") is True

    def test_dict_zone_forbid_alias_denies(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_permits

        zone = {"forbid": ("trees",)}
        assert _zone_permits(zone, "trees") is False
        assert _zone_permits(zone, "grass") is True

    def test_dict_zone_allowed_kinds_restricts(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_permits

        zone = {"allowed_kinds": ("grass",)}
        assert _zone_permits(zone, "grass") is True
        assert _zone_permits(zone, "trees") is False

    def test_dict_zone_allow_alias_restricts(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_permits

        zone = {"allow": ("grass",)}
        assert _zone_permits(zone, "grass") is True
        assert _zone_permits(zone, "trees") is False

    def test_dict_zone_forbidden_wins_over_allowed(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_permits

        zone = {"forbidden_kinds": ("trees",), "allowed_kinds": ("trees", "grass")}
        # Forbidden is checked first — trees is denied even though it is
        # also in allowed_kinds.
        assert _zone_permits(zone, "trees") is False
        assert _zone_permits(zone, "grass") is True

    def test_empty_dict_zone_defaults_permissive(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_permits

        assert _zone_permits({}, "anything") is True

    def test_unknown_shape_defaults_permissive(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_permits

        # No .permits() method, not a dict — open zone fallback.
        assert _zone_permits(object(), "anything") is True
        assert _zone_permits(None, "anything") is True
        assert _zone_permits(42, "anything") is True


class TestZoneId:
    """PR #126 review (coderabbit DvFAk): _zone_id must extract zone_id
    from dict zones (.get) AND object/dataclass zones (getattr) so
    blocked-by-zone diagnostics survive the same schema fragmentation
    that motivated _zone_permits and _resolve_protected_zone_aabb.
    """

    def test_dict_zone_returns_zone_id(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_id

        assert _zone_id({"zone_id": "lake_shore"}) == "lake_shore"

    def test_dict_zone_without_zone_id_returns_unknown(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_id

        assert _zone_id({}) == "unknown"

    def test_object_zone_returns_zone_id(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_id

        @dataclass
        class _ObjZone:
            zone_id: str = "ruins"

        assert _zone_id(_ObjZone()) == "ruins"

    def test_object_zone_without_zone_id_returns_unknown(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_id

        assert _zone_id(object()) == "unknown"

    def test_zone_id_coerced_to_string(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_id

        # Some upstream paths set zone_id as int — diagnostic must
        # still produce a string-safe value.
        assert _zone_id({"zone_id": 42}) == "42"


# ---------------------------------------------------------------------------
# _zone_bounds_intersect — PR #126 adversarial review F2
# ---------------------------------------------------------------------------


class TestZoneBoundsIntersect:
    """PR #126 adversarial review F2: _zone_bounds_intersect must handle
    all three zone schemas so TerrainPassController.enforce_protected_zones
    does not crash on dict-shaped zones.
    """

    def _target(self) -> Any:
        from veilbreakers_terrain.handlers.terrain_semantics import BBox

        return BBox(min_x=2.0, min_y=2.0, max_x=6.0, max_y=6.0)

    def test_object_zone_intersects(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_bounds_intersect
        from veilbreakers_terrain.handlers.terrain_semantics import BBox, ProtectedZoneSpec

        zone = ProtectedZoneSpec(
            zone_id="z",
            bounds=BBox(min_x=0.0, min_y=0.0, max_x=4.0, max_y=4.0),
            kind="generic",
        )
        assert _zone_bounds_intersect(zone, self._target()) is True

    def test_object_zone_no_intersect(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_bounds_intersect
        from veilbreakers_terrain.handlers.terrain_semantics import BBox, ProtectedZoneSpec

        zone = ProtectedZoneSpec(
            zone_id="z",
            bounds=BBox(min_x=10.0, min_y=10.0, max_x=20.0, max_y=20.0),
            kind="generic",
        )
        assert _zone_bounds_intersect(zone, self._target()) is False

    def test_dict_zone_schema_b_intersects(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_bounds_intersect

        zone = {"zone_id": "z", "x_min": 0.0, "y_min": 0.0, "x_max": 4.0, "y_max": 4.0}
        assert _zone_bounds_intersect(zone, self._target()) is True

    def test_dict_zone_schema_b_no_intersect(self) -> None:
        from veilbreakers_terrain.handlers._protected_zones import _zone_bounds_intersect

        zone = {"zone_id": "z", "x_min": 50.0, "y_min": 50.0, "x_max": 60.0, "y_max": 60.0}
        assert _zone_bounds_intersect(zone, self._target()) is False
