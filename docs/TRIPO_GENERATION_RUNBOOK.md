# Tripo Overnight Generation Runbook

Driver: [`scripts/tripo_batch_generate.py`](../scripts/tripo_batch_generate.py)
Manifest: [`docs/TRIPO_FOLIAGE_MANIFEST_2026_04_24.md`](TRIPO_FOLIAGE_MANIFEST_2026_04_24.md)
Ingest: [`scripts/batch_ingest_tripo_downloads.py`](../scripts/batch_ingest_tripo_downloads.py)

This runbook drives Tripo3D end-to-end to materialise all
**33 prompts × 4 variations = 132 foliage assets**, then hands them off to the
existing decimation / LOD / catalog pipeline.

The driver supports **two backends**:

| Backend  | Endpoint         | Credits used         | Auth                                  |
|----------|------------------|----------------------|---------------------------------------|
| `studio` | `/v2/web/`       | Subscription credits | `ory_kratos_session` cookie or JWT    |
| `api`    | `/v2/openapi/`   | Pay-as-you-go API    | `TRIPO_API_KEY` Bearer token          |

`studio` is the default because the subscription credit pool is usually
pre-paid and refills monthly. The `api` backend is the fallback for
emergencies or when subscription credits are exhausted.

---

## Status at time of writing (2026-04-24, Phase I+++)

| Backend  | State                                                                 |
|----------|-----------------------------------------------------------------------|
| `studio` | **Session cookie expired (~37 days old).** Re-extract from DevTools.  |
| `api`    | Balance `$0`. Top up at https://platform.tripo3d.ai/billing.          |

Current auth diagnostic is persisted to
[`output/tripo_generation/STUDIO_AUTH_FAILED.log`](../output/tripo_generation/STUDIO_AUTH_FAILED.log)
with the exact probe responses from Kratos, the Nuxt SSR page, and both the
`/v2/web/` and `/v2/openapi/` balance endpoints.

### Refreshing the studio session cookie

1. Open https://studio.tripo3d.ai in a logged-in browser tab.
2. DevTools → Application → Cookies → `studio.tripo3d.ai`.
3. Copy the value of `ory_kratos_session`.
4. Paste into `veilbreakers-terrain/.env.tripo_studio` as
   `TRIPO_SESSION_COOKIE=<paste>`.

The cookie auto-refreshes its embedded JWTs for ~25–30 days after that, no
further action required.

---

## One-command invocation (studio backend — default)

```bash
# Make sure .env.tripo_studio has a fresh TRIPO_SESSION_COOKIE
cd veilbreakers-terrain
python scripts/tripo_batch_generate.py --run-ingest
```

## One-command invocation (api backend — fallback)

```bash
export TRIPO_API_KEY="tsk_..."           # bash
# $env:TRIPO_API_KEY = "tsk_..."         # PowerShell
cd veilbreakers-terrain
python scripts/tripo_batch_generate.py --backend api --run-ingest
```

That single call:

1. Parses `docs/TRIPO_FOLIAGE_MANIFEST_2026_04_24.md` → 26 prompts.
2. Writes `output/tripo_generation/manifest.json` (structured).
3. Seeds `output/tripo_generation/ledger.json` with 104 `TaskRecord`s.
4. Pre-flight checks credit balance, enforces `--hard-cost-cap` (default $100)
   and `--hard-task-cap` (104).
5. Submits prompts in waves of 8 (×4 = 32 tasks per wave), sleeping 1.0s
   between submits, with max 20 in-flight tasks at once.
6. Polls every 30s until each task transitions to `success` or `failed`.
7. Downloads each GLB to
   `output/tripo_generation/downloads/<display_category>/<prompt_id>_v<n>.glb`.
8. Shells out to `batch_ingest_tripo_downloads.py` which decimates, builds
   LOD0/1/2, exports each LOD as GLB, and registers the asset in
   `assets/foliage/catalog.json`.

Everything is **idempotent**: interrupt with Ctrl-C at any time and re-running
the same command resumes from the ledger without re-submitting completed
tasks or re-downloading files.

---

## Cost estimate

Tripo charges approximately **$0.20 – $0.50 per text-to-model task** (30
credits per generation per their docs). The driver defaults assume
`$0.30 / task`:

```
104 tasks × $0.30 = $31.20  (estimated)
```

The driver hard-caps cost at `$100`. Override with `--cost-per-task` and
`--hard-cost-cap` if your account's pricing differs, but keep the safety
valve above the estimate to avoid an uncontrolled bleed.

Before any submission the driver calls `GET /v2/openapi/user/balance` and
refuses to proceed if the balance is zero.

---

## Directory layout

```
output/tripo_generation/
├── manifest.json                 # structured 26-prompt manifest
├── ledger.json                   # task status: pending/submitted/running/success/failed/downloaded/ingested
├── api.log                       # JSON-lines log of every API call
└── downloads/
    ├── grass/                    # display_category folders
    ├── rock_small/
    ├── rock_boulder/
    ├── moss/
    ├── vine/
    ├── tree/
    ├── log/
    ├── bush/
    ├── water_foliage/
    ├── structure/
    ├── terrain_tile/
    └── accent/
```

After `batch_ingest_tripo_downloads.py` runs, each GLB is processed into:

```
assets/foliage/
├── catalog.json                  # source-of-truth for terrain_foliage_catalog
├── grass/<asset_id>/<asset_id>_LOD[012].glb
├── tree/<asset_id>/<asset_id>_LOD[012].glb
└── ...
```

---

## CLI flags

```
--backend {api,studio} Which Tripo backend to hit (default: studio)
--env-file PATH         dotenv file for TRIPO_SESSION_COOKIE (default: .env.tripo_studio)
--studio-model-version  Studio model_version (default: v3.0-20250812)
--manifest PATH         Manifest .md (default: docs/TRIPO_FOLIAGE_MANIFEST_2026_04_24.md)
--output PATH           Output root (default: output/tripo_generation)
--wave-size N           Prompts per wave (default: 8 -> 32 tasks)
--max-in-flight N       Max concurrent tasks (default: 20)
--submit-spacing S      Sleep between submits (default: 1.0s)
--poll-interval S       Sleep between poll rounds (default: 30.0s)
--max-retries N         Retries per failed task (default: 2)
--cost-per-task USD     Cost estimate per task (default: 0.30)
--hard-cost-cap USD     Abort if estimate exceeds (default: 100.0)
--hard-task-cap N       Refuse > N total tasks (default: 104)
--model-version STR     Tripo model_version (default: v2.5-20250123)
--plan-only             Seed ledger + manifest.json, no network calls
--single-wave           Run one wave then stop (good for first-night)
--run-ingest            After generation, invoke batch_ingest_tripo_downloads.py
--assets-root PATH      Ingest target (default: assets/foliage)
--blender PATH          Blender exe for ingest
--synthetic-ingest      Use the pure-Python ingest path (no Blender)
-v / --verbose
```

---

## Resume semantics

Every state transition is fsync'd to `ledger.json`. `TaskRecord.status`
follows this state machine:

```
pending ─submit──▶ submitted ─poll──▶ running ─poll──▶ success ─download──▶ downloaded
   ▲                    │                │                                       │
   │                    └─error──▶ failed◀┘                                       │
   │                                 │                                            │
   └──────retry (≤ max_retries) ─────┘                                            │
                                                                                  ▼
                                                                            ingested
                                                                  (set by batch_ingest_...)
```

Re-running the driver:
- skips `ingested` / `downloaded` records,
- polls any `submitted` / `running` records (they may have completed while
  the driver was offline),
- retries `failed` records up to `max_retries`,
- submits any `pending` records.

---

## If generation completes but ingest did not

```bash
python scripts/batch_ingest_tripo_downloads.py \
    --downloads output/tripo_generation/downloads \
    --assets   assets/foliage
```

Add `--watch 60` to loop every minute if you want it sitting in the
background watching for late arrivals.

---

## If a task is stuck for hours

```bash
# Inspect the ledger entry
python - <<'PY'
import json, pathlib
data = json.loads(pathlib.Path("output/tripo_generation/ledger.json").read_text())
for key, rec in data["tasks"].items():
    if rec["status"] in ("submitted", "running"):
        print(key, rec["task_id"], rec["status"], rec.get("submitted_at"))
PY

# Hit Tripo directly for the specific task
curl -s -H "Authorization: Bearer $TRIPO_API_KEY" \
     "https://api.tripo3d.ai/v2/openapi/task/<task_id>" | jq .
```

Common failure modes:
- `banned` — prompt triggered Tripo's content filter. Edit the manifest
  prompt and clear the specific record's status back to `pending`.
- `expired` — task sat too long on the queue. Same fix as above.
- Infinite `queued` — Tripo compute backlog; wait it out or contact support.

---

## Safety invariants (don't disable these casually)

| Guard | Default | Purpose |
|-------|---------|---------|
| `--hard-task-cap`    | 104      | Refuses to launch more than the manifest's scope. |
| `--hard-cost-cap`    | $100     | Refuses to launch if estimate exceeds budget. |
| `--max-in-flight`    | 20       | Keeps us inside Tripo's polite concurrency range. |
| `--submit-spacing`   | 1.0s     | Avoids rate-limit 429s at start of wave. |
| Pre-flight `balance` | > 0      | Refuses to submit against a dry account. |

---

## Tests

```bash
python -m pytest veilbreakers_terrain/tests/test_tripo_batch_generate.py -v
```

Covers manifest parsing (26 → 104), category overrides, ledger round-trip,
pre-flight caps, full wave submit → poll → download loop, insufficient-credit
handling, transient-failure retry, and API-log format.

No real HTTP traffic — every test uses the `http_fn` seam on `TripoClient`.

---

## Appendix: Tripo API cheat-sheet

```bash
# Balance
curl -s -H "Authorization: Bearer $TRIPO_API_KEY" \
     https://api.tripo3d.ai/v2/openapi/user/balance
# -> {"code":0,"data":{"balance":0,"frozen":0}}

# Create text-to-model
curl -s -X POST https://api.tripo3d.ai/v2/openapi/task \
     -H "Authorization: Bearer $TRIPO_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"type":"text_to_model","prompt":"...","model_version":"v2.5-20250123"}'
# -> {"code":0,"data":{"task_id":"..."}}

# Poll
curl -s -H "Authorization: Bearer $TRIPO_API_KEY" \
     https://api.tripo3d.ai/v2/openapi/task/<task_id>
# -> {"code":0,"data":{"task_id":"...","status":"success","output":{"model":"https://..."}}}
```

Status values observed: `queued`, `running`, `success`, `failed`, and
(documented but unconfirmed at this account tier): `banned`, `expired`.
