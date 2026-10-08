/* Dashboard model: every number the page shows comes through these functions.
   No DOM access here, so the same code is tested in Node (tests/dashboard_model_test.js)
   and used in the browser. The data is window.EHIS_DATA, built by Agent 09. */
(function (root) {
  "use strict";
  let D = null;

  function init(data) { D = data; return api; }

  // ---------- helpers ----------
  function round(v, d) { if (v === null || v === undefined) return null; const f = Math.pow(10, d); return Math.round(v * f) / f; }
  function mean(arr) { const v = arr.filter(x => x !== null && x !== undefined); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; }

  function periodRange(n) {
    const total = D.meta.n_weeks;
    const w = Math.min(Math.max(n, 1), total);
    return [total - w + 1, total];
  }
  function slice(values, range) { return values.slice(range[0] - 1, range[1]); }

  function formatValue(v, unit, digits) {
    if (v === null || v === undefined) return "n/a";
    const d = digits === undefined ? (Math.abs(v) >= 100 ? 0 : 1) : digits;
    const s = (round(v, d)).toLocaleString("en-US", { maximumFractionDigits: d });
    if (unit === "%") return s + "%";
    if (unit === "count" || unit === "items" || unit === "people") return s;
    const short = { days: "d", hours: "h", minutes: "min", LOC: "LOC" }[unit] || unit;
    return s + " " + short;
  }

  function matches(record, where) {
    for (const k in where) {
      const want = where[k];
      if (Array.isArray(want)) { if (want.indexOf(record[k]) < 0) return false; }
      else if (record[k] !== want) return false;
    }
    return true;
  }

  // ---------- scopes ----------
  function scope(id) { return D.scopes[id]; }
  function scopesOfType(type) { return Object.keys(D.scopes).filter(id => D.scopes[id].type === type); }
  function childScopes(id, by) {
    const s = D.scopes[id];
    if (s.type === "org") return scopesOfType(by === "platform" ? "platform" : "team");
    if (s.type === "team_platform") return [];
    return s.pairs.map(p => "tp:" + p);
  }

  // ---------- KPIs ----------
  function kpiCards(scopeId, n) {
    const r = periodRange(n);
    return Object.keys(D.meta.kpi_labels).map(key => {
      const roll = D.kpi[scopeId][key].rolling;
      const now = roll[r[1] - 1], start = roll[r[0] - 1];
      return { key, label: D.meta.kpi_labels[key], value: now, start,
               delta: (now !== null && start !== null) ? round(now - start, 1) : null,
               spark: slice(roll, r), band: band(now) };
    });
  }
  function band(score) {
    if (score === null || score === undefined) return "unknown";
    if (score >= 75) return "healthy";
    if (score >= 60) return "watch";
    return "at-risk";
  }
  function kpiMetrics(scopeId, kpiKey, n) {
    const r = periodRange(n);
    return Object.keys(D.metrics)
      .filter(m => kpiKey === "overall" ? D.metrics[m].kpi : D.metrics[m].kpi === kpiKey)
      .map(m => {
        const c = (D.classifications[scopeId] || {})[m] || {};
        return { metric: m, label: D.metrics[m].label, unit: D.metrics[m].unit, kpi: D.metrics[m].kpi,
                 score: round(mean(slice(D.metric_scores[scopeId][m], r)), 1),
                 value: periodMean(scopeId, m, n), classification: c.classification || "n/a",
                 finding: c.finding_id || null };
      })
      .sort((a, b) => (a.score === null) - (b.score === null) || a.score - b.score);
  }

  // ---------- metrics ----------
  function periodMean(scopeId, metric, n) {
    return round(mean(slice(D.series[scopeId][metric], periodRange(n))), 2);
  }
  function anomaliesFor(scopeId, metric) {
    return Object.values(D.findings).filter(f => f.type === "anomaly" && f.metrics[0] === metric &&
      (f.dimension.scope === scopeId || (f.also_visible_in || []).indexOf(scopeId) >= 0));
  }
  function metricView(scopeId, metric, n, by) {
    const c = (D.classifications[scopeId] || {})[metric] || {};
    const children = childScopes(scopeId, by).map(id => ({
      scope: id, label: D.scopes[id].label, value: periodMean(id, metric, n),
      classification: ((D.classifications[id] || {})[metric] || {}).classification || "n/a" }));
    return { scope: scopeId, metric, meta: D.metrics[metric], values: D.series[scopeId][metric], range: periodRange(n),
             periodMean: periodMean(scopeId, metric, n), classification: c,
             trend: c.finding_id ? D.findings[c.finding_id] : null, anomalies: anomaliesFor(scopeId, metric), children };
  }

  // ---------- drill-down to source records ----------
  function weekRecords(scopeId, metric, week) {
    const s = D.scopes[scopeId], m = D.metrics[metric], d = m.derive;
    const weekly = s.pairs.map(p => {
      const [t, pl] = p.split("/");
      return "WM-W" + String(week).padStart(2, "0") + "-" + t.toUpperCase() + "-" + pl.toUpperCase();
    }).filter(id => D.records.weekly_metrics[id]);
    let events = [], dataset = null, where = null;
    if (d.kind !== "weekly_field") {
      dataset = d.dataset;
      where = d.kind === "event_ratio" ? d.numerator : (d.where || {});
      s.pairs.forEach(p => {
        const ids = (((D.record_index[p] || {})[String(week)] || {})[dataset]) || [];
        ids.forEach(id => {
          const rec = D.records[dataset][id];
          const inDen = d.kind === "event_ratio" ? matches(rec, d.denominator) : (d.kind === "event_count" ? true : rec[d.field] !== null);
          if (!inDen && d.kind !== "event_count") return;
          events.push({ id, dataset, highlight: d.kind === "event_mean" ? true : matches(rec, where), included: d.kind !== "event_count" || matches(rec, where) });
        });
      });
      if (d.kind === "event_count") events = events.filter(e => e.included);
    }
    return { scope: scopeId, metric, week, value: D.series[scopeId][metric][week - 1], meta: m,
             field: d.kind === "weekly_field" ? d.field : null, weekly, dataset, events,
             explanation: explain(m, d) };
  }
  function explain(m, d) {
    if (d.kind === "weekly_field") return `${d.agg === "sum" ? "Sum" : "Mean"} of '${d.field}' over the weekly rows below.`;
    if (d.kind === "event_count") return `Count of ${d.dataset} records${Object.keys(d.where).length ? " where " + JSON.stringify(d.where) : ""}.`;
    if (d.kind === "event_ratio") return `100 x highlighted / all ${d.dataset} records listed (highlighted = ${JSON.stringify(d.numerator)}).`;
    return `Mean of '${d.field}' over the ${d.dataset} records below.`;
  }
  function record(id) {
    for (const ds in D.records) {
      if (D.records[ds][id]) return { id, dataset: ds, fields: D.records[ds][id], dq: D.dq_flags[id] || [] };
    }
    return null;
  }

  // ---------- comparison ----------
  function compareTable(type, metrics, n) {
    const ids = scopesOfType(type);
    const rows = ids.map(id => ({ scope: id, label: D.scopes[id].label, cells: {} }));
    metrics.forEach(m => {
      const pol = D.metrics[m].polarity;
      const vals = rows.map(r => periodMean(r.scope, m, n));
      const sorted = vals.filter(v => v !== null).slice().sort((a, b) => a - b);
      const med = sorted.length ? (sorted.length % 2 ? sorted[(sorted.length - 1) / 2] : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2) : null;
      rows.forEach((r, i) => {
        const v = vals[i];
        let rel = null;
        if (v !== null && med) rel = (pol === "lower_is_better" ? (med - v) : (v - med)) / Math.abs(med);
        const order = vals.filter(x => x !== null).slice().sort((a, b) => pol === "lower_is_better" ? a - b : b - a);
        r.cells[m] = { value: v, relative: rel === null ? null : round(rel, 3), rank: v === null ? null : order.indexOf(v) + 1,
                       classification: ((D.classifications[r.scope] || {})[m] || {}).classification || "n/a" };
      });
    });
    return rows;
  }

  // ---------- findings ----------
  function finding(id) { return D.findings[id] || null; }
  function risks() { return D.risks.map(id => D.findings[id]); }
  function recommendations() { return D.recommendations.map(id => D.findings[id]); }
  function narrative(id) { return D.narratives[id] || null; }
  function recommendationFor(riskId) {
    return recommendations().find(r => (r.related_findings || []).indexOf(riskId) >= 0) || null;
  }
  function traceChain(riskId) {
    const r = D.findings[riskId];
    const primary = (r.primary_refs || []).map(id => D.findings[id]).filter(Boolean);
    const rec = recommendationFor(riskId);
    return {
      insight: r.id, metrics: r.metrics, scope: r.dimension.scope,
      datasets: Array.from(new Set(primary.map(f => (f.evidence && f.evidence.dataset) || "metric_series"))),
      records: Array.from(new Set(primary.flatMap(f => (f.evidence && f.evidence.record_ids) || []))),
      calculations: primary.map(f => ({ id: f.id, text: f.evidence.calculation })),
      agents: Array.from(new Set(primary.map(f => f.id.startsWith("ANO") ? "05_anomaly_detection" : "04_trend_analysis").concat(["06_risk_analysis"]))),
      validation: r.verdict, caveats: r.caveats, recommendation: rec ? rec.id : null,
    };
  }

  const api = { init, periodRange, formatValue, matches, scope, scopesOfType, childScopes, kpiCards, band, kpiMetrics,
                periodMean, metricView, anomaliesFor, weekRecords, record, compareTable, finding, risks, recommendations,
                narrative, recommendationFor, traceChain, mean, round, get data() { return D; } };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.EHISModel = api;
})(typeof window !== "undefined" ? window : this);
