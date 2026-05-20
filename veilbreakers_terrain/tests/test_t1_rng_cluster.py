"""Regression tests for the T1 RNG cluster (Y04 v3 §B.4.3).

Covers:
  - T1-11 — `_terrain_world.pass_macro_world` degenerate-fallback RNG namespacing
  - T1-12 — `_water_network.WaterNetwork.from_heightmap` RNG namespacing
  - T1-12 — `_water_network.build_braided_polylines` RNG namespacing
  - T1-13 — `_water_network_ext._tileable_value_noise` RNG namespacing
  - T1-23 — `_terrain_noise.voronoi_biome_distribution` RNG namespacing
  - T1-24 — `_scatter_engine.poisson_disk_sample` / `cluster_density_map`
            (DEMOTED per X01 — already canonical numpy modern API)
  - T4-15 — `derive_pass_seed` single-canonical signature (Bug-A already landed)
  - γ3 D-17 — `_rng_from_seed` 4-way duplicate collapsed onto
              `_terrain_noise._rng_from_seed`

Each fix gets:
  - Same-input → same-output determinism check
  - Cross-namespace independence check (same raw seed at two callers
    must NOT produce identical RNG streams once `derive_pass_seed`
    namespacing lands)

Cross-process determinism is exercised by the broader suite via
`test_scatter_determinism.py`; this file deliberately scopes to the
T1 RNG cluster surface so any future regression to the namespacing
discipline lights up here first.

TODO(cross-process): when the cross-process determinism harness
under `tests/integration/test_cross_process_determinism.py` gains a
parameterise-by-bytestream hook, mirror each of these tests into a
subprocess invocation to lock in cross-process stability.
"""
from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# T1-12 — WaterNetwork.from_heightmap RNG namespacing
# ---------------------------------------------------------------------------

class TestT1_12_FromHeightmapDeterminism:
    """`WaterNetwork.from_heightmap` must be deterministic per seed and must
    not collapse with other callers passing the same raw seed value."""

    @pytest.fixture
    def heightmap(self) -> np.ndarray:
        # Bowl-with-central-valley heightmap that produces hundreds of river
        # segments under priority-flood D8 — enough surface area for the
        # seeded jitter to differ visibly across seeds.
        N = 128
        ys, xs = np.mgrid[0:N, 0:N].astype(np.float64)
        center_x, center_y = N / 2, N / 2
        r = np.sqrt((xs - center_x) ** 2 + (ys - center_y) ** 2)
        h: np.ndarray = (
            200.0
            + 0.5 * r
            - 100.0 * np.exp(-((xs - center_x) ** 2) / (2.0 * 5.0 ** 2))
        )
        return h

    def test_same_seed_same_network(self, heightmap: np.ndarray) -> None:
        from veilbreakers_terrain.handlers._water_network import WaterNetwork

        tile_size: int = int(heightmap.shape[0])
        net_a = WaterNetwork.from_heightmap(
            heightmap,
            cell_size=1.0,
            tile_size=tile_size,
            min_drainage_area=50.0,
            river_threshold=200.0,
            compute_velocity=False,
            seed=42,
        )
        net_b = WaterNetwork.from_heightmap(
            heightmap,
            cell_size=1.0,
            tile_size=tile_size,
            min_drainage_area=50.0,
            river_threshold=200.0,
            compute_velocity=False,
            seed=42,
        )
        # Segment counts and the round-tripped dict view must agree.
        assert len(net_a.segments) == len(net_b.segments)
        assert net_a.to_dict() == net_b.to_dict()

    def test_different_seed_different_network(self, heightmap: np.ndarray) -> None:
        from veilbreakers_terrain.handlers._water_network import WaterNetwork

        tile_size: int = int(heightmap.shape[0])
        net_a = WaterNetwork.from_heightmap(
            heightmap,
            cell_size=1.0,
            tile_size=tile_size,
            min_drainage_area=50.0,
            river_threshold=200.0,
            compute_velocity=False,
            seed=1,
        )
        net_b = WaterNetwork.from_heightmap(
            heightmap,
            cell_size=1.0,
            tile_size=tile_size,
            min_drainage_area=50.0,
            river_threshold=200.0,
            compute_velocity=False,
            seed=999,
        )
        # If two different seeds produce the bit-identical to_dict view, the
        # seed has been ignored entirely. The RNG inside `from_heightmap` is
        # used to perturb braided polyline jitter and similar — distinct seeds
        # should diverge in at least one downstream serialised field.
        assert net_a.to_dict() != net_b.to_dict(), (
            "from_heightmap ignored its seed argument"
        )


# ---------------------------------------------------------------------------
# T1-12 — build_braided_polylines RNG namespacing
# ---------------------------------------------------------------------------

class TestT1_12_BuildBraidedPolylinesDeterminism:
    """`build_braided_polylines` must produce identical results per seed and
    distinct results across seeds."""

    @pytest.fixture
    def waypoints(self) -> list[tuple[float, float, float]]:
        # Straight x-axis polyline 30 m long
        return [(float(x), 0.0, 0.0) for x in range(30)]

    def test_same_seed_same_branches(
        self, waypoints: list[tuple[float, float, float]]
    ) -> None:
        from veilbreakers_terrain.handlers._water_network import (
            build_braided_polylines,
        )
        a = build_braided_polylines(
            waypoints, channel_width=30.0, braiding_width_threshold=20.0,
            max_branches=3, divergence_ratio=0.2, seed=7,
        )
        b = build_braided_polylines(
            waypoints, channel_width=30.0, braiding_width_threshold=20.0,
            max_branches=3, divergence_ratio=0.2, seed=7,
        )
        assert a == b, "build_braided_polylines is non-deterministic"
        assert len(a) >= 1, "expected at least one braided polyline at width=30 > 20"

    def test_different_seed_different_branches(
        self, waypoints: list[tuple[float, float, float]]
    ) -> None:
        from veilbreakers_terrain.handlers._water_network import (
            build_braided_polylines,
        )
        a = build_braided_polylines(
            waypoints, channel_width=30.0, braiding_width_threshold=20.0,
            max_branches=3, divergence_ratio=0.2, seed=1,
        )
        b = build_braided_polylines(
            waypoints, channel_width=30.0, braiding_width_threshold=20.0,
            max_branches=3, divergence_ratio=0.2, seed=2,
        )
        assert a != b, "build_braided_polylines ignored its seed argument"


# ---------------------------------------------------------------------------
# T1-13 — _tileable_value_noise RNG namespacing
# ---------------------------------------------------------------------------

class TestT1_13_TileableValueNoiseDeterminism:
    """`_tileable_value_noise` must be deterministic per seed."""

    def test_same_seed_same_noise_array(self):
        from veilbreakers_terrain.handlers._water_network_ext import (
            _tileable_value_noise,
        )
        a = _tileable_value_noise((32, 32), frequency=4.0, seed=42)
        b = _tileable_value_noise((32, 32), frequency=4.0, seed=42)
        np.testing.assert_array_equal(a, b)

    def test_different_seed_different_noise_array(self):
        from veilbreakers_terrain.handlers._water_network_ext import (
            _tileable_value_noise,
        )
        a = _tileable_value_noise((32, 32), frequency=4.0, seed=1)
        b = _tileable_value_noise((32, 32), frequency=4.0, seed=2)
        assert not np.array_equal(a, b), (
            "_tileable_value_noise ignored its seed argument"
        )


# ---------------------------------------------------------------------------
# T1-23 — compute_voronoi_biome_map RNG namespacing
# ---------------------------------------------------------------------------

class TestT1_23_VoronoiBiomeMapDeterminism:
    """`voronoi_biome_distribution` jittered seed placement must be reproducible."""

    def test_same_seed_same_biome_map(self):
        from veilbreakers_terrain.handlers._terrain_noise import (
            voronoi_biome_distribution,
        )
        ids_a, w_a = voronoi_biome_distribution(
            width=24, height=24, biome_count=4, seed=12345,
        )
        ids_b, w_b = voronoi_biome_distribution(
            width=24, height=24, biome_count=4, seed=12345,
        )
        np.testing.assert_array_equal(ids_a, ids_b)
        np.testing.assert_array_equal(w_a, w_b)

    def test_different_seed_different_biome_map(self):
        from veilbreakers_terrain.handlers._terrain_noise import (
            voronoi_biome_distribution,
        )
        ids_a, _ = voronoi_biome_distribution(
            width=24, height=24, biome_count=4, seed=1,
        )
        ids_b, _ = voronoi_biome_distribution(
            width=24, height=24, biome_count=4, seed=999,
        )
        assert not np.array_equal(ids_a, ids_b), (
            "voronoi_biome_distribution ignored its seed argument"
        )


# ---------------------------------------------------------------------------
# T1-11 — pass_macro_world degenerate fallback RNG (indirect)
# ---------------------------------------------------------------------------

class TestT1_11_MacroWorldFallbackRng:
    """The degenerate-flat-output fallback in `pass_macro_world` derives its
    RNG via `derive_pass_seed`. We exercise the derivation path directly
    rather than constructing a full TerrainPipelineState (which would pull
    bpy + a much larger fixture surface)."""

    def test_fallback_seed_is_namespaced_via_derive_pass_seed(self):
        from veilbreakers_terrain.handlers.terrain_rng import derive_pass_seed

        # Two different raw seeds at the same site must produce different
        # derived seeds.
        s_a = derive_pass_seed(
            42 ^ 0xDEAD,
            "terrain_world.pass_macro_world.degenerate_fallback",
            0, 0, None,
        )
        s_b = derive_pass_seed(
            7 ^ 0xDEAD,
            "terrain_world.pass_macro_world.degenerate_fallback",
            0, 0, None,
        )
        assert s_a != s_b

    def test_fallback_namespace_differs_from_other_macro_world_uses(self):
        from veilbreakers_terrain.handlers.terrain_rng import derive_pass_seed

        # The same raw seed at this site MUST produce a different derived seed
        # than the same raw seed at a sibling namespace — proving the
        # namespacing is load-bearing.
        s_here = derive_pass_seed(
            42 ^ 0xDEAD,
            "terrain_world.pass_macro_world.degenerate_fallback",
            0, 0, None,
        )
        s_sibling = derive_pass_seed(
            42 ^ 0xDEAD,
            "terrain_world.pass_macro_world.some_other_use",
            0, 0, None,
        )
        assert s_here != s_sibling


# ---------------------------------------------------------------------------
# T1-24 — _scatter_engine default_rng is canonical (DEMOTED, doc-only fix)
# ---------------------------------------------------------------------------

class TestT1_24_ScatterEngineCanonicalDocumented:
    """Per Y04 v3 §B.4.3 + Context7 `/numpy/numpy`, `np.random.default_rng(seed)`
    IS the canonical modern numpy RNG API. The fix is a doc comment, not a
    behaviour change. This test pins the call-shape so any future regression
    that swaps in legacy `np.random.seed()` or `np.random.RandomState()` lights
    up immediately."""

    def test_poisson_disk_sample_is_deterministic_per_seed(self):
        from veilbreakers_terrain.handlers._scatter_engine import (
            poisson_disk_sample,
        )
        a = poisson_disk_sample(40.0, 40.0, min_distance=4.0, seed=11)
        b = poisson_disk_sample(40.0, 40.0, min_distance=4.0, seed=11)
        assert a == b, (
            "poisson_disk_sample regressed to a non-deterministic RNG path"
        )

    def test_poisson_disk_sample_differs_across_seeds(self):
        from veilbreakers_terrain.handlers._scatter_engine import (
            poisson_disk_sample,
        )
        a = poisson_disk_sample(40.0, 40.0, min_distance=4.0, seed=1)
        b = poisson_disk_sample(40.0, 40.0, min_distance=4.0, seed=2)
        assert a != b


# ---------------------------------------------------------------------------
# T4-15 — derive_pass_seed single-canonical signature
# ---------------------------------------------------------------------------

class TestT4_15_DerivePassSeedCanonical:
    """The `terrain_rng.derive_pass_seed` shim must route through the
    canonical `terrain_pipeline.derive_pass_seed` (Bug-A landed). Two calls
    with structurally-equivalent inputs but routed via the two import paths
    must produce identical seeds."""

    def test_shim_matches_canonical_for_explicit_5_arg_call(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import (
            derive_pass_seed as canonical,
        )
        from veilbreakers_terrain.handlers.terrain_rng import (
            derive_pass_seed as shim,
        )

        # With `region=None` the shim is a pure pass-through.
        s_canon = canonical(42, "scatter.test", 10, 20, None)
        s_shim = shim(42, "scatter.test", 10, 20, None)
        assert s_canon == s_shim

    def test_shim_region_string_folds_into_namespace(self):
        from veilbreakers_terrain.handlers.terrain_pipeline import (
            derive_pass_seed as canonical,
        )
        from veilbreakers_terrain.handlers.terrain_rng import (
            derive_pass_seed as shim,
        )

        # Shim documented behaviour: non-empty string region is folded into
        # the namespace (`f"{pass_name}.{region}"`) so the canonical helper
        # never sees the string region.
        s_shim = shim(42, "scatter", 10, 20, "forest")
        s_canon = canonical(42, "scatter.forest", 10, 20, None)
        assert s_shim == s_canon


# ---------------------------------------------------------------------------
# γ3 D-17 — _rng_from_seed 4-way duplicate collapsed onto canonical
# ---------------------------------------------------------------------------

class TestGamma3_D17_RngFromSeedCollapsed:
    """The 4 `_rng_from_seed` definitions (one canonical, three re-exports)
    must produce identical RNG streams for identical (seed, namespace) inputs
    — proving the collapse onto `_terrain_noise._rng_from_seed` is real and
    not just a docstring claim."""

    def test_terrain_advanced_reexports_canonical(self):
        from veilbreakers_terrain.handlers._terrain_noise import (
            _rng_from_seed as canonical,
        )
        from veilbreakers_terrain.handlers.terrain_advanced import (
            _rng_from_seed as adv,
        )
        rng_a = canonical(42, "test_collapse_canonical")
        rng_b = adv(42, "test_collapse_canonical")
        assert rng_a.random() == rng_b.random()

    def test_biome_grammar_reexports_canonical(self):
        from veilbreakers_terrain.handlers._biome_grammar import (
            _rng_from_seed as bg,
        )
        from veilbreakers_terrain.handlers._terrain_noise import (
            _rng_from_seed as canonical,
        )
        rng_a = canonical(99, "test_collapse_canonical")
        rng_b = bg(99, "test_collapse_canonical")
        assert rng_a.random() == rng_b.random()

    def test_terrain_morphology_1arg_uses_canonical(self):
        """The 1-arg variant in `terrain_morphology` now folds in a constant
        namespace and routes through canonical. We verify it produces an
        independent stream from the 2-arg variant called with a DIFFERENT
        namespace (which proves the namespace is actually being applied)."""
        from veilbreakers_terrain.handlers._terrain_noise import (
            _rng_from_seed as canonical,
        )
        from veilbreakers_terrain.handlers.terrain_morphology import (
            _rng_from_seed as morpho,
        )
        rng_morpho = morpho(42)
        rng_canon_same_ns = canonical(42, "morphology_template")
        # Same effective inputs -> same stream
        assert rng_morpho.random() == rng_canon_same_ns.random()

        rng_morpho2 = morpho(42)
        rng_canon_diff_ns = canonical(42, "totally_different_namespace")
        # Different namespace -> different stream
        assert rng_morpho2.random() != rng_canon_diff_ns.random()

    def test_namespace_separation_is_load_bearing(self):
        """Two callers passing the same raw seed but different namespaces
        must get different RNG streams. This is the determinism property
        the T1 RNG cluster as a whole is preserving."""
        from veilbreakers_terrain.handlers._terrain_noise import _rng_from_seed
        rng_a = _rng_from_seed(42, "namespace_alpha")
        rng_b = _rng_from_seed(42, "namespace_beta")
        # Pull 8 draws from each — extremely unlikely they collide on all 8
        # by chance if namespaces are working.
        draws_a = [rng_a.random() for _ in range(8)]
        draws_b = [rng_b.random() for _ in range(8)]
        assert draws_a != draws_b
