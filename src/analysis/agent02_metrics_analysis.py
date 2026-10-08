"""Agent 02 - Metrics Analysis.  Spec: agents/02_metrics_analysis_agent.md

Pure arithmetic, no interpretation. Produces:
  * data/processed/metric_series.json - every metric x scope x week, with source record ids
  * observations for every scope x metric (current vs previous week, last-4 vs prior-4 weeks,
    direction by polarity, rank among peers)
  * health scores (KPI cards) per scope and week
  * findings: material period-over-period changes at team / platform / org level

Run:  python -m src.analysis.agent02_metrics_analysis
"""
from datetime import date, timedelta
from statistics import mean

from src.analysis.dataset import build_series, load_clean_data, load_metric_catalog, scope_tag
from src.common.envelope import AGENTS, dump_json, envelope_path, processed_dir, read_envelope, write_envelope
from src.common.stats import clamp, pct_change
from src.config import load_json, load_settings, project_path
from src.data.loader import DATASETS, raw_dir

AGENT = AGENTS["02"]
SERIES_FILE = "metric_series.json"
KPIS = ["delivery", "quality", "reliability", "efficiency"]


def load_series():
    path = processed_dir() / SERIES_FILE
    if not path.exists():
        from src.common.envelope import MissingDependencyError
        raise MissingDependencyError(f"Required input missing: {SERIES_FILE}. Run agent {AGENT} first.")
    return load_json(path)


def direction(change, polarity):
    if change is None:
        return "unknown"
    if change == 0:
        return "unchanged"
    if polarity == "neutral":
        return "increasing" if change > 0 else "decreasing"
    better = (change > 0) == (polarity == "higher_is_better")
    return "improving" if better else "deteriorating"


def window_mean(values, start, end):
    """Mean of non-missing values for weeks start..end (1-based, inclusive)."""
    vals = [v for v in values[start - 1:end] if v is not None]
    return (round(mean(vals), 3), len(vals)) if vals else (None, 0)


def observe(scope_id, scope, metric, entry, n_weeks, period):
    values = entry["values"]
    cur, prev = values[n_weeks - 1], values[n_weeks - 2]
    cur_p, n_cur = window_mean(values, n_weeks - period + 1, n_weeks)
    prev_p, n_prev = window_mean(values, n_weeks - 2 * period + 1, n_weeks - period)
    abs_change = None if cur is None or prev is None else round(cur - prev, 3)
    p_abs = None if cur_p is None or prev_p is None else round(cur_p - prev_p, 3)
    return {
        "scope": scope_id, "scope_type": scope["type"], "team": scope["team"], "platform": scope["platform"],
        "metric": metric["id"], "unit": metric["unit"], "polarity": metric["polarity"],
        "current_week": n_weeks, "current": cur, "previous": prev,
        "abs_change": abs_change, "change_pct": pct_change(cur, prev), "direction": direction(abs_change, metric["polarity"]),
        "period_weeks": [n_weeks - period + 1, n_weeks], "previous_period_weeks": [n_weeks - 2 * period + 1, n_weeks - period],
        "current_period": cur_p, "previous_period": prev_p, "period_points": [n_cur, n_prev],
        "period_abs_change": p_abs, "period_change_pct": pct_change(cur_p, prev_p),
        "period_direction": direction(p_abs, metric["polarity"]),
    }


def add_rankings(observations, catalog):
    groups = {}
    for o in observations:
        if o["scope_type"] in ("team", "platform", "team_platform"):
            groups.setdefault((o["scope_type"], o["metric"]), []).append(o)
    for (stype, mid), obs in groups.items():
        pol = catalog[mid]["polarity"]
        ranked = [o for o in obs if o["current_period"] is not None]
        if pol == "neutral":
            for o in obs:
                o["rank"] = None
            continue
        ranked.sort(key=lambda o: (o["current_period"] if pol == "lower_is_better" else -o["current_period"], o["scope"]))
        for i, o in enumerate(ranked, start=1):
            o["rank"] = i
            o["rank_of"] = len(ranked)


def health_scores(store, catalog, n_weeks, cfg):
    """Relative health index per scope/week. 75 = organisation baseline (first weeks), 100 = 25%+
    better than baseline, 50 = 25% worse. Category = mean of its metrics; overall = mean of KPIs."""
    base_weeks = cfg["health_baseline_weeks"]
    at_base = cfg["health_score_at_baseline"]
    tp_scopes = [s for s in store.values() if s["type"] == "team_platform"]

    def transform(m, v):
        return None if v is None else (100 - v if m.get("health_transform") == "unavailability" else v)

    baseline = {}
    for mid, m in catalog.items():
        if not m["kpi"]:
            continue
        vals = [transform(m, s["metrics"][mid]["values"][w]) for s in tp_scopes for w in range(base_weeks)]
        vals = [v for v in vals if v is not None]
        b = mean(vals) if vals else None
        if b is not None and m.get("count_metric"):
            b = max(b, 0.5)
        baseline[mid] = b

    out = {}
    for sid, s in store.items():
        n_pairs = len(s["pairs"])
        weeks = []
        for w in range(n_weeks):
            per_kpi = {k: [] for k in KPIS}
            metric_scores = {}
            for mid, m in catalog.items():
                if not m["kpi"] or baseline[mid] in (None, 0):
                    continue
                v = transform(m, s["metrics"][mid]["values"][w])
                if v is None:
                    continue
                b = baseline[mid] * (n_pairs if m.get("count_metric") else 1)
                if m["polarity"] == "higher_is_better" and m.get("health_transform") != "unavailability":
                    r = v / b
                else:
                    r = b / v if v > 0 else 2.0
                score = round(clamp(at_base + 100 * (r - 1), 0, 100), 1)
                metric_scores[mid] = score
                per_kpi[m["kpi"]].append(score)
            kpi = {k: (round(mean(v), 1) if v else None) for k, v in per_kpi.items()}
            present = [v for v in kpi.values() if v is not None]
            weeks.append({"week": w + 1, "overall": round(mean(present), 1) if present else None, **kpi,
                          "metric_scores": metric_scores})
        out[sid] = weeks
    return {"method": "relative_to_org_baseline", "baseline_weeks": [1, base_weeks], "score_at_baseline": at_base,
            "baseline_per_team_platform": {k: (round(v, 3) if v is not None else None) for k, v in baseline.items()},
            "scopes": out}


def material_findings(observations, store, catalog, cfg):
    findings = []
    for o in observations:
        if o["scope_type"] == "team_platform" or catalog[o["metric"]]["polarity"] == "neutral":
            continue
        pct = o["period_change_pct"]
        if pct is None or abs(pct) < cfg["material_change_pct"]:
            continue
        s = store[o["scope"]]
        weeks = list(range(o["previous_period_weeks"][0], o["period_weeks"][1] + 1))
        m = catalog[o["metric"]]
        verb = "rose" if o["period_abs_change"] > 0 else "fell"
        findings.append({
            "id": f"MET-{scope_tag(s)}-{o['metric'].upper()}",
            "type": "metric_change",
            "claim": (f"{s['label']}: {m['label']} {verb} {abs(pct):.1f}% "
                      f"(weeks {o['period_weeks'][0]}-{o['period_weeks'][1]} avg {o['current_period']:g} {m['unit']} vs "
                      f"weeks {o['previous_period_weeks'][0]}-{o['previous_period_weeks'][1]} avg {o['previous_period']:g}) - {o['period_direction']}."),
            "metrics": [o["metric"]],
            "dimension": {"scope": o["scope"], "team": o["team"], "platform": o["platform"]},
            "weeks": [weeks[0], weeks[-1]],
            "direction": o["period_direction"],
            "evidence": {
                "dataset": "metric_series",
                "series_ref": {"scope": o["scope"], "metric": o["metric"], "weeks": weeks},
                "record_ids": [rid for w in weeks for rid in s["weekly_records"][str(w)]],
                "event_record_count": (sum(len(s["metrics"][o["metric"]]["event_records"][str(w)]) for w in weeks)
                                       if s["metrics"][o["metric"]]["event_records"] is not None else 0),
                "values": {str(w): s["metrics"][o["metric"]]["values"][w - 1] for w in weeks},
                "calculation": (f"mean(weeks {o['period_weeks'][0]}-{o['period_weeks'][1]}) = {o['current_period']}; "
                                f"mean(weeks {o['previous_period_weeks'][0]}-{o['previous_period_weeks'][1]}) = {o['previous_period']}; "
                                f"change = {o['period_abs_change']} ({pct}%)"),
                "computed": {"current_period": o["current_period"], "previous_period": o["previous_period"], "change_pct": pct},
            },
            "confidence": None,
            "produced_by": AGENT,
            "related_findings": [],
            "validation": None,
        })
    return findings


def run():
    validation = read_envelope(AGENTS["01"])
    settings = load_settings()
    n_weeks = settings["generator"]["n_weeks"]
    cfg = load_json(project_path("config/thresholds.json"))["metrics_analysis"]
    catalog = load_metric_catalog()

    data = load_clean_data(validation["analysis_directives"])
    store = build_series(data, catalog, n_weeks)
    start = date.fromisoformat(settings["generator"]["start_date"])
    series_doc = {
        "generated_by": AGENT,
        "weeks": list(range(1, n_weeks + 1)),
        "week_starts": [(start + timedelta(days=7 * i)).isoformat() for i in range(n_weeks)],
        "metrics": {mid: {k: m[k] for k in ("label", "unit", "category", "kpi", "polarity")} for mid, m in catalog.items()},
        "scopes": store,
    }
    dump_json(processed_dir() / SERIES_FILE, series_doc)

    observations = [observe(sid, s, catalog[mid], s["metrics"][mid], n_weeks, cfg["period_weeks"])
                    for sid, s in store.items() for mid in catalog]
    add_rankings(observations, catalog)
    health = health_scores(store, catalog, n_weeks, cfg)
    findings = material_findings(observations, store, catalog, cfg)

    incomplete = sum(1 for s in store.values() for m in s["metrics"].values() for c in m["complete"] if not c)
    summary = {
        "scopes": len(store), "metrics": len(catalog), "weeks": n_weeks,
        "observations": len(observations), "material_changes": len(findings),
        "incomplete_points": incomplete,
        "org_health_current": {k: v for k, v in health["scopes"]["org"][-1].items() if k != "metric_scores"},
    }
    inputs = [envelope_path(AGENTS["01"])] + [raw_dir() / f"{ds}.csv" for ds in DATASETS] + \
             [project_path("config/metrics.json"), project_path("config/thresholds.json")]
    write_envelope(AGENT, "PASS", [AGENTS["01"]], inputs, summary, findings,
                   artifacts={"metric_series": f"data/processed/{SERIES_FILE}"},
                   observations=observations, health_scores=health)
    return summary


def main():
    s = run()
    print(f"[{AGENT}] status=PASS scopes={s['scopes']} metrics={s['metrics']} observations={s['observations']} "
          f"material_changes={s['material_changes']} incomplete_points={s['incomplete_points']}")
    print(f"  org health (week {s['weeks']}): {s['org_health_current']}")


if __name__ == "__main__":
    main()
