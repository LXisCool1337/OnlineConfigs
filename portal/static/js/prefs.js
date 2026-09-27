// Per-browser preferences: colour theme and interface language.

import { applyStatic, lang, setLang } from "./i18n.js";
import { store } from "./util.js";

export function getTheme() {
  return store.get("theme", "system");
}

export function applyTheme(mode = getTheme()) {
  const root = document.documentElement;
  if (mode === "light" || mode === "dark") root.dataset.theme = mode;
  else delete root.dataset.theme;
  store.set("theme", mode);
  window.dispatchEvent(new CustomEvent("portal:theme", { detail: mode }));
}

export function switchLanguage(code) {
  if (code === lang()) return;
  setLang(code);
  applyStatic();
  window.dispatchEvent(new CustomEvent("portal:lang", { detail: code }));
}
