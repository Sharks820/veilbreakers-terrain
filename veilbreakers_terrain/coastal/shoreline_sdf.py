"""Signed-distance field driven by a Bezier shoreline curve.

Replaces the grid-mask shoreline with a curve-driven SDF that grades the
heightfield. Eliminates jagged grid edges at the cost of one O(N log M)
preprocess per build.

Math reference: Inigo Quilez, "2D distance functions"
(https://iquilezles.org/articles/distfunctions2d/). Sign disambiguation
is by the cross product of the segment tangent vs the vertex-to-segment
vector — well-defined for both open and closed shorelines as long as
the curve has a global orientation.

This module is bpy-free at import time. ``ShorelineSDF.from_bezier_points``
accepts plain Python tuples, so it can be unit-tested without Blender.
``ShorelineSDF.from_bpy_curve`` is the live-Blender entry point.

Plan reference:
    docs/plans/2026-05-04-001-feat-coastal-aaa-perfection-plan.md, U3.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


class EmptyCurveError(ValueError):
    """Raised when a Bezier curve has fewer than 2 control points."""


@dataclass(slots=True)
class BezierSegment:
    """Cubic Bezier segment between two control points.

    Each control point has a position ``co``, the right handle of the
    previous point (``handle_left``), and the left handle of the next
    point (``handle_right``) — matching Blender's bezier_points layout.
    """

    p0: tuple[float, float]
    p1: tuple[float, float]  # handle on p0 going toward p3
    p2: tuple[float, float]  # handle on p3 going toward p0
    p3: tuple[float, float]


def _interpolate_bezier(
    seg: BezierSegment, samples: int
) -> list[tuple[float, float]]:
    """Sample ``samples`` points along a cubic Bezier segment, ``t ∈ [0, 1]``."""
    if samples < 2:
        samples = 2
    points: list[tuple[float, float]] = []
    p0x, p0y = seg.p0
    p1x, p1y = seg.p1
    p2x, p2y = seg.p2
    p3x, p3y = seg.p3
    for i in range(samples):
        t = i / (samples - 1)
        omt = 1.0 - t
        b0 = omt * omt * omt
        b1 = 3.0 * omt * omt * t
        b2 = 3.0 * omt * t * t
        b3 = t * t * t
        x = b0 * p0x + b1 * p1x + b2 * p2x + b3 * p3x
        y = b0 * p0y + b1 * p1y + b2 * p2y + b3 * p3y
        points.append((x, y))
    return points


def _polyline_from_segments(
    segments: Sequence[BezierSegment], samples_per_segment: int
) -> np.ndarray:
    """Tessellate a chain of bezier segments to a polyline.

    Returns an ``(N, 2)`` float64 array. Adjacent segments share endpoints,
    so the second segment skips its first sample to avoid duplicates.
    """
    if not segments:
        raise EmptyCurveError("at least one bezier segment is required")
    points: list[tuple[float, float]] = []
    for i, seg in enumerate(segments):
        seg_pts = _interpolate_bezier(seg, samples_per_segment)
        if i == 0:
            points.extend(seg_pts)
        else:
            points.extend(seg_pts[1:])
    return np.asarray(points, dtype=np.float64)


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    """Hermite smooth interpolation, vectorised."""
    if edge0 == edge1:
        return np.where(x < edge0, 0.0, 1.0)
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ShorelineSDF:
    """Signed-distance field over a tessellated Bezier shoreline.

    Sign convention: ``sd > 0`` is land (right of the curve traversal),
    ``sd < 0`` is sea. Reverse the curve if the sign comes out wrong.
    """

    polyline: np.ndarray  # (N, 2) float64

    @classmethod
    def from_bezier_points(
        cls,
        bezier_points: Iterable[tuple[
            tuple[float, float],  # co (x, y)
            tuple[float, float],  # handle_right (right handle of this point)
            tuple[float, float],  # handle_left of NEXT point
        ]],
        samples_per_segment: int = 64,
        cyclic: bool = False,
    ) -> "ShorelineSDF":
        """Build SDF from explicit (co, handle_right, handle_left_of_next) tuples.

        This is the bpy-free entry point used by tests. ``handle_left_of_next``
        is the left handle of the *next* bezier point — Blender stores this
        on the next point itself, so callers must pre-pair the handles.

        Args:
            bezier_points: ordered iterable of ``(co, hr, hl_next)``.
            samples_per_segment: tessellation density per cubic segment.
            cyclic: if True, treat the curve as closed (last point connects
                back to first).

        Raises:
            EmptyCurveError: if fewer than 2 points are supplied.
        """
        pts = list(bezier_points)
        if len(pts) < 2:
            raise EmptyCurveError(
                f"need at least 2 bezier points, got {len(pts)}"
            )
        segments: list[BezierSegment] = []
        for i in range(len(pts) - 1):
            co_a, hr_a, hl_b = pts[i]
            co_b, _hr_b, _hl_c = pts[i + 1]
            segments.append(BezierSegment(co_a, hr_a, hl_b, co_b))
        if cyclic:
            co_a, hr_a, hl_b = pts[-1]
            co_b, _hr_b, _hl_c = pts[0]
            segments.append(BezierSegment(co_a, hr_a, hl_b, co_b))
        polyline = _polyline_from_segments(segments, samples_per_segment)
        return cls(polyline=polyline)

    @classmethod
    def from_bpy_curve(
        cls, curve_obj: object, samples_per_segment: int = 64, cyclic: bool | None = None
    ) -> "ShorelineSDF":
        """Build SDF from a live Blender ``bpy.types.Curve`` object.

        Walks ``curve_obj.data.splines[0].bezier_points`` and builds the
        ``(co, handle_right, handle_left_of_next)`` triples in object-local
        space. Caller is responsible for applying world-matrix conversion
        if the curve is parented or transformed.
        """
        # Avoid bpy import at module level — only needed at this call site.
        spline = curve_obj.data.splines[0]  # type: ignore[attr-defined]
        bps = list(spline.bezier_points)
        if len(bps) < 2:
            raise EmptyCurveError(
                f"curve {getattr(curve_obj, 'name', '?')} has fewer than 2 bezier points"
            )
        triples = []
        for i, bp in enumerate(bps):
            co = (float(bp.co.x), float(bp.co.y))
            hr = (float(bp.handle_right.x), float(bp.handle_right.y))
            next_bp = bps[(i + 1) % len(bps)]
            hl_next = (float(next_bp.handle_left.x), float(next_bp.handle_left.y))
            triples.append((co, hr, hl_next))
        is_cyclic = bool(spline.use_cyclic_u) if cyclic is None else cyclic
        return cls.from_bezier_points(
            triples, samples_per_segment=samples_per_segment, cyclic=is_cyclic
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def sample_signed_distance(self, xy: np.ndarray) -> np.ndarray:
        """Return signed distance for every point in ``xy``.

        Args:
            xy: ``(N, 2)`` array of query positions in the same coordinate
                space as the polyline.

        Returns:
            ``(N,)`` array of signed distances. Positive = land
            (right-of-curve), negative = sea.

        Implementation: for each query point, find the nearest polyline
        segment, project onto it, compute unsigned distance, then sign
        by the cross product of segment tangent vs (query - segment_start).
        """
        if xy.ndim != 2 or xy.shape[1] != 2:
            raise ValueError(f"xy must be (N, 2); got {xy.shape}")
        if self.polyline.shape[0] < 2:
            raise EmptyCurveError("polyline has fewer than 2 points")
        # Vectorised nearest-segment search. For typical 4096m × 4096m at
        # 1025² grid (≈1M queries) and ~1100-point polyline, the broadcast
        # distance matrix is ~9 GB — too big. Use a chunked approach.
        seg_starts = self.polyline[:-1]  # (S, 2)
        seg_ends = self.polyline[1:]     # (S, 2)
        seg_vec = seg_ends - seg_starts  # (S, 2)
        seg_len2 = np.einsum("ij,ij->i", seg_vec, seg_vec) + 1e-12
        n_queries = xy.shape[0]
        out = np.empty(n_queries, dtype=np.float64)
        chunk_size = max(1, min(n_queries, 16_384))
        for start in range(0, n_queries, chunk_size):
            end = min(start + chunk_size, n_queries)
            q = xy[start:end][:, None, :]  # (Q, 1, 2)
            ss = seg_starts[None, :, :]    # (1, S, 2)
            sv = seg_vec[None, :, :]       # (1, S, 2)
            # t along segment, clamped to [0,1]
            qmss = q - ss                  # (Q, S, 2)
            dot = qmss[..., 0] * sv[..., 0] + qmss[..., 1] * sv[..., 1]
            t = np.clip(dot / seg_len2[None, :], 0.0, 1.0)
            proj = ss + t[..., None] * sv  # (Q, S, 2)
            diff = q - proj
            d2 = diff[..., 0] ** 2 + diff[..., 1] ** 2
            best = np.argmin(d2, axis=1)  # (Q,)
            best_d = np.sqrt(d2[np.arange(end - start), best])
            # Sign: cross(seg_tangent, query - seg_start)
            ss_b = seg_starts[best]
            sv_b = seg_vec[best]
            qb = xy[start:end] - ss_b
            cross = sv_b[:, 0] * qb[:, 1] - sv_b[:, 1] * qb[:, 0]
            sign = np.where(cross >= 0.0, 1.0, -1.0)
            out[start:end] = best_d * sign
        return out

    def grade_heightfield(
        self,
        xx: np.ndarray,
        yy: np.ndarray,
        z_ocean: np.ndarray,
        z_land: np.ndarray,
        beach_w: float = 35.0,
        cliff_w: float = 80.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Blend ocean and land heightfields by signed distance to the shore.

        ``h_new = lerp(z_ocean, z_land, smoothstep(-beach_w, +cliff_w, sd))``.

        Returns ``(z_blended, sd_grid)`` where ``sd_grid`` is the same shape
        as ``xx`` and is reused by the water-shader foam mask.
        """
        if xx.shape != yy.shape or xx.shape != z_ocean.shape or xx.shape != z_land.shape:
            raise ValueError(
                f"shape mismatch xx={xx.shape} yy={yy.shape} "
                f"z_ocean={z_ocean.shape} z_land={z_land.shape}"
            )
        flat_xy = np.stack([xx.ravel(), yy.ravel()], axis=1)
        sd = self.sample_signed_distance(flat_xy).reshape(xx.shape)
        blend_t = _smoothstep(-beach_w, cliff_w, sd)
        z = z_ocean * (1.0 - blend_t) + z_land * blend_t
        return z, sd

    def tessellate_polyline(self) -> np.ndarray:
        """Return a copy of the underlying polyline."""
        return self.polyline.copy()

    @property
    def length(self) -> float:
        """Total polyline length in world units."""
        diffs = np.diff(self.polyline, axis=0)
        return float(np.sum(np.hypot(diffs[:, 0], diffs[:, 1])))


# ---------------------------------------------------------------------------
# Convenience: build a default Coastal-tile shoreline curve programmatically
# ---------------------------------------------------------------------------


def default_coastal_shoreline(
    tile_m: float = 4096.0,
    n_control_points: int = 18,
    amplitude_m: float = 220.0,
    period: float = 0.62,
    seed: int = 842911,
) -> ShorelineSDF:
    """Build the default Coastal SDF without needing a Blender curve.

    Mirrors the analytic ``shore_x_norm`` from the legacy builder script
    but produces a high-density polyline + KDTree-friendly SDF instead
    of an analytic grid mask.
    """
    rng = np.random.default_rng(seed)
    half = tile_m / 2.0
    # Traverse top-to-bottom so the curve's "left" (cross > 0) is east. Under
    # ``sample_signed_distance``'s left-positive convention, east then resolves
    # as land (sd > 0) and west as sea (sd < 0) — matching the legacy
    # ``shore_x_norm`` analytic.
    ys = np.linspace(half, -half, n_control_points)
    points: list[tuple[
        tuple[float, float], tuple[float, float], tuple[float, float]
    ]] = []
    for i, y in enumerate(ys):
        y_norm = y / half
        x = (
            -0.32 * half
            + amplitude_m * 0.68 * math.sin(y_norm * math.pi * period + 0.30)
            + amplitude_m * 0.08 * math.sin(y_norm * math.pi * period * 1.78 - 0.55)
            + rng.normal(0.0, amplitude_m * 0.05)
        )
        co = (float(x), float(y))
        # Smooth handles via numerical tangent
        if 0 < i < n_control_points - 1:
            dx = ys[i + 1] - ys[i - 1]
            tangent_y = dx
            tangent_x = (
                amplitude_m * 0.68 * math.cos(y_norm * math.pi * period + 0.30)
                * math.pi * period / half
                + amplitude_m * 0.08 * math.cos(y_norm * math.pi * period * 1.78 - 0.55)
                * math.pi * period * 1.78 / half
            ) * dx
        else:
            tangent_x = 0.0
            tangent_y = (ys[1] - ys[0]) if i == 0 else (ys[-1] - ys[-2])
        handle_len = 0.33
        hr = (float(x + tangent_x * handle_len), float(y + tangent_y * handle_len))
        # hl_next is the left handle of the NEXT point — symmetric to its hr
        if i + 1 < n_control_points:
            y_next = ys[i + 1]
            y_next_norm = y_next / half
            x_next = (
                -0.32 * half
                + amplitude_m * 0.68 * math.sin(y_next_norm * math.pi * period + 0.30)
                + amplitude_m * 0.08 * math.sin(y_next_norm * math.pi * period * 1.78 - 0.55)
            )
            tangent_y_next = ys[1] - ys[0]
            tangent_x_next = (
                amplitude_m * 0.68 * math.cos(y_next_norm * math.pi * period + 0.30)
                * math.pi * period / half
            ) * tangent_y_next
            hl_next = (
                float(x_next - tangent_x_next * handle_len),
                float(y_next - tangent_y_next * handle_len),
            )
        else:
            hl_next = (float(x), float(y))
        points.append((co, hr, hl_next))
    return ShorelineSDF.from_bezier_points(points, samples_per_segment=64)
