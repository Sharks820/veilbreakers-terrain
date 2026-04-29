"""Bundle Q — Procedural weathering event timeline.

Generates a deterministic sequence of weathering events (rain, wind,
freeze, thaw) over a duration. Events mutate the mask stack's wetness
channel when applied. Seeded via ``derive_pass_seed`` if available,
otherwise ``numpy.random.default_rng``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from .terrain_semantics import TerrainMaskStack


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

    wet = np.asarray(stack.wetness, dtype=np.float64)
    max_existing = float(wet.max()) if wet.size else 0.0
    ceil_val = max(1.0, max_existing * 2.0)

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
        flow = stack.get("flow_accumulation")
        if flow is not None:
            fa = np.asarray(flow, dtype=np.float64)
            fa_max = float(fa.max()) if fa.size else 1.0
            weight = np.clip(fa / max(fa_max, 1e-9), 0.0, 1.0)
        else:
            weight = alt_inv
        wet = np.clip(wet + intensity * (0.5 + 0.5 * weight), 0.0, ceil_val)

    elif kind == "thaw":
        # Thaw releases previously frozen moisture; slope routes it downhill
        slope_drain = np.clip(0.5 + 0.5 * slope_norm, 0.5, 1.0)
        wet = np.clip(wet + intensity * slope_drain, 0.0, ceil_val)

    elif kind in ("drought", "wind"):
        # Exposure = higher elevation + steeper slopes dry faster
        exposure = np.clip(0.4 * (1.0 - alt_inv) + 0.6 * slope_norm, 0.0, 1.0)
        wet = np.clip(wet - intensity * (0.3 + 0.7 * exposure), 0.0, ceil_val)

    elif kind == "freeze":
        # Wetness is locked in place; write an ice_factor channel
        ice = np.clip(wet * intensity, 0.0, 1.0).astype(np.float32)
        if hasattr(stack, "set"):
            try:
                stack.set("ice_factor", ice, "weathering_freeze")
            except Exception:
                pass
        return  # wetness unchanged by freeze

    else:
        return

    stack.set("wetness", wet.astype(np.float32), "weathering_timeline")
