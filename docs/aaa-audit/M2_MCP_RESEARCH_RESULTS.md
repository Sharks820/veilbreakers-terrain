# M2 MCP-Deep Research Wave — Results

**Status:** COMPLETE — 12 of 12 agents finished
**Date:** 2026-04-16
**Scope:** All NOT-IN-CONTEXT7 / NEEDS-REVISION / missing-external items surfaced by the Context7 Round 2 pass.

---

## Executive numbers

| Metric | Count |
|--------|:-----:|
| Agents dispatched | 12 (Opus 4.7, parallel) |
| Bugs verified | 97 |
| R7 MCP verification lines inserted into master audit | 91 |
| Bugs with upgraded verdicts (CONFIRMED-STRONGER) | 24+ |
| New bugs surfaced | 3 (NEW-BUG-A1-01 / 02 / 03) |
| Architectural meta-findings | 12 (new H3 block in master) |
| Critical R5 errors caught | 2 (`bmesh.ops.decimate` and `bmesh.ops.boolean` DO NOT EXIST) |
| Severity escalations | BUG-140 → CRITICAL, BUG-60 HIGH reaffirmed |
| Total MCP tool calls across agents | ~290 |

---

## Agent-by-agent summary

| Agent | Cluster | Bugs | Verdict mix | Notable win |
|:-----:|---------|:----:|-------------|-------------|
| A1 | External deps (rasterio, OpenEXR, watchdog, Wwise, Recast, impostor) | 7 | 3 CONF-STR, 3 CONF, 1 NEEDS-REV | 3 NEW bugs (SRTM big-endian, OneDrive watchdog, waapi/autobahn) |
| A2 | Hydrology (D8, Priority-Flood, Beyer, Strahler, Liang-Barsky) | 13 | 7 CONF-STR, 5 CONF, 1 NEEDS-REV | Beyer 2015 §5.4 formula verbatim; `np.nextafter` ε for Priority-Flood |
| A3 | Caves / SDF / marching cubes | 8 | Mixed; BUG-82 master-fix direction WRONG for Unity | `ndimage.label+bincount` one-pass; KarstMorphology enum |
| A4 | Coord conventions (Unity / UE / GDAL) | 7 | All CONFIRMED | R5 cell-CORNER flip primary-source verified; propose `terrain_coords.py` |
| A5 | Procedural mesh topology (bmesh) | 14 | 14 CONF | **`bmesh.ops.decimate` does NOT exist**; icosphere subdiv=3 floor |
| A6 | DAG pass-graph / channel drift | 9 | 3 BLOCKER, 4 IMPORTANT | `__getattr__` contract decorator + AST-lint closes 11 bugs as one class |
| A7 | Erosion (Beyer, Gaea, lpmitchell) | 10 | Mixed | Gaea Stratify geometry-modifying confirmed; lpmitchell ref UNFINDABLE — Axel Paris 2018 substituted (flag for user) |
| A8 | LOD / vegetation / impostor | 7 | All CONF | Fortnite impostor spec: 12×12=144 frames @ 2048²; `meshoptimizer` Python binding |
| A9 | Atmospheric volumes | 7 | Mixed | BUG-140 upgraded to CRITICAL; BUG-116 needs triplanar for overhangs |
| A10 | Tile-parallel / determinism | 10 | All CONF | NumPy docs explicitly flag BUG-49 pattern "UNSAFE! Do not do this!"; `rand()%7` modulo bias |
| A11 | Coastline / waves / noise | 6 | 6 CONF (1 out-of-scope) | sin-hash NOT cross-platform bit-stable → breaks deterministic replay |
| A12 | Honesty / live-preview / reload | 12 | All CONF | 9 AAA rebake-hint patterns; `replace()` bypasses `__setattr__` |

---

## 3 new bugs (full entries in master audit)

- **NEW-BUG-A1-01 — SRTM big-endian byte-order:** silent data corruption on Windows if `np.int16` used without `>` prefix. **HIGH.**
- **NEW-BUG-A1-02 — watchdog + OneDrive phantom-fires:** `ReadDirectoryChangesW` triggers on OneDrive sync ticks; affects Conner's exact repo path. **IMPORTANT.**
- **NEW-BUG-A1-03 — waapi-client pulls autobahn==24.4.2:** conflicts with Blender's embedded asyncio; if adopted for BUG-121 must be isolated to designer-side venv. **HIGH.**

---

## 12 architectural meta-findings (new H3 block in master audit)

Higher-leverage than individual BUG fixes — each closes a whole class of future regressions. Highlights:

- Unified `DeterministicRNG` class kills BUG-48 / 49 / 81 / 91 / 96 in one PR (A10)
- Unified `terrain_coords.py` + `terrain_units.py` kills 7 coord/unit bugs (A4)
- Runtime `__getattr__` contract-check decorator + AST-lint closes 11 DAG-drift bugs as one class (A6)
- "Always declare, conditionally write zeros" architectural rule for DAG pass-graph (A3 + A6)
- 9 AAA rebake-hint patterns (`RefreshMask`, named-handle registry, provenance lists, AST-not-grep) kill 12 honesty bugs (A12)
- Two critical errors in prior R5 notes caught — `bmesh.ops.decimate` and `bmesh.ops.boolean` do not exist; any R5 fix that references them must be rewritten (A5)
- Fortnite impostor spec (12×12=144 frames @ 2048²) sets the AAA floor for BUG-137 / BUG-141 (A8)
- lpmitchell GLSL reference is NOT FINDABLE via any MCP — user should verify author name or accept Axel Paris 2018 as the canonical substitute (A7)
- sin-hash is NOT cross-platform bit-stable → breaks deterministic replay when mixed engine builds share seeds (A11)
- `dataclasses.replace()` bypasses `__setattr__`, so BUG-113's lock guard MUST live at the public mutator choke point (A12)
- BUG-128 hot-reload incompat fixed via named-handle registry, not list append (A12)
- NumPy 2.x `default_rng([worker_id, root_seed])` is canonical for parallel RNG; the mechanically-migrated `RandomState(base_seed + worker_id)` pattern is explicitly flagged "UNSAFE! Do not do this!" in NumPy docs (A10)

---

## MCP quota observations

- **Brave:** token 422 — rotate.
- **Tavily:** free-tier quota exhausted partway through — need upgrade or wait for monthly reset before next broad wave.
- **Firecrawl + Exa:** handled 12 parallel agents cleanly.
- **Microsoft Learn:** rarely triggered (terrain algorithms skew to gamedev DCC docs, not Windows/Azure).

Quota status added to `~/.claude/projects/.../memory/reference_mcp_servers.md`.

---

## BUGs not captured by R7 pass (miss list)

- **BUG-143:** referenced in tables but has no standalone `### BUG-143` section in master audit. Tracked under B14 vegetation cluster in deep-dive files.
- **BUG-36:** same pattern; tracked under Context7 R1 summary.

Both will be surfaced in M3 (cleanup / normalization pass).

---

## What's next (M3 candidates)

1. **Execute the top architectural wins.** The unified `DeterministicRNG`, `terrain_coords.py`, and `__getattr__` contract decorator each close 5-11 bugs in one refactor. Cheap, high-leverage.
2. **Rotate Brave API key + upgrade Tavily** so the next research wave has full coverage.
3. **Verify lpmitchell reference** — either locate the original source or officially substitute Axel Paris 2018.
4. **Promote BUG-143 and BUG-36** into standalone `### BUG-` sections so they're visible to future graders.
5. **Apply fixes** — the audit is saturated; next productive move is a triage pass on severity + execute order, not more auditing.
