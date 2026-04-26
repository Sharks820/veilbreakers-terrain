import csv
from pathlib import Path


def _write_matrix(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "file",
        "line",
        "callable",
        "kind",
        "domain",
        "subdomain",
        "criticality",
        "current_grade",
        "grade_status",
        "match_mode",
        "upgrade_tier",
        "best_practice_authorities",
        "best_practice_contract",
        "when_to_use",
        "do_not_use_for",
        "required_callable_setup",
        "upgrade_actions",
        "validation_gates",
        "anti_patterns_to_block",
        "required_output_artifacts",
        "implementation_phase",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _row(file_name: str, callable_name: str, domain: str = "hydrology") -> dict[str, str]:
    return {
        "file": file_name,
        "line": "10",
        "callable": callable_name,
        "kind": "function",
        "domain": domain,
        "subdomain": "test",
        "criticality": "critical",
        "current_grade": "",
        "grade_status": "MISSING_GRADE",
        "match_mode": "none",
        "upgrade_tier": "P0",
        "best_practice_authorities": "official docs",
        "best_practice_contract": "emit typed terrain channels",
        "when_to_use": "use for water systems",
        "do_not_use_for": "do not use for texturing",
        "required_callable_setup": "declare units and provenance",
        "upgrade_actions": "add direct tests",
        "validation_gates": "contract_tests|artifact_presence",
        "anti_patterns_to_block": "one_shot_scene_build",
        "required_output_artifacts": "manifest.json",
        "implementation_phase": "Phase 1",
    }


def test_guardrail_detects_missing_callable_matrix_rows(tmp_path):
    from scripts.terrain_best_practice_guardrail import (
        CallableKey,
        validate_matrix_against_callables,
    )

    matrix_path = tmp_path / "matrix.csv"
    _write_matrix(matrix_path, [_row("_water_network.py", "compute_velocity_field")])

    live = [
        CallableKey("_water_network.py", "compute_velocity_field"),
        CallableKey("terrain_materials.py", "compute_world_splatmap_weights"),
    ]

    report = validate_matrix_against_callables(matrix_path, live)

    assert report.missing_rows == [
        CallableKey("terrain_materials.py", "compute_world_splatmap_weights")
    ]
    assert report.is_blocking


def test_guardrail_requires_contract_gate_and_artifact_fields(tmp_path):
    from scripts.terrain_best_practice_guardrail import (
        CallableKey,
        validate_matrix_against_callables,
    )

    bad = _row("terrain_materials.py", "compute_world_splatmap_weights", "terrain_texturing")
    bad["validation_gates"] = ""
    bad["required_output_artifacts"] = ""
    matrix_path = tmp_path / "matrix.csv"
    _write_matrix(matrix_path, [bad])

    report = validate_matrix_against_callables(
        matrix_path,
        [CallableKey("terrain_materials.py", "compute_world_splatmap_weights")],
    )

    assert report.field_gaps == {
        "terrain_materials.py::compute_world_splatmap_weights": [
            "validation_gates",
            "required_output_artifacts",
        ]
    }
    assert report.is_blocking


def test_guardrail_strict_modes_block_duplicate_p0_and_non_a_rows(tmp_path):
    from scripts.terrain_best_practice_guardrail import (
        CallableKey,
        validate_matrix_against_callables,
    )

    row_a = _row("_water_network.py", "compute_velocity_field")
    row_a["current_grade"] = "B"
    row_a["grade_status"] = "GRADED"
    row_b = _row("terrain_materials.py", "compute_velocity_field", "terrain_texturing")
    row_b["current_grade"] = "A"
    row_b["grade_status"] = "GRADED"
    matrix_path = tmp_path / "matrix.csv"
    _write_matrix(matrix_path, [row_a, row_b])

    report = validate_matrix_against_callables(
        matrix_path,
        [
            CallableKey("_water_network.py", "compute_velocity_field"),
            CallableKey("terrain_materials.py", "compute_velocity_field"),
        ],
        block_duplicates=True,
        block_p0=True,
        require_a_grade=True,
    )

    assert "compute_velocity_field" in report.duplicate_names
    assert report.p0_rows
    assert report.non_a_rows == {"_water_network.py::compute_velocity_field": "B"}
    assert report.is_blocking


def test_guardrail_strict_grade_status_blocks_name_only_rows(tmp_path):
    from scripts.terrain_best_practice_guardrail import (
        CallableKey,
        validate_matrix_against_callables,
    )

    row = _row("_water_network.py", "compute_velocity_field")
    row["grade_status"] = "NAME_ONLY_MATCH"
    row["current_grade"] = "A"
    row["upgrade_tier"] = "P1"
    matrix_path = tmp_path / "matrix.csv"
    _write_matrix(matrix_path, [row])

    report = validate_matrix_against_callables(
        matrix_path,
        [CallableKey("_water_network.py", "compute_velocity_field")],
        block_grade_status=True,
    )

    assert report.grade_status_blocks == {
        "_water_network.py::compute_velocity_field": "NAME_ONLY_MATCH"
    }
    assert report.is_blocking


def test_guardrail_verification_blocks_read_summary_json(tmp_path):
    from scripts.terrain_best_practice_guardrail import load_verification_blocks

    summary_path = tmp_path / "CALLABLE_VERIFICATION_SUMMARY.json"
    summary_path.write_text(
        '{"risk_counts":{"BLOCKER":2,"HIGH":3},"false_grade_count":1}\n',
        encoding="utf-8",
    )

    assert load_verification_blocks(summary_path) == {
        "verification_blockers": 2,
        "verification_high": 3,
        "false_a_grade_rows": 1,
    }


def test_guardrail_verification_passes_when_summary_has_no_risk(tmp_path):
    from scripts.terrain_best_practice_guardrail import load_verification_blocks

    summary_path = tmp_path / "CALLABLE_VERIFICATION_SUMMARY.json"
    summary_path.write_text(
        '{"risk_counts":{"BLOCKER":0,"HIGH":0},"false_grade_count":0}\n',
        encoding="utf-8",
    )

    assert load_verification_blocks(summary_path) == {}


def test_guardrail_splits_reviewed_duplicate_names():
    from scripts.terrain_best_practice_guardrail import CallableKey, split_reviewed_duplicate_names

    duplicates = {
        "to_dict": [
            CallableKey("a.py", "A.to_dict"),
            CallableKey("b.py", "B.to_dict"),
        ],
        "unsafe": [
            CallableKey("x.py", "unsafe"),
            CallableKey("y.py", "unsafe"),
        ],
    }
    review = {
        "to_dict": {"a.py::A.to_dict", "b.py::B.to_dict"},
    }

    unreviewed, reviewed = split_reviewed_duplicate_names(duplicates, review)

    assert sorted(reviewed) == ["to_dict"]
    assert sorted(unreviewed) == ["unsafe"]


def test_usage_guide_names_domain_purpose_and_duplicate_groups(tmp_path):
    from scripts.terrain_best_practice_guardrail import (
        CallableKey,
        build_usage_guide,
        collect_duplicate_names,
        load_matrix_rows,
    )

    matrix_path = tmp_path / "matrix.csv"
    _write_matrix(
        matrix_path,
        [
            _row("_water_network.py", "compute_velocity_field", "hydrology"),
            _row("terrain_materials.py", "compute_velocity_field", "terrain_texturing"),
        ],
    )

    rows = load_matrix_rows(matrix_path)
    duplicates = collect_duplicate_names(
        [
            CallableKey("_water_network.py", "compute_velocity_field"),
            CallableKey("terrain_materials.py", "compute_velocity_field"),
        ]
    )
    guide = build_usage_guide(rows, duplicates)

    assert "Use `hydrology` callables for water systems" in guide
    assert "Use `terrain_texturing` callables for terrain texture/PBR work" in guide
    assert "Duplicate callable names requiring review" in guide
    assert "compute_velocity_field" in guide


def test_usage_guide_links_to_active_matrix_path(tmp_path):
    from scripts.terrain_best_practice_guardrail import build_usage_guide, load_matrix_rows

    matrix_path = tmp_path / "INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2099_01_02.csv"
    _write_matrix(matrix_path, [_row("_water_network.py", "compute_velocity_field")])

    guide = build_usage_guide(
        load_matrix_rows(matrix_path),
        {},
        matrix_path=matrix_path,
    )

    assert "INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2099_01_02.csv" in guide


def test_matrix_classifies_scatter_quaternion_helper_as_scatter_ecology():
    from scripts.build_industry_best_practice_callable_matrix import classify

    domain, _subdomain = classify("terrain_scatter_points.py", "_normalise_quat")

    assert domain == "scatter_ecology"


def test_matrix_uses_verification_low_risk_to_clear_p0_backlog():
    from scripts.build_industry_best_practice_callable_matrix import grade_status, upgrade_tier

    assert grade_status("D+", "LOW") == "VERIFIED_LOW_RISK"
    assert upgrade_tier("D+", "hydrology", "LOW") == "P3"
    assert upgrade_tier("D+", "hydrology", "BLOCKER") == "P0"
