"""The agent-to-agent contract (CLAUDE.md section 4).

Agents only talk through JSON envelopes in data/processed/. This module is the single
place that reads and writes them, so every agent gets the same rules for free:
  * dependencies that are missing or FAILED stop the agent with a clear message
  * output is deterministic (stable key order, no timestamps), so re-runs are idempotent
  * the input fingerprint records exactly which inputs produced the output
"""
import hashlib
import json

from src.config import load_json, load_settings, project_path

SCHEMA_VERSION = "1.0"

AGENTS = {
    "01": "01_data_validation",
    "02": "02_metrics_analysis",
    "03": "03_quality_analysis",
    "04": "04_trend_analysis",
    "05": "05_anomaly_detection",
    "06": "06_risk_analysis",
    "07": "07_engineering_coach",
    "08": "08_evidence_validation",
}


class MissingDependencyError(RuntimeError):
    """A required input file or upstream agent output does not exist."""


class DependencyFailedError(RuntimeError):
    """An upstream agent finished with status FAIL, so this agent must not run."""


_override_dir = None


def set_processed_dir(path):
    """Redirect all envelope reads/writes (used by tests so they never touch real outputs)."""
    global _override_dir
    _override_dir = path


def processed_dir():
    path = _override_dir or project_path(load_settings()["paths"]["processed_data"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def envelope_path(agent):
    return processed_dir() / f"{agent}.json"


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(paths):
    """sha256 over the sorted (name, content-hash) pairs of every input."""
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: x.name):
        h.update(p.name.encode())
        h.update(file_sha(p).encode())
    return h.hexdigest()


def dump_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def read_envelope(agent, allow_fail=False):
    path = envelope_path(agent)
    if not path.exists():
        raise MissingDependencyError(
            f"Required input missing: {path.name}. Run agent {agent} first.")
    env = load_json(path)
    if env.get("status") == "FAIL" and not allow_fail:
        raise DependencyFailedError(
            f"Upstream agent {agent} finished with status FAIL; refusing to run on its output. "
            f"See {path.name} for the reasons.")
    return env


def write_envelope(agent, status, depends_on, input_paths, summary, findings, errors=None, **extra):
    env = {
        "agent": agent,
        "schema_version": SCHEMA_VERSION,
        "input_fingerprint": fingerprint(input_paths),
        "status": status,
        "depends_on": depends_on,
        "summary": summary,
        "findings": findings,
        "errors": errors or [],
    }
    env.update(extra)
    path = envelope_path(agent)
    dump_json(path, env)
    return path


def dependency_paths(*agents):
    return [envelope_path(a) for a in agents]
