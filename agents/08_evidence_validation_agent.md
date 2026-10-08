# Agent 08 — Evidence Validation

**Implementation:** [src/validation/agent08_evidence_validation.py](../src/validation/agent08_evidence_validation.py), confidence in [src/validation/confidence.py](../src/validation/confidence.py) · **Kind:** deterministic re-checks (reasoning layer output is validated here too) · **Output:** `data/processed/08_evidence_validation.json`

## Purpose
Challenge every other agent. Each finding from agents 02–07 receives **PASS**, **WARN** or **REJECT**. Rejected findings never reach executive outputs, and warnings are visibly marked.

## Responsibilities
Answer eight questions for every significant finding:

| # | Question | Checks |
|---|---|---|
| 1 | Is the claim supported by data? | `evidence_present` |
| 2 | Can the source records be identified? | `records_identifiable` (every id exists in the validated data) |
| 3 | Is the calculation correct? | `recomputed_*`: period means, baseline/recent medians, pooled counts, r, values, all recomputed from the series |
| 4 | Is this actually a trend? | `trend_window` (≥ 5 weeks, ≥ 3 elevated), `not_single_spike` (holds without the most extreme week) |
| 5 | Could this simply be an anomaly? | `anomaly_returns` (an isolated spike really returned), `anomaly_language` (no trend wording) |
| 6 | Is causality being incorrectly claimed? | `no_causal_claim` (un-negated causal language), `hedged`, `common_driver`, `co_trending_only` |
| 7 | Is confidence appropriate? | `confidence_consistent` (score = weighted components), `high_confidence_support` (≥ 0.8 needs ≥ 5 weeks), `magnitude` (marginal anomaly) |
| 8 | Does the recommendation logically follow? | `linked_finding_valid`, `success_metric_linked`, `priority_matches`, `evidence_refs_known` |

## Inputs
Envelopes 01–07, `metric_series.json`, the clean data (via 01's directives) for record identification, and `config/thresholds.json → evidence_validation, trend, anomaly, correlation, confidence`.

## Outputs
Envelope whose `findings` are **all** upstream findings, each with `validation` and a validated `confidence` (the analytical one is kept as `analytical_confidence`), plus `rejected[]`, `executive_findings[]` (PASS/WARN ids) and `rerun_requests[]`.

## Input schema
Standard findings (CLAUDE.md §4) of types `metric_change`, `trend`, `anomaly`, `correlation`, `quality_signal`, `hypothesis`, `risk`, `recommendation`.

## Output schema
```json
{"validation": {"verdict": "PASS|WARN|REJECT",
                "checks": [{"check": "", "result": "PASS|WARN|REJECT", "detail": ""}],
                "reasons": ["<check>: <detail>"], "validated_by": "08_evidence_validation"},
 "confidence": {"score": 0, "stage": "validated", "components": {"...": 0, "validation": 1.0}},
 "analytical_confidence": {}}
```

## Decision rules
- **Verdict** = the worst result among the finding's checks.
- **Order:** metric changes, trends, anomalies, correlations → quality signals → hypotheses → risks → recommendations. A rejection therefore **cascades**: a risk loses rejected supporting trends (REJECT if none remain, WARN if some do), and a recommendation on a rejected risk is REJECTED.
- **Causal language:** words like *causes, due to, because, drives, leads to, results in* are REJECTED unless negated within the preceding ~40 characters ("not evidence that one causes the other" is fine).
- **Hypotheses never PASS on correlation alone:**
  - REJECT if a measured common driver explains the association (partial r < 0.5 after controlling for it).
  - REJECT if the week-over-week changes are uncorrelated (|r| < 0.2), because the two series only share a time trend.
  - Otherwise WARN: "an association cannot establish contribution".
  - Record-level evidence (post-incident attribution, two-proportion test p ≤ 0.05) can PASS; when it is not significant it gets WARN.
- **Confidence model** (CLAUDE.md §6): `validated = Σ wᵢ·componentᵢ` with weights completeness 0.20, observations 0.20, consistency 0.25, magnitude 0.15, evidence quality 0.10, validation 0.10 (PASS 1.0, WARN 0.5, REJECT 0).
- **Re-run requests:** if any recommendation is rejected, `rerun_requests` asks the orchestrator to regenerate Agent 07 without the rejected risks.

## Validating the reasoning layer
The same principles apply to narratives written by the Claude Code subagents, checked by
`python run.py ingest` ([src/orchestration/reasoning.py](../src/orchestration/reasoning.py), reusing this agent's causal-language check):
`stale` (written for a different validation output), `known_finding` (exists and was not rejected),
`no_new_numbers` (every number appears in that finding's evidence, allowing rounding),
`no_causal_claim`, and `specific` (names the entity, ≤ 90 words). "Cause" used as a noun
("identify the root cause") is not a causal claim.

## Failure conditions
Any upstream envelope missing or FAILED → the agent refuses to run. This agent never "fixes" a finding: it only labels it and explains why.

## Validation rules (how we know the critic works)
`tests/test_agents.py::TestEvidenceValidator` feeds deliberately broken findings: a wrong calculation, unknown record ids, no evidence, causal wording, a spike presented as a trend, a recommendation on a rejected risk, and an unhedged hypothesis. Each one must be REJECTED, and a correct finding must PASS.

## Dependencies
01–07.

## Example input
Hypothesis from Agent 06: *"Throughput rose over the same period (r=0.9025); the change in throughput may be contributing to the change in build time."*

## Example output (real run)
```json
{"id": "RISK-TITAN-ALL-ENGINEERING_EFFICIENCY-H-THROUGHPUT_ITEMS",
 "validation": {"verdict": "REJECT", "reasons": ["common_driver: both metrics track team_headcount (r=0.9619, 0.9639); controlling for it the association drops to r=-0.339. A common driver explains the correlation - correlation is not causation."]},
 "confidence": {"score": 0.7, "stage": "validated"}}
```
