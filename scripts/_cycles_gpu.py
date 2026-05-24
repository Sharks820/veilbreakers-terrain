"""Shared Cycles GPU device selection for every Blender render script.

Cycles defaults its render device to CPU per-scene, and `--background` does NOT
auto-enable the GPU even if one exists. Each render script must therefore
explicitly (a) pick a GPU compute backend, (b) enable the device(s), and
(c) set scene.cycles.device = 'GPU'. Doing this in one place keeps every render
path consistent instead of 10 drifting copies.

Usage (from any render script, after REPO_ROOT is on sys.path):
    from scripts._cycles_gpu import enable_cycles_gpu
    enable_cycles_gpu(scene)            # OptiX -> CUDA -> HIP/oneAPI/Metal -> CPU

Returns the chosen backend name (e.g. "OPTIX") or "CPU" if no GPU is available.
bpy is imported lazily so this module stays importable outside Blender (tests).
"""
from __future__ import annotations

from typing import Any, Callable

# Preference order: OptiX (RTX RT cores, best) -> CUDA -> AMD HIP -> Intel oneAPI -> Apple Metal.
_DEFAULT_BACKENDS = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")


def enable_cycles_gpu(
    scene: Any,
    backends: tuple[str, ...] = _DEFAULT_BACKENDS,
    log: Callable[..., Any] = print,
) -> str:
    """Select a GPU compute device for Cycles on `scene`; fall back to CPU.

    Also enables the GPU denoiser (OptiX AI denoiser when on OptiX, else
    OpenImageDenoise on GPU) so denoising doesn't silently run on the CPU.
    """
    import bpy

    scene.render.engine = "CYCLES"
    try:
        cprefs = bpy.context.preferences.addons["cycles"].preferences
    except Exception as exc:  # cycles addon not enabled
        scene.cycles.device = "CPU"
        log("[gpu] cycles preferences unavailable (%r) -> CPU render" % (exc,))
        return "CPU"

    chosen = None
    for backend in backends:
        try:
            cprefs.compute_device_type = backend
            cprefs.refresh_devices()
        except (TypeError, AttributeError):
            continue  # backend not supported by this build/platform
        if any(d.type == backend for d in cprefs.devices):
            for d in cprefs.devices:
                d.use = (d.type == backend)  # enable matching GPU(s), disable CPU + other backends
            chosen = backend
            break

    if not chosen:
        scene.cycles.device = "CPU"
        log("[gpu] no GPU compute device found -> CPU render")
        return "CPU"

    scene.cycles.device = "GPU"
    # Denoiser: keep it on the GPU too (otherwise OIDN can run on CPU and
    # re-introduce a CPU bottleneck after a fast GPU render).
    try:
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = "OPTIX" if chosen == "OPTIX" else "OPENIMAGEDENOISE"
        if hasattr(scene.cycles, "denoising_use_gpu"):
            scene.cycles.denoising_use_gpu = True
    except Exception as exc:
        log("[gpu] denoiser setup skipped (%r)" % (exc,))

    enabled = ", ".join(d.name for d in cprefs.devices if d.use)
    log("[gpu] Cycles GPU ENABLED: %s | denoiser=%s | %s" % (chosen, scene.cycles.denoiser, enabled))
    return chosen
