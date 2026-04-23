# VeilBreakers Terrain

AAA-grade procedural terrain, environment, water, and biome generation for the VeilBreakers gamedev toolkit. Designed for direct live testing in Blender.

## Features

- **Procedural heightmap generation** — multi-octave fBm, domain-warped Simplex noise, ridge noise, and thermal/hydraulic erosion
- **Biome system** — 14 named biomes with voronoi boundaries, ecotone blending, and biome-grammar rule application
- **Water network** — Barnes (2014) Priority-Flood D8 routing, river/lake/waterfall detection, tile-contract geometry matching
- **Vegetation** — L-system trees, biome-aware scatter (Poisson-disk, Lloyd relaxation), SpeedTree-compatible wind vertex colors, 9-view billboard impostors
- **Coastline** — tidal-zone classification, coastal erosion (wave-energy scaled), reef/lagoon/beach procedural profiles
- **Caves & karst** — chamber mesh generation, stalactite/stalagmite placement, Dreybrodt mineral deposits
- **LOD pipeline** — 4-tier mesh decimation, billboard LOD, horizon clipmap
- **Material system** — stochastic tiling (Heitz 2019 histogram-preserving blend), Quixel asset ingest, per-biome splatmap weights
- **Shadow/lighting** — 4-cascade shadow clipmap (EXR export), god-ray hints at ridge notches, cloud shadow masks
- **Navmesh export** — JSON navmesh from walkable terrain regions
- **Unity export** — RAW heightmap + JSON config bridge

## Requirements

- Python ≥ 3.11
- numpy ≥ 1.26.0
- opensimplex ≥ 0.4.5
- scipy (optional — enables fast-path for EDT, box filter, Gaussian smoothing)
- Pillow (optional — visual diff tooling)
- Blender 4.x (runtime; not required for unit tests)

## Installation

```bash
# Install the package and dev tooling
pip install -e '.[dev]'

# veilbreakers-mcp is not on PyPI — install from the monorepo
pip install "git+https://github.com/Sharks820/veilbreakers-gamedev-toolkit#subdirectory=Tools/mcp-toolkit"
```

## Running Tests

```bash
python -m pytest veilbreakers_terrain/tests/ -q
```

> **Note:** Tests mock `bpy`, `bmesh`, and `mathutils` via `conftest.py`, so the full suite runs outside Blender. Avoid running the entire suite at once on low-memory machines — individual test files run in < 2 s each.

## Linting

```bash
python -m ruff check .
```

## Blender Live Testing

1. Open Blender 4.x and switch to the **Scripting** workspace.
2. Load or symlink this repository into Blender's addon path.
3. Enable **VeilBreakers Terrain** in *Edit → Preferences → Add-ons*.
4. In any 3-D viewport, open the **N panel → VeilBreakers** tab.
5. Adjust biome/noise parameters and press **Generate Terrain** to run the full procedural pipeline in-session.

## Repository Layout

```
veilbreakers_terrain/
  handlers/          # All terrain pass implementations
  tests/             # pytest suite (~90+ test files)
  presets/           # YAML terrain presets
  contracts/         # Pass contract definitions
scripts/             # Audit, grading, and CI tooling
docs/
  aaa-audit/         # Grade audit CSVs and rubrics
```

## Grade Audit

Every public callable is graded against the AAA rubric in `docs/aaa-audit/GRADES_VERIFIED.csv`. Run the audit tooling with:

```bash
python scripts/build_master_callable_audit.py
python scripts/callable_census_gate.py
```

Target: all callables at B or higher. Current status: all graded functions are at B+/A- or above after R9 consensus.
