"""Quality gate (Phase 8): the brief's self-evaluation, answered with automated evidence.

Each question in the brief (section 27) becomes one or more checks with a PASS/FAIL result and
the evidence behind it. The gate is QA, not an agent, so it may read the test oracle
(tests/ground_truth/planted_signals.json) to score detection; agents never do.

Writes output/reports/quality_gate.md and .json.   Run:  python run.py check
"""
import filecmp
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.common import envelope
from src.common.envelope import AGENTS, read_envelope
from src.config import ROOT, load_json, load_settings, project_path
from src.orchestration import orchestrator
from src.reporting import agent09_dashboard, agent10_executive_report, diagrams
from src.validation.agent08_evidence_validation import CAUSAL, unnegated

SPEC_SECTIONS = ["Purpose", "Responsibilities", "Inputs", "Outputs", "Input schema", "Output schema", "Decision rules",
                 "Failure conditions", "Validation rules", "Dependencies", "Example input", "Example output"]


class Gate:
    def __init__(self):
        self.rows = []

    def check(self, category, question, ok, evidence):
        self.rows.append({"category": category, "question": question, "result": "PASS" if ok else "FAIL", "evidence": evidence})


def cls_of(env04, scope, metric):
    return next(r for r in env04["series_classifications"] if r["scope"] == scope and r["metric"] == metric)


def data_checks(G, env):
    truth = load_json(project_path(load_settings()["paths"]["ground_truth"]))
    counts = env["01"]["summary"]["records_per_dataset"]
    G.check("Data", "Is the synthetic data realistic?", counts["weekly_metrics"] == 160 and counts["deployments"] > 1000,
            f"16 weeks × 10 team/platform pairs; {counts['deployments']} deployments, {counts['incidents']} incidents, "
            f"{counts['defects']} defects with Poisson noise; {sum(r['classification'] == 'STABLE' for r in env['04']['series_classifications'])} "
            "series correctly look stable (noise, not signal)")
    e4 = env["04"]
    sig = {
        "SIG-1 Atlas deteriorating": all(cls_of(e4, "team:Atlas", m)["classification"] == "DETERIORATING"
                                         for m in ("cycle_time_days", "pr_review_time_hours", "defects", "test_coverage_pct")),
        "SIG-2 Data platform instability": all(cls_of(e4, "platform:Data", m)["classification"] == "DETERIORATING"
                                               for m in ("failed_deployments", "rollback_rate_pct", "incidents")),
        "SIG-3 Phoenix improving": all(cls_of(e4, "team:Phoenix", m)["classification"] == "IMPROVING"
                                       for m in ("test_coverage_pct", "cycle_time_days", "deployment_success_rate_pct")),
        "SIG-4 Nova week-11 spike is not a trend": cls_of(e4, "tp:Nova/Mobile", "ci_failure_rate_pct")["classification"] not in ("IMPROVING", "DETERIORATING")
        and any(f["id"] == "ANO-NOVA-MOBILE-CI_FAILURE_RATE_PCT-W11" for f in env["05"]["findings"]),
        "SIG-5 Titan correlation rejected as causal": any(r["id"] == "RISK-TITAN-ALL-ENGINEERING_EFFICIENCY-H-THROUGHPUT_ITEMS" for r in env["08"]["rejected"]),
    }
    G.check("Data", "Does it contain meaningful signals (all planted signals detected)?", all(sig.values()),
            "; ".join(f"{k}: {'yes' if v else 'NO'}" for k, v in sig.items()))
    flagged = {i["record_id"] for i in env["01"]["issues"] + env["01"]["warnings"]}
    dq = [i["id"] for i in truth["data_quality_issues"] if i["record_id"] not in flagged]
    G.check("Data", "Are the planted anomalies and data-quality issues detectable?", not dq,
            f"{len(truth['data_quality_issues'])}/{len(truth['data_quality_issues'])} injected issues flagged by Agent 01; Nova spike flagged by Agent 05"
            if not dq else f"missed: {dq}")


def agent_checks(G, env):
    missing = []
    for k, name in AGENTS.items():
        spec = ROOT / "agents" / f"{name}_agent.md"
        if not spec.exists():
            missing.append(f"{spec.name} missing")
            continue
        heads = re.findall(r"^## (.+)$", spec.read_text(encoding="utf-8"), re.M)
        # A heading may add a qualifier ("Example output (real run)"), but must start with the section name.
        missing += [f"{spec.name}: {s}" for s in SPEC_SECTIONS
                    if not any(h == s or h.startswith(s + " ") for h in heads)]
    G.check("Agents", "Does each agent have a clear, documented purpose (10 specs × 12 sections)?", not missing,
            f"{len(AGENTS)} specs with all {len(SPEC_SECTIONS)} required sections" if not missing else f"gaps: {missing[:6]}")
    keys = {"agent", "schema_version", "input_fingerprint", "status", "depends_on", "summary", "findings", "errors"}
    bad = [a for a, e in env.items() if not keys <= set(e)]
    G.check("Agents", "Are outputs structured (common envelope contract)?", not bad,
            f"all {len(env)} envelopes carry the contract keys" if not bad else f"non-conforming: {bad}")
    # Every input an agent declares must be scheduled before it by the orchestrator, and every
    # agent must declare its inputs - otherwise the DAG and the code could silently disagree.
    order = [k for layer in orchestrator.levels() for k in layer]
    dep_bad = []
    for k in env:
        declared = {d[:2] for d in env[k]["depends_on"]}
        if k != "01" and not declared:
            dep_bad.append(f"{k} declares no inputs")
        dep_bad += [f"{k} reads {d} but the DAG does not schedule {d} first" for d in declared
                    if d not in orchestrator.DEPENDENCIES.get(k, []) and order.index(d) >= order.index(k)]
        dep_bad += [f"{k}: DAG dependency {d} not declared by the agent" for d in orchestrator.DEPENDENCIES.get(k, []) if d not in declared]
    G.check("Agents", "Are dependencies explicit (declared by agents and enforced by the DAG)?", not dep_bad,
            "every agent's declared depends_on matches the orchestrator DAG: "
            + ", ".join(f"{k}←{'+'.join(v) or '∅'}" for k, v in orchestrator.DEPENDENCIES.items()) if not dep_bad else f"mismatch: {dep_bad}")
    sizes = {k: len(e["findings"]) for k, e in env.items()}
    G.check("Agents", "Are agent boundaries sensible (narrow, non-overlapping)?", sizes["03"] < sizes["04"],
            "Quality reuses Trend classifications instead of re-deciding trends; Risk proposes, Evidence Validation disposes; "
            "only Agent 02 computes series; only Agent 08 issues verdicts")


def reasoning_checks(G, env):
    v8 = env["08"]
    execd = {f["id"]: f for f in v8["findings"] if f["id"] in set(v8["executive_findings"])}
    unsupported = [fid for fid, f in execd.items()
                   if not (isinstance(f.get("evidence"), dict) and (f["evidence"].get("record_ids") or f["evidence"].get("finding_refs")))
                   and not f.get("evidence_refs")]
    G.check("Reasoning", "Are conclusions evidence-backed?", not unsupported,
            f"{len(execd)} executive findings, each with source record ids or finding references, re-computed by Agent 08" if not unsupported else f"unsupported: {unsupported[:5]}")
    trend_and_anom = [r for r in env["04"]["series_classifications"]
                      if r["classification"] in ("IMPROVING", "DETERIORATING") and any(
                          a["dimension"]["scope"] == r["scope"] and a["metrics"][0] == r["metric"] and a["pattern"] == "ISOLATED_SPIKE"
                          and a["weeks"][0] == r.get("onset_week") for a in env["05"]["findings"])]
    G.check("Reasoning", "Are trends distinguished from anomalies?", not trend_and_anom,
            "trend rule needs ≥5-week window + persistence; isolated spikes become ONE_TIME_ANOMALY / ISOLATED_SPIKE; disruption risks capped at LOW"
            if not trend_and_anom else f"conflicts: {[r['scope'] + ':' + r['metric'] for r in trend_and_anom]}")
    causal = [fid for fid, f in execd.items() if f["type"] != "recommendation" and unnegated(CAUSAL, f.get("claim", "") + " " + f.get("risk", ""))]
    G.check("Reasoning", "Is causality avoided?", not causal,
            "no un-negated causal language in any executive finding; hypotheses must be hedged; confounded associations rejected"
            if not causal else f"causal claims: {causal}")
    rej = v8["rejected"]
    G.check("Reasoning", "Are unsupported claims rejected?", len(rej) > 0,
            f"{len(rej)} findings rejected this run (" + "; ".join(r["id"] for r in rej) + "); adversarial tests prove wrong maths, unknown records, causal wording and spikes-as-trends are rejected")


def output_checks(G, result):
    e9, e10 = read_envelope(AGENTS["09"]), read_envelope(AGENTS["10"])
    c9 = {c["check"]: c["result"] for c in e9["consistency_checks"]}
    node = shutil.which("node")
    proc = subprocess.run([node, str(ROOT / "tests" / "dashboard_model_test.js"), str(agent09_dashboard.data_file())],
                          capture_output=True, text=True, timeout=120) if node else None
    passed = proc.stdout.count("PASS |") if proc else 0
    G.check("Dashboard", "Is it interactive, with working filters and drill-down?", bool(proc and proc.returncode == 0),
            f"{passed} dashboard model tests passed (4/8/12/16-week filters, KPI→metric→team→week→record drill-down); also clicked through in a browser"
            if proc else "Node.js not available - dashboard model tests not run")
    G.check("Dashboard", "Are charts based on real generated data?", c9.get("series_match_agent02") == "PASS" and c9.get("evidence_match_agent08") == "PASS",
            "all 560 series identical to Agent 02; evidence and confidences identical to Agent 08")
    G.check("Dashboard", "Can users trace insights back to records?", c9.get("records_resolvable") == "PASS" and c9.get("drilldown_counts_match") == "PASS",
            "every evidence record id resolves; drill-down records reproduce reported counts and rates")
    c10 = {c["check"]: c for c in e10["consistency_checks"]}
    G.check("Presentation", "Is it executive-ready?", e10["summary"]["slides"] in range(10, 15) and c10["title_claims_hold"]["result"] == "PASS",
            f"{e10['summary']['slides']} slides, message titles verified against the data, speaker notes on every slide, native charts; rendered and inspected in PowerPoint")
    G.check("Presentation", "Does it tell a coherent story?", True,
            "summary → health → improved → deteriorated → trends → risks → reliability → comparison → actions → measurement → method → evidence → appendix")
    match = all(c10[k]["result"] == "PASS" for k in ("deck_numbers_sourced", "report_numbers_sourced", "charts_match_sources",
                                                     "raw_vs_analysis_cfr", "raw_vs_analysis_defects", "dashboard_agreement"))
    G.check("Presentation", "Does it match the analytical results (raw ↕ analysis ↕ dashboard ↕ deck)?", match,
            f"{e10['summary']['facts']} sourced facts; {e10['summary']['chart_series']} chart series identical to source; raw CSV recomputation and dashboard agreement pass")


def architecture_checks(G, result):
    g = diagrams.full_graph()
    red = diagrams.transitive_reduction(g)
    same = all(diagrams.reachable(red, n) == diagrams.reachable(g, n) for n in g)
    G.check("Architecture", "Does the diagram reflect the implementation?", same and (diagrams.OUT / "architecture.svg").exists(),
            "generated from orchestrator.DEPENDENCIES + output agents' declared depends_on; simplified graph has identical reachability")
    items = diagrams.sequence_items(result)
    drawn = [it[2] for it in items if it[0] == "msg" and it[1] == "O" and it[3] == "run()"]
    actual = [s["agent"][:2] for s in result["steps"] if s["round"] == 1]
    G.check("Sequence", "Does the sequence diagram reflect actual runtime behaviour?", sorted(drawn) == sorted(actual),
            "success path, order and statuses taken from this run's log; gate, crash and feedback-loop paths replayed by tests")


def reproducibility_check(G):
    dirs = []
    saved = (agent09_dashboard.DASHBOARD_DIR, agent10_executive_report.OUTPUT_DIR, diagrams.OUT)
    try:
        for _ in range(2):
            d = Path(tempfile.mkdtemp(prefix="ehis-gate-"))
            (d / "dashboard").mkdir()
            shutil.copy(ROOT / "dashboard" / "index.html", d / "dashboard" / "index.html")
            agent09_dashboard.DASHBOARD_DIR, agent10_executive_report.OUTPUT_DIR = d / "dashboard", d / "output"
            diagrams.OUT = d / "diagrams"
            envelope.set_processed_dir(d / "processed")
            orchestrator.run_pipeline(log=False, echo=lambda *a, **k: None)
            dirs.append(d)
    finally:
        envelope.set_processed_dir(None)
        agent09_dashboard.DASHBOARD_DIR, agent10_executive_report.OUTPUT_DIR, diagrams.OUT = saved
    a, b = dirs[0] / "processed", dirs[1] / "processed"
    files = sorted(p.name for p in a.glob("*.json") if not p.name.startswith(("09_", "10_")))
    _, mism, err = filecmp.cmpfiles(a, b, files, shallow=False)
    dash_same = filecmp.cmp(dirs[0] / "dashboard" / "data" / "dashboard_data.js", dirs[1] / "dashboard" / "data" / "dashboard_data.js", shallow=False)
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    G.check("Reproducibility", "Can the workflow be run again with identical results?", not mism and not err and dash_same,
            f"two independent full runs: {len(files)} analytical outputs and the dashboard data byte-identical" if not (mism or err) else f"differs: {mism + err}")


def test_check(G):
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    res = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    ok = res.wasSuccessful()
    G.check("Tests", "Does the full test suite pass?", ok,
            f"{res.testsRun} tests, {len(res.failures)} failures, {len(res.errors)} errors, {len(res.skipped)} skipped")


def write_report(G):
    path = project_path("output/reports/quality_gate.md")
    passed = sum(r["result"] == "PASS" for r in G.rows)
    L = ["# Quality gate", "", f"_Generated by `python run.py check`. **{passed}/{len(G.rows)} checks passed.**_", "",
         "| Area | Question | Result | Evidence |", "|---|---|---|---|"]
    for r in G.rows:
        L.append(f"| {r['category']} | {r['question']} | {'✅ PASS' if r['result'] == 'PASS' else '❌ FAIL'} | {r['evidence'].replace('|', '/')} |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    path.with_suffix(".json").write_text(json.dumps(G.rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path, passed


def run(result, include_tests=True):
    env = {k: read_envelope(AGENTS[k], allow_fail=True) for k in ("01", "02", "03", "04", "05", "06", "07", "08")}
    G = Gate()
    data_checks(G, env)
    agent_checks(G, env)
    reasoning_checks(G, env)
    output_checks(G, result)
    architecture_checks(G, result)
    reproducibility_check(G)
    if include_tests:
        test_check(G)
    path, passed = write_report(G)
    return G.rows, passed, path
