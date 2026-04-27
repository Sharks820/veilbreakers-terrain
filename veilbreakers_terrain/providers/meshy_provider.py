"""Meshy AI provider — image-to-3D via Meshy REST API v2.

Submits image-to-3D (or text-to-3D) generation jobs to Meshy AI, polls for
completion, and downloads the resulting GLB with PBR materials.

Authentication:
    Set MESHY_API_KEY environment variable, or pass api_key= to __init__.

Example usage:
    from veilbreakers_terrain.providers import MeshyProvider, AssetGenerationRequest
    from pathlib import Path

    provider = MeshyProvider()
    result = provider.generate_blocking(
        AssetGenerationRequest(
            species_id="dark_oak_hero",
            prompt="ancient gnarled dark oak tree, dead branches, dark fantasy",
            image_path=Path("reference/dark_oak_ref.jpg"),
            require_pbr=True,
            target_tris=50_000,
        ),
        dest_dir=Path("output/assets/trees"),
    )
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Optional

from .external_asset_provider import (
    AssetGenerationRequest,
    AssetJobResult,
    ExternalAssetProvider,
    JobStatus,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.meshy.ai"
_IMAGE_TO_3D_ENDPOINT = "/openapi/v2/image-to-3d"

# Meshy status string → JobStatus mapping
_STATUS_MAP: dict[str, JobStatus] = {
    "PENDING": JobStatus.PENDING,
    "IN_PROGRESS": JobStatus.PROCESSING,
    "SUCCEEDED": JobStatus.COMPLETED,
    "FAILED": JobStatus.FAILED,
    "EXPIRED": JobStatus.FAILED,
}


def _get_requests():
    try:
        import requests  # type: ignore
        return requests
    except ImportError as exc:
        raise RuntimeError("requests is required: pip install requests") from exc


class MeshyProvider(ExternalAssetProvider):
    """Provider backed by the Meshy AI REST API v2.

    Supports image-to-3D generation with PBR textures via meshy.ai.
    Requires a valid API key from https://www.meshy.ai/.

    ABC contract (submit / poll / download):
        submit() sends the image-to-3D job and returns a Meshy task_id string.
        poll() GETs the task status without blocking.
        download() fetches the GLB from the pre-signed URL and writes it to disk.
        Use generate_blocking() for the simpler direct path.
    """

    provider_id = "meshy"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        ai_model: str = "meshy-4",
        topology: str = "quad",
        timeout_s: float = 600.0,
    ) -> None:
        """Initialise the provider.

        Parameters
        ----------
        api_key:
            Meshy AI API key. Falls back to MESHY_API_KEY env var.
            Raises RuntimeError if neither is set.
        ai_model:
            Meshy model to use (default: "meshy-4", the latest).
        topology:
            Mesh topology: "quad" or "triangle" (default: "quad").
        timeout_s:
            Default hard timeout for generate_blocking() in seconds.
        """
        self._api_key = api_key or os.environ.get("MESHY_API_KEY", "")
        if not self._api_key:
            raise RuntimeError("MESHY_API_KEY not set")

        self._ai_model = ai_model
        self._topology = topology
        self._timeout_s = timeout_s

        logger.info(
            "[meshy] initialised provider model=%s topology=%s",
            self._ai_model,
            self._topology,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _poll_raw(self, job_id: str) -> dict:
        """Fetch raw task dict from Meshy API."""
        requests = _get_requests()
        url = f"{_BASE_URL}{_IMAGE_TO_3D_ENDPOINT}/{job_id}"
        resp = requests.get(url, headers=self._auth_headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # ExternalAssetProvider ABC — submit / poll / download
    # ------------------------------------------------------------------

    def submit(self, request: AssetGenerationRequest) -> str:
        """POST image-to-3D job to Meshy and return the task_id."""
        requests = _get_requests()

        payload: dict = {
            "ai_model": self._ai_model,
            "topology": self._topology,
            "target_polycount": request.target_tris,
            "should_remesh": True,
            "enable_pbr": request.require_pbr,
        }

        if request.image_path is not None:
            # Base64-encode the local image file
            img_bytes = Path(request.image_path).read_bytes()
            b64 = base64.b64encode(img_bytes).decode("ascii")
            # Determine MIME type from extension
            ext = Path(request.image_path).suffix.lower()
            mime = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
            }.get(ext, "image/jpeg")
            payload["image_file"] = f"data:{mime};base64,{b64}"
        else:
            # Text-to-3D fallback — Meshy accepts a prompt as object_prompt
            payload["object_prompt"] = request.prompt

        url = f"{_BASE_URL}{_IMAGE_TO_3D_ENDPOINT}"
        resp = requests.post(url, json=payload, headers=self._auth_headers(), timeout=60)
        resp.raise_for_status()

        data = resp.json()
        task_id: str = data["result"]
        logger.info(
            "[meshy] submitted job task_id=%s for species=%s",
            task_id,
            request.species_id,
        )
        return task_id

    def poll(self, job_id: str) -> JobStatus:
        """GET task status and return mapped JobStatus."""
        data = self._poll_raw(job_id)
        meshy_status: str = data.get("status", "PENDING")
        status = _STATUS_MAP.get(meshy_status, JobStatus.PENDING)
        progress = data.get("progress", 0)
        logger.debug(
            "[meshy] job %s status=%s progress=%s%%",
            job_id,
            meshy_status,
            progress,
        )
        return status

    def download(self, job_id: str, dest_dir: Path, *, species_id: str) -> Path:
        """Download the GLB from the completed task and write to dest_dir/{species_id}.glb."""
        requests = _get_requests()

        data = self._poll_raw(job_id)
        meshy_status = data.get("status", "")

        if meshy_status == "FAILED" or meshy_status == "EXPIRED":
            error_msg = ""
            task_error = data.get("task_error")
            if task_error:
                error_msg = task_error.get("message", "")
            raise RuntimeError(
                f"[meshy] job {job_id} {meshy_status.lower()}: {error_msg}"
            )

        model_urls = data.get("model_urls") or {}
        glb_url = model_urls.get("glb")
        if not glb_url:
            raise RuntimeError(
                f"[meshy] job {job_id} has no glb URL in model_urls (status={meshy_status})"
            )

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"{species_id}.glb"

        logger.info("[meshy] downloading GLB for species=%s from %s", species_id, glb_url)
        # Pre-signed URLs don't require auth headers
        resp = requests.get(glb_url, timeout=120, stream=True)
        resp.raise_for_status()
        with dest_file.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)

        logger.info("[meshy] downloaded %s -> %s", species_id, dest_file)
        return dest_file

    # ------------------------------------------------------------------
    # generate_blocking — poll loop with timeout + validation
    # ------------------------------------------------------------------

    def generate_blocking(
        self,
        request: AssetGenerationRequest,
        dest_dir: Path,
        *,
        poll_interval_s: float = 10.0,
        timeout_s: float = 600.0,
        max_tris: int = 100_000,
    ) -> AssetJobResult:
        """Submit, poll, download, and validate in one blocking call."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        job_id = self.submit(request)
        logger.info(
            "[meshy] submitted job %s for species %s",
            job_id,
            request.species_id,
        )

        deadline = time.monotonic() + timeout_s
        while True:
            status = self.poll(job_id)
            if status == JobStatus.COMPLETED:
                break
            if status == JobStatus.FAILED:
                raise RuntimeError(f"[meshy] job {job_id} failed")
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"[meshy] job {job_id} timed out after {timeout_s}s"
                )
            logger.debug(
                "[meshy] job %s status=%s — waiting %.0fs",
                job_id,
                status,
                poll_interval_s,
            )
            time.sleep(poll_interval_s)

        glb_path = self.download(job_id, dest_dir, species_id=request.species_id)
        result = self.validate(
            glb_path,
            species_id=request.species_id,
            max_tris=max_tris,
            require_pbr=request.require_pbr,
        )
        result.job_id = job_id

        if not result.validated:
            logger.warning(
                "[meshy] asset %s validation issues: %s",
                request.species_id,
                result.validation_issues,
            )
        return result
