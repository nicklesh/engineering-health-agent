"""Agent 03 - Quality Analysis.  Spec: agents/03_quality_analysis_agent.md

A quality-focused view per team and platform, built on Agent 02's series and Agent 04/05's
classifications (it does not re-classify trends itself):
  * quality profile: defects, severity mix, escape / regression / change-failure rates
    (pooled), coverage and automation - baseline weeks vs recent weeks
  * quality status: IMPROVING / DETERIORATING / MIXED / STABLE from the quality-metric trends
  * persistent quality risks: worse than the peer median by >= X% in most recent weeks
  * potential leading indicators: coverage / automation changes that precede defect or escape
    changes by 1-3 weeks (association only)

Run:  python -m src.analysis.agent03_quality_analysis
"""
from statistics import mean, median

from src.analysis.agent02_metrics_analysis import load_series
from src.analysis.dataset import load_metric_catalog, scope_tag
from src.common import fmt
from src.common.envelope import AGENTS, envelope_path, processed_dir, read_envelope, write_envelope
from src.common.stats import pct_change, pearson
from src.config import load_json, project_path
from src.validation import confidence

AGENT = AGENTS["03"]
RATES = ["escaped_defect_rate_pct", "regression_rate_pct", "change_failure_rate_pct"]
LEVELS = ["test_coverage_pct", "automated_test_pct"]
LEAD_PAIRS = [("test_coverage_pct", "defects"), ("test_coverage_pct", "escaped_defect_rate_pct"),
              ("automated_test_pct", "defects"), ("automated_test_pct", "escaped_defect_rate_pct")]


def pooled(entry, lo, hi):
    num = sum(entry["numerator"][lo - 1:hi])
    den = sum(entry["denominator"][lo - 1:hi])
    return (round(100 * num / den, 2) if den else None), num, den


def profile(scope, n_weeks, base_hi, recent_lo):
    m = scope["metrics"]
    out = {}
    for label, (lo, hi) in {"baseline": (1, base_hi), "recent": (recent_lo, n_weeks)}.items():
        weeks = hi - lo + 1
        d = sum(m["defects"]["values"][lo - 1:hi])
        hs = sum(m["high_severity_defects"]["values"][lo - 1:hi])
        p = {"weeks": [lo, hi], "defects_per_week": round(d / weeks, 2),
             "high_severity_share_pct": round(100 * hs / d, 1) if d else None}
        for r in RATES:
            p[r], p[f"{r}_counts"] = pooled(m[r], lo, hi)[0], list(pooled(m[r], lo, hi)[1:])
        for lv in LEVELS:
            vals = [v for v in m[lv]["values"][lo - 1:hi] if v is not None]
            p[lv] = round(mean(vals), 2) if vals else None
        out[label] = p
    out["change"] = {k: (round(out["recent"][k] - out["baseline"][k], 2)
                         if isinstance(out["recent"].get(k), (int, float)) and isinstance(out["baseline"].get(k), (int, float)) else None)
                     for k in out["baseline"] if k != "weeks" and not k.endswith("_counts")}
    return out


def run():
    read_envelope(AGENTS["02"])
    trends = read_envelope(AGENTS["04"])
    anomalies = read_envelope(AGENTS["05"])
    series = load_series()
    store, n_weeks = series["scopes"], len(series["weeks"])
    thresholds = load_json(project_path("config/thresholds.json"))
    cfg, tcfg = thresholds["quality"], thresholds["trend"]
    catalog = load_metric_catalog()
    quality_metrics = [mid for mid, m in catalog.items() if m["risk_category"] == "Quality"]

    cls = {(r["scope"], r["metric"]): r for r in trends["series_classifications"]}
    trend_ids = {f["id"]: f for f in trends["findings"]}
    base_hi, recent_lo = tcfg["baseline_weeks"], n_weeks - tcfg["recent_weeks"] + 1

    profiles, findings = {}, []
    peer_scopes = {t: [sid for sid, s in store.items() if s["type"] == t] for t in ("team", "platform")}

    for sid, scope in store.items():
        if scope["type"] not in ("team", "platform"):
            continue
        tag = scope_tag(scope)
        prof = profile(scope, n_weeks, base_hi, recent_lo)

        improving = [mid for mid in quality_metrics if cls[(sid, mid)]["classification"] == "IMPROVING"]
        deteriorating = [mid for mid in quality_metrics if cls[(sid, mid)]["classification"] == "DETERIORATING"]
        if len(deteriorating) >= 2 and len(deteriorating) > len(improving):
            status = "DETERIORATING"
        elif len(improving) >= 2 and len(improving) > len(deteriorating):
            status = "IMPROVING"
        elif improving and deteriorating:
            status = "MIXED"
        else:
            status = "STABLE"
        quality_anoms = [f["id"] for f in anomalies["findings"]
                         if f["metrics"][0] in quality_metrics and (f["dimension"]["scope"] == sid or sid in f["also_visible_in"])]
        profiles[sid] = {"scope": sid, "label": scope["label"], "status": status, "improving": improving,
                         "deteriorating": deteriorating, "quality_anomalies": quality_anoms, **prof}

        if status in ("IMPROVING", "DETERIORATING"):
            members = improving if status == "IMPROVING" else deteriorating
            refs = [f"TRD-{tag}-{mid.upper()}" for mid in members]
            parts = []
            for mid in members:
                c = cls[(sid, mid)]
                parts.append(f"{catalog[mid]['label'].lower()} {fmt.arrow(c['baseline'], c['recent'], catalog[mid]['unit'])}")
            findings.append({
                "id": f"QUA-{tag}-STATUS", "type": "quality_signal", "signal": f"QUALITY_{status}",
                "claim": f"{scope['label']}: quality is {status.lower()} - {len(members)} quality metrics with a qualifying trend ({'; '.join(parts)}).",
                "metrics": members, "dimension": {"scope": sid, "team": scope["team"], "platform": scope["platform"]},
                "weeks": [min(trend_ids[r]["weeks"][0] for r in refs), n_weeks],
                "evidence": {"dataset": "04_trend_analysis", "finding_refs": refs,
                             "record_ids": sorted({rid for r in refs for rid in trend_ids[r]["evidence"]["record_ids"]}),
                             "values": {mid: [cls[(sid, mid)]["baseline"], cls[(sid, mid)]["recent"]] for mid in members},
                             "calculation": f"count of quality metrics classified {status} by Agent 04 = {len(members)} (>= 2 and more than the opposite direction)"},
                "confidence": confidence.combine([trend_ids[r]["confidence"] for r in refs]),
                "produced_by": AGENT, "related_findings": refs, "validation": None,
            })

        # Persistent: worse than the peer median in most of the recent window.
        lo = n_weeks - cfg["persistent_window"] + 1
        for mid in quality_metrics:
            m = catalog[mid]
            if m["derive"]["kind"] == "event_ratio" or m.get("count_metric"):
                continue  # small-sample weekly rates/counts are compared via the pooled profile instead
            worse_weeks, gaps = [], []
            for w in range(lo, n_weeks + 1):
                peers = [store[p]["metrics"][mid]["values"][w - 1] for p in peer_scopes[scope["type"]]]
                peers = [v for v in peers if v is not None]
                v = scope["metrics"][mid]["values"][w - 1]
                if v is None or len(peers) < 3:
                    continue
                ref = median(peers)
                gap = pct_change(v, ref)
                if gap is None:
                    continue
                worse = gap >= cfg["worse_than_org_pct"] if m["polarity"] == "lower_is_better" else gap <= -cfg["worse_than_org_pct"] / 2
                if worse:
                    worse_weeks.append(w)
                    gaps.append(gap)
            if len(worse_weeks) >= cfg["persistent_weeks"]:
                findings.append({
                    "id": f"QUA-{tag}-PERSISTENT-{mid.upper()}", "type": "quality_signal", "signal": "PERSISTENT_QUALITY_RISK",
                    "claim": (f"{scope['label']}: {m['label'].lower()} was materially worse than the {scope['type']} median in "
                              f"{len(worse_weeks)} of the last {cfg['persistent_window']} weeks (average gap {mean(gaps):+.1f}%)."),
                    "metrics": [mid], "dimension": {"scope": sid, "team": scope["team"], "platform": scope["platform"]},
                    "weeks": [lo, n_weeks],
                    "evidence": {"dataset": "metric_series", "series_ref": {"scope": sid, "metric": mid, "weeks": worse_weeks},
                                 "record_ids": [rid for w in worse_weeks for rid in scope["weekly_records"][str(w)]],
                                 "values": {str(w): scope["metrics"][mid]["values"][w - 1] for w in worse_weeks},
                                 "calculation": f"weeks where gap to peer median breaches threshold = {len(worse_weeks)} (>= {cfg['persistent_weeks']})",
                                 "computed": {"worse_weeks": worse_weeks, "gaps_pct": gaps}},
                    "confidence": confidence.build(1.0, len(worse_weeks), len(worse_weeks) / cfg["persistent_window"], mean(abs(g) for g in gaps) / 10),
                    "produced_by": AGENT, "related_findings": [], "validation": None,
                })

        # Leading indicators (team scopes only, association not causation).
        if scope["type"] == "team":
            for lead, lag_metric in LEAD_PAIRS:
                a, b = scope["metrics"][lead]["values"], scope["metrics"][lag_metric]["values"]
                best = None
                for k in range(1, cfg["lead_max_lag"] + 1):
                    idx = [i for i in range(n_weeks - k) if a[i] is not None and b[i + k] is not None]
                    if len(idx) < 8:
                        continue
                    r = pearson([a[i] for i in idx], [b[i + k] for i in idx])
                    if r is not None and r <= -cfg["lead_min_abs_r"] and (best is None or r < best[1]):
                        best = (k, r, idx)
                if best:
                    k, r, idx = best
                    findings.append({
                        "id": f"QUA-{tag}-LEAD-{lead.upper()}-{lag_metric.upper()}", "type": "quality_signal",
                        "signal": "POTENTIAL_LEADING_INDICATOR", "causal_claim": False,
                        "claim": (f"{scope['label']}: lower {catalog[lead]['label'].lower()} was followed {k} week(s) later by higher "
                                  f"{catalog[lag_metric]['label'].lower()} (r={r}). A potential leading indicator to monitor - "
                                  f"an association, not proof that one causes the other."),
                        "metrics": [lead, lag_metric], "dimension": {"scope": sid, "team": scope["team"], "platform": scope["platform"]},
                        "weeks": [idx[0] + 1, idx[-1] + 1 + k],
                        "evidence": {"dataset": "metric_series", "series_ref": {"scope": sid, "metric": lead, "metric_2": lag_metric,
                                                                                 "lag": k, "weeks": [i + 1 for i in idx]},
                                     "record_ids": [rid for i in idx for rid in scope["weekly_records"][str(i + 1)]],
                                     "values": {str(i + 1): [a[i], b[i + k]] for i in idx},
                                     "calculation": f"Pearson r between {lead}(t) and {lag_metric}(t+{k}) over {len(idx)} weeks = {r}",
                                     "computed": {"r": r, "lag": k, "n": len(idx)}},
                        "confidence": confidence.build(len(idx) / (n_weeks - k), len(idx), 0.5, abs(r) * 3),
                        "produced_by": AGENT, "related_findings": [], "validation": None,
                    })

    summary = {"profiles": len(profiles),
               "status": {sid: p["status"] for sid, p in profiles.items()},
               "signals": {s: sum(f["signal"] == s for f in findings) for s in sorted({f["signal"] for f in findings})}}
    inputs = [envelope_path(a) for a in (AGENTS["02"], AGENTS["04"], AGENTS["05"])] + \
             [processed_dir() / "metric_series.json", project_path("config/thresholds.json")]
    write_envelope(AGENT, "PASS", [AGENTS["02"], AGENTS["04"], AGENTS["05"]], inputs, summary, findings, quality_profiles=profiles)
    return summary, findings


def main():
    s, findings = run()
    print(f"[{AGENT}] status=PASS profiles={s['profiles']} signals={s['signals']}")
    print("  status: " + ", ".join(f"{k}={v}" for k, v in s["status"].items()))
    for f in findings:
        print(f"  {f['id']}: {f['claim'][:150]}")


if __name__ == "__main__":
    main()
