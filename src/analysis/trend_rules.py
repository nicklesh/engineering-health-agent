"""Trend classification rules (Agent 04). Kept separate from the agent so tests and the
Evidence Validation agent can call the exact documented rule on any series.

Minimum evidence threshold for calling something a TREND (all must hold, see
config/thresholds.json -> trend, and agents/04_trend_analysis_agent.md):
  1. at least `min_points` valid, non-outlier weekly values
  2. Mann-Kendall |tau| >= min_abs_tau and p <= max_p_value, same sign as the change
  3. |recent median - baseline median| >= min_change_pct % of baseline
  4. that change is >= min_effect_sd x the week-to-week noise level
  5. the last `persistence_weeks` values all stay beyond baseline +/- 1 noise unit
  6. the trend window (onset -> last week) is >= min_trend_weeks long
A single-week spike can satisfy none of 5-6, which is why it can never be a trend.
"""
import math
from statistics import median

from src.analysis.dataset import pooled_ratio
from src.common.stats import diff_noise_sd, mann_kendall, robust_sd, sign, theil_sen


def find_outliers(points, cfg, count_metric):
    """Points far from the median of their +/- window neighbours (robust z >= outlier_z)."""
    w = cfg["outlier_window"]
    residuals = []
    for i, (wk, v) in enumerate(points):
        nb = [pv for pw, pv in points if pw != wk and abs(pw - wk) <= w]
        local = median(nb) if nb else v
        residuals.append((wk, v, local, v - local))
    scale = robust_sd([r[3] for r in residuals])
    out = []
    for wk, v, local, res in residuals:
        s = scale
        if count_metric:
            s = max(s, math.sqrt(max(local, 1.0)))
        s = max(s, 1e-9, 0.01 * abs(local))
        z = res / s
        if abs(z) >= cfg["outlier_z"]:
            out.append({"week": wk, "value": v, "local_median": round(local, 3), "z": round(z, 2)})
    return out


def analysed_values(values, metric, entry, cfg):
    """Rates built from small weekly samples (e.g. 18 deployments) are too noisy week by week,
    so event_ratio metrics are judged on a pooled rolling window:
    sum(numerators) / sum(denominators) over the last `ratio_pooling_weeks` weeks."""
    if metric["derive"]["kind"] == "event_ratio" and entry and "numerator" in entry:
        return [pooled_ratio(entry, w, cfg["ratio_pooling_weeks"]) for w in range(1, len(values) + 1)], \
            f"pooled_{cfg['ratio_pooling_weeks']}_week_rate"
    return values, "weekly"


def two_proportion_test(x0, n0, x1, n1):
    """z-test for a difference between two proportions. Returns (z, two-sided p)."""
    if n0 == 0 or n1 == 0:
        return 0.0, 1.0
    p = (x0 + x1) / (n0 + n1)
    se = math.sqrt(p * (1 - p) * (1 / n0 + 1 / n1))
    if se == 0:
        return 0.0, 1.0
    z = (x1 / n1 - x0 / n0) / se
    return round(z, 3), round(math.erfc(abs(z) / math.sqrt(2)), 6)


def classify_ratio(entry, metric, cfg):
    """Rates (e.g. change-failure rate) are compared on pooled counts, where every event counts
    once: baseline weeks vs recent weeks with a two-proportion z-test. The rolling pooled rate
    is only used to locate the onset and check persistence - NOT for significance, because
    overlapping windows are autocorrelated and would make any test overconfident."""
    num, den = entry["numerator"], entry["denominator"]
    n_weeks = len(num)
    polarity = metric["polarity"]
    b_hi, r_lo = cfg["baseline_weeks"], n_weeks - cfg["recent_weeks"] + 1
    x0, n0 = sum(num[:b_hi]), sum(den[:b_hi])
    x1, n1 = sum(num[r_lo - 1:]), sum(den[r_lo - 1:])
    result = {"metric": metric["id"], "polarity": polarity, "basis": f"pooled_counts_two_proportion",
              "valid_points": sum(1 for d in den if d), "expected_points": n_weeks,
              "pooled_counts": {"baseline": [x0, n0], "recent": [x1, n1]}}
    if n0 < 20 or n1 < 12:
        return {**result, "classification": "INSUFFICIENT_DATA", "reason": f"too few events (baseline {n0}, recent {n1})"}

    p0, p1 = 100 * x0 / n0, 100 * x1 / n1
    z, p_value = two_proportion_test(x0, n0, x1, n1)
    change = p1 - p0
    change_pct = round(change / p0 * 100, 2) if p0 else None
    d = sign(change)
    se = math.sqrt(max(p0, 0.5) * max(100 - p0, 0.5) / n0 + max(p1, 0.5) * max(100 - p1, 0.5) / n1)
    effect = change / se if se else 0.0

    window = cfg["ratio_pooling_weeks"]
    rolling = [(w, pooled_ratio(entry, w, window)) for w in range(window, n_weeks + 1)]
    rolling = [(w, v) for w, v in rolling if v is not None]

    def window_sd(w):
        n = sum(den[max(0, w - window):w])
        return 100 * math.sqrt(max(p0 / 100, 0.005) * (1 - min(p0 / 100, 0.995)) / max(n, 1))

    beyond = {w: d * (v - p0) > window_sd(w) for w, v in rolling}
    onset = None
    for w, _ in rolling:
        later = [beyond[x] for x, _ in rolling if x >= w]
        if beyond[w] and sum(later) / len(later) >= cfg["onset_share"]:
            onset = max(1, w - window + 1)  # first week inside the first elevated window
            break
    win_weeks = (n_weeks - onset + 1) if onset else 0
    persistence = bool(rolling) and all(beyond[w] for w, _ in rolling[-cfg["persistence_weeks"]:])
    seq = [v for w, v in rolling if onset and w >= onset]
    diffs = [b - a for a, b in zip(seq, seq[1:])]
    consistency = (sum(1.0 if sign(x) == d else 0.5 if x == 0 else 0.0 for x in diffs) / len(diffs)) if diffs else 0.0

    checks = {
        "significant": p_value <= cfg["max_p_value"],
        # Rates are judged in percentage points; a relative % would treat complements
        # (success 92->100 = +9%, failure 8->0 = -100%) inconsistently.
        "magnitude_pct": abs(change) >= cfg["min_change_pp"],
        "magnitude_vs_noise": abs(effect) >= cfg["min_effect_sd"],
        "persistent": persistence,
        "long_enough": win_weeks >= cfg["min_trend_weeks"],
    }
    is_trend = all(checks.values())
    if is_trend:
        good = (d > 0) == (polarity == "higher_is_better")
        classification = "IMPROVING" if good else "DETERIORATING"
    else:
        classification = "STABLE"
    return {
        **result,
        "classification": classification, "trend_test_passed": is_trend,
        "movement": "RISING" if d > 0 else ("FALLING" if d < 0 else "FLAT"),
        "checks": checks,
        "emerging": (not is_trend and checks["significant"] and checks["persistent"] and not checks["long_enough"]),
        "baseline": round(p0, 3), "baseline_weeks": [1, b_hi],
        "recent": round(p1, 3), "recent_weeks": [r_lo, n_weeks],
        "change": round(change, 3), "change_pct": change_pct,
        "noise_sd": round(se, 4), "effect_sd": round(effect, 2),
        "kendall_tau": None, "p_value": p_value, "z": z,
        "slope_per_week": None,
        "onset_week": onset, "trend_window": [onset, n_weeks] if onset else None, "window_weeks": win_weeks,
        "consistency": round(consistency, 3),
        "robust_cv": None, "low_volume": False, "outliers": [], "latest_week_outlier": None,
        "rolling_rate": {str(w): v for w, v in rolling},
    }


def classify_series(values, metric, cfg, entry=None):
    """values: list indexed by week-1 (None = missing). `entry` is the metric-series entry
    (rates need its numerator/denominator counts). Returns a dict describing the series."""
    if metric["derive"]["kind"] == "event_ratio" and entry and "numerator" in entry:
        return classify_ratio(entry, metric, cfg)
    n_weeks = len(values)
    values, basis = analysed_values(values, metric, entry, cfg)
    pooled = basis != "weekly"
    points = [(i + 1, v) for i, v in enumerate(values) if v is not None]
    count_metric = bool(metric.get("count_metric"))
    polarity = metric["polarity"]
    result = {"metric": metric["id"], "polarity": polarity, "valid_points": len(points), "expected_points": n_weeks,
              "basis": basis}

    if len(points) < cfg["min_points"]:
        return {**result, "classification": "INSUFFICIENT_DATA", "reason": f"only {len(points)} valid points (< {cfg['min_points']})"}

    # Pooled series are smoothed on purpose, so single-week outliers are judged by Agent 05 on
    # the raw weekly values instead.
    outliers = [] if pooled else find_outliers(points, cfg, count_metric)
    # An outlier in the latest week cannot be called one-time yet: nobody knows whether it
    # persists. It is excluded from the trend fit and flagged for watching.
    latest = [o for o in outliers if o["week"] == points[-1][0]]
    outliers = [o for o in outliers if o["week"] != points[-1][0]]
    out_weeks = {o["week"] for o in outliers} | {o["week"] for o in latest}
    clean = [(w, v) for w, v in points if w not in out_weeks]
    vals = [v for _, v in clean]
    base_pts = [v for w, v in clean if w <= cfg["baseline_weeks"]]
    recent_pts = [v for w, v in clean if w > n_weeks - cfg["recent_weeks"]]
    if len(clean) < cfg["min_points"] or len(base_pts) < 3 or len(recent_pts) < 2:
        return {**result, "classification": "INSUFFICIENT_DATA", "outliers": outliers,
                "reason": "not enough clean baseline/recent points"}

    tau, p = mann_kendall(vals)
    baseline, recent = median(base_pts), median(recent_pts)
    noise = diff_noise_sd(vals)
    if count_metric:
        noise = max(noise, math.sqrt(max(baseline, 1.0)))
    noise = max(noise, 1e-9, 0.01 * abs(baseline))
    change = recent - baseline
    change_pct = round(change / abs(baseline) * 100, 2) if baseline else None
    effect = change / noise
    d = sign(change)

    beyond = {w: d * (v - baseline) > noise for w, v in clean}
    onset = None
    for w, _ in clean:
        later = [beyond[x] for x, _ in clean if x >= w]
        if beyond[w] and sum(later) / len(later) >= cfg["onset_share"]:
            onset = w
            break
    last_week = clean[-1][0]
    window = (last_week - onset + 1) if onset else 0
    persistence = all(beyond[w] for w, _ in clean[-cfg["persistence_weeks"]:])

    checks = {
        "monotonic": abs(tau) >= cfg["min_abs_tau"] and p <= cfg["max_p_value"] and sign(tau) == d,
        # Percent-unit metrics may also qualify on percentage points (92% -> 100% is +8 pp but
        # only +8.7% relative, yet clearly material for a success rate near its ceiling).
        "magnitude_pct": (change_pct is None or abs(change_pct) >= cfg["min_change_pct"]
                          or (metric["unit"] == "%" and abs(change) >= cfg["min_change_pp"])),
        "magnitude_vs_noise": abs(effect) >= cfg["min_effect_sd"],
        "persistent": persistence,
        "long_enough": window >= cfg["min_trend_weeks"],
    }
    is_trend = all(checks.values())
    movement = "RISING" if d > 0 else ("FALLING" if d < 0 else "FLAT")

    window_pts = [v for w, v in clean if onset and w >= onset]
    diffs = [b - a for a, b in zip(window_pts, window_pts[1:])]
    consistency = (sum(1.0 if sign(x) == d else 0.5 if x == 0 else 0.0 for x in diffs) / len(diffs)) if diffs else 0.0

    med = median(vals)
    robust_cv = (robust_sd(vals) / abs(med)) if med else float("inf")
    low_volume = count_metric and med < cfg["low_volume_median"]

    if polarity == "neutral":
        classification = "NOT_CLASSIFIED"
    elif is_trend:
        good = (d > 0) == (polarity == "higher_is_better")
        classification = "IMPROVING" if good else "DETERIORATING"
    elif 0 < len(outliers) <= cfg["max_outliers_for_anomaly"]:
        classification = "ONE_TIME_ANOMALY"
    elif len(outliers) > cfg["max_outliers_for_anomaly"]:
        classification = "VOLATILE"
    elif not low_volume and robust_cv > cfg["volatile_robust_cv"]:
        classification = "VOLATILE"
    else:
        classification = "STABLE"

    # A recent, persistent shift that is real but too young to call a trend yet.
    emerging = (not is_trend and checks["persistent"] and checks["magnitude_vs_noise"]
                and checks["magnitude_pct"] and not checks["long_enough"])
    return {
        **result,
        "classification": classification,
        "trend_test_passed": is_trend,
        "movement": movement,
        "checks": checks,
        "emerging": emerging,
        "baseline": round(baseline, 3), "baseline_weeks": [1, cfg["baseline_weeks"]],
        "recent": round(recent, 3), "recent_weeks": [n_weeks - cfg["recent_weeks"] + 1, n_weeks],
        "change": round(change, 3), "change_pct": change_pct,
        "noise_sd": round(noise, 4), "effect_sd": round(effect, 2),
        "kendall_tau": tau, "p_value": p,
        "slope_per_week": round(theil_sen([w for w, _ in clean], vals), 4),
        "onset_week": onset, "trend_window": [onset, last_week] if onset else None, "window_weeks": window,
        "consistency": round(consistency, 3),
        "robust_cv": round(robust_cv, 3) if robust_cv != float("inf") else None,
        "low_volume": low_volume,
        "outliers": outliers,
        "latest_week_outlier": latest[0] if latest else None,
    }
