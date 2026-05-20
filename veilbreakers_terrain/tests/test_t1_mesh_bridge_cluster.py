"""Regression tests for the T1-mesh-bridge cluster (T1-15, T1-20).

**T1-15** — ``_mesh_bridge.py:1393-1416`` material-id slot count formula.

Origin: ``S12-P1-18`` ⇄ X03 PROMOTE to P0-cert. Bundled in PR-12 per Y04 v3.

The previous code used ``len(set(material_ids))`` (unique-count), which is
wrong whenever the upstream material-id set is **non-contiguous**:

* ``[0, 2, 2, 2]`` -> ``len(set) = 2``, but Unity allocates 3 dense slots
  (indices 0, 1, 2). Reporting 2 slots means face references to id=2 are
  treated as out-of-range OR silently shifted to slot 1 on the Unity side.
* ``[0, 0, 0, 5]`` -> ``len(set) = 2``, but Unity allocates 6 dense slots.
  Reporting 2 slots rejects every face referencing id=5 as out-of-range, even
  though the asset is well-formed.

The fix uses ``max(material_ids) + 1`` (the AAA-standard formula used by
Maya, Blender, and Houdini; matches the dense indexing used by Unity's
``Mesh.subMeshCount`` + ``MeshRenderer.sharedMaterials[]`` arrays).

FIX_PATTERN_v1 §C5 — Numerical / unit conversion category.

**T1-20** — bmesh try/finally remainder.

Per Y04 v3 the audit explicitly states that "Most of T1-20 absorbed into
T0-3.5" (MASTER_FINAL.md:2108). PR #94 (``b12550eb``) wrapped all 22+
``bmesh.new()`` sites in handlers, including the single site at
``_mesh_bridge.py:1419``. T1-20's remainder for the mesh bridge is therefore
**empty** at this commit, but we keep a sentinel test below that fails if a
new ``bmesh.new()`` site lands in ``_mesh_bridge.py`` without try/finally —
defending the same invariant T0-3.5 defends for the rest of handlers/.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from veilbreakers_terrain.handlers._mesh_bridge import mesh_from_spec


# ---------------------------------------------------------------------------
# T1-15 — material-id slot count formula
# ---------------------------------------------------------------------------


def _spec(material_ids: list[int]) -> dict[str, Any]:
    """Build a minimal MeshSpec dict with `len(material_ids)` faces.

    Each face is a triangle on three fresh vertices, so face count == len(ids)
    regardless of dedup. The non-Blender fallback path in mesh_from_spec
    returns a dict containing the slot count and is therefore the right
    surface to test without spinning Blender.
    """
    n_faces = len(material_ids)
    verts: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    for i in range(n_faces):
        base = i * 3
        # Spread vertices in x so dedup never collapses them.
        verts.extend([
            (float(base + 0), 0.0, 0.0),
            (float(base + 1), 1.0, 0.0),
            (float(base + 2), 0.0, 1.0),
        ])
        faces.append([base + 0, base + 1, base + 2])
    return {"vertices": verts, "faces": faces, "material_ids": material_ids}


@pytest.mark.parametrize(
    ("material_ids", "expected_slots"),
    [
        # Contiguous from 0 — both old and new formulae agree.
        ([0, 0, 0], 1),
        ([0, 1], 2),
        ([0, 1, 2, 1, 0], 3),
        # Non-contiguous — T1-15 anchor cases from MASTER_FINAL.md:2077.
        ([0, 2, 2, 2], 3),     # OLD reported 2 (false positive)
        ([0, 0, 0, 5], 6),     # OLD reported 2 (false negative)
        # Single high index — degenerate but legal (e.g. Tripo asset using
        # slot 9 only because slots 0-8 are reserved by a downstream atlas).
        ([9], 10),
        # Repeated high index — every face on same high slot.
        ([7, 7, 7], 8),
    ],
)
def test_t1_15_material_slot_count_uses_max_plus_one(
    material_ids: list[int], expected_slots: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """material_slot_count is max(material_ids)+1, not len(set(material_ids))."""
    # T1-15 round-3: the CI conftest installs a bpy stub which makes
    # `_HAS_BPY = True` (the module-level try/import succeeds against
    # the stub). Force the headless fallback path explicitly so the
    # dict-return contract is what we exercise.
    from veilbreakers_terrain.handlers import _mesh_bridge as _mb
    monkeypatch.setattr(_mb, "_HAS_BPY", False)

    result = mesh_from_spec(_spec(material_ids))
    assert isinstance(result, dict), (
        "Test must run on the headless fallback path; got Blender object instead."
    )
    assert result["material_slot_count"] == expected_slots, (
        f"For material_ids={material_ids}, expected {expected_slots} slots "
        f"(max+1) but got {result['material_slot_count']}. The pre-fix formula "
        f"len(set(material_ids)) would have returned "
        f"{len(set(material_ids))}."
    )


def test_t1_15_negative_material_id_rejected() -> None:
    """Negative material_ids raise ValueError before reaching max+1.

    Without this guard, a stray negative id could synthesise an artificially
    small slot count (because max() ignores the negative) and silently pass
    through to Blender / Unity where it would crash or paint wrong materials.
    """
    spec = _spec([0, -1, 1])
    with pytest.raises(ValueError, match=r"material_id .* is negative"):
        mesh_from_spec(spec)


def test_t1_15_empty_material_ids_defaults_to_one_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty material_ids list yields num_slots == 1 (single default material).

    Regression: ensures the `else: num_slots = 1` branch survived the
    T1-15 refactor that removed the now-unreachable range-check loop.
    """
    from veilbreakers_terrain.handlers import _mesh_bridge as _mb
    monkeypatch.setattr(_mb, "_HAS_BPY", False)
    spec = _spec([])
    # _spec([]) builds zero faces — give it one face manually.
    spec["faces"] = [[0, 1, 2]]
    spec["vertices"] = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    result = mesh_from_spec(spec)
    assert isinstance(result, dict)
    assert result["material_slot_count"] == 1


# ---------------------------------------------------------------------------
# T1-20 — bmesh try/finally sentinel for _mesh_bridge.py
# ---------------------------------------------------------------------------


_MESH_BRIDGE = (
    Path(__file__).resolve().parents[1] / "handlers" / "_mesh_bridge.py"
)


def _count_bmesh_new_sites(source: str) -> int:
    """Count `bmesh.new()` (or `_bmesh.new()`) call expressions in source."""
    tree = ast.parse(source)
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "new"
            and isinstance(func.value, ast.Name)
            and func.value.id in {"bmesh", "_bmesh"}
        ):
            count += 1
    return count


def _bmesh_new_sites_with_try_finally_free(source: str) -> tuple[int, int]:
    """Return (total_sites, properly_wrapped_sites).

    "Properly wrapped" means the bmesh.new() assignment is followed in the
    same body by a Try node whose finalbody calls <var>.free(). Mirrors the
    T0-3.5 AST regression net's check, scoped to a single file.
    """
    tree = ast.parse(source)

    def _walk_body(body: list[ast.stmt]) -> tuple[int, int]:
        total = 0
        wrapped = 0
        for i, stmt in enumerate(body):
            # Look for `var = bmesh.new()` assignment.
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr == "new"
                and isinstance(stmt.value.func.value, ast.Name)
                and stmt.value.func.value.id in {"bmesh", "_bmesh"}
            ):
                total += 1
                var_name = stmt.targets[0].id
                # Next stmt must be a Try whose finally calls var.free().
                next_stmt: ast.stmt | None = body[i + 1] if i + 1 < len(body) else None
                if isinstance(next_stmt, ast.Try):
                    for fstmt in next_stmt.finalbody:
                        if (
                            isinstance(fstmt, ast.Expr)
                            and isinstance(fstmt.value, ast.Call)
                            and isinstance(fstmt.value.func, ast.Attribute)
                            and fstmt.value.func.attr == "free"
                            and isinstance(fstmt.value.func.value, ast.Name)
                            and fstmt.value.func.value.id == var_name
                        ):
                            wrapped += 1
                            break
            # Recurse into nested bodies (function defs, ifs, fors, etc.).
            for child_attr in ("body", "orelse", "finalbody", "handlers"):
                child = getattr(stmt, child_attr, None)
                if isinstance(child, list):
                    sub_total, sub_wrapped = _walk_body(child)
                    total += sub_total
                    wrapped += sub_wrapped
            # ExceptHandler bodies are reached via .handlers above.
        return total, wrapped

    return _walk_body(tree.body)


def test_t1_20_mesh_bridge_bmesh_sites_have_try_finally() -> None:
    """Every bmesh.new() in _mesh_bridge.py is wrapped in try/finally bm.free().

    Per Y04 v3 (MASTER_FINAL.md:2093-2108) T1-20 was absorbed into T0-3.5
    (PR #94). This test pins the invariant for the mesh-bridge file
    specifically so any new bmesh.new() landing here in the future must
    follow the same discipline.
    """
    source = _MESH_BRIDGE.read_text(encoding="utf-8")
    total = _count_bmesh_new_sites(source)
    counted, wrapped = _bmesh_new_sites_with_try_finally_free(source)
    # Sanity: counted (top-level walk) should equal total (full AST walk).
    assert counted == total, (
        f"AST walkers disagree on bmesh.new() count: {counted} vs {total}"
    )
    assert wrapped == total, (
        f"_mesh_bridge.py has {total} bmesh.new() site(s) but only {wrapped} "
        f"are wrapped in try/finally bm.free(). T1-20 invariant broken."
    )
    # Headline-count sentinel. T0-3.5 (PR #94) leaves exactly one site here
    # at line 1419 (the mesh_from_spec body). If a new site lands, update
    # this number AFTER confirming the new site is correctly wrapped.
    assert total == 1, (
        f"_mesh_bridge.py expected exactly 1 bmesh.new() site (T0-3.5 / PR #94 "
        f"baseline) but found {total}. If a new site is intentional, bump "
        f"this assertion and verify try/finally bm.free() coverage above."
    )


# ---------------------------------------------------------------------------
# ADV-PR104-01 (CHECKPOINT-2 hotfix) — Blender path must consume num_slots
# ---------------------------------------------------------------------------


def test_adv_pr104_01_blender_path_allocates_slots_and_assigns_material_index() -> None:
    """The Blender path in mesh_from_spec must consume num_slots end-to-end.

    ADV-PR104-01: PR #104 fixed ``num_slots = max(material_ids) + 1`` but
    the Blender branch never read ``num_slots`` and never assigned
    ``face.material_index``. Multi-material specs rendered as a single
    category-mapped slot 0, silently collapsing slot information that the
    headless-fallback dict surfaced correctly. PR #104's fix was dead code
    in the path that actually runs in Blender.

    A full Blender integration test would require a richer bpy stub than
    the project conftest provides today. Per the hotfix spec, this is a
    source-level sentinel: it asserts the two patterns added by the hotfix
    are present in the Blender branch so a future refactor that removes
    them lights up CI immediately.

    Patterns asserted:
    * ``mesh_data.materials.append(None)`` — placeholder-slot allocation
      driven by ``num_slots`` so downstream consumers see the right count.
    * ``poly.material_index = int(mid)`` — per-face id assignment so each
      face actually paints the slot the spec intended.
    """
    source = _MESH_BRIDGE.read_text(encoding="utf-8")

    assert "mesh_data.materials.append(None)" in source, (
        "_mesh_bridge.py Blender path is missing "
        "`mesh_data.materials.append(None)` slot allocation "
        "(ADV-PR104-01 hotfix regression — num_slots is dead code again)"
    )
    assert "poly.material_index = int(mid)" in source, (
        "_mesh_bridge.py Blender path is missing "
        "`poly.material_index = int(mid)` per-face assignment "
        "(ADV-PR104-01 hotfix regression — multi-material specs collapse)"
    )

    # Pin the order: the slot allocation must come BEFORE the per-face
    # assignment (you can't set material_index on a slot that hasn't been
    # appended yet — Blender silently clamps to len(materials)-1).
    alloc_idx = source.index("mesh_data.materials.append(None)")
    assign_idx = source.index("poly.material_index = int(mid)")
    assert alloc_idx < assign_idx, (
        "Slot allocation must precede per-face material_index assignment "
        "(Blender clamps material_index to len(materials)-1 otherwise)"
    )


def test_adv_pr104_01_headless_fallback_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headless fallback dict path still reports num_slots correctly.

    Belt-and-braces: this re-asserts the PR-104 invariant on the path that
    PR-104 originally fixed, to confirm the hotfix did not regress the
    fallback contract that downstream tooling relies on for CI.
    """
    from veilbreakers_terrain.handlers import _mesh_bridge as _mb

    monkeypatch.setattr(_mb, "_HAS_BPY", False)
    spec = _spec([0, 5, 5, 5])  # max+1 = 6, len(set) = 2
    result = mesh_from_spec(spec)
    assert isinstance(result, dict)
    assert result["material_slot_count"] == 6, (
        "Headless fallback num_slots must remain max(material_ids)+1=6 "
        "after ADV-PR104-01 hotfix (PR #104 contract preserved)"
    )
