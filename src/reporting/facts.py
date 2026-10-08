"""The fact sheet behind the executive deck and report.

Every number that appears in an executive output is registered here once, with the source it
came from. Slides and the report only ever print `fact.text`, so:
  * a number cannot be typed in by hand without the consistency check noticing, and
  * every number can be traced back (key -> source -> validated finding / series).
"""
import re
from dataclasses import dataclass, field

NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class Fact:
    key: str
    value: object
    text: str
    source: str


@dataclass
class FactSheet:
    facts: dict = field(default_factory=dict)

    def add(self, key, value, text, source):
        if key in self.facts and self.facts[key].text != text:
            raise ValueError(f"Fact {key} registered twice with different text")
        self.facts[key] = Fact(key, value, text, source)
        return text

    def __getitem__(self, key):
        return self.facts[key].text

    def allowed_numbers(self):
        out = set()
        for f in self.facts.values():
            out.update(float(x) for x in NUMBER.findall(f.text))
        return out

    def manifest(self):
        return [{"key": f.key, "value": f.value, "text": f.text, "source": f.source} for f in self.facts.values()]


def num(v, digits=1):
    """Plain number text: 4.5, 12, 27.1."""
    v = round(v, digits)
    return f"{v:g}" if digits else f"{int(round(v))}"


def val(v, unit, digits=1):
    """Number with unit, matching the dashboard formatter."""
    if v is None:
        return "n/a"
    s = num(v, digits)
    if unit == "%":
        return s + "%"
    if unit in ("count", "items", "people"):
        return s
    return s + {"days": " d", "hours": " h", "minutes": " min", "LOC": " LOC"}.get(unit, " " + unit)


def change(base, recent, unit, pct=None):
    if unit == "%":
        return f"{recent - base:+.1f} pp"
    if pct is None and base:
        pct = (recent - base) / abs(base) * 100
    return f"{pct:+.0f}%"
