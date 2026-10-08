"""Agent 09 - Dashboard Generation.  Spec: agents/09_dashboard_generation_agent.md

Builds dashboard/data/dashboard_data.js, the single data file the static dashboard reads.
Everything in it comes from validated outputs:
  * series, health scores      <- Agent 02 (metric_series.json, health_scores)
  * classifications            <- Agent 04
  * findings                   <- Agent 08, verdict PASS or WARN only (REJECTED never enter)
  * narratives                 <- reasoning layer, accepted and fresh only
  * source records             <- raw data after Agent 01's directives, with data-quality flags
It then re-reads what it wrote and checks it against the sources (consistency_checks), so a
dashboard number can never silently disagree with the analysis.

The dashboard is a static page (dashboard/index.html) with no build step and no network
dependency: data is a JS file so it also works when opened straight from disk (file://).

Run:  python -m src.reporting.agent09_dashboard
"""
import hashlib
import json
import re
from statistics import mean

from src.analysis.agent02_metrics_analysis import load_series
from src.analysis.dataset import PK, load_clean_data, load_metric_catalog
from src.common.envelope import AGENTS, envelope_path, file_sha, processed_dir, read_envelope, write_envelope
from src.config import ROOT, load_json, project_path

AGENT = AGENTS["09"]
DASHBOARD_DIR = project_path("dashboard")  # tests point this at a temporary copy


def data_file():
    return DASHBOARD_DIR / "data" / "dashboard_data.js"


def index_file():
    return DASHBOARD_DIR / "index.html"
KPIS = ["overall", "delivery", "quality", "reliability", "efficiency"]
KPI_LABELS = {"overall": "Engineering Health", "delivery": "Delivery Health", "quality": "Quality Health",
              "reliability": "Reliability Health", "efficiency": "Efficiency Health"}
ROLLING = 4
FINDING_TYPES = ("trend", "anomaly", "correlation", "quality_signal", "hypothesis", "risk", "recommendation")
KEEP = ["id", "type", "classification", "pattern", "impact", "signal", "claim", "risk", "category", "severity", "rank",
        "severity_points", "severity_breakdown",
        "entity", "metrics", "dimension", "weeks", "evidence", "evidence_refs", "primary_refs", "possible_explanations",
        "explanation_verdicts", "potential_impact", "recommended_follow_up", "priority", "problem", "recommended_action",
        "expected_outcome", "owner_type", "measurement_of_success", "related_findings", "also_visible_in",
        "expected_baseline", "magnitude", "basis", "causal_claim"]


def rolling(values, n=ROLLING):
    out = []
    for i in range(len(values)):
        window = [v for v in values[max(0, i - n + 1):i + 1] if v is not None]
        out.append(round(mean(window), 1) if window else None)
    return out


def compact_finding(f):
    out = {k: f[k] for k in KEEP if k in f}
    out["verdict"] = f["validation"]["verdict"]
    out["caveats"] = f["validation"]["reasons"]
    out["confidence"] = {"score": f["confidence"]["score"], "components": f["confidence"]["components"]} if f.get("confidence") else None
    return out


def build():
    env08 = read_envelope(AGENTS["08"])
    env01 = read_envelope(AGENTS["01"])
    env02 = read_envelope(AGENTS["02"])
    env03 = read_envelope(AGENTS["03"])
    env04 = read_envelope(AGENTS["04"])
    series = load_series()
    catalog = load_metric_catalog()
    store = series["scopes"]
    n_weeks = len(series["weeks"])

    rejected_ids = {r["id"] for r in env08["rejected"]}
    findings = {f["id"]: compact_finding(f) for f in env08["findings"]
                if f["type"] in FINDING_TYPES and f["validation"]["verdict"] != "REJECT"}
    for f in findings.values():
        if "possible_explanations" in f:
            f["possible_explanations"] = [h for h in f["possible_explanations"] if h not in rejected_ids]
            f.pop("explanation_verdicts", None)
        if "evidence_refs" in f:
            f["evidence_refs"] = [r for r in f["evidence_refs"] if r not in rejected_ids]

    # Accepted narratives from the reasoning layer - only if written for this exact evidence.
    narratives, reasoning_status = {}, "NOT_RUN"
    rl_path = processed_dir() / "reasoning_layer.json"
    if rl_path.exists():
        rl = load_json(rl_path)
        if rl.get("evidence_validation_fingerprint") == file_sha(envelope_path(AGENTS["08"])):
            narratives = {n["finding_id"]: n["text"] for n in rl["narratives"]
                          if n["verdict"] == "PASS" and n["finding_id"] in findings}
            reasoning_status = rl["status"]
        else:
            reasoning_status = "STALE"

    data = load_clean_data(env01["analysis_directives"])
    dq_flags = {}
    for issue in env01["issues"] + env01["warnings"]:
        dq_flags.setdefault(issue["record_id"], []).append(
            {"rule": issue["rule"], "severity": issue["severity"], "field": issue["field"],
             "message": issue["message"], "handling": issue["handling"], "exception": issue["exception_id"]})
    records = {ds: {r[PK[ds]]: {k: v for k, v in r.items() if not k.startswith("_")} for r in rows} for ds, rows in data.items()}
    index = {}
    for ds in ("deployments", "incidents", "defects"):
        for r in data[ds]:
            index.setdefault(f"{r['team']}/{r['platform']}", {}).setdefault(str(r["week"]), {}).setdefault(ds, []).append(r[PK[ds]])

    classes = {}
    for r in env04["series_classifications"]:
        tag_id = None
        c = {k: r.get(k) for k in ("classification", "movement", "baseline", "recent", "change", "change_pct",
                                   "onset_week", "trend_window", "basis", "emerging", "latest_week_outlier")}
        classes.setdefault(r["scope"], {})[r["metric"]] = c
    for f in findings.values():
        if f["type"] == "trend":
            sid, mid = f["dimension"]["scope"], f["metrics"][0]
            classes.setdefault(sid, {}).setdefault(mid, {})["finding_id"] = f["id"]

    health = env02["health_scores"]["scopes"]
    kpi = {sid: {k: {"weekly": [w[k] for w in weeks], "rolling": rolling([w[k] for w in weeks])} for k in KPIS}
           for sid, weeks in health.items()}
    metric_scores = {sid: {mid: [w["metric_scores"].get(mid) for w in weeks] for mid in catalog}
                     for sid, weeks in health.items()}

    risks = sorted((f for f in findings.values() if f["type"] == "risk"), key=lambda f: f["rank"])
    recs = [f for f in findings.values() if f["type"] == "recommendation"]
    prio = {"P1": 0, "P2": 1, "P3": 2}
    recs.sort(key=lambda r: (prio[r["priority"]], -(r["confidence"] or {}).get("score", 0), r["id"]))
    improvements = sorted((f["id"] for f in findings.values()
                           if f["type"] == "trend" and f.get("classification") == "IMPROVING"
                           and f["dimension"]["scope"].startswith(("team:", "platform:"))))

    doc = {
        "meta": {
            "title": "Engineering Health",
            "weeks": series["weeks"], "week_starts": series["week_starts"], "n_weeks": n_weeks,
            "evidence_fingerprint": file_sha(envelope_path(AGENTS["08"]))[:12],
            "data_quality": {"status": env01["status"], "score": env01["data_quality_score"],
                             "validated_records": env01["validated_records"], "total_records": env01["summary"]["total_records"],
                             "issues": [{"rule": i["rule"], "severity": i["severity"], "record_id": i["record_id"], "field": i["field"],
                                         "message": i["message"], "handling": i["handling"], "exception": i["exception_id"]}
                                        for i in env01["issues"] + env01["warnings"]]},
            "validation": env08["summary"],
            "reasoning": reasoning_status,
            "rolling_weeks": ROLLING,
            "health_method": env02["health_scores"]["method"],
            "health_baseline_weeks": env02["health_scores"]["baseline_weeks"],
            "kpi_labels": KPI_LABELS,
        },
        "metrics": {mid: {k: m.get(k) for k in ("label", "unit", "polarity", "kpi", "category", "risk_category", "count_metric")}
                    | {"derive": m["derive"]} for mid, m in catalog.items()},
        "scopes": {sid: {k: s[k] for k in ("type", "label", "team", "platform", "pairs")} for sid, s in store.items()},
        "series": {sid: {mid: s["metrics"][mid]["values"] for mid in catalog} for sid, s in store.items()},
        "kpi": kpi,
        "metric_scores": metric_scores,
        "classifications": classes,
        "quality_status": {sid: p["status"] for sid, p in env03["quality_profiles"].items()},
        "findings": findings,
        "risks": [r["id"] for r in risks],
        "recommendations": [r["id"] for r in recs],
        "improvements": improvements,
        "narratives": narratives,
        "rejected": [{"id": r["id"], "type": r["type"], "reasons": r["reasons"]} for r in env08["rejected"]],
        "records": records,
        "record_index": index,
        "dq_flags": dq_flags,
    }
    return doc


def write_data(doc):
    data_file().parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    data_file().write_text("// Generated by Agent 09 (src/reporting/agent09_dashboard.py). Do not edit.\n"
                         f"window.EHIS_DATA = {payload};\n", encoding="utf-8", newline="\n")
    # Cache-busting: browsers cache the data file, so a regenerated analysis could show stale
    # numbers. The script tag carries a hash of the content, so any change forces a reload.
    version = hashlib.sha256(payload.encode()).hexdigest()[:12]
    html = index_file().read_text(encoding="utf-8")
    html = re.sub(r'data/dashboard_data\.js(\?v=[0-9a-f]+)?"', f'data/dashboard_data.js?v={version}"', html)
    index_file().write_text(html, encoding="utf-8", newline="\n")
    return version


def read_back():
    text = data_file().read_text(encoding="utf-8")
    return json.loads(text[text.index("=") + 1:].strip().rstrip(";"))


def consistency_checks(doc):
    """Re-read the written file and compare it with the validated sources."""
    written = read_back()
    env08 = read_envelope(AGENTS["08"])
    series = load_series()["scopes"]
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    mism = [(sid, mid) for sid, s in series.items() for mid, m in s["metrics"].items() if written["series"][sid][mid] != m["values"]]
    add("series_match_agent02", not mism, f"{len(mism)} series differ" if mism else "all 560 series identical to metric_series.json")
    rejected = {r["id"] for r in env08["rejected"]}
    leaked = sorted(rejected & set(written["findings"]))
    refs = {r for f in written["findings"].values() for r in (f.get("evidence_refs") or []) + (f.get("possible_explanations") or [])}
    add("no_rejected_findings", not leaked and not (refs & rejected), f"leaked: {leaked}" if leaked else "no rejected finding or reference present")
    v08 = {f["id"]: f for f in env08["findings"]}
    conf_mism = [fid for fid, f in written["findings"].items() if f["confidence"] and f["confidence"]["score"] != v08[fid]["confidence"]["score"]]
    add("confidence_match_agent08", not conf_mism, f"{len(conf_mism)} differ" if conf_mism else "all confidences identical to Agent 08")
    ev_mism = [fid for fid, f in written["findings"].items() if f.get("evidence") != v08[fid].get("evidence")]
    add("evidence_match_agent08", not ev_mism, f"{len(ev_mism)} differ" if ev_mism else "all evidence identical to Agent 08")
    missing = [rid for f in written["findings"].values() if isinstance(f.get("evidence"), dict)
               for rid in f["evidence"].get("record_ids", [])
               if not any(rid in written["records"][ds] for ds in written["records"])]
    add("records_resolvable", not missing, f"{len(missing)} unresolvable" if missing else "every evidence record id resolves to a source record")
    counts_ok = all(len(written["record_index"].get(p, {}).get(str(w), {}).get("deployments", [])) == series[f"tp:{p}"]["metrics"]["deployments"]["values"][w - 1]
                    for p in (s.split(":", 1)[1] for s in series if s.startswith("tp:")) for w in range(1, len(written["meta"]["weeks"]) + 1))
    add("drilldown_counts_match", counts_ok, "deployment counts equal the records reachable by drill-down")
    return checks


def run():
    doc = build()
    version = write_data(doc)
    checks = consistency_checks(doc)
    html = index_file().read_text(encoding="utf-8")
    checks.append({"check": "cache_busting", "result": "PASS" if f"dashboard_data.js?v={version}" in html else "FAIL",
                   "detail": f"index.html loads data version {version}"})
    status = "PASS" if all(c["result"] == "PASS" for c in checks) else "FAIL"
    summary = {"risks": len(doc["risks"]), "recommendations": len(doc["recommendations"]), "findings": len(doc["findings"]),
               "narratives": len(doc["narratives"]), "reasoning": doc["meta"]["reasoning"],
               "records": sum(len(v) for v in doc["records"].values()),
               "data_file": data_file().relative_to(ROOT).as_posix() if data_file().is_relative_to(ROOT) else str(data_file()),
               "bytes": data_file().stat().st_size}
    deps = [AGENTS[k] for k in ("01", "02", "03", "04", "08")]
    inputs = [envelope_path(a) for a in deps] + [processed_dir() / "metric_series.json"]
    write_envelope(AGENT, status, deps, inputs, summary, [], consistency_checks=checks,
                   errors=[c["detail"] for c in checks if c["result"] == "FAIL"])
    return summary, checks, status


def main():
    s, checks, status = run()
    print(f"[{AGENT}] status={status} risks={s['risks']} recommendations={s['recommendations']} findings={s['findings']} "
          f"narratives={s['narratives']} ({s['reasoning']}) -> {s['data_file']} ({s['bytes'] // 1024} KB)")
    for c in checks:
        print(f"  [{c['result']}] {c['check']}: {c['detail']}")


if __name__ == "__main__":
    main()
