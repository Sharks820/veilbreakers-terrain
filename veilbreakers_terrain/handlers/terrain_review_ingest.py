"""Bundle N — review ingest / intent-feedback loop.

Parses review JSON (from a human reviewer OR from an AI reviewer run such
as ``vb-review``) and folds the findings into the terrain
``TerrainIntentState`` as new composition hints, protected-zone bumps,
or hero feature tweaks.

Pure stdlib — no bpy, no numpy required. See plan §19.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .terrain_semantics import TerrainIntentState, TerrainPipelineState, ValidationIssue


ALLOWED_SEVERITIES: Tuple[str, ...] = ("hard", "soft", "info")
ALLOWED_SOURCES: Tuple[str, ...] = ("human", "ai")


@dataclass
class ReviewFinding:
    """One item from an external review report."""

    source: str  # "human" | "ai"
    severity: str  # "hard" | "soft" | "info"
    location: Optional[Tuple[float, float, float]] = None
    message: str = ""
    suggested_fix: str = ""
    tags: Tuple[str, ...] = ()
    affected_feature: Optional[str] = None

    def __post_init__(self) -> None:
        if self.source not in ALLOWED_SOURCES:
            raise ValueError(
                f"ReviewFinding.source must be one of {ALLOWED_SOURCES}, got {self.source!r}"
            )
        if self.severity not in ALLOWED_SEVERITIES:
            raise ValueError(
                f"ReviewFinding.severity must be one of {ALLOWED_SEVERITIES}, got {self.severity!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.location is not None:
            d["location"] = list(self.location)
        d["tags"] = list(self.tags)
        return d


def _coerce_location(raw: Any) -> Optional[Tuple[float, float, float]]:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        return (float(raw[0]), float(raw[1]), float(raw[2]))
    return None


def ingest_review_json(path: Path) -> List[ReviewFinding]:
    """Parse a review report JSON file into a list of ReviewFinding.

    BUG-R8-A9-029: malformed entries are no longer silently swallowed.
    Each skip reason is collected and logged at WARNING level after the
    loop so callers can audit data quality.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    data = json.loads(Path(path).read_text())
    findings_raw: List[Dict[str, Any]]
    if isinstance(data, dict) and "findings" in data:
        findings_raw = list(data["findings"])
    elif isinstance(data, list):
        findings_raw = list(data)
    else:
        raise ValueError(
            f"Unsupported review JSON shape — expected 'findings' key or list, "
            f"got {type(data).__name__}"
        )
    out: List[ReviewFinding] = []
    # BUG-R8-A9-029: collect skip reasons instead of silently continuing
    skipped_reasons: List[str] = []
    for idx, item in enumerate(findings_raw):
        if not isinstance(item, dict):
            skipped_reasons.append(f"[{idx}] not a dict: {type(item).__name__}")
            continue
        try:
            finding = ReviewFinding(
                source=str(item.get("source", "ai")),
                severity=str(item.get("severity", "soft")),
                location=_coerce_location(item.get("location")),
                message=str(item.get("message", "")),
                suggested_fix=str(item.get("suggested_fix", "")),
                tags=tuple(str(t) for t in item.get("tags", [])),
                affected_feature=(
                    str(item["affected_feature"])
                    if item.get("affected_feature") is not None
                    else None
                ),
            )
        except ValueError as exc:
            skipped_reasons.append(f"[{idx}] ValueError: {exc}")
            continue
        out.append(finding)

    if skipped_reasons:
        _log.warning(
            "ingest_review_json: skipped %d malformed entr%s in %s:\n  %s",
            len(skipped_reasons),
            "y" if len(skipped_reasons) == 1 else "ies",
            path,
            "\n  ".join(skipped_reasons),
        )
    return out


def apply_review_findings(
    intent: TerrainIntentState,
    findings: List[ReviewFinding],
) -> TerrainIntentState:
    """Fold review findings back into the authoring intent.

    Hard findings set ``composition_hints['review_blockers']``, soft findings
    append to ``composition_hints['review_suggestions']``. This function
    never mutates ``intent`` in place — it returns a new frozen dataclass.
    """
    from dataclasses import replace as _replace

    hints = dict(intent.composition_hints)
    blockers: List[Dict[str, Any]] = list(hints.get("review_blockers", []))
    suggestions: List[Dict[str, Any]] = list(hints.get("review_suggestions", []))
    info: List[Dict[str, Any]] = list(hints.get("review_info", []))

    for f in findings:
        payload = f.to_dict()
        if f.severity == "hard":
            blockers.append(payload)
        elif f.severity == "soft":
            suggestions.append(payload)
        else:
            info.append(payload)

    hints["review_blockers"] = blockers
    hints["review_suggestions"] = suggestions
    hints["review_info"] = info
    hints["review_total_ingested"] = int(
        hints.get("review_total_ingested", 0)
    ) + len(findings)

    return _replace(intent, composition_hints=hints)


# ---------------------------------------------------------------------------
# Action-verb → pass name mapping for suggestion routing
# ---------------------------------------------------------------------------

_ACTION_VERB_TO_PASS: Dict[str, str] = {
    "erode": "pass_erosion",
    "erosion": "pass_erosion",
    "smooth": "pass_smooth_height",
    "smoothing": "pass_smooth_height",
    "cliff": "pass_cliff_candidate",
    "cliffs": "pass_cliff_candidate",
    "cave": "pass_cave_candidate",
    "caves": "pass_cave_candidate",
    "waterfall": "pass_waterfall_candidate",
    "waterfalls": "pass_waterfall_candidate",
    "water": "pass_water_network",
    "river": "pass_water_network",
    "rivers": "pass_water_network",
    "material": "pass_material_zoning",
    "materials": "pass_material_zoning",
    "biome": "pass_biome_assignment",
    "vegetation": "pass_ecosystem",
    "foliage": "pass_ecosystem",
    "scatter": "pass_scatter",
    "noise": "pass_base_noise",
    "heightmap": "pass_base_noise",
    "slope": "pass_structural_masks",
    "curvature": "pass_structural_masks",
    "ridge": "pass_structural_masks",
    "drainage": "pass_water_network",
    "splatmap": "pass_quixel_ingest",
    "texture": "pass_quixel_ingest",
}


def pass_apply_review_blockers(
    state: TerrainPipelineState,
    findings: List[ReviewFinding],
) -> Dict[str, Any]:
    """Translate review findings into ValidationIssues on the mask stack and
    return a list of suggested passes to run for soft/info findings.

    For each hard blocker with a location: creates a ValidationIssue and
    appends it to ``state.mask_stack``'s issues registry via the pass
    history side-channel (stored as ``state.side_effects`` entries with a
    structured prefix so downstream tooling can parse them).

    For each suggestion (soft/info) whose message or suggested_fix contains
    recognised action verbs: maps to a known pass name and collects it in
    ``suggested_passes``.

    Returns a summary dict with counts and the suggested pass list.
    """
    hard_issues: List[ValidationIssue] = []
    suggested_passes: List[str] = []
    seen_passes: set = set()

    for finding in findings:
        if finding.severity == "hard":
            issue = ValidationIssue(
                code=f"review_blocker:{finding.affected_feature or 'unknown'}",
                severity="hard",
                location=finding.location,
                affected_feature=finding.affected_feature,
                message=finding.message,
                remediation=finding.suggested_fix or None,
            )
            hard_issues.append(issue)
            # Persist as a structured side_effect so the pass history is
            # queryable without a separate issues list on the mask stack.
            loc_str = (
                f"{finding.location[0]:.2f},{finding.location[1]:.2f},{finding.location[2]:.2f}"
                if finding.location
                else "none"
            )
            state.side_effects.append(
                f"review_blocker:{finding.affected_feature or 'unknown'}:"
                f"loc={loc_str}:{finding.message}"
            )
        else:
            # Soft / info — scan message + suggested_fix for action verbs
            text = f"{finding.message} {finding.suggested_fix}".lower()
            for verb, pass_name in _ACTION_VERB_TO_PASS.items():
                if verb in text and pass_name not in seen_passes:
                    suggested_passes.append(pass_name)
                    seen_passes.add(pass_name)

    return {
        "hard_blocker_count": len(hard_issues),
        "hard_issues": [
            {
                "code": vi.code,
                "location": list(vi.location) if vi.location else None,
                "affected_feature": vi.affected_feature,
                "message": vi.message,
                "remediation": vi.remediation,
            }
            for vi in hard_issues
        ],
        "suggested_passes": suggested_passes,
    }


__all__ = [
    "ALLOWED_SEVERITIES",
    "ALLOWED_SOURCES",
    "ReviewFinding",
    "ingest_review_json",
    "apply_review_findings",
    "pass_apply_review_blockers",
]
