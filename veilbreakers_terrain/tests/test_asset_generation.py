"""Unit tests for veilbreakers_terrain.handlers.asset_generation.

These tests do not hit the network — backend implementations are
monkey-patched at the call site.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="veilbreakers_terrain.handlers.asset_generation is deprecated.*",
        category=DeprecationWarning,
    )
    import veilbreakers_terrain.handlers.asset_generation as asset_generation
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
        _atomic_copy,
        _atomic_write_json,
        _progress,
        _retry,
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


def test_progress_prints_desc_without_tqdm(monkeypatch, capsys):
    monkeypatch.setattr(asset_generation, "_tqdm", None)

    out = list(_progress([1, 2, 3], desc="asset pass"))

    assert out == [1, 2, 3]
    assert "asset pass" in capsys.readouterr().out


def test_retry_retries_then_returns(monkeypatch):
    monkeypatch.setattr(asset_generation.time, "sleep", lambda _seconds: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("try again")
        return "ok"

    assert _retry(flaky, max_attempts=2, base_delay_s=0.01, label="unit") == "ok"
    assert calls["n"] == 2


def test_retry_raises_last_exception(monkeypatch):
    monkeypatch.setattr(asset_generation.time, "sleep", lambda _seconds: None)

    with pytest.raises(ValueError, match="final"):
        _retry(lambda: (_ for _ in ()).throw(ValueError("final")), max_attempts=2)


def test_atomic_copy_and_json_replace_tmp_files(tmp_path: Path):
    src = tmp_path / "src.glb"
    dst = tmp_path / "nested" / "out.glb"
    src.write_bytes(b"glTF" + b"x" * 2048)

    copied = _atomic_copy(src, dst)
    json_path = _atomic_write_json(tmp_path / "nested" / "meta.json", {"b": 2, "a": 1})

    assert copied == dst
    assert dst.read_bytes() == src.read_bytes()
    assert json.loads(json_path.read_text()) == {"a": 1, "b": 2}
    assert not list((tmp_path / "nested").glob("*.tmp"))


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


def test_pipeline_build_backend_rejects_unknown_backend():
    pipe = AssetGenerationPipeline()

    with pytest.raises(ValueError, match="Unknown backend"):
        pipe._build_backend("bad")  # type: ignore[arg-type]


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


def test_huggingface_lazy_client_and_wrap_image(monkeypatch, tmp_path: Path):
    seen: dict[str, object] = {}

    class FakeClient:
        def __init__(self, space, hf_token=None):
            seen["space"] = space
            seen["hf_token"] = hf_token

    def fake_handle_file(path: str) -> str:
        return f"wrapped:{Path(path).name}"

    monkeypatch.setitem(
        sys.modules,
        "gradio_client",
        SimpleNamespace(Client=FakeClient, handle_file=fake_handle_file),
    )
    image = tmp_path / "ref.png"
    image.write_bytes(b"png")
    backend = HuggingFaceBackend(space="space/test", hf_token="tok")

    client = backend._client()
    wrapped = backend._wrap_image(image)

    assert isinstance(client, FakeClient)
    assert seen == {"space": "space/test", "hf_token": "tok"}
    assert wrapped == "wrapped:ref.png"
    assert backend._wrap_image(None) is None


def test_runpod_backend_construct_logs_warning(caplog):
    with caplog.at_level("WARNING"):
        RunPodBackend(endpoint_id=None, api_key=None)


def test_runpod_lazy_import_and_download_stream(monkeypatch, tmp_path: Path):
    fake_runpod = SimpleNamespace(api_key=None)
    monkeypatch.setitem(sys.modules, "runpod", fake_runpod)

    backend = RunPodBackend(endpoint_id="ep", api_key="key")
    assert backend._runpod() is fake_runpod
    assert fake_runpod.api_key == "key"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"glTF"
            yield b"x" * 2048

    monkeypatch.setitem(
        sys.modules,
        "requests",
        SimpleNamespace(get=lambda *args, **kwargs: FakeResponse()),
    )

    dest = RunPodBackend._download("https://example.invalid/out.glb", tmp_path / "out.glb")
    assert dest.read_bytes().startswith(b"glTF")


def test_rodin_backend_construct_logs_warning(caplog):
    with caplog.at_level("WARNING"):
        RodinBackend(api_key=None)


def test_rodin_lazy_requests_and_headers(monkeypatch):
    fake_requests = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    backend = RodinBackend(api_key="rodin-key", base_url="https://api.test/")

    assert backend._requests() is fake_requests
    assert backend._headers() == {"Authorization": "Bearer rodin-key"}
    assert backend.base_url == "https://api.test"
