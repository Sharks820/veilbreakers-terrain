"""Scan every handler callable for reachability, wiring, and grade-sheet coverage.

Outputs:
- output/spreadsheet/CALLABLE_WIRING_AUDIT_2026_04_19.csv
- output/spreadsheet/CALLABLE_WIRING_SUMMARY_2026_04_19.md

This is a static code audit. It does not prove semantic correctness, but it
does answer the key structural questions for each callable:
- does it exist in live code?
- is it covered by the grade sheet?
- is it called anywhere outside tests?
- is it exposed through command handlers or pass registration?
- does it look orphaned, test-only, module-private, or runtime-facing?
"""

from __future__ import annotations

import ast
import csv
import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
HANDLERS_DIR = REPO_ROOT / "veilbreakers_terrain" / "handlers"
TESTS_DIR = REPO_ROOT / "veilbreakers_terrain" / "tests"
CSV_PATH = REPO_ROOT / "docs" / "aaa-audit" / "GRADES_VERIFIED.csv"
OUTPUT_DIR = REPO_ROOT / "output" / "spreadsheet"
DATE_TAG = "2026_04_19"
OUTPUT_CSV = OUTPUT_DIR / f"CALLABLE_WIRING_AUDIT_{DATE_TAG}.csv"
OUTPUT_SUMMARY = OUTPUT_DIR / f"CALLABLE_WIRING_SUMMARY_{DATE_TAG}.md"


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


@dataclass(frozen=True)
class CallSite:
    file: str
    line: int
    mode: str


class CallableVisitor(ast.NodeVisitor):
    def __init__(self, file_name: str) -> None:
        self.file_name = file_name
        self.class_stack: List[str] = []
        self.records: List[CallableDef] = []

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


class UsageVisitor(ast.NodeVisitor):
    def __init__(self, file_name: str) -> None:
        self.file_name = file_name
        self.name_calls: List[Tuple[str, CallSite]] = []
        self.attr_calls: List[Tuple[str, CallSite]] = []
        self.attr_reads: List[Tuple[str, CallSite]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Name):
            self.name_calls.append((node.func.id, CallSite(self.file_name, node.lineno, "direct_call")))
        elif isinstance(node.func, ast.Attribute):
            self.attr_calls.append((node.func.attr, CallSite(self.file_name, node.lineno, "attr_call")))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        self.attr_reads.append((node.attr, CallSite(self.file_name, node.lineno, "attr_read")))
        self.generic_visit(node)


class ResolvedUsageVisitor(ast.NodeVisitor):
    def __init__(
        self,
        file_name: str,
        defs_by_file: Dict[str, List[CallableDef]],
        alias_functions: Dict[str, Tuple[str, str]],
        alias_modules: Dict[str, str],
    ) -> None:
        self.file_name = file_name
        self.defs_by_file = defs_by_file
        self.alias_functions = alias_functions
        self.alias_modules = alias_modules
        self.class_stack: List[str] = []
        self.records: List[Tuple[Tuple[str, str], CallSite]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        target = self._resolve_call_target(node.func)
        if target:
            self.records.append((target, CallSite(self.file_name, node.lineno, "resolved_call")))
        self.generic_visit(node)

    def _resolve_call_target(self, node: ast.AST) -> Optional[Tuple[str, str]]:
        if isinstance(node, ast.Name):
            if node.id in self.alias_functions:
                return self.alias_functions[node.id]
            for record in self.defs_by_file.get(self.file_name, []):
                if record.name == node.id or record.qualified_name == node.id:
                    return (self.file_name, record.qualified_name)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                base = node.value.id
                if base in {"self", "cls"} and self.class_stack:
                    qname = f"{self.class_stack[-1]}.{node.attr}"
                    for record in self.defs_by_file.get(self.file_name, []):
                        if record.qualified_name == qname:
                            return (self.file_name, qname)
                if base in self.alias_modules:
                    target_file = self.alias_modules[base]
                    for record in self.defs_by_file.get(target_file, []):
                        if record.name == node.attr or record.qualified_name == node.attr:
                            return (target_file, record.qualified_name)
            for record in self.defs_by_file.get(self.file_name, []):
                if record.name == node.attr or record.qualified_name == node.attr:
                    return (self.file_name, record.qualified_name)
        return None


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_module(path: Path) -> ast.AST:
    return ast.parse(read_text(path), filename=str(path))


def to_handler_file(module_name: str) -> Optional[str]:
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
        return Path(tail.replace(".", "/") + ".py").name
    if module_name.startswith("veilbreakers_terrain.handlers.") or module_name.startswith("blender_addon.handlers."):
        tail = module_name.split(".")[-1]
        return "__init__.py" if tail == "handlers" else f"{tail}.py"
    return f"{module_name.split('.')[-1]}.py"


def extract_constant_string(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: List[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
        return "".join(parts)
    return ""


def collect_defs() -> Tuple[List[CallableDef], Dict[str, List[CallableDef]]]:
    records: List[CallableDef] = []
    by_file: Dict[str, List[CallableDef]] = defaultdict(list)
    for path in sorted(HANDLERS_DIR.glob("*.py")):
        visitor = CallableVisitor(path.name)
        visitor.visit(parse_module(path))
        records.extend(visitor.records)
        by_file[path.name].extend(visitor.records)
    return records, by_file


def collect_usages() -> Tuple[DefaultDict[str, List[CallSite]], DefaultDict[str, List[CallSite]], DefaultDict[str, List[CallSite]]]:
    direct: DefaultDict[str, List[CallSite]] = defaultdict(list)
    attr_call: DefaultDict[str, List[CallSite]] = defaultdict(list)
    attr_read: DefaultDict[str, List[CallSite]] = defaultdict(list)
    for path in sorted((REPO_ROOT / "veilbreakers_terrain").rglob("*.py")):
        file_name = path.relative_to(REPO_ROOT).as_posix()
        visitor = UsageVisitor(file_name)
        visitor.visit(parse_module(path))
        for name, site in visitor.name_calls:
            direct[name].append(site)
        for name, site in visitor.attr_calls:
            attr_call[name].append(site)
        for name, site in visitor.attr_reads:
            attr_read[name].append(site)
    return direct, attr_call, attr_read


def collect_resolved_usages(
    defs_by_file: Dict[str, List[CallableDef]],
) -> DefaultDict[Tuple[str, str], List[CallSite]]:
    resolved: DefaultDict[Tuple[str, str], List[CallSite]] = defaultdict(list)
    for path in sorted((REPO_ROOT / "veilbreakers_terrain").rglob("*.py")):
        file_name = path.relative_to(REPO_ROOT).as_posix()
        tree = parse_module(path)
        aliases = import_alias_map(tree)
        module_aliases = import_module_alias_map(tree)
        visitor = ResolvedUsageVisitor(
            file_name=file_name.split("/")[-1] if "/handlers/" in file_name else file_name,
            defs_by_file=defs_by_file,
            alias_functions=aliases,
            alias_modules=module_aliases,
        )
        visitor.visit(tree)
        for target, site in visitor.records:
            resolved[target].append(site)
    return resolved


def import_alias_map(tree: ast.AST) -> Dict[str, Tuple[str, str]]:
    aliases: Dict[str, Tuple[str, str]] = {}

    def bind_alias(local_name: str, target_file: str, symbol: str) -> None:
        aliases[local_name] = (target_file, symbol)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module is None and node.level:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    target_file = to_handler_file(alias.name)
                    if target_file:
                        continue
                continue
            target_file = to_handler_file(node.module or "")
            if not target_file:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                if not ((target_file == "__init__.py" and alias.name == "handlers") or target_file == f"{alias.name}.py"):
                    bind_alias(local_name, target_file, alias.name)

    return aliases


def import_module_alias_map(tree: ast.AST) -> Dict[str, str]:
    module_aliases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module is None and node.level:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    target_file = to_handler_file(alias.name)
                    if target_file:
                        module_aliases[alias.asname or alias.name] = target_file
                continue
            target_file = to_handler_file(node.module or "")
            if not target_file:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                if (target_file == "__init__.py" and alias.name == "handlers") or target_file == f"{alias.name}.py":
                    module_aliases[local_name] = target_file
        elif isinstance(node, ast.Import):
            for alias in node.names:
                target_file = to_handler_file(alias.name)
                if target_file:
                    module_aliases[alias.asname or alias.name.split(".")[-1]] = target_file
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if isinstance(node.value, ast.Call) and extract_name(node.value.func) == "import_module" and node.value.args:
                    module_hint = extract_constant_string(node.value.args[0])
                    target_file = to_handler_file(module_hint) or Path(module_hint.lstrip(".").split(".")[-1] + ".py").name
                    module_aliases[target.id] = target_file
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Attribute):
            continue
        if not isinstance(node.value.value, ast.Name):
            continue
        base = node.value.value.id
        if base not in module_aliases:
            continue
        target_file = module_aliases[base]
        for target in node.targets:
            if isinstance(target, ast.Name):
                module_aliases[target.id] = target_file
    return module_aliases


def extract_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def resolve_symbol(file_name: str, name: str, alias_map: Dict[str, Tuple[str, str]], defs_by_file: Dict[str, List[CallableDef]]) -> Optional[Tuple[str, str]]:
    if name in alias_map:
        return alias_map[name]
    for record in defs_by_file.get(file_name, []):
        if record.name == name or record.qualified_name == name:
            return (file_name, record.qualified_name)
    return None


def resolve_call_target(
    file_name: str,
    node: ast.AST,
    alias_map: Dict[str, Tuple[str, str]],
    module_aliases: Dict[str, str],
    defs_by_file: Dict[str, List[CallableDef]],
) -> Optional[Tuple[str, str]]:
    if isinstance(node, ast.Name):
        return resolve_symbol(file_name, node.id, alias_map, defs_by_file)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        base = node.value.id
        if base in module_aliases:
            return resolve_symbol(module_aliases[base], node.attr, {}, defs_by_file)
        return resolve_symbol(file_name, node.attr, alias_map, defs_by_file)
    return resolve_symbol(file_name, extract_name(node) or "", alias_map, defs_by_file)


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


def collect_runtime_exposure(defs_by_file: Dict[str, List[CallableDef]]) -> DefaultDict[Tuple[str, str], List[str]]:
    exposure: DefaultDict[Tuple[str, str], List[str]] = defaultdict(list)
    registrar_targets: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
    registrar_calls: DefaultDict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)

    # First pass: record which pass functions each registrar adds, plus any
    # sub-registrar calls so bundle-transitive registration is not missed.
    for path in sorted(HANDLERS_DIR.glob("*.py")):
        tree = parse_module(path)
        aliases = import_alias_map(tree)
        module_aliases = import_module_alias_map(tree)
        file_name = path.name
        for node in ast.walk(tree):
            is_registrar = (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (node.name.startswith("register_") or (file_name == "terrain_pipeline.py" and node.name == "register_default_passes"))
            )
            if is_registrar:
                targets: List[Tuple[str, str]] = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and extract_name(child.func) == "PassDefinition":
                        target = None
                        for kw in child.keywords:
                            if kw.arg == "func":
                                target = resolve_call_target(file_name, kw.value, aliases, module_aliases, defs_by_file)
                                break
                        if target is None and child.args:
                            target = resolve_call_target(file_name, child.args[0], aliases, module_aliases, defs_by_file)
                        if target:
                            targets.append(target)
                        continue
                    if isinstance(child, ast.Call):
                        callee = resolve_call_target(file_name, child.func, aliases, module_aliases, defs_by_file)
                        if callee and (callee[1].startswith("register_") or callee == ("terrain_pipeline.py", "register_default_passes")):
                            registrar_calls[(file_name, node.name)].append(callee)
                registrar_targets[(file_name, node.name)] = targets

    # Second pass: detect runtime-exposed handlers and registrars.
    for path in sorted(HANDLERS_DIR.glob("*.py")):
        tree = parse_module(path)
        aliases = import_alias_map(tree)
        file_name = path.name
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_name = extract_name(node.func)
                if file_name == "__init__.py" and call_name == "_try_register" and len(node.args) >= 3:
                    module_hint = extract_constant_string(node.args[1])
                    fn_name = extract_constant_string(node.args[2])
                    target_file = ""
                    if module_hint:
                        target_file = f"{module_hint.split('.')[-1]}.py"
                    if target_file and fn_name:
                        target = (target_file, fn_name)
                    else:
                        target = None
                    if target:
                        exposure[target].append("command_handler")
                elif call_name == "_try_register" and len(node.args) >= 2:
                    target = resolve_symbol(file_name, extract_name(node.args[1]) or "", aliases, defs_by_file)
                    if target:
                        exposure[target].append("command_handler")
                if call_name == "PassDefinition":
                    target = None
                    for kw in node.keywords:
                        if kw.arg == "func":
                            target = resolve_call_target(file_name, kw.value, aliases, import_module_alias_map(tree), defs_by_file)
                            break
                    if target is None and node.args:
                        target = resolve_call_target(file_name, node.args[0], aliases, import_module_alias_map(tree), defs_by_file)
                    if target:
                        if file_name == "terrain_pipeline.py":
                            exposure[target].append("default_pass")
                        elif file_name == "terrain_master_registrar.py":
                            exposure[target].append("master_bundle_pass")
                        else:
                            exposure[target].append("module_registrar")
            elif isinstance(node, ast.Assign):
                for target_node in node.targets:
                    if (
                        isinstance(target_node, ast.Subscript)
                        and isinstance(target_node.value, ast.Name)
                        and target_node.value.id in {"COMMAND_HANDLERS", "handlers"}
                    ):
                        if isinstance(node.value, ast.Call):
                            factory_name = extract_name(node.value.func) or ""
                            if file_name == "__init__.py" and factory_name == "_wrap" and node.value.args:
                                fn_name = extract_constant_string(node.value.args[0])
                                if fn_name:
                                    exposure[("blender_capability_bridge.py", fn_name)].append("command_handler")
                                    continue
                            if factory_name == "_fail_closed":
                                for record in defs_by_file.get(file_name, []):
                                    if record.name in {"_fail_closed", "_handler"}:
                                        exposure[(file_name, record.qualified_name)].append("command_handler")
                                continue
                            if factory_name == "_make_generator_handler":
                                for record in defs_by_file.get(file_name, []):
                                    if record.name in {"_make_generator_handler", "_h"}:
                                        exposure[(file_name, record.qualified_name)].append("command_handler")
                                continue
                        target_name = extract_name(node.value) or ""
                        target = resolve_symbol(file_name, target_name, aliases, defs_by_file)
                        if target:
                            exposure[target].append("command_handler")

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

    # Third pass: terrain_master_registrar loads module registrars by string,
    # so propagate through the full registrar graph, not just the first hop.
    master_registrar = HANDLERS_DIR / "terrain_master_registrar.py"
    registrar_queue: deque[Tuple[Tuple[str, str], str]] = deque()
    registrar_seen: set[Tuple[Tuple[str, str], str]] = set()
    default_seed = ("terrain_pipeline.py", "register_default_passes")
    if default_seed in registrar_targets or default_seed in registrar_calls:
        registrar_queue.append((default_seed, "default_registrar"))
    if master_registrar.exists():
        tree = parse_module(master_registrar)
        for node in ast.walk(tree):
            if isinstance(node, ast.List):
                for elt in node.elts:
                    if not isinstance(elt, ast.Tuple) or len(elt.elts) < 3:
                        continue
                    module_hint = extract_constant_string(elt.elts[1])
                    registrar_name = extract_constant_string(elt.elts[2])
                    if not registrar_name:
                        continue
                    registrar_file = f"{module_hint.split('.')[-1]}.py" if module_hint else ""
                    if registrar_file:
                        reg_key = (registrar_file, registrar_name)
                        if reg_key in registrar_targets or reg_key in registrar_calls:
                            registrar_queue.append((reg_key, "master_bundle_registrar"))
    while registrar_queue:
        reg_key, source_tag = registrar_queue.popleft()
        if (reg_key, source_tag) in registrar_seen:
            continue
        registrar_seen.add((reg_key, source_tag))
        exposure[reg_key].append(source_tag)
        target_tag = "default_pass" if source_tag == "default_registrar" else "master_bundle_pass"
        for target in registrar_targets.get(reg_key, []):
            exposure[target].append(target_tag)
        for callee in registrar_calls.get(reg_key, []):
            registrar_queue.append((callee, source_tag))
    return exposure


def load_grade_index() -> DefaultDict[Tuple[str, str], List[dict]]:
    index: DefaultDict[Tuple[str, str], List[dict]] = defaultdict(list)
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            key = ((row.get("File") or "").strip(), (row.get("Function") or "").strip())
            index[key].append(row)
    return index


def latest_r9(row: dict) -> str:
    return (row.get("R9 Phase7-14 Consensus") or "").strip()


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


def split_sites(sites: Iterable[CallSite]) -> Tuple[List[CallSite], List[CallSite]]:
    non_test: List[CallSite] = []
    test: List[CallSite] = []
    for site in sites:
        if "/tests/" in site.file or site.file.startswith("veilbreakers_terrain/tests/"):
            test.append(site)
        else:
            non_test.append(site)
    return non_test, test


def sample_sites(sites: List[CallSite], limit: int = 4) -> str:
    if not sites:
        return ""
    unique = []
    seen = set()
    for site in sites:
        key = (site.file, site.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f"{site.file}:{site.line}")
        if len(unique) >= limit:
            break
    return "; ".join(unique)


def classify_status(
    callable_def: CallableDef,
    exposure_tags: List[str],
    direct_non_test: List[CallSite],
    attr_non_test: List[CallSite],
    test_sites: List[CallSite],
    grade_rows: List[dict],
) -> str:
    if {
        "command_handler",
        "command_handler_generated",
        "default_pass",
        "default_registrar",
        "master_bundle_pass",
    } & set(exposure_tags):
        return "runtime_primary"
    if "master_bundle_registrar" in exposure_tags:
        return "runtime_primary"
    if direct_non_test or attr_non_test:
        return "helper_reachable"
    if "module_registrar" in exposure_tags:
        return "registrar_declared_only"
    if test_sites:
        return "test_only_or_unwired"
    if callable_def.name.startswith("register_"):
        return "uninvoked_registrar"
    return "orphan_candidate"


def write_csv(path: Path, fieldnames: List[str], rows: List[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: List[dict], total_defs: int) -> None:
    status_counts = Counter(row["status"] for row in rows)
    file_risk = Counter()
    uncovered = 0
    no_r9 = 0
    for row in rows:
        if row["status"] in {"orphan_candidate", "uninvoked_registrar", "registrar_declared_only", "test_only_or_unwired"}:
            file_risk[row["file"]] += 1
        if row["csv_rows"] == "0":
            uncovered += 1
        if row["has_r9"] == "no":
            no_r9 += 1
    top_risks = file_risk.most_common(20)
    lines = [
        "# Callable Wiring Summary",
        "",
        "Audit date: 2026-04-19",
        f"Input handlers directory: `{HANDLERS_DIR}`",
        f"Input grade sheet: `{CSV_PATH}`",
        f"Output CSV: `{OUTPUT_CSV}`",
        "",
        "## Totals",
        "",
        f"- Live handler callables scanned: `{total_defs}`",
        f"- Callables missing from the grade sheet: `{uncovered}`",
        f"- Callables without any R9 grade attached via matching CSV row: `{no_r9}`",
        "",
        "Status distribution:",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- `{status}`: `{count}`")
    lines.extend(
        [
            "",
            "## Highest-Risk Files",
            "",
        ]
    )
    for file_name, count in top_risks:
        lines.append(f"- `{file_name}`: `{count}` callable(s) flagged as orphaned, registrar-only, or test-only")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `runtime_primary`: exposed via command handlers or loaded pass registration.",
            "- `helper_reachable`: not a primary surface, but called from non-test code.",
            "- `registrar_declared_only`: function appears in a module-local registrar, but the scan found no evidence that the registrar itself is loaded by the primary runtime surfaces.",
            "- `uninvoked_registrar`: registration helper exists but has no discovered non-test caller.",
            "- `test_only_or_unwired`: only referenced by tests or not clearly used by runtime.",
            "- `orphan_candidate`: no discovered runtime exposure, non-test callsite, or test caller.",
            "",
            "This is a static scan. False positives are possible where dispatch is fully dynamic, but the flagged rows are exactly the set that need human review before claiming there are no wiring gaps.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    defs, defs_by_file = collect_defs()
    direct_calls, attr_calls, attr_reads = collect_usages()
    resolved_calls = collect_resolved_usages(defs_by_file)
    exposure = collect_runtime_exposure(defs_by_file)
    grade_index = load_grade_index()

    rows: List[dict] = []
    for record in sorted(defs, key=lambda item: (item.file, item.lineno, item.qualified_name)):
        key = (record.file, record.name)
        grade_rows = grade_index.get(key, [])
        name_sites = direct_calls.get(record.name, [])
        attr_sites = attr_calls.get(record.name, [])
        read_sites = attr_reads.get(record.name, [])
        resolved_sites = resolved_calls.get((record.file, record.qualified_name), [])
        direct_non_test, direct_test = split_sites(name_sites)
        attr_non_test, attr_test = split_sites(attr_sites)
        read_non_test, read_test = split_sites(read_sites)
        resolved_non_test, resolved_test = split_sites(resolved_sites)
        exposure_tags = sorted(
            set(exposure.get((record.file, record.qualified_name), []))
            | set(exposure.get((record.file, record.name), []))
        )
        status = classify_status(
            record,
            exposure_tags,
            direct_non_test + resolved_non_test,
            attr_non_test,
            direct_test + attr_test + read_test + resolved_test,
            grade_rows,
        )
        csv_grade = latest_grade(grade_rows[0]) if grade_rows else ""
        r9_value = latest_r9(grade_rows[0]) if grade_rows else ""
        row = {
            "file": record.file,
            "qualified_name": record.qualified_name,
            "function": record.name,
            "line": str(record.lineno),
            "kind": record.kind,
            "container_class": record.container,
            "csv_rows": str(len(grade_rows)),
            "csv_has_match": "yes" if grade_rows else "no",
            "has_r9": "yes" if r9_value else "no",
            "claimed_grade": csv_grade,
            "r9_value": r9_value,
            "runtime_exposure": ",".join(exposure_tags) if exposure_tags else "none",
            "non_test_direct_calls": str(len(direct_non_test)),
            "non_test_attr_calls": str(len(attr_non_test)),
            "non_test_attr_reads": str(len(read_non_test)),
            "test_direct_calls": str(len(direct_test)),
            "test_attr_calls": str(len(attr_test)),
            "test_attr_reads": str(len(read_test)),
            "sample_non_test_callers": sample_sites(direct_non_test + resolved_non_test + attr_non_test + read_non_test),
            "sample_test_callers": sample_sites(direct_test + resolved_test + attr_test + read_test),
            "status": status,
        }
        rows.append(row)

    fieldnames = [
        "file",
        "qualified_name",
        "function",
        "line",
        "kind",
        "container_class",
        "csv_rows",
        "csv_has_match",
        "has_r9",
        "claimed_grade",
        "r9_value",
        "runtime_exposure",
        "non_test_direct_calls",
        "non_test_attr_calls",
        "non_test_attr_reads",
        "test_direct_calls",
        "test_attr_calls",
        "test_attr_reads",
        "sample_non_test_callers",
        "sample_test_callers",
        "status",
    ]
    write_csv(OUTPUT_CSV, fieldnames, rows)
    write_summary(OUTPUT_SUMMARY, rows, len(defs))
    print(json.dumps({"rows": len(rows), "csv": str(OUTPUT_CSV), "summary": str(OUTPUT_SUMMARY)}, indent=2))


if __name__ == "__main__":
    main()
