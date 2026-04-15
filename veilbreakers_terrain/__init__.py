"""veilbreakers-terrain — terrain / environment / water / biome generation.

Extracted from veilbreakers-gamedev-toolkit in Phase 50 via git filter-repo.
Depends on veilbreakers-mcp (the toolkit) for shared primitives (mesh, material,
vegetation, road_network) via an editable sibling-disk install.

See the toolkit's `.planning/phases/50-terrain-repo-extraction/` for the full
split rationale and rollback instructions.
"""

from veilbreakers_terrain.handlers import register_all  # noqa: F401

__version__ = "0.1.0"
__all__ = ["register_all", "__version__"]
