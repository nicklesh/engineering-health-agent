# Agentic Engineering Health Intelligence System

A multi-agent pipeline that turns raw (synthetic) engineering metrics into validated,
evidence-backed insights for engineering leadership. It produces an interactive dashboard,
an executive deck, an executive report and architecture documentation.

> **Status: Phase 1 of 8 complete.** The foundation, schemas, synthetic data and data tests
> are built and running. The agents, dashboard and deck are not built yet. See
> [CLAUDE.md §9](CLAUDE.md#9-current-status).

## Why it exists

Dashboards show numbers. Leaders need to know which numbers matter, whether a change is a
trend or a blip, how sure we are, and what to do about it. This project shows how to build
that reasoning as a chain of small, inspectable agents rather than one giant prompt. Each
agent has a contract, explicit evidence and a validator that is allowed to say "no".

It is also a learning exercise in the *See → Try → Fail → Ask AI → Fix → Repeat* loop, so
failures are recorded below instead of hidden.

All data is synthetic. No real company, system or person is represented.

## Architecture

See [CLAUDE.md §2](CLAUDE.md#2-architecture) for the full picture and agent table. In short:

```
synthetic data → 01 validation (gate) → 02 metrics, 03 quality → 04 trends, 05 anomalies
→ 06 risk → 07 coach → 08 evidence validation → 09 dashboard / 10 report + deck
```

Calculations are deterministic Python. AI reasoning (interpretation and narrative) is
supplied by Claude Code subagents when you run the pipeline inside Claude Code, using your
existing Claude login, so no API key is needed. It never affects the numbers, and its
output is validated like everything else.

## Agents

Specifications will live in [`agents/`](agents/) (Phase 2). Responsibilities are listed in
[CLAUDE.md](CLAUDE.md#agents).

## Data model

Five datasets in `data/raw/`, each described by a JSON Schema in `data/schemas/`. The
full field-by-field reference is in [data/schemas/DATA_DICTIONARY.md](data/schemas/DATA_DICTIONARY.md).

| Dataset | Grain | Rows | Purpose |
|---|---|---|---|
| `services.csv` | service | 10 | Reference: which team owns which service on which platform |
| `weekly_metrics.csv` | week × team × platform | 160 | Delivery, code-health, testing, CI and ops aggregates |
| `deployments.csv` | deployment | ~1.5k | Source records for deployment success, failure and rollbacks |
| `incidents.csv` | incident | ~100 | Source records for incidents, severity and MTTR |
| `defects.csv` | defect | ~580 | Source records for defects, severity, escapes and regressions |

The dataset covers 5 fictional teams (Atlas, Nova, Orion, Phoenix, Titan), 4 platforms
(Web, Mobile, Services, Data) and 16 weeks (2026-06-15 → 2026-10-04).

### Planted signals

The generator deliberately plants patterns the agents must find, or must *not* misread:

| # | Signal | Where |
|---|---|---|
| 1 | Gradually deteriorating team: cycle time ↑, PR review time ↑, defects ↑, coverage ↓ | one team, second half of the period |
| 2 | Deployment instability: failed deployments ↑, rollbacks ↑, incidents ↑ | one platform |
| 3 | Sustained improvement: coverage ↑, cycle time ↓, escapes ↓, deploy success ↑ | one team |
| 4 | One-week spike that must **not** be called a trend | one team/platform, one week |
| 5 | Two metrics that correlate strongly but are not causally linked (hidden common driver) | one team |
| 6 | Four injected data-quality defects: duplicate, missing value, invalid value, inconsistent total | various |

The exact answer key is in `tests/ground_truth/planted_signals.json`. Only tests may read
it. The agents have to find the signals on their own.

## How to run

Requirements: Python 3.12+.

```bash
pip install -r requirements.txt
```

### Regenerate synthetic data

```bash
python -m src.data.generate_synthetic_data
```

The output is deterministic: the same `config/settings.json` always produces byte-identical
files (hashes are recorded in `data/raw/MANIFEST.json`). Change `seed` to get a different but
equally structured dataset.

### Regenerate the data dictionary

```bash
python -m src.data.schema_docs
```

### Run analysis / generate dashboard / generate PowerPoint / regenerate diagrams

Not built yet (Phases 2–7).

## Testing

```bash
python -m unittest discover -s tests -t . -v
```

Phase 1 tests check that:
- generation is deterministic and the raw files match the manifest
- every row conforms to its schema **except** the injected issues, and the schema check actually catches them (so the test cannot pass vacuously)
- weekly deployment totals reconcile with deployment events, apart from the injected mismatches
- each planted signal is visible in the raw data

## Limitations

- The data is synthetic and simpler than reality: one service per team/platform, no seasonality, no holidays, independent noise.
- Weekly aggregates such as cycle time are generated directly, not derived from work-item records, so they can only be traced to the weekly row, not to individual items.
- 16 weeks is a short history for trend statistics. Thresholds are tuned for it and documented in the agent specs.

## Future production architecture

To be written in Phase 7. Expected direction: replace the generator with connectors to
delivery, CI, incident and defect systems; keep the same schemas and agent contracts; run the
pipeline on a schedule; store envelopes in a database instead of JSON files.

## Development log

Meaningful failures and how they were fixed.

| # | Phase | What failed | Why | Fix |
|---|---|---|---|---|
| 1 | 1 | The Data-platform incident trend (signal 2) was too weak: 7 incidents in week 15, then 0 in week 16, the "current" week. | The planted rate increase was small relative to Poisson noise. | Raised the planted incident and deployment-failure rates. |
| 2 | 1 | After the fix, week 16 still showed 0 Data incidents (about a 1-in-1,000 chance at the new rate). | Deployments, incidents, defects and weekly metrics shared **one random stream per row**. Changing the deployment logic shifted every later draw, so signals were coupled by accident. | Gave each record type its own seeded stream. Signals are now independent, and tuning one cannot silently change another. |

## What I Learned

_Fill this in after experimenting with the system._

- What surprised me about building agents with contracts:
- A failure I caused on purpose, and what the system did:
- Where deterministic code beat LLM reasoning (and vice versa):
- What I would change about the agent boundaries:
- One thing I would do differently next time:
