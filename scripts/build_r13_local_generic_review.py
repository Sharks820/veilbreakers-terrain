"""Build the local manual R13 review rows for generic script/other batches."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BATCH_DIR = ROOT / "docs" / "aaa-audit" / "manual_review_batches"
OUT_CSV = ROOT / "docs" / "aaa-audit" / "R13_LOCAL_MANUAL_REVIEW_GENERIC_SCRIPT_OTHER.csv"
OUT_MD = ROOT / "docs" / "aaa-audit" / "R13_LOCAL_MANUAL_REVIEW_GENERIC_SCRIPT_OTHER.md"
BATCHES = [
    "R13_batch_generic_script_01.csv",
    "R13_batch_generic_script_02.csv",
    "R13_batch_generic_other_01.csv",
    "R13_batch_generic_other_02.csv",
]


SCRIPT_CI_TOOLS = {
    "scripts/audit_test_guardrails.py",
    "scripts/build_master_callable_audit.py",
    "scripts/scan_callable_wiring.py",
    "scripts/generate_strict_grade_audit.py",
    "scripts/build_verification_matrix.py",
    "scripts/build_r11_research_aaa_callable_audit.py",
    "scripts/build_r12_strict_aaa_generator_audit.py",
    "scripts/build_r13_manual_review_batches.py",
    "scripts/grade_audit_shared.py",
}

SCENE_BUILD_TOOLS = {
    "scripts/build_aaa_node_v1.py",
    "scripts/build_scene_v3.py",
    "scripts/phase_l_triple_judge.py",
}


def read_batches() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for batch in BATCHES:
        with (BATCH_DIR / batch).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                row["R13 Batch"] = batch
                rows.append(row)
    return rows


def classify(row: dict[str, str]) -> dict[str, str]:
    file_path = row["File"]
    qname = row["Qualified Name"]

    if file_path == "veilbreakers_terrain/procedural_meshes.py":
        if qname.startswith("_"):
            grade = "D+"
            action = "RELOCATE_OR_ADD_HELPER_CONTRACT_TESTS"
            gap = (
                "Private MeshSpec helper in a 22k-line prop library; no per-helper "
                "terrain runtime wiring row or direct visual/contract proof."
            )
        else:
            grade = "C"
            action = "RELOCATE_ASSET_LIBRARY_OR_PROVE_SCATTER_RENDER_PATH"
            gap = (
                "Pure prop MeshSpec generator, not a terrain generator. Some outputs "
                "are reachable through _mesh_bridge maps, but no row-level terrain "
                "placement, LOD, material, or screenshot proof exists."
            )
        return {
            "R13 Manual Grade": grade,
            "R13 Manual Action": action,
            "R13 Evidence": (
                "Manual code read: procedural_meshes.py is imported by "
                "handlers/_mesh_bridge.py and then used by scatter/prop maps, while "
                "repo docs already mark it as non-terrain scope contamination. Prior "
                "deep-dive notes also list shape/UV/topology bugs in this library."
            ),
            "R13 Best Practice Gap": gap,
        }

    if file_path == "veilbreakers_terrain/src/veilbreakers_mcp/blender_server.py":
        return {
            "R13 Manual Grade": "C+",
            "R13 Manual Action": "ADD_DISPATCH_TABLE_COVERAGE_GATE",
            "R13 Evidence": (
                "Manual code read: bpy-free MCP shim maps human location/action keys "
                "to COMMAND_HANDLERS and returns structured errors. It is useful wiring "
                "but B requires a CI gate proving every mapped command exists and every "
                "core generator is reachable."
            ),
            "R13 Best Practice Gap": (
                "AAA tooling needs verified command-surface contracts and stale-key "
                "prevention; the static map alone does not prove terrain quality."
            ),
        }

    if file_path == "scripts/tripo_batch_generate.py":
        return {
            "R13 Manual Grade": "C",
            "R13 Manual Action": "DEFER_TRIPO_OWNER_ADD_CLI_AND_LEDGER_TESTS",
            "R13 Evidence": (
                "Manual code read: Tripo batch driver is documented, journaled, "
                "rate-limited, and external-service oriented. User stated Tripo is "
                "being finished separately, so this row is reviewed but not remediated "
                "inside this pass."
            ),
            "R13 Best Practice Gap": (
                "Before B: hermetic CLI tests for plan/resume/retry/cost caps plus "
                "ingest golden checks against the foliage catalog."
            ),
        }

    if file_path in SCENE_BUILD_TOOLS:
        return {
            "R13 Manual Grade": "C",
            "R13 Manual Action": "ADD_LIVE_BLENDER_GOLDEN_ARTIFACTS",
            "R13 Evidence": (
                "Manual script classification: scene/node build tooling can produce "
                "assets, but the callable row has no live Blender golden screenshot "
                "or node-graph regression proof attached."
            ),
            "R13 Best Practice Gap": (
                "B requires deterministic scene artifacts, camera captures, and "
                "node-graph diff checks tied to CI or a reproducible validation run."
            ),
        }

    if file_path in SCRIPT_CI_TOOLS or file_path.startswith("scripts/"):
        return {
            "R13 Manual Grade": "C",
            "R13 Manual Action": "KEEP_AS_TOOLING_ADD_CI_GATE_OR_DEPRECATE",
            "R13 Evidence": (
                "Manual script classification: audit/build helper, not runtime terrain "
                "generation. These callables should be graded as tooling unless wired "
                "into a required verification command."
            ),
            "R13 Best Practice Gap": (
                "B requires a maintained CI/runbook entry, deterministic output schema, "
                "and tests for stale audit rows or command failure modes."
            ),
        }

    return {
        "R13 Manual Grade": "D+",
        "R13 Manual Action": "MANUAL_REVIEW_UNCLASSIFIED_BEFORE_UPGRADE",
        "R13 Evidence": "Row was in generic local batch but did not match a reviewed file class.",
        "R13 Best Practice Gap": "Needs direct file read, caller proof, and tests before any upgrade.",
    }


def main() -> None:
    rows = read_batches()
    out_rows: list[dict[str, str]] = []
    for row in rows:
        manual = classify(row)
        out_rows.append({
            "File": row["File"],
            "Qualified Name": row["Qualified Name"],
            "Function": row["Function"],
            "Line": row["Line"],
            "Kind": row["Kind"],
            "Scope": row["Scope"],
            "R13 Batch": row["R13 Batch"],
            "R12 Domain": row["R12 Domain"],
            "R12 Strict Grade": row["R12 Strict Grade"],
            "R12 Remediation": row["R12 Remediation"],
            "Wiring Status": row["Wiring Status"],
            **manual,
            "R13 Reviewer": "Codex local manual review",
        })

    fieldnames = list(out_rows[0].keys()) if out_rows else []
    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    by_grade = Counter(row["R13 Manual Grade"] for row in out_rows)
    by_action = Counter(row["R13 Manual Action"] for row in out_rows)
    by_file = Counter(row["File"] for row in out_rows)
    lines = [
        "# R13 Local Manual Review - Generic Script/Other",
        "",
        "This is the local row-level manual review for the four generic script/other batches.",
        "It does not promote rows to B without direct runtime, test, and visual proof.",
        "",
        f"- Rows reviewed: {len(out_rows)}",
        f"- Source batches: {', '.join(BATCHES)}",
        "",
        "## Manual Grades",
    ]
    for grade, count in sorted(by_grade.items()):
        lines.append(f"- {grade}: {count}")
    lines.extend(["", "## Actions"])
    for action, count in by_action.most_common():
        lines.append(f"- {action}: {count}")
    lines.extend(["", "## Largest Files"])
    for file_path, count in by_file.most_common(12):
        lines.append(f"- {file_path}: {count}")
    lines.extend([
        "",
        "## Manual Conclusion",
        "",
        "The generic script/other batch remains below B. The dominant runtime_other block is "
        "`veilbreakers_terrain/procedural_meshes.py`, a pure MeshSpec prop/asset library. "
        "It is reachable through `_mesh_bridge.py` for some scatter/prop paths, but that is "
        "not the same as verified AAA terrain generation. The correct remediation is to "
        "relocate/scope-exempt the non-terrain library or add explicit MeshSpec contract, "
        "LOD/material, scatter placement, and visual golden tests for the reachable subset.",
    ])
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_CSV.relative_to(ROOT)} ({len(out_rows)} rows)")
    print(f"wrote {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
