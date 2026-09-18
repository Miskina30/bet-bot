/* Static preview renderer. No framework, no build step, no network calls.
 * Mirrors the real dashboard's information architecture so the interface can be
 * reviewed on GitHub Pages before the API is deployed anywhere. */
(function () {
  "use strict";
  var F = window.AE_FIXTURES;

  function esc(v) {
    return String(v === null || v === undefined ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function bps(v) {
    if (v === null || v === undefined) return "n/a";
    return (v > 0 ? "+" : "") + v + " bps";
  }
  function age(s) {
    if (s === null || s === undefined) return "unknown";
    if (s < 60) return Math.round(s) + "s";
    if (s < 3600) return Math.round(s / 60) + "m";
    return Math.round(s / 3600) + "h";
  }
  function odds(v) { return v === null || v === undefined ? "n/a" : String(v); }
  function pct(v, d) {
    if (v === null || v === undefined) return "n/a";
    return (Number(v) * 100).toFixed(d === undefined ? 1 : d) + "%";
  }
  function money(v) { return v === null || v === undefined ? "—" : Number(v).toFixed(2); }
  function freshnessChip(f) {
    if (f === "stale") return '<span class="chip bad">stale</span>';
    if (f === "aging") return '<span class="chip warn">aging</span>';
    if (f === "fresh") return '<span class="chip ok">fresh</span>';
    return '<span class="chip">unknown</span>';
  }
  function sevChip(s) {
    if (s === "actionable") return '<span class="chip ok">actionable</span>';
    if (s === "watch") return '<span class="chip warn">watch</span>';
    return '<span class="chip">' + esc(s) + "</span>";
  }
  function statusChip(s) {
    if (s === "open") return '<span class="chip acc">open</span>';
    if (s === "acknowledged") return '<span class="chip ok">acknowledged</span>';
    if (s === "settled") return '<span class="chip ok">settled</span>';
    return '<span class="chip">' + esc(s) + "</span>";
  }
  function panel(title, subtitle, body) {
    return "<section class='panel'><div class='panel-head'><div><h2>" + esc(title) + "</h2>" +
      "<p>" + esc(subtitle) + "</p></div></div><div class='panel-body'>" + body + "</div></section>";
  }

  function viewOpportunities() {
    var rows = F.opportunities.map(function (o) {
      var legs = (o.best_legs || []).map(function (l) {
        return "<li><span class='chip'>" + esc(l.source_id) + "</span> " + esc(l.outcome_label) +
          " <span class='mono'>" + odds(l.decimal_odds) + "</span> " +
          "<span class='muted'>" + age(l.quote_age_seconds) + " old</span> " +
          freshnessChip(l.freshness) + "</li>";
      }).join("");
      var reasons = (o.reasons || []).concat(o.warnings || []).map(function (r) {
        return "<li>" + esc(r) + "</li>";
      }).join("");
      return "<tr>" +
        "<td><span class='chip " + (o.is_actionable ? "ok" : "warn") + "'>" + esc(o.opportunity_type) + "</span>" +
        (o.is_synthetic ? " <span class='chip'>synthetic</span>" : "") + "</td>" +
        "<td>" + esc(o.event_label) + "</td>" +
        "<td>" + esc(o.market_display_name) + "</td>" +
        "<td class='num'>" + bps(o.net_edge_bps) + "</td>" +
        "<td class='num muted'>" + bps(o.gross_edge_bps) + "</td>" +
        "<td class='num'>" + pct(o.confidence, 0) + "</td>" +
        "<td><ul style='margin:0;padding-left:14px;font-size:11px'>" + legs + "</ul></td>" +
        "<td class='num'>" + age(o.age_seconds) + "</td>" +
        "<td class='num'>" + money(o.liquidity) + "</td>" +
        "<td><ul class='reasons'>" + reasons + "</ul></td>" +
        "</tr>";
    }).join("");
    return panel("Opportunity board",
      "Arbitrage and model-vs-market value, with the friction that decides whether it is actionable.",
      "<div style='overflow-x:auto'><table><thead><tr>" +
      "<th>Type</th><th>Event</th><th>Market</th><th class='num'>Net edge</th>" +
      "<th class='num'>Gross</th><th class='num'>Confidence</th><th>Best legs</th>" +
      "<th class='num'>Age</th><th class='num'>Liquidity</th><th>Reason</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>");
  }

  function viewSources() {
    var rows = F.sources.map(function (s) {
      return "<tr>" +
        "<td><div>" + esc(s.display_name) + "</div><div class='mono muted'>" + esc(s.source_id) + "</div></td>" +
        "<td><span class='chip'>" + esc(s.mode) + "</span></td>" +
        "<td><span class='chip " + (s.ok ? "ok" : "bad") + "'>" + (s.ok ? "ok" : "failing") + "</span></td>" +
        "<td class='num'>" + (s.latency_ms === null ? "n/a" : s.latency_ms + " ms") + "</td>" +
        "<td class='num'>" + (s.quota_limit === null ? "not reported" : (s.quota_used || 0) + " / " + s.quota_limit) + "</td>" +
        "<td class='num'>" + (s.consecutive_failures || 0) + "</td>" +
        "<td class='num'>" + (s.parser_drift_count || 0) + "</td>" +
        "<td>" + esc(s.checked_at) + "</td>" +
        "<td><div>" + esc(s.message) + "</div>" +
        (s.terms_reviewed_by === null
          ? "<span class='chip warn'>terms review not recorded</span>"
          : "<span class='chip ok'>reviewed by " + esc(s.terms_reviewed_by) + "</span>") +
        "</td></tr>";
    }).join("");
    return panel("Source health",
      F.sources.length + " configured · " +
        F.sources.filter(function (s) { return s.ok; }).length + " healthy",
      "<div style='overflow-x:auto'><table><thead><tr>" +
      "<th>Source</th><th>Mode</th><th>Health</th><th class='num'>Latency</th>" +
      "<th class='num'>Quota</th><th class='num'>Failures</th><th class='num'>Drift</th>" +
      "<th>Last checked</th><th>Detail</th></tr></thead><tbody>" + rows + "</tbody></table></div>") +
      panel("When a source is degraded", "One-paragraph runbook",
        "<ol style='margin:0;padding-left:20px;font-size:11px' class='muted'>" +
        "<li>Confirm credential and quota state against the provider dashboard. Never retry past a 429.</li>" +
        "<li>Check parser drift: a non-zero count means the vendor changed a field, and the raw payload is archived.</li>" +
        "<li>If only fixtures are available, keep fixture mode and label it. Synthetic data is never presented as live.</li>" +
        "<li>Record the outcome in the audit log so the next analyst does not repeat the diagnosis.</li></ol>");
  }

  function viewAlerts() {
    var rows = F.alerts.map(function (a) {
      return "<tr><td>" + sevChip(a.severity) + "</td><td>" + statusChip(a.status) + "</td>" +
        "<td>" + esc(a.event_label) + "</td><td>" + esc(a.message) + "</td>" +
        "<td><span class='chip'>" + esc(a.rule) + "</span></td>" +
        "<td class='muted'>" + esc(a.raised_at) + "</td></tr>";
    }).join("");
    return panel("Alert inbox", F.alerts.length + " alerts (fixture data)",
      "<div style='overflow-x:auto'><table><thead><tr><th>Severity</th><th>Status</th>" +
      "<th>Event</th><th>Message</th><th>Rule</th><th>Raised</th></tr></thead><tbody>" +
      rows + "</tbody></table></div>");
  }

  function viewLedger() {
    var rows = F.ledger.map(function (e) {
      return "<tr><td>" + esc(e.event_label) + "</td><td><span class='chip'>" + esc(e.source_id) + "</span></td>" +
        "<td class='num'>" + money(e.stake) + "</td><td class='num mono'>" + odds(e.decimal_odds) + "</td>" +
        "<td>" + statusChip(e.status) + "</td>" +
        "<td class='num'>" + money(e.pnl) + "</td>" +
        "<td class='muted'>" + esc(e.placed_at) + "</td></tr>";
    }).join("");
    return panel("Paper ledger", "Research only — no real stake exists, ever",
      "<div style='overflow-x:auto'><table><thead><tr><th>Event</th><th>Source</th>" +
      "<th class='num'>Stake</th><th class='num'>Odds</th><th>Status</th>" +
      "<th class='num'>P&amp;L</th><th>Placed</th></tr></thead><tbody>" + rows + "</tbody></table></div>");
  }

  function viewPredictions() {
    var rows = F.predictions.map(function (p) {
      var expl = (p.explanation || []).map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("");
      return "<tr><td>" + esc(p.event_label) + "</td><td class='mono'>" + esc(p.model) + "</td>" +
        "<td><span class='chip'>" + esc(p.market_type) + "</span></td>" +
        "<td>" + esc(p.outcome_kind) + "</td>" +
        "<td class='num'>" + pct(p.probability, 1) + "</td>" +
        "<td class='num mono'>" + odds(p.fair_odds) + "</td>" +
        "<td class='num'>" + (p.uncertainty === null ? "n/a" : p.uncertainty) + "</td>" +
        "<td>" + (p.abstained
          ? "<span class='chip warn'>abstained</span>"
          : "<span class='chip ok'>active</span>") + "</td>" +
        "<td><ul class='reasons' style='color:rgb(var(--muted))'>" + expl + "</ul></td></tr>";
    }).join("");
    return panel("Model cards", "Walk-forward metrics and per-prediction explanations",
      "<div style='overflow-x:auto'><table><thead><tr><th>Event</th><th>Model</th><th>Market</th>" +
      "<th>Outcome</th><th class='num'>Probability</th><th class='num'>Fair odds</th>" +
      "<th class='num'>Uncertainty</th><th>State</th><th>Explanation</th></tr></thead><tbody>" +
      rows + "</tbody></table></div>");
  }

  var VIEWS = [
    { id: "opportunities", label: "Opportunities", render: viewOpportunities },
    { id: "sources", label: "Sources", render: viewSources },
    { id: "alerts", label: "Alerts", render: viewAlerts },
    { id: "ledger", label: "Paper ledger", render: viewLedger },
    { id: "predictions", label: "Models", render: viewPredictions }
  ];

  function render(id) {
    var view = VIEWS.filter(function (v) { return v.id === id; })[0] || VIEWS[0];
    document.getElementById("view").innerHTML = view.render();
    Array.prototype.forEach.call(document.querySelectorAll("#nav button"), function (b) {
      b.setAttribute("aria-current", b.getAttribute("data-id") === view.id ? "true" : "false");
    });
    if (location.hash !== "#" + view.id) {
      history.replaceState(null, "", "#" + view.id);
    }
  }

  function boot() {
    var nav = document.getElementById("nav");
    nav.innerHTML = VIEWS.map(function (v) {
      return "<button type='button' data-id='" + v.id + "'>" + esc(v.label) + "</button>";
    }).join("");
    nav.addEventListener("click", function (e) {
      var t = e.target;
      if (t && t.getAttribute && t.getAttribute("data-id")) render(t.getAttribute("data-id"));
    });
    if (F.fixture_mode) document.getElementById("fixtureBanner").classList.remove("hidden");
    render((location.hash || "").replace("#", "") || "opportunities");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();