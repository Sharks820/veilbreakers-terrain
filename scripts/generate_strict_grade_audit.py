"""Generate a stricter, evidence-backed grade audit for GRADES_VERIFIED.csv.

This script does not overwrite the historical sheet. It emits a new CSV and a
summary report under ``output/spreadsheet/`` with row-by-row current scores,
evidence flags, and a concrete AAA verification path.
"""

from __future__ import annotations

import ast
import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "docs" / "aaa-audit" / "GRADES_VERIFIED.csv"
RUBRIC_PATH = REPO_ROOT / "docs" / "aaa-audit" / "STRICT_AUDIT_RUBRIC.json"
OUTPUT_DIR = REPO_ROOT / "output" / "spreadsheet"
DATE_TAG = "2026_04_19"
OUTPUT_CSV = OUTPUT_DIR / f"GRADES_STRICT_{DATE_TAG}.csv"
OUTPUT_SUMMARY = OUTPUT_DIR / f"STRICT_AUDIT_SUMMARY_{DATE_TAG}.md"
HANDLERS_DIR = REPO_ROOT / "veilbreakers_terrain" / "handlers"
TESTS_DIR = REPO_ROOT / "veilbreakers_terrain" / "tests"
LASTFAILED_PATH = REPO_ROOT / ".pytest_cache" / "v" / "cache" / "lastfailed"

IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
IMPORT_RE_TEMPLATE = r"\b(?:from\s+[A-Za-z0-9_\.]+\s+import\s+.*\b{symbol}\b|import\s+.*\b{symbol}\b)"
GRADE_TOKEN_RE = re.compile(r"^(A-|A|B\+|B-|B|C\+|C-|C|D\+|D-|D|F)(?:$|[|:,\s])")

CLAIM_COLUMNS = [
    "R9 Phase7-14 Consensus",
    "R8 Deep Dive Verdict",
    "R7 MCP Verdict",
    "FINAL GRADE",
    "R6 Opus 4.7 wave-2 Grade",
    "R5 Opus 4.7 Grade",
    "R4 Grade",
    "R3 Grade",
    "R2 Verified Grade",
    "R1 Consensus",
]

SURFACE_FILES = {
    "__init__.py",
    "terrain_pipeline.py",
    "terrain_master_registrar.py",
    "_terrain_world.py",
    "terrain_pass_dag.py",
}

RUNTIME_FILES = {
    "__init__.py": "command_surface",
    "terrain_pipeline.py": "default_pipeline",
    "terrain_master_registrar.py": "master_registrar",
    "_terrain_world.py": "world_runtime",
    "terrain_pass_dag.py": "dag_runtime",
}

RISK_KEYWORDS = {
    "stub_or_placeholder": ("stub", "placeholder"),
    "dead_or_shadowed": (
        "dead code",
        "never called",
        "not called",
        "not registered",
        "not wired",
        "no caller",
        "orphan",
        "orphaned",
        "shadowed",
        "legacy only",
    ),
    "contract_gap": (
        "unknown channel",
        "contract mismatch",
        "not in semantics",
        "not supported",
        "api drift",
    ),
    "todo_or_missing": ("todo", "fixme", "missing", "not implemented"),
    "numeric_risk": ("nan", "invalid value", "nondeterministic", "unstable"),
    "manual_claim": ("confirmed", "upgraded", "manual", "ledger", "hand"),
}

# Current live failure map from targeted reruns on 2026-04-19.
DIRECT_FAILURE_FLAGS = {
    ("terrain_checkpoints.py", "save_checkpoint"): ["FAIL_OUTPUT_IO"],
    ("terrain_checkpoints.py", "rollback_last_checkpoint"): ["FAIL_OUTPUT_IO"],
    ("terrain_checkpoints.py", "rollback_to"): ["FAIL_OUTPUT_IO"],
    ("terrain_checkpoints.py", "list_checkpoints"): ["FAIL_OUTPUT_IO"],
    ("terrain_checkpoints.py", "save_preset"): ["FAIL_OUTPUT_IO"],
    ("terrain_checkpoints.py", "restore_preset"): ["FAIL_OUTPUT_IO"],
    ("terrain_checkpoints.py", "autosave_after_pass"): ["FAIL_OUTPUT_IO"],
    ("terrain_chunking.py", "compute_chunk_lod"): ["FAIL_API_DRIFT"],
    ("terrain_horizon_lod.py", "pass_horizon_lod"): ["FAIL_CONTRACT_CHANNEL"],
    ("terrain_caves.py", "pick_cave_archetype"): ["FAIL_DIRECT_BEHAVIOR"],
    ("terrain_caves.py", "carve_cave_volume"): ["FAIL_CONTRACT_CHANNEL", "FAIL_DIRECT_BEHAVIOR"],
    ("terrain_caves.py", "pass_caves"): ["FAIL_CONTRACT_CHANNEL", "FAIL_DIRECT_BEHAVIOR"],
    ("_water_network.py", "detect_lakes"): ["FAIL_DIRECT_BEHAVIOR"],
    ("terrain_waterfalls.py", "generate_mist_zone"): ["FAIL_DIRECT_BEHAVIOR"],
    ("terrain_waterfalls.py", "pass_waterfalls"): ["FAIL_CONTRACT_CHANNEL", "FAIL_DIRECT_BEHAVIOR"],
    ("terrain_water_variants.py", "detect_wetlands"): ["FAIL_DIRECT_BEHAVIOR"],
    ("terrain_banded.py", "_generate_strata_band"): ["FAIL_NUMERIC_STABILITY"],
    ("terrain_banded.py", "_generate_domain_warp_band"): ["FAIL_NUMERIC_STABILITY"],
    ("terrain_banded.py", "compose_banded_heightmap"): ["FAIL_NUMERIC_STABILITY"],
    ("_terrain_noise.py", "generate_heightmap"): ["FAIL_PERF_SEVERE"],
}

MODULE_FAILURE_FLAGS = {
    "terrain_checkpoints.py": ["FAIL_TRANSITIVE_MODULE"],
    "terrain_chunking.py": ["FAIL_TRANSITIVE_MODULE"],
    "terrain_banded.py": ["FAIL_TRANSITIVE_MODULE"],
    "terrain_horizon_lod.py": ["FAIL_TRANSITIVE_MODULE"],
    "terrain_caves.py": ["FAIL_TRANSITIVE_MODULE"],
    "_water_network.py": ["FAIL_TRANSITIVE_MODULE"],
    "_terrain_noise.py": ["FAIL_TRANSITIVE_MODULE"],
    "terrain_waterfalls.py": ["FAIL_TRANSITIVE_MODULE"],
    "terrain_water_variants.py": ["FAIL_TRANSITIVE_MODULE"],
}

DIRECT_FAILURE_NOTES = {
    ("terrain_checkpoints.py", "save_checkpoint"): "Current pytest: checkpoint write opens *.npz.tmp but np.savez_compressed writes *.npz.",
    ("terrain_checkpoints.py", "save_preset"): "Current pytest: preset save fails through the same *.npz.tmp write path.",
    ("terrain_checkpoints.py", "autosave_after_pass"): "Current pytest: autosave does not append a checkpoint because save fails.",
    ("terrain_chunking.py", "compute_chunk_lod"): "Current pytest: API drift; function now returns an int LOD while shipped tests expect a downsampled heightmap.",
    ("terrain_horizon_lod.py", "pass_horizon_lod"): "Current pytest: writes horizon_elevation_angles, but TerrainMaskStack rejects the channel.",
    ("terrain_caves.py", "pick_cave_archetype"): "Current pytest: misclassifies a wet high plateau as karst_sinkhole instead of glacial_melt.",
    ("terrain_caves.py", "carve_cave_volume"): "Agent reruns: cave_wall_texture channel is unsupported and ndarray truthiness crashes remain in cave orchestration.",
    ("terrain_caves.py", "pass_caves"): "Agent reruns: cave_wall_texture channel is unsupported and ndarray truthiness crashes remain in cave orchestration.",
    ("_water_network.py", "detect_lakes"): "Current pytest: emits lake surface_z below member cell elevations, violating physical plausibility.",
    ("terrain_waterfalls.py", "generate_mist_zone"): "Agent reruns: mist-zone peak-at-pool invariant fails on current tree.",
    ("terrain_waterfalls.py", "pass_waterfalls"): "Agent reruns: waterfall_velocity channel is written even though semantics has no such channel.",
    ("terrain_water_variants.py", "detect_wetlands"): "Agent reruns: NameError because math is not imported in the live code path.",
    ("terrain_banded.py", "_generate_strata_band"): "Current pytest: strata directionality and invalid-power warnings show numeric instability.",
    ("terrain_banded.py", "_generate_domain_warp_band"): "Current pytest: warp field centering/finite invariants are not holding.",
    ("terrain_banded.py", "compose_banded_heightmap"): "Current pytest: composition fails linearity and frequency-isolation invariants.",
    ("_terrain_noise.py", "generate_heightmap"): "Current pytest: 256x256 mountains took 13.086s vs <0.5s, and 6x128x128 batch took 32.002s vs <3s.",
}

SPECIFIC_AAA_PATHS = {
    ("terrain_checkpoints.py", "save_checkpoint"): (
        "Fix Windows-safe atomic NPZ write semantics first, then prove save/rollback/preset/autosave round-trips on NTFS "
        "with checksum corruption tests and large-mask latency budgets."
    ),
    ("terrain_checkpoints.py", "save_preset"): (
        "Make preset export use a real temp path strategy, add preset restore fidelity tests for intent/masks, and validate "
        "cross-session reload on Windows and CI runners."
    ),
    ("terrain_checkpoints.py", "autosave_after_pass"): (
        "Make autosave transitively green through the checkpoint path, then add pass-wrapper integration tests and budget guardrails "
        "for autosave frequency under multi-pass terrain runs."
    ),
    ("terrain_chunking.py", "compute_chunk_lod"): (
        "Split LOD selection from heightmap resampling or update all callers/tests to the new contract, then add seam continuity, "
        "boundary-sample parity, and streaming-pop validation against engine playback."
    ),
    ("terrain_horizon_lod.py", "pass_horizon_lod"): (
        "Register horizon_elevation_angles in semantics or route it through supported metadata, then add visibility/readability tests "
        "and verify camera-facing LOD decisions in an engine viewport."
    ),
    ("_water_network.py", "detect_lakes"): (
        "Replace the pit-only lake solve with spill-elevation basin logic, prove every lake cell stays below surface_z with outlet "
        "continuity, then compare masks against Houdini/Gaea basin references and engine water-surface import."
    ),
    ("terrain_caves.py", "pick_cave_archetype"): (
        "Make archetype selection deterministic and climate/elevation faithful, add a scenario matrix for karst/glacial/volcanic cases, "
        "then validate the resulting cave families against shipped art-direction references."
    ),
    ("terrain_banded.py", "compose_banded_heightmap"): (
        "Restore linear weight behavior and frequency isolation, eliminate invalid-power paths, then lock spectral/variance goldens and "
        "compare strata breakup against Houdini/Gaea geological references."
    ),
    ("_terrain_noise.py", "generate_heightmap"): (
        "Profile and vectorize until 256x256 stays below 0.5s and the six-terrain 128x128 batch stays below 3s, then lock spectral, seam, "
        "and erosion-reference goldens against Houdini/Gaea-class terrain outputs."
    ),
    ("terrain_waterfalls.py", "pass_waterfalls"): (
        "Move waterfall outputs onto supported channels, add mist/velocity invariants plus region-boundary tests, then validate imported "
        "waterfall data and readability in Unity/Unreal camera captures."
    ),
}


@dataclass(frozen=True)
class SymbolRecord:
    name: str
    kind: str
    lineno: int
    container_class: str = ""


class SymbolVisitor(ast.NodeVisitor):
    """Collect top-level functions/classes and class methods/properties."""

    def __init__(self) -> None:
        self.records: List[SymbolRecord] = []
        self._class_stack: List[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.records.append(SymbolRecord(node.name, "class", node.lineno, ""))
        self._class_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._add_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._add_function(node)

    def _add_function(self, node: ast.AST) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if node.name.startswith("__") and node.name.endswith("__"):
            return
        container = self._class_stack[-1] if self._class_stack else ""
        kind = "property" if self._is_property(node) else ("method" if container else "function")
        self.records.append(SymbolRecord(node.name, kind, node.lineno, container))
        if not container:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.visit(child)

    @staticmethod
    def _is_property(node: ast.AST) -> bool:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id in {"property", "cached_property"}:
                return True
            if isinstance(decorator, ast.Attribute) and decorator.attr in {"setter", "getter", "deleter"}:
                return True
        return False


def load_rubric() -> dict:
    if RUBRIC_PATH.exists():
        return json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"Rubric JSON not found at {RUBRIC_PATH}")


def load_rows() -> tuple[list[str], list[dict[str, str]]]:
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if None in fieldnames:
        fieldnames.remove(None)
    for row in rows:
        row.pop(None, None)
    return fieldnames, rows


def extract_grade_token(cell: str) -> str:
    raw = (cell or "").strip()
    if not raw:
        return ""
    if raw in {"SCOPE_EXEMPT", "N/A", "N/A (SCOPE)"}:
        return raw
    raw = raw.split("|", 1)[0].strip()
    match = GRADE_TOKEN_RE.match(raw)
    return match.group(1) if match else ""


def score_to_grade(score: float, rubric: dict) -> str:
    for cutoff in rubric["grade_cutoffs"]:
        if score >= float(cutoff["min_score"]):
            return str(cutoff["grade"])
    return "F"


def grade_to_notch(grade: str, rubric: dict) -> int:
    ordered = [item["grade"] for item in rubric["grade_cutoffs"]]
    return ordered.index(grade) if grade in ordered else -1


def safe_int(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def build_symbol_index() -> tuple[dict[str, list[SymbolRecord]], dict[str, Path]]:
    index: dict[str, list[SymbolRecord]] = defaultdict(list)
    file_paths: dict[str, Path] = {}
    for path in sorted(HANDLERS_DIR.glob("*.py")):
        file_paths[path.name] = path
        visitor = SymbolVisitor()
        visitor.visit(ast.parse(read_text(path), filename=str(path)))
        index[path.name].extend(visitor.records)
    return index, file_paths


def build_identifier_stats(
    py_paths: Sequence[Path],
) -> tuple[dict[Path, Counter], Counter, Counter, Counter, Counter, Counter]:
    per_file_counts: dict[Path, Counter] = {}
    test_occurrences: Counter = Counter()
    source_occurrences: Counter = Counter()
    test_file_hits: Counter = Counter()
    source_file_hits: Counter = Counter()
    import_hits: Counter = Counter()
    for path in py_paths:
        text = read_text(path)
        counts = Counter(IDENTIFIER_RE.findall(text))
        per_file_counts[path] = counts
        is_test = "tests" in path.parts
        target_occ = test_occurrences if is_test else source_occurrences
        target_files = test_file_hits if is_test else source_file_hits
        for symbol, count in counts.items():
            target_occ[symbol] += count
            target_files[symbol] += 1
        if is_test:
            for symbol in counts:
                pattern = re.compile(IMPORT_RE_TEMPLATE.format(symbol=re.escape(symbol)))
                if pattern.search(text):
                    import_hits[symbol] += 1
    return per_file_counts, test_occurrences, source_occurrences, test_file_hits, source_file_hits, import_hits


def build_runtime_index(file_paths: dict[str, Path]) -> dict[str, set[str]]:
    runtime_index: dict[str, set[str]] = defaultdict(set)
    pass_def_re = re.compile(r"PassDefinition\([^)]*func\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", re.S)
    register_re = re.compile(
        r'(?:_try_register|COMMAND_HANDLERS\[[^\]]+\]\s*=)\s*\(?\s*"[^"]+"\s*,?\s*([A-Za-z_][A-Za-z0-9_]*)'
    )
    for file_name, path in file_paths.items():
        if file_name not in SURFACE_FILES:
            continue
        text = read_text(path)
        surface_tag = RUNTIME_FILES[file_name]
        for match in IDENTIFIER_RE.finditer(text):
            if file_name == "__init__.py":
                runtime_index[match.group(0)].add("surface_seen")
        if file_name == "__init__.py":
            for match in register_re.finditer(text):
                runtime_index[match.group(1)].add("command_handler")
        for match in pass_def_re.finditer(text):
            if file_name == "terrain_pipeline.py":
                runtime_index[match.group(1)].add("default_pass")
            elif file_name == "terrain_master_registrar.py":
                runtime_index[match.group(1)].add("bundle_pass")
            else:
                runtime_index[match.group(1)].add(surface_tag)
    # Also pick up module-local PassDefinition(func=...) as weaker registrar evidence.
    for file_name, path in file_paths.items():
        text = read_text(path)
        for match in pass_def_re.finditer(text):
            runtime_index[match.group(1)].add("registrar_declared")
    return runtime_index


def load_lastfailed() -> dict[str, bool]:
    if not LASTFAILED_PATH.exists():
        return {}
    return json.loads(LASTFAILED_PATH.read_text(encoding="utf-8"))


def pick_symbol(symbols: Sequence[SymbolRecord], function_name: str, csv_line: Optional[int]) -> Optional[SymbolRecord]:
    candidates = [record for record in symbols if record.name == function_name]
    if not candidates:
        return None
    if csv_line is None:
        return min(candidates, key=lambda record: record.lineno)
    return min(candidates, key=lambda record: abs(record.lineno - csv_line))


def latest_claim(row: dict[str, str], rubric: dict) -> tuple[str, str, float, str]:
    non_gradable = {value for value in rubric["non_gradable_values"] if value}
    for column in CLAIM_COLUMNS:
        raw = (row.get(column) or "").strip()
        token = extract_grade_token(raw)
        if not raw:
            continue
        if token in non_gradable:
            return token, column, 0.0, "NON_GRADABLE"
        if token in rubric["grade_scale"]:
            return token, column, float(rubric["grade_scale"][token]), claim_flag_for_column(column)
    return "", "", 0.0, "NON_GRADABLE"


def claim_flag_for_column(column: str) -> str:
    if column == "R9 Phase7-14 Consensus":
        return "CLAIM_R9"
    if column == "R8 Deep Dive Verdict":
        return "CLAIM_R8"
    if column == "R7 MCP Verdict":
        return "CLAIM_R7"
    if column == "FINAL GRADE":
        return "CLAIM_FINAL_ONLY"
    return "CLAIM_R6_OR_OLDER"


def module_named_test_exists(file_name: str, test_paths: Sequence[Path]) -> bool:
    stem = Path(file_name).stem.lstrip("_")
    target = f"test_{stem}.py"
    return any(path.name == target for path in test_paths)


def classify_test_strength(
    function_name: str,
    file_name: str,
    test_hits: int,
    test_files: int,
    import_hits: int,
    has_direct_failure: bool,
    has_module_named_test: bool,
) -> str:
    if has_direct_failure or import_hits >= 2 or test_files >= 3 or test_hits >= 10:
        return "TEST_STRONG"
    if test_files >= 1 or (has_module_named_test and test_hits >= 1):
        return "TEST_MEDIUM"
    if has_module_named_test or test_hits >= 1:
        return "TEST_WEAK"
    return "TEST_NONE"


def text_flags(row: dict[str, str]) -> set[str]:
    haystack = " ".join(
        str(row.get(column, ""))
        for column in (
            "Dispute Reason",
            "Evidence",
            "Strength",
            "Weakness",
            "Upgrade",
            "R5 Notes",
            "R6 Notes",
            "R7 MCP Verdict",
            "R8 Deep Dive Verdict",
            "R9 Phase7-14 Consensus",
        )
    ).lower()
    flags: set[str] = set()
    for flag, terms in RISK_KEYWORDS.items():
        if any(term in haystack for term in terms):
            flags.add(flag)
    return flags


def classify_pipeline_wiring(
    runtime_tags: set[str],
    external_source_files: int,
    row_text_flags: set[str],
    contract_mismatch: bool,
) -> str:
    if contract_mismatch:
        return "PIPE_CONTRACT_MISMATCH"
    if {"default_pass", "bundle_pass", "command_handler"} & runtime_tags:
        return "PIPE_ACTIVE"
    if "registrar_declared" in runtime_tags or external_source_files >= 2 or "surface_seen" in runtime_tags:
        return "PIPE_PARTIAL"
    if "dead_or_shadowed" in row_text_flags or external_source_files == 0:
        return "PIPE_DEAD_OR_SHADOWED"
    return "PIPE_OPTIONAL"


def classify_public_exposure(function_name: str, runtime_tags: set[str], row_text_flags: set[str]) -> str:
    if "command_handler" in runtime_tags or function_name.startswith("handle_"):
        return "PUBLIC_PRIMARY"
    if "surface_seen" in runtime_tags:
        return "PUBLIC_HELPER_ONLY"
    if "dead_or_shadowed" in row_text_flags:
        return "PUBLIC_LEGACY_ONLY"
    return "PUBLIC_INTERNAL_ONLY"


def collect_failure_flags(file_name: str, function_name: str) -> list[str]:
    flags: list[str] = []
    flags.extend(MODULE_FAILURE_FLAGS.get(file_name, []))
    flags.extend(DIRECT_FAILURE_FLAGS.get((file_name, function_name), []))
    return sorted(set(flags))


def failure_note(file_name: str, function_name: str, lastfailed: dict[str, bool]) -> str:
    direct = DIRECT_FAILURE_NOTES.get((file_name, function_name))
    if direct:
        return direct
    if file_name in MODULE_FAILURE_FLAGS:
        cache_hits = [
            node for node in lastfailed
            if Path(node.split("::", 1)[0]).name.startswith(f"test_{Path(file_name).stem.lstrip('_')}")
        ]
        if cache_hits:
            return f"Current pytest cache still marks {len(cache_hits)} failing node(s) for this module."
        return "Current workspace has live module failures that lower confidence for sibling functions."
    return ""


def apply_caps(score: float, failure_flags: list[str], test_strength: str, pipeline_wiring: str, public_exposure: str, rubric: dict) -> tuple[float, str]:
    cap_grade = ""
    cap_score = score
    for cap_rule in rubric["grade_caps"]:
        matched = False
        if "if_any" in cap_rule:
            matched = any(flag in failure_flags for flag in cap_rule["if_any"])
        elif "if_all" in cap_rule:
            required = set(cap_rule["if_all"])
            matched = required.issubset({test_strength, pipeline_wiring, public_exposure, *failure_flags})
        if matched:
            rule_grade = str(cap_rule["max_grade"])
            rule_score = float(rubric["grade_scale"][rule_grade])
            if not cap_grade or rule_score < cap_score:
                cap_grade = rule_grade
                cap_score = min(cap_score, rule_score)
    return cap_score, cap_grade


def evidence_bucket(
    code_exists: bool,
    runtime_tags: set[str],
    test_strength: str,
    pipeline_wiring: str,
    failure_flags: list[str],
    non_gradable: bool,
) -> str:
    if non_gradable:
        return "scope_exempt"
    if not code_exists:
        return "stale_or_missing"
    if failure_flags and any(flag != "FAIL_TRANSITIVE_MODULE" for flag in failure_flags):
        return "live_partial"
    if pipeline_wiring == "PIPE_DEAD_OR_SHADOWED":
        return "shadowed_or_unloaded"
    if {"default_pass", "bundle_pass", "command_handler"} & runtime_tags and test_strength in {"TEST_STRONG", "TEST_MEDIUM"}:
        return "live_verified"
    if runtime_tags:
        return "live_partial"
    return "historical_claim_only"


def confidence_band(test_strength: str, pipeline_wiring: str, failure_flags: list[str]) -> str:
    if failure_flags:
        return "low"
    if test_strength == "TEST_STRONG" and pipeline_wiring == "PIPE_ACTIVE":
        return "high"
    if test_strength in {"TEST_STRONG", "TEST_MEDIUM"} and pipeline_wiring in {"PIPE_ACTIVE", "PIPE_PARTIAL", "PIPE_OPTIONAL"}:
        return "medium"
    return "low"


def category_for_row(file_name: str, function_name: str) -> str:
    text = f"{file_name} {function_name}".lower()
    if any(term in text for term in ("waterfall", "river", "lake", "hydro", "water_", "_water", "wetland", "coast")):
        return "water"
    if any(term in text for term in ("noise", "erosion", "world", "macro", "depth", "weathering")):
        return "heightfield"
    if any(term in text for term in ("banded", "strat", "cliff", "cave", "geolog", "sculpt", "feature")):
        return "geology"
    if any(term in text for term in ("atmos", "fog", "horizon", "mist", "cloud", "god_ray")):
        return "atmosphere"
    if any(term in text for term in ("road", "lod", "chunk", "stream", "budget")):
        return "streaming"
    if any(term in text for term in ("material", "shader", "paint", "color", "splat")):
        return "materials"
    if any(term in text for term in ("biome", "vegetation", "scatter", "ecotone", "wildlife", "environment")):
        return "scatter"
    if any(term in text for term in ("validation", "pipeline", "registrar", "checkpoint", "dirty", "golden", "semantic")):
        return "pipeline"
    return "general"


def generic_aaa_path(category: str, bucket: str, pipeline_wiring: str, test_strength: str, failure_flags: list[str]) -> str:
    steps: List[str] = []
    if pipeline_wiring in {"PIPE_PARTIAL", "PIPE_DEAD_OR_SHADOWED", "PIPE_OPTIONAL", "PIPE_CONTRACT_MISMATCH"}:
        steps.append("Wire this into the default/master runtime path and remove stale or contract-breaking call surfaces.")
    if test_strength in {"TEST_NONE", "TEST_WEAK"} or failure_flags:
        if category == "water":
            steps.append("Add physical invariants for spill height, flow continuity, water masks, and exportable surface metadata.")
        elif category == "heightfield":
            steps.append("Add spectral, seam, determinism, and erosion-reference goldens tied to the shipped path.")
        elif category == "geology":
            steps.append("Add finite-value, orientation, and mesh/material metadata tests that prove geological breakup rather than only shape presence.")
        elif category == "atmosphere":
            steps.append("Add channel-contract, placement, and readability tests plus camera-facing validation in an engine viewport.")
        elif category == "streaming":
            steps.append("Add API-contract, seam continuity, and visible-pop tests across chunk and LOD boundaries.")
        elif category == "materials":
            steps.append("Round-trip exported masks/material params through Unity or Unreal and add perceptual or artifact-diff checks.")
        elif category == "scatter":
            steps.append("Add overlap/exclusion/grounding tests and verify placement breakup against terrain-aware masks.")
        elif category == "pipeline":
            steps.append("Add end-to-end pass and rollback tests so pipeline claims are backed by current runtime behavior, not ledger text.")
        else:
            steps.append("Add direct runtime and behavior tests that validate the shipped implementation, not just helper-level smoke checks.")
    if category in {"heightfield", "streaming"} or "FAIL_PERF_SEVERE" in failure_flags:
        steps.append("Hit explicit generation/streaming budgets in CI before keeping any B+ or A-range claim.")
    steps.append("Validate against a real AAA bar: Houdini/Gaea-style terrain references plus Unity/Unreal import or camera playback where applicable.")
    return " ".join(steps)


def build_aaa_path(file_name: str, function_name: str, category: str, bucket: str, pipeline_wiring: str, test_strength: str, failure_flags: list[str]) -> str:
    specific = SPECIFIC_AAA_PATHS.get((file_name, function_name))
    if specific:
        return specific
    return generic_aaa_path(category, bucket, pipeline_wiring, test_strength, failure_flags)


def format_adjustments(adjustments: dict[str, float]) -> str:
    return "; ".join(f"{name}={value:+.2f}" for name, value in adjustments.items() if abs(value) > 1e-9) or "none"


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(
    path: Path,
    strict_rows: Sequence[dict[str, str]],
    downgraded_rows: Sequence[dict[str, str]],
    non_gradable_rows: Sequence[dict[str, str]],
) -> None:
    grade_dist = Counter(row["STRICT_CURRENT_GRADE"] for row in strict_rows if row["STRICT_CURRENT_GRADE"])
    bucket_dist = Counter(row["STRICT_BUCKET"] for row in strict_rows)
    file_downgrades = Counter(row["File"] for row in downgraded_rows)
    low_confidence = [row for row in strict_rows if row["STRICT_CONFIDENCE"] == "low"]
    top_downgrades = sorted(
        downgraded_rows,
        key=lambda row: (abs(int(row["STRICT_DELTA_NOTCHES"])), row["File"], row["Function"]),
        reverse=True,
    )[:20]
    lines = [
        "# Strict Audit Summary",
        "",
        "Audit date: 2026-04-19",
        f"Source sheet: `{CSV_PATH}`",
        f"Output CSV: `{OUTPUT_CSV}`",
        "",
        "## Method",
        "",
        "- Primary key is the CSV row `#`, not just `(File, Function)`, because the sheet currently contains duplicate keys.",
        "- Latest claim precedence is `R9 -> R8 -> R7 -> FINAL -> older rounds` using the strict rubric in `docs/aaa-audit/STRICT_AUDIT_RUBRIC.json`.",
        "- Live evidence is layered on top of the claim: code existence, symbol-line match, test hits, runtime exposure, and current failing-test signals.",
        "- Current direct failures were refreshed on 2026-04-19 for checkpoints, chunking, banded terrain, horizon LOD, hydrology, caves, and terrain-noise performance.",
        "",
        "## Headline Numbers",
        "",
        f"- Total rows processed: `{len(strict_rows)}`",
        f"- Non-gradable / scope-exempt rows: `{len(non_gradable_rows)}`",
        f"- Downgraded rows vs latest claim: `{len(downgraded_rows)}`",
        f"- Low-confidence rows: `{len(low_confidence)}`",
        "",
        "Grade distribution:",
    ]
    for grade, count in sorted(grade_dist.items(), key=lambda item: (item[0] != "SCOPE_EXEMPT", item[0])):
        lines.append(f"- `{grade}`: `{count}`")
    lines.extend(
        [
            "",
            "Evidence buckets:",
        ]
    )
    for bucket, count in sorted(bucket_dist.items()):
        lines.append(f"- `{bucket}`: `{count}`")
    lines.extend(
        [
            "",
            "## Highest-Risk Files",
            "",
        ]
    )
    for file_name, count in file_downgrades.most_common(15):
        lines.append(f"- `{file_name}`: `{count}` downgraded row(s)")
    lines.extend(
        [
            "",
            "## Direct Failure Clusters Confirmed On 2026-04-19",
            "",
            "- `terrain_checkpoints.py`: 12 failures. Save, rollback, presets, and autosave all break on the current `*.npz.tmp` path handling.",
            "- `terrain_chunking.py::compute_chunk_lod`: 6 failures. The live API returns an `int` LOD level while the shipped tests still expect a downsampled heightmap.",
            "- `terrain_banded.py`: 4 failures plus invalid-power warnings. Composition linearity, warp centering, and strata-direction invariants are failing.",
            "- `terrain_horizon_lod.py::pass_horizon_lod`: 1 failure. The pass writes `horizon_elevation_angles`, but semantics does not accept that channel.",
            "- `_water_network.py::detect_lakes`: 1 physical-plausibility failure. `surface_z` can be lower than member lake cells.",
            "- `terrain_caves.py::pick_cave_archetype`: 1 direct behavior failure. Wet high plateau still picks `karst_sinkhole` instead of `glacial_melt`.",
            "- `_terrain_noise.py::generate_heightmap`: severe perf miss. `256x256 mountains` took `13.086s` vs `<0.5s`; six `128x128` terrains took `32.002s` vs `<3s`.",
            "",
            "## Largest Downgrades",
            "",
        ]
    )
    for row in top_downgrades:
        lines.append(
            f"- Row `{row['#']}` `{row['File']}::{row['Function']}` "
            f"`{row['STRICT_BASE_GRADE']}` -> `{row['STRICT_CURRENT_GRADE']}` "
            f"({row['STRICT_EVIDENCE_FLAGS']})"
        )
    lines.extend(
        [
            "",
            "## AAA Verification Bar Used",
            "",
            "- Houdini HeightField Erode: multi-scale erosion, mask-driven terrain operations, and production-grade channel workflows.",
            "- Gaea erosion/strata references: geological breakup, sediment transport, and art-directed terrain layers.",
            "- AAA engine bar: Unity/Unreal import validity, camera-facing readability, and open-world streaming/no-pop expectations.",
            "- Activision COD terrain reference: runtime terrain streaming and readability at game-speed traversal.",
            "",
            "These references inform the `STRICT_AAA_PATH` column. A row does not keep an A/B-range grade unless the code, tests, and live runtime path can realistically support that bar.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rubric = load_rubric()
    fieldnames, rows = load_rows()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    symbol_index, file_paths = build_symbol_index()
    test_paths = sorted(TESTS_DIR.rglob("test_*.py"))
    py_paths = sorted((REPO_ROOT / "veilbreakers_terrain").rglob("*.py"))
    per_file_counts, test_occurrences, source_occurrences, test_file_hits, source_file_hits, import_hits = build_identifier_stats(py_paths)
    runtime_index = build_runtime_index(file_paths)
    lastfailed = load_lastfailed()
    duplicate_counter = Counter((row.get("File", "").strip(), row.get("Function", "").strip()) for row in rows)

    extra_fields = [
        "STRICT_ROW_ID",
        "STRICT_BASE_GRADE",
        "STRICT_BASE_SOURCE",
        "STRICT_BASE_SCORE",
        "STRICT_CURRENT_SCORE",
        "STRICT_CURRENT_GRADE",
        "STRICT_DELTA_NOTCHES",
        "STRICT_CONFIDENCE",
        "STRICT_BUCKET",
        "STRICT_CODE_EXISTS",
        "STRICT_SYMBOL_KIND",
        "STRICT_CONTAINER_CLASS",
        "STRICT_LINE_DELTA",
        "STRICT_DUPLICATE_KEY",
        "STRICT_TEST_HITS",
        "STRICT_TEST_FILE_HITS",
        "STRICT_IMPORT_HITS",
        "STRICT_SOURCE_FILE_HITS",
        "STRICT_RUNTIME_EXPOSURE",
        "STRICT_FAILURE_FLAGS",
        "STRICT_EVIDENCE_FLAGS",
        "STRICT_ADJUSTMENTS",
        "STRICT_FAILURE_NOTE",
        "STRICT_AAA_PATH",
    ]
    output_fieldnames = list(fieldnames)
    for field in extra_fields:
        if field not in output_fieldnames:
            output_fieldnames.append(field)

    strict_rows: List[dict[str, str]] = []
    downgraded_rows: List[dict[str, str]] = []
    non_gradable_rows: List[dict[str, str]] = []

    for row in rows:
        file_name = (row.get("File") or "").strip()
        function_name = (row.get("Function") or "").strip()
        row_id = (row.get("#") or "").strip()
        csv_line = safe_int(row.get("Line") or "")
        row_flags = text_flags(row)
        claim_grade, claim_source, claim_score, claim_flag = latest_claim(row, rubric)
        non_gradable = claim_flag == "NON_GRADABLE" or claim_grade in {"SCOPE_EXEMPT", "N/A", "N/A (SCOPE)"}

        path = file_paths.get(file_name)
        code_exists = path is not None
        symbol = pick_symbol(symbol_index.get(file_name, []), function_name, csv_line) if code_exists else None
        line_delta = abs(csv_line - symbol.lineno) if symbol and csv_line is not None else ""
        duplicate_key = duplicate_counter[(file_name, function_name)] > 1

        own_count = per_file_counts.get(path, Counter()).get(function_name, 0) if path else 0
        test_hits = test_occurrences.get(function_name, 0)
        test_files = test_file_hits.get(function_name, 0)
        import_hit_count = import_hits.get(function_name, 0)
        source_files = max(source_file_hits.get(function_name, 0) - (1 if own_count else 0), 0)
        runtime_tags = runtime_index.get(function_name, set())
        failure_flags = collect_failure_flags(file_name, function_name)
        has_module_named_test = module_named_test_exists(file_name, test_paths)
        test_strength = classify_test_strength(
            function_name,
            file_name,
            test_hits,
            test_files,
            import_hit_count,
            bool(DIRECT_FAILURE_FLAGS.get((file_name, function_name))),
            has_module_named_test,
        )
        pipeline_wiring = classify_pipeline_wiring(
            runtime_tags,
            source_files,
            row_flags,
            "FAIL_CONTRACT_CHANNEL" in failure_flags,
        )
        public_exposure = classify_public_exposure(function_name, runtime_tags, row_flags)
        bucket = evidence_bucket(
            code_exists=bool(symbol),
            runtime_tags=runtime_tags,
            test_strength=test_strength,
            pipeline_wiring=pipeline_wiring,
            failure_flags=failure_flags,
            non_gradable=non_gradable,
        )
        confidence = confidence_band(test_strength, pipeline_wiring, failure_flags)
        category = category_for_row(file_name, function_name)
        aaa_path = build_aaa_path(
            file_name,
            function_name,
            category,
            bucket,
            pipeline_wiring,
            test_strength,
            failure_flags,
        )
        note = failure_note(file_name, function_name, lastfailed)

        if not claim_grade:
            claim_grade = ""
            claim_score = 0.0

        if non_gradable:
            current_score = 0.0
            current_grade = claim_grade or "SCOPE_EXEMPT"
            delta_notches = ""
            adjustments_text = "non-gradable row"
        else:
            adjustments = {
                claim_flag: float(rubric["adjustments"]["claim_recency"][claim_flag]),
                test_strength: float(rubric["adjustments"]["test_strength"][test_strength]),
                pipeline_wiring: float(rubric["adjustments"]["pipeline_wiring"][pipeline_wiring]),
                public_exposure: float(rubric["adjustments"]["public_exposure"][public_exposure]),
            }
            failure_adjust = sum(float(rubric["adjustments"]["failure_evidence"][flag]) for flag in failure_flags)
            failure_adjust = max(failure_adjust, float(rubric["failure_penalty_cap"]))
            if failure_flags:
                adjustments["FAILURES"] = failure_adjust
            pre_cap_score = max(0.0, min(4.0, claim_score + sum(adjustments.values())))
            current_score, cap_grade = apply_caps(
                pre_cap_score,
                failure_flags,
                test_strength,
                pipeline_wiring,
                public_exposure,
                rubric,
            )
            current_grade = score_to_grade(current_score, rubric)
            if cap_grade:
                current_grade = score_to_grade(min(current_score, float(rubric["grade_scale"][cap_grade])), rubric)
            delta_notches = grade_to_notch(current_grade, rubric) - grade_to_notch(claim_grade, rubric)
            adjustments_text = format_adjustments(adjustments)

        evidence_flags = [claim_flag] if claim_flag != "NON_GRADABLE" else ["SCOPE_EXEMPT"]
        evidence_flags.extend(
            [
                test_strength,
                pipeline_wiring,
                public_exposure,
                *failure_flags,
            ]
        )
        if duplicate_key:
            evidence_flags.append("DUPLICATE_ROW_KEY")
        if not symbol:
            evidence_flags.append("CSV_STALE_ROW")
        if source_files == 0 and not runtime_tags:
            evidence_flags.append("NO_RUNTIME_REACH")
        if code_exists and line_delta != "" and isinstance(line_delta, int) and line_delta > 25:
            evidence_flags.append("LINE_DRIFT_GT_25")

        enriched = dict(row)
        enriched.update(
            {
                "STRICT_ROW_ID": row_id,
                "STRICT_BASE_GRADE": claim_grade,
                "STRICT_BASE_SOURCE": claim_source,
                "STRICT_BASE_SCORE": f"{claim_score:.2f}" if claim_grade else "",
                "STRICT_CURRENT_SCORE": f"{current_score:.2f}" if not non_gradable else "",
                "STRICT_CURRENT_GRADE": current_grade,
                "STRICT_DELTA_NOTCHES": str(delta_notches) if delta_notches != "" else "",
                "STRICT_CONFIDENCE": confidence,
                "STRICT_BUCKET": bucket,
                "STRICT_CODE_EXISTS": "yes" if symbol else "no",
                "STRICT_SYMBOL_KIND": symbol.kind if symbol else "",
                "STRICT_CONTAINER_CLASS": symbol.container_class if symbol else "",
                "STRICT_LINE_DELTA": str(line_delta) if line_delta != "" else "",
                "STRICT_DUPLICATE_KEY": "yes" if duplicate_key else "no",
                "STRICT_TEST_HITS": str(test_hits),
                "STRICT_TEST_FILE_HITS": str(test_files),
                "STRICT_IMPORT_HITS": str(import_hit_count),
                "STRICT_SOURCE_FILE_HITS": str(source_files),
                "STRICT_RUNTIME_EXPOSURE": ",".join(sorted(runtime_tags)) if runtime_tags else "none",
                "STRICT_FAILURE_FLAGS": ",".join(failure_flags) if failure_flags else "FAIL_NONE",
                "STRICT_EVIDENCE_FLAGS": ",".join(evidence_flags),
                "STRICT_ADJUSTMENTS": adjustments_text,
                "STRICT_FAILURE_NOTE": note,
                "STRICT_AAA_PATH": aaa_path,
            }
        )
        strict_rows.append(enriched)
        if non_gradable:
            non_gradable_rows.append(enriched)
        elif delta_notches > 0:
            downgraded_rows.append(enriched)

    write_csv(OUTPUT_CSV, output_fieldnames, strict_rows)
    write_summary(OUTPUT_SUMMARY, strict_rows, downgraded_rows, non_gradable_rows)

    print(f"Wrote strict audit CSV: {OUTPUT_CSV}")
    print(f"Wrote strict audit summary: {OUTPUT_SUMMARY}")
    print(f"Rows processed: {len(strict_rows)}")
    print(f"Downgraded rows: {len(downgraded_rows)}")
    print(f"Non-gradable rows: {len(non_gradable_rows)}")


if __name__ == "__main__":
    main()
