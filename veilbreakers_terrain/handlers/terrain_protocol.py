"""Bundle R — runtime protocol enforcement.

Turns the 7 rules from TERRAIN_EDITING_PROTOCOL.md into callable Python gates
that any terrain mutation handler can route through. Any gate failure raises
``ProtocolViolation`` — the handler is expected to let this propagate.

See docs/terrain_ultra_implementation_plan_2026-04-08.md Addendum 1.A.2 for
the authoritative spec of each rule.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Optional

from .terrain_semantics import (
    TerrainPipelineState,
)

TERRAIN_ADDON_MIN_VERSION = (1, 0, 0)

# Default thresholds per Addendum 1.A.2
DEFAULT_SCENE_READ_MAX_AGE_S = 300.0
DEFAULT_BULK_EDIT_CELL_FRACTION = 0.02  # > 2% of tile cells = bulk
DEFAULT_BULK_EDIT_OBJECT_COUNT = 20
VALID_PLACEMENT_CLASSES = frozenset(
    {"surface", "interior", "above_surface", "below_surface"}
)


class ProtocolViolation(RuntimeError):
    """Raised when a terrain mutation bypasses one of the 7 enforced rules.

    Attributes:
        rule_number: Integer 1–7 identifying which rule was violated, or 0 if
                     unknown/multiple.
        severity:    'hard' (operation must abort) or 'soft' (warning-level;
                     current policy always aborts, but callers may inspect to
                     route differently in future).
        description: Human-readable explanation of the violation including the
                     corrective action.

    The string representation is ``"rule_<N>/<severity>: <description>"`` so
    log lines are greppable without parsing the exception attributes.
    """

    def __init__(
        self,
        description: str,
        *,
        rule_number: int = 0,
        severity: str = "hard",
    ) -> None:
        self.rule_number = int(rule_number)
        self.severity = str(severity)
        self.description = str(description)
        tag = f"rule_{self.rule_number}/{self.severity}: " if self.rule_number else ""
        super().__init__(f"{tag}{self.description}")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"ProtocolViolation(rule_number={self.rule_number!r}, "
            f"severity={self.severity!r}, description={self.description!r})"
        )


class ProtocolGate:
    """The 7 terrain-editing rules, as callable static gates.

    Each rule takes whatever context it needs (state and/or params dict)
    and either returns ``None`` on success or raises ``ProtocolViolation``.
    """

    @staticmethod
    def rule_1_observe_before_calculate(
        state: TerrainPipelineState,
        *,
        max_age_s: float = DEFAULT_SCENE_READ_MAX_AGE_S,
        now: Optional[float] = None,
    ) -> None:
        """Assert a TerrainSceneRead was captured recently enough."""
        sr = state.intent.scene_read
        if sr is None:
            raise ProtocolViolation(
                "no TerrainSceneRead attached to intent — "
                "capture one via terrain_scene_read.capture_scene_read() first.",
                rule_number=1,
                severity="hard",
            )
        current = time.time() if now is None else now
        age = current - float(sr.timestamp)
        if age < 0:
            # Clock skew / synthetic tests — treat as fresh
            age = 0.0
        if age > max_age_s:
            raise ProtocolViolation(
                f"scene_read is {age:.0f}s old (max {max_age_s:.0f}s). "
                "Re-capture before running further mutations.",
                rule_number=1,
                severity="hard",
            )
        # FIX-B14-P1-44: lock every anchor declared on the intent so that
        # Rule 3 (rule_3_lock_reference_empties) can detect drift on
        # subsequent runs.  lock_anchor is idempotent — re-locking the same
        # anchor to the same position is a no-op for drift purposes.
        # Import inside the method to avoid a circular import at module load
        # (terrain_protocol ← terrain_semantics ← terrain_reference_locks).
        try:
            from .terrain_reference_locks import lock_anchor as _lock_anchor
            for anchor in getattr(state.intent, "anchors", None) or []:
                _lock_anchor(anchor)
        except Exception:  # noqa: BLE001
            pass  # non-fatal: anchor locking is best-effort at Rule 1

    @staticmethod
    def rule_2_sync_to_user_viewport(
        state: TerrainPipelineState,
        *,
        out_of_view_ok: bool = False,
    ) -> None:
        """Require that a ViewportVantage is attached to the pipeline state,
        or that the caller explicitly opts out via ``out_of_view_ok=True``.

        ``TerrainPipelineState.viewport_vantage`` is a declared ``Optional[Any]``
        field (default ``None``).  Headless / automated pipeline runs that have
        no Blender viewport open should pass ``out_of_view_ok=True`` (or supply
        the vantage) so that Rule 2 is satisfied without raising.

        When ``viewport_vantage`` is ``None`` and ``out_of_view_ok`` is not set,
        the gate raises :class:`ProtocolViolation`. Automated/headless callers
        must pass ``out_of_view_ok=True`` explicitly.

        Args:
            state: current pipeline state; ``state.viewport_vantage`` is read.
            out_of_view_ok: suppress the Rule 2 check entirely (e.g. headless CI).
        """
        if out_of_view_ok:
            return
        vantage = state.viewport_vantage  # declared field — no getattr fallback needed
        if vantage is None:
            raise ProtocolViolation(
                "Protocol Rule 2: viewport_vantage is None but out_of_view_ok=False. "
                "Cannot verify out-of-view readability. "
                "Call terrain_viewport_sync.read_user_vantage() and assign the result "
                "to state.viewport_vantage, or pass out_of_view_ok=True for headless runs.",
                rule_number=2,
                severity="hard",
            )

    @staticmethod
    def rule_3_lock_reference_empties(
        state: TerrainPipelineState,
        *,
        tolerance: float = 0.01,
    ) -> None:
        """Assert every locked anchor still matches its recorded position."""
        # Import here to avoid circular dependency at module load.
        from .terrain_reference_locks import assert_all_anchors_intact

        reports = assert_all_anchors_intact(state.intent, tolerance=tolerance)
        drifted = [r for r in reports if r.drifted]
        if drifted:
            names = ", ".join(r.anchor_name for r in drifted)
            raise ProtocolViolation(
                f"anchor drift detected for: {names}. "
                "Re-lock anchors or revert the drifting mutation.",
                rule_number=3,
                severity="hard",
            )

    # Canonical set of hero feature kinds that require real mesh additions.
    # Kept in sync with terrain_hierarchy.cinematic_kinds — if you add a kind
    # there, add it here too.  Previously this was a hardcoded local set that
    # diverged from hierarchy (cliff/cave/waterfall vs canyon/arch/megaboss_arena
    # /sanctum/waterfall).  Now unified: any cinematic-tier hero feature is
    # forbidden from using vertex-color fakes.
    HERO_MESH_REQUIRED_KINDS: "frozenset[str]" = frozenset(
        {
            # From terrain_hierarchy.cinematic_kinds
            "canyon",
            "waterfall",
            "arch",
            "megaboss_arena",
            "sanctum",
            # Additional hero kinds always requiring real geometry
            "cliff",
            "cave",
        }
    )

    @staticmethod
    def rule_4_real_geometry_not_vertex_tricks(params: dict) -> None:
        """Forbid vertex-color-only fakes for any hero / cinematic feature kind.

        Hero features (cliffs, caves, waterfalls, canyons, arches, boss arenas,
        sanctums) must land as real mesh additions in the scene.  A pass that
        sets ``vertex_color_fake=True`` for any of these kinds is a protocol
        violation — vertex-color tricks produce visually convincing screenshots
        but break navmesh baking, physics colliders, and LOD generation.

        The allowed hero kinds are defined in ``HERO_MESH_REQUIRED_KINDS`` and
        intentionally mirror ``terrain_hierarchy.cinematic_kinds`` so there is
        a single canonical list.  If you add a new cinematic kind to the
        hierarchy, add it here too.

        Args:
            params: mutation parameter dict.  Relevant keys:
                ``feature_kind`` (str) — the kind being placed.
                ``vertex_color_fake`` (bool) — True if the caller wants to skip
                    real geometry and use vertex-color shading only.
        """
        feature_kind = str(params.get("feature_kind", "")).lower()
        if feature_kind in ProtocolGate.HERO_MESH_REQUIRED_KINDS and bool(
            params.get("vertex_color_fake", False)
        ):
            raise ProtocolViolation(
                f"hero feature '{feature_kind}' cannot be a vertex-color fake. "
                f"All cinematic-tier hero features "
                f"({sorted(ProtocolGate.HERO_MESH_REQUIRED_KINDS)}) "
                "must land as real mesh additions.",
                rule_number=4,
                severity="hard",
            )

    @staticmethod
    def rule_5_smallest_diff_per_iteration(
        state: TerrainPipelineState,
        *,
        cells_affected: int = 0,
        objects_affected: int = 0,
        bulk_edit: bool = False,
        cell_fraction_threshold: float = DEFAULT_BULK_EDIT_CELL_FRACTION,
        object_count_threshold: int = DEFAULT_BULK_EDIT_OBJECT_COUNT,
    ) -> None:
        """Reject pass-sized mutations without an explicit ``bulk_edit=True``."""
        if bulk_edit:
            return
        tile_cells = max(1, state.mask_stack.height.size)
        cell_frac = cells_affected / tile_cells
        if cell_frac > cell_fraction_threshold:
            raise ProtocolViolation(
                f"mutation affects {cell_frac*100:.1f}% of tile "
                f"(threshold {cell_fraction_threshold*100:.0f}%). "
                "Use a region-scoped pass or set bulk_edit=True.",
                rule_number=5,
                severity="hard",
            )
        if objects_affected > object_count_threshold:
            raise ProtocolViolation(
                f"mutation affects {objects_affected} objects "
                f"(threshold {object_count_threshold}). "
                "Split into smaller edits or set bulk_edit=True.",
                rule_number=5,
                severity="hard",
            )

    @staticmethod
    def rule_6_surface_vs_interior_classification(params: dict) -> None:
        """Every placed object must carry a valid ``placement_class`` tag."""
        placements = params.get("placements") or []
        if not isinstance(placements, list):
            return
        bad: list[str] = []
        for idx, placement in enumerate(placements):
            if not isinstance(placement, dict):
                continue
            pc = placement.get("placement_class")
            if pc not in VALID_PLACEMENT_CLASSES:
                bad.append(f"[{idx}] {placement.get('id', 'anon')!r}: {pc!r}")
        if bad:
            raise ProtocolViolation(
                "invalid placement_class on: "
                + ", ".join(bad)
                + f". Must be one of {sorted(VALID_PLACEMENT_CLASSES)}.",
                rule_number=6,
                severity="hard",
            )

    @staticmethod
    def rule_7_plugin_usage(params: Optional[dict] = None) -> None:
        """Require the vb-blender addon to be loaded at the expected version."""
        from .terrain_addon_health import assert_addon_version_matches

        assert_addon_version_matches(TERRAIN_ADDON_MIN_VERSION)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def enforce_protocol(
    *,
    require_rule_1: bool = True,
    require_rule_2: bool = True,
    require_rule_3: bool = True,
    require_rule_4: bool = True,
    require_rule_5: bool = True,
    require_rule_6: bool = True,
    require_rule_7: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that enforces all 7 terrain-editing protocol gates before a handler runs.

    Wrap any terrain mutation handler with this decorator to guarantee that the
    7 rules from ``TERRAIN_EDITING_PROTOCOL.md`` are checked at every call site.
    Any gate failure raises :class:`ProtocolViolation` and the wrapped handler
    body is never entered.

    The decorated function **must** accept:
      - ``state: TerrainPipelineState`` as its first positional argument.
      - ``params: dict | None`` as its second positional argument.

    Additional positional and keyword arguments are forwarded unchanged.

    Rule toggle kwargs (all default ``True``) let test fixtures opt out of
    gates that require a live Blender scene or addon:

    - ``require_rule_1`` — scene_read freshness (Rule 1)
    - ``require_rule_2`` — viewport vantage sync (Rule 2)
    - ``require_rule_3`` — reference-empty anchor drift (Rule 3)
    - ``require_rule_4`` — no vertex-color fakes for hero features (Rule 4)
    - ``require_rule_5`` — smallest-diff / bulk_edit guard (Rule 5)
    - ``require_rule_6`` — placement_class tags (Rule 6)
    - ``require_rule_7`` — addon version check (Rule 7)

    Example::

        @enforce_protocol(require_rule_7=False)  # skip addon check in CI
        def my_pass(state: TerrainPipelineState, params: dict) -> PassResult:
            ...

    Params extracted from the ``params`` dict by the wrapper:
      - ``out_of_view_ok`` (bool)  — Rule 2 opt-out for headless runs.
      - ``cells_affected`` (int)   — Rule 5 cell count.
      - ``objects_affected`` (int) — Rule 5 object count.
      - ``bulk_edit`` (bool)       — Rule 5 bulk override.
      - ``placements`` (list)      — Rule 6 placement descriptor list.
      - ``feature_kind`` (str)     — Rule 4 hero kind.
      - ``vertex_color_fake`` (bool) — Rule 4 fake flag.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(
            state: TerrainPipelineState,
            params: Optional[dict] = None,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            params_only_call = False
            original_params_arg: Any = params
            if isinstance(state, dict) and params is None:
                raw_params = dict(state)
                stack = raw_params.get("mask_stack")
                if stack is None:
                    raise TypeError(
                        "@enforce_protocol params-only handlers require a 'mask_stack' entry"
                    )
                from .terrain_semantics import BBox, TerrainIntentState

                region = BBox(
                    float(getattr(stack, "world_origin_x", 0.0)),
                    float(getattr(stack, "world_origin_y", 0.0)),
                    float(getattr(stack, "world_origin_x", 0.0))
                    + float(getattr(stack, "tile_size", 0)) * float(getattr(stack, "cell_size", 1.0)),
                    float(getattr(stack, "world_origin_y", 0.0))
                    + float(getattr(stack, "tile_size", 0)) * float(getattr(stack, "cell_size", 1.0)),
                )
                intent = TerrainIntentState(
                    seed=int(raw_params.get("seed", 0)),
                    region_bounds=region,
                    tile_size=int(getattr(stack, "tile_size", 0)),
                    cell_size=float(getattr(stack, "cell_size", 1.0)),
                    quality_profile=str(
                        raw_params.get("profile")
                        or raw_params.get("quality_profile")
                        or "aaa_open_world"
                    ),
                    scene_read=raw_params.get("scene_read"),
                    composition_hints=dict(raw_params.get("composition_hints") or {}),
                )
                protocol_state = TerrainPipelineState(intent=intent, mask_stack=stack)
                protocol_state.viewport_vantage = raw_params.get("viewport_vantage")
                state = protocol_state
                params = raw_params
                params_only_call = True
                original_params_arg = raw_params
            else:
                params = dict(params or {})
            if require_rule_1:
                ProtocolGate.rule_1_observe_before_calculate(state)
            if require_rule_2:
                ProtocolGate.rule_2_sync_to_user_viewport(
                    state,
                    out_of_view_ok=bool(params.get("out_of_view_ok", False)),
                )
            if require_rule_3:
                ProtocolGate.rule_3_lock_reference_empties(state)
            if require_rule_4:
                ProtocolGate.rule_4_real_geometry_not_vertex_tricks(params)
            if require_rule_5:
                ProtocolGate.rule_5_smallest_diff_per_iteration(
                    state,
                    cells_affected=int(params.get("cells_affected", 0)),
                    objects_affected=int(params.get("objects_affected", 0)),
                    bulk_edit=bool(params.get("bulk_edit", False)),
                )
            if require_rule_6:
                ProtocolGate.rule_6_surface_vs_interior_classification(params)
            if require_rule_7:
                ProtocolGate.rule_7_plugin_usage(params)
            if params_only_call:
                return fn(original_params_arg, *args, **kwargs)
            return fn(state, params, *args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "ProtocolViolation",
    "ProtocolGate",
    "enforce_protocol",
    "TERRAIN_ADDON_MIN_VERSION",
    "VALID_PLACEMENT_CLASSES",
]
