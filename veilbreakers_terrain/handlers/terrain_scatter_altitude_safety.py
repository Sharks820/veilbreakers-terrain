"""Deprecated compatibility alias for the scatter altitude audit linter.

# DEAD CODE: no callers found outside terrain_scatter_altitude_audit_linter tests —
# candidate for removal in next cleanup. Use terrain_scatter_altitude_audit_linter
# directly; this shim exists only to preserve old import paths.
"""

from .terrain_scatter_altitude_audit_linter import (
    WORLD_HEIGHT_TRANSFORM_WARNING,
    audit_scatter_altitude_conversion,
)

__all__ = ["WORLD_HEIGHT_TRANSFORM_WARNING", "audit_scatter_altitude_conversion"]
