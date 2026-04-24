# Tripo Studio Auth Diagnosis — 2026-04-24 early morning

## Symptom
`scripts/tripo_batch_generate.py --backend studio` failed pre-flight with
`RuntimeError: Failed to extract JWT from studio page. Session cookie may have expired.`

## Root cause (confirmed)
The ported `TripoStudioClient._refresh_jwt` assumes the Nuxt SSR page embeds a
JWT (`eyJ...`) directly in the server-rendered HTML. **This assumption is
outdated.** Tripo's studio has migrated to client-side auth:

1. The Nuxt SSR renders `__NUXT_DATA__` with user profile, subscription, wallet,
   region data — but NO JWT. Verified: 144KB of serialized state, zero standard
   JWT three-part tokens. The only `eyJ...` hits in the page are **S3
   pre-signed URL policies** (base64-encoded `{"Statement":[{"Resource":...}]}`)
   for asset thumbnails.
2. `/v2/web/user/balance`, `/v2/web/user/info`, `/v2/web/wallet/balance`,
   `/v2/web/auth/refresh`, `/v2/web/auth/session`, `/v2/web/session` — ALL
   return HTTP 401 `{"code":1002,"message":"Authentication failed"}` when sent
   with just the `ory_kratos_session` cookie.
3. Only `/v2/studio/marketing/detail` (a public marketing endpoint) returns 200
   with the cookie alone — confirming the cookie is recognized but does NOT
   grant JWT auth directly.

## What this means
The JWT must be minted by client-side JavaScript *after hydration*, probably by
calling a /v2/web/ endpoint that inspects the Kratos cookie via a specific
headers pattern (CSRF token + referrer + fingerprint) we don't replicate when
hitting the API with plain httpx.

## Mitigations in priority order

### Option 1 — Provide a JWT directly (fastest, 2-hour validity)
1. Open https://studio.tripo3d.ai in Chrome/Firefox while logged in.
2. DevTools → Application → Local Storage OR Network → any `/v2/web/` request.
3. Copy the `Authorization: Bearer <JWT>` value.
4. In `.env.tripo_studio`, set:
   ```
   TRIPO_SESSION_TOKEN=eyJ...  (paste full JWT without 'Bearer ')
   ```
5. Re-run: `python scripts/tripo_batch_generate.py --backend studio`.

The JWT expires after ~2h — re-paste as needed. A single 2h window is enough
to submit all 132 tasks (the driver submits in waves of 8 × 1s delay, then
polls every 30s; ~15 min total wall clock).

### Option 2 — Headless browser-assisted auth (resilient, 25-day validity)
Add a Playwright-based JWT harvester:
1. `pip install playwright; playwright install chromium`.
2. Write `scripts/tripo_harvest_jwt.py` that launches headless Chromium,
   injects `ory_kratos_session` cookie, navigates to `studio.tripo3d.ai`,
   waits for the first `/v2/web/` request, captures the `Authorization`
   header, writes it to `.env.tripo_studio` as `TRIPO_SESSION_TOKEN`.
3. Schedule the harvester to run every 90 min via cron/Task Scheduler.

This is the proper long-term fix. The gamedev-toolkit's `TripoStudioClient`
should be updated upstream with this mechanism.

### Option 3 — Use OpenAPI API credits instead
Purchase/top-up API credits at https://platform.tripo3d.ai/billing. The
existing `--backend api` path works immediately once balance > 0.

## Status of the 132-task queue
- `output/tripo_generation/ledger.json` — all 132 `TaskRecord`s seeded at
  `status: pending`. No `task_id`s assigned.
- Driver is idempotent: once auth is fixed (either path above), re-running
  `tripo_batch_generate.py --backend studio` (or `--backend api`) picks up
  from the pending ledger without duplicating work.

## Impact on Phase K / K+ node builds
**None.** Node 1 and Node 2 both have procedural foliage fallbacks in
`environment_scatter._scatter_pass` (trees from L-system, rocks from
distribution-sampled primitives, grass from cross-card instances). Builds
proceed at AAA quality using procedurals — Tripo assets upgrade visual
density and variation when they land but are not gating.
