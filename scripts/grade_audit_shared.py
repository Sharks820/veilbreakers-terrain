"""Shared helpers for callable-grade audit tooling."""

from __future__ import annotations

import ast
import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
HANDLERS_DIR = REPO_ROOT / "veilbreakers_terrain" / "handlers"
DEFAULT_GRADE_FILE = REPO_ROOT / "docs" / "aaa-audit" / "GRADES_VERIFIED.csv"
VALID_GRADE_TOKENS = {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "F"}


@dataclass(frozen=True)
class CallableDef:
    file: str
    qualified_name: str
    simple_name: str
    lineno: int
    kind: str


@dataclass(frozen=True)
class GradeMatch:
    row: dict | None
    status: str
    match_mode: str


class CallableVisitor(ast.NodeVisitor):
    def __init__(self, file_name: str) -> None:
        self.file_name = file_name
        self.class_stack: List[str] = []
        self.rows: List[CallableDef] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._record(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._record(node)
        self.generic_visit(node)

    def _record(self, node: ast.AST) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if node.name.startswith("__") and node.name.endswith("__"):
            return
        container = self.class_stack[-1] if self.class_stack else ""
        qualified = f"{container}.{node.name}" if container else node.name
        kind = "method" if container else "function"
        self.rows.append(
            CallableDef(
                file=self.file_name,
                qualified_name=qualified,
                simple_name=node.name,
                lineno=node.lineno,
                kind=kind,
            )
        )


def collect_callables(include_init: bool = True) -> List[CallableDef]:
    out: List[CallableDef] = []
    for py in sorted(HANDLERS_DIR.glob("*.py")):
        if not include_init and py.name == "__init__.py":
            continue
        tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"), filename=str(py))
        visitor = CallableVisitor(py.name)
        visitor.visit(tree)
        out.extend(visitor.rows)
    return out


def collect_classes(include_init: bool = True) -> Dict[str, set[str]]:
    classes_by_file: Dict[str, set[str]] = defaultdict(set)
    for py in sorted(HANDLERS_DIR.glob("*.py")):
        if not include_init and py.name == "__init__.py":
            continue
        tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes_by_file[py.name].add(node.name)
    return classes_by_file


def read_grade_rows(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def norm(value: str) -> str:
    return (value or "").strip()


def normalize_function_name(name: str) -> str:
    raw = norm(name)
    if not raw:
        return ""
    return raw.split(".")[-1]


def parse_line(value: str) -> int | None:
    raw = norm(value)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def latest_grade(row: dict) -> str:
    for column in (
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
    ):
        raw = norm(row.get(column, ""))
        if not raw:
            continue
        token = raw.split("|", 1)[0].strip()
        if token in VALID_GRADE_TOKENS:
            return token
    return ""


class GradeIndex:
    def __init__(self) -> None:
        self.by_file_name: DefaultDict[Tuple[str, str], List[dict]] = defaultdict(list)
        self.by_simple_name: DefaultDict[str, List[dict]] = defaultdict(list)


def build_grade_index(rows: Iterable[dict]) -> GradeIndex:
    index = GradeIndex()
    for row in rows:
        file_name = norm(row.get("File", ""))
        function_name = norm(row.get("Function", ""))
        if not file_name or not function_name:
            continue
        index.by_file_name[(file_name, function_name)].append(row)
        index.by_simple_name[normalize_function_name(function_name)].append(row)
    return index


def _select_row(rows: Sequence[dict], lineno: int) -> tuple[dict | None, bool]:
    if not rows:
        return None, False
    if len(rows) == 1:
        return rows[0], False

    exact_line_matches = [row for row in rows if parse_line(row.get("Line", "")) == lineno]
    if len(exact_line_matches) == 1:
        return exact_line_matches[0], False

    return None, True


def resolve_grade_match(callable_def: CallableDef, index: GradeIndex) -> GradeMatch:
    qualified_rows = index.by_file_name.get((callable_def.file, callable_def.qualified_name), [])
    matched_row, ambiguous = _select_row(qualified_rows, callable_def.lineno)
    if matched_row:
        return GradeMatch(matched_row, "GRADED", "file_qualified")
    if ambiguous:
        return GradeMatch(None, "AMBIGUOUS_FILE_MATCH", "file_qualified")

    simple_rows = index.by_file_name.get((callable_def.file, callable_def.simple_name), [])
    matched_row, ambiguous = _select_row(simple_rows, callable_def.lineno)
    if matched_row:
        return GradeMatch(matched_row, "GRADED", "file_simple")
    if ambiguous:
        return GradeMatch(None, "AMBIGUOUS_FILE_MATCH", "file_simple")

    same_name_rows = index.by_simple_name.get(callable_def.simple_name, [])
    if len(same_name_rows) == 1:
        return GradeMatch(same_name_rows[0], "NAME_ONLY_MATCH", "global_simple")
    if len(same_name_rows) > 1:
        return GradeMatch(None, "AMBIGUOUS_NAME_MATCH", "global_simple")

    return GradeMatch(None, "MISSING", "none")
