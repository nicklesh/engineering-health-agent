# Agent 07 — Engineering Coach

**Implementation:** [src/analysis/agent07_engineering_coach.py](../src/analysis/agent07_engineering_coach.py) · **Kind:** playbook core + Claude Code reasoning layer for wording · **Output:** `data/processed/07_engineering_coach.json`

## Purpose
Translate risks, and improvements worth copying, into recommendations that are **specific, evidence-based, prioritised, actionable and proportional to the evidence**.

## Responsibilities
- One recommendation per risk, using the playbook entry for the risk's leading metric, filled with the real numbers, services and weeks.
- One "replicate" recommendation per team whose quality is IMPROVING (Agent 03), pointed at the teams whose quality is deteriorating.
- A measurable success criterion for each: metric, scope, baseline, target and deadline week.

## Inputs
`06_risk_analysis.json` (risks), `04_trend_analysis.json` (baselines), `03_quality_analysis.json` (improvements), `01_data_validation.json` (for service names via clean data), `metric_series.json`.

## Outputs
Envelope with `recommendation` findings.

## Input schema
Risk findings as specified in agent 06; classification records from agent 04.

## Output schema
```json
{"id": "REC-<ENTITY>-<CATEGORY | REPLICATE>", "type": "recommendation",
 "problem": "", "evidence": [], "evidence_refs": [],
 "recommended_action": "", "expected_outcome": "", "owner_type": "",
 "priority": "P1|P2|P3",
 "measurement_of_success": {"metric": "", "scope": "", "baseline": 0, "current": 0, "target": "", "by_week": 0},
 "related_findings": ["RISK-..."], "confidence": {}}
```

## Decision rules
- **Leading metric** (first match): coverage → defects → change-failure rate → failed deployments → incidents → on-call pages → PR review time → cycle time → PR size → review latency → build time → CI failure rate; disruption risks use the anomaly playbook.
- **Priority:** P1 if CRITICAL, or HIGH with confidence ≥ 0.85; P2 for other HIGH and MEDIUM; P3 for LOW.
- **Target:** back within one trend threshold of baseline (± 3 pp for rates, ± 10% otherwise), by current week + 6. For disruptions: no recurrence for 8 weeks.
- **Proportionality:** a LOW one-week disruption gets "confirm the post-incident review, act only if it recurs", not a programme of work.
- **Banned:** generic advice ("Improve quality."). Every action names the entity, the numbers and what to look at.
- **Reasoning layer:** may rewrite wording for clarity. It may not change the numbers, targets, owner, priority or links. Its output is re-validated by Agent 08.

## Failure conditions
Agent 06 output missing or FAILED → the agent refuses to run. A risk with no matching playbook entry raises an error rather than producing generic advice.

## Validation rules
Agent 08 REJECTs a recommendation whose linked risk was rejected (cascade), WARNs when the success metric is not one of the problem metrics or the priority does not match the severity. A test checks that every recommendation has all seven required fields and cites numbers.

## Dependencies
01, 03, 04, 06.

## Example input
`RISK-ALL-DATA-RELIABILITY` (CRITICAL, confidence 0.89).

## Example output (real run)
```json
{"id": "REC-ALL-DATA-RELIABILITY", "priority": "P1", "owner_type": "Platform / SRE lead",
 "recommended_action": "Run one joint failed-deployment review across the Data platform services (analytics-warehouse, event-pipeline): change failure rate 5.4% -> 27.1%, rollback rate 1.1% -> 25.9%, incidents 1 -> 5.5. Check which release-gating steps (pre-deploy checks, canary, automated rollback) the failing deployments bypassed.",
 "expected_outcome": "Fewer failed releases and change-related incidents on the platform.",
 "measurement_of_success": {"metric": "change_failure_rate_pct", "scope": "platform:Data", "baseline": 5.435, "current": 27.059,
                            "target": "<= 8.4% (baseline 5.4% plus/minus one trend threshold)", "by_week": 22}}
```
