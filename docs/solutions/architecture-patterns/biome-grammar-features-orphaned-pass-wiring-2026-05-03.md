---
title: "Biome Grammar Feature Functions Must Be Wired via register_*_pass() into the Pipeline"
date: 2026-05-03
category: docs/solutions/architecture-patterns
module: biome_grammar
problem_type: architecture_pattern
component: tooling
severity: high
applies_when:
  - Adding new surface feature functions to a biome grammar module
  - Creating a new pass in any pipeline module
  - Reviewing whether all callable functions in a module are reachable at runtime
tags: [biome-grammar, pass-registration, pipeline-wiring, dead-code, register-default-passes]
---

# Biome Grammar Feature Functions Must Be Wired via register_*_pass() into the Pipeline

## Context

Eight fully-implemented biome surface feature functions in `_biome_grammar.py` — `apply_periglacial_patterns`, `apply_desert_pavement`, `apply_tafoni_weathering`, `apply_reef_platform`, `apply_hot_spring_features`, `apply_landslide_scars`, `compute_spring_line_mask`, `apply_geological_folds` — had no wiring into the terrain pipeline. `register_biome_surface_features_pass()` existed but was never called from `register_default_passes()`, and `"biome_surface_features"` was never inserted into the default pass sequence. Every pipeline run silently skipped all biome micro-features.

The gap was not obvious: each function was importable, syntactically correct, and produced valid numpy output. Code review and CI could not detect the omission because there was no mechanism to enforce that a registered module's callables must appear in a pipeline pass body.

## Guidance

**Every `register_*_pass()` function defined in the codebase must be called from `register_default_passes()` or explicitly marked as opt-in with a comment in `register_default_passes()` explaining why it is excluded.**

**Every pass that produces output channels must unconditionally write those channels on every execution path** — even when no processing applies, write a zero array. This is required by `PassDefinition`'s `produces_channels` contract and prevents `PassContractError` from being raised when the channel is absent.

**Implementation pattern for a new biome pass** (`_biome_grammar.py` + `terrain_pipeline.py`):

1. Write the dispatcher pass function — one function that reads `composition_hints` and routes to feature sub-functions:
```python
def pass_biome_surface_features(
    stack: TerrainMaskStack,
    intent: TerrainIntentState,
    params: dict,
) -> None:
    composition_hints = intent.composition_hints or {}
    biome = composition_hints.get("biome", "")
    delta = np.zeros_like(stack.height)

    if biome == "tundra":
        delta += apply_periglacial_patterns(stack, intent, params)
    elif biome == "desert":
        delta += apply_desert_pavement(stack, intent, params)
    # ... route all features ...

    # Always write — zero array satisfies PassDefinition contract when no features apply
    stack.set("biome_surface_delta", delta)
```

2. Write the registration function — declares the `PassDefinition`:
```python
def register_biome_surface_features_pass() -> None:
    from .terrain_pipeline import TerrainPassController
    TerrainPassController.register(PassDefinition(
        pass_name="biome_surface_features",
        fn=pass_biome_surface_features,
        produces_channels=("biome_surface_delta",),
        requires_channels=("height",),
        description="Dispatch biome-specific surface micro-features",
    ))
```

3. Call registration from `register_default_passes()` in `terrain_pipeline.py`:
```python
from ._biome_grammar import register_biome_surface_features_pass
register_biome_surface_features_pass()
```

4. Insert the pass into the default pass sequence at the correct position:
```python
# After pass_glacial, before feature carving
pass_sequence.insert(composite_idx, "biome_surface_features")
composite_idx += 1
```

5. Add the output channel to `_DELTA_CHANNELS` in `terrain_delta_integrator.py` if the delta should be applied to `stack.height`:
```python
_DELTA_CHANNELS: Tuple[str, ...] = (
    ...
    "biome_surface_delta",
)
```

6. Export both the pass function and registration function from `__all__` in the module.

## Why This Matters

Dead feature functions have no runtime signal — no test failure, no warning, no metric anomaly. The code base looked feature-complete while every pipeline run silently produced terrain with no biome-specific micro-features: no periglacial frost-heave patterning on tundra, no pavement on desert, no fringing reef on coastal zones. The defect was invisible until a wiring audit explicitly counted call sites per public function.

The gap compounds across future development: new biome functions added following the same pattern will also be dead unless a registration discipline is enforced. A function that exists and is never called in a production path is a P0 omission that only audit finds.

## When to Apply

- When adding any new surface feature function to a biome grammar or procedural module
- When creating a new `register_*_pass()` function anywhere in the pipeline
- When code-reviewing a module that has grown new `apply_*` or `compute_*` public functions without corresponding test or pipeline call sites
- When validating pass registration completeness during audit sweeps

## Examples

**Before — function implemented but dead:**
```python
# _biome_grammar.py — function exists, zero callers in production
def apply_periglacial_patterns(stack, intent, params):
    ...  # full implementation

# terrain_pipeline.py — registration function exists but never called
def register_biome_surface_features_pass():
    ...  # never invoked from register_default_passes()
```

**After — function reachable and output integrated:**
```python
# terrain_pipeline.py — register_default_passes() now calls registration
def register_default_passes() -> None:
    ...
    from ._biome_grammar import register_biome_surface_features_pass
    register_biome_surface_features_pass()

# terrain_delta_integrator.py — delta channel integrated into stack.height
_DELTA_CHANNELS: Tuple[str, ...] = (
    ...
    "biome_surface_delta",
)
```

## Related

- Commit: 285463d (`feat/vegetation-scatter-water-contracts`)
- `PassDefinition overrides=()` pattern: `memory/feedback_channel_ownership_pattern.md` — secondary channel writers must declare `overrides=()` or `ChannelOwnershipError` silently drops the bundle
- Orphan audit: `docs/WIRING_ORPHAN_AUDIT_2026_04_20.md` — lists these same functions as "register when biome-type pipeline is extended"
- Historical: `docs/aaa-audit/deep_dive_2026_04_16/G2_bugs_conventions_gaps.md` §4.3
