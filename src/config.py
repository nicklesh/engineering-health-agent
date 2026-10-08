"""Project paths and config loading. Every module resolves paths through here so the
pipeline behaves the same no matter which directory it is launched from."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_settings():
    return load_json(CONFIG_DIR / "settings.json")


def load_org():
    return load_json(CONFIG_DIR / "org.json")


def project_path(relative):
    """Resolve a path from settings.json (relative to the project root)."""
    return ROOT / relative
