"""Tests for terrain_wind_field — Fix 9.6 canyon wind signed ridge.

Verifies that negative ridge values (canyon/valley) now produce wind
acceleration (via abs(ridge)) rather than being silently clipped to zero.
"""
from __future__ import annotations

import numpy as np
import pytest

from blender_addon.handlers.terrain_semantics import TerrainMaskStack
from blender_addon.handlers.terrain_wind_field import compute_wind_field


def _make_stack(ridge_val: float, height_val: float = 0.5) -> TerrainMaskStack:
    """Build a minimal 4x4 TerrainMaskStack for wind field tests."""
    stack = TerrainMaskStack(
        tile_size=4,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.full((4, 4), height_val, dtype=np.float32),
        height_min_m=0.0,
        height_max_m=100.0,
        ridge=np.full((4, 4), ridge_val, dtype=np.float32),
    )
    return stack


class TestCanyonWindFix:
    """Fix 9.6 — signed ridge_factor replaces one-sided clip."""

    def test_flat_ridge_produces_base_speed(self) -> None:
        """ridge=0.0 (flat) → ridge_factor = 1.0 → speed ≈ base_speed * altitude_factor."""
        stack = _make_stack(ridge_val=0.0, height_val=0.0)
        field = compute_wind_field(stack, prevailing_direction_rad=0.0, base_speed_mps=5.0)
        speed = float(np.sqrt(field[..., 0] ** 2 + field[..., 1] ** 2).mean())
        # Altitude_factor at height=0 is 1.0; expect speed ≈ 5.0 (small Perlin perturbation)
        assert speed == pytest.approx(5.0, abs=2.5), f"Expected ~5 m/s for flat ridge, got {speed}"

    def test_positive_ridge_accelerates_wind(self) -> None:
        """ridge=+1.0 (exposed peak) → ridge_factor = 1.3 → faster than flat."""
        stack_flat = _make_stack(ridge_val=0.0, height_val=0.0)
        stack_ridge = _make_stack(ridge_val=1.0, height_val=0.0)
        # Use same seed by using the same tile coords
        speed_flat = float(np.sqrt(
            compute_wind_field(stack_flat, 0.0, 5.0)[..., 0] ** 2 +
            compute_wind_field(stack_flat, 0.0, 5.0)[..., 1] ** 2
        ).mean())
        speed_ridge = float(np.sqrt(
            compute_wind_field(stack_ridge, 0.0, 5.0)[..., 0] ** 2 +
            compute_wind_field(stack_ridge, 0.0, 5.0)[..., 1] ** 2
        ).mean())
        assert speed_ridge > speed_flat, (
            f"Ridge (+1.0) should be faster than flat: {speed_ridge} vs {speed_flat}"
        )

    def test_negative_ridge_also_accelerates_wind(self) -> None:
        """ridge=-1.0 (deep canyon) → abs(ridge)=1.0 → same acceleration as +1.0 ridge."""
        stack_canyon = _make_stack(ridge_val=-1.0, height_val=0.0)
        stack_ridge = _make_stack(ridge_val=1.0, height_val=0.0)
        field_canyon = compute_wind_field(stack_canyon, 0.0, 5.0)
        field_ridge = compute_wind_field(stack_ridge, 0.0, 5.0)
        speed_canyon = float(np.sqrt(field_canyon[..., 0] ** 2 + field_canyon[..., 1] ** 2).mean())
        speed_ridge = float(np.sqrt(field_ridge[..., 0] ** 2 + field_ridge[..., 1] ** 2).mean())
        # Both ridge=+1 and ridge=-1 produce ridge_factor=1.3; speeds should be equal
        assert speed_canyon == pytest.approx(speed_ridge, rel=0.01), (
            f"Canyon speed {speed_canyon} should match ridge speed {speed_ridge} with abs(ridge)"
        )

    def test_shallow_canyon_faster_than_flat(self) -> None:
        """ridge=-0.5 (shallow canyon) → abs=0.5 → ridge_factor=1.15 → faster than flat."""
        stack_flat = _make_stack(ridge_val=0.0, height_val=0.0)
        stack_canyon = _make_stack(ridge_val=-0.5, height_val=0.0)
        speed_flat = float(np.sqrt(
            compute_wind_field(stack_flat, 0.0, 5.0)[..., 0] ** 2 +
            compute_wind_field(stack_flat, 0.0, 5.0)[..., 1] ** 2
        ).mean())
        speed_canyon = float(np.sqrt(
            compute_wind_field(stack_canyon, 0.0, 5.0)[..., 0] ** 2 +
            compute_wind_field(stack_canyon, 0.0, 5.0)[..., 1] ** 2
        ).mean())
        assert speed_canyon > speed_flat, (
            f"Canyon (-0.5) should accelerate wind above flat: {speed_canyon} vs {speed_flat}"
        )

    def test_ridge_factor_uses_abs_not_clip(self) -> None:
        """Confirm abs(ridge) is used: ridge=-1.0 produces ridge_factor=1.3, not 1.0."""
        stack = _make_stack(ridge_val=-1.0, height_val=0.0)
        field = compute_wind_field(stack, prevailing_direction_rad=0.0, base_speed_mps=10.0)
        speed = float(np.sqrt(field[..., 0] ** 2 + field[..., 1] ** 2).mean())
        # With ridge_factor=1.3 and base 10 m/s, expect speed > 11.0 (before perturbation)
        assert speed > 10.0, (
            f"Canyon (ridge=-1) must accelerate above base speed; got {speed}"
        )
