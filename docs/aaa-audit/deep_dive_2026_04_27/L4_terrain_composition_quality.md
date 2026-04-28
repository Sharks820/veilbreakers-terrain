# L4 — Terrain Composition Quality (Macro-Scale Output Audit, 2026-04-27)

**Auditor:** Opus deep-dive L4
**Date:** 2026-04-27
**Scope:** Read what the production 8-pass pipeline (`macro_world → structural_masks → pass_hydrology → erosion → structural_masks → cliffs → emit_overhang_meshes → validation_minimal`) actually produces and judge its geological / artistic plausibility against AAA reference output (Ghost of Tsushima, Horizon Zero Dawn, The Witcher 3, Far Cry 6).
**Source root:** `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\`

Already-counted P0s NOT re-counted here: K1-P0-1/2 (biome fields dead), K2-P0-1 (slope unit bug), I3-P0-1 (QualityProfile dead), E-1 / E-2 / E-3 (erodibility 1000×, stratigraphy delta unapplied, hydraulic loop non-functional at AAA sizes).

---

## TL;DR — What Comes Out of the 8-Pass Pipeline

The macro heightmap is **isotropic three-band fBm with 13 % ridged-multifractal blend, then a Gaussian dome** (when the optional `composition_hints` continent dial is supplied — almost never set in production). It has no anisotropic mountain ranges, no oriented drainage divides, no hydrologically coherent ridge–valley hierarchy in the **input** to erosion. The geological-constraint helper `_apply_geological_constraints` (river-valleys-sink / ridges-rise — the only routine in the code base that would impose ridge/valley structure at noise time) is gated behind `normalize=True` and `pass_macro_world` calls `generate_world_heightmap(..., normalize=False)` — so the helper is dead under the production code path.

Erosion does a single analytical pass ("phacelle" gully filter from `terrain_erosion_filter.erosion_filter`) which carves V-creases along the local gradient and produces ridge crests as a byproduct. This *does* impose some local drainage texture but it is **not driven by a real flow simulation** — it is a noise-modulated gully field shaped by the static gradient of the input fBm. The "hydraulic" droplet loop that follows is the pure-Python 50 000-particle Olsen-2004 implementation already flagged as **non-functional at AAA tile sizes (E-3)**; the SPL solver runs 50 implicit steps with `K_scalar=0.001`, `dt=1000`, and (because stratigraphy is an orphan) a uniform `rock_hardness` everywhere.

The result that ships to the player is roughly **"2-octave continent-scale fBm + 5-octave mid fBm + 4-octave high fBm + 13 % ridged blend, then a tile-wide phacelle erosion noise overlay"**. Every VeilBreakers biome — thornwood_forest, corrupted_swamp, mountain_pass, ruined_fortress, abandoned_village, veil_crack_zone, underground_dungeon, sacred_shrine, battlefield, cemetery — collapses to the *same* `terrain_type="mountains"` preset (see L4-P0-1 below), so all 10 biomes generate the same macro shape distribution under a given seed. They differ only in `height_scale` (a post-multiply scalar) and scatter rules.

Net: the macro shape would not pass an art-director review at any of the four reference studios. It is on the "early Houdini HeightField tutorial" end of the spectrum, not "Decima / Foundation Engine open world."

---

## P0 Findings (NEW — not duplicating already-counted P0s)

### L4-P0-1 — All 10 VB biomes collapse to a single "mountains" terrain_type at the noise stage
**Severity:** P0 — fundamental landscape diversity failure
**Source:** `veilbreakers_terrain/handlers/_terrain_world.py:861-869`

```python
noise_profile = (intent.noise_profile if intent else None) or "dark_fantasy_default"
terrain_type_map = {
    "dark_fantasy_default": "mountains",
    "temperate": "mountains",
    "arid": "desert",
    "arctic": "mountains",
    "coastal": "coastal",
}
terrain_type = terrain_type_map.get(str(noise_profile), "mountains")
```

`intent.noise_profile` is fed from `params["terrain_type"]` (`environment.py:2977`). The 10 `VB_BIOME_PRESETS` (`environment.py:436-615`) set `terrain_type` to one of `{"hills", "flat", "mountains", "plains", "chaotic"}`. None of those keys (except the trivial `"mountains" → "mountains"` identity, which only matches because `"mountains"` is *also* the `.get` default — there is **no `"mountains"` key in `terrain_type_map`**) are present in the dict. Result:

| VB biome | preset terrain_type | resolves to |
|---|---|---|
| thornwood_forest | hills | mountains |
| corrupted_swamp | flat | mountains |
| mountain_pass | mountains | mountains |
| ruined_fortress | hills | mountains |
| abandoned_village | plains | mountains |
| veil_crack_zone | chaotic | mountains |
| underground_dungeon | flat | mountains |
| sacred_shrine | plains | mountains |
| battlefield | hills | mountains |
| cemetery | flat | mountains |

The rich `TERRAIN_PRESETS` table at `_terrain_noise.py:905-1006` ("hills", "plains", "volcanic", "canyon", "cliffs", "flat", "coastal", "swamp", "chaotic", "desert" — each with distinct `octaves`, `persistence`, `amplitude_scale`, `post_process`, `ridged_blend`, `crater_radius`, `step_count`, etc.) is **completely unreachable** from any production tile. A swamp generates with mountain spectra; a battlefield generates with mountain spectra; a cemetery generates with mountain spectra. The only inter-biome shape difference is the `height_scale` post-multiplier (5 m for swamp, 40 m for mountain_pass) — i.e. the same shape stretched vertically, not a different landform.

This goes beyond K1 (biome field selection within multi-biome worlds) — it is *single-biome shape collapse*. K1 found that biome[0]'s shape is used for the whole world; L4-P0-1 finds that biome[0]'s shape is itself one of 1–2 hard-coded outputs.

**AAA reference:** Ghost of Tsushima ships ~15 visually distinct biomes each with bespoke macro silhouettes; Horizon Zero Dawn's Frozen Wilds vs. Sundom vs. Carja heartland use different fBm spectra, anisotropic mountain seeds, and different post-shaping (canyon stepping, crater stamping, etc.) — exactly what `TERRAIN_PRESETS["volcanic"|"canyon"|"cliffs"|"swamp"]` would supply if the production path could reach them.

**Fix:** The `terrain_type_map` should pass `noise_profile` straight through to `generate_world_heightmap(terrain_type=...)` for any value present in `TERRAIN_PRESETS`, and only fall back to the dark-fantasy default for unknown strings. The 5-key map is a leftover from when the project had only 5 climate profiles.

---

### L4-P0-2 — `_apply_geological_constraints` (river-valleys-sink, ridges-rise) is dead under production path
**Severity:** P0 — the only ridge-valley-hierarchy enforcer in the noise generator is bypassed
**Source:** `veilbreakers_terrain/handlers/_terrain_noise.py:1349-1350` and `_terrain_world.py:885`

```python
# _terrain_noise.py:1349
if normalize:
    hmap = _apply_geological_constraints(hmap, cell_size=cell_size)
```

```python
# _terrain_world.py:876-886 (production call site)
hmap = generate_world_heightmap(
    width=tile_size, height=tile_size, ...,
    terrain_type=terrain_type,
    normalize=False,        # ← production always passes False
).astype(np.float32)
```

`_apply_geological_constraints` (`_terrain_noise.py:1111-1184`) is the function that pulls valley cells (concave Laplacian) downward by 8 % of the local height range and lifts ridge cells (convex Laplacian) upward by 6 %. Comments in the function explicitly state: *"This mirrors the physical reality that erosion preferentially removes material from convex surfaces and deposits it in concave ones."* It is gated entirely on `normalize=True`. Under the production path (`pass_macro_world` always calls with `normalize=False` so seam coordinates remain world-space deterministic), this routine never runs.

The consequence: the heightmap fed into erosion has **no enforced ridge–valley topology**. It is straight isotropic fBm + ridged-multifractal blend at 13 % weight. Ridges in this input are statistical accidents of the noise — they do not form coherent watershed divides, do not orient along tectonic strike, do not have the convex-up cross-section that real ranges do.

The downstream `erosion_filter` (analytical phacelle gully filter) then carves gullies along the *local gradient of this isotropic noise*. With no real ridge structure in the input, the gullies do not converge into dendritic drainage networks the way real catchments do — they fan out wherever local slope exists, and look like a noise-modulated scratch-pattern rather than a Strahler-ordered river network.

**AAA reference:** Witcher 3's Skellige cliffs, Horizon's Cauldron Sigma surroundings, and Ghost of Tsushima's Iki are all painted over a base heightmap where drainage is either authored by hand (Houdini HeightField MaskByFeature → river paths → hydraulic erosion seeded onto those paths) or where the *unprocessed* fBm goes through a Gaea Geology / World Machine HydroErosion node that imposes ridge-and-valley topology before fluvial erosion. Our pipeline ships with that exact step (`_apply_geological_constraints`) but disables it.

**Fix:** Either (a) call `_apply_geological_constraints` unconditionally (it is mathematically tile-safe — uses `np.pad(reflect)`), or (b) move the call into `pass_macro_world` after the noise composition so it operates regardless of the `normalize` argument. Option (b) is preferable — the function is already cell-size-aware.

---

## P1 Findings (NEW)

### L4-P1-1 — `composition_hints` continent dial is the *only* non-noise macro feature, almost never set
`pass_macro_world:944-995` adds an optional Gaussian dome bias derived from `composition_hints["continent_center_x"|"continent_center_y"|"continent_radius"|"continent_amplitude"]`. Any tile that does not author these keys gets a pure-noise heightmap. Searching the code base for set-sites of `composition_hints`: it is wired through from `params["composition_hints"]` in `_execute_terrain_pipeline` (`environment.py:2966`) but no production caller — including `handle_generate_terrain_aaa` — sets these keys. So in practice every production tile is "noise + nothing." Even if it were set, it is **one Gaussian dome** — not a tectonic plate boundary, not a fault-line uplift, not a multi-peak mountain belt — so it produces a single radially-symmetric bump that reads as a giant featureless dome rather than a continent.

### L4-P1-2 — `meso` band gets a static 5-octave default; no anisotropy ever applied
`generate_world_heightmap:202-217` builds the meso band with `octaves=_meso_octaves` (default 5), no domain warp, isotropic Perlin. The Quilez domain warp (`generate_heightmap:1302-1308`) is gated on `warp_strength > 0.0`, but `pass_macro_world` never forwards a `warp_strength` kwarg. So the meso band has no anisotropy: ridges run in random directions instead of along the tectonic strike that real ranges show (Olympus Mons radial vs. Sierra Nevada N-S vs. Atlas E-W). All three reference studios use anisotropic warps for their mountain bands; our pipeline does not.

### L4-P1-3 — `_apply_terrain_preset` for `mountains` does only a `np.sign(x) * |x|^1.6` power transform
`_terrain_noise.py:1399-1412` for `terrain_type="mountains"`, `normalize=False` branch: `hmap = np.sign(signed) * np.power(np.abs(signed), 1.6)`. This sharpens peaks but does not add ridge structure, does not introduce stepped escarpments, does not stamp craters. The other `post_process` branches (`crater`, `canyon`, `step`) are all unreachable from production thanks to L4-P0-1. So the production path's *only* shape post-processing is a single per-cell power transform — no `cliff` step quantization for cliffs biome, no `canyon` ridge inversion for chaotic biome, no `crater` stamp for volcanic biome.

### L4-P1-4 — Erosion `analytical_cfg` has only 3 profiles ("temperate", "arid", "alpine"); none keyed on biome
`pass_erosion:1137-1142` selects the analytical erosion config from `intent.erosion_profile`, not from biome. Default is `"temperate"` (`environment.py:2978`). Production never overrides this, so all 10 biomes get *identical* erosion: 4 octaves, gully_weight=1.0, strength=0.5, fade_amplitude default 1.0. Mountain_pass (alpine) and corrupted_swamp (low gradient) get the same erosion treatment.

### L4-P1-5 — `apply_thermal_erosion_masks(iterations=6)` is far below AAA threshold
`pass_erosion:1202-1207` runs 6 thermal iterations. World Machine's "Thermal Weathering" preset uses 200–500 iterations to relax hard talus angles to natural slopes; Gaea's "Stratify+Wizard" pipeline uses ~150. 6 iterations on a 512² tile redistributes only material within a ~3-cell neighborhood, not enough to reach the talus angle equilibrium that gives natural slopes their characteristic bow shape. Sharp post-analytical features remain.

### L4-P1-6 — Second `structural_masks` pass overwrites first pass's `ridge_eroded` ownership in the DAG, but reuses `compute_base_masks` so `ridge` regenerates from the eroded height — yet `ridge_eroded` survives
`pass_structural_masks:1027-1034` re-runs `terrain_masks.compute_base_masks` against `stack.height` (which is now post-erosion at the second invocation). It writes `ridge` (raw Laplacian-based mask). It does NOT touch `ridge_eroded`, which was published earlier by `pass_erosion`. Downstream consumers are split: cliffs reads `ridge`, scatter reads `ridge` again, but materials reads neither. Result: there are two ridge fields with subtly different geometric meanings (raw structural Laplacian over eroded DEM vs. analytical phacelle ridge_map) and no canonical choice. Not a P0, but it is exactly the sort of unowned-channel inconsistency that K-sweep flagged. Worth merging into K1/K2 follow-up.

---

## P2 Findings

- **L4-P2-1** — `compute_base_masks` `extract_ridge_mask` thresholds at the 5th percentile of the *negative* second-derivative tail (`terrain_masks.py:130-133`). On smoothed eroded terrain, the negative tail is shallow, so the 5th percentile threshold often selects ~5 % of cells regardless of whether real ridges exist. The mask is therefore self-calibrating to "always 5 % ridge cells" and does not reflect ridge density.
- **L4-P2-2** — `detect_basins(..., min_area=50)` (`terrain_masks.py:145-298`) labels watersheds via watershed_ift, but on a 512² tile a single-pass priority flood without sink filling produces dozens of micro-basins (every depression — including erosion noise pits — is its own basin). Reference DEMs use Wang & Liu 2006 sink-filling first; we do not. Result: basin count metric is dominated by noise pits, not by drainage organization.
- **L4-P2-3** — Continent dome `continent_amplitude` defaults to **60 % of full height range** (`pass_macro_world:957-959`). When a caller does set this, the dome adds 0.6× the existing range as additional elevation, swamping the fBm and producing a monotonic radial slope from edge to center — i.e. a giant smooth dome with surface texture, not a mountain range. The default amplitude is too high.
- **L4-P2-4** — No tectonic uplift band, no sediment basin band, no plateau stamping. Real game terrain (Witcher 3 Velen, RDR2 Grizzlies) layers an authored "uplift mask" → fluvial erosion → "deposition mask" → fan deposition. Our pipeline has neither uplift nor deposition zones at the macro scale.

---

## What Stratigraphy's Absence Costs

`pass_stratigraphy` is not registered in `terrain_pipeline.py` (verified — Grep returned no match). The pipeline therefore never populates `rock_hardness`. Downstream consequences in `pass_erosion`:

- `K_map = None` (line 1112) → SPL solver and analytical erosion fall back to uniform `K_scalar = 0.001` for every cell.
- The `analytical_delta = analytical_delta * k_mod` adjustment at line 1157-1164 never runs (the `if rock_hardness is not None` branch is skipped).
- The `downstream_delta = new_height - h_after_analytical; new_height = h_after_analytical + downstream_delta * k_mod_full` re-attenuation at line 1286-1291 also never runs.
- Cliff faces have no banded resistance pattern → they erode uniformly into smooth slopes rather than the stepped, bench-and-cap shape that real sedimentary cliffs (Bryce Canyon, Cappadocia, Dover) have.
- The Witcher 3's Velen marshes use a stratified soft/hard horizon to produce alternating mud benches; Horizon's Sundom uses banded sandstone beds. Our cliffs are featureless tilted slabs.

Combined with E-2 (stratigraphy delta unapplied even when computed), there is **zero geological layering anywhere in the production output** regardless of which entry point you use.

---

## AAA Comparison — what a Decima / Foundation / RED-Engine artist would say

A senior terrain artist at Guerrilla, Sucker Punch, or CDPR looking at the production output would call out, in priority order:

1. **"Why does every region of your map have the same silhouette?"** — L4-P0-1: 10 biomes, 1 macro shape.
2. **"There are no mountain ranges, just lumps."** — L4-P1-2 + L4-P0-2: no anisotropy, no ridge–valley enforcement.
3. **"The drainage doesn't go anywhere."** — Erosion gullies are a noise overlay, not a routed flow network. (Even with `pass_hydrology` running, the SPL solver only does 50 implicit steps with uniform K=0.001 — the resulting incision is in the millimeter range relative to a 200 m vertical scale.)
4. **"The cliffs don't have layers."** — Stratigraphy unwired (E-2 already counted).
5. **"Why is this 200 m of vertical relief? Real mountain belts are 2–4 km."** — `_HEIGHT_SCALE["mountains"]=200.0` (`pass_macro_world:894`). Olympus Vihren is 2914 m, Mont Blanc 4810 m, Snowdon 1085 m. 200 m is foothill scale, not mountain. (The biome `height_scale` then *multiplies* the [-1,+1] noise, but the macro pass first scales the raw output to the 200 m envelope, so the final relief is `height_scale × ~1.0 ≈ 5–40 m`. Mountain_pass at `height_scale=40` produces 40 m of relief — that is a single hill in a real game world.)
6. **"There is no plateau, no escarpment, no canyon, no crater anywhere."** — All 4 special post-processes (`step`, `canyon`, `crater`, "swamp") are unreachable (L4-P0-1).
7. **"The hydraulic erosion looks like sandpaper, not riverbeds."** — E-3: pure-Python droplet loop is non-functional at AAA tile sizes; combined with the lack of input ridge–valley topology (L4-P0-2), there are no ridge-to-valley sediment transport paths to begin with.
8. **"Where's the navigation logic? — there is no flat-ground bias for traversable corridors."** — No anisotropic blending toward path-friendly terrain.

In total: the macro-shape pipeline is at the level of a Gaea/World Machine *tutorial demo* — an isotropic fBm sketch — not a production AAA terrain. The infrastructure to do better is **all in this code base** (the `TERRAIN_PRESETS` table, the `_apply_geological_constraints` helper, the stratigraphy module, the SPL solver, the priority-flood D8 router, the analytical erosion octaves) — but the production wiring routes around almost every quality gate.

---

## Summary of NEW P0/P1 from L4

| ID | Severity | One-line | Source |
|---|---|---|---|
| L4-P0-1 | P0 | All 10 VB biomes resolve to `"mountains"` terrain_type via 5-key gate | `_terrain_world.py:861-869` |
| L4-P0-2 | P0 | `_apply_geological_constraints` is dead — gated on `normalize=True`, production calls with `normalize=False` | `_terrain_noise.py:1349-1350` + `_terrain_world.py:885` |
| L4-P1-1 | P1 | `composition_hints` continent dial never set in production; only macro non-noise feature | `pass_macro_world:944-995` |
| L4-P1-2 | P1 | No domain-warp / anisotropy; meso band is 5-octave isotropic Perlin | `_terrain_world.py:202-217`; warp gated at `_terrain_noise.py:1302` |
| L4-P1-3 | P1 | Production "mountains" preset only applies a `|x|^1.6` power transform; `crater`, `canyon`, `step` unreachable | `_terrain_noise.py:1399-1412` (+ L4-P0-1) |
| L4-P1-4 | P1 | All 10 biomes get `erosion_profile="temperate"` analytical config; no per-biome erosion | `pass_erosion:1090, 1137-1142` |
| L4-P1-5 | P1 | Thermal erosion 6 iterations vs. AAA reference 150–500 | `pass_erosion:1202-1207` |
| L4-P1-6 | P1 | `ridge` (re-computed by 2nd structural_masks) and `ridge_eroded` (from erosion) coexist with split downstream consumers | `_terrain_world.py:1017-1056, 1191` |
| L4-P2-1..4 | P2 | Ridge-mask self-calibrates to 5% density; basin count dominated by noise pits; continent dome amplitude default is 60% range; no uplift/sediment-basin bands | `terrain_masks.py:130, 145-298`; `pass_macro_world:957` |

**Net assessment of macro-scale composition quality grade: D−.** The infrastructure is partially built but the production wiring guarantees the *worst* available combination (single noise preset, no geological-constraint enforcement, no anisotropy, no biome differentiation, uniform erosion config). Two single-line wiring fixes (L4-P0-1 pass-through and L4-P0-2 unconditional `_apply_geological_constraints` call) would already lift the grade to roughly C+; reaching B/B+ requires anisotropic warp wiring (L4-P1-2) and a per-biome erosion config (L4-P1-4); reaching A territory requires authored uplift/strike fields (L4-P2-4) and stratigraphy wiring (already covered by E-2).
