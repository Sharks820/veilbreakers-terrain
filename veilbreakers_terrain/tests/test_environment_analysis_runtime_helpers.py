"""Direct tests for atmosphere, gameplay, rhythm, and audio analysis helpers."""

from __future__ import annotations

import numpy as np
import pytest


def _stack(height: np.ndarray | None = None):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    h = (
        np.asarray(height, dtype=np.float32)
        if height is not None
        else np.zeros((5, 5), dtype=np.float32)
    )
    return TerrainMaskStack(
        tile_size=h.shape[0],
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )


def test_atmospheric_noise_helpers_are_deterministic_and_bounded():
    from veilbreakers_terrain.handlers.atmospheric_volumes import (
        _grad2,
        _lerp,
        _perlin2,
        _permute,
        _smooth,
    )

    assert _permute(17, seed=3) == _permute(17, seed=3)
    assert _permute(17, seed=3) != _permute(18, seed=3)
    assert _smooth(0.0) == pytest.approx(0.0)
    assert _smooth(1.0) == pytest.approx(1.0)
    assert _lerp(2.0, 6.0, 0.25) == pytest.approx(3.0)
    assert _grad2(0, 0.25, 0.5) == pytest.approx(0.75)
    assert _perlin2(0.0, 0.0, seed=5) == pytest.approx(0.0)
    assert -1.0 <= _perlin2(0.37, 0.82, seed=5) <= 1.0


def test_gameplay_zone_score_helpers_return_valid_ranges_and_metrics():
    from veilbreakers_terrain.handlers.terrain_gameplay_zones import (
        _compute_choke_score,
        _compute_cover_score,
        _compute_gameplay_score_metrics,
        _compute_sky_exposure,
        _compute_vantage_score,
        _label_zones,
    )

    h = np.zeros((5, 5), dtype=np.float64)
    h[1:4, 1:4] = 2.0
    h[2, 2] = 0.0
    slope_deg = np.zeros_like(h)
    slope_deg[:, 0] = 45.0
    mask = np.zeros((5, 5), dtype=bool)
    mask[0, 0] = True
    mask[0, 1] = True
    mask[4, 4] = True

    labels = _label_zones(mask, eight_connected=False)
    cover = _compute_cover_score(h, cell_size=1.0)
    exposure = _compute_sky_exposure(h)
    choke = _compute_choke_score(h, slope_deg)
    vantage = _compute_vantage_score(h, slope_deg)
    metrics = _compute_gameplay_score_metrics(h, slope_deg)

    assert labels.max() == 2
    assert cover[2, 2] > 0.0
    assert np.all((0.0 <= exposure) & (exposure <= 1.0))
    assert np.all((0.0 <= choke) & (choke <= 1.0))
    assert np.all((0.0 <= vantage) & (vantage <= 1.0))
    assert {"cover_score_mean", "choke_cells_gt05", "vantage_cells_gt07"} <= set(metrics)


def test_rhythm_helpers_score_feature_type_salience_distances_and_gradients():
    from veilbreakers_terrain.handlers.terrain_rhythm import (
        _feature_salience,
        _feature_type,
        _monotonic_gradient,
        _nn_distances,
        _ripley_k_proxy,
    )

    features = [
        {"feature_kind": "cave", "salience": 0.9, "position": (0.0, 0.0)},
        {"kind": "arch", "weight": 0.4, "position": (3.0, 4.0)},
    ]
    pts = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [3.0, 0.0],
            [6.0, 0.0],
            [10.0, 0.0],
            [15.0, 0.0],
            [21.0, 0.0],
            [28.0, 0.0],
        ],
        dtype=np.float64,
    )
    radii = np.array([1.5, 5.0], dtype=np.float64)

    assert _feature_type(features[0]) == "cave"
    assert _feature_type(features[1]) == "arch"
    assert _feature_salience(features[0]) == pytest.approx(0.9)
    assert _feature_salience(features[1]) == pytest.approx(0.4)
    assert np.allclose(_nn_distances(np.array([[0.0, 0.0], [3.0, 4.0]])), 5.0)
    assert _ripley_k_proxy(pts, area=1000.0, radii=radii).shape == radii.shape
    assert np.isfinite(_ripley_k_proxy(pts, area=1000.0, radii=radii)).all()
    assert -1.0 <= _monotonic_gradient(pts, axis=0) <= 1.0


def test_audio_zone_helpers_filter_boundaries_rt60_echo_classification_and_zone_list():
    from veilbreakers_terrain.handlers.terrain_audio_zones import (
        AudioReverbClass,
        _audio_cc_filter,
        _classify_raster,
        _cliff_echo_delay,
        _component_boundary_polygon,
        _sabine_rt60,
        compute_audio_zone_list,
    )

    mask = np.zeros((4, 4), dtype=bool)
    mask[0, 0] = True
    mask[2:4, 2:4] = True
    cleaned = _audio_cc_filter(mask, min_cells=2)
    label_arr = np.zeros((4, 4), dtype=np.int32)
    label_arr[2:4, 2:4] = 1
    boundary = _component_boundary_polygon(cleaned, label_arr, cid=1)
    delay = _cliff_echo_delay((4, 4), cleaned, cell_size=2.0)

    stack = _stack(np.zeros((4, 4), dtype=np.float32))
    stack.water_surface = np.ones((4, 4), dtype=np.float32)
    classes = _classify_raster(stack)
    zones = compute_audio_zone_list(stack)

    assert not cleaned[0, 0]
    assert cleaned[2:4, 2:4].all()
    assert len(boundary) >= 3
    assert 0.05 <= _sabine_rt60(16, 1.0, 2.0, 0.5) <= 10.0
    assert delay.shape == (4, 4)
    assert delay.dtype == np.float32
    assert np.all(classes == AudioReverbClass.WATER_NEAR.value)
    assert zones
    assert zones[0]["reverb_preset"] == "water_near"


# ---------------------------------------------------------------------------
# Wave-10 audio-zone upgrades — vectorised EDT fallback, enriched zone payload,
# multi-class classifier coverage, Wwise CSV exporter, pipeline wiring.
# ---------------------------------------------------------------------------


def _make_stack_large(tile_size: int = 24, seed: int = 7):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    rng = np.random.default_rng(seed)
    xs = np.linspace(0.0, 1.0, tile_size + 1)
    ys = np.linspace(0.0, 1.0, tile_size + 1)
    xv, yv = np.meshgrid(xs, ys)
    height = (
        50.0
        + 400.0 * (xv ** 2 + yv ** 2)
        + 30.0 * rng.standard_normal((tile_size + 1, tile_size + 1))
    ).astype(np.float64)
    return TerrainMaskStack(
        tile_size=tile_size,
        cell_size=2.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )


def _attach_slope(stack) -> None:
    h = np.asarray(stack.height, dtype=np.float64)
    gy, gx = np.gradient(h, float(stack.cell_size))
    stack.set("slope", np.arctan(np.sqrt(gx * gx + gy * gy)), "test_fixture")


def _build_state(tile_size: int = 24, seed: int = 7):
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainPipelineState,
    )

    stack = _make_stack_large(tile_size=tile_size, seed=seed)
    _attach_slope(stack)
    region = BBox(
        0.0, 0.0,
        float(tile_size * stack.cell_size),
        float(tile_size * stack.cell_size),
    )
    intent = TerrainIntentState(
        seed=seed,
        region_bounds=region,
        tile_size=tile_size,
        cell_size=stack.cell_size,
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# Upgrade A — _cliff_echo_delay (vectorised chamfer EDT fallback)
# ---------------------------------------------------------------------------


def test_cliff_echo_delay_chamfer_fallback_matches_scipy_within_tolerance():
    from veilbreakers_terrain.handlers.terrain_audio_zones import _cliff_echo_delay

    try:
        import scipy  # noqa: F401
    except ImportError:
        pytest.skip("SciPy not installed — cannot compare to ground truth")

    cliff = np.zeros((16, 16), dtype=bool)
    cliff[3, 4] = True
    cliff[10, 11] = True

    scipy_delay = _cliff_echo_delay((16, 16), cliff, cell_size=1.0, _force_no_scipy=False)
    chamfer_delay = _cliff_echo_delay((16, 16), cliff, cell_size=1.0, _force_no_scipy=True)

    assert scipy_delay.shape == chamfer_delay.shape == (16, 16)
    max_delay = float(scipy_delay.max())
    err = float(np.abs(scipy_delay - chamfer_delay).max())
    # Borgefors 3-4 chamfer has theoretical max error ≈ 4.4 % of the exact
    # Euclidean distance; allow 6 % to absorb rounding at small grid sizes.
    assert err <= max(0.06 * max_delay, 1e-3), (
        f"chamfer fallback deviates {err:.6f} s from SciPy ground truth "
        f"(max_delay={max_delay:.6f} s)"
    )


def test_cliff_echo_delay_chamfer_fallback_emits_warning(caplog):
    from veilbreakers_terrain.handlers.terrain_audio_zones import _cliff_echo_delay

    cliff = np.zeros((6, 6), dtype=bool)
    cliff[0, 0] = True
    with caplog.at_level("WARNING", logger="veilbreakers_terrain.handlers.terrain_audio_zones"):
        _ = _cliff_echo_delay((6, 6), cliff, cell_size=1.0, _force_no_scipy=True)
    assert any(
        "chamfer EDT fallback" in rec.getMessage() for rec in caplog.records
    ), "fallback path must emit a warning, not silently degrade"


def test_cliff_echo_delay_scipy_path_is_physical():
    from veilbreakers_terrain.handlers.terrain_audio_zones import _cliff_echo_delay

    cliff = np.zeros((10, 10), dtype=bool)
    cliff[0, 0] = True
    delay = _cliff_echo_delay((10, 10), cliff, cell_size=2.0)
    assert delay.shape == (10, 10)
    assert delay.dtype == np.float32
    assert float(delay[0, 0]) == 0.0
    assert delay[9, 9] > 0.0
    assert np.isfinite(delay).all()


def test_chamfer_distance_cells_basic():
    from veilbreakers_terrain.handlers.terrain_audio_zones import _chamfer_distance_cells

    cliff = np.zeros((5, 5), dtype=bool)
    cliff[2, 2] = True
    dist = _chamfer_distance_cells(cliff)
    assert float(dist[2, 2]) == 0.0
    assert abs(float(dist[2, 3]) - 1.0) < 0.01
    # Diagonal distance = 4/3 ≈ 1.333 (chamfer 3-4 kernel).
    assert abs(float(dist[3, 3]) - 4.0 / 3.0) < 0.01


# ---------------------------------------------------------------------------
# Upgrade B — _classify_raster multi-class coverage
# ---------------------------------------------------------------------------


def test_classify_raster_cave_requires_low_sky_exposure_when_ao_present():
    from veilbreakers_terrain.handlers.terrain_audio_zones import (
        AudioReverbClass,
        _classify_raster,
    )

    stack = _make_stack_large()
    _attach_slope(stack)
    cliff = np.zeros_like(stack.height, dtype=np.float64)
    conc = np.zeros_like(stack.height, dtype=np.float64)
    ao_high = np.zeros_like(stack.height, dtype=np.float64)
    cliff[5:10, 5:10] = 1.0
    conc[5:10, 5:10] = 0.8
    ao_high[5:10, 5:10] = 0.9  # heavily occluded ⇒ cave
    stack.set("cliff_candidate", cliff, "test")
    stack.set("concavity", conc, "test")
    stack.set("ambient_occlusion_bake", ao_high.astype(np.float32), "test")

    cls = _classify_raster(stack)
    assert (cls[5:10, 5:10] == AudioReverbClass.CAVE.value).any()


def test_classify_raster_cave_rejected_when_sky_exposure_high():
    from veilbreakers_terrain.handlers.terrain_audio_zones import (
        AudioReverbClass,
        _classify_raster,
    )

    stack = _make_stack_large()
    _attach_slope(stack)
    cliff = np.zeros_like(stack.height, dtype=np.float64)
    conc = np.zeros_like(stack.height, dtype=np.float64)
    ao_low = np.zeros_like(stack.height, dtype=np.float64)
    cliff[5:10, 5:10] = 1.0
    conc[5:10, 5:10] = 0.8
    ao_low[5:10, 5:10] = 0.1  # sky-exposed cliff face ⇒ NOT a cave
    stack.set("cliff_candidate", cliff, "test")
    stack.set("concavity", conc, "test")
    stack.set("ambient_occlusion_bake", ao_low.astype(np.float32), "test")

    cls = _classify_raster(stack)
    assert not (cls[5:10, 5:10] == AudioReverbClass.CAVE.value).any()


def test_classify_raster_canyon_from_steep_parallel_walls():
    from veilbreakers_terrain.handlers.terrain_audio_zones import (
        AudioReverbClass,
        _classify_raster,
    )

    stack = _make_stack_large(tile_size=32, seed=11)
    h = np.asarray(stack.height, dtype=np.float64).copy()
    for r in range(h.shape[0]):
        dist = abs(r - 16)
        if dist < 4:
            h[r, :] = 20.0 + dist * 40.0
    stack.height = h
    _attach_slope(stack)
    conc = np.zeros_like(h)
    conc[14:18, :] = -0.3
    stack.set("curvature", conc.astype(np.float64), "test")

    cls = _classify_raster(stack)
    canyon_cells = int((cls == AudioReverbClass.CANYON.value).sum())
    assert canyon_cells > 0, (
        "canyon with steep parallel walls must classify at least some cells CANYON"
    )


def test_classify_raster_forest_dense_and_sparse_distinguished():
    from veilbreakers_terrain.handlers.terrain_audio_zones import (
        AudioReverbClass,
        _classify_raster,
    )

    stack = _make_stack_large()
    _attach_slope(stack)
    dense = np.zeros_like(stack.height, dtype=np.float32)
    dense[2:8, 2:8] = 0.9
    sparse = np.zeros_like(stack.height, dtype=np.float32)
    sparse[18:23, 18:23] = 0.3
    stack.set("detail_density", {"trees": dense, "shrubs": sparse}, "test")

    cls = _classify_raster(stack)
    assert (cls[2:8, 2:8] == AudioReverbClass.FOREST_DENSE.value).any()
    assert (cls[18:23, 18:23] == AudioReverbClass.FOREST_SPARSE.value).any()


def test_classify_raster_outdoor_default_is_open_field():
    from veilbreakers_terrain.handlers.terrain_audio_zones import (
        AudioReverbClass,
        _classify_raster,
    )

    stack = _make_stack_large()
    _attach_slope(stack)
    cls = _classify_raster(stack)
    frac = (cls == AudioReverbClass.OPEN_FIELD.value).mean()
    assert frac > 0.4, (
        f"flat featureless terrain must classify mostly open_field, got {frac:.2f}"
    )


def test_audio_zone_priority_order_is_documented_and_complete():
    from veilbreakers_terrain.handlers.terrain_audio_zones import (
        AUDIO_ZONE_PRIORITY_ORDER,
        AudioReverbClass,
    )

    assert AUDIO_ZONE_PRIORITY_ORDER[0] == AudioReverbClass.OPEN_FIELD.value
    assert AUDIO_ZONE_PRIORITY_ORDER[-1] == AudioReverbClass.INTERIOR.value
    assert AudioReverbClass.CAVE.value in AUDIO_ZONE_PRIORITY_ORDER
    # No duplicates.
    assert len(set(AUDIO_ZONE_PRIORITY_ORDER)) == len(AUDIO_ZONE_PRIORITY_ORDER)
    # Every class covered.
    for cls in AudioReverbClass:
        assert cls.value in AUDIO_ZONE_PRIORITY_ORDER


# ---------------------------------------------------------------------------
# Upgrade C — compute_audio_zone_list enriched payload + Wwise CSV exporter
# ---------------------------------------------------------------------------


def _make_composite_stack():
    stack = _make_stack_large(tile_size=28, seed=23)
    _attach_slope(stack)
    H, W = stack.height.shape
    water = np.zeros((H, W), dtype=np.float64)
    cliff = np.zeros((H, W), dtype=np.float64)
    conc = np.zeros((H, W), dtype=np.float64)
    ao = np.zeros((H, W), dtype=np.float64)
    water[20:26, 3:9] = 1.0
    cliff[3:9, 20:26] = 1.0
    conc[3:9, 20:26] = 0.8
    ao[3:9, 20:26] = 0.9
    stack.set("water_surface", water, "test")
    stack.set("cliff_candidate", cliff, "test")
    stack.set("concavity", conc, "test")
    stack.set("ambient_occlusion_bake", ao.astype(np.float32), "test")
    return stack


def test_compute_audio_zone_list_returns_enriched_payload():
    from veilbreakers_terrain.handlers.terrain_audio_zones import compute_audio_zone_list

    stack = _make_composite_stack()
    zones = compute_audio_zone_list(stack)
    assert len(zones) >= 2, f"composite stack must yield ≥2 zones, got {len(zones)}"

    required = {
        "id",
        "preset",
        "boundary_polygon",
        "rt60_seconds",
        "echo_delay_ms",
        "occlusion_weight",
        "wet_send_default",
        "class_id",
        "cell_count",
    }
    for z in zones:
        missing = required - set(z.keys())
        assert not missing, f"zone {z.get('id')} missing keys: {missing}"
        # Non-empty polygon.
        assert len(z["boundary_polygon"]) > 0, f"zone {z['id']} has empty polygon"
        # RT60 within hard physical bounds.
        rt60 = float(z["rt60_seconds"])
        assert 0.05 <= rt60 <= 10.0
        # Echo delay finite and non-negative.
        ed = float(z["echo_delay_ms"])
        assert np.isfinite(ed) and ed >= 0.0


def test_compute_audio_zone_list_ids_are_deterministic_and_unique():
    from veilbreakers_terrain.handlers.terrain_audio_zones import compute_audio_zone_list

    stack = _make_composite_stack()
    ids_a = [z["id"] for z in compute_audio_zone_list(stack)]
    ids_b = [z["id"] for z in compute_audio_zone_list(stack)]
    assert ids_a == ids_b
    assert len(set(ids_a)) == len(ids_a)


def test_export_zones_to_wwise_csv_round_trip():
    from veilbreakers_terrain.handlers.terrain_audio_zones import (
        compute_audio_zone_list,
        export_zones_to_wwise_csv,
    )

    stack = _make_composite_stack()
    zones = compute_audio_zone_list(stack)
    csv_text = export_zones_to_wwise_csv(zones)
    lines = [ln for ln in csv_text.splitlines() if ln]
    assert lines[0].startswith("zone_id,preset_name,class_id,")
    assert len(lines) == len(zones) + 1
    header_cols = lines[0].split(",")
    for row in lines[1:]:
        assert len(row.split(",")) == len(header_cols)


def test_export_zones_to_wwise_csv_empty_input_emits_header_only():
    from veilbreakers_terrain.handlers.terrain_audio_zones import export_zones_to_wwise_csv

    csv_text = export_zones_to_wwise_csv([])
    lines = [ln for ln in csv_text.splitlines() if ln]
    assert len(lines) == 1
    assert "zone_id" in lines[0]


# ---------------------------------------------------------------------------
# Upgrade D — pipeline wiring publishes audio_zone_list opaque channel
# ---------------------------------------------------------------------------


def test_pass_audio_zones_publishes_audio_zone_list_opaque_channel():
    from veilbreakers_terrain.handlers.terrain_audio_zones import pass_audio_zones

    state = _build_state()
    stack = state.mask_stack
    water = np.zeros_like(stack.height, dtype=np.float64)
    water[10:14, 10:14] = 1.0
    stack.set("water_surface", water, "test")

    result = pass_audio_zones(state, None)
    assert result.status == "ok"
    zone_list = stack.audio_zone_list
    assert zone_list is not None, (
        "pass_audio_zones must publish audio_zone_list opaque channel"
    )
    assert isinstance(zone_list, list)
    assert len(zone_list) >= 1
    assert "rt60_seconds" in zone_list[0]
    assert "audio_zone_list" in result.produced_channels


def test_pass_compute_audio_zones_is_alias_for_pass_audio_zones():
    from veilbreakers_terrain.handlers.terrain_audio_zones import (
        pass_audio_zones,
        pass_compute_audio_zones,
    )

    assert pass_compute_audio_zones is pass_audio_zones


# ---------------------------------------------------------------------------
# Norris-Eyring RT60 sanity
# ---------------------------------------------------------------------------


def test_sabine_rt60_eyring_shorter_than_sabine_at_high_absorption():
    from veilbreakers_terrain.handlers.terrain_audio_zones import _sabine_rt60

    rt_sabine = _sabine_rt60(200, 2.0, 5.0, 0.7, use_eyring=False)
    rt_eyring = _sabine_rt60(200, 2.0, 5.0, 0.7, use_eyring=True)
    assert rt_eyring < rt_sabine, (
        f"Eyring must < Sabine at α=0.7 (got sabine={rt_sabine:.3f}, "
        f"eyring={rt_eyring:.3f})"
    )


def test_reverb_presets_cover_every_enum_class():
    from veilbreakers_terrain.handlers.terrain_audio_zones import (
        AudioReverbClass,
        REVERB_PRESETS,
        _CLASS_PRESET,
    )

    for cls in AudioReverbClass:
        preset_name = _CLASS_PRESET.get(cls.value)
        assert preset_name is not None, f"class {cls.name} has no preset mapping"
        assert preset_name in REVERB_PRESETS, f"preset {preset_name!r} undefined"
