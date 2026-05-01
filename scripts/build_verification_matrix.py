"""Build a callable verification matrix from grades, tests, and live-risk signals.

This is intentionally stricter than the grade census. A callable can have an
"A" row in GRADES_VERIFIED.csv and still be unverified here if there is no
executable evidence tied to it. The output is meant to drive live-readiness work:
tests, Blender/tool smoke probes, visual QA, material/texture validation, and
camera/readability checks.

Exit behaviour
--------------
* By default the script exits non-zero when any row carries a
  ``FalseGradeFlag=True`` (an A-or-better claim with zero executable evidence)
  or when any row is flagged ``BLOCKER`` / ``HIGH`` risk.
* ``--advisory`` downgrades all of that to reporting-only (exit 0 on any result)
  so maintainers can inspect drift without breaking CI during remediation.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from grade_audit_shared import (  # noqa: E402 - path fixed above
    DEFAULT_GRADE_FILE,
    REPO_ROOT,
    build_grade_index,
    collect_callables,
    latest_grade,
    read_grade_rows,
    resolve_grade_match,
)


TEST_DIR = REPO_ROOT / "veilbreakers_terrain" / "tests"
HANDLERS_DIR = REPO_ROOT / "veilbreakers_terrain" / "handlers"
OUTPUT_DIR = REPO_ROOT / "output" / "verification"
CSV_OUT = OUTPUT_DIR / "CALLABLE_VERIFICATION_MATRIX.csv"
SUMMARY_OUT = OUTPUT_DIR / "CALLABLE_VERIFICATION_SUMMARY.md"
JSON_OUT = OUTPUT_DIR / "CALLABLE_VERIFICATION_SUMMARY.json"
WIRING_CSV = REPO_ROOT / "output" / "spreadsheet" / "CALLABLE_WIRING_AUDIT_2026_04_19.csv"
TRUE_WIRING_RISK_STATUSES = {"orphan_candidate", "uninvoked_registrar", "registrar_declared_only"}


DOMAIN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("blender_tool", ("handle_", "bpy", "bmesh", "mathutils", "blender")),
    ("visual_qa", ("visual", "screenshot", "thumbnail", "render", "diff", "saliency")),
    ("camera_readability", ("camera", "viewport", "framing", "focal", "silhouette", "readability")),
    ("materials_texturing", ("material", "texture", "splat", "shader", "quixel", "decal", "albedo", "roughness")),
    ("water", ("water", "river", "lake", "flow", "foam", "mist", "hydro", "waterfall")),
    ("geometry_mesh", ("mesh", "lod", "navmesh", "cliff", "cave", "karst", "strata", "height", "slope")),
    ("scatter_ecology", ("scatter", "vegetation", "tree", "wildlife", "biome", "ecotone")),
    ("pipeline_wiring", ("pass_", "register_", "pipeline", "dag", "contract", "checkpoint")),
)


EVIDENCE_WEIGHTS = {
    "direct_test": 4,
    "module_test": 2,
    "live_probe": 3,
    "grade_a_or_better": 1,
}


@dataclass(frozen=True)
class TestIndex:
    tests_by_text: dict[str, set[str]]
    module_test_files: dict[str, set[str]]
    live_probe_files: set[str]


class ImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imported_modules: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.imported_modules.add(alias.name.rsplit(".", 1)[-1])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module:
            self.imported_modules.add(node.module.rsplit(".", 1)[-1])
        for alias in node.names:
            self.imported_modules.add(alias.name)


def _test_files() -> list[Path]:
    return sorted(TEST_DIR.rglob("test_*.py"))


def _build_test_index() -> TestIndex:
    tests_by_text: dict[str, set[str]] = defaultdict(set)
    module_test_files: dict[str, set[str]] = defaultdict(set)
    live_probe_files: set[str] = set()

    for test_path in _test_files():
        rel = test_path.relative_to(REPO_ROOT).as_posix()
        text = test_path.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        if any(token in lowered for token in ("live", "blender", "bpy", "visual", "screenshot", "viewport")):
            live_probe_files.add(rel)

        tree = ast.parse(text, filename=str(test_path))
        imports = ImportVisitor()
        imports.visit(tree)
        for imported in imports.imported_modules:
            module_test_files[imported].add(rel)

        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                tests_by_text[node.id].add(rel)
            elif isinstance(node, ast.Attribute):
                tests_by_text[node.attr].add(rel)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                if value:
                    tests_by_text[value].add(rel)

    return TestIndex(
        tests_by_text={key: set(files) for key, files in tests_by_text.items()},
        module_test_files={key: set(files) for key, files in module_test_files.items()},
        live_probe_files=live_probe_files,
    )


def _source_for(file_name: str) -> str:
    path = HANDLERS_DIR / file_name
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _domain_tags(file_name: str, qualified_name: str, source: str) -> list[str]:
    haystack = f"{file_name} {qualified_name} {source[:2000]}".lower()
    tags = [
        domain
        for domain, needles in DOMAIN_KEYWORDS
        if any(needle in haystack for needle in needles)
    ]
    return tags or ["core"]


def _cap(files: Iterable[str], limit: int = 8) -> str:
    unique = sorted(set(files))
    if len(unique) <= limit:
        return ";".join(unique)
    return ";".join(unique[:limit]) + f";...(+{len(unique) - limit})"


def _load_wiring_index(path: Path = WIRING_CSV) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        file_name = (row.get("file") or "").strip()
        qualified_name = (row.get("qualified_name") or "").strip()
        simple_name = (row.get("function") or "").strip()
        if file_name and qualified_name:
            index[(file_name, qualified_name)] = row
        if file_name and simple_name:
            index.setdefault((file_name, simple_name), row)
    return index


def _evidence_for(
    file_name: str,
    simple_name: str,
    qualified_name: str,
    test_index: TestIndex,
) -> tuple[list[str], set[str], int]:
    module = file_name.removesuffix(".py")
    evidence: list[str] = []
    files: set[str] = set()
    score = 0

    direct_files = set()
    direct_files.update(test_index.tests_by_text.get(simple_name, set()))
    direct_files.update(test_index.tests_by_text.get(qualified_name, set()))
    if direct_files:
        evidence.append("direct_test")
        files.update(direct_files)
        score += EVIDENCE_WEIGHTS["direct_test"]

    module_files = test_index.module_test_files.get(module, set())
    if module_files:
        evidence.append("module_test")
        files.update(module_files)
        score += EVIDENCE_WEIGHTS["module_test"]

    live_files = files.intersection(test_index.live_probe_files)
    if live_files:
        evidence.append("live_probe")
        score += EVIDENCE_WEIGHTS["live_probe"]

    return evidence, files, score


def _risk_level(
    grade: str,
    evidence: list[str],
    evidence_score: int,
    tags: list[str],
    is_tool: bool,
    wiring_status: str,
) -> str:
    live_critical = bool(
        {"blender_tool", "visual_qa", "camera_readability", "materials_texturing", "pipeline_wiring"}.intersection(tags)
    )
    if wiring_status in TRUE_WIRING_RISK_STATUSES:
        return "BLOCKER"
    if not grade:
        return "BLOCKER"
    if evidence_score == 0:
        return "BLOCKER"
    if is_tool and "live_probe" not in evidence and evidence_score < 5:
        return "HIGH"
    if live_critical and evidence_score < 5:
        return "HIGH"
    if evidence_score < 4:
        return "MEDIUM"
    return "LOW"


def _grade_is_a_or_better(grade: str) -> bool:
    return grade in {"A+", "A", "A-", "B+"}


def build_rows() -> list[dict[str, str]]:
    grade_rows = read_grade_rows(DEFAULT_GRADE_FILE)
    grade_index = build_grade_index(grade_rows)
    test_index = _build_test_index()
    wiring_index = _load_wiring_index()
    source_cache: dict[str, str] = {}
    rows: list[dict[str, str]] = []

    for callable_def in collect_callables(include_init=False, tracked_only=False):
        source = source_cache.setdefault(callable_def.file, _source_for(callable_def.file))
        match = resolve_grade_match(callable_def, grade_index)
        grade = latest_grade(match.row) if match.row else ""
        evidence, evidence_files, score = _evidence_for(
            callable_def.file,
            callable_def.simple_name,
            callable_def.qualified_name,
            test_index,
        )
        if _grade_is_a_or_better(grade):
            score += EVIDENCE_WEIGHTS["grade_a_or_better"]
        tags = _domain_tags(callable_def.file, callable_def.qualified_name, source)
        is_tool = callable_def.simple_name.startswith(("handle_", "register_")) or "blender_tool" in tags
        wiring_row = wiring_index.get((callable_def.file, callable_def.qualified_name), {})
        wiring_status = (wiring_row.get("status") or "unknown").strip()
        risk = _risk_level(grade, evidence, score, tags, is_tool, wiring_status)
        false_grade_flag = bool(grade.startswith("A") and not evidence)

        rows.append(
            {
                "File": callable_def.file,
                "Callable": callable_def.qualified_name,
                "SimpleName": callable_def.simple_name,
                "Line": str(callable_def.lineno),
                "Kind": callable_def.kind,
                "Grade": grade,
                "GradeMatchStatus": match.status,
                "GradeMatchMode": match.match_mode,
                "DomainTags": ";".join(tags),
                "IsToolOrBlenderCallable": str(is_tool),
                "WiringStatus": wiring_status,
                "RuntimeExposure": (wiring_row.get("runtime_exposure") or "unknown").strip(),
                "NonTestCallCount": str(
                    int(wiring_row.get("non_test_direct_calls") or 0)
                    + int(wiring_row.get("non_test_attr_calls") or 0)
                    + int(wiring_row.get("non_test_attr_reads") or 0)
                ) if wiring_row else "unknown",
                "EvidenceTypes": ";".join(evidence),
                "EvidenceScore": str(score),
                "EvidenceFiles": _cap(evidence_files),
                "RiskLevel": risk,
                "FalseGradeFlag": str(false_grade_flag),
                "RequiredNextEvidence": _required_next_evidence(tags, evidence, grade, is_tool, wiring_status),
            }
        )

    return rows


def _required_next_evidence(
    tags: list[str],
    evidence: list[str],
    grade: str,
    is_tool: bool,
    wiring_status: str,
) -> str:
    needed: list[str] = []
    if not grade:
        needed.append("grade_rubric_row")
    if wiring_status in TRUE_WIRING_RISK_STATUSES:
        needed.append("production_wiring_or_scope_removal")
    if wiring_status == "direct_test_covered":
        needed.append("production_caller_or_scope_exemption")
    if "direct_test" not in evidence:
        needed.append("direct_behavior_test")
    if is_tool and "live_probe" not in evidence:
        needed.append("blender_or_mcp_tool_smoke")
    if "visual_qa" in tags and "live_probe" not in evidence:
        needed.append("visual_snapshot_or_metric")
    if "materials_texturing" in tags and "direct_test" not in evidence:
        needed.append("material_texture_contract_test")
    if "camera_readability" in tags and "direct_test" not in evidence:
        needed.append("camera_readability_probe")
    return ";".join(dict.fromkeys(needed))


def write_outputs(rows: list[dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with CSV_OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    risk_counts = Counter(row["RiskLevel"] for row in rows)
    tag_counts = Counter(tag for row in rows for tag in row["DomainTags"].split(";"))
    wiring_counts = Counter(row["WiringStatus"] for row in rows)
    false_grade_count = sum(1 for row in rows if row["FalseGradeFlag"] == "True")
    direct_test_only_a = sum(
        1
        for row in rows
        if row["WiringStatus"] == "direct_test_covered" and row["Grade"].startswith("A")
    )
    tool_blockers = [
        row for row in rows
        if row["IsToolOrBlenderCallable"] == "True" and row["RiskLevel"] in {"BLOCKER", "HIGH"}
    ]
    high_risk = [row for row in rows if row["RiskLevel"] in {"BLOCKER", "HIGH"}]

    payload = {
        "total_callables": len(rows),
        "risk_counts": dict(risk_counts),
        "domain_counts": dict(tag_counts),
        "wiring_status_counts": dict(wiring_counts),
        "false_grade_count": false_grade_count,
        "direct_test_only_a_grade_count": direct_test_only_a,
        "tool_blocker_count": len(tool_blockers),
        "csv": CSV_OUT.as_posix(),
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Callable Verification Summary",
        "",
        "This report treats grade rows as claims, not proof. A callable needs executable evidence.",
        "",
        f"- Total callables: {len(rows)}",
        f"- Blockers: {risk_counts.get('BLOCKER', 0)}",
        f"- High risk: {risk_counts.get('HIGH', 0)}",
        f"- Medium risk: {risk_counts.get('MEDIUM', 0)}",
        f"- Low risk: {risk_counts.get('LOW', 0)}",
        f"- A-grade rows with no executable evidence: {false_grade_count}",
        f"- A-grade rows with tests but no production caller/runtime exposure: {direct_test_only_a}",
        f"- Tool/Blender callables needing blocker/high evidence: {len(tool_blockers)}",
        f"- Wiring status counts: {dict(sorted(wiring_counts.items()))}",
        "",
        "## Highest Risk Files",
        "",
    ]
    by_file = Counter(row["File"] for row in high_risk)
    for file_name, count in by_file.most_common(25):
        lines.append(f"- {file_name}: {count}")

    lines.extend(["", "## Top Blocker/High Callables", ""])
    for row in high_risk[:80]:
        lines.append(
            f"- {row['RiskLevel']} {row['File']}:{row['Line']} "
            f"{row['Callable']} grade={row['Grade'] or 'NONE'} "
            f"needs={row['RequiredNextEvidence'] or 'review'}"
        )

    lines.extend(["", f"Full CSV: `{CSV_OUT.relative_to(REPO_ROOT).as_posix()}`", ""])
    SUMMARY_OUT.write_text("\n".join(lines), encoding="utf-8")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build callable verification matrix")
    parser.add_argument(
        "--advisory",
        action="store_true",
        help=(
            "Report-only mode: always exit 0 regardless of false-grade or risk "
            "findings. Useful while the backlog is being worked down; CI should "
            "leave this off so the signal is enforceable."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    rows = build_rows()
    write_outputs(rows)

    blockers = sum(1 for row in rows if row["RiskLevel"] == "BLOCKER")
    high = sum(1 for row in rows if row["RiskLevel"] == "HIGH")
    false_grade_count = sum(1 for row in rows if row["FalseGradeFlag"] == "True")

    print(f"wrote {CSV_OUT}")
    print(f"wrote {SUMMARY_OUT}")
    print(f"verification risk: {blockers} blocker, {high} high")
    print(f"false_grade_A_rows: {false_grade_count}")

    if args.advisory:
        if false_grade_count or blockers or high:
            print("advisory mode: findings present but not enforced (exit 0)")
        return 0

    if false_grade_count > 0:
        print(
            f"ENFORCEMENT: {false_grade_count} A-grade rows lack executable "
            "evidence. Pass --advisory to downgrade to reporting-only."
        )
        return 1
    if blockers or high:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
