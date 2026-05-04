"""Tests for ``scripts/visual_testing_readiness_gate.py``.

The gate script imports the real terrain handler registry and MCP dispatch
layer. These tests stub both ends so behaviour can be exercised deterministically
without Blender, and so we can assert:

  * fail-hard on missing Blender runtime (no flag  -> exit 1;
    ``--allow-no-blender`` -> exit 0 with ``ready=False``),
  * placeholder PNGs (<500 bytes) are rejected,
  * pixel-diff exceedance against a synthetic reference trips the gate.
"""

from __future__ import annotations

import importlib
import json
import struct
import sys
import zlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, TypeAlias, TypedDict, cast

import pytest


JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonMap: TypeAlias = dict[str, JsonValue]
Handler: TypeAlias = Callable[..., JsonMap]


class GateModule(Protocol):
    THUMBNAIL_NAME: str
    PIXEL_DIFF_CHANNEL_THRESHOLD: float

    def run_gate(
        self,
        *,
        allow_no_blender: bool,
        screenshot_width: int,
        screenshot_height: int,
    ) -> tuple[JsonMap, int]: ...

    def main(self, argv: list[str] | None = None) -> int: ...

    def _compute_perceptual_hash(self, blob: bytes) -> str: ...


class StubState(TypedDict):
    screenshot_payload: JsonMap


class RedirectedPaths(TypedDict):
    output_dir: Path
    reference_dir: Path
    thumbnail: Path
    reference: Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_gate_module() -> GateModule:
    # Ensure a fresh import so module-level REPO_ROOT / constants reflect test
    # state (they don't rely on tmp_path, but re-importing avoids stale test
    # dispatch stubs bleeding across tests).
    if "visual_testing_readiness_gate" in sys.modules:
        del sys.modules["visual_testing_readiness_gate"]
    return cast(GateModule, importlib.import_module("visual_testing_readiness_gate"))


def _force_no_blender(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the gate observes blender_runtime_detected=False.

    We cannot simply remove ``bpy`` from ``sys.modules`` because the gate uses
    ``import bpy`` inline and Python's import system will re-probe site-packages.
    Instead we inject a stub whose class module starts with ``"unittest"`` so
    the gate's detection heuristic treats it as a mock.
    """

    class _StubBpy:  # noqa: N801 - namespace shim
        pass

    _StubBpy.__module__ = "unittest.mock"
    monkeypatch.setitem(sys.modules, "bpy", _StubBpy())


def _json_mapping(value: JsonValue) -> Mapping[str, JsonValue]:
    assert isinstance(value, dict)
    return value


def _json_list(value: JsonValue) -> list[JsonValue]:
    assert isinstance(value, list)
    return value


def _json_number(value: JsonValue) -> int | float:
    assert isinstance(value, (int, float))
    return value


def _make_png(width: int, height: int, fill_rgb: tuple[int, int, int]) -> bytes:
    """Produce a real PNG blob for pixel-diff tests.

    We deliberately add a light per-pixel perturbation so the encoded result
    exceeds the 500-byte placeholder threshold enforced by the gate, and the
    perceptual hash has meaningful content to bite on. A purely solid image
    would compress to ~80 bytes and trip the placeholder check.
    """

    signature = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    r, g, b = fill_rgb
    rows: list[bytes] = []
    for y in range(height):
        pixels = bytearray()
        for x in range(width):
            # Deterministic low-amplitude noise so compression cannot flatten
            # the image to a sub-500-byte blob. The noise stays within +/-3 of
            # the base colour, which keeps mean-abs-diff comparisons stable.
            jitter = (x * 7 + y * 13) % 7
            pixels.append((r + jitter) & 0xFF)
            pixels.append((g + jitter) & 0xFF)
            pixels.append((b + jitter) & 0xFF)
        rows.append(b"\x00" + bytes(pixels))
    raw = b"".join(rows)
    # Use minimum compression to keep the encoded payload well above 500 bytes.
    idat = zlib.compress(raw, level=0)
    return (
        signature
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def _stub_handlers(monkeypatch: pytest.MonkeyPatch) -> StubState:
    """Install a minimally wired COMMAND_HANDLERS + dispatch stack.

    Returns the per-test state dict so tests can tweak individual probes.
    """

    state: StubState = {"screenshot_payload": {"status": "ok", "result": {}}}

    def ok_empty(**_kw: object) -> JsonMap:
        return {"status": "ok", "result": {}}

    def ok_viewport(**_kw: object) -> JsonMap:
        return {"status": "ok", "result": {"vantage": {}}}

    def ok_screenshot(**_kw: object) -> JsonMap:
        return state["screenshot_payload"]

    def ok_materials(**_kw: object) -> JsonMap:
        return {
            "status": "ok",
            "result": {"count": 60, "materials": []},
        }

    handlers: dict[str, Handler] = {
        "terrain_capture_scene_read": ok_empty,
        "terrain_read_viewport_vantage": ok_viewport,
        "terrain_assert_vantage_fresh": ok_empty,
        "terrain_is_in_frustum": ok_empty,
        "visual_qa_setup_camera": ok_empty,
        "visual_qa_set_shading": ok_empty,
        "visual_qa_capture_screenshot": ok_screenshot,
        "material_create_procedural": ok_materials,
        "terrain_generate_lods": ok_empty,
        "terrain_validation": ok_empty,
    }

    locations: dict[str, str] = {
        "scene_read": "terrain_capture_scene_read",
        "viewport_read": "terrain_read_viewport_vantage",
        "viewport_fresh": "terrain_assert_vantage_fresh",
        "frustum_check": "terrain_is_in_frustum",
        "visual_setup_camera": "visual_qa_setup_camera",
        "visual_set_shading": "visual_qa_set_shading",
        "visual_capture_screenshot": "visual_qa_capture_screenshot",
        "material_procedural": "material_create_procedural",
        "terrain_lods": "terrain_generate_lods",
        "validation": "terrain_validation",
    }

    def fake_dispatch(location: str, params: Mapping[str, object]) -> JsonMap:
        command = locations.get(location)
        if command is None:
            return {"status": "error", "error": "unknown_location"}
        handler = handlers[command]
        payload = handler(**params)
        # Wrap into the standard dispatch envelope the gate expects.
        envelope: JsonMap = {
            "status": payload.get("status", "ok"),
            "command": command,
            "result": payload.get("result", {}),
        }
        if "captured" in payload or "width" in payload:
            # For the screenshot path, surface handler fields directly.
            envelope["result"] = {
                k: v for k, v in payload.items() if k != "status"
            }
        return envelope

    def fake_resolve(location: str) -> str | None:
        return locations.get(location)

    import veilbreakers_terrain.handlers as real_handlers
    import veilbreakers_terrain.src.veilbreakers_mcp.blender_server as real_bs

    monkeypatch.setattr(real_handlers, "COMMAND_HANDLERS", handlers, raising=False)
    monkeypatch.setattr(real_bs, "dispatch", fake_dispatch, raising=False)
    monkeypatch.setattr(real_bs, "resolve_command", fake_resolve, raising=False)

    return state


def _redirect_outputs(
    monkeypatch: pytest.MonkeyPatch, gate_mod: GateModule, tmp_path: Path
) -> RedirectedPaths:
    output_dir = tmp_path / "visual_readiness"
    reference_dir = output_dir / "reference"
    thumbnail = output_dir / gate_mod.THUMBNAIL_NAME
    reference = reference_dir / gate_mod.THUMBNAIL_NAME

    monkeypatch.setattr(gate_mod, "OUTPUT_DIR", output_dir, raising=False)
    monkeypatch.setattr(gate_mod, "REFERENCE_DIR", reference_dir, raising=False)
    monkeypatch.setattr(
        gate_mod, "JSON_OUT", output_dir / "VISUAL_TESTING_READINESS.json", raising=False
    )
    monkeypatch.setattr(
        gate_mod, "MD_OUT", output_dir / "VISUAL_TESTING_READINESS.md", raising=False
    )
    monkeypatch.setattr(gate_mod, "THUMBNAIL_PATH", thumbnail, raising=False)
    monkeypatch.setattr(gate_mod, "REFERENCE_PATH", reference, raising=False)

    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "output_dir": output_dir,
        "reference_dir": reference_dir,
        "thumbnail": thumbnail,
        "reference": reference,
    }


def _set_screenshot_result(
    state: StubState,
    thumbnail: Path,
    *,
    width: int,
    height: int,
    png_bytes: bytes | None,
    captured: bool = True,
) -> None:
    if png_bytes is not None:
        thumbnail.parent.mkdir(parents=True, exist_ok=True)
        thumbnail.write_bytes(png_bytes)
    state["screenshot_payload"] = {
        "status": "ok",
        "result": {
            "filepath": str(thumbnail),
            "width": width,
            "height": height,
            "captured": captured,
        },
    }


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_gate_fails_hard_when_blender_runtime_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gate = _load_gate_module()
    state = _stub_handlers(monkeypatch)
    paths = _redirect_outputs(monkeypatch, gate, tmp_path)

    png = _make_png(32, 32, (10, 20, 30))
    _set_screenshot_result(
        state, paths["thumbnail"], width=320, height=180, png_bytes=png
    )

    _force_no_blender(monkeypatch)

    payload, code = gate.run_gate(allow_no_blender=False, screenshot_width=320, screenshot_height=180)
    assert code == 1
    assert payload["ready_for_visual_testing"] is False
    assert payload["blender_runtime_detected"] is False
    assert "no_blender_runtime" in _json_list(payload["blockers"])


def test_gate_allow_no_blender_exits_zero_but_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gate = _load_gate_module()
    state = _stub_handlers(monkeypatch)
    paths = _redirect_outputs(monkeypatch, gate, tmp_path)

    png = _make_png(32, 32, (10, 20, 30))
    _set_screenshot_result(
        state, paths["thumbnail"], width=320, height=180, png_bytes=png
    )
    _force_no_blender(monkeypatch)

    payload, code = gate.run_gate(allow_no_blender=True, screenshot_width=320, screenshot_height=180)
    assert code == 0
    assert payload["ready_for_visual_testing"] is False
    assert payload["allow_no_blender"] is True
    assert "no_blender_runtime" in _json_list(payload["blockers"])
    assert payload["placeholder_png"] is False


def test_gate_rejects_placeholder_png_even_with_allow_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gate = _load_gate_module()
    state = _stub_handlers(monkeypatch)
    paths = _redirect_outputs(monkeypatch, gate, tmp_path)

    # 8-byte fake file, same as the historical placeholder shipped by the
    # broken gate.
    _set_screenshot_result(
        state, paths["thumbnail"], width=320, height=180, png_bytes=b"\x89PNG\x00\x00\x00\x00"
    )
    _force_no_blender(monkeypatch)

    payload, code = gate.run_gate(allow_no_blender=True, screenshot_width=320, screenshot_height=180)
    assert code == 1  # placeholder trumps --allow-no-blender
    assert payload["placeholder_png"] is True
    assert "placeholder_png" in _json_list(payload["blockers"])
    assert _json_number(payload["captured_byte_length"]) < 500


def test_gate_rejects_corrupt_nonplaceholder_png(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gate = _load_gate_module()
    state = _stub_handlers(monkeypatch)
    paths = _redirect_outputs(monkeypatch, gate, tmp_path)

    corrupt_png = b"not-a-real-png" * 64
    reference = _make_png(16, 16, (10, 20, 30))
    paths["reference_dir"].mkdir(parents=True, exist_ok=True)
    paths["reference"].write_bytes(reference)
    _set_screenshot_result(
        state, paths["thumbnail"], width=320, height=180, png_bytes=corrupt_png
    )
    monkeypatch.setattr(gate, "_running_in_blender_runtime", lambda: True)
    monkeypatch.setattr(gate, "_ensure_blender_readiness_fixture", lambda: {"created": True})

    payload, code = gate.run_gate(allow_no_blender=False, screenshot_width=320, screenshot_height=180)
    assert code == 1
    assert payload["placeholder_png"] is False
    assert payload["thumbnail_decode_failed"] is True
    assert "thumbnail_decode_failed" in _json_list(payload["blockers"])
    assert _json_mapping(payload["pixel_diff"])["compared"] is False


def test_gate_detects_pixel_diff_exceedance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gate = _load_gate_module()
    state = _stub_handlers(monkeypatch)
    paths = _redirect_outputs(monkeypatch, gate, tmp_path)

    captured = _make_png(16, 16, (10, 20, 30))
    # Make the reference very different (>10/255 mean channel diff).
    reference = _make_png(16, 16, (200, 220, 240))

    paths["reference_dir"].mkdir(parents=True, exist_ok=True)
    paths["reference"].write_bytes(reference)

    _set_screenshot_result(
        state, paths["thumbnail"], width=320, height=180, png_bytes=captured
    )
    _force_no_blender(monkeypatch)

    payload, code = gate.run_gate(allow_no_blender=True, screenshot_width=320, screenshot_height=180)
    assert code == 1
    assert payload["pixel_diff_exceeded"] is True
    assert "pixel_diff_exceeded" in _json_list(payload["blockers"])
    pixel_diff = _json_mapping(payload["pixel_diff"])
    assert pixel_diff["compared"] is True
    mean_abs_diff = pixel_diff.get("mean_abs_diff", 0.0)
    assert _json_number(mean_abs_diff) > gate.PIXEL_DIFF_CHANNEL_THRESHOLD


def test_gate_honours_requested_screenshot_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gate = _load_gate_module()
    state = _stub_handlers(monkeypatch)
    paths = _redirect_outputs(monkeypatch, gate, tmp_path)

    # Handler reports (507, 64) — the historical clamped shape — while the
    # caller asked for (320, 180). The contract check must register that as a
    # mismatch rather than accepting the stale canned pair.
    png = _make_png(32, 32, (10, 20, 30))
    paths["thumbnail"].write_bytes(png)
    state["screenshot_payload"] = {
        "status": "ok",
        "result": {
            "filepath": str(paths["thumbnail"]),
            "width": 507,
            "height": 64,
            "captured": True,
        },
    }
    _force_no_blender(monkeypatch)

    payload, _ = gate.run_gate(allow_no_blender=True, screenshot_width=320, screenshot_height=180)
    assert payload["screenshot_contract_ok"] is False
    assert "screenshot_contract" in _json_list(payload["blockers"])
    assert payload["requested_screenshot_shape"] == [320, 180]


def test_gate_rejects_failed_capture_even_with_stale_png(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gate = _load_gate_module()
    state = _stub_handlers(monkeypatch)
    paths = _redirect_outputs(monkeypatch, gate, tmp_path)

    png = _make_png(32, 32, (10, 20, 30))
    _set_screenshot_result(
        state,
        paths["thumbnail"],
        width=320,
        height=180,
        png_bytes=png,
        captured=False,
    )
    _force_no_blender(monkeypatch)

    payload, _ = gate.run_gate(allow_no_blender=True, screenshot_width=320, screenshot_height=180)
    assert payload["screenshot_contract_ok"] is False
    assert "screenshot_contract" in _json_list(payload["blockers"])


def test_gate_rejects_blender_runtime_without_reference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gate = _load_gate_module()
    state = _stub_handlers(monkeypatch)
    paths = _redirect_outputs(monkeypatch, gate, tmp_path)

    png = _make_png(32, 32, (10, 20, 30))
    _set_screenshot_result(
        state,
        paths["thumbnail"],
        width=320,
        height=180,
        png_bytes=png,
        captured=True,
    )
    monkeypatch.setattr(gate, "_running_in_blender_runtime", lambda: True)
    monkeypatch.setattr(gate, "_ensure_blender_readiness_fixture", lambda: {"created": True})

    payload, code = gate.run_gate(allow_no_blender=False, screenshot_width=320, screenshot_height=180)
    assert code == 1
    assert payload["reference_present"] is False
    assert "missing_visual_reference" in _json_list(payload["blockers"])


def test_perceptual_hash_is_stable_and_decodable() -> None:
    gate = _load_gate_module()
    png_a = _make_png(8, 8, (50, 50, 50))
    png_b = _make_png(8, 8, (50, 50, 50))
    png_c = _make_png(8, 8, (200, 10, 10))

    h_a = gate._compute_perceptual_hash(png_a)
    h_b = gate._compute_perceptual_hash(png_b)
    h_c = gate._compute_perceptual_hash(png_c)
    assert h_a == h_b  # deterministic for identical images
    assert isinstance(h_a, str) and len(h_a) <= 24
    # Distinct content should not be forced to equal, though collision is possible.
    # Just assert the hash function handles non-trivial input.
    assert isinstance(h_c, str)


def test_perceptual_hash_handles_garbage_bytes_gracefully() -> None:
    gate = _load_gate_module()
    h = gate._compute_perceptual_hash(b"not a png at all")
    assert h.startswith("raw:")


def test_main_writes_json_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gate = _load_gate_module()
    state = _stub_handlers(monkeypatch)
    paths = _redirect_outputs(monkeypatch, gate, tmp_path)

    png = _make_png(32, 32, (10, 20, 30))
    _set_screenshot_result(
        state, paths["thumbnail"], width=320, height=180, png_bytes=png
    )
    _force_no_blender(monkeypatch)

    exit_code = gate.main(["--allow-no-blender"])
    assert exit_code == 0

    json_path = paths["output_dir"] / "VISUAL_TESTING_READINESS.json"
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    for key in (
        "ready_for_visual_testing",
        "blockers",
        "blender_runtime_detected",
        "placeholder_png",
        "pixel_diff_exceeded",
        "perceptual_hash",
        "captured_byte_length",
        "requested_screenshot_shape",
    ):
        assert key in data, f"missing key: {key}"
