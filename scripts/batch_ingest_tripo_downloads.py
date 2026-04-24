"""Batch ingest for Tripo downloads (VeilBreakers Phase I).

Scans a downloads directory for newly arrived Tripo assets
(``.glb``/``.gltf``/``.fbx``/``.zip``) and feeds each one through
``ingest_tripo_asset.ingest``.  Already-processed files are tracked in a
sidecar ledger (``.tripo_ingest_ledger.json``) so re-running the script is
idempotent.

Typical overnight flow:

    # User runs Tripo prompts, lets the 4-variation downloads pile up in
    # ``~/Downloads``, then fires:
    python scripts/batch_ingest_tripo_downloads.py \
        --downloads ~/Downloads \
        --assets assets/foliage

Add ``--watch 60`` to loop every 60 s, picking up files as they finish
downloading.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable

# Allow this script to be run directly without a package install.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import ingest_tripo_asset  # noqa: E402  (path setup above)


_SUPPORTED_EXT = {".glb", ".gltf", ".fbx", ".zip", ".synthmesh.json"}

# Files Tripo and web browsers create mid-download — skip until they finalise.
_IN_FLIGHT_PATTERNS = ("*.crdownload", "*.part", "*.tmp", "*.download")

# Default download filename filter — Tripo names typically include "tripo".
# When the user curates a subfolder, we match everything inside it.
_DEFAULT_INCLUDE = ("tripo*", "*foliage*", "*grass*", "*tree*", "*rock*", "*boulder*",
                    "*moss*", "*vine*", "*bush*", "*fern*", "*fence*", "*signpost*",
                    "*walkway*", "*cobble*", "*flower*", "*mushroom*", "*lily*",
                    "*reed*", "*log*", "*stump*")


def _is_supported(path: Path) -> bool:
    if path.is_dir():
        return False
    name = path.name.lower()
    if any(fnmatch.fnmatch(name, pat) for pat in _IN_FLIGHT_PATTERNS):
        return False
    if name.endswith(".synthmesh.json"):
        return True
    return path.suffix.lower() in _SUPPORTED_EXT


def _matches_include(path: Path, patterns: Iterable[str]) -> bool:
    lowered = path.name.lower()
    parent = path.parent.name.lower()
    for pat in patterns:
        if fnmatch.fnmatch(lowered, pat) or fnmatch.fnmatch(parent, pat):
            return True
    return False


def discover_candidates(
    downloads_root: Path,
    *,
    include_patterns: Iterable[str] = _DEFAULT_INCLUDE,
    recursive: bool = True,
) -> list[Path]:
    """Return every unprocessed Tripo download under *downloads_root*."""
    if not downloads_root.exists():
        return []
    walker = downloads_root.rglob("*") if recursive else downloads_root.iterdir()
    hits: list[Path] = []
    for path in walker:
        if not _is_supported(path):
            continue
        if not _matches_include(path, include_patterns):
            continue
        hits.append(path)
    hits.sort(key=lambda p: p.stat().st_mtime)
    return hits


def _ledger_path(assets_root: Path) -> Path:
    return assets_root / ".tripo_ingest_ledger.json"


def _load_ledger(assets_root: Path) -> dict[str, Any]:
    p = _ledger_path(assets_root)
    if not p.exists():
        return {"version": 1, "processed": {}}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "processed": {}}
    data.setdefault("processed", {})
    return data


def _save_ledger(assets_root: Path, ledger: dict[str, Any]) -> None:
    assets_root.mkdir(parents=True, exist_ok=True)
    p = _ledger_path(assets_root)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, sort_keys=True)
    tmp.replace(p)


def _file_fingerprint(path: Path) -> str:
    try:
        st = path.stat()
    except OSError:
        return f"missing:{path}"
    # Use size + mtime for speed; content hash only on ambiguity. Good enough
    # for ledger dedup because Tripo downloads are append-only.
    seed = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode()
    return hashlib.sha1(seed).hexdigest()


def run_batch(
    downloads_root: Path,
    assets_root: Path,
    *,
    blender_exe: Path | None = None,
    force_synthetic: bool = False,
    include_patterns: Iterable[str] = _DEFAULT_INCLUDE,
    recursive: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run a single batch pass.  Returns a stats dict."""
    downloads_root = downloads_root.expanduser().resolve()
    assets_root = assets_root.expanduser().resolve()
    assets_root.mkdir(parents=True, exist_ok=True)

    ledger = _load_ledger(assets_root)
    processed: dict[str, Any] = ledger["processed"]

    candidates = discover_candidates(
        downloads_root,
        include_patterns=include_patterns,
        recursive=recursive,
    )

    stats: dict[str, Any] = {
        "scanned": len(candidates),
        "ingested": [],
        "skipped": [],
        "failed": [],
    }

    for path in candidates:
        fp = _file_fingerprint(path)
        if fp in processed:
            stats["skipped"].append({"path": str(path), "reason": "already_processed"})
            continue
        if dry_run:
            stats["skipped"].append({"path": str(path), "reason": "dry_run"})
            continue
        try:
            entry = ingest_tripo_asset.ingest(
                path,
                assets_root,
                blender_exe=blender_exe,
                force_synthetic=force_synthetic,
            )
            processed[fp] = {
                "path": str(path),
                "asset_id": entry["asset_id"],
                "category": entry["category"],
                "ingested_at": entry["ingested_at"],
            }
            _save_ledger(assets_root, ledger)
            stats["ingested"].append(entry["asset_id"])
        except Exception as exc:  # noqa: BLE001 — we want to keep going
            stats["failed"].append({"path": str(path), "error": repr(exc)})
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_downloads() -> Path:
    env = os.environ.get("TRIPO_DOWNLOADS")
    if env:
        return Path(env)
    home = Path.home()
    for name in ("Downloads", "downloads"):
        cand = home / name
        if cand.exists():
            return cand
    return home / "Downloads"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Batch-ingest Tripo downloads.")
    p.add_argument("--downloads", type=Path, default=_default_downloads())
    p.add_argument("--assets", type=Path, default=Path("assets/foliage"))
    p.add_argument(
        "--blender",
        type=Path,
        default=ingest_tripo_asset._default_blender(),
    )
    p.add_argument("--synthetic", action="store_true", help="Force synthetic ingest (CI / testing).")
    p.add_argument("--dry-run", action="store_true", help="List work without ingesting.")
    p.add_argument(
        "--watch",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Loop forever, re-scanning every N seconds. 0 = run once.",
    )
    p.add_argument(
        "--include",
        action="append",
        default=None,
        help="Glob include pattern (may be repeated). Defaults to Tripo-ish names.",
    )
    p.add_argument("--no-recursive", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    patterns = tuple(args.include) if args.include else _DEFAULT_INCLUDE

    while True:
        stats = run_batch(
            args.downloads,
            args.assets,
            blender_exe=args.blender,
            force_synthetic=args.synthetic,
            include_patterns=patterns,
            recursive=not args.no_recursive,
            dry_run=args.dry_run,
        )
        print(json.dumps(stats, indent=2, default=str))
        if args.watch <= 0:
            break
        time.sleep(args.watch)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
