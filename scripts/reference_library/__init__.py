"""VeilBreakers reference library — visual & photometric calibration data.

Each scene type (e.g. ``ashen_caldera``, ``mountain_pass``, ``mire_basin``)
ships a JSON descriptor under ``scripts/reference_library/<scene_id>.json``.
Build agents call :func:`load_scene_reference` at the top of the build script
to pull AAA-grade calibrated values for material albedos, lava luminance,
volcanic haze color, sun irradiance under aerosol, and so on — instead of
guessing.

Why this exists
---------------
Two recurring AAA-bar failures in this repo:

1.  Artists hard-coded basalt albedo at ``0.018`` (charcoal black) when real
    basalt measures ``0.06`` (USGS spectral library). Crushed blacks under
    volumetric haze. See ``build_aaa_ashen_caldera_v2.py`` v1 → v2 fix.
2.  Sun strength left at clear-sky ``20 W`` under heavy ash aerosol — gave
    bright daylight when scene should be dim brown twilight.

The reference library makes those values data, not magic numbers.

Schema version
--------------
``schema_version: 1.0.0``. Build scripts MUST validate the major version.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

REFERENCE_LIBRARY_DIR = Path(__file__).resolve().parent
SCHEMA_MAJOR = 1

__all__ = [
    "REFERENCE_LIBRARY_DIR",
    "SCHEMA_MAJOR",
    "SceneReference",
    "ReferenceSchemaError",
    "load_scene_reference",
    "list_scene_ids",
    "fetch_reference_samples",
    "get_material_albedo",
    "get_lava_emission",
    "get_haze_color",
    "get_sun_irradiance",
]


class ReferenceSchemaError(ValueError):
    """Raised when a scene reference JSON fails schema validation."""


@dataclass(frozen=True)
class SceneReference:
    """Validated, frozen view over a scene reference JSON.

    Always access calibration values through this wrapper rather than
    indexing the raw dict — it enforces schema invariants (presence of
    required keys, sane numeric ranges) at load time.
    """

    scene_id: str
    raw: Dict[str, Any]

    @property
    def materials(self) -> Dict[str, Any]:
        return self.raw["photometric_calibration"]["materials"]

    @property
    def lighting(self) -> Dict[str, Any]:
        return self.raw["photometric_calibration"]["lighting"]

    @property
    def atmosphere(self) -> Dict[str, Any]:
        return self.raw["photometric_calibration"]["atmosphere"]

    @property
    def post_processing(self) -> Dict[str, Any]:
        return self.raw["photometric_calibration"]["post_processing"]

    @property
    def visual_benchmarks(self) -> Dict[str, Any]:
        return self.raw["visual_benchmarks"]

    def material(self, key: str) -> Dict[str, Any]:
        try:
            return self.materials[key]
        except KeyError as exc:
            raise ReferenceSchemaError(
                f"Scene {self.scene_id!r} has no material {key!r}. "
                f"Available: {sorted(self.materials)}"
            ) from exc

    def albedo(self, key: str) -> Tuple[float, float, float]:
        mat = self.material(key)
        rgb = mat.get("linear_albedo")
        if rgb is None or len(rgb) != 3:
            raise ReferenceSchemaError(
                f"Material {key!r} in scene {self.scene_id!r} is missing "
                f"linear_albedo:[r,g,b]"
            )
        return tuple(float(c) for c in rgb)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

_REQUIRED_TOP_KEYS = (
    "schema_version",
    "scene_id",
    "photometric_calibration",
    "visual_benchmarks",
)
_REQUIRED_PHOTOMETRIC_KEYS = ("materials", "lighting", "atmosphere", "post_processing")


def _validate_schema(data: Dict[str, Any], path: Path) -> None:
    for key in _REQUIRED_TOP_KEYS:
        if key not in data:
            raise ReferenceSchemaError(f"{path}: missing required key {key!r}")

    version = str(data["schema_version"])
    major = int(version.split(".", 1)[0])
    if major != SCHEMA_MAJOR:
        raise ReferenceSchemaError(
            f"{path}: schema_version {version!r} incompatible with loader "
            f"major {SCHEMA_MAJOR}"
        )

    photometric = data["photometric_calibration"]
    for key in _REQUIRED_PHOTOMETRIC_KEYS:
        if key not in photometric:
            raise ReferenceSchemaError(
                f"{path}: photometric_calibration missing {key!r}"
            )

    # Sanity-check albedos (linear sRGB must be in [0, 1])
    for mat_key, mat in photometric["materials"].items():
        rgb = mat.get("linear_albedo")
        if rgb is not None:
            if any((c < 0.0 or c > 1.0) for c in rgb):
                raise ReferenceSchemaError(
                    f"{path}: material {mat_key} linear_albedo {rgb} out of "
                    f"[0,1]"
                )


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_scene_reference(scene_id: str) -> SceneReference:
    """Load and validate the reference JSON for ``scene_id``.

    Build scripts call this once at startup, then read calibrated values
    instead of hard-coding magic numbers.

    Example::

        ref = load_scene_reference("ashen_caldera")
        basalt = ref.albedo("fresh_basalt_rock")           # (0.063, 0.060, 0.057)
        sun_W = ref.lighting["sun"]["blender_strength_W_m2"]  # 4.5
        haze = ref.atmosphere["haze_color_linear_rgb"]
    """
    path = REFERENCE_LIBRARY_DIR / f"{scene_id}.json"
    if not path.exists():
        available = list_scene_ids()
        raise FileNotFoundError(
            f"No reference library entry for scene_id={scene_id!r}. "
            f"Available: {available}. Looked at: {path}"
        )

    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    _validate_schema(data, path)

    if data["scene_id"] != scene_id:
        raise ReferenceSchemaError(
            f"{path}: scene_id field {data['scene_id']!r} does not match "
            f"filename-derived id {scene_id!r}"
        )

    logger.info(
        "Loaded scene reference %s (schema %s, %d materials)",
        scene_id,
        data["schema_version"],
        len(data["photometric_calibration"]["materials"]),
    )
    return SceneReference(scene_id=scene_id, raw=data)


def list_scene_ids() -> List[str]:
    """List every scene reference available on disk."""
    return sorted(p.stem for p in REFERENCE_LIBRARY_DIR.glob("*.json"))


# ---------------------------------------------------------------------------
# Convenience accessors used by build scripts
# ---------------------------------------------------------------------------

def get_material_albedo(
    ref: SceneReference, key: str
) -> Tuple[float, float, float]:
    """Return ``(r, g, b)`` linear-sRGB albedo for a calibrated material."""
    return ref.albedo(key)


def get_lava_emission(ref: SceneReference) -> Dict[str, Any]:
    """Return the active-lava emission dict (color, luminance, blackbody K)."""
    return ref.material("active_lava_surface")


def get_haze_color(ref: SceneReference) -> Tuple[float, float, float]:
    """Return the volumetric haze tint in linear sRGB."""
    rgb = ref.atmosphere["haze_color_linear_rgb"]
    return tuple(float(c) for c in rgb)  # type: ignore[return-value]


def get_sun_irradiance(ref: SceneReference, *, with_aerosol: bool = True) -> float:
    """Return ground-level sun irradiance in W/m^2.

    Set ``with_aerosol=False`` to get the clear-sky baseline (mostly useful
    when authoring or sanity-checking the JSON itself).
    """
    sun = ref.lighting["sun"]
    if with_aerosol:
        return float(sun["irradiance_at_ground_volcanic_aerosol_W_m2"])
    return float(sun["irradiance_at_ground_clear_W_m2"])


# ---------------------------------------------------------------------------
# Offline reference-image scraping (NOT called during build)
# ---------------------------------------------------------------------------

def fetch_reference_samples(
    scene_id: str,
    query: Optional[str] = None,
    *,
    max_results: int = 12,
    out_dir: Optional[Path] = None,
    backend: str = "brave",
) -> List[Dict[str, Any]]:
    """Scrape reference imagery & metadata to refresh the library offline.

    This is a maintainer-time function. It is never called from a build
    script — we want builds to be deterministic and offline. Run it from
    the dev shell when you want to refresh the JSON descriptors with new
    photographic references.

    Parameters
    ----------
    scene_id:
        Must match a JSON filename in this directory (creates one if not
        found).
    query:
        Override the default query. If ``None``, uses
        ``reference_image_queries.primary[0]`` from the existing JSON,
        falling back to ``f"{scene_id} terrain UE5 reference"``.
    max_results:
        Cap the number of returned samples.
    out_dir:
        If provided, downloaded images are saved here. Default:
        ``output/reference_samples/<scene_id>/``.
    backend:
        ``"brave"`` (default), ``"exa"``, or ``"tavily"``. Selects the MCP
        server used. ``brave`` is the safest free quota; ``exa`` returns
        the highest-quality semantic matches; ``tavily`` is best for
        long-form articles with embedded measurements.

    Returns
    -------
    List of result dicts with keys:
    ``{"title", "url", "image_url", "snippet", "saved_path", "score"}``.

    The MCP calls themselves live in the Claude / Codex agent layer — this
    function emits a *manifest* describing what to fetch, and (when run
    inside an agent context that has MCP access) the agent dispatches the
    calls. Out-of-band callers receive a ``NotImplementedError`` reminding
    them to invoke this through an MCP-enabled agent.
    """
    # Resolve query
    if query is None:
        try:
            ref = load_scene_reference(scene_id)
            queries = ref.raw.get("reference_image_queries", {}).get("primary", [])
            query = queries[0] if queries else f"{scene_id} terrain UE5 reference"
        except FileNotFoundError:
            query = f"{scene_id} terrain UE5 reference"

    # Resolve output dir
    if out_dir is None:
        out_dir = (
            REFERENCE_LIBRARY_DIR.parent.parent
            / "output"
            / "reference_samples"
            / scene_id
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "scene_id": scene_id,
        "query": query,
        "max_results": max_results,
        "backend": backend,
        "out_dir": str(out_dir),
        "mcp_calls": _build_mcp_call_plan(query, backend, max_results),
    }
    manifest_path = out_dir / "fetch_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    logger.info(
        "Wrote MCP fetch manifest for %s -> %s. Run via the agent harness.",
        scene_id,
        manifest_path,
    )

    # If we're inside a runtime that exposes MCP tools (Claude Code agent),
    # the tool runner can pick up the manifest. From plain Python we cannot
    # invoke the MCP server directly — surface that clearly.
    if not _mcp_runtime_available():
        raise NotImplementedError(
            f"fetch_reference_samples wrote a manifest at {manifest_path}. "
            "Execute it via the Claude/Codex MCP agent harness — this "
            "function cannot invoke MCP servers from a plain Python "
            "process."
        )

    # Inside an agent runtime, the agent harness consumes the manifest.
    return _execute_mcp_call_plan(manifest, out_dir)


def _build_mcp_call_plan(
    query: str, backend: str, max_results: int
) -> List[Dict[str, Any]]:
    """Construct the MCP call list for the agent harness to execute."""
    if backend == "brave":
        return [
            {
                "tool": "mcp__brave-search__brave_image_search",
                "args": {"q": query, "count": max_results},
            },
            {
                "tool": "mcp__brave-search__brave_web_search",
                "args": {"q": query + " photometric albedo measurement", "count": max_results},
            },
        ]
    if backend == "exa":
        return [
            {
                "tool": "mcp__exa__web_search_exa",
                "args": {"query": query, "num_results": max_results},
            }
        ]
    if backend == "tavily":
        return [
            {
                "tool": "mcp__tavily__tavily_search",
                "args": {"query": query, "max_results": max_results, "search_depth": "advanced"},
            }
        ]
    raise ValueError(f"Unknown backend {backend!r}")


def _mcp_runtime_available() -> bool:
    """Best-effort detection that we're running inside an MCP-enabled agent."""
    import os
    return bool(os.environ.get("CLAUDE_MCP_RUNTIME") or os.environ.get("CODEX_MCP_RUNTIME"))


def _execute_mcp_call_plan(
    manifest: Dict[str, Any], out_dir: Path
) -> List[Dict[str, Any]]:
    """Stub — actual execution happens in the agent harness, which patches
    this function at runtime to dispatch MCP calls and write results back.
    """
    raise NotImplementedError(
        "MCP execution must be patched in by the agent harness. "
        f"Manifest is at {out_dir / 'fetch_manifest.json'}."
    )
