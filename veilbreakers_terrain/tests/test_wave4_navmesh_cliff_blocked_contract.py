"""End-to-end contract test: the cliff_blocked value in a navmesh JSON export
must exactly match the NAVMESH_CLIFF_BLOCKED constant.

Background (WAVE4-NAVMESH-CONTRACT-MISMATCH-001):
  terrain_navmesh_export.NAVMESH_CLIFF_BLOCKED == 64, but the docstring for
  export_navmesh_json() previously stated "cliff_blocked: 255". Any NPC
  pathfinding consumer reading the docstring would use the wrong blocking
  sentinel. The docstring has been corrected to 64.

  This test pins the end-to-end contract so that future changes to the constant
  or the legend dict are caught immediately by CI, regardless of whether the
  docstring is also updated.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _flat_stack(size: int = 4):
    """Return a TerrainMaskStack with a flat terrain (no slopes → all walkable)."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    height = np.zeros((size, size), dtype=np.float32)
    return TerrainMaskStack(
        tile_size=size,
        cell_size=2.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )


def _steep_stack(size: int = 4):
    """Return a stack where the entire terrain is slope > 60° → all cliff_blocked."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    # Ramp from 0 to 600 m across 4 cells of 2 m each → ~80° slope.
    height = np.zeros((size, size), dtype=np.float32)
    for i in range(size):
        height[i, :] = float(i) * 200.0
    return TerrainMaskStack(
        tile_size=size,
        cell_size=2.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )


def test_exported_json_area_ids_cliff_blocked_matches_constant(tmp_path: Path) -> None:
    """area_ids.cliff_blocked in the written JSON must equal NAVMESH_CLIFF_BLOCKED."""
    from veilbreakers_terrain.handlers.terrain_navmesh_export import (
        NAVMESH_CLIFF_BLOCKED,
        export_navmesh_json,
    )

    out_file = tmp_path / "navmesh.json"
    export_navmesh_json(_flat_stack(), out_file)

    data = json.loads(out_file.read_text(encoding="utf-8"))
    exported_value = data["area_ids"]["cliff_blocked"]

    assert exported_value == NAVMESH_CLIFF_BLOCKED, (
        f"Exported cliff_blocked={exported_value} does not match "
        f"NAVMESH_CLIFF_BLOCKED={NAVMESH_CLIFF_BLOCKED}. "
        "Update _AREA_LEGEND or the constant — do NOT just fix the docstring."
    )


def test_exported_json_area_ids_cliff_blocked_is_64(tmp_path: Path) -> None:
    """Absolute pin: cliff_blocked in the JSON legend must be 64.

    This test intentionally hard-codes 64 (not the constant) so that any
    change to the constant value is caught here and forces a deliberate
    decision — the consuming Unity/Unreal side also needs updating if the
    value changes.
    """
    from veilbreakers_terrain.handlers.terrain_navmesh_export import export_navmesh_json

    out_file = tmp_path / "navmesh_pin.json"
    export_navmesh_json(_flat_stack(), out_file)

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["area_ids"]["cliff_blocked"] == 64, (
        "cliff_blocked changed from 64. If this is intentional, update the Unity "
        "NavMesh area IDs and the docstring in export_navmesh_json."
    )


def test_steep_terrain_stats_cliff_blocked_fraction_uses_correct_sentinel(
    tmp_path: Path,
) -> None:
    """On a steep terrain the stats.cliff_blocked_fraction must be > 0.

    This verifies that the stat aggregation in export_navmesh_json uses
    NAVMESH_CLIFF_BLOCKED (64) — not 255 or some other stale value — to count
    cliff-blocked cells.
    """
    from veilbreakers_terrain.handlers.terrain_navmesh_export import export_navmesh_json

    out_file = tmp_path / "steep_navmesh.json"
    descriptor = export_navmesh_json(_steep_stack(), out_file)

    cliff_fraction = descriptor["stats"]["cliff_blocked_fraction"]
    assert cliff_fraction > 0.0, (
        "Expected cliff_blocked_fraction > 0 on a steep terrain, but got "
        f"{cliff_fraction}. The stats counter may be using the wrong sentinel."
    )
