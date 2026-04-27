"""Phase L+ — Triple-judge sign-off loop.

Extends the existing Opus + Codex Phase L supervisor with Gemini 3 Pro as a
third judge. All three must agree (OVERALL_PASS) on a node before sign-off.

Judges:
  * Opus — invoked via an in-process sub-agent-style stub (see `opus_judge`).
    In live operation this is dispatched via the parent supervisor's Task
    tool; for standalone runs and tests the stub can be monkey-patched.
  * Codex — invoked via `codex exec --skip-git-repo-check
    --output-last-message <tmp> "<prompt>"`.
  * Gemini — invoked via `gemini -p "<prompt>"` with GEMINI_API_KEY in env.

Usage:
    python scripts/phase_l_triple_judge.py
    python scripts/phase_l_triple_judge.py --node-dir output/aaa_node_v1
    python scripts/phase_l_triple_judge.py --max-rounds 8 --probe-only

On triple-agreement per node a TRIPLE_SIGNOFF.json is written and, for the
showcase dir, Blender is launched detached in the foreground so the artist
can eyeball the .blend file.

Design notes:
  * Gemini's response quality is unknown — per user direction, if Gemini
    errors/refuses/returns garbage we fall back to Opus+Codex agreement and
    annotate that in the signoff doc. We never block on Gemini alone.
  * Round-by-round ledger goes to <node_dir>/TRIPLE_LOOP_STATUS.json.
  * Fix-round dispatch is emitted as a queued job description; a parent
    agent consumes it and spawns a sub-agent. When run standalone with
    --dispatch-stub the dispatch is logged only.

"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NODE_DIRS = [
    REPO_ROOT / "output" / "aaa_node_v1",
    REPO_ROOT / "output" / "aaa_node_v2",
    REPO_ROOT / "output" / "aaa_node_showcase",
]
SHOWCASE_DIR = REPO_ROOT / "output" / "aaa_node_showcase"
SHOWCASE_BLEND = SHOWCASE_DIR / "VeilBreakers_Showcase_TwoNode.blend"
BLENDER_EXE = Path("C:/Program Files/Blender Foundation/Blender 4.5/blender.exe")

MAX_ROUNDS_DEFAULT = 8


def _resolve_node_cli(stem: str) -> str:
    """Return an executable path for a node-installed CLI (gemini/codex).

    On Windows, subprocess cannot exec the bash shim directly (it's not a
    PE executable), so we prefer the `.cmd` sibling. On POSIX the bare
    script works. Falls back to PATH lookup.
    """

    base = Path("C:/nvm4w/nodejs") / stem
    candidates: list[Path] = []
    if os.name == "nt":
        candidates.extend([base.with_suffix(".cmd"), base.with_suffix(".exe"), base])
    else:
        candidates.extend([base, base.with_suffix(".cmd")])
    for c in candidates:
        if c.exists():
            return str(c)
    which = shutil.which(stem)
    return which or stem


GEMINI_BIN = None  # lazily resolved
CODEX_BIN = None


# ---------------------------------------------------------------------------
# Verdict data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Verdict:
    """Normalized judge verdict."""

    judge: str
    verdict: str  # "OVERALL_PASS" | "OVERALL_FAIL" | "ERROR"
    score_of_10: int | None = None
    critical_issues: list[str] = dataclasses.field(default_factory=list)
    minor_issues: list[str] = dataclasses.field(default_factory=list)
    praise: list[str] = dataclasses.field(default_factory=list)
    raw: str = ""
    error: str | None = None

    def passed(self) -> bool:
        return self.verdict == "OVERALL_PASS"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _list_renders(node_dir: Path) -> list[Path]:
    if not node_dir.exists():
        return []
    return sorted(p for p in node_dir.glob("render_*.png") if p.is_file())


def parse_verdict_json(raw: str, judge: str) -> Verdict:
    """Extract the JSON object from a judge's free-text response.

    Judges sometimes wrap JSON in ```json fences or emit preamble text. We
    walk the string, find the first balanced `{...}` block, and parse it.
    """

    if not raw:
        return Verdict(judge=judge, verdict="ERROR", raw=raw, error="empty response")

    # Try fenced block first.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        # First '{' to matching '}'.
        start = raw.find("{")
        if start < 0:
            return Verdict(judge=judge, verdict="ERROR", raw=raw, error="no JSON object")
        depth = 0
        end = -1
        in_str = False
        esc = False
        for i, ch in enumerate(raw[start:], start=start):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            return Verdict(judge=judge, verdict="ERROR", raw=raw, error="unbalanced JSON")
        candidate = raw[start : end + 1]

    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return Verdict(judge=judge, verdict="ERROR", raw=raw, error=f"json decode: {exc}")

    verdict_str = str(obj.get("verdict", "")).upper().strip()
    if verdict_str not in {"OVERALL_PASS", "OVERALL_FAIL"}:
        return Verdict(
            judge=judge,
            verdict="ERROR",
            raw=raw,
            error=f"unexpected verdict value: {verdict_str!r}",
        )

    score = obj.get("score_of_10")
    try:
        score_int = int(score) if score is not None else None
    except (TypeError, ValueError):
        score_int = None

    def _as_list(val: Any) -> list[str]:
        if isinstance(val, list):
            return [str(x) for x in val]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
        return []

    return Verdict(
        judge=judge,
        verdict=verdict_str,
        score_of_10=score_int,
        critical_issues=_as_list(obj.get("critical_issues")),
        minor_issues=_as_list(obj.get("minor_issues")),
        praise=_as_list(obj.get("praise")),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

JUDGE_PREAMBLE = (
    "You are a AAA game art director. Below is a BUILD_SUMMARY describing a "
    "procedurally-generated terrain tile, and I will describe 6 rendered "
    "views. Judge whether this tile would pass as AAA-studio quality "
    "(Horizon Forbidden West / Red Dead 2 / Elden Ring) or whether a trained "
    "eye would flag it as \"obviously AI/procedural\". Respond with exactly "
    "this JSON format and NOTHING ELSE:\n"
    '{"verdict": "OVERALL_PASS" | "OVERALL_FAIL", "score_of_10": <int>, '
    '"critical_issues": ["..."], "minor_issues": ["..."], "praise": ["..."]}\n'
)


def build_prompt(node_dir: Path, summary: dict[str, Any], renders: list[Path]) -> str:
    render_lines = []
    for p in renders:
        render_lines.append(f"  - {p.name} ({p.stat().st_size} bytes) at {p}")
    render_block = "\n".join(render_lines) if render_lines else "  (no renders)"

    summary_block = json.dumps(summary, indent=2, sort_keys=True)[:6000]

    failure_log = node_dir / "BUILD_FAILURE.log"
    failure_excerpt = ""
    if failure_log.exists():
        try:
            excerpt = failure_log.read_text(encoding="utf-8", errors="replace")[:1500]
            failure_excerpt = f"\n\nBUILD_FAILURE.log excerpt:\n{excerpt}\n"
        except OSError:
            pass

    return (
        f"{JUDGE_PREAMBLE}\n"
        f"Node directory: {node_dir}\n"
        f"Renders available for inspection (paths):\n{render_block}\n"
        f"{failure_excerpt}\n"
        f"BUILD_SUMMARY.json:\n{summary_block}\n"
    )


# ---------------------------------------------------------------------------
# Judge adapters
# ---------------------------------------------------------------------------

def opus_judge(prompt: str, node_dir: Path) -> Verdict:
    """Opus judge stub.

    In supervisor mode the parent agent overrides this with a real Task-tool
    dispatch. Standalone runs use the stub, which returns ERROR so that the
    loop reports the missing integration rather than silently passing.
    """

    override = os.environ.get("TRIPLE_JUDGE_OPUS_STUB")
    if override:
        try:
            data = json.loads(Path(override).read_text(encoding="utf-8"))
            return parse_verdict_json(json.dumps(data), judge="opus")
        except (OSError, json.JSONDecodeError) as exc:
            return Verdict(judge="opus", verdict="ERROR", raw="", error=str(exc))
    return Verdict(
        judge="opus",
        verdict="ERROR",
        raw="",
        error="opus_judge not wired — parent agent must override with Task dispatch",
    )


def codex_judge(prompt: str, node_dir: Path, timeout: int = 180) -> Verdict:
    codex_bin = _resolve_node_cli("codex")
    if not Path(codex_bin).exists() and not shutil.which(codex_bin):
        return Verdict(judge="codex", verdict="ERROR", raw="", error=f"codex binary not found ({codex_bin})")
    tmp = Path(tempfile.gettempdir()) / f"codex_verdict_{os.getpid()}.txt"
    cmd = [
        codex_bin,
        "exec",
        "--skip-git-repo-check",
        "--output-last-message",
        str(tmp),
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired:
        return Verdict(judge="codex", verdict="ERROR", raw="", error="timeout")
    except OSError as exc:
        return Verdict(judge="codex", verdict="ERROR", raw="", error=f"spawn: {exc}")

    raw = ""
    if tmp.exists():
        try:
            raw = tmp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    if not raw:
        raw = proc.stdout or proc.stderr or ""

    if proc.returncode != 0 and not raw.strip():
        return Verdict(
            judge="codex",
            verdict="ERROR",
            raw=raw,
            error=f"codex exit {proc.returncode}: {proc.stderr[:400]}",
        )

    return parse_verdict_json(raw, judge="codex")


def gemini_judge(prompt: str, node_dir: Path, timeout: int = 180) -> Verdict:
    gemini_bin = _resolve_node_cli("gemini")
    if not Path(gemini_bin).exists() and not shutil.which(gemini_bin):
        return Verdict(judge="gemini", verdict="ERROR", raw="", error=f"gemini binary not found ({gemini_bin})")

    # Gemini CLI scans the cwd for folder context and falls over on
    # unreadable dirs (pytest-of-Conner, .pr5-worktree, tmp*). Run from a
    # clean temp cwd so the scan succeeds.
    with tempfile.TemporaryDirectory(prefix="gemini_cwd_") as clean_cwd:
        env = os.environ.copy()
        env.setdefault("GEMINI_API_KEY", "")
        cmd = [gemini_bin, "-p", prompt]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=clean_cwd,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return Verdict(judge="gemini", verdict="ERROR", raw="", error="timeout")
        except OSError as exc:
            return Verdict(judge="gemini", verdict="ERROR", raw="", error=f"spawn: {exc}")

    raw = proc.stdout or ""
    if not raw.strip() and proc.returncode != 0:
        return Verdict(
            judge="gemini",
            verdict="ERROR",
            raw=proc.stderr[:400],
            error=f"gemini exit {proc.returncode}",
        )
    return parse_verdict_json(raw, judge="gemini")


def probe_gemini() -> tuple[bool, str]:
    """Return (ok, message) after the trivial PING probe."""

    gemini_bin = _resolve_node_cli("gemini")
    if not Path(gemini_bin).exists() and not shutil.which(gemini_bin):
        return False, f"gemini binary not found ({gemini_bin})"
    with tempfile.TemporaryDirectory(prefix="gemini_probe_") as clean_cwd:
        try:
            proc = subprocess.run(
                [gemini_bin, "-p", "Reply with exactly: PING OK"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=clean_cwd,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return False, f"probe error: {exc}"
    out = (proc.stdout or "").strip()
    ok = "PING OK" in out
    return ok, out or proc.stderr[:200]


# ---------------------------------------------------------------------------
# Ledger + signoff
# ---------------------------------------------------------------------------

def write_status(node_dir: Path, status: dict[str, Any]) -> None:
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / "TRIPLE_LOOP_STATUS.json").write_text(
        json.dumps(status, indent=2, sort_keys=True), encoding="utf-8"
    )


def write_verdict_md(node_dir: Path, verdict: Verdict) -> Path:
    name = {
        "opus": "OPUS_VERDICT.md",
        "codex": "CODEX_VERDICT.md",
        "gemini": "GEMINI_VERDICT.md",
    }.get(verdict.judge, f"{verdict.judge.upper()}_VERDICT.md")
    path = node_dir / name
    body = [
        f"# {verdict.judge.title()} verdict",
        f"- timestamp: {_utc_now()}",
        f"- verdict: {verdict.verdict}",
        f"- score_of_10: {verdict.score_of_10}",
    ]
    if verdict.error:
        body.append(f"- error: {verdict.error}")
    if verdict.critical_issues:
        body.append("\n## Critical issues")
        body.extend(f"- {x}" for x in verdict.critical_issues)
    if verdict.minor_issues:
        body.append("\n## Minor issues")
        body.extend(f"- {x}" for x in verdict.minor_issues)
    if verdict.praise:
        body.append("\n## Praise")
        body.extend(f"- {x}" for x in verdict.praise)
    body.append("\n## Raw response\n")
    body.append("```\n" + (verdict.raw or "(no raw output)") + "\n```\n")
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def union_issues(verdicts: list[Verdict]) -> dict[str, list[str]]:
    crit: list[str] = []
    minor: list[str] = []
    seen = set()
    for v in verdicts:
        for issue in v.critical_issues:
            key = ("c", issue.strip().lower())
            if key not in seen:
                seen.add(key)
                crit.append(f"[{v.judge}] {issue}")
        for issue in v.minor_issues:
            key = ("m", issue.strip().lower())
            if key not in seen:
                seen.add(key)
                minor.append(f"[{v.judge}] {issue}")
    return {"critical": crit, "minor": minor}


def agreement(verdicts: list[Verdict], allow_gemini_fallback: bool) -> tuple[bool, str]:
    """Return (all_pass, mode). Mode is 'triple' or 'duo_fallback' or 'fail'."""

    opus = next((v for v in verdicts if v.judge == "opus"), None)
    codex = next((v for v in verdicts if v.judge == "codex"), None)
    gemini = next((v for v in verdicts if v.judge == "gemini"), None)

    opus_pass = opus is not None and opus.passed()
    codex_pass = codex is not None and codex.passed()
    gemini_pass = gemini is not None and gemini.passed()
    gemini_errored = gemini is not None and gemini.verdict == "ERROR"

    if opus_pass and codex_pass and gemini_pass:
        return True, "triple"
    if opus_pass and codex_pass and gemini_errored and allow_gemini_fallback:
        return True, "duo_fallback"
    return False, "fail"


# ---------------------------------------------------------------------------
# Fix-round dispatch
# ---------------------------------------------------------------------------

def build_fix_prompt(node_dir: Path, issues: dict[str, list[str]], round_num: int) -> str:
    node_name = node_dir.name
    if node_name in ("aaa_node_v1", "aaa_node_v2"):
        # build_aaa_node_v1.py and v2.py are deleted; v4 is the current script.
        script = "scripts/build_terrain_aaa_node_v4.py"
        short = "Node v4"
    else:
        script = "scripts/build_aaa_node_showcase.py"
        short = "Showcase"

    lines = [f"Fix these {len(issues['critical']) + len(issues['minor'])} issues in the AAA node build scripts ({script})."]
    if issues["critical"]:
        lines.append("Critical:")
        lines.extend(f"  - {x}" for x in issues["critical"])
    if issues["minor"]:
        lines.append("Minor:")
        lines.extend(f"  - {x}" for x in issues["minor"])
    lines.append(
        "Re-run Blender headless. Re-render. Save over existing outputs."
    )
    lines.append(
        f'Commit as "fix(node): round {round_num} visual polish — {short}".'
    )
    return "\n".join(lines)


def dispatch_fix(node_dir: Path, issues: dict[str, list[str]], round_num: int, stub: bool) -> str:
    """Queue a fix-agent dispatch. Returns the dispatch id / marker.

    In supervisor mode the parent agent reads TRIPLE_FIX_QUEUE.json and
    spawns a Task sub-agent. In stub mode we only write the queue entry.
    """

    queue_path = node_dir / "TRIPLE_FIX_QUEUE.json"
    existing = _safe_read_json(queue_path) or {"dispatches": []}
    dispatch_id = f"{node_dir.name}-r{round_num}-{_utc_now().replace(':', '')}"
    entry = {
        "id": dispatch_id,
        "round": round_num,
        "created_utc": _utc_now(),
        "issues": issues,
        "prompt": build_fix_prompt(node_dir, issues, round_num),
        "stub_only": stub,
    }
    existing.setdefault("dispatches", []).append(entry)
    queue_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return dispatch_id


# ---------------------------------------------------------------------------
# Showcase launch
# ---------------------------------------------------------------------------

def launch_blender_foreground(blend_path: Path, log_path: Path) -> dict[str, Any]:
    if not blend_path.exists():
        return {"launched": False, "reason": f"blend missing: {blend_path}"}
    if not BLENDER_EXE.exists():
        return {"launched": False, "reason": f"blender missing: {BLENDER_EXE}"}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_path, "ab")
    try:
        # Detached process on Windows: use DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP.
        creationflags = 0
        if os.name == "nt":
            creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            [str(BLENDER_EXE), str(blend_path)],
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as exc:
        log_fp.close()
        return {"launched": False, "reason": f"spawn error: {exc}"}
    return {"launched": True, "pid": proc.pid, "log": str(log_path)}


# ---------------------------------------------------------------------------
# Per-node orchestration
# ---------------------------------------------------------------------------

def run_node(
    node_dir: Path,
    max_rounds: int,
    dispatch_stub: bool,
    allow_gemini_fallback: bool,
    judges: dict[str, Callable[[str, Path], Verdict]] | None = None,
) -> dict[str, Any]:
    """Run the triple-judge loop for one node dir and return the final record."""

    if judges is None:
        judges = {
            "opus": opus_judge,
            "codex": codex_judge,
            "gemini": gemini_judge,
        }

    result: dict[str, Any] = {
        "node_dir": str(node_dir),
        "exists": node_dir.exists(),
        "rounds": [],
        "final_verdicts": None,
        "agreement_mode": None,
        "signoff": None,
        "started_utc": _utc_now(),
    }

    if not node_dir.exists():
        result["skipped"] = "node_dir does not exist yet"
        write_status(node_dir if False else node_dir.parent, {
            "node": node_dir.name,
            "skipped": True,
            "reason": "node_dir missing",
            "timestamp": _utc_now(),
        }) if node_dir.parent.exists() else None
        return result

    summary_path = node_dir / "BUILD_SUMMARY.json"
    if not summary_path.exists():
        result["skipped"] = "BUILD_SUMMARY.json missing"
        write_status(node_dir, {
            "node": node_dir.name,
            "skipped": True,
            "reason": "BUILD_SUMMARY.json missing",
            "timestamp": _utc_now(),
        })
        return result

    summary = _safe_read_json(summary_path)
    renders = _list_renders(node_dir)

    for round_num in range(1, max_rounds + 1):
        prompt = build_prompt(node_dir, summary, renders)
        verdicts: list[Verdict] = []
        for name in ("opus", "codex", "gemini"):
            fn = judges[name]
            v = fn(prompt, node_dir)
            verdicts.append(v)
            write_verdict_md(node_dir, v)

        all_pass, mode = agreement(verdicts, allow_gemini_fallback=allow_gemini_fallback)
        round_record = {
            "round_num": round_num,
            "timestamp": _utc_now(),
            "verdicts": [v.to_dict() for v in verdicts],
            "all_pass": all_pass,
            "mode": mode,
        }

        fix_dispatch_id = None
        if not all_pass:
            issues = union_issues(verdicts)
            if issues["critical"] or issues["minor"]:
                fix_dispatch_id = dispatch_fix(node_dir, issues, round_num, stub=dispatch_stub)
            round_record["fix_dispatch_id"] = fix_dispatch_id
            round_record["issues"] = issues

        result["rounds"].append(round_record)

        write_status(node_dir, {
            "node": node_dir.name,
            "round_num": round_num,
            "max_rounds": max_rounds,
            "verdicts": [v.to_dict() for v in verdicts],
            "all_pass": all_pass,
            "mode": mode,
            "fix_dispatch_id": fix_dispatch_id,
            "issues": union_issues(verdicts) if not all_pass else {"critical": [], "minor": []},
            "last_update_utc": _utc_now(),
        })

        if all_pass:
            result["final_verdicts"] = [v.to_dict() for v in verdicts]
            result["agreement_mode"] = mode
            signoff = {
                "node_dir": str(node_dir),
                "agreement_mode": mode,
                "agreed_utc": _utc_now(),
                "round_num": round_num,
                "verdicts": [v.to_dict() for v in verdicts],
                "gemini_fallback_used": mode == "duo_fallback",
            }
            if mode == "duo_fallback":
                signoff["note"] = (
                    "Gemini judge errored or refused; signoff uses Opus + Codex "
                    "agreement with Gemini flagged as unusable."
                )
            (node_dir / "TRIPLE_SIGNOFF.json").write_text(
                json.dumps(signoff, indent=2), encoding="utf-8"
            )
            result["signoff"] = signoff

            if node_dir.resolve() == SHOWCASE_DIR.resolve():
                launch = launch_blender_foreground(
                    SHOWCASE_BLEND, SHOWCASE_DIR / "blender_foreground.log"
                )
                (SHOWCASE_DIR / "BLENDER_FOREGROUND_LAUNCH.json").write_text(
                    json.dumps({**launch, "timestamp": _utc_now()}, indent=2),
                    encoding="utf-8",
                )
                result["blender_launch"] = launch
            return result

        # Otherwise continue to next round — the fix dispatch is expected to
        # rebuild artifacts before the next iteration. In stub mode the loop
        # will simply re-run against unchanged inputs and terminate at
        # max_rounds with a FAILURE_TO_AGREE.md.

    # Max rounds exhausted.
    failure_doc = node_dir / "FAILURE_TO_AGREE.md"
    lines = [
        f"# Failure to agree — {node_dir.name}",
        f"- exhausted {max_rounds} rounds at {_utc_now()}",
        "",
        "## Round-by-round audit",
    ]
    for r in result["rounds"]:
        lines.append(f"### Round {r['round_num']} ({r['timestamp']}) — mode={r['mode']}")
        for vd in r["verdicts"]:
            lines.append(
                f"- {vd['judge']}: {vd['verdict']} "
                f"score={vd.get('score_of_10')} err={vd.get('error')}"
            )
            if vd.get("critical_issues"):
                lines.append("  critical: " + "; ".join(vd["critical_issues"]))
            if vd.get("minor_issues"):
                lines.append("  minor: " + "; ".join(vd["minor_issues"]))
    failure_doc.write_text("\n".join(lines), encoding="utf-8")
    result["failure_to_agree"] = str(failure_doc)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--node-dir", type=Path, action="append", default=None,
                   help="Specific node directory (repeatable). Default: all three.")
    p.add_argument("--max-rounds", type=int, default=MAX_ROUNDS_DEFAULT)
    p.add_argument("--probe-only", action="store_true",
                   help="Only run the Gemini PING probe and exit.")
    p.add_argument("--dispatch-stub", action="store_true",
                   help="Log fix dispatches to queue but do not invoke Task.")
    p.add_argument("--no-gemini-fallback", action="store_true",
                   help="Disallow duo_fallback; require triple agreement strictly.")
    args = p.parse_args(argv)

    probe_ok, probe_msg = probe_gemini()
    print(f"[gemini-probe] ok={probe_ok} msg={probe_msg[:200]!r}", flush=True)
    if args.probe_only:
        return 0 if probe_ok else 2

    node_dirs = args.node_dir or DEFAULT_NODE_DIRS
    overall: list[dict[str, Any]] = []
    for nd in node_dirs:
        nd = Path(nd).resolve()
        print(f"[triple-judge] starting node: {nd}", flush=True)
        rec = run_node(
            nd,
            max_rounds=args.max_rounds,
            dispatch_stub=args.dispatch_stub,
            allow_gemini_fallback=not args.no_gemini_fallback,
        )
        overall.append(rec)
        print(f"[triple-judge] done: {nd.name} -> signoff={bool(rec.get('signoff'))}", flush=True)

    summary_path = REPO_ROOT / "output" / "TRIPLE_JUDGE_RUN.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps({"run_utc": _utc_now(), "nodes": overall, "gemini_probe_ok": probe_ok}, indent=2),
        encoding="utf-8",
    )
    print(f"[triple-judge] summary -> {summary_path}", flush=True)

    all_signed = all(r.get("signoff") for r in overall if r.get("exists"))
    return 0 if all_signed else 1


if __name__ == "__main__":
    sys.exit(main())
