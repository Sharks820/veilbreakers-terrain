"""
test_hotfix_7n_unity_path_traversal_guard.py

Python-side static regression tests for the CWE-22 path-traversal containment
guard added to VbTerrainImporter.cs (Verifier A 2026-05-21 #17 / hotfix-7n).

The tests parse the C# source and assert:
  1. SafePathCombine helper is defined in the class.
  2. SecurityException is thrown from SafePathCombine.
  3. Every Path.Combine call-site that originates from a manifest-controlled
     (bundleDirectory-relative) path has been migrated to SafePathCombine.
     "Bare" Path.Combine(bundleDirectory, ...) calls are forbidden.
  4. No Path.GetFullPath(Path.Combine(...)) pattern exists around bundle-dir
     paths without a SafePathCombine wrapper.
"""

from __future__ import annotations

import pathlib
import re

# ---------------------------------------------------------------------------
# Resolve the C# source under test
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_CS_PATH = _REPO_ROOT / "unity_plugin" / "Editor" / "VbTerrainImporter.cs"


def _read_source() -> str:
    if not _CS_PATH.exists():
        raise FileNotFoundError(
            f"VbTerrainImporter.cs not found at expected path: {_CS_PATH}"
        )
    return _CS_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: SafePathCombine helper exists
# ---------------------------------------------------------------------------

def test_safe_path_combine_helper_exists() -> None:
    """SafePathCombine must be defined as a static method in the class."""
    source = _read_source()
    assert "private static string SafePathCombine(" in source, (
        "VbTerrainImporter.cs is missing the SafePathCombine helper. "
        "Add the CWE-22 containment helper per hotfix-7n."
    )


# ---------------------------------------------------------------------------
# Test 2: SecurityException is thrown from SafePathCombine
# ---------------------------------------------------------------------------

def test_safe_path_combine_throws_security_exception() -> None:
    """SafePathCombine must throw SecurityException on traversal."""
    source = _read_source()
    assert "SecurityException" in source, (
        "VbTerrainImporter.cs SafePathCombine must throw SecurityException "
        "(System.Security.SecurityException) on CWE-22 path traversal."
    )
    # Verify the throw is inside the SafePathCombine method body, not elsewhere.
    # Extract the method body heuristically by finding the method signature and
    # grabbing text until the matching closing brace.
    helper_start = source.find("private static string SafePathCombine(")
    assert helper_start != -1, "SafePathCombine not found"
    # Find the opening brace of the method body
    brace_open = source.find("{", helper_start)
    assert brace_open != -1
    depth = 0
    end = brace_open
    for idx in range(brace_open, len(source)):
        if source[idx] == "{":
            depth += 1
        elif source[idx] == "}":
            depth -= 1
            if depth == 0:
                end = idx
                break
    method_body = source[helper_start:end + 1]
    assert "SecurityException" in method_body, (
        "SecurityException throw must be inside SafePathCombine body, "
        "not elsewhere in the file."
    )
    assert "throw" in method_body, (
        "SafePathCombine body must contain a throw statement."
    )


# ---------------------------------------------------------------------------
# Test 3: No bare Path.Combine(bundleDirectory, ...) call sites remain
# ---------------------------------------------------------------------------

def test_no_bare_path_combine_bundle_directory() -> None:
    """Every Path.Combine(bundleDirectory, ...) must be migrated to SafePathCombine."""
    source = _read_source()
    lines = source.splitlines()
    violations: list[tuple[int, str]] = []
    bare_pattern = re.compile(r"Path\.Combine\s*\(\s*bundleDirectory\b")
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Skip comment lines
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        if bare_pattern.search(line):
            violations.append((lineno, line.rstrip()))

    assert not violations, (
        "Found bare Path.Combine(bundleDirectory, ...) call sites that must be "
        "migrated to SafePathCombine for CWE-22 containment:\n"
        + "\n".join(f"  line {ln}: {txt}" for ln, txt in violations)
    )


# ---------------------------------------------------------------------------
# Test 4: No Path.GetFullPath(Path.Combine(bundleDirectory, ...)) without guard
# ---------------------------------------------------------------------------

def test_no_getfullpath_combine_without_safe_wrapper() -> None:
    """
    Path.GetFullPath(Path.Combine(bundleDirectory, ...)) is the exact unsafe
    pattern the guard replaces. Assert it doesn't appear in non-comment code.
    """
    source = _read_source()
    lines = source.splitlines()
    pattern = re.compile(
        r"Path\.GetFullPath\s*\(\s*Path\.Combine\s*\(\s*bundleDirectory\b"
    )
    violations: list[tuple[int, str]] = []
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        if pattern.search(line):
            violations.append((lineno, line.rstrip()))

    assert not violations, (
        "Found Path.GetFullPath(Path.Combine(bundleDirectory, ...)) call sites "
        "that bypass the SafePathCombine containment guard:\n"
        + "\n".join(f"  line {ln}: {txt}" for ln, txt in violations)
    )


# ---------------------------------------------------------------------------
# Test 5: All SafePathCombine call sites reference bundleDirectory as first arg
# ---------------------------------------------------------------------------

def test_safe_path_combine_all_sites_use_bundle_directory() -> None:
    """
    Every SafePathCombine call in the file (outside the definition) must pass
    bundleDirectory as its first argument, confirming no call accidentally
    uses a different base without containment.
    """
    source = _read_source()
    lines = source.splitlines()
    # Find the definition line to skip it
    defn_line = next(
        (i + 1 for i, ln in enumerate(lines) if "private static string SafePathCombine(" in ln),
        None,
    )
    call_pattern = re.compile(r"SafePathCombine\s*\(")
    bad_base_pattern = re.compile(r"SafePathCombine\s*\(\s*(?!bundleDirectory\b)")
    violations: list[tuple[int, str]] = []
    for lineno, line in enumerate(lines, start=1):
        if lineno == defn_line:
            continue
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        if call_pattern.search(line) and bad_base_pattern.search(line):
            violations.append((lineno, line.rstrip()))

    assert not violations, (
        "Found SafePathCombine calls that do NOT pass bundleDirectory as first arg:\n"
        + "\n".join(f"  line {ln}: {txt}" for ln, txt in violations)
    )
