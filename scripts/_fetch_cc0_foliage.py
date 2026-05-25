"""Fetch CC0 foliage/rock model assets from Poly Haven (public API; all CC0).

  python scripts/_fetch_cc0_foliage.py --list
  python scripts/_fetch_cc0_foliage.py --inspect <asset_id>
  python scripts/_fetch_cc0_foliage.py --get <asset_id> <category> [--fmt gltf] [--res 1k]

Downloads land under assets/foliage_cc0/<category>/<asset_id>/ preserving the
glTF relative-path layout (so Blender can import the .gltf with its textures).
"""
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

API = "https://api.polyhaven.com"
ROOT = Path(__file__).resolve().parents[1] / "assets" / "foliage_cc0"
UA = {"User-Agent": "veilbreakers-terrain/1.0 (CC0 asset fetch)"}

WANT = ("tree", "plant", "nature", "rock", "boulder", "bush", "grass",
        "flower", "moss", "log", "stump", "fern", "wood", "forest", "leaf",
        "branch", "shrub", "trunk", "cliff")


_SAFE_NAME = re.compile(r"\A[A-Za-z0-9._-]+\Z")


def _check_url(url: str) -> None:
    """Refuse non-https URLs. The remote API JSON supplies every fetched
    url, and the default urllib opener also honours file://, ftp:// and
    data: -- a spoofed/compromised endpoint could otherwise read local
    files or reach internal hosts (CWE-918/CWE-20)."""
    p = urlparse(url)
    if p.scheme != "https" or not p.netloc:
        raise ValueError(f"refusing non-https url: {url!r}")


def _get_json(url: str) -> Any:
    _check_url(url)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def list_assets() -> None:
    data = _get_json(f"{API}/assets?type=models")
    rows = []
    for aid, meta in data.items():
        cats = [c.lower() for c in meta.get("categories", [])]
        tags = [t.lower() for t in meta.get("tags", [])]
        hay = " ".join(cats + tags + [aid.lower()])
        if any(w in hay for w in WANT):
            rows.append((aid, meta.get("name", aid), cats, tags))
    for aid, name, cats, tags in sorted(rows):
        print(f"{aid}\t{name}\tcats={cats}\ttags={tags[:8]}")
    print(f"# TOTAL relevant models: {len(rows)} / {len(data)}")


def inspect(aid: str) -> None:
    f = _get_json(f"{API}/files/{aid}")
    print("TOP KEYS:", list(f.keys()))
    print(json.dumps(f, indent=2)[:3500])


def _dl(url: str, dest: Path) -> int:
    _check_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as fh:
        shutil.copyfileobj(r, fh)  # stream in chunks (no full-buffer load)
    return dest.stat().st_size


def _safe_dest(base: Path, relpath: str) -> Path | None:
    """Join relpath under base, rejecting path traversal. The relpath/url
    segments come from the remote API and must not escape the asset dir."""
    dest = (base / relpath).resolve()
    try:
        dest.relative_to(base.resolve())
    except ValueError:
        return None
    return dest


def get_asset(aid: str, category: str, fmt: str = "gltf", res: str = "1k") -> int:
    if not (_SAFE_NAME.match(aid) and _SAFE_NAME.match(category)):
        raise ValueError(f"unsafe asset id/category: {aid!r}/{category!r}")
    f = _get_json(f"{API}/files/{aid}")
    if fmt not in f:
        print(f"  {aid}: fmt {fmt!r} N/A; have {list(f.keys())}")
        return 0
    node = f[fmt]
    if res not in node:
        res = sorted(node.keys())[0]
    block = node[res]   # e.g. {"gltf": {url, md5, size, include:{relpath:{url}}}}
    base = ROOT / category / aid
    total = 0
    for _key, entry in block.items():
        if not isinstance(entry, dict) or "url" not in entry:
            continue
        main = _safe_dest(base, entry["url"].split("/")[-1])
        if main is not None:
            total += _dl(entry["url"], main)
        for relpath, info in entry.get("include", {}).items():
            dest = _safe_dest(base, relpath)
            if dest is None:
                print(f"  !! skip unsafe path {relpath!r} for {aid}")
                continue
            total += _dl(info["url"], dest)
    print(f"  {aid} -> {category}/  ({total // 1024} KB, fmt={fmt} res={res})")
    return total


# Curated CC0 forest/alpine kit (Poly Haven). Real photoscan/geo-node assets.
CURATED = {
    "tree": ["fir_tree_01", "island_tree_01", "island_tree_02", "jacaranda_tree"],
    "sapling": ["fir_sapling", "fir_sapling_medium"],
    "shrub": ["fern_02", "nettle_plant", "calathea_orbifolia_01"],
    "flower": ["dandelion_01", "celandine_01"],
    "ground": ["moss_01", "grass_medium_01", "grass_medium_02"],
    "deadfall": ["dead_tree_trunk", "dead_tree_trunk_02", "dry_branches_medium_01"],
    "rock": ["boulder_01", "coast_rocks_01", "namaqualand_boulder_03"],
}


def curated(res: str = "1k") -> None:
    n = 0
    for cat, ids in CURATED.items():
        for aid in ids:
            try:
                if get_asset(aid, cat, fmt="gltf", res=res):
                    n += 1
            except Exception as e:  # noqa: BLE001
                print(f"  !! {aid} failed: {e!r}")
    print(f"# curated done: {n} assets -> {ROOT}")


# ---- CC0 PBR terrain texture sets (Poly Haven textures) -------------------
TEX_ROOT = ROOT.parent / "terrain_pbr"
TEX_WANT = ("forest", "ground", "rock", "cliff", "grass", "snow", "mud",
            "moss", "dirt", "gravel", "scree", "sand", "mountain", "terrain",
            "leaves", "meadow", "soil")


def list_textures() -> None:
    data = _get_json(f"{API}/assets?type=textures")
    rows = []
    for aid, meta in data.items():
        cats = [c.lower() for c in meta.get("categories", [])]
        tags = [t.lower() for t in meta.get("tags", [])]
        hay = " ".join(cats + tags + [aid.lower()])
        if any(w in hay for w in TEX_WANT):
            rows.append((aid, meta.get("name", aid), cats))
    for aid, name, cats in sorted(rows):
        print(f"{aid}\t{name}\t{cats}")
    print(f"# relevant textures: {len(rows)} / {len(data)}")


def get_texture(aid: str, res: str = "1k") -> int:
    if not _SAFE_NAME.match(aid):
        raise ValueError(f"unsafe texture id: {aid!r}")
    f = _get_json(f"{API}/files/{aid}")
    base = TEX_ROOT / aid
    total = 0

    def walk(n: Any) -> None:
        nonlocal total
        if isinstance(n, dict):
            u = n.get("url")
            if (isinstance(u, str) and (f"_{res}" in u or f"/{res}/" in u)
                    and u.lower().endswith((".jpg", ".png"))):
                total += _dl(u, base / u.split("/")[-1])
                return
            for v in n.values():
                walk(v)

    for mt, node in f.items():
        if mt.lower() in ("blend", "gltf", "fbx", "usd"):
            continue
        walk(node)
    print(f"  tex {aid} -> {base.name}/ ({total // 1024} KB)")
    return total


def curated_tex(ids: list[str], res: str = "1k") -> None:
    for aid in ids:
        try:
            get_texture(aid, res=res)
        except Exception as e:  # noqa: BLE001
            print(f"  !! tex {aid} failed: {e!r}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--list" in a:
        list_assets()
    elif "--inspect" in a:
        inspect(a[a.index("--inspect") + 1])
    elif "--get" in a:
        i = a.index("--get")
        fmt = a[a.index("--fmt") + 1] if "--fmt" in a else "gltf"
        res = a[a.index("--res") + 1] if "--res" in a else "1k"
        get_asset(a[i + 1], a[i + 2], fmt=fmt, res=res)
    elif "--curated" in a:
        curated()
    elif "--list-tex" in a:
        list_textures()
    elif "--gettex" in a:
        i = a.index("--gettex")
        get_texture(a[i + 1])
    elif "--curated-tex" in a:
        i = a.index("--curated-tex")
        curated_tex(a[i + 1:])
    else:
        print(__doc__)
