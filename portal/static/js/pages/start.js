// Start page: search, how it works, setup checklist and what happened recently.

import { api } from "../api.js";
import { t } from "../i18n.js";
import { jobTitle } from "../jobs.js";
import { openPreview } from "../preview.js";
import { companySearch } from "../search.js";
import { sourcesPanel } from "../sources.js";
import { card, cardHead, linkButton, statTile, tag } from "../ui.js";
import { categoryLabel, el, fmtBytes, fmtInt, timeAgo } from "../util.js";

export async function render(main) {
  const hero = el("section", { class: "hero" },
    el("h1", {}, t("start.title")),
    el("p", { class: "hero-sub" }, t("start.subtitle")),
    companySearch({ big: true, examples: true, autofocus: true, onSelect: (c) => { location.hash = "#/company/" + c.lei; } }));
  const how = el("section", { class: "how", "aria-label": t("start.how") },
    [1, 2, 3].map((n) => el("div", { class: "how-step" }, el("span", { class: "how-num", "aria-hidden": "true" }, String(n)),
      el("div", {}, el("h3", {}, t(`start.how${n}.title`)), el("p", {}, t(`start.how${n}.text`))))));
  const setupBox = el("div");
  const dash = el("div");
  main.replaceChildren(hero, how, setupBox, dash);

  let data;
  try {
    data = await api("GET", "/api/overview");
  } catch (err) {
    dash.replaceChildren(card(el("p", { class: "error" }, t("common.server_error", { error: err.message }))));
    return;
  }
  setupBox.replaceChildren(setupCard(data));
  dash.replaceChildren(...dashboard(data));
}

function setupCard(data) {
  const s = data.setup;
  const item = (done, key, action) => el("li", { class: done ? "done" : "" },
    el("span", { class: "check-icon", "aria-hidden": "true" }, done ? "✓" : "○"),
    el("div", {}, el("span", { class: "setup-label" }, t(done ? `setup.${key}_done` : `setup.${key}`)),
      el("span", { class: "hint" }, t(`setup.${key}_hint`))),
    !done && action ? action : null);
  const items = [
    item(s.contact_email, "email", linkButton(t("setup.email_action"), "#/settings", "ghost small")),
    item(s.search, "search", linkButton(t("setup.optional"), "#/settings", "ghost small")),
    item(s.pdftotext, "pdftotext", null),
  ];
  const allDone = s.contact_email && s.search && s.pdftotext;
  return el("details", { class: "card setup", open: !s.contact_email || data.stats.documents === 0 },
    el("summary", {}, el("span", { class: "card-title" }, t("setup.title")),
      el("span", { class: "muted small" }, allDone ? t("setup.all_done") : t("setup.progress", {
        done: [s.contact_email, s.search, s.pdftotext].filter(Boolean).length, total: 3 }))),
    el("ul", { class: "setup-list" }, items),
    el("div", { class: "setup-sources" }, el("h3", {}, t("sources.title")), sourcesPanel({ compact: true })));
}

function dashboard(data) {
  const st = data.stats;
  if (!st.documents) {
    return [card(el("div", { class: "empty" }, el("p", { class: "empty-title" }, t("start.empty_title")),
      el("p", { class: "muted" }, t("start.empty_text"))))];
  }
  const tiles = el("div", { class: "stats" },
    statTile(fmtInt(st.companies), t("stat.companies")), statTile(fmtInt(st.documents), t("stat.documents")),
    statTile(fmtBytes(st.bytes), t("stat.storage")), statTile(fmtInt(st.with_financials), t("stat.with_figures")),
    statTile(fmtInt(st.indexed), t("stat.searchable")));
  const recent = card(cardHead(t("start.recent")), el("ul", { class: "plain" }, data.recent.map((d) => el("li", {},
    el("div", { class: "grow" },
      d.lei && d.scope === "company"
        ? el("a", { href: "#/company/" + d.lei }, d.company || d.lei)
        : el("a", { href: "#/industry/" + (d.nace || "") }, d.company || "NACE " + d.nace),
      el("span", { class: "muted" }, " · " + categoryLabel(d.category) + (d.fy_label || d.fiscal_year ? " " + (d.fy_label || d.fiscal_year) : ""))),
    el("button", { class: "btn ghost small", onclick: () => openPreview(d) }, t("common.view")),
    el("span", { class: "muted small nowrap" }, timeAgo(d.created_at))))));
  const gaps = card(cardHead(t("start.gaps"), { sub: t("start.gaps_sub") }),
    data.gaps.length
      ? el("ul", { class: "plain" }, data.gaps.map((g) => el("li", {},
        el("div", { class: "grow" }, el("a", { href: "#/company/" + g.lei }, g.name),
          el("span", { class: "muted small block" }, t("start.missing", { years: g.missing.join(", ") }))),
        tag(`${g.covered}/${g.target}`, "warn"))))
      : el("p", { class: "muted" }, t("start.no_gaps")));
  const watch = card(cardHead(t("start.watchlist")),
    data.watchlist.length
      ? el("ul", { class: "plain" }, data.watchlist.map((w) => el("li", {},
        el("a", { class: "grow", href: "#/company/" + w.lei }, w.name),
        el("span", { class: "muted small" }, w.latest ? t("start.until", { year: w.latest }) : t("start.nothing_yet")))))
      : el("p", { class: "muted" }, t("start.watch_hint")),
    el("p", { class: "muted small" }, data.auto_refresh.days
      ? t("start.auto_on", { days: data.auto_refresh.days }) : t("start.auto_off")));
  const active = data.active.length ? card(cardHead(t("start.active")), el("ul", { class: "plain" }, data.active.map((j) =>
    el("li", {}, el("a", { class: "grow", href: "#/jobs/" + j.id }, jobTitle(j)),
      el("span", { class: "muted small" }, Math.round((j.progress || 0) * 100) + " %"))))) : null;
  return [tiles, el("div", { class: "grid2 top" }, recent, gaps, watch, active)];
}
