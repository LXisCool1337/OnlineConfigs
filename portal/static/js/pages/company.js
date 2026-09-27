// Company page: profile, one-click loading, key-figure tiles, year-by-year reports, charts, notes, files.

import { api, withToken } from "../api.js";
import { columnChart, sparkline } from "../charts.js";
import { countryName, lang, t } from "../i18n.js";
import { jobPanel } from "../jobs.js";
import { loadMeta, naceSelect } from "../meta.js";
import { fileUrl, openPreview } from "../preview.js";
import { companySearch } from "../search.js";
import { button, card, cardHead, checkbox, empty, field, info, linkButton, pageTitle, tag, toast } from "../ui.js";
import {
  $, categoryLabel, debounce, el, fill, fmtBytes, fmtDate, fmtMetric, fmtMillions, fmtNum, fmtPct, metricLabel, sourceLabel,
  store, timeAgo,
} from "../util.js";

function remember(company) {
  const list = store.get("recent", []).filter((c) => c.lei !== company.lei);
  list.unshift({ lei: company.lei, name: company.name, country: company.country });
  store.set("recent", list.slice(0, 8));
}

export async function render(main, params) {
  await loadMeta().catch(() => null);
  const lei = params[0];
  if (!lei) return renderPicker(main);
  main.replaceChildren(el("p", { class: "muted loading" }, t("common.loading")));
  let data;
  try {
    await api("POST", "/api/companies", { lei });
    data = await api("GET", `/api/companies/${lei}`);
  } catch (err) {
    main.replaceChildren(card(empty(t("company.not_found"), err.message, [linkButton(t("company.back_search"), "#/company", "primary")])));
    return null;
  }
  remember(data.company);
  const view = new CompanyView(main, lei, data);
  view.mount();
  return () => view.destroy();
}

async function renderPicker(main) {
  const recent = store.get("recent", []);
  const libraryBox = el("div");
  fill(main,
    pageTitle(t("company.title"), t("company.subtitle")),
    card(companySearch({ big: true, examples: true, autofocus: true, onSelect: (c) => { location.hash = "#/company/" + c.lei; } })),
    recent.length ? card(cardHead(t("company.recent")), el("ul", { class: "plain" }, recent.map((c) => el("li", {},
      el("a", { class: "grow", href: "#/company/" + c.lei }, c.name), el("span", { class: "muted small" }, countryName(c.country)))))) : null,
    libraryBox);
  try {
    const lib = await api("GET", "/api/library");
    if (lib.companies.length) {
      libraryBox.replaceChildren(card(cardHead(t("company.in_library")), el("ul", { class: "plain" },
        lib.companies.slice(0, 15).map((c) => el("li", {}, el("a", { class: "grow", href: "#/company/" + c.lei }, c.name),
          tag(`${c.covered}/${c.target}`, c.covered === c.target ? "ok" : "warn", t("company.coverage_title")))))));
    }
  } catch (_) { /* offline */ }
  return null;
}

class CompanyView {
  constructor(main, lei, data) {
    this.main = main;
    this.lei = lei;
    this.data = data;
    this.fin = null;
    this.panel = null;
    this.jobBox = el("section", { class: "card job no-print", hidden: true, "aria-live": "polite" });
    this.boxes = {};
  }

  mount() {
    for (const name of ["profile", "load", "kpis", "years", "figures", "notes", "files"]) this.boxes[name] = el("div", { class: "box-" + name });
    this.main.replaceChildren(...Object.values(this.boxes));
    this.renderProfile();
    this.renderLoad();
    this.renderYears();
    this.renderNotes();
    this.renderFiles();
    this.loadFinancials();
    const running = (this.data.jobs || []).find((j) => ["queued", "running", "cancelling"].includes(j.status));
    if (running) this.watch(running.id, false);
    this.onResize = debounce(() => this.renderFigures(), 200);
    window.addEventListener("resize", this.onResize);
  }

  destroy() {
    window.removeEventListener("resize", this.onResize);
    if (this.panel) this.panel.close();
  }

  async reload() {
    this.data = await api("GET", `/api/companies/${this.lei}`);
    this.renderProfile();
    this.renderLoad();
    this.renderYears();
    this.renderFiles();
    await this.loadFinancials();
  }

  get company() {
    return this.data.company;
  }

  // --- profile -------------------------------------------------------------------------------

  renderProfile() {
    const c = this.company;
    const stats = this.data.stats;
    const naceText = c.nace ? `${c.nace} – ${lang() === "en" ? c.nace_label_en : c.nace_label}` : t("company.no_industry");
    const link = (url) => el("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, url.replace(/^https?:\/\//, "").replace(/\/$/, ""));
    const fact = (label, value, term) => el("div", { class: "fact" }, el("dt", {}, label, term ? info(term) : null), el("dd", {}, value));
    const watch = button((c.watch ? "★ " : "☆ ") + t(c.watch ? "company.watching" : "company.watch"), async () => {
      await api("PATCH", `/api/companies/${c.lei}`, { watch: !c.watch });
      c.watch = !c.watch;
      this.renderProfile();
      toast(t(c.watch ? "company.watch_on" : "company.watch_off"), "ok");
    }, "ghost", { "aria-pressed": String(Boolean(c.watch)), title: t("company.watch_title") });
    this.boxes.profile.replaceChildren(el("section", { class: "card profile" },
      el("div", { class: "profile-head" },
        el("div", {},
          el("p", { class: "eyebrow" }, t("company.eyebrow")),
          el("h1", { class: "company-name" }, c.name),
          el("div", { class: "tags" }, c.country ? tag(countryName(c.country)) : null, c.listed ? tag(t("tag.listed"), "ok") : null,
            c.has_esef ? tag("ESEF", "ok") : null)),
        el("div", { class: "actions no-print" }, watch,
          stats.documents ? linkButton(t("company.zip"), withToken(`/api/companies/${c.lei}/export`), "ghost") : null,
          button(t("company.print"), () => window.print(), "ghost"))),
      el("dl", { class: "facts" },
        fact("ISIN", (c.isins || []).join(", ") || "–", "isin"),
        fact("LEI", el("span", { class: "mono" }, c.lei), "lei"),
        fact(t("company.industry"), naceText, "nace"),
        fact(t("company.website"), c.website ? link(c.website) : t("company.unknown")),
        fact(t("company.ir_page"), c.ir_url ? link(c.ir_url) : t("company.auto_detect"), "ir"),
        fact(t("company.library"), stats.documents
          ? t("company.library_value", { n: stats.documents, size: fmtBytes(stats.bytes), when: timeAgo(stats.last_update) })
          : t("company.library_empty"))),
      el("details", { class: "edit no-print" }, el("summary", {}, t("company.edit")), this.editForm())));
  }

  editForm() {
    const c = this.company;
    const website = el("input", { type: "url", value: c.website || "", placeholder: "https://…" });
    const ir = el("input", { type: "url", value: c.ir_url || "", placeholder: "https://…/investor-relations" });
    const nace = naceSelect(c.nace, "e-nace");
    const keywords = el("input", { type: "text", value: c.keywords || "", placeholder: t("company.keywords_ph") });
    const save = button(t("common.save"), async () => {
      try {
        await api("PATCH", `/api/companies/${c.lei}`, { website: website.value.trim(), ir_url: ir.value.trim(), nace: nace.value,
          keywords: keywords.value.trim() });
        toast(t("company.saved"), "ok");
        await this.reload();
      } catch (err) {
        toast(err.message, "error");
      }
    }, "primary");
    return el("div", { class: "form-grid" },
      field(t("company.website"), website, t("company.website_hint")),
      field(t("company.ir_page"), ir, t("company.ir_hint"), "ir"),
      field(t("company.industry"), nace, t("company.industry_hint"), "nace"),
      field(t("company.keywords"), keywords, t("company.keywords_hint")),
      el("div", { class: "form-actions" }, save));
  }

  // --- loading -------------------------------------------------------------------------------

  renderLoad() {
    const c = this.company;
    const has = this.data.stats.documents > 0;
    const years = el("input", { type: "number", id: "o-years", min: 1, max: 30, value: 10 });
    const language = el("select", { id: "o-lang" }, ["en_local", "local_en", "en", "both"].map((v) => el("option", { value: v }, t("load.lang." + v))));
    const formats = el("select", { id: "o-esef" }, [["report,package", "load.esef.report_package"], ["report", "load.esef.report"],
      ["report,package,json", "load.esef.all"]].map(([v, k]) => el("option", { value: v }, t(k))));
    const urls = el("textarea", { id: "o-urls", rows: 3, placeholder: "2017: https://…/geschaeftsbericht-2017.pdf" });
    const industry = checkbox("o-industry", t("load.industry"), true, t("load.industry_hint"));
    const naceSelectBox = naceSelect("", "o-nace");
    this.naceError = el("p", { class: "field-error", role: "alert", hidden: true }, t("load.need_nace"));
    const naceRow = el("div", { class: "inline-field", hidden: Boolean(c.nace) },
      field(t("load.industry_needs_nace"), naceSelectBox, null, "nace"), this.naceError);
    naceSelectBox.addEventListener("change", () => { this.naceError.hidden = true; naceRow.classList.remove("invalid"); });
    this.naceRow = naceRow;
    industry.querySelector("input").addEventListener("change", (e) => { naceRow.hidden = Boolean(c.nace) || !e.target.checked; });
    const start = button(has ? t("load.update") : t("load.start"), () => this.start(), "primary big", { id: "c-start" });
    const advanced = el("details", { class: "advanced" }, el("summary", {}, t("load.advanced")),
      el("div", { class: "form-grid" },
        field(t("load.years"), years, t("load.years_hint")),
        field(t("load.language"), language, t("load.language_hint")),
        field(t("load.esef_formats"), formats, t("load.esef_formats_hint"), "esef")),
      el("fieldset", { class: "sources" }, el("legend", {}, t("load.sources")),
        checkbox("o-src-esef", t("load.src.esef"), true, t("load.src.esef_hint")),
        checkbox("o-src-pdf", t("load.src.pdf"), true, t("load.src.pdf_hint")),
        checkbox("o-src-web", t("load.src.web"), true, t("load.src.web_hint")),
        checkbox("o-src-sust", t("load.src.sust"), false, t("load.src.sust_hint"))),
      field(t("load.urls"), urls, t("load.urls_hint")));
    this.boxes.load.replaceChildren(el("section", { class: "card load no-print" },
      cardHead(t("load.title"), { sub: t("load.explain") }),
      el("div", { class: "load-row" }, start, industry),
      naceRow, advanced), this.jobBox);
  }

  params(overrides = {}) {
    const langChoice = $("#o-lang").value;
    return {
      lei: this.lei,
      years: Number($("#o-years").value) || 10,
      languages: { en_local: ["en", "local"], local_en: ["local", "en"], en: ["en"], both: ["en", "local"] }[langChoice],
      all_languages: langChoice === "both",
      esef_formats: $("#o-esef").value.split(","),
      include: {
        esef: $("#o-src-esef").checked, pdf: $("#o-src-pdf").checked, websearch: $("#o-src-web").checked,
        sustainability: $("#o-src-sust").checked, industry: $("#o-industry").checked,
      },
      urls: $("#o-urls").value,
      nace: this.company.nace || ($("#o-nace") ? $("#o-nace").value : ""),
      ...overrides,
    };
  }

  async start(overrides) {
    const params = this.params(overrides);
    if (params.include.industry && !params.nace) {
      // Say it right at the field instead of a toast that outlives the fix.
      this.naceError.hidden = false;
      this.naceRow.classList.add("invalid");
      $("#o-nace")?.focus();
      return;
    }
    const bad = String(params.urls || "").split("\n").map((l) => l.trim()).filter(Boolean)
      .filter((l) => !/^((19|20)\d{2}\s*[:=]\s*)?https?:\/\/\S+$/i.test(l));
    if (bad.length) {
      toast(t("load.bad_urls", { line: bad[0] }), "error");
      return;
    }
    try {
      const { id } = await api("POST", "/api/jobs", { kind: "company", params });
      this.watch(id, true);
    } catch (err) {
      toast(err.message, "error");
    }
  }

  watch(jobId, scroll) {
    if (this.panel) this.panel.close();
    this.panel = jobPanel(this.jobBox, jobId, {
      onDone: () => this.reload(),
      actions: () => [
        button(t("result.see_years"), () => this.boxes.years.scrollIntoView({ behavior: "smooth" }), "primary small"),
        button(t("result.see_figures"), () => this.boxes.figures.scrollIntoView({ behavior: "smooth" }), "ghost small"),
        linkButton(t("company.zip"), withToken(`/api/companies/${this.lei}/export`), "ghost small"),
      ],
    });
    if (scroll) this.jobBox.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // --- key-figure tiles ----------------------------------------------------------------------

  renderKpis() {
    const f = this.fin;
    if (!f || !f.years.length) {
      this.boxes.kpis.replaceChildren();
      return;
    }
    const m = Object.fromEntries(f.metrics.map((x) => [x.key, x.values]));
    const years = f.years;
    const last = years[years.length - 1];
    const cur = f.currency;
    const val = (key, y) => (m[key] && m[key][String(y)] !== undefined ? m[key][String(y)] : null);
    const series = (key) => years.map((y) => val(key, y));
    const tiles = [];
    // Change against the prior year in percent (kind "pct") or percentage points ("pp"), one decimal.
    // The arrow follows the rounded number, so "0,0" never gets one.
    const delta = (change, kind) => {
      const shown = Math.round(change * 1000) / 10;
      const text = (shown > 0 ? "+" : "") + fmtNum(shown, 1) + (kind === "pp" ? ` ${t("unit.pp")}` : " %");
      return el("span", { class: "delta " + (shown > 0 ? "up" : shown < 0 ? "down" : "") },
        (shown > 0 ? "▲ " : shown < 0 ? "▼ " : "") + `${text} ${t("kpi.vs_prev")}`);
    };
    if (val("revenue", last) !== null) {
      const g = val("revenue_growth", last);
      tiles.push(kpi(t("kpi.revenue", { year: last }), `${fmtMillions(val("revenue", last))} ${t("unit.mio")} ${cur}`,
        g !== null ? delta(g, "pct") : null, sparkline(series("revenue"))));
      const first = years.find((y) => val("revenue", y) !== null && val("revenue", y) > 0);
      if (first !== undefined && first < last) {
        const cagr = Math.pow(val("revenue", last) / val("revenue", first), 1 / (last - first)) - 1;
        tiles.push(kpi(t("kpi.cagr", { from: first, to: last }), fmtPct(cagr, 1, true), el("span", { class: "muted small" }, t("kpi.cagr_hint")), null));
      }
    }
    const marginKey = val("ebit_margin", last) !== null ? "ebit_margin" : val("net_margin", last) !== null ? "net_margin" : null;
    if (marginKey) {
      const now = val(marginKey, last), before = val(marginKey, last - 1);
      tiles.push(kpi(`${metricLabel(marginKey)} ${last}`, fmtPct(now),
        before !== null ? delta(now - before, "pp") : null,
        sparkline(series(marginKey))));
    }
    if (val("eps", last) !== null) {
      const now = val("eps", last), before = val("eps", last - 1);
      tiles.push(kpi(`${metricLabel("eps")} ${last}`, `${fmtNum(now, 2)} ${cur}`,
        before !== null && before > 0 ? delta(now / before - 1, "pct") : null,
        sparkline(series("eps"))));
    } else if (val("equity_ratio", last) !== null) {
      tiles.push(kpi(`${metricLabel("equity_ratio")} ${last}`, fmtPct(val("equity_ratio", last)), null, sparkline(series("equity_ratio"))));
    }
    this.boxes.kpis.replaceChildren(el("section", { class: "kpis", "aria-label": t("kpi.title") }, tiles.slice(0, 4)),
      el("p", { class: "muted small kpi-note" }, t("kpi.note"), " ", info("key_figures")));
  }

  // --- year overview -------------------------------------------------------------------------

  renderYears() {
    const cov = this.data.coverage;
    const docs = this.data.documents;
    const pick = (year, cats) => {
      for (const cat of cats) {
        const doc = docs.find((d) => d.fiscal_year === year && d.category === cat);
        if (doc) return doc;
      }
      return null;
    };
    const cards = cov.years.slice().reverse().map((year) => {
      const pdf = pick(year, ["annual_report", "single_entity_statements"]);
      const esef = pick(year, ["esef_report", "esef_package"]);
      const status = pdf && esef ? "full" : pdf || esef ? "partial" : "missing";
      const label = (pdf || esef || {}).fy_label || String(year);
      return el("article", { class: "year " + status, "aria-label": t("years.aria", { year: label }) },
        el("div", { class: "year-head" }, el("span", { class: "year-label" }, label),
          el("span", { class: "year-state", title: t("years.state." + status) }, status === "missing" ? "!" : "✓")),
        this.slot("PDF", pdf, year),
        this.slot("ESEF", esef, year));
    });
    const missing = cov.missing.length;
    this.boxes.years.replaceChildren(el("section", { class: "card years", id: "years" },
      cardHead(t("years.title", { from: cov.years[0], to: cov.years[cov.years.length - 1] }),
        { sub: t("years.sub", { covered: cov.covered, target: cov.target }), info: info("coverage") }),
      el("p", { class: "legend-line muted small" }, el("b", {}, "PDF"), info("pdf"), " " + t("years.pdf_explain") + " · ",
        el("b", {}, "ESEF"), info("esef"), " " + t("years.esef_explain")),
      el("div", { class: "year-grid" }, cards),
      missing ? el("p", { class: "hint-box" }, t("years.missing_hint"), " ", info("missing_years", "faq.missing_years")) : null));
  }

  slot(kind, doc, year) {
    if (doc) {
      return el("div", { class: "slot has" },
        el("span", { class: "slot-kind" }, kind),
        doc.language ? el("span", { class: "lang" }, doc.language.toUpperCase()) : null,
        el("button", { type: "button", class: "btn tiny", onclick: () => openPreview({ ...doc, company: this.company.name }) }, t("common.view")),
        el("a", { class: "icon-link", href: fileUrl(doc, true), title: t("common.download"), "aria-label": t("common.download") + " " + kind + " " + year }, "⬇"),
        kind === "PDF" ? el("button", { type: "button", class: "icon-link danger", title: t("doc.wrong_title"),
          "aria-label": t("doc.wrong_title"), onclick: () => this.markWrong(doc) }, "✕") : null);
    }
    if (kind === "ESEF" && year < 2020) {
      return el("div", { class: "slot na", title: t("years.no_esef_before") }, el("span", { class: "slot-kind" }, kind),
        el("span", { class: "muted small" }, t("years.not_available")));
    }
    const node = el("div", { class: "slot missing" }, el("span", { class: "slot-kind" }, kind), el("span", { class: "muted small" }, t("years.missing")));
    if (kind === "PDF") {
      node.append(el("button", { type: "button", class: "btn tiny ghost", onclick: () => this.addLink(year, node) }, "+ " + t("years.add_link")));
    }
    return node;
  }

  addLink(year, node) {
    const input = el("input", { type: "url", placeholder: "https://…pdf", "aria-label": t("years.link_for", { year }) });
    const submit = async () => {
      const url = input.value.trim();
      if (!/^https?:\/\/\S+$/i.test(url)) {
        toast(t("years.link_invalid"), "error");
        return;
      }
      await this.start({ urls: `${year}: ${url}`, include: { esef: false, pdf: false, websearch: false, sustainability: false, industry: false } });
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") this.renderYears(); });
    node.replaceChildren(el("span", { class: "slot-kind" }, "PDF"), input,
      el("button", { type: "button", class: "btn tiny", onclick: submit }, t("common.ok")),
      el("button", { type: "button", class: "icon-link", "aria-label": t("common.cancel"), onclick: () => this.renderYears() }, "×"));
    input.focus();
  }

  async markWrong(doc) {
    if (!window.confirm(t("doc.wrong_confirm", { title: doc.title || categoryLabel(doc.category, doc.category_label) }))) return;
    try {
      await api("DELETE", `/api/documents/${doc.id}?block=1`);
      toast(t("doc.wrong_done"), "ok", { label: t("doc.reload_now"), run: () => this.start() });
      await this.reload();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // --- key figures ---------------------------------------------------------------------------

  async loadFinancials() {
    try {
      this.fin = await api("GET", `/api/companies/${this.lei}/financials`);
    } catch (_) {
      this.fin = null;
    }
    this.renderKpis();
    this.renderFigures();
  }

  renderFigures() {
    const f = this.fin;
    const head = cardHead(t("fig.title"), { info: info("key_figures"), sub: f && f.years.length
      ? t("fig.sub", { from: f.years[0], to: f.years[f.years.length - 1], cur: f.currency }) : null,
    actions: f && f.years.length ? [
      linkButton(t("fig.xlsx"), withToken(`/api/companies/${this.lei}/financials.xlsx`), "ghost small"),
      linkButton(t("fig.csv"), withToken(`/api/companies/${this.lei}/financials.csv?style=${lang() === "en" ? "en" : "de"}`), "ghost small"),
      button(t("fig.compare"), () => this.openCompare(), "ghost small"),
      button(t("fig.recalc"), async () => {
        this.fin = await api("POST", `/api/companies/${this.lei}/financials`, {});
        this.renderKpis();
        this.renderFigures();
        toast(t("fig.recalculated"), "ok");
      }, "ghost small")] : null });
    if (!f || !f.years.length) {
      this.boxes.figures.replaceChildren(card(head, empty(t("fig.empty_title"), t("fig.empty_text"))));
      return;
    }
    const grid = el("div", { class: "charts" });
    const table = el("table", { class: "data fin" });
    const section = el("section", { class: "card figures", id: "figures" }, head, grid,
      el("details", { class: "table-details" }, el("summary", {}, t("fig.table")), el("div", { class: "scroll-x" }, table)),
      f.restatements.length ? el("p", { class: "muted small" }, t("fig.restated", {
        list: f.restatements.map((r) => `${metricLabel(r.metric, r.label)} ${r.year}: ${fmtMillions(r.reported)} → ${fmtMillions(r.restated)}`).join("; "),
      }), " ", info("restatement")) : null);
    this.boxes.figures.replaceChildren(section);
    const byKey = Object.fromEntries(f.metrics.map((m) => [m.key, m]));
    const single = window.matchMedia("(max-width: 760px)").matches;
    const width = single ? grid.clientWidth : (grid.clientWidth - 20) / 2;
    const cur = f.currency;
    const slots = [
      [["revenue", `${t("unit.mio")} ${cur}`]],
      [["ebit_margin", t("fig.sub_margin")], ["net_margin", t("fig.sub_net_margin")]],
      [["fcf", `${t("unit.mio")} ${cur} · ${t("fig.sub_fcf")}`], ["eps", `${cur} ${t("fig.per_share")}`]],
      [["equity_ratio", t("fig.sub_equity")], ["revenue_growth", t("fig.sub_growth")]],
    ];
    for (const options of slots) {
      for (const [key, sub] of options) {
        if (!byKey[key]) continue;
        const chart = columnChart({ title: metricLabel(key, byKey[key].label), sub, years: f.years, values: byKey[key].values,
          unit: byKey[key].unit, width, suffix: byKey[key].unit === "money" ? ` ${t("unit.mio")}` : "" });
        if (chart) {
          grid.append(chart);
          break;
        }
      }
    }
    const unitText = (m) => (m.unit === "money" ? ` (${t("unit.mio")} ${cur})` : m.unit === "per_share" ? ` (${cur})` : "");
    table.replaceChildren(
      el("thead", {}, el("tr", {}, el("th", { scope: "col" }, t("fig.metric")), f.years.map((y) => el("th", { scope: "col" }, String(y))))),
      el("tbody", {}, f.metrics.map((m) => el("tr", {}, el("th", { scope: "row" }, metricLabel(m.key, m.label) + unitText(m)),
        f.years.map((y) => el("td", {}, fmtMetric(m.values[String(y)], m.unit)))))));
  }

  // Open the comparison with this company and up to three peers from its industry package.
  async openCompare() {
    let leis = [this.lei];
    if (this.company.nace) {
      try {
        const cmp = await api("GET", `/api/industries/${encodeURIComponent(this.company.nace)}/compare?lei=${this.lei}`);
        leis = leis.concat(cmp.rows.filter((r) => !r.focus && r.fiscal_year).map((r) => r.lei)).slice(0, 4);
      } catch (_) { /* no industry package yet */ }
    }
    location.hash = "#/compare?leis=" + leis.join(",");
  }

  // --- notes and files -----------------------------------------------------------------------

  renderNotes() {
    const notes = this.data.notes || { text: "" };
    const area = el("textarea", { rows: 5, placeholder: t("notes.placeholder"), "aria-label": t("notes.title") });
    area.value = notes.text || "";
    const status = el("span", { class: "muted small", "aria-live": "polite" },
      notes.updated_at ? t("notes.saved_at", { when: fmtDate(notes.updated_at) }) : t("notes.autosave"));
    const save = debounce(async () => {
      try {
        const result = await api("PUT", `/api/companies/${this.lei}/notes`, { text: area.value });
        status.textContent = t("notes.saved_at", { when: fmtDate(result.updated_at) });
      } catch (err) {
        status.textContent = err.message;
      }
    }, 700);
    area.addEventListener("input", () => { status.textContent = t("notes.saving"); save(); });
    this.boxes.notes.replaceChildren(card(cardHead(t("notes.title"), { sub: t("notes.sub") }), area, status));
  }

  renderFiles() {
    const docs = this.data.documents;
    if (!docs.length) {
      this.boxes.files.replaceChildren();
      return;
    }
    const rows = docs.map((d) => el("tr", {},
      el("td", {}, d.fy_label || d.fiscal_year || "–"),
      el("td", {}, el("div", {}, categoryLabel(d.category, d.category_label)), el("div", { class: "muted small" }, d.title || "")),
      el("td", {}, (d.language || "").toUpperCase()),
      el("td", {}, el("a", { href: d.source_url, target: "_blank", rel: "noopener noreferrer" }, sourceLabel(d.source))),
      el("td", { class: "num" }, fmtBytes(d.size)),
      el("td", { class: "nowrap no-print" },
        el("button", { type: "button", class: "btn tiny", onclick: () => openPreview({ ...d, company: this.company.name }) }, t("common.view")), " ",
        el("a", { class: "icon-link", href: fileUrl(d, true), title: t("common.download"), "aria-label": t("common.download") }, "⬇"), " ",
        el("button", { type: "button", class: "icon-link danger", title: t("doc.wrong_title"), "aria-label": t("doc.wrong_title"),
          onclick: () => this.markWrong(d) }, "✕"))));
    this.boxes.files.replaceChildren(el("details", { class: "card files" },
      el("summary", {}, el("span", { class: "card-title" }, t("files.title", { n: docs.length })),
        el("span", { class: "muted small" }, t("files.sub"))),
      el("div", { class: "scroll-x" }, el("table", { class: "data" },
        el("thead", {}, el("tr", {}, [t("files.year"), t("files.doc"), t("files.lang"), t("files.source"), t("files.size"), ""].map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", {}, rows)))));
  }
}

function kpi(label, value, deltaNode, spark) {
  return el("div", { class: "stat kpi" }, el("span", { class: "stat-label" }, label), el("b", { class: "stat-value" }, value),
    deltaNode || null, spark || null);
}
