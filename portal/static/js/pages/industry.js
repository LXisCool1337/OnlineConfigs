// Industry page: build an industry package and browse it (statistics, studies, associations, peers).

import { api, withToken } from "../api.js";
import { chartValue, hbarChart } from "../charts.js";
import { countryName, lang, t } from "../i18n.js";
import { jobPanel } from "../jobs.js";
import { fileUrl, openPreview } from "../preview.js";
import { button, card, cardHead, checkbox, empty, field, info, linkButton, pageTitle, toast } from "../ui.js";
import { $, categoryLabel, debounce, el, fill, fmtBytes, fmtMetric, metricLabel, store } from "../util.js";
import { loadMeta, naceSelect } from "../meta.js";

const GROUPS = [
  ["statistics", ["statistics"]],
  ["studies", ["study"]],
  ["associations", ["association_report"]],
  ["peers", ["peer_report", "peer_report_package", "peer_report_json"]],
  ["web", ["web_report"]],
];

export async function render(main, params, query) {
  const m = await loadMeta();
  const nace = params[0] ? decodeURIComponent(params[0]) : store.get("last_nace", "");
  const focus = query.get("lei") || (store.get("recent", [])[0] || {}).lei || "";
  const jobBox = el("section", { class: "card job", hidden: true, "aria-live": "polite" });
  const results = el("div");
  let panel = null;
  let redraw = null;

  const division = nace ? nace.slice(0, 2) : "";
  const select = naceSelect(division, "i-nace");
  const code = el("input", { type: "text", id: "i-code", placeholder: "28.29", value: nace.length > 2 ? nace : "" });
  const keywords = el("input", { type: "text", id: "i-keywords", placeholder: t("industry.keywords_ph") });
  const country = el("select", { id: "i-country" }, el("option", { value: "" }, t("industry.eu_only")),
    m.countries.map((c) => el("option", { value: c.code }, countryName(c.code))));
  const peers = el("textarea", { id: "i-peers", rows: 2, placeholder: t("industry.peers_ph") });
  const go = () => {
    const value = code.value.trim() || select.value;
    if (value) location.hash = "#/industry/" + encodeURIComponent(value) + (focus ? "?lei=" + focus : "");
  };
  select.addEventListener("change", () => { code.value = ""; go(); });
  code.addEventListener("change", go);

  const start = button(t("industry.start"), async () => {
    const value = code.value.trim() || select.value;
    if (!value) {
      toast(t("industry.need_nace"), "error");
      select.focus();
      return;
    }
    const jobParams = {
      nace: value, keywords: keywords.value.trim(), country: country.value, peers: peers.value,
      include_industry: {
        statistics: $("#i-stat").checked, studies: $("#i-studies").checked, associations: $("#i-assoc").checked,
        peers: $("#i-peers-on").checked, websearch: $("#i-web").checked,
      },
    };
    const recent = store.get("recent", [])[0];
    if (focus) jobParams.company_lei = focus;
    else if (recent) jobParams.company_lei = recent.lei;
    try {
      const { id } = await api("POST", "/api/jobs", { kind: "industry", params: jobParams });
      if (panel) panel.close();
      panel = jobPanel(jobBox, id, { onDone: () => showResults(value) });
      jobBox.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      toast(err.message, "error");
    }
  }, "primary big");

  main.replaceChildren(
    pageTitle(t("industry.title"), t("industry.subtitle")),
    card(cardHead(t("industry.form_title"), { info: info("industry_package") }),
      el("div", { class: "form-grid" },
        field(t("industry.division"), select, t("industry.division_hint"), "nace"),
        field(t("industry.code"), code, t("industry.code_hint")),
        field(t("industry.keywords"), keywords, t("industry.keywords_hint")),
        field(t("industry.country"), country, t("industry.country_hint"))),
      field(t("industry.peers"), peers, t("industry.peers_hint"), "peers"),
      el("fieldset", { class: "sources" }, el("legend", {}, t("industry.sources")),
        checkbox("i-stat", t("industry.src.stat"), true, t("industry.src.stat_hint")),
        checkbox("i-studies", t("industry.src.studies"), true, t("industry.src.studies_hint")),
        checkbox("i-assoc", t("industry.src.assoc"), true, t("industry.src.assoc_hint")),
        checkbox("i-peers-on", t("industry.src.peers"), true, t("industry.src.peers_hint")),
        checkbox("i-web", t("industry.src.web"), true, t("industry.src.web_hint"))),
      el("div", { class: "row end" }, start)),
    jobBox, results);

  async function showResults(value) {
    let data;
    try {
      data = await api("GET", "/api/industries/" + encodeURIComponent(value));
    } catch (err) {
      results.replaceChildren(card(el("p", { class: "error" }, err.message)));
      return;
    }
    store.set("last_nace", data.nace);
    const label = lang() === "en" ? ((m.nace.find((n) => n.code === data.nace.slice(0, 2)) || {}).en || data.label) : data.label;
    const compareBox = el("div");
    const blocks = GROUPS.map(([key, cats]) => {
      const docs = data.documents.filter((d) => cats.includes(d.category));
      return card(cardHead(t("industry.group." + key), { sub: t("industry.group_sub." + key) }),
        docs.length ? el("ul", { class: "doclist" }, docs.map((d) => el("li", {},
          el("div", { class: "grow" }, el("span", { class: "doc-title" }, d.title || categoryLabel(d.category, d.category_label)),
            el("span", { class: "muted small block" }, [d.fiscal_year, d.meta.peer_name || d.meta.publisher || d.meta.dataset,
              fmtBytes(d.size)].filter(Boolean).join(" · "))),
          el("button", { type: "button", class: "btn tiny", onclick: () => openPreview(d) }, t("common.view")),
          el("a", { class: "icon-link", href: fileUrl(d, true), title: t("common.download"), "aria-label": t("common.download") }, "⬇"),
          el("button", { type: "button", class: "icon-link danger", title: t("doc.wrong_title"), "aria-label": t("doc.wrong_title"),
            onclick: async () => {
              if (!window.confirm(t("doc.wrong_confirm", { title: d.title || d.category }))) return;
              await api("DELETE", `/api/documents/${d.id}?block=1`);
              toast(t("doc.wrong_done_industry"), "ok");
              showResults(value);
            } }, "✕")))) : el("p", { class: "muted small" }, t("industry.group_empty")));
    });
    fill(results,
      el("div", { class: "section-head" }, el("h2", {}, `NACE ${data.nace} – ${label}`),
        data.documents.length ? linkButton(t("industry.zip"), withToken(`/api/industries/${data.nace}/export`), "ghost") : null),
      data.documents.length ? null : card(empty(t("industry.nothing_title"), t("industry.nothing_text"))),
      compareBox, ...blocks, sourcesCard(data, () => showResults(value)));
    redraw = null;
    loadCompare(data.nace, compareBox);
  }

  async function loadCompare(value, box) {
    let cmp;
    try {
      cmp = await api("GET", `/api/industries/${encodeURIComponent(value)}/compare` + (focus ? "?lei=" + focus : ""));
    } catch (_) {
      return;
    }
    const withData = cmp.rows.filter((r) => r.fiscal_year);
    if (withData.length < 2) return;
    // Start with a ratio the highlighted company has (otherwise it would be missing from the chart).
    const ratios = cmp.metrics.filter((x) => x.key !== "revenue").map((x) => x.key);
    const focusRow = withData.find((r) => r.focus);
    let metric = ratios.find((k) => focusRow && focusRow[k] !== undefined && focusRow[k] !== null)
      || ratios.find((k) => withData.some((r) => r[k] !== undefined && r[k] !== null)) || "net_margin";
    const holder = el("div", { class: "chart-holder" });
    const tableBox = el("div", { class: "scroll-x" });
    const metricSelect = el("select", { "aria-label": t("compare.metric") },
      cmp.metrics.filter((x) => x.key !== "revenue").map((x) => el("option", { value: x.key, selected: x.key === metric || null }, metricLabel(x.key, x.label))));
    const draw = () => {
      metric = metricSelect.value;
      const unit = (cmp.metrics.find((x) => x.key === metric) || {}).unit || "pct";
      const rows = cmp.rows.filter((r) => r[metric] !== undefined && r[metric] !== null).sort((a, b) => b[metric] - a[metric])
        .map((r) => ({ label: r.name || r.lei, value: chartValue(r[metric], unit), focus: r.focus, note: `${r.fiscal_year}` }));
      holder.replaceChildren(rows.length ? hbarChart({ rows, unit, width: holder.clientWidth, median: chartValue(cmp.median[metric], unit),
        medianLabel: t("compare.median"), ariaLabel: metricLabel(metric) }) : el("p", { class: "muted" }, t("compare.no_values")));
    };
    metricSelect.addEventListener("change", draw);
    redraw = draw;
    tableBox.replaceChildren(el("table", { class: "data fin" },
      el("thead", {}, el("tr", {}, el("th", { scope: "col" }, t("compare.company")), el("th", { scope: "col" }, t("files.year")),
        cmp.metrics.map((x) => el("th", { scope: "col" }, metricLabel(x.key, x.label))))),
      el("tbody", {}, cmp.rows.map((r) => el("tr", { class: r.focus ? "focus" : "" },
        el("th", { scope: "row" }, `${r.name || r.lei}${r.country ? " (" + r.country + ")" : ""}`), el("td", {}, r.fiscal_year || "–"),
        cmp.metrics.map((x) => el("td", {}, fmtMetric(r[x.key], x.unit) + (x.unit === "money" && r[x.key] !== undefined && r.currency ? " " + r.currency : ""))))))));
    box.replaceChildren(card(cardHead(t("industry.compare_title"), { sub: t("industry.compare_sub"), info: info("peers") }),
      el("div", { class: "toolbar" }, el("label", { class: "field inline" }, el("span", { class: "field-label" }, t("compare.metric")), metricSelect)),
      holder, el("details", { class: "table-details" }, el("summary", {}, t("fig.table")), tableBox)));
    draw();
  }

  const onResize = debounce(() => { if (redraw) redraw(); }, 200);
  window.addEventListener("resize", onResize);
  if (nace) showResults(nace);
  return () => { window.removeEventListener("resize", onResize); if (panel) panel.close(); };
}

function sourcesCard(data, refresh) {
  const name = el("input", { type: "text", placeholder: t("industry.source_name") });
  const url = el("input", { type: "url", placeholder: "https://verband.example/publikationen" });
  const add = button(t("industry.source_add"), async () => {
    if (!/^https?:\/\//i.test(url.value.trim())) {
      toast(t("years.link_invalid"), "error");
      return;
    }
    try {
      await api("POST", `/api/industries/${encodeURIComponent(data.nace)}/sources`, { name: name.value.trim(), url: url.value.trim() });
      toast(t("industry.source_added"), "ok");
      refresh();
    } catch (err) {
      toast(err.message, "error");
    }
  }, "ghost");
  return el("details", { class: "card" },
    el("summary", {}, el("span", { class: "card-title" }, t("industry.sources_title", { n: data.sources.length })),
      el("span", { class: "muted small" }, t("industry.sources_sub"))),
    el("ul", { class: "plain" }, data.sources.map((s) => el("li", {},
      el("div", { class: "grow" }, s.name, " ", el("a", { class: "small", href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.url)),
      el("span", { class: "muted small" }, s.own ? t("industry.own_source") : t("industry.builtin_source"))))),
    el("div", { class: "row" }, name, url, add));
}
