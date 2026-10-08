# Agent 03 — Quality Analysis

**Implementation:** [src/analysis/agent03_quality_analysis.py](../src/analysis/agent03_quality_analysis.py) · **Kind:** deterministic signals (reasoning layer may add narrative) · **Output:** `data/processed/03_quality_analysis.json`

## Purpose
Give a quality-focused view of each team and platform: what is improving, what is deteriorating, what is persistently weak, and which practice metrics might be early warnings.

## Responsibilities
- Build a **quality profile** per team and platform for baseline weeks 1–6 vs recent weeks 13–16: defects/week, critical+high share, escaped / regression / change-failure rate (pooled counts), coverage, automated tests.
- Derive a **quality status** from Agent 04's classifications of quality metrics.
- Flag **persistent quality risks**: weekly level metrics materially worse than the peer median in most recent weeks.
- Flag **potential leading indicators**: coverage or automation changes followed 1–3 weeks later by defect or escape changes.

## Inputs
`02_metrics_analysis.json`, `metric_series.json`, `04_trend_analysis.json` (classifications), `05_anomaly_detection.json`, and `config/thresholds.json → quality, trend`.

## Outputs
Envelope with `quality_profiles{scope}` and `quality_signal` findings whose `signal` is `QUALITY_IMPROVING`, `QUALITY_DETERIORATING`, `PERSISTENT_QUALITY_RISK` or `POTENTIAL_LEADING_INDICATOR`.

## Input schema
Agent 04 `series_classifications[]` entries: `{scope, metric, classification, baseline, recent, ...}`. Agent 05 findings: `{metrics, dimension.scope, also_visible_in}`.

## Output schema
```json
{"id": "QUA-<TEAM|ALL>-<PLATFORM|ALL>-STATUS | -PERSISTENT-<METRIC> | -LEAD-<A>-<B>",
 "type": "quality_signal", "signal": "", "claim": "", "metrics": [], "dimension": {}, "weeks": [0, 0],
 "evidence": {"finding_refs | series_ref": "...", "record_ids": [], "values": {}, "calculation": ""},
 "causal_claim": false, "confidence": {}, "produced_by": "03_quality_analysis"}
```

## Decision rules
- Quality metrics are those whose `risk_category` is Quality (defects, critical+high defects, escaped / regression rate, coverage, automated tests, rework).
- **Status:** DETERIORATING when ≥ 2 quality metrics are DETERIORATING and they outnumber the improving ones. IMPROVING is the mirror. MIXED when both are present. Otherwise STABLE. This agent **does not re-classify trends**; it reuses Agent 04's result, so the two can never disagree.
- **Persistent risk** (weekly level metrics only): worse than the peer median by ≥ 20% (lower-is-better) or ≥ 10% (higher-is-better) in ≥ 6 of the last 8 weeks. Small-sample rates and counts are compared through the pooled profile instead.
- **Leading indicator** (team scope): Pearson r between `lead(t)` and `lagging(t+k)` for k = 1..3, reported when r ≤ −0.6 over ≥ 8 weeks. Pairs checked: coverage or automation → defects or escape rate. Always worded as an association.

## Failure conditions
Agent 02, 04 or 05 output missing or FAILED → the agent refuses to run.

## Validation rules
Agent 08 REJECTs a status finding if fewer than 2 of its supporting trends survive validation, recomputes every lagged r, and REJECTs any causal wording.

## Dependencies
02 Metrics Analysis, 04 Trend Analysis, 05 Anomaly Detection.

## Example input
Agent 04: `team:Atlas` → test coverage DETERIORATING (72.0% → 63.2%), defects DETERIORATING (6 → 12/week), automated tests and rework rate DETERIORATING.

## Example output (real run)
```json
{"id": "QUA-ATLAS-ALL-STATUS", "signal": "QUALITY_DETERIORATING",
 "claim": "Atlas: quality is deteriorating - 4 quality metrics with a qualifying trend (rework rate 8.3% -> 12.8%; defects 6 -> 12; test coverage 72% -> 63.2%; automated tests 80.4% -> 75.7%)."}
{"id": "QUA-ATLAS-ALL-LEAD-TEST_COVERAGE_PCT-DEFECTS", "signal": "POTENTIAL_LEADING_INDICATOR",
 "claim": "Atlas: lower test coverage was followed 1 week(s) later by higher defects (r=-0.6492). A potential leading indicator to monitor - an association, not proof that one causes the other."}
```
