"""Agent 07 - Engineering Coach.  Spec: agents/07_engineering_coach_agent.md

Turns risks (and validated improvements worth copying) into specific, prioritised,
measurable recommendations. Each recommendation names the problem, the evidence, the action,
the expected outcome, an owner type, a priority and a success measure with a target.

The deterministic core uses a playbook keyed by the risk's leading metric, filled with the
actual numbers, services and weeks. The Claude Code reasoning layer may later rewrite the
wording; it may not change the numbers, targets or links.

Run:  python -m src.analysis.agent07_engineering_coach
"""
from src.analysis.agent02_metrics_analysis import load_series
from src.analysis.dataset import load_clean_data, load_metric_catalog, scope_tag
from src.common import fmt as format_
from src.common.envelope import AGENTS, envelope_path, read_envelope, write_envelope
from src.config import load_json, project_path
from src.validation import confidence

AGENT = AGENTS["07"]
HORIZON_WEEKS = 6

# Which metric of a risk drives the recommendation, in priority order.
LEAD_METRIC = ["test_coverage_pct", "defects", "change_failure_rate_pct", "failed_deployments", "incidents",
               "on_call_pages", "pr_review_time_hours", "cycle_time_days", "avg_pr_size_loc", "review_latency_hours",
               "build_time_min", "ci_failure_rate_pct"]


fmt = format_.value


def playbook(lead, ctx):
    """Returns (action, expected_outcome, owner_type). ctx holds entity label, services, numbers."""
    e, svc, n = ctx["entity"], ctx["services"], ctx["num"]
    plays = {
        "test_coverage_pct": (
            f"Investigate the sustained rise in defects for {e} since week {ctx['since']} ({n('defects')}) and review whether the "
            f"decline in test coverage ({n('test_coverage_pct')}) is concentrated in specific modules of {svc}. "
            f"Add a coverage gate on changed code for these services until coverage is back at baseline.",
            "Defect volume returns toward its baseline and the coverage decline stops.", "Engineering manager + tech lead"),
        "change_failure_rate_pct": (
            f"Run one joint failed-deployment review across the {e} platform services ({svc}): change failure rate "
            f"{n('change_failure_rate_pct')}, rollback rate {n('rollback_rate_pct')}, incidents {n('incidents')}. "
            f"Check which release-gating steps (pre-deploy checks, canary, automated rollback) the failing deployments bypassed.",
            "Fewer failed releases and change-related incidents on the platform.", "Platform / SRE lead"),
        "on_call_pages": (
            f"Audit on-call pages for {e} ({n('on_call_pages')} per week): classify them as actionable or noise, and link "
            f"actionable pages to the reliability review for the same platform.",
            "On-call load falls back toward baseline; pages that remain are actionable.", "SRE lead + engineering manager"),
        "pr_review_time_hours": (
            f"Find where {e}'s extra cycle time ({n('cycle_time_days')}) accumulates. PR review time rose {n('pr_review_time_hours')}: "
            f"check reviewer load and availability, and agree a review turnaround target and rotation for {svc}.",
            "Review time and cycle time return toward their baselines.", "Engineering manager"),
        "avg_pr_size_loc": (
            f"Reduce change size on {e} (average PR size {n('avg_pr_size_loc')}, first-review latency {n('review_latency_hours')}): "
            f"split work into smaller, independently reviewable PRs and track PR size in team retros.",
            "Smaller PRs that get a first review sooner.", "Tech lead"),
        "build_time_min": (
            f"Profile the CI pipeline for {e} (build time {n('build_time_min')}). Check whether the growth tracks codebase size "
            f"and team growth (headcount {n('team_headcount')}), and whether caching or parallelising test stages would "
            f"recover the lost time.",
            "Build time stabilises or falls, keeping feedback loops short as the team grows.", "Tech lead / developer-productivity owner"),
        "anomaly": (
            f"Confirm that the week-{ctx['since']} spike on {e} ({ctx['metric_list']}) has a completed post-incident review with "
            f"an identified one-off cause. Take no structural action unless a similar spike recurs within 8 weeks.",
            "The cause is documented; no recurrence.", "Team lead"),
    }
    return plays[lead]


# Short imperative headline per playbook entry, for slides and summaries (no numbers, so it
# can never disagree with the evidence).
HEADLINES = {
    "test_coverage_pct": "Find where coverage fell and gate coverage on changed code",
    "change_failure_rate_pct": "Run a joint failed-deployment review and tighten release gating",
    "on_call_pages": "Audit on-call pages: actionable versus noise",
    "pr_review_time_hours": "Unblock code review: reviewer load, turnaround target, rotation",
    "avg_pr_size_loc": "Ship smaller, independently reviewable PRs",
    "build_time_min": "Profile the CI pipeline before it slows the team further",
    "anomaly": "Confirm the post-incident review; act only if it recurs",
}


def priority(risk):
    if risk["severity"] == "CRITICAL" or (risk["severity"] == "HIGH" and risk["confidence"]["score"] >= 0.85):
        return "P1"
    if risk["severity"] in ("HIGH", "MEDIUM"):
        return "P2"
    return "P3"


def run(exclude=None):
    """`exclude`: finding ids the Evidence Validation agent rejected. The orchestrator passes
    them when it re-runs this agent, so no recommendation is built on rejected evidence."""
    exclude = set(exclude or [])
    risks_env = read_envelope(AGENTS["06"])
    trends = read_envelope(AGENTS["04"])
    quality = read_envelope(AGENTS["03"])
    validation = read_envelope(AGENTS["01"])
    series = load_series()
    store, n_weeks = series["scopes"], len(series["weeks"])
    catalog = load_metric_catalog()
    tcfg = load_json(project_path("config/thresholds.json"))["trend"]
    data = load_clean_data(validation["analysis_directives"])
    names = {f"{s['team']}/{s['platform']}": s["service_name"] for s in data["services"]}
    cls = {(r["scope"], r["metric"]): r for r in trends["series_classifications"]}
    target_week = n_weeks + HORIZON_WEEKS

    def numbers(sid):
        def n(mid):
            c = cls.get((sid, mid))
            m = catalog[mid]
            if not c or c.get("baseline") is None:
                return "n/a"
            arrow = f"{fmt(c['baseline'], m['unit'])} -> {fmt(c['recent'], m['unit'])}"
            return arrow
        return n

    recs = []
    for risk in [r for r in risks_env["findings"] if r["type"] == "risk" and r["id"] not in exclude]:
        sid = risk["entity"]
        s = store[sid]
        services = ", ".join(sorted(names[p] for p in s["pairs"]))
        is_anomaly = "DISRUPTION" in risk["id"]
        lead = "anomaly" if is_anomaly else next(m for m in LEAD_METRIC if m in risk["metrics"])
        ctx = {"entity": s["label"], "services": services, "num": numbers(sid), "since": risk["weeks"][0],
               "metric_list": ", ".join(catalog[m]["label"].lower() for m in risk["metrics"])}
        action, outcome, owner = playbook(lead, ctx)

        measure_metric = risk["metrics"][0] if is_anomaly else lead
        c = cls.get((sid, measure_metric), {})
        m = catalog[measure_metric]
        if is_anomaly:
            target = "no week above the anomaly threshold (Agent 05 rule) for 8 weeks"
            baseline = None
        else:
            baseline = c.get("baseline")
            tol = tcfg["min_change_pp"] if m["unit"] == "%" else abs(baseline) * tcfg["min_change_pct"] / 100
            bound = baseline + tol if m["polarity"] == "lower_is_better" else baseline - tol
            target = (f"{'<=' if m['polarity'] == 'lower_is_better' else '>='} {fmt(bound, m['unit'])} "
                      f"(baseline {fmt(baseline, m['unit'])} plus/minus one trend threshold)")
        recs.append({
            "id": f"REC-{risk['id'][5:]}", "type": "recommendation",
            "claim": action,
            "problem": risk["risk"],
            "evidence": risk["evidence"],
            "evidence_refs": [risk["id"]] + risk["primary_refs"],
            "recommended_action": action,
            "headline": HEADLINES[lead],
            "expected_outcome": outcome,
            "owner_type": owner,
            "priority": priority(risk),
            "measurement_of_success": {"metric": measure_metric, "scope": sid, "baseline": baseline,
                                       "current": c.get("recent"), "target": target, "by_week": target_week},
            "metrics": risk["metrics"], "dimension": risk["dimension"], "weeks": risk["weeks"],
            "confidence": risk["confidence"],
            "produced_by": AGENT, "related_findings": [risk["id"]], "validation": None,
        })

    # Improvements worth copying: teams whose quality is IMPROVING (Agent 03).
    risk_entities = {r["entity"]: r for r in risks_env["findings"]
                     if r["type"] == "risk" and r["category"] == "Quality" and r["id"] not in exclude}
    for q in quality["findings"]:
        if q.get("signal") != "QUALITY_IMPROVING" or not q["dimension"]["scope"].startswith("team:") or q["id"] in exclude:
            continue
        sid = q["dimension"]["scope"]
        s = store[sid]
        n = numbers(sid)
        peers = sorted(risk_entities)
        peer_txt = (" and share them with " + ", ".join(store[p]["label"] for p in peers) + ", where quality is deteriorating") if peers else ""
        lines = [f"{catalog[mid]['label']}: {n(mid)}" for mid in q["metrics"]]
        recs.append({
            "id": f"REC-{scope_tag(s)}-REPLICATE", "type": "recommendation",
            "claim": f"Document the practices behind {s['label']}'s quality improvement ({'; '.join(lines)}){peer_txt}.",
            "problem": f"{s['label']} improved quality while other teams declined; the practices are not yet shared.",
            "evidence": lines, "evidence_refs": [q["id"]] + q["evidence"]["finding_refs"],
            "headline": f"Spread {s['label']}'s practices to teams where quality is falling",
            "recommended_action": (f"Run a short practice review with {s['label']} covering what changed in testing, review and release "
                                   f"habits since week {q['weeks'][0]} ({'; '.join(lines)}), and publish the findings{peer_txt}."),
            "expected_outcome": "Proven practices spread to teams with deteriorating quality.",
            "owner_type": "Engineering director",
            "priority": "P2",
            "measurement_of_success": {"metric": q["metrics"][0], "scope": sid, "baseline": None, "current": None,
                                       "target": f"{s['label']} keeps its improvement; adopting teams' quality trend stops deteriorating",
                                       "by_week": target_week},
            "metrics": q["metrics"], "dimension": q["dimension"], "weeks": q["weeks"],
            "confidence": q["confidence"], "produced_by": AGENT,
            "related_findings": [q["id"]] + [risk_entities[p]["id"] for p in peers], "validation": None,
        })

    order = {"P1": 0, "P2": 1, "P3": 2}
    recs.sort(key=lambda r: (order[r["priority"]], -r["confidence"]["score"], r["id"]))
    summary = {"recommendations": len(recs), "by_priority": {p: sum(r["priority"] == p for r in recs) for p in order},
               "excluded_rejected_findings": sorted(exclude)}
    deps = [AGENTS[k] for k in ("01", "03", "04", "06")]
    inputs = [envelope_path(a) for a in deps]
    write_envelope(AGENT, "PASS", deps, inputs, summary, recs)
    return summary, recs


def main():
    s, recs = run()
    print(f"[{AGENT}] status=PASS recommendations={s['recommendations']} by_priority={s['by_priority']}")
    for r in recs:
        print(f"  {r['priority']} {r['id']}: {r['recommended_action'][:160]}")
        print(f"       success: {r['measurement_of_success']['metric']} {r['measurement_of_success']['target']} by week {r['measurement_of_success']['by_week']}")


if __name__ == "__main__":
    main()
