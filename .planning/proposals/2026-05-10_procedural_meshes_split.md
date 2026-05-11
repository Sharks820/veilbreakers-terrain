---
date: 2026-05-10
agent: wave-4-procedural-meshes-split
status: proposal-ready-for-execution
parent_proposal: .planning/proposals/2026-05-10_repo_reorg.md
---

# `procedural_meshes.py` Split — Detailed Migration Plan (Wave 4/4)

## Why this isn't a "just refactor it" job

`veilbreakers_terrain/procedural_meshes.py` is **22,816 LOC** with **290 top-level functions** and **2 classes**. It's a single-file catalog of mesh generators for ~25 distinct asset domains (furniture, vegetation, weapons, dungeon decor, traps, occult, etc.). The size alone causes:

- Pyright re-checks the whole file on any edit (slow IDE / CI)
- Code reviewers can't see meaningful context
- 290 functions in one namespace makes IDE navigation a chore
- Test isolation impossible — touching any function loads the whole catalog
- Pylint / Ruff caches are file-scoped, so they invalidate often

The scope contamination has been memory-flagged since 2026-04-12 (`project_procedural_meshes_scope.md`).

## External surface area (importers — preserve EXACTLY)

| Importer | Line | Imports |
|---|---|---|
| `veilbreakers_terrain/handlers/environment.py` | :229 | Bulk `from ..procedural_meshes import (...)` (re-export) |
| `veilbreakers_terrain/handlers/_bridge_mesh.py` | :15 | `_make_result`, `generate_bridge_mesh` |
| `veilbreakers_terrain/handlers/_mesh_bridge.py` | :26 | Bulk import |
| `veilbreakers_terrain/handlers/_terrain_depth.py` | :51 | Bulk import |
| `veilbreakers_terrain/tests/test_sim_modules.py` | :76 (lazy) | `generate_rope_bridge_mesh` |

**Plus**: `pyright-strict-baseline.json:273+` references rows. **Plus**: `GRADES_VERIFIED.csv` references procedural_meshes line numbers. **Plus**: docs that cite specific line ranges.

The shim must make **every name** that was reachable via `from veilbreakers_terrain.procedural_meshes import X` continue to resolve. Anything less breaks importers silently.

## Proposed target package layout

```
veilbreakers_terrain/procedural_meshes/
├── __init__.py            # Re-export shim — every name from old module
├── _core/
│   ├── __init__.py
│   ├── primitives.py      # _make_box, _make_cylinder, _make_cone, _make_torus_ring, _make_tapered_cylinder, _make_beveled_box, _make_sphere, _make_lathe, _make_profile_extrude, _make_faceted_rock_shell  (≈1100 LOC)
│   ├── helpers.py         # _grid_vector_xyz, _detect_grid_dims*, _get_trig_table, _auto_detect_sharp_edges, _auto_generate_box_projection_uvs, _make_result, _alias_generator_category, _compute_dimensions, _circle_points, _enhance_mesh_detail, _merge_meshes  (≈300 LOC)
│   ├── registry.py        # _GeneratorRegistry  (~50 LOC)
│   └── protocols.py       # _GridMeshLike Protocol  (~15 LOC)
├── furniture.py           # generate_table, chair, shelf, chest, barrel, candelabra, bookshelf  (~600 LOC)
├── vegetation.py          # generate_tree, rock, mushroom, root, grass_clump, shrub, ivy  (~700 LOC)
├── dungeon_decor.py       # generate_torch_sconce, prison_door, sarcophagus, altar, pillar, archway, chain, skull_pile  (~760 LOC)
├── weapons/
│   ├── __init__.py
│   ├── blunt.py           # hammer, spear, crossbow, scythe, flail, whip, claw, tome  (~600 LOC)
│   ├── blade.py           # greatsword, curved_sword, hand_axe, battle_axe, greataxe, club, mace, warhammer  (~900 LOC)
│   ├── paired.py          # paired_daggers, twin_swords, dual_axes, dual_claws  (~280 LOC)
│   ├── fist.py            # brass_knuckles, cestus, bladed_gauntlet, iron_fist  (~270 LOC)
│   ├── thrusting.py       # rapier, estoc  (~200 LOC)
│   └── thrown.py          # javelin, throwing_axe, shuriken, bola  (~270 LOC)
├── magic_focus.py         # orb_focus, skull_fetish, holy_symbol, totem  (~340 LOC)
├── architecture.py        # gargoyle, fountain, statue, bridge, gate, staircase  (~810 LOC)
├── barriers.py            # fence, barricade, railing  (~430 LOC)
├── traps.py               # spike_trap, bear_trap, pressure_plate, dart_launcher, swinging_blade, falling_cage  (~420 LOC)
├── vehicles.py            # cart, boat, wagon_wheel  (~470 LOC)
├── fortifications.py      # column_row, buttress, rampart, drawbridge, well, ladder, scaffolding  (~570 LOC)
├── dark_occult.py         # sacrificial_circle, corruption_crystal, veil_tear, soul_cage, blood_fountain, bone_throne, dark_obelisk, spider_web, coffin, gibbet  (~900 LOC)
├── containers.py          # urn, crate, sack, basket, treasure_pile, potion_bottle, scroll  (~550 LOC)
├── lighting.py            # lantern, brazier, campfire, crystal_light, magic_orb_light  (~400 LOC)
├── portals.py             # door, window, trapdoor  (~400 LOC)
├── wall_decor.py          # banner, wall_shield, mounted_head, painting_frame, rug, chandelier, hanging_cage  (~700 LOC)
├── crafting.py            # anvil, forge, workbench, cauldron, grinding_wheel  (~400 LOC)
└── _legacy.py             # TEMP — original 22.8K file, deleted after final phase
```

**Total**: ~24 domain files + 4 `_core/` files + 1 `__init__.py` + 1 `_legacy.py` (temp).

## Migration phases (each = own PR)

### Phase 0 — Setup (zero behaviour change)
1. Create `veilbreakers_terrain/procedural_meshes/` package dir.
2. Move existing `procedural_meshes.py` → `procedural_meshes/_legacy.py`.
3. Add `procedural_meshes/__init__.py` containing:
   ```python
   # Phase 0 — shim during the split.
   # Re-exports every public + private name from the legacy single-file
   # module. Domain extraction happens in Phases 1-N; the shim keeps
   # external importers green throughout.
   from ._legacy import *  # noqa: F401,F403
   from ._legacy import (  # noqa: F401  - explicit names not in __all__
       _make_result,
       _GeneratorRegistry,
       _GridMeshLike,
       # ... all _-prefixed names that handlers/_bridge_mesh.py imports
   )
   ```
4. Update `pyright-strict-baseline.json` if file path renames break baseline anchors.
5. Run all 4 mandatory gates locally; confirm green.

**Risk**: minimal. Pure file move + shim. No symbol semantics change.

### Phase 1 — Extract `_core/` (foundations)
1. Move helpers, primitives, registry, protocol → `_core/`.
2. Update `_legacy.py` to import these from `_core/` at the top:
   ```python
   from ._core.helpers import (
       _grid_vector_xyz,
       _detect_grid_dims_from_vertices,
       # ...
   )
   from ._core.primitives import _make_box, _make_cylinder, ...
   ```
3. `__init__.py` re-exports both `_core/` names AND `_legacy` names.
4. Gates: pyright, callable_census, terrain_best_practice_guardrail.

**Risk**: low. `_core/` symbols are stable utilities; few internal call-sites.

### Phases 2-N — Domain-by-domain extraction (one PR per file)
For each domain file (`furniture.py`, `vegetation.py`, etc.):
1. Cut domain section from `_legacy.py` → new file.
2. Add `from ._core.helpers import _make_result, ...` plus any cross-domain imports.
3. Update `_legacy.py` to re-export from the new module so any internal references continue to work:
   ```python
   from .furniture import (
       generate_table_mesh,
       generate_chair_mesh,
       # ...
   )
   ```
4. Update `__init__.py` to also re-export from the new domain file (idempotent).
5. Run gates.

**Risk**: moderate per phase. Each domain has potential for cross-domain helper calls. Catch via gate failures + targeted pytest runs.

### Phase N+1 — Delete `_legacy.py`
1. Verify every name is now re-exported from a domain file.
2. Update `__init__.py` to drop `_legacy` references.
3. Delete `_legacy.py`.
4. Run **full** pytest + all 4 gates.

**Risk**: highest single phase. The catch-net for any name that wasn't migrated. Test thoroughness here matters.

## Risk register

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Hidden name dependency between two domain functions (e.g. `generate_chair_mesh` calls `_some_helper_defined_in_weapons`) | Medium | High | Phase 0 keeps everything in `_legacy.py`; subsequent phases migrate domains one at a time. Each phase verifies imports resolve and pytest passes. |
| `pyright-strict-baseline.json:273+` anchors drift | High | Medium | Run `pyright_strict_baseline_gate.py` at end of each phase; commit baseline updates as part of the phase PR. |
| `GRADES_VERIFIED.csv` row anchored to specific file path | Low | Medium | Audit CSV before Phase 0; update row(s) if file path or line numbers are part of the assertion. |
| `test_sim_modules.py:76` lazy import path | Low | Low | Lazy import (`from veilbreakers_terrain.procedural_meshes import generate_rope_bridge_mesh`) still resolves via `__init__.py` shim — no change needed. |
| 4 handler importers reference internal names (`_make_result`, etc.) | Medium | High | Phase 0 shim explicitly re-exports `_`-prefixed names. Verify before merging Phase 0 PR by grepping every importer's import list. |
| `from .procedural_meshes import *` somewhere | Low | Medium | Grep for `from .*procedural_meshes import \*` — none found currently, but verify before Phase 0. |
| Test fixtures that reload the module | Low | Low | Pytest's import cache may need flushing if any test does `importlib.reload(procedural_meshes)`. Grep for `reload\|importlib`. |
| Circular import via `_core/` (e.g. `_make_result` calls a domain function) | Low | High | `_core/` should NEVER import from domain files. Enforce by review during Phase 1. |

## Estimated effort

| Phase | Touched files | Estimated time | Reviewer cost |
|---|---|---|---|
| 0 | 2 (move + `__init__.py`) | 30 min | trivial |
| 1 | 5 (`_core/` x 4 + `_legacy.py`) | 90 min | small |
| 2-N (24 phases) | ~3 each | 30-60 min each (avg 45 min) | small each |
| N+1 | `__init__.py` + delete `_legacy.py` + pytest sweep | 60 min | medium |
| **Total** | **~30 files** | **~22 hours** | **Many small PRs review well** |

## Why this is N+2 PRs, not 1

Doing all 24 domains in a single PR:
- Diff size: ~22,800 LOC moved + ~24 new file headers + `__init__.py` re-exports = unreviewable
- Bisect blast radius: if a test breaks, the breakage could be in any domain; small PRs let bisect pinpoint
- Reverting partial work: a single rollback discards 22 hours of refactoring
- CI risk: each phase verified independently catches name-resolution bugs early

Small PRs are the responsible move here. The shim makes them safe to stack — every commit is a green state.

## Open questions (user decision before Phase 0)

1. **Branch strategy** — one long-lived feature branch with stacked PRs, or one PR per phase merged to main sequentially?
2. **Domain naming** — `dungeon_decor.py` vs `architectural_decor.py` vs `decor_dungeon.py`? Pick a convention.
3. **`weapons/` subdir vs flat** — package the 6 weapon files under `weapons/` subdir, or keep at top of `procedural_meshes/`? Subdir is cleaner but adds an import-path level.
4. **Snapshot** — capture a `procedural_meshes_legacy_snapshot.py` git ref *before* Phase 0 so any escape hatch lets us diff against the known-good single-file state? (Recommended)

## Recommendation

**Do not attempt this in the 2026-05-10 session.** Schedule a dedicated 2-4 hour focused session to ship Phase 0 + Phase 1, then trickle Phases 2-N as background work over the next 1-2 weeks. The risk of a half-finished split corrupting the index is high enough that the user should explicitly approve the branch strategy first.

**Next session deliverable**: PR for Phase 0 + Phase 1, with a tracking issue covering Phases 2-N.
