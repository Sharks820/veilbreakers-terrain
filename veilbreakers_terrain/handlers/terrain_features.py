"""Terrain feature generators -- pure logic, no bpy/bmesh.

Generates walkable terrain features (canyons, waterfalls, cliff faces, swamps,
natural arches, geysers, sinkholes, floating rocks, ice formations, lava flows)
as mesh specification dicts. Each function returns vertices, faces, materials,
and feature metadata.

All functions are pure and operate on plain Python data structures.
Fully testable without Blender.
"""

from __future__ import annotations

from functools import lru_cache
import math
import random
import time
from typing import Any

from ._terrain_noise import _make_noise_generator
from .terrain_semantics import BBox, PassDefinition, PassResult, TerrainPipelineState


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Vec3 = tuple[float, float, float]


# ---------------------------------------------------------------------------
# AAA geometry helpers
# ---------------------------------------------------------------------------

def _cross(a: Vec3, b: Vec3) -> Vec3:
    """3-D cross product."""
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _normalize(v: Vec3) -> Vec3:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    inv = 1.0 / length
    return (v[0] * inv, v[1] * inv, v[2] * inv)


def _face_normal(verts: list[Vec3], face: tuple[int, ...]) -> Vec3:
    """Newell's method face normal for a polygon (robust for quads and tris)."""
    n = (0.0, 0.0, 0.0)
    count = len(face)
    for i in range(count):
        vi = verts[face[i]]
        vj = verts[face[(i + 1) % count]]
        n = (
            n[0] + (vi[1] - vj[1]) * (vi[2] + vj[2]),
            n[1] + (vi[2] - vj[2]) * (vi[0] + vj[0]),
            n[2] + (vi[0] - vj[0]) * (vi[1] + vj[1]),
        )
    return _normalize(n)


def _compute_face_normals(verts: list[Vec3], faces: list[tuple[int, ...]]) -> list[Vec3]:
    """Compute one normal per face using Newell's method."""
    return [_face_normal(verts, f) for f in faces]


def _lod1_faces(faces: list[tuple[int, ...]], ratio: float = 0.5) -> list[tuple[int, ...]]:
    """Return a deterministic face-list simplification for LOD_1."""
    if not faces:
        return []
    if len(faces) <= 4:
        return list(faces)
    target = max(4, min(len(faces), int(round(len(faces) * ratio))))
    if target >= len(faces):
        return list(faces)
    step = len(faces) / float(target)
    return [faces[min(len(faces) - 1, int(i * step))] for i in range(target)]


def _material_metadata(*entries: tuple[str, float, str, float]) -> dict[str, dict]:
    """Build per-material AAA metadata dict.
    Each entry: (name, roughness_hint, layer_type, emission)
    """
    return {
        name: {"roughness_hint": rh, "layer_type": lt, "emission": em}
        for name, rh, lt, em in entries
    }


# ---------------------------------------------------------------------------
# Noise utility -- opensimplex via _terrain_noise (replaces old sin-hash)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _get_feature_noise(seed: int):
    """Return a cached per-seed terrain noise generator.

    The old module-global singleton was correct for serial callers but
    thrashed between alternating seeds and relied on mutable shared state.
    A per-seed cache keeps determinism while avoiding repeated generator
    construction in loop-heavy feature builders such as canyon, swamp, and
    lava flow generation.
    """
    return _make_noise_generator(int(seed))


def _hash_noise(x: float, y: float, seed: int = 0) -> float:
    """Wang-hash gradient noise via the project's opensimplex/perm-table backend.

    Uses _make_noise_generator so the noise type is consistent with every
    other call site in the codebase (opensimplex when available, permutation-
    table gradient fallback otherwise).  Replaces the old sin-hash that had
    visible directional banding.  Returns values in approximately [-1, 1].
    """
    return _get_feature_noise(int(seed)).noise2(x, y)


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
    if octaves <= 0:
        return 0.0
    # ``gain`` is the canonical parameter; accept ``persistence`` as alias.
    effective_gain = gain if gain != 0.5 or persistence == 0.5 else persistence
    gen = _get_feature_noise(int(seed))
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
    num_strata_types: int = 4,
    overhang_side: str = "left",
) -> dict[str, Any]:
    """Generate a geologically plausible canyon with winding centerline, slot-canyon
    cross-section, strata ledges, stitched wall-to-floor seams, a talus debris
    slope at the base, and a one-sided overhang cap.

    AAA upgrades over the B baseline:
    - **Layered strata geometry**: ``num_strata_types`` distinct rock bands, each
      with its own hardness, roughness, lateral lean, and material ID.  Hard bands
      (sandstone) protrude slightly outward; soft bands (mudstone) are recessed.
      This drives per-stratum material IDs rather than a single ``canyon_wall``
      material for the whole face.
    - **Talus slope mesh**: A separate wedge-shaped apron runs along the base of
      both walls.  The apron rises from the floor outward and slopes at a natural
      angle of repose (~32°).  Material = ``talus_debris``.
    - **One-sided overhang cap**: The ``overhang_side`` wall receives a thin cap
      geometry that leans over the canyon at the rim, creating the asymmetric
      overhang typical of differential erosion (softer rock undercut on one side).
      Material = ``overhang_cap``.
    - **Per-stratum UV set**: U coordinate on wall faces is remapped per stratum
      (0..1 within each band) so textures tile cleanly at band boundaries without
      UV stretching across the full wall height.

    The canyon runs roughly along the X axis with fBm lateral displacement on
    the centerline so the path meanders.  Cross-sections use a slot-canyon
    profile where the effective width narrows toward the bottom:

        width_at_depth = canyon_width * (1 - depth_fraction) ** carve_power

    where ``depth_fraction`` is 0 at the rim and 1 at the floor, and
    ``carve_power`` equals ``canyon_slope``.

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
        Exponent for the slot-canyon cross-section formula.
    strata_interval : float
        Vertical spacing (metres) between strata ledge cuts.
    num_strata_types : int
        Number of distinct rock strata bands (alternating hard/soft).  Each band
        gets its own material ID and lean angle.  Default 4.
    overhang_side : str
        Which wall receives the asymmetric overhang cap: "left", "right", or
        "none".  Default "left".

    Returns
    -------
    dict with keys:
        - "mesh": {"vertices": list[Vec3], "faces": list[tuple]}
        - "uvs": list of (u, v) per vertex
        - "floor_path": list of (x, y, z) waypoints along the canyon floor
        - "centerline_points": list of (x, y, z) winding centreline samples
        - "side_caves": list of cave dicts
        - "depth_profile": list of (x, depth_at_x) pairs
        - "width_profile": list of (x, width_at_x) pairs
        - "strata_bands": list of band dicts (z_bottom, z_top, type, lean, roughness_scale)
        - "talus_specs": list of talus apron metadata dicts
        - "materials": list of material zone names
        - "material_indices": list of per-face material indices
        - "dimensions": dict
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)

    # Resolution: enough segments to capture the winding and strata detail.
    res_along = max(8, int(length / 1.5))
    res_wall = max(8, int(depth / 1.0))   # vertical resolution on each wall face

    vertices: list[Vec3] = []
    uvs: list[tuple[float, float]] = []   # per-vertex (u, v) — V longitudinal
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=canyon_floor, 1=canyon_wall, 2=wet_rock, 3=canyon_ledge,
    #            4..4+n-1 = per-stratum rock IDs, then talus_debris, overhang_cap
    _n = max(2, num_strata_types)
    _strata_mat_names = [f"strata_{si}" for si in range(_n)]
    materials = (
        ["canyon_floor", "canyon_wall", "wet_rock", "canyon_ledge"]
        + _strata_mat_names
        + ["talus_debris", "overhang_cap"]
    )
    MAT_FLOOR    = 0
    MAT_WALL     = 1  # FIX-11-10: reserved for future wall-face material tagging
    MAT_WET      = 2
    MAT_LEDGE    = 3
    MAT_STRATA_0 = 4
    MAT_TALUS    = 4 + _n
    MAT_OVERHANG = 4 + _n + 1

    # ------------------------------------------------------------------
    # Pre-compute strata band definitions.
    # Alternating hard (sandstone-like) and soft (mudstone-like) bands.
    # Each band gets its own lean angle and roughness scale.
    # ------------------------------------------------------------------
    strata_bands_def: list[dict[str, Any]] = []
    band_height_m = depth / max(_n, 1)
    for bi in range(_n):
        z_bot = bi * band_height_m
        z_top = (bi + 1) * band_height_m
        is_hard = (bi % 2 == 0)
        # Hard bands lean outward slightly (protrude); soft bands recess
        lean_sign = -1.0 if is_hard else +1.0
        lean_mag = width * (0.04 if is_hard else 0.02)
        strata_bands_def.append({
            "z_bottom": z_bot,
            "z_top": z_top,
            "type": "hard" if is_hard else "soft",
            "lean": lean_sign * lean_mag,
            "roughness_scale": 1.0 if is_hard else 0.6,
            "mat_id": MAT_STRATA_0 + bi,
        })

    half_w = width / 2.0

    # ------------------------------------------------------------------
    # 1. Build winding centreline by displacing a straight line with fBm.
    #    Displacement is purely lateral (Y axis) so the canyon still runs
    #    end-to-end along X.  A sine meander offset is added on top of the
    #    fBm wander to produce a clear S-curve shape.
    # ------------------------------------------------------------------
    # Meander parameters used consistently across all geometry passes
    _meander_amp = half_w * 0.55
    _meander_freq = 2.5 * math.pi / max(length, 1.0)
    _seed_phase = (seed % 1000) * 0.006283

    centerline: list[Vec3] = []
    for i in range(res_along):
        t = i / max(res_along - 1, 1)
        x = t * length
        # fBm lateral wander — amplitude up to half of width so the walls
        # don't overlap.
        y_disp = _fbm(x * 0.04, 0.0, seed, octaves=4, lacunarity=2.0, gain=0.5) * half_w * 0.4
        # Sine meander on top of fBm
        y_disp += _meander_amp * math.sin(x * _meander_freq + _seed_phase)
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
    #
    #    Slot-canyon width formula applied here: at the floor (depth_fraction=1)
    #    the floor width = canyon_width * (1 - 1)^carve_power = 0 ideally, but
    #    we use a minimum floor_width = width * slot_floor_fraction so there is
    #    always walkable geometry at the base.
    # ------------------------------------------------------------------
    slot_floor_fraction = 0.15   # floor is 15% of mouth width at maximum carve
    floor_width = width * max(slot_floor_fraction,
                              (1.0 - 1.0) ** max(canyon_slope, 0.1))
    # Clamp: floor always at least slot_floor_fraction of mouth width
    floor_width = max(floor_width, width * slot_floor_fraction)
    floor_half_w = floor_width / 2.0

    floor_res_across = max(4, int(floor_width * 2) + 4)
    floor_start = len(vertices)

    for i in range(res_along):
        t_along = i / max(res_along - 1, 1)   # longitudinal UV: 0..1
        cx, cy, cz = centerline[i]
        for j in range(floor_res_across):
            jt = j / max(floor_res_across - 1, 1)
            # Floor spans ±floor_half_w around the winding centre
            local_y = cy + (-floor_half_w + jt * floor_width)
            # Very small height variation across the floor
            z_floor = cz + _hash_noise(cx * 0.08, local_y * 0.08, seed) * 0.2
            vertices.append((cx, local_y, z_floor))
            uvs.append((jt, t_along))

    for i in range(res_along - 1):
        for j in range(floor_res_across - 1):
            v0 = floor_start + i * floor_res_across + j
            v1 = v0 + 1
            v2 = v0 + floor_res_across + 1
            v3 = v0 + floor_res_across
            faces.append((v0, v1, v2, v3))
            mat_indices.append(0)  # canyon_floor

    # ------------------------------------------------------------------
    # 3. Wall geometry — slot-canyon cross-section for each side.
    #    The key formula controlling the slot shape is:
    #
    #      width_at_depth = canyon_width * (1 - depth_fraction) ** carve_power
    #
    #    where depth_fraction = kt (0=rim, 1=floor) and carve_power=canyon_slope.
    #    This narrows the canyon toward the bottom: at the rim (kt=0) the wall
    #    sits at half_w; at the floor (kt=1) the wall collapses to
    #    floor_half_w (the minimum walkable width set above).
    #
    #    Wall lateral position at depth fraction kt:
    #      slot_half_width = half_w * (1 - kt) ** canyon_slope
    #    clamped to floor_half_w so the wall never closes past the floor.
    #
    #    The sinusoidal meander offset (already encoded in the centreline) is
    #    re-applied here at full depth so the walls track the centreline wander.
    #    3-level strata banding shifts each third of the wall laterally to
    #    simulate tilted sediment layers.
    # ------------------------------------------------------------------
    # Per-stratum strata offsets (one per band, replaces old 3-level list)
    _strata_depth = width * 0.07
    _strata_offsets = [
        math.sin(bi * 2.3 + seed * 0.17) * _strata_depth
        for bi in range(_n)
    ]

    def _wall_verts_for_side(side: int) -> list[list[int]]:
        """Build wall vertices and return a 2-D index table [i][k] -> global idx."""
        sign = -1.0 if side == 0 else 1.0  # left = -1, right = +1
        idx_table: list[list[int]] = []

        for i in range(res_along):
            t_along = i / max(res_along - 1, 1)   # longitudinal UV V coord
            cx, cy, cz = centerline[i]
            row_indices: list[int] = []

            for k in range(res_wall + 1):
                kt = k / max(res_wall, 1)  # 0 = floor level, 1 = rim/top of wall
                z_wall = cz + kt * depth

                # Slot-canyon formula
                depth_frac = 1.0 - kt   # 1 at floor, 0 at rim
                slot_half = half_w * ((1.0 - depth_frac) ** max(canyon_slope, 0.1))
                slot_half = max(slot_half, floor_half_w)

                # Per-stratum lean: look up which strata band this height falls in
                band_idx_k = min(int(kt * _n), _n - 1)
                band_def = strata_bands_def[band_idx_k]
                band_rough_scale = band_def["roughness_scale"]
                band_lean = band_def["lean"]

                # fBm roughness scaled by band hardness
                rough_scale = wall_roughness * math.sin(kt * math.pi) * 1.5 * band_rough_scale
                rough = _fbm(cx * 0.12 + k * 0.3, float(i) * 0.1, seed + side * 7,
                             octaves=4, lacunarity=2.0, gain=0.5) * rough_scale

                # Per-stratum lateral shift (replaces old 3-level list)
                strata_x_shift = _strata_offsets[band_idx_k]

                y_pos = cy + sign * (slot_half + rough + abs(band_lean)) + strata_x_shift

                # Strata ledge: every strata_interval depth units cut a narrow shelf
                z_strata_phase = (z_wall - cz) % max(strata_interval, 0.1)
                ledge_window = strata_interval * 0.08
                if z_strata_phase < ledge_window and k > 0:
                    y_pos = cy + sign * (slot_half + rough - sign * 0.35) + strata_x_shift

                global_idx = len(vertices)
                vertices.append((cx, y_pos, z_wall))
                # UV: U=per-stratum normalised (0..1 within band), V=longitudinal
                band_t = (kt * _n) - band_idx_k   # 0..1 within band
                uvs.append((band_t, t_along))
                row_indices.append(global_idx)
            idx_table.append(row_indices)

        return idx_table

    left_table = _wall_verts_for_side(0)
    right_table = _wall_verts_for_side(1)

    def _wall_face_mat(k: int) -> int:
        """Return material index for a wall face quad at wall-row k."""
        z_frac = k / max(res_wall, 1)
        z_depth_m = z_frac * depth
        strata_phase = z_depth_m % max(strata_interval, 0.1)
        if strata_phase < strata_interval * 0.08:
            return MAT_LEDGE
        if k < res_wall // 5:
            return MAT_WET
        band_idx_k = min(int(z_frac * _n), _n - 1)
        return strata_bands_def[band_idx_k]["mat_id"]

    # Build wall faces for left side
    for i in range(res_along - 1):
        for k in range(res_wall):
            v0 = left_table[i][k]
            v1 = left_table[i][k + 1]
            v2 = left_table[i + 1][k + 1]
            v3 = left_table[i + 1][k]
            faces.append((v0, v1, v2, v3))
            mat_indices.append(_wall_face_mat(k))

    # Build wall faces for right side (reversed winding for outward normals)
    for i in range(res_along - 1):
        for k in range(res_wall):
            v0 = right_table[i][k]
            v1 = right_table[i + 1][k]
            v2 = right_table[i + 1][k + 1]
            v3 = right_table[i][k + 1]
            faces.append((v0, v1, v2, v3))
            mat_indices.append(_wall_face_mat(k))

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
        mat_indices.append(MAT_FLOOR)

        # Right side: floor right-edge column (j = floor_res_across - 1)
        fr0 = floor_start + i * floor_res_across + (floor_res_across - 1)
        fr1 = floor_start + (i + 1) * floor_res_across + (floor_res_across - 1)
        wr0 = right_table[i][0]
        wr1 = right_table[i + 1][0]
        faces.append((fr0, fr1, wr1, wr0))
        mat_indices.append(MAT_FLOOR)

    # ------------------------------------------------------------------
    # 4b. Talus slope aprons — one wedge along each wall base.
    #     Geometry: a strip that runs from the wall k=0 ring outward to
    #     floor_half_w * 0.5 at z = floor level, sloping at ~32° (natural
    #     angle of repose for loose rocky debris).
    #     This is pure extra geometry on top of the existing floor seam.
    # ------------------------------------------------------------------
    talus_width = floor_half_w * 0.9     # how far the talus extends inward from wall
    talus_res_w = max(3, int(talus_width * 2) + 2)
    talus_specs: list[dict[str, Any]] = []

    for side, side_sign, wall_table in [(0, -1.0, left_table), (1, 1.0, right_table)]:
        talus_start = len(vertices)
        for i in range(res_along):
            cx, cy, cz = centerline[i]
            t_along = i / max(res_along - 1, 1)
            # Wall base position (k=0 vertex)
            wall_base_v = vertices[wall_table[i][0]]
            wall_y = wall_base_v[1]
            wall_z = wall_base_v[2]
            for tw in range(talus_res_w + 1):
                tw_t = tw / max(talus_res_w, 1)   # 0 = at wall, 1 = inner edge
                # Y: moves inward from wall_y toward centreline
                ty = wall_y - side_sign * tw_t * talus_width
                # Z: rises slightly at the wall, flat at inner edge (angle of repose)
                # tan(32°) ≈ 0.625
                tz = wall_z + (1.0 - tw_t) * talus_width * 0.35
                # fBm height variation for rubble texture
                tz += _hash_noise(cx * 0.1, ty * 0.1, seed + 300 + side) * 0.15
                vertices.append((cx, ty, tz))
                uvs.append((tw_t, t_along))

        for i in range(res_along - 1):
            for tw in range(talus_res_w):
                v0 = talus_start + i * (talus_res_w + 1) + tw
                v1 = v0 + 1
                v2 = v0 + (talus_res_w + 1) + 1
                v3 = v0 + (talus_res_w + 1)
                if side == 0:
                    faces.append((v0, v1, v2, v3))
                else:
                    faces.append((v0, v3, v2, v1))
                mat_indices.append(MAT_TALUS)

        talus_specs.append({
            "side": "left" if side == 0 else "right",
            "width": talus_width,
            "angle_of_repose_deg": 32.0,
            "vertex_start": talus_start,
        })

    # ------------------------------------------------------------------
    # 4c. One-sided overhang cap — a thin sloping shelf at the rim of the
    #     designated overhang_side wall, leaning over the canyon interior.
    #     The cap is a narrow strip from the rim outward and inward,
    #     representing the harder caprock that resists undercutting.
    # ------------------------------------------------------------------
    if overhang_side in ("left", "right"):
        oh_table = left_table if overhang_side == "left" else right_table
        oh_sign  = -1.0    if overhang_side == "left" else 1.0
        cap_lean_dist = half_w * 0.20    # how far the cap overhangs inward
        cap_res_w = 3
        cap_thickness = depth * 0.04

        cap_start = len(vertices)
        for i in range(res_along):
            cx, cy, cz = centerline[i]
            t_along = i / max(res_along - 1, 1)
            # Rim vertex position (k = res_wall, topmost ring)
            rim_v = vertices[oh_table[i][res_wall]]
            rim_y = rim_v[1]
            rim_z = rim_v[2]
            for cw in range(cap_res_w + 1):
                cw_t = cw / max(cap_res_w, 1)   # 0 = outer rim edge, 1 = inner tip
                # Y: leans inward over canyon (toward centreline)
                cap_y = rim_y + oh_sign * cap_lean_dist * cw_t
                # Z: slopes slightly downward toward tip (gravity sag)
                cap_z = rim_z - cap_thickness * cw_t
                cap_z += _hash_noise(cx * 0.1, cap_y * 0.1, seed + 400) * 0.06
                vertices.append((cx, cap_y, cap_z))
                uvs.append((cw_t, t_along))

        for i in range(res_along - 1):
            for cw in range(cap_res_w):
                v0 = cap_start + i * (cap_res_w + 1) + cw
                v1 = v0 + 1
                v2 = v0 + (cap_res_w + 1) + 1
                v3 = v0 + (cap_res_w + 1)
                if overhang_side == "left":
                    faces.append((v0, v3, v2, v1))   # face inward
                else:
                    faces.append((v0, v1, v2, v3))
                mat_indices.append(MAT_OVERHANG)

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

    # Build per-strata material_metadata entries
    _strata_mm = []
    for bi, bd in enumerate(strata_bands_def):
        rh = 0.80 if bd["type"] == "hard" else 0.55
        lt = "sandstone" if bd["type"] == "hard" else "mudstone"
        _strata_mm.append((f"strata_{bi}", rh, lt, 0.0))

    _normals = _compute_face_normals(vertices, faces)
    return {
        "mesh": {
            "vertices": vertices,
            "faces": faces,
            "normals": _normals,
        },
        "uvs": uvs,
        "floor_path": floor_path,
        "centerline_points": centerline,
        "side_caves": side_caves,
        "depth_profile": depth_profile,
        "width_profile": width_profile,
        "strata_bands": strata_bands_def,
        "talus_specs": talus_specs,
        "materials": materials,
        "material_indices": mat_indices,
        "material_metadata": _material_metadata(
            ("canyon_floor",  0.85, "sediment",   0.0),
            ("canyon_wall",   0.80, "sandstone",  0.0),
            ("wet_rock",      0.60, "wet_stone",  0.0),
            ("canyon_ledge",  0.75, "hard_rock",  0.0),
            *_strata_mm,
            ("talus_debris",  0.90, "loose_rock", 0.0),
            ("overhang_cap",  0.78, "hard_rock",  0.0),
        ),
        "dimensions": {
            "width": width,
            "length": length,
            "depth": depth,
            "canyon_slope": canyon_slope,
            "strata_interval": strata_interval,
            "num_strata_types": _n,
            "overhang_side": overhang_side,
            "lod": {
                "LOD_0": len(faces),
                "LOD_1": _lod1_faces(faces),
            },
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
        - "uvs": per-vertex (u, v) — V coord runs 0 (top/lip) to 1 (plunge)
          so an animated texture scrolls downward with increasing V
        - "sheet_verts": indices into vertices list for the front water sheet
        - "pool_verts": indices for the plunge pool basin
        - "foam_verts": indices of the foam-zone vertices at the impact base
        - "spray_verts": indices of the side-spray plane vertices
        - "steps": list of ledge dicts
        - "pool": dict (center, radius, depth)
        - "cave": dict or None
        - "splash_zone": dict
        - "materials": list of material names (includes "white_foam" at index 7,
          "spray_mist" at index 8)
        - "material_indices": per-face list
        - "dimensions": dict
        - "facing_direction": normalized direction tuple
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)
    vertices: list[Vec3] = []
    uvs: list[tuple[float, float]] = []    # per-vertex (u, v)
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=cliff_rock, 1=wet_rock, 2=pool_bottom, 3=ledge_stone,
    #            4=moss, 5=water_sheet, 6=air_pocket, 7=white_foam, 8=spray_mist
    materials = [
        "cliff_rock", "wet_rock", "pool_bottom", "ledge_stone",
        "moss", "water_sheet", "air_pocket", "white_foam", "spray_mist",
    ]

    half_w = width / 2.0
    # Rule-of-thumb: pool radius = waterfall_height * 0.4 if caller passed
    # the default sentinel value (4.0) and height implies a larger basin.
    effective_pool_radius = max(pool_radius, height * 0.4)

    # Sheet geometry parameters
    sheet_horiz_segs = max(4, int(width * 2))   # >= 4 horizontal segments
    sheet_vert_segs = max(6, math.ceil(height * 48.0))  # 48 verts/m per WaterfallVolumetricProfile
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
            uvs.append((ixt, 1.0 - kt))   # V=0 at top, V=1 at bottom

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
    # 2. Water sheet — curved front face with gravity parabola bow.
    #
    #    Each cascade section uses the formula:
    #      bow_at_drop = bow_depth * 0.35 * sqrt(drop_frac)
    #    where drop_frac = fraction of the total drop completed (0=lip, 1=plunge).
    #    This mimics the real acceleration bow of a free-falling water curtain.
    #
    #    UV coords: U = horizontal position (0..1), V = 0 at lip → 1 at plunge.
    #    V flows downward so an animated scroll texture moves toward the pool.
    #    Thickness tapers from lip_thickness at z=height to plunge_thickness
    #    at z=0.
    # ------------------------------------------------------------------
    bow_depth = height * 0.08   # max forward bow of the curtain

    sheet_front_start = len(vertices)
    sheet_vert_indices: list[int] = []

    for k in range(sheet_vert_segs + 1):
        kt = k / max(sheet_vert_segs, 1)       # 0=top(lip), 1=bottom(plunge)
        drop_frac = kt                          # fraction of drop completed
        z = height * (1.0 - kt)
        # Gravity parabola bow: depth = bow_depth * 0.35 * sqrt(drop_frac)
        bow = -bow_depth * 0.35 * math.sqrt(max(drop_frac, 0.0))
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
            uvs.append((ixt, kt))   # V=0 at lip, V=1 at plunge (flows downward)

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
        drop_frac = kt
        z = height * (1.0 - kt)
        bow = -bow_depth * 0.35 * math.sqrt(max(drop_frac, 0.0))
        thickness = lip_thickness + (plunge_thickness - lip_thickness) * kt

        for ix in range(sheet_horiz_segs + 1):
            ixt = ix / max(sheet_horiz_segs, 1)
            x = -half_w + ixt * width
            x_noise = _hash_noise(x * 0.5, z * 0.3, seed + 3) * 0.04 * width
            y_air = bow + thickness + x_noise  # pushed back
            vertices.append((x + x_noise, y_air, z))
            uvs.append((ixt, kt))

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
    # 4. Cascade ledges — grid ledge tops and visible rock face below each drop.
    #
    #    Each ledge has:
    #      - A 4×2 quad grid top surface (better lighting than single quad)
    #      - A 4×2 quad grid front rock face (the drop face between tiers)
    #    Respects caller's num_steps exactly (clamped to >= 1, not forced to 2).
    # ------------------------------------------------------------------
    effective_steps = max(1, num_steps)
    step_height_val = height / max(effective_steps, 1)
    steps: list[dict[str, Any]] = []
    ledge_x_segs = 4   # 4 segments across = 5 verts → 4 quads per row
    ledge_d_segs = 2   # 2 depth segments
    for si in range(effective_steps):
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
        ledge_face_h = step_height_val * 0.35   # height of the vertical rock face below lip

        # Each cascade section's sheet bows outward by the parabola formula
        # depth = bow_depth * 0.35 * sqrt(drop_frac) where drop_frac is the
        # fractional drop completed at this step's start height.
        step_drop_frac = (si + 1) / max(effective_steps, 1)

        # --- 4-segment grid ledge top surface ---
        top_s = len(vertices)
        for ldi in range(ledge_d_segs + 1):
            ldt = ldi / max(ledge_d_segs, 1)
            ly = step_y - ldt * step_d
            for lxi in range(ledge_x_segs + 1):
                lxt = lxi / max(ledge_x_segs, 1)
                lx = -hw + lxt * step_w
                # Small height variation for believable ledge surface
                lz = step_z + _hash_noise(lx * 0.3, ly * 0.3, seed + 70 + si) * 0.08
                vertices.append((lx, ly, lz))
                uvs.append((lxt, step_drop_frac))
        for ldi in range(ledge_d_segs):
            for lxi in range(ledge_x_segs):
                v0 = top_s + ldi * (ledge_x_segs + 1) + lxi
                v1 = v0 + 1
                v2 = v0 + (ledge_x_segs + 1) + 1
                v3 = v0 + (ledge_x_segs + 1)
                faces.append((v0, v1, v2, v3))
                mat_indices.append(3)  # ledge_stone

        # --- 4-segment grid rock face (vertical drop below ledge lip) ---
        face_z_segs = 2
        face_s = len(vertices)
        for fzi in range(face_z_segs + 1):
            fzt = fzi / max(face_z_segs, 1)
            fz = step_z - fzt * ledge_face_h
            for lxi in range(ledge_x_segs + 1):
                lxt = lxi / max(ledge_x_segs, 1)
                lx = -hw + lxt * step_w
                fy = step_y + _hash_noise(lx * 0.2, fz * 0.2, seed + 80 + si) * 0.06
                vertices.append((lx, fy, fz))
                uvs.append((lxt, step_drop_frac + fzt * (1.0 / max(effective_steps, 1))))
        for fzi in range(face_z_segs):
            for lxi in range(ledge_x_segs):
                v0 = face_s + fzi * (ledge_x_segs + 1) + lxi
                v1 = v0 + 1
                v2 = v0 + (ledge_x_segs + 1) + 1
                v3 = v0 + (ledge_x_segs + 1)
                faces.append((v0, v3, v2, v1))  # reversed: face toward viewer
                mat_indices.append(1)  # wet_rock

    # ------------------------------------------------------------------
    # 5. Plunge pool — hemispherical concave basin (bowl shape).
    #    Built as a grid of latitude rings that follow a hemispherical
    #    profile: r(lat) = pool_r * cos(lat), z(lat) = -pool_depth * sin(lat)
    #    This gives a smooth concave bowl rather than a flat disk.
    # ------------------------------------------------------------------
    pool_res = 24          # angular divisions around the rim
    pool_lat_rings = 5     # number of latitude rings from rim to deepest point
    pool_depth_val = rng.uniform(height * 0.1, height * 0.2)
    pool_center_y = -(effective_steps * 1.5 + effective_pool_radius * 0.6)

    _ = len(vertices)  # FIX-11-10: pool_vert_start unused; pool_vert_indices tracks indices directly
    pool_vert_indices: list[int] = []

    # Build hemispherical basin rings from rim (lat=0, z=0) down to nadir
    # lat angle runs from 0 (rim) to π/2 (bottom)
    basin_rings: list[int] = []   # start index of each ring in vertices list

    for ring in range(pool_lat_rings + 1):
        lat_t = ring / max(pool_lat_rings, 1)            # 0=rim, 1=nadir
        lat_angle = lat_t * (math.pi / 2.0)              # 0..π/2
        ring_r = effective_pool_radius * math.cos(lat_angle)
        ring_z = -pool_depth_val * math.sin(lat_angle)

        ring_start = len(vertices)
        basin_rings.append(ring_start)

        for i in range(pool_res):
            angle = 2.0 * math.pi * i / pool_res
            noise_r = _hash_noise(math.cos(angle) * 3.0 + ring,
                                  math.sin(angle) * 3.0 + ring, seed + 9) \
                      * effective_pool_radius * 0.04 * (1.0 - lat_t)
            r = ring_r + noise_r
            x = math.cos(angle) * r
            y = pool_center_y + math.sin(angle) * r
            idx = len(vertices)
            if ring == 0:
                pool_vert_indices.append(idx)
            vertices.append((x, y, ring_z))
            u_pool = (math.cos(angle) + 1.0) * 0.5
            v_pool = (math.sin(angle) + 1.0) * 0.5
            uvs.append((u_pool, v_pool))

    # Nadir (deepest point) center vertex
    pool_nadir_idx = len(vertices)
    vertices.append((0.0, pool_center_y, -pool_depth_val))
    uvs.append((0.5, 0.5))

    # Basin quad faces between adjacent latitude rings
    for ring in range(pool_lat_rings):
        r0 = basin_rings[ring]
        r1 = basin_rings[ring + 1]
        for i in range(pool_res):
            i_next = (i + 1) % pool_res
            v0 = r0 + i
            v1 = r0 + i_next
            v2 = r1 + i_next
            v3 = r1 + i
            faces.append((v0, v1, v2, v3))
            mat_indices.append(2)  # pool_bottom

    # Fan from innermost ring to nadir point
    last_ring = basin_rings[pool_lat_rings]
    for i in range(pool_res):
        i_next = (i + 1) % pool_res
        faces.append((last_ring + i, pool_nadir_idx, last_ring + i_next))
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
    # 7. Foam at impact zone — wider flat ring at the base of the fall.
    #    Foam is a concentric annulus around the plunge point: inner radius =
    #    half_w (matches the sheet width), outer radius = half_w * 2.4 so it
    #    fans out where the curtain hits the pool surface.  Uses white_foam
    #    material.  The ring sits at z = 0 (pool surface level).
    # ------------------------------------------------------------------
    foam_res_ang = 24     # angular segments around the ring
    foam_res_rad = 3      # radial segments from inner to outer edge
    foam_inner_r = half_w
    foam_outer_r = half_w * 2.4
    foam_center_y = pool_center_y * 0.15   # slightly toward the base of fall

    foam_vert_start = len(vertices)
    foam_vert_indices: list[int] = []

    for ri in range(foam_res_rad + 1):
        rt = ri / max(foam_res_rad, 1)
        r = foam_inner_r + rt * (foam_outer_r - foam_inner_r)
        # Foam thins out and sits slightly above pool level toward outer edge
        z_foam = rt * 0.06   # slight upward tilt outward (splash)
        for ai in range(foam_res_ang):
            angle = 2.0 * math.pi * ai / foam_res_ang
            x_f = math.cos(angle) * r
            y_f = foam_center_y + math.sin(angle) * r * 0.5   # elliptical
            # Small height perturbation for foam chop
            z_f = z_foam + _hash_noise(x_f * 0.4, y_f * 0.4, seed + 40) * 0.04
            fidx = len(vertices)
            foam_vert_indices.append(fidx)
            vertices.append((x_f, y_f, z_f))
            uvs.append(((math.cos(angle) + 1.0) * 0.5, rt))

    # Foam quad faces
    for ri in range(foam_res_rad):
        for ai in range(foam_res_ang):
            ai_next = (ai + 1) % foam_res_ang
            v0 = foam_vert_start + ri * foam_res_ang + ai
            v1 = foam_vert_start + ri * foam_res_ang + ai_next
            v2 = foam_vert_start + (ri + 1) * foam_res_ang + ai_next
            v3 = foam_vert_start + (ri + 1) * foam_res_ang + ai
            faces.append((v0, v1, v2, v3))
            mat_indices.append(7)  # white_foam

    # ------------------------------------------------------------------
    # 8. Side spray — thin extruded planes fanning out at the impact zone.
    #    Two spray planes, one on each side of the curtain, each a 3×4 quad
    #    grid fanning outward and upward from the base of the sheet.
    #    Material: spray_mist (semi-transparent in the renderer).
    # ------------------------------------------------------------------
    spray_vert_start = len(vertices)
    spray_vert_indices: list[int] = []
    spray_segs_x = 3    # horizontal segments per spray plane
    spray_segs_z = 4    # vertical segments per spray plane
    spray_height = height * 0.25          # spray rises 25% of fall height
    spray_width_spread = half_w * 1.8    # total lateral spread of each fan

    for side_sign in (-1.0, 1.0):
        # Spray fans outward from the impact point at the base
        # Base x = ±half_w (edge of curtain), y = 0 (front of fall)
        # Fan spreads laterally by spray_width_spread and rises spray_height
        for sxi in range(spray_segs_x + 1):
            sxt = sxi / max(spray_segs_x, 1)   # 0=at curtain edge, 1=outer spray
            for szi in range(spray_segs_z + 1):
                szt = szi / max(spray_segs_z, 1)
                # Lateral position fans outward
                x_s = side_sign * (half_w + sxt * spray_width_spread)
                # Spray curves upward and forward (away from cliff)
                y_s = -szt * spray_height * 0.4    # leans away from cliff
                z_s = szt * spray_height * (1.0 - sxt * 0.5)  # rises, tapers laterally
                # Thin perturbation for organic spray shape
                x_s += _hash_noise(x_s * 0.3, z_s * 0.3, seed + 50) * 0.12 * half_w
                sidx = len(vertices)
                spray_vert_indices.append(sidx)
                vertices.append((x_s, y_s, z_s))
                uvs.append((sxt, 1.0 - szt))  # V=0 at top of spray, V=1 at base

        # Quad faces for this spray plane
        cols_sp = spray_segs_x + 1
        base_sp = spray_vert_start + (0 if side_sign < 0 else
                                       (spray_segs_x + 1) * (spray_segs_z + 1))
        for szi in range(spray_segs_z):
            for sxi in range(spray_segs_x):
                v0 = base_sp + szi * cols_sp + sxi
                v1 = v0 + 1
                v2 = v0 + cols_sp + 1
                v3 = v0 + cols_sp
                if side_sign < 0:
                    faces.append((v0, v1, v2, v3))
                else:
                    faces.append((v0, v3, v2, v1))  # flip winding for right side
                mat_indices.append(8)  # spray_mist

    # ------------------------------------------------------------------
    # 9. Direction-aware rotation (same contract as original)
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

    _wf_normals = _compute_face_normals(vertices, faces)
    return {
        "mesh": {"vertices": vertices, "faces": faces, "normals": _wf_normals},
        "uvs": uvs,
        "sheet_verts": sheet_vert_indices,
        "pool_verts": pool_vert_indices,
        "foam_verts": foam_vert_indices,
        "spray_verts": spray_vert_indices,
        "drop_zone": {
            "center": (0.0, 0.0, 0.0),
            "radius": half_w * 1.2,
            "impact_velocity_hint": math.sqrt(2.0 * 9.81 * height),
        },
        "steps": steps,
        "pool": pool_info,
        "cave": cave_info,
        "splash_zone": splash_zone,
        "materials": materials,
        "material_indices": mat_indices,
        "material_metadata": _material_metadata(
            ("cliff_rock",        0.90, "hard_rock",     0.0),
            ("wet_rock",          0.60, "wet_stone",     0.0),
            ("pool_bottom",       0.70, "sediment",      0.0),
            ("ledge_stone",       0.80, "hard_rock",     0.0),
            ("moss",              0.95, "organic",       0.0),
            ("water_sheet",       0.05, "water",         0.0),
            ("air_pocket",        0.10, "air",           0.0),
            ("white_foam",        0.90, "foam",          0.0),
            ("spray_mist",        0.20, "particle_hint", 0.0),
        ),
        "dimensions": {
            "height": height,
            "width": width,
            "pool_radius": effective_pool_radius,
            "lip_thickness": lip_thickness,
            "plunge_thickness": plunge_thickness,
            "lod": {
                "LOD_0": len(faces),
                "LOD_1": _lod1_faces(faces),
            },
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
        - "uvs": per-vertex (u, v) — world-space triplanar XZ projection
          (u = world X / width, v = world Z / height); suitable for
          vertical face texturing without UV seams at band boundaries
        - "cave_entrances": list of cave dicts (position, width, height, depth,
          strata_band)
        - "ledge_path": list of (x, y, z) waypoints (empty if has_ledge_path=False)
        - "overhang_zone": dict (extent, vertices)
        - "overhang_faces": list of face indices flagged as overhang_cell
          (face tilt > 90° — face normal has negative Z component)
        - "strata_bands": list of band dicts (z_bottom, z_top, type,
          fbm_x_offset) — fbm_x_offset is the per-band fBm lateral shift
        - "materials": list of material names
        - "material_indices": per-face list
        - "dimensions": dict
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)
    vertices: list[Vec3] = []
    uvs: list[tuple[float, float]] = []   # world-space triplanar XZ per vertex
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=cliff_rock, 1=hard_rock, 2=soft_rock, 3=ledge_stone,
    #            4=overhang_rock, 5=moss_rock, 6=ground_base, 7=talus_debris
    materials = ["cliff_rock", "hard_rock", "soft_rock", "ledge_stone", "overhang_rock",
                 "moss_rock", "ground_base", "talus_debris"]

    res_x = max(10, int(width))
    # Vertical resolution: at least 4 rows per strata band
    res_z = max(num_strata * 4, int(height * 1.2))

    half_w = width / 2.0
    band_height = height / max(num_strata, 1)

    # ------------------------------------------------------------------
    # Pre-compute strata band definitions.
    # Each band gets its own fBm lateral offset (fbm_x_offset) to simulate
    # tilted sediment layers — this is the "fBm noise offset per stratum
    # band" that makes each band's surface visually distinct.
    # ------------------------------------------------------------------
    strata_bands: list[dict[str, Any]] = []
    for bi in range(num_strata):
        z_bot = bi * band_height
        z_top = (bi + 1) * band_height
        hard = (bi % 2 == 1)  # odd bands are hard
        # Per-band fBm offset: sample at the band's mid-height and a
        # band-specific X seed so every band has independent wander.
        z_mid = (z_bot + z_top) * 0.5
        fbm_offset = _fbm(z_mid * 0.15, float(bi) * 1.37 + seed * 0.01,
                          seed + bi * 31, octaves=3, lacunarity=2.0, gain=0.5)
        strata_bands.append({
            "z_bottom": z_bot,
            "z_top": z_top,
            "type": "hard" if hard else "soft",
            "fbm_x_offset": fbm_offset * width * 0.06,  # up to 6% of width
        })

    # ------------------------------------------------------------------
    # Vertical crack pattern: Voronoi-like column displacement.
    # We distribute a set of "crack centres" uniformly along X, then for
    # each surface vertex compute the distance to the nearest crack centre.
    # Near the crack (<crack_radius) we displace the surface inward (toward
    # the cliff interior) to carve a narrow vertical groove.
    # ------------------------------------------------------------------
    num_cracks = max(3, int(width / 2.5))
    crack_spacing = width / max(num_cracks, 1)
    # Crack centre X positions with small random jitter
    crack_rng = random.Random(seed + 9001)
    crack_xs = [
        -half_w + (ci + 0.5) * crack_spacing + crack_rng.uniform(-crack_spacing * 0.3, crack_spacing * 0.3)
        for ci in range(num_cracks)
    ]
    crack_radius = crack_spacing * 0.18   # groove half-width
    crack_depth = 0.22                     # how deep the groove goes into the face

    def _crack_displacement(x: float, z: float) -> float:
        """Return Y displacement due to vertical cracks at position (x, z).

        Finds the nearest crack centre, then applies a smooth inward push
        if within crack_radius.  The crack deepens slightly toward the middle
        of the cliff height (most exposed zone).
        """
        nearest = min(abs(x - cx) for cx in crack_xs)
        if nearest >= crack_radius:
            return 0.0
        t = nearest / crack_radius          # 0=at crack, 1=at edge
        # Smooth cosine falloff into groove
        groove = crack_depth * (0.5 + 0.5 * math.cos(math.pi * t))
        # Modulate with height: deepest at 40–70% of cliff height
        z_mod = math.sin(max(0.0, z / max(height, 1.0)) * math.pi) * 0.6 + 0.4
        return groove * z_mod

    # ------------------------------------------------------------------
    # 1. Main cliff face — quad grid with per-row strata lean,
    #    per-band fBm offset, vertical crack displacement, and triplanar UVs.
    # ------------------------------------------------------------------
    cliff_start = len(vertices)
    for k in range(res_z + 1):
        kt = k / max(res_z, 1)
        z = kt * height

        # Which strata band are we in?
        band_idx = min(int(kt * num_strata), num_strata - 1)
        is_hard = (band_idx % 2 == 1)
        band = strata_bands[band_idx]

        # Lean: hard bands overhang (+lean in -Y), soft bands recess (+lean in +Y)
        band_t = (kt * num_strata) - band_idx   # 0..1 within this band
        if is_hard:
            lean = -0.6 * band_t
            rough_scale = 0.9
        else:
            lean = 0.4 * band_t
            rough_scale = 0.4

        # Global overhang increases toward the top
        if kt > 0.75:
            global_lean = -overhang * ((kt - 0.75) / 0.25)
        else:
            global_lean = 0.0

        # Per-band fBm lateral shift: adds horizontal wander to the whole band
        band_fbm_shift = band["fbm_x_offset"] * math.sin(kt * math.pi * num_strata)

        for ix in range(res_x):
            ixt = ix / max(res_x - 1, 1)
            x = -half_w + ixt * width

            # Two-frequency roughness: large-scale strata shape + small-scale texture
            noise = (
                _fbm(x * 0.08, z * 0.12, seed, octaves=3, lacunarity=2.0, gain=0.5)
                * rough_scale * 0.7
                + _hash_noise(x * 0.4, z * 0.4, seed + 1) * rough_scale * 0.25
            )

            # Vertical crack groove displacement (pushes surface forward/inward)
            crack_disp = _crack_displacement(x, z)

            y = lean + global_lean + noise + band_fbm_shift + crack_disp
            vertices.append((x, y, z))

            # World-space triplanar XZ UV: u = world X normalised, v = world Z normalised
            # This projects the texture horizontally along the cliff face (no seams at
            # band boundaries) and is correct for vertical surfaces viewed from the front.
            uvs.append((x / max(width, 1e-6) + 0.5, z / max(height, 1e-6)))

    # Quad faces for the cliff surface; track overhang cells
    overhang_face_indices: list[int] = []
    for k in range(res_z):
        for ix in range(res_x - 1):
            v0 = cliff_start + k * res_x + ix
            v1 = v0 + 1
            v2 = v0 + res_x + 1
            v3 = v0 + res_x
            face_idx = len(faces)
            faces.append((v0, v1, v2, v3))
            kt_face = (k + 0.5) / max(res_z, 1)
            band_idx_f = min(int(kt_face * num_strata), num_strata - 1)
            is_hard_f = (band_idx_f % 2 == 1)

            # Overhang detection: compute approximate face normal's Z component.
            # The face lies in the XZ plane with Y displacement; if the quad's
            # average Y of the top row is less than the bottom row's average Y
            # (i.e. the face tilts backward past vertical), it is an overhang.
            y_bot = (vertices[v0][1] + vertices[v1][1]) * 0.5
            y_top = (vertices[v3][1] + vertices[v2][1]) * 0.5
            is_overhang = y_top < y_bot - 0.05   # top leans outward past vertical
            if is_overhang:
                overhang_face_indices.append(face_idx)
                mat_indices.append(3)  # overhang_rock
            elif kt_face > 0.75:
                mat_indices.append(3)  # overhang_rock (top zone)
            elif kt_face > 0.55:
                mat_indices.append(4)  # moss (mid-upper)
            elif is_hard_f:
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
        cliff_bot_v = vertices[cliff_start + ix]
        y_base = cliff_bot_v[1]
        vertices.append((x, ground_y, 0.0))   # ground edge
        uvs.append((x / max(width, 1e-6) + 0.5, 0.0))
        vertices.append((x, y_base, 0.0))     # cliff foot
        uvs.append((x / max(width, 1e-6) + 0.5, 0.0))

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
            # Triplanar XZ UV for underside (same projection, Z is nearly constant)
            uvs.append((x / max(width, 1e-6) + 0.5, z_under / max(height, 1e-6)))
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
            uvs.append((wp[0] / max(width, 1e-6) + 0.5, wp[2] / max(height, 1e-6)))
            vertices.append((wp[0], wp[1] - ledge_w, wp[2]))
            uvs.append((wp[0] / max(width, 1e-6) + 0.5, wp[2] / max(height, 1e-6)))

        for i in range(len(ledge_path) - 1):
            v0 = ledge_geom_start + i * 2
            v1 = v0 + 1
            v2 = v0 + 3
            v3 = v0 + 2
            faces.append((v0, v1, v2, v3))
            mat_indices.append(2)  # ledge_stone

    # Enrich strata_bands with differential hardness metadata
    for band in strata_bands:
        if band["type"] == "hard":
            band["hardness"] = 0.85
            band["erosion_resistance"] = 0.90
            band["roughness_hint"] = 0.80
        else:
            band["hardness"] = 0.35
            band["erosion_resistance"] = 0.40
            band["roughness_hint"] = 0.45

    # Fracture pattern spec (vertical crack distribution metadata)
    fracture_spec = {
        "crack_count": num_cracks,
        "crack_xs": crack_xs,
        "crack_radius": crack_radius,
        "crack_depth": crack_depth,
    }

    # ------------------------------------------------------------------
    # 6. Talus cone — wedge-shaped debris apron at the cliff base.
    #    The apron runs the full width of the cliff, extending outward
    #    from the cliff foot at the natural angle of repose (~32°).
    #    Height of the talus at its inner edge = height * 0.15 (the cone
    #    reaches ~15% of cliff height before it flattens to ground).
    #    This is the key AAA gap: without talus the cliff reads as floating.
    # ------------------------------------------------------------------
    talus_height = height * 0.15       # talus mound height at cliff foot
    talus_reach  = talus_height / math.tan(math.radians(32.0))  # horizontal extent
    talus_res_d  = max(4, int(talus_reach * 1.5))
    talus_res_x  = res_x

    talus_start = len(vertices)
    for ix in range(talus_res_x):
        ixt = ix / max(talus_res_x - 1, 1)
        tx = -half_w + ixt * width
        # Cliff foot Y from the ground plane geometry
        cliff_foot_y = vertices[cliff_start + ix][1]
        for td in range(talus_res_d + 1):
            tdt = td / max(talus_res_d, 1)   # 0 = cliff foot, 1 = talus toe
            ty = cliff_foot_y + tdt * talus_reach    # extends forward (away from cliff)
            tz = talus_height * (1.0 - tdt)          # drops to 0 at toe
            # fBm rubble texture
            tz += _hash_noise(tx * 0.15, ty * 0.15, seed + 600) * talus_height * 0.12
            vertices.append((tx, ty, tz))
            uvs.append((ixt, tdt))

    for ix in range(talus_res_x - 1):
        for td in range(talus_res_d):
            v0 = talus_start + ix * (talus_res_d + 1) + td
            v1 = v0 + 1
            v2 = v0 + (talus_res_d + 1) + 1
            v3 = v0 + (talus_res_d + 1)
            faces.append((v0, v1, v2, v3))
            mat_indices.append(6)  # talus_debris

    talus_spec = {
        "height": talus_height,
        "reach": talus_reach,
        "angle_of_repose_deg": 32.0,
        "vertex_start": talus_start,
    }

    # ------------------------------------------------------------------
    # 7. Varying setback angle along height — metadata for the main face.
    #    The existing lean logic bakes this into vertex positions, but we
    #    also expose it as a per-band setback_angle for downstream tools.
    # ------------------------------------------------------------------
    for band in strata_bands:
        z_mid = (band["z_bottom"] + band["z_top"]) * 0.5
        kt_mid = z_mid / max(height, 1e-6)
        # Global overhang lean at this height (same formula as vertex builder)
        if kt_mid > 0.75:
            global_l = -overhang * ((kt_mid - 0.75) / 0.25)
        else:
            global_l = 0.0
        # Band local lean
        local_l = -0.6 * 0.5 if band["type"] == "hard" else 0.4 * 0.5
        total_lean = global_l + local_l
        # Convert lean distance to approximate angle from vertical (degrees)
        band["setback_angle_deg"] = math.degrees(math.atan2(abs(total_lean), height * 0.1))

    # ------------------------------------------------------------------
    # 8. Boulder scatter placements — Williams morphometry r = 0.6 * H^0.4
    #    5-15 boulders per 10 m of cliff width, placed 3-8 m outward from
    #    cliff base (positive Y = away from cliff face).
    #    Output feeds scatter system for physical boulder mesh placement.
    # ------------------------------------------------------------------
    boulder_rng = random.Random(seed + 77777)
    boulders_per_10m = boulder_rng.uniform(5.0, 15.0)
    n_boulders = max(1, int(boulders_per_10m * width / 10.0))
    cliff_boulder_placements: list[dict] = []
    for _bi in range(n_boulders):
        bx = boulder_rng.uniform(-half_w * 0.95, half_w * 0.95)
        outward_dist = boulder_rng.uniform(3.0, 8.0)
        # Williams morphometry: base radius = 0.6 * height^0.4
        b_radius = 0.6 * (height ** 0.4)
        size_scale = boulder_rng.uniform(0.15, 1.25)
        b_radius = max(0.3, min(2.5, b_radius * size_scale))
        # Y = cliff foot (y=0) + outward extent; Z = ground level + radius
        cliff_boulder_placements.append({
            "position": (bx, outward_dist, b_radius),
            "radius_m": b_radius,
        })

    # ------------------------------------------------------------------
    # 9. Ledge vegetation points — one anchor per ledge per 2 m along X.
    #    Placed on the hard strata ledge surfaces at the mid-depth of each
    #    ledge band; suitable for small shrubs, ferns, and creeping plants.
    # ------------------------------------------------------------------
    cliff_ledge_vegetation_points: list[Vec3] = []
    hard_strata = [b for b in strata_bands if b["type"] == "hard"]
    veg_step = max(1, int(width / 2.0))
    for band in hard_strata:
        ledge_z = (band["z_bottom"] + band["z_top"]) * 0.5
        # Place a vegetation point every ~2 m along the cliff width
        for vi in range(veg_step + 1):
            vt = vi / max(veg_step, 1)
            vx = -half_w + vt * width
            # Slight Y inset so vegetation sits on the ledge face (0.1 m into face)
            vy = _hash_noise(vx * 0.2, ledge_z * 0.2, seed + 8888) * 0.15 - 0.1
            vz = ledge_z + _hash_noise(vx * 0.3, float(vi), seed + 9999) * 0.2
            cliff_ledge_vegetation_points.append((vx, vy, vz))

    _cf_normals = _compute_face_normals(vertices, faces)
    return {
        "mesh": {"vertices": vertices, "faces": faces, "normals": _cf_normals},
        "uvs": uvs,
        "cave_entrances": cave_entrances,
        "ledge_path": ledge_path,
        "overhang_zone": {"extent": overhang, "vertices": overhang_zone_verts},
        "overhang_faces": overhang_face_indices,
        "strata_bands": strata_bands,
        "fracture_spec": fracture_spec,
        "talus_spec": talus_spec,
        "cliff_boulder_placements": cliff_boulder_placements,
        "cliff_ledge_vegetation_points": cliff_ledge_vegetation_points,
        "materials": materials,
        "material_indices": mat_indices,
        "material_metadata": _material_metadata(
            ("cliff_rock",     0.85, "hard_rock",   0.0),
            ("hard_rock",      0.80, "hard_rock",   0.0),
            ("soft_rock",      0.50, "soft_rock",   0.0),
            ("ledge_stone",    0.75, "hard_rock",   0.0),
            ("overhang_rock",  0.78, "hard_rock",   0.0),
            ("moss_rock",      0.92, "organic",     0.0),
            ("ground_base",    0.88, "sediment",    0.0),
            ("talus_debris",   0.92, "loose_rock",  0.0),
        ),
        "dimensions": {
            "width": width,
            "height": height,
            "overhang": overhang,
            "num_strata": num_strata,
            "talus_height": talus_height,
            "talus_reach": talus_reach,
            "lod": {
                "LOD_0": len(faces),
                "LOD_1": _lod1_faces(faces),
            },
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
    # Fixed minimum resolution: size/2 gives only 25 quads for a 50 m terrain.
    # Clamp to at least 32 so there is enough geometry for believable channel carving.
    resolution = max(32, int(size / 2))
    half_size = size / 2.0

    # Materials: 0=swamp_mud, 1=shallow_water, 2=deep_water, 3=moss_ground,
    #            4=dead_vegetation, 5=sedge_mound, 6=wet_transition
    materials = ["swamp_mud", "shallow_water", "deep_water", "moss_ground",
                 "dead_vegetation", "sedge_mound", "wet_transition"]

    # ------------------------------------------------------------------
    # 1. Base heightmap — 3-octave microtopography: macro undulation +
    #    hummock-scale roughness + micro peat-crack detail
    # ------------------------------------------------------------------
    heights: list[list[float]] = []
    for i in range(resolution):
        row: list[float] = []
        for j in range(resolution):
            gx = -half_size + (j / max(resolution - 1, 1)) * size
            gy = -half_size + (i / max(resolution - 1, 1)) * size
            # Macro: broad swamp basin (~10 m wavelength)
            h_macro = _fbm(gx * 0.02, gy * 0.02, seed, octaves=3,
                           lacunarity=2.0, gain=0.5) * 0.15
            # Meso: hummock-scale undulation (~2 m wavelength)
            h_meso = _fbm(gx * 0.12, gy * 0.12, seed + 7, octaves=2,
                          lacunarity=1.8, gain=0.45) * 0.06
            # Micro: peat surface cracking (~0.3 m wavelength)
            h_micro = _hash_noise(gx * 0.5, gy * 0.5, seed + 3) * 0.02
            h = 0.2 + h_macro + h_meso + h_micro
            row.append(h)
        heights.append(row)

    # ------------------------------------------------------------------
    # 1b. Three meandering channels — main + left tributary + right tributary
    #     Each runs roughly from one edge to the other with sinusoidal
    #     lateral wander.  Channel floor below water_level → deep water.
    # ------------------------------------------------------------------
    channel_defs = [
        # (meander_amp_frac, meander_freq_mult, width_frac, depth_drop, phase_offset)
        (0.14, 2.8, 0.06, 0.18, 0.0),       # main channel
        (0.07, 3.4, 0.035, 0.12, 1.1),      # left tributary
        (0.08, 3.1, 0.032, 0.11, 2.3),      # right tributary
    ]
    for (ma_frac, mf_mult, cw_frac, cdrop, c_phase_off) in channel_defs:
        cw = size * cw_frac
        c_amp = size * ma_frac
        c_freq = mf_mult * math.pi / max(size, 1.0)
        c_phase = (seed % 500) * 0.01257 + c_phase_off
        for i in range(resolution):
            for j in range(resolution):
                gx = -half_size + (j / max(resolution - 1, 1)) * size
                gy = -half_size + (i / max(resolution - 1, 1)) * size
                ch_cx = c_amp * math.sin(gy * c_freq + c_phase)
                dist_ch = abs(gx - ch_cx)
                if dist_ch < cw:
                    t_ch = dist_ch / cw
                    carve = cdrop * (0.5 + 0.5 * math.cos(math.pi * t_ch))
                    heights[i][j] -= carve

    # ------------------------------------------------------------------
    # 2. Hummocks — raised sedge mounds with a wet transition ring dip
    #    just outside the mound edge, mimicking pooling at hummock margins.
    # ------------------------------------------------------------------
    hummocks: list[dict[str, Any]] = []
    for hi in range(hummock_count):
        hx = rng.uniform(-half_size * 0.8, half_size * 0.8)
        hy = rng.uniform(-half_size * 0.8, half_size * 0.8)
        h_radius = rng.uniform(1.5, 4.0)
        # Height guaranteed above water so hummock is always dry land
        h_height = rng.uniform(0.25, 0.65)
        # Transition zone dip: ring of water just outside hummock edge
        transition_radius = h_radius * 1.45
        hummocks.append({"position": (hx, hy, 0.0), "radius": h_radius,
                         "transition_radius": transition_radius,
                         "height": h_height})
        for i in range(resolution):
            for j in range(resolution):
                gx = -half_size + (j / max(resolution - 1, 1)) * size
                gy = -half_size + (i / max(resolution - 1, 1)) * size
                dist = math.sqrt((gx - hx) ** 2 + (gy - hy) ** 2)
                if dist < h_radius:
                    # Core mound with smooth falloff
                    falloff = 1.0 - (dist / h_radius) ** 2
                    heights[i][j] += h_height * falloff
                elif dist < transition_radius:
                    # Wet moat ring dips ~40% of mound height below surroundings
                    ring_t = (dist - h_radius) / (transition_radius - h_radius)
                    dip = h_height * 0.4 * math.sin(math.pi * ring_t)
                    heights[i][j] -= dip

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
            elif avg_z < water_z + 0.3:
                mat_indices.append(6)   # wet_transition (waterlogged margin)
            elif avg_z < water_z + 0.8:
                mat_indices.append(0)   # swamp_mud
            elif avg_z < water_z + 1.8:
                mat_indices.append(5)   # sedge_mound (raised hummock top)
            elif avg_z < water_z + 2.5:
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

    # ------------------------------------------------------------------
    # 8. Root network specs — exposed tree-root systems radiating from
    #    each hummock and island centre (no mesh, instanced downstream).
    # ------------------------------------------------------------------
    root_network: list[dict[str, Any]] = []
    for feature in [*hummocks, *islands]:
        fx, fy = feature["position"][0], feature["position"][1]
        num_roots = rng.randint(3, 7)
        roots: list[dict[str, Any]] = []
        for ri in range(num_roots):
            r_angle = rng.uniform(0.0, 2.0 * math.pi)
            r_len = rng.uniform(feature["radius"] * 0.6, feature["radius"] * 1.4)
            r_width = rng.uniform(0.05, 0.18)
            end_x = fx + math.cos(r_angle) * r_len
            end_y = fy + math.sin(r_angle) * r_len
            # Roots dip into mud (z slightly below water level)
            r_dip = water_z - rng.uniform(0.0, 0.08)
            roots.append({
                "start": (fx, fy, r_dip),
                "end": (end_x, end_y, r_dip - rng.uniform(0.0, 0.05)),
                "width": r_width,
                "arch_height": r_width * rng.uniform(1.0, 2.5),
            })
        root_network.append({
            "origin": (fx, fy, water_z),
            "roots": roots,
        })

    # Mud displacement metadata (vertex-level procedural detail hint for renderer)
    mud_displacement = {
        "amplitude": 0.08,
        "frequency": 3.5,
        "octaves": 3,
        "seed": seed + 200,
        "affected_materials": ["swamp_mud"],
    }

    # Planar XY UVs for swamp: u = (x + half_size) / size, v = (y + half_size) / size
    _sw_uvs = [
        (
            max(0.0, min(1.0, (float(v[0]) + half_size) / max(size, 1e-6))),
            max(0.0, min(1.0, (float(v[1]) + half_size) / max(size, 1e-6))),
        )
        for v in vertices
    ]
    _sw_normals = _compute_face_normals(vertices, faces)
    return {
        "mesh": {"vertices": vertices, "faces": faces, "normals": _sw_normals},
        "uvs": _sw_uvs,
        "hummocks": hummocks,
        "islands": islands,
        "water_zones": water_zones,
        "log_specs": log_specs,
        "root_network": root_network,
        "mud_displacement": mud_displacement,
        "mist_zone": mist_zone,
        "materials": materials,
        "material_indices": mat_indices,
        "material_metadata": _material_metadata(
            ("swamp_mud",       0.92, "mud",          0.0),
            ("shallow_water",   0.08, "water",        0.0),
            ("deep_water",      0.05, "water",        0.0),
            ("moss_ground",     0.88, "organic",      0.0),
            ("dead_vegetation", 0.95, "organic",      0.0),
            ("sedge_mound",     0.85, "organic",      0.0),
            ("wet_transition",  0.78, "mud",          0.0),
        ),
        "dimensions": {
            "size": size,
            "water_level": water_level,
            "lod": {
                "LOD_0": len(faces),
                "LOD_1": _lod1_faces(faces),
            },
        },
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

    # Strata displacement parameters — X-axis shift per band to fake sediment offset
    strata_amp = thickness * 0.12   # amplitude of per-strata X shift

    # UV list for triplanar arch projection (u = x/span normalised, v = z/height)
    uvs: list[tuple[float, float]] = []

    # ------------------------------------------------------------------
    # 1. Arch front face — catenary profile, extruded along Y.
    #
    #    Catenary: z(x) = a * cosh(x / a) - a  (cable hanging under gravity)
    #    We solve for 'a' so the crown (x=0) reaches arch_height:
    #        a * cosh(0) - a = 0, so catenary gives 0 at x=0.
    #    Shift: z_cat(x) = a*(cosh(x/a) - cosh(half_span/a)) + arch_height
    #    This puts the crown at z=arch_height and the legs at z=0.
    #
    #    'a' (catenary parameter) controls curvature: large a = flat,
    #    small a = tight.  Use a = half_span / acosh(arch_height/half_span + 1)
    #    clamped so the formula stays real.
    # ------------------------------------------------------------------
    _cat_ratio = max(arch_height / max(half_span, 1e-6), 0.01)
    # acosh(x) = ln(x + sqrt(x^2-1)), need argument >= 1
    _cat_arg = _cat_ratio + 1.0
    _cat_a = half_span / math.log(_cat_arg + math.sqrt(_cat_arg ** 2 - 1))
    _cat_leg_z = _cat_a * (math.cosh(half_span / _cat_a) - 1.0)

    def _arch_z(x: float) -> float:
        """Catenary arch crown height at lateral position x.

        Returns arch_height at x=0 (keystone) and 0 at x=±half_span (legs).
        """
        raw = _cat_a * (math.cosh(x / _cat_a) - 1.0)
        # Map: 0 at keystone → arch_height, _cat_leg_z at legs → 0
        t = raw / max(_cat_leg_z, 1e-9)
        return arch_height * max(0.0, 1.0 - t)

    def _arch_inner_z(x: float, taper_thickness: float = 0.0) -> float:
        """Soffit height using the given (possibly tapered) thickness."""
        tt = taper_thickness if taper_thickness > 0.0 else _tapered_thickness(x)
        crown = _arch_z(x)
        return max(0.0, crown - tt)

    # Cross-section tube radius tapers: thick at base, thin at crown.
    # At x=±half_span (legs) tube_t=0 → full thickness.
    # At x=0 (keystone) tube_t=1 → thinned crown.
    def _tapered_thickness(x: float) -> float:
        """Thickness tapers from full at legs (|x|=half_span) to 60% at crown."""
        leg_t = abs(x) / max(half_span, 1e-6)        # 0 at keystone, 1 at leg
        return thickness * (0.60 + 0.40 * leg_t)     # 60%–100% of thickness

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

            taper_t = _tapered_thickness(x_pos)
            crown = _arch_z(x_pos)
            soffit = _arch_inner_z(x_pos, taper_t)
            band_h = crown - soffit

            for tk in range(thickness_segs + 1):
                tkt = tk / max(thickness_segs, 1)
                z_pos = soffit + tkt * band_h

                # Strata displacement: offset X by sin wave keyed to height band
                # angle varies along the arch span so each strata line shows a
                # slightly different lateral shift — mimics tilted rock beds.
                strata_angle = (z_pos / max(arch_height, 1e-6)) * num_strata * math.pi
                strata_x_shift = math.sin(strata_angle + seed * 0.31) * strata_amp

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

                vx = x_pos + nx_n * rough + strata_x_shift
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
    # 3. Rock-mass side walls — fill the space between each arch leg and
    #    the ground.  Each wall is a planar quad grid on the front/back
    #    faces of the leg volume, spanning from ground (z=0) up to the
    #    soffit of the arch at that x position.  This gives the arch real
    #    visual bulk instead of leaving hollow voids under the legs.
    # ------------------------------------------------------------------
    wall_segs_z = max(4, int(arch_height))
    wall_segs_d = max(3, depth_segs // 2)

    for side_sign, side_x_start, side_x_end in [
        (-1.0, -half_span - thickness, -half_span),   # left leg wall
        ( 1.0,  half_span,              half_span + thickness),  # right leg wall
    ]:
        sw_start = len(vertices)
        for wz in range(wall_segs_z + 1):
            wzt = wz / max(wall_segs_z, 1)
            z_w = wzt * arch_height
            for wd in range(wall_segs_d + 1):
                wdt = wd / max(wall_segs_d, 1)
                y_w = -half_depth + wdt * eff_depth
                # X position is the outer face of the leg (constant per side)
                x_w = side_x_start if side_sign < 0 else side_x_end
                rough_w = roughness * _hash_noise(x_w * 0.1, z_w * 0.13 + y_w * 0.07, seed + 200) * 0.25
                vertices.append((x_w + rough_w * 0.3, y_w, z_w + rough_w * 0.2))

        for wz in range(wall_segs_z):
            for wd in range(wall_segs_d):
                v0 = sw_start + wz * (wall_segs_d + 1) + wd
                v1 = v0 + 1
                v2 = v0 + (wall_segs_d + 1) + 1
                v3 = v0 + (wall_segs_d + 1)
                if side_sign < 0:
                    faces.append((v0, v1, v2, v3))
                else:
                    faces.append((v0, v3, v2, v1))
                mat_indices.append(1)  # rock_mass

    # ------------------------------------------------------------------
    # 4. Undercut base geometry — each arch leg base has an erosion notch
    #    carved into the bottom inner face, giving the arch that characteristic
    #    underhung "pedestal" look seen in Delicate Arch and Rainbow Bridge.
    #    Geometry: a thin inset ring of triangles along the base of each leg,
    #    set back ~30% of thickness from the outer face, at z=0..undercut_h.
    # ------------------------------------------------------------------
    undercut_h = min(arch_height * 0.18, thickness * 0.55)   # notch height
    undercut_depth = thickness * 0.30                          # how far it recesses
    undercut_segs = max(6, int(eff_depth * 1.2))

    # Materials 5=undercut_notch added inline (material list updated below)
    materials.append("undercut_notch")

    for leg_cx in (-half_span, half_span):
        # Inner edge of the notch (recessed) and outer edge (flush with outer face)
        notch_inner_x = leg_cx + (undercut_depth if leg_cx < 0 else -undercut_depth)
        notch_outer_x = leg_cx

        uc_inner_start = len(vertices)
        for ud in range(undercut_segs + 1):
            udt = ud / max(undercut_segs, 1)
            y_uc = -half_depth + udt * eff_depth
            # Inner bottom edge (recessed, at z=0)
            noise_uc = _hash_noise(notch_inner_x * 0.3, y_uc * 0.2, seed + 900) * 0.08
            vertices.append((notch_inner_x + noise_uc, y_uc, noise_uc * 0.3))
        uc_outer_start = len(vertices)
        for ud in range(undercut_segs + 1):
            udt = ud / max(undercut_segs, 1)
            y_uc = -half_depth + udt * eff_depth
            # Outer bottom edge (flush with leg outer face, at z=undercut_h)
            noise_uc = _hash_noise(notch_outer_x * 0.3, y_uc * 0.2, seed + 901) * 0.06
            vertices.append((notch_outer_x + noise_uc, y_uc, undercut_h + noise_uc * 0.4))

        for ud in range(undercut_segs):
            v0 = uc_inner_start + ud
            v1 = uc_inner_start + ud + 1
            v2 = uc_outer_start + ud + 1
            v3 = uc_outer_start + ud
            if leg_cx < 0:
                faces.append((v0, v1, v2, v3))
            else:
                faces.append((v0, v3, v2, v1))
            mat_indices.append(5)   # undercut_notch

    # ------------------------------------------------------------------
    # 4b. Span-to-rise ratio validation
    #     Natural arches: span/rise typically 1.5–6.0 (Arches NP data).
    #     Flag extreme values in dimensions so downstream code can warn.
    # ------------------------------------------------------------------
    span_to_rise = span_width / max(arch_height, 1e-6)
    span_rise_valid = 1.2 <= span_to_rise <= 7.0
    span_rise_note = (
        "within natural arch range" if span_rise_valid
        else f"{'too narrow' if span_to_rise < 1.2 else 'too flat'} "
             f"(span/rise={span_to_rise:.2f}; natural range 1.2–7.0)"
    )

    # ------------------------------------------------------------------
    # 5. Compute arch apex, opening clearance, keystone spec, and UVs
    # ------------------------------------------------------------------
    arch_apex: Vec3 = (0.0, 0.0, arch_height)
    opening_clearance = _arch_inner_z(0.0, _tapered_thickness(0.0))  # soffit height at keystone

    # Keystone metadata: the topmost section of the arch band at x=0
    keystone_spec = {
        "position": arch_apex,
        "width": thickness * 0.6,        # narrowest point of the arch band
        "depth": eff_depth,
        "clearance_below": opening_clearance,
        "catenary_a": _cat_a,            # catenary parameter (curvature control)
    }

    # Triplanar XZ UV projection for every vertex (u = x/total_span, v = z/arch_height)
    total_span = span_width + 2.0 * thickness
    uvs = [
        (v[0] / max(total_span, 1e-6) + 0.5, v[2] / max(arch_height + thickness, 1e-6))
        for v in vertices
    ]

    _arch_normals = _compute_face_normals(vertices, faces)
    return {
        "mesh": {"vertices": vertices, "faces": faces, "normals": _arch_normals},
        "uvs": uvs,
        "arch_apex": arch_apex,
        "opening_clearance": opening_clearance,
        "keystone": keystone_spec,
        "strata_bands": strata_bands,
        "materials": materials,
        "material_indices": mat_indices,
        "material_metadata": _material_metadata(
            ("arch_stone",      0.82, "hard_rock",   0.0),
            ("rock_mass",       0.85, "hard_rock",   0.0),
            ("moss",            0.93, "organic",     0.0),
            ("weathered_rock",  0.70, "soft_rock",   0.0),
            ("strata_line",     0.65, "sediment",    0.0),
            ("undercut_notch",  0.60, "soft_rock",   0.0),
        ),
        "dimensions": {
            "span_width": span_width,
            "arch_height": arch_height,
            "thickness": thickness,
            "arch_depth": eff_depth,
            "catenary_a": _cat_a,
            "span_to_rise": span_to_rise,
            "span_rise_valid": span_rise_valid,
            "span_rise_note": span_rise_note,
            "undercut_height": undercut_h,
            "undercut_depth": undercut_depth,
            "lod": {
                "LOD_0": len(faces),
                "LOD_1": _lod1_faces(faces),
            },
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
    #            4=travertine, 5=crater_rim, 6=sinter_cone, 7=vent_lip
    materials = ["mineral_deposit", "pool_water", "vent_rock", "sulfur_crust",
                 "travertine", "crater_rim", "sinter_cone", "vent_lip"]

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
    # 2b. Silica sinter cone — a gently tapered mound of white/cream silica
    #     built up around the vent mouth by years of mineral precipitation.
    #     The cone rises from ground level at radius=sinter_base_r to a
    #     peak at the vent lip, then drops into the vent opening.
    # ------------------------------------------------------------------
    sinter_base_r = eff_vent_diam * 2.8    # cone base radius (~3× vent opening)
    sinter_peak_h = rim_height * 0.8       # cone apex height above ground
    sinter_rings = max(4, int(sinter_base_r * 3))
    sinter_ring_res = max(16, vent_res)
    sinter_start = len(vertices)

    for sk in range(sinter_rings + 1):
        skt = sk / max(sinter_rings, 1)    # 0=base outer edge, 1=vent lip
        # Radius tapers linearly from sinter_base_r to vent_base_r
        sr = sinter_base_r + skt * (vent_base_r - sinter_base_r)
        # Height rises with smoothstep curve toward apex at vent lip
        sh = sinter_peak_h * (3.0 * skt ** 2 - 2.0 * skt ** 3)
        for si in range(sinter_ring_res):
            sa = 2.0 * math.pi * si / sinter_ring_res
            # fBm lumpy surface — sinter deposits are uneven knobs
            s_r_noise = _fbm(
                math.cos(sa) * (skt * 3.0 + 1.5),
                math.sin(sa) * (skt * 3.0 + 1.5),
                seed + 700 + sk, octaves=3, lacunarity=2.1, gain=0.48,
            ) * sr * 0.10 * (1.0 - skt * 0.6)
            s_z_noise = _hash_noise(math.cos(sa) * 4.0, float(sk), seed + 701) * 0.04
            vertices.append((
                math.cos(sa) * (sr + s_r_noise),
                math.sin(sa) * (sr + s_r_noise),
                sh + s_z_noise,
            ))

    for sk in range(sinter_rings):
        for si in range(sinter_ring_res):
            si_next = (si + 1) % sinter_ring_res
            v0 = sinter_start + sk * sinter_ring_res + si
            v1 = sinter_start + sk * sinter_ring_res + si_next
            v2 = sinter_start + (sk + 1) * sinter_ring_res + si_next
            v3 = sinter_start + (sk + 1) * sinter_ring_res + si
            faces.append((v0, v1, v2, v3))
            mat_indices.append(6)  # sinter_cone

    # ------------------------------------------------------------------
    # 2c. Steam vent lip — a raised annular ridge at the vent opening with
    #     an outward-flared outer edge and a sharp inner rim, giving the
    #     classic geyser "nozzle" look.  Placed at the top of the sinter cone.
    # ------------------------------------------------------------------
    lip_inner_r = vent_base_r * 1.05
    lip_outer_r = vent_base_r * 1.55
    lip_height = sinter_peak_h + rim_height * 0.25   # raised above cone peak
    lip_res = sinter_ring_res
    lip_inner_start = len(vertices)

    for li in range(lip_res):
        la = 2.0 * math.pi * li / lip_res
        l_noise = _hash_noise(math.cos(la) * 5.0, math.sin(la) * 5.0, seed + 800) * 0.05
        vertices.append((
            math.cos(la) * (lip_inner_r + l_noise),
            math.sin(la) * (lip_inner_r + l_noise),
            lip_height,
        ))

    lip_outer_start = len(vertices)
    for li in range(lip_res):
        la = 2.0 * math.pi * li / lip_res
        # Outer edge flares slightly lower than inner rim
        l_noise = _hash_noise(math.cos(la) * 4.5, math.sin(la) * 4.5, seed + 801) * 0.06
        vertices.append((
            math.cos(la) * (lip_outer_r + l_noise),
            math.sin(la) * (lip_outer_r + l_noise),
            lip_height - rim_height * 0.12,
        ))

    for li in range(lip_res):
        li_next = (li + 1) % lip_res
        v0 = lip_inner_start + li
        v1 = lip_inner_start + li_next
        v2 = lip_outer_start + li_next
        v3 = lip_outer_start + li
        faces.append((v0, v1, v2, v3))
        mat_indices.append(7)  # vent_lip

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

    # ------------------------------------------------------------------
    # 6. Steam column geometry — tapered cone rising from vent mouth.
    #    Represented as a cylinder that widens from vent_base_r at z=0
    #    to steam_top_r at z=steam_height, with slight fBm wobble.
    # ------------------------------------------------------------------
    steam_height = vent_height * 6.0          # steam plume rises 6× vent height
    steam_top_r = vent_base_r * 4.5           # plume fans out to 4.5× vent radius
    steam_res = max(10, vent_res)
    steam_rings = max(4, int(steam_height * 0.8))
    steam_start = len(vertices)

    for sk in range(steam_rings + 1):
        skt = sk / max(steam_rings, 1)
        sz = skt * steam_height
        # Tapered radius: narrowest at base, widest at top
        sr = vent_base_r + skt * (steam_top_r - vent_base_r)
        # fBm wobble for organic plume shape
        wobble = _fbm(sz * 0.15, float(sk) * 0.3, seed + 500,
                      octaves=3, lacunarity=2.0, gain=0.5) * sr * 0.12
        for si in range(steam_res):
            sa = 2.0 * math.pi * si / steam_res
            snoise = _hash_noise(math.cos(sa) * 3.0, sz * 0.2 + si * 0.1, seed + 501) * sr * 0.06
            svx = math.cos(sa) * (sr + wobble + snoise)
            svy = math.sin(sa) * (sr + wobble + snoise)
            vertices.append((svx, svy, sz))

    for sk in range(steam_rings):
        for si in range(steam_res):
            si_next = (si + 1) % steam_res
            v0 = steam_start + sk * steam_res + si
            v1 = steam_start + sk * steam_res + si_next
            v2 = steam_start + (sk + 1) * steam_res + si_next
            v3 = steam_start + (sk + 1) * steam_res + si
            faces.append((v0, v1, v2, v3))
            mat_indices.append(0)  # mineral_deposit (tinted as steam in shader)

    steam_vert_indices = list(range(steam_start, len(vertices)))

    # ------------------------------------------------------------------
    # 7. Eruption particle spec (no geometry — renderer reads this dict)
    # ------------------------------------------------------------------
    eruption_spec = {
        "origin": (0.0, 0.0, 0.0),
        "initial_velocity": (0.0, 0.0, vent_height * 3.5),
        "spread_angle_deg": 12.0,
        "particle_count_hint": 800,
        "steam_lifetime_s": 4.0,
        "water_droplet_lifetime_s": 1.5,
        "eruption_period_s": 90.0 + _hash_noise(float(seed), 0.0, seed + 600) * 30.0,
        "column_height": steam_height,
        "emission_hint": 0.9,
    }

    # Cylindrical UVs: u = atan2(y,x)/(2π), v = z / (pool_depth + eff_vent_depth + steam_height)
    _gy_z_range = max(pool_depth + eff_vent_depth + steam_height, 1e-6)
    _gy_uvs = [
        (
            (math.atan2(float(v[1]), float(v[0])) / (2.0 * math.pi)) % 1.0,
            (float(v[2]) + pool_depth + eff_vent_depth) / _gy_z_range,
        )
        for v in vertices
    ]
    _gy_normals = _compute_face_normals(vertices, faces)
    return {
        "mesh": {"vertices": vertices, "faces": faces, "normals": _gy_normals},
        "uvs": _gy_uvs,
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
        "steam_column": {
            "vert_indices": steam_vert_indices,
            "height": steam_height,
            "top_radius": steam_top_r,
        },
        "eruption_spec": eruption_spec,
        "materials": materials,
        "material_indices": mat_indices,
        "material_metadata": _material_metadata(
            ("mineral_deposit", 0.70, "mineral",     0.0),
            ("pool_water",      0.05, "water",       0.05),
            ("vent_rock",       0.85, "hard_rock",   0.0),
            ("sulfur_crust",    0.55, "mineral",     0.08),
            ("travertine",      0.65, "mineral",     0.0),
            ("crater_rim",      0.75, "hard_rock",   0.0),
            ("sinter_cone",     0.55, "mineral",     0.0),
            ("vent_lip",        0.50, "mineral",     0.04),
        ),
        "dimensions": {
            "pool_radius": pool_radius,
            "pool_depth": pool_depth,
            "vent_height": vent_height,
            "vent_diameter": eff_vent_diam,
            "vent_depth": eff_vent_depth,
            "crater_radius": eff_crater_r,
            "mineral_rim_width": mineral_rim_width,
            "steam_height": steam_height,
            "lod": {
                "LOD_0": len(faces),
                "LOD_1": _lod1_faces(faces),
            },
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

    # Materials: 0=dirt_wall, 1=exposed_rock, 2=rubble, 3=cave_entrance,
    #            4=rim_ground
    materials = ["dirt_wall", "exposed_rock", "rubble", "cave_entrance",
                 "rim_ground"]

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

    # Wall profile noise parameters: radius varies around the circle so the
    # sinkhole is not rotationally symmetric — different angular sectors have
    # wider/narrower walls, mimicking asymmetric karst collapse.
    wall_noise_amp = 0.18    # fraction of radius as peak-to-peak modulation
    wall_noise_freq = 5.0    # number of lobes around the circumference
    wall_noise_phase = (seed % 997) * 0.00629  # deterministic angular offset

    # Off-center depression: the deepest point is shifted slightly from centre
    # so the floor is not a perfect horizontal plane.
    depress_offset_x = _hash_noise(float(seed), 0.0, seed + 55) * radius * 0.15
    depress_offset_y = _hash_noise(0.0, float(seed), seed + 56) * radius * 0.15
    depress_depth_extra = radius * 0.08   # extra depth at the off-center low point

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

            # Noise perturbation to wall radius: each angular sector has a
            # different base radius so the wall is not a perfect circle.
            r_theta_mod = radius * wall_noise_amp * math.sin(
                angle * wall_noise_freq + wall_noise_phase
            )
            r_effective = r_profile + r_theta_mod

            # fBm roughness — more noise in mid-depth where rock is most exposed
            rough_scale = wall_roughness * math.sin(kt * math.pi) * 1.2
            noise_r = _fbm(
                cos_a * 3.5 + kt * 1.5, sin_a * 3.5 + kt * 1.5,
                seed + 10, octaves=4, lacunarity=2.0, gain=0.5,
            ) * rough_scale * radius * 0.10
            noise_z = wall_roughness * _hash_noise(angle * 3.5, kt * 5.5, seed + 11) * 0.25

            r = r_effective + noise_r
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
    # 3. Base — at z = -depth with an off-center depression so the floor is
    #    not perfectly flat.  The centre vertex is shifted to the depression
    #    point; all bottom-ring verts get a small z dip toward it.
    # ------------------------------------------------------------------
    base_z = -depth
    floor_center_idx = len(vertices)
    # Place deepest point at the off-center depression location
    vertices.append((depress_offset_x, depress_offset_y, base_z - depress_depth_extra))

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
        # Per-box random yaw rotation around Z axis — breaks axis-alignment
        box_yaw = rng.uniform(0.0, 2.0 * math.pi)
        cos_yaw = math.cos(box_yaw)
        sin_yaw = math.sin(box_yaw)
        for ddx, ddy, ddz in [
            (-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        ]:
            nd = _hash_noise(rx + ddx * 2.0, ry + ddy * 2.0, seed + 100 + ri) * r_size * 0.28
            # Local corner offset before rotation
            lx = ddx * hs + nd * 0.5
            ly = ddy * hs + nd * 0.5
            # Apply yaw rotation in XY plane
            rx_rot = lx * cos_yaw - ly * sin_yaw
            ry_rot = lx * sin_yaw + ly * cos_yaw
            vertices.append((
                rx + rx_rot,
                ry + ry_rot,
                rz + ddz * r_size + abs(nd) * 0.3,
            ))
        for bf in [(0,1,2,3), (4,7,6,5), (0,4,5,1), (2,6,7,3), (0,3,7,4), (1,5,6,2)]:
            faces.append((rb_start+bf[0], rb_start+bf[1], rb_start+bf[2], rb_start+bf[3]))
            mat_indices.append(2)

    # ------------------------------------------------------------------
    # 4b. Collapse debris ring — angular chunks at the rim edge where the
    #     ground fractured and slid inward.  These are irregular box shards
    #     placed in a ring just inside the rim, distinct from floor rubble.
    # ------------------------------------------------------------------
    debris_ring_count = max(6, int(radial_res * 0.6))
    for di in range(debris_ring_count):
        d_angle = 2.0 * math.pi * di / debris_ring_count
        d_angle += rng.uniform(-0.18, 0.18)   # break perfect ring symmetry
        d_r = radius * rng.uniform(0.88, 1.05)  # straddle the rim edge
        dx = math.cos(d_angle) * d_r
        dy = math.sin(d_angle) * d_r
        dz = _hash_noise(dx * 0.5, dy * 0.5, seed + 200 + di) * 0.35  # rim-level z
        d_size = rng.uniform(0.15, 0.55)
        d_yaw = rng.uniform(0.0, 2.0 * math.pi)
        d_pitch = rng.uniform(-0.4, 0.4)   # tip toward or away from hole
        cos_dy = math.cos(d_yaw); sin_dy = math.sin(d_yaw)
        cos_dp = math.cos(d_pitch); sin_dp = math.sin(d_pitch)
        db_start = len(vertices)
        hs = d_size / 2.0
        for ddx, ddy, ddz in [
            (-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        ]:
            # Apply yaw then pitch (rotation around world Z then local X)
            lx = ddx * hs
            ly = ddy * hs
            lz = ddz * hs
            rx2 = lx * cos_dy - ly * sin_dy
            ry2 = lx * sin_dy + ly * cos_dy
            rz2 = lz * cos_dp - ry2 * sin_dp
            ry3 = ry2 * cos_dp + lz * sin_dp
            nd = _hash_noise(dx + ddx, dy + ddy, seed + 300 + di) * d_size * 0.22
            vertices.append((dx + rx2 + nd, dy + ry3 + nd, dz + rz2 + abs(nd) * 0.2))
        for bf in [(0,1,2,3),(4,7,6,5),(0,4,5,1),(2,6,7,3),(0,3,7,4),(1,5,6,2)]:
            faces.append((db_start+bf[0], db_start+bf[1], db_start+bf[2], db_start+bf[3]))
            mat_indices.append(2)  # rubble (debris_rim folded in)

    # ------------------------------------------------------------------
    # 5. Optional bottom cave — exposed cave roof geometry above the entrance
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

        # Exposed cave ceiling — a rough horizontal quad patch above the cave
        # entrance showing the underside of dissolved limestone.
        # Placed at base_z + cave_height (roof of the cave mouth).
        cos_ca = math.cos(cave_angle)
        sin_ca = math.sin(cave_angle)
        ceil_cx = cos_ca * cave_r
        ceil_cy = sin_ca * cave_r
        ceil_z = base_z + cave_height
        ceil_hw = cave_width * 0.65    # half-width of ceiling patch
        ceil_hd = cave_width * 0.55    # half-depth along cave axis
        # Four corners of ceiling patch, displaced with fBm
        ceil_corners: list[Vec3] = []
        for su, sv in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
            cx_off = cos_ca * sv * ceil_hd - sin_ca * su * ceil_hw
            cy_off = sin_ca * sv * ceil_hd + cos_ca * su * ceil_hw
            cnoise = _fbm(ceil_cx + cx_off, ceil_cy + cy_off, seed + 400,
                          octaves=3, lacunarity=2.1, gain=0.5) * 0.18
            ceil_corners.append((ceil_cx + cx_off,
                                  ceil_cy + cy_off,
                                  ceil_z + cnoise))
        cc_start = len(vertices)
        vertices.extend(ceil_corners)
        faces.append((cc_start, cc_start+1, cc_start+2, cc_start+3))
        mat_indices.append(1)  # exposed_rock (cave ceiling)

    # ------------------------------------------------------------------
    # 6. Limestone layer specification — progressive depth profile showing
    #    alternating limestone/dolomite bands exposed on the sinkhole walls.
    #    Each layer gets hardness, thickness, and a color-hint for the shader.
    # ------------------------------------------------------------------
    num_limestone_layers = max(3, int(depth / 1.8))
    limestone_layer_thickness = depth / max(num_limestone_layers, 1)
    limestone_layers: list[dict[str, Any]] = []
    _layer_rng = random.Random(seed + 9999)
    for li in range(num_limestone_layers):
        z_top_l = -li * limestone_layer_thickness
        z_bot_l = -(li + 1) * limestone_layer_thickness
        # Alternate hard limestone / softer dolomite
        layer_type = "limestone" if li % 2 == 0 else "dolomite"
        hardness = 0.80 if layer_type == "limestone" else 0.55
        thickness_var = limestone_layer_thickness * _layer_rng.uniform(0.8, 1.2)
        limestone_layers.append({
            "index": li,
            "z_top": z_top_l,
            "z_bottom": z_bot_l,
            "layer_type": layer_type,
            "hardness": hardness,
            "thickness": thickness_var,
            "color_hint": "cream_white" if layer_type == "limestone" else "tan_grey",
        })

    # Progressive depth profile — radius and material at each depth step
    depth_profile: list[dict[str, Any]] = []
    for k in range(depth_res + 1):
        kt = k / max(depth_res, 1)
        z_val = -kt * depth
        bell = math.exp(-((kt - undercut_peak) ** 2) / (2 * 0.08 ** 2))
        r_at_depth = radius + bell * undercut_amount - kt * radius * 0.18
        layer_idx = min(int(kt * num_limestone_layers), num_limestone_layers - 1)
        depth_profile.append({
            "z": z_val,
            "radius": r_at_depth,
            "layer_index": layer_idx,
        })

    # Cylindrical UVs for sinkhole: u = angle/(2π), v = normalised depth
    _sh_uvs = [
        (
            (math.atan2(float(v[1]), float(v[0])) / (2.0 * math.pi)) % 1.0,
            max(0.0, min(1.0, -float(v[2]) / max(depth, 1e-6))),
        )
        for v in vertices
    ]
    _sh_normals = _compute_face_normals(vertices, faces)
    return {
        "mesh": {"vertices": vertices, "faces": faces, "normals": _sh_normals},
        "uvs": _sh_uvs,
        "rim": {"radius": radius, "vertices": rim_verts},
        "cave": cave_info,
        "rubble": rubble,
        "base_water_level": base_z,
        "limestone_layers": limestone_layers,
        "depth_profile": depth_profile,
        "materials": materials,
        "material_indices": mat_indices,
        "material_metadata": _material_metadata(
            ("dirt_wall",      0.90, "sediment",  0.0),
            ("exposed_rock",   0.75, "limestone", 0.0),
            ("rubble",         0.85, "sediment",  0.0),
            ("cave_entrance",  0.80, "hard_rock", 0.0),
            ("rim_ground",     0.88, "sediment",  0.0),
        ),
        "dimensions": {
            "radius": radius,
            "depth": depth,
            "wall_roughness": wall_roughness,
            "rubble_density": rubble_density,
            "undercut_amount": undercut_amount,
            "lod": {
                "LOD_0": len(faces),
                "LOD_1": _lod1_faces(faces),
            },
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
            _ = ring_sizes_list[equator_ring]  # FIX-11-10: eq_size unused; shader handles vein tagging
            # Position in mat_indices: top_cap + sum of previous ring bands + eq band
            top_cap_faces = ring_sizes_list[0] if ring_starts else 0
            prev_band_faces = sum(ring_sizes_list[i] for i in range(equator_ring))
            _ = (len(mat_indices) - rock_end + rock_start  # FIX-11-10: eq_start_mi unused
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

        # -- Chain links: proper interlocking torus geometry --
        # Each link is a torus with major radius R (ring centre-to-centre) and
        # minor radius r (tube cross-section).  Adjacent links are rotated 90°
        # around the chain axis so they interlock — this is the defining
        # property of a real chain: even links lie in the XZ plane, odd links
        # lie in the YZ plane.
        #
        # Torus parametric form for a link centred at (cx, cy, cz) oriented
        # along its axis direction:
        #   For an axis-aligned torus:
        #     x(u, v) = (R + r·cos v) · cos u
        #     y(u, v) = (R + r·cos v) · sin u
        #     z(u, v) = r · sin v
        #   Rotating 90° around Z swaps x↔y, giving a torus in the XZ plane:
        #     x(u, v) = r · sin v
        #     y(u, v) = (R + r·cos v) · sin u   [same sin-u factor]
        #     z(u, v) = (R + r·cos v) · cos u
        #
        # Link spacing: link centres step by 2·R along the chain so the
        # inner edges of adjacent links just touch.
        if chain_links > 0:
            anchor_x = rock_x + rng.uniform(-0.4, 0.4)
            anchor_y = rock_y + rng.uniform(-0.4, 0.4)
            anchor_z = 0.0
            attach_z = rock_z - rock_half

            chain_span = attach_z - anchor_z
            # Torus geometry parameters
            # Major radius R: half of the link outer diameter.
            # Choose R so chain_links × (2·R) ≈ chain_span.
            torus_R = max(0.06, chain_span / max(chain_links * 2, 1))
            torus_r = torus_R * 0.30   # tube radius = 30% of ring radius
            # Resolution: 8 segments around the tube (v), 12 around the ring (u)
            TORUS_U = 12  # segments around the ring (u-loop)
            TORUS_V = 8   # segments around the tube cross-section (v-loop)

            chain_link_list: list[dict[str, Any]] = []

            for li in range(chain_links):
                # Centre Z of this link
                lz_center = anchor_z + (li + 0.5) * (chain_span / max(chain_links, 1))
                link_start = len(vertices)

                # Alternate orientation: even links lie in XY plane (axis = Z),
                # odd links lie in XZ plane (axis = Y) — produces 90° alternation
                # that is the visual signature of interlocking chain links.
                axis_is_z = (li % 2 == 0)

                for ui in range(TORUS_U):
                    u = 2.0 * math.pi * ui / TORUS_U
                    cos_u = math.cos(u)
                    sin_u = math.sin(u)
                    for vi in range(TORUS_V):
                        v = 2.0 * math.pi * vi / TORUS_V
                        cos_v = math.cos(v)
                        sin_v = math.sin(v)
                        ring_r = torus_R + torus_r * cos_v
                        if axis_is_z:
                            # Torus ring lies in XY plane, tube cross-section in XY+Z
                            vx = anchor_x + ring_r * cos_u
                            vy = anchor_y + ring_r * sin_u
                            vz = lz_center + torus_r * sin_v
                        else:
                            # Torus ring lies in XZ plane, tube cross-section in XZ+Y
                            vx = anchor_x + ring_r * cos_u
                            vy = anchor_y + torus_r * sin_v
                            vz = lz_center + ring_r * sin_u
                        vertices.append((vx, vy, vz))

                # Build quad faces for the torus surface
                for ui in range(TORUS_U):
                    ui_next = (ui + 1) % TORUS_U
                    for vi in range(TORUS_V):
                        vi_next = (vi + 1) % TORUS_V
                        v0 = link_start + ui * TORUS_V + vi
                        v1 = link_start + ui * TORUS_V + vi_next
                        v2 = link_start + ui_next * TORUS_V + vi_next
                        v3 = link_start + ui_next * TORUS_V + vi
                        faces.append((v0, v1, v2, v3))
                        mat_indices.append(3)  # chain_metal

                chain_link_list.append({
                    "position": (anchor_x, anchor_y, lz_center),
                    "torus_R": torus_R,
                    "torus_r": torus_r,
                    "axis": "z" if axis_is_z else "y",
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
        - "uvs": per-vertex (u, v) — planar cubemap-style projection.
          Column side faces: u=angle fraction (0..1), v=height fraction (0..1).
          Flat top cap facets: u,v are planar XY normalised coords.
          Wall and floor: u=X normalised, v=Z normalised.
        - "stalactites": list of stalactite dicts (tip_position, length, base_radius)
        - "columns": list of serac/column dicts (base_center, column_height, radius,
          crack_count) — hexagonal prism glacier seracs
        - "wall_info": dict with dimensions and refraction zones (if ice_wall)
        - "materials": list of material names
        - "material_indices": per-face material index list
        - "dimensions": dict
        - "vertex_count", "face_count"
    """
    rng = random.Random(seed)
    vertices: list[Vec3] = []
    uvs: list[tuple[float, float]] = []   # per-vertex (u, v) cubemap/planar
    faces: list[tuple[int, ...]] = []
    mat_indices: list[int] = []

    # Materials: 0=clear_ice, 1=frosted_ice, 2=blue_ice, 3=ice_wall_refraction,
    #            4=icicle_tip, 5=ice_crack, 6=deep_blue_green
    # deep_blue_green: oldest/densest ice, strongly absorbs red — deep teal subsurface.
    # Assigned to the lowest ~20% of columns and wall faces near the base.
    materials = ["clear_ice", "frosted_ice", "blue_ice", "ice_wall_refraction",
                 "icicle_tip", "ice_crack", "deep_blue_green"]

    half_w = width / 2.0
    half_d = depth / 2.0

    HEX_SEGS = 6   # hexagonal cross-section — standard ice crystal prism

    # ------------------------------------------------------------------
    # Helper: build one hexagonal prism column (glacier serac / ice column).
    # ------------------------------------------------------------------
    def _build_hex_column(
        cx: float, cy: float,
        col_r: float, col_h: float,
        base_z: float,
        col_rings: int,
        col_seed: int,
        crack_count: int,
    ) -> int:
        col_start = len(vertices)

        # Side walls: col_rings+1 rings from base to top
        for k in range(col_rings + 1):
            kt = k / max(col_rings, 1)
            ring_z = base_z + kt * col_h
            bulge = 1.0 + 0.08 * math.sin(kt * math.pi)
            ring_r = col_r * bulge
            fbm_r = _fbm(cx * 0.4 + kt * 1.8, cy * 0.4,
                         col_seed, octaves=3, lacunarity=2.0, gain=0.5)
            ring_r += fbm_r * col_r * 0.06

            for s in range(HEX_SEGS):
                # Flat hexagonal prism — exactly 60° increments, no per-ring twist
                s_angle = 2.0 * math.pi * s / HEX_SEGS
                v_noise = _hash_noise(s_angle * 3.0 + kt * 5.0,
                                      float(col_seed % 100), col_seed + s) * col_r * 0.04
                vx = cx + math.cos(s_angle) * (ring_r + v_noise)
                vy = cy + math.sin(s_angle) * (ring_r + v_noise)
                vertices.append((vx, vy, ring_z))
                uvs.append((s / HEX_SEGS, kt))

        # Side faces — flat quad panels with 4-zone depth colour:
        #   0.00–0.18 → deep_blue_green (ancient compressed ice, teal SSS)
        #   0.18–0.40 → frosted_ice     (surface re-crystallisation)
        #   0.40–0.72 → clear_ice       (transparent mid-column)
        #   0.72–1.00 → blue_ice        (dense upper crystal bands)
        for k in range(col_rings):
            for s in range(HEX_SEGS):
                s_next = (s + 1) % HEX_SEGS
                v0 = col_start + k * HEX_SEGS + s
                v1 = col_start + k * HEX_SEGS + s_next
                v2 = col_start + (k + 1) * HEX_SEGS + s_next
                v3 = col_start + (k + 1) * HEX_SEGS + s
                faces.append((v0, v1, v2, v3))
                kt_f = (k + 0.5) / max(col_rings, 1)
                if kt_f < 0.18:
                    mat_indices.append(6)   # deep_blue_green — basal compressed ice
                elif kt_f < 0.40:
                    mat_indices.append(1)   # frosted_ice
                elif kt_f < 0.72:
                    mat_indices.append(0)   # clear_ice
                else:
                    mat_indices.append(2)   # blue_ice

        # Top cap: angular flat facets — 6 triangles meeting at a raised peak.
        # Each facet is hard-edged (separate triangle) for angular ice refraction look.
        top_ring_start = col_start + col_rings * HEX_SEGS
        top_z = base_z + col_h
        peak_z = top_z + col_r * rng.uniform(0.08, 0.22)
        peak_noise_xy = _hash_noise(cx * 1.5, cy * 1.5, col_seed + 77) * col_r * 0.05
        peak_idx = len(vertices)
        vertices.append((cx + peak_noise_xy, cy + peak_noise_xy, peak_z))
        uvs.append((0.5, 0.5))

        for s in range(HEX_SEGS):
            s_next = (s + 1) % HEX_SEGS
            faces.append((top_ring_start + s, top_ring_start + s_next, peak_idx))
            mat_indices.append(0)

        # Random crack edge loops — narrow inset rings at random heights
        for ci in range(crack_count):
            crack_t = rng.uniform(0.15, 0.85)
            crack_ring_z = base_z + crack_t * col_h
            crack_inset = col_r * rng.uniform(0.06, 0.14)
            crack_z_dip = col_r * rng.uniform(0.02, 0.05)

            crack_ring_start = len(vertices)
            for s in range(HEX_SEGS):
                s_angle = 2.0 * math.pi * s / HEX_SEGS
                c_noise = _hash_noise(s_angle * 2.5, crack_t * 7.0, col_seed + ci * 17 + s) * col_r * 0.03
                vx = cx + math.cos(s_angle) * (col_r - crack_inset + c_noise)
                vy = cy + math.sin(s_angle) * (col_r - crack_inset + c_noise)
                vz = crack_ring_z - crack_z_dip + c_noise * 0.5
                vertices.append((vx, vy, vz))
                uvs.append((s / HEX_SEGS, crack_t))

            k_below = max(0, min(int(crack_t * col_rings), col_rings - 1))
            k_above = min(k_below + 1, col_rings)
            ring_below = col_start + k_below * HEX_SEGS
            ring_above = col_start + k_above * HEX_SEGS

            for s in range(HEX_SEGS):
                s_next = (s + 1) % HEX_SEGS
                cb = ring_below + s
                cb_n = ring_below + s_next
                cr = crack_ring_start + s
                cr_n = crack_ring_start + s_next
                ca = ring_above + s
                ca_n = ring_above + s_next
                faces.append((cb, cb_n, cr_n, cr))
                mat_indices.append(5)   # ice_crack
                faces.append((cr, cr_n, ca_n, ca))
                mat_indices.append(5)   # ice_crack

        return col_start

    # ------------------------------------------------------------------
    # A. Glacier seracs — hexagonal columns rising from the floor
    # ------------------------------------------------------------------
    num_columns = max(2, stalactite_count // 2)
    col_spacing = min(width, depth) / max(num_columns, 1) * 0.8
    columns: list[dict[str, Any]] = []

    for ci in range(num_columns):
        col_x = rng.uniform(-half_w * 0.85, half_w * 0.85)
        col_y = rng.uniform(-half_d * 0.85, half_d * 0.85)
        col_r = rng.uniform(0.2, min(0.7, col_spacing * 0.4))
        col_h = rng.uniform(height * 0.4, height * 0.95)
        crack_cnt = rng.randint(0, 3)
        col_rings = max(4, int(col_h * 3))

        col_start_idx = _build_hex_column(
            col_x, col_y, col_r, col_h, 0.0,
            col_rings, seed + ci * 113, crack_cnt,
        )
        columns.append({
            "base_center": (col_x, col_y, 0.0),
            "column_height": col_h,
            "radius": col_r,
            "crack_count": crack_cnt,
            "vertex_range_start": col_start_idx,
        })

    # ------------------------------------------------------------------
    # B. Ice stalactites — hanging from ceiling, 6-facet cross-section
    # ------------------------------------------------------------------
    stalactites: list[dict[str, Any]] = []
    for si in range(stalactite_count):
        sx = rng.uniform(-half_w * 0.9, half_w * 0.9)
        sy = rng.uniform(-half_d * 0.5, half_d * 0.5)
        stl_length = rng.uniform(height * 0.2, height * 0.8)
        stl_base_r = rng.uniform(0.1, 0.4)

        stalactites.append({
            "tip_position": (sx, sy, height - stl_length),
            "length": stl_length,
            "base_radius": stl_base_r,
        })

        cone_segments = 6   # hexagonal prism cross-section
        cone_rings = max(3, int(stl_length * 2))
        stl_start = len(vertices)

        for k in range(cone_rings):
            kt = k / max(cone_rings - 1, 1)
            ring_z = height - kt * stl_length

            if kt < 0.25:
                taper = 1.0 + 0.15 * math.sin(kt / 0.25 * math.pi)
            else:
                taper = 1.0 - (kt - 0.25) / 0.75 * 0.98
            ring_r = stl_base_r * max(taper, 0.02)

            fbm_disp = _fbm(sx * 0.5 + kt * 2.5, sy * 0.5 + k * 1.2,
                            seed + si * 7, octaves=3, lacunarity=2.0, gain=0.5)
            ring_r += fbm_disp * stl_base_r * 0.12

            for s in range(cone_segments):
                # Flat prism facets — no per-ring rotation so each face is a clean quad
                s_angle = 2.0 * math.pi * s / cone_segments
                noise = _hash_noise(s_angle * 2.0, kt * 4.0, seed + si * 11 + k) * ring_r * 0.05
                vx = sx + math.cos(s_angle) * (ring_r + noise)
                vy = sy + math.sin(s_angle) * (ring_r + noise)
                vertices.append((vx, vy, ring_z))
                uvs.append((s / cone_segments, 1.0 - kt))

        tip_idx = len(vertices)
        tip_noise_z = _hash_noise(sx * 2.0, sy * 2.0, seed + si * 13) * 0.04
        vertices.append((sx, sy, height - stl_length + tip_noise_z))
        uvs.append((0.5, 0.0))

        for k in range(cone_rings - 1):
            kt_face = k / max(cone_rings - 1, 1)
            for s in range(cone_segments):
                s_next = (s + 1) % cone_segments
                v0 = stl_start + k * cone_segments + s
                v1 = stl_start + k * cone_segments + s_next
                v2 = stl_start + (k + 1) * cone_segments + s_next
                v3 = stl_start + (k + 1) * cone_segments + s
                faces.append((v0, v1, v2, v3))
                if kt_face < 0.3:
                    mat_indices.append(1)
                elif kt_face > 0.7:
                    mat_indices.append(2)
                else:
                    mat_indices.append(0)

        last_ring_start = stl_start + (cone_rings - 1) * cone_segments
        for s in range(cone_segments):
            s_next = (s + 1) % cone_segments
            faces.append((last_ring_start + s, last_ring_start + s_next, tip_idx))
            mat_indices.append(4)

    # ------------------------------------------------------------------
    # C. Ice wall backdrop
    # ------------------------------------------------------------------
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
                y_base = half_d
                y_noise = _fbm(x * 0.3, z * 0.3, seed + 50, octaves=3) * 0.3
                y = y_base + y_noise
                vertices.append((x, y, z))
                uvs.append((ixt, kt))

        for k in range(wall_res_z - 1):
            for ix in range(wall_res_x - 1):
                v0 = wall_start + k * wall_res_x + ix
                v1 = v0 + 1
                v2 = v0 + wall_res_x + 1
                v3 = v0 + wall_res_x
                faces.append((v0, v1, v2, v3))
                x_center = -half_w + (ix + 0.5) / max(wall_res_x - 1, 1) * width
                z_center = (k + 0.5) / max(wall_res_z - 1, 1) * height
                zt_wall = z_center / max(height, 1e-6)
                curvature = abs(_fbm(x_center * 0.5, z_center * 0.5, seed + 60, octaves=2))
                # 3-zone depth colour for wall: base=deep_blue_green, mid=blue_ice
                # or ice_wall_refraction (where curvature high), upper=clear_ice/refraction
                if zt_wall < 0.20:
                    mat_indices.append(6)   # deep_blue_green basal band
                elif zt_wall < 0.55:
                    mat_indices.append(3 if curvature > 0.3 else 2)  # refraction / blue_ice
                else:
                    mat_indices.append(3 if curvature > 0.3 else 0)  # refraction / clear_ice

        num_zones = rng.randint(2, 5)
        for zi in range(num_zones):
            zx = rng.uniform(-half_w * 0.7, half_w * 0.7)
            zz = rng.uniform(height * 0.1, height * 0.9)
            z_radius = rng.uniform(0.5, 1.5)
            refraction_zones.append({"center": (zx, half_d, zz), "radius": z_radius})

        wall_info = {
            "width": width,
            "height": height,
            "y_position": half_d,
            "refraction_zones": refraction_zones,
        }

    # ------------------------------------------------------------------
    # D. Voronoi crack pattern on ice surface (metadata — no extra geometry).
    #    We distribute N crack seed points across the XY plane and record
    #    them so the shader/renderer can draw Voronoi cell boundaries as
    #    darkened cracks in the ice surface.
    # ------------------------------------------------------------------
    voronoi_crack_seeds: list[dict[str, Any]] = []
    num_voronoi_cells = max(6, stalactite_count + 4)
    _vcr = random.Random(seed + 7777)
    for vi in range(num_voronoi_cells):
        vox = _vcr.uniform(-half_w, half_w)
        voy = _vcr.uniform(-half_d, half_d)
        voz = _vcr.uniform(0.0, height)
        crack_width = _vcr.uniform(0.005, 0.025)
        voronoi_crack_seeds.append({
            "seed_point": (vox, voy, voz),
            "crack_width": crack_width,
            "depth_fraction": _vcr.uniform(0.02, 0.10),
        })

    # Translucency metadata — per-material IOR and scattering hints.
    # deep_blue_green: ancient compressed ice strongly absorbs red/green wavelengths,
    # leaving a teal-blue transmission.  High scatter_depth drives SSS teal glow.
    translucency_metadata = {
        "clear_ice":          {"ior": 1.31, "absorption": 0.08, "scatter_depth": 0.4},
        "frosted_ice":        {"ior": 1.31, "absorption": 0.20, "scatter_depth": 0.1},
        "blue_ice":           {"ior": 1.31, "absorption": 0.05, "scatter_depth": 0.9},
        "ice_wall_refraction":{"ior": 1.31, "absorption": 0.12, "scatter_depth": 0.6},
        "icicle_tip":         {"ior": 1.31, "absorption": 0.03, "scatter_depth": 1.2},
        "ice_crack":          {"ior": 1.00, "absorption": 0.80, "scatter_depth": 0.0},
        "deep_blue_green":    {"ior": 1.31, "absorption": 0.02, "scatter_depth": 1.8,
                               "color_hint": (0.05, 0.45, 0.55)},
    }

    _ice_normals = _compute_face_normals(vertices, faces)
    return {
        "mesh": {"vertices": vertices, "faces": faces, "normals": _ice_normals},
        "uvs": uvs,
        "stalactites": stalactites,
        "columns": columns,
        "wall_info": wall_info,
        "voronoi_crack_seeds": voronoi_crack_seeds,
        "translucency_metadata": translucency_metadata,
        "materials": materials,
        "material_indices": mat_indices,
        "material_metadata": _material_metadata(
            ("clear_ice",           0.05, "ice",    0.0),
            ("frosted_ice",         0.30, "ice",    0.0),
            ("blue_ice",            0.08, "ice",    0.0),
            ("ice_wall_refraction", 0.10, "ice",    0.0),
            ("icicle_tip",          0.03, "ice",    0.0),
            ("ice_crack",           0.70, "ice",    0.0),
            ("deep_blue_green",     0.04, "ice",    0.0),
        ),
        "dimensions": {
            "width": width,
            "height": height,
            "depth": depth,
            "stalactite_count": stalactite_count,
            "ice_wall": ice_wall,
            "lod": {
                "LOD_0": len(faces),
                "LOD_1": _lod1_faces(faces),
            },
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
    flow_type: str = "pahoehoe",
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
    #            4=levee_crust, 5=flow_front, 6=aa_clinker, 7=embankment_face
    # aa_clinker: spiny clinker surface unique to aa flows (rough, angular, dark).
    # embankment_face: vertical step-drop at flow edge where lava overrode the ground.
    materials = ["hot_lava", "cooling_crust", "solid_rock", "ember_glow",
                 "levee_crust", "flow_front", "aa_clinker", "embankment_face"]

    # Aa lava: high-amplitude jagged clinker surface, no ropy ridges.
    # Pahoehoe lava: smooth ropy fBm ridges across the channel.
    _is_aa = flow_type.lower().startswith("aa")

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
            nx2, ny2, _ = cl_points[i + 1]  # FIX-11-10: nz2 unused
        else:
            nx2, ny2, _ = cx, cy, cz  # FIX-11-10: nz2 unused
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
            _ = 1.0 if offset >= 0.0 else -1.0  # FIX-11-10: side unused; sign carried by offset

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

            # Surface texture: pahoehoe = ropy fBm ridges; aa = jagged clinker
            if _is_aa:
                if dist < half_w + edge_crust_width:
                    # Aa clinker: high-freq, high-amplitude jagged noise
                    ropy = (
                        _fbm(cx * 0.35 + offset * 1.2, offset * 1.5 + float(i) * 0.5,
                             seed + 20, octaves=5, lacunarity=2.5, gain=0.60) * 0.28
                        + _hash_noise(cx * 0.8 + offset * 2.0, float(i) * 1.2, seed + 22) * 0.12
                    )
                else:
                    ropy = _hash_noise(cx * 0.2 + offset * 0.3, offset * 0.2, seed + 21) * 0.06
            else:
                if dist < half_w + edge_crust_width:
                    # Pahoehoe ropy texture: smooth fBm ridges
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
                # Aa: clinker surface; pahoehoe: cooling crust
                mat_indices.append(6 if _is_aa else 1)
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
    # 3b. Flow edge embankment discontinuity — vertical step-drop faces at
    #     both sides of the flow where the lava overrode the surrounding ground.
    #     Aa flows have sharp near-vertical embankment edges (~60–80°); pahoehoe
    #     edges are slightly less steep but still distinctly discontinuous.
    #     Geometry: one quad strip per side, spanning the full flow length,
    #     dropping from the outer levee base height to ground level (z=0).
    # ------------------------------------------------------------------
    embankment_drop_h = levee_height + 0.25   # total drop of the embankment face
    embank_slope_frac = 0.15 if _is_aa else 0.35  # aa=near-vertical, paho=gentler

    for emb_sign in (-1.0, 1.0):
        emb_start = len(vertices)
        # Two rows: top row (outer levee base height) and bottom row (ground)
        for row in range(2):
            row_z_frac = 0.0 if row == 0 else -embankment_drop_h
            for i, (cx, cy, cz) in enumerate(cl_points):
                # Perpendicular direction at this cross-section
                if i < flow_segments:
                    nx2, ny2, _ = cl_points[i + 1]
                else:
                    nx2, ny2 = cx + (cx - cl_points[i-1][0]), cy + (cy - cl_points[i-1][1])
                tdx_e2 = nx2 - cx
                tdy_e2 = ny2 - cy
                tlen_e2 = math.hypot(tdx_e2, tdy_e2)  # FIX-11-6
                if tlen_e2 > 1e-9:
                    px_e = -tdy_e2 / tlen_e2
                    py_e = tdx_e2 / tlen_e2
                else:
                    px_e, py_e = 0.0, 1.0

                emb_r = rock_edge_outer + emb_sign * embank_slope_frac * row
                emb_x = cx + emb_sign * px_e * emb_r
                emb_y = cy + emb_sign * py_e * emb_r
                emb_z = cz + row_z_frac
                noise_emb = _hash_noise(emb_x * 0.2, emb_z * 0.3, seed + 500) * 0.04
                vertices.append((emb_x + noise_emb, emb_y + noise_emb, emb_z))

        # Faces: top_row=rows 0..(flow_segments), bot_row=rows (fs+1)..(2*fs+1)
        top_start = emb_start
        bot_start = emb_start + (flow_segments + 1)
        for i in range(flow_segments):
            v0 = top_start + i
            v1 = top_start + i + 1
            v2 = bot_start + i + 1
            v3 = bot_start + i
            if emb_sign > 0:
                faces.append((v0, v1, v2, v3))
            else:
                faces.append((v0, v3, v2, v1))
            mat_indices.append(7)   # embankment_face

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

    # ------------------------------------------------------------------
    # 6. Voronoi cooling crack pattern (metadata — shader-driven geometry).
    #    Seed points distributed across the flow surface; the renderer draws
    #    Voronoi cell boundaries as dark crack lines in the cooling crust.
    #    Each seed carries a temperature hint (hotter = wider crack glows).
    # ------------------------------------------------------------------
    num_voronoi_cells = max(8, flow_segments * 2)
    voronoi_cooling_cracks: list[dict[str, Any]] = []
    _vcr2 = random.Random(seed + 4444)
    for vi in range(num_voronoi_cells):
        t_along = _vcr2.random()
        seg_idx = int(t_along * flow_segments)
        cx_v, cy_v, cz_v = cl_points[min(seg_idx, len(cl_points) - 1)]
        lat_offset = _vcr2.uniform(-(width / 2.0 + edge_crust_width),
                                    width / 2.0 + edge_crust_width)
        temperature = max(0.0, 1.0 - t_along * 0.7)
        crack_width = 0.02 + (1.0 - temperature) * 0.06
        voronoi_cooling_cracks.append({
            "seed_point": (cx_v + lat_offset * 0.3, cy_v + lat_offset * 0.3, cz_v),
            "temperature": temperature,
            "crack_width": crack_width,
            "glow_emission": temperature * 0.85,   # hotter cracks glow more
        })

    # Ropy pahoehoe ridge spec (vertex-level procedural detail hint)
    pahoehoe_spec = {
        "ridge_amplitude": 0.10,
        "ridge_frequency": 1.8,
        "ridge_octaves": 4,
        "seed": seed + 20,
        "affected_zone_half_width": width / 2.0 + edge_crust_width,
    }

    # Triplanar XZ UVs for lava: u = x/length (flow direction), v = y/total_width (cross)
    _lv_uvs = [
        (
            max(0.0, min(1.0, float(v[0]) / max(length, 1e-6))),
            max(0.0, min(1.0, (float(v[1]) + rock_edge_outer) / max(2.0 * rock_edge_outer, 1e-6))),
        )
        for v in vertices
    ]
    _lv_normals = _compute_face_normals(vertices, faces)
    return {
        "mesh": {"vertices": vertices, "faces": faces, "normals": _lv_normals},
        "uvs": _lv_uvs,
        "flow_path": flow_path,
        "flow_front": flow_front_verts,
        "levee_specs": levee_specs,
        "heat_zones": heat_zones,
        "voronoi_cooling_cracks": voronoi_cooling_cracks,
        "pahoehoe_spec": pahoehoe_spec,
        "materials": materials,
        "material_indices": mat_indices,
        "material_metadata": _material_metadata(
            ("hot_lava",         0.10, "lava",        1.00),
            ("cooling_crust",    0.70, "lava_crust",  0.20),
            ("solid_rock",       0.88, "basalt",      0.00),
            ("ember_glow",       0.15, "lava",        0.60),
            ("levee_crust",      0.75, "lava_crust",  0.10),
            ("flow_front",       0.40, "lava_crust",  0.35),
            ("aa_clinker",       0.92, "basalt",      0.00),
            ("embankment_face",  0.80, "basalt",      0.00),
        ),
        "dimensions": {
            "length": length,
            "width": width,
            "edge_crust_width": edge_crust_width,
            "flow_segments": flow_segments,
            "slope_angle_deg": slope_angle_deg,
            "levee_height": levee_height,
            "flow_type": flow_type,
            "lod": {
                "LOD_0": len(faces),
                "LOD_1": _lod1_faces(faces),
            },
        },
        "vertex_count": len(vertices),
        "face_count": len(faces),
    }


_PASS_FEATURE_GENERATORS = {
    "canyon": generate_canyon,
    "waterfall": generate_waterfall,
    "cliff": generate_cliff_face,
    "cliff_face": generate_cliff_face,
    "swamp": generate_swamp_terrain,
    "natural_arch": generate_natural_arch,
    "arch": generate_natural_arch,
    "geyser": generate_geyser,
    "sinkhole": generate_sinkhole,
    "floating_rocks": generate_floating_rocks,
    "ice_formation": generate_ice_formation,
    "lava_flow": generate_lava_flow,
}


def pass_terrain_features(
    state: TerrainPipelineState,
    region: BBox | None,
) -> PassResult:
    """Generate authored terrain feature mesh specs through the pass graph."""
    t0 = time.perf_counter()
    hints = dict(getattr(state.intent, "composition_hints", {}) or {})
    raw_specs = hints.get("terrain_feature_specs")
    if raw_specs is None:
        raw_specs = [
            {
                "kind": getattr(feature, "feature_kind", ""),
                "id": getattr(feature, "feature_id", ""),
            }
            for feature in getattr(state.intent, "hero_feature_specs", ()) or ()
        ]

    mesh_specs: list[dict[str, Any]] = []
    skipped: list[str] = []
    seed = int(getattr(state.intent, "seed", 0))
    for idx, raw in enumerate(raw_specs or ()):
        if isinstance(raw, str):
            kind = raw
            params: dict[str, Any] = {}
            feature_id = f"{kind}_{idx}"
        elif isinstance(raw, dict):
            kind = str(raw.get("kind") or raw.get("feature_kind") or raw.get("type") or "")
            params = dict(raw.get("params") or {})
            feature_id = str(raw.get("id") or raw.get("feature_id") or f"{kind}_{idx}")
        else:
            continue
        generator = _PASS_FEATURE_GENERATORS.get(kind)
        if generator is None:
            if kind:
                skipped.append(kind)
            continue
        params.setdefault("seed", seed + idx)
        spec = generator(**params)
        spec["feature_id"] = feature_id
        spec["feature_kind"] = kind
        mesh_specs.append(spec)

    state.mask_stack.set("terrain_feature_mesh_specs", mesh_specs, "pass_terrain_features")
    return PassResult(
        pass_name="pass_terrain_features",
        status="ok" if not skipped else "warning",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=("terrain_feature_mesh_specs",),
        metrics={
            "feature_mesh_count": len(mesh_specs),
            "skipped_feature_count": len(skipped),
            "region_scoped": region is not None,
        },
    )


def register_terrain_features_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_terrain_features",
            func=pass_terrain_features,
            requires_channels=("height",),
            produces_channels=("terrain_feature_mesh_specs",),
            seed_namespace="pass_terrain_features",
            requires_scene_read=False,
            description="Bundle terrain features: authored mesh spec generation for hero terrain props.",
        )
    )


# ---------------------------------------------------------------------------
# FIX-13-18: Biome grammar height-modifying features wired as a pipeline pass
# ---------------------------------------------------------------------------

# Maps composition_hints kind key → _biome_grammar function name.
# Height-mutating functions: return a modified heightmap (or (heightmap, extra)).
_BIOME_GRAMMAR_KIND_MAP: dict[str, str] = {
    "periglacial":       "apply_periglacial_patterns",
    "desert_pavement":   "apply_desert_pavement",
    "landslide_scars":   "apply_landslide_scars",
    "hot_spring":        "apply_hot_spring_features",
    "reef_platform":     "apply_reef_platform",
    "tafoni":            "apply_tafoni_weathering",
    "geological_folds":  "apply_geological_folds",
}

# Mask-producing functions: return a (H,W) float mask stored as a stack channel.
# These do NOT modify the heightmap.
_BIOME_GRAMMAR_MASK_MAP: dict[str, str] = {
    "spring_line_mask":  "compute_spring_line_mask",
}


def pass_biome_grammar_features(
    state: TerrainPipelineState,
    region: Any,
) -> PassResult:
    """Apply biome-grammar height-modifying features (periglacial, tafoni, etc.).

    Contract
    --------
    Consumes : height
    Produces : height (modified in-place), hot_spring_locations (optional),
               spring_line_mask (optional side-channel mask)

    Triggered by ``composition_hints["biome_grammar_features"]``:
        a list of dicts each with ``kind`` (str) and optional ``params`` (dict).

    Height-mutating kinds (modify heightmap):
        periglacial, desert_pavement, landslide_scars, hot_spring,
        reef_platform, tafoni, geological_folds.

    Mask-producing kinds (stored as stack channels, do not modify height):
        spring_line_mask  — calls compute_spring_line_mask, stores result
                            on stack as ``spring_line_mask`` channel.
    """
    import numpy as np
    from . import _biome_grammar as _bg

    t0 = time.perf_counter()
    stack = state.mask_stack
    hints = dict(getattr(state.intent, "composition_hints", {}) or {})
    feature_specs = hints.get("biome_grammar_features") or []

    if not feature_specs:
        return PassResult(
            pass_name="pass_biome_grammar_features",
            status="ok",
            duration_seconds=time.perf_counter() - t0,
            consumed_channels=("height",),
            produced_channels=(),
            metrics={"features_applied": 0},
        )

    height = np.asarray(stack.height, dtype=np.float64)
    base_seed = int(getattr(state.intent, "seed", 0))
    applied: list[str] = []
    skipped: list[str] = []
    hot_spring_locations: list[dict] = []
    spring_line_masks: list[Any] = []

    for idx, spec in enumerate(feature_specs):
        if isinstance(spec, str):
            kind, kparams = spec, {}
        elif isinstance(spec, dict):
            kind = str(spec.get("kind") or "")
            kparams = dict(spec.get("params") or {})
        else:
            continue

        kparams.setdefault("seed", base_seed + idx)

        # ── mask-producing branch ────────────────────────────────────────────
        mask_fn_name = _BIOME_GRAMMAR_MASK_MAP.get(kind)
        if mask_fn_name is not None:
            mask_fn = getattr(_bg, mask_fn_name, None)
            if mask_fn is None:
                skipped.append(kind)
                continue
            try:
                # compute_spring_line_mask(heightmap, geology_layers, seed)
                mask_result = mask_fn(height, **kparams)
            except Exception:
                skipped.append(kind)
                continue
            spring_line_masks.append(np.asarray(mask_result, dtype=np.float32))
            applied.append(kind)
            continue

        # ── height-mutating branch ───────────────────────────────────────────
        fn_name = _BIOME_GRAMMAR_KIND_MAP.get(kind)
        if fn_name is None:
            skipped.append(kind)
            continue

        fn = getattr(_bg, fn_name, None)
        if fn is None:
            skipped.append(kind)
            continue

        try:
            result = fn(height, **kparams)
        except Exception:
            skipped.append(kind)
            continue

        if isinstance(result, tuple):
            # apply_desert_pavement returns (heightmap, pavement_mask)
            # apply_hot_spring_features returns (heightmap, spring_list)
            height = result[0]
            if len(result) > 1:
                extra = result[1]
                if isinstance(extra, list):
                    hot_spring_locations.extend(extra)
        else:
            height = result

        applied.append(kind)

    stack.set("height", height, "pass_biome_grammar_features")
    if hot_spring_locations:
        stack.set("hot_spring_locations", hot_spring_locations, "pass_biome_grammar_features")

    # Merge accumulated spring-line masks (max-blend) and store as a channel.
    if spring_line_masks:
        import numpy as _np
        merged_mask = spring_line_masks[0].copy()
        for m in spring_line_masks[1:]:
            _np.maximum(merged_mask, m, out=merged_mask)
        stack.set("spring_line_mask", merged_mask, "pass_biome_grammar_features")

    produced_list = ["height"]
    if hot_spring_locations:
        produced_list.append("hot_spring_locations")
    if spring_line_masks:
        produced_list.append("spring_line_mask")
    produced = tuple(produced_list)

    return PassResult(
        pass_name="pass_biome_grammar_features",
        status="ok" if not skipped else "warning",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height",),
        produced_channels=produced,
        metrics={
            "features_applied": len(applied),
            "features_skipped": len(skipped),
            "applied_kinds": applied,
            "hot_spring_count": len(hot_spring_locations),
            "spring_line_mask_computed": len(spring_line_masks) > 0,
        },
    )


def register_biome_grammar_features_pass() -> None:
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="pass_biome_grammar_features",
            func=pass_biome_grammar_features,
            requires_channels=("height",),
            produces_channels=("height",),
            overrides=("height",),
            seed_namespace="biome_grammar_features",
            requires_scene_read=False,
            may_modify_geometry=True,
            respects_protected_zones=False,
            protocol_enforced=True,
            protocol_require_rule_5=True,
            protocol_bulk_edit=True,
            description="FIX-13-18: biome grammar height features (periglacial, tafoni, geological folds, etc.).",
        )
    )
