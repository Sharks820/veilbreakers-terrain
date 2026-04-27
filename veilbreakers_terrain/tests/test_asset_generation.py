"""Unit tests for veilbreakers_terrain.handlers.asset_generation.

These tests do not hit the network — backend implementations are
monkey-patched at the call site.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from veilbreakers_terrain.handlers.asset_generation import (
    AssetGenerationBackend,
    AssetGenerationPipeline,
    AssetRequest,
    DARK_FANTASY_PRESETS,
    HuggingFaceBackend,
    KNOWN_CATEGORIES,
    PipelineConfig,
    RodinBackend,
    RunPodBackend,
    apply_preset,
    validate_glb,
)


# ---------------------------------------------------------------------------
# AssetRequest validation
# ---------------------------------------------------------------------------


def test_asset_request_minimal_ok():
    req = AssetRequest(prompt="weathered stone", asset_category="rock", output_name="rock_01")
    assert req.prompt == "weathered stone"
    assert req.asset_category == "rock"
    assert req.target_poly_count > 0


def test_asset_request_empty_prompt_raises():
    with pytest.raises(ValueError):
        AssetRequest(prompt="", asset_category="rock", output_name="rock_01")


def test_asset_request_empty_output_name_raises():
    with pytest.raises(ValueError):
        AssetRequest(prompt="x", asset_category="rock", output_name=" ")


def test_asset_request_negative_poly_raises():
    with pytest.raises(ValueError):
        AssetRequest(
            prompt="x",
            asset_category="rock",
            output_name="r",
            target_poly_count=-1,
        )


def test_asset_request_unknown_category_warns_but_accepts(caplog):
    with caplog.at_level("WARNING"):
        req = AssetRequest(prompt="x", asset_category="zorgon", output_name="z")
    assert req.asset_category == "zorgon"
    assert any("zorgon" in r.message for r in caplog.records)


def test_known_categories_includes_rock_tree_ruin():
    for cat in ("rock", "tree", "ruin", "prop", "grass_hero"):
        assert cat in KNOWN_CATEGORIES


# ---------------------------------------------------------------------------
# Preset library
# ---------------------------------------------------------------------------


def test_preset_library_has_required_keys():
    for key in (
        "veilbreakers_rock",
        "veilbreakers_ruin",
        "veilbreakers_tree",
        "veilbreakers_prop",
    ):
        assert key in DARK_FANTASY_PRESETS
        assert DARK_FANTASY_PRESETS[key]


def test_apply_preset_appends():
    out = apply_preset("a small boulder", "veilbreakers_rock")
    assert "a small boulder" in out
    assert "Elden Ring" in out


def test_apply_preset_unknown_returns_input():
    assert apply_preset("foo", "no_such_preset") == "foo"


# ---------------------------------------------------------------------------
# GLB validation
# ---------------------------------------------------------------------------


def test_validate_glb_rejects_missing(tmp_path: Path):
    assert not validate_glb(tmp_path / "missing.glb")


def test_validate_glb_rejects_too_small(tmp_path: Path):
    p = tmp_path / "tiny.glb"
    p.write_bytes(b"glTF" + b"x" * 100)
    assert not validate_glb(p)


def test_validate_glb_rejects_wrong_magic(tmp_path: Path):
    p = tmp_path / "wrong.glb"
    p.write_bytes(b"FBX " + b"x" * 4096)
    assert not validate_glb(p)


def test_validate_glb_accepts_valid(tmp_path: Path):
    p = tmp_path / "ok.glb"
    p.write_bytes(b"glTF" + b"\x02\x00\x00\x00" + b"x" * 4096)
    assert validate_glb(p)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def test_pipeline_default_backend_is_huggingface():
    pipe = AssetGenerationPipeline()
    assert pipe.config.default_backend is AssetGenerationBackend.HUGGINGFACE


def test_pipeline_picks_huggingface_backend():
    pipe = AssetGenerationPipeline()
    backend = pipe._backend(AssetGenerationBackend.HUGGINGFACE)
    assert isinstance(backend, HuggingFaceBackend)


def test_pipeline_picks_runpod_backend():
    pipe = AssetGenerationPipeline()
    backend = pipe._backend(AssetGenerationBackend.RUNPOD)
    assert isinstance(backend, RunPodBackend)


def test_pipeline_picks_rodin_backend():
    pipe = AssetGenerationPipeline()
    backend = pipe._backend(AssetGenerationBackend.RODIN)
    assert isinstance(backend, RodinBackend)


def test_pipeline_caches_backend_instances():
    pipe = AssetGenerationPipeline()
    a = pipe._backend(AssetGenerationBackend.HUGGINGFACE)
    b = pipe._backend(AssetGenerationBackend.HUGGINGFACE)
    assert a is b


# ---------------------------------------------------------------------------
# generate() with mock backend
# ---------------------------------------------------------------------------


def _make_fake_glb(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"glTF" + b"\x02\x00\x00\x00" + b"x" * 8192)
    return path


def test_pipeline_generate_writes_glb_and_sidecar(tmp_path: Path, monkeypatch):
    pipe = AssetGenerationPipeline()
    fake_backend = MagicMock()
    fake_backend.generate.side_effect = lambda req, out, timeout_s: _make_fake_glb(out)
    pipe._backends[AssetGenerationBackend.HUGGINGFACE] = fake_backend

    req = AssetRequest(prompt="boulder", asset_category="rock", output_name="rock_99")
    out = pipe.generate(req, backend=AssetGenerationBackend.HUGGINGFACE, output_dir=tmp_path)

    assert out.exists()
    sidecar = tmp_path / "rock_99.json"
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text())
    assert payload["prompt"] == "boulder"
    assert payload["asset_category"] == "rock"
    assert payload["backend"] == "huggingface"


def test_pipeline_generate_rejects_invalid_glb(tmp_path: Path):
    pipe = AssetGenerationPipeline()
    fake = MagicMock()

    def _bad(req, out, timeout_s):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"bad!")
        return out

    fake.generate.side_effect = _bad
    pipe._backends[AssetGenerationBackend.HUGGINGFACE] = fake

    req = AssetRequest(prompt="x", asset_category="rock", output_name="bad")
    with pytest.raises(RuntimeError, match="failed validation"):
        pipe.generate(req, backend=AssetGenerationBackend.HUGGINGFACE, output_dir=tmp_path)


def test_pipeline_batch_continues_on_error(tmp_path: Path):
    pipe = AssetGenerationPipeline()
    fake = MagicMock()
    calls = {"n": 0}

    def _flaky(req, out, timeout_s):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated failure")
        return _make_fake_glb(out)

    fake.generate.side_effect = _flaky
    pipe._backends[AssetGenerationBackend.HUGGINGFACE] = fake

    requests = [
        AssetRequest(prompt=f"r{i}", asset_category="rock", output_name=f"r{i}")
        for i in range(3)
    ]
    out = pipe.batch_generate(requests, output_dir=tmp_path, continue_on_error=True)
    # 3 attempted, 1 failed → 2 successes
    assert len(out) == 2


def test_pipeline_generate_from_concept(tmp_path: Path):
    pipe = AssetGenerationPipeline()
    fake = MagicMock()
    fake.generate.side_effect = lambda req, out, timeout_s: _make_fake_glb(out)
    pipe._backends[AssetGenerationBackend.HUGGINGFACE] = fake

    out = pipe.generate_from_concept(
        prompt="dark fantasy boulder",
        style_preset="veilbreakers_rock",
        output_dir=tmp_path,
        asset_category="rock",
        output_name="dfp_rock",
    )
    assert out.exists()
    # Check that the preset language reached the request.
    sent = fake.generate.call_args.args[0]
    assert "Elden Ring" in sent.prompt


# ---------------------------------------------------------------------------
# Backend smoke (no network)
# ---------------------------------------------------------------------------


def test_huggingface_backend_construct_with_token():
    b = HuggingFaceBackend(hf_token="abc")
    assert b.hf_token == "abc"
    assert b.space.startswith("tencent/")


def test_runpod_backend_construct_logs_warning(caplog):
    with caplog.at_level("WARNING"):
        RunPodBackend(endpoint_id=None, api_key=None)


def test_rodin_backend_construct_logs_warning(caplog):
    with caplog.at_level("WARNING"):
        RodinBackend(api_key=None)
