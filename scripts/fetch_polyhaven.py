"""fetch_polyhaven.py — Download PBR textures from Poly Haven.

Uses the Poly Haven public API (no key required).
Downloads all PBR maps for a given texture slug at the requested resolution
and format, saving to assets/textures/polyhaven/<asset_slug>/.

Usage:
    python fetch_polyhaven.py <asset_slug> [--resolution 2k|4k] [--format jpg|png|exr]

Examples:
    python fetch_polyhaven.py rock_ground_02
    python fetch_polyhaven.py forest_floor_01 --resolution 4k --format exr
    python fetch_polyhaven.py aerial_rocks_02 --resolution 2k --format png
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("ERROR: 'requests' is required. Install it with: pip install requests")

API_BASE = "https://api.polyhaven.com"
CDN_BASE = "https://dl.polyhaven.org"

# PBR map types Poly Haven exposes for textures (subset we care about)
WANTED_MAP_TYPES = (
    "diffuse",       # Albedo / Base Color
    "nor_gl",        # OpenGL Normal map
    "nor_dx",        # DirectX Normal map (fallback)
    "rough",         # Roughness
    "ao",            # Ambient Occlusion
    "disp",          # Displacement / Height
    "metal",         # Metalness
    "arm",           # AO + Roughness + Metalness packed
)

RETRY_WAIT = 5
MAX_RETRIES = 3


def _get_json(url: str, timeout: int = 30) -> dict | list | None:
    """GET JSON from Poly Haven API with retry on 429."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=timeout)
        except requests.RequestException as exc:
            print(f"  Network error (attempt {attempt}/{MAX_RETRIES}): {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_WAIT)
            else:
                raise
            continue

        if resp.status_code == 429:
            print(f"  Rate limited (429). Waiting {RETRY_WAIT}s before retry {attempt}/{MAX_RETRIES}…")
            time.sleep(RETRY_WAIT)
            continue

        if resp.status_code == 404:
            return None

        resp.raise_for_status()
        return resp.json()

    return None


def _download_file(url: str, dest: Path) -> bool:
    """Stream-download a single file with progress. Returns True on success."""
    if dest.exists():
        print(f"  [skip] {dest.name} already exists")
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with requests.get(url, stream=True, timeout=120) as resp:
                if resp.status_code == 429:
                    print(f"  Rate limited. Waiting {RETRY_WAIT}s…")
                    time.sleep(RETRY_WAIT)
                    continue
                if resp.status_code == 404:
                    print(f"  [404] Not found: {url}")
                    return False
                resp.raise_for_status()

                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=65536):
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            print(f"\r  Downloading {dest.name} … {pct}%", end="", flush=True)
                print(f"\r  Downloaded  {dest.name} ({downloaded // 1024} KB)       ")

            tmp.rename(dest)
            return True

        except requests.RequestException as exc:
            print(f"\n  Download error (attempt {attempt}/{MAX_RETRIES}): {exc}")
            if tmp.exists():
                tmp.unlink()
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_WAIT)

    return False


def _resolve_download_url(file_info: dict) -> str | None:
    """Extract a CDN download URL from a Poly Haven files entry."""
    # Poly Haven files API returns: {"url": "...", "size": N, "md5": "..."}
    return file_info.get("url") or file_info.get("download_url")


def fetch_texture(
    slug: str,
    resolution: str = "2k",
    fmt: str = "jpg",
    output_dir: Path | None = None,
) -> int:
    """Fetch all PBR maps for *slug* at the given resolution and format.

    Returns the number of files successfully downloaded.
    """
    res = resolution.lower()
    fmt = fmt.lower()

    if output_dir is None:
        script_dir = Path(__file__).resolve().parent
        repo_root = script_dir.parent
        output_dir = repo_root / "assets" / "textures" / "polyhaven" / slug
    else:
        output_dir = Path(output_dir) / slug

    print(f"Asset slug:  {slug}")
    print(f"Resolution:  {res}")
    print(f"Format:      {fmt}")
    print(f"Output dir:  {output_dir}")
    print()

    # Confirm the asset exists and is a texture
    print(f"Querying Poly Haven API for {slug!r}…")
    asset_info = _get_json(f"{API_BASE}/info/{slug}")
    if asset_info is None:
        print(f"ERROR: Asset {slug!r} not found on Poly Haven.")
        print("Hint: browse https://polyhaven.com/textures to find valid slugs.")
        return 0

    asset_type = asset_info.get("type", 0)
    # Poly Haven type codes: 0=hdri, 1=texture, 2=model
    TYPE_NAMES = {0: "hdri", 1: "texture", 2: "model"}
    print(f"Found: {asset_info.get('name', slug)} (type: {TYPE_NAMES.get(asset_type, asset_type)})")

    # Fetch the files manifest
    files_data = _get_json(f"{API_BASE}/files/{slug}")
    if not files_data or not isinstance(files_data, dict):
        print(f"ERROR: Could not retrieve file manifest for {slug!r}.")
        return 0

    # files_data shape:
    # {
    #   "<map_type>": {
    #     "<resolution>": {
    #       "<format>": {"url": "...", "size": N, "md5": "..."},
    #       ...
    #     }
    #   }
    # }
    available_maps = list(files_data.keys())
    print(f"Available map types: {available_maps}")

    to_download: list[tuple[str, str]] = []  # (url, filename)

    for map_type in WANTED_MAP_TYPES:
        if map_type not in files_data:
            continue

        res_dict = files_data[map_type]
        if not isinstance(res_dict, dict):
            continue

        # Find best resolution match
        chosen_res = None
        if res in res_dict:
            chosen_res = res
        else:
            # Try case-insensitive match or nearest available
            for avail_res in res_dict:
                if avail_res.lower() == res:
                    chosen_res = avail_res
                    break
            if chosen_res is None and res_dict:
                chosen_res = sorted(res_dict.keys())[0]
                print(f"  {map_type}: resolution {res!r} not available, using {chosen_res!r}")

        if chosen_res is None:
            continue

        fmt_dict = res_dict[chosen_res]
        if not isinstance(fmt_dict, dict):
            continue

        # Find best format match
        chosen_fmt = None
        if fmt in fmt_dict:
            chosen_fmt = fmt
        else:
            # Fallback priority: exr > png > jpg
            for fallback in ("exr", "png", "jpg"):
                if fallback in fmt_dict:
                    chosen_fmt = fallback
                    if fallback != fmt:
                        print(f"  {map_type}: format {fmt!r} not available, using {chosen_fmt!r}")
                    break

        if chosen_fmt is None:
            continue

        file_info = fmt_dict[chosen_fmt]
        url = _resolve_download_url(file_info)
        if not url:
            continue

        # Derive filename from URL path
        fname = Path(url).name or f"{slug}_{map_type}_{chosen_res}.{chosen_fmt}"
        to_download.append((url, fname))

    if not to_download:
        print(f"ERROR: No downloadable files found for slug {slug!r} "
              f"at resolution={res}, format={fmt}.")
        return 0

    print(f"\nFiles to download: {len(to_download)}")
    print()

    output_dir.mkdir(parents=True, exist_ok=True)
    success_count = 0

    for url, fname in to_download:
        dest = output_dir / fname
        ok = _download_file(url, dest)
        if ok:
            success_count += 1

    print()
    print(f"Done. {success_count}/{len(to_download)} files saved to: {output_dir}")
    return success_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download PBR textures from Poly Haven (free, no key required).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("asset_slug", help="Poly Haven texture slug, e.g. rock_ground_02")
    parser.add_argument(
        "--resolution",
        default="2k",
        choices=["1k", "2k", "4k", "8k"],
        help="Texture resolution (default: 2k)",
    )
    parser.add_argument(
        "--format",
        default="jpg",
        choices=["jpg", "png", "exr"],
        dest="fmt",
        help="Preferred file format (default: jpg; falls back to png then exr)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Root output directory (default: assets/textures/polyhaven/)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else None
    n = fetch_texture(args.asset_slug, resolution=args.resolution, fmt=args.fmt, output_dir=output_dir)
    sys.exit(0 if n > 0 else 1)


if __name__ == "__main__":
    main()
