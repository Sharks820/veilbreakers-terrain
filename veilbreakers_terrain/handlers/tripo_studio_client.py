"""Tripo Studio client — uses studio/web credits via /v2/web/ endpoints.

Ported from veilbreakers-gamedev-toolkit
``Tools/mcp-toolkit/src/veilbreakers_mcp/shared/tripo_studio_client.py``.

Unlike the API client (which uses /v2/openapi/ and API credits),
this client hits /v2/web/ endpoints using a studio session JWT,
allowing use of subscription/studio credits.

Supports two auth modes:

1. **Session cookie** (preferred): Long-lived Kratos session cookie
   (``ory_kratos_session``) that auto-refreshes JWTs. Lasts ~25 days.
2. **JWT token**: Short-lived (2h) Bearer token from browser DevTools.
"""

from __future__ import annotations

import asyncio
import binascii
import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from veilbreakers_terrain.handlers.tripo_model_validation import (
    validate_generated_model_file,
)

logger = logging.getLogger(__name__)

STUDIO_BASE_URL = "https://api.tripo3d.ai/v2/web"


class TripoStudioClient:
    """Client for Tripo Studio /v2/web/ API using studio credits.

    Usage::

        # Auto-refresh via session cookie (recommended):
        client = TripoStudioClient(session_cookie="MTc3...")

        # Or direct JWT (expires in 2h):
        client = TripoStudioClient(session_token="eyJ...")

        result = await client.generate_from_text("a wooden barrel", "/output")
    """

    def __init__(
        self,
        session_token: str = "",
        session_cookie: str = "",
    ):
        if not session_token and not session_cookie:
            raise ValueError(
                "Either session_token (JWT) or session_cookie "
                "(ory_kratos_session) is required."
            )
        # Strip "Bearer " prefix if user included it
        if session_token and session_token.lower().startswith("bearer "):
            session_token = session_token[7:]

        self._jwt: str = session_token
        self._jwt_exp: float = 0.0  # Unix timestamp when JWT expires
        self._session_cookie: str = session_cookie
        self._client: httpx.AsyncClient | None = None
        self._client_jwt: str = ""  # JWT the current client was created with

        # If we have a JWT, parse its expiry
        if self._jwt:
            self._jwt_exp = self._parse_jwt_exp(self._jwt)

    @staticmethod
    def _parse_jwt_exp(jwt: str) -> float:
        """Extract expiry timestamp from a JWT without verification."""
        try:
            payload = jwt.split(".")[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            data = json.loads(base64.urlsafe_b64decode(payload))
            return float(data.get("exp", 0))
        except (IndexError, TypeError, ValueError, json.JSONDecodeError, binascii.Error):
            return 0.0

    async def _refresh_jwt(self) -> str:
        """Get a fresh JWT using the long-lived ory_kratos_session cookie.

        Tripo migrated JWT minting to the browser (client-side), so the
        SSR page no longer embeds a JWT in HTML. We instead try the API
        and Nuxt session endpoints the browser JS calls at page-load time,
        then fall back to the original HTML scrape.
        """
        if not self._session_cookie:
            raise RuntimeError(
                "Cannot refresh JWT: no session_cookie configured. "
                "Set TRIPO_SESSION_COOKIE env var."
            )
        cookie_header = {"Cookie": f"ory_kratos_session={self._session_cookie}"}
        jwt_pattern = re.compile(
            r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
        )

        def _pick_jwt(text: str) -> str:
            """Return the longest JWT found in text (avoids fragment matches)."""
            candidates = jwt_pattern.findall(text)
            return max(candidates, key=len) if candidates else ""

        async with httpx.AsyncClient(
            timeout=15.0, follow_redirects=True
        ) as client:
            # 1. Ory Kratos session tokenization — the canonical path.
            #    Tripo runs Kratos on auth.tripo3d.ai with session tokenization
            #    enabled. GET /sessions/whoami with the session cookie returns
            #    {"tokenized": "eyJ..."} — a signed JWT for the live session.
            #    This is the same endpoint the browser JS calls to keep its
            #    Bearer token fresh on a ~30-minute cycle.
            try:
                resp = await client.get(
                    "https://auth.tripo3d.ai/sessions/whoami",
                    headers=cookie_header,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    tokenized = data.get("tokenized", "")
                    if tokenized and tokenized.startswith("eyJ"):
                        logger.info("Refreshed JWT via Kratos sessions/whoami")
                        self._jwt = tokenized
                        self._jwt_exp = self._parse_jwt_exp(tokenized)
                        return tokenized
                    # Fallback: JWT might appear anywhere in the JSON body
                    jwt = _pick_jwt(resp.text)
                    if jwt:
                        logger.info("Refreshed JWT via Kratos whoami body")
                        self._jwt = jwt
                        self._jwt_exp = self._parse_jwt_exp(jwt)
                        return jwt
            except Exception:
                pass

            # 2. Nuxt server-side session route variants
            for path in (
                "/api/_auth/session",
                "/api/auth/session",
                "/api/session",
                "/api/auth/token",
            ):
                try:
                    resp = await client.get(
                        f"https://studio.tripo3d.ai{path}",
                        headers=cookie_header,
                    )
                    if resp.status_code == 200:
                        jwt = _pick_jwt(resp.text)
                        if jwt:
                            logger.info("Refreshed JWT via studio%s", path)
                            self._jwt = jwt
                            self._jwt_exp = self._parse_jwt_exp(jwt)
                            return jwt
                except Exception:
                    pass

            # 3. Original SSR HTML scrape (kept as last resort)
            try:
                resp = await client.get(
                    "https://studio.tripo3d.ai/",
                    headers=cookie_header,
                )
                jwt = _pick_jwt(resp.text)
                if jwt:
                    logger.info("Refreshed JWT via studio HTML page")
                    self._jwt = jwt
                    self._jwt_exp = self._parse_jwt_exp(jwt)
                    return jwt
            except Exception:
                pass

        raise RuntimeError(
            "Failed to auto-refresh JWT from Tripo Studio. "
            "The session cookie auth flow may have changed. "
            "Manual fix: open studio.tripo3d.ai in Edge > F12 > Network tab > "
            "click any api.tripo3d.ai GET/POST > Request Headers > "
            "copy the value after 'Authorization: Bearer ' and set "
            "TRIPO_SESSION_TOKEN=<token> in .env.tripo_studio."
        )

    async def _get_valid_jwt(self) -> str:
        """Return a valid JWT, refreshing if needed."""
        now = time.time()
        # Refresh if expired or expiring within 5 minutes
        if (
            not self._jwt
            or self._jwt_exp <= 0
            or now > self._jwt_exp - 300
        ):
            if self._session_cookie:
                await self._refresh_jwt()
            else:
                raise RuntimeError(
                    "JWT expired and no session_cookie for refresh."
                )
        return self._jwt

    async def _ensure_client(self) -> httpx.AsyncClient:
        jwt = await self._get_valid_jwt()
        if self._client and not self._client.is_closed and self._client_jwt == jwt:
            return self._client
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {jwt}",
                "Content-Type": "application/json",
                "x-tripo-region": "rg1",
            },
            timeout=60.0,
        )
        self._client_jwt = jwt
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self, method: str, path: str, json_data: dict | None = None
    ) -> dict:
        client = await self._ensure_client()
        url = f"{STUDIO_BASE_URL}{path}"
        resp = await client.request(method, url, json=json_data)
        data = resp.json()
        if resp.status_code >= 400:
            code = data.get("code", resp.status_code)
            msg = data.get("message", resp.reason_phrase)
            suggestion = data.get("suggestion", "")
            raise RuntimeError(
                f"Tripo Studio API error {code}: {msg}. {suggestion}"
            )
        return data

    async def get_balance(self) -> dict:
        """Get studio credit balance."""
        resp = await self._request("GET", "/user/profile/payment")
        return resp.get("data", resp)

    async def create_task(self, task_data: dict[str, Any]) -> list[str]:
        """Create a generation task, returns list of task_ids (studio creates variants)."""
        resp = await self._request("POST", "/task", json_data=task_data)
        data = resp.get("data", {})
        # Studio returns task_ids (plural) as a list of variants
        if "task_ids" in data:
            return data["task_ids"]
        # Fallback for single task_id
        if "task_id" in data:
            return [data["task_id"]]
        raise RuntimeError(f"No task_id in response: {resp}")

    async def get_task(self, task_id: str) -> dict:
        """Poll task status."""
        resp = await self._request("GET", f"/task/{task_id}")
        return resp.get("data", resp)

    async def wait_for_task(
        self,
        task_id: str,
        timeout: float = 300,
        polling_interval: float = 3.0,
    ) -> dict:
        """Poll until task completes or fails."""
        start = time.monotonic()
        while True:
            task = await self.get_task(task_id)
            status = task.get("status", "unknown")
            if status == "success":
                return task
            if status in ("failed", "banned", "cancelled"):
                raise RuntimeError(
                    f"Task {task_id} ended with status: {status}"
                )
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                raise TimeoutError(
                    f"Task {task_id} timed out after {timeout}s (status: {status})"
                )
            # Adaptive polling
            left = task.get("running_left_time")
            if left is not None and left > 0:
                wait = max(2.0, left * 0.5)
            else:
                wait = polling_interval
            await asyncio.sleep(wait)

    async def _download_file(self, url: str, output_path: str) -> str:
        """Download a model file to local path.

        Uses a separate httpx client WITHOUT auth headers to avoid leaking
        Bearer tokens to third-party CDN hosts.
        """
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as download_client:
            async with download_client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise RuntimeError(f"Download failed: {resp.status_code} {resp.reason_phrase}")
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
        validation = validate_generated_model_file(output_path)
        if not validation.get("valid", False):
            try:
                Path(output_path).unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError(
                f"Downloaded model failed validation: {validation.get('error', 'unknown')}"
            )
        return output_path

    async def _poll_and_download_variants(
        self,
        task_ids: list[str],
        output_dir: str,
        max_variants: int = 2,
        timeout: float = 300,
    ) -> dict:
        """Poll up to *max_variants* tasks and download their models.

        Returns a result dict with ``models`` list and verification info.
        """
        os.makedirs(output_dir, exist_ok=True)
        use_ids = task_ids[:max_variants]
        models: list[dict] = []

        for i, tid in enumerate(use_ids):
            tag = f"v{i + 1}"
            try:
                task_result = await self.wait_for_task(tid, timeout=timeout)
                pbr_url = task_result.get("pbr_model")
                if pbr_url:
                    fname = f"model_{tag}_pbr.glb" if len(use_ids) > 1 else "model_pbr.glb"
                    out_path = str(Path(output_dir) / fname)
                    await self._download_file(pbr_url, out_path)
                    size = Path(out_path).stat().st_size
                    models.append({
                        "task_id": tid,
                        "variant": tag,
                        "path": out_path,
                        "size_bytes": size,
                        "verified": size > 1000,
                    })
                else:
                    models.append({
                        "task_id": tid,
                        "variant": tag,
                        "error": "no pbr_model URL in task result",
                        "verified": False,
                    })
            except Exception as exc:
                models.append({
                    "task_id": tid,
                    "variant": tag,
                    "error": str(exc),
                    "verified": False,
                })

        ok = [m for m in models if m.get("verified")]
        return {
            "status": "success" if ok else "failed",
            "all_task_ids": task_ids,
            "downloaded": len(ok),
            "total_variants": len(task_ids),
            "models": models,
            # Convenience: first verified model path
            "model_path": ok[0]["path"] if ok else "",
        }

    async def generate_from_text(
        self,
        prompt: str,
        output_dir: str,
        texture: bool = True,
        pbr: bool = True,
        model_version: str = "v3.0-20250812",
        timeout: float = 300,
        max_variants: int = 4,
    ) -> dict:
        """Generate a 3D model from text using studio credits.

        Args:
            max_variants: How many of the 4 studio variants to download (default 4).
        """
        task_data = {
            "type": "text_to_model",
            "prompt": prompt,
            "model_version": model_version,
            "texture": texture,
            "pbr": pbr,
        }

        try:
            task_ids = await self.create_task(task_data)
            logger.info(
                "Studio task created: %d variants, downloading %d",
                len(task_ids),
                min(max_variants, len(task_ids)),
            )
            return await self._poll_and_download_variants(
                task_ids, output_dir, max_variants=max_variants, timeout=timeout
            )
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}

    async def generate_from_image(
        self,
        image_path: str,
        output_dir: str,
        texture: bool = True,
        pbr: bool = True,
        model_version: str = "v3.0-20250812",
        timeout: float = 300,
        max_variants: int = 4,
    ) -> dict:
        """Generate a 3D model from an image using studio credits."""
        if not os.path.isfile(image_path):
            return {"status": "failed", "error": f"Image not found: {image_path}"}

        try:
            # Upload image first
            jwt = await self._get_valid_jwt()
            url = f"{STUDIO_BASE_URL}/task/upload"
            headers = {
                "Authorization": f"Bearer {jwt}",
                "x-tripo-region": "rg1",
            }
            with open(image_path, "rb") as f:
                files = {"file": (os.path.basename(image_path), f)}
                async with httpx.AsyncClient(timeout=60.0) as upload_client:
                    resp = await upload_client.post(
                        url, files=files, headers=headers
                    )
                    upload_data = resp.json()
                    if resp.status_code >= 400:
                        return {
                            "status": "failed",
                            "error": f"Upload failed: {upload_data}",
                        }
                    image_token = upload_data["data"]["image_token"]

            _ext = Path(image_path).suffix.lower()
            _img_type = "png" if _ext == ".png" else "jpg"
            task_data = {
                "type": "image_to_model",
                "file": {"type": _img_type, "file_token": image_token},
                "model_version": model_version,
                "texture": texture,
                "pbr": pbr,
            }

            task_ids = await self.create_task(task_data)
            logger.info(
                "Studio image task created: %d variants, downloading %d",
                len(task_ids),
                min(max_variants, len(task_ids)),
            )
            return await self._poll_and_download_variants(
                task_ids, output_dir, max_variants=max_variants, timeout=timeout
            )
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}
