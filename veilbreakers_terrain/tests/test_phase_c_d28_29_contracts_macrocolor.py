"""Phase C D28-29 — pass contracts + macro_color 8-channel + 14-biome palette.

Pins the spec PR #21 / #31 / #32 deliverables produced on
``feat/phase-c-d28-29-contracts-macrocolor``:

PR #21 — pass contracts:
    * ``emit_overhang_meshes`` declares its (cliff_mesh_specs, cave_mesh_specs)
      reads as ``optional_channels`` (was empty).
    * ``emit_particle_systems`` declares ``particle_emitter_specs`` as
      ``optional_channels`` (was empty).
    * ``waterfalls`` declares ``particle_emitter_specs`` in both
      ``produces_channels`` and ``overrides`` (was missing entirely).
    * ``quixel_ingest`` declares all 6 channels it actually writes
      (splatmap_weights_layer + macro_color + roughness_variation +
      terrain_normals + terrain_ao + terrain_displacement) in BOTH
      ``produces_channels`` and ``overrides`` (was only splatmap).

PR #31 — macro_color 8-channel consumed declaration:
    * ``compute_macro_color`` reads 8 channels (height + biome_id + wetness +
      erosion_amount + deposition_amount + albedo_shift_rgb +
      snow_line_factor + strata_cross_section) but the PassResult was
      declaring ``consumed_channels=("height",)``. Pin the new tuple.

PR #32 — DARK_FANTASY_PALETTE 14-biome:
    * Palette extended from biome IDs 0-7 to 0-13 (14 entries).
    * ``BIOME_BUCKET_MAP_18_TO_14`` maps every canonical biome name in
      ``terrain_biome_registry.CANONICAL_BIOME_IDS`` (18 entries) onto
      exactly one of the 14 palette buckets.
"""

from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_biome_registry import (
    CANONICAL_BIOME_IDS,
)
from veilbreakers_terrain.handlers.terrain_macro_color import (
    BIOME_BUCKET_MAP_18_TO_14,
    DARK_FANTASY_PALETTE,
    DEFAULT_BIOME_ID,
    MACRO_COLOR_CONSUMED_CHANNELS,
    PALETTE_BUCKET_COUNT,
    compute_macro_color,
    pass_macro_color,
)
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    PassDefinition,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _build_stack(tile_size: int = 32, seed: int = 7) -> TerrainMaskStack:
    rng = np.random.default_rng(seed)
    xs = np.linspace(0.0, 1.0, tile_size + 1)
    ys = np.linspace(0.0, 1.0, tile_size + 1)
    xv, yv = np.meshgrid(xs, ys)
    height = (
        20.0
        + 80.0 * (xv * yv)
        + 5.0 * rng.standard_normal((tile_size + 1, tile_size + 1))
    )
    stack = TerrainMaskStack(
        tile_size=tile_size,
        cell_size=2.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height.astype(np.float64),
    )
    stack.height_min_m = float(height.min())
    stack.height_max_m = float(height.max())
    return stack


def _build_state(stack: TerrainMaskStack) -> TerrainPipelineState:
    extent = float(stack.tile_size) * float(stack.cell_size)
    region = BBox(0.0, 0.0, extent, extent)
    intent = TerrainIntentState(
        seed=7,
        region_bounds=region,
        tile_size=stack.tile_size,
        cell_size=stack.cell_size,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


def _registered_passes() -> "dict[str, PassDefinition]":
    """Trigger full registration and return the registry dict."""
    from veilbreakers_terrain.handlers import terrain_master_registrar
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
    )
    terrain_master_registrar.register_all_terrain_passes()
    return dict(TerrainPassController.PASS_REGISTRY)


# ---------------------------------------------------------------------------
# PR #21 — pass contracts
# ---------------------------------------------------------------------------


class TestPR21PassContracts:
    """Spec PR #21 — declare missing requires/produces/overrides."""

    def test_emit_overhang_meshes_declares_optional_inputs(self) -> None:
        registry = _registered_passes()
        pd = registry["emit_overhang_meshes"]
        # Bridge pass: no hard inputs but declares the two opaque channels
        # it consults via stack.get(...). Spec PR #21 row.
        assert "cliff_mesh_specs" in pd.optional_channels
        assert "cave_mesh_specs" in pd.optional_channels

    def test_emit_particle_systems_declares_optional_input(self) -> None:
        registry = _registered_passes()
        pd = registry["emit_particle_systems"]
        assert "particle_emitter_specs" in pd.optional_channels

    def test_waterfalls_produces_particle_emitter_specs(self) -> None:
        registry = _registered_passes()
        pd = registry["waterfalls"]
        # Spec PR #21: waterfalls writes ``particle_emitter_specs`` (line
        # ~2523) but never declared the channel. Producer→consumer DAG edge
        # must be explicit.
        assert "particle_emitter_specs" in pd.produces_channels
        # And declared as override since emit_particle_systems may also be
        # treated as a secondary writer in some configurations.
        assert "particle_emitter_specs" in pd.overrides

    def test_quixel_ingest_declares_all_six_channels_written(self) -> None:
        registry = _registered_passes()
        pd = registry["quixel_ingest"]
        # Spec PR #21 row: quixel writes up to 6 channels but the previous
        # declaration only listed ``splatmap_weights_layer``. Of the 6, only
        # splatmap is GUARANTEED-populated (single-layer fallback when no
        # assets ingested — see pass body line ~931-945). The other 5 are
        # CONDITIONAL on the Megascans asset shipping that texture, so they
        # belong in ``overrides`` (declares secondary-writer intent without
        # requiring population) rather than ``produces_channels`` (which the
        # contract checker would assert at exit).
        all_six = {
            "splatmap_weights_layer",
            "macro_color",
            "roughness_variation",
            "terrain_normals",
            "terrain_ao",
            "terrain_displacement",
        }
        # Splatmap is the one always-populated output.
        assert "splatmap_weights_layer" in pd.produces_channels, (
            "quixel_ingest guarantees splatmap_weights_layer (fallback "
            "writes single-layer placeholder when no assets ingested)"
        )
        # All 6 declared as overrides — closes spec gap "Quixel ingest
        # declares only `splatmap_weights_layer`; overrides incomplete".
        assert all_six.issubset(set(pd.overrides)), (
            f"quixel_ingest must declare all 6 channels as overrides; "
            f"missing: {all_six - set(pd.overrides)}"
        )

    def test_no_pass_has_completely_empty_contracts(self) -> None:
        """Spec PR #21 ≥60 of 74 passes declare contracts. After this PR,
        every default-sequence pass declares either requires_channels,
        produces_channels, or optional_channels (no all-empty triples)."""
        registry = _registered_passes()
        empty = []
        for nm, pd in registry.items():
            if (
                not pd.requires_channels
                and not pd.produces_channels
                and not pd.optional_channels
                and not pd.overrides
            ):
                empty.append(nm)
        # Strict: zero passes with all-empty contracts.
        assert not empty, (
            f"Phase C D28-29 PR #21: passes with no contract declarations: "
            f"{empty}. Add requires/produces/optional/overrides per spec."
        )


# ---------------------------------------------------------------------------
# PR #31 — macro_color consumed_channels = 8 (not 1)
# ---------------------------------------------------------------------------


class TestPR31MacroColorConsumedChannels:
    """Spec PR #31 — declared inputs must match what the pass actually reads."""

    def test_consumed_channels_tuple_is_eight(self) -> None:
        # Spec row PR #31 enumerates the canonical 8-tuple.
        assert MACRO_COLOR_CONSUMED_CHANNELS == (
            "height",
            "biome_id",
            "wetness",
            "erosion_amount",
            "deposition_amount",
            "albedo_shift_rgb",
            "snow_line_factor",
            "strata_cross_section",
        )

    def test_pass_macro_color_consumed_channels_pinned(self) -> None:
        stack = _build_stack()
        state = _build_state(stack)
        result = pass_macro_color(state, region=None)
        # PassResult MUST report the 8-channel consumed set per spec.
        assert tuple(result.consumed_channels) == MACRO_COLOR_CONSUMED_CHANNELS

    def test_macro_color_pass_definition_optional_channels(self) -> None:
        registry = _registered_passes()
        pd = registry["macro_color"]
        # 7 of the 8 consumed channels are soft reads → optional_channels.
        # ``height`` stays in requires_channels (compute_macro_color raises
        # without it).
        assert pd.requires_channels == ("height",)
        for ch in MACRO_COLOR_CONSUMED_CHANNELS[1:]:  # skip 'height'
            assert ch in pd.optional_channels, (
                f"macro_color must declare '{ch}' as optional_channels"
            )

    def test_macro_color_output_remains_rgb_3(self) -> None:
        """User-task ambiguity reconciliation: spec interpretation is
        ``8 input channels declared``, NOT ``output expanded to 8 channels``.
        Macro_color stays (H, W, 3) RGB — the Unity shader ABI is unchanged.
        """
        stack = _build_stack()
        result = compute_macro_color(stack)
        assert result.ndim == 3
        assert result.shape[2] == 3, (
            "macro_color must remain RGB-3 — see file docstring "
            "'User-task ambiguity reconciliation' for rationale."
        )
        assert result.dtype == np.float32

    def test_macro_color_no_silent_keyerror_on_missing_optional(self) -> None:
        """All 7 soft-read channels must be guarded — pass runs cleanly
        on a height-only stack."""
        stack = _build_stack()
        # Sanity: only height set, everything else absent.
        for ch in MACRO_COLOR_CONSUMED_CHANNELS[1:]:
            assert stack.get(ch) is None
        # Must not raise.
        result = compute_macro_color(stack)
        assert np.all(np.isfinite(result))


# ---------------------------------------------------------------------------
# PR #32 — DARK_FANTASY_PALETTE 14-biome
# ---------------------------------------------------------------------------


class TestPR32FourteenBiomePalette:
    """Spec PR #32 — palette extended from 8 to 14 entries."""

    def test_palette_bucket_count_constant(self) -> None:
        assert PALETTE_BUCKET_COUNT == 14

    def test_palette_has_fourteen_entries(self) -> None:
        assert len(DARK_FANTASY_PALETTE) == 14, (
            f"DARK_FANTASY_PALETTE must have 14 entries (biome IDs 0-13); "
            f"got {len(DARK_FANTASY_PALETTE)}"
        )

    def test_palette_keys_are_ints_0_to_13(self) -> None:
        assert set(DARK_FANTASY_PALETTE.keys()) == set(range(14))

    def test_palette_values_are_rgb_in_unit_range(self) -> None:
        for bid, rgb in DARK_FANTASY_PALETTE.items():
            assert len(rgb) == 3, f"biome {bid} has {len(rgb)}-tuple, want 3"
            for c in rgb:
                assert 0.0 <= c <= 1.0, (
                    f"biome {bid} RGB out of [0,1]: {rgb}"
                )

    def test_default_biome_id_resolves(self) -> None:
        # Spec acceptance: "fallback documented as biome-0 umber, not grey".
        assert DEFAULT_BIOME_ID == 0
        assert DEFAULT_BIOME_ID in DARK_FANTASY_PALETTE
        # Biome 0 is umber (<= 0.4 on each channel).
        rgb = DARK_FANTASY_PALETTE[DEFAULT_BIOME_ID]
        assert max(rgb) < 0.4, f"biome 0 must be umber-tone, got {rgb}"

    # ----- 18-canonical → 14-bucket mapping --------------------------------

    def test_every_canonical_biome_maps_to_a_bucket(self) -> None:
        """Spec PR #32: every canonical 18-biome must map to exactly one
        of the 14 palette buckets (no fall-through to default umber)."""
        for canonical in CANONICAL_BIOME_IDS:
            assert canonical in BIOME_BUCKET_MAP_18_TO_14, (
                f"Canonical biome '{canonical}' not in "
                f"BIOME_BUCKET_MAP_18_TO_14"
            )

    def test_bucket_map_does_not_contain_aliases(self) -> None:
        """The bucket map must key on canonical IDs only — no aliases."""
        for k in BIOME_BUCKET_MAP_18_TO_14:
            assert k in CANONICAL_BIOME_IDS, (
                f"Bucket map contains non-canonical key '{k}'"
            )

    def test_bucket_map_is_18_entries(self) -> None:
        """Every canonical biome appears exactly once."""
        assert len(BIOME_BUCKET_MAP_18_TO_14) == len(CANONICAL_BIOME_IDS) == 18

    def test_every_bucket_index_is_valid(self) -> None:
        """Every bucket value must be a valid palette key (0..13)."""
        for canonical, bucket in BIOME_BUCKET_MAP_18_TO_14.items():
            assert 0 <= bucket < PALETTE_BUCKET_COUNT, (
                f"Biome '{canonical}' maps to bucket {bucket} outside "
                f"[0, {PALETTE_BUCKET_COUNT})"
            )
            assert bucket in DARK_FANTASY_PALETTE, (
                f"Biome '{canonical}' maps to bucket {bucket} which has "
                f"no DARK_FANTASY_PALETTE entry"
            )

    def test_some_buckets_shared_across_canonical_biomes(self) -> None:
        """Spec semantics: 18 canonical → 14 buckets means at least 4 biomes
        share a bucket with another biome (18 - 14 = 4 collapses minimum).
        """
        from collections import Counter
        counts = Counter(BIOME_BUCKET_MAP_18_TO_14.values())
        sharers = [b for b, c in counts.items() if c > 1]
        # At least 4 buckets host >1 canonical biome (collapse count >= 4).
        total_extra = sum(c - 1 for c in counts.values() if c > 1)
        assert total_extra >= 4, (
            f"Spec expects 18→14 collapse (≥4 shared bucket assignments); "
            f"got {total_extra}. Sharers: {sharers}"
        )


# ---------------------------------------------------------------------------
# Integration smoke: macro_color end-to-end with biome_id channel populated
# ---------------------------------------------------------------------------


class TestMacroColorIntegration:
    """Verify macro_color paints from biome_id under the new 14-bucket palette."""

    def test_biome_id_drives_palette_lookup(self) -> None:
        stack = _build_stack(tile_size=16)
        # Set biome_id to bucket 8 (volcanic) across the whole tile.
        biome = np.full((17, 17), 8, dtype=np.int32)
        stack.set("biome_id", biome, "test")

        result = compute_macro_color(stack)
        # Volcanic palette is iron-red: R > G and R > B in the source spec.
        # Other modulations (altitude/erosion) shift but R-dominance
        # should still hold on average because no other channel is set.
        mean_r = float(result[..., 0].mean())
        mean_g = float(result[..., 1].mean())
        mean_b = float(result[..., 2].mean())
        assert mean_r > mean_g, (
            f"Volcanic bucket 8 should produce R-dominant tones; "
            f"got R={mean_r:.3f} G={mean_g:.3f} B={mean_b:.3f}"
        )

    def test_palette_id_5_snowcap_bright(self) -> None:
        stack = _build_stack(tile_size=16)
        biome = np.full((17, 17), 5, dtype=np.int32)
        stack.set("biome_id", biome, "test")
        result = compute_macro_color(stack)
        # Snowcap palette is the brightest entry.
        assert float(result.mean()) > 0.4, (
            "Snowcap bucket 5 should average bright (>0.4)"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
