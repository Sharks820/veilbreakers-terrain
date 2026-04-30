# Missing Items Rescan - 2026-04-30

Scope: refresh `MISSING_ITEMS_IMPLEMENTATION_GUIDE_2026_04_30.md` after concurrent Codex work and the final semantic-golden hardening sweep.

## Final Current Status - 2026-04-30

- Code guardrails are merge-safe from the refreshed local evidence.
- Blender visual readiness proof now exists from local Blender 4.5 headless
  render: `ready_for_visual_testing=True`, `placeholder_png=False`,
  `blank_png=False`, decoded luminance stats present.
- Unity editor runtime import proof now exists from Unity 2022.3.62f3 batchmode
  smoke: NavMeshData asset, water plane/elevation, water depth/flow sidecars,
  light/probe objects, foliage renderer manifest, and duplicate-free reimport.
- Current full suite: prior full-suite evidence was `3720 passed in 372.38s`; final post-semantic sweep rerun is recorded separately when complete.
- Current callable census: `1726/1726`, `0 uncovered`.
- Current wiring scan: `true_wiring_risks=0`.
- Current verification matrix: `0` blocker, `0` high,
  `false_grade_A_rows=0`.
- Current best-practice guardrail: `1728` live callables, `1728` matrix rows,
  `0` missing, `blocking=False`; `--require-a-grade --no-write` passes.

## Scan Results

- `python scripts/callable_census_gate.py --strict-zero`: PASS, `1726/1726`, `0 uncovered`.
- `scripts.scan_callable_wiring` with temp outputs + `--strict-no-risk`: PASS, `0 true_wiring_risks`.
- `build_test_guardrail_audit` with temp outputs + `--strict-quality`: PASS.
- `python -m veilbreakers_terrain.handlers.terrain_scatter_altitude_audit_linter`: PASS.
- `python -m pytest --collect-only -q`: PASS, `3720 tests collected`.
- `python -m ruff check --select F821 veilbreakers_terrain/handlers`: PASS.
- Focused CI lint command from `python-package.yml`: PASS.
- Full suite: `python -m pytest -q -ra --basetemp output\pytest-tmp\full-post-guardrails-4`: PASS, `3720 passed in 372.38s`.
- Targeted tests:
  - `test_bundle_r.py`: `66 passed`.
  - `test_terrain_unity_export_bridge.py`: `26 passed`.
  - `test_terrain_iteration.py`: `32 passed`.
  - `test_visual_testing_readiness_gate_script.py` + `test_scene_v3_visual_quality_gate.py`: `11 passed`.
- Stale earlier caveat: previous ignored pytest atexit cleanup warnings did not
  appear in the final full run summary.

## Meaningfully Improved Since Guide

| Area | Old status | Current status |
| --- | --- | --- |
| Callable census trigger | PR-only | `callable_census.yml` now runs on `push` and `pull_request`; PR-only job guard removed. |
| Callable/wiring scans | Callable census only in workflow | Workflow now also runs `scan_callable_wiring.py --strict-no-risk`. |
| Callable coverage | Previously guide referenced `1699/1699` memory | Current strict scan reports `1726/1726`, `0 uncovered`. |
| Pytest hardening | No timeout/strict markers/durations/maxfail | `pyproject.toml` now has `pytest-timeout`, `timeout=120`, strict markers, durations, maxfail, short tb. |
| Branch coverage | Absent | `python-package.yml` now passes `--cov-branch`; coverage floor remains `40`. |
| Pre-commit | Absent | `.pre-commit-config.yaml` exists with local Ruff/callable/guardrail hooks. |
| Unity export hard fail | Python wrote failed manifest + descriptor | `export_unity_manifest(..., fail_on_validation_error=True)` now raises before `unity_import_descriptor.json`; test asserts descriptor absent. |
| Audio zone list export | Explicit `audio_zone_list` without raster returned empty | `_audio_zones_json` now serializes explicit list; test added. |
| Unity dropped sidecars | Atmos/wind/cloud/navmesh absent from importer descriptor handling | Import descriptor now includes `atmospheric_volumes_file`, `wind_field_descriptor`, `cloud_shadow_descriptor`, `navmesh_area_id_file`; importer creates sidecar refs. |
| Unity unknown descriptor keys | No warning | `WarnUnhandledDescriptorKeys()` added for import descriptor top-level keys. |
| Hydraulic high-request erosion | 50K small-tile tests could take minutes | Cached brush kernel, vectorized talus smoothing, transparent cap telemetry, and wall-clock regression guard now cover this path. |
| Quality-profile defaults | Deprecated `production` surfaced warnings | Runtime defaults now use `aaa_open_world`; cheaper smoke coverage uses explicit `standard`. |
| Texture ingest | HDR floats and packed normals could be mishandled | HDR float payloads stay in float space and packed normals decode to tangent-space vectors before blend/normalize. |

## Still Open From Previous Guide

| Priority | Finding(s) | Current evidence | Still needed |
| --- | --- | --- | --- |
| P0 | FIND-001/FIND-036 | `handle_export_unity_bundle` now uses `@enforce_protocol`, but broad registered export/gameplay/navmesh/wildlife pass adoption is not proven by a dedicated scanner. | Apply decorators or land protocol-specific scanner/allowlist. |
| P0 | FIND-002/FIND-034/FIND-035 | CLOSED for readiness proof: workflow runs Blender directly, no `continue-on-error`, tracked thumbnail and reference thumbnail are real 35KB renders, gate decodes PNG without Pillow and blocks failed/stale captures or missing references. | Add per-scenario rendered golden baselines before claiming final visual AAA quality. |
| P0 | FIND-009 | `python-package.yml` now has branch coverage but still has `--cov-fail-under=40`. | Raise floor after measuring current coverage; guide suggested staged 55 -> 65 -> 70. |
| P0 | FIND-024 | GitHub API still reports `main protected=false`; protection endpoint returns `Branch not protected`. | Enable branch protection/required checks. |
| P0 | FIND-015 | CLOSED: `_merge_pass_outputs()` recomputes `height_min_m/height_max_m` from merged `height` after worker outputs merge. | Keep DAG merge regression tests wired. |
| P0/P1 | FIND-006 | CLOSED: Unity importer builds deterministic `NavMeshData` asset with `NavMeshBuilder.BuildNavMeshData` and area modifier sources from `navmesh_area_id.bin`; Unity batchmode smoke verified asset creation. | Keep Unity batchmode smoke and descriptor tests wired. |
| P1 | FIND-014 | No `test_socket_server.py` found. | Add socket server framing/partial read/error tests. |
| P1 | FIND-011 | A small-tile hydraulic wall-clock guard exists, but no `pytest-benchmark` or 1024x1024 benchmark regression CI exists. | Add benchmark dependency and nightly/perf workflow; avoid making 1024x1024 a default push gate until hardware budget is explicit. |
| P1 | FIND-012 | `terrain_validation.py` still does not wire `validate_strahler_ordering`; geology validator remains separate/overlapping. | Add adapter and include non-overlap validator. |
| P1 | FIND-018/FIND-020 | `TerrainIntentState.composition_hints` remains mutable `Dict[str, Any]` with old REVIEW-IGNORE note. | Typed/immutable hints migration. |
| P1 | FIND-030 | Rule 5 still accepts `bulk_edit=True`; `environment.py` still defaults direct protocol call `bulk_edit=True`. | Replace with pass budget/rationale contract. |
| P1 | FIND-005 | `procedural_meshes.py` still 863,004 bytes, 291 top-level defs/classes. | Split after P0 guardrails. |
| P2 | FIND-027/FIND-029 | No mutmut/cosmic-ray; CodeQL still default comments only, no custom pack. | Add scheduled mutation testing and CodeQL query pack. |
| P2 | FIND-038 | CLOSED: `.gitattributes` exists with binary/render asset handling. | Keep large generated artifacts out of normal source churn. |

## New Or Missed Issues

### RESCAN-001 - Protocol Rule 2 Can Be Implicitly Bypassed In Wrapper

`ProtocolGate.rule_2_sync_to_user_viewport()` hard-raises when called with `out_of_view_ok=False`, but `enforce_protocol()` previously defaulted:

```python
params.get("out_of_view_ok", state.viewport_vantage is None)
```

The direct Unity export boundary is now decorated with explicit rule toggles. A broader scanner is still needed before claiming all registered protocol surfaces are enforced.

Fix: default to `False`; require explicit `out_of_view_ok=True` for headless CI with reason in params or pass metadata.

### RESCAN-002 - Callable Wiring Scan Does Not Prove Protocol Adoption

`scan_callable_wiring.py --strict-no-risk` passes with zero risks, but it only proves reachability/grade exposure. It does not check `@enforce_protocol` adoption. FIND-001 remains open even though callable scans are green.

Fix: add protocol decorator scanner or extend wiring scan with a dedicated `protocol_wrapped` column and strict mode.

### RESCAN-003 - Python CI Ruff Gate Was Narrowed

`python-package.yml` used to run `python -m ruff check .`. It now runs:

- `ruff check --select F821 veilbreakers_terrain/handlers`
- full Ruff only on a targeted file list.

This is useful for stabilization, but it is not equivalent to full-repo lint. New files outside the targeted list can bypass Ruff.

Fix: keep targeted runtime-error gate, but add a non-blocking or staged full `ruff check .`; once clean, make it blocking.

### RESCAN-004 - Unity Unknown-Key Warning Covers Descriptor, Not Raw Manifest

Importer now warns for unknown top-level keys in `unity_import_descriptor.json`. The original finding mentioned manifest keys. If a key exists only in `manifest.json` and never reaches descriptor, Unity still will not warn.

Fix: either ensure every exported manifest sidecar field is mirrored into descriptor, or have importer read `manifest.json` and warn on unhandled top-level keys there too.

## Current Go/No-Go

Code guardrails are merge-safe from current local evidence. Visual readiness
and Unity import readiness are now proven; final visual AAA terrain-quality
still needs semantic golden baselines and live generated-map review.

Merge-safe slices:

1. Callable census + test hardening changes look good from scans.
2. Unity export hard-fail/audio-zone/importer sidecar changes pass focused tests.

Still blocking for full original AAA claim:

1. Protocol adoption scanner/decorators.
2. Semantic visual golden baselines.
3. Branch protection.
4. Coverage floor still 40, despite branch coverage being enabled.
5. Branch protection / required remote checks.
