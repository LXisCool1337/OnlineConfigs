"use strict";

// --- helpers -------------------------------------------------------------------------------

const state = { meta: null, company: null, nace: null, token: null, streams: {}, jobDetail: null };
const $ = (sel) => document.querySelector(sel);

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function withToken(url) {
  return state.token ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(state.token) : url;
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (state.token) options.headers.Authorization = "Bearer " + state.token;
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const res = await fetch(path, options);
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) throw new Error((data && data.error) || res.statusText);
  return data;
}

function toast(message, kind) {
  const box = $("#notice");
  box.textContent = message;
  box.style.background = kind === "error" ? "var(--err-bg)" : kind === "ok" ? "var(--ok-bg)" : "";
  box.style.color = kind === "error" ? "var(--err)" : kind === "ok" ? "var(--ok)" : "";
  box.hidden = false;
  clearTimeout(toast.timer);
  if (kind) toast.timer = setTimeout(() => { box.hidden = true; }, 6000);
}

function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + " KB";
  return (bytes / 1024 / 1024).toFixed(1).replace(".", ",") + " MB";
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

const SOURCE_LABELS = {
  esef: "ESEF (filings.xbrl.org)", irsite: "IR-Website", websearch: "Websuche", manual: "manuell",
  eurostat: "Eurostat", openalex: "OpenAlex", curated: "Verband/Behörde",
};
const STATUS_LABELS = {
  queued: ["wartet", ""], running: ["läuft", "warn"], cancelling: ["bricht ab", "warn"], done: ["fertig", "ok"],
  failed: ["Fehler", "err"], cancelled: ["abgebrochen", ""],
};
const KIND_LABELS = { company: "Unternehmen", industry: "Branche", batch: "Stapel", refresh: "Beobachtung", universe: "Universum" };

function statusTag(status) {
  const [label, cls] = STATUS_LABELS[status] || [status, ""];
  return el("span", { class: "tag " + cls }, label);
}

// --- tabs --------------------------------------------------------------------------------

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".tab").forEach((s) => { s.hidden = s.id !== "tab-" + name; });
  if (name === "jobs") loadJobs();
  if (name === "library") loadLibrary();
  if (name === "universe") loadUniverse();
  if (name === "settings") loadSettings();
  if (name === "industry") loadIndustry();
}

// --- company search and detail -----------------------------------------------------------

let searchTimer = null;
function onSearchInput() {
  clearTimeout(searchTimer);
  const q = $("#search").value.trim();
  if (q.length < 2) { $("#results").replaceChildren(); return; }
  searchTimer = setTimeout(() => runSearch(q), 300);
}

async function runSearch(q) {
  const list = $("#results");
  list.replaceChildren(el("li", { class: "muted" }, "Suche …"));
  try {
    const data = await api("GET", "/api/search?q=" + encodeURIComponent(q));
    const warn = $("#search-warning");
    warn.hidden = !data.warning;
    warn.textContent = data.warning || "";
    if (!data.results.length) {
      list.replaceChildren(el("li", { class: "muted" }, "Keine Treffer. Tipp: ISIN oder LEI eingeben."));
      return;
    }
    list.replaceChildren(...data.results.map(resultItem));
  } catch (err) {
    list.replaceChildren(el("li", { class: "muted" }, "Suche fehlgeschlagen: " + err.message));
  }
}

function resultItem(c) {
  const tags = [];
  if (c.listed) tags.push(el("span", { class: "tag ok" }, "börsennotiert"));
  if (c.has_esef) tags.push(el("span", { class: "tag ok" }, "ESEF"));
  if (c.in_library) tags.push(el("span", { class: "tag" }, c.in_library + " Dok."));
  if (c.country && !c.eu) tags.push(el("span", { class: "tag warn" }, "außerhalb EU/EWR"));
  const isin = (c.isins || [])[0];
  const item = el("li", { tabindex: "0", role: "button" },
    el("div", {},
      el("div", { class: "name" }, c.name),
      el("div", { class: "muted small mono" }, [c.country_name || c.country || "?", "LEI " + c.lei, isin ? "ISIN " + isin : null].filter(Boolean).join(" · "))),
    el("div", { class: "tags" }, tags));
  const open = () => selectCompany(c.lei);
  item.addEventListener("click", open);
  item.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  return item;
}

async function selectCompany(lei) {
  try {
    await api("POST", "/api/companies", { lei });
    const data = await api("GET", "/api/companies/" + lei);
    state.company = data.company;
    renderCompany(data);
    $("#results").replaceChildren();
    $("#company-panel").hidden = false;
    const running = (data.jobs || []).find((j) => ["queued", "running", "cancelling"].includes(j.status));
    if (running) watchJob(running.id, $("#c-job"), () => refreshCompany());
  } catch (err) {
    toast("Unternehmen konnte nicht geladen werden: " + err.message, "error");
  }
}

async function refreshCompany() {
  if (!state.company) return;
  renderCompany(await api("GET", "/api/companies/" + state.company.lei));
}

function fillNaceSelect(select, current) {
  const options = [el("option", { value: "" }, "— Branche wählen —")];
  let found = false;
  for (const row of state.meta.nace) {
    options.push(el("option", { value: row.code, selected: row.code === current }, row.code + " – " + row.de));
    if (row.code === current) found = true;
  }
  if (current && !found) options.push(el("option", { value: current, selected: true }, current + " (genauer Code)"));
  select.replaceChildren(...options);
}

function renderCompany(data) {
  const c = data.company;
  $("#c-name").textContent = c.name;
  const ids = ["LEI " + c.lei, c.country ? c.country : null, (c.isins || []).slice(0, 3).map((i) => "ISIN " + i).join(", ")];
  $("#c-ids").textContent = ids.filter(Boolean).join(" · ");
  $("#c-website").value = c.website || "";
  $("#c-ir").value = c.ir_url || "";
  $("#c-keywords").value = c.keywords || "";
  fillNaceSelect($("#c-nace"), c.nace || "");
  $("#c-watch").textContent = c.watch ? "★ Beobachtet" : "☆ Beobachten";
  $("#c-export").href = withToken("/api/companies/" + c.lei + "/export");
  $("#c-export").hidden = !data.documents.length;
  renderCoverage(data.coverage);
  renderDocs($("#c-docs"), $("#c-docs-empty"), data.documents, false);
}

function renderCoverage(cov) {
  const table = $("#c-coverage");
  const head = el("tr", {}, el("th", {}, "Geschäftsjahr"), cov.years.map((y) => el("th", {}, String(y))));
  const row = (label, key) => el("tr", {}, el("td", {}, label),
    cov.rows.map((r) => el("td", {}, el("span", { class: "cell " + (r[key] ? "yes" : "no"), title: r[key] ? "vorhanden" : "fehlt" }, r[key] ? "✓" : "–"))));
  table.replaceChildren(el("thead", {}, head), el("tbody", {}, row("PDF-Bericht", "pdf"), row("ESEF", "esef")));
  $("#c-cov-text").textContent = cov.covered + " von " + cov.target + " Jahren abgedeckt" +
    (cov.missing.length ? " · fehlend: " + cov.missing.join(", ") : "");
}

function renderDocs(table, empty, docs, industry) {
  empty.hidden = docs.length > 0;
  if (!docs.length) { table.replaceChildren(); return; }
  const head = el("tr", {},
    el("th", {}, industry ? "Jahr" : "GJ"), el("th", {}, "Dokument"), el("th", {}, industry ? "Herkunft" : "Sprache"),
    el("th", {}, "Quelle"), el("th", { class: "num" }, "Größe"), el("th", {}, ""));
  const rows = docs.map((d) => {
    const fileUrl = withToken("/api/documents/" + d.id + "/file");
    const origin = industry ? (d.meta.peer_name || d.meta.publisher || d.meta.dataset || "") : (d.language || "").toUpperCase();
    return el("tr", {},
      el("td", {}, d.fy_label || d.fiscal_year || "–"),
      el("td", {}, el("div", {}, d.category_label), el("div", { class: "muted small" }, d.title || "")),
      el("td", {}, origin),
      el("td", {}, el("a", { href: d.source_url, target: "_blank", rel: "noopener noreferrer" }, SOURCE_LABELS[d.source] || d.source)),
      el("td", { class: "num" }, fmtSize(d.size)),
      el("td", {}, el("a", { href: fileUrl, target: "_blank", rel: "noopener" }, "Öffnen"), " · ",
        el("a", { href: fileUrl + (fileUrl.includes("?") ? "&" : "?") + "download=1" }, "Laden")));
  });
  table.replaceChildren(el("thead", {}, head), el("tbody", {}, rows));
}

async function saveCompany() {
  const c = state.company;
  try {
    await api("PATCH", "/api/companies/" + c.lei, {
      website: $("#c-website").value.trim(), ir_url: $("#c-ir").value.trim(),
      nace: $("#c-nace").value, keywords: $("#c-keywords").value.trim(),
    });
    toast("Stammdaten gespeichert", "ok");
    refreshCompany();
  } catch (err) { toast(err.message, "error"); }
}

async function toggleWatch() {
  const c = state.company;
  await api("PATCH", "/api/companies/" + c.lei, { watch: !c.watch });
  state.company.watch = !c.watch;
  $("#c-watch").textContent = state.company.watch ? "★ Beobachtet" : "☆ Beobachten";
}

async function startCompanyJob() {
  const c = state.company;
  const lang = $("#o-lang").value;
  const params = {
    lei: c.lei,
    years: Number($("#o-years").value) || 10,
    languages: lang === "both" ? ["en", "local"] : lang.split(","),
    all_languages: lang === "both",
    esef_formats: $("#o-esef").value.split(","),
    include: {
      esef: $("#o-esef-on").checked, pdf: $("#o-pdf").checked, websearch: $("#o-web").checked,
      sustainability: $("#o-sust").checked, industry: $("#o-industry").checked,
    },
    urls: $("#o-urls").value,
    website: $("#c-website").value.trim(), ir_url: $("#c-ir").value.trim(),
    nace: $("#c-nace").value, keywords: $("#c-keywords").value.trim(),
  };
  try {
    const { id } = await api("POST", "/api/jobs", { kind: "company", params });
    watchJob(id, $("#c-job"), () => refreshCompany());
  } catch (err) { toast(err.message, "error"); }
}

// --- job progress --------------------------------------------------------------------------

function logLine(event) {
  const time = event.ts ? event.ts.slice(11, 19) : "";
  let text = time + "  " + event.message;
  const data = event.data || {};
  if (data.url && event.level !== "ok") text += "\n          " + data.url;
  return el("div", { class: event.level }, text);
}

function watchJob(id, box, onDone) {
  if (state.streams[box.id]) state.streams[box.id].close();
  box.hidden = false;
  const bar = el("div");
  const stage = el("span", { class: "muted small" }, "wartet …");
  const status = el("span", {}, statusTag("queued"));
  const log = el("div", { class: "log", "aria-live": "polite" });
  const cancel = el("button", { class: "ghost", onclick: () => api("POST", "/api/jobs/" + id + "/cancel").catch(() => {}) }, "Abbrechen");
  box.replaceChildren(
    el("div", { class: "row between" }, el("h3", {}, "Auftrag #" + id), el("div", { class: "actions" }, status, cancel)),
    el("div", { class: "progress" }, bar), stage, log);
  let lastEvent = 0;
  let finished = false;
  const update = (job) => {
    bar.style.width = Math.round((job.progress || 0) * 100) + "%";
    stage.textContent = job.stage || "";
    status.replaceChildren(statusTag(job.status));
    if (["done", "failed", "cancelled"].includes(job.status) && !finished) {
      finished = true;
      cancel.hidden = true;
      if (job.error) log.append(el("div", { class: "error" }, job.error));
      if (onDone) onDone(job);
      refreshBadge();
    }
  };
  const append = (event) => {
    if (event.id <= lastEvent) return;
    lastEvent = event.id;
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
    log.append(logLine(event));
    if (atBottom) log.scrollTop = log.scrollHeight;
  };
  const poll = async () => {
    while (!finished) {
      try {
        const data = await api("GET", "/api/jobs/" + id + "?after=" + lastEvent);
        data.events.forEach(append);
        update(data.job);
      } catch (_) { /* retry */ }
      await new Promise((r) => setTimeout(r, 1500));
    }
  };
  if (window.EventSource) {
    const source = new EventSource(withToken("/api/jobs/" + id + "/stream"));
    state.streams[box.id] = source;
    source.addEventListener("log", (e) => append(JSON.parse(e.data)));
    source.addEventListener("job", (e) => update(JSON.parse(e.data)));
    source.addEventListener("end", () => source.close());
    source.onerror = () => { source.close(); if (!finished) poll(); };
  } else {
    poll();
  }
  refreshBadge();
}

async function refreshBadge() {
  try {
    const { jobs } = await api("GET", "/api/jobs");
    const active = jobs.filter((j) => ["queued", "running", "cancelling"].includes(j.status)).length;
    const badge = $("#jobs-badge");
    badge.hidden = active === 0;
    badge.textContent = String(active);
  } catch (_) { /* ignore */ }
}

// --- industry ------------------------------------------------------------------------------

function currentNace() {
  return $("#i-code").value.trim() || $("#i-nace").value;
}

async function loadIndustry() {
  if (!$("#i-nace").options.length) fillNaceSelect($("#i-nace"), state.company && state.company.nace ? state.company.nace.slice(0, 2) : "");
  const nace = currentNace();
  $("#i-export").hidden = true;
  if (!nace) {
    $("#i-title").textContent = "Quellen";
    $("#i-sources").replaceChildren(el("li", { class: "muted" }, "Bitte Branche wählen."));
    renderDocs($("#i-docs"), $("#i-docs-empty"), [], true);
    return;
  }
  try {
    const data = await api("GET", "/api/industries/" + encodeURIComponent(nace));
    state.nace = data.nace;
    $("#i-title").textContent = "Quellen für NACE " + data.nace + " – " + data.label;
    $("#i-sources").replaceChildren(...data.sources.map((s) => el("li", {},
      el("span", {}, s.name + " ", el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", class: "small" }, s.url)),
      el("span", { class: "muted small" }, s.origin))));
    renderDocs($("#i-docs"), $("#i-docs-empty"), data.documents, true);
    $("#i-export").href = withToken("/api/industries/" + data.nace + "/export");
    $("#i-export").hidden = !data.documents.length;
  } catch (err) { toast(err.message, "error"); }
}

async function startIndustryJob() {
  const nace = currentNace();
  if (!nace) { toast("Bitte Branche wählen", "error"); return; }
  const params = {
    nace, keywords: $("#i-keywords").value.trim(), country: $("#i-country").value, peers: $("#i-peers").value,
    include_industry: {
      statistics: $("#i-stat").checked, studies: $("#i-studies").checked, associations: $("#i-assoc").checked,
      peers: $("#i-peers-on").checked, websearch: $("#i-web").checked,
    },
  };
  if (state.company && state.company.nace && state.company.nace.slice(0, 2) === nace.slice(0, 2)) params.company_lei = state.company.lei;
  try {
    const { id } = await api("POST", "/api/jobs", { kind: "industry", params });
    watchJob(id, $("#i-job"), () => loadIndustry());
  } catch (err) { toast(err.message, "error"); }
}

async function addSource() {
  const nace = currentNace();
  const url = $("#i-src-url").value.trim();
  if (!nace || !url) { toast("Branche und URL angeben", "error"); return; }
  try {
    await api("POST", "/api/industries/" + encodeURIComponent(nace) + "/sources", { name: $("#i-src-name").value.trim(), url });
    $("#i-src-url").value = "";
    $("#i-src-name").value = "";
    loadIndustry();
  } catch (err) { toast(err.message, "error"); }
}

// --- jobs, library, universe, settings ----------------------------------------------------------

async function loadJobs() {
  const { jobs } = await api("GET", "/api/jobs");
  const head = el("tr", {}, el("th", {}, "#"), el("th", {}, "Typ"), el("th", {}, "Titel"), el("th", {}, "Status"),
    el("th", { class: "num" }, "Fortschritt"), el("th", {}, "erstellt"));
  const rows = jobs.map((j) => el("tr", { class: "clickable", onclick: () => watchJob(j.id, $("#j-detail"), () => loadJobs()) },
    el("td", {}, j.id), el("td", {}, KIND_LABELS[j.kind] || j.kind), el("td", {}, j.title || ""), el("td", {}, statusTag(j.status)),
    el("td", { class: "num" }, Math.round((j.progress || 0) * 100) + " %"), el("td", {}, fmtDate(j.created_at))));
  $("#j-table").replaceChildren(el("thead", {}, head), el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: 6, class: "muted" }, "Noch keine Aufträge."))));
}

async function loadLibrary() {
  const data = await api("GET", "/api/library");
  const chead = el("tr", {}, el("th", {}, "Unternehmen"), el("th", {}, "Land"), el("th", { class: "num" }, "Jahre"), el("th", { class: "num" }, "Dokumente"));
  const crow = data.companies.map((c) => el("tr", { class: "clickable", onclick: () => { showTab("company"); selectCompany(c.lei); } },
    el("td", {}, c.name), el("td", {}, c.country_name || c.country || ""), el("td", { class: "num" }, c.years), el("td", { class: "num" }, c.documents)));
  $("#l-companies").replaceChildren(el("thead", {}, chead), el("tbody", {}, crow.length ? crow : el("tr", {}, el("td", { colspan: 4, class: "muted" }, "Noch leer."))));
  const ihead = el("tr", {}, el("th", {}, "NACE"), el("th", {}, "Branche"), el("th", { class: "num" }, "Dokumente"), el("th", {}, "zuletzt"));
  const irow = data.industries.map((i) => el("tr", { class: "clickable", onclick: () => { $("#i-code").value = i.nace; showTab("industry"); } },
    el("td", {}, i.nace), el("td", {}, i.label), el("td", { class: "num" }, i.documents), el("td", {}, fmtDate(i.updated_at))));
  $("#l-industries").replaceChildren(el("thead", {}, ihead), el("tbody", {}, irow.length ? irow : el("tr", {}, el("td", { colspan: 4, class: "muted" }, "Noch leer."))));
  $("#l-watch").replaceChildren(...(data.watchlist.length ? data.watchlist.map(resultItem) : [el("li", { class: "muted" }, "Keine beobachteten Unternehmen.")]));
}

async function loadUniverse() {
  const stats = await api("GET", "/api/universe");
  const stat = (value, label) => el("div", { class: "stat" }, el("b", {}, value.toLocaleString("de-DE")), el("span", {}, label));
  $("#u-stats").replaceChildren(stat(stats.companies, "Unternehmen im Katalog"), stat(stats.listed, "börsennotiert"),
    stat(stats.with_esef, "mit ESEF-Berichten"), stat(stats.securities, "Aktien (FIRDS)"));
  const head = el("tr", {}, el("th", {}, "Land"), el("th", { class: "num" }, "börsennotierte Unternehmen"));
  $("#u-countries").replaceChildren(el("thead", {}, head), el("tbody", {}, stats.by_country.map((r) =>
    el("tr", {}, el("td", {}, r.name || r.country || "?"), el("td", { class: "num" }, r.n)))));
  if (!$("#b-countries").children.length) {
    $("#b-countries").replaceChildren(...state.meta.countries.map((c) =>
      el("label", {}, el("input", { type: "checkbox", value: c.code, onchange: estimateBatch }), c.name)));
  }
  estimateBatch();
}

function estimateBatch() {
  const limit = Number($("#b-limit").value) || 0;
  const years = Number($("#b-years").value) || 10;
  const files = limit * years * 2;
  const hours = files / 3600 * 2.5;
  $("#b-estimate").textContent = "Grobe Schätzung: bis zu " + files.toLocaleString("de-DE") + " Dateien, " +
    (hours < 1 ? "unter einer Stunde" : "ca. " + Math.ceil(hours) + " Stunden") + " bei höflicher Drosselung.";
}

async function startBatch() {
  const countries = [...document.querySelectorAll("#b-countries input:checked")].map((i) => i.value);
  const limit = Number($("#b-limit").value) || 25;
  const params = {
    countries, limit, esef_only: $("#b-esef").checked, years: Number($("#b-years").value) || 10,
    include: { pdf: $("#b-pdf").checked, industry: $("#b-industry").checked },
  };
  if (limit > 500) {
    if (!window.confirm(limit + " Unternehmen einreihen? Das kann Tage dauern und viel Speicher belegen.")) return;
    params.confirm_large = true;
  }
  try {
    const { id } = await api("POST", "/api/jobs", { kind: "batch", params });
    toast("Stapelauftrag #" + id + " gestartet – Fortschritt unter „Aufträge“", "ok");
    refreshBadge();
  } catch (err) { toast(err.message, "error"); }
}

async function startUniverse(source) {
  try {
    const { id } = await api("POST", "/api/jobs", { kind: "universe", params: { source } });
    toast("Universum-Aktualisierung #" + id + " gestartet", "ok");
    showTab("jobs");
    watchJob(id, $("#j-detail"), () => loadJobs());
  } catch (err) { toast(err.message, "error"); }
}

const SETTING_KEYS = ["contact_email", "years", "languages", "esef_formats", "search_provider", "brave_api_key", "searxng_url",
  "default_rate", "peers_max", "peer_years", "openalex_max", "curated_max_per_source", "all_languages", "include_sustainability"];

async function loadSettings() {
  const { settings } = await api("GET", "/api/settings");
  for (const key of SETTING_KEYS) {
    const input = $("#s-" + key);
    if (!input) continue;
    const value = settings[key];
    if (input.type === "checkbox") input.checked = Boolean(value);
    else input.value = Array.isArray(value) ? value.join(", ") : (value ?? "");
  }
}

async function saveSettings() {
  const values = {};
  for (const key of SETTING_KEYS) {
    const input = $("#s-" + key);
    if (!input) continue;
    values[key] = input.type === "checkbox" ? input.checked : input.value.trim();
  }
  try {
    await api("PUT", "/api/settings", values);
    toast("Einstellungen gespeichert", "ok");
    checkHealth();
  } catch (err) { toast(err.message, "error"); }
}

async function checkHealth() {
  try {
    const health = await api("GET", "/api/health");
    if (!health.contact_email_set) {
      const box = $("#notice");
      box.replaceChildren("Bitte unter ", el("a", { href: "#", onclick: (e) => { e.preventDefault(); showTab("settings"); } }, "Einstellungen"),
        " eine Kontakt-E-Mail hinterlegen: Wikidata und OpenAlex erwarten sie im User-Agent.");
      box.style.background = "";
      box.style.color = "";
      box.hidden = false;
    } else {
      $("#notice").hidden = true;
    }
  } catch (err) {
    toast("Portal-Server nicht erreichbar: " + err.message, "error");
  }
}

// --- start ---------------------------------------------------------------------------------

async function init() {
  try {
    const params = new URLSearchParams(location.search);
    const token = params.get("token") || sessionStorage.getItem("portal_token");
    if (token) { state.token = token; sessionStorage.setItem("portal_token", token); }
  } catch (_) { /* storage unavailable */ }
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $("#search").addEventListener("input", onSearchInput);
  $("#c-save").addEventListener("click", saveCompany);
  $("#c-watch").addEventListener("click", toggleWatch);
  $("#c-start").addEventListener("click", startCompanyJob);
  $("#i-start").addEventListener("click", startIndustryJob);
  $("#i-nace").addEventListener("change", () => { $("#i-code").value = ""; loadIndustry(); });
  $("#i-code").addEventListener("change", loadIndustry);
  $("#i-src-add").addEventListener("click", addSource);
  $("#j-refresh").addEventListener("click", loadJobs);
  $("#l-refresh").addEventListener("click", async () => {
    const { id } = await api("POST", "/api/jobs", { kind: "refresh", params: {} });
    toast("Aktualisierung #" + id + " gestartet", "ok");
  });
  $("#u-esef").addEventListener("click", () => startUniverse("esef"));
  $("#u-firds").addEventListener("click", () => startUniverse("firds"));
  $("#b-start").addEventListener("click", startBatch);
  $("#b-limit").addEventListener("input", estimateBatch);
  $("#b-years").addEventListener("input", estimateBatch);
  $("#s-save").addEventListener("click", saveSettings);
  try {
    state.meta = await api("GET", "/api/meta");
    $("#i-country").append(...state.meta.countries.map((c) => el("option", { value: c.code }, c.name)));
  } catch (err) {
    toast("Portal-Server nicht erreichbar: " + err.message, "error");
    return;
  }
  checkHealth();
  refreshBadge();
  setInterval(refreshBadge, 10000);
}

document.addEventListener("DOMContentLoaded", init);
