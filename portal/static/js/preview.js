// In-page document viewer (PDF and ESEF-XHTML) in a dialog.

import { withToken } from "./api.js";
import { t } from "./i18n.js";
import { $, categoryLabel, el, fmtBytes } from "./util.js";

const VIEWABLE = new Set(["pdf", "xhtml", "html", "xml"]);

export function canPreview(doc) {
  return VIEWABLE.has(doc.mime || "pdf");
}

export function fileUrl(doc, download = false) {
  return withToken(`/api/documents/${doc.id}/file${download ? "?download=1" : ""}`);
}

export function openPreview(doc, page = null) {
  const dialog = $("#dlg-preview");
  const src = fileUrl(doc) + (page ? `#page=${page}` : "");
  const title = [doc.company, categoryLabel(doc.category, doc.category_label), doc.fy_label || doc.fiscal_year]
    .filter(Boolean).join(" · ");
  const viewer = canPreview(doc)
    ? el("iframe", { class: "viewer", src, title: doc.title || title })
    : el("div", { class: "empty" }, el("p", { class: "empty-title" }, t("preview.none")),
      el("a", { class: "btn primary", href: fileUrl(doc, true) }, t("preview.download")));
  dialog.replaceChildren(el("div", { class: "dialog-head" },
    el("div", {}, el("h2", { class: "dialog-title", id: "preview-title" }, title),
      el("p", { class: "muted small" }, [doc.title, doc.size ? fmtBytes(doc.size) : null, page ? t("preview.page", { n: page }) : null]
        .filter(Boolean).join(" · "))),
    el("div", { class: "actions" },
      el("a", { class: "btn ghost small", href: src, target: "_blank", rel: "noopener" }, t("preview.new_tab")),
      el("a", { class: "btn ghost small", href: fileUrl(doc, true) }, t("preview.download")),
      doc.source_url ? el("a", { class: "btn ghost small", href: doc.source_url, target: "_blank", rel: "noopener noreferrer" }, t("preview.source")) : null,
      el("button", { class: "btn primary small", onclick: () => dialog.close() }, t("common.close")))), viewer);
  dialog.setAttribute("aria-labelledby", "preview-title");
  dialog.showModal();
}
