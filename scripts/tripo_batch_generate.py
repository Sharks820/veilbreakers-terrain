"""Tripo batch generator for VeilBreakers foliage (Phase I+).

Parses ``docs/TRIPO_FOLIAGE_MANIFEST_2026_04_24.md``, submits the 26 prompts
(x4 variations = 104 tasks) to the Tripo text-to-model API, polls until
completion, downloads each GLB to
``output/tripo_generation/downloads/<display_category>/<prompt_id>_v<n>.glb``,
and finally drives ``scripts/batch_ingest_tripo_downloads.py`` to decimate,
LOD, and register everything into ``assets/foliage/catalog.json``.

Key properties:

  * Idempotent — every task is journaled in
    ``output/tripo_generation/ledger.json`` and resumed on rerun.
  * Rate-limited — 1.0s between submits, max 20 in-flight tasks by default.
  * Retry-safe — failed tasks retry up to 2x before being surfaced.
  * Cost-capped — refuses to run if estimated cost exceeds the safety cap
    (default $100) or if Tripo reports insufficient credits.
  * Auditable — every HTTP call is logged to
    ``output/tripo_generation/api.log``.

CLI
---
Dry-run (no network, just expand manifest into ledger & print plan):

    python scripts/tripo_batch_generate.py --plan-only

Real run (requires ``TRIPO_API_KEY``):

    python scripts/tripo_batch_generate.py

Single wave of 8 prompts (32 tasks), then exit:

    python scripts/tripo_batch_generate.py --wave-size 8 --single-wave

After the whole run, ingest:

    python scripts/batch_ingest_tripo_downloads.py \
        --downloads output/tripo_generation/downloads \
        --assets assets/foliage
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRIPO_BASE_URL = "https://api.tripo3d.ai/v2/openapi"
DEFAULT_MODEL_VERSION = "v2.5-20250123"

# ``ingest_tripo_asset.CATEGORY_DISPLAY`` — duplicated here to avoid importing
# the Blender-using script into the driver (keeps tests hermetic).
CATEGORY_TO_DISPLAY = {
    "grass": "grass",
    "pebble": "rock_small",
    "gravel": "rock_small",
    "hero_boulder": "rock_boulder",
    "boulder": "rock_boulder",
    "moss": "moss",
    "moss_drape": "moss",
    "vine_hanging": "vine",
    "vine": "vine",
    "log": "log",
    "stump": "log",
    "oak": "tree",
    "birch": "tree",
    "pine": "tree",
    "dead_tree": "tree",
    "tree": "tree",
    "bramble": "bush",
    "fern": "bush",
    "heath": "bush",
    "bush": "bush",
    "reed": "water_foliage",
    "lily": "water_foliage",
    "fence_wood": "structure",
    "fence_stone": "structure",
    "fence": "structure",
    "gate": "structure",
    "sign_wooden": "structure",
    "sign_stone_waypoint": "structure",
    "signpost": "structure",
    "walkway_plank": "terrain_tile",
    "walkway": "terrain_tile",
    "cobble": "terrain_tile",
    "path": "terrain_tile",
    "flower": "accent",
    "mushroom": "accent",
}

# Ordered longest-first so ``moss_drape`` beats ``moss``, etc.
_CATEGORY_KEYWORDS = sorted(CATEGORY_TO_DISPLAY.keys(), key=len, reverse=True)

# Explicit prompt-id -> asset_category overrides for ambiguous manifest ids
# (substring matches in ``_detect_category`` would mis-classify these).
_PROMPT_ID_CATEGORY_OVERRIDES: dict[str, str] = {
    "tree_oak_ancient": "oak",
    "tree_birch_pale": "birch",
    "tree_pine_black": "pine",
    "tree_dead_claw": "dead_tree",
    "log_fallen_mossy": "log",
    "moss_stalactite_drape": "moss_drape",
    "bush_bramble_thorn": "bramble",
    "bush_fern_shadowleaf": "fern",
    "bush_heath_bloom": "heath",
    "walkway_cobbled": "walkway",
    "pebbles_streambed": "pebble",
    "gravel_ruin_debris": "gravel",
    # Phase I++ additions (7 new prompts).
    "hero_boulder_landmark": "hero_boulder",
    "vine_hanging_cliff": "vine_hanging",
    "fence_wood_modular": "fence_wood",
    "fence_stone_wall": "fence_stone",
    "sign_wooden_crossroads": "sign_wooden",
    "sign_stone_waypoint": "sign_stone_waypoint",
    "walkway_plank_swamp": "walkway_plank",
}

# Default safety rails.
DEFAULT_COST_PER_TASK_USD = 0.30
DEFAULT_HARD_COST_CAP_USD = 100.0
DEFAULT_HARD_TASK_CAP = 132
DEFAULT_WAVE_SIZE = 8  # prompts per wave (×4 variations = 32 tasks)
DEFAULT_MAX_IN_FLIGHT = 20
DEFAULT_POLL_INTERVAL_S = 30.0
DEFAULT_SUBMIT_SPACING_S = 1.0
DEFAULT_MAX_RETRIES = 2

# Variation style hints — swap into the prompt for diversity when the API
# returns one model per request. Category -> list[4] of short adjectives.
VARIATION_STYLES: dict[str, list[str]] = {
    "grass": ["lush and upright", "wind-pushed and leaning", "sparse with flower stalks", "compact dense mat"],
    "pebble": ["tight cluster", "spread scatter", "mossy wet", "larger boulderlet mix"],
    "gravel": ["rubble heap", "scattered debris", "mossy shards", "ashy large fragments"],
    "boulder": ["mostly mossed", "half-buried tilted", "split with fern", "clean stratified stone"],
    "moss": ["thick dome", "spread flat", "with tiny flowers", "half-dry crispy edge"],
    "moss_drape": ["dense curtain", "sparse strands", "long trailing", "twisted knot"],
    "vine": ["thick wrap", "trailing free", "flowering", "dried brown curl"],
    "log": ["intact mossy", "split open hollow", "heavy fungus cluster", "half-sunken in mud"],
    "stump": ["tall jagged", "short flat-top", "mushroom ringed", "hollow-centred with roots"],
    "oak": ["dense canopy", "half-leafless", "split trunk", "leaning overgrown"],
    "birch": ["full canopy", "thin sparse", "storm-broken top", "grouped twin trunks"],
    "pine": ["dense conical", "bare-bottomed", "storm-bent", "dead-top with crow perch"],
    "dead_tree": ["upright claw", "leaning fallen", "split lightning-struck", "charred stump"],
    "tree": ["dense canopy", "sparse", "split", "leaning"],
    "bramble": ["dense spherical", "spreading wide", "berry laden", "broken half-dead"],
    "fern": ["dense symmetric", "asymmetric leaning", "young curled", "old and browning"],
    "heath": ["full bloom", "sparse bloom", "post-bloom brown", "wind-flattened"],
    "bush": ["dense", "open", "blooming", "sparse"],
    "reed": ["dense reed bed", "bent windblown", "with seed heads", "broken half-dead"],
    "lily": ["single bloom", "many pads no flower", "closed bud", "wilting with algae"],
    "fence": ["intact line", "broken missing plank", "leaning collapsed", "gate with rusted hinges"],
    "fence_wood": ["intact", "broken picket gap", "moss-heavy overgrown", "charred from fire"],
    "fence_stone": ["intact", "partial collapse", "ivy-covered", "half-buried in earth"],
    "gate": ["intact", "half-broken", "rusted", "overgrown"],
    "signpost": ["upright intact", "leaning cracked", "double arrow crossroads", "broken stub"],
    "sign_wooden": ["two-arm", "three-arm", "one-arm broken off", "burnt blackened"],
    "sign_stone_waypoint": ["fresh carving", "heavily eroded", "toppled tilted", "glowing rune inlay faint teal"],
    "hero_boulder": ["mossy forest boulder", "shattered cliff-fall boulder", "runic-carved ruin marker", "waterfall-polished river giant"],
    "vine_hanging": ["dense leaf curtain", "sparse wispy strands", "with small pale flowers", "dead wilted with rot patches"],
    "walkway_plank": ["straight", "with broken plank gap", "ivy crawling", "half-submerged in bog"],
    "walkway": ["dense cobble", "half-overgrown", "broken with cracks", "flooded puddles"],
    "cobble": ["dense cobble", "half-overgrown", "broken", "flooded"],
    "path": ["dense cobble", "half-overgrown", "broken", "flooded"],
    "flower": ["tight cluster", "single stem", "closed bud", "wilting drooping"],
    "mushroom": ["small cluster", "tall lone", "shelf-on-log", "broken toppled"],
}


logger = logging.getLogger("tripo_batch")


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


@dataclass
class PromptSpec:
    """One manifest row; expands into 4 Tripo tasks (variations)."""

    id: str
    section_id: str  # e.g. "A1"
    category_letter: str  # e.g. "A"
    category_name: str  # e.g. "Grass"
    asset_category: str  # e.g. "grass" (maps into CATEGORY_TO_DISPLAY)
    display_category: str  # e.g. "grass"
    base_prompt: str
    poly_budget_min: int
    poly_budget_max: int
    variations: list[str]  # length 4 — styled prompts for each variation
    species_binding: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_category(label: str) -> str:
    """Pick the best asset_category keyword from a prompt id / name.

    Applies explicit overrides first to disambiguate prompts whose id contains
    more than one category keyword (e.g. ``tree_oak_ancient`` -> ``oak``).
    """
    norm = label.lower().replace("-", "_")
    if norm in _PROMPT_ID_CATEGORY_OVERRIDES:
        return _PROMPT_ID_CATEGORY_OVERRIDES[norm]
    for kw in _CATEGORY_KEYWORDS:
        if kw in norm:
            return kw
    return "unknown"


def _parse_poly_budget(text: str) -> tuple[int, int]:
    m = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*tris", text.lower())
    if not m:
        return (1000, 2000)
    return int(m.group(1)), int(m.group(2))


def _make_variation_prompts(base: str, category: str) -> list[str]:
    styles = VARIATION_STYLES.get(category, ["variation A", "variation B", "variation C", "variation D"])
    out: list[str] = []
    for i, style in enumerate(styles[:4]):
        # Add the style hint at the end so Tripo's word-order sensitivity keeps
        # the core description intact (the manifest warns against reordering).
        out.append(f"{base.strip()} — variation {i + 1}: {style}.")
    while len(out) < 4:
        out.append(f"{base.strip()} — variation {len(out) + 1}.")
    return out


def parse_manifest(markdown_text: str) -> list[PromptSpec]:
    """Parse the TRIPO_FOLIAGE_MANIFEST markdown into a list of PromptSpec.

    The manifest layout is stable: each prompt is an ``### <letter><num>.
    \\`<prompt_id>\\``` header followed by a blockquote, then an
    ``Expected variations:`` line. Poly budget comes from the section-level
    ``Poly budget:`` line.
    """
    specs: list[PromptSpec] = []

    # Split into top-level sections like "## A. Grass (…)".
    section_re = re.compile(r"^## ([A-Z])\. ([^\n(]+).*?$", re.MULTILINE)
    sections = list(section_re.finditer(markdown_text))

    for i, m in enumerate(sections):
        letter = m.group(1).strip()
        name = m.group(2).strip()
        start = m.end()
        end = sections[i + 1].start() if i + 1 < len(sections) else len(markdown_text)
        body = markdown_text[start:end]

        poly_min, poly_max = _parse_poly_budget(body)

        # Sub-prompts ``### <letter><n>. \`<id>\` — <descr>``.
        sub_re = re.compile(
            r"^###\s+([A-Z]\d+)\.\s+`([^`]+)`(?:\s*[—-]\s*([^\n]+))?\n([\s\S]*?)(?=^###|^##|\Z)",
            re.MULTILINE,
        )
        for sm in sub_re.finditer(body):
            section_id = sm.group(1).strip()
            prompt_id = sm.group(2).strip()
            block = sm.group(4)

            # Extract the blockquote base prompt.
            quote_lines = []
            in_quote = False
            for line in block.splitlines():
                stripped = line.rstrip()
                if stripped.startswith(">"):
                    in_quote = True
                    quote_lines.append(stripped.lstrip("> ").rstrip())
                elif in_quote and not stripped.startswith(">"):
                    # First blank or non-quote line ends the quote.
                    if stripped == "":
                        break
                    # some manifests allow continuation lines — keep going.
                    quote_lines.append(stripped)
            base_prompt = " ".join(p for p in quote_lines if p).strip()
            if not base_prompt:
                continue

            # species binding (optional).
            species: list[str] = []
            species_m = re.search(
                r"Scatter species binding:\s*([\s\S]+?)(?:\n\n|\Z)",
                block,
            )
            if species_m:
                raw = species_m.group(1)
                for tok in re.findall(r"`([^`]+)`", raw):
                    species.append(tok.strip())

            category = _detect_category(prompt_id)
            display = CATEGORY_TO_DISPLAY.get(category, category)
            variations = _make_variation_prompts(base_prompt, category)

            specs.append(
                PromptSpec(
                    id=prompt_id,
                    section_id=section_id,
                    category_letter=letter,
                    category_name=name,
                    asset_category=category,
                    display_category=display,
                    base_prompt=base_prompt,
                    poly_budget_min=poly_min,
                    poly_budget_max=poly_max,
                    variations=variations,
                    species_binding=species,
                )
            )
    return specs


def write_structured_manifest(specs: Sequence[PromptSpec], out_path: Path) -> None:
    payload = {
        "version": 1,
        "model_version": DEFAULT_MODEL_VERSION,
        "total_prompts": len(specs),
        "total_tasks": sum(len(s.variations) for s in specs),
        "prompts": [s.to_dict() for s in specs],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    tmp.replace(out_path)


# ---------------------------------------------------------------------------
# Tripo HTTP client (seam for tests)
# ---------------------------------------------------------------------------


class TripoError(RuntimeError):
    """Non-transient Tripo API error."""


class TripoInsufficientCredit(TripoError):
    pass


HttpFn = Callable[[str, str, dict[str, Any] | None, dict[str, str]], tuple[int, dict[str, Any]]]


def _default_http(method: str, url: str, body: dict[str, Any] | None, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            code = resp.getcode()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        code = e.code
    except urllib.error.URLError as e:
        raise TripoError(f"network error contacting {url}: {e}") from e
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"_raw": raw}
    return code, payload


class TripoClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = TRIPO_BASE_URL,
        http_fn: HttpFn | None = None,
        api_log_path: Path | None = None,
    ) -> None:
        if not api_key:
            raise TripoError("TRIPO_API_KEY is empty")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http = http_fn or _default_http
        self.api_log_path = api_log_path

    # ------------------------------------------------------------------
    # Low level
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "veilbreakers-tripo-batch/1.0",
        }

    def _log_call(self, method: str, url: str, code: int, body: dict[str, Any] | None, resp: dict[str, Any]) -> None:
        if self.api_log_path is None:
            return
        self.api_log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "method": method,
            "url": url,
            "code": code,
            "req": body,
            # Truncate response to keep log digestible.
            "resp": _truncate(resp, 2000),
        }
        with self.api_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        code, payload = self._http(method, url, body, self._headers())
        self._log_call(method, url, code, body, payload)
        if code == 403 and payload.get("code") == 2010:
            raise TripoInsufficientCredit(payload.get("message") or "insufficient credit")
        if code >= 400:
            raise TripoError(f"{method} {path} -> {code}: {payload}")
        if isinstance(payload, dict) and payload.get("code") not in (0, None):
            raise TripoError(f"{method} {path} -> api code {payload.get('code')}: {payload}")
        return payload

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def get_balance(self) -> dict[str, Any]:
        payload = self._request("GET", "/user/balance")
        data = payload.get("data") if isinstance(payload, dict) else None
        return data or {}

    def create_text_to_model(
        self,
        prompt: str,
        *,
        model_version: str = DEFAULT_MODEL_VERSION,
        negative_prompt: str | None = None,
        seed: int | None = None,
        face_limit: int | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "type": "text_to_model",
            "prompt": prompt,
            "model_version": model_version,
        }
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        if seed is not None:
            body["seed"] = int(seed)
        if face_limit is not None:
            body["face_limit"] = int(face_limit)
        payload = self._request("POST", "/task", body)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or "task_id" not in data:
            raise TripoError(f"create task returned no task_id: {payload}")
        return str(data["task_id"])

    def get_task(self, task_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/task/{urllib.parse.quote(task_id)}")
        data = payload.get("data") if isinstance(payload, dict) else None
        return data or {}


class TripoStudioBackend:
    """Sync facade around the async :class:`TripoStudioClient` port.

    Exposes the same ``create_text_to_model``/``get_task``/``get_balance``
    surface as :class:`TripoClient` so :class:`TripoBatchDriver` stays agnostic
    to which backend ships the requests.

    Studio differences we normalise:
      * One POST ``/task`` returns *four* ``task_ids`` (variants) instead of
        one. We keep a per-prompt variant queue so subsequent ``create_…``
        calls return the remaining variants without submitting again.
      * Status strings are identical-ish (``queued``/``running``/``success``/
        ``failed``/``banned``/``cancelled``) but the successful payload exposes
        ``pbr_model`` and ``model`` at the top level, not under ``output``.
      * Balance lives under ``/user/profile/payment`` with shape
        ``{free_balance, purchased_balance, frozen, total_balance}``. We
        surface ``total_balance`` (free + purchased) as ``balance`` for the
        driver's pre-flight check.
    """

    def __init__(
        self,
        *,
        session_cookie: str = "",
        session_token: str = "",
        api_log_path: Path | None = None,
    ) -> None:
        # Deferred import so ``--plan-only`` and API-mode runs don't require
        # httpx (keeps CI lean).
        try:
            from veilbreakers_terrain.handlers.tripo_studio_client import (
                TripoStudioClient,
            )
        except ImportError as exc:  # pragma: no cover - import-time failure
            raise TripoError(
                f"Cannot import TripoStudioClient: {exc}. "
                "Install httpx: pip install httpx"
            ) from exc
        if not session_cookie and not session_token:
            raise TripoError(
                "Studio backend requires TRIPO_SESSION_COOKIE or "
                "TRIPO_SESSION_TOKEN to be set."
            )
        self._client = TripoStudioClient(
            session_cookie=session_cookie,
            session_token=session_token,
        )
        self.api_key = "studio"
        self.api_log_path = api_log_path
        # prompt_text -> list[task_id] we still owe the driver.
        self._pending_variants: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, coro):  # pragma: no cover - passthrough for asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # If we're already inside a loop (e.g. test harness), create a new
        # loop in a worker thread.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, coro).result()

    def _log(self, action: str, payload: dict[str, Any]) -> None:
        if self.api_log_path is None:
            return
        self.api_log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "backend": "studio",
            "action": action,
            "payload": _truncate(payload, 2000),
        }
        with self.api_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    # ------------------------------------------------------------------
    # TripoClient-compatible surface
    # ------------------------------------------------------------------

    def get_balance(self) -> dict[str, Any]:
        """Return ``{"balance": <combined>, ...raw_studio_fields}``."""
        try:
            raw = self._run(self._client.get_balance())
        except Exception as exc:
            # Surface insufficient-credit shape for driver's detector.
            msg = str(exc)
            if "2010" in msg or "don't have enough credit" in msg:
                raise TripoInsufficientCredit(msg) from exc
            raise TripoError(f"studio balance error: {exc}") from exc
        free = float(raw.get("free_balance", 0) or 0)
        purchased = float(raw.get("purchased_balance", 0) or 0)
        total = float(raw.get("total_balance", free + purchased) or (free + purchased))
        norm = {
            "balance": total,
            "free_balance": free,
            "purchased_balance": purchased,
            "frozen": float(raw.get("frozen", 0) or 0),
            "_raw": raw,
        }
        self._log("get_balance", norm)
        return norm

    def create_text_to_model(
        self,
        prompt: str,
        *,
        model_version: str = DEFAULT_MODEL_VERSION,
        negative_prompt: str | None = None,
        seed: int | None = None,
        face_limit: int | None = None,
    ) -> str:
        """Submit (once per prompt) and return the next pending variant id.

        The studio endpoint bills one task but yields 4 variants. We treat each
        variant as a sibling :class:`TaskRecord` in the driver's ledger; this
        method hands them out one-by-one so the driver's submit loop still
        registers four ``task_id``s per prompt.
        """
        # Studio ignores our variation-style suffix inside the prompt but we
        # keep it so api.log is useful. We dedupe by the *base* prompt: pre-
        # stripping the " — variation N: …" tail the driver appends.
        base_prompt = re.split(r"\s+—\s+variation\s+\d+", prompt)[0].strip()
        queue = self._pending_variants.get(base_prompt)
        if not queue:
            body: dict[str, Any] = {
                "type": "text_to_model",
                "prompt": base_prompt,
                "model_version": model_version,
            }
            if negative_prompt:
                body["negative_prompt"] = negative_prompt
            if seed is not None:
                body["seed"] = int(seed)
            if face_limit is not None:
                body["face_limit"] = int(face_limit)
            try:
                task_ids = self._run(self._client.create_task(body))
            except Exception as exc:
                msg = str(exc)
                if "2010" in msg or "don't have enough credit" in msg:
                    raise TripoInsufficientCredit(msg) from exc
                raise TripoError(f"studio create task: {exc}") from exc
            queue = list(task_ids)
            self._pending_variants[base_prompt] = queue
            self._log("create_text_to_model", {"prompt": base_prompt, "task_ids": task_ids})
        if not queue:
            raise TripoError(f"studio returned no task_ids for prompt: {base_prompt}")
        task_id = queue.pop(0)
        return str(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        try:
            data = self._run(self._client.get_task(task_id))
        except Exception as exc:
            msg = str(exc)
            if "2010" in msg or "don't have enough credit" in msg:
                raise TripoInsufficientCredit(msg) from exc
            raise TripoError(f"studio poll: {exc}") from exc
        # Normalise to the API client's shape so :class:`TripoBatchDriver`
        # doesn't need a backend branch in its poll loop.
        pbr = data.get("pbr_model")
        model = data.get("model")
        status = data.get("status")
        normalised: dict[str, Any] = {
            "task_id": task_id,
            "status": status,
            "message": data.get("message"),
            "output": {},
        }
        if pbr:
            normalised["output"]["pbr_model"] = pbr
        if model:
            normalised["output"]["model"] = model
        # Preserve running_left_time for adaptive polling if the driver wants it.
        if data.get("running_left_time") is not None:
            normalised["running_left_time"] = data["running_left_time"]
        self._log("get_task", {"task_id": task_id, "status": status})
        return normalised


def _truncate(obj: Any, limit: int) -> Any:
    try:
        s = json.dumps(obj, default=str)
    except TypeError:
        s = str(obj)
    if len(s) <= limit:
        return obj
    return {"_truncated": True, "_len": len(s), "_head": s[:limit]}


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


@dataclass
class TaskRecord:
    prompt_id: str
    variation_id: int  # 1..4
    section_id: str
    asset_category: str
    display_category: str
    prompt_text: str
    task_id: str | None = None
    status: str = "pending"  # pending, submitted, running, success, failed, downloaded, ingested
    attempts: int = 0
    submitted_at: float | None = None
    finished_at: float | None = None
    last_error: str | None = None
    model_url: str | None = None
    download_path: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.prompt_id}_v{self.variation_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class Ledger:
    """JSON-file-backed task ledger (idempotent)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: dict[str, TaskRecord] = {}
        self.created_at: float | None = None
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.records = {}
            self.created_at = None
            return
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self.created_at = data.get("created_at")
        self.records = {
            k: TaskRecord.from_dict(v) for k, v in (data.get("tasks") or {}).items()
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "created_at": self.created_at or time.time(),
            "updated_at": time.time(),
            "tasks": {k: r.to_dict() for k, r in self.records.items()},
        }
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp.replace(self.path)

    def seed_from_specs(self, specs: Sequence[PromptSpec]) -> list[TaskRecord]:
        new: list[TaskRecord] = []
        if self.created_at is None:
            self.created_at = time.time()
        for spec in specs:
            for v_idx, prompt_text in enumerate(spec.variations, start=1):
                rec = TaskRecord(
                    prompt_id=spec.id,
                    variation_id=v_idx,
                    section_id=spec.section_id,
                    asset_category=spec.asset_category,
                    display_category=spec.display_category,
                    prompt_text=prompt_text,
                )
                if rec.key not in self.records:
                    self.records[rec.key] = rec
                    new.append(rec)
        return new

    # filters
    def pending(self) -> list[TaskRecord]:
        return [r for r in self.records.values() if r.status == "pending"]

    def in_flight(self) -> list[TaskRecord]:
        return [r for r in self.records.values() if r.status in ("submitted", "running")]

    def done(self) -> list[TaskRecord]:
        return [r for r in self.records.values() if r.status in ("success", "downloaded", "ingested")]

    def failed(self) -> list[TaskRecord]:
        return [r for r in self.records.values() if r.status == "failed"]

    def touch(self, rec: TaskRecord, **fields_) -> None:
        for k, v in fields_.items():
            setattr(rec, k, v)
        rec.history.append({
            "ts": time.time(),
            "status": rec.status,
            "task_id": rec.task_id,
            "error": rec.last_error,
        })
        self.save()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


@dataclass
class DriverConfig:
    manifest_path: Path
    output_root: Path
    wave_size: int = DEFAULT_WAVE_SIZE
    max_in_flight: int = DEFAULT_MAX_IN_FLIGHT
    submit_spacing_s: float = DEFAULT_SUBMIT_SPACING_S
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S
    max_retries: int = DEFAULT_MAX_RETRIES
    cost_per_task_usd: float = DEFAULT_COST_PER_TASK_USD
    hard_cost_cap_usd: float = DEFAULT_HARD_COST_CAP_USD
    hard_task_cap: int = DEFAULT_HARD_TASK_CAP
    model_version: str = DEFAULT_MODEL_VERSION
    negative_prompt: str = "low quality, blurry, watermark, text, logo, cartoon, flat shading"
    plan_only: bool = False
    single_wave: bool = False


@dataclass
class DriverHooks:
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time
    download: Callable[[str, Path], int] | None = None  # url, dest -> bytes_written


def _default_download(url: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "veilbreakers-tripo-batch/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return len(data)


class TripoBatchDriver:
    def __init__(
        self,
        client: TripoClient,
        config: DriverConfig,
        *,
        hooks: DriverHooks | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.hooks = hooks or DriverHooks()
        self.output_root = config.output_root
        self.downloads_root = self.output_root / "downloads"
        self.ledger_path = self.output_root / "ledger.json"
        self.manifest_json_path = self.output_root / "manifest.json"
        self.api_log_path = self.output_root / "api.log"
        # Rewire client log path to this run.
        self.client.api_log_path = self.api_log_path
        self.ledger = Ledger(self.ledger_path)

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------

    def plan(self) -> list[PromptSpec]:
        text = self.config.manifest_path.read_text(encoding="utf-8")
        specs = parse_manifest(text)
        if not specs:
            raise TripoError(f"No prompts parsed from {self.config.manifest_path}")
        write_structured_manifest(specs, self.manifest_json_path)
        self.ledger.seed_from_specs(specs)
        self.ledger.save()
        return specs

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def pre_flight(self) -> dict[str, Any]:
        """Check credit balance and enforce cost/task caps.

        Returns a dict describing the decision.  Raises ``TripoError`` if
        caps are exceeded.
        """
        balance = self.client.get_balance()
        pending_count = len(self.ledger.pending()) + len(self.ledger.in_flight())
        if pending_count > self.config.hard_task_cap:
            raise TripoError(
                f"ledger has {pending_count} unfinished tasks; hard cap is {self.config.hard_task_cap}"
            )
        estimated_usd = pending_count * self.config.cost_per_task_usd
        if estimated_usd > self.config.hard_cost_cap_usd:
            raise TripoError(
                f"estimated cost ${estimated_usd:.2f} exceeds safety cap ${self.config.hard_cost_cap_usd:.2f}"
            )
        available = float(balance.get("balance") or 0.0)
        decision = {
            "balance": balance,
            "estimated_usd": estimated_usd,
            "pending_tasks": pending_count,
            "hard_cost_cap_usd": self.config.hard_cost_cap_usd,
            "hard_task_cap": self.config.hard_task_cap,
            "can_proceed": available > 0 and pending_count > 0,
        }
        return decision

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        specs = self.plan()
        if self.config.plan_only:
            logger.info(
                "plan-only: %d prompts, %d tasks seeded in ledger",
                len(specs),
                sum(len(s.variations) for s in specs),
            )
            return {
                "plan_only": True,
                "prompts": len(specs),
                "tasks": sum(len(s.variations) for s in specs),
                "ledger_path": str(self.ledger_path),
                "manifest_json": str(self.manifest_json_path),
            }

        decision = self.pre_flight()
        logger.info("pre-flight: %s", json.dumps(decision, default=str))
        if not decision["can_proceed"]:
            return {
                "aborted": True,
                "reason": "insufficient_balance_or_nothing_to_do",
                "decision": decision,
            }

        waves = self._group_pending_by_prompt(self.config.wave_size)
        summary = {
            "submitted": 0,
            "downloaded": 0,
            "failed": 0,
            "waves": 0,
            "decision": decision,
        }
        for wave_specs in waves:
            summary["waves"] += 1
            wave_records = self._records_for_prompts(wave_specs)
            logger.info(
                "wave %d: %d prompts -> %d tasks",
                summary["waves"],
                len(wave_specs),
                len(wave_records),
            )
            self._submit_records(wave_records)
            self._drain_in_flight()
            self._download_successes()
            if self.config.single_wave:
                break

        summary["submitted"] = sum(1 for r in self.ledger.records.values() if r.status not in ("pending",))
        summary["downloaded"] = sum(1 for r in self.ledger.records.values() if r.status in ("downloaded", "ingested"))
        summary["failed"] = len(self.ledger.failed())
        return summary

    def _group_pending_by_prompt(self, wave_size: int) -> list[list[str]]:
        # Use submission order from the manifest JSON (prompt_id order).
        manifest_data = json.loads(self.manifest_json_path.read_text(encoding="utf-8"))
        prompt_ids = [p["id"] for p in manifest_data["prompts"]]
        # Only include prompts that still have pending variations.
        pending_prompts = [
            pid for pid in prompt_ids
            if any(
                r.prompt_id == pid and r.status in ("pending", "submitted", "running", "failed")
                for r in self.ledger.records.values()
            )
        ]
        waves: list[list[str]] = []
        for i in range(0, len(pending_prompts), wave_size):
            waves.append(pending_prompts[i:i + wave_size])
        return waves

    def _records_for_prompts(self, prompt_ids: Iterable[str]) -> list[TaskRecord]:
        ids = set(prompt_ids)
        out: list[TaskRecord] = []
        for rec in self.ledger.records.values():
            if rec.prompt_id in ids and rec.status in ("pending", "failed"):
                if rec.status == "failed" and rec.attempts > self.config.max_retries:
                    continue
                if rec.status == "failed":
                    # Reset for retry.
                    rec.status = "pending"
                    rec.last_error = None
                out.append(rec)
        return out

    def _submit_records(self, records: Sequence[TaskRecord]) -> None:
        submitted = 0
        for rec in records:
            # Respect in-flight cap.
            while len(self.ledger.in_flight()) >= self.config.max_in_flight:
                self._drain_in_flight(single_pass=True)
                if len(self.ledger.in_flight()) >= self.config.max_in_flight:
                    self.hooks.sleep(self.config.poll_interval_s)
            try:
                task_id = self.client.create_text_to_model(
                    rec.prompt_text,
                    model_version=self.config.model_version,
                    negative_prompt=self.config.negative_prompt,
                    seed=1000 + rec.variation_id,
                )
            except TripoInsufficientCredit as e:
                self.ledger.touch(rec, status="failed", last_error=f"insufficient_credit: {e}", attempts=rec.attempts + 1)
                logger.error("insufficient credit; halting submissions")
                raise
            except TripoError as e:
                self.ledger.touch(
                    rec,
                    status="failed",
                    last_error=str(e),
                    attempts=rec.attempts + 1,
                )
                continue
            self.ledger.touch(
                rec,
                status="submitted",
                task_id=task_id,
                attempts=rec.attempts + 1,
                submitted_at=self.hooks.clock(),
                last_error=None,
            )
            submitted += 1
            if submitted < len(records):
                self.hooks.sleep(self.config.submit_spacing_s)

    def _drain_in_flight(self, single_pass: bool = False) -> None:
        while True:
            inflight = self.ledger.in_flight()
            if not inflight:
                return
            for rec in inflight:
                try:
                    data = self.client.get_task(rec.task_id or "")
                except TripoError as e:
                    logger.warning("poll %s failed: %s", rec.task_id, e)
                    continue
                status = str(data.get("status") or "").lower()
                if status in ("queued", "pending"):
                    self.ledger.touch(rec, status="submitted")
                elif status == "running":
                    self.ledger.touch(rec, status="running")
                elif status in ("success", "succeeded", "completed"):
                    output = data.get("output") or {}
                    model_url = output.get("pbr_model") or output.get("model")
                    if not model_url:
                        self.ledger.touch(rec, status="failed", last_error="no model url in output")
                        continue
                    self.ledger.touch(
                        rec,
                        status="success",
                        model_url=model_url,
                        finished_at=self.hooks.clock(),
                    )
                elif status in ("failed", "error", "banned", "expired"):
                    self.ledger.touch(
                        rec,
                        status="failed",
                        last_error=f"tripo status={status} msg={data.get('message')}",
                        finished_at=self.hooks.clock(),
                    )
                # else: unknown status — leave it.
            if single_pass:
                return
            if not self.ledger.in_flight():
                return
            self.hooks.sleep(self.config.poll_interval_s)

    def _download_successes(self) -> None:
        downloader = self.hooks.download or _default_download
        for rec in self.ledger.records.values():
            if rec.status != "success" or not rec.model_url:
                continue
            dest = self.downloads_root / rec.display_category / f"{rec.prompt_id}_v{rec.variation_id}.glb"
            try:
                n = downloader(rec.model_url, dest)
            except Exception as e:  # noqa: BLE001
                self.ledger.touch(rec, status="success", last_error=f"download error: {e}")
                continue
            self.ledger.touch(
                rec,
                status="downloaded",
                download_path=str(dest),
                last_error=None,
            )
            logger.info("downloaded %s (%d bytes) -> %s", rec.key, n, dest)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Tripo batch text-to-model driver.")
    p.add_argument("--manifest", type=Path, default=Path("docs/TRIPO_FOLIAGE_MANIFEST_2026_04_24.md"))
    p.add_argument("--output", type=Path, default=Path("output/tripo_generation"))
    p.add_argument("--wave-size", type=int, default=DEFAULT_WAVE_SIZE)
    p.add_argument("--max-in-flight", type=int, default=DEFAULT_MAX_IN_FLIGHT)
    p.add_argument("--submit-spacing", type=float, default=DEFAULT_SUBMIT_SPACING_S)
    p.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_S)
    p.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    p.add_argument("--cost-per-task", type=float, default=DEFAULT_COST_PER_TASK_USD)
    p.add_argument("--hard-cost-cap", type=float, default=DEFAULT_HARD_COST_CAP_USD)
    p.add_argument("--hard-task-cap", type=int, default=DEFAULT_HARD_TASK_CAP)
    p.add_argument("--model-version", type=str, default=DEFAULT_MODEL_VERSION)
    p.add_argument("--plan-only", action="store_true", help="Parse manifest + seed ledger, no API calls.")
    p.add_argument("--single-wave", action="store_true")
    p.add_argument(
        "--run-ingest",
        action="store_true",
        help="After generation completes, invoke scripts/batch_ingest_tripo_downloads.py.",
    )
    p.add_argument("--assets-root", type=Path, default=Path("assets/foliage"))
    p.add_argument("--blender", type=Path, default=None)
    p.add_argument("--synthetic-ingest", action="store_true")
    p.add_argument(
        "--backend",
        choices=("api", "studio"),
        default="studio",
        help=(
            "Which Tripo backend to hit. 'studio' uses /v2/web/ and "
            "subscription credits (default). 'api' uses /v2/openapi/ and "
            "purchased API credits via TRIPO_API_KEY."
        ),
    )
    p.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env.tripo_studio"),
        help="Path to a KEY=VALUE file with TRIPO_SESSION_COOKIE/TOKEN.",
    )
    p.add_argument(
        "--studio-model-version",
        type=str,
        default="v3.0-20250812",
        help="model_version for studio backend (default v3.0-20250812).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _load_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv-style ``KEY=VALUE`` file, no interpolation.

    Silent-returns ``{}`` if the file is missing so callers can layer env
    vars from multiple places. Comments (``#``) and blank lines are skipped.
    """
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def _run_ingest(output_root: Path, assets_root: Path, *, blender: Path | None, synthetic: bool) -> int:
    """Shell out to the existing batch ingest script."""
    import subprocess

    cmd = [
        sys.executable,
        str(Path("scripts") / "batch_ingest_tripo_downloads.py"),
        "--downloads", str(output_root / "downloads"),
        "--assets", str(assets_root),
    ]
    if blender:
        cmd.extend(["--blender", str(blender)])
    if synthetic:
        cmd.append("--synthetic")
    logger.info("running ingest: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Layer env from the dotenv file on top of the process env (process env
    # wins so operators can still override via `export`).
    file_env = _load_env_file(args.env_file)
    for k, v in file_env.items():
        os.environ.setdefault(k, v)

    backend = args.backend
    model_version = args.model_version

    client: Any
    if backend == "studio":
        session_cookie = os.environ.get("TRIPO_SESSION_COOKIE", "")
        session_token = os.environ.get("TRIPO_SESSION_TOKEN", "")
        if not args.plan_only and not session_cookie and not session_token:
            print(
                "ERROR: backend=studio requires TRIPO_SESSION_COOKIE "
                "(preferred) or TRIPO_SESSION_TOKEN. Add it to "
                f"{args.env_file} or export it.",
                file=sys.stderr,
            )
            return 2
        if args.plan_only:
            # plan-only doesn't hit the network so a dummy API-mode client is
            # fine and avoids the httpx import.
            client = TripoClient("plan-only")
        else:
            client = TripoStudioBackend(
                session_cookie=session_cookie,
                session_token=session_token,
            )
            # Studio uses a newer model version by default.
            if model_version == DEFAULT_MODEL_VERSION:
                model_version = args.studio_model_version
    else:
        api_key = os.environ.get("TRIPO_API_KEY", "")
        if not args.plan_only and not api_key:
            print("ERROR: TRIPO_API_KEY is not set.", file=sys.stderr)
            return 2
        client = TripoClient(api_key or "plan-only")

    config = DriverConfig(
        manifest_path=args.manifest,
        output_root=args.output,
        wave_size=args.wave_size,
        max_in_flight=args.max_in_flight,
        submit_spacing_s=args.submit_spacing,
        poll_interval_s=args.poll_interval,
        max_retries=args.max_retries,
        cost_per_task_usd=args.cost_per_task,
        hard_cost_cap_usd=args.hard_cost_cap,
        hard_task_cap=args.hard_task_cap,
        model_version=model_version,
        plan_only=args.plan_only,
        single_wave=args.single_wave,
    )
    driver = TripoBatchDriver(client, config)
    try:
        summary = driver.run()
    except TripoInsufficientCredit as e:
        print(f"ABORTED: insufficient credit: {e}", file=sys.stderr)
        print("See docs/TRIPO_GENERATION_RUNBOOK.md for how to top up and resume.", file=sys.stderr)
        return 3
    print(json.dumps(summary, indent=2, default=str))
    if args.run_ingest and not args.plan_only:
        rc = _run_ingest(
            args.output,
            args.assets_root,
            blender=args.blender,
            synthetic=args.synthetic_ingest,
        )
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
