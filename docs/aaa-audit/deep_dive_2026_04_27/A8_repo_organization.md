# A8 Audit: Repository Organization, Dead Code, and Orphan Detection
**Date:** 2026-04-27  
**Scope:** Full repo — 137 files audited, all imports verified, all dependencies mapped

---

## CRITICAL FINDINGS

### [P0] Scope Contamination — procedural_meshes.py
**File:** `veilbreakers_terrain/procedural_meshes.py` (22,769 lines)  
**Finding:** Dark-fantasy dungeon/furniture/equipment mesh library with 80+ generators — furniture, weapons, armor, monsters, dark fantasy props, consumables, crafting items. Not terrain-specific. Violates Phase 50 extraction contract, inflates module, slows pip install.  
**Consumers:** `_bridge_mesh.py`, `_mesh_bridge.py`, `_terrain_depth.py`, `environment.py`  
**Action:** Move to `veilbreakers-mcp` or new `veilbreakers-assets` repo  
**Effort:** 4–6 hours

---

## HIGH-SEVERITY FINDINGS

### [P1] Duplicate Mesh Bridge Files — Overlapping Scope
**Files:** `_bridge_mesh.py` (963 LOC) vs `_mesh_bridge.py` (1,556 LOC)  
**Finding:** `_bridge_mesh.py` is the toolkit-side bridge generation (20 functions); `_mesh_bridge.py` is the handler-side asset mapping table (80+ generators from procedural_meshes). Naming is confusing; scope overlaps after P0 relocation.  
**Action:** Consolidate into `environment_scatter.py` or relocate both with procedural_meshes.py  
**Effort:** 2–3 hours

---

## MEDIUM-SEVERITY FINDINGS

### [P2] 134 Stale Channel Name References
**Finding:** Two deprecated channel names are still referenced across the codebase:

| Channel | Count | Correct Name | Key Files |
|---------|-------|-------------|-----------|
| `water_surface` | 89 | `water_surface_mask` | terrain_waterfalls.py, light_integration.py, environment.py, test files |
| `heightmap` | 45 | `height` | terrain_stochastic_shader.py, _water_network.py, test files |

**Impact:** Maintenance burden; future schema changes will fail silently in files not yet migrated.  
**Action:** Global find/replace both names; run full test suite after  
**Effort:** 3–4 hours

---

## LOW-PRIORITY FINDINGS

### [P3] Stale Build Scripts (5 files)
Move to `scripts/deprecated/`:
- `build_terrain_aaa_node_v3.py` — superseded by v4
- `build_terrain_aaa_node_v4.py` — superseded by v5
- `build_terrain_aaa_node_v5.py` — superseded by v6 (current)
- `open_aaa_node_v1.py` — targets deleted v1 .blend file
- `_wave10_grades_update.py` — one-time utility from Wave 10 audit  
**Effort:** 0.5 hours

### [P4] Material Tier Documentation Missing
**Files:** `terrain_materials.py` (24 func), `terrain_materials_v2.py` (13 func), `terrain_materials_ext.py` (4 func)  
**Finding:** ALL THREE ARE INTENTIONAL AND ACTIVE (Bundle B design). v1 = legacy biome-keyed palette; v2 = modern slope/altitude/curvature rules (preferred); ext = validation extensions for v2. Not duplicates — a tier system. Needs a README section explaining this.  
**Action:** Add README section + mark v1 as legacy in its docstring  
**Effort:** 0.5 hours

### [P5] Audit-Only Modules Have No Tags
- `terrain_legacy_bug_fixes.py`: documentation/verification deliverable, audits 4 `np.clip()` sites; NOT called at runtime
- `terrain_iteration_metrics.py`: observability/telemetry only; not wired to COMMAND_HANDLERS  
**Action:** Add `# AUDITOR_MODULE` and `# OBSERVABILITY_ONLY` tags at top of each file  
**Effort:** 0.25 hours

### [P6] Test Resource Leaks Unaudited — Effort: 2–3 hours
### [P7] No CI check for circular imports — Add `python -c "import veilbreakers_terrain.handlers"` to CI — Effort: 0.5 hours
### [P8] `scripts/deprecated/_deprecated_build_scene_v2.py` — verify no git refs, then delete — Effort: 0.25 hours
### [P9] Missing `__all__` exports in handler modules — Effort: 2–3 hours

---

## CLEAN FINDINGS (No Action Needed)

| Item | Status |
|------|--------|
| `terrain_checkpoints.py` + `_ext.py` | Intentional Bundle D design |
| `_water_network.py` + `_ext.py` | Intentional core + extensions |
| `autonomous_loop.py` | 2 handlers correctly wired |
| `blender_capability_bridge.py` | 18 handlers correctly wired |
| `terrain_addon_health.py` | 3 handlers correctly wired |
| `terrain_hot_reload.py` | 3 handlers correctly wired |
| `terrain_live_preview.py` | 5 handlers correctly wired |
| `terrain_viewport_sync.py` | 3 handlers correctly wired |
| Circular imports | None detected |
| Test imports | 135 test files, all resolve cleanly |
| `__init__.py` surface | Minimal, appropriate public API |
| Bundle files (J, K, L, N, O) | All referenced and wired |

---

## STATISTICS

| Metric | Count |
|--------|-------|
| Active handler files | 105 |
| Test files | 135 |
| Total files audited | 137 |
| Stale build scripts | 5 |
| Scope-contaminated files | 1 (procedural_meshes.py) |
| Files with overlapping scope | 2 (_bridge_mesh, _mesh_bridge) |
| Stale channel references | 134 (89 + 45) |
| Audit-only modules (untagged) | 2 |

---

## RECOMMENDED IMPLEMENTATION ORDER

**Phase 1 — Quick Wins (1–2 days)**
1. Move v3/v4/v5/open_v1/_wave10 scripts to `scripts/deprecated/`
2. Add AUDITOR_MODULE/OBSERVABILITY_ONLY tags
3. Add README section on material tiers
4. Add CI compile check for all handler .py files

**Phase 2 — Channel Names (1–2 days)**
1. Global find/replace `"water_surface"` → `"water_surface_mask"` (89 sites)
2. Global find/replace `"heightmap"` → `"height"` (45 sites)
3. Run full test suite + verify external API contracts

**Phase 3 — Structural (3–5 days)**
1. Move `procedural_meshes.py` to `veilbreakers-mcp`
2. Update imports in `_bridge_mesh.py`, `_mesh_bridge.py`, `_terrain_depth.py`, `environment.py`
3. Consolidate mesh bridge files
4. Run full integration suite + update Phase 50 docs
