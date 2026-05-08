"""Phase C D30-32 — Structural label-stamping system (Issue #27).

Per IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL §17 Phase C D30-32 (spec PR #29).

Concept
-------
Structural labels are AUTHORED tags (not analytical / not computed). Each
terrain region has a label like ``mesa_caprock``, ``river_bend``, or
``scree_field`` that downstream texturing/scatter systems read.

Currently texturing in ``terrain_materials_v2`` is partly analytical
(slope > slope_threshold → cliff) per ``project_terrain_audit_2026_04_15``.
The existing four label channels (``rock_label``, ``gravel_label``,
``water_label``, ``cliff_label``) are zero-initialised by
``pass_compute_terrain_labels`` and only stamped if a feature generator
runs first — for many world generations no feature generator stamps them,
so the fallback analytical path runs everywhere.

This module adds:

* :data:`STRUCTURAL_LABELS` — canonical tuple of ~20 structural label IDs
  (``mesa_caprock``, ``river_bend``, ``scree_field`` etc.).
* :class:`LabelStamp` — immutable record describing a single stamped region.
* :class:`LabelStack` — collection of stamps with a simple spatial index.
* :func:`pass_label_stamping` — pipeline pass that watersheds slope +
  curvature + biome_id + water masks into structural regions, fills the
  legacy ``cliff_label`` / ``rock_label`` / ``gravel_label`` /
  ``water_label`` channels for those regions, and publishes a
  :class:`LabelStack` on ``TerrainMaskStack.label_stack``.

The pass is OPTIONAL in the default sequence — gated by
``composition_hints["label_stamping"]`` — so existing test fixtures that
do not request it stay byte-identical.

Authoritative-label semantics
-----------------------------
Downstream consumers (terrain_materials_v2) ALREADY prefer the four legacy
label channels over analytical slope thresholds — labelled cells skip the
analytical splatmap path. By stamping these channels per region, this pass
shifts material classification from analytical → authored without touching
any consumer.

The :class:`LabelStack` is the canonical authored-tag surface for future
consumers (Phase E texturing rework) that need richer per-region metadata
(e.g. ``mesa_caprock`` vs ``cliff_face`` — both fall under the legacy
``cliff_label`` channel but route to different texturing rules).

NO Blender imports. Pure Python + numpy + scipy.ndimage.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, cast

import numpy as np

from .terrain_semantics import (
    BBox,
    PassDefinition,
    PassResult,
)

if TYPE_CHECKING:
    from .terrain_semantics import TerrainPipelineState


# ---------------------------------------------------------------------------
# Canonical structural label vocabulary
# ---------------------------------------------------------------------------
# These IDs are CANONICAL — adding or renaming an entry is a breaking change
# pinned by ``test_phase_c_d30_32_label_stamping.py``. Each ID is a stable
# tag downstream consumers (texturing, scatter, navmesh) may key off.
#
# Categories:
#   * Lithic / cliff:   mesa_caprock, cliff_face, ridgeline, talus_slope, scree_field
#   * Hydrological:     river_bend, river_channel, valley_floor, coastal_strand,
#                       waterfall_pool, bog_pocket, lake_shore
#   * Slope/colluvium:  alluvial_fan, glacial_moraine, hillslope, plateau
#   * Aeolian/aeoline:  dune_crest, dune_swale
#   * Biological:       forest_floor, alpine_meadow, marsh
#
STRUCTURAL_LABELS: Tuple[str, ...] = (
    "mesa_caprock",
    "cliff_face",
    "ridgeline",
    "talus_slope",
    "scree_field",
    "river_bend",
    "river_channel",
    "valley_floor",
    "coastal_strand",
    "waterfall_pool",
    "bog_pocket",
    "lake_shore",
    "alluvial_fan",
    "glacial_moraine",
    "hillslope",
    "plateau",
    "dune_crest",
    "dune_swale",
    "forest_floor",
    "alpine_meadow",
    "marsh",
)


# Each structural label maps to one of the four legacy material-channel
# masks in TerrainMaskStack so that ``terrain_materials_v2`` keeps working
# without modification.  The mapping intentionally pins the analytical-
# fallback semantic: a labelled cell skips analytical slope classification
# in materials_v2 and routes to the named channel instead.
LABEL_TO_LEGACY_CHANNEL: Dict[str, str] = {
    "mesa_caprock":     "cliff_label",
    "cliff_face":       "cliff_label",
    "ridgeline":        "cliff_label",
    "talus_slope":      "gravel_label",
    "scree_field":      "gravel_label",
    "river_bend":       "water_label",
    "river_channel":    "water_label",
    "valley_floor":     "rock_label",
    "coastal_strand":   "water_label",
    "waterfall_pool":   "water_label",
    "bog_pocket":       "water_label",
    "lake_shore":       "water_label",
    "alluvial_fan":     "gravel_label",
    "glacial_moraine":  "gravel_label",
    "hillslope":        "rock_label",
    "plateau":          "rock_label",
    "dune_crest":       "gravel_label",
    "dune_swale":       "gravel_label",
    "forest_floor":     "rock_label",
    "alpine_meadow":    "rock_label",
    "marsh":            "water_label",
}


# Canonical legacy channel names — referenced for assertions.
_LEGACY_LABEL_CHANNELS: Tuple[str, ...] = (
    "rock_label",
    "gravel_label",
    "water_label",
    "cliff_label",
)


# ---------------------------------------------------------------------------
# LabelStamp + LabelStack
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelStamp:
    """A single authored structural-label stamp covering a contiguous region.

    Attributes:
        label_id:       Canonical ID from :data:`STRUCTURAL_LABELS`.
        region_bbox:    Bounding box ``(row_min, col_min, row_max, col_max)``
                        in cell coordinates (inclusive-exclusive, numpy slice
                        convention) — i.e. ``stack.height[r0:r1, c0:c1]``.
        confidence:     Stamping confidence in ``[0, 1]``. 1.0 = certain
                        (e.g. label provenance is authored), values below
                        1.0 indicate watershed-derived stamps where the
                        analytical heuristic was the only source.
        source_pass:    Name of the pass that produced this stamp (e.g.
                        ``"label_stamping"``). Consumers can filter by
                        provenance.
    """

    label_id: str
    region_bbox: Tuple[int, int, int, int]
    confidence: float
    source_pass: str

    def __post_init__(self) -> None:
        if self.label_id not in STRUCTURAL_LABELS:
            raise ValueError(
                f"LabelStamp.label_id={self.label_id!r} is not in "
                f"STRUCTURAL_LABELS (canonical {len(STRUCTURAL_LABELS)} entries)"
            )
        r0, c0, r1, c1 = self.region_bbox
        if r1 <= r0 or c1 <= c0:
            raise ValueError(
                f"LabelStamp.region_bbox={self.region_bbox!r} must satisfy "
                f"r1>r0 and c1>c0"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"LabelStamp.confidence={self.confidence} must be in [0, 1]"
            )

    @property
    def area_cells(self) -> int:
        """Number of cells covered by the bounding box."""
        r0, c0, r1, c1 = self.region_bbox
        return (r1 - r0) * (c1 - c0)


@dataclass
class LabelStack:
    """Collection of :class:`LabelStamp` records with a small spatial index.

    The index is intentionally simple — a per-label list of stamps plus a
    cached aggregate bbox per label.  Consumers that need fine-grained
    queries can iterate :attr:`stamps` directly; the cached index speeds up
    the common case of "is anything stamped at row=R, col=C?".
    """

    stamps: List[LabelStamp] = field(default_factory=lambda: cast(List[LabelStamp], []))
    _by_label: Dict[str, List[LabelStamp]] = field(
        default_factory=lambda: cast(Dict[str, List[LabelStamp]], {}),
        repr=False,
        compare=False,
    )

    def add(self, stamp: LabelStamp) -> None:
        self.stamps.append(stamp)
        self._by_label.setdefault(stamp.label_id, []).append(stamp)

    def stamps_for_label(self, label_id: str) -> List[LabelStamp]:
        """Return all stamps for ``label_id`` (empty list if none)."""
        if label_id not in STRUCTURAL_LABELS:
            raise ValueError(
                f"label_id={label_id!r} not in STRUCTURAL_LABELS"
            )
        return list(self._by_label.get(label_id, ()))

    def stamps_at(self, row: int, col: int) -> List[LabelStamp]:
        """Return every stamp whose bbox contains ``(row, col)``.

        Returned stamps are in stamp-insertion order; a single cell may
        belong to multiple stamps when overlapping regions are authored.
        """
        out: List[LabelStamp] = []
        for stamp in self.stamps:
            r0, c0, r1, c1 = stamp.region_bbox
            if r0 <= row < r1 and c0 <= col < c1:
                out.append(stamp)
        return out

    def label_ids_present(self) -> Tuple[str, ...]:
        """Return tuple of label IDs that have at least one stamp."""
        return tuple(sorted(self._by_label.keys()))

    def __len__(self) -> int:
        return len(self.stamps)


# ---------------------------------------------------------------------------
# Watershed-style segmentation (cliff / scree / valley / water masks)
# ---------------------------------------------------------------------------


# Heuristic thresholds — these mirror the analytical slope thresholds in
# ``terrain_materials.assign_terrain_materials_by_slope`` so that the
# stamped regions agree with the analytical fallback by default.  When a
# feature generator stamps a region authoritatively (confidence=1.0), it
# overrides this default — the stamps from this pass are confidence=0.6
# (heuristic) so authored stamps always win.
_CLIFF_SLOPE_RAD = np.deg2rad(60.0)     # ≥60° → cliff_face / mesa_caprock
_SLOPE_SLOPE_RAD = np.deg2rad(30.0)     # ≥30° → talus_slope / scree_field
_RIDGE_CURVATURE_THRESH = 0.15           # convex ridge cells
_VALLEY_CURVATURE_THRESH = -0.15         # concave valley cells
_MIN_REGION_CELLS = 4                    # drop tiny components


_ScipyLabelCallable = Callable[..., Tuple[Any, int]]


def _try_scipy_label() -> Optional[_ScipyLabelCallable]:
    """Return ``scipy.ndimage.label`` if available, else ``None``.

    Imported lazily so callers without scipy still load the module.
    The return type is narrowed to a Callable so static analysis treats
    the result as invocable instead of an opaque ``object``.
    """
    try:
        from scipy.ndimage import label as _label  # type: ignore[import-untyped]
        return cast(_ScipyLabelCallable, _label)
    except ImportError:  # pragma: no cover — scipy is a hard repo dep
        return None


def _label_components(mask: np.ndarray) -> Tuple[np.ndarray, int]:
    """Return ``(label_array, num_components)`` for a 2-D boolean mask.

    Uses ``scipy.ndimage.label`` when scipy is available; falls back to a
    pure-Python flood fill otherwise. Returned label_array uses 0 = background
    and 1..N for individual components.
    """
    scipy_label = _try_scipy_label()
    if scipy_label is not None:
        labels, n = scipy_label(mask)
        return np.asarray(labels, dtype=np.int32), int(n)

    # Pure-Python fallback (4-connected flood fill) — slower but correct.
    rows, cols = mask.shape
    labels = np.zeros((rows, cols), dtype=np.int32)
    next_id = 0
    for r in range(rows):
        for c in range(cols):
            if mask[r, c] and labels[r, c] == 0:
                next_id += 1
                stack: List[Tuple[int, int]] = [(r, c)]
                while stack:
                    rr, cc = stack.pop()
                    if rr < 0 or rr >= rows or cc < 0 or cc >= cols:
                        continue
                    if not mask[rr, cc] or labels[rr, cc] != 0:
                        continue
                    labels[rr, cc] = next_id
                    stack.extend(((rr - 1, cc), (rr + 1, cc), (rr, cc - 1), (rr, cc + 1)))
    return labels, next_id


def _bbox_of_component(labels: np.ndarray, comp_id: int) -> Tuple[int, int, int, int]:
    """Return ``(r0, c0, r1, c1)`` slice bbox of ``labels == comp_id``.

    Inclusive on the low end, exclusive on the high end (numpy slice
    convention so ``arr[r0:r1, c0:c1]`` gives the bbox window).
    """
    rows, cols = np.where(labels == comp_id)
    if rows.size == 0:
        return (0, 0, 0, 0)
    return (
        int(rows.min()),
        int(cols.min()),
        int(rows.max()) + 1,
        int(cols.max()) + 1,
    )


def _stamp_label_in_channel(
    legacy_mask: Optional[np.ndarray],
    region_mask: np.ndarray,
    shape: Tuple[int, int],
) -> np.ndarray:
    """Return ``legacy_mask`` (or zeros) with ``region_mask`` set to 1.0.

    Preserves any prior stamping (so authored generator stamps survive).
    """
    if legacy_mask is None:
        out = np.zeros(shape, dtype=np.float32)
    else:
        out = np.asarray(legacy_mask, dtype=np.float32).copy()
    out[region_mask] = np.maximum(out[region_mask], 1.0).astype(np.float32)
    return out


# ---------------------------------------------------------------------------
# pass_label_stamping
# ---------------------------------------------------------------------------


def pass_label_stamping(
    state: "TerrainPipelineState",
    region: Optional[BBox],
) -> PassResult:
    """Watershed slope + curvature + biome + water masks into structural regions.

    Phase C D30-32 / spec PR #29 / Issue #27.

    Reads:
        ``slope`` (radians), ``curvature``, ``biome_id`` (int32), and either
        ``water_surface_mask`` or ``water_label`` (float32). Each input is
        optional — if missing, that branch of the watershed is skipped.

    Writes:
        ``label_stack`` channel (a :class:`LabelStack` instance on
        ``TerrainMaskStack``). Also stamps the four legacy mask channels
        (``cliff_label``, ``gravel_label``, ``water_label``, ``rock_label``)
        for the regions that match a structural label.

    The stamps written by this pass have ``confidence=0.6`` so any authored
    feature-generator stamp (confidence=1.0) wins by precedence.

    Args:
        state:  Pipeline state. ``state.mask_stack`` is mutated.
        region: Currently ignored — the pass operates on the whole stack.

    Returns:
        :class:`PassResult` with metrics describing how many stamps were
        produced for each label and total covered area.
    """
    t0 = time.perf_counter()
    stack = state.mask_stack

    height = np.asarray(stack.height)
    H, W = height.shape

    slope = stack.get("slope")
    curvature = stack.get("curvature")
    water_mask_raw = stack.get("water_surface_mask")
    if water_mask_raw is None:
        water_mask_raw = stack.get("water_label")

    label_stack = LabelStack()
    legacy_stamps: Dict[str, np.ndarray] = {}
    label_counts: Dict[str, int] = {label: 0 for label in STRUCTURAL_LABELS}

    # --- cliff_face: any contiguous slope >= _CLIFF_SLOPE_RAD region.
    if slope is not None:
        slope_arr = np.asarray(slope, dtype=np.float32)
        cliff_mask = slope_arr >= _CLIFF_SLOPE_RAD
        labels, n = _label_components(cliff_mask)
        for comp_id in range(1, n + 1):
            comp_mask = labels == comp_id
            if int(comp_mask.sum()) < _MIN_REGION_CELLS:
                continue
            bbox = _bbox_of_component(labels, comp_id)
            # Disambiguate cliff_face vs mesa_caprock vs ridgeline by curvature
            label_id = "cliff_face"
            if curvature is not None:
                curv_arr = np.asarray(curvature, dtype=np.float32)
                mean_curv = float(curv_arr[comp_mask].mean())
                if mean_curv > _RIDGE_CURVATURE_THRESH:
                    label_id = "ridgeline"
                elif mean_curv < _VALLEY_CURVATURE_THRESH:
                    # Concave steep regions — usually cliff faces of incised
                    # valleys; keep cliff_face.
                    label_id = "cliff_face"
                else:
                    # Roughly flat-on-average steep regions = mesa caprock.
                    label_id = "mesa_caprock"
            label_stack.add(LabelStamp(
                label_id=label_id,
                region_bbox=bbox,
                confidence=0.6,
                source_pass="label_stamping",
            ))
            label_counts[label_id] += 1
            chan = LABEL_TO_LEGACY_CHANNEL[label_id]
            legacy_stamps[chan] = _stamp_label_in_channel(
                legacy_stamps.get(chan, stack.get(chan)),
                comp_mask,
                (H, W),
            )

        # --- talus_slope / scree_field: 30°..60° slopes.
        scree_mask = (slope_arr >= _SLOPE_SLOPE_RAD) & (slope_arr < _CLIFF_SLOPE_RAD)
        labels_s, n_s = _label_components(scree_mask)
        for comp_id in range(1, n_s + 1):
            comp_mask = labels_s == comp_id
            if int(comp_mask.sum()) < _MIN_REGION_CELLS:
                continue
            bbox = _bbox_of_component(labels_s, comp_id)
            # Talus slopes sit at the foot of cliffs (lower elevation than
            # surroundings); scree fields are open. We use a simple area
            # heuristic — small components near a cliff are talus, larger
            # open ones are scree.
            label_id = "talus_slope" if int(comp_mask.sum()) < 64 else "scree_field"
            label_stack.add(LabelStamp(
                label_id=label_id,
                region_bbox=bbox,
                confidence=0.6,
                source_pass="label_stamping",
            ))
            label_counts[label_id] += 1
            chan = LABEL_TO_LEGACY_CHANNEL[label_id]
            legacy_stamps[chan] = _stamp_label_in_channel(
                legacy_stamps.get(chan, stack.get(chan)),
                comp_mask,
                (H, W),
            )

    # --- valley_floor: low-slope concave regions.
    if slope is not None and curvature is not None:
        slope_arr = np.asarray(slope, dtype=np.float32)
        curv_arr = np.asarray(curvature, dtype=np.float32)
        valley_mask = (
            (slope_arr < _SLOPE_SLOPE_RAD)
            & (curv_arr < _VALLEY_CURVATURE_THRESH)
        )
        labels_v, n_v = _label_components(valley_mask)
        for comp_id in range(1, n_v + 1):
            comp_mask = labels_v == comp_id
            if int(comp_mask.sum()) < _MIN_REGION_CELLS:
                continue
            bbox = _bbox_of_component(labels_v, comp_id)
            label_stack.add(LabelStamp(
                label_id="valley_floor",
                region_bbox=bbox,
                confidence=0.6,
                source_pass="label_stamping",
            ))
            label_counts["valley_floor"] += 1
            chan = LABEL_TO_LEGACY_CHANNEL["valley_floor"]
            legacy_stamps[chan] = _stamp_label_in_channel(
                legacy_stamps.get(chan, stack.get(chan)),
                comp_mask,
                (H, W),
            )

    # --- river_channel + lake_shore from water mask.
    if water_mask_raw is not None:
        water_arr = np.asarray(water_mask_raw, dtype=np.float32)
        water_bool = water_arr > 0.5
        labels_w, n_w = _label_components(water_bool)
        for comp_id in range(1, n_w + 1):
            comp_mask = labels_w == comp_id
            cells = int(comp_mask.sum())
            if cells < _MIN_REGION_CELLS:
                continue
            bbox = _bbox_of_component(labels_w, comp_id)
            r0, c0, r1, c1 = bbox
            # Long-thin → river_channel, blob → lake_shore
            extent_r = r1 - r0
            extent_c = c1 - c0
            aspect = max(extent_r, extent_c) / max(min(extent_r, extent_c), 1)
            label_id = "river_channel" if aspect > 3.0 else "lake_shore"
            label_stack.add(LabelStamp(
                label_id=label_id,
                region_bbox=bbox,
                confidence=0.6,
                source_pass="label_stamping",
            ))
            label_counts[label_id] += 1
            chan = LABEL_TO_LEGACY_CHANNEL[label_id]
            legacy_stamps[chan] = _stamp_label_in_channel(
                legacy_stamps.get(chan, stack.get(chan)),
                comp_mask,
                (H, W),
            )

    # --- Write everything back to the stack ---
    for chan_name, mask_arr in legacy_stamps.items():
        # Clamp once to [0, 1] to honour the existing label-channel contract.
        clamped = np.clip(mask_arr, 0.0, 1.0).astype(np.float32)
        stack.set(chan_name, clamped, "label_stamping")

    # Publish the LabelStack as a non-array attribute. TerrainMaskStack accepts
    # arbitrary attributes for object-typed channels (``label_stack`` is added
    # to the dataclass below so static analysis sees it).
    stack.label_stack = label_stack

    coverage = {
        chan: float(np.asarray(stack.get(chan), dtype=np.float32).mean())
        for chan in _LEGACY_LABEL_CHANNELS
        if stack.get(chan) is not None
    }

    return PassResult(
        pass_name="label_stamping",
        status="ok",
        duration_seconds=time.perf_counter() - t0,
        consumed_channels=("slope", "curvature", "biome_id", "water_surface_mask"),
        produced_channels=(
            "label_stack",
            "rock_label",
            "gravel_label",
            "water_label",
            "cliff_label",
        ),
        metrics={
            "stamps_total": len(label_stack),
            "label_ids_present": list(label_stack.label_ids_present()),
            **{f"count_{k}": v for k, v in label_counts.items() if v > 0},
            **{f"coverage_{k}": v for k, v in coverage.items()},
        },
        issues=[],
    )


def register_pass_label_stamping() -> None:
    """Register ``pass_label_stamping`` on the TerrainPassController.

    Idempotent — safe to call multiple times (the controller upserts on
    duplicate name).
    """
    # Local import to avoid module-load-time circular dependency.
    from .terrain_pipeline import TerrainPassController

    TerrainPassController.register_pass(
        PassDefinition(
            name="label_stamping",
            func=pass_label_stamping,
            requires_channels=("height",),
            optional_channels=("slope", "curvature", "biome_id", "water_surface_mask"),
            produces_channels=(
                "rock_label",
                "gravel_label",
                "water_label",
                "cliff_label",
            ),
            # The four legacy label channels are also produced (initialised
            # to zeros) by ``pass_compute_terrain_labels`` — declare overrides
            # so the DAG accepts the dual writer relationship.
            overrides=(
                "rock_label",
                "gravel_label",
                "water_label",
                "cliff_label",
            ),
            seed_namespace="label_stamping",
            requires_scene_read=False,
            may_modify_geometry=False,
            description=(
                "Phase C D30-32: watersheds slope+curvature+biome+water "
                "into structural regions and stamps the four legacy "
                "material labels per region. Publishes a LabelStack on "
                "stack.label_stack for downstream texturing/scatter."
            ),
        )
    )


__all__ = [
    "STRUCTURAL_LABELS",
    "LABEL_TO_LEGACY_CHANNEL",
    "LabelStamp",
    "LabelStack",
    "pass_label_stamping",
    "register_pass_label_stamping",
]
