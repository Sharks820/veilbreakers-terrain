"""Hunyuan3D-2 local API provider for AI-generated terrain assets.

Requires:
  - Tencent Hunyuan3D-2 repo running locally (https://github.com/Tencent/Hunyuan3D-2)
  - api_server.py started on DEFAULT_BASE_URL (default: http://127.0.0.1:8080)
  - 16-24 GB VRAM for shape + texture pipeline
  - hunyuan3d2 v2.1+ for full PBR (albedo + normal + roughness + ORM packed)

Usage:
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
import tempfile
from pathlib import Path
from typing import Optional

from .external_asset_provider import (
    AssetGenerationRequest,
    ExternalAssetProvider,
    JobStatus,
)

logger = logging.getLogger(__name__)


class Hunyuan3D2Provider(ExternalAssetProvider):
    """Provider backed by Hunyuan3D-2 local API server.

    The server exposes two-stage generation:
      1. Shape:   POST /generate   → {"uid": "..."}
      2. Texture: POST /texture    → same uid, blocks until textured

    With texture=True the provider chains both calls and returns a fully
    textured GLB. With texture=False only the geometry is returned.
    """

    provider_id = "hunyuan3d2"
    DEFAULT_BASE_URL = "http://127.0.0.1:8080"

    # Endpoint paths — override via env vars for non-standard server builds
    _EP_GENERATE = os.environ.get("HUNYUAN3D2_EP_GENERATE", "/generate")
    _EP_STATUS = os.environ.get("HUNYUAN3D2_EP_STATUS", "/status")
    _EP_TEXTURE = os.environ.get("HUNYUAN3D2_EP_TEXTURE", "/texture")

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout_connect_s: float = 10.0,
        timeout_read_s: float = 120.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("HUNYUAN3D2_BASE_URL")
            or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout = (timeout_connect_s, timeout_read_s)

    def _requests(self):
        try:
            import requests  # type: ignore
        except ImportError as exc:
            raise RuntimeError("requests is required: pip install requests") from exc
        return requests

    def submit(self, request: AssetGenerationRequest) -> str:
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
                f"{self.base_url}{self._EP_GENERATE}",
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
            raise RuntimeError(f"Hunyuan3D-2 submit returned no uid: {body}")
        logger.debug("[hunyuan3d2] submitted uid=%s for species %s", uid, request.species_id)
        return str(uid)

    def poll(self, job_id: str) -> JobStatus:
        """GET /status/{uid} → {"status": "processing"|"completed"|"failed"}"""
        requests = self._requests()
        resp = requests.get(
            f"{self.base_url}{self._EP_STATUS}/{job_id}",
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

    def _request_texture(self, uid: str) -> None:
        """POST /texture/{uid} — triggers texture generation for a completed shape."""
        requests = self._requests()
        resp = requests.post(
            f"{self.base_url}{self._EP_TEXTURE}/{uid}",
            timeout=(self._timeout[0], 600.0),
        )
        resp.raise_for_status()

    def download(self, job_id: str, dest_dir: Path, *, species_id: str) -> Path:
        """Download the GLB from the completed status response.

        Hunyuan3D-2 api_server embeds the model as base64 in the status response
        once generation is complete. This method re-polls once to get the final
        response with model_base64 and decodes it to a GLB file.
        """
        requests = self._requests()
        resp = requests.get(
            f"{self.base_url}{self._EP_STATUS}/{job_id}",
            timeout=(self._timeout[0], 300.0),
        )
        resp.raise_for_status()
        body = resp.json()

        # Attempt direct download URL first (some server builds expose one)
        download_url = body.get("download_url") or body.get("glb_url")
        if download_url:
            dest = dest_dir / f"{species_id}_{job_id[:8]}.glb"
            with requests.get(download_url, stream=True, timeout=120) as r:
                r.raise_for_status()
                dest.write_bytes(r.content)
            logger.info("[hunyuan3d2] downloaded %s -> %s", species_id, dest)
            return dest

        # Fall back to base64-encoded model in response body
        model_b64 = body.get("model_base64") or body.get("glb_base64")
        if model_b64:
            dest = dest_dir / f"{species_id}_{job_id[:8]}.glb"
            dest.write_bytes(base64.b64decode(model_b64))
            logger.info("[hunyuan3d2] decoded base64 GLB %s -> %s", species_id, dest)
            return dest

        raise RuntimeError(
            f"Hunyuan3D-2 completed job {job_id} has no download_url or model_base64 in response: "
            f"{list(body.keys())}"
        )
