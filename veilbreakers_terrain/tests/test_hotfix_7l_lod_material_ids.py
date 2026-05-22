"""Tests for HOTFIX-7l: generate_lod_specs propagates material_ids.

Verifier A 2026-05-21 #8 — _mesh_bridge.generate_lod_specs was returning
MeshSpec dicts without a ``material_ids`` key.  Downstream ``mesh_from_spec``
for multi-material LODs raised RuntimeError because the key was absent, which
broke every multi-material LOD asset in the pipeline.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(
    n_faces: int = 6,
    material_ids: list[int] | None = None,
    *,
    name: str = "TestMesh",
) -> dict[str, Any]:
    """Build a minimal valid MeshSpec for a flat triangle grid."""
    # Two triangles per row, n_faces rows — keep it simple: use a cube-ish mesh
    # with n_faces distinct triangles, all sharing a small vertex pool.
    verts = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 1.0),
        (1.0, 1.0, 1.0),
        (0.0, 1.0, 1.0),
    ]
    # Build exactly n_faces triangles cycling through the vertex pool
    faces = []
    for i in range(n_faces):
        a = i % len(verts)
        b = (i + 1) % len(verts)
        c = (i + 2) % len(verts)
        faces.append((a, b, c))
    spec: dict[str, Any] = {
        "vertices": verts,
        "faces": faces,
        "uvs": [(float(i) / n_faces, 0.0) for i in range(len(verts))],
        "metadata": {"name": name, "category": "test"},
    }
    if material_ids is not None:
        spec["material_ids"] = material_ids
    return spec


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_material_ids_key_absent_in_lod_output():
    """Spec with no material_ids → LODs must NOT have material_ids key.

    Backward-compat: single-material callers never set material_ids;
    adding the key would break code that checks ``"material_ids" not in spec``.
    """
    from veilbreakers_terrain.handlers._mesh_bridge import generate_lod_specs

    spec = _make_spec(n_faces=6, material_ids=None)
    lod_list = generate_lod_specs(spec, include_billboard=False)
    assert len(lod_list) == 4
    for lod in lod_list:
        assert "material_ids" not in lod, (
            f"LOD{lod['metadata']['lod_level']} should have no material_ids key "
            f"when source spec has none"
        )


def test_empty_material_ids_key_absent_in_lod_output():
    """Spec with material_ids=[] → LODs must NOT have material_ids key.

    Empty list is treated same as absent — preserves backward compat for
    callers that always set the key but leave it empty for single-material.
    """
    from veilbreakers_terrain.handlers._mesh_bridge import generate_lod_specs

    spec = _make_spec(n_faces=6, material_ids=[])
    lod_list = generate_lod_specs(spec, include_billboard=False)
    for lod in lod_list:
        assert "material_ids" not in lod, (
            f"LOD{lod['metadata']['lod_level']} should have no material_ids key "
            f"when source spec has empty list"
        )


def test_single_material_all_zeros_propagated():
    """Spec with material_ids=[0]*N → all LODs carry the key with all-zero ids."""
    from veilbreakers_terrain.handlers._mesh_bridge import generate_lod_specs

    n = 8
    spec = _make_spec(n_faces=n, material_ids=[0] * n)
    lod_list = generate_lod_specs(spec, include_billboard=False)
    for lod in lod_list:
        assert "material_ids" in lod, (
            f"LOD{lod['metadata']['lod_level']} missing material_ids"
        )
        n_faces_lod = len(lod["faces"])
        ids = lod["material_ids"]
        assert len(ids) == n_faces_lod, (
            f"LOD{lod['metadata']['lod_level']}: material_ids length {len(ids)} "
            f"!= face count {n_faces_lod}"
        )
        assert all(i == 0 for i in ids), "All-zero ids should remain all-zero"


def test_multi_material_lod0_exact_passthrough():
    """LOD0 (ratio=1.0) must return material_ids identical to source."""
    from veilbreakers_terrain.handlers._mesh_bridge import generate_lod_specs

    n = 6
    ids = [0, 1, 2, 1, 0, 2]
    spec = _make_spec(n_faces=n, material_ids=ids)
    lod_list = generate_lod_specs(spec, ratios=[1.0, 0.5, 0.25, 0.1], include_billboard=False)
    lod0 = lod_list[0]
    assert lod0["metadata"]["lod_level"] == 0
    assert "material_ids" in lod0
    # LOD0 returns original geometry verbatim — face count unchanged
    assert len(lod0["material_ids"]) == len(lod0["faces"])
    assert lod0["material_ids"] == ids


def test_multi_material_all_lods_have_key_and_correct_length():
    """All non-billboard LODs must have material_ids with len == face count."""
    from veilbreakers_terrain.handlers._mesh_bridge import generate_lod_specs

    n = 8
    ids = [0, 1, 2, 1, 0, 2, 0, 1]
    spec = _make_spec(n_faces=n, material_ids=ids)
    lod_list = generate_lod_specs(spec, include_billboard=False)
    for lod in lod_list:
        level = lod["metadata"]["lod_level"]
        assert "material_ids" in lod, f"LOD{level} missing material_ids"
        n_faces_lod = len(lod["faces"])
        n_ids = len(lod["material_ids"])
        assert n_ids == n_faces_lod, (
            f"LOD{level}: material_ids length {n_ids} != face count {n_faces_lod}"
        )


def test_billboard_lod_does_not_carry_material_ids():
    """Billboard LOD (synthetic cross-quad) should NOT carry source material_ids.

    The billboard has 4 synthetic faces unrelated to source topology; injecting
    source material_ids would produce a length mismatch at mesh_from_spec.
    """
    from veilbreakers_terrain.handlers._mesh_bridge import generate_lod_specs

    n = 6
    ids = [0, 1, 2, 1, 0, 2]
    spec = _make_spec(n_faces=n, material_ids=ids)
    # include_billboard=True (default) → last level is a billboard
    lod_list = generate_lod_specs(spec, include_billboard=True)
    billboard_lod = lod_list[-1]
    assert billboard_lod["metadata"]["is_billboard"] is True
    assert "material_ids" not in billboard_lod, (
        "Billboard LOD must not carry source material_ids (length mismatch risk)"
    )


def test_decimation_subsampled_material_ids_length_matches_faces():
    """After decimation, sub-sampled material_ids length must equal face count.

    Uses a larger mesh where clustering is expected to reduce face count so
    that the sub-sampling path is exercised (n_lod != n_src branch).
    """
    from veilbreakers_terrain.handlers._mesh_bridge import generate_lod_specs

    # Build a larger mesh: 1000 triangles arranged in a regular grid
    n_verts_side = 33  # 33x33 grid → 32*32*2 = 2048 triangles
    verts = []
    for row in range(n_verts_side):
        for col in range(n_verts_side):
            verts.append((float(col), float(row), 0.0))

    faces = []
    for row in range(n_verts_side - 1):
        for col in range(n_verts_side - 1):
            tl = row * n_verts_side + col
            tr = tl + 1
            bl = tl + n_verts_side
            br = bl + 1
            faces.append((tl, tr, br))
            faces.append((tl, br, bl))

    n_faces = len(faces)
    # Alternating two-material layout
    material_ids = [i % 2 for i in range(n_faces)]

    spec = {
        "vertices": verts,
        "faces": faces,
        "uvs": [],
        "metadata": {"name": "GridMesh", "category": "test"},
        "material_ids": material_ids,
    }

    lod_list = generate_lod_specs(spec, ratios=[1.0, 0.5, 0.25, 0.1], include_billboard=False)

    for lod in lod_list:
        level = lod["metadata"]["lod_level"]
        assert "material_ids" in lod, f"LOD{level} missing material_ids"
        n_faces_lod = len(lod["faces"])
        n_ids = len(lod["material_ids"])
        assert n_ids == n_faces_lod, (
            f"LOD{level}: material_ids length {n_ids} != face count {n_faces_lod}"
        )
        # All ids must be in the valid range [0, 1]
        for mid in lod["material_ids"]:
            assert mid in (0, 1), f"LOD{level}: unexpected material_id value {mid}"


def test_single_face_lod_gets_material_id():
    """Edge case: LOD collapses to exactly 1 face → material_ids=[src[0]]."""
    from veilbreakers_terrain.handlers._mesh_bridge import generate_lod_specs

    # Tiny mesh: 3 verts, 1 face — ratio=1 passthrough only
    spec = {
        "vertices": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, 0.0)],
        "faces": [(0, 1, 2)],
        "uvs": [],
        "metadata": {"name": "Tri", "category": "test"},
        "material_ids": [3],
    }
    lod_list = generate_lod_specs(spec, ratios=[1.0], include_billboard=False)
    lod = lod_list[0]
    assert "material_ids" in lod
    assert len(lod["material_ids"]) == len(lod["faces"])
    assert lod["material_ids"][0] == 3
