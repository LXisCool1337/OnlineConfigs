// Search inside all downloaded reports.

import { api } from "../api.js";
import { t } from "../i18n.js";
import { openPreview } from "../preview.js";
import { button, card, empty, field, info, pageTitle } from "../ui.js";
import { categoryLabel, el, fmtInt } from "../util.js";

export async function render(main, params, query) {
  const q = el("input", { type: "search", class: "search-input big", id: "f-q", placeholder: t("fulltext.placeholder"),
    "aria-label": t("fulltext.placeholder"), value: query.get("q") || "", autofocus: true });
  const company = el("select", { id: "f-lei" }, el("option", { value: "" }, t("fulltext.all_companies")));
  const from = el("input", { type: "number", id: "f-from", min: 1990, max: 2100 });
  const to = el("input", { type: "number", id: "f-to", min: 1990, max: 2100 });
  const infoLine = el("p", { class: "muted small", "aria-live": "polite" });
  const results = el("div");
  const run = async () => {
    const text = q.value.trim();
    if (text.length < 2) return;
    history.replaceState(null, "", "#/search?q=" + encodeURIComponent(text));
    const qs = new URLSearchParams({ q: text });
    if (company.value) qs.set("lei", company.value);
    if (from.value) qs.set("from", from.value);
    if (to.value) qs.set("to", to.value);
    infoLine.textContent = t("fulltext.searching");
    try {
      const data = await api("GET", "/api/fulltext?" + qs.toString());
      renderResults(data);
    } catch (err) {
      infoLine.textContent = err.message;
    }
  };
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });

  function renderResults(data) {
    const groups = new Map();
    for (const hit of data.results) {
      if (!groups.has(hit.id)) groups.set(hit.id, []);
      groups.get(hit.id).push(hit);
    }
    infoLine.textContent = t("fulltext.summary", { hits: fmtInt(data.results.length), docs: fmtInt(groups.size), indexed: fmtInt(data.indexed) })
      + (data.pdftotext ? "" : " " + t("fulltext.no_pdf"));
    if (!groups.size) {
      results.replaceChildren(card(empty(t("fulltext.none_title"), data.indexed ? t("fulltext.none_text") : t("fulltext.empty_index"))));
      return;
    }
    results.replaceChildren(...[...groups.values()].map((hits) => {
      const h = hits[0];
      const doc = { ...h, company: h.company };
      return el("article", { class: "card hit" },
        el("div", { class: "hit-head" },
          el("div", {},
            el("h3", {}, h.company || "NACE " + (h.nace || ""), " · ", categoryLabel(h.category, h.category_label), " ", h.fy_label || h.fiscal_year || ""),
            el("p", { class: "muted small" }, h.title || "")),
          el("div", { class: "actions" },
            el("button", { type: "button", class: "btn tiny", onclick: () => openPreview(doc, hits[0].page) }, t("common.view")),
            h.lei ? el("a", { class: "btn tiny ghost", href: "#/company/" + h.lei }, t("fulltext.open_company")) : null)),
        hits.map((x) => el("div", { class: "snippet-row" }, snippet(x.snippet),
          x.page ? el("button", { type: "button", class: "link small", onclick: () => openPreview(doc, x.page) }, t("fulltext.page", { n: x.page })) : null)));
    }));
  }

  main.replaceChildren(
    pageTitle(t("fulltext.title"), t("fulltext.subtitle")),
    card(
      el("div", { class: "search-row" }, q, button(t("fulltext.search"), run, "primary")),
      el("div", { class: "form-grid three" },
        field(t("fulltext.company"), company),
        field(t("fulltext.from"), from),
        field(t("fulltext.to"), to)),
      el("details", { class: "tips" }, el("summary", {}, t("fulltext.tips")), el("ul", {},
        ["tip1", "tip2", "tip3", "tip4"].map((k) => el("li", {}, t("fulltext." + k)))), el("p", { class: "muted small" }, t("fulltext.tip_pdf"), " ", info("fulltext")))),
    infoLine, results);

  try {
    const lib = await api("GET", "/api/library");
    company.append(...lib.companies.map((c) => el("option", { value: c.lei }, c.name)));
  } catch (_) { /* offline */ }
  if (q.value) run();
  return null;
}

function snippet(text) {
  const node = el("p", { class: "snippet" });
  const parts = (text || "").split("\u0002");
  node.append(parts[0]);
  for (const part of parts.slice(1)) {
    const [marked, rest] = part.split("\u0003");
    node.append(el("mark", {}, marked), rest || "");
  }
  return node;
}
