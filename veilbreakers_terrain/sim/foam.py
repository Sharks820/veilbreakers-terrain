"""foam.py — AAA-quality waterfall and shoreline foam mask generation.

Implements the full foam model derived from Bifrost/hydraulics research:
  A. Obstacle-proximity foam (existing bake_foam_vertex_alpha)
  B. Froude-number whitecap foam (supercritical flow whitecaps)
  C. Kelvin wake chevron behind rocks (fixed 19.47-degree half-angle)
  D. Shoreline depth-fade foam (UE5/Unity depth-difference technique)
  E. Convergence/vorticity foam (trapped air in churning flow)

Sources:
  Autodesk Maya 2018 Bifrost Foam Properties (Autodesk cloudhelp)
  PMC9363398 "Hydraulic jumps: air-water patterns and void fraction" (2022)
  Wikipedia "Kelvin wake pattern" + Harvard Kelvin wakes paper (Bostan 2021)
  Roystan "Toon Water Shader" (roystan.net) — depth-diff foam formula
  Valve SIGGRAPH 2010 "Water Flow in Portal 2" — flow map dual-phase UV
"""
from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter


# ---------------------------------------------------------------------------
# Froude-number foam intensity
# ---------------------------------------------------------------------------

def froude_foam_intensity(
    flow_speed: np.ndarray,
    flow_depth: float = 0.3,
) -> np.ndarray:
    """Whitecap foam intensity from Froude number per cell.

    Fr < 1.7  → no whitecaps (subcritical / undular jump)
    Fr 1.7-4.5 → ramping whitecaps
    Fr > 4.5  → maximum foam (strong hydraulic jump)

    Based on PMC9363398 Table 1 hydraulic jump regimes.

    Args:
        flow_speed: (H, W) flow velocity magnitude in m/s.
        flow_depth: Approximate flow depth in metres (uniform approximation).

    Returns:
        (H, W) float32 foam intensity in [0, 1].
    """
    g = 9.81
    Fr = np.asarray(flow_speed, dtype=np.float32) / math.sqrt(g * max(flow_depth, 0.01))
    foam = np.clip((Fr - 1.7) / (4.5 - 1.7), 0.0, 1.0).astype(np.float32)
    return foam


# ---------------------------------------------------------------------------
# Kelvin wake behind rocks
# ---------------------------------------------------------------------------

def kelvin_wake_mask(
    pos_grid_x: np.ndarray,
    pos_grid_y: np.ndarray,
    rock_row: float,
    rock_col: float,
    flow_dir_xy: tuple[float, float],
    flow_speed: float,
    cell_size: float = 1.0,
    max_dist_m: float = 20.0,
) -> np.ndarray:
    """2-D foam mask for the Kelvin chevron wake behind a rock.

    The Kelvin wake half-angle is arcsin(1/3) = 19.47 degrees for subcritical
    obstacles (Fr_rock < 1).  For supercritical obstacles the angle narrows
    following sin(theta) = 1 / (3 * Fr_rock).

    Args:
        pos_grid_x: (H, W) world-X coordinate of each cell.
        pos_grid_y: (H, W) world-Y coordinate of each cell.
        rock_row, rock_col: Rock centre in grid coordinates.
        flow_dir_xy: Normalised (dx, dy) flow direction (horizontal plane).
        flow_speed: Flow speed in m/s for Froude correction.
        cell_size: Metres per grid cell.
        max_dist_m: Wake intensity falls to 0 at this distance.

    Returns:
        (H, W) float32 wake-foam intensity in [0, 1].
    """
    rock_x = rock_col * cell_size
    rock_y = rock_row * cell_size
    dx_flow, dy_flow = flow_dir_xy
    norm = math.sqrt(dx_flow ** 2 + dy_flow ** 2)
    if norm < 1e-9:
        return np.zeros(pos_grid_x.shape, dtype=np.float32)
    dx_flow, dy_flow = dx_flow / norm, dy_flow / norm

    # ADV-PR97-01 (CHECKPOINT-2 hotfix): stationary water must produce zero wake.
    # PR #97 fixed the half-angle math (arcsin(1/3) = 19.47 deg) but left the
    # zero-flow-speed regression unguarded: when flow_speed == 0 the cone is
    # still emitted at 19.47 deg, which is credible-but-wrong silent corruption
    # (pre-PR-97 emitted an obviously-wrong 90 deg cone instead). A Kelvin wake
    # only exists where there is actual relative motion between fluid and
    # obstacle; below ~1 mm/s no coherent wake forms (Bostan 2021 sec. 2).
    if flow_speed < 1e-3:
        return np.zeros(pos_grid_x.shape, dtype=np.float32)

    rel_x = pos_grid_x - rock_x
    rel_y = pos_grid_y - rock_y

    along = rel_x * dx_flow + rel_y * dy_flow
    across = rel_x * (-dy_flow) + rel_y * dx_flow

    Fr_rock = flow_speed / max(math.sqrt(9.81 * cell_size), 1e-6)
    # T1-40 fix (S09-P0-01): the prior clamp `max(3.0 * Fr_rock, 1.0)` collapsed
    # to asin(1) == pi/2 for any Fr_rock < 1/3, producing a 90 deg half-plane
    # "wake". Correct subcritical Kelvin half-angle is arcsin(1/3) = 19.47 deg
    # (Lord Kelvin 1887); the cone narrows only as Fr_rock > 1.
    inv = 1.0 / max(3.0 * Fr_rock, 1e-6)
    wake_half_angle = math.asin(min(1.0 / 3.0, inv))
    tan_wake = math.tan(wake_half_angle)

    in_wake = (along > 0) & (np.abs(across) < along * tan_wake)

    dist = np.sqrt(along ** 2 + across ** 2)
    intensity = np.exp(-dist / (max_dist_m * 0.3 + 1e-9)) * in_wake.astype(np.float32)
    return np.clip(intensity, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Shoreline depth-fade foam
# ---------------------------------------------------------------------------

def shoreline_depth_foam(
    water_depth: np.ndarray,
    foam_min_depth: float = 0.05,
    foam_max_depth: float = 0.60,
    noise_cutoff: float = 0.50,
    noise_seed: int = 42,
) -> np.ndarray:
    """Depth-difference shoreline foam, matching UE5/Unity water shaders.

    Inverted depth ramp: shallowest cells get the most foam.
    Thresholded against an FBM noise texture to produce natural foam edges.

    Based on:
      Roystan "Toon Water Shader" (roystan.net) — depth-diff formula
      Halisavakis water shader (halisavakis.com) — smoothstep AA

    Args:
        water_depth: (H, W) metres of water above terrain (0 = shoreline).
        foam_min_depth: Depth where foam starts (< this = full foam).
        foam_max_depth: Depth where foam ends (> this = no foam).
        noise_cutoff: FBM noise threshold for foam edge detection [0, 1].
        noise_seed: Reproducibility seed for noise generation.

    Returns:
        (H, W) float32 shoreline foam in [0, 1].
    """
    depth = np.asarray(water_depth, dtype=np.float32)
    H, W = depth.shape

    foam_factor = 1.0 - np.clip(
        (depth - foam_min_depth) / max(foam_max_depth - foam_min_depth, 1e-6),
        0.0, 1.0,
    )

    noise = _fbm_noise(H, W, octaves=4, seed=noise_seed)
    raw = noise * foam_factor
    AA = 0.05
    foam = np.clip((raw - (noise_cutoff - AA)) / (2.0 * AA), 0.0, 1.0)
    return foam.astype(np.float32)


# ---------------------------------------------------------------------------
# Combined AAA foam mask
# ---------------------------------------------------------------------------

def generate_foam_mask(
    height: np.ndarray,
    flow_speed: np.ndarray,
    water_mask: np.ndarray,
    water_depth: np.ndarray,
    rock_mask: np.ndarray,
    cell_size: float = 1.0,
    flow_depth: float = 0.3,
    rock_positions: list | None = None,
    flow_dir: np.ndarray | None = None,
    noise_seed: int = 42,
) -> np.ndarray:
    """Full AAA foam mask combining all foam sources.

    Weights tuned to match KCD2 / RDR2 reference:
      40% obstacle-proximity (dominant visual foam at shores/rocks)
      25% shoreline depth-fade (smooth edge transition)
      20% Froude whitecaps (supercritical flow)
      15% convergence/churn (vorticity foam)

    Args:
        height: (H, W) terrain heightmap in metres.
        flow_speed: (H, W) flow velocity magnitude in m/s.
        water_mask: (H, W) bool, True = water surface.
        water_depth: (H, W) metres of water above terrain.
        rock_mask: (H, W) bool, True = rock/obstacle.
        cell_size: Metres per grid cell.
        flow_depth: Approximate uniform flow depth for Froude calc.
        rock_positions: Optional list of (row, col) for Kelvin wakes.
        flow_dir: Optional (H, W, 2) velocity vectors for vorticity foam.
        noise_seed: Reproducibility seed.

    Returns:
        (H, W) float32 combined foam intensity in [0, 1].
    """
    H, W = height.shape
    speed = np.where(water_mask, np.asarray(flow_speed, dtype=np.float32), 0.0)

    # A — Obstacle proximity
    obstacle = np.asarray(rock_mask, dtype=bool) | ~np.asarray(water_mask, dtype=bool)
    dist_m = distance_transform_edt(~obstacle).astype(np.float32) * cell_size
    FOAM_RADIUS = 2.5
    prox_foam = np.exp(-dist_m / FOAM_RADIUS)
    prox_foam = np.where(water_mask, prox_foam, 0.0)

    # B — Shoreline depth-fade
    shore_foam = shoreline_depth_foam(water_depth, noise_seed=noise_seed)
    shore_foam = np.where(water_mask, shore_foam, 0.0)

    # C — Froude whitecaps
    froude_foam = froude_foam_intensity(speed, flow_depth)
    froude_foam = np.where(water_mask, froude_foam, 0.0)

    # D — Vorticity/convergence (requires velocity field)
    if flow_dir is not None and flow_dir.ndim == 3:
        dvx_dy = np.gradient(flow_dir[..., 0], axis=0) / cell_size
        dvy_dx = np.gradient(flow_dir[..., 1], axis=1) / cell_size
        vorticity = np.abs(dvy_dx - dvx_dy)
        vort_foam = np.clip((vorticity - 0.5) / 4.5, 0.0, 1.0).astype(np.float32)

        dvx_dx = np.gradient(flow_dir[..., 0], axis=1) / cell_size
        dvy_dy = np.gradient(flow_dir[..., 1], axis=0) / cell_size
        convergence = np.clip(-(dvx_dx + dvy_dy) / 5.0, 0.0, 1.0).astype(np.float32)
        churn_foam = np.maximum(vort_foam, convergence)
    else:
        churn_foam = np.zeros((H, W), dtype=np.float32)
    churn_foam = np.where(water_mask, churn_foam, 0.0)

    # E — Kelvin wakes behind explicit rock positions
    #
    # T1-43 fix (Wave-T03-NEW): previously this call passed the constant
    # ``(1.0, 0.0)`` for ``flow_dir_xy``, so every shoreline wake pointed East
    # regardless of the actual local flow field. We now sample the per-rock
    # flow direction from ``flow_dir`` when supplied (the canonical pipeline
    # feeds ``stack["waterfall_velocity"]`` shaped (H, W, 2) -- channel 0 is
    # V_x/east, channel 1 is V_y/north per ``generate_velocity_field``), and
    # fall back to East only when the local magnitude underflows.
    #
    # ADV-CP4-03 (CHECKPOINT-4 V2 hotfix): the prior zero-flow gate used the
    # GLOBAL water_mask mean speed (``speed[water_mask].mean()``) to decide
    # whether to render a wake at every rock. This silenced ALL rock wakes in
    # rivers with eddies (some cells fast, mean ~0 → no wakes) and spuriously
    # generated wakes around stagnant rocks in turbulent reaches (some cells
    # fast, mean high → wakes everywhere). Sample the LOCAL flow speed at each
    # rock_position and skip the rock if the local magnitude underflows the
    # 1 mm/s threshold (matching the per-rock guard inside ``kelvin_wake_mask``
    # at line 101). The fast path keeps unit cost: nearest-cell lookup is O(1)
    # per rock, vs. the prior global mask reduction over (H, W).
    kelvin_foam = np.zeros((H, W), dtype=np.float32)
    if rock_positions:
        rows_g = np.arange(H)[:, None] * cell_size
        cols_g = np.arange(W)[None, :] * cell_size
        speed_arr = np.asarray(speed, dtype=np.float32)
        for (r, c) in rock_positions:
            # Per-rock local flow magnitude — nearest cell to the rock centre.
            ri = int(round(float(r)))
            ci = int(round(float(c)))
            if 0 <= ri < H and 0 <= ci < W:
                local_speed = float(speed_arr[ri, ci])
            else:
                # Rock outside the grid → no wake (no flow data to gate on).
                continue
            # 1 mm/s threshold mirrors ``kelvin_wake_mask``'s internal guard
            # (foam.py:101) — keeps source-of-truth single per ADV-PR97-01.
            if local_speed < 1e-3:
                continue
            local_dir = _local_flow_dir_at(flow_dir, r, c, fallback=(1.0, 0.0))
            wake = kelvin_wake_mask(
                cols_g, rows_g, r, c, local_dir, local_speed, cell_size
            )
            kelvin_foam = np.maximum(kelvin_foam, wake)
    kelvin_extra = kelvin_foam * 0.10

    # Combine
    foam = (
        0.40 * np.asarray(prox_foam, dtype=np.float32)
        + 0.25 * np.asarray(shore_foam, dtype=np.float32)
        + 0.20 * np.asarray(froude_foam, dtype=np.float32)
        + 0.15 * np.asarray(churn_foam, dtype=np.float32)
        + kelvin_extra
    )
    foam_smooth = gaussian_filter(foam.astype(np.float64), sigma=0.8).astype(np.float32)
    return np.clip(foam_smooth, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Flow map UV baking (Valve dual-phase)
# ---------------------------------------------------------------------------

def bake_flow_map(velocity_field: np.ndarray) -> np.ndarray:
    """Convert (H, W, 2) velocity vectors to (H, W, 2) uint8 flow map texture.

    R = X velocity, G = Y velocity; 128 = zero velocity.
    Matches UE5/Unity flow map convention.

    Source: Valve SIGGRAPH 2010 "Water Flow in Portal 2" (Vlachos)
    """
    vfield = np.asarray(velocity_field, dtype=np.float32)
    if vfield.ndim != 3 or vfield.shape[2] != 2:
        raise ValueError("velocity_field must be (H, W, 2)")
    mag = np.linalg.norm(vfield, axis=2)
    # T1-42 fix (S09-P0-03): the prior implementation clipped AFTER
    # `*0.5 + 0.5`, which collapsed every cell with `mag > vmax` (top 1%) to
    # the identical encoded value 255 -- losing direction in the most visually
    # important Kelvin wakes / jets. Clip ``normalized`` to [-1, 1] FIRST so
    # the post-clip encoding preserves sign on both axes and the [0, 255]
    # range is guaranteed without a second clip. ``method='linear'`` is pinned
    # to keep numpy>=1.22 behaviour deterministic across versions.
    vmax = float(np.percentile(mag, 99, method="linear"))
    vmax = max(vmax, 0.01)
    normalized = np.clip(vfield / vmax, -1.0, 1.0)
    encoded = normalized * 0.5 + 0.5
    return (encoded * 255.0).astype(np.uint8)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_flow_dir_at(
    flow_field: np.ndarray | None,
    rock_row: float,
    rock_col: float,
    fallback: tuple[float, float] = (1.0, 0.0),
) -> tuple[float, float]:
    """Sample a unit ``(vx, vy)`` flow direction at ``(row, col)``.

    Used by ``generate_foam_mask`` for the T1-43 fix: per-rock Kelvin wakes
    align with the local flow field rather than a hard-coded East vector.

    Convention (matches ``generate_velocity_field`` in
    ``handlers/terrain_waterfalls.py``): ``flow_field`` has shape
    ``(H, W, 2)`` with channel 0 = ``V_x`` (east) and channel 1 = ``V_y``
    (north). When ``flow_field`` is ``None`` / wrong shape / out of bounds /
    too small in magnitude, the ``fallback`` direction is returned (unit
    length not enforced on the fallback — the caller is responsible).
    """
    if flow_field is None:
        return fallback
    arr = np.asarray(flow_field)
    if arr.ndim != 3 or arr.shape[-1] < 2:
        return fallback
    H, W = arr.shape[0], arr.shape[1]
    r = int(round(float(rock_row)))
    c = int(round(float(rock_col)))
    if not (0 <= r < H and 0 <= c < W):
        return fallback
    vx = float(arr[r, c, 0])
    vy = float(arr[r, c, 1])
    mag = math.sqrt(vx * vx + vy * vy)
    if mag < 1e-6:
        return fallback
    return (vx / mag, vy / mag)


def _fbm_noise(H: int, W: int, octaves: int = 4, seed: int = 0) -> np.ndarray:
    """Fast FBM approximation via scipy zoom upsampling. Returns [0, 1]."""
    from scipy.ndimage import zoom as _zoom
    rng = np.random.default_rng(seed)
    result = np.zeros((H, W), dtype=np.float64)
    amplitude = 0.5
    frequency = 1.0
    norm = 0.0
    for _ in range(octaves):
        h_ = max(1, int(H / frequency))
        w_ = max(1, int(W / frequency))
        layer = rng.random((h_, w_))
        layer_up = _zoom(layer, (H / h_, W / w_), order=1)
        result += amplitude * layer_up[:H, :W]
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return (result / max(norm, 1e-9)).astype(np.float32)


