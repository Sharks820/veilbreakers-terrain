# VeilBreakers Terrain Test Suite — Quality Audit

**Audit Date:** 2026-04-26
**Auditor:** Claude (gsd-code-reviewer, deep mode)
**Scope:** `veilbreakers_terrain/tests/` — all discoverable test files
**Total tests scanned:** ~591 across 60+ files

---

## Contents

1. [STALE TESTS](#1-stale-tests)
2. [ORPHANED TESTS](#2-orphaned-tests)
3. [MODULE IDENTITY RISKS](#3-module-identity-risks)
4. [SOFT TESTS](#4-soft-tests)
5. [DUPLICATE / REDUNDANT TESTS](#5-duplicate--redundant-tests)
6. [P0 / P1 / P2 ACTION PLAN](#6-action-plan)

---

## 1. STALE TESTS

Stale tests are tests where the name, assertion count, or tested API no longer matches the current state of the codebase.

---

### ST-01: `test_all_14_biomes_present` asserts `len == 16`

**File:** `test_terrain_materials.py:119`

The test method is named `test_all_14_biomes_present` but its body asserts `len(BIOME_PALETTES_V2) == 16`. The biome count was expanded from 14 to 16 and the assertion was updated, but the test name was not. A developer reading this test will trust the name and infer the count is 14.

```python
def test_all_14_biomes_present(self):
    assert len(BIOME_PALETTES_V2) == 16   # name says 14, assertion says 16
```

**Fix:** Rename to `test_all_16_biomes_present`.

---

### ST-02: `test_v1_has_14_biomes` asserts `len == 16`

**File:** `test_terrain_materials.py:335`

Same stale-name pattern for the V1 palette class. The V1 palette also has 16 biomes now.

```python
def test_v1_has_14_biomes(self):
    assert len(BIOME_PALETTES) == 16   # name says 14, assertion says 16
```

**Fix:** Rename to `test_v1_has_16_biomes`.

---

### ST-03: `test_has_eleven_terrain_types` — hard-coded preset count

**File:** `test_terrain_noise.py:217`

```python
def test_has_eleven_terrain_types():
    assert len(TERRAIN_PRESETS) == 11
```

No comment explains what the 11 presets are or why 11 is the right count. Any addition of a new terrain preset will silently fail this test, which then becomes misleading. Unlike ST-01/ST-02 where the name is wrong, here the name accurately describes the current assertion — but the count is frozen with no known upper bound intent.

**Fix:** Either replace the count-exact assertion with a minimum bound (`assert len(TERRAIN_PRESETS) >= 11`) if the catalog is intended to grow, or add a comment enumerating all 11 expected names so it functions as a registry contract test.

---

### ST-04: `test_add_cliff_ledges_scales_with_span` — assertion range allows failure cases

**File:** `test_terrain_cliffs.py:217`

A comment in the test body says "span is ~35m => count should be 3" but the assertion is `assert 1 <= len(cliff.ledges) <= 3`. This means the test passes even if the ledge-generation logic produces only 1 ledge on a 35m span. The assertion does not enforce the documented expected count.

**Fix:** If the invariant is "~1 ledge per 10m of span", tighten to `assert len(cliff.ledges) == 3` or `assert len(cliff.ledges) >= 3` with a comment on the spacing formula.

---

## 2. ORPHANED TESTS

Orphaned tests are tests that have lost their connection to the production pipeline — they may call removed or renamed functions, reference non-existent channels, or test code paths that have been superseded.

---

### OR-01: `test_visual_qa_headless_handlers_report_not_applied` uses `blender_addon.handlers` import path

**File:** `test_visual_testing_readiness.py:128`

```python
from blender_addon.handlers import terrain_visual_qa as vqa
```

This import succeeds only because `conftest.py` installs a `_BlenderAddonHandlersAliasFinder` meta_path redirect. The `veilbreakers_terrain.handlers.terrain_visual_qa` module is the canonical source. When the alias is eventually removed (Phase 50 migration completion), this test will fail with `ModuleNotFoundError`.

The same file also uses the canonical path correctly in `test_visual_qa_module_import_is_stable_without_reloading_bpy` (line 325), creating an inconsistency within the same file.

**Fix:** Replace all `from blender_addon.handlers import terrain_visual_qa as vqa` with `from veilbreakers_terrain.handlers import terrain_visual_qa as vqa`.

---

### OR-02: `test_wiring_bundle_a_default_pipeline_runs` — `blender_addon` import for `_terrain_world`

**File:** `test_terrain_wiring_integration.py:108`

```python
from blender_addon.handlers import _terrain_world as world_mod
```

Used to monkeypatch `apply_hydraulic_erosion_masks` and `apply_thermal_erosion_masks`. Since `_terrain_world` is NOT in the eagerly-loaded set in `conftest.py`, this import may produce a different module object than what the pipeline uses internally if the pipeline has already cached `veilbreakers_terrain.handlers._terrain_world`. The monkeypatch would then patch a shadow copy and the test would NOT intercept the real erosion calls.

**Fix:** Use `import veilbreakers_terrain.handlers._terrain_world as world_mod` to ensure the monkeypatch targets the same object that the pipeline holds.

---

### OR-03: `test_terrain_composition.py` — top-level `blender_addon` import

**File:** `test_terrain_composition.py:20`

```python
from blender_addon.handlers import terrain_masks
```

This is a module-level import (not inside a test function), so any isolation the alias provides is bypassed. `terrain_masks` is not in the eagerly-loaded set. If another test in the same session has already imported `veilbreakers_terrain.handlers.terrain_masks` under the canonical key, this import may produce a second instance. The `compute_base_masks` call on line 50 passes `stack` to mutate it in-place; if it targets the wrong instance this produces silent non-mutation.

**Fix:** Change to `from veilbreakers_terrain.handlers import terrain_masks`.

---

### OR-04: Removed `TestGenerateRoadPath` class comment in `test_terrain_noise.py`

**File:** `test_terrain_noise.py:692`

Lines 692–697 contain a comment block documenting the removal of `TestGenerateRoadPath` and its tests when `generate_road_path` was deleted. This is dead documentation that will mislead anyone searching for why road path tests were dropped.

**Fix:** Delete the comment block entirely. If the intent is to preserve rationale, move it to a `CHANGELOG.md` or commit message instead.

---

## 3. MODULE IDENTITY RISKS

Module identity risks occur when the same underlying module is imported via two different path strings in the same process. Python caches modules by key in `sys.modules`; two different string keys produce two different module objects, causing `isinstance` checks, `is` comparisons, and `monkeypatch.setattr` to operate on the wrong instance.

The `conftest.py` alias finder at line 119 maps `blender_addon.handlers.X` → `veilbreakers_terrain.handlers.X` for the eagerly-loaded set only. Modules NOT in the eagerly-loaded set risk dual instantiation.

**Eagerly loaded (safe):** `terrain_semantics`, `terrain_pipeline`, `terrain_reference_locks`, `animation_gaits`, `animation_environment`, `environment`

**NOT eagerly loaded (at risk):** `_terrain_erosion`, `_terrain_noise`, `_terrain_world`, `terrain_masks`, `terrain_materials_v2`, `environment_scatter`, and all other handlers

---

### MI-01: Mixed import of `environment` module in `test_aaa_water_scatter.py`

**File:** `test_aaa_water_scatter.py:344–347`

```python
from blender_addon.handlers import _terrain_noise as terrain_noise      # line 344
from blender_addon.handlers import environment as _environment_mod      # line 345 (alias path)
# ...
from veilbreakers_terrain.handlers.environment import handle_create_water  # line 347 (canonical path)
```

`environment` IS in the eagerly-loaded set, so lines 345 and 347 produce the same object — this is safe. However, `_terrain_noise` on line 344 is NOT eagerly loaded. If `veilbreakers_terrain.handlers._terrain_noise` has already been imported by any prior test, lines 344 and the production call chain will use different module objects. Any `monkeypatch.setattr` targeting `terrain_noise` from this test file will patch the alias copy, not the live one, and silently not intercept.

**Fix:** Change line 344 to:
```python
from veilbreakers_terrain.handlers import _terrain_noise as terrain_noise
```

---

### MI-02: Mixed import of `_terrain_erosion` in `test_p2_subtle_fixes.py`

**File:** `test_p2_subtle_fixes.py:41–43`

```python
from blender_addon.handlers import _terrain_erosion          # line 41 — NOT eagerly loaded
from veilbreakers_terrain.handlers._terrain_erosion import (  # line 43
    apply_hydraulic_erosion_masks,
)
```

`_terrain_erosion` is not in the eagerly-loaded set. Depending on import order, these two lines may produce different module instances. The `inspect.getsource(apply_hydraulic_erosion_masks)` call on line 46 will use the function from the canonical import (line 43), which is correct — but the `_terrain_erosion` module object on line 41 is unused except as a side-effect of import. If any test later uses `blender_addon.handlers._terrain_erosion` for monkeypatching, it will patch the alias copy.

**Fix:** Remove the unused `from blender_addon.handlers import _terrain_erosion` import on line 41 entirely. The test only needs the canonical function from line 43.

---

### MI-03: `_terrain_noise` alias import in `test_aaa_terrain_vegetation.py`

**File:** `test_aaa_terrain_vegetation.py:192`

```python
from blender_addon.handlers import _terrain_noise as terrain_noise
```

`_terrain_noise` is not eagerly loaded. This is used to access noise generation functions. If production code has already imported the canonical `veilbreakers_terrain.handlers._terrain_noise`, this produces a shadow copy. Unlike MI-01/MI-02, there is no corresponding canonical import in the same file to detect the divergence.

**Fix:** Change to `from veilbreakers_terrain.handlers import _terrain_noise as terrain_noise`.

---

### MI-04: `environment_scatter` alias import in `test_aaa_terrain_vegetation.py`

**File:** `test_aaa_terrain_vegetation.py:193`

```python
from blender_addon.handlers import environment_scatter as scatter_mod
```

`environment_scatter` is not eagerly loaded. Same risk class as MI-03.

**Fix:** Change to `from veilbreakers_terrain.handlers import environment_scatter as scatter_mod`.

---

### MI-05: `terrain_materials_v2` alias import in `test_terrain_cliffs.py`

**File:** `test_terrain_cliffs.py:649`

```python
from blender_addon.handlers import terrain_materials_v2
```

Used inside `test_height_blend_weights_active_in_materials` to call `inspect.getsource`. The source inspection will succeed (Python's inspect finds the file regardless of module identity), but the module object may diverge if used elsewhere for attribute access.

**Fix:** Change to `from veilbreakers_terrain.handlers import terrain_materials_v2`.

---

## 4. SOFT TESTS

Soft tests are assertions that pass even when the code under test is doing something wrong. They provide false confidence and mask regressions.

---

### SO-01: `test_wiring_bundle_a_default_pipeline_runs` — wrong status string literal (BUG)

**File:** `test_terrain_wiring_integration.py:148`

```python
assert r.status in ("ok", "warnings"), f"{r.pass_name}: {r.status} {r.issues}"
```

The valid `PassResult.status` values throughout the codebase are `"ok"`, `"warning"` (singular), and `"failed"`. The string `"warnings"` (plural) never appears as a valid status. This means:

- If the pipeline returns `"warning"`, the assertion FAILS — the test rejects valid production output.
- If the pipeline always returns `"ok"` on this path, the wrong string is never exercised and the bug hides.

**This is the highest-priority finding in this audit.** It causes test failures against correct pipeline behavior.

**Fix:**
```python
assert r.status in ("ok", "warning"), f"{r.pass_name}: {r.status} {r.issues}"
```

---

### SO-02: Channel presence checks without value validation

**File:** `test_terrain_wiring_integration.py:152–156`

```python
assert stack.slope is not None
assert stack.curvature is not None
assert stack.erosion_amount is not None
assert stack.deposition_amount is not None
```

These only verify that the attributes were assigned. A pass that sets `stack.slope = np.zeros_like(height)` would satisfy all four assertions even if slope computation is completely broken. The test comment on line 9 explicitly acknowledges this is a "smoke test", which is acceptable for a wiring test — but the soft assertions should be documented as intentional, or at minimum one statistical sanity check should be added (e.g., `assert stack.slope.max() > 0.0` for a terrain with non-zero relief).

**Fix (minimal):** Add one non-trivial value check per populated channel:
```python
assert stack.slope.max() > 0.0, "slope all-zero on non-flat terrain"
assert stack.curvature is not None  # shape check is sufficient here
```

---

### SO-03: `test_talus_conversion_no_error` — smoke-only assertion

**File:** `test_p7_thermal_consolidation.py:53`

```python
def test_talus_conversion_no_error():
    dem = _make_test_dem(4)
    result = advanced_thermal(dem, iterations=1, talus_angle=0.5)
    assert result is not None
```

This test verifies only that no exception is raised. The legacy talus conversion from raw angle (0.5) to degrees was the specific bug being addressed. The test should verify the output is a valid DEM.

**Fix:**
```python
def test_talus_conversion_no_error():
    dem = _make_test_dem(4)
    result = advanced_thermal(dem, iterations=1, talus_angle=0.5)
    arr = np.array(result)
    assert arr.shape == dem.shape
    assert np.all(np.isfinite(arr))
```

---

### SO-04: `test_structure_pass_returns_list`, `test_ground_cover_pass_returns_list`, `test_debris_pass_returns_list`

**File:** `test_aaa_terrain_vegetation.py:558–568`

Three consecutive tests with identical structure, each asserting only return type:

```python
def test_structure_pass_returns_list(self):
    assert isinstance(result, list)

def test_ground_cover_pass_returns_list(self):
    assert isinstance(result, list)

def test_debris_pass_returns_list(self):
    assert isinstance(result, list)
```

An empty list passes all three. A list with `None` entries passes all three. A list with dicts missing required keys passes all three.

**Fix:** Assert at minimum `len(result) > 0` and that items contain expected keys (e.g., `"position"`, `"vegetation_type"`) — or parametrize these as a single contract test.

---

### SO-05: `test_water_creation_does_not_raise`

**File:** `test_aaa_water_scatter.py:492`

```python
class TestWaterMaterialProperties:
    def test_water_creation_does_not_raise(self, ...):
        # ... setup ...
        # asserts nothing except no exception
```

The test name explicitly acknowledges it is a smoke-only test. For a module at the heart of the water rendering pipeline, this is insufficient.

**Fix:** At minimum assert that the returned dict contains `"status": "ok"` and the expected water surface keys.

---

### SO-06: `test_water_result_complete_keys` — only checks key presence

**File:** `test_aaa_water_scatter.py:501`

```python
def test_water_result_complete_keys(self):
    # checks that expected_keys is a subset of result.keys()
    # does NOT check key values
```

A handler that returns `{k: None for k in expected_keys}` passes this test.

**Fix:** Add value checks: `result["status"] == "ok"`, `isinstance(result["surface"], np.ndarray)`, etc.

---

### SO-07: `test_pass_water_variants_populates_wetness_and_surface`

**File:** `test_terrain_water_vegetation_depth.py:569`

```python
assert state.mask_stack.wetness is not None
```

The wetness channel being non-None is necessary but not sufficient. The water pass is supposed to populate physically meaningful wetness values in [0, 1]. A pass that sets `mask_stack.wetness = np.zeros(...)` satisfies this assertion.

**Fix:**
```python
assert state.mask_stack.wetness is not None
assert state.mask_stack.wetness.min() >= 0.0
assert state.mask_stack.wetness.max() <= 1.0
assert state.mask_stack.wetness.mean() > 0.01, "wetness appears to be all-zero"
```

---

### SO-08: `test_pass_validation_full_returns_pass_result` — status in any of three values

**File:** `test_terrain_validation.py:629`

```python
assert result.status in ("ok", "warning", "failed")
```

This assertion passes for any valid `PassResult`, including one that reports `"failed"`. A test that succeeds for any of the three possible statuses provides no diagnostic signal about what the validation actually computed.

**Fix:** If the full validation on a known-good terrain is expected to produce `"ok"`, assert exactly that. If `"warning"` is also acceptable, document why.

---

### SO-09: Multiple `assert len(...) > 0` patterns in `test_environment_scatter_handlers.py`

**File:** `test_environment_scatter_handlers.py:198, 231, 343, 366, 393, 475, 620`

Seven locations assert only that a list or dict is non-empty. These pass for a single-element result that could still have wrong structure or wrong content.

**Fix (representative):**
```python
# Before
assert len(placements) > 0

# After
assert len(placements) > 5, "Expected meaningful scatter density, got barely any"
for p in placements:
    assert "position" in p
    assert p["vegetation_type"] in VALID_VEGETATION_TYPES
```

---

### SO-10: `test_phase14_wave1.py` — `assert result is not None` after glacial/coastline delta

**File:** `test_phase14_wave1.py:66, 77`

```python
assert result.glacial_delta is not None, "glacial_delta must be set even with no glacier_paths"
# and
assert result.coastline_delta is not None
```

Both also check `.shape`, which is slightly better. But the absence of any content check means a delta of all-zeros passes. The whole point of this test is to verify the morphology delta was actually computed.

**Fix:** Add `assert float(np.abs(result.glacial_delta).max()) > 0.0` — or at minimum document in a comment that zero-delta is physically valid for the test input.

---

## 5. DUPLICATE / REDUNDANT TESTS

---

### DU-01: Large bpy stub builder duplicated across two test files

**File A:** `test_aaa_water_scatter.py` — `_build_full_bpy_stubs()` function (~150 lines)
**File B:** `test_aaa_terrain_vegetation.py` — `_make_bpy_stubs()` function (~similar size)

Both functions construct a comprehensive fake `bpy` namespace with identical structure (cameras, objects, materials, nodes, context, render settings). The two implementations will drift as Blender mocking needs evolve, creating maintenance overhead and inconsistent test behavior.

**Fix:** Extract to a shared `conftest.py` fixture or a `tests/fixtures/bpy_stubs.py` helper module. Both files import it via `from tests.fixtures.bpy_stubs import make_bpy_stubs`.

---

### DU-02: `test_structure_pass_returns_list`, `test_ground_cover_pass_returns_list`, `test_debris_pass_returns_list` — identical structure

**File:** `test_aaa_terrain_vegetation.py:558–568`

Covered in SO-04 as a softness issue. From a duplication standpoint, three tests with identical assertion bodies (`assert isinstance(result, list)`) should be parametrized:

```python
@pytest.mark.parametrize("pass_name", ["structure", "ground_cover", "debris"])
def test_scatter_pass_returns_list(self, pass_name):
    result = self._run_pass(pass_name)
    assert isinstance(result, list)
    assert len(result) > 0
```

---

### DU-03: Path-traversal security check duplicated across test files

**File A:** `test_visual_testing_readiness.py:285–299` — `test_capture_rejects_filepath_outside_allowed_root`
**File B:** `test_terrain_water_vegetation_depth.py` — similar path rejection test

Both tests call `handle_visual_qa_capture_screenshot("../../etc/passwd", ...)` and assert `result["error"] == "filepath_outside_allowed_root"`. The fixture setup differs slightly (one calls `_ensure_allowed_root`, one does not). This is acceptable test duplication for security contracts — document as intentional rather than removing.

---

### DU-04: `auto_frame_terrain(0.0) == 10.0` zero-extent behavior tested twice

**File:** `test_visual_testing_readiness.py:111` and `test_terrain_visual_qa.py` (if present)

Minor — zero-extent edge case is a single-line check and low maintenance cost. No action required.

---

## 6. ACTION PLAN

### P0 — Correct immediately (test produces wrong pass/fail signal)

| ID | File | Line | Action |
|----|------|------|--------|
| SO-01 | `test_terrain_wiring_integration.py` | 148 | Change `"warnings"` → `"warning"` — this test currently rejects valid pipeline output |
| MI-02 | `test_p2_subtle_fixes.py` | 41 | Remove unused `from blender_addon.handlers import _terrain_erosion` — this import is dead and creates dual-instance risk |

### P1 — Fix before next major refactor (latent failure risk)

| ID | File | Lines | Action |
|----|------|-------|--------|
| MI-01 | `test_aaa_water_scatter.py` | 344 | Change `_terrain_noise` import to canonical path |
| MI-03 | `test_aaa_terrain_vegetation.py` | 192 | Change `_terrain_noise` import to canonical path |
| MI-04 | `test_aaa_terrain_vegetation.py` | 193 | Change `environment_scatter` import to canonical path |
| MI-05 | `test_terrain_cliffs.py` | 649 | Change `terrain_materials_v2` import to canonical path |
| OR-02 | `test_terrain_wiring_integration.py` | 108 | Change `_terrain_world` import to canonical path; monkeypatch currently patches shadow copy |
| OR-03 | `test_terrain_composition.py` | 20 | Change top-level `terrain_masks` import to canonical path |
| OR-01 | `test_visual_testing_readiness.py` | 128 | Change `terrain_visual_qa` import to canonical path |
| ST-01 | `test_terrain_materials.py` | 119 | Rename method: `test_all_14_biomes_present` → `test_all_16_biomes_present` |
| ST-02 | `test_terrain_materials.py` | 335 | Rename method: `test_v1_has_14_biomes` → `test_v1_has_16_biomes` |
| SO-08 | `test_terrain_validation.py` | 629 | Tighten `status in (...)` to assert the expected specific status for the known-good input |

### P2 — Address in next test quality sweep (correctness signals, no false negatives today)

| ID | File | Lines | Action |
|----|------|-------|--------|
| ST-03 | `test_terrain_noise.py` | 217 | Either use `>= 11` or enumerate expected preset names |
| ST-04 | `test_terrain_cliffs.py` | 217 | Tighten ledge count assertion to match documented invariant |
| SO-02 | `test_terrain_wiring_integration.py` | 152–156 | Add one non-trivial value check per populated channel |
| SO-03 | `test_p7_thermal_consolidation.py` | 53 | Assert shape + finite values, not just non-None |
| SO-04 | `test_aaa_terrain_vegetation.py` | 558–568 | Assert non-empty list + required key presence; parametrize |
| SO-05 | `test_aaa_water_scatter.py` | 492 | Assert `status == "ok"` + expected keys |
| SO-06 | `test_aaa_water_scatter.py` | 501 | Assert key values, not just key presence |
| SO-07 | `test_terrain_water_vegetation_depth.py` | 569 | Assert wetness in [0,1] + non-trivial mean |
| SO-09 | `test_environment_scatter_handlers.py` | 198, 231, 343, 366, 393, 475, 620 | Raise count threshold and check item structure |
| SO-10 | `test_phase14_wave1.py` | 66, 77 | Assert max(abs(delta)) > 0, or document why zero-delta is valid |
| DU-01 | `test_aaa_water_scatter.py` / `test_aaa_terrain_vegetation.py` | — | Extract bpy stub builders to shared `conftest.py` fixture |
| DU-02 | `test_aaa_terrain_vegetation.py` | 558–568 | Parametrize the three identical-structure scatter pass tests |
| OR-04 | `test_terrain_noise.py` | 692–697 | Delete dead comment block about removed `TestGenerateRoadPath` |

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Stale tests (wrong name or frozen count) | 4 |
| Orphaned / alias-fragile tests | 4 |
| Module identity risks | 5 |
| Soft tests (no meaningful signal) | 10 |
| Duplicate / redundant | 3 |
| **Total findings** | **26** |

| Severity | Count |
|----------|-------|
| P0 (breaks pass/fail today) | 2 |
| P1 (latent failure on migration or refactor) | 10 |
| P2 (false confidence, no immediate breakage) | 14 |

---

_Audit completed: 2026-04-26_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
