"""Foreground opener for the AAA node v1 blend file.

Invoked by Phase L after dual-agent sign-off so the user can immediately
inspect the node in Blender on wake. Optionally loads a .blend path
(passed after ``--``), sets the hero camera as active, and switches the
3D viewport to Rendered shading.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import bpy  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - only runs inside Blender
    sys.stderr.write("open_aaa_node_v1.py must run inside Blender\n")
    sys.exit(1)


def _resolve_blend_path() -> str | None:
    argv = list(sys.argv)
    if "--" in argv:
        tail = argv[argv.index("--") + 1:]
        if tail:
            return tail[0]
    # Fallback: look for any trailing .blend in argv
    for a in reversed(argv):
        if a.endswith(".blend"):
            return a
    return None


def _load_blend(path: str) -> bool:
    try:
        bpy.ops.wm.open_mainfile(filepath=path)
        print(f"[open_aaa_node_v1] loaded {path}")
        return True
    except Exception as exc:
        print(f"[open_aaa_node_v1] FAILED to open {path}: {exc!r}")
        return False


def _set_hero_camera() -> None:
    scene = bpy.context.scene
    hero = bpy.data.objects.get("CAM_hero_wide")
    if hero is not None:
        scene.camera = hero
        print(f"[open_aaa_node_v1] hero camera set: {hero.name}")


def _set_rendered_shading() -> None:
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                try:
                    space.shading.type = "RENDERED"
                except Exception:
                    pass
                try:
                    space.overlay.show_overlays = True
                except Exception:
                    pass
                try:
                    space.region_3d.view_perspective = "CAMERA"
                except Exception:
                    pass


def _frame_all() -> None:
    try:
        for window in bpy.context.window_manager.windows:
            screen = window.screen
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                with bpy.context.temp_override(window=window, area=area, screen=screen):
                    bpy.ops.view3d.view_all(center=False)
    except Exception:
        pass


def main() -> None:
    blend = _resolve_blend_path()
    if blend and Path(blend).exists():
        _load_blend(blend)
    _set_hero_camera()
    _set_rendered_shading()
    _frame_all()
    print("[open_aaa_node_v1] ready for inspection")


if __name__ == "__main__":
    main()
