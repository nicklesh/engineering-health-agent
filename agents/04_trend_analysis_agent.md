# Agent 04 — Trend Analysis

**Implementation:** [src/analysis/agent04_trend_analysis.py](../src/analysis/agent04_trend_analysis.py), rules in [src/analysis/trend_rules.py](../src/analysis/trend_rules.py) · **Kind:** deterministic signals (reasoning layer may add narrative) · **Output:** `data/processed/04_trend_analysis.json`

## Purpose
Decide, for every metric series over the full 16 weeks, whether something is **really changing**. Also report strong co-movements between changing metrics as associations, never as causes.

## Responsibilities
- Classify each scope × metric series as IMPROVING, STABLE, DETERIORATING, VOLATILE, ONE_TIME_ANOMALY or INSUFFICIENT_DATA. Neutral context metrics (headcount, PR count) are `NOT_CLASSIFIED` but keep their movement.
- Locate the trend onset week and window.
- Report up to 5 correlations per team or platform scope between trending outcome metrics, with a common-driver check.

## Inputs
`02_metrics_analysis.json`, `metric_series.json`, `config/thresholds.json → trend, correlation`, `config/metrics.json`.

## Outputs
Envelope with `series_classifications[]` (all 560 series) and findings of type `trend` (IMPROVING / DETERIORATING / ONE_TIME_ANOMALY) and `correlation`.

## Input schema
`metric_series.json → scopes[scope].metrics[metric] = {values[], numerator[]?, denominator[]?}`.

## Output schema
Classification record: `{scope, metric, classification, basis, movement, checks{...}, baseline, recent, change, change_pct, noise_sd, effect_sd, kendall_tau|z, p_value, onset_week, trend_window, window_weeks, consistency, outliers[], latest_week_outlier, emerging}`.
Trend finding: standard finding with `classification`, `evidence.computed`, `evidence.calculation` and `evidence.outliers_excluded`.
Correlation finding: `{type: "correlation", causal_claim: false, evidence.computed: {r, r_differences, n, common_drivers[{metric, r_with_first, r_with_second, partial_r}]}}`.

## Decision rules — the minimum evidence threshold

**Level and count metrics** (weekly values). A series is a trend only if **all** of these hold:

| # | Condition | Threshold |
|---|---|---|
| 1 | Enough data | ≥ 8 valid, non-outlier weeks |
| 2 | Monotonic | Mann-Kendall \|τ\| ≥ 0.4 and p ≤ 0.05, same sign as the change |
| 3 | Material | \|recent median − baseline median\| ≥ 10% of baseline (or ≥ 3 pp for % metrics) |
| 4 | Beyond noise | that change ≥ 2 × the week-to-week noise (robust sd of differences / √2; for counts at least √baseline) |
| 5 | Persistent | the last 3 weeks all lie beyond baseline ± 1 noise unit |
| 6 | Long enough | trend window (onset → last week) ≥ 5 weeks |

Baseline = weeks 1–6 and recent = weeks 13–16, both as medians. Onset = the first week from which ≥ 80% of later weeks are beyond baseline ± noise.

**Rates** (event ratios such as change-failure rate, escape rate). Weekly rates built on about 9 deployments or 3 defects are too noisy, and overlapping rolling windows are autocorrelated, which makes Mann-Kendall overconfident. So rates are judged on **pooled counts**: a two-proportion z-test of weeks 1–6 vs weeks 13–16 (p ≤ 0.05, ≥ 3 pp, effect ≥ 2 standard errors, ≥ 20 baseline / 12 recent events). The rolling 4-week pooled rate is used only to find the onset and check persistence.

**Other classes:**
- `ONE_TIME_ANOMALY`: not a trend, and 1–2 isolated outliers (robust z ≥ 3.5 against the ±2-week local median).
- `VOLATILE`: more than 2 outliers, or a robust coefficient of variation > 0.35 (except low-volume counts with median < 3).
- `STABLE`: otherwise.
- An outlier in the **latest week** is never called one-time (nobody knows yet whether it persists). It is excluded from the fit and flagged `latest_week_outlier`.
- `emerging`: a persistent, material shift that is too young (< 5 weeks) to call a trend.

**Why a single-week spike can never be a trend:** it fails conditions 5 and 6 by construction.

**Correlations:** only between outcome metrics that each passed the trend test, never between metrics in the same `definition_group` (e.g. success rate = 100 − failure rate). The rule is |r| ≥ 0.8 over ≥ 8 weeks. For each pair the agent also reports the correlation of week-over-week differences, and a partial correlation controlling for headcount whenever headcount correlates ≥ 0.8 with both metrics.

## Failure conditions
Agent 02 output missing or FAILED → the agent refuses to run.

## Validation rules
Agent 08 recomputes the baseline and recent values (or pooled counts), checks that the trend window contains enough elevated weeks, and checks that the change survives removing the most extreme week. A spike presented as a trend is REJECTED (`test_spike_presented_as_trend_rejected`). Unit tests cover the rule on a spike, a ramp and a short shift.

## Dependencies
02 Metrics Analysis.

## Example input
`team:Atlas / cycle_time_days`: `[3.2, 3.2, 3.3, 3.3, 3.3, 3.2, 3.2, 3.4, 3.5, 4.0, 4.3, 4.2, 4.3, 4.5, 5.2, 5.1]`.

## Example output (real run)
```json
{"id": "TRD-ATLAS-ALL-CYCLE_TIME_DAYS", "classification": "DETERIORATING", "weeks": [8, 16],
 "claim": "Atlas: Cycle time has been rising since week 8 - DETERIORATING. Median 3.245 days in weeks 1-6 vs 4.525 in weeks 13-16 (+39%).",
 "evidence": {"calculation": "Mann-Kendall tau=0.7905 (p=5e-05); baseline median=3.245, recent median=4.525, change=1.28 (39.45%), noise sd=0.0996 -> effect=12.85 sd; Theil-Sen slope=0.115/week; trend window weeks 8-16 (9 weeks)"},
 "confidence": {"score": 0.96}}
```
