# Agent 10 — Executive Report

**Implementation:** [src/reporting/agent10_executive_report.py](../src/reporting/agent10_executive_report.py), fact sheet in [src/reporting/facts.py](../src/reporting/facts.py) · **Kind:** deterministic composition (wording rules in code; no number is typed by hand) · **Outputs:** `output/presentation/engineering_health_review.pptx`, `output/reports/executive_report.md`, `data/processed/10_executive_report.json`

## Purpose
Tell leadership a coherent, evidence-backed story (what changed, what is at risk, what to do) in a 14-slide deck and a written report, where **every number matches the analysis**.

## Responsibilities
- Build a **fact sheet** from validated outputs. Each fact has a key, a value, its display text and its source (finding id + field, series, or config).
- Compose 14 slides (title, executive summary, health score, what improved, what deteriorated, emerging trends, top risks, quality & reliability, team comparison, recommended actions, outcomes & measurement, how the system works, evidence & confidence, appendix) with **native, editable charts** and speaker notes.
- Write the same story as Markdown.
- Verify both outputs before declaring success.

## Inputs
Envelopes 01–08 and `metric_series.json`; `dashboard/data/dashboard_data.js` (Agent 09) for the cross-check; `config/thresholds.json`.

## Outputs
The `.pptx` and `.md` files, plus an envelope with `consistency_checks[]`, the full `fact_sheet[]` (key, value, text, source) and `chart_sources[]`.

## Input schema
Validated findings (CLAUDE.md §4) with `validation.verdict`; recommendations carry `headline`, `owner_type`, `priority` and `measurement_of_success`.

## Output schema
Fact: `{"key": "data.cfr.recent", "value": 27.059, "text": "27.1%", "source": "TRD-ALL-DATA-CHANGE_FAILURE_RATE_PCT.evidence.computed.recent"}`.
Chart source: `{"slide": 8, "series": "Data platform", "values": [...], "source": "metric_series platform:Data ..."}`.

## Decision rules
- **Only validated findings feed conclusions.** One rejected hypothesis is shown, on the evidence slide only, as a labelled "REJECTED EXAMPLE". Its facts use the `rejected_example.` prefix, and tests enforce both rules.
- **Titles state the message.** Quantitative titles use facts; qualitative titles ("Atlas trails on flow and quality") are verified by `title_claims_hold`.
- **Statistics are named.** Stat cards compare weeks 13–16 with weeks 1–6 using the trend test's own statistics (medians; pooled rates for percentages). The comparison table shows 4-week averages and says so. This prevents an apparent conflict (for example a 4.5 d median against a 4.8 d mean).
- **Charts** fit their value axis to the data, so trends are not flattened against zero.
- **Visual system:** ink and white with a deep-teal accent and semantic red, green and amber; Cambria headings, Calibri body (safe fonts that render true-to-width); dark title and closing slides.

## Failure conditions
A dependency missing or FAILED → refuses to run. Any consistency check failing → status FAIL, and the orchestrator reports `ERROR` ("outputs must not be used").

## Validation rules
| Check | What it proves |
|---|---|
| `deck_opens` | the saved file re-opens with 14 slides (QA also opens it in PowerPoint and renders every slide) |
| `deck_numbers_sourced` | every number in slide text, tables and speaker notes is in the fact sheet (integers ≤ 22, such as weeks and slide numbers, are exempt) |
| `report_numbers_sourced` | the same for the Markdown report |
| `charts_match_sources` | every chart series in the saved file equals its source series |
| `raw_vs_analysis_*` | headline facts recomputed straight from the raw CSVs |
| `dashboard_agreement` | KPI, risk order and confidences identical to the dashboard data |
| `title_claims_hold` | qualitative title claims are true in the data |

`tests/test_reporting.py` also proves an invented number is caught, and that rejected content appears only as the labelled example.

## Dependencies
01–08, and 09 for the cross-check. It runs after the evidence feedback loop.

## Example input
`TRD-ALL-DATA-CHANGE_FAILURE_RATE_PCT` (PASS): pooled baseline 5/92 = 5.4%, recent 23/85 = 27.1%.

## Example output (real run)
Slide 8 title: *"Data platform: change failure rate rose from 5.4% to 27.1%"*, with a native line chart of the 4-week pooled rate (Data platform vs organisation) and stat cards for rollback rate 1.1% → 25.9%, incidents 1 → 5.5 per week, and on-call pages 7.5 → 14.5 per week. The CFR fact is also recomputed from `deployments.csv` (27.059%).
