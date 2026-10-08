# CLAUDE.md — Agentic Engineering Health Intelligence System

Instructions for any AI assistant (and any human) working in this repository. Read this
before changing anything. The original brief is in [input/MainPrompt.md](input/MainPrompt.md).

---

## 1. Project purpose

This system answers one question for engineering leadership:

> What is the current health of our engineering organisation, what is changing, what risks
> are emerging, why might they be happening, and what actions should leadership consider?

It does that by running **synthetic** engineering data through a pipeline of narrow,
contract-bound agents. The pipeline produces validated, evidence-backed insights, and then
turns them into an interactive dashboard, an executive deck, an executive report and
design documentation.

It is a **learning exercise** in how agentic systems are really built. The workflow is
*See → Try → Fail → Ask AI → Fix → Repeat*. Understandable beats clever, and failures
must be visible, never hidden.

**Hard boundary:** synthetic data and generic engineering concepts only. Never use, request
or infer real company data, internal systems, credentials, repositories, Jira projects or
customer information. Every team and service name in `config/org.json` is fictional.

---

## 2. Architecture

```
config/ ──► src/data/generate_synthetic_data.py ──► data/raw/*.csv (+ MANIFEST.json)
                                                        │
                                   01 Data Validation ◄─┘   (gate: FAIL stops the run)
                                                        │
                            ┌───────── Orchestrator (src/orchestration) ─────────┐
                            │  02 Metrics ─┬─► 04 Trends ─┐                      │
                            │              ├─► 05 Anomalies├─► 06 Risk ─► 07 Coach │
                            │  03 Quality ─┘               ┘                      │
                            └──────────────────────────┬──────────────────────────┘
                                                        ▼
                                   08 Evidence Validation (PASS / WARN / REJECT)
                                                        │   REJECT → finding removed;
                                                        │   affected agent may be re-run
                              ┌─────────────────────────┼─────────────────────────┐
                              ▼                         ▼                         ▼
                     09 Dashboard              10 Executive report           Diagrams
                     (dashboard/)              + deck (output/)              (output/diagrams)
```

The diagrams in `output/diagrams/` are the authoritative version. They are generated from
the real implementation in Phase 7. Update this sketch if they diverge.

### Agents

| # | Agent | Responsibility | Kind |
|---|---|---|---|
| 01 | Data Validation | Schema, missing values, duplicates, ranges, dates, relationships and aggregate reconciliation. Produces a data-quality score. **Gate:** downstream work does not run on FAIL unless the issue is listed as a known exception. | Deterministic |
| 02 | Metrics Analysis | Current vs previous values, absolute and % change, direction (improving or deteriorating, which depends on the metric's polarity), ranking across teams and platforms. | Deterministic |
| 03 | Quality Analysis | Defects, severity mix, escape rate, regression rate, coverage, change-failure rate. Flags improving or deteriorating quality and possible leading indicators. | Deterministic signals + reasoning |
| 04 | Trend Analysis | Classifies every metric series over the full history: IMPROVING / STABLE / DETERIORATING / VOLATILE / ONE_TIME_ANOMALY / INSUFFICIENT_DATA, with a documented minimum-evidence threshold. | Deterministic signals + reasoning |
| 05 | Anomaly Detection | Unusual single observations, with baseline, magnitude, period, dimension, supporting records and confidence. Tells anomalies apart from trends. | Deterministic signals + reasoning |
| 06 | Risk Analysis | Turns validated signals into risks (Delivery, Quality, Reliability, Operational, Efficiency, Sustainability). Phrasing: *observed evidence → possible explanation → confidence*. Never asserts a root cause. | Reasoning over structured inputs |
| 07 | Engineering Coach | Specific, prioritised, evidence-proportional recommendations: problem, evidence, action, expected outcome, owner type, priority, success measure. | Reasoning over structured inputs |
| 08 | Evidence Validation | Challenges every finding: supported? source records identifiable? calculation correct? trend or anomaly? causality claimed? confidence appropriate? recommendation follows? → PASS / WARN / REJECT. | Deterministic re-checks + reasoning |
| 09 | Dashboard Generation | Interactive HTML dashboard built only from validated outputs. Drill-down from KPI → metric → team/platform → week → source record. | Deterministic rendering |
| 10 | Executive Report | Executive report and PowerPoint built only from validated outputs. Every number must match the analysis. | Deterministic rendering + narrative |

Each agent has a specification in `agents/NN_<name>_agent.md`. The spec is the contract and
the code in `src/` implements it. If they disagree, that is a bug: fix one of them, don't
work around it.

### Where the "AI" lives (design decision)

Reasoning agents are built as two layers. **No API key is required.**

1. **Deterministic core (always runs).** Rule-based Python implements every decision rule
   written in the agent spec. This keeps runs reproducible, idempotent and testable, and
   lets the whole pipeline run from a plain terminal.
2. **Claude Code reasoning layer.** The agent specs are also exposed as Claude Code
   subagents. When the pipeline runs inside a Claude Code session, Claude adds the
   interpretation and narrative: risk explanations, coaching wording and the executive
   summary. It uses the user's existing Claude Code login, so there is no
   `ANTHROPIC_API_KEY` and no direct API calls from `src/`. Claude only receives structured,
   already-computed evidence, never does arithmetic, and writes its output to a file that
   goes through the same Evidence Validation agent as everything else.

The final analytical numbers never depend on the reasoning layer. Only wording may differ.
If the reasoning layer has not run, the deterministic wording is used and outputs say so.

---

## 3. Operating principles

- **Evidence before conclusions.** Every finding carries the records and calculation that support it.
- **Deterministic calculations where possible.** Code computes percentages, deltas, slopes and correlations. An LLM never does arithmetic.
- **No unsupported claims.** If evidence is missing, the finding is downgraded or rejected, not reworded.
- **Explicit confidence.** Confidence comes from the documented model (§6). Arbitrary numbers are not allowed.
- **Correlation ≠ causation.** Use "is associated with" / "may indicate". Claiming a cause requires evidence the data cannot provide, so in this system it is always REJECTED.
- **Traceability.** Insight ID → metric(s) → dataset → record IDs → calculation → producing agent → validation result → recommendation.
- **Idempotency.** The same inputs give byte-identical analytical outputs. IDs are deterministic, outputs are overwritten (never appended), and analytical payloads carry no timestamps (run timestamps go in the run log only).
- **Reproducibility.** Seeded generation (`config/settings.json`). `data/raw/MANIFEST.json` records the hash of every raw file.
- **Separation of concerns.** Data (`data/`, `src/data`), analysis (`src/analysis`), validation (`src/validation`), orchestration (`src/orchestration`) and presentation (`src/reporting`, `dashboard/`) do not import across layers except through the documented contracts.
- **Human-readable artifacts.** JSON with stable key order and indentation, Markdown docs, CSV raw data.
- **Fail loudly.** A missing required input raises an error that names the file. A failed gate stops the run with a clear reason.
- **Never fabricate data.** Agents only report what is in the inputs.
- **Never silently change source data.** `data/raw/` is read-only to every agent. Corrections become documented exceptions, not edits.

---

## 4. Agent communication contract

Agents talk only through JSON files in `data/processed/`, one file per agent:
`data/processed/NN_<agent_name>.json`. Every file uses the same envelope:

```json
{
  "agent": "04_trend_analysis",
  "schema_version": "1.0",
  "input_fingerprint": "sha256 of the input files/envelopes this output was derived from",
  "status": "PASS | WARN | FAIL",
  "depends_on": ["01_data_validation", "02_metrics_analysis"],
  "summary": {},
  "findings": [
    {
      "id": "TRD-ATLAS-ALL-CYCLE_TIME_DAYS",
      "type": "trend | metric_change | anomaly | quality_signal | risk | recommendation",
      "claim": "Plain-language statement of the finding.",
      "metrics": ["cycle_time_days"],
      "dimension": {"team": "Atlas", "platform": null},
      "weeks": [7, 16],
      "evidence": {
        "dataset": "weekly_metrics",
        "record_ids": ["WM-W07-ATLAS-WEB", "..."],
        "values": {"7": 3.2, "16": 5.1},
        "calculation": "Theil-Sen slope over weeks 7-16 = +0.21 days/week; +59% vs baseline"
      },
      "confidence": {"score": 0.0, "components": {}},
      "produced_by": "04_trend_analysis",
      "related_findings": [],
      "validation": null
    }
  ],
  "errors": []
}
```

Rules:
- Finding IDs are deterministic: `<PREFIX>-<TEAM|ALL>-<PLATFORM|ALL>-<METRIC>[-W<week>]`.
- `validation` is filled in only by agent 08 (`{"verdict": "PASS|WARN|REJECT", "checks": [...], "reasons": [...]}`).
- Agents 09 and 10 consume **only** findings whose verdict is PASS or WARN. WARN findings are visibly marked.
- An agent whose dependency is missing or has `status: FAIL` must refuse to run and say which dependency is missing.

---

## 5. Data

- Raw data: `data/raw/` (five CSVs + `MANIFEST.json`), produced by `python -m src.data.generate_synthetic_data`.
- Schemas: `data/schemas/*.schema.json` (JSON Schema 2020-12 + `x-` extensions for units, grain and cross-record rules). Human view: [data/schemas/DATA_DICTIONARY.md](data/schemas/DATA_DICTIONARY.md), regenerated with `python -m src.data.schema_docs`.
- Planted signals and injected data-quality issues are listed in `tests/ground_truth/planted_signals.json`. **That file is a test oracle. No agent may read it.** Detection that peeks at the answer key is not detection.

---

## 6. Confidence model (to be implemented in Phase 2)

Confidence is in [0, 1] and is computed, never chosen:

| Component | Weight | Meaning |
|---|---|---|
| Data completeness | 0.20 | Share of expected records present and valid for the series |
| Observations | 0.20 | Number of points behind the claim relative to the threshold (saturates) |
| Consistency | 0.25 | How consistently the series moves in the claimed direction (e.g. share of same-sign week-over-week changes, fit quality) |
| Magnitude | 0.15 | Size of the effect relative to normal variation (robust z / % of baseline, saturating) |
| Evidence quality | 0.10 | Source records are identifiable and recompute to the claimed value |
| Validation | 0.10 | 1.0 PASS, 0.5 WARN, 0 REJECT (applied by agent 08) |

The exact formulas will live in `src/validation/confidence.py` and be documented in the agent specs.

---

## 7. Quality standards — what a successful run means

A run counts as successful only when **all** of these hold. "The files exist" is not success.

1. Data Validation finishes with PASS, or WARN where every issue is listed as a known exception.
2. Every planted signal is found and classified correctly (checked against the ground truth by tests, never by agents).
3. The one-week anomaly is reported as `ONE_TIME_ANOMALY`, not as a trend.
4. No finding claims causation. The misleading correlation is reported, if at all, as association with a WARN or REJECT.
5. Every finding shown in an executive output has a validation verdict of PASS or WARN, plus traceable record IDs.
6. The same numbers appear in the analysis JSON, the dashboard and the deck (an automated consistency test).
7. Running the pipeline twice produces identical analytical outputs.
8. `python -m unittest discover -s tests -t .` passes.

---

## 8. Development workflow

```
Inspect → Design → Implement → Run → Validate → Identify failure → Fix → Rerun → Package
```

- Build in phases (see the brief, section 32). Do not start the dashboard or deck until the analytical pipeline passes.
- After each change, **run it** and check the outputs, not just that the code executes.
- Record meaningful failures and their fixes in `README.md` → *Development log*. Hiding failures defeats the purpose of the exercise.
- Keep agent responsibilities narrow. If an agent needs data that another agent owns, read that agent's output file instead of recomputing it.

### Commands

```bash
python -m src.data.generate_synthetic_data     # (re)generate raw data — deterministic
python -m src.data.schema_docs                 # regenerate DATA_DICTIONARY.md
python -m unittest discover -s tests -t . -v   # run all tests
```

### Environment

Python 3.12, standard library plus `jsonschema` and `python-pptx` (`requirements.txt`).
No pandas or numpy, which keeps every calculation readable. Tests use `unittest`.
The dashboard is plain HTML/CSS/JS with no build step.

---

## 9. Current status

- [x] Phase 1: foundation (structure, schemas, generator, data dictionary, Phase 1 tests)
- [ ] Phase 2: agents 01–08 (specs + implementation + tests)
- [ ] Phase 3: orchestration
- [ ] Phase 4: full-run validation
- [ ] Phase 5: dashboard
- [ ] Phase 6: executive report and PowerPoint
- [ ] Phase 7: architecture and sequence diagrams
- [ ] Phase 8: final QA and self-critique loop
