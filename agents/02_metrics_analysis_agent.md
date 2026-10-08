# Agent 02 — Metrics Analysis

**Implementation:** [src/analysis/agent02_metrics_analysis.py](../src/analysis/agent02_metrics_analysis.py), [src/analysis/dataset.py](../src/analysis/dataset.py) · **Kind:** fully deterministic (arithmetic only) · **Outputs:** `data/processed/02_metrics_analysis.json`, `data/processed/metric_series.json`

## Purpose
Turn the validated raw data into numbers that every other agent can trust and trace. **No interpretation happens here**, only arithmetic.

## Responsibilities
- Apply Agent 01's `analysis_directives` (exclude duplicates, treat invalid values as missing).
- Compute every metric in `config/metrics.json` for every **scope** × **week**. Scopes are `org`, `team:<T>`, `platform:<P>` and `tp:<T>/<P>` (20 scopes × 28 metrics × 16 weeks).
- Keep the source record ids behind every data point (the basis of dashboard drill-down).
- For every scope × metric: current vs previous week, last-4-weeks vs prior-4-weeks, absolute and % change, direction by polarity, and rank among peers.
- Compute the KPI health scores (Engineering Health, Delivery, Quality, Reliability, Efficiency).
- Emit a `metric_change` finding for each material period-over-period change at team, platform or org level.

## Inputs
`01_data_validation.json` (status must not be FAIL), the raw CSVs, `config/metrics.json`, and `config/thresholds.json → metrics_analysis`.

## Outputs
- `metric_series.json`: `scopes[scope].metrics[metric] = {values[16], complete[16], event_records{week: [ids]}, numerator[16]?, denominator[16]?}` and `scopes[scope].weekly_records{week: [ids]}`.
- Envelope: `observations[]` (560), `health_scores`, `findings[]` (`metric_change`).

## Input schema
Agent 01 envelope (`analysis_directives`) + CSVs per the data dictionary. Metric catalog entry:
```json
{"id": "change_failure_rate_pct", "unit": "%", "polarity": "lower_is_better", "category": "quality",
 "kpi": "quality", "risk_category": "Reliability", "definition_group": "deploy_outcome",
 "derive": {"kind": "event_ratio", "dataset": "deployments", "numerator": {"status": "FAILED"}, "denominator": {}}}
```

## Output schema
Observation:
```json
{"scope": "", "metric": "", "current": 0, "previous": 0, "abs_change": 0, "change_pct": 0, "direction": "improving|deteriorating|unchanged|increasing|decreasing|unknown",
 "current_period": 0, "previous_period": 0, "period_change_pct": 0, "period_direction": "", "rank": 1, "rank_of": 5}
```
`metric_change` finding: standard finding (CLAUDE.md §4) with `evidence.series_ref`, `evidence.computed {current_period, previous_period, change_pct}`.

## Decision rules
- **Aggregation.** `weekly_field` metrics are averaged (`mean`) or summed (`sum`) over the rows in scope. Rates are **pooled**: `100 × Σ numerator / Σ denominator`, never an average of rates. Counts use the event logs, not the weekly aggregate columns.
- **Missing data.** If any contributing row is missing a value, the point is `None` and marked incomplete. It is not averaged over the rows that remain, because that would silently bias the scope value.
- **Direction.** Determined by the metric's polarity. Neutral metrics (headcount, PR count) only "increase" or "decrease".
- **Material change.** `|period_change_pct| ≥ material_change_pct` (10%) at team, platform or org scope.
- **Ranking.** Peers of the same scope type are ranked on the current-period value; 1 = best for that polarity.
- **Health score.** For each metric, `r = value / baseline` (or `baseline / value` when lower is better), where the baseline is the organisation's per-team/platform mean over weeks 1–4, scaled by the scope's team/platform count for counts. Then `score = clamp(75 + 100 × (r − 1), 0, 100)`: 75 = organisation baseline, 100 = 25%+ better, 50 = 25% worse. A KPI is the mean of its metrics; Engineering Health is the mean of the four KPIs. Availability is scored on unavailability. It is a **relative index**, not an absolute grade.

## Failure conditions
Agent 01 output missing → `MissingDependencyError`. Agent 01 status FAIL → `DependencyFailedError`. A raw file missing → `FileNotFoundError` naming the file.

## Validation rules
- Each deployment-count point equals the number of event ids stored for it (`test_02_series_traceable`).
- The injected missing coverage value stays `None` (never imputed).
- Agent 08 recomputes every `metric_change` from the series and REJECTs any mismatch.

## Dependencies
01 Data Validation.

## Example input
Weekly row `WM-W16-ATLAS-WEB` and `WM-W16-ATLAS-SERVICES` (cycle time 5.4 and 4.8 days).

## Example output (real run)
```json
{"scope": "team:Atlas", "metric": "cycle_time_days", "current": 5.115, "previous": 5.2, "change_pct": -1.63,
 "direction": "improving", "current_period": 4.78, "previous_period": 3.987, "period_change_pct": 19.89, "rank": 5, "rank_of": 5}
```
Note how the week-over-week view says "improving" while the 4-week view shows +19.9%. That gap is why week-over-week changes alone never drive conclusions; Agent 04 owns trends.
