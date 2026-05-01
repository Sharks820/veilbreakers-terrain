"""Build a second-pass master callable audit across the terrain handlers.

This merges:
- live callable definitions in handlers/
- runtime exposure from command handlers, default passes, and master bundle passes
- static call graph reachability through handler callsites
- grade-sheet coverage, including qualified/unqualified semantic matches
- strict grade results, when available

Outputs:
- output/spreadsheet/MASTER_CALLABLE_AUDIT_2026_04_19.csv
- docs/aaa-audit/MASTER_AUDIT_2026_04_19.md
"""

from __future__ import annotations

import ast
import csv
import subprocess
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
HANDLERS_DIR = REPO_ROOT / "veilbreakers_terrain" / "handlers"
TESTS_DIR = REPO_ROOT / "veilbreakers_terrain" / "tests"
CSV_PATH = REPO_ROOT / "docs" / "aaa-audit" / "GRADES_VERIFIED.csv"
STRICT_CSV = REPO_ROOT / "output" / "spreadsheet" / "GRADES_STRICT_2026_04_19.csv"
FIRST_PASS_CSV = REPO_ROOT / "output" / "spreadsheet" / "CALLABLE_WIRING_AUDIT_2026_04_19.csv"
OUTPUT_DIR = REPO_ROOT / "output" / "spreadsheet"
OUTPUT_CSV = OUTPUT_DIR / "MASTER_CALLABLE_AUDIT_2026_04_19.csv"
OUTPUT_MD = REPO_ROOT / "docs" / "aaa-audit" / "MASTER_AUDIT_2026_04_19.md"


@dataclass(frozen=True)
class CallableDef:
    file: str
    name: str
    lineno: int
    kind: str
    container: str = ""

    @property
    def qualified_name(self) -> str:
        return f"{self.container}.{self.name}" if self.container else self.name

    @property
    def key(self) -> Tuple[str, str]:
        return (self.file, self.qualified_name)


@dataclass(frozen=True)
class CallEdge:
    source: Tuple[str, str]
    target: Tuple[str, str]
    source_file: str
    line: int
    kind: str
    in_tests: bool


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_module(path: Path) -> ast.AST:
    return ast.parse(read_text(path), filename=str(path))


def tracked_python_files() -> List[Path]:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "*.py", "veilbreakers_terrain/**/*.py"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        files = [
            REPO_ROOT / line.strip()
            for line in proc.stdout.splitlines()
            if line.strip().endswith(".py")
        ]
        return sorted(path for path in files if path.exists())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return sorted((REPO_ROOT / "veilbreakers_terrain").rglob("*.py"))


def handler_files() -> List[Path]:
    return [path for path in tracked_python_files() if path.parent == HANDLERS_DIR]


def normalize_function_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    return raw.split(".")[-1]


def to_handler_file(module_name: str, defs_by_file: Dict[str, List["CallableDef"]]) -> Optional[str]:
    module_name = (module_name or "").strip()
    if not module_name:
        return None
    if module_name in {"handlers", ".handlers", "veilbreakers_terrain.handlers", "blender_addon.handlers"}:
        return "__init__.py"
    if module_name.endswith(".handlers"):
        return "__init__.py"
    if module_name.startswith("."):
        tail = module_name.lstrip(".")
        if tail == "handlers":
            return "__init__.py"
        candidate = f"{tail.split('.')[-1]}.py"
        return candidate if candidate in defs_by_file else None
    if module_name.startswith("veilbreakers_terrain.handlers.") or module_name.startswith("blender_addon.handlers."):
        tail = module_name.split(".")[-1]
        if tail == "handlers":
            return "__init__.py"
        candidate = f"{tail}.py"
        return candidate if candidate in defs_by_file else None
    candidate = f"{module_name.split('.')[-1]}.py"
    if candidate in defs_by_file:
        return candidate
    return None


def extract_constant_string(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: List[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
        return "".join(parts)
    return ""


def extract_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


class DefVisitor(ast.NodeVisitor):
    def __init__(self, file_name: str) -> None:
        self.file_name = file_name
        self.class_stack: List[str] = []
        self.function_stack: List[str] = []
        self.records: List[CallableDef] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._enter_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._enter_function(node)

    def _enter_function(self, node: ast.AST) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if not self.function_stack:
            self._record(node)
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def _record(self, node: ast.AST) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if node.name.startswith("__") and node.name.endswith("__"):
            return
        container = self.class_stack[-1] if self.class_stack else ""
        kind = "property" if self._is_property(node) else ("method" if container else "function")
        self.records.append(CallableDef(self.file_name, node.name, node.lineno, kind, container))

    @staticmethod
    def _is_property(node: ast.AST) -> bool:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id in {"property", "cached_property"}:
                return True
            if isinstance(decorator, ast.Attribute) and decorator.attr in {"setter", "getter", "deleter"}:
                return True
        return False


class CallGraphVisitor(ast.NodeVisitor):
    def __init__(
        self,
        file_name: str,
        defs_by_file: Dict[str, List[CallableDef]],
        alias_functions: Dict[str, Tuple[str, str]],
        alias_modules: Dict[str, str],
        in_tests: bool,
    ) -> None:
        self.file_name = file_name
        self.defs_by_file = defs_by_file
        self.alias_functions = alias_functions
        self.alias_modules = alias_modules
        self.in_tests = in_tests
        self.class_stack: List[str] = []
        self.func_stack: List[str] = []
        self.edges: List[CallEdge] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.class_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._enter_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._enter_function(node)

    def _enter_function(self, node: ast.AST) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        container = self.class_stack[-1] if self.class_stack else ""
        current = f"{container}.{node.name}" if container else node.name
        self.func_stack.append(current)
        for child in node.body:
            self.visit(child)
        self.func_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if not self.func_stack:
            self.generic_visit(node)
            return
        source = (self.file_name, self.func_stack[-1])
        target = self._resolve_call_target(node.func)
        if target:
            self.edges.append(
                CallEdge(
                    source=source,
                    target=target,
                    source_file=self.file_name,
                    line=node.lineno,
                    kind="call",
                    in_tests=self.in_tests,
                )
            )
        self.generic_visit(node)

    def _resolve_call_target(self, node: ast.AST) -> Optional[Tuple[str, str]]:
        if isinstance(node, ast.Name):
            if node.id in self.alias_functions:
                return self.alias_functions[node.id]
            local_candidates = self._local_defs(normalize_function_name(node.id))
            if local_candidates:
                return local_candidates[0]
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                base = node.value.id
                if base in {"self", "cls"} and self.class_stack:
                    qname = f"{self.class_stack[-1]}.{node.attr}"
                    if any(d.qualified_name == qname for d in self.defs_by_file.get(self.file_name, [])):
                        return (self.file_name, qname)
                if base in self.alias_modules:
                    target_file = self.alias_modules[base]
                    return self._best_match(target_file, node.attr)
            local_candidates = self._local_defs(node.attr)
            if local_candidates:
                return local_candidates[0]
        return None

    def _best_match(self, target_file: str, symbol: str) -> Optional[Tuple[str, str]]:
        defs = self.defs_by_file.get(target_file, [])
        for record in defs:
            if record.qualified_name == symbol or record.name == symbol:
                return (target_file, record.qualified_name)
        return None

    def _local_defs(self, symbol: str) -> List[Tuple[str, str]]:
        defs = []
        for record in self.defs_by_file.get(self.file_name, []):
            if record.name == symbol or record.qualified_name == symbol:
                defs.append((self.file_name, record.qualified_name))
        return defs


def import_maps(tree: ast.AST, file_name: str, defs_by_file: Dict[str, List[CallableDef]]) -> Tuple[Dict[str, Tuple[str, str]], Dict[str, str]]:
    alias_functions: Dict[str, Tuple[str, str]] = {}
    alias_modules: Dict[str, str] = {}

    def bind_alias(local_name: str, target_file: str, symbol: str) -> None:
        for record in defs_by_file.get(target_file, []):
            if record.name == symbol or record.qualified_name == symbol:
                alias_functions[local_name] = (target_file, record.qualified_name)
                break

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module is None and node.level:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    target_file = to_handler_file(alias.name, defs_by_file)
                    if target_file:
                        alias_modules[local] = target_file
                continue
            target_file = to_handler_file(node.module or "", defs_by_file)
            if not target_file:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                if target_file == "__init__.py" and alias.name == "handlers":
                    alias_modules[local] = target_file
                elif target_file == f"{alias.name}.py":
                    alias_modules[local] = target_file
                else:
                    bind_alias(local, target_file, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                target_file = to_handler_file(alias.name, defs_by_file)
                if target_file:
                    alias_modules[alias.asname or alias.name.split(".")[-1]] = target_file
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if isinstance(node.value, ast.Call) and extract_name(node.value.func) == "import_module" and node.value.args:
                    target_file = to_handler_file(extract_constant_string(node.value.args[0]), defs_by_file)
                    if target_file:
                        alias_modules[target.id] = target_file

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Attribute):
            continue
        if not isinstance(node.value.value, ast.Name):
            continue
        base = node.value.value.id
        if base not in alias_modules:
            continue
        target_file = alias_modules[base]
        for target in node.targets:
            if isinstance(target, ast.Name):
                bind_alias(target.id, target_file, node.value.attr)
    return alias_functions, alias_modules


def resolve_symbol(
    file_name: str,
    symbol: str,
    alias_functions: Dict[str, Tuple[str, str]],
    defs_by_file: Dict[str, List[CallableDef]],
) -> Optional[Tuple[str, str]]:
    if not symbol:
        return None
    if symbol in alias_functions:
        return alias_functions[symbol]
    for record in defs_by_file.get(file_name, []):
        if record.name == symbol or record.qualified_name == symbol:
            return (file_name, record.qualified_name)
    return None


def resolve_call_target(
    file_name: str,
    node: ast.AST,
    alias_functions: Dict[str, Tuple[str, str]],
    alias_modules: Dict[str, str],
    defs_by_file: Dict[str, List[CallableDef]],
) -> Optional[Tuple[str, str]]:
    if isinstance(node, ast.Name):
        return resolve_symbol(file_name, node.id, alias_functions, defs_by_file)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        base = node.value.id
        if base in alias_modules:
            return resolve_symbol(alias_modules[base], node.attr, {}, defs_by_file)
        return resolve_symbol(file_name, node.attr, alias_functions, defs_by_file)
    return resolve_symbol(file_name, extract_name(node) or "", alias_functions, defs_by_file)


def collect_module_exports(path: Path) -> set[str]:
    exports: set[str] = set()
    tree = parse_module(path)
    for node in ast.walk(tree):
        targets: List[str] = []
        value: Optional[ast.AST] = None
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        if "__all__" not in targets or not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            continue
        for elt in value.elts:
            export_name = extract_constant_string(elt)
            if export_name:
                exports.add(export_name)
    return exports


def collect_defs() -> Tuple[List[CallableDef], Dict[str, List[CallableDef]]]:
    defs: List[CallableDef] = []
    defs_by_file: Dict[str, List[CallableDef]] = defaultdict(list)
    for path in handler_files():
        visitor = DefVisitor(path.name)
        visitor.visit(parse_module(path))
        defs.extend(visitor.records)
        defs_by_file[path.name].extend(visitor.records)
    return defs, defs_by_file


def collect_edges(defs_by_file: Dict[str, List[CallableDef]]) -> List[CallEdge]:
    edges: List[CallEdge] = []
    for path in tracked_python_files():
        file_name = path.relative_to(REPO_ROOT).as_posix()
        tree = parse_module(path)
        alias_functions, alias_modules = import_maps(tree, file_name, defs_by_file)
        visitor = CallGraphVisitor(
            file_name=file_name.split("/")[-1] if "/handlers/" in file_name else file_name,
            defs_by_file=defs_by_file,
            alias_functions=alias_functions,
            alias_modules=alias_modules,
            in_tests="/tests/" in file_name,
        )
        visitor.visit(tree)
        edges.extend(visitor.edges)
    return edges


def collect_runtime_exposure(defs_by_file: Dict[str, List[CallableDef]]) -> DefaultDict[Tuple[str, str], List[str]]:
    exposure: DefaultDict[Tuple[str, str], List[str]] = defaultdict(list)
    registrar_to_targets: Dict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
    registrar_calls: DefaultDict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)

    # Collect registrar-owned pass targets and registrar -> sub-registrar calls.
    for path in handler_files():
        tree = parse_module(path)
        aliases, module_aliases = import_maps(tree, path.name, defs_by_file)
        for node in ast.walk(tree):
            is_registrar = (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (node.name.startswith("register_") or (path.name == "terrain_pipeline.py" and node.name == "register_default_passes"))
            )
            if not is_registrar:
                continue
            reg_key = (path.name, node.name)
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and extract_name(child.func) == "PassDefinition":
                    target_name = ""
                    for kw in child.keywords:
                        if kw.arg == "func":
                            target_name = extract_name(kw.value) or ""
                            break
                    if not target_name and child.args:
                        target_name = extract_name(child.args[0]) or ""
                    target = resolve_symbol(path.name, target_name, aliases, defs_by_file)
                    if target:
                        registrar_to_targets[reg_key].append(target)
                        exposure[target].append("module_registrar")
                    continue
                if isinstance(child, ast.Call):
                    callee = resolve_call_target(path.name, child.func, aliases, module_aliases, defs_by_file)
                    if callee and (callee[1].startswith("register_") or callee == ("terrain_pipeline.py", "register_default_passes")):
                        registrar_calls[reg_key].append(callee)

    # __init__ command handlers and generated closures.
    init_path = HANDLERS_DIR / "__init__.py"
    if init_path.exists():
        tree = parse_module(init_path)
        aliases, _module_aliases = import_maps(tree, "__init__.py", defs_by_file)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and extract_name(node.func) == "_try_register" and len(node.args) >= 3:
                module_hint = extract_constant_string(node.args[1])
                fn_name = extract_constant_string(node.args[2])
                target_file = f"{module_hint.split('.')[-1]}.py" if module_hint else ""
                if target_file and fn_name:
                    target = resolve_symbol(target_file, fn_name, {}, defs_by_file)
                    if target:
                        exposure[target].append("command_handler")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == "handlers":
                        rhs = ""
                        if isinstance(node.value, ast.Call):
                            rhs = extract_name(node.value.func) or ""
                            if rhs == "_fail_closed":
                                for record in defs_by_file.get("__init__.py", []):
                                    if record.name in {"_fail_closed", "_handler"}:
                                        exposure[("__init__.py", record.qualified_name)].append("command_wrapper")
                                continue
                            if rhs == "_make_generator_handler":
                                for record in defs_by_file.get("__init__.py", []):
                                    if record.name in {"_make_generator_handler", "_h"}:
                                        exposure[("__init__.py", record.qualified_name)].append("command_wrapper")
                                continue
                        else:
                            rhs = extract_name(node.value) or ""
                        wrapped = resolve_symbol("__init__.py", rhs, aliases, defs_by_file)
                        if wrapped:
                            exposure[wrapped].append("command_wrapper")
                    elif isinstance(target, ast.Name) and target.id == "COMMAND_HANDLERS":
                        call_name = ""
                        if isinstance(node.value, ast.Call):
                            call_name = extract_name(node.value.func) or ""
                        wrapped = resolve_symbol("__init__.py", call_name, aliases, defs_by_file)
                        if wrapped:
                            exposure[wrapped].append("module_init")
            elif isinstance(node, ast.AnnAssign):
                target = node.target
                if isinstance(target, ast.Name) and target.id == "COMMAND_HANDLERS":
                    call_name = ""
                    if isinstance(node.value, ast.Call):
                        call_name = extract_name(node.value.func) or ""
                    wrapped = resolve_symbol("__init__.py", call_name, aliases, defs_by_file)
                    if wrapped:
                        exposure[wrapped].append("module_init")

        animation_exports = collect_module_exports(HANDLERS_DIR / "animation_environment.py")
        for export_name in sorted(animation_exports):
            if (
                export_name.startswith("generate_")
                and export_name.endswith("_keyframes")
                and export_name != "generate_env_keyframes"
            ):
                target = resolve_symbol("animation_environment.py", export_name, {}, defs_by_file)
                if target:
                    exposure[target].append("command_handler_generated")

    # Seed Bundle A and the master registrar, then follow bundle-transitive
    # sub-registrars (J/K/L/O, supplemental default-pass helpers, etc.).
    registrar_queue: deque[Tuple[Tuple[str, str], str]] = deque()
    registrar_seen: set[Tuple[Tuple[str, str], str]] = set()

    default_seed = ("terrain_pipeline.py", "register_default_passes")
    if default_seed in registrar_to_targets or default_seed in registrar_calls:
        registrar_queue.append((default_seed, "default_registrar"))

    master = HANDLERS_DIR / "terrain_master_registrar.py"
    if master.exists():
        tree = parse_module(master)
        for node in ast.walk(tree):
            if not isinstance(node, ast.List):
                continue
            for elt in node.elts:
                if not isinstance(elt, ast.Tuple) or len(elt.elts) < 3:
                    continue
                module_hint = extract_constant_string(elt.elts[1])
                registrar_name = extract_constant_string(elt.elts[2])
                if not module_hint or not registrar_name:
                    continue
                reg_key = (f"{module_hint.split('.')[-1]}.py", registrar_name)
                if reg_key in registrar_to_targets or reg_key in registrar_calls:
                    registrar_queue.append((reg_key, "master_registrar"))

    while registrar_queue:
        reg_key, source_tag = registrar_queue.popleft()
        if (reg_key, source_tag) in registrar_seen:
            continue
        registrar_seen.add((reg_key, source_tag))
        exposure[reg_key].append(source_tag)
        target_tag = "default_pass" if source_tag == "default_registrar" else "master_bundle_pass"
        for target in registrar_to_targets.get(reg_key, []):
            exposure[target].append(target_tag)
        for callee in registrar_calls.get(reg_key, []):
            registrar_queue.append((callee, source_tag))
    return exposure


def bfs_runtime_reachability(
    defs: Iterable[CallableDef],
    edges: Iterable[CallEdge],
    exposure: DefaultDict[Tuple[str, str], List[str]],
) -> set[Tuple[str, str]]:
    outgoing: DefaultDict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
    for edge in edges:
        if edge.in_tests:
            continue
        if "/tests/" in edge.source_file:
            continue
        if edge.source[0].endswith(".py") and edge.target[0].endswith(".py"):
            outgoing[edge.source].append(edge.target)

    seeds = {
        key
        for key, tags in exposure.items()
        if {
            "command_handler",
            "command_handler_generated",
            "command_wrapper",
            "default_pass",
            "default_registrar",
            "master_bundle_pass",
            "master_registrar",
            "module_init",
        } & set(tags)
    }
    visited = set(seeds)
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        for nxt in outgoing.get(current, []):
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)
    return visited


def load_csv_rows(path: Path) -> List[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def group_grade_rows(rows: List[dict]) -> Tuple[DefaultDict[Tuple[str, str], List[dict]], DefaultDict[Tuple[str, str], List[dict]]]:
    exact: DefaultDict[Tuple[str, str], List[dict]] = defaultdict(list)
    normalized: DefaultDict[Tuple[str, str], List[dict]] = defaultdict(list)
    for row in rows:
        file_name = (row.get("File") or "").strip()
        function = (row.get("Function") or "").strip()
        if not file_name or not function:
            continue
        exact[(file_name, function)].append(row)
        normalized[(file_name, normalize_function_name(function))].append(row)
    return exact, normalized


def latest_grade(row: dict) -> str:
    for col in (
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
        raw = (row.get(col) or "").strip()
        if not raw:
            continue
        token = raw.split("|", 1)[0].strip()
        if token in {"A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "F", "N/A (SCOPE)", "SCOPE_EXEMPT"}:
            return token
    return ""


def summarize_sites(edges: List[CallEdge], limit: int = 5) -> str:
    if not edges:
        return ""
    seen = set()
    samples = []
    for edge in edges:
        key = (edge.source_file, edge.line)
        if key in seen:
            continue
        seen.add(key)
        samples.append(f"{edge.source_file}:{edge.line}")
        if len(samples) >= limit:
            break
    return "; ".join(samples)


def classify_status(
    record: CallableDef,
    direct_tags: List[str],
    runtime_reachable: bool,
    non_test_edges: List[CallEdge],
    test_edges: List[CallEdge],
) -> str:
    tags = set(direct_tags)
    if {
        "command_handler",
        "command_handler_generated",
        "command_wrapper",
        "default_pass",
        "default_registrar",
        "master_bundle_pass",
        "master_registrar",
        "module_init",
    } & tags:
        return "runtime_primary"
    if runtime_reachable:
        return "runtime_transitive"
    if "module_registrar" in tags:
        return "registrar_declared_only"
    cross_module = [edge for edge in non_test_edges if edge.source[0] != record.file]
    same_file = [edge for edge in non_test_edges if edge.source[0] == record.file]
    if cross_module:
        return "cross_module_helper"
    if same_file:
        return "module_local_helper"
    if test_edges:
        return "test_only_or_unwired"
    if record.name.startswith("register_"):
        return "uninvoked_registrar"
    if record.name.startswith("handle_"):
        return "public_handle_unwired"
    return "orphan_candidate"


def load_first_pass_status() -> Dict[Tuple[str, str], str]:
    if not FIRST_PASS_CSV.exists():
        return {}
    rows = load_csv_rows(FIRST_PASS_CSV)
    result = {}
    for row in rows:
        file_name = row.get("file", "")
        qname = row.get("qualified_name", "")
        if file_name and qname:
            result[(file_name, qname)] = row.get("status", "")
    return result


def write_csv(path: Path, fieldnames: List[str], rows: List[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: List[dict], changed_from_first: List[dict]) -> None:
    status_counts = Counter(row["master_status"] for row in rows)
    hard_risks = [
        row
        for row in rows
        if row["master_status"]
        in {"orphan_candidate", "registrar_declared_only", "uninvoked_registrar", "public_handle_unwired"}
    ]
    runtime_primary = [row for row in rows if row["master_status"] == "runtime_primary"]
    runtime_transitive = [row for row in rows if row["master_status"] == "runtime_transitive"]
    no_grade = [row for row in rows if row["csv_exact_match"] == "no" and row["csv_semantic_match"] == "no"]
    no_r9 = [row for row in rows if row["has_any_r9"] == "no"]
    lines = [
        "# Master Audit",
        "",
        "Audit date: 2026-04-19",
        "",
        "## Scope",
        "",
        "Second-pass audit over every live callable in `veilbreakers_terrain/handlers`, merged with runtime registration surfaces, static call-graph reachability, grade-sheet coverage, and strict-grade outputs.",
        "",
        "## Totals",
        "",
        f"- Live handler callables scanned: `{len(rows)}`",
        f"- Runtime-primary callables: `{len(runtime_primary)}`",
        f"- Runtime-transitive callables: `{len(runtime_transitive)}`",
        f"- Hard wiring risks after first-pass corroboration (`orphan`, `registrar-only`, `uninvoked registrar`, `public handle unwired`): `{len(hard_risks)}`",
        f"- Callables with no exact or semantic CSV match: `{len(no_grade)}`",
        f"- Callables with no matching R9 coverage: `{len(no_r9)}`",
        "",
        "Status distribution:",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- `{status}`: `{count}`")
    lines.extend(
        [
            "",
            "## What Changed From The First Pass",
            "",
            f"- Reclassified callables after runtime-reachability propagation: `{len(changed_from_first)}`",
            "- This second pass follows command-handler wrappers, default-pass registration, master bundle registration, and transitive helper reachability.",
            "- It also normalizes qualified vs unqualified CSV function names so semantic matches are no longer silently missed.",
            "",
            "## Strongest Verified Gaps",
            "",
        ]
    )
    top_hard = hard_risks[:25]
    if top_hard:
        for row in top_hard:
            lines.append(
                f"- `{row['file']}::{row['qualified_name']}` -> `{row['master_status']}` "
                f"(runtime=`{row['runtime_exposure']}`, callers=`{row['sample_non_test_callers'] or 'none'}`)"
            )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Runtime Surfaces Missing Adequate Grade Coverage",
            "",
        ]
    )
    runtime_ungraded = [row for row in runtime_primary if row["csv_exact_match"] == "no" and row["csv_semantic_match"] == "no"]
    for row in runtime_ungraded[:25]:
        lines.append(
            f"- `{row['file']}::{row['qualified_name']}` has runtime-primary exposure but no matching CSV row."
        )
    lines.extend(
        [
            "",
            "## Runtime-Reachable Callables Still Missing R9",
            "",
        ]
    )
    missing_r9_runtime = [row for row in rows if row["master_status"] in {"runtime_primary", "runtime_transitive"} and row["has_any_r9"] == "no"]
    for row in missing_r9_runtime[:25]:
        lines.append(f"- `{row['file']}::{row['qualified_name']}`")
    lines.extend(
        [
            "",
            "## Master Audit Interpretation",
            "",
            "- `runtime_primary`: directly on the shipped runtime surface via command handlers, default passes, or master bundle passes.",
            "- `runtime_transitive`: not itself a public surface, but statically reachable from a runtime-primary callable through non-test handler call edges.",
            "- `cross_module_helper`: used by other handler modules, but not currently proven reachable from runtime-primary surfaces.",
            "- `module_local_helper`: only used within its own module.",
            "- `registrar_declared_only`: appears in a module registrar, but that registrar is not proven loaded by the main runtime path.",
            "- `test_only_or_unwired`: only found in tests or weakly referenced outside runtime.",
            "- `orphan_candidate`: no discovered non-test caller and no runtime registration surface.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    defs, defs_by_file = collect_defs()
    edges = collect_edges(defs_by_file)
    exposure = collect_runtime_exposure(defs_by_file)
    runtime_reachable = bfs_runtime_reachability(defs, edges, exposure)

    incoming: DefaultDict[Tuple[str, str], List[CallEdge]] = defaultdict(list)
    for edge in edges:
        incoming[edge.target].append(edge)

    csv_rows = load_csv_rows(CSV_PATH)
    exact_rows, semantic_rows = group_grade_rows(csv_rows)
    strict_rows = load_csv_rows(STRICT_CSV) if STRICT_CSV.exists() else []
    strict_exact, strict_semantic = group_grade_rows(strict_rows)
    first_pass = load_first_pass_status()

    result_rows: List[dict] = []
    changed_from_first: List[dict] = []

    for record in sorted(defs, key=lambda item: (item.file, item.lineno, item.qualified_name)):
        exact_grade_rows = exact_rows.get((record.file, record.qualified_name), []) or exact_rows.get((record.file, record.name), [])
        semantic_grade_rows = semantic_rows.get((record.file, normalize_function_name(record.qualified_name)), [])
        exact_strict_rows = strict_exact.get((record.file, record.qualified_name), []) or strict_exact.get((record.file, record.name), [])
        semantic_strict_rows = strict_semantic.get((record.file, normalize_function_name(record.qualified_name)), [])

        inbound = incoming.get((record.file, record.qualified_name), []) + incoming.get((record.file, record.name), [])
        non_test = [edge for edge in inbound if not edge.in_tests]
        tests = [edge for edge in inbound if edge.in_tests]
        runtime_tags = sorted(set(exposure.get((record.file, record.qualified_name), []) + exposure.get((record.file, record.name), [])))
        previous = first_pass.get((record.file, record.qualified_name), "")
        status = classify_status(
            record,
            runtime_tags,
            (record.file, record.qualified_name) in runtime_reachable
            or (record.file, record.name) in runtime_reachable,
            non_test,
            tests,
        )
        if status in {
            "orphan_candidate",
            "registrar_declared_only",
            "uninvoked_registrar",
            "public_handle_unwired",
            "test_only_or_unwired",
        }:
            if previous == "runtime_primary":
                status = "runtime_primary"
                runtime_tags = sorted(set(runtime_tags + ["first_pass_runtime_primary"]))
            elif previous == "helper_reachable":
                status = "cross_module_helper"
            elif previous == "direct_test_covered":
                status = "test_only_or_unwired"
        if previous and previous != status:
            changed_from_first.append(
                {
                    "file": record.file,
                    "qualified_name": record.qualified_name,
                    "first_pass_status": previous,
                    "master_status": status,
                }
            )

        strict_row = exact_strict_rows[0] if exact_strict_rows else (semantic_strict_rows[0] if semantic_strict_rows else {})
        result_rows.append(
            {
                "file": record.file,
                "qualified_name": record.qualified_name,
                "function": record.name,
                "line": str(record.lineno),
                "kind": record.kind,
                "container_class": record.container,
                "runtime_exposure": ",".join(runtime_tags) if runtime_tags else "none",
                "runtime_reachable": "yes" if (record.file, record.qualified_name) in runtime_reachable or (record.file, record.name) in runtime_reachable else "no",
                "non_test_callers": str(len(non_test)),
                "test_callers": str(len(tests)),
                "sample_non_test_callers": summarize_sites(non_test),
                "sample_test_callers": summarize_sites(tests),
                "csv_exact_match": "yes" if exact_grade_rows else "no",
                "csv_semantic_match": "yes" if semantic_grade_rows else "no",
                "csv_semantic_match_count": str(len(semantic_grade_rows)),
                "has_any_r9": "yes" if any((row.get("R9 Phase7-14 Consensus") or "").strip() for row in semantic_grade_rows or exact_grade_rows) else "no",
                "claimed_grade": latest_grade((exact_grade_rows or semantic_grade_rows or [{}])[0]),
                "strict_current_grade": (strict_row.get("STRICT_CURRENT_GRADE") or ""),
                "strict_failure_flags": (strict_row.get("STRICT_FAILURE_FLAGS") or ""),
                "first_pass_status": previous,
                "master_status": status,
            }
        )

    fieldnames = [
        "file",
        "qualified_name",
        "function",
        "line",
        "kind",
        "container_class",
        "runtime_exposure",
        "runtime_reachable",
        "non_test_callers",
        "test_callers",
        "sample_non_test_callers",
        "sample_test_callers",
        "csv_exact_match",
        "csv_semantic_match",
        "csv_semantic_match_count",
        "has_any_r9",
        "claimed_grade",
        "strict_current_grade",
        "strict_failure_flags",
        "first_pass_status",
        "master_status",
    ]
    write_csv(OUTPUT_CSV, fieldnames, result_rows)
    write_markdown(OUTPUT_MD, result_rows, changed_from_first)
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {OUTPUT_MD}")
    print(f"Callables: {len(result_rows)}")
    print(f"Reclassified from first pass: {len(changed_from_first)}")


if __name__ == "__main__":
    main()
