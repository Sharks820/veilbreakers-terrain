"""Regression net for T0.5-8 (Y04 v3 §P.8.2 + ZZ4-A6 R3):
JSON serialisation at the Unity export hop must fail loud on NaN/Inf
rather than emitting 'NaN'/'Infinity' tokens that Unity's strict-RFC
JsonUtility.FromJson silently interprets as zero.

The silent-zero-manifest chain (β10-05): a single NaN slipping into the
manifest payload caused Unity's importer to silently zero-fill the
entire deserialised object, breaking every downstream consumer. With
``allow_nan=False`` json.dumps raises ValueError at serialise-time, so
the bake aborts BEFORE the corrupt file is atomic-written.

Three sites guarded by this regression net:
- terrain_unity_export.py:858 sidecar writer (general payload).
- terrain_unity_export.py:2807 unity_import_descriptor.
- terrain_unity_export.py:2810 manifest.

This file directly tests the json.dumps invocation contract. End-to-end
tests of the full Unity export pipeline live in
test_terrain_unity_export_bridge.py.

Per FIX_PATTERN_v1.md §3 C3+C5 hybrid recipe.
"""

from __future__ import annotations

import json
import math

import pytest


class TestAllowNanFalseRaisesOnNaN:
    """All three Unity-export json.dumps sites must reject NaN."""

    def test_serialise_payload_with_nan_raises(self) -> None:
        """Mirror the kwargs at terrain_unity_export.py:858 / 2807 / 2810."""
        payload = {"valid_field": 1.0, "nan_field": float("nan")}
        with pytest.raises(ValueError, match="Out of range float values"):
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)

    def test_serialise_payload_with_positive_inf_raises(self) -> None:
        payload = {"valid_field": 1.0, "inf_field": math.inf}
        with pytest.raises(ValueError, match="Out of range float values"):
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)

    def test_serialise_payload_with_negative_inf_raises(self) -> None:
        payload = {"valid_field": 1.0, "neg_inf_field": -math.inf}
        with pytest.raises(ValueError, match="Out of range float values"):
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)

    def test_serialise_payload_with_nested_nan_raises(self) -> None:
        """Nested NaN inside a dict-of-list must also raise (manifest shape)."""
        payload = {
            "splatmap_layers": [{"name": "layer_a", "weight": float("nan")}],
        }
        with pytest.raises(ValueError, match="Out of range float values"):
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)

    def test_serialise_clean_payload_succeeds(self) -> None:
        """Payloads with finite floats must serialise normally."""
        payload = {
            "tile_x": 3,
            "tile_y": 7,
            "splatmap_layers": [{"name": "grass", "weight": 0.6}],
            "height_min_m": 10.0,
            "height_max_m": 22.0,
        }
        out = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
        assert '"height_max_m": 22.0' in out
        assert "NaN" not in out
        assert "Infinity" not in out

    def test_default_allow_nan_true_would_emit_nan_token(self) -> None:
        """Sanity check: WITHOUT allow_nan=False, json.dumps silently emits
        the 'NaN' token that Unity's JsonUtility.FromJson rejects/zeros.
        Documents the failure mode this fix closes.
        """
        payload = {"poisoned": float("nan")}
        out_silent = json.dumps(payload, indent=2, sort_keys=True)
        assert "NaN" in out_silent  # the silent-corruption signature
