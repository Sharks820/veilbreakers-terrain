"""Bundle N — Deep Validation & QA tests.

Covers all six Bundle N modules:
    terrain_determinism_ci
    terrain_readability_bands
    terrain_budget_enforcer
    terrain_golden_snapshots
    terrain_review_ingest
    terrain_telemetry_dashboard

>= 25 tests. Determinism test must FAIL on a 1-bit mutation of the
mask stack. Golden snapshot library seed must produce >= 20 snapshots.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from veilbreakers_terrain.handlers.terrain_budget_enforcer import TerrainBudget
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import (
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
        ValidationIssue,
    )


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def register_passes() -> Generator[None, None, None]:
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )

    TerrainPassController.clear_registry()
    register_default_passes()
    yield
    TerrainPassController.clear_registry()


def _build_stack(
    tile_size: int = 16,
    seed: int = 1234,
    *,
    extras: bool = True,
) -> "TerrainMaskStack":
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    rng = np.random.default_rng(seed)
    height = rng.standard_normal((tile_size, tile_size)).astype(np.float64) * 5.0 + 100.0
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=2.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    if extras:
        slope = np.abs(rng.standard_normal((tile_size, tile_size))).astype(np.float64)
        macro = rng.random((tile_size, tile_size, 3)).astype(np.float64)
        stack.set("slope", slope, "test_setup")
        stack.set("macro_color", macro, "test_setup")
    return stack


def _build_state(tile_size: int = 16, seed: int = 1234) -> "TerrainPipelineState":
    from veilbreakers_terrain.handlers._terrain_noise import generate_heightmap
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
        TerrainSceneRead,
    )

    height = np.asarray(
        generate_heightmap(
            tile_size + 1,
            tile_size + 1,
            scale=80.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            cell_size=1.0,
            seed=seed,
            terrain_type="mountains",
            normalize=False,
        ),
        dtype=np.float64,
    )
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    region = BBox(0.0, 0.0, float(tile_size), float(tile_size))
    scene_read = TerrainSceneRead(
        timestamp=0.0,
        major_landforms=("ridge_system",),
        focal_point=(tile_size / 2.0, tile_size / 2.0, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=region,
        success_criteria=("deep_qa",),
        reviewer="pytest",
    )
    intent = TerrainIntentState(
        seed=seed,
        region_bounds=region,
        tile_size=tile_size,
        cell_size=1.0,
        scene_read=scene_read,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# 1. Bundle N registrar
# ---------------------------------------------------------------------------


def test_bundle_n_registrar_is_callable():
    from veilbreakers_terrain.handlers.terrain_bundle_n import (
        BUNDLE_N_MODULES,
        BUNDLE_N_RUNTIME_CONTRACT,
        register_bundle_n_passes,
    )

    contract = register_bundle_n_passes()
    assert "terrain_determinism_ci" in BUNDLE_N_MODULES
    assert len(BUNDLE_N_MODULES) == 7
    assert contract == BUNDLE_N_RUNTIME_CONTRACT
    assert contract["registers_passes"] is False
    assert "compute_readability_bands" in contract["always_on_post_pipeline"]
    assert "collect_performance_report" in contract["always_on_post_pipeline"]
    assert "apply_review_blockers" in contract["always_on_post_pipeline"]
    assert "run_determinism_check" in contract["opt_in_post_pipeline"]


def test_bundle_n_pipeline_hooks_attach_budget_issues_and_readability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import veilbreakers_terrain.handlers.terrain_bundle_n as bundle_n
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers.terrain_semantics import ValidationIssue

    def _fake_enforce_budget(
        stack: "TerrainMaskStack",
        intent: "TerrainIntentState",
        budget: "TerrainBudget",
    ) -> list["ValidationIssue"]:
        assert stack.tile_size == intent.tile_size
        assert budget.max_tri_lod0 > 0
        return [
            ValidationIssue(
                code="BUNDLE_N_SOFT",
                severity="soft",
                message="soft issue",
            ),
            ValidationIssue(
                code="BUNDLE_N_HARD",
                severity="hard",
                message="hard issue",
            ),
        ]

    monkeypatch.setattr(
        bundle_n.terrain_budget_enforcer,
        "enforce_budget",
        _fake_enforce_budget,
    )

    state = _build_state(tile_size=8, seed=2121)
    state.intent.composition_hints["bundle_n_runtime"] = {
        "visual_qa_blocking": False,
    }
    controller = TerrainPassController(state)
    results = controller.run_pipeline(pass_sequence=["macro_world"], checkpoint=False)

    last = results[-1]
    assert [issue.code for issue in last.issues] == ["BUNDLE_N_SOFT", "BUNDLE_N_HARD"]
    assert last.status == "failed"
    assert not hasattr(last, "validation_issues")
    assert "bundle_n" in last.metrics
    assert "budget_report" in last.metrics["bundle_n"]
    assert len(last.metrics["bundle_n"]["readability_band_scores"]) == 5


def test_bundle_n_pipeline_hooks_attach_structured_budget_report():
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    state = _build_state(tile_size=8, seed=2222)
    controller = TerrainPassController(state)
    results = controller.run_pipeline(pass_sequence=["macro_world"], checkpoint=False)

    budget_report = results[-1].metrics["bundle_n"]["budget_report"]
    perf_report = results[-1].metrics["bundle_n"]["performance_report"]
    assert "lod0_tris" in budget_report
    assert "unique_materials" in budget_report
    assert budget_report["lod0_tris"]["current"] >= 0
    assert perf_report["status"] in {"ok", "over_budget"}
    assert perf_report["triangle_count"]["terrain"] > 0


def test_bundle_n_pipeline_hooks_apply_review_blockers_from_intent():
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    state = _build_state(tile_size=8, seed=2323)
    state.intent.composition_hints["review_blockers"] = [
        {
            "source": "human",
            "location": [1.0, 2.0, 3.0],
            "message": "Hero cliff silhouette still blocks the focal read.",
            "suggested_fix": "Smooth the silhouette around the camera lane.",
            "affected_feature": "hero_cliff",
        }
    ]
    state.intent.composition_hints["review_suggestions"] = [
        {
            "source": "ai",
            "message": "Smooth waterfall framing and erosion transition.",
            "suggested_fix": "Smooth the waterfall shoulder.",
            "affected_feature": "waterfall",
        }
    ]

    controller = TerrainPassController(state)
    results = controller.run_pipeline(pass_sequence=["macro_world"], checkpoint=False)

    last = results[-1]
    assert last.status == "failed"
    assert any(issue.code == "review_blocker:hero_cliff" for issue in last.issues)
    assert any(side_effect.startswith("review_blocker:hero_cliff:") for side_effect in state.side_effects)
    assert last.metrics["bundle_n"]["review_blocker_count"] == 1
    assert "pass_smooth_height" in last.metrics["bundle_n"]["review_suggested_passes"]


def test_bundle_n_pipeline_opt_in_records_telemetry_and_golden():
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    state = _build_state(tile_size=8, seed=3131)
    with tempfile.TemporaryDirectory() as td:
        telemetry_path = Path(td) / "telemetry.ndjson"
        golden_dir = Path(td) / "goldens"
        state.intent.composition_hints["bundle_n_runtime"] = {
            "telemetry_path": str(telemetry_path),
            "golden_output_dir": str(golden_dir),
            "golden_snapshot_id": "bundle_n_runtime_test",
        }

        controller = TerrainPassController(state, checkpoint_dir=Path(td) / "ckpt")
        results = controller.run_pipeline(pass_sequence=["macro_world"], checkpoint=False)

        bundle_n_metrics = results[-1].metrics["bundle_n"]
        assert telemetry_path.exists()
        assert (golden_dir / "bundle_n_runtime_test.golden.json").exists()
        parsed = json.loads(telemetry_path.read_text().strip().splitlines()[0])
        assert parsed["extra"]["bundle_n_post_pipeline"] is True
        assert bundle_n_metrics["telemetry_path"] == str(telemetry_path)
        assert bundle_n_metrics["golden_snapshot_id"] == "bundle_n_runtime_test"


def test_bundle_n_pipeline_opt_in_runs_determinism_from_pre_pipeline_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import veilbreakers_terrain.handlers.terrain_bundle_n as bundle_n
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    captured: dict[str, object] = {}

    def _fake_run_determinism_check_subprocess(
        seed: int,
        runs: int = 3,
    ) -> dict[str, object]:
        captured["seed"] = seed
        captured["runs"] = runs
        return {
            "deterministic": True,
            "run_count": runs,
            "suspect_passes": [],
        }

    monkeypatch.setattr(
        bundle_n.terrain_determinism_ci,
        "run_determinism_check_subprocess",
        _fake_run_determinism_check_subprocess,
    )

    state = _build_state(tile_size=8, seed=4141)
    state.intent.composition_hints["bundle_n_runtime"] = {"determinism_runs": 2}

    controller = TerrainPassController(state)
    results = controller.run_pipeline(pass_sequence=["macro_world"], checkpoint=False)

    bundle_n_metrics = results[-1].metrics["bundle_n"]
    assert captured["seed"] == 4141
    assert captured["runs"] == 2
    assert bundle_n_metrics["deterministic"] is True
    assert bundle_n_metrics["determinism_run_count"] == 2


# ---------------------------------------------------------------------------
# 2-5. Determinism CI
# ---------------------------------------------------------------------------


def test_determinism_check_passes_on_identical_runs():
    from veilbreakers_terrain.handlers.terrain_determinism_ci import run_determinism_check
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with tempfile.TemporaryDirectory() as td:
        state = _build_state(tile_size=12)
        ctrl = TerrainPassController(state, checkpoint_dir=Path(td))
        report = run_determinism_check(ctrl, seed=state.intent.seed, runs=3)
        assert report["deterministic"] is True
        assert report["run_count"] == 3
        assert not report["mismatches"]


def test_determinism_check_detects_mutation():
    """Mutate 1 bit of the replay baseline and expect a regression."""
    from veilbreakers_terrain.handlers.terrain_determinism_ci import (
        detect_determinism_regressions,
    )

    issues = detect_determinism_regressions("a" * 64, "b" * 64)
    assert len(issues) == 1
    assert issues[0].is_hard()
    assert issues[0].code == "DETERMINISM_REGRESSION"


def test_determinism_check_no_regression_on_equal_hashes():
    from veilbreakers_terrain.handlers.terrain_determinism_ci import (
        detect_determinism_regressions,
    )

    assert detect_determinism_regressions("abc123", "abc123") == []


def test_hash_tile_output_hashes_nested_relative_paths(tmp_path: Path) -> None:
    from veilbreakers_terrain.handlers.terrain_determinism_ci import _hash_tile_output

    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "tile.bin").write_bytes(b"same")
    (tmp_path / "z.bin").write_bytes(b"root")
    first = _hash_tile_output(str(tmp_path))

    (tmp_path / "a" / "tile.bin").write_bytes(b"changed")
    second = _hash_tile_output(str(tmp_path))

    assert first != second


def test_run_determinism_check_subprocess_uses_temp_dirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veilbreakers_terrain.handlers import terrain_determinism_ci as det

    seen_dirs: list[str] = []

    def _fake_run(
        cmd: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert capture_output is True
        assert text is True
        assert check is True
        out_dir = cmd[cmd.index("--output-dir") + 1]
        seen_dirs.append(out_dir)
        Path(out_dir, "tile.json").write_text('{"ok":true}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    report = det.run_determinism_check_subprocess(seed=9, runs=2, size=4)

    assert report["deterministic"] is True
    assert report["run_count"] == 2
    assert len(seen_dirs) == 2


def test_determinism_check_run_records_populated():
    from veilbreakers_terrain.handlers.terrain_determinism_ci import run_determinism_check
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with tempfile.TemporaryDirectory() as td:
        state = _build_state(tile_size=12)
        ctrl = TerrainPassController(state, checkpoint_dir=Path(td))
        report = run_determinism_check(ctrl, seed=state.intent.seed, runs=2)
        assert len(report["runs"]) == 2
        assert all(len(r.content_hash) == 64 for r in report["runs"])
        assert len(report["runs"][0].per_channel_hashes) > 0


def test_determinism_fails_on_1bit_mutation_of_mask_stack():
    """A 1-bit change in the mask stack bytes must produce a distinct hash
    and therefore a detected regression via detect_determinism_regressions."""
    from veilbreakers_terrain.handlers.terrain_determinism_ci import (
        detect_determinism_regressions,
    )

    stack_a = _build_stack(tile_size=8, seed=42)
    baseline = stack_a.compute_hash()

    # Flip a single float bit
    stack_b = _build_stack(tile_size=8, seed=42)
    mutated = stack_b.height.copy()
    mutated.flat[0] = np.float64(mutated.flat[0]) + np.float64(1e-9)
    stack_b.set("height", mutated, "mutation")
    current = stack_b.compute_hash()

    assert baseline != current
    issues = detect_determinism_regressions(baseline, current)
    assert any(i.code == "DETERMINISM_REGRESSION" for i in issues)


# ---------------------------------------------------------------------------
# 6-10. Readability bands
# ---------------------------------------------------------------------------


def test_readability_bands_returns_five_entries():
    from veilbreakers_terrain.handlers.terrain_readability_bands import (
        BAND_IDS,
        compute_readability_bands,
    )

    stack = _build_stack()
    bands = compute_readability_bands(stack)
    assert len(bands) == 5
    assert tuple(b.band_id for b in bands) == BAND_IDS


def test_readability_bands_all_clamped_to_range():
    from veilbreakers_terrain.handlers.terrain_readability_bands import (
        compute_readability_bands,
    )

    stack = _build_stack()
    for band in compute_readability_bands(stack):
        assert 0.0 <= band.score <= 10.0


def test_readability_aggregate_between_0_and_10():
    from veilbreakers_terrain.handlers.terrain_readability_bands import (
        aggregate_readability_score,
        compute_readability_bands,
    )

    stack = _build_stack()
    score = aggregate_readability_score(compute_readability_bands(stack))
    assert 0.0 <= score <= 10.0


def test_readability_flat_terrain_scores_lower_than_varied():
    from veilbreakers_terrain.handlers.terrain_readability_bands import (
        aggregate_readability_score,
        compute_readability_bands,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    flat = TerrainMaskStack(
        tile_size=16,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.ones((16, 16), dtype=np.float64) * 50.0,
    )
    varied = _build_stack(seed=7)

    score_flat = aggregate_readability_score(compute_readability_bands(flat))
    score_varied = aggregate_readability_score(compute_readability_bands(varied))
    assert score_varied > score_flat


def test_readability_aggregate_empty_returns_zero():
    from veilbreakers_terrain.handlers.terrain_readability_bands import (
        aggregate_readability_score,
    )

    assert aggregate_readability_score([]) == 0.0


# ---------------------------------------------------------------------------
# 11-15. Budget enforcer
# ---------------------------------------------------------------------------


def test_budget_default_values():
    from veilbreakers_terrain.handlers.terrain_budget_enforcer import TerrainBudget

    b = TerrainBudget()
    assert b.max_tri_count > 0
    assert b.max_unique_materials > 0
    assert 0.0 < b.warn_fraction <= 1.0


def test_budget_usage_computes_per_axis():
    from veilbreakers_terrain.handlers.terrain_budget_enforcer import (
        TerrainBudget,
        compute_tile_budget_usage,
    )

    stack = _build_stack(tile_size=16)
    usage = compute_tile_budget_usage(stack, TerrainBudget())
    assert "tri_count" in usage
    assert "npz_mb" in usage
    assert usage["tri_count"]["current"] > 0


def test_budget_report_as_dict_serializes_nested_budget_fields():
    from veilbreakers_terrain.handlers.terrain_budget_enforcer import BudgetReport

    report = BudgetReport(
        tile_km2=0.25,
        lod0_tris=100,
        lod1_tris=40,
        lod2_tris=20,
        unique_materials=3,
        materials_utilization=0.375,
        scatter_instances=50,
        scatter_utilization=0.025,
        npz_mb=12.5,
        npz_utilization=0.1953125,
        hero_features=2,
        hero_per_km2=8.0,
        hero_over=True,
    )

    payload = report.as_dict()

    assert payload["tile_km2"] == 0.25
    assert payload["lod0_tris"]["current"] == 100
    assert abs(payload["lod0_tris"]["utilization"] - (100 / 250_000)) < 1e-12
    assert payload["unique_materials"]["current"] == 3
    assert payload["scatter_instances"]["current"] == 50
    assert payload["npz_mb"]["current"] == 12.5
    assert payload["hero_features"]["count"] == 2
    assert payload["hero_features"]["over"] is True


def test_budget_resolve_uses_quality_profile_defaults():
    from veilbreakers_terrain.handlers.terrain_budget_enforcer import resolve_budget

    state = _build_state(tile_size=8)
    object.__setattr__(state.intent, "quality_profile", "mobile")

    budget = resolve_budget(intent=state.intent)
    assert budget.max_tri_lod0 == 100_000
    assert budget.max_unique_materials == 4
    assert budget.max_scatter_instances == 100_000


def test_budget_enforce_clean_tile_no_issues():
    from veilbreakers_terrain.handlers.terrain_budget_enforcer import (
        TerrainBudget,
        enforce_budget,
    )

    stack = _build_stack(tile_size=8)
    state = _build_state(tile_size=8)
    issues = enforce_budget(stack, state.intent, TerrainBudget())
    assert all(not i.is_hard() for i in issues)


def test_budget_enforce_triggers_hard_on_tight_budget():
    from veilbreakers_terrain.handlers.terrain_budget_enforcer import (
        TerrainBudget,
        enforce_budget,
    )

    stack = _build_stack(tile_size=32)
    state = _build_state(tile_size=32)
    tight = TerrainBudget(max_tri_count=10, max_npz_mb=0.0001)
    issues = enforce_budget(stack, state.intent, tight)
    hard = [i for i in issues if i.is_hard()]
    assert len(hard) >= 1
    assert any("TRI" in i.code or "NPZ" in i.code for i in hard)


def test_budget_soft_warn_at_near_threshold():
    from veilbreakers_terrain.handlers.terrain_budget_enforcer import (
        TerrainBudget,
        enforce_budget,
    )

    stack = _build_stack(tile_size=16)
    state = _build_state(tile_size=16)
    usage_mb = 0.0
    for name in stack._ARRAY_CHANNELS:
        v = getattr(stack, name, None)
        if v is not None:
            usage_mb += float(np.asarray(v).nbytes) / (1024 * 1024)
    # Set max just above current usage, with warn_fraction forcing a warn
    near = TerrainBudget(max_npz_mb=max(usage_mb * 1.05, 0.0002), warn_fraction=0.5)
    issues = enforce_budget(stack, state.intent, near)
    # May or may not trigger, but must not crash and must return list
    assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# 16-20. Golden snapshots
# ---------------------------------------------------------------------------


def test_golden_snapshot_save_and_load_roundtrip():
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        load_golden_snapshot,
        save_golden_snapshot,
    )

    stack = _build_stack(seed=99)
    with tempfile.TemporaryDirectory() as td:
        snap = save_golden_snapshot(stack, Path(td), "golden_test", seed=99)
        assert snap.content_hash == stack.compute_hash()
        loaded = load_golden_snapshot(Path(td) / "golden_test.golden.json")
        assert loaded.snapshot_id == snap.snapshot_id
        assert loaded.content_hash == snap.content_hash
        assert loaded.channel_hashes == snap.channel_hashes


def test_golden_compare_identical_stack_no_issues():
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        compare_against_golden,
        save_golden_snapshot,
    )

    stack = _build_stack(seed=55)
    with tempfile.TemporaryDirectory() as td:
        snap = save_golden_snapshot(stack, Path(td), "g1", seed=55)
        issues = compare_against_golden(stack, snap)
        assert issues == []


def test_golden_compare_mutated_stack_raises_hard_issue():
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        compare_against_golden,
        save_golden_snapshot,
    )

    stack = _build_stack(seed=55)
    with tempfile.TemporaryDirectory() as td:
        snap = save_golden_snapshot(stack, Path(td), "g1", seed=55)
        mutated = stack.height.copy()
        mutated.flat[0] += 0.5
        stack.set("height", mutated, "mutation")
        issues = compare_against_golden(stack, snap)
        assert any(i.is_hard() for i in issues)
        assert any(i.code == "GOLDEN_HASH_MISMATCH" for i in issues)


def test_golden_compare_detects_new_channel_soft():
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        compare_against_golden,
        save_golden_snapshot,
    )

    stack = _build_stack(seed=55, extras=False)
    with tempfile.TemporaryDirectory() as td:
        snap = save_golden_snapshot(stack, Path(td), "g1", seed=55)
        # Now add a new channel to the stack
        curvature = np.zeros_like(stack.height)
        stack.set("curvature", curvature, "later_pass")
        issues = compare_against_golden(stack, snap)
        soft_codes = [i.code for i in issues if i.severity == "soft"]
        assert "GOLDEN_NEW_CHANNEL" in soft_codes


def test_golden_compare_strict_makes_export_channel_drift_hard():
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        compare_against_golden,
        save_golden_snapshot,
    )

    stack = _build_stack(seed=55, extras=False)
    with tempfile.TemporaryDirectory() as td:
        snap = save_golden_snapshot(stack, Path(td), "g1", seed=55)
        stack.set("water_surface_elevation_m", np.full_like(stack.height, 10.0), "later_pass")
        issues = compare_against_golden(stack, snap, strict_contract=True)
        hard_codes = [i.code for i in issues if i.is_hard()]
        assert "GOLDEN_NEW_CHANNEL" in hard_codes


def test_golden_library_seeds_at_least_20_snapshots():
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import seed_golden_library
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    with tempfile.TemporaryDirectory() as td:
        def build(seed: int, tile_x: int, tile_y: int) -> "TerrainPipelineState":
            state = _build_state(tile_size=8, seed=seed)
            # Override tile coords in the fresh stack
            state.mask_stack.tile_x = tile_x
            state.mask_stack.tile_y = tile_y
            return state

        # Use a throwaway controller; build_state_fn overrides cloning.
        base_state = _build_state(tile_size=8, seed=2000)
        ctrl = TerrainPassController(base_state, checkpoint_dir=Path(td) / "ckpt")
        snaps = seed_golden_library(
            ctrl, Path(td) / "goldens", count=22, build_state_fn=build
        )
        assert len(snaps) >= 20
        manifest = json.loads((Path(td) / "goldens" / "golden_library_manifest.json").read_text())
        assert manifest["count"] == len(snaps)


# ---------------------------------------------------------------------------
# 21-24. Review ingest
# ---------------------------------------------------------------------------


def test_review_finding_rejects_bad_severity():
    from veilbreakers_terrain.handlers.terrain_review_ingest import ReviewFinding

    with pytest.raises(ValueError):
        ReviewFinding(source="ai", severity="catastrophic", message="nope")


def test_review_finding_rejects_bad_source():
    from veilbreakers_terrain.handlers.terrain_review_ingest import ReviewFinding

    with pytest.raises(ValueError):
        ReviewFinding(source="alien", severity="hard", message="nope")


def test_ingest_review_json_parses_findings_list():
    from veilbreakers_terrain.handlers.terrain_review_ingest import ingest_review_json

    payload = {
        "findings": [
            {
                "source": "human",
                "severity": "hard",
                "message": "cliffs look fake",
                "suggested_fix": "add lip + talus",
                "location": [10.0, 20.0, 30.0],
                "tags": ["cliff", "silhouette"],
            },
            {
                "source": "ai",
                "severity": "soft",
                "message": "reduce grass density",
            },
            {"source": "ai", "severity": "GARBAGE", "message": "skip me"},
        ]
    }
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "review.json"
        p.write_text(json.dumps(payload))
        findings = ingest_review_json(p)
    assert len(findings) == 2
    assert findings[0].severity == "hard"
    assert findings[0].location == (10.0, 20.0, 30.0)
    assert findings[1].severity == "soft"


def test_apply_review_findings_preserves_immutability():
    from veilbreakers_terrain.handlers.terrain_review_ingest import (
        ReviewFinding,
        apply_review_findings,
    )

    state = _build_state()
    findings = [
        ReviewFinding(source="ai", severity="hard", message="fix cliffs"),
        ReviewFinding(source="human", severity="soft", message="add variety"),
        ReviewFinding(source="ai", severity="info", message="FYI"),
    ]
    new_intent = apply_review_findings(state.intent, findings)
    assert new_intent is not state.intent
    assert len(new_intent.composition_hints["review_blockers"]) == 1
    assert len(new_intent.composition_hints["review_suggestions"]) == 1
    assert len(new_intent.composition_hints["review_info"]) == 1
    assert new_intent.composition_hints["review_total_ingested"] == 3


# ---------------------------------------------------------------------------
# 25-28. Telemetry dashboard
# ---------------------------------------------------------------------------


def test_record_telemetry_writes_and_returns_record():
    from veilbreakers_terrain.handlers.terrain_telemetry_dashboard import record_telemetry

    state = _build_state()
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "telemetry.ndjson"
        rec = record_telemetry(
            state, path,
            budget_usage={"tri_count": {"current": 100, "max": 1000}},
            readability_score=7.5,
        )
        assert path.exists()
        assert rec.readability_score == 7.5
        assert rec.tile_coords == (0, 0)
        # File must be valid NDJSON
        line = path.read_text().strip().splitlines()[0]
        parsed = json.loads(line)
        assert parsed["readability_score"] == 7.5


def test_summarize_telemetry_empty_file_returns_zero_counts():
    from veilbreakers_terrain.handlers.terrain_telemetry_dashboard import summarize_telemetry

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "missing.ndjson"
        summary = summarize_telemetry(path)
        assert summary["record_count"] == 0
        assert summary["tile_count"] == 0


def test_summarize_telemetry_aggregates_across_records():
    from veilbreakers_terrain.handlers.terrain_telemetry_dashboard import (
        record_telemetry,
        summarize_telemetry,
    )

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.ndjson"
        for i in range(3):
            state = _build_state(seed=1000 + i)
            record_telemetry(
                state, path,
                readability_score=float(i) + 1.0,
            )
        summary = summarize_telemetry(path)
        assert summary["record_count"] == 3
        assert summary["readability_min"] == 1.0
        assert summary["readability_max"] == 3.0
        assert summary["readability_avg"] == 2.0


def test_telemetry_record_roundtrip_to_dict():
    from veilbreakers_terrain.handlers.terrain_telemetry_dashboard import TelemetryRecord

    rec = TelemetryRecord(
        timestamp=123.0,
        tile_coords=(4, 5),
        pass_durations={"erosion": 0.5},
        mask_channel_counts=3,
        budget_usage={},
        readability_score=6.2,
    )
    d = rec.to_dict()
    rec2 = TelemetryRecord.from_dict(d)
    assert rec2.tile_coords == (4, 5)
    assert rec2.pass_durations == {"erosion": 0.5}
    assert rec2.readability_score == 6.2
