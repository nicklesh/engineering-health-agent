"""Agent 04 - Trend Analysis.  Spec: agents/04_trend_analysis_agent.md

Classifies every metric series over the full history (IMPROVING / STABLE / DETERIORATING /
VOLATILE / ONE_TIME_ANOMALY / INSUFFICIENT_DATA) using the documented threshold in
src/analysis/trend_rules.py, and reports strong co-movements between trending metrics as
*associations* (never causes), with a common-driver check.

Run:  python -m src.analysis.agent04_trend_analysis
"""
from src.analysis.agent02_metrics_analysis import load_series
from src.analysis.dataset import load_metric_catalog, scope_tag
from src.analysis.trend_rules import analysed_values, classify_series
from src.common.envelope import AGENTS, envelope_path, processed_dir, read_envelope, write_envelope
from src.common.stats import partial_correlation, pearson
from src.config import load_json, project_path
from src.validation import confidence

AGENT = AGENTS["04"]
TREND_CLASSES = ("IMPROVING", "DETERIORATING")


def trend_finding(sid, scope, m, c, n_weeks, cfg):
    lo, hi = c["trend_window"]
    weeks = list(range(lo, hi + 1))
    entry = scope["metrics"][m["id"]]
    values = {str(w): entry["values"][w - 1] for w in range(1, n_weeks + 1)}
    is_ratio = c["basis"] != "weekly"
    verb = "rising" if c["movement"] == "RISING" else "falling"
    pct = f"{abs(c['change_pct']):.0f}%" if c["change_pct"] is not None else f"{abs(c['change']):g} {m['unit']}"
    b_lo, b_hi = c["baseline_weeks"]
    r_lo, r_hi = c["recent_weeks"]
    sign_ = "+" if c["change"] > 0 else "-"
    if is_ratio:
        (x0, n0), (x1, n1) = c["pooled_counts"]["baseline"], c["pooled_counts"]["recent"]
        detail = (f"Pooled rate {c['baseline']:.1f}% in weeks {b_lo}-{b_hi} ({x0}/{n0}) vs {c['recent']:.1f}% in weeks "
                  f"{r_lo}-{r_hi} ({x1}/{n1}), {sign_}{abs(c['change']):.1f} pp.")
        calc = (f"two-proportion z={c['z']} (p={c['p_value']}); baseline {x0}/{n0}={c['baseline']}%, recent {x1}/{n1}={c['recent']}%, "
                f"change={c['change']} pp ({c['change_pct']}%); effect={c['effect_sd']} se; onset from rolling "
                f"{cfg['ratio_pooling_weeks']}-week pooled rate; trend window weeks {lo}-{hi}")
    else:
        detail = (f"Median {c['baseline']:g} {m['unit']} in weeks {b_lo}-{b_hi} vs {c['recent']:g} in weeks "
                  f"{r_lo}-{r_hi} ({sign_}{pct}).")
        calc = (f"Mann-Kendall tau={c['kendall_tau']} (p={c['p_value']}); baseline median={c['baseline']}, "
                f"recent median={c['recent']}, change={c['change']} ({c['change_pct']}%), "
                f"noise sd={c['noise_sd']} -> effect={c['effect_sd']} sd; Theil-Sen slope={c['slope_per_week']}/week; "
                f"trend window weeks {lo}-{hi} ({c['window_weeks']} weeks)")
    conf = confidence.build(
        completeness=c["valid_points"] / c["expected_points"],
        n_observations=c["window_weeks"],
        consistency=c["consistency"],
        effect_sd=c["effect_sd"],
    )
    return {
        "id": f"TRD-{scope_tag(scope)}-{m['id'].upper()}",
        "type": "trend",
        "classification": c["classification"],
        "claim": f"{scope['label']}: {m['label']} has been {verb} since week {lo} - {c['classification']}. {detail}",
        "metrics": [m["id"]],
        "dimension": {"scope": sid, "team": scope["team"], "platform": scope["platform"]},
        "weeks": [lo, hi],
        "evidence": {
            "dataset": "metric_series",
            "series_ref": {"scope": sid, "metric": m["id"], "weeks": list(range(1, n_weeks + 1))},
            "record_ids": [rid for w in weeks for rid in scope["weekly_records"][str(w)]],
            "values": values,
            "basis": c["basis"],
            "rolling_rate": c.get("rolling_rate"),
            "calculation": calc,
            "computed": {k: c.get(k) for k in ("baseline", "recent", "change", "change_pct", "effect_sd", "kendall_tau", "z",
                                               "p_value", "onset_week", "window_weeks", "noise_sd", "pooled_counts", "basis")},
            "outliers_excluded": c["outliers"],
        },
        "confidence": conf,
        "produced_by": AGENT,
        "related_findings": [],
        "validation": None,
    }


def anomaly_finding(sid, scope, m, c):
    o = max(c["outliers"], key=lambda x: abs(x["z"]))
    w = o["week"]
    return {
        "id": f"TRD-{scope_tag(scope)}-{m['id'].upper()}",
        "type": "trend",
        "classification": "ONE_TIME_ANOMALY",
        "claim": (f"{scope['label']}: {m['label']} is otherwise stable; week {w} ({o['value']:g} {m['unit']} vs local median "
                  f"{o['local_median']:g}) is a one-time deviation, not a trend."),
        "metrics": [m["id"]],
        "dimension": {"scope": sid, "team": scope["team"], "platform": scope["platform"]},
        "weeks": [w, w],
        "evidence": {
            "dataset": "metric_series",
            "series_ref": {"scope": sid, "metric": m["id"], "weeks": [x["week"] for x in c["outliers"]]},
            "record_ids": [rid for x in c["outliers"] for rid in scope["weekly_records"][str(x["week"])]],
            "values": {str(x["week"]): x["value"] for x in c["outliers"]},
            "calculation": f"robust z={o['z']} vs +/-2-week local median; series without outliers fails the trend threshold",
            "computed": {"outliers": c["outliers"], "trend_checks": c.get("checks")},
        },
        "confidence": confidence.build(c["valid_points"] / c["expected_points"], c["valid_points"], 1.0, abs(o["z"])),
        "produced_by": AGENT,
        "related_findings": [],
        "validation": None,
    }


def correlations(store, catalog, classifications, cfg, n_weeks):
    findings = []
    confounders = cfg["confounders"]
    for sid, scope in store.items():
        if scope["type"] not in ("team", "platform"):
            continue
        # Only outcome metrics are paired; context metrics (headcount, PR count) are used as
        # possible common drivers instead of being reported as correlations themselves.
        trending = [mid for mid in catalog
                    if mid not in confounders and catalog[mid]["polarity"] != "neutral"
                    and classifications[(sid, mid)].get("trend_test_passed")]
        pairs = []
        for i, a in enumerate(trending):
            for b in trending[i + 1:]:
                ga, gb = catalog[a].get("definition_group"), catalog[b].get("definition_group")
                if ga and ga == gb:
                    continue  # linked by definition (e.g. success rate = 100 - failure rate)
                va, vb = scope["metrics"][a]["values"], scope["metrics"][b]["values"]
                idx = [k for k in range(n_weeks) if va[k] is not None and vb[k] is not None]
                if len(idx) < 8:
                    continue
                r = pearson([va[k] for k in idx], [vb[k] for k in idx])
                if r is not None and abs(r) >= cfg["min_abs_r"]:
                    pairs.append((abs(r), a, b, r, idx))
        pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
        for _, a, b, r, idx in pairs[:cfg["top_pairs_per_scope"]]:
            va, vb = scope["metrics"][a]["values"], scope["metrics"][b]["values"]
            xs, ys = [va[k] for k in idx], [vb[k] for k in idx]
            dx = [q - p for p, q in zip(xs, xs[1:])]
            dy = [q - p for p, q in zip(ys, ys[1:])]
            r_diff = pearson(dx, dy)
            drivers = []
            for z in confounders:
                vz = scope["metrics"][z]["values"]
                if any(vz[k] is None for k in idx):
                    continue
                zs = [vz[k] for k in idx]
                r_xz, r_yz = pearson(xs, zs), pearson(ys, zs)
                if r_xz is not None and r_yz is not None and abs(r_xz) >= cfg["confounder_min_abs_r"] and abs(r_yz) >= cfg["confounder_min_abs_r"]:
                    drivers.append({"metric": z, "r_with_first": r_xz, "r_with_second": r_yz,
                                    "partial_r": partial_correlation(r, r_xz, r_yz)})
            ma, mb = catalog[a], catalog[b]
            note = ""
            if drivers:
                d = drivers[0]
                note = (f" Both also track {catalog[d['metric']]['label'].lower()} (r={d['r_with_first']}, {d['r_with_second']}); "
                        f"controlling for it the association drops to r={d['partial_r']}, so a common driver is likely.")
            findings.append({
                "id": f"COR-{scope_tag(scope)}-{a.upper()}-{b.upper()}",
                "type": "correlation",
                "claim": (f"{scope['label']}: {ma['label']} and {mb['label']} moved together over weeks {idx[0] + 1}-{idx[-1] + 1} "
                          f"(r={r}). This is an association, not evidence that one causes the other." + note),
                "metrics": [a, b],
                "dimension": {"scope": sid, "team": scope["team"], "platform": scope["platform"]},
                "weeks": [idx[0] + 1, idx[-1] + 1],
                "causal_claim": False,
                "evidence": {
                    "dataset": "metric_series",
                    "series_ref": {"scope": sid, "metric": a, "metric_2": b, "weeks": [k + 1 for k in idx]},
                    "record_ids": [rid for k in idx for rid in scope["weekly_records"][str(k + 1)]],
                    "values": {str(k + 1): [va[k], vb[k]] for k in idx},
                    "calculation": f"Pearson r={r} over {len(idx)} weeks; r of week-over-week changes={r_diff}",
                    "computed": {"r": r, "r_differences": r_diff, "n": len(idx), "common_drivers": drivers},
                },
                "confidence": confidence.build(len(idx) / n_weeks, len(idx), abs(r_diff or 0), abs(r) * 3),
                "produced_by": AGENT,
                "related_findings": [f"TRD-{scope_tag(scope)}-{a.upper()}", f"TRD-{scope_tag(scope)}-{b.upper()}"],
                "validation": None,
            })
    return findings


def run():
    read_envelope(AGENTS["02"])
    series = load_series()
    store = series["scopes"]
    n_weeks = len(series["weeks"])
    thresholds = load_json(project_path("config/thresholds.json"))
    cfg = thresholds["trend"]
    catalog = load_metric_catalog()

    classifications, records, findings = {}, [], []
    for sid, scope in store.items():
        for mid, m in catalog.items():
            c = classify_series(scope["metrics"][mid]["values"], m, cfg, scope["metrics"][mid])
            classifications[(sid, mid)] = c
            records.append({"scope": sid, "scope_type": scope["type"], "team": scope["team"], "platform": scope["platform"], **c})
            if c["classification"] in TREND_CLASSES:
                findings.append(trend_finding(sid, scope, m, c, n_weeks, cfg))
            elif c["classification"] == "ONE_TIME_ANOMALY":
                findings.append(anomaly_finding(sid, scope, m, c))

    findings += correlations(store, catalog, classifications, thresholds["correlation"], n_weeks)

    counts = {}
    for r in records:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    summary = {"series": len(records), "classification_counts": dict(sorted(counts.items())),
               "trend_findings": sum(f["type"] == "trend" and f["classification"] in TREND_CLASSES for f in findings),
               "anomaly_classifications": sum(f.get("classification") == "ONE_TIME_ANOMALY" for f in findings),
               "correlations": sum(f["type"] == "correlation" for f in findings),
               "emerging": [f"{r['scope']}:{r['metric']}" for r in records if r.get("emerging")],
               "latest_week_outliers": [f"{r['scope']}:{r['metric']}" for r in records if r.get("latest_week_outlier")],
               "threshold": cfg}
    inputs = [envelope_path(AGENTS["02"]), processed_dir() / "metric_series.json", project_path("config/thresholds.json")]
    write_envelope(AGENT, "PASS", [AGENTS["02"]], inputs, summary, findings, series_classifications=records)
    return summary


def main():
    s = run()
    print(f"[{AGENT}] status=PASS series={s['series']} classes={s['classification_counts']} "
          f"trend_findings={s['trend_findings']} correlations={s['correlations']}")


if __name__ == "__main__":
    main()
