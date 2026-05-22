"""Shared schema-tolerant helpers for protected_zone resolution.

Extracted as a separate leaf module so every handler that consumes
``state.intent.protected_zones`` (ProtectedZoneSpec dataclasses) and every
handler that consumes ``params["protected_zones"]`` (raw dict zones) can
share one resolver without creating import cycles.

PR #123 originally placed the resolver in ``environment.py``. That worked
for the four dict-shaped consumers in ``environment.py`` itself, but the
five sibling modules that iterate ``state.intent.protected_zones``
(``terrain_assets``, ``_terrain_world``, ``terrain_caves``,
``terrain_cliffs``, ``terrain_delta_integrator``) all import names that
``environment.py`` ALSO imports (TerrainMaskStack, TerrainPipelineState,
BBox, PassResult, …). Importing the helper back from ``environment.py``
into those modules would create a cycle, so the helper lives here.

HOTFIX-7d (Verifier A #13 2026-05-21): added Schema C (dataclass attr
access) on top of PR #123's Schema A + Schema B handling. See the
docstring on ``_resolve_protected_zone_aabb`` for the schema catalogue.
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

# Pyright: ``_resolve_protected_zone_aabb`` is intentionally underscored
# (consistent with the PR #123 helper name imported by every consumer) but
# it IS exported across the package via __all__ — every handler module
# imports it through the cross-module path
# ``from ._protected_zones import _resolve_protected_zone_aabb``. Declaring
# it in __all__ silences ``reportUnusedFunction`` without renaming the
# symbol (which would break PR #123's existing call sites).
__all__ = ["_resolve_protected_zone_aabb", "_zone_permits", "_zone_bounds_intersect", "_zone_id"]


def _resolve_protected_zone_aabb(
    pz: Any,
) -> tuple[float, float, float, float]:
    """Resolve a protected_zone into a world-space AABB tuple.

    Accepts all THREE historic schemas without silently dropping any:

    Schema A (nested-bounds dict, the canonical form built by
    ``_resolve_terrain_tile_params`` and consumed by terrain merge / glacial
    crater / structure placement)::

        {"zone_id": "...", "bounds": {"min_x": ..., "min_y": ...,
                                       "max_x": ..., "max_y": ...}}

    Schema B (flat-AABB dict, the form used by the road network reform
    handler and the seasonal-water basin clipper — also accepts
    ``x0/x1/y0/y1`` aliases shipped by some emitter-side callers)::

        {"zone_id": "...", "x_min": ..., "y_min": ..., "x_max": ..., "y_max": ...}
        {"zone_id": "...", "x0": ..., "y0": ..., "x1": ..., "y1": ...}

    Schema C (dataclass attr-access, the canonical form built by the
    pass-controller out of ``ProtectedZoneSpec`` instances that flow on
    ``state.intent.protected_zones`` — consumed by the asset / cliffs /
    caves / delta-integrator / terrain-world handlers)::

        ProtectedZoneSpec(zone_id=..., bounds=BBox(min_x, min_y, max_x, max_y), ...)

    Returns:
        ``(min_x, min_y, max_x, max_y)`` tuple suitable for use in either an
        inclusion test (``min_x <= wx <= max_x and min_y <= wy <= max_y``) or
        a mask broadcast.  The defaults — ``+/-1e18`` for the nested-bounds
        path, ``+/-1e9`` for the flat path — match the prior call-site
        sentinels and were preserved so downstream comparisons that relied
        on a "no-clip" zone (e.g. when only one axis was provided) continue
        to behave the same. WAVE-1-HOTFIX-2 Bug 3 (FIX_PATTERN_v1 §C3
        contract / schema unification): two of the six dict-shaped handler
        sites used the flat schema; calling them with a nested-bounds zone
        silently no-op'd the zone (every coord returned the +/-1e9 sentinel
        range), causing protected geometry to be paved through.

        HOTFIX-7d (Verifier A #13 2026-05-21): the original PR #123 helper
        only resolved Schema A + B (dict-shaped zones). The five handler
        sites that consume ``state.intent.protected_zones`` directly
        (``terrain_assets``, ``_terrain_world``, ``terrain_caves``,
        ``terrain_cliffs``, ``terrain_delta_integrator``) iterate over
        ``ProtectedZoneSpec`` dataclasses, not dicts — so each had its
        own inline ``zone.bounds.min_x`` access. Centralising those onto
        this resolver (Schema C) closes the convergence so every consumer
        goes through one schema-tolerant path, and the four handlers no
        longer carry duplicated dataclass-attribute access logic.
    """
    # None is a legitimate "no zone" signal (e.g. an optional zone param that
    # was not set by the caller).  Return the open-zone sentinel silently —
    # this is expected, not a silent-defeat case.
    if pz is None:
        return (-1e18, -1e18, 1e18, 1e18)
    if isinstance(pz, dict):
        bounds = pz.get("bounds")
        if isinstance(bounds, dict):
            return (
                float(bounds.get("min_x", -1e18)),
                float(bounds.get("min_y", -1e18)),
                float(bounds.get("max_x",  1e18)),
                float(bounds.get("max_y",  1e18)),
            )
        return (
            float(pz.get("x_min", pz.get("x0", -1e9))),
            float(pz.get("y_min", pz.get("y0", -1e9))),
            float(pz.get("x_max", pz.get("x1",  1e9))),
            float(pz.get("y_max", pz.get("y1",  1e9))),
        )
    # Schema C — dataclass instance (e.g. ProtectedZoneSpec) with a .bounds
    # attribute that itself exposes min_x / min_y / max_x / max_y. We use
    # getattr (not isinstance against ProtectedZoneSpec / BBox) so this
    # module stays a true leaf — no imports from terrain_semantics — and
    # therefore importable by every handler without cycle risk.
    #
    # PR #126 review (Copilot T1): require *all four* attrs (not just min_x)
    # so a partially-populated duck-typed object can't AttributeError at
    # read time — fall through to the open-zone sentinel instead.
    bounds_obj = getattr(pz, "bounds", None)
    if bounds_obj is not None and all(
        hasattr(bounds_obj, _attr) for _attr in ("min_x", "min_y", "max_x", "max_y")
    ):
        try:
            return (
                float(bounds_obj.min_x),
                float(bounds_obj.min_y),
                float(bounds_obj.max_x),
                float(bounds_obj.max_y),
            )
        except (TypeError, ValueError):
            # Attributes existed but weren't numeric — WAVE6-1 (CWE-749
            # silent-defeat risk): a partial/mock dataclass whose bounds attrs
            # are non-numeric would previously fall through silently to the
            # open-zone sentinel, which disables ALL zone protection.  Log a
            # loud warning so the caller can diagnose the bad input.
            _log.warning(
                "_resolve_protected_zone_aabb: bounds attrs exist but are not "
                "numeric on %s — returning open-zone sentinel "
                "(CWE-749 silent-defeat risk). Check that ProtectedZoneSpec.bounds "
                "carries real float values, not a mock or placeholder.",
                type(pz).__name__,
            )
            return (-1e18, -1e18, 1e18, 1e18)
    # WAVE6-1 (CWE-749 silent-defeat): caller passed a non-dict, non-None
    # value whose shape the resolver does NOT recognise (e.g. a dataclass
    # without a .bounds attribute, a string, or an unexpected wrapper type).
    # Previously silent — now emits a WARNING so call-graph evolution that
    # accidentally routes ProtectedZoneSpec instances here (or passes a
    # partial mock) is immediately visible in logs rather than silently
    # disabling all zone protection.
    _log.warning(
        "_resolve_protected_zone_aabb: unrecognised zone shape "
        "(type=%s, has_bounds=%s) — returning open-zone sentinel. "
        "Likely silent-defeat (CWE-749). Ensure the caller passes either "
        "a dict with x_min/y_min/x_max/y_max (Schema B) or a nested "
        "bounds dict (Schema A) or a ProtectedZoneSpec with .bounds "
        "attrs (Schema C).",
        type(pz).__name__,
        bounds_obj is not None,
    )
    return (-1e18, -1e18, 1e18, 1e18)


def _zone_permits(
    zone: Any,
    kind: str,
) -> bool:
    """Schema-tolerant zone.permits() — works with object zones (.permits method)
    AND dict-shaped zones (key-based forbid/allow lists).

    PR #126 review (coderabbit T7/T9/T10): three sibling handlers
    (``_terrain_world``, ``terrain_assets``, ``terrain_delta_integrator``)
    called ``zone.permits(kind)`` directly, which crashes when a caller
    supplies a dict-shaped zone instead of a ProtectedZoneSpec dataclass.
    This helper resolves both shapes so every consumer can use one call.

    Object zone: delegates to ``zone.permits(kind)`` unchanged.
    Dict zone: checks ``forbidden_kinds`` / ``forbid`` deny-list first,
               then ``allowed_kinds`` / ``allow`` allow-list.
               Unknown shape defaults permissive (open zone).
    """
    permits_method = getattr(zone, "permits", None)
    if callable(permits_method):
        return bool(permits_method(kind))
    if isinstance(zone, dict):
        forbidden = zone.get("forbidden_kinds") or zone.get("forbid") or ()
        if kind in forbidden:
            return False
        allowed = zone.get("allowed_kinds") or zone.get("allow")
        if allowed is not None:
            return kind in allowed
        return True
    return True  # unknown shape -> default permissive


def _zone_id(zone: Any) -> str:
    """Schema-tolerant zone_id accessor for `blocked_by_zone` reporting.

    PR #126 review (coderabbit DvFAk): the cave-entrance placement loop
    read ``pz.get("zone_id", "unknown") if isinstance(pz, dict) else "unknown"``
    which silently dropped the real zone_id for dataclass-backed zones
    (every ProtectedZoneSpec attached via state.intent.protected_zones).
    This helper unifies dict + attr access so blocked-by-zone diagnostics
    work across all three schemas the resolver already supports.
    """
    if isinstance(zone, dict):
        return str(zone.get("zone_id", "unknown"))
    return str(getattr(zone, "zone_id", "unknown"))


def _zone_bounds_intersect(zone: Any, target_bounds: Any) -> bool:
    """Schema-tolerant zone.bounds.intersects(target_bounds) — AABB-intersection
    that works whether zone is object-with-bounds-with-intersects,
    object-with-bounds-as-dict, or dict zone (all three schemas accepted by
    ``_resolve_protected_zone_aabb``).

    PR #126 adversarial review F2: ``TerrainPassController.enforce_protected_zones``
    called ``zone.bounds.intersects(target_bounds)`` directly, which crashes when
    a caller supplies a dict-shaped zone instead of a ProtectedZoneSpec.  This
    helper replaces that call so the pipeline-core enforcement is schema-tolerant.

    ``target_bounds`` is the typed ``BBox`` with ``.min_x/.min_y/.max_x/.max_y``
    or a 4-tuple ``(min_x, min_y, max_x, max_y)`` fallback.
    """
    z_min_x, z_min_y, z_max_x, z_max_y = _resolve_protected_zone_aabb(zone)
    if hasattr(target_bounds, "min_x"):
        t_min_x = float(target_bounds.min_x)
        t_min_y = float(target_bounds.min_y)
        t_max_x = float(target_bounds.max_x)
        t_max_y = float(target_bounds.max_y)
    else:
        t_min_x, t_min_y, t_max_x, t_max_y = target_bounds  # 4-tuple fallback
    return (
        z_min_x <= t_max_x
        and z_max_x >= t_min_x
        and z_min_y <= t_max_y
        and z_max_y >= t_min_y
    )
