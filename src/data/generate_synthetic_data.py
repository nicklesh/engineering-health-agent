"""Synthetic engineering-data generator.

Produces five CSV files in data/raw/ plus a manifest, and writes the list of planted
signals to tests/ground_truth/planted_signals.json.

Design notes
------------
* Deterministic: every random stream is seeded from (settings seed, stream key), so the
  same settings always produce byte-identical files. Re-running overwrites; it never appends.
* Events first, aggregates second: deployment events are generated, then the weekly
  deployment counts are computed from them, so the two reconcile by construction.
  The only mismatch is the one deliberately injected as a data-quality issue.
* Planted signals are defined in SIGNALS below. The ground-truth file exists for TESTS
  ONLY - analysis agents must never read it, otherwise detection would be cheating.

Run:  python -m src.data.generate_synthetic_data
"""
import csv
import hashlib
import json
import math
import random
from datetime import date, timedelta

from src.config import ROOT, load_org, load_settings, project_path

# --------------------------------------------------------------------------------------
# Planted signals. Weeks are inclusive, 1-based. A ramp goes 0 -> 1 from start to end.
# --------------------------------------------------------------------------------------
DETERIORATING_TEAM = {"team": "Atlas", "start": 7, "end": 16}
IMPROVING_TEAM = {"team": "Phoenix", "start": 3, "end": 14}
UNSTABLE_PLATFORM = {"platform": "Data", "start": 8, "end": 16}
ANOMALY = {"team": "Nova", "platform": "Mobile", "week": 11}
CORRELATION_TEAM = {"team": "Titan", "headcount_from": 6, "headcount_to": 11}

DQ_DUPLICATE = {"team": "Nova", "platform": "Services", "week": 5}
DQ_MISSING = {"team": "Orion", "platform": "Services", "week": 6, "field": "test_coverage_pct"}
DQ_INVALID = {"team": "Titan", "platform": "Web", "week": 4, "field": "ci_failure_rate_pct", "value": 112.0}
DQ_INCONSISTENT = {"team": "Phoenix", "platform": "Web", "week": 10, "field": "deployments", "delta": 2}

INCIDENT_SEVERITIES = [("SEV1", 0.03), ("SEV2", 0.15), ("SEV3", 0.47), ("SEV4", 0.35)]
INCIDENT_MTTR_MEAN = {"SEV1": 190, "SEV2": 120, "SEV3": 60, "SEV4": 30}
DEFECT_SEVERITIES = [("CRITICAL", 0.05), ("HIGH", 0.20), ("MEDIUM", 0.45), ("LOW", 0.30)]

WEEKLY_FIELDS = [
    "record_id", "week", "week_start", "team", "platform", "team_headcount",
    "deployments", "successful_deployments", "failed_deployments", "rollbacks",
    "cycle_time_days", "lead_time_days", "throughput_items",
    "pr_count", "pr_review_time_hours", "avg_pr_size_loc", "review_latency_hours", "rework_rate_pct",
    "test_coverage_pct", "automated_test_pct",
    "build_time_min", "ci_failure_rate_pct", "queue_time_min",
    "on_call_pages", "availability_pct",
]
DEPLOYMENT_FIELDS = ["deployment_id", "week", "deployed_on", "team", "platform", "service_id",
                     "status", "rolled_back", "duration_min"]
INCIDENT_FIELDS = ["incident_id", "week", "opened_on", "team", "platform", "service_id",
                   "severity", "mttr_minutes", "change_related"]
DEFECT_FIELDS = ["defect_id", "week", "reported_on", "team", "platform", "service_id",
                 "severity", "escaped", "regression"]
SERVICE_FIELDS = ["service_id", "service_name", "team", "platform", "tier"]


# --------------------------------------------------------------------------------------
# Small deterministic helpers
# --------------------------------------------------------------------------------------
def rng_for(seed, *key):
    """Independent, reproducible random stream per key (string seeding is stable across runs)."""
    return random.Random(f"{seed}|" + "|".join(str(k) for k in key))


def ramp(week, start, end):
    if week <= start:
        return 0.0
    if week >= end:
        return 1.0
    return (week - start) / (end - start)


def poisson(rng, lam):
    """Knuth's algorithm - fine for the small rates used here."""
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def pick(rng, weighted):
    r, acc = rng.random(), 0.0
    for value, weight in weighted:
        acc += weight
        if r <= acc:
            return value
    return weighted[-1][0]


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def tag(name):
    return name.upper()


# --------------------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------------------
def team_headcount(team, base, week, n_weeks):
    if team == CORRELATION_TEAM["team"]:
        lo, hi = CORRELATION_TEAM["headcount_from"], CORRELATION_TEAM["headcount_to"]
        return round(lo + (hi - lo) * (week - 1) / (n_weeks - 1))
    return base


def baseline_profile(seed, team, platform):
    """Stable 'personality' of a team/platform: its normal operating levels."""
    r = rng_for(seed, "profile", team, platform)
    return {
        "cycle_time": r.uniform(2.4, 3.4),
        "lead_extra": r.uniform(1.0, 2.0),
        "pr_review": r.uniform(7.0, 11.0),
        "review_latency": r.uniform(2.5, 4.5),
        "pr_size": r.uniform(160, 260),
        "rework": r.uniform(8.0, 12.0),
        "coverage": r.uniform(68.0, 78.0),
        "automated": r.uniform(72.0, 85.0),
        "build_time": r.uniform(9.0, 14.0),
        "ci_fail": r.uniform(5.0, 9.0),
        "queue": r.uniform(2.0, 5.0),
        "on_call": r.uniform(2.0, 5.0),
        "availability": r.uniform(99.95, 99.99),
        "defect_rate": r.uniform(2.5, 4.5),
        "escape_p": r.uniform(0.14, 0.20),
        "regression_p": r.uniform(0.10, 0.14),
        "fail_p": r.uniform(0.04, 0.07),
        "incident_rate": r.uniform(0.25, 0.45),
    }


def generate(settings, org):
    g = settings["generator"]
    seed, n_weeks = g["seed"], g["n_weeks"]
    start = date.fromisoformat(g["start_date"])

    services = []
    for t in org["teams"]:
        for s in t["services"]:
            services.append({"service_id": s["service_id"], "service_name": s["service_name"],
                             "team": t["team"], "platform": s["platform"], "tier": s["tier"]})

    weekly, deployments, incidents, defects = [], [], [], []
    base_headcount = {t["team"]: t["base_headcount"] for t in org["teams"]}

    for week in range(1, n_weeks + 1):
        week_start = start + timedelta(days=7 * (week - 1))
        for svc in services:
            team, platform, sid = svc["team"], svc["platform"], svc["service_id"]
            p = baseline_profile(seed, team, platform)
            # Separate streams per record type, so a change in one (e.g. deployment logic)
            # never shifts the random draws of another.
            r = rng_for(seed, "week", week, team, platform)
            rd = rng_for(seed, "deployments", week, team, platform)
            ri = rng_for(seed, "incidents", week, team, platform)
            rf = rng_for(seed, "defects", week, team, platform)
            hc = team_headcount(team, base_headcount[team], week, n_weeks)
            key = f"W{week:02d}-{tag(team)}-{tag(platform)}"

            # Signal strengths for this row (0 when the signal does not apply).
            det = ramp(week, DETERIORATING_TEAM["start"], DETERIORATING_TEAM["end"]) if team == DETERIORATING_TEAM["team"] else 0.0
            imp = ramp(week, IMPROVING_TEAM["start"], IMPROVING_TEAM["end"]) if team == IMPROVING_TEAM["team"] else 0.0
            ins = ramp(week, UNSTABLE_PLATFORM["start"], UNSTABLE_PLATFORM["end"]) if platform == UNSTABLE_PLATFORM["platform"] else 0.0
            anom = team == ANOMALY["team"] and platform == ANOMALY["platform"] and week == ANOMALY["week"]
            growth = hc - CORRELATION_TEAM["headcount_from"] if team == CORRELATION_TEAM["team"] else 0

            def noisy(value, pct):
                return value * (1 + r.gauss(0, pct))

            # ---- Deployment events (source records) --------------------------------
            n_dep = max(2, round(rd.gauss(9 * hc / 7, 1.3)))
            fail_p = p["fail_p"] + 0.28 * ins
            if team == IMPROVING_TEAM["team"]:
                fail_p = 0.10 - 0.08 * imp  # Phoenix starts unreliable and improves
            rollback_p = 0.5 + 0.35 * ins
            n_failed = n_rolled = 0
            for i in range(1, n_dep + 1):
                failed = rd.random() < clamp(fail_p, 0.0, 0.9)
                rolled = failed and rd.random() < rollback_p
                n_failed += failed
                n_rolled += rolled
                deployments.append({
                    "deployment_id": f"DEP-{key}-{i:03d}", "week": week,
                    "deployed_on": (week_start + timedelta(days=rd.randint(0, 4))).isoformat(),
                    "team": team, "platform": platform, "service_id": sid,
                    "status": "FAILED" if failed else "SUCCESS", "rolled_back": rolled,
                    "duration_min": round(clamp(rd.gauss(22 if failed else 14, 4), 2, 120), 1),
                })

            # ---- Incident events -----------------------------------------------------
            inc_rate = p["incident_rate"] + 3.2 * ins
            n_inc = poisson(ri, inc_rate) + (5 if anom else 0)
            downtime = 0.0
            for i in range(1, n_inc + 1):
                forced = anom and i > n_inc - 5
                sev = "SEV2" if (forced and i == n_inc) else pick(ri, INCIDENT_SEVERITIES)
                mttr = round(clamp(ri.gauss(INCIDENT_MTTR_MEAN[sev], INCIDENT_MTTR_MEAN[sev] * 0.3), 5, 1440))
                if sev in ("SEV1", "SEV2"):
                    downtime += mttr
                elif sev == "SEV3":
                    downtime += mttr * 0.2
                incidents.append({
                    "incident_id": f"INC-{key}-{i:03d}", "week": week,
                    "opened_on": (week_start + timedelta(days=ri.randint(0, 6))).isoformat(),
                    "team": team, "platform": platform, "service_id": sid, "severity": sev,
                    "mttr_minutes": mttr,
                    "change_related": (not forced) and ri.random() < (0.3 + 0.5 * ins),
                })

            # ---- Defect events ---------------------------------------------------------
            n_def = poisson(rf, p["defect_rate"] * (1 + 1.0 * det) * (1 - 0.25 * imp) * (hc / base_headcount[team]) ** 0.5)
            escape_p = (p["escape_p"] + 0.10 * det) * (1 - 0.7 * imp)
            if team == IMPROVING_TEAM["team"]:
                escape_p = 0.24 * (1 - 0.7 * imp)
            regression_p = p["regression_p"] + 0.10 * det
            for i in range(1, n_def + 1):
                defects.append({
                    "defect_id": f"DEF-{key}-{i:03d}", "week": week,
                    "reported_on": (week_start + timedelta(days=rf.randint(0, 6))).isoformat(),
                    "team": team, "platform": platform, "service_id": sid,
                    "severity": pick(rf, DEFECT_SEVERITIES),
                    "escaped": rf.random() < escape_p, "regression": rf.random() < regression_p,
                })

            # ---- Weekly aggregate row -------------------------------------------------
            cycle = noisy(p["cycle_time"] * (1 + 0.65 * det) * (1 - 0.35 * imp), 0.05)
            coverage = p["coverage"] - 11 * det + 13 * imp + r.gauss(0, 0.5)
            if team == IMPROVING_TEAM["team"]:
                coverage = 64.0 + 13 * imp + r.gauss(0, 0.5)
            build = noisy(p["build_time"] * (1 + 0.06 * growth), 0.03) * (1.9 if anom else 1)
            weekly.append({
                "record_id": f"WM-{key}", "week": week, "week_start": week_start.isoformat(),
                "team": team, "platform": platform, "team_headcount": hc,
                "deployments": n_dep, "successful_deployments": n_dep - n_failed,
                "failed_deployments": n_failed, "rollbacks": n_rolled,
                "cycle_time_days": round(cycle, 2),
                "lead_time_days": round(cycle + noisy(p["lead_extra"], 0.08), 2),
                "throughput_items": max(0, round(noisy(hc * 1.6 * (1 - 0.15 * det), 0.07))),
                "pr_count": max(0, round(noisy(hc * 3.2, 0.08))),
                "pr_review_time_hours": round(noisy(p["pr_review"] * (1 + 0.8 * det) * (1 - 0.15 * imp), 0.06), 1),
                "avg_pr_size_loc": round(noisy(p["pr_size"] * (1 + 0.35 * det), 0.07)),
                "review_latency_hours": round(noisy(p["review_latency"] * (1 + 0.6 * det), 0.07), 1),
                "rework_rate_pct": round(clamp(p["rework"] + 6 * det - 2 * imp + r.gauss(0, 0.6), 0, 100), 1),
                "test_coverage_pct": round(clamp(coverage, 0, 100), 1),
                "automated_test_pct": round(clamp(p["automated"] - 6 * det + 10 * imp + r.gauss(0, 0.5), 0, 100), 1),
                "build_time_min": round(build, 1),
                "ci_failure_rate_pct": round(41.0 if anom else clamp(p["ci_fail"] + r.gauss(0, 1.0), 0, 100), 1),
                "queue_time_min": round(noisy(p["queue"], 0.1) * (3 if anom else 1), 1),
                "on_call_pages": max(0, round(p["on_call"] + 6 * ins + r.gauss(0, 1.0) + (22 if anom else 0))),
                "availability_pct": round(clamp(p["availability"] - downtime / 10080 * 100 + r.gauss(0, 0.005), 0, 100), 3),
            })

    return services, weekly, deployments, incidents, defects


# --------------------------------------------------------------------------------------
# Controlled data-quality issues (Signal 6)
# --------------------------------------------------------------------------------------
def find_row(rows, team, platform, week):
    for row in rows:
        if row["team"] == team and row["platform"] == platform and row["week"] == week:
            return row
    raise LookupError(f"No row for {team}/{platform}/week {week}")


def inject_data_quality_issues(weekly, deployments):
    """Mutates the generated rows and returns a description of every injected issue."""
    issues = []

    d = DQ_DUPLICATE
    idx = next(i for i, x in enumerate(deployments)
               if x["team"] == d["team"] and x["platform"] == d["platform"] and x["week"] == d["week"])
    deployments.insert(idx + 2, dict(deployments[idx + 1]))
    issues.append({"id": "DQ-01", "type": "DUPLICATE_RECORD", "file": "deployments.csv",
                   "record_id": deployments[idx + 1]["deployment_id"],
                   "detail": "Exact duplicate deployment row. Also makes the event count exceed the weekly aggregate by 1.",
                   "expected_rules": ["DEP-R01", "WM-R04"]})

    m = DQ_MISSING
    row = find_row(weekly, m["team"], m["platform"], m["week"])
    original = row[m["field"]]
    row[m["field"]] = None
    issues.append({"id": "DQ-02", "type": "MISSING_VALUE", "file": "weekly_metrics.csv",
                   "record_id": row["record_id"], "field": m["field"], "original_value": original,
                   "expected_rules": ["schema:required"]})

    v = DQ_INVALID
    row = find_row(weekly, v["team"], v["platform"], v["week"])
    original = row[v["field"]]
    row[v["field"]] = v["value"]
    issues.append({"id": "DQ-03", "type": "INVALID_VALUE", "file": "weekly_metrics.csv",
                   "record_id": row["record_id"], "field": v["field"], "value": v["value"],
                   "original_value": original, "expected_rules": ["schema:maximum"]})

    c = DQ_INCONSISTENT
    row = find_row(weekly, c["team"], c["platform"], c["week"])
    original = row[c["field"]]
    row[c["field"]] = original + c["delta"]
    issues.append({"id": "DQ-04", "type": "INCONSISTENT_TOTAL", "file": "weekly_metrics.csv",
                   "record_id": row["record_id"], "field": c["field"], "value": row[c["field"]],
                   "original_value": original,
                   "detail": "deployments no longer equals successful + failed, nor the event count.",
                   "expected_rules": ["WM-R02", "WM-R04"]})
    return issues


def ground_truth(settings, dq_issues):
    n = settings["generator"]["n_weeks"]
    return {
        "_comment": "TEST ORACLE ONLY. Analysis agents must never read this file.",
        "signals": [
            {"id": "SIG-1", "name": "Deteriorating team", "team": DETERIORATING_TEAM["team"],
             "weeks": [DETERIORATING_TEAM["start"], DETERIORATING_TEAM["end"]],
             "expected": {"cycle_time_days": "DETERIORATING", "pr_review_time_hours": "DETERIORATING",
                          "defects_per_week": "DETERIORATING", "test_coverage_pct": "DETERIORATING"},
             "also_moves": ["review_latency_hours", "avg_pr_size_loc", "rework_rate_pct",
                            "automated_test_pct", "escaped_defect_rate", "regression_rate"]},
            {"id": "SIG-2", "name": "Deployment instability", "platform": UNSTABLE_PLATFORM["platform"],
             "weeks": [UNSTABLE_PLATFORM["start"], UNSTABLE_PLATFORM["end"]],
             "expected": {"failed_deployments": "DETERIORATING", "rollback_rate": "DETERIORATING",
                          "incidents_per_week": "DETERIORATING"},
             "also_moves": ["change_failure_rate", "on_call_pages", "availability_pct"]},
            {"id": "SIG-3", "name": "Positive improvement", "team": IMPROVING_TEAM["team"],
             "weeks": [IMPROVING_TEAM["start"], IMPROVING_TEAM["end"]],
             "expected": {"test_coverage_pct": "IMPROVING", "cycle_time_days": "IMPROVING",
                          "deployment_success_rate_pct": "IMPROVING",
                          "escaped_defect_rate_pct": "DIRECTIONAL_ONLY"},
             "note": "The escape rate falls (about 17% -> 4%) but rests on ~60 defects; it is not statistically "
                     "significant (p~0.14), so a correct system reports it as directional, not as a trend."},
            {"id": "SIG-4", "name": "Temporary anomaly", "team": ANOMALY["team"], "platform": ANOMALY["platform"],
             "weeks": [ANOMALY["week"], ANOMALY["week"]],
             "expected": {"ci_failure_rate_pct": "ONE_TIME_ANOMALY", "on_call_pages": "ONE_TIME_ANOMALY",
                          "incidents_per_week": "ONE_TIME_ANOMALY", "build_time_min": "ONE_TIME_ANOMALY"},
             "note": "Must NOT be reported as a trend."},
            {"id": "SIG-5", "name": "Misleading correlation", "team": CORRELATION_TEAM["team"],
             "weeks": [1, n],
             "metrics": ["throughput_items", "build_time_min"],
             "truth": "Both rise because team_headcount grows from "
                      f"{CORRELATION_TEAM['headcount_from']} to {CORRELATION_TEAM['headcount_to']} "
                      "(more people -> more items; larger codebase -> slower builds). "
                      "Neither causes the other. A causal claim between them must be rejected.",
             "secondary_trap": "Titan/Data failed deployments also rise while headcount rises, but the cause is "
                               "the platform-wide Data instability (SIG-2), not headcount."},
        ],
        "data_quality_issues": dq_issues,
    }


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------
def fmt(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: fmt(row[k]) for k in fields})


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    settings, org = load_settings(), load_org()
    raw = project_path(settings["paths"]["raw_data"])

    services, weekly, deployments, incidents, defects = generate(settings, org)
    dq = inject_data_quality_issues(weekly, deployments) if settings["generator"]["inject_data_quality_issues"] else []

    files = {
        "services.csv": (SERVICE_FIELDS, services),
        "weekly_metrics.csv": (WEEKLY_FIELDS, weekly),
        "deployments.csv": (DEPLOYMENT_FIELDS, deployments),
        "incidents.csv": (INCIDENT_FIELDS, incidents),
        "defects.csv": (DEFECT_FIELDS, defects),
    }
    manifest = {"generator": settings["generator"], "files": {}}
    for name, (fields, rows) in files.items():
        write_csv(raw / name, fields, rows)
        manifest["files"][name] = {"rows": len(rows), "sha256": sha256(raw / name)}
    (raw / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    truth_path = project_path(settings["paths"]["ground_truth"])
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.write_text(json.dumps(ground_truth(settings, dq), indent=2) + "\n", encoding="utf-8", newline="\n")

    print(f"Wrote synthetic data to {raw.relative_to(ROOT)}")
    for name, info in manifest["files"].items():
        print(f"  {name:<22} {info['rows']:>5} rows  sha256={info['sha256'][:12]}")
    print(f"Injected {len(dq)} data-quality issues: " + ", ".join(i["id"] + " " + i["type"] for i in dq))
    print(f"Ground truth (tests only): {truth_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
