"""WAVE-1 regression — env.py neighbor heightmap dequant round-trip.

The CE WAVE 1 audit (6 parallel adversarial reviewers, 2026-05-20)
re-confirmed the T1-17 round-4 fix landed: the neighbor-edge loader at
``environment.py:2680..`` now does

    np.fromfile(path, dtype="<u2") → reshape → flipud → dequantize via
    height_range from neighbor manifest

instead of the original ``np.load()`` which silently failed on raw uint16
bytes (no .npy magic) and let every multi-tile world bake ship visible
seams. This test pins the closure by exercising the round-trip through
the *production* helper (T122-1 round-2 — CodeRabbit Major):

    heightmap (float metres) → _export_heightmap_raw → bytes-on-disk →
    _read_neighbor_heightmap_from_manifest (production code path) →
    heightmap (float metres ≈ original within uint16 quantisation step)

If a future refactor drops the ``height_range`` manifest field, swaps the
writer back to .npy, or removes the flipud round-trip, this test fails
LOUDLY at the regression-net layer.

WAVE-1 hotfix ALSO narrows the outer ``except Exception`` to a tuple of
``(FileNotFoundError, OSError, ValueError, KeyError, TypeError)``. The
narrow-except test verifies legitimate refactor bugs (e.g. AttributeError
from a dropped attribute) surface as crashes instead of warnings.

T122-1 round-2 fix history
--------------------------
The original CE WAVE 1 hotfix landed a guard-check test that reimplemented
the dequant logic inline (CodeRabbit Major: "test does not exercise
production guard logic — Line 155 onward reimplements the check
locally"). The fix:

1. Extracted the previously-nested ``_read_neighbor_heightmap`` (inside
   ``handle_generate_world_terrain``) to a module-level helper named
   ``_read_neighbor_heightmap_from_manifest``. Behaviour unchanged.
2. Rewrote ``test_dequant_raises_value_error_when_height_range_missing``
   to drive the actual production helper instead of reimplementing the
   guard. If anyone weakens the production guard, this test now fails.
3. Added two adjacent production-helper exercises: invalid file size +
   non-finite height_range bounds — both also drive the production code
   path.
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import numpy as np
import pytest

# T122-2 (CodeQL py/import-statement-mixed-with-from-import-statement):
# previously this module did BOTH
#   ``import veilbreakers_terrain.handlers.environment as env``
# AND
#   ``from veilbreakers_terrain.handlers.environment import (...)``
# which CodeQL flags. Settled on a single ``from ... import`` form at
# call sites, and the static-source test below resolves the path via
# inspect.getsourcefile() instead of an alias-import.
from veilbreakers_terrain.handlers.environment import (
    _export_heightmap_raw,
    _read_neighbor_heightmap_from_manifest,
)


def _make_synthetic_heightmap(side: int = 65, seed: int = 4242) -> np.ndarray:
    """Build a known float64 heightmap with a non-degenerate value range."""
    rng = np.random.default_rng(seed)
    base = rng.uniform(low=10.0, high=150.0, size=(side, side)).astype(np.float64)
    # Tilt it so the corners are distinct (helps the flipud check below).
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float64)
    return base + (yy * 0.5) + (xx * 0.25)


def _write_raw_heightmap_and_manifest(
    tmpdir: Path,
    heightmap: np.ndarray,
    *,
    height_range: tuple[float, float] | None,
    resolution: int | None = None,
) -> dict[str, object]:
    """Write ``heightmap`` as a raw uint16 file under ``tmpdir`` and build
    a neighbor-result dict suitable for ``_read_neighbor_heightmap_from_manifest``.

    Mirrors the on-disk format produced by ``_write_tile_raw_files`` in
    ``handle_generate_world_terrain``. The returned dict can be passed
    directly into the production helper (whose contract is documented in
    its docstring).
    """
    if height_range is None:
        # The caller wants to exercise the missing-height_range guard;
        # still write a file so other guards don't pre-empt.
        hmin, hmax = float(heightmap.min()), float(heightmap.max())
        raw_bytes = _export_heightmap_raw(
            heightmap, flip_vertical=True, value_range=(hmin, hmax)
        )
    else:
        raw_bytes = _export_heightmap_raw(
            heightmap, flip_vertical=True, value_range=height_range
        )
    raw_path = tmpdir / "neighbor_heightmap.raw"
    raw_path.write_bytes(raw_bytes)
    manifest: dict[str, object] = {
        "heightmap_path": str(raw_path),
        "resolution": resolution if resolution is not None else int(heightmap.shape[0]),
    }
    if height_range is not None:
        manifest["height_range"] = height_range
    return manifest


def test_neighbor_heightmap_round_trip_within_uint16_quantisation_step():
    """A heightmap written via ``_export_heightmap_raw`` must dequantise
    back to within one uint16 step (i.e. ``(hmax-hmin)/65535``) when read
    by the production ``_read_neighbor_heightmap_from_manifest``.
    """
    side = 65
    hmap = _make_synthetic_heightmap(side=side, seed=1234)
    hmin = float(hmap.min())
    hmax = float(hmap.max())
    quant_step = (hmax - hmin) / 65535.0

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        manifest = _write_raw_heightmap_and_manifest(
            tmpdir, hmap, height_range=(hmin, hmax)
        )

        # T122-1 round-2: drive the production helper directly.
        reconstructed = _read_neighbor_heightmap_from_manifest(manifest)

    assert reconstructed.shape == hmap.shape
    # Reconstruction error must fit inside the quantisation step.
    max_err = float(np.max(np.abs(reconstructed - hmap)))
    assert max_err <= quant_step * 1.5, (
        f"dequant error {max_err:.6e} exceeds 1.5x uint16 step "
        f"{quant_step:.6e} for range [{hmin}, {hmax}]"
    )


def test_dequant_recovers_known_corner_values_after_flipud():
    """A flat-tilted gradient must reconstruct to the same corner values
    after the writer's flipud + the production helper's flipud cancel out.

    This catches the regression where someone removes one of the two
    flips and silently 180-rotates every neighbor edge into the seam
    lock.
    """
    # Use a perfectly clean linear gradient so quantisation rounds cleanly.
    side = 33
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float64)
    hmap = (yy * 1.0) + (xx * 2.0)  # range: [0, 3*(side-1)] = [0, 96]
    hmin, hmax = 0.0, float(3 * (side - 1))

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        manifest = _write_raw_heightmap_and_manifest(
            tmpdir, hmap, height_range=(hmin, hmax)
        )
        # T122-1 round-2: drive the production helper directly.
        reconstructed = _read_neighbor_heightmap_from_manifest(manifest)

    # Corners must match the original within the per-pixel quant step.
    quant_step = (hmax - hmin) / 65535.0
    for (y, x) in [(0, 0), (0, side - 1), (side - 1, 0), (side - 1, side - 1)]:
        assert abs(reconstructed[y, x] - hmap[y, x]) <= quant_step * 1.5, (
            f"corner ({y},{x}): orig={hmap[y, x]}, "
            f"reconstructed={reconstructed[y, x]} "
            f"(quant_step={quant_step:.4e})"
        )


def test_dequant_raises_value_error_when_height_range_missing():
    """The production helper MUST reject a manifest that omits ``height_range``.

    T122-1 round-2 (CodeRabbit Major): this test previously reimplemented
    the guard inline, so it would have passed even if the production
    guard regressed. It now drives the actual production helper
    ``_read_neighbor_heightmap_from_manifest`` — if anyone weakens the
    guard, this fails at the regression-net layer.

    Without dequant info we cannot know whether the uint16 values
    represent [0, 100m] or [0, 4000m]; silently treating the raw uint16
    as metres would feed values in the [0, 65535] domain into seam-lock
    logic that expects values in metres — exactly the corruption the
    WAVE-1 audit flagged.
    """
    side = 17
    hmap = _make_synthetic_heightmap(side=side, seed=4242)
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        # T122-1 round-2: build a manifest with NO ``height_range`` key
        # and feed it to the production helper.  The production guard
        # must raise ValueError; if a future refactor swallows the
        # missing-key case the test fails immediately.
        manifest = _write_raw_heightmap_and_manifest(
            tmpdir, hmap, height_range=None
        )
        # Defensive: confirm the manifest really is missing the key (so
        # the helper's guard is being exercised, not a different one).
        assert "height_range" not in manifest, (
            "manifest fixture leaked height_range; the guard under test "
            "would not actually be reached"
        )

        with pytest.raises(ValueError, match=r"height_range"):
            _read_neighbor_heightmap_from_manifest(manifest)


def test_dequant_raises_value_error_when_height_range_non_finite():
    """The production helper must reject ``height_range`` with non-finite
    bounds (NaN / inf) — otherwise the dequant math returns NaN heights
    that propagate silently into seam-lock state.

    Added in T122-1 round-2 to exercise a second production guard branch
    that was previously not pinned by any test.
    """
    side = 17
    hmap = _make_synthetic_heightmap(side=side, seed=4242)
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        manifest = _write_raw_heightmap_and_manifest(
            tmpdir, hmap, height_range=(0.0, 100.0)
        )
        # Overwrite the manifest's height_range with non-finite bounds.
        manifest["height_range"] = (float("nan"), 100.0)
        with pytest.raises(ValueError, match=r"non-finite"):
            _read_neighbor_heightmap_from_manifest(manifest)

        manifest["height_range"] = (0.0, float("inf"))
        with pytest.raises(ValueError, match=r"non-finite"):
            _read_neighbor_heightmap_from_manifest(manifest)


def test_dequant_raises_value_error_when_resolution_mismatches_file_size():
    """The production helper must reject a manifest whose declared
    ``resolution`` does not match the on-disk uint16 element count.

    T122-4 round-3 (copilot): wording corrected — ``np.fromfile(..., dtype="<u2")``
    returns an array of uint16 *elements* (each 2 bytes), so the
    comparison is element-count vs resolution², not byte-count vs
    resolution². A mismatched resolution would either truncate or run
    off the end of the array, producing silent edge corruption.
    """
    side = 17
    hmap = _make_synthetic_heightmap(side=side, seed=4242)
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        manifest = _write_raw_heightmap_and_manifest(
            tmpdir, hmap, height_range=(0.0, 100.0)
        )
        # Lie about the resolution so the size guard trips.
        manifest["resolution"] = side + 1
        with pytest.raises(ValueError, match=r"resolution"):
            _read_neighbor_heightmap_from_manifest(manifest)


def test_neighbor_loader_except_is_narrow_not_bare():
    """Static check: the ``except`` around any call to
    ``_read_neighbor_heightmap_from_manifest`` in environment.py must NOT
    be ``except Exception`` (bare). Narrowing surfaces real refactor bugs
    (AttributeError, ImportError, RuntimeError) as crashes instead of
    swallowing them as harmless warnings.

    Implements FIX_PATTERN §C3 "broad-except hygiene" for this site.

    T122-2 (CodeQL): resolve the source file via ``inspect.getsourcefile``
    on the production helper itself rather than re-importing the module
    under a separate alias (which previously triggered CodeQL's
    py/import-statement-mixed-with-from-import-statement rule).

    T122-5 (copilot round-3): replaced the brittle string-containment
    check ``narrow_marker in src`` with a structural AST walk. The
    previous form failed on harmless formatting changes (line breaks,
    reordered exception tuple, additional exceptions). The new check:
      1. Parses the production module with ``ast``.
      2. Walks every ``Try`` whose body contains a Call to
         ``_read_neighbor_heightmap_from_manifest`` (the live consumer).
      3. For each such Try, asserts at least one handler matches:
         (a) handler.type is a Tuple, AND
         (b) every element in the tuple is a Name node (i.e. an
             explicit exception class, not bare ``Exception``), AND
         (c) the *names* superset our REQUIRED_NARROW set so the
             dequant-relevant exceptions are all covered.
      Reordering / adding more narrow classes / wrapping across lines is
      now invisible to the check. Bare ``except Exception`` or
      ``except (Exception, ...)`` still trips it.
    """
    import inspect

    src_path = inspect.getsourcefile(_read_neighbor_heightmap_from_manifest)
    assert src_path is not None, "production helper has no source file?"
    src = Path(src_path).read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Required narrow exception names — every dequant-relevant exception
    # that the WAVE-1 hotfix's narrowing must keep covering.  Adding more
    # narrow classes is fine — they just need to also be Names, not bare
    # Exception.
    # CHECKPOINT-5 cascade-D: AttributeError added — if ``neighbor`` is None
    # or a non-dict type (namedtuple/dataclass), calling ``.get()`` raises
    # AttributeError which was previously not in the tuple and would escape
    # to crash the tile bake.
    required_narrow: set[str] = {
        "FileNotFoundError",
        "OSError",
        "ValueError",
        "KeyError",
        "TypeError",
        "AttributeError",
    }
    target_call_name = "_read_neighbor_heightmap_from_manifest"

    def _try_body_calls_target(try_node: ast.Try) -> bool:
        """True iff ``try_node.body`` contains a Call to the target."""
        for stmt in try_node.body:
            for sub in ast.walk(stmt):
                if not isinstance(sub, ast.Call):
                    continue
                f = sub.func
                if isinstance(f, ast.Name) and f.id == target_call_name:
                    return True
                if isinstance(f, ast.Attribute) and f.attr == target_call_name:
                    return True
        return False

    def _handler_is_narrow(handler: ast.ExceptHandler) -> tuple[bool, set[str]]:
        """Return (is_narrow_tuple_of_names, set_of_class_names)."""
        t = handler.type
        if t is None:
            # bare ``except:`` — definitely not narrow
            return (False, set())
        if isinstance(t, ast.Name):
            # ``except SomeException`` — narrow only if not bare Exception
            return (t.id != "Exception" and t.id != "BaseException", {t.id})
        if isinstance(t, ast.Tuple):
            names: set[str] = set()
            for elt in t.elts:
                if not isinstance(elt, ast.Name):
                    # ``except (mod.SomeError, ...)`` — Attribute, not Name —
                    # treat as non-narrow for the strict check
                    return (False, set())
                if elt.id in {"Exception", "BaseException"}:
                    return (False, names)
                names.add(elt.id)
            return (True, names)
        # ``except some_expression`` — not a static narrow form
        return (False, set())

    narrow_handlers_found: list[set[str]] = []
    enclosing_target_tries = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if not _try_body_calls_target(node):
            continue
        enclosing_target_tries += 1
        for handler in node.handlers:
            is_narrow, names = _handler_is_narrow(handler)
            if is_narrow:
                narrow_handlers_found.append(names)

    assert enclosing_target_tries > 0, (
        f"No try/except block found enclosing a call to "
        f"{target_call_name} in {src_path}. Either the helper is no "
        f"longer called or this test has drifted out of sync with the "
        f"production wiring."
    )
    assert narrow_handlers_found, (
        f"No narrow ``except (NameA, NameB, ...)`` handler found around "
        f"any call to {target_call_name}. The WAVE-1 hotfix narrowed "
        f"this from 'except Exception'; if you intentionally broadened "
        f"it back, document why in a docstring above the except clause "
        f"and update this test."
    )
    # At least one narrow handler must be a superset of the required
    # dequant-relevant exception names.
    covering = [h for h in narrow_handlers_found if required_narrow.issubset(h)]
    assert covering, (
        f"Found narrow handlers {narrow_handlers_found} but none cover "
        f"the required dequant-relevant exceptions {required_narrow}. "
        f"The narrow tuple must include at least these names so a "
        f"corrupted manifest / IO error / type mismatch still falls into "
        f"the recoverable warn-and-skip-neighbor-edge branch instead of "
        f"crashing the tile bake."
    )


# ---------------------------------------------------------------------------
# CHECKPOINT-5 cascade-D: non-dict neighbor input must NOT raise AttributeError
# ---------------------------------------------------------------------------

class TestNeighborNonDictInputHandling:
    """CHECKPOINT-5 cascade-D — _read_neighbor_heightmap_from_manifest must
    handle non-dict neighbor inputs without raising AttributeError.

    PR #122 narrowed the except tuple to
    ``(FileNotFoundError, OSError, ValueError, KeyError, TypeError)`` to
    surface real refactor bugs.  CHECKPOINT-5 found that if ``neighbor`` is
    ``None`` or a non-dict type (namedtuple, dataclass, …) calling
    ``neighbor.get(...)`` raises **AttributeError** — previously NOT in the
    tuple — which escaped and crashed the terrain bake.

    Fix (cascade-D):
    1. Added ``AttributeError`` to the except tuple at the call site in
       ``handle_generate_world_terrain``.
    2. Added an ``isinstance(neighbor, dict)`` early guard at the function
       entry of ``_read_neighbor_heightmap_from_manifest`` that raises
       ``TypeError`` (in the except tuple) with a clear message so the
       caller's warn-and-skip path fires instead of propagating a crash.
    """

    def test_none_neighbor_does_not_raise_attribute_error(self):
        """Passing None must raise TypeError (in the except tuple), NOT AttributeError."""
        with pytest.raises(TypeError, match=r"expected dict"):
            _read_neighbor_heightmap_from_manifest(None)  # type: ignore[arg-type]

    def test_tuple_neighbor_does_not_raise_attribute_error(self):
        """Passing a plain tuple must raise TypeError, not AttributeError."""
        with pytest.raises(TypeError, match=r"expected dict"):
            _read_neighbor_heightmap_from_manifest(("some", "values"))  # type: ignore[arg-type]

    def test_dataclass_neighbor_does_not_raise_attribute_error(self):
        """Passing a dataclass instance must raise TypeError, not AttributeError."""
        import dataclasses

        @dataclasses.dataclass
        class FakeNeighbor:
            heightmap_path: str = "/fake/path"
            resolution: int = 17
            height_range: tuple = (0.0, 100.0)

        with pytest.raises(TypeError, match=r"expected dict"):
            _read_neighbor_heightmap_from_manifest(FakeNeighbor())  # type: ignore[arg-type]

    def test_non_dict_raises_type_error_not_attribute_error(self):
        """Confirm the raised exception is TypeError (in the narrow except tuple)
        and NOT AttributeError (which previously escaped the except tuple).
        """
        for bad_input in (None, 42, "string", [1, 2, 3], (1, 2)):
            try:
                _read_neighbor_heightmap_from_manifest(bad_input)  # type: ignore[arg-type]
                pytest.fail(f"Expected TypeError for input {bad_input!r} but no exception raised")
            except TypeError:
                pass  # expected — TypeError is in the narrow except tuple
            except AttributeError as exc:
                pytest.fail(
                    f"AttributeError escaped for input {bad_input!r}: {exc}. "
                    f"CHECKPOINT-5 cascade-D fix not applied — isinstance guard "
                    f"or AttributeError not in except tuple."
                )

    def test_non_dict_warns_via_logger(self, caplog: pytest.LogCaptureFixture):
        """The function must emit a logger.warning before raising TypeError."""
        import logging

        with caplog.at_level(logging.WARNING, logger="veilbreakers_terrain.handlers.environment"):
            with pytest.raises(TypeError):
                _read_neighbor_heightmap_from_manifest(None)  # type: ignore[arg-type]

        assert any(
            "not a dict" in record.message or "skipping" in record.message
            for record in caplog.records
        ), (
            "Expected a warning log about non-dict neighbor but none found in caplog. "
            "The logger.warning call in the isinstance guard may be missing."
        )
