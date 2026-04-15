"""veilbreakers_terrain.handlers — terrain handler registration surface.

The 105 handler modules live alongside this file. Registration is delegated
to ``terrain_master_registrar.register_all_terrain_passes``; this module just
re-exports a slim ``register_all()`` that the toolkit's preflight hook (D-07)
and downstream tooling can call without knowing the registrar's internals.
"""

from __future__ import annotations

from typing import Any


def register_all(strict: bool = False) -> Any:
    """Register all terrain passes.

    Replaces the legacy
    ``blender_addon.handlers.terrain_master_registrar.register_all_terrain_passes``
    call site used by the toolkit prior to Phase 50.

    Parameters
    ----------
    strict:
        If True, raise on first registration error. If False (default),
        swallow per-pass failures and log — matches legacy behaviour.

    Returns
    -------
    Whatever ``register_all_terrain_passes`` returns (currently a
    registration report; see ``terrain_master_registrar``).
    """
    # Lazy import so importing this package does not require bpy at collect-time.
    from .terrain_master_registrar import register_all_terrain_passes

    return register_all_terrain_passes(strict=strict)


__all__ = ["register_all"]
