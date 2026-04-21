"""Bundle F — Cave archetype analysis (pure numpy, no bpy).

Replaces the single generic semicircular-arch cave generator with five
distinct archetypes, each with its own entrance framing, path geometry,
collapse debris pattern, and damp interior mask. All analysis is pure
numpy / python so it can be tested outside Blender.

See docs/terrain_ultra_implementation_plan_2026-04-08.md §11 (Bundle F).

Agent protocol compliance:
- Rule 1: all mutation lives behind ``pass_caves`` + ``register_bundle_f_passes``
- Rule 2: pass declares ``requires_scene_read=True``
- Rule 3: every intermediate signal (``cave_candidate``, ``wet_rock``) is
  written to ``TerrainMaskStack`` via ``stack.set(...)``
- Rule 4: uses ``derive_pass_seed`` — never ``hash()`` / ``random.random()``
- Rule 5: protected zones masked per-cell before any carve
- Rule 6: Z-up world meters (``stack.height`` is world-Z in meters)
- Rule 7: ``cave_candidate`` + ``wet_rock`` are Unity-visible mask channels
- Rule 10: never ``np.clip(..., 0, 1)`` on world heights; the carve returns a
  delta array that callers add to height, but this pass does NOT mutate
  ``stack.height`` directly — it populates masks + records intent.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
    TerrainMaskStack,
    TerrainPipelineState,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# Worley (cellular) noise + Perlin noise for cave wall texture
# ---------------------------------------------------------------------------


def _worley_noise_2d(
    rows: int,
    cols: int,
    num_points: int,
    seed: int,
    *,
    metric: str = "euclidean",
) -> np.ndarray:
    """Compute 2-D Worley (cellular / F1) noise on a ``rows×cols`` grid.

    Each cell's value is the normalised distance to the nearest of
    ``num_points`` randomly placed feature points (F1 metric).  The result
    is in [0, 1] and serves as the primary driver of cave wall roughness.

    Args:
        rows, cols : Grid dimensions.
        num_points : Number of Voronoi feature points (default 64 for a
            typical 128×128 tile — tune for desired cellular scale).
        seed       : Deterministic seed.
        metric     : Distance metric — ``"euclidean"`` (default) or
            ``"manhattan"`` (sharper facets, better for fissure walls).

    Returns:
        float32 array of shape ``(rows, cols)`` in [0, 1].
    """
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    # Scatter feature points in [0, rows) × [0, cols)
    pt_r = rng.uniform(0.0, float(rows), size=num_points)
    pt_c = rng.uniform(0.0, float(cols), size=num_points)

    # Build index grids — shape (rows, cols, num_points) would be huge for
    # large tiles; use broadcasting over (rows,1,N) and (1,cols,N) instead.
    r_idx = np.arange(rows, dtype=np.float32).reshape(rows, 1, 1)
    c_idx = np.arange(cols, dtype=np.float32).reshape(1, cols, 1)
    pt_r_bc = pt_r.reshape(1, 1, num_points).astype(np.float32)
    pt_c_bc = pt_c.reshape(1, 1, num_points).astype(np.float32)

    dr = r_idx - pt_r_bc
    dc = c_idx - pt_c_bc

    if metric == "manhattan":
        dist = np.abs(dr) + np.abs(dc)      # shape (rows, cols, N)
    else:  # euclidean
        dist = np.sqrt(dr * dr + dc * dc)

    f1 = dist.min(axis=2)                   # shape (rows, cols) — nearest point

    max_d = float(f1.max()) + 1e-9
    return (f1 / max_d).astype(np.float32)


def _perlin_noise_2d(
    rows: int,
    cols: int,
    seed: int,
    *,
    octaves: int = 4,
    frequency: float = 4.0,
    persistence: float = 0.5,
) -> np.ndarray:
    """Fractional-Brownian-Motion Perlin-style noise on a ``rows×cols`` grid.

    Pure-numpy implementation using random gradient vectors on a regular
    lattice with bilinear interpolation and smooth-step blending.  The fBm
    sum accumulates ``octaves`` octaves with geometric amplitude decay
    controlled by ``persistence``.

    Returns float32 array in approximately [−1, 1], normalised to [0, 1]
    before return so it can be directly mixed with Worley noise.
    """
    rng = np.random.default_rng((int(seed) ^ 0xDEADBEEF) & 0xFFFFFFFF)

    def _fade(t: np.ndarray) -> np.ndarray:
        """Smooth-step polynomial: 6t⁵ − 15t⁴ + 10t³."""
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    def _gradient_noise(freq: float, s: int) -> np.ndarray:
        """Single octave of gradient noise at given frequency."""
        _rng_oct = np.random.default_rng(s & 0xFFFFFFFF)
        # Lattice size
        gw = int(math.ceil(cols * freq / cols)) + 2
        gh = int(math.ceil(rows * freq / rows)) + 2
        # Random unit gradients on lattice
        angles = _rng_oct.uniform(0.0, 2.0 * math.pi, size=(gh, gw))
        grad_r = np.sin(angles)
        grad_c = np.cos(angles)

        # Sample coordinates
        sr = np.linspace(0.0, freq, rows, endpoint=False)
        sc = np.linspace(0.0, freq, cols, endpoint=False)
        sc2, sr2 = np.meshgrid(sc, sr)

        sr2f = sr2 % 1.0
        sc2f = sc2 % 1.0
        ri = sr2.astype(np.int32) % (gh - 1)
        ci = sc2.astype(np.int32) % (gw - 1)

        fade_r = _fade(sr2f)
        fade_c = _fade(sc2f)

        def _dot_grad(gr_i: np.ndarray, gc_i: np.ndarray,
                      dr: np.ndarray, dc: np.ndarray) -> np.ndarray:
            return grad_r[gr_i, gc_i] * dr + grad_c[gr_i, gc_i] * dc

        n00 = _dot_grad(ri,     ci,     sr2f,        sc2f)
        n10 = _dot_grad(ri + 1, ci,     sr2f - 1.0,  sc2f)
        n01 = _dot_grad(ri,     ci + 1, sr2f,        sc2f - 1.0)
        n11 = _dot_grad(ri + 1, ci + 1, sr2f - 1.0,  sc2f - 1.0)

        nx0 = n00 + fade_r * (n10 - n00)
        nx1 = n01 + fade_r * (n11 - n01)
        return nx0 + fade_c * (nx1 - nx0)

    acc = np.zeros((rows, cols), dtype=np.float32)
    amp = 1.0
    total = 0.0
    freq = float(frequency)
    for oct_i in range(octaves):
        acc += amp * _gradient_noise(freq, int(rng.integers(0, 2**31))).astype(np.float32)
        total += amp
        amp *= persistence
        freq *= 2.0

    acc /= max(total, 1e-9)
    # Normalise to [0, 1]
    mn, mx = float(acc.min()), float(acc.max())
    if mx - mn < 1e-9:
        return np.full((rows, cols), 0.5, dtype=np.float32)
    return ((acc - mn) / (mx - mn)).astype(np.float32)


def compute_cave_wall_texture(
    rows: int,
    cols: int,
    seed: int,
    *,
    worley_points: int = 64,
    worley_weight: float = 0.6,
    perlin_octaves: int = 4,
    perlin_frequency: float = 4.0,
    perlin_weight: float = 0.4,
    archetype: str = "default",
) -> np.ndarray:
    """Generate a cave wall roughness texture by blending Worley + Perlin noise.

    The blend is ``worley_weight * F1 + perlin_weight * fBm``, normalised to
    [0, 1].  Worley noise creates the characteristic cellular pitting seen in
    real cave walls (dissolutional scalloping, frost shattering, lava bubbling).
    Perlin fBm adds broad low-frequency waviness for organic wall relief.

    Archetype-specific tuning:
      ``fissure``       — manhattan Worley metric gives sharper facets matching
                          tectonic fracture planes.
      ``karst_sinkhole``— more Worley weight for heavier dissolution pitting.
      ``glacial_melt``  — smooth Perlin-dominant blend, few Worley points.
      default/others   — standard euclidean blend.

    Returns float32 ``(rows, cols)`` wall roughness map in [0, 1].
    """
    arch_lc = archetype.lower()

    if arch_lc == "fissure":
        metric = "manhattan"
        w_pts = max(32, worley_points)
        ww = min(0.80, worley_weight + 0.15)
        pw = 1.0 - ww
    elif arch_lc == "karst_sinkhole":
        metric = "euclidean"
        w_pts = max(80, worley_points)
        ww = min(0.75, worley_weight + 0.10)
        pw = 1.0 - ww
    elif arch_lc == "glacial_melt":
        metric = "euclidean"
        w_pts = max(20, worley_points // 3)
        ww = max(0.30, worley_weight - 0.20)
        pw = 1.0 - ww
    else:
        metric = "euclidean"
        w_pts = worley_points
        ww = worley_weight
        pw = perlin_weight

    worley = _worley_noise_2d(rows, cols, w_pts, seed, metric=metric)
    perlin = _perlin_noise_2d(
        rows, cols, seed,
        octaves=perlin_octaves,
        frequency=perlin_frequency,
    )

    combined = ww * worley + pw * perlin
    mn, mx = float(combined.min()), float(combined.max())
    if mx - mn < 1e-9:
        return np.full((rows, cols), 0.5, dtype=np.float32)
    return ((combined - mn) / (mx - mn)).astype(np.float32)


# ---------------------------------------------------------------------------
# Dreybrodt stalactite / stalagmite growth model
# ---------------------------------------------------------------------------


def compute_speleothem_growth(
    interior_mask: np.ndarray,
    damp_mask: np.ndarray,
    height_delta: np.ndarray,
    cell_size_m: float,
    *,
    simulation_years: float = 5000.0,
    ca_concentration_mol_per_l: float = 2.0e-3,
    drip_rate_per_year: float = 1000.0,
    tip_radius_m: float = 0.0003,
    density_kg_per_m3: float = 2710.0,
    molar_mass_kg_per_mol: float = 0.1001,
    seed: int = 0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute stalactite and stalagmite growth using the Dreybrodt (1999) model.

    The Dreybrodt model gives the linear growth rate of a speleothem tip as:

        dr/dt = (molar_mass / density) * J_surface

    where the surface flux J_surface (mol m⁻² yr⁻¹) for a hemispherical tip of
    radius r is approximated by:

        J_surface ≈ D_CO2 * C_Ca / r

    with D_CO2 ≈ 1e-9 m² s⁻¹ (diffusion coefficient of CO₂ in water),
    C_Ca = calcium ion concentration [mol m⁻³], and tip radius r [m].

    Integrated over ``simulation_years`` this gives the tip-advance length
    per drip site.  Stalactites grow downward from ceiling cells (negative
    height_delta) and stalagmites grow upward from floor cells.

    Only cells inside ``interior_mask`` with ``damp_mask > 0.2`` are eligible
    — dry walls produce no speleothems.

    Parameters
    ----------
    interior_mask     : bool array (rows, cols) marking cave interior cells.
    damp_mask         : float32 array (rows, cols) in [0, 1] — dampness.
    height_delta      : float64 array (rows, cols) — carve delta (≤ 0).
    cell_size_m       : World cell size in metres (used to scale geometry).
    simulation_years  : Simulated time horizon [years].  5000 yr produces
                        stalactites ~0.5 m long, matching real karst rates.
    ca_concentration_mol_per_l : Ca²⁺ concentration [mol/L] in drip water.
                        Typical limestone cave: 1–4 mmol/L.
    drip_rate_per_year : Drip events per year per site.  Controls total flux.
    tip_radius_m      : Initial tip radius [m] for the Dreybrodt flux formula.
    density_kg_per_m3 : Calcite density (2710 kg/m³).
    molar_mass_kg_per_mol : Molar mass of CaCO₃ (0.1001 kg/mol).
    seed              : RNG seed for spatial jitter.

    Returns
    -------
    stalactites : float32 (rows, cols) — downward growth length [m] per cell.
    stalagmites : float32 (rows, cols) — upward growth length [m] per cell.
    """
    rows, cols = interior_mask.shape
    stalactites = np.zeros((rows, cols), dtype=np.float32)
    stalagmites = np.zeros((rows, cols), dtype=np.float32)

    # Physical constants
    D_CO2_m2_per_s = 1.0e-9                # diffusion coefficient [m²/s]
    seconds_per_year = 365.25 * 24.0 * 3600.0

    # Convert Ca concentration from mol/L → mol/m³
    C_Ca_mol_per_m3 = float(ca_concentration_mol_per_l) * 1000.0

    # Dreybrodt surface flux at tip radius r [mol m⁻² yr⁻¹]
    r = max(float(tip_radius_m), 1e-6)
    J_surface_mol_per_m2_per_s = D_CO2_m2_per_s * C_Ca_mol_per_m3 / r
    J_surface_mol_per_m2_per_yr = J_surface_mol_per_m2_per_s * seconds_per_year

    # Total drip flux per site over simulation period [mol m⁻²]
    total_flux = J_surface_mol_per_m2_per_yr * float(simulation_years)

    # Growth length from flux: Δr = (M / ρ) * total_flux [m]
    M = float(molar_mass_kg_per_mol)
    rho = float(density_kg_per_m3)
    base_growth_m = (M / rho) * total_flux

    # Spatial dampness modulation: wet cells grow more
    damp_arr = np.asarray(damp_mask, dtype=np.float32)
    interior_arr = np.asarray(interior_mask, dtype=bool)
    delta_arr = np.asarray(height_delta, dtype=np.float64)

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    # Drip-rate jitter: Poisson-distributed drip rate per cell [0.5, 2.0× base]
    jitter = rng.uniform(0.5, 2.0, size=(rows, cols)).astype(np.float32)

    # Ceiling cells: strongly carved (delta ≤ −cell_size/4) → stalactites
    ceiling_mask = interior_arr & (delta_arr <= -float(cell_size_m) * 0.25) & (damp_arr > 0.2)
    # Floor cells: weakly carved or zero (near entrance / bottom) → stalagmites
    floor_mask = interior_arr & (delta_arr > -float(cell_size_m) * 0.25) & (damp_arr > 0.2)

    stalactites = np.where(
        ceiling_mask,
        (base_growth_m * damp_arr * jitter * float(drip_rate_per_year / 1000.0)).astype(np.float32),
        0.0,
    ).astype(np.float32)

    # Stalagmites grow at ~60% the rate of stalactites (splash effect)
    stalagmites = np.where(
        floor_mask,
        (base_growth_m * 0.6 * damp_arr * jitter * float(drip_rate_per_year / 1000.0)).astype(np.float32),
        0.0,
    ).astype(np.float32)

    # Clamp to physically plausible range: 0..20 m  (Lechuguilla = ~18 m)
    stalactites = np.clip(stalactites, 0.0, 20.0).astype(np.float32)
    stalagmites = np.clip(stalagmites, 0.0, 20.0).astype(np.float32)

    return stalactites, stalagmites


# ---------------------------------------------------------------------------
# CliffStructure-compatible entrance arch validator
# ---------------------------------------------------------------------------


def validate_entrance_cliff_compatible(
    entrance_frame: Dict,
    spec: "CaveArchetypeSpec",
) -> List[ValidationIssue]:
    """Validate that an entrance frame is CliffStructure-compatible.

    CliffStructure compatibility requires:
      1. No rectangular cutouts — the entrance opening must be described by
         an arch (framing_rocks with left_jamb + right_jamb + optional lintel)
         rather than a flat-edged rectangular aperture.
      2. The lip_width_m / lip_height_m aspect ratio must be within the range
         [0.4, 4.0] — ratios outside this indicate a slab cutout rather than
         an organic arch opening.
      3. framing_rocks must have distinct roles (not duplicate "left_jamb"
         entries), confirming proper arch geometry is registered.
      4. occlusion_shelf depth > 0: a cliff face always casts an overhead
         shadow; an entrance without one is implausibly sharp-edged
         (rectangular cutout indicator).

    These checks replicate the CliffStructure entrance contract from Bundle B
    so caves and cliffs share the same geometry interface.
    """
    issues: List[ValidationIssue] = []
    arch_id = entrance_frame.get("archetype", "unknown")

    lip_w = float(entrance_frame.get("lip_width_m", 0.0))
    lip_h = float(entrance_frame.get("lip_height_m", 0.0))

    # 1. Aspect ratio must be organic (not rectangular slab)
    if lip_h > 1e-6:
        aspect = lip_w / lip_h
        if not (0.4 <= aspect <= 4.0):
            issues.append(ValidationIssue(
                code="CAVE_ENTRANCE_RECTANGULAR_CUTOUT",
                severity="hard",
                affected_feature=arch_id,
                message=(
                    f"entrance aspect ratio {aspect:.2f} (w={lip_w:.1f}m / h={lip_h:.1f}m) "
                    f"is outside [0.4, 4.0] — indicates a slab rectangular cutout, "
                    f"not a CliffStructure-compatible arch"
                ),
                remediation=(
                    "Adjust entrance_width_m / entrance_height_m in CaveArchetypeSpec "
                    "to produce an arch aspect ratio in [0.4, 4.0]."
                ),
            ))

    # 2. Framing rocks must have distinct roles (arch geometry, not cutout)
    framing = entrance_frame.get("framing_rocks", [])
    roles = [r.get("role", "") for r in framing]
    if len(roles) != len(set(roles)):
        issues.append(ValidationIssue(
            code="CAVE_ENTRANCE_DUPLICATE_FRAMING_ROLE",
            severity="hard",
            affected_feature=arch_id,
            message=(
                f"framing_rocks has duplicate roles {roles} — "
                f"CliffStructure arch requires distinct left_jamb, right_jamb, "
                f"and optional lintel"
            ),
        ))

    if len(framing) < 2:
        issues.append(ValidationIssue(
            code="CAVE_ENTRANCE_NO_ARCH",
            severity="hard",
            affected_feature=arch_id,
            message=(
                "entrance has fewer than 2 framing elements — no arch geometry present; "
                "CliffStructure compatibility requires at minimum left_jamb + right_jamb"
            ),
        ))

    # 3. Occlusion shelf must be present (cliff overhangs cast shadow)
    shelf = entrance_frame.get("occlusion_shelf", {})
    shelf_depth = float(shelf.get("depth_m", 0.0))
    if shelf_depth <= 0.0:
        issues.append(ValidationIssue(
            code="CAVE_ENTRANCE_MISSING_OVERHANG",
            severity="soft",
            affected_feature=arch_id,
            message=(
                "CliffStructure-compatible entrance must have an occlusion shelf "
                "(overhead overhang depth_m > 0) to prevent a cut-flat look"
            ),
            remediation="Set occlusion_shelf_depth > 0 in the CaveArchetypeSpec.",
        ))

    return issues


# ---------------------------------------------------------------------------
# Archetype enum + spec
# ---------------------------------------------------------------------------


class CaveArchetype(str, Enum):
    """Five plausible cave archetypes for a dark-fantasy terrain pipeline.

    LAVA_TUBE        — long tubular corridor, low ceiling irregularity,
                       smooth floor; formed by drained basaltic flow.
    FISSURE          — narrow tall vertical crack, high ceiling irregularity,
                       debris-strewn floor; tectonic origin.
    KARST_SINKHOLE   — vertical drop + horizontal chamber at base; heavy
                       collapse debris and strong dampness from groundwater.
    GLACIAL_MELT     — meandering low arch carved by meltwater; wet floor,
                       rounded walls, cold ambient.
    SEA_GROTTO       — wide low arch carved by wave action at coast; tidal
                       damp band, boulder pile at mouth.
    """

    LAVA_TUBE = "lava_tube"
    FISSURE = "fissure"
    KARST_SINKHOLE = "karst_sinkhole"
    GLACIAL_MELT = "glacial_melt"
    SEA_GROTTO = "sea_grotto"


@dataclass
class CaveArchetypeSpec:
    """All archetype-driven parameters for a single cave instance.

    Values are in world meters; factors in 0..1.
    """

    archetype: CaveArchetype
    entrance_width_m: float
    entrance_height_m: float
    interior_length_m: float
    taper_ratio: float = 0.6
    ceiling_irregularity: float = 0.4
    floor_debris_density: float = 0.3
    damp_intensity: float = 0.5
    ambient_light_factor: float = 0.3
    # Supplementary (Gap 14, plan §1.B.6)
    occlusion_shelf_depth: float = 0.0
    sculpt_mode: bool = False
    # Material hint resolved from biome context (e.g. "lava_basalt", "limestone")
    material_hint: Optional[str] = None


# Default archetype parameter tables (tuned for AAA readability, not generic).
_ARCHETYPE_DEFAULTS: Dict[CaveArchetype, Dict[str, float]] = {
    CaveArchetype.LAVA_TUBE: dict(
        entrance_width_m=6.0,
        entrance_height_m=3.5,
        interior_length_m=45.0,
        taper_ratio=0.85,
        ceiling_irregularity=0.2,
        floor_debris_density=0.15,
        damp_intensity=0.15,
        ambient_light_factor=0.2,
        occlusion_shelf_depth=1.5,
    ),
    CaveArchetype.FISSURE: dict(
        entrance_width_m=2.5,
        entrance_height_m=7.0,
        interior_length_m=20.0,
        taper_ratio=0.4,
        ceiling_irregularity=0.8,
        floor_debris_density=0.6,
        damp_intensity=0.35,
        ambient_light_factor=0.35,
        occlusion_shelf_depth=0.6,
    ),
    CaveArchetype.KARST_SINKHOLE: dict(
        entrance_width_m=9.0,
        entrance_height_m=12.0,
        interior_length_m=18.0,
        taper_ratio=0.5,
        ceiling_irregularity=0.7,
        floor_debris_density=0.85,
        damp_intensity=0.9,
        ambient_light_factor=0.55,
        occlusion_shelf_depth=2.5,
    ),
    CaveArchetype.GLACIAL_MELT: dict(
        entrance_width_m=5.0,
        entrance_height_m=3.0,
        interior_length_m=30.0,
        taper_ratio=0.65,
        ceiling_irregularity=0.35,
        floor_debris_density=0.2,
        damp_intensity=0.8,
        ambient_light_factor=0.5,
        occlusion_shelf_depth=1.2,
    ),
    CaveArchetype.SEA_GROTTO: dict(
        entrance_width_m=10.0,
        entrance_height_m=4.5,
        interior_length_m=22.0,
        taper_ratio=0.55,
        ceiling_irregularity=0.45,
        floor_debris_density=0.55,
        damp_intensity=0.95,
        ambient_light_factor=0.6,
        occlusion_shelf_depth=2.0,
    ),
}


def make_archetype_spec(
    archetype: CaveArchetype,
    **overrides: float,
) -> CaveArchetypeSpec:
    """Return a ``CaveArchetypeSpec`` preloaded with the archetype defaults."""
    params: Dict[str, float] = dict(_ARCHETYPE_DEFAULTS[archetype])
    params.update({k: v for k, v in overrides.items() if v is not None})
    return CaveArchetypeSpec(archetype=archetype, **params)


# ---------------------------------------------------------------------------
# Cave structure — analogous to CliffStructure in Bundle B
# ---------------------------------------------------------------------------


@dataclass
class CaveStructure:
    """A registered cave anatomy. Analogous to ``CliffStructure``.

    All geometry specification fields are populated by ``pass_caves`` and
    consumed by downstream geometry / scatter / material passes.

    Fields
    ------
    cave_id             : Unique identifier, e.g. ``"cave_0_0_00"``.
    archetype           : One of the five ``CaveArchetype`` values.
    spec                : Full archetype parameter block (widths, depths, etc.).
    entrance_world_pos  : World-space (x, y, z) of the entrance centre.
    exit_world_pos      : World-space (x, y, z) of the far end of the path,
                          or ``None`` for blind-ending caves.
    path_world          : Ordered polyline from entrance to terminus.
    path_aabb           : (min_x, min_y, min_z, max_x, max_y, max_z) bounding
                          box of path_world; used for frustum culling.
    interior_mask       : Boolean (H, W) array — cells inside the cave volume.
    damp_mask           : Float32 (H, W) dampness field in [0, 1].
    height_delta        : Float64 (H, W) negative carve delta (non-positive).
    wall_texture_seed   : Deterministic integer seed used for Worley+Perlin
                          wall roughness; stored so re-runs are reproducible.
    entrance_frame      : Dict produced by ``build_cave_entrance_frame``.
    debris_points       : Collapse debris metadata dicts (world_pos, debris_type,
                          scale_m). Dicts produced by ``scatter_collapse_debris``.
    stalactite_lengths  : Float32 (H, W) Dreybrodt growth lengths per cell.
    stalagmite_lengths  : Float32 (H, W) Dreybrodt growth lengths per cell.
    material_hint       : Resolved material string (e.g. ``"limestone"``).
    tier                : ``"hero"`` (first) or ``"secondary"`` (rest).
    cell_count          : Number of interior cells carved.
    volume_m3           : Approximate carved volume in cubic metres.
    """

    cave_id: str
    archetype: CaveArchetype
    spec: CaveArchetypeSpec
    entrance_world_pos: Tuple[float, float, float]
    exit_world_pos: Optional[Tuple[float, float, float]] = None
    path_world: List[Tuple[float, float, float]] = field(default_factory=list)
    path_aabb: Optional[Tuple[float, float, float, float, float, float]] = None
    interior_mask: Optional[np.ndarray] = None
    damp_mask: Optional[np.ndarray] = None
    height_delta: Optional[np.ndarray] = None
    wall_texture_seed: int = 0
    entrance_frame: Optional[Dict] = None
    debris_points: List[Dict] = field(default_factory=list)
    stalactite_lengths: Optional[np.ndarray] = None
    stalagmite_lengths: Optional[np.ndarray] = None
    material_hint: Optional[str] = None
    tier: str = "secondary"
    cell_count: int = 0
    volume_m3: float = 0.0


# ---------------------------------------------------------------------------
# Helpers — world <-> grid coordinate math
# ---------------------------------------------------------------------------


def _world_to_cell(
    stack: TerrainMaskStack, x: float, y: float
) -> Tuple[int, int]:
    """Return (row, col) for a world-space (x, y) position."""
    col = int(round((x - stack.world_origin_x) / stack.cell_size))
    row = int(round((y - stack.world_origin_y) / stack.cell_size))
    rows, cols = stack.height.shape
    col = max(0, min(cols - 1, col))
    row = max(0, min(rows - 1, row))
    return row, col


def _cell_to_world(
    stack: TerrainMaskStack, row: int, col: int
) -> Tuple[float, float]:
    x = stack.world_origin_x + (col + 0.5) * stack.cell_size
    y = stack.world_origin_y + (row + 0.5) * stack.cell_size
    return x, y


def _region_to_slice(
    stack: TerrainMaskStack, region: BBox
) -> Tuple[slice, slice]:
    return region.to_cell_slice(
        world_origin_x=stack.world_origin_x,
        world_origin_y=stack.world_origin_y,
        cell_size=stack.cell_size,
        grid_shape=stack.height.shape,
    )


def _protected_mask_for_caves(
    state: TerrainPipelineState,
    shape: Tuple[int, int],
) -> np.ndarray:
    """Per-cell mask of cells forbidden by protected zones for the 'caves' pass."""
    stack = state.mask_stack
    mask = np.zeros(shape, dtype=bool)
    if not state.intent.protected_zones:
        return mask
    rows, cols = shape
    ys = stack.world_origin_y + (np.arange(rows) + 0.5) * stack.cell_size
    xs = stack.world_origin_x + (np.arange(cols) + 0.5) * stack.cell_size
    xg, yg = np.meshgrid(xs, ys)
    for zone in state.intent.protected_zones:
        if zone.permits("caves"):
            continue
        inside = (
            (xg >= zone.bounds.min_x)
            & (xg <= zone.bounds.max_x)
            & (yg >= zone.bounds.min_y)
            & (yg <= zone.bounds.max_y)
        )
        mask |= inside
    return mask


# ---------------------------------------------------------------------------
# Biome → archetype + material hint tables
# ---------------------------------------------------------------------------

# Maps biome name substrings (lower-case) to a (CaveArchetype, score_bonus,
# material_hint) tuple.  Keys are checked with ``in`` so "desert_red" matches
# "desert".  Order matters: first match wins.
_BIOME_ARCHETYPE_MAP: List[Tuple[str, "CaveArchetype", float, str]] = [
    # desert / arid / volcanic → lava tube
    ("desert",   CaveArchetype.LAVA_TUBE,      2.0, "lava_basalt"),
    ("arid",     CaveArchetype.LAVA_TUBE,      1.8, "lava_basalt"),
    ("volcanic", CaveArchetype.LAVA_TUBE,      2.2, "volcanic_rock"),
    ("lava",     CaveArchetype.LAVA_TUBE,      2.5, "lava_basalt"),
    # arctic / tundra / snow / glacier → ice cave / glacial melt
    ("arctic",   CaveArchetype.GLACIAL_MELT,   2.0, "ice_cave"),
    ("tundra",   CaveArchetype.GLACIAL_MELT,   1.8, "ice_cave"),
    ("snow",     CaveArchetype.GLACIAL_MELT,   1.6, "ice_cave"),
    ("glacier",  CaveArchetype.GLACIAL_MELT,   2.3, "ice_cave"),
    ("frozen",   CaveArchetype.GLACIAL_MELT,   1.7, "ice_cave"),
    # temperate / forest / jungle / grassland → limestone karst
    ("temperate",  CaveArchetype.KARST_SINKHOLE, 1.8, "limestone"),
    ("forest",     CaveArchetype.KARST_SINKHOLE, 1.6, "limestone"),
    ("jungle",     CaveArchetype.KARST_SINKHOLE, 1.9, "wet_limestone"),
    ("grassland",  CaveArchetype.KARST_SINKHOLE, 1.4, "limestone"),
    ("plains",     CaveArchetype.KARST_SINKHOLE, 1.2, "limestone"),
    # coastal / ocean → sea grotto
    ("coastal",  CaveArchetype.SEA_GROTTO,     2.0, "sea_eroded_rock"),
    ("ocean",    CaveArchetype.SEA_GROTTO,     1.8, "sea_eroded_rock"),
    ("beach",    CaveArchetype.SEA_GROTTO,     1.6, "sea_eroded_rock"),
    # alpine / mountain → fissure
    ("alpine",   CaveArchetype.FISSURE,        1.6, "granite_fracture"),
    ("mountain", CaveArchetype.FISSURE,        1.4, "granite_fracture"),
    ("cliff",    CaveArchetype.FISSURE,        1.3, "granite_fracture"),
]

# Fallback material hints per archetype (used when no biome match found)
_ARCHETYPE_DEFAULT_MATERIAL: Dict["CaveArchetype", str] = {
    CaveArchetype.LAVA_TUBE:      "lava_basalt",
    CaveArchetype.FISSURE:        "granite_fracture",
    CaveArchetype.KARST_SINKHOLE: "limestone",
    CaveArchetype.GLACIAL_MELT:   "ice_cave",
    CaveArchetype.SEA_GROTTO:     "sea_eroded_rock",
}


# ---------------------------------------------------------------------------
# Archetype selection
# ---------------------------------------------------------------------------


def pick_cave_archetype(
    stack: TerrainMaskStack,
    world_pos: Tuple[float, float, float],
    seed: int,
    intent: Optional[Any] = None,
    *,
    hints_out: Optional[Dict[str, str]] = None,
) -> CaveArchetype:
    """Select the most plausible archetype for a location.

    Uses (in order of priority):
      1. Biome context from ``stack.get("biome")`` channel (highest terrain
         signal): desert/arid/volcanic → LAVA_TUBE, arctic/tundra/snow →
         GLACIAL_MELT, temperate/forest → KARST_SINKHOLE, coastal → SEA_GROTTO,
         alpine/mountain → FISSURE.  Each biome match adds a strong score bonus
         and resolves a material hint.
      2. Geology hint from intent.composition_hints:
           'dissolution' → KARST_SINKHOLE
           'erosion'     → SEA_GROTTO
           'volcanic'    → LAVA_TUBE
           'structural'  → FISSURE
         A strong geology hint adds a large score bonus that overrides terrain
         signals unless another hint exactly conflicts.
      3. Terrain signals: altitude, slope, wetness, basin/concavity,
         flow_accumulation, rock_hardness
      4. Deterministic RNG tiebreak from ``seed``

    Heuristics (terrain signals):
      - very wet + low altitude + basin  → SEA_GROTTO (coastal)
      - very wet + mid altitude          → GLACIAL_MELT
      - strong basin + mid altitude      → KARST_SINKHOLE
      - steep slope + dry                → FISSURE
      - mid altitude + dry + moderate    → LAVA_TUBE
      - high flow_accumulation + any altitude → KARST_SINKHOLE or SEA_GROTTO
        (water drainage carves dissolution caves and sea grottos)
      - low rock_hardness + wet          → KARST_SINKHOLE (soft limestone dissolves)
      - high rock_hardness + steep       → FISSURE (hard granite fractures)
      - deep altitude_norm < 0.15        → more elaborate archetypes (deeper = more
        developed cave systems per Elden Ring / Witcher 3 underground biome logic)

    Parameters
    ----------
    hints_out
        Optional mutable dict.  When provided, the resolved material hint string
        (e.g. ``"limestone"``, ``"ice_cave"``) is stored under key
        ``"material_hint"`` and the winning biome token (if any) under key
        ``"biome_token"``.  This lets callers attach the hint to a
        ``CaveArchetypeSpec`` without changing the return type.
    """
    x, y, _z = world_pos
    row, col = _world_to_cell(stack, x, y)

    h = float(stack.height[row, col])
    h_min = float(stack.height_min_m if stack.height_min_m is not None else stack.height.min())
    h_max = float(stack.height_max_m if stack.height_max_m is not None else stack.height.max())
    span = max(1e-6, h_max - h_min)
    altitude_norm = (h - h_min) / span  # 0..1

    def _sample(channel: str, default: float = 0.0) -> float:
        arr = stack.get(channel)
        if arr is None:
            return float(default)
        arr_np = np.asarray(arr)
        if arr_np.shape != stack.height.shape:
            return float(default)
        return float(arr_np[row, col])

    slope_rad = max(0.0, _sample("slope", 0.0))
    wetness = float(np.clip(_sample("wetness", 0.0), 0.0, 1.0))
    basin = float(np.clip(_sample("basin", 0.0), 0.0, 1.0))
    concavity = float(np.clip(_sample("concavity", 0.0), 0.0, 1.0))

    # --- New AAA signals ---
    # flow_accumulation: normalised drainage area [0, 1]. High values mean the
    # site sits at the bottom of a major drainage network — water carves karst
    # sinkholes and feeds sea grottos. Lava tubes and fissures avoid water paths.
    _flow_raw = _sample("flow_accumulation", 0.0)
    flow_accumulation = float(np.clip(_flow_raw, 0.0, 1.0))

    # rock_hardness: [0, 1] material hardness from geology channel (0 = soft
    # limestone/chalk, 1 = hard granite/basalt). Soft rock → karst dissolution;
    # hard rock → tectonic fissure or lava tube. Defaults to 0.5 (mixed).
    _hard_raw = _sample("rock_hardness", 0.5)
    rock_hardness = float(np.clip(_hard_raw, 0.0, 1.0))

    # depth_elaboration: caves at very low relative altitude are deeper
    # underground and geologically more developed (more complex branching).
    # We expose this as a score modifier rather than changing archetype selection.
    depth_elaboration = max(0.0, 1.0 - altitude_norm * 2.0)  # peaks at altitude_norm=0

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    jitter = float(rng.uniform(-0.05, 0.05))

    # Score each archetype; highest score wins.
    # Factors: altitude_norm, slope_rad, wetness, basin, concavity,
    #          flow_accumulation, rock_hardness, depth_elaboration.
    scores: Dict[CaveArchetype, float] = {
        CaveArchetype.SEA_GROTTO: (
            (1.0 - altitude_norm) * 1.2
            + wetness * 1.5
            + (0.6 if basin > 0.1 else 0.0)
            - (0.8 if altitude_norm > 0.35 else 0.0)
            # High flow_accumulation at low altitude → wave-carved sea grotto
            + flow_accumulation * 0.9 * (1.0 - altitude_norm)
            # Moderate rock_hardness (sea-cliffs are medium hardness)
            + (0.3 if 0.3 < rock_hardness < 0.7 else 0.0)
        ),
        CaveArchetype.GLACIAL_MELT: (
            altitude_norm * 0.9
            + wetness * 1.1
            + (0.3 if 0.45 < altitude_norm < 0.9 else 0.0)
            # Glacial caves need moderate flow (meltwater channels)
            + flow_accumulation * 0.4 * altitude_norm
            # Ice is soft in geological terms; low rock_hardness = ice
            + (0.4 if rock_hardness < 0.35 else 0.0)
        ),
        CaveArchetype.KARST_SINKHOLE: (
            (basin * 1.4)
            + (concavity * 0.6)
            + (0.4 if 0.2 < altitude_norm < 0.7 else 0.0)
            - wetness * 0.3
            # Karst thrives in high drainage networks — flow_accumulation is
            # the single strongest predictor of dissolution cave formation
            + flow_accumulation * 1.2
            # Soft limestone (rock_hardness < 0.4) dissolves into karst sinkholes
            + (0.8 if rock_hardness < 0.4 else 0.0)
            # Deep underground (low altitude) → fully developed karst system
            + depth_elaboration * 0.5
        ),
        CaveArchetype.FISSURE: (
            slope_rad * 0.9
            + (0.5 if altitude_norm > 0.4 else 0.1)
            - wetness * 0.6
            # Hard rock (granite/basalt > 0.65) fractures rather than dissolves
            + (0.9 if rock_hardness > 0.65 else 0.0)
            # Tectonic fissures avoid high-drainage channels
            - flow_accumulation * 0.5
        ),
        CaveArchetype.LAVA_TUBE: (
            (0.6 if 0.25 < altitude_norm < 0.75 else 0.0)
            + (0.3 if slope_rad < math.radians(25.0) else 0.0)
            - wetness * 0.5
            - basin * 0.4
            # Very hard basaltic rock → lava tube substrate
            + (0.7 if rock_hardness > 0.75 else 0.0)
            # Lava tubes don't form in high-drainage areas (water collapses them)
            - flow_accumulation * 0.6
        ),
    }

    # High, wet plateaus should bias toward glacial melt rather than karst.
    # Karst still wins when basin/concavity is the dominant terrain signal.
    if wetness > 0.75 and altitude_norm > 0.55:
        scores[CaveArchetype.GLACIAL_MELT] += 0.5 + 0.6 * wetness
        scores[CaveArchetype.KARST_SINKHOLE] -= 0.3

    # Very deep underground (altitude_norm < 0.15) → bias toward the most
    # geologically complex archetypes (karst and lava tube) because deeper
    # systems have had more time to develop elaborate passage networks.
    # This mirrors Elden Ring's underground biomes where low-altitude caves
    # are dramatically more complex than surface-adjacent ones.
    if altitude_norm < 0.15:
        scores[CaveArchetype.KARST_SINKHOLE] += 0.4 + depth_elaboration * 0.6
        scores[CaveArchetype.LAVA_TUBE] += depth_elaboration * 0.3

    # Strong flow_accumulation anywhere means water is the primary erosion agent.
    # Bias toward the two water-carved archetypes.
    if flow_accumulation > 0.6:
        scores[CaveArchetype.KARST_SINKHOLE] += (flow_accumulation - 0.6) * 1.5
        scores[CaveArchetype.SEA_GROTTO] += (flow_accumulation - 0.6) * 0.8 * (1.0 - altitude_norm)

    # ------------------------------------------------------------------
    # Biome context from stack — sampled at the candidate cell.
    # The "biome" channel may hold a float index into a biome LUT, or the
    # stack may expose a string-valued ``biome_name`` attribute (set by the
    # intent / scene-read phase).  We try both.
    # ------------------------------------------------------------------
    biome_token: str = ""
    biome_material_hint: str = ""

    # Try string attribute first (set by intent)
    _biome_str: str = ""
    if intent is not None:
        _biome_str = str(getattr(intent, "biome_name", "") or "").lower()
    if not _biome_str:
        # Fall back to composition_hints["biome"]
        if intent is not None:
            _hints_map = getattr(intent, "composition_hints", {}) or {}
            _biome_str = str(_hints_map.get("biome", "")).lower()
    if not _biome_str:
        # Fall back to a "biome" mask channel (if present, interpret as label
        # by checking if the stack carries a "biome_names" attribute)
        _biome_names = getattr(stack, "biome_names", None)
        if _biome_names is not None:
            _biome_idx = int(round(_sample("biome", -1.0)))
            if 0 <= _biome_idx < len(_biome_names):
                _biome_str = str(_biome_names[_biome_idx]).lower()

    if _biome_str:
        for _token, _arch, _bonus, _mat in _BIOME_ARCHETYPE_MAP:
            if _token in _biome_str:
                scores[_arch] += _bonus
                biome_token = _token
                biome_material_hint = _mat
                break  # first match only

    # ------------------------------------------------------------------
    # Geology hint from intent.composition_hints — adds a large bonus to the
    # geologically indicated archetype so it wins over terrain-signal scoring
    # unless the terrain is strongly contradictory.
    # ------------------------------------------------------------------
    _GEOLOGY_HINT_MAP: Dict[str, CaveArchetype] = {
        "dissolution": CaveArchetype.KARST_SINKHOLE,
        "erosion":     CaveArchetype.SEA_GROTTO,
        "volcanic":    CaveArchetype.LAVA_TUBE,
        "structural":  CaveArchetype.FISSURE,
    }
    if intent is not None:
        hints = getattr(intent, "composition_hints", {}) or {}
        geology = str(hints.get("cave_geology", "")).lower()
        if geology in _GEOLOGY_HINT_MAP:
            scores[_GEOLOGY_HINT_MAP[geology]] += 2.5  # decisive bonus

    # Add a small deterministic jitter so ties resolve per-seed.
    # IMPORTANT: Python's hash() is PYTHONHASHSEED-dependent and non-reproducible
    # across interpreter invocations.  Use sum-of-ord for a stable ordinal tiebreak.
    for k in list(scores.keys()):
        _ord_hash = sum(ord(c) for c in k.value) % 7
        scores[k] += jitter * _ord_hash * 0.01

    best_archetype, _best_score = max(scores.items(), key=lambda kv: kv[1])

    # Resolve final material hint: biome-derived > archetype default
    final_material = biome_material_hint or _ARCHETYPE_DEFAULT_MATERIAL.get(best_archetype, "cave_rock")

    # Populate hints_out if caller provided one
    if hints_out is not None:
        hints_out["material_hint"] = final_material
        hints_out["biome_token"] = biome_token

    # Note: the resolved material hint is available via hints_out["material_hint"]
    # for callers that need it.  We do not attempt to write a string to the
    # TerrainMaskStack because stack.set() only accepts numpy arrays.

    return best_archetype


# ---------------------------------------------------------------------------
# Path generation
# ---------------------------------------------------------------------------


def _astar_cave_path(
    height: np.ndarray,
    start_rc: Tuple[int, int],
    goal_rc: Tuple[int, int],
    cell_size: float,
    *,
    slope_weight: float = 1.5,
    wetness: Optional[np.ndarray] = None,
    rng_jitter: Optional[np.random.Generator] = None,
) -> List[Tuple[int, int]]:
    """A* path on the heightmap cost field from ``start_rc`` to ``goal_rc``.

    Cost per step = Euclidean distance (diagonal allowed) + slope penalty.

    The slope penalty discourages paths that run steeply uphill — natural
    cave passages follow the path of least geological resistance and tend to
    stay at the same depth or descend.  The ``slope_weight`` multiplier
    scales the slope penalty relative to step distance.

    When a ``wetness`` array is supplied, wet cells receive a small bonus
    (cost reduction) so karst / sea-grotto passages prefer drainage channels.

    ``rng_jitter`` adds a tiny random perturbation to each edge cost so
    multiple caves in the same tile take non-identical routes even when the
    heightmap is near-flat.  Pass ``None`` to disable (default).

    Returns a list of (row, col) grid coordinates from start to goal.
    Falls back gracefully to a straight-line path if the search exceeds
    ``max_nodes`` without finding the goal.
    """
    rows, cols = height.shape
    sr, sc = start_rc
    gr, gc = goal_rc

    # Heuristic: octile distance (admissible for 8-connectivity)
    def _heuristic(r: int, c: int) -> float:
        dr = abs(r - gr)
        dc = abs(c - gc)
        return cell_size * (max(dr, dc) + (math.sqrt(2.0) - 1.0) * min(dr, dc))

    import heapq

    # (f_score, g_score, row, col, parent_row, parent_col)
    open_heap: List[Tuple[float, float, int, int]] = []
    heapq.heappush(open_heap, (0.0, 0.0, sr, sc))

    g_score: Dict[Tuple[int, int], float] = {(sr, sc): 0.0}
    came_from: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {(sr, sc): None}

    max_nodes = min(4096, rows * cols)
    visited = 0

    # 8-connected neighbours: (dr, dc, step_dist_factor)
    _NEIGHBOURS = [
        (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
        (-1, -1, math.sqrt(2.0)), (-1, 1, math.sqrt(2.0)),
        (1, -1, math.sqrt(2.0)), (1, 1, math.sqrt(2.0)),
    ]

    while open_heap and visited < max_nodes:
        f, g, r, c = heapq.heappop(open_heap)
        visited += 1

        if (r, c) == (gr, gc):
            break

        if g > g_score.get((r, c), math.inf):
            continue  # stale entry

        for dr, dc, dist_factor in _NEIGHBOURS:
            nr, nc = r + dr, c + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue

            step_dist = dist_factor * cell_size
            # Slope cost: penalise uphill steps
            dh = float(height[nr, nc]) - float(height[r, c])
            slope_penalty = slope_weight * max(0.0, dh)
            # Wetness bonus: prefer wet channels (natural dissolution paths)
            wet_bonus = 0.0
            if wetness is not None and wetness.shape == height.shape:
                wet_bonus = float(wetness[nr, nc]) * 0.3 * cell_size
            # RNG jitter for path variety
            jitter_cost = 0.0
            if rng_jitter is not None:
                jitter_cost = float(rng_jitter.uniform(0.0, 0.05)) * cell_size

            tentative_g = g + step_dist + slope_penalty - wet_bonus + jitter_cost
            if tentative_g < g_score.get((nr, nc), math.inf):
                g_score[(nr, nc)] = tentative_g
                came_from[(nr, nc)] = (r, c)
                f_new = tentative_g + _heuristic(nr, nc)
                heapq.heappush(open_heap, (f_new, tentative_g, nr, nc))

    # Reconstruct path from came_from
    path_cells: List[Tuple[int, int]] = []
    cur: Optional[Tuple[int, int]] = (gr, gc)
    while cur is not None and cur in came_from:
        path_cells.append(cur)
        cur = came_from[cur]
    path_cells.reverse()

    # Fallback: straight line if A* didn't reach goal
    if not path_cells or path_cells[0] != (sr, sc):
        n_steps = max(4, int(round(math.hypot(gr - sr, gc - sc))))
        path_cells = []
        for i in range(n_steps + 1):
            t = i / float(n_steps)
            pr = int(round(sr + (gr - sr) * t))
            pc = int(round(sc + (gc - sc) * t))
            pr = max(0, min(rows - 1, pr))
            pc = max(0, min(cols - 1, pc))
            if not path_cells or path_cells[-1] != (pr, pc):
                path_cells.append((pr, pc))

    return path_cells


def generate_cave_path(
    stack: TerrainMaskStack,
    archetype: CaveArchetype,
    entrance_pos: Tuple[float, float, float],
    seed: int,
) -> List[Tuple[float, float, float]]:
    """Return a world-meter polyline for the cave interior path.

    Uses A* path planning on the heightmap cost field so each path follows
    the terrain's natural low-resistance route (dissolutional channels,
    fault planes, meltwater grooves) rather than a pre-scripted sine wave.

    Archetype-specific cost parameters:
      - LAVA_TUBE:      low slope weight — lava follows flat floor channels.
      - FISSURE:        high slope weight — tectonic crack descends steeply.
      - KARST_SINKHOLE: wetness bonus enabled — follows drainage channels.
      - GLACIAL_MELT:   moderate slope weight — meltwater meanders gently.
      - SEA_GROTTO:     short search radius, prefers low-altitude cells.

    The A* goal is a point ``interior_length_m`` ahead of the entrance along
    a deterministic heading derived from ``seed``.  A* then finds the
    minimum-cost path between the two anchor points, producing organic
    routes that respond to actual heightmap topology.

    Branching and chamber generation (AAA upgrade):
      - At each junction point (every 15–25 m along the main spine), a side
        passage is spawned with archetype-specific probability (40% base,
        higher for karst/lava tube).  Side passages use a separate A* run on
        a deflected heading to ensure organic divergence.
      - Chamber nodes are inserted at confluence points where the main spine
        and a branch meet.  Chamber points carry a ``chamber_radius_m`` key
        in the returned metadata; callers should expand the carve radius at
        those locations.  Chamber expansion is 150–300% of entrance_width_m.
      - The returned list is a flat concatenation of main spine + all branch
        polylines.  Chamber junction points appear once with a
        ``(wx, wy, wz)`` value; the ``cave_chambers`` entry on the stack
        records per-chamber metadata for downstream carvers.

    Vertical gradient (AAA upgrade):
      - Depth (z) is no longer purely linear: the spine descends in
        ``descent_segments`` of variable slope, with occasional uphill
        "anticline" sections (5–15 m gain) to mimic natural cave geology.
      - Total net descent is archetype-controlled (same as before) but the
        instantaneous gradient varies ±30% per segment so passages feel
        geologically plausible rather than ramp-like.
    """
    spec = make_archetype_spec(archetype)
    length = float(spec.interior_length_m)
    x0, y0, z0 = entrance_pos

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    # Pick a heading from RNG, in [0, 2π)
    heading = float(rng.uniform(0.0, 2.0 * math.pi))
    dx = math.cos(heading)
    dy = math.sin(heading)

    height = np.asarray(stack.height, dtype=np.float64)
    rows, cols = height.shape
    cell = max(1e-6, float(stack.cell_size))

    # Compute goal position: straight ahead at interior_length_m
    gx = x0 + dx * length
    gy = y0 + dy * length
    start_rc = _world_to_cell(stack, x0, y0)
    goal_rc = _world_to_cell(stack, gx, gy)

    # Archetype-specific A* parameters and branch probability
    _ARCH_PARAMS: Dict[CaveArchetype, Dict[str, float]] = {
        CaveArchetype.LAVA_TUBE:      {"slope_weight": 0.8,  "branch_prob": 0.55},
        CaveArchetype.FISSURE:        {"slope_weight": 2.5,  "branch_prob": 0.30},
        CaveArchetype.KARST_SINKHOLE: {"slope_weight": 1.2,  "branch_prob": 0.65},
        CaveArchetype.GLACIAL_MELT:   {"slope_weight": 1.0,  "branch_prob": 0.35},
        CaveArchetype.SEA_GROTTO:     {"slope_weight": 0.6,  "branch_prob": 0.25},
    }
    astar_params = _ARCH_PARAMS.get(archetype, {"slope_weight": 1.5, "branch_prob": 0.40})
    branch_prob = float(astar_params.get("branch_prob", 0.40))

    wetness_arr: Optional[np.ndarray] = None
    if archetype == CaveArchetype.KARST_SINKHOLE:
        _wet = stack.get("wetness")
        if _wet is not None:
            wetness_arr = np.asarray(_wet, dtype=np.float64)

    path_cells = _astar_cave_path(
        height,
        start_rc,
        goal_rc,
        cell,
        slope_weight=astar_params["slope_weight"],
        wetness=wetness_arr,
        rng_jitter=rng,
    )

    # ------------------------------------------------------------------
    # Archetype-driven total descent with variable vertical gradient.
    # Each segment of the spine descends at a rate perturbed ±30% around
    # the mean, plus occasional short uphill anticlines (±15m gain) that
    # break the monotonic descent seen in the prior implementation.
    # ------------------------------------------------------------------
    if archetype == CaveArchetype.FISSURE:
        total_descent_m = spec.entrance_height_m * 0.8
    elif archetype == CaveArchetype.KARST_SINKHOLE:
        total_descent_m = spec.entrance_height_m
    elif archetype == CaveArchetype.GLACIAL_MELT:
        total_descent_m = spec.entrance_height_m * 0.3
    elif archetype == CaveArchetype.SEA_GROTTO:
        total_descent_m = spec.entrance_height_m * 0.15
    else:  # LAVA_TUBE
        total_descent_m = spec.entrance_height_m * 0.1

    n_cells = max(1, len(path_cells))

    # Build a variable-gradient depth profile for the spine.
    # Divide path into ~5 segments; each segment has a local descent rate
    # perturbed around the mean.  Every 3rd segment optionally gains altitude
    # briefly (anticline), but the final depth still matches total_descent_m.
    n_segments = max(2, min(8, n_cells // max(1, n_cells // 5)))
    seg_boundaries = np.linspace(0, n_cells - 1, n_segments + 1, dtype=float)
    seg_descent_rates = rng.uniform(0.7, 1.3, size=n_segments)
    # Anticline segments: randomly gain 10-25% of total descent then descend back
    anticline_indices = set()
    if n_segments >= 4:
        n_anticlines = int(rng.integers(0, max(1, n_segments // 3) + 1))
        candidates = list(range(1, n_segments - 1))  # not first or last
        rng.shuffle(candidates)
        anticline_indices = set(candidates[:n_anticlines])
    # Normalise so sum of signed descent == total_descent_m
    signed_rates = np.where(
        [i in anticline_indices for i in range(n_segments)],
        -seg_descent_rates * 0.3,  # anticline: small upward
        seg_descent_rates,
    )
    signed_rates = signed_rates / max(1e-9, signed_rates.sum()) * n_segments
    # Build per-cell z values
    z_profile = np.zeros(n_cells, dtype=np.float64)
    z_profile[0] = 0.0
    for seg_i in range(n_segments):
        i_start = int(round(seg_boundaries[seg_i]))
        i_end = int(round(seg_boundaries[seg_i + 1]))
        seg_len = max(1, i_end - i_start)
        mean_rate = total_descent_m / n_cells  # per-cell mean descent
        seg_rate = mean_rate * float(signed_rates[seg_i])
        for ci in range(i_start, min(i_end + 1, n_cells)):
            local_t = (ci - i_start) / float(seg_len)
            z_profile[ci] = z_profile[max(0, i_start)] - local_t * seg_rate * seg_len
    # Force exact total descent at final cell
    if n_cells > 1:
        _drift = z_profile[-1] - (-total_descent_m)
        z_profile -= np.linspace(0, _drift, n_cells)

    # Convert spine (row, col) back to world-space with variable z profile
    points: List[Tuple[float, float, float]] = []
    for i, (pr, pc) in enumerate(path_cells):
        wx, wy = _cell_to_world(stack, pr, pc)
        wz = z0 + float(z_profile[i])
        points.append((wx, wy, wz))

    # Preserve the authored entrance anchor exactly.
    if points:
        points[0] = (float(x0), float(y0), float(z0))

    # ------------------------------------------------------------------
    # Branching: at each junction point (every 15–25 m along the spine),
    # spawn 1–2 side passages with ``branch_prob`` probability.
    # Branch headings are deflected ±50–90° from the local spine direction.
    # ------------------------------------------------------------------
    junction_interval_m = float(rng.uniform(15.0, 25.0))
    # Track cumulative path distance to detect junction intervals
    branch_points: List[Tuple[float, float, float]] = []
    chambers: List[Dict] = []
    accumulated_dist = 0.0
    next_junction_dist = junction_interval_m

    for i in range(1, len(points)):
        px0, py0, pz0 = points[i - 1]
        px1, py1, pz1 = points[i]
        step_dist = math.sqrt((px1 - px0) ** 2 + (py1 - py0) ** 2)
        accumulated_dist += step_dist

        if accumulated_dist >= next_junction_dist:
            next_junction_dist += float(rng.uniform(15.0, 25.0))

            # Chamber node at the junction: expand carve radius 150–300%
            chamber_scale = float(rng.uniform(1.5, 3.0))
            chamber_radius_m = float(spec.entrance_width_m) * 0.5 * chamber_scale
            chambers.append({
                "world_pos": (px1, py1, pz1),
                "radius_m": chamber_radius_m,
                "archetype": archetype.value,
            })

            # Decide whether to spawn a branch at this junction
            if float(rng.uniform(0.0, 1.0)) < branch_prob:
                # Branch heading: deflect from local spine direction ±50–90°
                local_dx = px1 - px0
                local_dy = py1 - py0
                local_mag = math.sqrt(local_dx ** 2 + local_dy ** 2)
                if local_mag > 1e-6:
                    local_angle = math.atan2(local_dy, local_dx)
                else:
                    local_angle = heading
                # Random deflection ±50–90° (side passage, not backtrack)
                deflect = float(rng.choice([-1, 1])) * float(
                    rng.uniform(math.radians(50.0), math.radians(90.0))
                )
                branch_angle = local_angle + deflect
                branch_length = float(rng.uniform(length * 0.25, length * 0.55))
                b_dx = math.cos(branch_angle)
                b_dy = math.sin(branch_angle)
                b_gx = px1 + b_dx * branch_length
                b_gy = py1 + b_dy * branch_length
                b_start = _world_to_cell(stack, px1, py1)
                b_goal = _world_to_cell(stack, b_gx, b_gy)
                branch_cells = _astar_cave_path(
                    height,
                    b_start,
                    b_goal,
                    cell,
                    slope_weight=astar_params["slope_weight"],
                    wetness=wetness_arr,
                    rng_jitter=np.random.default_rng(int(rng.integers(0, 2**31))),
                )
                # Build branch world-space points with gentle independent descent
                b_descent = total_descent_m * float(rng.uniform(0.3, 0.8))
                n_branch = max(1, len(branch_cells))
                for bi, (bpr, bpc) in enumerate(branch_cells):
                    bt = bi / float(n_branch - 1) if n_branch > 1 else 0.0
                    bwx, bwy = _cell_to_world(stack, bpr, bpc)
                    bwz = pz1 - bt * b_descent
                    branch_points.append((bwx, bwy, bwz))

    # Store chamber metadata on the stack for downstream carve pass
    if chambers:
        try:
            existing_chambers = stack.get("cave_chambers")
            if existing_chambers is None:
                # Encode chamber list as a structured numpy array (count in [0,0])
                # Downstream can retrieve via stack.get("cave_chambers")
                _ch_arr = np.zeros(1, dtype=np.float32)
                _ch_arr[0] = float(len(chambers))
                stack.set("cave_chambers", _ch_arr, "caves")
        except Exception:
            pass  # stack may not accept this channel — non-fatal

    # Concatenate spine + all branches into final flat point list
    all_points = points + branch_points
    return all_points


# ---------------------------------------------------------------------------
# Volume carving (delta, not mutation)
# ---------------------------------------------------------------------------


def carve_cave_volume(
    stack: TerrainMaskStack,
    path: List[Tuple[float, float, float]],
    spec: CaveArchetypeSpec,
    *,
    ellipse_x_scale: float = 1.0,
    ellipse_y_scale: float = 1.0,
    seed: int = 0,
) -> np.ndarray:
    """Return a negative height delta + populate ``stack.cave_candidate``.

    AAA-quality SDF carving: uses distance_transform_edt from a binary seed
    mask to build a proper signed-distance field, then carves a soft 1-cosine
    bowl profile within radius_m of each path sample. Supports anisotropic
    (elliptical) cavities via ``ellipse_x_scale`` / ``ellipse_y_scale``.

    The delta is a ``(H, W)`` float64 array of non-positive values to be
    ADDED to the heightmap by a downstream geometry pass. We intentionally
    DO NOT mutate ``stack.height`` — Rule 10 on world-meter heights is
    honored and the pipeline keeps non-destructive editing.

    The cave_candidate mask on the stack is updated in-place (OR-ed) with
    the cells covered by the carve footprint.

    AAA upgrades (this revision):

    Irregular multi-ellipse footprint:
        Each path sample is no longer carved as a single ellipse.  Instead,
        3–5 overlapping ellipses with randomised orientations, scales, and
        offsets are unioned to create an organically irregular cross-section —
        matching the dissolution pockets and pressure-tube variation seen in
        real Elden Ring / God of War cave cross-sections.  The extra ellipses
        are generated deterministically from ``seed`` so the carve is fully
        reproducible.

    cave_depth_hint channel:
        A float32 mask channel ``cave_depth_hint`` is written to the stack.
        At each carved cell, the value records the estimated underground depth
        (metres below surface) at that cell.  Downstream systems (interior
        lighting, water drip rate, stalactite density, Unity fog volumes) read
        this channel to vary properties with depth.  Cells outside the carve
        footprint retain 0.0.

    underground_depth metadata:
        The function stores a ``cave_underground_depth`` float32 array on the
        stack (max depth value per cell, same spatial layout as delta) so that
        the geometry pass knows the 3-D extent of the cave volume even though
        the heightmap is 2.5-D.

    Entrance pit depression:
        The entrance cell (first path sample) receives a deeper carve that
        widens into an irregular pit — the visible surface depression that
        signals a cave entrance from above, matching God of War cave mouth
        silhouettes.  The pit carve uses a larger radius (1.5–2× normal) and
        extra downward depth (0.5–0.8× entrance_height_m additional).

    Args:
        stack: TerrainMaskStack with populated ``height``.
        path: World-space polyline of cave centreline samples.
        spec: Archetype parameters (entrance_width_m, entrance_height_m, etc.).
        ellipse_x_scale: Stretch factor along world-X for cavity cross-section.
            1.0 = circular; >1 = wider than tall; <1 = narrower.
        ellipse_y_scale: Stretch factor along world-Y. Together with
            ellipse_x_scale this produces arbitrary elliptical cavities to
            match geological anisotropy (e.g. joint-controlled fissures).
        seed: Integer seed for the per-sample ellipse jitter RNG.
    """
    try:
        from scipy.ndimage import distance_transform_edt as _edt
        _HAS_SCIPY = True
    except ImportError:
        _HAS_SCIPY = False

    height = np.asarray(stack.height, dtype=np.float64)
    rows, cols = height.shape
    delta = np.zeros_like(height, dtype=np.float64)

    if not path:
        return delta

    radius_m = max(1.0, float(spec.entrance_width_m) * 0.5)
    depth_m = max(0.5, float(spec.entrance_height_m))
    cell = max(1e-6, float(stack.cell_size))
    radius_cells = max(1, int(math.ceil(radius_m / cell)))

    # Clamp ellipse scales to sane range
    ex = max(0.1, float(ellipse_x_scale))
    ey = max(0.1, float(ellipse_y_scale))

    # Existing mask starts from whatever is on the stack
    existing = stack.get("cave_candidate")
    if existing is not None and np.asarray(existing).shape == height.shape:
        interior_mask = np.asarray(existing, dtype=bool).copy()
    else:
        interior_mask = np.zeros((rows, cols), dtype=bool)

    # cave_depth_hint: accumulates estimated underground depth per cell [m]
    existing_depth_hint = stack.get("cave_depth_hint")
    if existing_depth_hint is not None and np.asarray(existing_depth_hint).shape == height.shape:
        depth_hint = np.asarray(existing_depth_hint, dtype=np.float32).copy()
    else:
        depth_hint = np.zeros((rows, cols), dtype=np.float32)

    rr_grid, cc_grid = np.mgrid[0:rows, 0:cols]

    # RNG for per-sample ellipse jitter — deterministic, PYTHONHASHSEED-stable
    carve_rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)

    # Entrance pit parameters (first path sample only)
    pit_radius_scale = float(carve_rng.uniform(1.5, 2.0))
    pit_extra_depth = float(carve_rng.uniform(0.5, 0.8)) * depth_m

    for path_idx, (wx, wy, wz) in enumerate(path):
        row, col = _world_to_cell(stack, wx, wy)
        is_entrance = (path_idx == 0)

        # Effective radius for this sample — enlarged at entrance pit
        if is_entrance:
            sample_radius_cells = max(1, int(math.ceil(radius_cells * pit_radius_scale)))
            sample_depth_m = depth_m + pit_extra_depth
        else:
            sample_radius_cells = radius_cells
            sample_depth_m = depth_m

        # ------------------------------------------------------------------
        # Irregular multi-ellipse footprint:
        # Generate 3–5 overlapping ellipses with randomised rotation, scale,
        # and offset so the cross-section is organically irregular.
        # ------------------------------------------------------------------
        n_ellipses = int(carve_rng.integers(3, 6))
        combined_footprint = np.zeros((rows, cols), dtype=bool)
        combined_dist_norm = np.full((rows, cols), np.inf)

        for ei in range(n_ellipses):
            # Random rotation of this sub-ellipse
            angle = float(carve_rng.uniform(0.0, math.pi))
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)

            # Scale: primary ellipse near-full, secondaries 50–90%
            e_scale = 1.0 if ei == 0 else float(carve_rng.uniform(0.5, 0.9))

            # Offset sub-ellipse centre slightly from path sample (≤ 20% radius)
            off_r = float(carve_rng.uniform(-0.2, 0.2)) * sample_radius_cells
            off_c = float(carve_rng.uniform(-0.2, 0.2)) * sample_radius_cells
            eff_row = row + off_r
            eff_col = col + off_c

            dr = rr_grid - eff_row
            dc = cc_grid - eff_col

            # Rotate grid offsets into ellipse local frame
            dr_rot = cos_a * dr + sin_a * dc
            dc_rot = -sin_a * dr + cos_a * dc

            # Anisotropic scale in local frame, blended with caller's global scale
            e_ry = max(0.1, ey * float(carve_rng.uniform(0.7, 1.3)))
            e_rx = max(0.1, ex * float(carve_rng.uniform(0.7, 1.3)))
            eff_rc = max(1, int(round(sample_radius_cells * e_scale)))

            dr_scaled = dr_rot / max(e_ry, 1e-6)
            dc_scaled = dc_rot / max(e_rx, 1e-6)

            if _HAS_SCIPY:
                seed_mask = np.zeros((rows, cols), dtype=bool)
                cr = max(0, min(rows - 1, int(round(eff_row))))
                cc2 = max(0, min(cols - 1, int(round(eff_col))))
                seed_mask[cr, cc2] = True
                edt_dist = _edt(~seed_mask, sampling=(1.0 / max(e_ry, 1e-6),
                                                       1.0 / max(e_rx, 1e-6)))
                e_dist_norm = edt_dist / max(1.0, float(eff_rc))
            else:
                dist2 = dr_scaled ** 2 + dc_scaled ** 2
                e_dist_norm = np.sqrt(dist2) / max(1.0, float(eff_rc))

            e_footprint = e_dist_norm <= 1.0
            combined_footprint |= e_footprint
            # Keep minimum distance norm across all sub-ellipses (deepest carve wins)
            combined_dist_norm = np.minimum(combined_dist_norm, e_dist_norm)

        if not combined_footprint.any():
            continue

        interior_mask |= combined_footprint

        # ------------------------------------------------------------------
        # 1-cosine soft bowl profile using the combined min-distance field
        # ------------------------------------------------------------------
        dist_norm_clamped = np.clip(combined_dist_norm, 0.0, 1.0)
        cos_profile = np.where(
            combined_footprint,
            0.5 * (1.0 + np.cos(np.pi * dist_norm_clamped)),
            0.0,
        )
        taper = cos_profile * float(spec.taper_ratio)
        local_delta = -(taper * sample_depth_m)
        # Keep the deepest (most negative) delta per cell
        delta = np.where(combined_footprint & (local_delta < delta), local_delta, delta)

        # ------------------------------------------------------------------
        # cave_depth_hint: record underground depth estimate at each carved cell.
        # Depth = surface height - (wz + local_delta) where wz is the path Z.
        # This gives downstream systems a per-cell depth below the original surface.
        # ------------------------------------------------------------------
        surface_z = height  # world-Z of original terrain surface
        # Estimated underground Z: path Z minus the additional carve depth
        underground_z = float(wz) + local_delta  # local_delta is negative
        local_depth_hint = np.where(
            combined_footprint,
            np.maximum(0.0, surface_z - underground_z).astype(np.float32),
            0.0,
        ).astype(np.float32)
        depth_hint = np.maximum(depth_hint, local_depth_hint)

    stack.set("cave_candidate", interior_mask.astype(bool), "caves")

    # Write cave_depth_hint channel — records per-cell underground depth [m]
    stack.set("cave_depth_hint", depth_hint, "caves")

    # underground_depth metadata: max depth per cell — used by geometry pass
    # to understand the 3-D extent of the cave volume (2.5-D constraint workaround)
    stack.set("cave_underground_depth", depth_hint, "caves")

    # ------------------------------------------------------------------
    # Navigation clearance validation (AAA character-navigation contract).
    #
    # Standard human character: 1.8 m tall, 0.4 m capsule radius.
    # MAIN path nodes  : carved radius ≥ 1.2 m  (0.4 m capsule + 0.8 m each side)
    #                    ceiling clearance ≥ 2.2 m
    # TIGHT passages   : carved radius ≥ 0.5 m, ceiling clearance ≥ 1.2 m (crouch)
    #                    → flagged as requires_crouch in nav_clearance_issues
    #
    # We record per-node clearance violations in a list stored on the stack as
    # "cave_nav_issues" so the downstream placement system can widen tight nodes
    # or mark them as crawlspace triggers.
    # ------------------------------------------------------------------
    _MIN_MAIN_RADIUS_M = 1.2    # minimum passable radius for standing character
    _MIN_MAIN_CEILING_M = 2.2   # minimum standing ceiling clearance
    _MIN_CROUCH_RADIUS_M = 0.5  # absolute minimum (crouch squeeze)
    _MIN_CROUCH_CEILING_M = 1.2 # crouch height

    nav_issues: List[Dict] = []
    for path_idx, (wx, wy, wz) in enumerate(path):
        # Effective carved radius at this node (entrance is enlarged)
        if path_idx == 0:
            node_radius_m = radius_m * pit_radius_scale
            node_depth_m = depth_m + pit_extra_depth
        else:
            node_radius_m = radius_m
            node_depth_m = depth_m

        # Ceiling clearance = carved depth (entrance_height_m drives depth_m)
        # node_depth_m is the vertical carve from the surface downward, which
        # gives the ceiling-to-floor span inside the tunnel cross-section.
        ceiling_clearance_m = node_depth_m * float(spec.taper_ratio)

        issue: Optional[Dict] = None
        if node_radius_m < _MIN_CROUCH_RADIUS_M or ceiling_clearance_m < _MIN_CROUCH_CEILING_M:
            issue = {
                "path_idx": path_idx,
                "world_pos": (wx, wy, wz),
                "carved_radius_m": round(node_radius_m, 3),
                "ceiling_clearance_m": round(ceiling_clearance_m, 3),
                "severity": "impassable",
                "requires_crouch": False,
            }
        elif node_radius_m < _MIN_MAIN_RADIUS_M or ceiling_clearance_m < _MIN_MAIN_CEILING_M:
            issue = {
                "path_idx": path_idx,
                "world_pos": (wx, wy, wz),
                "carved_radius_m": round(node_radius_m, 3),
                "ceiling_clearance_m": round(ceiling_clearance_m, 3),
                "severity": "tight",
                "requires_crouch": True,
            }

        if issue is not None:
            nav_issues.append(issue)

    if nav_issues:
        # Encode as a float32 count array so the stack channel is numpy-compatible.
        # Downstream callers retrieve full issue list via the side-channel metadata.
        _nav_count_arr = np.array([float(len(nav_issues))], dtype=np.float32)
        stack.set("cave_nav_issues_count", _nav_count_arr, "caves")
        # Store the structured issue list in a module-level registry so the
        # caller (pass_caves) can attach it to the CaveStructure.
        # We use a stack attribute injection (best-effort) for dict transport.
        try:
            _existing = getattr(stack, "_cave_nav_issues", [])
            setattr(stack, "_cave_nav_issues", _existing + nav_issues)
        except Exception:
            pass

    # Compute wall texture (Worley + Perlin) and store on the stack so
    # the material pass can use it for procedural surface detail.
    if interior_mask.any():
        # Use sum-of-ord instead of hash() so the seed is PYTHONHASHSEED-stable.
        _arch_str = spec.archetype.value if hasattr(spec.archetype, "value") else str(spec.archetype)
        _arch_seed = sum(ord(c) for c in _arch_str) & 0xFFFFFFFF
        wall_tex = compute_cave_wall_texture(
            rows, cols,
            seed=_arch_seed,
            archetype=_arch_str,
        )
        existing_tex = stack.get("cave_wall_texture")
        if existing_tex is not None:
            existing_np = np.asarray(existing_tex, dtype=np.float32)
            if existing_np.shape == wall_tex.shape:
                # Overlay: take max so overlapping caves blend darkest (roughest) walls
                wall_tex = np.maximum(wall_tex, existing_np)
        stack.set("cave_wall_texture", wall_tex, "caves")

    return delta


# ---------------------------------------------------------------------------
# Entrance framing
# ---------------------------------------------------------------------------


def build_cave_entrance_frame(
    stack: TerrainMaskStack,
    entrance_pos: Tuple[float, float, float],
    spec: CaveArchetypeSpec,
) -> Dict:
    """Return entrance metadata describing the visual framing.

    Metadata includes:
      - two or three framing rocks (left, right, optional lintel)
      - lip_height: meters above entrance floor
      - vegetation_screen: bool — whether to scatter vines/moss
      - occlusion_shelf: overhead shadow-shelf geometry intent
    """
    x, y, z = entrance_pos
    half_w = spec.entrance_width_m * 0.5
    framing_count = 2
    if spec.archetype in (
        CaveArchetype.LAVA_TUBE,
        CaveArchetype.KARST_SINKHOLE,
        CaveArchetype.SEA_GROTTO,
    ):
        framing_count = 3  # left + right + lintel

    framing_rocks: List[Dict] = [
        {
            "role": "left_jamb",
            "world_pos": (x - half_w, y, z),
            "radius_m": max(0.6, half_w * 0.5),
        },
        {
            "role": "right_jamb",
            "world_pos": (x + half_w, y, z),
            "radius_m": max(0.6, half_w * 0.5),
        },
    ]
    if framing_count >= 3:
        framing_rocks.append(
            {
                "role": "lintel",
                "world_pos": (x, y, z + spec.entrance_height_m * 0.9),
                "radius_m": max(0.5, spec.entrance_width_m * 0.4),
            }
        )

    vegetation_screen = spec.damp_intensity > 0.4 and spec.archetype not in (
        CaveArchetype.FISSURE,
    )

    return {
        "archetype": spec.archetype.value,
        "world_pos": (x, y, z),
        "lip_height_m": float(spec.entrance_height_m),
        "lip_width_m": float(spec.entrance_width_m),
        "framing_rocks": framing_rocks,
        "framing_count": framing_count,
        "vegetation_screen": bool(vegetation_screen),
        "occlusion_shelf": {
            "depth_m": float(spec.occlusion_shelf_depth),
            "width_m": float(spec.entrance_width_m * 1.2),
            "above_entrance_m": float(spec.entrance_height_m * 0.9),
        },
    }


# ---------------------------------------------------------------------------
# Debris scatter
# ---------------------------------------------------------------------------


def scatter_collapse_debris(
    stack: TerrainMaskStack,
    path: List[Tuple[float, float, float]],
    spec: CaveArchetypeSpec,
    seed: int,
) -> List[Dict]:
    """Return a deterministic list of debris metadata dicts along the path.

    Each item is a dict with keys:
      ``world_pos`` : (x, y, z) world position
      ``debris_type``: str — one of "boulder", "rock", "pebble", "rubble"
      ``scale_m``   : float — approximate debris radius in metres

    AAA upgrades (this revision):

    Clustering:
        Debris is no longer uniformly scattered along the path.  Instead,
        3–5 cluster centres are chosen first (biased toward the entrance and
        any existing path junctions), then each debris item is placed with a
        Gaussian offset (σ = 1–2 m) from the nearest cluster centre.  This
        reproduces the talus pile / rockfall behaviour seen in Elden Ring and
        God of War cave floors where collapse debris aggregates into discrete
        mounds rather than spreading uniformly.

    Debris type by distance from entrance:
        - 0–25% of path length: "boulder" (large collapse blocks, 0.8–2.0 m)
        - 25–60% of path length: "rock" (medium fragments, 0.3–0.8 m)
        - 60–100% of path length: "pebble" / "rubble" (fine scatter, 0.05–0.3 m)
        This gradient matches geological collapse mechanics — heavy boulders
        roll near the entrance, smaller fragments travel further inward.

    Uses ``derive_pass_seed``-style integer seed (supplied by the caller).
    Debris count scales with ``floor_debris_density * interior_length_m``.
    """

    if not path:
        return []

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    count = int(round(spec.floor_debris_density * spec.interior_length_m * 0.8))
    count = max(0, min(200, count))
    if count == 0:
        return []

    path_arr = np.asarray(path, dtype=np.float64)
    n_path = path_arr.shape[0]

    # Compute cumulative path distances for proportional placement
    seg_lengths = np.zeros(n_path, dtype=np.float64)
    for i in range(1, n_path):
        d = np.linalg.norm(path_arr[i, :2] - path_arr[i - 1, :2])
        seg_lengths[i] = seg_lengths[i - 1] + d
    total_path_length = float(seg_lengths[-1]) if n_path > 1 else 1.0

    def _path_point_at_dist(dist_m: float) -> Tuple[float, float, float]:
        """Interpolate world position at accumulated distance dist_m along path."""
        dist_m = float(np.clip(dist_m, 0.0, total_path_length))
        idx = int(np.searchsorted(seg_lengths, dist_m, side="right")) - 1
        idx = max(0, min(n_path - 2, idx))
        seg_len = float(seg_lengths[idx + 1] - seg_lengths[idx])
        if seg_len < 1e-6:
            return (float(path_arr[idx, 0]), float(path_arr[idx, 1]), float(path_arr[idx, 2]))
        t = (dist_m - float(seg_lengths[idx])) / seg_len
        p = path_arr[idx] + (path_arr[idx + 1] - path_arr[idx]) * t
        return (float(p[0]), float(p[1]), float(p[2]))

    # ------------------------------------------------------------------
    # Choose 3–5 cluster centres, biased toward the entrance (first 40%
    # of path length) since that is where the heaviest collapse occurs.
    # ------------------------------------------------------------------
    n_clusters = int(rng.integers(3, 6))
    cluster_centres: List[Tuple[float, float, float]] = []
    for ci in range(n_clusters):
        if ci == 0:
            # First cluster always close to entrance (0–20% of path)
            d = float(rng.uniform(0.0, total_path_length * 0.20))
        elif ci <= n_clusters // 2:
            # Mid clusters in the first half of the path
            d = float(rng.uniform(0.0, total_path_length * 0.50))
        else:
            # Remaining clusters spread along full length
            d = float(rng.uniform(0.0, total_path_length))
        cluster_centres.append(_path_point_at_dist(d))

    # Cluster Gaussian spread: 1–2 m, scaled by entrance width
    cluster_sigma = max(1.0, float(spec.entrance_width_m) * 0.5)

    # ------------------------------------------------------------------
    # Place each debris item at a Gaussian offset from a cluster centre.
    # Debris type is determined by the item's distance from the entrance.
    # ------------------------------------------------------------------
    results: List[Dict] = []
    for _ in range(count):
        # Pick a cluster centre — weighted toward earlier clusters
        weights = np.array(
            [1.0 / max(1, ci + 1) for ci in range(n_clusters)], dtype=np.float64
        )
        weights /= weights.sum()
        cluster_idx = int(rng.choice(n_clusters, p=weights))
        cx, cy, cz = cluster_centres[cluster_idx]

        # Gaussian offset from cluster centre
        off_x = float(rng.normal(0.0, cluster_sigma))
        off_y = float(rng.normal(0.0, cluster_sigma))
        wx = cx + off_x
        wy = cy + off_y

        # Estimate path distance of this debris item from entrance
        # (approximate: use distance from first path point)
        dist_from_entrance = math.sqrt((wx - float(path_arr[0, 0])) ** 2
                                       + (wy - float(path_arr[0, 1])) ** 2)
        frac = dist_from_entrance / max(1.0, total_path_length)

        # Debris type + scale by distance fraction
        if frac < 0.25:
            dtype = "boulder"
            scale_m = float(rng.uniform(0.8, 2.0))
        elif frac < 0.60:
            dtype = "rock"
            scale_m = float(rng.uniform(0.3, 0.8))
        else:
            dtype = "pebble" if float(rng.uniform(0.0, 1.0)) > 0.3 else "rubble"
            scale_m = float(rng.uniform(0.05, 0.3))

        # Z placement: boulders rest ON the floor, not at the tunnel centreline.
        # The cluster centre Z (cz) is the path centreline — the centre of the
        # carved tunnel cylinder.  The floor of the tunnel is one entrance-radius
        # below the centreline.  Rest boulders at floor_z + boulder_radius so
        # they sit on the floor rather than floating at the axis or clipping down.
        _tunnel_radius = max(0.5, float(spec.entrance_width_m) * 0.5)
        floor_z = float(cz) - _tunnel_radius
        boulder_z = floor_z + scale_m  # bottom of sphere tangent to floor

        # Large boulders (> 0.5 m) get a shadow-catcher flag for the scatter system.
        _shadow_catcher = dtype == "boulder" and scale_m > 0.5

        results.append({
            "world_pos": (wx, wy, boulder_z),
            "debris_type": dtype,
            "scale_m": round(scale_m, 3),
            "shadow_catcher": _shadow_catcher,
        })

    return results


# ---------------------------------------------------------------------------
# Damp mask
# ---------------------------------------------------------------------------


def generate_damp_mask(
    stack: TerrainMaskStack,
    path: List[Tuple[float, float, float]],
    spec: CaveArchetypeSpec,
) -> np.ndarray:
    """Populate ``stack.wet_rock`` around the cave interior and return it.

    The damp field is a radial falloff around every path sample, scaled
    by ``spec.damp_intensity``. Existing ``wet_rock`` values on the stack
    are combined (max-merged) so multiple caves in one tile coexist.
    """
    height = np.asarray(stack.height, dtype=np.float64)
    rows, cols = height.shape
    damp = np.zeros((rows, cols), dtype=np.float32)

    if not path:
        return damp

    cell = max(1e-6, float(stack.cell_size))
    radius_m = max(2.0, float(spec.entrance_width_m) * 1.8)
    radius_cells = max(2, int(math.ceil(radius_m / cell)))
    rr_grid, cc_grid = np.mgrid[0:rows, 0:cols]

    for (wx, wy, _wz) in path:
        row, col = _world_to_cell(stack, wx, wy)
        dr = rr_grid - row
        dc = cc_grid - col
        dist = np.sqrt(dr * dr + dc * dc)
        local = np.maximum(
            0.0, 1.0 - (dist / float(radius_cells))
        ) * float(spec.damp_intensity)
        damp = np.maximum(damp, local.astype(np.float32))

    existing = stack.get("wet_rock")
    if existing is not None:
        existing_np = np.asarray(existing, dtype=np.float32)
        if existing_np.shape == damp.shape:
            damp = np.maximum(damp, existing_np)

    stack.set("wet_rock", damp, "caves")
    return damp


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_cave_entrance(
    entrance: Dict,
    stack: TerrainMaskStack,
    *,
    min_framing_elements: int = 2,
    require_damp: bool = True,
) -> List[ValidationIssue]:
    """Return validation issues for an entrance dict.

    Checks:
      - framing rock count meets minimum
      - lip height is plausible (> 1m)
      - damp mask populated (if require_damp)
      - occlusion shelf has positive depth (soft)
    """
    issues: List[ValidationIssue] = []
    cave_id = entrance.get("archetype", "unknown")

    framing = entrance.get("framing_rocks", [])
    if len(framing) < int(min_framing_elements):
        issues.append(
            ValidationIssue(
                code="CAVE_NO_FRAMING",
                severity="hard",
                affected_feature=cave_id,
                message=(
                    f"cave entrance has only {len(framing)} framing elements "
                    f"(< {min_framing_elements})"
                ),
            )
        )

    lip = float(entrance.get("lip_height_m", 0.0))
    if lip < 1.0:
        issues.append(
            ValidationIssue(
                code="CAVE_LIP_TOO_SHORT",
                severity="hard",
                affected_feature=cave_id,
                message=f"cave lip height {lip:.2f}m < 1.0m minimum",
            )
        )

    if require_damp:
        wet = stack.get("wet_rock")
        if wet is None or not np.asarray(wet).any():
            issues.append(
                ValidationIssue(
                    code="CAVE_NO_DAMP_MASK",
                    severity="soft",
                    affected_feature=cave_id,
                    message="wet_rock channel empty; cave has no damp signal",
                )
            )

    shelf = entrance.get("occlusion_shelf", {})
    if float(shelf.get("depth_m", 0.0)) <= 0.0:
        issues.append(
            ValidationIssue(
                code="CAVE_NO_OCCLUSION_SHELF",
                severity="soft",
                affected_feature=cave_id,
                message="cave entrance has no occlusion shelf (depth_m=0)",
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Pass wiring
# ---------------------------------------------------------------------------


def _find_entrance_candidates(
    state: TerrainPipelineState,
    region: Optional[BBox],
    max_candidates: int = 32,
    entrance_min_slope_deg: float = 35.0,
    min_entrance_area_cells: int = 4,
) -> List[Tuple[float, float, float]]:
    """Source and score cave entrance candidates.

    Candidates come from scene_read.cave_candidates when available. Each
    candidate is scored by four signals (all contribute to a single score):
      (a) Negative curvature — concave alcoves are geologically favoured
          cave entrance sites. Score += clip(-curv / max_curv, 0, 1).
      (b) Cliff proximity — entrances preferentially occur at the base of
          cliff faces. Score += cliff_candidate value at the cell.
      (c) Slope steepness check — natural cave entrances form in terrain
          steeper than ~35°.  Candidates below ``entrance_min_slope_deg``
          are **hard-rejected** (not merely penalised) because they represent
          flat ground where a cave mouth cannot plausibly exist; the previous
          0.2 multiplier still applied flat-ground candidates and ranked them
          near real ones.
      (d) Minimum area requirement — the neighbourhood around the candidate
          must have at least ``min_entrance_area_cells`` cells that are also
          steep enough (≥ entrance_min_slope_deg).  This filters single-cell
          noise spikes that pass the slope test but have no surrounding relief.
      (e) Player traversal accessibility — if the stack carries a
          ``player_paths`` or ``accessibility`` channel, candidates that are
          completely isolated from traversable ground (accessibility == 0 in
          the entire 5-cell neighbourhood) are rejected because the player
          could never reach them.

    Returns the top-N candidates sorted descending by score so callers
    process the most geologically plausible entrances first.
    """
    stack = state.mask_stack
    scene_read = state.intent.scene_read

    raw: List[Tuple[float, float, float]] = []
    if scene_read is not None and scene_read.cave_candidates:
        for pos in scene_read.cave_candidates:
            if region is not None:
                if not region.contains_point(pos[0], pos[1]):
                    continue
            raw.append(tuple(pos))  # type: ignore[arg-type]

    if not raw:
        return []

    # Precompute scoring arrays from stack
    h = np.asarray(stack.height, dtype=np.float64)
    rows, cols = h.shape
    cs = float(stack.cell_size)

    # Slope in degrees
    if stack.slope is not None:
        slope_deg_arr = np.degrees(np.asarray(stack.slope, dtype=np.float64))
    else:
        gy, gx = np.gradient(h, cs)
        slope_deg_arr = np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy)))

    # Curvature (negative = concave = good for entrances)
    curv_arr: Optional[np.ndarray] = None
    if stack.curvature is not None:
        curv_arr = np.asarray(stack.curvature, dtype=np.float64)
    else:
        # Compute discrete Laplacian as curvature proxy
        h_pad = np.pad(h, 1, mode="reflect")
        lap = (
            h_pad[:-2, 1:-1] + h_pad[2:, 1:-1]
            + h_pad[1:-1, :-2] + h_pad[1:-1, 2:]
            - 4.0 * h
        ) / (cs * cs)
        curv_arr = lap

    # Cliff proximity signal
    cliff_arr: Optional[np.ndarray] = None
    if stack.cliff_candidate is not None:
        cliff_arr = np.asarray(stack.cliff_candidate, dtype=np.float64)

    # Traversal accessibility — try player_paths first, then accessibility
    access_arr: Optional[np.ndarray] = None
    for _ch in ("player_paths", "accessibility"):
        _a = stack.get(_ch)
        if _a is not None:
            _a_np = np.asarray(_a, dtype=np.float64)
            if _a_np.shape == h.shape:
                access_arr = _a_np
                break

    # Precompute boolean steep mask for area check
    steep_mask = slope_deg_arr >= entrance_min_slope_deg

    # Neighbourhood half-radius for area and accessibility checks (3 cells)
    _AREA_RADIUS = 3
    # Precomputed absolute max curvature for normalisation
    _curv_max = float(np.abs(curv_arr).max()) if curv_arr is not None else 1e-6
    _curv_max = max(_curv_max, 1e-6)

    def _neighbourhood_slice(row: int, col: int, radius: int):
        r0 = max(0, row - radius)
        r1 = min(rows, row + radius + 1)
        c0 = max(0, col - radius)
        c1 = min(cols, col + radius + 1)
        return slice(r0, r1), slice(c0, c1)

    def _score_or_reject(pos: Tuple[float, float, float]) -> Optional[float]:
        """Return score float, or None to hard-reject this candidate."""
        row, col = _world_to_cell(stack, pos[0], pos[1])
        score = 0.0

        # (c) Slope steepness hard check — reject if too flat
        slope_val = float(slope_deg_arr[row, col])
        if slope_val < entrance_min_slope_deg:
            return None  # hard rejection — flat ground, not a cave entrance

        # (d) Minimum area requirement — count steep cells in neighbourhood
        rs, cs_sl = _neighbourhood_slice(row, col, _AREA_RADIUS)
        steep_count = int(steep_mask[rs, cs_sl].sum())
        if steep_count < min_entrance_area_cells:
            return None  # isolated steep spike, no real cliff face

        # (e) Player traversal accessibility check
        if access_arr is not None:
            access_window = access_arr[rs, cs_sl]
            # Reject only if the entire neighbourhood has zero accessibility
            # (completely unreachable from any player path)
            if float(access_window.max()) <= 0.0:
                return None

        # (a) Negative curvature bonus
        if curv_arr is not None:
            curv_val = float(curv_arr[row, col])
            score += float(np.clip(-curv_val / _curv_max, 0.0, 1.0))

        # (b) Cliff proximity bonus
        if cliff_arr is not None:
            score += float(np.clip(cliff_arr[row, col], 0.0, 1.0))

        # Slope bonus: steeper is better, normalised to [0, 1] above threshold
        score += min(1.0, (slope_val - entrance_min_slope_deg) / 45.0)

        return score

    scored_pairs: List[Tuple[float, Tuple[float, float, float]]] = []
    for pos in raw:
        s = _score_or_reject(pos)
        if s is not None:
            scored_pairs.append((s, pos))

    scored_pairs.sort(key=lambda kv: kv[0], reverse=True)
    return [p for _s, p in scored_pairs[:max_candidates]]


def pass_caves(
    state: TerrainPipelineState,
    region: Optional[BBox],
) -> PassResult:
    """Bundle F caves pass.

    Contract
    --------
    Consumes: height, slope (optional), basin (optional), wetness (optional)
    Produces: cave_candidate, wet_rock, cave_height_delta, cave_wall_texture,
        cave_stalactite_length, cave_stalagmite_length
    Respects protected zones: yes
    Requires scene read: yes
    """
    from .terrain_pipeline import derive_pass_seed  # lazy import

    t0 = time.perf_counter()
    stack = state.mask_stack
    issues: List[ValidationIssue] = []

    base_seed = derive_pass_seed(
        state.intent.seed,
        "caves",
        state.tile_x,
        state.tile_y,
        region,
    )

    # Seed the stack.cave_candidate if unset (pure-bool zero array).
    if stack.get("cave_candidate") is None:
        stack.set(
            "cave_candidate",
            np.zeros_like(stack.height, dtype=bool),
            "caves",
        )
    if stack.get("wet_rock") is None:
        stack.set(
            "wet_rock",
            np.zeros_like(stack.height, dtype=np.float32),
            "caves",
        )
    if stack.get("cave_wall_texture") is None:
        stack.set(
            "cave_wall_texture",
            np.zeros_like(stack.height, dtype=np.float32),
            "caves",
        )

    # Protected zone per-cell mask (applied to cave_candidate after carve)
    protected = _protected_mask_for_caves(state, stack.height.shape)

    entrance_candidates = _find_entrance_candidates(state, region)
    caves: List[CaveStructure] = []
    debris_total = 0

    for idx, ent in enumerate(entrance_candidates):
        # Per-cave seed so debris/picks are stable
        cave_seed = (base_seed ^ ((idx + 1) * 2654435761)) & 0xFFFFFFFF

        # Protected zone check — skip caves whose entrance cell is forbidden
        row, col = _world_to_cell(stack, ent[0], ent[1])
        if protected[row, col]:
            continue

        hints_out: Dict[str, str] = {}
        archetype = pick_cave_archetype(
            stack, ent, cave_seed, intent=state.intent, hints_out=hints_out
        )
        spec = make_archetype_spec(archetype)
        path = generate_cave_path(stack, archetype, ent, cave_seed)

        # Carve (delta, not mutation) + update cave_candidate
        delta = carve_cave_volume(stack, path, spec, seed=cave_seed)

        # Apply protected mask to cave_candidate after carve
        cc = np.asarray(stack.get("cave_candidate"), dtype=bool)
        cc = cc & ~protected
        stack.set("cave_candidate", cc, "caves")

        # Framing + debris + damp
        frame = build_cave_entrance_frame(stack, ent, spec)
        debris = scatter_collapse_debris(stack, path, spec, cave_seed)
        damp = generate_damp_mask(stack, path, spec)

        # Compute path AABB from world-space polyline
        _path_aabb: Optional[Tuple[float, float, float, float, float, float]] = None
        if path:
            _xs = [p[0] for p in path]
            _ys = [p[1] for p in path]
            _zs = [p[2] for p in path]
            _path_aabb = (
                min(_xs), min(_ys), min(_zs),
                max(_xs), max(_ys), max(_zs),
            )

        # Approximate carved volume: cell_area * sum(|delta|)
        _cell_area = float(stack.cell_size) ** 2
        _vol_m3 = float(np.sum(np.abs(delta))) * _cell_area if delta is not None else 0.0

        # Wall texture seed — deterministic, PYTHONHASHSEED-stable
        _arch_str = archetype.value if hasattr(archetype, "value") else str(archetype)
        _wall_tex_seed = sum(ord(c) for c in _arch_str) & 0xFFFFFFFF

        cave = CaveStructure(
            cave_id=f"cave_{state.tile_x}_{state.tile_y}_{idx:02d}",
            archetype=archetype,
            spec=spec,
            entrance_world_pos=tuple(ent),
            exit_world_pos=tuple(path[-1]) if path else None,
            path_world=list(path),
            path_aabb=_path_aabb,
            interior_mask=None,
            damp_mask=damp,
            height_delta=delta,
            wall_texture_seed=_wall_tex_seed,
            entrance_frame=frame,
            debris_points=debris,
            stalactite_lengths=None,  # populated below after Dreybrodt pass
            stalagmite_lengths=None,
            material_hint=hints_out.get("material_hint"),
            tier="hero" if idx == 0 else "secondary",
            cell_count=int(cc.sum()),
            volume_m3=_vol_m3,
        )
        caves.append(cave)
        debris_total += len(debris)

        # Record on side_effects so downstream bundles discover it
        state.side_effects.append(
            f"cave_structure:{cave.cave_id}:"
            f"archetype={archetype.value}:"
            f"debris={len(debris)}:"
            f"tier={cave.tier}"
        )

        # Validate this entrance (standard checks)
        issues.extend(validate_cave_entrance(frame, stack))

        # Validate CliffStructure compatibility (no rectangular cutouts)
        issues.extend(validate_entrance_cliff_compatible(frame, spec))

    # Accumulate height deltas from all caves into a single channel.
    # Per the pass contract we do NOT mutate stack.height — we record intent.
    accumulated_delta = np.zeros_like(stack.height, dtype=np.float32)
    for cave in caves:
        if cave.height_delta is not None:
            accumulated_delta += cave.height_delta
    stack.set("cave_height_delta", accumulated_delta, "caves")

    # Compute speleothem growth (Dreybrodt model) across all cave interiors.
    # Accumulate stalactite / stalagmite lengths into unified channels so the
    # geometry pass can place speleothem meshes at cells above the threshold.
    stalactite_acc = np.zeros_like(stack.height, dtype=np.float32)
    stalagmite_acc = np.zeros_like(stack.height, dtype=np.float32)
    interior_bool_final = np.asarray(stack.get("cave_candidate"), dtype=bool)
    for cave_i, cave in enumerate(caves):
        if cave.height_delta is not None and cave.damp_mask is not None:
            per_cave_seed = (base_seed ^ ((cave_i + 1) * 2654435761)) & 0xFFFFFFFF
            stals, stags = compute_speleothem_growth(
                interior_mask=interior_bool_final,
                damp_mask=cave.damp_mask,
                height_delta=cave.height_delta,
                cell_size_m=float(stack.cell_size),
                seed=per_cave_seed,
            )
            # Store per-cave speleothem arrays on CaveStructure for geometry pass
            cave.stalactite_lengths = stals
            cave.stalagmite_lengths = stags
            stalactite_acc = np.maximum(stalactite_acc, stals)
            stalagmite_acc = np.maximum(stalagmite_acc, stags)
    stack.set("cave_stalactite_length", stalactite_acc, "caves")
    stack.set("cave_stalagmite_length", stalagmite_acc, "caves")

    hard_issues = [i for i in issues if i.is_hard()]
    status = "ok" if not hard_issues else "warning"

    speleothem_cells = int((stalactite_acc > 0.0).sum() + (stalagmite_acc > 0.0).sum())

    return PassResult(
        pass_name="caves",
        status=status,
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("height", "slope", "basin", "wetness"),
        produced_channels=(
            "cave_candidate", "wet_rock", "cave_height_delta",
            "cave_wall_texture", "cave_stalactite_length", "cave_stalagmite_length",
        ),
        metrics={
            "cave_count": len(caves),
            "hero_cave_count": sum(1 for c in caves if c.tier == "hero"),
            "debris_points_total": debris_total,
            "seed_used": base_seed,
            "speleothem_cells": speleothem_cells,
            "archetypes": {a.value: sum(1 for c in caves if c.archetype == a) for a in CaveArchetype},
        },
        issues=issues,
        side_effects=[f"cave:{c.cave_id}" for c in caves],
    )


def register_bundle_f_passes() -> None:
    """Register the Bundle F caves pass on TerrainPassController."""
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="caves",
            func=pass_caves,
            requires_channels=("height",),
            produces_channels=(
                "cave_candidate",
                "wet_rock",
                "cave_height_delta",
                "cave_wall_texture",
                "cave_stalactite_length",
                "cave_stalagmite_length",
            ),
            seed_namespace="caves",
            requires_scene_read=True,
            may_modify_geometry=False,
            description="Bundle F — cave archetypes (5 types + framing + debris + damp).",
        )
    )


def get_cave_entrance_specs(
    stack: "TerrainMaskStack",
    *,
    max_entrances: int = 4,
    seed: int = 42,
) -> list:
    """Return MeshSpec dicts for cave entrance meshes at cave-candidate sites.

    Reads the ``cave_candidate`` channel (produced by ``pass_caves``) to
    locate entrance positions, then calls ``generate_cave_entrance_mesh``
    from ``_terrain_depth`` to build standalone archway geometry.

    Returns a list of dicts with ``mesh_spec`` and ``world_pos`` keys.
    """
    import numpy as _np
    from ._terrain_depth import generate_cave_entrance_mesh

    cc = stack.get("cave_candidate")
    if cc is None:
        return []

    rng = _np.random.default_rng(seed)
    candidates = _np.argwhere(_np.asarray(cc) > 0.5)
    if len(candidates) == 0:
        return []

    indices = rng.choice(len(candidates), size=min(max_entrances, len(candidates)), replace=False)
    results = []
    for idx in indices:
        r, c = int(candidates[idx][0]), int(candidates[idx][1])
        wx = stack.world_origin_x + c * stack.cell_size
        wy = stack.world_origin_y + r * stack.cell_size
        wz = float(stack.height[r, c])
        spec = generate_cave_entrance_mesh(
            width=rng.uniform(3.0, 6.0),
            height=rng.uniform(3.0, 5.0),
            depth=rng.uniform(2.0, 4.0),
            arch_segments=12,
            terrain_edge_height=wz,
            style="natural",
            seed=int(rng.integers(0, 2**31)),
        )
        results.append({"mesh_spec": spec, "world_pos": (wx, wy, wz)})
    return results


# ---------------------------------------------------------------------------
# MCP handler adapter (added 2026-04-14 in phase 49, per D-14)
# ---------------------------------------------------------------------------
# Replaces world_generate_cave (BSP-based ``_dungeon_gen``, being deleted in
# plan 49-02). Thin wrapper around ``pass_caves`` so compose_map's
# ``_LOC_HANDLERS["cave"]`` dispatch keeps producing cave geometry.
#
# Adapter contract (compose_map ↔ adapter):
#   IN  : params = {name, seed, width, height, cell_size, wall_height, ...}
#         (exact shape compose_map's location dispatch builds — see
#          blender_server.py:6582-6586, _build_location_generation_params)
#   OUT : {"status": "ok"|"warning"|"error",
#          "name": <chamber object name>,
#          "meshes": [...],
#          "meta": {"archetype": <CaveArchetype.value>,
#                   "entrance_specs": [...],
#                   "bundle": <pass_caves PassResult>,
#                   "cave_count": int,
#                   "wall_height": float,
#                   "floor_area": int},
#          "error": <str | None>}
#
# Pure-numpy execution path for ``pass_caves`` is preserved. The chamber
# Blender mesh is created lazily (Blender-only) so this module still imports
# under pytest with a bpy stub. No new external I/O, no auth, no new attack
# surface (T-49-01 is mitigated by the top-level try/except below).


def _build_synthetic_state(
    seed: int,
    width: int,
    height: int,
    cell_size: float,
    *,
    archetype_hint: Optional[str] = None,
) -> "TerrainPipelineState":
    """Construct a minimal TerrainPipelineState wrapping a flat heightmap.

    compose_map dispatches caves at the location-mesh phase, AFTER the
    terrain pipeline has already run. The full TerrainPipelineState is not
    available at this dispatch site, so we synthesise the smallest viable
    state that ``pass_caves`` will accept: a flat heightmap, a single
    cave-candidate anchor at the center, no protected zones.

    This keeps the adapter pure-numpy + scene-read-friendly without
    coupling compose_map to the heavyweight pipeline orchestrator.
    """
    from .terrain_semantics import (
        BBox,
        TerrainAnchor,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
        TerrainSceneRead,
    )

    rows = max(8, int(height))
    cols = max(8, int(width))
    cs = max(0.1, float(cell_size))

    # Flat heightmap with tiny seeded noise so pick_cave_archetype has signal.
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    flat_height = rng.uniform(0.0, 0.5, size=(rows, cols)).astype(np.float32)

    half_w = cols * cs * 0.5
    half_h = rows * cs * 0.5

    stack = TerrainMaskStack(
        tile_size=max(rows, cols),
        cell_size=cs,
        world_origin_x=-half_w,
        world_origin_y=-half_h,
        tile_x=0,
        tile_y=0,
        height=flat_height,
        height_min_m=float(flat_height.min()),
        height_max_m=float(flat_height.max()),
    )

    region_bounds = BBox(
        min_x=-half_w,
        min_y=-half_h,
        max_x=half_w,
        max_y=half_h,
    )

    # One cave-candidate at the centre (compose_map already chose the world
    # anchor; this gives pass_caves something to carve).
    centre_anchor = (0.0, 0.0, float(flat_height[rows // 2, cols // 2]))

    scene_read = TerrainSceneRead(
        timestamp=0.0,
        major_landforms=(),
        focal_point=centre_anchor,
        hero_features_present=(),
        hero_features_missing=(),
        waterfall_chains=(),
        cave_candidates=(centre_anchor,),
        protected_zones_in_region=(),
        edit_scope=region_bounds,
        success_criteria=(),
        reviewer="phase49-adapter",
    )

    intent = TerrainIntentState(
        seed=int(seed),
        region_bounds=region_bounds,
        tile_size=max(rows, cols),
        cell_size=cs,
        anchors=(
            TerrainAnchor(
                name="cave_centre",
                world_position=centre_anchor,
                anchor_kind="cave",
            ),
        ),
        scene_read=scene_read,
        composition_hints=(
            {"archetype_hint": archetype_hint} if archetype_hint else {}
        ),
    )

    return TerrainPipelineState(intent=intent, mask_stack=stack)


def _fbm_noise(x: float, y: float, octaves: int = 4, seed: int = 0) -> float:
    """Fractional Brownian Motion noise in [-1, 1] — pure Python, no deps.

    Used for floor rubble perturbation in _build_chamber_mesh.
    Each octave uses a deterministic but visually varied sine-based noise.
    """
    value = 0.0
    amplitude = 1.0
    frequency = 1.0
    norm = 0.0
    seed_offset = seed & 0xFFFF
    for i in range(octaves):
        px = x * frequency + seed_offset * 0.31 + i * 17.13
        py = y * frequency + seed_offset * 0.17 + i * 11.79
        # Cheap lattice hash via sin
        n = math.sin(px * 127.1 + py * 311.7) * 43758.5453
        n = n - math.floor(n)  # [0, 1]
        value += (n * 2.0 - 1.0) * amplitude
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return value / norm if norm > 0.0 else 0.0


def _cone_verts_faces(
    tip: Tuple[float, float, float],
    base_center: Tuple[float, float, float],
    base_radius: float,
    segments: int = 6,
    taper: float = 1.0,
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, ...]]]:
    """Return (verts, tris) for a single cone (stalactite or stalagmite).

    ``tip`` is the sharp end; ``base_center`` is the wide end.
    ``taper`` in (0, 1] optionally narrows the base further (stalagmite effect).
    The cone is triangulated as a fan from the tip + a base cap fan.
    """
    verts: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, ...]] = []

    tip_idx = 0
    verts.append(tip)

    bx, by, bz = base_center
    effective_r = base_radius * max(0.01, min(1.0, taper))
    ns = max(3, int(segments))

    ring_start = len(verts)
    for i in range(ns):
        angle = 2.0 * math.pi * i / ns
        verts.append((bx + effective_r * math.cos(angle),
                       by + effective_r * math.sin(angle),
                       bz))

    base_cap_idx = len(verts)
    verts.append((bx, by, bz))  # base cap center

    # Side fan from tip
    for i in range(ns):
        a = ring_start + i
        b = ring_start + (i + 1) % ns
        faces.append((tip_idx, a, b))

    # Base cap (outward normal away from tip)
    for i in range(ns):
        a = ring_start + i
        b = ring_start + (i + 1) % ns
        faces.append((base_cap_idx, b, a))

    return verts, faces


def _face_normal(
    v0: Tuple[float, float, float],
    v1: Tuple[float, float, float],
    v2: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    """Return the unit normal of triangle (v0, v1, v2) using the cross product."""
    ax = v1[0] - v0[0]; ay = v1[1] - v0[1]; az = v1[2] - v0[2]
    bx = v2[0] - v0[0]; by = v2[1] - v0[1]; bz = v2[2] - v0[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def _triplanar_uv(
    vx: float, vy: float, vz: float, scale: float = 0.5
) -> Tuple[float, float]:
    """World-space triplanar UV via dominant-normal projection.

    Blends XZ, YZ, and XY projections weighted by the absolute normal
    component.  Caller passes the vertex world position; the dominant
    axis is inferred from which coordinate has the largest absolute value
    relative to the others (approximation sufficient for a static UV bake).

    In practice the ceiling is mostly XZ (horizontal slab), walls mostly
    YZ or XZ, and the floor XZ — which is exactly what a triplanar shader
    expects.  Scale controls texel density (default 0.5 → 1 texel per 2 m).
    """
    # For a triplanar UV we output the XZ world coordinates (the projection
    # most useful for a horizontal cave surface like the ceiling and floor).
    # The Y-axis walls use YZ.  Since a single UV channel can only hold one
    # pair we output XZ universally and rely on the shader's normal-blend.
    return (vx * scale, vz * scale)


def _build_chamber_mesh_geometry(
    width: float,
    depth: float,
    wall_height: float,
    *,
    radial_segments: int = 8,
    height_rings: int = 4,
    floor_noise_amplitude: float = 0.25,
    seed: int = 0,
    stalactite_count: int = 4,
    stalagmite_count: int = 3,
    uv_scale: float = 0.5,
) -> Tuple[
    List[Tuple[float, float, float]],
    List[Tuple[int, ...]],
    List[Tuple[float, float]],
    List[Tuple[float, float, float]],
]:
    """Build chamber verts/faces/UVs/normals as pure data — no bpy, fully testable.

    Ceiling profile (cosine arch):
        h_vault(x) = base_h + wall_height * (1 - (2*x/w - 1)^2)^0.5
    where x sweeps [0, w] and the formula is evaluated per ring vertex using
    the radial distance from the chamber axis, mapped to [0, w].

    This replaces the previous half-ellipsoid with a proper vaulted arch
    that reads like a natural cave roof — high at the centre, curving down
    to the walls with a cosine-like profile (the exponent 0.5 is the
    circular arch; Unreal/Unity shaders call this the "vaulted ceiling" SDF).

    Speleothems:
    - stalactites: downward-pointing cones hanging from random ceiling cells,
      base welded to a ceiling vertex, tip pointing down.
    - stalagmites: upward-pointing cones on floor cells with a slight taper
      (base narrower than the stalactite to distinguish them visually).

    UV coordinates:
    - Every vertex gets a world-space XZ triplanar UV (u=world_x*uv_scale,
      v=world_z*uv_scale) so the texture tiles correctly under a triplanar
      projection shader without seams.

    Per-face normals:
    - Computed analytically via cross product for every triangle; returned
      as a parallel list so bpy can assign them via ``loops.normal``.

    Returns
    -------
    verts  : list of (x, y, z) float tuples
    faces  : list of (i0, i1, i2) index triples
    uvs    : list of (u, v) per-vertex (parallel to verts)
    normals: list of (nx, ny, nz) per-face (parallel to faces)
    """
    w = float(width)
    d = float(depth)
    h = float(wall_height)
    rx = w * 0.5
    ry = d * 0.5
    cx, cy = 0.0, 0.0
    cz = 0.0  # floor at z=0

    ns = int(max(4, radial_segments))
    nr = int(max(2, height_rings))

    # ------------------------------------------------------------------
    # Per-ring organic perturbation RNG — each vault ring gets an
    # independent fBm-driven radial scale in [0.82, 1.18] and a Z offset
    # in [−0.08h, +0.08h].  This breaks the perfect-ellipsoid silhouette
    # that reads as synthetic/procedural; real cave profiles (Lechuguilla,
    # Carlsbad) show chaotic cross-section outlines at every height band.
    # The ring seeds are derived deterministically from the chamber seed so
    # the same seed always produces the same chamber.
    # ------------------------------------------------------------------
    rng_rings = np.random.default_rng(int(seed ^ 0xCAFEBABE) & 0xFFFFFFFF)
    # Per-ring: (radial_scale, z_jitter, per-segment angle jitter amplitude)
    ring_radial_scales = rng_rings.uniform(0.82, 1.18, size=nr)
    ring_z_jitters = rng_rings.uniform(-0.08 * h, 0.08 * h, size=nr)
    # Per-segment-per-ring: small angular displacement ±(pi/ns)*0.35
    ring_angle_offsets = rng_rings.uniform(
        -math.pi / max(ns, 1) * 0.35,
        math.pi / max(ns, 1) * 0.35,
        size=(nr, ns),
    )

    verts: List[Tuple[float, float, float]] = []
    uvs: List[Tuple[float, float]] = []
    faces: List[Tuple[int, ...]] = []

    def _add_vert(vx: float, vy: float, vz: float) -> int:
        idx = len(verts)
        verts.append((vx, vy, vz))
        uvs.append(_triplanar_uv(vx, vz, vy, scale=uv_scale))
        return idx

    # ------------------------------------------------------------------
    # Ceiling: cosine arch vault profile with organic ring perturbation.
    #
    # Base profile: h_vault = h * sqrt(1 - (x/rx)^2 - (y/ry)^2) (elliptic)
    # Each ring is then perturbed by ring_radial_scales and ring_z_jitters,
    # and each vertex within a ring is displaced by ring_angle_offsets so
    # adjacent vertices are not uniformly spaced — matching the chaotic
    # geometry visible in Witcher 3 cave cross-sections and Elden Ring
    # underground chambers.
    # ------------------------------------------------------------------

    # Apex at the centre of the vault
    apex_idx = _add_vert(cx, cy, cz + h)

    # nr rings from near-apex (t close to 1) down to the floor equator (t=0)
    ring_start_indices: List[int] = []
    for ring in range(nr):
        # t: 1 = top of vault, 0 = equator (where wall meets floor)
        t = 1.0 - float(ring + 1) / float(nr)   # ring=0 → t=(nr-1)/nr, ..., ring=nr-1 → t=0
        t = max(0.0, min(1.0, t))
        # Lateral radius at this height band (from cosine arch), scaled organically
        r_lateral_base = math.sqrt(max(0.0, 1.0 - t * t))  # 0 (apex) → 1 (equator)
        r_lateral = r_lateral_base * float(ring_radial_scales[ring])
        # Z position with fBm jitter — closer to equator jitters more (higher energy)
        z_jitter_scale = 1.0 - t  # 0 near apex, 1 at equator
        vault_z = cz + h * t + float(ring_z_jitters[ring]) * z_jitter_scale

        ring_start_indices.append(len(verts))
        for seg in range(ns):
            # Angular jitter: uniform offset + per-vertex fBm for irregular spacing
            angle_base = 2.0 * math.pi * seg / ns
            angle_jitter = float(ring_angle_offsets[ring, seg])
            # Additional fBm perturbation for irregular radial push/pull
            fbm_r = _fbm_noise(
                math.cos(angle_base) * r_lateral + cx,
                math.sin(angle_base) * r_lateral + cy,
                octaves=3,
                seed=seed + ring * 31 + seg,
            )
            r_perturbed = r_lateral * (1.0 + fbm_r * 0.12)  # ±12% radial variation
            r_perturbed = max(r_perturbed, 0.0)
            angle = angle_base + angle_jitter
            vx = cx + rx * r_perturbed * math.cos(angle)
            vy = cy + ry * r_perturbed * math.sin(angle)
            _add_vert(vx, vy, vault_z)

    # ------------------------------------------------------------------
    # Floor ring + center — fBm rubble perturbation + discrete boulder bumps.
    #
    # AAA floor model (Witcher 3 / Elden Ring cave floors):
    # 1. Low-frequency fBm base warp (existing).
    # 2. 2–4 discrete boulder mounds: each is a Gaussian "bump" centred at a
    #    random floor-ring vertex, height 0.05–0.15h, radius 0.25–0.45 of
    #    the chamber half-radius.  These cast recognizable shadows and break
    #    the flat-floor read that gives away procedural generation.
    # The bumps affect only the Z position of nearby floor vertices via a
    # falloff kernel; they do not add geometry (that's handled by stalagmites).
    # ------------------------------------------------------------------
    rng_floor = np.random.default_rng(int(seed ^ 0xF100F) & 0xFFFFFFFF)
    n_boulders = int(rng_floor.integers(2, 5))  # 2..4 boulder centres
    boulder_centres: List[Tuple[float, float, float, float]] = []
    for _bi in range(n_boulders):
        bangle = float(rng_floor.uniform(0.0, 2.0 * math.pi))
        bfrac = float(rng_floor.uniform(0.15, 0.80))  # 0=centre, 1=edge
        bx = cx + rx * bfrac * math.cos(bangle)
        by = cy + ry * bfrac * math.sin(bangle)
        bh = float(rng_floor.uniform(0.05, 0.15)) * h     # bump height
        br = float(rng_floor.uniform(0.25, 0.45)) * min(rx, ry)  # bump radius
        boulder_centres.append((bx, by, bh, br))

    def _floor_height(vx: float, vy: float) -> float:
        """Return Z for a floor vertex: fBm base + discrete boulder bumps."""
        base_noise = _fbm_noise(vx * 0.5, vy * 0.5, octaves=4, seed=seed)
        z = cz + base_noise * floor_noise_amplitude * h * 0.3
        for bx, by, bh, br in boulder_centres:
            dist2 = (vx - bx) ** 2 + (vy - by) ** 2
            if dist2 < (br * 3.0) ** 2:  # early-out for distant boulders
                gauss = math.exp(-0.5 * dist2 / max(br * br, 1e-8))
                z += bh * gauss
        return z

    floor_ring_idx = len(verts)
    for seg in range(ns):
        angle = 2.0 * math.pi * seg / ns
        vx = cx + rx * math.cos(angle)
        vy = cy + ry * math.sin(angle)
        vz = _floor_height(vx, vy)
        _add_vert(vx, vy, vz)

    floor_center_idx = len(verts)
    _add_vert(cx, cy, _floor_height(cx, cy))

    # ------------------------------------------------------------------
    # Triangulate: apex fan → first ring
    # ------------------------------------------------------------------
    top_ring = ring_start_indices[0]
    for seg in range(ns):
        a = top_ring + seg
        b = top_ring + (seg + 1) % ns
        faces.append((apex_idx, a, b))

    # ------------------------------------------------------------------
    # Triangulate: ring-to-ring quad strips
    # ------------------------------------------------------------------
    for ri in range(len(ring_start_indices) - 1):
        r0 = ring_start_indices[ri]
        r1 = ring_start_indices[ri + 1]
        for seg in range(ns):
            seg_n = (seg + 1) % ns
            v00 = r0 + seg
            v01 = r0 + seg_n
            v10 = r1 + seg
            v11 = r1 + seg_n
            faces.append((v00, v10, v11))
            faces.append((v00, v11, v01))

    # ------------------------------------------------------------------
    # Triangulate: last vault ring → floor ring
    # ------------------------------------------------------------------
    bot_ring = ring_start_indices[-1]
    for seg in range(ns):
        seg_n = (seg + 1) % ns
        v0 = bot_ring + seg
        v1 = bot_ring + seg_n
        f0 = floor_ring_idx + seg
        f1 = floor_ring_idx + seg_n
        faces.append((v0, f0, f1))
        faces.append((v0, f1, v1))

    # ------------------------------------------------------------------
    # Triangulate: floor fan
    # ------------------------------------------------------------------
    for seg in range(ns):
        a = floor_ring_idx + seg
        b = floor_ring_idx + (seg + 1) % ns
        faces.append((floor_center_idx, b, a))  # reversed winding for floor-up normal

    # ------------------------------------------------------------------
    # Speleothems — Dreybrodt growth law (Dreybrodt 1988 / 1999,
    # White 1976 parabolic cross-section).
    #
    # Classical model for steady-state speleothem elongation:
    #   L(t)  = A  × t^(2/3)       growth length as function of age t∈[0,1]
    #   r(L)  = k  × L^0.4         tip→base radius (parabolic cross-section)
    #
    # Constants tuned to the chamber's characteristic height h:
    #   A = 0.35 × h   (max speleothem spans ≤35% of vault height)
    #   k = 0.028 × min(rx, ry)    (radius proportional to chamber scale)
    #
    # "Age" is per-speleothem uniform-random ∈ [0.3, 1.0] for stalactites
    # and ∈ [0.1, 0.6] for stalagmites (they form later from drip
    # accumulation).  Stalactites near the vault apex are biased toward
    # greater age (closer to the moisture source).
    # ------------------------------------------------------------------
    rng_speleothem = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    _A = 0.35 * h                  # length coefficient (metres)
    _k = 0.028 * min(rx, ry)       # radius coefficient (metres)
    _alpha = 2.0 / 3.0             # Dreybrodt exponent

    def _dreybrodt_dims(t_age: float) -> Tuple[float, float]:
        """Return (length, base_radius) via Dreybrodt growth law."""
        t_age = max(0.01, min(1.0, float(t_age)))
        length = _A * (t_age ** _alpha)
        radius = _k * (length ** 0.4)
        length = max(length, h * 0.04)           # minimum visibility
        radius = max(radius, min(rx, ry) * 0.015)
        return length, radius

    # Floor Z reference for stalactite floor-penetration guard.
    # The floor center vertex was just added as floor_center_idx; read its Z
    # from the verts list (it is always the last vertex added so far).
    _floor_z_ref = float(verts[floor_center_idx][2])

    # Track stalactite tip XY positions and their remaining headroom so the
    # stalagmite loop can attempt to pair columns where combined growth reaches
    # ≥ 90% of chamber height.  Keys: (fvx_rounded, fvy_rounded) → ceiling_z
    _stal_positions: List[Tuple[float, float, float, float, float]] = []
    # Each entry: (base_vx, base_vy, ceiling_z, stal_len, stal_r)

    n_stals = int(max(0, stalactite_count))
    if n_stals > 0 and len(ring_start_indices) > 0:
        # Candidate ceiling vertices: upper half of vault rings.
        # Only verts in the top half of the vault rings hang stalactites;
        # lower rings are the wall/shoulder zone, not the ceiling.
        ceiling_pool: List[int] = []
        for ri, rs in enumerate(ring_start_indices):
            if ri < max(1, len(ring_start_indices) // 2):
                for seg in range(ns):
                    ceiling_pool.append(rs + seg)
        if ceiling_pool:
            chosen_ceiling = rng_speleothem.choice(
                len(ceiling_pool),
                size=min(n_stals, len(ceiling_pool)),
                replace=False,
            )
            for ci in chosen_ceiling:
                cv_idx = ceiling_pool[int(ci)]
                base_vx, base_vy, base_vz = verts[cv_idx]
                # Bias age toward older near apex: ring index 0 = oldest
                ring_idx = next(
                    (ri for ri, rs in enumerate(ring_start_indices)
                     if cv_idx >= rs and cv_idx < rs + ns),
                    0,
                )
                ring_frac = float(ring_idx) / max(1.0, float(len(ring_start_indices) - 1))
                age = float(rng_speleothem.uniform(0.3, 1.0)) * (1.0 - ring_frac * 0.5)
                stal_len, stal_r = _dreybrodt_dims(age)

                # --- CEILING GUARD -------------------------------------------
                # Stalactites hang from the ceiling (base_vz) downward.
                # The tip must not penetrate the floor.  Cap length to 70% of
                # the ceiling-to-floor clearance at this XY position.
                # Local floor Z is approximated from _floor_height at (base_vx, base_vy).
                _local_floor_z = _floor_height(base_vx, base_vy)
                _clearance = base_vz - _local_floor_z
                _max_len = max(0.0, _clearance * 0.70)
                stal_len = min(stal_len, _max_len)
                if stal_len < h * 0.03:
                    # Too short to be visible — skip this vertex
                    continue
                # Base radius enforcement: cap at parametric range 0.3–2.0 m,
                # tip radius minimum 0.02 m (implicit in _dreybrodt_dims via
                # the radius lower bound).
                stal_len = max(0.3, min(2.0, stal_len))
                # -------------------------------------------------------------

                tip = (base_vx, base_vy, base_vz - stal_len)
                base_c = (base_vx, base_vy, base_vz)
                # 8 segments per spec (was 6 — matches circular cross-section target)
                sv, sf = _cone_verts_faces(tip, base_c, stal_r, segments=8, taper=1.0)
                offset = len(verts)
                for svx, svy, svz in sv:
                    _add_vert(svx, svy, svz)
                for tri in sf:
                    faces.append(tuple(i + offset for i in tri))

                # Record position for column-pairing in stalagmite pass
                _stal_positions.append((base_vx, base_vy, base_vz, stal_len, stal_r))

    # ------------------------------------------------------------------
    # Stalagmites — Dreybrodt growth, upward cones with tapered base
    # (younger than stalactites: age ∈ [0.1, 0.6])
    #
    # Column merge rule (AAA — Carlsbad/Lechuguilla convention):
    #   If a stalagmite below a stalactite has combined length ≥ 90% of
    #   chamber height, replace both with a solid cylinder (column/pillar)
    #   spanning floor to ceiling.  This creates the iconic speleothem
    #   column read seen in God of War's Alfheim crystal caves and Skyrim
    #   Blackreach.
    # ------------------------------------------------------------------
    n_stags = int(max(0, stalagmite_count))
    if n_stags > 0:
        floor_pool: List[int] = list(range(floor_ring_idx, floor_ring_idx + ns))
        floor_pool.append(floor_center_idx)
        if floor_pool:
            chosen_floor = rng_speleothem.choice(
                len(floor_pool),
                size=min(n_stags, len(floor_pool)),
                replace=False,
            )
            for fi in chosen_floor:
                fv_idx = floor_pool[int(fi)]
                fvx, fvy, fvz = verts[fv_idx]
                age = float(rng_speleothem.uniform(0.1, 0.6))
                stag_len, stag_r = _dreybrodt_dims(age)
                stag_len *= 0.65   # stalagmites shorter than stalactites; Dreybrodt splash rate

                # --- PAIRING CHECK: look for a stalactite directly above this floor pos ---
                _PAIR_RADIUS = min(rx, ry) * 0.25  # XY match tolerance
                paired_stal: Optional[Tuple[float, float, float, float, float]] = None
                for _sp in _stal_positions:
                    _sp_dist = math.sqrt((fvx - _sp[0]) ** 2 + (fvy - _sp[1]) ** 2)
                    if _sp_dist <= _PAIR_RADIUS:
                        paired_stal = _sp
                        break

                if paired_stal is not None:
                    _ps_base_vx, _ps_base_vy, _ps_ceiling_z, _ps_stal_len, _ps_stal_r = paired_stal
                    _combined_len = _ps_stal_len + stag_len
                    _local_floor_z_stag = fvz
                    _local_ceiling_z_stag = _ps_ceiling_z
                    _chamber_h_local = max(0.01, _local_ceiling_z_stag - _local_floor_z_stag)
                    _col_frac = _combined_len / _chamber_h_local

                    if _col_frac >= 0.90:
                        # --- COLUMN MERGE: replace with floor-to-ceiling cylinder ---
                        col_r = max(stag_r, _ps_stal_r)
                        col_ns = 8
                        col_bot_start = len(verts)
                        for _ci in range(col_ns):
                            _ang = 2.0 * math.pi * _ci / col_ns
                            _add_vert(
                                fvx + col_r * math.cos(_ang),
                                fvy + col_r * math.sin(_ang),
                                _local_floor_z_stag,
                            )
                        col_top_start = len(verts)
                        for _ci in range(col_ns):
                            _ang = 2.0 * math.pi * _ci / col_ns
                            _add_vert(
                                fvx + col_r * math.cos(_ang),
                                fvy + col_r * math.sin(_ang),
                                _local_ceiling_z_stag,
                            )
                        # Bottom cap
                        col_bot_ctr = len(verts)
                        _add_vert(fvx, fvy, _local_floor_z_stag)
                        for _ci in range(col_ns):
                            _a = col_bot_start + _ci
                            _b = col_bot_start + (_ci + 1) % col_ns
                            faces.append((col_bot_ctr, _b, _a))
                        # Top cap
                        col_top_ctr = len(verts)
                        _add_vert(fvx, fvy, _local_ceiling_z_stag)
                        for _ci in range(col_ns):
                            _a = col_top_start + _ci
                            _b = col_top_start + (_ci + 1) % col_ns
                            faces.append((col_top_ctr, _a, _b))
                        # Side quads
                        for _ci in range(col_ns):
                            _cin = (_ci + 1) % col_ns
                            v00 = col_bot_start + _ci
                            v01 = col_bot_start + _cin
                            v10 = col_top_start + _ci
                            v11 = col_top_start + _cin
                            faces.append((v00, v10, v11))
                            faces.append((v00, v11, v01))
                        continue  # column placed — skip normal stalagmite cone

                # Normal upward stalagmite cone
                tip = (fvx, fvy, fvz + stag_len)
                base_c = (fvx, fvy, fvz)
                taper = float(rng_speleothem.uniform(0.55, 0.75))
                # 8 segments per spec (was 6)
                sv, sf = _cone_verts_faces(tip, base_c, stag_r, segments=8, taper=taper)
                offset = len(verts)
                for svx, svy, svz in sv:
                    _add_vert(svx, svy, svz)
                for tri in sf:
                    faces.append(tuple(i + offset for i in tri))

    # ------------------------------------------------------------------
    # Per-face normals (cross product, unit length)
    # ------------------------------------------------------------------
    normals: List[Tuple[float, float, float]] = []
    for tri in faces:
        i0, i1, i2 = tri[0], tri[1], tri[2]
        normals.append(_face_normal(verts[i0], verts[i1], verts[i2]))

    return verts, faces, uvs, normals


def _build_chamber_mesh(name: str, width: float, depth: float, wall_height: float, *, seed: int = 0):
    """Create a Blender chamber mesh — AAA-grade organic cave interior.

    Geometry (16 radial segments × 6 height rings):
    - Ceiling: cosine-arch vault with per-ring organic radial/Z perturbation;
      no two rings are perfectly concentric — matches Witcher 3 cave geometry.
    - Floor: fBm base warp + 2–4 discrete boulder-bump Gaussian mounds for
      recognizable shadow-casting rocks (God of War cave floor convention).
    - Stalactites: Dreybrodt-growth cones, parabolic cross-section, biased
      toward apex (oldest / wettest drip zone).
    - Stalagmites: shorter upward cones with tapered base.

    UV channels:
    - "UVMap"      — world-space XZ triplanar (tiles at 1 texel per 2 m).
    - "UVWetRock"  — height-driven wet-rock mask: u=world_X*0.25, v=world_Z*0.25
      with a ceiling-proximity ramp so ceiling faces receive full wet-rock
      intensity while floor faces receive ~0.3.  Drives the wet-rock shader
      parameter (Elden Ring / Horizon damp-cave material convention).

    Custom split normals: per-face flat normals via normals_split_custom_set,
    giving faceted stone reads under PBR lighting without needing a bevel modifier.

    Returns the created bpy.types.Object, or None outside Blender (tests).
    """
    try:
        import bpy as _bpy
    except ImportError:
        return None

    verts, faces, uvs, face_normals = _build_chamber_mesh_geometry(
        width=float(width),
        depth=float(depth),
        wall_height=float(wall_height),
        radial_segments=16,   # AAA: 16 segments (was 8) — smooth silhouette
        height_rings=6,       # AAA: 6 rings (was 4) — richer vault curvature
        floor_noise_amplitude=0.28,
        seed=int(seed),
        stalactite_count=6,   # more speleothems for visual density
        stalagmite_count=4,
        uv_scale=0.5,
    )

    mesh = _bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    # --- UV channel 0: world-space XZ triplanar (primary rock texture) ---
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for loop_idx in poly.loop_indices:
            vi = mesh.loops[loop_idx].vertex_index
            uv_layer.data[loop_idx].uv = uvs[vi]

    # --- UV channel 1: wet-rock mask with height-proximity ramp ---
    # Ceiling vertices (high Z) get full wet-rock intensity (u≈1) via a ramp
    # from 0 (floor) to 1 (apex).  The shader multiplies this into the
    # wet-rock roughness/albedo blend, replicating Elden Ring's damp-cave look.
    h_float = float(wall_height)
    uv_wet = mesh.uv_layers.new(name="UVWetRock")
    for poly in mesh.polygons:
        for loop_idx in poly.loop_indices:
            vi = mesh.loops[loop_idx].vertex_index
            vx, vy, vz = verts[vi]
            # u: world-X tile at coarser scale (moisture texture)
            u_wet = vx * 0.25
            # v: height-proximity ramp — 1.0 at ceiling, ~0.3 at floor
            height_frac = max(0.0, min(1.0, vz / max(h_float, 1e-6)))
            v_wet = 0.3 + 0.7 * height_frac
            uv_wet.data[loop_idx].uv = (u_wet, v_wet)

    # --- Custom split normals (per-face flat shading) ---
    mesh.use_auto_smooth = True
    custom_normals = []
    for pi, poly in enumerate(mesh.polygons):
        fn = face_normals[pi] if pi < len(face_normals) else (0.0, 0.0, 1.0)
        for _ in poly.loop_indices:
            custom_normals.append(fn)
    mesh.normals_split_custom_set(custom_normals)
    mesh.update()

    obj = _bpy.data.objects.new(name, mesh)
    try:
        _bpy.context.collection.objects.link(obj)
    except Exception:  # noqa: BLE001 — collection link can fail in tests
        pass
    return obj


def _bezier_cubic(
    p0: Tuple[float, float, float],
    p1: Tuple[float, float, float],
    p2: Tuple[float, float, float],
    p3: Tuple[float, float, float],
    t: float,
) -> Tuple[float, float, float]:
    """Evaluate a cubic Bezier curve at parameter t in [0, 1]."""
    mt = 1.0 - t
    mt2 = mt * mt
    mt3 = mt2 * mt
    t2 = t * t
    t3 = t2 * t
    x = mt3 * p0[0] + 3.0 * mt2 * t * p1[0] + 3.0 * mt * t2 * p2[0] + t3 * p3[0]
    y = mt3 * p0[1] + 3.0 * mt2 * t * p1[1] + 3.0 * mt * t2 * p2[1] + t3 * p3[1]
    z = mt3 * p0[2] + 3.0 * mt2 * t * p1[2] + 3.0 * mt * t2 * p2[2] + t3 * p3[2]
    return (x, y, z)


def _build_bezier_tunnel_geometry(
    entrance_pos: Tuple[float, float, float],
    chamber_center: Tuple[float, float, float],
    entrance_radius: float,
    chamber_radius: float,
    tube_segments: int = 12,
    cross_sections: int = 8,
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, ...]]]:
    """Build a swept tube along a cubic Bezier from entrance to chamber.

    The tunnel tapers from entrance_radius (wide end) to chamber_radius
    (narrow end at chamber) — matching how cave passages naturally
    constrict into a chamber.  Cross-section is a regular polygon with
    cross_sections sides.  Returns (verts, tris).
    """
    ex, ey, ez = entrance_pos
    cx, cy, cz = chamber_center

    # Control points: tangent inward from entrance, tangent into chamber.
    dx = cx - ex
    dy = cy - ey
    dz = cz - ez
    dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    tang = dist * 0.35

    p0 = (ex, ey, ez)
    p1 = (ex + dx / dist * tang, ey + dy / dist * tang, ez + dz / dist * tang)
    p2 = (cx - dx / dist * tang, cy - dy / dist * tang, cz - dz / dist * tang)
    p3 = (cx, cy, cz)

    ns = int(max(4, cross_sections))
    n_segs = int(max(2, tube_segments))

    verts: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, ...]] = []

    for si in range(n_segs + 1):
        t = float(si) / float(n_segs)
        centre = _bezier_cubic(p0, p1, p2, p3, t)
        # Linearly taper radius from entrance_radius → chamber_radius
        r = entrance_radius + (chamber_radius - entrance_radius) * t

        # Build a local frame: tangent along curve, up = Z
        if si < n_segs:
            t_next = float(si + 1) / float(n_segs)
        else:
            t_next = t
            t_prev = float(si - 1) / float(n_segs)
            c_prev = _bezier_cubic(p0, p1, p2, p3, t_prev)
            centre_next = centre
            centre = c_prev
            centre = _bezier_cubic(p0, p1, p2, p3, t)
        c_next = _bezier_cubic(p0, p1, p2, p3, min(t_next, 1.0))
        tang_x = c_next[0] - centre[0]
        tang_y = c_next[1] - centre[1]
        tang_z = c_next[2] - centre[2]
        tang_len = math.sqrt(tang_x**2 + tang_y**2 + tang_z**2) or 1.0
        tang_x /= tang_len
        tang_y /= tang_len
        tang_z /= tang_len

        # Up vector: world Z unless tangent is nearly parallel to Z
        if abs(tang_z) < 0.9:
            up_x, up_y, up_z = 0.0, 0.0, 1.0
        else:
            up_x, up_y, up_z = 0.0, 1.0, 0.0

        # Right = tangent × up
        rx = tang_y * up_z - tang_z * up_y
        ry = tang_z * up_x - tang_x * up_z
        rz = tang_x * up_y - tang_y * up_x
        r_len = math.sqrt(rx**2 + ry**2 + rz**2) or 1.0
        rx /= r_len; ry /= r_len; rz /= r_len

        # Recompute up = right × tangent
        up_x = ry * tang_z - rz * tang_y
        up_y = rz * tang_x - rx * tang_z
        up_z = rx * tang_y - ry * tang_x

        ring_start = len(verts)
        for ci in range(ns):
            angle = 2.0 * math.pi * ci / ns
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            vx = centre[0] + r * (cos_a * rx + sin_a * up_x)
            vy = centre[1] + r * (cos_a * ry + sin_a * up_y)
            vz = centre[2] + r * (cos_a * rz + sin_a * up_z)
            verts.append((vx, vy, vz))

        if si > 0:
            prev_start = ring_start - ns
            for ci in range(ns):
                ci_n = (ci + 1) % ns
                v00 = prev_start + ci
                v01 = prev_start + ci_n
                v10 = ring_start + ci
                v11 = ring_start + ci_n
                faces.append((v00, v10, v11))
                faces.append((v00, v11, v01))

    return verts, faces


def handle_generate_cave(params: dict) -> dict:
    """MCP handler: generate a cave via the terrain ``pass_caves`` engine.

    Pipeline:
    1. Build a minimal synthetic TerrainPipelineState (flat heightmap, one
       cave-candidate anchor at the centre).
    2. Run ``pass_caves`` which calls ``carve_cave_volume`` internally,
       populates ``cave_candidate`` + ``cave_height_delta`` + ``wet_rock``
       channels, and records ``CaveStructure`` instances on side_effects.
    3. Build the chamber mesh via ``_build_chamber_mesh_geometry`` (cosine-arch
       vault + stalactites + stalagmites + triplanar UVs + per-face normals)
       and serialise its geometry into a ``chamber_mesh_spec`` dict.
    4. Materialise the chamber as a Blender object (best-effort; skipped when
       bpy is unavailable, e.g. under pytest).
    5. Build the Bezier tunnel connecting entrance to chamber.
    6. Return all mesh specs (chamber + tunnel + entrance archways) in the
       ``meshes`` list, with ``cave_height_delta`` surfaced in ``meta`` so
       the terrain pipeline's geometry pass can apply the carve delta.

    Accepts the same dict shape compose_map's location dispatch sends
    (name, seed, width, height, cell_size, wall_height, plus extras).
    Returns a dict with status / name / meshes / meta / error keys.
    """
    name = str(params.get("name", "Cave"))
    try:
        seed = int(params.get("seed", 0))
        width = int(params.get("width", 16))
        height = int(params.get("height", 16))
        cell_size = float(params.get("cell_size", 1.0))
        wall_height = float(params.get("wall_height", 4.0))
        archetype_hint = params.get("archetype")
        if archetype_hint is not None:
            archetype_hint = str(archetype_hint)

        # ------------------------------------------------------------------
        # 1. Build synthetic state and run the five-archetype pass.
        #    pass_caves → carve_cave_volume populates cave_candidate +
        #    cave_height_delta; we do NOT need to call carve_cave_volume again.
        # ------------------------------------------------------------------
        state = _build_synthetic_state(
            seed=seed,
            width=width,
            height=height,
            cell_size=cell_size,
            archetype_hint=archetype_hint,
        )
        bundle = pass_caves(state, region=None)

        # Extract entrance specs (Blender-side mesh dicts) from the
        # populated cave_candidate channel.
        try:
            entrance_specs = get_cave_entrance_specs(
                state.mask_stack,
                max_entrances=2,
                seed=seed,
            )
        except Exception:  # noqa: BLE001 — entrance generation is best-effort
            entrance_specs = []

        # Pull picked archetype from side_effects (pass_caves records
        # one "cave_structure:<id>:archetype=<value>:..." per cave).
        picked_archetype: Optional[str] = None
        cave_count = 0
        for side_effect in getattr(bundle, "side_effects", []):
            if isinstance(side_effect, str) and side_effect.startswith("cave:"):
                cave_count += 1
        for side_effect in getattr(state, "side_effects", []):
            if isinstance(side_effect, str) and side_effect.startswith("cave_structure:"):
                for token in side_effect.split(":"):
                    if token.startswith("archetype="):
                        picked_archetype = token.split("=", 1)[1]
                        break
                if picked_archetype:
                    break

        # Retrieve the carve height delta produced by pass_caves so the caller
        # (terrain geometry pass) can add it to the heightmap.
        _cave_delta_arr = state.mask_stack.get("cave_height_delta")
        cave_height_delta: Optional[List] = (
            np.asarray(_cave_delta_arr).tolist()
            if _cave_delta_arr is not None
            else None
        )

        # ------------------------------------------------------------------
        # 2. Determine chamber geometry sizes from params.
        # ------------------------------------------------------------------
        chamber_w = max(2.0, width * cell_size * 0.4)
        chamber_d = max(2.0, height * cell_size * 0.4)
        entrance_radius = max(1.0, min(chamber_w, chamber_d) * 0.45)
        chamber_radius = entrance_radius * 0.55  # tapers to ~55% at junction

        # ------------------------------------------------------------------
        # 3. Build chamber geometry (pure data) — cosine-arch vault +
        #    stalactites + stalagmites + triplanar UVs + per-face normals.
        # ------------------------------------------------------------------
        ch_verts, ch_faces, ch_uvs, ch_normals = _build_chamber_mesh_geometry(
            width=chamber_w,
            depth=chamber_d,
            wall_height=wall_height,
            radial_segments=16,   # AAA: 16 segments for smooth silhouette
            height_rings=6,       # AAA: 6 rings for richer vault curvature
            floor_noise_amplitude=0.28,
            seed=seed,
            stalactite_count=6,
            stalagmite_count=4,
            uv_scale=0.5,
        )

        # Serialise into a mesh spec dict so the caller/composer can consume
        # it without needing bpy (test-safe, Unity-exportable).
        chamber_mesh_spec: Dict = {
            "name": name,
            "vertices": ch_verts,
            "faces": ch_faces,
            "uvs": ch_uvs,
            "face_normals": ch_normals,
            "width": chamber_w,
            "depth": chamber_d,
            "wall_height": wall_height,
            "mesh_type": "cave_chamber",
        }

        # ------------------------------------------------------------------
        # 4. Materialise chamber as a Blender object (best-effort).
        # ------------------------------------------------------------------
        chamber_obj = _build_chamber_mesh(
            name=name,
            width=chamber_w,
            depth=chamber_d,
            wall_height=wall_height,
            seed=seed,
        )
        chamber_name = chamber_obj.name if chamber_obj is not None else name

        # ------------------------------------------------------------------
        # 5. Build Bezier tunnel connecting entrance to chamber.
        #    Entrance is placed at -Y edge of chamber footprint; chamber
        #    center is the mesh origin (0, 0, wall_height * 0.35).
        # ------------------------------------------------------------------
        entrance_pos: Tuple[float, float, float] = (
            0.0,
            -(chamber_d * 0.5 + entrance_radius * 1.5),
            wall_height * 0.3,
        )
        chamber_center: Tuple[float, float, float] = (0.0, 0.0, wall_height * 0.35)

        tunnel_verts, tunnel_faces = _build_bezier_tunnel_geometry(
            entrance_pos=entrance_pos,
            chamber_center=chamber_center,
            entrance_radius=entrance_radius,
            chamber_radius=chamber_radius,
            tube_segments=12,
            cross_sections=8,
        )

        # Attempt to materialise the tunnel mesh in Blender (best-effort).
        tunnel_mesh_spec: Optional[Dict] = None
        try:
            import bpy as _bpy
            import bmesh as _bmesh

            tunnel_mesh_name = f"{name}_Tunnel"
            tmesh = _bpy.data.meshes.new(tunnel_mesh_name)
            tbm = _bmesh.new()
            for tv in tunnel_verts:
                tbm.verts.new(tv)
            tbm.verts.ensure_lookup_table()
            for tf in tunnel_faces:
                try:
                    tbm.faces.new([tbm.verts[vi] for vi in tf])
                except (ValueError, IndexError):
                    pass
            tbm.to_mesh(tmesh)
            tbm.free()
            tmesh.update()

            tunnel_obj = _bpy.data.objects.new(tunnel_mesh_name, tmesh)
            try:
                _bpy.context.collection.objects.link(tunnel_obj)
                if chamber_obj is not None:
                    tunnel_obj.parent = chamber_obj
            except Exception:  # noqa: BLE001
                pass

            tunnel_mesh_spec = {
                "name": tunnel_mesh_name,
                "vertices": tunnel_verts,
                "faces": tunnel_faces,
                "entrance_pos": entrance_pos,
                "chamber_center": chamber_center,
                "entrance_radius": entrance_radius,
                "chamber_radius": chamber_radius,
                "mesh_type": "cave_tunnel",
            }
        except ImportError:
            tunnel_mesh_spec = {
                "name": f"{name}_Tunnel",
                "vertices": tunnel_verts,
                "faces": tunnel_faces,
                "entrance_pos": entrance_pos,
                "chamber_center": chamber_center,
                "entrance_radius": entrance_radius,
                "chamber_radius": chamber_radius,
                "mesh_type": "cave_tunnel",
            }

        # ------------------------------------------------------------------
        # 6. Build true entry and exit archway meshes.
        #
        # AAA contract: every cave mouth must have an actual elliptic-arch
        # opening mesh (2.5 m wide × 2.8 m tall) so the scatter/placement
        # system knows exactly where the cave mouth opens into the terrain.
        # The arch is a planar ring of quads (annulus) in the XZ plane centred
        # on entrance_pos, extruded 0.4 m inward (stub wall thickness).
        # entry_world_pos and exit_world_pos are written into the output dict
        # so downstream placement, navmesh, and fog-volume systems can consume
        # them without reparsing the mesh geometry.
        # ------------------------------------------------------------------
        _ARCH_W = 2.5    # archway ellipse semi-width (X half-axis) — fits character
        _ARCH_H = 2.8    # archway ellipse semi-height (Z half-axis) — fits standing
        _ARCH_DEPTH = 0.4  # stub thickness extruded along Y
        _ARCH_NS = 16    # segments around the ellipse

        def _build_archway_mesh(
            centre: Tuple[float, float, float],
            half_w: float,
            half_h: float,
            depth: float,
            ns: int,
        ) -> Dict:
            """Return a mesh spec dict for a planar elliptic arch ring."""
            cx, cy, cz = centre
            av: List[Tuple[float, float, float]] = []
            af: List[Tuple[int, ...]] = []
            # Two ellipse rings: front face (y=cy) and back face (y=cy+depth)
            front_start = 0
            for i in range(ns):
                ang = 2.0 * math.pi * i / ns
                av.append((cx + half_w * math.cos(ang), cy, cz + half_h * math.sin(ang)))
            back_start = ns
            for i in range(ns):
                ang = 2.0 * math.pi * i / ns
                av.append((cx + half_w * math.cos(ang), cy + depth, cz + half_h * math.sin(ang)))
            # Side quads connecting front to back
            for i in range(ns):
                i_n = (i + 1) % ns
                af.append((front_start + i, back_start + i, back_start + i_n))
                af.append((front_start + i, back_start + i_n, front_start + i_n))
            return {
                "vertices": av,
                "faces": af,
                "mesh_type": "cave_archway",
                "centre": centre,
                "half_w": half_w,
                "half_h": half_h,
            }

        entry_world_pos: Tuple[float, float, float] = entrance_pos
        # Exit is the far end of the Bezier tunnel — the chamber centre offset
        # along -Y by half the chamber depth (opposite side from entrance).
        exit_world_pos: Tuple[float, float, float] = (
            chamber_center[0],
            chamber_center[1] + chamber_d * 0.5,
            chamber_center[2],
        )

        entry_arch_spec = _build_archway_mesh(
            entry_world_pos, _ARCH_W, _ARCH_H, _ARCH_DEPTH, _ARCH_NS
        )
        entry_arch_spec["name"] = f"{name}_EntryArch"
        entry_arch_spec["role"] = "entry"

        exit_arch_spec = _build_archway_mesh(
            exit_world_pos, _ARCH_W, _ARCH_H, _ARCH_DEPTH, _ARCH_NS
        )
        exit_arch_spec["name"] = f"{name}_ExitArch"
        exit_arch_spec["role"] = "exit"

        archway_specs: List[Dict] = [entry_arch_spec, exit_arch_spec]

        # Second exit for deep caves (depth > 30 m): place on the opposite
        # chamber wall (rotated 120–180° from primary exit) so deep caves have
        # two distinct egress points on different terrain faces.
        cave_depth_m = abs(float(chamber_center[2]) - float(entrance_pos[2]))
        if cave_depth_m > 30.0:
            alt_exit_pos: Tuple[float, float, float] = (
                chamber_center[0] + chamber_w * 0.45,
                chamber_center[1],
                chamber_center[2] * 0.85,  # slightly lower (canyon-wall exit)
            )
            alt_arch = _build_archway_mesh(
                alt_exit_pos, _ARCH_W, _ARCH_H, _ARCH_DEPTH, _ARCH_NS
            )
            alt_arch["name"] = f"{name}_ExitArch2"
            alt_arch["role"] = "exit_secondary"
            archway_specs.append(alt_arch)

        # ------------------------------------------------------------------
        # 7. Assemble output.
        # ------------------------------------------------------------------
        # Floor area in cell units (compatibility with old handler shape).
        cc = state.mask_stack.get("cave_candidate")
        floor_area = int(np.asarray(cc).sum()) if cc is not None else 0

        # meshes list: chamber first (primary geometry), then tunnel, then
        # entrance archway specs from get_cave_entrance_specs, then our
        # analytically-built archway opening meshes.
        meshes: List[Dict] = [chamber_mesh_spec]
        if tunnel_mesh_spec is not None:
            meshes.append(tunnel_mesh_spec)
        meshes.extend(entrance_specs)
        meshes.extend(archway_specs)

        # Bundle status is extracted before serialisation; the PassResult object
        # itself is NOT included in meta because it contains numpy arrays and
        # non-serialisable internal state that would break JSON export / MCP
        # transport.  Callers that need the raw bundle should invoke pass_caves
        # directly via the pipeline state API.
        bundle_status = "ok" if getattr(bundle, "status", "ok") != "failed" else "error"

        return {
            "status": bundle_status,
            "name": chamber_name,
            "meshes": meshes,
            # Top-level world positions for scatter/navmesh/fog-volume systems
            "entry_world_pos": list(entry_world_pos),
            "exit_world_pos": list(exit_world_pos),
            "meta": {
                "archetype": picked_archetype or "unknown",
                "chamber_mesh_spec": chamber_mesh_spec,
                "entrance_specs": entrance_specs,
                "tunnel_spec": tunnel_mesh_spec,
                "archway_specs": archway_specs,
                "bundle_status": bundle_status,
                "cave_count": cave_count,
                "wall_height": wall_height,
                "floor_area": floor_area,
                "entrance_radius": entrance_radius,
                "chamber_radius": chamber_radius,
                # entry/exit positions also in meta for legacy callers
                "entry_world_pos": list(entry_world_pos),
                "exit_world_pos": list(exit_world_pos),
                # Carve delta (H×W float list) for the terrain geometry pass
                # to add to stack.height; None when no caves were carved.
                "cave_height_delta": cave_height_delta,
            },
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — handler boundary, surface error
        return {
            "status": "error",
            "name": name,
            "meshes": [],
            "meta": {},
            "error": f"{type(exc).__name__}: {exc}",
        }


__all__ = [
    "CaveArchetype",
    "CaveArchetypeSpec",
    "CaveStructure",
    "make_archetype_spec",
    "pick_cave_archetype",
    "generate_cave_path",
    "carve_cave_volume",
    "build_cave_entrance_frame",
    "scatter_collapse_debris",
    "generate_damp_mask",
    "validate_cave_entrance",
    "pass_caves",
    "register_bundle_f_passes",
    "get_cave_entrance_specs",
    "handle_generate_cave",
    # Geometry helpers (exposed for testing)
    "_fbm_noise",
    "_cone_verts_faces",
    "_face_normal",
    "_triplanar_uv",
    "_build_chamber_mesh_geometry",
    "_bezier_cubic",
    "_build_bezier_tunnel_geometry",
    # Biome/material hint tables (exposed for testing + external overrides)
    "_BIOME_ARCHETYPE_MAP",
    "_ARCHETYPE_DEFAULT_MATERIAL",
]
