/* Dashboard rendering. All numbers come from EHISModel (model.js); this file only lays them out. */
(function () {
  "use strict";
  if (!window.EHIS_DATA) {
    // Fail loudly: never render an empty or partial dashboard that looks valid.
    document.querySelector("main").innerHTML = `<div class="panel fatal"><h2>Dashboard data not loaded</h2>
      <p>The file <code>dashboard/data/dashboard_data.js</code> is missing or failed to load. Run <code>python run.py</code>
      from the project root, then reload this page. If you are serving the folder, check the server is still running.</p></div>`;
    return;
  }
  const M = EHISModel.init(window.EHIS_DATA);
  const C = EHISCharts;
  const D = M.data;
  const state = { scope: "org", weeks: 16, compare: "team", stack: [] };

  const TREND_METRICS = ["cycle_time_days", "defects", "deployment_success_rate_pct", "test_coverage_pct", "incidents", "pr_review_time_hours"];
  const COMPARE_METRICS = ["cycle_time_days", "pr_review_time_hours", "test_coverage_pct", "defects", "change_failure_rate_pct", "incidents", "on_call_pages", "build_time_min"];
  const CLASS_LABEL = { IMPROVING: "Improving", DETERIORATING: "Deteriorating", STABLE: "Stable", VOLATILE: "Volatile",
    ONE_TIME_ANOMALY: "One-time anomaly", INSUFFICIENT_DATA: "Insufficient data", NOT_CLASSIFIED: "Context", "n/a": "n/a" };
  const KPI_HELP = {
    overall: "Mean of the four health indices.",
    delivery: "Deployment frequency and outcomes, cycle and lead time, throughput.",
    quality: "Defects, escapes, regressions, change failure, coverage, automation, rework.",
    reliability: "Incidents, MTTR, availability, on-call load.",
    efficiency: "Review time and latency, PR size, build and CI health.",
  };

  const $ = s => document.querySelector(s);
  const esc = s => String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fmt = (metric, v) => M.formatValue(v, D.metrics[metric].unit);
  const label = m => D.metrics[m].label;
  const chip = cls => `<span class="chip c-${esc((cls || "n/a").toLowerCase().replace(/_/g, "-"))}">${esc(CLASS_LABEL[cls] || cls)}</span>`;
  const sev = s => `<span class="sev s-${esc(s.toLowerCase())}">${esc(s)}</span>`;
  const verdict = v => v === "WARN" ? `<span class="verdict warn" title="Shown with a caveat from Evidence Validation">Caveat</span>` : `<span class="verdict pass" title="Passed Evidence Validation">Validated</span>`;
  const conf = c => c ? `<span class="conf" title="Validated confidence (see methodology)"><span class="conf-bar"><i style="width:${Math.round(c.score * 100)}%"></i></span>${Math.round(c.score * 100)}%</span>` : "";
  const weekDate = w => D.meta.week_starts[w - 1];
  // Same symbols as the executive deck ("<= 11 hours" -> "≤ 11 hours").
  const target = t => String(t).replace(/<=/g, "≤").replace(/>=/g, "≥");
  function severityText(f) {
    const b = f.severity_breakdown || {};
    if (b.note) return b.note + ".";
    const parts = [];
    if (b.deteriorating_metrics) parts.push(`${b.deteriorating_metrics} deteriorating metric${b.deteriorating_metrics > 1 ? "s" : ""} (+${b.deteriorating_metrics})`);
    if (b.large_change) parts.push(`large change in ${b.large_change.map(label).join(", ").toLowerCase()} (+1)`);
    if (b.tier1_service) parts.push("runs a tier-1 service (+1)");
    if (b.reliability_impact) parts.push("reliability impact (+1)");
    return `${parts.join(" · ")} = ${f.severity_points} points → ${f.severity} (CRITICAL ≥ 6, HIGH ≥ 4, MEDIUM ≥ 2).`;
  }
  // "Cycle time: 3.2 days -> 4.5 days (+39%), trend since week 8 [TRD-...]" -> "Cycle time 3.2 → 4.5 days (+39%)"
  const shortEvidence = e => e.replace(/\s\[[^\]]+\]$/, "").replace(/, trend since week \d+$/, "").replace(" -> ", " → ");

  // ------------------------------------------------------------------ header
  function renderHeader() {
    const opt = (id) => `<option value="${esc(id)}" ${state.scope === id ? "selected" : ""}>${esc(D.scopes[id].label)}</option>`;
    $("#scope-select").innerHTML = opt("org") +
      `<optgroup label="Teams">${M.scopesOfType("team").map(opt).join("")}</optgroup>` +
      `<optgroup label="Platforms">${M.scopesOfType("platform").map(opt).join("")}</optgroup>`;
    document.querySelectorAll("[data-weeks]").forEach(b => b.setAttribute("aria-pressed", String(+b.dataset.weeks === state.weeks)));
    const r = M.periodRange(state.weeks);
    $("#period-label").textContent = `Weeks ${r[0]}–${r[1]} · ${weekDate(r[0])} to ${weekDate(r[1])}`;
    const dq = D.meta.data_quality, v = D.meta.validation.verdicts;
    $("#status").innerHTML = `
      <button class="badge ${dq.status === "PASS" ? "ok" : "warn"}" data-go="audit" title="Agent 01 data-quality gate">Data quality <b>${dq.score}</b> · ${esc(dq.status)}</button>
      <button class="badge" data-go="audit" title="Agent 08 verdicts">Findings <b>${v.PASS}</b> passed · <b>${v.WARN}</b> caveat · <b>${v.REJECT}</b> rejected</button>
      <span class="badge ${D.meta.reasoning === "PASS" ? "ok" : ""}" title="Claude Code reasoning layer">AI narratives · ${esc(D.meta.reasoning === "PASS" ? "validated" : D.meta.reasoning.toLowerCase().replace("_", " "))}</span>`;
  }

  // ------------------------------------------------------------------ KPIs
  function renderKPIs() {
    const cards = M.kpiCards(state.scope, state.weeks);
    $("#kpis").innerHTML = cards.map(k => `
      <button class="kpi ${k.key === "overall" ? "primary" : ""} b-${k.band}" data-kpi="${k.key}" aria-label="${esc(k.label)} ${M.formatValue(k.value, "count")}, open breakdown">
        <span class="kpi-label">${esc(k.label)}</span>
        <span class="kpi-value">${M.formatValue(k.value, "count")}<small>/100</small></span>
        <span class="kpi-delta ${k.delta > 0 ? "up" : k.delta < 0 ? "down" : ""}">${k.delta === null ? "" : (k.delta > 0 ? "+" : "") + k.delta + " vs W" + M.periodRange(state.weeks)[0]}</span>
        ${C.sparkline(k.spark, "b-" + k.band)}
        <span class="kpi-band">${esc(k.band.replace("-", " "))}</span>
      </button>`).join("");
  }

  // ------------------------------------------------------------------ risks
  function relevant(f) {
    if (state.scope === "org") return true;
    const mine = new Set(D.scopes[state.scope].pairs);
    return D.scopes[f.dimension.scope].pairs.some(p => mine.has(p));
  }
  function renderRisks() {
    const list = M.risks().filter(relevant);
    $("#risk-count").textContent = list.length + (state.scope === "org" ? "" : ` affecting ${D.scopes[state.scope].label}`);
    $("#risks").innerHTML = list.length ? list.map(r => {
      const nar = M.narrative(r.id);
      return `<article class="risk s-${r.severity.toLowerCase()}">
        <header><span class="rank">#${r.rank}</span>${sev(r.severity)}<span class="cat">${esc(r.category)}</span>${verdict(r.verdict)}${conf(r.confidence)}</header>
        <h3>${esc(r.risk)}</h3>
        <ul class="ev">${r.evidence.slice(0, 2).map(e => `<li>${esc(shortEvidence(e))}</li>`).join("")}${r.evidence.length > 2 ? `<li class="more">+${r.evidence.length - 2} more signals</li>` : ""}</ul>
        <p class="nar clamp">${esc(nar || r.potential_impact)}</p>
        <div class="risk-foot"><button class="link" data-finding="${esc(r.id)}">Why is this flagged? →</button>${nar ? '<span class="ai" title="Written by the Claude Code reasoning layer and accepted by validation">AI narrative · validated</span>' : ""}</div>
      </article>`;
    }).join("") : `<p class="empty">No validated risks for this scope.</p>`;
  }

  // ------------------------------------------------------------------ trends
  function bandFor(c) {
    // Shade only real trends: an onset week exists for any shifted series, but only series
    // that passed the trend threshold (IMPROVING / DETERIORATING) earn a trend window.
    if (!c || !c.trend_window || (c.classification !== "IMPROVING" && c.classification !== "DETERIORATING")) return null;
    return [c.trend_window[0], c.trend_window[1], c.classification === "IMPROVING" ? "good" : "bad"];
  }
  function renderTrends() {
    const sid = state.scope, r = M.periodRange(state.weeks);
    $("#trends").innerHTML = TREND_METRICS.map(m => `<div class="trend-card">
      <div class="trend-head"><button class="link strong" data-metric="${m}">${esc(label(m))}</button>
        ${chip(((D.classifications[sid] || {})[m] || {}).classification)}</div>
      <div class="trend-value">${fmt(m, M.periodMean(sid, m, state.weeks))} <small>avg W${r[0]}–${r[1]}</small></div>
      <div class="chart-box" id="tc-${m}"></div></div>`).join("");
    TREND_METRICS.forEach(m => {
      const c = (D.classifications[sid] || {})[m];
      const series = [{ values: D.series[sid][m], cls: "main" }];
      if (sid !== "org" && !D.metrics[m].count_metric) series.push({ values: D.series.org[m], cls: "ref", dashed: true });
      C.lineChart($("#tc-" + m), {
        range: r, series, format: v => fmt(m, v), formatTick: (v, d) => M.formatValue(v, D.metrics[m].unit, d), label: label(m) + " trend",
        band: bandFor(c), height: 170,
        markers: M.anomaliesFor(sid, m).map(a => ({ week: a.weeks[0], cls: "anomaly", title: "one-time anomaly" })),
        onPoint: w => openDrill({ kind: "week", scope: sid, metric: m, week: w }, true, [{ kind: "metric", scope: sid, metric: m }]),
      });
    });
    $("#trend-legend").innerHTML = (sid !== "org" ? `<span><i class="lg main"></i>${esc(D.scopes[sid].label)}</span><span><i class="lg ref"></i>Organisation (averages only)</span>` : "") +
      `<span><i class="lg bad"></i>Deteriorating trend window</span><span><i class="lg good"></i>Improving trend window</span><span><i class="lg anomaly"></i>One-time anomaly</span>`;
  }

  // ------------------------------------------------------------------ compare
  function renderCompare() {
    document.querySelectorAll("[data-compare]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.compare === state.compare)));
    const rows = M.compareTable(state.compare, COMPARE_METRICS, state.weeks);
    const arrow = cls => ({ DETERIORATING: '<i class="ar bad" title="Deteriorating trend">▲</i>', IMPROVING: '<i class="ar good" title="Improving trend">▼</i>',
                            ONE_TIME_ANOMALY: '<i class="ar anom" title="One-time anomaly">◆</i>' })[cls] || "";
    $("#compare").innerHTML = `<table class="cmp"><thead><tr><th scope="col">${state.compare === "team" ? "Team" : "Platform"}</th>
      ${COMPARE_METRICS.map(m => `<th scope="col">${esc(label(m))}<small>${D.metrics[m].polarity === "lower_is_better" ? "lower is better" : "higher is better"}</small></th>`).join("")}</tr></thead>
      <tbody>${rows.map(row => `<tr><th scope="row"><button class="link strong" data-scope="${esc(row.scope)}">${esc(row.label)}</button></th>
        ${COMPARE_METRICS.map(m => { const c = row.cells[m]; const t = c.relative === null ? "" : c.relative <= -0.15 ? "worse" : c.relative >= 0.15 ? "better" : "";
          return `<td class="${t}"><button class="cell" data-scope-metric="${esc(row.scope)}|${m}" title="${esc(label(m))} for ${esc(row.label)}: rank ${c.rank} of ${rows.length}">${fmt(m, c.value)}${arrow(c.classification)}</button></td>`; }).join("")}
      </tr>`).join("")}</tbody></table>
      <p class="note">Average over the selected weeks. Shading: ≥15% better or worse than the median ${state.compare}. ▲ deteriorating / ▼ improving trend (Agent 04, full history); ◆ one-time anomaly.</p>`;
  }

  // ------------------------------------------------------------------ recommendations / improvements
  function renderRecs() {
    const list = M.recommendations().filter(relevant);
    $("#recs").innerHTML = list.map(r => {
      const nar = M.narrative(r.id), ms = r.measurement_of_success;
      return `<article class="rec p-${r.priority.toLowerCase()}">
        <header><span class="prio">${esc(r.priority)}</span><span class="owner">${esc(r.owner_type)}</span>${verdict(r.verdict)}</header>
        <p class="action">${esc(nar || r.recommended_action)}${nar ? ' <span class="ai">AI narrative · validated</span>' : ""}</p>
        <p class="measure"><b>Success:</b> ${esc(label(ms.metric))} ${esc(target(ms.target))} by week ${ms.by_week}</p>
        <button class="link" data-finding="${esc(r.related_findings[0])}">Evidence →</button>
      </article>`;
    }).join("") || `<p class="empty">No recommendations for this scope.</p>`;
  }
  function renderImproved() {
    const items = D.improvements.map(id => D.findings[id]).filter(relevant);
    $("#improved").innerHTML = items.map(f => {
      const c = f.evidence.computed, m = f.metrics[0];
      // Volume metrics grow with team size; say so when headcount grew materially, so a bigger
      // team is not mistaken for a more effective one.
      const hc = ((D.classifications[f.dimension.scope] || {}).team_headcount) || {};
      const grew = D.metrics[m].count_metric && hc.movement === "RISING" && (hc.change_pct || 0) >= 20;
      return `<button class="imp${grew ? " ctx" : ""}" data-finding="${esc(f.id)}"><span class="imp-scope">${esc(D.scopes[f.dimension.scope].label)}</span>
        <span class="imp-metric">${esc(label(m))}</span><span class="imp-val">${fmt(m, c.baseline)} → ${fmt(m, c.recent)}</span>
        ${grew ? `<span class="imp-note">Volume metric; headcount also grew ${fmt("team_headcount", hc.baseline)} → ${fmt("team_headcount", hc.recent)}</span>` : ""}</button>`;
    }).join("") || `<p class="empty">No validated improvements for this scope.</p>`;
  }

  // ------------------------------------------------------------------ audit
  function renderAudit() {
    const dq = D.meta.data_quality;
    $("#audit").innerHTML = `
      <div class="audit-col"><h3>Data quality · Agent 01</h3>
        <p>Score <b>${dq.score}</b>/100 · ${dq.validated_records.toLocaleString()} of ${dq.total_records.toLocaleString()} records usable · status ${esc(dq.status)}</p>
        <table class="mini"><thead><tr><th>Rule</th><th>Record</th><th>Issue</th><th>Handling</th></tr></thead><tbody>
        ${dq.issues.map(i => `<tr><td>${esc(i.rule)}<br><small>${esc(i.severity)}</small></td><td><button class="link mono" data-record="${esc(i.record_id)}">${esc(i.record_id)}</button></td><td>${esc(i.message)}</td><td>${esc(i.handling.replace(/_/g, " "))}${i.exception ? `<br><small>approved ${esc(i.exception)}</small>` : ""}</td></tr>`).join("")}
        </tbody></table></div>
      <div class="audit-col"><h3>Excluded by Evidence Validation · Agent 08</h3>
        <p>These candidate findings were <b>rejected</b> and are not used in any conclusion above. They are listed for transparency.</p>
        <ul class="rejected">${D.rejected.map(r => `<li><span class="mono">${esc(r.id)}</span><br>${esc(r.reasons[0])}</li>`).join("")}</ul>
        <h3>How to read this dashboard</h3>
        <ul class="method">
          <li><b>Health indices</b> are relative: 75 = the organisation's level in weeks ${D.meta.health_baseline_weeks[0]}–${D.meta.health_baseline_weeks[1]}, 100 = 25%+ better, 50 = 25% worse. Cards show a ${D.meta.rolling_weeks}-week rolling average.</li>
          <li><b>Trends</b> need ≥5 weeks, statistical significance, a material change and persistence. A single spike is never a trend.</li>
          <li><b>Confidence</b> combines completeness, observations, consistency, magnitude, evidence quality and the validation verdict.</li>
          <li><b>Associations are not causes.</b> Possible explanations are shown only if they survived validation, and always as possibilities.</li>
          <li>Evidence fingerprint <span class="mono">${esc(D.meta.evidence_fingerprint)}</span>: every number on this page comes from that validated run.</li>
        </ul></div>`;
  }

  // ------------------------------------------------------------------ drill-down drawer
  let returnFocus = null;
  function openDrill(view, reset, prefix) {
    if (!$("#drawer").classList.contains("open")) returnFocus = document.activeElement;
    if (reset) state.stack = (prefix || []).slice();
    state.stack.push(view);
    renderDrawer();
    $("#drawer").classList.add("open");
    $("#drawer").removeAttribute("inert");
    $("#drawer").setAttribute("aria-hidden", "false");
    $("#drawer-close").focus();
  }
  function closeDrill() {
    // Move focus out before hiding, so focus is never inside an aria-hidden region.
    if (returnFocus && returnFocus !== document.body && document.contains(returnFocus)) returnFocus.focus();
    if ($("#drawer").contains(document.activeElement)) document.activeElement.blur();
    $("#drawer").classList.remove("open");
    $("#drawer").setAttribute("aria-hidden", "true");
    $("#drawer").setAttribute("inert", "");
    state.stack = [];
  }
  function crumb(v) {
    if (v.kind === "kpi") return D.meta.kpi_labels[v.kpi];
    if (v.kind === "metric") return `${label(v.metric)} · ${D.scopes[v.scope].label}`;
    if (v.kind === "week") return `Week ${v.week}`;
    if (v.kind === "record") return v.id;
    if (v.kind === "finding") { const f = M.finding(v.id); return f && f.type === "risk" ? "Why flagged" : v.id; }
    return v.kind;
  }
  function renderDrawer() {
    const v = state.stack[state.stack.length - 1];
    $("#crumbs").innerHTML = state.stack.map((s, i) => i === state.stack.length - 1
      ? `<span aria-current="page">${esc(crumb(s))}</span>` : `<button class="link" data-crumb="${i}">${esc(crumb(s))}</button>`).join('<span class="sep">›</span>');
    const body = $("#drawer-body");
    body.innerHTML = ({ kpi: kpiView, metric: metricView, week: weekView, record: recordView, finding: findingView })[v.kind](v);
    body.scrollTop = 0;
    if (v.kind === "metric") drawMetricChart(v);
    if (v.kind === "kpi") drawKpiChart(v);
    if (v.kind === "finding") drawFindingChart(v);
  }
  function kpiView(v) {
    const rows = M.kpiMetrics(state.scope, v.kpi, state.weeks);
    return `<h2>${esc(D.meta.kpi_labels[v.kpi])} <small>· ${esc(D.scopes[state.scope].label)}</small></h2>
      <p class="muted">${esc(KPI_HELP[v.kpi])} Weekly index (dots) and ${D.meta.rolling_weeks}-week rolling average (line).</p>
      <div class="chart-box" id="dc-kpi"></div>
      <h3>Metrics behind this index <small>(weakest first · score averaged over the selected weeks)</small></h3>
      <table class="mini click"><thead><tr><th>Metric</th><th>Score</th><th>Avg value</th><th>Trend (full history)</th></tr></thead><tbody>
      ${rows.map(r => `<tr data-metric="${r.metric}" tabindex="0"><td>${esc(r.label)}</td><td><span class="score b-${M.band(r.score)}">${M.formatValue(r.score, "count")}</span></td>
        <td>${fmt(r.metric, r.value)}</td><td>${chip(r.classification)}</td></tr>`).join("")}</tbody></table>`;
  }
  function drawKpiChart(v) {
    const k = D.kpi[state.scope][v.kpi];
    C.lineChart($("#dc-kpi"), { range: M.periodRange(state.weeks), series: [{ values: k.rolling, cls: "main" }, { values: k.weekly, cls: "ref", dashed: true }],
      format: x => M.formatValue(x, "count"), label: "KPI history", height: 180 });
  }
  function metricView(v) {
    const mv = M.metricView(v.scope, v.metric, state.weeks, state.compare), c = mv.classification;
    const t = mv.trend;
    return `<h2>${esc(label(v.metric))} <small>· ${esc(D.scopes[v.scope].label)}</small></h2>
      <p class="kv">${chip(c.classification)} <span>Average over selected weeks: <b>${fmt(v.metric, mv.periodMean)}</b></span>
        <span class="muted">${esc(mv.meta.polarity.replace(/_/g, " "))}</span></p>
      ${t ? `<div class="callout"><b>${esc(t.claim)}</b><br><span class="mono small">${esc(t.evidence.calculation)}</span>
         <br>${verdict(t.verdict)} ${conf(t.confidence)} <button class="link" data-finding="${esc(t.id)}">Full evidence →</button></div>` : ""}
      ${mv.anomalies.map(a => `<div class="callout anomaly-c">◆ ${esc(a.claim)} <button class="link" data-finding="${esc(a.id)}">Evidence →</button></div>`).join("")}
      <div class="chart-box" id="dc-metric"></div>
      <p class="muted">Select a week (chart point or table row) to see the source records behind it.</p>
      <div class="two">
        <table class="mini click"><thead><tr><th>Week</th><th>Starts</th><th>Value</th></tr></thead><tbody>
        ${mv.values.map((x, i) => i + 1 < mv.range[0] ? "" : `<tr data-week="${i + 1}" tabindex="0"><td>W${i + 1}</td><td>${weekDate(i + 1)}</td><td>${fmt(v.metric, x)}</td></tr>`).join("")}</tbody></table>
        ${mv.children.length ? `<table class="mini click"><thead><tr><th>${D.scopes[v.scope].type === "org" ? (state.compare === "team" ? "Team" : "Platform") : "Team / platform"}</th><th>Avg</th><th>Trend</th></tr></thead><tbody>
          ${mv.children.map(ch => `<tr data-child="${esc(ch.scope)}" tabindex="0"><td>${esc(ch.label)}</td><td>${fmt(v.metric, ch.value)}</td><td>${chip(ch.classification)}</td></tr>`).join("")}</tbody></table>` : ""}
      </div>`;
  }
  function drawMetricChart(v) {
    const c = (D.classifications[v.scope] || {})[v.metric];
    C.lineChart($("#dc-metric"), { range: M.periodRange(state.weeks), series: [{ values: D.series[v.scope][v.metric], cls: "main" }],
      format: x => fmt(v.metric, x), formatTick: (x, d) => M.formatValue(x, D.metrics[v.metric].unit, d), band: bandFor(c), height: 210,
      markers: M.anomaliesFor(v.scope, v.metric).map(a => ({ week: a.weeks[0], cls: "anomaly", title: "one-time anomaly" })),
      onPoint: w => openDrill({ kind: "week", scope: v.scope, metric: v.metric, week: w }) });
  }
  function recordRow(id, highlight) {
    const r = M.record(id);
    if (!r) return "";
    const f = r.fields, flag = r.dq.length ? `<span class="dq" title="${esc(r.dq.map(x => x.message).join("; "))}">data-quality flag</span>` : "";
    const detail = r.dataset === "deployments" ? `${f.status}${f.rolled_back ? " · rolled back" : ""} · ${f.duration_min} min`
      : r.dataset === "incidents" ? `${f.severity} · MTTR ${f.mttr_minutes} min${f.change_related ? " · change-related" : ""}`
      : r.dataset === "defects" ? `${f.severity}${f.escaped ? " · escaped" : ""}${f.regression ? " · regression" : ""}` : "";
    return `<tr data-record="${esc(id)}" tabindex="0" class="${highlight ? "hl" : ""}"><td class="mono">${esc(id)}</td><td>${esc(f.deployed_on || f.opened_on || f.reported_on || f.week_start)}</td><td>${esc(detail)} ${flag}</td></tr>`;
  }
  function weekView(v) {
    const wr = M.weekRecords(v.scope, v.metric, v.week);
    const field = wr.field;
    return `<h2>${esc(label(v.metric))} · Week ${v.week} <small>· ${esc(D.scopes[v.scope].label)} · from ${weekDate(v.week)}</small></h2>
      <p class="big">${fmt(v.metric, wr.value)}</p>
      <p class="muted">${esc(wr.explanation)}</p>
      <h3>Weekly rows <small>(weekly_metrics.csv)</small></h3>
      <table class="mini click"><thead><tr><th>Record</th><th>Team / platform</th><th>${field ? esc(field) : "Week start"}</th></tr></thead><tbody>
      ${wr.weekly.map(id => { const r = M.record(id); return `<tr data-record="${esc(id)}" tabindex="0"><td class="mono">${esc(id)}</td><td>${esc(r.fields.team)} / ${esc(r.fields.platform)}</td><td>${field ? esc(r.fields[field] === null ? "missing" : r.fields[field]) : esc(r.fields.week_start)} ${r.dq.length ? '<span class="dq">data-quality flag</span>' : ""}</td></tr>`; }).join("")}</tbody></table>
      ${wr.dataset ? `<h3>${esc(wr.dataset)} records <small>(${wr.events.length}${wr.events.some(e => e.highlight) && wr.meta.derive.kind === "event_ratio" ? `, ${wr.events.filter(e => e.highlight).length} highlighted` : ""})</small></h3>
        ${wr.events.length ? `<table class="mini click"><thead><tr><th>Record</th><th>Date</th><th>Detail</th></tr></thead><tbody>${wr.events.map(e => recordRow(e.id, e.highlight && wr.meta.derive.kind === "event_ratio")).join("")}</tbody></table>` : `<p class="empty">No ${esc(wr.dataset)} records this week.</p>`}` : ""}`;
  }
  function recordView(v) {
    const r = M.record(v.id);
    if (!r) return `<p class="empty">Record ${esc(v.id)} not found.</p>`;
    return `<h2 class="mono">${esc(r.id)}</h2><p class="muted">Source: data/raw/${esc(r.dataset)}.csv</p>
      ${r.dq.map(q => `<div class="callout warn-c"><b>${esc(q.rule)} · ${esc(q.severity)}</b> ${esc(q.message)}<br>Handling: ${esc(q.handling.replace(/_/g, " "))}${q.exception ? ` (approved exception ${esc(q.exception)})` : ""}</div>`).join("")}
      <table class="mini"><tbody>${Object.keys(r.fields).map(k => `<tr><th>${esc(k)}</th><td class="mono">${esc(r.fields[k] === null ? "— missing —" : r.fields[k])}</td></tr>`).join("")}</tbody></table>`;
  }
  function findingView(v) {
    const f = M.finding(v.id);
    if (!f) return `<p class="empty">Finding ${esc(v.id)} is not part of the validated set.</p>`;
    if (f.type === "risk") {
      const t = M.traceChain(f.id), rec = M.recommendationFor(f.id), nar = M.narrative(f.id);
      const primary = (f.primary_refs || []).map(id => M.finding(id)).filter(Boolean);
      return `<h2>Why is this flagged?</h2><p class="lead">${esc(f.risk)}</p>
        <p class="kv">${sev(f.severity)} <span class="cat">${esc(f.category)}</span> ${verdict(f.verdict)} ${conf(f.confidence)}</p>
        ${nar ? `<p class="nar">${esc(nar)} <span class="ai">AI narrative · validated</span></p>` : ""}
        ${f.caveats.length ? `<div class="callout warn-c"><b>Caveat:</b> ${esc(f.caveats.join(" "))}</div>` : ""}
        <h3>Observed evidence</h3>
        <ul class="ev">${f.evidence.map((e, i) => `<li>${esc(e.replace(/\s\[[^\]]+\]$/, "").replace(" -> ", " → "))} ${primary[i] ? `<button class="link" data-finding="${esc(primary[i].id)}">trend detail →</button>` : ""}</li>`).join("")}</ul>
        <div class="chart-box" id="dc-finding"></div>
        <h3>Possible explanations <small>(survived validation; possibilities, not causes)</small></h3>
        ${(f.possible_explanations || []).length ? `<ul class="expl">${f.possible_explanations.map(id => { const h = M.finding(id); return h ? `<li>${esc(M.narrative(id) || h.claim)}<br><small>${verdict(h.verdict)} ${esc(h.caveats[0] || "")}</small></li>` : ""; }).join("")}</ul>` : `<p class="muted">None survived validation. The system does not guess a cause.</p>`}
        <h3>Severity</h3><p class="small">${esc(severityText(f))}</p>
        <h3>Traceability</h3>
        <ol class="trace">
          <li><span>Insight</span><b class="mono">${esc(t.insight)}</b></li>
          <li><span>Metric(s)</span><b>${t.metrics.map(label).map(esc).join(", ")}</b></li>
          <li><span>Scope</span><b>${esc(D.scopes[t.scope].label)}</b></li>
          <li><span>Source records</span><b>${t.records.length} records <button class="link" data-records="${esc(f.id)}">list →</button></b></li>
          <li><span>Calculation</span><b class="small mono">${esc((t.calculations[0] || {}).text || "")}</b></li>
          <li><span>Agents</span><b>${t.agents.map(esc).join(" → ")}</b></li>
          <li><span>Validation</span><b>08_evidence_validation = ${esc(t.validation)}</b></li>
          <li><span>Recommendation</span><b>${rec ? esc(rec.priority + " · " + rec.owner_type) : "none"}</b></li>
        </ol>
        ${rec ? `<div class="callout"><b>Recommended action (${esc(rec.priority)})</b><br>${esc(M.narrative(rec.id) || rec.recommended_action)}<br><small>Success: ${esc(label(rec.measurement_of_success.metric))} ${esc(target(rec.measurement_of_success.target))} by week ${rec.measurement_of_success.by_week}</small></div>` : ""}`;
    }
    const e = f.evidence || {};
    const vals = e.values || {};
    const m = (f.metrics || [])[0];
    const scope = f.dimension && f.dimension.scope;
    return `<h2>${esc(f.type.replace("_", " "))} <small class="mono">${esc(f.id)}</small></h2>
      <p class="lead">${esc(f.claim)}</p>
      <p class="kv">${f.classification ? chip(f.classification) : ""} ${verdict(f.verdict)} ${conf(f.confidence)}</p>
      ${f.caveats.length ? `<div class="callout warn-c"><b>Caveat:</b> ${esc(f.caveats.join(" "))}</div>` : ""}
      <h3>Calculation</h3><p class="mono small">${esc(e.calculation || "")}</p>
      ${m && scope && D.series[scope] ? `<div class="chart-box" id="dc-finding"></div><button class="link" data-scope-metric="${esc(scope)}|${esc(m)}">Open metric and weekly records →</button>` : ""}
      ${Object.keys(vals).length && !Array.isArray(vals[Object.keys(vals)[0]]) ? `<h3>Values</h3><div class="vals">${Object.keys(vals).map(w => `<span><small>W${esc(w)}</small>${m ? fmt(m, vals[w]) : esc(vals[w])}</span>`).join("")}</div>` : ""}
      ${f.confidence ? `<h3>Confidence components</h3><div class="vals">${Object.entries(f.confidence.components).map(([k, x]) => `<span><small>${esc(k.replace("_", " "))}</small>${Math.round(x * 100)}%</span>`).join("")}</div>` : ""}`;
  }
  function drawFindingChart(v) {
    const f = M.finding(v.id);
    if (!f || !$("#dc-finding")) return;
    const ref = f.type === "risk" ? M.finding((f.primary_refs || [])[0]) : f;
    if (!ref || !ref.metrics || !D.series[ref.dimension.scope]) return;
    const m = ref.metrics[0], sid = ref.dimension.scope, c = (D.classifications[sid] || {})[m];
    C.lineChart($("#dc-finding"), { range: [1, D.meta.n_weeks], series: [{ values: D.series[sid][m], cls: "main" }], format: x => fmt(m, x),
      formatTick: (x, d) => M.formatValue(x, D.metrics[m].unit, d), band: bandFor(c), height: 190, label: label(m),
      markers: M.anomaliesFor(sid, m).map(a => ({ week: a.weeks[0], cls: "anomaly", title: "one-time anomaly" })),
      onPoint: w => openDrill({ kind: "week", scope: sid, metric: m, week: w }) });
  }
  function recordsListView(fid) {
    const t = M.traceChain(fid);
    return `<h2>Source records <small>· ${esc(fid)}</small></h2><p class="muted">Weekly rows behind the supporting trend windows. Select one to inspect it.</p>
      <table class="mini click"><thead><tr><th>Record</th><th>Date</th><th>Detail</th></tr></thead><tbody>${t.records.map(id => recordRow(id)).join("")}</tbody></table>`;
  }

  // ------------------------------------------------------------------ events
  function render() { renderHeader(); renderKPIs(); renderRisks(); renderTrends(); renderCompare(); renderRecs(); renderImproved(); renderAudit(); }

  document.addEventListener("click", e => {
    const t = e.target.closest("button, tr[data-metric], tr[data-week], tr[data-child], tr[data-record]");
    if (!t) return;
    const top = state.stack[state.stack.length - 1];
    if (t.dataset.weeks) { state.weeks = +t.dataset.weeks; render(); if (state.stack.length) renderDrawer(); return; }
    if (t.dataset.compare) { state.compare = t.dataset.compare; renderCompare(); return; }
    if (t.dataset.kpi) return openDrill({ kind: "kpi", kpi: t.dataset.kpi }, true);
    if (t.dataset.finding) return openDrill({ kind: "finding", id: t.dataset.finding }, !$("#drawer").contains(t));
    if (t.dataset.record) return openDrill({ kind: "record", id: t.dataset.record }, !$("#drawer").contains(t));
    if (t.dataset.records) { state.stack.push({ kind: "records", id: t.dataset.records }); $("#crumbs").innerHTML += '<span class="sep">›</span><span>Records</span>'; $("#drawer-body").innerHTML = recordsListView(t.dataset.records); return; }
    if (t.dataset.scopeMetric) { const [s, m] = t.dataset.scopeMetric.split("|"); return openDrill({ kind: "metric", scope: s, metric: m }, !$("#drawer").contains(t)); }
    if (t.dataset.scope) { state.scope = t.dataset.scope; render(); window.scrollTo({ top: 0, behavior: "smooth" }); return; }
    if (t.dataset.metric) return openDrill({ kind: "metric", scope: top && top.kind === "kpi" ? state.scope : state.scope, metric: t.dataset.metric }, !$("#drawer").contains(t));
    if (t.dataset.week && top) return openDrill({ kind: "week", scope: top.scope, metric: top.metric, week: +t.dataset.week });
    if (t.dataset.child && top) return openDrill({ kind: "metric", scope: t.dataset.child, metric: top.metric });
    if (t.dataset.crumb) { state.stack = state.stack.slice(0, +t.dataset.crumb + 1); return renderDrawer(); }
    if (t.dataset.go === "audit") { $("#audit-section").scrollIntoView({ behavior: "smooth" }); return; }
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && $("#drawer").classList.contains("open")) closeDrill();
    if ((e.key === "Enter" || e.key === " ") && e.target.matches("tr[tabindex]")) { e.preventDefault(); e.target.click(); }
  });
  $("#drawer-close").addEventListener("click", closeDrill);
  $("#scrim").addEventListener("click", closeDrill);
  $("#scope-select").addEventListener("change", e => { state.scope = e.target.value; render(); });
  $("#theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.dataset.theme = cur === "dark" ? "light" : "dark";
    try { localStorage.setItem("ehis-theme", document.documentElement.dataset.theme); } catch (_) { /* storage unavailable */ }
    render();
  });

  render();
  window.EHISApp = { state, render, openDrill, closeDrill, renderDrawer };
})();
