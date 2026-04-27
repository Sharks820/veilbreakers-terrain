"""Generate VeilBreakers dark-fantasy 3D assets via the AI pipeline.

Usage:
    python scripts/generate_veilbreakers_assets.py \\
        --backend huggingface \\
        --category rocks \\
        --count 10 \\
        --output-dir assets/generated/rocks \\
        --preset veilbreakers_rock

Run with ``--list-batch`` to print the canonical 30-asset VeilBreakers batch
manifest without generating anything.

The script never crashes the pipeline on a single asset failure — it
collects all errors and reports them at the end.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Make in-repo package importable when running directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from veilbreakers_terrain.handlers.asset_generation import (  # noqa: E402
    AssetGenerationBackend,
    AssetGenerationPipeline,
    AssetRequest,
    DARK_FANTASY_PRESETS,
    PipelineConfig,
    apply_preset,
)


# ---------------------------------------------------------------------------
# Canonical batch — 30 VeilBreakers dark-fantasy assets
# ---------------------------------------------------------------------------

VEILBREAKERS_BATCH: list[dict[str, Any]] = [
    # --- Rocks (8) ---
    {"category": "rock", "preset": "veilbreakers_rock", "name": "rock_boulder_mossy_01",
     "prompt": "large mossy boulder, broken at top"},
    {"category": "rock", "preset": "veilbreakers_rock", "name": "rock_boulder_mossy_02",
     "prompt": "rounded mossy boulder, partially buried"},
    {"category": "rock", "preset": "veilbreakers_rock", "name": "rock_obsidian_01",
     "prompt": "jagged obsidian rock cluster, sharp angles"},
    {"category": "rock", "preset": "veilbreakers_rock", "name": "rock_volcanic_01",
     "prompt": "volcanic pumice rock with porous surface"},
    {"category": "rock", "preset": "veilbreakers_rock", "name": "rock_root_boulder_01",
     "prompt": "boulder entangled with twisted roots"},
    {"category": "rock", "preset": "veilbreakers_rock", "name": "rock_frozen_01",
     "prompt": "frost-covered boulder with ice cracks"},
    {"category": "rock", "preset": "veilbreakers_rock", "name": "rock_cliff_chunk_01",
     "prompt": "sheared cliff face chunk, layered strata"},
    {"category": "rock", "preset": "veilbreakers_rock", "name": "rock_river_smooth_01",
     "prompt": "river-smoothed dark stone, wet sheen"},

    # --- Ruins (6) ---
    {"category": "ruin", "preset": "veilbreakers_ruin", "name": "ruin_pillar_broken_01",
     "prompt": "broken stone pillar, top half missing, runic carvings"},
    {"category": "ruin", "preset": "veilbreakers_ruin", "name": "ruin_wall_chunk_01",
     "prompt": "ruined castle wall section, vines crawling up"},
    {"category": "ruin", "preset": "veilbreakers_ruin", "name": "ruin_arch_collapsed_01",
     "prompt": "half-collapsed stone archway, keystone fallen"},
    {"category": "ruin", "preset": "veilbreakers_ruin", "name": "ruin_statue_torso_01",
     "prompt": "ancient statue torso, head and arms broken off"},
    {"category": "ruin", "preset": "veilbreakers_ruin", "name": "ruin_steps_overgrown_01",
     "prompt": "stone steps overgrown with moss, partially submerged"},
    {"category": "ruin", "preset": "veilbreakers_ruin", "name": "ruin_obelisk_cracked_01",
     "prompt": "tall cracked obelisk, ancient runes faintly glowing"},

    # --- Trees (6) ---
    {"category": "tree", "preset": "veilbreakers_tree", "name": "tree_dead_twisted_01",
     "prompt": "dead twisted tree, gnarled bare branches reaching upward"},
    {"category": "tree", "preset": "veilbreakers_tree", "name": "tree_dead_twisted_02",
     "prompt": "dead leaning tree, hollow trunk, exposed roots"},
    {"category": "tree", "preset": "veilbreakers_tree_blighted", "name": "tree_blighted_01",
     "prompt": "blighted tree with oozing dark sap and bone-white bark"},
    {"category": "tree", "preset": "veilbreakers_tree", "name": "tree_charred_stump_01",
     "prompt": "charred tree stump, blackened bark, smouldering cracks"},
    {"category": "tree", "preset": "veilbreakers_tree", "name": "tree_willow_hanging_01",
     "prompt": "weeping willow with long hanging branches and moss"},
    {"category": "tree", "preset": "veilbreakers_tree", "name": "tree_dark_pine_01",
     "prompt": "dark coniferous pine, dense needles, narrow silhouette"},

    # --- Props (10) ---
    {"category": "lantern", "preset": "veilbreakers_lantern", "name": "prop_lantern_iron_01",
     "prompt": "wrought iron lantern with cracked glass panels"},
    {"category": "lantern", "preset": "veilbreakers_lantern", "name": "prop_lantern_hanging_01",
     "prompt": "hanging chain lantern, rust patina, dim glow"},
    {"category": "arch", "preset": "veilbreakers_arch", "name": "prop_arch_runic_01",
     "prompt": "small stone archway with runic inscriptions"},
    {"category": "gravestone", "preset": "veilbreakers_gravestone", "name": "prop_gravestone_01",
     "prompt": "leaning gravestone, eroded letters, mossy base"},
    {"category": "gravestone", "preset": "veilbreakers_gravestone", "name": "prop_gravestone_02",
     "prompt": "tall cross-shaped gravestone, broken top"},
    {"category": "prop", "preset": "veilbreakers_prop", "name": "prop_chest_iron_01",
     "prompt": "iron-bound wooden chest, padlocked, rust streaks"},
    {"category": "prop", "preset": "veilbreakers_prop", "name": "prop_barrel_rotting_01",
     "prompt": "rotting wooden barrel, iron bands, leaking dark fluid"},
    {"category": "prop", "preset": "veilbreakers_prop", "name": "prop_wagon_broken_01",
     "prompt": "broken wagon wheel and axle, half-buried"},
    {"category": "debris", "preset": "veilbreakers_debris", "name": "prop_debris_pile_01",
     "prompt": "pile of stone rubble and broken roof tiles"},
    {"category": "debris", "preset": "veilbreakers_debris", "name": "prop_debris_pile_02",
     "prompt": "scattered bones and fabric scraps among rubble"},
]


def _filter_batch(category: str | None) -> list[dict[str, Any]]:
    if not category or category == "all":
        return list(VEILBREAKERS_BATCH)
    if category.endswith("s"):
        # Allow plurals: "rocks" -> "rock", "ruins" -> "ruin"
        singular = category[:-1]
    else:
        singular = category
    return [item for item in VEILBREAKERS_BATCH if item["category"] in (category, singular)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--backend",
        choices=[b.value for b in AssetGenerationBackend],
        default=AssetGenerationBackend.HUGGINGFACE.value,
        help="Which cloud backend to use",
    )
    parser.add_argument("--category", default="all", help="Asset category filter (e.g. 'rock', 'tree', 'all')")
    parser.add_argument("--count", type=int, default=0, help="Cap number of assets (0 = all matching)")
    parser.add_argument("--output-dir", default="assets/generated", type=Path)
    parser.add_argument("--preset", default=None,
                        help=f"Override preset for all items. One of: {', '.join(DARK_FANTASY_PRESETS)}")
    parser.add_argument("--target-poly", type=int, default=8000, help="Target poly count budget")
    parser.add_argument("--list-batch", action="store_true", help="Print the canonical batch and exit")
    parser.add_argument("--dry-run", action="store_true", help="Report planned work without calling the backend")
    parser.add_argument("--continue-on-error", action="store_true", default=True)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

    items = _filter_batch(args.category)
    if args.count > 0:
        items = items[: args.count]

    if args.list_batch:
        print(json.dumps(items, indent=2))
        return 0

    if not items:
        print(f"No assets matched category {args.category!r}", file=sys.stderr)
        return 2

    if args.dry_run:
        for item in items:
            preset = args.preset or item["preset"]
            full = apply_preset(item["prompt"], preset)
            print(f"[dry-run] {item['name']} ({item['category']}) :: {full}")
        return 0

    pipeline = AssetGenerationPipeline(PipelineConfig())
    requests: list[AssetRequest] = []
    for item in items:
        preset_key = args.preset or item["preset"]
        full_prompt = apply_preset(item["prompt"], preset_key)
        requests.append(
            AssetRequest(
                prompt=full_prompt,
                asset_category=item["category"],
                output_name=item["name"],
                target_poly_count=args.target_poly,
                metadata={"batch_preset": preset_key, "raw_prompt": item["prompt"]},
            )
        )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    backend = AssetGenerationBackend(args.backend)
    paths = pipeline.batch_generate(
        requests, output_dir=out_dir, backend=backend, continue_on_error=args.continue_on_error
    )
    print(f"Generated {len(paths)}/{len(requests)} assets into {out_dir}")
    return 0 if paths else 1


if __name__ == "__main__":
    raise SystemExit(main())
