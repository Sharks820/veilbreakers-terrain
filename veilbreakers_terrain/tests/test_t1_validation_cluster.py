"""T1-validation-cluster regression tests (Y04 v3 PR-6, v2-ord 19).

Per ``docs/aaa-audit/2026_05_17_ultrafinal/MASTER_FINAL.md`` §B.4.8 (T1-10 +
T1-47) and §M.4 D-07 collapse table (T1-10 absorbs G-59 unreachable-raise and
F-ZZ3b9-02 ``pass_seasonal_water_state`` symptom). Per
``docs/aaa-audit/2026_05_17_ultrafinal/FIX_PATTERN_v1.md`` §C3, the failing-test-
first recipe applies: each test below was written so that it fails against the
pre-fix code (triple-bug + tuple-typed _VALID_STATUSES) and passes against the
post-fix code.

Three failure modes covered:

1. ``test_t1_10_seasonal_water_state_invalid_input_emits_canonical_issue``:
   Drives ``pass_seasonal_water_state`` with an invalid seasonal_state string
   so the ``except ValueError`` branch fires. Pre-fix this raised TypeError
   (unexpected kwarg ``channel``) before the warning could even land; post-fix
   it emits a properly-shaped ValidationIssue.

2. ``test_t1_10_validation_issue_canonical_field_set``:
   Asserts the structural canonical-field invariants. Pre-fix the seasonal-
   water_state call site assumed the wrong field name; post-fix all callers
   align with ``terrain_semantics.ValidationIssue``'s declared field surface.

3. ``test_t1_47_pass_result_valid_statuses_is_classvar_frozenset``:
   Asserts ``PassResult._VALID_STATUSES`` is a ``ClassVar[frozenset[str]]``
   class-level constant (not a dataclass instance field). Same assertion on
   ``ValidationIssue._VALID_SEVERITIES`` since the two share the migration.
"""
from __future__ import annotations

import time
import typing
from dataclasses import fields as dataclass_fields

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Shared minimal-state helper (mirrors test_terrain_water_variants_direct.py)
# ---------------------------------------------------------------------------


def _make_state_with_seasonal_hint(seasonal_state: str):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
        TerrainSceneRead,
    )

    sz = 16
    height = np.zeros((sz + 1, sz + 1), dtype=np.float64)
    stack = TerrainMaskStack(
        tile_size=sz,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    stack.set("wetness", np.zeros((sz + 1, sz + 1), dtype=np.float32), "test")
    stack.set(
        "water_surface_mask",
        np.zeros((sz + 1, sz + 1), dtype=np.float32),
        "test",
    )
    stack.set("tidal", np.zeros((sz + 1, sz + 1), dtype=np.float32), "test")

    region_bounds = BBox(0.0, 0.0, float(sz), float(sz))
    scene_read = TerrainSceneRead(
        timestamp=time.time(),
        major_landforms=("plain",),
        focal_point=(0.0, 0.0, 0.0),
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(),
        protected_zones_in_region=(),
        edit_scope=region_bounds,
        success_criteria=("test",),
        reviewer="pytest",
    )
    intent = TerrainIntentState(
        seed=1,
        region_bounds=region_bounds,
        tile_size=sz,
        cell_size=1.0,
        scene_read=scene_read,
        composition_hints={"seasonal_state": seasonal_state},
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# T1-10 — pass_seasonal_water_state triple-bug (γ3 D-07 absorbs G-59 + F-ZZ3b9-02)
# ---------------------------------------------------------------------------


def test_t1_10_seasonal_water_state_invalid_input_emits_canonical_issue() -> None:
    """Drive the previously-unreachable ValueError branch.

    Pre-fix: the ``except ValueError`` body constructed
    ``ValidationIssue(severity="warning", message=..., channel="wetness")`` which
    raised both ``TypeError`` (no ``channel`` kwarg on the dataclass) and
    ``ValueError`` (``"warning"`` not in ``_VALID_SEVERITIES``) AND was missing
    the required ``code`` argument. The bug was latent because the default
    seasonal_state="normal" never triggered the branch.

    Post-fix: an invalid seasonal_state value falls back to NORMAL and the pass
    emits a single canonical soft ValidationIssue.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import ValidationIssue
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        SeasonalState,
        pass_seasonal_water_state,
    )

    state = _make_state_with_seasonal_hint("not-a-season-xyz")
    result = pass_seasonal_water_state(state, None)

    # Pass falls back to NORMAL and still returns ok.
    assert result.status == "ok"
    assert result.metrics.get("seasonal_state") == SeasonalState.NORMAL.value
    # Exactly one validation issue describing the fallback.
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert isinstance(issue, ValidationIssue)
    # All four canonical contract points the audit called out:
    assert issue.code == "SEASONAL_STATE_UNKNOWN", "code must be non-empty (was missing pre-fix)"
    assert issue.severity == "soft", "severity must be in _VALID_SEVERITIES (was 'warning' pre-fix)"
    assert issue.affected_feature == "seasonal_water_state", (
        "field name must be `affected_feature` (was `channel` pre-fix)"
    )
    assert "not-a-season-xyz" in issue.message


def test_t1_10_validation_issue_canonical_field_set() -> None:
    """Lock the ValidationIssue dataclass surface so future drift trips a test.

    The triple-bug at pre-fix had three sub-causes that all reduced to the same
    structural error: the call site used a phantom field name (`channel`) that
    doesn't exist on the dataclass. This test asserts the canonical field set.
    Any addition / rename / removal must update this test deliberately.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import ValidationIssue

    field_names = {f.name for f in dataclass_fields(ValidationIssue)}
    # The five real fields:
    expected = {"code", "severity", "location", "affected_feature", "message", "remediation"}
    assert field_names == expected, (
        f"ValidationIssue dataclass field set drifted: {field_names ^ expected}"
    )
    # The class-level constant must NOT be a dataclass field anymore (T1-47).
    assert "_VALID_SEVERITIES" not in field_names, (
        "_VALID_SEVERITIES should be a ClassVar (T1-47), not a dataclass field"
    )
    # Phantom field names that prior call sites incorrectly used must NOT exist.
    assert "channel" not in field_names, (
        "phantom field `channel` reintroduced — would re-open F-ZZ3b9-02 channel-name-drift symptom"
    )

    # Constructing with the pre-fix kwargs MUST fail (TypeError + ValueError).
    with pytest.raises(TypeError):
        ValidationIssue(
            severity="warning",
            message="x",
            channel="wetness",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# T1-47 — _VALID_STATUSES / _VALID_SEVERITIES ClassVar conversion
# ---------------------------------------------------------------------------


def test_t1_47_pass_result_valid_statuses_is_classvar_frozenset() -> None:
    """Pyright-strict requires class-level constants on dataclasses to use ClassVar.

    Pre-fix: both attributes were declared as ``field(init=False, repr=False,
    compare=False, default=(...))`` — a tuple-typed runtime workaround that
    happened to work but registered as a regular dataclass field under strict
    typing. Post-fix: ``ClassVar[frozenset[str]]`` is the canonical form.

    The assertion checks (a) the runtime type is frozenset, (b) the value set
    is unchanged, and (c) the attribute is NOT enumerated as a dataclass field.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import (
        PassResult,
        ValidationIssue,
    )

    # PassResult side.
    assert isinstance(PassResult._VALID_STATUSES, frozenset), (
        "T1-47: _VALID_STATUSES must be a frozenset (was tuple-via-field pre-fix)"
    )
    assert PassResult._VALID_STATUSES == frozenset(
        {"ok", "warning", "failed", "skipped", "dry_run"}
    ), "value set must be preserved across the typing migration"
    pr_field_names = {f.name for f in dataclass_fields(PassResult)}
    assert "_VALID_STATUSES" not in pr_field_names, (
        "T1-47: _VALID_STATUSES leaked back into dataclass field set"
    )

    # ValidationIssue side — same migration, same invariants.
    assert isinstance(ValidationIssue._VALID_SEVERITIES, frozenset)
    assert ValidationIssue._VALID_SEVERITIES == frozenset({"hard", "soft", "info"})
    vi_field_names = {f.name for f in dataclass_fields(ValidationIssue)}
    assert "_VALID_SEVERITIES" not in vi_field_names

    # The annotation itself must resolve through typing.get_type_hints. We
    # include the extras so ClassVar survives the resolution. PassResult uses
    # forward references for the dataclass fields, so we must opt in to
    # `include_extras=True` for the ClassVar marker to survive.
    pr_hints = typing.get_type_hints(PassResult, include_extras=True)
    vi_hints = typing.get_type_hints(ValidationIssue, include_extras=True)
    # Both annotations should be present and resolve.
    assert "_VALID_STATUSES" in pr_hints
    assert "_VALID_SEVERITIES" in vi_hints
