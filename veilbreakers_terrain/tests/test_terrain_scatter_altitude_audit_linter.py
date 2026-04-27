from __future__ import annotations

from pathlib import Path

from veilbreakers_terrain.handlers.terrain_scatter_altitude_audit_linter import (
    audit_scatter_altitude_conversion,
)


def test_environment_scatter_is_clean_of_forbidden_altitude_normalization():
    source = Path("veilbreakers_terrain/handlers/environment_scatter.py").read_text(
        encoding="utf-8"
    )
    assert audit_scatter_altitude_conversion(source) == []
