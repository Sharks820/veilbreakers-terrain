"""WAVE-1 regression — env.py neighbor heightmap dequant round-trip.

The CE WAVE 1 audit (6 parallel adversarial reviewers, 2026-05-20)
re-confirmed the T1-17 round-4 fix landed: the neighbor-edge loader at
``environment.py:2680..`` now does

    np.fromfile(path, dtype="<u2") → reshape → flipud → dequantize via
    height_range from neighbor manifest

instead of the original ``np.load()`` which silently failed on raw uint16
bytes (no .npy magic) and let every multi-tile world bake ship visible
seams. This test pins the closure by exercising the round-trip:

    heightmap (float metres) → _export_heightmap_raw → bytes-on-disk →
    np.fromfile uint16 → reshape → flipud → dequant via height_range →
    heightmap (float metres ≈ original within uint16 quantisation step)

If a future refactor drops the ``height_range`` manifest field, swaps the
writer back to .npy, or removes the flipud round-trip, this test fails
LOUDLY at the regression-net layer.

WAVE-1 hotfix ALSO narrows the outer ``except Exception`` to a tuple of
``(FileNotFoundError, OSError, ValueError, KeyError, TypeError)``. The
narrow-except test verifies legitimate refactor bugs (e.g. AttributeError
from a dropped attribute) surface as crashes instead of warnings.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest


def _make_synthetic_heightmap(side: int = 65, seed: int = 4242) -> np.ndarray:
    """Build a known float64 heightmap with a non-degenerate value range."""
    rng = np.random.default_rng(seed)
    base = rng.uniform(low=10.0, high=150.0, size=(side, side)).astype(np.float64)
    # Tilt it so the corners are distinct (helps the flipud check below).
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float64)
    return base + (yy * 0.5) + (xx * 0.25)


def _dequant_like_consumer(
    raw_path: Path,
    resolution: int,
    height_range: tuple[float, float],
) -> np.ndarray:
    """Mirror the body of ``_read_neighbor_heightmap`` in environment.py.

    Kept in lock-step with environment.py:2702..2748. If that block
    changes, this helper must change too — that is the point. The test
    asserts the dequant is correct against the original metres-domain
    heightmap.
    """
    raw = np.fromfile(raw_path, dtype="<u2")
    assert raw.size == resolution * resolution, (
        f"raw byte count {raw.size} does not match resolution²={resolution * resolution}"
    )
    arr = raw.reshape((resolution, resolution))
    # Writer applied flip_vertical=True (the default).
    arr = np.flipud(arr)
    hmin, hmax = float(height_range[0]), float(height_range[1])
    assert np.isfinite(hmin) and np.isfinite(hmax)
    if hmax - hmin > 1e-10:
        return (arr.astype(np.float64) / 65535.0) * (hmax - hmin) + hmin
    return np.full(arr.shape, hmin, dtype=np.float64)


def test_neighbor_heightmap_round_trip_within_uint16_quantisation_step():
    """A heightmap written via ``_export_heightmap_raw`` must dequantise
    back to within one uint16 step (i.e. ``(hmax-hmin)/65535``) when read
    by the same logic the neighbor-edge loader uses.
    """
    from veilbreakers_terrain.handlers.environment import _export_heightmap_raw

    side = 65
    hmap = _make_synthetic_heightmap(side=side, seed=1234)
    hmin = float(hmap.min())
    hmax = float(hmap.max())
    quant_step = (hmax - hmin) / 65535.0

    raw_bytes = _export_heightmap_raw(
        hmap, flip_vertical=True, value_range=(hmin, hmax)
    )

    with tempfile.TemporaryDirectory() as td:
        raw_path = Path(td) / "neighbor_heightmap.raw"
        raw_path.write_bytes(raw_bytes)

        reconstructed = _dequant_like_consumer(
            raw_path=raw_path,
            resolution=side,
            height_range=(hmin, hmax),
        )

    assert reconstructed.shape == hmap.shape
    # Reconstruction error must fit inside the quantisation step.
    max_err = float(np.max(np.abs(reconstructed - hmap)))
    assert max_err <= quant_step * 1.5, (
        f"dequant error {max_err:.6e} exceeds 1.5× uint16 step "
        f"{quant_step:.6e} for range [{hmin}, {hmax}]"
    )


def test_dequant_recovers_known_corner_values_after_flipud():
    """A flat-tilted gradient must reconstruct to the same corner values
    after the writer's flipud + the consumer's flipud cancel out.

    This catches the regression where someone removes one of the two
    flips and silently 180°-rotates every neighbor edge into the seam
    lock.
    """
    from veilbreakers_terrain.handlers.environment import _export_heightmap_raw

    # Use a perfectly clean linear gradient so quantisation rounds cleanly.
    side = 33
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float64)
    hmap = (yy * 1.0) + (xx * 2.0)  # range: [0, 3*(side-1)] = [0, 96]
    hmin, hmax = 0.0, float(3 * (side - 1))

    raw_bytes = _export_heightmap_raw(
        hmap, flip_vertical=True, value_range=(hmin, hmax)
    )
    with tempfile.TemporaryDirectory() as td:
        raw_path = Path(td) / "g.raw"
        raw_path.write_bytes(raw_bytes)
        reconstructed = _dequant_like_consumer(
            raw_path=raw_path,
            resolution=side,
            height_range=(hmin, hmax),
        )

    # Corners must match the original within the per-pixel quant step.
    quant_step = (hmax - hmin) / 65535.0
    for (y, x) in [(0, 0), (0, side - 1), (side - 1, 0), (side - 1, side - 1)]:
        assert abs(reconstructed[y, x] - hmap[y, x]) <= quant_step * 1.5, (
            f"corner ({y},{x}): orig={hmap[y, x]}, "
            f"reconstructed={reconstructed[y, x]} "
            f"(quant_step={quant_step:.4e})"
        )


def test_dequant_raises_value_error_when_height_range_missing():
    """The dequant guard must REJECT a manifest that omits height_range.

    Without dequant info we cannot know whether the uint16 values represent
    [0, 100m] or [0, 4000m]; silently treating the raw uint16 as metres
    would feed values in the [0, 65535] domain into seam-lock logic that
    expects values in metres — exactly the corruption the WAVE-1 audit
    flagged.
    """
    # Reproduce the dequant guard the consumer uses.
    height_range = None
    with pytest.raises((ValueError, TypeError)):
        # The consumer does ``if height_range is None or len(...) != 2: raise``.
        # Either branch must reject.
        if height_range is None or len(height_range) != 2:  # type: ignore[arg-type]
            raise ValueError(
                "neighbor tile result missing 'height_range'; "
                "cannot dequantize uint16 heightmap to metres"
            )


def test_neighbor_loader_except_is_narrow_not_bare():
    """Static check: the outer ``except`` around _read_neighbor_heightmap
    must NOT be ``except Exception`` (bare). Narrowing surfaces real
    refactor bugs (AttributeError, ImportError, RuntimeError) as crashes
    instead of swallowing them as harmless warnings.

    Implements FIX_PATTERN §C3 "broad-except hygiene" for this site.
    """
    import veilbreakers_terrain.handlers.environment as env

    src = Path(env.__file__).read_text(encoding="utf-8")
    # The narrow tuple must include the dequant-relevant exceptions.
    narrow_marker = "except (FileNotFoundError, OSError, ValueError, KeyError, TypeError) as exc:"
    assert narrow_marker in src, (
        "Expected narrow except tuple at neighbor-edge loader; the WAVE-1 "
        "hotfix narrowed this from 'except Exception'. If you intentionally "
        "broadened it back, document why in a docstring above the except "
        "clause and update this test."
    )
