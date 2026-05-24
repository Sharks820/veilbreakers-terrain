# The Generation Truth Rule

**The generator is the product. Renders are tests of the generator. Fix the generator, never the test.**

The value in this repository is `veilbreakers_terrain/` — the procedural passes and their callables. The nodes built by `scripts/build_*` and the images produced by `scripts/render_*` are **disposable verification fixtures** that exercise generator callables. They are not assets to keep, polish, or commit.

## The rule

1. **A render / `.blend` / PNG is verification evidence, never a deliverable.** Never hand-edit a `.blend`, and never tweak a render script (camera, lighting, post) to make a defect "look fixed." That fakes the test.

2. **A visual defect routes to the generator callable that produced the data,** and is fixed there. A wrong-looking render is a generation defect until proven otherwise. Trace it: which pass / which callable in `veilbreakers_terrain/` emitted the bad geometry, material, or channel?

3. **`scripts/` files drive output through generator callables / `COMMAND_HANDLERS`. They never reimplement generation.** A standalone material/mesh/water/scatter factory defined inside a `scripts/` file is a smell — it diverges from (and silently replaces) the real generator path. Canonical offender: `scripts/build_scene_v3.py:make_water_material` (graded D+, "not a default terrain runtime path").

4. **After a generator fix: regenerate → re-render → visually verify.** Read the resulting image and state what is *literally* there before claiming the fix works. This is a hard project rule: a fix is not "done" until the render has been opened, inspected, and described — never on the strength of code changes alone.

5. **Render / test `.blend` artifacts are not committed.** They are regenerated on demand. Exception: a small set of `output/` files are CI-gate inputs (`output/verification/*GUARDRAIL_REPORT*`, `output/spreadsheet/CALLABLE_WIRING_*`) — those stay tracked. Render PNGs, test `.blend`/`.blend1`, and scratch logs do not.

## Why

Fixing the test instead of the generator produces three compounding failures:
- The generator's real callables never improve (their defects stay latent and ship).
- The fixture diverges further from the generator each "fix," so renders stop representing real output (you are QA-ing a thing you don't ship).
- Version control fills with churning binary render artifacts (see the Git-LFS pointer churn on `output/`).

## How to apply (defect triage)

```
render shows a defect
  └─ is it a render-rig problem (camera clipping, wrong angle, missing light)?
        ├─ yes → the rig is a test harness; fix the rig ONLY for visibility,
        │        never to hide a generation defect. Re-aim is allowed; concealment is not.
        └─ no  → it is a generation defect
                   └─ find the pass/callable in veilbreakers_terrain/ that owns the data
                         └─ write a failing test pinning correct behavior
                               └─ fix the callable
                                     └─ regenerate → re-render → visually verify
```

## Enforcement

A guard test fails if any file under `scripts/` defines a generation factory (starting with water-material factories). The rule is executable, not aspirational. See `docs/superpowers/specs/2026-05-23-generator-water-source-of-truth-design.md` for the first worked example.
