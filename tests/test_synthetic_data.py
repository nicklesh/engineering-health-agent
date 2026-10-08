"""Phase 1 tests: the synthetic dataset is reproducible, schema-conformant (apart from the
deliberately injected issues) and actually contains the planted signals.

Run:  python -m unittest discover -s tests -v
"""
import hashlib
import json
import unittest
from collections import Counter, defaultdict
from statistics import correlation, mean, median

from jsonschema import Draft202012Validator, FormatChecker

from src.config import load_json, load_org, load_settings, project_path
from src.data import generate_synthetic_data as gen
from src.data.loader import DATASETS, raw_dir, read_dataset, without_meta

TRUTH = load_json(project_path(load_settings()["paths"]["ground_truth"]))
DQ_RECORDS = {i["record_id"] for i in TRUTH["data_quality_issues"]}


def weekly_series(rows, field, team=None, platform=None, agg=mean):
    by_week = defaultdict(list)
    for r in rows:
        if (team is None or r["team"] == team) and (platform is None or r["platform"] == platform):
            if r[field] is not None:
                by_week[r["week"]].append(r[field])
    return [agg(by_week[w]) for w in sorted(by_week)]


def event_counts(rows, team=None, platform=None, where=lambda r: True):
    c = Counter(r["week"] for r in rows
                if (team is None or r["team"] == team) and (platform is None or r["platform"] == platform) and where(r))
    return [c.get(w, 0) for w in range(1, 17)]


class TestReproducibility(unittest.TestCase):
    def test_generation_is_deterministic(self):
        a = gen.generate(load_settings(), load_org())
        b = gen.generate(load_settings(), load_org())
        self.assertEqual(a, b)

    def test_files_match_manifest(self):
        """Detects hand-edited raw data: source data must never change silently."""
        manifest = json.loads((raw_dir() / "MANIFEST.json").read_text(encoding="utf-8"))
        for name, info in manifest["files"].items():
            digest = hashlib.sha256((raw_dir() / name).read_bytes()).hexdigest()
            self.assertEqual(digest, info["sha256"], f"{name} differs from MANIFEST.json")


class TestSchemaConformance(unittest.TestCase):
    def test_rows_conform_except_injected_issues(self):
        for dataset in DATASETS:
            rows, schema = read_dataset(dataset)
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            pk = schema["x-primary-key"]
            bad = {r[pk] for r in rows if list(validator.iter_errors(without_meta(r)))
                   or any(f not in without_meta(r) for f in schema["required"])}
            with self.subTest(dataset=dataset):
                self.assertTrue(bad <= DQ_RECORDS, f"Unexpected invalid rows: {sorted(bad - DQ_RECORDS)}")
                # Guard against a vacuous pass: per-row schema issues MUST be caught here.
                expected = {i["record_id"] for i in TRUTH["data_quality_issues"]
                            if i["file"] == f"{dataset}.csv" and i["type"] in ("MISSING_VALUE", "INVALID_VALUE")}
                self.assertTrue(expected <= bad, f"Schema check missed: {sorted(expected - bad)}")

    def test_every_injected_issue_is_present(self):
        weekly = {r["record_id"]: r for r in read_dataset("weekly_metrics")[0]}
        deployments = [r["deployment_id"] for r in read_dataset("deployments")[0]]
        for issue in TRUTH["data_quality_issues"]:
            with self.subTest(issue=issue["id"]):
                if issue["type"] == "DUPLICATE_RECORD":
                    self.assertEqual(deployments.count(issue["record_id"]), 2)
                elif issue["type"] == "MISSING_VALUE":
                    self.assertIsNone(weekly[issue["record_id"]][issue["field"]])
                elif issue["type"] == "INVALID_VALUE":
                    self.assertGreater(weekly[issue["record_id"]][issue["field"]], 100)
                elif issue["type"] == "INCONSISTENT_TOTAL":
                    r = weekly[issue["record_id"]]
                    self.assertNotEqual(r["deployments"], r["successful_deployments"] + r["failed_deployments"])

    def test_aggregates_reconcile_except_injected(self):
        events = Counter((r["week"], r["team"], r["platform"]) for r in read_dataset("deployments")[0])
        # A duplicated deployment event also breaks the weekly row it rolls up into:
        # DEP-W05-NOVA-SERVICES-002 -> WM-W05-NOVA-SERVICES
        affected = DQ_RECORDS | {"WM-" + rid[4:].rsplit("-", 1)[0] for rid in DQ_RECORDS if rid.startswith("DEP-")}
        for r in read_dataset("weekly_metrics")[0]:
            if r["record_id"] in affected:
                continue
            with self.subTest(record=r["record_id"]):
                self.assertEqual(r["deployments"], events[(r["week"], r["team"], r["platform"])])


class TestPlantedSignals(unittest.TestCase):
    """Loose, human-readable checks that each signal is visible in the raw data. These test the
    generator, not the agents - the agents get their own tests in Phase 2."""

    @classmethod
    def setUpClass(cls):
        cls.wm = read_dataset("weekly_metrics")[0]
        cls.dep = read_dataset("deployments")[0]
        cls.inc = read_dataset("incidents")[0]
        cls.dfx = read_dataset("defects")[0]

    def test_sig1_deteriorating_team(self):
        for field, direction in [("cycle_time_days", 1), ("pr_review_time_hours", 1), ("test_coverage_pct", -1)]:
            s = weekly_series(self.wm, field, team="Atlas")
            with self.subTest(field=field):
                self.assertGreater(direction * (mean(s[-4:]) - mean(s[:6])), 0.15 * mean(s[:6]) if direction > 0 else 5)
        defects = event_counts(self.dfx, team="Atlas")
        self.assertGreater(mean(defects[-4:]), 1.5 * mean(defects[:6]))

    def test_sig2_deployment_instability(self):
        failed = event_counts(self.dep, platform="Data", where=lambda r: r["status"] == "FAILED")
        rolled = event_counts(self.dep, platform="Data", where=lambda r: r["rolled_back"])
        incidents = event_counts(self.inc, platform="Data")
        for name, s in [("failed", failed), ("rollbacks", rolled), ("incidents", incidents)]:
            with self.subTest(series=name):
                self.assertGreater(mean(s[-4:]), 2.5 * max(0.5, mean(s[:7])))

    def test_sig3_improving_team(self):
        cov = weekly_series(self.wm, "test_coverage_pct", team="Phoenix")
        cyc = weekly_series(self.wm, "cycle_time_days", team="Phoenix")
        self.assertGreater(mean(cov[-4:]) - mean(cov[:3]), 8)
        self.assertLess(mean(cyc[-4:]), 0.8 * mean(cyc[:3]))
        fail = [f / t for f, t in zip(event_counts(self.dep, team="Phoenix", where=lambda r: r["status"] == "FAILED"),
                                      event_counts(self.dep, team="Phoenix"))]
        self.assertLess(mean(fail[-4:]), mean(fail[:4]))

    def test_sig4_one_week_anomaly(self):
        a = gen.ANOMALY
        s = weekly_series(self.wm, "ci_failure_rate_pct", team=a["team"], platform=a["platform"])
        others = s[:a["week"] - 1] + s[a["week"]:]
        self.assertGreater(s[a["week"] - 1], 3 * median(others))
        self.assertLess(max(s[a["week"]:]), 2 * median(others), "spike must not persist")

    def test_sig5_misleading_correlation(self):
        t = gen.CORRELATION_TEAM["team"]
        throughput = weekly_series(self.wm, "throughput_items", team=t, agg=sum)
        build = weekly_series(self.wm, "build_time_min", team=t)
        headcount = weekly_series(self.wm, "team_headcount", team=t)
        self.assertGreater(correlation(throughput, build), 0.8)
        self.assertGreater(correlation(headcount, build), 0.8, "confounder must explain both")


if __name__ == "__main__":
    unittest.main()
