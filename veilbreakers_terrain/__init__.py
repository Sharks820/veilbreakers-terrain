"""veilbreakers-terrain — terrain / environment / water / biome generation.

Extracted from veilbreakers-gamedev-toolkit in Phase 50 via git filter-repo.
Depends on veilbreakers-mcp (the toolkit) for shared primitives (mesh, material,
vegetation, road_network) via an editable sibling-disk install.

See the toolkit's `.planning/phases/50-terrain-repo-extraction/` for the full
split rationale and rollback instructions.
"""

from veilbreakers_terrain.handlers import register_all  # noqa: F401

bl_info = {
    "name": "VeilBreakers Terrain",
    "author": "VeilBreakers Team",
    "version": (1, 0, 0),
    "blender": (4, 5, 0),
    "category": "Object",
}

__version__ = "0.1.0"

# Module-level MCP server singleton — socket callbacks call
# veilbreakers_terrain._mcp_server.enqueue({"command": ..., "params": ...})
_mcp_server = None


def register() -> None:
    """Blender addon register hook — called when the addon is enabled.

    Starts the MCP command queue timer (10 ms poll) so external tools
    can send commands to COMMAND_HANDLERS via the BlenderMCPServer queue.
    """
    global _mcp_server
    try:
        import bpy
        from veilbreakers_terrain.socket_server import BlenderMCPServer
        _mcp_server = BlenderMCPServer()
        bpy.app.timers.register(_mcp_server._process_commands, persistent=True)
        register_all()
    except ModuleNotFoundError:
        # Not running inside Blender — skip timer registration (test/CI context).
        pass


def unregister() -> None:
    """Blender addon unregister hook — called when the addon is disabled.

    Removes the MCP timer to prevent dangling callbacks after disable/reload.
    """
    global _mcp_server
    if _mcp_server is None:
        return
    try:
        import bpy
        bpy.app.timers.unregister(_mcp_server._process_commands)
    except Exception:
        pass
    finally:
        _mcp_server = None


__all__ = ["register_all", "register", "unregister", "__version__", "bl_info"]
