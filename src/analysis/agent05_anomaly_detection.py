"""Agent 05 - Anomaly Detection.  Spec: agents/05_anomaly_detection_agent.md

Finds single weekly observations that are far from their local baseline, and says whether
each one is an isolated spike (anomaly) or the start of a sustained shift (possible trend -
which only Agent 04 may call a trend). Works on raw weekly values, independent of Agent 04.

Rule (config/thresholds.json -> anomaly):
  expected  = median of the valid values within +/- `window` weeks (excluding the week itself)
  scale     = robust sd of all such residuals in the series; for count metrics at least
              sqrt(expected) (Poisson noise)
  anomaly   if |value - expected| / scale >= min_z  AND  |value - expected| >= min_relative_change x expected
  pattern   ISOLATED_SPIKE if the following week is back within `return_within_sd` x scale,
            SUSTAINED_SHIFT if the next two weeks stay beyond it, UNRESOLVED if it is the latest week.

Run:  python -m src.analysis.agent05_anomaly_detection
"""
import math
from statistics import median

from src.analysis.agent02_metrics_analysis import load_series
from src.analysis.dataset import load_metric_catalog, point_records, scope_tag
from src.common.envelope import AGENTS, envelope_path, processed_dir, read_envelope, write_envelope
from src.common.stats import robust_sd
from src.config import load_json, project_path
from src.validation import confidence

AGENT = AGENTS["05"]
SPECIFICITY = {"team_platform": 3, "team": 2, "platform": 2, "org": 1}


def detect_ratio(entry, cfg):
    """Rates: is this week's count of 'bad' events surprising given the pooled rate of the
    neighbouring weeks? Binomial z-test, so 1 failure out of 3 deployments is not an anomaly."""
    num, den, values = entry["numerator"], entry["denominator"], entry["values"]
    n, win = len(num), cfg["window"]
    found = []
    for i in range(n):
        if den[i] < cfg["min_events"]:
            continue
        nb = [j for j in range(max(0, i - win), min(n, i + win + 1)) if j != i]
        nb_num, nb_den = sum(num[j] for j in nb), sum(den[j] for j in nb)
        if nb_den < 4 * cfg["min_events"]:
            continue
        p = min(max(nb_num / nb_den, 0.5 / nb_den), 1 - 0.5 / nb_den)
        x, k = num[i], den[i]
        sd = math.sqrt(k * p * (1 - p))
        z = (x - k * p) / sd
        expected = round(100 * p, 3)
        resid = values[i] - expected
        material = abs(x - k * p) >= cfg["min_abs_events"] and abs(resid) >= cfg["min_relative_change"] * max(expected, 1)
        if abs(z) < cfg["min_z"] or not material:
            continue
        found.append({"week": i + 1, "value": values[i], "expected": expected, "residual": round(resid, 3), "z": round(z, 2),
                      "scale": round(100 * sd / k, 4), "neighbours": len(nb), "counts": [x, k], "neighbour_counts": [nb_num, nb_den]})
    return found


def classify_pattern(found, values, cfg):
    n = len(values)
    for a in found:
        week, expected, scale = a["week"], a["expected"], a["scale"]
        after = [values[j] for j in range(week, min(n, week + 2)) if values[j] is not None]
        a["after"] = after
        if week == n or not after:
            a["pattern"] = "UNRESOLVED"
        elif abs(after[0] - expected) <= cfg["return_within_sd"] * scale:
            a["pattern"] = "ISOLATED_SPIKE"
        elif len(after) == 2 and all(abs(x - expected) > cfg["return_within_sd"] * scale for x in after):
            a["pattern"] = "SUSTAINED_SHIFT"
        else:
            a["pattern"] = "ISOLATED_SPIKE"
    return found


def detect(entry, metric, cfg):
    kind = metric["derive"]["kind"]
    if kind == "event_ratio":
        return classify_pattern(detect_ratio(entry, cfg), entry["values"], cfg)
    values = list(entry["values"])
    if kind == "event_mean":
        # An average of 1-2 events (e.g. MTTR of a single incident) is not a stable weekly value.
        values = [v if v is not None and len(entry["event_records"][str(i + 1)]) >= cfg["min_events_for_mean"] else None
                  for i, v in enumerate(values)]
    n = len(values)
    win = cfg["window"]
    rows = []
    for i, v in enumerate(values):
        if v is None:
            continue
        nb = [values[j] for j in range(max(0, i - win), min(n, i + win + 1)) if j != i and values[j] is not None]
        if len(nb) < 4:
            continue
        rows.append((i + 1, v, median(nb), len(nb)))
    if not rows:
        return []
    base_scale = robust_sd([v - e for _, v, e, _ in rows])
    found = []
    for week, v, expected, n_nb in rows:
        scale = base_scale
        if metric.get("count_metric"):
            scale = max(scale, math.sqrt(max(expected, 1.0)))
        scale = max(scale, 1e-9, 0.01 * abs(expected))
        resid = v - expected
        z = resid / scale
        material = abs(resid) >= cfg["min_relative_change"] * abs(expected) if expected else abs(resid) >= 3
        if abs(z) < cfg["min_z"] or not material:
            continue
        found.append({"week": week, "value": v, "expected": round(expected, 3), "residual": round(resid, 3),
                      "z": round(z, 2), "scale": round(scale, 4), "neighbours": n_nb})
    return classify_pattern(found, values, cfg)


def run():
    read_envelope(AGENTS["02"])
    series = load_series()
    store, n_weeks = series["scopes"], len(series["weeks"])
    cfg = load_json(project_path("config/thresholds.json"))["anomaly"]
    catalog = load_metric_catalog()

    raw = []
    for sid, scope in store.items():
        for mid, m in catalog.items():
            if m["polarity"] == "neutral":
                continue
            for a in detect(scope["metrics"][mid], m, cfg):
                raw.append((sid, scope, m, a))

    # The same spike shows up in every scope containing the affected team/platform. Report it
    # once, at the most specific scope, and list where else it is visible.
    raw.sort(key=lambda x: (-SPECIFICITY[x[1]["type"]], x[0], x[2]["id"], x[3]["week"]))
    primaries, findings = [], []
    for sid, scope, m, a in raw:
        parent = next((p for p in primaries if p["metric"] == m["id"] and p["week"] == a["week"]
                       and set(p["pairs"]) <= set(scope["pairs"])), None)
        if parent:
            parent["finding"]["also_visible_in"].append(sid)
            continue
        adverse = (a["residual"] > 0) == (m["polarity"] == "lower_is_better")
        records = point_records(store, sid, m["id"], a["week"])
        conf = confidence.build(
            completeness=a["neighbours"] / (2 * cfg["window"]),
            n_observations=a["neighbours"],
            consistency={"ISOLATED_SPIKE": 1.0, "SUSTAINED_SHIFT": 0.6, "UNRESOLVED": 0.5}[a["pattern"]],
            effect_sd=a["z"],
        )
        word = {"ISOLATED_SPIKE": "a one-week spike that returned to normal the following week",
                "SUSTAINED_SHIFT": "a shift that persisted for the following weeks (see Trend Analysis; not called a trend here)",
                "UNRESOLVED": "the latest week, so it is not yet known whether it persists"}[a["pattern"]]
        f = {
            "id": f"ANO-{scope_tag(scope)}-{m['id'].upper()}-W{a['week']:02d}",
            "type": "anomaly",
            "pattern": a["pattern"],
            "impact": "adverse" if adverse else "favourable",
            "claim": (f"{scope['label']}: {m['label']} was {a['value']:g} {m['unit']} in week {a['week']} against an expected "
                      f"{a['expected']:g} (local median), {abs(a['z']):.1f}x the normal variation - {word}."),
            "metrics": [m["id"]],
            "dimension": {"scope": sid, "team": scope["team"], "platform": scope["platform"]},
            "weeks": [a["week"], a["week"]],
            "what_happened": f"{m['label']} {'rose' if a['residual'] > 0 else 'fell'} to {a['value']:g} {m['unit']}",
            "expected_baseline": a["expected"],
            "magnitude": {"residual": a["residual"], "z": a["z"],
                          "relative_pct": round(100 * a["residual"] / a["expected"], 1) if a["expected"] else None},
            "evidence": {
                "dataset": "metric_series",
                "series_ref": {"scope": sid, "metric": m["id"], "weeks": [a["week"]]},
                "record_ids": records,
                "values": {str(w): scope["metrics"][m["id"]]["values"][w - 1]
                           for w in range(max(1, a["week"] - cfg["window"]), min(n_weeks, a["week"] + cfg["window"]) + 1)},
                "calculation": (f"expected = median of weeks within +/-{cfg['window']} = {a['expected']}; "
                                f"residual = {a['residual']}; scale = {a['scale']}; z = {a['z']}; "
                                f"following weeks = {a['after']}"),
                "computed": {k: a[k] for k in ("value", "expected", "residual", "z", "scale", "pattern")},
            },
            "also_visible_in": [],
            "confidence": conf,
            "produced_by": AGENT,
            "related_findings": [],
            "validation": None,
        }
        primaries.append({"metric": m["id"], "week": a["week"], "pairs": scope["pairs"], "finding": f})
        findings.append(f)

    findings.sort(key=lambda f: f["id"])
    counts = {}
    for f in findings:
        counts[f["pattern"]] = counts.get(f["pattern"], 0) + 1
    summary = {"anomalies": len(findings), "by_pattern": dict(sorted(counts.items())),
               "raw_detections_before_dedup": len(raw), "rule": cfg}
    inputs = [envelope_path(AGENTS["02"]), processed_dir() / "metric_series.json", project_path("config/thresholds.json")]
    write_envelope(AGENT, "PASS", [AGENTS["02"]], inputs, summary, findings)
    return summary, findings


def main():
    s, findings = run()
    print(f"[{AGENT}] status=PASS anomalies={s['anomalies']} by_pattern={s['by_pattern']} (raw {s['raw_detections_before_dedup']})")
    for f in findings:
        print(f"  {f['id']:<45} {f['pattern']:<15} z={f['magnitude']['z']:>6} also: {', '.join(f['also_visible_in'])}")


if __name__ == "__main__":
    main()
