"""catenary.py — Catenary rope/chain curve solver.

Closed-form parametric solution for the rope shape between two anchors
under uniform gravity.  No simulation required — converges in <10 iterations.

Sources:
  Alan Zucconi "The Mathematics of Catenary" (alanzucconi.com 2020)
  Bryson Lee "GPU Rope System UE5" (brysonlee.com 2024) — arc-length UV formula
  Wikipedia "Catenary" — transcendental equation derivation
"""
from __future__ import annotations

import math
import numpy as np
from scipy.optimize import brentq


def solve_catenary(
    p0: np.ndarray,
    p1: np.ndarray,
    rope_length: float,
    n_points: int = 32,
) -> np.ndarray:
    """Return (n_points, 3) world-space points on the catenary between p0 and p1.

    The curve hangs in the vertical plane containing p0 and p1.

    Raises:
        ValueError: rope_length <= euclidean distance (rope too short to sag).
    """
    p0 = np.asarray(p0, dtype=float)
    p1 = np.asarray(p1, dtype=float)

    d = float(np.linalg.norm(p1 - p0))
    if rope_length <= d:
        raise ValueError(
            f"rope_length {rope_length:.3f} must exceed anchor distance {d:.3f}"
        )

    horiz = (p1 - p0).copy()
    horiz[2] = 0.0
    h = float(np.linalg.norm(horiz))
    vert = float((p1 - p0)[2])

    if h < 1e-6:
        t = np.linspace(0.0, 1.0, n_points)
        return p0[None] + t[:, None] * (p1 - p0)[None]

    target = math.sqrt(max(rope_length ** 2 - vert ** 2, 0.0))

    def _residual(a: float) -> float:
        arg = h / (2.0 * a)
        if arg > 709.0:  # sinh overflow guard (math domain ~710)
            return float('inf') - target
        return 2.0 * a * math.sinh(arg) - target

    # T1-41 fix (S09-P0-02): walk the bracket OUTWARD on residual-sign mismatch
    # rather than swallowing ``brentq``'s ValueError into the silent fallback
    # ``a = h * 50``, which was never a root and produced impossibly large or
    # zero sag downstream via cosh/sinh.
    #
    # The catenary residual ``2a sinh(h/2a) - target`` is monotonic in ``a`` on
    # ``(0, inf)``: it tends to ``+inf`` as ``a -> 0`` (sinh blowup) and to
    # ``h - target < 0`` as ``a -> inf`` (linear-rope limit, where target =
    # sqrt(L^2 - vert^2) > h whenever ``L > d``). So a sign-changing bracket
    # always exists; we just have to find it.
    lo = max(h / 20.0, 1e-6)
    hi = h * 100.0
    # Walk the LOWER bound DOWN until residual is positive (sinh dominates).
    while lo > 1e-9 and _residual(lo) <= 0:
        lo *= 0.5
    # Walk the UPPER bound UP until residual is negative (linear-rope limit).
    walks = 0
    while _residual(hi) >= 0 and walks < 32:
        hi *= 2.0
        walks += 1
    try:
        # Note: brentq stub returns tuple[float, RootResults] when
        # full_output=True; we don't pass that flag so it returns float.
        # Pyright doesn't narrow on the kwarg so we use typing.cast to
        # tell the type checker we're in the float-return branch.
        from typing import cast
        a = cast(float, brentq(_residual, lo, hi, xtol=1e-6, maxiter=100))
    except ValueError as exc:
        raise RuntimeError(
            "catenary brentq failed to bracket; "
            f"check inputs (h={h:.6f}, vert={vert:.6f}, "
            f"rope_length={rope_length:.6f}, target={target:.6f}): {exc}"
        ) from exc
    if not (math.isfinite(a) and a > 0.0):
        raise RuntimeError(
            f"catenary solver returned non-finite or non-positive a={a!r}"
        )

    log_arg = max((rope_length + vert) / max(rope_length - vert, 1e-12), 1e-12)
    p_shift = (h - a * math.log(log_arg)) / 2.0

    cosh_arg = h / (2.0 * a)
    coth_val = math.cosh(cosh_arg) / max(math.sinh(cosh_arg), 1e-12)
    q_shift = (vert - rope_length * coth_val) / 2.0

    u = np.linspace(0.0, h, n_points)
    v = a * np.cosh((u - p_shift) / a) + q_shift

    horiz_unit = horiz / (h + 1e-12)
    up = np.array([0.0, 0.0, 1.0])
    world_pts = (
        p0[None]
        + u[:, None] * horiz_unit[None]
        + v[:, None] * up[None]
    )
    return world_pts.astype(np.float32)


def arc_length_uv(points: np.ndarray) -> np.ndarray:
    """Return per-point arc-length UV in [0, 1] for correct texture tiling.

    Prevents texture stretching when tiling chain/rope textures along the
    catenary curve.
    """
    deltas = np.diff(points, axis=0)
    seg_lengths = np.linalg.norm(deltas, axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(seg_lengths)])
    total = cumulative[-1]
    return (cumulative / max(total, 1e-12)).astype(np.float32)


def catenary_with_sag(
    anchor_a: np.ndarray,
    anchor_b: np.ndarray,
    sag_ratio: float = 0.12,
    n_points: int = 32,
) -> np.ndarray:
    """Convenience wrapper — rope_length = dist * (1 + sag_ratio).

    sag_ratio=0.12 produces a visually natural 12% sag, matching the look
    of heavy iron chains in reference (KCD2, RDR2 terrain props).
    """
    d = float(np.linalg.norm(np.asarray(anchor_b) - np.asarray(anchor_a)))
    rope_length = d * (1.0 + max(sag_ratio, 0.001))
    return solve_catenary(anchor_a, anchor_b, rope_length, n_points)
