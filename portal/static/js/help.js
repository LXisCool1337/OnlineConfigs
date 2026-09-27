// Built-in help: getting started, glossary of every term used in the portal, common questions.

import { lang, t } from "./i18n.js";
import { $, el } from "./util.js";

const START = {
  de: [
    "Unter <Einstellungen> deine E-Mail-Adresse als Kontakt eintragen – einige Datenquellen verlangen das.",
    "<Datenquellen prüfen> (Startseite oder Einstellungen) zeigt, ob dein Netzwerk die Quellen erreicht.",
    "Ein Unternehmen suchen – mit Namen, ISIN (z. B. DE0006335003) oder LEI – und öffnen.",
    "<Jahresberichte laden> klicken. Das Portal sucht die offiziellen digitalen Berichte (ab 2020) und die PDF-Berichte auf der Firmenwebsite, nimmt pro Jahr die beste Datei und liest die Kennzahlen aus. Das läuft im Hintergrund; du kannst weiterarbeiten.",
    "Ergebnisse ansehen: Jahresübersicht mit Vorschau, Kennzahlen mit Diagrammen, Excel-Export. Mit dem <Branchenpaket> kommen Statistiken, Studien und die Berichte der Wettbewerber dazu.",
  ],
  en: [
    "Enter your e-mail address as contact under <Settings> – some data sources require it.",
    "<Check data sources> (start page or settings) shows whether your network can reach the sources.",
    "Search for a company – by name, ISIN (e.g. DE0006335003) or LEI – and open it.",
    "Click <Load annual reports>. The portal looks for the official digital reports (from 2020) and the PDF reports on the company website, keeps the best file per year and extracts the key figures. It runs in the background; you can keep working.",
    "Look at the results: year overview with preview, key figures with charts, Excel export. The <industry package> adds statistics, studies and the competitors' reports.",
  ],
};

export const TERMS = [
  ["esef", {
    de: "Seit dem Geschäftsjahr 2020 veröffentlichen alle Unternehmen an einem regulierten EU-Markt ihren Jahresfinanzbericht zusätzlich im „European Single Electronic Format“: eine Webseite (XHTML), in der jede Zahl der Abschlüsse maschinenlesbar markiert ist. Das Portal holt diese Berichte von filings.xbrl.org und liest daraus die Kennzahlen. Für Jahre vor 2020 gibt es kein ESEF.",
    en: "Since financial year 2020 every company on a regulated EU market also publishes its annual financial report in the European Single Electronic Format: a web page (XHTML) in which every number of the financial statements is machine-readable. The portal takes these reports from filings.xbrl.org and extracts the key figures from them. There is no ESEF before 2020.",
  }],
  ["pdf", {
    de: "Der gestaltete Geschäftsbericht, den Unternehmen auf ihrer Website anbieten. Er ist die einzige Quelle für die Jahre vor 2020. Das Portal durchsucht dafür die Investor-Relations-Seite der Firma.",
    en: "The designed annual report companies offer on their website. It is the only source for the years before 2020. The portal searches the company's investor-relations pages for it.",
  }],
  ["fiscal_year", {
    de: "Das Jahr, auf das sich ein Bericht bezieht. Endet das Geschäftsjahr nicht im Dezember, heißt es z. B. „2023/24“; das Portal ordnet es dem Endjahr (2024) zu.",
    en: "The year a report covers. If the financial year does not end in December it is written like “2023/24”; the portal files it under the year in which it ends (2024).",
  }],
  ["lei", {
    de: "Legal Entity Identifier: eine 20-stellige, weltweit eindeutige Nummer für ein Unternehmen (öffentliches GLEIF-Register). Jeder Emittent an einer EU-Börse hat eine. Das Portal erkennt Unternehmen daran.",
    en: "Legal Entity Identifier: a 20-character, globally unique number for a company (public GLEIF register). Every issuer on an EU exchange has one. The portal identifies companies by it.",
  }],
  ["isin", {
    de: "International Securities Identification Number: die 12-stellige Kennung einer Aktie, z. B. DE0006335003 für Krones. Damit findet die Suche ein Unternehmen am zuverlässigsten.",
    en: "International Securities Identification Number: the 12-character code of a share, e.g. DE0006335003 for Krones. It is the most reliable way to find a company.",
  }],
  ["nace", {
    de: "Die Branchenklassifikation der EU, z. B. 28 = Maschinenbau. Sie bestimmt, welche Statistiken, Verbände und Wettbewerber ins Branchenpaket kommen. Zwei Ziffern reichen meist; genauer geht es mit z. B. 28.29.",
    en: "The EU's industry classification, e.g. 28 = machinery. It decides which statistics, associations and competitors go into the industry package. Two digits are usually enough; 28.29 is more precise.",
  }],
  ["ir", {
    de: "Investor-Relations-Seite: der Bereich einer Firmenwebsite mit Geschäftsberichten. Findet das Portal Berichte nicht automatisch, trag hier die Adresse der Berichtsliste ein.",
    en: "Investor-relations page: the part of a company website that lists the annual reports. If the portal does not find the reports by itself, enter the address of that list here.",
  }],
  ["coverage", {
    de: "Wie viele der letzten 10 Geschäftsjahre mindestens einen Bericht haben – als PDF, als ESEF oder beides.",
    en: "How many of the last 10 financial years have at least one report – as PDF, as ESEF or both.",
  }],
  ["industry_package", {
    de: "Material zur Branche: amtliche Statistik (Eurostat), frei zugängliche Studien (OpenAlex), Veröffentlichungen von Verbänden und Behörden, die ESEF-Berichte von Wettbewerbern und – falls eingerichtet – Treffer der Websuche.",
    en: "Material about the industry: official statistics (Eurostat), freely available studies (OpenAlex), publications of associations and public bodies, the competitors' ESEF reports and – if set up – web-search results.",
  }],
  ["peers", {
    de: "Börsennotierte Unternehmen derselben Branche in EU/EWR – aus Wikidata, aus deinem Katalog (gleicher NACE-Code) oder von dir eingetragen.",
    en: "Listed companies in the same industry in the EU/EEA – from Wikidata, from your catalogue (same NACE code) or entered by you.",
  }],
  ["key_figures", {
    de: "Werte aus den ESEF-Berichten: Umsatz, EBIT (operatives Ergebnis), Ergebnis vor Steuern, Jahresergebnis, Ergebnis je Aktie, Cashflow, Investitionen und Bilanz. Daraus berechnet: Wachstum, Margen (Ergebnis ÷ Umsatz), Free Cashflow (operativer Cashflow − Investitionen), Eigenkapitalquote (Eigenkapital ÷ Bilanzsumme) und Eigenkapitalrendite (Ergebnis ÷ durchschnittliches Eigenkapital). Fehlt eine Angabe im Bericht, bleibt das Feld leer.",
    en: "Values from the ESEF reports: revenue, EBIT (operating result), profit before tax, net income, earnings per share, cash flow, capital expenditure and balance sheet. Calculated from them: growth, margins (profit ÷ revenue), free cash flow (operating cash flow − capex), equity ratio (equity ÷ total assets) and return on equity (profit ÷ average equity). If a report does not contain a value, the field stays empty.",
  }],
  ["restatement", {
    de: "Jeder Bericht enthält auch das Vorjahr. Weicht diese Zahl vom ursprünglich berichteten Wert ab, zeigt das Portal den ursprünglichen Wert und nennt die Anpassung als Hinweis.",
    en: "Every report also contains the prior year. If that number differs from the value originally reported, the portal shows the original value and mentions the change as a note.",
  }],
  ["fulltext", {
    de: "Durchsucht den Text aller geladenen Berichte. ESEF-Berichte sind immer durchsuchbar, PDFs erst mit dem Zusatzprogramm pdftotext (Poppler).",
    en: "Searches the text of all downloaded reports. ESEF reports are always searchable, PDFs once the pdftotext tool (Poppler) is installed.",
  }],
  ["watchlist", {
    de: "Mit ☆ markierte Unternehmen. „Alle aktualisieren“ und die automatische Aktualisierung holen für sie neue Berichte nach.",
    en: "Companies marked with ☆. “Update all” and the automatic refresh fetch new reports for them.",
  }],
  ["websearch", {
    de: "Optionaler Suchdienst (Brave Search API oder ein eigenes SearXNG) für Jahre, die weder ESEF noch die Firmenwebsite liefern. Treffer werden nur von der Firmendomain oder bekannten Dienstleistern für Investor Relations übernommen.",
    en: "Optional search service (Brave Search API or your own SearXNG) for years that neither ESEF nor the company website provide. Results are only accepted from the company's domain or well-known investor-relations hosts.",
  }],
  ["robots", {
    de: "Die Regeln einer Website für automatische Abrufe. Das Portal hält sich immer daran, fragt jede Website langsam ab und umgeht keine Logins oder Bezahlschranken.",
    en: "A website's rules for automated access. The portal always follows them, requests each site slowly and never bypasses logins or paywalls.",
  }],
  ["universe", {
    de: "Ein lokaler Katalog aller börsennotierten Unternehmen in EU/EWR – aus den ESEF-Meldungen oder aus der ESMA-Datenbank FIRDS. Er macht die Suche schneller und ermöglicht Stapelabrufe für viele Unternehmen.",
    en: "A local catalogue of all listed companies in the EU/EEA – from the ESEF filings or from ESMA's FIRDS database. It makes search faster and allows batch downloads for many companies.",
  }],
  ["job", {
    de: "Jeder Abruf läuft im Hintergrund als Auftrag. Du kannst weiterarbeiten; alle Aufträge stehen unter „Aufträge“.",
    en: "Every download runs in the background as a job. You can keep working; all jobs are listed under “Jobs”.",
  }],
];

const FAQ = [
  ["missing_years", {
    de: "Meist, weil die Firmenwebsite ältere Berichte nicht mehr verlinkt oder ihre Liste erst per JavaScript lädt. Abhilfe: (1) unter „Stammdaten bearbeiten“ die Adresse der Berichtsseite eintragen und neu laden, (2) in der Jahresübersicht beim fehlenden Jahr „+ Link“ klicken und die PDF-Adresse einfügen, (3) unter Einstellungen eine Websuche einrichten.",
    en: "Usually because the company website no longer links older reports or builds its list with JavaScript. Fix: (1) enter the address of the reports page under “Edit company details” and load again, (2) click “+ Link” at the missing year in the year overview and paste the PDF address, (3) set up web search in the settings.",
  }],
  ["unreachable", {
    de: "„Datenquellen prüfen“ zeigt, welche Quelle blockiert ist. Häufige Ursache ist eine Firewall oder ein Proxy im Firmennetz. Die übrigen Quellen funktionieren trotzdem; fehlende Teile lassen sich später nachladen.",
    en: "“Check data sources” shows which source is blocked. A common cause is a firewall or proxy on a company network. The other sources still work; missing parts can be loaded later.",
  }],
  ["pdf_search", {
    de: "Installiere pdftotext (Paket „poppler-utils“ bzw. „poppler“) und klicke unter Einstellungen auf „Volltext aktualisieren“.",
    en: "Install pdftotext (package “poppler-utils” or “poppler”) and click “Update full text” in the settings.",
  }],
  ["wrong_doc", {
    de: "In der Jahresübersicht oder der Dateiliste auf „Falsch“ klicken. Die Datei wird gelöscht und der Link gesperrt; beim nächsten Laden kommt die nächstbeste Quelle zum Zug.",
    en: "Click “Wrong” in the year overview or the file list. The file is deleted and its link blocked; the next load uses the next-best source.",
  }],
  ["files", {
    de: "Im Ordner „library“ neben dem Portal, geordnet nach Land, Unternehmen und Jahr. Die Datei manifest.json nennt Quelle, Prüfsumme und Abrufzeit jeder Datei. „Alles als ZIP“ packt einen Unternehmensordner zusammen.",
    en: "In the “library” folder next to the portal, sorted by country, company and year. manifest.json lists source, checksum and download time of every file. “Download all as ZIP” packs a company folder.",
  }],
  ["legal", {
    de: "Das Portal nutzt nur frei zugängliche Quellen und offizielle Schnittstellen, beachtet robots.txt und fragt langsam ab. Die Dateien sind für die eigene Recherche gedacht. Kommerzielle Studien hinter Bezahlschranken werden nicht geladen. Keine Anlageberatung.",
    en: "The portal only uses freely accessible sources and official interfaces, follows robots.txt and requests slowly. The files are meant for your own research. Commercial studies behind paywalls are not downloaded. Not investment advice.",
  }],
];

function richText(text) {
  // <Text> marks a button or menu name.
  return text.split(/(<[^>]+>)/).map((part) => part.startsWith("<") ? el("strong", {}, part.slice(1, -1)) : part);
}

export function openHelp(anchor = null) {
  const dialog = $("#dlg-help");
  const l = lang();
  const nav = el("nav", { class: "help-nav", "aria-label": t("help.title") },
    el("a", { href: "#help-start" }, t("help.start")), el("a", { href: "#help-terms" }, t("help.terms")),
    el("a", { href: "#help-faq" }, t("help.faq")));
  const filter = el("input", { type: "search", class: "help-filter", placeholder: t("help.filter"), "aria-label": t("help.filter") });
  const termList = el("dl", { class: "terms" }, TERMS.map(([id, text]) => el("div", { class: "term", id: "help-" + id },
    el("dt", {}, t("term." + id)), el("dd", {}, text[l]))));
  filter.addEventListener("input", () => {
    const q = filter.value.trim().toLowerCase();
    for (const node of termList.children) node.hidden = q && !node.textContent.toLowerCase().includes(q);
  });
  dialog.replaceChildren(
    el("div", { class: "dialog-head" }, el("h2", { class: "dialog-title", id: "help-title" }, t("help.title")),
      el("button", { class: "btn primary small", onclick: () => dialog.close() }, t("common.close"))),
    el("div", { class: "help-body" }, nav,
      el("div", { class: "help-content" },
        el("section", { id: "help-start" }, el("h3", {}, t("help.start")), el("ol", { class: "help-steps" }, START[l].map((s) => el("li", {}, richText(s))))),
        el("section", { id: "help-terms" }, el("h3", {}, t("help.terms")), filter, termList),
        el("section", { id: "help-faq" }, el("h3", {}, t("help.faq")),
          FAQ.map(([id, text]) => el("details", { class: "faq", id: "help-" + id }, el("summary", {}, t("faq." + id)), el("p", {}, text[l])))))));
  dialog.setAttribute("aria-labelledby", "help-title");
  if (!dialog.open) dialog.showModal();
  if (anchor) {
    const target = dialog.querySelector("#help-" + anchor);
    if (target) {
      if (target.tagName === "DETAILS") target.open = true;
      target.classList.add("flash");
      target.scrollIntoView({ block: "center" });
    }
  }
}
