"""TerrainPassController — the atomic pass orchestrator.

Bundle A — Foundation. Every terrain mutation routes through here.
See docs/terrain_ultra_implementation_plan_2026-04-08.md §5.10, §5.11, §5.12, §6.

Responsibilities
----------------
- Register passes via ``TerrainPassController.register_pass(PassDefinition)``
- Run a single pass or an ordered pipeline
- Enforce scene-read before mutation (passes that require it)
- Enforce protected-zone policy per pass
- Derive deterministic per-pass seeds
- Emit checkpoints after successful passes
- Rollback to any prior checkpoint

NO Blender imports. Pure Python + numpy so the controller can be unit-tested.
Blender geometry snapshots are handled by ``handle_run_terrain_pass`` on the
Blender side of the TCP bridge.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import time
import uuid
import dataclasses
import weakref
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .terrain_io import assert_finite_array
from .terrain_semantics import (
    BBox,
    ChannelOwnershipError,
    PassContractError,
    PassDefinition,
    PassResult,
    ProtectedZoneViolation,
    SceneReadRequired,
    TerrainCheckpoint,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
    UnknownPassError,
    ValidationIssue,
)

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level weak registry for hot-reload func rebinding (FIX-B14-23)
# ---------------------------------------------------------------------------
# Maps (module_name, attr_name) -> PassDefinition so that after
# importlib.reload() the hot-reload code can iterate this dict and re-bind
# PassDefinition.func without re-registering the whole pipeline.
#
# WeakValueDictionary is used so that PassDefinitions that are dropped from
# the PASS_REGISTRY (e.g. test teardown clears the class-level dict) do not
# accumulate here indefinitely.
_PASS_MODULE_REGISTRY: "weakref.WeakValueDictionary[Tuple[str, str], PassDefinition]" = (
    weakref.WeakValueDictionary()
)


class PipelineSubsystemError(RuntimeError):
    """Raised when a non-recoverable pipeline subsystem call fails (FIX-1.2)."""


def _make_gate_issue(code: str, severity: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, severity=severity, message=message)


_PREVIEW_QUALITY_PROFILES = frozenset({"preview", "mobile", "low"})
_ABSENT_CHANNEL = object()
_VOLCANIC_HINT_TOKENS = frozenset({"volcanic", "lava", "caldera", "magma"})
_LAVA_SOURCE_HINT_KEYS = frozenset(
    {"lava_source_mask", "lava_sources", "authored_lava_source", "has_lava_source_mask"}
)

# PR #57 round-4 fix (CodeRabbit thread on terrain_pipeline.py:192-210):
# Authoritative set of pass names that can still mutate height,
# water_surface_mask, or structural masks (cliff_mask, slope, curvature,
# convexity, divergence, etc.).  ``label_stamping`` is inserted AFTER the
# LAST scheduled pass in this set, so the labels stamped on the legacy
# material-label channels reflect the FINAL terrain/water/structural
# state read by ``materials_v2``.  Names not present in a given build's
# pass_sequence are silently ignored by the scan.
#
# NOTE: ``pass_road_network`` must be in this set even though it runs before
# ``materials_v2`` in the static sequence, because ``_normalize_delta_
# integration_sequence`` (called in ``run_pipeline``) moves
# ``integrate_deltas`` to AFTER the last delta producer.
# ``pass_road_network`` produces ``road_worn_path_delta``, so normalization
# places ``integrate_deltas`` after it, meaning any ``label_stamping``
# anchor placed before ``pass_road_network`` would end up BEFORE both the
# road mutation and its composed height delta — contrary to the "after the
# LAST mutator" guarantee.
_LABEL_STAMPING_DEFERRABLE_PASSES = frozenset({
    "pass_composite_hmap",
    "structural_masks",
    "banded_macro",
    "pass_banded_advanced",
    "structural_masks_post_erosion",
    "pass_hydrology_post_erosion",
    "pass_morphology",
    "pass_glacial",
    "biome_surface_features",
    "wind_erosion",
    "stratigraphy",
    "coastline",
    "pass_terrain_features",
    "framing",
    "talus",
    "structural_masks_post_talus",
    "structural_masks_post_deltas",
    "lava_emit",
    "lava_carve",
    "integrate_deltas",
    "bathymetry",
    "pass_seasonal_water_state",
    "water_variants",
    "pass_water_variants",
    "pass_water_depth",
    "erosion",
    "pass_hydrology",
    # Road network produces road_worn_path_delta; _normalize_delta_integration_
    # sequence will place integrate_deltas after this pass.  Without this entry
    # label_stamping would be anchored before the road/delta composition.
    "pass_road_network",
})


def _copy_checkpoint_value(value: Any) -> Any:
    """Copy one checkpoint channel without walking the whole stack object."""
    try:
        import numpy as _np
        if isinstance(value, _np.ndarray):
            return value.copy()
    except ImportError:  # pragma: no cover
        pass
    return copy.deepcopy(value)


def _checkpoint_pass_state(
    stack: TerrainMaskStack,
    channels: Iterable[str],
) -> Dict[str, Any]:
    """Snapshot only channels a pass may dirty, plus cheap stack metadata."""
    field_names = {field.name for field in dataclasses.fields(TerrainMaskStack)}
    unique_channels = sorted({str(ch) for ch in channels if str(ch) in field_names})
    values: Dict[str, Any] = {}
    for channel in unique_channels:
        value = getattr(stack, channel, _ABSENT_CHANNEL)
        values[channel] = (
            _ABSENT_CHANNEL
            if value is _ABSENT_CHANNEL
            else _copy_checkpoint_value(value)
        )
    return {
        "channels": values,
        "populated_by_pass": dict(stack.populated_by_pass),
        "dirty_channels": set(stack.dirty_channels),
        "content_hash": stack.content_hash,
        "height_min_m": stack.height_min_m,
        "height_max_m": stack.height_max_m,
    }


def _restore_pass_state(
    stack: TerrainMaskStack,
    snapshot: Dict[str, Any],
) -> None:
    """Restore a copy-on-write pass snapshot in place."""
    for channel, value in snapshot["channels"].items():
        if value is _ABSENT_CHANNEL:
            continue
        object.__setattr__(stack, channel, _copy_checkpoint_value(value))
    stack.populated_by_pass.clear()
    stack.populated_by_pass.update(snapshot["populated_by_pass"])
    stack.dirty_channels.clear()
    stack.dirty_channels.update(snapshot["dirty_channels"])
    stack.content_hash = snapshot["content_hash"]
    stack.height_min_m = snapshot["height_min_m"]
    stack.height_max_m = snapshot["height_max_m"]


def build_default_pass_sequence(intent: TerrainIntentState) -> List[str]:
    """Return the canonical default terrain pipeline for an intent."""
    quality_profile = str(getattr(intent, "quality_profile", "aaa_open_world"))
    composition_hints = dict(getattr(intent, "composition_hints", {}) or {})
    unity_export_opt_out = bool(composition_hints.get("unity_export_opt_out", False))
    skip_scatter = bool(composition_hints.get("skip_scatter", False))
    include_waterfalls = bool(composition_hints.get("waterfalls", True))
    # Phase C D30-32 (Issue #27) — opt-in structural label-stamping. Off by default
    # so existing fixtures stay byte-identical; downstream texturing/scatter
    # consumers that want authored region tags request it explicitly.
    include_label_stamping = bool(composition_hints.get("label_stamping", False))
    biome_hint = str(
        composition_hints.get("biome")
        or composition_hints.get("biome_name")
        or getattr(intent, "biome_name", "")
        or ""
    ).lower()
    lava_source_hint = any(bool(composition_hints.get(key, False)) for key in _LAVA_SOURCE_HINT_KEYS)
    stack_source = getattr(getattr(intent, "mask_stack", None), "lava_source_mask", None)
    try:
        stack_has_lava_source = bool(stack_source is not None and stack_source.any())
    except (AttributeError, TypeError, ValueError):
        stack_has_lava_source = stack_source is not None
    include_lava = (
        bool(composition_hints.get("lava", False))
        or lava_source_hint
        or stack_has_lava_source
        or any(token in biome_hint for token in _VOLCANIC_HINT_TOKENS)
    )
    include_talus = bool(composition_hints.get("talus", False))
    has_scene_read = getattr(intent, "scene_read", None) is not None
    validation_pass = (
        "validation_minimal"
        if quality_profile in _PREVIEW_QUALITY_PROFILES
        else "validation_full"
    )
    pass_sequence = [
        "pass_generate_low_freq_hmap",
        "biome_channels",
        "terrain_labels",
        "pass_generate_high_freq_detail",
        "pass_composite_hmap",
        # B14-9: structural_masks now runs AFTER composite_hmap so cliff_mask,
        # slope, and curvature are derived from the final composited height, not
        # the low-freq-only base.  Water/splatmap weights are always computed
        # downstream and are therefore consistent with the corrected masks.
        "structural_masks",
        # P1-9: banded_macro runs AFTER composite_hmap so its height output is
        # not overwritten by the composite.  P1-10: banded_advanced refines the
        # banded result with Kuwahara anti-grain smoothing.
        "banded_macro",
        "pass_banded_advanced",
        validation_pass,
    ]
    # Phase C D30-32 (Issue #27) — opt-in label-stamping deferred until AFTER
    # every pass that can still mutate height, water, or structural masks.
    # See _LABEL_STAMPING_DEFERRABLE_PASSES (module-level set) for the
    # authoritative list.  The actual insert happens in a single block at
    # the bottom of this builder (post all scene-read / validation-full
    # extensions) so the deferrable-set scan sees the FINAL pass_sequence.
    if has_scene_read:
        # Hydrology + erosion operate on the low-freq height before compositing.
        # Insert them at index 3 (before pass_generate_high_freq_detail).
        pass_sequence[3:3] = ["pass_hydrology", "erosion"]
        composite_idx = pass_sequence.index("pass_composite_hmap") + 1
        for post_erosion in ("structural_masks_post_erosion", "pass_hydrology_post_erosion"):
            pass_sequence.insert(composite_idx, post_erosion)
            composite_idx += 1
        if validation_pass == "validation_full":
            pass_sequence.insert(composite_idx, "pass_morphology")
            composite_idx += 1
            # C-1: glacial pass runs after morphology, before scatter/materials
            pass_sequence.insert(composite_idx, "pass_glacial")
            composite_idx += 1
            # Batch-13 wiring: biome surface features after glacial, before feature carving
            pass_sequence.insert(composite_idx, "biome_surface_features")
            composite_idx += 1
    if validation_pass == "validation_full":
        insert_at = pass_sequence.index("validation_full")
        for prereq in (
            # Phase A D8-9: explicitly schedule the 2 determinism-safe Bundle I
            # orphan passes whose deltas are otherwise stranded. R1.5 verifier
            # confirmed 3 real omissions (stratigraphy, wind_erosion, coastline);
            # this PR lands ``wind_erosion`` + ``coastline`` only. Stratigraphy
            # is DEFERRED to Phase B because it currently writes 4 undeclared
            # channels (bedrock_height, height, sediment_height, strata_height)
            # without ``overrides=("height",)`` — a pre-existing
            # produces_channels gap discovered while writing this PR's
            # determinism test (test_terrain_deep_qa::test_determinism_check
            # fails when stratigraphy is scheduled because its height
            # overwrite is non-determinism-safe today).
            #
            # karst + glacial are already scheduled (glacial via the
            # has_scene_read insert in the early validation_full block;
            # karst is consumed via optional_channels by downstream passes
            # per R1.5 verifier).
            #
            # ``wind_erosion`` is scheduled HERE, before ``pass_terrain_features``
            # and the water-variants block. Its only requires_channels=("height",)
            # entry is already populated by the macro/banded/erosion passes
            # earlier in the sequence.
            *(("wind_erosion",) if has_scene_read else ()),
            # Phase C D26-27 (Task #39 follow-up to Phase A D8-9):
            # ``stratigraphy`` is the third Bundle I orphan called out by
            # the R1.5 verifier. Phase A D8 deferred it because its
            # registration was missing produces_channels for
            # (sediment_height, bedrock_height, strata_height) and
            # overrides=("height",) for the fold-deformation overwrite.
            # Phase C D26-27 closes that gap in register_bundle_i_passes
            # (terrain_geology_validator.py) and schedules the pass HERE
            # so its strat_erosion_delta is composed into ``height`` by
            # ``integrate_deltas``.
            *(("stratigraphy",) if has_scene_read else ()),
            # Codex round-3 fix (PR #58 thread 1): ``topographic_indices``
            # was previously inserted HERE (before water/coastline/
            # waterfall/integrate_deltas/talus), so its outputs were
            # computed from the pre-delta surface.  When any of those
            # passes write a height-mutating delta and ``integrate_deltas``
            # composes it (or ``talus`` rewrites height post-integration),
            # vb_aspect_deg / vb_aspect_north / vb_canopy_openness / vb_TWI
            # would lag the actual surface and downstream foliage / scatter
            # consumers would see stale topographic masks.  The pass is now
            # scheduled BELOW after ``structural_masks_post_talus`` so it
            # always reads the final composited height — see the inserted
            # ``"topographic_indices"`` entry after talus + before
            # ``pass_road_network`` / ``materials_v2``.
            # C-7: terrain feature carving before scatter
            "pass_terrain_features",
            # C-8: sightline framing before scatter
            "framing",
            *(("water_variants", "pass_seasonal_water_state", "bathymetry", "pass_water_depth") if has_scene_read else ()),
            # PR-A (cross-audit P0 2026-05-09): schedule the two registered
            # water orphan passes that produce channels read by 5 existing
            # downstream call sites. ``pass_water_flow_speed`` produces
            # ``flow_speed`` which terrain_waterfalls reads at 5 sites
            # (148, 1521, 1856, 2389, ...) — silently degrading to zeros
            # before this PR. ``pass_river_convergence`` produces
            # ``river_mouth_mask``, ``confluence_foam``, ``delta_fan_direction``
            # which the unity export schema and waterfall foam shader can
            # consume once wired (PR-W follow-up). Both depend on
            # ``flow_accumulation`` + ``flow_direction`` from pass_hydrology
            # and on ``water_surface_mask`` from pass_water_variants —
            # already scheduled upstream.
            *(("pass_water_flow_speed", "pass_river_convergence") if has_scene_read else ()),
            # Codex review (PR #36 P2): ``pass_coastline`` reads
            # ``water_surface_elevation_m`` to derive shoreline; that channel is
            # written by ``pass_water_variants`` upstream. Scheduling coastline
            # BEFORE water_variants makes the pass fall back to sea_level=0.0
            # and produce wrong tidal/wave/coastline_delta. Schedule AFTER
            # water_variants but BEFORE waterfalls + integrate_deltas (so
            # ``coastline_delta`` is available to the integrator).
            *(("coastline",) if has_scene_read else ()),
            *(("waterfalls", "emit_particle_systems") if has_scene_read and include_waterfalls else ()),
            *(("integrate_deltas",) if has_scene_read else ()),
            # PR-F2 (cross-audit P0 2026-05-09): recompute structural masks
            # immediately after ``integrate_deltas`` composes all height
            # deltas. Always scheduled (not gated on ``include_talus``) so
            # the post-delta slope/curvature/ridge/basin fields are
            # available to ``materials_v2`` / ``scatter_intelligent`` /
            # ``label_stamping`` / ``topographic_indices`` even when talus
            # is disabled. When talus is enabled, both this AND
            # ``structural_masks_post_talus`` run — talus reads correct
            # slope from THIS recompute, then post_talus recomputes again
            # against post-talus height. Cheap (single Sobel-style filter)
            # and produces deterministic byte-identical results because
            # ``pass_structural_masks`` is purely derivative.
            *(("structural_masks_post_deltas",) if has_scene_read else ()),
            *(("talus", "structural_masks_post_talus") if include_talus else ()),
            *(("pass_lava_simulation",) if include_lava else ()),
            # Codex round-3 fix (PR #58 thread 1): ``topographic_indices``
            # is scheduled AFTER all height-mutating passes (delta
            # integration, talus, lava) and BEFORE the materials/scatter
            # consumers, so vb_aspect_deg / vb_aspect_north /
            # vb_canopy_openness / vb_TWI reflect the final composited
            # height the consumers actually texture / scatter on.
            "topographic_indices",
            # FIX-B14-6: road network pass runs before materials and scatter so
            # road_sdf_dist is available to materials_v2 / scatter_intelligent.
            "pass_road_network",
            "materials_v2",
            *(("emit_overhang_meshes",) if has_scene_read else ()),
            *(("scatter_intelligent", "pass_procedural_grass", "pass_horizon_lod") if has_scene_read and not skip_scatter else ()),
            # C-2: Bundle J ecosystem passes
            "audio_zones",
            "wildlife_zones",
            "gameplay_zones",
            "wind_field",
            "cloud_shadow",
            "ecotones",
            # C-3: Bundle K material ceiling passes
            "stochastic_shader",
            "macro_color",
            "multiscale_breakup",
            "shadow_clipmap",
            "roughness_driver",
            "quixel_ingest",
            # C-4: Bundle L atmosphere + atmospheric volumes
            "fog_masks",
            "god_ray_hints",
            "pass_atmospheric_volumes",
            # C-9: post-scatter saliency refinement
            "saliency_refine",
            # C-6: navmesh export runs regardless of unity_export_opt_out.
            # It must precede decals so traversability is populated before
            # footprint-trail density is computed.
            "pass_navmesh_export",
            "decals",
        ):
            if prereq not in pass_sequence:
                pass_sequence.insert(insert_at, prereq)
                insert_at += 1
    if validation_pass == "validation_full" and not unity_export_opt_out:
        insert_at = pass_sequence.index("validation_full")
        for prereq in (
            "prepare_terrain_normals",
            "prepare_heightmap_raw_u16",
            "prepare_unity_auxiliary_channels",
        ):
            if prereq not in pass_sequence:
                pass_sequence.insert(insert_at, prereq)
                insert_at += 1
    # PR #57 round-4 fix (CodeRabbit thread on terrain_pipeline.py:192-210):
    # ``label_stamping`` derives labels from slope/curvature/water masks, so
    # it must run AFTER every later pass that can still change height,
    # water_surface_mask, or structural masks (e.g. banded_macro,
    # pass_banded_advanced, integrate_deltas, talus, structural_masks_post_*,
    # pass_water_depth, pass_water_variants, ...).  Otherwise materials_v2
    # reads stamps that were derived from intermediate state.
    #
    # Single insertion point handles both headless and scene-read modes —
    # the scan over the FINAL pass_sequence picks up whichever deferrable
    # passes are actually scheduled in this build.  Skipped silently when
    # include_label_stamping is False so default tests are unaffected.
    if include_label_stamping and "label_stamping" not in pass_sequence:
        last_mutator_idx = -1
        for i, name in enumerate(pass_sequence):
            if name in _LABEL_STAMPING_DEFERRABLE_PASSES:
                last_mutator_idx = i
        if last_mutator_idx >= 0:
            pass_sequence.insert(last_mutator_idx + 1, "label_stamping")
        elif "structural_masks" in pass_sequence:
            # Fallback: post-structural_masks (covers truncated test sequences
            # where none of the deferrable mutators are scheduled).
            pass_sequence.insert(pass_sequence.index("structural_masks") + 1, "label_stamping")
        else:
            # No anchor at all — append before validation_pass, or at end.
            if validation_pass in pass_sequence:
                pass_sequence.insert(pass_sequence.index(validation_pass), "label_stamping")
            else:
                pass_sequence.append("label_stamping")
    return pass_sequence


# ---------------------------------------------------------------------------
# Determinism seed derivation (§5.12)
# ---------------------------------------------------------------------------


def derive_pass_seed(
    intent_seed: int,
    seed_namespace: str,
    tile_x: int,
    tile_y: int,
    region: Optional[BBox],
) -> int:
    """Derive a deterministic 32-bit seed from intent + pass + tile + region.

    Uses SHA-256 over a JSON-encoded tuple. Python's built-in ``hash()`` is
    PYTHONHASHSEED-randomized, so we cannot use it. The resulting integer
    is masked to 32 bits for numpy RNG compatibility.
    """
    payload = json.dumps(
        [
            int(intent_seed),
            str(seed_namespace),
            int(tile_x),
            int(tile_y),
            list(region.to_tuple()) if region is not None else None,
        ],
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:4], "big") & 0xFFFFFFFF


_POST_DELTAS_RECOMPUTE_PASS = "structural_masks_post_deltas"


def _normalize_delta_integration_sequence(pass_sequence: List[str]) -> List[str]:
    """Ensure ``integrate_deltas`` runs after the last delta-producing pass.

    Several terrain bundles publish deferred ``*_delta`` channels instead of
    mutating ``height`` directly. Downstream validation/export consumers need
    the composed heightfield, so controller sequencing normalizes the
    integrator placement instead of relying on every caller to insert it
    manually.

    PR-F2 (2026-05-09): also keeps ``structural_masks_post_deltas`` paired
    immediately after ``integrate_deltas`` regardless of where the integrator
    moves. Otherwise the recompute can land BEFORE the integrator and
    materials_v2 / scatter_intelligent / label_stamping / topographic_indices
    silently consume pre-delta slope/curvature — the exact pass-order rot
    this PR closes.
    """
    seq = list(pass_sequence)
    if not seq or "integrate_deltas" not in TerrainPassController.PASS_REGISTRY:
        return seq

    from .terrain_delta_integrator import _DELTA_CHANNELS

    delta_channels = set(_DELTA_CHANNELS)
    # Strip BOTH the integrator and its paired recompute so they are always
    # re-inserted together at the post-producer slot.
    #
    # Codex P2 / Copilot review fix on PR #62: only strip
    # ``structural_masks_post_deltas`` if it is REGISTERED. Otherwise the
    # unconditional strip silently drops the pass on partial-registry or
    # hot-reload scenarios — and the existing unregistered-passes warning
    # never fires because the strip happens before the diagnostic loop.
    # Leaving an unregistered recompute in place is the safer fallback:
    # the warning loop will surface it, and downstream consumers can
    # decide whether to skip or fail.
    pinned_passes = {"integrate_deltas"}
    if _POST_DELTAS_RECOMPUTE_PASS in TerrainPassController.PASS_REGISTRY:
        pinned_passes.add(_POST_DELTAS_RECOMPUTE_PASS)
    seq_without_integrator = [name for name in seq if name not in pinned_passes]

    # P2-5: surface unregistered pass names instead of silently skipping them.
    # A typo or missing registration would otherwise cause delta integrators to
    # land at the wrong position without any diagnostic.
    unregistered = [
        name for name in seq_without_integrator
        if name not in TerrainPassController.PASS_REGISTRY
    ]
    if unregistered:
        _log.warning(
            "_normalize_delta_integration_sequence: skipping unregistered pass names %s "
            "when locating delta producers; integrate_deltas placement may be suboptimal. "
            "Register these passes or remove them from pass_sequence.",
            sorted(set(unregistered)),
        )

    producer_indexes = [
        idx
        for idx, name in enumerate(seq_without_integrator)
        if name in TerrainPassController.PASS_REGISTRY
        and delta_channels.intersection(
            TerrainPassController.PASS_REGISTRY[name].produces_channels
        )
    ]
    if not producer_indexes:
        return seq

    insert_at = producer_indexes[-1] + 1
    normalized = list(seq_without_integrator)
    normalized.insert(insert_at, "integrate_deltas")
    # PR-F2 pairing: restore the post-deltas recompute immediately after
    # the integrator. Only pair when the recompute was scheduled by the
    # caller (otherwise we'd be silently adding it to legacy callers that
    # didn't ask for it) AND the pass is registered.
    if (
        _POST_DELTAS_RECOMPUTE_PASS in pass_sequence
        and _POST_DELTAS_RECOMPUTE_PASS in TerrainPassController.PASS_REGISTRY
    ):
        normalized.insert(insert_at + 1, _POST_DELTAS_RECOMPUTE_PASS)
    return normalized


# ---------------------------------------------------------------------------
# TerrainPassController (§5.10)
# ---------------------------------------------------------------------------


class TerrainPassController:
    """Central pass orchestrator. All terrain mutations route through here."""

    # Class-level pass registry — populated via ``register_pass``
    PASS_REGISTRY: Dict[str, PassDefinition] = {}

    def __init__(
        self,
        state: TerrainPipelineState,
        *,
        checkpoint_dir: Optional[Path] = None,
    ) -> None:
        self.state = state
        self.checkpoint_dir: Path = Path(
            checkpoint_dir
            if checkpoint_dir is not None
            else Path(".planning") / "terrain_checkpoints"
        )

    # -- registration --------------------------------------------------------

    @classmethod
    def register_pass(cls, definition: PassDefinition, strict: bool = False) -> None:
        """Register a pass definition by name.

        Parameters
        ----------
        definition:
            The ``PassDefinition`` to register.  Its ``.name`` attribute is
            used as the registry key.
        strict:
            When *True*, raises ``ValueError`` on a duplicate name so that
            integration test suites catch accidental double-registration
            immediately.  When *False* (default), logs a WARNING and lets
            the newer definition win — prevents import-order surprises in
            the 14-bundle pipeline from crashing the addon at startup.

        Raises
        ------
        TypeError
            If ``definition`` is not a ``PassDefinition`` instance, so
            callers that accidentally pass a plain dict or string get a
            clear diagnostic rather than a silent AttributeError later.
        ValueError
            In strict mode only, when ``definition.name`` is already
            present in the registry.
        """
        if not isinstance(definition, PassDefinition):
            # Tests and legacy Blender add-on callers can import this package
            # through both ``blender_addon.handlers`` and
            # ``veilbreakers_terrain.handlers``.  After hot-reload, that can
            # leave two PassDefinition class objects with identical fields.
            # Canonicalise that structural twin instead of rejecting it as a
            # plain non-pass object.
            if type(definition).__name__ == "PassDefinition":
                try:
                    definition = PassDefinition(
                        name=definition.name,
                        func=definition.func,
                        requires_channels=tuple(getattr(definition, "requires_channels", ()) or ()),
                        produces_channels=tuple(getattr(definition, "produces_channels", ()) or ()),
                        optional_channels=tuple(getattr(definition, "optional_channels", ()) or ()),
                        # FIX-B14-P1-13: canonicalise requires_channels_optional from twin class
                        requires_channels_optional=tuple(getattr(definition, "requires_channels_optional", ()) or ()),
                        overrides=tuple(getattr(definition, "overrides", ()) or ()),
                        requires_features=tuple(getattr(definition, "requires_features", ()) or ()),
                        idempotent=bool(getattr(definition, "idempotent", True)),
                        deterministic=bool(getattr(definition, "deterministic", True)),
                        may_modify_geometry=bool(getattr(definition, "may_modify_geometry", False)),
                        may_add_geometry=bool(getattr(definition, "may_add_geometry", False)),
                        respects_protected_zones=bool(getattr(definition, "respects_protected_zones", True)),
                        supports_region_scope=bool(getattr(definition, "supports_region_scope", True)),
                        seed_namespace=str(getattr(definition, "seed_namespace", "") or ""),
                        requires_scene_read=bool(getattr(definition, "requires_scene_read", False)),
                        protocol_enforced=bool(getattr(definition, "protocol_enforced", False)),
                        protocol_require_rule_2=bool(getattr(definition, "protocol_require_rule_2", False)),
                        protocol_require_rule_5=bool(getattr(definition, "protocol_require_rule_5", False)),
                        protocol_out_of_view_ok=bool(getattr(definition, "protocol_out_of_view_ok", False)),
                        protocol_bulk_edit=bool(getattr(definition, "protocol_bulk_edit", False)),
                        quality_gate=getattr(definition, "quality_gate", None),
                        visual_validator=getattr(definition, "visual_validator", None),
                        description=str(getattr(definition, "description", "") or ""),
                    )
                except Exception as exc:  # noqa: BLE001
                    raise TypeError(
                        "register_pass received a PassDefinition-shaped object "
                        f"that could not be canonicalised: {exc}"
                    ) from exc
            else:
                raise TypeError(
                    f"register_pass expects a PassDefinition, got {type(definition).__name__}"
                )

        # ------------------------------------------------------------------
        # Duplicate-producer enforcement (added 2026-04-23 wiring audit).
        #
        # When a channel is already produced by some other registered pass,
        # the new pass must explicitly acknowledge the overwrite by listing
        # the channel in ``overrides``. This catches accidental dual-producer
        # DAG hazards (of the kind that motivated the cloud_shadow rename)
        # at register time instead of silently fighting over the channel at
        # run time.
        # ------------------------------------------------------------------
        # Idempotency: if this exact pass name is already in the registry,
        # treat this as a re-registration of the SAME pass (common when
        # ``register_all_terrain_passes`` runs twice in a session: e.g. once
        # when the registry is empty, and again when post-injection pipeline
        # scanning finds a missing pass). The duplicate-producer check is
        # only meaningful on the FIRST registration of a given pass name —
        # on a re-register, the channel claims are identical to the previous
        # round and do not introduce a new hazard.
        if definition.name not in cls.PASS_REGISTRY:
            declared_overrides = set(getattr(definition, "overrides", ()) or ())
            for ch in definition.produces_channels:
                existing_producers = [
                    other.name
                    for other in cls.PASS_REGISTRY.values()
                    if other.name != definition.name and ch in other.produces_channels
                ]
                if existing_producers and ch not in declared_overrides:
                    raise ChannelOwnershipError(
                        f"Pass '{definition.name}' declares produces_channels="
                        f"{definition.produces_channels!r} but channel {ch!r} is "
                        f"already produced by {existing_producers!r}. If this "
                        f"overwrite is intentional, add overrides={{'{ch}'}} to "
                        f"the PassDefinition. Otherwise pick a distinct channel "
                        f"name (see cloud_shadow → sun_cloud_shadow/baked_cloud_shadow "
                        f"rename for the canonical pattern)."
                    )

        if definition.name in cls.PASS_REGISTRY:
            existing = cls.PASS_REGISTRY[definition.name]
            msg = (
                f"Duplicate pass registration: '{definition.name}' already registered "
                f"(description={getattr(existing, 'description', '?')!r}); "
                f"overwriting with description={getattr(definition, 'description', '?')!r}. "
                f"Use strict=True to raise instead of silently overwrite."
            )
            if strict:
                raise ValueError(msg)
            _log.warning(msg)
        cls.PASS_REGISTRY[definition.name] = definition

        # Populate the module-level weak registry for hot-reload func rebinding
        # (FIX-B14-23).  We store (module_name, attr_name) -> PassDefinition so
        # that after importlib.reload() the hot-reload code can re-bind func
        # without going through the full registration path.
        func = definition.func
        mod = getattr(func, "__module__", None)
        qual = getattr(func, "__qualname__", None) or getattr(func, "__name__", None)
        if mod and qual:
            # Use just the top-level name for attribute lookup after reload
            attr_name = qual.split(".")[0]
            try:
                _PASS_MODULE_REGISTRY[(mod, attr_name)] = definition
            except TypeError:
                pass  # unhashable key — skip silently

    @classmethod
    def get_pass(cls, pass_name: str) -> PassDefinition:
        if pass_name not in cls.PASS_REGISTRY:
            raise UnknownPassError(f"Pass not registered: {pass_name}")
        return cls.PASS_REGISTRY[pass_name]

    @classmethod
    def clear_registry(cls) -> None:
        """Test helper — clears the pass registry."""
        cls.PASS_REGISTRY.clear()

    @classmethod
    def validate_registry_graph(cls) -> list[str]:
        """Check registered passes for common wiring issues.

        Returns a list of warning strings (empty = clean). Checks:
          - requires_channels not produced by any registered pass.
          - duplicate entries in requires/produces_channels.
        """
        warnings_list: list[str] = []
        all_produced: set[str] = set()
        for defn in cls.PASS_REGISTRY.values():
            all_produced.update(defn.produces_channels)

        for name, defn in cls.PASS_REGISTRY.items():
            seen_req: set[str] = set()
            for ch in defn.requires_channels:
                if ch in seen_req:
                    warnings_list.append(
                        f"Pass '{name}': duplicate requires_channels entry '{ch}'"
                    )
                seen_req.add(ch)
                if ch not in all_produced:
                    warnings_list.append(
                        f"Pass '{name}' requires channel '{ch}' "
                        "but no registered pass produces it"
                    )
            seen_prod: set[str] = set()
            for ch in defn.produces_channels:
                if ch in seen_prod:
                    warnings_list.append(
                        f"Pass '{name}': duplicate produces_channels entry '{ch}'"
                    )
                seen_prod.add(ch)

        return warnings_list

    # -- enforcement hooks ---------------------------------------------------

    def require_scene_read(self, operation: str) -> None:
        """Raise SceneReadRequired if current intent lacks a TerrainSceneRead."""
        if self.state.intent.scene_read is None:
            raise SceneReadRequired(
                f"Pass '{operation}' requires a TerrainSceneRead on the intent. "
                "Attach one via intent.with_scene_read() before running mutating passes."
            )

    def enforce_protected_zones(
        self,
        pass_name: str,
        target_bounds: BBox,
    ) -> None:
        """Raise ProtectedZoneViolation only if a forbidding zone fully
        covers ``target_bounds`` — i.e. the pass would have no mutable
        cells to work on.

        Partial intersection is allowed: the pass is expected to consult
        per-cell protected masks (see ``pass_erosion``) and skip mutation
        on forbidden cells.
        """
        for zone in self.state.intent.protected_zones:
            if not zone.bounds.intersects(target_bounds):
                continue
            if zone.permits(pass_name):
                continue
            fully_covers = (
                zone.bounds.min_x <= target_bounds.min_x
                and zone.bounds.min_y <= target_bounds.min_y
                and zone.bounds.max_x >= target_bounds.max_x
                and zone.bounds.max_y >= target_bounds.max_y
            )
            if fully_covers:
                raise ProtectedZoneViolation(
                    f"Pass '{pass_name}' forbidden in protected zone "
                    f"'{zone.zone_id}' (kind={zone.kind}) which fully "
                    f"covers target_bounds — no mutable cells available."
                )

    # -- execution -----------------------------------------------------------

    def run_pass(
        self,
        pass_name: str,
        region: Optional[BBox] = None,
        *,
        force: bool = False,
        checkpoint: bool = True,
    ) -> PassResult:
        """Run a single registered pass against the current state.

        Enforces:
            - Scene-read presence (if the pass requires it)
            - Protected-zone permissions over ``region`` (or full region_bounds)
            - Channel prerequisites declared by the pass
            - Post-run verification that ``produces_channels`` are actually set

        Records the pass result on ``state.pass_history``, optionally emits
        a checkpoint, and returns the ``PassResult``.
        """
        definition = self.get_pass(pass_name)

        if definition.requires_scene_read:
            self.require_scene_read(pass_name)

        target_bounds = region if region is not None else self.state.intent.region_bounds
        if definition.respects_protected_zones:
            self.enforce_protected_zones(pass_name, target_bounds)

        missing_inputs = [
            ch
            for ch in definition.requires_channels
            if self.state.mask_stack.get(ch) is None
        ]
        if missing_inputs:
            raise PassContractError(
                f"Pass '{pass_name}' requires channels {missing_inputs} "
                "but they are not populated on the mask stack."
            )

        if definition.protocol_enforced:
            from .terrain_protocol import ProtocolGate

            hints = dict(getattr(self.state.intent, "composition_hints", {}) or {})
            if definition.protocol_require_rule_2:
                ProtocolGate.rule_2_sync_to_user_viewport(
                    self.state,
                    out_of_view_ok=bool(
                        definition.protocol_out_of_view_ok
                        or hints.get("protocol_out_of_view_ok", False)
                    ),
                )
            if definition.protocol_require_rule_5:
                tile_cells = max(1, int(getattr(self.state.mask_stack.height, "size", 1)))
                if region is None:
                    cells_affected = tile_cells
                else:
                    cell = max(float(self.state.mask_stack.cell_size), 1e-9)
                    cells_affected = int(max(1.0, (region.width * region.height) / (cell * cell)))
                ProtocolGate.rule_5_smallest_diff_per_iteration(
                    self.state,
                    cells_affected=cells_affected,
                    objects_affected=0,
                    bulk_edit=bool(
                        definition.protocol_bulk_edit
                        or hints.get("protocol_bulk_edit", False)
                    ),
                )

        content_hash_before = self.state.mask_stack.compute_hash()
        seed_used = derive_pass_seed(
            self.state.intent.seed,
            definition.seed_namespace or pass_name,
            self.state.tile_x,
            self.state.tile_y,
            region,
        )

        # Phase 7.1: copy-on-write rollback. Snapshot only declared output /
        # override channels instead of deepcopying the entire TerrainMaskStack.
        stack_snapshot = _checkpoint_pass_state(
            self.state.mask_stack,
            set(definition.produces_channels)
            | set(definition.overrides)
            | {"height"},
        )

        _provenance_before = dict(self.state.mask_stack.populated_by_pass)
        t0 = time.perf_counter()
        try:
            result = definition.func(self.state, region)
        except Exception as exc:  # pragma: no cover — surface all errors
            _log.error(
                "Pass %r raised exception — rolling back mask_stack: %s",
                pass_name, exc, exc_info=exc,
            )
            _restore_pass_state(self.state.mask_stack, stack_snapshot)
            result = PassResult(
                pass_name=pass_name,
                status="failed",
                duration_seconds=time.perf_counter() - t0,
                metrics={"error": repr(exc)},
                seed_used=seed_used,
                content_hash_before=content_hash_before,
            )
            self.state.record_pass(result)
            return result

        if not isinstance(result, PassResult):
            raise PassContractError(
                f"Pass '{pass_name}' did not return a PassResult "
                f"(got {type(result).__name__})"
            )

        # Defaults / enforced fields
        result.pass_name = pass_name
        result.seed_used = seed_used
        result.content_hash_before = content_hash_before
        if result.duration_seconds <= 0.0:
            result.duration_seconds = time.perf_counter() - t0

        # Verify produced-channel contract
        missing_outputs = [
            ch
            for ch in definition.produces_channels
            if self.state.mask_stack.get(ch) is None
        ]
        if missing_outputs and result.status == "ok":
            raise PassContractError(
                f"Pass '{pass_name}' declared produces_channels={definition.produces_channels} "
                f"but did not populate {missing_outputs}"
            )

        # FIX-D24-PR13: NaN/Inf assertion on every produced channel.
        # Catches numerical corruption (e.g. erosion divide-by-slope-zero,
        # uninitialised float buffers, hydraulic accumulation overflow) at
        # the boundary that produced it, instead of letting the poison
        # silently propagate downstream into water depth / scatter / Unity
        # heightmap export. Skipped on failed/dry-run passes because their
        # channel state is not part of the success contract. Integer and
        # boolean channels are skipped automatically by ``assert_finite_array``
        # because those dtypes cannot represent NaN/Inf.
        if result.status == "ok":
            for _produced_ch in definition.produces_channels:
                _arr = self.state.mask_stack.get(_produced_ch)
                # ``assert_finite_array`` is a no-op on None / non-float arrays.
                assert_finite_array(
                    _arr,
                    channel=_produced_ch,
                    pass_name=pass_name,
                )
            # Also verify any channels declared as overrides (secondary
            # writes) to catch in-place mutation that introduces NaN/Inf
            # without being declared in produces_channels.
            for _override_ch in definition.overrides:
                _arr = self.state.mask_stack.get(_override_ch)
                assert_finite_array(
                    _arr,
                    channel=_override_ch,
                    pass_name=pass_name,
                )

        # Warn on channels written but not declared in produces_channels
        # Full dict comparison catches both new keys AND silent overwrites of
        # existing channels by a different pass_name.
        _provenance_after = dict(self.state.mask_stack.populated_by_pass)
        _undeclared = {
            ch for ch, pname in _provenance_after.items()
            if _provenance_before.get(ch) != pname
               and ch not in definition.produces_channels
               and ch not in definition.overrides
        }
        if _undeclared:
            _log.warning(
                "Pass '%s' wrote undeclared channels %s; add to produces_channels",
                pass_name, sorted(_undeclared),
            )

        # Run quality gate if defined (§agent protocol rule 4)
        if definition.quality_gate is not None and result.status == "ok":
            gate = definition.quality_gate
            try:
                gate_issues = gate.check(result, self.state.mask_stack)
            except Exception as exc:  # pragma: no cover — gate bugs must fail loudly
                gate_issues = [
                    # Construct ValidationIssue lazily to avoid a hard import loop
                    _make_gate_issue(
                        code=f"GATE_{gate.name.upper()}_CRASHED",
                        severity="hard",
                        message=f"quality gate {gate.name} raised: {exc!r}",
                    )
                ]
            if gate_issues:
                hard = [i for i in gate_issues if getattr(i, "severity", "") == "hard"]
                if hard and gate.blocking:
                    result.status = "failed"
                    result.issues.extend(gate_issues)
                else:
                    result.status = "warning" if result.status == "ok" else result.status
                    result.warnings.extend(gate_issues)

        # Run visual validator (optional)
        if definition.visual_validator is not None and result.status in ("ok", "warning"):
            try:
                signature = definition.visual_validator(self.state.mask_stack)
                result.metrics.setdefault("visual_signature_bytes", len(signature or b""))
            except Exception as exc:  # pragma: no cover
                result.metrics["visual_signature_error"] = repr(exc)

        result.content_hash_after = self.state.mask_stack.compute_hash()
        self.state.record_pass(result)

        if checkpoint and result.status == "ok":
            ckpt = self._save_checkpoint(pass_name, result)
            result.checkpoint_path = str(ckpt.mask_stack_path)
            self.state.checkpoints.append(ckpt)

        return result

    def run_pipeline(
        self,
        intent: Optional[TerrainIntentState] = None,
        pass_sequence: Optional[List[str]] = None,
        *,
        region: Optional[BBox] = None,
        checkpoint: bool = True,
        from_pass: Optional[str] = None,
        dry_run: bool = False,
        resume_from_checkpoint: Optional[str] = None,
    ) -> List[PassResult]:
        """Run a sequence of passes in order. Stops on the first failure.

        Parameters
        ----------
        intent:
            Optional new intent to replace the current state intent.
        pass_sequence:
            Ordered list of pass names to execute.  Defaults to the standard
            Bundle A sequence when omitted.
        region:
            Optional spatial region to scope all passes to.
        checkpoint:
            When True (default) a checkpoint is emitted after each successful pass.
        from_pass:
            When set, skip all passes in ``pass_sequence`` that appear *before*
            this name (inclusive start).  Allows partial re-runs from a known
            good pass without re-executing expensive earlier passes.
            Raises ``ValueError`` when ``from_pass`` is not in ``pass_sequence``.
        dry_run:
            When True, resolve and validate the pass sequence (checking for
            unknown pass names, protected-zone violations, and missing channel
            inputs) but do NOT execute any pass functions.  Returns a list of
            ``PassResult`` stubs with ``status="dry_run"`` and zero duration.
            Useful for CI pre-flight checks.
        resume_from_checkpoint:
            Checkpoint id to restore before starting the sequence.  The
            controller will call ``rollback_to(resume_from_checkpoint)`` so the
            mask stack matches the named checkpoint, then execute any passes
            that come *after* that checkpoint's pass in the sequence.  When
            combined with ``from_pass``, the latter takes precedence for
            sequencing and the checkpoint is only used for state restoration.
        """
        if intent is not None:
            self.state.intent = intent

        if pass_sequence is None:
            pass_sequence = build_default_pass_sequence(self.state.intent)
            missing_default_passes = [
                name for name in pass_sequence if name not in self.PASS_REGISTRY
            ]
            if missing_default_passes:
                try:
                    from .terrain_master_registrar import register_all_terrain_passes

                    register_all_terrain_passes(strict=False)
                except Exception as exc:  # noqa: BLE001
                    _log.warning(
                        "run_pipeline: could not register default passes %s: %s",
                        missing_default_passes,
                        exc,
                    )
        else:
            pass_sequence = list(pass_sequence)

        pass_sequence = _normalize_delta_integration_sequence(pass_sequence)

        # ------------------------------------------------------------------
        # resume_from_checkpoint: restore state before sequencing
        # ------------------------------------------------------------------
        if resume_from_checkpoint is not None:
            self.rollback_to(resume_from_checkpoint)
            _log.info(
                "run_pipeline: resumed from checkpoint '%s'",
                resume_from_checkpoint,
            )
            # When no from_pass given, automatically advance past the
            # checkpoint's pass so we don't re-run completed work.
            if from_pass is None:
                restored_ckpt = next(
                    (c for c in self.state.checkpoints
                     if c.checkpoint_id == resume_from_checkpoint),
                    None,
                )
                if restored_ckpt is not None:
                    ckpt_pass = restored_ckpt.pass_name
                    if ckpt_pass in pass_sequence:
                        idx = pass_sequence.index(ckpt_pass)
                        # Start from the pass AFTER the checkpoint's pass
                        if idx + 1 < len(pass_sequence):
                            from_pass = pass_sequence[idx + 1]

        # ------------------------------------------------------------------
        # from_pass: slice the sequence to start at the named pass
        # ------------------------------------------------------------------
        if from_pass is not None:
            if from_pass not in pass_sequence:
                raise ValueError(
                    f"run_pipeline: from_pass={from_pass!r} is not in pass_sequence "
                    f"{pass_sequence}. Valid pass names: {pass_sequence}"
                )
            start_idx = pass_sequence.index(from_pass)
            pass_sequence = pass_sequence[start_idx:]
            _log.info(
                "run_pipeline: partial re-run starting from pass '%s' (%d/%d passes)",
                from_pass,
                len(pass_sequence),
                len(pass_sequence),
            )

        # ------------------------------------------------------------------
        # dry_run: validate without executing
        # ------------------------------------------------------------------
        if dry_run:
            stub_results: List[PassResult] = []
            for pass_name in pass_sequence:
                definition = self.get_pass(pass_name)
                target_bounds = region if region is not None else self.state.intent.region_bounds
                issues: list = []
                # Validate protected zones
                if definition.respects_protected_zones:
                    try:
                        self.enforce_protected_zones(pass_name, target_bounds)
                    except Exception as exc:  # noqa: BLE001
                        issues.append(str(exc))
                # Validate channel prerequisites
                missing_inputs = [
                    ch for ch in definition.requires_channels
                    if self.state.mask_stack.get(ch) is None
                ]
                if missing_inputs:
                    issues.append(
                        f"Missing required channels: {missing_inputs}"
                    )
                stub = PassResult(
                    pass_name=pass_name,
                    status="dry_run",
                    duration_seconds=0.0,
                    metrics={"dry_run": True, "issues": issues},
                    seed_used=0,
                )
                stub_results.append(stub)
            _log.info(
                "run_pipeline: dry_run complete — %d passes validated, %d with issues",
                len(stub_results),
                sum(1 for r in stub_results if r.metrics.get("issues")),
            )
            return stub_results

        # ------------------------------------------------------------------
        # Normal execution
        # ------------------------------------------------------------------
        pre_pipeline_mask_stack = copy.deepcopy(self.state.mask_stack)
        setattr(self, "_pre_pipeline_baseline_stack", pre_pipeline_mask_stack)
        validation_bound = False
        try:
            from .terrain_validation import bind_active_controller

            bind_active_controller(self)
            validation_bound = True
        except Exception:  # noqa: BLE001
            validation_bound = False

        bundle_n_pre_pipeline_state = None
        try:
            from .terrain_bundle_n import bundle_n_runtime_requests_determinism

            if bundle_n_runtime_requests_determinism(self.state.intent):
                bundle_n_pre_pipeline_state = copy.deepcopy(self.state)
        except Exception:  # noqa: BLE001
            bundle_n_pre_pipeline_state = None

        results: List[PassResult] = []
        try:
            for pass_name in pass_sequence:
                res = self.run_pass(pass_name, region=region, checkpoint=checkpoint)
                results.append(res)
                if res.status == "failed":
                    break
        finally:
            if validation_bound:
                try:
                    from .terrain_validation import bind_active_controller

                    bind_active_controller(None)
                except Exception:  # noqa: BLE001
                    pass

        # ------------------------------------------------------------------
        # Bundle N post-pipeline QA safety net.
        # Runs only after a successful execution phase so the authored mask
        # stack is valid to inspect. The hook truthfully owns Bundle N's
        # always-on and opt-in runtime surfaces and attaches findings to the
        # final PassResult itself.
        # ------------------------------------------------------------------
        if results and results[-1].status != "failed":
            try:
                from .terrain_bundle_n import run_bundle_n_post_pipeline_hooks

                run_bundle_n_post_pipeline_hooks(
                    self,
                    results,
                    pre_pipeline_state=bundle_n_pre_pipeline_state,
                )
            except Exception as exc:  # noqa: BLE001
                # Bundle N post-pipeline QA is a safety net: never let it break
                # the main pipeline. Log at ERROR so the failure is visible, but
                # remain best-effort (S22-P0-38 / FIX-1.2).
                _log.error(
                    "Subsystem bundle_n_post_pipeline_hooks failed: %s",
                    exc, exc_info=exc,
                )

        return results

    # -- checkpoints ---------------------------------------------------------

    def _save_checkpoint(self, pass_name: str, result: PassResult) -> TerrainCheckpoint:
        """Persist the current mask stack to ``checkpoint_dir``.

        Populates Unity-export metadata (world_bounds, height range,
        cell_size, coordinate system) so the checkpoint can round-trip
        to a Unity importer without re-reading the mask stack.
        """
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_id = f"{pass_name}_{uuid.uuid4().hex[:8]}"
        mask_path = self.checkpoint_dir / f"{checkpoint_id}.npz"
        stack = self.state.mask_stack
        stack.to_npz(mask_path)

        parent_id = (
            self.state.checkpoints[-1].checkpoint_id
            if self.state.checkpoints
            else None
        )
        world_tile_extent = float(stack.tile_size) * float(stack.cell_size)
        world_bounds = BBox(
            min_x=float(stack.world_origin_x),
            min_y=float(stack.world_origin_y),
            max_x=float(stack.world_origin_x) + world_tile_extent,
            max_y=float(stack.world_origin_y) + world_tile_extent,
        )
        ckpt = TerrainCheckpoint(
            checkpoint_id=checkpoint_id,
            pass_name=pass_name,
            timestamp=time.time(),
            intent_hash=self.state.intent.intent_hash(),
            mask_stack_path=mask_path,
            geometry_snapshot_path=None,
            content_hash=result.content_hash_after or stack.compute_hash(),
            parent_checkpoint_id=parent_id,
            metrics=dict(result.metrics),
            world_bounds=world_bounds,
            height_min_m=stack.height_min_m,
            height_max_m=stack.height_max_m,
            cell_size_m=float(stack.cell_size),
            tile_size=int(stack.tile_size),
            coordinate_system=stack.coordinate_system,
            unity_export_schema_version=stack.unity_export_schema_version,
            water_network_snapshot=copy.deepcopy(self.state.water_network),
            viewport_vantage_snapshot=copy.deepcopy(self.state.viewport_vantage),
            side_effects_snapshot=list(self.state.side_effects),
            pass_history_len=len(self.state.pass_history),
        )
        return ckpt

    def rollback_to(self, checkpoint_id: str) -> None:
        """Rewind full pipeline state to a named checkpoint by id.

        Matches Houdini PDG rollback semantics:
          1. Load the mask stack from the checkpoint's .npz file.
          2. Validate that every channel shape in the restored stack matches
             the current grid dimensions (tile_size x tile_size + 1 for height,
             tile_size x tile_size for masks).  Shape mismatch raises ValueError
             rather than silently producing a mis-sized state.
          3. Restore water_network, side_effects, and pass_history to the
             snapshot captured at checkpoint time.
          4. Truncate the checkpoint list to the restored point so future
             checkpoints branch cleanly from it.
          5. Emit an INFO log with checkpoint id, pass name, and how many
             passes were rewound.
        """
        for ckpt in reversed(self.state.checkpoints):
            if ckpt.checkpoint_id == checkpoint_id:
                restored = TerrainMaskStack.from_npz(ckpt.mask_stack_path)

                # --- Shape validation against current grid ---
                current_shape = self.state.mask_stack.height.shape
                restored_shape = restored.height.shape
                if restored_shape != current_shape:
                    raise ValueError(
                        f"rollback_to '{checkpoint_id}': restored height shape "
                        f"{restored_shape} does not match current grid shape "
                        f"{current_shape}. Rollback aborted."
                    )
                # Validate all populated channels (skip opaque channels —
                # e.g. ``label_stack`` rebuilt as a live LabelStack — which
                # have no array-shape contract).  PR #57 round-4 fix
                # (CodeRabbit thread on PR #57): without this guard, a
                # rollback to any checkpoint taken after ``label_stamping``
                # crashes on the LabelStack object instead of restoring state.
                opaque = getattr(restored, "_OPAQUE_CHANNELS", ())
                for ch_name in list(restored.populated_by_pass.keys()):
                    if ch_name in opaque:
                        continue
                    ch_arr = restored.get(ch_name)
                    if ch_arr is None:
                        continue
                    if not hasattr(ch_arr, "shape"):
                        continue
                    if ch_arr.shape[:2] != current_shape[:2]:
                        raise ValueError(
                            f"rollback_to '{checkpoint_id}': channel '{ch_name}' "
                            f"shape {ch_arr.shape} incompatible with current grid "
                            f"{current_shape}. Rollback aborted."
                        )

                passes_rewound = (
                    len(self.state.pass_history) - ckpt.pass_history_len
                )

                self.state.mask_stack = restored
                self.state.water_network = copy.deepcopy(ckpt.water_network_snapshot)
                self.state.viewport_vantage = copy.deepcopy(
                    ckpt.viewport_vantage_snapshot
                )
                self.state.side_effects = list(ckpt.side_effects_snapshot)
                self.state.pass_history = self.state.pass_history[: ckpt.pass_history_len]

                # Truncate checkpoint history past the restored point
                idx = self.state.checkpoints.index(ckpt)
                self.state.checkpoints = self.state.checkpoints[: idx + 1]

                _log.info(
                    "rollback_to: restored to checkpoint '%s' (pass=%s); "
                    "rewound %d pass(es); %d checkpoint(s) remaining",
                    checkpoint_id,
                    ckpt.pass_name,
                    passes_rewound,
                    len(self.state.checkpoints),
                )
                return

        raise KeyError(f"Unknown checkpoint id: {checkpoint_id}")

    def rollback_last_checkpoint(self) -> None:
        if not self.state.checkpoints:
            raise RuntimeError("No checkpoints available to roll back to.")
        self.rollback_to(self.state.checkpoints[-1].checkpoint_id)


# ---------------------------------------------------------------------------
# Structural terrain label pass (Phase 10 / Fix 10.10 / REQ-P10-001)
# ---------------------------------------------------------------------------

def pass_compute_terrain_labels(
    state: "TerrainPipelineState",
    region: Optional[BBox],
) -> "PassResult":
    """Initialize structural terrain label channels (Fix 10.10 / REQ-P10-001).

    Each of the four label channels (rock_label, gravel_label, water_label,
    cliff_label) is initialized to zeros if not already stamped by a feature
    generator.  Feature generators that stamp a label during generation retain
    their authored mask unchanged — this pass only guarantees the channels are
    present so downstream passes never hit KeyError.

    Values are clamped to [0, 1] after stamping to guard against out-of-range
    inputs from feature generators (T-10-01-01).

    Contract:
        Requires: height
        Produces: rock_label, gravel_label, water_label, cliff_label
    """
    import time
    import numpy as np

    t0 = time.perf_counter()
    stack = state.mask_stack
    shape = stack.height.shape

    pre_stamped = 0
    coverage: dict = {}

    def _label_array(channel: str) -> "np.ndarray":
        nonlocal pre_stamped
        existing = stack.get(channel)
        if existing is not None:
            # Preserve generator-stamped mask; clamp to [0, 1] (T-10-01-01)
            clamped = np.clip(np.asarray(existing, dtype=np.float32), 0.0, 1.0)
            pre_stamped += 1
            coverage[channel] = float(np.mean(clamped > 0.0))
            return clamped
        coverage[channel] = 0.0
        return np.zeros(shape, dtype=np.float32)

    stack.set("rock_label", _label_array("rock_label"), "terrain_labels")
    stack.set("gravel_label", _label_array("gravel_label"), "terrain_labels")
    stack.set("water_label", _label_array("water_label"), "terrain_labels")
    stack.set("cliff_label", _label_array("cliff_label"), "terrain_labels")

    return PassResult(
        pass_name="terrain_labels",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("rock_label", "gravel_label", "water_label", "cliff_label"),
        metrics={
            "channels_pre_stamped": pre_stamped,
            "channels_zeroed": 4 - pre_stamped,
            **{f"coverage_{ch}": v for ch, v in coverage.items()},
        },
        issues=[],
    )


def register_terrain_label_passes() -> None:
    """Register the terrain_labels pass on TerrainPassController."""
    TerrainPassController.register_pass(
        PassDefinition(
            name="terrain_labels",
            func=pass_compute_terrain_labels,
            requires_channels=("height",),
            produces_channels=("rock_label", "gravel_label", "water_label", "cliff_label"),
            seed_namespace="terrain_labels",
            requires_scene_read=False,
            may_modify_geometry=False,
            description=(
                "Structural terrain labeling: initializes label channels; "
                "feature generators stamp during generation."
            ),
        )
    )


# ---------------------------------------------------------------------------
# Biome/corruption channel pass (Phase 2 writer contract)
# ---------------------------------------------------------------------------


def pass_compute_biome_channels(
    state: "TerrainPipelineState",
    region: Optional[BBox],
) -> "PassResult":
    """Populate numeric biome and corruption maps for downstream readers."""
    import time
    import numpy as np

    from ._biome_grammar import generate_world_map_spec

    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = dict(getattr(state.intent, "composition_hints", {}) or {})
    height = np.asarray(stack.height)
    rows, cols = height.shape
    biome_count = int(hints.get("biome_count", 6))
    biome_count = max(1, min(biome_count, 32))
    corruption_level = float(hints.get("corruption_level", 0.0))
    spec = generate_world_map_spec(
        width=cols,
        height=rows,
        world_size=float(stack.tile_size) * float(stack.cell_size),
        biome_count=biome_count,
        biomes=hints.get("biomes"),
        seed=int(getattr(state.intent, "seed", 0)),
        corruption_level=corruption_level,
        transition_width_m=float(hints.get("transition_width_m", 15.0)),
    )
    stack.set("biome_id", spec.biome_ids.astype(np.int32), "biome_channels")
    stack.set("corruption_map", spec.corruption_map.astype(np.float32), "biome_channels")
    # PR #55 review fix (threads #1 / #4): ``spec.biome_ids`` are Voronoi
    # indices into ``spec.biome_names`` (0..biome_count-1), NOT canonical
    # palette bucket indices. Downstream consumers (``compute_macro_color``,
    # ``terrain_caves``, ``terrain_unity_export``) need the per-cell
    # canonical biome name to translate via ``BIOME_BUCKET_MAP_18_TO_14``
    # to the 14-bucket render palette. Stamp the ordered name list onto
    # the stack so consumers can do ``biome_names[biome_id_value]``.
    setattr(stack, "biome_names", list(spec.biome_names))

    return PassResult(
        pass_name="biome_channels",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("biome_id", "corruption_map"),
        metrics={
            "biome_count": int(len(set(spec.biome_ids.ravel().tolist()))),
            "corruption_mean": float(spec.corruption_map.mean()),
            "region_scoped": region is not None,
        },
    )


def register_biome_channel_pass() -> None:
    """Register the biome_channels pass on TerrainPassController."""
    TerrainPassController.register_pass(
        PassDefinition(
            name="biome_channels",
            func=pass_compute_biome_channels,
            requires_channels=("height",),
            produces_channels=("biome_id", "corruption_map"),
            seed_namespace="biome_channels",
            requires_scene_read=False,
            may_modify_geometry=False,
            description="Populate biome_id and corruption_map from deterministic world-map grammar.",
        )
    )


# ---------------------------------------------------------------------------
# Snow line pass (Phase 10 / Fix 10.5 / REQ-P10-006)
# ---------------------------------------------------------------------------


def pass_compute_snow_line(
    state: "TerrainPipelineState",
    region: Optional[BBox],
) -> "PassResult":
    """Compute and write snow_line_factor channel (Fix 10.5 / REQ-P10-006).

    Contract:
        Consumes: height (normalized 0-1), slope (radians)
        Produces: snow_line_factor
    """
    import time
    import numpy as np

    from .terrain_materials_v2 import compute_snow_line_factor as _compute_snow

    t0 = time.perf_counter()
    stack = state.mask_stack

    # Normalize height to 0-1 using stack's declared range
    raw_height = np.asarray(stack.height, dtype=np.float32)
    h_min = float(getattr(stack, "height_min_m", None) or raw_height.min())
    h_max = float(getattr(stack, "height_max_m", None) or raw_height.max())
    h_range = h_max - h_min if (h_max - h_min) > 1e-9 else 1.0
    height_norm = ((raw_height - h_min) / h_range).astype(np.float32)

    slope = stack.get("slope")
    if slope is None:
        slope = np.zeros_like(height_norm)

    climate_params: dict = {}
    if state.intent is not None:
        intent_dict = getattr(state.intent, "__dict__", {})
        climate_params = intent_dict.get("climate_params", {}) or {}

    factor = _compute_snow(height_norm, slope, climate_params)
    stack.set("snow_line_factor", factor, "snow_line")

    return PassResult(
        pass_name="snow_line",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "slope"),
        produced_channels=("snow_line_factor",),
        metrics={"snow_coverage_mean": float(factor.mean())},
    )


def register_snow_line_pass() -> None:
    """Register the snow_line pass on TerrainPassController."""
    TerrainPassController.register_pass(
        PassDefinition(
            name="snow_line",
            func=pass_compute_snow_line,
            requires_channels=("height",),
            optional_channels=("slope",),
            produces_channels=("snow_line_factor",),
            seed_namespace="snow_line",
            requires_scene_read=False,
            may_modify_geometry=False,
            description="Compute snow_line_factor: sigmoid altitude curve modulated by slope.",
        )
    )


# ---------------------------------------------------------------------------
# W-2: Water depth + shoreline blend pass
# ---------------------------------------------------------------------------

import numpy as _np  # noqa: E402


def pass_water_depth(
    state: "TerrainPipelineState",
    region: "BBox | None",
) -> "PassResult":
    """Compute water_depth_m and shoreline_blend from elevation channels.

    Writes:
        water_depth_m    — float32 (H, W), metres of water above terrain (>= 0).
        shoreline_blend  — float32 (H, W) in [0, 1]; 0 = dry, 1 = fully
                           submerged.  Cubic smoothstep over a 0.5 m blend zone.

    Reads:
        water_surface_elevation_m  — water surface elevation in world metres
        height_m / height          — terrain DEM (height_m preferred)

    Must run after pass_hydrology (which writes water_surface_elevation_m when
    available) and after any pass that produces height_m.
    """
    import time as _time
    from .terrain_semantics import PassResult

    t0 = _time.perf_counter()
    stack = state.mask_stack

    ws_elev = stack.get("water_surface_elevation_m")
    # Cannot use ``a or b`` on numpy arrays — ndarray truthy raises
    # ValueError ("ambiguous").  Use explicit None check instead.
    height = stack.get("height_m")
    if height is None:
        height = stack.get("height")

    if ws_elev is None or height is None:
        return PassResult(
            pass_name="pass_water_depth",
            status="skipped",
            duration_seconds=_time.perf_counter() - t0,
            issues=[],
        )

    ws_arr = _np.asarray(ws_elev, dtype=_np.float32)
    h_arr = _np.asarray(height, dtype=_np.float32)

    depth = _np.ascontiguousarray(_np.maximum(ws_arr - h_arr, 0.0).astype(_np.float32))
    # water_depth_m and shoreline_blend are now declared dataclass fields on
    # TerrainMaskStack (commit e2b8043) and registered in _ARRAY_CHANNELS, so
    # the canonical stack.set(...) path provides version stamping + dirty
    # channel tracking.
    stack.set("water_depth_m", depth, "pass_water_depth")

    # Shoreline blend: smooth 0.5 m transition zone, cubic smoothstep
    shoreline_blend = _np.clip(depth / 0.5, 0.0, 1.0)
    shoreline_blend = (shoreline_blend * shoreline_blend * (3.0 - 2.0 * shoreline_blend)).astype(_np.float32)
    stack.set("shoreline_blend", _np.ascontiguousarray(shoreline_blend), "pass_water_depth")

    return PassResult(
        pass_name="pass_water_depth",
        status="ok",
        duration_seconds=_time.perf_counter() - t0,
        produced_channels=("water_depth_m", "shoreline_blend"),
        consumed_channels=("water_surface_elevation_m", "height_m", "height"),
        metrics={
            "depth_max_m": float(depth.max()),
            "depth_mean_m": float(depth.mean()),
            "wet_cell_pct": round(float((_np.asarray(depth) > 0).sum()) / max(depth.size, 1) * 100.0, 2),
        },
        issues=[],
    )


def register_pass_water_depth() -> None:
    """Register pass_water_depth with TerrainPassController (W-2 fix)."""
    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_water_depth",
            func=pass_water_depth,
            requires_channels=("height",),
            optional_channels=("water_surface_elevation_m",),
            produces_channels=("water_depth_m", "shoreline_blend"),
            seed_namespace="",
            requires_scene_read=False,
            description=(
                "W-2: compute water_depth_m = max(ws_elev - height, 0) and "
                "shoreline_blend smoothstep. Skips gracefully when "
                "water_surface_elevation_m is absent."
            ),
        )
    )


# ---------------------------------------------------------------------------
# Default pass registration
# ---------------------------------------------------------------------------


def _toposort_passes(
    definitions: "list[PassDefinition]",
) -> "list[PassDefinition]":
    """Return a topological ordering of pass definitions by channel dependency.

    Algorithm: Kahn's BFS.  An edge A→B exists when pass B requires a channel
    that pass A produces — UNLESS pass B also declares ``overrides=(c, ...)``
    for that channel, in which case the edge is suppressed.  Rationale: a
    pass that overrides a channel is the authoritative writer for it (per the
    ``ChannelOwnershipError`` registration check at line ~470); requiring
    that channel as input plus declaring it as overridden tells the DAG
    "I read whatever value happens to be there, then replace it." Treating
    the producer as a hard prerequisite would force a strict ordering where
    the spec only intends a soft "if a producer ran, fine" semantic, and
    this is what creates dual-cycles when two passes both override the same
    channel and require each other's primary channel (e.g.
    ``terrain_banded`` ↔ ``terrain_morphology`` on ``height``).

    Passes with no channel dependencies appear first; passes that only consume
    channels produced by earlier passes appear after their producers.  Within
    the same dependency level, original registration order is preserved
    (stable sort).

    Raises ``ValueError`` on a cycle that survives override suppression —
    which indicates a circular dependency the override mechanism cannot
    resolve.
    """
    name_to_def: "dict[str, PassDefinition]" = {d.name: d for d in definitions}

    # Build the channel→producers map
    channel_producers: "dict[str, list[str]]" = {}
    for d in definitions:
        for ch in d.produces_channels:
            channel_producers.setdefault(ch, []).append(d.name)

    # Build adjacency list: for each pass, which passes must run before it.
    # Per §11.1 PR #3: when pass B requires channel c AND c is in B.overrides,
    # suppress the edge A→B for that channel — B is the authoritative writer
    # and accepts whatever input value exists rather than blocking on a
    # specific producer's output. Other edges (via channels not in overrides)
    # are still added, so a producer that B genuinely depends on through a
    # different channel still orders before B.
    in_edges: "dict[str, set[str]]" = {d.name: set() for d in definitions}
    for d in definitions:
        overridden_channels = frozenset(d.overrides)
        for ch in d.requires_channels:
            if ch in overridden_channels:
                continue
            for producer in channel_producers.get(ch, []):
                if producer != d.name:
                    in_edges[d.name].add(producer)

    # Kahn's algorithm
    in_degree: "dict[str, int]" = {name: len(deps) for name, deps in in_edges.items()}
    queue: "list[str]" = [
        d.name for d in definitions if in_degree[d.name] == 0
    ]
    ordered: "list[str]" = []

    while queue:
        # Pop in original-registration order for stability
        nxt = queue.pop(0)
        ordered.append(nxt)
        # Reduce in-degree for passes that depended on nxt
        for d in definitions:
            if nxt in in_edges[d.name]:
                in_edges[d.name].discard(nxt)
                in_degree[d.name] -= 1
                if in_degree[d.name] == 0:
                    queue.append(d.name)

    if len(ordered) != len(definitions):
        cycle_names = [d.name for d in definitions if d.name not in ordered]
        raise ValueError(
            f"register_default_passes: cycle detected in pass dependency graph "
            f"involving: {cycle_names}"
        )

    result = [name_to_def[n] for n in ordered]
    _log.debug(
        "_toposort_passes: topological order = %s",
        [d.name for d in result],
    )
    return result


def register_default_passes(*, strict: bool = False) -> None:
    """Register the Bundle A default passes on the controller with full DAG validation.

    Matches UE5 World Partition DAG registration semantics:
      1. Collect all PassDefinition objects (does NOT auto-register — call
         this function or import ``_terrain_world`` to activate; lets unit
         tests start from an empty registry).
      2. **Channel prerequisite check**: before registering, verify that every
         ``requires_channels`` entry is produced by at least one other pass in
         the batch.  Passes that consume externally-supplied channels (e.g.
         ``height`` already on the mask stack) are exempted from this check
         because those channels may be present at runtime even without a
         registered producer.  An unresolvable dependency emits a WARNING
         rather than raising, so the pipeline degrades gracefully.
      3. **Cycle detection + topological sort**: the full dependency graph is
         checked for cycles (``ValueError`` on cycle); passes are registered
         in topological order so the registry reflects a valid execution
         sequence.
      4. **Registration order log**: logs the final ordered pass names at INFO
         level so pipeline wiring is always auditable.
    """
    # Lazy import to avoid circular dependency at module load time.
    from . import _terrain_world as _tw

    # ----- Collect all definitions -----
    raw_definitions: "list[PassDefinition]" = [
        PassDefinition(
            name="macro_world",
            func=_tw.pass_macro_world,
            requires_channels=(),
            produces_channels=("height", "hmap_low_freq"),
            seed_namespace="macro_world",
            may_modify_geometry=False,
            requires_scene_read=False,
        ),
        PassDefinition(
            name="pass_generate_low_freq_hmap",
            func=_tw.pass_generate_low_freq_hmap,
            requires_channels=(),
            produces_channels=("height", "hmap_low_freq"),
            # OVERRIDE: ``macro_world`` also produces (height, hmap_low_freq).
            # The 12.1 decomposition split the base heightmap into explicit
            # low_freq/high_freq bands so callers can drive downstream passes
            # without re-running the legacy ``macro_world`` monolith. Declaring
            # the override makes the intentional overwrite explicit.
            overrides=("height", "hmap_low_freq"),
            seed_namespace="macro_world",
            may_modify_geometry=False,
            requires_scene_read=False,
            description="Generate low-freq base heightmap (Fix 12.1)",
        ),
        PassDefinition(
            name="pass_generate_high_freq_detail",
            func=_tw.pass_generate_high_freq_detail,
            requires_channels=(),
            produces_channels=("hmap_high_freq",),
            seed_namespace="macro_world_detail",
            may_modify_geometry=False,
            requires_scene_read=False,
            description="Generate high-freq detail noise band (Fix 12.1)",
        ),
        PassDefinition(
            name="structural_masks",
            func=_tw.pass_structural_masks,
            requires_channels=("height",),
            produces_channels=(
                "slope",
                "curvature",
                "concavity",
                "convexity",
                "ridge",
                "basin",
                "saliency_macro",
                "hero_exclusion",
            ),
            seed_namespace="structural_masks",
            requires_scene_read=False,
            supports_region_scope=False,
        ),
        PassDefinition(
            name="structural_masks_post_erosion",
            func=_tw.pass_structural_masks,
            requires_channels=("height",),
            produces_channels=(
                "slope",
                "curvature",
                "concavity",
                "convexity",
                "ridge",
                "basin",
                "saliency_macro",
                "hero_exclusion",
            ),
            overrides=(
                "slope",
                "curvature",
                "concavity",
                "convexity",
                "ridge",
                "basin",
                "saliency_macro",
                "hero_exclusion",
            ),
            seed_namespace="structural_masks_post_erosion",
            requires_scene_read=False,
            supports_region_scope=False,
            description=(
                "Recompute structural terrain masks after erosion/composite height "
                "updates so downstream water, scatter, materials, and validation "
                "consume current slope/curvature/ridge fields."
            ),
        ),
        PassDefinition(
            name="structural_masks_post_talus",
            func=_tw.pass_structural_masks,
            requires_channels=("height",),
            produces_channels=(
                "slope",
                "curvature",
                "concavity",
                "convexity",
                "ridge",
                "basin",
                "saliency_macro",
                "hero_exclusion",
            ),
            overrides=(
                "slope",
                "curvature",
                "concavity",
                "convexity",
                "ridge",
                "basin",
                "saliency_macro",
                "hero_exclusion",
            ),
            seed_namespace="structural_masks_post_talus",
            requires_scene_read=False,
            supports_region_scope=False,
            description=(
                "Recompute structural terrain masks after talus mutates height "
                "so materials_v2 and scatter consume current slope/curvature fields."
            ),
        ),
        PassDefinition(
            name="structural_masks_post_deltas",
            func=_tw.pass_structural_masks,
            requires_channels=("height",),
            produces_channels=(
                "slope",
                "curvature",
                "concavity",
                "convexity",
                "ridge",
                "basin",
                "saliency_macro",
                "hero_exclusion",
            ),
            overrides=(
                "slope",
                "curvature",
                "concavity",
                "convexity",
                "ridge",
                "basin",
                "saliency_macro",
                "hero_exclusion",
            ),
            seed_namespace="structural_masks_post_deltas",
            requires_scene_read=False,
            supports_region_scope=False,
            description=(
                "PR-F2 (cross-audit P0 2026-05-09): recompute structural terrain "
                "masks AFTER ``integrate_deltas`` composes coastline_delta + "
                "stratigraphy_delta + worn-path/road_worn_path_delta + "
                "wind_erosion_delta + others into ``height``. Without this "
                "recompute, downstream materials_v2 / scatter_intelligent / "
                "label_stamping / topographic_indices would consume slope, "
                "curvature, ridge, etc. derived from the PRE-delta surface — "
                "which is exactly the audit-reported pass-order rot. Identical "
                "function to structural_masks_post_erosion / _post_talus; the "
                "name disambiguates the schedule slot for census tracking."
            ),
        ),
        PassDefinition(
            name="erosion",
            func=_tw.pass_erosion,
            requires_channels=("hmap_low_freq",),
            produces_channels=(
                "height",
                "hmap_low_freq",
                "erosion_amount",
                "deposition_amount",
                "wetness",
                "drainage",
                "bank_instability",
                "talus",
                "pool_deepening_delta",
                "sediment_accumulation_at_base",
                # Refined ridge field — declared producer so the PassDAG knows
                # ``pass_erosion`` owns ``ridge_eroded``. ``ridge`` (raw) stays
                # owned by ``structural_masks`` upstream.
                "ridge_eroded",
            ),
            # OVERRIDE: ``macro_world`` / ``pass_generate_low_freq_hmap`` produce
            # the initial (height, hmap_low_freq) pair; ``erosion`` deliberately
            # rewrites them with hydraulically-eroded values. This is the Gaea /
            # World Machine "macro → erosion" staged-pipeline pattern — the
            # second writer is correct, not accidental.
            overrides=("height", "hmap_low_freq"),
            seed_namespace="erosion",
            requires_scene_read=True,
        ),
        PassDefinition(
            name="pass_composite_hmap",
            func=_tw.pass_composite_hmap,
            requires_channels=("hmap_low_freq", "hmap_high_freq"),
            produces_channels=("height",),
            # OVERRIDE: composite of eroded low-freq + detail high-freq writes
            # the FINAL height used by downstream passes. Upstream ``erosion``
            # already wrote ``height`` from eroded low-freq alone; this pass
            # finishes the Fix 12.1 decomposition by adding high-freq detail.
            overrides=("height",),
            seed_namespace="",
            may_modify_geometry=False,
            requires_scene_read=False,
            description="Composite eroded low-freq + high-freq detail into final height (Fix 12.1)",
        ),
        PassDefinition(
            name="validation_minimal",
            func=_tw.pass_validation_minimal,
            requires_channels=("height", "slope"),
            produces_channels=(),
            seed_namespace="validation_minimal",
            may_modify_geometry=False,
            respects_protected_zones=False,
            requires_scene_read=False,
        ),
    ]

    if raw_definitions:
        # ----- Channel prerequisite check -----
        all_produced: "set[str]" = set()
        for d in raw_definitions:
            all_produced.update(d.produces_channels)

        for d in raw_definitions:
            for ch in d.requires_channels:
                if ch not in all_produced:
                    _log.warning(
                        "register_default_passes: pass '%s' requires channel '%s' "
                        "which no registered pass produces — expected on mask stack "
                        "at runtime (e.g. height supplied by caller).",
                        d.name, ch,
                    )

        # ----- Cycle detection + topological sort -----
        try:
            ordered = _toposort_passes(raw_definitions)
        except ValueError as exc:
            _log.error("register_default_passes: %s", exc)
            ordered = raw_definitions  # fall back to declaration order

        # ----- Register in topological order -----
        for definition in ordered:
            TerrainPassController.register_pass(definition, strict=strict)

        _log.info(
            "register_default_passes: registered %d passes in order: %s",
            len(ordered),
            [d.name for d in ordered],
        )

    # Supplemental passes (always register after core DAG)
    from ._water_network import (
        register_pass_hydrology,
        register_pass_river_convergence,
        register_pass_water_flow_speed,
    )
    from .terrain_delta_integrator import register_integrator_pass
    register_integrator_pass()
    # Hydrology is a foundational derived field for downstream water-aware passes.
    register_pass_hydrology()
    # Manning flow-speed map: must run after pass_hydrology (requires flow_direction,
    # flow_accumulation). Produces flow_speed channel consumed by water VC encoding.
    register_pass_water_flow_speed()
    # River-mouth / confluence transition masks depend on hydrology + downstream water.
    register_pass_river_convergence()
    # W-2: water_depth_m + shoreline_blend — requires water_surface_elevation_m
    # which is emitted by pass_water_variants / pass_hydrology when elevation data
    # is available.  Skips gracefully when that channel is absent.
    register_pass_water_depth()
    register_biome_channel_pass()
    register_terrain_label_passes()
    # Phase C D30-32 (Issue #27) — structural label-stamping. Optional in the
    # default sequence (gated by composition_hints["label_stamping"]) so
    # existing fixtures stay byte-identical. Registered here directly via the
    # canonical PassDefinition so terrain_labels does NOT have to import
    # terrain_pipeline (avoids the static CodeQL cycle).
    from .terrain_labels import label_stamping_pass_definition
    TerrainPassController.register_pass(label_stamping_pass_definition())
    register_snow_line_pass()
    # Phase C D35: pass_topographic_indices emits vb_aspect_deg /
    # vb_aspect_north / vb_canopy_openness / vb_TWI from height (post-erosion,
    # post-composite). Foliage / scatter consumers read them via
    # optional_channels declarations.
    # Use the broker pattern (PassDefinition factory) so terrain_topographic_indices
    # never has to import terrain_pipeline — avoids CodeQL static cycle.
    from .terrain_topographic_indices import topographic_indices_pass_definition
    TerrainPassController.register_pass(topographic_indices_pass_definition())
    from ._biome_grammar import register_biome_surface_features_pass
    register_biome_surface_features_pass()
    # pass_seasonal_water_state registers AFTER Bundle O/I in terrain_master_registrar
    # so that water_variants and coastline own water_surface_mask/tidal first.
    # macro_color is owned by Bundle K (see terrain_macro_color.pass_macro_color).
    # The orphan ``pass_compute_macro_color`` helper that used to live here was
    # never auto-registered and has been removed (deep-dive guide 2026-04-20).


__all__ = [
    "TerrainPassController",
    "PipelineSubsystemError",
    "_PASS_MODULE_REGISTRY",
    "build_default_pass_sequence",
    "derive_pass_seed",
    "register_default_passes",
    "pass_compute_biome_channels",
    "register_biome_channel_pass",
    "pass_compute_terrain_labels",
    "register_terrain_label_passes",
    "pass_compute_snow_line",
    "register_snow_line_pass",
    "pass_water_depth",
    "register_pass_water_depth",
]


# Phase C D30-32 — structural label types live in ``terrain_labels``.
# We DO NOT re-export them at module top here because that creates a
# CodeQL-flagged static import cycle (terrain_pipeline -> terrain_labels
# -> terrain_pipeline). Callers should import directly:
#     from veilbreakers_terrain.handlers.terrain_labels import LabelStamp
#
# A lazy `__getattr__` provides backwards-compat for callers that still
# reach for these on terrain_pipeline; it imports terrain_labels on first
# access (after both modules are fully loaded), avoiding the cycle.
def __getattr__(name: str) -> object:
    """Lazy attribute access for terrain_labels re-exports (PEP 562)."""
    _label_exports = {
        "LABEL_TO_LEGACY_CHANNEL",
        "LabelStack",
        "LabelStamp",
        "STRUCTURAL_LABELS",
        "pass_label_stamping",
        "label_stamping_pass_definition",
    }
    if name in _label_exports:
        from . import terrain_labels  # local import, after both modules loaded
        return getattr(terrain_labels, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
