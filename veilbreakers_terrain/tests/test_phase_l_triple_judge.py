"""Tests for scripts/phase_l_triple_judge.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "phase_l_triple_judge.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("phase_l_triple_judge", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["phase_l_triple_judge"] = mod
    spec.loader.exec_module(mod)
    return mod


tj = _load_module()


def _fake_judge(
    judge_name: str,
    verdict: str,
    score: int = 8,
    critical: list[str] | None = None,
    minor: list[str] | None = None,
    error: str | None = None,
) -> Callable[[str, Path], "tj.Verdict"]:
    def _fn(prompt: str, node_dir: Path):
        return tj.Verdict(
            judge=judge_name,
            verdict=verdict,
            score_of_10=score,
            critical_issues=list(critical or []),
            minor_issues=list(minor or []),
            praise=[],
            raw=json.dumps({"verdict": verdict, "score_of_10": score}),
            error=error,
        )

    return _fn


# ---------------------------------------------------------------------------
# parse_verdict_json
# ---------------------------------------------------------------------------

def test_parse_verdict_bare_json():
    raw = '{"verdict": "OVERALL_PASS", "score_of_10": 9, "critical_issues": [], "minor_issues": ["seams"], "praise": ["lighting"]}'
    v = tj.parse_verdict_json(raw, "gemini")
    assert v.passed()
    assert v.score_of_10 == 9
    assert v.minor_issues == ["seams"]


def test_parse_verdict_fenced_json():
    raw = "Here you go:\n```json\n{\"verdict\":\"OVERALL_FAIL\",\"score_of_10\":5,\"critical_issues\":[\"tiling\"],\"minor_issues\":[],\"praise\":[]}\n```\nThanks."
    v = tj.parse_verdict_json(raw, "codex")
    assert not v.passed()
    assert v.verdict == "OVERALL_FAIL"
    assert v.critical_issues == ["tiling"]


def test_parse_verdict_preamble():
    raw = 'Verdict below.\n{"verdict": "OVERALL_PASS", "score_of_10": 7, "critical_issues": [], "minor_issues": [], "praise": []}\nEnd.'
    v = tj.parse_verdict_json(raw, "opus")
    assert v.passed()


def test_parse_verdict_malformed():
    v = tj.parse_verdict_json("sorry I cannot help with that", "gemini")
    assert v.verdict == "ERROR"
    assert v.error


def test_parse_verdict_bad_verdict_value():
    raw = '{"verdict": "MAYBE", "score_of_10": 5, "critical_issues": [], "minor_issues": [], "praise": []}'
    v = tj.parse_verdict_json(raw, "codex")
    assert v.verdict == "ERROR"


# ---------------------------------------------------------------------------
# agreement + union_issues
# ---------------------------------------------------------------------------

def test_agreement_triple_pass():
    verdicts = [
        tj.Verdict(judge="opus", verdict="OVERALL_PASS"),
        tj.Verdict(judge="codex", verdict="OVERALL_PASS"),
        tj.Verdict(judge="gemini", verdict="OVERALL_PASS"),
    ]
    ok, mode = tj.agreement(verdicts, allow_gemini_fallback=True)
    assert ok and mode == "triple"


def test_agreement_duo_fallback_when_gemini_errors():
    verdicts = [
        tj.Verdict(judge="opus", verdict="OVERALL_PASS"),
        tj.Verdict(judge="codex", verdict="OVERALL_PASS"),
        tj.Verdict(judge="gemini", verdict="ERROR", error="refused"),
    ]
    ok, mode = tj.agreement(verdicts, allow_gemini_fallback=True)
    assert ok and mode == "duo_fallback"


def test_agreement_strict_requires_gemini():
    verdicts = [
        tj.Verdict(judge="opus", verdict="OVERALL_PASS"),
        tj.Verdict(judge="codex", verdict="OVERALL_PASS"),
        tj.Verdict(judge="gemini", verdict="ERROR"),
    ]
    ok, mode = tj.agreement(verdicts, allow_gemini_fallback=False)
    assert not ok and mode == "fail"


def test_agreement_any_fail_blocks():
    verdicts = [
        tj.Verdict(judge="opus", verdict="OVERALL_PASS"),
        tj.Verdict(judge="codex", verdict="OVERALL_FAIL"),
        tj.Verdict(judge="gemini", verdict="OVERALL_PASS"),
    ]
    ok, _ = tj.agreement(verdicts, allow_gemini_fallback=True)
    assert not ok


def test_union_issues_dedupes_case_insensitive():
    verdicts = [
        tj.Verdict(judge="opus", verdict="OVERALL_FAIL", critical_issues=["Tiling visible"]),
        tj.Verdict(judge="codex", verdict="OVERALL_FAIL", critical_issues=["tiling visible"]),
        tj.Verdict(judge="gemini", verdict="OVERALL_FAIL", minor_issues=["soft shadows"]),
    ]
    merged = tj.union_issues(verdicts)
    assert len(merged["critical"]) == 1
    assert merged["critical"][0].startswith("[opus]")
    assert any("soft shadows" in m for m in merged["minor"])


# ---------------------------------------------------------------------------
# run_node loop: pass case
# ---------------------------------------------------------------------------

@pytest.fixture
def node_dir(tmp_path) -> Path:
    nd = tmp_path / "aaa_node_v1"
    nd.mkdir()
    (nd / "BUILD_SUMMARY.json").write_text(
        json.dumps({"seed": 43681, "biome": "dark_fantasy_forest"}),
        encoding="utf-8",
    )
    for name in ["hero_wide", "N_peak", "SE", "SW", "river_eye", "cave_entry"]:
        (nd / f"render_{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return nd


def test_run_node_triple_pass_signs_off(node_dir):
    judges = {
        "opus": _fake_judge("opus", "OVERALL_PASS", score=9),
        "codex": _fake_judge("codex", "OVERALL_PASS", score=8),
        "gemini": _fake_judge("gemini", "OVERALL_PASS", score=9),
    }
    rec = tj.run_node(node_dir, max_rounds=3, dispatch_stub=True,
                      allow_gemini_fallback=True, judges=judges)
    assert rec["signoff"] is not None
    assert rec["agreement_mode"] == "triple"
    assert (node_dir / "TRIPLE_SIGNOFF.json").exists()
    assert (node_dir / "OPUS_VERDICT.md").exists()
    assert (node_dir / "CODEX_VERDICT.md").exists()
    assert (node_dir / "GEMINI_VERDICT.md").exists()
    status = json.loads((node_dir / "TRIPLE_LOOP_STATUS.json").read_text())
    assert status["all_pass"]
    assert len(rec["rounds"]) == 1


def test_run_node_duo_fallback_on_gemini_error(node_dir):
    judges = {
        "opus": _fake_judge("opus", "OVERALL_PASS"),
        "codex": _fake_judge("codex", "OVERALL_PASS"),
        "gemini": _fake_judge("gemini", "ERROR", error="quota"),
    }
    rec = tj.run_node(node_dir, max_rounds=2, dispatch_stub=True,
                      allow_gemini_fallback=True, judges=judges)
    assert rec["signoff"]["gemini_fallback_used"] is True
    assert rec["agreement_mode"] == "duo_fallback"


# ---------------------------------------------------------------------------
# run_node loop: fix-cycle dispatch + max rounds
# ---------------------------------------------------------------------------

def test_run_node_dispatches_fix_and_fails_after_max(node_dir):
    judges = {
        "opus": _fake_judge("opus", "OVERALL_FAIL", score=4, critical=["obvious tiling"]),
        "codex": _fake_judge("codex", "OVERALL_FAIL", score=5, minor=["weak SSS"]),
        "gemini": _fake_judge("gemini", "OVERALL_FAIL", score=4, critical=["harsh normals"]),
    }
    rec = tj.run_node(node_dir, max_rounds=3, dispatch_stub=True,
                      allow_gemini_fallback=True, judges=judges)
    assert rec["signoff"] is None
    assert len(rec["rounds"]) == 3
    assert "failure_to_agree" in rec
    assert (node_dir / "FAILURE_TO_AGREE.md").exists()
    # All 3 rounds should have dispatched a fix.
    for r in rec["rounds"]:
        assert r["fix_dispatch_id"]
    queue = json.loads((node_dir / "TRIPLE_FIX_QUEUE.json").read_text())
    assert len(queue["dispatches"]) == 3
    # Prompt should mention the build script and issue list.
    # build_aaa_node_v1/v2 are deleted; v1/v2 node dirs now map to v6 script.
    assert "build_terrain_aaa_node_v6.py" in queue["dispatches"][0]["prompt"]
    assert "tiling" in queue["dispatches"][0]["prompt"].lower()


def test_run_node_skips_when_dir_missing(tmp_path):
    missing = tmp_path / "aaa_node_v2"
    rec = tj.run_node(missing, max_rounds=1, dispatch_stub=True,
                      allow_gemini_fallback=True, judges={
                          "opus": _fake_judge("opus", "OVERALL_PASS"),
                          "codex": _fake_judge("codex", "OVERALL_PASS"),
                          "gemini": _fake_judge("gemini", "OVERALL_PASS"),
                      })
    assert "skipped" in rec
    assert rec["signoff"] is None


def test_run_node_skips_when_build_summary_missing(tmp_path):
    nd = tmp_path / "aaa_node_v2"
    nd.mkdir()
    rec = tj.run_node(nd, max_rounds=1, dispatch_stub=True,
                      allow_gemini_fallback=True, judges={
                          "opus": _fake_judge("opus", "OVERALL_PASS"),
                          "codex": _fake_judge("codex", "OVERALL_PASS"),
                          "gemini": _fake_judge("gemini", "OVERALL_PASS"),
                      })
    assert "skipped" in rec
    status = json.loads((nd / "TRIPLE_LOOP_STATUS.json").read_text())
    assert status["skipped"]


# ---------------------------------------------------------------------------
# Fix prompt builder
# ---------------------------------------------------------------------------

def test_build_fix_prompt_node_v1(tmp_path):
    nd = tmp_path / "aaa_node_v1"
    nd.mkdir()
    prompt = tj.build_fix_prompt(
        nd,
        {"critical": ["tiling"], "minor": ["foam"]},
        round_num=2,
    )
    # build_aaa_node_v1.py through v5.py are deprecated; v1 node dir now maps to v6 script.
    assert "build_terrain_aaa_node_v6.py" in prompt
    assert "tiling" in prompt
    assert "round 2" in prompt
    assert "Node v6" in prompt


def test_build_fix_prompt_showcase(tmp_path):
    nd = tmp_path / "aaa_node_showcase"
    nd.mkdir()
    prompt = tj.build_fix_prompt(nd, {"critical": [], "minor": ["seam"]}, round_num=1)
    assert "build_aaa_node_showcase.py" in prompt
    assert "Showcase" in prompt


# ---------------------------------------------------------------------------
# Ledger writer
# ---------------------------------------------------------------------------

def test_write_verdict_md_contains_sections(tmp_path):
    v = tj.Verdict(
        judge="gemini",
        verdict="OVERALL_FAIL",
        score_of_10=6,
        critical_issues=["tiling"],
        minor_issues=["foam blur"],
        praise=["sky"],
        raw='{"verdict":"OVERALL_FAIL"}',
    )
    path = tj.write_verdict_md(tmp_path, v)
    assert path.name == "GEMINI_VERDICT.md"
    txt = path.read_text(encoding="utf-8")
    assert "OVERALL_FAIL" in txt
    assert "tiling" in txt
    assert "foam blur" in txt
    assert "sky" in txt
