// Interface language (German or English). Texts live in /static/i18n/<lang>.json.

import { store } from "./util.js";

const dicts = {};
let current = "de";

export async function loadLanguages() {
  const [de, en] = await Promise.all(["de", "en"].map((code) =>
    fetch(`/static/i18n/${code}.json`).then((r) => r.json())));
  dicts.de = de;
  dicts.en = en;
  const saved = store.get("lang");
  const guess = (navigator.language || "de").toLowerCase().startsWith("de") ? "de" : "en";
  setLang(saved === "de" || saved === "en" ? saved : guess);
}

export function setLang(code) {
  current = code === "en" ? "en" : "de";
  document.documentElement.lang = current;
  store.set("lang", current);
}

export function lang() {
  return current;
}

export function locale() {
  return current === "en" ? "en-GB" : "de-DE";
}

// t("key", {name: "Krones"}) -> text with {name} replaced; falls back to German, then to the key.
export function t(key, vars) {
  let text = (dicts[current] && dicts[current][key]) ?? (dicts.de && dicts.de[key]) ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) text = text.split(`{${name}}`).join(String(value));
  }
  return text;
}

export function has(key) {
  return Boolean(dicts[current] && key in dicts[current]);
}

// Static markup: data-i18n (text), data-i18n-title, data-i18n-placeholder, data-i18n-aria.
export function applyStatic(root = document) {
  for (const node of root.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const node of root.querySelectorAll("[data-i18n-title]")) node.title = t(node.dataset.i18nTitle);
  for (const node of root.querySelectorAll("[data-i18n-placeholder]")) node.placeholder = t(node.dataset.i18nPlaceholder);
  for (const node of root.querySelectorAll("[data-i18n-aria]")) node.setAttribute("aria-label", t(node.dataset.i18nAria));
}

// Country names in the interface language (browser data), falling back to the ISO code.
export function countryName(code) {
  if (!code) return "";
  try {
    return new Intl.DisplayNames([locale()], { type: "region" }).of(code) || code;
  } catch (_) {
    return code;
  }
}
