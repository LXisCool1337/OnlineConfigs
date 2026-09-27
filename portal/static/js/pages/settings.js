// Settings, grouped and explained. Language and theme apply at once; the rest is saved on the server.

import { api } from "../api.js";
import { lang, t } from "../i18n.js";
import { applyTheme, getTheme, switchLanguage } from "../prefs.js";
import { sourcesPanel } from "../sources.js";
import { button, card, cardHead, checkbox, field, info, pageTitle, toast } from "../ui.js";
import { el } from "../util.js";

const LANG_PRESETS = { en_local: ["en", "local"], local_en: ["local", "en"], en: ["en"], local: ["local"] };

export async function render(main) {
  let settings;
  let health = {};
  try {
    settings = (await api("GET", "/api/settings")).settings;
    health = await api("GET", "/api/health");
  } catch (err) {
    main.replaceChildren(card(el("p", { class: "error" }, err.message)));
    return null;
  }

  const seg = (name, options, current, onPick) => el("div", { class: "seg", role: "group", "aria-label": name },
    options.map(([value, label]) => el("button", { type: "button", "aria-pressed": String(value === current), onclick: (e) => {
      for (const b of e.currentTarget.parentElement.children) b.setAttribute("aria-pressed", String(b === e.currentTarget));
      onPick(value);
    } }, label)));

  const input = (key, type, attrs = {}) => {
    const node = el("input", { type, id: "s-" + key, ...attrs });
    if (type === "checkbox") node.checked = Boolean(settings[key]);
    else node.value = settings[key] ?? "";
    return node;
  };
  const presetKey = Object.entries(LANG_PRESETS).find(([, v]) => JSON.stringify(v) === JSON.stringify(settings.languages))?.[0] || "en_local";
  const languages = el("select", { id: "s-languages" }, Object.keys(LANG_PRESETS).map((k) =>
    el("option", { value: k, selected: k === presetKey || null }, t("settings.lang_" + k))));
  const provider = el("select", { id: "s-search_provider" }, [["", "settings.search_off"], ["brave", "settings.search_brave"],
    ["searxng", "settings.search_searxng"]].map(([v, k]) => el("option", { value: v, selected: v === settings.search_provider || null }, t(k))));
  const formats = ["report", "package", "json"].map((f) => {
    const box = checkbox("s-fmt-" + f, t("settings.fmt_" + f), (settings.esef_formats || []).includes(f), t("settings.fmt_" + f + "_hint"));
    box.querySelector("input").value = f;
    return box;
  });

  const collect = () => ({
    contact_email: document.getElementById("s-contact_email").value.trim(),
    years: document.getElementById("s-years").value,
    languages: LANG_PRESETS[languages.value],
    all_languages: document.getElementById("s-all_languages").checked,
    include_sustainability: document.getElementById("s-include_sustainability").checked,
    esef_formats: formats.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => i.value),
    search_provider: provider.value,
    brave_api_key: document.getElementById("s-brave_api_key").value.trim(),
    searxng_url: document.getElementById("s-searxng_url").value.trim(),
    peers_max: document.getElementById("s-peers_max").value,
    peer_years: document.getElementById("s-peer_years").value,
    openalex_max: document.getElementById("s-openalex_max").value,
    curated_max_per_source: document.getElementById("s-curated_max_per_source").value,
    auto_refresh_days: document.getElementById("s-auto_refresh_days").value,
    default_rate: document.getElementById("s-default_rate").value,
  });

  const save = async () => {
    const values = collect();
    if (values.contact_email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.contact_email)) {
      toast(t("settings.bad_email"), "error");
      return;
    }
    if (!values.esef_formats.length) values.esef_formats = ["report"];
    try {
      await api("PUT", "/api/settings", values);
      toast(t("settings.saved"), "ok");
      window.dispatchEvent(new CustomEvent("portal:settings"));
    } catch (err) {
      toast(err.message, "error");
    }
  };

  const reindex = button(t("settings.reindex"), async () => {
    try {
      const { id } = await api("POST", "/api/jobs", { kind: "index", params: {} });
      toast(t("settings.reindex_started"), "ok", { label: t("common.show"), run: () => { location.hash = "#/jobs/" + id; } });
    } catch (err) {
      toast(err.message, "error");
    }
  }, "ghost");

  main.replaceChildren(
    pageTitle(t("settings.title"), t("settings.subtitle")),
    card(cardHead(t("settings.display")),
      el("div", { class: "form-grid" },
        group(t("settings.language"), seg(t("settings.language"), [["de", "Deutsch"], ["en", "English"]], lang(), (v) => switchLanguage(v))),
        group(t("settings.theme"), seg(t("settings.theme"), [["system", t("settings.theme_system")], ["light", t("settings.theme_light")],
          ["dark", t("settings.theme_dark")]], getTheme(), (v) => applyTheme(v))))),
    card(cardHead(t("settings.fetch")),
      el("div", { class: "form-grid" },
        field(t("settings.contact_email"), input("contact_email", "email", { placeholder: "name@example.com" }), t("settings.contact_email_hint")),
        field(t("settings.years"), input("years", "number", { min: 1, max: 30 }), t("settings.years_hint")),
        field(t("settings.languages"), languages, t("settings.languages_hint"))),
      el("fieldset", { class: "sources" }, el("legend", {}, t("settings.esef_formats"), info("esef")), formats),
      el("div", { class: "checks" },
        checkboxFor("all_languages", settings, t("settings.all_languages"), t("settings.all_languages_hint")),
        checkboxFor("include_sustainability", settings, t("settings.sustainability"), t("settings.sustainability_hint")))),
    card(cardHead(t("settings.websearch"), { info: info("websearch"), sub: t("settings.websearch_sub") }),
      el("div", { class: "form-grid" },
        field(t("settings.provider"), provider),
        field(t("settings.brave_key"), input("brave_api_key", "password", { autocomplete: "off" }), t("settings.brave_key_hint")),
        field(t("settings.searxng_url"), input("searxng_url", "url", { placeholder: "https://searx.example" }), t("settings.searxng_hint")))),
    card(cardHead(t("settings.industry"), { info: info("industry_package") }),
      el("div", { class: "form-grid" },
        field(t("settings.peers_max"), input("peers_max", "number", { min: 0, max: 100 }), t("settings.peers_max_hint")),
        field(t("settings.peer_years"), input("peer_years", "number", { min: 1, max: 10 }), t("settings.peer_years_hint")),
        field(t("settings.openalex_max"), input("openalex_max", "number", { min: 0, max: 100 }), t("settings.openalex_max_hint")),
        field(t("settings.curated_max"), input("curated_max_per_source", "number", { min: 0, max: 100 }), t("settings.curated_max_hint")))),
    card(cardHead(t("settings.automation")),
      el("div", { class: "form-grid" },
        field(t("settings.auto_refresh"), input("auto_refresh_days", "number", { min: 0, max: 365 }), t("settings.auto_refresh_hint"), "watchlist"),
        field(t("settings.rate"), input("default_rate", "number", { min: 0.2, step: 0.1 }), t("settings.rate_hint"), "robots")),
      el("div", { class: "row" }, reindex, el("span", { class: "muted small" }, health.pdftotext ? t("settings.pdftotext_ok") : t("settings.pdftotext_missing")))),
    card(cardHead(t("sources.title"), { sub: t("sources.sub") }), sourcesPanel()),
    card(cardHead(t("settings.storage")), el("p", {}, t("settings.storage_text"), " ", el("code", {}, health.library_dir || "library/"))),
    el("div", { class: "savebar" }, el("span", { class: "muted small" }, t("settings.save_hint")), button(t("common.save"), save, "primary")));
  return null;
}

// A labelled button group. Not a <label>: clicking the caption must not press the first button.
function group(label, control) {
  return el("div", { class: "field" }, el("span", { class: "field-label" }, label), control);
}

function checkboxFor(key, settings, label, hint) {
  return checkbox("s-" + key, label, Boolean(settings[key]), hint);
}
