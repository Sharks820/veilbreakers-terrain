"""grade_renders_codex.py — Run Codex CLI to visually grade terrain renders.

Finds all render PNGs in a build output directory, calls `codex exec` for
each image, and writes a structured GRADE_REPORT.json.

Usage:
    python scripts/grade_renders_codex.py [--dir output/aaa_node_v5]
    python scripts/grade_renders_codex.py --dir output/aaa_node_v4 --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Resolve codex binary at import time so subprocess.run doesn't rely on PATH
# (Python's subprocess PATH ≠ bash/shell PATH on Windows).
_CODEX_BIN = shutil.which("codex") or shutil.which("codex.cmd") or "codex"

GRADING_PROMPT = """You are a AAA game art director grading terrain renders for a dark fantasy game (VeilBreakers).
Grade the attached image on a letter scale (A through F) across these specific dimensions:

1. **Terrain Shape Quality** (A-F): Does the heightfield look natural? Are there plausible ridges, valleys, gorge cuts, and
   cliffs? Are there banding artifacts, grid patterns, or unnaturally uniform slopes?

2. **Water / Shoreline Quality** (A-F): Is the water surface believable? Is the shoreline blend smooth (no hard pixel
   cutoff)? Are foam/wetness transitions present? Is the water contained to plausible terrain depressions?

3. **Material / Texture Quality** (A-F): Is there PBR texture variation? Are there harsh tile seams, pixel blowout,
   over-bright normals, or blurry/placeholder textures? Does the material layer blend (height-based splatting)?

4. **Lighting Quality** (A-F): Does the scene have directional light, ambient occlusion, and atmospheric depth? Are there
   harsh crease artifacts caused by hard normals on the mesh? Is it over-exposed or flat?

5. **Vegetation / Scatter Quality** (A-F): If visible, does scatter distribution feel natural? Are there billboard pop-in
   artifacts, floating objects, or Z-fighting? If no vegetation is visible, grade N/A.

6. **Overall AAA Grade** (A-F): Compared to KCD2 / The Witcher 3 / RDR2 terrain quality standards.

For each dimension, state the grade then one sentence of specific evidence from the image.
End with: "PASS" if overall >= B-, or "FAIL" if overall < B-.
"""


def _run_codex_grade(image_path: Path, dry_run: bool = False) -> dict:
    prompt = GRADING_PROMPT.format(image_path=str(image_path))

    if dry_run:
        return {
            "image": image_path.name,
            "status": "dry_run",
            "output": "DRY RUN — codex not called",
        }

    try:
        result = subprocess.run(
            [_CODEX_BIN, "exec", "--model", "gpt-5.5", "-i", str(image_path)],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(REPO_ROOT),
        )
        raw = result.stdout.strip() or result.stderr.strip()
        passed = "PASS" in raw.upper().split()[-5:] if raw else False
        return {
            "image": image_path.name,
            "status": "ok" if result.returncode == 0 else "error",
            "return_code": result.returncode,
            "passed": passed,
            "output": raw,
        }
    except subprocess.TimeoutExpired:
        return {"image": image_path.name, "status": "timeout", "passed": False, "output": ""}
    except Exception as exc:
        return {"image": image_path.name, "status": "exception", "error": repr(exc), "passed": False, "output": ""}


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade terrain renders via Codex CLI")
    parser.add_argument("--dir", default="output/aaa_node_v5", help="Build output directory")
    parser.add_argument("--dry-run", action="store_true", help="Skip actual Codex calls")
    args = parser.parse_args()

    build_dir = REPO_ROOT / args.dir
    renders = sorted(build_dir.glob("render_*.png"))

    if not renders:
        print(f"[grade] No render_*.png found in {build_dir}", flush=True)
        return 1

    print(f"[grade] Grading {len(renders)} renders in {build_dir.name}...", flush=True)

    results = []
    for img in renders:
        print(f"[grade] -> {img.name}", flush=True)
        r = _run_codex_grade(img, dry_run=args.dry_run)
        results.append(r)
        verdict = "PASS" if r.get("passed") else "FAIL" if r.get("status") == "ok" else r.get("status", "?")
        print(f"[grade]   {verdict}", flush=True)
        if r.get("output"):
            for line in r["output"].splitlines()[:8]:
                print(f"[grade]     {line}", flush=True)

    passed = sum(1 for r in results if r.get("passed"))
    report = {
        "build_dir": str(build_dir),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
    report_path = build_dir / "GRADE_REPORT.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[grade] DONE - {passed}/{len(results)} passed. Report: {report_path}", flush=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
