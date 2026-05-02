"""Hunyuan3D-2 provider — HuggingFace Space (default) or HF Inference Endpoint.

Default: HuggingFace Space tencent/Hunyuan3D-2 via gradio_client (free, queued, ~90s).
  pip install gradio-client

Faster: Set HUNYUAN3D2_HF_ENDPOINT to a private HF Inference Endpoint URL (paid).

Mode selection:
  1. HUNYUAN3D2_HF_ENDPOINT set → HF Inference Endpoint (paid, fast)
  2. (default)                  → HuggingFace Space (free, ~90s queue)

HF Space endpoints (tencent/Hunyuan3D-2):
  /generation_all    — shape + texture (~90s); outputs white_mesh, textured_mesh, html, stats, seed
  /shape_generation  — shape only (~40s); outputs mesh_file, html, stats, seed

Example usage:
    from veilbreakers_terrain.providers import Hunyuan3D2Provider, AssetGenerationRequest
    from pathlib import Path

    provider = Hunyuan3D2Provider()
    result = provider.generate_blocking(
        AssetGenerationRequest(
            species_id="dark_oak_hero",
            prompt="ancient gnarled dark oak tree, dead branches, dark fantasy, game asset",
            image_path=Path("reference/dark_oak_ref.jpg"),
            seed=42,
            quality="high",
            texture=True,
            target_tris=40_000,
        ),
        dest_dir=Path("output/assets/trees"),
    )
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .external_asset_provider import (
    AssetGenerationRequest,
    AssetJobResult,
    ExternalAssetProvider,
    JobStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mode constants
# ---------------------------------------------------------------------------
_MODE_HF_SPACE = "huggingface"
_MODE_HF_ENDPOINT = "hf_endpoint"

_DEFAULT_HF_SPACE = "tencent/Hunyuan3D-2"

_API_SHAPE_AND_TEXTURE = "/generation_all"
_API_SHAPE_ONLY = "/shape_generation"


class Hunyuan3D2Provider(ExternalAssetProvider):
    """Provider backed by the Hunyuan3D-2 HuggingFace Space.

    huggingface (default)
        Uses the public tencent/Hunyuan3D-2 Space via gradio_client.
        Free, queued, ~90 seconds per asset.  No GPU required.
        Requires: pip install gradio-client

    hf_endpoint
        Uses a private HF Inference Endpoint you deploy yourself.
        Set HUNYUAN3D2_HF_ENDPOINT=https://your-endpoint.huggingface.cloud
        Paid, fast.  Requires: pip install gradio-client

    ABC contract (submit / poll / download):
        Generation is a single blocking predict() call.  submit() runs it in a
        background thread and returns a synthetic UUID job_id; poll() checks
        thread state; download() copies the result to dest_dir.
        Use generate_blocking() for the simpler direct path.
    """

    provider_id = "hunyuan3d2"

    def __init__(
        self,
        *,
        hf_space: Optional[str] = None,
        hf_endpoint: Optional[str] = None,
        hf_token: Optional[str] = None,
        timeout_s: float = 1800.0,
        job_retention_s: float = 900.0,
    ) -> None:
        """Initialise the provider.

        Parameters
        ----------
        hf_space:
            HuggingFace Space slug (default: "tencent/Hunyuan3D-2").
            Override via HUNYUAN3D2_HF_SPACE env var.
        hf_endpoint:
            Full URL to a private HF Inference Endpoint.
            Override via HUNYUAN3D2_HF_ENDPOINT env var.
            When set, takes priority over the public Space.
        hf_token:
            HuggingFace API token for private Spaces / Endpoints.
            Override via HUGGINGFACE_TOKEN or HF_TOKEN env vars.
        timeout_s:
            Hard timeout for a single generate_blocking() call in seconds.
        job_retention_s:
            Seconds to retain completed job metadata before pruning temp files.
        """
        env_mode = os.environ.get("HUNYUAN3D2_MODE", "").lower()
        if env_mode == "local":
            raise RuntimeError(
                "HUNYUAN3D2_MODE=local is not supported — local Hunyuan3D-2 requires "
                "16-24 GB VRAM and will OOM on 8 GB cards. "
                "Unset HUNYUAN3D2_MODE to use the HuggingFace Space (free, no GPU needed)."
            )

        env_endpoint = os.environ.get("HUNYUAN3D2_HF_ENDPOINT", "")

        self._hf_space = (
            hf_space
            or os.environ.get("HUNYUAN3D2_HF_SPACE", "")
            or _DEFAULT_HF_SPACE
        )
        self._hf_endpoint = hf_endpoint or env_endpoint or ""
        self._hf_token = (
            hf_token
            or os.environ.get("HUGGINGFACE_TOKEN", "")
            or os.environ.get("HF_TOKEN", "")
            or None
        )
        self._mode = _MODE_HF_ENDPOINT if self._hf_endpoint else _MODE_HF_SPACE
        self._timeout_s = timeout_s
        self._job_retention_s = job_retention_s

        self._jobs: Dict[str, Tuple[threading.Thread, dict]] = {}
        self._jobs_lock = threading.Lock()

        logger.info(
            "[hunyuan3d2] mode=%s src=%s",
            self._mode,
            self._hf_endpoint if self._mode == _MODE_HF_ENDPOINT else self._hf_space,
        )

    def is_available(self, *, timeout_s: float = 10.0) -> bool:
        """Return whether the configured Hunyuan backend can be reached."""
        holder: dict[str, bool] = {"ok": False}

        def _probe() -> None:
            try:
                self._get_gradio_client()
                holder["ok"] = True
            except Exception:
                logger.debug("[hunyuan3d2] availability probe failed", exc_info=True)

        thread = threading.Thread(target=_probe, daemon=True, name="hy3d-probe")
        thread.start()
        thread.join(timeout=max(float(timeout_s), 0.0))
        return bool(holder["ok"])

    # ------------------------------------------------------------------
    # gradio_client helpers
    # ------------------------------------------------------------------

    def _get_gradio_client(self):
        try:
            from gradio_client import Client  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "gradio-client is required: pip install gradio-client"
            ) from exc

        src = self._hf_endpoint if self._mode == _MODE_HF_ENDPOINT else self._hf_space
        kwargs: dict[str, Any] = {"verbose": False}
        if self._hf_token:
            kwargs["token"] = self._hf_token
        logger.debug("[hunyuan3d2] connecting gradio_client to %s", src)
        return Client(src, **kwargs)

    def _build_predict_kwargs(self, request: AssetGenerationRequest) -> dict:
        from gradio_client import handle_file  # type: ignore

        # When an image is provided, set caption=None: passing text+image together
        # triggers a NameError in the Space's multimodal code path.
        kwargs: dict[str, Any] = {
            "caption": None if request.image_path is not None else request.prompt,
            "steps": 30 if request.quality == "high" else 5,
            "guidance_scale": 5.0,
            "seed": request.seed if request.seed is not None else 1234,
            "octree_resolution": 256 if request.quality == "high" else 128,
            "check_box_rembg": True,
            "num_chunks": 8000,
            "randomize_seed": False,
        }
        if request.image_path is not None:
            kwargs["image"] = handle_file(str(request.image_path))
        for mv_key in ("mv_image_front", "mv_image_back", "mv_image_left", "mv_image_right"):
            kwargs[mv_key] = None
        return kwargs

    def _hf_generate_blocking(self, request: AssetGenerationRequest, dest_dir: Path) -> Path:
        client = self._get_gradio_client()
        kwargs = self._build_predict_kwargs(request)

        # Attempt shape+texture; fall back to shape-only if the public Space has
        # texture generation disabled (returns NameError via AppError).
        api_name = _API_SHAPE_AND_TEXTURE if request.texture else _API_SHAPE_ONLY
        logger.info(
            "[hunyuan3d2] calling %s for species=%s",
            api_name,
            request.species_id,
        )

        try:
            result = client.predict(api_name=api_name, **kwargs)
        except Exception as exc:
            if request.texture and "NameError" in str(exc):
                logger.warning(
                    "[hunyuan3d2] /generation_all unavailable on public Space "
                    "(texture generation disabled server-side); falling back to shape-only"
                )
                api_name = _API_SHAPE_ONLY
                result = client.predict(api_name=api_name, **kwargs)
            else:
                raise

        logger.debug("[hunyuan3d2] raw result type=%s", type(result))

        def _extract_path(val) -> Optional[str]:
            """gradio_client returns File components as dicts or plain strings."""
            if val is None:
                return None
            if isinstance(val, dict):
                return val.get("value") or val.get("path") or val.get("name")
            return str(val)

        glb_src: Optional[str] = None
        if isinstance(result, (list, tuple)):
            if request.texture and api_name == _API_SHAPE_AND_TEXTURE and len(result) >= 2:
                glb_src = _extract_path(result[1])
                if not glb_src:
                    logger.warning(
                        "[hunyuan3d2] generation_all returned no textured mesh for %s; "
                        "using white mesh",
                        request.species_id,
                    )
                    glb_src = _extract_path(result[0])
            else:
                glb_src = _extract_path(result[0])
        elif isinstance(result, str):
            glb_src = result
        elif isinstance(result, dict):
            glb_src = _extract_path(result)
        else:
            raise RuntimeError(
                f"[hunyuan3d2] unexpected predict() return type {type(result)}: {result!r}"
            )

        if not glb_src:
            raise RuntimeError(
                f"[hunyuan3d2] predict() returned no file path for species {request.species_id}"
            )

        dest_dir.mkdir(parents=True, exist_ok=True)
        src_path = Path(glb_src)
        dest_file = dest_dir / f"{request.species_id}{src_path.suffix or '.glb'}"
        shutil.copy2(str(src_path), str(dest_file))
        logger.info("[hunyuan3d2] downloaded %s -> %s", request.species_id, dest_file)
        return dest_file

    def _cleanup_tmp_dir(self, tmp_dir: Path | None) -> None:
        """Best-effort cleanup for provider-owned temp dirs."""
        if tmp_dir is None:
            return
        try:
            shutil.rmtree(str(tmp_dir), ignore_errors=True)
        except Exception:
            logger.debug("[hunyuan3d2] temp cleanup failed for %s", tmp_dir, exc_info=True)

    def _prune_finished_jobs_locked(self) -> None:
        """Drop stale completed/failed jobs. Caller must hold ``_jobs_lock``."""
        if self._job_retention_s < 0:
            return
        now = time.monotonic()
        expired: list[str] = []
        for job_id, (_thread, holder) in self._jobs.items():
            status = holder.get("status")
            finished_at = holder.get("finished_at")
            if status not in (JobStatus.COMPLETED, JobStatus.FAILED):
                continue
            if finished_at is None:
                continue
            if now - float(finished_at) >= self._job_retention_s:
                expired.append(job_id)
        for job_id in expired:
            _thread, holder = self._jobs.pop(job_id)
            self._cleanup_tmp_dir(holder.get("tmp_dir"))

    # ------------------------------------------------------------------
    # ExternalAssetProvider ABC — submit / poll / download
    # ------------------------------------------------------------------

    def submit(self, request: AssetGenerationRequest) -> str:
        job_id = str(uuid.uuid4())
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"hy3d_{job_id[:8]}_"))
        holder: dict[str, Any] = {
            "status": JobStatus.PENDING,
            "glb_path": None,
            "error": None,
            "tmp_dir": tmp_dir,
            "finished_at": None,
        }

        def _run():
            with self._jobs_lock:
                holder["status"] = JobStatus.PROCESSING
            try:
                glb = self._hf_generate_blocking(request, tmp_dir)
                with self._jobs_lock:
                    holder["glb_path"] = glb
                    holder["status"] = JobStatus.COMPLETED
                    holder["finished_at"] = time.monotonic()
            except Exception as exc:
                logger.error("[hunyuan3d2] job %s failed: %s", job_id, exc)
                self._cleanup_tmp_dir(tmp_dir)
                with self._jobs_lock:
                    holder["error"] = exc
                    holder["status"] = JobStatus.FAILED
                    holder["finished_at"] = time.monotonic()

        t = threading.Thread(target=_run, daemon=True, name=f"hy3d-{job_id[:8]}")
        with self._jobs_lock:
            self._prune_finished_jobs_locked()
            self._jobs[job_id] = (t, holder)
        t.start()
        logger.info("[hunyuan3d2] queued job %s for species %s", job_id, request.species_id)
        return job_id

    def poll(self, job_id: str) -> JobStatus:
        with self._jobs_lock:
            self._prune_finished_jobs_locked()
            entry = self._jobs.get(job_id)
            if entry is None:
                raise KeyError(f"[hunyuan3d2] unknown job_id {job_id!r}")
            _thread, holder = entry
            return holder["status"]

    def download(self, job_id: str, dest_dir: Path, *, species_id: str) -> Path:
        with self._jobs_lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                raise KeyError(f"[hunyuan3d2] unknown job_id {job_id!r}")
            thread, holder = entry
        thread.join(timeout=self._timeout_s)
        if thread.is_alive():
            raise TimeoutError(
                f"[hunyuan3d2] job {job_id} download timed out after "
                f"{self._timeout_s}s for species {species_id}"
            )

        with self._jobs_lock:
            status = holder["status"]
            error = holder.get("error")
            glb_tmp = holder.get("glb_path")
            tmp_dir = holder.get("tmp_dir")
        if status == JobStatus.FAILED:
            with self._jobs_lock:
                self._jobs.pop(job_id, None)
            self._cleanup_tmp_dir(tmp_dir)
            raise RuntimeError(f"[hunyuan3d2] job {job_id} failed: {error}")
        if glb_tmp is None:
            with self._jobs_lock:
                self._jobs.pop(job_id, None)
            self._cleanup_tmp_dir(tmp_dir)
            raise RuntimeError(
                f"[hunyuan3d2] job {job_id} completed without a glb_path (status={status})"
            )
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / glb_tmp.name
        if glb_tmp != dest_file:
            shutil.copy2(str(glb_tmp), str(dest_file))
        with self._jobs_lock:
            self._jobs.pop(job_id, None)
        self._cleanup_tmp_dir(tmp_dir)
        logger.info("[hunyuan3d2] moved %s -> %s", glb_tmp.name, dest_file)
        return dest_file

    # ------------------------------------------------------------------
    # generate_blocking — direct path, skips threading overhead
    # ------------------------------------------------------------------

    def generate_blocking(
        self,
        request: AssetGenerationRequest,
        dest_dir: Path,
        *,
        poll_interval_s: float = 5.0,
        timeout_s: float = 1800.0,
        max_tris: int = 100_000,
    ) -> AssetJobResult:
        return super().generate_blocking(
            request,
            dest_dir,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
            max_tris=max_tris,
        )
