// Library: everything downloaded so far, with coverage at a glance.

import { api } from "../api.js";
import { countryName, t } from "../i18n.js";
import { naceLabel, loadMeta } from "../meta.js";
import { button, card, cardHead, empty, linkButton, pageTitle, toast } from "../ui.js";
import { el, fill, fmtBytes, fmtInt, timeAgo } from "../util.js";

export async function render(main) {
  await loadMeta();
  main.replaceChildren(pageTitle(t("library.title"), t("library.subtitle")), el("p", { class: "muted loading" }, t("common.loading")));
  let data;
  try {
    data = await api("GET", "/api/library");
  } catch (err) {
    main.append(card(el("p", { class: "error" }, err.message)));
    return null;
  }
  const filter = el("input", { type: "search", placeholder: t("library.filter"), "aria-label": t("library.filter") });
  const sort = el("select", { "aria-label": t("library.sort") },
    ["name", "coverage", "updated", "size"].map((k) => el("option", { value: k }, t("library.sort_" + k))));
  const tbody = el("tbody");
  const draw = () => {
    const q = filter.value.trim().toLowerCase();
    const rows = data.companies.filter((c) => !q || c.name.toLowerCase().includes(q) || (c.isins || []).join(" ").toLowerCase().includes(q))
      .sort({
        name: (a, b) => a.name.localeCompare(b.name),
        coverage: (a, b) => a.covered / a.target - b.covered / b.target,
        updated: (a, b) => String(b.last_update).localeCompare(String(a.last_update)),
        size: (a, b) => b.bytes - a.bytes,
      }[sort.value]);
    tbody.replaceChildren(...rows.map((c) => el("tr", {},
      el("th", { scope: "row" }, el("a", { href: "#/company/" + c.lei }, c.name), c.watch ? el("span", { class: "star", title: t("company.watching") }, " ★") : null),
      el("td", {}, countryName(c.country)),
      el("td", {}, meter(c.covered, c.target)),
      el("td", {}, c.has_financials ? "✓" : "–"),
      el("td", { class: "num" }, fmtInt(c.documents)),
      el("td", { class: "num" }, fmtBytes(c.bytes)),
      el("td", { class: "muted small" }, timeAgo(c.last_update)))));
  };
  filter.addEventListener("input", draw);
  sort.addEventListener("change", draw);
  draw();
  const companies = data.companies.length
    ? card(cardHead(t("library.companies", { n: data.companies.length }), {
      actions: [button(t("library.refresh_watch"), async () => {
        try {
          const { id } = await api("POST", "/api/jobs", { kind: "refresh", params: {} });
          toast(t("library.refresh_started"), "ok", { label: t("common.show"), run: () => { location.hash = "#/jobs/" + id; } });
        } catch (err) {
          toast(err.message, "error");
        }
      }, "ghost small", { title: t("library.refresh_title") })] }),
    el("div", { class: "toolbar" }, filter, sort),
    el("div", { class: "scroll-x" }, el("table", { class: "data" },
      el("thead", {}, el("tr", {}, [t("library.col_company"), t("library.col_country"), t("library.col_coverage"), t("library.col_figures"),
        t("library.col_docs"), t("library.col_size"), t("library.col_updated")].map((h) => el("th", { scope: "col" }, h)))),
      tbody)))
    : card(empty(t("library.empty_title"), t("library.empty_text"), [linkButton(t("library.go_search"), "#/company", "primary")]));
  const industries = data.industries.length ? card(cardHead(t("library.industries")), el("ul", { class: "plain" },
    data.industries.map((i) => el("li", {},
      el("a", { class: "grow", href: "#/industry/" + i.nace }, `NACE ${i.nace} – ${naceLabel(i.nace) || i.label}`),
      el("span", { class: "muted small" }, t("library.industry_docs", { n: i.documents }) + " · " + timeAgo(i.updated_at)))))) : null;
  fill(main, pageTitle(t("library.title"), t("library.subtitle")), companies, industries);
  return null;
}

function meter(covered, target) {
  const share = target ? covered / target : 0;
  const bar = el("span", { class: "meter-fill" + (share === 1 ? " full" : "") });
  bar.style.width = Math.round(share * 100) + "%";  // CSSOM, allowed by the page's CSP
  return el("div", { class: "meter", title: t("library.coverage_title", { covered, target }) },
    el("span", { class: "meter-track" }, bar), el("span", { class: "meter-text" }, `${covered}/${target}`));
}
