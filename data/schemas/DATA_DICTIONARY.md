# Data Dictionary

_Generated from `data/schemas/*.schema.json` by `python -m src.data.schema_docs`. Do not edit by hand._

## services

Reference table: one row per service, mapping it to its owning team and platform. Defines which (team, platform) pairs are valid.

- File: `data/raw/services.csv`
- Grain: one row per service_id
- Primary key: `service_id`

| Field | Type | Unit | Required | Allowed values | Meaning |
|---|---|---|---|---|---|
| `service_id` | string | id | yes | `^SVC-[A-Z]+-[A-Z]+$` | Service identifier: SVC-<TEAM>-<PLATFORM>. |
| `service_name` | string | text | yes | any | Human-readable service name (fictional). |
| `team` | string | category | yes | Atlas, Nova, Orion, Phoenix, Titan | Owning team. |
| `platform` | string | category | yes | Web, Mobile, Services, Data | Platform the service runs on. |
| `tier` | integer | ordinal | yes | >= 1; <= 3 | Business criticality: 1 = most critical. |

**Validation rules (beyond per-field checks):**

| Rule | Severity | Rule |
|---|---|---|
| SVC-R01 | CRITICAL | service_id is unique. |
| SVC-R02 | CRITICAL | (team, platform) is unique - one service per team/platform in this dataset. |

## weekly_metrics

One row per (week, team, platform). Weekly aggregate delivery, code-health, quality-practice, efficiency and operational metrics. Event counts (deployments) must reconcile with deployments.csv.

- File: `data/raw/weekly_metrics.csv`
- Grain: one row per week, team, platform
- Primary key: `record_id`

| Field | Type | Unit | Required | Allowed values | Meaning |
|---|---|---|---|---|---|
| `record_id` | string | id | yes | `^WM-W[0-9]{2}-[A-Z]+-[A-Z]+$` | Deterministic row id: WM-W<week>-<TEAM>-<PLATFORM>. |
| `week` | integer | week number | yes | >= 1; <= 52 | Sequential reporting week (1 = oldest). |
| `week_start` | string | date | yes | YYYY-MM-DD | Monday that starts the reporting week (ISO 8601). |
| `team` | string | category | yes | Atlas, Nova, Orion, Phoenix, Titan | Owning engineering team (fictional). |
| `platform` | string | category | yes | Web, Mobile, Services, Data | Technology platform the work ships on. |
| `team_headcount` | integer | people | yes | >= 1; <= 50 | Engineers on the team that week. Same value on every platform row for a team/week. |
| `deployments` | integer | count | yes | >= 0; <= 200 | Production deployments attempted. |
| `successful_deployments` | integer | count | yes | >= 0; <= 200 | Deployments that completed without failure. |
| `failed_deployments` | integer | count | yes | >= 0; <= 200 | Deployments that failed (and caused degraded service or needed remediation). |
| `rollbacks` | integer | count | yes | >= 0; <= 200 | Failed deployments that were rolled back. |
| `cycle_time_days` | number | days | yes | >= 0.1; <= 60 | Median time from first commit to production for items finished this week. |
| `lead_time_days` | number | days | yes | >= 0.1; <= 90 | Median time from work item creation to production. Must be >= cycle_time_days. |
| `throughput_items` | integer | count | yes | >= 0; <= 500 | Work items completed this week. |
| `pr_count` | integer | count | yes | >= 0; <= 1000 | Pull requests merged. |
| `pr_review_time_hours` | number | hours | yes | >= 0; <= 336 | Median time from PR opened to approved. |
| `avg_pr_size_loc` | integer | lines of code | yes | >= 1; <= 10000 | Mean lines changed per merged PR. |
| `review_latency_hours` | number | hours | yes | >= 0; <= 336 | Median time from PR opened to first review comment. |
| `rework_rate_pct` | number | percent | yes | >= 0; <= 100 | Share of changed lines that rewrite code less than 21 days old. |
| `test_coverage_pct` | number | percent | yes | >= 0; <= 100 | Line coverage of the team's services on this platform at week end. |
| `automated_test_pct` | number | percent | yes | >= 0; <= 100 | Share of test cases that are automated. |
| `build_time_min` | number | minutes | yes | >= 0.1; <= 240 | Median CI pipeline duration. |
| `ci_failure_rate_pct` | number | percent | yes | >= 0; <= 100 | Share of CI runs that failed. |
| `queue_time_min` | number | minutes | yes | >= 0; <= 240 | Median wait before a CI job starts. |
| `on_call_pages` | integer | count | yes | >= 0; <= 500 | On-call pages received. |
| `availability_pct` | number | percent | yes | >= 0; <= 100 | Measured availability of the team's services on this platform. |

**Validation rules (beyond per-field checks):**

| Rule | Severity | Rule |
|---|---|---|
| WM-R01 | CRITICAL | record_id is unique and (week, team, platform) is unique. |
| WM-R02 | CRITICAL | successful_deployments + failed_deployments == deployments. |
| WM-R03 | MAJOR | rollbacks <= failed_deployments. |
| WM-R04 | MAJOR | deployments, failed_deployments and rollbacks equal the counts of matching rows in deployments.csv. |
| WM-R05 | MINOR | lead_time_days >= cycle_time_days. |
| WM-R06 | MINOR | team_headcount is identical across all platform rows of the same team and week. |
| WM-R07 | CRITICAL | week_start == settings.start_date + 7 * (week - 1); weeks are contiguous; every (team, platform) in services.csv has a row for every week. |
| WM-R08 | CRITICAL | (team, platform) exists in services.csv. |

## deployments

One row per production deployment attempt. Source records for deployment metrics.

- File: `data/raw/deployments.csv`
- Grain: one row per deployment_id
- Primary key: `deployment_id`

| Field | Type | Unit | Required | Allowed values | Meaning |
|---|---|---|---|---|---|
| `deployment_id` | string | id | yes | `^DEP-W[0-9]{2}-[A-Z]+-[A-Z]+-[0-9]{3}$` | Deterministic id: DEP-W<week>-<TEAM>-<PLATFORM>-<seq>. |
| `week` | integer | week number | yes | >= 1; <= 52 | Reporting week the deployment belongs to. |
| `deployed_on` | string | date | yes | YYYY-MM-DD | Calendar date of the deployment. Must fall inside the reporting week. |
| `team` | string | category | yes | Atlas, Nova, Orion, Phoenix, Titan | Owning team. |
| `platform` | string | category | yes | Web, Mobile, Services, Data | Platform deployed to. |
| `service_id` | string | id | yes | `^SVC-[A-Z]+-[A-Z]+$` | Service deployed. Must belong to (team, platform) in services.csv. |
| `status` | string | category | yes | SUCCESS, FAILED | Deployment outcome. |
| `rolled_back` | boolean | boolean | yes | true / false | true if the deployment was rolled back. Only FAILED deployments are rolled back. |
| `duration_min` | number | minutes | yes | >= 0.1; <= 600 | Wall-clock duration of the deployment. |

**Validation rules (beyond per-field checks):**

| Rule | Severity | Rule |
|---|---|---|
| DEP-R01 | MAJOR | deployment_id is unique (duplicates are reported and excluded from analysis). |
| DEP-R02 | MAJOR | deployed_on falls within [week_start, week_start + 6 days] of its week. |
| DEP-R03 | CRITICAL | service_id belongs to the row's (team, platform). |
| DEP-R04 | MINOR | rolled_back == true implies status == FAILED. |

## incidents

One row per production incident. Source records for incident count, severity and MTTR.

- File: `data/raw/incidents.csv`
- Grain: one row per incident_id
- Primary key: `incident_id`

| Field | Type | Unit | Required | Allowed values | Meaning |
|---|---|---|---|---|---|
| `incident_id` | string | id | yes | `^INC-W[0-9]{2}-[A-Z]+-[A-Z]+-[0-9]{3}$` | Deterministic id: INC-W<week>-<TEAM>-<PLATFORM>-<seq>. |
| `week` | integer | week number | yes | >= 1; <= 52 | Reporting week the incident was opened in. |
| `opened_on` | string | date | yes | YYYY-MM-DD | Date the incident was opened. Must fall inside the reporting week. |
| `team` | string | category | yes | Atlas, Nova, Orion, Phoenix, Titan | Team owning the affected service. |
| `platform` | string | category | yes | Web, Mobile, Services, Data | Platform of the affected service. |
| `service_id` | string | id | yes | `^SVC-[A-Z]+-[A-Z]+$` | Affected service. |
| `severity` | string | category | yes | SEV1, SEV2, SEV3, SEV4 | SEV1 = full outage, SEV4 = minor degradation. |
| `mttr_minutes` | number | minutes | yes | >= 1; <= 10080 | Minutes from detection to recovery. |
| `change_related` | boolean | boolean | yes | true / false | true if the post-incident review attributed the trigger to a deployment/change. |

**Validation rules (beyond per-field checks):**

| Rule | Severity | Rule |
|---|---|---|
| INC-R01 | MAJOR | incident_id is unique. |
| INC-R02 | MAJOR | opened_on falls within its reporting week. |
| INC-R03 | CRITICAL | service_id belongs to the row's (team, platform). |

## defects

One row per defect reported. Source records for defect volume, severity, escape rate and regression rate.

- File: `data/raw/defects.csv`
- Grain: one row per defect_id
- Primary key: `defect_id`

| Field | Type | Unit | Required | Allowed values | Meaning |
|---|---|---|---|---|---|
| `defect_id` | string | id | yes | `^DEF-W[0-9]{2}-[A-Z]+-[A-Z]+-[0-9]{3}$` | Deterministic id: DEF-W<week>-<TEAM>-<PLATFORM>-<seq>. |
| `week` | integer | week number | yes | >= 1; <= 52 | Reporting week the defect was reported in. |
| `reported_on` | string | date | yes | YYYY-MM-DD | Date reported. Must fall inside the reporting week. |
| `team` | string | category | yes | Atlas, Nova, Orion, Phoenix, Titan | Team owning the defective service. |
| `platform` | string | category | yes | Web, Mobile, Services, Data | Platform of the defective service. |
| `service_id` | string | id | yes | `^SVC-[A-Z]+-[A-Z]+$` | Defective service. |
| `severity` | string | category | yes | CRITICAL, HIGH, MEDIUM, LOW | Defect severity. |
| `escaped` | boolean | boolean | yes | true / false | true if found in production (escaped pre-release testing). |
| `regression` | boolean | boolean | yes | true / false | true if the defect broke previously working behaviour. |

**Validation rules (beyond per-field checks):**

| Rule | Severity | Rule |
|---|---|---|
| DEF-R01 | MAJOR | defect_id is unique. |
| DEF-R02 | MAJOR | reported_on falls within its reporting week. |
| DEF-R03 | CRITICAL | service_id belongs to the row's (team, platform). |
