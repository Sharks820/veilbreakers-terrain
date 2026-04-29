"""AI 3D asset generation client for VeilBreakers dark fantasy terrain.

Wraps three cloud backends behind a single :class:`AssetGenerationPipeline`
facade so the rest of the project can request a GLB by prompt + category
without caring which service produced it:

* **HuggingFace Spaces** (``tencent/Hunyuan3D-2``) — free, queue-based, primary
  daily-driver path. Uses the ``gradio_client`` wire protocol.
* **RunPod** — paid GPU workers running Hunyuan3D-2 docker images. Async job
  submission with polling. Used when HF queue is saturated and turnaround
  matters.
* **Rodin** (Hyperhuman / Deemos) — best topology for hero assets that will
  be retopologised in 3ds Max 2027. Image-to-3D via REST.

The module is import-safe with **no hard dependency** on the cloud SDKs:
``gradio_client``, ``runpod``, and ``requests`` are imported lazily so the
rest of the terrain pipeline can keep running without those packages.

Design notes
------------
* All filesystem paths use :class:`pathlib.Path`.
* Every network call is wrapped with bounded exponential backoff
  (max 3 retries) and a ``timeout_s`` per attempt.
* Output GLBs are validated by file size + magic bytes before we declare
  success.
* Progress reporting uses ``tqdm`` if available, plain ``print`` fallback.
* Style presets live in :data:`DARK_FANTASY_PRESETS` so prompts are
  consistent across rocks/ruins/trees/props.
"""

from __future__ import annotations

import json
import logging
import os
import random
import shutil
import string
import tempfile
import time
import warnings
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

warnings.warn(
    "veilbreakers_terrain.handlers.asset_generation is deprecated (FIX-7-11). "
    "Use veilbreakers_terrain.providers.Hunyuan3D2Provider or MeshyProvider instead. "
    "This module will be removed once all callers are migrated to providers/.",
    DeprecationWarning,
    stacklevel=2,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional progress reporter
# ---------------------------------------------------------------------------

try:  # pragma: no cover - tqdm optional
    from tqdm import tqdm as _tqdm  # type: ignore
except Exception:  # noqa: BLE001
    _tqdm = None  # type: ignore[assignment]


def _progress(iterable: Iterable, desc: str = "") -> Iterable:
    """tqdm-if-available, plain iterable otherwise."""
    if _tqdm is not None:
        return _tqdm(iterable, desc=desc)
    if desc:
        print(f"[asset_generation] {desc}")
    return iterable


# ---------------------------------------------------------------------------
# Public enums and data classes
# ---------------------------------------------------------------------------


class AssetGenerationBackend(str, Enum):
    """Which cloud service produces the GLB."""

    HUGGINGFACE = "huggingface"
    RUNPOD = "runpod"
    RODIN = "rodin"


# Asset categories — these line up with the directory layout under
# ``Assets/Foliage/`` and ``assets/generated/`` so the manifest schema in
# FOLIAGE_WAVE5_RESEARCH.md can match them 1:1.
KNOWN_CATEGORIES: tuple[str, ...] = (
    "rock",
    "ruin",
    "tree",
    "prop",
    "grass_hero",
    "shrub",
    "lantern",
    "arch",
    "gravestone",
    "debris",
)


@dataclass
class AssetRequest:
    """One unit of work: a single asset to generate.

    Args:
        prompt: Free-form text prompt fed to the image-to-3D / text-to-3D
            backend. Should already include style preset text.
        reference_image_path: Optional source image. Required by Rodin and
            preferred by Hunyuan3D-2 image-to-3D mode. ``None`` means
            text-only generation.
        asset_category: One of :data:`KNOWN_CATEGORIES`. Used for output
            directory layout and downstream manifest tagging.
        output_name: Stem for the produced GLB file (no extension).
        target_poly_count: Game-ready triangle budget. Backends respect
            this only as a *hint*; final retopo happens in 3ds Max
            ProOptimizer.
        seed: Optional generation seed. Backends that don't support seeds
            will ignore this.
        metadata: Free-form dict written next to the GLB as a sidecar
            JSON for traceability.
    """

    prompt: str
    asset_category: str
    output_name: str
    target_poly_count: int = 8000
    reference_image_path: Optional[Path] = None
    seed: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.prompt or not self.prompt.strip():
            raise ValueError("AssetRequest.prompt must be non-empty")
        if not self.output_name or not self.output_name.strip():
            raise ValueError("AssetRequest.output_name must be non-empty")
        if self.asset_category not in KNOWN_CATEGORIES:
            # Don't fail hard — log and accept; categories are user-extensible.
            logger.warning(
                "AssetRequest.asset_category=%r is not in KNOWN_CATEGORIES; "
                "downstream tooling may not recognise it.",
                self.asset_category,
            )
        if self.target_poly_count <= 0:
            raise ValueError("target_poly_count must be > 0")
        if self.reference_image_path is not None:
            self.reference_image_path = Path(self.reference_image_path)


# ---------------------------------------------------------------------------
# Dark fantasy style preset library
# ---------------------------------------------------------------------------


DARK_FANTASY_PRESETS: dict[str, str] = {
    "veilbreakers_rock": (
        "weathered dark stone boulder, fantasy RPG, Elden Ring style, "
        "moss-covered, photorealistic PBR, sharp silhouette, ambient occlusion"
    ),
    "veilbreakers_ruin": (
        "ancient crumbling ruin fragment, dark fantasy, worn stone, mystical, "
        "overgrown with creeping moss, broken mortar, stylised AAA"
    ),
    "veilbreakers_tree": (
        "gnarled dead tree trunk, dark fantasy forest, twisted bark, no leaves, "
        "ominous, cracked silhouette, dense bark detail, photorealistic PBR"
    ),
    "veilbreakers_tree_blighted": (
        "blighted twisted tree, oozing dark sap, hollowed bark, malformed branches, "
        "dark fantasy horror, photorealistic PBR"
    ),
    "veilbreakers_prop": (
        "dark fantasy prop, hand-crafted aged material, atmospheric, "
        "weathered iron and wood, soft volumetric lighting, AAA quality"
    ),
    "veilbreakers_lantern": (
        "wrought-iron hanging lantern, dark fantasy, dim glow, gothic detail, "
        "rust patina, single hero asset, AAA"
    ),
    "veilbreakers_arch": (
        "stone archway entrance, runes carved into keystone, partially collapsed, "
        "dark fantasy, weathered, photorealistic PBR"
    ),
    "veilbreakers_gravestone": (
        "broken weathered gravestone, mossy, cracked, leaning, dark fantasy "
        "cemetery, photorealistic PBR"
    ),
    "veilbreakers_grass_hero": (
        "tuft of dark withered grass blades, dark fantasy ground cover, "
        "photoscanned realism, root-up volumetric"
    ),
    "veilbreakers_debris": (
        "scattered stone rubble pile, dark fantasy ruins, photorealistic PBR, "
        "varied weathered fragments"
    ),
}


def apply_preset(prompt: str, preset_key: str) -> str:
    """Concatenate a dark-fantasy preset onto a base prompt.

    The preset is appended *after* the user prompt so the user's specifics
    take semantic priority.
    """
    preset = DARK_FANTASY_PRESETS.get(preset_key)
    if not preset:
        return prompt
    return f"{prompt.strip()}, {preset}"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


GLB_MAGIC = b"glTF"
MIN_GLB_BYTES = 1024  # 1 KB sanity floor


def validate_glb(path: Path) -> bool:
    """Return True iff ``path`` looks like a real GLB.

    Checks file size > :data:`MIN_GLB_BYTES` and the first four magic bytes
    spell ``glTF``. Does not parse the chunk header — backends occasionally
    return GLB-2 with vendor extensions, so we keep validation cheap.
    """
    p = Path(path)
    if not p.is_file():
        return False
    if p.stat().st_size < MIN_GLB_BYTES:
        return False
    try:
        with p.open("rb") as fh:
            magic = fh.read(4)
    except OSError:
        return False
    return magic == GLB_MAGIC


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------


def _retry(
    func: Callable[[], Any],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 2.0,
    label: str = "operation",
) -> Any:
    """Run ``func`` with exponential backoff. Raises last exception."""
    last_exc: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 — we re-raise after retries
            last_exc = exc
            if attempt >= max_attempts:
                break
            delay = base_delay_s * (2 ** (attempt - 1))
            logger.warning(
                "%s attempt %d/%d failed (%s); sleeping %.1fs",
                label,
                attempt,
                max_attempts,
                type(exc).__name__,
                delay,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------


def _atomic_copy(src: Path, dst: Path) -> Path:
    """Copy ``src`` to ``dst`` atomically (write tmp + rename)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    tmp = dst.with_name(f".{dst.name}.{suffix}.tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    return dst


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


class _BackendBase:
    """Abstract backend interface."""

    def generate(self, request: AssetRequest, output_path: Path, *, timeout_s: float) -> Path:
        raise NotImplementedError


class HuggingFaceBackend(_BackendBase):
    """Hunyuan3D-2 via HuggingFace Spaces / ``gradio_client``.

    The Space name and api endpoint are pinned but overridable so the
    user can swap to a private duplicate of the Space without code edits.
    """

    DEFAULT_SPACE = "tencent/Hunyuan3D-2"
    DEFAULT_API_NAME = "/shape_generation"

    def __init__(
        self,
        *,
        space: str = DEFAULT_SPACE,
        api_name: str = DEFAULT_API_NAME,
        hf_token: Optional[str] = None,
    ) -> None:
        self.space = space
        self.api_name = api_name
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")

    def _client(self):
        try:
            from gradio_client import Client  # type: ignore
        except ImportError as exc:  # pragma: no cover - import-time path
            raise RuntimeError(
                "gradio_client is required for the HuggingFace backend. "
                "Install with `pip install gradio_client`."
            ) from exc
        return Client(self.space, hf_token=self.hf_token)

    @staticmethod
    def _wrap_image(path: Optional[Path]):
        if path is None:
            return None
        try:
            from gradio_client import handle_file  # type: ignore
        except ImportError:  # pragma: no cover
            return str(path)
        return handle_file(str(path))

    def generate(self, request: AssetRequest, output_path: Path, *, timeout_s: float = 600.0) -> Path:
        client = self._client()

        def _call() -> Path:
            kwargs: dict[str, Any] = {
                "caption": request.prompt,
                "image": self._wrap_image(request.reference_image_path),
                "seed": request.seed if request.seed is not None else 1234,
                "octree_resolution": 256,
                "num_inference_steps": 30,
                "guidance_scale": 5.5,
                "num_chunks": 8000,
                "randomize_seed": request.seed is None,
            }
            # Some Space versions reject unknown kwargs; drop image when None.
            if kwargs["image"] is None:
                kwargs.pop("image")

            result = client.predict(api_name=self.api_name, **kwargs)
            # gradio_client returns a path str (or tuple) for File outputs.
            src_path = result[0] if isinstance(result, (list, tuple)) else result
            if not src_path:
                raise RuntimeError("HuggingFace backend returned empty result")
            src = Path(str(src_path))
            if not src.exists():
                raise RuntimeError(f"HuggingFace returned non-existent file: {src}")
            return _atomic_copy(src, output_path)

        return _retry(_call, label=f"HF generate({request.output_name})")


class RunPodBackend(_BackendBase):
    """RunPod async-job runner for Hunyuan3D-2 docker images.

    The backend submits a job, polls for completion, then downloads the
    resulting GLB. Cost-per-job is logged when ``log_cost`` is True.
    """

    def __init__(
        self,
        *,
        endpoint_id: Optional[str] = None,
        api_key: Optional[str] = None,
        cost_per_minute_usd: float = 0.013,  # rough A100 spot rate as of 2026
        log_cost: bool = True,
    ) -> None:
        self.endpoint_id = endpoint_id or os.environ.get("RUNPOD_ENDPOINT_ID")
        self.api_key = api_key or os.environ.get("RUNPOD_API_KEY")
        self.cost_per_minute_usd = cost_per_minute_usd
        self.log_cost = log_cost
        if not self.endpoint_id or not self.api_key:
            logger.warning(
                "RunPodBackend created without endpoint_id/api_key; "
                "set RUNPOD_ENDPOINT_ID and RUNPOD_API_KEY env vars."
            )

    def _runpod(self):
        try:
            import runpod  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "runpod is required for the RunPod backend. Install with `pip install runpod`."
            ) from exc
        runpod.api_key = self.api_key
        return runpod

    def generate(self, request: AssetRequest, output_path: Path, *, timeout_s: float = 900.0) -> Path:
        runpod = self._runpod()
        endpoint = runpod.Endpoint(self.endpoint_id)

        def _call() -> Path:
            t0 = time.monotonic()
            payload: dict[str, Any] = {
                "prompt": request.prompt,
                "target_poly_count": request.target_poly_count,
                "seed": request.seed if request.seed is not None else 1234,
            }
            if request.reference_image_path is not None:
                payload["reference_image_path"] = str(request.reference_image_path)

            run = endpoint.run(payload)
            poll_interval = 4.0
            deadline = t0 + timeout_s
            while True:
                status = run.status()
                if status == "COMPLETED":
                    break
                if status in {"FAILED", "CANCELLED"}:
                    raise RuntimeError(f"RunPod job {status}: {run.output()}")
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"RunPod job did not complete within {timeout_s:.0f}s"
                    )
                time.sleep(poll_interval)

            output = run.output() or {}
            glb_url = output.get("glb_url") or output.get("output_url")
            if not glb_url:
                raise RuntimeError(f"RunPod completed but returned no glb_url: {output}")

            local = self._download(glb_url, output_path)
            elapsed_min = (time.monotonic() - t0) / 60.0
            if self.log_cost:
                cost = elapsed_min * self.cost_per_minute_usd
                logger.info(
                    "RunPod %s done in %.2f min (~$%.3f)",
                    request.output_name,
                    elapsed_min,
                    cost,
                )
            return local

        return _retry(_call, label=f"RunPod generate({request.output_name})")

    @staticmethod
    def _download(url: str, dest: Path) -> Path:
        try:
            import requests  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "requests is required to download RunPod outputs"
            ) from exc
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".glb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
                tmp = Path(fh.name)
        return _atomic_copy(tmp, dest)


class RodinBackend(_BackendBase):
    """Hyper3D Rodin REST client (secondary provider — requires Business plan ~$96/mo).

    Primary provider for VeilBreakers is Hunyuan3D-2 (local, free).
    Use Rodin only when GPU is unavailable locally.

    API reference: https://api.hyper3d.com/api/v2
    Submit: POST /rodin (multipart/form-data) → {"subscription_key": "..."}
    Poll:   POST /status  (JSON body {"subscription_key": key}) → {"status": "Done"|"Failed"|...}
    Download: POST /download (JSON {"subscription_key": key}) → [{"url": "..."}]
              then GET the pre-signed S3 URL *without* auth header.
    """

    # Corrected from "https://hyperhuman.deemos.com/api/v2/rodin"
    BASE_URL = "https://api.hyper3d.com/api/v2"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("RODIN_API_KEY")
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        if not self.api_key:
            logger.warning("RodinBackend created without api_key; set RODIN_API_KEY")

    def _requests(self):
        try:
            import requests  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("requests is required for the Rodin backend") from exc
        return requests

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def generate(self, request: AssetRequest, output_path: Path, *, timeout_s: float = 1200.0) -> Path:
        requests = self._requests()

        if request.reference_image_path is None:
            logger.warning(
                "Rodin works best with reference_image_path; falling back to "
                "text-only mode for %s",
                request.output_name,
            )

        def _submit() -> str:
            # POST /rodin with multipart/form-data — returns subscription_key (not job_id)
            files = {}
            data: dict = {
                "prompt": request.prompt,
                "geometry_file_format": "glb",
                "material": "PBR",
                "quality": "high",
                "use_hyper": "false",
            }
            if request.seed is not None:
                data["seed"] = str(request.seed)
            if request.target_poly_count:
                data["poly_count"] = str(request.target_poly_count)
            if request.reference_image_path is not None:
                files["images"] = open(request.reference_image_path, "rb")
            try:
                resp = requests.post(
                    f"{self.base_url}/rodin",
                    headers=self._headers(),
                    data=data,
                    files=files or None,
                    timeout=60,
                )
            finally:
                for fh in files.values():
                    fh.close()
            resp.raise_for_status()
            body = resp.json()
            # API returns subscription_key, not a job UUID
            key = body.get("subscription_key") or body.get("uuid") or body.get("job_id")
            if not key:
                raise RuntimeError(f"Rodin submit returned no subscription_key: {body}")
            return str(key)

        def _poll(subscription_key: str) -> None:
            # POST /status with JSON body — status field is capitalized ("Done", "Failed")
            deadline = time.monotonic() + timeout_s
            while True:
                resp = requests.post(
                    f"{self.base_url}/status",
                    headers=self._headers(),
                    json={"subscription_key": subscription_key},
                    timeout=30,
                )
                resp.raise_for_status()
                body = resp.json()
                status = (body.get("status") or "").lower()
                if status in {"done", "completed", "success", "finished"}:
                    return
                if status in {"failed", "error", "cancelled"}:
                    raise RuntimeError(f"Rodin job {status}: {body}")
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Rodin job {subscription_key} timed out after {timeout_s}s")
                time.sleep(5.0)

        def _download(subscription_key: str) -> str:
            # POST /download → list of pre-signed S3 URLs; must NOT send auth header to S3
            resp = requests.post(
                f"{self.base_url}/download",
                headers=self._headers(),
                json={"subscription_key": subscription_key},
                timeout=60,
            )
            resp.raise_for_status()
            items = resp.json()
            if not items:
                raise RuntimeError(f"Rodin /download returned empty list for {subscription_key}")
            # Find GLB entry; fall back to first item
            glb_url = next(
                (item["url"] for item in items if str(item.get("name", "")).lower().endswith(".glb")),
                items[0]["url"],
            )
            return str(glb_url)

        def _call() -> Path:
            subscription_key = _submit()
            _poll(subscription_key)
            glb_url = _download(subscription_key)
            # S3 pre-signed URLs must NOT include the auth header
            with requests.get(glb_url, stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with tempfile.NamedTemporaryFile(delete=False, suffix=".glb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
                    tmp = Path(fh.name)
            return _atomic_copy(tmp, output_path)

        return _retry(_call, label=f"Rodin generate({request.output_name})")


# ---------------------------------------------------------------------------
# Pipeline facade
# ---------------------------------------------------------------------------


@dataclass
class PipelineConfig:
    """Backend selection + auth materials.

    Auth values default to environment variables so secrets stay out of
    the codebase. Override at construction time for tests.
    """

    huggingface_space: str = HuggingFaceBackend.DEFAULT_SPACE
    huggingface_api_name: str = HuggingFaceBackend.DEFAULT_API_NAME
    hf_token: Optional[str] = None
    runpod_endpoint_id: Optional[str] = None
    runpod_api_key: Optional[str] = None
    rodin_api_key: Optional[str] = None
    rodin_base_url: str = RodinBackend.BASE_URL
    default_backend: AssetGenerationBackend = AssetGenerationBackend.HUGGINGFACE
    timeout_s: float = 900.0


class AssetGenerationPipeline:
    """Top-level facade for backend-agnostic GLB generation.

    Typical usage::

        pipe = AssetGenerationPipeline()
        path = pipe.generate(
            AssetRequest(prompt="...", asset_category="rock", output_name="rock_01"),
            backend=AssetGenerationBackend.HUGGINGFACE,
            output_dir=Path("assets/generated/rocks"),
        )
    """

    def __init__(self, config: Optional[PipelineConfig] = None) -> None:
        self.config = config or PipelineConfig()
        self._backends: dict[AssetGenerationBackend, _BackendBase] = {}

    # ------------------------------------------------------------------
    def _backend(self, which: AssetGenerationBackend) -> _BackendBase:
        if which not in self._backends:
            self._backends[which] = self._build_backend(which)
        return self._backends[which]

    def _build_backend(self, which: AssetGenerationBackend) -> _BackendBase:
        cfg = self.config
        if which is AssetGenerationBackend.HUGGINGFACE:
            return HuggingFaceBackend(
                space=cfg.huggingface_space,
                api_name=cfg.huggingface_api_name,
                hf_token=cfg.hf_token,
            )
        if which is AssetGenerationBackend.RUNPOD:
            return RunPodBackend(
                endpoint_id=cfg.runpod_endpoint_id,
                api_key=cfg.runpod_api_key,
            )
        if which is AssetGenerationBackend.RODIN:
            return RodinBackend(api_key=cfg.rodin_api_key, base_url=cfg.rodin_base_url)
        raise ValueError(f"Unknown backend: {which}")

    # ------------------------------------------------------------------
    def generate(
        self,
        request: AssetRequest,
        backend: Optional[AssetGenerationBackend] = None,
        output_dir: Optional[Path] = None,
    ) -> Path:
        """Produce a single GLB. Returns the output path.

        Output filename is ``<output_name>.glb`` under ``output_dir``.
        Sidecar ``<output_name>.json`` is written with prompt + metadata.
        """
        which = backend or self.config.default_backend
        out_dir = Path(output_dir) if output_dir else Path("assets/generated") / request.asset_category
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{request.output_name}.glb"

        impl = self._backend(which)
        result = impl.generate(request, out_path, timeout_s=self.config.timeout_s)
        if not validate_glb(result):
            raise RuntimeError(f"Generated GLB failed validation: {result}")

        sidecar = out_dir / f"{request.output_name}.json"
        sidecar_data = {
            "prompt": request.prompt,
            "asset_category": request.asset_category,
            "target_poly_count": request.target_poly_count,
            "seed": request.seed,
            "backend": which.value,
            "reference_image_path": (
                str(request.reference_image_path) if request.reference_image_path else None
            ),
            "metadata": request.metadata,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _atomic_write_json(sidecar, sidecar_data)
        logger.info("Generated %s via %s", result, which.value)
        return result

    # ------------------------------------------------------------------
    def batch_generate(
        self,
        requests: list[AssetRequest],
        output_dir: Path,
        backend: Optional[AssetGenerationBackend] = None,
        *,
        continue_on_error: bool = True,
    ) -> list[Path]:
        """Generate many assets sequentially. Returns successful paths.

        Errors are logged. When ``continue_on_error`` is True, a single
        failure does not abort the batch.
        """
        out: list[Path] = []
        for req in _progress(requests, desc="Generating assets"):
            try:
                out.append(self.generate(req, backend=backend, output_dir=output_dir))
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to generate %s: %s", req.output_name, exc)
                if not continue_on_error:
                    raise
        return out

    # ------------------------------------------------------------------
    def generate_from_concept(
        self,
        prompt: str,
        style_preset: str,
        output_dir: Path,
        *,
        asset_category: str = "prop",
        output_name: Optional[str] = None,
        backend: Optional[AssetGenerationBackend] = None,
        target_poly_count: int = 8000,
    ) -> Path:
        """One-shot: prompt + preset → GLB.

        Convenience wrapper that applies a dark-fantasy preset and chooses
        a deterministic file stem if none was provided.
        """
        full_prompt = apply_preset(prompt, style_preset)
        stem = output_name or f"{asset_category}_{abs(hash(full_prompt)) % 10**8:08d}"
        request = AssetRequest(
            prompt=full_prompt,
            asset_category=asset_category,
            output_name=stem,
            target_poly_count=target_poly_count,
        )
        return self.generate(request, backend=backend, output_dir=output_dir)


# ---------------------------------------------------------------------------
# Atomic JSON helper
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, data: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    tmp = path.with_name(f".{path.name}.{suffix}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return path


__all__ = [
    "AssetGenerationBackend",
    "AssetRequest",
    "AssetGenerationPipeline",
    "PipelineConfig",
    "HuggingFaceBackend",
    "RunPodBackend",
    "RodinBackend",
    "DARK_FANTASY_PRESETS",
    "KNOWN_CATEGORIES",
    "apply_preset",
    "validate_glb",
]
