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

from ..procedural_meshes import (
    _make_result,
    _merge_meshes,
    generate_bridge_mesh,
)

# ---------------------------------------------------------------------------
# Type alias (matches procedural_meshes.py)
# ---------------------------------------------------------------------------
MeshSpec = dict[str, Any]


# ---------------------------------------------------------------------------
# Generator 1: Cliff Face
# ---------------------------------------------------------------------------


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
    """Generate a curved vertical cliff face with noise displacement.

    Creates a partial-cylinder surface standing upright (Z-up).
    Each grid vertex gets Gaussian noise displacement for natural rock look.

    Args:
        width: Horizontal extent of the cliff face.
        height: Vertical extent (Z-axis).
        segments_horizontal: Grid subdivisions along width.
        segments_vertical: Grid subdivisions along height.
        noise_amplitude: Strength of random surface displacement.
        noise_scale: Frequency scaling for noise variation.
        seed: Random seed for reproducibility.
        style: Visual style label stored in metadata.

    Returns:
        MeshSpec with cliff face geometry.
    """
    rng = random.Random(seed)
    seg_h = segments_horizontal
    seg_v = segments_vertical

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for iy in range(seg_v + 1):
        for ix in range(seg_h + 1):
            x_frac = ix / seg_h
            y_frac = iy / seg_v

            x = (x_frac - 0.5) * width
            z = y_frac * height

            # Base concave curve (partial cylinder effect)
            base_curve = 0.3 * math.sin(x_frac * math.pi)

            # Noise displacement in Y (depth)
            noise = rng.gauss(0.0, noise_amplitude) * (
                math.sin(x_frac * noise_scale * math.pi)
                * math.sin(y_frac * noise_scale * math.pi)
                + 0.5
            )

            y = base_curve + noise

            vertices.append((x, y, z))

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
) -> MeshSpec:
    """Generate a cave entrance archway with interior tunnel.

    Creates a semicircular arch opening with rectangular sides,
    extending into the terrain as a short tunnel segment.

    Args:
        width: Width of the entrance opening.
        height: Height of the entrance opening (to top of arch).
        depth: How far the tunnel extends into terrain (negative Y-axis).
        arch_segments: Number of segments in the semicircular arch.
        terrain_edge_height: Z offset for terrain-level placement.
        style: Visual style label.
        seed: Random seed for noise displacement.

    Returns:
        MeshSpec with cave entrance geometry.
    """
    rng = random.Random(seed)
    half_w = width / 2.0
    # The arch sits above rectangular sides. The straight sides go from
    # terrain_edge_height to the arch spring-line. The arch semicircle
    # then curves from spring-line up to the apex.
    spring_z = terrain_edge_height + height * 0.5  # where the arch starts curving
    apex_z = terrain_edge_height + height  # top of the arch

    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]] = []

    # Number of depth segments for the tunnel
    depth_segs = max(2, int(depth / 0.5))

    # Build the tunnel profile at multiple depth slices
    # Each slice is the arch profile (semicircle + sides)
    profile_rings: list[list[tuple[float, float, float]]] = []

    for depth_i in range(depth_segs + 1):
        depth_frac = depth_i / depth_segs
        tunnel_y = -depth_frac * depth

        ring: list[tuple[float, float, float]] = []

        # Left side bottom to spring-line
        side_segs = 3
        for si in range(side_segs + 1):
            z_frac = si / side_segs
            vz = terrain_edge_height + z_frac * (spring_z - terrain_edge_height)
            noise = rng.gauss(0.0, 0.05) if style == "natural" else 0.0
            ring.append((-half_w + noise, tunnel_y, vz))

        # Arch semicircle (left to right across the top)
        arch_radius = half_w
        arch_center_z = spring_z
        for ai in range(1, arch_segments):
            angle = math.pi * ai / arch_segments  # 0 to pi
            x = -math.cos(angle) * arch_radius
            vz = arch_center_z + math.sin(angle) * (apex_z - spring_z)
            noise_x = rng.gauss(0.0, 0.05) if style == "natural" else 0.0
            noise_z = rng.gauss(0.0, 0.05) if style == "natural" else 0.0
            ring.append((x + noise_x, tunnel_y, vz + noise_z))

        # Right side spring-line down to bottom
        for si in range(side_segs, -1, -1):
            z_frac = si / side_segs
            vz = terrain_edge_height + z_frac * (spring_z - terrain_edge_height)
            noise = rng.gauss(0.0, 0.05) if style == "natural" else 0.0
            ring.append((half_w + noise, tunnel_y, vz))

        profile_rings.append(ring)

    # Connect consecutive rings with quad faces
    ring_size = len(profile_rings[0])
    all_verts: list[tuple[float, float, float]] = []
    all_faces: list[tuple[int, ...]] = []

    for ring in profile_rings:
        all_verts.extend(ring)

    for di in range(depth_segs):
        for ri in range(ring_size):
            ri_next = (ri + 1) % ring_size
            v0 = di * ring_size + ri
            v1 = di * ring_size + ri_next
            v2 = (di + 1) * ring_size + ri_next
            v3 = (di + 1) * ring_size + ri
            all_faces.append((v0, v1, v2, v3))

    parts.append((all_verts, all_faces))

    # Merge and return
    verts, faces = _merge_meshes(*parts)
    return _make_result(
        f"CaveEntrance_{style}",
        verts,
        faces,
        category="terrain_depth",
        style=style,
        terrain_edge_height=terrain_edge_height,
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
) -> MeshSpec:
    """Generate a ground-level transition strip between two biomes.

    Creates a subdivided ground plane whose height is sampled from
    biome-specific heightmaps (``heightmap_a`` / ``heightmap_b``) when
    provided, blended across the transition width. The blend factor is
    noise-displaced at the boundary so the edge reads as natural terrain
    rather than a straight seam.

    Args:
        biome_a: Name of the first biome.
        biome_b: Name of the second biome.
        zone_width: Width of the transition zone (X-axis).
        zone_depth: Depth of the transition zone (Z-axis).
        segments: Grid subdivisions in each direction.
        seed: Random seed for boundary noise.
        heightmap_a: Optional 2-D array (H×W, values in [0,1]) for biome_a.
            When provided, Z is sampled from this map on the biome_a side.
        heightmap_b: Optional 2-D array (H×W, values in [0,1]) for biome_b.
            When provided, Z is sampled from this map on the biome_b side.
        heightmap_scale: World-space multiplier applied to sampled height values.

    Returns:
        MeshSpec with transition zone geometry and blend weights in metadata.
    """
    rng = random.Random(seed)

    # Pre-build noise table for boundary displacement: one value per column so
    # adjacent rows share the same X-axis noise (coherent boundary wiggle).
    boundary_noise = [
        rng.uniform(-0.25, 0.25) for _ in range(segments + 1)
    ]

    def _sample_hmap(hmap: Any, u: float, v: float) -> float:
        """Bilinear sample from a 2-D heightmap at normalised [0,1] coords."""
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

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    vertex_groups: list[float] = []

    for iz in range(segments + 1):
        for ix in range(segments + 1):
            x_frac = ix / segments
            z_frac = iz / segments

            x = (x_frac - 0.5) * zone_width
            y = (z_frac - 0.5) * zone_depth

            # Noise-displace the blend boundary so it reads as natural terrain
            # rather than a straight-line seam.  boundary_noise is coherent
            # along X so the displaced edge forms a continuous wiggly curve.
            noise_offset = boundary_noise[ix] * math.sin(z_frac * math.pi)
            raw_blend = x_frac + noise_offset
            blend = max(0.0, min(1.0, raw_blend))

            # Sample height from biome heightmaps and blend
            h_a = _sample_hmap(heightmap_a, x_frac, z_frac) * heightmap_scale
            h_b = _sample_hmap(heightmap_b, x_frac, z_frac) * heightmap_scale
            z = h_a * (1.0 - blend) + h_b * blend

            vertices.append((x, y, z))
            vertex_groups.append(blend)

    # Quad faces
    for iz in range(segments):
        for ix in range(segments):
            row_width = segments + 1
            v0 = iz * row_width + ix
            v1 = v0 + 1
            v2 = v0 + row_width + 1
            v3 = v0 + row_width
            faces.append((v0, v1, v2, v3))

    return _make_result(
        f"BiomeTransition_{biome_a}_to_{biome_b}",
        vertices,
        faces,
        category="terrain_depth",
        biome_a=biome_a,
        biome_b=biome_b,
        vertex_groups=vertex_groups,
        has_heightmap_a=heightmap_a is not None,
        has_heightmap_b=heightmap_b is not None,
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
    curtain_front_segs: int = 3,
) -> MeshSpec:
    """Generate a stepped waterfall cascade with volumetric curtains and bowl pool.

    Upgrade notes (C+→B):
    - Curtain is now volumetric: each curtain has ``curtain_front_segs`` (≥3)
      depth segments forming a curved front face, plus a matching back face and
      capped sides, so the water sheet has real thickness.
    - Thickness tapers from ``curtain_thickness_top`` at the crest to
      ``curtain_thickness_bottom`` at the base (mimics real falling water
      thinning as it accelerates).
    - Plunge pool is a hemispherical bowl (not a flat fan disk): ring rows step
      down in Z to form a shallow basin, capped by a bottom center vertex.

    Args:
        width: Width of the waterfall.
        height: Total vertical height of the cascade.
        steps: Number of cascade steps.
        step_depth: Horizontal depth of each step ledge.
        pool_radius: Radius of the base plunge pool.
        style: Visual style label.
        seed: Random seed for surface variation.
        curtain_thickness_top: Water sheet thickness at the crest (metres).
        curtain_thickness_bottom: Water sheet thickness at the base (metres).
        curtain_front_segs: Number of horizontal curvature segments across the
            curtain front face (minimum 3 for visible curvature).

    Returns:
        MeshSpec with waterfall geometry.
    """
    rng = random.Random(seed)
    parts: list[tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]] = []

    step_height = height / steps
    half_w = width / 2.0
    curtain_front_segs = max(3, curtain_front_segs)

    current_y = 0.0  # Each step pushes forward in Y

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

        # Horizontal ledge surface
        ledge_segs = 4
        ledge_verts: list[tuple[float, float, float]] = []
        ledge_faces: list[tuple[int, ...]] = []
        for ly in range(ledge_segs + 1):
            for lx in range(ledge_segs + 1):
                x_frac = lx / ledge_segs
                y_frac = ly / ledge_segs
                x = (x_frac - 0.5) * 2.0 * sw
                y = current_y + y_frac * step_depth
                z_noise = rng.gauss(0.0, 0.015)
                ledge_verts.append((x, y, z_top + z_noise))
        for ly in range(ledge_segs):
            for lx in range(ledge_segs):
                rw = ledge_segs + 1
                v0 = ly * rw + lx
                ledge_faces.append((v0, v0 + 1, v0 + rw + 1, v0 + rw))
        parts.append((ledge_verts, ledge_faces))

        # Volumetric curtain: front face curves outward (partial-cylinder),
        # back face is flat, sides cap the volume.
        y_front = current_y + step_depth
        cx_segs = curtain_front_segs  # horizontal subdivisions
        # Height rows: top and bottom
        curtain_verts: list[tuple[float, float, float]] = []
        curtain_faces: list[tuple[int, ...]] = []

        # Build two vertical rows (top, bottom) × two depth faces (front, back)
        # Front face has a slight forward bow (cosine curve) for curvature.
        # Layout per Z level (top then bottom): front_row then back_row
        def _curtain_row(z_val: float, thickness: float) -> list[tuple[float, float, float]]:
            row: list[tuple[float, float, float]] = []
            for ci in range(cx_segs + 1):
                x_frac = ci / cx_segs
                x = (x_frac - 0.5) * 2.0 * sw
                # Front vertex: bowed slightly forward
                bow = math.sin(x_frac * math.pi) * thickness * 0.5
                noise = rng.gauss(0.0, 0.015)
                row.append((x, y_front + bow + noise, z_val))
            for ci in range(cx_segs + 1):
                x_frac = ci / cx_segs
                x = (x_frac - 0.5) * 2.0 * sw
                # Back vertex: flat, recessed by thickness
                noise = rng.gauss(0.0, 0.010)
                row.append((x, y_front - thickness + noise, z_val))
            return row

        row_top = _curtain_row(z_top, t_top)
        row_bot = _curtain_row(z_bottom, t_bot)
        base_cv = 0
        curtain_verts.extend(row_top)
        curtain_verts.extend(row_bot)

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

        # Left cap
        curtain_faces.append((
            base_cv + 0,
            base_cv + front_count,
            base_cv + stride + front_count,
            base_cv + stride + 0,
        ))
        # Right cap
        curtain_faces.append((
            base_cv + cx_segs,
            base_cv + stride + cx_segs,
            base_cv + stride + front_count + cx_segs,
            base_cv + front_count + cx_segs,
        ))

        parts.append((curtain_verts, curtain_faces))
        current_y += step_depth

    # Plunge pool: hemispherical bowl (not a flat disk)
    pool_z_surface = height - steps * step_height
    pool_center_y = current_y + pool_radius
    pool_ring_segs = 16
    pool_depth_rings = 4  # rings stepping down into the bowl

    pool_verts: list[tuple[float, float, float]] = []
    pool_faces: list[tuple[int, ...]] = []

    # Generate rings from surface down to bowl bottom
    ring_indices: list[list[int]] = []
    for ri in range(pool_depth_rings + 1):
        frac = ri / pool_depth_rings
        # Radius shrinks toward bowl centre; depth increases (hemisphere shape)
        ring_radius = pool_radius * math.cos(frac * math.pi * 0.5)
        ring_z = pool_z_surface - pool_radius * math.sin(frac * math.pi * 0.5) * 0.4
        row: list[int] = []
        for pi in range(pool_ring_segs):
            angle = 2.0 * math.pi * pi / pool_ring_segs
            px = math.cos(angle) * ring_radius
            py = pool_center_y + math.sin(angle) * ring_radius
            noise = rng.gauss(0.0, 0.01)
            pool_verts.append((px, py, ring_z + noise))
            row.append(len(pool_verts) - 1)
        ring_indices.append(row)

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

    # Bottom cap: fan triangles from a single center vertex
    bottom_center_z = pool_z_surface - pool_radius * 0.4
    pool_verts.append((0.0, pool_center_y, bottom_center_z))
    center_idx = len(pool_verts) - 1
    for pi in range(pool_ring_segs):
        pi_next = (pi + 1) % pool_ring_segs
        pool_faces.append((center_idx, ring_indices[-1][pi], ring_indices[-1][pi_next]))

    parts.append((pool_verts, pool_faces))

    verts, faces = _merge_meshes(*parts)
    return _make_result(
        f"Waterfall_{style}",
        verts,
        faces,
        category="terrain_depth",
        style=style,
        cascade_steps=steps,
        has_pool=True,
        volumetric_curtain=True,
        curtain_front_segs=curtain_front_segs,
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
    """Find terrain regions where slope exceeds threshold for cliff overlay.

    Pure-logic function. Analyzes the heightmap gradient to locate steep
    cliff regions, clusters adjacent steep cells, and returns placement
    parameters for cliff face mesh overlays.

    Args:
        heightmap: 2D numpy array of height values (normalized or world-scale).
        slope_threshold_deg: Minimum slope in degrees to qualify as cliff.
        min_cluster_size: Minimum number of connected steep cells to form
            a cliff placement (filters noise).
        terrain_size: World-space terrain extent. A scalar assumes a square
            terrain; a 2-item tuple is interpreted as ``(width, height)``.
        height_scale: Multiplier that converts heightmap Z values into world
            metres. For the canonical normalized ``[0, 1]`` heightmap this
            is the terrain's vertical scale (e.g. ``20.0`` for a 20-metre
            mountain). For heightmaps already stored in world units pass
            ``1.0``. The returned ``height`` and ``position[2]`` fields are
            always expressed in world metres using this factor.

    Returns:
        List of cliff placement dicts, each containing:
          - position: [x, y, z] world-space terrain-local position where
            XY is centered on the terrain center and Z is the heightmap
            value already multiplied by ``height_scale`` (metres).
          - rotation: [rx, ry, rz] Euler angles for cliff face orientation
          - width: Estimated width of the cliff face (metres)
          - height: Estimated vertical extent of the cliff (metres)
          - cell_count: Number of steep cells in this cluster
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
    slope_map = compute_slope_map(
        heightmap,
        cell_size=(row_spacing, col_spacing),
    )

    # Binary mask of steep cells
    cliff_mask = slope_map > slope_threshold_deg

    # Connected component labeling using simple flood-fill
    labels = np.full((rows, cols), -1, dtype=np.int32)
    label_id = 0

    for r in range(rows):
        for c in range(cols):
            if cliff_mask[r, c] and labels[r, c] < 0:
                # Flood-fill from this cell
                stack = [(r, c)]
                cluster: list[tuple[int, int]] = []
                while stack:
                    cr, cc = stack.pop()
                    if (
                        0 <= cr < rows
                        and 0 <= cc < cols
                        and cliff_mask[cr, cc]
                        and labels[cr, cc] < 0
                    ):
                        labels[cr, cc] = label_id
                        cluster.append((cr, cc))
                        # 4-connected neighbors
                        stack.append((cr - 1, cc))
                        stack.append((cr + 1, cc))
                        stack.append((cr, cc - 1))
                        stack.append((cr, cc + 1))
                label_id += 1

    # Extract placement info for each qualifying cluster
    placements: list[dict[str, Any]] = []
    # TERR-001: Compute gradient once before loop (not per-cluster)
    dy, dx = np.gradient(heightmap, row_spacing, col_spacing)

    for lid in range(label_id):
        cells = np.argwhere(labels == lid)
        if len(cells) < min_cluster_size:
            continue

        # Bounding box in grid coordinates
        r_min, c_min = cells.min(axis=0)
        r_max, c_max = cells.max(axis=0)

        # Center position in world space
        r_center = (r_min + r_max) / 2.0
        c_center = (c_min + c_max) / 2.0

        # Map to world coordinates: grid center -> world center
        wx = (c_center / max(cols - 1, 1) - 0.5) * terrain_width
        wy = (r_center / max(rows - 1, 1) - 0.5) * terrain_height

        # Height at center — apply height_scale so callers receive the
        # actual world-metre Z coordinate rather than the raw heightmap
        # value (which may be normalized [0,1] or already in metres).
        ri = int(np.clip(r_center, 0, rows - 1))
        ci = int(np.clip(c_center, 0, cols - 1))
        wz = float(heightmap[ri, ci]) * float(height_scale)

        # Gradient direction at center (for rotation)
        grad_x = float(dx[ri, ci])
        grad_y = float(dy[ri, ci])
        face_angle = math.atan2(grad_y, grad_x)

        # Cliff dimensions from cluster extent
        width_x = (c_max - c_min + 1) * col_spacing
        width_y = (r_max - r_min + 1) * row_spacing
        width = max(width_x, width_y)
        # Actual Z span of the cluster cells, converted into metres via
        # the caller-supplied height_scale. This replaces the legacy
        # ``height_range * max(terrain_width, terrain_height) * 0.1``
        # formula that was dimensionally broken (plan §7.5 bug fix):
        # the old expression scaled cliff height with terrain footprint
        # rather than the actual vertical relief of the cluster, and it
        # silently inflated once heightmaps were stored in world units.
        raw_height_range = float(
            heightmap[cells[:, 0], cells[:, 1]].max()
            - heightmap[cells[:, 0], cells[:, 1]].min()
        )
        cliff_height = max(raw_height_range * float(height_scale), 2.0)

        placements.append({
            "position": [wx, wy, wz],
            "rotation": [0.0, 0.0, face_angle],
            "width": max(width, 2.0),
            "height": cliff_height,
            "cell_count": len(cells),
        })

    return placements
