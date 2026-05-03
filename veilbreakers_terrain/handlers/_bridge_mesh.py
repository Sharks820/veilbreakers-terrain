"""Toolkit-side bridge-mesh primitive (Phase 50-02 G1).

Previously lived in ``_terrain_depth.generate_terrain_bridge_mesh``. Moved here
because toolkit-side ``road_network`` (non-terrain) depends on it; having it
reach into a soon-to-be-extracted terrain module is a D-09 blocker.

Pure-logic; no ``bpy``. Tests for this symbol live with
``test_road_coastline_terrain_features.py`` + ``test_terrain_pipeline_smoke.py``.
"""
from __future__ import annotations

import math
from typing import Any

from ..procedural_meshes import _make_result, generate_bridge_mesh

# Type alias matching _terrain_depth.MeshSpec (pure dict).
MeshSpec = dict[str, Any]


def _resolved_bridge_style(style: str, *, span: float, width: float) -> str:
    key = str(style or "stone_arch").strip().lower()
    if key in {"wood", "wooden", "timber", "timber_beam"}:
        return "timber_beam"
    if key in {"stone", "masonry", "cobblestone", "stone_arch", "stone_viaduct"}:
        return "stone_viaduct" if span >= 24.0 or width >= 4.5 else "stone_arch"
    if key in {"rope", "rope_bridge"}:
        return "rope"
    if key == "drawbridge":
        return "drawbridge"
    if width <= 2.25 and span <= 14.0:
        return "timber_beam"
    return "stone_viaduct" if span >= 24.0 else "stone_arch"


def _bridge_material_slots(resolved_style: str) -> tuple[str, ...]:
    if resolved_style == "timber_beam":
        return (
            "timber_planks",
            "timber_stringers",
            "wood_posts",
            "wood_rails",
            "approach_transition",
        )
    if resolved_style == "rope":
        return (
            "timber_planks",
            "rope_rails",
            "rope_posts",
            "approach_transition",
        )
    if resolved_style in {"stone_arch", "stone_viaduct"}:
        return (
            "stone_deck",
            "stone_parapets",
            "stone_arch_ribs",
            "stone_abutments",
            "approach_transition",
        )
    return ("bridge_deck", "bridge_hardware", "approach_transition")


def _bridge_profile(
    *,
    requested_style: str,
    resolved_style: str,
    span: float,
    width: float,
) -> dict[str, Any]:
    module_length = 2.4 if resolved_style == "timber_beam" else 3.5
    module_count = max(1, int(math.ceil(span / module_length)))
    arch_count = 0
    support_count = 2
    if resolved_style in {"stone_arch", "stone_viaduct"}:
        arch_count = max(1, min(6, int(math.ceil(span / 12.0))))
        support_count = arch_count + 1
    elif resolved_style == "timber_beam":
        support_count = max(2, min(10, module_count + 1))
    elif resolved_style == "rope":
        support_count = 2
    return {
        "requested_style": requested_style,
        "resolved_style": resolved_style,
        "material_family": (
            "wood" if resolved_style in {"timber_beam", "rope", "drawbridge"} else "stone"
        ),
        "span_m": float(span),
        "width_m": float(width),
        "module_length_m": float(module_length),
        "module_count": int(module_count),
        "arch_count": int(arch_count),
        "support_count": int(support_count),
        "approach_transition_m": max(2.0, min(8.0, width * 1.5)),
        "material_slots": list(_bridge_material_slots(resolved_style)),
        "path_to_bridge_rules": [
            "match road/path width at both abutments",
            "reserve approach_transition material on both banks",
            "keep deck above water by validated clearance contract",
            "place supports only on banks or shallow pier points",
        ],
    }


def _polyline_length(points: list[tuple[float, float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _resample_centerline(
    points: list[tuple[float, float, float]],
    *,
    spacing_m: float,
) -> list[tuple[float, float, float]]:
    samples: list[tuple[float, float, float]] = [points[0]]
    for a, b in zip(points, points[1:]):
        seg_len = math.dist(a, b)
        steps = max(1, int(math.ceil(seg_len / max(spacing_m, 0.25))))
        for step in range(1, steps + 1):
            t = step / steps
            samples.append((
                float(a[0]) + (float(b[0]) - float(a[0])) * t,
                float(a[1]) + (float(b[1]) - float(a[1])) * t,
                float(a[2]) + (float(b[2]) - float(a[2])) * t,
            ))
    return samples


def _frame_at(
    samples: list[tuple[float, float, float]],
    index: int,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    prev_i = max(0, index - 1)
    next_i = min(len(samples) - 1, index + 1)
    a = samples[prev_i]
    b = samples[next_i]
    dx = float(b[0]) - float(a[0])
    dy = float(b[1]) - float(a[1])
    length = math.hypot(dx, dy)
    if length <= 1.0e-6:
        tangent = (1.0, 0.0, 0.0)
    else:
        tangent = (dx / length, dy / length, 0.0)
    normal = (-tangent[1], tangent[0], 0.0)
    return tangent, normal


def _oriented_box(
    center: tuple[float, float, float],
    tangent: tuple[float, float, float],
    normal: tuple[float, float, float],
    *,
    half_width: float,
    half_height: float,
    half_length: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    verts: list[tuple[float, float, float]] = []
    for n_sign, z_sign, t_sign in (
        (-1, -1, -1),
        (1, -1, -1),
        (1, 1, -1),
        (-1, 1, -1),
        (-1, -1, 1),
        (1, -1, 1),
        (1, 1, 1),
        (-1, 1, 1),
    ):
        verts.append((
            center[0] + normal[0] * half_width * n_sign + tangent[0] * half_length * t_sign,
            center[1] + normal[1] * half_width * n_sign + tangent[1] * half_length * t_sign,
            center[2] + half_height * z_sign,
        ))
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (2, 3, 7, 6),
        (0, 4, 7, 3),
        (1, 2, 6, 5),
    ]
    return verts, faces


def _append_part(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    part: tuple[list[tuple[float, float, float]], list[tuple[int, ...]]],
) -> None:
    base = len(vertices)
    part_vertices, part_faces = part
    vertices.extend(part_vertices)
    faces.extend(tuple(base + int(index) for index in face) for face in part_faces)


def _append_swept_rail(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    samples: list[tuple[float, float, float]],
    *,
    side: float,
    side_offset: float,
    z_center: float,
    half_depth: float,
    half_height: float,
) -> None:
    start = len(vertices)
    for index, sample in enumerate(samples):
        _, normal = _frame_at(samples, index)
        rail_center = side_offset * side
        inner = rail_center - half_depth * side
        outer = rail_center + half_depth * side
        vertices.append((
            sample[0] + normal[0] * inner,
            sample[1] + normal[1] * inner,
            sample[2] + z_center - half_height,
        ))
        vertices.append((
            sample[0] + normal[0] * outer,
            sample[1] + normal[1] * outer,
            sample[2] + z_center - half_height,
        ))
        vertices.append((
            sample[0] + normal[0] * outer,
            sample[1] + normal[1] * outer,
            sample[2] + z_center + half_height,
        ))
        vertices.append((
            sample[0] + normal[0] * inner,
            sample[1] + normal[1] * inner,
            sample[2] + z_center + half_height,
        ))
    for index in range(len(samples) - 1):
        b = start + index * 4
        n = b + 4
        faces.append((b + 0, n + 0, n + 1, b + 1))
        faces.append((b + 1, n + 1, n + 2, b + 2))
        faces.append((b + 2, n + 2, n + 3, b + 3))
        faces.append((b + 3, n + 3, n + 0, b + 0))


def _append_swept_tube(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    centers: list[tuple[float, float, float]],
    *,
    radius: float,
    sides: int = 8,
) -> None:
    start = len(vertices)
    ring_count = max(6, int(sides))
    for index, center in enumerate(centers):
        _, normal = _frame_at(centers, index)
        for ring_index in range(ring_count):
            angle = 2.0 * math.pi * ring_index / ring_count
            n_offset = math.cos(angle) * radius
            z_offset = math.sin(angle) * radius
            vertices.append((
                center[0] + normal[0] * n_offset,
                center[1] + normal[1] * n_offset,
                center[2] + z_offset,
            ))
    for index in range(len(centers) - 1):
        b = start + index * ring_count
        n = b + ring_count
        for ring_index in range(ring_count):
            next_ring = (ring_index + 1) % ring_count
            faces.append((b + ring_index, n + ring_index, n + next_ring, b + next_ring))


def _generate_swept_centerline_bridge_mesh(
    *,
    centerline: list[tuple[float, float, float]],
    width: float,
    style: str,
    support_foundation_z: float | None = None,
) -> MeshSpec:
    input_centerline = [tuple(point) for point in centerline]
    input_span = max(_polyline_length(input_centerline), 1.0)
    resolved_style = _resolved_bridge_style(style, span=input_span, width=width)
    unsupported_mid_control_points_ignored = False
    if resolved_style == "rope" and len(input_centerline) > 2:
        # Unsupported rope bridges are bank-to-bank spans. Midpoint curvature
        # needs a tower, rock anchor, or pylon contract; without one it creates
        # a physically implausible bent rope bridge through open air.
        centerline = [input_centerline[0], input_centerline[-1]]
        unsupported_mid_control_points_ignored = True

    total_span = max(_polyline_length(centerline), 1.0)
    profile = _bridge_profile(
        requested_style=str(style),
        resolved_style=resolved_style,
        span=total_span,
        width=width,
    )
    profile["input_centerline_point_count"] = len(input_centerline)
    profile["input_centerline_points"] = [list(point) for point in input_centerline]
    profile["centerline_point_count"] = len(centerline)
    profile["curve_segment_count"] = len(centerline) - 1
    profile["elevation_delta_m"] = float(centerline[-1][2]) - float(centerline[0][2])
    profile["centerline_points"] = [list(point) for point in centerline]
    profile["swept_centerline"] = True
    if support_foundation_z is not None:
        profile["support_foundation_z"] = float(support_foundation_z)
        if resolved_style != "rope":
            profile["supports_reach_foundation"] = True
    if resolved_style in {"stone_arch", "stone_viaduct"}:
        profile["surface_pattern"] = "cobblestone"
        profile["has_side_walls"] = True
        profile["has_bottom"] = True
        profile["stone_bridge_parts"] = [
            "cobblestone_roadbed",
            "vertical_spandrel_walls",
            "parapet_capstones",
            "abutments",
            "piers",
            "arch_barrel_underside",
        ]

    spacing = 1.15 if resolved_style in {"timber_beam", "rope"} else 1.45
    samples = _resample_centerline(centerline, spacing_m=spacing)
    if resolved_style == "timber_beam":
        deck_thick = 0.18
    elif resolved_style == "rope":
        deck_thick = 0.10
    else:
        deck_thick = 0.34
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    if resolved_style not in {"timber_beam", "rope", "stone_arch", "stone_viaduct"}:
        raise ValueError(
            f"swept terrain-aware bridges do not support style {resolved_style!r}; "
            "use timber_beam or stone styles for waterbed/control-point bridge generation"
        )

    for index, sample in enumerate(samples):
        _, normal = _frame_at(samples, index)
        left_top = (
            sample[0] - normal[0] * width / 2.0,
            sample[1] - normal[1] * width / 2.0,
            sample[2],
        )
        right_top = (
            sample[0] + normal[0] * width / 2.0,
            sample[1] + normal[1] * width / 2.0,
            sample[2],
        )
        left_bottom = (left_top[0], left_top[1], sample[2] - deck_thick)
        right_bottom = (right_top[0], right_top[1], sample[2] - deck_thick)
        vertices.extend([left_top, right_top, left_bottom, right_bottom])

    for index in range(len(samples) - 1):
        b = index * 4
        n = b + 4
        faces.append((b + 0, n + 0, n + 1, b + 1))  # deck top
        faces.append((b + 2, b + 3, n + 3, n + 2))  # underside
        faces.append((b + 0, b + 2, n + 2, n + 0))  # left edge
        faces.append((b + 1, n + 1, n + 3, b + 3))  # right edge

    if resolved_style == "timber_beam":
        profile["rail_geometry"] = "continuous_light_rails"
        profile["terminal_pillar_style"] = "simple_newel_caps"
        profile["support_footing_style"] = "waterbed_sill_footings"
        # Continuous load path: underlay/stringers, sill beams at both banks,
        # cap beams and rails follow the curve instead of being detached chunks.
        for index, sample in enumerate(samples):
            tangent, normal = _frame_at(samples, index)
            if index in {0, len(samples) - 1}:
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        (sample[0], sample[1], sample[2] - 0.16),
                        tangent,
                        normal,
                        half_width=width * 0.58,
                        half_height=0.08,
                        half_length=0.18,
                    ),
                )
            if index % 2 == 0 or index in {0, len(samples) - 1}:
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        (sample[0], sample[1], sample[2] + 0.035),
                        tangent,
                        normal,
                        half_width=width * 0.48,
                        half_height=0.035,
                        half_length=0.52,
                    ),
                )
                for side in (-1.0, 1.0):
                    post_center = (
                        sample[0] + normal[0] * width * 0.46 * side,
                        sample[1] + normal[1] * width * 0.46 * side,
                        sample[2] + 0.36,
                    )
                    _append_part(
                        vertices,
                        faces,
                        _oriented_box(
                            post_center,
                            tangent,
                            normal,
                            half_width=0.055,
                            half_height=0.36,
                            half_length=0.055,
                        ),
                    )

        for side in (-1.0, 1.0):
            for height, rail_depth, rail_height in (
                (0.55, 0.055, 0.050),
                (0.81, 0.065, 0.060),
            ):
                _append_swept_rail(
                    vertices,
                    faces,
                    samples,
                    side=side,
                    side_offset=width * 0.46,
                    z_center=height,
                    half_depth=rail_depth,
                    half_height=rail_height,
                )

        # Lower tie rail and toe kick directly on the deck edge so the railing
        # is visibly attached rather than floating outside the bridge.
        for side in (-1.0, 1.0):
            for height, rail_depth, rail_height in (
                (0.18, 0.040, 0.030),
                (0.055, 0.032, 0.020),
            ):
                _append_swept_rail(
                    vertices,
                    faces,
                    samples,
                    side=side,
                    side_offset=width * 0.45,
                    z_center=height,
                    half_depth=rail_depth,
                    half_height=rail_height,
                )

        # Terminal newel/pillar assemblies at both banks. Rails terminate into
        # these larger posts instead of simply ending as loose strips.
        for endpoint_index in (0, len(samples) - 1):
            sample = samples[endpoint_index]
            tangent, normal = _frame_at(samples, endpoint_index)
            for side in (-1.0, 1.0):
                pillar_center = (
                    sample[0] + normal[0] * width * 0.46 * side,
                    sample[1] + normal[1] * width * 0.46 * side,
                    sample[2] + 0.44,
                )
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        pillar_center,
                        tangent,
                        normal,
                        half_width=0.13,
                        half_height=0.48,
                        half_length=0.13,
                    ),
                )
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        (
                            pillar_center[0],
                            pillar_center[1],
                            sample[2] + 0.95,
                        ),
                        tangent,
                        normal,
                        half_width=0.17,
                        half_height=0.055,
                        half_length=0.17,
                    ),
                )

        if support_foundation_z is not None:
            for index, sample in enumerate(samples):
                if index not in {0, len(samples) - 1} and index % 3 != 0:
                    continue
                top_z = sample[2] - deck_thick - 0.02
                bottom_z = min(float(support_foundation_z), top_z - 0.25)
                half_height = (top_z - bottom_z) / 2.0
                center_z = (top_z + bottom_z) / 2.0
                tangent, normal = _frame_at(samples, index)
                for side in (-1.0, 1.0):
                    _append_part(
                        vertices,
                        faces,
                        _oriented_box(
                            (
                                sample[0] + normal[0] * width * 0.34 * side,
                                sample[1] + normal[1] * width * 0.34 * side,
                                center_z,
                            ),
                            tangent,
                            normal,
                            half_width=0.075,
                            half_height=half_height,
                            half_length=0.075,
                    ),
                )

    elif resolved_style == "rope":
        profile["rope_planform"] = "straight_bank_to_bank"
        profile["unsupported_mid_control_points_ignored"] = unsupported_mid_control_points_ignored
        profile["rope_physics_model"] = "catenary_sag_with_sway_metadata"
        profile["sway_enabled"] = True
        profile["sway_amplitude_m"] = round(max(0.08, min(0.32, total_span * 0.012)), 3)
        profile["sway_frequency_hz"] = 0.33
        profile["catenary_sag_m"] = round(max(0.18, min(1.2, total_span * 0.045)), 3)
        profile["rope_bridge_parts"] = [
            "main_catenary_ropes",
            "hand_ropes",
            "vertical_suspenders",
            "timber_plank_deck",
            "bank_anchor_frames",
            "sway_animation_contract",
        ]
        profile["anchored_to_banks"] = True
        profile["supports_reach_foundation"] = False

        cumulative = [0.0]
        for a, b in zip(samples, samples[1:]):
            cumulative.append(cumulative[-1] + math.dist(a, b))
        total_len = max(cumulative[-1], 1.0)

        def sag_at(index: int, amount: float) -> float:
            t = cumulative[index] / total_len
            return -math.sin(t * math.pi) * amount

        sag_depth = float(profile["catenary_sag_m"])
        plank_step = 1
        plank_width = width * 0.86
        for index, sample in enumerate(samples):
            tangent, normal = _frame_at(samples, index)
            if index % plank_step == 0:
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        (sample[0], sample[1], sample[2] + sag_at(index, sag_depth * 0.38) + 0.02),
                        tangent,
                        normal,
                        half_width=plank_width * 0.5,
                        half_height=0.035,
                        half_length=0.23,
                    ),
                )

        for side in (-1.0, 1.0):
            side_offset = width * 0.58 * side
            main_centers: list[tuple[float, float, float]] = []
            hand_centers: list[tuple[float, float, float]] = []
            lower_centers: list[tuple[float, float, float]] = []
            for index, sample in enumerate(samples):
                _, normal = _frame_at(samples, index)
                main_sag = sag_at(index, sag_depth)
                deck_sag = sag_at(index, sag_depth * 0.38)
                main_centers.append((
                    sample[0] + normal[0] * side_offset,
                    sample[1] + normal[1] * side_offset,
                    sample[2] + 1.02 + main_sag,
                ))
                hand_centers.append((
                    sample[0] + normal[0] * side_offset,
                    sample[1] + normal[1] * side_offset,
                    sample[2] + 0.66 + main_sag * 0.62,
                ))
                lower_centers.append((
                    sample[0] + normal[0] * width * 0.46 * side,
                    sample[1] + normal[1] * width * 0.46 * side,
                    sample[2] + 0.22 + deck_sag,
                ))
            _append_swept_tube(vertices, faces, main_centers, radius=0.055, sides=10)
            _append_swept_tube(vertices, faces, hand_centers, radius=0.035, sides=8)
            _append_swept_tube(vertices, faces, lower_centers, radius=0.030, sides=8)

            suspender_every = 2
            for index, sample in enumerate(samples):
                if index not in {0, len(samples) - 1} and index % suspender_every != 0:
                    continue
                tangent, normal = _frame_at(samples, index)
                main_z = main_centers[index][2]
                deck_z = sample[2] + sag_at(index, sag_depth * 0.38) + 0.12
                center_z = (main_z + deck_z) * 0.5
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        (
                            sample[0] + normal[0] * side_offset,
                            sample[1] + normal[1] * side_offset,
                            center_z,
                        ),
                        tangent,
                        normal,
                        half_width=0.025,
                        half_height=max(0.08, (main_z - deck_z) * 0.5),
                        half_length=0.025,
                    ),
                )

        for endpoint_index in (0, len(samples) - 1):
            sample = samples[endpoint_index]
            tangent, normal = _frame_at(samples, endpoint_index)
            for side in (-1.0, 1.0):
                anchor = (
                    sample[0] + normal[0] * width * 0.58 * side,
                    sample[1] + normal[1] * width * 0.58 * side,
                    sample[2] + 0.62,
                )
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        anchor,
                        tangent,
                        normal,
                        half_width=0.12,
                        half_height=0.68,
                        half_length=0.12,
                    ),
                )
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        (anchor[0], anchor[1], sample[2] + 1.34),
                        tangent,
                        normal,
                        half_width=0.18,
                        half_height=0.055,
                        half_length=0.18,
                    ),
                )

    else:
        # Stone: keep the roadbed continuous but avoid sloped "boat hull"
        # spandrels. Medieval masonry reads as vertical side walls/parapets,
        # block caps, abutments, and pier masses tied to the deck path.
        arch_count = max(1, int(profile["arch_count"]))
        support_indices = sorted({
            int(round(i * (len(samples) - 1) / arch_count))
            for i in range(arch_count + 1)
        })
        for side in (-1.0, 1.0):
            for start_index, end_index in zip(support_indices, support_indices[1:]):
                if end_index <= start_index:
                    continue
                bay_samples = samples[start_index : end_index + 1]
                bay_span = max(_polyline_length(bay_samples), 1.0)
                arch_drop = max(1.15, min(3.2, bay_span * 0.24))
                wall_start = len(vertices)
                for local_index, sample in enumerate(bay_samples):
                    t = local_index / max(len(bay_samples) - 1, 1)
                    _, normal = _frame_at(samples, start_index + local_index)
                    arch_bottom_z = sample[2] - arch_drop + math.sin(t * math.pi) * (arch_drop - 0.18)
                    wall_inner_top = (
                        sample[0] + normal[0] * width * 0.48 * side,
                        sample[1] + normal[1] * width * 0.48 * side,
                        sample[2] + 0.66,
                    )
                    wall_outer_top = (
                        sample[0] + normal[0] * width * 0.58 * side,
                        sample[1] + normal[1] * width * 0.58 * side,
                        sample[2] + 0.66,
                    )
                    wall_inner_bottom = (
                        sample[0] + normal[0] * width * 0.48 * side,
                        sample[1] + normal[1] * width * 0.48 * side,
                        arch_bottom_z,
                    )
                    wall_outer_bottom = (
                        sample[0] + normal[0] * width * 0.58 * side,
                        sample[1] + normal[1] * width * 0.58 * side,
                        arch_bottom_z,
                    )
                    vertices.extend([wall_inner_bottom, wall_outer_bottom, wall_inner_top, wall_outer_top])
                for local_index in range(len(bay_samples) - 1):
                    b = wall_start + local_index * 4
                    n = b + 4
                    faces.append((b + 0, n + 0, n + 2, b + 2))
                    faces.append((b + 1, b + 3, n + 3, n + 1))
                    faces.append((b + 2, n + 2, n + 3, b + 3))
                    faces.append((b + 0, b + 1, n + 1, n + 0))

                block_count = max(7, min(17, len(bay_samples)))
                for block_index in range(block_count):
                    t = block_index / max(block_count - 1, 1)
                    sample_index = int(round(start_index + t * (end_index - start_index)))
                    sample = samples[sample_index]
                    tangent, normal = _frame_at(samples, sample_index)
                    block_z = sample[2] - arch_drop + math.sin(t * math.pi) * (arch_drop - 0.12)
                    _append_part(
                        vertices,
                        faces,
                        _oriented_box(
                            (
                                sample[0] + normal[0] * width * 0.595 * side,
                                sample[1] + normal[1] * width * 0.595 * side,
                                block_z,
                            ),
                            tangent,
                            normal,
                            half_width=0.16,
                            half_height=0.10,
                            half_length=max(0.16, bay_span / block_count * 0.24),
                        ),
                    )

        # Pre-compute arch_drop per bay boundary so each pier descends to the
        # correct arch springing depth rather than a flat 1.40 m hardcode.
        _pier_arch_drop: dict = {}
        for _si_s, _si_e in zip(support_indices, support_indices[1:]):
            _bay = samples[_si_s : _si_e + 1]
            _ad = max(1.15, min(3.2, _polyline_length(_bay) * 0.24))
            _pier_arch_drop.setdefault(_si_s, _ad)
            _pier_arch_drop[_si_e] = _ad

        support_indices_set = set(support_indices)
        for index, sample in enumerate(samples):
            tangent, normal = _frame_at(samples, index)
            # Place piers only at arch-bay boundaries so they align with arch
            # springing points instead of being on an independent sample grid.
            if index in support_indices_set:
                top_z = sample[2] - 0.08
                arch_drop_here = _pier_arch_drop.get(index, 1.15)
                bottom_z = (
                    min(float(support_foundation_z), top_z - 0.40)
                    if support_foundation_z is not None
                    else top_z - arch_drop_here - 0.50
                )
                pier_half_height = (top_z - bottom_z) / 2.0
                pier_center_z = (top_z + bottom_z) / 2.0
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        (sample[0], sample[1], pier_center_z),
                        tangent,
                        normal,
                        half_width=width * 0.18,
                        half_height=pier_half_height,
                        half_length=0.34 if index in {0, len(samples) - 1} else 0.22,
                    ),
                )
            if index % 2 == 0:
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        (sample[0], sample[1], sample[2] + 0.82),
                        tangent,
                        normal,
                        half_width=width * 0.62,
                        half_height=0.06,
                        half_length=0.28,
                    ),
                )
            if index % 3 == 0:
                for side in (-1.0, 1.0):
                    _append_part(
                        vertices,
                        faces,
                        _oriented_box(
                            (
                                sample[0] + normal[0] * width * 0.55 * side,
                                sample[1] + normal[1] * width * 0.55 * side,
                                sample[2] + 0.76,
                            ),
                            tangent,
                            normal,
                            half_width=0.16,
                            half_height=0.08,
                            half_length=0.32,
                        ),
                    )

        # Cobblestone roadbed: staggered, low-relief stone blocks on the top
        # surface. Kept shallow so it reads as paving rather than loose props.
        lane_rows = max(3, min(5, int(width / 0.9)))
        for index, sample in enumerate(samples):
            if index % 2 != 0 and index not in {0, len(samples) - 1}:
                continue
            tangent, normal = _frame_at(samples, index)
            for row in range(lane_rows):
                row_t = (row + 0.5) / lane_rows - 0.5
                offset = row_t * width * 0.74 + (0.10 if (index + row) % 2 else 0.0)
                _append_part(
                    vertices,
                    faces,
                    _oriented_box(
                        (
                            sample[0] + normal[0] * offset,
                            sample[1] + normal[1] * offset,
                            sample[2] + 0.035,
                        ),
                        tangent,
                        normal,
                        half_width=width / lane_rows * 0.30,
                        half_height=0.09,
                        half_length=0.28,
                    ),
                )

        # Arch-barrel hint underneath between support locations. These are
        # intentionally below the roadbed and between the side walls, so the
        # bridge reads as masonry compression rather than a boat-shaped shell.
        support_step = max(3, int(len(samples) / max(profile["arch_count"], 1)))
        for index in range(0, len(samples), support_step):
            sample = samples[index]
            tangent, normal = _frame_at(samples, index)
            _append_part(
                vertices,
                faces,
                _oriented_box(
                    (sample[0], sample[1], sample[2] - 0.42),
                    tangent,
                    normal,
                    half_width=width * 0.28,
                    half_height=0.10,
                    half_length=0.44,
                ),
            )

    return _make_result(
        f"TerrainBridge_{resolved_style}_swept",
        vertices,
        faces,
        category="terrain_depth",
        style=style,
        resolved_style=resolved_style,
        bridge_profile=profile,
        material_slots=profile["material_slots"],
        start_pos=tuple(centerline[0]),
        end_pos=tuple(centerline[-1]),
        span=total_span,
    )


def _generate_straight_bridge_mesh(
    *,
    start_pos: tuple[float, float, float],
    end_pos: tuple[float, float, float],
    width: float,
    style: str,
) -> MeshSpec:
    sx, sy, sz = start_pos
    ex, ey, ez = end_pos

    dx = ex - sx
    dy = ey - sy
    _ = ez - sz  # FIX-11-10: __dz unused; span computed from horizontal dist only

    horizontal_dist = math.sqrt(dx * dx + dy * dy)
    span = max(horizontal_dist, 1.0)

    resolved_style = _resolved_bridge_style(style, span=span, width=width)
    base = generate_bridge_mesh(span=span, width=width, style=resolved_style)
    profile = _bridge_profile(
        requested_style=str(style),
        resolved_style=resolved_style,
        span=span,
        width=width,
    )

    yaw = math.atan2(dy, dx)
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)

    mid_x = (sx + ex) / 2.0
    mid_y = (sy + ey) / 2.0
    mid_z = (sz + ez) / 2.0

    transformed_verts: list[tuple[float, float, float]] = []
    for vx, vy, vz in base["vertices"]:
        rx = vz * cos_yaw - vx * sin_yaw
        ry = vz * sin_yaw + vx * cos_yaw
        tx = rx + mid_x
        ty = ry + mid_y
        tz = vy + mid_z
        transformed_verts.append((tx, ty, tz))

    return _make_result(
        f"TerrainBridge_{resolved_style}",
        transformed_verts,
        base["faces"],
        category="terrain_depth",
        style=style,
        resolved_style=resolved_style,
        bridge_profile=profile,
        material_slots=profile["material_slots"],
        start_pos=start_pos,
        end_pos=end_pos,
        span=span,
    )


def generate_terrain_bridge_mesh(
    start_pos: tuple[float, float, float] = (0, 0, 0),
    end_pos: tuple[float, float, float] = (10, 0, 0),
    width: float = 3.0,
    style: str = "stone_arch",
    seed: int = 0,
    control_points: list[tuple[float, float, float]] | tuple[tuple[float, float, float], ...] | None = None,
    water_level: float | None = None,
    support_foundation_z: float | None = None,
    waterbed_z: float | None = None,
) -> MeshSpec:
    """Generate a terrain-aware bridge between two world positions.

    Wraps :func:`generate_bridge_mesh` (toolkit primitive) with position /
    rotation transformation to connect arbitrary world-space endpoints.

    Args:
        start_pos: World position of bridge start ``(x, y, z)``.
        end_pos: World position of bridge end ``(x, y, z)``.
        width: Bridge width.
        style: Bridge style (``"stone_arch"``, ``"rope"``, ``"drawbridge"``).
        seed: Random seed (reserved for future noise variation).

    Returns:
        :class:`MeshSpec` dict with bridge geometry transformed to the world
        position spanned by ``start_pos`` -> ``end_pos``.
    """
    centerline = list(control_points or [])
    foundation_z = support_foundation_z
    if foundation_z is None:
        foundation_z = waterbed_z
    if foundation_z is None and water_level is not None:
        foundation_z = float(water_level) - max(1.0, float(width) * 0.35)
    if centerline:
        if len(centerline) < 2:
            raise ValueError("control_points must include at least two points")
        return _generate_swept_centerline_bridge_mesh(
            centerline=[tuple(point) for point in centerline],
            width=width,
            style=style,
            support_foundation_z=foundation_z,
        )
    if foundation_z is not None:
        return _generate_swept_centerline_bridge_mesh(
            centerline=[tuple(start_pos), tuple(end_pos)],
            width=width,
            style=style,
            support_foundation_z=foundation_z,
        )

    return _generate_straight_bridge_mesh(
        start_pos=start_pos,
        end_pos=end_pos,
        width=width,
        style=style,
    )
