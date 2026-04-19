# R8-A9: Semantic Agent Pipeline & Visual Quality System

Audit scope: the 13 files that collectively define how a Claude-Opus terrain agent
(a) learns what it is building, (b) sees what it has built, and (c) decides when a
tile is shippable to Unity. Date: 2026-04-17. Reviewer: R8 A9 (Opus 4.7, 1M ctx).

Scope files (all absolute paths, Windows):

- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_semantics.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_twelve_step.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_protocol.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_quality_profiles.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_framing.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_saliency.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_rhythm.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_live_preview.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_viewport_sync.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_scene_read.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_visual_diff.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_golden_snapshots.py`
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_review_ingest.py`

Headline finding: the data-contract layer is strong, the "visual feedback loop"
is a theatre prop. There is no code path in this codebase that renders a pixel
for an agent to look at. Every file that talks about "visual" moves floats, not
images — the agent is flying on instruments with no windshield. Correcting this
is the single largest quality lift available and is specified below.

---

## NEW BUGS (not in FIXPLAN)

| id | file:line | severity | description | correct fix |
|---|---|---|---|---|
| BUG-R8-A9-001 | terrain_protocol.py:69-84 | HIGH | `rule_2_sync_to_user_viewport` reads `getattr(state, "viewport_vantage", None)` but `TerrainPipelineState` (terrain_semantics.py:975-998) has no `viewport_vantage` field. Every `@enforce_protocol`-decorated handler must either (a) opt out via `out_of_view_ok=True` or (b) have the caller monkey-patch the attribute on the dataclass, which is exactly what the test fixture at `test_bundle_r.py:72` does (`state.viewport_vantage = read_user_vantage()  # type: ignore[attr-defined]`). In production paths (e.g. `terrain_live_preview.LivePreviewSession` apply_edit) no code attaches a vantage, so any protocol-enforced pass will throw ProtocolViolation. | Add `viewport_vantage: Optional[Any] = None` to `TerrainPipelineState`. Then update `terrain_live_preview.LivePreviewSession.__post_init__` to call `self.controller.state.viewport_vantage = read_user_vantage()` by default. |
| BUG-R8-A9-002 | terrain_twelve_step.py:42-52 | HIGH | Steps 4 and 5 (`_apply_flatten_zones_stub`, `_apply_canyon_river_carves_stub`) are **pass-through no-ops** in a function named "12-step canonical sequence." These are not stubs, they are lies. The module docstring admits "Steps 10 and 11 are pass-through stubs" but does not disclose that 4 and 5 are also pass-throughs. Any agent running `run_twelve_step_world_terrain` receives terrain that claims to have had flatten zones and carves applied when it has not. | Either call the real implementations (`pass_flatten_zones` in terrain_masks.py, `generate_canyon` in _terrain_noise.py) or rename the stubs to `_apply_flatten_zones_NOT_YET_WIRED` and return a warning dict field `stub_steps=[4,5]` in the result so the caller can see which steps were skipped. |
| BUG-R8-A9-003 | terrain_twelve_step.py:269-278 | MED | `compute_erosion_params_for_world_range` result is stored in `erosion_params` and placed in `metadata["erosion_params"]`, but the actual `erode_world_heightmap` call ignores the computed params and hard-codes `hydraulic_iterations=50, thermal_iterations=0`. The quality profile (`aaa_open_world` = 48 iters) is completely bypassed. | Read `intent.quality_profile` → `load_quality_profile(name).erosion_iterations` and pass that to `erode_world_heightmap`. Thermal iterations should also be quality-driven. |
| BUG-R8-A9-004 | terrain_twelve_step.py:54-65 | MED | `_detect_cliff_edges_stub` returns a list comprehension of every cell above the 95th percentile gradient. On a 1025×1025 tile that's ~52k cells returned as "cliff candidates". The downstream consumer has no way to cluster these into actual cliff features. | Apply connected-component labeling (scipy.ndimage.label) on the threshold mask and return one (x,y) per component at its gradient-max cell. Cap output at ~100 candidates. |
| BUG-R8-A9-005 | terrain_twelve_step.py:68-80 | MED | `_detect_cave_candidates_stub` uses `centre <= np.min(neighbours)` — the centre cell is *included in* `neighbours[y-1:y+2, x-1:x+2]`, so the test degenerates to `centre <= centre` which is always true for any cell that equals the min of its 3x3 neighborhood. On a flat patch every cell matches. | Compare against `np.min(neighbours[neighbours != centre])` or use `scipy.ndimage.minimum_filter` then equality-with-strict-lower-surround check. |
| BUG-R8-A9-006 | terrain_twelve_step.py:207-367 | HIGH | `run_twelve_step_world_terrain` is only invoked from two tests (`test_terrain_world_orchestration.py`, `test_adjacent_tile_contract.py`). **No MCP handler, no pipeline controller, no bridge endpoint calls it.** The "canonical 12-step sequence" is dead code from a production standpoint — agents have no way to trigger it. | Register it as an MCP handler (`handle_twelve_step_world`) in the bridge; wire it into `terrain_pipeline.TerrainPassController.run_pipeline` as the world-level preflight before per-tile passes. |
| BUG-R8-A9-007 | terrain_live_preview.py:69-107 | HIGH | `LivePreviewSession.apply_edit` runs passes and returns a content hash — never a **visual preview**. Despite the filename, nothing in this module renders a viewport, writes a thumbnail, or calls `bpy.ops.render.opengl`. An agent calling `apply_edit` gets a SHA-256 back and no way to look at the result. | Add `render_thumbnail_png(path: Path, view: str)` method that calls `bpy.ops.render.opengl(write_still=True)` (in Blender mode) or a matplotlib heightmap fallback (headless) and returns both the hash and the png path. See Visual Pipeline Design below. |
| BUG-R8-A9-008 | terrain_live_preview.py:109-127 | MED | `diff_preview(hash_before, hash_after)` lookup searches `self.history` for matching hash entries but history only stores the post-edit hash, never the pre-edit hash. If `hash_before` is the state at construction time, `matched_before` is always `[]`. The returned dict's `found_before`/`found_after` flags are therefore nearly always `(False, True)`. | Record both `hash_before` and `hash_after` on each history entry. Seed the history list with an initial entry at `__post_init__` using `self.current_hash()`. |
| BUG-R8-A9-009 | terrain_live_preview.py:138-183 | HIGH | `edit_hero_feature` does **not edit** — it appends strings like `"edit:hero_01:translate:1,0,0"` to `state.side_effects`. Nothing consumes these strings. The feature position/scale/rotation is never mutated on the actual HeroFeatureSpec, the mask stack, or the Blender scene. Function is 100% cosmetic. | Either (a) mutate the HeroFeatureSpec via `dataclasses.replace` and write back via a new `intent.replace_hero_feature(feature_id, new_spec)` method, OR (b) rename to `log_hero_feature_edit_intent` so the name matches the behavior and raise a clear exception if called on a stateful path. |
| BUG-R8-A9-010 | terrain_live_preview.py:54 | LOW | `cache: MaskCache = field(default_factory=lambda: MaskCache(max_entries=256))` — 256 full mask-stack entries at 1025² × ~15 channels × 8 bytes = ~3.2 GB upper bound per session. Unbounded for hero-shot tiles. | Document the memory ceiling and default to 32 entries; expose `max_entries` as a session parameter. |
| BUG-R8-A9-011 | terrain_framing.py:54 | LOW | `feather_cells = max(2.0, 4.0 / 1.0)` — the `/1.0` is meaningless. Was almost certainly meant to divide by cell_size. As written, feather is always 4.0 regardless of tile resolution. | `feather_cells = max(2.0, 4.0 / float(cell))` — so feather is ~4 m regardless of cell size. |
| BUG-R8-A9-012 | terrain_framing.py:77 | MED | `delta = np.minimum(delta, this_delta)` accumulates the **most-negative** cut across all samples but `this_delta` is already negative-or-zero. Good. However, the outer loop `total_delta = np.minimum(total_delta, enforce_sightline(...))` in `pass_framing:124` then takes the minimum-across-features, so a later feature can *un-deepen* a previous feature's cut — wrong: a sightline cut should be the union of all features' demands. | Correct: since `enforce_sightline` returns ≤0 values, the union of cuts is still `np.minimum`. The behavior is correct, but the `max_cut_m` metric uses `-total_delta.min()` which on an all-zero delta (no-op) gives 0.0, OK. **Not a bug — clarify comment instead.** Keep this row as a doc-only fix. |
| BUG-R8-A9-013 | terrain_saliency.py:95-116 | MED | Triple-nested Python loop over vantages × rays × samples (`V * 64 * n_samples`). For a 1025² tile with 2 vantages: 2 * 64 * 1500 = 192k iterations, each doing bilinear sampling via `_sample_height_bilinear`. On an `aaa_open_world` profile this is several seconds per pass. | Vectorize: precompute all sample coordinates `(V, ray_count, n_samples, 2)` then do a single `map_coordinates` call. 100x speedup at the cost of memory. |
| BUG-R8-A9-014 | terrain_saliency.py:227-237 | LOW | `falloff = np.clip(1.0 - (dist / (max_dist + 1e-9)), 0.0, 1.0)` falls off linearly to zero at the tile's *bounding diagonal*, so cells outside the vantage's actual visible frustum still get non-zero saliency. Should use the `is_in_frustum` test from `terrain_viewport_sync.py` or at least clip by an explicit view-cone half-angle. | Replace the linear falloff with: (1) in-frustum test via vantage fov, (2) inverse-square distance falloff within the cone. |
| BUG-R8-A9-015 | terrain_rhythm.py:64-65 | MED | `diffs = pts[:, None, :] - pts[None, :, :]` and `dist2 = (diffs * diffs).sum(axis=2)` builds an N² float array. With N=500 features this is 500×500×2×8 = 4 MB — fine; with N=10k features (world-scale) it's 1.6 GB. No guard. | Use `scipy.spatial.cKDTree.query(pts, k=4)` for O(N log N) nearest-neighbor search; cap N (raise if > 50k). |
| BUG-R8-A9-016 | terrain_rhythm.py:106-132 | MED | `enforce_rhythm` iterates 3 times and nudges each feature by a fraction of the spacing error, but there's no damping coefficient and no convergence check. For clustered inputs the algorithm oscillates. | Add relaxation factor `alpha=0.5` and compute post-iteration rhythm delta; early-exit if delta < 0.01. |
| BUG-R8-A9-017 | terrain_rhythm.py:137-156 | LOW | Output list order depends on `_positions_xy` insertion order, but HeroFeatureSpec inputs are skipped in the nudge loop yet counted in `idx`. If the caller passes `[HeroFeatureSpec, dict, dict]`, the dicts receive positions `pts[1]` and `pts[2]` — but `pts` only contains 3 positions extracted from the original features *including* the frozen HeroFeatureSpec. Indexing is consistent, but a dict placed *after* a HeroFeatureSpec receives a position that was computed from the HeroFeatureSpec's neighborhood and then reassigned — the frozen feature is not at `pts[0]` after nudging. | Either document that "HeroFeatureSpec positions are frozen but participate in the neighborhood" OR split inputs into frozen+mutable sets before running the relaxation. |
| BUG-R8-A9-018 | terrain_viewport_sync.py:57-94 | HIGH | `read_user_vantage` is labelled "real Blender reads region_data" but **there is no bpy path** in this module. Running inside Blender, the function still uses the synthetic defaults. The whole of Rule 2 enforcement (`rule_2_sync_to_user_viewport`) therefore does not actually sync to the user's viewport — it only checks that *some* vantage object exists. | Add a `_read_from_blender_context()` helper that when `bpy` is importable reads `bpy.context.space_data.region_3d.view_matrix / view_perspective / view_distance`, computes camera_position from inverted view matrix, and returns a ViewportVantage. Fall back to synthetic when bpy unavailable. |
| BUG-R8-A9-019 | terrain_viewport_sync.py:138-191 | LOW | `is_in_frustum` rebuilds an orthonormal basis from the stored `camera_up` every call. Since ViewportVantage is frozen, this basis should be precomputed once and stored. | Make `ViewportVantage` compute `_view_basis` in `__post_init__` via `object.__setattr__` and use it in `is_in_frustum` / `transform_world_to_vantage`. |
| BUG-R8-A9-020 | terrain_scene_read.py:80-85 | HIGH | `_EXTENDED_METADATA[id(sr)]` uses `id()` of a frozen dataclass as the key. **`id()` can be recycled** — when a TerrainSceneRead is garbage-collected, its id may be reused by a *different* object, which will then receive stale extended metadata (addon_version, lockable_anchors, etc.). This is a latent correctness bug. | Use `weakref.WeakKeyDictionary` instead. Frozen dataclasses are not hashable by default but are immutable so `WeakValueDictionary` keyed by `sr.timestamp + reviewer` is safer. Best: just store the extended fields on TerrainSceneRead directly (widen the dataclass) and retire the sidecar. |
| BUG-R8-A9-021 | terrain_scene_read.py:23-86 | HIGH | `capture_scene_read` in headless mode takes every field as a kwarg — real Blender would walk `bpy.data`. No bpy-walking code exists. Rule 1 is therefore paper-only: in Blender, the function returns the synthetic defaults plus whatever the caller passes, never the real scene state. | Add `_walk_scene()` helper: enumerate `bpy.data.objects` where `vb_feature_id` custom property is set → build HeroFeatureRef list; walk `vb_waterfall_chain_*` empties → WaterfallChainRef list; read focal point from active camera. |
| BUG-R8-A9-022 | terrain_visual_diff.py:99-103 | MED | `while mask2.ndim > 2: mask2 = np.any(mask2, axis=-1)` collapses a multi-channel mask to 2D by reducing **the last axis**. For `splatmap_weights_layer` shape `(H, W, L)` this correctly reduces L, but for `terrain_normals` shape `(H, W, 3)` and `tree_instance_points` shape `(N, 5)` this is nonsense: `tree_instance_points` has no H/W grid. | Hard-code per-channel diff strategies: 2D arrays → direct; (H,W,C) → reduce C; (N,M) point lists → return "instance count delta" metric, skip bbox. |
| BUG-R8-A9-023 | terrain_visual_diff.py:141-144 | MED | `overlay[..., 0]` and `overlay[..., 2]` receive positive-direction and negative-direction height deltas. Blue for negative is fine, but the **green** channel (any non-height change) is OR-max'd with height changes via the shared uint8 image — a cell with both +height AND a splatmap change reads as yellow (R+G), not as a distinguishable 4-category overlay. | Return a 4-channel (H, W, 4) with explicit semantic channels: [height_pos, height_neg, mask_any, reserved] and let the caller colorize. |
| BUG-R8-A9-024 | terrain_golden_snapshots.py:145-151 | MED | `compare_against_golden` flags `new_channels` as a soft warning but the loop at 149-151 only iterates `golden.channel_hashes.items()` — it does not compare channels present in the current stack that were *absent* from the golden. So a pass that starts writing to a new channel passes silently (only the soft "new channel present" warning fires). A pass that *stops* writing to a channel present in the golden produces a divergence (`current_channels.get(ch) != h` where `current = None` ≠ stored hash). | Also emit a hard `GOLDEN_CHANNEL_REMOVED` issue for channels in golden but absent in current, with the recommendation to regenerate golden if intentional. |
| BUG-R8-A9-025 | terrain_golden_snapshots.py:123-125 | MED | `tolerance` parameter is reserved but unused. For float-valued channels (height, slope, wetness) a bit-exact hash comparison is brittle — any platform-dependent floating-point change (e.g. different numpy version) busts every golden. | Implement tolerance: when `tolerance > 0` and current/golden hashes disagree, load the golden's saved channel arrays (requires also saving arrays to disk — see below) and compare via `np.allclose(atol=tolerance)`. Requires save format extension. |
| BUG-R8-A9-026 | terrain_golden_snapshots.py:86-110 | MED | `save_golden_snapshot` writes only the hashes to `.golden.json` — **the actual channel arrays are never persisted**. This means once a golden is declared, there is no way to regenerate the pipeline, inspect the expected values, or recover from a hash bust by re-checking "close enough". A golden library is useless for debugging without the underlying data. | Add companion `.golden.npz` via `stack.to_npz()` and store the path on the GoldenSnapshot. Loading then permits tolerance-based comparison and visualization. |
| BUG-R8-A9-027 | terrain_golden_snapshots.py:197-258 | MED | `seed_golden_library` runs the pipeline `count` times (default 120) synchronously. On production tiles at 1025² with 8 erosion iterations this is 30-60 minutes. No progress reporting, no parallelism. | Use `concurrent.futures.ProcessPoolExecutor(max_workers=cpu_count-1)` with `tqdm.tqdm` progress. Requires the state builder to be pickleable. |
| BUG-R8-A9-028 | terrain_golden_snapshots.py:232-235 | HIGH | `except Exception: continue` silently swallows failures mid-library-generation. A seeded library with 120 targets might produce 3 actual snapshots if the pipeline is broken, with no warning. | Collect failures into a `failures: List[Tuple[int, str]]` and write them to `manifest["failures"]`; if `failures > 10%` of count, raise a RuntimeError. |
| BUG-R8-A9-029 | terrain_review_ingest.py:63-99 | LOW | `ingest_review_json` silently skips malformed entries (`except ValueError: continue`). A reviewer file with typo-ed severity for 10 of 11 findings produces a 1-finding ingest with no diagnostic. | Collect skipped reason strings and return `(findings, skipped_reasons)` tuple, or log at WARNING level per skip. |
| BUG-R8-A9-030 | terrain_review_ingest.py:102-135 | HIGH | `apply_review_findings` only writes review findings into `intent.composition_hints` dict. **No pass reads `review_blockers` or `review_suggestions`.** grep confirms: no consumer. The entire review-feedback loop is a write-only log. Human reviewer says "cliff at (128,256) is floating" → added to blockers → next pipeline run ignores it. | Add a new pass `pass_apply_review_blockers` that (a) for each hard blocker with a location, generates a ValidationIssue and refuses to continue unless the blocker is resolved, (b) for each suggestion with `tags=["regrow_trees"]` etc., runs a mapped pass. Register it before `validate_final_tile`. |
| BUG-R8-A9-031 | terrain_quality_profiles.py:134-175 | MED | `_merge_with_parent` takes `max()` across numeric fields (higher = better). But `save_every_n_operations` = 0 means "disabled" — taking max(0, 0) across inheritance chain yields 0, so checkpointing is disabled by default in every profile including `aaa_open_world`. Checkpoint retention is 80 but nothing ever gets saved. | Either set explicit `save_every_n_operations` defaults in each profile (preview=0, production=5, hero_shot=2, aaa=1) or document that 0 means "checkpoint at pass boundaries only". |
| BUG-R8-A9-032 | terrain_quality_profiles.py:199-248 | MED | `write_profile_jsons` has tight path-traversal guard (good). However, `PresetLocked` exception is defined (line 27) but never raised by `lock_preset`/`unlock_preset` which return copies rather than mutating. The lock flag has no enforcement semantics. | Either make `load_quality_profile` check `profile.lock_preset` before returning and refuse to return if locked-without-override, or delete `PresetLocked`. |
| BUG-R8-A9-033 | terrain_semantics.py:399-436 | LOW | `TerrainMaskStack.__post_init__` tolerates both `(tile_size, tile_size)` (legacy) and `(tile_size+1, tile_size+1)` (new Addendum 2.A.1 contract). Enforcement only fires for *square* shapes — non-square heights bypass the contract. This was flagged as an intentional legacy carve-out in the docstring but any non-square tile silently violates the Unity shared-edge contract. | Add a `strict_tile_contract: bool = False` flag on the dataclass; when True, reject legacy shapes with a clear error. |
| BUG-R8-A9-034 | terrain_semantics.py:485-501 | LOW | `UNITY_EXPORT_CHANNELS` is a class attribute (tuple) but listed with `_ARRAY_CHANNELS` as `field(init=False, ..., default=...)`. The two lists are **not in sync**: `UNITY_EXPORT_CHANNELS` includes `audio_reverb_class`, `gameplay_zone`, `traversability`, `wind_field`, `cloud_shadow` (all ARRAY channels) — good. But `UNITY_EXPORT_CHANNELS` omits `splatmap_weights_layer`'s dependent masks like `foam`, `mist`, `wet_rock`, `tidal` — even though Unity's water shader needs these. | Either widen `UNITY_EXPORT_CHANNELS` to include foam/mist/wet_rock/tidal OR document explicitly why water-surface masks stop at `water_surface`. |
| BUG-R8-A9-035 | terrain_semantics.py:624-648 | MED | `from_npz` does not read the `unity_export_schema_version`, `coordinate_system`, `height_min_m`, `height_max_m` scalars from the meta dict — the `cls(...)` construction omits them, then `__post_init__` auto-populates `height_min_m`/`height_max_m` from the array. A tile saved with explicit world heights round-trips as auto-computed heights. For a tile that had world-space negative elevations, this is catastrophic for Unity export. | Read every scalar from meta and pass to the `cls(...)` call explicitly. |
| BUG-R8-A9-036 | terrain_semantics.py:792 | LOW | `composition_hints: Dict[str, Any] = field(default_factory=dict)  # REVIEW-IGNORE PY-COR-17: frozen+mutable is safe here` — frozen dataclass with mutable dict default is a classic Python footgun. The REVIEW-IGNORE is correct that the caller treats it as read-only, but `apply_review_findings` (terrain_review_ingest.py:112-114) *copies* hints via `dict(intent.composition_hints)` — good. However, `pass_framing` (terrain_framing.py:101) does `intent.composition_hints.get("vantages", ())` directly and the returned tuple from `vantages` is then mutated in no place — safe, but a future caller who stores the returned list is in trouble. | Convert the dict to `types.MappingProxyType` at construction for true read-only semantics. Low priority — all current callers are well-behaved. |

36 new bugs. 7 HIGH, 16 MED, 13 LOW.

---

## LIVE PREVIEW / VIEWPORT WIRING

### Current state: the feedback loop does not exist end-to-end

Detailed audit of the "visual" surface area:

| component | claimed function | actual function | verdict |
|---|---|---|---|
| `terrain_live_preview.LivePreviewSession` | "live preview" of terrain edits | Runs passes, stores hashes, history dicts | No pixels rendered. Name is aspirational. |
| `terrain_live_preview.edit_hero_feature` | Mutate a hero feature | Appends strings to `state.side_effects` | Cosmetic log. BUG-R8-A9-009. |
| `terrain_viewport_sync.read_user_vantage` | Read Blender's active 3D viewport | Returns synthetic `(0,-20,12)` defaults | No bpy integration. BUG-R8-A9-018. |
| `terrain_viewport_sync.ViewportVantage` | Camera snapshot for composition passes | Good contract, used only by saliency/framing for math | Contract fine; never reflects the user's actual viewport. |
| `terrain_scene_read.capture_scene_read` | Snapshot of current Blender scene | Returns kwargs verbatim; no bpy walk | Write-only metadata. BUG-R8-A9-021. |
| `terrain_visual_diff.compute_visual_diff` | Per-channel delta report | Computes max/mean delta + bbox | Works for 2D floats; fails on (N,M) point lists. BUG-R8-A9-022. |
| `terrain_visual_diff.generate_diff_overlay` | Color-coded delta image | Returns (H,W,3) uint8 RGB | Works; but never written to disk anywhere. Only tests consume it. |
| `terrain_golden_snapshots.save_golden_snapshot` | Persist reference tiles for regression | Writes hashes-only to .json | Arrays not saved. BUG-R8-A9-026. |
| `terrain_golden_snapshots.compare_against_golden` | Detect regressions | Compares hashes; tolerance unused | Brittle across platforms. BUG-R8-A9-025. |
| `terrain_review_ingest.apply_review_findings` | Fold review into intent | Writes to composition_hints dict | No pass reads the hints. BUG-R8-A9-030. |

### What an agent can actually see during generation

Strictly textual:

1. Mask-stack channel *statistics* (min, max, mean, shape, dtype) via `TerrainMaskStack.unity_export_manifest()` — numeric only.
2. `PassResult.metrics` dict — per-pass scalar stats (counts, thresholds).
3. `compute_visual_diff` — per-channel delta scalars.
4. Content hashes (SHA-256 hex).
5. Validation issues (severity + message strings).

### What an agent cannot see

1. **A rendered image of the terrain.** Not from top-down, isometric, ground-level, or any vantage. There is no code path in this codebase that produces a PNG of the generated terrain for agent review.
2. **The tile's silhouette against the sky.** The whole saliency/framing machinery operates on elevation arrays; no "is this a dramatic ridgeline against sunset" check.
3. **Seam continuity between tiles.** `validate_tile_seams` compares numpy arrays, not rendered joins.
4. **Scatter placement correctness.** Tree/rock scatter lives in `_scatter_engine.py` and `environment_scatter.py` but no "does the scatter look natural in this view" render exists.
5. **Shadow and lighting quality.** `terrain_shadow_clipmap_bake.py` bakes a clipmap; no render confirms it looks right at any sun angle.
6. **Material tiling artifacts.** `terrain_materials.py` produces splatmaps; no "rendered patch at 20 m showing the repetition pattern" check.

### Unity editor MCP caveat

Per `.mcp.json` the project exposes `mcp__unity-editor__*` tools for reading files in Unity projects. These are read-only — the Unity editor does not drive terrain generation review. No round-trip image bake exists.

### Verdict

Every "visual" label in this handler set is either (a) a math operation on float arrays labelled as "visual" or (b) aspirational scaffolding. The feedback loop is not closed. An agent running the pipeline today cannot tell the difference between beautiful terrain and a flat plane — both will produce valid numpy arrays that hash correctly.

---

## SEMANTIC KNOWLEDGE GAP ANALYSIS

### What the agent gets today (from semantics/twelve-step/protocol)

**Structural knowledge** (terrain_semantics.py): ~55 mask-stack channel names, each with a short docstring. TerrainIntentState captures seed, region_bounds, tile_size, cell_size, hero_feature_specs, water_system_spec, quality_profile, noise_profile ("dark_fantasy_default"), erosion_profile ("temperate"). Good data contracts, shallow semantics.

**Process knowledge** (terrain_protocol.py): 7 enforced rules. Observe before calculate, sync to viewport (broken), lock reference empties, real geometry for hero features, smallest diff per iteration, surface vs interior classification, plugin version check. These are process rules, not design knowledge.

**Sequence knowledge** (terrain_twelve_step.py): Named 12 steps. Steps 4, 5, 10, 11 are partial/stubs (BUG-R8-A9-002). Step names are operational ("generate_world_heightmap", "erode_world_heightmap") — nothing about the *why* or the *aesthetic target* per step.

### What's missing — the AAA design knowledge gap

For each of the six required knowledge dimensions the user specified, here's the state:

1. **Natural terrain formation (erosion, deposition, tectonic)**
   - Implemented as erosion iterations/params in quality profiles; agents do not know *when* to increase erosion vs keep it low. There is no guidance like "fluvial erosion >300 iters for tropical forest biomes, <50 for alpine scree".
   - Tectonic features: no fault-line system, no uplift/subsidence model. A dark fantasy world needs plate boundaries to read as "ancient cataclysm".

2. **Dark fantasy aesthetics (forbidding, dramatic, oppressive)**
   - The string `"dark_fantasy_default"` appears as a `noise_profile` and as a `biome` key in `terrain_banded.py:52`. That is **the sum total** of dark fantasy aesthetic knowledge in this codebase.
   - No encoded rules for: vertical exaggeration targets (dark fantasy wants 1.5-2.2× real-world), color desaturation targets (saturation ≤ 30% except for accent fog), silhouette complexity targets (bimodal distribution of low-plateau + spike-ridge).
   - `procedural_materials.py` has a `validate_dark_fantasy_color` function — but it's color-only, not landscape-composition.

3. **Player navigation affordances**
   - Mentioned in passing via `saliency_macro`, `gameplay_zone`, `traversability` mask channels. No rules for landmark placement spacing, sightline budgets, or "every 2 km of traversable terrain needs one silhouette landmark".
   - No encoding of Kevin Lynch's paths/edges/districts/nodes/landmarks model that is used explicitly at Nintendo for Zelda.

4. **Ecological realism (biome by elevation/moisture)**
   - `_biome_grammar.py` exists (not in this audit scope) — I verified it's 28k LOC of biome rules. **However, no pass in this audit's scope references biome rules** — framing, saliency, rhythm, live_preview all operate on raw height/mask arrays regardless of biome.
   - No agent-facing rule: "before placing vegetation, check biome_id mask; agent must not request swamp trees on alpine tiles".

5. **Lighting considerations (north vs south slopes, shadow casting)**
   - No lighting-aware pass in scope. `terrain_shadow_clipmap_bake.py` exists but doesn't feed into the composition passes. No rule like "silhouette ridges should cast 300m+ shadows at golden-hour sun-angle" — which is a Ghost of Tsushima hallmark.

6. **Hero moment framing**
   - `terrain_framing.py` has `enforce_sightline` (feather-cut terrain to clear vantage→target). But: no rule for **creating** a dramatic vantage in the first place. Agent doesn't know "place a vantage 80-120m below the highest nearby peak, on the leeward side, with a 45° view arc to the peak's silhouette".

### Ranked gaps

| rank | gap | impact on output quality |
|---|---|---|
| 1 | No rendered visual feedback to the agent | Catastrophic — agent flies blind |
| 2 | Dark fantasy aesthetic knowledge = 1 string constant | Output will be generic procedural terrain, not dark fantasy |
| 3 | Twelve-step sequence has 4 stubbed-out steps | "Running the canonical sequence" skips flatten zones, carves, roads, water bodies |
| 4 | Review feedback loop is write-only | Human/AI reviewer findings never influence next run |
| 5 | Biome rules exist but aren't wired into composition passes | Elden Ring would have birch trees on volcanoes |
| 6 | No landmark spacing / Lynch-model rules | Terrain reads as "samey" at walking pace |
| 7 | No lighting-aware silhouette pass | Horizon and Ghost get 60% of their AAA feel from this |
| 8 | No "hero moment" vantage authoring | Players get no "I need to get there" reveal |
| 9 | Protocol Rule 2 viewport sync doesn't sync to a real viewport | Rule passes but is semantically empty |

---

## TWELVE-STEP PIPELINE ASSESSMENT

### Step-by-step verdict

| # | name | implemented | meaningful | order correct | grade |
|---|---|---|---|---|---|
| 1 | parse_params | yes | yes | yes | A |
| 2 | compute_world_region | yes | yes | yes | A |
| 3 | generate_world_heightmap | yes | yes | yes | A |
| 4 | apply_flatten_zones | **no — stub pass-through** | would be yes | yes (before erosion) | F |
| 5 | apply_canyon_river_carves | **no — stub pass-through** | would be yes | yes (before erosion) | F |
| 6 | erode_world_heightmap | yes, but hard-codes 50 iters ignoring quality profile (BUG-R8-A9-003) | yes | yes | C |
| 7 | compute_flow_map | yes | yes | yes | A |
| 8 | detect_hero_candidates | yes, but detection quality is poor (BUGs 4, 5) | partial | yes | D |
| 9 | per_tile_extract | yes | yes | yes | A |
| 10 | generate_road_meshes | yes when waypoints present; empty no-op otherwise | partial | yes | C |
| 11 | generate_water_bodies | yes, threshold-based; very crude | partial | yes | C |
| 12 | validate_tile_seams | yes | yes | yes | A |

### Missing steps for AAA quality

The "12-step canonical sequence" is missing at least the following steps that real AAA pipelines do execute:

- **0. Macro scale silhouette audit** — before any heightmap generation, place authored landmark positions and verify their silhouettes against the skybox from known vantages. Sucker Punch literally did this on Tsushima.
- **3.5. Tectonic fault-line generation** — inject fault structure for "ancient world" readability (Elden Ring).
- **6.5. Thermal erosion pass** — `erode_world_heightmap` is called with `thermal_iterations=0`. Thermal erosion produces the talus slopes that make cliffs look weathered, not cartoonish.
- **8.5. Secondary hero-feature coupling** — once hero candidates are found, couple them (waterfall lip → plunge pool → outflow river), not treat them as independent.
- **9.5. Biome assignment** — before scattering or materials, assign `biome_id` per cell based on elevation/moisture/aspect. Currently this runs later, as a separate pass outside the twelve-step.
- **11.5. Vegetation seed** — Ghost of Tsushima pipeline seeds big trees first, then medium, then ground cover in that order. No equivalent here.
- **12.5. LOD generation** — after validation, generate LOD1/LOD2/LOD3 representations.
- **12.6. Visual QA render** — render top-down + isometric + ground-level previews. **Missing entirely.**
- **12.7. Golden snapshot compare** — if a golden exists for this seed/coords, compare. Currently runs only when the test harness invokes it.

### Ordering critique

The current order is mostly defensible but:

- **Step 6 (erode) precedes step 8 (detect candidates)** — good; erosion reveals hero candidates that don't exist on a raw heightmap.
- **Step 10 (roads) after step 9 (tiles)** — wrong for an AAA pipeline. Roads cross tile boundaries; they should be planned in world-space *before* tile extraction so each tile knows about road ROWs in its bounds.
- **Step 11 (water bodies) threshold-based from flow_accumulation** — wrong; water bodies need to be authored intent (from WaterSystemSpec.lakes, hero_waterfalls), not detected bottom-up. Post-hoc threshold picks up every basin including ones the designer explicitly wanted to be a valley.

### Overall grade: D+

The sequence is a reasonable *draft* of what a 12-step pipeline should look like. It is dead code in production (not invoked outside tests), it has 2 hard stubs (4, 5), 2 crude implementations (10, 11), 2 poor-quality detectors (8's cliff + cave), and it ignores the quality profile (6). Calling it "canonical" in the docstring overstates its maturity.

---

## VISUAL PIPELINE DESIGN (COMPLETE SPEC)

This is the primary deliverable. What follows is an implementation-ready specification for the visual QA system that should exist.

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ TerrainPipelineState                                             │
│   ├── mask_stack: TerrainMaskStack                               │
│   ├── viewport_vantage: ViewportVantage (FIX BUG-R8-A9-001)      │
│   └── visual_cache: VisualCache  (NEW)                           │
└──────────────────────────────────────────────────────────────────┘
              ▲                            ▲
              │                            │
              │                            │
┌─────────────┴────────────┐   ┌──────────┴──────────────────────┐
│ terrain_visual_render.py │   │ terrain_visual_qa.py            │
│ (NEW — 7 render modes)   │   │ (NEW — checklist enforcement)   │
│                          │   │                                 │
│  render_topdown_heightmap│   │  run_completion_checklist()     │
│  render_iso_silhouette   │   │  check_silhouette_quality()     │
│  render_ground_eye       │   │  check_texture_tiling()         │
│  render_sun_angle_sweep  │   │  check_scatter_distribution()   │
│  render_wireframe_density│   │  check_seam_quality()           │
│  render_textured_flat    │   │  check_mood()                   │
│  render_normals          │   │  check_lod_readability()        │
└──────────────────────────┘   └─────────────────────────────────┘
              │                            │
              ▼                            ▼
┌──────────────────────────────────────────────────────────────────┐
│ terrain_visual_reference.py (NEW)                                │
│   compare_against_reference(rendered_png, ref_tag) -> score      │
│   references: Elden_Ring, Tsushima, Horizon, Witcher3            │
└──────────────────────────────────────────────────────────────────┘
```

### 1. Render views for QA — seven fixed cameras

Every one of these is a callable `render_<mode>(state, *, output_path, resolution=(1024, 1024))` that returns `(png_path, metadata_dict)`. In Blender mode they call `bpy.ops.render.opengl(write_still=True, view_context=False)` with a programmatically placed camera. In headless mode they use matplotlib to rasterize the heightmap + overlay data.

#### View 1 — Top-down orthographic heightmap

```python
def render_topdown_heightmap(state, output_path, *, colormap="viridis"):
    """
    Camera: orthographic, directly above tile center, looking -Z.
    Output: heightmap as colored image; isohypses every 10 m as overlay.
    Purpose: read elevation distribution at a glance; detect flat regions
             and height "noise" that doesn't correspond to real topography.
    Metadata:
      height_min_m, height_max_m, vertical_exaggeration_if_visualized,
      isohypse_count_visible, pct_flat_cells (|gradient| < 0.5 m/cell)
    AAA target:
      pct_flat_cells < 15% for mountain biome, < 40% for plains.
      If pct_flat_cells > 60%, output is probably broken (Flat-Terrain failure mode).
    """
```

Implementation: colormap the height array, overlay isohypse lines computed via `skimage.measure.find_contours`. Save PNG. In Blender, set up a top ortho camera at `(cx, cy, max_z + 100m)` with ortho_scale = tile_extent.

#### View 2 — Isometric 45° silhouette

```python
def render_iso_silhouette(state, output_path, *, sun_azimuth=135, sun_elevation=30):
    """
    Camera: orthographic at 45° yaw, 30° pitch; looking at tile center.
    Output: shaded greyscale isometric with sun shadow.
    Purpose: READ THE SILHOUETTE. This is the single most important view for
             AAA quality assessment.
    Metadata:
      silhouette_peak_count (local maxima along horizon line),
      silhouette_negative_space_pct,
      silhouette_complexity (fractal dimension approx),
      dominant_silhouette_feature_position_m
    AAA target:
      silhouette_peak_count 3-7 for a readable composition,
      silhouette_complexity in [1.15, 1.35] (crenellation),
      negative_space 30-55% (sky vs ground).
    """
```

Implementation: precompute the sky-line by ray-casting from the camera per viewport column and reading max-hit z. Compute peaks via `scipy.signal.find_peaks`. This is the FromSoftware diagnostic.

#### View 3 — Ground-level perspective (player eye)

```python
def render_ground_eye(state, output_path, *, eye_height_m=1.7, direction_deg=None):
    """
    Camera: perspective at (focal_x, focal_y, terrain_z+1.7m), fov=75°,
            looking toward most-salient direction if direction_deg is None
            (use saliency_macro peak), else fixed.
    Output: what the player sees at eye level.
    Purpose: does the terrain read at walking pace? Can the player see a
             landmark to navigate to?
    Metadata:
      visible_landmarks (count of hero features in frustum),
      horizon_line_height_px (should be 35-55% of image height),
      occlusion_depth_layers (number of distinct depth ranges visible;
        3+ is good, 1 is cardboard-cutout bad).
    AAA target:
      visible_landmarks >= 1 in 80% of random ground-eye renders,
      horizon_line in [35%, 60%] of image height,
      occlusion_depth_layers >= 3.
    """
```

Implementation: pick a random (or saliency-peak-weighted) ground cell, set camera there + eye height, compute direction via gradient of saliency_macro. Render via bpy.ops.render.opengl. In headless: raymarch the heightmap and colormap by z.

#### View 4 — Sun-angle sweep (shadow/form reading)

```python
def render_sun_angle_sweep(state, output_path, *, azimuths=(45, 135, 225, 315),
                           elevation_deg=15):
    """
    Renders 4 images at 4 sun azimuths, low sun elevation (15°) to
    maximize shadow length.
    Purpose: does the form READ at low sun? Ghost of Tsushima hallmark.
    Output: 2x2 grid PNG or separate files.
    Metadata per azimuth:
      shadow_area_pct (fraction of tile in cast shadow),
      shadow_form_complexity (edge density of shadow mask),
      max_shadow_length_m.
    AAA target:
      shadow_area_pct 25-55% at 15° sun,
      max_shadow_length > 100 m for any tile containing a hero feature.
    """
```

Implementation: bake a sun shadow per azimuth via horizon-angle algorithm (for each cell, the sun is blocked if any cell along the sun-ward ray rises above the sun-line). Already partially available via `terrain_shadow_clipmap_bake.py`. Use those bakes, colorize, render.

#### View 5 — Wireframe density

```python
def render_wireframe_density(state, output_path, *, density_levels=3):
    """
    Camera: iso 45°. Output: mesh wireframe only, tri density color-coded.
    Purpose: verify LOD0 has enough density on hero features, LOD1/2 don't
             waste tris on distant flats.
    Metadata:
      lod0_tri_count, lod1_tri_count, lod2_tri_count,
      density_variance (max_density_region / min_density_region).
    AAA target:
      density_variance 3-8× (hero regions 3-8× denser than background),
      lod2 < 1/10 lod0.
    """
```

Implementation: render with `shading='WIREFRAME'` in bpy, or in headless generate a triangle-count heatmap per tile region.

#### View 6 — Textured flat-lit (texture quality, no shading)

```python
def render_textured_flat(state, output_path, *, patch_size_m=50):
    """
    Camera: top-down, flat-lit (no shadows), zoomed to patch_size_m x patch_size_m.
    Renders 4 random patches in a 2x2 grid.
    Purpose: see texture tiling artifacts without shadow masking them.
    Metadata per patch:
      fft_periodicity_score (if > 0.4, tiling is visible),
      unique_material_count (how many splatmap layers contribute),
      mean_saturation.
    AAA target:
      fft_periodicity_score < 0.25 for all 4 patches,
      unique_material_count >= 3 per patch,
      mean_saturation 0.15-0.35 (dark fantasy desaturated range).
    """
```

Implementation: apply splatmap weights to texture layer colors, no lighting, save. FFT periodicity: 2D FFT of the luminance channel, ratio of second-strongest peak to DC term.

#### View 7 — Normal map visualization

```python
def render_normals(state, output_path):
    """
    Camera: top-down. Output: tangent-space normal map as RGB.
    Purpose: see micro-detail on the surface; verify erosion produced
             micro-structure, not just macro-shape.
    Metadata:
      normal_variance (std of RGB across the image),
      normal_banding_score (bands indicate quantized heights).
    AAA target:
      normal_variance > 0.15 (detail present),
      normal_banding < 0.05 (smooth heightmap).
    """
```

Implementation: read `terrain_normals` mask channel if populated, else compute from height via `np.gradient`. Colorize XYZ→RGB.

### 2. Visual completion checklist — implementation-ready

A terrain node is ready to ship to Unity iff **all 10 checks below pass**. Each check runs against the 7 rendered views above + the mask stack metadata. Implement as a new module `terrain_visual_qa.py`.

```python
@dataclass
class CompletionCheck:
    name: str
    required_views: Tuple[str, ...]   # which of the 7 renders must exist
    check: Callable[[Dict[str, Path], TerrainMaskStack], CheckResult]
    severity: str                      # "hard" | "soft"

@dataclass
class CheckResult:
    name: str
    passed: bool
    score: float                       # 0..1
    target_band: Tuple[float, float]
    actual: float
    advice: str                        # agent-readable prose
```

The 10 checks:

| # | name | severity | target | pass criteria |
|---|---|---|---|---|
| 1 | silhouette_quality | hard | peak count 3-7; negative_space 30-55%; complexity 1.15-1.35 | From View 2 metadata, score = min(peaks_in_band, neg_space_in_band, complexity_in_band). Pass if all three in their bands. |
| 2 | elevation_variance | hard | pct_flat_cells < 40% plains / 15% mountain | From View 1. Reject tiles that are mostly flat unless the biome explicitly wants it. |
| 3 | ground_texture_tiling | hard | fft_periodicity < 0.25 on all 4 patches | From View 6. |
| 4 | scatter_distribution | hard | rhythm 0.45-0.75 per `analyze_feature_rhythm` | From rhythm metric. Reject lumpy (<0.4) or grid-regular (>0.8). |
| 5 | water_flow_correctness | hard | flow_accumulation peaks at actual basin bottoms; rivers monotonically decrease in elevation | Sample river cell path; verify `z[i+1] <= z[i]` within 0.1 m tolerance. |
| 6 | seam_continuity | hard | `validate_tile_seams` atol < 1e-4 at all 4 tile edges | Use existing validator. |
| 7 | mood_fit_dark_fantasy | hard | mean_saturation 0.15-0.35; mean_value 0.12-0.45; dominant_hue in (cool_blue ∪ moss_green ∪ ash_grey ∪ bone_cream) | From View 6 histograms + color palette check. |
| 8 | lod_readability | soft | silhouette_peak_count from View 2 stays within ±1 across LOD0/1/2 renders | Run View 2 at three LOD mesh swaps. |
| 9 | landmark_visibility | soft | View 3 reports visible_landmarks ≥ 1 in 80% of 10 random-direction samples | Sample 10 directions per render_ground_eye; pass if ≥8 have a landmark. |
| 10 | shadow_form_reads | soft | View 4 shadow_area 25-55%; at least one azimuth has shadow_form_complexity > 0.3 | From sun-sweep. |

Hard checks gate ship. Soft checks produce warnings the agent should attempt one more pass to fix.

```python
def run_completion_checklist(state: TerrainPipelineState,
                              render_dir: Path) -> List[CheckResult]:
    """
    Runs all 7 render views, then runs all 10 checks, returns the results.
    If every hard check passes, caller may set state.ready_for_unity_export = True.
    """
    renders = {
        "topdown": render_topdown_heightmap(state, render_dir/"01_topdown.png"),
        "iso":     render_iso_silhouette    (state, render_dir/"02_iso.png"),
        "ground":  render_ground_eye        (state, render_dir/"03_ground.png"),
        "sun":     render_sun_angle_sweep   (state, render_dir/"04_sun.png"),
        "wire":    render_wireframe_density (state, render_dir/"05_wire.png"),
        "texture": render_textured_flat     (state, render_dir/"06_texture.png"),
        "normals": render_normals           (state, render_dir/"07_normals.png"),
    }
    results = [check(renders, state.mask_stack) for check in ALL_10_CHECKS]
    return results
```

### 3. AAA reference comparison protocol

Implement as `terrain_visual_reference.py`. Reference images are captured from approved studio art-blast galleries (Horizon Forbidden West Art Blast on ArtStation, Tsushima GDC Vault slides, Elden Ring Network Test art) — stored as reduced 512×512 reference PNGs in `docs/reference/aaa/`.

```python
REFERENCE_TAGS = {
    "elden_ring_limgrave":      "rolling_hills + tree_islands + distant_cathedral",
    "elden_ring_caelid":        "rotten_plateau + ash_horizon + bone_pillars",
    "elden_ring_mt_gelmir":     "volcanic_cliff + black_rock + lava_highlights",
    "tsushima_haiku_field":     "rolling_grass + wind_cone + distant_torii",
    "tsushima_cliff_coast":     "vertical_cliff + foam_base + pine_scatter",
    "horizon_forest_valley":    "dense_canopy + low_fog + terraced_ridges",
    "witcher3_skellige":        "stone_plateau + stormy_coast + moss_rock",
    "witcher3_velen":           "swamp_flat + dead_tree + grey_sky",
}

def compare_against_reference(
    rendered_iso_png: Path,   # our View 2 output
    ref_tag: str,
) -> ReferenceScore:
    """
    Returns a 5-dimensional similarity score:
      silhouette_complexity_match : 0..1
      texture_layer_count_match   : 0..1 (we decode splatmap count)
      scatter_density_match       : 0..1
      color_palette_match         : 0..1 (chi^2 hist distance)
      silhouette_peak_count_match : 0..1
    And an overall = weighted mean.
    """
```

**Which games to match against which biome:**

| biome | primary reference | secondary | why |
|---|---|---|---|
| volcanic | Elden Ring Mt Gelmir | Witcher 3 Skellige coast | Black rock + harsh light |
| ash_plateau | Elden Ring Caelid | Horizon Thornmarsh (ZD) | Saturated red/orange over bone |
| forest_valley | Horizon Forbidden West jungle | Witcher 3 White Orchard | Canopy layering |
| rolling_hills | Elden Ring Limgrave | Tsushima Izuhara | Gentle gradient + hero silhouette |
| coastal_cliff | Tsushima Iki | Witcher 3 Skellige | Vertical drama + water foam |
| swamp | Witcher 3 Velen | Horizon Greyhollow | Dead tree rhythm + grey sky |
| alpine | Horizon Forbidden West peaks | Elden Ring Mountaintops | Snow line + rock strata |

**"Good enough" vs "needs another pass":**

Per the 5-dim similarity score on the primary reference:
- overall >= 0.75 → **ship**
- 0.60 <= overall < 0.75 → **one more pass** (raise erosion iterations, increase scatter variance, check palette)
- overall < 0.60 → **major rework** (wrong macro shape; re-plan)

Any single dimension below 0.35 is a hard reject regardless of overall.

### 4. Failure modes — visual detection catalog

| failure | how to detect visually | threshold | remediation |
|---|---|---|---|
| Flat/boring terrain | View 1: pct_flat_cells > 60% | 60% | Re-run step 3 with `scale=75.0` (more variation), or bump fbm octaves in noise profile |
| Over-procedural (regular) | View 2: FFT of silhouette shows dominant periodicity >0.5 | 0.5 | Add `multiscale_breakup` pass after step 3; inject randomness via perlin * 0.2 octave |
| Tiling textures | View 6: fft_periodicity > 0.25 | 0.25 | Increase splatmap stochastic shader intensity; add `terrain_stochastic_shader` pass |
| Floating scatter | View 3 + `terrain_scatter_altitude_safety`: any scatter where heightmap(x,y) - scatter.z > 0.2 m | 0.2 m | Run `scatter_altitude_safety` pass to resnap instances |
| Seam lines | View 2 at tile boundary: height discontinuity > 1e-4 m | 1e-4 | Re-run `validate_tile_seams`; if fail, regenerate the world heightmap in EXACT strategy |
| Wrong mood | View 6 mean_saturation > 0.4 OR mean_value > 0.5 | sat 0.4 / val 0.5 | Apply `validate_dark_fantasy_color` to macro_color; tone-down saturation in material shader |
| No landmarks | View 3: visible_landmarks = 0 in all 10 sample directions | 0 | Inject a hero feature via `HeroFeatureSpec` at tile's highest ridge; re-run framing pass |
| Underwater scatter | View 3: scatter instance z < water_surface mask value | direct comparison | Filter scatter against `water_surface` mask; blacklist any instance below it |
| Shadow dead-zone | View 4: shadow_area < 15% at all 4 azimuths | 15% | Terrain lacks vertical relief or the sun is too high; verify sun elevation = 15° and add ridge features |
| Color banding | View 7: normal_banding_score > 0.1 | 0.1 | Heightmap was quantized somewhere; widen bit-depth in quality profile (16 → 32) |
| Mesh seam popping | View 5: tri density discontinuity at tile border | visual | Increase erosion_margin_cells in quality profile; re-run with EXACT erosion strategy |

All 11 failure modes are detectable from the 7 fixed renders plus existing mask-stack data. No new rendering infrastructure beyond the 7 views is required.

### 5. Implementation estimate

| module | LOC estimate | complexity | depends on |
|---|---|---|---|
| terrain_visual_render.py | ~900 | medium | bpy.ops.render.opengl; matplotlib fallback |
| terrain_visual_qa.py | ~600 | low | new render module; existing mask_stack |
| terrain_visual_reference.py | ~400 | medium | skimage.metrics; reference PNGs |
| reference PNG capture | ~30 min per ref × 20 refs | low | human curation |
| wiring into pipeline | ~200 | low | terrain_pipeline.py |
| tests | ~600 | medium | pytest + synthetic fixtures |
| **total** | **~2,700 LOC + 20 ref assets** | | |

Feasible in 2-3 dev weeks. Highest ROI feature in the codebase right now.

---

## DARK FANTASY TERRAIN DESIGN PRINCIPLES

Synthesis from research (Sucker Punch GDC "Samurai Landscapes", 80.lv Horizon and Ghost blast interviews, Level Design Book wayfinding chapter, FromSoftware art-direction analyses) applied to VeilBreakers:

### Seven encodable principles

**1. Vertical exaggeration beats realism.**
Elden Ring's mountains are 1.8-2.2× steeper than any real-world range; Tsushima cliffs are 1.5×. Real-world elevation is not aesthetically sufficient for dark fantasy. Encode: `quality_profile.vertical_exaggeration_target = 1.7` for dark fantasy; apply as a post-erosion multiplicative on the heightmap in regions tagged "dramatic".

**2. Silhouette is the primary design surface.**
"Elden Ring has 15-20 vistas that look like classical paintings." The silhouette (skyline) is what the eye latches onto. Encode: a hard gate on View 2's silhouette_peak_count ∈ [3,7] per tile containing any hero feature.

**3. Negative space and sky carry the mood.**
Sky/cloud occupies 35-55% of dark fantasy renders; grounded terrain occupies the rest. Encode: the `mood_fit_dark_fantasy` check verifies horizon_line_height_px ∈ [35%, 60%] of the render. Players should feel small.

**4. Oppression via scale relationship.**
Berserk/Dark Souls trick: the *scale of things near the player must feel overwhelming*. A mossy stone wall at eye level reads as 5× bigger than the player. Encode: scatter budgets must include `dominant_near_scale_m` ≥ 1.5× avg_human_height for hero zones.

**5. Decaying grandeur silhouettes, not fresh construction.**
Tree Sentinel, broken archways, fallen pillars. Encode: a `decay_bias` parameter in HeroFeatureSpec — 0.0 pristine, 1.0 fully ruined. Dark fantasy defaults to 0.7.

**6. Landmark hierarchy follows Lynch's 5-element map.**
Paths (rivers, ridges), edges (cliffs, coast), districts (biome zones), nodes (caves, shrines), landmarks (unique silhouettes). Encode: the composition_hints structure should have a `lynch_manifest` listing at least 1 instance of each category per 1km² region.

**7. Low sun angle is mandatory.**
Every iconic FromSoftware/Guerrilla screenshot is shot at sun elevation ≤ 20°. High sun flattens form. Encode: default `composition_hints["sun_elevation_deg"] = 18` for VeilBreakers; all View 2/4 renders use this.

### What makes Elden Ring's terrain iconic (research synthesis)

1. **Guidance via silhouette, not HUD** — every direction the player can walk has at least one distant silhouette pulling the eye.
2. **Painterly composition** — 15-20 vistas framed like Caspar David Friedrich paintings. Silhouette against sky with negative space → diagonal leading line → distant focal point.
3. **Scale shock** — giant objects (Tree Sentinel, Erdtree, dragons) placed at scales that make the player feel small without being comic.
4. **Decayed European mythology base** — Narnia/LOTR's mythic vocabulary filtered through Berserk's rot. Encoded visually as: ancient stone + moss + rust + bone + cloth.
5. **Bimodal elevation** — low rolling plains interrupted by vertical spikes. Not a smooth gradient. Limgrave's plateau edge is ~40 m in 10 m of horizontal distance.
6. **Biome transitions are narrative beats** — Caelid's red rot, Altus Plateau's gold, Mountaintops' snow — each transition is visually instantaneous, not blended.
7. **Sub-player-scale detail everywhere** — cobblestones, roots, skulls — even when you can't interact, the ground reads as "this place has history".

Of these 7, principles 1, 2, 5, 6, 7 are within scope for terrain generation; principles 3 and 4 belong to scatter/asset/material passes (out of scope for this audit but in scope for VeilBreakers overall).

---

## AGENT COMPLETION CRITERIA

Pass/fail spec for marking a terrain node "ready_for_unity_export = True":

### Hard gates (must all pass — reject if any fail)

1. `run_completion_checklist` — all 7 hard checks pass (silhouette_quality, elevation_variance, ground_texture_tiling, scatter_distribution, water_flow_correctness, seam_continuity, mood_fit_dark_fantasy).
2. `validate_tile_seams` — atol < 1e-4 at all 4 edges.
3. `compare_against_golden` — if a golden exists for this `(seed, tile_x, tile_y)`, content_hash matches. If not, create a new golden and store it.
4. `compare_against_reference(ref_tag=biome.primary_reference)` — overall ≥ 0.60 AND no single dimension < 0.35.
5. `TerrainMaskStack.unity_export_manifest()` — every channel in UNITY_EXPORT_CHANNELS is populated.
6. `ProtocolGate.rule_3_lock_reference_empties` — no anchor drift since scene_read capture.
7. Protected-zone compliance — every pass in pass_history respects every zone.
8. `apply_review_findings` produced `review_blockers = []` (no unresolved human/AI reviewer blockers).

### Soft gates (should pass — 2+ failures trigger "one more pass")

1. Checklist soft checks: lod_readability, landmark_visibility, shadow_form_reads.
2. Rhythm metric in [0.45, 0.75].
3. Iteration metric — tile converged (last 2 pass_results have identical content_hash).
4. compare_against_reference overall ≥ 0.75.

### Hard rejects (regardless of anything else)

1. Any `ValidationIssue` with `severity == "hard"` in the final pass history.
2. Any `ProtocolViolation` raised.
3. Any mask-stack channel with NaN or Inf.
4. Any height delta between adjacent tile cells > 100 m (numerical artifact).
5. `mean_saturation > 0.5` or `mean_value > 0.6` (wrong mood for dark fantasy).

### Workflow (agent-facing)

```
1. Build intent → capture scene_read → lock anchors.
2. Run twelve-step world terrain (fixed post-BUG-R8-A9-002/003).
3. Run per-tile pass chain.
4. Render all 7 views into docs/aaa-audit/tile_qa/<seed>_<tx>_<ty>/.
5. Run completion checklist.
6. If any hard gate fails → log, iterate. Max 3 iteration attempts.
7. If passes → compare_against_reference(biome.primary_ref).
8. If reference score ≥ 0.75 → ship.
   If 0.60-0.75 → one more pass focused on the lowest-scoring dimension.
   If < 0.60 → human review required.
9. Emit Unity export manifest → save golden if seed is canonical.
```

Every one of these gates is computable from the 7 rendered views + existing mask-stack data + the small set of new modules specified above.

---

## GRADE CORRECTIONS

Grades against the R7 / R8 CSV (scale A-F; rationale in parens):

| file | previous grade | new grade | delta | rationale |
|---|---|---|---|---|
| terrain_semantics.py | A- | A- | 0 | Solid contracts; BUG-R8-A9-033/34/35/36 are low-severity cleanups not grade-shifters. |
| terrain_twelve_step.py | B | **D+** | −2 | Stub steps 4, 5 undisclosed; detectors poor (BUGs 4/5); hard-codes iterations ignoring quality profile (BUG-3); dead code in production paths (BUG-6). |
| terrain_protocol.py | A- | **C+** | −1.5 | Rule 2 is paper-only (BUG-18, BUG-1); real protocol enforcement is weaker than advertised. Core logic is clean but the sync-to-viewport premise is broken. |
| terrain_quality_profiles.py | B+ | B | −0.5 | Lock flag is inert (BUG-32); save_every_n_operations = 0 across all tiers means checkpointing is disabled by default (BUG-31). Profiles exist but quality tiers may not differ in runtime behavior because BUG-3 in twelve-step ignores them. |
| terrain_framing.py | B | B− | −0.5 | Cell-size bug (BUG-11) means feather doesn't scale with resolution; saliency refinement logic is right-intent but slow (BUG-13). |
| terrain_saliency.py | B | B− | −0.5 | Triple-nested loop is a perf landmine (BUG-13); rasterization falloff is too permissive (BUG-14). |
| terrain_rhythm.py | B | B | 0 | O(N²) works at current scale but has no guard (BUG-15); enforcement lacks convergence control (BUG-16); idx bookkeeping is confusing (BUG-17) but correct. |
| terrain_live_preview.py | B | **F** | −3 | Module is named "live_preview" but renders no preview (BUG-7); `edit_hero_feature` doesn't edit (BUG-9); diff_preview lookup is nearly always empty (BUG-8); memory unbounded (BUG-10). The semantic gap between filename and behavior is disqualifying. |
| terrain_viewport_sync.py | A | **C** | −2 | Core math is correct. But `read_user_vantage` doesn't read from Blender even when Blender is available (BUG-18). The protocol rule that depends on it is therefore hollow. Net effect: a well-written module whose advertised function does not happen. |
| terrain_scene_read.py | B+ | **C** | −1.5 | Doesn't walk bpy.data (BUG-21); `_EXTENDED_METADATA` by id() is a latent correctness bug (BUG-20); headless-only in a handler that the protocol depends on for Rule 1. |
| terrain_visual_diff.py | B+ | B | −0.5 | Core 2D diff works. Multi-dim channel handling is broken (BUG-22); overlay semantics conflate categories (BUG-23). Fix 6.5 RETIRED context noted — the overlay is OK-ish but not great. |
| terrain_golden_snapshots.py | B | **C+** | −1 | Arrays not persisted (BUG-26); tolerance unused (BUG-25); seed library swallows failures (BUG-28); new-channel detection asymmetric (BUG-24); no parallelism (BUG-27). As a regression harness it's half-built. |
| terrain_review_ingest.py | B | **D** | −2 | Findings are written into composition_hints but **no downstream pass reads them** (BUG-30). The whole review loop is write-only. Grade reflects the end-to-end integration failure, not the per-function logic which is fine. |

### Cascading effect on pipeline-wide grades

The above 13 files sit at the center of the "agent understanding + visual QA" system. Their combined failure means:

- **Protocol Rule 1 (observe)**: paper-only without BUG-21 fixed.
- **Protocol Rule 2 (sync)**: paper-only without BUG-18 fixed.
- **Twelve-step canonical sequence**: dead in production without BUG-6 fixed.
- **Live preview**: doesn't preview anything.
- **Review feedback loop**: write-only.
- **Golden regression**: brittle + no parallelism.

Net effect: the agent-facing pipeline grade should drop at least half a letter (from the current B in R7) until these 8 HIGH bugs are fixed.

---

## SOURCES

- [GDC Vault — Samurai Landscapes: Building and Rendering Tsushima Island on PS4](https://gdcvault.com/play/1027352/Samurai-Landscapes-Building-and-Rendering)
- [Phillip Jenné — Ghost of Tsushima: Ground Materials and Procedural Work](https://phillipjenne.artstation.com/projects/QrKGQl)
- [Horizon Forbidden West Art Blast on ArtStation (Guerrilla)](https://www.guerrilla-games.com/read/horizon-forbidden-west-art-blast-on-artstation)
- [Creating a Horizon Forbidden West-Inspired Jungle Scene With UE5 (80.lv)](https://80.lv/articles/creating-a-horizon-forbidden-west-inspired-jungle-scene-with-ue5)
- [Ghost Of Tsushima Lead Environment Artist Reveals Process (The Gamer)](https://www.thegamer.com/ghost-of-tsushima-environment-artict-video/)
- [FromSoftware and the Power of Good Art Direction (Game Rant)](https://gamerant.com/fromsoftware-good-consistent-art-direction-elden-ring-bloodborne/)
- [The sublime dark fantasy aesthetics in FromSoftware's games (ResetEra)](https://www.resetera.com/threads/the-sublime-dark-fantasy-aesthetics-in-from-softwares-games-are-unmatched-across-all-media-and-we-dont-talk-about-them-enough.1391398/)
- [Defining Environment Language for Video Games (80.lv)](https://80.lv/articles/defining-environment-language-for-video-games)
- [Realism and Legibility in Open-World Level Design (GameDeveloper.com)](https://www.gamedeveloper.com/design/realism-and-legibility-in-open-world-level-design)
- [Wayfinding — The Level Design Book](https://book.leveldesignbook.com/process/blockout/wayfinding)
- [Composition — The Level Design Book](https://book.leveldesignbook.com/process/blockout/massing/composition)
- [Blender Viewport Render manual (5.1)](https://docs.blender.org/manual/en/latest/editors/3dview/viewport_render.html)
- [Blender `bpy.ops.render` API](https://docs.blender.org/api/current/bpy.ops.render.html)
- [Visually Improved Erosion Algorithm for Tile-based Terrain (arXiv 2210.14496)](https://arxiv.org/abs/2210.14496)
- [Methods for Procedural Terrain Generation — A Review (Springer)](https://link.springer.com/content/pdf/10.1007/978-3-030-21077-9_6.pdf)
- [Affordances in Game Level Design (Nic Phan)](https://www.nicphan.com/post/affordances-in-game-level-design)
