"""Phase-0 hardware capture harness for VeilBreakers (Day 0 task per §0.4 + §17.0).

Baselines RTX 4060 Ti 8GB VRAM peak + frame-time per HDRP feature toggle
*before* the implementation guide locks the §7.1 budget.

Run from repo root with Unity Editor closed (otherwise the GPU memory
queries are noisy):

    python tools/hwcap/capture_4060ti.py --unity-project unity_project/VbHeroDemo

The script:
  1. Confirms NVIDIA driver >= 546.01 (required to disable sysmem-fallback per §7.5)
  2. Confirms `nvidia-smi` is on PATH and emits CSV
  3. Boots a headless Unity Editor with a configurable HDRP test scene
  4. Toggles each feature in turn (empty → APV → vol-clouds → splat → speedtree → all)
  5. Samples GPU memory.used at 100ms intervals while the scene runs
  6. Captures peak VRAM + average frame time per feature
  7. Writes a JSON report to renders/quality-audit/hwcap_4060ti_baseline.json

Skeleton — wires a CLI + nvidia-smi capture loop. The Unity-editor invocation
and per-feature scene toggles are stubbed; fill those in once Phase D D36-37
authors `unity_project/VbHeroDemo/Assets/Scenes/vb_hwcap.unity`.

Per §19.8 #9 (implementation auditor fix-list): MUST exist on disk before
§17.0 PRE-PHASE-A so the dev can run it Day 0.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Driver version below which the sysmem-fallback toggle in NVIDIA Control Panel
# is not exposed. See §7.5 of IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md.
MIN_DRIVER_MAJOR = 546

# Features the harness baselines, in execution order. Names match HDRP profiler
# markers + Volume override toggles inside `vb_hwcap.unity` (to be authored).
FEATURE_TOGGLES: tuple[str, ...] = (
    "empty_scene",
    "apv_no_sky_occlusion",
    "apv_with_sky_occlusion",
    "vol_clouds_low",
    "vol_clouds_medium",
    "vol_clouds_high",
    "splat_4_layer",
    "splat_8_layer",
    "speedtree_5_species",
    "render_mesh_indirect_30k_grass",
    "water_surface_pool",
    "water_surface_ocean_river_pool",
    "all_combined",
)

# How long to sample each feature for. Long enough to catch streaming spikes,
# short enough to keep total run < 30 minutes.
SAMPLE_SECONDS = 60
SAMPLE_INTERVAL_MS = 100


@dataclass
class FeatureSample:
    """One feature's VRAM + frame-time baseline."""

    feature: str
    peak_vram_mb: float
    mean_vram_mb: float
    frame_time_ms_p50: float = 0.0  # filled in by Unity profiler hook (TODO)
    frame_time_ms_p95: float = 0.0
    samples: int = 0
    notes: list[str] = field(default_factory=list)


def _nvidia_smi_query(query: str) -> str:
    """Run nvidia-smi --query-gpu=<query> --format=csv,noheader,nounits."""
    if shutil.which("nvidia-smi") is None:
        raise RuntimeError("nvidia-smi not on PATH; install NVIDIA driver first")
    result = subprocess.run(
        [
            "nvidia-smi",
            f"--query-gpu={query}",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines()[0].strip()


def check_driver_version() -> tuple[int, int]:
    """Return (major, minor) and raise if < MIN_DRIVER_MAJOR."""
    raw = _nvidia_smi_query("driver_version")
    parts = raw.split(".")
    major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    if major < MIN_DRIVER_MAJOR:
        raise RuntimeError(
            f"NVIDIA driver {raw} below required {MIN_DRIVER_MAJOR}.xx — "
            f"sysmem fallback toggle unavailable. See §7.5."
        )
    return major, minor


def check_gpu_name() -> str:
    """Return GPU model string for cross-reference."""
    return _nvidia_smi_query("gpu_name")


def sample_vram_for(seconds: float, interval_ms: int) -> tuple[float, float, int]:
    """Sample memory.used at <interval_ms> for <seconds>. Return (peak, mean, n)."""
    samples_mb: list[float] = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            samples_mb.append(float(_nvidia_smi_query("memory.used")))
        except (subprocess.CalledProcessError, ValueError):
            pass  # transient driver hiccup — skip the sample, keep going
        time.sleep(interval_ms / 1000.0)
    if not samples_mb:
        return 0.0, 0.0, 0
    return max(samples_mb), sum(samples_mb) / len(samples_mb), len(samples_mb)


def run_unity_feature_toggle(unity_project: Path, feature: str) -> None:
    """Boot Unity headless on `vb_hwcap.unity` with a CLI flag toggling the feature.

    TODO Phase D D36-37: implement once `unity_project/VbHeroDemo/Assets/Scenes/vb_hwcap.unity`
    + `Assets/Editor/VbHwcapBatch.cs` exist. The ExecuteMethod hook should:
      - Load `vb_hwcap.unity`
      - Call `VbHwcapBatch.ToggleFeature("<feature>")` to enable just that pass
      - Run for SAMPLE_SECONDS, then exit
    """
    raise NotImplementedError(
        f"Unity test scene not yet authored. See §17 Phase D D36-37 for "
        f"`unity_project/VbHeroDemo/Assets/Scenes/vb_hwcap.unity` + "
        f"`VbHwcapBatch.ToggleFeature(\"{feature}\")`. Once that lands, replace "
        f"this NotImplementedError with the Unity headless invocation."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--unity-project",
        type=Path,
        default=Path("unity_project/VbHeroDemo"),
        help="path to Unity 6.3 project containing vb_hwcap.unity",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("renders/quality-audit/hwcap_4060ti_baseline.json"),
        help="JSON output path",
    )
    parser.add_argument(
        "--features",
        type=str,
        default=",".join(FEATURE_TOGGLES),
        help="comma-separated subset of FEATURE_TOGGLES to baseline",
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=SAMPLE_SECONDS,
        help="seconds to sample per feature",
    )
    parser.add_argument(
        "--skip-unity",
        action="store_true",
        help="skip Unity invocation (dry-run mode — emits zero-VRAM baseline)",
    )
    args = parser.parse_args()

    print("Phase-0 hardware capture — RTX 4060 Ti 8GB baseline")
    print(f"  Unity project: {args.unity_project}")
    print(f"  Output: {args.out}")
    print(f"  Sample: {args.seconds}s @ {SAMPLE_INTERVAL_MS}ms intervals")

    # Pre-flight
    try:
        gpu_name = check_gpu_name()
        major, minor = check_driver_version()
        print(f"  GPU: {gpu_name}")
        print(f"  Driver: {major}.{minor} (>= {MIN_DRIVER_MAJOR} required)")
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    samples: list[FeatureSample] = []
    features = [f.strip() for f in args.features.split(",") if f.strip()]

    for feature in features:
        print(f"\n  [{feature}]")
        if not args.skip_unity:
            try:
                run_unity_feature_toggle(args.unity_project, feature)
            except NotImplementedError as exc:
                print(f"    SKIP: {exc}")
                samples.append(
                    FeatureSample(
                        feature=feature,
                        peak_vram_mb=0.0,
                        mean_vram_mb=0.0,
                        samples=0,
                        notes=[f"unity-stub: {exc}"],
                    )
                )
                continue
        peak, mean, n = sample_vram_for(args.seconds, SAMPLE_INTERVAL_MS)
        sample = FeatureSample(
            feature=feature,
            peak_vram_mb=peak,
            mean_vram_mb=mean,
            samples=n,
        )
        print(f"    peak {peak:.0f} MB / mean {mean:.0f} MB / n={n}")
        samples.append(sample)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "gpu_name": gpu_name,
                "driver_version": f"{major}.{minor}",
                "sample_seconds": args.seconds,
                "sample_interval_ms": SAMPLE_INTERVAL_MS,
                "features": [asdict(s) for s in samples],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
