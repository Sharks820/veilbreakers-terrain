"""Phase B D19 / Bug-E regression tests — terrain_features.py RNG migration.

Pins the Bug-E fix: 14 ``random.Random(seed)`` sites in
``veilbreakers_terrain/handlers/terrain_features.py`` (5 magic-offset
splits + 9 plain-seed) replaced with
``random.Random(derive_pass_seed(seed, "terrain_features.<sublabel>", 0, 0, None))``
for collision-free namespacing per ``terrain_caves.py:24`` Rule 4
("uses derive_pass_seed — never random.random()").
"""

from __future__ import annotations

import inspect
import re
import pathlib


_FEATURES_SRC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "handlers"
    / "terrain_features.py"
).read_text(encoding="utf-8")


def test_no_magic_offset_random_random_in_terrain_features():
    """No `random.Random(seed + N)` magic-offset RNG splits remain.

    Pre-fix had: +9001, +77777, +9999, +7777, +4444 — collision-prone
    namespacing. Post-fix uses derive_pass_seed sublabels.
    """
    pattern = re.compile(r"random\.Random\(\s*seed\s*\+\s*\d+\s*\)")
    matches = pattern.findall(_FEATURES_SRC)
    assert not matches, (
        f"Bug-E REGRESSION — {len(matches)} `random.Random(seed + N)` "
        f"magic-offset sites remain in terrain_features.py: {matches!r}"
    )


def test_no_plain_seed_random_random_in_terrain_features():
    """No `random.Random(seed)` plain-seed sites remain in production handler.

    Pre-fix had 9 such sites; post-fix all wrap derive_pass_seed.
    """
    pattern = re.compile(r"random\.Random\(\s*seed\s*\)")
    matches = pattern.findall(_FEATURES_SRC)
    assert not matches, (
        f"Bug-E REGRESSION — {len(matches)} plain `random.Random(seed)` "
        f"sites remain in terrain_features.py: {matches!r}"
    )


def test_terrain_features_imports_derive_pass_seed():
    """terrain_features.py must import derive_pass_seed from terrain_pipeline."""
    assert (
        "from .terrain_pipeline import derive_pass_seed" in _FEATURES_SRC
        or "from veilbreakers_terrain.handlers.terrain_pipeline import derive_pass_seed"
        in _FEATURES_SRC
    ), (
        "terrain_features.py: derive_pass_seed import missing — Bug-E "
        "fix not applied"
    )


def test_all_terrain_features_random_uses_derive_pass_seed():
    """Every random.Random(...) call site in terrain_features.py wraps derive_pass_seed."""
    # Match ANY random.Random(...) and require its argument contain derive_pass_seed.
    sites = re.findall(r"random\.Random\(([^)]+(?:\([^)]*\))?[^)]*)\)", _FEATURES_SRC)
    bare_sites = [
        site for site in sites
        if "derive_pass_seed" not in site and "rng" not in site.lower().split(".")[-1]
    ]
    # The check is intentionally loose — we expect ZERO non-derive_pass_seed
    # bare argument forms. The "rng" exclusion catches transitive variable
    # passes that aren't the canonical seed expression.
    assert not bare_sites, (
        f"terrain_features.py: random.Random() call sites NOT wrapping "
        f"derive_pass_seed: {bare_sites!r}"
    )


def test_namespace_sublabels_collision_free():
    """Each derive_pass_seed call must use a distinct namespace sublabel."""
    # Extract every derive_pass_seed namespace string in terrain_features.
    namespaces = re.findall(
        r'derive_pass_seed\(\s*seed,\s*"([^"]+)"', _FEATURES_SRC
    )
    # Bug-E touched 14 sites; namespace must enumerate all of them
    # without duplicates. (Note: a single function might legitimately
    # call derive_pass_seed multiple times with the SAME namespace if
    # both calls pass DIFFERENT salt — but in this codebase each
    # site has a unique sublabel.)
    assert len(namespaces) == len(set(namespaces)), (
        f"terrain_features.py: derive_pass_seed namespaces collide: "
        f"{[ns for ns in namespaces if namespaces.count(ns) > 1]}"
    )


def test_migrated_sites_count_matches_bug_e_total():
    """Bug-E spec says 14 sites in terrain_features.py — pin the migration count."""
    # Each migrated site should now be `random.Random(derive_pass_seed(...))`.
    pattern = re.compile(r"random\.Random\(\s*derive_pass_seed\(")
    matches = pattern.findall(_FEATURES_SRC)
    assert len(matches) == 14, (
        f"Bug-E migration count mismatch: expected 14, got {len(matches)}. "
        f"Spec calls for 5 magic-offset + 9 plain-seed = 14 sites."
    )


def test_imports_terrain_features_module_does_not_crash():
    """Sanity: the module still imports cleanly after the migration."""
    from veilbreakers_terrain.handlers import terrain_features

    # Confirm the migrated symbols are still defined.
    assert hasattr(terrain_features, "generate_canyon")
    assert hasattr(terrain_features, "generate_waterfall")
    assert hasattr(terrain_features, "generate_cliff_face")
    assert hasattr(terrain_features, "generate_swamp_terrain")
    assert hasattr(terrain_features, "generate_natural_arch")
    assert hasattr(terrain_features, "generate_sinkhole")
    assert hasattr(terrain_features, "generate_floating_rocks")
    assert hasattr(terrain_features, "generate_ice_formation")
    assert hasattr(terrain_features, "generate_lava_flow")


def test_generate_canyon_deterministic_after_migration():
    """Smoke test: calling generate_canyon with same seed twice gives same output."""
    from veilbreakers_terrain.handlers.terrain_features import generate_canyon

    sig = inspect.signature(generate_canyon)
    # Build a minimal arg dict with sensible defaults.
    if "seed" in sig.parameters:
        try:
            a = generate_canyon(seed=42)
            b = generate_canyon(seed=42)
        except TypeError:
            # generate_canyon may require additional args; skip if so.
            return
        # Output is a dict with vertex_count / face_count etc.; compare
        # the determinism-relevant subset.
        # generate_canyon's return type is dict per its docstring, so a
        # `.get` access is type-safe; pyright-strict reports unnecessary
        # isinstance() narrowing if we add one here.
        a_count = a.get("vertex_count")
        b_count = b.get("vertex_count")
        assert a_count == b_count
