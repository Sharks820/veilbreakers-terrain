"""Bundle R — named empty anchor lock/unlock and drift detection.

Anchors are the single source of truth for "this hero feature belongs HERE".
Any pass that shifts an anchor's effective position beyond ``tolerance``
raises ``AnchorDrift`` — the orchestrator then rolls back.

See Addendum 1.A.4.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Dict, List

from .terrain_semantics import TerrainAnchor, TerrainIntentState


class AnchorDrift(RuntimeError):
    """Raised when a locked anchor's tracked position has drifted."""


@dataclass
class AnchorDriftReport:
    anchor_name: str
    drifted: bool
    distance_m: float
    tolerance_m: float
    message: str = ""


# Module-level lock registry — maps anchor name → originally-locked anchor.
# Mutable by design so `lock_anchor` + `assert_*` work across calls.
_LOCKED_ANCHORS: Dict[str, TerrainAnchor] = {}
_LOCKED_ANCHORS_LOCAL = threading.local()
_LOCKED_ANCHORS_GUARD = threading.RLock()


def _lock_registry() -> Dict[str, TerrainAnchor]:
    # Preserve the historical module-level registry for the main thread so
    # existing tests/tools that inspect `_LOCKED_ANCHORS` directly still work.
    if threading.current_thread() is threading.main_thread():
        return _LOCKED_ANCHORS

    registry = getattr(_LOCKED_ANCHORS_LOCAL, "anchors", None)
    if registry is None:
        registry = {}
        _LOCKED_ANCHORS_LOCAL.anchors = registry
    return registry


def lock_anchor(anchor: TerrainAnchor) -> None:
    """Record an anchor as the authoritative reference for its name.

    Overwrites any prior lock for the same name. Use ``unlock_anchor``
    to release before re-locking if you want to catch accidental re-locks.
    """
    with _LOCKED_ANCHORS_GUARD:
        _lock_registry()[anchor.name] = anchor


def unlock_anchor(anchor_name: str) -> None:
    with _LOCKED_ANCHORS_GUARD:
        _lock_registry().pop(anchor_name, None)


def clear_all_locks() -> None:
    """Test helper — releases every registered anchor lock."""
    with _LOCKED_ANCHORS_GUARD:
        _lock_registry().clear()


def is_locked(anchor_name: str) -> bool:
    with _LOCKED_ANCHORS_GUARD:
        return anchor_name in _lock_registry()


def _distance(
    a: tuple, b: tuple
) -> float:
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def assert_anchor_integrity(
    anchor: TerrainAnchor,
    *,
    tolerance: float = 0.01,
) -> None:
    """Raise ``AnchorDrift`` if a named anchor no longer matches its lock."""
    with _LOCKED_ANCHORS_GUARD:
        locked = _lock_registry().get(anchor.name)
    if locked is None:
        # Unlocked anchors are always considered intact — caller's choice.
        return
    dist = _distance(locked.world_position, anchor.world_position)
    if dist > tolerance:
        raise AnchorDrift(
            f"anchor '{anchor.name}' drifted {dist:.4f}m "
            f"(tolerance {tolerance:.4f}m)"
        )


def assert_all_anchors_intact(
    intent: TerrainIntentState,
    *,
    tolerance: float = 0.01,
) -> List[AnchorDriftReport]:
    """Check every anchor in ``intent.anchors`` against its locked position.

    Returns a list of ``AnchorDriftReport`` — one per anchor. Does NOT
    raise; the caller (ProtocolGate.rule_3) decides how to act on drift.
    """
    reports: List[AnchorDriftReport] = []
    for anchor in intent.anchors:
        with _LOCKED_ANCHORS_GUARD:
            locked = _lock_registry().get(anchor.name)
        if locked is None:
            reports.append(
                AnchorDriftReport(
                    anchor_name=anchor.name,
                    drifted=False,
                    distance_m=0.0,
                    tolerance_m=tolerance,
                    message="unlocked",
                )
            )
            continue
        dist = _distance(locked.world_position, anchor.world_position)
        reports.append(
            AnchorDriftReport(
                anchor_name=anchor.name,
                drifted=dist > tolerance,
                distance_m=dist,
                tolerance_m=tolerance,
                message="ok" if dist <= tolerance else "drifted",
            )
        )
    return reports


__all__ = [
    "AnchorDrift",
    "AnchorDriftReport",
    "lock_anchor",
    "unlock_anchor",
    "clear_all_locks",
    "is_locked",
    "assert_anchor_integrity",
    "assert_all_anchors_intact",
]
