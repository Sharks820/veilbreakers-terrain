"""
Coverage gap analysis: finds every function in handlers/*.py not in GRADES_VERIFIED.csv
"""
import ast
import csv
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HANDLERS_DIR = REPO_ROOT / "veilbreakers_terrain" / "handlers"
CSV_PATH = REPO_ROOT / "docs" / "aaa-audit" / "GRADES_VERIFIED.csv"

# ── 1. Parse CSV ─────────────────────────────────────────────────────────────
csv_entries = set()
csv_rows = []
with open(CSV_PATH, newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        file_val = (row.get('File') or '').strip()
        func_val = (row.get('Function') or '').strip()
        if file_val and func_val:
            csv_entries.add((file_val, func_val))
            csv_rows.append((file_val, func_val))

print(f"CSV rows loaded: {len(csv_rows)}")
print(f"Unique (file,func) pairs in CSV: {len(csv_entries)}")

# ── 2. Parse Python files ────────────────────────────────────────────────────
def extract_functions(filepath):
    """Extract all function defs (including nested, methods) with line numbers."""
    funcs = []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        source = f.read()
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"  SYNTAX ERROR in {filepath.name}: {e}", file=sys.stderr)
        return funcs
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            funcs.append((node.name, node.lineno))
    return funcs

all_py_files = sorted(
    f for f in HANDLERS_DIR.glob("*.py")
    if f.name != '__init__.py' and '__pycache__' not in str(f)
)

code_entries = {}  # (file, func) -> line
files_parsed = 0
for py_file in all_py_files:
    funcs = extract_functions(py_file)
    files_parsed += 1
    for func_name, lineno in funcs:
        code_entries[(py_file.name, func_name)] = lineno

print(f"Python files parsed: {files_parsed}")
print(f"Total function defs in code: {len(code_entries)}")

# ── 3. Gaps ──────────────────────────────────────────────────────────────────
in_code_not_csv = sorted(
    [(f, fn, ln) for (f,fn),ln in code_entries.items() if (f,fn) not in csv_entries],
    key=lambda x: (x[0], x[2])
)
in_csv_not_code = sorted(
    [(f, fn) for (f,fn) in csv_entries if (f,fn) not in code_entries]
)

print(f"\nFunctions in CODE but NOT in CSV: {len(in_code_not_csv)}")
print(f"Functions in CSV but NOT in CODE (stale): {len(in_csv_not_code)}")

# ── 4. Print gap functions grouped by file ───────────────────────────────────
print("\n" + "="*80)
print("=== CODE-NOT-CSV (missing from audit) ===")
print("="*80)
cur_file = None
for file, func, line in in_code_not_csv:
    if file != cur_file:
        print(f"\n  --- {file} ---")
        cur_file = file
    print(f"    L{line:5d}  {func}")

print("\n" + "="*80)
print("=== CSV-NOT-CODE (stale entries) ===")
print("="*80)
cur_file = None
for file, func in in_csv_not_code:
    if file != cur_file:
        print(f"\n  --- {file} ---")
        cur_file = file
    print(f"    {func}")

# ── 5. Special file inventories ──────────────────────────────────────────────
SPECIAL = ['terrain_quixel_ingest.py', 'terrain_vegetation_depth.py', 'terrain_palette_extract.py']
for special in SPECIAL:
    print(f"\n{'='*80}")
    print(f"=== FULL INVENTORY: {special} ===")
    print(f"{'='*80}")
    path = HANDLERS_DIR / special
    if path.exists():
        funcs = extract_functions(path)
        if not funcs:
            print("  (no functions found)")
        for fn, ln in sorted(funcs, key=lambda x: x[1]):
            status = "IN_CSV" if (special, fn) in csv_entries else "MISSING"
            print(f"  L{ln:5d}  {fn}  [{status}]")
    else:
        print("  FILE NOT FOUND")

# ── 6. File-level summary: which files have uncovered functions ──────────────
print(f"\n{'='*80}")
print("=== FILES WITH UNCOVERED FUNCTIONS (count) ===")
print(f"{'='*80}")
from collections import Counter
file_counts = Counter(f for f,_,_ in in_code_not_csv)
for fname, count in sorted(file_counts.items(), key=lambda x: -x[1]):
    total_in_file = sum(1 for (ff,fn) in code_entries if ff==fname)
    print(f"  {fname}: {count} uncovered / {total_in_file} total")

print("\nDone.")
