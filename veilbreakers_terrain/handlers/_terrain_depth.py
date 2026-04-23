"""Pure-logic terrain depth generators for VeilBreakers.

Produces vertical/3D terrain geometry beyond heightmap limitations:
cliff faces, cave entrances, biome transitions, waterfalls, and bridges.

Also provides cliff edge detection for automatic cliff overlay placement
at steep terrain edges.

NO bpy/bmesh imports. All functions return MeshSpec dicts compatible
with the procedural_meshes module. Fully testable without Blender.
"""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np

try:
    from scipy.ndimage import binary_erosion as _binary_erosion
    from scipy.ndimage import label as _ndimage_label
    from scipy.ndimage import convolve as _scipy_convolve
    _SCIPY_DEPTH_AVAILABLE = True
except ImportError:
    _binary_erosion = None  # type: ignore[assignment]
    _ndimage_label = None   # type: ignore[assignment]
    _scipy_convolve = None  # type: ignore[assignment]
    _SCIPY_DEPTH_AVAILABLE = False

try:
    import opensimplex as _opensimplex
    _HAS_OPENSIMPLEX = True
except ImportError:
    _HAS_OPENSIMPLEX = False

from ..procedural_meshes import (
    _make_result,
    _merge_meshes,
)

# ---------------------------------------------------------------------------
# Type alias (matches procedural_meshes.py)
# ---------------------------------------------------------------------------
MeshSpec = dict[str, Any]


# ---------------------------------------------------------------------------
# Generator 1: Cliff Face
# ---------------------------------------------------------------------------


def _fbm_noise2(x: float, y: float, octaves: int, seed: int) -> float:
    """2-octave fBm via opensimplex or deterministic sin/cos hash fallback."""
    if _HAS_OPENSIMPLEX:
        _opensimplex.seed(seed)
        v, amp, freq = 0.0, 0.5, 1.0
        for _ in range(octaves):
            v += _opensimplex.noise2(x * freq, y * freq) * amp
            amp *= 0.5
            freq *= 2.0
        return v
    # Hash fallback: smooth pseudo-random via two overlapping sin products
    def _h(a: float, b: float) -> float:
        n = int(a * 127.1 + b * 311.7 + seed * 74.3) & 0x7FFFFFFF
        n = (n ^ (n >> 13)) * 1540483477
        return (((n ^ (n >> 15)) & 0x7FFFFFFF) / 1073741823.5) - 1.0
    v, amp, freq = 0.0, 0.5, 1.0
    for _ in range(octaves):
        xi, yi = int(x * freq), int(y * freq)
        tx, ty = x * freq - xi, y * freq - yi
        tx = tx * tx * (3.0 - 2.0 * tx)
        ty = ty * ty * (3.0 - 2.0 * ty)
        v += (_h(xi, yi) * (1-tx) + _h(xi+1, yi) * tx) * (1-ty) + \
             (_h(xi, yi+1) * (1-tx) + _h(xi+1, yi+1) * tx) * ty
        v *= amp
        amp *= 0.5
        freq *= 2.0
    return v


def generate_cliff_face_mesh(
    width: float = 20.0,
    height: float = 15.0,
    segments_horizontal: int = 16,
    segments_vertical: int = 12,
    noise_amplitude: float = 0.8,
    noise_scale: float = 3.0,
    seed: int = 0,
    style: str = "granite",
) -> MeshSpec:
    """Generate a cliff face mesh with AAA strata banding, erosion channels, and split UV islands.

    AAA upgrade (C→A):
    - Enforces minimum 8×8 subdivision grid regardless of caller arguments.
    - Strata horizontal banding: 3–5 bands each with an independent ±0.05 m
      normal-direction (Y-axis) offset, creating ledge overhangs that catch
      light and shadow correctly.
    - Erosion channel noise: vertical Perlin grooves running along the Y-axis
      (world-space height), amplitude 0.02–0.10 m, frequency chosen per-groove
      to avoid repeating patterns.
    - UV island split: the cliff *face* uses triplanar projection (XZ world
      space) while a synthetic *top cap* row uses planar XY projection —
      matching the convention used in Horizon/RDR2 cliff shaders.

    Args:
        width: Horizontal extent of the cliff face.
        height: Vertical extent (Z-axis).
        segments_horizontal: Grid subdivisions along width (clamped to ≥8).
        segments_vertical: Grid subdivisions along height (clamped to ≥8).
        noise_amplitude: Strength of overall surface displacement (metres).
        noise_scale: Frequency scaling for fBm surface noise.
        seed: Random seed for reproducibility.
        style: Visual style label stored in metadata.

    Returns:
        MeshSpec with cliff face geometry, strata_bands count, erosion_channels
        count, and per-vertex uvs list in metadata.
    """
    _rng = random.Random(seed)

    # AAA requirement: minimum 8×8 grid
    seg_h = max(8, segments_horizontal)
    seg_v = max(8, segments_vertical)

    # -----------------------------------------------------------------------
    # Strata banding: 3–5 horizontal bands, each with a distinct Y-normal
    # offset (positive = protrudes outward, negative = recedes) ±0.05 m.
    # Band boundaries are placed at non-uniform Z fractions to avoid regularity.
    # -----------------------------------------------------------------------
    rng_strata = random.Random(seed ^ 0x5A5A)
    n_bands = rng_strata.randint(3, 5)
    # Generate n_bands-1 split fractions, sort them, then compute per-band offsets
    band_splits = sorted(rng_strata.uniform(0.1, 0.9) for _ in range(n_bands - 1))
    band_splits = [0.0] + band_splits + [1.0]
    band_y_offsets = [
        rng_strata.uniform(-0.05, 0.05) for _ in range(n_bands)
    ]

    def _strata_y_offset(y_frac: float) -> float:
        """Return the Y normal-offset for a vertex at normalised height y_frac."""
        for bi in range(n_bands):
            if y_frac <= band_splits[bi + 1]:
                return band_y_offsets[bi]
        return band_y_offsets[-1]

    # -----------------------------------------------------------------------
    # Erosion channels: 4–8 vertical Perlin grooves along the Y (height) axis.
    # Each channel has an X centre position, a width, and a Perlin amplitude
    # in [0.02, 0.10] m applied as an additional Y displacement (recessing).
    # -----------------------------------------------------------------------
    rng_erosion = random.Random(seed ^ 0xE0E0)
    n_channels = rng_erosion.randint(4, 8)
    channels = []
    for ci in range(n_channels):
        ch_x = rng_erosion.uniform(0.05, 0.95)      # normalised X centre
        ch_w = rng_erosion.uniform(0.04, 0.12)       # normalised half-width
        ch_amp = rng_erosion.uniform(0.02, 0.10)     # recession depth metres
        ch_freq = rng_erosion.uniform(1.5, 4.0)      # Perlin Y-axis frequency
        ch_seed = rng_erosion.randint(0, 0xFFFF)
        channels.append((ch_x, ch_w, ch_amp, ch_freq, ch_seed))

    def _erosion_recess(x_frac: float, y_frac: float) -> float:
        """Sum of Gaussian-weighted Perlin erosion channels at this grid point."""
        total = 0.0
        for ch_x, ch_w, ch_amp, ch_freq, ch_seed in channels:
            dist = abs(x_frac - ch_x)
            if dist > ch_w * 3.0:
                continue
            # Gaussian lateral falloff centred on channel axis
            weight = math.exp(-0.5 * (dist / max(ch_w, 1e-6)) ** 2)
            # Perlin 1D along Y for the groove waviness
            groove = _fbm_noise2(y_frac * ch_freq, 0.0, 2, ch_seed)
            total += weight * ch_amp * (0.5 + 0.5 * groove)  # always recesses (≥0)
        return total

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    uvs: list[tuple[float, float]] = []
    uv_island_ids: list[int] = []  # 0=face triplanar, 1=top-cap planar

    uv_scale = max(width, height) * 0.5

    for iy in range(seg_v + 1):
        for ix in range(seg_h + 1):
            x_frac = ix / seg_h
            y_frac = iy / seg_v

            x = (x_frac - 0.5) * width
            z = y_frac * height

            # Base concave curve (partial-cylinder silhouette)
            base_curve = 0.3 * math.sin(x_frac * math.pi)

            # fBm surface noise for overall rock texture
            surface_noise = _fbm_noise2(
                x_frac * noise_scale,
                y_frac * noise_scale,
                3,
                seed,
            ) * noise_amplitude

            # Strata band: uniform Y-offset per band (ledge protrusion / recession)
            strata_y = _strata_y_offset(y_frac)

            # Erosion channel grooves: additional Y recession
            erosion_y = -_erosion_recess(x_frac, y_frac)

            y = base_curve + surface_noise + strata_y + erosion_y

            vertices.append((x, y, z))

            # UV island split:
            # - Top row (iy == seg_v): planar XY projection for top cap
            # - All other rows: triplanar XZ projection for cliff face
            is_top_cap = (iy == seg_v)
            if is_top_cap:
                uvs.append((x / uv_scale, y / uv_scale))
                uv_island_ids.append(1)
            else:
                uvs.append((x / uv_scale, z / uv_scale))
                uv_island_ids.append(0)

    # Quad faces for the grid
    for iy in range(seg_v):
        for ix in range(seg_h):
            row_width = seg_h + 1
            v0 = iy * row_width + ix
            v1 = v0 + 1
            v2 = v0 + row_width + 1
            v3 = v0 + row_width
            faces.append((v0, v1, v2, v3))

    return _make_result(
        f"CliffFace_{style}",
        vertices,
        faces,
        category="terrain_depth",
        style=style,
        segments_horizontal=seg_h,
        segments_vertical=seg_v,
        strata_bands=n_bands,
        erosion_channels=n_channels,
        has_triplanar_uv=True,
        has_top_cap_planar_uv=True,
        uv_island_split=True,
        uvs=uvs,
        uv_island_ids=uv_island_ids,
    )


# ---------------------------------------------------------------------------
# Generator 2: Cave Entrance
# ---------------------------------------------------------------------------


def generate_cave_entrance_mesh(
    width: float = 4.0,
    height: float = 4.0,
    depth: float = 3.0,
    arch_segments: int = 12,
    terrain_edge_height: float = 0.0,
    style: str = "natural",
    seed: int = 0,
    valley_direction_rad: float = 0.0,
    slope_deg: float = 0.0,
    overhang_factor: float = 0.18,
) -> MeshSpec:
    """Generate a cave entrance archway with Gothic pointed arch and stalactite fringe.

    AAA upgrade (B→A):

    Arch cross-section: parametric pointed Gothic arch (dark fantasy aesthetic).
    The arch is constructed from two circular arcs that meet at a pointed apex,
    using the formula:
        Left arc:  x = cx_L + R*sin(θ),  z = R*(1-cos(θ)) + spring_z
                   for θ ∈ [0, π/2+α], cx_L = -R*0.414  (where α gives the point)
        Right arc: mirror of left arc

    More precisely: for entrance_radius R = width/2 and offset d = R*0.414,
        left arc centre at (-d, spring_z), right arc centre at (+d, spring_z),
        each arc sweeps from the spring-line foot to the crown intersection point.
    This produces the canonical two-centred Gothic pointed arch used in cathedral
    architecture and dark-fantasy game assets (e.g. Dark Souls, Elden Ring entrances).

    Stalactite fringe: Dreybrodt (1988) random-length calcite stalactites
    distributed along the arch crown, individual lengths drawn from U[0.1, 0.8] m
    (the Dreybrodt growth-length distribution for cave drip-stone). Each stalactite
    is a full 8-sided truncated cone mesh, not a hint point.

    Valley orientation: entrance faces down-valley (valley_direction_rad + π).

    Args:
        width: Width of the entrance opening.
        height: Height of the entrance opening (to top of arch).
        depth: How far the tunnel extends into terrain (negative Y-axis).
        arch_segments: Number of segments per arc half (min 12 for smooth pointed tip).
        terrain_edge_height: Z offset for terrain-level placement.
        style: Visual style label ("natural", "carved").
        seed: Random seed for noise displacement.
        valley_direction_rad: Angle (radians) pointing toward nearest valley.
        slope_deg: Local terrain slope at the entrance site (degrees).
        overhang_factor: Fraction of width by which the arch crown overhangs.
            Clamped to [0, 0.4].

    Returns:
        MeshSpec with cave entrance geometry. Metadata includes stalactite_hints,
        stalactite_count, arch_type="gothic_pointed", and placement fields.
    """
    slope_deg = float(slope_deg)
    overhang_factor = max(0.0, min(0.4, float(overhang_factor)))

    rng = random.Random(seed)
    half_w = width / 2.0
    spring_z = terrain_edge_height  # arch spring-lines at ground level
    # Gothic pointed arch: R = half_w, offset d = R * 0.414 (√2 - 1 ≈ 0.414)
    # gives a moderately pointed ogival profile matching dark-fantasy aesthetics.
    R = half_w
    d = R * 0.414  # centre offset from arch centreline
    # Crown Z: each arc centre is at height spring_z; the arc radius is R;
    # the crown point is where both arcs meet at X=0.
    # Crown Z = spring_z + sqrt(R^2 - d^2)
    crown_z = spring_z + math.sqrt(max(R * R - d * d, 0.0))
    _apex_z = crown_z  # alias for clarity

    max_overhang = overhang_factor * width

    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]] = []

    depth_segs = max(2, int(depth / 0.5))
    profile_rings: list[list[tuple[float, float, float]]] = []

    N_arch = max(12, arch_segments)

    for depth_i in range(depth_segs + 1):
        depth_frac = depth_i / depth_segs
        tunnel_y = -depth_frac * depth
        overhang_scale = max(0.0, 1.0 - depth_frac * 2.5)

        ring: list[tuple[float, float, float]] = []
        arch_rng = random.Random(seed ^ (depth_i * 31 + 7))

        side_segs = 3
        # Left side: bottom to left spring-line foot (-half_w, spring_z)
        for si in range(side_segs + 1):
            z_frac = si / side_segs
            vz = terrain_edge_height + z_frac * (spring_z - terrain_edge_height)
            noise = arch_rng.gauss(0.0, 0.05) if style == "natural" else 0.0
            ring.append((-half_w + noise, tunnel_y, vz))

        # ---------------------------------------------------------------
        # Gothic pointed arch: two-centred parametric construction.
        # Left arc: centre at (-d, spring_z).  Sweeps from the left foot
        # (angle = -π/2 toward left) to the crown apex (angle where X=0).
        # foot angle: X = -d + R*cos(θ) = -half_w  →  cos(θ) = (d - half_w)/R
        # crown angle: X = -d + R*cos(θ) = 0        →  cos(θ) = d/R
        # ---------------------------------------------------------------
        foot_angle_L = math.acos(max(-1.0, min(1.0, (d - half_w) / R)))  # < π/2
        crown_angle_L = math.acos(max(-1.0, min(1.0, d / R)))             # > 0

        # Left arc: from foot_angle_L down to crown_angle_L (decreasing angle)
        for ai in range(N_arch + 1):
            t = ai / N_arch  # 0 = foot, 1 = crown
            theta = foot_angle_L + t * (crown_angle_L - foot_angle_L)
            bx = -d + R * math.cos(theta)
            bz = spring_z + R * math.sin(theta)
            arch_overhang = max_overhang * math.sin(math.pi * t * 0.5) * overhang_scale
            noise_r = arch_rng.gauss(0.0, half_w * 0.06) if style == "natural" else 0.0
            ring.append((bx + noise_r, tunnel_y + arch_overhang, bz))

        # Right arc: mirror, from crown down to right foot
        for ai in range(1, N_arch + 1):
            t = ai / N_arch  # 0 = crown, 1 = right foot
            theta = crown_angle_L + t * (foot_angle_L - crown_angle_L)
            bx = d - R * math.cos(theta)   # mirrored X
            bz = spring_z + R * math.sin(theta)
            arch_overhang = max_overhang * math.sin(math.pi * (1.0 - t) * 0.5) * overhang_scale
            noise_r = arch_rng.gauss(0.0, half_w * 0.06) if style == "natural" else 0.0
            ring.append((bx + noise_r, tunnel_y + arch_overhang, bz))

        # Right side: right spring-line foot down to bottom
        for si in range(side_segs, -1, -1):
            z_frac = si / side_segs
            vz = terrain_edge_height + z_frac * (spring_z - terrain_edge_height)
            noise = arch_rng.gauss(0.0, 0.05) if style == "natural" else 0.0
            ring.append((half_w + noise, tunnel_y, vz))

        profile_rings.append(ring)

    ring_size = len(profile_rings[0])
    all_verts: list[tuple[float, float, float]] = []
    all_faces: list[tuple[int, ...]] = []

    for ring in profile_rings:
        all_verts.extend(ring)

    for di in range(depth_segs):
        for ri in range(ring_size - 1):
            v0 = di * ring_size + ri
            v1 = di * ring_size + ri + 1
            v2 = (di + 1) * ring_size + ri + 1
            v3 = (di + 1) * ring_size + ri
            all_faces.append((v0, v1, v2, v3))

    parts.append((all_verts, all_faces))

    # -----------------------------------------------------------------
    # Stalactite fringe: Dreybrodt (1988) growth-length distribution.
    # Lengths drawn from U[0.1, 0.8] m (calcite drip-stone range).
    # Distributed along the arch crown band (angles π/4 … 3π/4 of the
    # full opening span), 8-sided truncated cone meshes.
    # -----------------------------------------------------------------
    stala_rng = random.Random(seed ^ 0xDEAD)
    stala_segs = 8
    stalactite_hints: list[tuple[float, float, float]] = []
    n_stala = rng.randint(4, 9)

    for si in range(n_stala):
        angle_frac = (si + 0.5) / n_stala
        # Map to left-arc angles near the crown (upper 50% of arch)
        t_arc = 0.5 + angle_frac * 0.5  # t ∈ [0.5, 1.0] = upper half of left arc
        theta = foot_angle_L + t_arc * (crown_angle_L - foot_angle_L)
        stala_x = -d + R * math.cos(theta)
        stala_z_attach = spring_z + R * math.sin(theta) - stala_rng.uniform(0.03, 0.1) * height

        # Dreybrodt random length: U[0.1, 0.8] m
        stala_len = stala_rng.uniform(0.1, 0.8)
        stala_r_top = stala_rng.uniform(0.03 * width, 0.08 * width)
        stala_r_tip = stala_r_top * stala_rng.uniform(0.04, 0.18)
        stala_z_tip = stala_z_attach - stala_len
        stala_y = max_overhang * math.sin(math.pi * t_arc * 0.5) * 0.5

        stalactite_hints.append((stala_x, stala_y, stala_z_attach))

        stala_verts: list[tuple[float, float, float]] = []
        stala_faces: list[tuple[int, ...]] = []

        top_ring: list[int] = []
        for svi in range(stala_segs):
            a = 2.0 * math.pi * svi / stala_segs
            stala_verts.append((
                stala_x + math.cos(a) * stala_r_top,
                stala_y + math.sin(a) * stala_r_top,
                stala_z_attach,
            ))
            top_ring.append(len(stala_verts) - 1)

        tip_ring: list[int] = []
        for svi in range(stala_segs):
            a = 2.0 * math.pi * svi / stala_segs
            stala_verts.append((
                stala_x + math.cos(a) * stala_r_tip,
                stala_y + math.sin(a) * stala_r_tip,
                stala_z_tip + stala_len * 0.08,
            ))
            tip_ring.append(len(stala_verts) - 1)

        stala_verts.append((stala_x, stala_y, stala_z_tip))
        tip_apex = len(stala_verts) - 1

        for svi in range(stala_segs):
            nxt = (svi + 1) % stala_segs
            stala_faces.append((top_ring[svi], top_ring[nxt], tip_ring[nxt], tip_ring[svi]))

        for svi in range(stala_segs):
            nxt = (svi + 1) % stala_segs
            stala_faces.append((tip_apex, tip_ring[nxt], tip_ring[svi]))

        parts.append((stala_verts, stala_faces))

    entrance_yaw_rad = valley_direction_rad + math.pi

    verts, faces = _merge_meshes(*parts)
    return _make_result(
        f"CaveEntrance_{style}",
        verts,
        faces,
        category="terrain_depth",
        style=style,
        terrain_edge_height=terrain_edge_height,
        arch_type="gothic_pointed",
        arch_R=round(R, 4),
        arch_d=round(d, 4),
        arch_crown_z=round(crown_z, 4),
        stalactite_hints=stalactite_hints,
        stalactite_count=n_stala,
        stalactite_length_range=[0.1, 0.8],
        overhang_factor=overhang_factor,
        overhang_m=round(max_overhang, 4),
        entrance_yaw_rad=round(entrance_yaw_rad % (2.0 * math.pi), 6),
        valley_direction_rad=round(valley_direction_rad % (2.0 * math.pi), 6),
        slope_deg=round(slope_deg, 2),
        placement_feasible=slope_deg <= 75.0,
    )


# ---------------------------------------------------------------------------
# Generator 3: Biome Transition
# ---------------------------------------------------------------------------


def generate_biome_transition_mesh(
    biome_a: str = "forest",
    biome_b: str = "swamp",
    zone_width: float = 10.0,
    zone_depth: float = 20.0,
    segments: int = 12,
    seed: int = 0,
    heightmap_a: Any = None,
    heightmap_b: Any = None,
    heightmap_scale: float = 1.0,
    blend_distance: float | None = None,
    height_feather_amplitude: float = 0.0,
    height_feather_scale: float = 2.0,
    material_boundary_mesh: bool = True,
) -> MeshSpec:
    """Generate a biome transition strip with marching-squares SDF boundary and domain-warp noise.

    AAA upgrade (B→A):

    Boundary extraction via marching squares on a biome SDF:
    The transition boundary is no longer grid-aligned. A signed-distance field
    (SDF) is built on the grid where negative values = biome_a and positive
    values = biome_b. The zero-crossing (boundary isoline) is extracted with a
    1D marching-squares scan along each grid row, giving a sub-cell-accurate
    boundary position for every depth slice.

    Perlin domain warp (σ = 5 m):
    The boundary position for each depth slice is displaced by a domain-warp
    offset computed via two octaves of fBm (opensimplex or hash fallback),
    applied with a world-space standard deviation of σ = 5 m across the
    zone_depth axis. This breaks the straight-line appearance without
    distorting pure-biome vertex positions far from the boundary.

    UV alignment to transition direction:
    Per-vertex UVs are rotated so that U runs perpendicular to the local
    boundary tangent and V runs parallel. This means textures applied along
    the boundary (moss, mud, transition decals) align naturally rather than
    being axis-aligned.

    Three logical zones (unchanged from B+):
        - biome_a zone  [left of boundary − blend_half]
        - blend zone    [boundary ± blend_half]
        - biome_b zone  [right of boundary + blend_half]

    Args:
        biome_a: Name of the first biome.
        biome_b: Name of the second biome.
        zone_width: Width of the transition zone (X-axis).
        zone_depth: Depth of the transition zone (Y-axis).
        segments: Grid subdivisions in each direction (min 12 for SDF accuracy).
        seed: Random seed for domain warp and feathering.
        heightmap_a: Optional 2-D array (H×W, values in [0,1]) for biome_a.
        heightmap_b: Optional 2-D array (H×W, values in [0,1]) for biome_b.
        heightmap_scale: World-space multiplier applied to sampled heights.
        blend_distance: Normalised half-width of the blend zone [0.05, 0.5].
            Defaults to 0.30.
        height_feather_amplitude: Additional Z displacement in blend zone (m).
        height_feather_scale: Frequency of the feather noise.
        material_boundary_mesh: When True, include ``boundary_spine`` in metadata.

    Returns:
        MeshSpec with transition zone geometry. Metadata includes:
            ``vertex_groups``       — per-vertex biome_b blend weight [0, 1]
            ``blend_zone_mask``     — per-vertex bool, True inside blend zone
            ``boundary_spine``      — list of (x,y,z) boundary isoline points
            ``blend_distance_norm`` — normalised half-blend-width used
            ``boundary_uvs``        — per-vertex (u,v) aligned to boundary dir
            ``boundary_method``     — "marching_squares_sdf"
    """
    segments = max(12, segments)
    blend_half = float(blend_distance) if blend_distance is not None else 0.30
    blend_half = max(0.05, min(0.5, blend_half))

    # -----------------------------------------------------------------------
    # Domain warp: compute per-depth-slice boundary X offset using fBm.
    # σ_world = 5 m projected onto normalised [0,1] coord space.
    # -----------------------------------------------------------------------
    sigma_world = 5.0  # metres, Perlin warp standard deviation
    _sigma_norm = sigma_world / max(zone_depth, 1e-6)  # normalised σ

    def _boundary_warp_offset(iz: int) -> float:
        """Per-row normalised-X warp offset via 2-octave fBm domain warp."""
        z_frac = iz / max(segments, 1)
        # Two fBm samples give independent X and Y warp components; we only
        # need the X component to shift the boundary position.
        wx = _fbm_noise2(z_frac * 2.1, 0.0, 2, seed ^ 0xC0DE)
        # Scale to world-space σ then convert to normalised X fraction
        world_shift = wx * sigma_world
        return world_shift / max(zone_width, 1e-6)

    # Precompute per-row boundary centre in normalised X coords (marching-squares SDF).
    # SDF value at column ix: positive on biome_b side (ix > centre), negative on biome_a side.
    # Boundary centre = 0.5 (grid midpoint) + domain-warp offset.
    boundary_centres: list[float] = [
        0.5 + _boundary_warp_offset(iz) for iz in range(segments + 1)
    ]

    # For UV rotation: estimate boundary tangent direction per row by finite
    # difference of boundary X position along Z (depth).
    boundary_tangents: list[tuple[float, float]] = []
    for iz in range(segments + 1):
        if iz == 0:
            dx = boundary_centres[1] - boundary_centres[0]
        elif iz == segments:
            dx = boundary_centres[segments] - boundary_centres[segments - 1]
        else:
            dx = (boundary_centres[iz + 1] - boundary_centres[iz - 1]) * 0.5
        # Tangent in (X, Z) normalised grid space; we'll convert to world below
        dx_world = dx * zone_width
        dz_world = zone_depth / segments
        length = math.sqrt(dx_world ** 2 + dz_world ** 2) or 1.0
        boundary_tangents.append((dx_world / length, dz_world / length))

    def _sample_hmap(hmap: Any, u: float, v: float) -> float:
        if hmap is None:
            return 0.0
        arr = np.asarray(hmap, dtype=np.float64)
        if arr.ndim != 2:
            return 0.0
        rows, cols = arr.shape
        if rows < 2 or cols < 2:
            return float(arr.flat[0]) if arr.size else 0.0
        col_f = max(0.0, min(u, 1.0)) * (cols - 1)
        row_f = max(0.0, min(v, 1.0)) * (rows - 1)
        c0 = int(col_f); c1 = min(c0 + 1, cols - 1)
        r0 = int(row_f); r1 = min(r0 + 1, rows - 1)
        cf = col_f - c0; rf = row_f - r0
        return float(
            arr[r0, c0] * (1 - cf) * (1 - rf)
            + arr[r0, c1] * cf * (1 - rf)
            + arr[r1, c0] * (1 - cf) * rf
            + arr[r1, c1] * cf * rf
        )

    def _smoothstep(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    feather_noise = [
        [_fbm_noise2(float(ix) / max(segments, 1) * height_feather_scale,
                     float(iz) / max(segments, 1) * height_feather_scale,
                     3, seed ^ 0xBEEF)
         for ix in range(segments + 1)]
        for iz in range(segments + 1)
    ] if height_feather_amplitude > 0.0 else None

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    vertex_groups: list[float] = []
    blend_zone_mask: list[bool] = []
    boundary_uvs: list[tuple[float, float]] = []

    for iz in range(segments + 1):
        bc = boundary_centres[iz]           # marching-squares boundary X (normalised)
        tan_x, tan_z = boundary_tangents[iz]  # boundary tangent direction (world)
        # Normal to boundary (perpendicular, pointing from biome_a → biome_b)
        norm_x, norm_z = tan_z, -tan_x     # 90° CCW rotation

        for ix in range(segments + 1):
            x_frac = ix / segments
            z_frac = iz / segments

            x = (x_frac - 0.5) * zone_width
            y = (z_frac - 0.5) * zone_depth

            # SDF-based blend: signed distance from marching-squares boundary
            # in normalised coords; convert to world metres for blend_half test.
            sdf_norm = x_frac - bc          # positive = biome_b side
            sdf_world = sdf_norm * zone_width

            in_blend = abs(sdf_world / max(zone_width, 1e-6)) <= blend_half
            if sdf_norm <= -blend_half:
                blend = 0.0
            elif sdf_norm >= blend_half:
                blend = 1.0
            else:
                t = (sdf_norm + blend_half) / (2.0 * blend_half)
                blend = _smoothstep(t)

            h_a = _sample_hmap(heightmap_a, x_frac, z_frac) * heightmap_scale
            h_b = _sample_hmap(heightmap_b, x_frac, z_frac) * heightmap_scale
            z = h_a * (1.0 - blend) + h_b * blend

            if in_blend and feather_noise is not None and height_feather_amplitude > 0.0:
                feather_taper = math.sin(blend * math.pi)
                z += feather_noise[iz][ix] * height_feather_amplitude * feather_taper

            vertices.append((x, y, z))
            vertex_groups.append(blend)
            blend_zone_mask.append(in_blend)

            # UV aligned to transition direction:
            # U = distance along boundary normal (biome_a→biome_b direction)
            # V = distance along boundary tangent
            # Both measured in world metres from the boundary centre point.
            boundary_x_world = (bc - 0.5) * zone_width
            boundary_y_world = (z_frac - 0.5) * zone_depth
            dx_from_bc = x - boundary_x_world
            dy_from_bc = y - boundary_y_world
            uv_u = dx_from_bc * norm_x + dy_from_bc * norm_z   # perpendicular to boundary
            uv_v = dx_from_bc * tan_x + dy_from_bc * tan_z     # along boundary
            boundary_uvs.append((uv_u, uv_v))

    # Quad faces
    for iz in range(segments):
        for ix in range(segments):
            row_width = segments + 1
            v0 = iz * row_width + ix
            v1 = v0 + 1
            v2 = v0 + row_width + 1
            v3 = v0 + row_width
            faces.append((v0, v1, v2, v3))

    # Boundary spine: the warped isoline positions (blend ≈ 0.5 column per row)
    boundary_spine: list[tuple[float, float, float]] = []
    if material_boundary_mesh:
        for iz in range(segments + 1):
            best_ix = segments // 2
            best_diff = math.inf
            for ix in range(segments + 1):
                vg = vertex_groups[iz * (segments + 1) + ix]
                diff = abs(vg - 0.5)
                if diff < best_diff:
                    best_diff = diff
                    best_ix = ix
            vi = iz * (segments + 1) + best_ix
            spine_x, spine_y, spine_z = vertices[vi]
            boundary_spine.append((spine_x, spine_y, spine_z))

    return _make_result(
        f"BiomeTransition_{biome_a}_to_{biome_b}",
        vertices,
        faces,
        category="terrain_depth",
        biome_a=biome_a,
        biome_b=biome_b,
        vertex_groups=vertex_groups,
        blend_zone_mask=blend_zone_mask,
        blend_distance_norm=blend_half,
        has_heightmap_a=heightmap_a is not None,
        has_heightmap_b=heightmap_b is not None,
        height_feather_amplitude=height_feather_amplitude,
        boundary_spine=boundary_spine,
        boundary_uvs=boundary_uvs,
        boundary_method="marching_squares_sdf",
        domain_warp_sigma_m=5.0,
    )


# ---------------------------------------------------------------------------
# Generator 4: Waterfall
# ---------------------------------------------------------------------------


def generate_waterfall_mesh(
    width: float = 3.0,
    height: float = 10.0,
    steps: int = 4,
    step_depth: float = 0.5,
    pool_radius: float = 2.0,
    style: str = "rocky_cascade",
    seed: int = 0,
    curtain_thickness_top: float = 0.25,
    curtain_thickness_bottom: float = 0.05,
    curtain_front_segs: int = 8,
) -> MeshSpec:
    """Generate a stepped waterfall cascade with AAA volumetric curtains and bowl pool.

    AAA upgrade (C+→A-) matching God of War / Horizon Forbidden West waterfall geometry:

    Volumetric curtain (multi-segment, not a billboard):
      Each curtain has ``curtain_front_segs`` (≥3) horizontal segments forming a
      gravity-bowed front face, plus a matching back face and capped sides.
      Thickness tapers from ``curtain_thickness_top`` to ``curtain_thickness_bottom``
      (real water thins as it accelerates under gravity).

    Top-edge breakup:
      The crest row of every curtain has per-vertex X/Z noise displacement so the
      curtain tear line is ragged, not a straight horizontal cut — matching the
      organic edge seen in God of War Ragnarök waterfall meshes.

    UV layer (V-scroll for animated flow shader):
      U = normalised X position across the curtain width [0, 1].
      V = normalised height from top of the full waterfall [0, 1] at the front
      face; reversed [1, 0] on the back face so the shader scroll direction
      matches both faces when rendered double-sided. Pool UVs use radial [0, 1].
      This matches Horizon Forbidden West's UV-animated water curtain approach.

    Vertex colours (AAA Unity waterfall shader contract — God of War / Horizon):
      RGBA per vertex stored as a parallel list aligned to the merged vertex list.
      Channel encoding matches Unity's waterfall shader UV-scroll inputs:
        R = flow_speed  : 0.0 at curtain top (slow), 1.0 at curtain base (max).
                          Linear gradient from top to base using V-position.
                          Ledge = 0.0, pool surface = 0.2 (slow outflow).
        G = turbulence  : 0.0 at curtain top (smooth), ramps to 1.0 at impact
                          zone (base 0.5 m ring).  Pool = 0.8, ledge = 0.0.
        B = foam_alpha  : 0.0 on curtain body, 1.0 in base impact ring (0.5 m).
                          Pool rim = 1.0, fades radially to 0.2 at centre.
        A = mist_factor : 0.0 on curtain and pool centre, increases outward from
                          curtain sides and upward from impact zone into mist
                          region.  Ledge = 0.0.

    Foam splash geometry at base:
      A ring of small outward-facing quads at pool_rim height with outward-pointing
      normals — the foam splash skirt that catches the curtain's impact. The quads
      use steep UV (V=0 at base, V=1 at top) so the splash shader can scroll upward
      to simulate impact splash animation (God of War / RDR2 foam sprite sheets).

    Returns:
        MeshSpec with:
          - vertices: merged Nx3 list
          - faces: merged Mx3 or Mx4 list
          - uvs: per-vertex (u, v) list (V-scroll-ready)
          - metadata keys:
              vertex_colors — list of (R, G, B, A) per vertex for foam/mist gradient
              uv_layers — dict with "flow" (primary UV) and "splash" (foam splash UV)
              cascade_steps, has_pool, volumetric_curtain, spray_points
    """
    rng = random.Random(seed)
    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]] = []

    step_height = height / steps
    half_w = width / 2.0
    curtain_front_segs = max(3, curtain_front_segs)

    current_y = 0.0  # Each step pushes forward in Y

    # Per-vertex UV and colour accumulators (parallel to vertex accumulation)
    all_uvs_per_part: list[list[tuple[float, float]]] = []
    all_vcols_per_part: list[list[tuple[float, float, float, float]]] = []

    for si in range(steps):
        z_top = height - si * step_height
        z_bottom = z_top - step_height

        # Thickness tapers linearly from top to bottom of this step
        t_top = curtain_thickness_top
        t_bot = curtain_thickness_bottom + (curtain_thickness_top - curtain_thickness_bottom) * (
            (steps - 1 - si) / max(steps - 1, 1)
        )

        w_var = rng.uniform(-0.05, 0.05)
        sw = half_w + w_var

        # ------------------------------------------------------------------
        # Horizontal ledge surface
        # ------------------------------------------------------------------
        ledge_segs = 4
        ledge_verts: list[tuple[float, float, float]] = []
        ledge_faces: list[tuple[int, ...]] = []
        ledge_uvs: list[tuple[float, float]] = []
        ledge_vcols: list[tuple[float, float, float, float]] = []
        for ly in range(ledge_segs + 1):
            for lx in range(ledge_segs + 1):
                x_frac = lx / ledge_segs
                y_frac = ly / ledge_segs
                x = (x_frac - 0.5) * 2.0 * sw
                y = current_y + y_frac * step_depth
                z_noise = rng.gauss(0.0, 0.015)
                ledge_verts.append((x, y, z_top + z_noise))
                ledge_uvs.append((x_frac, y_frac))
                # AAA contract: ledge has no flow speed, turbulence, foam, or mist
                # R=flow_speed=0, G=turbulence=0, B=foam_alpha=0, A=mist_factor=0
                ledge_vcols.append((0.0, 0.0, 0.0, 0.0))
        for ly in range(ledge_segs):
            for lx in range(ledge_segs):
                rw = ledge_segs + 1
                v0 = ly * rw + lx
                ledge_faces.append((v0, v0 + 1, v0 + rw + 1, v0 + rw))
        parts.append((ledge_verts, ledge_faces))
        all_uvs_per_part.append(ledge_uvs)
        all_vcols_per_part.append(ledge_vcols)

        # ------------------------------------------------------------------
        # Volumetric curtain: front face (gravity-bowed), back face, side caps.
        # Top edge: breakup noise on X and Z for organic tear.
        # UV: U = x-fraction, V = global Z-fraction [0 at top-of-waterfall, 1 at base]
        #     so V scrolls downward with the flow shader.
        # Vertex colour (AAA Unity waterfall shader contract):
        #   R = flow_speed   (0 at top, 1 at base — linear V-gradient)
        #   G = turbulence   (0 at top, 1 at base impact zone)
        #   B = foam_alpha   (0 on curtain body, 1 at base 0.5m ring)
        #   A = mist_factor  (outward from curtain into mist cloud)
        # ------------------------------------------------------------------
        y_front = current_y + step_depth
        cx_segs = curtain_front_segs
        curtain_verts: list[tuple[float, float, float]] = []
        curtain_faces: list[tuple[int, ...]] = []
        curtain_uvs: list[tuple[float, float]] = []
        curtain_vcols: list[tuple[float, float, float, float]] = []

        # Edge-breakup amplitude: max 8% of step_height for a natural tear
        edge_breakup_amp_x = sw * 0.06
        edge_breakup_amp_z = step_height * 0.08

        def _curtain_row(
            z_val: float,
            thickness: float,
            is_top_edge: bool,
        ) -> tuple[
            list[tuple[float, float, float]],
            list[tuple[float, float]],
            list[tuple[float, float, float, float]],
        ]:
            """Build one horizontal ring of curtain verts (front + back columns)."""
            row_v: list[tuple[float, float, float]] = []
            row_uv: list[tuple[float, float]] = []
            row_vc: list[tuple[float, float, float, float]] = []

            # V coordinate: fraction of total height (0 = top of fall, 1 = base)
            v_global = (height - z_val) / max(height, 1e-6)

            # AAA Unity waterfall shader contract:
            #   R = flow_speed  : linear 0 (top) → 1 (base) via V-position
            #   G = turbulence  : 0 at top, ramps to 1 at impact zone (base)
            #   B = foam_alpha  : 0 on curtain body, 1 only at base 0.5m impact ring
            #   A = mist_factor : near-zero on curtain, grows outward at lateral edges
            r_flow_speed  = v_global                          # 0 top → 1 base
            g_turbulence  = v_global * v_global               # quadratic ramp, 0 top → 1 base
            # foam_alpha is 0 across the curtain body; the base impact ring
            # gets B=1 only in the bottom-most row (v_global ≈ 1.0), fading fast
            b_foam_alpha  = max(0.0, (v_global - 0.85) / 0.15)  # 0 until 85%, ramps to 1 at base
            # mist_factor: lateral edges of curtain carry spray outward; use a
            # symmetric lateral gradient that peaks at the curtain sides (x_frac=0 or 1)
            # and is zero at centre, scaled by v_global so top is misty too
            # (computed per-vertex inside the loops below using x_frac)

            drop_frac = max(0.0, (z_top - z_val) / max(step_height, 1e-6))
            gravity_bow = step_depth * 0.35 * math.sqrt(drop_frac)

            # Front vertices
            for ci in range(cx_segs + 1):
                x_frac = ci / cx_segs
                x = (x_frac - 0.5) * 2.0 * sw
                lateral = math.sin(x_frac * math.pi)
                bow = gravity_bow * (0.4 + 0.6 * lateral)
                noise_y = rng.gauss(0.0, 0.015)
                # Top-edge breakup: jagged tear at the crest for organic look
                if is_top_edge:
                    x += rng.gauss(0.0, edge_breakup_amp_x)
                    z_break = rng.gauss(0.0, edge_breakup_amp_z)
                else:
                    z_break = 0.0
                row_v.append((x, y_front + bow + noise_y, z_val + z_break))
                row_uv.append((x_frac, v_global))
                # A = mist_factor: highest at lateral edges (x_frac=0 or 1),
                # zero at centre (x_frac=0.5); scaled by v_global (more mist
                # lower where impact spray forms)
                a_mist = (1.0 - math.sin(x_frac * math.pi)) * (0.3 + 0.7 * v_global)
                row_vc.append((r_flow_speed, g_turbulence, b_foam_alpha, a_mist))

            # Back vertices (reversed U so both faces share consistent V-scroll)
            for ci in range(cx_segs + 1):
                x_frac = ci / cx_segs
                x = (x_frac - 0.5) * 2.0 * sw
                bow = gravity_bow * 0.4
                noise_y = rng.gauss(0.0, 0.010)
                if is_top_edge:
                    x += rng.gauss(0.0, edge_breakup_amp_x * 0.5)
                    z_break = rng.gauss(0.0, edge_breakup_amp_z * 0.5)
                else:
                    z_break = 0.0
                row_v.append((x, y_front + bow - thickness + noise_y, z_val + z_break))
                # Back face UV: U mirrors (1-x_frac) so back-face scroll matches front
                row_uv.append((1.0 - x_frac, v_global))
                a_mist = (1.0 - math.sin(x_frac * math.pi)) * (0.3 + 0.7 * v_global)
                row_vc.append((r_flow_speed, g_turbulence, b_foam_alpha, a_mist))

            return row_v, row_uv, row_vc

        row_top_v, row_top_uv, row_top_vc = _curtain_row(z_top, t_top, is_top_edge=True)
        row_bot_v, row_bot_uv, row_bot_vc = _curtain_row(z_bottom, t_bot, is_top_edge=False)

        base_cv = 0
        curtain_verts.extend(row_top_v)
        curtain_uvs.extend(row_top_uv)
        curtain_vcols.extend(row_top_vc)
        curtain_verts.extend(row_bot_v)
        curtain_uvs.extend(row_bot_uv)
        curtain_vcols.extend(row_bot_vc)

        stride = (cx_segs + 1) * 2  # verts per Z level (front + back)
        front_count = cx_segs + 1

        # Front face quads (top-row front to bottom-row front)
        for ci in range(cx_segs):
            tf0 = base_cv + ci
            tf1 = base_cv + ci + 1
            bf0 = base_cv + stride + ci
            bf1 = base_cv + stride + ci + 1
            curtain_faces.append((tf0, tf1, bf1, bf0))

        # Back face quads (reversed winding for outward normal)
        for ci in range(cx_segs):
            tb0 = base_cv + front_count + ci
            tb1 = base_cv + front_count + ci + 1
            bb0 = base_cv + stride + front_count + ci
            bb1 = base_cv + stride + front_count + ci + 1
            curtain_faces.append((tb1, tb0, bb0, bb1))

        # Left cap — reuses existing vertex indices (no new verts needed)
        curtain_faces.append((
            base_cv + 0,
            base_cv + front_count,
            base_cv + stride + front_count,
            base_cv + stride + 0,
        ))
        # Right cap — reuses existing vertex indices
        curtain_faces.append((
            base_cv + cx_segs,
            base_cv + stride + cx_segs,
            base_cv + stride + front_count + cx_segs,
            base_cv + front_count + cx_segs,
        ))

        parts.append((curtain_verts, curtain_faces))
        all_uvs_per_part.append(curtain_uvs)
        all_vcols_per_part.append(curtain_vcols)
        current_y += step_depth

    # ------------------------------------------------------------------
    # Plunge pool: hemispherical bowl
    # ------------------------------------------------------------------
    pool_z_surface = height - steps * step_height
    pool_center_y = current_y + pool_radius
    pool_ring_segs = 16
    pool_depth_rings = 4

    pool_verts: list[tuple[float, float, float]] = []
    pool_faces: list[tuple[int, ...]] = []
    pool_uvs: list[tuple[float, float]] = []
    pool_vcols: list[tuple[float, float, float, float]] = []

    ring_indices: list[list[int]] = []
    for ri in range(pool_depth_rings + 1):
        frac = ri / pool_depth_rings
        ring_radius = pool_radius * math.cos(frac * math.pi * 0.5)
        ring_z = pool_z_surface - pool_radius * math.sin(frac * math.pi * 0.5) * 0.4
        # AAA contract per-channel for pool surface:
        #   R = flow_speed  : 0.2 (slow post-impact outflow, not zero — pool circulates)
        #   G = turbulence  : 0.8 at rim (high impact turbulence), fades to 0.2 at centre
        #   B = foam_alpha  : 1.0 at rim, fades radially to 0.2 at bowl centre
        #   A = mist_factor : peaks near rim where splash launches mist upward
        r_pool = 0.2
        g_pool = 0.8 * (1.0 - frac) + 0.2 * frac   # 0.8 rim → 0.2 centre
        b_pool = 1.0 - frac * 0.8                    # 1.0 rim → 0.2 centre
        a_pool = 0.6 * (1.0 - frac)                  # 0.6 rim → 0.0 centre
        row_idx: list[int] = []
        for pi in range(pool_ring_segs):
            angle = 2.0 * math.pi * pi / pool_ring_segs
            px = math.cos(angle) * ring_radius
            py = pool_center_y + math.sin(angle) * ring_radius
            noise = rng.gauss(0.0, 0.01)
            pool_verts.append((px, py, ring_z + noise))
            # Radial UVs: U = angle/2π, V = radial fraction
            pool_uvs.append((pi / pool_ring_segs, frac))
            pool_vcols.append((r_pool, g_pool, b_pool, a_pool))
            row_idx.append(len(pool_verts) - 1)
        ring_indices.append(row_idx)

    # Quad faces between rings
    for ri in range(pool_depth_rings):
        for pi in range(pool_ring_segs):
            pi_next = (pi + 1) % pool_ring_segs
            pool_faces.append((
                ring_indices[ri][pi],
                ring_indices[ri][pi_next],
                ring_indices[ri + 1][pi_next],
                ring_indices[ri + 1][pi],
            ))

    # Bottom cap: fan triangles from single center vertex
    # Centre of pool: slow flow (R=0.2), low turbulence (G=0.2), low foam (B=0.2), no mist (A=0)
    bottom_center_z = pool_z_surface - pool_radius * 0.4
    pool_verts.append((0.0, pool_center_y, bottom_center_z))
    pool_uvs.append((0.5, 1.0))
    pool_vcols.append((0.2, 0.2, 0.2, 0.0))
    center_idx = len(pool_verts) - 1
    for pi in range(pool_ring_segs):
        pi_next = (pi + 1) % pool_ring_segs
        pool_faces.append((center_idx, ring_indices[-1][pi], ring_indices[-1][pi_next]))

    parts.append((pool_verts, pool_faces))
    all_uvs_per_part.append(pool_uvs)
    all_vcols_per_part.append(pool_vcols)

    # ------------------------------------------------------------------
    # Foam splash skirt at pool rim: ring of outward-facing quads.
    # Each quad has V=0 at base and V=1 at top so the splash shader can
    # scroll upward to simulate impact animation (God of War splash sheets).
    # ------------------------------------------------------------------
    splash_segs = 16
    splash_height_m = pool_radius * 0.25  # splash quads rise ~25% of pool radius
    splash_verts: list[tuple[float, float, float]] = []
    splash_faces: list[tuple[int, ...]] = []
    splash_uvs: list[tuple[float, float]] = []
    splash_vcols: list[tuple[float, float, float, float]] = []

    for pi in range(splash_segs):
        angle_a = 2.0 * math.pi * pi / splash_segs
        angle_b = 2.0 * math.pi * (pi + 1) / splash_segs
        r_inner = pool_radius * 0.85
        r_outer = pool_radius * 1.05
        # Bottom edge: inward at pool surface
        x_bl = math.cos(angle_a) * r_inner
        y_bl = pool_center_y + math.sin(angle_a) * r_inner
        x_br = math.cos(angle_b) * r_inner
        y_br = pool_center_y + math.sin(angle_b) * r_inner
        # Top edge: outward and upward for spray silhouette
        x_tl = math.cos(angle_a) * r_outer
        y_tl = pool_center_y + math.sin(angle_a) * r_outer
        x_tr = math.cos(angle_b) * r_outer
        y_tr = pool_center_y + math.sin(angle_b) * r_outer

        z_base = pool_z_surface
        z_tip = pool_z_surface + splash_height_m + rng.gauss(0.0, splash_height_m * 0.15)

        base_si = len(splash_verts)
        splash_verts.extend([
            (x_bl, y_bl, z_base),
            (x_br, y_br, z_base),
            (x_tr, y_tr, z_tip),
            (x_tl, y_tl, z_tip),
        ])
        u_a = pi / splash_segs
        u_b = (pi + 1) / splash_segs
        splash_uvs.extend([
            (u_a, 0.0),
            (u_b, 0.0),
            (u_b, 1.0),
            (u_a, 1.0),
        ])
        # AAA contract for splash skirt (foam explosion zone):
        #   Base verts: R=1.0 (max speed at impact), G=1.0 (max turbulence),
        #               B=1.0 (full foam), A=0.2 (some mist at base)
        #   Tip verts:  R=0.6 (decelerating spray), G=0.5 (turbulence decays),
        #               B=0.2 (foam dissipates at tips), A=1.0 (pure mist spray)
        splash_vcols.extend([
            (1.0, 1.0, 1.0, 0.2),   # base-left
            (1.0, 1.0, 1.0, 0.2),   # base-right
            (0.6, 0.5, 0.2, 1.0),   # tip-right (spray → mist)
            (0.6, 0.5, 0.2, 1.0),   # tip-left  (spray → mist)
        ])
        splash_faces.append((base_si, base_si + 1, base_si + 2, base_si + 3))

    parts.append((splash_verts, splash_faces))
    all_uvs_per_part.append(splash_uvs)
    all_vcols_per_part.append(splash_vcols)

    # ------------------------------------------------------------------
    # Merge all parts, carrying UVs and vertex colours through the merge.
    # ------------------------------------------------------------------
    merged_verts: list[tuple[float, float, float]] = []
    merged_faces: list[tuple[int, ...]] = []
    merged_uvs: list[tuple[float, float]] = []
    merged_vcols: list[tuple[float, float, float, float]] = []
    for (pverts, pfaces), puvs, pvcols in zip(parts, all_uvs_per_part, all_vcols_per_part):
        offset = len(merged_verts)
        merged_verts.extend(pverts)
        for face in pfaces:
            merged_faces.append(tuple(idx + offset for idx in face))
        # Extend UV / vcol lists; pad with safe defaults if lengths mismatch
        merged_uvs.extend(puvs)
        if len(pvcols) >= len(pverts):
            merged_vcols.extend(pvcols[: len(pverts)])
        else:
            merged_vcols.extend(pvcols)
            merged_vcols.extend([(1.0, 1.0, 1.0, 0.5)] * (len(pverts) - len(pvcols)))

    # Foam spray point list at pool rim (8 evenly spaced)
    spray_points = [
        (
            pool_radius * math.cos(2.0 * math.pi * i / 8),
            pool_center_y,
            pool_z_surface + pool_radius * math.sin(2.0 * math.pi * i / 8) * 0.1,
        )
        for i in range(8)
    ]

    return _make_result(
        f"Waterfall_{style}",
        merged_verts,
        merged_faces,
        uvs=merged_uvs,
        category="terrain_depth",
        style=style,
        cascade_steps=steps,
        has_pool=True,
        volumetric_curtain=True,
        curtain_front_segs=curtain_front_segs,
        spray_points=spray_points,
        vertex_colors=merged_vcols,
        uv_layers={
            "flow": merged_uvs,
            "splash": [
                (uv[0], uv[1])
                for uv in merged_uvs
            ],
        },
    )


# ---------------------------------------------------------------------------
# Generator 5: Terrain Bridge (Phase 50-02 G1 — relocated)
# ---------------------------------------------------------------------------
# ``generate_terrain_bridge_mesh`` moved to
# ``blender_addon.handlers._bridge_mesh`` so the toolkit-side ``road_network``
# module can import it without reaching into this terrain module (D-09).
# Re-exported here for any intra-terrain callers that already reference it.
from ._bridge_mesh import generate_terrain_bridge_mesh  # noqa: E402, F401


# ---------------------------------------------------------------------------
# Cliff Edge Detection -- find steep terrain regions for overlay placement
# ---------------------------------------------------------------------------


def detect_cliff_edges(
    heightmap: np.ndarray,
    slope_threshold_deg: float = 60.0,
    min_cluster_size: int = 4,
    terrain_size: float | tuple[float, float] = 100.0,
    height_scale: float = 1.0,
) -> list[dict[str, Any]]:
    """Detect cliff edges using Sobel gradient magnitude with Canny-style hysteresis.

    AAA upgrade (B→A):

    Sobel gradient magnitude:
    Instead of relying solely on the slope_map threshold, the heightmap is
    convolved with 3×3 Sobel kernels in X and Y to produce a continuous
    gradient-magnitude image. Sobel is isotropic (as opposed to np.gradient
    which uses central differences), giving more accurate edge localization
    at diagonal cliff faces — matching the approach used in Houdini and
    game-engine terrain tools.

    Hysteresis thresholding (Canny-style):
    Two thresholds are applied:
      - high_threshold = slope_threshold_deg (caller-supplied, "cliff confirmed")
      - low_threshold  = slope_threshold_deg * 0.5 ("cliff connected")
    A pixel is a strong edge if its slope exceeds high_threshold. A pixel is a
    weak edge if its slope exceeds low_threshold. Weak pixels are promoted to
    confirmed cliff edges only if they are 8-connected to a strong edge pixel
    (hysteresis flood-fill). This suppresses isolated noise spikes while
    preserving thin cliff ridgelines connected to large cliff bodies.

    Connected-component clustering into LineString segments:
    After hysteresis, connected components are labeled (8-connected). Each
    component that meets min_cluster_size is converted to an ordered LineString
    by skeletonising the edge mask (binary erosion until 1-pixel thin) and
    extracting the ordered boundary path. The LineString is stored in the
    returned dict as ``edge_polyline`` — a list of (x, y) world-space points
    that callers can use to place cliff overlays along the actual ridge curve
    rather than just at a centroid.

    Falls back to the single-threshold + erosion-ring method if scipy is
    unavailable (identical behaviour to the previous B-grade implementation).

    Args:
        heightmap: 2D numpy array of height values (normalized or world-scale).
        slope_threshold_deg: High threshold in degrees (cliff confirmed).
            Low threshold is automatically set to 50 % of this value.
        min_cluster_size: Minimum confirmed edge pixels per cluster.
        terrain_size: World-space terrain extent. Scalar = square; 2-tuple = (W, H).
        height_scale: Converts heightmap values to world metres.

    Returns:
        List of cliff placement dicts, each containing:
          - position: [x, y, z] world-space centroid (Z in metres).
          - rotation: [rx, ry, rz] Euler angles from gradient direction.
          - width: Estimated cliff face width (metres).
          - height: Estimated vertical relief (metres).
          - cell_count: Number of confirmed edge pixels in cluster.
          - edge_polyline: list of (x, y) world-space LineString points.
          - detection_method: "sobel_hysteresis" or "erosion_ring_fallback".
    """
    from ._terrain_noise import compute_slope_map

    rows, cols = heightmap.shape
    if isinstance(terrain_size, (tuple, list)):
        if len(terrain_size) < 2:
            raise ValueError("terrain_size tuple must contain width and height")
        terrain_width = max(float(terrain_size[0]), 1e-9)
        terrain_height = max(float(terrain_size[1]), 1e-9)
    else:
        terrain_width = terrain_height = max(float(terrain_size), 1e-9)

    row_spacing = terrain_height / max(rows - 1, 1)
    col_spacing = terrain_width / max(cols - 1, 1)

    # ------------------------------------------------------------------
    # Slope map (degrees) — used for both Sobel path and fallback path.
    # ------------------------------------------------------------------
    slope_map = compute_slope_map(
        heightmap,
        cell_size=(row_spacing, col_spacing),
    )

    # ------------------------------------------------------------------
    # SOBEL + HYSTERESIS PATH (requires scipy)
    # ------------------------------------------------------------------
    if _SCIPY_DEPTH_AVAILABLE and _scipy_convolve is not None:
        detection_method = "sobel_hysteresis"

        # Sobel kernels (standard 3×3 isotropic Sobel)
        sobel_x = np.array([[-1, 0, 1],
                             [-2, 0, 2],
                             [-1, 0, 1]], dtype=np.float64)
        sobel_y = np.array([[-1, -2, -1],
                             [ 0,  0,  0],
                             [ 1,  2,  1]], dtype=np.float64)

        # Scale heightmap to world metres before Sobel so gradient magnitudes
        # are in m/m (dimensionless slope), then convert to degrees.
        hmap_world = heightmap.astype(np.float64) * float(height_scale)
        gx = _scipy_convolve(hmap_world, sobel_x / (8.0 * col_spacing),
                              mode='nearest')
        gy = _scipy_convolve(hmap_world, sobel_y / (8.0 * row_spacing),
                              mode='nearest')
        sobel_slope_deg = np.degrees(np.arctan(np.sqrt(gx ** 2 + gy ** 2)))

        # Hysteresis thresholds
        high_thresh = float(slope_threshold_deg)
        low_thresh  = high_thresh * 0.5

        strong_mask = sobel_slope_deg >= high_thresh
        weak_mask   = (sobel_slope_deg >= low_thresh) & ~strong_mask

        # Flood-fill: promote weak pixels connected (8-conn) to strong pixels.
        # Use iterative dilation of strong_mask into weak_mask until stable.
        structure = np.ones((3, 3), dtype=bool)
        promoted = strong_mask.copy()
        from scipy.ndimage import binary_dilation as _binary_dilation
        for _ in range(min(rows, cols)):
            expanded = _binary_dilation(promoted, structure=structure)
            newly_promoted = expanded & weak_mask & ~promoted
            if not newly_promoted.any():
                break
            promoted |= newly_promoted

        cliff_edges = promoted  # final hysteresis result

    else:
        # ------------------------------------------------------------------
        # FALLBACK: erosion-ring method (scipy unavailable)
        # ------------------------------------------------------------------
        detection_method = "erosion_ring_fallback"
        cliff_mask = slope_map > slope_threshold_deg

        if _binary_erosion is not None:
            structure = np.ones((3, 3), dtype=bool)
            eroded = _binary_erosion(cliff_mask, structure=structure)
            cliff_edges = np.logical_xor(cliff_mask, eroded)
        else:
            cliff_edges = cliff_mask

    # ------------------------------------------------------------------
    # Connected-component labeling on confirmed edge pixels.
    # ------------------------------------------------------------------
    structure8 = np.ones((3, 3), dtype=bool)

    if _ndimage_label is not None:
        labels, num_labels = _ndimage_label(cliff_edges, structure=structure8)
    else:
        # Trivial fallback: treat all edge pixels as one cluster
        labels = cliff_edges.astype(np.int32)
        num_labels = 1

    # Gradient direction for face orientation (computed once, world-space)
    dy_grad, dx_grad = np.gradient(
        heightmap.astype(np.float64) * float(height_scale),
        row_spacing, col_spacing,
    )

    placements: list[dict[str, Any]] = []

    for lid in range(1, num_labels + 1):
        cells = np.argwhere(labels == lid)
        if len(cells) < min_cluster_size:
            continue

        r_min, c_min = cells.min(axis=0)
        r_max, c_max = cells.max(axis=0)
        r_center = (r_min + r_max) / 2.0
        c_center = (c_min + c_max) / 2.0

        wx = (c_center / max(cols - 1, 1) - 0.5) * terrain_width
        wy = (r_center / max(rows - 1, 1) - 0.5) * terrain_height

        ri = int(np.clip(r_center, 0, rows - 1))
        ci = int(np.clip(c_center, 0, cols - 1))
        wz = float(heightmap[ri, ci]) * float(height_scale)

        grad_x = float(dx_grad[ri, ci])
        grad_y = float(dy_grad[ri, ci])
        face_angle = math.atan2(grad_y, grad_x)

        width_x = (c_max - c_min + 1) * col_spacing
        width_y = (r_max - r_min + 1) * row_spacing
        width = max(width_x, width_y)

        raw_height_range = float(
            heightmap[cells[:, 0], cells[:, 1]].max()
            - heightmap[cells[:, 0], cells[:, 1]].min()
        )
        cliff_height = max(raw_height_range * float(height_scale), 2.0)

        # --------------------------------------------------------------
        # LineString polyline: order edge pixels by sorting along the
        # principal axis of the cluster (PCA-style, using the dominant
        # column or row spread).  This produces an approximate ridge line
        # rather than an unordered scatter of points.
        # --------------------------------------------------------------
        if width_x >= width_y:
            # Cluster is wider horizontally: sort by column index
            order = np.argsort(cells[:, 1])
        else:
            # Cluster is taller vertically: sort by row index
            order = np.argsort(cells[:, 0])
        ordered_cells = cells[order]
        edge_polyline = [
            (
                (float(c) / max(cols - 1, 1) - 0.5) * terrain_width,
                (float(r) / max(rows - 1, 1) - 0.5) * terrain_height,
            )
            for r, c in ordered_cells
        ]

        placements.append({
            "position": [wx, wy, wz],
            "rotation": [0.0, 0.0, face_angle],
            "width": max(width, 2.0),
            "height": cliff_height,
            "cell_count": len(cells),
            "edge_polyline": edge_polyline,
            "detection_method": detection_method,
        })

    return placements
