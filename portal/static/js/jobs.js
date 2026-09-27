// Job progress as a readable checklist: which step runs, what was skipped and why, what came out.

import { api, withToken } from "./api.js";
import { t } from "./i18n.js";
import { tag } from "./ui.js";
import { $, el, fmtInt } from "./util.js";

export const STEPS = {
  company: ["resolve", "enrich", "esef", "irsite", "websearch", "select", "download", "analyze", "industry"],
  industry: ["statistics", "studies", "associations", "websearch", "peers", "download", "analyze"],
  universe: ["load", "save", "names"],
  index: ["index", "figures"],
};

const FINISHED = ["done", "failed", "cancelled"];
const open = new Set();

export function closeAllPanels() {
  for (const panel of open) panel.close();
  open.clear();
}

export function kindLabel(kind) {
  return t("job.kind." + kind);
}

export function jobTitle(job) {
  const title = job.title === "auto" ? t("job.auto_refresh") : job.title;
  const params = job.params || {};
  const extra = job.kind === "universe" ? (params.source === "firds" ? "ESMA FIRDS" : "ESEF") : "";
  return [kindLabel(job.kind), title || extra].filter(Boolean).join(" · ");
}

export function statusTag(status) {
  const kinds = { running: "warn", cancelling: "warn", done: "ok", failed: "err" };
  return tag(t("job.status." + status), kinds[status] || "");
}

function stepState(job, events) {
  const keys = STEPS[job.kind] || [];
  const state = Object.fromEntries(keys.map((k) => [k, { status: "pending", warnings: 0, reason: null, sub: null }]));
  let current = null;
  for (const e of events) {
    const data = e.data || {};
    if (e.level === "stage" && data.step && state[data.step]) {
      if (current && current !== data.step && state[current].status === "running") state[current].status = "done";
      current = data.step;
      state[current].status = "running";
      state[current].sub = data.substep || null;  // e.g. "industry.peers" inside a company job
    } else if (data.skipped && data.step && state[data.step]) {
      state[data.step].status = "skipped";
      state[data.step].reason = data.skipped;
    } else if (e.level === "warn" && current) {
      state[current].warnings += 1;
    }
  }
  const params = job.params || {};
  const include = params.include || {};
  if (job.kind === "company" && include.industry === false && state.industry.status === "pending") {
    state.industry.status = "skipped";
    state.industry.reason = "not_selected";
  }
  if (FINISHED.includes(job.status)) {
    for (const key of keys) {
      if (state[key].status === "running") state[key].status = job.status === "done" ? "done" : "failed";
      else if (state[key].status === "pending" && job.status === "done") {
        state[key].status = "skipped";
        state[key].reason = state[key].reason || "not_needed";
      }
    }
  }
  return keys.map((key) => ({ key, ...state[key] }));
}

const ICONS = { pending: "○", running: "", done: "✓", skipped: "–", failed: "✗" };

function checklist(job, events) {
  const steps = stepState(job, events);
  if (!steps.length) return null;
  return el("ol", { class: "steps" }, steps.map((s) => el("li", { class: "step " + s.status },
    el("span", { class: "step-icon", "aria-hidden": "true" }, s.status === "running" ? el("span", { class: "spinner" }) : ICONS[s.status]),
    el("span", { class: "step-text" }, t(`step.${job.kind}.${s.key}`),
      s.status === "skipped" && s.reason ? el("span", { class: "step-note" }, t("skip." + s.reason)) : null,
      s.status === "running" && s.sub ? el("span", { class: "step-note" }, t("step." + s.sub)) : null,
      s.warnings ? el("span", { class: "step-note warn" }, t("job.warnings", { n: s.warnings })) : null),
    el("span", { class: "sr-only" }, t("step.status." + s.status)))));
}

function companySummary(job, actions) {
  const s = job.summary || {};
  const cov = s.coverage;
  if (!cov) return null;
  const complete = cov.covered === cov.target;
  const downloads = s.downloads || {};
  const chips = [
    t("result.files", { n: fmtInt((downloads.ok || 0) + (downloads.exists || 0) + (downloads.duplicate || 0)), new: fmtInt(downloads.ok || 0) }),
    (s.financial_years || []).length ? t("result.figures", { n: s.financial_years.length, from: s.financial_years[0],
      to: s.financial_years[s.financial_years.length - 1] }) : t("result.no_figures"),
    s.indexed && s.indexed.ok ? t("result.indexed", { n: s.indexed.ok }) : null,
    s.industry ? t("result.industry", { n: s.industry.documents, nace: s.industry.nace }) : null,
    downloads.failed ? t("result.failed", { n: downloads.failed }) : null,
  ].filter(Boolean);
  return el("div", { class: "result " + (complete ? "ok" : "warn") },
    el("p", { class: "result-title" }, complete
      ? t("result.complete", { covered: cov.covered, target: cov.target })
      : t("result.partial", { covered: cov.covered, target: cov.target, missing: cov.missing.join(", ") })),
    el("ul", { class: "chips" }, chips.map((c) => el("li", {}, c))),
    !complete ? el("p", { class: "muted small" }, t("result.partial_hint")) : null,
    actions ? el("div", { class: "actions" }, actions) : null);
}

function genericSummary(job) {
  const s = job.summary || {};
  const parts = [];
  if (job.kind === "industry") parts.push(t("result.industry", { n: s.documents || 0, nace: s.nace || "" }));
  if (job.kind === "universe") parts.push(t("result.universe", { n: fmtInt(s.issuers || 0) }));
  if (job.kind === "batch" || job.kind === "refresh") parts.push(t("result.batch", { n: s.enqueued || 0 }));
  if (job.kind === "index") parts.push(t("result.index", { n: (s.indexed && s.indexed.ok) || 0, m: s.financials || 0 }));
  return parts.length ? el("div", { class: "result ok" }, el("p", { class: "result-title" }, parts.join(" · "))) : null;
}

function logLine(event) {
  const data = event.data || {};
  let text = (event.ts || "").slice(11, 19) + "  " + event.message;
  if (data.url && event.level !== "ok") text += "\n          " + data.url;
  return el("div", { class: "log-" + event.level }, text);
}

// Render a live job panel into `box`. options.actions(job) -> buttons shown with the result.
export function jobPanel(box, jobId, options = {}) {
  const panel = { closed: false, source: null, close() { this.closed = true; if (this.source) this.source.close(); } };
  open.add(panel);
  const events = [];
  let job = null;
  let finished = false;
  const header = el("div", { class: "card-head" });
  const bar = el("div", { class: "bar" });
  const body = el("div", { class: "job-body" });
  const logBox = el("div", { class: "log" });
  const details = el("details", { class: "log-details" }, el("summary", {}, t("job.log")), logBox);
  box.hidden = false;
  box.replaceChildren(header, el("div", { class: "progress", role: "progressbar", "aria-label": t("job.progress") }, bar), body, details);

  const render = () => {
    if (!job) return;
    const running = !FINISHED.includes(job.status);
    header.replaceChildren(
      el("div", {}, el("h3", { class: "card-title" }, jobTitle(job)),
        el("p", { class: "card-sub" }, running ? (job.stage ? t("job.running_hint") : t("job.waiting")) : t("job.finished_hint"))),
      el("div", { class: "actions" }, statusTag(job.status),
        running ? el("button", { class: "btn ghost small", onclick: () => api("POST", `/api/jobs/${job.id}/cancel`).catch(() => {}) }, t("job.cancel")) : null));
    bar.style.width = Math.round((job.progress || 0) * 100) + "%";
    bar.parentElement.setAttribute("aria-valuenow", String(Math.round((job.progress || 0) * 100)));
    const summary = job.status === "done"
      ? (job.kind === "company" ? companySummary(job, options.actions ? options.actions(job) : null) : genericSummary(job))
      : null;
    const error = job.status === "failed" && job.error
      ? el("div", { class: "result err" }, el("p", { class: "result-title" }, t("job.failed")), el("p", { class: "small" }, job.error.split("\n")[0]))
      : null;
    body.replaceChildren(...[summary, error, checklist(job, events)].filter(Boolean));
  };

  const addEvent = (event) => {
    if (events.length && event.id <= events[events.length - 1].id) return;
    events.push(event);
    const atBottom = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 20;
    logBox.append(logLine(event));
    if (atBottom) logBox.scrollTop = logBox.scrollHeight;
  };

  const update = (next) => {
    job = next;
    render();
    if (FINISHED.includes(job.status) && !finished) {
      finished = true;
      if (panel.source) panel.source.close();
      refreshBadge();
      if (options.onDone) options.onDone(job);
    }
  };

  const poll = async () => {
    while (!finished && !panel.closed) {
      try {
        const data = await api("GET", `/api/jobs/${jobId}?after=${events.length ? events[events.length - 1].id : 0}`);
        data.events.forEach(addEvent);
        update(data.job);
      } catch (_) { /* retry */ }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  };

  api("GET", `/api/jobs/${jobId}`).then((data) => {
    data.events.forEach(addEvent);
    update(data.job);
    if (finished || panel.closed) return;
    if (!window.EventSource) return poll();
    const source = new EventSource(withToken(`/api/jobs/${jobId}/stream?after=${events.length ? events[events.length - 1].id : 0}`));
    panel.source = source;
    source.addEventListener("log", (e) => { addEvent(JSON.parse(e.data)); render(); });
    source.addEventListener("job", (e) => update(JSON.parse(e.data)));
    source.addEventListener("end", () => source.close());
    source.onerror = () => { source.close(); if (!finished && !panel.closed) poll(); };
  }).catch(() => poll());
  refreshBadge();
  return panel;
}

let badgeTimer = null;
export async function refreshBadge() {
  clearTimeout(badgeTimer);
  try {
    const { jobs } = await api("GET", "/api/jobs");
    const active = jobs.filter((j) => !FINISHED.includes(j.status)).length;
    const badge = $("#jobs-badge");
    badge.hidden = active === 0;
    badge.textContent = String(active);
    document.title = (active ? `(${active}) ` : "") + document.title.replace(/^\(\d+\) /, "");
    if (active) badgeTimer = setTimeout(refreshBadge, 4000);
  } catch (_) { /* server restarting */ }
}
