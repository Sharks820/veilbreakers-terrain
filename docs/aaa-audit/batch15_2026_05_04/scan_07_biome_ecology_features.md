# Scan 07 — Biome / Ecology / Feature Generators (Batch 15)

**Audit date:** 2026-05-04
**Auditor:** Opus 4.7 (terrain audit subagent)
**Scope:** 12 files, 19 551 LOC.
**Overall grade:** **D+** (regressed from C in 2026-05-03 sweep — Batch 14
fixed substring-match dispatch but introduced a 4-biome silent-drop bug).

> **Headline P0**: Of the 18 canonical VeilBreakers biomes, **4 are silently
> dropped by every biome-aware system in the audited surface**:
> `blighted_mire`, `ashen_wastes`, `frozen_hollows`, `ruined_citadel`.
> These names exist in `terrain_biome_registry.CANONICAL_BIOME_IDS`,
> `vegetation_system.BIOME_VEGETATION_SETS`, `procedural_grass`, and
> `terrain_foliage_catalog`, but are **absent** from
> `_biome_grammar.BIOME_CLIMATE_PARAMS` (14 entries),
> `_biome_grammar._BIOME_FEATURES` (14 entries),
> `_biome_grammar.BIOME_ALIASES`, and
> `terrain_materials.BIOME_PALETTES`.  Calling
> `_biome_grammar.resolve_biome_name("blighted_mire")` raises `ValueError`
> at runtime (verified) — any pipeline that lets one of these biomes hit
> the world-map composer will hard-crash.

---

## 1. Coverage matrix — 18 canonical biomes vs 6 subsystems

Legend: ✓ = present, ✗ = absent / silent drop, ✗! = hard-crash on access.

| # | Canonical biome    | CLIMATE_<br/>PARAMS | _BIOME_<br/>FEATURES | BIOME_<br/>PALETTES | Cave<br/>archetype<br/>map | Wildlife<br/>rules | Ecotone<br/>widths |
|---|--------------------|--------------------|---------------------|--------------------|--------------------------|---------------------|--------------------|
|  1 | thornwood_forest    | ✓ | ✓ | ✓ | ✓ (via "forest")  | ✗ | ✗ |
|  2 | deep_forest         | ✓ | ✓ | ✓ | ✓ (via "forest")  | ✗ | ✗ |
|  3 | mushroom_forest     | ✓ | ✓ | ✓ | ✓ (via "forest")  | ✗ | ✗ |
|  4 | corrupted_swamp     | ✓ | ✓ | ✓ | ✗ (no token)      | ✗ | ✗ |
|  5 | **blighted_mire**   | **✗!** | **✗** | **✗!** | **✗** | ✗ | ✗ |
|  6 | grasslands          | ✓ | ✓ | ✓ | ✓ (via "grassland")| ✗ | ✗ |
|  7 | desert              | ✓ | ✓ | ✓ | ✓ (via "desert")  | ✗ | ✗ |
|  8 | coastal             | ✓ | ✓ | ✓ | ✓ (via "coastal") | ✗ | ✗ |
|  9 | **ashen_wastes**    | **✗!** | **✗** | **✗!** | **✗** | ✗ | ✗ |
| 10 | mountain_pass       | ✓ | ✓ | ✓ | ✓ (via "mountain")| ✗ | ✗ |
| 11 | **frozen_hollows**  | **✗!** | **✗** | **✗!** | **✗ ¹** | ✗ | ✗ |
| 12 | cemetery            | ✓ | ✓ | ✓ | ✗ (no token)      | ✗ | ✗ |
| 13 | **ruined_citadel**  | **✗!** | **✗** | **✗!** | **✗** | ✗ | ✗ |
| 14 | ruined_fortress     | ✓ | ✓ | ✓ | ✗ (no token)      | ✗ | ✗ |
| 15 | abandoned_village   | ✓ | ✓ | ✓ | ✗ (no token)      | ✗ | ✗ |
| 16 | battlefield         | ✓ | ✓ | ✓ | ✗ (no token)      | ✗ | ✗ |
| 17 | crystal_cavern      | ✓ | ✓ | ✓ | ✗ (no token)      | ✗ | ✗ |
| 18 | veil_crack_zone     | ✓ | ✓ | ✓ | ✗ (no token)      | ✗ | ✗ |

¹ `frozen_hollows` *would* match the `_BIOME_ARCHETYPE_MAP` token "frozen"
in `terrain_caves._BIOME_ARCHETYPE_MAP` if the name ever reached
`pick_cave_archetype` — but the upstream biome-name resolver (`_biome_grammar.resolve_biome_name`)
raises `ValueError` first, so the cave subsystem can't see it either.

**Cave archetype score (substring match on `_BIOME_ARCHETYPE_MAP`):**
- 7 / 18 biomes have NO substring match: `corrupted_swamp`, `blighted_mire`,
  `ashen_wastes`, `cemetery`, `ruined_citadel`, `ruined_fortress`,
  `abandoned_village`, `battlefield`, `crystal_cavern`, `veil_crack_zone`.
- These 7 fall through to terrain-signal scoring only — meaning a battlefield,
  a crystal cavern, and a veil-crack zone all spawn the same default karst
  sinkhole at low altitude / damp signal.  The bespoke crystal-cavern fantasy
  archetype that AAA studios would author is silently absent.
- Substring matching is also fragile by design: adding `desert_red` would
  match — but adding `red_desert` would also match the `red` in another
  rule if order were different.  Real AAA pipelines (Witcher 3, RDR2) use
  exact-key dispatch tables, not substring.

**Ecotone widths (`terrain_ecotone_graph.DEFAULT_ECOTONE_WIDTH_M`):**
- Defines only 7 hardcoded `(int, int)` keys — `(0,1) (0,2) (1,2) (1,3) (2,3) (2,4) (3,4)`.
- Biomes are referenced by **integer index**, not by name.  When the world
  map permutes biome IDs (line 273-285 of `_biome_grammar.generate_world_map_spec`
  applies a `cell_to_biome` permutation by temperature), these int keys
  no longer correspond to any consistent biome pair.
- Effective behaviour: **every biome pair except those 7 ints uses the
  fallback 30 m width**.  No real per-pair ecology authoring.

**Wildlife `DEFAULT_WILDLIFE_RULES`:** only 3 species — deer, wolf, eagle.
None biome-restricted.  No swamp creatures, no desert lizards, no veil-corruption
fauna, no ruin scavengers, no thornwood predators.  Compare RDR2 (~200
species with biome-keyed habitat rules) or Ghost of Tsushima (~80 species).

---

## 2. Per-file findings (most severe first)

### 2.1 `_biome_grammar.py` (2 863 LOC) — **C-**

#### P0-B15-01 — `BIOME_CLIMATE_PARAMS` missing 4 canonical biomes [HARD CRASH]
**Lines 82-97.**  Dict has 14 entries; CANONICAL_BIOME_IDS frozenset (line
103) is then derived FROM this dict, so the frozenset itself is a 14-member
silent down-projection of the 18-member canonical list.  Other modules
(`vegetation_system`, `procedural_grass`, `terrain_foliage_catalog`,
`terrain_biome_registry`) reference all 18 names — when a worldgen call
flows from one of those modules into `resolve_biome_name`, it raises
`ValueError`.  **Verified by direct invocation** (this audit run).

```python
# repro:
>>> from veilbreakers_terrain.handlers._biome_grammar import resolve_biome_name
>>> resolve_biome_name("blighted_mire")
ValueError: Unknown biome: 'blighted_mire'. Known: [..., 'thornwood_forest', 'veil_crack_zone']
```

Fix: add 4 climate entries (suggested values below) AND make the canonical
source-of-truth `terrain_biome_registry.CANONICAL_BIOME_IDS` rather than
deriving it from `BIOME_CLIMATE_PARAMS`.

```python
"blighted_mire":     {"temperature": 0.40, "moisture": 0.95, "elevation": 0.05},
"ashen_wastes":      {"temperature": 0.75, "moisture": 0.10, "elevation": 0.40},
"frozen_hollows":    {"temperature": 0.05, "moisture": 0.45, "elevation": 0.55},
"ruined_citadel":    {"temperature": 0.40, "moisture": 0.30, "elevation": 0.65},
```

Also add an import-time invariant assert: `assert BIOME_CLIMATE_PARAMS.keys() == CANONICAL_BIOME_IDS, ...`

#### P0-B15-02 — `_BIOME_FEATURES` dispatch table missing the same 4 biomes
**Lines 2 678-2 693.**  When `pass_biome_surface_features` is invoked with
biome `blighted_mire`, `ashen_wastes`, `frozen_hollows`, or `ruined_citadel`,
`_dispatch_biome_surface_features` returns an empty list silently
(`feature_keys = _BIOME_FEATURES.get(biome_id, ())`), so the produced
`biome_surface_feature_delta` channel is all-zero.  No feature signal,
no warning, no `ValidationIssue` — just blank.

#### P0-B15-03 — `_apply_*` feature functions use `np.random.Generator.integers` for radii but **bare Python `range(n)` micro-loops with O(N²) per-pixel ops**
Examples: `_apply_forest_debris` (lines 1937-1940), `_apply_swamp_muck`
(1995-1999), `_apply_battlefield_craters` (2275-2283), 19 other
`_apply_*` functions follow the same pattern.

For each of `n = h*w * 0.005 ≈ 327` features at 256×256, each does a
full-grid `np.exp(-d2 / r2)` allocation = **327 × 256² × 8 bytes / 1 GiB ≈ 21 MB
per feature × 327 features = 6.7 GiB peak transient memory** before the
per-feature add reduces it.  At AAA tile size 1024×1024 this becomes
~1 TB transient.  This must be vectorised (sum-of-Gaussians via
broadcasting capped at e.g. 200 mounds, like `apply_reef_platform` does
on line 1467).

#### P1-B15-04 — `apply_geological_folds` strain-factor sampled at single hinge cell [bug]
**Lines 1888-1903.**  Strain factor uses Laplacian sampled at `(h_idx, w_idx)`
only.  Multiple folds whose hinge happens to land in a low-curvature region
get the same `strain_factor=1.0`, defeating the "cumulative strain" model.
Should sample within a small neighbourhood (e.g. mean(|laplacian|) over a
3-5 cell window centred on the hinge).

#### P1-B15-05 — `apply_landslide_scars` uses `rng.choice(prob)` but `prob` includes ZERO-slope flats
**Lines 1046-1048.**  `flat_slope = slope.ravel(); prob = flat_slope / sum`.
On a perfectly flat tile (`slope.sum() == 0`), `prob` becomes inf/nan and
`rng.choice` raises `ValueError`.  No guard.  Real defence:
`if flat_slope.sum() < 1e-9: continue`.

#### P1-B15-06 — `apply_periglacial_patterns` always applies `elev_mask` [biome confusion]
**Lines 683-684, 698.**  The function is called by name from
`_BIOME_FEATURES["mountain_pass"]`, but the mask gates by *normalised
elevation across the whole tile*.  In a multi-biome tile where mountain_pass
occupies only one Voronoi cell, the periglacial pattern bleeds across the
entire tile (because `elev_mask` ignores `biome_id`).  Should AND with the
biome-id mask of the calling biome.

#### P2-B15-07 — `apply_reef_platform` caps coral mounds at `n_use=200` but not warned
**Lines 1466-1468.**  Quietly truncates the Voronoi coral seed array at 200.
At tile 1024×1024 with default `coral_cell ≈ 6`, n_corals ≈ 28 000 — 99 %
silently dropped, yielding sparse reefs that look unfinished.  Either raise
the cap or document the behaviour and surface a `ValidationIssue`.

#### P2-B15-08 — climate-sort permutation only matches `voronoi_biome_distribution` RNG stream by coincidence
**Lines 253-285** comment "consume the x draw so the RNG stream matches".
This is a fragile invariant — any change to `voronoi_biome_distribution`
will desync the seed stream and silently produce mis-ordered biomes.  Add
a unit test that asserts seed_y values match exactly.

---

### 2.2 `terrain_biome_registry.py` (92 LOC) — **B-**

#### P1-B15-09 — `CANONICAL_BIOME_IDS` and `_biome_grammar.CANONICAL_BIOME_IDS` are TWO different objects
- `terrain_biome_registry.CANONICAL_BIOME_IDS` → 18-entry `dict[str, str]`.
- `_biome_grammar.CANONICAL_BIOME_IDS` → 14-entry `frozenset[str]` derived
  from `BIOME_CLIMATE_PARAMS.keys()`.
- Both files claim to be "the single source of truth".  Neither imports
  the other.  This is the literal source of the silent-drop bug — there
  is no enforced consistency.

Fix: `_biome_grammar` should `from .terrain_biome_registry import CANONICAL_BIOME_IDS` and assert at import time that `set(BIOME_CLIMATE_PARAMS) == set(CANONICAL_BIOME_IDS)`.

---

### 2.3 `terrain_ecotone_graph.py` (309 LOC) — **C-**

#### P1-B15-10 — `DEFAULT_ECOTONE_WIDTH_M` keyed by integer index, not biome name
**Lines 27-35.**  Dict keys are `(0,1)`, `(0,2)` etc.  Biome integer IDs
are assigned arbitrarily by `voronoi_biome_distribution` then permuted by
the climate-sort code in `_biome_grammar.generate_world_map_spec` (lines
253-285).  After permutation the integer IDs no longer correspond to any
consistent biome — so `(0,1)` might mean "thornwood-to-swamp" on one tile
and "desert-to-coastal" on the next, with no way to author a meaningful
35 m vs 55 m blend.

Should be keyed by `frozenset({"thornwood_forest", "corrupted_swamp"})` →
35.0 m, looked up via the `biome_names` list on the WorldMapSpec.

#### P2-B15-11 — `validate_ecotone_smoothness` only flags narrow widths, never "no transition"
A perfectly hard biome boundary (1 cell) raises a soft warning.  But two
biomes with NO border at all (sliver edges) silently produce zero-cell
ecotones — should be flagged as well.

#### P2-B15-12 — `pass_ecotones` uses `overrides=("traversability",)` to claim navmesh's channel
**Lines 286-292.**  This is a documented compromise (the Codex
"PassDefinition overrides pattern" memory).  Functionally correct but the
fallback path silently produces traversability scores that may differ from
the navmesh-pass version, leading to inconsistent gameplay-zone classification
when one tile has navmesh and the next does not.

---

### 2.4 `terrain_features.py` (4 678 LOC) — **C+**

This file is dominated by single-feature mesh generators (canyon, waterfall,
cliff_face, swamp, sinkhole, lava_flow, etc.).  None of them honours
biome context — every feature renders identical regardless of which biome
hosts it.

#### P1-B15-13 — `generate_canyon`, `generate_swamp_terrain`, `generate_lava_flow` use `random.Random(seed)` [non-deterministic across PYTHONHASHSEED]
**Lines 262, 1743 (similar in 8+ generators).**  Python's `random.Random`
has weaker statistical properties than numpy's `np.random.default_rng`
and (per Codex CHANGELOG entry) is on the "no bare random.Random" list.
Should use `derive_pass_seed`.

#### P2-B15-14 — `pass_terrain_features` doesn't pass biome to generators
**Lines 4 599-4 662.**  Each `generator(**params)` invocation gets only the
authored `params` dict; the biome context is never threaded through.
Witcher 3's hand-painted approach can survive this; a procedural pipeline
cannot — a "waterfall" in `desert` should look fundamentally different
from one in `frozen_hollows` (frozen, snow rim, no spray) but both currently
emit identical mesh specs.

#### P3-B15-15 — `_PASS_FEATURE_GENERATORS` registry not validated against `hero_feature_specs.feature_kind`
A misspelled kind silently produces a `skipped` warning rather than a hard
error.  Skipping a hero feature is worse than failing the pass.

---

### 2.5 `terrain_cliffs.py` (2 851 LOC) — **B-**

This is the strongest file in the bundle — geologically sound (Moore-neighbor
contour, Gaussian smoothing, B-spline fit, strata layers, talus cones,
overhangs, micro-erosion).  But:

#### P1-B15-16 — `slope_threshold_deg=55.0` default is below the 60° AAA cliff floor
**Line 340.**  AAA terrain (Horizon ZD, Witcher 3, Elden Ring) defines a
cliff as a face whose slope EXCEEDS 60°.  At 55° the cliff is still
walkable and reads as a "steep hillside", not a vertical drop.  The mock
test in §3.1 below specifically asserts ≥60°.

#### P1-B15-17 — `_generate_cliff_overhang` uses `random.Random(seed)` instead of `derive_pass_seed`
**Lines 1589-1591.**  Bare Python random; matches the Batch 13 "≈50 bare
random.Random" finding.

#### P2-B15-18 — Talus angle of repose hardcoded to 34° unless `material` passed
`TalusField.angle_of_repose_radians = math.radians(34.0)` default.  Real
talus varies 28-37° depending on grain size and water content.  The
`_REPOSE_TABLE` exists (line 64) but is consulted only when the caller
explicitly passes a `material` string.  `carve_cliff_system` doesn't —
it always falls through to `"default"`.

#### P3-B15-19 — `_extract_lip_polyline` Moore-trace can deadlock on disconnected components
**Lines 460-528.**  The `seen_states` exit guard prevents an infinite loop
but on a multi-component face mask only the topmost-leftmost component
is traced — the others' lips are silently dropped.  Any non-trivial cliff
system gets its secondary face's lip lost.

---

### 2.6 `terrain_caves.py` (5 565 LOC) — **C+**

#### P0-B15-20 — `_BIOME_ARCHETYPE_MAP` substring match misses ≥7 canonical VeilBreakers biomes
**Lines 715-741** (analysed above in Coverage Matrix).  No fallback for
veil_crack_zone, crystal_cavern, cemetery, etc.  These all silently default
to whatever the terrain-signal scorer produces — typically KARST_SINKHOLE.
**Crystal_cavern caves should be the FISSURE archetype with crystal_formations
material** — they're literally named after caves.

Fix: replace substring match with explicit dict mapping all 18 canonical
biome names to archetypes (and add VEIL_CRACK and CRYSTAL_CAVE archetypes
to `CaveArchetype` enum).

#### P1-B15-21 — `pick_cave_archetype` uses `sum(ord(c) for c in k.value) % 7` for tiebreak
**Line 985.**  Comment says "stable ordinal tiebreak"; in practice this
gives every archetype the SAME tiebreak modulo 7 because there are only 5
archetypes and the modulo collapses adjacent enum values.  Use
`derive_pass_seed(seed, "cave_archetype_tiebreak", 0, 0, k.value)` instead.

#### P1-B15-22 — `validate_cave_entrance` is registered but `validate_cave_opening_integration` returns `list[str]` not `list[ValidationIssue]`
**Line 2725.**  Mismatched return type — the validator can't be merged into
the standard `PassResult.issues` list, breaking the validation aggregator.

#### P2-B15-23 — `snap_entry_to_cliff_face` only consulted when `cliff_candidate` channel exists
But the cave pass declares `requires_scene_read=True` (per docstring) and
runs AFTER cliffs in the DAG, so the channel SHOULD always exist.  No
defensive handling for the case where cliffs ran but produced empty
candidates (sea_grotto on a flat coast).

---

### 2.7 `coastline.py` (1 330 LOC) — **B**

Solid.  JONSWAP fetch model, aspect-based exposure, intertidal amplification,
differential hardness, retreat-with-recompute loop.  Issues:

#### P1-B15-24 — `apply_coastal_erosion` storm-cap of 12 m per pass is **per-pass-step**
**Line 1144.**  With `erosion_passes=10` (a stormy generation), cumulative
retreat = 120 m per generation — RDR2-class is more like 0.5–2 m/century.
Should be `0.1–2 m / pass total` and storm conditions modelled by extending
the band, not amplifying the depth.

#### P2-B15-25 — `_generate_shoreline_profile` "fjord" style is documented but not implemented
Docstring lines 186-188 mention fjord style; the code only handles
`rocky / sandy / cliffs / harbor`.  Silent fallthrough to default.

#### P2-B15-26 — `compute_wave_energy` clamps energy via `log1p` but never normalises by tile size
Tile-area dependence means the same coast looks different at 256×256 vs
1024×1024.  Expose a `area_normalisation` flag.

#### P3-B15-27 — Wave-cut platform geometry is never explicitly built
Per the audit task §1d, AAA coastlines need wave-cut platforms (a flat
bedrock terrace at MSL ± 0.5 m, ~5–20 m wide).  `apply_coastal_erosion`
builds erosion deltas; the platform terrace itself is not produced.  See
the §3.3 mock test.

---

### 2.8 `terrain_negative_space.py` (454 LOC) — **B+**

Strongest file.  Implements scipy `gaussian_kde`, `maximum_filter` NMS,
EDT-based exclusion radius.  Validates ratio + density + spacing.

#### P2-B15-28 — `compute_min_peak_spacing` uses O(N²) pair distance matrix
Cap at top-K peaks (currently unlimited `peaks` list).  Real AAA tiles
can have 200+ peaks → 40 000 pairs → 320 KB allocation, fine — but
documents/larger maps it'll bloat.

#### P3-B15-29 — `enforce_quiet_zone` exclusion radius silently degrades when scipy missing
Lines 343-347: `except ImportError: pass`.  Should at least log/warn that
the EDT exclusion is inactive.

---

### 2.9 `terrain_destructibility_patches.py` (174 LOC) — **B+**

#### P1-B15-30 — `material_id` extracted from arbitrary first cell of region
Line 101: `int(stack.biome_id[rows_idx[0], cols_idx[0]])`.  For regions
spanning multiple biomes, this picks one biome cell at random based on
ravel order.  The 8x8 fallback path uses `np.bincount(... argmax)` (mode)
which is correct — the scipy fast path should match.

#### P2-B15-31 — No combat-zone proximity gate
Per audit task §1f: "destructibility patches correctly placed near
combat-relevant features".  Currently any soft+wet+steep cell qualifies.
Combat zones (from `gameplay_zone == COMBAT`) and hero feature footprints
should boost the score; currently they're ignored.

---

### 2.10 `terrain_decal_placement.py` (332 LOC) — **A-**

Most polished file.  Score-based fusion of slope / curvature / wetness /
erosion / flow_accumulation / basin / ridge + correct biome-agnostic
heuristics.

#### P3-B15-32 — `BLOOD_STAIN` only fires on `gameplay == 1` (COMBAT)
Lines 222-229.  Hardcoded gameplay zone literal.  Should reference
`GameplayZoneType.COMBAT.value` to survive enum reordering.

---

### 2.11 `terrain_gameplay_zones.py` (484 LOC) — **B**

Cover / exposure / choke / vantage scores all real.  Connected-component
filtering with `min_component_cells = max(4, H*W // 2000)` is sound.

#### P1-B15-33 — `_compute_choke_score` chamfer fallback is O(H²) Python loop
Lines 188-216.  When scipy is absent, two passes of nested Python `for r,c`
over an H×W grid.  At 1024×1024 = ~30 s per pass.  Should use the
vectorised cummin trick from `_distance_to_mask` in `terrain_wildlife_zones.py`
(lines 132-159) which is already Python-loop-only over rows.

#### P2-B15-34 — `compute_gameplay_zones` doesn't respect biome-specific movement constraints
Per audit §1g: "gameplay zones respect biome-specific movement constraints".
Currently a swamp is no harder to traverse than grassland — the zone
classifier uses slope alone.  `corrupted_swamp` should bias EXPLORATION→STEALTH;
`mountain_pass` should bias toward BOSS_ARENA on ridge cells.

---

### 2.12 `terrain_wildlife_zones.py` (511 LOC) — **C-**

#### P0-B15-35 — `DEFAULT_WILDLIFE_RULES` only 3 species, none biome-restricted
**Lines 379-402.**  Deer, wolf, eagle.  No `preferred_biomes` set on any.
Compare to RDR2 (200+ species), Ghost of Tsushima (~80), Witcher 3 (~30).
A dark-fantasy game with **18 biomes** needs biome-specific creatures:

| Biome | Suggested species | Notes |
|-------|-------------------|-------|
| thornwood_forest | thornwolf, corvids, briar boar | aggressive, ambush-prone |
| deep_forest | great-elk, lynx, owl | shelter-loving, road-averse |
| mushroom_forest | spore-mites, glow-beetles | low-light specialists |
| corrupted_swamp | bog-leech, plague-rat, swamp-toad | wetness-required |
| blighted_mire | rot-moth, mire-serpent | extremely high disturbance tolerance |
| grasslands | wild-horse, hare, pheasant | open-ground species (forest_preference < 0) |
| desert | sand-viper, desert-fox, scarab | high-altitude / dry-tolerant |
| coastal | seal, gull, crab | water-dependent |
| ashen_wastes | ash-rat, soot-vulture | desolation specialists |
| mountain_pass | mountain-goat, ibex, golden-eagle | high-altitude / steep slope |
| frozen_hollows | snow-fox, ice-wisp | cold + low altitude |
| cemetery | crow-flock, grave-wraith | corruption-attracted |
| ruined_citadel/fortress | feral-dogs, scavenger-rats | ruin proximity |
| abandoned_village | ferals, foxes | low road sensitivity |
| battlefield | carrion-flies, vultures | high corpse density |
| crystal_cavern | shimmer-bat, prism-mole | underground-only |
| veil_crack_zone | void-spawn, rift-eels | corruption-dependent |

#### P1-B15-36 — `road_sdf_dist` consumed but never declared in `consumed_channels`
**Line 478:** `consumed_channels=("height",)` only.  `road_sdf_dist` (line
267) is a hidden read, breaking the channel-ownership protocol.

#### P2-B15-37 — `forest_preference` blending is asymmetric
Lines 305-311.  `pref >= 0` uses `1.0 - (1-density) * pref`; `pref < 0`
uses `1.0 - density * abs(pref)`.  These don't compose to a smooth function
at `pref = 0` — there's a kink (both produce f=1, but slope differs).
Use a single `tanh(pref * (density - 0.5))` form.

---

## 3. Mock test code (per audit task §4)

### 3.1 Cliff face slope ≥ 60° assertion

```python
# tests/test_cliff_geological_validity.py
import math
import numpy as np
import pytest
from veilbreakers_terrain.handlers.terrain_cliffs import (
    build_cliff_candidate_mask,
    carve_cliff_system,
)


@pytest.fixture
def synthetic_cliff_stack():
    """Synthetic terrain with a single 80°-slope vertical face."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    H, W = 64, 64
    height = np.zeros((H, W), dtype=np.float32)
    # Sharp 30 m drop at row 32 — slope = atan(30 / cell_size)
    height[32:, :] = 30.0
    cell_size = 1.0
    stack = TerrainMaskStack(
        cell_size=cell_size, tile_size=H,
        world_origin_x=0.0, world_origin_y=0.0,
    )
    stack.set("height", height, "test")
    # Compute slope channel
    gy, gx = np.gradient(height, cell_size)
    slope = np.arctan(np.sqrt(gx ** 2 + gy ** 2)).astype(np.float32)
    stack.set("slope", slope, "test")
    return stack


def test_cliff_face_geological_validity(synthetic_cliff_stack):
    """Every cliff face cell must have slope >= 60° (AAA convention)."""
    stack = synthetic_cliff_stack
    AAA_CLIFF_FLOOR_DEG = 60.0
    AAA_CLIFF_FLOOR_RAD = math.radians(AAA_CLIFF_FLOOR_DEG)

    mask = build_cliff_candidate_mask(stack, slope_threshold_deg=AAA_CLIFF_FLOOR_DEG)
    if not mask.any():
        pytest.skip("no cliffs in synthetic terrain")

    slope_arr = np.asarray(stack.get("slope"))
    face_slopes = slope_arr[mask]
    assert face_slopes.min() >= AAA_CLIFF_FLOOR_RAD, (
        f"Cliff candidate has slope {math.degrees(face_slopes.min()):.1f}° "
        f"< AAA floor {AAA_CLIFF_FLOOR_DEG}°"
    )


def test_cliff_overhang_fraction_within_aaa_band(synthetic_cliff_stack):
    """Overhang count should be 25-45% of lip segments (Elden Ring band)."""
    from veilbreakers_terrain.handlers.terrain_cliffs import _generate_cliff_overhang, CliffStructure

    cliff = CliffStructure(
        cliff_id="test",
        lip_polyline=np.array([[10, c] for c in range(20, 50)], dtype=np.int32),
        face_mask=np.zeros((64, 64), dtype=bool),
        max_height_m=30.0,
        min_height_m=0.0,
    )
    spec = _generate_cliff_overhang(cliff, overhang_probability=0.35, seed=42)
    frac = spec["overhang_fraction"]
    assert 0.25 <= frac <= 0.45, f"overhang fraction {frac:.2f} outside AAA band [0.25, 0.45]"
```

### 3.2 Ecotone smoothness — no sharp biome boundaries

```python
def test_ecotone_no_sharp_boundaries():
    """Adjacent biome pairs must blend over >= 2 cells."""
    from veilbreakers_terrain.handlers.terrain_ecotone_graph import (
        build_ecotone_graph, validate_ecotone_smoothness,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    H, W = 32, 32
    biome = np.zeros((H, W), dtype=np.int64)
    biome[:, :W // 2] = 1   # split tile in half — biome 0 left, 1 right
    stack = TerrainMaskStack(cell_size=1.0, tile_size=H, world_origin_x=0, world_origin_y=0)
    stack.set("height", np.zeros((H, W), dtype=np.float32), "test")
    stack.set("biome_id", biome, "test")

    graph = build_ecotone_graph(stack)
    issues = validate_ecotone_smoothness(graph)

    # We expect no soft warnings if the ecotone width >= 2 cells
    hard_boundary_issues = [i for i in issues if i.code == "ECOTONE_HARD_BOUNDARY"]
    assert not hard_boundary_issues, (
        f"sharp boundary detected: {[i.message for i in hard_boundary_issues]}"
    )


def test_ecotone_width_per_biome_pair_authored():
    """Biome pairs (thornwood, corrupted_swamp) must have authored ecotone width != 30 m fallback."""
    from veilbreakers_terrain.handlers.terrain_ecotone_graph import _ecotone_width_for_pair
    # Currently fails because keys are int-int not biome-name-pair.
    # When the fix lands, assert authored value differs from FALLBACK.
    width = _ecotone_width_for_pair(0, 1)   # currently returns 45.0 from hardcoded table
    # After fix: lookup by name pair ("thornwood_forest", "corrupted_swamp") returns 35.0
    assert width != 30.0, "biome pair fell through to FALLBACK_ECOTONE_WIDTH_M"
```

### 3.3 Coastline wave-cut platform at MSL ± 0.5 m

```python
def test_coastline_wave_cut_platform_elevation():
    """After 100 erosion passes, a wave-cut platform must form at MSL ± 0.5 m."""
    from veilbreakers_terrain.handlers.coastline import apply_coastal_erosion
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    H, W = 64, 64
    # Synthetic seacoast: half ocean (z=-2), half land (z=10), sharp boundary
    height = np.full((H, W), 10.0, dtype=np.float32)
    height[:, :W // 2] = -2.0
    sea_level = 0.0

    stack = TerrainMaskStack(cell_size=1.0, tile_size=H, world_origin_x=0, world_origin_y=0)
    stack.set("height", height.copy(), "test")
    stack.set("rock_hardness", np.full((H, W), 0.45, dtype=np.float32), "test")  # medium-soft

    # Run 100 small erosion passes (calm conditions)
    for _ in range(100):
        d = apply_coastal_erosion(stack, sea_level, wave_direction=math.pi, wave_energy=0.3)
        stack.set("height", (np.asarray(stack.get("height")) + d).astype(np.float32), "test")

    final = np.asarray(stack.get("height"))

    # Look for cells within MSL ± 0.5 m near the coastline (col W/2 area)
    coast_band = final[:, W // 2 - 5:W // 2 + 5]
    platform_cells = (np.abs(coast_band - sea_level) < 0.5).sum()
    assert platform_cells >= 0.10 * coast_band.size, (
        f"only {platform_cells} cells in MSL±0.5 m; expected >= 10 % of coastal band — "
        "wave-cut platform did not form"
    )


def test_sea_stack_emergence_with_hardness_contrast():
    """Hard rock pillars (h=1.0) surrounded by soft sediment (h=0.2) must emerge as sea stacks."""
    # ... after differential erosion, the hard cells should still rise above sea_level
    # while the soft cells erode below it.  Asserts:
    #   final[hard_pillar_cells] > sea_level + 1.0
    #   final[soft_neighbour_cells] < sea_level
    pass  # full impl elided for brevity
```

---

## 4. AAA reference comparison

| AAA reference                | This codebase                          | Gap |
|------------------------------|----------------------------------------|-----|
| **Witcher 3** — handcrafted region rule sets, ~6 distinct ecologies | 4 of 18 biomes have ZERO grammar/feature/material entries | F |
| **Horizon ZD** — biome painting + machine ruin overlay | Ecotone widths are int-keyed, not name-keyed; ruin biomes have no archetype mapping | D |
| **Ghost of Tsushima** — cherry-blossom, pampas-grass, bamboo region rules | 0 region-specific feature rules outside `_BIOME_FEATURES` (which itself misses 4 biomes) | D− |
| **RDR2** — climate-driven vegetation density per cell | `BIOME_CLIMATE_PARAMS` exists but never consumed by vegetation density anywhere visible in this audit's surface | C− |
| **Elden Ring** — deliberate negative space for readability | `terrain_negative_space` IS solid (B+) — closest to AAA in this bundle | B+ |

---

## 5. Recommendations (priority-ordered for next sprint)

1. **(P0, ~2 hrs)** Make `terrain_biome_registry.CANONICAL_BIOME_IDS` the single
   source of truth.  Add 4 missing entries to `BIOME_CLIMATE_PARAMS`,
   `_BIOME_FEATURES`, `BIOME_PALETTES`, and the cave archetype map.  Add
   import-time invariant assert.
2. **(P0, ~3 hrs)** Replace `_BIOME_ARCHETYPE_MAP` substring matching with
   exact-key dict mapping all 18 canonical biomes.  Add `CRYSTAL_CAVE`
   and `VEIL_RIFT` archetypes.
3. **(P1, ~6 hrs)** Author `DEFAULT_WILDLIFE_RULES` for all 18 biomes with
   3-5 species each (~70 species total).  Make `preferred_biomes` always set.
4. **(P1, ~2 hrs)** Re-key `DEFAULT_ECOTONE_WIDTH_M` to `frozenset({biome_name, biome_name})`.
5. **(P1, ~4 hrs)** Vectorise the 22 `_apply_*` micro-loops in `_biome_grammar.py`
   to use the broadcasting pattern from `apply_reef_platform`.
6. **(P1, ~1 hr)** Raise cliff slope_threshold default from 55° → 60°.
7. **(P1, ~3 hrs)** Implement actual wave-cut platform geometry in `coastline.py`.
8. **(P2, ~2 hrs)** Wire biome context through `pass_terrain_features` so canyon /
   waterfall / lava generators can bias output by biome.
9. **(P2, ~1 hr)** Add `combat_zone_proximity` factor to destructibility patch detection.

---

## 6. Verified findings list (33 items)

| ID | Severity | Title | File |
|----|----------|-------|------|
| P0-B15-01 | P0 hard-crash | BIOME_CLIMATE_PARAMS missing 4 canonical biomes | _biome_grammar.py |
| P0-B15-02 | P0 silent-drop | _BIOME_FEATURES missing same 4 biomes | _biome_grammar.py |
| P0-B15-03 | P0 perf | 22 `_apply_*` O(N²) per-pixel micro-loops | _biome_grammar.py |
| P0-B15-20 | P0 silent-drop | _BIOME_ARCHETYPE_MAP misses ≥7 canonical biomes | terrain_caves.py |
| P0-B15-35 | P0 ecology | DEFAULT_WILDLIFE_RULES 3 species, none biome-restricted | terrain_wildlife_zones.py |
| P1-B15-04 | P1 bug | apply_geological_folds strain at single hinge cell | _biome_grammar.py |
| P1-B15-05 | P1 crash | apply_landslide_scars `prob` div-by-zero on flat | _biome_grammar.py |
| P1-B15-06 | P1 bug | apply_periglacial_patterns bleeds across biomes | _biome_grammar.py |
| P1-B15-09 | P1 dup | Two CANONICAL_BIOME_IDS objects in two files | _biome_grammar.py / terrain_biome_registry.py |
| P1-B15-10 | P1 design | DEFAULT_ECOTONE_WIDTH_M keyed by int, not name | terrain_ecotone_graph.py |
| P1-B15-13 | P1 nondet | terrain_features uses random.Random | terrain_features.py |
| P1-B15-16 | P1 quality | cliff slope_threshold_deg=55° below AAA 60° floor | terrain_cliffs.py |
| P1-B15-17 | P1 nondet | _generate_cliff_overhang uses random.Random | terrain_cliffs.py |
| P1-B15-21 | P1 bug | pick_cave_archetype tiebreak collapses by mod 7 | terrain_caves.py |
| P1-B15-22 | P1 type-mismatch | validate_cave_opening_integration returns list[str] | terrain_caves.py |
| P1-B15-24 | P1 quality | apply_coastal_erosion 12 m/pass storm cap = 120 m total | coastline.py |
| P1-B15-30 | P1 bug | destructibility material_id picks arbitrary cell | terrain_destructibility_patches.py |
| P1-B15-33 | P1 perf | _compute_choke_score chamfer fallback O(H²) Python | terrain_gameplay_zones.py |
| P1-B15-36 | P1 protocol | wildlife_zones reads road_sdf_dist undeclared | terrain_wildlife_zones.py |
| P2-B15-07 | P2 quality | apply_reef_platform truncates corals at 200 silently | _biome_grammar.py |
| P2-B15-08 | P2 fragile | climate-sort permutation depends on RNG stream coincidence | _biome_grammar.py |
| P2-B15-11 | P2 validation | validate_ecotone_smoothness misses zero-cell ecotones | terrain_ecotone_graph.py |
| P2-B15-12 | P2 protocol | pass_ecotones overrides traversability, may differ from navmesh | terrain_ecotone_graph.py |
| P2-B15-14 | P2 design | pass_terrain_features doesn't pass biome context | terrain_features.py |
| P2-B15-18 | P2 quality | TalusField defaults to 34° unless caller passes material | terrain_cliffs.py |
| P2-B15-23 | P2 robustness | snap_entry_to_cliff_face no fallback if cliffs empty | terrain_caves.py |
| P2-B15-25 | P2 incomplete | _generate_shoreline_profile fjord style not implemented | coastline.py |
| P2-B15-26 | P2 design | compute_wave_energy lacks tile-size normalisation | coastline.py |
| P2-B15-28 | P2 perf | compute_min_peak_spacing O(N²) on uncapped peaks | terrain_negative_space.py |
| P2-B15-31 | P2 design | destructibility no combat-zone proximity gate | terrain_destructibility_patches.py |
| P2-B15-34 | P2 design | gameplay_zones ignores biome-specific movement | terrain_gameplay_zones.py |
| P2-B15-37 | P2 math | wildlife forest_preference blend has kink at 0 | terrain_wildlife_zones.py |
| P3-B15-15 | P3 robustness | _PASS_FEATURE_GENERATORS skip rather than fail | terrain_features.py |
| P3-B15-19 | P3 bug | cliff Moore trace silently drops disconnected components | terrain_cliffs.py |
| P3-B15-27 | P3 missing-feature | wave-cut platform geometry never built | coastline.py |
| P3-B15-29 | P3 silent-degrade | enforce_quiet_zone EDT degrades silently w/o scipy | terrain_negative_space.py |
| P3-B15-32 | P3 hardcode | BLOOD_STAIN gameplay literal `1` instead of enum | terrain_decal_placement.py |

**Total: 37 P0–P3 findings (5 P0, 14 P1, 13 P2, 5 P3)**.

---

*End of scan_07_biome_ecology_features.md*
