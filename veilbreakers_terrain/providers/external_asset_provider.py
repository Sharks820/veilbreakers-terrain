"""Provider-neutral interface for AI-generated 3D terrain assets.

All external generation backends (Hunyuan3D-2, Rodin, etc.) implement this ABC.
Generated assets must pass validate() before entering terrain scatter.
"""

from __future__ import annotations

import abc
import enum
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_REQUIRED_PBR_CHANNELS = frozenset({"BASE_COLOR", "NORMAL", "ROUGHNESS"})


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AssetGenerationRequest:
    species_id: str
    prompt: str
    image_path: Optional[Path] = None
    seed: Optional[int] = None
    quality: str = "high"
    texture: bool = True
    target_tris: int = 50_000
    require_pbr: bool = True
    extra: dict = field(default_factory=dict)


@dataclass
class AssetJobResult:
    job_id: str
    provider: str
    species_id: str
    glb_path: Path
    pbr_channels: list[str]
    poly_count: int
    validated: bool
    validation_issues: list[str]


class ExternalAssetProvider(abc.ABC):
    """ABC for AI 3D asset generation providers.

    Implementation contract:
      - submit() sends the generation request and returns a provider-specific job_id string.
      - poll() returns the current JobStatus without blocking.
      - download() blocks until the file is on disk, returning the GLB path.
      - validate() runs topology/UV/PBR checks and returns AssetJobResult.
      - generate_blocking() is a convenience wrapper combining all four steps.
    """

    provider_id: str

    @abc.abstractmethod
    def submit(self, request: AssetGenerationRequest) -> str:
        """Submit a generation job and return the provider job_id."""

    @abc.abstractmethod
    def poll(self, job_id: str) -> JobStatus:
        """Check job status without blocking."""

    @abc.abstractmethod
    def download(self, job_id: str, dest_dir: Path, *, species_id: str) -> Path:
        """Download completed asset to dest_dir and return local GLB path."""

    def validate(
        self,
        glb_path: Path,
        *,
        species_id: str,
        max_tris: int = 100_000,
        require_pbr: bool = True,
    ) -> AssetJobResult:
        """Run topology, UV, and PBR channel validation on a downloaded GLB."""
        issues: list[str] = []
        poly_count = 0
        pbr_channels: list[str] = []

        try:
            import trimesh  # type: ignore

            mesh_or_scene = trimesh.load(str(glb_path), force="scene")
            geometries = (
                list(mesh_or_scene.geometry.values())
                if hasattr(mesh_or_scene, "geometry")
                else [mesh_or_scene]
            )
            for geom in geometries:
                if hasattr(geom, "faces"):
                    poly_count += len(geom.faces)
                if hasattr(geom, "visual") and hasattr(geom.visual, "uv"):
                    uv = geom.visual.uv
                    if uv is None or len(uv) == 0:
                        issues.append(f"missing_uv:{geom.metadata.get('name', '?')}")
        except ImportError:
            issues.append("trimesh_not_installed:skipped_geometry_check")
        except Exception as exc:
            issues.append(f"load_error:{exc!r}")

        if poly_count > max_tris:
            issues.append(f"over_budget:{poly_count}>{max_tris}_tris")

        try:
            import pygltflib  # type: ignore

            gltf = pygltflib.GLTF2().load(str(glb_path))
            for material in gltf.materials or []:
                if material.pbrMetallicRoughness:
                    pbr = material.pbrMetallicRoughness
                    if pbr.baseColorTexture:
                        pbr_channels.append("BASE_COLOR")
                    if pbr.metallicRoughnessTexture:
                        pbr_channels.append("ROUGHNESS")
                        pbr_channels.append("METALLIC")
                if material.normalTexture:
                    pbr_channels.append("NORMAL")
                if material.occlusionTexture:
                    pbr_channels.append("AO")
        except ImportError:
            issues.append("pygltflib_not_installed:skipped_pbr_check")
        except Exception as exc:
            issues.append(f"pbr_check_error:{exc!r}")

        if require_pbr:
            missing = _REQUIRED_PBR_CHANNELS - set(pbr_channels)
            if missing:
                issues.append(f"missing_pbr_channels:{','.join(sorted(missing))}")

        return AssetJobResult(
            job_id="",
            provider=self.provider_id,
            species_id=species_id,
            glb_path=glb_path,
            pbr_channels=pbr_channels,
            poly_count=poly_count,
            validated=len(issues) == 0,
            validation_issues=issues,
        )

    def generate_blocking(
        self,
        request: AssetGenerationRequest,
        dest_dir: Path,
        *,
        poll_interval_s: float = 5.0,
        timeout_s: float = 1800.0,
        max_tris: int = 100_000,
    ) -> AssetJobResult:
        """Submit, poll until done, download, validate. Raises on timeout or failure."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        job_id = self.submit(request)
        logger.info("[%s] submitted job %s for species %s", self.provider_id, job_id, request.species_id)

        deadline = time.monotonic() + timeout_s
        while True:
            status = self.poll(job_id)
            if status == JobStatus.COMPLETED:
                break
            if status == JobStatus.FAILED:
                raise RuntimeError(f"[{self.provider_id}] job {job_id} failed")
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"[{self.provider_id}] job {job_id} timed out after {timeout_s}s"
                )
            logger.debug("[%s] job %s status=%s — waiting %.0fs", self.provider_id, job_id, status, poll_interval_s)
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
                "[%s] asset %s validation issues: %s",
                self.provider_id,
                request.species_id,
                result.validation_issues,
            )
        return result

    def catalog(self, result: AssetJobResult, catalog_path: Path) -> None:
        """Append a validated asset result to the species catalog JSON."""
        import json

        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog: list[dict] = []
        if catalog_path.exists():
            try:
                catalog = json.loads(catalog_path.read_text())
            except Exception:
                pass

        entry = {
            "species_id": result.species_id,
            "provider": result.provider,
            "job_id": result.job_id,
            "glb_path": str(result.glb_path),
            "pbr_channels": result.pbr_channels,
            "poly_count": result.poly_count,
            "validated": result.validated,
            "validation_issues": result.validation_issues,
        }
        catalog.append(entry)
        catalog_path.write_text(json.dumps(catalog, indent=2))
        logger.info("[%s] cataloged %s -> %s", result.provider, result.species_id, catalog_path)
