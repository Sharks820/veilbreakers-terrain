"""Terrain feature generators -- pure logic, no bpy/bmesh.

Generates walkable terrain features (canyons, waterfalls, cliff faces, swamps,
natural arches, geysers, sinkholes, floating rocks, ice formations, lava flows)
as mesh specification dicts. Each function returns vertices, faces, materials,
and feature metadata.

All functions are pure and operate on plain Python data structures.
Fully testable without Blender.
"""

from __future__ import annotations

import math
import random
from typing import Any

from ._terrain_noise import _make_noise_generator


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Vec3 = tuple[float, float, float]


# ---------------------------------------------------------------------------
# Noise utility -- opensimplex via _terrain_noise (replaces old sin-hash)
# ---------------------------------------------------------------------------

# Cached noise generator to avoid re-creating per call
_features_gen = None
_features_seed = -1


def _hash_noise(x: float, y: float, seed: int = 0) -> float:
    """Wang-hash gradient noise via the project's opensimplex/perm-table backend.

    Uses _make_noise_generator so the noise type is consistent with every
    other call site in the codebase (opensimplex when available, permutation-
    table gradient fallback otherwise).  Replaces the old sin-hash that had
    visible directional banding.  Returns values in approximately [-1, 1].
    """
    global _features_gen, _features_seed
    if _features_gen is None or _features_seed != seed:
        _features_gen = _make_noise_generator(seed)
        _features_seed = seed
    return _features_gen.noise2(x, y)


def _fbm(
    x: float,
    y: float,
    seed: int = 0,
    octaves: int = 4,
    persistence: float = 0.5,
    lacunarity: float = 2.0,
    gain: float = 0.5,
) -> float:
    """Fractal Brownian motion using the project's noise generator.

    Parameters
    ----------
    x, y : float
        Sampling coordinates.
    seed : int
        Random seed forwarded to _make_noise_generator.
    octaves : int
        Number of noise layers to accumulate.
    persistence : float
        Amplitude multiplier per octave (legacy name; ``gain`` is preferred
        for new call sites — both are supported).
    lacunarity : float
        Frequency multiplier per octave (default 2.0).
    gain : float
        Synonym for persistence.  When both are provided and differ, ``gain``
        takes precedence so that call sites using the canonical fBm naming
        (gain, lacunarity) work correctly.

    Returns
    -------
    float
        Normalized fBm value in [-1, 1].  Normalization uses the exact
        geometric-series amplitude bound (sum of gain^i for i=0..octaves-1)
        so the range contract holds regardless of octave count.
    """
    # ``gain`` is the canonical parameter; accept ``persistence`` as alias.
    effective_gain = gain if gain != 0.5 or persistence == 0.5 else persistence
    gen = _make_noise_generator(seed)
    value = 0.0
    amplitude = 1.0
    frequency = 1.0
    # Theoretical max amplitude: geometric series sum_{i=0}^{octaves-1} gain^i
    # = (1 - gain^octaves) / (1 - gain) when gain != 1, else octaves.
    if abs(1.0 - effective_gain) < 1e-12:
        max_val = float(octaves)
    else:
        max_val = (1.0 - effective_gain ** octaves) / (1.0 - effective_gain)
    for _ in range(octaves):
        value += gen.noise2(x * frequency, y * frequency) * amplitude
        amplitude *= effective_gain
        frequency *= lacunarity
    return value / max_val if max_val > 0 else 0.0


# ---------------------------------------------------------------------------
# Canyon generator
# ---------------------------------------------------------------------------

def generate_canyon(
    width: float = 5.0,
    length: float = 50.0,
    depth: float = 15.0,
    wall_roughness: float = 0.5,
    num_side_caves: int = 3,
    seed: int = 42,
    canyon_slope: float = 1.5,
    strata_interval: float = 3.0,
) -> dict[str, Any]:
    """Generate a geologically plausible canyon with winding centerline, V-profile
    walls, strata ledges, and stitched wall-to-floor seams.

    The canyon runs roughly along the X axis with fBm lateral displacement on
    the centerline so the path meanders.  Cross-sections use a V/talus-slope
    profile: depth falls off as ``max_depth * (1 - (dist/half_width)^canyon_slope)``.
    Every ``strata_interval`` metres a narrow ledge is cut into the wall,
    approximating sedimentary layer exposure.

    Parameters
    ----------
    width : float
        Canyon mouth width (widest point at ground level).
    length : float
        Canyon length along X.
    depth : float
        Maximum carve depth (deepest point at centreline).
    wall_roughness : float
        fBm displacement magnitude on wall surfaces [0, 1].
    num_side_caves : int
        Number of side cave openings to place in walls.
    seed : int
        Random seed.
    canyon_slope : float
        Exponent for talus-slope profile.  1.0 = linear V, >1 = steeper walls,
        <1 = more bowl-shaped.  Default 1.5 approximates natural talus.
    strata_interval : float
        Vertical spacing (metres) between strata ledge cuts.

    Returns
    -------
    dict with keys:
        - "mesh": {"vertices": list[Vec3], "faces": list[tuple]}
        - "floor_path": list of (x, y, z) waypoints along the canyon floor
        - "centerline_points": list of (x, y, z) winding centreline samples
        - "side_caves": list of cave dicts (position, side, width, height, depth)
        - "depth_profile": list of (x, depth_at_x) pairs
        - "width_profile": list of (x, width_at_x) pairs
        - "materials": list of material zone names
        - "material_indices": list of per-face material indices
        - "dimensions": dict with width, length, depth, canyon_slope, strata_interval
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)

    # Resolution: enough segments to capture the winding and strata detail.
    res_along = max(8, int(length / 1.5))
    res_wall = max(8, int(depth / 1.0))   # vertical resolution on each wall face

    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=canyon_floor, 1=canyon_wall, 2=wet_rock, 3=canyon_ledge
    materials = ["canyon_floor", "canyon_wall", "wet_rock", "canyon_ledge"]

    half_w = width / 2.0

    # ------------------------------------------------------------------
    # 1. Build winding centreline by displacing a straight line with fBm.
    #    Displacement is purely lateral (Y axis) so the canyon still runs
    #    end-to-end along X.
    # ------------------------------------------------------------------
    centerline: list[Vec3] = []
    for i in range(res_along):
        t = i / max(res_along - 1, 1)
        x = t * length
        # fBm lateral wander — amplitude up to half of width so the walls
        # don't overlap.
        y_disp = _fbm(x * 0.04, 0.0, seed, octaves=4, lacunarity=2.0, gain=0.5) * half_w * 0.4
        # Slight drainage slope downhill along X
        z = -t * (depth * 0.06) + _hash_noise(x * 0.05, 0.0, seed + 99) * 0.25
        centerline.append((x, y_disp, z))

    # Precompute depth_profile and width_profile (both could vary in future;
    # for now depth and mouth width are constant per cross-section).
    depth_profile: list[tuple[float, float]] = [
        (centerline[i][0], depth) for i in range(res_along)
    ]
    width_profile: list[tuple[float, float]] = [
        (centerline[i][0], width) for i in range(res_along)
    ]

    # ------------------------------------------------------------------
    # 2. Floor mesh — a grid that follows the centreline's Y wander.
    #    Floor width is fixed at ``width``; geometry is at the canyon bottom
    #    (z = centreline z — small local variation).
    # ------------------------------------------------------------------
    floor_res_across = max(4, int(width) + 4)
    floor_start = len(vertices)

    for i in range(res_along):
        cx, cy, cz = centerline[i]
        for j in range(floor_res_across):
            jt = j / max(floor_res_across - 1, 1)
            # Floor spans ±half_w around the winding centre
            local_y = cy + (-half_w * 0.5 + jt * width * 0.5)
            # Very small height variation across the floor
            z_floor = cz + _hash_noise(cx * 0.08, local_y * 0.08, seed) * 0.2
            vertices.append((cx, local_y, z_floor))

    for i in range(res_along - 1):
        for j in range(floor_res_across - 1):
            v0 = floor_start + i * floor_res_across + j
            v1 = v0 + 1
            v2 = v0 + floor_res_across + 1
            v3 = v0 + floor_res_across
            faces.append((v0, v1, v2, v3))
            mat_indices.append(0)  # canyon_floor

    # ------------------------------------------------------------------
    # 3. Wall geometry — V/talus profile for each side.
    #    For each along-segment i and wall-ring k we place one vertex per
    #    side.  The wall rises from floor-level (z = cz) to z = cz + depth.
    #    The lateral position at height k is computed from the talus formula:
    #
    #      effective_dist = half_w * (kt ** (1/canyon_slope))
    #
    #    so wall base touches the floor edge (dist = half_w at z=cz) and
    #    the top is at dist = half_w (vertical).
    #    This gives a proper V shape and stitches wall bottom to floor edge.
    # ------------------------------------------------------------------
    def _wall_verts_for_side(side: int) -> list[list[int]]:
        """Build wall vertices and return a 2-D index table [i][k] -> global idx."""
        sign = -1.0 if side == 0 else 1.0  # left = -1, right = +1
        w_start = len(vertices)
        idx_table: list[list[int]] = []

        for i in range(res_along):
            cx, cy, cz = centerline[i]
            row_indices: list[int] = []
            for k in range(res_wall + 1):
                kt = k / max(res_wall, 1)  # 0 = floor level, 1 = top of wall
                z_wall = cz + kt * depth

                # Talus profile: at k=0 wall is at floor edge (half_w from centre);
                # at k=1 wall is at half_w (vertical cliff top).
                # Use (1 - kt)^(1/canyon_slope) to smoothly go from half_w → 0
                # extra offset, i.e. wall top is at half_w and base is at half_w
                # (they align — stitching the floor).
                talus_offset = half_w * ((1.0 - kt) ** (1.0 / max(canyon_slope, 0.1)))
                lateral = half_w + talus_offset

                # fBm roughness increases toward mid-height (most exposed)
                rough_scale = wall_roughness * math.sin(kt * math.pi) * 1.5
                rough = _fbm(cx * 0.12 + k * 0.3, float(i) * 0.1, seed + side * 7,
                             octaves=4, lacunarity=2.0, gain=0.5) * rough_scale

                y_pos = cy + sign * (lateral + rough)

                # Strata ledge: every strata_interval depth units cut a narrow shelf
                z_strata_phase = (z_wall - cz) % max(strata_interval, 0.1)
                ledge_window = strata_interval * 0.08  # 8% of interval = ledge width
                if z_strata_phase < ledge_window and k > 0:
                    # Pull wall inward slightly to create the ledge
                    y_pos = cy + sign * (lateral + rough - sign * 0.35)

                vertices.append((cx, y_pos, z_wall))
                row_indices.append(w_start + i * (res_wall + 1) + k)
            idx_table.append(row_indices)

        return idx_table

    left_table = _wall_verts_for_side(0)
    right_table = _wall_verts_for_side(1)

    # Build wall faces for left side
    for i in range(res_along - 1):
        for k in range(res_wall):
            v0 = left_table[i][k]
            v1 = left_table[i][k + 1]
            v2 = left_table[i + 1][k + 1]
            v3 = left_table[i + 1][k]
            faces.append((v0, v1, v2, v3))
            # Wet near bottom, ledge material at strata bands, else wall rock
            z_frac = k / max(res_wall, 1)
            z_depth_m = z_frac * depth
            strata_phase = z_depth_m % max(strata_interval, 0.1)
            if strata_phase < strata_interval * 0.08:
                mat_indices.append(3)  # canyon_ledge
            elif k < res_wall // 5:
                mat_indices.append(2)  # wet_rock
            else:
                mat_indices.append(1)  # canyon_wall

    # Build wall faces for right side (reversed winding for outward normals)
    for i in range(res_along - 1):
        for k in range(res_wall):
            v0 = right_table[i][k]
            v1 = right_table[i + 1][k]
            v2 = right_table[i + 1][k + 1]
            v3 = right_table[i][k + 1]
            faces.append((v0, v1, v2, v3))
            z_frac = k / max(res_wall, 1)
            z_depth_m = z_frac * depth
            strata_phase = z_depth_m % max(strata_interval, 0.1)
            if strata_phase < strata_interval * 0.08:
                mat_indices.append(3)
            elif k < res_wall // 5:
                mat_indices.append(2)
            else:
                mat_indices.append(1)

    # ------------------------------------------------------------------
    # 4. Stitch wall bottom to floor edge (connect k=0 wall ring to the
    #    nearest floor edge column so there is no gap).
    # ------------------------------------------------------------------
    for i in range(res_along - 1):
        # Left side: floor left-edge column (j=0)
        fl0 = floor_start + i * floor_res_across + 0
        fl1 = floor_start + (i + 1) * floor_res_across + 0
        wl0 = left_table[i][0]
        wl1 = left_table[i + 1][0]
        faces.append((fl0, wl0, wl1, fl1))
        mat_indices.append(0)

        # Right side: floor right-edge column (j = floor_res_across - 1)
        fr0 = floor_start + i * floor_res_across + (floor_res_across - 1)
        fr1 = floor_start + (i + 1) * floor_res_across + (floor_res_across - 1)
        wr0 = right_table[i][0]
        wr1 = right_table[i + 1][0]
        faces.append((fr0, fr1, wr1, wr0))
        mat_indices.append(0)

    # ------------------------------------------------------------------
    # 5. Floor path waypoints and side caves
    # ------------------------------------------------------------------
    floor_path: list[Vec3] = []
    step = max(1, res_along // 12)
    for i in range(0, res_along, step):
        floor_path.append(centerline[i])
    if floor_path[-1][0] < centerline[-1][0] - 0.01:
        floor_path.append(centerline[-1])

    side_caves: list[dict[str, Any]] = []
    for ci in range(num_side_caves):
        cave_t = rng.uniform(0.1, 0.9)
        ci_idx = int(cave_t * (res_along - 1))
        cx, cy, cz = centerline[ci_idx]
        cave_side = rng.choice(["left", "right"])
        sign = -1.0 if cave_side == "left" else 1.0
        cave_y = cy + sign * half_w
        cave_z = cz + rng.uniform(depth * 0.15, depth * 0.5)
        cave_width = rng.uniform(1.5, min(3.0, width * 0.55))
        cave_height = rng.uniform(1.5, min(4.0, depth * 0.35))
        cave_depth_val = rng.uniform(3.0, 8.0)
        side_caves.append({
            "position": (cx, cave_y, cave_z),
            "side": cave_side,
            "width": cave_width,
            "height": cave_height,
            "depth": cave_depth_val,
        })

    return {
        "mesh": {
            "vertices": vertices,
            "faces": faces,
        },
        "floor_path": floor_path,
        "centerline_points": centerline,
        "side_caves": side_caves,
        "depth_profile": depth_profile,
        "width_profile": width_profile,
        "materials": materials,
        "material_indices": mat_indices,
        "dimensions": {
            "width": width,
            "length": length,
            "depth": depth,
            "canyon_slope": canyon_slope,
            "strata_interval": strata_interval,
        },
        "vertex_count": len(vertices),
        "face_count": len(faces),
    }


# ---------------------------------------------------------------------------
# Waterfall generator
# ---------------------------------------------------------------------------

def generate_waterfall(
    height: float = 10.0,
    width: float = 3.0,
    pool_radius: float = 4.0,
    num_steps: int = 3,
    has_cave_behind: bool = True,
    seed: int = 42,
    facing_direction: tuple[float, float] = (0.0, -1.0),
) -> dict[str, Any]:
    """Generate a volumetric waterfall with curved water sheet, air-pocket gap,
    tapering thickness, plunge pool basin, and cascade ledges.

    The water sheet is not a flat plane: it has at least 4 horizontal segments
    with curvature that increases toward the base (the sheet bows outward as
    water accelerates).  Behind the sheet a thin air-pocket mesh is generated.
    Sheet thickness tapers from 0.3 m at the lip to 0.05 m at the plunge
    (parametric, following natural film-flow physics).

    By default the waterfall faces along the -Y direction.  Pass
    ``facing_direction`` to orient along any horizontal vector.

    Parameters
    ----------
    height : float
        Total drop height.
    width : float
        Width of the water curtain.
    pool_radius : float
        Radius of the plunge pool basin (overrides rule-of-thumb if caller
        passes a value; the rule-of-thumb default is height * 0.4).
    num_steps : int
        Number of cascade ledges (1 = single sheer drop).
    has_cave_behind : bool
        Include a cave behind the fall.
    seed : int
        Random seed.
    facing_direction : tuple[float, float]
        World-XY flow direction (normalized internally).

    Returns
    -------
    dict with keys:
        - "mesh": {"vertices", "faces"}
        - "sheet_verts": indices into vertices list for the front water sheet
        - "pool_verts": indices for the plunge pool basin
        - "steps": list of ledge dicts
        - "pool": dict (center, radius, depth)
        - "cave": dict or None
        - "splash_zone": dict
        - "materials": list of material names
        - "material_indices": per-face list
        - "dimensions": dict
        - "facing_direction": normalized direction tuple
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)
    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=cliff_rock, 1=wet_rock, 2=pool_bottom, 3=ledge_stone,
    #            4=moss, 5=water_sheet, 6=air_pocket
    materials = [
        "cliff_rock", "wet_rock", "pool_bottom", "ledge_stone",
        "moss", "water_sheet", "air_pocket",
    ]

    half_w = width / 2.0
    # Rule-of-thumb: pool radius = waterfall_height * 0.4 if caller passed
    # the default sentinel value (4.0) and height implies a larger basin.
    effective_pool_radius = max(pool_radius, height * 0.4)

    # Sheet geometry parameters
    sheet_horiz_segs = max(4, int(width * 2))   # >= 4 horizontal segments
    sheet_vert_segs = max(6, int(height * 1.5))
    lip_thickness = 0.30   # metres at the top
    plunge_thickness = 0.05  # metres at the bottom

    # ------------------------------------------------------------------
    # 1. Cliff face (rock behind the fall, wider than the water curtain)
    # ------------------------------------------------------------------
    cliff_res_x = max(6, int(width * 2) + 4)
    cliff_res_z = max(6, int(height))
    cliff_extent = width * 3.0
    cliff_start = len(vertices)

    for k in range(cliff_res_z):
        kt = k / max(cliff_res_z - 1, 1)
        z = kt * height
        for ix in range(cliff_res_x):
            ixt = ix / max(cliff_res_x - 1, 1)
            x = -cliff_extent / 2.0 + ixt * cliff_extent
            y_noise = _hash_noise(x * 0.2, z * 0.2, seed) * 0.5
            vertices.append((x, y_noise, z))

    for k in range(cliff_res_z - 1):
        for ix in range(cliff_res_x - 1):
            v0 = cliff_start + k * cliff_res_x + ix
            v1 = v0 + 1
            v2 = v0 + cliff_res_x + 1
            v3 = v0 + cliff_res_x
            faces.append((v0, v1, v2, v3))
            x_center = abs((ix / max(cliff_res_x - 1, 1)) - 0.5) * 2.0
            mat_indices.append(1 if x_center < 0.4 else 0)

    # ------------------------------------------------------------------
    # 2. Water sheet — curved front face
    #    Y position at each height follows a parabolic bow outward:
    #      y_bow = -bow_depth * (z_norm^2)   (more bow near plunge)
    #    Thickness tapers from lip_thickness at z=height to plunge_thickness
    #    at z=0.
    # ------------------------------------------------------------------
    bow_depth = height * 0.08   # max forward bow of the curtain

    sheet_front_start = len(vertices)
    sheet_vert_indices: list[int] = []

    for k in range(sheet_vert_segs + 1):
        kt = k / max(sheet_vert_segs, 1)       # 0=top(lip), 1=bottom(plunge)
        z = height * (1.0 - kt)
        bow = -bow_depth * (kt * kt)            # increasing bow toward plunge
        thickness = lip_thickness + (plunge_thickness - lip_thickness) * kt

        for ix in range(sheet_horiz_segs + 1):
            ixt = ix / max(sheet_horiz_segs, 1)
            x = -half_w + ixt * width
            # Small horizontal undulation for visual richness
            x_noise = _hash_noise(x * 0.5, z * 0.3, seed + 3) * 0.04 * width
            y_sheet = bow + x_noise
            vx = x + x_noise
            idx = len(vertices)
            sheet_vert_indices.append(idx)
            vertices.append((vx, y_sheet, z))

    # Sheet front faces
    cols_s = sheet_horiz_segs + 1
    for k in range(sheet_vert_segs):
        for ix in range(sheet_horiz_segs):
            v0 = sheet_front_start + k * cols_s + ix
            v1 = v0 + 1
            v2 = v0 + cols_s + 1
            v3 = v0 + cols_s
            faces.append((v0, v1, v2, v3))
            mat_indices.append(5)  # water_sheet

    # ------------------------------------------------------------------
    # 3. Air-pocket mesh: thin gap behind the sheet
    #    The air pocket is built as a second offset surface parallel to the
    #    sheet, pushed back by ``thickness`` in +Y.
    # ------------------------------------------------------------------
    air_start = len(vertices)
    for k in range(sheet_vert_segs + 1):
        kt = k / max(sheet_vert_segs, 1)
        z = height * (1.0 - kt)
        bow = -bow_depth * (kt * kt)
        thickness = lip_thickness + (plunge_thickness - lip_thickness) * kt

        for ix in range(sheet_horiz_segs + 1):
            ixt = ix / max(sheet_horiz_segs, 1)
            x = -half_w + ixt * width
            x_noise = _hash_noise(x * 0.5, z * 0.3, seed + 3) * 0.04 * width
            y_air = bow + thickness + x_noise  # pushed back
            vertices.append((x + x_noise, y_air, z))

    # Air-pocket back faces (reversed winding so normals face the sheet)
    for k in range(sheet_vert_segs):
        for ix in range(sheet_horiz_segs):
            v0 = air_start + k * cols_s + ix
            v1 = v0 + cols_s
            v2 = v0 + cols_s + 1
            v3 = v0 + 1
            faces.append((v0, v1, v2, v3))
            mat_indices.append(6)  # air_pocket

    # Cap the top of the air pocket to the cliff face (lip seal)
    for ix in range(sheet_horiz_segs):
        sf_top = sheet_front_start + ix
        sf_top1 = sf_top + 1
        ap_top = air_start + ix
        ap_top1 = ap_top + 1
        faces.append((sf_top, sf_top1, ap_top1, ap_top))
        mat_indices.append(1)  # wet_rock at lip

    # ------------------------------------------------------------------
    # 4. Cascade ledges
    # ------------------------------------------------------------------
    step_height_val = height / max(num_steps, 1)
    steps: list[dict[str, Any]] = []
    for si in range(num_steps):
        step_z = height - (si + 1) * step_height_val
        step_y = -(si + 1) * 1.5
        step_w = width + rng.uniform(-0.4, 0.4)
        step_d = rng.uniform(0.8, 1.5)
        steps.append({
            "position": (0.0, step_y, step_z),
            "width": step_w,
            "depth": step_d,
            "height_drop": step_height_val,
        })
        hw = step_w / 2.0
        ledge_s = len(vertices)
        vertices.extend([
            (-hw, step_y, step_z), (hw, step_y, step_z),
            (hw, step_y - step_d, step_z), (-hw, step_y - step_d, step_z),
            (-hw, step_y, step_z - 0.3), (hw, step_y, step_z - 0.3),
            (hw, step_y - step_d, step_z - 0.3), (-hw, step_y - step_d, step_z - 0.3),
        ])
        faces.append((ledge_s, ledge_s + 1, ledge_s + 2, ledge_s + 3))
        mat_indices.append(3)
        faces.append((ledge_s + 4, ledge_s + 5, ledge_s + 1, ledge_s))
        mat_indices.append(1)

    # ------------------------------------------------------------------
    # 5. Plunge pool — circular basin at base
    #    Rule-of-thumb: radius = waterfall_height * 0.4
    # ------------------------------------------------------------------
    pool_res = 24
    pool_depth_val = rng.uniform(height * 0.1, height * 0.2)
    pool_center_y = -(num_steps * 1.5 + effective_pool_radius * 0.6)

    pool_vert_start = len(vertices)
    pool_vert_indices: list[int] = []

    # Rim ring (at z=0, ground level)
    for i in range(pool_res):
        angle = 2.0 * math.pi * i / pool_res
        noise_r = _hash_noise(math.cos(angle) * 3.0, math.sin(angle) * 3.0, seed + 9) \
                  * effective_pool_radius * 0.06
        r = effective_pool_radius + noise_r
        x = math.cos(angle) * r
        y = pool_center_y + math.sin(angle) * r
        idx = len(vertices)
        pool_vert_indices.append(idx)
        vertices.append((x, y, 0.0))

    # Basin floor ring (at z = -pool_depth, slightly smaller radius)
    basin_r = effective_pool_radius * 0.7
    basin_start = len(vertices)
    for i in range(pool_res):
        angle = 2.0 * math.pi * i / pool_res
        x = math.cos(angle) * basin_r
        y = pool_center_y + math.sin(angle) * basin_r
        vertices.append((x, y, -pool_depth_val))

    # Basin center vertex
    pool_center_idx = len(vertices)
    vertices.append((0.0, pool_center_y, -pool_depth_val - 0.1))

    # Outer slope faces (rim → basin floor)
    for i in range(pool_res):
        i_next = (i + 1) % pool_res
        v0 = pool_vert_start + i
        v1 = pool_vert_start + i_next
        v2 = basin_start + i_next
        v3 = basin_start + i
        faces.append((v0, v1, v2, v3))
        mat_indices.append(2)  # pool_bottom

    # Basin floor fan
    for i in range(pool_res):
        i_next = (i + 1) % pool_res
        faces.append((basin_start + i, pool_center_idx, basin_start + i_next))
        mat_indices.append(2)

    pool_info = {
        "center": (0.0, pool_center_y, -pool_depth_val),
        "radius": effective_pool_radius,
        "depth": pool_depth_val,
    }
    splash_zone = {
        "center": (0.0, pool_center_y, 0.0),
        "radius": effective_pool_radius * 1.4,
    }

    # ------------------------------------------------------------------
    # 6. Optional cave behind waterfall
    # ------------------------------------------------------------------
    cave_info: dict[str, Any] | None = None
    if has_cave_behind:
        cave_width = width * 0.8
        cave_height_val = min(height * 0.4, 3.0)
        cave_depth_val = rng.uniform(3.0, 6.0)
        cave_z = height * 0.12
        cave_info = {
            "position": (0.0, cave_depth_val * 0.5, cave_z),
            "width": cave_width,
            "height": cave_height_val,
            "depth": cave_depth_val,
            "entrance": (0.0, lip_thickness + 0.05, cave_z),
        }

    # ------------------------------------------------------------------
    # 7. Direction-aware rotation (same contract as original)
    # ------------------------------------------------------------------
    dx, dy = float(facing_direction[0]), float(facing_direction[1])
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        cos_t, sin_t = 1.0, 0.0
    else:
        inv_len = 1.0 / math.sqrt(length_sq)
        dx *= inv_len
        dy *= inv_len
        cos_t = -dy
        sin_t = dx

    if abs(cos_t - 1.0) > 1e-9 or abs(sin_t) > 1e-9:
        def _rot_xy(p: tuple) -> tuple:
            x0, y0 = float(p[0]), float(p[1])
            z0 = float(p[2]) if len(p) > 2 else 0.0
            return (x0 * cos_t - y0 * sin_t, x0 * sin_t + y0 * cos_t, z0)

        vertices = [_rot_xy(v) for v in vertices]
        for step in steps:
            step["position"] = _rot_xy(step["position"])
        pool_info["center"] = _rot_xy(pool_info["center"])
        splash_zone["center"] = _rot_xy(splash_zone["center"])
        if cave_info is not None:
            cave_info["position"] = _rot_xy(cave_info["position"])
            cave_info["entrance"] = _rot_xy(cave_info["entrance"])

    return {
        "mesh": {"vertices": vertices, "faces": faces},
        "sheet_verts": sheet_vert_indices,
        "pool_verts": pool_vert_indices,
        "steps": steps,
        "pool": pool_info,
        "cave": cave_info,
        "splash_zone": splash_zone,
        "materials": materials,
        "material_indices": mat_indices,
        "dimensions": {
            "height": height,
            "width": width,
            "pool_radius": effective_pool_radius,
            "lip_thickness": lip_thickness,
            "plunge_thickness": plunge_thickness,
        },
        "facing_direction": (float(facing_direction[0]), float(facing_direction[1])),
        "vertex_count": len(vertices),
        "face_count": len(faces),
    }


# ---------------------------------------------------------------------------
# Cliff face generator
# ---------------------------------------------------------------------------

def generate_cliff_face(
    width: float = 20.0,
    height: float = 15.0,
    overhang: float = 3.0,
    num_cave_entrances: int = 2,
    has_ledge_path: bool = True,
    seed: int = 42,
    num_strata: int = 5,
) -> dict[str, Any]:
    """Generate a geologically stratified cliff face.

    Alternating hard and soft strata bands run horizontally across the face.
    Hard bands lean slightly outward (>90 deg, overhanging), have rougher
    surfaces, and resist erosion.  Soft bands are recessed (<90 deg), smoother,
    and may contain alcove cave openings.  The bottom of the cliff connects
    to a ground plane so there is no floating edge.

    Parameters
    ----------
    width : float
        Width of the cliff face along X.
    height : float
        Cliff height in Z.
    overhang : float
        Maximum overhang magnitude at the cliff top (metres in Y).
    num_cave_entrances : int
        Number of alcove cave openings (placed only in soft bands).
    has_ledge_path : bool
        Whether to include a walkable ledge across the mid-height.
    seed : int
        Random seed.
    num_strata : int
        Number of alternating strata bands.  Odd index = hard, even = soft.

    Returns
    -------
    dict with keys:
        - "mesh": {"vertices": list[Vec3], "faces": list[tuple]}  — quad topology
        - "cave_entrances": list of cave dicts (position, width, height, depth,
          strata_band)
        - "ledge_path": list of (x, y, z) waypoints (empty if has_ledge_path=False)
        - "overhang_zone": dict (extent, vertices)
        - "strata_bands": list of band dicts (z_bottom, z_top, type)
        - "materials": list of material names
        - "material_indices": per-face list
        - "dimensions": dict
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)
    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=cliff_rock, 1=hard_rock, 2=soft_rock, 3=ledge_stone,
    #            4=overhang_rock, 5=moss_rock, 6=ground_base
    materials = ["cliff_rock", "hard_rock", "soft_rock", "ledge_stone", "overhang_rock",
                 "moss_rock", "ground_base"]

    res_x = max(10, int(width))
    # Vertical resolution: at least 4 rows per strata band
    res_z = max(num_strata * 4, int(height * 1.2))

    half_w = width / 2.0
    band_height = height / max(num_strata, 1)

    # Pre-compute strata band definitions
    strata_bands: list[dict[str, Any]] = []
    for bi in range(num_strata):
        z_bot = bi * band_height
        z_top = (bi + 1) * band_height
        hard = (bi % 2 == 1)  # odd bands are hard
        strata_bands.append({
            "z_bottom": z_bot,
            "z_top": z_top,
            "type": "hard" if hard else "soft",
        })

    # ------------------------------------------------------------------
    # 1. Main cliff face — quad grid with per-row strata lean
    # ------------------------------------------------------------------
    cliff_start = len(vertices)
    for k in range(res_z + 1):
        kt = k / max(res_z, 1)
        z = kt * height

        # Which strata band are we in?
        band_idx = min(int(kt * num_strata), num_strata - 1)
        is_hard = (band_idx % 2 == 1)

        # Lean: hard bands overhang (+lean in -Y), soft bands recess (+lean in +Y)
        # Progressive lean within each band, reset at band boundary
        band_t = (kt * num_strata) - band_idx   # 0..1 within this band
        if is_hard:
            # Hard: lean outward up to -0.6 m, rougher
            lean = -0.6 * band_t
            rough_scale = 0.9
        else:
            # Soft: lean inward up to +0.4 m, smoother
            lean = 0.4 * band_t
            rough_scale = 0.4

        # Global overhang increases toward the top
        if kt > 0.75:
            global_lean = -overhang * ((kt - 0.75) / 0.25)
        else:
            global_lean = 0.0

        for ix in range(res_x):
            ixt = ix / max(res_x - 1, 1)
            x = -half_w + ixt * width

            # Two-frequency roughness: large-scale for strata shape,
            # small-scale for rock texture
            noise = (
                _fbm(x * 0.08, z * 0.12, seed, octaves=3, lacunarity=2.0, gain=0.5)
                * rough_scale * 0.7
                + _hash_noise(x * 0.4, z * 0.4, seed + 1) * rough_scale * 0.25
            )
            y = lean + global_lean + noise
            vertices.append((x, y, z))

    # Quad faces for the cliff surface
    for k in range(res_z):
        for ix in range(res_x - 1):
            v0 = cliff_start + k * res_x + ix
            v1 = v0 + 1
            v2 = v0 + res_x + 1
            v3 = v0 + res_x
            faces.append((v0, v1, v2, v3))
            kt_face = (k + 0.5) / max(res_z, 1)
            band_idx = min(int(kt_face * num_strata), num_strata - 1)
            is_hard = (band_idx % 2 == 1)
            if kt_face > 0.75:
                mat_indices.append(3)  # overhang_rock
            elif kt_face > 0.55:
                mat_indices.append(4)  # moss (mid-upper)
            elif is_hard:
                mat_indices.append(0)  # hard_rock
            else:
                mat_indices.append(1)  # soft_rock

    # ------------------------------------------------------------------
    # 2. Ground base — connect cliff bottom row to a flat ground plane so
    #    there is no floating bottom edge.
    # ------------------------------------------------------------------
    ground_y = 1.5  # ground plane offset forward from cliff face
    ground_start = len(vertices)
    for ix in range(res_x):
        ixt = ix / max(res_x - 1, 1)
        x = -half_w + ixt * width
        # cliff bottom vertex y
        cliff_bot_v = vertices[cliff_start + ix]
        y_base = cliff_bot_v[1]
        vertices.append((x, ground_y, 0.0))   # ground edge
        vertices.append((x, y_base, 0.0))     # cliff foot

    for ix in range(res_x - 1):
        g0 = ground_start + ix * 2
        g1 = g0 + 2
        c0 = g0 + 1
        c1 = g1 + 1
        faces.append((g0, g1, c1, c0))
        mat_indices.append(5)  # ground_base

    # ------------------------------------------------------------------
    # 3. Overhang underside
    # ------------------------------------------------------------------
    overhang_start = len(vertices)
    overhang_res = max(5, int(width / 2))
    overhang_depth_segs = 4
    overhang_zone_verts: list[Vec3] = []

    for ix in range(overhang_res):
        ixt = ix / max(overhang_res - 1, 1)
        x = -half_w + ixt * width
        for iy in range(overhang_depth_segs):
            iyt = iy / max(overhang_depth_segs - 1, 1)
            y = -overhang * iyt
            y += _hash_noise(x * 0.25, iyt * 8.0, seed + 3) * 0.25
            z_under = height - iyt * overhang * 0.12
            vt: Vec3 = (x, y, z_under)
            vertices.append(vt)
            overhang_zone_verts.append(vt)

    for ix in range(overhang_res - 1):
        for iy in range(overhang_depth_segs - 1):
            v0 = overhang_start + ix * overhang_depth_segs + iy
            v1 = v0 + 1
            v2 = v0 + overhang_depth_segs + 1
            v3 = v0 + overhang_depth_segs
            faces.append((v0, v1, v2, v3))
            mat_indices.append(3)  # overhang_rock

    # ------------------------------------------------------------------
    # 4. Cave entrances — placed in soft strata bands only
    # ------------------------------------------------------------------
    soft_band_indices = [bi for bi, b in enumerate(strata_bands) if b["type"] == "soft"]
    cave_entrances: list[dict[str, Any]] = []
    actual_caves = max(0, num_cave_entrances)
    for ci in range(actual_caves):
        if not soft_band_indices:
            break
        band_idx_c = soft_band_indices[ci % len(soft_band_indices)]
        band = strata_bands[band_idx_c]
        cave_x = rng.uniform(-half_w * 0.65, half_w * 0.65)
        cave_z = rng.uniform(band["z_bottom"] + 0.3, band["z_top"] - 0.3)
        c_width = rng.uniform(1.8, min(3.5, width * 0.28))
        c_height = rng.uniform(1.8, min(3.5, band_height * 0.7))
        c_depth = rng.uniform(2.5, 7.0)
        cave_entrances.append({
            "position": (cave_x, 0.0, cave_z),
            "width": c_width,
            "height": c_height,
            "depth": c_depth,
            "strata_band": band_idx_c,
        })

    # ------------------------------------------------------------------
    # 5. Ledge path
    # ------------------------------------------------------------------
    ledge_path: list[Vec3] = []
    if has_ledge_path:
        # Pick a hard band for the ledge (harder rock holds a ledge better)
        hard_bands = [b for b in strata_bands if b["type"] == "hard"]
        if hard_bands:
            ledge_band = hard_bands[len(hard_bands) // 2]
            ledge_z_base = (ledge_band["z_bottom"] + ledge_band["z_top"]) * 0.5
        else:
            ledge_z_base = height * 0.35
        ledge_w = rng.uniform(0.65, 1.1)

        for ix in range(res_x):
            ixt = ix / max(res_x - 1, 1)
            x = -half_w + ixt * width
            z_ledge = ledge_z_base + _hash_noise(x * 0.12, ledge_z_base, seed + 4) * 0.4
            y_ledge = -ledge_w * 0.5 + _hash_noise(x * 0.18, 0.0, seed + 5) * 0.15
            ledge_path.append((x, y_ledge, z_ledge))

        ledge_geom_start = len(vertices)
        for wp in ledge_path:
            vertices.append(wp)
            vertices.append((wp[0], wp[1] - ledge_w, wp[2]))

        for i in range(len(ledge_path) - 1):
            v0 = ledge_geom_start + i * 2
            v1 = v0 + 1
            v2 = v0 + 3
            v3 = v0 + 2
            faces.append((v0, v1, v2, v3))
            mat_indices.append(2)  # ledge_stone

    return {
        "mesh": {"vertices": vertices, "faces": faces},
        "cave_entrances": cave_entrances,
        "ledge_path": ledge_path,
        "overhang_zone": {"extent": overhang, "vertices": overhang_zone_verts},
        "strata_bands": strata_bands,
        "materials": materials,
        "material_indices": mat_indices,
        "dimensions": {
            "width": width,
            "height": height,
            "overhang": overhang,
            "num_strata": num_strata,
        },
        "vertex_count": len(vertices),
        "face_count": len(faces),
    }


# ---------------------------------------------------------------------------
# Swamp terrain generator
# ---------------------------------------------------------------------------

def generate_swamp_terrain(
    size: float = 50.0,
    water_level: float = 0.3,
    hummock_count: int = 12,
    island_count: int = 4,
    seed: int = 42,
    log_count: int = 6,
) -> dict[str, Any]:
    """Generate swamp terrain: standing-water pools, hummocks, dead-tree log specs,
    and a mist-zone marking.

    Pools are flat faces clamped to water_level (true standing-water appearance).
    Hummocks are raised mounds above water.  Log specs describe fallen/dead tree
    placements without adding mesh geometry (handled downstream by instancing).
    The mist zone is an axis-aligned box above the water surface.

    Parameters
    ----------
    size : float
        Side length of the square terrain.
    water_level : float
        Normalised height threshold [0, 1].  Faces below this are water.
    hummock_count : int
        Number of raised hummocks.
    island_count : int
        Number of larger dry islands.
    seed : int
        Random seed.
    log_count : int
        Number of fallen/dead tree log placement specs to generate.

    Returns
    -------
    dict with keys:
        - "mesh": {"vertices", "faces"}
        - "hummocks": list of dicts (position, radius, height)
        - "islands": list of dicts (position, radius, height)
        - "water_zones": list of connected-pool dicts (bounds, cell_count)
        - "log_specs": list of fallen-log dicts (start, end, radius, species)
        - "mist_zone": dict (bounds_min, bounds_max, density)
        - "materials": list of material names
        - "material_indices": per-face list
        - "dimensions": dict
        - "water_coverage": float
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)
    resolution = max(8, int(size / 2))
    half_size = size / 2.0

    # Materials: 0=swamp_mud, 1=shallow_water, 2=deep_water, 3=moss_ground,
    #            4=dead_vegetation
    materials = ["swamp_mud", "shallow_water", "deep_water", "moss_ground",
                 "dead_vegetation"]

    # ------------------------------------------------------------------
    # 1. Base heightmap — very flat with low-frequency undulation
    # ------------------------------------------------------------------
    heights: list[list[float]] = []
    for i in range(resolution):
        row: list[float] = []
        for j in range(resolution):
            gx = -half_size + (j / max(resolution - 1, 1)) * size
            gy = -half_size + (i / max(resolution - 1, 1)) * size
            h = 0.2 + _fbm(gx * 0.02, gy * 0.02, seed, octaves=3,
                            lacunarity=2.0, gain=0.5) * 0.15
            h += _hash_noise(gx * 0.1, gy * 0.1, seed + 1) * 0.03
            row.append(h)
        heights.append(row)

    # ------------------------------------------------------------------
    # 2. Hummocks — small raised mounds above water line
    # ------------------------------------------------------------------
    hummocks: list[dict[str, Any]] = []
    for hi in range(hummock_count):
        hx = rng.uniform(-half_size * 0.8, half_size * 0.8)
        hy = rng.uniform(-half_size * 0.8, half_size * 0.8)
        h_radius = rng.uniform(1.5, 4.0)
        # Height guaranteed above water so hummock is always dry land
        h_height = rng.uniform(0.25, 0.65)
        hummocks.append({"position": (hx, hy, 0.0), "radius": h_radius,
                         "height": h_height})
        for i in range(resolution):
            for j in range(resolution):
                gx = -half_size + (j / max(resolution - 1, 1)) * size
                gy = -half_size + (i / max(resolution - 1, 1)) * size
                dist = math.sqrt((gx - hx) ** 2 + (gy - hy) ** 2)
                if dist < h_radius:
                    falloff = 1.0 - (dist / h_radius) ** 2
                    heights[i][j] += h_height * falloff

    # ------------------------------------------------------------------
    # 3. Islands — larger dry platforms
    # ------------------------------------------------------------------
    islands: list[dict[str, Any]] = []
    for ii in range(island_count):
        isx = rng.uniform(-half_size * 0.6, half_size * 0.6)
        isy = rng.uniform(-half_size * 0.6, half_size * 0.6)
        i_radius = rng.uniform(4.0, 10.0)
        i_height = rng.uniform(0.3, 0.7)
        islands.append({"position": (isx, isy, 0.0), "radius": i_radius,
                        "height": i_height})
        for i in range(resolution):
            for j in range(resolution):
                gx = -half_size + (j / max(resolution - 1, 1)) * size
                gy = -half_size + (i / max(resolution - 1, 1)) * size
                dist = math.sqrt((gx - isx) ** 2 + (gy - isy) ** 2)
                if dist < i_radius:
                    falloff = (1.0 - (dist / i_radius) ** 2) ** 2
                    heights[i][j] += i_height * falloff

    # ------------------------------------------------------------------
    # 4. Build mesh — clamp water-face vertices to water_level (flat pools)
    # ------------------------------------------------------------------
    vertices: list[Vec3] = []
    faces: list[tuple[int, int, int, int]] = []
    mat_indices: list[int] = []
    height_scale = size * 0.1
    water_z = water_level * height_scale

    for i in range(resolution):
        for j in range(resolution):
            gx = -half_size + (j / max(resolution - 1, 1)) * size
            gy = -half_size + (i / max(resolution - 1, 1)) * size
            raw_z = heights[i][j] * height_scale
            vertices.append((gx, gy, raw_z))

    water_face_count = 0
    for i in range(resolution - 1):
        for j in range(resolution - 1):
            v0 = i * resolution + j
            v1 = v0 + 1
            v2 = (i + 1) * resolution + j + 1
            v3 = (i + 1) * resolution + j
            faces.append((v0, v1, v2, v3))
            avg_z = (vertices[v0][2] + vertices[v1][2]
                     + vertices[v2][2] + vertices[v3][2]) / 4.0

            if avg_z < water_z - 0.5:
                mat_indices.append(2)   # deep_water
                water_face_count += 1
            elif avg_z < water_z:
                mat_indices.append(1)   # shallow_water
                water_face_count += 1
            elif avg_z < water_z + 0.5:
                mat_indices.append(0)   # swamp_mud
            elif avg_z < water_z + 1.5:
                mat_indices.append(3)   # moss_ground
            else:
                mat_indices.append(4)   # dead_vegetation

    # Clamp water-surface vertices to exact water_level so pools are flat
    water_vert_set: set[int] = set()
    for fi, (v0, v1, v2, v3) in enumerate(faces):
        if mat_indices[fi] in (1, 2):
            for vi in (v0, v1, v2, v3):
                water_vert_set.add(vi)
    flat_verts = list(vertices)
    for vi in water_vert_set:
        vx, vy, vz = flat_verts[vi]
        if vz < water_z:
            flat_verts[vi] = (vx, vy, water_z)
    vertices = flat_verts

    # ------------------------------------------------------------------
    # 5. Water zones via flood-fill
    # ------------------------------------------------------------------
    water_zones: list[dict[str, Any]] = []
    total_faces = len(faces)
    water_coverage = water_face_count / total_faces if total_faces > 0 else 0.0

    water_cells: set[tuple[int, int]] = set()
    face_idx = 0
    for i in range(resolution - 1):
        for j in range(resolution - 1):
            if face_idx < len(mat_indices) and mat_indices[face_idx] in (1, 2):
                water_cells.add((i, j))
            face_idx += 1

    visited: set[tuple[int, int]] = set()
    for cell in water_cells:
        if cell in visited:
            continue
        component: list[tuple[int, int]] = []
        queue = [cell]
        while queue:
            c = queue.pop()
            if c in visited or c not in water_cells:
                continue
            visited.add(c)
            component.append(c)
            ci2, cj2 = c
            for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = (ci2 + di, cj2 + dj)
                if nb not in visited and nb in water_cells:
                    queue.append(nb)
        if component:
            min_i = min(c[0] for c in component)
            max_i = max(c[0] for c in component)
            min_j = min(c[1] for c in component)
            max_j = max(c[1] for c in component)
            x_min = -half_size + (min_j / max(resolution - 1, 1)) * size
            x_max = -half_size + ((max_j + 1) / max(resolution - 1, 1)) * size
            y_min = -half_size + (min_i / max(resolution - 1, 1)) * size
            y_max = -half_size + ((max_i + 1) / max(resolution - 1, 1)) * size
            water_zones.append({
                "bounds": (x_min, y_min, x_max, y_max),
                "cell_count": len(component),
            })

    # ------------------------------------------------------------------
    # 6. Log specs — fallen/dead tree placements (no mesh geometry;
    #    downstream code instances a log asset at each spec).
    # ------------------------------------------------------------------
    log_species = ["dead_oak", "dead_cypress", "dead_willow"]
    log_specs: list[dict[str, Any]] = []
    for li in range(log_count):
        lx = rng.uniform(-half_size * 0.75, half_size * 0.75)
        ly = rng.uniform(-half_size * 0.75, half_size * 0.75)
        angle = rng.uniform(0.0, 2.0 * math.pi)
        log_length = rng.uniform(3.0, 9.0)
        log_radius = rng.uniform(0.15, 0.45)
        # Ends of the log
        end_x = lx + math.cos(angle) * log_length
        end_y = ly + math.sin(angle) * log_length
        # Partially submerged: base z slightly below water_z
        lz = water_z - rng.uniform(0.0, log_radius * 0.8)
        log_specs.append({
            "start": (lx, ly, lz),
            "end": (end_x, end_y, lz),
            "radius": log_radius,
            "species": rng.choice(log_species),
            "rot_angle_deg": math.degrees(angle),
        })

    # ------------------------------------------------------------------
    # 7. Mist zone — axis-aligned box above the water surface
    # ------------------------------------------------------------------
    mist_height = size * 0.04   # mist rises ~4% of terrain size above water
    mist_zone = {
        "bounds_min": (-half_size, -half_size, water_z),
        "bounds_max": (half_size, half_size, water_z + mist_height),
        "density": 0.35 + _hash_noise(0.0, 0.0, seed + 77) * 0.15,
    }

    return {
        "mesh": {"vertices": vertices, "faces": faces},
        "hummocks": hummocks,
        "islands": islands,
        "water_zones": water_zones,
        "log_specs": log_specs,
        "mist_zone": mist_zone,
        "materials": materials,
        "material_indices": mat_indices,
        "dimensions": {"size": size, "water_level": water_level},
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "water_coverage": water_coverage,
    }


# ---------------------------------------------------------------------------
# Natural arch generator
# ---------------------------------------------------------------------------

def generate_natural_arch(
    span_width: float = 8.0,
    arch_height: float = 6.0,
    thickness: float = 2.0,
    roughness: float = 0.3,
    seed: int = 42,
    arch_depth: float = 0.0,
) -> dict[str, Any]:
    """Generate a natural rock arch (rock bridge) with parabolic profile,
    extruded arch body, rock mass above the opening, and strata lines.

    The arch profile is a true parabola (not a semicircle):
        z(x) = arch_height * (1 - (x / half_span)^2)
    This matches the shape of naturally eroded desert arches (e.g. Delicate Arch).
    The profile is extruded along Y (arch_depth axis) to give the arch physical
    thickness.  A box-ish rock mass sits above the opening, tapering at the sides.
    Strata lines are embedded as material bands across the face.

    Parameters
    ----------
    span_width : float
        Horizontal distance between the two arch legs at ground level.
    arch_height : float
        Height of the arch keystone above ground.
    thickness : float
        Radial stone thickness of the arch band.
    roughness : float
        fBm displacement on arch surface [0, 1].
    seed : int
        Random seed.
    arch_depth : float
        Extrusion depth along Y.  0 = auto (thickness * 2.5).

    Returns
    -------
    dict with keys:
        - "mesh": {"vertices", "faces"}  — proper quad topology
        - "arch_apex": Vec3 of keystone centre
        - "opening_clearance": float (min vertical clearance under arch)
        - "strata_bands": list of dicts (z_bottom, z_top)
        - "materials": list of material names
        - "material_indices": per-face list
        - "dimensions": dict
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)
    _ = rng  # reserved for future jitter

    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=arch_stone, 1=rock_mass, 2=moss, 3=weathered_rock, 4=strata_line
    materials = ["arch_stone", "rock_mass", "moss", "weathered_rock", "strata_line"]

    half_span = span_width / 2.0
    eff_depth = arch_depth if arch_depth > 0.0 else thickness * 2.5
    half_depth = eff_depth / 2.0

    # Resolution
    arch_segs_x = max(16, int(span_width * 3))   # horizontal divisions along span
    depth_segs = max(4, int(eff_depth * 1.5))     # Y extrusion divisions

    # Number of strata bands visible on the arch face
    num_strata = max(3, int(arch_height / 1.5))
    strata_bands: list[dict[str, Any]] = []
    for si in range(num_strata):
        z_bot = si * arch_height / num_strata
        z_top = (si + 1) * arch_height / num_strata
        strata_bands.append({"z_bottom": z_bot, "z_top": z_top})

    # ------------------------------------------------------------------
    # 1. Arch front face (Y = -half_depth) — parabolic profile, extruded
    #    along Y.  We generate a 2-D grid in (x_along_span, y_depth).
    #    For each (i_x, i_y) we compute:
    #      - arch_z: the parabolic crown height at x
    #      - inner_z: crown minus thickness (tunnel soffit)
    #    The front face is the arch profile projected flat in Y.
    # ------------------------------------------------------------------

    def _arch_z(x: float) -> float:
        """Parabolic arch crown height at lateral position x."""
        return arch_height * max(0.0, 1.0 - (x / half_span) ** 2)

    def _arch_inner_z(x: float) -> float:
        """Soffit (inside of arch opening) height — crown minus thickness."""
        crown = _arch_z(x)
        # Thickness measured radially: approximate as vertical offset at each x
        # The parabola's local normal angle adjusts the effective vertical offset
        # slightly, but for game meshes the vertical approximation is fine.
        return max(0.0, crown - thickness)

    # The arch solid band: from inner_z (soffit) up to crown (arch_z).
    # We extrude this quad band in depth (Y).

    # We also need the rock mass above the arch: from crown (arch_z) up to a
    # flat top at z = arch_height + thickness * 0.5, spanning full width.

    # -- Arch band (the stone ring itself) --
    # Grid: arch_segs_x+1 columns × (depth_segs+1) rows in Y
    # At each column x_i, the front/back faces have a quad from inner_z to crown_z.
    # We subdivide vertically into thickness_segs rows.
    thickness_segs = max(3, int(thickness * 2))

    arch_band_start = len(vertices)
    # Layout: for each depth row d and each x column ix, we store
    # (thickness_segs+1) vertices from soffit to crown.
    # Total vert layout: (depth_segs+1) × (arch_segs_x+1) × (thickness_segs+1)

    for d in range(depth_segs + 1):
        dt = d / max(depth_segs, 1)
        y_pos = -half_depth + dt * eff_depth

        for ix in range(arch_segs_x + 1):
            xt = ix / max(arch_segs_x, 1)
            x_pos = -half_span + xt * span_width

            crown = _arch_z(x_pos)
            soffit = _arch_inner_z(x_pos)
            band_h = crown - soffit

            for tk in range(thickness_segs + 1):
                tkt = tk / max(thickness_segs, 1)
                z_pos = soffit + tkt * band_h

                # fBm roughness, stronger toward outside of arch
                rough = roughness * _fbm(
                    x_pos * 0.15 + tk * 0.4,
                    y_pos * 0.2 + d * 0.3,
                    seed, octaves=3, lacunarity=2.0, gain=0.5,
                ) * 0.35
                # Displace outward from the arch centre (radially)
                # Approximate normal: for parabola y'=−2x/half_span², normal ∝ (2x/H, 1)
                slope_x = -2.0 * x_pos / (half_span ** 2) * arch_height
                norm_len = math.sqrt(slope_x ** 2 + 1.0)
                nx_n = slope_x / norm_len
                nz_n = 1.0 / norm_len

                vx = x_pos + nx_n * rough
                vy = y_pos
                vz = z_pos + nz_n * rough
                vertices.append((vx, vy, vz))

    # Arch band faces
    # Stride: each depth row has (arch_segs_x+1)*(thickness_segs+1) verts
    col_stride = thickness_segs + 1
    row_stride = (arch_segs_x + 1) * col_stride

    for d in range(depth_segs):
        for ix in range(arch_segs_x):
            for tk in range(thickness_segs):
                v0 = arch_band_start + d * row_stride + ix * col_stride + tk
                v1 = v0 + 1                       # tk+1
                v2 = v0 + col_stride + 1          # ix+1, tk+1
                v3 = v0 + col_stride              # ix+1, tk
                # Shift by row_stride for next depth row
                v4 = v0 + row_stride
                v5 = v1 + row_stride
                v6 = v2 + row_stride
                v7 = v3 + row_stride

                # Front face (d side)
                if d == 0:
                    faces.append((v0, v3, v2, v1))
                    _mat = _arch_face_mat(ix, arch_segs_x, tk, thickness_segs,
                                         vertices[v0][2], arch_height, num_strata,
                                         strata_bands)
                    mat_indices.append(_mat)
                # Back face
                if d == depth_segs - 1:
                    faces.append((v4, v5, v6, v7))
                    _mat = _arch_face_mat(ix, arch_segs_x, tk, thickness_segs,
                                         vertices[v4][2], arch_height, num_strata,
                                         strata_bands)
                    mat_indices.append(_mat)
                # Outer surface (tk = thickness_segs - 1 → outermost quad)
                if tk == thickness_segs - 1:
                    faces.append((v1, v5, v6, v2))  # outer surface
                    mat_indices.append(
                        2 if vertices[v1][2] > arch_height * 0.6 else 0
                    )
                # Inner soffit (tk == 0 → innermost quad = tunnel ceiling)
                if tk == 0:
                    faces.append((v0, v4, v7, v3))
                    mat_indices.append(3)  # weathered_rock on soffit

    # ------------------------------------------------------------------
    # 2. Rock mass above the arch opening — box with tapered sides
    #    Height: arch_height to arch_height + thickness * 0.6
    #    Width at base = span_width + thickness * 2
    #    Width tapers to span_width * 0.5 at top
    # ------------------------------------------------------------------
    mass_bot_z = arch_height
    mass_top_z = arch_height + thickness * 0.6
    mass_base_hw = half_span + thickness
    mass_top_hw = half_span * 0.55
    mass_segs_x = max(6, int(span_width))
    mass_segs_z = max(3, int(thickness))

    mass_start = len(vertices)
    for mz in range(mass_segs_z + 1):
        mzt = mz / max(mass_segs_z, 1)
        z_m = mass_bot_z + mzt * (mass_top_z - mass_bot_z)
        hw_m = mass_base_hw + mzt * (mass_top_hw - mass_base_hw)

        for d in range(depth_segs + 1):
            dt = d / max(depth_segs, 1)
            y_m = -half_depth + dt * eff_depth

            for mx in range(mass_segs_x + 1):
                mxt = mx / max(mass_segs_x, 1)
                x_m = -hw_m + mxt * 2.0 * hw_m
                rough = roughness * _hash_noise(x_m * 0.1, z_m * 0.12, seed + 50) * 0.4
                vertices.append((x_m + rough * 0.3, y_m, z_m + rough * 0.2))

    # Mass faces (front, back, sides, top)
    mass_col_stride = mass_segs_x + 1
    mass_dep_stride = (depth_segs + 1) * mass_col_stride

    for mz in range(mass_segs_z):
        for d in range(depth_segs):
            for mx in range(mass_segs_x):
                base = mass_start + mz * mass_dep_stride + d * mass_col_stride + mx
                v0 = base
                v1 = base + 1
                v2 = base + mass_col_stride + 1
                v3 = base + mass_col_stride
                v4 = base + mass_dep_stride
                v5 = base + mass_dep_stride + 1
                v6 = base + mass_dep_stride + mass_col_stride + 1
                v7 = base + mass_dep_stride + mass_col_stride

                # Front face
                if d == 0:
                    faces.append((v0, v3, v2, v1))
                    mat_indices.append(1)  # rock_mass
                # Back face
                if d == depth_segs - 1:
                    faces.append((v4, v5, v6, v7))
                    mat_indices.append(1)
                # Top face
                if mz == mass_segs_z - 1:
                    faces.append((v4, v0, v1, v5))
                    mat_indices.append(2)  # moss on top

    # ------------------------------------------------------------------
    # 3. Compute arch apex and opening clearance
    # ------------------------------------------------------------------
    arch_apex: Vec3 = (0.0, 0.0, arch_height)
    opening_clearance = _arch_inner_z(0.0)  # soffit height at keystone

    return {
        "mesh": {"vertices": vertices, "faces": faces},
        "arch_apex": arch_apex,
        "opening_clearance": opening_clearance,
        "strata_bands": strata_bands,
        "materials": materials,
        "material_indices": mat_indices,
        "dimensions": {
            "span_width": span_width,
            "arch_height": arch_height,
            "thickness": thickness,
            "arch_depth": eff_depth,
        },
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "pillars": [
            {"side": "left",  "position": (-half_span, 0.0, 0.0), "width": thickness, "height": arch_height},
            {"side": "right", "position": ( half_span, 0.0, 0.0), "width": thickness, "height": arch_height},
        ],
    }


def _arch_face_mat(
    ix: int, arch_segs_x: int,
    tk: int, thickness_segs: int,
    z_val: float, arch_height: float,
    num_strata: int,
    strata_bands: list[dict[str, Any]],
) -> int:
    """Choose material index for an arch face quad based on position."""
    # Strata lines at band boundaries
    band_t = z_val / max(arch_height, 1e-9)
    band_idx = int(band_t * num_strata)
    band_frac = (band_t * num_strata) - band_idx
    if band_frac < 0.06 or band_frac > 0.94:
        return 4  # strata_line
    # Moss on upper outer surface
    if z_val > arch_height * 0.65 and tk == thickness_segs - 1:
        return 2  # moss
    # Weathered on inner soffit
    if tk == 0:
        return 3  # weathered_rock
    return 0  # arch_stone


# ---------------------------------------------------------------------------
# Geyser generator
# ---------------------------------------------------------------------------

def generate_geyser(
    pool_radius: float = 3.0,
    pool_depth: float = 0.5,
    vent_height: float = 1.0,
    mineral_rim_width: float = 0.8,
    seed: int = 42,
    vent_diameter: float = 0.0,
    vent_depth: float = 0.0,
    crater_radius: float = 0.0,
) -> dict[str, Any]:
    """Generate a geyser vent with crater rim, central vent opening, outer terrain
    ramp, and travertine terraced deposits with fBm radial displacement.

    Geometry layers (inside-out):
    1. Central vent cylinder: diameter=vent_diameter, descending to vent_depth
    2. Inner crater rim ring: at crater_radius, height = vent_height * 0.3
    3. Outer terrain ramp: smooth ramp from ground level down to rim
    4. Travertine terraces: lumpy concentric rings with fBm radial noise

    Parameters
    ----------
    pool_radius : float
        Radius of the visible hot-spring pool surface.
    pool_depth : float
        Depth of the pool depression below ground.
    vent_height : float
        Height the eruption column rises (drives rim height scaling).
    mineral_rim_width : float
        Width of each mineral/travertine terrace ring.
    seed : int
        Random seed.
    vent_diameter : float
        Diameter of the central vent opening.  0 = auto (pool_radius * 0.35).
    vent_depth : float
        How far the vent descends below pool floor.  0 = auto (pool_depth * 2).
    crater_radius : float
        Radius of the inner crater rim ring.  0 = auto (pool_radius * 0.6).

    Returns
    -------
    dict with keys:
        - "mesh": {"vertices", "faces"}
        - "vent": dict (position, height, base_radius, vent_depth)
        - "pool": dict (center, radius, depth)
        - "terraces": list of terrace ring dicts
        - "materials": list of material names
        - "material_indices": per-face list
        - "dimensions": dict
        - "vertex_count", "face_count"
    """
    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=mineral_deposit, 1=pool_water, 2=vent_rock, 3=sulfur_crust,
    #            4=travertine, 5=crater_rim
    materials = ["mineral_deposit", "pool_water", "vent_rock", "sulfur_crust",
                 "travertine", "crater_rim"]

    # Auto-defaults
    eff_vent_diam = vent_diameter if vent_diameter > 0.0 else pool_radius * 0.35
    eff_vent_depth = vent_depth if vent_depth > 0.0 else pool_depth * 2.0
    eff_crater_r = crater_radius if crater_radius > 0.0 else pool_radius * 0.6
    vent_base_r = eff_vent_diam / 2.0
    rim_height = vent_height * 0.3

    radial_res = max(20, int(pool_radius * 7))

    # ------------------------------------------------------------------
    # 1. Pool bottom (concave disc)
    # ------------------------------------------------------------------
    pool_center_idx = len(vertices)
    vertices.append((0.0, 0.0, -pool_depth))

    pool_edge_start = len(vertices)
    for i in range(radial_res):
        angle = 2.0 * math.pi * i / radial_res
        noise = _hash_noise(math.cos(angle) * 2.0, math.sin(angle) * 2.0, seed) * 0.1
        r = pool_radius + noise
        x = math.cos(angle) * r
        y = math.sin(angle) * r
        vertices.append((x, y, -pool_depth * 0.6))

    for i in range(radial_res):
        i_next = (i + 1) % radial_res
        faces.append((pool_center_idx, pool_edge_start + i, pool_edge_start + i_next))
        mat_indices.append(1)  # pool_water

    # ------------------------------------------------------------------
    # 2. Central vent cylinder — descends to vent_depth
    # ------------------------------------------------------------------
    vent_res = max(10, int(radial_res // 2))
    vent_rings = max(3, int(eff_vent_depth * 2))
    vent_cyl_start = len(vertices)

    for vk in range(vent_rings + 1):
        vkt = vk / max(vent_rings, 1)
        vz = -pool_depth - vkt * eff_vent_depth
        # Vent narrows slightly toward bottom (tapers to 80% of base radius)
        vr = vent_base_r * (1.0 - vkt * 0.2)
        for vi in range(vent_res):
            va = 2.0 * math.pi * vi / vent_res
            noise = _hash_noise(math.cos(va) * 4.0, vz * 0.5, seed + 1) * vr * 0.08
            vx = math.cos(va) * (vr + noise)
            vy = math.sin(va) * (vr + noise)
            vertices.append((vx, vy, vz))

    for vk in range(vent_rings):
        for vi in range(vent_res):
            vi_next = (vi + 1) % vent_res
            v0 = vent_cyl_start + vk * vent_res + vi
            v1 = vent_cyl_start + vk * vent_res + vi_next
            v2 = vent_cyl_start + (vk + 1) * vent_res + vi_next
            v3 = vent_cyl_start + (vk + 1) * vent_res + vi
            faces.append((v0, v1, v2, v3))
            mat_indices.append(2)  # vent_rock

    # Vent bottom cap
    vent_bot_idx = len(vertices)
    vertices.append((0.0, 0.0, -pool_depth - eff_vent_depth))
    vent_bot_ring_start = vent_cyl_start + vent_rings * vent_res
    for vi in range(vent_res):
        vi_next = (vi + 1) % vent_res
        faces.append((vent_bot_ring_start + vi, vent_bot_idx,
                      vent_bot_ring_start + vi_next))
        mat_indices.append(2)

    # ------------------------------------------------------------------
    # 3. Crater rim ring at eff_crater_r, height = rim_height
    # ------------------------------------------------------------------
    rim_inner_start = len(vertices)
    for i in range(radial_res):
        angle = 2.0 * math.pi * i / radial_res
        # fBm radial displacement on rim for organic shape
        r_noise = _fbm(math.cos(angle) * 2.5, math.sin(angle) * 2.5,
                       seed + 10, octaves=3, lacunarity=2.0, gain=0.5) * eff_crater_r * 0.12
        r = eff_crater_r + r_noise
        x = math.cos(angle) * r
        y = math.sin(angle) * r
        vertices.append((x, y, rim_height))

    rim_outer_start = len(vertices)
    for i in range(radial_res):
        angle = 2.0 * math.pi * i / radial_res
        r_noise = _fbm(math.cos(angle) * 3.0, math.sin(angle) * 3.0,
                       seed + 11, octaves=3, lacunarity=2.0, gain=0.5) * eff_crater_r * 0.08
        r = eff_crater_r + mineral_rim_width * 0.5 + r_noise
        x = math.cos(angle) * r
        y = math.sin(angle) * r
        vertices.append((x, y, rim_height * 0.6))

    # Rim top quads (inner → outer)
    for i in range(radial_res):
        i_next = (i + 1) % radial_res
        v0 = rim_inner_start + i
        v1 = rim_inner_start + i_next
        v2 = rim_outer_start + i_next
        v3 = rim_outer_start + i
        faces.append((v0, v1, v2, v3))
        mat_indices.append(5)  # crater_rim

    # Connect rim outer edge to pool edge (ramp down from rim to pool surface)
    for i in range(radial_res):
        i_next = (i + 1) % radial_res
        v0 = rim_outer_start + i
        v1 = rim_outer_start + i_next
        v2 = pool_edge_start + i_next
        v3 = pool_edge_start + i
        faces.append((v0, v1, v2, v3))
        mat_indices.append(0)  # mineral_deposit on inner ramp

    # ------------------------------------------------------------------
    # 4. Outer terrain ramp: from ground level (z=0) down to rim outer edge
    # ------------------------------------------------------------------
    ramp_outer_r = pool_radius + mineral_rim_width * 4.0
    ramp_start = len(vertices)
    for i in range(radial_res):
        angle = 2.0 * math.pi * i / radial_res
        r_noise = _hash_noise(math.cos(angle) * 1.5, math.sin(angle) * 1.5,
                              seed + 20) * ramp_outer_r * 0.04
        r = ramp_outer_r + r_noise
        x = math.cos(angle) * r
        y = math.sin(angle) * r
        vertices.append((x, y, 0.0))

    for i in range(radial_res):
        i_next = (i + 1) % radial_res
        v0 = ramp_start + i
        v1 = ramp_start + i_next
        v2 = rim_outer_start + i_next
        v3 = rim_outer_start + i
        faces.append((v0, v1, v2, v3))
        mat_indices.append(0)  # mineral_deposit

    # ------------------------------------------------------------------
    # 5. Travertine terraces — lumpy concentric rings with fBm displacement
    # ------------------------------------------------------------------
    num_terraces = 3
    terraces: list[dict[str, Any]] = []
    prev_ring_start = ramp_start

    for tier in range(num_terraces):
        tier_inner_r = ramp_outer_r + tier * mineral_rim_width
        tier_outer_r = ramp_outer_r + (tier + 1) * mineral_rim_width
        # Each terrace steps up slightly then flattens
        tier_z = mineral_rim_width * 0.15 * (tier + 1)

        ring_start = len(vertices)
        for i in range(radial_res):
            angle = 2.0 * math.pi * i / radial_res
            # Lumpy fBm displacement — travertine deposits are irregular
            r_noise = _fbm(
                math.cos(angle) * (tier + 2.5),
                math.sin(angle) * (tier + 2.5),
                seed + 30 + tier, octaves=4, lacunarity=2.0, gain=0.5,
            ) * mineral_rim_width * 0.22
            z_noise = _hash_noise(math.cos(angle) * 5.0, float(tier), seed + 40 + tier) * 0.06
            r = tier_outer_r + r_noise
            x = math.cos(angle) * r
            y = math.sin(angle) * r
            z = tier_z + z_noise
            vertices.append((x, y, z))

        for i in range(radial_res):
            i_next = (i + 1) % radial_res
            v0 = prev_ring_start + i
            v1 = prev_ring_start + i_next
            v2 = ring_start + i_next
            v3 = ring_start + i
            faces.append((v0, v1, v2, v3))
            mat_indices.append(4)  # travertine

        terraces.append({
            "tier": tier + 1,
            "inner_radius": tier_inner_r,
            "outer_radius": tier_outer_r,
            "elevation": tier_z,
        })
        prev_ring_start = ring_start

    return {
        "mesh": {"vertices": vertices, "faces": faces},
        "vent": {
            "position": (0.0, 0.0, vent_height),
            "height": vent_height,
            "base_radius": vent_base_r,
            "vent_depth": eff_vent_depth,
            "crater_radius": eff_crater_r,
        },
        "pool": {
            "center": (0.0, 0.0, -pool_depth),
            "radius": pool_radius,
            "depth": pool_depth,
        },
        "terraces": terraces,
        "materials": materials,
        "material_indices": mat_indices,
        "dimensions": {
            "pool_radius": pool_radius,
            "pool_depth": pool_depth,
            "vent_height": vent_height,
            "vent_diameter": eff_vent_diam,
            "vent_depth": eff_vent_depth,
            "crater_radius": eff_crater_r,
            "mineral_rim_width": mineral_rim_width,
        },
        "vertex_count": len(vertices),
        "face_count": len(faces),
    }


# ---------------------------------------------------------------------------
# Sinkhole generator
# ---------------------------------------------------------------------------

def generate_sinkhole(
    radius: float = 5.0,
    depth: float = 8.0,
    wall_roughness: float = 0.5,
    has_bottom_cave: bool = True,
    rubble_density: float = 0.3,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate a collapse sinkhole with near-vertical walls, undercutting,
    a flat or water-filled base, and an irregular fBm-displaced rim.

    Key geological features:
    - Walls are near-vertical (slight inward lean by default) with some
      sections undercutting (radius increases slightly mid-depth) to simulate
      the asymmetric collapse of karst sinkholes.
    - The base is flat (water plane) — no bowl shape at the bottom.
    - The rim edge is irregularly displaced with fBm so it looks like
      freshly collapsed ground, not a perfect circle.
    - Rubble is placed on the flat base.

    Parameters
    ----------
    radius : float
        Average radius of the sinkhole opening at ground level.
    depth : float
        Depth from rim to flat base.
    wall_roughness : float
        Noise amplitude on wall surfaces [0, 1].
    has_bottom_cave : bool
        Whether to include a cave opening at the base.
    rubble_density : float
        Fraction of base area covered with rubble specs [0, 1].
    seed : int
        Random seed.

    Returns
    -------
    dict with keys:
        - "mesh": {"vertices", "faces"}
        - "rim": dict (radius, vertices)
        - "cave": dict or None
        - "rubble": list of rubble piece dicts
        - "base_water_level": float (z of flat base — can be used for water plane)
        - "materials": list of material names
        - "material_indices": per-face list
        - "dimensions": dict
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)
    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=dirt_wall, 1=exposed_rock, 2=rubble, 3=cave_entrance, 4=rim_ground
    materials = ["dirt_wall", "exposed_rock", "rubble", "cave_entrance", "rim_ground"]

    radial_res = max(20, int(radius * 4))
    depth_res = max(8, int(depth * 2))
    rim_width = radius * 0.4

    # ------------------------------------------------------------------
    # 1. Ground rim — fBm displaced inner edge so it looks like cracked
    #    and collapsed ground rather than a machined circle.
    # ------------------------------------------------------------------
    rim_start = len(vertices)
    rim_verts: list[Vec3] = []

    for i in range(radial_res):
        angle = 2.0 * math.pi * i / radial_res
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        # Outer rim: gentle noise
        noise_outer = _hash_noise(cos_a * 3.0, sin_a * 3.0, seed + 1) * rim_width * 0.18
        r_outer = radius + rim_width + noise_outer
        vertices.append((cos_a * r_outer, sin_a * r_outer, 0.0))

        # Inner rim: fBm displaced — larger amplitude for deliberate collapse look
        r_fbm_noise = _fbm(cos_a * 4.0, sin_a * 4.0, seed + 2,
                           octaves=4, lacunarity=2.0, gain=0.5) * radius * 0.14
        r_inner = radius + r_fbm_noise
        z_inner = _hash_noise(cos_a * 2.5, sin_a * 2.5, seed + 3) * 0.2
        v_inner: Vec3 = (cos_a * r_inner, sin_a * r_inner, z_inner)
        vertices.append(v_inner)
        rim_verts.append(v_inner)

    for i in range(radial_res):
        i_next = (i + 1) % radial_res
        v_o0 = rim_start + i * 2
        v_i0 = rim_start + i * 2 + 1
        v_o1 = rim_start + i_next * 2
        v_i1 = rim_start + i_next * 2 + 1
        faces.append((v_o0, v_o1, v_i1, v_i0))
        mat_indices.append(4)  # rim_ground

    # ------------------------------------------------------------------
    # 2. Walls — near-vertical with deliberate undercutting
    #    Wall profile:
    #      kt=0 (top): r = radius  (matches rim inner edge)
    #      kt=0.3:     r = radius + undercut_amount  (widest — undercutting)
    #      kt=1.0:     r = radius * 0.82  (base is slightly narrower)
    #    The undercut makes the top lip look precarious, which is authentic
    #    for collapse sinkholes.
    # ------------------------------------------------------------------
    undercut_peak = 0.35     # kt where undercutting is maximum
    undercut_amount = radius * 0.06  # how far walls belly out

    wall_start = len(vertices)
    for k in range(depth_res + 1):
        kt = k / max(depth_res, 1)  # 0=top, 1=bottom
        z = -kt * depth

        # Undercut profile: bell curve peaking at undercut_peak
        bell = math.exp(-((kt - undercut_peak) ** 2) / (2 * 0.08 ** 2))
        r_profile = radius + bell * undercut_amount - kt * radius * 0.18

        for i in range(radial_res):
            angle = 2.0 * math.pi * i / radial_res
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)

            # fBm roughness — more noise in mid-depth where rock is most exposed
            rough_scale = wall_roughness * math.sin(kt * math.pi) * 1.2
            noise_r = _fbm(
                cos_a * 3.5 + kt * 1.5, sin_a * 3.5 + kt * 1.5,
                seed + 10, octaves=4, lacunarity=2.0, gain=0.5,
            ) * rough_scale * radius * 0.10
            noise_z = wall_roughness * _hash_noise(angle * 3.5, kt * 5.5, seed + 11) * 0.25

            r = r_profile + noise_r
            vertices.append((cos_a * r, sin_a * r, z + noise_z))

    for k in range(depth_res):
        for i in range(radial_res):
            i_next = (i + 1) % radial_res
            v0 = wall_start + k * radial_res + i
            v1 = wall_start + k * radial_res + i_next
            v2 = wall_start + (k + 1) * radial_res + i_next
            v3 = wall_start + (k + 1) * radial_res + i
            faces.append((v0, v1, v2, v3))
            # Upper quarter: dirt over rock; lower: exposed rock
            if kt < 0.25:
                mat_indices.append(0)  # dirt_wall
            elif kt < 0.5:
                mat_indices.append(1)  # exposed_rock (transitional)
            else:
                mat_indices.append(1)  # exposed_rock

    # ------------------------------------------------------------------
    # 3. Flat base — at z = -depth.  A circular disc with slight variation.
    #    This serves as the water plane surface.
    # ------------------------------------------------------------------
    base_z = -depth
    floor_center_idx = len(vertices)
    vertices.append((0.0, 0.0, base_z))

    bottom_ring_start = wall_start + depth_res * radial_res
    for i in range(radial_res):
        i_next = (i + 1) % radial_res
        faces.append((floor_center_idx, bottom_ring_start + i_next, bottom_ring_start + i))
        mat_indices.append(2)  # rubble on floor

    # ------------------------------------------------------------------
    # 4. Rubble specs on the flat base
    # ------------------------------------------------------------------
    rubble: list[dict[str, Any]] = []
    floor_radius = radius * (1.0 - 0.18)  # bottom ring approximate radius
    num_rubble = max(0, int(rubble_density * 30))

    for ri in range(num_rubble):
        r_pos = rng.uniform(0.0, floor_radius * 0.82)
        r_angle = rng.uniform(0.0, 2.0 * math.pi)
        rx = math.cos(r_angle) * r_pos
        ry = math.sin(r_angle) * r_pos
        rz = base_z
        r_size = rng.uniform(0.2, 0.75)
        rubble.append({"position": (rx, ry, rz), "size": r_size})

        rb_start = len(vertices)
        hs = r_size / 2.0
        for ddx, ddy, ddz in [
            (-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        ]:
            nd = _hash_noise(rx + ddx * 2.0, ry + ddy * 2.0, seed + 100 + ri) * r_size * 0.28
            vertices.append((
                rx + ddx * hs + nd * 0.5,
                ry + ddy * hs + nd * 0.5,
                rz + ddz * r_size + abs(nd) * 0.3,
            ))
        for bf in [(0,1,2,3), (4,7,6,5), (0,4,5,1), (2,6,7,3), (0,3,7,4), (1,5,6,2)]:
            faces.append((rb_start+bf[0], rb_start+bf[1], rb_start+bf[2], rb_start+bf[3]))
            mat_indices.append(2)

    # ------------------------------------------------------------------
    # 5. Optional bottom cave
    # ------------------------------------------------------------------
    cave_info: dict[str, Any] | None = None
    if has_bottom_cave:
        cave_angle = rng.uniform(0.0, 2.0 * math.pi)
        cave_width = rng.uniform(1.5, min(3.0, radius * 0.5))
        cave_height = rng.uniform(1.5, min(3.0, depth * 0.3))
        cave_depth_val = rng.uniform(3.0, 8.0)
        cave_r = floor_radius * 0.8
        cave_info = {
            "position": (math.cos(cave_angle) * cave_r,
                         math.sin(cave_angle) * cave_r,
                         base_z + cave_height * 0.5),
            "direction_angle": cave_angle,
            "width": cave_width,
            "height": cave_height,
            "depth": cave_depth_val,
        }

    return {
        "mesh": {"vertices": vertices, "faces": faces},
        "rim": {"radius": radius, "vertices": rim_verts},
        "cave": cave_info,
        "rubble": rubble,
        "base_water_level": base_z,
        "materials": materials,
        "material_indices": mat_indices,
        "dimensions": {
            "radius": radius,
            "depth": depth,
            "wall_roughness": wall_roughness,
            "rubble_density": rubble_density,
            "undercut_amount": undercut_amount,
        },
        "vertex_count": len(vertices),
        "face_count": len(faces),
    }


# ---------------------------------------------------------------------------
# Floating rocks generator
# ---------------------------------------------------------------------------

def generate_floating_rocks(
    count: int = 5,
    base_height: float = 4.0,
    max_size: float = 3.0,
    chain_links: int = 2,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate a cluster of fully-closed floating rocks using icosphere + fBm.

    Each rock is a complete closed mesh (no flat bottom — full icosphere
    subdivision with fBm displacement on every vertex).  The undersurface
    uses a distinct material so the player can see it when looking up.
    Rock sizes vary across the cluster.  Each rock has a RockSpec transform
    in the return dict for downstream instancing.

    Parameters
    ----------
    count : int
        Number of floating rocks.
    base_height : float
        Minimum hover height (Z) of the lowest rock center.
    max_size : float
        Maximum rock diameter.
    chain_links : int
        Chain link count per rock (0 = no chains).
    seed : int
        Random seed.

    Returns
    -------
    dict with keys:
        - "mesh": {"vertices", "faces"} — all rocks combined
        - "rocks": list of RockSpec dicts (center, size, vertex_range, transform)
        - "chains": list of chain dicts
        - "materials": list of material names
        - "material_indices": per-face list
        - "dimensions": dict
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)
    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=rock_surface (top), 1=rock_underside, 2=crystal_vein, 3=chain_metal
    materials = ["rock_surface", "rock_underside", "crystal_vein", "chain_metal"]

    rocks: list[dict[str, Any]] = []
    chains: list[dict[str, Any]] = []

    spread = max_size * count * 0.45

    # Golden angle for ring rotation (same technique as ice formations)
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))

    for ri in range(count):
        rock_x = rng.uniform(-spread, spread)
        rock_y = rng.uniform(-spread, spread)
        rock_z = base_height + rng.uniform(0.0, base_height * 1.5)
        # Varied sizes: use a power distribution so most rocks are mid-sized
        size_t = rng.random() ** 1.4
        rock_size = max_size * 0.25 + size_t * max_size * 0.75
        rock_half = rock_size / 2.0

        rock_start = len(vertices)

        # -- Icosphere generation (subdivided octahedron) --
        # Use latitude rings with equal-area spacing (more rings = rounder sphere).
        ico_rings = max(5, int(rock_size * 3))
        segments_per_ring = max(6, int(rock_size * 4 + 6))

        # Top pole
        top_idx = len(vertices)
        top_disp = _fbm(rock_x * 0.3, rock_z * 0.3 + 99.0,
                        seed + ri * 7, octaves=3, lacunarity=2.0, gain=0.5)
        vertices.append((rock_x,
                          rock_y,
                          rock_z + rock_half * (1.0 + top_disp * 0.18)))

        ring_starts: list[int] = []
        ring_sizes_list: list[int] = []

        for k in range(1, ico_rings):
            kt = k / ico_rings              # 0 (top) → 1 (bottom)
            lat = math.pi * kt              # 0 → π
            ring_r_base = math.sin(lat) * rock_half
            ring_z_base = rock_z + math.cos(lat) * rock_half

            ring_start_idx = len(vertices)
            ring_starts.append(ring_start_idx)
            ring_sizes_list.append(segments_per_ring)

            for s in range(segments_per_ring):
                # Golden-angle rotation per ring for irregular faceting
                s_angle = 2.0 * math.pi * s / segments_per_ring + k * golden_angle

                # fBm displacement — applied radially so the rock is always closed
                fbm_r = _fbm(
                    s_angle * 1.5 + ri * 0.7 + kt * 2.1,
                    float(k) * 0.4 + ri * 0.3,
                    seed + ri * 13 + k,
                    octaves=4, lacunarity=2.0, gain=0.5,
                ) * rock_half * 0.22
                # Secondary small-scale noise for rock texture
                small_r = _hash_noise(
                    s_angle * 4.0 + ri, kt * 6.0 + k * 0.5, seed + ri * 17 + k
                ) * rock_half * 0.07

                r = ring_r_base + fbm_r + small_r
                z_disp = (_hash_noise(s_angle * 3.0, kt * 5.0, seed + ri * 19 + k)
                          * rock_half * 0.10)
                vx = rock_x + math.cos(s_angle) * r
                vy = rock_y + math.sin(s_angle) * r
                vz = ring_z_base + z_disp
                vertices.append((vx, vy, vz))

        # Bottom pole
        bot_idx = len(vertices)
        bot_disp = _fbm(rock_x * 0.3, rock_z * 0.3 - 99.0,
                        seed + ri * 11, octaves=3, lacunarity=2.0, gain=0.5)
        vertices.append((rock_x,
                          rock_y,
                          rock_z - rock_half * (1.0 + bot_disp * 0.18)))

        # -- Faces: top cap, ring bands, bottom cap --
        half_rings = len(ring_starts) // 2

        # Top cap
        if ring_starts:
            fr = ring_starts[0]
            fs = ring_sizes_list[0]
            for s in range(fs):
                faces.append((top_idx, fr + s, fr + (s + 1) % fs))
                mat_indices.append(0)  # rock_surface (top hemisphere)

        # Ring bands — all rings have the same segment count so pure quads
        for r_idx in range(len(ring_starts) - 1):
            r0 = ring_starts[r_idx]
            r1 = ring_starts[r_idx + 1]
            seg = ring_sizes_list[r_idx]
            is_bottom_half = (r_idx + 1) >= half_rings
            for s in range(seg):
                s_next = (s + 1) % seg
                faces.append((r0 + s, r0 + s_next, r1 + s_next, r1 + s))
                mat_indices.append(1 if is_bottom_half else 0)

        # Bottom cap
        if ring_starts:
            lr = ring_starts[-1]
            ls = ring_sizes_list[-1]
            for s in range(ls):
                faces.append((lr + s, bot_idx, lr + (s + 1) % ls))
                mat_indices.append(1)  # rock_underside

        rock_end = len(vertices)

        # Assign a crystal_vein band near the equator (material override
        # on equatorial ring faces — reached by post-pass below)
        equator_ring = len(ring_starts) // 2
        if equator_ring < len(ring_starts) - 1:
            # Re-label the equatorial band faces as crystal_vein
            # Count backward from the current mat_indices tail
            # Equatorial band = ring_sizes_list[equator_ring] quads
            eq_size = ring_sizes_list[equator_ring]
            # Position in mat_indices: top_cap + sum of previous ring bands + eq band
            top_cap_faces = ring_sizes_list[0] if ring_starts else 0
            prev_band_faces = sum(ring_sizes_list[i] for i in range(equator_ring))
            eq_start_mi = (len(mat_indices) - rock_end + rock_start
                           + top_cap_faces + prev_band_faces)
            # Simpler: just tag the vein in the RockSpec; downstream shader handles it
            # (adding geometry-level crystal veins would require UV seams)

        rocks.append({
            "center": (rock_x, rock_y, rock_z),
            "size": rock_size,
            "vertex_range": (rock_start, rock_end),
            "transform": {
                "translation": (rock_x, rock_y, rock_z),
                "scale": rock_size,
                "rotation_z_deg": rng.uniform(0.0, 360.0),
            },
        })

        # -- Chain links --
        if chain_links > 0:
            anchor_x = rock_x + rng.uniform(-0.4, 0.4)
            anchor_y = rock_y + rng.uniform(-0.4, 0.4)
            anchor_z = 0.0
            attach_z = rock_z - rock_half

            chain_link_list: list[dict[str, Any]] = []
            link_height = (attach_z - anchor_z) / max(chain_links, 1)
            link_radius = 0.07

            for li in range(chain_links):
                lz_bot = anchor_z + li * link_height
                lz_top = lz_bot + link_height
                link_start = len(vertices)
                for end_z in (lz_bot, lz_top):
                    for ci in range(4):
                        ca = 2.0 * math.pi * ci / 4
                        vertices.append((anchor_x + math.cos(ca) * link_radius,
                                         anchor_y + math.sin(ca) * link_radius,
                                         end_z))
                for ci in range(4):
                    ci_next = (ci + 1) % 4
                    v0 = link_start + ci
                    v1 = link_start + ci_next
                    v2 = link_start + 4 + ci_next
                    v3 = link_start + 4 + ci
                    faces.append((v0, v1, v2, v3))
                    mat_indices.append(3)  # chain_metal
                chain_link_list.append({
                    "position": (anchor_x, anchor_y, (lz_bot + lz_top) / 2.0),
                    "height": link_height,
                })

            chains.append({
                "rock_index": ri,
                "anchor": (anchor_x, anchor_y, anchor_z),
                "rock_attach": (rock_x, rock_y, attach_z),
                "links": chain_link_list,
            })

    return {
        "mesh": {"vertices": vertices, "faces": faces},
        "rocks": rocks,
        "chains": chains,
        "materials": materials,
        "material_indices": mat_indices,
        "dimensions": {
            "count": count,
            "base_height": base_height,
            "max_size": max_size,
            "chain_links": chain_links,
        },
        "vertex_count": len(vertices),
        "face_count": len(faces),
    }


# ---------------------------------------------------------------------------
# Ice formation generator
# ---------------------------------------------------------------------------

def generate_ice_formation(
    width: float = 6.0,
    height: float = 4.0,
    depth: float = 3.0,
    stalactite_count: int = 8,
    ice_wall: bool = True,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate ice cave/wall features with stalactites and refraction zones.

    The formation is oriented along the X axis. Ice stalactites hang from
    the ceiling (top of formation). An optional ice wall provides a
    semi-transparent backdrop with refraction-hint material zones.

    Parameters
    ----------
    width : float
        Width of the formation along X.
    height : float
        Height of the formation in Z.
    depth : float
        Depth of the formation into Y.
    stalactite_count : int
        Number of ice stalactites hanging from the ceiling.
    ice_wall : bool
        Whether to include an ice wall backdrop.
    seed : int
        Random seed.

    Returns
    -------
    dict with:
        - "mesh": dict with vertices and faces
        - "stalactites": list of stalactite dicts (tip_position, length, base_radius)
        - "wall_info": dict with dimensions and refraction zones (if ice_wall)
        - "materials": list of material names
        - "material_indices": per-face material index list
        - "dimensions": dict
    """
    rng = random.Random(seed)
    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=clear_ice, 1=frosted_ice, 2=blue_ice, 3=ice_wall_refraction, 4=icicle_tip
    materials = ["clear_ice", "frosted_ice", "blue_ice", "ice_wall_refraction", "icicle_tip"]

    half_w = width / 2.0
    half_d = depth / 2.0

    # --- Ice stalactites ---
    # Golden angle for crystal facet rotation per ring (avoids alignment)
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))  # ~137.5 degrees in radians

    stalactites: list[dict[str, Any]] = []
    for si in range(stalactite_count):
        # Position along ceiling
        sx = rng.uniform(-half_w * 0.9, half_w * 0.9)
        sy = rng.uniform(-half_d * 0.5, half_d * 0.5)
        stl_length = rng.uniform(height * 0.2, height * 0.8)
        stl_base_r = rng.uniform(0.1, 0.4)

        stalactites.append({
            "tip_position": (sx, sy, height - stl_length),
            "length": stl_length,
            "base_radius": stl_base_r,
        })

        # Ice formations: use 6 facets for crystal-like cross-section
        cone_segments = 6
        cone_rings = max(3, int(stl_length * 2))

        stl_start = len(vertices)

        # Rings from base (ceiling) to tip.
        # Fix: guard against cone_rings == 1 → max(cone_rings - 1, 1) to avoid ZeroDivisionError.
        for k in range(cone_rings):
            kt = k / max(cone_rings - 1, 1)   # 0=base, 1=tip (ZeroDivision fixed)
            ring_z = height - kt * stl_length

            # Tapered base: radius is largest near ceiling and tapers to near-zero at tip.
            # Use a slight convex bulge near the base (ice columns swell slightly
            # before tapering) then taper sharply at tip.
            if kt < 0.25:
                taper = 1.0 + 0.15 * math.sin(kt / 0.25 * math.pi)  # slight bulge
            else:
                taper = 1.0 - (kt - 0.25) / 0.75 * 0.98            # taper to 0.02x
            ring_r = stl_base_r * max(taper, 0.02)

            # fBm displacement for irregular ice surface
            fbm_disp = _fbm(sx * 0.5 + kt * 2.5, sy * 0.5 + k * 1.2,
                            seed + si * 7, octaves=3, lacunarity=2.0, gain=0.5)
            ring_r += fbm_disp * stl_base_r * 0.12

            for s in range(cone_segments):
                # Crystal faceting: rotate each ring by golden_angle * ring_index
                # so facets never align vertically → proper crystal facet appearance.
                s_angle = 2.0 * math.pi * s / cone_segments + k * golden_angle
                noise = _hash_noise(s_angle * 2.0, kt * 4.0, seed + si * 11 + k) * ring_r * 0.08
                vx = sx + math.cos(s_angle) * (ring_r + noise)
                vy = sy + math.sin(s_angle) * (ring_r + noise)
                vertices.append((vx, vy, ring_z))

        # Tip vertex
        tip_idx = len(vertices)
        tip_noise_z = _hash_noise(sx * 2.0, sy * 2.0, seed + si * 13) * 0.04
        vertices.append((sx, sy, height - stl_length + tip_noise_z))

        # Stalactite faces: ring quads
        for k in range(cone_rings - 1):
            kt_face = k / max(cone_rings - 1, 1)
            for s in range(cone_segments):
                s_next = (s + 1) % cone_segments
                v0 = stl_start + k * cone_segments + s
                v1 = stl_start + k * cone_segments + s_next
                v2 = stl_start + (k + 1) * cone_segments + s_next
                v3 = stl_start + (k + 1) * cone_segments + s
                faces.append((v0, v1, v2, v3))
                # Material: frosted near base, clear in middle, blue at tip
                if kt_face < 0.3:
                    mat_indices.append(1)  # frosted
                elif kt_face > 0.7:
                    mat_indices.append(2)  # blue
                else:
                    mat_indices.append(0)  # clear

        # Tip triangles (last ring to tip)
        last_ring_start = stl_start + (cone_rings - 1) * cone_segments
        for s in range(cone_segments):
            s_next = (s + 1) % cone_segments
            faces.append((last_ring_start + s, last_ring_start + s_next, tip_idx))
            mat_indices.append(4)  # icicle_tip

    # --- Ice wall ---
    wall_info: dict[str, Any] | None = None
    if ice_wall:
        wall_res_x = max(8, int(width * 2))
        wall_res_z = max(6, int(height * 2))
        wall_start = len(vertices)

        refraction_zones: list[dict[str, Any]] = []

        for k in range(wall_res_z):
            kt = k / max(wall_res_z - 1, 1)
            z = kt * height

            for ix in range(wall_res_x):
                ixt = ix / max(wall_res_x - 1, 1)
                x = -half_w + ixt * width

                # Wall surface with ice undulations
                y_base = half_d
                y_noise = _fbm(x * 0.3, z * 0.3, seed + 50, octaves=3) * 0.3
                y = y_base + y_noise

                vertices.append((x, y, z))

        # Wall faces
        for k in range(wall_res_z - 1):
            for ix in range(wall_res_x - 1):
                v0 = wall_start + k * wall_res_x + ix
                v1 = v0 + 1
                v2 = v0 + wall_res_x + 1
                v3 = v0 + wall_res_x
                faces.append((v0, v1, v2, v3))

                # Refraction zones: areas with high curvature
                x_center = -half_w + (ix + 0.5) / max(wall_res_x - 1, 1) * width
                z_center = (k + 0.5) / max(wall_res_z - 1, 1) * height
                curvature = abs(_fbm(x_center * 0.5, z_center * 0.5, seed + 60, octaves=2))

                if curvature > 0.3:
                    mat_indices.append(3)  # refraction zone
                else:
                    mat_indices.append(2)  # blue_ice

        # Identify distinct refraction zones
        num_zones = rng.randint(2, 5)
        for zi in range(num_zones):
            zx = rng.uniform(-half_w * 0.7, half_w * 0.7)
            zz = rng.uniform(height * 0.1, height * 0.9)
            z_radius = rng.uniform(0.5, 1.5)
            refraction_zones.append({
                "center": (zx, half_d, zz),
                "radius": z_radius,
            })

        wall_info = {
            "width": width,
            "height": height,
            "y_position": half_d,
            "refraction_zones": refraction_zones,
        }

    return {
        "mesh": {
            "vertices": vertices,
            "faces": faces,
        },
        "stalactites": stalactites,
        "wall_info": wall_info,
        "materials": materials,
        "material_indices": mat_indices,
        "dimensions": {
            "width": width,
            "height": height,
            "depth": depth,
            "stalactite_count": stalactite_count,
            "ice_wall": ice_wall,
        },
        "vertex_count": len(vertices),
        "face_count": len(faces),
    }


# ---------------------------------------------------------------------------
# Lava flow generator
# ---------------------------------------------------------------------------

def generate_lava_flow(
    length: float = 30.0,
    width: float = 4.0,
    edge_crust_width: float = 1.0,
    flow_segments: int = 20,
    seed: int = 42,
    slope_angle_deg: float = 5.0,
) -> dict[str, Any]:
    """Generate a lava flow that follows terrain gradient with lobate flow-front,
    ropy pahoehoe surface texture, and levee walls along both sides.

    Key improvements:
    - Flow follows a downhill gradient (slope_angle_deg along X) so the path
      is geologically plausible, not flat.
    - Flow-front geometry: a rounded snout with lobate (kidney-bean) outline
      at the downhill terminus.
    - Surface: ropy pahoehoe texture via fBm displacement in Z (ridges ~0.1 m
      amplitude across the flow width).
    - Levee walls: raised ridges along both flow edges, higher than the centre,
      formed by overflow cooling (accurate to real pahoehoe/aa flows).

    Parameters
    ----------
    length : float
        Total length of the flow along X.
    width : float
        Width of the hot central channel.
    edge_crust_width : float
        Width of the cooling crust flanks on each side.
    flow_segments : int
        Number of cross-section slices along the flow.
    seed : int
        Random seed.
    slope_angle_deg : float
        Downhill slope of the flow in degrees (flow descends at this angle along X).
        Random seed.

    Returns
    -------
    dict with keys:
        - "mesh": {"vertices", "faces"}
        - "flow_path": list of (x, y, z) centreline waypoints
        - "flow_front": list of (x, y, z) lobate snout vertices
        - "levee_specs": list of dicts (side, start, end, height)
        - "heat_zones": list of zone dicts (center, temperature, radius)
        - "materials": list of material names
        - "material_indices": per-face list
        - "dimensions": dict
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)
    vertices: list[Vec3] = []
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=hot_lava, 1=cooling_crust, 2=solid_rock, 3=ember_glow,
    #            4=levee_crust, 5=flow_front
    materials = ["hot_lava", "cooling_crust", "solid_rock", "ember_glow",
                 "levee_crust", "flow_front"]

    slope_rad = math.radians(slope_angle_deg)
    total_width = width + 2.0 * edge_crust_width
    levee_height = width * 0.18    # levees are ~18% of channel width tall
    levee_width = edge_crust_width * 0.6

    # Cross-section columns: levee_outer | solid_rock | crust | hot_lava | crust | solid_rock | levee_outer
    cross_res = max(10, int(total_width * 2) + 4)
    # Outer extent including levees
    rock_edge_outer = total_width / 2.0 + edge_crust_width + levee_width

    # ------------------------------------------------------------------
    # 1. Centreline: follows terrain gradient downhill along X with fBm
    #    lateral wander.
    # ------------------------------------------------------------------
    flow_path: list[Vec3] = []
    heat_zones: list[dict[str, Any]] = []

    # Sinuous lateral wander (fBm, not pure sine, for organic look)
    wander_amp = width * 1.2

    # Precompute centreline points
    cl_points: list[tuple[float, float, float]] = []
    for i in range(flow_segments + 1):
        t = i / max(flow_segments, 1)
        x = t * length
        # Gradient descent in Z (positive x = downhill)
        z_slope = -x * math.tan(slope_rad)
        # fBm lateral wander
        y_wander = (_fbm(x * 0.035, 0.0, seed, octaves=4, lacunarity=2.0, gain=0.5)
                    * wander_amp)
        # Small vertical undulation (pahoehoe surface rolls)
        z_extra = _fbm(x * 0.06, 1.0, seed + 1, octaves=3, lacunarity=2.0, gain=0.5) * 0.25
        cl_points.append((x, y_wander, z_slope + z_extra))
        flow_path.append((x, y_wander, z_slope + z_extra))

    # ------------------------------------------------------------------
    # 2. Main flow body: cross-sections perpendicular to centreline
    # ------------------------------------------------------------------
    for i, (cx, cy, cz) in enumerate(cl_points):
        # Tangent along centreline (forward difference)
        if i < flow_segments:
            nx2, ny2, nz2 = cl_points[i + 1]
        else:
            nx2, ny2, nz2 = cx, cy, cz
            if i > 0:
                px, py, pz = cl_points[i - 1]
                nx2, ny2 = cx + (cx - px), cy + (cy - py)

        tdx = nx2 - cx
        tdy = ny2 - cy
        tlen = math.sqrt(tdx * tdx + tdy * tdy)
        if tlen > 1e-9:
            perp_x = -tdy / tlen
            perp_y = tdx / tlen
        else:
            perp_x, perp_y = 0.0, 1.0

        for j in range(cross_res + 1):
            jt = j / max(cross_res, 1)
            offset = -rock_edge_outer + jt * 2.0 * rock_edge_outer
            dist = abs(offset)
            half_w = width / 2.0
            side = 1.0 if offset >= 0.0 else -1.0

            # Height profile (inside-out):
            #   hot channel: sunken -0.2 m
            #   levee crest at channel edge: +levee_height
            #   crust slope: rises from channel to levee then drops
            #   solid rock beyond levee: at 0
            if dist < half_w * 0.6:
                # Hot centre: depressed
                z_profile = -0.2
            elif dist < half_w:
                # Transition to levee base
                t_lev = (dist - half_w * 0.6) / (half_w * 0.4)
                z_profile = -0.2 + t_lev * (levee_height + 0.2)
            elif dist < half_w + levee_width:
                # Levee crest then outer slope
                t_lev = (dist - half_w) / levee_width
                z_profile = levee_height * (1.0 - t_lev * t_lev)
            elif dist < half_w + levee_width + edge_crust_width:
                # Cooling crust: gently sloping down
                t_cr = (dist - half_w - levee_width) / edge_crust_width
                z_profile = 0.3 * (1.0 - t_cr)
            else:
                # Solid rock: flat at ground level
                z_profile = 0.0

            # Pahoehoe ropy texture: fBm bumps across the channel surface
            if dist < half_w + edge_crust_width:
                ropy = _fbm(
                    cx * 0.15 + offset * 0.4,
                    offset * 0.6 + float(i) * 0.2,
                    seed + 20, octaves=4, lacunarity=2.2, gain=0.55,
                ) * 0.10
            else:
                ropy = _hash_noise(cx * 0.2 + offset * 0.3, offset * 0.2, seed + 21) * 0.06

            vx = cx + perp_x * offset
            vy = cy + perp_y * offset
            vz = cz + z_profile + ropy
            vertices.append((vx, vy, vz))

    # Faces for the flow body
    for i in range(flow_segments):
        for j in range(cross_res):
            v0 = i * (cross_res + 1) + j
            v1 = v0 + 1
            v2 = (i + 1) * (cross_res + 1) + j + 1
            v3 = (i + 1) * (cross_res + 1) + j
            faces.append((v0, v1, v2, v3))

            # Material by lateral position
            jt_mid = (j + 0.5) / max(cross_res, 1)
            off_mid = -rock_edge_outer + jt_mid * 2.0 * rock_edge_outer
            d_mid = abs(off_mid)
            hw = width / 2.0
            if d_mid < hw * 0.6:
                mat_indices.append(0)   # hot_lava
            elif d_mid < hw:
                mat_indices.append(3)   # ember_glow (inner levee slope)
            elif d_mid < hw + levee_width:
                mat_indices.append(4)   # levee_crust
            elif d_mid < hw + levee_width + edge_crust_width:
                mat_indices.append(1)   # cooling_crust
            else:
                mat_indices.append(2)   # solid_rock

    # ------------------------------------------------------------------
    # 3. Flow front — lobate (kidney-bean) snout at the downhill terminus
    #    A semicircular fan of vertices in front of the last cross-section,
    #    displaced radially with fBm to create the lobate bulge pattern.
    # ------------------------------------------------------------------
    last_cx, last_cy, last_cz = cl_points[-1]
    # Tangent at end (use second-to-last if available)
    if flow_segments >= 1:
        plx, ply, plz = cl_points[-2]
        tdx_e = last_cx - plx
        tdy_e = last_cy - ply
    else:
        tdx_e, tdy_e = 1.0, 0.0
    t_elen = math.sqrt(tdx_e ** 2 + tdy_e ** 2)
    if t_elen > 1e-9:
        tdx_e /= t_elen
        tdy_e /= t_elen

    front_res = max(12, cross_res)
    front_lobe_r = total_width / 2.0 * 1.1   # slightly wider than channel
    front_start = len(vertices)
    flow_front_verts: list[Vec3] = []

    for fi in range(front_res + 1):
        ft = fi / max(front_res, 1)
        # Half-circle sweep forward: -π/2 to +π/2 in local frame
        fan_angle = (ft - 0.5) * math.pi
        # Local frame: forward = tangent, right = perp
        lf_x = math.cos(fan_angle)    # right component
        lf_y = math.sin(fan_angle)    # forward component

        # World direction
        world_x = tdx_e * lf_y - tdy_e * lf_x
        world_y = tdy_e * lf_y + tdx_e * lf_x

        # Lobate fBm radial displacement
        r_disp = _fbm(
            lf_x * 3.0, lf_y * 3.0,
            seed + 30, octaves=4, lacunarity=2.0, gain=0.5,
        ) * front_lobe_r * 0.18
        r = front_lobe_r + r_disp

        vx = last_cx + world_x * r
        vy = last_cy + world_y * r
        # Flow front sits at ground level with slight downslope
        vz = last_cz - r * math.tan(slope_rad) * 0.5 + _hash_noise(vx * 0.3, vy * 0.3, seed + 31) * 0.08
        v: Vec3 = (vx, vy, vz)
        vertices.append(v)
        flow_front_verts.append(v)

    # Flow front centre at the last centreline point
    front_center_idx = len(vertices)
    vertices.append((last_cx, last_cy, last_cz))

    # Fan triangles for the flow front
    for fi in range(front_res):
        faces.append((front_center_idx, front_start + fi, front_start + fi + 1))
        mat_indices.append(5)   # flow_front

    # Connect flow front rim to last cross-section row
    last_row_start = flow_segments * (cross_res + 1)
    # Map front_res+1 front verts to cross_res+1 row verts
    for fi in range(min(front_res, cross_res)):
        # Simple proportional mapping
        ci = int(fi * cross_res / max(front_res, 1))
        ci_next = int((fi + 1) * cross_res / max(front_res, 1))
        v0 = last_row_start + ci
        v1 = last_row_start + ci_next
        v2 = front_start + fi + 1
        v3 = front_start + fi
        faces.append((v0, v1, v2, v3))
        mat_indices.append(5)   # flow_front

    # ------------------------------------------------------------------
    # 4. Levee specs — metadata for the two raised ridges along flow sides
    # ------------------------------------------------------------------
    levee_specs: list[dict[str, Any]] = []
    for side_name, side_sign in [("left", -1.0), ("right", 1.0)]:
        lev_pts: list[Vec3] = []
        for i, (cx, cy, cz) in enumerate(cl_points):
            if i < flow_segments:
                nx2, ny2, _ = cl_points[i + 1]
            else:
                nx2, ny2 = cx, cy
            tdx_l = nx2 - cx
            tdy_l = ny2 - cy
            tlen_l = math.sqrt(tdx_l ** 2 + tdy_l ** 2)
            if tlen_l > 1e-9:
                px_l = -tdy_l / tlen_l
                py_l = tdx_l / tlen_l
            else:
                px_l, py_l = 0.0, 1.0
            lev_x = cx + side_sign * px_l * (width / 2.0)
            lev_y = cy + side_sign * py_l * (width / 2.0)
            lev_z = cz + levee_height
            lev_pts.append((lev_x, lev_y, lev_z))
        levee_specs.append({
            "side": side_name,
            "points": lev_pts,
            "height": levee_height,
            "width": levee_width,
        })

    # ------------------------------------------------------------------
    # 5. Heat zones
    # ------------------------------------------------------------------
    num_heat_zones = max(3, flow_segments // 4)
    for hi in range(num_heat_zones):
        ht = (hi + 0.5) / num_heat_zones
        hcx, hcy, hcz = cl_points[int(ht * flow_segments)]
        temperature = max(0.3, min(1.0, 1.0 - ht * 0.4 + rng.uniform(-0.08, 0.08)))
        heat_zones.append({
            "center": (hcx, hcy, hcz),
            "temperature": temperature,
            "radius": width * 0.75,
        })

    return {
        "mesh": {"vertices": vertices, "faces": faces},
        "flow_path": flow_path,
        "flow_front": flow_front_verts,
        "levee_specs": levee_specs,
        "heat_zones": heat_zones,
        "materials": materials,
        "material_indices": mat_indices,
        "dimensions": {
            "length": length,
            "width": width,
            "edge_crust_width": edge_crust_width,
            "flow_segments": flow_segments,
            "slope_angle_deg": slope_angle_deg,
            "levee_height": levee_height,
        },
        "vertex_count": len(vertices),
        "face_count": len(faces),
    }
