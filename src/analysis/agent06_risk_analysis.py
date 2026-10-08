"""Agent 06 - Risk Analysis.  Spec: agents/06_risk_analysis_agent.md

Turns signals into engineering risks: observed evidence -> possible explanation -> confidence.

Design: this agent is deliberately *recall-oriented*. It proposes every risk and every
possible explanation (hypothesis) the evidence could support, including ones a careful
analyst would doubt. Agent 08 (Evidence Validation) is *precision-oriented* and removes what
does not survive scrutiny. Generator + critic is a common agentic pattern; it keeps each
agent simple and makes rejections visible instead of silently never proposing them.

Steps
  1. attribute each DETERIORATING trend to an entity: a platform when 2+ teams on it share
     the trend, otherwise the team that shows it
  2. group by (entity, risk category) -> one risk; severity from documented points
  3. clusters of adverse one-week anomalies -> a LOW "disruption" risk (never a trend risk)
  4. attach hypotheses: correlations, leading indicators, record attributes (e.g. the share
     of incidents attributed to a change)

Run:  python -m src.analysis.agent06_risk_analysis
"""
from collections import defaultdict

from src.analysis.agent02_metrics_analysis import load_series
from src.analysis.dataset import load_clean_data, load_metric_catalog, scope_tag
from src.common import fmt
from src.common.envelope import AGENTS, envelope_path, processed_dir, read_envelope, write_envelope
from src.common.stats import pct_change
from src.analysis.trend_rules import two_proportion_test
from src.config import load_json, project_path
from src.validation import confidence

AGENT = AGENTS["06"]

TITLES = {
    "Delivery": "{e}: delivery is slowing",
    "Quality": "{e}: quality is deteriorating",
    "Reliability": "{e}: deployment and service reliability is deteriorating",
    "Operational": "{e}: incident recovery is slowing",
    "Sustainability": "{e}: on-call load is rising",
    "Engineering efficiency": "{e}: engineering efficiency is declining",
}
IMPACT = {
    "Delivery": "Planned work ships later; delivery commitments are at risk if the trend continues.",
    "Quality": "More defects reach users and more unplanned rework competes with roadmap work.",
    "Reliability": "More failed releases and customer-facing incidents on the affected services.",
    "Operational": "Longer outages when incidents occur.",
    "Sustainability": "A rising on-call burden increases fatigue and attrition risk.",
    "Engineering efficiency": "Slower feedback loops reduce how much the team can ship.",
    "Disruption": "Limited if it stays isolated; it would matter if it recurs.",
}
FOLLOW_UP = {
    "Delivery": "Locate where in the flow (review, build, deploy) the extra time accumulates.",
    "Quality": "Check whether the defect increase is concentrated where test coverage fell.",
    "Reliability": "Review the failed deployments and incidents on the affected platform together.",
    "Operational": "Review recent incident timelines for recovery bottlenecks.",
    "Sustainability": "Review on-call page volume and actionability.",
    "Engineering efficiency": "Profile the CI pipeline and compare with codebase and team growth.",
    "Disruption": "Confirm the one-off cause was captured in a post-incident review; watch for recurrence.",
}


def entity_label(store, eid):
    return store[eid]["label"]


def contributes(cls, sid, mid, direction, n_parts, tcfg):
    """Does this team's slice of a platform move the same way materially, even if it is too
    small to pass the trend test alone? Requires the full % / pp magnitude, a consistent
    direction (monotonic or persistent), and an effect of at least min_effect_sd / sqrt(n_parts):
    a slice holding 1/n of the events has ~sqrt(n) times more relative noise, so the same
    underlying change shows a proportionally smaller effect size."""
    c = cls.get((sid, mid), {})
    if c.get("classification") == "DETERIORATING":
        return True
    if c.get("movement") != direction or c.get("change") is None:
        return False
    checks = c.get("checks", {})
    consistent = checks.get("monotonic") or checks.get("significant") or checks.get("persistent")
    return bool(checks.get("magnitude_pct") and consistent
                and abs(c.get("effect_sd") or 0) >= tcfg["min_effect_sd"] / n_parts ** 0.5)


def attribute(trend_findings, cls, store, catalog, tcfg):
    """Map each deteriorating trend finding to (entity scope, metric). A platform-level trend
    stays a platform risk when 2+ teams on it contribute; with exactly one contributing team
    it becomes that team's risk."""
    det = [f for f in trend_findings if f["type"] == "trend" and f["classification"] == "DETERIORATING"]
    is_det = lambda sid, mid: cls.get((sid, mid), {}).get("classification") == "DETERIORATING"

    platform_entity = {}
    for f in det:
        s = store[f["dimension"]["scope"]]
        if s["type"] != "platform":
            continue
        mid, p = f["metrics"][0], s["platform"]
        direction = cls[(f["dimension"]["scope"], mid)]["movement"]
        teams = sorted({pair.split("/")[0] for pair in s["pairs"]})
        affected = [t for t in teams if contributes(cls, f"tp:{t}/{p}", mid, direction, len(teams), tcfg) or is_det(f"team:{t}", mid)]
        platform_entity[(p, mid)] = f"platform:{p}" if len(affected) != 1 else f"team:{affected[0]}"

    assignment = defaultdict(list)  # (entity, metric) -> [finding ids]
    for f in det:
        sid, mid = f["dimension"]["scope"], f["metrics"][0]
        s = store[sid]
        if s["type"] == "org":
            continue
        if s["type"] == "platform":
            entity = platform_entity[(s["platform"], mid)]
        elif s["type"] == "team":
            plats = sorted({pair.split("/")[1] for pair in s["pairs"]})
            entity = next((f"platform:{p}" for p in plats if platform_entity.get((p, mid)) == f"platform:{p}"), sid)
        else:  # team_platform: only used when nothing broader carries the trend
            t, p = s["team"], s["platform"]
            if is_det(f"team:{t}", mid) or is_det(f"platform:{p}", mid):
                entity = platform_entity.get((p, mid)) if platform_entity.get((p, mid)) == f"platform:{p}" else f"team:{t}"
            else:
                entity = f"team:{t}"
        assignment[(entity, mid)].append(f["id"])

    # Metrics in the same definition group describe one phenomenon (e.g. failed deployments,
    # change-failure rate, rollback rate). If any of them is a platform-level risk on one of
    # the team's platforms, the team-level variants belong to that platform risk too.
    platform_groups = {(e, catalog[m].get("definition_group")) for (e, m) in assignment
                       if e.startswith("platform:") and catalog[m].get("definition_group")}
    merged = defaultdict(list)
    for (entity, mid), ids in assignment.items():
        group = catalog[mid].get("definition_group")
        if entity.startswith(("team:", "tp:")) and group:
            plats = sorted({pair.split("/")[1] for pair in store[entity]["pairs"]})
            target = next((f"platform:{p}" for p in plats if (f"platform:{p}", group) in platform_groups), None)
            if target:
                entity = target
        merged[(entity, mid)].extend(ids)
    return merged


def change_related_hypothesis(risk_id, entity, store, data, n_weeks, tcfg):
    s = store[entity]
    pairs = set(s["pairs"])
    inc = [r for r in data["incidents"] if f"{r['team']}/{r['platform']}" in pairs]
    b_hi, r_lo = tcfg["baseline_weeks"], n_weeks - tcfg["recent_weeks"] + 1
    base = [r for r in inc if r["week"] <= b_hi]
    recent = [r for r in inc if r["week"] >= r_lo]
    if len(base) < 3 or len(recent) < 3:
        return None
    x0, x1 = sum(r["change_related"] for r in base), sum(r["change_related"] for r in recent)
    z, p = two_proportion_test(x0, len(base), x1, len(recent))
    p0, p1 = round(100 * x0 / len(base), 1), round(100 * x1 / len(recent), 1)
    return {
        "id": f"{risk_id}-H-CHANGE_RELATED", "type": "hypothesis", "basis": "record_attribute",
        "claim": (f"Deployment-related changes may be contributing to the incident increase: incidents attributed to a change "
                  f"in post-incident review went from {p0}% ({x0}/{len(base)}, weeks 1-{b_hi}) to {p1}% ({x1}/{len(recent)}, weeks {r_lo}-{n_weeks})."),
        "metrics": ["incidents", "failed_deployments"],
        "dimension": {"scope": entity, "team": s["team"], "platform": s["platform"]},
        "weeks": [1, n_weeks],
        "evidence": {"dataset": "incidents", "record_ids": [r["incident_id"] for r in base + recent],
                     "values": {"baseline": [x0, len(base)], "recent": [x1, len(recent)]},
                     "calculation": f"change_related share {p0}% -> {p1}%; two-proportion z={z}, p={p}",
                     "computed": {"z": z, "p_value": p, "baseline": [x0, len(base)], "recent": [x1, len(recent)]}},
        "confidence": confidence.build(1.0, len(base) + len(recent), 1.0 if p <= 0.05 else 0.5, abs(z)),
        "produced_by": AGENT, "related_findings": [risk_id], "validation": None,
    }


def run():
    read_envelope(AGENTS["02"])
    trends = read_envelope(AGENTS["04"])
    anomalies = read_envelope(AGENTS["05"])
    quality = read_envelope(AGENTS["03"])
    validation = read_envelope(AGENTS["01"])
    series = load_series()
    store, n_weeks = series["scopes"], len(series["weeks"])
    thresholds = load_json(project_path("config/thresholds.json"))
    rcfg, tcfg = thresholds["risk"], thresholds["trend"]
    catalog = load_metric_catalog()
    data = load_clean_data(validation["analysis_directives"])
    tier = {f"{s['team']}/{s['platform']}": s["tier"] for s in data["services"]}

    cls = {(r["scope"], r["metric"]): r for r in trends["series_classifications"]}
    tf = {f["id"]: f for f in trends["findings"]}
    assignment = attribute(trends["findings"], cls, store, catalog, tcfg)

    groups = defaultdict(dict)  # (entity, category) -> {metric: [finding ids]}
    for (entity, mid), ids in assignment.items():
        groups[(entity, catalog[mid]["risk_category"])][mid] = ids
    # Success rate is exactly 100 - change failure rate; listing both double-counts one fact.
    for metrics in groups.values():
        if "deployment_success_rate_pct" in metrics and "change_failure_rate_pct" in metrics:
            metrics.pop("deployment_success_rate_pct")

    risks, hypotheses = [], []
    pts, levels = rcfg["severity_points"], rcfg["severity_levels"]
    for (entity, category), metrics in sorted(groups.items()):
        s = store[entity]
        rid = f"RISK-{scope_tag(s)}-{category.upper().replace(' ', '_')}"
        primary = {mid: ids[0] if any(i.startswith(f"TRD-{scope_tag(s)}-") for i in ids) is False else
                   next(i for i in ids if i.startswith(f"TRD-{scope_tag(s)}-")) for mid, ids in metrics.items()}
        evidence_lines, supporting, big_metrics = [], [], []
        for mid in sorted(metrics):
            f = tf[primary[mid]]
            c = f["evidence"]["computed"]
            m = catalog[mid]
            evidence_lines.append(f"{m['label']}: {fmt.arrow(c['baseline'], c['recent'], m['unit'])} "
                                  f"({fmt.change(c['baseline'], c['recent'], m['unit'], c.get('change_pct'))}), "
                                  f"trend since week {f['weeks'][0]} [{f['id']}]")
            supporting.extend(metrics[mid])
            # A "large change" is >= large_change_pct % for levels and counts, and >= large_change_pp
            # percentage points for rates (a relative % of a small rate exaggerates).
            large = (abs(c["change"]) >= pts["large_change_pp"] if m["unit"] == "%"
                     else abs(c.get("change_pct") or 0) >= pts["large_change_pct"])
            if large:
                big_metrics.append(mid)
        quality_refs = [q["id"] for q in quality["findings"] if q["dimension"]["scope"] == entity and q["signal"] == "QUALITY_DETERIORATING"]

        points = pts["per_deteriorating_metric"] * len(metrics)
        breakdown = {"deteriorating_metrics": len(metrics)}
        if big_metrics:
            points += pts["large_change_bonus"]; breakdown["large_change"] = big_metrics
        tiers = [tier[p] for p in s["pairs"]]
        if 1 in tiers:
            points += pts["tier1_service_bonus"]; breakdown["tier1_service"] = True
        if category in ("Reliability", "Operational"):
            points += pts["reliability_impact_bonus"]; breakdown["reliability_impact"] = True
        severity = next(lv for lv, th in sorted(levels.items(), key=lambda x: -x[1]) if points >= th)

        label = entity_label(store, entity)
        metric_names = ", ".join(catalog[m]["label"].lower() for m in sorted(metrics))
        risk = {
            "id": rid, "type": "risk",
            "risk": TITLES[category].format(e=label) + f" ({metric_names}).",
            "claim": TITLES[category].format(e=label) + f" ({metric_names}).",
            "category": category, "severity": severity, "severity_points": points, "severity_breakdown": breakdown,
            "entity": entity, "metrics": sorted(metrics),
            "dimension": {"scope": entity, "team": s["team"], "platform": s["platform"]},
            "weeks": [min(tf[primary[m]]["weeks"][0] for m in metrics), n_weeks],
            "evidence": evidence_lines,
            "evidence_refs": sorted(set(supporting)) + quality_refs,
            "primary_refs": [primary[m] for m in sorted(metrics)],
            "confidence": confidence.combine([tf[primary[m]]["confidence"] for m in metrics]),
            "potential_impact": IMPACT[category],
            "recommended_follow_up": FOLLOW_UP[category],
            "possible_explanations": [],
            "produced_by": AGENT, "related_findings": [], "validation": None,
        }

        # Hypotheses from correlations involving this risk's metrics (top 2 by |r|).
        cors = [f for f in trends["findings"] if f["type"] == "correlation"
                and f["dimension"]["scope"] in ([entity] + [f"team:{p.split('/')[0]}" for p in s["pairs"]])
                and set(f["metrics"]) & set(metrics)]
        cors.sort(key=lambda f: -abs(f["evidence"]["computed"]["r"]))
        seen_others = set()
        for c in cors:
            target = next(m for m in c["metrics"] if m in metrics)
            other = next(m for m in c["metrics"] if m != target)
            if other in seen_others or len(seen_others) >= 2:
                continue  # one hypothesis per explanatory metric, at most two per risk
            seen_others.add(other)
            om = catalog[other]
            moved = "rose" if cls[(c["dimension"]["scope"], other)]["movement"] == "RISING" else "fell"
            hypotheses.append({
                "id": f"{rid}-H-{other.upper()}", "type": "hypothesis", "basis": "correlation",
                "claim": (f"{om['label']} {moved} over the same period (r={c['evidence']['computed']['r']}); "
                          f"the change in {om['label'].lower()} may be contributing to the change in {catalog[target]['label'].lower()}."),
                "metrics": [other, target], "dimension": c["dimension"], "weeks": c["weeks"],
                "evidence": {"dataset": "04_trend_analysis", "finding_refs": [c["id"]], "record_ids": c["evidence"]["record_ids"],
                             "calculation": c["evidence"]["calculation"], "computed": c["evidence"]["computed"]},
                "confidence": c["confidence"], "produced_by": AGENT, "related_findings": [rid, c["id"]], "validation": None,
            })
            risk["possible_explanations"].append(hypotheses[-1]["id"])

        # Hypotheses from Agent 03 leading indicators.
        for q in quality["findings"]:
            if q["signal"] == "POTENTIAL_LEADING_INDICATOR" and q["dimension"]["scope"] == entity and set(q["metrics"]) & set(metrics):
                lead, lagm = q["metrics"]
                hypotheses.append({
                    "id": f"{rid}-H-LEAD-{lead.upper()}", "type": "hypothesis", "basis": "leading_indicator",
                    "claim": (f"Declining {catalog[lead]['label'].lower()} may be letting more {catalog[lagm]['label'].lower()} through: "
                              f"changes in coverage preceded changes in {catalog[lagm]['label'].lower()} by {q['evidence']['computed']['lag']} week(s) "
                              f"(r={q['evidence']['computed']['r']})."),
                    "metrics": [lead, lagm], "dimension": q["dimension"], "weeks": q["weeks"],
                    "evidence": {"dataset": "03_quality_analysis", "finding_refs": [q["id"]], "record_ids": q["evidence"]["record_ids"],
                                 "calculation": q["evidence"]["calculation"], "computed": q["evidence"]["computed"]},
                    "confidence": q["confidence"], "produced_by": AGENT, "related_findings": [rid, q["id"]], "validation": None,
                })
                risk["possible_explanations"].append(hypotheses[-1]["id"])

        if category == "Reliability" and "incidents" in metrics:
            h = change_related_hypothesis(rid, entity, store, data, n_weeks, tcfg)
            if h:
                hypotheses.append(h)
                risk["possible_explanations"].append(h["id"])
        risks.append(risk)

    # Disruption risks from clusters of adverse one-week anomalies (never treated as trends).
    clusters = defaultdict(list)
    for a in anomalies["findings"]:
        if a["impact"] == "adverse" and a["pattern"] == "ISOLATED_SPIKE":
            team = a["dimension"]["team"] or a["dimension"]["platform"]
            clusters[(a["dimension"]["scope"], a["weeks"][0])].append(a)
    for (sid, week), items in sorted(clusters.items()):
        if len(items) < 2 and max(abs(i["magnitude"]["z"]) for i in items) < 6:
            continue
        s = store[sid]
        rid = f"RISK-{scope_tag(s)}-DISRUPTION-W{week:02d}"
        risks.append({
            "id": rid, "type": "risk",
            "risk": f"{s['label']}: one-week operational disruption in week {week} ({', '.join(catalog[i['metrics'][0]]['label'].lower() for i in items)}).",
            "claim": f"{s['label']}: one-week operational disruption in week {week}; values returned to normal the following week.",
            "category": "Operational", "severity": "LOW", "severity_points": 0,
            "severity_breakdown": {"note": "one-week anomalies are capped at LOW - an isolated spike is not a trend"},
            "entity": sid, "metrics": sorted(i["metrics"][0] for i in items),
            "dimension": {"scope": sid, "team": s["team"], "platform": s["platform"]},
            "weeks": [week, week],
            "evidence": [f"{catalog[i['metrics'][0]]['label']}: {i['evidence']['computed']['value']:g} vs expected "
                         f"{i['expected_baseline']:g} (z={i['magnitude']['z']}) [{i['id']}]" for i in items],
            "evidence_refs": [i["id"] for i in items], "primary_refs": [i["id"] for i in items],
            "confidence": confidence.combine([i["confidence"] for i in items]),
            "potential_impact": IMPACT["Disruption"], "recommended_follow_up": FOLLOW_UP["Disruption"],
            "possible_explanations": [], "produced_by": AGENT, "related_findings": [], "validation": None,
        })

    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    risks.sort(key=lambda r: (order[r["severity"]], -r["confidence"]["score"], r["id"]))
    for i, r in enumerate(risks, start=1):
        r["rank"] = i
    findings = risks + hypotheses
    summary = {"risks": len(risks), "hypotheses": len(hypotheses),
               "by_severity": {k: sum(r["severity"] == k for r in risks) for k in order},
               "by_category": {c: sum(r["category"] == c for r in risks) for c in sorted({r["category"] for r in risks})}}
    deps = [AGENTS[k] for k in ("01", "02", "03", "04", "05")]
    inputs = [envelope_path(a) for a in deps] + [processed_dir() / "metric_series.json", project_path("config/thresholds.json")]
    write_envelope(AGENT, "PASS", deps, inputs, summary, findings)
    return summary, risks, hypotheses


def main():
    s, risks, hyps = run()
    print(f"[{AGENT}] status=PASS risks={s['risks']} hypotheses={s['hypotheses']} by_severity={s['by_severity']}")
    for r in risks:
        print(f"  #{r['rank']} {r['severity']:<8} {r['id']:<40} conf={r['confidence']['score']} {r['risk']}")
    for h in hyps:
        print(f"    H {h['id']}: {h['claim'][:140]}")


if __name__ == "__main__":
    main()
