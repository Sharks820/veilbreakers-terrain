# veilbreakers-terrain

Terrain, environment, water, biome, coastline, and atmospheric generation
for the VeilBreakers gamedev toolkit.

## Provenance

Extracted from
[veilbreakers-gamedev-toolkit](https://github.com/Sharks820/veilbreakers-gamedev-toolkit)
at rollback tag `pre-terrain-extraction-2026-04-15` via
[`git filter-repo`](https://github.com/newren/git-filter-repo). Per-file
history is preserved — `git log --follow` on any `veilbreakers_terrain/handlers/*.py`
file still shows its original commit lineage from the toolkit.

See Phase 50 in the toolkit's `.planning/phases/50-terrain-repo-extraction/`
for the full split rationale, decisions (D-01 ... D-17), and rollback plan.

## Dependency model (one-way)

- `veilbreakers-terrain` depends on `veilbreakers-mcp` (the toolkit) via an
  editable sibling-disk install.
- The toolkit **never** imports from `veilbreakers-terrain`. This is enforced
  by `scripts/cross_repo_import_lint.py` in the toolkit repo (D-09).
- The toolkit's `blender_addon/__init__.py` has a preflight hook that
  fails loud if `veilbreakers_terrain` is missing (D-07).

## Install (sibling-disk editable)

Clone both repos as siblings on disk:

```bash
git clone https://github.com/Sharks820/veilbreakers-gamedev-toolkit
git clone https://github.com/Sharks820/veilbreakers-terrain
```

Install toolkit first, then terrain (editable so edits pick up immediately):

```bash
pip install -e ./veilbreakers-gamedev-toolkit/Tools/mcp-toolkit
pip install -e ./veilbreakers-terrain
```

Verify both packages are importable from the same interpreter:

```bash
python -c "import veilbreakers_mcp; import veilbreakers_terrain; print('both OK')"
```

## Layout

```
veilbreakers_terrain/
  handlers/       # 105 handler modules (terrain_*, _terrain_*, _water_*, environment*, coastline, atmospheric_volumes, _biome_grammar)
  tests/          # Pytest suite extracted from toolkit tests/
    contract/     # Contract tests for terrain pipeline invariants
    integration/  # End-to-end pipeline integration test
  docs/           # Extracted terrain-specific docs
  presets/        # quality_profiles/*.json (preview, production, hero_shot, aaa_open_world)
  contracts/      # terrain.yaml — L0 contract source of truth
```

## Tests

```bash
pip install -e '.[dev]'
python -m ruff check .
pytest veilbreakers_terrain/tests/ -q
```

## Preset / contract usage

Terrain generation is driven by:

- `veilbreakers_terrain/contracts/terrain.yaml` — machine-readable contract (L0 of
  the quality infrastructure — see toolkit `CLAUDE.md`).
- `veilbreakers_terrain/presets/quality_profiles/*.json` — preview / production /
  hero_shot / aaa_open_world quality budgets.

## Rollback

The split is fully reversible. See the toolkit's
`.planning/phases/50-terrain-repo-extraction/50-03-PLAN.md` §Rollback plan
for the `git revert -m 1 <merge-sha>` recipe.
