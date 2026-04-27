"""Visual testing readiness probes for camera, shading, screenshot, and MCP wiring."""

from __future__ import annotations

import importlib
import math
from pathlib import Path
import sys
import types


_OUT_DIR = Path("output/visual_readiness")


def _ensure_allowed_root(monkeypatch) -> Path:
    root = Path("output/visual_readiness").resolve()
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VEILBREAKERS_VISUAL_QA_ROOT", str(root))
    return root


def _install_functional_mathutils(monkeypatch) -> None:
    class _V:
        def __init__(self, xyz):
            self.x = float(xyz[0])
            self.y = float(xyz[1])
            self.z = float(xyz[2])

        def __sub__(self, other):
            return _V((self.x - other.x, self.y - other.y, self.z - other.z))

        @property
        def length(self):
            return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

        def to_track_quat(self, track, up):
            x, y, z = self.x, self.y, self.z
            horiz = math.sqrt(x * x + y * y)
            rx = math.atan2(horiz, -z)
            rz = math.atan2(-x, y)
            euler = types.SimpleNamespace(x=rx, y=0.0, z=rz)
            return types.SimpleNamespace(to_euler=lambda: euler)

    fake = types.ModuleType("mathutils")
    fake.Vector = _V
    monkeypatch.setitem(sys.modules, "mathutils", fake)


def _build_fake_bpy(render_calls, opengl_calls):
    class _CameraStore(dict):
        def new(self, name):
            data = types.SimpleNamespace(
                name=name, lens=0.0, sensor_width=36.0, clip_end=1000.0
            )
            self[name] = data
            return data

    class _ObjectStore(dict):
        def new(self, name, data):
            obj = types.SimpleNamespace(
                name=name, data=data, location=None, rotation_euler=None
            )
            self[name] = obj
            return obj

    shading = types.SimpleNamespace(
        type="SOLID", use_scene_lights=False, use_world_lighting=False
    )
    fake_bpy = types.SimpleNamespace(
        data=types.SimpleNamespace(cameras=_CameraStore(), objects=_ObjectStore()),
        context=types.SimpleNamespace(
            collection=types.SimpleNamespace(
                objects=types.SimpleNamespace(link=lambda obj: None)
            ),
            screen=types.SimpleNamespace(
                areas=[
                    types.SimpleNamespace(
                        type="VIEW_3D",
                        spaces=[types.SimpleNamespace(type="VIEW_3D", shading=shading)],
                    )
                ]
            ),
            scene=types.SimpleNamespace(
                camera=None,
                render=types.SimpleNamespace(
                    filepath="",
                    resolution_x=0,
                    resolution_y=0,
                    image_settings=types.SimpleNamespace(file_format=""),
                ),
            ),
        ),
        ops=types.SimpleNamespace(
            render=types.SimpleNamespace(
                render=lambda write_still: render_calls.append(write_still),
                opengl=lambda write_still: opengl_calls.append(write_still),
            )
        ),
    )
    return fake_bpy, shading


def test_visual_qa_math_contracts_are_deterministic():
    from veilbreakers_terrain.handlers.terrain_visual_qa import (
        auto_frame_terrain,
        compute_rotation_to_look_at,
        fov_to_focal_length,
    )

    assert fov_to_focal_length(45.0) > fov_to_focal_length(90.0)
    assert auto_frame_terrain(0.0) == 10.0
    assert math.isclose(
        auto_frame_terrain(100.0, fov_degrees=45.0, padding=1.2),
        144.8528137423857,
        rel_tol=1e-9,
    )

    rx, ry, rz = compute_rotation_to_look_at((10.0, 0.0, 10.0), (0.0, 0.0, 0.0))
    assert math.isclose(rx, math.pi / 4, rel_tol=1e-6)
    assert ry == 0.0
    assert math.isclose(rz, math.pi / 2, rel_tol=1e-6)


def test_visual_qa_headless_handlers_report_not_applied(monkeypatch):
    _ensure_allowed_root(monkeypatch)
    from blender_addon.handlers import terrain_visual_qa as vqa

    monkeypatch.setattr(vqa, "_HAS_BPY", False)

    camera = vqa.handle_visual_qa_setup_camera(max_extent=128.0)
    assert camera["status"] == "ok"
    assert camera["camera_applied"] is False
    assert camera["has_bpy"] is False

    shading = vqa.handle_visual_qa_set_shading("MATERIAL")
    assert shading["status"] == "ok"
    assert shading["applied"] is False

    screenshot = vqa.handle_visual_qa_capture_screenshot(
        str(_OUT_DIR / "headless.png"), 999, 16
    )
    assert screenshot["status"] == "ok"
    assert screenshot["captured"] is False
    assert screenshot["width"] == 999
    assert screenshot["height"] == 64

    thumb = vqa.handle_visual_qa_capture_screenshot(
        str(_OUT_DIR / "thumb.png"), 999, 16, thumbnail=True
    )
    assert thumb["status"] == "ok"
    assert thumb["width"] == 507
    assert thumb["height"] == 64

    bad = vqa.handle_visual_qa_set_shading("BROKEN")
    assert bad["status"] == "error"


def test_visual_qa_blender_stub_applies_camera_shading_and_screenshot(monkeypatch):
    root = _ensure_allowed_root(monkeypatch)
    _install_functional_mathutils(monkeypatch)
    from blender_addon.handlers import terrain_visual_qa as vqa

    render_calls: list = []
    opengl_calls: list = []
    fake_bpy, shading = _build_fake_bpy(render_calls, opengl_calls)

    monkeypatch.setattr(vqa, "_HAS_BPY", True)
    monkeypatch.setattr(vqa, "bpy", fake_bpy)

    camera = vqa.handle_visual_qa_setup_camera(max_extent=128.0, fov_degrees=50.0)
    assert camera["status"] == "ok"
    assert camera["camera_applied"] is True
    assert fake_bpy.context.scene.camera is fake_bpy.data.objects["Camera"]
    assert fake_bpy.context.scene.camera.data.lens == camera["focal_length"]

    shaded = vqa.handle_visual_qa_set_shading("rendered", use_scene_lights=True)
    assert shaded["status"] == "ok"
    assert shaded["applied"] is True
    assert shading.type == "RENDERED"
    assert shading.use_scene_lights is True

    out = root / "visual.png"
    shot = vqa.handle_visual_qa_capture_screenshot(str(out), width=1920, height=1080)
    assert shot["status"] == "ok"
    assert shot["captured"] is True
    assert fake_bpy.context.scene.render.filepath == str(out.resolve())
    assert fake_bpy.context.scene.render.resolution_x == 1920
    assert fake_bpy.context.scene.render.resolution_y == 1080
    assert fake_bpy.context.scene.render.image_settings.file_format == "PNG"
    assert opengl_calls == [True]
    assert render_calls == []


def test_camera_aims_at_origin_via_quaternion(monkeypatch):
    _ensure_allowed_root(monkeypatch)
    _install_functional_mathutils(monkeypatch)
    from blender_addon.handlers import terrain_visual_qa as vqa

    render_calls: list = []
    opengl_calls: list = []
    fake_bpy, _ = _build_fake_bpy(render_calls, opengl_calls)

    monkeypatch.setattr(vqa, "_HAS_BPY", True)
    monkeypatch.setattr(vqa, "bpy", fake_bpy)

    result = vqa.handle_visual_qa_setup_camera(max_extent=100.0)
    assert result["status"] == "ok"
    assert result["camera_applied"] is True

    cam = fake_bpy.data.objects["Camera"]
    loc = cam.location
    mag = math.sqrt(loc[0] ** 2 + loc[1] ** 2 + loc[2] ** 2)
    assert mag > 0.0

    rot = cam.rotation_euler
    rx = float(rot[0])
    ry = float(rot[1])
    rz = float(rot[2])

    def _rot_xyz(v, rx, ry, rz):
        x, y, z = v
        y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
        x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
        x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
        return (x, y, z)

    forward = _rot_xyz((0.0, 0.0, -1.0), rx, ry, rz)
    dx, dy, dz = -loc[0], -loc[1], -loc[2]
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    desired = (dx / norm, dy / norm, dz / norm)

    dot = forward[0] * desired[0] + forward[1] * desired[1] + forward[2] * desired[2]
    dot = max(-1.0, min(1.0, dot))
    angle = math.acos(dot)
    assert angle < 0.01, (
        f"camera forward deviates by {angle} rad; forward={forward}, desired={desired}"
    )


def test_render_respects_render_max_not_thumbnail_cap(monkeypatch):
    root = _ensure_allowed_root(monkeypatch)
    _install_functional_mathutils(monkeypatch)
    from blender_addon.handlers import terrain_visual_qa as vqa

    render_calls: list = []
    opengl_calls: list = []
    fake_bpy, _ = _build_fake_bpy(render_calls, opengl_calls)

    monkeypatch.setattr(vqa, "_HAS_BPY", True)
    monkeypatch.setattr(vqa, "bpy", fake_bpy)

    out = root / "render1920.png"
    shot = vqa.handle_visual_qa_capture_screenshot(str(out), width=1920, height=1080)
    assert shot["status"] == "ok"
    assert shot["captured"] is True
    assert fake_bpy.context.scene.render.resolution_x == 1920
    assert fake_bpy.context.scene.render.resolution_y == 1080


def test_capture_viewport_uses_ops_render_opengl_by_default(monkeypatch):
    root = _ensure_allowed_root(monkeypatch)
    _install_functional_mathutils(monkeypatch)
    from blender_addon.handlers import terrain_visual_qa as vqa

    render_calls: list = []
    opengl_calls: list = []
    fake_bpy, _ = _build_fake_bpy(render_calls, opengl_calls)

    monkeypatch.setattr(vqa, "_HAS_BPY", True)
    monkeypatch.setattr(vqa, "bpy", fake_bpy)

    out = root / "opengl.png"
    shot = vqa.handle_visual_qa_capture_screenshot(str(out), width=640, height=360)
    assert shot["status"] == "ok"
    assert opengl_calls == [True]
    assert render_calls == []

    hero = vqa.handle_visual_qa_capture_screenshot(
        str(out), width=640, height=360, mode="render"
    )
    assert hero["status"] == "ok"
    assert render_calls == [True]


def test_capture_rejects_filepath_outside_allowed_root(monkeypatch):
    _ensure_allowed_root(monkeypatch)
    _install_functional_mathutils(monkeypatch)
    from blender_addon.handlers import terrain_visual_qa as vqa

    render_calls: list = []
    opengl_calls: list = []
    fake_bpy, _ = _build_fake_bpy(render_calls, opengl_calls)

    monkeypatch.setattr(vqa, "_HAS_BPY", True)
    monkeypatch.setattr(vqa, "bpy", fake_bpy)

    result = vqa.handle_visual_qa_capture_screenshot("../../etc/passwd", 128, 128)
    assert result["status"] == "error"
    assert result["error"] == "filepath_outside_allowed_root"
    assert render_calls == []
    assert opengl_calls == []


def test_camera_clip_end_accommodates_km_terrain(monkeypatch):
    _ensure_allowed_root(monkeypatch)
    _install_functional_mathutils(monkeypatch)
    from blender_addon.handlers import terrain_visual_qa as vqa

    render_calls: list = []
    opengl_calls: list = []
    fake_bpy, _ = _build_fake_bpy(render_calls, opengl_calls)

    monkeypatch.setattr(vqa, "_HAS_BPY", True)
    monkeypatch.setattr(vqa, "bpy", fake_bpy)

    result = vqa.handle_visual_qa_setup_camera(max_extent=1000.0)
    assert result["status"] == "ok"
    cam = fake_bpy.data.objects["Camera"]
    assert cam.data.clip_end >= 4000.0
    assert result["clip_end"] is not None
    assert result["clip_end"] >= 4000.0


def test_visual_qa_module_import_is_stable_without_reloading_bpy():
    module = importlib.import_module("veilbreakers_terrain.handlers.terrain_visual_qa")
    assert hasattr(module, "handle_visual_qa_setup_camera")
    assert hasattr(module, "handle_visual_qa_set_shading")
    assert hasattr(module, "handle_visual_qa_capture_screenshot")
