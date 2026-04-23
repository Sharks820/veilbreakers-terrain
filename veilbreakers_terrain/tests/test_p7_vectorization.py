"""Tests for vectorized detect_cliff_edges and QEM heap (REQ-P7-005 / Fix 4.8 ext)."""
from __future__ import annotations

import re
import time
from pathlib import Path

import numpy as np

from veilbreakers_terrain.handlers._terrain_depth import detect_cliff_edges
from veilbreakers_terrain.handlers.lod_pipeline import decimate_preserving_silhouette


HANDLERS_DIR = Path(__file__).parent.parent / "handlers"


def _make_cliff_dem(size: int = 32) -> np.ndarray:
    """Heightmap with a high-slope cliff region in the center."""
    dem = np.zeros((size, size), dtype=np.float64)
    # Flat base then a steep step — creates >60 deg slope at the edge
    dem[size // 2:, :] = 10.0
    return dem


def _make_mesh_grid(n: int = 5) -> tuple[list, list]:
    """Simple n x n grid mesh."""
    verts = [(float(r), float(c), 0.0) for r in range(n) for c in range(n)]
    faces = []
    for r in range(n - 1):
        for c in range(n - 1):
            i = r * n + c
            faces.append((i, i + 1, i + n))
            faces.append((i + 1, i + n + 1, i + n))
    return verts, faces


def test_detect_cliff_edges_uses_scipy():
    """detect_cliff_edges must use binary_erosion + logical_xor + scipy label (Fix 4.8 ext)."""
    src = (HANDLERS_DIR / "_terrain_depth.py").read_text(encoding="utf-8")
    assert re.search(r"binary_erosion\s*\(", src), (
        "_terrain_depth.py must CALL binary_erosion() for cliff edge ring detection (Fix 4.8 ext)"
    )
    assert re.search(r"logical_xor\s*\(|np\.logical_xor\s*\(", src), (
        "_terrain_depth.py must use logical_xor to extract the cliff edge ring (Fix 4.8 ext)"
    )
    assert re.search(r"_ndimage_label|ndimage_label|ndimage\.label", src), (
        "_terrain_depth.py should use scipy.ndimage.label for connected components (Fix 4.8 ext)"
    )


def test_detect_cliff_edges_returns_expected_keys():
    """detect_cliff_edges must return list of dicts with position/rotation/width/height."""
    dem = _make_cliff_dem(32)
    placements = detect_cliff_edges(
        dem, slope_threshold_deg=30.0, min_cluster_size=4, terrain_size=32.0, height_scale=1.0
    )
    assert isinstance(placements, list)
    if placements:
        p = placements[0]
        for key in ("position", "rotation", "width", "height", "cell_count"):
            assert key in p, f"Missing key '{key}' in cliff placement dict"


def test_detect_cliff_edges_speed():
    """detect_cliff_edges on 64x64 must complete in < 1.0 second."""
    dem = _make_cliff_dem(64)
    t0 = time.perf_counter()
    detect_cliff_edges(dem, slope_threshold_deg=30.0, terrain_size=64.0, height_scale=1.0)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"detect_cliff_edges took {elapsed:.3f}s on 64x64 (expected < 1.0s)"


def test_simplify_mesh_heap_present():
    """lod_pipeline.decimate_preserving_silhouette must use heapq for edge priorities."""
    src = (HANDLERS_DIR / "lod_pipeline.py").read_text(encoding="utf-8")
    assert re.search(r"heapq\.heappush|_heapq\.heappush", src), (
        "lod_pipeline.py should use heapq.heappush for QEM edge priority queue (Fix 7.13/7.14)"
    )


def test_simplify_mesh_reduces_vertex_count():
    """decimate_preserving_silhouette with target_ratio=0.5 reduces vertex count."""
    verts, faces = _make_mesh_grid(10)  # 100 verts
    weights = [1.0] * len(verts)
    out_verts, out_faces = decimate_preserving_silhouette(
        verts, faces, target_ratio=0.5, importance_weights=weights
    )
    assert len(out_verts) <= 60, (
        f"decimate should reduce 100 verts to ~50 at ratio=0.5; got {len(out_verts)}"
    )
    assert len(out_faces) > 0, "decimate returned empty face list"
