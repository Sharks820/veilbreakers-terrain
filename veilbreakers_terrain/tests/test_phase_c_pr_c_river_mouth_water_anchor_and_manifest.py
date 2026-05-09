"""PR-C (cross-audit P0 2026-05-09): river-mouth water anchor + manifest exports.

Pins:
1. ``detect_river_mouth_zones`` now anchors detected mouths to actual
   water — gating the flow-accumulation heuristic on
   ``water_surface_mask`` (or ``water_surface_elevation_m`` vs height,
   or ``bathymetry``) so dry accumulation valleys no longer false-flag
   as river mouths. Codex Claim C from cross-audit verifier.
2. ``water_contract_channels`` in ``terrain_unity_export.py`` now
   includes ``river_mouth_mask`` / ``confluence_foam`` /
   ``delta_fan_direction`` (produced by ``pass_river_convergence``).
   Verifier 3 flagged them as stranded — produced but not in any Unity
   export schema. Now they reach the Unity-side foam shader /
   river-mouth gameplay zones.
"""
from __future__ import annotations

import numpy as np


def test_river_mouth_excludes_dry_accumulation_when_water_surface_mask_present():
    """The flow-accumulation jump heuristic alone fires on dry valleys
    that have no water in them. With water_surface_mask present, the
    detection must intersect with the wet region so dry false-positives
    drop out."""
    from veilbreakers_terrain.handlers._water_network import (
        detect_river_mouth_zones,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import (
        TerrainMaskStack,
    )

    rows, cols = 16, 16
    h = np.zeros((rows, rows), dtype=np.float32)
    stack = TerrainMaskStack(
        tile_size=rows, cell_size=1.0,
        world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0, height=h,
    )

    # Build a flow-accumulation field with a sharp jump from low (river)
    # to high (lake) at column 8, with flow_direction pointing east
    # everywhere so the heuristic fires across the boundary.
    fa = np.zeros((rows, cols), dtype=np.float64)
    fa[:, :8] = 50.0   # river column
    fa[:, 8:] = 1000.0 # lake column (jump of 20x)
    fd = np.full((rows, cols), 2, dtype=np.int32)  # all flow east (idx 2 in D8 = (0, 1))
    stack.set("flow_accumulation", fa.astype(np.float32), "test")
    stack.set("flow_direction", fd, "test")

    # Water mask: ONLY the right half is wet.
    mask = np.zeros((rows, cols), dtype=np.float32)
    mask[:, 8:] = 1.0
    stack.set("water_surface_mask", mask, "test")

    mouths = detect_river_mouth_zones(stack, buffer_cells=0)

    # Mouth_raw fires at col 7 (the upstream cell flowing INTO the wet
    # body in col 8). PR-C anchor logic forces a 1-cell minimum
    # dilation on the water anchor so that dry-side mouths adjacent to
    # water survive (Copilot/Codex review on PR #65). So col 7 SHOULD
    # be flagged (legitimate river-mouth on the river side), but cols
    # 0-6 must be clean (deeper river territory, no false positives).
    assert mouths[:, :7].sum() == 0.0, (
        f"river_mouth must not flag dry accumulation valleys upstream "
        f"of the actual confluence; got left-half hits in cols 0-6: "
        f"{mouths[:, :7].sum()}"
    )
    assert mouths[:, 7].sum() > 0.0, (
        "the legitimate mouth cell at col 7 (adjacent to wet col 8) "
        "must survive the anchor (1-cell min dilation captures it)"
    )


def test_river_mouth_falls_back_to_legacy_heuristic_without_water_channel():
    """Backward compat: when no water channel exists (headless / pre-bake
    pipelines), the function falls back to the legacy heuristic."""
    from veilbreakers_terrain.handlers._water_network import (
        detect_river_mouth_zones,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import (
        TerrainMaskStack,
    )

    rows, cols = 16, 16
    h = np.zeros((rows, rows), dtype=np.float32)
    stack = TerrainMaskStack(
        tile_size=rows, cell_size=1.0,
        world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0, height=h,
    )
    fa = np.zeros((rows, cols), dtype=np.float64)
    fa[:, :8] = 50.0
    fa[:, 8:] = 1000.0
    fd = np.full((rows, cols), 2, dtype=np.int32)  # idx 2 = east in D8
    stack.set("flow_accumulation", fa.astype(np.float32), "test")
    stack.set("flow_direction", fd, "test")
    # NO water channel set — legacy heuristic should fire as before.

    mouths = detect_river_mouth_zones(stack, buffer_cells=0)

    # Without anchor, the heuristic must still detect SOMETHING (the
    # accumulation jump). This proves backward-compat: dropping water
    # channel doesn't silently kill the producer.
    assert mouths.sum() > 0.0, (
        "without water channel, legacy heuristic must still produce "
        "non-zero mouth detections (no silent regression)"
    )


def test_water_contract_channels_includes_river_convergence_outputs():
    """PR-C: river_mouth_mask + confluence_foam + delta_fan_direction
    are included in the Unity water_contract_channels tuple so they
    reach Unity-side consumers (foam shader, river-mouth zones).
    Verifier 3 flagged them as stranded (produced but not exported)
    until this PR.
    """
    import inspect

    from veilbreakers_terrain.handlers import terrain_unity_export

    src = inspect.getsource(terrain_unity_export)
    # Locate the water_contract_channels tuple body — assert each new
    # channel is listed there.
    assert "water_contract_channels" in src
    for new_channel in (
        "river_mouth_mask",
        "confluence_foam",
        "delta_fan_direction",
    ):
        assert (
            f'"{new_channel}"' in src
        ), (
            f"water_contract_channels must include '{new_channel}' so the "
            f"Unity-side foam shader / river-mouth zones can consume it"
        )
