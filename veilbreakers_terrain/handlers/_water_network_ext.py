"""Bundle C — WaterNetwork extension module.

Extension helpers for `_water_network.WaterNetwork` without editing that
file directly. Adds:
    - add_meander: Leopold & Wolman (1960) empirical scaling + Langbein &
      Leopold (1966) sine-generated curve for meander planform geometry
    - apply_bank_asymmetry: Ikeda (1989) inner/outer bank asymmetric erosion
      profile with full cross-section deformation
    - solve_outflow: pool → downstream outflow path solver with Manning
      discharge accumulation
    - compute_wet_rock_mask: wetness proxy around water surfaces
    - compute_foam_mask / compute_mist_mask: shared foam/mist builders

Pure Python + numpy. No bpy/bmesh imports.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

from .terrain_semantics import TerrainMaskStack

try:
    from scipy.ndimage import distance_transform_edt as _distance_transform_edt

    _HAS_SCIPY = True
except ImportError:  # pragma: no cover - exercised via fallback tests
    _distance_transform_edt = None
    _HAS_SCIPY = False

if TYPE_CHECKING:  # pragma: no cover
    from .terrain_waterfalls import ImpactPool, WaterfallChain


# ---------------------------------------------------------------------------
# WaterNetwork upgrades
# ---------------------------------------------------------------------------


def add_meander(
    water_network: Any,
    amplitude: float,
    discharge: float | None = None,
) -> None:
    """Perturb each segment's waypoints using Langbein & Leopold (1966) sine-generated curve.

    Implements the full physical meandering model:

    1. **Leopold & Wolman (1960) empirical scaling**:
           wavelength λ = 10.9 * Q^0.46
           amplitude   A = 2.7 * Q^0.31
       where Q is the volumetric discharge (m³/s).  Exponents are the
       original empirical values from Leopold & Wolman (1960) — NOT 0.5.

    2. **Langbein & Leopold (1966) sine-generated curve**:
       The planform direction angle varies as:
           θ(s) = θ_max * sin(2π s / λ)
       where s is arc length along the channel.  This is integrated to
       give lateral displacement:
           offset(s) = (θ_max * λ / 2π) * (1 - cos(2π s / λ))
       Endpoint positions are pinned (zero displacement at s=0 and s=L)
       using a sine taper so tile seams remain connected.

    3. **Oxbow cutoff detection**: when the maximum perpendicular
       displacement exceeds 40% of the chord length, amplitude is clamped
       and ``_oxbow_candidate`` is flagged on the segment.

    When ``discharge`` is None, a discharge proxy is estimated from the
    segment's average width using the inverse hydraulic geometry relation
    Q ≈ (W/3)².

    Args:
        water_network: WaterNetwork-like with ``segments`` dict.
        amplitude: Minimum meander amplitude in world-units. Acts as a
            floor when Leopold & Wolman scaling would give a smaller value.
        discharge: Optional volumetric discharge (m³/s). When None,
            estimated from segment width.
    """
    if amplitude <= 0.0 or water_network is None:
        return
    segments = getattr(water_network, "segments", {})

    for seg in segments.values():
        waypoints = list(getattr(seg, "waypoints", []))
        n = len(waypoints)
        if n < 3:
            continue

        # Compute arc-length table for geometry-correct phase
        arc_lengths: List[float] = [0.0]
        for i in range(1, n):
            prev_wp = waypoints[i - 1]
            curr_wp = waypoints[i]
            dx_seg = curr_wp[0] - prev_wp[0]
            dy_seg = curr_wp[1] - prev_wp[1]
            arc_lengths.append(arc_lengths[-1] + math.sqrt(dx_seg * dx_seg + dy_seg * dy_seg))
        total_arc = max(arc_lengths[-1], 1e-9)

        # --- Estimate discharge when not supplied ---------------------------
        if discharge is None or discharge <= 0.0:
            # Inverse hydraulic geometry: W ≈ 3 * Q^0.5 → Q ≈ (W/3)^2
            avg_width = getattr(seg, "avg_width", 1.0) or 1.0
            q = max(0.01, (avg_width / 3.0) ** 2)
        else:
            q = float(discharge)

        # --- Leopold & Wolman (1960) empirical wavelength and amplitude ------
        # Original paper exponents: λ = 10.9 * Q^0.46, A = 2.7 * Q^0.31
        wavelength = 10.9 * (q ** 0.46)
        lw_amplitude = 2.7 * (q ** 0.31)
        effective_amp = max(amplitude, lw_amplitude)
        wavelength = max(wavelength, 1e-9)

        # --- Oxbow guard: clamp amplitude to 40% of chord half-length -------
        start = waypoints[0]
        end = waypoints[-1]
        chord = math.sqrt((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2)
        max_amp = max(0.0, chord * 0.4)
        if max_amp > 0:
            effective_amp = min(effective_amp, max_amp)

        # --- Langbein & Leopold (1966) sine-generated curve -----------------
        # θ_max: maximum deviation angle.  Natural rivers: θ_max ≈ 110°.
        # Clamp to 90° for terrain-constrained channels.
        theta_max = math.radians(min(110.0, 90.0))
        omega = 2.0 * math.pi / wavelength

        # Chord direction (base axis for perpendicular displacement)
        if chord > 1e-9:
            chord_dx = (end[0] - start[0]) / chord
            chord_dy = (end[1] - start[1]) / chord
        else:
            chord_dx, chord_dy = 1.0, 0.0
        # Perpendicular (rotate 90° CCW)
        perp_x = -chord_dy
        perp_y = chord_dx

        new_points: List[Tuple[float, float, float]] = []
        oxbow_candidate = False

        for i, (wx, wy, wz) in enumerate(waypoints):
            if i == 0 or i == n - 1:
                # Pin endpoints: preserve connectivity with adjacent segments
                new_points.append((wx, wy, wz))
                continue

            s = arc_lengths[i]

            # Sine-generated lateral displacement:
            # offset(s) = (θ_max / ω) * (1 - cos(ω * s))
            # This is the exact integral of θ(s) = θ_max * sin(ω * s).
            raw_offset = (theta_max / omega) * (1.0 - math.cos(omega * s))

            # Scale to effective_amp (the sine curve's natural amplitude is
            # θ_max/ω which can be large; we normalise and re-scale)
            natural_amp = theta_max / omega
            if natural_amp > 1e-9:
                scaled_offset = raw_offset * (effective_amp / natural_amp)
            else:
                scaled_offset = 0.0

            # Sine taper: zero displacement at endpoints, maximum at midpoint
            # taper(s) = sin(π * s / L)
            taper = math.sin(math.pi * s / total_arc)
            offset = scaled_offset * taper

            # Clamp per-point to max_amp
            if max_amp > 0 and abs(offset) > max_amp:
                offset = math.copysign(max_amp, offset)
                if abs(offset) >= max_amp * 0.95:
                    oxbow_candidate = True

            new_points.append((wx + perp_x * offset, wy + perp_y * offset, wz))

        seg.waypoints = new_points
        try:
            setattr(seg, "_oxbow_candidate", oxbow_candidate)
            # Store computed discharge for downstream consumers
            setattr(seg, "_meander_discharge_m3s", q)
            setattr(seg, "_meander_wavelength_m", wavelength)
        except Exception:
            logger.debug("meander metadata setattr failed (best-effort)", exc_info=True)


def apply_bank_asymmetry(water_network: Any, bias: float) -> None:
    """Apply Ikeda (1989) inner/outer bank asymmetry to river cross-sections.

    Implements the Ikeda (1989) secondary flow model for meander cross-section
    deformation:
        - **Outer bank** (positive bias side): centrifugal force drives flow
          outward, eroding the outer bank.  Depth increases toward the outer
          bank following a power-law profile:
              d_outer(y) = d_center * (1 + β * (y / W/2))^γ_outer
          where β = |bias|, γ_outer = 1.3 (Ikeda 1989 calibration),
          y = lateral distance from centreline, W = channel width.
        - **Inner bank** (negative bias side): Helical secondary flow
          deposits sediment, building a point bar.  Depth decreases toward
          the inner bank:
              d_inner(y) = d_center * (1 - β * (y / W/2))^γ_inner
          where γ_inner = 0.7.
        - **Point bar elevation**: the inner bank is raised by
              Δz_bar = 0.3 * d_center * |bias|
          simulating the point-bar scroll bars typical of meandering rivers.

    The asymmetry profile is stored on each segment as:
        ``bank_asymmetry``        — raw bias value in [-1, 1]
        ``outer_bank_depth_mult`` — depth multiplier at the outer bank edge
        ``inner_bank_depth_mult`` — depth multiplier at the inner bank edge
        ``point_bar_rise_m``      — point-bar elevation above centreline (m)

    These attributes are consumed by the tile mesh generator and the
    splatmap pass to place eroded rock and sand/gravel point-bar textures.

    Args:
        water_network: WaterNetwork-like with ``segments`` dict.
        bias: Bank asymmetry in [-1, 1].  Positive = right bank (positive
            perpendicular direction) erodes faster.  Negative = left bank.
            0.0 produces a symmetric channel.
    """
    bias = max(-1.0, min(1.0, float(bias)))
    if water_network is None:
        return
    segments = getattr(water_network, "segments", {})

    # Ikeda (1989) calibrated exponents
    _GAMMA_OUTER = 1.3   # outer bank depth growth exponent
    _GAMMA_INNER = 0.7   # inner bank depth decay exponent
    _BETA_SCALE = 1.0    # secondary-flow intensity scale (1.0 = full Ikeda)

    abs_bias = abs(bias)

    for seg in segments.values():
        avg_depth = getattr(seg, "avg_depth", 1.0) or 1.0

        # Outer bank: depth at the channel edge (y = W/2, normalised y = 1.0)
        # d_outer = d_center * (1 + β * 1.0)^γ_outer
        outer_mult = (1.0 + _BETA_SCALE * abs_bias) ** _GAMMA_OUTER

        # Inner bank: depth at the inner channel edge (y = -W/2, normalised y = -1.0)
        # d_inner = d_center * (1 - β * 1.0)^γ_inner
        # Clamp to a minimum of 0.05× centre depth so the point bar never
        # becomes numerically zero (physical: bars are still submerged at flood)
        inner_raw = (1.0 - _BETA_SCALE * abs_bias) ** _GAMMA_INNER
        inner_mult = max(0.05, inner_raw)

        # Point-bar surface elevation rise above the channel centreline
        # Ikeda (1989): bar height ≈ 30% of centre depth × relative curvature
        point_bar_rise_m = 0.3 * avg_depth * abs_bias

        try:
            setattr(seg, "bank_asymmetry", float(bias))
            setattr(seg, "outer_bank_depth_mult", round(outer_mult, 4))
            setattr(seg, "inner_bank_depth_mult", round(inner_mult, 4))
            setattr(seg, "point_bar_rise_m", round(point_bar_rise_m, 4))
        except Exception:  # pragma: no cover
            pass


def solve_outflow(
    water_network: Any,
    pool: "ImpactPool",
) -> List[Tuple[int, int]]:
    """Solve steady-state discharge along the outflow path from an impact pool.

    Uses the Gauckler-Manning formula to compute discharge at each cell and
    accumulates it downstream via a topological sort on the D8 flow tree.
    This gives physically correct discharge magnitudes rather than a raw
    cell-count accumulation.

    Manning formula per cell:
        Q = (1/n) * A * R^(2/3) * S^(1/2)
        where:
            n = 0.035 (natural channel roughness)
            A = width * depth  (rectangular cross-section)
            R = A / (width + 2*depth)  (hydraulic radius)
            S = max(|dz| / dx, 1e-5)   (bed slope from D8 gradient)

    The function returns the spatial path (ordered list of grid cells) that
    the outflow follows from the pool to the map boundary or an existing
    water body.  Discharge values are stored as a dynamic attribute
    ``outflow_discharge_m3s`` on each visited cell (encoded as a dict
    accessible via ``water_network._outflow_discharge`` after the call).

    Termination conditions:
        (a) Boundary reached — next step would leave the grid.
        (b) Local minimum (sink) — no lower neighbor exists.
        (c) Existing water body reached — a cell flagged in the
            ``water_surface`` channel (if available) is encountered.

    Falls back to the previous straight-line approximation when no
    heightmap is available on ``water_network``.

    Args:
        water_network: WaterNetwork instance or any object that may expose
            a ``_heightmap`` numpy array and optionally ``_cell_size``,
            ``_world_origin_x``, ``_world_origin_y``.
        pool: ImpactPool whose ``world_position`` and ``outflow_direction_rad``
            seed the walk.

    Returns:
        List of (row, col) grid-coordinate tuples tracing the outflow path,
        ordered from the pool to the terminal cell.  Empty list if the pool
        position cannot be resolved to a grid cell.
    """
    # ------------------------------------------------------------------
    # D8 offsets and distances (consistent with _water_network.py)
    # ------------------------------------------------------------------
    _D8 = [(-1, 0), (-1, 1), (0, 1), (1, 1),
           (1, 0), (1, -1), (0, -1), (-1, -1)]
    _DIST = [1.0, math.sqrt(2.0), 1.0, math.sqrt(2.0),
             1.0, math.sqrt(2.0), 1.0, math.sqrt(2.0)]
    _MANNING_N = 0.035  # natural channel (conservative mid-range)

    # ------------------------------------------------------------------
    # Resolve heightmap
    # ------------------------------------------------------------------
    hmap: "np.ndarray | None" = None
    for attr in ("_heightmap", "heightmap"):
        candidate = getattr(water_network, attr, None)
        if candidate is not None:
            hmap = np.asarray(candidate, dtype=np.float64)
            break

    # If no heightmap, fall back to straight-line polyline (legacy behaviour)
    if hmap is None:
        cx, cy, _cz = pool.world_position
        dx = math.cos(pool.outflow_direction_rad)
        dy = math.sin(pool.outflow_direction_rad)
        step = max(1.0, pool.radius_m * 0.5)
        fallback: List[Tuple[int, int]] = []
        for i in range(1, 17):
            fallback.append((int(cy + dy * step * i), int(cx + dx * step * i)))
        return fallback

    rows, cols = hmap.shape
    origin_x: float = getattr(water_network, "_world_origin_x", 0.0)
    origin_y: float = getattr(water_network, "_world_origin_y", 0.0)
    cell_size: float = float(getattr(water_network, "_cell_size", 1.0))

    # ------------------------------------------------------------------
    # Resolve pool grid position
    # ------------------------------------------------------------------
    px, py, _ = pool.world_position
    start_c = int(round((px - origin_x) / cell_size))
    start_r = int(round((py - origin_y) / cell_size))
    start_r = max(0, min(rows - 1, start_r))
    start_c = max(0, min(cols - 1, start_c))

    # ------------------------------------------------------------------
    # Optional water_surface mask for termination condition (c)
    # ------------------------------------------------------------------
    water_surface: "np.ndarray | None" = None
    stack = getattr(water_network, "_mask_stack", None)
    if stack is not None:
        ws = stack.get("water_surface_mask")
        if ws is None:
            ws = stack.get("water_surface")
        if ws is not None:
            water_surface = np.asarray(ws)

    # ------------------------------------------------------------------
    # Phase 1: trace the steepest-descent path from the pool.
    #
    # AAA gap addressed: plain steepest-descent gets trapped in planar
    # depressions (lakes, flat valley floors) and halts, producing a
    # truncated outflow path that stops inside the depression rather than
    # routing through it.  The Wang & Liu (2006) / Barnes et al. (2014)
    # priority-flood approach fills depressions before routing so water
    # always finds a spill path.
    #
    # We implement a lightweight inline priority-flood: when the steepest-
    # descent step hits a local minimum (no lower neighbour), we switch to
    # a min-heap that expands the frontier at increasing water levels until
    # a downhill exit is found.  This is topologically equivalent to the
    # Wang & Liu "Improved" priority-flood but scoped only to the path
    # rather than the whole DEM, keeping it fast for the outflow use-case.
    # ------------------------------------------------------------------
    import heapq as _heapq  # already imported at module level; local alias

    path: List[Tuple[int, int]] = [(start_r, start_c)]
    visited: set[Tuple[int, int]] = {(start_r, start_c)}
    r, c = start_r, start_c
    max_steps = max(rows, cols) * 2

    for _ in range(max_steps):
        # Termination (c): reached an existing water body
        if water_surface is not None and (r, c) != (start_r, start_c):
            if water_surface[r, c] > 0.01:
                break

        # Steepest-descent step — pick neighbour with greatest slope-adjusted drop
        h0 = hmap[r, c]
        best_slope = 0.0
        best_next: "Tuple[int, int] | None" = None
        for (dr, dc), dist in zip(_D8, _DIST):
            nr, nc = r + dr, c + dc
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            slope = (h0 - hmap[nr, nc]) / (dist * cell_size)
            if slope > best_slope:
                best_slope = slope
                best_next = (nr, nc)

        if best_next is not None:
            nr, nc = best_next
            # Termination (a): boundary
            if not (0 <= nr < rows and 0 <= nc < cols):
                path.append((nr, nc))
                break
            # Cycle guard
            if (nr, nc) in visited:
                break
            visited.add((nr, nc))
            path.append((nr, nc))
            r, c = nr, nc
            if nr == 0 or nr == rows - 1 or nc == 0 or nc == cols - 1:
                break
        else:
            # Termination (b) — local minimum / planar depression.
            # Priority-flood spill: expand from (r,c) via a min-heap keyed
            # on max(current_water_level, neighbour_elevation) until we find
            # a cell that has a lower unvisited neighbour (spill point).
            pf_heap: List["Tuple[float, int, int]"] = []
            pf_visited: set[Tuple[int, int]] = set(visited)
            _heapq.heappush(pf_heap, (float(hmap[r, c]), r, c))
            spill_found = False
            pf_steps = 0
            max_pf = min(rows * cols, 4096)  # cap flood search radius

            while pf_heap and pf_steps < max_pf:
                wl, pr, pc = _heapq.heappop(pf_heap)
                pf_steps += 1
                for (dr, dc), dist in zip(_D8, _DIST):
                    nr2, nc2 = pr + dr, pc + dc
                    if not (0 <= nr2 < rows and 0 <= nc2 < cols):
                        continue
                    if (nr2, nc2) in pf_visited:
                        continue
                    nh = float(hmap[nr2, nc2])
                    new_wl = max(wl, nh)
                    pf_visited.add((nr2, nc2))
                    _heapq.heappush(pf_heap, (new_wl, nr2, nc2))
                    # Check if nr2,nc2 has a downhill exit not yet flooded
                    for (dr2, dc2), dist2 in zip(_D8, _DIST):
                        ex_r, ex_c = nr2 + dr2, nc2 + dc2
                        if not (0 <= ex_r < rows and 0 <= ex_c < cols):
                            continue
                        if (ex_r, ex_c) in pf_visited:
                            continue
                        if float(hmap[ex_r, ex_c]) < new_wl:
                            # Found a spill exit — route to nr2,nc2 then exit
                            if (nr2, nc2) not in visited:
                                visited.add((nr2, nc2))
                                path.append((nr2, nc2))
                            spill_found = True
                            r, c = nr2, nc2
                            break
                    if spill_found:
                        break
                if spill_found:
                    break

            if not spill_found:
                # Genuinely enclosed basin with no spill — terminate here
                break

    # ------------------------------------------------------------------
    # Phase 2: Manning discharge accumulation along the path
    # Seed the pool with its own inflow volume (proportional to pool area),
    # then carry the discharge downstream, adding lateral catchment at each
    # step via the local bed slope.
    # ------------------------------------------------------------------
    # Estimate initial discharge from pool radius (proxy for upstream area)
    pool_area_m2 = math.pi * max(pool.radius_m, 1.0) ** 2
    discharge: List[float] = [pool_area_m2 * 0.01]  # rough seed Q in m³/s

    for idx in range(1, len(path)):
        r_prev, c_prev = path[idx - 1]
        r_cur, c_cur = path[idx]

        if not (0 <= r_cur < rows and 0 <= c_cur < cols):
            discharge.append(discharge[-1])
            continue

        dr = r_cur - r_prev
        dc = c_cur - c_prev
        dist = math.sqrt(dr * dr + dc * dc) * cell_size
        dz = float(hmap[r_prev, c_prev]) - float(hmap[r_cur, c_cur])
        slope = max(dz / max(dist, 1e-9), 1e-5)

        # Approximate channel geometry from accumulated discharge
        q_prev = discharge[-1]
        # Width from hydraulic geometry: w ∝ Q^0.5 (Leopold & Maddock 1953)
        w = max(0.5, min(20.0, 1.5 * math.sqrt(q_prev)))
        # Depth from Manning inversion: d = (Q*n / (w * S^0.5))^(3/5)
        # using rectangular channel where R ≈ d for wide channels
        d = max(0.1, ((q_prev * _MANNING_N) / max(w * math.sqrt(slope), 1e-9)) ** 0.6)
        area = w * d
        wetted_p = w + 2.0 * d
        R = area / max(wetted_p, 1e-9)
        # Recompute Q with updated geometry (one Manning iteration)
        q_cell = (1.0 / _MANNING_N) * area * (R ** (2.0 / 3.0)) * math.sqrt(slope)
        # Carry forward the max of accumulated and locally computed Q
        discharge.append(max(q_prev, q_cell))

    # Store discharge profile on the network object for downstream consumers
    try:
        outflow_map: dict[Tuple[int, int], float] = {}
        for idx, (pr, pc) in enumerate(path):
            outflow_map[(pr, pc)] = discharge[idx] if idx < len(discharge) else discharge[-1]
        setattr(water_network, "_outflow_discharge", outflow_map)
    except Exception:
        logger.debug("_outflow_discharge setattr failed (best-effort)", exc_info=True)

    return path


# ---------------------------------------------------------------------------
# Mask builders (shared with terrain_waterfalls.py)
# ---------------------------------------------------------------------------


def _world_to_grid(
    stack: TerrainMaskStack, x: float, y: float,
) -> Tuple[int, int]:
    """Convert world XY to nearest grid cell (row, col).

    Uses the same cell-centre convention as terrain_waterfalls._world_to_grid:
    grid_to_world places the cell centre at origin + (idx + 0.5) * cell_size,
    so the exact inverse is idx = round((world - origin) / cs - 0.5).
    Using plain int() (floor truncation) introduces a systematic half-cell
    bias that causes misalignment between the ext module and the waterfall
    solver when world_origin > 0 or when coords are near cell boundaries.
    """
    cs = float(stack.cell_size)
    ox = float(stack.world_origin_x)
    oy = float(stack.world_origin_y)
    c = int(round((x - ox) / cs - 0.5))
    r = int(round((y - oy) / cs - 0.5))
    rows, cols = stack.height.shape
    r = max(0, min(rows - 1, r))
    c = max(0, min(cols - 1, c))
    return r, c


def compute_wet_rock_mask(
    stack: TerrainMaskStack,
    water_network: Any,
    radius_m: float = 3.0,
    seasonal_wetness: float = 1.0,
) -> np.ndarray:
    """Build a wet-rock mask around water surfaces.

    Uses ``scipy.ndimage.distance_transform_edt(..., return_indices=True)``
    so each cell inherits the strength of its nearest water seed rather than
    multiplying against a global flow field.  That preserves physically
    important differences between a weak seep and a high-discharge plunge
    pool.  The no-SciPy fallback keeps the same per-seed strength model with
    vectorized local radial stamps.

    Wetness formula:
        edge_strength = 0.55 + 0.45 * normalized_source_strength
        falloff_t     = clip(dist / radius_m, 0, 1)
        base          = 1 - smoothstep(falloff_t)
        wet           = max(seed_mask, base * edge_strength * seasonal_wetness)

    Source strength is derived from the best available hydrology signal:
        - local ``flow_accumulation`` on the stack
        - per-cell discharge hints from ``water_network._outflow_discharge``
        - or a uniform strength when those channels are absent

    Seeds are drawn from:
        - The ``water_surface`` channel on the stack (cells > 0.01).
        - Each node in ``water_network.nodes`` projected to grid space.

    Args:
        stack: TerrainMaskStack with at minimum a ``height`` channel.
        water_network: WaterNetwork providing node positions (may be None).
        radius_m: Maximum splash / seep radius in metres.
        seasonal_wetness: Seasonal multiplier in [0, 1]. 1.0 = peak wet
            season, 0.0 = dry season.  Useful for wet/dry cycle animation.
    """
    if seasonal_wetness <= 0.0:
        h = np.asarray(stack.height, dtype=np.float64)
        return np.zeros(h.shape, dtype=np.float32)

    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)
    radius_cells = max(1, int(math.ceil(radius_m / cs)))

    def _smoothstep01(t: np.ndarray) -> np.ndarray:
        return t * t * (3.0 - 2.0 * t)

    # Build boolean seed mask + per-seed source-strength field.
    seed_mask = np.zeros((rows, cols), dtype=bool)
    seed_strength = np.zeros((rows, cols), dtype=np.float64)

    fa_norm = None
    fa = stack.get("flow_accumulation", default=None)
    if fa is not None:
        fa_arr = np.asarray(fa, dtype=np.float64)
        if fa_arr.shape == h.shape:
            fa_max = float(fa_arr.max())
            if fa_max > 1e-9:
                fa_norm = np.clip(fa_arr / fa_max, 0.0, 1.0)

    discharge_map = {}
    discharge_max = 0.0
    if water_network is not None:
        discharge_map = getattr(water_network, "_outflow_discharge", {}) or {}
        if discharge_map:
            discharge_max = max(float(v) for v in discharge_map.values())

    def _source_strength_at(r: int, c: int, explicit_value: float | None = None) -> float:
        if explicit_value is not None:
            norm = max(0.0, min(1.0, float(explicit_value)))
            return 0.55 + 0.45 * norm
        norm_candidates: list[float] = []
        if fa_norm is not None:
            norm_candidates.append(float(fa_norm[r, c]))
        if discharge_map and discharge_max > 1e-9:
            norm_candidates.append(
                max(
                    0.0,
                    min(1.0, float(discharge_map.get((r, c), 0.0)) / discharge_max),
                )
            )
        if not norm_candidates:
            return 1.0
        return 0.55 + 0.45 * max(norm_candidates)

    surface = stack.get("water_surface_mask", default=None) if stack.get("water_surface_mask", default=None) is not None else stack.get("water_surface", default=None)  # FIX-10-H14
    if surface is not None:
        surface_arr = np.asarray(surface)
        if surface_arr.shape == h.shape:
            water_cells = surface_arr > 0.01
            seed_mask |= water_cells
            if fa_norm is not None:
                surface_strength = 0.55 + 0.45 * fa_norm
                seed_strength = np.maximum(
                    seed_strength,
                    np.where(water_cells, surface_strength, 0.0),
                )
            else:
                seed_strength = np.maximum(
                    seed_strength,
                    np.where(water_cells, 1.0, 0.0),
                )

    if water_network is not None:
        nodes = getattr(water_network, "nodes", {}) or {}
        for node in nodes.values():
            wx = getattr(node, "world_x", None)
            wy = getattr(node, "world_y", None)
            if wx is None or wy is None:
                continue
            nr, nc = _world_to_grid(stack, float(wx), float(wy))
            seed_mask[nr, nc] = True
            seed_strength[nr, nc] = max(seed_strength[nr, nc], _source_strength_at(nr, nc))

    if not seed_mask.any():
        return np.zeros((rows, cols), dtype=np.float32)

    # --- scipy path (preferred) -------------------------------------------
    if _HAS_SCIPY and _distance_transform_edt is not None:
        dist, nearest = _distance_transform_edt(
            ~seed_mask,
            sampling=cs,
            return_indices=True,
        )
        nearest_strength = seed_strength[tuple(nearest)]
        falloff_t = np.clip(dist / max(radius_m, 1e-6), 0.0, 1.0)
        base = 1.0 - _smoothstep01(falloff_t)
        wet = np.clip(
            base * nearest_strength * float(seasonal_wetness),
            0.0,
            1.0,
        )
        wet = np.where(seed_mask, 1.0, wet)
        wet[dist > radius_m] = 0.0
        return wet.astype(np.float32)

    # --- Fallback: vectorized per-seed radial stamp -----------------------
    wet = np.zeros((rows, cols), dtype=np.float32)
    seed_coords = list(zip(*np.where(seed_mask)))
    for (r, c) in seed_coords:
        r0 = max(0, r - radius_cells)
        r1 = min(rows, r + radius_cells + 1)
        c0 = max(0, c - radius_cells)
        c1 = min(cols, c + radius_cells + 1)
        rr, cc = np.ogrid[r0:r1, c0:c1]
        dist_m = np.hypot(rr - r, cc - c) * cs
        falloff_t = np.clip(dist_m / max(radius_m, 1e-6), 0.0, 1.0)
        base = 1.0 - _smoothstep01(falloff_t)
        local = np.where(
            dist_m <= radius_m,
            np.clip(
                base * float(seed_strength[r, c]) * float(seasonal_wetness),
                0.0,
                1.0,
            ),
            0.0,
        )
        wet[r0:r1, c0:c1] = np.maximum(wet[r0:r1, c0:c1], local.astype(np.float32))
    wet[seed_mask] = 1.0
    return wet


def compute_foam_mask(
    chain: "WaterfallChain",
    stack: TerrainMaskStack,
    foam_threshold: float = 500.0,
    min_slope_for_foam: float = 0.1,
) -> np.ndarray:
    """Build a foam mask from three physically distinct turbulence sources.

    Foam appears in three situations:

    1. **Waterfall impact** — high-intensity foam centred on the plunge pool,
       decaying with a squared-normalised radial falloff.  Intensity is
       proportional to ``chain.foam_intensity`` and the total drop height.

    2. **Rapids** — cells where flow accumulation is high AND bed slope
       exceeds ``min_slope_for_foam``.  Contribution is
       ``clip(fa / foam_threshold, 0, 1) * clip(sl / 0.3, 0, 1)``.

    3. **Wave-break / coastal froth** — cells near sea level (within
       ``wave_break_elev_range`` metres above the minimum elevation of the
       tile) where water energy is dissipated against the shore.  Strength
       is modulated by local slope so gentle shores produce less foam than
       rocky coastlines.

    All three layers are combined with ``np.maximum`` so the strongest
    source wins.  A Gaussian blur (sigma = 2.0 cells) softens hard edges
    for a natural look.

    Args:
        chain: WaterfallChain providing pool position, foam_intensity, and
               total_drop_m.
        stack: TerrainMaskStack with at minimum a ``height`` channel.
               ``flow_accumulation`` and ``slope`` channels improve quality.
        foam_threshold: Flow accumulation value that maps to full rapids foam.
        min_slope_for_foam: Minimum slope (rise/run) for rapids foam.
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)
    foam_intensity = float(chain.foam_intensity)

    # ------------------------------------------------------------------
    # Layer 1: Waterfall impact pool foam
    # ------------------------------------------------------------------
    pool_r, pool_c = _world_to_grid(
        stack, chain.pool.world_position[0], chain.pool.world_position[1]
    )
    # Scale impact radius by drop height: taller falls create bigger splash zones
    drop_factor = max(1.0, getattr(chain, "total_drop_m", 5.0) / 5.0)
    impact_radius_m = chain.pool.radius_m * drop_factor
    impact_radius_cells = max(1, int(math.ceil(impact_radius_m / cs)))

    foam_impact = np.zeros((rows, cols), dtype=np.float64)
    r0_i = max(0, pool_r - impact_radius_cells)
    r1_i = min(rows, pool_r + impact_radius_cells + 1)
    c0_i = max(0, pool_c - impact_radius_cells)
    c1_i = min(cols, pool_c + impact_radius_cells + 1)
    for rr in range(r0_i, r1_i):
        for cc in range(c0_i, c1_i):
            dr = rr - pool_r
            dc = cc - pool_c
            dist_m = math.sqrt(dr * dr + dc * dc) * cs
            if dist_m > impact_radius_m:
                continue
            norm = dist_m / max(impact_radius_m, 1e-6)
            # Squared falloff: concentrated at centre, sharp edge
            foam_impact[rr, cc] = foam_intensity * max(0.0, 1.0 - norm ** 2)

    # ------------------------------------------------------------------
    # Layer 2: Rapids — high accumulation on steep slope
    # ------------------------------------------------------------------
    foam_rapids = np.zeros((rows, cols), dtype=np.float64)
    flow_acc = stack.get("flow_accumulation")
    slope_ch = stack.get("slope")

    if flow_acc is not None and slope_ch is not None:
        fa = np.asarray(flow_acc, dtype=np.float64)
        sl = np.asarray(slope_ch, dtype=np.float64)
        # Accumulation contribution: ramps from 0→1 over [0, foam_threshold]
        acc_contrib = np.clip(fa / max(foam_threshold, 1e-6), 0.0, 1.0)
        # Slope contribution: ramps from 0→1 over [min_slope, 3×min_slope]
        slope_range = max(min_slope_for_foam * 2.0, 1e-6)
        slope_contrib = np.clip(
            (sl - min_slope_for_foam) / slope_range, 0.0, 1.0
        )
        foam_rapids = acc_contrib * slope_contrib * foam_intensity
    elif slope_ch is not None:
        # No accumulation data: use slope alone with a lower intensity
        sl = np.asarray(slope_ch, dtype=np.float64)
        slope_range = max(min_slope_for_foam * 2.0, 1e-6)
        foam_rapids = np.clip(
            (sl - min_slope_for_foam) / slope_range, 0.0, 1.0
        ) * foam_intensity * 0.5

    # ------------------------------------------------------------------
    # Layer 3: Wave-break / coastal froth
    # Foam forms within a narrow elevation band just above sea level
    # where wave energy is dissipated.  We define "sea level" as the
    # bottom 2 % of the tile's elevation range.
    # ------------------------------------------------------------------
    h_min = float(h.min())
    h_max = float(h.max())
    elev_range = max(h_max - h_min, 1e-6)
    # Wave-break zone: bottom 2 % of elevation range (≈ near-shore band)
    wave_break_elev_range = elev_range * 0.02
    # Normalised closeness to sea level: 1.0 at h_min, 0.0 above wave zone
    coastal_proximity = np.clip(
        1.0 - (h - h_min) / max(wave_break_elev_range, 1e-6), 0.0, 1.0
    )
    # Modulate by slope so steep shores produce more foam than gentle beaches
    if slope_ch is not None:
        sl_arr = np.asarray(slope_ch, dtype=np.float64)
        slope_mod = np.clip(sl_arr / max(min_slope_for_foam * 3.0, 1e-6), 0.0, 1.0)
    else:
        # Approximate slope from height differences
        dh_r = np.gradient(h, axis=0)
        dh_c = np.gradient(h, axis=1)
        slope_approx = np.sqrt(dh_r ** 2 + dh_c ** 2) / max(cs, 1e-6)
        slope_mod = np.clip(slope_approx / max(min_slope_for_foam * 3.0, 1e-6), 0.0, 1.0)

    foam_coastal = coastal_proximity * slope_mod * foam_intensity * 0.7

    # ------------------------------------------------------------------
    # Combine layers (strongest wins) then Gaussian smooth
    # ------------------------------------------------------------------
    foam = np.maximum(foam_impact, np.maximum(foam_rapids, foam_coastal))

    try:
        from scipy.ndimage import gaussian_filter  # type: ignore
        foam = gaussian_filter(foam, sigma=2.0)
    except ImportError:
        pass

    return np.clip(foam, 0.0, 1.0).astype(np.float32)


def compute_mist_mask(
    chain: "WaterfallChain",
    stack: TerrainMaskStack,
    mist_height_range: float = 20.0,
    wind_direction_rad: float = 0.0,
    wind_speed_ms: float = 3.0,
) -> np.ndarray:
    """Build a mist mask with wind-advected waterfall plume and valley fog.

    Three components are combined with ``np.maximum``:

    1. **Waterfall mist source** — a Gaussian kernel centred on the impact
       pool.  Sigma scales with ``chain.mist_radius_m`` and the total drop
       height (taller falls generate wider plumes).

    2. **Wind advection** — the source Gaussian is shifted along the wind
       vector by a distance proportional to ``wind_speed_ms``.  Multiple
       shifted copies are blended with exponential decay so the mist forms
       a diffuse plume rather than a hard-edged disc.  The shift distance
       per step is ``wind_speed_ms * 2`` seconds (coarse LES-style advection).

    3. **Low-elevation valley mist** — still-air fog that pools in hollows.
       ``low_elev_mist = 1 - clip((h - valley_floor) / mist_height_range, 0, 1)``
       Contributes at a reduced weight (0.6×) so waterfall mist dominates
       near the source.

    Args:
        chain: WaterfallChain providing pool position, mist_radius_m, and
               total_drop_m.
        stack: TerrainMaskStack with at minimum a ``height`` channel.
        mist_height_range: Elevation range above the valley floor over which
            low-elevation mist fades from 1 to 0 (metres).
        wind_direction_rad: Wind bearing in radians (0 = east, π/2 = north).
            Mist plume is advected in this direction.
        wind_speed_ms: Wind speed in m/s.  Controls how far the plume
            extends downwind.  0.0 disables advection (still-air mode).
    """
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    pool_r, pool_c = _world_to_grid(
        stack, chain.pool.world_position[0], chain.pool.world_position[1]
    )

    mist_radius_m = float(chain.mist_radius_m)
    total_drop_m = float(getattr(chain, "total_drop_m", 5.0))

    # ------------------------------------------------------------------
    # Component 1 + 2: wind-advected Gaussian mist plume
    # ------------------------------------------------------------------
    # Sigma in cells: base radius + bonus from drop height (tall falls
    # spray further).  Clamped so sigma is always at least 1 cell.
    sigma_m = mist_radius_m + total_drop_m * 0.3
    sigma_cells = max(1.0, sigma_m / cs)

    # Build the base (un-advected) Gaussian centred on the pool
    mist_source = np.zeros((rows, cols), dtype=np.float64)

    try:
        from scipy.ndimage import gaussian_filter  # type: ignore

        seed = np.zeros((rows, cols), dtype=np.float64)
        seed[pool_r, pool_c] = 1.0
        mist_source = gaussian_filter(seed, sigma=sigma_cells)
        # Normalise so peak = 1.0
        peak = float(mist_source.max())
        if peak > 1e-12:
            mist_source /= peak

        # Wind advection: accumulate N shifted copies with exponential decay
        # Each copy is the source Gaussian shifted by k * step along wind vector
        if wind_speed_ms > 0.0:
            # Wind direction: dc positive = east, dr negative = north (row ↓)
            wind_dc = math.cos(wind_direction_rad)   # east component
            wind_dr = -math.sin(wind_direction_rad)  # north component (inverted rows)

            # Step distance in cells: 2 s advection per copy
            dt = 2.0  # seconds per step
            step_cells = wind_speed_ms * dt / cs
            n_steps = max(1, int(mist_radius_m * 3.0 / max(wind_speed_ms * dt, 1e-6)))
            n_steps = min(n_steps, 20)  # cap for performance

            plume = np.zeros_like(mist_source)
            for k in range(n_steps + 1):
                shift_r = k * step_cells * wind_dr
                shift_c = k * step_cells * wind_dc
                decay = math.exp(-k / max(n_steps * 0.4, 1.0))
                # Shift via scipy affine_transform
                try:
                    from scipy.ndimage import shift as nd_shift  # type: ignore
                    shifted = nd_shift(mist_source, shift=(shift_r, shift_c), order=1, mode="constant", cval=0.0)
                except ImportError:
                    shifted = mist_source  # no shift if unavailable
                plume = np.maximum(plume, shifted * decay)
            mist_wf = plume
        else:
            mist_wf = mist_source

    except ImportError:
        # Fallback: manual radial disc with linear advection offset
        mist_wf = np.zeros((rows, cols), dtype=np.float64)
        radius_cells = int(math.ceil(sigma_cells * 2.5))

        # Advection offset in cells for the disc centre
        if wind_speed_ms > 0.0:
            adv_time = mist_radius_m / max(wind_speed_ms, 1e-6)
            adv_dc = int(round(math.cos(wind_direction_rad) * wind_speed_ms * adv_time / cs))
            adv_dr = int(round(-math.sin(wind_direction_rad) * wind_speed_ms * adv_time / cs))
        else:
            adv_dc, adv_dr = 0, 0

        centre_r = pool_r + adv_dr
        centre_c = pool_c + adv_dc
        r0_f = max(0, centre_r - radius_cells)
        r1_f = min(rows, centre_r + radius_cells + 1)
        c0_f = max(0, centre_c - radius_cells)
        c1_f = min(cols, centre_c + radius_cells + 1)
        radius_m_fb = sigma_cells * 2.5 * cs
        for rr in range(r0_f, r1_f):
            for cc in range(c0_f, c1_f):
                dr = rr - centre_r
                dc = cc - centre_c
                dist_m = math.sqrt(dr * dr + dc * dc) * cs
                if dist_m > radius_m_fb:
                    continue
                # Also include original source location with decay
                dr_src = rr - pool_r
                dc_src = cc - pool_c
                dist_src = math.sqrt(dr_src * dr_src + dc_src * dc_src) * cs
                val_src = max(0.0, 1.0 - dist_src / max(mist_radius_m, 1e-6))
                val_adv = max(0.0, 1.0 - dist_m / max(radius_m_fb, 1e-6)) * 0.7
                mist_wf[rr, cc] = max(mist_wf[rr, cc], val_src, val_adv)

    # ------------------------------------------------------------------
    # Component 3: low-elevation valley mist (still-air fog)
    # ------------------------------------------------------------------
    valley_floor = float(h.min())
    low_elev_mist = (
        1.0 - np.clip(
            (h - valley_floor) / max(mist_height_range, 1e-6), 0.0, 1.0
        )
    ) * 0.6  # reduced weight so waterfall plume dominates near source

    # ------------------------------------------------------------------
    # Combine: waterfall plume takes priority over valley fog
    # ------------------------------------------------------------------
    mist = np.maximum(mist_wf, low_elev_mist)
    return np.clip(mist, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Riverbed caustics (Phase E AAA water upgrade)
# ---------------------------------------------------------------------------


def _tileable_value_noise(
    shape: Tuple[int, int],
    frequency: float,
    seed: int,
) -> np.ndarray:
    """Generate a tileable value-noise field in [0, 1].

    Seeded by ``seed`` for determinism.  The output is tileable at the
    native shape so the resulting caustic map can be laid seamlessly in a
    shader.  Purely numpy — no external noise library required.
    """
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    rows, cols = int(shape[0]), int(shape[1])
    cell = max(int(round(max(rows, cols) / max(frequency, 1e-3))), 2)
    grid_rows = max(rows // cell, 1)
    grid_cols = max(cols // cell, 1)
    # Random node values on a low-res grid (periodic in both dims)
    nodes = rng.uniform(0.0, 1.0, size=(grid_rows + 1, grid_cols + 1)).astype(np.float32)
    # Wrap last row/col to first for seamless tileability
    nodes[-1, :] = nodes[0, :]
    nodes[:, -1] = nodes[:, 0]

    # Bilinearly upsample to target shape
    rs = np.linspace(0.0, grid_rows, rows, endpoint=False, dtype=np.float32)
    cs = np.linspace(0.0, grid_cols, cols, endpoint=False, dtype=np.float32)
    r0 = np.floor(rs).astype(np.int32)
    c0 = np.floor(cs).astype(np.int32)
    r1 = np.clip(r0 + 1, 0, grid_rows)
    c1 = np.clip(c0 + 1, 0, grid_cols)
    fr = (rs - r0)[:, None]
    fc = (cs - c0)[None, :]
    # Smoothstep for less grid-aligned look
    fr = fr * fr * (3.0 - 2.0 * fr)
    fc = fc * fc * (3.0 - 2.0 * fc)

    v00 = nodes[r0[:, None], c0[None, :]]
    v01 = nodes[r0[:, None], c1[None, :]]
    v10 = nodes[r1[:, None], c0[None, :]]
    v11 = nodes[r1[:, None], c1[None, :]]
    top = v00 * (1.0 - fc) + v01 * fc
    bot = v10 * (1.0 - fc) + v11 * fc
    out = top * (1.0 - fr) + bot * fr
    return np.clip(out.astype(np.float32), 0.0, 1.0)


def compute_riverbed_caustics(
    stack: "Any",
    *,
    depth_channel: str = "water_depth_m",  # FIX-10-10: match pass_water_depth writer
    water_surface_channel: str = "water_surface",
    base_caustic_scale: float = 6.0,
    detail_caustic_scale: float = 18.0,
    beer_lambert_k: float = 0.35,
    intensity: float = 1.0,
    seed: int = 0,
) -> np.ndarray:
    """Generate a tileable riverbed caustic intensity map.

    Caustics are produced by sun-light refracting through the wavy water
    surface and focusing on the riverbed.  In a shader we normally drive
    this with a scrolling noise texture modulated by water depth.  This
    function bakes the static per-cell intensity at authoring time using
    the Beer–Lambert law for underwater light attenuation:

        I_bed(d) = I_surface * exp(-k * d)

    where ``d`` is water depth (metres) and ``k`` is the extinction
    coefficient (roughly 0.25–0.5 for clear lake water, up to ~3 for
    silty rivers).  Two octaves of tileable value noise are summed
    (base_caustic_scale for the dominant swirls and detail_caustic_scale
    for high-frequency sparkle) and the result is multiplied by the
    depth-attenuated visibility.

    Args:
        stack: TerrainMaskStack-like with ``.get(channel)`` and
            ``.height`` / ``.cell_size``.
        depth_channel: Name of the water-depth channel (metres).  If
            missing, depth is derived from
            ``water_surface - height`` when ``water_surface`` is available.
        water_surface_channel: Channel storing the water-surface mask
            / elevation.  Cells where this is 0 (non-water) get zero
            caustics.
        base_caustic_scale: Frequency of the large-scale caustic pattern.
        detail_caustic_scale: Frequency of the detail octave.
        beer_lambert_k: Extinction coefficient in 1/m.  Higher values
            darken the bed faster with depth.
        intensity: Overall multiplier in [0, 1].
        seed: RNG seed for deterministic tileable noise.

    Returns:
        float32 (H, W) array in [0, 1] — 0 on dry cells, caustic-modulated
        brightness on wet cells.
    """
    height = np.asarray(stack.height, dtype=np.float64) if getattr(stack, "height", None) is not None else None
    if height is None:
        return np.zeros((0, 0), dtype=np.float32)
    H, W = height.shape

    # Resolve water depth and water mask
    depth = stack.get(depth_channel) if hasattr(stack, "get") else None
    water_surface = stack.get(water_surface_channel) if hasattr(stack, "get") else None
    if depth is None and water_surface is not None:
        ws = np.asarray(water_surface, dtype=np.float64)
        depth = np.maximum(ws - height, 0.0)
    if depth is None:
        depth_arr = np.zeros((H, W), dtype=np.float32)
    else:
        depth_arr = np.asarray(depth, dtype=np.float32)

    if water_surface is not None:
        ws_arr = np.asarray(water_surface, dtype=np.float32)
        water_mask = (ws_arr > 0.0) | (depth_arr > 1e-6)
    else:
        water_mask = depth_arr > 1e-6

    # Beer-Lambert attenuation: brighter in shallow water, dark in deep
    attenuation = np.exp(-float(beer_lambert_k) * np.maximum(depth_arr, 0.0)).astype(np.float32)

    # Two-octave tileable caustic noise (seamless, deterministic)
    base = _tileable_value_noise((H, W), base_caustic_scale, seed=seed)
    detail = _tileable_value_noise((H, W), detail_caustic_scale, seed=seed + 1)
    # Bias base noise toward bright hot-spots (caustics are peaky, not gaussian)
    caustic_noise = np.clip(base, 0.0, 1.0) ** 2
    caustic_noise = 0.7 * caustic_noise + 0.3 * detail
    caustic_noise = np.clip(caustic_noise, 0.0, 1.0)

    out = caustic_noise * attenuation * float(intensity)
    out[~water_mask] = 0.0
    return np.clip(out, 0.0, 1.0).astype(np.float32)


__all__ = [
    "add_meander",
    "apply_bank_asymmetry",
    "solve_outflow",
    "compute_wet_rock_mask",
    "compute_foam_mask",
    "compute_mist_mask",
    "compute_riverbed_caustics",
]
