"""Architecture and sequence diagrams, generated from the implementation (Phase 7).

Nothing here is drawn by hand:
  * the architecture comes from src/orchestration/orchestrator.py (DEPENDENCIES, OUTPUT_AGENTS),
    reduced to the edges that are not implied by other edges (transitive reduction);
  * the sequence diagram's success path comes from the latest run log
    (output/reports/run_log.json: real order, real parallel layer, real statuses), and its
    failure paths mirror the orchestrator's code paths (gate, crash, evidence feedback loop).
Each diagram is written as Mermaid (renders on GitHub) and as a standalone SVG.

Run:  python -m src.reporting.diagrams
"""
import json
from html import escape

from src.common.envelope import AGENTS, processed_dir
from src.config import load_json, project_path
from src.orchestration.orchestrator import DEPENDENCIES, MAX_FEEDBACK_ROUNDS, OUTPUT_AGENTS, levels

OUT = project_path("output/diagrams")
LABEL = {"01": "01 Data Validation", "02": "02 Metrics Analysis", "03": "03 Quality Analysis", "04": "04 Trend Analysis",
         "05": "05 Anomaly Detection", "06": "06 Risk Analysis", "07": "07 Engineering Coach", "08": "08 Evidence Validation",
         "09": "09 Dashboard Generation", "10": "10 Executive Report"}
INK, PAPER, PANEL, LINE, MUTED, TEAL, BAD, GOOD, WARN = "#16191d", "#ffffff", "#f3f3f1", "#d6d1c6", "#666b73", "#0e6b63", "#b4361f", "#2e7d4f", "#9a6a0c"


# ============================================================ graph helpers
def full_graph():
    """Every dependency edge: the orchestrator's DAG, plus each output agent's declared
    `depends_on` (read from its envelope) and the fact that output agents run in order."""
    g = {k: set(v) for k, v in DEPENDENCIES.items()}
    for i, k in enumerate(OUTPUT_AGENTS):
        env = load_json(processed_dir() / f"{AGENTS[k]}.json")
        g[k] = {d[:2] for d in env["depends_on"]} | set(OUTPUT_AGENTS[:i])
    return g


def reachable(g, node):
    seen, stack = set(), list(g[node])
    while stack:
        n = stack.pop()
        if n not in seen:
            seen.add(n)
            stack.extend(g[n])
    return seen


def transitive_reduction(g):
    red = {}
    for n, deps in g.items():
        red[n] = {d for d in deps if not any(d in reachable(g, other) for other in deps if other != d)}
    return red


# ============================================================ architecture
def architecture_mermaid():
    red = transitive_reduction(full_graph())
    L = ["flowchart TB",
         '  classDef gate fill:#16191d,color:#fff,stroke:#16191d',
         '  classDef agent fill:#f3f3f1,color:#16191d,stroke:#d6d1c6',
         '  classDef data fill:#dcecea,color:#16191d,stroke:#0e6b63',
         '  classDef out fill:#fff,color:#16191d,stroke:#0e6b63,stroke-width:2px',
         '  classDef ai fill:#f4ead2,color:#16191d,stroke:#9a6a0c',
         '  subgraph DATA["Data layer"]',
         '    CFG["config/*.json<br/>settings, metric catalog, thresholds, known exceptions"]:::data',
         '    GEN["Synthetic data generator<br/>src/data"]:::data',
         '    RAW["data/raw/*.csv + MANIFEST<br/>validated by data/schemas"]:::data',
         '  end',
         '  CFG --> GEN --> RAW',
         '  subgraph ORCH["Orchestrator · src/orchestration · python run.py"]']
    for layer in levels():
        for k in layer:
            cls = "gate" if k in ("01", "08") else "agent"
            L.append(f'    A{k}["{LABEL[k]}"]:::{cls}')
    L.append("  end")
    L.append('  subgraph OUTPUTS["Outputs · built only from validated findings"]')
    for k in OUTPUT_AGENTS:
        L.append(f'    A{k}["{LABEL[k]}"]:::out')
    L += ['    DASH["dashboard/ · interactive HTML"]:::out', '    DECK["output/ · PowerPoint + report"]:::out',
          '    DIAG["output/diagrams · generated from code"]:::out', "  end",
          '  subgraph AI["Claude Code reasoning layer (optional, no API key)"]',
          '    BRIEF["brief.json<br/>validated findings only"]:::ai', '    SUB["risk-narrator +<br/>engineering-coach-writer subagents"]:::ai',
          '    ING["ingest: stale? new numbers?<br/>causal claims? generic?"]:::ai', "  end",
          "  RAW --> A01", "  CFG --> A01"]
    for n in sorted(red):
        for d in sorted(red[n]):
            L.append(f"  A{d} --> A{n}")
    L += ['  A08 -. "REJECT → rerun_requests: re-run 07 without rejected findings" .-> A07',
          '  A01 -. "FAIL → pipeline BLOCKED" .-> GATEFAIL(["stop: fix data or approve exception"])',
          "  A09 --> DASH", "  A10 --> DECK", "  A08 --> BRIEF --> SUB --> ING --> A09"]
    return "\n".join(L) + "\n"


def architecture_svg():
    """Layered top-to-bottom layout: one row per orchestrator layer."""
    red = transitive_reduction(full_graph())
    rows = [["DATA"]] + levels() + [OUTPUT_AGENTS]
    W, rh, bw, bh = 980, 92, 230, 50
    H = 120 + rh * len(rows) + 40
    pos = {}
    for r, row in enumerate(rows):
        n = len(row)
        for i, k in enumerate(row):
            x = W / 2 + (i - (n - 1) / 2) * (bw + 40) - bw / 2
            pos[k] = (x, 100 + r * rh)
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Segoe UI, Calibri, Arial, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{PAPER}"/>',
         '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         f'<path d="M0,0 L10,5 L0,10 z" fill="{MUTED}"/></marker>'
         '<marker id="b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         f'<path d="M0,0 L10,5 L0,10 z" fill="{BAD}"/></marker></defs>',
         f'<text x="40" y="44" font-size="22" font-weight="600" fill="{INK}">Engineering Health Intelligence System · architecture</text>',
         f'<text x="40" y="68" font-size="13" fill="{MUTED}">Generated from src/orchestration/orchestrator.py (transitive reduction of the dependency graph). Rows run in order; boxes in one row run in parallel.</text>']

    def box(k, x, y):
        if k == "DATA":
            fill, stroke, color, label, sub = "#dcecea", TEAL, INK, "Synthetic data + config", "CSV files · schemas · thresholds"
        else:
            gate = k in ("01", "08")
            out = k in OUTPUT_AGENTS
            fill = INK if gate else (PAPER if out else PANEL)
            stroke = INK if gate else (TEAL if out else LINE)
            color = PAPER if gate else INK
            label = LABEL[k]
            sub = {"01": "gate: FAIL stops the run", "08": "PASS / WARN / REJECT", "09": "dashboard/", "10": "PowerPoint + report",
                   "02": "metric_series.json", "06": "proposes widely", "07": "actions + targets"}.get(k, "")
        out = [f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="9" fill="{fill}" stroke="{stroke}" stroke-width="{2 if k in OUTPUT_AGENTS else 1.2}"/>',
               f'<text x="{x + 14}" y="{y + 21}" font-size="14" font-weight="600" fill="{color}">{escape(label)}</text>']
        if sub:
            out.append(f'<text x="{x + 14}" y="{y + 39}" font-size="11.5" fill="{"#c9cdd2" if k in ("01", "08") else MUTED}">{escape(sub)}</text>')
        return out

    edges = [("DATA", "01")] + [(d, n) for n in red for d in red[n]]
    for a, b in edges:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        if y1 == y2:  # same row (e.g. 09 -> 10): side to side
            s.append(f'<line x1="{x1 + bw}" y1="{y1 + bh / 2}" x2="{x2 - 2}" y2="{y2 + bh / 2}" stroke="{MUTED}" stroke-width="1.4" marker-end="url(#a)"/>')
            continue
        s.append(f'<line x1="{x1 + bw / 2}" y1="{y1 + bh}" x2="{x2 + bw / 2}" y2="{y2 - 2}" stroke="{MUTED}" stroke-width="1.4" marker-end="url(#a)"/>')
    (x8, y8), (x7, y7) = pos["08"], pos["07"]
    s.append(f'<path d="M{x8 + bw} {y8 + bh / 2} C {x8 + bw + 110} {y8 + bh / 2}, {x7 + bw + 110} {y7 + bh / 2}, {x7 + bw + 2} {y7 + bh / 2}" '
             f'fill="none" stroke="{BAD}" stroke-width="1.6" stroke-dasharray="5 4" marker-end="url(#b)"/>')
    s.append(f'<text x="{x8 + bw + 92}" y="{(y7 + y8) / 2 + bh / 2 + 4}" font-size="12" fill="{BAD}">REJECT → re-run 07 (≤ {MAX_FEEDBACK_ROUNDS} rounds)</text>')
    x1, y1 = pos["01"]
    s.append(f'<text x="{x1 + bw + 16}" y="{y1 + 30}" font-size="12" fill="{BAD}">FAIL → pipeline BLOCKED, nothing downstream runs</text>')
    for k, (x, y) in pos.items():
        s += box(k, x, y)
    # Reasoning layer: left of the 06-08 rows, fed by 08 and feeding 09.
    yb, bx, bwid = pos["06"][1], 30, 280
    s.append(f'<rect x="{bx}" y="{yb}" width="{bwid}" height="{pos["08"][1] + bh - yb}" rx="9" fill="#f4ead2" stroke="{WARN}"/>')
    s.append(f'<text x="{bx + 14}" y="{yb + 22}" font-size="13.5" font-weight="600" fill="{INK}">Claude Code reasoning layer</text>')
    for i, t in enumerate(["brief: validated findings only", "subagents write narratives", "ingest rejects: stale, new numbers,",
                           "causal claims, generic text", "accepted narratives → 09 only"]):
        s.append(f'<text x="{bx + 14}" y="{yb + 44 + i * 18}" font-size="11.5" fill="{INK}">{escape(t)}</text>')
    x8, y8 = pos["08"]
    s.append(f'<line x1="{x8}" y1="{y8 + bh / 2}" x2="{bx + bwid + 2}" y2="{y8 + bh / 2}" stroke="{WARN}" stroke-width="1.4" marker-end="url(#a)"/>')
    x9, y9 = pos["09"]
    s.append(f'<path d="M{bx + bwid / 2} {pos["08"][1] + bh} V {y9 + bh / 2} H {x9 - 2}" fill="none" stroke="{WARN}" stroke-width="1.4" marker-end="url(#a)"/>')
    s.append("</svg>")
    return "\n".join(s) + "\n"


# ============================================================ sequence
def sequence_items(run_log):
    """One list of steps that both the Mermaid and the SVG renderer draw."""
    steps = [st for st in run_log["steps"] if st["round"] == 1]
    order = [s["agent"][:2] for s in steps]
    status = {s["agent"][:2]: s["status"] for s in steps}
    par = next((lay for lay in levels() if len(lay) > 1), [])
    it = [("msg", "U", "O", "python run.py"), ("note", "O", "clean slate: delete previous agent outputs")]
    done = set()
    for k in order:
        if k in done:
            continue
        if k in par:
            it.append(("par", "parallel layer"))
            for j, p in enumerate(par):
                if j:
                    it.append(("and", ""))
                it += [("msg", "O", p, "run()"), ("ret", p, "O", status[p])]
                done.add(p)
            it.append(("end",))
            continue
        it += [("msg", "O", k, "run()"), ("ret", k, "O", status[k])]
        done.add(k)
        if k == "01":
            it += [("alt", "01 status = FAIL (un-excepted CRITICAL issue)"),
                   ("ret", "O", "U", "BLOCKED + blocking issues · exit 1 · nothing else runs"),
                   ("msg", "U", "U", "fix the data, or approve a documented exception"),
                   ("msg", "U", "O", "re-run → 01 revalidates"),
                   ("else", "PASS / WARN (issues handled by directives)"), ("note", "O", "continue"), ("end",)]
        if k == "08":
            it += [("loop", f"while 08 has rerun_requests (max {MAX_FEEDBACK_ROUNDS} rounds)"),
                   ("msg", "O", "07", "run(exclude = rejected findings)"), ("ret", "07", "O", "recommendations rebuilt"),
                   ("msg", "O", "08", "re-validate"), ("ret", "08", "O", "verdicts"), ("end",)]
    it += [("alt", "an agent raises / an output check fails"), ("ret", "O", "U", "ERROR · dependants skipped · exit 1"),
           ("else", "all passed"), ("ret", "O", "U", f"{run_log['status']} · run_log.json"), ("end",),
           ("msg", "U", "O", "python run.py brief"), ("ret", "O", "U", "brief.json (validated findings only)"),
           ("msg", "U", "C", "run risk-narrator + engineering-coach-writer"), ("ret", "C", "U", "narratives_*.json"),
           ("msg", "U", "O", "python run.py ingest"),
           ("alt", "narrative is stale / adds a number / claims a cause / is generic"), ("note", "O", "REJECT: deterministic wording kept"),
           ("else", "accepted"), ("msg", "O", "09", "refresh dashboard with accepted narratives"), ("end",)]
    return it


PARTS = [("U", "User"), ("O", "Orchestrator"), ("01", "01 Validation"), ("02", "02 Metrics"), ("04", "04 Trends"),
         ("05", "05 Anomalies"), ("03", "03 Quality"), ("06", "06 Risk"), ("07", "07 Coach"), ("08", "08 Evidence"),
         ("09", "09 Dashboard"), ("10", "10 Report"), ("C", "AI subagents")]


def sequence_mermaid(items):
    L = ["sequenceDiagram", "  autonumber"] + [f"  participant P{k} as {name}" for k, name in PARTS]
    for item in items:
        kind = item[0]
        if kind == "msg":
            L.append(f"  P{item[1]}->>P{item[2]}: {item[3]}")
        elif kind == "ret":
            L.append(f"  P{item[1]}-->>P{item[2]}: {item[3]}")
        elif kind == "note":
            L.append(f"  Note over P{item[1]}: {item[2]}")
        elif kind in ("par", "alt", "loop"):
            L.append(f"  {kind} {item[1]}")
        elif kind == "and":
            L.append("  and")
        elif kind == "else":
            L.append(f"  else {item[1]}")
        elif kind == "end":
            L.append("  end")
    return "\n".join(L) + "\n"


def sequence_svg(items):
    col = {k: 70 + i * 112 for i, (k, _) in enumerate(PARTS)}
    W = 70 + len(PARTS) * 112
    y, rows, blocks, stack = 110, [], [], []
    for item in items:
        kind = item[0]
        if kind in ("par", "alt", "loop"):
            stack.append([kind, item[1], y, []])
            y += 44  # clear the block's header label before the first message
        elif kind in ("and", "else"):
            stack[-1][3].append((y, item[1]))
            y += 40
        elif kind == "end":
            k, label, y0, splits = stack.pop()
            blocks.append((k, label, y0, y, splits, len(stack)))
            y += 14
        else:
            rows.append((item, y))
            y += 30
    H = y + 50
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Segoe UI, Calibri, Arial, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{PAPER}"/>',
         '<defs><marker id="s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         f'<path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker></defs>',
         f'<text x="20" y="30" font-size="20" font-weight="600" fill="{INK}">Runtime sequence · success and failure paths</text>',
         f'<text x="20" y="50" font-size="12" fill="{MUTED}">Success path and statuses from output/reports/run_log.json; failure paths mirror the orchestrator code.</text>']
    for k, name in PARTS:
        x = col[k]
        s.append(f'<line x1="{x}" y1="86" x2="{x}" y2="{H - 30}" stroke="{LINE}" stroke-dasharray="3 4"/>')
        dark = k in ("01", "08")
        s.append(f'<rect x="{x - 52}" y="62" width="104" height="26" rx="6" fill="{INK if dark else PANEL}" stroke="{INK if dark else LINE}"/>')
        s.append(f'<text x="{x}" y="79" font-size="11" font-weight="600" text-anchor="middle" fill="{PAPER if dark else INK}">{escape(name)}</text>')
    color = {"par": TEAL, "alt": BAD, "loop": WARN}
    for kind, label, y0, y1, splits, depth in blocks:
        x0, x1 = 12 + depth * 6, W - 12 - depth * 6
        c = color[kind]
        s.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="none" stroke="{c}" stroke-width="1.2" rx="4"/>')
        s.append(f'<rect x="{x0}" y="{y0}" width="{max(60, len(label) * 6.4 + 60)}" height="20" fill="{c}" rx="4"/>')
        s.append(f'<text x="{x0 + 8}" y="{y0 + 14}" font-size="11" font-weight="600" fill="{PAPER}">{kind.upper()} · {escape(label)}</text>')
        for ys, lab in splits:
            s.append(f'<line x1="{x0}" y1="{ys + 4}" x2="{x1}" y2="{ys + 4}" stroke="{c}" stroke-dasharray="5 4"/>')
            if lab:
                s.append(f'<text x="{x0 + 8}" y="{ys + 17}" font-size="11" font-style="italic" fill="{c}">[{escape(lab)}]</text>')
    for item, yy in rows:
        kind = item[0]
        if kind == "note":
            x = col[item[1]]
            w = len(item[2]) * 6.3 + 20
            s.append(f'<rect x="{x - w / 2}" y="{yy - 13}" width="{w}" height="20" fill="#f4ead2" stroke="{WARN}" rx="3"/>')
            s.append(f'<text x="{x}" y="{yy + 1}" font-size="11" text-anchor="middle" fill="{INK}">{escape(item[2])}</text>')
            continue
        a, b, text = col[item[1]], col[item[2]], item[3]
        dash = ' stroke-dasharray="5 4"' if kind == "ret" else ""
        if a == b:
            s.append(f'<path d="M{a} {yy} h34 v12 h-32" fill="none" stroke="{INK}" stroke-width="1.2"{dash} marker-end="url(#s)"/>')
            s.append(f'<text x="{a + 40}" y="{yy + 8}" font-size="11" fill="{INK}">{escape(text)}</text>')
            continue
        s.append(f'<line x1="{a}" y1="{yy}" x2="{b + (-3 if b > a else 3)}" y2="{yy}" stroke="{INK}" stroke-width="1.2"{dash} marker-end="url(#s)"/>')
        tc = BAD if text.startswith(("FAIL", "ERROR", "BLOCKED")) else (WARN if text == "WARN" else INK)
        if abs(b - a) < 200 and len(text) * 6 > abs(b - a) - 10:
            # Short arrow, long label: write it to the right of the arrow instead of across lifelines.
            s.append(f'<text x="{max(a, b) + 8}" y="{yy + 4}" font-size="11" fill="{tc}">{escape(text)}</text>')
        else:
            s.append(f'<text x="{(a + b) / 2}" y="{yy - 5}" font-size="11" text-anchor="middle" fill="{tc}">{escape(text)}</text>')
    s.append("</svg>")
    return "\n".join(s) + "\n"


# ============================================================ write
def write(run_log=None):
    run_log = run_log or load_json(project_path("output/reports/run_log.json"))
    OUT.mkdir(parents=True, exist_ok=True)
    items = sequence_items(run_log)
    files = {
        "architecture.mmd": architecture_mermaid(),
        "architecture.svg": architecture_svg(),
        "sequence.mmd": sequence_mermaid(items),
        "sequence.svg": sequence_svg(items),
    }
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8", newline="\n")
    md = ["# Diagrams", "", "_Generated by `python -m src.reporting.diagrams` from the orchestrator and the latest run log. Do not edit by hand._", "",
          "## Architecture", "", "![Architecture](architecture.svg)", "", "```mermaid", files["architecture.mmd"].rstrip(), "```", "",
          "## Runtime sequence", "", "![Sequence](sequence.svg)", "", "```mermaid", files["sequence.mmd"].rstrip(), "```", ""]
    (OUT / "README.md").write_text("\n".join(md), encoding="utf-8", newline="\n")
    return files, items


def main():
    files, items = write()
    print(f"Wrote {len(files) + 1} files to {OUT}: {', '.join(sorted(files))}, README.md ({len(items)} sequence steps)")


if __name__ == "__main__":
    main()
