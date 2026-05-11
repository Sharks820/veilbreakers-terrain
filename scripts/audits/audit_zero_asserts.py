"""AST scan: count test functions with no assert/Raise/pytest.raises across all test files."""
from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(r"C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\tests")


def has_assertion(node: ast.AST) -> bool:
    """Walk the function body looking for assert / Raise / pytest.raises / pytest.fail."""
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            return True
        if isinstance(child, ast.Raise):
            return True
        if isinstance(child, ast.With):
            # pytest.raises(...) context manager
            for item in child.items:
                ce = item.context_expr
                if isinstance(ce, ast.Call):
                    f = ce.func
                    if isinstance(f, ast.Attribute) and f.attr in ("raises", "warns"):
                        return True
                    if isinstance(f, ast.Name) and f.id in ("raises", "warns"):
                        return True
        if isinstance(child, ast.Call):
            f = child.func
            # pytest.fail(...) / pytest.skip(...) / pytest.xfail(...)
            if isinstance(f, ast.Attribute) and f.attr in ("fail", "skip", "xfail", "exit"):
                return True
            if isinstance(f, ast.Name) and f.id in ("fail",):
                return True
            # self.assertX(...) unittest style
            if isinstance(f, ast.Attribute) and f.attr.startswith("assert"):
                return True
    return False


def main() -> None:
    zero_assert: list[tuple[str, str, int]] = []
    test_fn_count = 0
    test_file_count = 0
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        test_file_count += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("test_"):
                    continue
                test_fn_count += 1
                if not has_assertion(node):
                    rel = path.relative_to(TESTS_DIR.parent.parent)
                    zero_assert.append((str(rel), node.name, node.lineno))

    print(f"Total test files scanned: {test_file_count}")
    print(f"Total test functions:     {test_fn_count}")
    print(f"Zero-assert test count:   {len(zero_assert)}")
    print()
    if zero_assert:
        # Group by file
        by_file: dict[str, list[tuple[str, int]]] = {}
        for f, name, line in zero_assert:
            by_file.setdefault(f, []).append((name, line))
        print("Zero-assert tests by file:")
        for f in sorted(by_file):
            print(f"  {f}  ({len(by_file[f])} tests)")
            for name, line in by_file[f][:5]:
                print(f"    L{line}: {name}")
            if len(by_file[f]) > 5:
                print(f"    ... +{len(by_file[f]) - 5} more")


if __name__ == "__main__":
    main()
