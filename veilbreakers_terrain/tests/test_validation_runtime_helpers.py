"""Direct tests for validation reporting and adapter helper contracts."""

from __future__ import annotations

import numpy as np


def test_validation_report_category_summary_and_issue_category_routes():
    from veilbreakers_terrain.handlers.terrain_semantics import ValidationIssue
    from veilbreakers_terrain.handlers.terrain_validation import ValidationReport, _issue_category

    report = ValidationReport()
    report.add(ValidationIssue(code="HEIGHT_NAN", severity="hard", message="bad height"))
    report.add(ValidationIssue(code="MAT_TEXEL_DENSITY", severity="soft", message="bad material"))
    report.add(ValidationIssue(code="UNKNOWN_NOTE", severity="info", message="note"))

    summary = report.category_summary()

    assert _issue_category("CLIFF_SCREEN_COVERAGE") == "readability"
    assert _issue_category("WATERFALL_CHAIN") == "water"
    assert _issue_category("UNKNOWN_NOTE") == "other"
    assert summary["geometry"] == {"hard": 1, "soft": 0, "info": 0}
    assert summary["materials"] == {"hard": 0, "soft": 1, "info": 0}
    assert summary["other"] == {"hard": 0, "soft": 0, "info": 1}


def test_readability_audit_validator_returns_flat_issues():
    from veilbreakers_terrain.handlers.terrain_semantics import BBox, TerrainIntentState, TerrainMaskStack
    from veilbreakers_terrain.handlers.terrain_validation import _readability_audit_validator

    stack = TerrainMaskStack(
        tile_size=3,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((3, 3), dtype=np.float32),
    )
    intent = TerrainIntentState(seed=1, region_bounds=BBox(0.0, 0.0, 3.0, 3.0), tile_size=3, cell_size=1.0)

    issues = _readability_audit_validator(stack, intent)

    assert isinstance(issues, list)
    assert all(hasattr(issue, "code") for issue in issues)
