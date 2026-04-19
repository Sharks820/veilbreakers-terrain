# R8-A1: Core Pipeline & Wiring Deep Audit

Scope: 11 files / 3,332 lines of the Bundle-A orchestrator + protocol +
waterfalls + checkpoint plumbing. Every function read end-to-end.

Files audited:

| file | lines |
|---|---|
| terrain_pipeline.py | 472 |
| terrain_pass_dag.py | 199 |
| terrain_protocol.py | 239 |
| terrain_delta_integrator.py | 192 |
| terrain_master_registrar.py | 179 |
| terrain_hot_reload.py | 139 |
| terrain_waterfalls.py | 831 |
| terrain_waterfalls_volumetric.py | 368 |
| terrain_dirty_tracking.py | 161 |
| terrain_checkpoints.py | 374 |
| terrain_checkpoints_ext.py | 178 |

---

## NEW BUGS (not in FIXPLAN)

### BUG-R8-A1-001 | terrain_checkpoints_ext.py:87 | BLOCKER | `save_fn(pass_name)` invocation is missing required `result` arg

`save_every_n_operations` (L58–98) patches `controller.run_pass` to call
`controller._save_checkpoint(pass_name)` every Nth pass (L87). But
`TerrainPassController._save_checkpoint(self, pass_name: str, result: PassResult)`
(terrain_pipeline.py:327) REQUIRES `result` as second positional arg. The
call at L87 passes only one argument, so every invocation raises
`TypeError: _save_checkpoint() missing 1 required positional argument: 'result'`.

The L88–90 `except Exception: pass` silently swallows the failure.
Result: Bundle D's "save every N operations" autosave feature has
**never actually saved a checkpoint in production** — it's been throwing
and swallowing TypeError since shipped.

**Correct fix:** capture the PassResult returned by the wrapped `original`
call and pass it through, e.g.:

```python
pass_name = getattr(result, "pass_name", "autosave")
try:
    save_fn(pass_name, result)
except Exception:
    pass
```

Or better — call the module-level `save_checkpoint(controller, pass_name)`
(which is the correct public API that already handles absence of a
`PassResult`).

---

### BUG-R8-A1-002 | terrain_waterfalls.py:748 + 754 + register | CRITICAL | Double-carving of waterfall pools (fix 2.3 creates a new bug)

Waterfalls at L748 sets `waterfall_pool_delta` on the mask stack. L754
ADDITIONALLY applies the same delta directly to `stack.height`. The delta
integrator (terrain_delta_integrator.py:36 `_DELTA_CHANNELS`) reads
`waterfall_pool_delta` and ADDS IT TO `stack.height` AGAIN.

Net effect when both passes run: every waterfall pool is carved **twice**,
producing pits with 2x the intended depth. The `may_modify_geometry=True`
flag added by Fix 2.3's sibling change does not prevent this — it only
documents what the pass claims to do.

**Correct fix:** Remove the L752–754 in-place carve. Let the integrator
own all delta→height application. If waterfalls must "preview" the carved
terrain for downstream calculations within the same pass, capture a LOCAL
`h_after = stack.height + pool_delta` variable and compute foam/mist from
that, but do not mutate `stack.height`.

(Note: this bug is the *architectural* consequence of Fix 2.3's spot fix.
Fix 2.3 as written closes the stack-discipline bypass but opens this
double-apply bug. The FIXPLAN approach is incomplete — see
FIX-CORRECTION-001 below.)

---

### BUG-R8-A1-003 | terrain_pass_dag.py:68 | CRITICAL | "Last producer wins" breaks all `height`-dependent ordering

`PassDAG.__init__` (L65–68) overwrites `self._producers[ch]` on every
producer, so with multiple passes declaring `produces_channels=("height",...)`
— which are `macro_world` (pipeline L410), `integrate_deltas`
(delta_integrator.L179), plus the undeclared height modifiers `erosion`
and `waterfalls` — the DAG believes the SINGLE producer of `height` is
whichever was registered last.

In `register_all_terrain_passes`, Bundle A registers first (so erosion's
declared height=macro_world, then overwrites via macro_world, then … the
actual registered order is macro_world → structural_masks → erosion →
validation_minimal for Bundle A, then Bundle I-integrator last, so
`_producers["height"] = "integrate_deltas"`).

Consequence: `structural_masks.requires_channels=("height",)` → depends
on `integrate_deltas`. But `integrate_deltas` requires channels that
come from `structural_masks`/`erosion`/etc. → dependency loop in
INTENT but not in the DAG because `integrate_deltas` only declares
`requires_channels=("height",)` (its OWN output!), which is self-filtered
at pass_dag.py:94 (`producer != pass_name`). Net: all height-consumers
become dependents of `integrate_deltas`, which has NO upstream
dependencies, so it ends up in Wave 0 ALONGSIDE `macro_world`.

Running order in `parallel_waves()` will therefore be:
- Wave 0: macro_world, integrate_deltas  (← integrate_deltas runs BEFORE
  any delta-producer, finds no deltas, does nothing)
- Wave 1: structural_masks, erosion, waterfalls, caves, coastline, glacial,
  karst, wind_erosion, stratigraphy  (deltas are produced here)
- Wave 2+: validation passes

Since `integrate_deltas` already ran (Wave 0) and Wave-0 is its only
scheduled execution, the actual delta integration NEVER HAPPENS for
waterfalls, caves, coastline, etc. The deltas they produce are left
orphaned.

**Correct fix:** Either
(a) add explicit `depends_on` field to `PassDefinition` and populate
    `integrate_deltas.depends_on=("waterfalls","caves","coastline","glacial",
    "karst","wind_erosion","stratigraphy")`;
(b) declare `integrate_deltas.requires_channels` to INCLUDE each of the
    delta channels (`waterfall_pool_delta`, `cave_height_delta`, etc.) so
    the DAG's producer-overwrite lands on the right side; OR
(c) fix `_producers` to accumulate a LIST per channel and have
    `dependencies()` return the union — giving correct fan-in dependency
    tracking for the "multiple writers" case.

Option (b) is minimally invasive and already aligns with `_DELTA_CHANNELS`
at delta_integrator.py:36. Implementation:

```python
requires_channels=("height",) + _DELTA_CHANNELS,
```

This also forces the DAG to order integrate_deltas AFTER every delta
producer.

---

### BUG-R8-A1-004 | _terrain_erosion.py:338 + _terrain_world.py:~599 | CRITICAL | `pool_deepening_delta` is computed but never written to stack (dead delta)

`_terrain_erosion.py` computes `pool_deepening_delta` (L328) and returns
it inside the `HydroResult` dataclass (L338). `_terrain_world.pass_erosion`
(L593–599) writes height, erosion_amount, deposition_amount, wetness,
drainage, bank_instability, talus to the stack — but NEVER writes
`pool_deepening_delta`. The delta integrator (delta_integrator.py:40)
reads `stack.pool_deepening_delta`, which is always None → dropped.

Result: the pool-deepening feature is computed and discarded. One of the
8 channels the integrator promises to sum is phantom.

**Correct fix:** in `pass_erosion` add
`stack.set("pool_deepening_delta", hydro.pool_deepening_delta, "erosion")`
and add `"pool_deepening_delta"` to the erosion PassDefinition's
`produces_channels` tuple.

---

### BUG-R8-A1-005 | terrain_delta_integrator.py (no producer anywhere) | CRITICAL | `strat_erosion_delta` is declared in `_DELTA_CHANNELS` but NO PASS WRITES IT

`_DELTA_CHANNELS` at L39 lists `"strat_erosion_delta"`. `terrain_stratigraphy`
(searched full file) does not call `stack.set("strat_erosion_delta", ...)`
anywhere. The channel is defined on `TerrainMaskStack` (semantics.py:280,
378) but is only ever `None`.

Result: another phantom delta. The integrator's contract "sum all
stratigraphy erosion into height" is vaporware.

**Correct fix:** either
(a) have stratigraphy compute + write the delta (feature complete);
(b) remove `"strat_erosion_delta"` from `_DELTA_CHANNELS` and the
    mask-stack field list until it has a producer.

---

### BUG-R8-A1-006 | terrain_geology_validator.py:289 + 308 | CRITICAL | `glacial` and `coastline` PassDefinitions don't declare their delta channels in `produces_channels`

`register_bundle_i_passes` declares:
- `glacial.produces_channels=("snow_line_factor",)` — but glacial.py:243
  writes `stack.set("glacial_delta", ...)` UNDECLARED.
- `coastline.produces_channels=("tidal",)` — but coastline.py:699 writes
  `stack.set("coastline_delta", ...)` UNDECLARED (conditional on
  `apply_retreat`).

Result: PassDAG cannot discover these producers of the delta channels.
`integrate_deltas` never gets ordered after glacial/coastline by the DAG.
(This interacts with BUG-R8-A1-003 — it's one of the contributing
channel-producer wiring holes.)

**Correct fix:** add the channels to each PassDefinition:
```python
# glacial
produces_channels=("snow_line_factor", "glacial_delta"),
# coastline
produces_channels=("tidal", "coastline_delta"),
```

---

### BUG-R8-A1-007 | terrain_pipeline.py:454–465 + _terrain_world.py:593 | HIGH | `erosion` PassDefinition doesn't declare `height` in `produces_channels`

`register_default_passes` declares `erosion.produces_channels` without
`height`. But `pass_erosion` calls `stack.set("height", new_height,
"erosion")` at L593. Same failure class as waterfalls Fix 2.3.

Result: `_producers["height"]` does not include `erosion` in the DAG
producer map. DAG dependency resolution is wrong for every pass that
consumes the eroded height.

Also: erosion writes `ridge` (L537) but `ridge` is declared as produced
by `structural_masks`, not by erosion — same undeclared-write pattern.

**Correct fix:** add `"height"` (and `"ridge"` if erosion should own
the post-pass ridge recomputation) to `erosion.produces_channels`. If
`ridge` should only be written by structural_masks, remove the L537
`stack.set("ridge", ...)` in erosion.

---

### BUG-R8-A1-008 | terrain_waterfalls.py:730–746 | HIGH | Region-scope zeroes PRE-EXISTING data outside the region (comment lies)

```python
# 6. Region scope: zero outside the region (leave pre-existing values alone)
if region is not None:
    scoped = np.zeros_like(foam)
    scoped[r_slice, c_slice] = foam[r_slice, c_slice]
    foam = scoped
    # ... same for mist, lip_mask, wet_rock, pool_delta
```

The comment says "leave pre-existing values alone", but the code zeros the
ENTIRE output then copies only the in-region slice. Because `foam`/`mist`
etc. are written via `stack.set("foam", foam, ...)`, pre-existing values
on `stack.foam` outside the region are OVERWRITTEN to zero.

Compare to `pass_erosion` (terrain_world.py:556–561) which correctly
starts from `h_before.copy()` and only splices the in-region slice —
preserving pre-existing data outside the region.

**Correct fix:** seed `scoped` from the existing `stack.get(ch)` value
(or default zeros if channel was None), then splice:
```python
def _splice(channel: str, computed: np.ndarray) -> np.ndarray:
    existing = stack.get(channel)
    out = computed.copy() if existing is None else np.asarray(existing, dtype=computed.dtype).copy()
    out[r_slice, c_slice] = computed[r_slice, c_slice]
    return out
```

---

### BUG-R8-A1-009 | terrain_waterfalls.py:711–713 | HIGH | Overlapping plunge pools ADD instead of MIN, creating non-physical pits

```python
pool_delta = np.zeros(h_shape, dtype=np.float64)
for chain in chains:
    pool_delta += carve_impact_pool(stack, chain)
    pool_delta += build_outflow_channel(stack, chain)
```

Each `carve_impact_pool` returns negative values inside its radius.
Adding two overlapping pool deltas sums their depths — a cell under two
pools gets carved `-depth_A + -depth_B = -(depth_A + depth_B)` metres,
potentially 2x deeper than either pool alone. Physically nonsensical.

**Correct fix:** use `np.minimum` (most negative wins) so overlapping
pools produce the deepest of the two, not the sum:

```python
contribution = carve_impact_pool(stack, chain) + build_outflow_channel(stack, chain)
pool_delta = np.minimum(pool_delta, contribution)
```

Or composite pool and outflow independently with min semantics.

---

### BUG-R8-A1-010 | terrain_waterfalls.py:590–635 | HIGH | `validate_waterfall_volumetric` signature is unusable

```python
def validate_waterfall_volumetric(
    chain: WaterfallChain,
    profile: Optional[WaterfallVolumetricProfile] = None,
) -> List[ValidationIssue]:
    ...
    expected_verts = int(chain.total_drop_m * profile.min_verts_per_meter)
    if expected_verts < profile.min_verts_per_meter:
        issues.append(... WATERFALL_LOW_VERT_DENSITY ...)
```

L603 condition `expected_verts < profile.min_verts_per_meter` is only
true when `chain.total_drop_m < 1.0`. So the vertex-density check fires
for sub-meter waterfalls and NEVER for the 50m+ hero waterfalls the
spec is trying to protect against. Inverted logic.

Additionally, the function NEVER RECEIVES `vertex_count` — so it has no
way to compare actual mesh density against the minimum. It only has the
drop height. The sibling version in `terrain_waterfalls_volumetric.py:125`
correctly takes `vertex_count`, `drop_m`, `front_normals_cos`.

Result: this `validate_waterfall_volumetric` is dead code. No caller in
the production tree (only tests hit the OTHER function). It appears to
exist only for documentation.

**Correct fix:** Delete this function. Redirect all references to the
canonical `terrain_waterfalls_volumetric.validate_waterfall_volumetric`.
(See also BUG-R8-A1-012 on the name collision.)

---

### BUG-R8-A1-011 | terrain_waterfalls.py:98–110 + terrain_waterfalls_volumetric.py:30–52 | HIGH | Two distinct `WaterfallVolumetricProfile` classes with different fields

The class is dataclass-declared in BOTH files with DIFFERENT field names:

`terrain_waterfalls.py:98`:
```python
thickness_top_m: float = 0.3
thickness_bottom_m: float = 0.8
front_curvature_segments: int = 6
min_verts_per_meter: int = 48
taper_exponent: float = 1.4
spray_offset_m: float = 0.15
```

`terrain_waterfalls_volumetric.py:30`:
```python
vertex_density_per_meter: float = 48.0
front_curvature_radius_ratio: float = 0.15
min_non_coplanar_front_fraction: float = 0.30
```

Import path determines which class you get. Callers (tests, environment.py)
import from `terrain_waterfalls_volumetric`. The inner `terrain_waterfalls`
version is used only by the dead `validate_waterfall_volumetric` above.

**Correct fix:** Delete the class + the dead validator from
`terrain_waterfalls.py` (both reside in the 98–110 and 590–635 blocks).
The volumetric module owns the authoritative contract.

---

### BUG-R8-A1-012 | terrain_waterfalls.py:590 + terrain_waterfalls_volumetric.py:125 | HIGH | Name collision: `validate_waterfall_volumetric` defined in two modules with incompatible signatures

Related to BUG-R8-A1-010 and 011. Static analysis + editor jump-to-def
will go to the wrong function depending on import order.

**Correct fix:** same as BUG-R8-A1-011 — delete the waterfalls-module
version entirely.

---

### BUG-R8-A1-013 | terrain_delta_integrator.py:160 | MED | `max_delta` metric key stores the MIN value

```python
metrics={
    ...
    "max_delta": float(total_delta.min()),  # most negative = deepest carve
}
```

The comment acknowledges this, but callers reading `metrics["max_delta"]`
and using it as an absolute maximum will get a confused number. Either
rename the key to `max_negative_delta` / `deepest_carve_m` or store
`float(np.abs(total_delta).max())`.

**Correct fix:** rename the key to `deepest_carve_m` in both the metric
dict and any consumer.

---

### BUG-R8-A1-014 | terrain_delta_integrator.py:101–104 + 130–142 | MED | `delta_channels_applied` is collected BEFORE protected-zone and region masking; metrics overstate real effect

```python
for name, arr in deltas:
    total_delta += arr
    applied_names.append(name)  # <-- names recorded unconditionally
# ...
total_delta = np.where(prot_bool, 0.0, total_delta)  # may zero everything
# ...
total_delta = np.where(mask, total_delta, 0.0)       # region gate
```

If a delta channel's entire support falls in a protected zone or outside
the region, its contribution becomes zero but its name still appears in
`metrics["delta_channels_applied"]`. Diagnostic noise.

**Correct fix:** compute per-channel contribution after masking, and only
record names with nonzero remaining contribution. Or store both
`channels_declared` and `channels_contributing_after_mask`.

---

### BUG-R8-A1-015 | terrain_pipeline.py:167–173, 334–340, terrain_checkpoints.py:334–340 | MED | `force: bool = False` kwarg on `run_pass` is never read; propagates through autosave wrappers as dead code

`run_pass(pass_name, region=None, *, force=False, checkpoint=True)` at
terrain_pipeline.py:167 — the function body NEVER references `force`.
The autosave wrapper at terrain_checkpoints.py:334 faithfully re-declares
and forwards it. Neither of them does anything with it.

Callers may pass `force=True` expecting some semantic (force a protected
zone override? force a re-run?) and silently get default behavior.

**Correct fix:** either implement `force` (likely: skip the
`enforce_protected_zones` gate when force=True) or delete the kwarg from
the signature everywhere (pipeline.py, checkpoints.py wrapper).

---

### BUG-R8-A1-016 | terrain_pipeline.py:243–253 + 279 | MED | `produces_channels` contract is only enforced when `status == "ok"`; passes returning `status="warning"` can silently omit promised channels

```python
missing_outputs = [...]
if missing_outputs and result.status == "ok":
    raise PassContractError(...)
```

A pass that returns `status="warning"` bypasses the "you promised to
populate X" check. Downstream code that depends on X (via `requires_channels`)
will crash in the next pass. The contract is "soft" exactly when it
shouldn't be — warnings are supposed to not block forward progress, but
skipping channel guarantees causes cascading failures.

**Correct fix:** enforce produces_channels for both "ok" AND "warning"
statuses; only skip for "failed".

---

### BUG-R8-A1-017 | terrain_semantics.py:463 + waterfalls.py:754 | MED | `stack.height =` direct assignment skips the `content_hash = None` cache invalidation (Fix 2.3 target already knows but propagation matters)

`stack.set()` invalidates `content_hash` (semantics.py:463). The direct
`stack.height = np.where(...)` at waterfalls.py:754 does NOT. Anyone
reading `stack.content_hash` without calling `compute_hash()` first
(e.g., the `to_dict()` serializer at semantics.py:541 which does
`self.content_hash or self.compute_hash()`) sees a STALE pre-waterfalls
hash if the stack had a cached hash from an earlier `compute_hash()`.

This is a *consequence* of Fix 2.3's target, not Fix 2.3 itself.

**Correct fix:** when Fix 2.3 converts the line to `stack.set("height",
..., "waterfalls")`, this bug disappears as a side effect. But flag it
here so the fix is verified to close the cache gap, not just the
provenance gap.

---

### BUG-R8-A1-018 | terrain_protocol.py:167–169 | LOW | `rule_7_plugin_usage` raises `AddonVersionMismatch` not `ProtocolViolation`

```python
@staticmethod
def rule_7_plugin_usage(params: Optional[dict] = None) -> None:
    from .terrain_addon_health import assert_addon_version_matches
    assert_addon_version_matches(TERRAIN_ADDON_MIN_VERSION)
```

`assert_addon_version_matches` raises `AddonVersionMismatch(RuntimeError)`.
The module docstring says "Any gate failure raises ``ProtocolViolation``".
Contract lies. Callers catching `ProtocolViolation` will miss rule-7
failures (they get a subtly different exception type).

**Correct fix:** wrap with `try/except AddonVersionMismatch as exc:
raise ProtocolViolation(str(exc)) from exc`.

---

### BUG-R8-A1-019 | terrain_hot_reload.py:20–29 | BLOCKER (duplicate of Fix 1.3) | Hardcoded `blender_addon.handlers.*` prefix breaks outside test mode

Already in FIXPLAN as Fix 1.3. Re-surfaced for context — this module is
entirely non-functional outside tests because the module names it tries
to reload don't exist under that package path in Blender runtime.

---

### BUG-R8-A1-020 | terrain_waterfalls.py:770–776 vs 754 | HIGH | `PassResult.produced_channels` lists 5 channels; pass ACTUALLY modifies 6 (missing `height`)

```python
produced_channels=(
    "waterfall_lip_candidate",
    "waterfall_pool_delta",
    "foam",
    "mist",
    "wet_rock",
),
```

L754 modifies `stack.height` but `height` is not in the tuple. This is
the `PassResult` declaration (runtime, per-call) — separate from the
`PassDefinition.produces_channels` static declaration. Both lie.

**Correct fix:** After BUG-R8-A1-002 is addressed (removing the direct
height carve), this is automatically resolved. If instead waterfalls is
deliberately kept as a height-modifier, then add `"height"` to both
the static PassDefinition and the dynamic PassResult tuples.

---

### BUG-R8-A1-021 | terrain_caves.py:899 + terrain_waterfalls.py:808 | HIGH | `wet_rock` is declared by BOTH `caves` and `waterfalls` — channel-ownership ambiguity

Both PassDefinitions claim to produce `wet_rock`. In the DAG producer
map, "last registered wins" → `caves` owns `wet_rock` → `waterfalls`
becomes NOT a producer of `wet_rock` in the DAG even though it writes
it. Any pass that requires `wet_rock` will depend on `caves` not
`waterfalls`.

Also, linear pipeline order: whoever runs last overwrites the previous
— so if caves runs after waterfalls, it REPLACES waterfalls' contribution
to `wet_rock` instead of merging.

**Correct fix:** Pick one owner. Likely option: introduce separate
channels `wet_rock_waterfall` and `wet_rock_cave`, then have a later
compositing pass merge them into `wet_rock` via `np.maximum`. OR,
inside each pass, READ the existing `stack.wet_rock` and merge new
values via `np.maximum` before calling `stack.set`.

---

### BUG-R8-A1-022 | terrain_checkpoints.py:162–268 | MED | `_intent_to_dict` / `_intent_from_dict` silently drop `water_system_spec`

`TerrainIntentState` (semantics.py:783) has a `water_system_spec:
Optional[WaterSystemSpec] = None` field. `_intent_to_dict` at
checkpoints.py:162 does not serialize it; `_intent_from_dict` at L214
does not deserialize it. Any preset saved with a water spec LOSES it
on reload.

**Correct fix:** add serialization for `water_system_spec` (requires
round-tripping the `WaterSystemSpec` dataclass as a nested dict).

---

### BUG-R8-A1-023 | terrain_pipeline.py:226–228 | LOW | Failed-pass record_pass still raises — caller can't decide to recover

```python
except Exception as exc:
    result = PassResult(pass_name=pass_name, status="failed", ...)
    self.state.record_pass(result)
    raise
```

The pass is recorded as failed AND the exception is re-raised. That's OK
for most cases, but `run_pipeline` at L318–322 `break`s on failure, which
leaves the controller in a state where `state.pass_history` has the
failed entry but `state.checkpoints` does NOT have a rollback point for
before the failure. Combined with autosave_after_pass (checkpoints.py:344)
which only saves on `status=="ok"`, the recovery story is: "your pipeline
is in the middle of an exception with no checkpoint to restore from".

**Correct fix:** emit a recovery checkpoint BEFORE invoking `definition.func`
(i.e., checkpoint the PRE-pass state, not the post-pass state), so a
failure can be rolled back to the checkpoint of the previous successful
pass. Requires a `checkpoint_dir` + an extra write per pass.

---

### BUG-R8-A1-024 | terrain_pass_dag.py:156–193 | MED | Single-pass wave branch runs on shared controller; multi-pass wave on workers — asymmetric checkpoint semantics

For `len(wave) == 1`, L158 calls `controller.run_pass(wave[0], checkpoint=checkpoint)`
which triggers `_save_checkpoint` via the run_pass internal path (pipeline.py:289).
For `len(wave) > 1`, L188–190 calls `controller._save_checkpoint(pname,
merged)` EXPLICITLY for each pass.

The two branches thus produce different checkpoint metadata paths
(different `parent_checkpoint_id` propagation — since for multi-pass
waves all pre-wave checkpoints have the same parent, they form a
"star" rather than a "chain"). `rollback_to()` by id still works,
but `rollback_to_last_checkpoint()` behavior diverges between
serial and parallel runs.

**Correct fix:** document the checkpoint-graph semantics (OK) or change
multi-pass-wave branch to checkpoint only the FINAL merged state of the
wave (simplest; loses per-pass granularity but removes the asymmetry).

---

### BUG-R8-A1-025 | terrain_pipeline.py:310–316 | MED | Default `pass_sequence` is hardcoded to 4 passes and silently misses everything else

```python
if pass_sequence is None:
    pass_sequence = [
        "macro_world",
        "structural_masks",
        "erosion",
        "validation_minimal",
    ]
```

Callers running `run_pipeline()` with no sequence argument get ONLY
Bundle A. Waterfalls, caves, coastline, glacial, karst, wind_erosion,
stratigraphy, integrate_deltas — all skipped. The `register_all_terrain_passes()`
side of the house registers 16 bundles, but run_pipeline() doesn't exercise
them. Functionality invisible to defaults.

**Correct fix:** either (a) remove the hardcoded default (force caller to
supply one), or (b) build the default from `PassDAG.from_registry().topological_order()`
at call time so every registered pass runs in a valid order.

---

### BUG-R8-A1-026 | terrain_waterfalls.py:262 | LOW | D8-neighbor deduplication includes the center (0,0), which is a tautology

```python
if any((r + dr, c + dc) in claimed for dr, dc in _D8_OFFSETS + ((0, 0),)):
    continue
```

`((0, 0),)` is included in the iterable. Since `(r, c)` is added to
`claimed` only after the check, this is technically safe, but the
logical intent is "if any of my 8 neighbors OR myself is claimed, skip".
The `(0, 0)` pair catches "I'm already claimed", which can only happen
if two LipCandidates share identical `grid_rc` — possible if
`detect_waterfall_lip_candidates` finds duplicates, which it doesn't
(one pass over (r, c)).

Harmless but confusing. Removing `((0, 0),)` clarifies intent.

---

## WIRING GAPS (not in FIXPLAN)

### GAP-R8-A1-001 | terrain_pipeline.py + terrain_dirty_tracking.py | DirtyTracker not integrated into run_pass

`DirtyTracker` exists (terrain_dirty_tracking.py:55), is attached via
`attach_dirty_tracker(state)` (L142), and is read by
`terrain_live_preview.py` (L16, L60, L85). But `TerrainPassController.run_pass`
does NOT automatically call `tracker.mark_dirty(ch, region)` for any
`definition.produces_channels` after a successful pass.

**Impact:** live preview / mask-cache invalidation can't rely on the
tracker alone — each pass must remember to mark its outputs dirty. None
of the registered passes does. The tracker is effectively empty at
all times outside manual-preview calls.

**Correct fix:** after L287 `self.state.record_pass(result)` (and before
checkpoint), add:

```python
tracker = getattr(self.state, "_dirty_tracker", None)
if tracker is not None:
    region_bbox = region if region is not None else self.state.intent.region_bounds
    tracker.mark_many(definition.produces_channels, region_bbox)
```

---

### GAP-R8-A1-002 | terrain_master_registrar.py:130–147 | No `"M"` bundle registered

Bundle M ("iteration velocity") comment at master_registrar.py:30 says
"no new passes" but the registrar silently omits bundle M. The
`loaded` list will never include "M", so consumers checking for its
presence assume it's missing/broken when it's just intentionally absent.

**Impact:** low but a minor transparency gap.

**Correct fix:** add a `("M", "", "")` entry or explicit log noting the
deliberate skip.

---

### GAP-R8-A1-003 | terrain_waterfalls.py:672 + terrain_waterfalls.py:684 | `derive_pass_seed` imported and called, return value stored in `_`

```python
derived_seed = derive_pass_seed(
    state.intent.seed, "waterfalls",
    stack.tile_x, stack.tile_y, region,
)
_ = np.random.default_rng(derived_seed)
```

L684 creates an `rng = np.random.default_rng(derived_seed)` but stores
it in `_`. The waterfalls pass never consumes a random sample. So the
derived seed is computed purely for the `metrics["seed_used"]` reporting
at L782 — no stochastic behavior is actually seeded.

**Impact:** if future edits add randomness to `pass_waterfalls`, authors
would assume the RNG is available and deterministic-per-tile. It's not.

**Correct fix:** either (a) remove the `_ = np.random.default_rng(...)`
line since it has no effect, or (b) rename to `rng` and actually use it
when sampling (e.g., for pool-radius jitter).

---

### GAP-R8-A1-004 | terrain_delta_integrator.py:176–185 | PassDefinition does NOT declare delta-source channels as required

```python
TerrainPassController.register_pass(
    PassDefinition(
        name="integrate_deltas",
        func=pass_integrate_deltas,
        requires_channels=("height",),
        produces_channels=("height",),
        ...
    )
)
```

`requires_channels=("height",)` — not `+_DELTA_CHANNELS`. Consequence:
the DAG does not order integrate_deltas AFTER any delta producer. This
is the root cause of BUG-R8-A1-003.

**Correct fix:** `requires_channels=("height",) + _DELTA_CHANNELS`.
But note that declaring required channels that are *optionally* populated
will cause `run_pass` to raise PassContractError if they're absent
(pipeline.py:200–204). Either:
(a) change the contract at pipeline.py:200 to treat delta channels as
    optional-when-absent (the integrator already tolerates None), or
(b) declare dependencies via a NEW `depends_on_passes` field on
    PassDefinition rather than inferring through channel producers.

---

### GAP-R8-A1-005 | terrain_checkpoints.py:320–361 | `autosave_after_pass` holds stale closure over `original` after disable+re-enable

```python
if enabled:
    ...
    original = controller.run_pass
    _ORIGINAL_RUN_PASS[key] = original
    def wrapped_run_pass(...):
        result = original(...)
```

If `autosave_after_pass(ctrl, enabled=True)`, then `autosave_after_pass(ctrl,
enabled=False)` restores original correctly, then `autosave_after_pass(ctrl,
enabled=True)` AGAIN, the new capture of `original = controller.run_pass`
is the CLASS method — OK. But if in the meantime `save_every_n_operations`
(checkpoints_ext.py) has also wrapped, the captures stack and
unwrapping order becomes brittle.

**Impact:** low — but both modules manage `run_pass` monkey-patching
without coordinating. Can lead to "I disabled autosave but it's still
saving" scenarios when both mechanisms interact.

**Correct fix:** funnel both autosave mechanisms through a single
run_pass decorator chain with a deterministic stack.

---

### GAP-R8-A1-006 | terrain_pipeline.py:456–465 | `validation_minimal` declares `produces_channels=()` — nothing to check

`produces_channels=()` means the post-run contract verification at
pipeline.py:244–253 is a no-op. If `pass_validation_minimal` is
supposed to produce validation issues on `result.issues` but never
updates channels, the contract check is vacuous. This is consistent
with being a read-only pass, but intent is unclear.

**Impact:** none if intentional — flag for clarity.

**Correct fix:** add a comment to `register_default_passes` explaining
that `validation_minimal` is intentionally side-effect-free at the
channel level.

---

### GAP-R8-A1-007 | terrain_protocol.py:86–103 | `rule_3_lock_reference_empties` raises if ANY anchor drifts, with no per-anchor tolerance override

The tolerance is a single float applied to every anchor type. A water-
surface anchor (which can legitimately move with tides) and a stone-
column anchor (which must not move at all) get the same tolerance.

**Impact:** false positives when hero features have different drift
budgets.

**Correct fix:** per-anchor `tolerance` field on TerrainAnchor (may
exist in semantics — worth checking).

---

### GAP-R8-A1-008 | terrain_pipeline.py:307 | `if intent is not None: self.state.intent = intent` replaces immutable intent mid-pipeline

`run_pipeline` takes an optional `intent`. If passed, `state.intent`
is replaced wholesale — which means pass_history, checkpoints etc. now
reference a DIFFERENT `intent_hash()`. Checkpoint validity contract
breaks silently (rollback after intent swap restores a mask_stack that
was generated under a different intent; downstream passes assume
intent_hash matches checkpoint.intent_hash, it doesn't).

**Impact:** checkpoints saved under intent A, restored under intent B,
won't report the mismatch anywhere — subtle determinism bug.

**Correct fix:** if intent is replaced, clear `state.checkpoints` or
record a "rebasing" marker so rollback knows which intent to honor.

---

## INCORRECT FIX APPROACHES (review FIXPLAN approach vs actual code)

### FIX-CORRECTION-001 | Fix 2.3 | Converting `stack.height = ...` to `stack.set("height", ...)` alone creates double-carving

Fix 2.3 plans to convert waterfalls.py:754 `stack.height = np.where(...)`
to `stack.set("height", ...)`, plus add `"height"` to
`produces_channels`. This closes the provenance/cache gap but LEAVES
the double-carving bug (BUG-R8-A1-002): waterfalls still writes
`waterfall_pool_delta` at L748 AND applies it to height at L754, then
the integrator applies it again.

**Correct approach:** Fix 2.3 must CHOOSE which pass owns the carve:
- Option A (recommended): waterfalls writes ONLY `waterfall_pool_delta`
  (remove L752–754 entirely). Integrator owns all height mutation.
  Requires BUG-R8-A1-003 and GAP-R8-A1-004 fixes so the DAG orders
  integrator after waterfalls.
- Option B: waterfalls writes ONLY `stack.height` and removes the
  `waterfall_pool_delta` channel entirely from `_DELTA_CHANNELS` and
  `_ARRAY_CHANNELS`. Loses the "integrator composes all deltas" story
  for waterfalls.

Option A is consistent with the rest of the delta architecture (caves,
glacial, karst, wind_erosion, coastline all use delta-only). The FIXPLAN
should reflect this.

---

### FIX-CORRECTION-002 | Fix 2.1 | Adding `register_integrator_pass()` call is necessary but insufficient

Fix 2.1 adds the missing `register_integrator_pass()` call into
`register_default_passes`. This closes the "integrator pass isn't
registered" hole.

But the integrator's PassDefinition at delta_integrator.py:176 declares
`requires_channels=("height",)` only. Post-Fix-2.1 the integrator IS
registered, but per BUG-R8-A1-003 + GAP-R8-A1-004 the DAG schedules it
in Wave 0 alongside macro_world, BEFORE any delta producer. Registering
the pass does not wire it up — the dependency declaration is the real
gap.

**Correct approach:** bundle Fix 2.1 with GAP-R8-A1-004 (declare
_DELTA_CHANNELS as required) AND a pass_dag change to tolerate optional
prereqs.

---

### FIX-CORRECTION-003 | Fix 2.4 | "Audit all `stack.attr =` direct assignments" scope is wider than documented

Prior audits (r7_phase_technical.md) concluded Fix 2.4 scope is 1 line
(waterfalls.py:754, same as Fix 2.3). I confirm that statement for
scalar ndarray channel assignment in the audited files.

However, this audit found that `_terrain_erosion.py` (via `pass_erosion`
delegation) and `terrain_waterfalls.py` are not the ONLY sites that
should concern Fix 2.4 — the UNDECLARED writes via `stack.set(...)` are
equally violating the "pass contract is the source of truth" rule.
Examples:

- `pass_erosion` writes `height` (line 593) AND `ridge` (line 537) both
  via `stack.set` — both UNDECLARED in PassDefinition.produces_channels
  (`ridge` is claimed by structural_masks, not erosion; `height` is not
  declared by erosion at all).
- `pass_coastline` writes `coastline_delta` (conditionally) via
  `stack.set` but does not declare it in produces_channels.
- `pass_glacial` writes `glacial_delta` via `stack.set` but does not
  declare it.

These are bugs of the same *class* (pass modifies mask stack in a way
its contract doesn't advertise) even though they don't use direct `.attr
=` assignment.

**Correct approach:** broaden Fix 2.4 to include a grep for `stack.set\(`
inside every registered pass function, cross-reference with that pass's
`produces_channels`, and fail-loud on any mismatch. See BUG-R8-A1-006,
007, 020 for specific instances.

---

### FIX-CORRECTION-004 | Fix 2.5 | `_merge_pass_outputs` channel guard should verify `produces_channels` actually exist on source_stack AND cover all channels that were mutated

The FIXPLAN Fix 2.5 says "add channel guard in `_merge_pass_outputs`".
Reviewing pass_dag.py:39–47:

```python
for channel in definition.produces_channels:
    if not hasattr(source_stack, channel):
        raise PassDAGError(...)
    setattr(target_stack, channel, copy.deepcopy(getattr(source_stack, channel)))
    ...
```

Current guard is "channel must exist as an attribute on source_stack".
Because `TerrainMaskStack` statically declares every channel in
`_ARRAY_CHANNELS`, `hasattr(source_stack, channel)` is always True for
any valid channel name AND for any bogus string like "height_typo"
(because attribute access on a missing field raises AttributeError,
which `hasattr` catches and returns False... actually only for truly
missing attributes). In practice this guard fires on typo-channels
(good) but DOES NOT catch the undeclared-mutation case (a pass mutated
some OTHER channel that's not in produces_channels).

**Correct approach:** Fix 2.5 should ALSO capture a content-hash of
source_stack BEFORE the pass runs (captured in `_runner`), compare
the hash AFTER the pass runs, and if any channel outside
`produces_channels` changed, raise PassDAGError. This needs capturing
pre/post hashes per channel, not just the aggregate hash.

Pragmatic option: restrict parallel execution to passes that truly only
write their declared channels, and warn on the rest — force them to run
serially.

---

## CONFIRMED CORRECT (things working as intended)

- `derive_pass_seed` (terrain_pipeline.py:55–79): SHA-256 over JSON,
  32-bit masked. Deterministic under PYTHONHASHSEED. Correct as written.
- `ProtocolGate.rule_1_observe_before_calculate` (protocol.py:44–66):
  scene-read freshness check with clock-skew tolerance. Solid.
- `ProtocolGate.rule_6_surface_vs_interior_classification` (protocol.py:145–162):
  validates `placement_class` against the frozenset. Correct.
- `enforce_protected_zones` (pipeline.py:134–163): the "fully-covers"
  logic is correct for its intent — only blocks when NO mutable cells
  remain, allowing partial-intersect passes to proceed and filter
  per-cell. Non-obvious but right.
- `PassDAG.topological_order` (pass_dag.py:98–118): Tarjan-style DFS
  with cycle detection. Correct.
- `_world_to_grid` / `_grid_to_world` / `_d8_to_angle` in waterfalls
  (L118–170): coordinate math is self-consistent with Z-up + origin-at-
  bottom convention. `atan2(dr, dc)` maps 0=east, +pi/2=north correctly.
- `WaterfallFunctionalObjects.as_list` (waterfalls_volumetric.py:78–87):
  returns the 7 canonical names in suffix order. Correct.
- `enforce_functional_object_naming` (waterfalls_volumetric.py:299–357):
  prefix check + suffix-set validation + missing-suffix reporting. Solid.
- `DirtyRegion.merge` (dirty_tracking.py:36–47): bounds min/max + union
  of channels. Correct set semantics.
- `DirtyTracker.coalesce` (dirty_tracking.py:127–134): fold-left merge.
  Correct.
- `save_checkpoint` / `list_checkpoints` / `rollback_to` in
  checkpoints.py: label registry keyed by `id(controller)`, proper
  parent_id chaining, JSON-serializable list output. Solid.
- `generate_checkpoint_filename` (checkpoints_ext.py:113–127): regex
  sanitization + 8-hex-char hash truncation. Correct.
- `enforce_retention_policy` (checkpoints_ext.py:135–166): mtime-sort +
  oldest-first deletion + OSError swallow. Correct.
- `master_registrar._safe_import_registrar` (master_registrar.py:47–64):
  try/except + logger.warning. Fix M5 correctly implemented.

---

## GRADE CORRECTIONS NEEDED

| Function | Current Grade | New Grade | Reason |
|---|---|---|---|
| `pass_integrate_deltas` (delta_integrator.py:66) | — | **C-** (down from whatever); depending on cover | Misleading `max_delta` metric; `delta_channels_applied` records pre-mask names; no guard on protected/region making it a no-op silently |
| `register_integrator_pass` (delta_integrator.py:170) | A | **C** | `requires_channels` does not name any delta; DAG scheduling is wrong post-registration |
| `pass_waterfalls` (waterfalls.py:659) | — | **D** | Double-carving bug + undeclared height mutation + region-scope data loss + overlapping pool addition instead of min |
| `validate_waterfall_volumetric` (waterfalls.py:590) | — | **F** (delete) | Inverted vert-density condition; missing vertex_count param; dead code; name-colliding with the real validator in waterfalls_volumetric.py |
| `WaterfallVolumetricProfile` (waterfalls.py:98) | — | **F** (delete) | Orphan duplicate class; all callers use the waterfalls_volumetric version |
| `register_default_passes` (terrain_pipeline.py:395) | — | **C+** | Hardcoded 4-pass default; erosion declares wrong produces_channels (missing `height`, writes `ridge` unowned); structural_masks declares `ridge` but erosion overwrites it |
| `run_pipeline` (terrain_pipeline.py:296) | — | **C** | Default `pass_sequence` is 4 Bundle-A passes — misses 12+ registered passes; intent-swap (L307) silently invalidates prior checkpoints |
| `save_every_n_operations` (checkpoints_ext.py:58) | — | **F** | Calls `_save_checkpoint(pass_name)` without required `result` arg — every Nth pass raises TypeError, swallowed silently |
| `PassDAG.__init__` (pass_dag.py:62) | — | **C-** | "last producer wins" overwrite breaks ordering when multiple passes produce the same channel (height, wet_rock, ridge) |
| `pass_erosion` (terrain_world.py:459) | — | **C** | Undeclared writes: `height`, `ridge`. Also: doesn't persist computed `pool_deepening_delta` — dead delta. |
| `_merge_pass_outputs` (pass_dag.py:25) | — | **C** | Channel guard is weak; doesn't detect undeclared mutations |
| `autosave_after_pass` (checkpoints.py:320) | — | **B-** | `force` kwarg forwarded uselessly; double-monkey-patch coordination with `save_every_n_operations` is fragile |
| `_intent_to_dict` / `_intent_from_dict` (checkpoints.py:162/214) | — | **C** | Silently drops `water_system_spec` field |
| `reload_biome_rules` / `HotReloadWatcher` (hot_reload.py) | — | **D** | Dead in production — hardcoded `blender_addon.handlers.*` prefix (Fix 1.3 target) |

---

## SUMMARY COUNTS

- NEW BUGS: 26 (1 BLOCKER, 2 CRITICAL, 12 HIGH, 8 MED, 3 LOW)
- WIRING GAPS: 8
- FIX CORRECTIONS: 4 (Fix 2.1, 2.3, 2.4, 2.5 all need scope adjustment)
- Grade corrections proposed: 14

**Highest-leverage fixes (in dependency order):**

1. BUG-R8-A1-003 + GAP-R8-A1-004 together — declare delta channels as
   required on integrate_deltas (unblocks correct DAG ordering).
2. BUG-R8-A1-002 — remove waterfalls direct height-carve (resolves
   double-carving after #1 lands).
3. BUG-R8-A1-004 + BUG-R8-A1-005 — wire up pool_deepening and
   strat_erosion deltas (or delete the phantom channels).
4. BUG-R8-A1-001 — fix `save_every_n_operations` argument count
   (Bundle D autosave has been silently non-functional).
5. BUG-R8-A1-006 + BUG-R8-A1-007 — declare delta channels in all
   Bundle I PassDefinitions and erosion PassDefinition.
6. BUG-R8-A1-008 — fix waterfalls region-scope data loss.
7. BUG-R8-A1-021 — resolve wet_rock ownership between caves and
   waterfalls.
