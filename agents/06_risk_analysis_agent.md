# Agent 06 — Risk Analysis

**Implementation:** [src/analysis/agent06_risk_analysis.py](../src/analysis/agent06_risk_analysis.py) · **Kind:** rule-based core + Claude Code reasoning layer for narrative · **Output:** `data/processed/06_risk_analysis.json`

## Purpose
Convert signals into engineering risks a leader can act on, using the chain **observed evidence → possible explanation → confidence** and never **metric changed → therefore this is the cause**.

## Responsibilities
- Attribute each deteriorating trend to the right **entity** (a team or a platform).
- Group signals into one risk per entity and category; assign severity with documented points.
- Turn clusters of one-week anomalies into LOW "disruption" risks, never trend risks.
- Propose **possible explanations** (hypotheses) from correlations, leading indicators and record attributes.

**Design note: generator and critic.** This agent is deliberately *recall-oriented*. It proposes every risk and explanation the evidence could support, including doubtful ones. Agent 08 is *precision-oriented* and removes what does not survive. Rejections therefore stay visible instead of silently never being proposed.

## Inputs
Envelopes 01–05, `metric_series.json`, the clean incidents data (via 01's directives) for record-level hypotheses, and `config/thresholds.json → risk, trend`.

## Outputs
Envelope with `risk` findings (ranked) and `hypothesis` findings.

## Input schema
Agent 04 trend and correlation findings and `series_classifications`; Agent 05 anomaly findings; Agent 03 quality findings.

## Output schema
```json
{"id": "RISK-<ENTITY>-<CATEGORY>", "type": "risk", "rank": 1,
 "risk": "", "category": "Delivery|Quality|Reliability|Operational|Engineering efficiency|Sustainability",
 "severity": "LOW|MEDIUM|HIGH|CRITICAL", "severity_points": 0, "severity_breakdown": {},
 "evidence": ["human-readable line [finding id]"], "evidence_refs": [], "primary_refs": [],
 "confidence": {"score": 0, "components": {}}, "potential_impact": "", "recommended_follow_up": "",
 "possible_explanations": ["<hypothesis ids>"]}
{"id": "<risk id>-H-<...>", "type": "hypothesis", "basis": "correlation|leading_indicator|record_attribute", "claim": "... may be contributing ..."}
```

## Decision rules
1. **Attribution.** A platform-level DETERIORATING trend stays a **platform** risk when ≥ 2 teams on the platform contribute, and becomes that **team's** risk when exactly one contributes. A team "contributes" if its slice is DETERIORATING, or if it moves the same way with the full magnitude (≥ 10% / 3 pp), consistently (monotonic, significant or persistent), with effect ≥ 2 / √(teams on the platform). The √n accounts for each slice carrying 1/n of the events.
2. **Definition groups.** Team-level metrics in the same definition group as a platform risk (failed deployments, CFR, rollback rate) join the platform risk: they are one phenomenon. Success rate is dropped when CFR is present (exact complement).
3. **Category** comes from `config/metrics.json → risk_category`.
4. **Severity points:** 1 per deteriorating metric; +1 if any change is large (≥ 30%, or ≥ 10 pp for rates); +1 if the entity runs a tier-1 service; +1 for Reliability or Operational. CRITICAL ≥ 6, HIGH ≥ 4, MEDIUM ≥ 2, otherwise LOW.
5. **Disruption risks.** Adverse ISOLATED_SPIKE anomalies in the same scope and week, needing ≥ 2 metrics or |z| ≥ 6, are capped at **LOW**.
6. **Hypotheses.** Up to 2 per risk from correlations (one per explanatory metric), plus Agent 03 leading indicators, plus, for Reliability risks with incidents, the change in the share of incidents that post-incident reviews attributed to a change (two-proportion test). Every hypothesis is hedged ("may be contributing").
7. **Confidence** = component-wise mean of the supporting trends' confidences.

## Failure conditions
Any dependency missing or FAILED → the agent refuses to run. It never invents a root cause; if there is no hypothesis evidence, `possible_explanations` stays empty.

## Validation rules
Agent 08 REJECTs a risk whose supporting trends were all rejected, WARNs when only some were, REJECTs a disruption risk rated above LOW, and validates every hypothesis independently (hedging, common driver, co-trending, significance).

## Dependencies
01, 02, 03, 04, 05.

## Example input
Agent 04: `platform:Data` change-failure, rollback, failed-deployment and incident trends DETERIORATING; Orion and Titan both contribute.

## Example output (real run)
```json
{"id": "RISK-ALL-DATA-RELIABILITY", "rank": 1, "severity": "CRITICAL", "category": "Reliability",
 "risk": "Data: deployment and service reliability is deteriorating (change failure rate, failed deployments, incidents, rollback rate).",
 "evidence": ["Change failure rate: 5.4% -> 27.1% (+21.6 pp), trend since week 8 [TRD-ALL-DATA-CHANGE_FAILURE_RATE_PCT]", "..."],
 "severity_breakdown": {"deteriorating_metrics": 4, "large_change": ["change_failure_rate_pct", "..."], "tier1_service": true, "reliability_impact": true},
 "potential_impact": "More failed releases and customer-facing incidents on the affected services.",
 "possible_explanations": ["RISK-ALL-DATA-RELIABILITY-H-ON_CALL_PAGES", "RISK-ALL-DATA-RELIABILITY-H-CHANGE_RELATED"]}
```
