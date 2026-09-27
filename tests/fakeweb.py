"""A fake internet for offline tests: GLEIF, filings.xbrl.org, Wikidata, Eurostat, OpenAlex, ESMA FIRDS,
Brave search, an industry association and a company website with ten years of reports.

Response formats follow the public APIs' documented shapes. The company and its identifiers are
fictitious (valid check digits, generated below).
"""

from __future__ import annotations

import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from portal.config import Settings
from portal.identifiers import isin_check_digit, lei_check_digits


def make_lei(body: str) -> str:
    return body + lei_check_digits(body)


def make_isin(body: str) -> str:
    return body + isin_check_digit(body)


COMPANY = {"lei": make_lei("529900BSPMASCHINEN"), "name": "Beispiel Maschinenbau AG", "country": "DE",
           "isin": make_isin("DE000BSPM01")}
PEER_IT = {"lei": make_lei("815600MUSTERPACKAG"), "name": "Muster Packaging S.p.A.", "country": "IT",
           "isin": make_isin("IT0000MSTPK")}
PEER_FR = {"lei": make_lei("969500EXEMPLEEMBAL"), "name": "Exemple Emballage SA", "country": "FR",
           "isin": make_isin("FR0000EXMBL")}
PEER_US = {"lei": make_lei("549300SAMPLEBOTTLN"), "name": "Sample Bottling Inc.", "country": "US",
           "isin": make_isin("US0000SMPLB")}
ENTITIES = [COMPANY, PEER_IT, PEER_FR, PEER_US]
TODAY = "2026-09-27"


def pdf_bytes(label: str, size: int = 4000) -> bytes:
    head = f"%PDF-1.4\n% {label}\n1 0 obj << /Type /Catalog >> endobj\n".encode()
    pad = (label.encode() * (size // max(1, len(label)) + 1))[:size]
    return head + pad + b"\n%%EOF\n"


def xhtml_bytes(title: str) -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><head><title>' + title + '</title></head>'
            '<body><p>' + title + '</p></body></html>').encode()


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def gleif_record(e: dict) -> dict:
    return {"type": "lei-records", "id": e["lei"], "attributes": {
        "lei": e["lei"],
        "entity": {"legalName": {"name": e["name"], "language": "de"}, "otherNames": [],
                   "legalAddress": {"country": e["country"], "city": "Musterstadt"},
                   "headquartersAddress": {"country": e["country"]}, "legalForm": {"id": "8Z6G"},
                   "status": "ACTIVE"},
        "registration": {"status": "ISSUED"}}}


def esef_filings(e: dict, years: list[int], corrected: int | None = None) -> list[dict]:
    rows = []
    for year in years:
        rows.append((year, 0, f"{year + 1}-04-01T10:00:00"))
        if year == corrected:
            rows.append((year, 1, f"{year + 1}-06-15T10:00:00"))
    out = []
    for year, idx, added in rows:
        period = f"{year}-12-31"
        fxo = f"{e['lei']}-{period}-ESEF-{e['country']}-{idx}"
        root = f"/esef/files/{e['lei']}/{period}/{idx}"
        out.append({"type": "filing", "id": fxo, "attributes": {
            "fxo_id": fxo, "period_end": period, "country": e["country"], "date_added": added,
            "report_url": f"{root}/report.xhtml", "package_url": f"{root}/package.zip",
            "json_url": f"{root}/report.json", "viewer_url": f"{root}/viewer.html", "error_count": 0},
            "relationships": {"entity": {"data": {"type": "entity", "id": e["lei"][:6]}}}})
    return out


ESEF = {COMPANY["lei"]: esef_filings(COMPANY, [2020, 2021, 2022, 2023, 2024, 2025], corrected=2021),
        PEER_IT["lei"]: esef_filings(PEER_IT, [2024, 2025]),
        PEER_FR["lei"]: esef_filings(PEER_FR, [2024, 2025])}


def esef_entity(e: dict) -> dict:
    return {"type": "entity", "id": e["lei"][:6], "attributes": {"identifier": e["lei"], "name": e["name"]}}


FIRDS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<BizData xmlns="urn:iso:std:iso:20022:tech:xsd:head.003.001.01">
 <Hdr/>
 <Pyld>
  <Document xmlns="urn:iso:std:iso:20022:tech:xsd:auth.017.001.02">
   <FinInstrmRptgRefDataRpt>
    <RptHdr><RptgNtty><NtnlCmptntAuthrty>EU</NtnlCmptntAuthrty></RptgNtty></RptHdr>
    {records}
   </FinInstrmRptgRefDataRpt>
  </Document>
 </Pyld>
</BizData>"""


def firds_record(isin, name, cfi, lei, mic, issuer_req, term=None):
    term_xml = f"<TermntnDt>{term}</TermntnDt>" if term else ""
    return (f"<RefData><FinInstrmGnlAttrbts><Id>{isin}</Id><FullNm>{name}</FullNm><ShrtNm>X</ShrtNm>"
            f"<ClssfctnTp>{cfi}</ClssfctnTp><NtnlCcy>EUR</NtnlCcy><CmmdtyDerivInd>false</CmmdtyDerivInd>"
            f"</FinInstrmGnlAttrbts><Issr>{lei}</Issr><TradgVnRltdAttrbts><Id>{mic}</Id>"
            f"<IssrReq>{'true' if issuer_req else 'false'}</IssrReq><FrstTradDt>2010-01-04T00:00:00Z</FrstTradDt>"
            f"{term_xml}</TradgVnRltdAttrbts><TechAttrbts><RlvntCmptntAuthrty>{isin[:2]}</RlvntCmptntAuthrty>"
            f"</TechAttrbts></RefData>")


DELISTED = {"lei": make_lei("529900ALTAGDELIST0"), "isin": make_isin("DE000ALT001")}
BOND_ISIN = make_isin("DE000BSPA01")


def firds_zip() -> bytes:
    records = "".join([
        firds_record(COMPANY["isin"], "BEISPIEL MASCHINENBAU AG O.N.", "ESVUFR", COMPANY["lei"], "XETR", True),
        firds_record(COMPANY["isin"], "BEISPIEL MASCHINENBAU AG O.N.", "ESVUFR", COMPANY["lei"], "XFRA", False),
        firds_record(PEER_IT["isin"], "MUSTER PACKAGING SPA", "ESVUFR", PEER_IT["lei"], "MTAA", True),
        firds_record(PEER_US["isin"], "SAMPLE BOTTLING INC", "ESVUFR", PEER_US["lei"], "XETR", False),
        firds_record(BOND_ISIN, "BEISPIEL 3% 2030", "DBFTFB", COMPANY["lei"], "XFRA", True),
        firds_record(DELISTED["isin"], "ALT AG O.N.", "ESVUFR", DELISTED["lei"], "XETR", True, "2020-06-30T00:00:00Z"),
    ])
    return zip_bytes({"FULINS_E_20260920_01of01.xml": FIRDS_XML.format(records=records).encode()})


def jsonstat() -> dict:
    years = [str(y) for y in range(2016, 2026)]
    values = {}
    for g in range(2):
        for t in range(len(years)):
            values[str(g * len(years) + t)] = round(90 + g * 5 + t * 1.5, 1)
    return {
        "version": "2.0", "class": "dataset", "label": "Production in industry - annual data", "source": "ESTAT",
        "updated": "2026-09-01T11:00:00+0200", "value": values, "status": {"3": "p"},
        "id": ["freq", "indic_bt", "nace_r2", "s_adj", "unit", "geo", "time"],
        "size": [1, 1, 1, 1, 1, 2, len(years)],
        "dimension": {
            "freq": {"label": "Time frequency", "category": {"index": {"A": 0}, "label": {"A": "Annual"}}},
            "indic_bt": {"label": "Indicator", "category": {"index": {"PRD": 0}, "label": {"PRD": "Production (volume)"}}},
            "nace_r2": {"label": "NACE", "category": {"index": {"C28": 0}, "label": {"C28": "Manufacture of machinery"}}},
            "s_adj": {"label": "Adjustment", "category": {"index": {"CA": 0}, "label": {"CA": "Calendar adjusted"}}},
            "unit": {"label": "Unit", "category": {"index": {"I21": 0}, "label": {"I21": "Index, 2021=100"}}},
            "geo": {"label": "Geo", "category": {"index": {"EU27_2020": 0, "DE": 1},
                                                 "label": {"EU27_2020": "European Union", "DE": "Germany"}}},
            "time": {"label": "Time", "category": {"index": {y: i for i, y in enumerate(years)},
                                                   "label": {y: y for y in years}}},
        },
    }


def page(title: str, body: str, lang: str = "de") -> bytes:
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{title}</title></head>'
            f"<body><nav><a href='/site/'>Start</a></nav>{body}</body></html>").encode("utf-8")


class FakeWeb:
    def __init__(self):
        self.requests: list[tuple[str, str, str]] = []
        self.esef_mode = "normal"  # normal | ignore_filter | reject_filter
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler(main=True))
        self.cdn = ThreadingHTTPServer(("127.0.0.1", 0), self._handler(main=False))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.cdn_base = f"http://127.0.0.1:{self.cdn.server_address[1]}"
        self.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (self.server, self.cdn)]

    def __enter__(self):
        for t in self.threads:
            t.start()
        return self

    def __exit__(self, *exc):
        for s in (self.server, self.cdn):
            s.shutdown()
            s.server_close()

    def paths(self) -> list[str]:
        with self.lock:
            return [p for p, _q, _ua in self.requests]

    def settings(self, library_dir: str, **extra) -> Settings:
        s = Settings(
            library_dir=library_dir, contact_email="test@example.org", default_rate=0.0, host_rates={},
            retries=0, backoff_base=0.01, timeout=10, crawl_max_pages=40, download_workers=3,
            gleif_api=f"{self.base}/gleif", esef_api=f"{self.base}/esef", wikidata_sparql=f"{self.base}/wikidata/sparql",
            eurostat_api=f"{self.base}/eurostat", openalex_api=f"{self.base}/openalex",
            esma_firds_api=f"{self.base}/esma/solr", brave_api=f"{self.base}/brave",
            search_trusted_hosts=[], search_provider="", peers_max=5, peer_years=1, openalex_max=5,
            curated_max_per_source=5)
        for key, value in extra.items():
            setattr(s, key, value)
        return s

    # --- routing ---------------------------------------------------------------------------

    def _handler(self, main: bool):
        web = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parts = urlsplit(self.path)
                with web.lock:
                    web.requests.append((("" if main else "cdn:") + parts.path, parts.query,
                                         self.headers.get("User-Agent", "")))
                q = {k: v for k, v in parse_qs(parts.query).items()}
                try:
                    status, ctype, body = (web.route if main else web.route_cdn)(parts.path, q)
                except Exception as err:  # noqa: BLE001
                    status, ctype, body = 500, "text/plain", repr(err).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def route_cdn(self, path, q):
        if path == "/files/annual-report-2023-en.pdf":
            return 200, "application/pdf", pdf_bytes("Annual Report 2023 EN (CDN)")
        return 404, "text/plain", b"not found"

    def route(self, path, q):
        j = lambda obj, status=200: (status, "application/json", json.dumps(obj).encode())  # noqa: E731
        html = lambda b: (200, "text/html; charset=utf-8", b)  # noqa: E731
        pdf = lambda label: (200, "application/pdf", pdf_bytes(label))  # noqa: E731
        base = self.base

        if path == "/robots.txt":
            return 200, "text/plain", (f"User-agent: *\nDisallow: /site/intern/\nDisallow: /assoc/intern/\n"
                                       f"Sitemap: {base}/sitemap.xml\n").encode()
        if path == "/sitemap.xml":
            urls = ["/site/", "/site/investor-relations/", "/site/media/Annual_Report_2017_EN.pdf"]
            body = "".join(f"<url><loc>{base}{u}</loc></url>" for u in urls)
            return 200, "application/xml", (f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/'
                                            f'schemas/sitemap/0.9">{body}</urlset>').encode()

        # company website
        if path == "/site/":
            return html(page("Beispiel Maschinenbau AG", "<h1>Willkommen</h1><ul>"
                             "<li><a href='/site/produkte/'>Produkte</a></li>"
                             "<li><a href='/site/karriere/'>Karriere</a></li>"
                             "<li><a href='/site/investor-relations/'>Investor Relations</a></li></ul>"))
        if path in ("/site/produkte/", "/site/karriere/"):
            return html(page("Seite", "<p>Kein Bericht hier. <a href='/site/media/katalog-2024.pdf'>Katalog</a></p>"))
        if path == "/site/investor-relations/":
            return html(page("Investor Relations", "<h1>Investor Relations</h1>"
                             "<a href='/site/investor-relations/finanzberichte/'>Finanzberichte</a> "
                             "<a href='/site/investor-relations/hauptversammlung/'>Hauptversammlung</a>"))
        if path == "/site/investor-relations/hauptversammlung/":
            return html(page("Hauptversammlung", "<a href='/site/media/einladung-hv-2026.pdf'>Einladung zur "
                             "Hauptversammlung 2026</a>"))
        if path == "/site/investor-relations/finanzberichte/":
            rows = []
            for year in range(2025, 2018, -1):
                de = f"<a href='/site/media/gb-{year}-de.pdf'>Geschäftsbericht {year}</a>"
                if year == 2022:
                    en = ""
                elif year == 2023:
                    en = f"<a href='{self.cdn_base}/files/annual-report-2023-en.pdf'>Annual Report 2023</a>"
                elif year == 2019:
                    en = "<a href='/site/media/broken-annual-report-2019-en.pdf'>Annual Report 2019</a>"
                else:
                    en = f"<a href='/site/media/annual-report-{year}-en.pdf'>Annual Report {year}</a>"
                rows.append(f"<tr><td>{year}</td><td>{de}</td><td>{en}</td></tr>")
            body = ("<h1>Finanzberichte</h1><h2>Geschäftsberichte</h2><table>" + "".join(rows) + "</table>"
                    "<h2>Weitere Berichte</h2><ul>"
                    "<li><a href='/site/media/hj-2025.pdf'>Halbjahresfinanzbericht 2025</a></li>"
                    "<li><a href='/site/media/nb-2024.pdf'>Nachhaltigkeitsbericht 2024</a></li>"
                    "<li><a href='/site/media/verguetung-2024.pdf'>Vergütungsbericht 2024</a></li>"
                    "<li><a href='/site/media/praesentation-gb-2024.pdf'>Präsentation zum Geschäftsbericht 2024</a></li>"
                    "<li><a href='/site/media/gb-2024-kurz.pdf'>Geschäftsbericht 2024 – Kurzfassung</a></li></ul>"
                    "<p><a href='/site/investor-relations/archiv/'>Archiv älterer Berichte</a> · "
                    "<a href='/site/intern/berichte/'>Interner Bereich (Berichte)</a></p>")
            return html(page("Finanzberichte – Beispiel Maschinenbau AG", body))
        if path == "/site/investor-relations/archiv/":
            rows = "".join(f"<tr><td>{y}</td><td><a href='/site/media/archiv/GB{str(y)[2:]}.pdf'>PDF (4 MB)</a></td></tr>"
                           for y in (2018, 2017, 2016, 2012))
            return html(page("Archiv", "<h1>Geschäftsberichte-Archiv</h1><table><tr><th>Jahr</th><th>Download</th>"
                                       f"</tr>{rows}</table>"))
        if path.startswith("/site/intern/"):
            return html(page("Intern", "<a href='/site/intern/gb-2015-entwurf.pdf'>Geschäftsbericht 2015 Entwurf</a>"))
        if path == "/site/media/broken-annual-report-2019-en.pdf":
            return html(page("Fehler", "<p>Diese Datei wurde verschoben.</p>"))
        if path.startswith("/site/media/") and path.endswith(".pdf"):
            return pdf(path)

        # GLEIF
        if path.startswith("/gleif/"):
            sub = path[len("/gleif"):]
            by_lei = {e["lei"]: e for e in ENTITIES}
            if sub == "/fuzzycompletions":
                term = (q.get("q") or [""])[0].lower()
                hits = [e for e in ENTITIES if term and term in e["name"].lower()]
                return j({"data": [{"type": "fuzzycompletions", "attributes": {"value": e["name"]},
                                    "relationships": {"lei-records": {"data": {"type": "lei-records", "id": e["lei"]}}}}
                                   for e in hits]})
            if sub == "/lei-records":
                if "filter[isin]" in q:
                    hits = [e for e in ENTITIES if e["isin"] == q["filter[isin]"][0]]
                elif "filter[lei]" in q:
                    wanted = q["filter[lei]"][0].split(",")
                    hits = [by_lei[l] for l in wanted if l in by_lei]
                elif "filter[fulltext]" in q:
                    term = q["filter[fulltext]"][0].lower()
                    hits = [e for e in ENTITIES if term in e["name"].lower()]
                else:
                    hits = []
                return j({"data": [gleif_record(e) for e in hits]})
            parts = sub.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "lei-records":
                entity = by_lei.get(parts[1])
                if not entity:
                    return j({"errors": [{"status": "404"}]}, 404)
                if len(parts) == 3 and parts[2] == "isins":
                    return j({"data": [{"type": "isins", "attributes": {"lei": entity["lei"], "isin": entity["isin"]}}]})
                return j({"data": gleif_record(entity)})
            return j({"errors": [{"status": "404"}]}, 404)

        # filings.xbrl.org
        if path == "/esef/api/filings":
            if "filter" not in q:  # universe listing
                data = [f for rows in ESEF.values() for f in rows]
                included = [esef_entity(e) for e in (COMPANY, PEER_IT, PEER_FR)]
                return j({"data": data, "included": included, "links": {}})
            if self.esef_mode == "reject_filter":
                return j({"errors": [{"detail": "filter not supported"}]}, 400)
            spec = json.loads(q["filter"][0])
            lei = spec[0]["val"]["val"]
            if self.esef_mode == "ignore_filter":
                data = [f for rows in ESEF.values() for f in rows]
            else:
                data = ESEF.get(lei, [])
            included = [esef_entity(e) for e in (COMPANY, PEER_IT, PEER_FR)]
            return j({"data": data, "included": included, "links": {"next": None}})
        if path == "/esef/api/entities":
            spec = json.loads(q["filter"][0])
            lei = spec[0]["val"]
            entity = next((e for e in (COMPANY, PEER_IT, PEER_FR) if e["lei"] == lei), None)
            if not entity:
                return j({"data": []})
            ent = esef_entity(entity)
            ent["relationships"] = {"filings": {"links": {"related": f"/esef/api/entities/{ent['id']}/filings"}}}
            return j({"data": [ent]})
        if path.startswith("/esef/api/entities/") and path.endswith("/filings"):
            eid = path.split("/")[4]
            entity = next(e for e in (COMPANY, PEER_IT, PEER_FR) if e["lei"][:6] == eid)
            return j({"data": ESEF[entity["lei"]], "included": [esef_entity(entity)]})
        if path.startswith("/esef/files/"):
            _, _, _, lei, period, idx, name = path.split("/")
            if name == "report.xhtml":
                return 200, "application/xhtml+xml", xhtml_bytes(f"ESEF {lei} {period} #{idx}")
            if name == "package.zip":
                return 200, "application/zip", zip_bytes({f"{lei}-{period}/reports/report.xhtml":
                                                          xhtml_bytes(f"ESEF {lei} {period} #{idx}")})
            if name == "report.json":
                return j({"documentInfo": {"documentType": "https://xbrl.org/2021/xbrl-json"}, "facts": {}})

        # Wikidata
        if path == "/wikidata/sparql":
            query = q.get("query", [""])[0]
            head = {"vars": []}
            if "VALUES ?ind" in query:
                rows = []
                for e in (COMPANY, PEER_IT, PEER_FR, PEER_US):
                    rows.append({"item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q9" + e["lei"][:4]},
                                 "itemLabel": {"type": "literal", "value": e["name"]},
                                 "lei": {"type": "literal", "value": e["lei"]},
                                 "isin": {"type": "literal", "value": e["isin"]},
                                 "cc": {"type": "literal", "value": e["country"]}})
                return j({"head": head, "results": {"bindings": rows}})
            if COMPANY["lei"] in query or COMPANY["isin"] in query:
                row = {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q99990001"},
                       "itemLabel": {"type": "literal", "value": COMPANY["name"]},
                       "website": {"type": "uri", "value": f"{base}/site/"},
                       "industry": {"type": "uri", "value": "http://www.wikidata.org/entity/Q99990002"},
                       "industryLabel": {"type": "literal", "value": "Verpackungsmaschinenbau"}}
                return j({"head": head, "results": {"bindings": [row]}})
            return j({"head": head, "results": {"bindings": []}})

        # Eurostat
        if path == "/eurostat/data/sts_inpr_a":
            return j(jsonstat())
        if path.startswith("/eurostat/data/"):
            return j({"error": {"status": "404", "label": "Dataset not found"}}, 404)

        # OpenAlex
        if path == "/openalex/works":
            return j({"meta": {"count": 2}, "results": [
                {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1234/test", "display_name":
                 "The European packaging machinery industry 2023", "publication_year": 2023, "type": "report",
                 "open_access": {"is_oa": True, "oa_url": f"{base}/oa/study-2023.pdf"},
                 "best_oa_location": {"pdf_url": f"{base}/oa/study-2023.pdf", "license": "cc-by",
                                      "landing_page_url": f"{base}/oa/", "source": {"display_name": "Test Journal"}},
                 "authorships": [{"author": {"display_name": "A. Autor"}}]},
                {"id": "https://openalex.org/W2", "display_name": "No PDF here", "publication_year": 2022,
                 "type": "article", "open_access": {"is_oa": True, "oa_url": f"{base}/oa/landing"},
                 "best_oa_location": {"pdf_url": None, "landing_page_url": f"{base}/oa/landing"}}]})
        if path == "/oa/study-2023.pdf":
            return pdf("OpenAlex study 2023")

        # industry association
        if path == "/assoc/":
            return html(page("Testverband", "<a href='/assoc/publikationen/'>Publikationen</a> "
                             "<a href='/assoc/karriere/'>Karriere</a>"))
        if path == "/assoc/publikationen/":
            items = [("branchenbericht-2024.pdf", "Branchenbericht Verpackungsmaschinen 2024"),
                     ("maschinenbau-in-zahlen-2023.pdf", "Maschinenbau in Zahlen 2023"),
                     ("konjunktur-herbst-2025.pdf", "Konjunkturumfrage Herbst 2025"),
                     ("einladung-2025.pdf", "Einladung zur Mitgliederversammlung 2025"),
                     ("jahresbericht-2012.pdf", "Jahresbericht 2012"),
                     ("satzung.pdf", "Satzung")]
            links = "".join(f"<li><a href='/assoc/files/{f}'>{t}</a></li>" for f, t in items)
            return html(page("Publikationen", f"<h1>Publikationen</h1><ul>{links}</ul>"))
        if path.startswith("/assoc/files/"):
            return pdf(path)

        # ESMA FIRDS
        if path == "/esma/solr":
            return j({"response": {"numFound": 2, "docs": [
                {"file_name": "FULINS_E_20260920_01of01.zip", "file_type": "FULINS",
                 "download_link": f"{base}/esma/files/FULINS_E_20260920_01of01.zip",
                 "publication_date": "2026-09-20T00:00:00Z"},
                {"file_name": "FULINS_D_20260920_01of01.zip", "file_type": "FULINS",
                 "download_link": f"{base}/esma/files/FULINS_D_20260920_01of01.zip",
                 "publication_date": "2026-09-20T00:00:00Z"}]}})
        if path == "/esma/files/FULINS_E_20260920_01of01.zip":
            return 200, "application/zip", firds_zip()

        # Brave search
        if path == "/brave":
            query = q.get("q", [""])[0]
            results = []
            if "2016" in query:
                results = [
                    {"title": "Geschäftsbericht 2016 – Beispiel Maschinenbau AG", "url": f"{base}/site/media/archiv/GB16.pdf",
                     "description": "Geschäftsbericht 2016"},
                    {"title": "Beispiel Maschinenbau Geschäftsbericht 2016", "url": "https://mirror.invalid/gb-2016.pdf",
                     "description": "Kopie"}]
            return j({"web": {"results": results}})

        return 404, "text/plain", b"not found"
