"""Regression tests for the CHECKPOINT-5 V2 cascade hotfix PR.

Closes 2 NEW adjacent broken modes surfaced by the CHECKPOINT-5 V2
adversarial sweep across the PR #118 silent-corruption fix. The
``every-silent-corruption-fix-surfaces-a-new-mode`` cross-PR pattern
fired again.

* **CP5-CASCADE Bug 2** (P1) — ``Channel.MACRO_COLOR`` Shape-A
  tag-vs-shape mismatch. The producer
  ``terrain_macro_color.compute_macro_color`` emits (H, W, 3) float32
  RGB but ``_channels.ChannelInfo.unit`` and
  ``terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS`` were both
  tagged ``"dimensionless"``. Same bug class as the
  ``STRATA_ORIENTATION_XYZ`` case PR #113 closed (retagged
  ``"unit_normal_xyz"``). Retagged to ``"rgb_triplet"`` and renamed
  ``Channel.MACRO_COLOR`` → ``Channel.MACRO_COLOR_RGB`` so consumer
  sites see the multi-channel surface explicitly.

* **CP5-CASCADE Bug 3** (P1) — ``_mesh_bridge.mesh_from_spec``
  auto-category material loop homogenization. PR #118 fixed CP4's
  Bug 4 (single-material spec magenta-debug regression) by writing
  the same auto-category material into every slot. Multi-material
  specs (``material_ids = [0, 1, 2, ...]``) inadvertently lost
  per-face material differentiation — every slot was clobbered with
  the same material. Now the loop branches on
  ``len(set(material_ids)) > 1``: multi-material specs only fill
  ``None`` placeholder slots; single-category specs homogenize as
  before.

Each test below fails on ``origin/main`` (pre-fix) and passes after
the hotfix lands.
"""
from __future__ import annotations

import types
from typing import Any, Tuple
from unittest.mock import patch


# ---------------------------------------------------------------------------
# CP5-CASCADE Bug 2 — Channel.MACRO_COLOR_RGB retag
# ---------------------------------------------------------------------------


def test_cp5_bug2_macro_color_renamed_to_rgb_with_rgb_triplet_unit() -> None:
    """``Channel.MACRO_COLOR_RGB`` must exist with unit ``"rgb_triplet"``.

    Mirrors PR #113's STRATA_ORIENTATION_XYZ retag pattern. The producer
    ``terrain_macro_color.compute_macro_color`` writes (H, W, 3) float32
    RGB; the previous ``"dimensionless"`` tag was a Shape-A bug class.

    Pre-fix: ``Channel.MACRO_COLOR`` exists with unit ``"dimensionless"``.
    Post-fix: ``Channel.MACRO_COLOR_RGB`` exists with unit
    ``"rgb_triplet"``. Both the enum rename and the unit retag must
    land together so every consumer sees the multi-channel surface.
    """
    from veilbreakers_terrain.handlers._channels import Channel

    # Enum member must be the renamed variant with the explicit RGB suffix.
    assert hasattr(Channel, "MACRO_COLOR_RGB"), (
        "Channel.MACRO_COLOR_RGB must exist post-retag (mirrors "
        "STRATA_ORIENTATION_XYZ rename). See CP5-CASCADE Bug 2."
    )
    # The legacy bare name must NOT be present — it would mask the
    # tag-vs-shape mismatch from future consumers.
    assert not hasattr(Channel, "MACRO_COLOR"), (
        "Channel.MACRO_COLOR (legacy bare name) must be removed; the "
        "new canonical name is MACRO_COLOR_RGB to make the (H, W, 3) "
        "shape explicit at every consumer site."
    )

    # Value (string key) is preserved for back-compat with mask-stack
    # accessors that lookup by the string ``"macro_color"``.
    assert Channel.MACRO_COLOR_RGB.value == "macro_color", (
        f"Channel.MACRO_COLOR_RGB.value must remain 'macro_color' "
        f"to preserve mask-stack accessor back-compat; got "
        f"{Channel.MACRO_COLOR_RGB.value!r}"
    )

    # Unit MUST be ``"rgb_triplet"`` — not ``"dimensionless"`` (Shape-A bug).
    assert Channel.MACRO_COLOR_RGB.info.unit == "rgb_triplet", (
        f"Channel.MACRO_COLOR_RGB.info.unit must be 'rgb_triplet' to "
        f"match the producer's (H, W, 3) RGB output; got "
        f"{Channel.MACRO_COLOR_RGB.info.unit!r}. This is the "
        f"CP5-CASCADE Bug 2 regression guard."
    )


def test_cp5_bug2_macro_color_in_channels_by_unit_rgb_triplet_bucket() -> None:
    """``CHANNELS_BY_UNIT["rgb_triplet"]`` must include
    ``Channel.MACRO_COLOR_RGB``.

    The ``CHANNELS_BY_UNIT`` table is auto-derived from
    ``_CHANNEL_INFO`` via a frozenset comprehension. After the retag,
    a new key ``"rgb_triplet"`` should appear in the table with
    ``MACRO_COLOR_RGB`` as its sole member.
    """
    from veilbreakers_terrain.handlers._channels import (
        CHANNELS_BY_UNIT,
        Channel,
    )

    assert "rgb_triplet" in CHANNELS_BY_UNIT, (
        "CHANNELS_BY_UNIT must include the 'rgb_triplet' key after "
        "the CP5-CASCADE Bug 2 retag — the auto-derivation pulls it "
        "from _CHANNEL_INFO; failing this means the retag did not "
        "land on ChannelInfo.unit."
    )
    assert Channel.MACRO_COLOR_RGB in CHANNELS_BY_UNIT["rgb_triplet"], (
        "Channel.MACRO_COLOR_RGB must be in CHANNELS_BY_UNIT['rgb_triplet']"
    )
    # Exclusive — must NOT also be in the dimensionless bucket.
    assert Channel.MACRO_COLOR_RGB not in CHANNELS_BY_UNIT.get(
        "dimensionless", frozenset()
    ), (
        "Channel.MACRO_COLOR_RGB must NOT be in the 'dimensionless' "
        "bucket; that would defeat the CP5-CASCADE Bug 2 retag."
    )


def test_cp5_bug2_cross_registry_symmetry_macro_color() -> None:
    """The unit assigned in ``_channels`` must match the unit assigned
    in ``terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS`` for the
    same channel name. Two registries cannot disagree about a channel's
    unit — that would itself be a Shape C bug.

    Mirrors the symmetry test
    ``test_cross_registry_consistency_with_golden_snapshots``; this
    is a focused guard for the CP5-CASCADE Bug 2 retag in particular.
    """
    from veilbreakers_terrain.handlers._channels import Channel
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        _CHANNEL_CANONICAL_UNITS,
    )

    enum_unit = Channel.MACRO_COLOR_RGB.info.unit
    canon_unit = _CHANNEL_CANONICAL_UNITS.get("macro_color")
    assert canon_unit is not None, (
        "_CHANNEL_CANONICAL_UNITS must register 'macro_color' — the "
        "channel is on the TerrainMaskStack and the registry pins "
        "the unit for the assertion gate."
    )
    assert canon_unit == "rgb_triplet", (
        f"_CHANNEL_CANONICAL_UNITS['macro_color'] must be 'rgb_triplet' "
        f"to match the new ChannelInfo unit; got {canon_unit!r}. "
        f"This is the CP5-CASCADE Bug 2 cross-registry regression guard."
    )
    assert enum_unit == canon_unit, (
        f"Unit drift between _channels.Channel.MACRO_COLOR_RGB ({enum_unit!r}) "
        f"and terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS['macro_color'] "
        f"({canon_unit!r}). Both must agree on 'rgb_triplet'."
    )


# ---------------------------------------------------------------------------
# CP5-CASCADE Bug 3 — _mesh_bridge per-face material distinction preserved
# ---------------------------------------------------------------------------


def _build_mesh_bridge_stubs() -> tuple[Any, Any, Any]:
    """Return ``(stub_bpy, stub_bmesh, fake_create_material_factory)`` for
    use with ``patch.object``. Mirrors the stub setup in
    test_checkpoint_4_hotfix.py::test_bug4_mesh_bridge_fills_all_material_slots.

    Returns a 3-tuple:
    * ``stub_bpy`` — fake ``bpy`` module with ``data.meshes/objects`` and
      ``context.collection`` for the mesh_from_spec write path.
    * ``stub_bmesh`` — fake ``bmesh`` module for the BMesh path.
    * ``fake_create_material_factory`` — callable that returns a fresh
      ``(create_material, captured_mats)`` tuple per test.
    """
    class _StubMaterials:
        def __init__(self) -> None:
            self._slots: list[Any] = []

        def append(self, mat: Any) -> None:
            self._slots.append(mat)

        def __iter__(self):
            return iter(self._slots)

        def __len__(self) -> int:
            return len(self._slots)

        def __getitem__(self, i: int) -> Any:
            return self._slots[i]

        def __setitem__(self, i: int, value: Any) -> None:
            self._slots[i] = value

        def __bool__(self) -> bool:
            return bool(self._slots)

    class _StubPoly:
        def __init__(self) -> None:
            self.material_index = 0
            self.use_smooth = False

    class _StubMesh:
        def __init__(self, name: str) -> None:
            self.name = name
            self.materials = _StubMaterials()
            self.polygons: list[_StubPoly] = []

        def update(self) -> None:
            pass

    class _StubObject:
        def __init__(self, name: str, data: _StubMesh) -> None:
            self.name = name
            self.data = data
            self.location = (0, 0, 0)
            self.rotation_euler = (0, 0, 0)
            self.scale = (1, 1, 1)
            self.parent = None

    class _StubMeshes:
        def new(self, name: str) -> _StubMesh:
            return _StubMesh(name)

    class _StubObjects:
        def new(self, name: str, data: _StubMesh) -> _StubObject:
            return _StubObject(name, data)

    class _StubCollection:
        def __init__(self) -> None:
            def _link(obj: Any) -> None:
                return None
            self.objects = types.SimpleNamespace(link=_link)

    class _StubContext:
        def __init__(self) -> None:
            self.collection = _StubCollection()

    class _StubBpyData:
        def __init__(self) -> None:
            self.meshes = _StubMeshes()
            self.objects = _StubObjects()

    class _StubBpy:
        def __init__(self) -> None:
            self.data = _StubBpyData()
            self.context = _StubContext()

    class _StubBMVert:
        def __init__(self, co: Tuple[float, float, float], index: int) -> None:
            self.co = co
            self.index = index
            self.normal = (0.0, 0.0, 1.0)

    class _StubBMFaces:
        def __init__(self) -> None:
            self._faces: list[Any] = []

        def new(self, verts: list[Any]) -> Any:
            f = types.SimpleNamespace(verts=verts, loops=[
                types.SimpleNamespace(vert=v, _uv=None) for v in verts
            ])
            for loop in f.loops:
                class _UV:
                    def __init__(self) -> None:
                        self.uv = (0.0, 0.0)
                loop._uv = _UV()
            self._faces.append(f)
            return f

        def ensure_lookup_table(self) -> None:
            pass

        def __iter__(self):
            return iter(self._faces)

        def __getitem__(self, key: Any) -> Any:
            if isinstance(key, slice):
                return self._faces[key]
            return self._faces[key]

    class _StubBMVerts:
        def __init__(self) -> None:
            self._verts: list[_StubBMVert] = []

        def new(self, co: Tuple[float, float, float]) -> _StubBMVert:
            v = _StubBMVert(co, len(self._verts))
            self._verts.append(v)
            return v

        def ensure_lookup_table(self) -> None:
            pass

    class _StubBMEdges:
        def __init__(self) -> None:
            self._edges: list[Any] = []

            def _get(key: Any) -> Any:
                return None

            def _new(key: Any) -> Any:
                return None

            self.layers = types.SimpleNamespace(
                float=types.SimpleNamespace(get=_get, new=_new)
            )

        def ensure_lookup_table(self) -> None:
            pass

        def __iter__(self):
            return iter(self._edges)

    class _StubBM:
        def __init__(self) -> None:
            self.verts = _StubBMVerts()
            self.faces = _StubBMFaces()
            self.edges = _StubBMEdges()

            def _new_uv(name: Any) -> Any:
                return None

            self.loops = types.SimpleNamespace(layers=types.SimpleNamespace(
                uv=types.SimpleNamespace(new=_new_uv)
            ))

        def to_mesh(self, mesh: _StubMesh) -> None:
            mesh.polygons = [_StubPoly() for _ in self.faces]

        def normal_update(self) -> None:
            pass

        def free(self) -> None:
            pass

    class _StubBmesh:
        @staticmethod
        def new() -> _StubBM:
            return _StubBM()

        class ops:
            @staticmethod
            def recalc_face_normals(bm: Any, faces: Any) -> None:
                pass

    def fake_create_material_factory() -> tuple[Any, list[Any]]:
        captured_mats: list[Any] = []

        def _fake_create_procedural_material(name: str, mat_type: str) -> Any:
            m = types.SimpleNamespace(name=name, mat_type=mat_type)
            captured_mats.append(m)
            return m

        return _fake_create_procedural_material, captured_mats

    return _StubBpy(), _StubBmesh, fake_create_material_factory


def test_cp5_bug3_multi_material_distinction_preserved() -> None:
    """When a spec carries ``material_ids`` with multiple distinct values
    (multi-material spec), the auto-category material loop must NOT
    overwrite slots already populated by upstream consumers.

    Pre-fix (PR #118): the loop wrote ``obj.data.materials[slot_idx] = mat``
    for EVERY slot, silently collapsing any per-face material
    differentiation set by upstream dispatch.

    Post-fix (CP5-CASCADE Bug 3): the loop only fills ``None``
    placeholder slots when ``len(set(material_ids)) > 1``. A pre-set
    non-None slot survives the auto-category pass.

    Test strategy: patch ``bpy.data.meshes.new`` to return a mesh whose
    ``materials.append`` auto-injects the sentinel into slot[1] during
    the placeholder-allocation loop inside ``mesh_from_spec``. Then call
    ``mesh_from_spec`` (the real production path — no inline reimplementation)
    and assert slot[1] still holds the sentinel after the auto-category loop
    ran. The test FAILS if ``mesh_from_spec`` overwrites non-None slots (PR
    #118 regression) and PASSES only when the production multi-material
    branch correctly skips already-populated slots.
    """
    import importlib
    from veilbreakers_terrain.handlers import _mesh_bridge

    stub_bpy, stub_bmesh, factory = _build_mesh_bridge_stubs()
    fake_create_procedural_material, _captured_mats = factory()
    mesh_bridge_module = importlib.reload(_mesh_bridge)

    # SENTINEL: simulates a material an upstream slot-dispatcher placed
    # into slot[1] before the auto-category loop runs inside mesh_from_spec.
    # The upstream-dispatch path does not exist yet, so we inject the
    # sentinel by subclassing _StubMeshes.new to return a mesh whose
    # materials.append auto-populates slot[1] (the second append) with the
    # sentinel instead of None.  The production placeholder-allocation loop
    # ``for _ in range(num_slots): mesh_data.materials.append(None)`` calls
    # append 3 times (num_slots == max([0,1,2,1])+1 == 3).  Intercepting the
    # second call replicates "an upstream dispatcher already claimed slot[1]".
    sentinel_material = types.SimpleNamespace(
        name="UPSTREAM_SLOT_DISPATCH_SENTINEL",
        mat_type="upstream_dispatch",
    )

    class _SentinelInjectingMaterials:
        """Like _StubMaterials but injects sentinel_material at slot[1]."""
        def __init__(self) -> None:
            self._slots: list[Any] = []

        def append(self, mat: Any) -> None:
            # Second append (index 1): inject the sentinel instead of None.
            if len(self._slots) == 1:
                self._slots.append(sentinel_material)
            else:
                self._slots.append(mat)

        def __iter__(self):
            return iter(self._slots)

        def __len__(self) -> int:
            return len(self._slots)

        def __getitem__(self, i: int) -> Any:
            return self._slots[i]

        def __setitem__(self, i: int, value: Any) -> None:
            self._slots[i] = value

        def __bool__(self) -> bool:
            return bool(self._slots)

    class _SentinelInjectingMeshes:
        """Returns a mesh whose materials slot-list injects the sentinel."""
        def new(self, name: str) -> Any:
            import types as _types
            m = _types.SimpleNamespace(
                name=name,
                materials=_SentinelInjectingMaterials(),
                polygons=[],
            )
            def _update() -> None:
                pass
            m.update = _update  # type: ignore[attr-defined]
            return m

    # Patch only the meshes factory; everything else (objects, context,
    # bmesh) comes from the shared stub so mesh_from_spec runs normally.
    stub_bpy.data.meshes = _SentinelInjectingMeshes()

    with patch.object(mesh_bridge_module, "bpy", stub_bpy), \
         patch.object(mesh_bridge_module, "bmesh", stub_bmesh), \
         patch.object(mesh_bridge_module, "_HAS_BPY", True), \
         patch("veilbreakers_terrain.handlers.procedural_materials.create_procedural_material",
               fake_create_procedural_material), \
         patch("veilbreakers_terrain.handlers.procedural_materials.MATERIAL_LIBRARY",
               {"rough_timber": {"node_recipe": {}}}):
        # Multi-material spec: 4 faces, material_ids = [0, 1, 2, 1]
        # → num_slots = max+1 = 3, distinct_set = {0, 1, 2} (size 3 > 1)
        # → multi-material branch fires.
        verts = [
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
        ]
        faces = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
        spec = {
            "vertices": verts,
            "faces": faces,
            "material_ids": [0, 1, 2, 1],
            "metadata": {"category": "furniture"},  # → "rough_timber"
        }

        # Drive the PRODUCTION path — no inline reimplementation of the
        # assignment loop below this line.
        obj = mesh_bridge_module.mesh_from_spec(spec, name="TestMultiMatSentinel")

        # All 3 slots allocated.
        assert len(obj.data.materials) == 3, (
            f"Expected 3 material slots; got {len(obj.data.materials)}"
        )

        # CP5-CASCADE Bug 3 load-bearing assertion: slot[1]'s sentinel
        # MUST survive — the multi-material branch only writes to None slots.
        # This assertion FAILS on the pre-fix (PR #118) code because that
        # version wrote mat into every slot regardless.
        assert obj.data.materials[1] is sentinel_material, (
            "CP5-CASCADE Bug 3 regression: multi-material spec "
            "(material_ids = [0, 1, 2, 1]) must only fill None "
            "placeholder slots. Slot[1] was pre-populated with the "
            "upstream sentinel — under PR #118 behaviour the "
            "sentinel was silently overwritten with the auto-category "
            "material, collapsing per-face material differentiation. "
            f"Expected slot[1] = {sentinel_material.name!r}, got "
            f"{obj.data.materials[1]!r}."
        )
        # Slot[0] and slot[2] (both started as None) DO receive the auto-
        # category material — the magenta-debug fix from CP4 stands for
        # placeholder slots.
        assert obj.data.materials[0] is not None, (
            "slot[0] (started as None) must receive the auto-category "
            "material to keep CP4's magenta-debug fix alive."
        )
        assert obj.data.materials[0] is not sentinel_material, (
            "slot[0] must be the auto-category material, not the sentinel."
        )
        assert obj.data.materials[2] is not None, (
            "slot[2] (started as None) must receive the auto-category material."
        )
        assert obj.data.materials[2] is not sentinel_material, (
            "slot[2] must be the auto-category material, not the sentinel."
        )


def test_cp5_bug3_single_material_spec_still_homogenizes() -> None:
    """When a spec has NO ``material_ids`` (single-category, no per-face
    differentiation) OR has all identical material_ids, the auto-
    category loop must homogenize EVERY slot. This preserves CP4's
    magenta-debug fix for single-material meshes.

    Pre-fix would also work for this case — the regression is purely
    on the multi-material distinction side (Bug 3 above).
    """
    import importlib
    from veilbreakers_terrain.handlers import _mesh_bridge

    stub_bpy, stub_bmesh, factory = _build_mesh_bridge_stubs()
    fake_create_procedural_material, _captured = factory()
    mesh_bridge_module = importlib.reload(_mesh_bridge)

    with patch.object(mesh_bridge_module, "bpy", stub_bpy), \
         patch.object(mesh_bridge_module, "bmesh", stub_bmesh), \
         patch.object(mesh_bridge_module, "_HAS_BPY", True), \
         patch("veilbreakers_terrain.handlers.procedural_materials.create_procedural_material",
               fake_create_procedural_material), \
         patch("veilbreakers_terrain.handlers.procedural_materials.MATERIAL_LIBRARY",
               {"rough_timber": {"node_recipe": {}}}):
        # SINGLE-material spec: no material_ids key at all.
        verts = [
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        ]
        faces = [(0, 1, 2), (0, 2, 3)]
        spec = {
            "vertices": verts,
            "faces": faces,
            # NO material_ids — single-category spec.
            "metadata": {"category": "furniture"},
        }

        obj = mesh_bridge_module.mesh_from_spec(spec, name="TestSingleMat")

        # When material_ids is empty, num_slots stays at 1 by the
        # mesh_from_spec else-branch (num_slots = 1 default).
        # Either way, every slot is filled with the auto-category mat.
        assert len(obj.data.materials) >= 1
        for i, slot in enumerate(obj.data.materials):
            assert slot is not None, (
                f"slot[{i}] is None — CP4 magenta-debug fix must "
                f"still apply for single-material specs. CP5-CASCADE "
                f"Bug 3 must NOT regress this case."
            )
        slot_names = {m.name for m in obj.data.materials}
        assert len(slot_names) == 1, (
            f"Single-material spec must homogenize every slot to one "
            f"material; got distinct names {slot_names}. CP5-CASCADE "
            f"Bug 3 should NOT split the homogenize path for the "
            f"no-material_ids case."
        )
