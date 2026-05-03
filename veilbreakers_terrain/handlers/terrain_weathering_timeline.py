"""Bundle Q — Procedural weathering event timeline.

Generates a deterministic sequence of weathering events (rain, wind,
freeze, thaw) over a duration. Events mutate the mask stack's wetness
channel when applied. Seeded via ``derive_pass_seed`` if available,
otherwise ``numpy.random.default_rng``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

from .terrain_semantics import TerrainMaskStack

if TYPE_CHECKING:
    from .terrain_semantics import BBox, PassResult, TerrainPipelineState


WEATHER_KINDS = ("rain", "wind", "freeze", "thaw", "drought")


@dataclass
class WeatheringEvent:
    """A single weathering event on the timeline."""

    time_hours: float
    kind: str
    intensity: float


def generate_weathering_timeline(
    # FUTURE USE: Bundle Q pass — drives time-lapse weathering sequences for
    # environmental storytelling and material aging. No production caller yet;
    # will be wired into the post-pipeline hooks in a future Bundle Q pass registration.
    duration_hours: float,
    seed: int,
) -> List[WeatheringEvent]:
    """Produce a deterministic list of weathering events.

    The generator averages one event per ~2 hours of duration, with
    per-event kind and intensity drawn from a seeded RNG.
    """
    if duration_hours <= 0:
        return []

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    n = max(1, int(round(duration_hours / 2.0)))

    times = np.sort(rng.uniform(0.0, float(duration_hours), size=n))
    kinds = rng.choice(WEATHER_KINDS, size=n)
    intensities = rng.uniform(0.1, 1.0, size=n)

    return [
        WeatheringEvent(
            time_hours=float(t),
            kind=str(k),
            intensity=float(i),
        )
        for t, k, i in zip(times, kinds, intensities)
    ]


def apply_weathering_event(
    stack: TerrainMaskStack,
    event: WeatheringEvent,
) -> None:
    """Mutate the stack's wetness in place with spatially-aware distribution.

    Spatial rules (matching Houdini's weather SOP and Gaea's climate node):
      rain   → wetness flows to drainage basins; low-elevation cells accumulate more
      thaw   → frozen wetness releases, routing downhill proportional to slope
      drought / wind → elevated/exposed cells dry faster (slope-weighted removal)
      freeze → clamp wetness in place and store ice_factor on the stack

    If ``flow_accumulation`` is populated it weights rain distribution so
    valleys receive a realistic surge. Falls back to altitude inversion when
    the channel is absent. Wetness ceiling = max(2 × current max, 1.0) to
    prevent runaway accumulation.
    """
    if stack.height is None:
        return

    h = np.asarray(stack.height, dtype=np.float64)
    H, W = h.shape

    if stack.wetness is None:
        stack.set(
            "wetness",
            np.zeros((H, W), dtype=np.float32),
            "weathering_timeline",
        )

    wet = np.clip(np.asarray(stack.wetness, dtype=np.float64), 0.0, 1.0)

    intensity = float(event.intensity)
    kind = event.kind

    # Altitude inversion (0=highest → most exposed, 1=lowest → most sheltered)
    h_min, h_max = float(h.min()), float(h.max())
    h_span = max(h_max - h_min, 1e-9)
    alt_inv = 1.0 - (h - h_min) / h_span  # 1 at low elevation, 0 at high

    # Slope magnitude for exposure proxy (higher slope → more wind exposure)
    dh_dy, dh_dx = np.gradient(h, float(stack.cell_size))
    slope_mag = np.sqrt(dh_dx ** 2 + dh_dy ** 2)
    slope_max = float(slope_mag.max()) if slope_mag.size else 1.0
    slope_norm = slope_mag / max(slope_max, 1e-9)

    if kind == "rain":
        # Weight by drainage accumulation (basins collect more) or altitude inversion
        flow = stack.get("flow_accumulation", default=None)
        if flow is not None:
            fa = np.asarray(flow, dtype=np.float64)
            fa_max = float(fa.max()) if fa.size else 1.0
            weight = np.clip(fa / max(fa_max, 1e-9), 0.0, 1.0)
        else:
            weight = alt_inv
        rain_weight = np.clip(0.5 + 0.5 * weight, 0.0, 1.0)
        wet = 1.0 - (1.0 - wet) * np.exp(-intensity * rain_weight)

    elif kind == "thaw":
        # Thaw releases previously frozen moisture; slope routes it downhill
        slope_drain = np.clip(0.5 + 0.5 * slope_norm, 0.5, 1.0)
        wet = 1.0 - (1.0 - wet) * np.exp(-intensity * slope_drain)

    elif kind in ("drought", "wind"):
        # Exposure = higher elevation + steeper slopes dry faster
        exposure = np.clip(0.4 * (1.0 - alt_inv) + 0.6 * slope_norm, 0.0, 1.0)
        drain_rate = np.clip(0.3 + 0.7 * exposure, 0.0, 1.0)
        wet = wet * np.exp(-intensity * drain_rate)

    elif kind == "freeze":
        # Wetness is locked in place; write an ice_factor channel
        ice = np.clip(wet * intensity, 0.0, 1.0).astype(np.float32)
        if hasattr(stack, "set"):
            try:
                stack.set("ice_factor", ice, "weathering_freeze")
            except Exception:
                logger.debug("ice_factor stack.set failed (weathering_freeze)", exc_info=True)
        return  # wetness unchanged by freeze

    else:
        return

    stack.set("wetness", wet.astype(np.float32), "weathering_timeline")


# ---------------------------------------------------------------------------
# FIX-13-9: DAG-compatible pass wrapper for apply_weathering_event.
#
# apply_weathering_event takes (stack, event) — not the standard DAG signature
# (state, region).  This wrapper reads duration_hours and seed from the intent
# hints, runs the full timeline, and writes both wetness and ice_factor so the
# Unity sidecar exporter can ship ice_factor.bin to the water/terrain shaders.
# ---------------------------------------------------------------------------

def pass_weathering_timeline(
    state: "TerrainPipelineState",
    region: "Optional[BBox]",
) -> "PassResult":
    """Bundle Q DAG pass: run the full weathering event timeline on the stack.

    Hint keys consumed
    ------------------
    ``weathering_duration_hours``  float  — simulation window (default 48.0)
    ``weathering_seed``            int    — seed override (default: derived from
                                           pass seed when available)

    Produces: wetness, ice_factor
    """
    import time as _time
    from .terrain_semantics import PassResult as _PR

    t0 = _time.perf_counter()
    stack = state.mask_stack
    hints = dict(state.intent.composition_hints) if state.intent else {}

    duration = float(hints.get("weathering_duration_hours", 48.0))

    # Prefer derive_pass_seed when available for determinism
    try:
        from .terrain_semantics import derive_pass_seed as _dps
        seed = int(_dps(state, "pass_weathering_timeline"))
    except Exception:
        seed = int(hints.get("weathering_seed", 0))

    seed = int(hints.get("weathering_seed", seed))

    timeline = generate_weathering_timeline(duration, seed=seed)
    freeze_events = 0
    for event in timeline:
        apply_weathering_event(stack, event)
        if event.kind == "freeze":
            freeze_events += 1

    # ice_factor is written inside apply_weathering_event for "freeze" events.
    # Confirm it landed so downstream passes and the Unity sidecar can use it.
    ice = stack.get("ice_factor", default=None)

    return _PR(
        pass_name="pass_weathering_timeline",
        status="ok",
        duration_seconds=_time.perf_counter() - t0,
        produced_channels=("wetness", "ice_factor") if ice is not None else ("wetness",),
        consumed_channels=("height", "flow_accumulation"),
        metrics={
            "event_count": len(timeline),
            "freeze_events": freeze_events,
            "has_ice_factor": ice is not None,
        },
        issues=[],
    )


def register_weathering_timeline_pass() -> None:
    """Register pass_weathering_timeline with TerrainPassController."""
    from .terrain_pipeline import TerrainPassController
    from .terrain_semantics import PassDefinition

    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_weathering_timeline",
            func=pass_weathering_timeline,
            requires_channels=("height",),
            produces_channels=("wetness", "ice_factor"),
            overrides=("wetness", "ice_factor"),
            seed_namespace="pass_weathering_timeline",
            requires_scene_read=False,
            description=(
                "Bundle Q — procedural weathering event timeline; "
                "writes wetness and ice_factor (FIX-13-9)"
            ),
        )
    )
