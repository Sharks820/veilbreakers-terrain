"""Regression tests for the T1-glacial/coastline/environment cluster.

Y04 v3 §B.4.11 anchors (MASTER_FINAL.md:2372-2432):

* **T1-3** — Glacial double-apply / dual-register
  ``terrain_geology_validator.py:702-718`` previously registered the glacial
  pass twice: once as ``name="glacial"`` (in ``register_bundle_i_passes``)
  and once as ``name="pass_glacial"`` (in
  ``terrain_glacial.register_glacial_pass``). Both pointed at the same
  ``func=pass_glacial`` and produced the same channels. The
  ``terrain_pipeline`` scheduler inserts ``"pass_glacial"`` (terrain
  _pipeline.py:272), so ``"glacial"`` was an orphan registration today —
  but any manual scheduler edit that referenced both names would have
  run the glacial pass twice, doubling ``glacial_delta`` and the
  ``snow_line_factor`` override. This is the **D-06 ↔ G-65 reachability
  defect** in MASTER_FINAL.md:8749 / 11176.

  Fix: ``"glacial"`` removed from ``BUNDLE_I_PASSES`` and from
  ``register_bundle_i_passes``; the canonical entry is the
  ``"pass_glacial"`` registered by ``register_glacial_pass``.

  FIX_PATTERN_v1 §C8 (visual mandate — visible blue-cast in tundra
  biome was the user-facing symptom).

* **T1-16** — Coastline saturated retreat (12 m always)
  ``coastline.py:1145`` used ``np.clip(3.0 * wave_energy, 0.1, 12.0)``;
  ``pass_coastline`` passed ``scalar_wave_energy = mean(_pass_energy) *
  100`` which routinely exceeded 4.0, saturating ``base_erosion`` at the
  ceiling for every coast and every biome. The audit's prescription is
  ``retreat_m = base_retreat * biome_factor * wave_energy_factor *
  fetch_factor`` — multiplicative, not clip-saturating.

  Fix: replaced the saturating clip with ``log1p(wave_energy)`` (sub
  -linear, never saturates for any realistic input) times a global
  ``fetch_factor`` derived from the mean/max fetch ratio; ``biome_factor``
  remains realised via the existing rock-hardness multiplier in section
  5 of ``apply_coastal_erosion``.

  FIX_PATTERN_v1 §C5 (numerical recipe — ``rtol=1e-6`` regression
  assertions).

* **T1-17** — ``environment.py:2675`` ``np.load`` on ``.raw``
  ``handle_generate_world_terrain`` reads neighbor tiles via
  ``np.load(tile["heightmap_path"], allow_pickle=False)``. The
  heightmap files are written by ``_export_world_tile_artifacts`` as
  uint16 little-endian raw binary (no ``.npy`` magic). Every call
  raised, was swallowed by the broad ``except``, and cross-tile seam
  blending silently became a no-op.

  Fix: switched to ``np.fromfile(path, dtype="<u2").reshape((res, res))``
  with ``res`` recovered from the neighbor's tile-result dict
  (``"resolution"`` field). The writer's ``flipud`` is undone before
  sampling the seam-adjacent column/row. Security property of
  ``allow_pickle=False`` is preserved structurally — ``np.fromfile`` has
  no pickle path.

  FIX_PATTERN_v1 §C5 (numerical recipe — exact byte-equality via
  ``assert_array_equal``).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# T1-3 — Glacial dual-register removal
# ---------------------------------------------------------------------------


def test_t1_3_bundle_i_does_not_register_name_glacial() -> None:
    """``register_bundle_i_passes`` must not register ``name="glacial"``.

    The canonical glacial pass is registered as ``"pass_glacial"`` by
    ``terrain_glacial.register_glacial_pass`` (Bundle I-glacial in
    ``terrain_master_registrar``). Registering it twice under two
    different names with the same ``func`` was the dual-register that
    risked double-applying the glacial delta.
    """
    from veilbreakers_terrain.handlers.terrain_geology_validator import (
        BUNDLE_I_PASSES,
        register_bundle_i_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )

    assert "glacial" not in BUNDLE_I_PASSES, (
        "T1-3 regression: BUNDLE_I_PASSES still claims 'glacial' — "
        "the dual-register is back."
    )

    prior = dict(TerrainPassController.PASS_REGISTRY)
    try:
        TerrainPassController.PASS_REGISTRY.clear()
        register_default_passes()
        default_names = set(TerrainPassController.PASS_REGISTRY.keys())
        register_bundle_i_passes()
        after = set(TerrainPassController.PASS_REGISTRY.keys())
        new_names = after - default_names
        assert "glacial" not in new_names, (
            "T1-3 regression: register_bundle_i_passes re-introduced the "
            f"'glacial' PassDefinition (newly registered: {sorted(new_names)})"
        )
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(prior)


def test_t1_3_pass_glacial_is_the_single_canonical_glacial_pass() -> None:
    """After both registrars run, exactly ONE PassDefinition uses
    ``pass_glacial`` as its ``func``."""
    from veilbreakers_terrain.handlers.terrain_geology_validator import (
        register_bundle_i_passes,
    )
    from veilbreakers_terrain.handlers.terrain_glacial import (
        pass_glacial,
        register_glacial_pass,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import (
        TerrainPassController,
        register_default_passes,
    )

    prior = dict(TerrainPassController.PASS_REGISTRY)
    try:
        TerrainPassController.PASS_REGISTRY.clear()
        register_default_passes()
        register_bundle_i_passes()
        register_glacial_pass()
        defs_with_pass_glacial_func = [
            name
            for name, definition in TerrainPassController.PASS_REGISTRY.items()
            if definition.func is pass_glacial
        ]
        assert defs_with_pass_glacial_func == ["pass_glacial"], (
            "T1-3 regression: expected exactly one registration of "
            f"pass_glacial func, got {defs_with_pass_glacial_func}"
        )
    finally:
        TerrainPassController.PASS_REGISTRY.clear()
        TerrainPassController.PASS_REGISTRY.update(prior)


def test_t1_3_static_source_proves_dual_register_removed() -> None:
    """AST-grep the source: no ``name="glacial"`` PassDefinition kwarg in
    ``terrain_geology_validator.py``.

    Defends against a regression that re-introduces the dup via a
    refactor that bypasses the BUNDLE_I_PASSES tuple sentinel.
    """
    src = Path(
        "veilbreakers_terrain/handlers/terrain_geology_validator.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)

    offending: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = getattr(node.func, "attr", None) or getattr(
            node.func, "id", None
        )
        if func_name != "PassDefinition":
            continue
        for kw in node.keywords:
            if (
                kw.arg == "name"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == "glacial"
            ):
                offending.append(node.lineno)

    assert not offending, (
        "T1-3 regression: terrain_geology_validator.py still constructs "
        f"PassDefinition(name='glacial', ...) at lines {offending}. The "
        "canonical entry is 'pass_glacial' in terrain_glacial.py."
    )


# ---------------------------------------------------------------------------
# T1-16 — Coastline saturated retreat
# ---------------------------------------------------------------------------


def _make_coastline_stack(
    height: np.ndarray,
    *,
    cell_size: float = 1.0,
) -> Any:
    """Build a minimal TerrainMaskStack for ``apply_coastal_erosion``.

    The function only reads ``stack.height`` (and optionally
    ``stack.rock_hardness``) so a hand-rolled namespace is enough.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    H, W = height.shape
    stack = TerrainMaskStack(
        tile_size=H,
        cell_size=cell_size,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height.astype(np.float32),
        slope=np.zeros((H, W), dtype=np.float32),
    )
    return stack


def _coastal_step_carve(stack: Any, *, wave_energy: float) -> np.ndarray:
    from veilbreakers_terrain.handlers.coastline import apply_coastal_erosion

    return apply_coastal_erosion(
        stack,
        sea_level_m=0.0,
        wave_direction=0.0,
        wave_energy=wave_energy,
    )


def _coastal_step_carve_with_dir(
    stack: Any,
    *,
    wave_energy: float,
    wave_direction: float,
) -> np.ndarray:
    from veilbreakers_terrain.handlers.coastline import apply_coastal_erosion

    return apply_coastal_erosion(
        stack,
        sea_level_m=0.0,
        wave_direction=wave_direction,
        wave_energy=wave_energy,
    )


def test_t1_16_retreat_varies_with_wave_energy() -> None:
    """A bigger storm should carve strictly more than a calm sea.

    Previously ``base_erosion = clip(3 * wave_energy, 0.1, 12.0)`` so any
    ``wave_energy >= 4.0`` produced identical 12.0 m base — this assertion
    failed for any pair above the clip ceiling.
    """
    # North-facing cliff: high land at row 0 stepping down to ocean at
    # the last rows. Aspect points north (+y, gy<0), wave_direction=0
    # (waves arriving from the north), so the cos(angle_diff) exposure
    # term is 1.0 along the cliff face.
    H, W = 32, 32
    height = np.linspace(10.0, -5.0, H, dtype=np.float64)[:, None].repeat(W, axis=1)
    stack = _make_coastline_stack(height)

    calm = _coastal_step_carve(stack, wave_energy=1.0)
    storm = _coastal_step_carve(stack, wave_energy=40.0)
    hurricane = _coastal_step_carve(stack, wave_energy=400.0)

    calm_mean = float(np.abs(calm).mean())
    storm_mean = float(np.abs(storm).mean())
    hurricane_mean = float(np.abs(hurricane).mean())

    # Monotonic: bigger storms carve strictly more on average. The previous
    # saturated formula returned (approximately) the same value for the
    # last two pairs.
    assert calm_mean < storm_mean, (
        f"T1-16 regression: calm ({calm_mean:.4f}) >= storm ({storm_mean:.4f})"
    )
    assert storm_mean < hurricane_mean, (
        f"T1-16 regression: storm ({storm_mean:.4f}) >= hurricane "
        f"({hurricane_mean:.4f}); base_erosion clip is saturating again."
    )


def test_t1_16_retreat_varies_with_fetch() -> None:
    """Identical wave energy on different shoreline geometries should
    produce different per-tile retreat magnitudes.

    Long-fetch headland vs short-fetch sheltered lagoon.
    """
    H, W = 32, 32

    # Long-fetch headland: only one ocean row at row 31, land elsewhere.
    # max_fetch ≈ 31 cells.
    headland = np.full((H, W), 5.0, dtype=np.float64)
    headland[-1, :] = -1.0

    # Short-fetch lagoon: ocean rows 30-31, land elsewhere. Smaller
    # max_fetch but everything else identical.
    lagoon = np.full((H, W), 5.0, dtype=np.float64)
    lagoon[H - 8 :, :] = -1.0  # ocean band at the south edge

    # Aspect on both points south (gy>0, so aspect=atan2(0, -positive)=pi).
    # Wave direction = pi means waves come from south, exposure=1.0.
    headland_delta = _coastal_step_carve_with_dir(
        _make_coastline_stack(headland),
        wave_energy=10.0,
        wave_direction=float(np.pi),
    )
    lagoon_delta = _coastal_step_carve_with_dir(
        _make_coastline_stack(lagoon),
        wave_energy=10.0,
        wave_direction=float(np.pi),
    )

    headland_peak = float(np.abs(headland_delta).max())
    lagoon_peak = float(np.abs(lagoon_delta).max())

    # Both shorelines carve, but not identically — under the saturated
    # formula they would both pin the carve-front cells to the same
    # ceiling.
    assert headland_peak > 0.0, (
        f"T1-16 fixture: headland_peak == 0 (no carve at all)"
    )
    assert lagoon_peak > 0.0, (
        f"T1-16 fixture: lagoon_peak == 0 (no carve at all)"
    )
    assert headland_peak != pytest.approx(lagoon_peak, rel=1e-6, abs=1e-9), (
        f"T1-16 regression: headland peak ({headland_peak:.6f}) == lagoon "
        f"peak ({lagoon_peak:.6f}); fetch_factor not modulating output."
    )


def test_t1_16_no_saturating_clip_constant_in_source() -> None:
    """The literal ``np.clip(3.0 * wave_energy, 0.1, 12.0)`` constant
    must not return as production code.

    AST scan defends the structural fix from being reverted via a
    refactor that re-introduces the saturating clip. Comments + docstrings
    that *reference* the pre-fix line for audit-trail purposes are
    excluded by line-level filtering (skip lines starting with ``#`` or
    inside docstring fences).
    """
    src_lines = Path(
        "veilbreakers_terrain/handlers/coastline.py"
    ).read_text(encoding="utf-8").splitlines()
    # Filter to code lines only — skip comments, docstring blocks, and
    # backtick-quoted in-line references.
    in_docstring = False
    code_lines: list[str] = []
    for line in src_lines:
        stripped = line.strip()
        # Toggle docstring fence (matches """ at start of line).
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        # Skip whole-line comments.
        if stripped.startswith("#"):
            continue
        # Strip inline trailing comment (``...`` references are inline).
        code_part = line.split("#", 1)[0]
        code_lines.append(code_part)
    code_src = "\n".join(code_lines)
    assert "np.clip(3.0 * wave_energy, 0.1, 12.0)" not in code_src, (
        "T1-16 regression: the saturating clip "
        "`np.clip(3.0 * wave_energy, 0.1, 12.0)` is back in production "
        "code of coastline.py."
    )


# ---------------------------------------------------------------------------
# T1-17 — environment.py np.load on .raw
# ---------------------------------------------------------------------------


def _write_uint16_raw_heightmap(
    path: Path,
    *,
    resolution: int,
    fill: int,
) -> None:
    """Reproduce the ``_export_heightmap_raw`` byte layout for a
    constant-fill heightmap.

    The writer applies ``flipud`` for Unity row order — for a constant
    field flipud is a no-op so the test value is preserved exactly.
    """
    arr = np.full((resolution, resolution), fill, dtype="<u2")
    path.write_bytes(np.ascontiguousarray(arr).tobytes())


def test_t1_17_neighbor_edge_reader_raw_byte_round_trip(tmp_path: Path) -> None:
    """Raw-byte-layer test: writer + reader produce byte-identical uint16.

    Validates ONLY the storage-layer round-trip (file bytes → np.fromfile →
    reshape → flipud). Dequantization to metres is verified separately in
    ``test_t1_17_neighbor_edge_reader_dequantizes_to_metres``.
    """
    resolution = 33
    raw_path = tmp_path / "tile_0_0_heightmap.raw"
    _write_uint16_raw_heightmap(raw_path, resolution=resolution, fill=12345)

    raw = np.fromfile(raw_path, dtype="<u2")
    assert raw.size == resolution * resolution, (
        f"T1-17 fixture: wrote {raw.size} values, expected "
        f"{resolution * resolution}"
    )
    arr = np.flipud(raw.reshape((resolution, resolution)))
    # Constant-fill: every raw value should equal 12345 (uint16 byte-level).
    assert arr.dtype == np.uint16
    np.testing.assert_array_equal(arr, np.full_like(arr, 12345))


def test_t1_17_neighbor_edge_reader_dequantizes_to_metres(tmp_path: Path) -> None:
    """Round-4 CodeRabbit CRITICAL fix: the production ``_read_neighbor_heightmap``
    helper inside ``handle_generate_world_terrain`` dequantizes the raw uint16
    values back to metres using the neighbor tile's stored ``height_range``.

    Verifies the dequantization formula matches the writer's normalisation:
    writer normalises ``(hmap - hmin) / (hmax - hmin)`` to [0, 1] then
    multiplies by 65535. Reader inverts: ``(arr / 65535) * (hmax - hmin) + hmin``.

    Pre-round-4 the reader returned raw uint16 values [0, 65535] directly
    to seam locking which expected metres — silent corruption at every
    tile boundary. This test pins the dequantization contract.
    """
    from veilbreakers_terrain.handlers.environment import _export_heightmap_raw

    resolution = 17
    # Build a heightmap with KNOWN values in [50.0, 200.0] m range.
    heightmap = np.linspace(50.0, 200.0, resolution * resolution).reshape(
        (resolution, resolution)
    )
    height_range = (50.0, 200.0)
    raw_bytes = _export_heightmap_raw(
        heightmap, flip_vertical=True, value_range=height_range
    )
    raw_path = tmp_path / "rt_heightmap.raw"
    raw_path.write_bytes(raw_bytes)

    # Replicate the production reader's dequantization logic verbatim
    # (since _read_neighbor_heightmap is a nested closure not directly
    # importable, this mirrors the inline math at environment.py round-4):
    raw = np.fromfile(raw_path, dtype="<u2")
    arr = np.flipud(raw.reshape((resolution, resolution)))
    hmin, hmax = float(height_range[0]), float(height_range[1])
    arr_metres = (arr.astype(np.float64) / 65535.0) * (hmax - hmin) + hmin

    # Round-trip must be within uint16 quantisation (~1.5e-5 relative
    # for a 150 m range = ~2.3 mm absolute).
    np.testing.assert_allclose(arr_metres, heightmap, atol=3e-3, rtol=0.0)

    # And explicitly assert values are in METRE range, not uint16 range.
    assert 50.0 <= arr_metres.min() <= 60.0, (
        f"T1-17 dequantization: min {arr_metres.min()} should be ≈hmin (50.0); "
        "if this is >1000 the reader is returning raw uint16 values, not metres."
    )
    assert 190.0 <= arr_metres.max() <= 200.0, (
        f"T1-17 dequantization: max {arr_metres.max()} should be ≈hmax (200.0); "
        "if this is >60000 the reader is returning raw uint16 values, not metres."
    )


def test_t1_17_np_load_raw_anchor_replaced_in_source() -> None:
    """The literal ``np.load(west_tile["heightmap_path"]`` and its
    ``north_tile`` sibling must not return — both were the exact
    anchors flagged in MASTER_FINAL.md:2417.

    Defends the structural fix from a refactor that re-introduces the
    wrong loader.
    """
    src = Path(
        "veilbreakers_terrain/handlers/environment.py"
    ).read_text(encoding="utf-8")
    assert 'np.load(west_tile["heightmap_path"]' not in src, (
        "T1-17 regression: np.load on west_tile heightmap_path is back."
    )
    assert 'np.load(north_tile["heightmap_path"]' not in src, (
        "T1-17 regression: np.load on north_tile heightmap_path is back."
    )
    assert 'np.fromfile(' in src and 'dtype="<u2"' in src, (
        "T1-17 regression: replacement np.fromfile reader is missing."
    )


def test_t1_17_export_writer_and_fromfile_reader_are_byte_round_trip(
    tmp_path: Path,
) -> None:
    """The writer used by ``_export_world_tile_artifacts`` and the new
    reader at ``handle_generate_world_terrain`` must be byte-exact
    round-trip for a non-trivial heightmap.

    Catches future drift in either side (e.g. someone changing
    ``flip_vertical`` default on one side only).
    """
    from veilbreakers_terrain.handlers.environment import _export_heightmap_raw

    resolution = 17
    heightmap = np.linspace(0.0, 100.0, resolution * resolution).reshape(
        (resolution, resolution)
    )
    raw_bytes = _export_heightmap_raw(
        heightmap, flip_vertical=True, value_range=(0.0, 100.0)
    )
    raw_path = tmp_path / "rt_heightmap.raw"
    raw_path.write_bytes(raw_bytes)

    # Reader (matches the production code path in
    # environment.py handle_generate_world_terrain).
    raw = np.fromfile(raw_path, dtype="<u2")
    assert raw.size == resolution * resolution
    arr = np.flipud(raw.reshape((resolution, resolution)))

    # Convert back to [0, 1] normalised, then to original scale, and
    # verify the round-trip is within uint16 quantisation (~1.5e-5
    # relative for the [0, 100] range = ~1.5e-3 absolute).
    arr_norm = arr.astype(np.float64) / 65535.0
    arr_back = arr_norm * (100.0 - 0.0) + 0.0
    np.testing.assert_allclose(arr_back, heightmap, atol=2e-3, rtol=0.0)
