"""Phase 5 tests: Agent 09 and the dashboard.

* Agent 09's own consistency checks pass (series, evidence and confidence identical to the
  analysis; no rejected findings; drill-down counts match; cache-busting).
* The dashboard model (dashboard/js/model.js) is exercised in Node: data loads, filters,
  drill-down to source records, evidence tracing.
* The page wiring: index.html loads the data file and every script it needs.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.common import envelope
from src.config import ROOT
from src.reporting import agent09_dashboard
from tests.pipeline_helper import shared_run

NODE = shutil.which("node")


class DashboardCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ehis-dash-"))
        shutil.copy(ROOT / "dashboard" / "index.html", cls.tmp / "index.html")
        cls.original_dir = agent09_dashboard.DASHBOARD_DIR
        agent09_dashboard.DASHBOARD_DIR = cls.tmp
        envelope.set_processed_dir(shared_run())
        try:
            cls.summary, cls.checks, cls.status = agent09_dashboard.run()
        finally:
            envelope.set_processed_dir(None)
            agent09_dashboard.DASHBOARD_DIR = cls.original_dir

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestAgent09(DashboardCase):
    def test_consistency_checks_pass(self):
        self.assertEqual(self.status, "PASS", [c for c in self.checks if c["result"] != "PASS"])
        names = {c["check"] for c in self.checks}
        for required in ("series_match_agent02", "no_rejected_findings", "evidence_match_agent08",
                         "confidence_match_agent08", "records_resolvable", "drilldown_counts_match", "cache_busting"):
            self.assertIn(required, names)

    def test_real_dashboard_untouched_by_tests(self):
        self.assertTrue((self.tmp / "data" / "dashboard_data.js").exists())
        self.assertNotEqual(agent09_dashboard.data_file().parent.parent, self.tmp)

    def test_page_loads_all_assets(self):
        html = (self.tmp / "index.html").read_text(encoding="utf-8")
        for asset in ("data/dashboard_data.js?v=", "js/model.js", "js/charts.js", "js/app.js", "css/dashboard.css"):
            self.assertIn(asset, html)
        for asset in ("js/model.js", "js/charts.js", "js/app.js", "css/dashboard.css"):
            self.assertTrue((ROOT / "dashboard" / asset).exists(), asset)

    @unittest.skipUnless(NODE, "Node.js not installed")
    def test_dashboard_model_in_node(self):
        proc = subprocess.run([NODE, str(ROOT / "tests" / "dashboard_model_test.js"), str(self.tmp / "data" / "dashboard_data.js")],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("FAIL", proc.stdout)
        self.assertGreaterEqual(proc.stdout.count("PASS"), 10)


if __name__ == "__main__":
    unittest.main()
