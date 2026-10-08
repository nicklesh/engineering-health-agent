# Master Prompt: Build an Agentic Engineering Health Intelligence System

## ROLE

You are a senior AI systems architect, agentic workflow engineer, data engineer, frontend engineer, technical writer, and executive communication designer.

Your task is to build a complete, runnable **Agentic Engineering Health Intelligence System** from scratch.

This is an educational/personal engineering exercise. **Do not use, request, infer, or depend on any proprietary company data, internal systems, credentials, APIs, Jira projects, GitHub repositories, customer information, internal terminology, or confidential architecture.**

Everything must use **synthetic data and generic engineering concepts.**

The final system should demonstrate how a multi-agent system can transform raw engineering metrics into:

1. Validated engineering insights
2. An interactive executive dashboard
3. An executive PowerPoint presentation
4. A system architecture/design document
5. A runtime sequence diagram

The system should be designed as though it could eventually consume real engineering data, but it must operate entirely on synthetic/local data for this exercise.

---

# 1. PRIMARY OBJECTIVE

Build a multi-agent workflow that answers:

> "What is the current health of our engineering organization, what is changing, what risks are emerging, why might they be happening, and what actions should leadership consider?"

The system must analyze synthetic engineering data across multiple weeks and dimensions.

It must identify:

* Current engineering health
* Week-over-week changes
* Multi-week trends
* Positive improvements
* Deteriorating metrics
* Quality risks
* Operational risks
* Delivery risks
* Anomalies
* Potential correlations
* Areas requiring leadership attention
* Recommended actions
* Confidence/evidence supporting every significant conclusion

The system must NOT simply summarize the data.

It must reason over the data and produce evidence-backed conclusions.

---

# 2. IMPORTANT DESIGN PRINCIPLE

Do not build one giant AI prompt.

Build a genuine multi-agent workflow where each agent has:

* A clearly defined responsibility
* Explicit inputs
* Explicit outputs
* A defined contract/schema
* Validation expectations
* Failure handling
* Dependencies
* Appropriate use of deterministic calculations vs LLM reasoning

Use deterministic code for calculations whenever practical.

Use AI agents for:

* Interpretation
* Pattern recognition
* Hypothesis generation
* Risk reasoning
* Recommendations
* Narrative generation
* Validation

Do NOT ask an LLM to calculate basic percentages when code can calculate them reliably.

---

# 3. PROJECT STRUCTURE

Create the following structure:

```text
engineering-health-agent/
│
├── CLAUDE.md
│
├── README.md
│
├── input/
│   └── master-prompt.md
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── schemas/
│
├── agents/
│   ├── 01_data_validation_agent.md
│   ├── 02_metrics_analysis_agent.md
│   ├── 03_quality_analysis_agent.md
│   ├── 04_trend_analysis_agent.md
│   ├── 05_anomaly_detection_agent.md
│   ├── 06_risk_analysis_agent.md
│   ├── 07_engineering_coach_agent.md
│   ├── 08_evidence_validation_agent.md
│   ├── 09_dashboard_generation_agent.md
│   └── 10_executive_report_agent.md
│
├── src/
│   ├── data/
│   ├── analysis/
│   ├── orchestration/
│   ├── validation/
│   └── reporting/
│
├── dashboard/
│   ├── index.html
│   ├── assets/
│   ├── css/
│   └── js/
│
├── output/
│   ├── presentation/
│   ├── design/
│   ├── reports/
│   └── diagrams/
│
├── tests/
│
└── config/
```

Adapt the implementation language/framework as appropriate, but keep the project simple enough to run locally.

Do not introduce unnecessary infrastructure.

---

# 4. CLAUDE.md

Create a comprehensive `CLAUDE.md`.

It must explain:

## Project purpose

What this system does and why.

## Architecture

Explain every agent and its responsibility.

## Operating principles

Include:

* Evidence before conclusions
* Deterministic calculations where possible
* No unsupported claims
* Explicit confidence
* Traceability
* Idempotency
* Reproducibility
* Separation of data, analysis, presentation, and orchestration
* Human-readable artifacts
* Fail loudly when required inputs are missing
* Never fabricate data
* Never silently change source data

## Agent communication

Define the contract between agents.

## Quality standards

Define what constitutes a successful run.

## Development workflow

Use:

```text
Inspect
→ Design
→ Implement
→ Run
→ Validate
→ Identify failure
→ Fix
→ Rerun
→ Package
```

Do not declare success simply because files exist.

---

# 5. SYNTHETIC DATA GENERATION

Create realistic synthetic engineering data.

Generate at least **16 weeks** of historical data.

Use multiple fictional teams and platforms.

Example:

```text
Teams:
- Atlas
- Nova
- Orion
- Phoenix
- Titan

Platforms:
- Web
- Mobile
- Services
- Data
```

These names are examples. You may choose better fictional names.

Generate enough data to support meaningful analysis.

Include dimensions such as:

### Delivery

* Deployments
* Successful deployments
* Failed deployments
* Rollbacks
* Lead/cycle time
* Throughput

### Quality

* Defects
* Severity
* Escaped defects
* Regression defects
* Test coverage
* Automated test percentage

### Code/change health

* PR count
* PR review time
* PR size
* Change failure rate
* Rework rate

### Operations

* Incidents
* Incident severity
* MTTR
* On-call events
* Availability/reliability indicators

### Engineering efficiency

* Build time
* CI failure rate
* Queue time
* Review latency

### Organizational dimensions

* Team
* Platform
* Week
* Service/category

---

# 6. PLANTED SIGNALS

The synthetic dataset must intentionally contain meaningful patterns.

Do NOT generate completely random data.

Plant at least:

### Signal 1 — Deteriorating team

One team should show:

* Increasing cycle time
* Increasing PR review time
* Increasing defects
* Declining test coverage

The trend should develop gradually across several weeks.

### Signal 2 — Deployment instability

One platform should experience:

* Increasing failed deployments
* Increasing rollback rate
* Increasing incidents

### Signal 3 — Positive improvement

Another team should show:

* Improved test coverage
* Lower cycle time
* Lower defect escape rate
* Better deployment success

### Signal 4 — Temporary anomaly

Create a one-week spike that should NOT be interpreted as a long-term trend.

### Signal 5 — Misleading correlation

Create two metrics that appear correlated but should NOT automatically be interpreted as causal.

The system must distinguish:

> Correlation ≠ causation.

### Signal 6 — Data-quality problem

Introduce a controlled data-quality issue that the validation agent should detect.

Examples:

* Missing value
* Invalid value
* Duplicate record
* Inconsistent total

---

# 7. DATA SCHEMA

Create explicit schemas for every dataset.

Document:

* Field name
* Type
* Meaning
* Allowed values
* Units
* Required/optional
* Validation rules

Create machine-readable schemas where appropriate.

---

# 8. AGENT SYSTEM

Create the following agents.

Each agent must have its own markdown instruction file.

Each agent filename MUST contain:

```text
<sequence>_<descriptive_name>_agent.md
```

Example:

```text
01_data_validation_agent.md
```

Every agent specification must contain:

```text
Purpose
Responsibilities
Inputs
Outputs
Input schema
Output schema
Decision rules
Failure conditions
Validation rules
Dependencies
Example input
Example output
```

---

# 9. AGENT 01 — DATA VALIDATION

Purpose:

Ensure the dataset is usable before any analytical reasoning occurs.

Responsibilities:

* Validate schema
* Check missing values
* Detect duplicates
* Validate ranges
* Validate dates/weeks
* Validate relationships
* Detect inconsistent aggregates
* Produce data-quality score

Output:

```json
{
  "status": "PASS|WARN|FAIL",
  "data_quality_score": 0,
  "issues": [],
  "warnings": [],
  "validated_records": 0
}
```

If critical validation fails, downstream analysis must not proceed until the issue is resolved or explicitly marked as a known exception.

---

# 10. AGENT 02 — METRICS ANALYSIS

Calculate:

* Current values
* Previous-period values
* Absolute change
* Percentage change
* Trend direction
* Relative ranking

Do not use LLM reasoning for arithmetic.

Generate structured metric observations.

Example:

```json
{
  "metric": "cycle_time",
  "team": "Atlas",
  "current": 4.2,
  "previous": 3.1,
  "change_pct": 35.48,
  "direction": "deteriorating"
}
```

---

# 11. AGENT 03 — QUALITY ANALYSIS

Analyze:

* Defects
* Severity
* Escaped defects
* Regression defects
* Test coverage
* Change failure rate
* Quality trends

Identify:

* Improving quality
* Deteriorating quality
* Persistent quality risks
* Potential leading indicators

---

# 12. AGENT 04 — TREND ANALYSIS

Analyze the full 16-week history.

Classify patterns as:

```text
IMPROVING
STABLE
DETERIORATING
VOLATILE
ONE_TIME_ANOMALY
INSUFFICIENT_DATA
```

Do not call a single-week spike a trend.

Require a minimum evidence threshold.

Document the threshold in the agent instructions.

---

# 13. AGENT 05 — ANOMALY DETECTION

Identify unusual observations.

Every anomaly must include:

* What happened
* Expected baseline
* Magnitude
* Time period
* Affected dimension
* Supporting records
* Confidence

The agent must distinguish:

```text
Anomaly
vs
Trend
```

---

# 14. AGENT 06 — RISK ANALYSIS

Convert validated signals into engineering risks.

Risk categories:

* Delivery
* Quality
* Reliability
* Operational
* Engineering efficiency
* Sustainability

Each risk must contain:

```json
{
  "risk": "",
  "category": "",
  "severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "evidence": [],
  "confidence": 0,
  "potential_impact": "",
  "recommended_follow_up": ""
}
```

Do not invent root causes.

Use:

```text
Observed evidence
→ Possible explanation
→ Confidence
```

not:

```text
Metric changed
→ Therefore this is definitely the cause
```

---

# 15. AGENT 07 — ENGINEERING COACH

Translate analytical findings into actionable recommendations.

Recommendations must be:

* Specific
* Evidence-based
* Prioritized
* Actionable
* Proportional to the evidence

For every recommendation provide:

```text
Problem
Evidence
Recommended action
Expected outcome
Owner type
Priority
Measurement of success
```

Avoid generic advice such as:

> "Improve quality."

Instead:

> "Investigate the sustained increase in escaped defects for Team X over the last five weeks and review whether the decline in automated coverage is concentrated in the affected service."

---

# 16. AGENT 08 — EVIDENCE VALIDATION

This is a critical agent.

Its job is to challenge the other agents.

For every significant finding ask:

1. Is the claim supported by data?
2. Can the source records be identified?
3. Is the calculation correct?
4. Is this actually a trend?
5. Could this simply be an anomaly?
6. Is causality being incorrectly claimed?
7. Is confidence appropriate?
8. Does the recommendation logically follow?

Every finding receives:

```text
PASS
WARN
REJECT
```

Rejected findings must not appear in executive outputs.

Warnings must be clearly marked.

---

# 17. AGENT 09 — DASHBOARD GENERATION

Create an interactive HTML dashboard.

The dashboard must be visually polished and executive-quality.

Do NOT create a static mockup.

It must use the actual generated analytical data.

Include:

## Executive KPI cards

Examples:

* Engineering Health Score
* Delivery Health
* Quality Health
* Reliability Health
* Efficiency Health

## Trend charts

Examples:

* Cycle time
* Defect rate
* Deployment success
* Test coverage
* Incident rate

## Risk view

Display:

* Risk severity
* Risk category
* Affected team
* Evidence
* Confidence

## Team comparison

Allow users to compare teams.

## Platform comparison

Allow users to compare platforms.

## Time filtering

Allow:

* 4 weeks
* 8 weeks
* 12 weeks
* 16 weeks

## Drill-down

This is mandatory.

A user should be able to click:

```text
KPI
→ Metric
→ Team/platform
→ Week
→ Source record
```

The dashboard must make it possible to understand **why a number exists**.

## Evidence panel

Every AI-generated insight should expose supporting evidence.

For example:

```text
Why is this flagged?

Cycle time increased 38% over 5 weeks.

Evidence:
Week 12: 2.8 days
Week 13: 3.1 days
Week 14: 3.5 days
Week 15: 3.7 days
Week 16: 3.9 days
```

---

# 18. DASHBOARD DESIGN

Use a modern executive/futuristic aesthetic.

However:

DO NOT use the generic:

> dark blue + purple + neon AI dashboard

look.

Prefer:

* Sophisticated
* Clean
* Premium
* High information density
* Strong typography
* Subtle futuristic elements
* Excellent whitespace
* Clear hierarchy

The dashboard should feel appropriate for an executive engineering organization.

---

# 19. POWERPOINT DECK

Create a polished executive presentation.

Target approximately 10–14 slides.

Suggested structure:

### Slide 1

Title

### Slide 2

Executive Summary

### Slide 3

Engineering Health Score

### Slide 4

What Improved

### Slide 5

What Deteriorated

### Slide 6

Emerging Trends

### Slide 7

Top Engineering Risks

### Slide 8

Quality & Reliability

### Slide 9

Team/Platform Comparison

### Slide 10

Recommended Actions

### Slide 11

Expected Outcomes / Measurement

### Slide 12

How the Intelligence System Works

### Slide 13

Evidence & Confidence Model

### Slide 14

Appendix / Methodology

Do not simply export dashboard screenshots.

The presentation must tell a coherent executive story.

---

# 20. POWERPOINT DESIGN

Use a modern futuristic executive theme.

Requirements:

* Strong visual hierarchy
* Minimal text
* High-quality charts
* Consistent typography
* Consistent spacing
* Clear storytelling
* Appropriate visual emphasis
* No walls of text
* No meaningless decorative graphics

Use actual analytical results.

Every important number must match the source analysis.

---

# 21. ARCHITECTURE DIAGRAM

Create a professional architecture diagram.

It must show:

```text
Synthetic Data
      ↓
Data Validation
      ↓
Orchestration Layer
      ↓
 ┌─────────────────────────────┐
 │      Analysis Agents        │
 │                             │
 │ Metrics                     │
 │ Quality                     │
 │ Trends                      │
 │ Anomalies                   │
 │ Risk                        │
 │ Engineering Coaching        │
 └─────────────────────────────┘
      ↓
Evidence Validation
      ↓
 ┌──────────────┬───────────────┬───────────────┐
 ↓              ↓               ↓
Dashboard      Executive       Design/
               Presentation    Architecture
```

But do not blindly follow this example.

The final architecture must accurately reflect the actual implementation.

Show:

* Data layer
* Agent layer
* Orchestration
* Validation loop
* Analytical artifacts
* Dashboard
* Presentation
* Design documentation

Use a standard diagram format such as Mermaid, SVG, or another reproducible format.

---

# 22. SEQUENCE DIAGRAM

Create a sequence diagram showing the actual runtime behavior.

Include:

* User
* Orchestrator
* Data Validation Agent
* Analysis agents
* Evidence Validation Agent
* Dashboard Generator
* Presentation Generator
* Artifact generation

Show:

### Success path

```text
Input
→ Validate
→ Analyze
→ Correlate
→ Identify risks
→ Validate evidence
→ Generate artifacts
→ Final output
```

### Failure path

Show at least:

```text
Validation FAIL
→ Correct/resolve
→ Revalidate
```

and:

```text
Evidence validation FAIL
→ Reject finding
→ Re-run affected analysis if necessary
```

The sequence diagram must represent actual workflow behavior rather than being decorative.

---

# 23. TRACEABILITY MODEL

Implement traceability throughout the system.

Every significant insight should have:

```text
Insight ID
↓
Metric(s)
↓
Source dataset
↓
Source records
↓
Calculation
↓
Agent that generated it
↓
Validation result
↓
Recommendation
```

Example:

```text
RISK-004
  ↓
cycle_time
  ↓
Atlas
  ↓
Weeks 12–16
  ↓
+39%
  ↓
Trend Analysis Agent
  ↓
Evidence Validation = PASS
  ↓
Investigate delivery bottleneck
```

This is one of the most important requirements.

---

# 24. CONFIDENCE MODEL

Do not allow arbitrary confidence scores.

Define a transparent confidence model.

Confidence should consider things such as:

* Data completeness
* Number of observations
* Trend consistency
* Magnitude
* Evidence quality
* Validation status

Document how confidence is calculated.

---

# 25. IDEMPOTENCY

The workflow must be idempotent.

Running it twice with the same input should produce equivalent analytical results.

Do not:

* Duplicate records
* Append duplicate findings
* Corrupt outputs
* Create uncontrolled artifact versions

Where appropriate, use deterministic IDs.

---

# 26. TESTING

Create tests for:

### Data validation

* Missing values
* Duplicate records
* Invalid values
* Bad dates
* Broken aggregates

### Metrics

* Percentage calculations
* WoW calculations
* Trend calculations

### Agents

* Expected outputs
* Invalid inputs
* Missing dependencies

### Evidence

* Unsupported claims rejected
* Correct claims accepted

### Dashboard

* Data loads
* Filters work
* Drill-down works
* Source records appear

### Output consistency

Verify:

```text
Raw data
↕
Analytical output
↕
Dashboard
↕
PowerPoint
```

Do not allow contradictory numbers.

---

# 27. QUALITY GATE

Before declaring the project complete, execute a self-evaluation.

The system must answer:

### Data

* Is synthetic data realistic?
* Does it contain meaningful signals?
* Are planted anomalies detectable?

### Agents

* Does each agent have a clear purpose?
* Are agent boundaries sensible?
* Are outputs structured?
* Are dependencies explicit?

### Reasoning

* Are conclusions evidence-backed?
* Are trends distinguished from anomalies?
* Is causality avoided?
* Are unsupported claims rejected?

### Dashboard

* Is it interactive?
* Can users drill down?
* Are charts based on real generated data?
* Can users trace insights back to records?

### Presentation

* Is it executive-ready?
* Does it tell a coherent story?
* Does it match the analytical results?

### Architecture

* Does the diagram reflect implementation?

### Sequence

* Does the sequence diagram reflect actual runtime behavior?

### Reproducibility

* Can the workflow be run again?

---

# 28. SELF-CRITIQUE LOOP

Do not stop after the first successful run.

After generating all artifacts:

## Step 1

Inspect your own output.

## Step 2

Identify at least five weaknesses.

Examples:

* Poor visualization
* Weak agent boundary
* Unsupported conclusion
* Missing drill-down
* Inconsistent number
* Poor executive narrative
* Insufficient validation

## Step 3

Fix the weaknesses.

## Step 4

Run the system again.

## Step 5

Revalidate.

Only then declare completion.

---

# 29. README

Create a README explaining:

* What the system does
* Why it exists
* Architecture
* Agents
* Data model
* How to run
* How to regenerate synthetic data
* How to run analysis
* How to generate dashboard
* How to generate PowerPoint
* How to regenerate diagrams
* Testing
* Limitations
* Future production architecture

Include a section:

# What I Learned

Leave this section as a template for the human learner to fill in after experimentation.

---

# 30. IMPORTANT LEARNING OBJECTIVE

The purpose of this exercise is NOT merely to produce polished artifacts.

The user is specifically practicing:

```text
See
↓
Try
↓
Fail
↓
Ask AI
↓
Fix
↓
Repeat
```

Therefore:

* Prefer understandable architecture over unnecessary complexity.
* Make failures visible.
* Do not hide errors.
* Explain why something failed.
* Make the system easy to inspect.
* Keep agent responsibilities understandable.
* Avoid black-box magic.

The project should teach the user how an agentic system is actually constructed.

---

# 31. IMPLEMENTATION PRINCIPLES

Follow these rules:

1. Do not fabricate real-world/company data.
2. Do not require proprietary credentials.
3. Do not connect to external enterprise systems.
4. Prefer local synthetic data.
5. Prefer deterministic calculations for numerical operations.
6. Use structured schemas between agents.
7. Keep agent responsibilities narrow.
8. Make evidence traceable.
9. Make outputs reproducible.
10. Validate before presenting.
11. Never hide failures.
12. Never claim causation without evidence.
13. Never generate an executive recommendation without supporting evidence.
14. Keep the architecture understandable.
15. Build the smallest viable version first, then improve it.

---

# 32. EXECUTION STRATEGY

Do not attempt to generate everything blindly in one pass.

Use this implementation sequence:

### Phase 1 — Foundation

Create:

* Directory structure
* CLAUDE.md
* README
* Data schemas
* Synthetic data generator

### Phase 2 — Agents

Create and test agents sequentially.

Start with:

```text
01 Data Validation
02 Metrics Analysis
03 Quality Analysis
04 Trend Analysis
05 Anomaly Detection
06 Risk Analysis
07 Engineering Coach
08 Evidence Validation
```

Do not build presentation/dashboard generation until the analytical pipeline works.

### Phase 3 — Orchestration

Connect the agents.

Make dependencies explicit.

Allow independent analysis agents to run in parallel where appropriate.

### Phase 4 — Validation

Run the complete analytical workflow.

Inspect failures.

Fix them.

### Phase 5 — Dashboard

Build the interactive dashboard from validated analytical outputs.

### Phase 6 — Executive Presentation

Generate the PowerPoint from the same validated analytical outputs.

### Phase 7 — Architecture Documentation

Generate architecture and sequence diagrams based on the actual implementation.

### Phase 8 — Final QA

Run the complete quality gate.

---

# 33. FINAL DELIVERABLES

When finished, the project should contain:

```text
✓ CLAUDE.md

✓ Synthetic dataset

✓ Data schemas

✓ 10 agent specifications

✓ Agent implementation

✓ Orchestration

✓ Validation system

✓ Tests

✓ Interactive HTML dashboard

✓ Executive PowerPoint

✓ Architecture diagram

✓ Sequence diagram

✓ Executive report

✓ README

✓ Example generated outputs
```

---

# 34. FINAL RESPONSE

When the build is complete, provide a concise completion summary containing:

## What was built

List the major components.

## Agent workflow

Show the agent execution flow.

## Key findings from synthetic data

List the most important insights discovered.

## Validation results

State:

* Tests passed
* Findings accepted
* Findings rejected
* Data-quality issues detected

## Generated artifacts

List every major output.

## How to run

Provide exact commands.

## What failed during development

Be honest.

List meaningful failures encountered and how they were fixed.

## Suggested next experiment

Recommend one small modification the user can make themselves.

Do NOT claim that the project is complete unless the system has actually been executed and validated.

If something could not be executed, explicitly state:

> "Built but not executed."

or:

> "Executed with the following known limitation..."

Never pretend an artifact was tested when it was not.

---

# 35. START NOW

Begin by inspecting the environment and determining what tools/frameworks are available.

Then:

1. Create the project structure.
2. Create `CLAUDE.md`.
3. Create the synthetic data model.
4. Generate the synthetic dataset.
5. Create the agent specifications.
6. Implement the workflow.
7. Run it.
8. Validate it.
9. Build the dashboard.
10. Build the PowerPoint.
11. Build the architecture diagram.
12. Build the sequence diagram.
13. Run the final quality gate.
14. Fix issues.
15. Produce the final artifacts.

Do not stop at planning.

**Build the system.**
