// Shared interface pieces: toasts, info buttons, tags, empty states, cards.

import { t } from "./i18n.js";
import { $, el } from "./util.js";

let helpOpener = null;
export function registerHelp(fn) {
  helpOpener = fn;
}

export function openHelp(anchor) {
  if (helpOpener) helpOpener(anchor);
}

// A small round "?" that opens the help at the matching glossary entry.
export function info(term, labelKey) {
  return el("button", {
    type: "button", class: "info", title: t("help.what_is", { term: t(labelKey || "term." + term) }),
    "aria-label": t("help.what_is", { term: t(labelKey || "term." + term) }), onclick: (e) => {
      e.preventDefault();
      e.stopPropagation();
      openHelp(term);
    },
  }, "?");
}

export function toast(message, kind = "info", action = null) {
  const box = $("#toasts");
  const node = el("div", { class: "toast " + kind, role: kind === "error" ? "alert" : "status" },
    el("span", { class: "toast-icon", "aria-hidden": "true" }, kind === "error" ? "!" : kind === "ok" ? "✓" : "i"),
    el("span", { class: "toast-text" }, message),
    action ? el("button", { class: "link", onclick: () => { action.run(); node.remove(); } }, action.label) : null,
    el("button", { class: "toast-close", "aria-label": t("common.close"), onclick: () => node.remove() }, "×"));
  box.append(node);
  setTimeout(() => node.remove(), kind === "error" ? 9000 : 6000);
}

export function tag(text, kind = "", title = null) {
  return el("span", { class: "tag " + kind, title }, text);
}

export function card(...children) {
  return el("section", { class: "card" }, ...children);
}

export function cardHead(title, options = {}) {
  return el("div", { class: "card-head" },
    el("div", {},
      el(options.level || "h2", { class: "card-title" }, title, options.info || null),
      options.sub ? el("p", { class: "card-sub" }, options.sub) : null),
    options.actions ? el("div", { class: "actions" }, options.actions) : null);
}

export function empty(title, text, actions) {
  return el("div", { class: "empty" },
    el("p", { class: "empty-title" }, title),
    text ? el("p", { class: "muted" }, text) : null,
    actions ? el("div", { class: "actions center" }, actions) : null);
}

export function button(label, onclick, kind = "ghost", attrs = {}) {
  return el("button", { type: "button", class: "btn " + kind, onclick, ...attrs }, label);
}

export function linkButton(label, href, kind = "ghost", attrs = {}) {
  return el("a", { class: "btn " + kind, href, ...attrs }, label);
}

export function field(label, control, hint, infoTerm) {
  return el("label", { class: "field" },
    el("span", { class: "field-label" }, label, infoTerm ? info(infoTerm) : null),
    control,
    hint ? el("span", { class: "hint" }, hint) : null);
}

export function checkbox(id, label, checked, hint) {
  return el("label", { class: "check" },
    el("input", { type: "checkbox", id, checked }),
    el("span", {}, el("span", { class: "check-label" }, label), hint ? el("span", { class: "hint" }, hint) : null));
}

export function pageTitle(title, sub) {
  return el("div", { class: "page-head" }, el("h1", {}, title), sub ? el("p", { class: "page-sub" }, sub) : null);
}

export function statTile(value, label, extra) {
  return el("div", { class: "stat" }, el("span", { class: "stat-label" }, label), el("b", { class: "stat-value" }, value),
    extra || null);
}
