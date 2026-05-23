"""Regression test — HOTFIX-7m: UV weld inverse-remap (Verifier A #9).

Bug
---
``_mesh_bridge.py`` builds a vertex-dedup table ``_remap[orig_vi] -> bm_vi``
that collapses coincident original verts into fewer bm-verts.  The UV
assignment loop then reads ``uvs[loop.vert.index]``, where
``loop.vert.index`` is the *bm-vert* index — NOT the original-vert index.
For any vertex that was welded in (i.e. its bm-vert index differs from the
first original-vert index that landed at that position), the UV is read
from the wrong slot of the ``uvs`` list.

Fix
---
Build ``_inverse_remap: dict[int, int]`` (bm_vi -> first orig_vi) during the
dedup loop.  In the UV section use
``orig_vi = _inverse_remap.get(bm_vi, bm_vi)`` so welded verts always read
from the correct original-vert UV slot (first-wins semantics).

Tests
-----
1. ``test_uv_weld_inverse_remap_first_wins`` — mesh with two coincident
   verts at different UV coords; after weld the loop UV must be the
   FIRST vert's UV, not a stale later-vert lookup.

2. ``test_uv_no_weld_identity`` — mesh with no welded verts; UV
   assignment is identical to a simple ``uvs[i]`` read (regression-
   preservation of the no-weld path).

3. ``test_uv_weld_sparse_inverse_remap_all_slots`` — four verts where
   two pairs are coincident; verifies that every face loop in the
   welded mesh resolves to the correct original UV slot.

4. ``test_inverse_remap_source_code_pattern`` — AST-level check that
   ``_inverse_remap`` is built and ``_inverse_remap.get`` is called in
   ``_mesh_bridge.py`` so the fix cannot be silently reverted without
   breaking this test.

Design note — fake BMesh
------------------------
The Blender UV path (``bm.faces``, ``face.loops``, ``loop.vert.index``,
``loop[uv_layer].uv``) runs only under a real bpy.  The conftest installs
MagicMock stubs that swallow attribute access without recording anything
useful.  Instead of monkey-patching the whole bmesh module, these tests
inject a thin *fake BMesh* that records what UV value is written to each
loop.  The fake is injected by monkeypatching the ``bmesh`` module-level
reference used inside ``_mesh_bridge``, and ``_HAS_BPY`` is left True so the
Blender code path actually runs.  The headless fallback (``_HAS_BPY=False``)
path does NOT execute the UV loop and therefore cannot test this bug at all.
"""

from __future__ import annotations

import ast
import types
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers — minimal fake BMesh
# ---------------------------------------------------------------------------


class _FakeUVLayer:
    """Behaves like ``bm.loops.layers.uv`` — just stores assigned UVs."""


class _FakeLoop:
    """Behaves like a BMesh loop: carries a vert index and a writable UV dict."""

    def __init__(self, bm_vi: int) -> None:
        self.vert = types.SimpleNamespace(index=bm_vi)
        self._uv_values: dict[Any, Any] = {}

    def __getitem__(self, layer: Any) -> Any:
        # Return a mutable namespace so ``loop[uv_layer].uv = ...`` works.
        if layer not in self._uv_values:
            self._uv_values[layer] = types.SimpleNamespace(uv=None)
        return self._uv_values[layer]

    def __setitem__(self, layer: Any, value: Any) -> None:
        self._uv_values[layer] = value

    def get_uv(self, layer: Any) -> Any:
        item = self._uv_values.get(layer)
        if item is None:
            return None
        return getattr(item, "uv", item)


class _FakeFace:
    def __init__(self, loops: list[_FakeLoop]) -> None:
        self.loops = loops


class _FakeLayersUV:
    def new(self, name: str) -> _FakeUVLayer:
        return _FakeUVLayer()


class _FakeLayersContainer:
    def __init__(self) -> None:
        self.uv = _FakeLayersUV()


class _FakeVertsContainer:
    """Minimal ``bm.verts`` container — supports ``.new()`` and
    ``.ensure_lookup_table()``."""

    def __init__(self) -> None:
        self._verts: list[types.SimpleNamespace] = []

    def new(self, co: Any) -> types.SimpleNamespace:  # noqa: A003
        vert = types.SimpleNamespace(index=len(self._verts), co=co)
        self._verts.append(vert)
        return vert

    def ensure_lookup_table(self) -> None:
        pass

    def __iter__(self):  # type: ignore[override]
        return iter(self._verts)

    def __len__(self) -> int:
        return len(self._verts)


class _FakeFacesContainer:
    def __init__(self, faces: list[_FakeFace]) -> None:
        self._faces = faces

    def new(self, bm_verts_list: list[Any]) -> None:
        loops = [_FakeLoop(v.index) for v in bm_verts_list]
        self._faces.append(_FakeFace(loops))

    def ensure_lookup_table(self) -> None:
        pass

    def __iter__(self):  # type: ignore[override]
        return iter(self._faces)

    def __getitem__(self, idx: Any) -> Any:
        # Support slicing (bm.faces[:]) as well as integer indexing
        return self._faces[idx]

    def __len__(self) -> int:
        return len(self._faces)


class _FakeEdgesContainer:
    def ensure_lookup_table(self) -> None:
        pass

    def __iter__(self):  # type: ignore[override]
        return iter([])


class _FakeLoopsContainer:
    def __init__(self) -> None:
        self.layers = _FakeLayersContainer()


class _FakeBMesh:
    """Minimal BMesh fake that records what UVs are assigned."""

    def __init__(self) -> None:
        self._face_list: list[_FakeFace] = []
        self.verts = _FakeVertsContainer()
        self.faces = _FakeFacesContainer(self._face_list)
        self.edges = _FakeEdgesContainer()
        self.loops = _FakeLoopsContainer()

    def normal_update(self) -> None:
        pass

    def free(self) -> None:
        pass

    def to_mesh(self, mesh_data: Any) -> None:
        pass

    def get_all_uvs(self, uv_layer: Any) -> list[Any]:
        """Return list of (face_idx, loop_idx, uv) triples for inspection."""
        result = []
        for fi, face in enumerate(self._face_list):
            for li, loop in enumerate(face.loops):
                result.append((fi, li, loop.get_uv(uv_layer)))
        return result


# ---------------------------------------------------------------------------
# Fixture — inject fake BMesh into mesh_bridge
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_bm_factory(monkeypatch: pytest.MonkeyPatch):  # type: ignore[misc]
    """Fixture that replaces bmesh.new in _mesh_bridge with a factory returning
    a _FakeBMesh.  Also patches out the bpy.data / bpy.context / bpy.ops
    pieces that mesh_from_spec touches after bm.to_mesh(), and forces
    _HAS_BPY=True so the Blender path runs.

    Returns the _FakeBMesh instance that was used.
    """
    import veilbreakers_terrain.handlers._mesh_bridge as _mb

    created: list[_FakeBMesh] = []

    def _fake_bmesh_new() -> _FakeBMesh:
        bm = _FakeBMesh()
        created.append(bm)
        return bm

    # Patch bmesh.new and bmesh.ops.recalc_face_normals
    import bmesh as _bmesh_stub  # the conftest MagicMock stub

    monkeypatch.setattr(_bmesh_stub, "new", _fake_bmesh_new)

    # bmesh.ops.recalc_face_normals — let it be a no-op.
    # The production call is: bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    # so the lambda must accept one positional arg (bm) plus **kwargs.
    fake_ops = types.SimpleNamespace(
        recalc_face_normals=lambda _bm, **_kw: None,  # type: ignore[misc]  # pyright: ignore[reportUnknownLambdaType]
    )
    monkeypatch.setattr(_bmesh_stub, "ops", fake_ops)

    # bpy.data.meshes.new → return a fake mesh_data
    import bpy as _bpy_stub  # the conftest MagicMock stub

    class _FakeMeshData:
        def __init__(self) -> None:
            self.polygons: list[Any] = []
            self.materials: list[Any] = []
            self.vertices: list[Any] = []

        def update(self) -> None:
            pass

    fake_mesh_data = _FakeMeshData()
    monkeypatch.setattr(_bpy_stub.data.meshes, "new", lambda name: fake_mesh_data)  # type: ignore[misc]  # pyright: ignore[reportUnknownLambdaType]

    # bpy.data.objects.new → return a fake obj
    class _FakeObj:
        name: str = "fake_obj"
        location = (0.0, 0.0, 0.0)
        rotation_euler = (0.0, 0.0, 0.0)
        scale = (1.0, 1.0, 1.0)
        parent = None

    fake_obj = _FakeObj()
    monkeypatch.setattr(_bpy_stub.data.objects, "new", lambda name, mesh: fake_obj)  # type: ignore[misc]  # pyright: ignore[reportUnknownLambdaType]

    # bpy.context.collection.objects.link → no-op
    fake_collection = types.SimpleNamespace(objects=types.SimpleNamespace(link=lambda o: None))  # type: ignore[misc]  # pyright: ignore[reportUnknownLambdaType]
    monkeypatch.setattr(_bpy_stub.context, "collection", fake_collection)

    # Force _HAS_BPY=True (conftest may already set this, but be explicit)
    monkeypatch.setattr(_mb, "_HAS_BPY", True)

    def _get_bm() -> _FakeBMesh | None:
        return created[0] if created else None

    return _get_bm


# ---------------------------------------------------------------------------
# Test 1 — weld: first-wins UV at welded position
# ---------------------------------------------------------------------------


def test_uv_weld_inverse_remap_first_wins(
    fake_bm_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Welded vertex carries the FIRST original vert's UV, not a stale later-vert lookup.

    Mesh layout:
    - v0 = (0, 0, 0)  uv=(0.0, 0.0)   ← FIRST to land at origin bucket
    - v1 = (1, 0, 0)  uv=(1.0, 0.0)   ← unique position
    - v2 = (0, 1, 0)  uv=(0.0, 1.0)   ← unique position
    - v3 = (0, 0, 0)  uv=(1.0, 1.0)   ← DUPLICATE of v0 → welded to bm_vi=0

    One triangle face: [0, 1, 2]  (v0, v1, v2)
    One triangle face: [3, 1, 2]  (v3 welds to v0; same bm triangle as face 0)

    After weld:
      bm_vi 0 == orig_vi 0  →  UV should be (0.0, 0.0)  (first-wins, not v3's (1.0,1.0))
      bm_vi 1 == orig_vi 1  →  UV should be (1.0, 0.0)
      bm_vi 2 == orig_vi 2  →  UV should be (0.0, 1.0)

    The PRE-FIX code would read uvs[bm_vi=0]=(0.0,0.0) for the first face
    (coincidentally correct for face 0 since bm_vi==orig_vi there) but for
    face 1 loop referring to the welded v3→bm_vi=0, it STILL reads uvs[0]
    which happens to be (0.0, 0.0) — but that's only correct BY ACCIDENT
    because v3 maps to bm_vi=0 and uvs[0] also happens to be v0's UV.

    The real failure case: if v0 were appended AFTER v3 (so bm_vi for the
    coincident bucket is set to v3's original index in the OLD code). To
    stress-test this properly we use a mesh where the first vert at a
    position has orig_vi=3 (bm_vi=0 after earlier unique verts) so that
    orig_vi != bm_vi, and a later duplicate maps to the same bucket.

    Revised layout for a clean test of the bug:
    - v0 = (1, 0, 0)  uv=(0.1, 0.0)  bm_vi=0  (unique)
    - v1 = (0, 1, 0)  uv=(0.0, 0.1)  bm_vi=1  (unique)
    - v2 = (0, 0, 1)  uv=(0.2, 0.2)  bm_vi=2  (unique)
    - v3 = (0, 0, 0)  uv=(0.3, 0.3)  bm_vi=3  ← FIRST at origin bucket
    - v4 = (0, 0, 0)  uv=(0.9, 0.9)  bm_vi=3  ← duplicate; welded to bm_vi=3

    Face [0, 1, 3]  bm_verts [0, 1, 3]
    Face [0, 2, 4]  bm_verts [0, 2, 3]  (v4→bm_vi=3)

    In face [0,2,4]:
      loop for bm_vi=3 → orig_vi=3 → uv=(0.3, 0.3)  ← CORRECT (first-wins)

    Pre-fix code: loop.vert.index=3 → uvs[3]=(0.3,0.3) coincidentally correct
    because bm_vi=3 happens to equal orig_vi=3 for the first vert at origin.

    To FORCE orig_vi != bm_vi for the weld target, we need the first-at-bucket
    vert to have orig_vi > 0 and bm_vi = (number of unique verts before it).
    That's naturally the case for v3 (orig_vi=3, bm_vi=3) only because we
    have exactly 3 unique verts before it.  For a harder test: insert a gap
    where bm_vi < orig_vi by having a duplicate BEFORE the canonical first-at-
    bucket, which is impossible by definition (first-at-bucket IS the first).

    The canonical stress test for the inverse-remap bug is a different shape:
    the FIRST vert at a bucket has orig_vi=N > 0 and bm_vi < N because earlier
    unique verts took bm indices 0..N-1.  Then a face references a LATER
    duplicate (orig_vi=M) and the pre-fix code reads uvs[bm_vi] which is wrong
    when bm_vi != orig_vi for the first-canonical vert.

    Final layout (bm_vi clearly != orig_vi for the canonical vert):
    - v0 = (1, 0, 0)  uv=(0.10, 0.20)  bm_vi=0  unique
    - v1 = (2, 0, 0)  uv=(0.30, 0.40)  bm_vi=1  unique
    - v2 = (3, 0, 0)  uv=(0.50, 0.60)  bm_vi=2  unique
    - v3 = (4, 0, 0)  uv=(0.70, 0.80)  bm_vi=3  unique  ← canonical origin of bucket B
    - v4 = (4, 0, 0)  uv=(0.99, 0.99)  DUPLICATE → bm_vi=3 (welded to v3)

    Face [0, 1, 4]  bm=[0, 1, 3]
      loop bm_vi=3 → orig_vi should be 3 → uv (0.70, 0.80)
      PRE-FIX: uvs[bm_vi=3] = uvs[3] = (0.70, 0.80) — happens to be correct
      because bm_vi==orig_vi for the FIRST vert at that bucket.

    This shows that when the canonical vert has bm_vi==orig_vi (which is
    always true for unique verts because bm assigns consecutive indices),
    the bug cannot be demonstrated by inspecting loops on the canonical vert.
    The bug fires ONLY when a later duplicate's loop is used — but after weld
    the loop carries the CANONICAL bm_vi (same as orig_vi for the first vert),
    so uvs[bm_vi] == uvs[orig_vi] == correct.

    Conclusion: the bug manifests ONLY when we have a MULTI-UV-per-vert setup
    where the "first-wins" original UV at a given bm-vert bucket differs from
    uvs[bm_vi].  This happens ONLY when bm_vi != orig_vi for the first vert
    at a bucket — which is impossible for unique verts (bm assigns bm_vi=N
    exactly when there are N prior unique verts, matching orig_vi only if no
    prior orig verts were ALSO unique — which they always are since dedup
    sees each unique position once).

    WAIT — re-examine.  bm_vi is assigned as ``len(bm_verts)`` at the time of
    insertion.  orig_vi is the enumerate index.  They differ WHEN DUPLICATES
    APPEAR BEFORE THE CANONICAL FIRST VERT — which is impossible (the first
    occurrence defines the bucket).

    REAL BUG SCENARIO: bm_vi 0 corresponds to orig_vi 0; bm_vi 1 to orig_vi 1;
    etc.  For unique verts bm_vi always equals orig_vi.  The bug fires when we
    have MORE original verts than bm-verts — i.e. when orig_vi > bm_vi for some
    verts (the later duplicates).  But the UV loop does NOT iterate over
    original verts — it iterates over bm faces/loops.  After weld, a face
    that originally referenced orig_vi=4 (a duplicate) now has loop.vert.index=
    bm_vi=3 (the canonical vert's bm index).  The OLD code reads uvs[bm_vi=3],
    which equals the canonical v3's UV.  That IS the correct first-wins UV.

    So the old code is accidentally correct for single-face meshes?  Let me
    re-read the audit finding more carefully.

    Verifier A #9 says: "_mesh_bridge.py:1569-1573 — uvs[vi] reads
    original-vertex-indexed UVs with post-dedup bm-vert index".

    The scenario: suppose we have 6 original verts [0..5] and 4 unique
    positions (bm_vi 0..3).  bm_vi assignments:
      orig 0 → bm_vi 0
      orig 1 → bm_vi 1
      orig 2 → bm_vi 0  (weld to orig 0)
      orig 3 → bm_vi 2
      orig 4 → bm_vi 1  (weld to orig 1)
      orig 5 → bm_vi 3

    Now uvs has 6 entries indexed [0..5].
    After bm construction, bm has 4 verts: bm_vi 0, 1, 2, 3.
    UV loop: for each bm-vert in each face, loop.vert.index = bm_vi ∈ {0,1,2,3}.
    Old code: loop[uv_layer].uv = uvs[bm_vi]
      bm_vi=0 → uvs[0]  ✓ (same as orig_vi=0)
      bm_vi=1 → uvs[1]  ✓ (same as orig_vi=1)
      bm_vi=2 → uvs[2]  ✗ should be uvs[3] (orig_vi=3 was first at bm_vi=2)
      bm_vi=3 → uvs[3]  ✗ should be uvs[5] (orig_vi=5 was first at bm_vi=3)

    THIS is the bug.  bm_vi=2 maps to orig_vi=3 (not 2) because orig 0→bm0,
    orig 1→bm1, orig 2 is a DUPLICATE (goes to bm0), orig 3 gets bm_vi=2.
    So bm_vi and orig_vi diverge as soon as any earlier vert is a duplicate.

    Test mesh for this:
    - v0=(0,0,0) uv=(0.0, 0.0)  bm_vi=0
    - v1=(1,0,0) uv=(0.1, 0.0)  bm_vi=1
    - v2=(0,0,0) uv=(0.5, 0.5)  DUPLICATE of v0 → bm_vi=0  ← inserts gap
    - v3=(0,1,0) uv=(0.0, 0.1)  bm_vi=2  (NOT orig_vi 2 — orig_vi is 3!)
    - v4=(1,1,0) uv=(0.1, 0.1)  bm_vi=3  (orig_vi=4 — another shift)

    Face [0,1,3] (orig) → bm [0,1,2]
    Face [0,1,4] (orig) → bm [0,1,3]

    UV loop for face [0,1,3] → bm [0,1,2]:
      bm_vi=2 → OLD: uvs[2]=(0.5,0.5) WRONG; CORRECT: uvs[3]=(0.0,0.1)
    UV loop for face [0,1,4] → bm [0,1,3]:
      bm_vi=3 → OLD: uvs[3]=(0.0,0.1) WRONG; CORRECT: uvs[4]=(0.1,0.1)
    """
    get_bm = fake_bm_factory

    import veilbreakers_terrain.handlers._mesh_bridge as _mb

    # Build the mesh described in the docstring above
    verts = [
        (0.0, 0.0, 0.0),  # v0  bm_vi=0
        (1.0, 0.0, 0.0),  # v1  bm_vi=1
        (0.0, 0.0, 0.0),  # v2  DUPLICATE of v0 → bm_vi=0  (creates the gap)
        (0.0, 1.0, 0.0),  # v3  bm_vi=2  (orig_vi=3 ≠ bm_vi=2 — THIS is the bug trigger)
        (1.0, 1.0, 0.0),  # v4  bm_vi=3  (orig_vi=4 ≠ bm_vi=3)
    ]
    uvs = [
        (0.0, 0.0),   # v0
        (0.1, 0.0),   # v1
        (0.5, 0.5),   # v2  (duplicate; first-wins → bm_vi=0 keeps v0's UV)
        (0.0, 0.1),   # v3  ← correct UV for bm_vi=2
        (0.1, 0.1),   # v4  ← correct UV for bm_vi=3
    ]
    faces = [
        [0, 1, 3],  # uses orig verts v0, v1, v3
        [0, 1, 4],  # uses orig verts v0, v1, v4
    ]
    spec = {"vertices": verts, "faces": faces, "uvs": uvs}

    _mb.mesh_from_spec(spec)

    bm = get_bm()
    assert bm is not None, "FakeBMesh was not created — Blender path did not run"

    # Collect the UV layer object (created by bm.loops.layers.uv.new)
    # We need to find the uv_layer key used in the loops.
    # Since _FakeLoop stores by the layer object as key, we need the layer.
    # We can inspect all loop UV assignments.
    all_uvs: dict[int, Any] = {}
    for face in bm._face_list:
        for loop in face.loops:
            bm_vi = loop.vert.index
            # Get the UV — find the first non-None value in the loop's _uv_values
            for _, slot in loop._uv_values.items():
                uv_val = getattr(slot, "uv", None)
                if uv_val is not None:
                    all_uvs[bm_vi] = uv_val

    # bm_vi=0 → first orig_vi=0 → UV (0.0, 0.0)
    assert (0, 0.0) == (0, all_uvs.get(0, "MISSING")[1] if all_uvs.get(0) else "MISSING") or \
        all_uvs.get(0) == (0.0, 0.0), (
        f"bm_vi=0 UV should be (0.0, 0.0), got {all_uvs.get(0)}"
    )

    # bm_vi=2 → first orig_vi=3 → UV (0.0, 0.1)   ← the HOTFIX-7m anchor case
    # PRE-FIX: uvs[2] = (0.5, 0.5)  WRONG
    # POST-FIX: uvs[3] = (0.0, 0.1) CORRECT
    uv_bm2 = all_uvs.get(2)
    assert uv_bm2 is not None, "bm_vi=2 loop UV was never set"
    assert uv_bm2 == (0.0, 0.1), (
        f"HOTFIX-7m anchor: bm_vi=2 UV should be (0.0, 0.1) [uvs[orig_vi=3]], "
        f"got {uv_bm2}. "
        f"Pre-fix code would give (0.5, 0.5) [uvs[bm_vi=2]] — wrong duplicate UV."
    )

    # bm_vi=3 → first orig_vi=4 → UV (0.1, 0.1)
    # PRE-FIX: uvs[3] = (0.0, 0.1)  WRONG
    # POST-FIX: uvs[4] = (0.1, 0.1) CORRECT
    uv_bm3 = all_uvs.get(3)
    assert uv_bm3 is not None, "bm_vi=3 loop UV was never set"
    assert uv_bm3 == (0.1, 0.1), (
        f"bm_vi=3 UV should be (0.1, 0.1) [uvs[orig_vi=4]], "
        f"got {uv_bm3}. "
        f"Pre-fix code would give (0.0, 0.1) [uvs[bm_vi=3]] — wrong."
    )


# ---------------------------------------------------------------------------
# Test 2 — no-weld: UV assignment is identity (no regression)
# ---------------------------------------------------------------------------


def test_uv_no_weld_identity(
    fake_bm_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no verts are welded, UV assignment is identical to direct uvs[i].

    This confirms the inverse-remap code path doesn't perturb
    the common no-weld case.
    """
    get_bm = fake_bm_factory
    import veilbreakers_terrain.handlers._mesh_bridge as _mb

    verts = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
    ]
    uvs = [
        (0.25, 0.25),
        (0.75, 0.25),
        (0.50, 0.75),
    ]
    faces = [[0, 1, 2]]
    spec = {"vertices": verts, "faces": faces, "uvs": uvs}

    _mb.mesh_from_spec(spec)

    bm = get_bm()
    assert bm is not None

    assigned: dict[int, Any] = {}
    for face in bm._face_list:
        for loop in face.loops:
            for _, slot in loop._uv_values.items():
                uv_val = getattr(slot, "uv", None)
                if uv_val is not None:
                    assigned[loop.vert.index] = uv_val

    for bm_vi, expected_uv in enumerate(uvs):
        assert assigned.get(bm_vi) == expected_uv, (
            f"No-weld: bm_vi={bm_vi} UV should be {expected_uv}, "
            f"got {assigned.get(bm_vi)}"
        )


# ---------------------------------------------------------------------------
# Test 3 — two pairs of welded verts, all loops correct
# ---------------------------------------------------------------------------


def test_uv_weld_sparse_inverse_remap_all_slots(
    fake_bm_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two coincident pairs; every loop in the welded mesh resolves correctly.

    Original verts (6):
      0=(0,0,0) uv=(0.0,0.0)  bm_vi=0
      1=(1,0,0) uv=(0.1,0.0)  bm_vi=1
      2=(0,0,0) uv=(0.8,0.8)  DUP→bm_vi=0  (gap: bm_vi now behind orig_vi)
      3=(0,1,0) uv=(0.0,0.1)  bm_vi=2  (orig_vi=3 ≠ bm_vi=2)
      4=(1,0,0) uv=(0.9,0.9)  DUP→bm_vi=1  (another gap)
      5=(1,1,0) uv=(0.1,0.1)  bm_vi=3  (orig_vi=5 ≠ bm_vi=3)

    Two faces:
      [0,1,3]  bm=[0,1,2]
      [2,4,5]  bm=[0,1,3]  (both 2 and 4 are welded)

    Expected UVs:
      bm_vi=0 → orig_vi=0 → (0.0,0.0)
      bm_vi=1 → orig_vi=1 → (0.1,0.0)
      bm_vi=2 → orig_vi=3 → (0.0,0.1)
      bm_vi=3 → orig_vi=5 → (0.1,0.1)
    """
    get_bm = fake_bm_factory
    import veilbreakers_terrain.handlers._mesh_bridge as _mb

    verts = [
        (0.0, 0.0, 0.0),   # 0 bm0
        (1.0, 0.0, 0.0),   # 1 bm1
        (0.0, 0.0, 0.0),   # 2 DUP→bm0
        (0.0, 1.0, 0.0),   # 3 bm2
        (1.0, 0.0, 0.0),   # 4 DUP→bm1
        (1.0, 1.0, 0.0),   # 5 bm3
    ]
    uvs = [
        (0.0, 0.0),  # 0
        (0.1, 0.0),  # 1
        (0.8, 0.8),  # 2  (dup — should NOT appear in output)
        (0.0, 0.1),  # 3  ← correct for bm_vi=2
        (0.9, 0.9),  # 4  (dup — should NOT appear)
        (0.1, 0.1),  # 5  ← correct for bm_vi=3
    ]
    faces = [
        [0, 1, 3],
        [2, 4, 5],
    ]
    spec = {"vertices": verts, "faces": faces, "uvs": uvs}
    _mb.mesh_from_spec(spec)

    bm = get_bm()
    assert bm is not None

    assigned: dict[int, Any] = {}
    for face in bm._face_list:
        for loop in face.loops:
            for _, slot in loop._uv_values.items():
                uv_val = getattr(slot, "uv", None)
                if uv_val is not None:
                    assigned[loop.vert.index] = uv_val

    expected = {
        0: (0.0, 0.0),
        1: (0.1, 0.0),
        2: (0.0, 0.1),  # orig_vi=3 not bm_vi=2
        3: (0.1, 0.1),  # orig_vi=5 not bm_vi=3
    }
    for bm_vi, exp_uv in expected.items():
        got = assigned.get(bm_vi)
        assert got == exp_uv, (
            f"bm_vi={bm_vi}: expected UV {exp_uv}, got {got}. "
            f"Pre-fix would give uvs[{bm_vi}]={uvs[bm_vi]}."
        )


# ---------------------------------------------------------------------------
# Test 4 — AST source-code regression pin
# ---------------------------------------------------------------------------

_MESH_BRIDGE_PATH = (
    Path(__file__).resolve().parents[1] / "handlers" / "_mesh_bridge.py"
)


def test_inverse_remap_source_code_pattern() -> None:
    """_mesh_bridge.py must build _inverse_remap AND call _inverse_remap.get.

    This AST-level test pins the HOTFIX-7m fix so it cannot be silently
    reverted.  If someone removes the inverse-remap or switches back to
    ``uvs[vi]``, both assertions fail with a clear message pointing to the
    Verifier A #9 anchor.
    """
    source = _MESH_BRIDGE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_MESH_BRIDGE_PATH))

    # 1. _inverse_remap dict is assigned somewhere in the source
    assigns_inverse_remap = any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "_inverse_remap"
            for t in node.targets
        )
        or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_inverse_remap"
        )
        for node in ast.walk(tree)
    )
    assert assigns_inverse_remap, (
        "HOTFIX-7m regression: '_inverse_remap' dict not found in _mesh_bridge.py. "
        "The UV weld inverse-remap fix (Verifier A #9) has been removed. "
        "Re-add _inverse_remap: dict[int, int] = {} in the vertex dedup loop."
    )

    # 2. _inverse_remap.get is called somewhere in the source
    calls_inverse_remap_get = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_inverse_remap"
        for node in ast.walk(tree)
    )
    assert calls_inverse_remap_get, (
        "HOTFIX-7m regression: '_inverse_remap.get(...)' not found in _mesh_bridge.py. "
        "The UV loop must use _inverse_remap.get(bm_vi, bm_vi) to translate "
        "bm-vert index → original-vert index before reading uvs[orig_vi]. "
        "Verifier A #9 anchor."
    )
