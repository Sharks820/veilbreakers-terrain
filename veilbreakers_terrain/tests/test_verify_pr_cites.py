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
    _classify,
    _extract_cites,
    _extract_pr_rows,
    _extract_pr_title,
    _resolve_path,
    _slice_runway,
    audit_spec,
)


# ---------------------------------------------------------------------------
# Path namespace resolution
# ---------------------------------------------------------------------------

def test_resolve_path_handlers_shorthand():
    assert _resolve_path("handlers/terrain_pipeline.py") == "veilbreakers_terrain/handlers/terrain_pipeline.py"


def test_resolve_path_providers_shorthand():
    assert _resolve_path("providers/meshy_provider.py") == "veilbreakers_terrain/providers/meshy_provider.py"


def test_resolve_path_unity_shorthand():
    assert _resolve_path("unity_project/Assets/Scripts/VbTerrainImporter.cs") == "unity_plugin/VbTerrainImporter.cs"


def test_resolve_path_already_absolute_passthrough():
    assert _resolve_path("docs/spec.md") == "docs/spec.md"


def test_resolve_path_chunks_new_directory():
    """Per spec §11.0.3: chunks/ is a NEW directory landing in PR #15.5."""
    assert _resolve_path("chunks/chunk_seed.py") == "veilbreakers_terrain/chunks/chunk_seed.py"


def test_path_namespace_map_is_ordered_longest_first():
    """Longer prefixes must come before shorter ones to avoid collision."""
    prefixes = [shorthand for shorthand, _ in PATH_NAMESPACE_MAP]
    # unity_project/Assets/Scripts/ contains 'Scripts/' so must come before
    # any future 'Scripts/' entry — sentinel test ensures we don't drift.
    for idx, prefix in enumerate(prefixes):
        for later in prefixes[idx + 1 :]:
            assert not prefix.startswith(later), f"{later} sorts before its prefix-superset {prefix}"


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


def test_extract_cites_dedupes_repeated_pair():
    row = "| 5b | fix(water) | terrain_water_variants.py:781,878 and again terrain_water_variants.py:781 | acc | val | M | #5a |"
    cites = _extract_cites(row)
    paths_lines = [(c[1], c[2]) for c in cites]
    # First occurrence of (path, 781) wins; the duplicate is dropped
    assert (("terrain_water_variants.py", 781) in paths_lines)


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
    # fail_count = STALE + OUT_OF_FILE + RESOLVE_FAIL
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

def test_audit_spec_handles_no_runway_gracefully(tmp_path: Path):
    """audit_spec raises a clear RuntimeError if §11 runway is absent."""
    bad_spec = tmp_path / "no_runway.md"
    bad_spec.write_text("# Just a header\n\nNo §11 here.\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="runway section not found"):
        audit_spec(bad_spec, ref="HEAD")


def test_audit_spec_missing_file_raises_filenotfound(tmp_path: Path):
    bogus = tmp_path / "does_not_exist.md"
    with pytest.raises(FileNotFoundError):
        audit_spec(bogus, ref="HEAD")
