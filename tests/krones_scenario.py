"""Krones scenario: the real Krones AG figures from this repository's value analysis
(data/krones_financials_2015_2025.csv) served through simulated sources.

What is real: the ISIN (DE0006335003) and every number (revenue, EBT, net income, EPS, order
backlog for 2019-2025). What is simulated: the sources themselves (GLEIF, filings.xbrl.org,
Wikidata, the investor-relations website, web search) and all prose, which is marked as test
content. The LEI is a placeholder with valid check digits, because the real one could not be
looked up from the development environment. The website layout (archive table, sitemap-only
file, a broken English link, a year only findable by web search) is a stress test of typical IR
site quirks, not a copy of krones.com.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from tests.fakeweb import (ESEF, PEER_FR, PEER_IT, PEER_US, FakeWeb, esef_entity, esef_filings, firds_record,
                           FIRDS_XML, make_lei, page, pdf_bytes, zip_bytes)

ROOT = Path(__file__).resolve().parent.parent
CSV_FILE = ROOT / "data" / "krones_financials_2015_2025.csv"
KRONES = {"lei": make_lei("TEST00KRONESAG0000"), "name": "Krones AG", "country": "DE", "isin": "DE0006335003"}
CONCEPTS = {"revenue": "ifrs-full:Revenue", "ebt": "ifrs-full:ProfitLossBeforeTax",
            "net_income": "ifrs-full:ProfitLoss", "eps": "ifrs-full:BasicEarningsLossPerShare"}


def krones_figures() -> dict[int, dict[str, float]]:
    """Reported figures per year: EUR million, EPS in EUR."""
    out = {}
    with CSV_FILE.open() as fh:
        for row in csv.DictReader(fh):
            out[int(row["year"])] = {
                "revenue": float(row["revenue_eur_m"]), "ebt": float(row["ebt_eur_m"]),
                "net_income": float(row["net_income_eur_m"]), "eps": float(row["eps_eur"]),
                "backlog": float(row["order_backlog_eur_m"]),
            }
    return out


FIGURES = krones_figures()


def de(value: float, decimals: int = 1) -> str:
    text = f"{abs(value):,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def krones_ixbrl(year: int) -> bytes:
    """ESEF-style inline XBRL for one Krones fiscal year, with the prior year as comparative."""
    lei = KRONES["lei"]
    ident = f'<xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">{lei}</xbrli:identifier></xbrli:entity>'
    contexts = "".join(
        f'<xbrli:context id="d_{cid}">{ident}<xbrli:period><xbrli:startDate>{y}-01-01</xbrli:startDate>'
        f'<xbrli:endDate>{y}-12-31</xbrli:endDate></xbrli:period></xbrli:context>'
        for cid, y in (("cur", year), ("prev", year - 1)))
    units = ('<xbrli:unit id="EUR"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>'
             '<xbrli:unit id="EURps"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:EUR</xbrli:measure>'
             '</xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure>'
             '</xbrli:unitDenominator></xbrli:divide></xbrli:unit>')
    rows = []
    for key, concept in CONCEPTS.items():
        cells = []
        for cid, y in (("cur", year), ("prev", year - 1)):
            value = FIGURES[y][key]
            sign = ' sign="-"' if value < 0 else ""
            if key == "eps":
                cells.append(f'<td><ix:nonFraction name="{concept}" contextRef="d_{cid}" unitRef="EURps" decimals="2" '
                             f'format="ixt4:num-comma-decimal"{sign}>{de(value, 2)}</ix:nonFraction></td>')
            else:
                cells.append(f'<td><ix:nonFraction name="{concept}" contextRef="d_{cid}" unitRef="EUR" decimals="-5" '
                             f'scale="6" format="ixt4:num-comma-decimal"{sign}>{de(value)}</ix:nonFraction></td>')
        rows.append(f"<tr><td>{concept}</td>{''.join(cells)}</tr>")
    prose = (f"<p>[Testinhalt, kein Originaltext] Krones AG, Geschäftsjahr {year}: Umsatz {de(FIGURES[year]['revenue'])} "
             f"Mio. EUR, Auftragsbestand zum Jahresende {de(FIGURES[year]['backlog'])} Mio. EUR.</p>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:xbrli="http://www.xbrl.org/2003/instance" '
            'xmlns:ifrs-full="https://xbrl.ifrs.org/taxonomy/2022-03-24/ifrs-full" '
            'xmlns:ixt4="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12" '
            'xmlns:iso4217="http://www.xbrl.org/2003/iso4217">'
            f'<head><title>Krones AG ESEF {year} (Testfall)</title></head><body>'
            f'<div style="display:none"><ix:header><ix:resources>{contexts}{units}</ix:resources></ix:header></div>'
            f'<h1>Jahresfinanzbericht {year}</h1>{prose}<table>{"".join(rows)}</table></body></html>').encode("utf-8")


def report_pdf(year: int, lang: str) -> bytes:
    title = "Geschäftsbericht" if lang == "de" else "Annual Report"
    return pdf_bytes(f"Krones AG {title} {year} [Testinhalt] Auftragsbestand {de(FIGURES[year]['backlog'])} Mio. EUR")


KRONES_ESEF = esef_filings(KRONES, [2020, 2021, 2022, 2023, 2024, 2025])


def write_fake_pdftotext(directory: Path) -> Path:
    """A stand-in for poppler's pdftotext: page 1 = the PDF's label line, page 2 = fixed text."""
    tool = directory / "pdftotext"
    tool.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "data = open(sys.argv[-2], 'rb').read().split(b'\\n')\n"
        "label = data[1][2:].decode('utf-8', 'replace') if len(data) > 1 else ''\n"
        "sys.stdout.write(label + '\\fKonzernanhang und Erläuterungen')\n")
    tool.chmod(0o755)
    return tool


class KronesWeb(FakeWeb):
    """The fake internet from fakeweb.py plus Krones AG."""

    def route(self, path, q):
        j = lambda obj, status=200: (status, "application/json", json.dumps(obj).encode())  # noqa: E731
        html = lambda b: (200, "text/html; charset=utf-8", b)  # noqa: E731
        base = self.base
        lei = KRONES["lei"]

        if path == "/sitemap.xml":
            urls = ["/site/", "/krones/", "/krones/investor-relations/", "/krones/media/Krones_Annual_Report_2018_EN.pdf"]
            body = "".join(f"<url><loc>{base}{u}</loc></url>" for u in urls)
            return 200, "application/xml", (f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/'
                                            f'schemas/sitemap/0.9">{body}</urlset>').encode()
        # GLEIF
        if path == "/gleif/fuzzycompletions" and "krones" in (q.get("q") or [""])[0].lower():
            return j({"data": [{"type": "fuzzycompletions", "attributes": {"value": "Krones AG"},
                                "relationships": {"lei-records": {"data": {"type": "lei-records", "id": lei}}}}]})
        if path == "/gleif/lei-records" and (q.get("filter[isin]") == [KRONES["isin"]]
                                             or lei in (q.get("filter[lei]") or [""])[0].split(",")):
            from tests.fakeweb import gleif_record
            return j({"data": [gleif_record(KRONES)]})
        if path == f"/gleif/lei-records/{lei}":
            from tests.fakeweb import gleif_record
            return j({"data": gleif_record(KRONES)})
        if path == f"/gleif/lei-records/{lei}/isins":
            return j({"data": [{"type": "isins", "attributes": {"lei": lei, "isin": KRONES["isin"]}}]})
        # filings.xbrl.org
        if path == "/esef/api/filings":
            if "filter" not in q:
                data = [f for rows in ESEF.values() for f in rows] + KRONES_ESEF
                return j({"data": data, "included": [esef_entity(e) for e in (KRONES, PEER_IT, PEER_FR)], "links": {}})
            spec = json.loads(q["filter"][0])
            if spec[0]["val"]["val"] == lei:
                return j({"data": KRONES_ESEF, "included": [esef_entity(KRONES)], "links": {"next": None}})
        if path.startswith(f"/esef/files/{lei}/"):
            _, _, _, _, period, _idx, name = path.split("/")
            year = int(period[:4])
            if name == "report.xhtml":
                return 200, "application/xhtml+xml", krones_ixbrl(year)
            if name == "package.zip":
                return 200, "application/zip", zip_bytes({f"krones-{period}/reports/krones-{period}-de.xhtml":
                                                          krones_ixbrl(year)})
        # Wikidata
        if path == "/wikidata/sparql":
            query = q.get("query", [""])[0]
            if "VALUES ?ind" in query:
                rows = [{"item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q9" + e["lei"][:4]},
                         "itemLabel": {"type": "literal", "value": e["name"]},
                         "lei": {"type": "literal", "value": e["lei"]}, "isin": {"type": "literal", "value": e["isin"]},
                         "cc": {"type": "literal", "value": e["country"]}} for e in (KRONES, PEER_IT, PEER_FR, PEER_US)]
                return j({"head": {"vars": []}, "results": {"bindings": rows}})
            if lei in query or KRONES["isin"] in query:
                row = {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q99990010"},
                       "itemLabel": {"type": "literal", "value": "Krones AG"},
                       "website": {"type": "uri", "value": f"{base}/krones/"},
                       "industry": {"type": "uri", "value": "http://www.wikidata.org/entity/Q99990002"},
                       "industryLabel": {"type": "literal", "value": "Verpackungsmaschinenbau"}}
                return j({"head": {"vars": []}, "results": {"bindings": [row]}})
        # simulated investor-relations website
        if path == "/krones/":
            return html(page("Krones AG", "<h1>Krones</h1><a href='/krones/unternehmen/'>Unternehmen</a> "
                             "<a href='/krones/karriere/'>Karriere</a> <a href='/krones/investor-relations/'>Investor Relations</a>"))
        if path in ("/krones/unternehmen/", "/krones/karriere/"):
            return html(page("Seite", "<p>Kein Bericht.</p>"))
        if path == "/krones/investor-relations/":
            return html(page("Investor Relations", "<h1>Investor Relations</h1>"
                             "<a href='/krones/investor-relations/finanzberichte/'>Finanzberichte</a> "
                             "<a href='/krones/investor-relations/archiv/'>Berichtsarchiv</a>"))
        if path == "/krones/investor-relations/finanzberichte/":
            rows = []
            for year in range(2025, 2018, -1):
                en = (f"<a href='/krones/media/broken-annual-report-{year}.pdf'>Annual Report {year}</a>" if year == 2019
                      else f"<a href='/krones/media/annual-report-{year}-en.pdf'>Annual Report {year}</a>")
                rows.append(f"<tr><td>{year}</td><td><a href='/krones/media/geschaeftsbericht-{year}-de.pdf'>"
                            f"Geschäftsbericht {year}</a></td><td>{en}</td></tr>")
            extra = ("<ul><li><a href='/krones/media/halbjahresfinanzbericht-2026.pdf'>Halbjahresfinanzbericht 2026</a></li>"
                     "<li><a href='/krones/media/nachhaltigkeitsbericht-2025.pdf'>Nachhaltigkeitsbericht 2025</a></li>"
                     "<li><a href='/krones/media/verguetungsbericht-2025.pdf'>Vergütungsbericht 2025</a></li>"
                     "<li><a href='/krones/media/einladung-hv-2026.pdf'>Einladung zur Hauptversammlung 2026</a></li></ul>")
            return html(page("Finanzberichte", f"<h1>Finanzberichte</h1><table>{''.join(rows)}</table>{extra}"))
        if path == "/krones/investor-relations/archiv/":
            rows = "".join(f"<tr><td>{y}</td><td><a href='/krones/media/archiv/GB{str(y)[2:]}.pdf'>PDF</a></td></tr>"
                           for y in (2018, 2017, 2015))  # 2016 deliberately missing: only web search finds it
            return html(page("Archiv", f"<h1>Geschäftsberichte-Archiv</h1><table>{rows}</table>"))
        if path.startswith("/krones/media/broken-"):
            return html(page("Nicht gefunden", "<p>Die Datei wurde verschoben.</p>"))
        if path.startswith("/krones/media/"):
            name = path.rsplit("/", 1)[-1]
            year = next((int(t) for t in name.replace(".", "-").replace("_", "-").split("-") if t.isdigit() and len(t) == 4), None)
            if year is None and name.startswith("GB"):
                year = 2000 + int(name[2:4])
            if year in FIGURES:
                return 200, "application/pdf", report_pdf(year, "en" if "annual" in name.lower() else "de")
            return 200, "application/pdf", pdf_bytes(path)
        # Brave search: finds the 2016 report that the website does not link any more
        if path == "/brave":
            query = q.get("q", [""])[0]
            if "Krones" in query and "2016" in query:
                return j({"web": {"results": [
                    {"title": "Krones Geschäftsbericht 2016", "url": f"{base}/krones/media/archiv/Krones_GB_2016.pdf",
                     "description": "Geschäftsbericht 2016 der Krones AG"},
                    {"title": "Krones Geschäftsbericht 2016 (Kopie)", "url": "https://mirror.invalid/krones-2016.pdf",
                     "description": "Kopie"}]}})
            return j({"web": {"results": []}})
        # ESMA FIRDS with the Krones share
        if path == "/esma/files/FULINS_E_20260920_01of01.zip":
            records = (firds_record(KRONES["isin"], "KRONES AG O.N.", "ESVUFR", lei, "XETR", True)
                       + firds_record(KRONES["isin"], "KRONES AG O.N.", "ESVUFR", lei, "XFRA", False)
                       + firds_record(PEER_IT["isin"], "MUSTER PACKAGING SPA", "ESVUFR", PEER_IT["lei"], "MTAA", True))
            return 200, "application/zip", zip_bytes({"FULINS_E_20260920_01of01.xml":
                                                      FIRDS_XML.format(records=records).encode()})
        return super().route(path, q)
