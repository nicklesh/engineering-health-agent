"""Builds the analysis-ready view of the raw data and the metric series store.

* `load_clean_data` applies Agent 01's analysis_directives (exclude duplicates, treat
  invalid values as missing). It never edits files - it only changes what analysis sees.
* `build_series` computes every metric in config/metrics.json for every scope and week,
  keeping the exact source record ids behind each number (traceability).

Scopes:  org | team:<Team> | platform:<Platform> | tp:<Team>/<Platform>
"""
from src.config import load_json, project_path
from src.data.loader import DATASETS, read_dataset

PK = {"services": "service_id", "weekly_metrics": "record_id", "deployments": "deployment_id",
      "incidents": "incident_id", "defects": "defect_id"}


def load_metric_catalog():
    return {m["id"]: m for m in load_json(project_path("config/metrics.json"))["metrics"]}


def load_clean_data(directives, raw=None):
    excluded = {(d["dataset"], d["line"]) for d in directives.get("exclude_records", [])}
    nulls = {(d["dataset"], d["record_id"], d["field"]) for d in directives.get("null_fields", [])}
    data = {}
    for ds in DATASETS:
        rows, _ = read_dataset(ds, raw)
        clean = []
        for r in rows:
            if (ds, r["_line"]) in excluded:
                continue
            r = dict(r)
            for (nds, rid, field) in nulls:
                if nds == ds and r.get(PK[ds]) == rid:
                    r[field] = None
            clean.append(r)
        data[ds] = clean
    return data


def scopes_for(services):
    teams = sorted({s["team"] for s in services})
    platforms = sorted({s["platform"] for s in services})
    pairs = sorted({(s["team"], s["platform"]) for s in services})
    scopes = {"org": {"type": "org", "team": None, "platform": None, "label": "Organisation"}}
    for t in teams:
        scopes[f"team:{t}"] = {"type": "team", "team": t, "platform": None, "label": t}
    for p in platforms:
        scopes[f"platform:{p}"] = {"type": "platform", "team": None, "platform": p, "label": p}
    for t, p in pairs:
        scopes[f"tp:{t}/{p}"] = {"type": "team_platform", "team": t, "platform": p, "label": f"{t} / {p}"}
    for s in scopes.values():
        s["pairs"] = [(t, p) for t, p in pairs
                      if (s["team"] in (None, t)) and (s["platform"] in (None, p))]
    return scopes


def in_scope(row, scope):
    return (scope["team"] in (None, row["team"])) and (scope["platform"] in (None, row["platform"]))


def matches(row, where):
    for k, v in where.items():
        if isinstance(v, list):
            if row.get(k) not in v:
                return False
        elif row.get(k) != v:
            return False
    return True


class RatioIds(list):
    """Record ids of a ratio's denominator, plus the numerator/denominator counts so later
    agents can pool several weeks (sum of numerators / sum of denominators)."""

    def __init__(self, ids, numerator, denominator):
        super().__init__(ids)
        self.numerator = numerator
        self.denominator = denominator


def pooled_ratio(entry, end_week, window):
    """100 * sum(numerator) / sum(denominator) over weeks end_week-window+1 .. end_week."""
    lo = max(1, end_week - window + 1)
    num = sum(entry["numerator"][w - 1] for w in range(lo, end_week + 1))
    den = sum(entry["denominator"][w - 1] for w in range(lo, end_week + 1))
    return round(100 * num / den, 3) if den else None


def compute_point(metric, scope, week, weekly_rows, events):
    """Return (value, complete, event_record_ids) for one metric / scope / week."""
    d = metric["derive"]
    if d["kind"] == "weekly_field":
        rows = weekly_rows
        values = [r[d["field"]] for r in rows]
        if not rows or any(v is None for v in values):
            return None, False, None
        if d["agg"] == "mean":
            return round(sum(values) / len(values), 3), True, None
        if d["agg"] == "sum":
            return round(sum(values), 3), True, None
        if d["agg"] == "team_distinct_sum":
            per_team = {}
            for r in rows:
                per_team.setdefault(r["team"], r[d["field"]])
            return sum(per_team.values()), True, None
        raise ValueError(f"Unknown agg {d['agg']}")

    pk = PK[d["dataset"]]
    evs = events[d["dataset"]]
    if d["kind"] == "event_count":
        hit = [e for e in evs if matches(e, d["where"])]
        return len(hit), True, [e[pk] for e in hit]
    if d["kind"] == "event_ratio":
        den = [e for e in evs if matches(e, d["denominator"])]
        num = [e for e in den if matches(e, d["numerator"])]
        ids = [e[pk] for e in den]
        if not den:
            return None, True, RatioIds(ids, 0, 0)
        return round(100 * len(num) / len(den), 3), True, RatioIds(ids, len(num), len(den))
    if d["kind"] == "event_mean":
        vals = [e for e in evs if e.get(d["field"]) is not None]
        if not vals:
            return None, True, []
        return round(sum(e[d["field"]] for e in vals) / len(vals), 3), True, [e[pk] for e in vals]
    raise ValueError(f"Unknown derivation {d['kind']}")


def build_series(data, catalog, n_weeks):
    scopes = scopes_for(data["services"])
    weekly_by = {}
    for r in data["weekly_metrics"]:
        weekly_by.setdefault(r["week"], []).append(r)
    events_by = {ds: {} for ds in ("deployments", "incidents", "defects")}
    for ds in events_by:
        for e in data[ds]:
            events_by[ds].setdefault(e["week"], []).append(e)

    store = {}
    for sid, scope in scopes.items():
        weekly_records = {}
        metrics = {}
        for week in range(1, n_weeks + 1):
            rows = [r for r in weekly_by.get(week, []) if in_scope(r, scope)]
            weekly_records[str(week)] = [r["record_id"] for r in rows]
            evs = {ds: [e for e in events_by[ds].get(week, []) if in_scope(e, scope)] for ds in events_by}
            for mid, m in catalog.items():
                value, complete, ids = compute_point(m, scope, week, rows, evs)
                kind = m["derive"]["kind"]
                entry = metrics.setdefault(mid, {"values": [], "complete": [], "event_records": {} if kind != "weekly_field" else None})
                if kind == "event_ratio":
                    entry.setdefault("numerator", []).append(ids.numerator)
                    entry.setdefault("denominator", []).append(ids.denominator)
                entry["values"].append(value)
                entry["complete"].append(complete)
                if entry["event_records"] is not None:
                    entry["event_records"][str(week)] = list(ids)
        store[sid] = {**{k: v for k, v in scope.items() if k != "pairs"},
                      "pairs": [f"{t}/{p}" for t, p in scope["pairs"]],
                      "weekly_records": weekly_records, "metrics": metrics}
    return store


def point_records(store, scope_id, metric_id, week):
    """All source record ids behind one data point (weekly rows + event records)."""
    s = store[scope_id]
    ids = list(s["weekly_records"][str(week)])
    ev = s["metrics"][metric_id]["event_records"]
    if ev is not None:
        ids += ev[str(week)]
    return ids


def finding_dimension(scope):
    return {"scope": scope.get("id"), "team": scope["team"], "platform": scope["platform"]}


def scope_tag(scope):
    return f"{(scope['team'] or 'ALL').upper()}-{(scope['platform'] or 'ALL').upper()}"
