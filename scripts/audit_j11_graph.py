"""J11 import graph audit. Output: dead modules, zombie modules."""
import os, re

ROOT = os.path.dirname(os.path.abspath(__file__))
handlers_dir = os.path.join(ROOT, 'veilbreakers_terrain', 'handlers')
pkg_dir = os.path.join(ROOT, 'veilbreakers_terrain')

handler_files = sorted([f[:-3] for f in os.listdir(handlers_dir) if f.endswith('.py') and f != '__init__.py'])
print(f'Total handler files: {len(handler_files)}')

# Find all 'from .X' or 'from veilbreakers_terrain.handlers.X' imports across handler files
imports = {}
for h in handler_files:
    path = os.path.join(handlers_dir, h + '.py')
    with open(path, encoding='utf-8') as f:
        content = f.read()
    refs = set()
    for m in re.finditer(r'from\s+\.([a-zA-Z_]\w*)\s+import', content):
        refs.add(m.group(1))
    for m in re.finditer(r'from\s+veilbreakers_terrain\.handlers\.([a-zA-Z_]\w*)\s+import', content):
        refs.add(m.group(1))
    for m in re.finditer(r'import\s+veilbreakers_terrain\.handlers\.([a-zA-Z_]\w*)', content):
        refs.add(m.group(1))
    for m in re.finditer(r"import_module\(['\"][^'\"]*handlers\.([a-zA-Z_]\w*)['\"]", content):
        refs.add(m.group(1))
    # `from . import (a, b, c)` or `from . import a, b`
    for m in re.finditer(r'from\s+\.\s+import\s+\(([^)]+)\)', content):
        for n in re.split(r'[,\s]+', m.group(1)):
            n = n.strip().rstrip(',')
            if n and re.match(r'^[a-zA-Z_]\w*$', n):
                refs.add(n)
    for m in re.finditer(r'from\s+\.\s+import\s+([a-zA-Z_][\w,\s]+)$', content, re.MULTILINE):
        for n in re.split(r'[,\s]+', m.group(1)):
            n = n.strip()
            if n and re.match(r'^[a-zA-Z_]\w*$', n):
                refs.add(n)
    imports[h] = refs

with open(os.path.join(handlers_dir, '__init__.py'), encoding='utf-8') as f:
    init_content = f.read()
init_refs = set()
for m in re.finditer(r'\{_pkg\}\.([a-zA-Z_]\w*)', init_content):
    init_refs.add(m.group(1))
for m in re.finditer(r'\{_pkg2?\}\.([a-zA-Z_]\w*)', init_content):
    init_refs.add(m.group(1))
for m in re.finditer(r'from\s+\.([a-zA-Z_]\w*)\s+import', init_content):
    init_refs.add(m.group(1))

with open(os.path.join(handlers_dir, 'terrain_master_registrar.py'), encoding='utf-8') as f:
    mr_content = f.read()
for m in re.finditer(r'\{package_root\}\.([a-zA-Z_]\w*)', mr_content):
    init_refs.add(m.group(1))
for m in re.finditer(r'from\s+\.([a-zA-Z_]\w*)\s+import', mr_content):
    init_refs.add(m.group(1))

# Also include refs from veilbreakers_terrain/__init__.py and socket_server.py
for top in ['__init__.py', 'socket_server.py']:
    p = os.path.join(pkg_dir, top)
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            c = f.read()
        for m in re.finditer(r'from\s+veilbreakers_terrain\.handlers\.([a-zA-Z_]\w*)\s+import', c):
            init_refs.add(m.group(1))
        for m in re.finditer(r'from\s+\.handlers\.([a-zA-Z_]\w*)\s+import', c):
            init_refs.add(m.group(1))

print(f'Direct production entry-point refs: {len(init_refs)}')
print(sorted(init_refs))

# BFS
reachable = set()
frontier = set(init_refs) | {'terrain_master_registrar'}
while frontier:
    n = frontier.pop()
    if n in reachable:
        continue
    reachable.add(n)
    if n in imports:
        frontier |= imports[n]

print(f'\nReachable: {len(reachable)} of {len(handler_files)}')

all_handlers = set(handler_files)
dead = all_handlers - reachable
print(f'\n=== DEAD MODULES ({len(dead)}) ===')
for d in sorted(dead):
    print(f'  {d}')

# Check who is imported by tests only
tests_dir = os.path.join(ROOT, 'veilbreakers_terrain', 'tests')
test_imports = set()
if os.path.isdir(tests_dir):
    for root_, _, files in os.walk(tests_dir):
        for f in files:
            if not f.endswith('.py'):
                continue
            p = os.path.join(root_, f)
            try:
                with open(p, encoding='utf-8') as fh:
                    c = fh.read()
            except Exception:
                continue
            for m in re.finditer(r'from\s+veilbreakers_terrain\.handlers\.([a-zA-Z_]\w*)\s+import', c):
                test_imports.add(m.group(1))
            for m in re.finditer(r'import\s+veilbreakers_terrain\.handlers\.([a-zA-Z_]\w*)', c):
                test_imports.add(m.group(1))

test_only = (test_imports & all_handlers) - reachable
print(f'\n=== TEST-ONLY MODULES ({len(test_only)}) (imported by tests but unreachable from prod) ===')
for d in sorted(test_only):
    print(f'  {d}')

unimported = dead - test_imports
print(f'\n=== ZERO-IMPORT MODULES (no test, no prod) ({len(unimported)}) ===')
for d in sorted(unimported):
    print(f'  {d}')
