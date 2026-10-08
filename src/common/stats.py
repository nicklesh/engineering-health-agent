"""Small, dependency-free statistics used by the analysis and validation agents.

Everything here is deterministic and readable on purpose: an engineer should be able to
check any number the system reports with a calculator and this file.
"""
import math
from statistics import median


def pct_change(current, previous):
    """Percentage change; None when undefined (missing value or zero baseline)."""
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def mad(values):
    m = median(values)
    return median(abs(v - m) for v in values)


def robust_sd(values):
    """1.4826 * MAD: a standard-deviation estimate that ignores outliers."""
    if len(values) < 2:
        return 0.0
    return 1.4826 * mad(values)


def diff_noise_sd(values):
    """Week-to-week noise level that is insensitive to a steady trend:
    robust sd of first differences / sqrt(2)."""
    diffs = [b - a for a, b in zip(values, values[1:])]
    if len(diffs) < 2:
        return 0.0
    return robust_sd(diffs) / math.sqrt(2)


def theil_sen(xs, ys):
    """Median of pairwise slopes - a robust linear trend estimate (units per week)."""
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i])
              for i in range(len(xs)) for j in range(i + 1, len(xs)) if xs[j] != xs[i]]
    return median(slopes) if slopes else 0.0


def mann_kendall(values):
    """Mann-Kendall monotonic trend test.
    Returns (tau, p_value). tau in [-1, 1]; p from the normal approximation (two-sided)."""
    n = len(values)
    if n < 3:
        return 0.0, 1.0
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            s += (values[j] > values[i]) - (values[j] < values[i])
    tau = s / (n * (n - 1) / 2)
    var_s = n * (n - 1) * (2 * n + 5) / 18
    if s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return round(tau, 4), round(p, 6)


def pearson(xs, ys):
    """Pearson correlation; None when either series is constant or too short."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return round(sxy / math.sqrt(sxx * syy), 4)


def partial_correlation(r_xy, r_xz, r_yz):
    """Correlation of x and y after removing the linear effect of z."""
    if None in (r_xy, r_xz, r_yz):
        return None
    denom = math.sqrt(max(1e-12, (1 - r_xz ** 2) * (1 - r_yz ** 2)))
    return round((r_xy - r_xz * r_yz) / denom, 4)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def sign(x):
    return (x > 0) - (x < 0)
