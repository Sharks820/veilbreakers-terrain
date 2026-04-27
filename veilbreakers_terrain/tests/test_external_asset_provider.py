"""Tests for ExternalAssetProvider ABC and AssetJobResult/AssetGenerationRequest contracts."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from veilbreakers_terrain.providers.external_asset_provider import (
    AssetGenerationRequest,
    AssetJobResult,
    ExternalAssetProvider,
    JobStatus,
)


# ---------------------------------------------------------------------------
# Stub provider for testing the ABC interface
# ---------------------------------------------------------------------------

class _StubProvider(ExternalAssetProvider):
    provider_id = "stub"

    def __init__(self, final_status: JobStatus = JobStatus.COMPLETED, fail_download: bool = False):
        self._final_status = final_status
        self._fail_download = fail_download
        self._calls: list[str] = []

    def submit(self, request: AssetGenerationRequest) -> str:
        self._calls.append("submit")
        return "stub-job-001"

    def poll(self, job_id: str) -> JobStatus:
        self._calls.append("poll")
        return self._final_status

    def download(self, job_id: str, dest_dir: Path, *, species_id: str) -> Path:
        self._calls.append("download")
        if self._fail_download:
            raise RuntimeError("download intentionally failed")
        p = dest_dir / f"{species_id}.glb"
        p.write_bytes(b"FAKE_GLB")
        return p


# ---------------------------------------------------------------------------
# AssetGenerationRequest
# ---------------------------------------------------------------------------

def test_request_defaults():
    req = AssetGenerationRequest(species_id="oak_01", prompt="dark oak tree")
    assert req.texture is True
    assert req.require_pbr is True
    assert req.target_tris == 50_000
    assert req.quality == "high"
    assert req.image_path is None
    assert req.seed is None


def test_request_extra_is_empty_dict_by_default():
    req = AssetGenerationRequest(species_id="rock_01", prompt="mossy rock")
    assert req.extra == {}
    req2 = AssetGenerationRequest(species_id="rock_02", prompt="dry rock")
    req.extra["foo"] = 1
    assert "foo" not in req2.extra  # no shared mutable default


# ---------------------------------------------------------------------------
# JobStatus
# ---------------------------------------------------------------------------

def test_job_status_values():
    assert JobStatus.COMPLETED == "completed"
    assert JobStatus.FAILED == "failed"
    assert JobStatus.PENDING == "pending"
    assert JobStatus.PROCESSING == "processing"


# ---------------------------------------------------------------------------
# validate() — no real GLB file so trimesh/pygltflib will raise load errors
# ---------------------------------------------------------------------------

def test_validate_missing_file():
    provider = _StubProvider()
    result = provider.validate(
        Path("/nonexistent/fake.glb"),
        species_id="test_01",
        require_pbr=False,
    )
    assert isinstance(result, AssetJobResult)
    assert result.validated is False
    # Either trimesh raises a load error, or the library isn't installed — both produce an issue
    has_issue = any(
        ("load_error" in issue or "not_installed" in issue or "pbr_check_error" in issue)
        for issue in result.validation_issues
    )
    assert has_issue, f"Expected load/install issue in {result.validation_issues}"


def test_validate_returns_provider_id():
    provider = _StubProvider()
    result = provider.validate(Path("/fake.glb"), species_id="oak", require_pbr=False)
    assert result.provider == "stub"
    assert result.species_id == "oak"


def test_validate_require_pbr_false_skips_channel_check():
    provider = _StubProvider()
    result = provider.validate(Path("/fake.glb"), species_id="oak", require_pbr=False)
    missing_pbr = [i for i in result.validation_issues if "missing_pbr_channels" in i]
    assert missing_pbr == [], "require_pbr=False should not flag missing channels"


# ---------------------------------------------------------------------------
# generate_blocking() fast-path tests (using stub)
# ---------------------------------------------------------------------------

def test_generate_blocking_completed(tmp_path: Path):
    provider = _StubProvider(final_status=JobStatus.COMPLETED)
    req = AssetGenerationRequest(species_id="fern_01", prompt="dark fern", require_pbr=False)
    result = provider.generate_blocking(req, tmp_path, poll_interval_s=0.0)
    assert result.job_id == "stub-job-001"
    assert result.species_id == "fern_01"
    assert "submit" in provider._calls
    assert "poll" in provider._calls
    assert "download" in provider._calls


def test_generate_blocking_failed_raises():
    provider = _StubProvider(final_status=JobStatus.FAILED)
    req = AssetGenerationRequest(species_id="rock_02", prompt="boulder", require_pbr=False)
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(RuntimeError, match="failed"):
            provider.generate_blocking(req, Path(td), poll_interval_s=0.0)


def test_generate_blocking_timeout_raises():
    provider = _StubProvider(final_status=JobStatus.PROCESSING)
    req = AssetGenerationRequest(species_id="tree_01", prompt="pine", require_pbr=False)
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(TimeoutError):
            provider.generate_blocking(req, Path(td), poll_interval_s=0.0, timeout_s=0.001)


# ---------------------------------------------------------------------------
# catalog() writes JSON
# ---------------------------------------------------------------------------

def test_catalog_writes_json(tmp_path: Path):
    provider = _StubProvider()
    glb = tmp_path / "oak_01.glb"
    glb.write_bytes(b"GLB")
    result = AssetJobResult(
        job_id="job-1",
        provider="stub",
        species_id="oak_01",
        glb_path=glb,
        pbr_channels=["BASE_COLOR", "NORMAL", "ROUGHNESS"],
        poly_count=12000,
        validated=True,
        validation_issues=[],
    )
    catalog_path = tmp_path / "catalog.json"
    provider.catalog(result, catalog_path)
    assert catalog_path.exists()
    data = json.loads(catalog_path.read_text())
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["species_id"] == "oak_01"
    assert data[0]["validated"] is True


def test_catalog_appends_multiple(tmp_path: Path):
    provider = _StubProvider()
    catalog_path = tmp_path / "catalog.json"
    for i in range(3):
        glb = tmp_path / f"spec_{i}.glb"
        glb.write_bytes(b"GLB")
        result = AssetJobResult(
            job_id=f"job-{i}",
            provider="stub",
            species_id=f"spec_{i}",
            glb_path=glb,
            pbr_channels=[],
            poly_count=1000,
            validated=False,
            validation_issues=["test"],
        )
        provider.catalog(result, catalog_path)
    data = json.loads(catalog_path.read_text())
    assert len(data) == 3
    assert [d["species_id"] for d in data] == ["spec_0", "spec_1", "spec_2"]


# ---------------------------------------------------------------------------
# Hunyuan3D2Provider — ABC conformance + mode detection (no network required)
# ---------------------------------------------------------------------------

def test_hunyuan3d2_provider_is_subclass():
    """Hunyuan3D2Provider must be a concrete subclass of ExternalAssetProvider."""
    from veilbreakers_terrain.providers.hunyuan3d2_provider import Hunyuan3D2Provider

    assert issubclass(Hunyuan3D2Provider, ExternalAssetProvider)


def test_hunyuan3d2_provider_id():
    """Provider ID must be 'hunyuan3d2' for catalog + dispatch keying."""
    from veilbreakers_terrain.providers.hunyuan3d2_provider import Hunyuan3D2Provider

    assert Hunyuan3D2Provider.provider_id == "hunyuan3d2"


def test_hunyuan3d2_default_mode_is_hf_space(monkeypatch):
    """Without env vars, mode must default to HuggingFace Space."""
    from veilbreakers_terrain.providers.hunyuan3d2_provider import (
        Hunyuan3D2Provider,
        _MODE_HF_SPACE,
    )

    monkeypatch.delenv("HUNYUAN3D2_MODE", raising=False)
    monkeypatch.delenv("HUNYUAN3D2_HF_ENDPOINT", raising=False)

    p = Hunyuan3D2Provider()
    assert p._mode == _MODE_HF_SPACE


def test_hunyuan3d2_local_mode_raises(monkeypatch):
    """HUNYUAN3D2_MODE=local must raise immediately — local requires 16-24 GB VRAM."""
    import pytest
    from veilbreakers_terrain.providers.hunyuan3d2_provider import Hunyuan3D2Provider

    monkeypatch.setenv("HUNYUAN3D2_MODE", "local")
    monkeypatch.delenv("HUNYUAN3D2_HF_ENDPOINT", raising=False)

    with pytest.raises(RuntimeError, match="HUNYUAN3D2_MODE=local is not supported"):
        Hunyuan3D2Provider()


def test_hunyuan3d2_has_abc_methods():
    """Hunyuan3D2Provider must implement all three ABC abstract methods."""
    from veilbreakers_terrain.providers.hunyuan3d2_provider import Hunyuan3D2Provider

    assert callable(getattr(Hunyuan3D2Provider, "submit", None))
    assert callable(getattr(Hunyuan3D2Provider, "poll", None))
    assert callable(getattr(Hunyuan3D2Provider, "download", None))


def test_hunyuan3d2_exported_from_providers_package():
    """Hunyuan3D2Provider must be importable from the providers package __init__."""
    from veilbreakers_terrain.providers import Hunyuan3D2Provider

    assert Hunyuan3D2Provider.provider_id == "hunyuan3d2"


# ---------------------------------------------------------------------------
# MeshyProvider — ABC conformance + key validation (no network required)
# ---------------------------------------------------------------------------

def test_meshy_provider_id():
    """MeshyProvider.provider_id must be 'meshy'."""
    from veilbreakers_terrain.providers.meshy_provider import MeshyProvider

    assert MeshyProvider.provider_id == "meshy"


def test_meshy_no_key_raises(monkeypatch):
    """MeshyProvider() must raise RuntimeError when MESHY_API_KEY is unset."""
    from veilbreakers_terrain.providers.meshy_provider import MeshyProvider

    monkeypatch.delenv("MESHY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MESHY_API_KEY not set"):
        MeshyProvider()


def test_meshy_is_subclass():
    """MeshyProvider must be a concrete subclass of ExternalAssetProvider."""
    from veilbreakers_terrain.providers.meshy_provider import MeshyProvider

    assert issubclass(MeshyProvider, ExternalAssetProvider)


def test_meshy_has_abc_methods():
    """MeshyProvider must implement all three ABC abstract methods."""
    from veilbreakers_terrain.providers.meshy_provider import MeshyProvider

    assert callable(getattr(MeshyProvider, "submit", None))
    assert callable(getattr(MeshyProvider, "poll", None))
    assert callable(getattr(MeshyProvider, "download", None))


def test_meshy_exported_from_providers_package():
    """MeshyProvider must be importable from the providers package __init__."""
    from veilbreakers_terrain.providers import MeshyProvider

    assert MeshyProvider.provider_id == "meshy"
