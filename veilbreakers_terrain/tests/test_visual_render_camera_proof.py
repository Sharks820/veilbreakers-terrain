"""Tests for veilbreakers_terrain.handlers.visual_render_camera_proof.

Pure-Python: covers the assertion + manifest helpers without bpy. The
bpy-dependent ``render_camera_proof`` is exercised by the live-Blender
integration drivers (``scripts/render_coastal_camera_proof.py``), not here,
because the test suite must stay headless.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from veilbreakers_terrain.handlers.visual_render_camera_proof import (
    CameraNotFoundError,
    RenderProof,
    RenderProofFailedError,
    RenderProofManifest,
    _slug,
    assert_render_proof,
    build_manifest_path,
    compute_nonblack_ratio,
)


# ---------------------------------------------------------------------------
# _slug
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("VB_CORRECT_COASTAL_FULL_NODE_CAMERA", "vb_correct_coastal_full_node_camera"),
        ("Camera 1 (foo)", "camera_1_foo"),
        ("___camera___", "camera"),
        ("", "camera"),
        ("hello-world.cam", "hello-world_cam"),
    ],
)
def test_slug_canonicalises(name: str, expected: str) -> None:
    assert _slug(name) == expected


# ---------------------------------------------------------------------------
# build_manifest_path
# ---------------------------------------------------------------------------


def test_build_manifest_path(tmp_path: Path) -> None:
    out = build_manifest_path(tmp_path)
    assert out == tmp_path / "RENDER_MANIFEST.json"


# ---------------------------------------------------------------------------
# compute_nonblack_ratio + assert_render_proof
# ---------------------------------------------------------------------------


def _write_solid_png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (32, 32)) -> None:
    """Write a solid-colour PNG via Pillow."""
    pillow = pytest.importorskip("PIL.Image")
    img = pillow.new("RGB", size, color)
    img.save(path, format="PNG")


def test_compute_nonblack_ratio_all_black(tmp_path: Path) -> None:
    p = tmp_path / "black.png"
    _write_solid_png(p, (0, 0, 0))
    assert compute_nonblack_ratio(p) == 0.0


def test_compute_nonblack_ratio_all_grey(tmp_path: Path) -> None:
    p = tmp_path / "grey.png"
    _write_solid_png(p, (128, 128, 128))
    assert compute_nonblack_ratio(p) == 1.0


def test_compute_nonblack_ratio_dim_below_threshold(tmp_path: Path) -> None:
    p = tmp_path / "very_dim.png"
    # threshold inside compute_nonblack_ratio is 8 — pixels at 4 are still "black"
    _write_solid_png(p, (4, 4, 4))
    assert compute_nonblack_ratio(p) == 0.0


def test_assert_render_proof_passes_on_grey(tmp_path: Path) -> None:
    p = tmp_path / "ok.png"
    _write_solid_png(p, (96, 96, 96), size=(256, 256))
    byte_size, ratio = assert_render_proof(p, nonblack_threshold=0.005, min_byte_size=10)
    assert byte_size > 0
    assert ratio >= 0.99


def test_assert_render_proof_fails_on_black(tmp_path: Path) -> None:
    p = tmp_path / "black.png"
    _write_solid_png(p, (0, 0, 0), size=(256, 256))
    with pytest.raises(RenderProofFailedError, match="too dark"):
        assert_render_proof(p, nonblack_threshold=0.005, min_byte_size=10)


def test_assert_render_proof_fails_on_missing(tmp_path: Path) -> None:
    p = tmp_path / "does_not_exist.png"
    with pytest.raises(RenderProofFailedError, match="missing"):
        assert_render_proof(p)


def test_assert_render_proof_fails_on_undersized(tmp_path: Path) -> None:
    p = tmp_path / "tiny.png"
    _write_solid_png(p, (200, 200, 200), size=(2, 2))
    with pytest.raises(RenderProofFailedError, match="undersized"):
        assert_render_proof(p, nonblack_threshold=0.005, min_byte_size=10_000_000)


# ---------------------------------------------------------------------------
# Manifest serialization
# ---------------------------------------------------------------------------


def test_manifest_serializes_to_dict() -> None:
    manifest = RenderProofManifest(
        unit_id="u01_render_harness",
        out_dir="/abs/path",
        engine="BLENDER_EEVEE_NEXT",
        resolution=(1600, 900),
        samples=64,
        frame=None,
        view_transform="Standard",
        look="Medium High Contrast",
    )
    manifest.renders.append(
        RenderProof(
            camera="VB_CORRECT_COASTAL_FULL_NODE_CAMERA",
            path="/abs/path/vb_correct_coastal_full_node_camera.png",
            byte_size=1234,
            nonblack_ratio=0.85,
            ok=True,
        )
    )
    data = manifest.to_dict()
    assert data["unit_id"] == "u01_render_harness"
    assert data["resolution"] == [1600, 900]
    assert data["renders"][0]["camera"] == "VB_CORRECT_COASTAL_FULL_NODE_CAMERA"
    assert data["renders"][0]["ok"] is True
    # Round-trip JSON
    text = json.dumps(data)
    assert "vb_correct_coastal_full_node_camera" in text


# ---------------------------------------------------------------------------
# Sanity: typed errors are subclasses of RuntimeError
# ---------------------------------------------------------------------------


def test_typed_errors_subclass_runtime_error() -> None:
    assert issubclass(CameraNotFoundError, RuntimeError)
    assert issubclass(RenderProofFailedError, RuntimeError)
