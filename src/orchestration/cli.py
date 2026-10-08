"""Command line entry point. Usually called through run.py at the project root:

    python run.py                 # run agents 01-08 (orchestrated)
    python run.py --generate      # regenerate synthetic data first
    python run.py brief           # write the brief for the Claude Code reasoning layer
    python run.py ingest          # validate the narratives the subagents wrote
"""
import argparse
import sys

from src.data import generate_synthetic_data, schema_docs
from src.orchestration import reasoning
from src.orchestration.orchestrator import run_pipeline


def main(argv=None):
    p = argparse.ArgumentParser(description="Engineering Health Intelligence System")
    p.add_argument("command", nargs="?", default="run", choices=["run", "brief", "ingest"])
    p.add_argument("--generate", action="store_true", help="regenerate the synthetic dataset first")
    args = p.parse_args(argv)

    if args.command == "run":
        if args.generate:
            generate_synthetic_data.main()
            schema_docs.main()
        result = run_pipeline()
        return 0 if result["status"] in ("PASS", "WARN") else 1

    if args.command == "brief":
        path, brief = reasoning.build_brief()
        print(f"Wrote {path}")
        for name, task in brief["tasks"].items():
            print(f"  {name}: {len(task['finding_ids'])} findings -> {task['output']}")
        print("Next: ask Claude Code to run the reasoning layer (see .claude/skills/run-health-pipeline), then `python run.py ingest`.")
        return 0

    out = reasoning.ingest()
    s = out["summary"]
    print(f"[reasoning_layer] status={out['status']} narratives={s['narratives']} accepted={s['accepted']} "
          f"rejected={s['rejected']} missing={len(s['missing'])}")
    for r in out["narratives"]:
        if r["verdict"] == "REJECT":
            print(f"  REJECT {r['finding_id']} ({r['author']}): {r['reasons'][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
