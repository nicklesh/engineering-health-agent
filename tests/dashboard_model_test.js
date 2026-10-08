/* Dashboard model tests (Node, no dependencies). Run by tests/test_dashboard.py:
     node tests/dashboard_model_test.js <path to dashboard_data.js>
   Checks the brief's dashboard requirements: data loads, filters work, drill-down works,
   source records appear, and the numbers match the analysis. */
"use strict";
const assert = require("assert");
const path = require("path");

global.window = {};
require(path.resolve(process.argv[2]));
const M = require(path.resolve(__dirname, "../dashboard/js/model.js")).init(window.EHIS_DATA);
const D = M.data;
const results = [];
function test(name, fn) {
  try { fn(); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name, e.message]); }
}
const close = (a, b, tol = 0.011) => Math.abs(a - b) <= tol;
const tps = Object.keys(D.scopes).filter(s => D.scopes[s].type === "team_platform");

test("data loads", () => {
  assert.strictEqual(D.meta.n_weeks, 16);
  assert.ok(D.risks.length > 0 && D.recommendations.length > 0);
  assert.strictEqual(Object.keys(D.scopes).length, 20);
});

test("time filter: 4/8/12/16 weeks select the right window", () => {
  assert.deepStrictEqual(M.periodRange(4), [13, 16]);
  assert.deepStrictEqual(M.periodRange(8), [9, 16]);
  assert.deepStrictEqual(M.periodRange(12), [5, 16]);
  assert.deepStrictEqual(M.periodRange(16), [1, 16]);
  for (const n of [4, 8, 12, 16]) {
    const cards = M.kpiCards("org", n);
    assert.strictEqual(cards.length, 5);
    cards.forEach(c => assert.strictEqual(c.spark.length, n));
    assert.strictEqual(cards[0].value, D.kpi.org.overall.rolling[15]);
  }
});

test("time filter: comparison values are the mean of the selected weeks", () => {
  for (const n of [4, 16]) {
    const rows = M.compareTable("team", ["cycle_time_days", "defects"], n);
    rows.forEach(r => {
      const vals = D.series[r.scope].cycle_time_days.slice(16 - n);
      const expected = vals.reduce((a, b) => a + b, 0) / vals.length;
      assert.ok(close(r.cells.cycle_time_days.value, expected), `${r.scope} ${n}w`);
    });
  }
});

test("drill-down: KPI -> metrics -> team -> week -> record", () => {
  const metrics = M.kpiMetrics("org", "quality", 16);
  assert.ok(metrics.length >= 5 && metrics.every(m => D.metrics[m.metric].kpi === "quality"));
  const mv = M.metricView("org", "change_failure_rate_pct", 16, "team");
  assert.strictEqual(mv.children.length, 5);
  const team = M.metricView(mv.children.find(c => c.label === "Titan").scope, "change_failure_rate_pct", 16);
  assert.deepStrictEqual(team.children.map(c => c.scope).sort(), ["tp:Titan/Data", "tp:Titan/Web"]);
  const wk = M.weekRecords("team:Titan", "change_failure_rate_pct", 16);
  assert.ok(wk.events.length > 0);
  const rec = M.record(wk.events[0].id);
  assert.strictEqual(rec.dataset, "deployments");
  assert.strictEqual(rec.fields.week, 16);
});

test("source records reproduce every count and rate point (all team/platform weeks)", () => {
  tps.forEach(tp => {
    for (let w = 1; w <= 16; w++) {
      const dep = M.weekRecords(tp, "deployments", w);
      assert.strictEqual(dep.events.length, D.series[tp].deployments[w - 1], `${tp} W${w} deployments`);
      const def = M.weekRecords(tp, "defects", w);
      assert.strictEqual(def.events.length, D.series[tp].defects[w - 1], `${tp} W${w} defects`);
      const cfr = M.weekRecords(tp, "change_failure_rate_pct", w);
      const v = D.series[tp].change_failure_rate_pct[w - 1];
      if (cfr.events.length) assert.ok(close(100 * cfr.events.filter(e => e.highlight).length / cfr.events.length, v), `${tp} W${w} CFR`);
      const ct = M.weekRecords(tp, "cycle_time_days", w);
      assert.strictEqual(ct.weekly.length, 1);
      assert.strictEqual(M.record(ct.weekly[0]).fields.cycle_time_days, D.series[tp].cycle_time_days[w - 1]);
    }
  });
});

test("team-level points aggregate their team/platform records", () => {
  const wk = M.weekRecords("team:Atlas", "defects", 12);
  assert.strictEqual(wk.events.length, D.series["team:Atlas"].defects[11]);
  assert.strictEqual(wk.weekly.length, 2);
});

test("data-quality flags reach the record view; missing stays missing", () => {
  const r = M.record("WM-W06-ORION-SERVICES");
  assert.strictEqual(r.fields.test_coverage_pct, null);
  assert.ok(r.dq.some(q => q.rule === "schema"));
  assert.strictEqual(D.series["tp:Orion/Services"].test_coverage_pct[5], null);
});

test("evidence panel: every risk traces to resolvable source records", () => {
  M.risks().forEach(r => {
    const t = M.traceChain(r.id);
    assert.ok(t.records.length > 0, r.id);
    t.records.forEach(id => assert.ok(M.record(id), `${r.id}: ${id}`));
    assert.ok(["PASS", "WARN"].includes(t.validation));
  });
});

test("rejected findings never appear; narratives only for shown findings", () => {
  const rejected = new Set(D.rejected.map(r => r.id));
  Object.keys(D.findings).forEach(id => assert.ok(!rejected.has(id), id));
  Object.values(D.findings).forEach(f => (f.possible_explanations || []).forEach(h => assert.ok(!rejected.has(h), h)));
  Object.keys(D.narratives).forEach(id => assert.ok(D.findings[id], id));
});

test("risks are ordered by rank and recommendations by priority", () => {
  const ranks = M.risks().map(r => r.rank);
  assert.deepStrictEqual(ranks, ranks.slice().sort((a, b) => a - b));
  const p = M.recommendations().map(r => r.priority);
  assert.deepStrictEqual(p, p.slice().sort());
});

test("formatting", () => {
  assert.strictEqual(M.formatValue(27.059, "%"), "27.1%");
  assert.strictEqual(M.formatValue(4.525, "days"), "4.5 d");
  assert.strictEqual(M.formatValue(null, "%"), "n/a");
});

results.forEach(r => console.log(r.join(" | ")));
process.exit(results.some(r => r[0] === "FAIL") ? 1 : 0);
