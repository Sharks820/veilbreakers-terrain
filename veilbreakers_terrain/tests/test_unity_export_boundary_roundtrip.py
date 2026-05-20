"""T0.5-4 regression net — Boundary round-trip tests at the Unity export hop.

Y04 v3 §P.8.2 ord 0.5d: closes ZZ4-A6 R2 (Shape A export catch). The audit
identified three unit-drift hazards at the Python ↔ Unity boundary that
silently corrupt downstream gameplay:

1. **Tree yaw** — ``tree_instance_points[:, 3]`` exits the producer (label
   "yaw_degrees" per ``_write_tree_instance_points`` docstring), enters
   ``_tree_instances_json`` (label "yaw_degrees" at terrain_unity_export.py
   :3356), then re-enters the GPU foliage manifest as ``rotation_y_rad =
   np.radians(yaw_degrees)`` at :3398. The boundary contract is degrees
   at the JSON hop; rad-vs-deg drift here renders every wind-aligned tree
   rotating 57× less than authored.

2. **Animation rotation** — ``Keyframe.value`` is documented as radians
   for the "rotation" channel (animation_gaits.py:25-29), but Unity reads
   ``m_EulerCurves.value`` as degrees (Unity Animator spec). Today
   ``write_animation_clip_yaml`` passes the value through with no
   conversion — every animated rotation rotates 57× less than authored.

3. **Water depth meters** — ``water_depth_m`` channel must remain in
   meters at every Python-side touch and at the binary export. A drift
   to cm or world-unity-scaled meters here corrupts every water-physics
   gameplay zone.

These tests pin the contract at the boundary so any future drift is
loud-at-source rather than silent-at-Unity. Tests #1 and #2 are paired
with the production fix T0-4.5 — they are marked ``xfail(strict=True)``
where the production code is known to fail today, so:

- xfail today → green after T0-4.5 lands → strict-fail if T0-4.5 regresses.
- Per the S5+S6 patterns documented in
  ``docs/solutions/best-practices/regression-net-per-raise-path-xfail-strict-2026-05-19.md``.

Per FIX_PATTERN_v1.md §3 C4 (boundary contract) + §4 (test-first cascade
rule).
"""
from __future__ import annotations

import math
import re
import tempfile
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Test 1 — tree yaw round-trip at the JSON export hop
# ---------------------------------------------------------------------------


def test_tree_yaw_degrees_round_trip_through_json_export() -> None:
    """The ``yaw_degrees`` field in ``_tree_instances_json`` must echo the
    input column 3 unchanged.

    Contract: ``tree_instance_points[:, 3]`` is degrees per the producer
    docstring; the export passes it through as the ``yaw_degrees`` JSON
    field. Any silent unit conversion at the export hop (e.g. an accidental
    ``math.degrees(...)`` or ``np.radians(...)`` insertion) breaks this
    contract and Unity reads the wrong value.

    NOTE: this test pins the JSON-hop contract independent of the upstream
    producer's actual units. A separate T0-4.5 fix corrects the producer
    if it is currently writing radians (audit ZZ3-NEW-P0-01); this test
    catches drift at the EXPORT hop regardless.
    """
    from veilbreakers_terrain.handlers.terrain_unity_export import (
        _tree_instances_json,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    # Build a stack with known yaw_degrees values at four cardinal angles
    # plus one off-axis value to catch any sign / wrap bug.
    yaws_in_degrees = np.array([0.0, 90.0, 180.0, 270.0, 47.5], dtype=np.float32)
    # tree_instance_points shape: (N, 5) = (x, y, z, yaw_degrees, prototype_id)
    n = len(yaws_in_degrees)
    tree_points = np.zeros((n, 5), dtype=np.float32)
    tree_points[:, 0] = np.arange(n, dtype=np.float32) * 2.0  # x = 0, 2, 4, ...
    tree_points[:, 1] = 0.0  # y = 0
    tree_points[:, 2] = 0.0  # z = 0
    tree_points[:, 3] = yaws_in_degrees
    tree_points[:, 4] = 0.0  # prototype_id = 0

    stack = TerrainMaskStack(
        tile_size=8,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((9, 9), dtype=np.float64),
    )
    stack.set("tree_instance_points", tree_points, "test_fixture")

    result = _tree_instances_json(stack)
    trees = result["trees"]

    assert len(trees) == n, (
        f"_tree_instances_json must yield one tree per input row; "
        f"got {len(trees)} for n={n}"
    )
    for i, expected_deg in enumerate(yaws_in_degrees):
        actual = float(trees[i]["yaw_degrees"])
        assert actual == pytest.approx(float(expected_deg), abs=1e-5), (
            f"tree[{i}].yaw_degrees: expected {expected_deg!r} (degrees), "
            f"got {actual!r}. Boundary contract: degrees in → degrees out. "
            f"A 57× mismatch ({float(expected_deg) / max(actual, 1e-9):.2f}×) "
            f"indicates a rad↔deg conversion bug at the export hop."
        )


# ---------------------------------------------------------------------------
# Test 2 — animation rotation rad→deg at the YAML export hop
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "T0-4.5 not yet landed — write_animation_clip_yaml passes Keyframe.value "
        "through unchanged but Unity reads m_EulerCurves.value as degrees. "
        "Keyframe.value is documented as radians for the rotation channel "
        "(animation_gaits.py:25-29). Today every animated rotation rotates "
        "57× less than authored. Once T0-4.5 inserts math.degrees() at the "
        "rotation-channel write path, this xfail flips to xpass→fail and "
        "this decorator must be removed."
    ),
)
def test_animation_rotation_yaml_value_field_is_degrees() -> None:
    """The Unity ``m_EulerCurves.value`` field must contain degrees.

    ``Keyframe.value`` is documented as radians for ``channel="rotation"``.
    Unity Animator's ``m_EulerCurves`` field is degrees. The boundary
    conversion must happen inside ``write_animation_clip_yaml`` — but it
    does NOT today (audit ZZ3-NEW-P0-02).

    This test pins the post-T0-4.5 contract: rotation Keyframe at
    value=π/2 rad must write value ≈ 90.0 in m_EulerCurves.
    """
    from veilbreakers_terrain.handlers.animation_gaits import Keyframe
    from veilbreakers_terrain.handlers.terrain_unity_export import (
        write_animation_clip_yaml,
    )

    # Keyframe at π/2 radians = 90 degrees. If conversion is correct, the
    # m_EulerCurves YAML line will say `value: 90` (or 90.0 / 9e+01). If
    # conversion is missing (today), it will say `value: 1.5707963...`.
    kf = Keyframe(
        frame=0,
        value=math.pi / 2.0,  # radians
        channel="rotation",
        axis=1,  # Y-axis
        bone_name="root",
        time=0.0,
        in_tangent=0.0,
        out_tangent=0.0,
    )

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "test_clip.anim"
        write_animation_clip_yaml([kf], out_path)
        yaml_text = out_path.read_text(encoding="utf-8")

    # Find the m_EulerCurves block and the first numeric value.
    m_euler_idx = yaml_text.find("m_EulerCurves:")
    assert m_euler_idx >= 0, (
        f"expected m_EulerCurves: section in YAML; got:\n{yaml_text}"
    )
    after_euler = yaml_text[m_euler_idx:]
    # The first `value: <float>` line inside m_EulerCurves.
    value_match = re.search(r"value:\s*([-\d.eE+]+)", after_euler)
    assert value_match, (
        f"expected `value: <number>` line in m_EulerCurves section; got:\n"
        f"{after_euler[:500]}"
    )
    actual_value = float(value_match.group(1))

    # Unity contract: m_EulerCurves.value is in degrees.
    # math.pi / 2.0 rad = 90.0 degrees.
    assert actual_value == pytest.approx(90.0, abs=1e-3), (
        f"m_EulerCurves.value: expected 90.0 (degrees, from π/2 rad input), "
        f"got {actual_value!r}. "
        f"If value ≈ 1.5708, the rad→deg conversion is missing at "
        f"write_animation_clip_yaml — this is T0-4.5 ZZ3-NEW-P0-02."
    )


# ---------------------------------------------------------------------------
# Test 3 — water_depth_m unit preservation at the manifest hop
# ---------------------------------------------------------------------------


def test_water_depth_file_naming_preserves_meters_unit() -> None:
    """The Unity manifest's water_depth_file field must reference a `*_m.bin`
    filename — the `_m` suffix is the canonical unit declaration at the
    binary export hop.

    Contract: water_depth values are meters in Python (channel name
    ``water_depth_m``). The binary export must preserve the `_m` suffix
    in the manifest filename so downstream Unity importers know to treat
    the f32 raw values as meters, not centimetres or world-Unity scale.

    This is a static contract test — it does not require running a full
    bake. The single string `water_depth_m.bin` is hard-coded in
    terrain_unity_export.py:1752 and any silent rename (e.g. to
    ``water_depth.bin`` or ``water_depth_cm.bin``) would break the
    importer-side unit assumption.
    """
    # Read the source directly and assert the canonical filename literal.
    src_path = (
        Path(__file__).resolve().parent.parent
        / "handlers"
        / "terrain_unity_export.py"
    )
    src = src_path.read_text(encoding="utf-8")

    # The export must emit a manifest field named `water_depth_file` that
    # references a `water_depth_m.bin` filename. Both halves are required.
    assert '"water_depth_file"' in src or "'water_depth_file'" in src, (
        "manifest must have a `water_depth_file` field — name appears to "
        "have been renamed; investigate before downstream Unity consumers "
        "break."
    )
    assert "water_depth_m.bin" in src, (
        "manifest must reference `water_depth_m.bin` (with `_m` suffix) "
        "so Unity importers know the values are meters. A rename to "
        "`water_depth.bin` or `water_depth_cm.bin` would silently corrupt "
        "every water-physics gameplay zone — this is T0.5-4 contract."
    )

    # Confirm no alternative unit-suffix variants leaked in via a stale
    # copy-paste or refactor.
    forbidden_variants = (
        "water_depth_cm.bin",
        "water_depth_mm.bin",
        "water_depth_world_units.bin",
    )
    for variant in forbidden_variants:
        assert variant not in src, (
            f"forbidden unit-drift variant {variant!r} found in "
            f"terrain_unity_export.py — meters is the canonical unit; "
            f"all other suffixes are unit-drift hazards per ZZ4-A6 R2."
        )
