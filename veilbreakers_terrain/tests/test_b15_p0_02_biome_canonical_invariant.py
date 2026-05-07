"""B15-P0-02 / Phase A D6-7 regression tests.

Verifies the cross-module canonical-biome invariant:

    set(_biome_grammar.BIOME_CLIMATE_PARAMS.keys())
    == set(terrain_biome_registry.CANONICAL_BIOME_IDS.keys())

If these two sets diverge, foliage catalog reads names that the climate
params don't recognise — silent zero placements at runtime (P0-S2 in the
old audit). The module-level invariant in ``_biome_grammar.py`` (try/except
ImportError block immediately after ``CANONICAL_BIOME_IDS``) raises
``AssertionError`` on first import when the sets drift; this test is the
explicit ratchet that the invariant remains held.
"""

from __future__ import annotations

from veilbreakers_terrain.handlers import _biome_grammar
from veilbreakers_terrain.handlers.terrain_biome_registry import CANONICAL_BIOME_IDS

BIOME_CLIMATE_PARAMS = _biome_grammar.BIOME_CLIMATE_PARAMS


def test_biome_climate_params_matches_canonical_registry():
    """BIOME_CLIMATE_PARAMS keys must equal terrain_biome_registry canonical set."""
    params_keys = set(BIOME_CLIMATE_PARAMS.keys())
    registry_keys = set(CANONICAL_BIOME_IDS.keys())

    missing_from_params = registry_keys - params_keys
    missing_from_registry = params_keys - registry_keys

    assert not missing_from_params, (
        f"Biomes present in registry but missing from BIOME_CLIMATE_PARAMS: "
        f"{sorted(missing_from_params)}"
    )
    assert not missing_from_registry, (
        f"Biomes present in BIOME_CLIMATE_PARAMS but missing from registry: "
        f"{sorted(missing_from_registry)}"
    )
    assert params_keys == registry_keys


def test_invariant_has_expected_18_biomes():
    """Lock the canonical count at 18 — drift here is a feature change requiring spec update."""
    assert len(BIOME_CLIMATE_PARAMS) == 18
    assert len(CANONICAL_BIOME_IDS) == 18


def test_module_exposes_canonical_attributes():
    """The _biome_grammar module exposes BIOME_CLIMATE_PARAMS + CANONICAL_BIOME_IDS publicly.

    The module is already imported at file-load time; if its module-level
    invariant raised, the import at the top of this test file would have
    failed and pytest collection would already be red. This test documents
    the public contract that downstream callers depend on.

    NOTE: We deliberately do NOT use ``importlib.reload(_biome_grammar)``
    to "re-fire the invariant" — reload rebinds module-level class objects
    (e.g. ``WorldMapSpec``) so any other test holding a reference to the
    pre-reload class fails ``isinstance`` checks. The single import-time
    invariant + this attribute-presence ratchet are the durable contract.
    """
    assert hasattr(_biome_grammar, "BIOME_CLIMATE_PARAMS")
    assert hasattr(_biome_grammar, "CANONICAL_BIOME_IDS")


def test_each_canonical_biome_has_climate_params_with_required_keys():
    """Every canonical biome must have temperature/moisture/elevation entries."""
    required = {"temperature", "moisture", "elevation"}
    for biome_id in CANONICAL_BIOME_IDS:
        params = BIOME_CLIMATE_PARAMS.get(biome_id)
        assert params is not None, f"{biome_id} missing from BIOME_CLIMATE_PARAMS"
        missing = required - set(params.keys())
        assert not missing, f"{biome_id} missing climate keys: {sorted(missing)}"
        # All values must be in [0, 1].
        for key in required:
            value = float(params[key])
            assert 0.0 <= value <= 1.0, (
                f"{biome_id}.{key}={value} out of [0, 1]"
            )
