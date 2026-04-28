# A1 Audit: Core Pipeline — PassDAG / Protocol / Registrar
**Date:** 2026-04-27
**Files audited:**
- `veilbreakers_terrain/handlers/terrain_pass_dag.py`
- `veilbreakers_terrain/handlers/terrain_protocol.py`
- `veilbreakers_terrain/handlers/terrain_pipeline.py`
- `veilbreakers_terrain/handlers/terrain_master_registrar.py`
- `veilbreakers_terrain/handlers/terrain_region_exec.py`
- `veilbreakers_terrain/handlers/terrain_validation.py`
- `veilbreakers_terrain/handlers/terrain_rng.py`

---

## CRITICAL FINDINGS (P0)

### [P0-1] `pass_water_depth` result `pass_name` mismatches its registration name — terrain_pipeline.py:1010–1015

**File:** `terrain_pipeline.py:1010`

The `pass_water_depth` function returns:
```python
return PassResult(
    pass_name="pass_water_depth",
    status="skipped",
    ...
)
```
But the **skipped** branch returns a `PassResult` with `pass_name="pass_water_depth"` and no `produced_channels` set. The `run_pass` caller then checks `produces_channels` from the `PassDefinition` against `self.state.mask_stack.get(ch)` and raises `PassContractError` if they are not populated — **but only when `result.status == "ok"`**. So this path is actually safe. However, the **more critical** problem is on the success path:

`pass_water_depth` is registered under the name `"pass_water_depth"` (line 1050) but its `PassDefinition.requires_channels = ()` while it reads `water_surface_elevation_m` and `height`/`height_m` directly from the stack without contract enforcement. The `optional_channels` field includes only `water_surface_elevation_m`, not `height_m` or `height`.

**The real P0 here:** If `water_surface_elevation_m` is present but `height` and `height_m` are both absent from the stack, `h_arr` will be `None` and the code returns `PassResult(status="skipped")` — but the calling `run_pass` will then check `produces_channels = ("water_depth_m", "shoreline_blend")` and because `result.status == "skipped"` the `_merge_pass_outputs` function skips those channels. This means a **successfully registered pass silently produces no output when its unlisted height dependency is absent**, with no warning emitted to the caller. The DAG cannot see this dependency because `height` is not in `requires_channels` or `optional_channels`.

**AAA comparison:** In Houdini HeightField SOPs, every node declares all consumed inputs in its wiring; unlisted inputs cannot be read. Gaea's node graph enforces the same contract. Here, the pass reads `height`/`height_m` via stack backdoor without any DAG visibility — this is a silent correctness hole.

**Impact:** Water depth and shoreline blend silently absent if height channel has a non-standard name, with no log or error. Shader will receive uninitialized water data.

---

### [P0-2] `_ACTIVE_CONTROLLER` global state creates data corruption under parallel execution — terrain_validation.py:1976–1987

**File:** `terrain_validation.py:1976`

```python
_ACTIVE_CONTROLLER: Optional[TerrainPassController] = None
_ACTIVE_CONTROLLER_CTX: contextvars.ContextVar[Optional[TerrainPassController]] = (
    contextvars.ContextVar("terrain_validation_active_controller", default=None)
)
```

`_ACTIVE_CONTROLLER` is a **module-level global**. `_ACTIVE_CONTROLLER_CTX` is a `ContextVar`, which is the correct async/thread approach, but `bind_active_controller` also writes to the global `_ACTIVE_CONTROLLER` fallback (line 2013–2014):
```python
_ACTIVE_CONTROLLER_CTX.set(controller)
_ACTIVE_CONTROLLER = controller
```

When `PassDAG.execute_parallel` runs multiple passes in a wave via `ThreadPoolExecutor`, each worker thread performs `copy.deepcopy(controller.state)` and creates a `worker_controller`. If `pass_validation_full` is scheduled in a wave alongside other passes (or if two pipelines run concurrently in separate threads), the global `_ACTIVE_CONTROLLER` is a shared non-thread-safe pointer. `ContextVar` values are thread-local only for async coroutines — they do **not** isolate across threads spawned by `ThreadPoolExecutor`. Multiple threads calling `_get_active_controller()` simultaneously will all see the same global fallback, and if one pipeline's validation triggers `rollback_last_checkpoint()` it will roll back the **wrong controller's state**.

**AAA comparison:** Guerrilla Games / Decima engine uses strict per-request context objects with no process-level shared mutable singletons for this exact reason. Epic's UE5 WorldPartition tile cook jobs are entirely isolated at the pass level. A mutable global rollback handle in a multithreaded tile cook is a textbook race condition.

**Impact:** P0 data corruption: validation pass in wave N can roll back a completely different in-flight pipeline if two tiles are being processed in parallel. Silent wrong output — terrain rolls back to a checkpoint that belongs to a different tile's controller.

---

### [P0-3] `run_pipeline` default sequence inserts `pass_hydrology` and `erosion` into a hardcoded position by mutation of `pass_sequence` — terrain_pipeline.py:568–569

**File:** `terrain_pipeline.py:568`

```python
pass_sequence = [
    "pass_generate_low_freq_hmap",
    "terrain_labels",
    "structural_masks",
    "pass_generate_high_freq_detail",
    "pass_composite_hmap",
    "validation_minimal",
]
if getattr(self.state.intent, "scene_read", None) is not None:
    pass_sequence[3:3] = ["pass_hydrology", "erosion"]
```

Inserting at index 3 places `pass_hydrology` and `erosion` **before** `pass_generate_high_freq_detail`, meaning erosion runs before the high-frequency detail band exists. `erosion` declares `requires_channels=("hmap_low_freq",)` and produces `height` and `hmap_low_freq`, so it would receive the pre-composite low-freq heightmap and overwrite it — then `pass_composite_hmap` tries to composite `hmap_low_freq` (now eroded) with `hmap_high_freq`. The resulting sequence becomes:

```
1. pass_generate_low_freq_hmap
2. terrain_labels
3. structural_masks
4. pass_hydrology   ← inserted
5. erosion          ← inserted; runs before high_freq exists
6. pass_generate_high_freq_detail
7. pass_composite_hmap
8. validation_minimal
```

`pass_hydrology` requires `flow_direction` and `flow_accumulation` which are not produced by any pass before it in this sequence; they come from the hydrology pass itself (`_water_network.register_pass_hydrology`). The intent is presumably to run hydrology before erosion for slope-following river carving. But the insertion index is brittle: if any future change adds or removes a pass before index 3, the slice becomes wrong without any error.

**AAA comparison:** Houdini PDG and World Machine do not embed hardcoded list indices; they use explicit dependency edges. This is a fragile implicit ordering that will silently misplace passes as the default sequence grows.

**Impact:** When `scene_read` is present, erosion runs on a pre-high-freq, pre-composite heightmap. The final `pass_composite_hmap` composites already-eroded low-freq with un-eroded high-freq detail — producing a composite that was never actually fully eroded. Silent wrong output in the most common game production path.

---

## HIGH-SEVERITY (P1)

### [P1-1] Duplicate `_toposort_passes` implementation inside `terrain_pipeline.py` — terrain_pipeline.py:1073

**File:** `terrain_pipeline.py:1073`

`terrain_pipeline.py` contains its own `_toposort_passes()` function (line 1073–1134) that is a separate Kahn's BFS implementation from `PassDAG.topological_order()` in `terrain_pass_dag.py`. These two implementations diverge in how they handle determinism: `PassDAG.topological_order()` inserts newly-ready nodes sorted lexicographically (lines 252–254), whereas `_toposort_passes()` pops from a plain list using `queue.pop(0)` and appends new nodes without sorting (line 1107–1120). This means:

- `PassDAG` guarantees lexicographic-stable topological order.
- `_toposort_passes` used in `register_default_passes` uses first-ready-first-served order that depends on Python dict insertion order (which is insertion-ordered since 3.7 but still non-lexicographic).

**Two topo-sorters + divergent determinism guarantees = two different orderings for the same pass graph depending on which path is taken.** Any test that constructs a `PassDAG` from the registry will see a different execution order than `run_pipeline` with its default sequence.

**AAA comparison:** UE5's Blueprint compiler has a single canonical topo-sort used by both the editor graph and the cook pipeline. Gaea's processing graph has one sort at graph-build time. Dual sort implementations are a maintenance hazard at the scale of a 14-bundle pipeline.

**Impact:** Execution order divergence between `execute_parallel` and `run_pipeline`. Passes that produce channels consumed by others may run in different relative order, producing different terrain outputs between the two code paths. Debugging is extremely difficult when the two paths give different results.

---

### [P1-2] `pass_compute_snow_line` returns `PassResult(pass_name="snow_line")` but is registered as `"snow_line"` — terrain_pipeline.py:947

**File:** `terrain_pipeline.py:947`

```python
return PassResult(
    pass_name="snow_line",
    ...
    consumed_channels=("height", "slope"),
    produced_channels=("snow_line_factor",),
```

The `consumed_channels`/`produced_channels` fields on `PassResult` are informational only — they are not the `PassDefinition.requires_channels`/`produces_channels` used for contract enforcement. The `run_pass` enforcer uses `definition.requires_channels`, not `result.consumed_channels`. But the registration (line 958–969) declares `requires_channels=("height",)` only — `slope` is silently consumed via `stack.get("slope")` with a `None → zeros` fallback at line 935–936. If `structural_masks` fails or is skipped, `snow_line` silently uses a zero slope map, producing incorrect snow distribution with no warning.

More critically: slope is a non-optional scientific input for an accurate snow-line calculation; treating its absence as equivalent to flat terrain is geologically wrong and violates the AAA quality bar.

**Impact:** Silent wrong output — snow coverage ignores slope when `structural_masks` has not run, producing elevation-only snow bands instead of elevation+slope-modulated snow. No diagnostic emitted.

---

### [P1-3] `execute_region_with_rollback` secondary rollback calls `_rollback_to(controller, pre_label)` with the label, not the ID — terrain_region_exec.py:212–218

**File:** `terrain_region_exec.py:212`

```python
pre_label = f"region_exec_pre_{int(time.time() * 1000)}"
try:
    ckpt = _save_ckpt(controller, pass_name="region_exec_pre", label=pre_label)
    pre_id = ckpt.checkpoint_id
except Exception:
    pre_id = None
...
if pre_id is not None and rolled_back:
    try:
        _rollback_to(controller, pre_label)   # ← uses label, not pre_id
```

`pre_id` is the checkpoint's `.checkpoint_id` (a UUID-based string like `"region_exec_pre_a1b2c3d4"`), but `_rollback_to` is called with `pre_label` (a timestamp string like `"region_exec_pre_1714267200000"`). If the external `terrain_checkpoints.rollback_to` function looks up by `checkpoint_id` (matching `TerrainPassController.rollback_to` behavior), the lookup will fail silently because the ID and the label are different strings. The `except Exception: pass` swallows the `KeyError`, so the secondary rollback always silently fails — it is effectively dead code.

**Impact:** The "two-layer defence" described in the docstring is actually one layer; the checkpoint-based secondary rollback never fires correctly. Misleading documentation creates false confidence in recovery guarantees.

---

### [P1-4] `_merge_pass_outputs` unconditionally overwrites `height_min_m` and `height_max_m` from the last merged worker — terrain_pass_dag.py:117–119

**File:** `terrain_pass_dag.py:117`

```python
target_stack.height_min_m = source_stack.height_min_m
target_stack.height_max_m = source_stack.height_max_m
target_stack.content_hash = None
```

In a wave with multiple parallel passes, `_merge_pass_outputs` is called in sorted pass-name order. Each call overwrites `height_min_m`/`height_max_m` from whatever worker just merged. If `pass_erosion` runs in the same wave as another pass that does not modify height, the height range metadata will be set to whichever worker's snapshot happens to merge last. If the non-erosion worker's `source_stack` carries the pre-erosion height range (from the deep-copy taken before the wave), the merged state will have eroded height data but pre-erosion range metadata — or the reverse. There is no range reconciliation (e.g., `min(all workers)` / `max(all workers)`) across parallel workers.

**AAA comparison:** In Houdini's parallel cook, per-node metadata (bbox, value ranges) is reconciled across all branches before the downstream node sees the result. No single branch's metadata silently wins.

**Impact:** `height_min_m`/`height_max_m` may not reflect the actual range of the merged `height` array. Downstream passes that use these values for normalization (e.g., `pass_compute_snow_line` line 929) will compute on incorrect range metadata, producing wrong normalized heights and wrong snow/material distributions.

---

### [P1-5] Rule 2 gate permanently downgraded to a warning-skip instead of an enforceable contract — terrain_protocol.py:136–139

**File:** `terrain_protocol.py:136`

```python
if vantage is None:
    _rule2_log.warning(
        "rule_2/soft: state.viewport_vantage is None — Rule 2 check skipped. ..."
    )
    return
```

Rule 2's gate unconditionally returns without raising when `viewport_vantage` is `None`. The `@enforce_protocol` decorator has `require_rule_2=True` by default, meaning callers believe Rule 2 is being enforced, but in every headless/automated context it silently passes. The docstring acknowledges this as a "backward compatibility" choice pending "future hardening," but:

1. There is no `rule_2_enforced` flag in the result, so callers cannot detect that the check was skipped.
2. The decorator's `require_rule_2` toggle misleads: setting it to `True` does not guarantee enforcement — it only guarantees "enforcement if vantage is populated."
3. Production terrain passes that wrap with `@enforce_protocol()` will never have Rule 2 checked during automated pipeline runs, which is exactly when incorrect viewport-relative decisions would go undetected.

**Impact:** Viewport-sync invariant never actually enforced in practice. Any pass that makes camera-relative decisions (LoD range, sightline culling, scatter density by proximity) can silently use stale or absent viewport data.

---

### [P1-6] `validate_protected_zones_untouched` is in `DEFAULT_VALIDATORS` but `pass_validation_full` never passes a `baseline_stack` — terrain_validation.py:1909, 2018–2060

**File:** `terrain_validation.py:1909` and `2029`

`DEFAULT_VALIDATORS` includes `validate_protected_zones_untouched` at tuple position 3 (line 1909). The validator signature is:
```python
def validate_protected_zones_untouched(
    stack, intent, baseline_stack=None
) -> List[ValidationIssue]:
```

But the `run_validation_suite` runner calls validators with only two arguments — `fn(stack, intent)` at line 1947. The `baseline_stack` parameter therefore always receives `None`. The validator then emits an `info` notice:
```python
issues.append(ValidationIssue(
    code="PROTECTED_BASELINE_ABSENT",
    severity="info",
    message="no baseline stack provided; cannot diff protected zones",
))
```

This means the protected-zone mutation check **never actually runs in production**. The validator is in the list but always degrades to a no-op info notice. Protected zones can be mutated by any pass and the validation suite will not detect it.

**AAA comparison:** Protected zones are equivalent to UE5's "restricted areas" in World Partition. Epic's validation checks reserved cells against pre-cook hashes. An enforcer that always says "can't check, no baseline" is worse than having no enforcer — it creates false confidence.

**Impact:** Protected zone mutation is entirely undetected at validation time. Authors who rely on `validation_full` to catch protected-zone violations will get a false clean result.

---

### [P1-7] `make_rng` in `terrain_rng.py` is **not used by any production pass** — terrain_rng.py:17–36

**File:** `terrain_rng.py:17`

```python
# FUTURE USE: intended as the canonical deterministic RNG factory for all
# scatter, erosion, and noise passes — replaces ad-hoc np.random.RandomState
# calls across the codebase (tracked under BUG-48/49/81/91/92/96).
# Currently called from tests only; production passes should migrate to this.
```

`terrain_pipeline.py`'s `derive_pass_seed` (line 60–84) correctly uses SHA-256 to generate a 32-bit seed, but passes it to `definition.func(self.state, region)` as `self.state.intent.seed` context — there is no mechanism to inject the derived seed into the pass function. Individual pass implementations are expected to read their seed from `state.intent.seed` or call some RNG, but the canonical `make_rng` is acknowledged as "tests only." This means production passes are using `state.intent.seed` directly or calling `np.random.RandomState` ad hoc with `hash()`-based seeds (which `PYTHONHASHSEED` randomizes).

BUG-48, 49, 81, 91, 92, and 96 are all open. Six tracked bugs for non-determinism across scatter, erosion, and noise are simultaneously open and the fix (`make_rng`) is unused in production.

**Impact:** Terrain is not deterministic across Python runs due to `PYTHONHASHSEED`. Re-generating a tile with the same seed will produce different results. Regression testing is effectively broken. In a game with a procedural world, this means a shipped seed cannot reproducibly generate the same map.

---

## MEDIUM (P2)

### [P2-1] `PassDAG` duplicate-pass warning is a WARNING not an ERROR — terrain_pass_dag.py:138–143

**File:** `terrain_pass_dag.py:138`

Duplicate pass names in the input list are logged as warnings and the dict comprehension silently keeps the last definition. For a 14-bundle pipeline, a bundle that accidentally registers under the same name as an existing pass will silently replace it. `TerrainPassController.register_pass` has a `strict=True` option to raise — `PassDAG.__init__` has no such option, so callers of `PassDAG` directly (not through `register_pass`) cannot get hard failure on duplicates.

---

### [P2-2] `_runner` closure inside `execute_parallel` captures `controller` by reference — terrain_pass_dag.py:340

**File:** `terrain_pass_dag.py:340`

```python
def _runner(pname: str) -> PassResult:
    worker_state = copy.deepcopy(controller.state)
    worker_controller = TerrainPassController(
        worker_state,
        checkpoint_dir=controller.checkpoint_dir,
    )
```

`_runner` is defined inside the `for wave_idx, wave in enumerate(self.parallel_waves()):` loop. It closes over `controller`, `checkpoint`, and `wave` (via the loop variable). `wave` is not captured by the closure itself (the closure only uses `pname` from the argument), so the wave variable issue is not present here. However, `controller.state` is read inside `_runner` which runs in worker threads. If the main thread modifies `controller.state` between the `executor.submit` calls (unlikely but possible if the same `controller` object is shared across waves in a concurrent context outside `execute_parallel`), workers will see inconsistent state. The design relies on all state mutation being deferred to the post-wave merge step, but this is not enforced — it is a convention that any future code change could accidentally violate.

---

### [P2-3] `register_all_terrain_passes` unconditionally calls `register_default_passes` even if Bundle A is already registered — terrain_master_registrar.py:202

**File:** `terrain_master_registrar.py:202`

```python
from .terrain_pipeline import register_default_passes
register_default_passes(strict=strict)
loaded.append("A")
```

`register_default_passes` calls `TerrainPassController.register_pass` which logs a WARNING and overwrites on duplicate. When `register_all_terrain_passes` is called twice (e.g., at startup and after hot-reload), every Bundle A pass is re-registered, the `ChannelOwnershipError` duplicate-producer check is bypassed because the code path at line 246 checks `if definition.name not in cls.PASS_REGISTRY` — a re-registration is silently allowed. The `pre_reg_size` snapshot on line 197 is taken before Bundle A registers, so `net_new` in the summary may report negative values on second call (since total passes did not increase), which is misleading.

---

### [P2-4] `validate_protected_zones_untouched` signature incompatibility with `run_validation_suite` — terrain_validation.py:409

**File:** `terrain_validation.py:409`

As noted in P1-6, the validator has a third optional parameter `baseline_stack`. The `DEFAULT_VALIDATORS` tuple type annotation is:
```python
Tuple[str, Callable[[TerrainMaskStack, TerrainIntentState], List[ValidationIssue]]]
```
The actual function signature is `(stack, intent, baseline_stack=None)`, which is compatible with the 2-argument call but the type annotation does not capture the third parameter. If someone adds a new suite runner that uses type-checked dispatch, it will break or silently omit baseline support. This is an interface hygiene issue adjacent to the P1-6 correctness bug.

---

### [P2-5] `_normalize_delta_integration_sequence` silently skips unregistered passes — terrain_pipeline.py:106–118

**File:** `terrain_pipeline.py:106`

The function logs a warning for unregistered pass names but continues without raising:
```python
if unregistered:
    _log.warning(
        "_normalize_delta_integration_sequence: skipping unregistered pass names %s "
        ...
    )
```
In a full production sequence of 14+ bundles, a typo in `pass_sequence` will cause `integrate_deltas` to be placed incorrectly (before all delta producers rather than after the last one), silently producing incorrect composite heights. The comment says "P2-5" as if this was a known issue but it was not escalated to a fix.

---

### [P2-6] `check_cliff_silhouette_readability` pure-numpy fallback component-labeling is O(diameter) iterations with a Python `while changed` loop — terrain_validation.py:1078–1089

**File:** `terrain_validation.py:1078`

```python
changed = True
while changed:
    new_labels = labels.copy()
    _lpad = np.pad(labels, 1, mode="edge")
    for dr, dc in ((-1, -1), ...):
        ...
    changed = bool(np.any(new_labels != labels))
    labels = new_labels
```

For a 1 km² tile at 1 m/cell (1000×1000 grid), the longest cliff component diagonal is up to 1414 cells, requiring ~1414 outer `while` iterations. Each iteration does 8 array operations on a 1000×1000 array. At ~0.1 ms per array op, this is roughly 1414 × 8 × 0.1 ms = **1.1 seconds per validation run** without scipy. The comment claims "no per-cell Python loops" but the outer `while changed` loop IS a Python-level loop iterating O(max_diameter) times. This is correct but slow.

For AAA production tiles (4096×4096 at 0.25 m/cell), this becomes pathological: up to ~5800 iterations × 8 ops on a 4096² array = minutes of validation time per tile.

---

### [P2-7] `_PASS_PAD_RADIUS` hardcoded lookup in `terrain_region_exec.py` is not extensible — terrain_region_exec.py:29–40

**File:** `terrain_region_exec.py:29`

The `_PASS_PAD_RADIUS` dict hardcodes padding for specific pass names. New bundles (J, K, L, N, O) are not represented. Any pass not in the dict gets `_DEFAULT_PAD_RADIUS_M = 8.0`, which may be too small for passes like `pass_river_convergence` (needs flow accumulation from adjacent tiles) or too large for instantaneous passes like `terrain_labels`. The dict is not validated against the registry — there is no mechanism to detect when a registered pass needs custom padding but was not added to the map.

---

## LOW (P3)

### [P3-1] `tile_rng` multiplies float coordinates by 1000 before casting to int — terrain_rng.py:43

**File:** `terrain_rng.py:43`

```python
return make_rng(int(world_origin_x * 1000), int(world_origin_y * 1000), root_seed)
```

For sub-meter grid coordinates (e.g., `world_origin_x = 0.001`), `int(0.001 * 1000) = int(1.0) = 1`. For floating-point values like `world_origin_x = 100.0003`, the result is `100000` (correct). But for tiles with `world_origin_x = 100.0` and `100.0003`, the seeds are `100000` and `100000` — **collision**. The precision is only 3 decimal places. World Machine and Gaea use full float-bit encoding (e.g., `struct.pack` or `.hex()`) when tiles have sub-centimeter origins. For most VeilBreakers tiles this is probably fine, but it is a latent bug for non-integer-origin tile grids.

---

### [P3-2] `enforce_protected_zones` only raises on **full coverage**, not partial intersection — terrain_pipeline.py:352–364

**File:** `terrain_pipeline.py:352`

The docstring says "Partial intersection is allowed: the pass is expected to consult per-cell protected masks." This is a design choice, but it means the zone enforcement gate never fires for passes that do not respect per-cell masks (e.g., global noise passes that write every cell). If a pass has `respects_protected_zones=True` but does not actually check per-cell masks, it will silently overwrite protected cells without any enforcement catching it unless the zone fully covers the region. The per-cell mask convention is unenforced documentation.

---

### [P3-3] `from_pass` validation uses `pass_sequence.index()` which returns first occurrence — terrain_pipeline.py:609

**File:** `terrain_pipeline.py:609`

```python
start_idx = pass_sequence.index(from_pass)
```

`list.index()` returns the first occurrence. If a pass appears twice in the sequence (e.g., `validation_minimal` could plausibly run pre- and post-erosion), using `from_pass` to restart from the second occurrence is impossible. No duplicate detection is done before the slice. This is a minor edge case but it means `from_pass` behaves unexpectedly when a pass appears more than once.

---

### [P3-4] Magic constant `0.5` for shoreline blend zone — terrain_pipeline.py:1029

**File:** `terrain_pipeline.py:1029`

```python
shoreline_blend = _np.clip(depth / 0.5, 0.0, 1.0)
```

The 0.5 m blend zone is hardcoded with no `PassDefinition` parameter, no intent override, and no docstring attribution. Different biomes (e.g., rocky coast vs. sandy beach vs. cliff waterfall plunge pool) need different blend widths. This should be an intent-driven parameter or at minimum a named constant.

---

### [P3-5] `run_pipeline` logs incorrect pass count in `from_pass` info message — terrain_pipeline.py:612–616

**File:** `terrain_pipeline.py:612`

```python
_log.info(
    "run_pipeline: partial re-run starting from pass '%s' (%d/%d passes)",
    from_pass,
    len(pass_sequence),   # ← this is the SLICED count, same value both times
    len(pass_sequence),   # ← should be the full original count
)
```

Both format arguments use `len(pass_sequence)` after the slice. The log will always read "N/N passes" regardless of how many passes were skipped, making it useless for diagnosing how far into the pipeline a partial re-run starts.

---

### [P3-6] `_issue_category` fallback returns `"other"` but `ValidationReport.categories` does not initialize `"other"` — terrain_validation.py:185–195 and 89–98

**File:** `terrain_validation.py:185`

`_issue_category` returns `"other"` when no prefix matches. `ValidationReport.categories` is initialized with 7 fixed keys (lines 89–98). `ValidationReport.add()` calls `self.categories.setdefault(cat, []).append(issue)` which will create an `"other"` key on first use. This is not a crash, but `category_summary()` at line 126 iterates `self.categories.items()` — it will include the ad-hoc `"other"` bucket in the summary but callers expecting exactly the 7 fixed keys will see an 8th unexpected key. A typo in an issue code prefix (e.g., `"HEIGHT_..."` vs. `"height_"` — the lookup is lowercased but the actual codes use `UPPER_SNAKE`) can silently route issues to `"other"` instead of `"geometry"`.

---

### [P3-7] `terrain_rng.py` has the docstring **after** the function signature comment block — terrain_rng.py:17–36

**File:** `terrain_rng.py:17`

```python
def make_rng(*keys: Union[int, str, float]) -> np.random.Generator:
    # FUTURE USE: intended as the canonical...
    """Create a deterministic Generator seeded from an ordered sequence of keys.
    ...
    """
```

The `# FUTURE USE:` comment appears **before** the docstring, so IDEs and `help()` will show the docstring correctly but the intent comment is invisible to documentation generators. Minor but causes reader confusion.

---

## CLEAN FINDINGS

- **Kahn's BFS in `PassDAG.topological_order()`** — correctly detects cycles, correctly names all passes in cycle, produces stable lexicographic output. No issues.
- **`derive_pass_seed`** — correctly avoids `hash()` (PYTHONHASHSEED-randomized), uses SHA-256 over JSON-encoded tuple, masks to 32 bits for numpy compatibility. This is the right approach.
- **`register_pass` duplicate-producer enforcement** (added 2026-04-23) — `ChannelOwnershipError` at register time for contested channels without declared `overrides` is correct and matches Gaea's node graph ownership model.
- **`TerrainPassController.rollback_to` shape validation** — validates all populated channel shapes against current grid dimensions before completing rollback. Correct guard against restoring a checkpoint from a differently-sized tile.
- **`run_validation_suite` exception isolation** — each validator is wrapped in `try/except` that converts crashes to `VALIDATOR_CRASHED` hard issues. This is correct: a validator crash should fail the tile, not silently pass it.
- **`execute_region_with_rollback` primary deep-copy rollback** — using `copy.deepcopy` as the primary rollback mechanism (rather than checkpoint-only) is the right choice for in-memory atomic rollback semantics. O(state_size) cost is acceptable for an error recovery path.
- **`PassDAG.parallel_waves()` wave grouping** — correctly uses `wave_index[d]` with a dependency intersection check (only considers deps that are in `wave_index`) to avoid KeyError when optional channels have no producer. Correct.
- **`register_all_terrain_passes_detailed`** — the split into `loaded`/`errors` return with structured error reporting is good API design.
- **`_CATEGORY_PREFIXES` tuple ordering** — lowercase prefix matching in priority order is a correct approach; more specific prefixes (e.g., `"channel_dtype"`) are listed before catch-all roots. This is fine.
- **`ValidationReport.recompute_status`** — correctly uses hard > soft > ok severity hierarchy without any off-by-one risk.
- **`make_rng` using list-form seed for `default_rng`** — the list-form seeding per NumPy parallel seeding guidance is correct. The SHA-256 key derivation per key avoids integer overflow issues with large coordinate values.

---

## STATISTICS

- **Files audited:** 7
- **P0 count:** 3
- **P1 count:** 7
- **P2 count:** 7
- **P3 count:** 7
- **Total findings:** 24
- **Clean findings:** 10

---

## PRIORITY ACTION ITEMS

**Immediate (P0 must fix before production tile cooks):**

1. **P0-2** — Remove `_ACTIVE_CONTROLLER` global from `terrain_validation.py`. Pass the controller explicitly to `pass_validation_full` via a closure or a per-call context parameter. The `ContextVar` approach is correct for async but not for `ThreadPoolExecutor` threads.

2. **P0-3** — Replace the hardcoded `pass_sequence[3:3] = [...]` insertion with proper dependency-driven sequencing: add `pass_hydrology` and `erosion` to `PassDAG` and let the DAG determine their position. Remove the magic index-3 slice.

3. **P0-1** — Add `height` and `height_m` to `pass_water_depth`'s `optional_channels` in the `PassDefinition`, so the DAG can order it correctly after any height-producing pass.

**High priority (before next wave of terrain assets):**

4. **P1-7** — Migrate all production passes from ad-hoc `np.random.RandomState` / `hash()`-seeded RNG to `terrain_rng.make_rng()`. Track against BUG-48/49/81/91/92/96.

5. **P1-6** — Either pass a baseline stack to `validate_protected_zones_untouched` inside `pass_validation_full`, or replace the validator with a hash-based approach using `protected_zone_hash()` stored at pipeline start.

6. **P1-4** — Replace the unconditional `height_min_m`/`height_max_m` overwrite in `_merge_pass_outputs` with proper range reconciliation: take `min` of all workers' `height_min_m` and `max` of all workers' `height_max_m`.
