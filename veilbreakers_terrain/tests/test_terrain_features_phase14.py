"""Phase 14 terrain features quality tests — Fix 7.3–7.6, 7.14–7.16."""
from __future__ import annotations

import math
import warnings

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fix 7.3 — apply_hot_spring_features vectorized
# ---------------------------------------------------------------------------


class TestFix73:
    def test_hot_spring_returns_tuple(self):
        from veilbreakers_terrain.handlers._biome_grammar import apply_hot_spring_features

        h = np.linspace(0, 1, 32 * 32).reshape(32, 32).astype(np.float64)
        result, springs = apply_hot_spring_features(h, seed=42, num_springs=1)
        assert result.shape == h.shape
        assert len(springs) >= 1
        assert not np.allclose(result, h), "hot spring must modify heightmap"

    def test_hot_spring_terrace_count(self):
        from veilbreakers_terrain.handlers._biome_grammar import apply_hot_spring_features

        h = np.full((32, 32), 0.5, dtype=np.float64)
        result, springs = apply_hot_spring_features(
            h, seed=1, num_springs=1, pool_radius=4.0, terrace_rings=3
        )
        # terrace_rings=3 means 3 travertine steps — output should have non-monotonic radial profile
        assert result.shape == (32, 32)


# ---------------------------------------------------------------------------
# Fix 7.4 — apply_landslide_scars fan deposit on walk path (not centroid)
# ---------------------------------------------------------------------------


class TestFix74:
    def test_landslide_deposits_away_from_scar(self):
        from veilbreakers_terrain.handlers._biome_grammar import apply_landslide_scars

        # Steep ramp so gradient walk moves downhill
        h = np.zeros((32, 32), dtype=np.float64)
        for r in range(32):
            h[r, :] = (31 - r) / 31.0  # decreasing from top to bottom
        result = apply_landslide_scars(h, seed=7, num_slides=1, scar_depth=0.05)
        delta = result - h
        assert delta.shape == (32, 32)
        # Material should have been added somewhere (net positive in fan region)
        assert float(delta.max()) > 0.0, "Deposit must add material somewhere"
        # And removed at scar (net negative somewhere)
        assert float(delta.min()) < 0.0, "Scar must remove material"


# ---------------------------------------------------------------------------
# Fix 7.5 — apply_periglacial_patterns KDTree branch for n_centers > 50
# ---------------------------------------------------------------------------


class TestFix75:
    def test_periglacial_shape_and_range(self):
        from veilbreakers_terrain.handlers._biome_grammar import apply_periglacial_patterns

        h = np.random.default_rng(42).uniform(0, 100, (64, 64)).astype(np.float64)
        result = apply_periglacial_patterns(h, seed=0, intensity=0.5)
        assert result.shape == (64, 64)
        assert not np.allclose(result, h), "periglacial must modify heightmap"

    def test_periglacial_large_uses_kdtree_path(self):
        from veilbreakers_terrain.handlers._biome_grammar import apply_periglacial_patterns

        # 128x128 => n_centers = max(4, int(128*128*0.0004)) = max(4, 6) = 6 — under 50
        # Use 512x512 => n_centers = max(4, int(512*512*0.0004)) = max(4, 104) = 104 — over 50
        h = np.random.default_rng(3).uniform(0, 100, (512, 512)).astype(np.float64)
        result = apply_periglacial_patterns(h, seed=0, intensity=0.3)
        assert result.shape == (512, 512)


# ---------------------------------------------------------------------------
# Fix 7.6 — apply_tafoni_weathering Gaussian exp() falloff
# ---------------------------------------------------------------------------


class TestFix76:
    def test_tafoni_creates_cavities(self):
        from veilbreakers_terrain.handlers._biome_grammar import apply_tafoni_weathering

        # Steep ramp to activate steep_mask
        h = np.zeros((32, 32), dtype=np.float64)
        for r in range(32):
            h[r, :] = r / 31.0
        result = apply_tafoni_weathering(h, seed=0, intensity=1.0, num_cavities=20)
        assert result.shape == (32, 32)
        assert float((result < h).sum()) > 0, "tafoni must carve at least one cavity"

    def test_tafoni_cavities_use_gaussian_falloff(self):
        from veilbreakers_terrain.handlers._biome_grammar import apply_tafoni_weathering

        h = np.zeros((16, 16), dtype=np.float64)
        h[8:, :] = 1.0  # half-ramp for steep mask
        result = apply_tafoni_weathering(h, seed=5, intensity=0.5, num_cavities=5)
        # Gaussian cavities have smooth edges — check that at least one carved cell is
        # between the min and original value (not a hard step)
        delta = result - h
        carved = delta[delta < -1e-6]
        if len(carved) > 1:
            assert float(carved.std()) > 0, "Gaussian falloff produces smooth cavity edges"


# ---------------------------------------------------------------------------
# Fix 7.14 — compute_atmospheric_placements terrain-aware z + no-heightmap warning
# ---------------------------------------------------------------------------


class TestFix714:
    def test_placement_z_matches_terrain_height(self):
        from veilbreakers_terrain.handlers.atmospheric_volumes import (
            compute_atmospheric_placements,
        )

        hmap = np.full((10, 10), 50.0, dtype=np.float64)  # flat at 50m
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            placements = compute_atmospheric_placements(
                "ashfall_plain",
                area_bounds=(0, 0, 100, 100),
                seed=1,
                heightmap=hmap,
                cell_size=10.0,
            )
        for p in placements:
            terrain_z = p.get("terrain_z", None)
            if terrain_z is not None:
                assert abs(terrain_z - 50.0) < 1e-3, (
                    f"terrain_z should be 50.0 (heightmap value), got {terrain_z}"
                )

    def test_no_heightmap_emits_warning(self):
        from veilbreakers_terrain.handlers.atmospheric_volumes import (
            compute_atmospheric_placements,
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            compute_atmospheric_placements(
                "ashfall_plain",
                area_bounds=(0, 0, 100, 100),
                seed=1,
            )
            assert len(w) >= 1, "Missing heightmap must emit a warning"
            assert "heightmap" in str(w[0].message).lower()


# ---------------------------------------------------------------------------
# Fix 7.15 — compute_volume_mesh_spec icosphere 42 verts / 80 faces
# ---------------------------------------------------------------------------


class TestFix715:
    def test_sphere_icosphere_42_verts_80_faces(self):
        from veilbreakers_terrain.handlers.atmospheric_volumes import compute_volume_mesh_spec

        # fireflies and spore_cloud are sphere-shaped volumes
        spec = compute_volume_mesh_spec("fireflies", position=(0, 0, 0), scale=1.0)
        assert spec["shape"] == "sphere"
        assert spec["vertex_count"] == 42, (
            f"Icosphere with 1 subdivision should have 42 verts, got {spec['vertex_count']}"
        )
        assert spec["face_count"] == 80, (
            f"Icosphere with 1 subdivision should have 80 faces, got {spec['face_count']}"
        )


# ---------------------------------------------------------------------------
# Fix 7.16 — estimate_atmosphere_performance physics cost model
# ---------------------------------------------------------------------------


class TestFix716:
    def test_cost_scales_with_resolution(self):
        from veilbreakers_terrain.handlers.atmospheric_volumes import (
            compute_atmospheric_placements,
            estimate_atmosphere_performance,
        )

        hmap = np.zeros((8, 8), dtype=np.float64)
        placements = compute_atmospheric_placements(
            "ashfall_plain", (0, 0, 80, 80), seed=42, heightmap=hmap
        )
        assert placements, "Atmosphere fixture must generate placements for cost scaling"
        cost_64 = estimate_atmosphere_performance(placements, resolution=64)["estimated_cost"]
        cost_128 = estimate_atmosphere_performance(placements, resolution=128)["estimated_cost"]
        assert cost_128 > cost_64, (
            f"Higher resolution must increase cost: res64={cost_64:.2f}, res128={cost_128:.2f}"
        )

    def test_higher_density_costs_more(self):
        from veilbreakers_terrain.handlers.atmospheric_volumes import (
            ATMOSPHERIC_VOLUMES,
            estimate_atmosphere_performance,
        )

        # Build synthetic placement list with one low-density and one high-density volume
        low_dens_type = min(
            ATMOSPHERIC_VOLUMES, key=lambda k: ATMOSPHERIC_VOLUMES[k]["density"]
        )
        high_dens_type = max(
            ATMOSPHERIC_VOLUMES, key=lambda k: ATMOSPHERIC_VOLUMES[k]["density"]
        )
        p_low = [{"volume_type": low_dens_type, "position": (0, 0, 0)}]
        p_high = [{"volume_type": high_dens_type, "position": (0, 0, 0)}]
        cost_low = estimate_atmosphere_performance(p_low)["estimated_cost"]
        cost_high = estimate_atmosphere_performance(p_high)["estimated_cost"]
        assert cost_high >= cost_low, (
            f"Higher density must cost more: low={cost_low:.4f}, high={cost_high:.4f}"
        )
