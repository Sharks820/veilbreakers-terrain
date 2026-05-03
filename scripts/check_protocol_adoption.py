"""Fail when critical production terrain passes lack controller protocol policy."""

from __future__ import annotations

import sys
from pathlib import Path
import inspect

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CRITICAL_PROTOCOL_PASSES = {
    "scatter_intelligent",
    "karst",
    "navmesh",
    "gameplay_zones",
    "wildlife_zones",
    "framing",
    "integrate_deltas",
    "prepare_terrain_normals",
    "prepare_heightmap_raw_u16",
    "prepare_unity_auxiliary_channels",
}


def main() -> int:
    from veilbreakers_terrain.handlers import environment
    from veilbreakers_terrain.handlers.terrain_master_registrar import (
        register_all_terrain_passes,
    )
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController

    TerrainPassController.clear_registry()
    register_all_terrain_passes(strict=False)
    missing = sorted(CRITICAL_PROTOCOL_PASSES - set(TerrainPassController.PASS_REGISTRY))
    unenforced = sorted(
        name
        for name in CRITICAL_PROTOCOL_PASSES & set(TerrainPassController.PASS_REGISTRY)
        if not getattr(TerrainPassController.PASS_REGISTRY[name], "protocol_enforced", False)
    )
    missing_rule5 = sorted(
        name
        for name in CRITICAL_PROTOCOL_PASSES & set(TerrainPassController.PASS_REGISTRY)
        if not getattr(TerrainPassController.PASS_REGISTRY[name], "protocol_require_rule_5", False)
    )
    source = inspect.getsource(environment)
    handler_gaps: list[str] = []
    if "_enforce_generate_terrain_protocol(" not in source:
        handler_gaps.append("handle_generate_terrain lacks protocol preflight")
    if 'params.get("use_controller", True)' not in source:
        handler_gaps.append("handle_generate_terrain does not default to controller path")
    if 'params.get("out_of_view_ok", state.viewport_vantage is None)' in source:
        handler_gaps.append("Rule 2 still self-bypasses when viewport_vantage is None")
    if 'params.get("bulk_edit", True)' in source:
        handler_gaps.append("Rule 5 still defaults bulk_edit=True")
    if 'execution_params.setdefault("enforce_protocol", True)' not in source:
        handler_gaps.append("env_run_terrain_pass does not default protocol enforcement on")

    if missing or unenforced or missing_rule5 or handler_gaps:
        print("Protocol adoption check failed.")
        if missing:
            print(f"missing critical passes: {missing}")
        if unenforced:
            print(f"protocol_enforced=false: {unenforced}")
        if missing_rule5:
            print(f"protocol_require_rule_5=false: {missing_rule5}")
        if handler_gaps:
            print(f"handler protocol gaps: {handler_gaps}")
        return 1
    print(
        "Protocol adoption check passed: "
        f"{len(CRITICAL_PROTOCOL_PASSES)} critical passes enforce controller protocol policy "
        "and public generate handlers fail closed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
