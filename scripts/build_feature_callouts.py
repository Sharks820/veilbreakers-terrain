"""Post-hoc FEATURE_CALLOUTS.png builder.

Uses Blender's VSE to overlay text annotations on a hero render. Separate from
the build scripts so it can be rerun/iterated quickly on existing renders.

Invoke::

    blender --background --python scripts/build_feature_callouts.py -- \
        --node v1   (or v2)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _args_after_dashdash() -> list[str]:
    if "--" in sys.argv:
        i = sys.argv.index("--")
        return sys.argv[i + 1:]
    return []


def run(node: str) -> int:
    import bpy

    out_dir_map = {
        "v1": REPO_ROOT / "output" / "aaa_node_v1",
        "v2": REPO_ROOT / "output" / "aaa_node_v2",
    }
    if node not in out_dir_map:
        print(f"[callouts] unknown node {node!r}")
        return 2
    out_dir = out_dir_map[node]
    hero = out_dir / "render_hero_wide.png"
    if not hero.exists():
        # Try Signature as fallback
        cands = sorted(out_dir.glob("render_*.png"))
        hero = cands[0] if cands else None
    if hero is None:
        print(f"[callouts] no hero render in {out_dir}")
        return 3
    out_path = out_dir / "FEATURE_CALLOUTS.png"

    # Build annotation scene
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ann_scene = bpy.context.scene
    ann_scene.name = "VB_Callouts"
    ann_scene.render.resolution_x = 1920
    ann_scene.render.resolution_y = 1080
    ann_scene.render.image_settings.file_format = "PNG"
    ann_scene.render.filepath = str(out_path)
    ann_scene.frame_start = 1
    ann_scene.frame_end = 1
    if not ann_scene.sequence_editor:
        ann_scene.sequence_editor_create()

    bg = ann_scene.sequence_editor.sequences.new_image(
        name="bg", filepath=str(hero), channel=1, frame_start=1
    )
    bg.frame_final_duration = 1

    if node == "v1":
        callouts = [
            ("Stratigraphy banding  (Phase G)", (0.04, 0.82)),
            ("Waterfall sheet + foam  (Phase B)", (0.16, 0.60)),
            ("Traversable cave  (Phase F)", (0.62, 0.48)),
            ("Lake transmission + caustics", (0.42, 0.22)),
            ("Foliage Poisson scatter  (Phase H)", (0.75, 0.35)),
            ("Cliff silhouette breakup  (Phase A)", (0.22, 0.36)),
        ]
    else:
        callouts = [
            ("Oak-dominant hills  (Phase H altitude gate)", (0.04, 0.80)),
            ("Ecotone species handoff  (Phase J)", (0.40, 0.55)),
            ("Birch transition band  (120m)", (0.25, 0.48)),
            ("Reed + lily marsh  (moisture gate)", (0.55, 0.22)),
            ("Marsh ponds  (0.7 transmission)", (0.73, 0.30)),
            ("Seam-lock to Node v1  (Phase A)", (0.05, 0.12)),
        ]

    ch = 2
    for text, (u, v) in callouts:
        try:
            ts = ann_scene.sequence_editor.sequences.new_effect(
                name=f"t_{ch}", type="TEXT", channel=ch,
                frame_start=1, frame_end=2,
            )
        except TypeError:
            ts = ann_scene.sequence_editor.sequences.new_effect(
                name=f"t_{ch}", type="TEXT", channel=ch, frame_start=1
            )
            try:
                ts.frame_final_duration = 1
            except Exception:
                pass
        ts.text = text
        try:
            ts.font_size = 42
        except Exception:
            pass
        try:
            ts.location = (u, v)
        except Exception:
            pass
        for attr, val in (("align_x", "LEFT"), ("align_y", "CENTER")):
            if hasattr(ts, attr):
                try:
                    setattr(ts, attr, val)
                except Exception:
                    pass
        try:
            ts.use_shadow = True
            ts.shadow_color = (0.0, 0.0, 0.0, 0.85)
        except Exception:
            pass
        try:
            ts.color = (1.0, 0.85, 0.4, 1.0)
        except Exception:
            pass
        ch += 1

    try:
        bpy.ops.render.render(write_still=True)
        print(f"[callouts] {node} -> {out_path}")
        return 0
    except Exception as exc:
        print(f"[callouts] render failed: {exc!r}")
        return 4


if __name__ == "__main__":
    args = _args_after_dashdash()
    node = "v1"
    for i, a in enumerate(args):
        if a == "--node" and i + 1 < len(args):
            node = args[i + 1]
    try:
        rc = run(node)
    except Exception as exc:
        print(f"[callouts] fatal: {exc!r}")
        rc = 5
    sys.stdout.flush()
