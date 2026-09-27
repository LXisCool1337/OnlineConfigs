// All EU stocks: build the local catalogue and run batch downloads.

import { api } from "../api.js";
import { countryName, t } from "../i18n.js";
import { jobPanel } from "../jobs.js";
import { loadMeta } from "../meta.js";
import { button, card, cardHead, checkbox, field, info, pageTitle, statTile, toast } from "../ui.js";
import { el, fill, fmtInt } from "../util.js";

export async function render(main) {
  const meta = await loadMeta();
  const jobBox = el("section", { class: "card job", hidden: true, "aria-live": "polite" });
  const statsBox = el("div");
  let panel = null;

  const startUniverse = async (source) => {
    try {
      const { id } = await api("POST", "/api/jobs", { kind: "universe", params: { source } });
      if (panel) panel.close();
      panel = jobPanel(jobBox, id, { onDone: () => loadStats() });
      jobBox.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      toast(err.message, "error");
    }
  };

  async function loadStats() {
    let stats;
    try {
      stats = await api("GET", "/api/universe");
    } catch (err) {
      statsBox.replaceChildren(card(el("p", { class: "error" }, err.message)));
      return;
    }
    fill(statsBox, el("div", { class: "stats" },
      statTile(fmtInt(stats.companies), t("universe.companies")), statTile(fmtInt(stats.listed), t("universe.listed")),
      statTile(fmtInt(stats.with_esef), t("universe.with_esef")), statTile(fmtInt(stats.securities), t("universe.securities"))),
    stats.by_country.length ? el("details", { class: "card" }, el("summary", {}, el("span", { class: "card-title" }, t("universe.by_country"))),
      el("div", { class: "scroll-x" }, el("table", { class: "data" },
        el("thead", {}, el("tr", {}, el("th", { scope: "col" }, t("universe.country")), el("th", { scope: "col", class: "num" }, t("universe.count")))),
        el("tbody", {}, stats.by_country.map((r) => el("tr", {}, el("td", {}, countryName(r.country) || "?"), el("td", { class: "num" }, fmtInt(r.n)))))))) : null);
  }

  const countries = el("div", { class: "countries" }, meta.countries.map((c) =>
    el("label", { class: "check compact" }, el("input", { type: "checkbox", value: c.code }), el("span", {}, countryName(c.code)))));
  const limit = el("input", { type: "number", id: "b-limit", min: 1, max: 20000, value: 25 });
  const years = el("input", { type: "number", id: "b-years", min: 1, max: 30, value: 10 });
  const estimate = el("p", { class: "muted small" });
  const updateEstimate = () => {
    const n = Number(limit.value) || 0;
    const files = n * (Number(years.value) || 10) * 2;
    const hours = (files / 3600) * 2.5;
    estimate.textContent = t("universe.estimate", { files: fmtInt(files), time: hours < 1 ? t("universe.under_hour") : t("universe.hours", { n: Math.ceil(hours) }) });
  };
  limit.addEventListener("input", updateEstimate);
  years.addEventListener("input", updateEstimate);
  updateEstimate();
  const startBatch = button(t("universe.batch_start"), async () => {
    const chosen = [...countries.querySelectorAll("input:checked")].map((i) => i.value);
    const n = Number(limit.value) || 25;
    const params = { countries: chosen, limit: n, esef_only: document.getElementById("b-esef").checked, years: Number(years.value) || 10,
      include: { pdf: document.getElementById("b-pdf").checked, industry: document.getElementById("b-industry").checked } };
    if (n > 500) {
      if (!window.confirm(t("universe.confirm_large", { n }))) return;
      params.confirm_large = true;
    }
    try {
      const { id } = await api("POST", "/api/jobs", { kind: "batch", params });
      toast(t("universe.batch_started"), "ok", { label: t("common.show"), run: () => { location.hash = "#/jobs/" + id; } });
    } catch (err) {
      toast(err.message, "error");
    }
  }, "primary");

  main.replaceChildren(
    pageTitle(t("universe.title"), t("universe.subtitle")),
    statsBox,
    card(cardHead(t("universe.build"), { sub: t("universe.build_sub"), info: info("universe") }),
      el("div", { class: "options" },
        el("div", { class: "option" }, el("h3", {}, t("universe.esef_title")), el("p", { class: "muted" }, t("universe.esef_text")),
          button(t("universe.esef_button"), () => startUniverse("esef"), "ghost")),
        el("div", { class: "option" }, el("h3", {}, t("universe.firds_title")), el("p", { class: "muted" }, t("universe.firds_text")),
          button(t("universe.firds_button"), () => startUniverse("firds"), "ghost")))),
    jobBox,
    card(cardHead(t("universe.batch"), { sub: t("universe.batch_sub") }),
      el("p", { class: "field-label" }, t("universe.countries")), countries,
      el("div", { class: "form-grid three" },
        field(t("universe.limit"), limit, t("universe.limit_hint")),
        field(t("load.years"), years)),
      el("fieldset", { class: "sources" }, el("legend", {}, t("universe.options")),
        checkbox("b-esef", t("universe.esef_only"), true, t("universe.esef_only_hint")),
        checkbox("b-pdf", t("load.src.pdf"), true, t("universe.pdf_hint")),
        checkbox("b-industry", t("load.industry"), false, t("universe.industry_hint"))),
      estimate, el("div", { class: "row end" }, startBatch)));
  await loadStats();
  return () => { if (panel) panel.close(); };
}
