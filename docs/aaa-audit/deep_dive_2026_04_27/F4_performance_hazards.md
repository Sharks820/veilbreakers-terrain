# F4 Audit: Performance Hazards & Scalability (Handlers)

**Date:** 2026-04-27
**Auditor:** Claude (gsd-code-reviewer) — focus: Python-level hot loops, memory peaks, global state, hash hazards at AAA terrain sizes (2K-8K)
**Scope:** `veilbreakers_terrain/handlers/*.py` (134 files). Tests excluded.
**Reference baseline:** 4K = 4096×4096 = 16,777,216 cells. Pure-Python iteration costs ~150-400 ns/iter, so a full H×W Python loop at 4K = **2.5-6.7 seconds** before any work happens.

**Already-known issues (confirmed, not re-graded):**
- `_water_network_ext.py:768-778` — nested H×W stamping (P0, 8-12s @ 4K). **Confirmed.**
- `terrain_cliffs.py:2368` — `hash(cliff.cliff_id)` PYTHONHASHSEED hazard. **Confirmed.**

---

## CRITICAL FINDINGS (P0)

### [P0-1] `_water_network.py:1551-1574` — full-resolution Python Manning velocity loop

```python
for r in range(H):
    for c in range(W):
        acc = float(fa[r, c])
        if acc < 1.0:
            continue
        d = int(fd[r, c])
        if d < 0:
            continue

        w = compute_river_width(acc)
        dep = _compute_river_depth(acc)
        area = w * dep
        wetted_p = w + 2.0 * dep
        if wetted_p < 1e-9:
            continue
        R = area / wetted_p

        S = float(slope_clamped[r, c])
        n = manning_n_river if acc >= river_threshold else manning_n_stream
        V = (1.0 / n) * (R ** (2.0 / 3.0)) * math.sqrt(S)

        speed[r, c] = V
        vx[r, c] = V * _d8_dx[d]
        vy[r, c] = V * _d8_dy[d]
```

**Pattern:** Manning open-channel velocity computation iterates every cell in Python. Each iteration calls two helper functions (`compute_river_width`, `_compute_river_depth`) plus `math.sqrt`/`pow` in pure Python.

**Complexity:** O(H·W) Python iterations.
**Estimated wall time @ 4K:** 16.7M × ~600 ns = **~10 seconds** (helper-function-call dominated; same magnitude as the known `_water_network_ext.py:768-778` hazard).
**Fix:** Vectorise the entire Manning equation. `width = compute_river_width(fa)` already accepts arrays in most river-width formulas (Leopold & Maddock); inline as `width_arr = a * fa**b`. Replace the loop with:
```python
mask = (fa >= 1.0) & (fd >= 0)
w_arr = a_w * np.power(fa, b_w)
d_arr = a_d * np.power(fa, b_d)
area = w_arr * d_arr
P = w_arr + 2.0 * d_arr
R = np.where(P > 1e-9, area / P, 0.0)
n_arr = np.where(fa >= river_threshold, manning_n_river, manning_n_stream)
V = (1.0 / n_arr) * np.power(R, 2.0/3.0) * np.sqrt(slope_clamped)
speed = np.where(mask, V, speed)
vx = speed * _d8_dx[fd_clamped]
vy = speed * _d8_dy[fd_clamped]
```
Expected speedup: **>100×** (from ~10s to ~50ms).

---

### [P0-2] `terrain_navmesh_export.py:354-360` — Python triple loop building H×W vertex grid

```python
for r in range(rows):
    for c in range(cols):
        vert_idx[r, c] = len(vertices)
        wx = ox + c * cs
        wz = oy + r * cs
        wy = float(h[r, c])
        vertices.append([wx, wy, wz])
```

**Pattern:** Builds a Python list of `[wx, wy, wz]` lists for every heightmap cell, plus an integer index grid. Followed at line 367-385 by another `(rows-1) × (cols-1)` Python loop generating triangle indices, and lines 395-408 emit off-mesh edge transitions in two more H×W Python loops.

**Complexity:** O(H·W) with Python list-construction overhead per iter (~1-2 μs incl. list allocation, three float boxings, index assignment).
**Estimated wall time @ 4K:** 16.7M × ~1.5 μs = **~25 seconds** (vertex loop alone). Second pair adds ~15s. Total ≈ **40 seconds** for one navmesh export.
**Memory hazard:** The `vertices` Python list at 4K holds 16.7M × ~80B (list overhead + 3 floats) = **~1.3 GB** of Python objects. PyObject overhead for floats is the dominant cost.
**Fix:** Vectorise:
```python
cc, rr = np.meshgrid(np.arange(cols), np.arange(rows))
xs = ox + cc * cs
zs = oy + rr * cs
ys = h.astype(np.float64)
verts_arr = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)  # (N, 3) float64
# Convert to list only at the boundary if a list is required by callers.
vertices = verts_arr.tolist()
vert_idx = np.arange(rows * cols, dtype=np.int32).reshape(rows, cols)
```
Triangles can also be vectorised by generating corner index tables and selecting non-blocked quads with a boolean mask. Expected speedup: **20-50×**.

---

### [P0-3] `terrain_waterfalls.py:153-161` — Python H×W loop building per-vertex dict for water mesh

```python
for r in range(rows):
    for c in range(cols):
        x = world_origin_x + c * cell_size
        y = world_origin_y + r * cell_size
        z = float(height[r, c]) + _MIN_WATER_ELEVATION_M
        vertices.append({
            "position": [x, y, z],
            "foam_alpha": float(foam_alpha_grid[r, c]),
        })
```

**Pattern:** Builds a Python list of dicts at every cell — but one **dict per cell**, each containing a position list. Worst possible Python-object density.

**Complexity:** O(H·W) Python iterations.
**Estimated wall time @ 4K:** 16.7M × ~3 μs (dict alloc + list alloc + 4 float boxings) = **~50 seconds**.
**Memory @ 4K:** ~16.7M dicts × ~232B (dict + nested list) = **~3.9 GB** Python heap.
**Fix:** Most callers only need positions and a foam scalar; return as two parallel ndarrays `(N, 3)` and `(N,)` instead of dicts. If a dict-per-vertex is truly required by export callers, build it lazily / streamed during the export rather than materialising the full list. Expected speedup: **50-100×** with dict elimination.

---

### [P0-4] `terrain_chunking.py:336-353` — per-chunk Python row-by-row heightmap copy into list-of-lists

```python
for gy in range(grid_rows):
    for gx in range(grid_cols):
        ...
        sub_heightmap: list[list[float]] = []
        for r in range(r_start, r_end):
            sub_heightmap.append(list(heightmap[r][c_start:c_end]))
```

**Pattern:** For each chunk in an `(grid_rows × grid_cols)` partition, copies the heightmap rows into a fresh Python list of lists. With chunk_size=256 at 4K, that's 16×16 = 256 chunks × ~256 rows × ~256 floats = ~16.7M Python float boxings, **plus the entire dataset is duplicated** into Python objects (each cell now lives both in the source ndarray and as a PyFloat).

**Complexity:** O(H·W) cumulative Python iterations across all chunks (since the chunks tile the heightmap).
**Estimated wall time @ 4K:** 16.7M × ~400 ns = **~7 seconds** (boxing-dominated). Memory: **~1.3 GB** of duplicated PyFloat objects on top of the original 64 MB ndarray.
**Fix:** Keep the chunk as a numpy view (`heightmap[r_start:r_end, c_start:c_end]`) and only convert to list-of-lists at the export boundary if downstream consumers truly need it. Most consumers in this codebase already accept ndarrays.

---

### [P0-5] `terrain_semantics.py:971-1019` — `compute_hash` runs SHA-256 over every populated channel, twice per pass

```python
for name in self._ARRAY_CHANNELS:
    val = getattr(self, name, None)
    if val is None:
        continue
    arr = np.ascontiguousarray(val)
    hasher.update(name.encode("utf-8"))
    hasher.update(str(arr.dtype).encode("utf-8"))
    hasher.update(repr(arr.shape).encode("utf-8"))
    hasher.update(arr.tobytes())
```

Combined with `terrain_pipeline.py:407` which calls it before *every* pass (and again indirectly via PassResult.content_hash_after when set), and `_ARRAY_CHANNELS` covers ~30 channels:

**Pattern:** `arr.tobytes()` materialises the entire ndarray as a Python `bytes` object, then SHA-256 hashes it. At 4K with 30 populated float32 channels, each channel is 64 MB. Total bytes hashed per call: ~**1.9 GB**.

**Complexity:** O(N · K) where N = H·W and K = number of populated channels.
**Estimated wall time @ 4K per `compute_hash`:** SHA-256 runs at ~500 MB/s in CPython → **~4 seconds per call**. `arr.tobytes()` allocates a fresh bytes copy each time, so additional ~30 × 64 MB = 1.9 GB of transient allocations per call. With ~40 passes × 1 hash before each = **~160 seconds wasted on hashing alone**, plus ~80 GB of cumulative bytes allocations.
**Fix:** (a) Hash channels incrementally using `hasher.update(arr.data)` with memoryview to avoid the `tobytes()` copy; (b) cache the channel-hash by content version so unchanged channels are not re-hashed; (c) skip the pre-pass hash when `force=False` and no caller actually consumes `content_hash_before` (it is currently always recorded on PassResult but rarely read). Expected: from ~4s/call to ~50ms/call.

---

## HIGH FINDINGS (P1)

### [P1-1] `terrain_advanced.py:996` — full-heightmap Gaussian filter inside per-brush function

```python
elif operation == "smooth":
    try:
        from scipy.ndimage import gaussian_filter as _gf
        blurred = _gf(layer.heights, sigma=1.0)[r0:r1, c0:c1]
```

**Pattern:** `apply_brush()` is called once per brush stroke. The "smooth" path runs Gaussian blur over the **entire** heightmap and then slices to the small brush rect. If a sculpting session runs N strokes, this is N full-heightmap convolutions instead of N tiny ones.

**Complexity:** O(N · H · W) per session, where it could be O(N · brush_area).
**Estimated wall time @ 4K:** Each `gaussian_filter` over 4K float32 ≈ 350-500 ms. 100 strokes = 35-50 seconds wasted.
**Fix:** Pass an enlarged slice (rect + padding equal to `3·sigma`) to `gaussian_filter`:
```python
pad = max(3, int(math.ceil(sigma * 3.0)))
sr0, sr1 = max(0, r0 - pad), min(rows, r1 + pad)
sc0, sc1 = max(0, c0 - pad), min(cols, c1 + pad)
blurred_roi = _gf(layer.heights[sr0:sr1, sc0:sc1], sigma=1.0)
blurred = blurred_roi[r0 - sr0:r1 - sr0, c0 - sc0:c1 - sc0]
```
Expected: **100-500×** speedup per stroke for typical brush sizes <128.

---

### [P1-2] `procedural_grass.py:545-560` — per-instance Python record building loop

```python
for i in range(positions.shape[0]):
    if biome_vals is not None:
        biome_name = _biome_id_to_name(int(biome_vals[i]), self.biome_id_map) or "unknown"
    else:
        biome_name = species.biomes[0] if species.biomes and species.biomes[0] != "*" else "unknown"
    records.append(
        GrassPlacementRecord(
            species=species.name,
            position_world=(float(wx[i]), float(wy[i]), float(wz[i])),
            ...
```

**Pattern:** Per-grass-instance dataclass construction in Python. AAA grass density: 4 instances/m² × 4096² m = **67 million instances per terrain**. Each iteration constructs a frozen dataclass + calls `_biome_id_to_name` (dict lookup) + 8 float boxings.

**Complexity:** O(N_instances) Python.
**Estimated wall time @ 4K + 4 inst/m²:** 67M × ~2 μs = **~135 seconds** per grass species. With ~6 species = ~14 minutes per terrain on grass placement alone.
**Memory:** 67M GrassPlacementRecord instances ≈ **~13 GB** Python heap.
**Fix:** Hold placements as columnar ndarrays (`positions: (N,3) float32`, `rotations: (N,) float32`, etc.) and only materialise dataclasses lazily on iteration / serialise via numpy's `npz` save. The biome-name field can be replaced by a `biome_id` int and resolved at write time. Expected: **>50×** speedup, **>10×** memory reduction.

---

### [P1-3] `terrain_checkpoints.py:50-55` — module-level mutable dicts keyed by `id(controller)` with no cleanup

```python
_LABEL_REGISTRY: Dict[int, Dict[str, str]] = {}
_AUTOSAVE_CONTROLLERS: Dict[int, bool] = {}
_ORIGINAL_RUN_PASS: Dict[int, Callable[..., PassResult]] = {}
```

`save_checkpoint` (line 163) does `_LABEL_REGISTRY.setdefault(id(controller), {})[label] = checkpoint_id` — entries are **never removed** when controllers are garbage-collected. The `id()` key is recycled by CPython after GC, so a long-running session that creates many controllers will (a) leak memory, and (b) eventually return stale labels for a new controller that happens to reuse a previous id().

**Severity:** Memory leak + correctness hazard.
**Fix:** Use `weakref.WeakValueDictionary` (or `WeakKeyDictionary` keyed by the controller object) so entries are GC'd with their controller. Add an explicit `clear_label_registry(controller)` exit point on controller teardown.

---

### [P1-4] `environment_scatter.py:3161, 3261` — two full `bpy.data.objects` scans inside scatter scoring path

```python
for _obj in bpy.data.objects:
    if _obj.type == "EMPTY" and _obj.children:
        ...
```
and again at line 3261 — both occur inside `apply_scatter_scoring` (or sibling) whose intent is one terrain pass. Two full-scene scans per pass; each `bpy.data.objects` access traverses the Blender RNA collection (one `bpy.data.objects[i]` lookup ≈ 1-3 μs RNA bridge cost).

**Estimated cost:** With a populated scene of 5,000+ objects (typical for a forest tile), each loop = 5-15 ms × 2 = ~30 ms per scatter pass. Across many passes / many tiles, this adds up.
**Severity:** Moderate (sub-second per call, but called on every scatter pass; and the two scans construct the same exclusion zone set with slight variations — code duplication risk).
**Fix:** Cache the exclusion-zone list on `state` once per tile. The two loops should be merged into one pass that produces both building and road exclusion zones.

---

### [P1-5] `terrain_waterfalls.py:2308 / 2312-2323` — full-resolution velocity field allocated, then `np.where` merged inside per-chain loop

```python
vel_field = np.zeros((*h_shape, 2), dtype=np.float32)
...
for chain in chains:
    chain_vel = generate_velocity_field(chain, _preview_stack)
    chain_vel = blend_velocity_to_water_body(chain_vel, ...)
    existing_speed = np.sqrt(np.sum(vel_field ** 2, axis=-1))
    chain_speed   = np.sqrt(np.sum(chain_vel ** 2, axis=-1))
    stronger_mask = chain_speed > existing_speed
    vel_field[stronger_mask] = chain_vel[stronger_mask]
```

**Pattern:** `vel_field` is `(H, W, 2)` = 128 MB at 4K. Each chain calls `generate_velocity_field` which allocates **another** full-res `(H, W, 2)` array. Inside the loop, `existing_speed` and `chain_speed` each allocate a full-res `(H, W)` float64 (256 MB each). `chain_vel ** 2` is another 128 MB. Total transient peak per chain ≈ **~1 GB**.
**Complexity:** O(C · H · W) memory peaks where C = number of waterfall chains (often 5-20).
**Estimated wall time @ 4K per chain:** Three full sqrt/sum operations + boolean indexing assignment ≈ 600-900 ms per chain. With 10 chains = **~8 seconds**.
**Fix:** Compute `existing_speed_sq = vel_field[...,0]**2 + vel_field[...,1]**2` once before the loop and update incrementally. Use float32 throughout (chain_speed is computed in float64 by default because of `**2` promotion in some numpy versions). Mask-blit using `np.copyto(vel_field, chain_vel, where=mask[..., None])` to avoid intermediate allocations.

---

### [P1-6] `terrain_semantics.py:1597-1598` — `pass_history` is unbounded

```python
def record_pass(self, result: PassResult) -> None:
    self.pass_history.append(result)
```

Combined with `terrain_iteration_metrics.py:120-121` which appends to `self.pass_names` and `self.durations_s` on every record. In a long-running multi-tile build (e.g. an 8×8 grid of 4K tiles = 64 tiles × ~40 passes = 2,560 entries) this is small in absolute terms, but the `PassResult` itself sometimes captures `metrics` dicts that include sample arrays — see e.g. `_water_network_ext.py` storing diagnostic arrays in `metrics`. Verify metrics are scalar-only.

**Severity:** Currently low, but hazardous if anyone adds an array to `metrics`. Cap at 10K entries with a deque, or clear after serialisation.

---

### [P1-7] `terrain_shadow_clipmap_bake.py:317-320` — string concatenation in scanline write loop

```python
scanlines = b""
for y in range(rows):
    row_bytes = arr_f32[y].tobytes()
    scanlines += struct.pack("<i", y) + struct.pack("<i", len(row_bytes)) + row_bytes
```

**Pattern:** Repeated `bytes` concatenation `scanlines += ...` triggers a fresh allocation each iteration (CPython's bytes immutability → O(N²) memory copies despite the optimisation).
**Complexity:** O(rows²) memory copies in the worst case, O(rows × scanline_size) at best.
**Estimated wall time @ 4K (rows=4096, scanline ≈ 16 KB):** ~4096 reallocations of growing buffers, total bytes copied ≈ rows² · scanline / 2 ≈ **~140 GB of memcpy**. Wall time: **5-15 seconds**.
**Fix:** Use a pre-allocated `bytearray(header_offset + offset_table_size + rows * scanline_block_size)` and write each scanline at a known offset, or build a `list[bytes]` and `b"".join(parts)` at the end.

---

## MEDIUM FINDINGS (P2)

### [P2-1] `terrain_dem_import.py:163-180` — O(max(H,W) · H · W) Python nodata-fill loop

```python
max_iters = max(arr.shape)  # worst case: a single valid pixel
for _ in range(max_iters):
    if not remaining.any():
        break
    padded = np.pad(out, 1, mode="edge")
    padded_mask = np.pad(remaining.astype(np.float32), 1, mode="constant", constant_values=1.0)
    windows = sliding_window_view(padded, (3, 3))
    valid_w = sliding_window_view(1.0 - padded_mask, (3, 3))
    h, w = arr.shape
    for r in range(h):
        for c in range(w):
            if not remaining[r, c]:
                continue
            nbr_vals = windows[r, c].ravel()
            nbr_valid = valid_w[r, c].ravel().astype(bool)
            if nbr_valid.any():
                out[r, c] = nbr_vals[nbr_valid].mean()
                remaining[r, c] = False
```

**Pattern:** Outer loop runs up to `max(H, W)` iterations. Inner loop iterates **every cell** in Python on every outer iter. At 4K with significant nodata regions: outer ~100 iters × 16.7M Python iters = **1.67 billion** Python iterations.
**Complexity:** O(K · H · W) where K can equal max(H,W).
**Estimated wall time @ 4K with 50% nodata:** **5-15 minutes** in the fallback (scipy path is fast). The `_HAS_SCIPY` import gate at line 64 protects the common path, but if scipy is missing for any reason (CI without scipy, isolated venv) this becomes a multi-minute wait.
**Fix:** Replace the fallback with a numpy-only multi-pass dilation that vectorises the inner loop (compute mean of valid neighbours via shift+sum without per-cell Python).

---

### [P2-2] `procedural_grass.py:64-86` — pure-Python distance-transform two-pass

```python
for r in range(h):
    for c in range(w):
        if dist[r, c] == 0:
            continue
        best = dist[r, c]
        if r > 0:
            best = min(best, dist[r - 1, c] + 1)
        if c > 0:
            best = min(best, dist[r, c - 1] + 1)
        dist[r, c] = best
# ... + reverse pass
```

Same pattern in: `terrain_audio_zones.py:325-384` (chamfer DT on `cliff_mask`), `terrain_navmesh_export.py:194-223` (8-conn chamfer fallback), `terrain_gameplay_zones.py:184-222`, `terrain_wildlife_zones.py:130-160`, `terrain_math.py:80-120`, `_biome_grammar.py:511-543`.

**Complexity:** O(H·W) Python.
**Estimated wall time @ 4K:** **8-15 seconds per call** in the fallback path. Common path (scipy) is fast. **Risk:** these are EDT fallbacks that fire when scipy is missing or the import fails on a Blender python without scipy.
**Fix:** Either remove the fallbacks (declare scipy a hard dep — already is via `requirements.txt`), OR replace each with the same vectorised forward/backward chamfer pattern used in `terrain_audio_zones.py:336-383` (which is pure-numpy with a tight inner Python col loop only — **note that even this version still has an inner `for c in range(W)` loop at lines 355-358 and 378-381 which dominates at 4K**).

---

### [P2-3] `terrain_destructibility_patches.py:122-150` — fallback grid scan with per-block `bincount`

```python
for r0 in range(0, h_arr, cell):
    for c0 in range(0, w_arr, cell):
        ...
        block = stack.biome_id[r0:r1, c0:c1].ravel().astype(np.int64)
        counts = np.bincount(block - block.min(), minlength=1)
        material_id = int(block.min() + int(counts.argmax()))
        ...
        patches.append(DestructibilityPatch(...))
```

**Pattern:** Block-scan iterates `(H/cell)×(W/cell)` blocks. With cell=8 at 4K, that's 512×512 = **262K iterations**, each calling `.ravel().astype()`, `bincount`, `argmax`, `mean()` on a 64-element block. Each iteration ~30-80 μs → **~10-20 seconds**.
**Severity:** Moderate. Only fires on the scipy-missing fallback.
**Fix:** Vectorise the block-stats with `block_reduce` (skimage) or via reshape+axis-reductions on `(H/cell, cell, W/cell, cell)` → mean axes (1, 3).

---

### [P2-4] `_water_network.py:1077-1106` and `1129-1154` — Python border seeding + flood-fill BFS

```python
for r in range(rows):
    for c in (0, cols - 1):
        if not closed[r, c]:
            heapq.heappush(open_heap, (hmap[r, c], r, c))
            water_level[r, c] = hmap[r, c]
            closed[r, c] = True
```

The seeding is only border cells (O(H+W), small) — that's fine. **The hot path is the priority-flood `while open_heap:` loop at 1093 (and 1142+ for connected-component flood-fill)**: at 4K that's 16.7M `heapq.heappush`/`pop` calls in Python. Each `heapq.heappush` on a list of millions of tuples is ~1-2 μs.
**Estimated wall time @ 4K:** **20-40 seconds** for priority-flood. Same magnitude for the lake-CC flood-fill (uses `deque.popleft`, slightly faster but still pure Python).
**Severity:** This is a known classic algorithm with no easy numpy vectorisation (priority-flood is inherently sequential). Common workaround: implement in Cython / numba, or use `richdem` / `pyflwdir` (already mentioned in some comments). Flag as architectural ceiling — at 8K terrain this becomes ~2-3 minutes per priority-flood call.

---

### [P2-5] `terrain_advanced.py:1501-1506, 1508-...` — particle-erosion brush with Python particle loop

```python
for r in range(min_r, max_r):
    for c in range(min_c, max_c):
        ddx = (c - cx) / max(rx, 1e-6)
        ddy = (r - cy) / max(ry, 1e-6)
        if math.sqrt(ddx * ddx + ddy * ddy) <= 1.0:
            footprint[r, c] = True

for _p in range(n_particles):
    for _attempt in range(16):
        ...
    for _step in range(max_steps):
        ...
```

**Pattern:** This is `apply_brush(operation="erode_particle")`. Particle simulation is inherently sequential — but the **footprint-marking double loop at 1501-1506 is unnecessary**: the brush ellipse mask is already computed at line 976 as `in_brush = dist_box <= 1.0`. Just do `footprint[r0:r1, c0:c1] |= in_brush`.
**Severity:** Moderate. With `n_particles = max(50, iterations * 20)` and `max_steps = 64`, this is ~64K Python steps per brush stroke. At ~2 μs/step ≈ 130 ms per stroke. 1000 strokes = 2 minutes.
**Fix (footprint):** Replace 1501-1506 with the existing mask. **Fix (particles):** Vectorise N particles in parallel as ndarray (positions, velocities, sediment) updated each step — standard pattern in Houdini Heightfield Erode and `terrain-erosion-3-ways` reference implementations. Expected speedup: 20-50×.

---

### [P2-6] `terrain_cliffs.py:561-580` — pure-Python BFS connected-component fallback

```python
for r0 in range(rows):
    for c0 in range(cols):
        if not m[r0, c0] or labels[r0, c0] != 0:
            continue
        queue = [(r0, c0)]
        seed_id = next_id
        next_id += 1
        head = 0
        while head < len(queue):
            ...
            for dr, dc in offsets:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and m[nr, nc] and labels[nr, nc] == 0:
                    queue.append((nr, nc))
```

**Pattern:** Pure-Python flood-fill with 8-connected offsets. Activates in scipy-missing fallback only. Same complexity caveat as P2-2.
**Estimated wall time @ 4K when fallback fires:** ~30-90 seconds.
**Fix:** Treat scipy as required (it already is in requirements.txt) and either delete the fallback or guard with a clear runtime error.

---

### [P2-7] `terrain_water_variants.py:551-566` — pure-Python connected-component fallback (same family as P2-6)

```python
for r0 in range(rows):
    for c0 in range(cols):
        if not candidate[r0, c0] or visited[r0, c0]:
            continue
        n_comp += 1
        stk = [(r0, c0)]
        while stk:
            r, c = stk.pop()
            ...
            stk.extend([(r-1,c),(r+1,c),...])
```

Same severity, same fix as P2-6.

---

### [P2-8] `terrain_vegetation_depth.py:630-646` — Python two-pass labeling with full-array `labelled[labelled == max(...)] = ...` rewrite

```python
for r in range(rows):
    for c in range(cols):
        if not disturbed[r, c]:
            continue
        left = labelled[r, c - 1] if c > 0 else 0
        up = labelled[r - 1, c] if r > 0 else 0
        ...
        else:
            labelled[r, c] = min(left, up)
            labelled[labelled == max(left, up)] = min(left, up)
```

**Pattern:** Per-cell Python check **plus** a full-array `labelled == X` boolean scan AND assignment **inside the inner loop** when collisions occur. Each collision triggers an O(H·W) numpy scan over the entire labels array.
**Worst-case wall time @ 4K:** 16.7M Python iters × occasional 16.7M numpy scan in the equivalence-merge branch = **billions of operations**. Could run for **hours** at 4K when the fallback fires.
**Fix:** Use union-find for label equivalences, OR delete the fallback in favour of scipy-required.

---

### [P2-9] `_scatter_engine.py:434-448` — Python search-radius square scan inside biome-distance fallback

```python
for r2 in range(rows):
    for c2 in range(cols):
        if inside_mask[r2, c2]:
            min_d = biome_edge_feather_m / cell_size_avg + 1
            search_r = int(min_d) + 2
            for dr2 in range(-search_r, search_r + 1):
                for dc2 in range(-search_r, search_r + 1):
                    nr2, nc2 = r2 + dr2, c2 + dc2
                    if 0 <= nr2 < rows and 0 <= nc2 < cols:
                        if not inside_mask[nr2, nc2]:
                            d = _math.sqrt(dr2 * dr2 + dc2 * dc2)
                            ...
```

**Complexity:** O(H · W · search_r²). With search_r=10 at 4K = 16.7M × 441 ≈ **7.4 billion** Python iters. Scipy fallback only.
**Estimated wall time @ 4K:** **multiple hours**. Effectively non-functional at AAA size.
**Fix:** Same as above — declare scipy required, delete fallback.

---

## LOW FINDINGS (P3)

### [P3-1] `world_map.py:329-339` — Python jittered-grid loop

Small (rows×cols where both are bounded by `math.ceil(sqrt(num))`). Negligible at terrain scale; flagged for completeness.

### [P3-2] `terrain_caves.py:2795-2805, 3276-3306` — bounded H×W loops with early-break at 32 openings

Capped at 32 iterations effectively — not a hot path at AAA size. Acceptable.

### [P3-3] `terrain_features.py:1841-1850, 1868-1900, 1912-1922` — Python-loop carving on small per-feature heightmaps

These operate on small per-feature `(resolution, resolution)` arrays (typically 64×64 to 256×256). Total cost ~50-200 ms per feature mesh. Acceptable for chunked feature emission. Flag if the feature meshes are ever extended to terrain resolution.

### [P3-4] Module-level mutable dicts that **are** intentional caches:
- `terrain_pipeline.py:146` `PASS_REGISTRY` — bounded by # of registered pass kinds (~50). Fine.
- `environment_scatter.py:_SCATTER_MATERIAL_PRESETS` etc. — read-only literals at module scope. Fine.
- `terrain_audio_zones.py:_PAINT_MASKS` (inside function but `Dict[int, np.ndarray]`) — ad-hoc local cache, bounded. Fine.

### [P3-5] `terrain_destructibility_patches.py:135` and `procedural_grass.py:545` use f-strings inside hot loops

```python
records.append(GrassPlacementRecord(species=species.name, ...))   # no f-string here
```
Reviewed: the only f-strings inside H×W cell loops are in `_water_network.py:3574-3580` (issue messages, capped at 16) and `terrain_caves.py:2801` (capped at 32). All bounded — no real hazard.

---

## SUMMARY TABLE

| ID | File:Line | Pattern | Complexity | Time @ 4K | Severity |
|---|---|---|---|---|---|
| P0-1 | `_water_network.py:1551` | Python H×W Manning velocity loop | O(H·W) | ~10 s | P0 |
| P0-2 | `terrain_navmesh_export.py:354` | Python H×W vertex grid build | O(H·W) | ~25 s + 1.3 GB | P0 |
| P0-3 | `terrain_waterfalls.py:153` | Python H×W dict-per-cell builder | O(H·W) | ~50 s + 3.9 GB | P0 |
| P0-4 | `terrain_chunking.py:336-353` | Per-chunk Python list-of-lists copy | O(H·W) | ~7 s + 1.3 GB dup | P0 |
| P0-5 | `terrain_semantics.py:971` | SHA-256 over all channels per pass × 2 | O(N·K) per pass | ~4 s/call × 80 = 5+ min | P0 |
| P1-1 | `terrain_advanced.py:996` | Full-heightmap Gaussian inside per-brush smooth | O(N · H · W) | ~50 s/100 strokes | P1 |
| P1-2 | `procedural_grass.py:545` | Per-instance dataclass build for 67M grass | O(N_inst) | ~14 min + 13 GB | P1 |
| P1-3 | `terrain_checkpoints.py:50` | id()-keyed registries, never cleaned | leak | unbounded growth | P1 |
| P1-4 | `environment_scatter.py:3161, 3261` | Two `bpy.data.objects` scans per scatter | O(N_obj) × 2 | ~30 ms/pass × passes | P1 |
| P1-5 | `terrain_waterfalls.py:2308` | Per-chain (H,W,2) alloc + np.where merge | O(C·H·W) | ~8 s + ~1 GB peak | P1 |
| P1-6 | `terrain_semantics.py:1597` | `pass_history` unbounded | leak | conditional | P1 |
| P1-7 | `terrain_shadow_clipmap_bake.py:317` | `bytes` concat in scanline loop | O(rows²) memcpy | ~5-15 s | P1 |
| P2-1 | `terrain_dem_import.py:163` | O(max(H,W)·H·W) nodata fill fallback | O(K·H·W) | ~5-15 min when fired | P2 |
| P2-2 | (×6 files) | Python chamfer DT fallback | O(H·W) | ~8-15 s when fired | P2 |
| P2-3 | `terrain_destructibility_patches.py:122` | (H/cell)×(W/cell) Python block scan | O((H·W)/cell²) | ~10-20 s fallback | P2 |
| P2-4 | `_water_network.py:1077, 1129` | Python priority-flood + flood-fill | O(H·W·log) | ~20-40 s | P2 |
| P2-5 | `terrain_advanced.py:1501, 1508` | Particle-erosion Python loop | O(N_part·steps) | ~130 ms/stroke | P2 |
| P2-6 | `terrain_cliffs.py:561` | Python BFS CC fallback | O(H·W) | ~30-90 s when fired | P2 |
| P2-7 | `terrain_water_variants.py:551` | Same family as P2-6 | O(H·W) | ~30-90 s when fired | P2 |
| P2-8 | `terrain_vegetation_depth.py:630` | Per-cell labels + full-array merge scan | O(H²·W²) worst | hours when fired | P2 |
| P2-9 | `_scatter_engine.py:434` | Per-cell biome-distance Python search | O(H·W·r²) | hours when fired | P2 |

## RECOMMENDATIONS (ranked by ROI)

1. **P0-5 (compute_hash)** — Biggest cumulative cost across a full pipeline run. Estimated **>5 minutes** of pure SHA-256 work per terrain. Caching channel-bytes and switching to memoryview alone reclaims 90%+. Highest single ROI.
2. **P0-1 (Manning loop)** — Single hot function, trivial vectorisation, ~100× speedup.
3. **P0-3 (waterfalls vertex dicts)** — Memory + time win. The dict-per-cell pattern is the worst-case Python-object density in the codebase.
4. **P0-2 (navmesh vertex grid)** — Same family as P0-3, smaller absolute cost but called per-tile.
5. **P0-4 (chunking row copy)** — Removing the list-of-lists copy and exposing the ndarray view propagates speedups to all downstream chunk consumers.
6. **P1-2 (grass per-instance loop)** — Architectural: 67M dataclasses cannot scale to AAA. Move to columnar storage.
7. **P1-1 (brush Gaussian)** — Localised fix, easy 100×.
8. **P1-3 (checkpoint registry leak)** — `WeakKeyDictionary`, two-line fix, prevents long-session memory blowup.
9. **P2-2/P2-6/P2-7/P2-8/P2-9 (scipy fallbacks)** — Bulk-delete the pure-Python fallbacks. They are de-facto unreachable on AAA workloads (would run for hours/days), and their existence creates false confidence that the code is degraded-mode-safe. Replace each with a clear `raise RuntimeError("scipy is required for AAA terrain")`.

## OPEN QUESTIONS

- **Q1 (P0-5):** How often is `compute_hash` actually consumed downstream? If the pre-pass hash is only used by checkpoint provenance (`content_hash_before` is recorded but not always read), gating it on `checkpoint=True` alone could remove the cost entirely on non-checkpointed runs.
- **Q2 (P1-2):** Are grass placements ever serialised as individual records, or do they always go to Unity through a columnar `npz`/`fbx` writer? If the latter, the `GrassPlacementRecord` instances are pure overhead.
- **Q3 (P2-4):** Is there an adopted dependency policy on `richdem` or `pyflwdir`? The priority-flood algorithm is the architectural ceiling for hydrology at 8K and cannot reach AAA wall-time without a compiled implementation.
