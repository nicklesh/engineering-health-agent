"""Phase 7 tests: the diagrams reflect the implementation, not someone's memory of it."""
import shutil
import tempfile
import unittest
from pathlib import Path

from src.common import envelope
from src.config import ROOT
from src.orchestration import orchestrator
from src.reporting import agent09_dashboard, agent10_executive_report, diagrams
from src.validation.agent08_evidence_validation import Checker


def closure(g):
    return {n: diagrams.reachable(g, n) for n in g}


class DiagramCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ehis-diag-"))
        (cls.tmp / "dashboard").mkdir()
        shutil.copy(ROOT / "dashboard" / "index.html", cls.tmp / "dashboard" / "index.html")
        cls._saved = (agent09_dashboard.DASHBOARD_DIR, agent10_executive_report.OUTPUT_DIR, diagrams.OUT)
        agent09_dashboard.DASHBOARD_DIR = cls.tmp / "dashboard"
        agent10_executive_report.OUTPUT_DIR = cls.tmp / "output"
        diagrams.OUT = cls.tmp / "diagrams"
        envelope.set_processed_dir(cls.tmp / "processed")
        quiet = dict(log=False, echo=lambda *a, **k: None)
        cls.result = orchestrator.run_pipeline(**quiet)
        cls.graph = diagrams.full_graph()

    @classmethod
    def tearDownClass(cls):
        envelope.set_processed_dir(None)
        agent09_dashboard.DASHBOARD_DIR, agent10_executive_report.OUTPUT_DIR, diagrams.OUT = cls._saved
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestArchitecture(DiagramCase):
    def test_reduction_preserves_every_dependency(self):
        red = diagrams.transitive_reduction(self.graph)
        self.assertEqual(closure(red), closure(self.graph), "simplified diagram implies exactly the real dependencies")

    def test_graph_matches_orchestrator_and_envelopes(self):
        for k, deps in orchestrator.DEPENDENCIES.items():
            self.assertTrue(set(deps) <= self.graph[k])
        for k in orchestrator.OUTPUT_AGENTS:
            env = envelope.read_envelope(envelope.AGENTS[k])
            self.assertTrue({d[:2] for d in env["depends_on"]} <= self.graph[k])

    def test_mermaid_has_every_agent_and_edge(self):
        mm = diagrams.architecture_mermaid()
        for k in self.graph:
            self.assertIn(f"A{k}[", mm)
        for n, deps in diagrams.transitive_reduction(self.graph).items():
            for d in deps:
                self.assertIn(f"A{d} --> A{n}", mm)
        self.assertIn("A08 -.", mm, "evidence feedback loop drawn")
        self.assertIn("BLOCKED", mm, "validation gate drawn")


class TestSequence(DiagramCase):
    def run_order(self, items):
        """Agents in the order the diagram calls them, outside loops and alternatives."""
        order, depth = [], 0
        for it in items:
            if it[0] in ("alt", "loop"):
                depth += 1
            elif it[0] == "end" and depth:
                depth -= 1
            elif it[0] == "msg" and it[1] == "O" and it[3] == "run()" and depth == 0:
                order.append(it[2])
        return order

    def test_success_path_matches_actual_run(self):
        items = diagrams.sequence_items(self.result)
        actual = [s["agent"][:2] for s in self.result["steps"] if s["round"] == 1]
        drawn = self.run_order(items)
        self.assertEqual(sorted(drawn), sorted(actual))
        par = next(l for l in orchestrator.levels() if len(l) > 1)
        self.assertEqual([k for k in drawn if k not in par], [k for k in actual if k not in par], "same order outside the parallel layer")

    def test_statuses_come_from_the_run(self):
        items = diagrams.sequence_items(self.result)
        rets = {it[1]: it[3] for it in items if it[0] == "ret" and it[2] == "O" and it[3] in ("PASS", "WARN", "FAIL")}
        for s in (s for s in self.result["steps"] if s["round"] == 1):
            self.assertEqual(rets[s["agent"][:2]], s["status"])

    def test_failure_paths_drawn_and_real(self):
        mm = diagrams.sequence_mermaid(diagrams.sequence_items(self.result))
        self.assertIn("alt 01 status = FAIL", mm)
        self.assertIn(f"loop while 08 has rerun_requests (max {orchestrator.MAX_FEEDBACK_ROUNDS} rounds)", mm)
        self.assertIn("ERROR", mm)
        # ...and the drawn feedback loop really happens: force a rejection and replay.
        original = Checker.risk

        def strict(self, f, checks):
            original(self, f, checks)
            if f["id"] == "RISK-ALL-DATA-SUSTAINABILITY":
                checks.append({"check": "forced", "result": "REJECT", "detail": "test"})
        from unittest import mock
        with mock.patch.object(Checker, "risk", strict):
            res = orchestrator.run_pipeline(log=False, echo=lambda *a, **k: None)
        rounds = [s["agent"][:2] for s in res["steps"] if s["round"] > 1]
        self.assertEqual(rounds[:2], ["07", "08"], "07 re-run, then 08 re-validates - as drawn")

    def test_files_written(self):
        files, _ = diagrams.write(self.result)
        for name in ("architecture.mmd", "architecture.svg", "sequence.mmd", "sequence.svg"):
            self.assertTrue((diagrams.OUT / name).exists(), name)
        self.assertTrue((diagrams.OUT / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
