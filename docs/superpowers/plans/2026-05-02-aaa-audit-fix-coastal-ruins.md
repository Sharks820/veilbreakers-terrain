# AAA Terrain Audit-Fix + Sunken Coastal Ruins Node — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every confirmed audit item (Batches 0–14) in strict dependency order with Opus verification at each gate, then build a AAA-quality Sunken Coastal Ruins terrain node with Hunyuan3D-2 props and Opus visual approval before GitHub push.

**Architecture:** Sequential Approach A — each phase fully verified before the next starts. Phase 1 scans all 13 code domains for new bugs (Batch 14). Phase 2 Opus verifies all 429+ items are still real. Phase 3 fixes them in safe dependency order (Batch 0 → 14), with the primary session running pytest + callable census after each batch and Opus doing static code review only. Phase 4 builds the terrain node standalone-Python (Caldera v2 pattern), generates Hunyuan3D-2 props via HF Space, renders in Blender 4.5, and gets Opus AAA approval before committing outputs.

**Tech Stack:** Python 3.11/3.12, Blender 4.5 bpy, Unity HDRP C#, NumPy/SciPy, gradio_client (Hunyuan3D-2 via HF Space), pytest, pyright, GitHub Actions (callable-census, ci, pyright checks)

**Source of truth for fix specifications:** `docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md` — this plan references FIX IDs; read the codex for each fix's exact before/after code. Starting Phase 3, use `docs/aaa-audit/ACTIVE_ITEMS_FINAL_2026_05_02.json` as the authoritative work list — only implement items marked ACTIVE in that file.

**Opus checkpoint rule (applies to ALL batch tasks):** Opus reads changed files and verifies code matches codex spec via static reading only. Opus does NOT invoke pytest, run commands, or mutate files. The primary session (not subagents) runs `pytest` and `callable_census_gate.py`.

---

## Chunk 1: Phase 1 — Batch 14 Deep Scan

**Goal:** Systematically scan all 13 code domains for bugs not yet in the codex. Output `docs/aaa-audit/BATCH14_FINDINGS.md`.

**13 scan domains (per spec Phase 1 table):**
1. Water / coastline
2. Coastline / tidal zones
3. Erosion / geology
4. Materials / splatmap
5. Scatter / foliage
6. Unity export / C#
7. Procedural meshes
8. Roads / navmesh
9. Atmospheric / VFX
10. Tests / guardrails
11. CodeQL 629-alert audit
12. Hunyuan3D-2 provider
13. Visual pipeline / renders

**Key pre-scan context (confirmed findings — assign to tasks below):**
- `coastline.py:detect_tidal_zones()` emits only scalar mask — no 5-zone label channel → **B14-W-1** (pre-confirmed, include in Task 1.1 output)
- `terrain_dem_import.py:466` synthetic fallback removed → caller audit needed → **B14-E candidate** (Task 1.2)
- `environment.py:3792` strict material coverage default change → guard check needed → **B14-S candidate** (Task 1.4)

---

### Task 1.1: Scan — Water / Coastline + Coastline / Tidal Zones (domains 1 & 2)

**Files to read:**
- `veilbreakers_terrain/handlers/coastline.py`
- `veilbreakers_terrain/handlers/_water_network.py`
- `veilbreakers_terrain/handlers/terrain_water_variants.py`
- `veilbreakers_terrain/handlers/terrain_waterfalls.py`

- [ ] **Step 1:** Read `coastline.py` top-to-bottom. For each function, check:
  - Does it write to the mask stack with `stack.set()`? If it computes a value and discards it, note it.
  - Are all 5 tidal zones (subtidal / intertidal / splash / spray / supralittoral) emitted as a labeled uint8 channel OR only as a scalar blend?
  - Does `pass_coastline` register itself in the pass registry?
  - Does `compute_wave_energy()` write its result to the stack?

- [ ] **Step 2:** Read `_water_network.py`. Check:
  - `assign_strahler_orders` — does it still use `setattr` on a dataclass (B12 issue)?
  - `get_tile_water_features` — are dead-assignment lines (`_ = self.nodes.get(...)`) still present?
  - `_compute_tile_contracts` — midpoint approximation still there?

- [ ] **Step 3:** Read `terrain_water_variants.py`. Check:
  - Line 755 threshold — was FIX-0-2 already applied on this branch?
  - Any new `stack.set()` missing after a channel computation?

- [ ] **Step 4:** Read `terrain_waterfalls.py`. Check:
  - Waterfall splash zone `wet_rock` bridging — was recent commit (`325a8a9`) complete?
  - Any orphaned `drop_here` or `Q` values computed but not written?

- [ ] **Step 5:** Document findings. Include pre-confirmed finding:
  ```
  B14-W-1 | coastline.py:1165 | P1 | detect_tidal_zones emits scalar 0–1 tidal mask only;
           |                   |    | no tidal_zone_label channel (uint8 0–4) for splatmap 5-zone consumption
  ```
  Format all findings as: `B14-W-N | file:line | severity (P0/P1/P2/INFO) | description`

---

### Task 1.2: Scan — Erosion / Geology (domain 3)

**Files to read:**
- `veilbreakers_terrain/handlers/_terrain_erosion.py`
- `veilbreakers_terrain/handlers/terrain_stratigraphy.py`
- `veilbreakers_terrain/handlers/terrain_geology_validator.py`
- `veilbreakers_terrain/handlers/terrain_glacial.py`
- `veilbreakers_terrain/handlers/terrain_karst.py`
- `veilbreakers_terrain/handlers/terrain_wind_erosion.py`

- [ ] **Step 1:** Read `_terrain_erosion.py`. Check:
  - Line 308 erodibility divide by 1e-3 — was FIX-0-3 applied on this branch?
  - Any erosion pass results (flow_accumulation, sediment, erosion_amount) computed but not written to stack?
  - Does `pass_erosion` properly write `pool_deepening_delta` to stack (FIX-0-6 scope)?

- [ ] **Step 2:** Read `terrain_stratigraphy.py`. Check:
  - `simulate_fold_deformation` — does it call `stack.height =` directly (bypassing ownership)?
  - Line 991 stratigraphy erosion delta — never applied to heightmap?
  - Any functions that compute values and return them without calling `stack.set()`?

- [ ] **Step 3:** Read `terrain_geology_validator.py`. Check:
  - Do validators call `stack.set()` for cliff_mask, talus_mask, strata_mask?
  - Any bare `raise Exception` instead of domain-specific errors?

- [ ] **Step 4:** Check `terrain_glacial.py`, `terrain_karst.py`, `terrain_wind_erosion.py`:
  - Hack's law fraction vs. area_m2 (FIX-10-2 scope)
  - Absolute dissolution threshold in karst (FIX-10-3 scope)
  - `np.gradient` missing `cell_size_m` (FIX-10-1 scope)
  - Audit DEM synthetic fallback callers (pre-confirmed: `terrain_dem_import.py:466` removed fallback — check if any caller depends on it)

- [ ] **Step 5:** Document all findings as `B14-E-N` entries.

---

### Task 1.3: Scan — Materials / Splatmap (domain 4)

**Files to read:**
- `veilbreakers_terrain/handlers/terrain_materials.py`
- `veilbreakers_terrain/handlers/terrain_quixel_ingest.py`
- Any `terrain_materials_v2.py` or `terrain_lava.py`

- [ ] **Step 1:** Read `terrain_materials.py`. Check:
  - Is `BIOME_PALETTES` the single source of truth, or does a second registry exist?
  - Are `compute_slope_material_weights` thresholds in radians (after FIX-0-1 slope fix)?
  - Does the splatmap-assembly step produce normalized weights (sum to 1.0)?
  - Any template slots (morphology_specs etc.) defined but never populated?

- [ ] **Step 2:** Read `terrain_quixel_ingest.py`. Check:
  - Normal blend at line ~730 — FIX-10-Q1 Whiteout blend — applied?
  - `old_layer_scale` renormalization — does it correctly rescale all 5 channels or only some?
  - Are there layers defined in the Quixel manifest that never get splatmap weights written?

- [ ] **Step 3:** Check for `terrain_lava.py` — FIX-10-9 says "lava system entirely absent." Does this file exist? If not, note it.

- [ ] **Step 4:** Run callable census to get current uncovered callable count:
  ```bash
  python scripts/callable_census_gate.py --strict-zero
  ```
  Note the count. Any callable in materials/quixel domain that is uncovered is a candidate.

- [ ] **Step 5:** Document all findings as `B14-M-N` entries.

---

### Task 1.4: Scan — Scatter / Foliage (domain 5)

**Files to read:**
- `veilbreakers_terrain/handlers/terrain_decal_placement.py`
- Any `_scatter_engine.py` or `environment_scatter.py`
- `veilbreakers_terrain/handlers/environment.py` (scatter-relevant sections)

- [ ] **Step 1:** Read scatter handler files. Check:
  - `apply_collision_exclusion` — FIX-10-22 says never called after scatter. Is it wired now?
  - `SpeciesSpec` — does it have LOD, wind vertex colors, impostor fields?
  - Duplicate wiring paths in `COMMAND_HANDLERS` — FIX C-1 scope.
  - Any scatter that writes density records but never calls `stack.set("scatter_density", ...)`?

- [ ] **Step 2:** Read `terrain_decal_placement.py`. Check:
  - `decal_density` dict type — FIX-10-H12 says dict type mismatch. Fixed?
  - `optional_channels` addition — does it properly soft-order the pass?

- [ ] **Step 3:** Check `environment.py`:
  - `heightmap.tolist()` at line ~2246 — FIX-10-16 scope. Fixed?
  - Per-vertex Python Z write loop at line ~8253 — FIX-10-17 scope. Fixed?
  - `bmesh.new()` sites with no `try/finally` — FIX-10-15 scope. Any remaining?
  - Pre-confirmed: `environment.py:3792` strict `material_coverage=True` default — does it break any existing biome rule set?

- [ ] **Step 4:** Document findings as `B14-S-N` entries.

---

### Task 1.5: Scan — Unity Export / C# (domain 6)

**Files to read:**
- `veilbreakers_terrain/handlers/terrain_unity_export.py`
- `unity_plugin/Editor/VbTerrainImporter.cs`
- `veilbreakers_terrain/handlers/terrain_navmesh_export.py`

- [ ] **Step 1:** Read `terrain_unity_export.py`. Check:
  - `_write_raw_array` NaN/Inf scrub — FIX-0-4 scope. Applied?
  - `VbTerrainTileMetadata.ChannelBounds` — FIX-10-8 scope. Is it populated?

- [ ] **Step 2:** Read `VbTerrainImporter.cs`. Check:
  - Splatmap `layer_end = -1` bug — FIX-10-6 scope. Fixed?
  - Navmesh uint8/ushort mismatch — FIX-10-7 scope. Fixed?
  - Foliage manifest — FIX-10-J2 scope. Is foliage ever attached in Unity?
  - Off-mesh JSON — FIX-10-H2 scope. Is it imported?

- [ ] **Step 3:** Read `terrain_navmesh_export.py`. Check:
  - OBJ vs NMX format — correct format for Unity navmesh?

- [ ] **Step 4:** Document findings as `B14-U-N` entries.

---

### Task 1.6: Scan — Procedural Meshes / Roads / Atmospheric / Tests / Hunyuan3D-2 provider / Visual pipeline (domains 7–13)

**Files to read:**
- `veilbreakers_terrain/procedural_meshes.py` (relevant sections — grep first)
- `veilbreakers_terrain/handlers/terrain_roads.py` (or equivalent)
- `veilbreakers_terrain/handlers/atmospheric_volumes.py`
- `veilbreakers_terrain/providers/hunyuan3d2_provider.py`
- `scripts/build_aaa_ashen_caldera_node_v1.py` (visual pipeline reference)

- [ ] **Step 1:** Grep procedural_meshes.py for functions defined but never called from non-test files:
  ```bash
  grep -n "def generate_" veilbreakers_terrain/procedural_meshes.py | head -50
  ```
  Check UV layers or vertex color domains written to wrong Blender domain (CORNER vs POINT).

- [ ] **Step 2:** Check roads (domain 8):
  - `pass_road_network` — FIX-10-25 says unregistered. Is it registered now?
  - A* 24-direction table — complete?
  - Road mask wiring to stack — FIX-0-5 scope. Applied?

- [ ] **Step 3:** Check `atmospheric_volumes.py` (domain 9):
  - `compute_atmospheric_placements` — FIX-10 said `pz=0.0` for all placements. Fixed?
  - Volume mesh spec — cone/icosphere/box geometry valid?

- [ ] **Step 4:** Scan tests / guardrails (domain 10):
  - Are there test-only callables with no runtime callers? (callable census flags these)
  - Any mock leaks — test files that import production modules and leave patched state?
  - Any test that passes but relies on a broken stub instead of real implementation?

- [ ] **Step 5:** Scan Hunyuan3D-2 provider (domain 12):
  - Read `veilbreakers_terrain/providers/hunyuan3d2_provider.py`
  - Verify HF Space wiring: `gradio_client` import guard present?
  - `/generation_all` endpoint name correct and used for shape + PBR texture?
  - `HUGGINGFACE_TOKEN` env var (or `HF_TOKEN`) read and passed to client?
  - Local mode explicitly blocked (raises `RuntimeError` if `HUNYUAN3D2_MODE=local`)?

- [ ] **Step 6:** Scan visual pipeline / renders (domain 13):
  - Read `scripts/build_aaa_ashen_caldera_node_v1.py` for pattern reference
  - Is `_gpu_cycles_available()` probe implemented and used for engine selection?
  - Is EEVEE NEXT fallback present when GPU unavailable?
  - Does the output manifest (`BUILD_SUMMARY.json`) include required fields?
  - Any Blender deprecated APIs (non-4.5) in the visual pipeline?

- [ ] **Step 7:** Document all findings:
  - Procedural meshes: `B14-P-N`
  - Roads/navmesh: `B14-R-N`
  - Atmospheric: `B14-A-N`
  - Tests/guardrails: `B14-T-N`
  - Hunyuan3D-2: `B14-H-N`
  - Visual pipeline: `B14-V-N`

---

### Task 1.7: Scan — CodeQL 629-Alert Full Triage (domain 11)

**Goal:** Every one of the 629 CodeQL alerts must map to either a FIX entry or an explicit REFUTED entry.

- [ ] **Step 1:** Fetch the current GitHub CodeQL alerts list:
  ```bash
  gh api repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/code-scanning/alerts \
    --paginate -q '.[] | [.number, .rule.id, .most_recent_instance.location.path, .most_recent_instance.location.start_line, .state] | @tsv' \
    > /tmp/codeql_alerts.tsv 2>/dev/null || echo "gh auth needed — skip to Step 2"
  ```
  If `gh auth` not available, use `output/spreadsheet/CALLABLE_WIRING_AUDIT_2026_04_19.csv` as baseline.

- [ ] **Step 2:** For each alert category, verify FIX_ORDER_CODEX has coverage:
  - `pythagorean` (122 alerts) → FIX-11-6: `np.hypot` replacement
  - `unused-import` (73 alerts) → FIX-11-9: unused imports
  - `unused-local-variable` (143 alerts) → FIX-11-10: unused locals / orphaned wiring
  - `cyclic-import` (50 alerts) → FIX-11-4: cyclic imports
  - `empty-except` (57 production sites) → FIX-11-5: empty-except expansion
  - `multiple-definition` (~21 alerts) → FIX-11-3 + FIX-11-4
  - `import-and-import-from` (19 alerts) → FIX-11-9
  - `file-not-closed` (1 alert) → FIX-11-7
  - `self-assignment` (1 alert) → FIX-11-10
  - Remaining (~142 alerts that are test-noise/false positives) → need individual REFUTED entries

- [ ] **Step 3:** For each alert NOT covered by an existing FIX entry, decide:
  - **ACTIVE** → add to Batch 14 findings as `B14-CQL-N`
  - **REFUTED** → note as `B14-CQL-N | REFUTED | reason`
  Record the `codeql_alert_ref` (GitHub alert number) for each alert.

- [ ] **Step 4:** Document the complete mapping in findings output (Task 1.8 compiles this).

---

### Task 1.8: Write BATCH14_FINDINGS.md

- [ ] **Step 1:** Compile all findings from Tasks 1.1–1.7 into one file:
  ```
  docs/aaa-audit/BATCH14_FINDINGS.md
  ```
  Format:
  ```markdown
  # Batch 14 Findings — 2026-05-02

  ## Summary
  | Domain | New findings | Severity breakdown |
  |---|---|---|
  ...

  ## Findings

  ### B14-W-1 — coastline.py:detect_tidal_zones 5-zone label channel missing
  **File:** veilbreakers_terrain/handlers/coastline.py:1165
  **Severity:** P1
  **Finding:** detect_tidal_zones() emits scalar 0–1 tidal mask only; no tidal_zone_label uint8 channel (0=subtidal, 1=intertidal, 2=splash, 3=spray, 4=supralittoral)
  **Fix:** Add tidal_zone_label channel via stack.set()
  **codeql_alert_ref:** null (not a CodeQL alert)
  ```
  Include `codeql_alert_ref` field on every entry (GitHub alert number for CodeQL alerts, `null` for non-CodeQL findings).

- [ ] **Step 2:** Commit:
  ```bash
  git add docs/aaa-audit/BATCH14_FINDINGS.md
  git commit -m "audit(batch14): new findings from 13-domain deep scan"
  ```

**Gate:** BATCH14_FINDINGS.md written and committed. All 13 scan domains covered.

---

## Chunk 2: Phase 2 — Opus Consolidation + Open-Item Verification

**Goal:** Single Opus verification pass classifies every item in Batches 0–13 + Batch 14 as FIXED, ACTIVE, REFUTED, or REDUNDANT. Outputs updated codex + ACTIVE_ITEMS_FINAL.json.

**Opus constraint:** Static code reading only. No pytest. No mutations.

---

### Task 2.1: Opus verify Batches 0–6

- [ ] **Step 1:** For each FIX entry in Batches 0–6 of `FIX_ORDER_CODEX_2026_04_27.md`, read the specific file:line cited and check whether the fix is applied on the current branch.

  Decision tree per item:
  - Current code matches the "Fixed code" block → mark `FIXED`
  - Current code still matches the "Current code" block → mark `ACTIVE`
  - Current code is different from both → investigate and decide
  - Current code is a duplicate of an earlier fix → mark `REDUNDANT` (reference the earlier FIX ID)

- [ ] **Step 2:** Verify all Batch 0 items as defined in the codex (do not assume count — read all FIX-0-x entries):
  - FIX-0-1: `np.degrees(...)` → `np.arctan(...)` in build script (slope in radians not degrees)
  - FIX-0-2: water_variants threshold 0.75 → 0.55
  - FIX-0-3: erodibility `/ 1e-3` → direct clip
  - FIX-0-4: NaN scrub in `_write_raw_array`
  - FIX-0-5: road_mask stack.set() after `_build_road_mask_and_sdf`
  - FIX-0-6: pool_deepening_delta written to stack
  - FIX-0-7: StratigraphyStack `base_elevation_m=0.0` → `_hmap_min` in build script
  - FIX-0A through FIX-0G: preflight fixes (test infrastructure fixes)

- [ ] **Step 3:** Output ACTIVE vs FIXED count for Batches 0–6.

---

### Task 2.2: Opus verify Batches 7–13 + Batch 14

- [ ] **Step 1:** For each FIX entry in Batches 7–13, apply same decision tree as Task 2.1.

- [ ] **Step 2:** For each Batch 14 finding from BATCH14_FINDINGS.md, decide ACTIVE vs REFUTED:
  - Fix already exists in current code → REFUTED (mark with evidence)
  - Issue already covered by an earlier batch FIX → REDUNDANT (reference the FIX ID)
  - Genuinely new → ACTIVE

- [ ] **Step 3:** Confirm all 629 CodeQL alerts are adjudicated:
  - Each alert must have a FIX entry (active or completed) OR a written REFUTED entry
  - Use the category mapping from Task 1.7 as the baseline
  - Write individual REFUTED entries for test-noise / false-positive alerts (~187 alerts), each with specific evidence

---

### Task 2.3: Write updated codex + output files

- [ ] **Step 1:** Append Batch 14 section to `docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md`:
  ```markdown
  ## BATCH 14 — NEW FINDINGS 2026-05-02
  (one entry per ACTIVE finding from BATCH14_FINDINGS.md, same format as prior batches)
  ```
  Update batch summary table at top of codex with accurate fix counts for every batch.

- [ ] **Step 2:** Write `docs/aaa-audit/REFUTED_2026_05_02.md`:
  ```markdown
  # Refuted Findings — 2026-05-02
  | ID | Original claim | Evidence | Verdict |
  ...
  ```

- [ ] **Step 3:** Write `docs/aaa-audit/ACTIVE_ITEMS_FINAL_2026_05_02.json`:
  ```json
  [
    {
      "fix_id": "FIX-0-1",
      "batch": 0,
      "status": "ACTIVE",
      "file": "scripts/build_terrain_aaa_node_v6.py",
      "line": 178,
      "description": "slope written in degrees; all readers expect radians",
      "codeql_alert_ref": null
    },
    ...
  ]
  ```
  Include `codeql_alert_ref` field (GitHub alert number or `null`). List every ACTIVE item across Batches 0–14 in dependency order.

- [ ] **Step 4:** Update `docs/aaa-audit/GRADES_VERIFIED.csv` for any grade changes from Batch 14 findings.
  **Rule:** All new findings MUST be merged into GRADES_VERIFIED.csv directly — do NOT write a parallel CSV file (e.g., no `GRADES_VERIFIED_BATCH14.csv`). This is per project constraint.

- [ ] **Step 5:** Commit all outputs:
  ```bash
  git add docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md \
          docs/aaa-audit/REFUTED_2026_05_02.md \
          docs/aaa-audit/ACTIVE_ITEMS_FINAL_2026_05_02.json \
          docs/aaa-audit/GRADES_VERIFIED.csv
  git commit -m "audit: Phase 2 verification — codex updated with accurate counts, 629 CodeQL alerts adjudicated, ACTIVE_ITEMS_FINAL written"
  ```

**Gate:** All items classified. Codex updated with accurate batch contents and fix counts. All 629 CodeQL alerts individually adjudicated (each has FIX entry OR REFUTED entry). GRADES_VERIFIED.csv updated (no parallel files). ACTIVE_ITEMS_FINAL.json written.

---

## Chunk 3: Phase 3 Tiers T0–T3 — Batches 0–4 (Foundation Fixes)

**Goal:** Fix all critical-path, wiring, export, math, and simulation completeness items. These are the highest-severity fixes that unlock downstream systems.

**Rules:**
- Read `docs/aaa-audit/ACTIVE_ITEMS_FINAL_2026_05_02.json` at the start — only implement items marked ACTIVE. Do NOT implement FIXED or REFUTED items.
- Read FIX_ORDER_CODEX for exact before/after code for each fix. The plan provides the process; the codex provides the content.
- Opus checkpoints: static reading only, no pytest (see header rule).
- Commit message format: `fix(batchN): <N> <type> fixes — <key items>` (e.g., `fix(batch0): 7 critical-path single-line fixes — slope units, water threshold, erodibility, NaN export, road_mask, pool_delta, stratigraphy base`)

**Test commands:**
```bash
# Full suite
pytest veilbreakers_terrain/tests/ -x -q --timeout=120

# Callable census
python scripts/callable_census_gate.py --strict-zero

# Quick smoke
pytest veilbreakers_terrain/tests/ -x -q -k "smoke" --timeout=30
```

---

### Task 3.0: Batch 0 — 7 Critical-Path Single-Line Fixes

**Source:** `ACTIVE_ITEMS_FINAL_2026_05_02.json` Batch 0 entries.

**Known fixes (verify each is still ACTIVE):**
- FIX-0-1: slope in degrees → radians (`scripts/build_terrain_aaa_node_v6.py:178`)
- FIX-0-2: water threshold 0.75 → 0.55 (`terrain_water_variants.py:755`)
- FIX-0-3: erodibility `/ 1e-3` → direct clip (`_terrain_erosion.py:308`)
- FIX-0-4: NaN scrub in `_write_raw_array` (`terrain_unity_export.py:426-429`)
- FIX-0-5: road_mask stack.set() (`environment.py:6141`)
- FIX-0-6: pool_deepening_delta to stack (`_terrain_world.py:1297 area`)
- FIX-0-7: StratigraphyStack `base_elevation_m=0.0` → `_hmap_min` (`build_terrain_aaa_node_v6.py:201-207`)

- [ ] **Step 1:** For each of the 7 fixes, read the cited file:line. Verify current code still has the bug (ACTIVE, not already FIXED on this branch). Skip any that are already FIXED.

- [ ] **Step 2:** For each ACTIVE fix, write a failing test:
  ```python
  # Example for FIX-0-1 slope units
  def test_slope_channel_in_radians():
      """slope must be in radians — threshold 0.524 rad (~30°) must work"""
      slope = compute_slope(heightmap)
      assert slope.max() <= math.pi / 2  # never exceeds 90° in radians
      assert slope.max() > 0.01  # never degrees (30° in degrees >> π/2)
  ```

- [ ] **Step 3:** Run failing tests to **confirm they fail**:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q -k "batch0" --timeout=30
  ```
  Expected: FAIL. If a test unexpectedly passes, the fix may already be applied — verify before proceeding.

- [ ] **Step 4:** Apply each fix exactly as specified in the codex (copy the "Fixed code" block verbatim).

- [ ] **Step 5:** Run full test suite. All must pass:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q --timeout=120
  python scripts/callable_census_gate.py --strict-zero
  ```

- [ ] **Step 6:** Opus checkpoint — Opus reads the changed files and confirms each fix matches the codex "Fixed code" block exactly. No test run by Opus.

- [ ] **Step 7:** Commit:
  ```bash
  git add <all changed files>
  git commit -m "fix(batch0): 7 critical-path single-line fixes — slope units, water threshold, erodibility, NaN export, road_mask, pool_delta, stratigraphy base"
  ```

---

### Task 3.1: Batch 1 — Pipeline Wiring (12 fixes)

**Key items (from codex):** Pass appends, missing `stack.set()` calls, pass registration gaps.

- [ ] **Step 1:** Read Batch 1 section of `ACTIVE_ITEMS_FINAL_2026_05_02.json`. List all ACTIVE Batch 1 fixes with file:line.

- [ ] **Step 2:** For each fix, verify ACTIVE (not already FIXED on this branch).

- [ ] **Step 3:** Write failing tests that prove the wiring is absent:
  ```python
  def test_pass_writes_channel_to_stack():
      result = run_pass(intent, stack)
      assert stack.has_channel("expected_channel")
  ```

- [ ] **Step 4:** Run failing tests to **confirm they fail** before applying any fixes.

- [ ] **Step 5:** Apply all active fixes.

- [ ] **Step 6:** Run test slice + callable census:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q -k "batch1 or pipeline or wiring" --timeout=60
  python scripts/callable_census_gate.py --strict-zero
  ```

- [ ] **Step 7:** Opus checkpoint — static reading only, no pytest. Confirms all `stack.set()` inserts and pass registrations match codex.

- [ ] **Step 8:** Commit:
  ```bash
  git commit -m "fix(batch1): pipeline wiring — 12 pass registration + stack.set fixes"
  ```

---

### Task 3.2: Batch 2 — Export Contracts (10 fixes)

**Key items:** Binary channel export, splatmap normalization, Unity importer gaps.

- [ ] **Step 1:** Read Batch 2 entries in `ACTIVE_ITEMS_FINAL_2026_05_02.json`. List all ACTIVE Batch 2 fixes.

- [ ] **Step 2:** Verify ACTIVE for each.

- [ ] **Step 3:** Write failing tests — especially for Unity binary export:
  ```python
  def test_exported_float32_has_no_nan():
      export_channel(arr_with_nan, output_path)
      raw = np.frombuffer(output_path.read_bytes(), dtype=np.float32)
      assert not np.any(np.isnan(raw))
  ```

- [ ] **Step 4:** Run failing tests to **confirm they fail** before applying any fixes.

- [ ] **Step 5:** Apply all active fixes.

- [ ] **Step 6:** Run tests:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q -k "batch2 or export or unity or splatmap" --timeout=60
  ```

- [ ] **Step 7:** Opus checkpoint — static reading only, no pytest. Confirms Unity importer + export handler changes match codex.

- [ ] **Step 8:** Commit:
  ```bash
  git commit -m "fix(batch2): export contracts — NaN scrub, splatmap norm, Unity importer gaps"
  ```

---

### Task 3.3: Batch 3 — Math / Algorithm Correctness (18 fixes)

**Key items:** Wrong formulas, wrong units — Hack's law, karst dissolution threshold, D8 river tracing, Manning equation, Barnes 2014 priority-flood, Leopold-Maddock, Olsen 2004.

- [ ] **Step 1:** Read Batch 3 entries in `ACTIVE_ITEMS_FINAL_2026_05_02.json`. List all ACTIVE fixes. Note which reference external publications.

- [ ] **Step 2:** For each formula fix, write a golden-value test:
  ```python
  def test_river_width_leopold_maddock():
      """Leopold-Maddock 1953: w ~ Q^0.5"""
      w1 = compute_river_width(acc=100)
      w2 = compute_river_width(acc=400)
      assert abs(w2 / w1 - 2.0) < 0.3  # doubling Q → sqrt(4)=2x width
  ```

- [ ] **Step 3:** Run to confirm failures.

- [ ] **Step 4:** Apply all active fixes.

- [ ] **Step 5:** Run full suite:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q --timeout=120
  ```

- [ ] **Step 6:** Opus checkpoint — static reading only, no pytest. Confirms each formula change matches its cited reference (Olsen 2004, Leopold-Maddock, Manning, Barnes 2014, etc.).

- [ ] **Step 7:** Commit:
  ```bash
  git commit -m "fix(batch3): math/algorithm correctness — 18 formula and unit fixes"
  ```

---

### Task 3.4: Batch 4 — Simulation Completeness (14 fixes)

**Key items:** Stubs replaced with real algorithms (lava system creation, snow wind drift, L-system LOD, etc.).

- [ ] **Step 1:** Read Batch 4 entries in `ACTIVE_ITEMS_FINAL_2026_05_02.json`. List all ACTIVE items. For each, verify it is still ACTIVE (not already FIXED) before writing any tests.

- [ ] **Step 2:** Note which require creating new files (e.g., `terrain_lava.py`):
  ```python
  # veilbreakers_terrain/handlers/terrain_lava.py
  # Lava flow simulation: cellular automaton on heightmap
  # pass_lava_flow registered in terrain_pipeline
  ```

- [ ] **Step 3:** Write integration tests for each stub→real replacement:
  ```python
  def test_lava_flow_produces_nonzero_flow_mask():
      state = run_pass(lava_intent, stack)
      assert state.mask_stack.has_channel("lava_flow_mask")
      assert state.mask_stack.get("lava_flow_mask").sum() > 0
  ```

- [ ] **Step 4:** Run failing tests to confirm they fail before applying fixes.

- [ ] **Step 5:** Implement each stub→real replacement using the codex spec. These are the most complex fixes — allocate ~2–5 hours for Batch 4.

- [ ] **Step 6:** Run extended test suite:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q --timeout=300
  ```

- [ ] **Step 7:** Opus checkpoint — static reading only, no pytest. Verifies stub→real replacements are non-trivial (real algorithm, not just a stub that returns non-zero dummy data).

- [ ] **Step 8:** Commit:
  ```bash
  git commit -m "fix(batch4): simulation completeness — 14 stub→real replacements including lava, snow wind, L-system LOD"
  ```

**Gate T0–T3:** Full test suite green after Batch 4. Callable census clean.
(Note: CodeQL full re-scan is a gate for Batch 11 — it is deferred, not blocking here.)

---

## Chunk 4: Phase 3 Tiers T4–T7 — Batches 5–11 (Orphan Wiring, Quality, S22, CodeQL)

**Rules (same as Chunk 3):**
- Read `ACTIVE_ITEMS_FINAL_2026_05_02.json` — only implement ACTIVE items.
- Opus checkpoints: static reading only, no pytest.
- Commit message format: `fix(batchN): <type> — <N> fixes, <key items>`

---

### Task 3.5: Batch 5 — Orphan System Wiring (10 fixes)

**Key items:** Complete code with zero callers — add callers.

- [ ] **Step 1:** Read Batch 5 entries in `ACTIVE_ITEMS_FINAL_2026_05_02.json`. List all ACTIVE orphaned systems and their missing call sites.

- [ ] **Step 2:** For each orphaned system, trace where its output SHOULD be consumed and add the wiring:
  ```python
  # Example: terrain_morphology templates — 30 dead templates
  # Fix: intent.morphology_specs populated from quality_profile
  # Call site: pass_morphology in terrain_pipeline.py
  ```

- [ ] **Step 3:** Write tests proving the system is now reachable.

- [ ] **Step 4:** Apply fixes.

- [ ] **Step 5:** Run callable census — must reach ZERO (not just decrease):
  ```bash
  python scripts/callable_census_gate.py --strict-zero
  ```
  **Gate:** Callable census exits with code 0. If still non-zero, investigate remaining uncovered callables before proceeding.

- [ ] **Step 6:** Opus checkpoint — static reading only, no pytest. Verifies caller-side wiring added, not just stub fixes.

- [ ] **Step 7:** Commit:
  ```bash
  git commit -m "fix(batch5): orphan system wiring — 10 dead systems now have live callers"
  ```

---

### Task 3.6: Batch 6 — Quality / Density Floors (12 fixes)

**Key items:** Below-AAA output quality — erosion iterations, hot spring ring perturbation, cliff LOD, etc.

- [ ] **Step 1:** Read Batch 6 entries in `ACTIVE_ITEMS_FINAL_2026_05_02.json`.

- [ ] **Step 2:** For each fix, write a quality assertion:
  ```python
  def test_erosion_iterations_aaa_floor():
      """AAA minimum: 10k iterations for visible gully detail"""
      profile = load_quality_profile("production")
      assert profile.erosion_iterations >= 10_000
  ```

- [ ] **Step 3:** Apply fixes.

- [ ] **Step 4:** Run full suite:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q --timeout=120
  ```

- [ ] **Step 5:** Opus checkpoint — static reading only, no pytest. Verifies output quality parameters match AAA references cited in codex.

- [ ] **Step 6:** Commit:
  ```bash
  git commit -m "fix(batch6): quality floors — 12 below-AAA output parameters upgraded"
  ```

---

### Task 3.7: Batches 7–9 — S22 Sweep (67 fixes)

**Key items:** Triplanar UV pinstripes, deepcopy OOM, parallel merge setattr bypass, Rule-1 gate, navmesh OBJ/NMX, decal_density crash, 12 phantom channel reads.

- [ ] **Step 1:** Read Batches 7–9 entries in `ACTIVE_ITEMS_FINAL_2026_05_02.json`. **Group all ACTIVE items by file** — produce a table of `file → [FIX-IDs]` before making any edits. Each file will be edited once, not once per fix.

  Example grouping:
  ```
  terrain_bundle_n.py         → [FIX-7-H8, ...]
  VbTerrainImporter.cs        → [FIX-8-U2, FIX-8-U3, ...]
  _terrain_world.py           → [FIX-9-W1, FIX-9-W2, ...]
  ```

- [ ] **Step 2:** For the deepcopy OOM fix (`terrain_bundle_n.py:439`):
  ```python
  # Before: deepcopy(stack) — 4-8 GB at 4k
  # After: stack.snapshot() — lightweight reference copy
  ```

- [ ] **Step 3:** For phantom channel reads (12 channels) — each must raise `ChannelNotWrittenError` when the channel doesn't exist, not silently return zeros. Verify each affected file:line before editing.

- [ ] **Step 4:** Apply all ACTIVE S22 fixes, editing each file once using the per-file grouping from Step 1.

- [ ] **Step 5:** Run full suite + callable census:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q --timeout=180
  python scripts/callable_census_gate.py --strict-zero
  ```

- [ ] **Step 6:** Opus checkpoint — static reading only, no pytest. Verifies S22 sweep items resolved by file:line against committed code. Specifically confirms: Rule-1 gate not bypassed, `ChannelNotWrittenError` raised correctly, deepcopy removed.

- [ ] **Step 7:** Commit:
  ```bash
  git commit -m "fix(batch7-9): S22 sweep — triplanar UV, deepcopy OOM, phantom channels, Rule-1 gate, navmesh format"
  ```

---

### Task 3.8a: Batch 10 — Opus Deep-Scan P0 + Wiring-Orphan Fixes (23 active)

**Key items (pipeline algorithmic bugs AND wiring orphans):** Waterfall drop/Q disconnected, saliency vantage_weights discarded, JONSWAP fetch_norm unused, DEM valid_mask never applied, billboard/impostor config arrays ignored, AASHTO grade limits + road bed width unused, animation timing orphans, `make_rng` / `tile_rng` dead at 31+ production sites.

- [ ] **Step 1:** Read Batch 10 entries in `ACTIVE_ITEMS_FINAL_2026_05_02.json`. Note that Batch 10 contains BOTH algorithmic bugs (e.g., AASHTO, JONSWAP physics correctness) AND wiring orphans (e.g., vantage_weights discarded, animation timing disconnected) — do not skip orphan fixes.

- [ ] **Step 2:** For `make_rng` / `tile_rng` dead — 31+ production sites use bare `random`:
  ```bash
  grep -rn "random\.random\(\)\|random\.uniform\(" veilbreakers_terrain/handlers/
  ```
  Replace each with `make_rng(seed).random()` or `tile_rng(tile_id, seed)` as appropriate.

- [ ] **Step 3:** For saliency vantage_weights discarded:
  Find where `vantage_weights` is computed → add `stack.set("vantage_weights", vantage_weights, "saliency")` after computation.

- [ ] **Step 4:** Apply all 23 ACTIVE fixes.

- [ ] **Step 5:** Run full suite:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q --timeout=180
  ```

- [ ] **Step 6:** Opus checkpoint — static reading only, no pytest. For algorithmic fixes (JONSWAP, AASHTO), Opus verifies the logic matches the cited physical/engineering reference (same bar as Batch 3 formula verification). For wiring orphans, Opus verifies the channel is now written to stack and will reach its consumer.

- [ ] **Step 7:** Commit:
  ```bash
  git commit -m "fix(batch10): opus deep-scan P0 — 23 algorithmic + wiring-orphan fixes including rng determinism, vantage_weights, JONSWAP fetch_norm"
  ```

---

### Task 3.8b: Batch 11 — CodeQL Active Fixes (15 active)

**All 15 items (FIX-11-3 through FIX-11-17):**
- FIX-11-3: 19 phantom `__all__` exports → ImportError
- FIX-11-4: 3 module-level cyclic import crash risks
- FIX-11-5: 57 production empty-except sites
- FIX-11-6: 122 `sqrt(x²+y²)` → `np.hypot` replacements
- FIX-11-7: file-not-closed
- FIX-11-8: 7 CI permission gaps
- FIX-11-9: 73 unused imports
- FIX-11-10: 143 unused locals + self-assignment
- FIX-11-11: waterfall drop_here + Q disconnected
- FIX-11-12: saliency vantage_weights discarded
- FIX-11-13: JONSWAP fetch_norm unused
- FIX-11-14: DEM valid_mask never applied
- FIX-11-15: billboard/impostor config arrays ignored
- FIX-11-16: AASHTO grade limits + road bed width unused
- FIX-11-17: animation timing orphans + procedural material colors disconnected

- [ ] **Step 1:** For FIX-11-3 (phantom `__all__` exports):
  ```python
  python -c "
  import ast, pathlib
  for f in pathlib.Path('veilbreakers_terrain').rglob('*.py'):
      tree = ast.parse(f.read_text())
      # check __all__ vs actual names defined at module level
  "
  ```

- [ ] **Step 2:** For FIX-11-6 (122 np.hypot replacements):
  ```bash
  grep -rn "np\.sqrt.*\*\*\s*2.*\+.*\*\*\s*2\|math\.sqrt.*\*\*\s*2" \
    veilbreakers_terrain/ --include="*.py" | wc -l
  ```
  Apply replacements in bulk.

- [ ] **Step 3:** For FIX-11-11 through FIX-11-17 (orphaned wiring): Read each cited file:line from the codex and apply the fix. These are wiring fixes — each must add a `stack.set()` or consumer call.

- [ ] **Step 4:** Apply all 15 ACTIVE fixes from `ACTIVE_ITEMS_FINAL_2026_05_02.json`.

- [ ] **Step 5:** Run full suite + callable census:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q --timeout=180
  python scripts/callable_census_gate.py --strict-zero
  ```

- [ ] **Step 6:** Opus checkpoint — static reading only, no pytest. Verifies all 15 CodeQL FIX-11 items are applied. Explicitly confirms: phantom `__all__` exports removed (ImportError risk gone), cyclic imports resolved, `ChannelNotWrittenError` behavior intact.

- [ ] **Step 7:** Confirm CodeQL re-scan gate (requires GitHub Actions to run):
  ```bash
  gh api repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/code-scanning/alerts \
    --paginate -q '.[] | select(.state=="open") | .number' | wc -l
  ```
  **Expected:** Reduced alert count. All 15 FIX-11 categories should show closed alerts.

- [ ] **Step 8:** Commit:
  ```bash
  git commit -m "fix(batch11): CodeQL 15 active fixes — phantom exports, cyclic imports, empty-except, np.hypot, 7 orphaned wiring items"
  ```

**Gate T4–T7:** Full suite green after Batch 11. Callable census zero. CodeQL re-scan shows reduced alerts confirming Batch 11 categories resolved.

---

## Chunk 5: Phase 3 Tiers T8–T10 + Phase 4 — Batches 12–14 + Coastal Ruins Node

---

### Task 3.9: Batches 12–13 — Deep Scan (66 fixes)

**Key items:** Inert erosion passes, water physics, Unity import orphans, `pool_deepening_delta` double-apply, 8 biome grammar features never called, foliage never attached, 10 orphaned channels.

- [ ] **Step 1:** Read Batches 12–13 entries in `ACTIVE_ITEMS_FINAL_2026_05_02.json`. **Critical:** `pool_deepening_delta` double-apply:
  ```bash
  grep -n "pool_deepening_delta" veilbreakers_terrain/handlers/_terrain_world.py
  ```
  Must be applied ONCE only — not in both `pass_erosion` and `pass_integrate_deltas`.

- [ ] **Step 2:** For 8 biome grammar features never called:
  ```bash
  grep -n "def apply_" veilbreakers_terrain/handlers/_biome_grammar.py | head -30
  ```
  Cross-check each against pipeline registration. Add missing wiring calls in `terrain_pipeline.py`.

- [ ] **Step 3:** For foliage never attached in Unity:
  Add `_attach_foliage_renderers()` method to `VbTerrainImporter.cs` that reads the foliage manifest and attaches FoliageRenderer components.

- [ ] **Step 4:** For 10 orphaned channels — each channel written but never read must either have a consumer added (if it should be consumed) OR be removed (if dead data).

- [ ] **Step 5:** Apply all ACTIVE fixes.

- [ ] **Step 6:** Run full suite:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q --timeout=300
  python scripts/callable_census_gate.py --strict-zero
  ```

- [ ] **Step 7:** Opus checkpoint — static reading only, no pytest. Verifies: pool_delta applied exactly once, biome grammar features wired, foliage attached in C# importer.

- [ ] **Step 8:** Commit:
  ```bash
  git commit -m "fix(batch12-13): deep scan — pool_delta double-apply, biome grammar wiring, foliage Unity attachment, orphaned channels"
  ```

---

### Task 3.10: Batch 14 — New Findings (from Phase 1 scan)

- [ ] **Step 1:** Read `docs/aaa-audit/ACTIVE_ITEMS_FINAL_2026_05_02.json` for all Batch 14 ACTIVE items.

- [ ] **Step 2:** Lead with confirmed P1 — **B14-W-1: Add `tidal_zone_label` channel to `detect_tidal_zones()`:**
  ```python
  # veilbreakers_terrain/handlers/coastline.py — after tidal intensity computation
  zones = np.zeros(tidal.shape, dtype=np.uint8)
  zones[tidal < 0.2] = 0   # subtidal
  zones[(tidal >= 0.2) & (tidal < 0.4)] = 1  # intertidal
  zones[(tidal >= 0.4) & (tidal < 0.6)] = 2  # splash
  zones[(tidal >= 0.6) & (tidal < 0.8)] = 3  # spray
  zones[tidal >= 0.8] = 4   # supralittoral
  stack.set("tidal_zone_label", zones, "coastline")
  ```

- [ ] **Step 3:** Write test for B14-W-1:
  ```python
  def test_detect_tidal_zones_emits_five_zones():
      result = detect_tidal_zones(...)
      labels = stack.get("tidal_zone_label")
      assert set(np.unique(labels)).issuperset({0, 1, 2, 3, 4})
  ```

- [ ] **Step 4:** Apply all remaining ACTIVE Batch 14 fixes.

- [ ] **Step 5:** Final full test suite + callable census:
  ```bash
  pytest veilbreakers_terrain/tests/ -x -q --timeout=300
  python scripts/callable_census_gate.py --strict-zero
  ```
  **Expected:** 0 failures, 0 uncovered callables.

- [ ] **Step 6:** Opus final checkpoint — static reading only. Reads changed files across all batches, confirms nothing regressed, confirms callable census is zero.

- [ ] **Step 7:** Commit:
  ```bash
  git commit -m "fix(batch14): new findings — tidal zone label channel, DEM synthetic fallback audit, material coverage guard"
  ```

**Gate Phase 3 Complete:** All batches done. Test suite green. Callable census zero. CodeQL alerts adjudicated.

---

### Task 4.1: Visual Reference Research — Sunken Coastal Ruins

- [ ] **Step 1:** Web-search for reference imagery using these specific targets (from spec §4.1):
  **Real-world:** Tintagel Cornwall cliffs, Dunluce Castle Northern Ireland, Étretat sea arches Normandy, Makapuu tidepools Hawaii, Dunnottar Castle Scotland
  **AAA game:** God of War (2018) coastal zones, AC Odyssey sea-cliff shores, Horizon Forbidden West shoreline vignettes

- [ ] **Step 2:** Download/save 3–5 hero reference images:
  ```bash
  mkdir -p output/aaa_sunken_coastal_ruins/references/
  # Save reference images as ref_01.png through ref_05.png
  ```

- [ ] **Step 3:** Write `output/aaa_sunken_coastal_ruins/references/REFERENCE_NOTES.md`:
  One paragraph per reference covering:
  - Cliff profile (vertical face vs angled escarpment, height estimate)
  - Tidal zone features visible (barnacle bands, tidepool geometry, wet_rock zones)
  - Ruin style (Norman/medieval limestone, Celtic stone, foundation stones partially submerged)
  - Atmospheric character (sea mist, dramatic storm light, spray streaks)
  - Emulation target: storm-carved escarpment 50–120m, eroded sea stacks, submerged limestone ruin bases, deep tide pools, spume-streaked lower cliffs

---

### Task 4.2: Build Script — Heightmap + Coastline + Erosion

**File to create:** `scripts/build_aaa_sunken_coastal_ruins.py`

- [ ] **Step 1:** Scaffold the build script (Caldera v2 pattern):
  ```python
  """VeilBreakers Sunken Coastal Ruins — AAA terrain node.
  Storm-carved sea cliffs, tide pools, eroded rock stacks, submerged ruin foundations.

  Run:
      "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe"
          --background --python scripts/build_aaa_sunken_coastal_ruins.py
  """
  SEED = 0xC0A5_2026
  NODE_ID = "VB_AAA_NODE_SUNKEN_COASTAL_2026_05_02_A"
  TILE_M = 1024.0
  HALF = TILE_M / 2.0
  ```

- [ ] **Step 2:** Implement heightmap generation (spec §4.2 formula — exact values):
  ```python
  def _compose_coastal_heightmap() -> np.ndarray:
      SIZE = 513
      xs = np.linspace(-HALF, HALF, SIZE)
      ys = np.linspace(-HALF, HALF, SIZE)
      XX, YY = np.meshgrid(xs, ys)

      # 1. Heaviside escarpment: k=8.0 (plain scalar — NOT k/TILE_M)
      k = 8.0
      shelf = 0.5 * (1.0 + np.tanh(k * XX / TILE_M))

      # 2. Domain-warped cliff face displacement (3 octaves, base freq=0.004, warp=80m)
      warp_x = _fbm_noise(XX, YY, freq=0.004, octaves=3) * 80.0
      warp_y = _fbm_noise(XX + 1000, YY + 1000, freq=0.004, octaves=3) * 80.0
      displaced = _fbm_noise(XX + warp_x, YY + warp_y, freq=0.006, octaves=5)
      cliff_disp = displaced * 0.15 * shelf  # only on land side

      # 3. Sea floor bathymetry: LINEAR RAMP from 0m at waterline to -30m at tile edge
      #    (NOT shelf-derived; independent linear gradient into ocean)
      sea_floor_depth = -0.3  # normalized (-30m)
      sea_floor = np.where(XX < 0, sea_floor_depth * (-XX / HALF), 0.0)

      # 4. Tide pool depressions (Gaussian bowls at intertidal shelf)
      pools = _place_tide_pools(XX, YY, n_pools=12, r_range=(8, 20), depth_range=(-2, -6))

      # 5. Sea stacks: 3–7 stacks per tile (use rng from SEED for count)
      rng = np.random.default_rng(SEED)
      n_stacks = rng.integers(3, 8)  # 3–7 inclusive
      stacks = _place_sea_stacks(XX, YY, n_stacks=n_stacks, r_range=(8, 25), h_range=(20, 60))

      # 6. Ruin footprints (flat pads at tidal shelf, 40% partially submerged)
      ruins = _place_ruin_pads(XX, YY, n_pads=6, partially_submerged=0.4)

      hmap = shelf + cliff_disp + sea_floor + pools + stacks + ruins
      return np.clip(hmap, 0.0, 1.0).astype(np.float32)
  ```

- [ ] **Step 3:** Wire coastline pipeline (call existing handlers — do NOT reimplement):
  ```python
  def _apply_coastline_pipeline(intent, stack):
      from veilbreakers_terrain.handlers.coastline import (
          pass_coastline, apply_coastal_erosion, compute_wave_energy
      )
      pass_coastline(intent, stack)           # writes tidal scalar + tidal_zone_label uint8
      apply_coastal_erosion(intent, stack)    # cliff-face drainage gullies
      energy = compute_wave_energy(intent, stack)  # JONSWAP wave energy
      stack.set("wave_energy", energy, "coastline")
  ```

- [ ] **Step 4:** Add hydraulic erosion (10k+ iterations as per AAA floor from Batch 6):
  ```python
  def _apply_hydraulic_erosion(hmap):
      from veilbreakers_terrain.handlers._terrain_erosion import apply_hydraulic_erosion
      return apply_hydraulic_erosion(hmap, iterations=12_000, cell_size_m=2.0)
  ```

- [ ] **Step 5:** Test heightmap generation headlessly (no Blender):
  ```bash
  python -c "
  import numpy as np, sys; sys.path.insert(0, '.')
  from scripts.build_aaa_sunken_coastal_ruins import _compose_coastal_heightmap
  h = _compose_coastal_heightmap()
  print(f'shape={h.shape} min={h.min():.3f} max={h.max():.3f} mean={h.mean():.3f}')
  assert h.shape == (513, 513)
  assert 0.0 <= h.min() and h.max() <= 1.0
  print('PASS')
  "
  ```

---

### Task 4.3: Build Script — Scatter + Atmospheric + Splatmap

- [ ] **Step 1:** Add scatter configuration:
  ```python
  SCATTER_CONFIG = {
      "driftwood_log":     {"zone": "intertidal+splash", "count": (40, 80),  "scale": (1.5, 4.0)},
      "wave_worn_boulder": {"zone": "all_tidal",         "count": (60, 120), "scale": (0.8, 3.0)},
      "rock_stack":        {"zone": "splash+spray",      "count": (15, 25),  "scale": (2.0, 8.0)},
      "ruin_column":       {"zone": "subtidal+intertidal","count": (20, 40),  "scale": (1.0, 3.0)},
      "kelp_clump":        {"zone": "subtidal+intertidal","count": (100, 200),"scale": (0.5, 2.0)},
      "barnacle_cluster":  {"zone": "intertidal",        "count": (200, 400),"scale": (0.1, 0.5)},
  }
  ```

- [ ] **Step 2:** Implement tidal-zone-aware scatter placement using `tidal_zone_label` channel (written by B14-W-1 fix in Task 3.10):
  ```python
  def _scatter_by_tidal_zone(stack, config_key, config):
      zone_mask = _zone_mask_from_label(stack, config["zone"])
      return place_scatter_instances(zone_mask, **config)
  ```

- [ ] **Step 3:** Add 5-zone splatmap assembly:
  ```python
  SPLATMAP_ZONES = {
      0: "deep_water",    # subtidal
      1: "wet_rock",      # intertidal
      2: "barnacle_rock", # splash
      3: "spray_stone",   # spray
      4: "ruin_stone",    # supralittoral (ruin pads)
  }
  ```

- [ ] **Step 4:** Add atmospheric volume placement (sea mist, spume, cave fog). Crucially, use heightmap Z for volume pz — NOT `pz=0.0` (old bug from Batch 10 / atmospheric_volumes.py scope):
  ```python
  def _place_atmospheric_volumes(stack, hmap):
      # Sea mist: at cliff base (low elevation, high wave energy)
      # Spume: at splash zone (wave_energy > threshold)
      # Cave fog: in sea cave entrances (concave hull detection)
      # Use hmap values for pz — never pz=0.0
  ```

- [ ] **Step 5:** Wire `apply_coastal_erosion()` for cliff-face drainage gullies and verify
  `compute_wave_energy()` (JONSWAP) result is used for foam + wet_rock placement in splatmap.

---

### Task 4.4: Hunyuan3D-2 Prop Generation

**File:** `scripts/build_aaa_sunken_coastal_ruins.py` (continued)

- [ ] **Step 1:** Add `gradio_client` install guard (required per spec — must be in build script):
  ```python
  def _ensure_gradio_client():
      try:
          import gradio_client  # noqa: F401
      except ImportError:
          import subprocess, sys
          subprocess.check_call([sys.executable, "-m", "pip", "install", "gradio_client"])
  ```

- [ ] **Step 2:** Verify `HUGGINGFACE_TOKEN` env var at startup (required for HF Space access):
  ```python
  import os
  HF_TOKEN = os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN")
  if not HF_TOKEN:
      raise RuntimeError(
          "HUGGINGFACE_TOKEN env var required for Hunyuan3D-2 via HF Space. "
          "Set it before running this script."
      )
  ```

- [ ] **Step 3:** Implement prop generation using ExternalAssetProvider with `/generation_all` endpoint:
  ```python
  from veilbreakers_terrain.providers.hunyuan3d2_provider import Hunyuan3D2Provider

  PROPS = [
      ("dead_tree_coastal",    3, "bleached salt-weathered dead tree, coastal, no leaves, twisted branches"),
      ("boulder_wave_worn",    5, "wave-worn coastal boulder, wet basalt, barnacle patches, tidemark staining"),
      ("log_driftwood",        4, "driftwood log, grey-bleached, waterlogged, coastal beach, kelp draped"),
      ("rock_stack_eroded",    6, "eroded sea stack, layered sedimentary rock strata, spray-wet, coastal"),
      ("ruin_column_fragment", 3, "ancient ruin column fragment, worn limestone, algae-stained, half-submerged"),
      ("kelp_clump",           4, "kelp seaweed clump, dark olive green, translucent edges, wet sheen"),
  ]

  def _generate_props():
      _ensure_gradio_client()
      provider = Hunyuan3D2Provider()  # uses HF Space via gradio_client, NOT local server
      results = {}
      for name, variants, prompt in PROPS:
          results[name] = []
          for i in range(variants):
              asset = provider.generate(
                  caption=f"{prompt}, variant {i+1}",
                  seed=SEED + hash(name) + i,
                  texture=True,  # uses /generation_all endpoint for shape + PBR texture
              )
              results[name].append(asset)
      return results
  ```

- [ ] **Step 4:** Build LOD chain for each prop using Blender decimate modifier:
  ```python
  def _build_prop_lod_chain(obj, prop_name):
      """LOD0=full, LOD1=0.3, LOD2=0.1, LOD3=billboard impostor (>400m)"""
      for lod_factor, lod_name in [(1.0, "LOD0"), (0.3, "LOD1"), (0.1, "LOD2")]:
          lod_obj = obj.copy()
          mod = lod_obj.modifiers.new("Decimate", "DECIMATE")
          mod.ratio = lod_factor
          with bpy.context.temp_override(active_object=lod_obj):
              bpy.ops.object.modifier_apply(modifier="Decimate")
          lod_obj.name = f"{prop_name}_{lod_name}"
      # LOD3: camera-facing billboard impostor plane
      _create_billboard_impostor(obj, f"{prop_name}_LOD3")
  ```

- [ ] **Step 5:** Add CC0 bake fallback (if Hunyuan texture quality is rejected in Task 4.6 Opus review):
  ```python
  def _bake_cc0_texture_fallback(obj, material_name: str, output_path: str):
      """Download matching CC0 PBR set from ambientCG and bake onto UV-unwrapped mesh.
      Only used if Hunyuan3D-2 texture quality is rejected by Opus visual review.
      """
      import urllib.request
      cc0_url = f"https://ambientcg.com/api/v2?id={material_name}&method=GET&format=PNG-VAR1"
      # Download PNG-VAR1 PBR set, bake onto UV-unwrapped mesh in Blender headless
  ```

- [ ] **Step 6:** Generate `hunyuan_props_proof.png` — mosaic of all props with textures:
  Set up 6×4 grid scene with each prop variant, EEVEE NEXT, 16 TAA, white studio backdrop.

---

### Task 4.5: Blender Scene + Renders

- [ ] **Step 1:** Implement GPU probe + render safety (required per spec §4.4):
  ```python
  def _gpu_cycles_available() -> bool:
      import bpy
      prefs = bpy.context.preferences.addons["cycles"].preferences
      prefs.refresh_devices()
      return any(d.use for d in prefs.devices if d.type in ("CUDA", "OPTIX", "HIP", "METAL"))

  def _set_render_engine():
      if _gpu_cycles_available():
          bpy.context.scene.render.engine = "CYCLES"
          bpy.context.scene.cycles.samples = 48  # hero renders: 48 spp
      else:
          bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
          bpy.context.scene.eevee.taa_render_samples = 16  # fallback: 16 TAA
  ```

- [ ] **Step 2:** Enforce particle / grass count ceiling (required per spec §4.4):
  ```python
  MAX_PARTICLES_PER_COLLECTION = 3_500
  # Before rendering, verify all particle systems are within ceiling
  for ps in scene.particles:
      assert ps.count <= MAX_PARTICLES_PER_COLLECTION
  ```

- [ ] **Step 3:** Assemble full Blender scene:
  - Apply heightmap as displacement on a grid plane
  - Apply splatmap as vertex color / material
  - Place scatter instances (Hunyuan props + procedural meshes)
  - Add atmospheric volumes (HDRP-compatible volume objects)
  - Dramatic coastal lighting (key from NE, fill from SW, atmospheric haze)

- [ ] **Step 4:** Render all outputs — 3 hero renders + 4 orbit frames max:
  ```python
  RENDERS = [
      ("render_hero",          camera_hero_pos,        camera_hero_target),
      ("render_waterline",     camera_waterline_pos,   camera_waterline_target),
      ("render_cave_entrance", camera_cave_pos,        camera_cave_target),
  ]
  ORBIT_ANGLES = [0, 90, 180, 270]  # N/E/S/W — 4 frames max (not 8)
  ```

- [ ] **Step 5:** Generate CROSS_SECTIONS.png (matplotlib, no Blender needed):
  ```python
  def _render_cross_sections(hmap, splatmap, water_mask, output_path):
      import matplotlib.pyplot as plt
      fig, axes = plt.subplots(1, 3, figsize=(18, 6))
      axes[0].imshow(hmap, cmap="terrain"); axes[0].set_title("Heightmap")
      axes[1].imshow(splatmap); axes[1].set_title("Splatmap (5-zone)")
      axes[2].imshow(water_mask, cmap="Blues"); axes[2].set_title("Water / Tidal Mask")
      plt.savefig(output_path, dpi=150, bbox_inches="tight")
  ```

- [ ] **Step 6:** Implement `_push_renders_to_github()` (required per spec §4.4 — do NOT rely on CI artifact upload):
  ```python
  def _push_renders_to_github(output_dir: str, branch: str = "codex/aaa-terrain-golden-semantics"):
      """Stage all render outputs and commit + push to GitHub.
      Requires user confirmation (see Task 4.6).
      """
      import subprocess
      subprocess.run(["git", "add", output_dir], check=True)
      subprocess.run(["git", "commit", "-m", f"feat: Sunken Coastal Ruins renders — {NODE_ID}"], check=True)
      subprocess.run(["git", "push", "origin", branch], check=True)
  ```

- [ ] **Step 7:** Generate BUILD_SUMMARY.json with pass results and metrics.

- [ ] **Step 8:** Commit build script:
  ```bash
  git add scripts/build_aaa_sunken_coastal_ruins.py
  git commit -m "feat: Sunken Coastal Ruins build script — heightmap, coastline, scatter, Hunyuan props, renders"
  ```

---

### Task 4.6: Opus AAA Visual Analysis + GitHub Push

- [ ] **Step 1:** Run the build script and confirm all renders are produced:
  ```bash
  "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
    --background --python scripts/build_aaa_sunken_coastal_ruins.py
  ```

- [ ] **Step 2:** Dispatch Opus agent with all rendered images as input. Opus evaluates 5 dimensions (all must score ≥ B+ before push):
  1. KCD2 / TW3 / God of War coastal reference quality bar
  2. Splatmap correctness (5-zone tidal transitions, no material bleeding)
  3. Water believability (foam placement, tidemark, wet_rock wetness, JONSWAP wave energy visible)
  4. Prop integration (scale, weathering coherence, scatter density matches real coastal imagery)
  5. Silhouette readability (cliff edge, ruin shapes, sea stacks readable against sky)

- [ ] **Step 3:** Re-render fallback policy (per spec §4.5 — one re-render attempt, then escalate):
  - If any dimension < B+:
    - Identify specific visual failure
    - Patch build script to fix it
    - Run ONE re-render iteration
    - Re-run Opus analysis on second render
    - If second render STILL fails → **escalate as blocking hold for manual review — do not push**
  - Maximum: 2 total render attempts before escalation (not 2 additional re-renders)

- [ ] **Step 4:** Once all 5 dimensions ≥ B+ — Opus issues AAA PASS verdict.

- [ ] **Step 5:** Push to GitHub — **requires user confirmation before executing** (irreversible external action):
  ```bash
  # Confirm with user before this step
  git push origin codex/aaa-terrain-golden-semantics
  ```

- [ ] **Step 6:** Update memory files:
  - `project_audit_status` memory → note all batches complete, Sunken Coastal Ruins node added
  - `project_master_implementation_guide` → note Sunken Coastal Ruins node with Opus AAA PASS verdict

**DONE.** All audit items resolved. New terrain node Opus-approved. Outputs committed and pushed.

---

## Quick Reference — Key Commands

```bash
# Full test suite
pytest veilbreakers_terrain/tests/ -x -q --timeout=300

# Callable census
python scripts/callable_census_gate.py --strict-zero

# Build coastal ruins node (Blender headless)
"C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
  --background --python scripts/build_aaa_sunken_coastal_ruins.py

# Check CodeQL alerts (requires gh auth)
gh api repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/code-scanning/alerts \
  --paginate -q '.[] | [.number,.rule.id,.state] | @tsv'

# Git status
git status --short

# Verify no deleted-file orphans
grep -rn "terrain_scatter_altitude_safety" veilbreakers_terrain/ --include="*.py"
```

## Key File Map

```
docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md           ← Fix specifications (source of truth)
docs/aaa-audit/ACTIVE_ITEMS_FINAL_2026_05_02.json       ← Phase 2 work list (Phase 3 source of truth)
docs/aaa-audit/BATCH14_FINDINGS.md                      ← Phase 1 output
docs/aaa-audit/REFUTED_2026_05_02.md                    ← Phase 2 refuted items
docs/aaa-audit/GRADES_VERIFIED.csv                      ← Updated with Batch 14 grades
veilbreakers_terrain/handlers/coastline.py              ← Core coastal pass (add tidal_zone_label)
veilbreakers_terrain/providers/hunyuan3d2_provider.py   ← HF Space prop generator
scripts/build_aaa_sunken_coastal_ruins.py               ← Phase 4 build script (CREATE)
output/aaa_sunken_coastal_ruins/                        ← All renders + outputs (CREATE)
output/aaa_sunken_coastal_ruins/references/             ← Visual reference images (CREATE)
```
