# Engineering Health Intelligence System — System Design

_Status: implemented and tested. Diagrams are generated from the code (`python -m src.reporting.diagrams`) and live in [output/diagrams](../diagrams/README.md)._

## 1. Problem and goal

Engineering leaders see dashboards of numbers but need answers: *what is the health of the organisation, what is changing, which risks are emerging, why might that be, and what should we do?* This system answers those questions from engineering telemetry (synthetic here). It does so with **evidence-backed, validated** conclusions instead of summaries, and every number can be traced back to source records.

Non-goals: real company data, live integrations, root-cause claims the data cannot support.

## 2. Design principles

| Principle | How it is enforced |
|---|---|
| Numbers come from code, never from an LLM | All arithmetic in `src/`; the AI layer may only reword validated findings, and ingest rejects any narrative that introduces a number |
| Evidence before conclusions | Every finding carries record ids, values and its calculation; Agent 08 recomputes them |
| Correlation is not causation | Causal-language check; hypotheses need hedging; confounded or co-trending associations are rejected |
| Fail loudly | Validation gate (`BLOCKED`), crash handling (`ERROR`), output consistency checks, explicit "data not loaded" page |
| Never edit source data | Data problems become documented exceptions plus analysis directives |
| Idempotent and reproducible | Seeded generation, deterministic ids, no timestamps in analytical outputs, clean-slate runs; a test asserts byte-identical reruns |
| Traceability | Insight → metric → dataset → records → calculation → agent → validation → recommendation, shown in the dashboard and the deck |

## 3. Architecture

![Architecture](../diagrams/architecture.svg)

Layers:
1. **Data layer:** `config/` (settings, metric catalog, thresholds, approved exceptions), the deterministic generator, and five CSV datasets with JSON Schemas and a manifest of hashes.
2. **Validation gate (Agent 01):** schema, duplicates, ranges, calendar, relationships and aggregate reconciliation. It produces a quality score and `analysis_directives`. A critical issue without an exception stops the run.
3. **Analysis agents (02–07):** metrics with traceable series; trend and anomaly detection in parallel; quality analysis on top of their classifications; risk analysis (deliberately wide-net); recommendations with owners and measurable targets.
4. **Evidence validation (Agent 08):** an independent critic that recomputes, tests trend versus anomaly, checks causal language and confounders, and cascades rejections. Its `rerun_requests` drive the feedback loop.
5. **Outputs (09, 10):** dashboard and executive deck/report, built only from PASS/WARN findings, each with its own consistency checks.
6. **Reasoning layer (optional):** Claude Code subagents write narratives from a brief of validated findings; ingest validates them; only accepted narratives are shown.

### Agent contracts
Agents communicate only through JSON envelopes in `data/processed/` (`agent`, `schema_version`, `input_fingerprint`, `status`, `depends_on`, `summary`, `findings`, `errors`). Findings have deterministic ids and a common shape (claim, metrics, dimension, weeks, evidence, confidence, validation). Specs: [agents/](../../agents/).

## 4. Runtime behaviour

![Sequence](../diagrams/sequence.svg)

- **Success path:** clean slate → 01 → 02 → (04 ∥ 05) → 03 → 06 → 07 → 08 → feedback loop if needed → 09 → 10 → run log.
- **Validation FAIL:** the pipeline is `BLOCKED` and the blocking issues are printed. The user fixes the data or approves a documented exception, then re-runs.
- **Evidence REJECT:** findings are rejected and the rejection cascades. If recommendations depended on them, Agent 07 is re-run without them and Agent 08 re-validates (at most 2 rounds).
- **Crash or failed output check:** `ERROR`, dependants skipped, exit code 1. Outputs must not be used.

## 5. Data model
Five datasets (services, weekly metrics, deployments, incidents, defects), described field by field in [DATA_DICTIONARY.md](../../data/schemas/DATA_DICTIONARY.md). Event-level datasets are the source of truth for counts and rates. The weekly table carries aggregates (cycle time, coverage, CI). The metric catalog (`config/metrics.json`) defines how 28 metrics are derived, plus their polarity, KPI, risk category and definition group (metrics linked by arithmetic are never reported as correlations of each other).

## 6. Analytical methods
- **Trends:** level and count metrics need Mann-Kendall significance, a material change (% or pp), an effect beyond noise, persistence and at least 5 weeks. Rates use pooled counts with a two-proportion test, because rolling windows are autocorrelated and make tests overconfident.
- **Anomalies:** robust local baseline for levels; a binomial test for rates; minimum event counts for averages; pattern classification (isolated spike / sustained shift / unresolved).
- **Risk attribution:** platform-level when two or more teams contribute (noise bar scaled by √n), otherwise team-level; definition groups keep one phenomenon in one risk.
- **Confidence:** six named components with documented weights; analysis agents publish analytical confidence and Agent 08 adds the validation verdict.

## 7. Quality assurance
- 70+ automated tests: data, agents, adversarial validator tests, orchestration failure paths, dashboard logic (Node), deck consistency, diagrams.
- Output consistency, raw ↕ analysis ↕ dashboard ↕ deck: Agent 09 and Agent 10 re-read their outputs and compare them with the sources and with each other.
- The quality gate (`python run.py check`) answers the brief's self-evaluation questions with automated evidence, in `output/reports/quality_gate.md`.

## 8. Security and privacy
Synthetic data only; no credentials and no external calls. The reasoning layer treats the brief as data and its output as untrusted until validated. The dashboard has no third-party scripts; fonts come from Google Fonts with system fallbacks.

## 9. Limitations
Synthetic data with one service per team and platform; 16 weeks is a short history; small weekly samples limit what rate changes can be proven (Phoenix's escape rate is directional only); the health index is relative, not absolute; the narrative "no new numbers" check matches numbers per finding, not per metric.

## 10. Future production architecture
| Concern | This exercise | Production direction |
|---|---|---|
| Ingestion | Synthetic CSV generator | Connectors to delivery (CI/CD), code review, incident and defect systems, landing raw events in a warehouse; the same schemas become data contracts |
| Validation | Agent 01 on files | The same rules as warehouse data tests, with exceptions approved in a review workflow |
| Orchestration | In-process DAG, `python run.py` | A scheduled workflow engine (e.g. Airflow, Dagster) running the same DAG; envelopes stored in a database with lineage |
| Reasoning | Claude Code subagents on demand | Claude via API inside the workflow, with the same brief → validate → accept contract and audit logging |
| Outputs | Static dashboard, generated deck | The dashboard served from the warehouse with access control; deck generation on a cadence; risk register integration |
| Governance | Tests, quality gate | CI on every change, drift monitoring on thresholds, human sign-off for exceptions and executive outputs |
