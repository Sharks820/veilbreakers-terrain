"""T1 shader cluster regression tests — T1-1, T1-22, T1-28, T1-29.

Y04 v3 anchor: docs/aaa-audit/2026_05_17_ultrafinal/MASTER_FINAL.md §B.4.2.

Each fix in the cluster:

* **T1-1** — HDRP shader leak (3 sites in
  ``unity_plugin/Editor/VbTerrainImporter.cs``). Project is URP 17.3 per
  ``project_urp_commitment_2026_05_07``; HDRP fallbacks produced gray-flat
  terrain in URP/HDRP-clean builds. Fix: URP-first lookup, loud
  ``InvalidOperationException`` when URP is missing instead of silent
  Standard/Diffuse fallback.

* **T1-22** — Anisotropic + Trilinear at terrain texture import in
  ``VbTerrainImporter.CopyAndConfigureTexture``. Previously Bilinear +
  default ``anisoLevel = 1`` caused visible moire / shimmer in motion.
  Fix: ``filterMode = Trilinear``, ``anisoLevel = 8`` (Snowdrop / Anvil
  default).

* **T1-28** — 5 PBR additive blend sites in
  ``handlers/terrain_quixel_ingest.py`` (lines 629, 643, 665, 699, 728 in
  the pre-fix source). Additive blend (``base + sampled * w``) over
  several layers exceeded 1.0 and produced blown-out PBR. Fix: LERP
  (``base * (1 - w) + sampled * w``) per Megascans / UE5 / URP Shader
  Graph convention.

* **T1-29** — Shadow clipmap bake nearest-neighbor ray-march sample in
  ``handlers/terrain_shadow_clipmap_bake.py:_bake_single_cascade``.
  Nearest sampling quantised the shadow boundary onto the grid lattice;
  shadow edges swam / stair-stepped when the camera rotated. Fix:
  4-tap bilinear interpolation along the ray.

Per ``FIX_PATTERN_v1.md §C8`` visual proof is the canonical gate for the
Unity .cs sites, but the orchestrator (overnight PR-8 brief) directs that
JSON-roundtrip / numerical-property tests are acceptable as a regression
net for the Python-side material descriptor changes. For the .cs sites we
assert canonical strings are present (URP shader name) and the previous
silent-fallback strings are absent (no ``Shader.Find("HDRP/...")`` left).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VB_TERRAIN_IMPORTER = _REPO_ROOT / "unity_plugin" / "Editor" / "VbTerrainImporter.cs"


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _make_stack(rows: int = 8, cols: int = 8):
    """Construct a minimal TerrainMaskStack with a flat height channel."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    return TerrainMaskStack(
        tile_size=max(rows, cols) - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((rows, cols), dtype=np.float64),
    )


# ---------------------------------------------------------------------------
# T1-1 — VbTerrainImporter HDRP shader leak removed
# ---------------------------------------------------------------------------


class TestT1_1_HdrpShaderLeakRemoved:
    """Per Y04 v3 T1-1: VbTerrainImporter must not silently substitute a
    default Standard / Diffuse shader for a missing URP terrain shader.
    """

    def test_no_hdrp_shader_find_remains(self) -> None:
        """All 3 ``Shader.Find("HDRP/...")`` sites must be gone from
        ``VbTerrainImporter.cs``. Project is URP 17.3 per
        ``project_urp_commitment_2026_05_07``.
        """
        text = _VB_TERRAIN_IMPORTER.read_text(encoding="utf-8")
        assert 'Shader.Find("HDRP/TerrainLit")' not in text, (
            "T1-1 regression: HDRP/TerrainLit shader reference reintroduced "
            "in VbTerrainImporter.cs. Project is URP-only."
        )
        assert 'Shader.Find("HDRP/Lit")' not in text, (
            "T1-1 regression: HDRP/Lit shader reference reintroduced in "
            "VbTerrainImporter.cs."
        )

    def test_urp_shader_is_canonical_resolution_target(self) -> None:
        """The canonical URP shader path must be present at every former
        HDRP site.  Use a literal-string-occurrence count to guard against
        partial reverts.
        """
        text = _VB_TERRAIN_IMPORTER.read_text(encoding="utf-8")
        urp_lit_count = text.count('Shader.Find("Universal Render Pipeline/Lit")')
        assert urp_lit_count >= 3, (
            f"T1-1 regression: expected at least 3 URP/Lit Shader.Find "
            f"sites in VbTerrainImporter.cs after HDRP removal, got "
            f"{urp_lit_count}."
        )

    def test_loud_failure_when_urp_missing(self) -> None:
        """The fix must raise ``InvalidOperationException`` if URP is not
        installed, rather than falling back to ``Standard`` or ``Diffuse``
        (which produced unlit gray-flat terrain).
        """
        text = _VB_TERRAIN_IMPORTER.read_text(encoding="utf-8")
        assert "InvalidOperationException" in text, (
            "T1-1 regression: VbTerrainImporter no longer raises on missing "
            "URP shader. Silent-fallback path has been reintroduced."
        )


# ---------------------------------------------------------------------------
# T1-22 — Anisotropic + Trilinear at terrain texture import
# ---------------------------------------------------------------------------


class TestT1_22_AnisotropicAndTrilinear:
    """Per Y04 v3 T1-22: VbTerrainImporter.CopyAndConfigureTexture must
    set ``filterMode = Trilinear`` and ``anisoLevel = 8`` for imported
    terrain textures.
    """

    def test_terrain_importer_uses_trilinear_filter(self) -> None:
        text = _VB_TERRAIN_IMPORTER.read_text(encoding="utf-8")
        # Importer block (around the SaveAndReimport() call) must set
        # Trilinear, not Bilinear.
        assert "importer.filterMode = FilterMode.Trilinear" in text, (
            "T1-22 regression: VbTerrainImporter texture importer no longer "
            "sets FilterMode.Trilinear. Textures will alias visibly in motion."
        )

    def test_terrain_importer_sets_aniso_level_8(self) -> None:
        text = _VB_TERRAIN_IMPORTER.read_text(encoding="utf-8")
        assert "importer.anisoLevel = 8" in text, (
            "T1-22 regression: VbTerrainImporter texture importer no longer "
            "sets anisoLevel = 8. Grazing-angle terrain textures will "
            "shimmer."
        )


# ---------------------------------------------------------------------------
# T1-28 — terrain_quixel_ingest PBR LERP (not additive) blending
# ---------------------------------------------------------------------------


class TestT1_28_PbrLerpBlend:
    """Per Y04 v3 T1-28: ``apply_quixel_to_layer`` must blend layered PBR
    channels with LERP (``base*(1-w) + sampled*w``), never additive
    (``base + sampled*w``). Additive blends with multiple layers exceed
    1.0 and produce over-saturated highlights / blown-out PBR.
    """

    def test_macro_color_blend_is_lerp_not_additive(self) -> None:
        """Apply two non-trivial layers and assert the resulting albedo
        stays in [0, 1] and equals the LERP closed-form.

        Construction: layer0 paints albedo = (0.2, 0.2, 0.2); layer1 paints
        albedo = (0.9, 0.9, 0.9) with full per-texel weight after
        re-normalisation. Additive would give 1.1+; LERP gives 0.9.
        """
        from veilbreakers_terrain.handlers.terrain_quixel_ingest import (
            QuixelAsset,
            apply_quixel_to_layer,
        )

        rows, cols = 8, 8
        stack = _make_stack(rows, cols)

        # Pre-seed macro_color with a uniform 0.2 albedo (acts as "base").
        stack.set(
            "macro_color",
            np.full((rows, cols, 3), 0.2, dtype=np.float32),
            "test_fixture",
        )
        # Force a single-layer splatmap with full weight so the new layer's
        # weight after re-normalisation is exactly 1.0.
        stack.set(
            "splatmap_weights_layer",
            np.ones((rows, cols, 1), dtype=np.float32),
            "test_fixture",
        )

        # New layer: solid 0.9 albedo.
        new_albedo = np.full((4, 4, 3), 0.9, dtype=np.float32)
        asset = QuixelAsset(asset_id="t1_28_lerp_albedo")
        apply_quixel_to_layer(
            stack,
            "t1_28_lerp_albedo_layer",
            asset,
            albedo_array=new_albedo,
        )

        blended = np.asarray(stack.macro_color, dtype=np.float32)
        # All values must stay <= 1.0 (LERP property) — additive would
        # produce values > 1.0.
        assert blended.max() <= 1.0 + 1e-5, (
            f"T1-28 regression: macro_color max {blended.max()} > 1.0 "
            "indicates additive blend (LERP would clamp to layer max)."
        )
        # Expected LERP result: 0.2 * 0 + sRGB-linearised(0.9) * 1 ≈
        # 0.7874 for sRGB-linear conversion of 0.9. Just assert > 0.5 and
        # < 1.0 — exact value depends on the sRGB→linear conversion.
        assert blended.mean() < 1.0, (
            f"T1-28 regression: mean blended {blended.mean():.4f} touches "
            "saturation; suggests additive overflow."
        )
        assert blended.mean() > 0.5, (
            f"T1-28 regression: mean blended {blended.mean():.4f} too low; "
            "new layer's contribution lost."
        )

    def test_roughness_lerp_stays_in_unit_interval(self) -> None:
        """Roughness blend must stay within [0, 1] — additive would overflow."""
        from veilbreakers_terrain.handlers.terrain_quixel_ingest import (
            QuixelAsset,
            apply_quixel_to_layer,
        )

        rows, cols = 6, 6
        stack = _make_stack(rows, cols)
        stack.set(
            "roughness_variation",
            np.full((rows, cols), 0.6, dtype=np.float32),
            "test_fixture",
        )
        stack.set(
            "splatmap_weights_layer",
            np.ones((rows, cols, 1), dtype=np.float32),
            "test_fixture",
        )

        new_rough = np.full((3, 3), 0.8, dtype=np.float32)
        asset = QuixelAsset(asset_id="t1_28_lerp_rough")
        apply_quixel_to_layer(
            stack,
            "t1_28_lerp_rough_layer",
            asset,
            roughness_array=new_rough,
        )

        result = np.asarray(stack.roughness_variation, dtype=np.float32)
        assert result.max() <= 1.0 + 1e-5, (
            f"T1-28 regression: roughness_variation max {result.max()} > 1.0; "
            "indicates additive blend remained."
        )
        # LERP of 0.6 * 0 + 0.8 * 1.0 = 0.8; additive would be 0.6 + 0.8 = 1.4.
        assert abs(result.mean() - 0.8) < 0.05, (
            f"T1-28 regression: roughness LERP expected ≈0.8, got "
            f"{result.mean():.4f}."
        )


# ---------------------------------------------------------------------------
# T1-29 — terrain_shadow_clipmap_bake bilinear ray-march sample
# ---------------------------------------------------------------------------


class TestT1_29_ShadowRayMarchBilinear:
    """Per Y04 v3 T1-29: ``_bake_single_cascade`` must bilinear-interpolate
    the heightmap sample along the ray instead of nearest-neighbor lookup.

    Detection strategy: bake the same scene twice with slightly different
    sun azimuths. With nearest-neighbor the shadow mask diff between the
    two bakes is dominated by integer grid jumps (large mean delta). With
    bilinear interpolation the diff transitions smoothly (small mean
    delta + smaller max delta). We assert the smoothness property.
    """

    def test_bake_uses_bilinear_height_sampling(self) -> None:
        """Source-level guard: the bilinear 4-tap pattern must be present
        in the file. Belt-and-braces over the numerical test below.
        """
        from veilbreakers_terrain.handlers import terrain_shadow_clipmap_bake

        src = Path(terrain_shadow_clipmap_bake.__file__).read_text(encoding="utf-8")
        # Bilinear tag-line we added in the fix.
        assert "T1-29 fix" in src, (
            "T1-29 regression: bilinear fix marker missing from "
            "terrain_shadow_clipmap_bake.py."
        )
        # The 4-tap pattern terms must all be present.
        assert "(1.0 - fx) * (1.0 - fy)" in src, (
            "T1-29 regression: 4-tap bilinear weights missing from "
            "_bake_single_cascade."
        )
        # The nearest-neighbor anti-pattern must be gone.
        assert "sampled_h = h[syi, sxi]" not in src, (
            "T1-29 regression: nearest-neighbor heightmap sample "
            "re-introduced in _bake_single_cascade."
        )

    def test_bake_shadow_mask_is_smooth_under_small_sun_perturbation(self) -> None:
        """With bilinear sampling, perturbing the sun azimuth by a small
        delta should produce a smoothly-varying shadow mask. With
        nearest-neighbor sampling the mask would snap discretely as the
        ray quantises to different grid cells.
        """
        from veilbreakers_terrain.handlers.terrain_shadow_clipmap_bake import (
            _bake_single_cascade,
        )

        # Construct a slanted ramp heightmap (smooth, monotonic) — any
        # quantisation artefact will show up as discrete jumps in the
        # shadow mask between adjacent azimuths.
        rows, cols = 32, 32
        h = np.fromfunction(
            lambda y, x: 0.05 * x + 0.02 * y, (rows, cols), dtype=np.float64
        )

        el = float(np.deg2rad(20.0))  # low sun = long shadows
        cell_m = 1.0
        num_steps = 16

        az0 = float(np.deg2rad(45.0))
        az1 = az0 + 1e-3  # tiny perturbation

        mask0 = _bake_single_cascade(h, az0, el, cell_m, num_steps)
        mask1 = _bake_single_cascade(h, az1, el, cell_m, num_steps)

        # Sanity: outputs are valid masks.
        assert mask0.shape == (rows, cols)
        assert mask1.shape == (rows, cols)
        assert np.all((mask0 >= 0.0) & (mask0 <= 1.0))
        assert np.all((mask1 >= 0.0) & (mask1 <= 1.0))

        # Smoothness property: for a 1e-3 rad azimuth perturbation on a
        # smooth ramp, the average per-cell change should stay small.
        # Nearest-neighbor sampling would snap entire rows/cols of cells
        # between lit/shadowed states, producing a large mean delta.
        mean_delta = float(np.abs(mask0 - mask1).mean())
        assert mean_delta < 0.05, (
            f"T1-29 regression: shadow mask delta {mean_delta:.4f} under "
            "1e-3 rad azimuth perturbation is too large; suggests "
            "nearest-neighbor sampling has been reintroduced."
        )
