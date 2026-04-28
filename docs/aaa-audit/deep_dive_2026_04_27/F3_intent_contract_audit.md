# F3: TerrainIntent Contract Audit

**Audit date:** 2026-04-27
**Auditor:** Claude (Opus) — F3 dispatch
**Scope:** `TerrainIntentState`, `TerrainQualityProfile`, `WaterSystemSpec`, ProtocolGate
**Sources:**
- `veilbreakers_terrain/handlers/terrain_semantics.py:1275-1335` (TerrainIntentState)
- `veilbreakers_terrain/handlers/terrain_semantics.py:1212-1230` (WaterSystemSpec)
- `veilbreakers_terrain/handlers/terrain_quality_profiles.py` (TerrainQualityProfile + 4 built-in profiles)
- `veilbreakers_terrain/handlers/terrain_protocol.py` (7 ProtocolGate rules)

---

## TL;DR — Severity Triage

| Severity | Count | Examples |
|----------|-------|----------|
| **P0 — completely silent (declared, never read)** | 2 fields | `morphology_templates`, `biome_rules` |
| **P0 — partially read but impotent** | 11 of 13 WaterSystemSpec fields | `meander_amplitude`, `bank_asymmetry`, `tidal_range`, `braided_channels`, `estuaries`, `karst_springs`, `perched_lakes`, `hot_springs`, `wetlands`, `seasonal_state`, `hero_waterfalls` |
| **P0 — quality_profile fields with no consumer** | 27 of 35 profile fields | See §"Quality Profile Delta Analysis" |
| **P1 — typed Optional, used without guard** | 2 sites | `intent.scene_read` (rule_1 raises early but other passes deref), `intent.composition_hints` (frozen+dict — mutable through `intent.composition_hints[...]`) |
| **P1 — silent-wrong on extreme values** | 4 fields | `intent.seed` accepts negative, `tile_size` no postcondition, `cell_size` no postcondition, `region_bounds` not validated against tile_size×cell_size |
| **P2 — rule validators that don't validate** | rule_2 (degraded to warning), rule_5/6 (only fire if caller passes params dict) |

---

## Fields That Are Documentation-Only (declared but never read in production)

### `TerrainIntentState.morphology_templates: Tuple[str, ...] = ()`
- **Declared:** `terrain_semantics.py:1293`
- **Read sites:** Only `terrain_checkpoints.py:296` (serialize) and `:433` (round-trip from JSON). Zero handler reads.
- **Impact:** AAA pipeline can carry a list of "morphology templates" (presumably geomorphology archetypes — fluvial, glacial, karst…) but the field is round-tripped through checkpoints with no consumer ever inspecting it.
- **Likely intent (from name):** Pick generation grammar archetype. **Currently:** dead.

### `TerrainIntentState.biome_rules: Optional[str] = None`
- **Declared:** `terrain_semantics.py:1289`
- **Read sites:** Only `terrain_checkpoints.py:293` (serialize) and `terrain_semantics.py:1312` (intent_hash). Zero handler reads.
- **Impact:** Field name suggests it should switch which biome generation grammar is applied. The actual `biome_id` mask channel is produced from analytical slope/altitude bands inside `_biome_grammar.py`, with no reference to `intent.biome_rules`. The G1 wiring audit (G1_wiring_disconnections.md:572) already flagged this as a blocker — `intent.biome_rules` is supposed to gate biome selection but never does.
- **Note:** A *parameter* called `biome_rules` exists in `environment.py:3701` (`params.get("biome_rules") or BIOME_RULES`) — but that is **not** `intent.biome_rules`. It is a distinct legacy params-dict shim that bypasses the intent contract entirely.

---

## Fields That Are Read But Don't Change Output

### `WaterSystemSpec` — 11 of 13 fields impotent

`environment.py:2940-2964` faithfully constructs a `WaterSystemSpec` from params. **No downstream pass reads `state.intent.water_system_spec`.** The only consumer is `environment.py:2992-2995` (same function), which extracts `min_drainage_area`, `river_threshold`, `lake_min_area`, `network_seed` to pass directly to `WaterNetwork.from_heightmap`. The remaining 11 fields disappear into the void:

| Field | Default | Read by any pass? |
|-------|---------|--------------------|
| `meander_amplitude` | 0.0 | **No** — `_water_network.py` does not read `intent.water_system_spec.meander_amplitude` |
| `bank_asymmetry` | 0.0 | **No** |
| `tidal_range` | 0.0 | **No** — coastline.py uses `composition_hints["tidal_range_m"]` instead, ignoring the typed field |
| `hero_waterfalls` | () | **No** — terrain_waterfalls.py never references the spec |
| `braided_channels` | False | **No** |
| `estuaries` | False | **No** |
| `karst_springs` | False | **No** — terrain_karst.py uses composition_hints instead |
| `perched_lakes` | False | **No** |
| `hot_springs` | False | **No** |
| `wetlands` | False | **No** |
| `seasonal_state` | "normal" | **No** — terrain_water_variants doesn't branch on it |

**The contract is a lie:** an agent setting `WaterSystemSpec(braided_channels=True, hot_springs=True, seasonal_state="flood")` gets identical output to `WaterSystemSpec()`.

### `TerrainIntentState.noise_profile`
- **Read site:** `_terrain_world.py:510, 861` — fed through `_terrain_type_from_intent()` which maps the string to a `terrain_type` enum (mountains/desert/coastal/cliffs/canyon/...). **Does change output.** OK.

### `TerrainIntentState.erosion_profile`
- **Read site:** `_terrain_world.py:1090` — only "temperate"/"arid"/"alpine" are handled; anything else falls back to "temperate" defaults silently.
- **Three string keys recognized.** Any other value is a silent fallback. `intent.erosion_profile = "tropical"` produces identical output to `"temperate"` with no warning. P1 silent-wrong.

### `TerrainIntentState.quality_profile`
- **Read site:** `terrain_budget_enforcer.py:191` only.
- Loads the profile, then maps **only** these into `TerrainBudget`: `triangle_budget`, `heightmap_resolution` (used to compute `max_npz_mb`), `splatmap_layer_count`, `max_tree_count`. Every other field on the profile object is ignored at runtime.
- **No pipeline pass calls `load_quality_profile()` to drive its own behavior.** See §"Quality Profile Delta Analysis" below.

### `TerrainIntentState.composition_hints`
- **Heavily read** (40+ sites). This is the *de facto* configuration channel — most actual user knobs live in this untyped dict, bypassing the typed contract. Validates the audit hypothesis that the typed fields are doc decoration while the real plumbing happens through stringly-typed dict lookups.

### `WaterSystemSpec.network_seed`
- **Used** by `environment.py:2995` in WaterNetwork construction. OK.

### `WaterSystemSpec.min_drainage_area / river_threshold / lake_min_area`
- **Used** by `environment.py:2992-2994` in WaterNetwork construction. OK.

---

## Dangerous Optional Fields (None-unsafe usage)

### `intent.scene_read: Optional[TerrainSceneRead] = None`
- **Production guard:** `terrain_pipeline.py:329` and `terrain_protocol.py:83` raise `ProtocolViolation` if None **only when** `require_rule_1=True`.
- **Unguarded deref:** `terrain_caves.py:3461` does `scene_read = state.intent.scene_read` then proceeds to use it without a None guard. Any caller that bypasses Rule 1 (e.g. tests with `@enforce_protocol(require_rule_1=False)`) will hit `AttributeError: 'NoneType' object has no attribute 'major_landforms'`.
- **Risk:** In the legitimate AAA headless path (no Blender viewport, no scene_read source) this is a footgun: the controller logs a warning and continues, but caves will crash.

### `intent.water_system_spec: Optional[WaterSystemSpec] = None`
- The `intent_hash()` method at `terrain_semantics.py:1316` does `vars(self.water_system_spec) if self.water_system_spec is not None else None` — guarded. OK.
- However, since no pass actually reads it, the None case is incidentally safe everywhere else: nothing dereferences a field that nothing reads.

### `intent.composition_hints: Dict[str, Any]` — frozen-dataclass + mutable-default smell
- `terrain_semantics.py:1296` carries a `# REVIEW-IGNORE PY-COR-17` tag claiming "frozen+mutable is safe here — callers treat as read-only".
- **Reality check:** test files write into the dict directly (`test_terrain_master_registrar.py:175`, `test_terrain_material_ceiling.py:495,507`, `test_terrain_materials_v2.py:381`, `test_terrain_deep_qa.py:199,208,235,283`). Production code in `terrain_review_ingest.py:133` does `hints = dict(intent.composition_hints)` then mutates the *local* copy — defensive — but `terrain_live_preview.py:281` also takes a copy. The "treat as read-only" claim is technically honored in handlers but blatantly violated in tests, which means a frozen invariant is being kept by social contract, not by enforcement.

### `intent.seed: int` (not Optional, but accepts pathological values)
- `int` annotation, no validator — `seed=-1`, `seed=0`, `seed=2**63` all accepted.
- `_terrain_world.py:577` falls back to `0` if `intent is None`. Headless paths that forget to set the intent quietly all share seed 0 — bit-exact between worlds.

---

## Quality Profile Delta Analysis (what actually differs between headless/preview/aaa)

`TerrainQualityProfile` declares **35 fields**. Each is set independently across the four built-in profiles — but only **8 fields** are *consumed* anywhere in production code.

### Fields with at least one runtime consumer

| Field | Consumer | Effect |
|-------|----------|--------|
| `triangle_budget` | `terrain_budget_enforcer.py:199` | LOD0/1/2 ceilings; **enforced as postcondition** (per E2) |
| `heightmap_resolution` | `terrain_budget_enforcer.py:204` | **Only** used to compute `max_npz_mb`. **Does NOT drive actual heightmap shape** — that comes from `intent.tile_size + 1`. |
| `max_tree_count` | `terrain_budget_enforcer.py:212` | Scatter cap; **enforced as postcondition** |
| `splatmap_layer_count` | `terrain_budget_enforcer.py:211` | Material limit; **enforced as postcondition** |
| `quality_profile` (string) | `_terrain_world.py:_terrain_type_from_intent` indirectly via `noise_profile` | Indirect at best |
| `lock_preset` | `terrain_quality_profiles.py:817` | Raises PresetLocked on load — never blocks generation |
| `name` | `terrain_quality_profiles.py` internal | Used for inheritance / aliasing |
| `extends` | `terrain_quality_profiles.py:809` | Inheritance graph traversal |

### Fields that are documentation-only (no runtime read found in any handler)

These are claimed as quality knobs but do not drive any pass:

- `erosion_iterations` — actual erosion counts are hardcoded inside `_terrain_world.py:1097-1100` (`{"temperate": 50_000, "arid": 40_000, "alpine": 60_000}`) keyed on **erosion_profile**, not quality_profile.
- `hydraulic_erosion_iterations` — declared 10 / 100 / 500 / 2000 across tiers; **zero consumers**. Headless and AAA both run the same 50k particles.
- `thermal_erosion_iterations` — zero consumers
- `talus_angle_degrees` — zero consumers (geological constant in actual erosion code)
- `erosion_rain_amount` — zero consumers
- `erosion_evaporation_rate` — zero consumers
- `erosion_strategy` (EXACT vs TILED_PADDED) — zero consumers (Addendum 3.B.1 strategy is named but no pass branches on it)
- `erosion_margin_cells` — zero consumers
- `cell_size_m` — collides with `intent.cell_size`; never read off the profile. The pipeline always uses `intent.cell_size`.
- `texture_resolution` — zero consumers (E2 already flagged this: not enforced)
- `normal_map_resolution` — zero consumers
- `roughness_variation_strength` — zero consumers
- `normal_smooth_iterations` — zero consumers
- `lod_count` — zero consumers — actual LOD count is derived analytically by `terrain_budget_enforcer._estimate_tri_count_per_lod`
- `lod_max_distance_m` — zero consumers
- `chunk_size_cells` — zero consumers
- `shadow_clipmap_resolution` — zero consumers
- `shadow_clipmap_bit_depth` — zero consumers
- `splatmap_bit_depth` — zero consumers
- `heightmap_bit_depth` — zero consumers (Unity export hardcodes uint16)
- `scatter_density_multiplier` — zero consumers
- `scatter_min_distance_m` — zero consumers
- `grass_density_multiplier` — zero consumers
- `river_min_flow_accumulation` — zero consumers (water_system_spec.river_threshold is consulted instead)
- `cave_min_volume_m3` — zero consumers
- `cliff_min_height_m` — zero consumers
- `waterfall_min_drop_m` — zero consumers
- `volumetric_fog_sample_count` — zero consumers
- `shadow_sample_count` — zero consumers
- `ambient_occlusion_radius_m` — zero consumers
- `corruption_spread_radius_m` — zero consumers
- `boneyard_density` — zero consumers
- `shrine_placement_attempts` — zero consumers
- `shadow_distance_m` — zero consumers (declared as direct UE5 cascade mapping; never wired)
- `streaming_radius_m` — zero consumers
- `checkpoint_retention` — zero consumers (terrain_checkpoints.py uses its own constant)
- `save_every_n_operations` — zero consumers in checkpoint code (BUG-R8-A9-031 wired the **inheritance merge** for it, but no pass actually checks the resolved value)
- `checkpoint_naming` — zero consumers (literal naming string never plugged into checkpoint_id formatter)

### Effective profile delta when switching mobile→aaa_open_world

After load_quality_profile() resolves to a final dict, the *only* observable behavioral differences are:

1. `triangle_budget` (100k → 4M) → enforces tri count
2. `max_tree_count` (50 → 10000) → enforces scatter count
3. `splatmap_layer_count` (4 → 4) → no diff in built-ins (always 4)
4. `heightmap_resolution` indirectly affects `max_npz_mb`
5. `lock_preset` and `name` (cosmetic)

**Everything else is documentation pretending to be configuration.**

This is a contract-vs-implementation gap. An agent submitting `quality_profile="aaa_open_world"` for hero shots gets the same erosion fidelity as `quality_profile="mobile"` because erosion iterations are not driven by the profile.

---

## Seed Propagation Gaps (which subsystems ignore intent.seed)

### Confirmed hardcoded seeds (D8 + new findings)

| File:line | Hardcoded seed | Effect |
|-----------|----------------|--------|
| `terrain_stratigraphy.py:420` | `default_rng(0)` | Bed sequence invariant across worlds |
| `terrain_stratigraphy.py:569` | `default_rng(1)` | Folding invariant |
| `terrain_stratigraphy.py:794` | `default_rng(42)` | Unconformity invariant |
| `terrain_palette_extract.py:106` | `default_rng(0)` | Color palette extraction invariant |

### Subsystems that DO consume `intent.seed`

`terrain_assets.py`, `terrain_banded.py`, `terrain_bundle_n.py`, `terrain_caves.py` (via `derive_pass_seed`), `terrain_cliffs.py`, `terrain_cloud_shadow.py`, `terrain_glacial.py`, `terrain_golden_snapshots.py`, `terrain_karst.py`, `terrain_materials_v2.py`, `terrain_multiscale_breakup.py`, `terrain_pipeline.py`, `terrain_stratigraphy.py:951` (one of three call sites uses real seed; the other three at :420/569/794 are hardcoded), `terrain_twelve_step.py`, `terrain_vegetation_depth.py`, `terrain_waterfalls.py`, `terrain_water_variants.py`, `terrain_wind_erosion.py`, `_terrain_world.py`.

### `_biome_grammar.py` — uses passed-in `seed` (not hardcoded), but caller chain not always verified to forward `intent.seed`.

### Risk summary

D8 already flagged `terrain_stratigraphy` (3 hardcoded seeds) and `terrain_palette_extract` (1 hardcoded seed). The **same world will always have:**
- Identical bed thicknesses across all worlds
- Identical fold orientations across all worlds
- Identical unconformity placements across all worlds
- Identical extracted color palette across all worlds

A user re-rolling seed=1 → seed=2 expecting different geology will see **only** the river / heightmap / cliff layout shift; the strata layering and color choices are bit-exact.

---

## Protocol Rules that Don't Actually Validate

### `rule_2_sync_to_user_viewport` — degraded to soft-warning
`terrain_protocol.py:135-141` — when `viewport_vantage is None` and `out_of_view_ok=False`, the gate **logs a warning and returns**. The docstring states "Future hardening: change the warning to a raise once all automated callers are confirmed to set out_of_view_ok=True" — meaning all current production callers fall through silently. The gate is non-binding.

### `rule_5_smallest_diff_per_iteration` — only fires if caller passes counts
`terrain_protocol.py:222-248` — gate consults `params["cells_affected"]` and `params["objects_affected"]`. **Default for both is 0**, so any pass that does not explicitly populate the params dict bypasses Rule 5 entirely. There is no introspection of the actual stack diff to compute affected cells; the rule trusts the caller to self-report.

### `rule_6_surface_vs_interior_classification` — only fires if `placements` populated
`terrain_protocol.py:256` — `placements = params.get("placements") or []` and bails if not a list. Most passes never set `params["placements"]`, so the gate is a no-op for the bulk of the pipeline.

### `rule_7_plugin_usage` — fires on production runs, but addon may be loose-versioned
`terrain_addon_health.assert_addon_version_matches` — depends on a Blender addon health check that returns true for any version ≥ `(1, 0, 0)`. Headless tests with no addon raise; production with any 1.x addon passes.

### Rules that ARE rigorously enforced
- Rule 1 (scene_read freshness) — hard raise
- Rule 3 (anchor drift) — hard raise
- Rule 4 (vertex-color-fake hero kinds) — hard raise

### Per E2 finding
The quality-profile postconditions are partially enforced. F3 confirms the *non-enforcement* set: `texture_resolution`, `heightmap_resolution` (as actual mesh shape, not just npz size), `hydraulic_erosion_iterations`, plus all 27 other profile fields listed above.

---

## Silent-Wrong Inputs (extreme/incorrect values that don't error)

| Input | What happens | Should happen |
|-------|--------------|---------------|
| `intent.seed = -1` | Forwarded to `default_rng(-1)` which masks to uint64; works but undocumented | Validate in __post_init__ |
| `intent.seed = None` (via type hole) | TypeError at first arithmetic XOR site (e.g. `int(seed) ^ 0xDEADBEEF`) | Should be impossible per type, but no explicit guard |
| `intent.tile_size = -100` | Frozen dataclass accepts. Mask stack post-init only fires if `tile_size > 0` (line 696). Negative → all tile-size guards skip → downstream shape errors deep in pipeline | Validate `tile_size > 0` in TerrainIntentState.__post_init__ |
| `intent.tile_size = 0` | Mask stack treats as "non-tile" (allowed by design); but pipeline that derives `region_bounds.width / tile_size` divides by zero | Validate against region_bounds |
| `intent.cell_size = 0.0` | All world-space distance computations collapse; `WorldHeightTransform` has its own `1e-10` guard but `intent.cell_size` itself isn't guarded | Validate `cell_size > 0` |
| `intent.cell_size = -1.0` | Negative cell sizes → mirrored coordinates → silently wrong placements | Validate positive |
| `intent.region_bounds` doesn't match `tile_size * cell_size` | Accepted; downstream tile-coords-vs-world-coords may diverge | Validate consistency |
| `intent.erosion_profile = "tropical"` | Falls back to "temperate" silently | Validate against known set |
| `intent.noise_profile = "atlantis"` | Falls back to "mountains" silently | Validate against known set |
| `intent.quality_profile = "ultra"` | `load_quality_profile` raises KeyError, but `terrain_budget_enforcer.resolve_budget` swallows the exception (line 196 `except Exception: return TerrainBudget()`) and returns defaults — caller never learns the profile was invalid | Don't swallow; let KeyError propagate |
| `WaterSystemSpec.tidal_range = -5.0` | Silently zeroes out tidal mask (ignored anyway) | N/A — field is dead |
| `quality_profile.hydraulic_erosion_iterations = 0` | No effect (field unused) | Wire to actual erosion |

---

## Top-Priority Fixes

Ranked by AAA-shipping impact for VeilBreakers:

### P0-F3-1: Wire quality_profile to actual erosion settings
**File:** `_terrain_world.py:1090-1100` and `terrain_budget_enforcer.py`
**Action:** Replace the hardcoded `{"temperate": 50_000, ...}` map with `profile.hydraulic_erosion_iterations` look-ups. Today an AAA hero shot gets identical erosion fidelity to a mobile preview.
**Test gate:** Determinism harness should show different content_hash between `quality_profile="mobile"` and `quality_profile="aaa_open_world"` runs.

### P0-F3-2: Wire WaterSystemSpec to actual water passes
**File:** `_water_network.py`, `terrain_waterfalls.py`, `terrain_water_variants.py`, `coastline.py`
**Action:** Read `state.intent.water_system_spec.{meander_amplitude, bank_asymmetry, tidal_range, braided_channels, estuaries, hot_springs, seasonal_state}`. Today setting `seasonal_state="flood"` on a winter-themed VeilBreakers map produces identical water height to "normal".
**Migration:** Coastline and karst currently pull from `composition_hints`; consolidate to the typed field, deprecate the dict path.

### P0-F3-3: Either delete `morphology_templates`/`biome_rules` or wire them
**File:** `terrain_semantics.py:1289,1293`
**Action:** Both fields are pure decoration. Either:
  (a) Remove from dataclass and update intent_hash + checkpoint serialization, OR
  (b) Wire `biome_rules` into `_biome_grammar.py` (already flagged in G1 audit), and wire `morphology_templates` into `_terrain_world` template selection.

### P0-F3-4: Replace 4 hardcoded seeds with `intent.seed` derivation
**Files:**
- `terrain_stratigraphy.py:420` (`default_rng(0)`)
- `terrain_stratigraphy.py:569` (`default_rng(1)`)
- `terrain_stratigraphy.py:794` (`default_rng(42)`)
- `terrain_palette_extract.py:106` (`default_rng(0)`)

**Action:** Replace with `derive_pass_seed(intent.seed, "stratigraphy_beds", tile_x, tile_y)` etc. Re-confirms D8.

### P1-F3-5: Add TerrainIntentState.__post_init__ validation
**File:** `terrain_semantics.py:1275-1296`
**Action:**
```python
def __post_init__(self) -> None:
    if not isinstance(self.seed, int):
        raise TypeError("seed must be int")
    if self.tile_size <= 0:
        raise ValueError(f"tile_size must be > 0, got {self.tile_size}")
    if self.cell_size <= 0.0:
        raise ValueError(f"cell_size must be > 0, got {self.cell_size}")
    if self.noise_profile not in _VALID_NOISE_PROFILES:
        raise ValueError(...)
    if self.erosion_profile not in {"temperate", "arid", "alpine"}:
        raise ValueError(...)
    expected_w = self.tile_size * self.cell_size
    if not math.isclose(self.region_bounds.width, expected_w, rel_tol=1e-3):
        raise ValueError(f"region_bounds width {self.region_bounds.width} ≠ tile_size*cell_size {expected_w}")
```

### P1-F3-6: Stop swallowing load_quality_profile exceptions in budget enforcer
**File:** `terrain_budget_enforcer.py:196`
**Action:** Replace `except Exception: return TerrainBudget()` with explicit `except KeyError as e: raise ValueError(f"Unknown quality_profile: {self.intent.quality_profile!r}") from e`. Today a typo silently downgrades the world to defaults.

### P1-F3-7: Promote rule_2 from warning to raise
**File:** `terrain_protocol.py:135-141`
**Action:** All headless callers should set `out_of_view_ok=True`. Audit current call sites, fix any that pass nothing, then change the warning to a `ProtocolViolation` raise.

### P2-F3-8: Cull dead profile fields or wire each
**File:** `terrain_quality_profiles.py:97-294`
**Action:** Either:
  (a) Remove the 27 unused fields from `TerrainQualityProfile`, OR
  (b) Add explicit consumers for each in the relevant pass (preferred: at least the dark-fantasy specifics like `corruption_spread_radius_m`, `boneyard_density`, `shrine_placement_attempts` should drive the corruption / undead generators if any exist).

### P2-F3-9: Fix `composition_hints` mutability footgun
**File:** `terrain_semantics.py:1296`
**Action:** Either use `MappingProxyType(dict)` to make it truly immutable in the frozen dataclass, or convert to a typed sub-dataclass with explicit fields for the keys actually consumed (`vantages`, `framing_clearance_m`, `wave_dir`, `tidal_range_m`, `latitude_deg`, `lithology`, `focal_points`, `flatten_zones`, `canyon_paths`, `river_carves`, `cultivated_zones`, `cave_framing_required`, `quixel_assets`, `material_height_blend_gamma`, `review_blockers`, `review_suggestions`, `bundle_n_runtime`, `boss_arena_bbox`, `unity_export_opt_out`).

### P3-F3-10: Document or delete frozen+mutable composition_hints REVIEW-IGNORE tag
**File:** `terrain_semantics.py:1296`
**Action:** The `# REVIEW-IGNORE PY-COR-17` annotation claims callers treat the dict as read-only, but tests demonstrably mutate it. Either honor the contract by making the field immutable, or remove the IGNORE tag and acknowledge it is a mutable handle.

---

## Cross-references
- D8 (determinism audit) — confirms hardcoded seed findings (P0-F3-4)
- E2 (guardrail effectiveness) — confirms profile postconditions partially enforced
- G1 (wiring disconnections) — flagged biome_rules at :572
- A2 (water systems) — independent F0+ grade despite WaterSystemSpec being a paper contract; the actual water shape comes from heightmap + WaterNetwork.from_heightmap params, bypassing the typed spec entirely
