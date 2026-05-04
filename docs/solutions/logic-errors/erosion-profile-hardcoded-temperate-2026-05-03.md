---
title: "erosion_profile Hardcoded to temperate in environment.py Ignores Biome Climate"
date: 2026-05-03
category: docs/solutions/logic-errors
module: environment
problem_type: logic_error
component: tooling
symptoms:
  - Tundra terrain erodes at 0.70 erodibility (temperate) instead of 0.40
  - Desert terrain erodes at 0.70 erodibility (temperate) instead of 1.01
  - Every non-temperate biome produces climatically incorrect erosion character
  - No error or warning raised; output looks plausible but is quantitatively wrong
root_cause: config_error
resolution_type: code_fix
severity: high
tags: [erosion-profile, composition-hints, climate, erodibility, biome, environment]
---

# erosion_profile Hardcoded to "temperate" in environment.py Ignores Biome Climate

## Problem

Two sites in `environment.py` that set `erosion_profile` never consulted `composition_hints["erosion_profile"]` or `composition_hints["climate"]`. Both fell back to `"temperate"` regardless of biome, bypassing the erodibility table (tundra=0.40, temperate=0.70, arid/desert=1.01, tropical=0.85) for every non-temperate intent. Tundra terrain was over-eroded; desert terrain was under-eroded.

## Symptoms

- Tundra terrain erodes at 0.70 erodibility (temperate) instead of 0.40
- Desert terrain erodes at 0.70 erodibility (temperate) instead of 1.01
- Every non-temperate biome produces climatically incorrect erosion character
- No error or warning raised; output looks plausible but is quantitatively wrong

## What Didn't Work

The controller-params site read:
```python
controller_params["erosion_profile"] = (
    "temperate" if erosion == "hydraulic" else "arid" if erosion == "thermal" else "temperate"
)
```
This appeared to be intentional logic branching on erosion type. The pipeline-builder site used `params.get("erosion_profile", "temperate")` — a reasonable-looking safe fallback — but `params` never received the value because `composition_hints` was never consulted upstream. Neither site raised any error; the system ran correctly, just with the wrong erodibility profile.

Note: a closely related but distinct bug (FIX-13-24) hardcodes `climate_zone` in `terrain_unity_export.py`'s `_build_unity_import_descriptor()` — that is a Unity import-side issue in a different file. This fix addresses the Python erosion-pass side only.

## Solution

Both sites in `environment.py` now consult `composition_hints` before falling back.

**Controller params site** (`environment.py` lines 2121–2126):
```python
if erosion in ("hydraulic", "thermal", "both"):
    controller_params["erosion_profile"] = (
        composition_hints.get("erosion_profile")
        or composition_hints.get("climate")
        or ("arid" if erosion == "thermal" else "temperate")
    )
```

**Pipeline builder / TerrainIntentState construction site** (`environment.py` lines 3061–3066):
```python
erosion_profile=str(
    params.get("erosion_profile")
    or composition_hints.get("erosion_profile")
    or composition_hints.get("climate")
    or "temperate"
),
```

The lookup chain: explicit param override → `composition_hints["erosion_profile"]` (direct key) → `composition_hints["climate"]` (proxy; "tundra", "desert", "arid" etc. are valid erodibility table keys) → erosion-type structural fallback → `"temperate"` as last resort only.

## Why This Works

The erodibility table in `_terrain_erosion.py` keys profiles by string name. `composition_hints["climate"]` is already set to these same strings by the biome grammar layer when building a generation intent. Inserting the `composition_hints` lookups ahead of the hardcoded fallback at both sites means a caller who sets `composition_hints={"climate": "tundra"}` gets erodibility 0.40 rather than 0.70 without any other change at the call site.

## Prevention

- **`composition_hints` is the source-of-truth for biome character.** Any parameter affecting a simulation constant (erodibility, roughness scale, precipitation rate) must be derived from `composition_hints` unless explicitly overridden. Document this rule in the pipeline contribution guide.
- **Parametrized regression test.** For each known climate string ("tundra", "desert", "tropical", "temperate"), assert that `TerrainIntentState.erosion_profile` produced by `_execute_terrain_pipeline` matches the expected profile — not always "temperate".
- **Lint for hardcoded profile literals.** Flag `"temperate"` in assignment positions; require a `# noqa: hardcoded-profile` annotation with reviewer sign-off when intentional.

## Related Issues

- Related bug (Unity export side): FIX-13-24 in `docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md`
- Related audit: `docs/aaa-audit/deep_dive_2026_04_27/F3_intent_contract_audit.md` §erosion_iterations
- Related audit: `docs/aaa-audit/deep_dive_2026_04_27/K1_biome_intent_wiring.md`
- Commit: 285463d (`feat/vegetation-scatter-water-contracts`)
