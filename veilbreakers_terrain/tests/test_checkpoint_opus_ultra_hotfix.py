"""Regression tests for the CHECKPOINT-OPUS-ULTRA hotfix PR.

Closes 5 P0/P1 bugs found by the 7-reviewer comprehensive sweep documented
in ``project_checkpoint_opus_ultra_2026_05_20.md``:

* **REL-PR97-CASCADE-01** (P0) — ``procedural_meshes.py`` swallowed the new
  ``RuntimeError`` from PR #97's catenary loud-fail patch via a bare
  ``except Exception``, silently degrading to the sine sag fallback with
  no observability.
* **REL-PR102-USERVIS-01** (P0) — the CLI ``_generate_tile`` handler
  returned ``0`` unconditionally even when ``pipeline_status`` reported
  ``failed`` / ``no_passes_executed``. Operators and CI harnesses saw a
  green tile from a broken pipeline.
* **UT-C1** (P0) — ``Channel.STRATA_ORIENTATION_RAD`` and the parallel
  ``_CHANNEL_CANONICAL_UNITS["strata_orientation"]`` were both tagged
  ``"rad"``, but the producer writes (H, W, 3) direction-cosine vectors
  in [-1, 1]. Same Shape-A class as the prior ``flow_direction`` mistag.
* **ADV-01** (P1) — ``_mesh_bridge.mesh_from_spec`` silently skipped the
  per-face ``material_index`` assignment when ``bm.faces.new`` dropped
  degenerate / duplicate-vertex faces, leaving every face on slot 0 and
  reproducing the original PR #104 multi-material-as-single-material
  bug.
* **ADV-02** (P1) — ``_default_strat_stack_from_hints`` Mapping branch
  captured the user-supplied ``strike_angle_rad`` into a local but
  never threaded it into ``StratigraphyLayer(...)``, so the value was
  silently overwritten by ``__post_init__``'s derivation from
  ``azimuth_rad``. Sibling ``_layer_from_mapping`` had been fixed by
  T1-26; this path was missed.

Each test below fails on ``origin/main`` (pre-fix) and passes after the
hotfix lands.
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Bug 1 — REL-PR97-CASCADE-01: catenary RuntimeError must surface
# ---------------------------------------------------------------------------


def test_bug1_catenary_runtime_error_logged_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Forcing the catenary solver to raise ``RuntimeError`` must emit a
    logger warning and tag ``sag_solver`` as ``fallback_sine_after_solver_error``.

    Pre-fix: the bare ``except Exception`` clause swallowed the raise and
    tagged sag_solver as ``"fallback_sine"`` with zero log output — defeating
    PR #97's loud-fail intent.
    """
    import veilbreakers_terrain.procedural_meshes as pm
    from veilbreakers_terrain.sim import catenary as cat_mod

    def _raise_runtime(*_args: object, **_kwargs: object) -> np.ndarray:
        raise RuntimeError(
            "catenary brentq failed to bracket — synthetic failure for "
            "regression test"
        )

    monkeypatch.setattr(cat_mod, "catenary_with_sag", _raise_runtime)

    with caplog.at_level(logging.WARNING, logger=pm.__name__):
        spec = pm.generate_rope_bridge_mesh(style="simple")

    # Post-fix: sag_solver tag MUST distinguish "no sim deps" from
    # "solver actually failed". The ``_after_solver_error`` suffix is the
    # discriminator. ``sag_solver`` lands in spec["metadata"] via the
    # ``**extra_meta`` plumbing of ``_make_result``.
    sag_solver_tag = spec.get("metadata", {}).get("sag_solver")
    assert sag_solver_tag == "fallback_sine_after_solver_error", (
        f"Expected sag_solver='fallback_sine_after_solver_error' to flag "
        f"the swallowed RuntimeError surfaced via logger.warning; got "
        f"{sag_solver_tag!r}. Pre-fix the bare 'except Exception' "
        f"would have set sag_solver='fallback_sine' silently."
    )
    # And the warning must have hit the logger (proof we narrowed the
    # except clause and added the log call).
    assert any(
        "catenary solve failed" in rec.message.lower()
        or "catenary solve failed" in rec.getMessage().lower()
        for rec in caplog.records
    ), (
        f"No warning log surfaced for the RuntimeError. Pre-fix the "
        f"exception was swallowed without trace. caplog.records="
        f"{[(r.name, r.levelname, r.getMessage()) for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# Bug 2 — REL-PR102-USERVIS-01: CLI must exit non-zero on pipeline failure
# ---------------------------------------------------------------------------


def test_bug2_cli_exit_nonzero_when_pipeline_fails(tmp_path: Path) -> None:
    """When a registered pass raises, the CLI must return non-zero.

    We trigger a pipeline failure by injecting a sitecustomize.py into the
    subprocess CWD that monkeypatches ``TerrainPassController.run_pipeline``
    to return a single failed PassResult. The CLI must still write its
    forensic manifest but return exit-code 1.

    Pre-fix: the CLI returned 0 unconditionally, so a failing pipeline
    looked like a successful tile bake to make / CI / shell scripts.
    """
    out_dir = tmp_path / "bake"
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    # sitecustomize.py is imported automatically by every Python process
    # whose cwd or PYTHONPATH contains it. We use it to install a
    # fail-first stub for run_pipeline before the CLI imports it.
    site_customize = work_dir / "sitecustomize.py"
    site_customize.write_text(
        "from dataclasses import dataclass, field\n"
        "from typing import Any\n"
        "\n"
        "from veilbreakers_terrain.handlers import terrain_pipeline as tp\n"
        "\n"
        "@dataclass\n"
        "class _FailResult:\n"
        "    pass_name: str = 'pass_generate_low_freq_hmap'\n"
        "    status: str = 'failed'\n"
        "    duration_seconds: float = 0.0\n"
        "    metrics: dict = field(default_factory=dict)\n"
        "    seed_used: int = 0\n"
        "    content_hash_before: str = ''\n"
        "\n"
        "def _failing_run_pipeline(self, *args, **kwargs):\n"
        "    # Force terminal status = 'failed' so the CLI must return non-zero.\n"
        "    return [_FailResult()]\n"
        "\n"
        "tp.TerrainPassController.run_pipeline = _failing_run_pipeline\n",
        encoding="utf-8",
    )

    env = {
        **__import__("os").environ,
        "PYTHONPATH": str(work_dir) + str(__import__("os").pathsep)
        + __import__("os").environ.get("PYTHONPATH", ""),
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "veilbreakers_terrain.cli",
            "generate_tile",
            "--seed",
            "7",
            "--output-dir",
            str(out_dir),
            "--size",
            "16",
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    # Pre-fix: returncode was 0 regardless of pipeline_status.
    # Post-fix: returncode is non-zero when pipeline_status == 'failed'.
    assert completed.returncode != 0, (
        f"CLI returned 0 despite the orchestrator reporting a failed "
        f"pipeline. stdout={completed.stdout!r} stderr={completed.stderr!r}. "
        f"Pre-fix behaviour: unconditional `return 0` after manifest write."
    )

    # The forensic manifest should still exist so operators can debug.
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.is_file(), (
        "Forensic manifest.json must still be written on failure paths so "
        "operators can post-mortem the broken bake."
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["pipeline_status"] == "failed", (
        f"Manifest must record pipeline_status='failed' to discriminate "
        f"this case from a clean tile; got {manifest['pipeline_status']!r}."
    )


# ---------------------------------------------------------------------------
# Bug 3 — UT-C1: strata_orientation unit tag must agree across registries
# ---------------------------------------------------------------------------


def test_bug3_strata_orientation_unit_tags_agree_post_retag() -> None:
    """Channel.STRATA_ORIENTATION_XYZ must tag as ``unit_normal_xyz`` in
    BOTH the typed Channel registry AND the assertion-site canonical
    units map.

    Pre-fix: both registries said ``"rad"`` even though the producer
    writes (H, W, 3) direction-cosine vectors in [-1, 1] — silent
    Shape-A unit drift (same bug class Codex caught for flow_direction).
    """
    from veilbreakers_terrain.handlers._channels import Channel
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        _CHANNEL_CANONICAL_UNITS,
    )

    # The enum member must exist under the new name.
    assert hasattr(Channel, "STRATA_ORIENTATION_XYZ"), (
        "Channel.STRATA_ORIENTATION_XYZ enum member is missing. "
        "Hotfix renamed STRATA_ORIENTATION_RAD -> STRATA_ORIENTATION_XYZ "
        "because the producer writes 3D direction cosines, not radians."
    )

    # The old rad-tagged enum name should no longer be present.
    assert not hasattr(Channel, "STRATA_ORIENTATION_RAD"), (
        "Channel.STRATA_ORIENTATION_RAD still exists — the misleading "
        "rad-suffix enum name was not removed by the hotfix."
    )

    enum_unit = Channel.STRATA_ORIENTATION_XYZ.info.unit
    assert enum_unit == "unit_normal_xyz", (
        f"Channel.STRATA_ORIENTATION_XYZ.info.unit must be "
        f"'unit_normal_xyz' (matches producer), got {enum_unit!r}. "
        f"Pre-fix this was the silent 'rad' tag."
    )

    # The mask-stack field name (enum value) is unchanged for backwards
    # compatibility — callers still use stack.get('strata_orientation').
    assert Channel.STRATA_ORIENTATION_XYZ.value == "strata_orientation", (
        f"Enum value must remain 'strata_orientation' so consumer "
        f"stack.get(...) calls do not break. Got "
        f"{Channel.STRATA_ORIENTATION_XYZ.value!r}."
    )

    # The golden-snapshot assertion-site registry must match.
    canon_unit = _CHANNEL_CANONICAL_UNITS.get("strata_orientation")
    assert canon_unit == "unit_normal_xyz", (
        f"_CHANNEL_CANONICAL_UNITS['strata_orientation'] must be "
        f"'unit_normal_xyz' to mirror the Channel registry, got "
        f"{canon_unit!r}. Pre-fix this was the silent 'rad' tag — the "
        f"two registries disagreed with the producer for >1 release."
    )


# ---------------------------------------------------------------------------
# Bug 4 — ADV-01: mesh_from_spec must raise on per-face material_index mismatch
# ---------------------------------------------------------------------------


def test_bug4_mesh_bridge_raises_on_degenerate_face_material_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing a spec where ``len(material_ids) != surviving_face_count``
    must raise ``RuntimeError`` rather than silently dropping the per-face
    material_index assignment.

    The spec below has 2 declared faces, but the second face has three
    vertices that all dedup to the same welded vertex (so bm.faces.new
    would drop it as degenerate). Pre-fix: the post-bm length check at
    line ~1533 of ``_mesh_bridge.py`` silently skipped the assignment
    loop, leaving both faces on slot 0. Post-fix: the upfront degenerate-
    count gate raises RuntimeError.
    """
    from veilbreakers_terrain.handlers import _mesh_bridge as _mb

    # Force the headless path so we don't depend on a live Blender for the
    # validation pre-check. The new raise runs BEFORE the bpy split so
    # the headless path also triggers it.
    monkeypatch.setattr(_mb, "_HAS_BPY", False)

    # Two faces: the first is a real triangle, the second has three
    # vertices that all map to the same dedup key (within weld_tolerance)
    # so bm.faces.new would drop it as degenerate.
    spec: dict[str, Any] = {
        "vertices": [
            (0.0, 0.0, 0.0),  # face 0 vertex 0
            (1.0, 0.0, 0.0),  # face 0 vertex 1
            (0.0, 1.0, 0.0),  # face 0 vertex 2
            # Three vertices within weld_tolerance (5mm) of each other —
            # all dedup to the same key so the face collapses.
            (5.0, 5.0, 5.0),
            (5.0, 5.0, 5.0001),  # within 5mm
            (5.0001, 5.0, 5.0),  # within 5mm
        ],
        "faces": [
            [0, 1, 2],     # well-formed triangle
            [3, 4, 5],     # degenerate after dedup (single welded vertex)
        ],
        "material_ids": [0, 1],  # caller promises one id per face
    }

    with pytest.raises(RuntimeError, match=r"material_id count"):
        _mb.mesh_from_spec(spec)


# ---------------------------------------------------------------------------
# Bug 5 — ADV-02: strata_materials Mapping branch must thread user strike
# ---------------------------------------------------------------------------


def test_bug5_strata_materials_mapping_branch_preserves_user_strike() -> None:
    """A user-supplied ``strike_angle_rad`` in a ``strata_materials`` dict
    entry must flow into ``StratigraphyLayer.__post_init__`` where it is
    validated against the derived (azimuth+pi/2) value.

    With a deterministic RNG and a strike that disagrees with the derived
    value, post-fix raises ``ValueError`` from the StratigraphyLayer
    contradiction check. Pre-fix the user strike was silently discarded
    and __post_init__ derived from azimuth, so NO error fired and the
    user's geological intent vanished.

    This mirrors the existing T1-26 fix already in place on the sibling
    ``_layer_from_mapping`` (``stratigraphy_layers`` path); the
    ``strata_materials`` path was missed.
    """
    from veilbreakers_terrain.handlers.terrain_stratigraphy import (
        _default_strat_stack_from_hints,
    )

    # With np.random.default_rng(42) the RNG draw order is:
    #   draw1 -> legacy strike consume (was 'strike' pre-fix, now discarded)
    #   draw2 -> dip_noise in [-0.087, 0.087]
    #   draw3 -> azimuth in [0, 2*pi] -> derived_strike = azimuth + pi/2
    # We supply strike=1.5 which disagrees with derived_strike by >>5e-3
    # rad, so post-fix __post_init__ raises ValueError.
    rng = np.random.default_rng(42)

    hints: dict[str, object] = {
        "strata_materials": [
            {
                "name": "shale",
                "strike_angle_rad": 1.5,
                "azimuth_rad": 0.5,  # ignored — RNG overrides
                "thickness_m": 10.0,
            }
        ]
    }

    # Sanity-check the RNG sequence so the test is self-documenting. The
    # legacy ``draw1`` (range [0, pi]) used to be consumed as the strike
    # value and silently discarded; pinning the expected legacy value here
    # documents that the first draw lands inside ``[0, pi]`` and so could
    # never equal ``user_strike=1.5`` by accident — keeping the post-fix
    # contradiction check load-bearing.
    expected_legacy = float(np.random.default_rng(42).uniform(0.0, np.pi))
    assert 0.0 <= expected_legacy <= np.pi, (
        f"RNG draw1 (legacy strike consume) must be in [0, pi]; "
        f"got {expected_legacy}"
    )
    rng_replay = np.random.default_rng(42)
    _ = float(rng_replay.uniform(0.0, np.pi))           # draw1
    _ = float(rng_replay.uniform(-0.087, 0.087))         # draw2
    expected_azimuth = float(rng_replay.uniform(0.0, 2.0 * np.pi))
    expected_derived = (expected_azimuth + math.pi * 0.5) % (2.0 * math.pi)
    user_strike = 1.5
    # The supplied strike must differ from the derived value by >5e-3 rad
    # so __post_init__ definitely raises post-fix.
    diff = abs(user_strike - expected_derived)
    circular = min(diff, 2.0 * math.pi - diff)
    assert circular > 5.0e-3, (
        f"Test setup error: expected_derived={expected_derived} is too "
        f"close to user_strike={user_strike} (circular diff {circular} "
        f"rad). Pick a different strike so the contradiction check fires."
    )

    # Pre-fix: strike was set via _to_float(get('strike_angle_rad', 0.0))
    # and then DISCARDED (the layer was constructed without strike_angle_rad,
    # so __post_init__ derived from azimuth — no ValueError).
    # Post-fix: strike flows in -> __post_init__ sees contradiction -> raise.
    with pytest.raises(ValueError, match=r"strike_angle_rad"):
        _default_strat_stack_from_hints(hints, rng=rng)
