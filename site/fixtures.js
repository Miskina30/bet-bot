/* Synthetic fixture data for the GitHub Pages static preview.
 * Every record is labelled synthetic. This is NOT live market data; the numbers
 * exist only to render the interface faithfully. */
window.AE_FIXTURES = {
  generated_at: "2026-09-18T12:00:00Z",
  fixture_mode: true,
  sources: [
    { source_id: "api_football", display_name: "API-Football (api-sports.io)", ok: true,
      mode: "fixture", checked_at: "2026-09-18T11:59:40Z", latency_ms: 42, quota_used: 12,
      quota_limit: 100, parser_drift_count: 0, consecutive_failures: 0, tier: "free",
      terms_reviewed_by: null,
      message: "fixture mode: labelled frozen payload, no network" },
    { source_id: "football_data_org", display_name: "football-data.org", ok: true,
      mode: "fixture", checked_at: "2026-09-18T11:59:41Z", latency_ms: 18, quota_used: null,
      quota_limit: null, parser_drift_count: 0, consecutive_failures: 0, tier: "free",
      terms_reviewed_by: null, message: "fixture mode: no odds capability by design" },
    { source_id: "polymarket_gamma", display_name: "Polymarket (Gamma + CLOB)", ok: true,
      mode: "fixture", checked_at: "2026-09-18T11:59:42Z", latency_ms: 65, quota_used: null,
      quota_limit: null, parser_drift_count: 0, consecutive_failures: 0, tier: "public_read",
      terms_reviewed_by: null, message: "public read; one venue, never ground truth" },
    { source_id: "football_data_uk", display_name: "Football-Data.co.uk (historical CSV)",
      ok: true, mode: "fixture", checked_at: "2026-09-18T11:59:43Z", latency_ms: 210,
      quota_used: null, quota_limit: null, parser_drift_count: 0, consecutive_failures: 0,
      tier: "public", terms_reviewed_by: null, message: "static CSV; refresh at most daily" },
    { source_id: "crocobet", display_name: "Crocobet", ok: false, mode: "fixture",
      checked_at: "2026-09-18T11:59:44Z", latency_ms: null, quota_used: null,
      quota_limit: null, parser_drift_count: 0, consecutive_failures: 1, tier: "manual",
  ],
  opportunities: [
    { id: "opp-0001", opportunity_type: "arbitrage", event_label: "Man Utd vs Man City",
      market_display_name: "Full-time 1X2", net_edge_bps: 148, gross_edge_bps: 205,
      confidence: 0.92, is_actionable: true, is_synthetic: true, detected_at: "2026-09-18T11:58:10Z",
      age_seconds: 42, liquidity: "2400.00", reasons: ["all legs fresh", "rules match across venues"],
      warnings: [], best_legs: [
        { source_id: "api_football", venue_name: "FIXTURE: Bookmaker Alpha", outcome_label: "Home",
          decimal_odds: "2.20", quote_age_seconds: 35, freshness: "fresh" },
        { source_id: "polymarket_gamma", venue_name: "FIXTURE: Polymarket", outcome_label: "Draw",
          decimal_odds: "3.55", quote_age_seconds: 48, freshness: "fresh" },
        { source_id: "api_football", venue_name: "FIXTURE: Bookmaker Alpha", outcome_label: "Away",
          decimal_odds: "3.30", quote_age_seconds: 35, freshness: "fresh" } ] },
    { id: "opp-0002", opportunity_type: "positive_ev", event_label: "Inter vs Juventus",
      market_display_name: "Full-time BTTS", net_edge_bps: 64, gross_edge_bps: 91,
      confidence: 0.61, is_actionable: true, is_synthetic: true, detected_at: "2026-09-18T11:57:02Z",
      age_seconds: 118, liquidity: "850.00",
      reasons: ["model 0.58 vs de-vigged market 0.52", "net edge survives 15 bps slippage"],
      warnings: ["model uncertainty 0.22 - monitor for lineup news"], best_legs: [
        { source_id: "polymarket_gamma", venue_name: "FIXTURE: Polymarket", outcome_label: "Yes",
          decimal_odds: "1.80", quote_age_seconds: 118, freshness: "aging" } ] },
    { id: "opp-0003", opportunity_type: "arbitrage", event_label: "Barcelona vs Real Madrid",
      market_display_name: "Full-time Over/Under 2.5", net_edge_bps: -12, gross_edge_bps: 18,
      confidence: 0.74, is_actionable: false, is_synthetic: true,
      detected_at: "2026-09-18T11:52:30Z", age_seconds: 402, liquidity: "120.00",
      reasons: ["gross edge existed before friction"],
      warnings: ["near miss: edge does not survive friction"],
      best_legs: [
        { source_id: "api_football", venue_name: "FIXTURE: Bookmaker Alpha", outcome_label: "Over",
          decimal_odds: "2.02", quote_age_seconds: 402, freshness: "stale" },
        { source_id: "polymarket_gamma", venue_name: "FIXTURE: Polymarket", outcome_label: "Under",
          decimal_odds: "1.98", quote_age_seconds: 402, freshness: "stale" } ] }
  ],
  alerts: [
    { id: "alert-0001", rule: "default_arb", severity: "actionable", status: "open",
      message: "Arbitrage cleared friction on Man Utd vs Man City (net 148 bps)",
      raised_at: "2026-09-18T11:58:12Z", event_label: "Man Utd vs Man City", is_synthetic: true },
    { id: "alert-0002", rule: "positive_ev_watch", severity: "watch", status: "open",
      message: "Model disagrees with market on Inter vs Juventus BTTS (64 bps net)",
      raised_at: "2026-09-18T11:57:05Z", event_label: "Inter vs Juventus", is_synthetic: true },
    { id: "alert-0003", rule: "stale_quote_guard", severity: "info", status: "acknowledged",
      message: "Stale quotes blocked an apparent arbitrage on Barcelona vs Real Madrid",
      raised_at: "2026-09-18T11:52:33Z", event_label: "Barcelona vs Real Madrid", is_synthetic: true }
  ],
  ledger: [
    { id: "led-0001", event_label: "Man Utd vs Man City", source_id: "api_football",
      stake: "25.00", decimal_odds: "2.20", status: "open", placed_at: "2026-09-18T11:58:20Z",
      pnl: null, is_synthetic: true },
    { id: "led-0002", event_label: "Inter vs Juventus", source_id: "polymarket_gamma",
      stake: "10.00", decimal_odds: "1.80", status: "settled", placed_at: "2026-09-17T18:00:00Z",
      pnl: "4.00", is_synthetic: true },
    { id: "led-0003", event_label: "Bayern vs Dortmund", source_id: "api_football",
      stake: "10.00", decimal_odds: "1.95", status: "settled", placed_at: "2026-09-16T18:00:00Z",
      pnl: "-10.00", is_synthetic: true }
  ],
  predictions: [
    { event_label: "Inter vs Juventus", model: "poisson_dc@0.1.0", market_type: "ft_btts",
      outcome_kind: "yes", probability: "0.580", fair_odds: "1.724", uncertainty: 0.22,
      abstained: false, market_free: true,
      explanation: ["attack/defence fitted on 380 weighted matches", "rho -0.05 low-score correction"] },
    { event_label: "Man Utd vs Man City", model: "elo_decay@0.1.0", market_type: "ft_1x2",
      outcome_kind: "home", probability: "0.402", fair_odds: "2.488", uncertainty: 0.31,
      abstained: true, market_free: true,
      explanation: ["abstained: uncertainty above 0.30 threshold"] }
  ]
};

