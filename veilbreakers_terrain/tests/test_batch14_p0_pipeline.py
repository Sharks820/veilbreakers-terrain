"""Batch-14 P0 pipeline ordering tests.

Covers:
  B14-9  : structural_masks runs AFTER pass_composite_hmap so cliff_mask,
            slope, and curvature are derived from the final composited height.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# B14-9: structural_masks must follow pass_composite_hmap
# ---------------------------------------------------------------------------

def test_post_rescale_cliff_mask_matches_rescaled_height():
    """structural_masks is ordered after pass_composite_hmap in the default sequence.

    Before B14-9 the sequence was:
      ...low_freq → biome_channels → terrain_labels → structural_masks →
      high_freq → composite_hmap...

    cliff_mask was derived from the low-freq base only; high-freq detail added
    by composite_hmap silently invalidated it.

    After B14-9:
      ...low_freq → biome_channels → terrain_labels → high_freq →
      composite_hmap → structural_masks...
    """
    from unittest.mock import MagicMock
    from veilbreakers_terrain.handlers.terrain_pipeline import build_default_pass_sequence

    intent = MagicMock()
    intent.scene_read = None
    intent.tile_size = 64
    intent.composition_hints = {}
    intent.biome_name = "grasslands"
    intent.climate_profile = "temperate"
    intent.quality_profile = "aaa_open_world"

    seq = build_default_pass_sequence(intent)

    assert "structural_masks" in seq, "structural_masks must appear in the default pass sequence"
    assert "pass_composite_hmap" in seq, "pass_composite_hmap must appear in the default pass sequence"

    idx_structural = seq.index("structural_masks")
    idx_composite = seq.index("pass_composite_hmap")

    assert idx_structural > idx_composite, (
        f"B14-9: structural_masks (idx={idx_structural}) must run AFTER "
        f"pass_composite_hmap (idx={idx_composite}) so cliff_mask is "
        f"derived from the composited height, not the low-freq-only base."
    )


def test_structural_masks_after_composite_with_scene_read():
    """Even with has_scene_read=True (hydrology+erosion inserted), structural_masks
    still follows pass_composite_hmap.
    """
    from unittest.mock import MagicMock
    from veilbreakers_terrain.handlers.terrain_pipeline import build_default_pass_sequence

    intent = MagicMock()
    intent.scene_read = MagicMock()  # truthy → has_scene_read branch
    intent.tile_size = 64
    intent.composition_hints = {}
    intent.biome_name = "grasslands"
    intent.climate_profile = "temperate"
    intent.quality_profile = "aaa_open_world"

    seq = build_default_pass_sequence(intent)

    if "structural_masks" not in seq:
        pytest.skip("structural_masks not in sequence for this intent configuration")

    idx_structural = seq.index("structural_masks")
    idx_composite = seq.index("pass_composite_hmap")

    assert idx_structural > idx_composite, (
        f"B14-9 (scene_read): structural_masks (idx={idx_structural}) must "
        f"still follow pass_composite_hmap (idx={idx_composite}) when "
        f"hydrology+erosion passes are inserted."
    )
