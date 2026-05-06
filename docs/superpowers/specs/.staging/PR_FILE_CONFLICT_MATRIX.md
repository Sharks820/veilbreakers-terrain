# Cross-PR File-Edit Conflict Matrix

**Generated**: 2026-05-06
**Source spec**: `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md` §11 v3 (lines 1609–2179)
**Branch evaluated against**: `main` @ `3cc63c5` (Harden AAA terrain audit gates and golden semantics)
**PRs analyzed**: 88 (Block 1: 15 / Block 2: 22 / Block 3: 11 / Block 4: 14 / Block 5: 26 line items, 25 PR groups)
**Files with multi-PR ownership**: 11
**Ordering hazards**: 7 (P0/P1)
**Stale-cite hazards (refactor invalidates surgical)**: 5
**Bad-cite line-number drift hazards (spec cite ≠ `main` reality)**: 22
**Missing dep edges in §11.6**: 14

> **Critical context**: spec uses repo-relative paths like `handlers/terrain_advanced.py` but the file actually lives at `veilbreakers_terrain/handlers/terrain_advanced.py` on `main`. All "verified" line cites are checked against the latter. The spec's drafting was presumably done against the in-flight branch `docs/biome-render-rebuild-spec` (HEAD `481b7a1`), which contains uncommitted speculative refactors (e.g., the duplicated `derive_pass_seed` in `terrain_rng.py`) that do NOT exist on `main`. The implementation team will branch from `main` and these line numbers will be off by 30–250 lines for many surgical PRs.

---

## 1. Files with multi-PR ownership

### 1.1 `veilbreakers_terrain/handlers/terrain_unity_export.py` (2847 LOC on main)

**Touched by**: 8 PRs (single hottest file in the runway)

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #5b  | edit (consumer migrate) | `:2270-2278` | manifest writer at 2248/2272; `unity_import_descriptor` at 2266 | water-channel migration |
| #12  | edit (atomic write) | `:2484-2510` "real `json.dumps(manifest)` site" | actually 2248 + 2272 | **spec cite ~250 lines off** |
| #13  | edit (NaN/Inf sanitize) | "various pack-points" | unspecified | depends on #12 |
| #20  | edit (`_compat` shim) | "deprecation notices" | unspecified | depends on #5b |
| #44  | edit (streaming budget cap) | `unity_export_v2/chunk_artifacts.py` | `unity_export_v2/` does NOT exist on main | **NEW directory; not a `terrain_unity_export.py` edit** — V4 referee correct |
| #48  | edit (consolidate metadata) | `:2484-2510` neighborhood + 25-field metadata | metadata block lives near 2266; `tile_metadata_asset_path` at 1535 | reordering only |
| #B5-C2 | meta (serialize edits) | dep ordering | n/a | enforces serialization |
| #B5-U4 | edit (tangent normal G-flip) | `:334` `_pack_tangent_space_normal_rgba` | actual line 288 | **spec cite ~46 lines off** |

**Spec-stated order** (per B5-C2): `#11 → #12 → #44 → #5b → #48`.

**Issue**:
- B5-C2 lists **#11** as touching this file. PR #11 is path-injection in `providers/meshy_provider.py`, `providers/hunyuan3d2_provider.py`, `handlers/asset_generation.py:699,706`. **#11 does NOT touch `terrain_unity_export.py`.**
- B5-C2 lists **#44**. PR #44 creates `unity_export_v2/chunk_artifacts.py` (NEW directory). It does NOT edit `terrain_unity_export.py` either.
- The real list of PRs that mutate `terrain_unity_export.py` is: **#5b, #12, #13, #20, #48, B5-U4**. Add #B5-C2 as the serialization meta-PR.

**Corrected B5-C2 cite**: `#5b → #12 → #13 → #20 → #48 → B5-U4` (6 PRs in dep order).

**Required dep edges** (currently missing in §11.6):
- `#13 → #12` ✅ already declared
- `#20 → #5b` ✅ already declared
- `#48 → #12, #44, #5b` ✅ already declared
- `#48 → #20` ✗ **MISSING** (since both edit `terrain_unity_export.py` and #20 introduces `_compat.py` deprecations that #48 may rely on)
- `B5-U4 → #5b, #48` ✗ **MISSING** (B5-U4 has zero deps in §11.5.1)

---

### 1.2 `veilbreakers_terrain/handlers/environment.py` (8613 LOC on main)

**Touched by**: 6 PRs (the second hottest file; XL refactor #53 splits it into 5)

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #23  | edit (DAG-escape `road_mask` closure) | `:6265-6266` "Blender-only legacy closure" | NO `road_mask` write at 6265-6266; `road_mask` is at 4630-4689 (`_build_road_mask_and_sdf`) | **spec cite ~1600 lines off**; possibly file refers to a different module entirely |
| #25  | edit (biome archetype cite correction) | `:2031` `params.get("terrain_type", "mountains")` | NOT at 2031; actual lines are **1205, 2020, 2322, 2990, 3043** | **spec cite is itself wrong** (claims to FIX a wrong cite, but new cite is also wrong by ~10-1000 lines) |
| #45  | edit (`pass_hydrology` insert) | `:2861` `requested_passes[3:3] = ["pass_hydrology", "erosion"]` | actually at line **2844** | **spec cite ~17 lines off** |
| #49  | edit (4-symbol shim caller) | `environment.py:229` (procedural_meshes shim) | not directly cited; dependent on #49 import | passive |
| #53  | rename/refactor (XL split at 5 seams) | "all 5 cited line numbers (1211, 2031, 2339, 2861, 3007, 3060) re-anchored" | the spec internally lists 6 numbers (1211, 2031, 2339, 2861, 3007, 3060); `main` actual is closer to **1205, 2020, 2322, 2844, 2990, 3043** | XL refactor; landing this BEFORE #23/#25/#45 means all surgical line cites become stale |
| caller-only refs (sister callsites in #25's note) | edit | flagged at lines 1211, 2339, 3007, 3060 | actual `terrain_type` defaults at 1205, 2322, 2990, 3043 | **5/5 sister callsite cites are off by 4-17 lines** |

**Spec-stated order**: §11.6 places #23, #25, #45 inside Block 2/3 (parallel after #3, #4); #53 is a Block-4 XL refactor; #49 is Block-4 scope-relocation.

**Issue (P0 — STALE CITE HAZARD)**:
- PR #53 splits `environment.py` (8613 LOC) into 5 files. If #53 lands first OR runs in parallel with #23/#25/#45, **all surgical line cites in #23/#25/#45 evaporate** because the file no longer exists at the cited path; the targets move into one of `terrain_env_terrain.py`, `terrain_env_water.py`, `terrain_env_roads.py`, `terrain_env_export.py`, or `terrain_env_validation.py` (per §11.4 PR #53 row).

**Required dep edges** (currently missing in §11.6):
- `#53 → #23, #25, #45, #49` ✗ **MISSING** — §11.6 graph does not declare these. **Recommendation**: either `#53 → {#23, #25, #45, #49}` (refactor goes LAST), OR move #53 to v1.1.

**Compounding issue**: PR #25 is presented as a "cite correction" PR but its own corrected cite (`:2031`) is itself wrong on `main`. The biome collapse is at line 1205 (the first occurrence) and 4 sister callsites at 2020/2322/2990/3043. Whoever implements PR #25 must re-discover the actual lines.

---

### 1.3 `veilbreakers_terrain/handlers/terrain_pipeline.py` (1675 LOC on main)

**Touched by**: 11 PRs (the third hottest file; orchestrator)

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #3   | edit (toposort overrides) | `:1449-1510` | `_toposort_passes` at line **1369** | **spec cite ~80 lines off** |
| #4   | edit (wire orphan passes + carry C-1) | `:169-261` | `build_default_pass_sequence` at line **118**; pass list at 155-175 | **spec cite ~50 lines off** |
| #8   | edit (deepcopy → COW) | `:940,956` | actual `copy.deepcopy(self.state.mask_stack)` at line **861**; `bundle_n_pre_pipeline_state` at 877; checkpoint deepcopy at 968 | **spec cite ~80 lines off** |
| #14  | edit (canonical `derive_pass_seed`) | `:269` (KEEP) | actually at line **208** | **spec cite ~60 lines off**; KEEP target verified to exist |
| #29  | edit (label-stamping validator/clamp) | `:1133-1191` `pass_compute_terrain_labels` | **NOT** at 1133; that range is `pass_compute_biome_channels`. Actual `pass_compute_terrain_labels` def at line **1054**, registration at 1120 | **spec cite ~80 lines off** + **conflates two different passes** |
| #35  | edit (`bundle_n` exception → hard fail) | `:992-999` | actual `bundle_n_post_pipeline_hooks` `except Exception:` swallow at line **906-918** | **spec cite ~80 lines off** |
| #46  | edit (Rule-1 gate restored) | `_rule1_gate.py` (NEW) | not on main (NEW file) | new module |
| #51  | edit (extract `terrain_core.py`) | "PassDefinition + derive_pass_seed re-export" | depends on #14 canonical | refactor |
| #62  | edit (W-1 close) | `:1355-1421` `pass_water_depth` | actual `pass_water_depth` def at line **1275-1330** | **spec cite ~80 lines off** |
| #36 (note) | line-cite note in #36 row | references `terrain_asset_budget.py` | **DOES NOT EXIST on main** — feasibility reviewer correct | spec cites file that's not in repo |
| (orphan registrations) | indirect | various | n/a | several PRs touch `register_*` calls in this file |

**Spec-stated order**: #1 → #2 → #3 → #4 → (Block 2 parallel #8, #29, #35; Block 3 parallel #46, #62; Block 4 #51).

**Issue (P0 — CO-EDIT COLLISION)**: 11 PRs all mutate the same orchestrator file. Spec does NOT define a serialization rule for `terrain_pipeline.py` (only for `terrain_unity_export.py` per B5-C2). Concurrent agents working on Block 2 #8/#29/#35 (which depend only on Block 1 #3 or #4) **WILL** collide on this file.

**Required dep edges** (currently missing in §11.6):
- `terrain_pipeline.py` serialization meta-PR ✗ **MISSING** — recommend a parallel "B5-C2-bis" that serializes `terrain_pipeline.py` writer-edits.

**Compounding issue**: PR #29 cites `terrain_pipeline.py:1133-1191` as `pass_compute_terrain_labels`. That range on `main` is in fact `pass_compute_biome_channels` (a completely different pass). The actual `pass_compute_terrain_labels` is at 1054. Implementing PR #29 against the spec cite would either no-op or, worse, modify the wrong pass.

---

### 1.4 `veilbreakers_terrain/handlers/terrain_water_variants.py` (~960 LOC on main)

**Touched by**: 4 PRs

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #5a  | edit (drop legacy writes) | `:781,878` | line **786** has `water_surface[lr,lc] = ...`; line **766** has `stack.set("water_surface", ...)`; line **836** has `water_surface[br,bc] = ...` | **spec cite ~5-15 lines off**; partial match only |
| #5b  | edit (canonical channels register) | (whole file) | new `set("water_surface_mask", ...)` already partially present at lines **691, 864** | **w-1 ALREADY partially landed** (per memory: W-1 ✅ FIXED) |
| #29  | edit (water_label stamping ref) | "stamps `water_label`" | n/a (new code) | depends on #5b |
| #37  | edit (water_label = water_surface_mask) | "reads `water_surface_mask` from PR #5b" | depends on #5b channel registration | binary copy |

**Issue**: PR #5a's "drop legacy writes" cite at `:781` and `:878` are off by 5-15 lines on `main`. More importantly, the `water_surface_mask` channel is already partially set in production code (lines 691, 864). PR #5b's "register canonical W-1 channels" should be a verification + cleanup, not a from-scratch implementation.

**Required dep edges**:
- `#37 → #29` ✗ **MISSING in §11.6** — #37 stamps `water_label`, but #29 is the stamping architecture PR. §11.6 declares `#37 → #5b, #29` in the table but the graph drawing doesn't.

---

### 1.5 `veilbreakers_terrain/handlers/terrain_cliffs.py` (2820 LOC on main)

**Touched by**: 2 PRs (#15, #24)

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #15  | edit (`hash(cliff.cliff_id)`) | `:2397` | actual at line **2368** (`mesh_seed = hash(cliff.cliff_id) & 0x7FFFFFFF`) | **spec cite ~30 lines off**; hash hazard verified to exist |
| #24  | edit (overhang threshold configurable) | `:890` (allegedly `radians(88.0)`) | actual at line **857** (`overhang_threshold_rad = math.radians(88.0)`) | **spec cite ~33 lines off** — and §11 v3 even acknowledges "v3 forensic confirms cite `857-858` is WRONG" then provides the WRONG correction (890); the truly correct cite IS 857 |

**Issue (CRITICAL)**: PR #24's spec row contains a **self-contradicting** cite correction. v3 says "do NOT use comments-only 60° / 80° (V3 forensic confirms cite `857-858` is WRONG)". But on `main` the actual `radians(88.0)` IS at line 857. Whoever drafted §11 v3 conflated two findings. The implementer of #24 must use line 857, not 890.

Also: bare `hash(...)` patterns at lines 83, 619, 622, 916, 936 on `main` use `& 0x7FFFFFFF` BUT they are not `hash(cliff.cliff_id)` — they're `hash(rng_seed * ...)` or `hash(layer_seed ^ ...)`. PR #15 should sweep all of these, but only the #15 row mentions one.

---

### 1.6 `veilbreakers_terrain/handlers/_water_network.py` (1135 LOC on main)

**Touched by**: 1 PR (#19) — listed for completeness

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #19  | perf (Numba/Taichi-jit) | `:580-664` `priority_flood_d8` + `_erode` | actual `priority_flood_d8` def at line **515** | **spec cite ~65 lines off** |

---

### 1.7 `veilbreakers_terrain/handlers/_terrain_erosion.py` (1135 LOC on main)

**Touched by**: 1 PR (#19) — paired with above

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #19  | perf (Taichi kernel rewrite) | `:308-487` (`_erode` loop) | actual particle loop at lines **341-460**+; `_erode_brush` def at 656 | **spec cite ~30 lines off** |

---

### 1.8 `veilbreakers_terrain/handlers/vegetation_system.py` (1849 LOC on main; deleted by #55)

**Touched by**: 3 PRs (#43, #56, #B5-A4) PLUS deletion #55

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #43  | fix (lod_meshes validator) | `:1284` | line **1284** is `terrain_vertices` block in spec_only mode; `"lod_meshes": []` actually at line **685**; `entry.setdefault("lod_meshes", [])` at line **1600** | **spec cite ~600+ lines off** |
| #56  | fix (defaults BEFORE delete) | `:1284, 1534` | same — line 1284 is unrelated; line 1534 is mostly metadata writers | **spec cite ~500-600 lines off** |
| #55  | DELETE | (locked-list) | currently 1849 LOC | hard delete — order critical |
| #B5-A4 | gate (manifest emission) | `:1284` (mirror of #43) | same wrong cite | **spec cite ~600 lines off** |

**Issue (P0 — DELETE-BEFORE-EDIT)**: PRs #43, #56, #B5-A4 all edit `vegetation_system.py:1284`. PR #55 DELETES the file entirely. §11.6 declares `#56 → #55` (defaults fix BEFORE delete) ✅. But:
- §11.6 does NOT declare `#43 → #55` ✗ **MISSING** — if #55 lands before #43, #43 has no file to edit.
- §11.6 does NOT declare `#B5-A4 → #55` ✗ **MISSING** — same hazard.

PR #55's row says "Run AFTER #56 (vegetation_system defaults fix) to break #55 ↔ #56 cycle". But #55 must also land AFTER #43 and #B5-A4, OR #55's locked-list must EXCLUDE `vegetation_system.py` from the delete. Currently neither condition is enforced in the spec text.

**Required dep edges**:
- `#43 → #55` ✗ **MISSING**
- `#B5-A4 → #55` ✗ **MISSING**
- Alternative: `#55` removes `vegetation_system.py` from delete list (§11.5.2 PR B5-C3 hints at this but doesn't enforce).

---

### 1.9 `veilbreakers_terrain/handlers/asset_generation.py` (802 LOC on main; deleted by #55)

**Touched by**: 1 PR (#11) edits PLUS deletion #55

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #11  | sec (path-injection) | `:699,706` | actual `out_path = out_dir / f"{request.output_name}.glb"` at **697**; sidecar at **702** | **spec cite ~3-4 lines off** (close) |
| #55  | DELETE | "asset_generation.py (after replace 1 import)" | exists | order critical |

**Issue (P0 — DELETE-BEFORE-EDIT)**: PR #11 sanitizes `species_id` in `asset_generation.py` paths. PR #55 deletes the file. §11.6 graph drawing does NOT declare `#11 → #55` and the §11.6 dep table for #55 lists deps as `#5b, #2, #56` — **missing #11**.

**Required dep edges**:
- `#11 → #55` ✗ **MISSING** — if #55 deletes before #11 lands, the path-injection sanitization in `asset_generation.py` evaporates. PR #55 row claims "(after replace 1 import)" which suggests this is anticipated, but the dep is not in §11.6.

---

### 1.10 `veilbreakers_terrain/handlers/terrain_macro_color.py` (~270 LOC on main)

**Touched by**: 2 PRs (#31, #32)

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #31  | fix (consumed_channels=8) | `:230` | actual `consumed_channels=("height",)` at line **230** ✅ | spec cite verified |
| #32  | fix (DARK_FANTASY_PALETTE 8→14 entries) | `:28-37` | actual palette block at lines **26-37** | **spec cite ~2 lines off** (close) |

**Issue**: §11.6 declares `#32 → #31` ✅ (palette must extend AFTER consumed_channels expansion). But the actual writes are non-overlapping (palette dict vs registration metadata), so the dep is documentation-only.

---

### 1.11 `veilbreakers_terrain/handlers/terrain_morphology.py`

**Touched by**: 2 PRs (#17, #29)

| PR # | Edit type | Spec cite | Reality on `main` | Notes |
|------|-----------|-----------|-------------------|-------|
| #17  | fix (apply morphology_delta to height) | `:459-465` | actual `stack.set("morphology_delta", ...)` at line **458**; `pass_name="pass_morphology"` at **460** | **spec cite ~1 line off** (very close) |
| #29  | edit (gravel_label stamping) | "terrain_morphology.py stamps gravel_label" | new code addition | depends on #17 (delta applied first) |

**Required dep edges**:
- `#29 → #17` ✅ already declared

---

## 2. Ordering failures (P0/P1)

### 2.1 Cycle: PR #18 ↔ B5-D1 (P0)

**Status**: **CONFIRMED**, partially worked-around, dep declaration insufficient.

§11.6 declares: `B5-D1 → #18` (`B5-D1` is a DEP of #18 → wait, the ARROW direction is B5-D1 depends on #18, since `B5-D1` row in §11.5.3 lists `Deps: #18`). And §11.5 PR #18 row lists `Deps: #14, #15` — **does NOT list B5-D1**, but the ACCEPTANCE criterion of #18 requires "Each migrated site tagged with scope (`biome_seed` for pre-slice, `chunk_seed` for post-slice) per C-1" — and `chunk_seed`/`biome_seed` are CONCRETE FUNCTIONS that LIVE IN `chunks/chunk_seed.py` (defined by B5-D1).

**Cycle**: #18 acceptance USES `chunk_seed/biome_seed`; B5-D1 DEPS-ON #18.

**§11.0.2 work-around**: Spec amends with "two-tier seed model amended by PR #4 (carry-amendment) + PR #36 (chunk_seed module)". But PR #36 row in §11.2 says `feat(asset-budget): split splatmap_layer_count 4→8` — has nothing to do with `chunk_seed` module. The §11.0.2 reference to "PR #36" is **a typo/conflation**; the chunk_seed module is actually PR **B5-D1** per §11.5.3. So §11.0.2 inadvertently asserts the cycle workaround through a phantom-PR.

**Recommended fix**:
- Reverse the dep: `B5-D1 → #14, #15` (chunk_seed module depends on canonical seed primitives), then `#18 → B5-D1` (RNG migration USES chunk_seed). Removes the cycle.
- Update §11.0.2 to cite "B5-D1 (chunk_seed module)" not "PR #36".
- Update PR B5-C4 (which is the C-1 propagation patch) row dep to `B5-D1` instead of just `#18`.

### 2.2 Stale-cite hazard: PR #53 invalidates #23/#25/#45 line cites (P0)

PR #53 splits `environment.py` (8613 LOC) at 5 seams. The §11.6 graph places #53 in Block 4 (parallel to Block 1-3 work) with no explicit deps on the surgical edits in #23/#25/#45 (which all mutate `environment.py:specific-line`).

If #53 lands first, the surgical line cites in #23/#25/#45 reference a FILE THAT NO LONGER EXISTS at those paths. Implementers attempting #23/#25/#45 against a #53-merged tree must re-find the targets in one of: `terrain_env_terrain.py`, `terrain_env_water.py`, `terrain_env_roads.py`, `terrain_env_export.py`, `terrain_env_validation.py`.

**Compounding**: even on `main` BEFORE #53, the spec line cites for #23/#25/#45 are off by 17-1600 lines. Whoever implements them must re-find anyway.

**Recommended fix**:
- Add `#53 → #23, #25, #45, #49` to §11.6 graph (#53 is a dep of all surgical edits — i.e., they must land FIRST).
- OR move #53 to v1.1 (per §11.4 row "may slip to v1.1 if Block 4 calendar is tight").

### 2.3 Stale-cite hazard: PR #54 invalidates `terrain_features.py` cites (P1)

PR #54 splits `terrain_features.py` at 9 `generate_*` seams. §11 v3 references this file in #29 row (`terrain_features.py stamps rock_label`). After #54, those references need re-anchoring.

**Recommended fix**:
- Add `#54 → #29` ✗ **MISSING**.

### 2.4 Stale-cite hazard: PR #52 invalidates `terrain_semantics.py` consumers (P1)

PR #52 splits `terrain_semantics.py` (82 importers) into `_types.py` + `_semantics.py`. Many other PRs reference `from .terrain_semantics import PassResult, PassDefinition`. If #52 lands first, all those imports require update.

**§11.6 status**: `#52` listed but no inbound arrows. **MISSING**: deps to all 16+ pass-contract-edit PRs (#21, #16, #17, #29, #37, #45, #62, etc.).

**Recommended fix**:
- Add `#52 → {#16, #17, #21, #29, #37, #45, #62}` ✗ **MISSING** — OR document that #52 is API-preserving (re-exports from old location). Spec doesn't say which.

### 2.5 Delete-before-edit: PR #55 deletes `asset_generation.py`; PR #11 edits `:699,706` (P0)

**See §1.9 above**. §11.6 missing edge `#11 → #55`. Current §11.6 dep table for #55 lists `#5b, #2, #56` — does not include `#11`. The PR #55 row body text `(after replace 1 import)` hints at awareness but doesn't formalize.

### 2.6 Delete-before-edit: PR #55 deletes `vegetation_system.py`; PRs #43, #B5-A4, #56 edit `:1284` (P0)

**See §1.8 above**. §11.6 declares `#55 → #56` (correct ordering: #56 fixes defaults BEFORE #55 deletes). Missing edges:
- `#43 → #55` ✗ **MISSING**
- `#B5-A4 → #55` ✗ **MISSING**

The spec admits this awareness in §11.5.2 PR B5-C3 ("break #56 ↔ #55 cycle") but the resolution mentions only `#56`/`#55`. PR #43 and B5-A4 are not part of the cycle resolution.

**Recommended fix**: Either remove `vegetation_system.py` from #55's locked-list (it's already an awkward delete since the file is 1849 LOC of active code), OR add `#43, #B5-A4 → #55`.

### 2.7 Co-edit collision: 11 PRs all edit `terrain_pipeline.py` (P1)

**See §1.3 above**. §11.6 has no `terrain_pipeline.py` serialization rule (unlike `terrain_unity_export.py` which has B5-C2). Block 2 #8/#29/#35 + Block 3 #46/#62 + Block 4 #51 are spec'd as parallel-eligible but all touch this file.

**Recommended fix**: add a new B5-C2-bis serialization PR for `terrain_pipeline.py` writer-edits, OR explicitly serialize the inner-block edits.

---

## 3. Bad-cite line-number drift hazards

These are cite errors where the spec's stated `file:line` differs from `main` reality by ≥5 lines. Implementing the PR against the spec cite would either no-op or modify the wrong code.

| PR | Spec cite | `main` reality | Drift | Severity |
|----|-----------|----------------|-------|----------|
| #3 | `terrain_pipeline.py:1449-1510` | line **1369** | -80 | P1 |
| #4 | `terrain_pipeline.py:169-261` | line **118** | -50 | P1 |
| #6 | `terrain_advanced.py:2652` | line 2652 ✅ | 0 | OK |
| #7 | `terrain_chunking.py:100` | line 100 ✅ | 0 | OK |
| #8 | `terrain_pipeline.py:940,956` | line **861** | -80 | P1 |
| #9 | `road_network.py:1808-1817` | file is 1775 LOC; **OUT OF FILE** | n/a | P0 |
| #10 | `terrain_shadow_clipmap_bake.py:317-322` | ~317-322 ✅ | ~0 | OK |
| #11 | `asset_generation.py:699,706` | line **697, 702** | -3,-4 | OK |
| #11 | `meshy_provider.py:216` | line 216 ✅ | 0 | OK |
| #12 | `terrain_unity_export.py:2484-2510` | actual `json.dumps(manifest)` at lines **2248, 2272** | -240 | P0 |
| #14 | `terrain_rng.py:45` (alternate to delete) | **DOES NOT EXIST on main** (file is 43 lines, no `def derive_pass_seed` there) | n/a | P0 |
| #14 | `terrain_pipeline.py:269` (canonical to keep) | actual at line **208** | -61 | P1 |
| #15 | `terrain_cliffs.py:2397` | actual `hash(cliff.cliff_id)` at line **2368** | -29 | P1 |
| #16 | `terrain_master_registrar.py` | `register_stratigraphy_pass` and `wind_erosion` NOT FOUND on main | n/a | P0 |
| #17 | `terrain_morphology.py:459-465` | line **458-460** | -1 | OK |
| #19 | `_water_network.py:580-664` | `priority_flood_d8` at line **515** | -65 | P1 |
| #19 | `_terrain_erosion.py:308-487` | particle loop at **341+** | -33 | P1 |
| #23 | `environment.py:6265-6266` (road_mask DAG-escape) | road_mask at lines **4630-4689** (`_build_road_mask_and_sdf`) | -1600+ | P0 |
| #24 | `terrain_cliffs.py:890` (allegedly `radians(88.0)`) | actual at line **857**; spec self-contradicts ("857-858 is WRONG") | -33 | P0 |
| #25 | `environment.py:2031` (`params.get("terrain_type", "mountains")`) | actual at lines **1205, 2020, 2322, 2990, 3043** — 2031 is unrelated `terrain_type = validated["terrain_type"]` | -10 to +1000 | P0 |
| #29 | `terrain_pipeline.py:1133-1191` (`pass_compute_terrain_labels`) | range 1133-1191 is `pass_compute_biome_channels`. Actual `pass_compute_terrain_labels` at **1054-1120** | -80 + WRONG-PASS | P0 |
| #30 | `terrain_waterfalls.py:115` | line 115 ✅ (`prox_ratio = 1.0 - saturate(...)` and `speed_ratio = 1.0 - flow_speed/...`) | 0 | OK |
| #31 | `terrain_macro_color.py:230` | line 230 ✅ (`consumed_channels=("height",)`) | 0 | OK |
| #32 | `terrain_macro_color.py:28-37` | actual palette at **26-37** | -2 | OK |
| #33 | spec body `terrain_audio_zones.py` 1049 LOC | actual **1028 LOC** | -21 | P2 (spec body fact wrong; both v2's "989" and v3's "1049" are wrong) |
| #33 | Sabine cites `:539, :554` (cave/2s, open-field/0.1-0.3s) | Sabine references at lines **12, 73, 79, 115, 181, 252-254** — 539/554 nowhere near | -480 | P0 |
| #34 | `terrain_checkpoints.py:97-102` | `_LABEL_REGISTRY` at line **49**; `_AUTOSAVE_CONTROLLERS` at **52**; `_ORIGINAL_RUN_PASS` at **54** | -50 | P1 |
| #35 | `terrain_pipeline.py:992-999` | `bundle_n_post_pipeline_hooks` swallow at **906-918** | -85 | P1 |
| #36 | `terrain_quality_profiles.py:183/353/409/465/521` | actual at **182/352/408/464/520** | -1 each | OK |
| #36 | `terrain_asset_budget.py` cited | **DOES NOT EXIST on main** | n/a | P0 |
| #36 | `build_terrain_aaa_node_v6.py:597-605` | not verified | unknown | P2 |
| #43 | `vegetation_system.py:1284, procedural_grass.py:720` | `lod_meshes` actually at **vegetation_system.py:685, 1561, 1600** and **procedural_grass.py: NOT FOUND** | -600 / not present | P0 |
| #45 | `environment.py:2861` (`requested_passes[3:3] = ["pass_hydrology", "erosion"]`) | actual at line **2844** | -17 | P1 |
| #48 | "25-field `VbTerrainTileMetadata`" | actual **28 data fields** in `unity_plugin/VbTerrainTileMetadata.cs` | spec count off by 3 | P2 |
| #49 | `procedural_meshes.py` 22,816 LOC; 4 callers `_mesh_bridge.py:26, _terrain_depth.py:51, environment.py:229, _bridge_mesh.py:15` | not verified line-by-line | unknown | P2 |
| #56 | `vegetation_system.py:1284, 1534` | line 1284 unrelated; `lod_meshes` at 685/1561/1600 | -600 | P0 |
| #60 | `terrain_quixel_ingest.py:619` | line 619 ✅ (`sampled_albedo = _srgb_to_linear(_bilinear_sample_texture(`) | 0 | OK |
| #61 | `terrain_stochastic_shader.py:51-265` | HLSL block at **46-182** (Heitz 2019 already implemented); spec claim "URP-tagged at 73, 263" not verified — Heitz block looks like it could be either renderer | -5 / 0 | P1 (need shader review) |
| #61 | `terrain_banded_advanced.py:542` (`variant="classic"` hardcoded) | actual `variant: str = "classic"` at line **434** | -108 | P0 |
| #62 | `terrain_pipeline.py:1355-1421` (`pass_water_depth`) | actual `pass_water_depth` def at line **1275-1330**; register at 1344-1357 | -80 | P1 |
| #B5-A4 | `vegetation_system.py:1284` | line 1284 unrelated; lod_meshes elsewhere | -600 | P0 |
| #B5-U4 | `terrain_unity_export.py:334` (`_pack_tangent_space_normal_rgba`) | actual at line **288** | -46 | P1 |
| #B5-U4 | `VbTerrainImporter.cs:2097` (`textureType = NormalMap`) | actual at line **2040** | -57 | P1 |
| #B5-U2 | `VbTerrainImporter.cs:1150-1153` (raster-backed water mesh skip) | not found in scan; possibly different stub location | unknown | P1 |
| #B5-U11 | `VbTerrainImporter.cs:GetOrCreateTreePrefab:2229-2273` | actual `GetOrCreateTreePrefab` at line **2152**; `Capsule` primitive at **2196** | -77 | P1 |

---

## 4. Files referenced by spec but missing on `main`

| Spec reference | Status | Used by PRs |
|----------------|--------|-------------|
| `handlers/terrain_asset_budget.py` | NOT ON MAIN | #36, #B5-A1 (description body), §11.5.5 |
| `handlers/_parallel_merge.py` | NOT ON MAIN | #47 |
| `coastal/landform_zones.py` | NOT ON MAIN (NET-NEW per #26) | #26 |
| `coastal/shoreline_sdf.py` | NOT ON MAIN (NET-NEW per #26) | #26 |
| `chunks/chunk_seed.py` | NOT ON MAIN (NET-NEW per B5-D1) | B5-D1, B5-C4, #18 |
| `chunks/cache_invalidator.py` | NOT ON MAIN (NET-NEW per B5-D2) | B5-D2, B5-D3 |
| `chunks/chunk_baker.py` | NOT ON MAIN (NET-NEW per B5-D4) | B5-D4 |
| `chunks/edge_contract.py` | NOT ON MAIN (NET-NEW per #38, #39) | #38, #39, B5-U5 |
| `unity_export_v2/splat_layers.py` | NOT ON MAIN (NET-NEW per #40) | #40 |
| `unity_export_v2/texture_compression.py` | NOT ON MAIN (NET-NEW per #41) | #41, B5-A3 |
| `unity_export_v2/chunk_artifacts.py` | NOT ON MAIN (NET-NEW per #42) | #42, #44, B5-A2 |
| `unity_project/Assets/Shaders/...shadergraph` | NOT ON MAIN (no Unity project) | B5-U1 |
| `unity_project/Assets/Scripts/VbTerrainImporter.cs` | spec uses `unity_project/`; actual file is `unity_plugin/Editor/VbTerrainImporter.cs` | B5-U2, B5-U3, B5-U4, B5-U11 |
| `unity_project/Assets/Scripts/VbTerrainTileMetadata.cs` | spec uses `unity_project/`; actual file is `unity_plugin/VbTerrainTileMetadata.cs` | B5-U13 |
| `VbChunkLoader.cs` | NOT ON MAIN (no VbChunkLoader.cs file) | B5-U5, B5-U6, B5-U7, B5-U8, B5-U9, B5-U10, B5-U12, B5-U14 |
| `foliage/scatter/parent_child_rules.py` | NOT ON MAIN (NET-NEW per #27) | #27 |
| `foliage/scatter/artist_override.py` | NOT ON MAIN (NET-NEW per #28) | #28 |
| `foliage/wind_uv_bake.py` | NOT ON MAIN (NET-NEW per B5-U12) | B5-U12 |
| `foliage/species_libs/<biome>.yaml` | NOT ON MAIN | #57, #58, #59 |

**Implication**: 19 file paths in §11 v3 reference net-new files. This is fine if the spec drafted them as "feat(...)" PRs — and most do. The dangerous case is `terrain_asset_budget.py` and `_parallel_merge.py` which are cited as targets of `fix(...)` PRs (PR #36 row says "find `splatmap_layer_count = 4`" in `terrain_asset_budget.py`; PR #47 says "audit-referenced setattr-bypass leak" in `_parallel_merge.py`). Those PRs are **fix(...)** but the file does not exist — implementer must either CREATE the file (turning fix→feat) OR find the actual location of the targeted code.

---

## 5. Path namespace mismatches (spec vs `main`)

§11 v3 uses bare `handlers/<file>.py`, `providers/<file>.py`, `unity_project/Assets/...`. On `main`:

- `handlers/<file>.py` → `veilbreakers_terrain/handlers/<file>.py` (every PR has this prefix mismatch)
- `providers/<file>.py` → `veilbreakers_terrain/providers/<file>.py`
- `unity_project/Assets/...` → `unity_plugin/...` (Unity directory name DIFFERS)
- `tests/<file>.py` → likely `veilbreakers_terrain/tests/<file>.py` (per repo layout)

Every single PR row in §11 v3 has the wrong path prefix. This is a global doc-rot issue, not a per-PR finding.

**Recommended fix**: add a §11.0.3 "path conventions" preface stating "all `handlers/...` paths in this section are shorthand for `veilbreakers_terrain/handlers/...`", or globally update.

---

## 6. Missing dep edges in §11.6

| From | To | Why |
|------|----|-----|
| #53 | #23 | `environment.py` split invalidates surgical line cite |
| #53 | #25 | same |
| #53 | #45 | same |
| #53 | #49 | `environment.py:229` shim caller depends on file location |
| #54 | #29 | `terrain_features.py` split invalidates `rock_label` stamping site |
| #52 | {#16, #17, #21, #29, #37, #45, #62} | `terrain_semantics.py` `PassDefinition`/`PassResult` import site |
| #11 | #55 | path-injection edit BEFORE `asset_generation.py` delete |
| #43 | #55 | `lod_meshes` validator BEFORE `vegetation_system.py` delete |
| #B5-A4 | #55 | manifest-emission gate BEFORE `vegetation_system.py` delete |
| #48 | #20 | both edit `terrain_unity_export.py`; `_compat` shim before metadata consolidation |
| B5-U4 | {#5b, #48} | tangent-normal flip BOTH bake-side (`terrain_unity_export.py`) AND Unity-side; Unity-side change cascades from bake-side meta |
| B5-D1 | {#14, #15} | `chunk_seed` module USES `derive_pass_seed` primitives |
| #18 | B5-D1 | RNG migration USES chunk_seed (cycle break: arrow direction reversed from current) |
| B5-C2 | {#5b, #12, #13, #20, #48, B5-U4} | `terrain_unity_export.py` writer-edit chain (corrected list) |
| B5-C2-bis (NEW) | {#3, #4, #8, #14, #29, #35, #46, #51, #62, #21} | `terrain_pipeline.py` writer-edit chain — currently NO serialization rule exists |

**Total missing edges: 14** (excluding the new B5-C2-bis aggregate edge, which is itself a missing rule).

---

## 7. Line-cite verification (against `main` HEAD `3cc63c5`)

| PR | File:Line | Status | Notes |
|----|-----------|--------|-------|
| #6 | `terrain_advanced.py:2652` | OK | `align_to_normal = params.get("align_to_normal", True)` verified at line 2652 |
| #14 | `terrain_rng.py:45` (alternate to delete) | NOT ON MAIN | File is 43 lines on main; no `def derive_pass_seed` exists. Branch `docs/biome-render-rebuild-spec` adds the duplicate; spec was written against that worktree. Implementer branching from main has **nothing to delete** — PR #14 reduces to a no-op against main. |
| #14 | `terrain_pipeline.py:269` (canonical to keep) | DRIFT | Actual at line **208**. KEEP target verified to exist (signature `derive_pass_seed(intent_seed, seed_namespace, tile_x, tile_y, region) -> int`). |
| #15 | `terrain_cliffs.py:2397` | DRIFT | Actual `hash(cliff.cliff_id) & 0x7FFFFFFF` at line **2368**. |
| #19 | `_water_network.py:580-664` | DRIFT | `priority_flood_d8` at line **515**. |
| #19 | `_terrain_erosion.py:308-487` | DRIFT | particle loop at line **341+**. |
| #23 | `environment.py:6265-6266` (road_mask DAG-escape) | NOT FOUND | road_mask write closure not at 6265-6266. The road_mask logic is at `_build_road_mask_and_sdf` (4630-4689). PR #23 cite appears to refer to a no-longer-existing file or fundamentally wrong line. |
| #25 | `environment.py:2031` (biome archetype) | DRIFT | Actual at lines 1205, 2020, 2322, 2990, 3043. Line 2031 is unrelated. PR #25's "cite correction" is itself wrong. |
| #29 | `terrain_pipeline.py:1133-1191` (`pass_compute_terrain_labels`) | WRONG-PASS | Range 1133-1191 contains `pass_compute_biome_channels`. Actual `pass_compute_terrain_labels` at line **1054-1120**. |
| #36 | `terrain_quality_profiles.py:183/353/409/465/521` | DRIFT (-1) | Actual at 182/352/408/464/520. |
| #36 | `terrain_asset_budget.py` | NOT ON MAIN | File doesn't exist; feasibility reviewer correct. |
| #45 | `environment.py:2861` (`pass_hydrology` insert) | DRIFT | Actual at line **2844**. |
| #62 | `terrain_pipeline.py:1386-1392` (`pass_water_depth` skip) | WRONG-PASS | Range 1386-1392 contains `_topo_sort_passes` (Kahn's algorithm). Actual `pass_water_depth` def at line **1275-1330**. |
| B5-A4 | `vegetation_system.py:1284` (LOD mesh array) | NOT FOUND | Line 1284 is unrelated `terrain_vertices` block in spec_only mode. `lod_meshes` actually at lines **685, 1561, 1600**. |

**Verification summary**: of 14 high-risk surgical PRs verified, **only 1** has a fully-correct cite (PR #6). 13 have either DRIFT (5-100+ line offset), WRONG-PASS (cite points to a different code structure), NOT FOUND (cite cannot be located), or NOT ON MAIN (file doesn't exist).

---

## 8. Corrected B5-C2 cite

**Spec says** (§11.5.2 PR B5-C2 row): `dep ordering (#11 → #12 → #44 → #5b → #48)` — 5 PRs touching `terrain_unity_export.py`.

**Reality**:
- **#11** does NOT touch `terrain_unity_export.py`. It touches `providers/meshy_provider.py:216`, `providers/hunyuan3d2_provider.py:274`, `handlers/asset_generation.py:699,706`. (Verifier-B already noted this.)
- **#44** does NOT touch `terrain_unity_export.py` either. PR #44 row in §11.3 cites `unity_export_v2/chunk_artifacts.py` — a DIFFERENT (net-new) directory. (Verifier-B already noted this.)

**Actually touch `terrain_unity_export.py`**:
- **#5b** — water-channel migration (consumer at `:2270-2278`)
- **#12** — atomic manifest write (`json.dumps(manifest)` at `:2248, :2272`)
- **#13** — NaN/Inf sanitize ("various pack-points")
- **#20** — `_compat` shim for 14 test imports
- **#48** — consolidate metadata (25-field `VbTerrainTileMetadata` populate)
- **#B5-U4** — bake-side normal G-flip option in `_pack_tangent_space_normal_rgba` (line 288 on main)

**Corrected dep chain for B5-C2**:
```
#5b → #12 → #13 → #20 → #48 → B5-U4
(canonical) (atomic) (NaN/Inf) (compat shim) (consolidate) (normal flip option)
```

This is **6 PRs**, not 5. The original spec list of `#11 / #44` was contaminated with PRs that touch a different file (#11 → providers/asset_generation; #44 → unity_export_v2/).

---

## 9. PR-to-file edit summary table

For every PR in §11 v3, this table lists the files it touches per the spec. (Edit type: E=edit, C=create, D=delete, R=rename, M=meta/policy.)

| PR | Block | Files touched (spec-stated) |
|----|-------|------------------------------|
| 1 | 1 | E: `.gitignore` |
| 2 | 1 | E: `pyproject.toml` |
| 3 | 1 | E: `terrain_pipeline.py` |
| 4 | 1 | E: `terrain_pipeline.py`; spec body §3 lines 124, 237 |
| 5a | 1 | E: `terrain_water_variants.py`; `TerrainMaskStack` (in `terrain_semantics.py` likely) |
| 5b | 1 | E: `terrain_water_variants.py`, `terrain_unity_export.py`, `terrain_navmesh_export.py`, `pass_bathymetry`, `compute_riverbed_caustics` |
| 6 | 1 | E: `terrain_advanced.py` |
| 7 | 1 | E: `terrain_chunking.py` |
| 8 | 1 | E: `terrain_pipeline.py` |
| 9 | 1 | E: `road_network.py` |
| 10 | 1 | E: `terrain_shadow_clipmap_bake.py` |
| 11 | 1 | E: `meshy_provider.py`, `hunyuan3d2_provider.py`, `asset_generation.py` |
| 12 | 1 | E: `terrain_unity_export.py` |
| 13 | 1 | E: `terrain_unity_export.py` |
| 14 | 1 | E (delete): `terrain_rng.py`; E: `terrain_pipeline.py` |
| 15 | 1 | E: `terrain_cliffs.py` |
| 16 | 2 | E: `terrain_master_registrar.py`; E: `terrain_stratigraphy.py` |
| 17 | 2 | E: `terrain_morphology.py` |
| 18 | 2 | E: 47 handlers (full list in `RNG_SITES_47.txt`) + 11 tests |
| 19 | 2 | E: `_water_network.py`, `_terrain_erosion.py` |
| 20 | 2 | E: `terrain_unity_export.py`; C: `_compat.py` |
| 21 | 2 | E: 16+ pass declarations (`climate_zone`, `forest_mask`, `canopy_density`, `pass_road_network`, `quixel_ingest`, `waterfalls`, etc.) |
| 22 | 2 | E: `tests/test_dynamic_quality_truth_gates.py`, `tests/test_visual_render_camera_proof.py`, `tests/test_scene_v3_visual_quality_gate.py`, `tests/test_callable_orphan_contracts.py` |
| 23 | 2 | E: `environment.py` |
| 24 | 2 | E: `terrain_cliffs.py`; C: config `overhang_threshold_deg` |
| 25 | 2 | E: `environment.py` |
| 26 | 2 | C: `coastal/landform_zones.py`, `coastal/shoreline_sdf.py` |
| 27 | 2 | C: `foliage/scatter/parent_child_rules.py` |
| 28 | 2 | C: `foliage/scatter/artist_override.py`; C: `foliage/species_libs/<biome>_overrides.yaml` |
| 29 | 2 | E: `terrain_cliffs.py`, `terrain_water_variants.py`, `terrain_features.py`, `terrain_morphology.py`, `terrain_pipeline.py` |
| 30 | 2 | E: `terrain_waterfalls.py` |
| 31 | 2 | E: `terrain_macro_color.py` |
| 32 | 2 | E: `terrain_macro_color.py` |
| 33 | 2 | E: spec body; E: `terrain_audio_zones.py` (Sabine cites) |
| 34 | 2 | E: `terrain_checkpoints.py` (docstring + cleanup hooks) |
| 35 | 2 | E: `terrain_pipeline.py` |
| 36 | 2 | E: `terrain_asset_budget.py` (NOT ON MAIN); E: `terrain_quality_profiles.py`; E: `build_terrain_aaa_node_v6.py`; E: `default_dark_fantasy_rules` location TBD |
| 37 | 2 | E: `terrain_water_variants.py` |
| 38 | 3 | C: `chunks/edge_contract.py`; C: `tests/test_edge_vert_sharing.py` |
| 39 | 3 | E: `chunks/edge_contract.py` (write/read) |
| 40 | 3 | C: `unity_export_v2/splat_layers.py` |
| 41 | 3 | C: `unity_export_v2/texture_compression.py` |
| 42 | 3 | E: `unity_export_v2/chunk_artifacts.py` |
| 43 | 3 | E: `vegetation_system.py`, `procedural_grass.py`; C: validator |
| 44 | 3 | E: `unity_export_v2/chunk_artifacts.py` |
| 45 | 3 | E: `environment.py` |
| 46 | 3 | C: `_rule1_gate.py`; E: `TerrainPassController` (in `terrain_pipeline.py`) |
| 47 | 3 | E: `_parallel_merge.py` (NOT ON MAIN) |
| 48 | 3 | E: `terrain_unity_export.py` (reorders metadata) |
| 49 | 4 | R: `procedural_meshes.py` → sibling repo; C: `_compat/procedural_meshes.py`; E: `_mesh_bridge.py`, `_terrain_depth.py`, `environment.py`, `_bridge_mesh.py` |
| 50 | 4 | R: `animation_environment.py`, `animation_gaits.py`, `sim/foam.py`, `sim/cloth.py` → sibling repo |
| 51 | 4 | C: `terrain_core.py`; E: `terrain_rng.py` (re-export); E: `terrain_pipeline.py` (extract) |
| 52 | 4 | R: `terrain_semantics.py` → `_types.py` + `_semantics.py` |
| 53 | 4 | R: `environment.py` (8651 LOC) → 5-seam split |
| 54 | 4 | R: `terrain_features.py` → 9 files per `generate_*` |
| 55 | 4 | D: 47+ deprecated scripts; D: `terrain_scatter_altitude_safety.py`, `terrain_legacy_bug_fixes.py`, `asset_generation.py`, `vegetation_system.py` (per locked-list); D: 14 superseded markdowns; D: `output/visual_nodes/`; D: `output/aaa_node_v*/`, `*.blend1` |
| 56 | 4 | E: `vegetation_system.py` (defaults repair) |
| 57 | 4 | C: `foliage/species_libs/mountain.yaml`; C: `foliage/scatter/biome_specific/mountain.py` |
| 58 | 4 | C: `foliage/species_libs/grassland.yaml`; C: `foliage/scatter/biome_specific/grassland.py` |
| 59 | 4 | C: `foliage/species_libs/coastal.yaml`; C: `foliage/scatter/biome_specific/coastal.py` |
| 60 | 4 | E: `terrain_quixel_ingest.py` |
| 61 | 4 | E: `terrain_stochastic_shader.py`, `terrain_banded_advanced.py` |
| 62 | 4 | E: `terrain_pipeline.py` |
| B5-U1 | 5 | C: `unity_project/Assets/Shaders/...shadergraph` (or MicroSplat fallback) |
| B5-U2 | 5 | E: `VbTerrainImporter.cs` (raster water replace) |
| B5-U3 | 5 | E: `VbTerrainImporter.cs` (`SetHoles`) |
| B5-U4 | 5 | E: `VbTerrainImporter.cs` (G-channel invert); E: `terrain_unity_export.py` (bake-side flip option) |
| B5-U5 | 5 | E: `chunks/edge_contract.py`; C: `VbChunkLoader.cs` consumer |
| B5-U6 | 5 | E: `VbChunkLoader.cs` (vertex AO) |
| B5-U7 | 5 | E: `VbChunkLoader.cs` (decal projector) |
| B5-U8 | 5 | E: `VbChunkLoader.cs` (River currentMap) |
| B5-U9 | 5 | E: `VbChunkLoader.cs` (caves FBX) |
| B5-U10 | 5 | E: `VbChunkLoader.cs` (TerrainLayer height/detail) |
| B5-U11 | 5 | E: `VbChunkLoader.cs` (`GetOrCreateTreePrefab`) |
| B5-U12 | 5 | C: `foliage/wind_uv_bake.py`; E: `VbFoliageImporter.cs` |
| B5-U13 | 5 | E: `VbTerrainTileMetadata.cs` (25 fields → spec; reality is 28) |
| B5-U14 | 5 | E: `VbChunkLoader.cs` schema validators |
| B5-C1 | 5 | C: `terrain_channel_registry.py`; E: spec body §3.4 line 192 (delete) |
| B5-C2 | 5 | M: dep ordering (no code) |
| B5-C3 | 5 | M: dep ordering (no code) |
| B5-C4 | 5 | E: extends #18 with `seed_scope` argument |
| B5-C5 | 5 | E: extends #5b channel registration |
| B5-D1 | 5 | C: `chunks/chunk_seed.py` |
| B5-D2 | 5 | C: `chunks/cache_invalidator.py` |
| B5-D3 | 5 | E: `chunks/cache_invalidator.py` (watershed) |
| B5-D4 | 5 | C: `chunks/chunk_baker.py` + CLI |
| B5-T1 | 5 | C: `tests/golden_scenarios/{cave_entrance, cliff_talus_apron, deep_lake_basin, waterfall_plunge_pool}/baseline.png` (4 files); E: CI step uses `terrain_visual_qa.py:706` SSIM |
| B5-T2 | 5 | E: `pyproject.toml` (`pytest-benchmark`); E: 8 ad-hoc perf tests; C: `.github/workflows/perf-nightly.yml` |
| B5-T3 | 5 | E: `pyproject.toml` (`hypothesis`); C: `tests/test_channel_invariants.py` |
| B5-T4 | 5 | E: `tests/test_phase8_determinism_guardrails.py` |
| B5-T5 | 5 | E: `scripts/check_protocol_adoption.py`; E: handler decoration |
| B5-T6 | 5 | E: `pyproject.toml` (`pytest-rerunfailures`); C: `.github/workflows/flaky-hunter.yml` |
| B5-T7 | 5 | E: `.github/workflows/python-package.yml` (split fast/nightly) |
| B5-A1 | 5 | E: `scripts/build_terrain_aaa_node_v6.py` (controller wire) |
| B5-A2 | 5 | E: `unity_export_v2/chunk_artifacts.py` |
| B5-A3 | 5 | E: `unity_export_v2/texture_compression.py` |
| B5-A4 | 5 | E: `vegetation_system.py`, `procedural_grass.py` |
| B5-DEP1 | 5 | E: `pyproject.toml` |
| B5-DEP2 | 5 | C: `uv.lock` or `requirements-lock.txt`; C: `bake-env.yml` |
| B5-DEP3 | 5 | C: `.github/dependabot.yml`; E: GitHub Actions (SHA-pin); E: `hunyuan3d2_provider.py` (HF Space SHA pin); E: `.github/codeql/codeql-config.yml` |
| B5-DOC1 | 5 | R: 14 markdowns → `docs/_archive/2026-04/`; C: `docs/_archive/2026-04/INDEX.md` |
| B5-DOC2 | 5 | E: `docs/aaa-audit/deep_dive_2026_04_27/master_implementation_guide.md` |
| B5-DOC3 | 5 | E: spec body lines 7, 27 |
| B5-DOC4 | 5 | E: `docs/BLENDER_AGENT_USAGE_GUIDE.md`, `docs/TERRAIN_CALLABLE_USAGE_GUARDRAIL.md` |

---

## 10. Recommendations to fixes guide

1. **Add §11.0.3 path-prefix preface** stating all `handlers/`, `providers/`, `tests/`, `chunks/`, `unity_project/` shorthand expand to `veilbreakers_terrain/handlers/`, `veilbreakers_terrain/providers/`, `veilbreakers_terrain/tests/`, `veilbreakers_terrain/chunks/`, `unity_plugin/` respectively.
2. **Re-anchor 22 surgical-PR line cites against `main` HEAD** (not against the in-flight branch). Spec was drafted on a worktree containing speculative refactors that haven't landed; line numbers drift by 5-1600 lines for many PRs.
3. **Resolve 6 P0 cite errors** (table 7) before any implementer can act:
   - PR #14 (`terrain_rng.py:45` doesn't exist on main)
   - PR #16 (`terrain_master_registrar.py` lacks `register_stratigraphy_pass`/`wind_erosion`)
   - PR #23 (`environment.py:6265-6266` road_mask cite untraceable)
   - PR #25 (`environment.py:2031` is itself wrong)
   - PR #29 (`terrain_pipeline.py:1133-1191` cites the WRONG pass)
   - PR #36 (`terrain_asset_budget.py` doesn't exist)
   - PR #43, #B5-A4, #56 (`vegetation_system.py:1284` is unrelated code)
   - PR #62 (`terrain_pipeline.py:1386-1392` cites `_topo_sort_passes`, not `pass_water_depth`)
4. **Add 14 missing dep edges to §11.6** (table 6).
5. **Resolve PR #18 ↔ B5-D1 cycle** by reversing arrow direction (B5-D1 → #14, #15; #18 → B5-D1) and fixing §11.0.2's typo from "PR #36" to "PR B5-D1".
6. **Correct B5-C2's serialization cite chain** from `#11 → #12 → #44 → #5b → #48` (5 PRs, 2 of which don't touch the file) to `#5b → #12 → #13 → #20 → #48 → B5-U4` (6 PRs, all of which actually edit `terrain_unity_export.py`).
7. **Add a B5-C2-bis serialization rule for `terrain_pipeline.py`** to cover Block 2/3/4 PRs colliding on the orchestrator file (11 PRs).
8. **Decide #55's locked-list relative to #43, #B5-A4, #11**: either remove `vegetation_system.py` and `asset_generation.py` from the delete (leaving only deprecated scripts), or add explicit deps `#11, #43, #B5-A4 → #55`.
9. **Audit unity_plugin paths** — replace all `unity_project/Assets/Scripts/...` references with `unity_plugin/...` (Unity directory rename).
10. **Update memory finding #1** — `VbTerrainTileMetadata` has 28 data fields on `main`, not 25 (spec-claimed) or 3 (stale memory). Fix in PR B5-U13's row and in §11.10 #1.
