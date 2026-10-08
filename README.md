# Agentic Engineering Health Intelligence System

A multi-agent pipeline that turns raw (synthetic) engineering metrics into validated,
evidence-backed insights for engineering leadership. It produces an interactive dashboard,
an executive deck, an executive report and architecture documentation.

> **Status: Phases 1–6 of 8 complete.** Synthetic data, the eight analytical agents, the
> orchestrator, the Claude Code reasoning layer, the interactive dashboard, and the executive
> deck and report are built, run and tested (61 Python tests + 11 dashboard tests). The
> architecture and sequence diagrams and the final QA pass are next. See [CLAUDE.md §9](CLAUDE.md#9-current-status).

## Why it exists

Dashboards show numbers. Leaders need to know which numbers matter, whether a change is a
trend or a blip, how sure we are, and what to do about it. This project shows how to build
that reasoning as a chain of small, inspectable agents rather than one giant prompt. Each
agent has a contract, explicit evidence and a validator that is allowed to say "no".

It is also a learning exercise in the *See → Try → Fail → Ask AI → Fix → Repeat* loop, so
failures are recorded below instead of hidden.

All data is synthetic. No real company, system or person is represented.

## Architecture

See [CLAUDE.md §2](CLAUDE.md#2-architecture) for the full picture and agent table. In short:

```
synthetic data → 01 validation (gate) → 02 metrics, 03 quality → 04 trends, 05 anomalies
→ 06 risk → 07 coach → 08 evidence validation → 09 dashboard / 10 report + deck
```

Calculations are deterministic Python. AI reasoning (interpretation and narrative) is
supplied by Claude Code subagents when you run the pipeline inside Claude Code, using your
existing Claude login, so no API key is needed. It never affects the numbers, and its
output is validated like everything else.

## Agents

Each agent has a specification in [`agents/`](agents/): purpose, responsibilities, inputs,
outputs, schemas, decision rules, failure conditions, validation rules, dependencies and a
real example. Code lives in `src/validation/` (01, 08) and `src/analysis/` (02–07).

| Agent | What it decided on this dataset |
|---|---|
| 01 Data Validation | Caught all 4 planted data defects. **FAILs** without approved exceptions; WARN (score 93.8) with them |
| 02 Metrics Analysis | 20 scopes × 28 metrics × 16 weeks, each point traceable to source records |
| 04 Trend Analysis | Atlas deteriorating, Data platform deteriorating, Phoenix improving; the week-11 spike is *not* a trend |
| 05 Anomaly Detection | Nova/Mobile week 11 across 5 metrics, plus 4 marginal detections |
| 03 Quality Analysis | Atlas quality deteriorating, Phoenix improving; coverage leads defects by 1 week at Atlas (association) |
| 06 Risk Analysis | 7 risks (2 critical) and 11 candidate explanations |
| 07 Engineering Coach | 8 recommendations with owners, priorities and measurable targets |
| 08 Evidence Validation | 291 findings checked: 276 PASS, 11 WARN, 4 REJECT, including the misleading Titan correlation |

## Data model

Five datasets in `data/raw/`, each described by a JSON Schema in `data/schemas/`. The
full field-by-field reference is in [data/schemas/DATA_DICTIONARY.md](data/schemas/DATA_DICTIONARY.md).

| Dataset | Grain | Rows | Purpose |
|---|---|---|---|
| `services.csv` | service | 10 | Reference: which team owns which service on which platform |
| `weekly_metrics.csv` | week × team × platform | 160 | Delivery, code-health, testing, CI and ops aggregates |
| `deployments.csv` | deployment | ~1.5k | Source records for deployment success, failure and rollbacks |
| `incidents.csv` | incident | ~100 | Source records for incidents, severity and MTTR |
| `defects.csv` | defect | ~580 | Source records for defects, severity, escapes and regressions |

The dataset covers 5 fictional teams (Atlas, Nova, Orion, Phoenix, Titan), 4 platforms
(Web, Mobile, Services, Data) and 16 weeks (2026-06-15 → 2026-10-04).

### Planted signals

The generator deliberately plants patterns the agents must find, or must *not* misread:

| # | Signal | Where |
|---|---|---|
| 1 | Gradually deteriorating team: cycle time ↑, PR review time ↑, defects ↑, coverage ↓ | one team, second half of the period |
| 2 | Deployment instability: failed deployments ↑, rollbacks ↑, incidents ↑ | one platform |
| 3 | Sustained improvement: coverage ↑, cycle time ↓, escapes ↓, deploy success ↑ | one team |
| 4 | One-week spike that must **not** be called a trend | one team/platform, one week |
| 5 | Two metrics that correlate strongly but are not causally linked (hidden common driver) | one team |
| 6 | Four injected data-quality defects: duplicate, missing value, invalid value, inconsistent total | various |

The exact answer key is in `tests/ground_truth/planted_signals.json`. Only tests may read
it. The agents have to find the signals on their own.

## How to run

Requirements: Python 3.12+.

```bash
pip install -r requirements.txt
```

### Regenerate synthetic data

```bash
python -m src.data.generate_synthetic_data
```

The output is deterministic: the same `config/settings.json` always produces byte-identical
files (hashes are recorded in `data/raw/MANIFEST.json`). Change `seed` to get a different but
equally structured dataset.

### Regenerate the data dictionary

```bash
python -m src.data.schema_docs
```

### Run the analysis

```bash
python run.py
```

This runs agents 01–08 in dependency order (04 and 05 in parallel) in under a second.
Outputs land in `data/processed/`, one JSON envelope per agent plus `metric_series.json`.
A run log goes to `output/reports/run_log.json`. The exit code is 1 if the pipeline is
blocked or an agent crashes.

**Try the failure paths:**
- Rename `config/known_exceptions.json` and run again. The data-validation gate FAILs, nothing downstream runs, and the blocking issue is named.
- Lower `trend.min_effect_sd` in `config/thresholds.json` and watch noise become "trends". Then see which ones Agent 08 still lets through.

### Run the AI reasoning layer (inside Claude Code)

Ask Claude Code to *"run the health pipeline"*, which uses the `run-health-pipeline` skill. Or do it step by step:

```bash
python run.py brief
```

Then ask Claude Code to run the `risk-narrator` and `engineering-coach-writer` subagents, and finally validate what they wrote:

```bash
python run.py ingest
```

The subagents only write wording. Any narrative that introduces a number not present in the
evidence, claims a cause, is generic, or was written for older evidence is rejected, and the
deterministic wording is used instead.

### Open the dashboard

`python run.py` regenerates it (Agent 09, the last step). Then either open
`dashboard/index.html` directly in a browser, or serve it:

```bash
python -m http.server 8765 --directory dashboard
```

Then browse to http://localhost:8765. Things to try:
- Click a KPI card, then a metric, a team, a week and a record. That's the full drill-down to the raw CSV row.
- Use "Why is this flagged?" on a risk to see the evidence, the surviving explanations, the severity arithmetic and the traceability chain.
- Switch between 4, 8, 12 and 16 weeks, and set the scope to a team or platform.

No build step and no internet connection are needed; fonts fall back to system fonts when offline.

### Executive deck and report

`python run.py` also writes (Agent 10, the final step):
- `output/presentation/engineering_health_review.pptx`: 14 slides with native, editable charts and speaker notes.
- `output/reports/executive_report.md`: the same story in prose and tables.

Agent 10 refuses to finish (`ERROR`) unless:
- every number in the deck and the report is in its fact sheet;
- every chart series equals its source;
- headline facts recomputed from the raw CSVs agree;
- the deck agrees with the dashboard;
- qualitative titles are true in the data.

The fact sheet, with the source of every number, is in `data/processed/10_executive_report.json`.

### Publish the dashboard

```bash
python -m src.reporting.publish_dashboard
```

This writes `dashboard/artifact.html`, a copy of the page without the outer HTML skeleton, for hosting platforms that add their own. Publish it together with the `css/`, `js/` and `data/` files.

### Diagrams

Not built yet (Phase 7).

## Testing

```bash
python -m unittest discover -s tests -t . -v
```

49 tests in three files:
- `test_orchestration.py`:
  - dependency order and parallel layer;
  - the orchestrated run is byte-identical to a sequential run;
  - the validation gate blocks and leaves no stale outputs;
  - an agent crash stops its dependants;
  - **a forced evidence rejection makes the orchestrator re-run agent 07 and re-validate**;
  - the reasoning-layer guard rails (new numbers, causal claims, generic text, stale or unknown findings).
- `test_synthetic_data.py`: generation is deterministic and matches the manifest; rows conform to schemas except the injected issues (and the check provably catches those); aggregates reconcile; each planted signal is visible in the raw data.
- `test_agents.py`:
  - calculations: percentages, week-over-week, Mann-Kendall, correlation, two-proportion test, and the trend rule on a spike, a ramp and a short shift
  - each agent's output against the ground truth
  - failure handling: missing dependency, validation FAIL blocking downstream, missing file, bad date
  - **the evidence validator rejecting deliberately broken findings**
  - idempotency: two full runs are byte-identical

## Limitations

- The data is synthetic and simpler than reality: one service per team/platform, no seasonality, no holidays, independent noise.
- Weekly aggregates such as cycle time are generated directly, not derived from work-item records, so they can only be traced to the weekly row, not to individual items.
- 16 weeks is a short history for trend statistics. Thresholds are tuned for it and documented in the agent specs.

## Future production architecture

To be written in Phase 7. Expected direction: replace the generator with connectors to
delivery, CI, incident and defect systems; keep the same schemas and agent contracts; run the
pipeline on a schedule; store envelopes in a database instead of JSON files.

## Development log

Meaningful failures and how they were fixed.

| # | Phase | What failed | Why | Fix |
|---|---|---|---|---|
| 1 | 1 | The Data-platform incident trend (signal 2) was too weak: 7 incidents in week 15, then 0 in week 16, the "current" week. | The planted rate increase was small relative to Poisson noise. | Raised the planted incident and deployment-failure rates. |
| 2 | 1 | After the fix, week 16 still showed 0 Data incidents (about a 1-in-1,000 chance at the new rate). | Deployments, incidents, defects and weekly metrics shared **one random stream per row**. Changing the deployment logic shifted every later draw, so signals were coupled by accident. | Gave each record type its own seeded stream. Signals are now independent, and tuning one cannot silently change another. |
| 3 | 2 | Agent 01 reported the missing coverage value twice. | Both my explicit missing-value check and jsonschema's `required` rule fired. | Skipped jsonschema's `required` errors; the explicit check gives a clearer message. |
| 4 | 2 | The top correlations were "success rate vs change-failure rate" (r = 1.0), which crowded out the real Titan throughput ↔ build time pair. | Those metrics are linked **by definition** (they sum to 100%); their correlation is guaranteed and meaningless. | Added `definition_group` to the metric catalog and never pair metrics within a group; context metrics (headcount) are used as common-driver controls instead of being paired. |
| 5 | 2 | Phoenix's improving deployment success and escape rate were not detected. | Weekly rates from about 9 deployments or 3 defects swing 0–38% on noise alone; success rate near 100% barely moves in relative terms. | Rates are judged in percentage points on pooled counts. |
| 6 | 2 | Fix #5 first used a rolling 4-week pooled rate with Mann-Kendall, and Nova and Orion suddenly showed "deteriorating" rates that were never planted. | **Overlapping windows are autocorrelated**: neighbouring points share 3 of 4 weeks, so a test that assumes independence becomes overconfident and finds trends in noise. | Replaced it with a two-proportion z-test on baseline vs recent pooled counts. False positives disappeared. |
| 7 | 2 | Agent 05 reported 96 anomalies with z-scores around 10¹⁰. | A local median failure rate of 0% gave a noise estimate of 0, so any single failure became an "infinite" spike. MTTR averaged over one incident did the same. | Binomial test for rates, minimum event counts, and no anomaly testing of single-incident MTTR. Result: 9 anomalies, 5 of them the planted spike. |
| 8 | 2 | Risk attribution oscillated: first the Data platform problem was split into team risks, then Atlas's cycle time was pulled into a "Services platform" risk by another team's +7% noise. | My "does another team contribute?" rule was too strict, then too lenient. | A contributing team must show the full magnitude and a consistent direction, with the noise bar scaled by √(teams on the platform), because each team's slice holds 1/n of the events. |
| 9 | 2 | Phoenix's escape-rate improvement (17% → 4%) is **still not** called a trend. | It rests on 6 of 36 vs 1 of 24 defects: p = 0.14. | **Not a bug.** Kept the threshold and recorded it in the ground truth as "directional only". A system that reported it as a trend would be overclaiming. |
| 10 | 2 | A test caught that the "replicate Phoenix's practices" recommendation contained no numbers. | That template was the one place generic advice slipped through. | The action now cites the improvements it is based on. |
| 11 | 2 | Risk evidence read "5.435 -> 27.059 (+398%)". | Raw floats, and a relative % of a rate exaggerates. | Shared formatter: "5.4% -> 27.1% (+21.6 pp)". Rates use percentage points everywhere, including the severity "large change" rule. |
| 12 | 3 | The two new subagents could not be called by name. | Claude Code loads `.claude/agents/` when a session starts; they were created mid-session. | In this session they ran as general-purpose agents told to follow their definition files exactly. In a new session they work by name. |
| 13 | 3 | 1 of 15 subagent narratives was rejected for "causal language". | A **false positive in my validator**: the narrative said "an identified one-off *cause*" (a noun, from my own playbook wording), and the regex could not tell it from the verb. | "cause" after a determiner or adjective ("a / the / root / one-off cause") is treated as a noun. Regression test added. All 15 narratives then passed. |
| 14 | 3 | A new test failed on a correct narrative. | A bug **in the test**: results were keyed by the first 12 characters, and three narratives began "Data platfor", overwriting each other. | Key by full text. A reminder that test failures need diagnosing, not just fixing. |
| 15 | 5 | Trend charts shaded a red "deteriorating window" on organisation cycle time, which is classified STABLE. | Every shifted series gets an onset week, and the chart shaded any series that had one. | Shade only IMPROVING / DETERIORATING series. A chart must never contradict the classification next to it. |
| 16 | 5 | The y-axis read "3 d, 3 d, 3 d". | Ticks 2.8 / 3.0 / 3.2 were formatted with 0 decimals. | Decimals derived from the tick step. |
| 17 | 5 | The page scrolled sideways on a phone-width screen. | Grid columns sized to their content (`1fr` without `minmax(0, …)`), and a wide audit table. | `minmax(0, 1fr)` tracks, a one-column layout below 420px, and scroll containers for wide tables. Checked at 272px: no horizontal scroll. |
| 18 | 5 | The risk severity showed "0 points" in the evidence panel. | Agent 09's field allowlist dropped `severity_points` and `severity_breakdown`. | Added the fields and rendered the arithmetic in words ("4 deteriorating metrics (+4) · … = 7 points → CRITICAL"). |
| 19 | 5 | After regenerating, the browser kept showing the **old** data. | The browser cached `dashboard_data.js`: the stale-output problem again, this time in the browser. | Agent 09 stamps the script tag with a content hash (`?v=…`), and a consistency check verifies it. |
| 20 | 5 | When the local server dropped the data request, the page crashed silently. | No guard for missing data. | The page now shows an explicit "data not loaded, run `python run.py`" error instead of a broken or empty view. |
| 21 | 5 | Accessibility warning: focus stayed inside the closed drawer. | The drawer was hidden from screen readers while it still held keyboard focus. | Focus returns to whatever opened the drawer, and the closed drawer is `inert`. |
| 22 | 5 | "What improved" listed Titan's deployments and throughput rising, with no context. | They're volume metrics, and Titan grew from 6 to 11 people. That's the same confounder Agent 08 used to reject the build-time explanation. | Volume improvements carry a headcount note. |
| 23 | 6 | Slides 5 and 9 showed Atlas cycle time as **4.5 d** and **4.8 d**. | Both were correct, a median of weeks 13–16 (trend test) and a mean (comparison table), but to an executive that is a contradiction. The "every number is sourced" check cannot catch it, because both numbers are sourced. | Every stat slide now states its statistic, and the table says "average". A lesson: consistency means the same *meaning*, not only the same source. |
| 24 | 6 | Two slide titles made hard-coded claims ("problems began between weeks 6 and 11"). | Small integers are exempt from the number check, so the claims were unverified. With the final trend selection the range was actually weeks 6–11, but only by luck. | Titles are computed from facts, and a `title_claims_hold` check verifies the qualitative ones. |
| 25 | 6 | Every chart axis started at 0, flattening the trends. | Chart defaults. | Value axes fitted to the data range. |
| 26 | 6 | A test failed: deck facts were traced to a **rejected** finding. | The evidence slide deliberately shows one rejected claim as an example, which the brief's "rejected findings must not appear" rule seemed to forbid. | Made the policy explicit: rejected content may appear only as a labelled rejection on the evidence slide, under a `rejected_example.` key. Two tests enforce it. |
| 27 | 6 | 1 of 15 new AI narratives was rejected for a "new number". | A third validator false positive: the narrative said "the **P1** reliability work", and the "1" was read as a quantity. | Priority labels and agent numbers are treated as identifiers. Regression test added; all 15 narratives then passed. |

## What I Learned

_Fill this in after experimenting with the system._

- What surprised me about building agents with contracts:
- A failure I caused on purpose, and what the system did:
- Where deterministic code beat LLM reasoning (and vice versa):
- What I would change about the agent boundaries:
- One thing I would do differently next time:
