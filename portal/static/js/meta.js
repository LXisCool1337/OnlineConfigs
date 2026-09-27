// Reference data from the server (NACE industries, countries), loaded once.

import { api } from "./api.js";
import { lang, t } from "./i18n.js";
import { el } from "./util.js";

let cache = null;

export async function loadMeta() {
  if (!cache) {
    try {
      cache = await api("GET", "/api/meta");
    } catch (_) {
      return { nace: [], countries: [], categories: {} };
    }
  }
  return cache;
}

export function naceLabel(code) {
  const row = ((cache && cache.nace) || []).find((n) => n.code === String(code || "").slice(0, 2));
  return row ? (lang() === "en" ? row.en : row.de) : "";
}

export function naceSelect(current, id) {
  const options = [el("option", { value: "" }, t("company.choose_industry"))];
  let found = false;
  for (const row of (cache && cache.nace) || []) {
    options.push(el("option", { value: row.code, selected: row.code === current || null },
      `${row.code} – ${lang() === "en" ? row.en : row.de}`));
    if (row.code === current) found = true;
  }
  if (current && !found) options.push(el("option", { value: current, selected: true }, `${current} (${t("company.fine_code")})`));
  return el("select", { id }, options);
}
