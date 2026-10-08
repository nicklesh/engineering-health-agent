# Agent 09 — Dashboard Generation

**Implementation:** [src/reporting/agent09_dashboard.py](../src/reporting/agent09_dashboard.py) (data) · [dashboard/](../dashboard/) (static page: `index.html`, `js/model.js`, `js/charts.js`, `js/app.js`, `css/dashboard.css`) · **Kind:** deterministic rendering · **Outputs:** `dashboard/data/dashboard_data.js`, `data/processed/09_dashboard_generation.json`

## Purpose
Give leaders an interactive, executive-quality view of engineering health in which **every number can be traced to why it exists**, built only from validated outputs.

## Responsibilities
- Assemble one data file from validated sources: series and health from 02, classifications from 04, findings from 08 (PASS/WARN only), accepted narratives from the reasoning layer, and source records after 01's directives, with data-quality flags.
- Re-read what it wrote and **check it against the sources** (consistency checks below). Any mismatch means status FAIL, and the orchestrator reports `ERROR`.
- Stamp the page's data URL with a content hash, so a browser can never show a cached older analysis.
- The page provides KPI cards, trend charts, a risk view, team and platform comparison, 4/8/12/16-week filters, recommendations, improvements, an audit trail, and drill-down **KPI → metric → team/platform → week → source record**, with an evidence panel ("Why is this flagged?") and the traceability chain for every risk.

## Inputs
Envelopes 01, 02, 03, 04, 08; `metric_series.json`; `reasoning_layer.json` (optional; used only if its fingerprint matches the current Agent 08 output); raw data via 01's directives.

## Outputs
- `dashboard/data/dashboard_data.js`: `window.EHIS_DATA = {meta, metrics, scopes, series, kpi, metric_scores, classifications, quality_status, findings, risks, recommendations, improvements, narratives, rejected, records, record_index, dq_flags}`.
- Envelope with `summary` and `consistency_checks[]`.

## Input schema
As produced by agents 01–08 (CLAUDE.md §4) and the reasoning layer (`{evidence_validation_fingerprint, narratives[{finding_id, text, verdict}]}`).

## Output schema
`findings[id]` = the Agent 08 finding reduced to display fields + `verdict`, `caveats`, `confidence {score, components}`. `kpi[scope][kpi] = {weekly[16], rolling[16]}`. `record_index["Team/Platform"][week][dataset] = [ids]`. `rejected[] = {id, type, reasons}` (shown in the audit trail only, labelled as excluded).

## Decision rules
- **Only validated content.** REJECTED findings are excluded, and so are references to them (rejected explanations are removed from risks). They are listed in the audit trail as "not used in any conclusion".
- **Narratives** are shown only when accepted *and* written for the current evidence fingerprint; otherwise the deterministic wording is used, and the header says so.
- **KPI cards** show the 4-week rolling mean of Agent 02's weekly health index; the delta is measured against the first week of the selected period. Bands: ≥ 75 healthy, ≥ 60 watch, below 60 at risk.
- **Trend bands** are drawn only for series classified IMPROVING or DETERIORATING. Anomaly markers come from Agent 05.
- **Volume metrics** (counts) shown as improvements carry a note when the team's headcount grew ≥ 20%, so a bigger team is not mistaken for a more effective one.
- **The UI does no analysis.** `model.js` only selects, averages over the chosen weeks, and looks up records.

## Failure conditions
- Any dependency missing or FAILED → refuses to run.
- A consistency check fails → status FAIL → the orchestrator stops with `ERROR` ("outputs must not be used").
- In the browser: if the data file is missing or fails to load, the page shows an explicit error with the fix (`python run.py`), never an empty dashboard that looks valid.

## Validation rules
Consistency checks (each must PASS):
- `series_match_agent02`: all 560 series identical to `metric_series.json`.
- `no_rejected_findings`: no rejected finding or reference present.
- `evidence_match_agent08`, `confidence_match_agent08`: identical to Agent 08.
- `records_resolvable`: every evidence record id resolves to a source record.
- `drilldown_counts_match`: the deployment records reachable by drill-down equal the reported counts.
- `cache_busting`: `index.html` loads exactly this data version.

`tests/dashboard_model_test.js` (run from `tests/test_dashboard.py`) covers: data loads; the 4/8/12/16-week filters; the full drill-down path; every team/platform-week deployment count, defect count and change-failure rate reproduced from the drill-down records; data-quality flags; risk traceability; no rejected content.

## Dependencies
01, 02, 03, 04, 08 (and optionally the reasoning layer). It runs after the evidence feedback loop.

## Example input
`RISK-ALL-DATA-RELIABILITY` (Agent 08, PASS, confidence 0.90) + its primary trends + `metric_series.json`.

## Example output (real run)
Drill-down: *Engineering Health › Change failure rate · Organisation › Titan › Week 16 › DEP-W16-TITAN-DATA-001*. Week 16 lists 28 deployment records, 6 highlighted as FAILED: 6/28 = 21.4%, the value plotted for that week. The risk's severity reads: *"4 deteriorating metrics (+4) · large change … (+1) · runs a tier-1 service (+1) · reliability impact (+1) = 7 points → CRITICAL"*.
