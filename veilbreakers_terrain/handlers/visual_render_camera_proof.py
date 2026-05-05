"""Render named cameras to PNG with non-black pixel proof.

Bypasses ``mcp__blender__.get_viewport_screenshot`` which returns black
frames on the live Windows 11 + Blender 4.5 + MCP combination. Every
Coastal-perfection unit (U2-U13) uses this handler for visual proof.

Repo command key: ``visual_render_camera_proof`` (registered via
``_LOC_HANDLERS["render_camera_proof"]`` and
``COMMAND_HANDLERS["visual_render_camera_proof"]``).

Plan reference:
    docs/plans/2026-05-04-001-feat-coastal-aaa-perfection-plan.md, U1.

Failure modes (loud, never silent):
    * ``CameraNotFoundError`` — a requested camera name does not exist.
    * ``RenderProofFailedError`` — render produced a near-black PNG, an
      undersized file, or no file at all (the silent ``--background`` +
      empty-filepath gotcha).
    * ``OSError`` — output directory not writeable.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CameraNotFoundError(RuntimeError):
    """Raised when a named camera does not exist in ``bpy.data.objects``."""


class RenderProofFailedError(RuntimeError):
    """Raised when a render fails the non-black + min-size pixel proof."""


_DEFAULT_NONBLACK_THRESHOLD = 0.005
_DEFAULT_MIN_BYTE_SIZE = 50_000
_DEFAULT_RESOLUTION = (1600, 900)
_DEFAULT_SAMPLES = 64
_DEFAULT_ENGINE = "BLENDER_EEVEE_NEXT"
_DEFAULT_VIEW_TRANSFORM = "Standard"
_DEFAULT_LOOK = "Medium High Contrast"


@dataclass(slots=True)
class RenderProof:
    """One camera-render proof record."""

    camera: str
    path: str
    byte_size: int
    nonblack_ratio: float
    ok: bool
    error: str | None = None


@dataclass(slots=True)
class RenderProofManifest:
    """Aggregate manifest for a unit's render-proof run."""

    unit_id: str
    out_dir: str
    engine: str
    resolution: tuple[int, int]
    samples: int
    frame: int | None
    view_transform: str
    look: str
    renders: list[RenderProof] = field(default_factory=list)
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "out_dir": self.out_dir,
            "engine": self.engine,
            "resolution": list(self.resolution),
            "samples": self.samples,
            "frame": self.frame,
            "view_transform": self.view_transform,
            "look": self.look,
            "ok": self.ok,
            "renders": [asdict(r) for r in self.renders],
        }


# ---------------------------------------------------------------------------
# Pure-Python helpers (testable without bpy)
# ---------------------------------------------------------------------------


def compute_nonblack_ratio(png_path: str | os.PathLike[str]) -> float:
    """Return fraction of pixels in ``png_path`` that are not pure black.

    Uses Pillow. A pixel is "non-black" when its R, G, or B channel exceeds
    8/255. This catches the all-zero buffer that Blender produces when
    ``filepath`` is empty under ``--background``.
    """
    from PIL import Image  # imported lazily so unit tests can mock

    with Image.open(png_path) as im:
        rgb = im.convert("RGB")
        # tobytes is fast and avoids per-pixel Python loops
        data = rgb.tobytes()
    if not data:
        return 0.0
    width, height = im.size  # type: ignore[union-attr]
    total = width * height
    if total <= 0:
        return 0.0
    nonblack = 0
    threshold = 8
    # bytes are R,G,B,R,G,B,...
    for i in range(0, len(data), 3):
        if data[i] > threshold or data[i + 1] > threshold or data[i + 2] > threshold:
            nonblack += 1
    return nonblack / total


def assert_render_proof(
    png_path: str | os.PathLike[str],
    *,
    nonblack_threshold: float = _DEFAULT_NONBLACK_THRESHOLD,
    min_byte_size: int = _DEFAULT_MIN_BYTE_SIZE,
) -> tuple[int, float]:
    """Assert that a PNG is real proof — non-black and not undersized.

    Returns ``(byte_size, nonblack_ratio)``. Raises ``RenderProofFailedError``
    on any failure.
    """
    p = Path(png_path)
    if not p.exists():
        raise RenderProofFailedError(
            f"render proof missing: {p} — did filepath get set on bpy.scene? "
            "Under --background, empty/relative render filepath silently "
            "no-writes."
        )
    byte_size = p.stat().st_size
    if byte_size < min_byte_size:
        raise RenderProofFailedError(
            f"render proof undersized: {p} ({byte_size} B < {min_byte_size} B)"
        )
    ratio = compute_nonblack_ratio(p)
    if ratio < nonblack_threshold:
        raise RenderProofFailedError(
            f"render proof too dark: {p} ({ratio:.4%} non-black "
            f"< threshold {nonblack_threshold:.4%}). Likely a black-frame bug."
        )
    return byte_size, ratio


def build_manifest_path(out_dir: str | os.PathLike[str]) -> Path:
    """Return ``<out_dir>/RENDER_MANIFEST.json``."""
    return Path(out_dir) / "RENDER_MANIFEST.json"


# ---------------------------------------------------------------------------
# bpy-dependent core (handler entry point)
# ---------------------------------------------------------------------------


def render_camera_proof(
    cameras: list[str],
    out_dir: str,
    prefix: str = "",
    engine: str = _DEFAULT_ENGINE,
    resolution: tuple[int, int] | list[int] = _DEFAULT_RESOLUTION,
    samples: int = _DEFAULT_SAMPLES,
    view_transform: str = _DEFAULT_VIEW_TRANSFORM,
    look: str = _DEFAULT_LOOK,
    nonblack_threshold: float = _DEFAULT_NONBLACK_THRESHOLD,
    min_byte_size: int = _DEFAULT_MIN_BYTE_SIZE,
    frame: int | None = None,
    unit_id: str = "unknown",
) -> dict[str, Any]:
    """Render each named camera to ``out_dir`` and verify each proof.

    Lazily imports ``bpy``. Raises ``CameraNotFoundError`` early so the
    expensive render is never attempted with a missing camera.
    """
    if not cameras:
        raise ValueError("cameras must be a non-empty list of camera names")
    if isinstance(resolution, list):
        resolution = (int(resolution[0]), int(resolution[1]))
    if len(resolution) != 2:
        raise ValueError(f"resolution must be (width, height); got {resolution!r}")

    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    # Pre-flight write check so we fail before render, not after.
    test_marker = out_path / ".write_check"
    test_marker.write_text("ok")
    test_marker.unlink()

    import bpy  # type: ignore[import-not-found]  # noqa: PLC0415

    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.resolution_x = int(resolution[0])
    scene.render.resolution_y = int(resolution[1])
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = view_transform
    try:
        scene.view_settings.look = look
    except (AttributeError, TypeError):
        # ``look`` value may be unsupported in some color management profiles.
        logger.warning("view_settings.look=%r unsupported; skipping", look)
    if engine == "BLENDER_EEVEE_NEXT":
        eevee = scene.eevee
        try:
            eevee.taa_render_samples = int(samples)
        except AttributeError:
            logger.warning("eevee.taa_render_samples not available")
        try:
            eevee.use_shadows = True
            eevee.use_gtao = True
        except AttributeError:
            pass

    if frame is not None:
        scene.frame_set(int(frame))

    # Pre-flight: every camera must exist before we render anything.
    for cam in cameras:
        if cam not in bpy.data.objects:
            raise CameraNotFoundError(
                f"camera not found: {cam!r} (available: "
                f"{[o.name for o in bpy.data.objects if o.type == 'CAMERA']})"
            )
        if bpy.data.objects[cam].type != "CAMERA":
            raise CameraNotFoundError(
                f"object {cam!r} is type {bpy.data.objects[cam].type!r}, not CAMERA"
            )

    manifest = RenderProofManifest(
        unit_id=unit_id,
        out_dir=str(out_path),
        engine=engine,
        resolution=tuple(resolution),
        samples=int(samples),
        frame=frame,
        view_transform=view_transform,
        look=look,
    )

    for cam_name in cameras:
        scene.camera = bpy.data.objects[cam_name]
        slug = _slug(cam_name)
        filename = f"{prefix + '_' if prefix else ''}{slug}.png"
        png_path = (out_path / filename).resolve()
        # Use forward slashes on Windows — Blender accepts them and
        # Geometry-Nodes file paths break on backslashes.
        scene.render.filepath = png_path.as_posix()
        logger.info("rendering camera=%s -> %s", cam_name, png_path)
        bpy.ops.render.render(write_still=True)

        proof = RenderProof(
            camera=cam_name, path=str(png_path),
            byte_size=0, nonblack_ratio=0.0, ok=False,
        )
        try:
            byte_size, nonblack_ratio = assert_render_proof(
                png_path,
                nonblack_threshold=nonblack_threshold,
                min_byte_size=min_byte_size,
            )
            proof.byte_size = byte_size
            proof.nonblack_ratio = nonblack_ratio
            proof.ok = True
        except RenderProofFailedError as exc:
            proof.error = str(exc)
            proof.ok = False
            manifest.ok = False
            logger.error("render proof failed for %s: %s", cam_name, exc)
        manifest.renders.append(proof)

    manifest_path = build_manifest_path(out_path)
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=False)
    )

    return {
        "ok": manifest.ok,
        "manifest_path": str(manifest_path),
        "renders": [asdict(r) for r in manifest.renders],
        "errors": [r.error for r in manifest.renders if r.error],
    }


def _slug(name: str) -> str:
    """Make a filename-safe slug from a camera name."""
    out: list[str] = []
    for ch in name.strip().lower():
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out).strip("_") or "camera"
    # Collapse runs of underscores
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug


# ---------------------------------------------------------------------------
# Handler entry (signature-matching)
# ---------------------------------------------------------------------------


def handle_visual_render_camera_proof(
    cameras: list[str],
    out_dir: str,
    prefix: str = "",
    engine: str = _DEFAULT_ENGINE,
    resolution: tuple[int, int] | list[int] = _DEFAULT_RESOLUTION,
    samples: int = _DEFAULT_SAMPLES,
    view_transform: str = _DEFAULT_VIEW_TRANSFORM,
    look: str = _DEFAULT_LOOK,
    nonblack_threshold: float = _DEFAULT_NONBLACK_THRESHOLD,
    min_byte_size: int = _DEFAULT_MIN_BYTE_SIZE,
    frame: int | None = None,
    unit_id: str = "unknown",
) -> dict[str, Any]:
    """COMMAND_HANDLERS entry point — kwargs from params dict."""
    return render_camera_proof(
        cameras=cameras,
        out_dir=out_dir,
        prefix=prefix,
        engine=engine,
        resolution=resolution,
        samples=samples,
        view_transform=view_transform,
        look=look,
        nonblack_threshold=nonblack_threshold,
        min_byte_size=min_byte_size,
        frame=frame,
        unit_id=unit_id,
    )
