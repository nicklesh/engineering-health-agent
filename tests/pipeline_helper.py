"""Runs agents 01-08 into a temporary directory so tests never touch data/processed/."""
import tempfile
from pathlib import Path

from src.analysis import (agent02_metrics_analysis, agent03_quality_analysis, agent04_trend_analysis,
                          agent05_anomaly_detection, agent06_risk_analysis, agent07_engineering_coach)
from src.common import envelope
from src.config import load_json
from src.validation import agent01_data_validation, agent08_evidence_validation

SEQUENCE = [agent02_metrics_analysis, agent04_trend_analysis, agent05_anomaly_detection,
            agent03_quality_analysis, agent06_risk_analysis, agent07_engineering_coach, agent08_evidence_validation]

_cache = {}


def run_pipeline(directory=None):
    directory = Path(directory or tempfile.mkdtemp(prefix="ehis-"))
    envelope.set_processed_dir(directory)
    try:
        agent01_data_validation.run()
        for agent in SEQUENCE:
            agent.run()
    finally:
        envelope.set_processed_dir(None)
    return directory


def shared_run():
    """One pipeline run reused by read-only tests."""
    if "dir" not in _cache:
        _cache["dir"] = run_pipeline()
    return _cache["dir"]


def load(directory, agent_key):
    return load_json(Path(directory) / f"{envelope.AGENTS[agent_key]}.json")
