"""Unit tests for ``scripts/verify_pr_cites.py`` (Fix 1.0 / spec §11.0.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_pr_cites import (
    AuditResult,
    CiteRecord,
    PATH_NAMESPACE_MAP,
    STATUS_NEW_FILE,
    STATUS_NO_CITE,
    STATUS_OUT_OF_FILE,
    STATUS_STALE,
    STATUS_VALID,
    UNITY_EDITOR_FILES,
    _classify,
    _expand_line_spec,
    _extract_cites,
    _extract_pr_rows,
    _extract_pr_title,
    _resolve_path,
    _slice_runway,
    audit_spec,
    main,
)


# ---------------------------------------------------------------------------
# Path namespace resolution
# ---------------------------------------------------------------------------

def test_resolve_path_handlers_shorthand():
    assert _resolve_path("handlers/terrain_pipeline.py") == "veilbreakers_terrain/handlers/terrain_pipeline.py"


def test_resolve_path_providers_shorthand():
    assert _resolve_path("providers/meshy_provider.py") == "veilbreakers_terrain/providers/meshy_provider.py"


def test_resolve_path_unity_runtime_script_lands_at_top_level():
    """Runtime Unity scripts (e.g. VbFoliageManifestRenderer) live at unity_plugin/ top level."""
    assert (
        _resolve_path("unity_project/Assets/Scripts/VbFoliageManifestRenderer.cs")
        == "unity_plugin/VbFoliageManifestRenderer.cs"
    )


def test_resolve_path_unity_editor_script_lands_in_editor_subdir():
    """Editor-only scripts route through Editor/ even when cited via Scripts/ shorthand.

    Unity AssetPostprocessor types must physically live in an Editor folder. The
    spec sometimes cites VbTerrainImporter.cs via Assets/Scripts/ shorthand, but
    the file actually lives at unity_plugin/Editor/VbTerrainImporter.cs. Resolver
    consults UNITY_EDITOR_FILES carve-out to route correctly.
    """
    assert "VbTerrainImporter.cs" in UNITY_EDITOR_FILES
    assert (
        _resolve_path("unity_project/Assets/Scripts/VbTerrainImporter.cs")
        == "unity_plugin/Editor/VbTerrainImporter.cs"
    )


def test_resolve_path_unity_editor_shorthand_passthrough():
    """Cites already using Assets/Editor/ resolve directly to unity_plugin/Editor/."""
    assert (
        _resolve_path("unity_project/Assets/Editor/VbTerrainImporter.cs")
        == "unity_plugin/Editor/VbTerrainImporter.cs"
    )


def test_resolve_path_already_absolute_passthrough():
    assert _resolve_path("docs/spec.md") == "docs/spec.md"


def test_resolve_path_chunks_new_directory():
    """Per spec §11.0.3: chunks/ is a NEW directory landing in PR #15.5."""
    assert _resolve_path("chunks/chunk_seed.py") == "veilbreakers_terrain/chunks/chunk_seed.py"


def test_path_namespace_map_is_ordered_longest_first():
    """A later (potentially shorter) entry must not be a prefix of an earlier one.

    ``_resolve_path`` walks ``PATH_NAMESPACE_MAP`` top-to-bottom and returns on
    first match. If a later entry's shorthand is a prefix of an earlier entry's
    shorthand, the earlier (longer) rule shadows the later one and the later
    rule is unreachable. Equivalently: every later shorthand must NOT start
    with any earlier shorthand.
    """
    prefixes = [shorthand for shorthand, _ in PATH_NAMESPACE_MAP]
    for idx, prefix in enumerate(prefixes):
        for later in prefixes[idx + 1 :]:
            assert not later.startswith(prefix), (
                f"PATH_NAMESPACE_MAP[{idx + 1}+]={later!r} extends "
                f"PATH_NAMESPACE_MAP[{idx}]={prefix!r}; the earlier rule would "
                f"match first and the later rule would be unreachable. "
                f"Reorder so the longer/more-specific entry comes first."
            )


# ---------------------------------------------------------------------------
# Cite extraction
# ---------------------------------------------------------------------------

def test_extract_cites_single_path_line():
    row = "| 6 | fix(foliage): align | handlers/terrain_advanced.py:2652 | acc | val | S | none |"
    cites = _extract_cites(row)
    assert cites == [("handlers/terrain_advanced.py:2652", "handlers/terrain_advanced.py", 2652)]


def test_extract_cites_range_takes_first_line():
    row = "| 3 | fix(pipeline): topo | handlers/terrain_pipeline.py:1449-1510 | acc | val | M | #2 |"
    cites = _extract_cites(row)
    assert len(cites) == 1
    assert cites[0][2] == 1449


def test_extract_cites_multiple_in_one_row():
    row = "| 11 | sec(providers) | providers/meshy_provider.py:216, providers/hunyuan3d2_provider.py:274 | acc | val | M | none |"
    cites = _extract_cites(row)
    assert len(cites) == 2
    paths = {c[1] for c in cites}
    assert paths == {"providers/meshy_provider.py", "providers/hunyuan3d2_provider.py"}


def test_extract_cites_expands_comma_separated_lines():
    """``foo.py:N,M`` produces two distinct cites — one per line — not just N."""
    row = "| 5b | fix(water) | terrain_water_variants.py:781,878 | acc | val | M | #5a |"
    cites = _extract_cites(row)
    paths_lines = [(c[1], c[2]) for c in cites]
    assert ("terrain_water_variants.py", 781) in paths_lines
    assert ("terrain_water_variants.py", 878) in paths_lines
    assert len(cites) == 2


def test_extract_cites_dedupes_repeated_pair():
    row = "| 5b | fix(water) | terrain_water_variants.py:781,878 and again terrain_water_variants.py:781 | acc | val | M | #5a |"
    cites = _extract_cites(row)
    paths_lines = [(c[1], c[2]) for c in cites]
    # First occurrence of (path, 781) wins; the comma-list expands to 781 + 878
    # while the trailing standalone 781 is deduped.
    assert ("terrain_water_variants.py", 781) in paths_lines
    assert ("terrain_water_variants.py", 878) in paths_lines
    assert len(cites) == 2  # 781, 878 — repeated 781 deduped


def test_extract_cites_mixed_range_and_list():
    """``foo.py:1-5,10-12`` yields the start of each chunk: [1, 10]."""
    row = "| X | demo | terrain_pipeline.py:1-5,10-12 | acc | val | S | none |"
    cites = _extract_cites(row)
    lines = sorted(c[2] for c in cites)
    assert lines == [1, 10]


def test_expand_line_spec_pure_unit():
    """Direct unit test of the line-spec expansion helper."""
    assert _expand_line_spec("42") == [42]
    assert _expand_line_spec("42-50") == [42]
    assert _expand_line_spec("42,50") == [42, 50]
    assert _expand_line_spec("42-50,60-70") == [42, 60]
    assert _expand_line_spec("1,2,3,4") == [1, 2, 3, 4]


def test_extract_cites_skips_rows_without_cite():
    row = "| 1 | chore(repo): gitignore + LFS hygiene | .gitignore | criteria | val | S | none |"
    cites = _extract_cites(row)
    assert cites == []


# ---------------------------------------------------------------------------
# Spec slicing
# ---------------------------------------------------------------------------

SAMPLE_SPEC = """\
# §1 Locked decisions

Some content.

### 11.0 Preface

Some preface.

### 11.1 Block 1 — Immediate blockers

| PR | Title | Files | Acc | Val | Effort | Deps |
|---|---|---|---|---|---|---|
| 1 | chore(repo): gitignore + LFS hygiene | `.gitignore` | acc | val | S | none |
| 6 | fix(foliage): align | `handlers/terrain_advanced.py:2652` | acc | val | S | none |

### 11.6 Cross-PR dependency graph

graph stuff that should NOT be parsed as PR rows.
"""


def test_slice_runway_extracts_only_section_11():
    runway = _slice_runway(SAMPLE_SPEC)
    assert "### 11.1 Block 1" in runway
    assert "graph stuff" not in runway
    assert "Locked decisions" not in runway


def test_extract_pr_rows_skips_table_header():
    runway = _slice_runway(SAMPLE_SPEC)
    rows = _extract_pr_rows(runway)
    pr_ids = [pid for pid, _ in rows]
    assert "1" in pr_ids
    assert "6" in pr_ids
    assert "PR" not in pr_ids
    assert "---" not in pr_ids


def test_extract_pr_title_returns_second_cell():
    row = "| 6 | fix(foliage): align_to_normal default False | files | acc | val | S | none |"
    title = _extract_pr_title(row)
    assert title == "fix(foliage): align_to_normal default False"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_classify_new_file_when_path_missing_on_ref():
    rec = _classify(
        pr_id="B5-U-NAV",
        pr_title="feat(unity): replace navmesh.json with dtNavMesh.bin",
        raw_cite="chunks/navmesh_recast.py:1",
        resolved_path="veilbreakers_terrain/chunks/navmesh_recast.py",
        line=1,
        file_lines=None,
    )
    assert rec.status == STATUS_NEW_FILE


def test_classify_out_of_file_when_line_past_eof():
    rec = _classify(
        pr_id="14",
        pr_title="fix(rng): single-source derive_pass_seed",
        raw_cite="terrain_rng.py:45",
        resolved_path="veilbreakers_terrain/handlers/terrain_rng.py",
        line=45,
        file_lines=["line1", "line2", "line3"],
    )
    assert rec.status == STATUS_OUT_OF_FILE
    assert "file length=3" in rec.notes


def test_classify_valid_when_token_overlaps():
    rec = _classify(
        pr_id="15",
        pr_title="fix(determinism): replace hash hazards in cliffs",
        raw_cite="terrain_cliffs.py:2368",
        resolved_path="veilbreakers_terrain/handlers/terrain_cliffs.py",
        line=2368,
        file_lines=["unused"] * 2367 + ["mesh_seed = hash(cliff.cliff_id) & 0x7FFFFFFF"],
    )
    assert rec.status == STATUS_VALID
    assert "hash" in rec.notes


def test_classify_stale_when_no_token_overlap():
    rec = _classify(
        pr_id="3",
        pr_title="fix(pipeline): topo-sort consumes overrides",
        raw_cite="terrain_pipeline.py:1449",
        resolved_path="veilbreakers_terrain/handlers/terrain_pipeline.py",
        line=1449,
        file_lines=["unused"] * 1448 + ["    return result"],
    )
    assert rec.status == STATUS_STALE


def test_classify_stale_with_window_match_keeps_stale_but_notes_drift():
    """If overlap is in ±3-line window but not exact line, mark STALE with drift note."""
    file_lines = (
        ["unused"] * 1445
        + ["def _toposort_passes(", "    pass", "    return result"]
        + ["filler"] * 100
    )
    rec = _classify(
        pr_id="3",
        pr_title="fix(pipeline): topo-sort consumes overrides",
        raw_cite="terrain_pipeline.py:1448",
        resolved_path="veilbreakers_terrain/handlers/terrain_pipeline.py",
        line=1448,
        file_lines=file_lines,
    )
    assert rec.status == STATUS_STALE
    assert "drift" in rec.notes


# ---------------------------------------------------------------------------
# Audit result
# ---------------------------------------------------------------------------

def test_audit_result_counts_per_status():
    result = AuditResult()
    result.records.append(_make_rec(STATUS_VALID))
    result.records.append(_make_rec(STATUS_VALID))
    result.records.append(_make_rec(STATUS_STALE))
    result.records.append(_make_rec(STATUS_OUT_OF_FILE))
    result.records.append(_make_rec(STATUS_NO_CITE))
    counts = result.counts()
    assert counts[STATUS_VALID] == 2
    assert counts[STATUS_STALE] == 1
    assert counts[STATUS_OUT_OF_FILE] == 1
    assert counts[STATUS_NEW_FILE] == 0
    assert counts[STATUS_NO_CITE] == 1


def test_audit_result_fail_count_excludes_no_cite_and_new_file():
    result = AuditResult()
    result.records.append(_make_rec(STATUS_STALE))
    result.records.append(_make_rec(STATUS_OUT_OF_FILE))
    result.records.append(_make_rec(STATUS_NEW_FILE))
    result.records.append(_make_rec(STATUS_NO_CITE))
    # fail_count = STALE + OUT_OF_FILE only; NEW_FILE is expected for Phase 4 PRs
    # that introduce files not yet on main, NO_CITE is documentation breadcrumbs.
    assert result.fail_count == 2


def _make_rec(status: str) -> CiteRecord:
    return CiteRecord(
        pr_id="1",
        pr_title="t",
        raw_cite="x.py:1",
        resolved_path="x.py",
        line=1,
        status=status,
    )


# ---------------------------------------------------------------------------
# End-to-end against a tiny spec on disk
# ---------------------------------------------------------------------------

def test_audit_spec_handles_no_runway_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """audit_spec raises a clear RuntimeError if §11 runway is absent.

    Monkeypatches ``_ref_exists`` to True so the test is isolated from the
    surrounding git environment — we want to verify the runway-not-found
    branch, not the ref-resolution branch (which would mask intent if HEAD
    is undefined, e.g. on a fresh repo with no commits).
    """
    def _always_true(_ref: str) -> bool:
        return True

    monkeypatch.setattr("scripts.verify_pr_cites._ref_exists", _always_true)
    bad_spec = tmp_path / "no_runway.md"
    bad_spec.write_text("# Just a header\n\nNo §11 here.\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="runway section not found"):
        audit_spec(bad_spec, ref="HEAD")


def test_audit_spec_missing_file_raises_filenotfound(tmp_path: Path):
    """File-existence check runs before _ref_exists; no monkeypatch needed."""
    bogus = tmp_path / "does_not_exist.md"
    with pytest.raises(FileNotFoundError):
        audit_spec(bogus, ref="HEAD")


# ---------------------------------------------------------------------------
# --from-json / --check-fail-count ratchet path
# ---------------------------------------------------------------------------

def test_main_from_json_passes_when_under_baseline(tmp_path: Path) -> None:
    """--from-json + --check-fail-count exits 0 when fail_count <= baseline."""
    import json as _json

    json_path = tmp_path / "audit.json"
    json_path.write_text(
        _json.dumps({"fail_count": 10, "total": 100, "counts": {}, "records": []}),
        encoding="utf-8",
    )
    rc = main(["--from-json", str(json_path), "--check-fail-count", "25"])
    assert rc == 0


def test_main_from_json_fails_when_over_baseline(tmp_path: Path) -> None:
    """--from-json + --check-fail-count exits 1 when fail_count > baseline."""
    import json as _json

    json_path = tmp_path / "audit.json"
    json_path.write_text(
        _json.dumps({"fail_count": 30, "total": 100, "counts": {}, "records": []}),
        encoding="utf-8",
    )
    rc = main(["--from-json", str(json_path), "--check-fail-count", "25"])
    assert rc == 1


def test_main_from_json_handles_missing_file(tmp_path: Path) -> None:
    """Missing JSON exits 2, not 1, so CI distinguishes ratchet violation from infra error."""
    rc = main([
        "--from-json", str(tmp_path / "nope.json"),
        "--check-fail-count", "0",
    ])
    assert rc == 2
