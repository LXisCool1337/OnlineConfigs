// Jobs: everything that runs or ran in the background.

import { api } from "../api.js";
import { t } from "../i18n.js";
import { jobPanel, jobTitle, statusTag } from "../jobs.js";
import { card, cardHead, empty, pageTitle, button } from "../ui.js";
import { el, fmtDate } from "../util.js";

export async function render(main, params) {
  const detailBox = el("section", { class: "card job", hidden: true, "aria-live": "polite" });
  const listBox = el("div");
  let panel = null;
  main.replaceChildren(pageTitle(t("jobs.title"), t("jobs.subtitle")), detailBox, listBox);

  const openJob = (id) => {
    if (panel) panel.close();
    panel = jobPanel(detailBox, id, { onDone: () => load() });
  };

  async function load() {
    let jobs = [];
    try {
      jobs = (await api("GET", "/api/jobs")).jobs;
    } catch (err) {
      listBox.replaceChildren(card(el("p", { class: "error" }, err.message)));
      return;
    }
    if (!jobs.length) {
      listBox.replaceChildren(card(empty(t("jobs.empty_title"), t("jobs.empty_text"))));
      return;
    }
    listBox.replaceChildren(card(cardHead(t("jobs.list"), { actions: [button(t("jobs.reload"), load, "ghost small")] }),
      el("div", { class: "scroll-x" }, el("table", { class: "data clickable" },
        el("thead", {}, el("tr", {}, ["#", t("jobs.col_job"), t("jobs.col_status"), t("jobs.col_progress"), t("jobs.col_started")]
          .map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", {}, jobs.map((j) => el("tr", { tabindex: 0, onclick: () => { location.hash = "#/jobs/" + j.id; },
          onkeydown: (e) => { if (e.key === "Enter") location.hash = "#/jobs/" + j.id; } },
        el("td", { class: "num" }, String(j.id)), el("td", {}, jobTitle(j)), el("td", {}, statusTag(j.status)),
        el("td", { class: "num" }, Math.round((j.progress || 0) * 100) + " %"), el("td", { class: "muted small" }, fmtDate(j.created_at)))))))));
  }

  await load();
  if (params[0]) openJob(Number(params[0]));
  return () => { if (panel) panel.close(); };
}
