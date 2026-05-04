"""Tests for V-2: compare_render_to_golden + golden_scenarios fixture validation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import TypeAlias

import numpy as np
from numpy.typing import NDArray
import pytest

from veilbreakers_terrain.handlers.terrain_visual_qa import (
    compare_render_to_golden,
    handle_visual_qa_compare_render,
    validate_channel_manifest,
    REQUIRED_STACK_CHANNELS,
)
from veilbreakers_terrain.handlers.terrain_golden_snapshots import run_scenario_goldens
from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

_GOLDEN_SCENARIOS_DIR = Path(__file__).parent / "golden_scenarios"
_SCENARIO_FILES = list(_GOLDEN_SCENARIOS_DIR.glob("*.json"))

_HAS_PILLOW = importlib.util.find_spec("PIL") is not None

FloatArray: TypeAlias = NDArray[np.float32]
UInt8Array: TypeAlias = NDArray[np.uint8]
UInt16Array: TypeAlias = NDArray[np.uint16]
ChannelArray: TypeAlias = FloatArray | UInt8Array | UInt16Array
ChannelValue: TypeAlias = ChannelArray | None


def _write_rgb_png(path: Path, arr: FloatArray) -> None:
    from PIL import Image
    img = Image.fromarray((arr * 255).clip(0, 255).astype(np.uint8), mode="RGB")
    img.save(str(path))


# ---------------------------------------------------------------------------
# compare_render_to_golden
# ---------------------------------------------------------------------------

class TestCompareRenderToGolden:
    def test_golden_absent_blocks_by_default(self, tmp_path: Path) -> None:
        render = tmp_path / "render.png"
        golden = tmp_path / "golden_nonexistent.png"
        if _HAS_PILLOW:
            _write_rgb_png(render, np.ones((64, 64, 3), dtype=np.float32))
        result = compare_render_to_golden(str(render), str(golden))
        assert result["ok"] is False
        assert result["reason"] == "golden_absent"

    def test_golden_absent_can_be_allowed_for_seed_runs(self, tmp_path: Path) -> None:
        render = tmp_path / "render.png"
        golden = tmp_path / "golden_nonexistent.png"
        if _HAS_PILLOW:
            _write_rgb_png(render, np.ones((64, 64, 3), dtype=np.float32))
        result = compare_render_to_golden(
            str(render),
            str(golden),
            allow_missing_golden=True,
        )
        assert result["ok"] is True
        assert result["reason"] == "golden_absent"

    def test_render_absent_returns_ok_false(self, tmp_path: Path) -> None:
        render = tmp_path / "render_nonexistent.png"
        golden = tmp_path / "golden.png"
        if _HAS_PILLOW:
            _write_rgb_png(golden, np.ones((64, 64, 3), dtype=np.float32))
        else:
            golden.write_bytes(b"")
        result = compare_render_to_golden(str(render), str(golden))
        assert result["ok"] is False
        assert result["reason"] == "render_absent"

    def test_identical_images_pass(self, tmp_path: Path) -> None:
        img = np.random.default_rng(0).random((64, 64, 3)).astype(np.float32)
        render = tmp_path / "render.png"
        golden = tmp_path / "golden.png"
        _write_rgb_png(render, img)
        _write_rgb_png(golden, img)
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.95)
        assert result["ok"] is True
        assert result["ssim"] is not None
        assert result["ssim"] > 0.95

    def test_completely_different_images_fail(self, tmp_path: Path) -> None:
        render = tmp_path / "render.png"
        golden = tmp_path / "golden.png"
        ramp = np.linspace(0.0, 1.0, 64, dtype=np.float32)
        img = np.repeat(ramp[None, :], 64, axis=0)
        render_img = np.stack([img, np.roll(img, 7, axis=1), img.T], axis=2)
        golden_img = 1.0 - render_img
        _write_rgb_png(render, render_img)
        _write_rgb_png(golden, golden_img)
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.95)
        assert result["ok"] is False
        assert result["ssim"] is not None
        assert result["ssim"] < 0.95

    def test_identical_blank_images_fail_information_floor(self, tmp_path: Path) -> None:
        render = tmp_path / "render.png"
        golden = tmp_path / "golden.png"
        blank = np.zeros((64, 64, 3), dtype=np.float32)
        _write_rgb_png(render, blank)
        _write_rgb_png(golden, blank)
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.95)
        assert result["ok"] is False
        assert result["reason"].startswith("low_information_")

    def test_slightly_noisy_image_passes_low_threshold(self, tmp_path: Path) -> None:
        rng = np.random.default_rng(42)
        base = rng.random((64, 64, 3)).astype(np.float32)
        noisy = np.clip(
            base + rng.random((64, 64, 3)).astype(np.float32) * 0.02,
            0,
            1,
        ).astype(np.float32)
        render = tmp_path / "render.png"
        golden = tmp_path / "golden.png"
        _write_rgb_png(render, noisy)
        _write_rgb_png(golden, base)
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.80)
        assert result["ok"] is True

    def test_result_always_has_required_keys(self, tmp_path: Path) -> None:
        render = tmp_path / "r.png"
        golden = tmp_path / "g.png"
        result = compare_render_to_golden(str(render), str(golden))
        for key in ("ok", "ssim", "threshold", "render_path", "golden_path", "reason"):
            assert key in result, f"Missing key: {key}"

    def test_threshold_preserved_in_result(self, tmp_path: Path) -> None:
        render = tmp_path / "r.png"
        golden = tmp_path / "g.png"
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.80)
        assert result["threshold"] == 0.80

    def test_handle_wrapper_never_raises(self, tmp_path: Path) -> None:
        result = handle_visual_qa_compare_render(
            str(tmp_path / "bad.png"),
            str(tmp_path / "also_bad.png"),
        )
        assert isinstance(result, dict)
        assert "ok" in result

    def test_size_mismatch_handled(self, tmp_path: Path) -> None:
        render = tmp_path / "render.png"
        golden = tmp_path / "golden.png"
        rng = np.random.default_rng(3)
        _write_rgb_png(render, rng.random((32, 32, 3), dtype=np.float32))
        _write_rgb_png(golden, rng.random((64, 64, 3), dtype=np.float32))
        result = compare_render_to_golden(str(render), str(golden), ssim_threshold=0.90)
        assert result["ok"] is False
        assert result["reason"] == "shape_mismatch"


# ---------------------------------------------------------------------------
# Golden scenario fixture validation
# ---------------------------------------------------------------------------

REQUIRED_FIXTURE_KEYS = {
    "_scenario", "_description", "_version",
    "intent", "required_channels", "channel_assertions", "semantic_assertions",
}

REQUIRED_INTENT_KEYS = {"seed", "region_bounds", "tile_size", "cell_size"}


@pytest.mark.parametrize("scenario_file", _SCENARIO_FILES, ids=[f.stem for f in _SCENARIO_FILES])
class TestGoldenScenarioFixtures:
    def test_file_is_valid_json(self, scenario_file: Path) -> None:
        text = scenario_file.read_text(encoding="utf-8")
        data = json.loads(text)
        assert isinstance(data, dict)

    def test_required_top_level_keys_present(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        missing = REQUIRED_FIXTURE_KEYS - set(data.keys())
        assert not missing, f"{scenario_file.name} missing keys: {missing}"

    def test_intent_has_required_fields(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        intent = data.get("intent", {})
        missing = REQUIRED_INTENT_KEYS - set(intent.keys())
        assert not missing, f"{scenario_file.name} intent missing: {missing}"

    def test_seed_is_int(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert isinstance(data["intent"]["seed"], int)

    def test_region_bounds_is_four_numbers(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        bounds = data["intent"]["region_bounds"]
        assert isinstance(bounds, list) and len(bounds) == 4
        assert all(isinstance(v, (int, float)) for v in bounds)

    def test_required_channels_is_non_empty_list(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        channels = data.get("required_channels", [])
        assert isinstance(channels, list) and len(channels) >= 1

    def test_required_channels_are_strings(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        for ch in data.get("required_channels", []):
            assert isinstance(ch, str) and ch, f"Channel must be non-empty string: {ch!r}"

    def test_channel_assertions_is_dict(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert isinstance(data.get("channel_assertions"), dict)

    def test_semantic_assertions_is_non_empty_list(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assertions = data.get("semantic_assertions")
        assert isinstance(assertions, list) and assertions, (
            f"{scenario_file.name} must execute semantic assertions, not just schema checks"
        )

    def test_version_is_positive_int(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert isinstance(data["_version"], int) and data["_version"] >= 1

    def test_scenario_name_matches_filename(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert data["_scenario"] == scenario_file.stem, (
            f"_scenario '{data['_scenario']}' does not match filename '{scenario_file.stem}'"
        )


@pytest.mark.parametrize("scenario_file", _SCENARIO_FILES, ids=[f.stem for f in _SCENARIO_FILES])
class TestGoldenScenarioSemantics:
    def test_json_scenario_executes_against_rich_semantic_stack(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        result = run_scenario_goldens(
            _rich_semantic_golden_stack(),
            scenarios={data["_scenario"]: data},
        )
        outcome = result["results"][data["_scenario"]]
        assert outcome["ok"] is True, outcome

    def test_json_scenario_fails_when_required_channel_missing(self, scenario_file: Path) -> None:
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        stack = _rich_semantic_golden_stack()
        required = data["required_channels"][0]
        canonical = "height" if required == "heightmap" else required
        object.__setattr__(stack, canonical, None)
        result = run_scenario_goldens(stack, scenarios={data["_scenario"]: data})
        outcome = result["results"][data["_scenario"]]
        assert outcome["ok"] is False
        assert any(str(required) in issue for issue in outcome["issues"])


class TestGoldenScenarioCrossChannelSemantics:
    def test_deep_lake_rejects_depth_outside_water_mask(self) -> None:
        data = json.loads((_GOLDEN_SCENARIOS_DIR / "deep_lake_basin.json").read_text(encoding="utf-8"))
        stack = _rich_semantic_golden_stack()
        bad_depth = np.full_like(stack.water_depth_m, 50.0)
        stack.set("water_depth_m", bad_depth, "bad_fixture")
        result = run_scenario_goldens(stack, scenarios={data["_scenario"]: data})
        outcome = result["results"][data["_scenario"]]
        assert outcome["ok"] is False
        assert any("depth_requires_water_mask" in issue for issue in outcome["issues"])

    def test_cliff_talus_rejects_disconnected_talus(self) -> None:
        data = json.loads((_GOLDEN_SCENARIOS_DIR / "cliff_talus_apron.json").read_text(encoding="utf-8"))
        stack = _rich_semantic_golden_stack()
        talus = np.zeros_like(stack.talus_mask)
        talus[:, :4] = 1.0
        stack.set("talus_mask", talus, "bad_fixture")
        result = run_scenario_goldens(stack, scenarios={data["_scenario"]: data})
        outcome = result["results"][data["_scenario"]]
        assert outcome["ok"] is False
        assert any("talus_near_cliff" in issue for issue in outcome["issues"])

    def test_waterfall_rejects_foam_not_near_water(self) -> None:
        data = json.loads((_GOLDEN_SCENARIOS_DIR / "waterfall_plunge_pool.json").read_text(encoding="utf-8"))
        stack = _rich_semantic_golden_stack()
        foam = np.zeros_like(stack.foam)
        foam[:4, :4] = 1.0
        stack.set("foam", foam, "bad_fixture")
        result = run_scenario_goldens(stack, scenarios={data["_scenario"]: data})
        outcome = result["results"][data["_scenario"]]
        assert outcome["ok"] is False
        assert any("foam_near_water" in issue for issue in outcome["issues"])


# ---------------------------------------------------------------------------
# V-1: validate_channel_manifest
# ---------------------------------------------------------------------------

def _make_stack(**channels: ChannelValue) -> TerrainMaskStack:
    """Build a production TerrainMaskStack with provided channel arrays."""
    height: ChannelArray = np.asarray(
        channels.pop("height", np.zeros((1, 3), dtype=np.float32))
    )
    stack = TerrainMaskStack(
        tile_size=max(int(height.shape[0]) - 1, 0) if height.ndim >= 2 else 0,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    for channel, value in channels.items():
        if value is None:
            object.__setattr__(stack, channel, None)
        elif hasattr(stack, channel):
            stack.set(channel, value, "test_fixture")
        else:
            object.__setattr__(stack, channel, value)
    return stack

def _full_valid_stack() -> TerrainMaskStack:
    """Return a TerrainMaskStack with all REQUIRED_STACK_CHANNELS in-range."""
    splat = np.zeros((1, 3, 4), dtype=np.float32)
    splat[..., 0] = 1.0
    normals = np.zeros((1, 3, 3), dtype=np.float32)
    normals[..., 2] = 1.0
    return _make_stack(
        height=np.array([[0.0, 500.0, 9000.0]], dtype=np.float32),
        slope=np.array([[0.0, 30.0, 90.0]], dtype=np.float32),
        curvature=np.array([[-1.0, 0.0, 1.0]], dtype=np.float32),
        ridge=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        basin=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        flow_accumulation=np.array([[0.0, 100.0, 1000.0]], dtype=np.float32),
        wetness=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        drainage=np.array([[0.0, 100.0, 1000.0]], dtype=np.float32),
        water_surface_mask=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        water_surface_elevation_m=np.array([[0.0, 500.0, 9000.0]], dtype=np.float32),
        water_depth_m=np.array([[0.0, 100.0, 500.0]], dtype=np.float32),
        cliff_mask=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        talus_mask=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        strata_mask=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        foam=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        mist=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        splatmap_weights_layer=splat,
        heightmap_raw_u16=np.array([[0, 32768, 65535]], dtype=np.uint16),
        terrain_normals=normals,
        ambient_occlusion_bake=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        navmesh_area_id=np.array([[0, 1, 255]], dtype=np.uint8),
        gameplay_zone=np.array([[0, 2, 255]], dtype=np.uint8),
        traversability=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
        road_mask=np.array([[0.0, 0.5, 1.0]], dtype=np.float32),
    )


def _rich_semantic_golden_stack() -> TerrainMaskStack:
    """Build one terrain tile rich enough to exercise all JSON golden semantics."""
    size = 64
    y, x = np.indices((size, size), dtype=np.float32)
    height = 80.0 + x * 2.0 + y * 0.4
    height[:, 30:] += 45.0

    cliff = np.zeros((size, size), dtype=np.float32)
    cliff[:, 28:31] = 1.0
    slope = np.full((size, size), 12.0, dtype=np.float32)
    slope[:, 28:31] = 48.0
    talus = np.zeros((size, size), dtype=np.float32)
    talus[:, 30:33] = 0.85
    strata = (1.0 + ((y // 8) % 4).astype(np.float32)) / 4.0

    cave = np.zeros((size, size), dtype=np.float32)
    cave[26:34, 29:31] = 1.0

    cy, cx = 38.0, 34.0
    dist = np.sqrt((y - cy) ** 2 + (x - cx) ** 2)
    water_mask = (dist <= 15.0).astype(np.float32)
    surface = np.full((size, size), 330.0, dtype=np.float32)
    water_depth = np.where(water_mask > 0.5, np.maximum(surface - height, 0.0), 0.0).astype(np.float32)
    bathymetry = water_depth.copy()
    shoreline = (np.abs(dist - 15.0) <= 2.5).astype(np.float32)
    flow_acc = np.where(dist <= 18.0, 25.0, 0.0).astype(np.float32)
    flow_dir = np.zeros((size, size), dtype=np.float32)
    flow_dir[:, :] = 3.0
    foam = ((dist <= 16.0) & (dist >= 12.0)).astype(np.float32)
    lip = np.zeros((size, size), dtype=np.float32)
    lip[32:38, 29:31] = 1.0

    return _make_stack(
        height=height.astype(np.float32),
        slope=slope,
        cliff_mask=cliff,
        cliff_candidate=cliff,
        talus_mask=talus,
        strata_mask=strata,
        cave_candidate=cave,
        water_surface_mask=water_mask,
        water_surface_elevation_m=surface,
        water_depth_m=water_depth,
        shoreline_blend=shoreline,
        bathymetry=bathymetry,
        wetness=np.where(dist <= 18.0, 0.9, 0.2).astype(np.float32),
        flow_accumulation=flow_acc,
        flow_direction=flow_dir,
        foam=foam,
        waterfall_lip_candidate=lip,
    )


class TestValidateChannelManifest:

    def test_valid_stack_passes(self) -> None:
        """A stack with all required channels in-range returns valid=True."""
        result = validate_channel_manifest(_full_valid_stack())
        assert result["valid"] is True
        assert result["missing"] == []
        assert result["out_of_range"] == []
        assert result["issues"] == []

    def test_missing_channel_detected(self) -> None:
        """A stack missing one channel reports it in 'missing' and 'issues'."""
        stack = _full_valid_stack()
        del stack.cliff_mask  # remove attribute entirely
        result = validate_channel_manifest(stack)
        assert result["valid"] is False
        assert "cliff_mask" in result["missing"]
        assert any("missing:cliff_mask" in s for s in result["issues"])

    def test_out_of_range_value_detected(self) -> None:
        """A channel whose max exceeds the declared bound is reported in out_of_range."""
        stack = _full_valid_stack()
        # height max is 9000.0; push well beyond it
        stack.set("height", np.array([[0.0, 99999.0]], dtype=np.float32), "test_fixture")
        result = validate_channel_manifest(stack)
        assert result["valid"] is False
        assert "height" in result["out_of_range"]
        assert any("out_of_range:height" in s for s in result["issues"])

    def test_custom_required_channels_overrides_default(self) -> None:
        """Passing a custom spec only validates the channels in that spec."""
        custom_spec = {
            "heightmap": ("float", (0.0, 9000.0)),
        }
        # Stack only has 'heightmap'; default spec would flag others as missing,
        # but with the custom spec the result should be valid.
        stack = _make_stack(heightmap=np.array([0.0, 1000.0], dtype=np.float32))
        result = validate_channel_manifest(stack, required_channels=custom_spec)
        assert result["valid"] is True
        assert result["missing"] == []

    def test_result_always_has_required_keys(self) -> None:
        """The return dict always contains the four documented keys."""
        stack = _full_valid_stack()
        for channel in REQUIRED_STACK_CHANNELS:
            object.__setattr__(stack, channel, None)
        result = validate_channel_manifest(stack)
        for key in ("valid", "missing", "out_of_range", "issues"):
            assert key in result, f"Missing key: {key!r}"

    def test_valid_is_bool(self) -> None:
        """'valid' key is a strict bool, not just truthy."""
        result = validate_channel_manifest(_full_valid_stack())
        assert isinstance(result["valid"], bool)

    def test_multiple_missing_channels_all_reported(self) -> None:
        """Every missing channel appears in both 'missing' and 'issues'."""
        stack = _full_valid_stack()
        for channel in REQUIRED_STACK_CHANNELS:
            object.__setattr__(stack, channel, None)
        result = validate_channel_manifest(stack)
        assert result["valid"] is False
        for ch in REQUIRED_STACK_CHANNELS:
            assert ch in result["missing"], f"{ch} not in missing"
            assert any(f"missing:{ch}" in s for s in result["issues"]), (
                f"missing:{ch} not in issues"
            )
