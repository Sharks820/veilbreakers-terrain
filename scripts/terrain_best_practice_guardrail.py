"""Executable guardrail for terrain callable best-practice coverage.

This script turns the industry best-practice callable matrix into an enforceable
check. It verifies every live handler callable has a matrix row, every matrix
row has the required contract/gate/artifact fields, and duplicate callable names
are reported for routing review.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from grade_audit_shared import REPO_ROOT, collect_callables
except ModuleNotFoundError:
    from scripts.grade_audit_shared import REPO_ROOT, collect_callables


MATRIX_GLOB = "INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_*.csv"
DEFAULT_REPORT_MD = REPO_ROOT / "output" / "verification" / "TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.md"
DEFAULT_REPORT_JSON = REPO_ROOT / "output" / "verification" / "TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.json"
DEFAULT_USAGE_GUIDE = REPO_ROOT / "docs" / "TERRAIN_CALLABLE_USAGE_GUARDRAIL.md"
CALLABLE_VERIFICATION_SUMMARY_JSON = REPO_ROOT / "output" / "verification" / "CALLABLE_VERIFICATION_SUMMARY.json"
DEFAULT_DUPLICATE_REVIEW = REPO_ROOT / "docs" / "aaa-audit" / "CALLABLE_DUPLICATE_REVIEW.json"

REQUIRED_MATRIX_FIELDS = [
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

AAA_GRADE_TOKENS = {"A+", "A", "A-"}
BLOCKING_UPGRADE_TIERS = {"P0"}
BLOCKING_GRADE_STATUSES = {
    "MISSING_GRADE",
    "AMBIGUOUS_FILE_MATCH",
    "AMBIGUOUS_NAME_MATCH",
    "NAME_ONLY_MATCH",
}

DOMAIN_PURPOSE = {
    "terrain_pipeline": "Use `terrain_pipeline` callables for canonical pass orchestration, dependency contracts, handler registration, checkpoints, and generated-map provenance.",
    "heightfield_geomorph": "Use `heightfield_geomorph` callables for terrain shape, heightfields, cliffs, caves, erosion, talus, strata, geology, weathering, slope, curvature, and landform masks.",
    "hydrology": "Use `hydrology` callables for water systems: rivers, lakes, waterfalls, wetlands, flow direction, velocity, depth, foam, mist, wet rock, caustics, and seam continuity.",
    "scatter_ecology": "Use `scatter_ecology` callables for point distribution, vegetation placement, biome/ecotone logic, wildlife zones, density masks, and exclusion rules.",
    "foliage_assets": "Use `foliage_assets` callables for species catalogs, vegetation prototypes, LOD paths, impostors, billboards, wind profiles, and asset fallback metadata.",
    "terrain_texturing": "Use `terrain_texturing` callables for terrain texture/PBR work: material weights, splatmaps, base color, normal, roughness, height, AO, Quixel/Substance-style layers, stochastic shaders, and texel density.",
    "mesh_blender": "Use `mesh_blender` callables for Blender/DCC bridge work: mesh creation, named attributes, GLB import safety, viewport/scene readback, Geometry Nodes-style recipes, and screenshot proof.",
    "pathing_roads": "Use `pathing_roads` callables for roads, paths, navmesh, A*, bridges, fords, splines, cost fields, and traversal constraints.",
    "external_ai_assets": "Use `external_ai_assets` callables for provider-neutral generated model assets, Rodin-style async asset packages, validation, ingestion, scale, UV, PBR, collision, LOD, and license checks.",
    "export_runtime": "Use `export_runtime` callables for Unity/engine exports, water shader manifests, terrain layers, detail layers, particle emitters, scale factors, and runtime artifact schemas.",
    "validation_qa": "Use `validation_qa` callables for quality gates, visual QA, callable audits, deterministic checks, performance budgets, golden snapshots, scene inspection, and issue reporting.",
    "generic": "Use `generic` callables only for small shared helpers; connect them to a domain contract before they become production terrain behavior.",
}


@dataclass(frozen=True)
class CallableKey:
    file: str
    callable: str

    @property
    def id(self) -> str:
        return f"{self.file}::{self.callable}"

    @property
    def simple_name(self) -> str:
        return self.callable.split(".")[-1]


@dataclass
class GuardrailReport:
    matrix_path: Path
    live_count: int
    matrix_count: int
    missing_rows: list[CallableKey] = field(default_factory=list)
    field_gaps: dict[str, list[str]] = field(default_factory=dict)
    unknown_domains: dict[str, str] = field(default_factory=dict)
    duplicate_names: dict[str, list[CallableKey]] = field(default_factory=dict)
    reviewed_duplicate_names: dict[str, list[CallableKey]] = field(default_factory=dict)
    p0_rows: dict[str, str] = field(default_factory=dict)
    non_a_rows: dict[str, str] = field(default_factory=dict)
    grade_status_blocks: dict[str, str] = field(default_factory=dict)
    verification_blocks: dict[str, int] = field(default_factory=dict)
    duplicate_names_blocking: bool = False
    p0_rows_blocking: bool = False
    non_a_rows_blocking: bool = False
    grade_status_blocking: bool = False
    verification_blocking: bool = False

    @property
    def is_blocking(self) -> bool:
        return bool(
            self.missing_rows
            or self.field_gaps
            or self.unknown_domains
            or (self.duplicate_names_blocking and self.duplicate_names)
            or (self.p0_rows_blocking and self.p0_rows)
            or (self.non_a_rows_blocking and self.non_a_rows)
            or (self.grade_status_blocking and self.grade_status_blocks)
            or (self.verification_blocking and self.verification_blocks)
        )


def latest_matrix_path() -> Path | None:
    out_dir = REPO_ROOT / "output" / "spreadsheet"
    matches = sorted(out_dir.glob(MATRIX_GLOB), key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def load_matrix_rows(matrix_path: Path) -> list[dict[str, str]]:
    with matrix_path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def collect_live_callable_keys() -> list[CallableKey]:
    return [
        CallableKey(callable_def.file, callable_def.qualified_name)
        for callable_def in collect_callables(include_init=True)
    ]


def collect_duplicate_names(callables: Iterable[CallableKey]) -> dict[str, list[CallableKey]]:
    groups: dict[str, list[CallableKey]] = defaultdict(list)
    for key in callables:
        groups[key.simple_name].append(key)
    return {
        name: sorted(keys, key=lambda item: item.id)
        for name, keys in groups.items()
        if len(keys) > 1
    }


def load_duplicate_review(path: Path = DEFAULT_DUPLICATE_REVIEW) -> dict[str, set[str]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("reviewed_duplicate_groups") or {}
    out: dict[str, set[str]] = {}
    for name, data in groups.items():
        entries = data.get("callables") if isinstance(data, dict) else data
        out[str(name)] = {str(item) for item in entries or []}
    return out


def split_reviewed_duplicate_names(
    duplicate_names: dict[str, list[CallableKey]],
    review: dict[str, set[str]] | None = None,
) -> tuple[dict[str, list[CallableKey]], dict[str, list[CallableKey]]]:
    review = review if review is not None else load_duplicate_review()
    unreviewed: dict[str, list[CallableKey]] = {}
    reviewed: dict[str, list[CallableKey]] = {}
    for name, keys in duplicate_names.items():
        reviewed_ids = review.get(name, set())
        key_ids = {key.id for key in keys}
        if reviewed_ids and key_ids.issubset(reviewed_ids):
            reviewed[name] = keys
        else:
            unreviewed[name] = keys
    return unreviewed, reviewed


def validate_matrix_against_callables(
    matrix_path: Path,
    live_callables: Iterable[CallableKey] | None = None,
    *,
    block_duplicates: bool = False,
    block_p0: bool = False,
    require_a_grade: bool = False,
    block_grade_status: bool = False,
    block_verification: bool = False,
) -> GuardrailReport:
    rows = load_matrix_rows(matrix_path)
    live = list(live_callables) if live_callables is not None else collect_live_callable_keys()
    matrix_by_key = {
        CallableKey(row.get("file", "").strip(), row.get("callable", "").strip()): row
        for row in rows
    }

    missing_rows = [key for key in live if key not in matrix_by_key]

    field_gaps: dict[str, list[str]] = {}
    unknown_domains: dict[str, str] = {}
    p0_rows: dict[str, str] = {}
    non_a_rows: dict[str, str] = {}
    grade_status_blocks: dict[str, str] = {}
    for key, row in matrix_by_key.items():
        gaps = [field for field in REQUIRED_MATRIX_FIELDS if not (row.get(field) or "").strip()]
        if gaps:
            field_gaps[key.id] = gaps

        domain = (row.get("domain") or "").strip()
        if domain not in DOMAIN_PURPOSE:
            unknown_domains[key.id] = domain

        upgrade_tier = (row.get("upgrade_tier") or "").strip()
        if upgrade_tier in BLOCKING_UPGRADE_TIERS:
            p0_rows[key.id] = upgrade_tier

        grade_status = (row.get("grade_status") or "").strip()
        if grade_status in BLOCKING_GRADE_STATUSES:
            grade_status_blocks[key.id] = grade_status

        grade = (row.get("current_grade") or "").strip()
        verification_risk = (row.get("verification_risk_level") or "").strip().upper()
        if verification_risk != "LOW" and grade not in AAA_GRADE_TOKENS:
            non_a_rows[key.id] = grade or "(blank)"

    verification_blocks = load_verification_blocks() if block_verification else {}

    duplicates_all = collect_duplicate_names(live)
    unreviewed_duplicates, reviewed_duplicates = split_reviewed_duplicate_names(duplicates_all)

    return GuardrailReport(
        matrix_path=matrix_path,
        live_count=len(live),
        matrix_count=len(rows),
        missing_rows=missing_rows,
        field_gaps=field_gaps,
        unknown_domains=unknown_domains,
        duplicate_names=unreviewed_duplicates,
        reviewed_duplicate_names=reviewed_duplicates,
        p0_rows=p0_rows,
        non_a_rows=non_a_rows,
        grade_status_blocks=grade_status_blocks,
        verification_blocks=verification_blocks,
        duplicate_names_blocking=block_duplicates,
        p0_rows_blocking=block_p0,
        non_a_rows_blocking=require_a_grade,
        grade_status_blocking=block_grade_status,
        verification_blocking=block_verification,
    )


def load_verification_blocks(path: Path = CALLABLE_VERIFICATION_SUMMARY_JSON) -> dict[str, int]:
    if not path.exists():
        return {"verification_summary_missing": 1}
    payload = json.loads(path.read_text(encoding="utf-8"))
    risk_counts = payload.get("risk_counts") or {}
    blockers = int(risk_counts.get("BLOCKER") or 0)
    high = int(risk_counts.get("HIGH") or 0)
    false_grade_count = int(payload.get("false_grade_count") or 0)
    out: dict[str, int] = {}
    if blockers:
        out["verification_blockers"] = blockers
    if high:
        out["verification_high"] = high
    if false_grade_count:
        out["false_a_grade_rows"] = false_grade_count
    return out


def build_usage_guide(
    rows: list[dict[str, str]],
    duplicate_names: dict[str, list[CallableKey]],
    *,
    matrix_path: Path | None = None,
) -> str:
    domain_counts: dict[str, int] = defaultdict(int)
    p0_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        domain = (row.get("domain") or "unknown").strip()
        domain_counts[domain] += 1
        if (row.get("upgrade_tier") or "").strip() == "P0":
            p0_counts[domain] += 1

    lines = [
        "# Terrain Callable Usage Guardrail",
        "",
        "This guide is generated from the industry best-practice callable matrix.",
        "Use it before editing or invoking terrain generation code.",
        "",
        "## Required Rule",
        "",
        "Every callable used for terrain generation must satisfy its matrix row: best-practice contract, setup, upgrade actions, validation gates, anti-pattern blockers, and output artifacts.",
        "",
        "## Domain Routing",
        "",
    ]

    for domain in sorted(DOMAIN_PURPOSE):
        count = domain_counts.get(domain, 0)
        p0_count = p0_counts.get(domain, 0)
        lines.append(f"- {DOMAIN_PURPOSE[domain]} Matrix rows: {count}. P0 blockers: {p0_count}.")

    lines.extend(
        [
            "",
            "## Hard Blocks",
            "",
            "- Do not add one-shot terrain builders that bypass canonical passes.",
            "- Do not use flat color or slope-only texturing for production terrain.",
            "- Do not scatter foliage or props without a typed point table and asset manifest.",
            "- Do not create water bodies without surface elevation, depth, flow, and export metadata.",
            "- Do not use raw Blender Python as the normal production path when a typed terrain recipe should exist.",
            "- Do not let external AI asset providers place assets directly into terrain without validation.",
            "",
            "## Duplicate callable names requiring review",
            "",
        ]
    )

    if not duplicate_names:
        lines.append("No duplicate callable names detected.")
    else:
        for name in sorted(duplicate_names):
            keys = duplicate_names[name]
            locations = ", ".join(key.id for key in keys[:8])
            suffix = "" if len(keys) <= 8 else f", ... +{len(keys) - 8} more"
            lines.append(f"- `{name}`: {locations}{suffix}")

    lines.extend(
        [
            "",
            "## Matrix",
            "",
            "Full callable-by-callable rules live in "
            f"`{matrix_path or 'output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_YYYY_MM_DD.csv'}`.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_report_markdown(report: GuardrailReport) -> str:
    lines = [
        "# Terrain Best-Practice Guardrail Report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Matrix: `{report.matrix_path}`",
        f"- Live callables: {report.live_count}",
        f"- Matrix rows: {report.matrix_count}",
        f"- Blocking: {str(report.is_blocking).lower()}",
        f"- Missing rows: {len(report.missing_rows)}",
        f"- Rows with required-field gaps: {len(report.field_gaps)}",
        f"- Rows with unknown domains: {len(report.unknown_domains)}",
        f"- Duplicate callable-name groups: {len(report.duplicate_names)}",
        f"- Reviewed duplicate callable-name groups: {len(report.reviewed_duplicate_names)}",
        f"- P0 upgrade rows: {len(report.p0_rows)}",
        f"- Non-A grade rows: {len(report.non_a_rows)}",
        f"- Blocking grade-status rows: {len(report.grade_status_blocks)}",
        f"- Verification blockers: {sum(report.verification_blocks.values())}",
        "",
    ]

    if report.missing_rows:
        lines.extend(["## Missing Matrix Rows", ""])
        for key in report.missing_rows[:200]:
            lines.append(f"- `{key.id}`")
        if len(report.missing_rows) > 200:
            lines.append(f"- ... +{len(report.missing_rows) - 200} more")
        lines.append("")

    if report.field_gaps:
        lines.extend(["## Required Field Gaps", ""])
        for row_id, gaps in sorted(report.field_gaps.items())[:200]:
            lines.append(f"- `{row_id}`: {', '.join(gaps)}")
        if len(report.field_gaps) > 200:
            lines.append(f"- ... +{len(report.field_gaps) - 200} more")
        lines.append("")

    if report.unknown_domains:
        lines.extend(["## Unknown Domains", ""])
        for row_id, domain in sorted(report.unknown_domains.items())[:200]:
            lines.append(f"- `{row_id}`: `{domain}`")
        lines.append("")

    if report.p0_rows:
        lines.extend(["## P0 Upgrade Rows", ""])
        for row_id, tier in sorted(report.p0_rows.items())[:200]:
            lines.append(f"- `{row_id}`: `{tier}`")
        if len(report.p0_rows) > 200:
            lines.append(f"- ... +{len(report.p0_rows) - 200} more")
        lines.append("")

    if report.grade_status_blocks:
        lines.extend(["## Blocking Grade Status Rows", ""])
        for row_id, status in sorted(report.grade_status_blocks.items())[:200]:
            lines.append(f"- `{row_id}`: `{status}`")
        if len(report.grade_status_blocks) > 200:
            lines.append(f"- ... +{len(report.grade_status_blocks) - 200} more")
        lines.append("")

    if report.non_a_rows:
        lines.extend(["## Non-A Grade Rows", ""])
        for row_id, grade in sorted(report.non_a_rows.items())[:200]:
            lines.append(f"- `{row_id}`: `{grade}`")
        if len(report.non_a_rows) > 200:
            lines.append(f"- ... +{len(report.non_a_rows) - 200} more")
        lines.append("")

    if report.verification_blocks:
        lines.extend(["## Verification Blocks", ""])
        for code, count in sorted(report.verification_blocks.items()):
            lines.append(f"- `{code}`: {count}")
        lines.append("")

    lines.extend(["## Duplicate Callable Names", ""])
    if not report.duplicate_names:
        lines.append("No duplicate callable-name groups detected.")
    else:
        for name, keys in sorted(report.duplicate_names.items())[:200]:
            locations = ", ".join(key.id for key in keys[:8])
            suffix = "" if len(keys) <= 8 else f", ... +{len(keys) - 8} more"
            lines.append(f"- `{name}`: {locations}{suffix}")
    return "\n".join(lines) + "\n"


def write_outputs(report: GuardrailReport, rows: list[dict[str, str]]) -> None:
    DEFAULT_REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_USAGE_GUIDE.parent.mkdir(parents=True, exist_ok=True)

    DEFAULT_REPORT_MD.write_text(build_report_markdown(report), encoding="utf-8")
    DEFAULT_USAGE_GUIDE.write_text(
        build_usage_guide(rows, report.duplicate_names, matrix_path=report.matrix_path),
        encoding="utf-8",
    )
    DEFAULT_REPORT_JSON.write_text(
        json.dumps(
            {
                "matrix_path": str(report.matrix_path),
                "live_count": report.live_count,
                "matrix_count": report.matrix_count,
                "is_blocking": report.is_blocking,
                "missing_rows": [key.id for key in report.missing_rows],
                "field_gaps": report.field_gaps,
                "unknown_domains": report.unknown_domains,
                "p0_rows": report.p0_rows,
                "non_a_rows": report.non_a_rows,
                "grade_status_blocks": report.grade_status_blocks,
                "verification_blocks": report.verification_blocks,
                "strict_modes": {
                    "duplicate_names_blocking": report.duplicate_names_blocking,
                    "p0_rows_blocking": report.p0_rows_blocking,
                    "non_a_rows_blocking": report.non_a_rows_blocking,
                    "grade_status_blocking": report.grade_status_blocking,
                    "verification_blocking": report.verification_blocking,
                },
                "duplicate_names": {
                    name: [key.id for key in keys]
                    for name, keys in report.duplicate_names.items()
                },
                "reviewed_duplicate_names": {
                    name: [key.id for key in keys]
                    for name, keys in report.reviewed_duplicate_names.items()
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=None, help="Matrix CSV to validate. Defaults to newest generated matrix.")
    parser.add_argument("--no-write", action="store_true", help="Do not write report/usage guide artifacts.")
    parser.add_argument("--strict-duplicates", action="store_true", help="Treat duplicate callable names as blockers.")
    parser.add_argument("--strict-p0", action="store_true", help="Treat P0 upgrade rows as blockers.")
    parser.add_argument("--strict-grade-status", action="store_true", help="Treat missing, ambiguous, and name-only grade rows as blockers.")
    parser.add_argument("--strict-verification", action="store_true", help="Treat callable verification matrix blocker/high/false-A rows as blockers.")
    parser.add_argument("--require-a-grade", action="store_true", help="Treat any non-A/A-/A+ current grade as a blocker.")
    parser.add_argument(
        "--strict-aaa",
        action="store_true",
        help="Enable all strict AAA readiness checks: duplicates, P0 rows, grade status, and A-grade requirement.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    matrix_path = args.matrix or latest_matrix_path()
    if matrix_path is None:
        raise SystemExit(
            "No industry best-practice matrix found. Run "
            "`python scripts\\build_industry_best_practice_callable_matrix.py` first."
        )

    rows = load_matrix_rows(matrix_path)
    strict_aaa = args.strict_aaa
    report = validate_matrix_against_callables(
        matrix_path,
        block_duplicates=args.strict_duplicates or strict_aaa,
        block_p0=args.strict_p0 or strict_aaa,
        block_grade_status=args.strict_grade_status or strict_aaa,
        require_a_grade=args.require_a_grade or strict_aaa,
        block_verification=args.strict_verification or strict_aaa,
    )
    if not args.no_write:
        write_outputs(report, rows)

    print(f"Terrain best-practice guardrail: {report.live_count} live callables, {report.matrix_count} matrix rows")
    print(f"  missing rows        : {len(report.missing_rows)}")
    print(f"  required field gaps : {len(report.field_gaps)}")
    print(f"  unknown domains     : {len(report.unknown_domains)}")
    print(f"  duplicate groups    : {len(report.duplicate_names)}")
    print(f"  P0 rows             : {len(report.p0_rows)}")
    print(f"  grade status blocks : {len(report.grade_status_blocks)}")
    print(f"  non-A rows          : {len(report.non_a_rows)}")
    print(f"  verification blocks : {sum(report.verification_blocks.values())}")
    print(f"  blocking            : {report.is_blocking}")
    if not args.no_write:
        print(f"  report              : {DEFAULT_REPORT_MD}")
        print(f"  usage guide         : {DEFAULT_USAGE_GUIDE}")

    return 1 if report.is_blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
