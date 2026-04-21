"""Bundle O — central registrar.

Imports the two Bundle O modules (water variants + vegetation depth)
and exposes a single ``register_bundle_o_passes`` entry point following
the Bundle K / L / N registrar pattern.
"""

from __future__ import annotations

from . import terrain_vegetation_depth, terrain_water_variants


BUNDLE_O_MODULES = (
    "terrain_water_variants",
    "terrain_vegetation_depth",
)


def register_bundle_o_passes() -> None:
    """Register the Bundle O passes on the controller.

    Registers:
        - ``water_variants`` (produces water_surface, wetness)
        - ``bathymetry`` (produces bathymetry + water_depth_zone from height + water_surface)
        - ``vegetation_depth`` (populates stack.detail_density dict)
        - ``emergent_grass`` (derives grass_density_map from splatmap; Fix 9.9)

    Pass ordering note: ``bathymetry`` must run after ``water_variants`` so
    that ``water_surface`` is populated before depth zones are classified.
    The TerrainPassController dependency graph enforces this via
    ``requires_channels=("height", "water_surface")``.
    """
    terrain_water_variants.register_water_variants_pass()
    terrain_water_variants.register_bathymetry_pass()
    terrain_vegetation_depth.register_vegetation_depth_pass()
    terrain_vegetation_depth.register_emergent_grass_pass()


__all__ = [
    "BUNDLE_O_MODULES",
    "register_bundle_o_passes",
]
