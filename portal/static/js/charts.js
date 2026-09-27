// Inline SVG charts: columns (one series), horizontal bars (ranking with one highlighted row),
// lines (up to four companies) and sparklines. Every chart has a table view elsewhere on the page.

import { el, fmtInt, fmtNum, svg } from "./util.js";

export function niceTicks(lo, hi, count = 4) {
  if (lo === hi) hi = lo + 1;
  const raw = (hi - lo) / Math.max(1, count - 1);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= raw) || 10 * mag;
  const ticks = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 1e-9; v += step) ticks.push(Math.round(v / step) * step);
  if (ticks[ticks.length - 1] < hi) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

// Value shown in charts: money in millions, percentages in points.
export function chartValue(value, unit) {
  if (value === null || value === undefined) return null;
  if (unit === "pct") return value * 100;
  if (unit === "money") return value / 1e6;
  return value;
}

export function fmtChart(value, unit) {
  if (unit === "pct") return fmtNum(value, 1) + " %";
  if (unit === "per_share") return fmtNum(value, 2);
  if (unit === "index") return fmtNum(value, 0);
  return Math.abs(value) >= 1000 ? fmtInt(value) : fmtNum(value, 1);
}

function fmtTick(value, unit) {
  const text = Number.isInteger(value) ? fmtInt(value) : fmtNum(value, 1);
  return unit === "pct" ? text + " %" : text;
}

function barPath(x, y0, y1, w, r) {
  // Rounded data end, square at the baseline.
  const h = Math.abs(y1 - y0);
  r = Math.min(r, h, w / 2);
  if (y1 <= y0) return `M${x},${y0}V${y1 + r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 + r}V${y0}Z`;
  return `M${x},${y0}V${y1 - r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 - r}V${y0}Z`;
}

function tooltip(wrap) {
  return wrap.querySelector(".tooltip") || wrap.appendChild(el("div", { class: "tooltip", hidden: true }));
}

function placeTip(wrap, chart, tip, x, y) {
  const box = chart.getBoundingClientRect();
  const wbox = wrap.getBoundingClientRect();
  const scale = box.width / chart.viewBox.baseVal.width;
  tip.style.left = (box.left - wbox.left + x * scale) + "px";
  tip.style.top = (box.top - wbox.top + y * scale - 8) + "px";
  tip.hidden = false;
}

function hover(wrap, chart, hit, bar, lines, anchor) {
  const tip = tooltip(wrap);
  const show = () => {
    tip.replaceChildren(el("b", {}, lines[0]), el("span", {}, lines[1]));
    placeTip(wrap, chart, tip, anchor[0], anchor[1]);
    chart.classList.add("hovering");
    bar.classList.add("active");
  };
  const hide = () => {
    tip.hidden = true;
    chart.classList.remove("hovering");
    bar.classList.remove("active");
  };
  hit.addEventListener("pointerenter", show);
  hit.addEventListener("pointerleave", hide);
  hit.addEventListener("focus", show);
  hit.addEventListener("blur", hide);
}

// One series over the years. values = {"2019": v, ...} in raw units.
export function columnChart({ title, sub, years, values, unit, width, suffix = "" }) {
  const data = years.map((y) => ({ year: y, v: chartValue(values[String(y)], unit) }));
  const present = data.filter((d) => d.v !== null);
  if (present.length < 2) return null;
  const W = Math.max(260, Math.round(width || 340)), H = 190, M = { t: 22, r: 10, b: 22, l: 46 };
  const ticks = niceTicks(Math.min(0, ...present.map((d) => d.v)), Math.max(0, ...present.map((d) => d.v)), 4);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const pw = W - M.l - M.r, ph = H - M.t - M.b;
  const y = (v) => M.t + ph - ((v - lo) / (hi - lo)) * ph;
  const band = pw / data.length;
  const bw = Math.min(24, band * 0.62);
  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": title });
  for (const tick of ticks) {
    chart.append(svg("line", { x1: M.l, x2: W - M.r, y1: y(tick), y2: y(tick), class: tick === 0 ? "base" : "grid" }));
    chart.append(svg("text", { x: M.l - 6, y: y(tick) + 3, "text-anchor": "end", class: "tick" }, fmtTick(tick, unit)));
  }
  const wrap = el("figure", { class: "chart-wrap" },
    el("figcaption", {}, el("span", { class: "chart-title" }, title), el("span", { class: "chart-sub" }, sub)), chart);
  const last = present[present.length - 1];
  data.forEach((d, i) => {
    const cx = M.l + band * i + band / 2;
    chart.append(svg("text", { x: cx, y: H - 6, "text-anchor": "middle", class: "tick" },
      band >= 32 ? String(d.year) : "’" + String(d.year).slice(2)));
    if (d.v === null) return;
    const bar = svg("path", { d: barPath(cx - bw / 2, y(0), y(d.v), bw, 4), class: "bar" });
    chart.append(bar);
    if (d === last) {
      chart.append(svg("text", { x: cx, y: d.v >= 0 ? y(d.v) - 5 : y(d.v) + 13, "text-anchor": "middle", class: "value" },
        fmtChart(d.v, unit)));
    }
    const label = fmtChart(d.v, unit) + suffix;
    const hit = svg("rect", { x: M.l + band * i, y: M.t, width: band, height: ph, class: "hit", tabindex: 0,
      "aria-label": d.year + ": " + label });
    chart.append(hit);
    hover(wrap, chart, hit, bar, [label, String(d.year)], [cx, Math.min(y(d.v), y(0))]);
  });
  return wrap;
}

// Ranking: rows = [{label, value, focus, note}], value already in chart units.
export function hbarChart({ rows, unit, width, median, medianLabel, ariaLabel }) {
  const W = Math.max(300, Math.round(width || 680));
  const rowH = 30, labelW = Math.min(230, Math.round(W * 0.34)), M = { t: 24, r: 70, b: 8 };
  const H = M.t + rows.length * rowH + M.b;
  const values = rows.map((r) => r.value);
  const ticks = niceTicks(Math.min(0, ...values), Math.max(0, ...values), 4);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const x = (v) => labelW + ((v - lo) / (hi - lo)) * (W - labelW - M.r);
  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": ariaLabel || "" });
  for (const tick of ticks) chart.append(svg("line", { x1: x(tick), x2: x(tick), y1: M.t - 4, y2: H - M.b, class: tick === 0 ? "base" : "grid" }));
  const wrap = el("div", { class: "chart-wrap" }, chart);
  const anyFocus = rows.some((r) => r.focus);
  const maxChars = Math.max(10, Math.floor(labelW / 7.4));
  rows.forEach((r, i) => {
    const cy = M.t + i * rowH + rowH / 2;
    const name = r.label.length > maxChars ? r.label.slice(0, maxChars - 1) + "…" : r.label;
    chart.append(svg("text", { x: labelW - 10, y: cy + 4, "text-anchor": "end", class: r.focus ? "value" : "label" }, name));
    const x0 = x(0), x1 = x(r.value), h = 14, rr = Math.min(4, Math.abs(x1 - x0) / 2);
    const d = r.value >= 0
      ? `M${x0},${cy - h / 2}H${x1 - rr}Q${x1},${cy - h / 2} ${x1},${cy - h / 2 + rr}V${cy + h / 2 - rr}Q${x1},${cy + h / 2} ${x1 - rr},${cy + h / 2}H${x0}Z`
      : `M${x0},${cy - h / 2}H${x1 + rr}Q${x1},${cy - h / 2} ${x1},${cy - h / 2 + rr}V${cy + h / 2 - rr}Q${x1},${cy + h / 2} ${x1 + rr},${cy + h / 2}H${x0}Z`;
    const bar = svg("path", { d, class: "bar" + (r.focus || !anyFocus ? "" : " deemph") });
    chart.append(bar);
    chart.append(svg("text", { x: r.value >= 0 ? x1 + 6 : x1 - 6, y: cy + 4, "text-anchor": r.value >= 0 ? "start" : "end",
      class: "tick" }, fmtChart(r.value, unit)));
    const hit = svg("rect", { x: 0, y: cy - rowH / 2, width: W, height: rowH, class: "hit", tabindex: 0,
      "aria-label": r.label + ": " + fmtChart(r.value, unit) });
    chart.append(hit);
    hover(wrap, chart, hit, bar, [fmtChart(r.value, unit), r.label + (r.note ? " · " + r.note : "")], [x1, cy - h / 2]);
  });
  if (median !== undefined && median !== null) {
    const mx = x(median);
    chart.append(svg("line", { x1: mx, x2: mx, y1: M.t - 8, y2: H - M.b, class: "median" }));
    chart.append(svg("text", { x: mx, y: M.t - 11, "text-anchor": "middle", class: "tick" }, `${medianLabel} ${fmtChart(median, unit)}`));
  }
  return wrap;
}

// Several companies over time. series = [{name, slot (1-4), values: {"2019": v}}], values in chart units.
export function lineChart({ series, years, unit, width, ariaLabel, yLabel }) {
  const W = Math.max(300, Math.round(width || 720)), H = 300;
  const M = { t: 18, r: 20, b: 26, l: 54 };
  const points = series.flatMap((s) => years.map((y) => s.values[String(y)]).filter((v) => v !== null && v !== undefined));
  if (!points.length) return null;
  const ticks = niceTicks(Math.min(unit === "index" ? Math.min(...points) : 0, ...points), Math.max(...points), 5);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  // Room for end labels on the right when they fit.
  const lastPoints = series.map((s) => {
    const idx = years.map((y) => s.values[String(y)]).map((v, i) => (v === null || v === undefined ? -1 : i)).filter((i) => i >= 0);
    const i = idx.length ? idx[idx.length - 1] : -1;
    return { s, i, v: i >= 0 ? s.values[String(years[i])] : null };
  });
  const pw0 = W - M.l - M.r;
  const yPos = (v) => M.t + (H - M.t - M.b) - ((v - lo) / (hi - lo)) * (H - M.t - M.b);
  const ends = lastPoints.filter((p) => p.v !== null).map((p) => ({ ...p, y: yPos(p.v) })).sort((a, b) => a.y - b.y);
  const labelsFit = ends.every((p, i) => i === 0 || p.y - ends[i - 1].y >= 15) && W >= 480;
  const labelW = labelsFit ? Math.min(150, Math.max(...ends.map((p) => p.s.name.length)) * 6.8 + 16) : 0;
  const pw = pw0 - labelW;
  const x = (i) => M.l + (years.length === 1 ? pw / 2 : (i / (years.length - 1)) * pw);
  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart line-chart", role: "img", "aria-label": ariaLabel || "", tabindex: 0 });
  for (const tick of ticks) {
    chart.append(svg("line", { x1: M.l, x2: M.l + pw, y1: yPos(tick), y2: yPos(tick), class: tick === 0 && unit !== "index" ? "base" : "grid" }));
    chart.append(svg("text", { x: M.l - 6, y: yPos(tick) + 3, "text-anchor": "end", class: "tick" }, fmtTick(tick, unit === "pct" ? "pct" : "")));
  }
  years.forEach((year, i) => {
    if (years.length <= 12 || i % 2 === 0) chart.append(svg("text", { x: x(i), y: H - 7, "text-anchor": "middle", class: "tick" }, String(year)));
  });
  for (const s of series) {
    let d = "";
    let pen = false;
    years.forEach((year, i) => {
      const v = s.values[String(year)];
      if (v === null || v === undefined) { pen = false; return; }
      d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + yPos(v).toFixed(1);
      pen = true;
    });
    chart.append(svg("path", { d, class: `line s${s.slot}` }));
  }
  for (const p of lastPoints) {
    if (p.v === null) continue;
    chart.append(svg("circle", { cx: x(p.i), cy: yPos(p.v), r: 4, class: `dot s${p.s.slot}` }));
  }
  if (labelsFit) {
    for (const p of ends) chart.append(svg("text", { x: x(p.i) + 10, y: p.y + 4, class: "label" }, p.s.name));
  }
  // Crosshair and one tooltip listing every company at the hovered year.
  const cross = svg("line", { x1: 0, x2: 0, y1: M.t, y2: H - M.b, class: "crosshair", visibility: "hidden" });
  const marks = svg("g", {});
  chart.append(cross, marks);
  const wrap = el("div", { class: "chart-wrap" },
    el("ul", { class: "legend" }, series.map((s) => el("li", {}, el("span", { class: `key s${s.slot}`, "aria-hidden": "true" }), s.name))),
    yLabel ? el("p", { class: "chart-sub" }, yLabel) : null, chart);
  const tip = tooltip(wrap);
  let active = -1;
  const showAt = (i) => {
    active = Math.max(0, Math.min(years.length - 1, i));
    const cx = x(active);
    cross.setAttribute("x1", cx);
    cross.setAttribute("x2", cx);
    cross.setAttribute("visibility", "visible");
    marks.replaceChildren();
    const rows = [];
    for (const s of series) {
      const v = s.values[String(years[active])];
      if (v === null || v === undefined) continue;
      marks.append(svg("circle", { cx, cy: yPos(v), r: 4, class: `dot s${s.slot}` }));
      rows.push({ s, v });
    }
    rows.sort((a, b) => b.v - a.v);
    tip.replaceChildren(el("span", { class: "tip-head" }, String(years[active])),
      ...rows.map((r) => el("div", { class: "tip-row" }, el("span", { class: `key s${r.s.slot}` }), el("b", {}, fmtChart(r.v, unit)),
        el("span", {}, r.s.name))));
    placeTip(wrap, chart, tip, cx, M.t + 10);
  };
  const hide = () => {
    tip.hidden = true;
    cross.setAttribute("visibility", "hidden");
    marks.replaceChildren();
  };
  const hit = svg("rect", { x: M.l, y: M.t, width: pw, height: H - M.t - M.b, class: "hit" });
  chart.append(hit);
  hit.addEventListener("pointermove", (e) => {
    const box = chart.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    showAt(Math.round(((px - M.l) / pw) * (years.length - 1)));
  });
  hit.addEventListener("pointerleave", hide);
  chart.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") { showAt(active < 0 ? 0 : active + 1); e.preventDefault(); }
    if (e.key === "ArrowLeft") { showAt(active < 0 ? years.length - 1 : active - 1); e.preventDefault(); }
    if (e.key === "Escape") hide();
  });
  chart.addEventListener("blur", hide);
  return wrap;
}

// Tiny trend line for stat tiles: de-emphasised line, latest point in the accent colour.
export function sparkline(values, width = 120, height = 30) {
  const pts = values.filter((v) => v !== null && v !== undefined);
  if (pts.length < 2) return null;
  const lo = Math.min(...pts), hi = Math.max(...pts);
  const span = hi - lo || 1;
  const step = width / (values.length - 1);
  let d = "";
  let last = null;
  values.forEach((v, i) => {
    if (v === null || v === undefined) return;
    const px = i * step, py = height - 3 - ((v - lo) / span) * (height - 6);
    d += (d ? "L" : "M") + px.toFixed(1) + "," + py.toFixed(1);
    last = [px, py];
  });
  return svg("svg", { viewBox: `-4 0 ${width + 8} ${height}`, class: "spark", "aria-hidden": "true" },
    svg("path", { d, class: "spark-line" }), svg("circle", { cx: last[0], cy: last[1], r: 3, class: "spark-dot" }));
}
