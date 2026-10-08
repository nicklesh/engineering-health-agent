---
name: run-health-pipeline
description: Run the Engineering Health Intelligence System end to end inside Claude Code - the deterministic agents, then the Claude Code reasoning layer (risk-narrator and engineering-coach-writer subagents), then validation of their narratives. Use when the user asks to run the pipeline, the analysis, or the reasoning layer.
---

# Run the Engineering Health pipeline

Run from the project root. Stop and report at the first step that fails. Never hide a failure.

1. **Deterministic agents 01–08**
   ```bash
   python run.py
   ```
   Add `--generate` to regenerate the synthetic data first.
   - `Pipeline BLOCKED` means the data-validation gate failed. Show the blocking issues, explain them, and stop. Do **not** edit `config/known_exceptions.json` unless the user approves the exception.
   - `Pipeline ERROR` means an agent crashed. Show the error from `output/reports/run_log.json`.

2. **Prepare the reasoning brief**
   ```bash
   python run.py brief
   ```

3. **Run the reasoning layer.** Launch both subagents in parallel with the Agent tool:
   - `risk-narrator`: "Write the risk narratives as instructed in your definition."
   - `engineering-coach-writer`: "Write the recommendation narratives as instructed in your definition."

4. **Validate the narratives**
   ```bash
   python run.py ingest
   ```
   Report the counts. For every REJECTED narrative, quote the reason (new number, causal language, stale, generic). Rejected narratives are dropped and the deterministic wording is used instead. Do not hand-edit narratives to make them pass; re-run the subagent if needed.

5. **Summarise for the user:** pipeline status, data-quality score, risks by severity, verdict counts, rejected findings, and narratives accepted or rejected.
