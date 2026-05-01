"""Fail CI when strict Pyright errors grow beyond the checked-in baseline."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "pyrightconfig.strict.json"
BASELINE_PATH = REPO_ROOT / "pyright-strict-baseline.json"


def _rel(path: str) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _run_pyright() -> dict[str, Any]:
    pyright_args = ["-p", str(CONFIG_PATH), "--outputjson"]
    pyright_cmd = ["pyright", *pyright_args]
    if os.name == "nt":
        resolved = (
            shutil.which("pyright.cmd")
            or shutil.which("pyright.exe")
            or shutil.which("pyright.ps1")
        )
        if resolved and resolved.lower().endswith(".ps1"):
            pyright_cmd = [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                resolved,
                *pyright_args,
            ]
        elif resolved:
            pyright_cmd = [resolved, *pyright_args]

    proc = subprocess.run(
        pyright_cmd,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if not proc.stdout.strip():
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode or 1)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode or 1)


def _error_counts(payload: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for diagnostic in payload.get("generalDiagnostics", []):
        if diagnostic.get("severity") != "error":
            continue
        key = f"{_rel(str(diagnostic.get('file', '')))}|{diagnostic.get('rule', 'unknown')}"
        counts[key] += 1
    return counts


def _write_baseline(actual: Counter[str]) -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    baseline["allowed_error_counts"] = {
        key: int(actual[key])
        for key in sorted(actual)
    }
    BASELINE_PATH.write_text(
        json.dumps(baseline, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail CI when strict Pyright errors grow beyond the checked-in baseline."
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Rewrite pyright-strict-baseline.json to the current strict error buckets.",
    )
    args = parser.parse_args()

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    allowed = Counter({
        str(key): int(value)
        for key, value in baseline.get("allowed_error_counts", {}).items()
    })
    actual = _error_counts(_run_pyright())

    if args.update_baseline:
        _write_baseline(actual)
        print(
            "updated pyright strict ratchet baseline: "
            f"{sum(actual.values())} allowed errors across {len(actual)} buckets"
        )
        return 0

    regressions = {
        key: (allowed.get(key, 0), count)
        for key, count in sorted(actual.items())
        if count > allowed.get(key, 0)
    }
    improvements = {
        key: (allowed_count, actual.get(key, 0))
        for key, allowed_count in sorted(allowed.items())
        if actual.get(key, 0) < allowed_count
    }

    print(
        "pyright strict ratchet baseline: "
        f"{sum(actual.values())} current errors, "
        f"{sum(allowed.values())} allowed errors, "
        f"{len(improvements)} improved buckets"
    )
    if improvements:
        print("Improved buckets:")
        for key, (old, new) in improvements.items():
            print(f"  {key}: {old} -> {new}")

    if regressions:
        print("New or increased strict Pyright error buckets:")
        for key, (old, new) in regressions.items():
            print(f"  {key}: {old} -> {new}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
