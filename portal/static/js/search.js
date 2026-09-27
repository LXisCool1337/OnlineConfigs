// Company search box with suggestions (keyboard friendly), used on the start and company pages.

import { api } from "./api.js";
import { countryName, t } from "./i18n.js";
import { tag } from "./ui.js";
import { debounce, el } from "./util.js";

const EXAMPLES = ["Krones", "DE0006335003", "SAP", "ASML", "Nokia"];

export function companySearch({ onSelect, big = false, examples = false, autofocus = false } = {}) {
  const input = el("input", { type: "search", class: "search-input" + (big ? " big" : ""), autocomplete: "off",
    placeholder: t("search.placeholder"), "aria-label": t("search.placeholder"), role: "combobox",
    "aria-expanded": "false", "aria-controls": "search-results", autofocus: autofocus || null });
  const list = el("ul", { class: "suggestions", id: "search-results", role: "listbox", hidden: true });
  const status = el("p", { class: "muted small search-status", "aria-live": "polite" });
  let items = [];
  let active = -1;
  let seq = 0;

  const choose = (company) => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    onSelect(company);
  };

  const highlight = (index) => {
    active = index;
    items.forEach((node, i) => node.setAttribute("aria-selected", String(i === index)));
    if (items[index]) items[index].scrollIntoView({ block: "nearest" });
  };

  const run = debounce(async (q) => {
    const mine = ++seq;
    if (q.length < 2) {
      list.hidden = true;
      status.textContent = "";
      return;
    }
    status.textContent = t("search.searching");
    try {
      const data = await api("GET", "/api/search?q=" + encodeURIComponent(q));
      if (mine !== seq) return;
      status.textContent = data.warning_code ? t("search.warning." + data.warning_code) : "";
      items = data.results.map((c, i) => {
        const isin = (c.isins || [])[0];
        const node = el("li", { role: "option", id: "sr-" + i, class: "suggestion", "aria-selected": "false",
          onclick: () => choose(c), onpointerenter: () => highlight(i) },
        el("div", { class: "sugg-main" },
          el("span", { class: "sugg-name" }, c.name),
          el("span", { class: "sugg-meta" }, [countryName(c.country), isin ? "ISIN " + isin : null, "LEI " + c.lei].filter(Boolean).join(" · "))),
        el("div", { class: "tags" },
          c.listed ? tag(t("tag.listed"), "ok") : null,
          c.has_esef ? tag("ESEF", "ok") : null,
          c.in_library ? tag(t("tag.in_library", { n: c.in_library })) : null,
          c.country && !c.eu ? tag(t("tag.outside_eu"), "warn") : null));
        return node;
      });
      list.replaceChildren(...(items.length ? items : [el("li", { class: "suggestion none" }, t("search.none"))]));
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      highlight(items.length ? 0 : -1);
    } catch (err) {
      if (mine !== seq) return;
      status.textContent = t("search.failed", { error: err.message });
    }
  }, 280);

  input.addEventListener("input", () => run(input.value.trim()));
  input.addEventListener("keydown", (e) => {
    if (list.hidden || !items.length) return;
    if (e.key === "ArrowDown") { highlight(Math.min(items.length - 1, active + 1)); e.preventDefault(); }
    if (e.key === "ArrowUp") { highlight(Math.max(0, active - 1)); e.preventDefault(); }
    if (e.key === "Enter" && active >= 0) { items[active].click(); e.preventDefault(); }
    if (e.key === "Escape") { list.hidden = true; input.setAttribute("aria-expanded", "false"); }
  });
  input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 180));
  input.addEventListener("focus", () => { if (items.length && input.value.trim().length >= 2) list.hidden = false; });

  const chips = examples ? el("p", { class: "examples" }, el("span", { class: "muted small" }, t("search.examples")),
    EXAMPLES.map((q) => el("button", { type: "button", class: "chip", onclick: () => { input.value = q; input.focus(); run(q); } }, q))) : null;

  return el("div", { class: "search" + (big ? " big" : "") }, el("div", { class: "search-box" }, input, list), status, chips);
}
