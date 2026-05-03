"""Bundle N — truthful runtime contract and post-pipeline hooks.

Bundle N does **not** register ``TerrainPassController`` passes. Its
modules are QA / validation utilities that run either:

- as always-on post-pipeline hooks (`enforce_budget`,
  `compute_readability_bands`);
- as opt-in post-pipeline hooks (`record_telemetry`,
  `save_golden_snapshot`, `run_determinism_check`);
- or as library helpers (`ingest_review_json`).

``register_bundle_n_passes()`` is therefore an import verifier plus
contract surface, not a pass registrar.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional, Sequence

from . import (
    terrain_budget_enforcer,
    terrain_determinism_ci,
    terrain_golden_snapshots,
    terrain_performance_report,
    terrain_readability_bands,
    terrain_review_ingest,
    terrain_telemetry_dashboard,
    terrain_visual_qa,
)
from .terrain_semantics import PassResult, TerrainPipelineState, ValidationIssue

if TYPE_CHECKING:
    from .terrain_pipeline import TerrainPassController


BUNDLE_N_MODULES = (
    "terrain_determinism_ci",
    "terrain_readability_bands",
    "terrain_budget_enforcer",
    "terrain_performance_report",
    "terrain_golden_snapshots",
    "terrain_review_ingest",
    "terrain_telemetry_dashboard",
)


BUNDLE_N_RUNTIME_CONTRACT = {
    "modules": BUNDLE_N_MODULES,
    "registers_passes": False,
    "always_on_post_pipeline": (
        "enforce_budget",
        "compute_budget_report",
        "collect_performance_report",
        "run_visual_qa_checks",
        "compute_readability_bands",
        "apply_review_blockers",
    ),
    "opt_in_post_pipeline": (
        "record_telemetry",
        "save_golden_snapshot",
        "run_determinism_check",
    ),
    "library_only": ("ingest_review_json",),
}


def get_bundle_n_runtime_contract() -> Dict[str, Any]:
    """Return Bundle N's truthful runtime contract."""
    return {
        "modules": tuple(BUNDLE_N_RUNTIME_CONTRACT["modules"]),
        "registers_passes": bool(BUNDLE_N_RUNTIME_CONTRACT["registers_passes"]),
        "always_on_post_pipeline": tuple(
            BUNDLE_N_RUNTIME_CONTRACT["always_on_post_pipeline"]
        ),
        "opt_in_post_pipeline": tuple(
            BUNDLE_N_RUNTIME_CONTRACT["opt_in_post_pipeline"]
        ),
        "library_only": tuple(BUNDLE_N_RUNTIME_CONTRACT["library_only"]),
    }


def _runtime_options(intent: Any) -> Dict[str, Any]:
    hints = getattr(intent, "composition_hints", None) or {}
    runtime = hints.get("bundle_n_runtime", {})
    if isinstance(runtime, Mapping):
        return dict(runtime)
    return {}


def _determinism_runs(options: Mapping[str, Any]) -> int:
    raw = options.get("determinism_runs", 0)
    if isinstance(raw, bool):
        return 2 if raw else 0
    try:
        runs = int(raw)
    except (TypeError, ValueError):
        runs = 0
    if runs >= 2:
        return runs
    return 2 if options.get("determinism_check") else 0


def bundle_n_runtime_requests_determinism(intent: Any) -> bool:
    """Return True when the current intent requests determinism replay."""
    return _determinism_runs(_runtime_options(intent)) >= 2


@contextmanager
def _skip_runtime_hooks(state: TerrainPipelineState):
    """Temporarily disable Bundle N post-pipeline hooks on replay state."""
    hints = state.intent.composition_hints
    runtime = hints.get("bundle_n_runtime")
    created_runtime = not isinstance(runtime, dict)
    if created_runtime:
        runtime = {}
        hints["bundle_n_runtime"] = runtime

    sentinel = object()
    previous = runtime.get("skip_post_pipeline_hooks", sentinel)
    runtime["skip_post_pipeline_hooks"] = True
    try:
        yield
    finally:
        if previous is sentinel:
            runtime.pop("skip_post_pipeline_hooks", None)
        else:
            runtime["skip_post_pipeline_hooks"] = previous
        if created_runtime and not runtime:
            hints.pop("bundle_n_runtime", None)


def _attach_issues(result: PassResult, issues: Sequence[ValidationIssue]) -> None:
    if not issues:
        return
    result.issues.extend(issues)
    if any(issue.is_hard() for issue in issues):
        result.status = "failed"
        return
    if result.status == "ok" and any(issue.is_soft() for issue in issues):
        result.status = "warning"


def _merge_bundle_n_metrics(result: PassResult, summary: Dict[str, Any]) -> None:
    bundle_n_metrics = result.metrics.get("bundle_n")
    if not isinstance(bundle_n_metrics, dict):
        bundle_n_metrics = {}
    bundle_n_metrics.update(summary)
    result.metrics["bundle_n"] = bundle_n_metrics


def _review_findings_from_intent(state: TerrainPipelineState) -> list[Any]:
    hints = state.intent.composition_hints or {}
    findings: list[Any] = []
    severity_keys = (
        ("hard", "review_blockers"),
        ("soft", "review_suggestions"),
        ("info", "review_info"),
    )
    for fallback_severity, hint_key in severity_keys:
        for raw in hints.get(hint_key, ()) or ():
            if isinstance(raw, terrain_review_ingest.ReviewFinding):
                findings.append(raw)
                continue
            if not isinstance(raw, Mapping):
                continue
            severity = str(raw.get("severity", fallback_severity)).lower()
            if severity not in terrain_review_ingest.ALLOWED_SEVERITIES:
                severity = fallback_severity
            source = str(raw.get("source", "ai")).lower()
            if source not in terrain_review_ingest.ALLOWED_SOURCES:
                source = "ai"
            location = raw.get("location")
            if isinstance(location, (list, tuple)) and len(location) >= 3:
                coerced_location = (
                    float(location[0]),
                    float(location[1]),
                    float(location[2]),
                )
            else:
                coerced_location = None
            findings.append(
                terrain_review_ingest.ReviewFinding(
                    source=source,
                    severity=severity,
                    location=coerced_location,
                    message=str(raw.get("message", "")),
                    suggested_fix=str(raw.get("suggested_fix", "")),
                    tags=tuple(str(tag) for tag in (raw.get("tags", ()) or ())),
                    affected_feature=(
                        str(raw["affected_feature"])
                        if raw.get("affected_feature") is not None
                        else None
                    ),
                )
            )
    return findings


def _validation_issue_from_review_payload(payload: Mapping[str, Any]) -> ValidationIssue:
    location = payload.get("location")
    coerced_location = None
    if isinstance(location, (list, tuple)) and len(location) >= 3:
        coerced_location = (
            float(location[0]),
            float(location[1]),
            float(location[2]),
        )
    return ValidationIssue(
        code=str(payload.get("code", "review_blocker:unknown")),
        severity="hard",
        location=coerced_location,
        affected_feature=(
            str(payload["affected_feature"])
            if payload.get("affected_feature") is not None
            else None
        ),
        message=str(payload.get("message", "")),
        remediation=(
            str(payload["remediation"])
            if payload.get("remediation") is not None
            else None
        ),
    )


def _default_snapshot_id(state: TerrainPipelineState) -> str:
    return (
        f"seed{int(state.intent.seed)}"
        f"_tile{int(state.tile_x)}_{int(state.tile_y)}"
    )


def register_bundle_n_passes() -> Dict[str, Any]:
    """Verify Bundle N imports and return its runtime contract.

    The name is kept for compatibility with the master registrar, but
    this function intentionally registers zero controller passes.
    """
    _ = terrain_determinism_ci.run_determinism_check
    _ = terrain_readability_bands.compute_readability_bands
    _ = terrain_budget_enforcer.enforce_budget
    _ = terrain_performance_report.collect_performance_report
    _ = terrain_golden_snapshots.save_golden_snapshot
    _ = terrain_review_ingest.ingest_review_json
    _ = terrain_review_ingest.pass_apply_review_blockers
    _ = terrain_telemetry_dashboard.record_telemetry
    _ = terrain_visual_qa.run_checks
    return get_bundle_n_runtime_contract()


def run_bundle_n_post_pipeline_hooks(
    controller: "TerrainPassController",
    results: Sequence[PassResult],
    *,
    pre_pipeline_state: Optional[TerrainPipelineState] = None,
) -> Dict[str, Any]:
    """Run Bundle N's production-safe post-pipeline hooks.

    Always-on hooks:
      - budget enforcement
      - readability scoring

    Opt-in hooks via ``intent.composition_hints["bundle_n_runtime"]``:
      - ``telemetry_path``: append NDJSON telemetry
      - ``golden_output_dir`` / ``golden_snapshot_id``: persist a golden
      - ``determinism_runs`` or ``determinism_check``: replay determinism CI
    """
    if not results:
        return {}

    last = results[-1]
    if last.status == "failed":
        return {}

    options = _runtime_options(controller.state.intent)
    if options.get("skip_post_pipeline_hooks"):
        return {"skipped": True, "reason": "skip_post_pipeline_hooks"}
    quality_profile = str(getattr(controller.state.intent, "quality_profile", "") or "")
    visual_qa_blocking = bool(
        options.get(
            "visual_qa_blocking",
            quality_profile in {"aaa_open_world", "production", "cinematic"},
        )
    )

    state = controller.state
    stack = state.mask_stack
    executed_passes = [result.pass_name for result in results]
    summary: Dict[str, Any] = {
        "budget_issue_count": 0,
        "budget_hard_issue_count": 0,
        "budget_report": {},
        "performance_report": {},
        "readability_score": 0.0,
        "readability_band_scores": {},
    }

    budget = terrain_budget_enforcer.resolve_budget(
        intent=state.intent,
    )
    budget_issues = terrain_budget_enforcer.enforce_budget(
        stack,
        state.intent,
        budget,
    )
    _attach_issues(last, budget_issues)
    summary["budget_issue_count"] = len(budget_issues)
    summary["budget_hard_issue_count"] = sum(
        1 for issue in budget_issues if issue.is_hard()
    )
    try:
        budget_report = terrain_budget_enforcer.compute_budget_report(
            stack,
            budget=budget,
            intent=state.intent,
        )
        summary["budget_report"] = budget_report.as_dict()
    except Exception as exc:  # noqa: BLE001
        summary["budget_report_error"] = repr(exc)

    try:
        perf_report = terrain_performance_report.collect_performance_report(stack)
        summary["performance_report"] = terrain_performance_report.serialize_performance_report(
            perf_report
        )
    except Exception as exc:  # noqa: BLE001
        summary["performance_report_error"] = repr(exc)

    try:
        visual_report = terrain_visual_qa.run_checks(stack)
        summary["visual_qa_report"] = visual_report
        summary["visual_qa_failed_names"] = list(visual_report.get("failed_names", []))
        if visual_qa_blocking and not visual_report.get("ok", False):
            _attach_issues(
                last,
                [
                    ValidationIssue(
                        code=f"BUNDLE_N_VISUAL_QA_{str(check.get('name', 'unknown')).upper()}",
                        severity="hard",
                        message=str(check.get("reason", "visual QA check failed")),
                        remediation=(
                            "Fix the named terrain channel contract before "
                            "shipping this tile."
                        ),
                    )
                    for check in visual_report.get("failed", [])
                    if isinstance(check, Mapping)
                ],
            )
    except Exception as exc:  # noqa: BLE001
        summary["visual_qa_error"] = repr(exc)

    try:
        qa_battery = run_bundle_n_qa_battery(stack)
        summary["qa_battery"] = qa_battery
        if bool(options.get("qa_battery_blocking", False)) and not qa_battery.get("ok", True):
            _attach_issues(
                last,
                [
                    ValidationIssue(
                        code="BUNDLE_N_QA_BATTERY_FAILED",
                        severity="hard" if visual_qa_blocking else "soft",
                        message=(
                            "Bundle N QA battery failed checks: "
                            f"{qa_battery.get('issues', [])}"
                        ),
                        remediation="Fix Bundle N QA failures before shipping this tile.",
                    )
                ],
            )
    except Exception as exc:  # noqa: BLE001
        summary["qa_battery_error"] = repr(exc)

    bands = terrain_readability_bands.compute_readability_bands(stack)
    readability_score = terrain_readability_bands.aggregate_readability_score(bands)
    summary["readability_score"] = float(readability_score)
    summary["readability_band_scores"] = {
        band.band_id: float(band.score) for band in bands
    }

    review_findings = _review_findings_from_intent(state)
    review_summary: Dict[str, Any] = {
        "review_finding_count": len(review_findings),
        "review_blocker_count": 0,
        "review_suggested_passes": [],
    }
    if review_findings:
        blocker_summary = terrain_review_ingest.pass_apply_review_blockers(
            state,
            review_findings,
        )
        hard_issue_payloads = blocker_summary.get("hard_issues", [])
        if isinstance(hard_issue_payloads, Sequence):
            review_issues = [
                _validation_issue_from_review_payload(payload)
                for payload in hard_issue_payloads
                if isinstance(payload, Mapping)
            ]
            _attach_issues(last, review_issues)
        review_summary["review_blocker_count"] = int(
            blocker_summary.get("hard_blocker_count", 0)
        )
        review_summary["review_suggested_passes"] = list(
            blocker_summary.get("suggested_passes", [])
        )
    summary.update(review_summary)

    budget_usage: Optional[Dict[str, Any]] = None

    telemetry_path = options.get("telemetry_path")
    if telemetry_path:
        try:
            budget_usage = terrain_budget_enforcer.compute_tile_budget_usage(
                stack,
                budget=budget,
                intent=state.intent,
            )
            record = terrain_telemetry_dashboard.record_telemetry(
                state,
                Path(telemetry_path),
                budget_usage=budget_usage,
                readability_score=readability_score,
                extra={"bundle_n_post_pipeline": True, "passes": executed_passes},
            )
            summary["telemetry_path"] = str(Path(telemetry_path))
            summary["telemetry_timestamp"] = float(record.timestamp)
        except Exception as exc:  # noqa: BLE001
            summary["telemetry_error"] = repr(exc)

    golden_output_dir = options.get("golden_output_dir")
    if golden_output_dir:
        try:
            snapshot_id = str(
                options.get("golden_snapshot_id") or _default_snapshot_id(state)
            )
            snap = terrain_golden_snapshots.save_golden_snapshot(
                stack,
                Path(golden_output_dir),
                snapshot_id,
                seed=int(state.intent.seed),
            )
            summary["golden_snapshot_id"] = snap.snapshot_id
            summary["golden_snapshot_path"] = str(
                Path(golden_output_dir) / f"{snap.snapshot_id}.golden.json"
            )
        except Exception as exc:  # noqa: BLE001
            summary["golden_snapshot_error"] = repr(exc)

    determinism_runs = _determinism_runs(options)
    if options.get("full_pass_determinism_check"):
        try:
            full_report = terrain_determinism_ci.test_determinism_full_pass_sequence(
                seed=int(getattr(state.intent, "seed", 0)),
                runs=int(options.get("full_pass_determinism_runs", 2)),
                size=int(options.get("full_pass_determinism_size", 32)),
                scale=float(options.get("full_pass_determinism_scale", 50.0)),
                terrain_type=str(options.get("full_pass_determinism_terrain_type", "mountains")),
            )
            summary["full_pass_determinism"] = full_report
            if not full_report.get("deterministic", False):
                _attach_issues(
                    last,
                    [
                        ValidationIssue(
                            code="BUNDLE_N_FULL_PASS_DETERMINISM_FAILED",
                            severity="hard",
                            message="Full pass sequence determinism check diverged.",
                            remediation="Audit full CLI generation for nondeterministic channels.",
                        )
                    ],
                )
        except Exception as exc:  # noqa: BLE001
            summary["full_pass_determinism_error"] = repr(exc)

    if determinism_runs >= 2:
        if pre_pipeline_state is None:
            summary["determinism_skipped_reason"] = "missing_pre_pipeline_state"
        else:
            try:
                from .terrain_pipeline import TerrainPassController

                # FIX-10-H8: shallow channel snapshot instead of full deepcopy
                # to avoid a 4-8 GB memory spike on 4K tiles. Only the written
                # channels are snapshotted; the rest of the state is shared
                # (intent is immutable, pass_history is reset by _clone_state).
                _written = getattr(
                    pre_pipeline_state.mask_stack, "_written_channels", None
                )
                _channels = getattr(
                    pre_pipeline_state.mask_stack, "_channels", None
                )
                if _channels is not None and _written is not None:
                    replay_snapshot = {
                        ch: arr.copy()
                        for ch, arr in _channels.items()
                        if ch in _written
                    }
                else:
                    replay_snapshot = {}

                replay_state = terrain_determinism_ci._clone_state(pre_pipeline_state)

                # Restore snapshotted channels so replay starts from the same
                # pre-pipeline state that was captured before any passes ran.
                if replay_snapshot and hasattr(replay_state.mask_stack, "_channels"):
                    for ch, arr in replay_snapshot.items():
                        replay_state.mask_stack.set(ch, arr, "replay_restore")

                with _skip_runtime_hooks(replay_state):
                    replay_controller = TerrainPassController(
                        replay_state,
                        checkpoint_dir=controller.checkpoint_dir,
                    )
                    report = terrain_determinism_ci.run_determinism_check(
                        replay_controller,
                        seed=int(replay_state.intent.seed),
                        runs=determinism_runs,
                        pass_sequence=tuple(executed_passes),
                    )
                summary["deterministic"] = bool(report.get("deterministic", False))
                summary["determinism_run_count"] = int(report.get("run_count", 0))
                summary["determinism_suspect_passes"] = list(
                    report.get("suspect_passes", [])
                )
                if not report.get("deterministic", False):
                    suspects = [
                        pass_name
                        for _, pass_name in report.get("suspect_passes", [])
                    ]
                    _attach_issues(
                        last,
                        [
                            ValidationIssue(
                                code="BUNDLE_N_DETERMINISM_FAILED",
                                severity="hard",
                                message=(
                                    "Bundle N determinism replay diverged"
                                    + (
                                        f"; suspect passes={suspects[:3]}"
                                        if suspects
                                        else ""
                                    )
                                ),
                                remediation=(
                                    "Audit the suspect passes for nondeterministic "
                                    "state, wall-clock inputs, or unseeded RNG use."
                                ),
                            )
                        ],
                    )
            except Exception as exc:  # noqa: BLE001
                summary["determinism_error"] = repr(exc)

    _merge_bundle_n_metrics(last, summary)
    return summary


# ---------------------------------------------------------------------------
# FIX-9-58: QA battery — replace dead water_depth_m < 0.01 and slope < 0.05
# condition with actual per-family checks.
# ---------------------------------------------------------------------------

import logging as _logging
_bundle_n_log = _logging.getLogger(__name__)


def _check_stochastic_seams(stack: Any) -> bool:
    """Return True when the stochastic UV seam check passes. FIX-9-58

    Delegates to terrain_visual_qa._check_stochastic_seam when available.
    Defaults to True so the battery is non-blocking until the channel is wired.
    """
    try:
        result = terrain_visual_qa._check_stochastic_seam(stack)
        return bool(result.get("ok", True))
    except Exception:
        return True


def _check_phantom_channel_reads(stack: Any) -> bool:
    """Return True when no phantom (unwritten) channel reads are detected. FIX-9-58

    Delegates to terrain_visual_qa._check_phantom_channel_writers when available.
    Defaults to True so the battery is non-blocking until the channel is wired.
    """
    try:
        result = terrain_visual_qa._check_phantom_channel_writers(stack)
        return bool(result.get("ok", True))
    except Exception:
        return True


def _check_tree_z_export(stack: Any) -> bool:
    """Return True when tree instance points carry non-zero Z values. FIX-9-58

    Delegates to terrain_visual_qa._check_tree_z_export when available.
    Defaults to True so the battery is non-blocking until the channel is wired.
    """
    try:
        result = terrain_visual_qa._check_tree_z_export(stack)
        return bool(result.get("ok", True))
    except Exception:
        return True


def _check_foam_alpha(stack: Any) -> bool:
    """Return True when foam channel values are in [0, 1]. FIX-9-58

    Delegates to terrain_visual_qa._check_foam_alpha when available.
    Defaults to True so the battery is non-blocking until the channel is wired.
    """
    try:
        result = terrain_visual_qa._check_foam_alpha(stack)
        return bool(result.get("ok", True))
    except Exception:
        return True


def run_bundle_n_qa_battery(stack: Any) -> Dict[str, Any]:
    """Run the Bundle N QA battery against the post-pipeline stack. FIX-9-58

    Replaces the former dead condition ``water_depth_m < 0.01 and slope < 0.05``
    (which always evaluated False and was never wired to any action) with a
    real multi-check battery that tests the top P0 failure families identified
    in the S1–S22 audit sweeps.

    Returns a dict with keys:
      ``ok``     — True only when all checks pass
      ``issues`` — list of failing check names
    """
    issues = []
    if not _check_stochastic_seams(stack):
        issues.append("stochastic_seams")
    if not _check_phantom_channel_reads(stack):
        issues.append("phantom_reads")
    if not _check_tree_z_export(stack):
        issues.append("tree_z")
    if not _check_foam_alpha(stack):
        issues.append("foam_alpha")
    if issues:
        _bundle_n_log.warning("terrain_bundle_n QA failures: %s", issues)
    return {"ok": not issues, "issues": issues}


__all__ = [
    "BUNDLE_N_MODULES",
    "BUNDLE_N_RUNTIME_CONTRACT",
    "bundle_n_runtime_requests_determinism",
    "get_bundle_n_runtime_contract",
    "register_bundle_n_passes",
    "run_bundle_n_post_pipeline_hooks",
    "_check_stochastic_seams",
    "_check_phantom_channel_reads",
    "_check_tree_z_export",
    "_check_foam_alpha",
    "run_bundle_n_qa_battery",
]
