"""Canonical pass-name constants for the terrain pipeline.

Promoted from a duplicated literal in ``environment._execute_terrain_pipeline``
per CHECKPOINT-OPUS-ULTRA V8 architectural finding (2026-05-20).

Round-2 (CE adversarial verifier follow-up): the V8 finding's framing was
factually wrong about ``cli.py``. PR #102 (T0-2 CLI rewire) introduced a
third literal copy of the prewarm-shaped sequence at ``cli.py:153-160``
AFTER the original V8 audit was written. That literal is consumed as the
ACTUAL runtime pipeline by ``TerrainPassController.run_pipeline`` (not just
registry pre-warm), so stale entries there cause real correctness drift,
not just slow registrar loads. ``DEFAULT_CLI_PASS_SEQUENCE`` below extracts
that third copy into the same single-source-of-truth file.

Background
----------
Prior to this module, ``environment.py`` carried a 6-entry literal list inside
``_execute_terrain_pipeline`` that mirrored a *subset* of the canonical pass
sequence produced by :func:`terrain_pipeline.build_default_pass_sequence`.
The literal was used to pre-warm the pass registry by name BEFORE
``TerrainIntentState`` is constructed (registry must be loaded so the later
``build_default_pass_sequence(intent)`` call resolves cleanly).

This drift surface had two failure modes:

1. Add a new pass to ``build_default_pass_sequence`` → forget to add it to
   the environment.py literal → the new pass is missing from the
   registration pre-warm and silently degrades to a ``UnknownPassError``
   on a fresh process.
2. Rename a canonical pass → ``build_default_pass_sequence`` updates, the
   environment.py literal does not → registration pre-warm tries to look
   up a stale name and forces a registrar load it would otherwise skip.

The constants below are now the SINGLE SOURCE OF TRUTH for the registration
pre-warm. A regression test
(``tests/test_default_pass_sequences.py``) pins that this minimal cover
remains a strict subset of whatever ``build_default_pass_sequence`` emits
for both AAA and preview quality profiles.

Public API
----------
``DEFAULT_REGISTRATION_PREWARM`` — frozen tuple of pass names that the
headless ``_execute_terrain_pipeline`` callers use to ensure the pass
registry is populated before intent construction. Strict subset of
:func:`build_default_pass_sequence` output across all quality profiles.

``DEFAULT_REGISTRATION_PREWARM_SCENE_READ`` — additional passes appended
when a ``scene_read`` is supplied. These are the hydrology/erosion passes
``build_default_pass_sequence`` injects at index 3 when
``has_scene_read`` is true.

``DEFAULT_CLI_PASS_SEQUENCE`` — the canonical pass list executed by
``veilbreakers_terrain.cli._run_real_pipeline_for_cli``. Unlike the
``DEFAULT_REGISTRATION_PREWARM`` constants above, this tuple drives the
actual runtime pipeline that the CLI feeds to
``TerrainPassController.run_pipeline``. It is byte-equivalent to
``build_registration_prewarm(quality_profile="preview", has_scene_read=False)``
today; the separate named constant exists so future divergence between
the CLI pipeline and the headless prewarm cannot silently desync, and so
``cli.py`` does not need to import the prewarm builder (which would mix
the runtime-pipeline contract with the registrar-warming contract).
"""
from __future__ import annotations

# Import the canonical preview-quality-profile frozenset rather than
# re-implementing the ("preview", "mobile", "low") tuple inline. The
# import is intentionally lazy/string-name to avoid any chance of a
# circular import even though ``terrain_pipeline`` does not currently
# depend on this module — keeping the dependency arrow one-way.
from .terrain_pipeline import PREVIEW_QUALITY_PROFILES

# The canonical 5-pass minimal pre-warm cover for headless registration.
# ``build_registration_prewarm`` appends one validation pass to this set
# (plus the hydrology/erosion pair when a scene_read is attached); the
# 6-pass cli list below extends from the same base.
# MUST be a strict subset of build_default_pass_sequence(intent) output for
# every supported quality_profile. Pinned by
# tests/test_default_pass_sequences.py.
#
# Adding a new pass here does NOT add it to the pipeline run — the actual
# pipeline is always derived from build_default_pass_sequence(intent) (or
# from an explicit caller-supplied params['pipeline']).
DEFAULT_REGISTRATION_PREWARM: tuple[str, ...] = (
    "pass_generate_low_freq_hmap",
    "terrain_labels",
    "structural_masks",
    "pass_generate_high_freq_detail",
    "pass_composite_hmap",
)

# Extra passes appended when scene_read is supplied. build_default_pass_sequence
# inserts these at index 3 via ``pass_sequence[3:3] = ["pass_hydrology", "erosion"]``
# when has_scene_read is true.
DEFAULT_REGISTRATION_PREWARM_SCENE_READ: tuple[str, ...] = (
    "pass_hydrology",
    "erosion",
)

# Canonical pass list executed by ``veilbreakers_terrain.cli._run_real_pipeline_for_cli``.
# This IS the runtime pipeline for ``vbterrain bake-tile`` style invocations
# (mode of T0-2 CLI rewire, PR #102) — not just pre-warm. Stale entries here
# cause real heightmap/splatmap output divergence, so it lives in the same
# single-source-of-truth file as the prewarm constants.
#
# Equivalent today to ``build_registration_prewarm(quality_profile="preview",
# has_scene_read=False)``; the separate named tuple keeps the CLI contract
# decoupled from the registrar-warming contract so each can evolve
# independently if needed. Regression-tested for byte-equivalence in
# tests/test_default_pass_sequences.py.
DEFAULT_CLI_PASS_SEQUENCE: tuple[str, ...] = (
    "pass_generate_low_freq_hmap",
    "terrain_labels",
    "structural_masks",
    "pass_generate_high_freq_detail",
    "pass_composite_hmap",
    "validation_minimal",
)


def build_registration_prewarm(
    *,
    quality_profile: str,
    has_scene_read: bool,
) -> tuple[str, ...]:
    """Return the registration pre-warm pass list for a given configuration.

    This is what ``environment._execute_terrain_pipeline`` uses to ensure
    the pass registry contains every name it might need *before* building
    ``TerrainIntentState`` (and thus before it can call the canonical
    :func:`terrain_pipeline.build_default_pass_sequence` itself).

    Parameters
    ----------
    quality_profile:
        Quality profile string (``"aaa_open_world"``, ``"preview"``,
        ``"mobile"``, ``"low"``). Determines which validation pass is
        appended (``validation_minimal`` for preview-tier, otherwise
        ``validation_full``).
    has_scene_read:
        Whether the call supplies a ``scene_read`` payload. When true,
        the hydrology/erosion passes are also included so they are
        registration-resolved up front.

    Returns
    -------
    tuple[str, ...]
        Pass names to pre-warm in the registry. Order is illustrative —
        the actual run order is determined by
        :func:`terrain_pipeline.build_default_pass_sequence`.
    """
    is_preview = quality_profile in PREVIEW_QUALITY_PROFILES
    validation_pass = "validation_minimal" if is_preview else "validation_full"
    out: list[str] = list(DEFAULT_REGISTRATION_PREWARM)
    if has_scene_read:
        # Same insertion index as build_default_pass_sequence's
        # ``pass_sequence[3:3] = ["pass_hydrology", "erosion"]`` so the
        # pre-warm shape mirrors the canonical builder.
        out[3:3] = list(DEFAULT_REGISTRATION_PREWARM_SCENE_READ)
    out.append(validation_pass)
    return tuple(out)
