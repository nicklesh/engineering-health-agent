# Agent 01 — Data Validation

**Implementation:** [src/validation/agent01_data_validation.py](../src/validation/agent01_data_validation.py) · **Kind:** fully deterministic · **Output:** `data/processed/01_data_validation.json`

## Purpose
Make sure the dataset is usable before any analysis happens. This agent is the **gate**: if a critical problem is neither fixed nor listed as an approved exception, nothing downstream runs.

## Responsibilities
- Validate every row against its JSON Schema (types, ranges, enums, formats, required fields).
- Detect missing values, duplicate records and invalid values.
- Validate dates and weeks: `week_start` matches the configured calendar, weeks are contiguous, event dates fall inside their week.
- Validate relationships: every (team, platform) and `service_id` exists in `services.csv`.
- Reconcile aggregates: weekly deployment totals vs `successful + failed`, and vs the deployment event log (after duplicate removal).
- Produce a data-quality score and a PASS / WARN / FAIL status.
- Tell downstream agents exactly how to handle each problem (`analysis_directives`). **It never edits the source files.**

## Inputs
| Input | Path |
|---|---|
| Raw datasets | `data/raw/{services,weekly_metrics,deployments,incidents,defects}.csv` |
| Schemas | `data/schemas/*.schema.json` |
| Calendar | `config/settings.json` → `generator.start_date`, `n_weeks` |
| Approved exceptions | `config/known_exceptions.json` (optional; absent = no exceptions) |
| Score settings | `config/thresholds.json` → `data_validation` |

## Outputs
Envelope (see CLAUDE.md §4) plus these top-level fields:

| Field | Meaning |
|---|---|
| `status` | PASS (no issues) · WARN (issues exist, but all are non-critical or excepted) · FAIL (an un-excepted CRITICAL issue, or score < `min_quality_score`) |
| `data_quality_score` | 0–100 (formula below) |
| `issues` | problems **not** covered by an exception (MINOR ones are listed under `warnings`) |
| `warnings` | excepted problems and MINOR problems |
| `validated_records` | records usable after exclusions |
| `analysis_directives` | `exclude_records` (dataset + line) and `null_fields` (dataset + record + field) |

## Input schema
Each CSV must match `data/schemas/<dataset>.schema.json`. The human-readable version is [DATA_DICTIONARY.md](../data/schemas/DATA_DICTIONARY.md). Booleans are `true`/`false`, dates ISO `YYYY-MM-DD`, and an empty cell means missing.

`known_exceptions.json`:
```json
{"exceptions": [{"id": "EXC-001", "rule": "DEP-R01", "dataset": "deployments", "record_id": "...",
                 "field": "optional", "handling": "exclude_duplicate | treat_as_missing | use_event_records | exclude_record",
                 "reason": "...", "approved_by": "..."}]}
```

## Output schema
```json
{
  "status": "PASS|WARN|FAIL",
  "data_quality_score": 0.0,
  "issues": [Issue], "warnings": [Issue],
  "validated_records": 0,
  "analysis_directives": {"exclude_records": [{"dataset": "", "record_id": "", "line": 0, "reason": ""}],
                          "null_fields": [{"dataset": "", "record_id": "", "field": "", "reason": ""}]}
}
Issue = {"id": "DQ|<rule>|<dataset>|<record>|<field>|<line>", "rule": "", "severity": "CRITICAL|MAJOR|MINOR",
         "dataset": "", "record_id": "", "field": "", "value": null, "line": 0, "message": "",
         "exception_id": "EXC-... or null", "handling": ""}
```

## Decision rules
| Check | Rule id | Severity | Default handling (when no exception) |
|---|---|---|---|
| File missing or empty | FILE / EMPTY | CRITICAL | — |
| Required column missing | COLUMNS | CRITICAL | — |
| Missing / invalid value | schema | MAJOR | treat as missing (never imputed) |
| Duplicate weekly row / grain | WM-R01 | CRITICAL | — |
| Duplicate event id | DEP/INC/DEF-R01 | MAJOR | exclude the later copy |
| successful + failed ≠ deployments | WM-R02 | CRITICAL | use event records |
| rollbacks > failed | WM-R03 | MAJOR | report only |
| weekly totals ≠ event log (after dedup) | WM-R04 | MAJOR | use event records |
| lead time < cycle time | WM-R05 | MINOR | report only |
| headcount differs across a team's rows | WM-R06 | MINOR | report only |
| wrong `week_start`, missing week/team/platform row | WM-R07 | CRITICAL | — |
| unknown team/platform or service owner mismatch | WM-R08, *-R03 | CRITICAL | exclude record |
| event date outside its week | *-R02 | MAJOR | report only |

**Score** = `100 × (1 − affected_records / total_records) − Σ penalty(severity)` with penalties CRITICAL 2, MAJOR 1, MINOR 0.25 (excepted issues still count), floored at 0.
**Status**: FAIL if any un-excepted CRITICAL or score < 80; otherwise WARN if anything was found; otherwise PASS.

## Failure conditions
- Any CRITICAL issue without an approved exception → `status: FAIL`, the CLI exits with code 1, and agents 02–08 refuse to run (`DependencyFailedError`).
- A missing raw file is reported as a CRITICAL issue rather than a crash, so the reason shows up in the envelope.

## Validation rules (how we know this agent works)
- Every injected data-quality issue in the ground truth is reported (`tests/test_agents.py::test_01_detects_every_injected_issue`).
- Without `known_exceptions.json` the run FAILs and blocks Agent 02 (`test_validation_fail_blocks_downstream`).
- A deleted file and an impossible date are both caught (`test_missing_raw_file_fails_loudly`, `test_invalid_value_detected`).

## Dependencies
None. This is the first agent.

## Example input
`weekly_metrics.csv`, line for `WM-W10-PHOENIX-WEB`: `deployments=12, successful_deployments=10, failed_deployments=0`.

## Example output (real run)
```json
{"status": "WARN", "data_quality_score": 93.8, "validated_records": 2360,
 "warnings": [{"rule": "DEP-R01", "severity": "MAJOR", "record_id": "DEP-W05-NOVA-SERVICES-002",
   "message": "Duplicate deployment_id (first seen on line 385); rows are exact copies",
   "exception_id": "EXC-001", "handling": "exclude_duplicate"}, "..."]}
```
Without exceptions the same data gives `"status": "FAIL"`, blocked by `WM-R02` on `WM-W10-PHOENIX-WEB`.
