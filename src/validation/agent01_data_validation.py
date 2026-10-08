"""Agent 01 - Data Validation.  Spec: agents/01_data_validation_agent.md

Gatekeeper. Checks that the raw data is usable before any analysis happens and tells
downstream agents exactly how to handle each problem (`analysis_directives`).
Fully deterministic: no reasoning layer is needed here.

Run:  python -m src.validation.agent01_data_validation
"""
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

from jsonschema import Draft202012Validator, FormatChecker

from src.common.envelope import AGENTS, write_envelope
from src.config import load_json, load_settings, project_path
from src.data.loader import DATASETS, raw_dir as default_raw_dir, read_dataset, without_meta

AGENT = AGENTS["01"]
PK = {"services": "service_id", "weekly_metrics": "record_id", "deployments": "deployment_id",
      "incidents": "incident_id", "defects": "defect_id"}
EVENT_DATE = {"deployments": "deployed_on", "incidents": "opened_on", "defects": "reported_on"}
EVENT_PREFIX = {"deployments": "DEP", "incidents": "INC", "defects": "DEF"}

# What happens to a problem nobody has approved an exception for.
DEFAULT_HANDLING = {
    "schema": "treat_as_missing",
    "duplicate": "exclude_duplicate",
    "WM-R02": "use_event_records",
    "WM-R04": "use_event_records",
    "service_mismatch": "exclude_record",
}


class Validator:
    def __init__(self, raw, settings, thresholds, exceptions):
        self.raw = raw
        self.settings = settings
        self.cfg = thresholds["data_validation"]
        self.exceptions = exceptions
        self.issues = []
        self.data = {}
        self.schemas = {}
        self.missing_files = []

    # ------------------------------------------------------------------ helpers
    def add(self, rule, severity, dataset, record_id, message, field=None, value=None, line=None, kind=None):
        self.issues.append({
            "id": f"DQ|{rule}|{dataset}|{record_id}|{field or '-'}|{line or '-'}",
            "rule": rule, "severity": severity, "dataset": dataset, "record_id": record_id,
            "field": field, "value": value, "line": line, "message": message,
            "default_handling": DEFAULT_HANDLING.get(kind or rule, "report_only"),
        })

    def load(self):
        for ds in DATASETS:
            try:
                self.data[ds], self.schemas[ds] = read_dataset(ds, self.raw)
            except FileNotFoundError as e:
                self.missing_files.append(ds)
                self.add("FILE", "CRITICAL", ds, "-", str(e))

    # ------------------------------------------------------------------ checks
    def check_columns(self, ds):
        rows, schema = self.data[ds], self.schemas[ds]
        if not rows:
            self.add("EMPTY", "CRITICAL", ds, "-", f"{ds}.csv has no rows")
            return
        present = set(rows[0]) - {"_line"}
        for col in sorted(set(schema["required"]) - present):
            self.add("COLUMNS", "CRITICAL", ds, "-", f"Required column '{col}' is missing", field=col)
        for col in sorted(present - set(schema["properties"])):
            self.add("COLUMNS", "MAJOR", ds, "-", f"Unexpected column '{col}'", field=col)

    def check_schema(self, ds):
        rows, schema = self.data[ds], self.schemas[ds]
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        pk = PK[ds]
        for row in rows:
            rid = row.get(pk)
            clean = without_meta(row)
            for field in schema["required"]:
                if row.get(field) is None:
                    self.add("schema", "MAJOR", ds, rid, f"Missing required value '{field}'",
                             field=field, line=row["_line"])
            for err in validator.iter_errors(clean):
                field = err.path[0] if err.path else None
                if err.validator in ("additionalProperties", "required"):
                    continue  # reported by check_columns / the explicit missing-value check above
                self.add("schema", "MAJOR", ds, rid, f"{field}: {err.message}",
                         field=field, value=clean.get(field), line=row["_line"])

    def check_unique(self, ds):
        pk = PK[ds]
        seen = {}
        rule = {"services": "SVC-R01", "weekly_metrics": "WM-R01"}.get(ds, f"{EVENT_PREFIX.get(ds, ds)}-R01")
        severity = "CRITICAL" if ds in ("services", "weekly_metrics") else "MAJOR"
        for row in self.data[ds]:
            key = row.get(pk)
            if key in seen:
                exact = without_meta(row) == without_meta(seen[key])
                self.add(rule, severity, ds, key,
                         f"Duplicate {pk} (first seen on line {seen[key]['_line']})"
                         + ("; rows are exact copies" if exact else "; rows differ"),
                         line=row["_line"], kind="duplicate")
            else:
                seen[key] = row

    def check_services(self):
        pairs = Counter((r["team"], r["platform"]) for r in self.data["services"])
        for (team, platform), n in pairs.items():
            if n > 1:
                self.add("SVC-R02", "CRITICAL", "services", f"{team}/{platform}", f"{n} services for one team/platform")

    def check_weekly(self):
        rows = self.data["weekly_metrics"]
        g = self.settings["generator"]
        start, n_weeks = date.fromisoformat(g["start_date"]), g["n_weeks"]
        valid_pairs = {(r["team"], r["platform"]) for r in self.data["services"]}

        grain = Counter((r["week"], r["team"], r["platform"]) for r in rows)
        for key, n in grain.items():
            if n > 1:
                self.add("WM-R01", "CRITICAL", "weekly_metrics", f"W{key[0]}/{key[1]}/{key[2]}", f"{n} rows for one week/team/platform")

        events = Counter()
        failed = Counter()
        rolled = Counter()
        for r in self.deduplicated("deployments"):
            k = (r["week"], r["team"], r["platform"])
            events[k] += 1
            failed[k] += r["status"] == "FAILED"
            rolled[k] += r["rolled_back"] is True

        headcount = defaultdict(set)
        for r in rows:
            rid, line = r["record_id"], r["_line"]
            k = (r["week"], r["team"], r["platform"])
            ints = all(isinstance(r.get(f), int) for f in ("deployments", "successful_deployments", "failed_deployments", "rollbacks"))
            if ints and r["successful_deployments"] + r["failed_deployments"] != r["deployments"]:
                self.add("WM-R02", "CRITICAL", "weekly_metrics", rid,
                         f"successful ({r['successful_deployments']}) + failed ({r['failed_deployments']}) "
                         f"!= deployments ({r['deployments']})", field="deployments", value=r["deployments"], line=line)
            if ints and r["rollbacks"] > r["failed_deployments"]:
                self.add("WM-R03", "MAJOR", "weekly_metrics", rid, "rollbacks exceed failed deployments", field="rollbacks", line=line)
            if ints and (r["deployments"], r["failed_deployments"], r["rollbacks"]) != (events[k], failed[k], rolled[k]):
                self.add("WM-R04", "MAJOR", "weekly_metrics", rid,
                         f"Weekly (deployments, failed, rollbacks) = {(r['deployments'], r['failed_deployments'], r['rollbacks'])} "
                         f"but deployment events give {(events[k], failed[k], rolled[k])}",
                         field="deployments", value=r["deployments"], line=line)
            if isinstance(r.get("lead_time_days"), float) and isinstance(r.get("cycle_time_days"), float) \
                    and r["lead_time_days"] < r["cycle_time_days"]:
                self.add("WM-R05", "MINOR", "weekly_metrics", rid, "lead time shorter than cycle time", field="lead_time_days", line=line)
            if isinstance(r.get("week"), int):
                expected = (start + timedelta(days=7 * (r["week"] - 1))).isoformat()
                if r["week_start"] != expected:
                    self.add("WM-R07", "CRITICAL", "weekly_metrics", rid,
                             f"week_start {r['week_start']} != expected {expected} for week {r['week']}", field="week_start", line=line)
            if (r["team"], r["platform"]) not in valid_pairs:
                self.add("WM-R08", "CRITICAL", "weekly_metrics", rid, f"{r['team']}/{r['platform']} is not in services.csv", kind="service_mismatch")
            headcount[(r["week"], r["team"])].add(r["team_headcount"])

        for (week, team), values in sorted(headcount.items(), key=str):
            if len(values) > 1:
                self.add("WM-R06", "MINOR", "weekly_metrics", f"W{week}/{team}", f"Inconsistent headcount {sorted(values, key=str)}", field="team_headcount")

        present = {(r["week"], r["team"], r["platform"]) for r in rows}
        for week in range(1, n_weeks + 1):
            for team, platform in sorted(valid_pairs):
                if (week, team, platform) not in present:
                    self.add("WM-R07", "CRITICAL", "weekly_metrics", f"W{week}/{team}/{platform}", "Missing weekly row")

    def check_events(self, ds):
        g = self.settings["generator"]
        start, n_weeks = date.fromisoformat(g["start_date"]), g["n_weeks"]
        owner = {r["service_id"]: (r["team"], r["platform"]) for r in self.data["services"]}
        prefix = EVENT_PREFIX[ds]
        for r in self.data[ds]:
            rid, line = r[PK[ds]], r["_line"]
            if not isinstance(r.get("week"), int) or not 1 <= r["week"] <= n_weeks:
                self.add(f"{prefix}-R02", "MAJOR", ds, rid, f"week {r.get('week')} outside 1..{n_weeks}", field="week", line=line)
                continue
            ws = start + timedelta(days=7 * (r["week"] - 1))
            try:
                d = date.fromisoformat(r[EVENT_DATE[ds]])
                if not ws <= d <= ws + timedelta(days=6):
                    self.add(f"{prefix}-R02", "MAJOR", ds, rid, f"{EVENT_DATE[ds]} {d} is outside week {r['week']}", field=EVENT_DATE[ds], line=line)
            except (TypeError, ValueError):
                pass  # already reported by the schema check
            if owner.get(r["service_id"]) != (r["team"], r["platform"]):
                self.add(f"{prefix}-R03", "CRITICAL", ds, rid, f"{r['service_id']} is not owned by {r['team']}/{r['platform']}",
                         field="service_id", line=line, kind="service_mismatch")
            if ds == "deployments" and r["rolled_back"] is True and r["status"] != "FAILED":
                self.add("DEP-R04", "MINOR", ds, rid, "rolled back but not FAILED", field="rolled_back", line=line)

    def deduplicated(self, ds):
        seen, out = set(), []
        for r in self.data[ds]:
            if r[PK[ds]] not in seen:
                seen.add(r[PK[ds]])
                out.append(r)
        return out

    # ------------------------------------------------------------------ exceptions & result
    def match_exception(self, issue):
        for exc in self.exceptions:
            if exc["dataset"] != issue["dataset"] or exc["record_id"] != issue["record_id"]:
                continue
            if exc["rule"] != issue["rule"]:
                continue
            if exc.get("field") and issue["field"] and exc["field"] != issue["field"]:
                continue
            return exc
        return None

    def run(self):
        self.load()
        for ds in DATASETS:
            if ds in self.missing_files:
                continue
            self.check_columns(ds)
            self.check_schema(ds)
            self.check_unique(ds)
        if not self.missing_files:
            self.check_services()
            self.check_weekly()
            for ds in EVENT_DATE:
                self.check_events(ds)
        return self.result()

    def result(self):
        issues, warnings, directives = [], [], {"exclude_records": [], "null_fields": []}
        for issue in sorted(self.issues, key=lambda i: i["id"]):
            exc = self.match_exception(issue)
            issue["exception_id"] = exc["id"] if exc else None
            handling = exc["handling"] if exc else issue["default_handling"]
            issue["handling"] = handling
            if handling == "exclude_duplicate" or handling == "exclude_record":
                directives["exclude_records"].append({"dataset": issue["dataset"], "record_id": issue["record_id"], "line": issue["line"], "reason": issue["id"]})
            elif handling == "treat_as_missing" and issue["field"]:
                directives["null_fields"].append({"dataset": issue["dataset"], "record_id": issue["record_id"], "field": issue["field"], "reason": issue["id"]})
            (warnings if exc or issue["severity"] == "MINOR" else issues).append(issue)

        total = sum(len(v) for v in self.data.values())
        affected = {(i["dataset"], i["record_id"]) for i in self.issues if i["record_id"] != "-"}
        penalty = sum(self.cfg["score_penalty"][i["severity"]] for i in self.issues)
        score = round(max(0.0, 100 * (1 - len(affected) / max(1, total)) - penalty), 1) if total else 0.0

        blocking = [i for i in issues if i["severity"] == "CRITICAL"]
        if blocking or score < self.cfg["min_quality_score"]:
            status = "FAIL"
        elif issues or warnings:
            status = "WARN"
        else:
            status = "PASS"
        excluded = len({(d["dataset"], d["line"]) for d in directives["exclude_records"]})
        return {
            "status": status,
            "data_quality_score": score,
            "issues": issues,
            "warnings": warnings,
            "validated_records": total - excluded,
            "total_records": total,
            "records_per_dataset": {ds: len(rows) for ds, rows in self.data.items()},
            "blocking_issues": [i["id"] for i in blocking],
            "analysis_directives": directives,
            "counts": dict(Counter(i["severity"] for i in self.issues)),
        }


def run(raw=None, exceptions_path=None):
    settings = load_settings()
    thresholds = load_json(project_path("config/thresholds.json"))
    exc_path = exceptions_path or project_path("config/known_exceptions.json")
    exceptions = load_json(exc_path)["exceptions"] if exc_path.exists() else []
    raw = raw or default_raw_dir()

    v = Validator(raw, settings, thresholds, exceptions)
    res = v.run()

    findings = [{
        "id": i["id"], "type": "data_quality", "claim": i["message"], "severity": i["severity"],
        "dimension": {"dataset": i["dataset"]},
        "evidence": {"dataset": i["dataset"], "record_ids": [i["record_id"]], "line": i["line"], "field": i["field"], "value": i["value"]},
        "rule": i["rule"], "exception_id": i["exception_id"], "handling": i["handling"], "produced_by": AGENT,
    } for i in res["issues"] + res["warnings"]]
    inputs = [raw / f"{ds}.csv" for ds in DATASETS if (raw / f"{ds}.csv").exists()]
    if exc_path.exists():
        inputs.append(exc_path)
    summary = {k: res[k] for k in ("data_quality_score", "validated_records", "total_records", "records_per_dataset", "counts", "blocking_issues")}
    summary["issues"] = len(res["issues"])
    summary["warnings"] = len(res["warnings"])
    write_envelope(AGENT, res["status"], [], inputs, summary, findings,
                   errors=[f"Blocking issue: {b}" for b in res["blocking_issues"]],
                   data_quality_score=res["data_quality_score"], issues=res["issues"], warnings=res["warnings"],
                   validated_records=res["validated_records"], analysis_directives=res["analysis_directives"])
    return res


def main():
    res = run()
    print(f"[{AGENT}] status={res['status']} score={res['data_quality_score']} "
          f"records={res['validated_records']}/{res['total_records']} "
          f"issues={len(res['issues'])} warnings={len(res['warnings'])}")
    for i in res["issues"] + res["warnings"]:
        tag = f"excepted by {i['exception_id']}" if i["exception_id"] else "NOT EXCEPTED"
        print(f"  {i['severity']:<8} {i['rule']:<8} {i['dataset']}/{i['record_id']} {i['field'] or ''} - {i['message']} [{tag}; {i['handling']}]")
    if res["status"] == "FAIL":
        print("Validation gate FAILED - downstream analysis must not run. Resolve the data or add a documented "
              "entry to config/known_exceptions.json, then re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
