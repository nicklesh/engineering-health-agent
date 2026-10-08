"""One way to print numbers in human-readable text, so every agent (and later the dashboard
and deck) says "5.4% -> 27.1% (+21.6 pp)" rather than "5.435 -> 27.059 (+398%)".

Rates are described in percentage points: a relative % change of a rate exaggerates
(1% -> 2% is "+100%" but only one point)."""

UNITLESS = ("count", "items", "people")


def value(v, unit, digits=1):
    if v is None:
        return "n/a"
    v = round(v, digits)
    if unit == "%":
        return f"{v:g}%"
    return f"{v:g}" if unit in UNITLESS else f"{v:g} {unit}"


def change(baseline, recent, unit, change_pct=None):
    """'+21.6 pp' for rates, '+39%' otherwise (falls back to the absolute change)."""
    if baseline is None or recent is None:
        return "n/a"
    delta = recent - baseline
    if unit == "%":
        return f"{delta:+.1f} pp"
    if change_pct is None and baseline:
        change_pct = delta / abs(baseline) * 100
    if change_pct is None:
        return f"{delta:+g}{'' if unit in UNITLESS else ' ' + unit}"
    return f"{change_pct:+.0f}%"


def arrow(baseline, recent, unit):
    return f"{value(baseline, unit)} -> {value(recent, unit)}"
