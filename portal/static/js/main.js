// Entry point: language, theme, header controls and the page router (#/company/<LEI>, #/compare, …).

import { api, initToken } from "./api.js";
import { openHelp } from "./help.js";
import { applyStatic, lang, loadLanguages, t } from "./i18n.js";
import { closeAllPanels, refreshBadge } from "./jobs.js";
import { applyTheme, getTheme, switchLanguage } from "./prefs.js";
import { registerHelp, toast } from "./ui.js";
import { $, $$, el } from "./util.js";
import * as company from "./pages/company.js";
import * as compare from "./pages/compare.js";
import * as fulltext from "./pages/fulltext.js";
import * as industry from "./pages/industry.js";
import * as jobs from "./pages/jobs.js";
import * as library from "./pages/library.js";
import * as settings from "./pages/settings.js";
import * as start from "./pages/start.js";
import * as universe from "./pages/universe.js";

const ROUTES = { start, company, compare, industry, search: fulltext, library, jobs, universe, settings };
let cleanup = null;
let renderSeq = 0;

function parseHash() {
  const [path, query] = (location.hash.replace(/^#/, "") || "/start").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const name = ROUTES[parts[0]] ? parts[0] : "start";
  return { name, params: parts.slice(1), query: new URLSearchParams(query || "") };
}

async function route() {
  const { name, params, query } = parseHash();
  const seq = ++renderSeq;
  if (cleanup) {
    try { cleanup(); } catch (_) { /* ignore */ }
    cleanup = null;
  }
  closeAllPanels();
  for (const link of $$(".nav a")) {
    if (link.dataset.route === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  const main = $("#main");
  main.replaceChildren();
  window.scrollTo(0, 0);
  try {
    const result = await ROUTES[name].render(main, params, query);
    if (seq === renderSeq) cleanup = typeof result === "function" ? result : null;
    else if (typeof result === "function") result();
  } catch (err) {
    console.error(err);
    main.replaceChildren(el("section", { class: "card" }, el("p", { class: "error" }, t("common.page_error", { error: err.message }))));
  }
  const badge = (document.title.match(/^\(\d+\) /) || [""])[0];
  document.title = badge + (name === "start" ? "" : t("nav." + name) + " · ") + "EU-Report-Portal";
  main.focus({ preventScroll: true });
}

async function checkHealth() {
  const banner = $("#banner");
  try {
    const health = await api("GET", "/api/health");
    if (!health.contact_email_set) {
      banner.replaceChildren(el("span", {}, t("banner.contact")), " ",
        el("a", { href: "#/settings" }, t("banner.contact_action")));
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  } catch (err) {
    banner.replaceChildren(t("banner.offline", { error: err.message }));
    banner.hidden = false;
  }
}

function setupHeader() {
  $("#btn-help").addEventListener("click", () => openHelp());
  for (const button of $$("[data-lang]")) button.addEventListener("click", () => switchLanguage(button.dataset.lang));
  $("#btn-theme").addEventListener("click", () => {
    const order = ["system", "light", "dark"];
    applyTheme(order[(order.indexOf(getTheme()) + 1) % order.length]);
  });
  const markLang = () => {
    for (const button of $$("[data-lang]")) button.setAttribute("aria-pressed", String(button.dataset.lang === lang()));
  };
  const markTheme = () => {
    const mode = getTheme();
    const button = $("#btn-theme");
    button.title = t("theme.current", { mode: t("settings.theme_" + mode) });
    button.setAttribute("aria-label", button.title);
    button.dataset.mode = mode;
  };
  markLang();
  markTheme();
  window.addEventListener("portal:lang", () => { markLang(); markTheme(); checkHealth(); route(); });
  window.addEventListener("portal:theme", markTheme);
  window.addEventListener("portal:settings", checkHealth);
  // Printing: open the folded tables so the printout contains every value, then restore.
  let reopened = [];
  window.addEventListener("beforeprint", () => {
    reopened = $$("details.table-details:not([open])");
    for (const node of reopened) node.open = true;
  });
  window.addEventListener("afterprint", () => {
    for (const node of reopened) node.open = false;
    reopened = [];
  });
  // "/" jumps to the search field of the current page.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    const target = e.target;
    if (target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
    const field = $("#main input[type=search]");
    if (field) {
      e.preventDefault();
      field.focus();
    }
  });
}

async function init() {
  initToken();
  applyTheme(getTheme());
  try {
    await loadLanguages();
  } catch (err) {
    document.body.prepend(el("p", { class: "error" }, "Could not load interface texts: " + err.message));
    return;
  }
  applyStatic();
  registerHelp(openHelp);
  setupHeader();
  window.addEventListener("hashchange", route);
  await route();
  checkHealth();
  refreshBadge();
  window.addEventListener("unhandledrejection", (e) => {
    if (e.reason && e.reason.message) toast(e.reason.message, "error");
  });
}

init();
