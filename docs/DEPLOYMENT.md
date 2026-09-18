# Deployment & running instructions

## What this repository contains

| Path | What it is | Can it run on GitHub Pages? |
|---|---|---|
| `site/` | Static dashboard preview (self-contained HTML/CSS/JS + synthetic fixtures) | **Yes** |
| `apps/web/` | The real Next.js 15 dashboard | Only if statically exported |
| `apps/api/` | FastAPI backend (`/v1/*`, roles, SSE) | **No** — Pages cannot run Python |
| `apps/worker/` | Ingest pipeline + CLI | **No** |
| `packages/*` | Domain, pricing, connectors, resolver, features, forecasting | **No** |
| `migrations/` | Alembic migrations | **No** |

### Important: GitHub Pages is static-only

GitHub Pages serves files. It cannot execute Python, so the FastAPI API is not
reachable from a Pages site. The Pages deployment in this repo is therefore a
**UI preview with labelled synthetic fixture data** — enough to review the
interface and information architecture, not a live market feed.

To run the whole system you need a Python host (see "Option B" below).

---

## Option A — Pages preview (already configured)

URL once Pages is enabled:
`https://miskina30.github.io/bet-bot/`

The preview renders the opportunity board, source health, alert inbox, paper
ledger and model cards from `site/fixtures.js`. Every row is marked synthetic.

To update it, edit `site/` and push to `main`; the workflow redeploys.

---

## Option B — run the full stack locally (no Docker, no keys)

Requirements: Python 3.12. No provider accounts needed — the system runs on
labelled fixtures.

```powershell
git clone https://github.com/Miskina30/bet-bot.git
cd bet-bot
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# verify the build (should print: 64 passed)
.\.venv\Scripts\python.exe -m pytest -q

# create the schema, seed the synthetic demo universe
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m academic_edge_worker.cli seed

# run the API -> interactive docs at http://127.0.0.1:8000/docs
.\.venv\Scripts\python.exe -m uvicorn academic_edge_api.main:app --reload --port 8000
```

### Frontend (requires Node.js 20+)

```powershell
cd apps/web
npm install
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev        # http://localhost:3000
```

---

## Option C — production-shaped stack (requires Docker)

```powershell
Copy-Item .env.example .env
docker compose up --build -d      # Postgres 16 + Redis + MinIO + api + worker + web
docker compose logs -f api worker
```

---

## Adding live provider keys (optional)

Without keys the system stays in fixture mode. To go live, register the accounts
yourself and put the keys in `.env` (never commit `.env`):

1. **API-Football** — <https://dashboard.api-football.com/register> → set `API_FOOTBALL_KEY`
2. **football-data.org** — <https://www.football-data.org/client/register> → set `FOOTBALL_DATA_ORG_TOKEN`
3. **Polymarket** and **Football-Data.co.uk** need no account (public reads / static CSV)
4. **Crocobet** stays manual-CSV only; web automation is refused by design until a
   terms review is recorded in `config/source_policies.yaml`

Verify what the system thinks it may do:

```powershell
.\.venv\Scripts\python.exe -m academic_edge_worker.cli doctor
```

---

## Safety properties enforced in code

- No wagering, no wallet signing, no bookmaker credentials anywhere.
- `CROCOBET_WEB_ENABLED=true` is rejected at settings load, at the policy layer,
  by a pre-commit hook and by a CI job.
- Every provider-derived row carries `is_synthetic`; fixture venues are prefixed
  `FIXTURE:`.
- Every quote carries `source_id`, `observed_at`, `provider_timestamp`,
  `latency_ms` and `freshness`; every market carries its `settlement_rule` and
  `settlement_version`.
- CI includes a no-secrets guard and a read-only guard.

## Limitations (honest list)

- Research tooling, not a trading system. Quotes can be seconds-to-minutes old and
  the pricing layer refuses to call anything actionable when a leg is stale.
- Free provider tiers are small (API-Football: ~100 requests/day).
- Prediction-market mapping is deliberately partial: only unambiguous question text
  is mapped.
- Pre-match only; no in-play model.
- The Pages preview is static fixture data, not a live feed.
- Historical backtests include costs but not account limits or market impact, and
  imply nothing about future results.
