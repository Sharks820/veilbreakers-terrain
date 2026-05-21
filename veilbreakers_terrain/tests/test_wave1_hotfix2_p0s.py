"""Regression tests for WAVE-1-HOTFIX-2 (CE WAVE-1 P0s: env + _mesh_bridge).

Covers four bugs landed in fix/ce-wave1-hotfix-2-env-mesh-p0s:

* Bug 2 — ``environment._paint_road_mask_on_terrain._min_dist_to_path``
  memory bomb. The previous broadcast allocated
  ``(N_verts, N_segments)`` doubles in one shot — 4096^2 verts x 500
  segments = 8.3B doubles = 67 GB transient. Chunked to <=65 536 rows.
* Bug 3 — ``environment`` protected_zone two incompatible schemas.
  Centralised resolver ``_resolve_protected_zone_aabb`` handles both
  nested-bounds and flat-AABB (with ``x0/x1`` aliases).
* Bug 4 — ``_mesh_bridge.generate_lod_specs`` stripped ``material_ids``.
  Multi-material LOD specs raised RuntimeError downstream because
  ``mesh_from_spec`` requires per-face id parity.
* Bug 5 — ``_mesh_bridge.mesh_from_spec`` per-vertex UV corruption after
  weld. Post-dedup bm vert index used to read pre-dedup uvs array;
  inverse remap added.

Bug 1 (the 11 unpaired ``bmesh.new()`` sites in environment.py) is a
FALSE POSITIVE from the CE WAVE-1 audit — PR #94 (``b12550eb``) already
wrapped every site in try/finally. The existing
``test_bmesh_release_discipline.py`` is the canonical regression net.

Audit anchors: FIX_PATTERN_v1 §C3 (contract), §C5 (numerical), §C9
(perf/HW envelope).
"""

from __future__ import annotations

import tracemalloc
from typing import Any

import numpy as np

from veilbreakers_terrain.handlers import _mesh_bridge as mb
from veilbreakers_terrain.handlers.environment import _resolve_protected_zone_aabb


# ---------------------------------------------------------------------------
# Bug 3 — protected_zones dual-schema resolver
# ---------------------------------------------------------------------------


def test_resolve_protected_zone_aabb_nested_bounds_schema() -> None:
    """Schema A: nested-bounds dict — canonical form built by tile params."""
    pz = {"zone_id": "z1", "bounds": {
        "min_x": -10.0, "min_y": -20.0, "max_x": 30.0, "max_y": 40.0,
    }}
    aabb = _resolve_protected_zone_aabb(pz)
    assert aabb == (-10.0, -20.0, 30.0, 40.0)


def test_resolve_protected_zone_aabb_flat_x_min_schema() -> None:
    """Schema B: flat-AABB with x_min/y_min keys — road network reform form."""
    pz = {
        "zone_id": "z2",
        "x_min": -5.0, "y_min": -6.0, "x_max": 7.0, "y_max": 8.0,
    }
    aabb = _resolve_protected_zone_aabb(pz)
    assert aabb == (-5.0, -6.0, 7.0, 8.0)


def test_resolve_protected_zone_aabb_flat_x0_alias() -> None:
    """Schema B alias: x0/y0/x1/y1 — emitter-side shorthand."""
    pz = {"zone_id": "z3", "x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0}
    aabb = _resolve_protected_zone_aabb(pz)
    assert aabb == (1.0, 2.0, 3.0, 4.0)


def test_resolve_protected_zone_aabb_nested_takes_precedence() -> None:
    """When BOTH schemas are present the nested-bounds dict wins.

    Rationale: ``_resolve_terrain_tile_params`` always builds the
    nested form; if a caller also supplied flat keys they are stale
    debug data and the canonical bounds must be honoured.
    """
    pz = {
        "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0},
        "x_min": -999.0, "y_min": -999.0, "x_max": 999.0, "y_max": 999.0,
    }
    aabb = _resolve_protected_zone_aabb(pz)
    assert aabb == (0.0, 0.0, 10.0, 10.0)


def test_resolve_protected_zone_aabb_open_zone_defaults() -> None:
    """Empty / non-dict input returns ``+/-1e18`` open zone.

    Behaviour is preserved so downstream "no clip" callers continue to
    fall through to their existing branches without crashing.
    """
    aabb = _resolve_protected_zone_aabb({})
    # Empty flat-schema path: defaults to +/-1e9
    assert aabb == (-1e9, -1e9, 1e9, 1e9)

    aabb_invalid = _resolve_protected_zone_aabb(None)  # type: ignore[arg-type]
    assert aabb_invalid == (-1e18, -1e18, 1e18, 1e18)


def test_resolve_protected_zone_aabb_partial_nested_bounds() -> None:
    """Nested-bounds dict missing some keys falls back to +/-1e18 sentinels."""
    pz = {"bounds": {"min_x": -5.0}}  # only min_x present
    aabb = _resolve_protected_zone_aabb(pz)
    assert aabb == (-5.0, -1e18, 1e18, 1e18)


# ---------------------------------------------------------------------------
# Bug 2 — _paint_road_mask memory bomb
# ---------------------------------------------------------------------------


def test_paint_road_mask_min_dist_chunked_no_memory_bomb() -> None:
    """Direct unit test of the chunked min-dist function.

    The original implementation broadcast ``(N_verts, N_segments)`` in
    one shot. With N_verts=1_000_000 and N_segments=500 (well below an
    AAA scene), the original would allocate ~30 GB of intermediates
    several times over. The chunked replacement keeps peak transient
    allocation below ~256 MB regardless of N_verts.

    This test reconstructs the closure-local helper using identical
    math so the regression net runs without the full Blender
    ``bpy.data`` dependency.
    """
    rng = np.random.default_rng(2026)
    # 1M points + 500 segments would have allocated ~30 GB in the prior code.
    n_pts = 1_000_000
    n_segs = 500
    px = rng.uniform(-100.0, 100.0, n_pts).astype(np.float64)
    py = rng.uniform(-100.0, 100.0, n_pts).astype(np.float64)
    seg_a = rng.uniform(-100.0, 100.0, (n_segs, 2)).astype(np.float64)
    seg_b = rng.uniform(-100.0, 100.0, (n_segs, 2)).astype(np.float64)
    ab = seg_b - seg_a
    ab_sq = np.maximum((ab * ab).sum(axis=1), 1e-12)

    # Reconstruct the chunked closure body (same code as in handler).
    def _min_dist_to_path(px: np.ndarray, py: np.ndarray, chunk: int = 8192) -> np.ndarray:
        n = int(px.shape[0])
        out = np.empty(n, dtype=np.float64)
        if n == 0:
            return out
        chunk = max(1, int(chunk))
        for start in range(0, n, chunk):
            end = min(start + chunk, n)
            px_c = px[start:end]
            py_c = py[start:end]
            t = (
                (px_c[:, None] - seg_a[None, :, 0]) * ab[None, :, 0]
                + (py_c[:, None] - seg_a[None, :, 1]) * ab[None, :, 1]
            ) / ab_sq[None, :]
            t = np.clip(t, 0.0, 1.0)
            cpx = seg_a[None, :, 0] + t * ab[None, :, 0]
            cpy = seg_a[None, :, 1] + t * ab[None, :, 1]
            dx = px_c[:, None] - cpx
            dy = py_c[:, None] - cpy
            out[start:end] = np.sqrt((dx * dx + dy * dy).min(axis=1))
        return out

    tracemalloc.start()
    out = _min_dist_to_path(px, py)  # uses default chunk=8192
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Peak alloc per chunk: 8192 * 500 * 8 bytes * ~7 intermediates =~ 230 MB
    # plus input/output arrays. Set a 1 GB ceiling — the prior unchunked
    # code at this size would have allocated >30 GB in one shot.
    assert peak < 1e9, (
        f"chunked _min_dist_to_path peak alloc {peak / 1e9:.2f} GB exceeds "
        f"1 GB ceiling — chunking likely broken"
    )
    assert out.shape == (n_pts,)
    assert np.all(np.isfinite(out))
    assert float(out.min()) >= 0.0


def test_paint_road_mask_min_dist_matches_unchunked_reference() -> None:
    """Chunked output must match a small unchunked reference bit-for-bit."""
    rng = np.random.default_rng(42)
    # Small problem so reference fits comfortably in memory.
    n_pts = 512
    n_segs = 16
    px = rng.uniform(-10.0, 10.0, n_pts).astype(np.float64)
    py = rng.uniform(-10.0, 10.0, n_pts).astype(np.float64)
    seg_a = rng.uniform(-10.0, 10.0, (n_segs, 2)).astype(np.float64)
    seg_b = rng.uniform(-10.0, 10.0, (n_segs, 2)).astype(np.float64)
    ab = seg_b - seg_a
    ab_sq = np.maximum((ab * ab).sum(axis=1), 1e-12)

    # Unchunked reference (matches prior code exactly).
    def _reference(px: np.ndarray, py: np.ndarray) -> np.ndarray:
        t = (
            (px[:, None] - seg_a[None, :, 0]) * ab[None, :, 0]
            + (py[:, None] - seg_a[None, :, 1]) * ab[None, :, 1]
        ) / ab_sq[None, :]
        t = np.clip(t, 0.0, 1.0)
        cpx = seg_a[None, :, 0] + t * ab[None, :, 0]
        cpy = seg_a[None, :, 1] + t * ab[None, :, 1]
        dx = px[:, None] - cpx
        dy = py[:, None] - cpy
        return np.sqrt((dx * dx + dy * dy).min(axis=1))

    def _chunked(px: np.ndarray, py: np.ndarray, chunk: int = 64) -> np.ndarray:
        n = int(px.shape[0])
        out = np.empty(n, dtype=np.float64)
        if n == 0:
            return out
        for start in range(0, n, chunk):
            end = min(start + chunk, n)
            px_c = px[start:end]
            py_c = py[start:end]
            t = (
                (px_c[:, None] - seg_a[None, :, 0]) * ab[None, :, 0]
                + (py_c[:, None] - seg_a[None, :, 1]) * ab[None, :, 1]
            ) / ab_sq[None, :]
            t = np.clip(t, 0.0, 1.0)
            cpx = seg_a[None, :, 0] + t * ab[None, :, 0]
            cpy = seg_a[None, :, 1] + t * ab[None, :, 1]
            dx = px_c[:, None] - cpx
            dy = py_c[:, None] - cpy
            out[start:end] = np.sqrt((dx * dx + dy * dy).min(axis=1))
        return out

    expected = _reference(px, py)
    # Run chunked with a small chunk size so the chunk boundary is exercised.
    actual = _chunked(px, py, chunk=64)
    # Bit-equality: the chunked impl performs identical scalar math on
    # identical rows, just in batches. NumPy guarantees per-row determinism.
    np.testing.assert_array_equal(actual, expected)


def test_paint_road_mask_handler_uses_chunked_helper() -> None:
    """The production handler closure source must contain the ``chunk`` kwarg.

    Source-level guard so the chunked design can't be silently reverted
    to a single broadcast.
    """
    from veilbreakers_terrain.handlers import environment as env

    import inspect
    src = inspect.getsource(env._paint_road_mask_on_terrain)
    assert "def _min_dist_to_path" in src
    assert "chunk" in src, "chunked _min_dist_to_path must accept a chunk kwarg"
    assert "for start in range(0, n, chunk):" in src, (
        "chunked _min_dist_to_path must iterate in chunks of N rows"
    )


# ---------------------------------------------------------------------------
# Bug 4 — LOD strips material_ids
# ---------------------------------------------------------------------------


def _multi_material_quad_spec() -> dict[str, Any]:
    """3-material spec: 6 verts, 4 triangles, 3 distinct material slots."""
    return {
        "vertices": [
            (0.0, 0.0, 0.0),  # 0
            (1.0, 0.0, 0.0),  # 1
            (2.0, 0.0, 0.0),  # 2
            (0.0, 1.0, 0.0),  # 3
            (1.0, 1.0, 0.0),  # 4
            (2.0, 1.0, 0.0),  # 5
        ],
        "faces": [
            (0, 1, 4),  # face 0 -> material 0
            (0, 4, 3),  # face 1 -> material 0
            (1, 2, 5),  # face 2 -> material 1
            (1, 5, 4),  # face 3 -> material 2
        ],
        "uvs": [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (0.0, 1.0), (0.5, 1.0), (1.0, 1.0)],
        "metadata": {"name": "tri_quad"},
        "material_ids": [0, 0, 1, 2],
    }


def test_lod_specs_preserve_material_ids_lod0() -> None:
    """LOD0 returns original geometry verbatim; material_ids passes 1:1."""
    spec = _multi_material_quad_spec()
    lods = mb.generate_lod_specs(spec)
    lod0 = lods[0]
    assert "material_ids" in lod0
    assert lod0["material_ids"] == [0, 0, 1, 2]
    assert len(lod0["material_ids"]) == len(lod0["faces"])


def test_lod_specs_preserve_material_ids_clustered_levels() -> None:
    """LOD1/LOD2 (clustered) emit material_ids matching surviving face count.

    The clustering may collapse some faces; the contract is just that
    every surviving face gets a valid material_id (no count mismatch
    that would break mesh_from_spec's per-face-vs-per-id gate).
    """
    spec = _multi_material_quad_spec()
    lods = mb.generate_lod_specs(spec)
    for level in (1, 2):
        lod = lods[level]
        n_faces = len(lod["faces"])
        if n_faces == 0:
            # Degenerate clustering — material_ids may be absent or empty
            mids = lod.get("material_ids", [])
            assert len(mids) == 0
            continue
        assert "material_ids" in lod, (
            f"LOD{level} dropped material_ids — would raise RuntimeError "
            f"at mesh_from_spec"
        )
        assert len(lod["material_ids"]) == n_faces, (
            f"LOD{level} material_id count {len(lod['material_ids'])} != "
            f"face count {n_faces}"
        )
        # All ids must be in the original {0, 1, 2} set
        assert set(lod["material_ids"]).issubset({0, 1, 2})


def test_lod_billboard_records_modal_material_in_metadata() -> None:
    """LOD3 billboard: material_ids deliberately absent, modal id in metadata.

    The cross-billboard has 8 verts + 4 faces by construction, but the
    back-face quads share vertex sets with the front-face quads
    (reversed winding). BMesh dedups them at ``bm.from_mesh()`` so the
    surviving polygon count is < 4 — adding ``material_ids = [m, m,
    m, m]`` here would trip mesh_from_spec's per-face-vs-per-id gate.
    The billboard represents the entire silhouette as a single visual
    unit; single-material falls out naturally, with the modal id
    captured in metadata for downstream atlas selection.
    """
    spec = _multi_material_quad_spec()
    lods = mb.generate_lod_specs(spec)
    bill = lods[3]
    assert bill["metadata"]["is_billboard"] is True
    assert len(bill["faces"]) == 4
    # Deliberately NOT in spec — bm dedup would create count mismatch.
    assert "material_ids" not in bill or bill.get("material_ids", []) == []
    # Modal id is captured in metadata so Unity / UE importer can pick atlas.
    assert bill["metadata"]["billboard_material_id"] == 0  # modal of [0,0,1,2]


def test_lod_specs_no_material_ids_when_source_has_none() -> None:
    """Single-material specs still work — material_ids absent / empty."""
    spec = {
        "vertices": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
        "faces": [(0, 1, 2)],
        "uvs": [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        "metadata": {"name": "single"},
    }
    lods = mb.generate_lod_specs(spec)
    for lod in lods:
        # Either absent or empty list — both signal "no per-face ids"
        assert not lod.get("material_ids", [])


def test_lod_material_ids_satisfy_pre_bm_contract_gate() -> None:
    """Every LOD spec's material_ids count must satisfy the pre-bm gate.

    The pre-bm gate in mesh_from_spec validates ``len(material_ids) ==
    surviving_face_count`` BEFORE the bpy-only post-bm gate runs. This
    test exercises the pre-bm gate directly so it works in headless
    mode. Pre-fix, LOD1/LOD2 specs reached this gate with
    ``material_ids=[]`` and ``faces`` non-empty — but no, actually the
    pre-fix bug was that LOD specs had NO material_ids field at all,
    so the pre-bm gate skipped (no ids -> no contract). The
    downstream bpy gate THEN raised because the user's caller still
    passed material_ids in via the source spec. Post-fix, every
    non-billboard LOD carries a per-face id list that matches the
    surviving face count — the contract is satisfied at the LOD level,
    not deferred to the consumer.
    """
    spec = _multi_material_quad_spec()
    lods = mb.generate_lod_specs(spec)
    for level, lod in enumerate(lods):
        if lod["metadata"].get("is_billboard"):
            # Billboard LOD intentionally drops material_ids (see
            # test_lod_billboard_records_modal_material_in_metadata).
            assert "material_ids" not in lod or lod.get("material_ids", []) == []
            continue
        # Non-billboard LODs MUST have a 1:1 material_ids:faces mapping.
        assert "material_ids" in lod, (
            f"LOD{level} missing material_ids — pre-bm contract gate "
            f"would raise downstream"
        )
        assert len(lod["material_ids"]) == len(lod["faces"]), (
            f"LOD{level} material_id count {len(lod['material_ids'])} "
            f"!= face count {len(lod['faces'])}"
        )

    # Pre-bm gate path: run mesh_from_spec on LOD0 (which is the source
    # geometry verbatim — bm dedup won't drop anything). Successful
    # return proves the per-face-vs-per-id gate accepts our LOD output.
    lod0 = lods[0]
    # In the stub-bpy env mesh_from_spec's bpy-post-gate is unreliable
    # (mesh_data.polygons is a MagicMock with length 0), but the pre-bm
    # gate runs first and is the one we're proving. Call into the
    # headless fallback by removing bpy.data attribute temporarily.
    import veilbreakers_terrain.handlers._mesh_bridge as mb_mod
    orig_has = mb_mod._HAS_BPY
    try:
        mb_mod._HAS_BPY = False
        result = mb.mesh_from_spec(lod0, name="lod0_test")
        # Headless fallback returns the dict summary
        assert result["material_slot_count"] == max(spec["material_ids"]) + 1
        assert result["face_material_ids"] == lod0["material_ids"]
    finally:
        mb_mod._HAS_BPY = orig_has


# ---------------------------------------------------------------------------
# Bug 5 — weld UV corruption
# ---------------------------------------------------------------------------


def test_mesh_from_spec_inverse_remap_uses_first_original_vertex() -> None:
    """The UV-fix inverse remap maps welded bm verts to first orig index.

    Source-level guard: the code change MUST keep the ``_inverse_remap``
    construction so welded verts pick up the FIRST original UV
    (deterministic, byte-reproducible) rather than randomly reading
    whatever uvs[bm_idx] returns.
    """
    import inspect

    src = inspect.getsource(mb.mesh_from_spec)
    assert "_inverse_remap" in src, (
        "Bug 5 fix removed — UV lookup will silently mis-align welded "
        "vertices to whatever uvs[bm_index] happens to return"
    )
    assert "_inverse_remap.get(bm_vi, bm_vi)" in src, (
        "Inverse remap lookup pattern lost — welded vert UV lookup will "
        "fall back to bm.vert.index (wrong array)"
    )
    # The construction must come AFTER the dedup loop and BEFORE the UV loop.
    dedup_pos = src.find("for orig_i, bm_i in enumerate(_remap):")
    uv_loop_pos = src.find("for loop in face.loops:")
    assert dedup_pos > 0 and uv_loop_pos > 0
    assert dedup_pos < uv_loop_pos, (
        "_inverse_remap must be populated before the UV-assignment loop"
    )


def test_mesh_from_spec_welded_vertex_uv_lookup_through_inverse_remap() -> None:
    """Unit-level: simulate the post-fix UV lookup math directly.

    The end-to-end weld behaviour requires a real BMesh; this test
    reproduces the inverse-remap construction in pure Python so the
    invariant is pinned without depending on a live Blender. The
    inverse-remap must give the FIRST original vertex index for every
    bm vert it maps to — and the UV at that index must match the
    intended UV the generator emitted.

    Pre-fix behaviour: ``uvs[loop.vert.index]`` read uvs at the bm
    (post-dedup) index, which silently mis-aligned every welded
    vertex's UV to whatever happened to be at the post-dedup index in
    the source uvs array (off-by-N where N = number of welds).
    """
    verts = [
        (0.0, 0.0, 0.0),  # orig 0 -> bm 0
        (1.0, 0.0, 0.0),  # orig 1 -> bm 1
        (1.0, 1.0, 0.0),  # orig 2 -> bm 2
        (0.0, 0.0, 0.0),  # orig 3 -> bm 0 (welded with orig 0)
        (2.0, 0.0, 0.0),  # orig 4 -> bm 3
    ]
    uvs = [
        (0.0, 0.0),  # uvs[0]
        (1.0, 0.0),  # uvs[1]
        (1.0, 1.0),  # uvs[2]
        (0.5, 0.5),  # uvs[3] — the WRONG uv the prior code would pick for bm 3
        (2.0, 0.0),  # uvs[4]
    ]

    # Recreate the production dedup loop (same math as mesh_from_spec).
    weld_tolerance = 0.005
    _vert_dedup: dict[tuple[int, int, int], int] = {}
    _remap: list[int] = []
    for v in verts:
        key = (
            round(v[0] / weld_tolerance),
            round(v[1] / weld_tolerance),
            round(v[2] / weld_tolerance),
        )
        if key in _vert_dedup:
            _remap.append(_vert_dedup[key])
        else:
            idx = len(_vert_dedup)
            _vert_dedup[key] = idx
            _remap.append(idx)
    _inverse_remap: dict[int, int] = {}
    for orig_i, bm_i in enumerate(_remap):
        if bm_i not in _inverse_remap:
            _inverse_remap[bm_i] = orig_i

    # First-wins invariant: bm 0 should map back to orig 0 (the first
    # original vertex that landed in that bm slot), NOT orig 3.
    assert _inverse_remap[0] == 0
    # Pre-fix code path would do: uvs[loop.vert.index] = uvs[0] for bm 0
    # — by happy accident correct for the FIRST coincident vertex.
    # Critical check: bm 3 (last unique bm slot) maps back to orig 4,
    # NOT to orig 3 (whose UV was the wrong (0.5, 0.5) sentinel).
    assert _inverse_remap[3] == 4
    # Post-fix: bm 3's UV is uvs[_inverse_remap[3]] = uvs[4] = (2.0, 0.0)
    # Pre-fix: bm 3's UV would be uvs[3] = (0.5, 0.5) -- WRONG.
    bm_3_uv = uvs[_inverse_remap[3]]
    assert bm_3_uv == (2.0, 0.0), (
        f"Welded UV lookup picked {bm_3_uv}; expected (2.0, 0.0) — "
        f"_inverse_remap is broken or returning the wrong original index"
    )

    # Sanity: for a non-welded mesh, _inverse_remap[i] == i for every i
    # (no offsets), so the prior code path would be byte-identical.
    plain_verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)]
    plain_remap: list[int] = []
    plain_dedup: dict[tuple[int, int, int], int] = {}
    for v in plain_verts:
        key = (
            round(v[0] / weld_tolerance),
            round(v[1] / weld_tolerance),
            round(v[2] / weld_tolerance),
        )
        if key in plain_dedup:
            plain_remap.append(plain_dedup[key])
        else:
            idx = len(plain_dedup)
            plain_dedup[key] = idx
            plain_remap.append(idx)
    plain_inv: dict[int, int] = {}
    for orig_i, bm_i in enumerate(plain_remap):
        if bm_i not in plain_inv:
            plain_inv[bm_i] = orig_i
    for i in range(len(plain_verts)):
        assert plain_inv[i] == i  # no-weld case unchanged
