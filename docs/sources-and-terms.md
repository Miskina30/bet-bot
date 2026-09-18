# Sources, licences, quotas and terms review

This is the human-readable companion to `config/source_policies.yaml`, which is
the **machine-enforced** registry. If the two ever disagree, the YAML wins and
the code refuses to run (`PolicyViolation`).

Status of every source in the MVP, with the review state recorded honestly.

| Source | Tier | Auth | Documented quota | Automation scope | Terms review recorded? |
|---|---|---|---|---|---|
| API-Football (api-sports.io) | free | `x-apisports-key` header | Free plan: 100 requests/day (verify in dashboard) | official API only | **No** - operator must confirm |
| football-data.org v4 | free | `X-Auth-Token` header | Free tier: 10 requests/min, 12 competitions | official API only | **No** - operator must confirm |
| Polymarket Gamma | public read | none | undocumented; we self-limit to 60 req/min | documented public reads | **No** - operator must confirm |
| Polymarket CLOB + WebSocket | public read | none | undocumented; we self-limit to 120 req/min | documented public reads | **No** - operator must confirm |
| Football-Data.co.uk CSV | public | none | static files; refresh at most daily | bulk static download | **No** - operator must confirm |
| Crocobet | manual | operator-supplied CSV | n/a | **manual CSV only** | **No** - and web automation is hard-disabled |
| Labelled fixtures | synthetic | none | n/a | local fixtures | Yes (project-owned) |

`terms_reviewed_by` and `terms_reviewed_at` are `null` for every third party. That
is deliberate and load-bearing: the registry will not build a network client for a
`manual_csv_only` source without them, and CI asserts that Crocobet automation
stays disabled. A human must read the current terms, then set both fields in a
reviewed commit. Terms change; re-review before production use.

## What each source is used for

**API-Football** - primary live/odds source. Fixtures, results, lineups, injuries,
in-play prices. Bet IDs mapped in `academic_edge_connectors.api_football`:
`1` Match Winner -> `FT_1X2`, `5` Goals Over/Under -> `FT_TOTALS_2_5` (line 2.5),
`8` Both Teams Score -> `FT_BTTS`. Free-tier quota is small, so the adapter is
built to cache aggressively and to spend its daily budget on upcoming fixtures
rather than on bulk history.

**football-data.org** - secondary identity source: competitions, fixtures,
results and standings used to cross-check event resolution. It does not provide
odds, so `fetch_markets` returns an empty list and says so rather than inventing a
price.

**Polymarket (Gamma + CLOB)** - one more venue, never ground truth. Gamma is used
for event discovery and last price, CLOB for book depth and history, and the
public WebSocket for updates. Yes/No markets are mapped onto canonical markets
only when the question text is unambiguous (e.g. "both teams to score" ->
`FT_BTTS`); anything ambiguous is skipped and logged. Read-only: no wallet, no
order placement, no signing, no API keys.

**Football-Data.co.uk** - historical backbone. Closing odds (B365/PS/PS closing
columns) plus results drive the historical loader and walk-forward validation.
Public CSVs, refreshed at most once a day.

**Crocobet** - **manual CSV only in this MVP**. The operator exports a CSV, drops
it in `CROCOBET_CSV_DIR`, and the importer validates and loads it. There is no
HTTP/HTML client for Crocobet anywhere in this repository, the config layer
refuses `CROCOBET_WEB_ENABLED=true`, and a pre-commit hook plus CI job fail the
build if that changes. Enabling web automation requires: (1) recorded permission
or a written terms review, (2) `terms_reviewed_by` + `terms_reviewed_at` set in
the registry, (3) an `AuditLog` entry, and (4) an explicit code review.

**Labelled fixtures** - synthetic, project-owned demo data used when no provider
key is present. Every record is flagged `is_synthetic=true`, venues are prefixed
`FIXTURE:`, and the API/UI surface a "synthetic fixtures" banner. Fixture data is
never presented as a live market and is never used to claim an edge.

## Hard rules this project will not break

1. Official APIs and documented public feeds come first.
2. No bypassing login, CAPTCHA, robots directives, rate limits or anti-bot
   systems. Rate limits are implemented as a token bucket with backoff and are
   never disabled.
3. No automatic wagering, no wallet signing, and no stored bookmaker credentials
   in the MVP. `assert_read_only_intent()` and a CI guard enforce this.
4. Every alert is labelled with source, `observed_at`, `provider_timestamp`,
   latency, freshness and the settlement rule version.
5. No synthetic data is ever presented as live market data.
6. No promise of profit. Output is research evidence with explicit uncertainty,
   costs and failure modes.

## Known limitations

- **Latency**: this is a poll-and-cache research tool, not a low-latency trading
  system. Quotes may be seconds-to-minutes old; the pricing layer applies an
  explicit age haircut and refuses to call anything actionable when a leg is stale.
- **Liquidity**: available size is only as good as the venue reports it. Books
  thinner than the requested stake are flagged, not silently accepted.
- **Prediction-market mapping**: Polymarket questions are free text; only
  unambiguous ones are mapped. Coverage is intentionally partial.
- **No in-play model**: the MVP forecasts pre-match markets only.
- **Free-tier quotas**: API-Football's 100/day budget is not enough for broad
  live coverage. Expect to run on fixtures or on a paid tier in practice.
- **Backtests are not promises**: walk-forward results include costs but not
  account limits, market impact or account closure risk.
