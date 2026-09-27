// "Check data sources": which of the portal's sources can this machine reach?

import { api } from "./api.js";
import { t } from "./i18n.js";
import { button, info } from "./ui.js";
import { el, fmtInt } from "./util.js";

let lastResult = null;

export function sourcesPanel({ compact = false } = {}) {
  const list = el("ul", { class: "sources-check" + (compact ? " compact" : "") });
  const note = el("p", { class: "muted small" });
  const run = button(t("sources.check"), async () => {
    run.disabled = true;
    run.textContent = t("sources.checking");
    try {
      lastResult = (await api("GET", "/api/diagnostics")).sources;
      render();
    } catch (err) {
      note.textContent = err.message;
    } finally {
      run.disabled = false;
      run.textContent = t("sources.check_again");
    }
  }, "ghost");

  function render() {
    if (!lastResult) {
      list.replaceChildren();
      note.textContent = t("sources.intro");
      return;
    }
    const ok = lastResult.filter((r) => r.code === "ok" || r.code === "http_error").length;
    note.textContent = ok === lastResult.length ? t("sources.all_ok") : t("sources.some_blocked", { ok, total: lastResult.length });
    list.replaceChildren(...lastResult.map((r) => {
      const good = r.code === "ok" || r.code === "http_error";
      return el("li", { class: good ? "ok" : "bad" },
        el("span", { class: "src-icon", "aria-hidden": "true" }, good ? "✓" : "✗"),
        el("span", { class: "src-name" }, t("sources.name." + r.key)),
        el("span", { class: "src-state" }, t("sources.state." + r.code, { status: r.status, ms: fmtInt(r.ms) })),
        compact ? null : el("span", { class: "src-url muted small" }, r.url));
    }));
    if (ok < lastResult.length) list.append(el("li", { class: "hint-row" }, t("sources.blocked_hint"), " ", info("unreachable", "faq.unreachable")));
  }

  render();
  if (lastResult) run.textContent = t("sources.check_again");
  return el("div", { class: "sources-panel" }, el("div", { class: "row" }, run), note, list);
}

export function sourcesChecked() {
  return lastResult;
}
