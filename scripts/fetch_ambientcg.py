"""fetch_ambientcg.py — Download PBR texture packs from ambientCG.

Uses the ambientCG public API (no key required).
Downloads Albedo, Normal, Roughness, AO, and Displacement maps for a given
material ID and saves them to assets/textures/ambientcg/<material_id>/.

Usage:
    python fetch_ambientcg.py <material_id> [--resolution 2K|4K] [--output-dir <path>]

Examples:
    python fetch_ambientcg.py Ground037
    python fetch_ambientcg.py Rock022 --resolution 4K
    python fetch_ambientcg.py Bark007 --resolution 2K --output-dir /my/textures
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    sys.exit("ERROR: 'requests' is required. Install it with: pip install requests")

API_BASE = "https://ambientcg.com/api/v2/full_json"
DOWNLOAD_BASE = "https://ambientcg.com/get"

# Map of PBR channel keywords to look for in download filenames
PBR_CHANNEL_KEYWORDS = (
    "Color",       # Albedo / Base Colour
    "NormalGL",    # OpenGL normal map
    "Normal",      # Fallback normal (DirectX or generic)
    "Roughness",
    "AmbientOcclusion",
    "Displacement",
    "Metalness",
)

RETRY_WAIT = 5   # seconds between retries on rate-limit (429)
MAX_RETRIES = 3


def _get_json(url: str, params: dict) -> dict:
    """Fetch JSON from the ambientCG API with basic retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
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
            return {}

        resp.raise_for_status()
        return resp.json()

    return {}


def _download_file(url: str, dest: Path) -> bool:
    """Download a single file with progress output. Returns True on success."""
    if dest.exists():
        print(f"  [skip] {dest.name} already exists")
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with requests.get(url, stream=True, timeout=60) as resp:
                if resp.status_code == 429:
                    print(f"  Rate limited (429). Waiting {RETRY_WAIT}s…")
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


def fetch_material(
    material_id: str,
    resolution: str = "2K",
    output_dir: Path | None = None,
) -> int:
    """Fetch all PBR maps for *material_id* at the given resolution.

    Returns the number of files successfully downloaded.
    """
    if output_dir is None:
        # Default: <repo_root>/assets/textures/ambientcg/<material_id>/
        script_dir = Path(__file__).resolve().parent
        repo_root = script_dir.parent
        output_dir = repo_root / "assets" / "textures" / "ambientcg" / material_id
    else:
        output_dir = Path(output_dir) / material_id

    print(f"Material:   {material_id}")
    print(f"Resolution: {resolution}")
    print(f"Output dir: {output_dir}")
    print()

    # Query API
    params = {
        "include": "downloadData",
        "type": "Material",
        "id": material_id,
    }
    print(f"Querying ambientCG API for {material_id!r}…")
    data = _get_json(API_BASE, params)

    if not data:
        print(f"ERROR: No data returned for material {material_id!r}. "
              "Check the ID is correct (e.g. Ground037, Rock022, Bark007).")
        return 0

    found_assets = data.get("foundAssets", [])
    if not found_assets:
        print(f"ERROR: Material {material_id!r} not found in ambientCG.")
        return 0

    asset = found_assets[0]
    asset_id = asset.get("assetId", material_id)
    print(f"Found asset: {asset_id}")

    download_data = asset.get("downloadFolders", {})
    if not download_data:
        # Newer API shape: downloadFileSets
        download_data = asset.get("downloadFileSets", {})

    # Find the best resolution match
    res_key = resolution.upper()
    available_resolutions = list(download_data.keys())
    print(f"Available resolutions: {available_resolutions}")

    chosen_key = None
    for key in available_resolutions:
        if res_key in key.upper():
            chosen_key = key
            break

    if chosen_key is None and available_resolutions:
        chosen_key = available_resolutions[0]
        print(f"Resolution {res_key} not found; using {chosen_key!r} instead.")

    if chosen_key is None:
        print("ERROR: No downloadable resolutions found for this material.")
        return 0

    resolution_data = download_data[chosen_key]
    # May be a dict with 'downloadLink' or a list of file dicts
    downloads: list[dict] = []
    if isinstance(resolution_data, dict):
        # Folder format: {"downloadLink": "...", "fileName": "..."}
        link = resolution_data.get("downloadLink") or resolution_data.get("cdnLink")
        fname = resolution_data.get("fileName", f"{asset_id}_{chosen_key}.zip")
        if link:
            downloads.append({"url": link, "fileName": fname})
    elif isinstance(resolution_data, list):
        downloads = resolution_data
    else:
        print(f"ERROR: Unexpected resolution data format: {type(resolution_data)}")
        return 0

    if not downloads:
        print("ERROR: No download links found.")
        return 0

    # Filter to PBR channels we care about; fall back to downloading everything
    def _is_wanted(fname: str) -> bool:
        fname_upper = fname.upper()
        return any(kw.upper() in fname_upper for kw in PBR_CHANNEL_KEYWORDS)

    wanted = [d for d in downloads if _is_wanted(d.get("fileName", ""))]
    if not wanted:
        wanted = downloads  # download all if we can't filter

    print(f"Files to download: {len(wanted)}")
    print()

    output_dir.mkdir(parents=True, exist_ok=True)
    success_count = 0

    for item in wanted:
        url = item.get("downloadLink") or item.get("cdnLink") or item.get("url", "")
        fname = item.get("fileName", "")
        if not url or not fname:
            continue

        dest = output_dir / fname
        ok = _download_file(url, dest)
        if ok:
            success_count += 1

    print()
    print(f"Done. {success_count}/{len(wanted)} files saved to: {output_dir}")
    return success_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download PBR textures from ambientCG (free, no key required).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("material_id", help="ambientCG material ID, e.g. Ground037")
    parser.add_argument(
        "--resolution",
        default="2K",
        choices=["1K", "2K", "4K", "8K"],
        help="Texture resolution (default: 2K)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Root output directory (default: assets/textures/ambientcg/)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else None
    n = fetch_material(args.material_id, resolution=args.resolution, output_dir=output_dir)
    sys.exit(0 if n > 0 else 1)


if __name__ == "__main__":
    main()
