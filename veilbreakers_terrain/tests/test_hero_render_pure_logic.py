"""Pure-logic regression nets for the hero-render modules (no Blender needed).

Locks the fixes from the 2026-05-25 CE adversarial review. These three modules
(scripts/aaa_asset_foliage.py, scripts/_fetch_cc0_foliage.py) had ZERO test
coverage, which is precisely why the original P0 (foliage wipe), the determinism
bug, and the security holes escaped CI + the gates + the PR bots. The testable
pieces are pure functions; pin them so the fixes cannot silently regress.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# _fetch_cc0_foliage imports no bpy -> direct import.
from scripts._fetch_cc0_foliage import _SAFE_NAME, _check_url  # noqa: E402

# aaa_asset_foliage imports bpy + mathutils at module scope. _layer_seed uses
# only zlib at call time, so stub those imports ONLY long enough to bind the
# function, then restore sys.modules so the rest of the suite is untouched.
_added_bpy = "bpy" not in sys.modules
_added_mu = "mathutils" not in sys.modules
sys.modules.setdefault("bpy", mock.MagicMock())
sys.modules.setdefault("mathutils", mock.MagicMock())
try:
    from scripts.aaa_asset_foliage import LIBRARY_SPEC, _layer_seed  # noqa: E402
finally:
    if _added_bpy:
        sys.modules.pop("bpy", None)
    if _added_mu:
        sys.modules.pop("mathutils", None)


class TestLayerSeed(unittest.TestCase):
    """seed + len(layer) collided same-length layers; crc32 of the name must not."""

    def test_same_length_layers_do_not_collide(self) -> None:
        # 'canopy' and 'ground' are both 6 chars -> the old bug stamped them on
        # the identical blue-noise lattice.
        self.assertNotEqual(_layer_seed(42, "canopy"), _layer_seed(42, "ground"))

    def test_all_library_layers_distinct(self) -> None:
        seeds = [_layer_seed(20260525, layer) for layer in LIBRARY_SPEC]
        self.assertEqual(len(seeds), len(set(seeds)),
                         "every ecological stratum must get a distinct seed")

    def test_deterministic_across_calls(self) -> None:
        self.assertEqual(_layer_seed(7, "grass"), _layer_seed(7, "grass"))

    def test_within_int32_range(self) -> None:
        for layer in LIBRARY_SPEC:
            value = _layer_seed(0, layer)
            self.assertTrue(0 <= value < 2 ** 31)


class TestCheckUrl(unittest.TestCase):
    """The downloader must refuse non-https URLs (file/ftp/data = SSRF/local-read)."""

    def test_rejects_non_https_schemes(self) -> None:
        for bad in ("file:///etc/passwd", "file:///C:/Windows/win.ini",
                    "ftp://host/x", "data:text/plain,hi", "http://host/x",
                    "FILE:///etc/passwd", "https:///no-host-path"):
            with self.assertRaises(ValueError, msg=f"{bad!r} must be refused"):
                _check_url(bad)

    def test_accepts_https(self) -> None:
        _check_url("https://api.polyhaven.com/files/boulder_01")
        _check_url("https://dl.polyhaven.org/asset/x.gltf")


class TestSafeName(unittest.TestCase):
    """Asset id / category must not escape the download root (CWE-22)."""

    def test_rejects_traversal_and_separators(self) -> None:
        for bad in ("../etc", "..\\windows", "a/b", "a\\b", "", "a;b",
                    "$(x)", "a b", "/abs", "a\x00b"):
            self.assertIsNone(_SAFE_NAME.match(bad), f"{bad!r} must be rejected")

    def test_accepts_real_asset_ids(self) -> None:
        for ok in ("island_tree_01", "namaqualand_boulder_03", "grass_medium_02",
                   "coast_rocks_01", "forest_ground_04", "dead_tree_trunk"):
            self.assertIsNotNone(_SAFE_NAME.match(ok), f"{ok!r} must pass")


if __name__ == "__main__":
    unittest.main()
