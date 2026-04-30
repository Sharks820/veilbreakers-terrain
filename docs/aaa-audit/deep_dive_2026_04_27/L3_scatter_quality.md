# L3 — Scatter & Vegetation Distribution Quality Deep-Dive

**Date:** 2026-04-27
**Scope:** Whether the scatter that runs in production produces AAA-quality placement.
**Verdict:** **F (catastrophic).** Production auto-generated terrain tiles ship with **zero scatter**. The only scatter call site is an unrelated demo/agent command (`generate_multi_biome_world`), and even when that runs the placement is hard-capped at 12,000 instances total across an entire world — below 1% of AAA bar.

Already-counted (not re-listed):
- I2-P0-1 (`vegetation_system.py` zero production imports)
- I5-P0-4 (`pass_scatter_intelligent` orphaned)
- J6 (`apply_collision_exclusion` dead, P2)

---

## 1. `handle_scatter_vegetation` — Registered, but not called from production tile pipeline

**Registered in `COMMAND_HANDLERS`** at `veilbreakers_terrain/handlers/__init__.py:1090-1102` as the canonical scatter route after C-1 deprecation of `scatter_biome_vegetation`. Verified at `__init__.py:1105-1106`:

```
# vegetation_system.scatter_biome_vegetation is deprecated (C-1):
# removed from COMMAND_HANDLERS; handle_scatter_vegetation is the canonical path.
```

**The handler body** (`environment_scatter.py:3066-3459`) is reasonably AAA-quality in *isolation* (multi-pass `_scatter_pass`, biome-keyed `_BIOME_DENSITY`, species constraints, terrain-normal alignment, slope/altitude/moisture filters, building exclusion, road-mask exclusion, hero-exclusion, wind-field rotation, LOD tier counts).

**Single call site in the entire production codebase:** `environment.py:8398-8410`, inside `handle_generate_multi_biome_world`. Verified by exhaustive grep across `veilbreakers_terrain/`:

```
environment.py:8398:        from .environment_scatter import handle_scatter_vegetation
environment.py:8401:                veg_result = handle_scatter_vegetation({
```

**Production tile pipeline does NOT call scatter:**

- `terrain_pipeline.run_pipeline` default `pass_sequence` (`terrain_pipeline.py:559-569`):
  ```
  ["pass_generate_low_freq_hmap", "terrain_labels", "structural_masks",
   "pass_generate_high_freq_detail", "pass_composite_hmap", "validation_minimal"]
  ```
  + optional `["pass_hydrology", "erosion"]` when `scene_read` is present. **No scatter pass, no vegetation pass, no asset pass.**
- `handle_generate_terrain` (`environment.py:1903-2245`) — verified: zero references to scatter, vegetation, or `tree_instance_points` in its 340-line body.
- `handle_generate_terrain_tile` (`environment.py:2247-…`) — verified: zero references to scatter or vegetation. Tile generation produces heightmap + cliff overlays + splatmap export, then ends.
- `terrain_region_exec.py` — zero matches for scatter/vegetation/tree_instance.

**MCP-only entry:** `blender_server.py:43` exposes `multi_biome_world → env_generate_multi_biome_world`. Triggered only when an external MCP client / agent explicitly issues that command. Default unattended terrain pipelines (`run_pipeline`, region exec, golden snapshot regen) **never** reach this code path.

### L3-P0-1 (NEW) — Production auto-generated tiles have zero scatter

**Severity:** P0 (catastrophic — meets the document's stated P0 threshold).
**Evidence:** `terrain_pipeline.py:559-569` default sequence omits scatter; `handle_generate_terrain` and `handle_generate_terrain_tile` bodies contain zero scatter calls; `handle_scatter_vegetation` is reachable only via `handle_generate_multi_biome_world`, which is only an MCP/agent on-demand command.
**Impact:** Every tile that comes out of the unattended terrain pipeline ships as bare heightmap + materials + (optional) water/caves. No trees, no grass, no rocks, no props. A dark fantasy AAA forest is rendered as bald geometry.

**Fix scope:** Add `pass_scatter_intelligent` (or a thin adapter wrapping `_generate_multipass_scatter_placements`) into the default `pass_sequence` after `pass_composite_hmap` and `validation_minimal`. Wire `tree_instance_points`/`detail_density` through to mesh export. Remove the gating on `scatter_veg = True` being inside a separate "multi_biome_world" demo command.

---

## 2. `_scatter_pass` algorithm quality — Reasonable AAA when it runs

`environment_scatter.py:2508-2966` is a **multi-pass species-aware Poisson** with the following AAA-grade primitives:

- **Per-species Poisson disk separation** (`_SPECIES_CONSTRAINTS`, `environment_scatter.py:2463-2487`) — tree=5m, bush=2m, grass=0.9m, rock=1.2m. This matches Ghost of Tsushima / Horizon ZD species spacing.
- **Lloyd relaxation** (2 iterations) on the structure pass, callsite at `_scatter_pass` per inline comment "GTS/Horizon use 2-3 passes to break residual clustering".
- **Species altitude bands** (alt_min/alt_max) and **moisture bands** (moisture_min/max) enforced in `_passes_species_constraints` (`environment_scatter.py:2651-2657`).
- **Density modulation** via `_build_scatter_density_map` (`environment_scatter.py:2310-2376`) — multiplies base biome density by sigmoid slope-flatness weight, adds water-proximity boost (+0.3 near water for moisture-loving species), adds disturbance pioneer-boost (+0.4 in disturbed cells).
- **Per-pass species mix:** structure (trees + bushes) → ground_cover (grass with tree-shadow exclusion) → debris (rocks with power-law sizing 70/25/5).
- **Combat clearings** respected via `_in_clearing` (uses `inner_clear_radius` Witcher-3 style format).
- **LOD assignment** per placement via `_LOD_THRESHOLDS` (`environment_scatter.py:2384-2389`).

**Quality assessment (when it runs):** B+ for the placement core. Slope+water+disturbance triad is industry-standard. Species constraints align with real ecological gradients. Lloyd relaxation is a real AAA polish step.

---

## 3. Density map source — Procedural, NOT consumed from `vegetation_system.py`

`_build_scatter_density_map` (`environment_scatter.py:2310-2376`) builds the density map **on the fly inside `_scatter_pass`** from:
- `_BIOME_DENSITY` lookup table (`environment_scatter.py:1652-1662`) — 9 hardcoded scalar densities (`dark_forest=0.8`, `corrupted_wasteland=0.05`, `mountain=0.2`, `default=0.5`).
- Slope sigmoid weight from `slope_map`.
- Optional `water_proximity_map` (additive boost).
- Optional `disturbance_map` (pioneer boost).

**It does NOT read from `vegetation_system.py`'s `BIOME_VEGETATION_SETS` density-map builder** — confirmed by I2-P0-1 (zero production imports of `vegetation_system`). Confirmed by direct grep here: 0 imports of `vegetation_system` from `environment_scatter.py`.

**`detail_density` channel consumer (Fix 9.1):** `environment_scatter.py:3221-3232` reads `_stack_value(_stack, "detail_density")` from the pipeline mask stack and stochastically rejects placements per cell. **But this only fires when the caller passes a `stack` parameter populated by `pass_scatter_intelligent` — which is orphaned (I5-P0-4) — so in production this channel is always None and the rejection step is a no-op.**

**Net result:** scatter (when invoked from `multi_biome_world`) uses a single hardcoded scalar `_BIOME_DENSITY[biome] ≈ 0.5–0.8` modulated only by slope/water/disturbance. **The `vegetation_system.py` rich density-map pipeline (1758 lines, BIOME_VEGETATION_SETS, ecological succession curves) is dead weight.**

### L3-P1-1 (NEW) — `_BIOME_DENSITY` is a 9-row lookup table; vegetation_system's per-cell density maps are unwired
Even when scatter runs, every cell in a biome region gets the same scalar density × (slope, water, disturbance). No species-density curves per biome, no understory layering, no canopy gap modeling. Below B+.

---

## 4. Single-biome scatter applied to multi-biome terrain — quality bug

`environment.py:8399-8410` iterates `for biome_name in spec.biome_names` and calls `handle_scatter_vegetation` once per biome. **Each call passes `biome_name` as a single string** that flows into `_scatter_pass`'s `biome` argument and is used only for `_BIOME_DENSITY[biome]` lookup. **There is no biome region mask.** All scatter passes operate on the entire terrain extent.

The handler does not receive a `biome_id` channel or a `biome_mask`. It scatters all 6 biomes' worth of trees across the full world, each pass independently. The placements use Poisson across the full extent; only altitude/slope/moisture filter them — not "this point is inside biome X's region."

**Net effect:** in a corrupted-wasteland + dark-forest world, dark-forest trees are scattered everywhere altitude/slope permits, not just inside the dark-forest Voronoi cells. With 6 biomes, this triple-stacks placements (Poisson collisions are within-pass only, not cross-pass).

### L3-P1-2 (NEW) — Multi-biome scatter has no per-biome region mask
`handle_scatter_vegetation` accepts a single `biome_name` string and applies it globally; `handle_generate_multi_biome_world` calls it 6× over the same terrain with no spatial restriction. Scatter produces biome-incoherent vegetation distribution. To fix: pass a `biome_mask` (rasterized from `WorldMapSpec.biome_ids`) and require scatter to reject candidates outside the mask.

---

## 5. Collision exclusion is dead

`apply_collision_exclusion` is imported at `environment_scatter.py:57` and **never called** anywhere in `environment_scatter.py`. Direct behavior coverage now lives in `tests/test_scatter_engine_distribution.py`; the production scatter route still needs general prop-vs-prop collision wiring.

J6 already classified this P2. I do **not** elevate without new evidence. The reason J6 is conservative: building exclusion zones (`_in_building`/`building_exclusion_zones_world`) and combat clearings (`_in_clearing`) DO run inside `handle_scatter_vegetation` (`environment_scatter.py:3158-3180`), and tree-shadow exclusion runs inside the ground-cover pass. So props vs. building geometry have a guard. What's missing is the *general* prop-vs-prop volumetric collision exclusion (e.g., torch inside boulder, log embedded in trunk). For the dark fantasy aesthetic where ruins and rocks intermix densely, the absence is noticeable but masked by the other guards. P2 stands.

---

## 6. Ecotone transitions — none in scatter pipeline

`terrain_ecotone_graph.py` exists and registers a `bundle_j_ecotones_pass`. Bundle J is **not in the default `pass_sequence`**. Cross-checked: `environment_scatter.py` has zero references to "ecotone", "biome_blend", or "biome_transition".

`WorldMapSpec` has a `transition_width_m` parameter (default 15.0m) used by `_compute_vertex_colors_for_biome_map` (line 8431) for vertex-color blending. **This affects color, not scatter density.** The scatter pass treats biome borders as binary.

### L3-P1-3 (NEW) — No scatter ecotones
At biome borders the scatter changes abruptly (because each biome's scatter is a separate `_scatter_pass` invocation with its own `_BIOME_DENSITY`). A forest does not thin out approaching grassland; alpine shrubs don't grade into grass at altitude. Compared to Witcher-3 / Horizon-Zero-Dawn which use 30-100m density falloff curves at biome interiors, this is C-grade.

---

## 7. Instance count — orders of magnitude below AAA bar

`handle_generate_multi_biome_world` defaults (`environment.py:8326-8410`):
- `world_size = 512.0` (default 512m × 512m = 0.262 km²).
- `max_veg_instances = 2000` per biome.
- `biome_count = 6` → max 12,000 instances total.
- 12,000 instances / 0.262 km² ≈ **45,800 instances per km²** at default settings — **below** the AAA dense-forest bar of 50k–500k per km² *and that's all foliage types combined* (trees + bushes + grass + rocks). Trees alone in a Witcher-3 dark forest exceed 100k/km².
- For a 2km × 2km AAA tile: cap is still 12,000 → **3,000 per km² combined** — two orders of magnitude below AAA bar.

The cap is reachable: `placements = placements[:max_instances]` (`environment_scatter.py:3318-3319`) hard-truncates without sampling.

### L3-P0-2 (NEW) — Hardcoded 2,000-per-biome cap caps all output below 1% of AAA density
At the default 2,000 cap × 6 biomes = 12,000 total instances per world. Even the Poisson disk minimum-separation (5m for trees) implies a theoretical max of ~40,000 trees per km² — meaning the cap itself, not the algorithm, is the bottleneck. Raising it to 500k+ would expose other bugs (template-instance collection cost, no chunked LOD streaming) but is the prerequisite for AAA density.

**Severity:** P0. The cap is the single tunable that determines whether a player sees a forest or a sparse meadow. Default 2000 produces visibly empty worlds.

---

## 8. Duplicate scatter execution — both paths exist but only one fires

J7-P1 noted dual paths. Verified state:

- **Path A: `pass_scatter_intelligent`** (`terrain_assets.py:790-885`) — registered via `register_bundle_e_passes` (`terrain_master_registrar.py:224`), but NOT in the default `pass_sequence`. Writes `tree_instance_points` and `detail_density` to mask stack. **Orphaned (I5-P0-4 confirmed).** It only fires when a caller explicitly includes `"scatter_intelligent"` in `pass_sequence`.
- **Path B: `handle_scatter_vegetation`** — only fires when `handle_generate_multi_biome_world` MCP command is dispatched. Reads `detail_density` from stack only if a stack is provided.

**Can both run in sequence producing double-density?** In theory, yes: an external orchestrator could call `run_pipeline` with `pass_sequence=["...", "scatter_intelligent"]` to populate `tree_instance_points`/`detail_density` on the stack, then dispatch `multi_biome_world` (whose scatter would consume `detail_density` to *reject* candidates, not augment). The `detail_density` consumer at `environment_scatter.py:3223-3232` actually filters candidates *down* — so if both run, the result is `multi_biome_world` placements stochastically masked by the `pass_scatter_intelligent` density map. **Not double-density**, but also **not coherent** — two independent scatter algorithms with different density math layered, producing whichever is more restrictive per cell.

In practice, no production code path triggers both. J7-P1 stays at P1.

---

## 9. Other findings

### L3-P1-4 (NEW) — Silent failure mode in multi-biome scatter
`environment.py:8412-8413`:
```
except Exception:
    pass  # Biome may not have vegetation set -- skip silently
```
Any error in `handle_scatter_vegetation` — including the most likely failure mode where `biome_name` isn't in `_BIOME_DENSITY` (only 9 entries; `WorldMapSpec` can produce arbitrary names) — is swallowed silently. A 6-biome world where 5 biome names are unknown to `_BIOME_DENSITY` produces 1× scatter call's worth of vegetation with no error and no log. Already flagged in B15_environment_atmospheric_zones.md but worth re-citing because it directly hides L3-P0-1 from operators.

### L3-P2-1 (NEW) — `bake_wind_colors=True` hardcoded in only call site
`environment.py:8408`. The wind vertex-color bake runs even on biomes that don't use grass cards (e.g., corrupted_wasteland, mountain). Wasted work; no correctness bug. Polish item.

### L3-P2-2 (NEW) — `_BIOME_DENSITY` table missing many biomes
`environment_scatter.py:1652-1662` lists 9 biomes; `WorldMapSpec.biome_names` and the `BIOME_PALETTES_V2` table list 14+. Unknown biomes silently fall through to `default=0.5` density, masking biome-specific scatter behaviour.

---

## Summary table

| ID | Severity | Item | Evidence |
|----|----------|------|----------|
| **L3-P0-1** | **P0** | Production auto-generated tiles have zero scatter | `terrain_pipeline.py:559-569` default seq has no scatter; `handle_generate_terrain[_tile]` body has no scatter calls |
| **L3-P0-2** | **P0** | 2,000 instances/biome cap is 1% of AAA bar | `environment.py:8406` `max_veg_instances=2000`; max 12k total for 6-biome world |
| L3-P1-1 | P1 | `_BIOME_DENSITY` 9-row lookup; vegetation_system rich maps unwired | `environment_scatter.py:1652-1662`; I2 |
| L3-P1-2 | P1 | Multi-biome scatter has no per-biome region mask | `environment.py:8399-8410` calls scatter 6× over full extent |
| L3-P1-3 | P1 | No scatter ecotones; abrupt biome borders | `environment_scatter.py` zero ecotone refs; bundle_j ecotones pass orphaned |
| L3-P1-4 | P1 | Silent except in multi-biome scatter loop | `environment.py:8412-8413` |
| L3-P2-1 | P2 | bake_wind_colors hardcoded for all biomes | `environment.py:8408` |
| L3-P2-2 | P2 | `_BIOME_DENSITY` missing biomes | `environment_scatter.py:1652-1662` |

---

## Bottom line

The scatter algorithm core (`_scatter_pass`) is competent — B+ in isolation. **It almost never runs.** The production terrain pipeline produces bare geometry. Only the `multi_biome_world` MCP command invokes scatter, and even then it tops out at 12,000 instances total for an entire world — sub-1% of AAA density.

For the dark-fantasy AAA bar Conner is targeting, this means: every screenshot, every preview, every golden snapshot from the unattended pipeline has been rendering with no vegetation. If the project has been visually evaluating terrain quality without manually invoking `multi_biome_world`, the scatter-quality bar has not been measured at all.

**Two new P0s** (L3-P0-1, L3-P0-2). **Four new P1s** (L3-P1-1 through L3-P1-4). Existing P0s (I2-P0-1, I5-P0-4) and P2 (J6) re-confirmed at cited lines.
