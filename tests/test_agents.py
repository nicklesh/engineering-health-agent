"""Phase 2 tests: agents 01-08.

* calculations (percentages, trends, pooled rates)
* each agent's expected output on the synthetic data, checked against the ground truth
* invalid inputs and missing / failed dependencies
* the Evidence Validation agent rejects unsupported claims and accepts correct ones
* idempotency: two runs give byte-identical outputs

Run:  python -m unittest discover -s tests -t . -v
"""
import copy
import filecmp
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.analysis import agent02_metrics_analysis
from src.analysis.trend_rules import classify_series, two_proportion_test
from src.common import envelope
from src.common.stats import mann_kendall, partial_correlation, pct_change, pearson
from src.config import load_json, load_settings, project_path
from src.data.loader import raw_dir
from src.validation import agent01_data_validation
from src.validation.agent08_evidence_validation import Checker
from src.analysis.dataset import PK, load_clean_data, load_metric_catalog
from tests.pipeline_helper import load, run_pipeline, shared_run

TRUTH = load_json(project_path(load_settings()["paths"]["ground_truth"]))
SIG = {s["id"]: s for s in TRUTH["signals"]}


def by_id(env):
    return {f["id"]: f for f in env["findings"]}


def classification(env04, scope, metric):
    return next(r for r in env04["series_classifications"] if r["scope"] == scope and r["metric"] == metric)


class TestCalculations(unittest.TestCase):
    def test_pct_change(self):
        self.assertEqual(pct_change(4.2, 3.1), 35.48)
        self.assertEqual(pct_change(90, 100), -10.0)
        self.assertIsNone(pct_change(5, 0))
        self.assertIsNone(pct_change(None, 3))

    def test_week_over_week_from_series(self):
        obs = agent02_metrics_analysis.observe(
            "x", {"type": "team", "team": "T", "platform": None},
            {"id": "m", "unit": "days", "polarity": "lower_is_better"},
            {"values": [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 5]}, 16, 4)
        self.assertEqual((obs["current"], obs["previous"], obs["abs_change"], obs["change_pct"]), (5, 4, 1, 25.0))
        self.assertEqual(obs["direction"], "deteriorating")
        self.assertEqual((obs["current_period"], obs["previous_period"]), (4.25, 3.0))

    def test_mann_kendall(self):
        tau, p = mann_kendall(list(range(10)))
        self.assertEqual(tau, 1.0)
        self.assertLess(p, 0.001)
        tau, p = mann_kendall([5, 5, 5, 5, 5, 5])
        self.assertEqual(tau, 0.0)

    def test_correlations(self):
        self.assertEqual(pearson([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)
        self.assertIsNone(pearson([1, 1, 1], [1, 2, 3]))
        self.assertAlmostEqual(partial_correlation(0.9, 0.95, 0.95), -0.0, places=1)

    def test_two_proportion(self):
        z, p = two_proportion_test(5, 100, 25, 100)
        self.assertGreater(z, 3)
        self.assertLess(p, 0.001)
        self.assertEqual(two_proportion_test(0, 0, 1, 10), (0.0, 1.0))

    def test_trend_rule_rejects_single_spike(self):
        cfg = load_json(project_path("config/thresholds.json"))["trend"]
        m = {"id": "x", "polarity": "lower_is_better", "count_metric": False, "unit": "%", "derive": {"kind": "weekly_field"}}
        spike = [7, 7.2, 6.8, 7.1, 6.9, 7, 7.3, 7, 6.9, 7.1, 41, 7, 6.8, 7.2, 7, 7.1]
        self.assertEqual(classify_series(spike, m, cfg)["classification"], "ONE_TIME_ANOMALY")
        ramp = [3, 3.1, 2.9, 3, 3.1, 3, 3.2, 3.5, 3.8, 4.0, 4.3, 4.5, 4.8, 5.0, 5.2, 5.5]
        self.assertEqual(classify_series(ramp, m, cfg)["classification"], "DETERIORATING")
        short = [3] * 13 + [5, 5.2, 5.4]
        self.assertNotIn(classify_series(short, m, cfg)["classification"], ("IMPROVING", "DETERIORATING"))


class TestAgentOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = shared_run()
        cls.env = {k: load(d, k) for k in ("01", "02", "03", "04", "05", "06", "07", "08")}

    def test_01_detects_every_injected_issue(self):
        env = self.env["01"]
        flagged = {i["record_id"] for i in env["issues"] + env["warnings"]}
        for issue in TRUTH["data_quality_issues"]:
            self.assertIn(issue["record_id"], flagged, issue["id"])
        self.assertEqual(env["status"], "WARN")
        self.assertEqual(env["issues"], [], "all issues are covered by documented exceptions")

    def test_02_series_traceable(self):
        series = json.loads((shared_run() / "metric_series.json").read_text(encoding="utf-8"))
        s = series["scopes"]["tp:Atlas/Web"]
        self.assertEqual(s["weekly_records"]["16"], ["WM-W16-ATLAS-WEB"])
        self.assertEqual(len(s["metrics"]["deployments"]["event_records"]["16"]), s["metrics"]["deployments"]["values"][15])
        self.assertIsNone(series["scopes"]["tp:Orion/Services"]["metrics"]["test_coverage_pct"]["values"][5], "missing stays missing")

    def test_04_signal1_deteriorating_team(self):
        for metric, expected in SIG["SIG-1"]["expected"].items():
            mid = "defects" if metric == "defects_per_week" else metric
            with self.subTest(metric=mid):
                self.assertEqual(classification(self.env["04"], "team:Atlas", mid)["classification"], expected)

    def test_04_signal2_platform_instability(self):
        for mid in ("failed_deployments", "rollback_rate_pct", "incidents", "change_failure_rate_pct"):
            with self.subTest(metric=mid):
                self.assertEqual(classification(self.env["04"], "platform:Data", mid)["classification"], "DETERIORATING")

    def test_04_signal3_improving_team(self):
        for mid in ("test_coverage_pct", "cycle_time_days", "deployment_success_rate_pct"):
            with self.subTest(metric=mid):
                self.assertEqual(classification(self.env["04"], "team:Phoenix", mid)["classification"], "IMPROVING")
        esc = classification(self.env["04"], "team:Phoenix", "escaped_defect_rate_pct")
        self.assertEqual(esc["movement"], "FALLING", "directionally improving")
        self.assertNotEqual(esc["classification"], "DETERIORATING")

    def test_04_05_signal4_spike_is_not_a_trend(self):
        for mid in ("ci_failure_rate_pct", "on_call_pages", "build_time_min"):
            with self.subTest(metric=mid):
                c = classification(self.env["04"], "tp:Nova/Mobile", mid)["classification"]
                self.assertNotIn(c, ("IMPROVING", "DETERIORATING"))
        ano = by_id(self.env["05"])["ANO-NOVA-MOBILE-CI_FAILURE_RATE_PCT-W11"]
        self.assertEqual(ano["pattern"], "ISOLATED_SPIKE")
        risk = by_id(self.env["06"])["RISK-NOVA-MOBILE-DISRUPTION-W11"]
        self.assertEqual(risk["severity"], "LOW")

    def test_06_08_signal5_correlation_not_causation(self):
        cor = by_id(self.env["04"])["COR-TITAN-ALL-THROUGHPUT_ITEMS-BUILD_TIME_MIN"]
        self.assertFalse(cor["causal_claim"])
        self.assertTrue(cor["evidence"]["computed"]["common_drivers"])
        h = by_id(self.env["08"])["RISK-TITAN-ALL-ENGINEERING_EFFICIENCY-H-THROUGHPUT_ITEMS"]
        self.assertEqual(h["validation"]["verdict"], "REJECT")
        self.assertIn("common_driver", h["validation"]["reasons"][0])

    def test_06_risks_cover_planted_problems(self):
        risks = {f["id"]: f for f in self.env["06"]["findings"] if f["type"] == "risk"}
        self.assertIn("RISK-ATLAS-ALL-QUALITY", risks)
        self.assertIn("RISK-ATLAS-ALL-DELIVERY", risks)
        self.assertIn("RISK-ALL-DATA-RELIABILITY", risks)
        self.assertFalse(any(r["entity"] == "team:Phoenix" for r in risks.values()), "improving team is not a risk")
        for r in risks.values():
            self.assertTrue(r["evidence"] and r["evidence_refs"], r["id"])

    def test_07_recommendations_are_specific_and_measurable(self):
        for r in self.env["07"]["findings"]:
            with self.subTest(rec=r["id"]):
                for field in ("problem", "evidence", "recommended_action", "expected_outcome", "owner_type", "priority", "measurement_of_success"):
                    self.assertTrue(r[field], field)
                self.assertNotRegex(r["recommended_action"], r"^(Improve|Fix) (quality|reliability)\.?$")
                self.assertTrue(any(ch.isdigit() for ch in r["recommended_action"]), "cites numbers")

    def test_08_every_finding_has_a_verdict(self):
        env = self.env["08"]
        upstream = sum(len(self.env[k]["findings"]) for k in ("02", "03", "04", "05", "06", "07"))
        self.assertEqual(len(env["findings"]), upstream)
        for f in env["findings"]:
            self.assertIn(f["validation"]["verdict"], ("PASS", "WARN", "REJECT"))
        self.assertTrue(set(env["executive_findings"]).isdisjoint({r["id"] for r in env["rejected"]}))


class TestEvidenceValidator(unittest.TestCase):
    """Feeds deliberately broken findings to the validator."""

    @classmethod
    def setUpClass(cls):
        d = shared_run()
        cls.env = {k: load(d, k) for k in ("01", "04", "05", "06", "07")}
        series = json.loads((d / "metric_series.json").read_text(encoding="utf-8"))
        data = load_clean_data(cls.env["01"]["analysis_directives"])
        ids = {r[PK[ds]] for ds, rows in data.items() for r in rows}
        cls.args = (series["scopes"], ids, load_metric_catalog(), load_json(project_path("config/thresholds.json")))

    def checker(self):
        return Checker(*self.args)

    def good_trend(self):
        return copy.deepcopy(by_id(self.env["04"])["TRD-ATLAS-ALL-CYCLE_TIME_DAYS"])

    def test_correct_claim_accepted(self):
        self.assertEqual(self.checker().validate(self.good_trend())["validation"]["verdict"], "PASS")

    def test_wrong_calculation_rejected(self):
        f = self.good_trend()
        f["evidence"]["computed"]["recent"] *= 1.5
        out = self.checker().validate(f)
        self.assertEqual(out["validation"]["verdict"], "REJECT")
        self.assertTrue(any(c["check"] == "recomputed_baseline_recent" and c["result"] == "REJECT" for c in out["validation"]["checks"]))

    def test_unidentifiable_records_rejected(self):
        f = self.good_trend()
        f["evidence"]["record_ids"].append("WM-W99-GHOST-TEAM")
        self.assertEqual(self.checker().validate(f)["validation"]["verdict"], "REJECT")

    def test_unsupported_claim_rejected(self):
        f = self.good_trend()
        f["evidence"]["record_ids"] = []
        self.assertEqual(self.checker().validate(f)["validation"]["verdict"], "REJECT")

    def test_causal_claim_rejected(self):
        f = self.good_trend()
        f["claim"] = "Atlas cycle time increased because of the drop in test coverage."
        out = self.checker().validate(f)
        self.assertEqual(out["validation"]["verdict"], "REJECT")
        f["claim"] = "This is an association, not evidence that coverage causes delay."
        self.assertEqual(self.checker().validate(f)["validation"]["verdict"], "PASS", "negated causal wording is fine")

    def test_spike_presented_as_trend_rejected(self):
        f = self.good_trend()
        f["id"] = "TRD-NOVA-MOBILE-CI_FAILURE_RATE_PCT"
        f["metrics"] = ["ci_failure_rate_pct"]
        f["dimension"]["scope"] = "tp:Nova/Mobile"
        f["evidence"]["series_ref"] = {"scope": "tp:Nova/Mobile", "metric": "ci_failure_rate_pct", "weeks": list(range(1, 17))}
        f["evidence"]["record_ids"] = ["WM-W11-NOVA-MOBILE"]
        f["evidence"]["outliers_excluded"] = []
        vals = self.args[0]["tp:Nova/Mobile"]["metrics"]["ci_failure_rate_pct"]["values"]
        f["weeks"] = [11, 16]
        f["evidence"]["computed"].update({"baseline": sorted(vals[:6])[2], "recent": sorted(vals[12:])[1], "change": 30,
                                          "window_weeks": 6, "noise_sd": 1.0, "basis": "weekly"})
        out = self.checker().validate(f)
        self.assertEqual(out["validation"]["verdict"], "REJECT")

    def test_recommendation_on_rejected_risk_rejected(self):
        ch = self.checker()
        risk = copy.deepcopy(by_id(self.env["06"])["RISK-ATLAS-ALL-QUALITY"])
        ch.verdicts.update({r: {"verdict": "REJECT"} for r in risk["primary_refs"]})
        self.assertEqual(ch.validate(risk)["validation"]["verdict"], "REJECT")
        rec = copy.deepcopy(by_id(self.env["07"])["REC-ATLAS-ALL-QUALITY"])
        ch.verdicts.update({r: {"verdict": "PASS"} for r in rec["evidence_refs"] if r not in ch.verdicts})
        self.assertEqual(ch.validate(rec)["validation"]["verdict"], "REJECT")

    def test_unhedged_hypothesis_rejected(self):
        h = copy.deepcopy(by_id(self.env["06"])["RISK-ATLAS-ALL-QUALITY-H-LEAD-TEST_COVERAGE_PCT"])
        h["claim"] = "Declining test coverage caused the defect increase."
        ch = self.checker()
        ch.verdicts[h["evidence"]["finding_refs"][0]] = {"verdict": "PASS"}
        self.assertEqual(ch.validate(h)["validation"]["verdict"], "REJECT")


class TestFailureHandling(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ehis-fail-"))
        envelope.set_processed_dir(self.dir)

    def tearDown(self):
        envelope.set_processed_dir(None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_missing_dependency_refuses_to_run(self):
        with self.assertRaises(envelope.MissingDependencyError) as cm:
            agent02_metrics_analysis.run()
        self.assertIn("01_data_validation", str(cm.exception))

    def test_validation_fail_blocks_downstream(self):
        res = agent01_data_validation.run(exceptions_path=self.dir / "none.json")
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(res["blocking_issues"])
        with self.assertRaises(envelope.DependencyFailedError):
            agent02_metrics_analysis.run()

    def test_missing_raw_file_fails_loudly(self):
        raw = self.dir / "raw"
        shutil.copytree(raw_dir(), raw)
        (raw / "incidents.csv").unlink()
        res = agent01_data_validation.run(raw=raw)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("incidents" in i["message"] for i in res["issues"]))

    def test_invalid_value_detected(self):
        raw = self.dir / "raw"
        shutil.copytree(raw_dir(), raw)
        text = (raw / "weekly_metrics.csv").read_text(encoding="utf-8").replace("2026-06-22", "2026-13-45", 1)
        (raw / "weekly_metrics.csv").write_text(text, encoding="utf-8", newline="\n")
        res = agent01_data_validation.run(raw=raw)
        self.assertTrue(any(i["field"] == "week_start" for i in res["issues"]), "bad date is caught")


class TestIdempotency(unittest.TestCase):
    def test_two_runs_identical(self):
        a, b = run_pipeline(), run_pipeline()
        files = sorted(p.name for p in a.glob("*.json"))
        self.assertEqual(files, sorted(p.name for p in b.glob("*.json")))
        match, mismatch, errors = filecmp.cmpfiles(a, b, files, shallow=False)
        self.assertEqual(mismatch + errors, [])


if __name__ == "__main__":
    unittest.main()
