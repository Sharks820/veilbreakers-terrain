"""VeilBreakers MCP — Blender server dispatch layer.

Thin MCP-facing shim that maps human-readable location / action keys
(``"cave"``, ``"waterfall"``, ``"road"``, ``"mesh_smooth"`` ...) to
canonical ``veilbreakers_terrain.handlers.COMMAND_HANDLERS`` entries.

Public surface (re-exported for convenient import):

    from veilbreakers_mcp import dispatch, resolve_command, list_locations

The underlying ``_LOC_HANDLERS`` mapping is also re-exported so tests
can assert the vocabulary without touching the private module.
"""

from __future__ import annotations

from .blender_server import (
    _LOC_HANDLERS,
    dispatch,
    list_locations,
    resolve_command,
)

__all__ = [
    "dispatch",
    "resolve_command",
    "list_locations",
    "_LOC_HANDLERS",
]
