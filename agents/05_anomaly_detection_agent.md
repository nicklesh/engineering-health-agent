# Agent 05 — Anomaly Detection

**Implementation:** [src/analysis/agent05_anomaly_detection.py](../src/analysis/agent05_anomaly_detection.py) · **Kind:** deterministic signals (reasoning layer may add narrative) · **Output:** `data/processed/05_anomaly_detection.json`

## Purpose
Find single weeks that are far from their local baseline, and say plainly whether each is an **anomaly** (an isolated spike) or the start of a **sustained shift**. Only Agent 04 may call a shift a trend.

## Responsibilities
- Scan every scope × outcome metric week by week on raw weekly values, independently of Agent 04.
- For each anomaly report what happened, the expected baseline, the magnitude, the period, the affected dimension, the supporting records and a confidence.
- Report each spike once, at the most specific scope, and list the broader scopes where it is also visible.

## Inputs
`02_metrics_analysis.json`, `metric_series.json`, `config/thresholds.json → anomaly`.

## Outputs
Envelope with `anomaly` findings.

## Input schema
`metric_series.json` entries (`values`, `numerator`/`denominator` for rates, `event_records` for event means).

## Output schema
```json
{"id": "ANO-<TEAM|ALL>-<PLATFORM|ALL>-<METRIC>-W<week>", "type": "anomaly",
 "pattern": "ISOLATED_SPIKE | SUSTAINED_SHIFT | UNRESOLVED", "impact": "adverse | favourable",
 "claim": "", "what_happened": "", "expected_baseline": 0, "magnitude": {"residual": 0, "z": 0, "relative_pct": 0},
 "weeks": [w, w], "dimension": {}, "also_visible_in": [],
 "evidence": {"record_ids": [], "values": {}, "calculation": "", "computed": {"value", "expected", "residual", "z", "scale", "pattern"}},
 "confidence": {}}
```

## Decision rules
- **Level and count metrics:** expected = median of valid values within ±3 weeks (excluding the week itself, ≥ 4 neighbours). Scale = robust sd of all such residuals in the series; for counts at least √expected (Poisson noise). The week is an anomaly when |z| ≥ 4 **and** |value − expected| ≥ 25% of expected.
- **Rates:** binomial test of the week's count against the pooled rate of neighbouring weeks: `z = (x − k·p) / √(k·p·(1−p))`. It requires ≥ 5 events that week, ≥ 20 in the neighbours and an excess of ≥ 3 events. Without this, 1 failure in 3 deployments looks like a "+200% spike".
- **Event means** (MTTR): only weeks with ≥ 3 incidents are tested. The mean of one incident is not a stable weekly value.
- **Pattern:** `ISOLATED_SPIKE` if the next week is back within 2 × scale of expected; `SUSTAINED_SHIFT` if both following weeks stay beyond it; `UNRESOLVED` for the latest week.
- **Anomaly vs trend:** this agent never uses the word "trend" for an isolated spike. A sustained shift is handed to Agent 04's judgement.

## Failure conditions
Agent 02 output missing or FAILED → the agent refuses to run.

## Validation rules
Agent 08 recomputes the value, checks that an ISOLATED_SPIKE really returned to normal, checks for trend wording, and marks marginal detections (|z| < 5) as WARN.

## Dependencies
02 Metrics Analysis.

## Example input
`tp:Nova/Mobile / ci_failure_rate_pct`: `[7.8, 7.0, 6.9, 6.9, 7.6, 6.8, 8.9, 7.7, 5.8, 7.1, 41.0, 7.4, 6.5, 8.5, 7.3, 7.6]`.

## Example output (real run)
```json
{"id": "ANO-NOVA-MOBILE-CI_FAILURE_RATE_PCT-W11", "pattern": "ISOLATED_SPIKE",
 "claim": "Nova / Mobile: CI failure rate was 41 % in week 11 against an expected 7.25 (local median), 53.6x the normal variation - a one-week spike that returned to normal the following week.",
 "expected_baseline": 7.25, "magnitude": {"residual": 33.75, "z": 53.56, "relative_pct": 465.5},
 "also_visible_in": ["platform:Mobile", "team:Nova", "org"], "evidence": {"record_ids": ["WM-W11-NOVA-MOBILE"]}, "confidence": {"score": 0.94}}
```
