"""Unit coverage for the scene-v3 visual quality gate helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "scene_v3_visual_quality_gate.py"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location("_scene_v3_visual_quality_gate", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_png(path: Path, *, varied: bool) -> None:
    from PIL import Image

    img = Image.new("RGB", (1920, 1080))
    pixels = img.load()
    assert pixels is not None
    for y in range(1080):
        for x in range(1920):
            if varied:
                pixels[x, y] = (
                    (x * 3 + y) % 256,
                    (x // 5 + y * 2) % 256,
                    (x + y // 3) % 256,
                )
            else:
                pixels[x, y] = (48, 48, 48)
    img.save(path)


def test_visual_gate_flags_flat_blank_renders(tmp_path):
    gate = _load_gate_module()
    image_path = tmp_path / "blank.png"
    _write_png(image_path, varied=False)

    report = gate.analyze_image_file(image_path)

    assert report["exists"] is True
    assert "render_flat_or_blank" in report["issues"]
    assert report["width"] == 1920
    assert report["height"] == 1080


def test_visual_gate_accepts_varied_full_resolution_render(tmp_path):
    gate = _load_gate_module()
    image_path = tmp_path / "varied.png"
    _write_png(image_path, varied=True)

    report = gate.analyze_image_file(image_path)

    assert report["exists"] is True
    assert report["issues"] == []
    assert report["color_bucket_count"] >= gate.MIN_COLOR_BUCKETS
    assert report["edge_density"] >= gate.MIN_EDGE_DENSITY


def test_visual_gate_requires_user_prompt_specific_closeups():
    gate = _load_gate_module()

    required = gate.REQUIRED_CLOSEUPS

    assert "05_waterfall_closeup" in required
    assert "07_bridge_waterline" in required
    assert "08_bridge_approach_path" in required
    assert "10_large_water_panorama" in required
    assert "14_forest_bridge_side" in required
