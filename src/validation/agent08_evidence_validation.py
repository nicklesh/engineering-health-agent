"""Agent 08 - Evidence Validation.  Spec: agents/08_evidence_validation_agent.md

The critic. Re-checks every finding from Agents 02-07 against the data, independently of the
code that produced it, and gives each one PASS / WARN / REJECT:

  1. Is the claim supported by evidence?            -> evidence_present
  2. Can the source records be identified?           -> records_identifiable
  3. Is the calculation correct?                     -> recomputed_* (from the series / raw counts)
  4. Is this actually a trend?                       -> trend_window, not_single_spike
  5. Could it simply be an anomaly?                  -> anomaly_returns, anomaly_language
  6. Is causality being claimed?                     -> no_causal_claim, hedged, common_driver, co_trending_only
  7. Is the confidence appropriate?                  -> confidence_consistent, high_confidence_support
  8. Does the recommendation follow?                 -> linked_risk, success_metric_linked, priority_matches

Validation order matters: primitive findings first, then hypotheses and risks that depend on
them, then recommendations - so a rejection cascades to everything built on it.
Rejected findings never reach executive outputs. WARN findings are shown, marked as such.

Run:  python -m src.validation.agent08_evidence_validation
"""
import copy
import re
import sys
from statistics import mean, median

from src.analysis.agent02_metrics_analysis import load_series
from src.analysis.dataset import PK, load_clean_data, load_metric_catalog, pooled_ratio
from src.common.envelope import AGENTS, envelope_path, processed_dir, read_envelope, write_envelope
from src.common.stats import pearson
from src.config import load_json, project_path
from src.validation import confidence

AGENT = AGENTS["08"]
RANK = {"PASS": 0, "WARN": 1, "REJECT": 2}
CAUSAL = re.compile(r"\b(caus(?:e|es|ed|ing)|due to|because(?: of)?|drives|driven by|leads? to|led to|results? in|"
                    r"resulted in|is responsible for|the reason for)\b", re.I)
NEGATION = re.compile(r"\b(not|no|never|without|rather than)\b", re.I)
HEDGE = re.compile(r"\b(may|might|could|possibl[ey]|associated|potential)\b", re.I)
TREND_WORDS = re.compile(r"\b(trend|sustained|steadily|consistently|increasingly)\b", re.I)


# "cause" after these words is a noun ("identify the root cause"), not a causal claim.
NOUN_CAUSE = {"a", "an", "the", "root", "one-off", "underlying", "likely", "possible", "probable",
              "identified", "its", "their", "main", "primary", "any", "no"}


def unnegated(pattern, text):
    """Matches of `pattern` that are not preceded (within ~40 chars) by a negation."""
    hits = []
    for m in pattern.finditer(text or ""):
        before = text[max(0, m.start() - 40):m.start()]
        words = before.lower().split()
        if m.group(0).lower() == "cause" and words and words[-1] in NOUN_CAUSE:
            continue
        if not NEGATION.search(before):
            hits.append(m.group(0))
    return hits


def close(a, b, tol):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(tol, tol * abs(b))


class Checker:
    def __init__(self, store, valid_ids, catalog, thresholds):
        self.store = store
        self.valid_ids = valid_ids
        self.catalog = catalog
        self.cfg = thresholds["evidence_validation"]
        self.tcfg = thresholds["trend"]
        self.ccfg = thresholds["correlation"]
        self.acfg = thresholds["anomaly"]
        self.verdicts = {}

    # ---------------------------------------------------------------- helpers
    def check(self, checks, name, ok, detail, fail="REJECT"):
        checks.append({"check": name, "result": "PASS" if ok else fail, "detail": detail})

    def values(self, f, metric=None):
        ref = f["evidence"]["series_ref"]
        return self.store[ref["scope"]]["metrics"][metric or ref["metric"]]

    def common(self, f, checks):
        ev = f.get("evidence") or {}
        ids = ev.get("record_ids", []) if isinstance(ev, dict) else []
        refs = (ev.get("finding_refs", []) if isinstance(ev, dict) else []) + f.get("evidence_refs", [])
        self.check(checks, "evidence_present", bool(ids or refs), f"{len(ids)} record ids, {len(refs)} finding refs")
        if ids:
            missing = [i for i in ids if i not in self.valid_ids]
            self.check(checks, "records_identifiable", not missing,
                       "all source records found in the validated data" if not missing else f"unknown record ids: {missing[:5]}")
        if f["type"] != "recommendation":
            text = f.get("claim", "") + " " + f.get("risk", "")
            hits = unnegated(CAUSAL, text)
            self.check(checks, "no_causal_claim", not hits and not f.get("causal_claim"),
                       "no causal language" if not hits else f"causal language without evidence: {sorted(set(hits))}")
        conf = f.get("confidence")
        if conf:
            w = load_json(project_path("config/thresholds.json"))["confidence"]["weights"]
            keys = confidence.ANALYTICAL
            recomputed = round(sum(w[k] * conf["components"][k] for k in keys) / sum(w[k] for k in keys), 2)
            self.check(checks, "confidence_consistent", close(recomputed, conf["score"], self.cfg["confidence_tolerance"]),
                       f"score {conf['score']} vs recomputed from components {recomputed}", fail="WARN")

    def ref_verdict(self, fid):
        return self.verdicts.get(fid, {}).get("verdict")

    # ---------------------------------------------------------------- per type
    def metric_change(self, f, checks):
        e = self.values(f)["values"]
        c = f["evidence"]["computed"]
        weeks = f["evidence"]["series_ref"]["weeks"]
        half = len(weeks) // 2
        prev = [e[w - 1] for w in weeks[:half] if e[w - 1] is not None]
        cur = [e[w - 1] for w in weeks[half:] if e[w - 1] is not None]
        ok = prev and cur and close(round(mean(cur), 3), c["current_period"], self.cfg["value_tolerance"]) \
            and close(round(mean(prev), 3), c["previous_period"], self.cfg["value_tolerance"])
        self.check(checks, "recomputed_period_means", bool(ok),
                   f"recomputed {round(mean(cur), 3) if cur else None} vs {round(mean(prev), 3) if prev else None}")
        if ok:
            pct = round((mean(cur) - mean(prev)) / abs(mean(prev)) * 100, 2) if mean(prev) else None
            self.check(checks, "recomputed_change_pct", close(pct, c["change_pct"], 0.02), f"recomputed {pct}% vs claimed {c['change_pct']}%")

    def trend(self, f, checks):
        if f["classification"] == "ONE_TIME_ANOMALY":
            return self.one_time(f, checks)
        entry = self.values(f)
        m = self.catalog[f["metrics"][0]]
        c = f["evidence"]["computed"]
        n = len(entry["values"])
        b_hi, r_lo = self.tcfg["baseline_weeks"], n - self.tcfg["recent_weeks"] + 1
        lo, hi = f["weeks"]
        direction = 1 if c["change"] > 0 else -1
        if c.get("basis", "").startswith("pooled"):
            x0, n0 = sum(entry["numerator"][:b_hi]), sum(entry["denominator"][:b_hi])
            x1, n1 = sum(entry["numerator"][r_lo - 1:]), sum(entry["denominator"][r_lo - 1:])
            ok = [x0, n0] == c["pooled_counts"]["baseline"] and [x1, n1] == c["pooled_counts"]["recent"]
            self.check(checks, "recomputed_pooled_counts", ok, f"baseline {x0}/{n0}, recent {x1}/{n1} from event records")
            series = {w: pooled_ratio(entry, w, self.tcfg["ratio_pooling_weeks"]) for w in range(lo, hi + 1)}
        else:
            out = {o["week"] for o in f["evidence"].get("outliers_excluded", [])}
            vals = entry["values"]
            base = [vals[w - 1] for w in range(1, b_hi + 1) if vals[w - 1] is not None and w not in out]
            rec = [vals[w - 1] for w in range(r_lo, n + 1) if vals[w - 1] is not None and w not in out]
            b, r = median(base), median(rec)
            self.check(checks, "recomputed_baseline_recent",
                       close(b, c["baseline"], self.cfg["value_tolerance"]) and close(r, c["recent"], self.cfg["value_tolerance"]),
                       f"baseline median {b} (claimed {c['baseline']}), recent median {r} (claimed {c['recent']})")
            series = {w: vals[w - 1] for w in range(lo, hi + 1) if w not in out}
        beyond = [w for w, v in series.items() if v is not None and direction * (v - c["baseline"]) > abs(c["noise_sd"])]
        need = self.tcfg["min_trend_weeks"]
        self.check(checks, "trend_window", c["window_weeks"] >= need and len(beyond) >= need - 2,
                   f"{c['window_weeks']}-week window with {len(beyond)} weeks beyond baseline + noise (need {need} and {need - 2})")
        if not c.get("basis", "").startswith("pooled"):
            rest = [v for w, v in series.items() if v is not None]
            if len(rest) > 2:
                worst = max(rest, key=lambda v: direction * (v - c["baseline"]))
                rest.remove(worst)
                still = direction * (median(rest) - c["baseline"]) > 0
                self.check(checks, "not_single_spike", still,
                           "the change holds after removing the most extreme week" if still else "the change depends on one extreme week")
        conf = f["confidence"]["score"]
        self.check(checks, "high_confidence_support",
                   not (conf >= self.cfg["high_confidence"] and c["window_weeks"] < self.cfg["min_weeks_for_high_confidence"]),
                   f"confidence {conf} over a {c['window_weeks']}-week window", fail="WARN")

    def one_time(self, f, checks):
        entry = self.values(f)
        week = f["weeks"][0]
        vals = entry["values"]
        claimed = f["evidence"]["values"].get(str(week))
        self.check(checks, "recomputed_value", close(vals[week - 1], claimed, self.cfg["value_tolerance"]),
                   f"week {week} value {vals[week - 1]} (claimed {claimed})")
        hits = unnegated(TREND_WORDS, f["claim"])
        self.check(checks, "anomaly_language", not hits, "described as a one-time deviation" if not hits else f"trend wording: {hits}")

    def anomaly(self, f, checks):
        entry = self.values(f)
        c = f["evidence"]["computed"]
        week = f["weeks"][0]
        vals = entry["values"]
        self.check(checks, "recomputed_value", close(vals[week - 1], c["value"], self.cfg["value_tolerance"]),
                   f"week {week} value {vals[week - 1]} (claimed {c['value']})")
        if c["pattern"] == "ISOLATED_SPIKE":
            nxt = vals[week] if week < len(vals) else None
            ok = nxt is not None and abs(nxt - c["expected"]) <= self.acfg["return_within_sd"] * c["scale"]
            self.check(checks, "anomaly_returns", ok, f"week {week + 1} value {nxt} vs expected {c['expected']} +/- {self.acfg['return_within_sd']} x {c['scale']}")
            hits = unnegated(TREND_WORDS, f["claim"])
            self.check(checks, "anomaly_language", not hits, "not described as a trend" if not hits else f"trend wording: {hits}")
        z = abs(c["z"])
        self.check(checks, "magnitude", z >= 5, f"|z| = {z} (threshold {self.acfg['min_z']}); marginal detections are flagged", fail="WARN")

    def correlation(self, f, checks):
        ref = f["evidence"]["series_ref"]
        a = self.store[ref["scope"]]["metrics"][ref["metric"]]["values"]
        b = self.store[ref["scope"]]["metrics"][ref["metric_2"]]["values"]
        idx = [w - 1 for w in ref["weeks"]]
        r = pearson([a[i] for i in idx], [b[i] for i in idx])
        self.check(checks, "recomputed_r", close(r, f["evidence"]["computed"]["r"], 0.001), f"r = {r} (claimed {f['evidence']['computed']['r']})")

    def quality_signal(self, f, checks):
        if f["signal"] in ("QUALITY_IMPROVING", "QUALITY_DETERIORATING"):
            refs = f["evidence"]["finding_refs"]
            ok = [r for r in refs if self.ref_verdict(r) in ("PASS", "WARN")]
            self.check(checks, "supporting_trends_valid", len(ok) >= 2, f"{len(ok)} of {len(refs)} supporting trends survived validation")
        elif f["signal"] == "POTENTIAL_LEADING_INDICATOR":
            ref = f["evidence"]["series_ref"]
            s = self.store[ref["scope"]]["metrics"]
            a, b, k = s[ref["metric"]]["values"], s[ref["metric_2"]]["values"], ref["lag"]
            idx = [w - 1 for w in ref["weeks"]]
            r = pearson([a[i] for i in idx], [b[i + k] for i in idx])
            self.check(checks, "recomputed_lagged_r", close(r, f["evidence"]["computed"]["r"], 0.001), f"r = {r}")

    def hypothesis(self, f, checks):
        self.check(checks, "hedged", bool(HEDGE.search(f["claim"])), "phrased as a possibility" if HEDGE.search(f["claim"]) else "stated as fact")
        basis = f["basis"]
        comp = f["evidence"].get("computed", {})
        if basis == "correlation":
            drivers = comp.get("common_drivers") or []
            explained = [d for d in drivers if d["partial_r"] is not None and abs(d["partial_r"]) < self.ccfg["partial_r_explained_below"]]
            if explained:
                d = explained[0]
                self.check(checks, "common_driver", False,
                           f"both metrics track {d['metric']} (r={d['r_with_first']}, {d['r_with_second']}); controlling for it the "
                           f"association drops to r={d['partial_r']}. A common driver explains the correlation - correlation is not causation.")
                return
            rd = comp.get("r_differences")
            self.check(checks, "co_trending_only", rd is not None and abs(rd) >= 0.2,
                       f"week-to-week changes correlate at r={rd}; " +
                       ("the series move together beyond a shared trend" if rd is not None and abs(rd) >= 0.2
                        else "the two series only share a time trend - two things that both drift over time will always correlate"))
            self.check(checks, "causality_not_established", False,
                       "an association between observational series cannot establish contribution; shown as a possibility only", fail="WARN")
        elif basis == "leading_indicator":
            ref = f["evidence"]["finding_refs"][0]
            self.check(checks, "underlying_finding_valid", self.ref_verdict(ref) in ("PASS", "WARN"), f"{ref}: {self.ref_verdict(ref)}")
            self.check(checks, "causality_not_established", False, "a lagged association is a lead to investigate, not proof", fail="WARN")
        elif basis == "record_attribute":
            p = comp.get("p_value", 1)
            self.check(checks, "record_level_support", p <= 0.05,
                       f"post-incident attribution share changed significantly (p={p})" if p <= 0.05 else f"change not significant (p={p})",
                       fail="WARN")

    def risk(self, f, checks):
        refs = f["primary_refs"]
        valid = [r for r in refs if self.ref_verdict(r) in ("PASS", "WARN")]
        rejected = [r for r in refs if self.ref_verdict(r) == "REJECT"]
        self.check(checks, "supporting_evidence_valid", bool(valid),
                   f"{len(valid)} of {len(refs)} supporting findings survived validation" + (f"; rejected: {rejected}" if rejected else ""))
        if rejected and valid:
            self.check(checks, "severity_basis", False, f"severity was computed with rejected evidence {rejected}", fail="WARN")
        if "DISRUPTION" in f["id"]:
            self.check(checks, "anomaly_not_escalated", f["severity"] == "LOW", f"one-week disruption rated {f['severity']}")
        expl = f.get("possible_explanations", [])
        f["_explanations"] = {h: self.ref_verdict(h) for h in expl}

    def recommendation(self, f, checks):
        risk_ids = [r for r in f["related_findings"] if r.startswith(("RISK-", "QUA-"))]
        primary = risk_ids[0]
        v = self.ref_verdict(primary)
        self.check(checks, "linked_finding_valid", v in ("PASS", "WARN"), f"{primary}: {v}")
        if v == "WARN":
            self.check(checks, "linked_finding_warned", False, f"{primary} carries a warning", fail="WARN")
        unknown = [r for r in f["evidence_refs"] if r not in self.verdicts]
        self.check(checks, "evidence_refs_known", not unknown, "all referenced findings exist" if not unknown else f"unknown: {unknown}")
        msm = f["measurement_of_success"]
        self.check(checks, "success_metric_linked", msm["metric"] in f["metrics"],
                   f"success metric {msm['metric']} is one of the problem metrics", fail="WARN")
        sev = self.verdicts.get(primary, {}).get("severity")
        expect = {"CRITICAL": "P1", "HIGH": ("P1", "P2"), "MEDIUM": "P2", "LOW": "P3"}.get(sev)
        if expect:
            self.check(checks, "priority_matches", f["priority"] in (expect if isinstance(expect, tuple) else (expect,)),
                       f"priority {f['priority']} for a {sev} risk", fail="WARN")

    # ---------------------------------------------------------------- driver
    def validate(self, f):
        checks = []
        self.common(f, checks)
        getattr(self, f["type"])(f, checks)
        verdict = max((c["result"] for c in checks), key=RANK.get, default="PASS")
        reasons = [f"{c['check']}: {c['detail']}" for c in checks if c["result"] != "PASS"]
        self.verdicts[f["id"]] = {"verdict": verdict, "severity": f.get("severity")}
        out = copy.deepcopy(f)
        out.pop("_explanations", None)
        if "_explanations" in f:
            out["explanation_verdicts"] = f["_explanations"]
        out["validation"] = {"verdict": verdict, "checks": checks, "reasons": reasons, "validated_by": AGENT}
        if f.get("confidence"):
            out["analytical_confidence"] = f["confidence"]
            out["confidence"] = confidence.validated(f["confidence"], verdict)
        return out


def run():
    validation = read_envelope(AGENTS["01"])
    envs = {k: read_envelope(AGENTS[k]) for k in ("02", "03", "04", "05", "06", "07")}
    series = load_series()
    thresholds = load_json(project_path("config/thresholds.json"))
    catalog = load_metric_catalog()
    data = load_clean_data(validation["analysis_directives"])
    valid_ids = {r[PK[ds]] for ds, rows in data.items() for r in rows}

    ch = Checker(series["scopes"], valid_ids, catalog, thresholds)
    by_type = {}
    for k in ("02", "04", "05", "03", "06", "07"):
        for f in envs[k]["findings"]:
            by_type.setdefault(f["type"], []).append(f)
    order = ["metric_change", "trend", "anomaly", "correlation", "quality_signal", "hypothesis", "risk", "recommendation"]
    validated = []
    for t in order:
        for f in by_type.get(t, []):
            validated.append(ch.validate(f))

    counts = {}
    for f in validated:
        v = f["validation"]["verdict"]
        counts.setdefault(f["type"], {"PASS": 0, "WARN": 0, "REJECT": 0})[v] += 1
    rejected = [{"id": f["id"], "type": f["type"], "reasons": f["validation"]["reasons"]} for f in validated
                if f["validation"]["verdict"] == "REJECT"]
    rerun = []
    if any(r["type"] == "recommendation" for r in rejected):
        rerun.append({"agent": AGENTS["07"], "reason": "recommendations depend on rejected findings; regenerate without them"})
    executive = [f["id"] for f in validated if f["validation"]["verdict"] != "REJECT"
                 and f["type"] in ("risk", "recommendation", "trend", "anomaly", "quality_signal", "hypothesis", "correlation")]
    total = {v: sum(c[v] for c in counts.values()) for v in ("PASS", "WARN", "REJECT")}
    summary = {"validated": len(validated), "verdicts": total, "by_type": counts,
               "rejected": len(rejected), "executive_findings": len(executive)}
    status = "PASS" if total["REJECT"] == 0 else "WARN"
    deps = [AGENTS[k] for k in ("01", "02", "03", "04", "05", "06", "07")]
    inputs = [envelope_path(a) for a in deps] + [processed_dir() / "metric_series.json", project_path("config/thresholds.json")]
    write_envelope(AGENT, status, deps, inputs, summary, validated,
                   rejected=rejected, executive_findings=executive, rerun_requests=rerun)
    return summary, validated, rejected


def main():
    s, validated, rejected = run()
    print(f"[{AGENT}] validated={s['validated']} verdicts={s['verdicts']} executive_findings={s['executive_findings']}")
    for t, c in s["by_type"].items():
        print(f"  {t:<15} {c}")
    print("  REJECTED:")
    for r in rejected:
        print(f"   - {r['id']}: {r['reasons'][0][:170]}")
    print("  WARN (risks / hypotheses / recommendations):")
    for f in validated:
        if f["validation"]["verdict"] == "WARN" and f["type"] in ("risk", "hypothesis", "recommendation", "anomaly"):
            print(f"   - {f['id']}: {f['validation']['reasons'][0][:150]}")


if __name__ == "__main__":
    main()
