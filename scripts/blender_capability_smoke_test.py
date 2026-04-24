"""Phase J — live Blender capability smoke test.

Invoke with::

    "/c/Program Files/Blender Foundation/Blender 4.5/blender.exe" \\
        --background --python scripts/blender_capability_smoke_test.py

This drives the Blender capability bridge through the MCP dispatch layer
with a real ``bpy`` available, proving the handlers execute end-to-end.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root))

    from veilbreakers_terrain.src.veilbreakers_mcp.blender_server import dispatch

    results: list[dict] = []

    def run(loc: str, params: dict) -> dict:
        r = dispatch(loc, params)
        results.append({"location": loc, "status": r.get("status"),
                        "error": r.get("error")})
        return r

    import bpy  # available in Blender only

    # Fresh scene with a single default cube we can operate on.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    cube.name = "SmokeCube"

    run("modifier_add", {
        "object_name": "SmokeCube", "modifier_type": "SUBSURF",
        "name": "ss1", "settings": {"levels": 2},
    })
    run("modifier_list", {"object_name": "SmokeCube"})
    run("uv_project", {"object_name": "SmokeCube", "method": "smart"})

    run("gn_create_group", {"name": "smoke_gn"})
    run("gn_add_node", {
        "group_name": "smoke_gn",
        "node_type": "GeometryNodeSubdivideMesh",
        "node_name": "subdiv_a",
    })
    run("gn_link_sockets", {
        "group_name": "smoke_gn",
        "from_node": "Group Input", "from_socket": "Geometry",
        "to_node": "subdiv_a", "to_socket": "Mesh",
    })
    run("gn_assign_object", {
        "object_name": "SmokeCube", "group_name": "smoke_gn",
    })
    run("gn_dump", {"group_name": "smoke_gn"})

    run("render_engine", {"engine": "BLENDER_EEVEE_NEXT"})
    run("collection_create", {"name": "smoke_coll"})
    run("collection_link", {
        "object_name": "SmokeCube", "collection_name": "smoke_coll",
    })
    run("empty_create", {"name": "smoke_empty"})
    run("parent_set", {
        "child_name": "SmokeCube", "parent_name": "smoke_empty",
    })
    run("bmesh_op", {"object_name": "SmokeCube", "op": "triangulate"})

    # Summary
    errors = [r for r in results if r["status"] != "ok"]
    summary = {
        "ran": len(results),
        "ok": len(results) - len(errors),
        "errors": errors,
        "results": results,
    }
    out = repo_root / "output" / "verification" / "BLENDER_SMOKE_TEST.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
