"""The Claude Code reasoning layer: brief -> subagents -> validated narratives.

The deterministic pipeline cannot call Claude itself (no API key by design). Instead:
  1. `build_brief()` writes data/processed/reasoning/brief.json: only findings that survived
     Evidence Validation, their evidence, and the rules the writers must follow.
  2. Claude Code subagents (.claude/agents/risk-narrator.md, engineering-coach-writer.md) read
     the brief and write data/processed/reasoning/narratives_<author>.json.
  3. `ingest()` validates every narrative and writes data/processed/reasoning_layer.json.
     Rejected narratives are dropped and the deterministic wording is used instead.

Narrative checks (the same spirit as Agent 08):
  stale          - written for a different Evidence Validation output than the current one
  known_finding  - refers to a finding that exists and was not rejected
  no_new_numbers - every number appears in that finding's own evidence (allowing rounding)
  no_causal_claim- no un-negated causal language
  specific       - names the team or platform; at most `MAX_WORDS` words
Narratives only change wording. Numbers, targets, priorities and links never come from here.
"""
import json
import re

from src.common.envelope import AGENTS, dump_json, envelope_path, file_sha, processed_dir, read_envelope
from src.config import load_json
from src.validation.agent08_evidence_validation import CAUSAL, unnegated

MAX_WORDS = 90
NUMBER = re.compile(r"\d+(?:\.\d+)?")
TASKS = {
    "risk-narrator": {"types": ["risk"], "output": "narratives_risk-narrator.json"},
    "engineering-coach-writer": {"types": ["recommendation"], "output": "narratives_engineering-coach-writer.json"},
}
RULES = [
    "Write one narrative per finding listed for you, 2-4 sentences, at most 90 words, plain business English.",
    "Use ONLY numbers that appear in that finding's own entry in this brief (you may round them). Never compute new numbers.",
    "Never state or imply a cause. Use 'may', 'is associated with', 'coincides with'. Never use 'because', 'due to', 'caused by', 'drives', 'leads to', 'results in'.",
    "Explanations marked do_not_use were REJECTED by Evidence Validation - do not mention them, not even as a possibility.",
    "Findings with verdict WARN must say plainly what the caveat is.",
    "Name the team or platform. No generic advice.",
    "Do not change priorities, owners, targets or deadlines; you may only explain them.",
]


def reasoning_dir():
    d = processed_dir() / "reasoning"
    d.mkdir(parents=True, exist_ok=True)
    return d


def current_fingerprint():
    return file_sha(envelope_path(AGENTS["08"]))


def build_brief():
    env = read_envelope(AGENTS["08"])
    found = {f["id"]: f for f in env["findings"]}
    kept = [f for f in env["findings"] if f["validation"]["verdict"] != "REJECT"]
    items = []
    for f in kept:
        if f["type"] == "risk":
            items.append({
                "finding_id": f["id"], "type": "risk", "verdict": f["validation"]["verdict"],
                "caveats": f["validation"]["reasons"], "entity": f["entity"],
                "risk": f["risk"], "category": f["category"], "severity": f["severity"],
                "confidence": f["confidence"]["score"], "evidence": f["evidence"],
                "potential_impact": f["potential_impact"], "recommended_follow_up": f["recommended_follow_up"],
                "possible_explanations": [
                    {"id": h, "claim": found[h]["claim"], "verdict": found[h]["validation"]["verdict"],
                     "do_not_use": found[h]["validation"]["verdict"] == "REJECT",
                     "caveat": (found[h]["validation"]["reasons"] or [""])[0]}
                    for h in f.get("possible_explanations", []) if h in found],
            })
        elif f["type"] == "recommendation":
            items.append({
                "finding_id": f["id"], "type": "recommendation", "verdict": f["validation"]["verdict"],
                "caveats": f["validation"]["reasons"], "entity": f["dimension"].get("scope"),
                "priority": f["priority"], "problem": f["problem"], "evidence": f["evidence"],
                "recommended_action": f["recommended_action"], "expected_outcome": f["expected_outcome"],
                "owner_type": f["owner_type"], "measurement_of_success": f["measurement_of_success"],
            })
    brief = {
        "evidence_validation_fingerprint": current_fingerprint(),
        "rules": RULES,
        "output_format": {"brief_fingerprint": "<copy evidence_validation_fingerprint>", "author": "<your agent name>",
                          "narratives": [{"finding_id": "<id>", "text": "<narrative>"}]},
        "tasks": {name: {"output": f"data/processed/reasoning/{t['output']}",
                         "finding_ids": [i["finding_id"] for i in items if i["type"] in t["types"]]}
                  for name, t in TASKS.items()},
        "findings": items,
    }
    path = reasoning_dir() / "brief.json"
    dump_json(path, brief)
    return path, brief


# Identifiers that contain digits but are not quantities: priority labels (P1-P3) and
# agent numbers ("Agent 07"). They are removed before numbers are compared.
IDENTIFIERS = re.compile(r"\bP[1-3]\b|\b[Aa]gent \d{2}\b")


def numbers_in(text):
    return [float(x) for x in NUMBER.findall(IDENTIFIERS.sub(" ", text or ""))]


def number_supported(n, source_numbers):
    for s in source_numbers:
        s = abs(s)
        for digits in (0, 1, 2, 3):
            if round(s, digits) == n:
                return True
    return False


def source_text(item):
    """Everything a narrative about this finding may draw numbers from (rejected explanations excluded)."""
    item = dict(item)
    if "possible_explanations" in item:
        item["possible_explanations"] = [h for h in item["possible_explanations"] if not h["do_not_use"]]
    return json.dumps(item, ensure_ascii=False)


def entity_names(item):
    e = item.get("entity") or ""
    name = e.split(":", 1)[-1]
    return [name] + name.split("/")


def check_narrative(n, item, fingerprint_ok):
    checks = []

    def add(name, ok, detail, fail="REJECT"):
        checks.append({"check": name, "result": "PASS" if ok else fail, "detail": detail})

    add("stale", fingerprint_ok, "written for the current evidence" if fingerprint_ok else
        "written for a different Evidence Validation output - re-run the reasoning layer")
    add("known_finding", item is not None, "finding exists and was not rejected" if item else
        f"{n.get('finding_id')} is unknown or was rejected")
    if item is None:
        return checks
    text = n.get("text", "")
    src = numbers_in(source_text(item))
    new = sorted({x for x in numbers_in(text) if not number_supported(x, src)})
    add("no_new_numbers", not new, "all numbers come from the finding's evidence" if not new else f"numbers not in the evidence: {new}")
    hits = unnegated(CAUSAL, text)
    add("no_causal_claim", not hits, "no causal language" if not hits else f"causal language: {sorted(set(hits))}")
    words = len(text.split())
    names = [x for x in entity_names(item) if x]
    add("specific", words <= MAX_WORDS and any(x.lower() in text.lower() for x in names),
        f"{words} words; names the entity" if any(x.lower() in text.lower() for x in names) else f"{words} words; does not name {names[0]}")
    return checks


def ingest():
    brief = load_json(reasoning_dir() / "brief.json")
    items = {i["finding_id"]: i for i in brief["findings"]}
    fp = current_fingerprint()
    results = []
    files = sorted(reasoning_dir().glob("narratives_*.json"))
    for path in files:
        doc = load_json(path)
        fresh = doc.get("brief_fingerprint") == fp and brief["evidence_validation_fingerprint"] == fp
        for n in doc.get("narratives", []):
            checks = check_narrative(n, items.get(n.get("finding_id")), fresh)
            verdict = "REJECT" if any(c["result"] == "REJECT" for c in checks) else "PASS"
            results.append({"finding_id": n.get("finding_id"), "author": doc.get("author", path.stem), "text": n.get("text"),
                            "verdict": verdict, "checks": checks,
                            "reasons": [f"{c['check']}: {c['detail']}" for c in checks if c["result"] != "PASS"]})
    expected = {fid for t in brief["tasks"].values() for fid in t["finding_ids"]}
    accepted = {r["finding_id"] for r in results if r["verdict"] == "PASS"}
    out = {
        "agent": "reasoning_layer",
        "depends_on": [AGENTS["08"]],
        "evidence_validation_fingerprint": fp,
        "status": "PASS" if results and len(accepted) == len(expected) else ("WARN" if results else "NOT_RUN"),
        "summary": {"narratives": len(results), "accepted": len(accepted),
                    "rejected": sum(r["verdict"] == "REJECT" for r in results),
                    "missing": sorted(expected - {r["finding_id"] for r in results})},
        "narratives": results,
    }
    dump_json(processed_dir() / "reasoning_layer.json", out)
    return out
