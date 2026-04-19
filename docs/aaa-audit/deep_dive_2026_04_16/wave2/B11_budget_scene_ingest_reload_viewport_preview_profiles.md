# B11 — Wave 2 Deep Re-Audit: Budget / Scene-Read / Review Ingest / Hot-Reload / Viewport Sync / Live Preview / Quality Profiles

**Date:** 2026-04-16
**Auditor:** Opus 4.7 (1M ctx) — ULTRATHINK
**Scope (7 files, 32 callable units):**
- `veilbreakers_terrain/handlers/terrain_budget_enforcer.py` (214 lines, 8 funcs + 1 dataclass)
- `veilbreakers_terrain/handlers/terrain_scene_read.py` (178 lines, 4 funcs)
- `veilbreakers_terrain/handlers/terrain_review_ingest.py` (144 lines, 3 funcs + 1 dataclass + 2 dunders)
- `veilbreakers_terrain/handlers/terrain_hot_reload.py` (139 lines, 4 funcs + 1 class with 4 methods)
- `veilbreakers_terrain/handlers/terrain_viewport_sync.py` (201 lines, 6 funcs + 2 classes)
- `veilbreakers_terrain/handlers/terrain_live_preview.py` (189 lines, 1 func + 1 class with 6 methods + 1 free func)
- `veilbreakers_terrain/handlers/terrain_quality_profiles.py` (282 lines, 5 funcs + 2 classes)

**References used (Context7 + WebFetch):**
- `/gorakhargosh/watchdog` — `Observer`, `FileSystemEventHandler`, `AutoRestartTrick`, `debounce_interval_seconds`
- `/websites/blender_api_4_5` — `bpy.types.SpaceView3D.draw_handler_add`, `WindowManager.modal_handler_add`, modal operator template
- `/websites/unity3d_manual` — URP `QualitySettings`, `UniversalRenderPipelineAsset.shadowDistance`, LOD bias, "Convert quality settings from BIRP to URP" page
- General: UE5 Scalability.ini conventions (sg.ViewDistanceQuality / sg.ShadowQuality / sg.FoliageQuality / sg.LandscapeQuality, 5-tier Low/Medium/High/Epic/Cinematic)

**Standard:** AAA shippable comparable to UE5 Scalability + Unity URP Quality Tiers + Houdini live preview + Substance/SD live re-bake. NOT "indie-acceptable". I do not sugar-coat.

---

## Executive Verdict

**Module-level grades (mine vs prior R5):**

| File | Prior | Mine | Disposition |
|---|---|---|---|
| `terrain_budget_enforcer.py` | A | **A−** | DISPUTE (mild) — heuristics are correct but tri-count formula is naive and material/scatter counters miss real production realities |
| `terrain_scene_read.py` | A−/A | **B+** | DISPUTE — `id()`-keyed sidecar is a real correctness bug; default 50 m edit-scope is ungrounded |
| `terrain_review_ingest.py` | A | **A−** | DISPUTE (mild) — silent-skip + no schema versioning + monotonic counter that can never decrement |
| `terrain_hot_reload.py` | A | **D** | **DISPUTE — HARD.** Watches the wrong package path (`blender_addon.*` vs actual `veilbreakers_terrain.*`). Verified: every configured module returns False from `_safe_reload`. Polling-based mtime check is also not how anyone in 2026 builds this — `watchdog.Observer` is the standard. |
| `terrain_viewport_sync.py` | A | **B+** | DISPUTE — square-FOV assumption + degenerate-basis fallback returns True for entire AABB when up ‖ forward (verified with `up=(0,0,1), focal=(0,0,0), camera=(0,0,10)`). Aspect ratio absent. |
| `terrain_live_preview.py` | mixed (A−/F) | **A−/F** | AGREE — `edit_hero_feature` is **F (cosmetic stub)**, rest of the session is a real B+/A−. Cache invalidation by `startswith` over-invalidates. |
| `terrain_quality_profiles.py` | A | **B** | DISPUTE — sandbox blocks the actual repo (no `mcp-toolkit` ancestor in `veilbreakers-terrain/` layout, **verified at runtime**). 7 axes is roughly half what UE5 Scalability covers; no GPU/CPU runtime knobs (no view-distance, shadow distance, LOD bias, foliage density). |

**Critical findings (CRITICAL/HIGH severity):**
1. **terrain_hot_reload.py: 100% non-functional in this codebase** — silently watches dead module names. ZERO modules ever reload. This is a "watches wrong path → D" by your own rubric. (file:`terrain_hot_reload.py:20-29`)
2. **terrain_live_preview.py:138 `edit_hero_feature`** is a fake editor that appends string labels to `state.side_effects` instead of mutating `intent.hero_feature_specs`. Confirmed: `edit_hero_feature(state, "boss_arena", [{"type":"translate","dx":100}])` returns `{"applied":1, "issues":[]}` while the boss arena is unchanged. **F**.
3. **terrain_quality_profiles.py:217-234 `write_profile_jsons`** sandbox check looks for an `mcp-toolkit` ancestor that does not exist in this repo (verified — repo writes are blocked, only tempdir works). The "Tools/mcp-toolkit/presets/terrain/quality_profiles/" path mentioned in the docstring is unreachable.
4. **terrain_scene_read.py:80 `_EXTENDED_METADATA[id(sr)]`** keys a global dict by Python `id()` — recycled when the `TerrainSceneRead` is GC'd. Long-running Blender session = silent metadata corruption.
5. **terrain_viewport_sync.py:166-176 `is_in_frustum`** returns True for ANY point in `visible_bounds` when `camera_up ‖ camera_direction`. A top-down view with `up=(0,0,1)` collapses the frustum to the AABB. Square FOV (no aspect) is also wrong for any real 16:9 viewport.

---

## Detailed Per-Function Audit

### File 1 — `terrain_budget_enforcer.py`

#### `TerrainBudget` (dataclass) — line 26
- **Prior:** A. **Mine:** **A−**. **DISPUTE (mild).**
- **What it does:** Holds 5 ship-budget knobs (hero/km², tri count, unique materials, scatter instances, NPZ MB) + a single `warn_fraction=0.80`.
- **Reference:** UE5 `r.LandscapeQuality` / `sg.FoliageQuality` use **per-platform** tiered budgets, not flat thresholds. Unity HDRP terrain budgets are split per-tile per-LOD. Cyberpunk 2077 streaming budgets are sector-tagged.
- **AAA gap:** No platform tier (PS5/XSX vs Steam Deck), no per-LOD breakdown (LOD0 may have 1.5M tris, LOD2 should have ~50k), no streaming-pool overlap budget. A single `max_tri_count=1_500_000` is arbitrary and not differentiated by tile size. A 1×1 km tile and a 4×4 km tile share the same triangle ceiling.
- **Severity:** important.
- **Upgrade:** Add `platform: str = "pc_high"`, `lod_budgets: Dict[int, int]`, derive tri ceiling from `tile_km2 * tris_per_km2`. Wire `warn_fraction` per axis (different sensitivities).

#### `_km2_from_stack(stack)` — line 38
- **Prior:** A. **Mine:** A. **AGREE.**
- **What it does:** `(tile_size * cell_size)² / 1e6` with min 1e-9 floor.
- **Reference:** Standard. Min-floor avoids div-by-zero downstream.
- **Bug/gap:** None.
- **Severity:** none.

#### `_count_unique_materials(stack)` — line 44
- **Prior:** A. **Mine:** **A−**. **DISPUTE (mild).**
- **What it does:** Counts splatmap layers where any cell weight > 0.01.
- **Reference:** Unreal/Unity terrain splat budgets. Threshold of 0.01 (1%) is a reasonable "is this layer visually present" gate.
- **Bug/gap:** A single "above threshold anywhere" check counts a layer that occupies 0.001% of the tile as a full layer. Real shipping budgets care about **shader sample cost**, which is ~constant per layer regardless of coverage — so the heuristic is actually fine for that purpose. But for VRAM/streaming, layer coverage matters. Also: threshold is hardcoded — should pull from `TerrainBudget`.
- **Severity:** minor.
- **Upgrade:** Make threshold configurable; expose both "active layers" and "VRAM-weighted layer cost".

#### `_count_scatter_instances(stack)` — line 56
- **Prior:** A. **Mine:** **B+**. **DISPUTE.**
- **What it does:** Sums `tree_instance_points.shape[0]` + `sum(detail_density.values())` of per-cell density.
- **Reference:** Unreal foliage HISM/Nanite Foliage instance counts; Unity URP terrain detail density is "instances per m²".
- **Bug/gap:** **Confuses density with count.** `detail_density` is per-cell instances; the code does `np.sum(finite)` which gives total expected instances ONLY if density values are already integer counts per cell. If density is a continuous Poisson rate (instances per m²), the result is unitless garbage. The comment at line 66 says "Per-cell density is instances per cell" — but other handlers in the codebase pass continuous rates here. Without a unit contract this is fragile. Also no NaN guard before `int(...)` cast — although `finite = arr[np.isfinite(arr)]` filters, negative densities pass through (`max(0.0, ...)` clamps the sum but not before summing — so a single -1e9 can make the sum negative then get clamped to 0).
- **Severity:** important.
- **Upgrade:** Document the density contract in `TerrainMaskStack.detail_density` docstring; clamp negatives at element level (`np.clip(finite, 0, None)`); multiply by `cell_area_m²` if density is per-m².

#### `_estimate_tri_count(stack)` — line 73
- **Prior:** A. **Mine:** **B**. **DISPUTE.**
- **What it does:** `2 * (rows-1) * (cols-1)` — uniform-grid heightmap mesh.
- **Reference:** Standard but assumes **no LOD, no Nanite, no clipmap, no GPU-driven tessellation**. UE5's "Virtual Heightfield Mesh" or Nanite landscape produces wildly different counts. Modern AAA terrain uses adaptive tessellation that may render 3M tris in foreground and 50k in background of the same heightmap.
- **Bug/gap:** Single-LOD assumption. A 1024×1024 heightmap = ~2.1M tris uniform — already over the 1.5M default budget without the terrain ever shipping at uniform res. So either the budget is calibrated for sub-1024² heightmaps OR the formula doesn't reflect reality.
- **Severity:** important.
- **Upgrade:** Multiply by an `lod_factor: float = 0.25` derived from active LOD pyramid; OR compute tri count from the actual mesh export rather than the heightmap.

#### `_estimate_npz_mb(stack)` — line 87
- **Prior:** A. **Mine:** A−. **AGREE (with caveat).**
- **What it does:** Sum `nbytes` of all stack array channels / 1024².
- **Reference:** Standard `nbytes` accounting.
- **Bug/gap:** Ignores **NPZ compression** (typically 2–4× shrink for heightfields). The check is therefore a ceiling, not actual on-disk size. Documented in handler header as "Approximate (no compression accounting) but useful" in prior audit, fair.
- **Severity:** minor.
- **Upgrade:** Add `_estimate_npz_compressed_mb` that does an `np.savez_compressed` to `BytesIO` and measures.

#### `compute_tile_budget_usage(stack, budget, intent)` — line 98
- **Prior:** A. **Mine:** A. **AGREE.**
- **What it does:** Returns nested dict with current/max/utilization for each axis.
- **Reference:** Standard usage-report dict. Returns floats — easy to JSON-serialize.
- **Bug/gap:** `hero_count` from `len(intent.hero_feature_specs)` ignores hero **density distribution** — 4 hero features in one corner is worse than 4 spread across. No spatial concentration metric.
- **Severity:** minor.
- **Upgrade:** Add a `hero_density_max_per_subtile` metric using a 4×4 grid kernel.

#### `_issue_for(...)` — line 148
- **Prior:** A. **Mine:** A. **AGREE.**
- **What it does:** Returns hard `ValidationIssue` if current > max, soft if > warn_fraction × max, else None.
- **Reference:** Standard hard/soft pattern.
- **Bug/gap:** No `current` value attached to the `ValidationIssue` payload — only formatted into message string. Downstream auto-remediation can't read the numbers without re-parsing the string.
- **Severity:** minor.
- **Upgrade:** Add `metadata={"current": current, "max": max_, "axis": axis}` to `ValidationIssue` (assuming the dataclass supports it; if not, that's a `terrain_semantics.py` change).

#### `enforce_budget(stack, intent, budget)` — line 178
- **Prior:** A. **Mine:** A. **AGREE.**
- **What it does:** Iterates 5 axes, returns list of issues.
- **Reference:** Standard.
- **Bug/gap:** No issue is emitted for **streaming pool overlap** or **LOD0 vertex memory** — both of which UE5 ships with as ship-blocking.
- **Severity:** minor (scope decision).

---

### File 2 — `terrain_scene_read.py`

#### `capture_scene_read(...)` — line 23
- **Prior:** A−. **Mine:** **B+**. **DISPUTE.**
- **What it does:** Builds a frozen `TerrainSceneRead` snapshot per Plan §5.3, defaulting `edit_scope` to a 50×50 m box around `focal_point`. Stashes Addendum 1.A.7 metadata in module-level `_EXTENDED_METADATA[id(sr)]`.
- **Reference:** Unreal's `EditorScriptingUtilities.GetEditorWorld()` + `WorldOutliner.GetSelectedActors()` provide a real scene snapshot. This handler operates headlessly which is fine — but the sidecar pattern is fragile.
- **Bug/gap (CRITICAL — file:line: `terrain_scene_read.py:80`):** `_EXTENDED_METADATA[id(sr)] = {...}`. CPython recycles `id()` after GC. In a long Blender session creating thousands of `TerrainSceneRead` snapshots, two distinct snapshots can share an id and silently overwrite each other's extended metadata. Prior audit flagged this; I escalate it because it is a **silent data corruption bug** in production — not "minor".
- **AAA gap:** Real DCC tools (Maya `MGlobal.executeCommand`, Unreal `UEditorAssetLibrary.find_asset_data`) attach editor metadata directly to the entity, not by `id()`. Either:
  - (a) thaw the dataclass and add the four extended fields, OR
  - (b) use `weakref.WeakKeyDictionary` (frozen dataclass is hashable, supports weakrefs by default in CPython if you don't override `__hash__`), OR
  - (c) wrap with a `@dataclass(frozen=False)` mutable extension class.
- **Severity:** **important** (data loss potential).
- **Upgrade:** Switch to `weakref.WeakKeyDictionary()`; verify `TerrainSceneRead` supports weakrefs (frozen dataclasses do by default).

Also: the default `edit_scope = focal ± 25.0` (line 59-64) is a **magic 50 m box**. AAA terrain edits range from 5 m (path tweak) to 2 km (river restructure). Ungrounded default — should require explicit scope or derive from `intent.region_bounds`.

#### `get_extended_metadata(sr)` — line 94
- **Prior:** A−. **Mine:** B+. **DISPUTE.**
- Same `id()` recycling caveat. Returns `None` silently when metadata missing (could be GC race) — caller has no way to distinguish "never set" from "lost to GC".
- **Severity:** important.
- **Upgrade:** Same fix as above.

#### `_coerce_bbox(raw)` — line 99
- **Prior:** A. **Mine:** A. **AGREE.**
- Accepts `BBox | dict | 4-tuple/list`. Defensive, correct.
- **Bug/gap:** No validation that `min < max` after coercion. A reversed BBox passes through and corrupts downstream frustum tests.
- **Severity:** minor.
- **Upgrade:** `if bb.min_x > bb.max_x or bb.min_y > bb.max_y: raise ValueError(...)`.

#### `handle_capture_scene_read(params)` — line 117
- **Prior:** A. **Mine:** A. **AGREE.**
- MCP-style handler with full Addendum 1.A.7 surface. Returns dict for JSON-RPC bridge.
- **Bug/gap:** `params.get("addon_version")` if the caller passes a string (e.g. `"1.2.3"`) will TypeError on `tuple(...)`. Should split on `.` or accept a string.
- **Severity:** minor.
- **Upgrade:** `_coerce_version` helper.

---

### File 3 — `terrain_review_ingest.py`

#### `ReviewFinding` (dataclass + `__post_init__` + `to_dict`) — line 26
- **Prior:** A. **Mine:** A. **AGREE.**
- Validates `source ∈ ALLOWED_SOURCES` and `severity ∈ ALLOWED_SEVERITIES`. Solid.
- **Bug/gap:** No URI/path field for code-attached findings (a review pointing at `terrain_pipeline.py:442` can't carry that pointer through). No timestamp.
- **Severity:** minor.
- **Upgrade:** Add `source_location: Optional[str]`, `created_at: Optional[float]`.

#### `_coerce_location(raw)` — line 55
- **Prior:** A. **Mine:** A. **AGREE.**
- Trivial 3-tuple coercion.

#### `ingest_review_json(path)` — line 63
- **Prior:** A. **Mine:** **A−**. **DISPUTE (mild).**
- **What it does:** Parses `{"findings": [...]}` or top-level list of dicts; validates each entry through `ReviewFinding`, **silently** skipping malformed items.
- **Reference:** Standard tolerant-parser pattern.
- **Bug/gap:** **Verified:** with mixed input `[{good}, {bad-source}, {bad-severity}, "not-a-dict"]`, only 1 of 4 ingests, **without warning or count of skipped items**. A reviewer's typo silently drops a hard finding — and the pipeline thinks everything is fine.
- **AAA gap:** Substance Painter / Unreal's review tools always log skipped entries. Houdini's `geometry.attribValue()` raises on bad type rather than silently dropping.
- **Severity:** important.
- **Upgrade:** Return `(findings, skipped_count, skipped_reasons)` tuple OR log via `logging.getLogger(__name__).warning(...)` per skip. Add JSON schema version field.

#### `apply_review_findings(intent, findings)` — line 102
- **Prior:** A. **Mine:** A. **AGREE.**
- Folds findings into `composition_hints['review_blockers' | 'review_suggestions' | 'review_info']` via `dataclasses.replace`. Returns new frozen intent. Correct immutable pattern.
- **Bug/gap:** `review_total_ingested` counter is **monotonically additive** — there's no way to clear stale findings. After 100 review cycles the blocker list grows to thousands without dedup. Also no idempotency: ingesting the same review JSON twice doubles the entries.
- **Severity:** important.
- **Upgrade:** Add `replace_existing: bool = False` flag; dedupe by `(source, severity, message_hash)`.

---

### File 4 — `terrain_hot_reload.py`

**THIS WHOLE MODULE IS A D.** The module file's published purpose ("hot-reload watcher for terrain rule modules so tuning iteration doesn't require Blender restart") is **not achieved** in this repo because every configured module path points at a package (`blender_addon.handlers.*`) that does not exist. **Runtime-verified:** every entry in `_BIOME_RULE_MODULES` and `_MATERIAL_RULE_MODULES` returns `False` from `_safe_reload`. The watcher silently watches nothing.

#### `_module_path(mod)` — line 32
- **Prior:** A. **Mine:** A. **AGREE.**
- Trivial getter.

#### `_safe_reload(name)` — line 37
- **Prior:** A. **Mine:** **B+**. **DISPUTE (mild).**
- **What it does:** Bare-except wrapper around `importlib.import_module` / `importlib.reload`.
- **Reference:** `importlib.reload` is the right primitive but **does not** reload child modules (e.g. reloading `terrain_materials_v2` will not re-execute `from .terrain_semantics import ...`). For a true hot-reload you need `importlib.invalidate_caches()` + recursive child reload (see `IPython.lib.deepreload` pattern).
- **Bug/gap:** Bare `except Exception` swallows the reason — a real syntax error in a dev-edited rule file disappears. Hot-reload's whole value is the dev sees errors fast.
- **Severity:** important.
- **Upgrade:** `except Exception as e: logger.warning("reload of %s failed: %s", name, e); return False`.

#### `reload_biome_rules()` / `reload_material_rules()` — lines 52, 61
- **Prior:** A. **Mine:** **D**. **DISPUTE — HARD.**
- **What it does:** Iterates `_BIOME_RULE_MODULES = ("blender_addon.handlers.terrain_ecotone_graph", ...)` and tries to reload each.
- **Reference:** N/A — these strings are **wrong**. Actual package is `veilbreakers_terrain.handlers.*`. Verified at runtime: each call returns False.
- **Bug/gap (CRITICAL — file:line: `terrain_hot_reload.py:20-29`):** Hardcoded module names refer to a non-existent `blender_addon` package. **The function returns an empty list every time.** Any caller that asserts "non-empty list = reload happened" silently passes with zero reloads.
- **AAA gap:** Anyone shipping `watchdog`-class hot-reload would derive the package root from `__package__` or `Path(__file__).parent.name`. Unreal's `HotReload` derives from the `.uproject`. Unity's `AssetDatabase.Refresh` walks the project root.
- **Severity:** **CRITICAL**.
- **Upgrade:**
  ```python
  _PKG = __package__ or "veilbreakers_terrain.handlers"
  _BIOME_RULE_MODULES = tuple(f"{_PKG}.{m}" for m in (
      "terrain_ecotone_graph", "terrain_materials_v2", "terrain_banded",
  ))
  ```

#### `HotReloadWatcher` class — line 70
- **Prior:** A. **Mine:** **D**. **DISPUTE — HARD.**
- **What it does:** Polls `mtime` of watched modules' source files; reloads when changed.
- **Reference:** `watchdog.Observer` + `FileSystemEventHandler.on_modified` is the standard. Polling is **8 years out of date** — kqueue (macOS), inotify (Linux), ReadDirectoryChangesW (Windows) provide push-based notification with sub-ms latency. Watchdog wraps all three. Polling-mtime in 2026 is below indie quality.
- **Bug/gap:**
  1. Same wrong-package-path problem as above — `watch_biome_rules` / `watch_material_rules` populate `watched_modules` with dead names.
  2. **No debounce** — saving a file can fire 2–3 mtime updates in rapid succession (editor write, fsync, OS metadata flush). Without debounce, `check_and_reload` reloads twice, second call may catch a half-written file.
  3. `check_and_reload` is **only called when something polls it** — there's no polling thread, no `asyncio.create_task`, no `watchdog.Observer`. **The watcher only reloads when manually invoked.** That's not a watcher; it's a reload-on-demand function.
  4. No granularity — if `terrain_materials_v2` is modified, ALL watched modules are checked; a change in one cascades nothing dependent.
- **AAA gap:** Substance Designer's live link, Houdini's `hou.session` reload, Unity's `[InitializeOnLoad]` + `AssetPostprocessor`, Unreal's `IHotReloadInterface` all use OS-level filesystem notifications + dependency graphs.
- **Severity:** **CRITICAL** (combination of "watches wrong path" + "no actual watcher loop" + "no debounce").
- **Upgrade:** Replace entire class with:
  ```python
  from watchdog.observers import Observer
  from watchdog.events import PatternMatchingEventHandler
  class _Reloader(PatternMatchingEventHandler):
      def __init__(self, mods):
          super().__init__(patterns=["*.py"], ignore_directories=True)
          self.mods = mods
          self._last_event = 0
      def on_modified(self, event):
          now = time.time()
          if now - self._last_event < 0.25:  # 250ms debounce
              return
          self._last_event = now
          for name in self.mods:
              _safe_reload(name)
  obs = Observer()
  obs.schedule(_Reloader(modules), str(Path(handlers_dir)), recursive=False)
  obs.start()
  ```

#### `force_reload_all()` — line 127
- **Prior:** A. **Mine:** A. **AGREE.**
- Best-effort iteration — fine.

---

### File 5 — `terrain_viewport_sync.py`

#### `ViewportStale` exception — line 21
- A. Trivial. AGREE.

#### `ViewportVantage` (frozen dataclass) — line 25
- **Prior:** A. **Mine:** **A−**. **DISPUTE (mild).**
- **What it does:** Holds camera pos/dir/up + focal + fov + visible_bounds + timestamp + matrix hash.
- **Reference:** Blender exposes `bpy.types.RegionView3D` with `view_matrix`, `perspective_matrix`, `view_camera_offset`, `view_distance`, `is_perspective`. Per Context7 `bpy.types.SpaceView3D` lookup, real DCC vantage carries these directly.
- **Bug/gap:** **Missing `aspect_ratio`** — every real viewport has one. Missing `is_perspective` flag (orthographic mode breaks `is_in_frustum`). Missing `near_clip` / `far_clip` — frustum culling without near/far is incomplete.
- **Severity:** important.
- **Upgrade:** Add `aspect_ratio: float = 16/9`, `is_perspective: bool = True`, `near_clip: float = 0.1`, `far_clip: float = 10000.0`.

#### `_unit(v)` — line 39
- **Prior:** A. **Mine:** A. **AGREE.**
- Standard normalize with epsilon guard returning `(0,0,1)` on zero vector. The default of `(0,0,1)` is opinionated — should probably raise. Minor.

#### `_matrix_hash(...)` — line 47
- **Prior:** A. **Mine:** A. **AGREE.**
- SHA-256 truncated to 16 hex chars. Solid.
- **Nit:** Format string `f"{pos}|{direction}|{up}|{fov:.6f}"` uses Python's `repr` of tuples — locale-independent but not guaranteed across CPython versions to remain identical. For a hash-equality check, `struct.pack` is more deterministic.
- **Severity:** trivial.

#### `read_user_vantage(...)` — line 57
- **Prior:** A. **Mine:** **B+**. **DISPUTE.**
- **What it does:** Builds a synthetic vantage with hardcoded defaults; production version is supposed to read `bpy.context.region_data`.
- **Reference:** `bpy.types.RegionView3D.view_matrix` (4×4) is the authoritative source. The current code does NOT have a Blender path — it's defaults-only.
- **Bug/gap:**
  1. Default `r = 40.0` for visible_bounds is arbitrary. Should derive from FOV + camera distance: `r = focal_distance * tan(fov/2)`.
  2. No actual Blender integration. The docstring says "real Blender reads region_data" — but there's **no code path that does so**. This is forever-headless.
  3. `up=(0,0,1)` default is Z-up — fine for game terrain, but Blender's default is also Z-up so that's consistent. OK.
- **Severity:** important (forever-headless = no real viewport sync ever happens).
- **Upgrade:** Add a `bpy_available` branch:
  ```python
  try:
      import bpy
      rv = bpy.context.region_data
      view_inv = rv.view_matrix.inverted()
      camera_position = view_inv.translation
      camera_direction = -view_inv.col[2].xyz  # -Z is forward in Blender
      camera_up = view_inv.col[1].xyz
      ...
  except (ImportError, AttributeError):
      # headless fallback
  ```

#### `assert_vantage_fresh(vantage, max_age_seconds, *, now)` — line 97
- **Prior:** A. **Mine:** A. **AGREE.**
- Standard age check. The injectable `now` is good for testability.
- **Bug/gap:** 300 s default freshness is huge — at 300 s the user has rotated the view 50 times. UE5's editor tools assume sub-second freshness for selection/snap operations.
- **Severity:** minor.
- **Upgrade:** Lower default to 30 s; allow per-operation override.

#### `transform_world_to_vantage(world_position, vantage)` — line 112
- **Prior:** A. **Mine:** A. **AGREE.**
- Right-handed orthonormal basis projection: `right = up × forward`. Correct.
- **Bug/gap:** Same degenerate-basis issue — when `up ‖ forward`, `right = (0,0,0)` and `rn = 1.0` (the `or 1.0` fallback), so the projected `right` coordinate is always 0. Caller gets `(0, dot(up, delta), dot(forward, delta))` — incorrect view-space coords. No exception raised.
- **Severity:** minor (caller can usually detect via the all-zero right component).
- **Upgrade:** Raise `ValueError("camera_up parallel to camera_direction")` or use a robust basis (e.g., pick world-up unless that's parallel, then world-forward).

#### `is_in_frustum(world_position, vantage)` — line 138
- **Prior:** A. **Mine:** **B+**. **DISPUTE.**
- **What it does:** Real frustum cull — forward-axis sign + symmetric horizontal/vertical FOV cone.
- **Reference:** Standard. UE5/Unity frustum culling decomposes into 6 planes (near/far/left/right/top/bottom). This implementation does 3 (forward, horizontal, vertical) — adequate for "is this point visible from this vantage".
- **Bug/gap (verified at runtime):**
  1. **Square-FOV** assumption — same `tan_h` for horizontal and vertical (line 187, 189). Real cameras have aspect ratio. Prior audit flagged.
  2. **Degenerate-basis silent fallback** (line 173-176): when `camera_up ‖ camera_direction` (e.g. top-down view with `up=(0,0,1), focal=(0,0,0), camera=(0,0,10)`), the function falls back to "in front of camera + inside AABB = True" — it returns True for **any** point in `visible_bounds`. **Verified:** with default 1000×1000 bounds and top-down vantage, point `(999, 999, 0)` returns True even though the camera FOV could only see ~12 m.
  3. **No near/far clipping** — a point 10 km away that happens to be in front of the camera and inside FOV cone returns True even though it's outside any reasonable far-clip.
- **AAA gap:** UE5's `FConvexVolume` does 6 planes + near/far. Unity's `GeometryUtility.TestPlanesAABB` does the same. Both honor aspect ratio.
- **Severity:** important.
- **Upgrade:**
  ```python
  def is_in_frustum(p, v, *, aspect=16/9, near=None, far=None):
      ...
      if forward < (near or 0.001): return False
      if far is not None and forward > far: return False
      tan_v = math.tan(v.fov / 2)
      tan_h = tan_v * aspect
      if abs(right) > forward * tan_h: return False
      if abs(up) > forward * tan_v: return False
      ...
  ```
  And **raise** on degenerate basis instead of silently passing.

---

### File 6 — `terrain_live_preview.py`

#### `_clone_stack_for_diff(stack)` — line 24
- **Prior:** A−. **Mine:** A. **AGREE.**
- Shallow copy + per-channel `.copy()` for arrays + dict-copy for `populated_by_pass` + set-copy for `dirty_channels`. Correct deep-enough clone for diffing.
- **Nit:** Doesn't copy non-array attributes that may be mutable (e.g., `detail_density` dict if present). Could leak state if caller mutates.
- **Severity:** minor.

#### `LivePreviewSession` (dataclass) — line 38
- **Prior:** A−. **Mine:** **B+**. **DISPUTE (mild).**
- **What it does:** Holds controller + LRU cache (256 entries) + dirty tracker + history list.
- **Reference:** Substance Painter's live preview holds a snapshot stack + dirty flags + history depth ~50.
- **Bug/gap:** `history: List[Dict[str, Any]] = field(default_factory=list)` — **unbounded growth.** A 30-min iteration session with 1 edit/sec = 1800 history entries × stack snapshots = unbounded RAM. Prior audit flagged.
- **Severity:** important.
- **Upgrade:** `history: collections.deque = field(default_factory=lambda: collections.deque(maxlen=100))`.

#### `__post_init__` — line 58
- A. Attaches dirty tracker if not provided. Fine.

#### `state` property — line 63 / `current_hash` — line 66
- A. Trivial passthroughs.

#### `apply_edit(edit)` — line 69
- **Prior:** A−. **Mine:** **B+**. **DISPUTE (mild).**
- **What it does:** Marks dirty channels, invalidates cache by prefix, runs passes through cache or region executor, records hash.
- **Reference:** Standard live-preview apply pattern.
- **Bug/gap:**
  1. **Cache over-invalidation** (line 87): `self.cache.invalidate_prefix(ch)` calls `invalidate_prefix("height")` which matches keys like `"height_normal_map"`, `"height_blur"` — over-invalidates. Verified `invalidate_prefix` impl at `terrain_mask_cache.py:120-125` uses raw `str.startswith`. Prior audit caught this.
  2. **No region argument** to cache invalidation — invalidates the channel globally even when the dirty region is a 10×10 m subregion. Real AAA caches are spatially indexed.
  3. **Silent ignore** of `region=None` + `dirty_channels` non-empty (line 83) — dirty channels are NOT marked when region is None. So a "dirty everything" edit is a no-op for the tracker.
  4. `pass_with_cache` runs without checking whether the pass's `requires_channels` are present — relies on the inner function to enforce.
- **Severity:** important.
- **Upgrade:** Add region-aware cache index; either require region for dirty marking or fall back to `intent.region_bounds`; add channel→cache-key precise reverse index.

#### `diff_preview(hash_before, hash_after)` — line 109
- **Prior:** A−. **Mine:** **B**. **DISPUTE.**
- **What it does:** Returns a summary dict of whether the two hashes are present in history.
- **Reference:** N/A — this is **not a diff**; it's a hash-membership check. Actual visual diff lives in `compute_visual_diff` in `terrain_visual_diff` (called by `diff_stacks`).
- **Bug/gap:** The function name promises a diff. It returns `{identical, found_before, found_after, history_length}` — that's a hash-equality + history-presence check. Misleading API.
- **Severity:** minor.
- **Upgrade:** Rename to `lookup_preview_hashes` OR retain stack snapshots (memory permitting) and return a real diff.

#### `diff_stacks(stack_before)` — line 129
- A. Convenience wrapper for `compute_visual_diff`. Fine.

#### `snapshot_stack()` — line 133
- A. Returns `_clone_stack_for_diff(...)`. Fine.

#### `edit_hero_feature(state, feature_id, mutations)` — line 138 (free function, NOT a method)
- **Prior:** F. **Mine:** **F**. **AGREE — confirmed runtime-fake.**
- **What it does:** Iterates `mutations`, appends labels like `"edit:boss_arena:translate:100,50,0"` to `state.side_effects`. **NEVER mutates anything else.**
- **Reference:** Real hero-feature editing in UE5 = `AActor.SetActorLocation(...)`. In Blender = `obj.location = ...`. In Houdini = `geometry.setPointAttrib(...)`. None of those return a "label string" — they actually update the scene.
- **Bug/gap (CRITICAL — file:line: `terrain_live_preview.py:138-183`):**
  - **Verified runtime:** `edit_hero_feature(state, "boss_arena", [{"type":"translate","dx":100}])` returns `{"applied":1, "issues":[], "feature_id":"boss_arena"}`. The boss_arena's actual position in `intent.hero_feature_specs` is **unchanged**.
  - The "feature found" check (line 155) does `feature_id in s` for each `s in state.side_effects` — string substring search. So `"boss"` matches a side-effect string `"boss_arena_at_(100,100)"`. False positives are rampant.
  - No dirty channel marking for the affected region.
  - No validation pass scheduled.
  - The function is **named** "edit_hero_feature" and **documented** as "Orchestrate modular editing of a single hero feature in-place" — both are lies. This is a stub.
- **AAA gap:** Total. UE5's "Modify Object" pipeline updates the actor, marks the level dirty, broadcasts `OnObjectModified`, schedules a navmesh rebuild. This function does ~0.1% of that.
- **Severity:** **blocker** — any test that calls this passes false-positive.
- **Upgrade:** Look up the `HeroFeatureSpec` by ID in `intent.hero_feature_specs` (which is a tuple of frozen dataclasses), construct a new instance with mutated fields via `dataclasses.replace`, swap into a new `intent.hero_feature_specs` tuple, mark `hero_exclusion` + downstream channels dirty over the feature's bounds, return validation issues.

---

### File 7 — `terrain_quality_profiles.py`

#### `PresetLocked` exception — line 27
- A. Trivial. AGREE. Note: defined but **never raised** anywhere in this module — `lock_preset` just sets a flag, doesn't enforce.

#### `TerrainQualityProfile` (dataclass) — line 39
- **Prior:** A. **Mine:** **B**. **DISPUTE.**
- **What it does:** 11 fields covering erosion params, checkpoint retention, bit depths, lock flag.
- **Reference (Context7 + UE5 conventions):**
  - Unity URP `UniversalRenderPipelineAsset` has ~40 quality knobs: `renderScale`, `shadowDistance`, `cascadeBorder`, `mainLightShadowmapResolution`, `additionalLightsShadowmapResolution`, `softShadowsEnabled`, MSAA samples, HDR enabled, opaque texture, etc.
  - UE5 Scalability has 11 groups (`sg.ViewDistanceQuality`, `sg.AntiAliasingQuality`, `sg.ShadowQuality`, `sg.GlobalIlluminationQuality`, `sg.ReflectionQuality`, `sg.PostProcessQuality`, `sg.TextureQuality`, `sg.EffectsQuality`, `sg.FoliageQuality`, `sg.ShadingQuality`, `sg.LandscapeQuality`) each with 5 tiers.
- **AAA gap:**
  - 7 axes vs Unity URP's ~40 vs UE5's 11×5=55 settings. **Roughly 1/8th coverage.**
  - **No view-distance / draw-distance**. Critical for terrain.
  - **No shadow distance / cascade count**. Critical for terrain.
  - **No LOD bias**. Critical for terrain.
  - **No foliage density multiplier**. Critical for terrain.
  - **No streaming pool size**. Critical for open world.
  - **No clipmap level count**. Critical for shadow clipmap.
  - **No anisotropic filtering level**.
  - **No tessellation factor**.
  - The 7 axes that ARE covered are all **CPU-side authoring quality**, not **GPU/runtime** quality. Auto-shipping at "aaa_open_world" tier with `erosion_iterations=48` does nothing for runtime FPS.
- **Severity:** important.
- **Upgrade:** Add at minimum: `view_distance_m: float`, `shadow_distance_m: float`, `lod_bias: float`, `foliage_density_mult: float`, `streaming_pool_mb: int`, `clipmap_levels: int`. Split profile into `AuthoringQuality` and `RuntimeQuality`.

#### Built-in profiles `PREVIEW_PROFILE` / `PRODUCTION_PROFILE` / `HERO_SHOT_PROFILE` / `AAA_OPEN_WORLD_PROFILE` — lines 72, 84, 96, 108
- **Prior:** A. **Mine:** A. **AGREE — for what they cover.**
- Numbers ramp correctly per Addendum 1.B.4: `erosion_iterations` 2→8→24→48; `checkpoint_retention` 5→20→40→80; bit depths jump at hero_shot. EXACT erosion seam strategy at hero/aaa_open_world. Reasonable.
- **Bug/gap:** PREVIEW with `erosion_iterations=2` is too low for any meaningful preview — Gaea's preview tier is 50–200 iterations. Production at 8 is laughable vs Gaea's 1k–10k. Hero-shot at 24 is still 100× lower than what Gaea ships. AAA at 48 is **two orders of magnitude below** Houdini's HeightField-Erode default (which is in the thousands). The numbers look monotonic but are uniformly **too low** vs real AAA tooling.
- **AAA gap:** Quantitative — iteration counts are 1–2 orders of magnitude below industry. May still be correct for THIS pipeline's per-iteration cost (different algorithms iterate differently) — but no calibration reference is provided.
- **Severity:** important (calibration unknown).
- **Upgrade:** Add a comment justifying iteration count vs algorithm class; benchmark against Gaea/Houdini parity for known reference terrains.

#### `_merge_with_parent(child, parent)` — line 134
- **Prior:** A. **Mine:** A. **AGREE.**
- "Child can strengthen, never weaken" via `max()` of numeric fields; child wins on strategy + naming. Clean inheritance contract.
- **Nit:** `lock_preset = child or parent` means a parent lock propagates forever — fine, but undocumented.

#### `load_quality_profile(name)` — line 178
- **Prior:** A. **Mine:** A. **AGREE.**
- Recursive parent merge. KeyError on unknown. Clean.
- **Bug/gap:** No cycle detection. If someone manually constructs a profile with `extends="self"` (or a 2-cycle), this stack-overflows.
- **Severity:** trivial (built-ins are acyclic).

#### `list_quality_profiles()` — line 189
- A. Hardcoded canonical 4. Should derive from `_BUILTIN_PROFILES.keys()` if order matters add explicit ordering. Cosmetic.

#### `write_profile_jsons(root)` — line 199
- **Prior:** A. **Mine:** **C+**. **DISPUTE — HARD.**
- **What it does:** Writes each built-in as `{name}.json` under `root` after sandbox check.
- **Reference:** Standard JSON dump.
- **Bug/gap (CRITICAL — verified at runtime, file:line: `terrain_quality_profiles.py:217-234`):**
  - The sandbox walks ancestors looking for an `mcp-toolkit` directory. **In this repo there is no `mcp-toolkit` ancestor** — the layout is `C:/Users/Conner/.../veilbreakers-terrain/veilbreakers_terrain/handlers/`. Verified: `repo_root` ends as `None`, `allowed_roots` is `[tempdir]` only.
  - The docstring claims writes go to `Tools/mcp-toolkit/presets/terrain/quality_profiles/`. **That path is rejected at runtime** with `ValueError("write_profile_jsons: refusing to write outside sandbox")`.
  - Tests presumably write to a tempdir so this passes — but **production usage is broken**.
- **Severity:** important (silent reachability failure).
- **Upgrade:**
  ```python
  for ancestor in this_file.parents:
      if (ancestor / "Tools" / "mcp-toolkit").is_dir():
          repo_root = ancestor / "Tools" / "mcp-toolkit"
          break
      if (ancestor / ".git").is_dir():  # OR repo root
          repo_root = ancestor
          break
  ```
  And update the docstring to match the new behavior, OR move the presets directory into the repo where the sandbox check expects it.

#### `lock_preset` / `unlock_preset` — lines 256, 263
- **Prior:** A. **Mine:** **C**. **DISPUTE.**
- **What they do:** Return `replace(profile, lock_preset=True/False)`.
- **Bug/gap:** **`PresetLocked` is never raised anywhere.** The lock flag is set but no code checks it. So `lock_preset()` is a label, not enforcement. Anyone can call `replace(locked_profile, erosion_iterations=999)` and get a mutated copy regardless. The lock is **decorative.**
- **AAA gap:** UE5's `FScalabilitySettings` enforces lock via runtime CVar `sg.QualityLevel` validation. Unity's `QualitySettings.lockSetting` (preview) blocks runtime mutation.
- **Severity:** important.
- **Upgrade:** Either:
  - (a) raise `PresetLocked` from `_merge_with_parent` / `replace` callsites if `parent.lock_preset`, OR
  - (b) document this is a hint flag and remove `PresetLocked` exception class.

---

## Cross-Module Findings

### CM-1: Hot-reload watches dead modules (CRITICAL)
**Files:** `terrain_hot_reload.py:20-29`
**Verified at runtime.** Every module name in `_BIOME_RULE_MODULES` and `_MATERIAL_RULE_MODULES` references a non-existent `blender_addon` package. Production iteration gets zero benefit from this module.

### CM-2: `edit_hero_feature` is a stub (CRITICAL)
**Files:** `terrain_live_preview.py:138-183`
**Verified at runtime.** Returns success without mutating anything. Any test using this for hero edits is silently false-positive. Combined with CM-1, the entire "live editing" story for this codebase is hollow: you can't reload tuned modules, and you can't edit hero features.

### CM-3: Quality profile sandbox blocks repo writes (HIGH)
**Files:** `terrain_quality_profiles.py:217-234`
**Verified at runtime.** The intended preset directory path is unreachable in this repo's layout.

### CM-4: `id()`-keyed sidecar registry leaks (HIGH)
**Files:** `terrain_scene_read.py:80, 91`
GC recycles `id()`. Long Blender sessions silently corrupt extended metadata.

### CM-5: Frustum cull degenerate basis silently passes everything (HIGH)
**Files:** `terrain_viewport_sync.py:166-176`
**Verified at runtime.** Top-down view with `up=(0,0,1)` over `focal=(0,0,0)` returns True for any point in `visible_bounds`. Aspect ratio also missing. Both critical for any code that uses this for vantage-aware computation (Bundle H composition).

### CM-6: Polling-mtime hot-reload is below indie quality (MEDIUM)
**Files:** `terrain_hot_reload.py:93-125`
No `watchdog.Observer`, no debounce, no auto-poll thread. Only fires on manual `check_and_reload()` call.

### CM-7: Unbounded history in LivePreviewSession (MEDIUM)
**Files:** `terrain_live_preview.py:56`
List grows forever. After 1 hr of iteration the session may consume hundreds of MB.

### CM-8: Cache invalidation by string prefix over-invalidates (MEDIUM)
**Files:** `terrain_live_preview.py:87` + `terrain_mask_cache.py:120-125`
`invalidate_prefix("height")` invalidates anything beginning with "height". Need a precise channel→key index.

### CM-9: Quality profiles cover authoring only, not runtime (MEDIUM)
**Files:** `terrain_quality_profiles.py:39-59`
Roughly 1/8th the surface of Unity URP / UE5 Scalability. No view distance, shadow distance, LOD bias, foliage density, streaming pool size.

### CM-10: Review ingest silently drops malformed entries (MEDIUM)
**Files:** `terrain_review_ingest.py:80-97`
**Verified at runtime.** A reviewer's typo silently drops a hard finding. No log, no count, no warning.

---

## Final Module Grades

| File | Functions | Critical Issues | Grade |
|---|---|---|---|
| `terrain_budget_enforcer.py` | 8 | naive tri-count, density unit confusion | **A−** |
| `terrain_scene_read.py` | 4 | `id()`-keyed sidecar (data corruption) | **B+** |
| `terrain_review_ingest.py` | 3 | silent skip, monotonic counter, no dedup | **A−** |
| `terrain_hot_reload.py` | 8 (incl. methods) | **wrong package path, no Observer, no debounce** | **D** |
| `terrain_viewport_sync.py` | 6 | square FOV, degenerate-basis silent pass, no near/far, forever-headless | **B+** |
| `terrain_live_preview.py` | 8 (incl. methods + free fn) | `edit_hero_feature` is **F** stub; rest A−/B+ | **C+** (mod avg) / **F** for edit_hero_feature |
| `terrain_quality_profiles.py` | 7 | sandbox unreachable, lock not enforced, 1/8 coverage | **B** |

**Overall wave-2 verdict:** Two outright **broken-in-production** modules (`terrain_hot_reload`, `edit_hero_feature`) and three with material correctness bugs (`terrain_scene_read` id-keying, `terrain_viewport_sync` degenerate basis, `terrain_quality_profiles` sandbox). Budget enforcer + review ingest are the two cleanest modules in the batch (A−).

By the user's stated rubric ("Hot-reload that watches wrong path = D. Live preview that's a stub = F."), both verdicts apply literally here.
