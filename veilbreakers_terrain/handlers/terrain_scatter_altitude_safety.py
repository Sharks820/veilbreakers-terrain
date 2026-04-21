"""Deprecated compatibility alias for the scatter altitude audit linter."""

from .terrain_scatter_altitude_audit_linter import (
    WORLD_HEIGHT_TRANSFORM_WARNING,
    audit_scatter_altitude_conversion,
)

__all__ = ["WORLD_HEIGHT_TRANSFORM_WARNING", "audit_scatter_altitude_conversion"]
