"""Blender MCP server — command dispatch stub.

_LOC_HANDLERS maps MCP location-action keys to terrain command names.
"""
from __future__ import annotations

_LOC_HANDLERS: dict[str, str] = {
    "cave": "terrain_generate_cave",
    "waterfall": "env_generate_waterfall",
    "coastline": "env_generate_coastline",
    "road": "env_compute_road_network",
}
