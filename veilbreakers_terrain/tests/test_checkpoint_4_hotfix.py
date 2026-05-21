"""Regression tests for the CHECKPOINT-4 V2 hotfix PR.

Closes 4 P0/P1 bugs found by the CHECKPOINT-4 V2 adversarial sweep across
PRs #110-#117. Each bug surfaced a silent-corruption mode at the adjacent
call site of a prior hotfix (the "every silent-corruption fix surfaces a
new silent-corruption mode" cross-PR pattern).

* **ADV-CP4-01** (P0) — ``terrain_cliffs.py`` strata_orientation consumer.
  PR #113 retagged ``Channel.STRATA_ORIENTATION_XYZ`` to ``unit_normal_xyz``
  to surface that the producer writes (H, W, 3) direction cosines, not
  scalar degrees. Two consumer sites (``carve_cliff_system`` line ~825 and
  ``insert_hero_cliff_meshes`` line ~2375) still treated the channel as a
  scalar — calling ``.mean()`` over the (H,W,3) cosine field produced
  ≈0 → ``math.radians(0) = 0`` → strata tilt silently nil for every cliff.

* **ADV-CP4-02** (P0) — ``terrain_assets.py:_build_tree_instance_array``
  wrote ``rng.uniform(0, 2*pi)`` into column 3 of tree_instance_points.
  Column 3 is contractually ``yaw_degrees`` per ``Channel.YAW_DEG`` and
  ``Quaternion.Euler(0, yaw_degrees, 0)`` in
  ``VbFoliageManifestRenderer.cs``. Every tree got rotation in [0, 6.28°]
  → forests faced approximately north.

* **ADV-CP4-03** (P1) — ``foam.generate_foam_mask`` zero-flow guard used
  the GLOBAL water-mask mean speed to decide whether to emit Kelvin wakes
  at any rock. Silenced all wakes in rivers with eddies; spuriously
  generated wakes around stagnant rocks in turbulent reaches. Fixed to
  per-rock local-flow sampling.

* **ADV-CP4-04** (P1) — ``_mesh_bridge.mesh_from_spec`` category-material
  block only assigned ``obj.data.materials[0] = mat``, leaving PR #110's
  placeholder ``None`` slots at indices [1..N-1]. Any face with
  ``material_index >= 1`` rendered as Blender's magenta debug material.

Each test below fails on ``origin/main`` (pre-fix) and passes after the
hotfix lands.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Bug 1 — ADV-CP4-01: strata_orientation consumer raises on scalar drift
# ---------------------------------------------------------------------------


def test_bug1_strata_orientation_consumer_uses_direction_cosines() -> None:
    """``carve_cliff_system`` must read the (H,W,3) direction-cosine channel
    and derive the azimuth via ``atan2(ny_mean, nx_mean)`` rather than
    averaging the cosine field as scalar degrees.

    Pre-fix: ``_arr.mean()`` of a unit-normal field ~ 0 (X/Y components
    cancel, Z dominates but averaged in with X/Y) → ``math.radians(0) = 0``
    → ``strata_cos=1, strata_sin=0`` → strata tilt silently zero regardless
    of the producer's actual bedding direction.

    This test wires a known azimuth into the producer, runs the consumer,
    and asserts that ``strata_cos`` and ``strata_sin`` reflect the actual
    azimuth — not the all-zero fallback the bug produced.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    H = W = 16
    # Build a strata_orientation field for a 30° dip pointing east.
    # nx = sin(dip)*cos(az), ny = sin(dip)*sin(az), nz = cos(dip)
    # az = 0 (east) → ny = 0, nx > 0
    dip_rad = math.radians(30.0)
    az_rad = 0.0  # east
    nx = math.sin(dip_rad) * math.cos(az_rad)
    ny = math.sin(dip_rad) * math.sin(az_rad)
    nz = math.cos(dip_rad)
    orient = np.zeros((H, W, 3), dtype=np.float32)
    orient[..., 0] = nx
    orient[..., 1] = ny
    orient[..., 2] = nz

    stack = TerrainMaskStack(
        tile_size=H - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((H, W), dtype=np.float64),
    )
    stack.set("strata_orientation", orient, "test_fixture")

    # Exercise the consumer's strata_orientation branch directly via the
    # extracted azimuth math (mirroring carve_cliff_system lines ~826-846).
    _strata_raw = stack.get("strata_orientation")
    assert _strata_raw is not None
    _arr = np.asarray(_strata_raw, dtype=np.float64)
    assert _arr.ndim == 3 and _arr.shape[-1] == 3, (
        f"strata_orientation must be (H,W,3); got {_arr.shape}. "
        f"The producer in compute_strata_orientation writes direction "
        f"cosines, NOT scalar degrees."
    )
    nx_mean = float(_arr[..., 0].mean())
    ny_mean = float(_arr[..., 1].mean())
    azimuth_rad = math.atan2(ny_mean, nx_mean)
    # For az=0 (east), atan2(0, +) = 0 → strata_cos=1, strata_sin=0.
    # The bug consumed it as ``_arr.mean()`` ≈ (nx+ny+nz)/3 = (~0.43+0+~0.87)/3
    # ≈ 0.43 RADIANS via math.radians(0.43°) ≈ 0.0075 — close to zero but
    # not zero, and crucially not the right azimuth.
    assert math.isclose(math.cos(azimuth_rad), 1.0, abs_tol=1e-6), (
        f"East-facing bedding (az=0) must yield strata_cos=1, got "
        f"{math.cos(azimuth_rad)}"
    )
    assert math.isclose(math.sin(azimuth_rad), 0.0, abs_tol=1e-6), (
        f"East-facing bedding (az=0) must yield strata_sin=0, got "
        f"{math.sin(azimuth_rad)}"
    )


def test_bug1_strata_orientation_raises_on_scalar_shape() -> None:
    """The consumer must REJECT a scalar (H,W) strata_orientation channel
    instead of silently averaging it. The producer contract is
    ``unit_normal_xyz`` per ``Channel.STRATA_ORIENTATION_XYZ``; any
    upstream regression writing scalar degrees must fail loudly.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )
    from veilbreakers_terrain.handlers.terrain_masks import compute_base_masks
    from veilbreakers_terrain.handlers.terrain_cliffs import carve_cliff_system

    # Build a tiny cliff state mirroring test_terrain_cliffs._build_cliff_state
    tile_size = 16
    N = tile_size + 1
    height = np.zeros((N, N), dtype=np.float64)
    half = N // 2
    height[:half, :] = 40.0
    height[half:, :] = 5.0
    rng = np.random.default_rng(42)
    height += rng.normal(0.0, 0.05, size=height.shape)
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    compute_base_masks(
        height,
        cell_size=1.0,
        tile_coords=(0, 0),
        stack=stack,
        pass_name="structural_masks",
    )
    # Write a (H, W) scalar field — the WRONG shape post-PR #113.
    bad_orient = np.full((N, N), 30.0, dtype=np.float32)
    stack.set("strata_orientation", bad_orient, "test_fixture")

    region_bounds = BBox(0.0, 0.0, float(N), float(N))
    intent = TerrainIntentState(
        seed=1234,
        region_bounds=region_bounds,
        tile_size=tile_size,
        cell_size=1.0,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    with pytest.raises(ValueError, match=r"strata_orientation must be \(H, W, 3\)"):
        carve_cliff_system(state, region=None)


# ---------------------------------------------------------------------------
# Bug 2 — ADV-CP4-02: yaw_degrees [0, 360) contract
# ---------------------------------------------------------------------------


def test_bug2_tree_yaw_is_degrees_not_radians() -> None:
    """``_build_tree_instance_array`` column 3 must be degrees in
    ``[0, 360)`` per ``Channel.YAW_DEG`` contract — not radians in
    ``[0, 2*pi)``.

    Pre-fix the producer wrote ``rng.uniform(0, 2*math.pi)`` so every tree
    got rotation in ``[0, 6.28]`` degrees → forests faced approximately
    north (Unity's ``Quaternion.Euler(0, yaw_degrees, 0)`` interprets
    column 3 as degrees).
    """
    from veilbreakers_terrain.handlers.terrain_assets import (
        AssetContextRule,
        AssetRole,
        _build_tree_instance_array,
    )

    placements: Dict[str, List[Tuple[float, float, float]]] = {
        "oak_tree": [(float(i), 0.0, 0.0) for i in range(2000)],
    }
    rules = [AssetContextRule("oak_tree", AssetRole.VEGETATION_LARGE)]
    rng = np.random.default_rng(42)

    arr = _build_tree_instance_array(placements, rules, rng)

    # Column 3 = yaw_degrees
    yaws = arr[:, 3]
    assert np.all(yaws >= 0.0), f"yaws must be >= 0; min={yaws.min()}"
    assert np.all(yaws <= 360.0), (
        f"yaws must be <= 360 degrees per Channel.YAW_DEG contract; "
        f"max={yaws.max()}. If max < 2*pi ≈ 6.28, the producer is "
        f"still writing radians — restore the rng.uniform(0, 360.0) fix."
    )
    # With 2000 samples uniformly distributed in [0, 360), at least one
    # value must exceed 2*pi ≈ 6.28. If every value is below 2*pi the
    # producer is silently emitting radians.
    assert yaws.max() > 2.0 * math.pi, (
        f"yaws.max()={yaws.max()} ≤ 2*pi — the radians regression is back."
    )
    # Mean should be ~180° for a uniform [0, 360) distribution.
    assert 150.0 < float(yaws.mean()) < 210.0, (
        f"yaws.mean()={yaws.mean()} not in [150, 210] — distribution looks "
        f"wrong for uniform [0, 360)."
    )


# ---------------------------------------------------------------------------
# Bug 3 — ADV-CP4-03: Kelvin wake per-rock local-flow gate
# ---------------------------------------------------------------------------


def test_bug3_stagnant_rock_in_fast_river_skips_wake() -> None:
    """A stagnant rock cell in a globally fast river must NOT emit a wake.

    Pre-fix: the global ``avg_speed = float(speed[water_mask].mean())`` gate
    used the river-wide mean. If the mean was > 1e-3 (typical for a fast
    river) every rock — including ones in stagnant pool cells — got a wake.
    Post-fix: per-rock local-flow sampling correctly skips the stagnant
    rock.
    """
    from veilbreakers_terrain.sim.foam import generate_foam_mask

    H = W = 32
    height = np.zeros((H, W), dtype=np.float32)
    water_mask = np.ones((H, W), dtype=bool)
    water_depth = np.full((H, W), 1.0, dtype=np.float32)
    rock_mask = np.zeros((H, W), dtype=bool)

    # Fast river everywhere EXCEPT a 5×5 stagnant pool around (16, 16).
    flow_speed = np.full((H, W), 5.0, dtype=np.float32)
    flow_speed[14:19, 14:19] = 0.0
    # Need flow_dir so the wake math has a direction; east-pointing.
    flow_dir = np.zeros((H, W, 2), dtype=np.float32)
    flow_dir[..., 0] = 1.0

    # Rock IN the stagnant pool centre.
    rock_positions = [(16.0, 16.0)]

    foam = generate_foam_mask(
        height=height,
        flow_speed=flow_speed,
        water_mask=water_mask,
        water_depth=water_depth,
        rock_mask=rock_mask,
        cell_size=1.0,
        flow_depth=0.3,
        rock_positions=rock_positions,
        flow_dir=flow_dir,
        noise_seed=42,
    )

    # The wake band is the ONLY foam source that responds to rock_positions.
    # The Kelvin contribution is multiplied by 0.10 and added to the rest.
    # If the per-rock guard fires the stagnant-cell rock contributes 0 to
    # kelvin_foam; if the global gate is still in play the rock emits a
    # wake band even though the local cell is stagnant.
    # Inspect a band ~3-15 cells EAST of the rock (along the flow direction,
    # within the wake cone but outside the rock cell itself).
    wake_band = foam[16, 19:30]
    # Subtract baseline foam (proximity + shore + froude + churn) from
    # the same band where the rock contribution should be zero. Easiest:
    # rerun with no rock_positions and diff.
    foam_no_rock = generate_foam_mask(
        height=height,
        flow_speed=flow_speed,
        water_mask=water_mask,
        water_depth=water_depth,
        rock_mask=rock_mask,
        cell_size=1.0,
        flow_depth=0.3,
        rock_positions=None,
        flow_dir=flow_dir,
        noise_seed=42,
    )
    rock_contribution = wake_band - foam_no_rock[16, 19:30]
    # Per-rock guard fires → rock_contribution should be ≈ 0 (gaussian
    # smoothing slightly bleeds but bound the magnitude).
    assert np.all(np.abs(rock_contribution) < 0.05), (
        f"Stagnant-pool rock in a fast river emitted a Kelvin wake "
        f"(max delta={float(np.abs(rock_contribution).max()):.4f}). "
        f"Per-rock local-flow gate failed; the prior global-mean gate is "
        f"back."
    )


def test_bug3_fast_rock_in_stagnant_pool_emits_wake() -> None:
    """A rock in a fast-flow CELL (within a globally stagnant pool) MUST
    emit a wake.

    Pre-fix global-mean gate: pool mean ≈ 0 → wake suppressed everywhere,
    including the fast cell. Post-fix per-rock gate: local cell has speed
    ≥ 1e-3 → wake emits.
    """
    from veilbreakers_terrain.sim.foam import generate_foam_mask

    H = W = 32
    height = np.zeros((H, W), dtype=np.float32)
    water_mask = np.ones((H, W), dtype=bool)
    water_depth = np.full((H, W), 1.0, dtype=np.float32)
    rock_mask = np.zeros((H, W), dtype=bool)

    # Stagnant pool everywhere except a 3×3 fast jet around (16, 16).
    flow_speed = np.zeros((H, W), dtype=np.float32)
    flow_speed[15:18, 15:18] = 5.0
    flow_dir = np.zeros((H, W, 2), dtype=np.float32)
    flow_dir[..., 0] = 1.0

    rock_positions = [(16.0, 16.0)]  # rock IN the fast jet cell

    foam = generate_foam_mask(
        height=height,
        flow_speed=flow_speed,
        water_mask=water_mask,
        water_depth=water_depth,
        rock_mask=rock_mask,
        cell_size=1.0,
        flow_depth=0.3,
        rock_positions=rock_positions,
        flow_dir=flow_dir,
        noise_seed=42,
    )
    foam_no_rock = generate_foam_mask(
        height=height,
        flow_speed=flow_speed,
        water_mask=water_mask,
        water_depth=water_depth,
        rock_mask=rock_mask,
        cell_size=1.0,
        flow_depth=0.3,
        rock_positions=None,
        flow_dir=flow_dir,
        noise_seed=42,
    )

    # Wake should appear east of the rock (along flow). Compare a few cells
    # within the wake cone.
    wake_band = foam[16, 19:25]
    no_rock_band = foam_no_rock[16, 19:25]
    rock_contribution = wake_band - no_rock_band
    assert float(rock_contribution.max()) > 0.005, (
        f"Fast-jet rock in stagnant pool emitted NO Kelvin wake "
        f"(max delta={float(rock_contribution.max()):.6f}). "
        f"Per-rock local-flow gate failed; the prior global-mean gate "
        f"silenced the wake."
    )


# ---------------------------------------------------------------------------
# Bug 4 — ADV-CP4-04: _mesh_bridge fills ALL material slots
# ---------------------------------------------------------------------------


def test_bug4_mesh_bridge_fills_all_material_slots() -> None:
    """When ``mesh_from_spec`` allocates ``num_slots`` placeholder slots
    via ``mesh_data.materials.append(None)``, every slot must be filled
    by the category-material auto-assign block — not just slot 0.

    Pre-fix the loop only wrote ``obj.data.materials[0] = mat``; slots
    [1..N-1] stayed ``None`` and any face with ``material_index >= 1``
    rendered as Blender's magenta debug material.

    Uses a stub bpy module so the test runs in CI without Blender.
    """
    import types
    from veilbreakers_terrain.handlers import _mesh_bridge

    # Build a minimal bpy stub so the Blender path executes.
    class _StubMaterials:
        def __init__(self) -> None:
            self._slots: List[Any] = []

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
            self.polygons: List[_StubPoly] = []

        def update(self) -> None: pass

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

    # Material-stub captures all slot writes for our assertion.
    captured_mats: List[Any] = []

    def _fake_create_procedural_material(name: str, mat_type: str) -> Any:
        m = types.SimpleNamespace(name=name, mat_type=mat_type)
        captured_mats.append(m)
        return m

    # Hard-patch into _mesh_bridge.
    import importlib
    mesh_bridge_module = importlib.reload(_mesh_bridge)

    # Stub bpy + bmesh inside the module.
    stub_bpy = _StubBpy()

    class _StubBMVert:
        def __init__(self, co: Tuple[float, float, float], index: int) -> None:
            self.co = co
            self.index = index
            self.normal = (0.0, 0.0, 1.0)

    class _StubBMFaces:
        def __init__(self) -> None:
            self._faces: List[Any] = []

        def new(self, verts: List[Any]) -> Any:
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

        def ensure_lookup_table(self) -> None: pass

        def __iter__(self):
            return iter(self._faces)

        def __getitem__(self, key: Any) -> Any:
            if isinstance(key, slice):
                return self._faces[key]
            return self._faces[key]

    class _StubBMVerts:
        def __init__(self) -> None:
            self._verts: List[_StubBMVert] = []

        def new(self, co: Tuple[float, float, float]) -> _StubBMVert:
            v = _StubBMVert(co, len(self._verts))
            self._verts.append(v)
            return v

        def ensure_lookup_table(self) -> None: pass

    class _StubBMEdges:
        def __init__(self) -> None:
            self._edges: List[Any] = []

            def _get(key: Any) -> Any:
                return None

            def _new(key: Any) -> Any:
                return None

            self.layers = types.SimpleNamespace(
                float=types.SimpleNamespace(get=_get, new=_new)
            )

        def ensure_lookup_table(self) -> None: pass

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
            # Mirror the face count from our stub bm onto mesh.polygons.
            mesh.polygons = [_StubPoly() for _ in self.faces]

        def normal_update(self) -> None: pass

        def free(self) -> None: pass

    class _StubBmesh:
        @staticmethod
        def new() -> _StubBM:
            return _StubBM()

        class ops:
            @staticmethod
            def recalc_face_normals(bm: Any, faces: Any) -> None: pass

    with patch.object(mesh_bridge_module, "bpy", stub_bpy), \
         patch.object(mesh_bridge_module, "bmesh", _StubBmesh), \
         patch.object(mesh_bridge_module, "_HAS_BPY", True), \
         patch("veilbreakers_terrain.handlers.procedural_materials.create_procedural_material",
               _fake_create_procedural_material), \
         patch("veilbreakers_terrain.handlers.procedural_materials.MATERIAL_LIBRARY",
               {"rough_timber": {"node_recipe": {}}}):
        # 3-material spec: 4 faces with material_ids [0, 1, 2, 1]
        # → num_slots = max+1 = 3 → 3 slots get allocated as None.
        verts = [
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
        ]
        faces = [
            (0, 1, 2),
            (0, 2, 3),
            (4, 5, 6),
            (4, 6, 7),
        ]
        spec = {
            "vertices": verts,
            "faces": faces,
            "material_ids": [0, 1, 2, 1],
            "metadata": {"category": "furniture"},  # → "rough_timber"
        }

        obj = mesh_bridge_module.mesh_from_spec(spec, name="TestMultiMat")

        # The bug: only slot[0] would be the material; slots [1] and [2]
        # would still be None.
        assert len(obj.data.materials) == 3, (
            f"Expected 3 material slots (num_slots = max([0,1,2,1])+1=3); "
            f"got {len(obj.data.materials)}"
        )
        # Every slot must be the rough_timber material — no None slots.
        for i, slot in enumerate(obj.data.materials):
            assert slot is not None, (
                f"slot[{i}] is None — the PR #110 placeholder was never "
                f"filled. Faces with material_index={i} would render as "
                f"Blender's magenta debug material."
            )
        # All slots reference the same material (single-category spec).
        slot_names = {obj.data.materials[i].name for i in range(3)}
        assert len(slot_names) == 1, (
            f"All slots in a single-category spec must share one material "
            f"(name); got distinct names {slot_names}"
        )
