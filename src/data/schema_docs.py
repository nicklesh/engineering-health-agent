"""Render data/schemas/DATA_DICTIONARY.md from the JSON Schemas.

The JSON Schemas are the single source of truth; this file only presents them for humans,
so the documentation can never drift from what the validator enforces.

Run:  python -m src.data.schema_docs
"""
from src.data.loader import DATASETS, load_schema, schema_dir


def allowed(spec):
    if "enum" in spec:
        return ", ".join(str(v) for v in spec["enum"])
    parts = []
    if "minimum" in spec:
        parts.append(f">= {spec['minimum']}")
    if "maximum" in spec:
        parts.append(f"<= {spec['maximum']}")
    if "pattern" in spec:
        parts.append(f"`{spec['pattern']}`")
    if spec.get("format") == "date":
        parts.append("YYYY-MM-DD")
    if spec.get("type") == "boolean":
        parts.append("true / false")
    return "; ".join(parts) or "any"


def render():
    out = ["# Data Dictionary", "",
           "_Generated from `data/schemas/*.schema.json` by `python -m src.data.schema_docs`. Do not edit by hand._", ""]
    for name in DATASETS:
        s = load_schema(name)
        required = set(s.get("required", []))
        out += [f"## {name}", "", s["description"], "",
                f"- File: `{s['x-file']}`",
                f"- Grain: one row per {', '.join(s['x-grain'])}",
                f"- Primary key: `{s['x-primary-key']}`", "",
                "| Field | Type | Unit | Required | Allowed values | Meaning |",
                "|---|---|---|---|---|---|"]
        for field, spec in s["properties"].items():
            out.append(f"| `{field}` | {spec['type']} | {spec.get('x-unit', '')} | "
                       f"{'yes' if field in required else 'no'} | {allowed(spec)} | {spec['description']} |")
        out += ["", "**Validation rules (beyond per-field checks):**", "",
                "| Rule | Severity | Rule |", "|---|---|---|"]
        for rule in s.get("x-validation-rules", []):
            out.append(f"| {rule['id']} | {rule['severity']} | {rule['rule']} |")
        out.append("")
    return "\n".join(out)


def main():
    path = schema_dir() / "DATA_DICTIONARY.md"
    path.write_text(render(), encoding="utf-8", newline="\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
