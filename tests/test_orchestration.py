"""Phase 3 tests: orchestration and the reasoning-layer guard rails.

Covers the success path and the three failure paths of the sequence diagram:
  validation FAIL -> stop;  agent crash -> stop;  evidence REJECT -> re-run 07 -> re-validate.
"""
import filecmp
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.common import envelope
from src.common.envelope import AGENTS
from src.config import ROOT, load_json
from src.orchestration import orchestrator, reasoning
from src.reporting import agent09_dashboard, agent10_executive_report, diagrams
from src.validation.agent08_evidence_validation import CAUSAL, Checker, unnegated
from tests.pipeline_helper import shared_run

QUIET = dict(log=False, echo=lambda *a, **k: None)


class OrchestratorCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ehis-orch-"))
        envelope.set_processed_dir(self.dir)
        # Agent 09 writes the dashboard; point it at a temporary copy.
        self.dash = self.dir / "dashboard"
        self.dash.mkdir()
        shutil.copy(ROOT / "dashboard" / "index.html", self.dash / "index.html")
        self._dash_orig = agent09_dashboard.DASHBOARD_DIR
        agent09_dashboard.DASHBOARD_DIR = self.dash
        self._out_orig = agent10_executive_report.OUTPUT_DIR
        agent10_executive_report.OUTPUT_DIR = self.dir / "output"
        self._diag_orig = diagrams.OUT
        diagrams.OUT = self.dir / "diagrams"

    def tearDown(self):
        envelope.set_processed_dir(None)
        agent09_dashboard.DASHBOARD_DIR = self._dash_orig
        agent10_executive_report.OUTPUT_DIR = self._out_orig
        diagrams.OUT = self._diag_orig
        shutil.rmtree(self.dir, ignore_errors=True)


class TestDependencyGraph(unittest.TestCase):
    def test_levels(self):
        lv = orchestrator.levels()
        self.assertEqual(lv[0], ["01"])
        self.assertIn(["04", "05"], lv, "trend and anomaly agents run in parallel")
        flat = [k for layer in lv for k in layer]
        for agent, deps in orchestrator.DEPENDENCIES.items():
            for d in deps:
                self.assertLess(flat.index(d), flat.index(agent), f"{d} must run before {agent}")

    def test_cycle_detected(self):
        with self.assertRaises(ValueError):
            orchestrator.levels({"a": ["b"], "b": ["a"]})


class TestOrchestratedRun(OrchestratorCase):
    def test_success_path_matches_sequential_run(self):
        result = orchestrator.run_pipeline(**QUIET)
        self.assertEqual(result["status"], "PASS")
        ref = shared_run()
        # Analytical outputs (agents 01-08 + series) must be byte-identical. Output-agent
        # envelopes record where they wrote files, which differs between temp directories.
        files = sorted(p.name for p in ref.glob("*.json") if not p.name.startswith(("09_", "10_")))
        self.assertTrue((self.dir / f"{AGENTS['09']}.json").exists(), "dashboard generated after validation")
        _, mismatch, errors = filecmp.cmpfiles(ref, self.dir, files, shallow=False)
        self.assertEqual(mismatch + errors, [], "orchestrated and sequential runs must be identical")

    def test_validation_fail_blocks_and_leaves_no_stale_outputs(self):
        orchestrator.run_pipeline(**QUIET)  # a previous successful run leaves outputs behind
        result = orchestrator.run_pipeline(exceptions_path=self.dir / "none.json", **QUIET)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.json")), ["01_data_validation.json"])
        self.assertIn(AGENTS["08"], result["skipped"])

    def test_agent_crash_stops_dependants(self):
        def boom():
            raise RuntimeError("simulated crash")
        with mock.patch.dict(orchestrator.RUNNERS, {"05": boom}):
            result = orchestrator.run_pipeline(**QUIET)
        self.assertEqual(result["status"], "ERROR")
        crashed = next(s for s in result["steps"] if s["agent"] == AGENTS["05"])
        self.assertIn("simulated crash", crashed["error"])
        self.assertFalse((self.dir / f"{AGENTS['06']}.json").exists())

    def test_evidence_rejection_triggers_rerun(self):
        target = "RISK-ALL-DATA-SUSTAINABILITY"
        original = Checker.risk

        def strict_risk(self, f, checks):
            original(self, f, checks)
            if f["id"] == target:
                checks.append({"check": "simulated_reviewer", "result": "REJECT", "detail": "forced for the test"})

        with mock.patch.object(Checker, "risk", strict_risk):
            result = orchestrator.run_pipeline(**QUIET)
        rounds = [s for s in result["steps"] if s["round"] > 1 and s["agent"] not in (AGENTS["09"], AGENTS["10"])]
        self.assertEqual([s["agent"] for s in rounds], [AGENTS["07"], AGENTS["08"]], "07 re-run, then 08 re-validates")
        env08 = load_json(self.dir / f"{AGENTS['08']}.json")
        self.assertEqual(env08["rerun_requests"], [])
        self.assertFalse(any(r["type"] == "recommendation" for r in env08["rejected"]))
        self.assertNotIn(target, env08["executive_findings"])
        env07 = load_json(self.dir / f"{AGENTS['07']}.json")
        self.assertNotIn("REC-ALL-DATA-SUSTAINABILITY", [r["id"] for r in env07["findings"]])
        self.assertIn(target, env07["summary"]["excluded_rejected_findings"])


class TestReasoningGuardRails(OrchestratorCase):
    def setUp(self):
        super().setUp()
        orchestrator.run_pipeline(**QUIET)
        _, self.brief = reasoning.build_brief()

    def write(self, narratives, fingerprint=None):
        doc = {"brief_fingerprint": fingerprint or self.brief["evidence_validation_fingerprint"],
               "author": "test", "narratives": narratives}
        envelope.dump_json(reasoning.reasoning_dir() / "narratives_test.json", doc)
        return {r["text"]: r for r in reasoning.ingest()["narratives"]}

    def verdict(self, results, text_start):
        return next(r for t, r in results.items() if t.startswith(text_start))

    def test_rejected_findings_excluded_from_brief(self):
        ids = {i["finding_id"] for i in self.brief["findings"]}
        self.assertNotIn("RISK-TITAN-ALL-ENGINEERING_EFFICIENCY-H-THROUGHPUT_ITEMS", ids)
        hyp = [h for i in self.brief["findings"] for h in i.get("possible_explanations", [])
               if h["id"] == "RISK-ALL-DATA-RELIABILITY-H-ON_CALL_PAGES"]
        self.assertTrue(hyp and hyp[0]["do_not_use"])

    def test_narrative_checks(self):
        res = self.write([
            {"finding_id": "RISK-ALL-DATA-RELIABILITY", "text": "Data platform change failure rate rose from 5.4% to 27.1%; this may affect customers."},
            {"finding_id": "RISK-ALL-DATA-RELIABILITY", "text": "Data platform failures rose 400% and will cost 2 million."},
            {"finding_id": "RISK-ALL-DATA-RELIABILITY", "text": "Data platform incidents rose because deployments failed."},
            {"finding_id": "RISK-ALL-DATA-RELIABILITY", "text": "Generic: reliability is getting worse; improve reliability."},
            {"finding_id": "RISK-DOES-NOT-EXIST", "text": "Atlas is fine."},
        ])
        self.assertEqual(self.verdict(res, "Data platform change failure")["verdict"], "PASS")
        bad_numbers = [r for r in res.values() if "2 million" in r["text"]][0]
        self.assertTrue(any("no_new_numbers" in x for x in bad_numbers["reasons"]))
        causal = [r for r in res.values() if "because" in r["text"]][0]
        self.assertTrue(any("no_causal_claim" in x for x in causal["reasons"]))
        generic = [r for r in res.values() if r["text"].startswith("Generic")][0]
        self.assertTrue(any("specific" in x for x in generic["reasons"]))
        self.assertEqual(self.verdict(res, "Atlas is fine")["verdict"], "REJECT")

    def test_stale_narratives_rejected(self):
        res = self.write([{"finding_id": "RISK-ALL-DATA-RELIABILITY", "text": "Data platform change failure rate rose to 27.1%."}],
                         fingerprint="0" * 64)
        r = list(res.values())[0]
        self.assertEqual(r["verdict"], "REJECT")
        self.assertTrue(any(x.startswith("stale") for x in r["reasons"]))

    def test_priority_labels_are_not_numbers(self):
        self.assertEqual(reasoning.numbers_in("Run it alongside the P1 work; Agent 08 checks it. Pages 14.5"), [14.5])

    def test_cause_as_noun_is_not_causal(self):
        self.assertEqual(unnegated(CAUSAL, "Confirm the review identified a one-off cause."), [])
        self.assertEqual(unnegated(CAUSAL, "Find the root cause of the spike."), [])
        self.assertEqual(unnegated(CAUSAL, "Low coverage causes defects."), ["causes"])


if __name__ == "__main__":
    unittest.main()
