# D8 Audit: Determinism & RNG Seeding
**Date:** 2026-04-27

---

## hash() calls used as RNG seeds (PYTHONHASHSEED hazard)

Only two production code sites call Python's built-in `hash()` and use the result as an actual RNG seed or filename discriminator. All other `hash(` hits in the codebase are calls to methods named `compute_hash`, `intent_hash`, `_wang_hash`, etc. — not Python's builtin — and are therefore safe.

| File:line | What's hashed | Impact |
|---|---|---|
| `handlers/terrain_cliffs.py:2368` | `hash(cliff.cliff_id)` — string cliff id → mesh_seed | **HIGH**: `cliff_id` is a string; `hash()` is PYTHONHASHSEED-randomized. `mesh_seed` is passed directly to mesh generation. Same cliff produces a different mesh shape in every new Python process. |
| `handlers/asset_generation.py:755` | `hash(full_prompt)` — prompt string → output filename stem | **MEDIUM**: determines the output file name, not geometry. File will have a different name each process run, breaking caching and reproducible build pipelines. |

---

## global random state mutations (np.random.seed / random.seed)

One production and one test-only site found. No `random.seed()` (stdlib) calls exist anywhere in the codebase.

| File:line | Call | Impact |
|---|---|---|
| `tests/test_coverage_gaps.py:420` | `np.random.seed(42)` | **LOW (test-only)**: mutates the global numpy legacy RNG state during a test. Can contaminate other tests running in the same process if they use `np.random` directly rather than a `RandomState`/`Generator` instance. Not a production-pass problem. |

No `np.random.seed()` or `random.seed()` calls exist in any production handler.

---

## np.random.default_rng(None) calls (non-deterministic)

None found. Every `default_rng(...)` call in production passes an explicit integer seed. No `default_rng(None)` or bare `default_rng()` calls exist in the handlers directory.

| File:line | Impact |
|---|---|
| *(none)* | — |

---

## Additional seeding concerns not in the original checklist

### np.random.RandomState usage in production handlers

`RandomState` is the legacy numpy RNG (pre-1.17). It is deterministic when seeded, but its use alongside the new `default_rng` API is inconsistent and makes future parallel-safe migration harder. These are the production (non-test) sites:

| File:line | Seed source | Notes |
|---|---|---|
| `handlers/_terrain_noise.py:79` | `seed & 0x7FFFFFFF` | `_build_permutation_table` — seeded from external int, safe |
| `handlers/_terrain_noise.py:1865` | `seed & 0x7FFFFFFF` | Road/moisture map generation — seeded from external int, safe |
| `handlers/_terrain_noise.py:2271` | `seed & 0x7FFFFFFF` | Another noise octave — seeded from external int, safe |
| `handlers/_biome_grammar.py:595` | external `seed` arg | periglacial relief — seeded from external int, safe |
| `handlers/_biome_grammar.py:732` | external `seed` arg | desert pavement — safe |
| `handlers/_biome_grammar.py:866` | external `seed` arg | sand dunes — safe |
| `handlers/_biome_grammar.py:983` | external `seed` arg | rock scatter — safe |
| `handlers/_biome_grammar.py:1151` | external `seed` arg | moraines — safe |
| `handlers/_biome_grammar.py:1315` | external `seed` arg | polygonal cracks — safe |
| `handlers/_biome_grammar.py:1499` | external `seed` arg | permafrost — safe |
| `handlers/_biome_grammar.py:1760` | external `seed` arg | saline flat — safe |
| `handlers/terrain_advanced.py:1009` | external `seed` arg (brush "noise" op) | safe if caller provides deterministic seed; caller chain is `apply_brush_operation` — need to verify caller seed provenance |
| `handlers/terrain_advanced.py:1654` | `rng.randint(0, 2**31-1)` where `rng` is an external `random.Random(seed)` instance | safe — derived from caller-provided seed |
| `handlers/terrain_advanced.py:2236` | `resolution_b ^ 0xDEAD` | **CONCERN**: `resolution_b` is a local variable derived from geometry/viewport geometry, not from `intent.seed`. If `resolution_b` can vary across runs (e.g. resolution changed by DPI/display), ejecta noise pattern will differ. Needs investigation. |

### Hard-coded seeds in production handlers

These use literal integer seeds (0, 1, 42) that are constant across runs — deterministic, but ignoring `intent.seed`. Terrain built with seed=1 vs seed=42 will get the same stratigraphy/palette pattern:

| File:line | Seed value | Impact |
|---|---|---|
| `handlers/terrain_palette_extract.py:106` | `default_rng(0)` | Palette K-means quantization seeded at 0 always; ignores intent seed. Medium: visual palette is always the same regardless of world seed. |
| `handlers/terrain_stratigraphy.py:420` | `default_rng(0)` | Stratigraphy sub-pass seeded at 0 always. Medium: strata layers identical for all world seeds. |
| `handlers/terrain_stratigraphy.py:569` | `default_rng(1)` | Another sub-pass, hard-coded seed 1. |
| `handlers/terrain_stratigraphy.py:794` | `default_rng(42)` | Another sub-pass, hard-coded seed 42. |

---

## terrain_rng.make_rng usage

- **make_rng called in production:** NO
- **tile_rng called in production:** NO
- **Current production seeding method:** `derive_pass_seed()` (in `terrain_pipeline.py`) is the actual production deterministic seed derivation. It uses SHA-256 over a JSON-serialized tuple of `[intent_seed, seed_namespace, tile_x, tile_y, region]`. This function IS used by most production passes: cliffs, caves, erosion, water variants, vegetation, waterfalls, stochastic shader, assets, and the `TerrainPassController.run_pass()` dispatcher all call it.

`make_rng` / `tile_rng` in `terrain_rng.py` are tested by `test_chunk_cache_math_helpers.py` but imported by zero production handlers. They are unreachable dead code from the production perspective.

**Critical gap:** `derive_pass_seed()` correctly computes a deterministic seed value and stores it in `result.seed_used`, but the pass function itself must still choose to use that seed — the controller does not inject the seed into the pass function. `run_pass()` calls `definition.func(self.state, region)` with no seed argument. Each pass function must import `derive_pass_seed` and call it independently. Passes that forget to do this (or use their own seed logic) are silently disconnected from the deterministic seed chain. Examples of passes correctly calling `derive_pass_seed` internally: `pass_stochastic_shader`, `pass_erosion`, `pass_cliffs`, `pass_caves`, `pass_waterfalls`. Example of a pass **not** using `derive_pass_seed` despite BUG-48 scope: `terrain_advanced.py` brush operations use a caller-supplied `seed` argument of unknown provenance — no call to `derive_pass_seed` observed.

---

## Determinism CI coverage

### `_snapshot_channel_hashes` — does it hash actual array content (bytes)?

**YES.** At `terrain_determinism_ci.py:53-58`:

```python
arr = np.ascontiguousarray(val)
h = hashlib.sha256()
h.update(name.encode("utf-8"))
h.update(str(arr.dtype).encode("utf-8"))
h.update(repr(arr.shape).encode("utf-8"))
h.update(arr.tobytes())
```

It hashes: channel name, dtype string, shape repr, and all array bytes. This is a genuine bit-level content hash — any floating-point difference, even in the last ULP, would cause a mismatch. This is correct and thorough.

### PYTHONHASHSEED controlled: NO

Neither `run_determinism_check` nor any CI configuration found in the handlers directory sets or checks `PYTHONHASHSEED` before running. The function runs within the current process's existing hash randomization. If the CI harness invokes multiple Python subprocesses without pinning `PYTHONHASHSEED=0`, the two `hash()` production sites (`terrain_cliffs.py:2368`, `asset_generation.py:755`) will produce different outputs in each subprocess, triggering false-positive determinism failures.

The correct fix is to run the determinism checker (and all tests touching determinism) with `PYTHONHASHSEED=0` in the environment, OR to eliminate the two `hash()` calls so PYTHONHASHSEED is irrelevant.

There is no check in `run_determinism_check` that warns when `PYTHONHASHSEED` is unset or randomized.

---

## seed_namespace usage

`seed_namespace` is a `PassDefinition` field (default `""`). In `TerrainPassController.run_pass()` at line 410:

```python
seed_used = derive_pass_seed(
    self.state.intent.seed,
    definition.seed_namespace or pass_name,  # fallback to pass_name
    self.state.tile_x,
    self.state.tile_y,
    region,
)
```

So `seed_namespace` is **active metadata** — it is used to derive the per-pass seed at dispatch time. Passes with empty `seed_namespace=""` fall back to using `pass_name` as the namespace, which is deterministic and safe.

Passes with empty `seed_namespace` (5 total):

| File:line | Pass name | Fallback namespace used |
|---|---|---|
| `terrain_pipeline.py:1057` | `pass_water_depth` | `"pass_water_depth"` (pass_name) |
| `terrain_pipeline.py:1252` | `pass_composite_hmap` | `"pass_composite_hmap"` (pass_name) |
| `_water_network.py:665` | `pass_hydrology` | `"pass_hydrology"` (pass_name) |
| `_water_network.py:1008` | `pass_water_flow_speed` | `"pass_water_flow_speed"` (pass_name) |
| `_water_network.py:3365` | `pass_river_convergence` | `"pass_river_convergence"` (pass_name) |

These 5 passes are deterministic — the fallback path is explicitly handled. The empty `seed_namespace` is a style issue, not a bug; using the pass_name as namespace is correct. However, the `pass_composite_hmap` and `pass_water_depth` passes don't use RNG at all (pure deterministic arithmetic), so the derived seed is computed but never consumed — harmless.

---

## STATISTICS

| Metric | Count |
|---|---|
| `hash()` seed sites in production | **2** |
| global seed mutations (`np.random.seed` / `random.seed`) | **1** (test-only) |
| `np.random.default_rng(None)` calls (non-deterministic) | **0** |
| `np.random.RandomState` in production handlers | **11** sites across `_terrain_noise.py` + `_biome_grammar.py` + `terrain_advanced.py` |
| Hard-coded literal seeds ignoring intent.seed | **4** (`terrain_palette_extract.py:106`, `terrain_stratigraphy.py:420,569,794`) |
| `make_rng` / `tile_rng` production callers | **0** |
| Passes with `seed_namespace=""` (uses pass_name fallback) | **5** |
| Passes with non-empty `seed_namespace` | ~45+ (all other registered passes) |
| CI determinism check hashes array bytes | **YES** |
| CI determinism check controls PYTHONHASHSEED | **NO** |

---

## Priority Fix List

1. **P0 — PYTHONHASHSEED cliff mesh seed** (`terrain_cliffs.py:2368`): Replace `hash(cliff.cliff_id)` with a stable hash. Use `int.from_bytes(hashlib.sha256(cliff.cliff_id.encode()).digest()[:4], "big")` or call `derive_pass_seed` with the cliff_id string as the namespace. This is an active terrain non-reproducibility bug on every re-run.

2. **P0 — PYTHONHASHSEED asset filename** (`asset_generation.py:755`): Replace `hash(full_prompt)` with `hashlib.sha256(full_prompt.encode()).hexdigest()[:8]`. Breaks caching and reproducible build pipelines.

3. **P1 — Add PYTHONHASHSEED=0 to CI determinism check**: Either enforce `PYTHONHASHSEED=0` in the environment before calling `run_determinism_check`, or add a check at the top of `run_determinism_check` that warns/raises when `os.environ.get("PYTHONHASHSEED", "random") not in ("0", "1")`.

4. **P1 — Hard-coded stratigraphy and palette seeds**: `terrain_stratigraphy.py` lines 420, 569, 794 and `terrain_palette_extract.py:106` use literal seeds 0/1/42. These ignore `intent.seed`, making stratigraphy and palette layers invariant across all world seeds. Replace with `derive_pass_seed` calls.

5. **P2 — `terrain_advanced.py:2236` ejecta seed from `resolution_b`**: Verify whether `resolution_b` is derived from `intent.seed` or from runtime/viewport state. If viewport-derived, this is a silent non-determinism source in impact crater ejecta patterns.

6. **P2 — Wire `make_rng`/`tile_rng` to production passes**: Per BUG-48/49/81/91/92/96, migrate `np.random.RandomState` sites in `_terrain_noise.py` and `_biome_grammar.py` to the `make_rng` API. These are currently deterministic (seeded from external ints) but use the legacy API.

7. **P3 — `seed_namespace=""` cleanup**: Replace empty `seed_namespace` strings with explicit names for documentation clarity, even though the pass_name fallback is functionally correct.
