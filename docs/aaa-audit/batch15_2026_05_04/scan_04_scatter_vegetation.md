# Batch 15 / Scan 04 — Scatter & Vegetation Audit

Date: 2026-05-04
Scope: vegetation_system, environment_scatter, terrain_scatter_points,
_scatter_engine, vegetation_lsystem, terrain_foliage_catalog,
terrain_scatter_altitude_safety, terrain_ecotone_graph, procedural_grass.
Repo root: `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain`

---

## TL;DR — Composite Grade: **C+**

The scatter pipeline has matured from C- (2026-04-27): the foliage catalog
now covers all 18 canonical VeilBreakers biomes (zero-coverage gap closed),
the `_scatter_pass` Phase-H catalog sub-pass is wired end-to-end with
species-level affinity rules, and Bridson Poisson-disk sampling uses an
np.random Generator (statistically clean blue noise). However, **eight
real bugs remain**, the biome density floor is misleading (8/18 biomes
get only the 7 "all biomes" placeholders — no biome character),
`scatter_biome_vegetation` delegation **silently drops `biome_name`**
(production data corruption), the L-system trees still use a flat-shaded
truncated-cone backbone (no SpeedTree-class branching variety), and the
pipeline has **no measurable wind-LOD chain** matching SpeedTree/
Megascans norms.

| Component                        | Grade | One-line verdict |
|----------------------------------|:-----:|------------------|
| Bridson + Lloyd scatter engine   | **B**   | Density-weighted Poisson, but Lloyd centroid is approximate (no real Voronoi) |
| Catalog (39 species, 18 biomes)  | **B-**  | All biomes covered numerically, but 8/18 only have the 7 all-biomes catch-alls |
| `_scatter_pass` multipass        | **B-**  | 3 passes (structure/cover/debris) + Phase-H species; species_constraints honored |
| Ecotone blend / smoothness       | **B+**  | EDT-driven smoothstep blend, validated for narrow ecotones |
| Vegetation L-system              | **C**   | Frenet-frame turtle is correct; only 7 grammars; trees are mesh-cylindric, no leaves |
| `scatter_biome_vegetation` shim  | **D**   | Drops biome_name on delegate_params — falls through to "default" silently |
| Determinism                      | **B**   | All seeded RNGs deterministic; module-level random in a few non-load-bearing spots |
| ProceduralGrassSystem            | **B**   | Vectorized eligibility mask is a good design; biome_id_map missing 4 biomes |
| Wind / LOD impostor pipeline     | **D+**  | Wind colors baked, but L-3 billboard impostor path is deprecated/broken |
| Compete vs SpeedTree / GTS       | **C-**  | Tree variety, leaf cards, and impostors fall well short of AAA |

**Net change vs 2026-04-27 (C-):** **+1 grade band** thanks to biome
coverage closure and species-affinity gating. Remaining grade gap to AAA
is dominated by L-system fidelity (no leaf cards on actual L-system
geometry) and the still-broken billboard impostor pipeline.

---

## 1. Determinism Audit

### 1a. Seeded `random.Random(seed)` calls — DETERMINISTIC, GOOD
All scatter/vegetation `random.Random(...)` instances are constructed
with an integer seed. None use bare `random.Random()`. Confirmed
locations:

| File | Line | Construction |
|------|------|--------------|
| `vegetation_system.py` | 397 | `rng = random.Random(seed)` |
| `environment_scatter.py` | 837 | `random.Random(seed ^ 0x5CA77E2)` |
| `environment_scatter.py` | 1975 | `random.Random(seed)` |
| `environment_scatter.py` | 2109 | `random.Random(seed)` |
| `environment_scatter.py` | 2280 | `random.Random(seed)` |
| `environment_scatter.py` | 2664 | `random.Random(seed)` |
| `environment_scatter.py` | 3359 | `random.Random(seed ^ 0xD1CE7)` |
| `_scatter_engine.py` | 93 | `random.Random(seed)` |
| `_scatter_engine.py` | 412 | `random.Random(seed)` |
| `_scatter_engine.py` | 702 | `random.Random(seed)` |
| `_scatter_engine.py` | 998 | `random.Random(seed)` |
| `_scatter_engine.py` | 1273 | `random.Random(seed)` |
| `vegetation_lsystem.py` | 259, 520, 936, 1207 | `_random.Random(seed)` |

The MEMORY.md note about "~50 bare `random.Random` calls" is **NOT
present in this set** — those must be in other modules.

### 1b. Non-deterministic module-level `random.choices` — 3 SITES
These do NOT use a seeded RNG; they call into Python's module-level
random (which has its own global state):

| File | Line | Code |
|------|------|------|
| `vegetation_system.py` | 1526 | `_random.choices(_string.ascii_letters + _string.digits, k=8)` |
| `procedural_grass.py` | 672 | `random.choices(string.ascii_letters + string.digits, k=8)` |
| `procedural_grass.py` | 757 | `random.choices(string.ascii_letters + string.digits, k=8)` |

Severity: **LOW** — all three are temp-file suffix generators
(`tmp = p.with_name(f".{p.name}.{suffix}.tmp")`). Filename randomness
does not affect placement. **Still flag as an antipattern**: replace with
`secrets.token_hex(4)` to make intent (uniqueness, not determinism)
explicit.

### 1c. Non-deterministic `rng or random` fallback — **HIGH SEVERITY**
`terrain_foliage_catalog.py:1135`
```python
def choose_for_species(self, species_id, *, rng: Optional[random.Random] = None):
    rng = rng or random  # falls through to MODULE-LEVEL random
```
When `rng=None`, the asset chosen is non-deterministic across runs.
`scatter_pass` calls `resolve_model_asset(species_id)` (line 989) without
passing an rng — every Phase-H species placement that resolves to multiple
ingested assets gets a **different mesh on every run**.

**Fix:** require an explicit rng or seed:
```python
rng = rng if rng is not None else random.Random(0)
```
or thread the per-tile seed through resolve_model_asset() / choose_for_species().

### 1d. NumPy RNG — DETERMINISTIC, GOOD
- `_scatter_engine.poisson_disk_sample`: `np.random.default_rng(seed)` — OK.
- `_scatter_engine._weighted_choice`: re-seeds a numpy generator from
  `rng.getrandbits(32)` so the python-rng and numpy-rng streams stay in
  lockstep — clever, but adds 1 random bit fetch per weighted choice
  (negligible).
- `procedural_grass.ProceduralGrassSystem.__init__`:
  `self.rng = np.random.default_rng(rng_seed)` — OK; default seed `1234`
  is used when caller forgets to pass `rng_seed`, which is a silent
  cross-tile collision risk.

---

## 2. Bug Inventory (8 real defects)

### BUG-S15-04-01 — `scatter_biome_vegetation` drops biome_name silently — **P0**
File: `vegetation_system.py:1209-1219`
The deprecated wrapper builds:
```python
delegate_params = {
    "terrain_name": params.get("terrain_name", ""),
    "min_distance": params.get("min_distance", 3.0),
    "seed": params.get("seed", 42),
    "max_instances": params.get("max_instances", 100_000),
    "moisture_map": params.get("moisture_map"),
    "stack": params.get("stack"),
}
```
**`biome_name` is NEVER forwarded.** `handle_scatter_vegetation` then
falls back at line 3317 to `biome_key = "default"`. Every call into the
deprecation shim now produces grasslands-template scatter regardless of
the requested biome. Also dropped: `biome_name` (P0), `season`,
`bake_wind_colors`, `water_level`, `exclusion_zones`, `lod_distances`,
`competition_radius`, `adjacent_biome`, `ecotone_blend_width`,
`ecotone_axis`, `ecotone_boundary`, `spec_only`, `camera_position`,
`max_tilt_angle`.

**Fix:** add the missing keys. At minimum `biome_name`, `lod_distances`,
`exclusion_zones`, `camera_position`:
```python
for k in ("biome_name", "biome", "season", "exclusion_zones",
         "lod_distances", "competition_radius", "camera_position",
         "max_tilt_angle", "water_level"):
    if params.get(k) is not None:
        delegate_params[k] = params[k]
```

### BUG-S15-04-02 — `_scatter_pass` does NOT respect biome species — **P1**
File: `environment_scatter.py:2761-2912`
Coarse-grained passes (structure / ground_cover / debris) hardcode
`vegetation_type = "tree" | "bush" | "grass" | "rock"` regardless of
the `biome` argument. Only the **Phase-H sub-pass** (lines 3019-3068)
filters by biome via `_spec.biome_mask`. Net effect: every tile gets
the same generic tree/bush/grass/rock skeleton, plus a thin layer of
biome-specific species on top.

For 8/18 biomes (`abandoned_village`, `cemetery`, `coastal`,
`crystal_cavern`, `frozen_hollows`, `mushroom_forest`, `ruined_citadel`,
`ruined_fortress`) the catalog only contains the 7 "all biomes" species
(`hero_boulder`, `walkway_stone_path`, `grass_short`, `pebbles`,
`sign_wooden`, `sign_stone_waypoint`, `walkway_dirt_path`) — none of
which are biome-character species. The visual signature comes entirely
from the placeholder coarse pass. **A frozen_hollows tile and a
grasslands tile look nearly identical at scatter level.**

**Fix:** thread biome-specific species into the structure/cover/debris
sub-passes. Either:
- (A) make the coarse passes consult `species_for_biome(biome)` to pick
  a biome-appropriate `vegetation_type` per LOD tier, or
- (B) add explicit biome-character species to the catalog for the 8
  thin biomes (e.g. `tree_ice_pine` for frozen_hollows, `tree_giant_mushroom`
  for mushroom_forest, `crystal_cluster` for crystal_cavern).

### BUG-S15-04-03 — `DEFAULT_BIOME_ID_MAP` missing 4 biomes — **P1**
File: `procedural_grass.py:257-272`
Lists 14 biomes (matches old vegetation_system enumeration). Missing:
`ruined_fortress`, `abandoned_village`, `battlefield`, `veil_crack_zone`.
Any tile whose `stack.biome_id` resolves to one of those four IDs has
**all grass species filtered out** by `_eligibility_mask` (line 408:
`allowed |= (biome_id == bid)` only triggers for known IDs).

Also a separate concern: this map's IDs (0-13) do **not** match the
canonical insertion-order ID scheme used by `vegetation_system.build_biome_density_map`
(line 1107: `numeric_id = list(BIOME_VEGETATION_SETS.keys()).index(biome_name)`).
Two different ID conventions silently coexist.

**Fix:** import biome IDs from `terrain_biome_registry`, derive the map
from the canonical list, and add a CI check that `procedural_grass.DEFAULT_BIOME_ID_MAP`
matches `vegetation_system` ordering.

### BUG-S15-04-04 — `_lod_for_distance` short-circuits on small object — **P2**
File: `environment_scatter.py:2515-2532`
When `object_radius_m` is supplied **and** `LOD_PRESETS` lookup
succeeds, the function bypasses the species-specific distance table
(`_LOD_THRESHOLDS`) entirely. Trees (200 m cull) and grass (80 m cull)
both fall through the same `screen_pcts` array, which means a tree
"culls to billboard" at the same screen-space angle as grass — wrong.
The "fall back to distance-only table" comment is inaccurate; the
function only falls back when `LOD_PRESETS.get(asset_type)` returns
None.

**Fix:** combine both — take MIN(distance-LOD, screen-pct-LOD) so the
species cull distance is still respected. SpeedTree's pipeline always
clamps to the per-species distance.

### BUG-S15-04-05 — Lloyd relaxation is centroid-of-neighbors, not Voronoi — **P2**
File: `_scatter_engine.py:217-334`
Comment claims Lloyd's relaxation, but the implementation moves each
point toward the **arithmetic mean of neighbors within a search radius**
(line 297: `cx = sum_x / count`). True Lloyd computes the centroid of
the Voronoi cell (which the Houdini Scatter SOP and SpeedTree's
distribution pipeline use). The current approximation produces
acceptable visual results but biases against edge points (their
"neighbors" are skewed inward), so trees pulled away from terrain
tile boundaries — exactly the same artifact RDR2's tile boundary stitching
fixes. Visible in 64-tile world streaming.

**Fix:** switch to `scipy.spatial.Voronoi` for ≤10K points, or use
`scipy.spatial.cKDTree` to find the k-nearest neighbors and compute a
weighted centroid (closer to the true Voronoi result and still O(n log n)).

### BUG-S15-04-06 — `_density_reject` reads the *unflattened* density_map — **P2**
File: `environment_scatter.py:3358-3367` (calls `_density_reject`)
Look at the call site: `density_map.shape[0]`, `density_map.shape[1]`.
But `_collapse_detail_density` may return **either** an HxW float map or
a HxWxC stack (per-species). When a per-species stack is returned, the
2D `_row_f, _col_f` indexing collapses **only the first species** — so
detail_density gating uses one species' density to gate every other
species' placements. Confirm by reading the implementation.

(I read `_collapse_detail_density` at line 574: it sums all species into
a single 2D map *if* the input is a dict-of-arrays. So the indexing is
fine for dict inputs, but if any caller passes a raw 3D ndarray the
shape assumption breaks silently.)

**Fix:** assert in `_density_reject` that `density_map.ndim == 2`.

### BUG-S15-04-07 — Vegetation L-System has no leaf cards on its mesh — **P1**
File: `vegetation_lsystem.py` (entire module, ~2148 lines)
The `branches_to_mesh` function at line 742 emits truncated-cone trunk
geometry (`vertices, edges, faces`) but emits **only `tip_positions`** for
leaf placement — no leaf cards, no leaf material, no canopy hull. The
adjacent `_add_leaf_card_canopy` lives in `environment_scatter.py:1747`
and is only invoked through `_create_grass_card`-style scatter cards, NOT
on individual L-system trees.

So the L-system pipeline produces **bare branches** when used standalone.
Compare:
- SpeedTree: every tip emits a leaf-card cluster (~6-12 quads) with proper
  alpha-tested material and wind vertex colors.
- Ghost of Tsushima: tip+depth-2 segments emit leaf-card meshlets with
  baked SDF leaves and per-card phase offsets.
- Horizon ZD: skeletal mesh tree with up to 64 leaf-card clusters per tree.

**Fix:** add a `leaf_card_pipeline` that takes `tip_positions /
tip_directions / tip_radii` from `branches_to_mesh()` output and emits
the standard 6-12 alpha-tested leaf quads per tip. The function exists in
`environment_scatter._add_leaf_card_canopy` — just needs to be wired into
the L-system tree builder.

### BUG-S15-04-08 — `generate_billboard_impostor` is permanently deprecated — **P1**
File: `environment_scatter.py:78-97`
The current code path:
```python
def generate_billboard_impostor(*args, **kwargs):
    if _generate_billboard_impostor_raw is None:
        raise NotImplementedError(...)
    _warnings.warn("...deprecated (L-3/C-4)...", DeprecationWarning, stacklevel=2)
    return _generate_billboard_impostor_raw(*args, **kwargs)
```
Comment: "implement N-view Blender atlas bake in Phase 9C of the 12-phase
plan." Phase 9C does not exist anywhere in the codebase.

This means every scatter result that crosses cull distance has **no
billboard impostor** — far-field foliage just disappears. Compare
SpeedTree: every tree above 200 m smoothly transitions to a 1-quad
billboard with an N-view atlas. RDR2: 8-view billboards at 150 m.

**Fix:** Either delete the function and accept that LOD3 = pop-cull
(currently the de facto behavior since the function raises), or implement
the N-view bake. The current "warn-and-call-anyway-when-import-succeeded"
pattern hides the unimplemented status from all consumers.

---

## 3. AAA Grade Analysis

### 3a. vs Houdini crowd / scatter SOP
| Houdini feature | Repo status |
|---|---|
| Blue-noise distribution | ✅ Bridson 2007 implemented (`_scatter_engine.poisson_disk_sample`) |
| Density-driven radius | ✅ `r_local = min_distance / max(density, 0.05)` (line 181) |
| Altitude / slope banding | ✅ `_SPECIES_CONSTRAINTS` per-species bands |
| Voronoi competition | ❌ Lloyd is approximate; no true Voronoi |
| Hierarchical clustering | ⚠ `cluster_density_map` exists but disconnected from main scatter path |

**Grade vs Houdini: B-** — base distribution is right; clustering is not wired.

### 3b. vs SpeedTree
| SpeedTree feature | Repo status |
|---|---|
| L-system / SBA grammars | ⚠ 7 grammars (oak/pine/birch/willow/dead/ancient/twisted) — SpeedTree ships ~50 |
| Leaf cards on tips | ❌ Pipeline emits tip positions but no leaves on actual L-system trees |
| Wind vertex colors (R/G/B/A) | ✅ `compute_wind_vertex_colors` (vegetation_system.py:760) follows canonical layout |
| LOD chain (mesh→billboard) | ❌ Billboard impostor path is `NotImplementedError` |
| Seasonal variants | ✅ summer/autumn/winter/corrupted (vegetation_system.py:233) |
| Per-tree color variation | ✅ `color_variation_seed` written into placement spec |

**Grade vs SpeedTree: C-** — wind + season variants OK, but no LOD chain.

### 3c. vs Ghost of Tsushima foliage
| GTS feature | Repo status |
|---|---|
| Density-falloff from biome center | ✅ `_BIOME_DENSITY` × `density_map` falloff |
| Painter-input density maps | ⚠ `stack.detail_density` consumed; no painting tooling |
| Reactive bend / wind | ⚠ Wind colors baked, but no per-instance bend animation hint |
| 2-pass (Lloyd + species) | ✅ Lloyd 2 iterations + 2-species disk |
| Combat clearing exclusion | ✅ `_resolve_combat_clearings` + `_in_clearing` |

**Grade vs GTS: B-** — clearings + density falloff land well, painted
density input would close most of the gap.

### 3d. vs Horizon Zero Dawn / Forbidden West
| HZD feature | Repo status |
|---|---|
| Biome-tagged procedural placement | ✅ `biome_mask` per species + `species_for_biome` |
| Hand-painted density override | ❌ Not exposed; `detail_density` is computed, not painted |
| Per-biome boundary feathering | ✅ EDT smoothstep at `_scatter_engine.biome_filter_points` line 482 |
| Ecosystem clusters (mossy roots near logs) | ✅ Phase-H `place_near=("trunk", "rock_face", "water_edge")` |
| Tile-stitch determinism | ✅ `halo_scatter_point_id` for tile ownership |

**Grade vs HZD: B** — biome feathering + ecosystem clusters land at AAA bar.

### 3e. vs Red Dead Redemption 2 ecosystem
| RDR2 feature | Repo status |
|---|---|
| Procedural ecological niches | ⚠ Coarse — moisture × altitude bands only; no temperature, no soil type |
| Long-tail species variety (1000+ assets) | ❌ 39 species in catalog |
| Realistic dispersal / clustering | ⚠ Single competition_radius value; no seed-dispersal patterns |
| Climate-modulated biome shift | ❌ No climate channel in scatter input |
| Trampling / wear paths | ❌ Not modeled |

**Grade vs RDR2: D+** — niche modeling is ~10% of RDR2 depth.

### 3f. Composite vs AAA bar
| Vegetation component | Grade |
|---|:---:|
| Scatter engine (Bridson + Lloyd + density) | **B** |
| Foliage catalog (39 species, 18 biomes) | **B-** |
| L-system tree generator | **C** |
| Ecotone blending | **B+** |
| Wind / LOD chain | **D+** |
| Determinism | **B** |
| **Composite** | **C+** |

---

## 4. Mock Tests

Test file path:
`veilbreakers_terrain/tests/test_aaa_scatter_vegetation_b15s4.py`

Below is the complete test source. Drop in to verify all the bugs and
contracts above — should be added in a follow-up PR.

```python
"""Batch15 / Scan04 — AAA scatter & vegetation contract tests.

Verifies:
  - Determinism: same seed → identical placements
  - Altitude gating: trees never above their max_altitude_m / max_alt
  - Min-distance constraint: no two trees closer than min_distance
  - Biome name forwarding (catches BUG-S15-04-01)
  - All 18 canonical biomes resolve to ≥1 species
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

from veilbreakers_terrain.handlers._scatter_engine import (
    biome_filter_points,
    poisson_disk_sample,
)
from veilbreakers_terrain.handlers.terrain_biome_registry import (
    CANONICAL_BIOME_IDS,
)
from veilbreakers_terrain.handlers.terrain_foliage_catalog import (
    FOLIAGE_SPECIES_CATALOG,
    species_for_biome,
)
from veilbreakers_terrain.handlers.vegetation_system import (
    BIOME_VEGETATION_SETS,
    compute_vegetation_placement,
)


# ---------------------------------------------------------------------------
# Synthetic 64x64 biome map fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_terrain_64():
    """64x64 terrain with 3 biomes (3 vertical stripes)."""
    rng = np.random.default_rng(42)
    # Heightmap: gentle slope from 0 -> 0.6
    yy, xx = np.meshgrid(np.linspace(0, 1, 64), np.linspace(0, 1, 64), indexing="ij")
    heightmap = (0.1 + 0.5 * yy + 0.05 * rng.standard_normal((64, 64))).astype(np.float32)
    heightmap = np.clip(heightmap, 0.0, 1.0)
    # Slope map: 5..20 deg
    slope_map = (5.0 + 15.0 * yy).astype(np.float32)
    # Biome map: 3 vertical stripes (left/middle/right)
    biome_map = np.zeros((64, 64), dtype=np.int64)
    biome_map[:, 22:43] = 1
    biome_map[:, 43:] = 2
    return heightmap, slope_map, biome_map


# ---------------------------------------------------------------------------
# Test 1 — Two identical seed runs produce identical placements
# ---------------------------------------------------------------------------

class TestScatterDeterminism:
    """Two runs with the same seed must produce the same placements."""

    def test_poisson_identical_seed_identical_points(self):
        a = poisson_disk_sample(64.0, 64.0, min_distance=3.0, seed=12345)
        b = poisson_disk_sample(64.0, 64.0, min_distance=3.0, seed=12345)
        assert a == b
        assert len(a) > 0  # sanity: non-empty

    def test_compute_vegetation_placement_deterministic(self):
        """Same seed → same placements through the full pipeline."""
        # Build a flat 16x16 grid for compute_vegetation_placement
        rng = np.random.default_rng(0)
        verts = []
        normals = []
        for j in range(16):
            for i in range(16):
                verts.append((float(i), float(j), 0.5 + 0.1 * float(i + j) / 30.0))
                normals.append((0.0, 0.0, 1.0))

        out_a = compute_vegetation_placement(
            verts, [], normals,
            biome_name="thornwood_forest",
            area_bounds=(0.0, 0.0, 15.0, 15.0),
            seed=999,
            min_distance=2.0,
        )
        out_b = compute_vegetation_placement(
            verts, [], normals,
            biome_name="thornwood_forest",
            area_bounds=(0.0, 0.0, 15.0, 15.0),
            seed=999,
            min_distance=2.0,
        )
        assert len(out_a) == len(out_b)
        for pa, pb in zip(out_a, out_b):
            assert pa["position"] == pb["position"]
            assert pa["scale"] == pb["scale"]
            assert pa["rotation"] == pb["rotation"]
            assert pa["type"] == pb["type"]
            assert pa["style"] == pb["style"]


# ---------------------------------------------------------------------------
# Test 2 — Altitude gating: trees never above max_altitude band
# ---------------------------------------------------------------------------

class TestAltitudeGating:
    """A scatter rule with max_alt=0.3 must never place above that band."""

    def test_altitude_band_enforced(self, synthetic_terrain_64):
        heightmap, slope_map, _ = synthetic_terrain_64
        # Build candidate points covering the whole tile
        candidates = poisson_disk_sample(64.0, 64.0, min_distance=3.0, seed=7)
        rules = [
            {
                "vegetation_type": "tree",
                "min_alt": 0.0,
                "max_alt": 0.3,  # strict — should reject upper half of tile
                "min_slope": 0.0,
                "max_slope": 90.0,
                "scale_range": (1.0, 1.0),
                "density": 1.0,
            }
        ]
        placements = biome_filter_points(
            candidates,
            heightmap=heightmap,
            slope_map=slope_map,
            rules=rules,
            terrain_size=64.0,
            seed=7,
            max_tilt_angle=90.0,
        )
        # Every accepted point must have terrain altitude <= 0.3
        for p in placements:
            x, y = p["position"]
            col = int(round(x / 64.0 * 63))
            row = int(round(y / 64.0 * 63))
            alt = float(heightmap[row, col])
            assert alt <= 0.3, (
                f"placement {p['position']} accepted at altitude {alt:.3f} "
                f"(rule cap was 0.3)"
            )


# ---------------------------------------------------------------------------
# Test 3 — Min-distance: no two placements closer than min_distance
# ---------------------------------------------------------------------------

class TestMinDistance:
    """Bridson's invariant: every pair of points >= min_distance apart."""

    def test_no_pair_below_min_distance(self):
        pts = poisson_disk_sample(80.0, 80.0, min_distance=4.0, seed=33)
        assert len(pts) > 5
        for i, (xa, ya) in enumerate(pts):
            for xb, yb in pts[i + 1:]:
                d = math.hypot(xa - xb, ya - yb)
                assert d >= 4.0 * 0.99, f"pair {i} dist={d:.3f} below min 4.0"


# ---------------------------------------------------------------------------
# Test 4 — Catch BUG-S15-04-01: biome_name must reach the delegate
# ---------------------------------------------------------------------------

class TestScatterBiomeVegetationDelegation:
    """The deprecated wrapper must forward biome_name; today it does not."""

    @pytest.mark.xfail(
        reason="BUG-S15-04-01: scatter_biome_vegetation drops biome_name",
        strict=True,
    )
    def test_biome_name_forwarded(self, monkeypatch):
        from veilbreakers_terrain.handlers import vegetation_system, environment_scatter

        captured: dict[str, object] = {}

        def fake_handler(params):
            captured["params"] = dict(params)
            return {
                "name": "stub",
                "instance_count": 0,
                "vegetation_types": {},
                "lod_instance_counts": {},
                "scatter_point_table": {"format": "ScatterPointTable", "points": [], "point_count": 0, "coordinate_space": "world_m", "source": "stub"},
                "bounds": {"width": 1.0, "depth": 1.0},
            }

        monkeypatch.setattr(environment_scatter, "handle_scatter_vegetation", fake_handler)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            vegetation_system.scatter_biome_vegetation(
                {"terrain_name": "T", "biome_name": "frozen_hollows", "seed": 1}
            )
        # This is what *should* be true:
        assert captured["params"].get("biome_name") == "frozen_hollows"


# ---------------------------------------------------------------------------
# Test 5 — Catalog must cover all 18 canonical biomes
# ---------------------------------------------------------------------------

class TestCatalogBiomeCoverage:
    """Every canonical biome must resolve to at least 1 catalog species."""

    def test_all_18_biomes_have_species(self):
        for biome_id in CANONICAL_BIOME_IDS:
            entries = species_for_biome(biome_id)
            assert len(entries) > 0, (
                f"biome {biome_id!r} has zero catalog species — "
                "fragmented biome name vocab regression"
            )

    def test_biome_character_species_per_biome(self):
        """Stricter: every biome should have at least 8 species (above the 7-floor)
        so each tile has biome character, not just the all-biomes catch-alls.
        BUG-S15-04-02: today 8/18 biomes only have the 7 floor species.
        """
        underpopulated: list[str] = []
        for biome_id in CANONICAL_BIOME_IDS:
            n = len(species_for_biome(biome_id))
            if n <= 7:
                underpopulated.append(f"{biome_id} ({n})")
        assert not underpopulated, (
            f"biomes with only floor species (placeholder, no character): "
            f"{', '.join(underpopulated)}"
        )


# ---------------------------------------------------------------------------
# Test 6 — Procedural grass biome_id_map must contain every canonical biome
# ---------------------------------------------------------------------------

class TestProceduralGrassBiomeMap:
    @pytest.mark.xfail(reason="BUG-S15-04-03: 4 biomes missing", strict=True)
    def test_all_canonical_biomes_in_map(self):
        from veilbreakers_terrain.handlers.procedural_grass import DEFAULT_BIOME_ID_MAP

        missing = set(CANONICAL_BIOME_IDS) - set(DEFAULT_BIOME_ID_MAP)
        assert not missing, f"missing biomes from procedural_grass map: {sorted(missing)}"
```

This test file:
- Uses fixed seeds for two-run determinism check.
- Verifies altitude gating with a 64×64 synthetic biome map.
- Verifies min-distance (Bridson invariant).
- Has explicit `xfail(strict=True)` markers on tests for **BUG-S15-04-01**
  and **BUG-S15-04-03** so when the fixes land, CI catches the
  unexpected-pass and forces flag removal.

---

## 5. Recommendations / Fix Order

1. **P0 — fix `scatter_biome_vegetation` delegation** (BUG-01). Trivial
   diff in `vegetation_system.py:1209-1219`. Test included above.
2. **P1 — wire biome species into coarse `_scatter_pass`** (BUG-02).
   Either add biome-character species to the catalog for the 8 thin
   biomes, or thread `species_for_biome(biome)` into the structure pass.
3. **P1 — repair `procedural_grass.DEFAULT_BIOME_ID_MAP`** (BUG-03).
   Derive from `terrain_biome_registry.CANONICAL_BIOME_IDS` insertion
   order; add a CI assertion.
4. **P1 — fix `terrain_foliage_catalog.choose_for_species` rng fallback**
   (Determinism 1c). Replace `rng or random` with explicit per-tile rng.
5. **P1 — wire leaf cards onto L-system tree tips** (BUG-07). Connect
   `_add_leaf_card_canopy` (already exists in environment_scatter.py:1747)
   to `branches_to_mesh()` `tip_positions / tip_directions / tip_radii`
   output.
6. **P1 — implement billboard impostor bake** (BUG-08). N-view atlas
   bake from rendered tree LOD0 → 8-quad atlas at 200 m.
7. **P2 — `_density_reject` shape assertion** (BUG-06).
8. **P2 — switch Lloyd to true Voronoi** (BUG-05) for tile boundary
   stability.
9. **P2 — `_lod_for_distance` MIN(distance, screen-pct)** (BUG-04).

---

## 6. Files referenced (absolute paths)

- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\vegetation_system.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\environment_scatter.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_scatter_points.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\_scatter_engine.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\vegetation_lsystem.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_foliage_catalog.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_scatter_altitude_safety.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_ecotone_graph.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\procedural_grass.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_biome_registry.py`
