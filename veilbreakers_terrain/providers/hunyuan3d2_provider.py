"""Hunyuan3D-2 provider — HuggingFace Space (default) or HF Inference Endpoint.

Default mode: HuggingFace Space tencent/Hunyuan3D-2 via gradio_client (free, queued, ~90s).
  pip install gradio-client

Faster mode: Set HUNYUAN3D2_HF_ENDPOINT to a private HF Inference Endpoint URL (paid).

Mode selection (checked in order):
  1. (default)               → HuggingFace Space via gradio_client (free, queued, ~90s)
  2. HUNYUAN3D2_HF_ENDPOINT  → HF Inference Endpoint URL (paid, fast)
  3. HUNYUAN3D2_MODE=local   → local api_server.py (requires 16-24 GB VRAM — NOT for 8 GB cards)

HF Space endpoints (tencent/Hunyuan3D-2):
  generation_all    — shape + texture in one call (~90s); outputs white_mesh, textured_mesh, ...
  shape_generation  — shape only (~40s); outputs mesh_file, html, stats, seed

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

import base64
import logging
import os
import shutil
import tempfile
import threading
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
_MODE_LOCAL = "local"

# Default HuggingFace Space slug — the official Tencent space
_DEFAULT_HF_SPACE = "tencent/Hunyuan3D-2"

# Gradio API endpoint names on the Space (verified from gradio_app.py)
#   generation_all   → shape + texture (~90 s)  outputs: white_mesh, textured_mesh, html, stats, seed
#   shape_generation → shape only     (~40 s)  outputs: mesh_file, html, stats, seed
_API_SHAPE_AND_TEXTURE = "/generation_all"
_API_SHAPE_ONLY = "/shape_generation"


class Hunyuan3D2Provider(ExternalAssetProvider):
    """Provider backed by Hunyuan3D-2.

    Supports three execution modes selected by environment variables:

    huggingface (default)
        Uses the public tencent/Hunyuan3D-2 HuggingFace Space via gradio_client.
        Free, queued, ~90 seconds per asset.  Works on any machine — no GPU required.
        Requires: pip install gradio-client

    hf_endpoint
        Uses a private HF Inference Endpoint you deploy yourself.
        Set HUNYUAN3D2_HF_ENDPOINT=https://your-endpoint.huggingface.cloud
        Paid, fast.  Requires: pip install gradio-client

    local  [NOT RECOMMENDED — requires 16-24 GB VRAM]
        Uses a local api_server.py from the Hunyuan3D-2 repo.
        Set HUNYUAN3D2_MODE=local (and optionally HUNYUAN3D2_BASE_URL).
        Only viable on high-end workstation GPUs; will OOM on 8 GB cards.

    ABC contract (submit / poll / download):
        In huggingface and hf_endpoint modes the generation is a single blocking
        predict() call.  submit() runs that call in a background thread and returns
        a synthetic job_id; poll() checks if the thread finished; download() copies
        the result file to dest_dir.  generate_blocking() overrides the base class
        with a simpler, direct implementation that avoids the thread overhead.
    """

    provider_id = "hunyuan3d2"

    # --- local mode defaults (kept for backward compat) ---
    DEFAULT_BASE_URL = "http://127.0.0.1:8080"
    _EP_GENERATE = os.environ.get("HUNYUAN3D2_EP_GENERATE", "/generate")
    _EP_STATUS = os.environ.get("HUNYUAN3D2_EP_STATUS", "/status")
    _EP_TEXTURE = os.environ.get("HUNYUAN3D2_EP_TEXTURE", "/texture")

    def __init__(
        self,
        *,
        mode: Optional[str] = None,
        hf_space: Optional[str] = None,
        hf_endpoint: Optional[str] = None,
        hf_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_connect_s: float = 10.0,
        timeout_read_s: float = 300.0,
    ) -> None:
        """Initialise the provider.

        Parameters
        ----------
        mode:
            Override mode detection.  One of "huggingface", "hf_endpoint", "local".
            Defaults to env var HUNYUAN3D2_MODE, then auto-detected.
        hf_space:
            HuggingFace Space slug (default: "tencent/Hunyuan3D-2").
            Can also be set via HUNYUAN3D2_HF_SPACE env var.
        hf_endpoint:
            Full URL to a private HF Inference Endpoint.
            Can also be set via HUNYUAN3D2_HF_ENDPOINT env var.
        hf_token:
            HuggingFace API token for private Spaces / Endpoints.
            Can also be set via HUGGINGFACE_TOKEN or HF_TOKEN env vars.
        base_url:
            Local server base URL (local mode only).
        timeout_connect_s / timeout_read_s:
            Connection and read timeouts for local-mode requests.
        """
        # --- resolve mode ---
        env_mode = os.environ.get("HUNYUAN3D2_MODE", "").lower()
        env_endpoint = os.environ.get("HUNYUAN3D2_HF_ENDPOINT", "")

        if mode is not None:
            self._mode = mode.lower()
        elif env_mode == "local":
            self._mode = _MODE_LOCAL
        elif env_endpoint or (mode or "").lower() == "hf_endpoint":
            self._mode = _MODE_HF_ENDPOINT
        else:
            self._mode = _MODE_HF_SPACE

        # --- HF Space / Endpoint config ---
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

        # --- local mode config ---
        self._base_url = (
            base_url
            or os.environ.get("HUNYUAN3D2_BASE_URL")
            or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout = (timeout_connect_s, timeout_read_s)

        # --- in-process job registry for submit/poll/download shim ---
        # Maps synthetic job_id -> (thread, result_holder)
        # result_holder is a dict with keys: "status", "glb_path", "error"
        # _jobs_lock guards both the registry mutation and per-holder
        # status reads so poll()/download() never observe a torn write
        # from the worker thread.  Without this, CPython's GIL happens
        # to make the single-key write atomic but the Python memory
        # model does not guarantee it across implementations.
        self._jobs: Dict[str, Tuple[threading.Thread, dict]] = {}
        self._jobs_lock = threading.Lock()

        logger.info(
            "[hunyuan3d2] mode=%s space=%s endpoint=%s",
            self._mode,
            self._hf_space if self._mode == _MODE_HF_SPACE else "(n/a)",
            self._hf_endpoint if self._mode == _MODE_HF_ENDPOINT else "(n/a)",
        )

    # ------------------------------------------------------------------
    # gradio_client helpers
    # ------------------------------------------------------------------

    def _get_gradio_client(self):
        """Return a connected gradio_client.Client instance."""
        try:
            from gradio_client import Client  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "gradio-client is required for HuggingFace mode: "
                "pip install gradio-client"
            ) from exc

        if self._mode == _MODE_HF_ENDPOINT:
            src = self._hf_endpoint
        else:
            src = self._hf_space

        kwargs: dict[str, Any] = {}
        if self._hf_token:
            kwargs["hf_token"] = self._hf_token

        logger.debug("[hunyuan3d2] connecting gradio_client to %s", src)
        return Client(src, **kwargs)

    def _build_predict_kwargs(self, request: AssetGenerationRequest) -> dict:
        """Build the keyword arguments for the Gradio predict() call."""
        from gradio_client import handle_file  # type: ignore

        steps = 30 if request.quality == "high" else 5
        octree_res = 256 if request.quality == "high" else 128
        seed = request.seed if request.seed is not None else 1234

        kwargs: dict[str, Any] = {
            "caption": request.prompt,
            "steps": steps,
            "guidance_scale": 5.0,
            "seed": seed,
            "octree_resolution": octree_res,
            "check_box_rembg": True,  # remove background automatically
            "num_chunks": 8000,
            "randomize_seed": False,
        }

        if request.image_path is not None:
            kwargs["image"] = handle_file(str(request.image_path))

        # Multi-view inputs not supported in single-image mode; leave as None
        for mv_key in ("mv_image_front", "mv_image_back", "mv_image_left", "mv_image_right"):
            kwargs[mv_key] = None

        return kwargs

    def _hf_generate_blocking(
        self,
        request: AssetGenerationRequest,
        dest_dir: Path,
    ) -> Path:
        """Call the HF Space directly via gradio_client.predict() and return the GLB path.

        Uses generation_all (shape + texture) when request.texture=True, otherwise
        shape_generation (shape only).

        The Space returns file paths on the Gradio server; gradio_client downloads
        them to a local temp directory automatically.  We copy the result into
        dest_dir and return the final path.

        Return value: Path to the downloaded .glb file in dest_dir.
        """
        client = self._get_gradio_client()
        kwargs = self._build_predict_kwargs(request)

        if request.texture:
            api_name = _API_SHAPE_AND_TEXTURE
            logger.info(
                "[hunyuan3d2] calling %s for species=%s (shape+texture, ~90s queue)",
                api_name,
                request.species_id,
            )
        else:
            api_name = _API_SHAPE_ONLY
            logger.info(
                "[hunyuan3d2] calling %s for species=%s (shape only, ~40s queue)",
                api_name,
                request.species_id,
            )

        # predict() blocks until the Space finishes (including queue wait).
        # generation_all returns: (white_mesh_path, textured_mesh_path, html, stats, seed)
        # shape_generation returns: (mesh_file_path, html, stats, seed)
        result = client.predict(api_name=api_name, **kwargs)

        logger.debug("[hunyuan3d2] raw result type=%s", type(result))

        # Extract the GLB path from the result tuple.
        # Both endpoints return the mesh as the first element when texture=False,
        # or the textured mesh as the second element for generation_all.
        glb_src: Optional[str] = None
        if isinstance(result, (list, tuple)):
            if request.texture and len(result) >= 2:
                # generation_all: index 1 = textured mesh (index 0 = white/untextured)
                if result[1] is not None:
                    glb_src = str(result[1])
                else:
                    # The Space failed to texture — degrading to the white mesh
                    # would silently strip PBR.  Loud-fail instead so the caller
                    # can retry or pick another provider; AAA pipelines must
                    # never substitute an untextured mesh for a textured one
                    # without consent.
                    raise RuntimeError(
                        f"[hunyuan3d2] generation_all returned no textured mesh "
                        f"for species {request.species_id}; the HF Space likely "
                        f"failed mid-texturing (white_mesh={result[0]!r}). "
                        f"Retry, or call with texture=False to accept shape only."
                    )
            else:
                # shape_generation or fallback: index 0 = mesh file
                glb_src = str(result[0])
        elif isinstance(result, str):
            glb_src = result
        else:
            raise RuntimeError(
                f"[hunyuan3d2] unexpected predict() return type {type(result)}: {result!r}"
            )

        if not glb_src:
            raise RuntimeError(
                f"[hunyuan3d2] predict() returned no file path for species {request.species_id}: {result!r}"
            )

        # Copy from gradio temp dir to our dest_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        src_path = Path(glb_src)
        suffix = src_path.suffix or ".glb"
        dest_file = dest_dir / f"{request.species_id}{suffix}"
        shutil.copy2(str(src_path), str(dest_file))
        logger.info(
            "[hunyuan3d2] downloaded %s -> %s", request.species_id, dest_file
        )
        return dest_file

    # ------------------------------------------------------------------
    # ExternalAssetProvider ABC — submit / poll / download
    # (thin async shim over the blocking gradio_client call)
    # ------------------------------------------------------------------

    def submit(self, request: AssetGenerationRequest) -> str:
        """Submit a generation job.

        HF Space / Endpoint modes: spawns a background thread running the blocking
        predict() call and returns a synthetic UUID job_id.  Use generate_blocking()
        for a simpler, direct call that avoids the threading overhead.

        Local mode: POST /generate → {"uid": "..."}
        """
        if self._mode == _MODE_LOCAL:
            return self._local_submit(request)

        job_id = str(uuid.uuid4())
        holder: dict[str, Any] = {"status": JobStatus.PENDING, "glb_path": None, "error": None}
        # Store a placeholder dest_dir; download() will copy to the real dest.
        # We use a temp directory so the thread has somewhere to write.
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"hy3d_{job_id[:8]}_"))

        def _run():
            with self._jobs_lock:
                holder["status"] = JobStatus.PROCESSING
            try:
                glb = self._hf_generate_blocking(request, tmp_dir)
                with self._jobs_lock:
                    holder["glb_path"] = glb
                    holder["status"] = JobStatus.COMPLETED
            except Exception as exc:
                logger.error("[hunyuan3d2] job %s failed: %s", job_id, exc)
                with self._jobs_lock:
                    holder["error"] = exc
                    holder["status"] = JobStatus.FAILED

        t = threading.Thread(target=_run, daemon=True, name=f"hy3d-{job_id[:8]}")
        with self._jobs_lock:
            self._jobs[job_id] = (t, holder)
        t.start()
        logger.info(
            "[hunyuan3d2] queued job %s for species %s (mode=%s)",
            job_id,
            request.species_id,
            self._mode,
        )
        return job_id

    def poll(self, job_id: str) -> JobStatus:
        """Return current job status.

        HF / Endpoint modes: checks background thread state from job registry.
        Local mode: GET /status/{uid}.
        """
        if self._mode == _MODE_LOCAL:
            return self._local_poll(job_id)

        with self._jobs_lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                raise KeyError(f"[hunyuan3d2] unknown job_id {job_id!r}")
            _thread, holder = entry
            return holder["status"]

    def download(self, job_id: str, dest_dir: Path, *, species_id: str) -> Path:
        """Copy the completed GLB from the thread's temp dir to dest_dir.

        Blocks until the background thread finishes (if still running).
        Local mode: polls the local server for the base64/URL result.
        """
        if self._mode == _MODE_LOCAL:
            return self._local_download(job_id, dest_dir, species_id=species_id)

        with self._jobs_lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                raise KeyError(f"[hunyuan3d2] unknown job_id {job_id!r}")
            thread, holder = entry
        thread.join()  # wait for completion if still running

        with self._jobs_lock:
            status = holder["status"]
            error = holder.get("error")
            glb_tmp = holder.get("glb_path")
        if status == JobStatus.FAILED:
            raise RuntimeError(
                f"[hunyuan3d2] job {job_id} failed: {error}"
            )
        if glb_tmp is None:
            raise RuntimeError(
                f"[hunyuan3d2] job {job_id} completed without a glb_path "
                f"(status={status})"
            )
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / glb_tmp.name
        if glb_tmp != dest_file:
            shutil.copy2(str(glb_tmp), str(dest_file))
        # Clean up the temp dir
        try:
            shutil.rmtree(str(glb_tmp.parent), ignore_errors=True)
        except Exception:
            pass
        logger.info("[hunyuan3d2] moved %s -> %s", glb_tmp.name, dest_file)
        return dest_file

    # ------------------------------------------------------------------
    # generate_blocking override — skip threading for HF modes
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
        """Generate, download, and validate an asset synchronously.

        HF Space / Endpoint modes bypass the submit/poll/download threading shim
        and call predict() directly in the calling thread (simpler, avoids overhead).

        Local mode falls back to the base class submit → poll → download loop.
        """
        if self._mode == _MODE_LOCAL:
            # Delegate to the base class loop which handles polling properly
            return super().generate_blocking(
                request,
                dest_dir,
                poll_interval_s=poll_interval_s,
                timeout_s=timeout_s,
                max_tris=max_tris,
            )

        # Direct blocking path for HF Space / Endpoint.
        # gradio_client.predict() has no native timeout — wrap it in a thread
        # bounded by timeout_s so a stuck Space queue cannot hang the pipeline
        # indefinitely.  AAA pipelines must always have a hard ceiling.
        dest_dir.mkdir(parents=True, exist_ok=True)

        result_box: dict[str, Any] = {"glb": None, "exc": None}

        def _runner() -> None:
            try:
                result_box["glb"] = self._hf_generate_blocking(request, dest_dir)
            except BaseException as exc:  # noqa: BLE001 — propagate via box
                result_box["exc"] = exc

        worker = threading.Thread(
            target=_runner,
            daemon=True,
            name=f"hy3d-blocking-{request.species_id[:16]}",
        )
        worker.start()
        worker.join(timeout=timeout_s)
        if worker.is_alive():
            # Daemon thread will be torn down at interpreter exit; we cannot
            # cancel the underlying HTTP request, but we surface a clean
            # TimeoutError so the caller can move on or retry.
            raise TimeoutError(
                f"[hunyuan3d2] generate_blocking exceeded timeout_s={timeout_s}s "
                f"for species {request.species_id} (mode={self._mode}); "
                f"underlying gradio_client.predict() may still be running in the "
                f"background daemon thread."
            )
        if result_box["exc"] is not None:
            raise result_box["exc"]  # type: ignore[misc]
        glb_path = result_box["glb"]
        if glb_path is None:
            raise RuntimeError(
                f"[hunyuan3d2] generate_blocking finished with no glb_path for "
                f"species {request.species_id}"
            )

        result = self.validate(
            glb_path,
            species_id=request.species_id,
            max_tris=max_tris,
            require_pbr=request.require_pbr,
        )
        result.job_id = glb_path.stem  # use filename stem as synthetic id
        if not result.validated:
            logger.warning(
                "[hunyuan3d2] asset %s validation issues: %s",
                request.species_id,
                result.validation_issues,
            )
        return result

    # ------------------------------------------------------------------
    # Local mode implementation (kept intact for future GPU use)
    # ------------------------------------------------------------------

    def _requests(self):
        try:
            import requests  # type: ignore
        except ImportError as exc:
            raise RuntimeError("requests is required: pip install requests") from exc
        return requests

    def _local_submit(self, request: AssetGenerationRequest) -> str:
        """POST /generate → {"uid": "..."}"""
        requests = self._requests()
        payload: dict = {
            "prompt": request.prompt,
            "seed": request.seed if request.seed is not None else 0,
            "num_steps": 50 if request.quality == "high" else 25,
            "guidance_scale": 7.5,
            "octree_resolution": 256 if request.quality == "high" else 128,
        }
        files = {}
        if request.image_path is not None:
            files["image"] = open(request.image_path, "rb")
        try:
            resp = requests.post(
                f"{self._base_url}{self._EP_GENERATE}",
                data=payload,
                files=files or None,
                timeout=self._timeout,
            )
        finally:
            for fh in files.values():
                fh.close()
        resp.raise_for_status()
        body = resp.json()
        uid = body.get("uid") or body.get("job_id") or body.get("id")
        if not uid:
            raise RuntimeError(f"Hunyuan3D-2 local submit returned no uid: {body}")
        logger.debug(
            "[hunyuan3d2] local submitted uid=%s for species %s",
            uid,
            request.species_id,
        )
        return str(uid)

    def _local_poll(self, job_id: str) -> JobStatus:
        """GET /status/{uid} → {"status": "processing"|"completed"|"failed"}"""
        requests = self._requests()
        resp = requests.get(
            f"{self._base_url}{self._EP_STATUS}/{job_id}",
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        raw = (body.get("status") or "").lower()
        if raw in {"completed", "done", "success", "finished"}:
            return JobStatus.COMPLETED
        if raw in {"failed", "error", "cancelled"}:
            return JobStatus.FAILED
        if raw in {"processing", "running", "generating"}:
            return JobStatus.PROCESSING
        return JobStatus.PENDING

    def _local_request_texture(self, uid: str) -> None:
        """POST /texture/{uid} — triggers texture generation for a completed shape."""
        requests = self._requests()
        resp = requests.post(
            f"{self._base_url}{self._EP_TEXTURE}/{uid}",
            timeout=(self._timeout[0], 600.0),
        )
        resp.raise_for_status()

    def _local_download(self, job_id: str, dest_dir: Path, *, species_id: str) -> Path:
        """Download the GLB from the local server's completed status response."""
        requests = self._requests()
        resp = requests.get(
            f"{self._base_url}{self._EP_STATUS}/{job_id}",
            timeout=(self._timeout[0], 300.0),
        )
        resp.raise_for_status()
        body = resp.json()

        # Attempt direct download URL first
        download_url = body.get("download_url") or body.get("glb_url")
        if download_url:
            dest = dest_dir / f"{species_id}_{job_id[:8]}.glb"
            with requests.get(download_url, stream=True, timeout=120) as r:
                r.raise_for_status()
                dest.write_bytes(r.content)
            logger.info("[hunyuan3d2] local downloaded %s -> %s", species_id, dest)
            return dest

        # Fall back to base64-encoded model in response body
        model_b64 = body.get("model_base64") or body.get("glb_base64")
        if model_b64:
            dest = dest_dir / f"{species_id}_{job_id[:8]}.glb"
            dest.write_bytes(base64.b64decode(model_b64))
            logger.info(
                "[hunyuan3d2] local decoded base64 GLB %s -> %s", species_id, dest
            )
            return dest

        raise RuntimeError(
            f"Hunyuan3D-2 local completed job {job_id} has no download_url or "
            f"model_base64 in response: {list(body.keys())}"
        )
