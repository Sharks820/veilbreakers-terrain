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

from typing import Any

# Pyright: ``_resolve_protected_zone_aabb`` is intentionally underscored
# (consistent with the PR #123 helper name imported by every consumer) but
# it IS exported across the package via __all__ — every handler module
# imports it through the cross-module path
# ``from ._protected_zones import _resolve_protected_zone_aabb``. Declaring
# it in __all__ silences ``reportUnusedFunction`` without renaming the
# symbol (which would break PR #123's existing call sites).
__all__ = ["_resolve_protected_zone_aabb"]


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
    bounds_obj = getattr(pz, "bounds", None)
    if bounds_obj is not None and hasattr(bounds_obj, "min_x"):
        return (
            float(bounds_obj.min_x),
            float(bounds_obj.min_y),
            float(bounds_obj.max_x),
            float(bounds_obj.max_y),
        )
    # Defensive: caller passed something the resolver doesn't recognise —
    # treat as an open zone so downstream logic falls through to its existing
    # "no zone" branch instead of crashing.
    return (-1e18, -1e18, 1e18, 1e18)
