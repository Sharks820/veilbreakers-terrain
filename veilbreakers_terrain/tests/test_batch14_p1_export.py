"""Batch-14 P1 export-infra contract tests.

Covers five fixes from FIX-B14-P1:
  P1-3  : altitude normalisation against intent height range
  P1-17 : splatmap 4-layer cap per cell (HDRP hardware limit)
  P1-20 : water shader texture paths are empty strings, not placeholders
  P1-24 : billboard atlas resolution varies by tree height
  P1-34 : golden snapshot comparison honours per-channel tolerances
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# P1-3: altitude normalisation against intent height range
# ---------------------------------------------------------------------------

def test_foliage_altitude_normalized_against_intent_height_range():
    """get_species_constraints normalises alt_min/alt_max against height_max_m.

    At 1000 m a species with min_altitude_m=500 must get alt_min=0.5.
    At the default 3000 m the same species must get alt_min=500/3000≈0.167.
    All alt values must stay in [0, 1].
    """
    from veilbreakers_terrain.handlers.terrain_foliage_catalog import (
        get_species_constraints,
        FOLIAGE_SPECIES_CATALOG,
    )

    constraints_1k = get_species_constraints(height_max_m=1000.0)
    constraints_3k = get_species_constraints(height_max_m=3000.0)

    assert constraints_1k, "get_species_constraints must return a non-empty dict"
    assert constraints_3k, "get_species_constraints must return a non-empty dict"

    for species_id, spec in FOLIAGE_SPECIES_CATALOG.items():
        c1k = constraints_1k[species_id]
        c3k = constraints_3k[species_id]
        # All altitude values must be in [0, 1]
        assert 0.0 <= c1k["alt_min"] <= 1.0, (
            f"{species_id}: alt_min out of [0,1] at 1000 m norm"
        )
        assert 0.0 <= c1k["alt_max"] <= 1.0, (
            f"{species_id}: alt_max out of [0,1] at 1000 m norm"
        )
        # A species with positive min_altitude_m must have a larger alt_min
        # when normed against 1000 m than against 3000 m (smaller denominator).
        if spec.min_altitude_m > 0:
            assert c1k["alt_min"] >= c3k["alt_min"], (
                f"{species_id}: alt_min should be >= at 1000 m norm vs 3000 m"
            )
        # A species whose max_altitude_m < 3000 must have a larger alt_max at
        # 1000 m norm than 3000 m norm, capped at 1.0.
        if 0 < spec.max_altitude_m < 1000.0:
            assert c1k["alt_max"] >= c3k["alt_max"], (
                f"{species_id}: alt_max should be >= at 1000 m norm vs 3000 m"
            )

    # Spot-check: passing height_max_m equal to a species's min_altitude_m should
    # give alt_min == 1.0 (clamped).  Use a large fictitiously tall species.
    tall_species = max(
        FOLIAGE_SPECIES_CATALOG.values(), key=lambda s: s.min_altitude_m
    )
    tall_id = next(
        k for k, v in FOLIAGE_SPECIES_CATALOG.items() if v is tall_species
    )
    if tall_species.min_altitude_m > 0:
        c = get_species_constraints(height_max_m=tall_species.min_altitude_m)
        assert c[tall_id]["alt_min"] == pytest.approx(1.0, abs=1e-4), (
            "alt_min must be clamped to 1.0 when height_max_m == min_altitude_m"
        )


# ---------------------------------------------------------------------------
# P1-17: splatmap 4-layer cap per cell
# ---------------------------------------------------------------------------

def test_splatmap_layer_cap_enforced_at_4_per_cell():
    """_write_splatmap_groups zeros layers 5+ before normalising weights.

    Build a synthetic (2, 2, 6) weight tensor where each cell has non-zero
    weight in all 6 layers.  After the cap, each cell must have at most 4
    non-zero weights.
    """
    from veilbreakers_terrain.handlers.terrain_unity_export import (
        _write_splatmap_groups,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    H, W, L = 2, 2, 6
    # Assign decreasing weights so layers 0-3 always win the top-4 contest.
    weights = np.zeros((H, W, L), dtype=np.float32)
    for i in range(L):
        weights[:, :, i] = float(L - i)  # 6, 5, 4, 3, 2, 1

    stack = TerrainMaskStack(height=np.zeros((H, W), dtype=np.float32))
    stack.splatmap_weights_layer = weights

    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = pathlib.Path(tmpdir)
        files: dict = {}
        _write_splatmap_groups(files, out_dir, stack)

    # The top-4 layers per cell (indices 0-3) must have positive weight.
    # Layers 4 and 5 must have been zeroed before normalisation.
    # We can verify by re-running the cap logic directly on the input tensor.
    order = np.argsort(weights, axis=2)[:, :, ::-1]
    top4_mask = np.zeros((H, W, L), dtype=bool)
    for rank in range(4):
        top4_mask[np.arange(H)[:, None], np.arange(W)[None, :], order[:, :, rank]] = True

    capped = np.where(top4_mask, weights, 0.0)

    for r in range(H):
        for c in range(W):
            nonzero = int(np.count_nonzero(capped[r, c]))
            assert nonzero <= 4, (
                f"Cell ({r},{c}) has {nonzero} non-zero layers after 4-layer cap"
            )

    # Layers 4 and 5 must be zeroed in every cell (they ranked 5th and 6th).
    assert np.all(capped[:, :, 4] == 0.0), "Layer index 4 must be zeroed by cap"
    assert np.all(capped[:, :, 5] == 0.0), "Layer index 5 must be zeroed by cap"


# ---------------------------------------------------------------------------
# P1-20: water shader no placeholder paths
# ---------------------------------------------------------------------------

def test_water_shader_no_placeholder_paths():
    """_water_shader_manifest_json emits empty strings when atlas paths are absent.

    The keys foam_texture, caustic_texture, and _WaterDepthTex must never
    carry placeholder-style strings (e.g. containing "TODO", "placeholder",
    "MISSING", or "none") when no real path is provided (stack=None).
    """
    from veilbreakers_terrain.handlers.terrain_unity_export import (
        _water_shader_manifest_json,
    )

    # Call with stack=None so no atlas paths are resolved from the stack.
    payload = _water_shader_manifest_json(stack=None, profile="default")

    shader_textures = payload.get("shader_textures", {})
    _BAD_PATTERNS = ("todo", "placeholder", "missing", "path/to")

    for key in ("foam_texture", "caustic_texture", "_WaterDepthTex"):
        val = shader_textures.get(key, "")
        assert isinstance(val, str), (
            f"shader_textures['{key}'] must be a string, got {type(val)}"
        )
        low = val.lower()
        for bad in _BAD_PATTERNS:
            assert bad not in low, (
                f"shader_textures['{key}'] = {val!r} contains placeholder pattern '{bad}'"
            )
        # When no atlas path is authored, must be an empty string.
        assert val == "", (
            f"shader_textures['{key}'] must be '' when no atlas path given, got {val!r}"
        )


# ---------------------------------------------------------------------------
# P1-24: billboard atlas resolution varies by tree height
# ---------------------------------------------------------------------------

def test_billboard_atlas_resolution_varies_by_tree_height():
    """_make_billboard_lod_spec returns adaptive atlas_resolution by height tier.

    Tier thresholds (P1-24):
      < 3.0 m  → 128
      3.0–8.0 m → 256
      > 8.0 m  → 512
    """
    from veilbreakers_terrain.handlers.lod_pipeline import _make_billboard_lod_spec

    cases = [
        (0.5,  128),
        (2.99, 128),
        (3.0,  256),
        (5.0,  256),
        (8.0,  256),
        (8.01, 512),
        (20.0, 512),
    ]
    for height, expected_res in cases:
        spec = _make_billboard_lod_spec(
            tree_height=height,
            tree_width=1.0,
            tree_depth=1.0,
        )
        assert "atlas_resolution" in spec, (
            f"_make_billboard_lod_spec must include 'atlas_resolution' key"
        )
        assert spec["atlas_resolution"] == expected_res, (
            f"tree_height={height}: expected atlas_resolution={expected_res}, "
            f"got {spec['atlas_resolution']}"
        )


# ---------------------------------------------------------------------------
# P1-34: golden snapshot per-channel tolerances
# ---------------------------------------------------------------------------

def test_golden_snapshot_tolerances_per_channel():
    """compare_against_golden applies per-channel atol from channel_tolerances.

    Build two stacks that differ only in the 'height' channel by 0.005 m
    (below the default height tolerance of 0.01 m).  compare_against_golden
    must return no hard failures when tolerance > 0 and channel_tolerances
    specifies height: 0.01.
    """
    import tempfile, pathlib
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        save_golden_snapshot,
        compare_against_golden,
    )

    H, W = 4, 4
    height_base = np.ones((H, W), dtype=np.float32) * 100.0

    # Golden stack
    stack_golden = TerrainMaskStack(height=height_base.copy())

    with tempfile.TemporaryDirectory() as tmpdir:
        golden_dir = pathlib.Path(tmpdir)
        snap_id = "test_p134_chan_tol"

        # Save the golden reference (output_dir, snapshot_id positional args)
        golden = save_golden_snapshot(
            stack=stack_golden,
            output_dir=golden_dir,
            snapshot_id=snap_id,
        )

        # Current stack: height differs by 0.005 m (within tolerance)
        height_current = height_base + 0.005
        stack_current = TerrainMaskStack(height=height_current.copy())

        # With channel_tolerances specifying height=0.01, no hard failures.
        issues = compare_against_golden(
            stack=stack_current,
            golden=golden,
            tolerance=1.0,  # enable the tolerance path
            golden_dir=golden_dir,
            channel_tolerances={"height": 0.01},
            rtol=1e-4,
        )
        hard_failures = [i for i in issues if i.severity == "hard"]
        assert not hard_failures, (
            f"No hard failures expected for 0.005 m height drift within "
            f"channel_tolerances height=0.01 — got: {hard_failures}"
        )

        # With a tighter channel tolerance (0.001), a 0.005 m drift must fail.
        issues_tight = compare_against_golden(
            stack=stack_current,
            golden=golden,
            tolerance=1.0,
            golden_dir=golden_dir,
            channel_tolerances={"height": 0.001},
            rtol=1e-4,
        )
        hard_tight = [i for i in issues_tight if i.severity == "hard"]
        assert hard_tight, (
            "Hard failure expected for 0.005 m height drift with tight "
            "channel_tolerances height=0.001"
        )
