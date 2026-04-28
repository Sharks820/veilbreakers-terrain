# I6 — Concurrency & Global Mutable State Audit (2026-04-27)

**Scope:** All five areas: module-level mutable state, PYTHONHASHSEED leakage,
random-seed propagation, async/thread safety in providers, file-system race
conditions. Cross-references the known D8 determinism findings and the master
guide P0 list.

**Verdict:** **6 confirmed P0 blockers** (3 brand-new, 3 confirming/extending
D8) plus **9 P1** plus **5 P2**. The codebase has solid intent on determinism
(`derive_pass_seed`, atomic checkpoint writes, `terrain_rng.make_rng`) but
several modules bypass it, the only multi-threaded code path
(Hunyuan3D2Provider) leaks per-call temp dirs and a wider list of helpers
write JSON / GLB / npy non-atomically. There is **no AAA-grade story** for
running two parallel terrain generations in one Python process — module-level
`id()`-keyed registries will silently collide.

---

## 1. P0 Findings

### P0-I6-1 — `id()`-keyed checkpoint registries collide on object recycling
**File:** `veilbreakers_terrain/handlers/terrain_checkpoints.py:50–55, 163, 177, 184, 574–635`

```python
_LABEL_REGISTRY: Dict[int, Dict[str, str]] = {}
_AUTOSAVE_CONTROLLERS: Dict[int, bool] = {}
_ORIGINAL_RUN_PASS: Dict[int, Callable[..., PassResult]] = {}
```

These three module-level dicts are keyed on `id(controller)`. CPython's
`id()` is the memory address; once a controller is garbage-collected the
address is reused by the next allocation, and this code never deletes the
old entry. A second controller created after the first is freed will see:
- the previous controller's labels in `list_checkpoints()`,
- a stale `_AUTOSAVE_CONTROLLERS[key] = True` flag, so `autosave_after_pass`
  will treat the fresh controller as already wrapped and skip wiring,
- a stale `_ORIGINAL_RUN_PASS[key]` containing a *bound method of a freed
  object* — disabling autosave then assigns a dead callable to the live
  controller's `run_pass`.

This is not theoretical: the existing tests instantiate controllers per test
function and rely on GC ordering. None of the dicts are protected by a
threading.Lock either, so two parallel generations sharing this module (the
common case in any worker/queue setup) will corrupt each other's labels.

**Fix:** Use `WeakKeyDictionary` keyed on the controller object (controllers
are not frozen — they are plain `class` instances and weak-refable), and
guard mutation with a single `threading.Lock()` at module scope. Drop the
`id()` indirection entirely.

**Severity:** P0 — silent label/autosave bleed-through across pipeline runs;
violates AAA reproducibility bar.

---

### P0-I6-2 — Hardcoded `np.random.default_rng()` seeds ignore `intent.seed`
**Files:**
- `veilbreakers_terrain/handlers/terrain_stratigraphy.py:420` — `rng = np.random.default_rng(0)`
- `veilbreakers_terrain/handlers/terrain_stratigraphy.py:569` — `rng = np.random.default_rng(1)`
- `veilbreakers_terrain/handlers/terrain_stratigraphy.py:794` — `rng = np.random.default_rng(42)`
- `veilbreakers_terrain/handlers/terrain_palette_extract.py:106` — `rng = np.random.default_rng(0)`

Each of these is invoked when the caller does **not** supply a `rng`/`seed`
argument. The default branch silently overrides the user's `intent.seed`,
so:
- changing `intent.seed` from 42 → 99 produces *the same* fold deformation
  on line 420 (every world plays back the identical fold pattern),
- the same intrusion mask on line 569,
- the same fallback 7-layer canonical column on line 794,
- the same kmeans palette init on line 106 (palette never varies between
  worlds).

This directly contradicts the user-facing contract that `intent.seed`
controls every variation in the world.

The neighbouring code in this module already uses
`np.random.default_rng(seed ^ 0x53747261)` (line 952, "Stra") and
`seed ^ 0x466F6C64` ("Fold", line 972), which is the correct pattern. The
default branches need the same treatment plus a seed argument plumbed
through.

**Fix:** Make `rng` mandatory (or accept `seed: int`), derive via
`derive_pass_seed(intent.seed, "stratigraphy_fold", tile_x, tile_y, region)`
inside the caller, and remove the hardcoded numeric defaults.

**Severity:** P0 — user loses control of variation, confirmed by D8.
Master guide already lists these locations. Re-confirmed during sweep.

---

### P0-I6-3 — `_LP_STATE` and `_HR_STATE` live-preview / hot-reload globals are unprotected
**File:** `veilbreakers_terrain/handlers/__init__.py:566, 602, 649, 657, 665`

```python
_LP_STATE: Dict[str, Any] = {"session": None}     # holds LivePreviewSession
_HR_STATE: Dict[str, Any] = {"watcher": None}     # holds HotReloadWatcher
```

These are defined **inside** `_build_command_handlers()` but captured by
five long-lived MCP handler closures (`terrain_preview_apply`,
`terrain_preview_state`, `terrain_preview_reset`, `terrain_preview_diff`,
`terrain_preview_render_thumbnail`, plus three `terrain_hot_reload_*`
handlers). Because the dispatch table itself is module-level
(`COMMAND_HANDLERS`), the closures keep `_LP_STATE`/`_HR_STATE` alive for
the lifetime of the addon — they are de-facto module globals.

The MCP socket server (`socket_server.py`) accepts concurrent JSON-RPC
clients. Two clients hitting `terrain_preview_apply` in parallel will
race on:
- `sess = _LP_STATE.get("session")` then `_LP_STATE["session"] = sess`
  — last-writer-wins, intermediate session can leak,
- `sess.apply_edit(edit)` mutates the shared `LivePreviewSession.history`
  list and `mask_stack` numpy buffers — no lock,
- `_handle_terrain_preview_reset` sets the session to `None` in the
  middle of another client's apply call — `AttributeError` on `current_hash()`.

`HotReloadWatcher` similarly has no thread safety; its `check_and_reload`
re-imports modules under a parallel reader.

**Fix:** Put a single `threading.RLock` around `_LP_STATE` access and around
the watcher; or scope the session per-MCP-connection (best). At minimum,
the `_LP_STATE["session"] = None` reset must be guarded.

**Severity:** P0 — MCP is the live editing surface for AAA work; concurrent
edits corrupt mask stacks.

---

### P0-I6-4 — `pass_validation_full` global `_ACTIVE_CONTROLLER` rolls back the wrong pipeline
**File:** `veilbreakers_terrain/handlers/terrain_validation.py:1976–2049`

```python
_ACTIVE_CONTROLLER: Optional[TerrainPassController] = None
_ACTIVE_CONTROLLER_CTX: contextvars.ContextVar[...] = ContextVar(...)
```

`bind_active_controller()` sets *both* the `ContextVar` (correct for async/
thread isolation) **and** a plain module-level global. `_get_active_controller`
prefers the ContextVar but falls back to the global. Two parallel pipelines
running in a thread pool that both call `bind_active_controller(self)` will:
1. Each set `_ACTIVE_CONTROLLER_CTX` correctly in their own context — fine.
2. *Both* clobber `_ACTIVE_CONTROLLER` — last-writer-wins.
3. If a worker forgets to set the ContextVar (e.g., enters via a callback
   that propagated `copy_context()` differently), the fallback rolls back
   the **other** pipeline's controller.

The rollback is destructive: `ctrl.rollback_last_checkpoint()` rewrites
`state.mask_stack` from disk. A misrouted rollback wipes a sibling
pipeline's pass output.

**Fix:** Delete the plain global. ContextVar is sufficient and is what's
already wired. The `_ACTIVE_CONTROLLER` global is a footgun left behind
when the ContextVar was added.

**Severity:** P0 — silent cross-pipeline data destruction.

---

### P0-I6-5 — Hunyuan3D2 `submit()` leaks tempdirs and never frees `_jobs`
**File:** `veilbreakers_terrain/providers/hunyuan3d2_provider.py:139–323`

The provider's job table is correctly locked:
```python
self._jobs: Dict[str, Tuple[threading.Thread, dict]] = {}
self._jobs_lock = threading.Lock()
```
but it is **never pruned**. Every call to `submit()` adds an entry; nothing
removes them. Long-running addon sessions accumulate completed-job entries
indefinitely, each holding a reference to a tempdir Path and a daemon
Thread object. The companion `download()` only `shutil.rmtree`s
`glb_tmp.parent` (the tmpdir), which is the *destination* directory created
by `_hf_generate_blocking`, **not** the `tmp_dir = Path(tempfile.mkdtemp(...))`
allocated at `submit()` line 265. That mkdtemp directory is permanently
orphaned on disk after every job, regardless of success.

Concurrent submits are race-free on the dict, but `gradio_client.Client`
itself is **not documented as thread-safe**, and the provider creates a
fresh `Client` per `_hf_generate_blocking` call (line 152) — that part is
correct, but means each in-flight job opens its own websocket; the public
HF Space rate-limits aggressively and a burst will partially fail with
hard-to-reproduce 429s. There is no concurrency cap (no semaphore).

**Fix:**
1. Drop entries from `self._jobs` in `download()`/`poll()` once status is
   COMPLETED/FAILED.
2. Track and clean the `tmp_dir` from `submit()` in `download()`.
3. Add a `threading.Semaphore(max_concurrent_jobs)` defaulting to 2 for
   the public Space.

**Severity:** P0 — disk fills (cumulative GB per session), and a long
session degrades into rate-limit failures with no diagnostic.

---

### P0-I6-6 — `terrain_unity_export` writes `manifest.json` non-atomically
**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py:457, 1612, 1629`

```python
target.write_text(json.dumps(payload, indent=2, sort_keys=True))
(output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
```

Three call sites write JSON manifests that Unity ingests, using bare
`Path.write_text`. There is no tmp-then-rename pattern. If the export pass
crashes or the user kills it mid-write, Unity sees a truncated/half-valid
JSON and the import fails or partially registers terrain assets. A failed
import in HDRP leaves *some* meshes registered with the old manifest hash
and others with a missing manifest — this is exactly the "Unity in a bad
state" scenario the audit prompt called out.

The terrain_checkpoints code already implements a full atomic-write helper
(`_atomic_npz_write`); export does not use it.

**Fix:** Wrap every export-time JSON writer in a tmp→rename pattern (use the
same `with_name(...".tmp")` + `replace()` idiom as `_atomic_npz_write`).
Also do this for the `.terrain` binary, height16 PNG, splatmap, mesh OBJ,
and lightmap UV outputs — `git grep "write_text\|.write_bytes" terrain_unity_export.py`
will surface them.

**Severity:** P0 — partial export = broken Unity scene = AAA pipeline
failure.

---

## 2. P1 Findings

### P1-I6-7 — `_DEFAULT_MANIFEST` foliage catalog uses double-checked-locking incorrectly
**File:** `veilbreakers_terrain/handlers/terrain_foliage_catalog.py:1162–1163`

```python
_DEFAULT_MANIFEST: Optional[AssetManifest] = None
_DEFAULT_MANIFEST_LOCK = threading.Lock()
```

The lock exists. Verify (via `grep get_default_manifest`) that *every* read
of `_DEFAULT_MANIFEST` happens under the lock. A read outside the lock
followed by a check-then-build pattern can race; under CPython this happens
to be safe due to the GIL on dict-pointer reads, but is not portable to
free-threaded CPython 3.13t.

**Fix:** Acquire the lock for both read-check and build. Or use
`functools.lru_cache(maxsize=1)` on a no-arg builder.

---

### P1-I6-8 — `_PRESET_LOCKS: Set[str]` is a shared mutable set with no lock
**File:** `veilbreakers_terrain/handlers/terrain_checkpoints_ext.py:35–55`

```python
_PRESET_LOCKS: Set[str] = set()
def lock_preset(name): _PRESET_LOCKS.add(name)
def unlock_preset(name): _PRESET_LOCKS.discard(name)
```

`set.add` / `set.discard` are atomic under GIL but the read in
`is_preset_locked` followed by `assert_preset_unlocked`'s logical check in
callers is a TOCTOU race. Two threads can both see "unlocked" and proceed
to mutate the same preset simultaneously. With Python 3.13 free-threaded
becoming GA in 2026, this is a 12-month time bomb.

**Fix:** Use a `threading.Lock` around the lock/unlock/check trio and
expose a `with locked_preset(name):` context manager so callers cannot
forget the guard.

---

### P1-I6-9 — `_VIEWPORT_VANTAGE` WeakKeyDictionary read-modify-write is not atomic
**File:** `veilbreakers_terrain/handlers/terrain_scene_read.py:199`

```python
_VIEWPORT_VANTAGE: "_weakref.WeakKeyDictionary[...]" = (...)
```

`WeakKeyDictionary` is **not** thread-safe (CPython documents this
explicitly). Concurrent set+iter can raise `RuntimeError: dictionary
changed size during iteration` and concurrent set+set can drop entries.

**Fix:** Wrap with `threading.RLock`.

---

### P1-I6-10 — `random.seed(seed + N)` integer-additive seeding in `terrain_features.py`
**File:** `veilbreakers_terrain/handlers/terrain_features.py:1350, 1664, 3356, 4067, 4518`

```python
crack_rng = random.Random(seed + 9001)       # line 1350
boulder_rng = random.Random(seed + 77777)    # line 1664
_layer_rng = random.Random(seed + 9999)      # line 3356
_vcr = random.Random(seed + 7777)            # line 4067
_vcr2 = random.Random(seed + 4444)           # line 4518
```

Integer-addition is a poor hash for stream separation. Two namespaces with
constants `(N1, N2)` produce identical streams whenever `seed` differs by
exactly `N1 - N2`, leading to subtle aliasing where boulder placement
mirrors crack placement at certain seeds.

The codebase has the right primitive (`derive_pass_seed`); these helpers
should use it with namespace strings.

**Fix:** Replace `seed + 9001` with
`derive_pass_seed(seed, "feature_crack", 0, 0, None)` (or `seed ^
0x...` if the call sites are too hot for a SHA-256 per call, but XOR with
distinct large constants is also better than addition).

---

### P1-I6-11 — `coastline.py: rng = random.Random(seed + 100)`
**File:** `veilbreakers_terrain/handlers/coastline.py:410`

Same pattern as P1-I6-10. Lower priority because there is only one
neighbouring `random.Random(seed)` call in this module, so aliasing is
limited.

---

### P1-I6-12 — `_terrain_depth.py` uses `seed ^ small-int` namespacing
**File:** `veilbreakers_terrain/handlers/_terrain_depth.py:198, 219, 408, 480`

```python
rng_strata = random.Random(seed ^ 0x5A5A)
rng_erosion = random.Random(seed ^ 0xE0E0)
arch_rng = random.Random(seed ^ (depth_i * 31 + 7))
stala_rng = random.Random(seed ^ 0xDEAD)
```

`0x5A5A`, `0xE0E0`, `0xDEAD`, `0x5CA77E2`, `0xD1CE7` (the latter two from
`environment_scatter.py:798, 3224`) are all **16-bit** values being XORed
into a 32-bit/64-bit seed — they only flip the bottom bits. For
seeds whose top bits are zero (typical when the user types
`intent.seed=42`), aliasing across namespaces is statistically detectable.

**Fix:** XOR with FNV-1a or full 32-bit SipHash-style constants
(`0xDEADBEEF`, `0xCAFEBABE`, etc.) — the cliffs/caves modules already do
this. Or, again, use `derive_pass_seed`.

---

### P1-I6-13 — `_GLTF_IMPORT_LOCK` is process-wide but Blender is single-threaded
**File:** `veilbreakers_terrain/handlers/terrain_blender_safety.py:335`

```python
_GLTF_IMPORT_LOCK = threading.Lock()
```

Inside Blender, all `bpy` calls must be on the main thread. A
`threading.Lock` here is correct for *non-Blender* test runs but a hint
that the call site might be invoked off-thread — which would crash Blender
with `Segmentation fault`. Verify the caller is always on the main thread,
and if so, replace with a `bpy.app.timers` queue assertion. If not, the
caller is unsafe regardless of the lock.

---

### P1-I6-14 — `socket_server.py` accepts concurrent connections that hit shared globals
**File:** `veilbreakers_terrain/socket_server.py` (full file)

The MCP socket server accepts multiple clients. Every command handler
currently mutates either `_LP_STATE`, `_HR_STATE`, or
`TerrainPassController.PASS_REGISTRY` (class-level dict modified by
register_pass). Concurrent connections can race during handler dispatch.

**Fix:** Either serialize MCP requests with a single
`threading.Lock` at the dispatcher, or audit each handler for thread
safety. The former is cheaper and sufficient given Blender's single-thread
constraint.

---

### P1-I6-15 — `np.random.seed(42)` global numpy seed in tests
**File:** `veilbreakers_terrain/tests/test_coverage_gaps.py:420`

This sets the **process-global** numpy RNG state. Any test that runs in
the same process afterward and calls `np.random.random()` (without a
generator) gets reproducible behaviour for the wrong reason — bugs that
should have been flushed by random state churn are masked. Pytest runs
tests in a single process by default.

**Fix:** Use `np.random.default_rng(42)` and the modern Generator API.

---

## 3. P2 Findings

### P2-I6-16 — `_BIOME_RULE_MODULES` and `_MATERIAL_RULE_MODULES` tuples in hot-reload
`terrain_hot_reload.py:23, 29`. Tuples are immutable — fine. Listed for
completeness because the hot-reload loop re-imports them; if a re-import
swaps out a module while another thread holds a reference, behaviour is
"works but may run an old copy briefly". Not a P0/P1.

### P2-I6-17 — `_DEFAULT_VEG_RULES`, `_DEFAULT_ATMOSPHERE`, `_DEFAULT_BIOMES`, `_DEFAULT_NOISE_SCALE_FACTORS`, `_DEFAULT_ROLE_MAP`
Module-level *default* tables in `environment_scatter.py:1439`,
`atmospheric_volumes.py:226`, `_biome_grammar.py:120`, `environment.py:169`,
`terrain_assets.py:128`, `vegetation_system.py:267`. Each is a list/dict
literal that is *mutable* — if any caller does `.append`/`.update`, they
mutate the shared default. Spot-checked grep found no mutators currently;
risk is regression in future PRs.

**Fix:** Wrap these in `MappingProxyType(...)` / make tuples-of-tuples to
make accidental mutation a TypeError.

### P2-I6-18 — `_FALLOFF_FUNCS`, `_STAMP_SHAPES`, `_TIER_PRIORITY`, `_VALID_MODIFIER_TYPES`, `_KNOWN_ADDONS`, `_TEXTURE_EXTS`, `_DEFAULT_HEIGHT_BLEND_GAMMAS`, `_REQUIRED_UNITY_SHADER_PROPERTIES`, `_INSTANCE_DTYPE`, `_D8_OFFSETS`, `_D8_DISTANCES`, `_UE5_DEFAULT_SCREEN_SIZES`, `_UE5_DEFAULT_SWITCH_DISTANCES_M`
All module-level lookup tables. Read-only by intent. No callers mutate.
Same defensive recommendation as P2-I6-17.

### P2-I6-19 — `terrain_features.py` 17 separate `random.Random(seed)` calls in hot loops
The module instantiates fresh `random.Random` instances at the top of
several scatter/decoration functions. Performance-only concern (numpy
Generator is faster for bulk draws); not a determinism bug because each is
seeded.

### P2-I6-20 — `procedural_grass.py:303` `np.random.default_rng(rng_seed)` taken from caller
Looks correct; flagged here only because the caller chain (`AAAGrassGenerator`)
needs verification that `rng_seed` actually comes from `intent.seed`. Quick
spot-check OK.

---

## 4. Reproducibility / PYTHONHASHSEED Re-Sweep

Confirmed only the two known offenders:
- `terrain_cliffs.py:2368` — `mesh_seed = hash(cliff.cliff_id) & 0x7FFFFFFF`
- `asset_generation.py:755` — `f"{asset_category}_{abs(hash(full_prompt)) % 10**8:08d}"`

No additional `hash(<str|tuple|bytes>)` cache-key uses found. The other
`hash(` matches in `Grep` output are either:
- numpy/wang-hash helpers operating on numbers (deterministic),
- `intent_hash()` / `compute_hash()` methods that use SHA-256 internally,
- test-helper names containing the word "hash".

**Recommendation:** Add a CI lint that greps `hash\(.*\)` outside an
allow-list of known-safe modules and fails the build. The existing
`terrain_determinism_ci.py` warns about this in its docstring (line 240) but
does not actually scan for it.

---

## 5. RNG / Seed Plumbing Sweep

### Files using `derive_pass_seed` correctly (good — keep)
`terrain_assets.py`, `terrain_caves.py`, `terrain_cliffs.py`,
`terrain_glacial.py`, `terrain_karst.py`, `terrain_materials_v2.py`,
`terrain_multiscale_breakup.py`, `terrain_stochastic_shader.py`,
`terrain_vegetation_depth.py`, `terrain_water_variants.py`,
`terrain_waterfalls.py`, `terrain_wind_erosion.py`, `_terrain_world.py`.

### Files NOT using `derive_pass_seed` despite needing it
- `terrain_stratigraphy.py` lines 420, 569, 794 (P0-I6-2 above).
- `terrain_palette_extract.py:106` (P0-I6-2 above).
- `terrain_features.py` — uses `random.Random(seed + N)` everywhere (P1-I6-10).
- `_terrain_depth.py` — uses `random.Random(seed ^ small)` (P1-I6-12).
- `environment_scatter.py:798` (`seed ^ 0x5CA77E2`) and 3224
  (`seed ^ 0xD1CE7`) (P1-I6-12 family).
- `coastline.py:410` (`random.Random(seed + 100)`) (P1-I6-11).
- `vegetation_system.py:390`, `weathering.py:572`, `world_map.py:518/634/699`,
  `road_network.py:603` — `random.Random(seed)` directly with no namespace.
  Functionally correct for a single pass but means *all* of these passes
  share the same stream when called with the same `seed`; if two of them
  are ever invoked back-to-back with the same `seed`, second pass replays
  identical numbers from start. They should namespace via
  `derive_pass_seed`.

### `make_rng` and `tile_rng` from `terrain_rng.py`
**D8 reported these as "unused"; confirmed.** The only call sites are
`tests/test_chunk_cache_math_helpers.py` (a test of the helper itself).
No production handler imports `make_rng` or `tile_rng`. Two options:
1. Delete `terrain_rng.py` (~50 LOC) — it's dead code.
2. Migrate the P0-I6-2 / P1-I6-10/11/12 sites to use it, since
   `make_rng(*keys)` SHA-256-hashes its keys (correct namespacing).

Option 2 is preferred — `terrain_rng.py` already has the correct semantics;
the codebase just needs to actually adopt it. `derive_pass_seed` and
`make_rng` partially overlap but are not redundant: `derive_pass_seed`
returns an `int`, `make_rng` returns a Generator. Wire `derive_pass_seed`
through `make_rng` for a single primitive.

---

## 6. Thread-safety in `providers/`

`hunyuan3d2_provider.py` (only async provider):
- `_jobs` and `_jobs_lock` correctly paired.
- Per-call `gradio_client.Client` correctly avoids cross-thread client reuse.
- **BUT:** see P0-I6-5 (job/tempdir leak + no concurrency cap).
- `generate_blocking` spawns a worker thread purely to support `timeout`
  via `Thread.join(timeout)`. This is correct but the worker thread
  becomes a zombie on timeout (`worker.is_alive()` is True at raise).
  Daemon=True means it'll be killed at interpreter shutdown but until then
  it continues calling into `gradio_client` and may produce confusing log
  output for a job the caller already considers failed.

`rodin_provider.py` and `runpod_provider.py` (referenced from
`asset_generation.py`): not separately audited here — quick grep showed no
threading. They're synchronous request/poll loops; safe under the
single-threaded MCP serialization recommendation in P1-I6-14.

---

## 7. File-System Race / Atomicity Sweep

### Atomic (safe)
- `terrain_checkpoints.py:_atomic_npz_write` — full tmp→rename + SHA-256 sidecar.
- `terrain_checkpoints.py:save_preset` — atomic JSON.
- `terrain_checkpoints_ext.py:_atomic_npz_save` — same pattern.

### Non-atomic (unsafe)
- `terrain_unity_export.py:457, 1612, 1629` — manifest JSON via `write_text`
  (P0-I6-6 above).
- A `Grep` on `\.write_text|\.write_bytes|json\.dump\(.*open\(` across
  `handlers/` will turn up ~80 more sites; a sample inspection of
  `terrain_telemetry_dashboard.py`, `terrain_iteration_metrics.py`,
  `terrain_navmesh_export.py` shows they all use bare `write_text`. None of
  these block Unity import like the manifest does, but they collectively
  make crash-recovery debugging hard.
- The `Hunyuan3D2Provider.download` `shutil.copy2` is followed by an
  immediate `shutil.rmtree` of the source — fine if dest write succeeds,
  but no `fsync` between them, so a power loss between copy and rmtree
  could leave both copies on disk. Low priority.

**Fix (project-wide):** Add a `atomic_write_text(path, contents)` helper to
`veilbreakers_terrain/utils/io_atomic.py` and lint-enforce its use in
export passes via a CI rule. The helper exists in spirit in
`terrain_checkpoints._atomic_npz_write` — promote it.

---

## 8. Summary Table

| ID         | Severity | Module                                       | Issue                                                     |
|------------|----------|----------------------------------------------|-----------------------------------------------------------|
| P0-I6-1    | P0       | `terrain_checkpoints.py:50–55`               | `id()`-keyed registries collide on GC                     |
| P0-I6-2    | P0       | `terrain_stratigraphy.py:420/569/794`, `terrain_palette_extract.py:106` | Hardcoded `default_rng(0/1/42)` ignores `intent.seed` |
| P0-I6-3    | P0       | `handlers/__init__.py:566/649`               | `_LP_STATE` / `_HR_STATE` unprotected MCP globals         |
| P0-I6-4    | P0       | `terrain_validation.py:1976`                 | Plain `_ACTIVE_CONTROLLER` global next to ContextVar      |
| P0-I6-5    | P0       | `providers/hunyuan3d2_provider.py:265`       | Job table + tempdir leak; no concurrency cap              |
| P0-I6-6    | P0       | `terrain_unity_export.py:457/1612/1629`      | `manifest.json` written non-atomically                    |
| P1-I6-7    | P1       | `terrain_foliage_catalog.py:1162`            | `_DEFAULT_MANIFEST` DCL pattern fragility                 |
| P1-I6-8    | P1       | `terrain_checkpoints_ext.py:35`              | `_PRESET_LOCKS` set TOCTOU                                |
| P1-I6-9    | P1       | `terrain_scene_read.py:199`                  | `WeakKeyDictionary` not thread-safe                       |
| P1-I6-10   | P1       | `terrain_features.py:1350/1664/3356/4067/4518` | `random.Random(seed + N)` aliasing                      |
| P1-I6-11   | P1       | `coastline.py:410`                           | `random.Random(seed + 100)`                               |
| P1-I6-12   | P1       | `_terrain_depth.py:198/219/408/480`, `environment_scatter.py:798/3224` | XOR with 16-bit constants            |
| P1-I6-13   | P1       | `terrain_blender_safety.py:335`              | `_GLTF_IMPORT_LOCK` smell — verify single-thread invariant |
| P1-I6-14   | P1       | `socket_server.py`                           | Concurrent MCP clients hit shared globals                 |
| P1-I6-15   | P1       | `tests/test_coverage_gaps.py:420`            | `np.random.seed(42)` poisons later tests                  |
| P2-I6-16+  | P2       | various                                      | Module-level mutable defaults, unused `terrain_rng.py`    |

**Total: 6 × P0, 9 × P1, 5 × P2.**

---

## 9. Recommended Wave Plan

1. **Wave 1 (block release):** P0-I6-1, P0-I6-2, P0-I6-4, P0-I6-6 — pure
   refactors, ~1 day each, no behaviour change.
2. **Wave 2 (block parallelism):** P0-I6-3, P0-I6-5, P1-I6-14 — adds locks
   and lifetime management to MCP and providers. Required before any
   parallel pipeline rollout.
3. **Wave 3 (determinism polish):** P1-I6-10/11/12, migrate to
   `make_rng`/`derive_pass_seed`. Mostly mechanical.
4. **Wave 4 (defensive):** P2 freezing of default tables, atomic-write
   helper promotion, CI lint for `hash(`.
