"""Tests for V-2: compare_render_to_golden + golden_scenarios fixture validation."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_visual_qa import (
    compare_render_to_golden,
    handle_visual_qa_compare_render,
)

_GOLDEN_SCENARIOS_DIR = Path(__file__).parent / "golden_scenarios"
_SCENARIO_FILES = list(_GOLDEN_SCENARIOS_DIR.glob("*.json"))

_HAS_PILLOW = False
try:
    from PIL import Image
    _HAS_PILLOW = True
except ImportError:
    pass


def _write_rgb_png(path: Path, arr: np.ndarray) -> None:
    from PIL import Image
    img = Image.fromarray((arr * 255).clip(0, 255).astype(np.uint8), mode="RGB")
    img.save(str(path))


# ---------------------------------------------------------------------------
# compare_render_to_golden
# ---------------------------------------------------------------------------

class TestCompareRenderToGolden:
    def test_golden_absent_returns_ok_true(self, tmp_path):
        render = tmp_path / "render.png"
        golden = tmp_path / "golden_nonexistent.png"
        if _HAS_PILLOW:
            _write_rgb_png(render, np.ones((64, 64, 3), dtype=np.float32))
        result = compare_render_to_golden(str(render), str(golden))
        assert result["ok"] is True
        assert result["reason"] == "golden_absent"

    def test_render_absent_returns_ok_false(self, tmp_path):
        render = tmp_path / "render_nonexistent.png"
        golden = tmp_path / "golden.png"
        if _HAS_PILLOW:
            _write_rgb_png(golden, np.ones((64, 64, 3), dtype=np.float32))
        else:
            golden.write_bytes(b"")
        result = compare_render_to_golden(str(render), str(golden))
        assert result["ok"] is False
        assert result["reason"] == "render_absent"

    @pytest.mark.skipif(not _HAS_PILLOW, reason="Pillow not installed")
    def test_identical_images_pass(self, tmp_path):
        img = np.random.default_rng(0).random((64, 64, 3)).astype(np.float32)
        render = tmp_path / "render.png"
        golden = tmp_path / "golden.png"
        _write_rgb_png(render, img)
        _write_rgb_png(golden, img)
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.95)
        assert result["ok"] is True
        assert result["ssim"] is not None
        assert result["ssim"] > 0.95

    @pytest.mark.skipif(not _HAS_PILLOW, reason="Pillow not installed")
    def test_completely_different_images_fail(self, tmp_path):
        rng = np.random.default_rng(1)
        render = tmp_path / "render.png"
        golden = tmp_path / "golden.png"
        _write_rgb_png(render, np.zeros((64, 64, 3), dtype=np.float32))
        _write_rgb_png(golden, np.ones((64, 64, 3), dtype=np.float32))
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.95)
        assert result["ok"] is False
        assert result["ssim"] is not None
        assert result["ssim"] < 0.95

    @pytest.mark.skipif(not _HAS_PILLOW, reason="Pillow not installed")
    def test_slightly_noisy_image_passes_low_threshold(self, tmp_path):
        rng = np.random.default_rng(42)
        base = rng.random((64, 64, 3)).astype(np.float32)
        noisy = np.clip(base + rng.random((64, 64, 3)).astype(np.float32) * 0.02, 0, 1)
        render = tmp_path / "render.png"
        golden = tmp_path / "golden.png"
        _write_rgb_png(render, noisy)
        _write_rgb_png(golden, base)
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.80)
        assert result["ok"] is True

    def test_result_always_has_required_keys(self, tmp_path):
        render = tmp_path / "r.png"
        golden = tmp_path / "g.png"
        result = compare_render_to_golden(str(render), str(golden))
        for key in ("ok", "ssim", "threshold", "render_path", "golden_path", "reason"):
            assert key in result, f"Missing key: {key}"

    def test_threshold_preserved_in_result(self, tmp_path):
        render = tmp_path / "r.png"
        golden = tmp_path / "g.png"
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.80)
        assert result["threshold"] == 0.80

    def test_handle_wrapper_never_raises(self, tmp_path):
        result = handle_visual_qa_compare_render(
            str(tmp_path / "bad.png"),
            str(tmp_path / "also_bad.png"),
        )
        assert isinstance(result, dict)
        assert "ok" in result

    @pytest.mark.skipif(not _HAS_PILLOW, reason="Pillow not installed")
    def test_size_mismatch_handled(self, tmp_path):
        render = tmp_path / "render.png"
        golden = tmp_path / "golden.png"
        _write_rgb_png(render, np.ones((32, 32, 3), dtype=np.float32))
        _write_rgb_png(golden, np.ones((64, 64, 3), dtype=np.float32))
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.90)
        # Should not crash; identical color → should pass
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# Golden scenario fixture validation
# ---------------------------------------------------------------------------

REQUIRED_FIXTURE_KEYS = {
    "_scenario", "_description", "_version",
    "intent", "required_channels", "channel_assertions",
}

REQUIRED_INTENT_KEYS = {"seed", "region_bounds", "tile_size", "cell_size"}


@pytest.mark.parametrize("scenario_file", _SCENARIO_FILES, ids=[f.stem for f in _SCENARIO_FILES])
class TestGoldenScenarioFixtures:
    def test_file_is_valid_json(self, scenario_file):
        text = scenario_file.read_text(encoding="utf-8")
        data = json.loads(text)
        assert isinstance(data, dict)

    def test_required_top_level_keys_present(self, scenario_file):
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        missing = REQUIRED_FIXTURE_KEYS - set(data.keys())
        assert not missing, f"{scenario_file.name} missing keys: {missing}"

    def test_intent_has_required_fields(self, scenario_file):
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        intent = data.get("intent", {})
        missing = REQUIRED_INTENT_KEYS - set(intent.keys())
        assert not missing, f"{scenario_file.name} intent missing: {missing}"

    def test_seed_is_int(self, scenario_file):
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert isinstance(data["intent"]["seed"], int)

    def test_region_bounds_is_four_numbers(self, scenario_file):
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        bounds = data["intent"]["region_bounds"]
        assert isinstance(bounds, list) and len(bounds) == 4
        assert all(isinstance(v, (int, float)) for v in bounds)

    def test_required_channels_is_non_empty_list(self, scenario_file):
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        channels = data.get("required_channels", [])
        assert isinstance(channels, list) and len(channels) >= 1

    def test_required_channels_are_strings(self, scenario_file):
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        for ch in data.get("required_channels", []):
            assert isinstance(ch, str) and ch, f"Channel must be non-empty string: {ch!r}"

    def test_channel_assertions_is_dict(self, scenario_file):
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert isinstance(data.get("channel_assertions"), dict)

    def test_version_is_positive_int(self, scenario_file):
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert isinstance(data["_version"], int) and data["_version"] >= 1

    def test_scenario_name_matches_filename(self, scenario_file):
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert data["_scenario"] == scenario_file.stem, (
            f"_scenario '{data['_scenario']}' does not match filename '{scenario_file.stem}'"
        )
