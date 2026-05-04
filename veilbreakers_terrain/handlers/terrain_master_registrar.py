"""Master registrar for the VeilBreakers terrain pipeline.

Single-call entrypoint that brings up every registered pass across
bundles A–O. Use this from Blender-side startup, tests, or the MCP
handler bridge to ensure the full pipeline is available.

Usage:
    from blender_addon.handlers.terrain_master_registrar import (
        register_all_terrain_passes,
    )
    register_all_terrain_passes()
    # Now TerrainPassController.PASS_REGISTRY contains every pass.

Individual bundle registrars remain callable for tests that want to
exercise a single bundle in isolation.

Bundle inventory (complete A–O):
    A — foundation (terrain_pipeline.register_default_passes)
    B — cliffs + materials (terrain_cliffs, terrain_materials_v2)
    C — waterfall hydrology (terrain_waterfalls)
    D — validation + checkpoints (terrain_validation, terrain_checkpoints)
    E — scatter intelligence (terrain_assets)
    F — cave archetypes (terrain_caves)
    G — banded noise (terrain_banded)
    H — composition & intent (terrain_saliency/framing)
    I — geology plausibility (terrain_geology_validator)
    J — ecosystem spine (terrain_bundle_j)
    K — material ceiling (terrain_bundle_k)
    L — atmosphere & horizon (terrain_bundle_l)
    M — iteration velocity (extension modules, no new passes)
    N — deep validation & QA (terrain_bundle_n)
    O — water + vegetation depth (terrain_bundle_o)

Registration order rationale (critical for non-DAG execution)
-------------------------------------------------------------
When ``TerrainPassController`` runs passes in registration order (i.e.
callers that don't go through ``PassDAG``), the order below must place
height-modifying passes BEFORE any downstream scatter / materials /
validation work. The order enforces:

    A                       →  baseline height + slope + erosion
    B-cliffs                →  cliff_candidate (reads slope/height only)
    G (banded_macro)        →  refines height BEFORE scatter sees it
    H-framing               →  cuts sightlines BEFORE scatter sees height
    F (caves)               →  carves cave_height_delta BEFORE materials
    I (geology)             →  wind/glacial/coastline/karst deltas
    C (waterfalls)          →  waterfall_pool_delta + lip masks
    B-materials             →  splatmap after all height mutators done
    E (scatter_intelligent) →  assets placed on FINAL height + materials
    D (validation_full)     →  validates the finished tile
    H-saliency (refine)     →  post-hoc saliency refinement
    J, K, L, N, O           →  secondary channels (atmosphere, water)

Prior to the 2026-04-18 audit, E registered before G/H/F/I, so scatter
placed trees on a pre-erosion, pre-carve heightmap — the tree-root-in-
mid-air bug. See docs/aaa-audit for the regression record.

AAA terrain generator comparison
--------------------------------
World Machine (Quadspinner's predecessor) builds terrain via macro →
thermal erosion → hydraulic erosion → flow analysis → texturing →
scatter. Our pipeline matches this flow after the registration-order
fix: A (macro + erosion) → I (thermal/wind/glacial) → C (hydrology) →
B-materials (texturing) → E (scatter).

Houdini HeightField SOPs layer noise → geological features → erosion
SOP (hydraulic/thermal) → hydrology (river solve) → material assign →
scatter. Our bundles B-cliffs + G + H + F + I collectively mirror the
"geological features" band; C mirrors hydrology; B-materials mirrors
the "material assign" and E mirrors scatter.

Gaea (QuadSpinner) exposes a node graph with explicit channel edges —
identical to our PassDAG's ``requires_channels`` / ``produces_channels``
pairs. Gaea's production-tier erosion runs 48+ iterations, which is
exactly the aaa_open_world quality profile.

SpeedTree ecosystem integration respects slope/height/material inputs
when placing vegetation — our ``scatter_intelligent`` pass reads those
channels (hard-required via ``requires_channels``) plus optional
``cliff_candidate`` / ``cave_candidate`` / ``waterfall_lip_candidate``
masks via ``stack.get(...)``. Parity after the bundle-order fix.

Unreal Engine 5 Landscape + Virtual Texture streaming requires a
minimum 16-bit splatmap and 32-bit height for production tiles. Our
aaa_open_world and hero_shot profiles match UE5's production settings;
the production profile (post-audit) is also 16-bit splatmap / 32-bit
height so shipped terrain never regresses below UE5's VT minimum.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bundle registrar lookup — one import per bundle
# ---------------------------------------------------------------------------


def _safe_import_registrar(module_path: str, attr: str) -> Callable[[], None] | None:
    """Return a callable bundle registrar, or None if the module is missing.

    This lets the master registrar degrade gracefully if a bundle is being
    rebuilt in a worktree or selectively disabled — the rest still loads.

    Import failures are logged as warnings so they don't vanish silently
    (Fix M5).
    """
    try:
        module = __import__(module_path, fromlist=[attr])
        fn = getattr(module, attr, None)
        return fn if callable(fn) else None
    except Exception as exc:
        logger.warning(
            "Failed to import bundle registrar %s.%s: %r", module_path, attr, exc
        )
        return None


# ---------------------------------------------------------------------------
# Master registrar
# ---------------------------------------------------------------------------


def register_all_terrain_passes(
    *, strict: bool = False,
) -> List[str]:
    """Invoke every bundle registrar. Returns the list of bundles loaded.

    Parameters
    ----------
    strict : bool
        If True, raise on any missing bundle registrar. If False (default),
        skip missing bundles so partial environments still work — but log
        warnings and collect errors for callers that want to inspect them.

    Returns
    -------
    List[str]
        Labels of bundles loaded. Failed bundles appear as
        ``"LABEL:SKIPPED(reason)"``.

    Notes
    -----
    Callers that need structured error info can call
    ``register_all_terrain_passes_detailed()`` instead, which returns a
    ``(loaded, errors)`` tuple.
    """
    loaded, _errors = _register_all_terrain_passes_impl(strict=strict)
    return loaded


def register_all_terrain_passes_detailed(
    *, strict: bool = False,
) -> Tuple[List[str], List[Tuple[str, Exception]]]:
    """Like :func:`register_all_terrain_passes` but also returns errors.

    Returns
    -------
    (loaded, errors)
        *loaded* — same list as the non-detailed variant.
        *errors* — list of ``(label, exception)`` for every bundle that
        failed to import or register.
    """
    return _register_all_terrain_passes_impl(strict=strict)


def _register_all_terrain_passes_impl(
    *, strict: bool = False,
) -> Tuple[List[str], List[Tuple[str, Exception]]]:
    """Shared implementation for both public registration entry-points.

    Upgrades over the prior B-grade implementation
    ------------------------------------------------
    1. **Duplicate pass-name detection**: after each bundle registers, the
       full PASS_REGISTRY is scanned for names that appear more than once.
       Duplicates are logged at WARNING and, when ``strict=True``, raise
       ``ValueError`` immediately.  This catches accidental double-registration
       (e.g. a bundle that calls ``register_default_passes`` internally) that
       would otherwise silently overwrite an earlier pass.

    2. **Registration summary log**: after all bundles load, a single INFO
       line records the bundle count, pass count, and any skipped bundles so
       the summary is visible in production logs without requiring DEBUG level.

    3. **Pre-registration snapshot**: the registry size before Bundle A is
       recorded so the summary can report net-new passes added by this call
       (useful when the registrar is called more than once in a test run).
    """
    from .terrain_pipeline import TerrainPassController

    loaded: List[str] = []
    errors: List[Tuple[str, Exception]] = []

    pre_reg_size = len(TerrainPassController.PASS_REGISTRY)

    # Bundle A — foundation (always required)
    from .terrain_pipeline import register_default_passes

    register_default_passes(strict=strict)
    loaded.append("A")

    package_root = __package__ or __name__.rpartition(".")[0]
    assert package_root.startswith("veilbreakers_terrain")

    # ------------------------------------------------------------------
    # Registration order (critical): see the docstring "Registration order
    # rationale" section. Height-modifying passes register BEFORE scatter,
    # materials, and validation.
    # ------------------------------------------------------------------
    registrars: list[tuple[str, str, str]] = [
        # Geology candidate analysis (reads slope only; doesn't modify height)
        ("B-cliffs", f"{package_root}.terrain_cliffs", "register_bundle_b_passes"),
        # Height mutators — MUST run before scatter/materials
        ("G", f"{package_root}.terrain_banded", "register_bundle_g_passes"),
        ("H-morphology", f"{package_root}.terrain_morphology", "register_morphology_pass"),
        ("H-terrain-features", f"{package_root}.terrain_features", "register_terrain_features_pass"),
        ("H-framing", f"{package_root}.terrain_framing", "register_framing_pass"),
        ("F", f"{package_root}.terrain_caves", "register_bundle_f_passes"),
        ("I", f"{package_root}.terrain_geology_validator", "register_bundle_i_passes"),
        ("I-glacial", f"{package_root}.terrain_glacial", "register_glacial_pass"),
        ("P-lava", f"{package_root}.terrain_lava", "register_lava_pass"),
        ("P-talus", f"{package_root}.terrain_talus", "register_talus_pass"),
        ("C", f"{package_root}.terrain_waterfalls", "register_bundle_c_passes"),
        # FIX-B14-6: road network DAG pass — BEFORE scatter so road_sdf_dist
        # is available to scatter_intelligent / procedural_grass consumers.
        ("road-network", f"{package_root}.road_network", "register_road_network_pass"),
        # Material + scatter (consume final height + all candidate masks)
        ("B-materials", f"{package_root}.terrain_materials_v2", "register_bundle_b_material_passes"),
        ("E", f"{package_root}.terrain_assets", "register_bundle_e_passes"),
        ("H-procedural-grass", f"{package_root}.procedural_grass", "register_procedural_grass_pass"),
        # Post-geometry validation + refinement
        ("D", f"{package_root}.terrain_validation", "register_bundle_d_passes"),
        ("H-saliency", f"{package_root}.terrain_saliency", "register_saliency_pass"),
        # Secondary channels (atmosphere, water, ecology, LOD)
        ("J", f"{package_root}.terrain_bundle_j", "register_bundle_j_passes"),
        ("K", f"{package_root}.terrain_bundle_k", "register_bundle_k_passes"),
        ("L", f"{package_root}.terrain_bundle_l", "register_bundle_l_passes"),
        ("L-atmospheric-volumes", f"{package_root}.atmospheric_volumes", "register_atmospheric_volumes_pass"),
        ("N", f"{package_root}.terrain_bundle_n", "register_bundle_n_passes"),
        ("O", f"{package_root}.terrain_bundle_o", "register_bundle_o_passes"),
        # Seasonal water mutation — secondary writer of water_surface_mask/tidal/wetness.
        # MUST register after Bundle O (water_variants) and Bundle I (coastline) so
        # those passes own the channels first and pass_seasonal_water_state can use
        # overrides=(...) to declare intentional secondary writes.
        ("O-seasonal-water", f"{package_root}.terrain_water_variants", "register_pass_seasonal_water_state"),
    ]

    # Track pass names seen so far to detect duplicates across bundles.
    seen_pass_names: dict[str, str] = {
        name: "A" for name in TerrainPassController.PASS_REGISTRY
    }

    for label, module_path, attr in registrars:
        fn = _safe_import_registrar(module_path, attr)
        if fn is not None:
            # Snapshot registry before this bundle registers
            before_registry = dict(TerrainPassController.PASS_REGISTRY)
            before = set(before_registry.keys())
            try:
                fn()
                loaded.append(label)
            except Exception as exc:
                if strict:
                    raise
                logger.warning("Bundle %s registration failed: %r", label, exc)
                loaded.append(f"{label}:SKIPPED({exc!r})")
                errors.append((label, exc))
                continue

            # Duplicate detection: any pass that existed before this bundle
            # and is STILL in the registry was not overwritten; new passes
            # added by this bundle may collide with ones from an earlier bundle.
            after = set(TerrainPassController.PASS_REGISTRY.keys())
            new_passes = after - before
            for pname in new_passes:
                if pname in seen_pass_names:
                    msg = (
                        f"Duplicate pass name {pname!r}: first registered by "
                        f"bundle {seen_pass_names[pname]!r}, now re-registered "
                        f"by bundle {label!r}. The later registration wins."
                    )
                    logger.warning(msg)
                    if strict:
                        raise ValueError(msg)
                seen_pass_names[pname] = label
            overwritten_passes = [
                pname
                for pname in before.intersection(after)
                if TerrainPassController.PASS_REGISTRY.get(pname) is not before_registry[pname]
            ]
            for pname in overwritten_passes:
                msg = (
                    f"Duplicate pass name {pname!r}: existing registration from "
                    f"bundle {seen_pass_names.get(pname, 'unknown')!r} was overwritten "
                    f"by bundle {label!r}. The later registration wins."
                )
                logger.warning(msg)
                if strict:
                    raise ValueError(msg)
                seen_pass_names[pname] = label
        else:
            if strict:
                err = ImportError(
                    f"Bundle {label} registrar not found: {module_path}.{attr}"
                )
                raise err
            # _safe_import_registrar already logged the warning; record it
            # so callers using the detailed API can inspect.
            errors.append(
                (label, ImportError(f"registrar not found: {module_path}.{attr}"))
            )

    # Registry graph warnings
    for _w in TerrainPassController.validate_registry_graph():
        logger.warning("Registry graph: %s", _w)

    # Registration summary
    total_passes = len(TerrainPassController.PASS_REGISTRY)
    net_new = total_passes - pre_reg_size
    clean_bundles = [b for b in loaded if "SKIPPED" not in b]
    skipped_bundles = [b for b in loaded if "SKIPPED" in b]
    logger.info(
        "Terrain pass registration complete: %d bundles loaded, "
        "%d total passes (%d net-new), %d skipped. Skipped: %s",
        len(clean_bundles),
        total_passes,
        net_new,
        len(skipped_bundles),
        skipped_bundles or "none",
    )

    return loaded, errors


__all__ = [
    "register_all_terrain_passes",
    "register_all_terrain_passes_detailed",
]
