# Wave 2 — B8: pipeline / pass_dag / protocol / master_registrar / semantics

**Auditor:** Opus 4.7 ultrathink (1M)
**Date:** 2026-04-16
**Scope:** 5 files under `veilbreakers_terrain/handlers/`
**Standard:** AAA vs Houdini TOPs / UE5 PCG
**References pulled this round:** Python `concurrent.futures` & `multiprocessing.shared_memory` docs, NetworkX DAG/Cycles algorithms, Houdini PDG/TOPs intro, prior CSV `docs/aaa-audit/GRADES_VERIFIED.csv`.

## 0. AST enumeration (every callable + class)

```
terrain_pipeline.py            (472 LOC)
  func _make_gate_issue                            L46
  func derive_pass_seed                            L55
  CLASS TerrainPassController                      L87
    func __init__                                  L93
    classmethod register_pass                      L109
    classmethod get_pass                           L114
    classmethod clear_registry                     L120
    func require_scene_read                        L126
    func enforce_protected_zones                   L134
    func run_pass                                  L167
    func run_pipeline                              L296
    func _save_checkpoint                          L327
    func rollback_to                               L372
    func rollback_last_checkpoint                  L384
  func register_default_passes                     L395

terrain_pass_dag.py            (199 LOC)
  CLASS PassDAGError                               L21
  func _merge_pass_outputs                         L25
  CLASS PassDAG                                    L59
    func __init__                                  L62
    classmethod from_registry                      L71
    property names                                 L85
    func dependencies                              L88
    func topological_order                         L98
    func parallel_waves                            L120
    func execute_parallel                          L139
      nested visit                                 L104
      nested _runner                               L164

terrain_protocol.py            (239 LOC)
  CLASS ProtocolViolation                          L32
  CLASS ProtocolGate                               L36
    static rule_1_observe_before_calculate         L44
    static rule_2_sync_to_user_viewport            L69
    static rule_3_lock_reference_empties           L87
    static rule_4_real_geometry_not_vertex_tricks  L106
    static rule_5_smallest_diff_per_iteration      L117
    static rule_6_surface_vs_interior_classification L145
    static rule_7_plugin_usage                     L165
  func enforce_protocol                            L177
    nested decorator                               L195
    nested wrapper                                 L197

terrain_master_registrar.py    (179 LOC)
  func _safe_import_registrar                      L47
  func register_all_terrain_passes                 L72
  func register_all_terrain_passes_detailed        L100
  func _register_all_terrain_passes_impl           L115

terrain_semantics.py           (1049 LOC)
  CLASS ErosionStrategy                            L41
  CLASS SectorOrigin                               L56
  CLASS WorldHeightTransform                       L70
    func __post_init__                             L83
    func to_normalized                             L90
    func from_normalized                           L94
  CLASS BBox                                       L105
    func __post_init__                             L117
    property width                                 L125
    property height                                L129
    property center                                L133
    func to_tuple                                  L136
    func contains_point                            L139
    func intersects                                L142
    func to_cell_slice                             L150
  CLASS HeroFeatureRef                             L167
  CLASS WaterfallChainRef                          L177
  CLASS HeroFeatureBudget                          L187
  CLASS TerrainMaskStack                           L201
    func __post_init__                             L399
    func get                                       L440
    func set                                       L455
    func mark_dirty                                L465
    func mark_clean                                L469
    func assert_channels_present                   L472
    func unity_export_manifest                     L503
    func compute_hash                              L546
    func to_npz                                    L600
    classmethod from_npz                           L625
  CLASS ProtectedZoneSpec                          L657
    func permits                                   L667
  CLASS TerrainAnchor                              L681
  CLASS HeroFeatureSpec                            L698
  CLASS WaterSystemSpec                            L720
  CLASS TerrainSceneRead                           L746
  CLASS TerrainIntentState                         L772
    func with_scene_read                           L794
    func intent_hash                               L800
  CLASS ValidationIssue                            L837
    func is_hard                                   L845
  CLASS PassResult                                 L855
    func ok                                        L870
  CLASS TerrainCheckpoint                          L880
  CLASS QualityGate                                L909
  CLASS PassDefinition                             L935
  CLASS TerrainPipelineState                       L975
    property tile_x                                L993
    property tile_y                                L997
    func record_pass                               L1000
  CLASS SceneReadRequired                          L1009
  CLASS ProtectedZoneViolation                     L1013
  CLASS PassContractError                          L1017
  CLASS UnknownPassError                           L1021
```

Total inventory: **5 modules, 26 classes, 56 functions/methods/properties**.

---

## 1. terrain_pipeline.py — orchestrator

### 1.1 `_make_gate_issue` (L46)
- **Prior:** B (R1) → A- (R5, “overdue lift”).
- **My grade:** **A-** — AGREE with R5.
- **What it does:** 2-line factory that returns `ValidationIssue(code, severity, message)`. Used only by `run_pass` to construct a synthetic issue when a gate raises.
- **Reference:** Trivial factory — Houdini equivalent is a 1-liner around `pdg.WorkItem.addError`.
- **Bug/gap:** None (`location`, `affected_feature`, `remediation` left default which is correct for a gate-crash issue).
- **AAA gap:** None.
- **Severity:** none.
- **Upgrade:** none — leave as-is.

### 1.2 `derive_pass_seed` (L55)
- **Prior:** A (consensus).
- **My grade:** **A** — AGREE.
- **What it does:** SHA-256 of `json.dumps([intent_seed, namespace, tile_x, tile_y, region], sort_keys=True)`, masked to 32 bits. Used as the per-pass numpy RNG seed.
- **Reference:** Matches Houdini HDA seed-chaining (`hou.HDADefinition` deterministic derivation) and UE5 PCG’s deterministic seed domain. SHA-256 is overkill but defensible.
- **Bug/gap:** Minor — `region.to_tuple()` returns 4 floats; if `region` ever held NaN the JSON would raise (`TypeError: Object of type float is not JSON serializable`). Not exploitable today (only `BBox.__post_init__` would have to allow NaN).
- **AAA gap:** None.
- **Severity:** none.
- **Upgrade:** Optional — cache the digest on the intent for hot loops; no functional change.

### 1.3 `TerrainPassController.__init__` (L93)
- **Prior:** A (R5 NEW).
- **My grade:** **A** — AGREE.
- **What it does:** Stores `state`, defaults `checkpoint_dir` to `.planning/terrain_checkpoints`. Wraps in `Path()`.
- **Reference:** Standard service-object pattern.
- **Bug/gap:** Wraps `Path(...)` twice (`Path(checkpoint_dir if ... else Path(...))`). Functionally fine — `Path(Path(x))` is `Path(x)`. Cosmetic only.
- **AAA gap:** None.
- **Severity:** none.
- **Upgrade:** none.

### 1.4 `register_pass` (classmethod, L109)
- **Prior:** B+ (R5) — “add duplicate-name warning.”
- **My grade:** **B+** — AGREE.
- **What it does:** `cls.PASS_REGISTRY[definition.name] = definition`. Silent overwrite of duplicates.
- **Reference:** UE5 PCG’s `UPCGGraph::AddNode` errors on duplicate node names; Houdini’s HDA registry also rejects duplicate type-names.
- **Bug/gap:** **L111** — silent overwrite. With 50+ passes across 14 bundles that import in different orders this WILL bite (e.g. two registrars accidentally claiming `"erosion"`). Master audit found `height` is produced by 4 passes — same hazard.
- **AAA gap:** AAA registries log/raise on duplicate.
- **Severity:** polish.
- **Upgrade:** `if definition.name in cls.PASS_REGISTRY: logger.warning("re-registering pass %s", definition.name)`.

### 1.5 `get_pass` (classmethod, L114)
- **Prior:** A- (R5).
- **My grade:** **A-** — AGREE. Raises `UnknownPassError` with the bad name. Trivial and right.

### 1.6 `clear_registry` (classmethod, L120)
- **Prior:** A- (R5).
- **My grade:** **A-** — AGREE. Test helper. Fine.

### 1.7 `require_scene_read` (L126)
- **Prior:** A.
- **My grade:** **A** — AGREE. Raises `SceneReadRequired` with actionable remediation. Models Houdini’s pre-cook validation pattern.

### 1.8 `enforce_protected_zones` (L134)
- **Prior:** A-.
- **My grade:** **A-** — AGREE. Iterates zones, intersects, only raises on FULL cover. Allows partial overlap (per-cell masks handle the rest). Solid policy.
- **Bug/gap:** AABB-only; no polygon zones. R5 already noted. Polygon support would close the gap to UE5 Landscape layer exclusions.
- **Severity:** polish.

### 1.9 `run_pass` (L167) — **HOT FUNCTION**
- **Prior:** A (R1) → A (R5 reaffirmed). R2 disputed → A-.
- **My grade:** **A-** — DISPUTE the R5 A. The R2 dispute is correct and was glossed over.
- **What it does:** Full orchestration: scene-read check → protected zones → input channels → seed derivation → content-hash before → call `definition.func(state, region)` → post-conditions (PassResult type, output channels populated) → quality gate → visual validator → content-hash after → record + checkpoint.
- **Reference:** Houdini PDG `WorkItem` execution model + UE5 PCG node `Execute()`. Both wrap user code in pre/post contracts. The pattern is correct.
- **Bug/gap (file:line):**
  1. **L216–228 NO TRANSACTIONAL ROLLBACK.** If `definition.func` partially mutates the mask stack and then raises, those mutations persist in `state.mask_stack`. `record_pass(failed_result)` runs but the stack is corrupted for any retry. Houdini PDG snapshots work-item state before cook and discards on failure; UE5 PCG does the same via per-node temp data. AAA implementations are transactional; this one is not.
  2. **L240** — `if result.duration_seconds <= 0.0: result.duration_seconds = time.perf_counter() - t0`. A pass that legitimately reports `0.0` (e.g. validator with no work) gets re-stamped. R5 caught this, my R6 confirms.
  3. **L218 `pragma: no cover`** — silently exempts the failure path from coverage. With no test exercising it, the rollback bug above stays invisible.
  4. **L237–239** — `result.pass_name = pass_name` etc. These assignments mutate the dataclass returned by user code; if the pass returned a shared/cached `PassResult` (anti-pattern but legal) we’d corrupt it. Should construct a new `PassResult` in the controller and copy fields over.
  5. **L256–276** — gate logic toggles `result.status = "warning"` even if it was already `"warning"` — dead branch but harmless. The `severity in ("hard",)` literal-string compare relies on convention with no `Severity` enum (`ValidationIssue.severity` is `str`). One typo (`"HARD"` vs `"hard"`) silently downgrades a hard failure.
- **AAA gap:** Houdini TOPs and UE5 PCG both treat partial-failure rollback as table stakes. This implementation will leave you debugging corrupted mask stacks.
- **Severity:** **important** (transactional rollback is a real production hazard).
- **Upgrade:**
  ```python
  before_snapshot = self.state.mask_stack
  worker_stack = copy.deepcopy(before_snapshot)  # or write to temp .npz
  self.state.mask_stack = worker_stack
  try:
      result = definition.func(self.state, region)
  except Exception:
      self.state.mask_stack = before_snapshot
      ...
      raise
  ```
  Replace the `severity == "hard"` string compare with an enum.

### 1.10 `run_pipeline` (L296)
- **Prior:** B+ (consensus).
- **My grade:** **B+** — AGREE.
- **What it does:** Sequential pass execution from `pass_sequence` (default 4-pass A bundle). Stops on first failure.
- **Reference:** Houdini PDG’s `pdg.GraphContext.cook()` accepts a pin-set; UE5 PCG schedules nodes by graph topology — neither requires the user to spell out a flat list.
- **Bug/gap (file:line):**
  - **L296–323** — does NOT consult `PassDAG`. Caller must hand-author a valid order. `run_pipeline(pass_sequence=["erosion"])` with no prior `macro_world` blows up at `PassContractError`. R5 already noted.
  - No parallel tile dispatch.
  - On failure, no auto-rollback to last-good checkpoint despite the checkpoint API being right next to it.
- **AAA gap:** Both Houdini and PCG let you specify *targets* and they derive the topo order. This module has the DAG (`PassDAG`) sitting next door but doesn’t use it.
- **Severity:** polish.
- **Upgrade:** Accept `targets: list[str] | None`; if given, build `PassDAG.from_registry()`, take `topological_order()` filtered to ancestors-of-targets, and execute that. Add `auto_rollback_on_failure=True` option that replays `rollback_last_checkpoint()` on exception.

### 1.11 `_save_checkpoint` (L327)
- **Prior:** A- (consensus).
- **My grade:** **A-** — AGREE.
- **What it does:** Writes `mask_stack.to_npz`, builds `TerrainCheckpoint` with Unity round-trip metadata (`world_bounds`, `height_min/max`, `cell_size`, `tile_size`, `coordinate_system`, `unity_export_schema_version`), parent-link.
- **Reference:** Houdini File Cache SOP / UE5 cooked-asset versioning. Solid.
- **Bug/gap:**
  - **L335** — `uuid.uuid4().hex[:8]` = 32 bits. Birthday-paradox 50% collision around 65k checkpoints. Long iteration sessions can hit it; not catastrophic (just `KeyError` on rollback).
  - **L334** — `mkdir(parents=True, exist_ok=True)` runs every pass. Cheap but unnecessary; cache the mkdir result.
  - No retention policy / pruning. Long sessions accumulate `.npz` files on disk indefinitely.
- **AAA gap:** Unity Addressables and Houdini PDG cache both ship with TTL/LRU eviction.
- **Severity:** polish.
- **Upgrade:** `uuid.uuid4().hex[:16]` (64 bits → astronomical collision space) + add `prune_older_than_n_passes()`.

### 1.12 `rollback_to` (L372)
- **Prior:** B (R5).
- **My grade:** **B** — AGREE.
- **What it does:** Linear search backwards through `state.checkpoints` for `checkpoint_id`, `from_npz` to restore mask stack, truncate history past restore point.
- **Reference:** Houdini PDG dirty-state restoration.
- **Bug/gap:**
  - **L376** — `from_npz` only restores `_ARRAY_CHANNELS` (scalar ndarrays). `wildlife_affinity` and `decal_density` (dict-of-ndarrays) are silently DROPPED on rollback. Master audit confirmed this in `to_npz` but the same bug bites here.
  - **L378–380** — `state.checkpoints.index(ckpt)` is a second `O(n)` scan over the same list we just walked. With 80 checkpoints (production session) this is `O(n²)` rollback.
  - No restoration of `state.water_network`, `state.viewport_vantage`, or any non-mask-stack runtime field. A rollback restores the heightmap but leaves stale river graphs around.
- **AAA gap:** A real undo system snapshots the entire pipeline state, not just one channel array.
- **Severity:** **important** (silent dict-channel data loss + incomplete rollback).
- **Upgrade:** Use a name→index dict during the iteration; serialize dict channels into `.npz` (use `np.savez` with `arr_kind__key` mangled names); snapshot the whole `TerrainPipelineState` (pickle the non-ndarray fields alongside the npz).

### 1.13 `rollback_last_checkpoint` (L384)
- **Prior:** A-.
- **My grade:** **A-** — AGREE. 4-line wrapper. Inherits dict-channel bug from `rollback_to` — fix there.

### 1.14 `register_default_passes` (L395)
- **Prior:** A- (R1) → **B-** (R5 “none of the 4 passes have a quality_gate”).
- **My grade:** **B-** — AGREE with R5. Master audit also flagged this.
- **What it does:** Registers `macro_world`, `structural_masks`, `erosion`, `validation_minimal` with channel contracts and seed namespaces.
- **Reference:** UE PCG node registration.
- **Bug/gap:**
  - All 4 passes have `quality_gate=None` despite `run_pass` having elaborate gate plumbing (L256–276). The gate API exists but is never exercised on the foundation passes — silent quality regression risk for the most-run code path.
  - `produces_channels=("height",)` for `macro_world` (L410) collides with `terrain_banded`, `terrain_framing`, and `terrain_delta_integrator` which all also declare `produces_channels=("height",)`. Combined with `PassDAG.__init__`’s “last producer wins” (L67–68), the resolved producer of `height` is non-deterministic across import orders. **This is a real wire bug** verified at `terrain_banded.py:660`, `terrain_framing.py:157`, `terrain_delta_integrator.py:179`, `terrain_pipeline.py:410`.
  - `respects_protected_zones=False` on `validation_minimal` is correct (read-only), but `may_modify_geometry=False` is implicit/missing on `validation_minimal` and `structural_masks` (defaults are False so it works, but should be explicit for the audit trail).
- **AAA gap:** AAA pipelines have *every* foundation pass guarded by quality assertions (Naughty Dog’s “the build never goes red because the gate stops it before it goes red”). This file ships with the gate-API and 0 gates.
- **Severity:** **important** (no quality enforcement on foundation passes; multi-producer hazard for `height`).
- **Upgrade:** Add 4 gates: `macro_world` → height range sanity; `structural_masks` → slope coverage min; `erosion` → wetness coverage min, no NaN; `validation_minimal` → already a validator. Consider YAML-driven pass profile composition.

---

## 2. terrain_pass_dag.py — wave scheduler

### 2.1 `PassDAGError` (L21)
- **Prior:** not graded individually.
- **My grade:** **A** — exception subclass with docstring.

### 2.2 `_merge_pass_outputs` (L25)
- **Prior:** B+ (R5 NEW).
- **My grade:** **B-** — DISPUTE the B+ down. Memory profile is worse than R5 captured.
- **What it does:** Pulls the `_worker_mask_stack` sentinel out of `metrics`, deep-copies each `produces_channels` entry from worker → controller, updates `populated_by_pass`, recomputes content_hash.
- **Reference:** Standard merge step for fork-join numpy pipelines. Correct alternative is `numpy.copyto(dst, src)` if shapes match, or `dst[...] = src` for in-place overwrite.
- **Bug/gap (file:line):**
  - **L44** — `copy.deepcopy(getattr(source_stack, channel))` per channel. For `height` at 4097×4097 float64 that’s 134 MB allocated AND copied — `copy.deepcopy` on a numpy array recurses through the array’s `__reduce__`/`__deepcopy__` then allocates. `np.array(arr, copy=True)` is roughly 2-3× faster.
  - **L32** — `source_result.metrics.pop("_worker_mask_stack", None)` mutates `metrics` in place. If the caller cached or logged metrics before merge, the sentinel disappears mid-flight. Should be a separate side-channel (e.g. `result.side_effects` is wrong for this; add a private `result._worker_stack` attr or pass it via the future’s return tuple).
  - **L46** — `target_stack.populated_by_pass[channel] = source_result.pass_name` only fires if `getattr(source_stack, channel) is not None`, but the `setattr` on L44 has already run unconditionally. So we can write `None` over an existing value without provenance update — the controller forgets who set the channel.
  - No multi-producer detection: if two parallel waves both produce `height` (which they can — see §1.14), the second overwrite wins silently with no warning.
  - `target_stack.height_min_m = source_stack.height_min_m` (L49) is taken from a single worker even if the worker’s pass didn’t touch height. Stale staleness propagation.
- **AAA gap:** Houdini PDG uses ref-counted attribute promotion — every channel knows its lineage. Here we’re manually `setattr`’ing with no transactional semantics.
- **Severity:** **important** (memory + provenance corruption).
- **Upgrade:** Use `np.array(arr, copy=True)` for ndarray channels; only update `height_min_m` if the worker’s definition declares `height` in produces; track multi-producer conflicts and log/raise.

### 2.3 `PassDAG.__init__` (L62)
- **Prior:** A- (R5).
- **My grade:** **B+** — DISPUTE A- down. The “last producer wins” comment is a load-bearing hazard, not a “stable enough” design.
- **What it does:** Builds `_passes: name→def` and `_producers: channel→pass_name`. Multi-producer: last one wins.
- **Reference:** A real DAG builder uses `producers: dict[channel, list[pass]]`. NetworkX `DiGraph.add_edge(producer, consumer)` happily accepts multi-edges if you let it; topo sort handles it.
- **Bug/gap (file:line):**
  - **L67–68** — `self._producers[ch] = p.name` overwrites silently. In this very codebase, `height` has 4 producers (verified above) — the resolved one depends on dict-iteration order over `self._passes`, which is bundle-import order. Different test runs and different `register_all_terrain_passes` codepaths will resolve different producers and therefore different DAGs. **Determinism violated.**
  - No detection of channels that are produced but never consumed (Bazel calls these “orphan outputs”) or required but never produced (would currently produce a `dependencies()` returning empty set, falsely declaring the consumer “root”).
- **AAA gap:** `networkx.DiGraph` + `simple_cycles` would surface this; UE PCG’s graph compiler asserts on multi-producer pins.
- **Severity:** **important**.
- **Upgrade:**
  ```python
  producers: Dict[str, List[str]] = {}
  for p in passes:
      for ch in p.produces_channels:
          producers.setdefault(ch, []).append(p.name)
  multi = {ch: ps for ch, ps in producers.items() if len(ps) > 1}
  if multi:
      raise PassDAGError(f"channels with multiple producers: {multi}")
  ```
  Or, allow it and emit a `MergeStrategy` enum (`OVERLAY | ADD | LAST_WINS`) per channel.

### 2.4 `from_registry` (L71)
- **Prior:** A (R5).
- **My grade:** **A** — AGREE. Filters by name, raises on missing. Correct.

### 2.5 `names` property (L85)
- **My grade:** **A** — AGREE (trivial accessor).

### 2.6 `dependencies` (L88)
- **Prior:** A.
- **My grade:** **A** — AGREE. Self-loops filtered (`producer != pass_name`); missing producers ignored (returns empty set, which is a feature for root passes but a bug for typo’d channel names — see 2.3 gap).

### 2.7 `topological_order` (L98) + nested `visit` (L104)
- **Prior:** A.
- **My grade:** **A** — AGREE. Classic DFS with `temp` (gray) set for cycle detection, `visited` (black). Iterates `sorted(self._passes.keys())` for determinism — matches NetworkX `lexicographical_topological_sort`. Solid.
- **Bug/gap:** Recursion-based; with 200+ passes you’d hit Python’s default 1000 stack limit. Not realistic for this codebase (~30 passes) but worth noting.
- **AAA gap:** None at current scale.
- **Severity:** none.

### 2.8 `parallel_waves` (L120)
- **Prior:** A.
- **My grade:** **A** — AGREE. Kahn-style layered topo (used by Bazel `-j`, Make `-j`, Buck2). Deterministic.
- **Bug/gap:** Computes wave_index over `topological_order()` but iterates `wave_index.items()` (Python 3.7+ insertion order) which matches topo order. Output is `[sorted(waves[k]) for k in sorted(waves.keys())]` — fully deterministic. Good.

### 2.9 `execute_parallel` (L139) + nested `_runner` (L164)
- **Prior:** B- (R5 — “deepcopy 14 channels × 4 workers = 14 GB”).
- **My grade:** **C+** — DISPUTE B- DOWN. The R5 critique understates the architectural problem.
- **What it does:** For each wave, deep-copies the controller state per pass, runs in `ThreadPoolExecutor`, merges produced channels back in deterministic name order.
- **Reference:** The Python docs verify: ThreadPoolExecutor on CPU-bound numpy gets near-linear speedup *when numpy releases the GIL*. Vectorized numpy (`+`, `*`, `@`) does release; pure-Python loops over arrays do not. Pass functions in this codebase (e.g. `pass_erosion`) are a mix — many include Python loops over flow accumulation, neighbour iteration etc. Actual speedup with 4 threads will be ~1.2×–1.8× at best.
- **Bug/gap (file:line):**
  1. **L165** — `copy.deepcopy(controller.state)` per worker. With a 1024² mask stack, ~14 populated channels at float32–float64, the snapshot is ~150 MB; with a 4097² aaa-quality stack at float64 it is ~3.5 GB *per worker*. With `max_workers=4` the wave allocates 14 GB. Houdini and UE5 use copy-on-write or memory-mapped tiles — **never** per-worker full state copies.
  2. **L174 `ThreadPoolExecutor`** — wrong tool. The user spec explicitly calls this out: “ThreadPoolExecutor on numpy = zero speedup” for the GIL-bound parts. For CPU-bound mixed Python-numpy passes, `ProcessPoolExecutor` is correct, and ndarray channels should ride `multiprocessing.shared_memory.SharedMemory` or `SharedMemoryManager` to avoid pickling 134 MB heightmaps over a pipe.
  3. **L186** — merges in `sorted(wave)` order, but `wave_results` was populated as workers completed (`as_completed` order), and the merge writes channel-by-channel. If two passes in a wave both produce the same channel (multi-producer hazard from §2.3), the merge is **silently order-dependent**. With 4 height-producing passes that could legitimately land in the same wave (e.g. `framing` and `delta_integrator` both consume `height` and produce `height`), wave-internal ordering matters and is not enforced.
  4. **L171** — `result.metrics["_worker_mask_stack"] = worker_controller.state.mask_stack` shoves a multi-MB object into a metrics dict that gets serialized and logged elsewhere. If the controller emits metrics to JSON (telemetry, audit trail), this will either OOM or json-encode-fail. Quick check: nothing currently json-dumps the metrics, but this is a footgun.
  5. **L188** — checkpointing inside the merge loop is sequential, not parallel. Defeats half the purpose of parallel execution if checkpoints are large.
  6. No timeout on `future.result()` — a hung pass hangs the whole wave forever.
  7. No exception handling — if `_runner` raises, the whole `as_completed` loop propagates and *other workers continue running but their results are dropped*. Houdini PDG cancels sibling work items on failure.
- **AAA gap:** Real reference: UE5 PCG’s `FPCGGraphExecutor` uses fiber-based scheduling with persistent point-data caches; never copies the entire graph state. Houdini PDG’s `pdg.scheduler.Scheduler` distributes work items with shared-memory promoted attributes. This implementation’s architecture is closer to a homework assignment than to AAA scheduling.
- **Severity:** **CRITICAL** (memory blowup at AAA tile sizes; wrong concurrency primitive; multi-producer races).
- **Upgrade:**
  - Switch to `ProcessPoolExecutor`.
  - Promote ndarray channels to `multiprocessing.shared_memory.SharedMemory` blocks created by a `SharedMemoryManager`; pass shape+dtype+name to workers.
  - For ndarray-heavy CPU-bound passes, expect ~3.5× on a 4-core machine with shared-memory IPC.
  - Add `merge_strategy` per channel to handle multi-producer waves explicitly (overlay vs additive vs error).
  - Add `executor.submit(..., timeout=...)` and `cancel_futures=True` on shutdown.
  - Either remove parallel execution entirely until the architecture is fixed, or restrict `parallel_waves()` to read-only passes.

---

## 3. terrain_protocol.py — 7-rule gates

### 3.1 `ProtocolViolation` (L32)
- **My grade:** **A** — exception with docstring. Trivial.

### 3.2 `ProtocolGate.rule_1_observe_before_calculate` (L43)
- **Prior:** A (R5).
- **My grade:** **A** — AGREE. `now=None` allows test injection. Negative age clamped to 0 (defensible for clock skew).
- **Bug/gap:** Compares to `time.time()` (wall clock). On systems where `state.intent.scene_read.timestamp` came from `time.monotonic()` they’re in different epochs and check is meaningless. Doc-only — currently `terrain_scene_read.capture_scene_read` does use `time.time()`. Fragile contract not enforced anywhere.
- **Severity:** none (today); polish (cross-source contract).

### 3.3 `rule_2_sync_to_user_viewport` (L68)
- **Prior:** A (R5).
- **My grade:** **B+** — DISPUTE A down.
- **What it does:** Demands `state.viewport_vantage` is not None.
- **Bug/gap (file:line):**
  - **L78** — `getattr(state, "viewport_vantage", None)`. **`TerrainPipelineState` (semantics.py L975) does NOT declare `viewport_vantage`.** The dataclass has only `intent / mask_stack / checkpoints / pass_history / side_effects / water_network`. Searched the codebase: nothing assigns `state.viewport_vantage` either. **Result: this rule will ALWAYS raise `ProtocolViolation` unless the caller passes `out_of_view_ok=True` or monkey-patches the attr.** R5 noted “type-checkers will flag it” but missed that this is a functional bug, not a typing nit.
  - The viewport_vantage sentinel exists in `terrain_scene_read.py` as a payload field, but it lives inside the `scene_read` dict, not on `state`.
- **AAA gap:** A protocol gate that always fails is a wire bug. Rule 2 is effectively dead.
- **Severity:** **important** (silent dead code or always-fire gate).
- **Upgrade:** Either (a) add `viewport_vantage: Optional[Any] = None` to `TerrainPipelineState` *and* a wiring step in the registrar/handler, or (b) read it from `state.intent.scene_read.viewport_vantage` (which is where capture_scene_read actually parks it). The latter is the smaller fix.

### 3.4 `rule_3_lock_reference_empties` (L86)
- **Prior:** A.
- **My grade:** **A** — AGREE. Delegates to `terrain_reference_locks.assert_all_anchors_intact`, raises on drift. Local import to dodge circular dep is acceptable.

### 3.5 `rule_4_real_geometry_not_vertex_tricks` (L105)
- **Prior:** A-.
- **My grade:** **A-** — AGREE.
- **Bug/gap:** **L109** — `hero_kinds = {"cliff", "cave", "waterfall"}` does NOT match `terrain_hierarchy.cinematic_kinds = {"canyon", "waterfall", "arch", "megaboss_arena", "sanctum"}`. Two sources of truth for the same concept. R5 caught it. Confirmed at the file:line cited.
- **Severity:** polish.
- **Upgrade:** Move the canonical set into `terrain_semantics` and import from both call sites.

### 3.6 `rule_5_smallest_diff_per_iteration` (L117)
- **Prior:** A.
- **My grade:** **A** — AGREE. 2% cell threshold + 20-object threshold for the “bulk edit” trip. `state.mask_stack.height.size` for normalisation is correct.

### 3.7 `rule_6_surface_vs_interior_classification` (L144)
- **Prior:** A.
- **My grade:** **A** — AGREE. Iterates `placements`, validates each `placement_class` against frozenset. Handles non-list (silently returns) and non-dict items (skips) — slightly forgiving but not buggy.

### 3.8 `rule_7_plugin_usage` (L164)
- **Prior:** A.
- **My grade:** **A** — AGREE. Delegates to `terrain_addon_health.assert_addon_version_matches`. The `params` arg is ignored — fine, kept for interface symmetry with other rules.

### 3.9 `enforce_protocol` decorator (L177) + `decorator` (L195) + `wrapper` (L197)
- **Prior:** B+ (R5).
- **My grade:** **B+** — AGREE.
- **What it does:** Per-rule kwargs let tests opt-out; wraps a `(state, params, *args, **kwargs)` callable so all 7 gates fire pre-body.
- **Bug/gap:**
  - **L203** — `params = dict(params or {})` materialises a defensive copy — good. But subsequent rule calls pass `params` directly, mutating the copy on rule_5 (no, actually they read; safe).
  - The wrapper signature requires `state` as first positional and `params` as second. Decorators applied to handlers with different signatures (e.g. some MCP handlers take `payload: dict` only) will silently mismatch — `state` becomes the payload and `params` becomes `None`. Should `inspect.signature(fn)` validate at decorate-time.
  - All 7 rules default to ON; for unit-test scaffolds you must remember 7 toggles. A `protocol_profile: Literal["strict", "relaxed", "test"]` would be cleaner.
- **AAA gap:** Decorator is fine, just brittle to misuse.
- **Severity:** polish.

---

## 4. terrain_master_registrar.py

### 4.1 `_safe_import_registrar` (L47)
- **Prior:** A (R5).
- **My grade:** **A** — AGREE. Logs `Failed to import bundle registrar X.Y: <exc>` on any Exception, returns None. Matches Fix M5.
- **Bug/gap:** Catches bare `Exception` — will eat `KeyboardInterrupt`’s parent if you change to `BaseException`. As-is it correctly leaves Ctrl+C uncaught. Fine.

### 4.2 `register_all_terrain_passes` (L72)
- **Prior:** A (R5).
- **My grade:** **A** — AGREE. Backward-compat shim around `_detailed`. Returns `loaded` list with `LABEL:SKIPPED(reason)` entries. Clean.

### 4.3 `register_all_terrain_passes_detailed` (L100)
- **Prior:** A (R5).
- **My grade:** **A** — AGREE. Returns `(loaded, errors)` tuple — the right shape for callers that need structured failure info.

### 4.4 `_register_all_terrain_passes_impl` (L115)
- **Prior:** B+ (R5).
- **My grade:** **B** — DISPUTE B+ down. Two real bugs.
- **What it does:** Hard-imports Bundle A (`terrain_pipeline.register_default_passes`), then loops 16 bundles via `_safe_import_registrar`.
- **Bug/gap (file:line):**
  - **L123** — `from .terrain_pipeline import register_default_passes` is hard-imported. If `terrain_pipeline` import fails (circular dep, syntax error in a sibling), the entire master registrar dies at this line with no entry in `errors` and no warning logged. R5 caught it; Bundle A should also go through `_safe_import_registrar` for symmetry.
  - **L128** — `package_root = __package__ or "blender_addon.handlers"`. The package is **`veilbreakers_terrain.handlers`** in this codebase (verified by repo path). The fallback string is stale and would silently mis-resolve every bundle if `__package__` were ever empty (e.g. if invoked via a script that imports the file directly). Confirmed by `Glob` — there is no `blender_addon` package anywhere.
  - **L130–147** — registrars list is hardcoded. Adding a Bundle P or splitting Bundle B further requires a code edit. A YAML manifest (`registrars.yaml`) read at startup would make bundles plug-in style, matching the “bundle inventory” comment intent.
  - **L154** — On success, appends label only; on registrar `Exception`, appends `f"{label}:SKIPPED({exc!r})"`. If a downstream tool greps for bundle labels it will silently misparse the SKIPPED entries.
  - **L165** — When `strict=True` and a registrar isn’t found, raises `ImportError`. But because `loaded` already contains "A" and possibly other bundles, the partial state of `PASS_REGISTRY` is left half-populated — no transactional cleanup. A retry will see duplicate registrations (which silently overwrite per §1.4).
- **AAA gap:** UE5 plugin loader records every load attempt and rolls back on partial-failure. This implementation half-loads.
- **Severity:** **polish** (stale fallback string, hard-import of A, no rollback). Bumped to a B because the stale fallback is an actual latent bug.
- **Upgrade:** Make Bundle A go through `_safe_import_registrar`; remove the stale `"blender_addon.handlers"` fallback (or compute the correct fallback via `__name__.rpartition(".")[0]`); add a YAML/TOML manifest; clear the registry on `strict=True` failure.

---

## 5. terrain_semantics.py — data contracts

### 5.1 `ErosionStrategy` (enum, L41)
- **Prior:** not graded.
- **My grade:** **A** — clear 3-value enum (`EXACT`, `TILED_PADDED`, `TILED_DISTRIBUTED_HALO`). Matches Addendum 3.B.1.

### 5.2 `SectorOrigin` (L56)
- **Prior:** A (R5 NEW).
- **My grade:** **A** — AGREE. Frozen dataclass for floating-origin anchor; matches Star Citizen / Cesium’s solution.

### 5.3 `WorldHeightTransform` (L70) + `__post_init__` (L83) + `to_normalized` (L90) + `from_normalized` (L94)
- **Prior:** A.
- **My grade:** **A** — AGREE. Vectorized numpy, zero-range guard. Solves the persistent scatter-altitude bug per Addendum 3.B.6. Critical infrastructure.
- **Bug/gap:** `__post_init__` mutates `world_min/max/range` via direct assignment — this is fine on a non-frozen dataclass, but the class is mutable (no `frozen=True`). Anywhere downstream that hashes or treats it as a value will be surprised.
- **Severity:** none.

### 5.4 `BBox` (L105) + `__post_init__` (L117) + `width`/`height`/`center` (L125–135) + `to_tuple` (L136) + `contains_point` (L139) + `intersects` (L142) + `to_cell_slice` (L150)
- **Prior:** A.
- **My grade:** **A** — AGREE. Frozen dataclass, validates `max >= min`, full AABB API + numpy grid bridge. Standard.
- **Bug/gap:** `to_cell_slice` uses `np.floor`/`np.ceil`/`+1` for the upper bound — produces inclusive-of-boundary slices that match numpy convention. Edge case: a BBox exactly equal to the grid edge gives `c1 = cols + 1` then `min(cols, ...)` clamps. Correct.

### 5.5 `HeroFeatureRef` (L167) / `WaterfallChainRef` (L177) / `HeroFeatureBudget` (L187)
- **Prior:** A.
- **My grade:** **A** — AGREE. Frozen dataclasses with reasonable fields.

### 5.6 `TerrainMaskStack` class (L201) — **the central data structure**
- **Prior:** A- (R2 dispute over B+, accepted).
- **My grade:** **A-** — AGREE.
- **What it is:** 60+ typed channels spanning 10 pass families, provenance map, dirty-channel set, Unity export manifest, content-hash, npz round-trip, tile-resolution contract enforcement.
- **Reference:** No 1:1 in Houdini (volumes use VDB grids per channel) or PCG (point-data with attribute set). Closest analogue: Substance Designer’s “channel stack” + Mari’s “channel cache”.
- **Bug/gap:** see per-method audits below.

### 5.7 `TerrainMaskStack.__post_init__` (L399)
- **Prior:** A (implicit).
- **My grade:** **A-** — AGREE-ish; one nit.
- **Bug/gap:**
  - **L410–413** — auto-populates `height_min_m/max_m` from current heights. As soon as another pass mutates `height`, these scalars go stale (the dataclass has no setter to invalidate them). Master audit already flagged this. Compute_hash includes them in the header (L564–565), so cache-keying becomes wrong post-mutation.
  - **L424–436** — tile-resolution contract is well-meaning but only enforced when `h.shape[0] == h.shape[1]`. A non-square shape silently bypasses. Acceptable for the legacy escape hatch but worth a debug log.
- **Severity:** important (stale height_min/max → wrong content_hash → cache poisoning).
- **Upgrade:** turn `height_min_m/max_m` into `@property` derived from `height`, OR add `mark_height_dirty()` that recomputes them.

### 5.8 `get` (L440)
- **Prior:** A.
- **My grade:** **A** — AGREE. Supports `channel[key]` for dict channels (`wildlife_affinity[wolf]`, `decal_density[scorch]`). Clean.

### 5.9 `set` (L455)
- **Prior:** B+ (R5 — “no dtype check”).
- **My grade:** **B+** — AGREE.
- **Bug/gap:** No dtype/shape validation. A pass can set `terrain_normals` (declared `float32 (H,W,3)`) to a `uint8 (H,W,1)` and it sticks until Unity export blows up. Trivial mistake to make and hard to debug. Should validate at write time when the channel has a declared schema.
- **Severity:** polish.

### 5.10 `mark_dirty` (L465) / `mark_clean` (L469)
- **My grade:** **A** — trivial set ops with content_hash invalidation.

### 5.11 `assert_channels_present` (L472)
- **Prior:** A.
- **My grade:** **A** — AGREE. Raises `KeyError` with the missing list.

### 5.12 `unity_export_manifest` (L503)
- **Prior:** A.
- **My grade:** **A** — AGREE. Returns the dict the Unity importer needs (schema, coord, tile, world_origin, height range, populated channels, content_hash). `world_tile_extent_m` is helpful redundancy.
- **Bug/gap:** Iterates `UNITY_EXPORT_CHANNELS` only (no `dirty_channels` cross-check) — if a channel was marked dirty since the last `set`, the manifest reports it as if it were clean. Minor.

### 5.13 `compute_hash` (L546)
- **Prior:** A.
- **My grade:** **A** — AGREE. SHA-256 over header + each populated `_ARRAY_CHANNELS` (name, dtype, shape, raw bytes) + dict channels in sorted-key order. Deterministic. `np.ascontiguousarray` ensures stride-independent bytes.
- **Bug/gap:** Mutates `self.content_hash = digest` — side effect inside a “compute” method. Defensible (cache), but a nit.

### 5.14 `to_npz` (L600)
- **Prior:** B (R5 — “drops dict channels”).
- **My grade:** **B** — AGREE.
- **Bug/gap:** Master audit + R5 confirmed: serialises only `_ARRAY_CHANNELS`. `wildlife_affinity` and `decal_density` (dict-of-ndarray) are silently dropped. Round-trip via `from_npz` then loses these channels — a checkpoint cycle erases ecosystem data.
- **Severity:** **important** (silent data loss on every checkpoint).
- **Upgrade:** Mangle dict-channel keys into the npz namespace: `for k, v in self.wildlife_affinity.items(): arrays[f"wildlife_affinity__{k}"] = v` and reverse on load.

### 5.15 `from_npz` (classmethod, L625)
- **Prior:** B+ (R5).
- **My grade:** **B+** — AGREE. Same dict-channel limitation; otherwise correctly restores `populated_by_pass`, `dirty_channels`, `schema_version`.
- **Bug/gap:** **L633–639** does NOT restore `height_min_m`/`height_max_m`/`coordinate_system`/`unity_export_schema_version` — they’ll be auto-recomputed in `__post_init__`. For `coordinate_system` that means a `y-up` checkpoint reloads as `z-up` (default). Cross-coordinate round-trip BUG.
- **Severity:** important.
- **Upgrade:** persist the four scalars in `meta` and pass them into the `cls(...)` call.

### 5.16 `ProtectedZoneSpec` + `permits` (L657, L667)
- **Prior:** A.
- **My grade:** **A** — AGREE. Forbidden > allowed > default-allow priority.

### 5.17 `TerrainAnchor` (L681)
- **Prior:** A.
- **My grade:** **A** — AGREE.

### 5.18 `HeroFeatureSpec` (L698)
- **Prior:** A.
- **My grade:** **A** — AGREE. `parameters: Dict[str, Any]` on a frozen dataclass with `field(default_factory=dict)` — looks suspect but is standard pattern; `frozen=True` only forbids reassigning the field, not mutating the dict in place. Caller-discipline contract.

### 5.19 `WaterSystemSpec` (L720)
- **Prior:** A.
- **My grade:** **A** — AGREE.

### 5.20 `TerrainSceneRead` (L746)
- **Prior:** A.
- **My grade:** **A** — AGREE. Frozen, all the fields the protocol needs.

### 5.21 `TerrainIntentState` (L772) + `with_scene_read` (L794) + `intent_hash` (L800)
- **Prior:** A.
- **My grade:** **A** — AGREE.
- **Bug/gap:** `composition_hints: Dict[str, Any]` on a frozen dataclass — the inline `# REVIEW-IGNORE` comment acknowledges it. `intent_hash` does `sorted(self.composition_hints.items())` which means non-comparable keys (mixing strs and ints) would crash here. Defensive but currently uncalled.

### 5.22 `ValidationIssue` (L837) + `is_hard` (L845)
- **Prior:** A.
- **My grade:** **A** — AGREE. `severity: str` is brittle — should be `Literal["hard", "soft", "info"]` or an Enum. Master audit found `terrain_validation.py:554` constructs this with kwargs (`category`, `hard`) that DO NOT EXIST on the dataclass. **Confirmed BLOCKER cross-file**: the dataclass at L837 has fields `(code, severity, location, affected_feature, message, remediation)`. Calling with `category="readability", hard=False` raises `TypeError: __init__() got an unexpected keyword argument 'category'` at runtime.
- **Severity (cross-file):** **CRITICAL** — see Master Audit row 743.

### 5.23 `PassResult` (L855) + `ok` (L870)
- **Prior:** A.
- **My grade:** **A** — AGREE. Complete instrumentation surface.

### 5.24 `TerrainCheckpoint` (L880)
- **Prior:** A.
- **My grade:** **A** — AGREE. Unity round-trip metadata in dataclass form.

### 5.25 `QualityGate` (L909)
- **Prior:** A.
- **My grade:** **A** — AGREE. `name + check + description + blocking`. Right shape. Sad that no foundation pass uses one (see §1.14).

### 5.26 `PassDefinition` (L935)
- **Prior:** A.
- **My grade:** **A** — AGREE. 14 typed fields covering channel contracts, behaviour flags, scene-read requirement, gates, visual validators. The contract surface for the entire pipeline.
- **Bug/gap:** No `merge_strategy` field for multi-producer channels — see §2.3.

### 5.27 `TerrainPipelineState` (L975) + `tile_x`/`tile_y` (L993, L997) + `record_pass` (L1000)
- **Prior:** A.
- **My grade:** **A-** — DISPUTE A down. Real wiring gap.
- **Bug/gap:** **NO `viewport_vantage` field** despite `terrain_protocol.rule_2` reading it. See §3.3 — Rule 2 is currently dead. Fix is one line here:
  ```python
  viewport_vantage: Optional[Any] = None
  ```
- **Severity:** **important** (wiring disconnection).

### 5.28 Custom exceptions (L1009–L1022)
- **My grade:** **A** — clean subclassing. `UnknownPassError` extends `KeyError` (so `KeyError` catchers work), others extend `RuntimeError`. Sensible.

---

## 6. Summary table

| File | Func / Class | Line | Prior | My grade | Verdict |
|---|---|---|---|---|---|
| terrain_pipeline.py | _make_gate_issue | 46 | B/A- | A- | AGREE |
| terrain_pipeline.py | derive_pass_seed | 55 | A | A | AGREE |
| terrain_pipeline.py | TerrainPassController.__init__ | 93 | A | A | AGREE |
| terrain_pipeline.py | register_pass | 109 | B+ | B+ | AGREE |
| terrain_pipeline.py | get_pass | 114 | A- | A- | AGREE |
| terrain_pipeline.py | clear_registry | 120 | A- | A- | AGREE |
| terrain_pipeline.py | require_scene_read | 126 | A | A | AGREE |
| terrain_pipeline.py | enforce_protected_zones | 134 | A- | A- | AGREE |
| terrain_pipeline.py | run_pass | 167 | A | **A-** | DISPUTE — no transactional rollback |
| terrain_pipeline.py | run_pipeline | 296 | B+ | B+ | AGREE |
| terrain_pipeline.py | _save_checkpoint | 327 | A- | A- | AGREE |
| terrain_pipeline.py | rollback_to | 372 | B | B | AGREE — dict-channel data loss |
| terrain_pipeline.py | rollback_last_checkpoint | 384 | A- | A- | AGREE |
| terrain_pipeline.py | register_default_passes | 395 | B- | B- | AGREE — multi-producer hazard for `height` |
| terrain_pass_dag.py | _merge_pass_outputs | 25 | B+ | **B-** | DISPUTE — provenance corruption + memory |
| terrain_pass_dag.py | PassDAG.__init__ | 62 | A- | **B+** | DISPUTE — non-deterministic “last producer wins” |
| terrain_pass_dag.py | from_registry | 71 | A | A | AGREE |
| terrain_pass_dag.py | dependencies | 88 | A | A | AGREE |
| terrain_pass_dag.py | topological_order | 98 | A | A | AGREE |
| terrain_pass_dag.py | parallel_waves | 120 | A | A | AGREE |
| terrain_pass_dag.py | execute_parallel | 139 | B- | **C+** | DISPUTE — wrong concurrency primitive, 14 GB blowup at 4097² |
| terrain_protocol.py | rule_1_observe_before_calculate | 43 | A | A | AGREE |
| terrain_protocol.py | rule_2_sync_to_user_viewport | 68 | A | **B+** | DISPUTE — reads field that doesn’t exist |
| terrain_protocol.py | rule_3_lock_reference_empties | 86 | A | A | AGREE |
| terrain_protocol.py | rule_4_real_geometry_not_vertex_tricks | 105 | A- | A- | AGREE — `hero_kinds` mismatch |
| terrain_protocol.py | rule_5_smallest_diff_per_iteration | 117 | A | A | AGREE |
| terrain_protocol.py | rule_6_surface_vs_interior_classification | 144 | A | A | AGREE |
| terrain_protocol.py | rule_7_plugin_usage | 164 | A | A | AGREE |
| terrain_protocol.py | enforce_protocol decorator | 177 | B+ | B+ | AGREE |
| terrain_master_registrar.py | _safe_import_registrar | 47 | A | A | AGREE |
| terrain_master_registrar.py | register_all_terrain_passes | 72 | A | A | AGREE |
| terrain_master_registrar.py | register_all_terrain_passes_detailed | 100 | A | A | AGREE |
| terrain_master_registrar.py | _register_all_terrain_passes_impl | 115 | B+ | **B** | DISPUTE — stale fallback, hard-import A, no rollback |
| terrain_semantics.py | ErosionStrategy | 41 | — | A | NEW |
| terrain_semantics.py | SectorOrigin | 56 | A | A | AGREE |
| terrain_semantics.py | WorldHeightTransform | 70 | A | A | AGREE |
| terrain_semantics.py | BBox + methods | 105 | A | A | AGREE |
| terrain_semantics.py | HeroFeatureRef | 167 | A | A | AGREE |
| terrain_semantics.py | WaterfallChainRef | 177 | A | A | AGREE |
| terrain_semantics.py | HeroFeatureBudget | 187 | A | A | AGREE |
| terrain_semantics.py | TerrainMaskStack (class) | 201 | A- | A- | AGREE |
| terrain_semantics.py | TerrainMaskStack.__post_init__ | 399 | — | **A-** | NEW — stale height_min/max |
| terrain_semantics.py | TerrainMaskStack.get | 440 | A | A | AGREE |
| terrain_semantics.py | TerrainMaskStack.set | 455 | B+ | B+ | AGREE |
| terrain_semantics.py | mark_dirty / mark_clean | 465 | A | A | AGREE |
| terrain_semantics.py | assert_channels_present | 472 | A | A | AGREE |
| terrain_semantics.py | unity_export_manifest | 503 | A | A | AGREE |
| terrain_semantics.py | compute_hash | 546 | A | A | AGREE |
| terrain_semantics.py | to_npz | 600 | B | B | AGREE — dict channels dropped |
| terrain_semantics.py | from_npz | 625 | B+ | **B+** | AGREE — also drops `coordinate_system`, `height_min/max_m`, `schema_version` |
| terrain_semantics.py | ProtectedZoneSpec.permits | 667 | A | A | AGREE |
| terrain_semantics.py | TerrainAnchor | 681 | A | A | AGREE |
| terrain_semantics.py | HeroFeatureSpec | 698 | A | A | AGREE |
| terrain_semantics.py | WaterSystemSpec | 720 | A | A | AGREE |
| terrain_semantics.py | TerrainSceneRead | 746 | A | A | AGREE |
| terrain_semantics.py | TerrainIntentState + methods | 772 | A | A | AGREE |
| terrain_semantics.py | ValidationIssue + is_hard | 837 | A | A | AGREE — but cross-file misuse is BLOCKER |
| terrain_semantics.py | PassResult + ok | 855 | A | A | AGREE |
| terrain_semantics.py | TerrainCheckpoint | 880 | A | A | AGREE |
| terrain_semantics.py | QualityGate | 909 | A | A | AGREE |
| terrain_semantics.py | PassDefinition | 935 | A | A | AGREE |
| terrain_semantics.py | TerrainPipelineState + props + record_pass | 975 | A | **A-** | DISPUTE — no `viewport_vantage` field |
| terrain_semantics.py | Custom exceptions | 1009 | A | A | AGREE |

**Disputes:** 8 (mostly downgrades).

---

## 7. Cross-file findings (CRITICAL / IMPORTANT)

| # | Severity | Where | Finding |
|---|---|---|---|
| 1 | **CRITICAL** | `terrain_pass_dag.py:174` + `:165` | `ThreadPoolExecutor` + per-worker `deepcopy(controller.state)` allocates ~14 GB on a 4097² mask stack with 4 workers. AAA pipelines use shared-memory IPC + ProcessPoolExecutor. Disable parallel execution or rewrite. |
| 2 | **CRITICAL** | `terrain_pass_dag.py:67-68` ↔ `terrain_pipeline.py:410`, `terrain_banded.py:660`, `terrain_framing.py:157`, `terrain_delta_integrator.py:179` | `height` is produced by 4 passes; `PassDAG.__init__` silently picks the last one (import-order dependent). DAG resolution is non-deterministic across builds. |
| 3 | **CRITICAL** (cross-file) | `terrain_validation.py:554` ↔ `terrain_semantics.py:837` | Validation calls `ValidationIssue(severity="warning", category="readability", ..., hard=False)`, but the dataclass has neither `category` nor `hard` fields. Runtime `TypeError`. (Already on master audit, repeated here for completeness.) |
| 4 | important | `terrain_protocol.py:78` ↔ `terrain_semantics.py:975` | `rule_2_sync_to_user_viewport` reads `state.viewport_vantage`; the field doesn’t exist on `TerrainPipelineState`. Rule is permanently dead unless `out_of_view_ok=True`. |
| 5 | important | `terrain_pipeline.py:216-228` | `run_pass` has no transactional rollback — partial mask-stack mutations on exception persist. |
| 6 | important | `terrain_semantics.py:600` (`to_npz`) | Drops dict-channels (`wildlife_affinity`, `decal_density`) every checkpoint cycle. |
| 7 | important | `terrain_semantics.py:625` (`from_npz`) | Drops `coordinate_system`, `height_min_m`, `height_max_m`, `unity_export_schema_version` on load — a y-up checkpoint reloads as z-up. |
| 8 | important | `terrain_pipeline.py:372` (`rollback_to`) | O(n²) scan; restores only mask_stack; doesn’t reset `water_network`/`viewport_vantage`. |
| 9 | important | `terrain_pipeline.py:395` (`register_default_passes`) | None of the 4 foundation passes have `quality_gate=...`; the gate API exists and is unused on the most-run code path. |
| 10 | important | `terrain_pass_dag.py:25` (`_merge_pass_outputs`) | Provenance corruption: `setattr(stack, channel, deepcopy(None))` writes None over an existing channel without updating `populated_by_pass`. |
| 11 | important | `terrain_master_registrar.py:115` (`_register_all_terrain_passes_impl`) | Stale fallback `"blender_addon.handlers"` — package is `veilbreakers_terrain.handlers`. Bundle A hard-imported with no error capture. |
| 12 | polish | `terrain_pipeline.py:109` | `register_pass` silently overwrites duplicates. |
| 13 | polish | `terrain_protocol.py:109` | `hero_kinds` set diverges from `terrain_hierarchy.cinematic_kinds`. |
| 14 | polish | `terrain_semantics.py:455` | `set` accepts any dtype/shape — no schema check. |

---

## 8. AAA-vs-this-codebase

| Capability | Houdini PDG / TOPs | UE5 PCG | This codebase |
|---|---|---|---|
| DAG topological sort | Built-in, supports multi-edge with explicit merge | Asserts on multi-producer pin | **Silent “last producer wins”** |
| Parallel scheduling | Schedulers (Local, HQueue, Deadline) with shared-memory promoted attrs | Fiber-scheduled, persistent point-data caches | `ThreadPoolExecutor` + per-worker `deepcopy` |
| Per-work-item caching | Hash-keyed file cache with TTL | Content-hash cache with eviction | SHA-256 hashes computed; **no cache lookup uses them** |
| Transactional rollback | Per-work-item temp + discard on failure | Per-node temp data | **No rollback at all** |
| Quality gates | Asserts inside HDAs / TOP filters | PCG node validators | API exists, **0 foundation passes use it** |
| Dict / variant attrs serialised | Yes (per-attr type promotion) | Yes (PCG metadata) | **Silently dropped on `to_npz`** |
| Determinism guarantees | Full (work item hash) | Per-node seed domain | Per-pass seed correct; DAG resolution non-deterministic |
| Memory for ndarray IPC | shared file caches / VDB grids | Persistent point-data | per-worker `deepcopy` (no shared mem) |

**Honest summary:** the *contracts and dataclasses* (`terrain_semantics.py`) are AAA-quality. The *orchestration glue* (`terrain_pipeline.py`, `terrain_pass_dag.py`) is closer to a competent prototype than to Houdini PDG / UE PCG. Three of the most-cited features (parallel execution, DAG resolution, rollback) have load-bearing bugs that won’t survive a 4097² production tile.

---

## 9. Top 5 fixes if you only do five

1. **Delete or quarantine `PassDAG.execute_parallel`** until it has shared-memory IPC and `ProcessPoolExecutor`. Today it will OOM at AAA tile sizes and provides minimal speedup at smaller ones (GIL-bound numpy mixed Python passes).
2. **Fix `PassDAG.__init__` multi-producer policy** — error on collisions OR add a `MergeStrategy` per channel. Without this, `height`’s producer is non-deterministic.
3. **Add `viewport_vantage: Optional[Any] = None`** to `TerrainPipelineState` (or rewrite `rule_2` to read `state.intent.scene_read.viewport_vantage`). Rule 2 is currently dead.
4. **Add transactional rollback to `run_pass`** — snapshot before, restore on exception. Otherwise partial mutations corrupt the next pass.
5. **Fix `to_npz` / `from_npz` dict-channel drop and metadata drop.** Persist `wildlife_affinity`, `decal_density`, `coordinate_system`, `height_min/max_m`, `unity_export_schema_version`. Otherwise every checkpoint silently destroys ecosystem data and may flip y-up/z-up.

(Bonus 6th: attach `quality_gate=...` to the four foundation passes registered in `register_default_passes`.)
