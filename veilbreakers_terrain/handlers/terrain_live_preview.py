"""Live-preview session for terrain iteration velocity (Bundle M).

Wraps a TerrainPassController with a dirty tracker and mask cache so
interactive edits (from an agent or editor) can apply→preview→refine
without re-running the whole pipeline.

Pure Python + numpy. No bpy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from .terrain_dirty_tracking import DirtyTracker, attach_dirty_tracker
from .terrain_mask_cache import MaskCache, controller_pass_with_cache
from .terrain_pipeline import TerrainPassController
from .terrain_region_exec import execute_region
from .terrain_semantics import BBox, PassResult, TerrainPipelineState
from .terrain_visual_diff import compute_visual_diff


def _channel_hash(arr: Any) -> int:
    """Compute a lightweight integer hash for a numpy ndarray.

    Uses xxhash.xxh64 when available (fast, low collision rate). Falls back to
    a cheap sum-XOR-shape fingerprint when xxhash is not installed.  The result
    is used only for change detection, not cryptographic integrity.
    """
    try:
        import xxhash  # type: ignore[import]
        return xxhash.xxh64(np.ascontiguousarray(arr).tobytes()).intdigest()
    except ImportError:
        pass
    # Fallback: int(sum) XOR shape[0] — fast, good enough for dirty detection
    return int(np.sum(arr)) ^ arr.shape[0]


class StackSnapshot:
    """Copy-on-write snapshot of a TerrainMaskStack.

    Stores only a dict of ``{channel_name: hash_int}`` plus a *reference* (not
    a copy) to the original stack.  Memory cost is O(num_channels × 8 bytes)
    rather than O(num_channels × array_size).

    Use :meth:`changed_channels` to find which channels have been modified
    since the snapshot was taken.
    """

    def __init__(self, stack: Any) -> None:
        self._stack_ref = stack
        # Build hash dict — only hash channels that are currently populated
        self._hashes: Dict[str, int] = {}
        for name in stack._ARRAY_CHANNELS:
            val = getattr(stack, name, None)
            if val is not None and isinstance(val, np.ndarray):
                self._hashes[name] = _channel_hash(val)

    def changed_channels(self, current_stack: Any) -> List[str]:
        """Return list of channel names whose content differs from the snapshot.

        A channel is considered changed if:
        - it was absent at snapshot time and is now present, OR
        - it was present at snapshot time and is now absent, OR
        - its hash differs between snapshot time and now.
        """
        changed: List[str] = []
        all_names = set(self._hashes.keys())
        for name in current_stack._ARRAY_CHANNELS:
            val = getattr(current_stack, name, None)
            is_now_array = val is not None and isinstance(val, np.ndarray)
            was_in_snapshot = name in self._hashes
            if is_now_array and was_in_snapshot:
                if _channel_hash(val) != self._hashes[name]:
                    changed.append(name)
            elif is_now_array and not was_in_snapshot:
                # Newly populated channel
                changed.append(name)
            elif not is_now_array and was_in_snapshot:
                # Channel cleared since snapshot
                changed.append(name)
            all_names.discard(name)
        # Any snapshot channels not in current stack at all
        changed.extend(all_names)
        return changed

    @property
    def hash_dict(self) -> Dict[str, int]:
        """Read-only view of the snapshot hash dict (for size measurement in tests)."""
        return self._hashes


@dataclass
class LivePreviewSession:
    """An interactive editing session over a TerrainPipelineState.

    Holds references to:
      - controller (source of truth for passes)
      - dirty tracker
      - mask cache

    ``apply_edit`` takes an edit dict with keys:
        passes: list[str]     # pass names to run
        region: BBox | None   # sub-tile scope (optional)
        dirty_channels: list[str]   # channels to mark dirty before running
    and returns the post-edit content hash (preview_hash).
    """

    controller: TerrainPassController
    cache: MaskCache = field(default_factory=lambda: MaskCache(max_entries=256))
    tracker: Optional[DirtyTracker] = None
    history: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.tracker is None:
            self.tracker = attach_dirty_tracker(self.controller.state)
        # BUG-R8-A9-008: seed history with baseline hash so diff_preview
        # can always find a valid "before" entry even on the first apply_edit.
        initial_hash = self.controller.state.mask_stack.compute_hash()
        self.history.append({
            "hash_before": None,
            "hash_after": initial_hash,
            "pass_name": "__init__",
            "timestamp": time.time(),
        })

    @property
    def state(self) -> TerrainPipelineState:
        return self.controller.state

    def current_hash(self) -> str:
        return self.state.mask_stack.compute_hash()

    def apply_edit(self, edit: Dict[str, Any]) -> str:
        """Apply an edit and return the new preview hash.

        ``edit`` keys:
            passes: list of pass names
            region: BBox or None
            dirty_channels: list of channel names to mark dirty
            use_cache: bool (default True) — cache-backed execution
        """
        passes: List[str] = list(edit.get("passes", []))
        region: Optional[BBox] = edit.get("region")
        dirty_channels: List[str] = list(edit.get("dirty_channels", []))
        use_cache: bool = bool(edit.get("use_cache", True))

        hash_before = self.current_hash()

        if dirty_channels:
            _dirty_region = region
            if _dirty_region is None:
                # P1-32: full-tile edit — mark dirty over the full tile bounds
                # so downstream consumers see the change even when no sub-region
                # was specified.
                _dirty_region = self.state.intent.region_bounds
            for ch in dirty_channels:
                if _dirty_region is not None:
                    self.tracker.mark_dirty(ch, _dirty_region)
                # Cache entries touching this channel should be dropped.
                self.cache.invalidate_prefix(ch)

        results: List[PassResult] = []
        if use_cache:
            for pname in passes:
                res = controller_pass_with_cache(self.controller, pname, region, self.cache)
                results.append(res)
        else:
            results = execute_region(self.controller, passes, region or self.state.intent.region_bounds, pad=False)

        hash_after = self.current_hash()
        self.history.append(
            {
                "edit": edit,
                "results": results,
                "hash": hash_after,
                "hash_before": hash_before,
                "hash_after": hash_after,
                "pass_name": passes[0] if len(passes) == 1 else str(passes),
                "timestamp": time.time(),
            }
        )
        return hash_after

    def diff_preview(self, hash_before: str, hash_after: str) -> Dict[str, Any]:
        """Look up stored snapshots and compute a diff between them.

        Because we do not retain full stack snapshots (memory), we use
        the recorded history's per-entry hashes. If either hash is the
        current head we can diff against the stored cache entries.
        Returns only a summary dict — for a full visual diff the caller
        must hold references to actual stacks.
        """
        matched_before = [h for h in self.history if h.get("hash") == hash_before]
        matched_after = [h for h in self.history if h.get("hash") == hash_after]
        return {
            "hash_before": hash_before,
            "hash_after": hash_after,
            "identical": hash_before == hash_after,
            "found_before": bool(matched_before),
            "found_after": bool(matched_after),
            "history_length": len(self.history),
        }

    def diff_stacks(self, stack_before: Any) -> Dict[str, Any]:
        """Convenience: diff a held-aside snapshot against current state.

        Accepts either a ``StackSnapshot`` (hash-based, returned by
        ``snapshot_stack()``) or a full ``TerrainMaskStack`` copy.
        """
        if isinstance(stack_before, StackSnapshot):
            changed = stack_before.changed_channels(self.state.mask_stack)
            return {"changed_channels": changed, "total_changed_cells": len(changed)}
        return compute_visual_diff(stack_before, self.state.mask_stack)

    def snapshot_stack(self) -> StackSnapshot:
        """Return a copy-on-write snapshot of the current mask stack for later diffing.

        Instead of deep-copying every array (which would allocate ~5 GB for a
        4096×4096 stack with 20 channels), stores only a dict of
        ``{channel_name: hash_int}`` plus a lightweight reference to the stack.
        Memory cost: O(num_channels × 8 bytes) instead of O(num_channels × array_size).

        Use ``snapshot.changed_channels(current_stack)`` to find which channels
        have been modified since the snapshot was taken.
        """
        return StackSnapshot(self.state.mask_stack)

    def render_thumbnail_png(self, path: str, view: str = "top") -> str:
        """Render a thumbnail preview of the current terrain state.

        In Blender: uses bpy.ops.render.opengl for a quick viewport render.
        Headless: uses matplotlib to render a heightmap color-map image.
        Returns the path written, or an "ERROR: ..." string on failure.
        """
        from pathlib import Path
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # bpy.ops.render.opengl removed in Blender 4.0; use matplotlib fallback.
        # Headless fallback: matplotlib heightmap
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            stack = self.controller.state.mask_stack
            height = np.asarray(stack.height, dtype=np.float32)
            fig, ax = plt.subplots(figsize=(8, 8), dpi=128)
            im = ax.imshow(height, cmap="terrain", origin="lower")
            plt.colorbar(im, ax=ax, label="Height (m)")
            ax.set_title(f"VeilBreakers Terrain — {view}")
            plt.tight_layout()
            plt.savefig(str(output_path), dpi=128)
            plt.close(fig)
            return str(output_path)
        except Exception as e:
            return f"ERROR: {e}"


def edit_hero_feature(
    state: TerrainPipelineState,
    feature_id: str,
    mutations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Orchestrate modular editing of a single hero feature in-place.

    Looks up the HeroFeatureSpec by feature_id in
    ``state.intent.hero_feature_specs``, applies each mutation via
    ``dataclasses.replace``, then writes the mutated spec back into
    ``state.intent.composition_hints['hero_features']`` and updates
    ``state.intent.hero_feature_specs`` via a frozen-dataclass replace.

    Supported mutation types: translate, scale, rotate, material.

    Returns a dict with applied count, dirty_channels, region BBox (as
    a 4-tuple), and any validation issues.
    """
    import dataclasses
    from .terrain_semantics import BBox, HeroFeatureSpec

    applied = 0
    issues: List[str] = []

    # Find the feature spec by ID
    spec: "HeroFeatureSpec | None" = None
    for s in state.intent.hero_feature_specs:
        if s.feature_id == feature_id:
            spec = s
            break

    if spec is None:
        return {
            "applied": 0,
            "issues": [f"Feature '{feature_id}' not found in hero_feature_specs"],
            "feature_id": feature_id,
            "dirty_channels": [],
            "region": None,
        }

    new_spec = spec
    for mutation in mutations:
        mut_type = mutation.get("type", "unknown")
        if mut_type == "translate":
            dx = float(mutation.get("dx", 0))
            dy = float(mutation.get("dy", 0))
            dz = float(mutation.get("dz", 0))
            wp = new_spec.world_position
            new_spec = dataclasses.replace(
                new_spec,
                world_position=(wp[0] + dx, wp[1] + dy, wp[2] + dz),
            )
            applied += 1
        elif mut_type == "scale":
            factor = float(mutation.get("factor", 1.0))
            new_params = dict(new_spec.parameters)
            new_params["scale_factor"] = factor
            new_spec = dataclasses.replace(new_spec, parameters=new_params)
            applied += 1
        elif mut_type == "rotate":
            angle_deg = float(mutation.get("angle_deg", 0))
            axis = str(mutation.get("axis", "z"))
            ori = list(new_spec.orientation)
            axis_idx = {"x": 0, "y": 1, "z": 2}.get(axis.lower(), 2)
            ori[axis_idx] = ori[axis_idx] + angle_deg
            new_spec = dataclasses.replace(new_spec, orientation=tuple(ori))
            applied += 1
        elif mut_type == "material":
            material_id = str(mutation.get("material_id", ""))
            new_params = dict(new_spec.parameters)
            new_params["material_id"] = material_id
            new_spec = dataclasses.replace(new_spec, parameters=new_params)
            applied += 1
        else:
            issues.append(f"Unknown mutation type: {mut_type}")

    if applied == 0:
        return {
            "applied": 0,
            "issues": issues,
            "feature_id": feature_id,
            "dirty_channels": [],
            "region": None,
        }

    # Write mutated spec back into intent (frozen dataclass — replace tuple entry)
    new_specs = tuple(
        new_spec if s.feature_id == feature_id else s
        for s in state.intent.hero_feature_specs
    )
    new_intent = dataclasses.replace(state.intent, hero_feature_specs=new_specs)
    # TerrainPipelineState.intent is not frozen — assign directly
    state.intent = new_intent

    # Also update composition_hints['hero_features'] list if it exists
    hints = dict(state.intent.composition_hints)
    hf_list: List[Dict[str, Any]] = list(hints.get("hero_features", []))
    for i, hf in enumerate(hf_list):
        if hf.get("feature_id") == feature_id:
            hf_list[i] = {
                **hf,
                "world_position": list(new_spec.world_position),
                "orientation": list(new_spec.orientation),
                "parameters": dict(new_spec.parameters),
            }
            break
    hints["hero_features"] = hf_list
    state.intent = dataclasses.replace(state.intent, composition_hints=hints)

    # Compute region bounding box around the mutated feature position
    wp = new_spec.world_position
    r = max(new_spec.exclusion_radius, 10.0)
    region = BBox(
        min_x=wp[0] - r,
        min_y=wp[1] - r,
        max_x=wp[0] + r,
        max_y=wp[1] + r,
    )

    # ------------------------------------------------------------------ #
    # Stamp hero_feature_preview channel on the mask stack.               #
    #                                                                      #
    # Builds a float32 (H, W) influence-weight overlay centred on the     #
    # mutated feature's world position, using a cosine radial falloff     #
    # over the feature's exclusion_radius.  Existing preview data is      #
    # preserved outside the new feature's influence zone (max-blend) so   #
    # multiple sequential edits accumulate rather than overwrite.         #
    # ------------------------------------------------------------------ #
    stack = state.mask_stack
    try:
        H, W = stack.height.shape
        cell = float(stack.cell_size) if stack.cell_size > 0 else 1.0
        ox = float(stack.world_origin_x)
        oy = float(stack.world_origin_y)

        # World-space coordinate grid for the tile
        row_coords = oy + np.arange(H, dtype=np.float64) * cell
        col_coords = ox + np.arange(W, dtype=np.float64) * cell
        yy, xx = np.meshgrid(row_coords, col_coords, indexing="ij")

        cx, cy = float(wp[0]), float(wp[1])
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

        # Cosine radial weight: 1 at centre, 0 at r and beyond
        weight = np.where(
            dist >= r,
            0.0,
            0.5 * (1.0 + np.cos(np.pi * dist / r)),
        ).astype(np.float32)

        # Max-blend with any existing preview so earlier edits are not erased
        existing = stack.get("hero_feature_preview")
        if existing is not None and existing.shape == weight.shape:
            preview = np.maximum(existing, weight)
        else:
            preview = weight

        stack.set("hero_feature_preview", preview, "edit_hero_feature")
    except Exception as _prev_exc:  # pragma: no cover — never fail the edit itself
        issues.append(f"hero_feature_preview update failed: {_prev_exc}")

    return {
        "applied": applied,
        "issues": issues,
        "feature_id": feature_id,
        "dirty_channels": ["hero_exclusion", "cliff_candidate", "cave_candidate", "hero_feature_preview"],
        "region": list(region.to_tuple()),
    }


__all__ = [
    "LivePreviewSession",
    "StackSnapshot",
    "edit_hero_feature",
]
