# R11 B-Floor Live Test Plan

Target: separate product-facing terrain risks from support-helper audit noise before live testing.

Important: this plan does not prove every callable is independently AAA B. Strict below-B rows remain in `R11_STRICT_BELOW_B_REMAINING.csv`; the B-floor CSV only shows rows still below B after support-helper reclassification.

## Required Live Scenes

- River and stream scene: carved bed below water surface, asymmetric banks, shelves, wet margins, flow direction colors, seam continuity across adjacent tiles.
- Mountain/cliff scene: macro mountain massing, cliff strata/fracture/talus masks, foothill-to-flatland transition, no blocky height noise.
- Road/path scene: terrain deformation, shoulders, drainage cuts, worn material blend, path spline proof across slopes and flats.
- Scatter/forest scene: forest core, edge, sparse transition, grass species variation, slope/moisture gating, no abrupt biome cut lines.
- Material scene: triplanar cliff/wet rock proof, macro color breakup, sediment/wetness borders, texture stretch check.

## Verification Gates

- Regenerate callable wiring: `python scripts\scan_callable_wiring.py`.
- Regenerate R11 audit: `python scripts\build_r11_research_aaa_callable_audit.py`.
- Focused tests: `python -m pytest veilbreakers_terrain\tests\test_aaa_water_scatter.py veilbreakers_terrain\tests\test_terrain_wiring_integration.py veilbreakers_terrain\tests\test_terrain_pipeline_smoke.py veilbreakers_terrain\tests\test_visual_testing_readiness.py -q`.
- Remaining remediation CSV must be reviewed at `docs\aaa-audit\R11_BELOW_B_REMEDIATION_BACKLOG.csv`.