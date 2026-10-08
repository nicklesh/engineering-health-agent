"""Orchestrator: runs the agent graph end to end.

What it guarantees
  * Dependency order comes from one explicit DAG (DEPENDENCIES below); agents whose
    dependencies are all done run together - 04 and 05 run in parallel.
  * Clean slate: previous agent outputs are deleted first, so a failed run can never leave
    stale results from an earlier run looking current.
  * The validation gate: if Agent 01 FAILs, nothing downstream runs and the reasons are shown.
  * Fail loudly: an agent that raises stops everything that depends on it.
  * Feedback loop: when Agent 08 rejects findings that recommendations were built on, Agent 07
    is re-run without them and Agent 08 re-validates (bounded by MAX_FEEDBACK_ROUNDS).
  * A run log (timings, statuses, loop rounds) is written to output/reports/run_log.json.
    Timestamps live only there, never in analytical outputs, so outputs stay idempotent.
"""
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from src.analysis import (agent02_metrics_analysis, agent03_quality_analysis, agent04_trend_analysis,
                          agent05_anomaly_detection, agent06_risk_analysis, agent07_engineering_coach)
from src.common import envelope
from src.common.envelope import AGENTS
from src.config import ROOT, load_json, project_path
from src.reporting import agent09_dashboard, agent10_executive_report
from src.validation import agent01_data_validation, agent08_evidence_validation

DEPENDENCIES = {
    "01": [],
    "02": ["01"],
    "04": ["02"],
    "05": ["02"],
    "03": ["02", "04", "05"],
    "06": ["01", "02", "03", "04", "05"],
    "07": ["01", "03", "04", "06"],
    "08": ["01", "02", "03", "04", "05", "06", "07"],
}
RUNNERS = {
    "01": agent01_data_validation.run,
    "02": agent02_metrics_analysis.run,
    "03": agent03_quality_analysis.run,
    "04": agent04_trend_analysis.run,
    "05": agent05_anomaly_detection.run,
    "06": agent06_risk_analysis.run,
    "07": agent07_engineering_coach.run,
    "08": agent08_evidence_validation.run,
    "09": agent09_dashboard.run,
    "10": agent10_executive_report.run,
}
# Output agents run after the analysis graph AND its feedback loop, so they only ever see
# the final validated findings. 10 runs after 09 because it cross-checks the dashboard data.
OUTPUT_AGENTS = ["09", "10"]
MAX_FEEDBACK_ROUNDS = 2


def levels(deps=DEPENDENCIES):
    """Topological layers: every agent in a layer only depends on earlier layers."""
    done, out = set(), []
    remaining = dict(deps)
    while remaining:
        ready = sorted(k for k, d in remaining.items() if set(d) <= done)
        if not ready:
            raise ValueError(f"Dependency cycle among {sorted(remaining)}")
        out.append(ready)
        done.update(ready)
        for k in ready:
            remaining.pop(k)
    return out


def clean_outputs():
    removed = []
    for name in list(AGENTS.values()) + ["metric_series"]:
        p = envelope.processed_dir() / f"{name}.json"
        if p.exists():
            p.unlink()
            removed.append(p.name)
    return removed


class Run:
    def __init__(self, exceptions_path=None, log=True, echo=print):
        self.exceptions_path = exceptions_path
        self.write_log = log
        self.echo = echo
        self.steps = []
        self.status = "RUNNING"

    def step(self, key, round_=1, **kwargs):
        name = AGENTS[key]
        started = time.perf_counter()
        entry = {"agent": name, "round": round_, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            if key == "01" and self.exceptions_path is not None:
                RUNNERS[key](exceptions_path=self.exceptions_path)
            else:
                RUNNERS[key](**kwargs)
            env = envelope.read_envelope(name, allow_fail=True)
            entry.update(status=env["status"], summary=self.short_summary(key, env))
        except Exception as exc:  # fail loudly, but record why
            entry.update(status="ERROR", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        entry["seconds"] = round(time.perf_counter() - started, 2)
        self.steps.append(entry)
        self.echo(f"  [{entry['status']:<5}] {name:<24} {entry['seconds']:>5.2f}s  {entry.get('summary') or entry.get('error', '')}")
        return entry

    @staticmethod
    def short_summary(key, env):
        s = env["summary"]
        return {
            "01": lambda: f"score {s['data_quality_score']}, {s['issues']} issues, {s['warnings']} warnings",
            "02": lambda: f"{s['scopes']} scopes x {s['metrics']} metrics, {s['material_changes']} material changes",
            "03": lambda: f"signals {s['signals']}",
            "04": lambda: f"{s['trend_findings']} trends, {s['correlations']} correlations",
            "05": lambda: f"{s['anomalies']} anomalies {s['by_pattern']}",
            "06": lambda: f"{s['risks']} risks {s['by_severity']}, {s['hypotheses']} hypotheses",
            "07": lambda: f"{s['recommendations']} recommendations {s['by_priority']}"
                          + (f", excluded {s['excluded_rejected_findings']}" if s.get("excluded_rejected_findings") else ""),
            "08": lambda: f"verdicts {s['verdicts']}",
            "09": lambda: f"{s['risks']} risks, {s['findings']} findings, narratives: {s['reasoning']} -> {s['data_file']}",
            "10": lambda: f"{s['slides']} slides, {s['facts']} sourced facts, {s['chart_series']} chart series -> {s['deck']}, {s['report']}",
        }[key]()

    def execute(self):
        self.echo(f"Pipeline start - outputs in {envelope.processed_dir()}")
        removed = clean_outputs()
        if removed:
            self.echo(f"  cleaned {len(removed)} previous outputs")

        for layer in levels():
            if len(layer) == 1:
                results = [self.step(layer[0])]
            else:
                self.echo(f"  running in parallel: {', '.join(AGENTS[k] for k in layer)}")
                with ThreadPoolExecutor(max_workers=len(layer)) as pool:
                    results = list(pool.map(self.step, layer))
            failed = [r for r in results if r["status"] in ("FAIL", "ERROR")]
            if failed:
                blocked = [AGENTS[k] for lay in levels() for k in lay
                           if all(AGENTS[k] != s["agent"] for s in self.steps)]
                self.status = "BLOCKED" if all(r["status"] == "FAIL" for r in failed) else "ERROR"
                self.echo(f"Pipeline {self.status}: {', '.join(r['agent'] for r in failed)} did not pass; "
                          f"not run: {', '.join(blocked)}")
                if any(r["agent"] == AGENTS["01"] for r in failed):
                    env = envelope.read_envelope(AGENTS["01"], allow_fail=True)
                    for b in env["summary"]["blocking_issues"]:
                        self.echo(f"    blocking: {b}")
                    self.echo("    Resolve the data or add a documented entry to config/known_exceptions.json, then re-run.")
                self.skipped = blocked
                return self.finish()

        self.feedback_loop()
        for key in OUTPUT_AGENTS:
            if self.step(key)["status"] in ("FAIL", "ERROR"):
                self.status = "ERROR"
                self.echo(f"Pipeline ERROR: {AGENTS[key]} failed its consistency checks - outputs must not be used")
                return self.finish()
        if self.status == "RUNNING":
            self.status = "PASS"
        return self.finish()

    def feedback_loop(self):
        """Evidence validation FAIL path: reject -> regenerate dependants -> re-validate."""
        for round_ in range(2, MAX_FEEDBACK_ROUNDS + 2):
            env = envelope.read_envelope(AGENTS["08"], allow_fail=True)
            if not env.get("rerun_requests"):
                return
            rejected = sorted(r["id"] for r in env["rejected"] if r["type"] in ("risk", "quality_signal"))
            self.echo(f"  feedback round {round_ - 1}: {AGENTS['08']} rejected {rejected}; re-running "
                      f"{', '.join(r['agent'] for r in env['rerun_requests'])} without them")
            self.step("07", round_=round_, exclude=rejected)
            self.step("08", round_=round_)
        env = envelope.read_envelope(AGENTS["08"], allow_fail=True)
        if env.get("rerun_requests"):
            self.status = "WARN"
            self.echo(f"  feedback loop stopped after {MAX_FEEDBACK_ROUNDS} rounds with unresolved rejections")

    def finish(self):
        result = {"status": self.status, "steps": self.steps, "skipped": getattr(self, "skipped", []),
                  "processed_dir": str(envelope.processed_dir())}
        if self.status in ("PASS", "WARN"):
            env = envelope.read_envelope(AGENTS["08"], allow_fail=True)
            result["validation"] = env["summary"]
            result["rejected"] = env["rejected"]
        if self.write_log:
            path = project_path("output/reports/run_log.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
            self.echo(f"Run log: {path.relative_to(ROOT)}")
        self.echo(f"Pipeline {self.status}")
        return result


def run_pipeline(exceptions_path=None, log=True, echo=print):
    return Run(exceptions_path=exceptions_path, log=log, echo=echo).execute()
