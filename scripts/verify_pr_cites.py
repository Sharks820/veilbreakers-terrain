"""CI gate: §11 v3 PR runway cite-refresh prereq (Fix 1.0 / spec §11.0.5).

Walks §11.1-§11.5 PR rows in the biome-render-rebuild spec, extracts every
``<path>:<line>`` cite, and verifies each against the current state of the
file in ``main`` HEAD (or another configurable ref). Reports stale,
out-of-file, or new-file cites.

Usage:
    python scripts/verify_pr_cites.py                # report mode (exit 0)
    python scripts/verify_pr_cites.py --strict       # fail if any cite is stale
    python scripts/verify_pr_cites.py --tsv PATH     # write TSV report
    python scripts/verify_pr_cites.py --json PATH    # write JSON report
    python scripts/verify_pr_cites.py --spec PATH    # override spec path
    python scripts/verify_pr_cites.py --ref REF      # compare against REF (default origin/main)

Exit codes:
    0 — report-only run, or strict run with zero stale cites
    1 — strict run; stale or out-of-file cites detected
    2 — spec missing, git unavailable, or other unrecoverable error

Per §11.0.5, this script must be run before any §11 surgical PR opens.
The cite ground truth is whatever ``git show <ref>:<file>`` returns at the
declared line; ``new_file`` results document Phase 4 PRs that introduce
files not yet on ``main`` (expected, not a failure).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Sequence

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-05-05-biome-render-rebuild-design.md"
)
DEFAULT_REF = "origin/main"

# Path-namespace shorthand → real path (per spec §11.0.3 preface). Order
# matters: longer prefixes first so ``unity_project/Assets/Scripts/`` wins
# over ``Assets/`` substring matches if any are added later.
PATH_NAMESPACE_MAP: tuple[tuple[str, str], ...] = (
    ("unity_project/Assets/Scripts/", "unity_plugin/"),
    ("unity_project/Assets/Editor/", "unity_plugin/Editor/"),
    ("handlers/", "veilbreakers_terrain/handlers/"),
    ("providers/", "veilbreakers_terrain/providers/"),
    ("chunks/", "veilbreakers_terrain/chunks/"),
    ("foliage/", "veilbreakers_terrain/foliage/"),
    ("tests/", "veilbreakers_terrain/tests/"),
    ("sim/", "veilbreakers_terrain/sim/"),
    ("src/veilbreakers_mcp/", "veilbreakers_terrain/src/veilbreakers_mcp/"),
)

# Section anchors that delimit the runway. Treat as substrings in
# ``# `` / ``## `` / ``### `` markdown headings.
RUNWAY_BEGIN_PREFIXES: tuple[str, ...] = (
    "### 11.1 Block 1",
    "### 11.1.0",
    "### 11.0.5",
)
RUNWAY_END_PREFIXES: tuple[str, ...] = (
    "### 11.6",
    "### 11.7",
    "### 11.8",
)

# Cite extractor: matches ``handlers/foo.py:NN``, ``foo.py:NN-MM``,
# ``foo.py:NN,MM``. Captures path and the first numeric line.
CITE_RE = re.compile(
    r"`?(?P<path>[A-Za-z0-9_./\-]+\.(?:py|cs|md|json|toml|yml|yaml|csv|txt|hlsl|shader|shadergraph))`?"
    r":(?P<line>\d+)(?:[-,](?:\d+))?"
)

# PR row sniffer: any markdown row whose first cell is a PR id token like
# ``1``, ``5a``, ``B5-U-NAV``, ``B5-T1b``, ``15.5``. We also accept rows
# where the first cell is struck through (``~~6~~``) or annotated
# ("MOVED to Block 4...") — those rows have no surgical cite but we still
# audit them to flag NO_CITE rows as documentation breadcrumbs.
PR_ROW_RE = re.compile(
    r"^\|\s*(?P<id>~~[^|~]+~~|[A-Za-z0-9._\-/]+)\s*\|", re.MULTILINE
)

# PR rows we deliberately skip because the first cell is text, not an ID
# (e.g. table headers, rule rows, "PR #" example rows).
SKIP_FIRST_CELL = {
    "PR",
    "PR #",
    "Title",
    "------",
    ":---",
    "---",
    "id",
}

PrCategoryT = str  # one of the cite-status strings below

STATUS_VALID = "VALID"
STATUS_STALE = "STALE"
STATUS_OUT_OF_FILE = "OUT_OF_FILE"
STATUS_NEW_FILE = "NEW_FILE_NOT_ON_MAIN"
STATUS_NO_CITE = "NO_CITE"
STATUS_RESOLVE_FAIL = "RESOLVE_FAIL"

ALL_STATUSES = (
    STATUS_VALID,
    STATUS_STALE,
    STATUS_OUT_OF_FILE,
    STATUS_NEW_FILE,
    STATUS_NO_CITE,
    STATUS_RESOLVE_FAIL,
)

# Statuses that fail a strict run.
STRICT_FAIL_STATUSES = frozenset({STATUS_STALE, STATUS_OUT_OF_FILE, STATUS_RESOLVE_FAIL})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CiteRecord:
    """One ``<file>:<line>`` cite extracted from a PR row."""

    pr_id: str
    pr_title: str
    raw_cite: str
    resolved_path: str
    line: int
    status: PrCategoryT
    actual_line_text: str = ""
    notes: str = ""

    def to_tsv_row(self) -> list[str]:
        return [
            self.pr_id,
            self.pr_title,
            self.raw_cite,
            self.resolved_path,
            str(self.line) if self.line else "",
            self.status,
            self.actual_line_text.strip()[:200],
            self.notes,
        ]


@dataclass
class AuditResult:
    """Aggregate audit result over a whole spec."""

    records: list[CiteRecord] = field(default_factory=list)
    spec_path: str = ""
    ref: str = ""

    def by_status(self, status: str) -> list[CiteRecord]:
        return [r for r in self.records if r.status == status]

    def counts(self) -> dict[str, int]:
        return {status: len(self.by_status(status)) for status in ALL_STATUSES}

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.records if r.status in STRICT_FAIL_STATUSES)


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------

def _slice_runway(spec_text: str) -> str:
    """Return only the §11 runway portion of the spec."""

    lines = spec_text.splitlines(keepends=True)
    start: int | None = None
    end: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if start is None and any(
            stripped.startswith(prefix) for prefix in RUNWAY_BEGIN_PREFIXES
        ):
            start = idx
            continue
        if start is not None and any(
            stripped.startswith(prefix) for prefix in RUNWAY_END_PREFIXES
        ):
            end = idx
            break
    if start is None:
        return ""
    return "".join(lines[start : end if end is not None else len(lines)])


def _extract_pr_rows(runway_text: str) -> list[tuple[str, str]]:
    """Return ``[(pr_id, full_row_text)]`` for every PR row in the runway."""

    rows: list[tuple[str, str]] = []
    for line in runway_text.splitlines():
        if not line.startswith("|"):
            continue
        match = PR_ROW_RE.match(line)
        if not match:
            continue
        pr_id = match.group("id").strip()
        first_cell_clean = pr_id.replace("~~", "").strip()
        if first_cell_clean in SKIP_FIRST_CELL:
            continue
        # Heuristic: a PR id is short, single-token, and not pure punctuation.
        if not first_cell_clean or len(first_cell_clean) > 32:
            continue
        if all(ch in "-:|" for ch in first_cell_clean):
            continue
        rows.append((pr_id, line))
    return rows


def _extract_cites(row_text: str) -> list[tuple[str, str, int]]:
    """Return ``[(raw_cite, path, line)]`` from a PR row."""

    cites: list[tuple[str, str, int]] = []
    seen: set[tuple[str, int]] = set()
    for match in CITE_RE.finditer(row_text):
        raw = match.group(0)
        path = match.group("path")
        try:
            line = int(match.group("line"))
        except ValueError:  # pragma: no cover — regex guarantees digits
            continue
        key = (path, line)
        if key in seen:
            continue
        seen.add(key)
        cites.append((raw, path, line))
    return cites


def _extract_pr_title(row_text: str) -> str:
    """Best-effort PR title extraction (the second pipe-delimited cell)."""

    cells = [cell.strip() for cell in row_text.split("|")]
    # Layout: '' | id | title | files | acceptance | validation | effort | deps
    if len(cells) >= 3:
        return cells[2].replace("`", "")
    return ""


# ---------------------------------------------------------------------------
# Path resolution + git lookup
# ---------------------------------------------------------------------------

def _resolve_path(raw_path: str) -> str:
    """Apply path-namespace shorthand resolution per spec §11.0.3."""

    for shorthand, real in PATH_NAMESPACE_MAP:
        if raw_path.startswith(shorthand):
            return real + raw_path[len(shorthand) :]
    return raw_path


def _git_show_lines(ref: str, path: str) -> list[str] | None:
    """Return file contents at ``ref`` as line list, or ``None`` if missing.

    Reads as bytes and decodes UTF-8 with replacement so cross-platform
    encodings (Windows cp1252 default) don't blow up on non-ASCII bytes.
    """

    proc = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    text = proc.stdout.decode("utf-8", errors="replace")
    return text.splitlines()


def _ref_exists(ref: str) -> bool:
    """Return True if git can resolve ``ref``."""

    proc = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# Cite classification
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def _classify(
    *,
    pr_id: str,
    pr_title: str,
    raw_cite: str,
    resolved_path: str,
    line: int,
    file_lines: list[str] | None,
) -> CiteRecord:
    """Apply VALID/STALE/OUT_OF_FILE/NEW_FILE classification heuristics."""

    if file_lines is None:
        return CiteRecord(
            pr_id=pr_id,
            pr_title=pr_title,
            raw_cite=raw_cite,
            resolved_path=resolved_path,
            line=line,
            status=STATUS_NEW_FILE,
            notes="path absent in ref blob",
        )
    if line < 1 or line > len(file_lines):
        return CiteRecord(
            pr_id=pr_id,
            pr_title=pr_title,
            raw_cite=raw_cite,
            resolved_path=resolved_path,
            line=line,
            status=STATUS_OUT_OF_FILE,
            actual_line_text="",
            notes=f"file length={len(file_lines)} on ref",
        )

    actual = file_lines[line - 1]
    title_tokens = {t.lower() for t in _TOKEN_RE.findall(pr_title) if len(t) > 2}
    actual_tokens = {t.lower() for t in _TOKEN_RE.findall(actual) if len(t) > 2}
    overlap = title_tokens & actual_tokens

    if overlap:
        return CiteRecord(
            pr_id=pr_id,
            pr_title=pr_title,
            raw_cite=raw_cite,
            resolved_path=resolved_path,
            line=line,
            status=STATUS_VALID,
            actual_line_text=actual,
            notes=f"shared tokens: {','.join(sorted(overlap))[:80]}",
        )

    # Window check: ±3 lines for a soft match.
    window_start = max(0, line - 4)
    window_end = min(len(file_lines), line + 3)
    window_text = " ".join(file_lines[window_start:window_end]).lower()
    nearby_overlap = [t for t in title_tokens if t in window_text]
    if nearby_overlap:
        return CiteRecord(
            pr_id=pr_id,
            pr_title=pr_title,
            raw_cite=raw_cite,
            resolved_path=resolved_path,
            line=line,
            status=STATUS_STALE,
            actual_line_text=actual,
            notes=f"line drift; tokens at L{window_start + 1}-{window_end}: {','.join(nearby_overlap)[:80]}",
        )

    return CiteRecord(
        pr_id=pr_id,
        pr_title=pr_title,
        raw_cite=raw_cite,
        resolved_path=resolved_path,
        line=line,
        status=STATUS_STALE,
        actual_line_text=actual,
        notes="no token overlap with PR title in ±3-line window",
    )


# ---------------------------------------------------------------------------
# Main audit routine
# ---------------------------------------------------------------------------

def audit_spec(spec_path: Path, ref: str) -> AuditResult:
    """Walk the spec at ``spec_path`` and verify every cite against ``ref``."""

    if not spec_path.exists():
        raise FileNotFoundError(spec_path)
    if shutil.which("git") is None:
        raise RuntimeError("git binary not found in PATH")
    if not _ref_exists(ref):
        raise RuntimeError(f"ref not resolvable: {ref}")

    spec_text = spec_path.read_text(encoding="utf-8")
    runway = _slice_runway(spec_text)
    if not runway:
        raise RuntimeError(
            f"runway section not found in {spec_path}; expected one of {RUNWAY_BEGIN_PREFIXES}"
        )

    result = AuditResult(spec_path=str(spec_path), ref=ref)
    file_cache: dict[str, list[str] | None] = {}

    for pr_id, row_text in _extract_pr_rows(runway):
        pr_title = _extract_pr_title(row_text)
        cites = _extract_cites(row_text)
        if not cites:
            result.records.append(
                CiteRecord(
                    pr_id=pr_id,
                    pr_title=pr_title,
                    raw_cite="",
                    resolved_path="",
                    line=0,
                    status=STATUS_NO_CITE,
                    notes="no <file>:<line> pattern in row",
                )
            )
            continue
        for raw_cite, path, line in cites:
            resolved = _resolve_path(path)
            if resolved not in file_cache:
                file_cache[resolved] = _git_show_lines(ref, resolved)
            file_lines = file_cache[resolved]
            result.records.append(
                _classify(
                    pr_id=pr_id,
                    pr_title=pr_title,
                    raw_cite=raw_cite,
                    resolved_path=resolved,
                    line=line,
                    file_lines=file_lines,
                )
            )
    return result


# ---------------------------------------------------------------------------
# Output emitters
# ---------------------------------------------------------------------------

def _emit_summary(result: AuditResult, *, file=sys.stdout) -> None:
    counts = result.counts()
    print(
        f"verify_pr_cites: spec={result.spec_path} ref={result.ref} total={result.total}",
        file=file,
    )
    for status in ALL_STATUSES:
        print(f"  {status:>22}: {counts[status]:4d}", file=file)
    if result.fail_count:
        print(f"  --> strict-fail-count={result.fail_count}", file=file)


def _emit_tsv(result: AuditResult, dest: Path) -> None:
    headers = [
        "pr_id",
        "pr_title",
        "raw_cite",
        "resolved_path",
        "line",
        "status",
        "actual_line_text",
        "notes",
    ]
    with dest.open("w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(headers) + "\n")
        for rec in result.records:
            fh.write("\t".join(rec.to_tsv_row()) + "\n")


def _emit_json(result: AuditResult, dest: Path) -> None:
    payload = {
        "spec_path": result.spec_path,
        "ref": result.ref,
        "total": result.total,
        "counts": result.counts(),
        "fail_count": result.fail_count,
        "records": [asdict(rec) for rec in result.records],
    }
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify §11 v3 PR runway cite-refresh prereq (Fix 1.0 / spec §11.0.5)."
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=DEFAULT_SPEC,
        help=f"Path to spec markdown (default: {DEFAULT_SPEC.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--ref",
        type=str,
        default=DEFAULT_REF,
        help=f"Git ref to verify cites against (default: {DEFAULT_REF})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any STALE/OUT_OF_FILE/RESOLVE_FAIL cites detected",
    )
    parser.add_argument(
        "--max-stale",
        type=int,
        default=0,
        dest="max_stale",
        help=(
            "Ratchet baseline: with --strict, exit 1 only if fail-count "
            "exceeds this number (default: 0). Use during the cite-cleanup "
            "transition; tighten as surgical PRs land cite corrections."
        ),
    )
    parser.add_argument(
        "--tsv",
        type=Path,
        default=None,
        help="Write per-cite TSV report to this path",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        dest="json_path",
        help="Write JSON report to this path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = audit_spec(args.spec, args.ref)
    except FileNotFoundError as exc:
        print(f"verify_pr_cites: spec not found: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"verify_pr_cites: {exc}", file=sys.stderr)
        return 2

    if args.tsv:
        _emit_tsv(result, args.tsv)
    if args.json_path:
        _emit_json(result, args.json_path)
    _emit_summary(result)

    if args.strict and result.fail_count > args.max_stale:
        print(
            f"verify_pr_cites: STRICT FAIL — fail-count {result.fail_count} "
            f"exceeds baseline {args.max_stale}; cite-refresh required",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
