// Small DOM and formatting helpers shared by all pages.

import { locale, t } from "./i18n.js";

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

// el("div", {class: "x", onclick: fn}, child, "text", [more]) - text is always inserted as text, never HTML.
export function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "value") node.value = value;
    else if (key === "checked") node.checked = Boolean(value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  append(node, children);
  return node;
}

// Like node.replaceChildren(), but skips null/false the way el() does (the DOM would print "null").
export function fill(node, ...children) {
  node.replaceChildren();
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

const SVG_NS = "http://www.w3.org/2000/svg";
export function svg(tag, attrs, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  append(node, children);
  return node;
}

// Per-viewer conveniences only (language, theme, recent companies). Storage may be unavailable.
export const store = {
  get(key, fallback = null) {
    try {
      const raw = localStorage.getItem("portal." + key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (_) {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem("portal." + key, JSON.stringify(value));
    } catch (_) { /* private mode or blocked storage */ }
  },
};

export function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// --- numbers and dates in the interface language --------------------------------------------

export function fmtNum(value, digits = 1) {
  return new Intl.NumberFormat(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

export function fmtInt(value) {
  return new Intl.NumberFormat(locale(), { maximumFractionDigits: 0 }).format(value);
}

export function fmtPct(fraction, digits = 1, signed = false) {
  const text = fmtNum(fraction * 100, digits) + " %";
  return signed && fraction > 0 ? "+" + text : text;
}

// Money in millions: 5.663,8 (below 1,000 with one decimal, above without)
export function fmtMillions(value) {
  const m = value / 1e6;
  return Math.abs(m) >= 1000 ? fmtInt(m) : fmtNum(m, 1);
}

export function fmtMetric(value, unit) {
  if (value === null || value === undefined) return "–";
  if (unit === "pct") return fmtPct(value);
  if (unit === "per_share") return fmtNum(value, 2);
  return fmtMillions(value);
}

export function fmtBytes(bytes) {
  if (!bytes) return "0 KB";
  if (bytes >= 1e9) return fmtNum(bytes / 1e9, 1) + " GB";
  if (bytes >= 1e6) return fmtNum(bytes / 1e6, bytes >= 1e8 ? 0 : 1) + " MB";
  return fmtInt(Math.max(1, bytes / 1e3)) + " KB";
}

export function fmtDate(iso, withTime = true) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(locale(), withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
}

export function timeAgo(iso) {
  if (!iso) return "";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: "auto" });
  if (seconds < 60) return rtf.format(-Math.round(seconds), "second");
  if (seconds < 3600) return rtf.format(-Math.round(seconds / 60), "minute");
  if (seconds < 86400) return rtf.format(-Math.round(seconds / 3600), "hour");
  return rtf.format(-Math.round(seconds / 86400), "day");
}

// Labels that come from the server in German get a translated version when one exists.
export function categoryLabel(category, fallback) {
  const key = "cat." + category;
  const text = t(key);
  return text === key ? (fallback || category) : text;
}

export function metricLabel(key, fallback) {
  const text = t("metric." + key);
  return text === "metric." + key ? (fallback || key) : text;
}

export function sourceLabel(source) {
  const text = t("source." + source);
  return text === "source." + source ? source : text;
}
