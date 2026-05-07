"""Unity Recorder + HDRP Path Tracing visual gate (replaces compute_nonblack_ratio).

Per §17 Phase D D43-44 + §19.8 #8 of IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md:
the visual gate has historically been `compute_nonblack_ratio` which "passed"
anything 0.5%+ non-black. This script replaces that gate with:

  1. Boot Unity headless against `unity_project/VbHeroDemo/Assets/Scenes/vb_hero_demo.unity`
  2. Activate Cinemachine vcam tagged "HeroShot" + 4 Volume profiles per biome
  3. Drive the Unity Recorder package (com.unity.recorder@5.1) to capture
     a 4K PNG sequence under HDRP Path Tracing accumulation (256-1024 spp)
  4. Diff against `tests/golden_scenarios/<biome>_pilot.png` via Graphics Test
     Framework's `ImageAssert.AreEqual` (SSIM ≥ 0.95 per spec §11.5b PR #6.5)
  5. Exit 0 = gate pass; exit 1 = SSIM too low; exit 2 = Unity invocation failed

Skeleton — wires the CLI + golden-image diff loop. The Unity Recorder
invocation and Path Tracer accumulation are stubbed until Phase D D36-37
authors `unity_project/VbHeroDemo` + `Assets/Editor/VbHeroShotRecorder.cs`.

Per §19.8 #8 implementation-auditor fix-list: this skeleton MUST exist on
disk Day 0 so the dev can iterate against its CLI surface during Phase A-C
even before Unity Recorder is fully wired.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Spec §11.5b PR #6.5 SSIM threshold. Tier-aware tolerance per §8.5.
DEFAULT_SSIM_THRESHOLD = 0.95
PATH_TRACER_SPP_GOLDEN = 1024
PATH_TRACER_SPP_QUICK = 256

# Two ship-minimum biomes per §16.3.
DEFAULT_BIOMES = ("mountain_pass", "corrupted_swamp")


@dataclass
class GateResult:
    """One biome's visual gate verdict."""

    biome: str
    ssim: float
    passed: bool
    captured: Path
    golden: Path
    spp: int
    notes: list[str] = field(default_factory=list)


def find_unity_executable() -> Path:
    """Locate Unity 6.3 LTS Editor on Windows + macOS + Linux."""
    candidates = [
        Path(r"C:\Program Files\Unity\Hub\Editor\6000.3.0f1\Editor\Unity.exe"),
        Path(r"C:\Program Files\Unity\Hub\Editor\6000.3.0\Editor\Unity.exe"),
        Path("/Applications/Unity/Hub/Editor/6000.3.0f1/Unity.app/Contents/MacOS/Unity"),
        Path("/opt/Unity/Hub/Editor/6000.3.0f1/Editor/Unity"),
    ]
    for path in candidates:
        if path.exists():
            return path
    found = shutil.which("Unity") or shutil.which("unity")
    if found:
        return Path(found)
    raise RuntimeError(
        "Unity 6.3 LTS Editor not found. Install via Unity Hub per §0.4 Day 0 checklist."
    )


def run_recorder_for_biome(
    unity_project: Path,
    biome: str,
    spp: int,
    output_dir: Path,
) -> Path:
    """Boot Unity headless + drive Recorder + Path Tracer for one biome.

    TODO Phase D D43-44: implement once `Assets/Editor/VbHeroShotRecorder.cs`
    exists with `[MenuItem]` callable via `-executeMethod`. Concrete steps:

      Unity.exe -batchmode -projectPath <unity_project> \\
                -executeMethod VbHeroShotRecorder.CaptureBiome \\
                -biome <biome> -spp <spp> -outputDir <output_dir> \\
                -logFile <output_dir>/unity.log -quit

    The C# side should:
      1. Load vb_hero_demo.unity
      2. Activate the biome's Volume profile (e.g. vb_mountain_pass_volume.asset)
      3. Activate the HeroShot Cinemachine vcam
      4. Configure HDRP Volume > Path Tracing override: enabled=true, spp=<spp>
      5. Configure Recorder Image Sequence:
           - source: GameView at 4K (3840×2160) — HDRP Path Tracer downsamples
           - format: PNG
           - frame range: 1 frame (path-traced still, not video)
           - accumulation: spp samples
      6. StartRecording → wait for Recorder.IsRecording==false → write PNG
    """
    raise NotImplementedError(
        f"VbHeroShotRecorder.cs not yet authored. See §17 Phase D D43-44 for the "
        f"Unity-side recorder + Path Tracer accumulation. Stub: would capture "
        f"`{biome}` at {spp} spp into `{output_dir}/<biome>.png`."
    )


def compute_ssim(captured: Path, golden: Path) -> float:
    """Compute SSIM via skimage.metrics.structural_similarity.

    Falls back to a hash-equality stub if skimage isn't available — that
    fallback is OK for Day 0 (no goldens exist yet); Phase D D43-44 must
    install scikit-image as a dev-dep.
    """
    try:
        import numpy as np
        from PIL import Image
        from skimage.metrics import structural_similarity as ssim_fn
    except ImportError as exc:
        print(f"  WARN: skimage unavailable ({exc}); using hash-equality stub", file=sys.stderr)
        # Stub: 1.0 if files byte-identical, 0.0 otherwise.
        if captured.read_bytes() == golden.read_bytes():
            return 1.0
        return 0.0

    cap_img = np.array(Image.open(captured).convert("RGB"))
    gold_img = np.array(Image.open(golden).convert("RGB"))
    if cap_img.shape != gold_img.shape:
        # Mismatched shapes can't SSIM — return a sentinel that fails the gate.
        return 0.0
    return float(ssim_fn(cap_img, gold_img, channel_axis=2, data_range=255))


def run_gate(
    unity_project: Path,
    biomes: tuple[str, ...],
    spp: int,
    threshold: float,
    captures_dir: Path,
    goldens_dir: Path,
    skip_unity: bool,
) -> list[GateResult]:
    results: list[GateResult] = []
    captures_dir.mkdir(parents=True, exist_ok=True)

    for biome in biomes:
        print(f"\n  [{biome}] capturing at {spp} spp...")
        captured = captures_dir / f"{biome}.png"
        golden = goldens_dir / f"{biome}_pilot.png"
        notes: list[str] = []

        if not skip_unity:
            try:
                run_recorder_for_biome(unity_project, biome, spp, captures_dir)
            except NotImplementedError as exc:
                notes.append(f"unity-stub: {exc}")
                print(f"    SKIP: {exc}")
                results.append(
                    GateResult(
                        biome=biome,
                        ssim=0.0,
                        passed=False,
                        captured=captured,
                        golden=golden,
                        spp=spp,
                        notes=notes,
                    )
                )
                continue

        if not golden.exists():
            notes.append(f"golden not found at {golden} — first run only")
            print(f"    SKIP: golden missing — capture as new golden via --update-golden")
            results.append(
                GateResult(
                    biome=biome,
                    ssim=0.0,
                    passed=False,
                    captured=captured,
                    golden=golden,
                    spp=spp,
                    notes=notes,
                )
            )
            continue

        score = compute_ssim(captured, golden)
        passed = score >= threshold
        print(f"    SSIM {score:.4f} (threshold {threshold:.2f}) → {'PASS' if passed else 'FAIL'}")
        results.append(
            GateResult(
                biome=biome,
                ssim=score,
                passed=passed,
                captured=captured,
                golden=golden,
                spp=spp,
                notes=notes,
            )
        )

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--unity-project",
        type=Path,
        default=Path("unity_project/VbHeroDemo"),
    )
    parser.add_argument(
        "--biomes",
        type=str,
        default=",".join(DEFAULT_BIOMES),
        help=f"comma-separated biome list (default: {','.join(DEFAULT_BIOMES)})",
    )
    parser.add_argument(
        "--spp",
        type=int,
        default=PATH_TRACER_SPP_GOLDEN,
        help=f"path tracer samples per pixel (default {PATH_TRACER_SPP_GOLDEN}, "
        f"quick mode: {PATH_TRACER_SPP_QUICK})",
    )
    parser.add_argument("--ssim-threshold", type=float, default=DEFAULT_SSIM_THRESHOLD)
    parser.add_argument(
        "--captures-dir",
        type=Path,
        default=Path("renders/visual-gate/captures"),
    )
    parser.add_argument(
        "--goldens-dir",
        type=Path,
        default=Path("tests/golden_scenarios"),
    )
    parser.add_argument(
        "--skip-unity",
        action="store_true",
        help="skip Unity invocation (use existing captures only — useful for SSIM-only re-runs)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("renders/visual-gate/gate_report.json"),
    )
    args = parser.parse_args()

    biomes = tuple(b.strip() for b in args.biomes.split(",") if b.strip())

    print("Unity Recorder visual gate — VeilBreakers")
    print(f"  Unity project: {args.unity_project}")
    print(f"  Biomes: {','.join(biomes)}")
    print(f"  Path Tracer spp: {args.spp}")
    print(f"  SSIM threshold: {args.ssim_threshold:.2f}")

    if not args.skip_unity:
        try:
            unity_exe = find_unity_executable()
            print(f"  Unity exe: {unity_exe}")
        except RuntimeError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 2

    results = run_gate(
        unity_project=args.unity_project,
        biomes=biomes,
        spp=args.spp,
        threshold=args.ssim_threshold,
        captures_dir=args.captures_dir,
        goldens_dir=args.goldens_dir,
        skip_unity=args.skip_unity,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "ssim_threshold": args.ssim_threshold,
                "spp": args.spp,
                "results": [
                    {**asdict(r), "captured": str(r.captured), "golden": str(r.golden)}
                    for r in results
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {args.report}")

    failed = [r for r in results if not r.passed]
    if failed:
        print(f"\nGATE FAIL: {len(failed)}/{len(results)} biomes below threshold", file=sys.stderr)
        return 1
    print(f"\nGATE PASS: {len(results)}/{len(results)} biomes ≥ {args.ssim_threshold:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
