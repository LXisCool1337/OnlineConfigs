// Compare up to four companies over time (key figures from their ESEF reports).

import { api, withToken } from "../api.js";
import { chartValue, lineChart } from "../charts.js";
import { countryName, t } from "../i18n.js";
import { card, cardHead, empty, info, linkButton, pageTitle } from "../ui.js";
import { debounce, el, fmtMetric, fmtNum, metricLabel, store } from "../util.js";

const METRICS = ["revenue", "revenue_growth", "ebit_margin", "net_margin", "eps", "ebt", "net_income", "fcf", "fcf_margin",
  "equity_ratio", "roe"];
const UNITS = { revenue: "money", revenue_growth: "pct", ebit_margin: "pct", net_margin: "pct", eps: "per_share", ebt: "money",
  net_income: "money", fcf: "money", fcf_margin: "pct", equity_ratio: "pct", roe: "pct" };
const MAX = 4;

export async function render(main, params, query) {
  let selected = (query.get("leis") || (store.get("compare", []) || []).join(",")).split(",").filter(Boolean).slice(0, MAX);
  const slots = new Map(selected.map((lei, i) => [lei, i + 1]));
  let metric = METRICS.includes(query.get("metric")) ? query.get("metric") : "revenue";
  let mode = query.get("mode") === "index" ? "index" : "abs";
  let library = [];
  let data = null;
  const pickerBox = el("div");
  const chartBox = el("div");
  const snapBox = el("div");
  main.replaceChildren(pageTitle(t("compare.title"), t("compare.subtitle")), pickerBox, chartBox, snapBox);
  try {
    library = (await api("GET", "/api/compare/candidates")).companies;
  } catch (_) { /* offline */ }

  const sync = () => {
    store.set("compare", selected);
    history.replaceState(null, "", `#/compare?leis=${selected.join(",")}&metric=${metric}&mode=${mode}`);
  };
  const freeSlot = () => [1, 2, 3, 4].find((s) => ![...slots.values()].includes(s));
  const load = async () => {
    data = selected.length ? await api("GET", "/api/compare?leis=" + selected.join(",")).catch(() => null) : null;
    renderAll();
  };
  const add = (lei) => {
    if (!lei || selected.length >= MAX || selected.includes(lei)) return;
    selected.push(lei);
    slots.set(lei, freeSlot());
    sync();
    load();
  };
  const remove = (lei) => {
    selected = selected.filter((x) => x !== lei);
    slots.delete(lei);
    sync();
    load();
  };
  const nameOf = (lei) => (data && data.companies.find((c) => c.lei === lei) || library.find((c) => c.lei === lei) || { name: lei }).name;

  function renderPicker() {
    if (!library.length && !selected.length) {
      pickerBox.replaceChildren(card(empty(t("compare.empty_title"), t("compare.empty_text"),
        [linkButton(t("compare.go_company"), "#/company", "primary")])));
      return;
    }
    const options = library.filter((c) => !selected.includes(c.lei));
    const option = (c) => el("option", { value: c.lei }, `${c.name} (${[countryName(c.country), c.latest].filter(Boolean).join(", ")})`);
    const own = options.filter((c) => c.in_library);
    const peers = options.filter((c) => !c.in_library);
    const select = el("select", { "aria-label": t("compare.add"), disabled: selected.length >= MAX || !options.length || null },
      el("option", { value: "" }, selected.length >= MAX ? t("compare.full") : t("compare.add")),
      own.length ? el("optgroup", { label: t("compare.group_library") }, own.map(option)) : null,
      peers.length ? el("optgroup", { label: t("compare.group_peers") }, peers.map(option)) : null);
    select.addEventListener("change", () => add(select.value));
    pickerBox.replaceChildren(card(cardHead(t("compare.pick"), { sub: t("compare.pick_sub") }),
      el("ul", { class: "picks" }, selected.map((lei) => el("li", { class: "pick" },
        el("span", { class: `key s${slots.get(lei)}`, "aria-hidden": "true" }), el("a", { href: "#/company/" + lei }, nameOf(lei)),
        el("button", { type: "button", class: "icon-link", "aria-label": t("compare.remove", { name: nameOf(lei) }), onclick: () => remove(lei) }, "×")))),
      select));
  }

  function renderChart() {
    if (!data || !data.companies.length) {
      chartBox.replaceChildren();
      return;
    }
    const comps = data.companies;
    const unit = UNITS[metric];
    const years = [...new Set(comps.flatMap((c) => c.years))].sort();
    const currencies = new Set(comps.map((c) => c.currency).filter(Boolean));
    const forcedIndex = unit === "money" && currencies.size > 1;
    const effective = forcedIndex ? "index" : mode;
    const raw = comps.map((c) => (c.metrics.find((m) => m.key === metric) || { values: {} }).values);
    let base = null;
    if (effective === "index") base = years.find((y) => raw.every((v) => v[String(y)] !== undefined && v[String(y)] !== null && v[String(y)] > 0));
    const series = comps.map((c, i) => {
      const values = {};
      const own = raw[i];
      const baseYear = base || years.find((y) => own[String(y)] > 0);
      for (const y of years) {
        const v = own[String(y)];
        if (v === undefined || v === null) continue;
        values[String(y)] = effective === "index" ? (baseYear && own[String(baseYear)] > 0 ? (v / own[String(baseYear)]) * 100 : null) : chartValue(v, unit);
      }
      return { name: c.name, slot: slots.get(c.lei) || i + 1, values, lei: c.lei };
    });
    const cur = [...currencies][0] || "";
    const yLabel = effective === "index" ? t("compare.index_label", { year: base || t("compare.first_year") })
      : unit === "money" ? `${t("unit.mio")} ${cur}` : unit === "per_share" ? `${cur} ${t("fig.per_share")}` : "%";
    const metricSelect = el("select", { "aria-label": t("compare.metric") },
      METRICS.map((k) => el("option", { value: k, selected: k === metric || null }, metricLabel(k))));
    metricSelect.addEventListener("change", () => { metric = metricSelect.value; sync(); renderChart(); });
    const modeSwitch = el("div", { class: "seg", role: "group", "aria-label": t("compare.mode") },
      ["abs", "index"].map((m) => el("button", { type: "button", "aria-pressed": String(effective === m), disabled: forcedIndex || null,
        onclick: () => { mode = m; sync(); renderChart(); } }, t("compare.mode_" + m))));
    const holder = el("div", { class: "chart-holder" });
    const tableBox = el("div", { class: "scroll-x" });
    chartBox.replaceChildren(card(
      cardHead(t("compare.chart_title"), { info: info("key_figures"), actions: [
        linkButton(t("fig.xlsx"), withToken("/api/compare/export.xlsx?leis=" + selected.join(",")), "ghost small")] }),
      el("div", { class: "toolbar" }, el("label", { class: "field inline" }, el("span", { class: "field-label" }, t("compare.metric")), metricSelect), modeSwitch),
      forcedIndex ? el("p", { class: "hint-box" }, t("compare.currency_note", { list: [...currencies].join(", ") })) : null,
      holder, el("details", { class: "table-details" }, el("summary", {}, t("fig.table")), tableBox)));
    const chart = lineChart({ series, years, unit: effective === "index" ? "index" : unit, width: holder.clientWidth,
      ariaLabel: metricLabel(metric), yLabel });
    holder.replaceChildren(chart || el("p", { class: "muted" }, t("compare.no_values")));
    tableBox.replaceChildren(el("table", { class: "data fin" },
      el("thead", {}, el("tr", {}, el("th", { scope: "col" }, t("compare.company")), years.map((y) => el("th", { scope: "col" }, String(y))))),
      el("tbody", {}, series.map((s, i) => el("tr", {}, el("th", { scope: "row" }, el("span", { class: `key s${s.slot}`, "aria-hidden": "true" }), " ", s.name),
        years.map((y) => {
          const v = s.values[String(y)];
          if (v === undefined || v === null) return el("td", {}, "–");
          return el("td", {}, effective === "index" ? fmtNum(v, 0) : fmtMetric(raw[i][String(y)], unit));
        }))))));
  }

  function renderSnapshot() {
    if (!data || !data.rows || !data.rows.length) {
      snapBox.replaceChildren();
      return;
    }
    const cols = data.metrics;
    snapBox.replaceChildren(card(cardHead(t("compare.snapshot"), { sub: t("compare.snapshot_sub") }),
      el("div", { class: "scroll-x" }, el("table", { class: "data fin" },
        el("thead", {}, el("tr", {}, el("th", { scope: "col" }, t("compare.company")), el("th", { scope: "col" }, t("files.year")),
          cols.map((m) => el("th", { scope: "col" }, metricLabel(m.key, m.label) + (m.unit === "money" ? ` (${t("unit.mio")})` : ""))))),
        el("tbody", {}, data.rows.map((r) => el("tr", {},
          el("th", { scope: "row" }, el("span", { class: `key s${slots.get(r.lei) || 1}`, "aria-hidden": "true" }), " ", r.name),
          el("td", {}, r.fiscal_year || "–"),
          cols.map((m) => el("td", {}, fmtMetric(r[m.key], m.unit) + (m.unit === "money" && r[m.key] !== undefined && r.currency ? " " + r.currency : ""))))),
        el("tr", { class: "median" }, el("th", { scope: "row" }, t("compare.median")), el("td", {}, ""),
          cols.map((m) => el("td", {}, data.median[m.key] !== undefined ? fmtMetric(data.median[m.key], m.unit) : "")))))),
      el("p", { class: "muted small" }, t("compare.snapshot_note"))));
  }

  function renderAll() {
    renderPicker();
    renderChart();
    renderSnapshot();
  }

  const onResize = debounce(renderChart, 200);
  window.addEventListener("resize", onResize);
  await load();
  return () => window.removeEventListener("resize", onResize);
}
