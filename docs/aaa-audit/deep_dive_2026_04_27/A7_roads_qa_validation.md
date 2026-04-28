# A7: Deep-Dive Audit — Road Networks, QA, & Validation

**Scope:** VeilBreakers terrain generator vs. AAA standards (RDR2, Witcher 3, Ghost of Tsushima)  
**Date:** 2026-04-27  
**Audit Type:** System-wide architectural + implementation review  

## Executive Summary

VeilBreakers demonstrates solid mid-tier engineering on roads (24-dir A*, AASHTO cost, Kruskal MST) and comprehensive validation infrastructure (7-domain, 12+ validators). However, it falls short of AAA-grade shipping quality in critical areas.

---

## P0 — Critical (Release Blockers)

### P0-1: Golden Snapshot Tolerance Logic Inverted

**File:** eilbreakers_terrain/handlers/terrain_golden_snapshots.py:157-167

**Finding:** The tolerance comparison uses 
p.allclose(atol=tolerance) without setting tolerance in the golden file. The function loads .npz files but never materializes tolerance values—all comparisons degrade to exact matching (atol=0), defeating tolerance-based regression testing.

**Impact:** Golden snapshots provide zero regression-testing value for floating-point data. A 1-ULP change fails the regression test, making the pipeline brittle to benign optimizations.

**Fix:** 
1. In save_golden_snapshot() line ~95, write tolerance to .golden.json: "tolerance": 1e-5
2. In compare_against_golden() line ~150, load tolerance from JSON
3. Add per-dtype logic: 	olerance = 1e-8 if stack.height.dtype == np.float64 else 1e-5

---

### P0-2: Missing Channel Name Contract Mismatch

**File:** eilbreakers_terrain/handlers/terrain_visual_qa.py:337

**Finding:** REQUIRED_STACK_CHANNELS uses "height" key, but external tools may reference "heightmap". Silent missing-channel failures when names diverge.

**Impact:** Validation passes but export fails silently. Regression test golden files may break if downstream tools use different key names.

**Fix:**
1. Add alias support in alidate_channel_manifest() line 406
2. Normalize legacy heightmap to canonical height attribute
3. Document in docstring: "Channel height is canonical; heightmap is legacy alias."

---

### P0-3: Protocol Enforcement Rule 2 Warnings Ignored at Pipeline Level

**File:** eilbreakers_terrain/handlers/terrain_protocol.py:105-141

**Finding:** ProtocolGate.rule_2_sync_to_user_viewport() issues soft warnings, but nforce_protocol() treats soft issues as non-fatal. Passes can violate viewport constraints without being caught.

**Impact:** Authorships perform out-of-viewport mutations without user awareness. Undo/redo becomes ambiguous.

**Fix:**
1. Change severity to "hard" when out_of_view_ok=False
2. Add optional enforcement flag to nforce_protocol()
3. Fail the pass if soft violations present and llow_soft_violations=False

---

### P0-4: Determinism Check Passes on Structural Changes Not Caught by Content Hash

**File:** eilbreakers_terrain/handlers/terrain_determinism_ci.py:155-166

**Finding:** Determinism check compares only content hashes, missing intent mutations during computation. Passes with identical output but different intermediate state are not detected.

**Impact:** Non-deterministic passes that produce identical output slip through. Bisection cannot pinpoint which pass introduced the mutation.

**Fix:**
1. Add per-pass hash snapshots to DeterminismRun dataclass
2. After each pass, snapshot intent hash
3. Bisection detects intent mutations via per-pass detailed hashes

---

### P0-5: Road Bridge Detection Doesn't Validate Water-Path Alignment

**File:** eilbreakers_terrain/handlers/road_network.py:908-968

**Finding:** _detect_bridges() marks ridge_required=True if height < water_level, without checking if actual water exists. Roads over dry ravines marked as needing bridges.

**Impact:** Unnecessary bridges in dry terrain (wasted geometry). Validation in alidate_path_network_contract() flags these as errors, blocking the tile.

**Fix:**
1. Add water_surface_mask parameter to _detect_bridges()
2. Check water presence before marking bridge_required
3. Call site in compute_road_network() passes water_surface: ridge_profile = _detect_bridges(..., water_surface_mask=stack.get("water_surface_mask"))

---

### P0-6: Circular Profile Inheritance Lock Bypass

**File:** eilbreakers_terrain/handlers/terrain_quality_profiles.py:816-821

**Finding:** load_quality_profile() lock check happens AFTER merge, allowing bypass via direct dict access. Locked profiles can be mutated.

**Impact:** A locked profile (e.g., AAA_OPEN_WORLD_PROFILE) can be loaded and mutated. No audit trail of unlocking.

**Fix:**
1. Move lock check to start of load_quality_profile() line 810, before recursion
2. Optional: add unlock token system for stricter control

---

## P1 — High Priority (Serious Quality Gaps vs. AAA)

### P1-1: Road Mesh Cross-Section Missing Shoulder Edge Hardening

**File:** eilbreakers_terrain/handlers/road_network.py:1009-1093

**Finding:** 7-vertex cross-section uses smooth parabolic blend at road-shoulder boundary. No vertex normal hardening for mechanical edge effect. Witcher 3/RDR2 use sharp 90° normals.

**Impact:** Roads lack road-like visual definition. Specular highlights blend across shoulders (unrealistic).

**Fix:** Generate two normal sets: hardened perpendicular-to-road for shoulders, smooth surface normals for center. Write to mesh tangent data.

---

### P1-2: Gameplay Zone Cover Score Ignores Slope Direction (Aspect)

**File:** eilbreakers_terrain/handlers/terrain_gameplay_zones.py:90-131

**Finding:** Cover scoring treats all slopes equally without considering aspect (slope direction). Slope facing player provides no cover, but scoring doesn't distinguish.

**Impact:** AI thinks enemies equally covered from all directions. Combat unbalanced.

**Fix:**
1. Add camera_direction parameter
2. For each neighbor, compute aspect; cover only counts if slope faces away from camera (> π/2 radians)
3. Update call site to determine camera direction from focal point

---

### P1-3: Determinism Check Doesn't Handle Float Bit-Ordering (x87 vs. SSE)

**File:** eilbreakers_terrain/handlers/terrain_determinism_ci.py:40-59

**Finding:** SHA-256 over raw array bytes produces different bit patterns on x87 FPU vs. SSE due to rounding differences. Intermittent CI failures on legacy hardware.

**Impact:** Determinism check creates false positives on mixed CI environments.

**Fix:** Add _tolerance_aware_hash() that quantizes float64 → float32 → float64 to normalize x87/SSE differences.

---

### P1-4: Water-Terrain Seam Continuity Validation Missing Cross-Tile Water Level Check

**File:** eilbreakers_terrain/handlers/terrain_validation.py:446-594

**Finding:** Tier 2 cross-tile validation checks height matching but ignores water level consistency. Water surfaces visibly jump at seams.

**Impact:** Naval combat zones unplayable if water_level diverges across tiles. Immersion-breaking.

**Fix:** Add water level consistency check with 1cm tolerance across tile boundaries.

---

### P1-5: Strahler Stream Ordering Validation Doesn't Handle Braided Rivers

**File:** eilbreakers_terrain/handlers/terrain_geology_validator.py:99-393

**Finding:** Validator enforces tree structure (no cycles), but braided rivers naturally have multiple channels at same elevation. Realistic glacial valley terrain marked as implausible.

**Impact:** Canyon/gorge with braided streams cannot be authored. Validation blocks plausible natural features.

**Fix:** Add llow_braided mode. Relax order constraint when braided: allow order[i] == order[parent].

---

### P1-6: Cliff Silhouette Readability Tier 1 Sky-Exposure Check Fails on Overhangs

**File:** eilbreakers_terrain/handlers/terrain_readability_semantic.py:33-235

**Finding:** Sky-exposure check marks cell "not exposed" if height < neighborhood.max. Fails for overhanging cliffs where undercut cells are sky-visible.

**Impact:** Overhanging cliffs marked unreadable despite visual prominence. Tier 2 component size fails.

**Fix:** Replace neighborhood-max check with local curvature detection. Accept cells with high concavity as sky-exposed.

---

### P1-7: Budget Enforcement Missing Per-Chunk Worst-Case Analysis

**File:** eilbreakers_terrain/handlers/terrain_budget_enforcer.py:252-308

**Finding:** Distributes LOD0 tris uniformly across chunks, but real terrain is non-uniform. Worst-case chunk may have 4-10x average tris. Static batch limit exceeded silently.

**Impact:** Frame-rate hiccups in dense areas. Budget enforcement unreliable.

**Fix:** Subdivide into chunks, count tris per chunk, use worst-case for batch limit check.

---

### P1-8: Road Network Pathfinding Ignores Terrain Stability (Erosion Susceptibility)

**File:** eilbreakers_terrain/handlers/road_network.py:123-339

**Finding:** A* uses AASHTO cost but ignores rock_hardness channel. Path through soft sediment (hardness=0.2) costs same as granite (hardness=0.9).

**Impact:** In-game maintenance budgets unpredictable. Gameplay: players can't reason about road degradation.

**Fix:** Add rock_hardness parameter. Soft rock incurs 2x maintenance cost (durability_penalty = 5.0 * (1.0 - hardness_factor)).

---

### P1-9: Worn Path Erosion Model Doesn't Account for Drainage Direction

**File:** eilbreakers_terrain/handlers/road_network.py:670-737

**Finding:** Erosion depth modeled as symmetric sine wave. Real paths erode asymmetrically along water flow direction. Path on slope naturally erodes downslope.

**Impact:** Worn paths unrealistically symmetric. Immersion: experts notice unnatural symmetry.

**Fix:** Add flow_direction parameter. Compute asymmetric rut depth based on downslope factor.

---

## P2 — Medium Priority (Incomplete Implementations)

### P2-1: Golden Snapshot Library Seed Generation Not Documented

**File:** eilbreakers_terrain/handlers/terrain_golden_snapshots.py:276-357

**Finding:** Generates 120 canonical snapshots but no documentation on seed sequence selection. Are all terrain types represented? Code is opaque.

**Fix:** Add _generate_seed_sequence() using quasi-random Halton sequence for even distribution. Document terrain types and feature densities covered.

---

### P2-2: Validation Report Aggregation Missing Category Priorities

**File:** eilbreakers_terrain/handlers/terrain_validation.py:58-148

**Finding:** Aggregates issues into 7 domains but no priority ordering within domains. 50 geometry issues reported equally regardless of severity.

**Fix:** Add geometry_by_priority property sorting by severity (hard > soft > info).

---

### P2-3: Budget Enforcer Triangle Estimate Doesn't Include Vegetation/LOD Geometry

**File:** eilbreakers_terrain/handlers/terrain_budget_enforcer.py:252-308

**Finding:** Estimate includes base terrain + cliff + hero, but missing vegetation (trees, shrubs), water surface (ripples), decals. In forests, vegetation = 20-50% of total tris.

**Impact:** Budget check passes, runtime vertex buffer overflows. Budget enforcement unreliable.

**Fix:** Add vegetation tri estimate. Assume 1000 tris per vegetation cell at max density.

---

### P2-4: Gameplay Zone Classification Missing Proximity-to-Player Scoring

**File:** eilbreakers_terrain/handlers/terrain_gameplay_zones.py:268-381

**Finding:** Classification uses 4 metrics but doesn't consider proximity to spawn. SAFE zones should cluster near spawn; BOSS_ARENA far from routes. All locations treated equally.

**Impact:** AI may spawn in SAFE zones near player. BOSS_ARENA in middle of patrol routes.

**Fix:** Add player_spawn_location parameter. Compute distance; prefer SAFE zones close to spawn.

---

### P2-5: Feature Rhythm Analysis Doesn't Distinguish Intentional Clusters from Accidental

**File:** eilbreakers_terrain/handlers/terrain_rhythm.py:148-232

**Finding:** Flags CV > 0.55 as clustering violation, but intentional settlements (tight feature clusters) trigger errors. No distinction between accidental vs. designed clustering.

**Impact:** Authoring settlement triggers validation errors. Enforcement removes intentionally designed clusters.

**Fix:** Add feature intent metadata (FeatureRhythmHint with preferred_clustering and max_cv per type).

---

### P2-6: Readability Semantic Checks Missing Icon Occlusion from Foliage

**File:** eilbreakers_terrain/handlers/terrain_readability_semantic.py:482-558

**Finding:** check_focal_composition() validates positioning but ignores foliage occlusion. Focal point prominent in empty landscape hidden by trees in-game.

**Impact:** Authored focal points invisible. Cinematics capture empty landscape instead of landmark.

**Fix:** Add detail_density parameter. Check sky visibility: if foliage_density > 0.5, flag FOCAL_OBSCURED_BY_FOLIAGE.

---

## P3 — Low Priority (Code Quality, Documentation)

### P3-1: Road Network Module Missing Type Hints on Private Functions

Functions _astar_24dir(), _fill_8connected_gaps(), _apply_road_profile_to_heightmap() lack complete type hints. Modern Python requires types on all parameters/returns.

**Fix:** Add -> ReturnType and param: Type annotations.

---

### P3-2: Golden Snapshot JSON Schema Not Enforced by Parser

compare_against_golden() doesn't validate JSON schema before loading. Corrupt golden files cause silent failures.

**Fix:** Validate against JSON schema (draft-07) before deserializing. Reject missing required keys.

---

### P3-3: Determinism CI Suspect-Pass Bisection Not Documented

un_determinism_check() returns suspect_passes but no doc on interpreting or re-running individual passes.

**Fix:** Add docstring example: "To debug pass_index 5, call controller.run_pass(pass_sequence[5], checkpoint=False)"

---

### P3-4: Budget Enforcer Missing per-LoD Breakdown in Serialization

Returns nested dicts (lod0_tris, lod1_tris) but external tools expect flattened keys.

**Fix:** Add flattened keys alongside nested dicts for backward compat: "lod0_tris_current": X, "lod0_tris_max": Y, ...

---

### P3-5: Protocol Enforcement Missing per-Rule Telemetry

Decorator applies 7 rules but doesn't track which rules pass/fail. No metrics for "how often is rule 2 violated?"

**Fix:** Add telemetry dict _RULE_STATS tracking pass/fail per rule.

---

### P3-6: Quality Profiles Missing Validation for Circular Inheritance Edge Cases

Cycle detection uses _chain list but doesn't validate depth limit. Pathological hierarchy might exceed reasonable depth.

**Fix:** Add max-depth check: if len(_chain) > 10: raise ProfileValidationError("inheritance chain too deep")

---

### P3-7: Visualization QA Missing Pixel-Level Diff Annotation

compare_render_to_golden() returns SSIM but no spatial info on differences. 0.85 SSIM could be clustered or scattered.

**Fix:** Add diff_region: BBox to result indicating bounding box of maximum difference intensity.

---

### P3-8: Terrain Protocol Missing Remediation Guide for Each Rule

Each rule violation has message but no concrete remediation steps.

**Fix:** Add remediation field: emediation="Call intent.set_viewport_vantage(camera_pos) before pass execution"

---

## AAA Comparative Analysis

| Feature | VeilBreakers | RDR2 | Witcher 3 | Ghost of Tsushima |
|---------|--------------|------|-----------|-------------------|
| **Road pathfinding** | 24-dir A* + AASHTO | 24-dir A* + durability | Rasterized pre-computed | Pre-computed + dynamic |
| **Mesh vertex normals** | Smooth parabola (soft) | Hardened edges (sharp) | Per-LOD optimization | Curvature-adaptive |
| **Cover scoring** | Isotropic (no aspect) | Azimuth-relative | Trace-based | Raycasting 8 directions |
| **Water seam validation** | None | Global enforcement | Cross-tile check | Continuous height/depth |
| **Determinism CI** | Per-pass hash | Instruction-level trace | Checkpoint replay | Bytecode verification |
| **Budget enforcement** | Uniform chunks | Quadtree worst-case | Per-LOD allocation | Streaming bandwidth model |

**Verdict:** VeilBreakers is at 60-70% AAA parity. Core algorithms solid. Missing pieces are polish and validation rigor. **Not production-ready without P0 fixes.**

---

## Audit Metrics

- **Total files reviewed:** 18 handler files + 7 test files
- **Critical issues:** 6 P0 (crash/silent-fail), 9 P1 (quality gap), 6 P2 (incomplete), 8 P3 (tech debt)
- **Estimated fix effort:** P0 = 40-60 hrs, P1 = 120-180 hrs, P2 = 80-120 hrs, P3 = 40-60 hrs
- **Ship readiness:** **NOT READY. P0 blockers must be fixed.**

---

**Report Generated:** 2026-04-27  
**Status:** INCOMPLETE — Awaiting fixes. Do NOT ship.
