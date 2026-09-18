environment variable, nothing is baked into an image, and the API/worker images
run as a non-root user.

## Quick start (no keys required)

Full instructions, including the Docker profile and how to add live provider keys:
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q          # 64 tests
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m academic_edge_worker.cli seed
.\.venv\Scripts\python.exe -m uvicorn academic_edge_api.main:app --reload --port 8000
```

**Static UI preview:** <https://miskina30.github.io/bet-bot/> — a rendered
snapshot of the dashboard using labelled synthetic fixtures. GitHub Pages serves
static files only, so the Python API is not running there; see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for why, and for how to run the real stack.

## Repository layout

```
academic-edge/
├─ apps/
│  ├─ api/      academic_edge_api/      FastAPI service: /v1/*, cursor pagination, roles, SSE
│  ├─ worker/   academic_edge_worker/   ingest pipeline, raw archive, jobs, CLI, local scheduler
│  └─ web/                              Next.js 15 App Router dashboard (TS strict, Tailwind)
├─ packages/
│  ├─ domain/       academic_edge_domain/       canonical model, enums, UTC types, settings, policy
│  ├─ connectors/   academic_edge_connectors/   provider adapters + DTOs + contract fixtures
│  ├─ resolver/     academic_edge_resolver/     normalisation, similarity, event matching
│  ├─ pricing/      academic_edge_pricing/      odds, de-vig, arbitrage, staking, value, friction
│  ├─ features/     academic_edge_features/     point-in-time feature building
│  └─ forecasting/  academic_edge_forecasting/  Elo, Poisson/Dixon-Coles, walk-forward evaluation
├─ config/source_policies.yaml     source registry (machine-enforced)
├─ docs/                           sources & terms review, runbooks
├─ migrations/                     Alembic (dialect-neutral: SQLite + Postgres 16)
├─ tests/{unit,property,golden,contract,api,e2e,fixtures}
├─ infra/docker/                   api/worker and web images
└─ docker-compose.yml, Makefile, .github/workflows/ci.yml, .pre-commit-config.yaml
```

Each leaf directory under `apps/` and `packages/` is an independently importable
package; `pyproject.toml` maps them explicitly so `pip install -e .` stays
deterministic, and `pytest` sets `pythonpath` so tests run without installing.

## Data flow

```
providers ─► adapter (policy-gated) ─► raw archive (append-only, content-addressed)
                   │                             │
                   │                             └─► raw_payload index row (provenance)
                   ▼
            normalise ─► event/market resolver ─► canonical Event / Market / Outcome
                   │            │
                   │            └─► auto-accept ≥ 0.985 · review 0.940–0.985 · else reject
                   ▼
                Quote ─► QuoteSnapshot (point-in-time, de-vigged fair probabilities)
                   │
                   ├─► arbitrage + model-vs-market EV ─► Opportunity (+ friction, warnings)
                   └─► alert rules ─► Alert (deduped) ─► SSE stream ─► web dashboard
                                                └─► paper ledger (research only)
```

Nothing on that path can place a bet: there is no order-placement code, no wallet
code and no bookmaker-credential handling anywhere in the repository.

## Canonical model

27 tables implement the brief's model: `sport`, `competition`, `season`,
`participant`, `participant_alias`, `venue`, `event`, `provider_event_map`,
`market`, `outcome`, `quote`, `quote_snapshot`, `raw_payload`, `ingest_run`,
`source_health_snapshot`, `injury_availability`, `lineup`, `feature_snapshot`,
`model_version`, `prediction`, `opportunity`, `alert_rule`, `alert`,
`settlement`, `paper_ledger_entry`, `audit_log`, `source_policy`.

Design decisions worth knowing:

- **Market identity** = event + `market_type` + `period` + `line_value` +
  `team_scope` + `overtime_included` + `settlement_version`, hashed into
  `identity_key`, so two providers are only compared when they truly agree.
  Line-less markets store `line_value = 0` rather than NULL, because SQL treats
  NULLs as distinct and a unique constraint would then silently allow duplicates.
- **Enums are strings** (`native_enum=False`), so SQLite, CI Postgres and
  production Postgres 16 behave identically and adding a value needs no DDL.
- **All timestamps are UTC** through a `UtcDateTime` type decorator that
  re-attaches UTC on load (SQLite drops tzinfo).
- **`is_synthetic`** is a first-class column on every row that can hold provider
  data, so fixture data can never be mistaken for a live market.

## Matching (resolver)

Same sport and competition, kickoff inside a bounded window
(`RESOLVER_TIME_WINDOW_MINUTES`, default 180), then a weighted score:

| Component | Weight | Notes |
|---|---|---|
| Participant names | 0.55 | Unicode-folded, club-noise tokens removed, then Jaro-Winkler blend |
| Kickoff time | 0.20 | linear decay across the window |
| Competition | 0.15 | normalised name similarity |
| Venue | 0.05 | optional |
| Round label | 0.05 | optional |

**Hard rejects** (never auto-accepted, whatever the score): sport mismatch,
competition mismatch, start time outside the window, home/away inversion,
participant mismatch, and any conflict in period, line, overtime inclusion or
settlement version. Auto-accept needs score ≥ `0.985` **and** zero hard rejects;
`0.940–0.985` goes to human review. Evidence (component scores, time delta,
normalised names, reject reasons) is persisted on `provider_event_map`, and the
golden set in `tests/golden` includes adversarial traps such as Manchester United
vs Manchester City and Internazionale vs Inter Miami. The target is ≥ 99.5%
precision on auto-accepted pairs, measured by the golden test.

## Pricing

- Decimal odds throughout, with an explicit `Decimal` context, so results are
  reproducible and property tests can assert exact invariants.
- **De-vig**: `multiplicative` (proportional normalisation) and `power` (solve
  `Σp_i^k = 1` by bisection, then renormalise and record the residual). Both are
  estimators, so every result records the method, the input book and the achieved
  residual rather than pretending to be exact.
- **Arbitrage**: `index = 1 − Σ(1/effective_odds)`, where exchange commission is
  applied as `1 + (odds−1)(1−c)`. Stakes are equalised so every leg pays the same
  amount; a requested stake that would breach a venue minimum is raised to the
  smallest compliant amount, and that adjustment is reported, not silently applied.
- **Friction** (bps, conservative defaults): slippage, exchange fee, FX spread and
  a quote-age haircut that grows with staleness and is capped. A quote older than
  `PRICING_MAX_QUOTE_AGE_SECONDS` can never be actionable.
- **Actionable** means: every leg fresh, settlement rules match, quoted size
  covers the stake, and the net edge still clears `PRICING_MIN_NET_EDGE_BPS`.
  Everything else is reported as a near-miss *with the reason*, which is the whole
  point of the opportunity board.

Property tests assert the invariants the brief calls out: de-vigged probabilities
sum to one; arbitrage payouts equalise; no negative stakes; stale quotes never
alert; net edge never exceeds gross edge.

## Forecasting

Two baseline families, so the value of each addition is measurable rather than
assumed:

- **Market-free**: time-decayed Elo with a home-advantage term and an explicit
  draw model, plus Poisson / Dixon-Coles attack-defence fitted by weighted
  maximum likelihood (the low-score dependency parameter ρ is estimated
  separately instead of being assumed to be 0).
- **Market-aware**: de-vigged multi-venue consensus, used both as a feature and as
  the benchmark the model must beat before anything is called value.

Point-in-time features: opponent-adjusted decayed form, rest and congestion,
home advantage, injuries/suspensions, expected and confirmed XI strength,
formation continuity, and low-weight decayed H2H. `build_feature_vector` refuses
to accept any observation timestamped after its `as_of`, which is what makes the
leakage test meaningful.

Evaluation is walk-forward (expanding window, strictly ordered), reporting
multiclass log loss, Brier, RPS, calibration/ECE, CLV, net ROI, turnover and max
drawdown, with calibration fitted on a *later* temporal window than training. The
pipeline abstains when uncertainty is high rather than dressing up noise as signal.

## API

All routes are under `/v1`, read-only except two analyst acknowledgements, with
cursor pagination (`?cursor=`) and an envelope of
`{"items": [...], "next_cursor": ..., "partial": bool}`.

| Route | Role | Notes |
|---|---|---|
| `GET /v1/health` | reader | liveness + mode + fixture/live banner |
| `GET /v1/sources/health` | reader | per-source ok, latency, quota, parser drift, mode |
| `GET /v1/events`, `GET /v1/events/{id}` | reader | filters by competition, date window, status |
| `GET /v1/markets` | reader | canonical definition incl. `settlement_version` |
| `GET /v1/quotes/latest` | reader | best price per outcome + `age_seconds`, latency, freshness |
| `GET /v1/opportunities`, `GET /v1/opportunities/{id}` | reader | filters: type, `min_net_edge_bps`, `actionable_only` |
| `GET /v1/resolver/review`, `POST .../{id}/decision` | reader / analyst | evidence-rich queue, manual link |
| `GET /v1/predictions/{event_id}` | reader | model probability, uncertainty, abstention reason |
| `GET /v1/models/metrics` | reader | walk-forward metrics per registered model |
| `GET /v1/alerts`, `POST /v1/alerts/{id}/acknowledge` | reader / analyst | deduped evidence snapshot |
| `GET /v1/paper-ledger` | reader | research ledger; clearly labelled as paper |
| `GET /v1/stream/opportunities` | reader | SSE, heartbeat, resumable via `Last-Event-ID` |

Authentication is an `X-API-Key` header mapped to `reader < analyst < admin`. With
no keys configured the service runs in an explicit dev mode and sets
`X-Academic-Edge-Dev-Auth: true` so it can never be mistaken for a secured
deployment. SSRF/injection risk is low by construction: no endpoint accepts a URL,
and every response is built from the canonical model, never a passthrough of raw
provider bytes.

## UI

`apps/web` is a Next.js 15 App Router dashboard (TypeScript strict, Tailwind,
TanStack Query v5 + Table v8): opportunity board, opportunity detail, source
health, resolver review, predictions/model card, alerts and the paper ledger.
Light/dark, keyboard accessible, responsive, and no decorative gambling imagery.

Every screen implements five explicit states - loading, empty, stale,
partial-source and error - because the honest answer to "what is this number?"
usually includes "one source did not answer". Every number is rendered next to
its source, `observed_at` and freshness; a stale row is visually distinct and its
reason is shown, and a synthetic-fixtures banner appears whenever the backend
reports fixture mode. Live updates arrive over SSE.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -q                 # everything
.\.venv\Scripts\python.exe -m pytest -m property -q     # hypothesis invariants
.\.venv\Scripts\python.exe -m pytest -m golden -q       # matcher golden set
.\.venv\Scripts\python.exe -m pytest -m contract -q     # frozen provider payloads
.\.venv\Scripts\python.exe -m pytest -m leakage -q      # point-in-time / walk-forward
```

| Suite | What it proves |
|---|---|
| `tests/unit` | conversions, de-vig, arbitrage, EV, staking, friction, Elo/Poisson, metrics |
| `tests/property` | pricing invariants (probabilities sum to 1, payouts equalise, no negative stakes, stale never alerts) |
| `tests/contract` | adapters still parse frozen, redacted provider payloads; drift raises instead of inventing fields |
| `tests/golden` | matcher golden set with adversarial false-positive traps; ≥ 99.5% precision on auto-accepts |
| `tests/leakage` | `as_of` guard and expanding-window walk-forward cannot see the future |
| `tests/api` | roles, cursor pagination, 404s, SSE, no secret leakage (ephemeral SQLite) |
| `tests/e2e` | Playwright: review → opportunity → alert (needs Node + a running stack) |

## Observability and operations

- **Logs**: structured JSON with `correlation_id`, `source`, `event_id` and
  `latency_ms`, so a single ingest can be traced end to end.
- **Metrics**: ingestion lag, adapter errors, parser drift, unmatched rate, stale
  quotes, alerts raised.
- **Traces**: OpenTelemetry-ready instrumentation points in the API and worker.
- **Raw archive**: append-only and content-addressed; re-fetching different bytes
  creates a *new* object rather than overwriting, which is what makes replay and
  audit possible.
- **Dead-letter handling**: failed ingest items are retained with their raw
  payload reference and retried from the CLI; `docs/runbook.md` covers the common
  failures (quota exhausted, parser drift, unmatched rate spike, stale-quote storm).

## Configuration

Everything is an environment variable (see `.env.example` for the annotated list):
`DATABASE_URL`, `REDIS_URL`, `RAW_ARCHIVE_BACKEND` (+ S3 vars), `API_KEYS`,
provider keys/tokens, `RESOLVER_*` thresholds, `PRICING_*` frictions, `MODEL_*`.
`CROCOBET_WEB_ENABLED` may only be `false` in this build: setting it true makes
configuration loading fail fast.

## Limitations

- Research tool, not a trading system: quotes can be seconds-to-minutes old and the
  pricing layer refuses to call anything actionable when a leg is stale.
- Free provider tiers are small (API-Football: 100 requests/day). Broad live
  coverage needs a paid tier or fixture/replay mode.
- Prediction-market mapping is deliberately partial: only unambiguous question
  text is mapped, everything else is skipped and logged.
- Pre-match only; no in-play model.
- Liquidity is only as good as each venue reports it. Thin books are flagged.
- Walk-forward results include costs but not account limits, market impact or
  account-closure risk. **No historical performance implies future results.**
- The terms review for every third-party source is still `null` in
  `config/source_policies.yaml`: complete it before any production use.

## Delivery order from the brief

1. Scaffold + Compose + CI + migrations - done
2. Domain model + source policy registry - done
3. API-Football and football-data.org adapters with contract fixtures - delegated/in progress
4. Polymarket public read adapter and streams - delegated/in progress
5. Raw archive + normalisation + health dashboard - in progress
6. Event/market resolver and review UI - in progress
7. Manual Crocobet importer - in progress
8. Pricing engine and opportunity board - de-vig done, arb/EV/friction in progress
9. Historical loader + Poisson/Elo + walk-forward report - delegated, retry required
10. Alerts and four-week paper-trading mode - in progress

Each slice lands with its own tests; nothing is marked done until its suite runs
green. Where a slice is still in progress it says so above rather than being
described as finished.