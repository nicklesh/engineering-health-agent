/* Minimal SVG charts (no library, works offline). Colours come from CSS variables so light
   and dark themes both work. */
(function (root) {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";

  function el(name, attrs, parent) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function niceExtent(vals) {
    const v = vals.filter(x => x !== null && x !== undefined);
    if (!v.length) return [0, 1];
    let lo = Math.min.apply(null, v), hi = Math.max.apply(null, v);
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.12;
    lo = lo - pad; hi = hi + pad;
    if (Math.min.apply(null, v) >= 0 && lo < 0) lo = 0;
    return [lo, hi];
  }
  function ticks(lo, hi, n) {
    const step = Math.pow(10, Math.floor(Math.log10((hi - lo) / n)));
    const err = (hi - lo) / n / step;
    const s = step * (err >= 5 ? 5 : err >= 2 ? 2 : 1);
    const out = [];
    for (let t = Math.ceil(lo / s) * s; t <= hi + 1e-9; t += s) out.push(+t.toFixed(10));
    out.digits = Math.max(0, -Math.floor(Math.log10(s) + 1e-9));  // decimals needed so labels stay distinct
    return out;
  }

  /* opts: {weeks, range:[lo,hi], series:[{values, cls, label, dashed}], format(v), band:[from,to,cls],
            markers:[{week, cls, title}], selectedWeek, onPoint(week), height} */
  function lineChart(container, opts) {
    container.innerHTML = "";
    const W = 560, H = opts.height || 200, m = { t: 12, r: 14, b: 26, l: 44 };
    const [lo, hi] = opts.range;
    const weeks = []; for (let w = lo; w <= hi; w++) weeks.push(w);
    const all = [];
    opts.series.forEach(s => weeks.forEach(w => all.push(s.values[w - 1])));
    const [y0, y1] = niceExtent(all);
    const x = w => m.l + (weeks.length === 1 ? 0.5 : (w - lo) / (hi - lo)) * (W - m.l - m.r);
    const y = v => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": opts.label || "chart" }, container);

    const yt = ticks(y0, y1, 4);
    yt.forEach(t => {
      el("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: "grid" }, svg);
      const tx = el("text", { x: m.l - 8, y: y(t) + 4, class: "axis", "text-anchor": "end" }, svg);
      tx.textContent = opts.formatTick ? opts.formatTick(t, yt.digits) : t;
    });
    weeks.forEach(w => {
      if (weeks.length > 8 && w % 2 && w !== hi) return;
      const tx = el("text", { x: x(w), y: H - 8, class: "axis", "text-anchor": "middle" }, svg);
      tx.textContent = "W" + w;
    });
    if (opts.band) {
      const from = Math.max(opts.band[0], lo), to = Math.min(opts.band[1], hi);
      if (from <= to) {
        el("rect", { x: x(from) - (weeks.length > 1 ? 6 : 10), y: m.t, width: Math.max(12, x(to) - x(from) + 12),
                     height: H - m.t - m.b, class: "band " + opts.band[2] }, svg);
      }
    }
    opts.series.forEach(s => {
      let d = "", pen = false;
      weeks.forEach(w => {
        const v = s.values[w - 1];
        if (v === null || v === undefined) { pen = false; return; }
        d += (pen ? "L" : "M") + x(w).toFixed(1) + "," + y(v).toFixed(1);
        pen = true;
      });
      el("path", { d, class: "line " + (s.cls || "") + (s.dashed ? " dashed" : "") }, svg);
    });
    const main = opts.series[0];
    const tip = el("text", { class: "tip", x: 0, y: 0, visibility: "hidden" }, svg);
    weeks.forEach(w => {
      const v = main.values[w - 1];
      if (v === null || v === undefined) return;
      const marker = (opts.markers || []).find(k => k.week === w);
      const g = el("g", { class: "pt" + (marker ? " " + marker.cls : "") + (opts.selectedWeek === w ? " selected" : ""),
                          tabindex: 0, role: "button", "data-week": w,
                          "aria-label": `Week ${w}: ${opts.format(v)}${marker ? " - " + marker.title : ""}` }, svg);
      el("circle", { cx: x(w), cy: y(v), r: marker ? 5 : 3.2 }, g);
      el("circle", { cx: x(w), cy: y(v), r: 11, class: "hit" }, g);
      const show = () => { tip.textContent = `W${w} · ${opts.format(v)}`; tip.setAttribute("x", Math.min(x(w) + 8, W - 90)); tip.setAttribute("y", Math.max(y(v) - 10, 12)); tip.setAttribute("visibility", "visible"); };
      g.addEventListener("mouseenter", show);
      g.addEventListener("focus", show);
      g.addEventListener("mouseleave", () => tip.setAttribute("visibility", "hidden"));
      if (opts.onPoint) {
        g.addEventListener("click", () => opts.onPoint(w));
        g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); opts.onPoint(w); } });
      }
    });
    svg.appendChild(tip);
    return svg;
  }

  function sparkline(values, cls) {
    const v = values.filter(x => x !== null);
    if (v.length < 2) return "";
    const W = 120, H = 32, lo = Math.min.apply(null, v), hi = Math.max.apply(null, v), span = hi - lo || 1;
    const pts = values.map((x, i) => x === null ? null : [(i / (values.length - 1)) * (W - 4) + 2, H - 3 - ((x - lo) / span) * (H - 6)]).filter(Boolean);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join("");
    const last = pts[pts.length - 1];
    return `<svg viewBox="0 0 ${W} ${H}" class="spark ${cls || ""}" aria-hidden="true"><path d="${d}"/><circle cx="${last[0]}" cy="${last[1]}" r="2.6"/></svg>`;
  }

  root.EHISCharts = { lineChart, sparkline };
})(window);
