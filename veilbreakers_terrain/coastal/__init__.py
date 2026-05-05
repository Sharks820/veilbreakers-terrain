"""VeilBreakers Coastal biome — fresh-build AAA pipeline.

Fresh build (not an audit) per user direction 2026-05-04. Modules here
do not depend on the legacy pipeline; they construct a Coastal node from
first principles and produce render-proven Blender scenes plus a
Unity-importable bundle.

Layered top-down:
    shoreline_sdf       : Bezier curve -> signed distance field
    landform_zones      : low beach / backshore / headland / gullies / inland ridge
    pbr_terrain_shader  : Brucks height-blend + Ben Golus triplanar
    water_shader_eevee  : Gerstner waves + depth foam + Eevee Next refraction
    lighting_atmosphere : sun + Nishita sky + volumetric mist + irradiance volume
    vegetation_pipeline : L-Py / Modular Tree / OpenScatter
    wind_pivot_painter  : PP2.0 vertex data for grass + tree sway
    props_hunyuan       : Hunyuan3D-2.1 hero props (driftwood / boulders / reeds)
    adaptive_mesh       : curve-conforming shoreline strip + cliff hero meshes
    coastal_build       : top-level orchestrator
    unity_export        : RAW16 heightmap + splat + water JSON + GLBs + manifest

Plan: docs/plans/2026-05-04-001-feat-coastal-aaa-perfection-plan.md.
"""

from __future__ import annotations
