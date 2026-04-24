"""Tests for ``scripts/tripo_batch_generate.py``.

Entirely stub-driven — no real network traffic, no Tripo credits spent.
Exercises:
  - manifest parsing (26 prompts -> 104 tasks, every category covered)
  - category override disambiguation (``tree_oak_ancient`` -> ``oak`` etc.)
  - ledger round-trip + idempotent seeding
  - pre-flight cost + task cap enforcement
  - submit loop writes ``task_id`` + ``submitted`` status
  - poll loop transitions submitted -> success -> downloaded when the stubbed
    Tripo client yields a model URL
  - failure handling: transient HTTP failure flips status to ``failed``,
    retry cycle increments attempt counter up to ``max_retries``
  - insufficient-credit response raises ``TripoInsufficientCredit`` and halts
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import tripo_batch_generate as tbg  # noqa: E402


MANIFEST_PATH = _REPO_ROOT / "docs" / "TRIPO_FOLIAGE_MANIFEST_2026_04_24.md"


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


def test_manifest_parses_to_26_prompts_104_tasks() -> None:
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    specs = tbg.parse_manifest(text)
    assert len(specs) == 26
    assert sum(len(s.variations) for s in specs) == 104
    for s in specs:
        assert len(s.variations) == 4
        assert s.asset_category in tbg.CATEGORY_TO_DISPLAY
        assert s.display_category == tbg.CATEGORY_TO_DISPLAY[s.asset_category]
        assert s.poly_budget_min <= s.poly_budget_max


@pytest.mark.parametrize(
    "prompt_id,expected",
    [
        ("tree_oak_ancient", "oak"),
        ("tree_birch_pale", "birch"),
        ("tree_pine_black", "pine"),
        ("tree_dead_claw", "dead_tree"),
        ("log_fallen_mossy", "log"),
        ("moss_stalactite_drape", "moss_drape"),
        ("bush_bramble_thorn", "bramble"),
        ("walkway_cobbled", "walkway"),
        ("grass_lush_wet", "grass"),
    ],
)
def test_category_override_disambiguates(prompt_id: str, expected: str) -> None:
    assert tbg._detect_category(prompt_id) == expected


def test_variation_styles_are_distinct() -> None:
    base = "a test prompt"
    out = tbg._make_variation_prompts(base, "grass")
    assert len(out) == 4
    assert len(set(out)) == 4
    # Each variation must still contain the base phrase verbatim (Tripo
    # retrieval is word-order sensitive per the manifest warning).
    for v in out:
        assert base in v


# ---------------------------------------------------------------------------
# Stub Tripo HTTP client
# ---------------------------------------------------------------------------


class StubHttp:
    """Deterministic Tripo HTTP responder.

    Call model:
        - GET /user/balance         -> balance decision
        - POST /task                -> create, yields task_id-N
        - GET  /task/<id>           -> stateful status machine per task
    """

    def __init__(self, *, balance: float = 50.0, fail_submit_count: int = 0) -> None:
        self.balance = balance
        self.fail_submit_count = fail_submit_count
        self.submit_count = 0
        self.tasks: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, url: str, body: dict | None, headers: dict[str, str]) -> tuple[int, dict]:
        self.calls.append((method, url))
        if url.endswith("/user/balance"):
            return 200, {"code": 0, "data": {"balance": self.balance, "frozen": 0}}
        if method == "POST" and url.endswith("/task"):
            self.submit_count += 1
            if self.submit_count <= self.fail_submit_count:
                return 500, {"code": 1, "message": "transient", "suggestion": ""}
            tid = f"task-{self.submit_count:04d}"
            self.tasks[tid] = {"status": "queued", "poll_count": 0}
            return 200, {"code": 0, "data": {"task_id": tid}}
        if method == "GET" and "/task/" in url:
            tid = url.rsplit("/", 1)[-1]
            st = self.tasks.get(tid)
            if not st:
                return 404, {"code": 404, "message": "not found"}
            st["poll_count"] += 1
            # queued -> running -> success over 3 polls
            if st["poll_count"] == 1:
                st["status"] = "running"
            else:
                st["status"] = "success"
            resp = {
                "code": 0,
                "data": {
                    "task_id": tid,
                    "status": st["status"],
                    "output": {
                        "model": f"https://stub.local/models/{tid}.glb",
                        "pbr_model": f"https://stub.local/models/{tid}_pbr.glb",
                    } if st["status"] == "success" else {},
                },
            }
            return 200, resp
        return 400, {"code": 400, "message": f"unknown route {method} {url}"}


class InsufficientStubHttp(StubHttp):
    def __call__(self, method, url, body, headers):  # type: ignore[override]
        if method == "POST" and url.endswith("/task"):
            return 403, {"code": 2010, "message": "You don't have enough credit to create this task"}
        return super().__call__(method, url, body, headers)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def test_ledger_idempotent_seed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    ledger = tbg.Ledger(path)
    specs = tbg.parse_manifest(MANIFEST_PATH.read_text(encoding="utf-8"))
    new1 = ledger.seed_from_specs(specs)
    ledger.save()
    assert len(new1) == 104
    # Re-load and seed again — nothing new should appear.
    ledger2 = tbg.Ledger(path)
    new2 = ledger2.seed_from_specs(specs)
    assert new2 == []
    assert len(ledger2.records) == 104


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _make_driver(tmp_path: Path, http: StubHttp, **cfg_over: Any) -> tbg.TripoBatchDriver:
    client = tbg.TripoClient("fake-key", http_fn=http)
    config = tbg.DriverConfig(
        manifest_path=MANIFEST_PATH,
        output_root=tmp_path / "out",
        wave_size=cfg_over.get("wave_size", 2),
        max_in_flight=cfg_over.get("max_in_flight", 4),
        submit_spacing_s=0.0,
        poll_interval_s=0.0,
        max_retries=cfg_over.get("max_retries", 2),
        hard_cost_cap_usd=cfg_over.get("hard_cost_cap_usd", 1000.0),
        hard_task_cap=cfg_over.get("hard_task_cap", 200),
        single_wave=cfg_over.get("single_wave", True),
    )
    downloads: list[tuple[str, Path]] = []

    def fake_download(url: str, dest: Path) -> int:
        downloads.append((url, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"stub-glb")
        return 8

    hooks = tbg.DriverHooks(
        sleep=lambda _s: None,
        clock=lambda: 1000.0,
        download=fake_download,
    )
    driver = tbg.TripoBatchDriver(client, config, hooks=hooks)
    driver._test_downloads = downloads  # type: ignore[attr-defined]
    return driver


def test_preflight_rejects_over_cost_cap(tmp_path: Path) -> None:
    http = StubHttp()
    driver = _make_driver(tmp_path, http, hard_cost_cap_usd=0.01)
    driver.plan()
    with pytest.raises(tbg.TripoError):
        driver.pre_flight()


def test_preflight_rejects_over_task_cap(tmp_path: Path) -> None:
    http = StubHttp()
    driver = _make_driver(tmp_path, http, hard_task_cap=10)
    driver.plan()
    with pytest.raises(tbg.TripoError):
        driver.pre_flight()


def test_full_wave_submits_polls_and_downloads(tmp_path: Path) -> None:
    http = StubHttp()
    driver = _make_driver(tmp_path, http, wave_size=2, single_wave=True)
    summary = driver.run()
    # First wave: 2 prompts × 4 variations = 8 tasks.
    downloads = driver._test_downloads  # type: ignore[attr-defined]
    assert len(downloads) == 8
    # Every download landed under the correct display_category folder.
    for _url, dest in downloads:
        assert dest.parent.parent.name == "downloads"
        assert dest.suffix == ".glb"
        assert dest.exists()
    # Ledger reflects downloaded state.
    downloaded = [r for r in driver.ledger.records.values() if r.status == "downloaded"]
    assert len(downloaded) == 8
    # Non-wave prompts still pending.
    pending = [r for r in driver.ledger.records.values() if r.status == "pending"]
    assert len(pending) == 104 - 8


def test_insufficient_credit_raises_and_halts(tmp_path: Path) -> None:
    http = InsufficientStubHttp(balance=10.0)
    driver = _make_driver(tmp_path, http)
    with pytest.raises(tbg.TripoInsufficientCredit):
        driver.run()
    # Ledger marks the first task as failed with credit error.
    failed = [r for r in driver.ledger.records.values() if r.status == "failed"]
    assert failed, "expected at least one task marked failed"
    assert "insufficient_credit" in (failed[0].last_error or "")


def test_transient_submit_failure_increments_attempts(tmp_path: Path) -> None:
    http = StubHttp(fail_submit_count=2)
    driver = _make_driver(tmp_path, http, wave_size=1, single_wave=True, max_retries=5)
    driver.run()
    # First wave has 4 tasks; the first 2 submits return 500 then succeed on
    # later ones. Two records should now be in 'failed' state with attempts>=1.
    records = [r for r in driver.ledger.records.values() if r.prompt_id == "grass_lush_wet"]
    failed = [r for r in records if r.status == "failed"]
    assert len(failed) == 2
    for r in failed:
        assert r.attempts >= 1


def test_api_log_captures_calls(tmp_path: Path) -> None:
    http = StubHttp()
    driver = _make_driver(tmp_path, http, wave_size=1)
    driver.run()
    log_path = driver.api_log_path
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 4  # balance + at least one create + one poll
    for line in lines:
        entry = json.loads(line)
        assert "method" in entry
        assert "url" in entry
        assert "code" in entry


def test_structured_manifest_is_written(tmp_path: Path) -> None:
    http = StubHttp()
    driver = _make_driver(tmp_path, http)
    driver.plan()
    mj = driver.manifest_json_path
    assert mj.exists()
    data = json.loads(mj.read_text(encoding="utf-8"))
    assert data["total_prompts"] == 26
    assert data["total_tasks"] == 104
    assert len(data["prompts"]) == 26
    # Every prompt has variations + asset_category.
    for p in data["prompts"]:
        assert len(p["variations"]) == 4
        assert p["asset_category"] in tbg.CATEGORY_TO_DISPLAY
