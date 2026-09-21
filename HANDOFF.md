# ACADEMIC EDGE — HANDOFF / CONTEXT COMPRESS

Read this first in any new session. Everything below is ground truth from the build.

## WHAT THIS PROJECT IS
"Academic Edge" — a **read-only football market-intelligence MVP**. Ingests permitted
sports data, resolves provider entities into a canonical model, compares equivalent
markets across venues, computes arbitrage + model-vs-market EV, and surfaces
evidence-rich alerts. **It never places bets, never signs wallets, never stores
bookmaker credentials.** Authoritative spec: `Downloads/academic-edge-agent-brief.md`.

## ENVIRONMENT (this machine)
- OS: Windows, shell is **PowerShell** (bash syntax like `||`, `&&`, `head`, `find -name` FAILS here — use PowerShell-native cmdlets or plain `python` one-liners).
- Python 3.12 at `C:\Users\Anania Light Laptop\Downloads\Blue Ocean\.tools\python\python.exe`; project venv at `<repo>\.venv` (`.venv\Scripts\python.exe`).
- **Node.js / npm: NOT installed** (web app cannot be built/run here).
- **Docker: NOT installed** (compose stack cannot run here).
- **git: NOT on PATH** (repo is not a git repo yet).
- Repo root: `C:\Users\Anania Light Laptop\projects\academic-edge`.

## REPO LAYOUT (mirror of the brief)
```
apps/api/academic_edge_api/        FastAPI service (/v1/*, roles, SSE)
apps/worker/academic_edge_worker/  seed.py, cli.py (pipeline.py is the open gap)
apps/web/                          Next.js 15 dashboard (lib + config done, pages partial)
packages/domain/                   canonical model (27 tables), policy, settings
packages/connectors/               5 provider adapters + fixtures + contract tests
packages/pricing/                  odds, de-vig, arb, staking, value, friction
packages/resolver/                 normalize, similarity, matcher (golden set)
packages/features/                 form.py, strength.py (point-in-time, leakage guard)
packages/forecasting/              elo.py, poisson.py, evaluate.py
config/source_policies.yaml        machine-enforced registry (Crocobet gated OFF)
docs/sources-and-terms.md          source licences, quotas, review state, limitations
migrations/                        alembic env + initial canonical migration
tests/{unit,golden,contract,fixtures}/   64+ tests, ALL PASSING
```

## VERIFIED WORKING (tests green)
`& .venv\Scripts\python.exe -m pytest -q` → **64 passed** (pricing unit incl. Hypothesis
property invariants, resolver golden set with adversarial traps incl. zero false
auto-accepts, connector contract tests incl. ParserDriftError on renamed vendor fields,
`ruff check` → clean.

## KEY DESIGN FACTS (so you don't re-derive them)
- Pricing works in **Decimal**, pure functions, `detect_arbitrage` equalises stakes to
  the cent with venue-minimum handling; power + multiplicative de-vig both sum to 1.
- Resolver: participant threshold **0.85** (post alias canonicalisation "Man Utd" →
  "manchester united"); auto-accept ≥ 0.985 with zero hard rejects; 0.940–0.985 →
  review. Optional components (venue/round) renormalise weight so providers omitting
  them can still auto-accept.
- Normalisation ORDER matters: alias phrases FIRST, then noise-token strip, then
  abbreviation expansion ("Athletic Bilbao" and "Athletic Club" must converge).
- Every provider row carries `is_synthetic`; fixture venues prefixed `FIXTURE:`.
- Crocobet web automation is hard-refused at settings load AND policy layer AND CI.
- Web lib (`apps/web/src/lib/*`) complete and typed: api.ts (ApiResult<T>, Page<T>),
  schemas.ts (zod), queries.ts (TanStack hooks), derive.ts, format.ts, sources.ts,
  theme.ts, use-sse.ts. `Page<T>` fields: items, next_cursor, generated_at,
  fixture_mode, stale, partial, sources_failed.

## OPEN WORK (next slices, in order)
1. `apps/web/src/app/`: layout.tsx + components/StateBlocks.tsx DONE; page.tsx
   (opportunity board) DONE; **sources/page.tsx DONE** (render body completed
   2026-09-18). Still missing: alerts/page.tsx,
   resolver/page.tsx (+ [id]/decision), predictions/page.tsx, ledger/page.tsx,
   opportunities/[id]/page.tsx detail, analyst-proxy route handlers
   (api/alerts/[id]/acknowledge/route.ts, api/resolver/[id]/decision/route.ts),
   components/{FreshnessBadge,DataTable,ThemeToggle,SourceChip,EvidencePanel}.tsx,
   e2e/dashboard.spec.ts + playwright.config.ts, web Dockerfile.
2. `apps/worker/academic_edge_worker/`: seed.py exists (partial), cli.py exists
   (partial). Missing: pipeline.py (archive→normalize→resolve→snapshots→
   opportunities→alerts→ledger, deterministic/in-memory), jobs.py, scheduler.py,
   archive.py; `tests/integration/` is EMPTY.
3. `tests/leakage/` — point-in-time feature guard test (strength.py raises on
   future-dated observations) + walk-forward smoke test. Directory missing.
4. `tests/property/` directory for hypothesis pricing invariants (currently inside
   tests/unit files).
5. Migrations: `migrations/versions/c244a4254cb9_initial_canonical_schema.py` exists —
   verify `alembic upgrade head` on temp SQLite, then downgrade, then up again.
6. README "Delivery order" section: update statuses to match reality.

## RUN / DEV COMMANDS (PowerShell, from repo root)
```powershell
& .venv\Scripts\python.exe -m pytest -q          # 64 passed
& .venv\Scripts\python.exe -m ruff check .       # clean
& .venv\Scripts\python.exe -m alembic upgrade head
& .venv\Scripts\python.exe -m academic_edge_worker.cli seed
& .venv\Scripts\python.exe -m uvicorn academic_edge_api.main:app --reload --port 8000
```
Makefile targets exist (install/lint/test/migrate/seed/api/demo) but `make` may not be
on PATH on this machine — use the python -m forms above.

## CREDENTIALS / SECURITY (do this first, always)
- `gensweaty@gmail.com` / the password shared in chat: **that password must be rotated
  and 2FA enabled.** It was pasted in cleartext; never write it to any file, never
  commit it, never echo it. No provider account was created with it.
- Provider keys (API-Football, football-data.org) are free-tier signups the USER does
  manually; keys go into `.env` only (already git-ignored). Without keys the system
  runs in labelled FIXTURE mode (synthetic, venue names prefixed `FIXTURE:`).
- `.env` must never be committed. CI has a no-secrets guard job.

## SIGNUP STEPS FOR THE USER (manual, ~2 min each)
1. API-Football: dashboard.api-football.com/register → copy key → `.env` `API_FOOTBALL_KEY=...`
2. football-data.org: football-data.org/client/register → token → `.env` `FOOTBALL_DATA_ORG_TOKEN=...`
3. Polymarket reads + Football-Data.co.uk CSVs need NO account.
4. Crocobet: operator CSV export only; automation stays disabled by design.

