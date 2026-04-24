"""Tripo asset ingest pipeline (VeilBreakers Phase I).

Given a single downloaded Tripo asset (``.glb`` or a ``.zip`` containing a
GLB/FBX), this script:

1. Resolves the target foliage category from filename / enclosing folder.
2. Launches Blender headless, loads the mesh, decimates it to the
   per-category poly budget, and builds an LOD0/LOD1/LOD2 chain.
3. Exports each LOD as ``assets/foliage/<category>/<asset_id>_LOD<N>.glb``.
4. Appends / updates an entry in ``assets/foliage/catalog.json``.

Runs two ways:

    # Standard use (spawns a Blender subprocess):
    python scripts/ingest_tripo_asset.py path/to/tripo-grass_lush_A.glb \
        --blender "/c/Program Files/Blender Foundation/Blender 4.5/blender.exe"

    # When already running inside Blender (``blender --background --python``):
    #   scripts/ingest_tripo_asset.py --in-blender <json-job-file>

The Blender step is fully headless; no UI. The non-Blender portion (category
detection, catalog I/O, synthetic/testing path) is pure Python and covered by
``tests/test_tripo_ingest_pipeline.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Category catalog (must stay in sync with docs/TRIPO_FOLIAGE_MANIFEST_2026_04_24.md)
# ---------------------------------------------------------------------------
#
# Each entry defines the poly budget for LOD0 and the ratios applied to
# LOD1/LOD2. LOD2 is always allowed to collapse to a billboard when
# ``billboard_at_lod2`` is true.

CATEGORY_BUDGETS: dict[str, dict[str, Any]] = {
    "grass":       {"lod0_tris": 400,  "lod_ratios": (1.0, 0.5, 0.0), "billboard_at_lod2": True,  "scatter_hint": "grass"},
    "pebble":      {"lod0_tris": 900,  "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "rock"},
    "gravel":      {"lod0_tris": 900,  "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "rock"},
    "boulder":     {"lod0_tris": 1500, "lod_ratios": (1.0, 0.4, 0.15), "billboard_at_lod2": False, "scatter_hint": "rock"},
    "moss_drape":  {"lod0_tris": 600,  "lod_ratios": (1.0, 0.5, 0.0), "billboard_at_lod2": True,  "scatter_hint": "moss"},
    "moss":        {"lod0_tris": 600,  "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "moss"},
    "vine":        {"lod0_tris": 1200, "lod_ratios": (1.0, 0.5, 0.0), "billboard_at_lod2": True,  "scatter_hint": "vine"},
    "log":         {"lod0_tris": 1500, "lod_ratios": (1.0, 0.4, 0.15), "billboard_at_lod2": False, "scatter_hint": "prop"},
    "stump":       {"lod0_tris": 1500, "lod_ratios": (1.0, 0.4, 0.15), "billboard_at_lod2": False, "scatter_hint": "prop"},
    "oak":         {"lod0_tris": 8000, "lod_ratios": (1.0, 0.35, 0.0), "billboard_at_lod2": True, "scatter_hint": "tree"},
    "birch":       {"lod0_tris": 6000, "lod_ratios": (1.0, 0.35, 0.0), "billboard_at_lod2": True, "scatter_hint": "tree"},
    "pine":        {"lod0_tris": 6000, "lod_ratios": (1.0, 0.35, 0.0), "billboard_at_lod2": True, "scatter_hint": "tree"},
    "dead_tree":   {"lod0_tris": 4000, "lod_ratios": (1.0, 0.35, 0.0), "billboard_at_lod2": True, "scatter_hint": "tree"},
    "tree":        {"lod0_tris": 6000, "lod_ratios": (1.0, 0.35, 0.0), "billboard_at_lod2": True, "scatter_hint": "tree"},
    "bramble":     {"lod0_tris": 2500, "lod_ratios": (1.0, 0.4, 0.0), "billboard_at_lod2": True,  "scatter_hint": "bush"},
    "fern":        {"lod0_tris": 2500, "lod_ratios": (1.0, 0.4, 0.0), "billboard_at_lod2": True,  "scatter_hint": "bush"},
    "heath":       {"lod0_tris": 2500, "lod_ratios": (1.0, 0.4, 0.0), "billboard_at_lod2": True,  "scatter_hint": "bush"},
    "bush":        {"lod0_tris": 2500, "lod_ratios": (1.0, 0.4, 0.0), "billboard_at_lod2": True,  "scatter_hint": "bush"},
    "reed":        {"lod0_tris": 900,  "lod_ratios": (1.0, 0.5, 0.0), "billboard_at_lod2": True,  "scatter_hint": "water_foliage"},
    "lily":        {"lod0_tris": 900,  "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "water_foliage"},
    "fence":       {"lod0_tris": 1800, "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "structure"},
    "gate":        {"lod0_tris": 1800, "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "structure"},
    "signpost":    {"lod0_tris": 1400, "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "structure"},
    "walkway":     {"lod0_tris": 2000, "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "terrain_tile"},
    "cobble":      {"lod0_tris": 2000, "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "terrain_tile"},
    "path":        {"lod0_tris": 2000, "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "terrain_tile"},
    "flower":      {"lod0_tris": 1000, "lod_ratios": (1.0, 0.5, 0.0), "billboard_at_lod2": True,  "scatter_hint": "accent"},
    "mushroom":    {"lod0_tris": 1000, "lod_ratios": (1.0, 0.5, 0.25), "billboard_at_lod2": False, "scatter_hint": "accent"},
}

# Canonical display categories (directory names under assets/foliage/).
# Scatter hints in CATEGORY_BUDGETS are for species binding; display categories
# are tidier folder labels.
CATEGORY_DISPLAY: dict[str, str] = {
    "grass": "grass",
    "pebble": "rock_small",
    "gravel": "rock_small",
    "boulder": "rock_boulder",
    "moss": "moss",
    "moss_drape": "moss",
    "vine": "vine",
    "log": "log",
    "stump": "log",
    "oak": "tree",
    "birch": "tree",
    "pine": "tree",
    "dead_tree": "tree",
    "tree": "tree",
    "bramble": "bush",
    "fern": "bush",
    "heath": "bush",
    "bush": "bush",
    "reed": "water_foliage",
    "lily": "water_foliage",
    "fence": "structure",
    "gate": "structure",
    "signpost": "structure",
    "walkway": "terrain_tile",
    "cobble": "terrain_tile",
    "path": "terrain_tile",
    "flower": "accent",
    "mushroom": "accent",
}

# Ordered longest-first so multi-token keywords (``moss_drape``, ``dead_tree``)
# win over their prefixes.
_CATEGORY_KEYWORDS = sorted(CATEGORY_BUDGETS.keys(), key=len, reverse=True)


# ---------------------------------------------------------------------------
# Category detection
# ---------------------------------------------------------------------------

def detect_category(path: Path) -> str:
    """Infer the foliage category from a filename and/or parent folder.

    Match order (first hit wins):
      1. filename stem (lowercased, ``-`` ``_`` normalised)
      2. enclosing folder name
      3. ``unknown``
    """
    tokens = [path.stem.lower(), path.parent.name.lower()]
    for token in tokens:
        normalised = token.replace("-", "_")
        for kw in _CATEGORY_KEYWORDS:
            if kw in normalised:
                return kw
    return "unknown"


def resolve_asset_id(source_path: Path, category: str) -> str:
    """Deterministic asset id derived from category + filename + content hash."""
    stem = source_path.stem.lower().replace(" ", "_")
    try:
        digest = hashlib.sha1(source_path.read_bytes()).hexdigest()[:8]
    except OSError:
        # Fall back to stat-based fingerprint (used in synthetic test path
        # where the file may not exist at hash time).
        st = source_path.stat() if source_path.exists() else None
        digest = hashlib.sha1(
            f"{stem}|{st.st_size if st else 0}".encode()
        ).hexdigest()[:8]
    return f"{category}_{stem}_{digest}"


# ---------------------------------------------------------------------------
# Job planning (pure-logic, used by tests)
# ---------------------------------------------------------------------------

def build_job(
    source_path: Path,
    assets_root: Path,
    *,
    category_override: str | None = None,
) -> dict[str, Any]:
    """Build the ingest job spec shared between host and Blender subprocess."""
    category = category_override or detect_category(source_path)
    if category not in CATEGORY_BUDGETS:
        category = "unknown"

    budget = CATEGORY_BUDGETS.get(category) or {
        "lod0_tris": 2000,
        "lod_ratios": (1.0, 0.5, 0.25),
        "billboard_at_lod2": False,
        "scatter_hint": "unknown",
    }
    display = CATEGORY_DISPLAY.get(category, category)
    asset_id = resolve_asset_id(source_path, category)
    out_dir = assets_root / display / asset_id

    return {
        "source": str(source_path.resolve()),
        "asset_id": asset_id,
        "category": category,
        "display_category": display,
        "scatter_hint": budget["scatter_hint"],
        "lod0_tris": int(budget["lod0_tris"]),
        "lod_ratios": list(budget["lod_ratios"]),
        "billboard_at_lod2": bool(budget["billboard_at_lod2"]),
        "out_dir": str(out_dir.resolve()),
        "catalog_path": str((assets_root / "catalog.json").resolve()),
    }


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_if_zip(path: Path, work_dir: Path) -> Path:
    """If *path* is a zip, extract the first .glb/.fbx inside and return it."""
    if path.suffix.lower() != ".zip":
        return path

    work_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        zf.extractall(work_dir)

    for ext in (".glb", ".gltf", ".fbx", ".obj"):
        for candidate in work_dir.rglob(f"*{ext}"):
            return candidate

    raise RuntimeError(f"No .glb/.fbx/.obj/.gltf found inside {path}")


# ---------------------------------------------------------------------------
# Catalog I/O
# ---------------------------------------------------------------------------

def load_catalog(catalog_path: Path) -> dict[str, Any]:
    if not catalog_path.exists():
        return {"version": 1, "assets": {}}
    try:
        with catalog_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "assets": {}}
    data.setdefault("version", 1)
    data.setdefault("assets", {})
    return data


def write_catalog(catalog_path: Path, catalog: dict[str, Any]) -> None:
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = catalog_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, sort_keys=True)
    tmp.replace(catalog_path)


def register_asset(
    catalog_path: Path,
    entry: dict[str, Any],
) -> dict[str, Any]:
    catalog = load_catalog(catalog_path)
    catalog["assets"][entry["asset_id"]] = entry
    write_catalog(catalog_path, catalog)
    return catalog


# ---------------------------------------------------------------------------
# Synthetic (test / headless-without-Blender) mesh path
# ---------------------------------------------------------------------------
#
# Runs entirely in pure Python; no bpy required. The decimation is a simple
# stride-based subsample which is *not* production quality but gives the
# pipeline a deterministic round-trip for CI + tests, and a graceful fallback
# when Blender is unavailable.

def _read_synthetic_mesh(path: Path) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Read a ``.synthmesh.json`` ({"verts": [...], "faces": [...]}) file."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    verts = [tuple(v) for v in data["verts"]]
    faces = [tuple(face) for face in data["faces"]]
    return verts, faces


def _write_synthetic_mesh(
    out_path: Path,
    verts: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({"verts": verts, "faces": faces}, f)


def _stride_decimate(
    verts: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    ratio: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Deterministic face-stride decimation; keeps roughly ``ratio`` faces."""
    ratio = max(0.0, min(1.0, ratio))
    if ratio >= 1.0 or not faces:
        return list(verts), list(faces)
    if ratio <= 0.0:
        return [], []

    stride = max(1, int(round(1.0 / ratio)))
    kept_faces = faces[::stride]
    if not kept_faces:
        kept_faces = [faces[0]]

    # Compact vertex table to only those referenced.
    used: dict[int, int] = {}
    new_verts: list[tuple[float, float, float]] = []
    new_faces: list[tuple[int, int, int]] = []
    for face in kept_faces:
        remapped: list[int] = []
        for idx in face:
            if idx not in used:
                used[idx] = len(new_verts)
                new_verts.append(verts[idx])
            remapped.append(used[idx])
        if len(remapped) >= 3:
            new_faces.append(tuple(remapped[:3]))
    return new_verts, new_faces


def _bbox(verts: list[tuple[float, float, float]]) -> dict[str, list[float]]:
    if not verts:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "size": [0.0, 0.0, 0.0]}
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    lo = [min(xs), min(ys), min(zs)]
    hi = [max(xs), max(ys), max(zs)]
    return {
        "min": lo,
        "max": hi,
        "size": [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]],
    }


def run_synthetic_ingest(job: dict[str, Any]) -> dict[str, Any]:
    """Run the full ingest for a ``.synthmesh.json`` source in pure Python.

    Mirrors the behaviour expected from the Blender path so the catalog
    contract is identical.
    """
    source = Path(job["source"])
    verts, faces = _read_synthetic_mesh(source)

    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    ratios = list(job["lod_ratios"])
    lod_paths: list[dict[str, Any]] = []
    prev_verts, prev_faces = verts, faces

    for level, ratio in enumerate(ratios):
        if ratio <= 0.0 and job.get("billboard_at_lod2"):
            # Billboard: single quad (2 tris) at the source bbox.
            bb = _bbox(prev_verts)
            x0, y0, z0 = bb["min"]
            x1, y1, z1 = bb["max"]
            cy = (y0 + y1) * 0.5
            bill_verts = [
                (x0, cy, z0),
                (x1, cy, z0),
                (x1, cy, z1),
                (x0, cy, z1),
            ]
            bill_faces = [(0, 1, 2), (0, 2, 3)]
            lod_verts, lod_faces = bill_verts, bill_faces
        elif ratio >= 1.0:
            lod_verts, lod_faces = list(verts), list(faces)
        else:
            lod_verts, lod_faces = _stride_decimate(verts, faces, ratio)
            # Monotonic guarantee.
            if len(lod_faces) > len(prev_faces):
                lod_verts, lod_faces = prev_verts, prev_faces

        lod_file = out_dir / f"{job['asset_id']}_LOD{level}.synthmesh.json"
        _write_synthetic_mesh(lod_file, lod_verts, lod_faces)
        lod_paths.append({
            "level": level,
            "path": str(lod_file.resolve()),
            "tri_count": len(lod_faces),
            "vert_count": len(lod_verts),
            "is_billboard": ratio <= 0.0 and job.get("billboard_at_lod2"),
        })
        prev_verts, prev_faces = lod_verts, lod_faces

    source_bbox = _bbox(verts)
    pivot = [
        (source_bbox["min"][0] + source_bbox["max"][0]) * 0.5,
        (source_bbox["min"][1] + source_bbox["max"][1]) * 0.5,
        source_bbox["min"][2],  # base-centre pivot convention.
    ]

    entry: dict[str, Any] = {
        "asset_id": job["asset_id"],
        "category": job["category"],
        "display_category": job["display_category"],
        "scatter_hint": job["scatter_hint"],
        "source": job["source"],
        "bbox": source_bbox,
        "pivot": pivot,
        "lods": lod_paths,
        "lod0_tris": len(faces),
        "lod0_verts": len(verts),
        "ingested_at": time.time(),
        "ingested_by": "synthetic",
    }

    register_asset(Path(job["catalog_path"]), entry)
    return entry


# ---------------------------------------------------------------------------
# Blender subprocess path
# ---------------------------------------------------------------------------

_BLENDER_SCRIPT = '''
"""Runs inside Blender. Reads job JSON, decimates, exports, returns result."""
import json, os, sys, time
try:
    import bpy  # type: ignore
except Exception as e:  # pragma: no cover
    print("BLENDER_ERROR: bpy unavailable -> %s" % e, file=sys.stderr)
    sys.exit(1)

job_path = os.environ.get("TRIPO_JOB_PATH") or sys.argv[-1]
with open(job_path, "r", encoding="utf-8") as f:
    job = json.load(f)

# --- clean scene ---
bpy.ops.wm.read_factory_settings(use_empty=True)

src = job["source"]
ext = os.path.splitext(src)[1].lower()
if ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=src)
elif ext == ".fbx":
    bpy.ops.import_scene.fbx(filepath=src)
elif ext == ".obj":
    bpy.ops.wm.obj_import(filepath=src)
else:
    print("BLENDER_ERROR: unsupported source %s" % ext, file=sys.stderr)
    sys.exit(2)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    print("BLENDER_ERROR: no meshes found in %s" % src, file=sys.stderr)
    sys.exit(3)

# Join into a single active mesh so LOD work is deterministic.
bpy.ops.object.select_all(action="DESELECT")
for m in meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
root = bpy.context.view_layer.objects.active

# Poly budget cap on LOD0 via Decimate modifier.
bpy.context.view_layer.objects.active = root
poly_budget = int(job["lod0_tris"])
current_tris = sum(len(p.vertices) - 2 for p in root.data.polygons)
if current_tris > poly_budget and current_tris > 0:
    ratio = max(0.05, poly_budget / float(current_tris))
    dec = root.modifiers.new(name="LOD0_budget", type="DECIMATE")
    dec.decimate_type = "COLLAPSE"
    dec.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=dec.name)

out_dir = job["out_dir"]
os.makedirs(out_dir, exist_ok=True)

lod_records = []
ratios = list(job["lod_ratios"])
prev_tris = len(root.data.polygons)

for level, ratio in enumerate(ratios):
    lod_path = os.path.join(out_dir, "%s_LOD%d.glb" % (job["asset_id"], level))
    is_billboard = (ratio <= 0.0) and bool(job.get("billboard_at_lod2"))

    # Duplicate root so we do not destroy previous LOD source.
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.object.duplicate()
    work = bpy.context.view_layer.objects.active

    if is_billboard:
        # Replace with AABB cross-quad.
        bbox = [work.matrix_world @ v.co for v in work.data.vertices]
        xs = [v.x for v in bbox]; ys = [v.y for v in bbox]; zs = [v.z for v in bbox]
        x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys); z0, z1 = min(zs), max(zs)
        cy = (y0 + y1) * 0.5
        verts = [(x0, cy, z0), (x1, cy, z0), (x1, cy, z1), (x0, cy, z1)]
        faces = [(0, 1, 2), (0, 2, 3)]
        me = bpy.data.meshes.new(name=work.name + "_billboard")
        me.from_pydata(verts, [], faces)
        me.update()
        old = work.data
        work.data = me
        if old.users == 0:
            bpy.data.meshes.remove(old)
    elif ratio < 1.0:
        dec = work.modifiers.new(name="LOD_dec", type="DECIMATE")
        dec.decimate_type = "COLLAPSE"
        dec.ratio = max(0.02, ratio)
        bpy.ops.object.modifier_apply(modifier=dec.name)

    tri_count = sum(len(p.vertices) - 2 for p in work.data.polygons)
    # Monotonic guard.
    if level > 0 and tri_count > prev_tris and not is_billboard:
        # Too many — decimate further by 0.5 until monotonic or degenerate.
        dec2 = work.modifiers.new(name="LOD_mono", type="DECIMATE")
        dec2.decimate_type = "COLLAPSE"
        dec2.ratio = max(0.05, 0.5 * (prev_tris / max(1, tri_count)))
        bpy.ops.object.modifier_apply(modifier=dec2.name)
        tri_count = sum(len(p.vertices) - 2 for p in work.data.polygons)

    bpy.ops.object.select_all(action="DESELECT")
    work.select_set(True)
    bpy.context.view_layer.objects.active = work
    bpy.ops.export_scene.gltf(
        filepath=lod_path,
        export_format="GLB",
        use_selection=True,
    )
    lod_records.append({
        "level": level,
        "path": lod_path,
        "tri_count": int(tri_count),
        "vert_count": int(len(work.data.vertices)),
        "is_billboard": bool(is_billboard),
    })
    prev_tris = tri_count

    # Remove the working duplicate before next iteration.
    bpy.data.objects.remove(work, do_unlink=True)

# Source bbox & pivot from root mesh.
src_bbox = [root.matrix_world @ v.co for v in root.data.vertices]
xs = [v.x for v in src_bbox]; ys = [v.y for v in src_bbox]; zs = [v.z for v in src_bbox]
bbox_dict = {
    "min": [min(xs), min(ys), min(zs)],
    "max": [max(xs), max(ys), max(zs)],
    "size": [max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs)],
}
pivot = [(bbox_dict["min"][0]+bbox_dict["max"][0])*0.5,
         (bbox_dict["min"][1]+bbox_dict["max"][1])*0.5,
         bbox_dict["min"][2]]

result = {
    "asset_id": job["asset_id"],
    "category": job["category"],
    "display_category": job["display_category"],
    "scatter_hint": job["scatter_hint"],
    "source": src,
    "bbox": bbox_dict,
    "pivot": pivot,
    "lods": lod_records,
    "lod0_tris": int(lod_records[0]["tri_count"]) if lod_records else 0,
    "lod0_verts": int(lod_records[0]["vert_count"]) if lod_records else 0,
    "ingested_at": time.time(),
    "ingested_by": "blender",
}

result_path = os.environ.get("TRIPO_RESULT_PATH") or (job_path + ".result.json")
with open(result_path, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
print("TRIPO_RESULT_WRITTEN: %s" % result_path)
'''


def run_blender_ingest(
    job: dict[str, Any],
    blender_exe: Path,
    *,
    timeout_s: int = 900,
) -> dict[str, Any]:
    """Invoke Blender headless to run the ingest job."""
    work_dir = Path(tempfile.mkdtemp(prefix="tripo_job_"))
    job_path = work_dir / "job.json"
    result_path = work_dir / "job.result.json"
    script_path = work_dir / "tripo_blender_runner.py"

    job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    script_path.write_text(_BLENDER_SCRIPT, encoding="utf-8")

    env = os.environ.copy()
    env["TRIPO_JOB_PATH"] = str(job_path)
    env["TRIPO_RESULT_PATH"] = str(result_path)

    cmd = [
        str(blender_exe),
        "--background",
        "--python-use-system-env",
        "--python", str(script_path),
        "--", str(job_path),
    ]
    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0 or not result_path.exists():
        raise RuntimeError(
            f"Blender ingest failed (rc={proc.returncode}).\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    with result_path.open("r", encoding="utf-8") as f:
        entry = json.load(f)

    register_asset(Path(job["catalog_path"]), entry)
    shutil.rmtree(work_dir, ignore_errors=True)
    return entry


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest(
    source: Path,
    assets_root: Path,
    *,
    blender_exe: Path | None = None,
    category_override: str | None = None,
    force_synthetic: bool = False,
) -> dict[str, Any]:
    """Run the full ingest for a single Tripo download."""
    source = source.expanduser().resolve()
    assets_root = assets_root.expanduser().resolve()

    work_dir = Path(tempfile.mkdtemp(prefix="tripo_extract_"))
    try:
        resolved = extract_if_zip(source, work_dir) if source.suffix.lower() == ".zip" else source
        job = build_job(resolved, assets_root, category_override=category_override)

        if force_synthetic or resolved.suffix.lower() == ".synthmesh.json" or resolved.name.endswith(".synthmesh.json"):
            return run_synthetic_ingest(job)

        if blender_exe is None:
            raise RuntimeError(
                "Blender executable is required for non-synthetic ingest. "
                "Pass --blender or set BLENDER_EXE."
            )
        return run_blender_ingest(job, blender_exe)
    finally:
        if source.suffix.lower() == ".zip":
            shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_blender() -> Path | None:
    env = os.environ.get("BLENDER_EXE")
    if env:
        return Path(env)
    win = Path("C:/Program Files/Blender Foundation/Blender 4.5/blender.exe")
    if win.exists():
        return win
    return None


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest a single Tripo download.")
    p.add_argument("source", type=Path, help="Path to .glb / .gltf / .fbx / .zip / .synthmesh.json")
    p.add_argument(
        "--assets",
        type=Path,
        default=Path("assets/foliage"),
        help="Assets root (default: assets/foliage).",
    )
    p.add_argument(
        "--blender",
        type=Path,
        default=_default_blender(),
        help="Path to blender.exe. Defaults to %BLENDER_EXE% or the standard Windows install.",
    )
    p.add_argument(
        "--category",
        type=str,
        default=None,
        help="Override the auto-detected category (e.g. 'oak', 'fern').",
    )
    p.add_argument(
        "--synthetic",
        action="store_true",
        help="Force the pure-Python synthetic ingest path (used by CI / tests).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    entry = ingest(
        args.source,
        args.assets,
        blender_exe=args.blender,
        category_override=args.category,
        force_synthetic=args.synthetic,
    )
    print(json.dumps({"registered": entry["asset_id"], "lods": len(entry["lods"])}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
