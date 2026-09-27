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
  if (name === "overview") loadOverview();
  if (name === "company" && state.fin && !$("#c-fin").hidden) renderFinancials(state.fin);  // size charts to the now-visible card
  if (name === "fulltext") loadFulltextFilters();
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
  state.company = c;
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
  loadFinancials(c.lei);
}

function renderCoverage(cov) {
  const table = $("#c-coverage");
  const head = el("tr", {}, el("th", {}, "Geschäftsjahr"), cov.years.map((y) => el("th", {}, String(y))));
  const row = (label, key) => el("tr", {}, el("td", {}, label),
    cov.rows.map((r) => el("td", {}, r[key] ? el("span", { class: "cell yes", title: "vorhanden" }, "✓")
      : key === "pdf" ? el("button", { class: "cell add", title: "PDF-Link für " + r.year + " ergänzen", "aria-label": "PDF-Link für " + r.year + " ergänzen", onclick: () => addManualLink(r.year) }, "+")
        : el("span", { class: "cell no", title: "fehlt" }, "–"))));
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
      el("td", { class: "nowrap" }, el("a", { href: fileUrl, target: "_blank", rel: "noopener" }, "Öffnen"), " · ",
        el("a", { href: fileUrl + (fileUrl.includes("?") ? "&" : "?") + "download=1" }, "Laden"), " · ",
        el("button", { class: "link", title: "Dokument löschen und Link künftig überspringen", onclick: () => removeDoc(d, industry) }, "Falsch")));
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
    loadCompare(data.nace);
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

const SETTING_KEYS = ["contact_email", "years", "auto_refresh_days", "languages", "esef_formats", "search_provider", "brave_api_key", "searxng_url",
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

// --- number formats ------------------------------------------------------------------------

const NF1 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const NF2 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const NF0 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });

function fmtMetric(v, unit) {
  if (v === null || v === undefined) return "–";
  if (unit === "pct") return NF1.format(v * 100) + " %";
  if (unit === "per_share") return NF2.format(v);
  const m = v / 1e6;
  return Math.abs(m) >= 1000 ? NF0.format(m) : NF1.format(m);
}

function chartValue(v, unit) {
  if (unit === "pct") return v * 100;
  if (unit === "money") return v / 1e6;
  return v;
}

function fmtChart(v, unit) {
  if (unit === "pct") return NF1.format(v) + " %";
  if (unit === "per_share") return NF2.format(v);
  return Math.abs(v) >= 1000 ? NF0.format(v) : NF1.format(v);
}

function fmtTick(v, unit) {
  const text = Number.isInteger(v) ? NF0.format(v) : NF1.format(v);
  return unit === "pct" ? text + " %" : text;
}

// --- charts (inline SVG, one series each; the tables are the accessible view) --------------

const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) node.setAttribute(k, String(v));
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

function niceTicks(lo, hi, count) {
  if (lo === hi) { hi = lo + 1; }
  const raw = (hi - lo) / Math.max(1, count - 1);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((st) => st >= raw) || 10 * mag;
  const start = Math.floor(lo / step) * step;
  const ticks = [];
  for (let t = start; t <= hi + step * 1e-9; t += step) ticks.push(Math.round(t / step) * step);
  if (ticks[ticks.length - 1] < hi) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function barPath(x, y0, y1, w, r) {
  // rounded data end, square at the baseline
  const h = Math.abs(y1 - y0);
  r = Math.min(r, h, w / 2);
  if (y1 <= y0) {
    return `M${x},${y0}V${y1 + r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 + r}V${y0}Z`;
  }
  return `M${x},${y0}V${y1 - r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 - r}V${y0}Z`;
}

function attachTooltip(wrap, chart, hit, bar, lines, anchor) {
  const tip = wrap.querySelector(".tooltip") || wrap.appendChild(el("div", { class: "tooltip", hidden: true }));
  const show = () => {
    tip.replaceChildren(el("b", {}, lines[0]), el("span", {}, lines[1]));
    const box = chart.getBoundingClientRect();
    const wbox = wrap.getBoundingClientRect();
    const scale = box.width / chart.viewBox.baseVal.width;
    tip.style.left = (box.left - wbox.left + anchor[0] * scale) + "px";
    tip.style.top = (box.top - wbox.top + anchor[1] * scale - 6) + "px";
    tip.hidden = false;
    chart.classList.add("hovering");
    bar.classList.add("active");
  };
  const hide = () => { tip.hidden = true; chart.classList.remove("hovering"); bar.classList.remove("active"); };
  hit.addEventListener("pointerenter", show);
  hit.addEventListener("pointerleave", hide);
  hit.addEventListener("focus", show);
  hit.addEventListener("blur", hide);
}

function columnChart({ title, sub, years, values, unit, width }) {
  const data = years.map((y) => {
    const v = values[String(y)];
    return { year: y, v: v === undefined || v === null ? null : chartValue(v, unit) };
  });
  const present = data.filter((d) => d.v !== null);
  if (present.length < 2) return null;
  const W = Math.max(260, Math.round(width || 340)), H = 190, M = { t: 22, r: 10, b: 22, l: 46 };
  const ticks = niceTicks(Math.min(0, ...present.map((d) => d.v)), Math.max(0, ...present.map((d) => d.v)), 4);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const pw = W - M.l - M.r, ph = H - M.t - M.b;
  const y = (v) => M.t + ph - ((v - lo) / (hi - lo)) * ph;
  const band = pw / data.length;
  const bw = Math.min(24, band * 0.62);
  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": title });
  for (const t of ticks) {
    chart.append(svg("line", { x1: M.l, x2: W - M.r, y1: y(t), y2: y(t), class: t === 0 ? "base" : "grid" }));
    chart.append(svg("text", { x: M.l - 6, y: y(t) + 3, "text-anchor": "end", class: "tick" }, fmtTick(t, unit)));
  }
  const wrap = el("div", { class: "chart-wrap" }, el("p", { class: "chart-title" }, title), el("p", { class: "chart-sub" }, sub), chart);
  const last = present[present.length - 1];
  data.forEach((d, i) => {
    const cx = M.l + band * i + band / 2;
    chart.append(svg("text", { x: cx, y: H - 6, "text-anchor": "middle", class: "tick" }, band >= 32 ? String(d.year) : "’" + String(d.year).slice(2)));
    if (d.v === null) return;
    const bar = svg("path", { d: barPath(cx - bw / 2, y(0), y(d.v), bw, 4), class: "bar" });
    chart.append(bar);
    if (d === last) {
      const above = d.v >= 0;
      chart.append(svg("text", { x: cx, y: above ? y(d.v) - 5 : y(d.v) + 12, "text-anchor": "middle", class: "value" }, fmtChart(d.v, unit)));
    }
    const hit = svg("rect", { x: M.l + band * i, y: M.t, width: band, height: ph, class: "hit", tabindex: 0,
      "aria-label": d.year + ": " + fmtChart(d.v, unit) });
    chart.append(hit);
    attachTooltip(wrap, chart, hit, bar, [fmtChart(d.v, unit) + (sub.startsWith("Mio") ? " Mio." : ""), "Geschäftsjahr " + d.year], [cx, Math.min(y(d.v), y(0))]);
  });
  return wrap;
}

// --- key figures -----------------------------------------------------------------------------

async function loadFinancials(lei) {
  try {
    renderFinancials(await api("GET", "/api/companies/" + lei + "/financials"));
  } catch (_) { $("#c-fin").hidden = true; }
}

function renderFinancials(data) {
  const card = $("#c-fin");
  state.fin = data;
  card.hidden = !data.years.length;
  if (!data.years.length) return;
  const grid = $("#c-charts");
  const single = window.matchMedia("(max-width: 760px)").matches;
  const colWidth = single ? grid.clientWidth : (grid.clientWidth - 18) / 2;
  const cur = data.currency || "";
  const byKey = Object.fromEntries(data.metrics.map((m) => [m.key, m]));
  $("#c-fin-sub").textContent = "Geschäftsjahre " + data.years[0] + "–" + data.years[data.years.length - 1] +
    " · Beträge in Mio. " + cur + " · automatisch aus dem Inline-XBRL der ESEF-Berichte (inkl. Vorjahreswerte)";
  $("#c-fin-csv").href = withToken("/api/companies/" + data.lei + "/financials.csv?style=de");
  // Four slots; when a report does not tag the first choice, the slot falls back to the next metric.
  const slots = [
    [["revenue", "Umsatz", "Mio. " + cur]],
    [["ebit_margin", "EBIT-Marge", "in % vom Umsatz"], ["net_margin", "Nettomarge", "Jahresergebnis in % vom Umsatz"]],
    [["fcf", "Free Cashflow", "Mio. " + cur + " · operativer Cashflow minus Investitionen"], ["eps", "Ergebnis je Aktie", cur + " je Aktie"]],
    [["equity_ratio", "Eigenkapitalquote", "in % der Bilanzsumme"], ["revenue_growth", "Umsatzwachstum", "in % zum Vorjahr"]],
  ];
  const charts = slots.map((options) => {
    for (const [key, title, sub] of options) {
      if (!byKey[key]) continue;
      const chart = columnChart({ title, sub, years: data.years, values: byKey[key].values, unit: byKey[key].unit, width: colWidth });
      if (chart) return chart;
    }
    return null;
  }).filter(Boolean);
  $("#c-charts").replaceChildren(...charts);
  const head = el("tr", {}, el("th", {}, "Kennzahl"), data.years.map((y) => el("th", {}, String(y))));
  const rows = data.metrics.map((m) => el("tr", {}, el("td", {}, m.label + (m.unit === "money" ? " (Mio. " + cur + ")" : m.unit === "per_share" ? " (" + cur + ")" : "")),
    data.years.map((y) => el("td", {}, fmtMetric(m.values[String(y)], m.unit)))));
  $("#c-fin-table").replaceChildren(el("thead", {}, head), el("tbody", {}, rows));
  $("#c-fin-notes").textContent = data.restatements.length
    ? "Nachträglich angepasst: " + data.restatements.map((r) => r.label + " " + r.year + " (berichtet " + fmtMetric(r.reported, "money") +
      ", im Folgejahr " + fmtMetric(r.restated, "money") + " Mio.)").join("; ") + ". Die Tabelle zeigt die ursprünglich berichteten Werte."
    : "";
}

// --- peer comparison -------------------------------------------------------------------------

async function loadCompare(nace) {
  try {
    const focus = state.company && state.company.nace && state.company.nace.slice(0, 2) === nace.slice(0, 2) ? state.company.lei : "";
    state.compare = await api("GET", "/api/industries/" + encodeURIComponent(nace) + "/compare" + (focus ? "?lei=" + focus : ""));
    const withData = state.compare.rows.filter((r) => r.fiscal_year);
    $("#i-compare").hidden = withData.length < 2;
    const select = $("#i-metric");
    if (!select.options.length) {
      select.replaceChildren(...state.compare.metrics.filter((m) => m.key !== "revenue").map((m) => el("option", { value: m.key }, m.label)));
      select.value = "ebit_margin";
    }
    renderCompare();
  } catch (_) { $("#i-compare").hidden = true; }
}

function renderCompare() {
  const data = state.compare;
  if (!data) return;
  const key = $("#i-metric").value || "ebit_margin";
  const unit = (data.metrics.find((m) => m.key === key) || {}).unit || "pct";
  const rows = data.rows.filter((r) => r[key] !== undefined && r[key] !== null).sort((a, b) => b[key] - a[key]);
  const wrapBox = $("#i-chart");
  if (!rows.length) { wrapBox.replaceChildren(el("p", { class: "muted" }, "Keine Werte für diese Kennzahl.")); }
  else {
    const W = Math.max(300, wrapBox.clientWidth || 680), rowH = 30, labelW = Math.min(220, Math.round(W * 0.34));
    const M = { t: 22, r: 64, b: 8 };
    const H = M.t + rows.length * rowH + M.b;
    const vals = rows.map((r) => chartValue(r[key], unit));
    const ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals), 4);
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const x = (v) => labelW + ((v - lo) / (hi - lo)) * (W - labelW - M.r);
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Vergleich " + key });
    for (const t of ticks) {
      chart.append(svg("line", { x1: x(t), x2: x(t), y1: M.t - 4, y2: H - M.b, class: t === 0 ? "base" : "grid" }));
    }
    const wrap = el("div", { class: "chart-wrap" }, chart);
    rows.forEach((r, i) => {
      const v = vals[i];
      const cy = M.t + i * rowH + rowH / 2;
      const maxChars = Math.max(10, Math.floor(labelW / 7.2));
      const name = (r.name || r.lei).length > maxChars ? (r.name || r.lei).slice(0, maxChars - 1) + "…" : (r.name || r.lei);
      chart.append(svg("text", { x: labelW - 10, y: cy + 4, "text-anchor": "end", class: r.focus ? "value" : "label" }, name));
      const x0 = x(0), x1 = x(v), h = 14;
      const left = Math.min(x0, x1), width = Math.max(1, Math.abs(x1 - x0)), rr = Math.min(4, width / 2);
      const d = v >= 0
        ? `M${x0},${cy - h / 2}H${x1 - rr}Q${x1},${cy - h / 2} ${x1},${cy - h / 2 + rr}V${cy + h / 2 - rr}Q${x1},${cy + h / 2} ${x1 - rr},${cy + h / 2}H${x0}Z`
        : `M${x0},${cy - h / 2}H${x1 + rr}Q${x1},${cy - h / 2} ${x1},${cy - h / 2 + rr}V${cy + h / 2 - rr}Q${x1},${cy + h / 2} ${x1 + rr},${cy + h / 2}H${x0}Z`;
      const bar = svg("path", { d, class: "bar" + (r.focus || !rows.some((q) => q.focus) ? "" : " deemph") });
      chart.append(bar);
      chart.append(svg("text", { x: v >= 0 ? x1 + 6 : x1 - 6, y: cy + 4, "text-anchor": v >= 0 ? "start" : "end", class: "tick" }, fmtChart(v, unit)));
      const hit = svg("rect", { x: 0, y: cy - rowH / 2, width: W, height: rowH, class: "hit", tabindex: 0, "aria-label": name + ": " + fmtChart(v, unit) });
      chart.append(hit);
      attachTooltip(wrap, chart, hit, bar, [fmtChart(v, unit), (r.name || r.lei) + " · GJ " + r.fiscal_year], [x1, cy - h / 2]);
    });
    const median = data.median[key];
    if (median !== undefined) {
      const mx = x(chartValue(median, unit));
      chart.append(svg("line", { x1: mx, x2: mx, y1: M.t - 8, y2: H - M.b, class: "median" }));
      chart.append(svg("text", { x: mx, y: M.t - 10, "text-anchor": "middle", class: "tick" }, "Median " + fmtChart(chartValue(median, unit), unit)));
    }
    wrapBox.replaceChildren(wrap);
  }
  const cols = data.metrics;
  const head = el("tr", {}, el("th", {}, "Unternehmen"), el("th", {}, "GJ"), cols.map((m) => el("th", {}, m.label + (m.unit === "money" ? " (Mio.)" : ""))));
  const body = data.rows.map((r) => el("tr", { class: r.focus ? "focus" : "" }, el("td", {}, (r.name || r.lei) + (r.country ? " (" + r.country + ")" : "")),
    el("td", {}, r.fiscal_year || "–"), cols.map((m) => el("td", {}, fmtMetric(r[m.key], m.unit) + (m.unit === "money" && r[m.key] !== undefined && r.currency ? " " + r.currency : "")))));
  body.push(el("tr", { class: "median" }, el("td", {}, "Median"), el("td", {}, ""), cols.map((m) => el("td", {}, data.median[m.key] !== undefined ? fmtMetric(data.median[m.key], m.unit) : ""))));
  $("#i-table").replaceChildren(el("thead", {}, head), el("tbody", {}, body));
}

// --- gaps and wrong documents -----------------------------------------------------------------

async function addManualLink(year) {
  const url = window.prompt("PDF-Link zum Geschäftsbericht " + year + " (https://…):");
  if (!url) return;
  if (!/^https?:\/\//i.test(url.trim())) { toast("Bitte einen vollständigen Link mit https:// angeben", "error"); return; }
  try {
    const { id } = await api("POST", "/api/jobs", { kind: "company", params: {
      lei: state.company.lei, urls: year + ": " + url.trim(),
      include: { esef: false, pdf: false, websearch: false, industry: false } } });
    watchJob(id, $("#c-job"), () => refreshCompany());
  } catch (err) { toast(err.message, "error"); }
}

async function removeDoc(doc, industry) {
  if (!window.confirm("„" + (doc.title || doc.category_label) + "“ löschen? Der Link wird bei künftigen Abrufen übersprungen, damit die nächstbeste Quelle zum Zug kommt.")) return;
  try {
    await api("DELETE", "/api/documents/" + doc.id + "?block=1");
    toast("Dokument entfernt. Starte den Abruf erneut, um die Lücke zu füllen.", "ok");
    if (industry) loadIndustry(); else refreshCompany();
  } catch (err) { toast(err.message, "error"); }
}

// --- overview --------------------------------------------------------------------------------

function fmtBytes(n) {
  if (n >= 1e9) return NF1.format(n / 1e9) + " GB";
  if (n >= 1e6) return NF0.format(n / 1e6) + " MB";
  return NF0.format(n / 1e3) + " KB";
}

async function loadOverview() {
  let data;
  try { data = await api("GET", "/api/overview"); } catch (err) { toast(err.message, "error"); return; }
  const st = data.stats;
  const tile = (value, label) => el("div", { class: "stat" }, el("b", {}, value), el("span", {}, label));
  $("#ov-stats").replaceChildren(tile(NF0.format(st.companies), "Unternehmen in der Bibliothek"), tile(NF0.format(st.documents), "Dokumente"),
    tile(fmtBytes(st.bytes), "Speicherplatz"), tile(NF0.format(st.industries), "Branchenpakete"),
    tile(NF0.format(st.with_financials), "mit Kennzahlen"), tile(NF0.format(st.indexed), "im Volltext durchsuchbar"));
  const openCompany = (lei) => { showTab("company"); selectCompany(lei); };
  $("#ov-recent").replaceChildren(...(data.recent.length ? data.recent.map((d) => el("li", {},
    el("span", { class: "grow" }, el("button", { class: "link", onclick: () => (d.lei && !d.nace ? openCompany(d.lei) : (d.nace ? ($("#i-code").value = d.nace, showTab("industry")) : null)) },
      d.company || ("NACE " + d.nace)), " · " + d.category_label + (d.fy_label || d.fiscal_year ? " " + (d.fy_label || d.fiscal_year) : "")),
    el("span", { class: "muted small nowrap" }, fmtDate(d.created_at)))) : [el("li", { class: "muted" }, "Noch nichts geladen. Starte unter „Unternehmen“.")]));
  $("#ov-gaps").replaceChildren(...(data.gaps.length ? data.gaps.map((g) => el("li", {},
    el("span", { class: "grow" }, el("button", { class: "link", onclick: () => openCompany(g.lei) }, g.name), el("br"),
      el("span", { class: "muted small" }, "fehlend: " + g.missing.join(", "))),
    el("span", { class: "tag warn" }, g.covered + "/" + g.target))) : [el("li", { class: "muted" }, "Keine Lücken – alle Unternehmen vollständig.")]));
  $("#ov-active").replaceChildren(...(data.active.length ? data.active.map((j) => el("li", {},
    el("span", { class: "grow" }, "#" + j.id + " " + (j.title || KIND_LABELS[j.kind]), el("br"), el("span", { class: "muted small" }, j.stage || "wartet")),
    el("span", {}, Math.round((j.progress || 0) * 100) + " %"))) : [el("li", { class: "muted" }, "Keine laufenden Aufträge.")]));
  $("#ov-watch").replaceChildren(...(data.watchlist.length ? data.watchlist.map((w) => el("li", {},
    el("button", { class: "link", onclick: () => openCompany(w.lei) }, w.name), el("span", { class: "muted small" }, w.latest ? "bis GJ " + w.latest : "noch leer")))
    : [el("li", { class: "muted" }, "Mit ☆ im Unternehmensprofil beobachten.")]));
  $("#ov-auto").textContent = data.auto_refresh.days
    ? "Automatische Aktualisierung alle " + data.auto_refresh.days + " Tage · nächste: " + (data.auto_refresh.next ? fmtDate(data.auto_refresh.next) : "bald")
    : "Automatische Aktualisierung aus (Einstellungen).";
  $("#ov-hint").textContent = data.pdftotext ? "" : "Hinweis: PDFs werden erst durchsuchbar, wenn „pdftotext“ (poppler-utils) installiert ist. ESEF-Berichte sind immer durchsuchbar.";
}

// --- full text -------------------------------------------------------------------------------

async function loadFulltextFilters() {
  try {
    const lib = await api("GET", "/api/library");
    const select = $("#f-lei");
    const current = select.value;
    select.replaceChildren(el("option", { value: "" }, "alle"), ...lib.companies.map((c) => el("option", { value: c.lei, selected: c.lei === current }, c.name)));
  } catch (_) { /* ignore */ }
  $("#f-q").focus();
}

function snippetNode(text) {
  const node = el("div", { class: "snippet" });
  const parts = (text || "").split("\u0002");
  node.append(parts[0]);
  for (const part of parts.slice(1)) {
    const [marked, rest] = part.split("\u0003");
    node.append(el("mark", {}, marked), rest || "");
  }
  return node;
}

async function runFulltext() {
  const q = $("#f-q").value.trim();
  if (q.length < 2) return;
  const params = new URLSearchParams({ q });
  for (const [key, id] of [["lei", "#f-lei"], ["from", "#f-from"], ["to", "#f-to"]]) if ($(id).value) params.set(key, $(id).value);
  $("#f-info").textContent = "Suche …";
  try {
    const data = await api("GET", "/api/fulltext?" + params.toString());
    const groups = new Map();
    for (const hit of data.results) {
      if (!groups.has(hit.id)) groups.set(hit.id, []);
      groups.get(hit.id).push(hit);
    }
    $("#f-info").textContent = data.results.length + " Fundstellen in " + groups.size + " Dokumenten · " + data.indexed + " Dokumente durchsucht" +
      (data.pdftotext ? "" : " (PDFs erst mit pdftotext)");
    const cards = [...groups.values()].map((hits) => {
      const h = hits[0];
      const fileUrl = withToken("/api/documents/" + h.id + "/file");
      return el("div", { class: "card hit-doc" },
        el("h4", {}, el("a", { href: fileUrl, target: "_blank", rel: "noopener" }, (h.company || ("NACE " + (h.nace || ""))) + " · " + h.category_label + " " + (h.fy_label || h.fiscal_year || ""))),
        el("div", { class: "meta" }, h.title || ""),
        hits.map((x) => el("div", {}, snippetNode(x.snippet),
          x.page ? el("a", { class: "small", href: fileUrl + "#page=" + x.page, target: "_blank", rel: "noopener" }, "Seite " + x.page) : null)));
    });
    $("#f-results").replaceChildren(...(cards.length ? cards : [el("p", { class: "muted" }, "Keine Treffer.")]));
  } catch (err) {
    $("#f-info").textContent = "";
    toast(err.message, "error");
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
  $("#c-fin-refresh").addEventListener("click", async () => {
    try { renderFinancials(await api("POST", "/api/companies/" + state.company.lei + "/financials")); } catch (err) { toast(err.message, "error"); }
  });
  $("#i-metric").addEventListener("change", () => renderCompare());
  $("#f-go").addEventListener("click", runFulltext);
  $("#f-q").addEventListener("keydown", (e) => { if (e.key === "Enter") runFulltext(); });
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
  showTab("overview");
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (state.fin && $("#c-charts").clientWidth > 0) renderFinancials(state.fin);
      if (state.compare && $("#i-chart").clientWidth > 0) renderCompare();
    }, 200);
  });
}

document.addEventListener("DOMContentLoaded", init);
