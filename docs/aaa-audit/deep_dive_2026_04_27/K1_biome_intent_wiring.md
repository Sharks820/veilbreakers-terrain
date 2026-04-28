# K1 — Biome Intent Wiring (Deep Dive)

**Audit date:** 2026-04-27
**Scope:** Does `TerrainIntent.biome_*` actually drive different pass behavior in
production, or is it spec theater (the I3-P0-1 pattern applied to biomes)?
**Reference bar:** I3-P0-1 — switching `TerrainQualityProfile` produces
bit-identical terrain because 33/41 fields are dead.

## TL;DR

**Yes — the same pattern applies, with a twist.** Biome selection in production
mostly affects **vertex colors and scatter rule lookup tables**, not the
terrain-shape passes. The `TerrainIntentState.biome_rules` field is **completely
dead in the AAA pipeline** (set only by checkpoint deserialization, never read
by any production pass), and the `noise_profile` it shadows is a 5-bucket
mapping that collapses 10+ named biomes into the same heightmap output.

**Net effect for the AAA build script (`build_terrain_aaa_node_v6.py`):**
calling that pipeline with biome="volcanic_wastes" vs "frozen_tundra" vs
"thornwood_forest" produces **bit-identical heightmaps, bit-identical
materials, bit-identical erosion deltas, and bit-identical cliff placements** —
because the script never sets `noise_profile`, `erosion_profile`, or
`biome_rules` on the `TerrainIntentState` it constructs (defaults are used).

---

## 1. Structure: `TerrainSceneRead` and `TerrainIntentState`

Both dataclasses live in `terrain_semantics.py`. Note: there is no
`terrain_intent.py` — the intent dataclass is named `TerrainIntentState`.

### `TerrainSceneRead` (lines 1242–1271)
**Zero biome-related fields.** Captures focal point, hero features, cave
candidates, protected zones, success criteria. No `biome`, no `biome_id`, no
ecological hints.

### `TerrainIntentState` (lines 1279–1339)
Three fields that *could* be biome-driving:

| Field | Type | Default | Read by? |
|-------|------|---------|----------|
| `biome_rules` | `Optional[str]` | `None` | **Only `terrain_vegetation_depth.py:1554`** (and serialization in `terrain_checkpoints.py:293`/`432`) |
| `noise_profile` | `str` | `"dark_fantasy_default"` | `_terrain_world.py:510, 861`, `terrain_banded.py:978` |
| `erosion_profile` | `str` | `"temperate"` | `_terrain_world.py:1090` |

There is **no top-level `biome` field**. The codebase has 10 named biomes in
`VB_BIOME_PRESETS` (`environment.py:436`), 14 climate-param entries in
`BIOME_CLIMATE_PARAMS` (`_biome_grammar.py:74`), and ~10 entries in
`BIOME_PALETTES_V2` — but the intent dataclass exposes none of this directly.

---

## 2. Production callers and what they actually pass

### 2.1 `handle_generate_terrain` (`environment.py:1903–2240`) — controller path
At line 2969–2981, `TerrainIntentState` is constructed with:
```python
noise_profile=str(params.get("noise_profile", params.get("terrain_type", "mountains"))),
erosion_profile=str(params.get("erosion_profile", "temperate")),
```
- `biome_rules` is **never set** (defaults to `None`).
- `noise_profile` falls back to `terrain_type`. But by line 1929-1952, when a
  caller passes a *biome name* like `"thornwood_forest"`, it is REPLACED with
  the preset's base type (`"hills"` for thornwood, `"mountains"` for
  mountain_pass, `"flat"` for cemetery, etc.) before reaching the intent.
  So `noise_profile` becomes one of ~5 strings: `hills`/`mountains`/`flat`/
  `plains`/`chaotic`.

### 2.2 `handle_generate_multi_biome_world` (`environment.py:8285–8428`)
This is the closest thing to "the AAA biome path" that the J2 audit doc calls
`handle_generate_terrain_aaa`. It:

1. Builds a `WorldMapSpec` via `_biome_grammar.generate_world_map_spec` —
   produces `biome_ids`, `biome_weights`, `corruption_map`, `cell_params`
   (all numpy arrays / lists of dicts).
2. Picks the **dominant biome** (line 8342) and looks up its preset
   `terrain_type` — that becomes the *only* biome-driven input to terrain
   shape: `base_terrain_type = biome_preset["terrain_type"] if biome_preset
   else "hills"`.
3. Calls `handle_generate_terrain` with that one terrain_type. The other 5
   biomes in the spec **never reach** the heightmap generator.
4. Writes per-vertex `BiomeColor` (lines 8366–8378) and applies a single
   primary-biome material (lines 8380–8393).
5. Loops over `spec.biome_names` for vegetation scatter (lines 8398–8413).

**So biome selection in the multi-biome world handler affects:** vertex colors,
material assignment, and scatter rule lookup. It does **not** affect: noise
profile (single dominant terrain_type only), erosion profile (always
"temperate" via default), `biome_rules` (never set), `cell_params` (built but
never consumed — see §4), or per-region heightmap shape (one terrain_type for
the whole world).

### 2.3 `build_terrain_aaa_node_v6.py` (the actual AAA generator script)
Lines 195-200:
```python
intent = TerrainIntentState(
    SEED,
    bbox,
    int(TILE_SIZE_M),
    CELL_SIZE_M,
)
```
**No biome argument at all.** All four biome-shaping fields take their
defaults: `biome_rules=None`, `noise_profile="dark_fantasy_default"`,
`erosion_profile="temperate"`, `composition_hints={}`. The AAA pipeline
literally cannot vary by biome from this entry point.

The script's own heightmap is generated **before** `TerrainIntentState` exists
(stage 1, not shown, runs noise generation independently). The intent is built
only to satisfy the contract for stage-2 passes (`pass_cliffs`, `pass_waterfalls`,
`pass_materials`) — none of which read any of the three biome fields.

---

## 3. Pass-by-pass: who reads which biome field?

| Pass / function | File:line | Field read | Effect |
|-----------------|-----------|------------|--------|
| `_terrain_type_from_intent` | `_terrain_world.py:510` | `noise_profile` | 20-key string→string map; collapses biome to one of 9 base shapes |
| `pass_macro_world` (inline) | `_terrain_world.py:861-869` | `noise_profile` | **5-key map only** — `dark_fantasy_default`/`temperate`/`arid`/`arctic`/`coastal`. Note: `arctic` and `temperate` both map to `mountains` (line 866). Bug: `arid` is the only one that produces visibly different output. |
| `pass_erosion` | `_terrain_world.py:1090-1100` | `erosion_profile` | 3-key map: `temperate`/`arid`/`alpine`. Default is `temperate`. Note: `arctic` is **not** in the map and falls through to default. |
| `pass_erosion` (analytical config) | `_terrain_world.py:1137-1142` | `erosion_profile` | Same 3-key map; unknown profiles get `ErosionConfig()` defaults |
| `banded_macro` (Bundle G) | `terrain_banded.py:978` | `noise_profile` | Passed through to `generate_banded_heightmap`. **Not registered in production controller pipeline** (`handle_generate_terrain` builds pipeline = `["macro_world", "structural_masks", "pass_hydrology", "erosion", "structural_masks", "caves", "integrate_deltas", "cliffs", "emit_overhang_meshes", "validation_minimal"]` at line 2004-2034 — `banded_macro` is absent). |
| `pass_vegetation_depth` | `terrain_vegetation_depth.py:1554` | `biome_rules` | `compute_vegetation_layers` recognizes 6 biome strings: `dark_fantasy_default/tundra/swamp/desert/temperate_forest/boreal`. **None of these match any of the 10 `VB_BIOME_PRESETS` keys.** Plus: `vegetation_depth` is **not in the production pipeline** either. |
| `pass_materials` | `terrain_materials_v2.py:795-894` | (none) | Uses `default_dark_fantasy_rules()`. Biome-agnostic. |
| `pass_cliffs` | `terrain_cliffs.py` | (none of the three) | Pure slope/curvature analysis |
| `pass_waterfalls` | `terrain_waterfalls.py` | (none) | Pure flow analysis |
| `_serialize_intent` | `terrain_checkpoints.py:293-295` | all three | Pure serialization for checkpoint round-trip |

**Net:** of the three biome-shaping fields, only `noise_profile` and
`erosion_profile` are read by passes that actually run in the production
pipeline (`pass_macro_world` and `pass_erosion`), and they collapse to 5- and
3-bucket lookups respectively. `biome_rules` is dead in the production
pipeline.

---

## 4. `cell_params` — built but never consumed

`_biome_grammar.WorldMapSpec.cell_params` (line 112) is documented as
"per-biome climate params (temperature, moisture, elevation)". Constructed at
`_biome_grammar.py:215-279` from `BIOME_CLIMATE_PARAMS` for every biome in
the world map.

**Consumers:** zero in `veilbreakers_terrain/handlers/`. Only test files
reference `spec.cell_params` (`test_biome_grammar.py:285-313`).

This is the same pattern as I3-P0-1: extensive structured data is computed and
attached to a spec, then never read by the pipeline.

---

## 5. `arctic` is silently a no-op

Line 866 of `_terrain_world.py`:
```python
terrain_type_map = {
    "dark_fantasy_default": "mountains",
    "temperate": "mountains",
    "arid": "desert",
    "arctic": "mountains",   # <-- same as temperate
    "coastal": "coastal",
}
```
- `arctic` and `temperate` produce identical noise output.
- `arctic` is also missing from the erosion profile map (`temperate`, `arid`,
  `alpine` only — line 1097-1100). Setting `erosion_profile="arctic"` falls
  through to the `temperate` default (50,000 iterations, 40° talus angle).
  No warning is emitted.

So the "frozen_tundra" alias path that maps to `arctic` produces the same
heightmap and same erosion as `temperate`. The only differentiator left is the
material palette downstream — i.e. paint, not shape.

---

## 6. Type confusion: `biome_rules` is `Optional[str]` but `paint_terrain` expects `list[dict]`

`TerrainIntentState.biome_rules: Optional[str]` (line 1293) is a string per
the type annotation. But:

- `terrain_vegetation_depth.py:1554` reads it as a string biome name
  (`"dark_fantasy_default"`/etc.), confirming the type.
- `handle_paint_terrain` (`environment.py:3701`) reads `params["biome_rules"]`
  as a `list[dict]` of altitude/slope rules, NOT from the intent.
- `_terrain_noise.compute_biome_assignments` accepts `biome_rules: list[dict]`.

So the same field name `biome_rules` is used for two different types in two
different layers, **and the intent field doesn't connect to either of the
list-of-dict consumers.** The intent field is connected only to
`compute_vegetation_layers(biome="...")`.

---

## Findings

### K1-P0-1 — `TerrainIntentState.biome_rules` is dead in the AAA production pipeline (DUPLICATE of I3-P0-1 pattern, distinct root cause)

**Severity:** P0
**Status:** Distinct from I3-P0-1 — different field, different consumer pattern.
Not an extension of the orphan-pass P0 (I5-P0-4) either; this is about a
field on the intent dataclass that no production pass reads.

**Evidence:**
- `terrain_semantics.py:1293` — defaults to `None`.
- `environment.py:2969-2981` (`_execute_terrain_pipeline`) — never sets
  `biome_rules` on the `TerrainIntentState` it constructs.
- `build_terrain_aaa_node_v6.py:195-200` — passes only positional args
  (seed, bbox, tile_size, cell_size); `biome_rules=None`.
- The only reader, `terrain_vegetation_depth.py:1554`, falls back to
  `"dark_fantasy_default"` whenever `intent.biome_rules` is None — which is
  always in production.
- Additionally, `pass_vegetation_depth` is not in the production controller
  pipeline list at `environment.py:2004-2034`. Even when registered (Bundle O,
  `terrain_bundle_o.py:35`), it never runs from `handle_generate_terrain`.

**Why it is distinct from I3-P0-1:** I3 is about `TerrainQualityProfile` —
production/balanced/preview presets that swap quality knobs. This is about
the *biome* identity of an authored region, a separate API surface that no
production pipeline plumbs.

**Why it is distinct from I5-P0-4:** I5 enumerates orphan *passes* (pass
functions that are registered but never appear in any production pipeline).
This is a dead *field* — the field would be inert even if every pass ran.

**Fix root cause:** either (a) wire `intent.biome_rules` from
`handle_generate_multi_biome_world`'s `WorldMapSpec.biome_names[dominant]`
through `_execute_terrain_pipeline`, or (b) delete `biome_rules` from
`TerrainIntentState` and remove the unreachable read in
`terrain_vegetation_depth.py:1554`.

---

### K1-P0-2 — Multi-biome world generation collapses to a single dominant biome's terrain_type for shape

**Severity:** P0
**Status:** Distinct root cause.

**Evidence:**
- `environment.py:8342` — `dominant_biome = biomes[0] if biomes else (...)`
- `environment.py:8347` — `base_terrain_type = biome_preset["terrain_type"]
  if biome_preset else "hills"`
- `environment.py:8350-8359` — passes a single `terrain_type` to
  `handle_generate_terrain` for the entire world.

A 6-biome world (default) where biomes[0] = `thornwood_forest` produces
*one* "hills" heightmap, regardless of whether the other five regions are
`mountain_pass`, `corrupted_swamp`, or `veil_crack_zone`. The biome_ids array
is then painted on top via vertex color (line 8366-8378), giving the *visual
illusion* of biome-driven terrain while the shape is monolithic.

A real AAA biome system (Far Cry 6, Horizon Forbidden West) generates
per-region noise weights and blends them across `transition_width_m`. We
build the transition mask but never use it for height; only for color.

**Fix:** in `handle_generate_multi_biome_world`, generate per-biome heightmaps
and blend them using `spec.biome_weights`. Or expose a single AAA pipeline
with per-cell `intent.noise_profile` instead of one global profile.

---

### K1-P1-1 — `noise_profile` map collapses 20+ logical biomes to 5 noise paths in production (`pass_macro_world`)

**Severity:** P1

**Evidence:** `_terrain_world.py:861-869`. The full 20-key map at line 512-534
exists but is only used by `_terrain_type_from_intent`, which itself feeds
into `pass_generate_low_freq_hmap` (line 584), not `pass_macro_world`. The
production controller pipeline calls `macro_world` first, which uses the
5-key map — so `noise_profile="hills"` (set by `handle_generate_terrain` for
8 of the 10 VB biomes) is not in the 5-key map and falls through to
`"mountains"`. **All 10 VB biomes whose `terrain_type` is `hills/plains/flat/
chaotic` collapse to the `dark_fantasy_default → mountains` path.**

Only `desert` (and `volcanic` via no biome wiring) gives a different macro
shape.

**Fix:** unify the two terrain_type maps; use the full 20-key version in
`pass_macro_world`.

---

### K1-P1-2 — `arctic` erosion profile silently falls through to `temperate`

**Severity:** P1

**Evidence:** `_terrain_world.py:1097-1100`. Erosion profile dict has only
`temperate`, `arid`, `alpine`. The `frozen_tundra → mountain_pass` alias
chain in `BIOME_ALIASES` (`_biome_grammar.py:38-43`) and the `arctic` key in
the noise-profile map (line 866) imply an arctic biome should differ — but
no `arctic` erosion config exists. Result: glacial terrain erodes
identically to temperate forest.

**Fix:** add `arctic`/`alpine_glacial` profile entries to the dict, OR collapse
the arctic key out of `terrain_type_map` to be honest about coverage.

---

### K1-P1-3 — `WorldMapSpec.cell_params` is built per-biome but never consumed by any handler

**Severity:** P1

**Evidence:**
- `_biome_grammar.py:215-279` — built from `BIOME_CLIMATE_PARAMS` for every
  biome in the world.
- Zero non-test consumers in `veilbreakers_terrain/handlers/`.
- Tests at `test_biome_grammar.py:285-313` validate its structure.

This is data infrastructure with no readers. Same ghost-spec pattern as
I3-P0-1, smaller scope.

**Fix:** delete `cell_params` from `WorldMapSpec`, OR wire it into a
biome-driven moisture/temperature mask used by erosion/vegetation.

---

### K1-P2-1 — `biome_rules` field is `Optional[str]` but used inconsistently with the same name elsewhere as `list[dict]`

**Severity:** P2

**Evidence:** see §6. The string-typed intent field has no relationship to
the `list[dict]` `biome_rules` consumed by `handle_paint_terrain` and
`compute_biome_assignments`. Naming overlap creates confusion and obscures
that the two systems are not connected.

**Fix:** rename the intent field to `biome_id` (single-biome name semantic)
or `vegetation_biome` to disambiguate from the rule-list usage.

---

### K1-P2-2 — `BIOME_CLIMATE_PARAMS` is missing 5 of the 10 `VB_BIOME_PRESETS`

**Severity:** P2

**Evidence:** `_biome_grammar.py:74-89` covers 14 entries but is missing
`thornwood_forest` overlap is fine, but `cemetery`, `battlefield`,
`ruined_fortress`, `abandoned_village`, `veil_crack_zone` show up in BOTH
preset lists, while presets like `mushroom_forest` and `crystal_cavern` are
in CLIMATE but not VB_PRESETS. Source of subtle "biome configured but
incomplete" bugs.

**Fix:** establish a single canonical biome registry that all subsystems
consume.

---

### K1-P3-1 — `compute_vegetation_layers` accepts 6 biome names, none of which match `VB_BIOME_PRESETS` keys

**Severity:** P3 (orphan even if K1-P0-1 is fixed)

**Evidence:** `terrain_vegetation_depth.py:294-301` — `dark_fantasy_default/
tundra/swamp/desert/temperate_forest/boreal`. The `VB_BIOME_PRESETS` keys at
`environment.py:436-614` are `thornwood_forest/corrupted_swamp/mountain_pass/
ruined_fortress/abandoned_village/veil_crack_zone/underground_dungeon/
sacred_shrine/battlefield/cemetery`. Even if `intent.biome_rules` were
piped through, only `swamp` would match (via the `BIOME_ALIASES`
`swamp → corrupted_swamp` mapping, but the alias resolves the wrong
direction).

**Fix:** add `VB_BIOME_PRESETS` keys to the `biome_scale` dict, or remove
the dict entirely if generic vegetation scaling is the intent.

---

## Bottom line

The biome system has the surface area of a AAA biome system — 10 named
presets, climate params, palette tables, scatter rules, alias resolution,
WorldMapSpec — but the **terrain-shape passes that produce heightmap,
erosion, cliffs, and materials read at most two intent fields
(`noise_profile`, `erosion_profile`), and even those collapse to 5- and
3-bucket lookups.** The third intent field (`biome_rules`) is plumbed only
into a pass that doesn't run in production.

The AAA generator script (`build_terrain_aaa_node_v6.py`) constructs the
intent with **no biome arguments at all**, and the multi-biome world handler
chooses **one** dominant biome's terrain_type for the whole world.

For the success criterion the user cares about — "switching
`biome="volcanic"` vs `"arctic"` produces visibly different terrain at the
heightmap layer" — the answer is **no**, in three of three pipelines:

1. `handle_generate_terrain` with `terrain_type=<vb_preset_name>`: differs in
   `terrain_type` *base shape* (one of 5 categories), but not in
   `noise_profile` semantic (collapses to mountains/desert/coastal); identical
   erosion (`temperate` default).
2. `handle_generate_multi_biome_world`: only the dominant biome's
   `terrain_type` reaches the heightmap; other 5 biomes are color-only.
3. `build_terrain_aaa_node_v6.py`: zero biome inputs reach the intent;
   bit-identical output regardless of caller intent.

This is a cleaner instance of the I3-P0-1 spec-theater pattern, with two
distinct P0s that are not duplicates of any already-counted finding.
