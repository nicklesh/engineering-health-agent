"""Schema-aware CSV loading shared by the generator tests and the agents.

CSV has no types, so values are coerced using the dataset's JSON Schema. Coercion never
hides a problem: an empty cell becomes None and an unparseable cell is kept as the raw
string, so schema validation downstream reports it instead of it silently disappearing.
"""
import csv

from src.config import load_json, load_settings, project_path

DATASETS = ["services", "weekly_metrics", "deployments", "incidents", "defects"]


def schema_dir():
    return project_path(load_settings()["paths"]["schemas"])


def raw_dir():
    return project_path(load_settings()["paths"]["raw_data"])


def load_schema(dataset):
    return load_json(schema_dir() / f"{dataset}.schema.json")


def coerce(value, json_type):
    if value == "":
        return None
    try:
        if json_type == "integer":
            return int(value)
        if json_type == "number":
            return float(value)
        if json_type == "boolean":
            if value in ("true", "false"):
                return value == "true"
            return value
    except ValueError:
        return value
    return value


def read_dataset(dataset, directory=None):
    """Return (rows, schema). Each row carries its 1-based CSV line number in '_line'."""
    schema = load_schema(dataset)
    props = schema["properties"]
    path = (directory or raw_dir()) / f"{dataset}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Required input missing: {path}")
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for line_no, raw in enumerate(csv.DictReader(f), start=2):
            row = {k: coerce(v, props.get(k, {}).get("type")) for k, v in raw.items()}
            row["_line"] = line_no
            rows.append(row)
    return rows, schema


def without_meta(row):
    return {k: v for k, v in row.items() if not k.startswith("_") and v is not None}
