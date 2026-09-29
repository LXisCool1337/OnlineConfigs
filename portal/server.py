"""Web portal: JSON API, live job progress (Server-Sent Events), document viewer and the static UI.

Bound to 127.0.0.1 by default. Write requests must be JSON (blocks cross-site form posts), the Host
header is checked (blocks DNS rebinding), and an access token can be required when exposed.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import re
import sqlite3
import time
import traceback
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from . import financials, fulltext
from .config import PACKAGE_DIR
from .identifiers import COUNTRY_NAMES, EU_EEA, nace_divisions, nace_label, normalize_nace
from .pipeline import CATEGORY_LABELS, compute_coverage, final_window
from .resolver import NotFound, Resolver
from .connectors.curated import Curated

STATIC_DIR = PACKAGE_DIR / "static"
MIME_BY_KIND = {"pdf": "application/pdf", "xhtml": "application/xhtml+xml", "html": "text/html",
                "xml": "application/xml", "zip": "application/zip", "json": "application/json",
                "csv": "text/csv; charset=utf-8", "gzip": "application/gzip"}
INLINE_KINDS = {"pdf", "xhtml", "html", "xml"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "SAMEORIGIN",
}
UI_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
          "frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _int(value, name: str, default: int | None = None) -> int | None:
    """A whole number from a query string or JSON body; 400 instead of a crash for anything else."""
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not re.fullmatch(r"-?\d{1,9}", str(value).strip()):
        raise ApiError(400, f"{name}: ganze Zahl erwartet")
    return int(value)


def make_handler(app):
    routes = []

    def route(method: str, pattern: str):
        def register(fn):
            routes.append((method, re.compile(f"^{pattern}$"), fn))
            return fn
        return register

    # --- API endpoints ----------------------------------------------------------------

    @route("GET", r"/api/health")
    def health(h, m):
        return {"ok": True, "contact_email_set": bool(app.settings.contact_email),
                "search_enabled": bool(app.settings.search_provider)}

    @route("GET", r"/api/search")
    def search(h, m):
        q = (h.query.get("q") or [""])[0].strip()
        if len(q) < 2:
            return {"results": [], "warning": None}
        results, warning = Resolver(app.context()).search(q, limit=15)
        return {"results": [_company_summary(c) for c in results], "warning": warning}

    @route("GET", r"/api/meta")
    def meta(h, m):
        return {"nace": nace_divisions(), "countries": [{"code": c, "name": COUNTRY_NAMES.get(c, c)}
                                                        for c in sorted(EU_EEA, key=lambda c: COUNTRY_NAMES.get(c, c))],
                "categories": CATEGORY_LABELS}

    @route("GET", r"/api/companies/(?P<lei>[A-Z0-9]{20})")
    def company(h, m):
        lei = m["lei"]
        record = app.db.company(lei)
        if not record:
            raise ApiError(404, "Unternehmen nicht im Katalog – bitte zuerst suchen")
        docs = app.db.company_documents(lei)
        found = {d["fiscal_year"] for d in docs if d["fiscal_year"]}
        window = final_window(found, app.settings.years, date.today())
        return {"company": {**record, "nace_label": nace_label(record.get("nace"))},
                "coverage": compute_coverage(docs, window),
                "documents": [_doc(d) for d in docs],
                "jobs": app.db.query("SELECT id, kind, status, progress, created_at FROM jobs "
                                     "WHERE params LIKE ? ORDER BY id DESC LIMIT 5", (f'%"{lei}"%',))}

    @route("POST", r"/api/companies")
    def company_add(h, m):
        body = h.json_body()
        try:
            record = Resolver(app.context()).resolve(query=body.get("query"), lei=body.get("lei"))
        except NotFound as err:
            raise ApiError(404, str(err)) from None
        return {"company": record}

    @route("PATCH", r"/api/companies/(?P<lei>[A-Z0-9]{20})")
    def company_update(h, m):
        body = h.json_body()
        for key in ("ir_url", "website", "nace", "keywords"):
            value = body.get(key)
            if key == "nace" and isinstance(value, int) and not isinstance(value, bool):
                value = str(value)  # {"nace": 28}
            if value is not None and not isinstance(value, str):
                raise ApiError(400, f"{key}: Text erwartet")
            if key in body:
                body[key] = value.strip() if value is not None else None
        if "nace" in body and body["nace"]:
            nace = normalize_nace(body["nace"])
            if not nace:
                raise ApiError(400, "Ungültiger NACE-Code")
            body["nace"] = nace
        for key in ("ir_url", "website"):
            if body.get(key) and not re.match(r"^https?://", body[key], re.I):
                raise ApiError(400, f"{key}: bitte vollständige URL mit https:// angeben")
        record = app.db.update_company_fields(m["lei"], body)
        if not record:
            raise ApiError(404, "Unternehmen unbekannt")
        return {"company": record}

    @route("GET", r"/api/companies/(?P<lei>[A-Z0-9]{20})/export")
    def company_export(h, m):
        record = app.db.company(m["lei"])
        if not record:
            raise ApiError(404, "Unternehmen unbekannt")
        folder = app.library.company_dir(record)
        if not folder.exists():
            raise ApiError(404, "Noch keine Dokumente vorhanden")
        path = app.library.build_zip(folder, f"{record['name']}_{record['lei']}")
        h.send_file(path, "application/zip", attachment=True)

    @route("GET", r"/api/industries/(?P<nace>[0-9.]{2,5})")
    def industry(h, m):
        nace = normalize_nace(m["nace"])
        if not nace:
            raise ApiError(400, "Ungültiger NACE-Code")
        return {"nace": nace, "label": nace_label(nace), "documents": [_doc(d) for d in app.db.industry_documents(nace)],
                "sources": Curated(app.context()).sources(nace)}

    @route("GET", r"/api/industries/(?P<nace>[0-9.]{2,5})/export")
    def industry_export(h, m):
        nace = normalize_nace(m["nace"])
        folder = app.library.industry_dir(nace) if nace else None
        if not folder or not folder.exists():
            raise ApiError(404, "Noch keine Branchendokumente vorhanden")
        h.send_file(app.library.build_zip(folder, f"branche_nace_{nace}"), "application/zip", attachment=True)

    @route("POST", r"/api/industries/(?P<nace>[0-9.]{2,5})/sources")
    def industry_source_add(h, m):
        nace = normalize_nace(m["nace"])
        body = h.json_body()
        url = (body.get("url") or "").strip()
        if not nace or not re.match(r"^https?://", url, re.I):
            raise ApiError(400, "Bitte NACE-Code und vollständige URL angeben")
        source_id = app.db.add_industry_source(nace[:2], (body.get("name") or "").strip()[:120], url)
        return {"id": source_id}

    @route("DELETE", r"/api/sources/(?P<sid>\d+)")
    def industry_source_delete(h, m):
        app.db.delete_industry_source(int(m["sid"]))
        return {"ok": True}

    @route("GET", r"/api/library")
    def library(h, m):
        return {"companies": [_company_summary(c) | {"documents": c["documents"], "years": c["years"]}
                              for c in app.db.library_companies()],
                "industries": [{**i, "label": nace_label(i["nace"])} for i in app.db.library_industries()],
                "watchlist": [_company_summary(c) for c in app.db.query("SELECT * FROM companies WHERE watch = 1")]}

    @route("GET", r"/api/documents/(?P<doc>\d+)/file")
    def document_file(h, m):
        doc = app.db.document(int(m["doc"]))
        if not doc or not doc.get("path"):
            raise ApiError(404, "Dokument nicht gefunden")
        path = app.library.absolute(doc["path"])
        if not path.exists():
            raise ApiError(410, "Datei fehlt im Bibliotheksordner")
        kind = doc.get("mime") or "pdf"
        forced = (h.query.get("download") or ["0"])[0] == "1"
        h.send_file(path, MIME_BY_KIND.get(kind, "application/octet-stream"),
                    attachment=forced or kind not in INLINE_KINDS, sandbox=kind in ("xhtml", "html", "xml"))

    @route("DELETE", r"/api/documents/(?P<doc>\d+)")
    def document_delete(h, m):
        doc = app.db.document(int(m["doc"]))
        if not doc:
            raise ApiError(404, "Dokument nicht gefunden")
        if doc.get("path"):
            app.library.absolute(doc["path"]).unlink(missing_ok=True)
        app.db.delete_document(doc["id"])
        blocked = (h.query.get("block") or ["0"])[0] == "1"
        if blocked:
            app.db.block_url(doc["source_url"], doc.get("lei"), "als falsch markiert")
        if doc.get("lei") and doc["category"] in ("esef_report", "peer_report", "esef_package", "peer_report_package"):
            financials.extract(app.context(), doc["lei"])
        return {"ok": True, "blocked": blocked}

    # --- key figures, comparison, full text, overview --------------------------------

    @route("GET", r"/api/companies/(?P<lei>[A-Z0-9]{20})/financials")
    def company_financials(h, m):
        return financials.table_for(app.db, m["lei"])

    @route("POST", r"/api/companies/(?P<lei>[A-Z0-9]{20})/financials")
    def company_financials_refresh(h, m):
        financials.extract(app.context(), m["lei"])
        return financials.table_for(app.db, m["lei"])

    @route("GET", r"/api/companies/(?P<lei>[A-Z0-9]{20})/financials\.csv")
    def company_financials_csv(h, m):
        style = (h.query.get("style") or ["de"])[0]
        record = app.db.company(m["lei"]) or {"name": m["lei"]}
        h.send_text(financials.csv_for(app.db, m["lei"], "en" if style == "en" else "de"),
                    f"kennzahlen_{record['name']}_{m['lei']}.csv", bom=style != "en")

    @route("GET", r"/api/industries/(?P<nace>[0-9.]{2,5})/compare")
    def industry_compare(h, m):
        nace = normalize_nace(m["nace"])
        if not nace:
            raise ApiError(400, "Ungültiger NACE-Code")
        focus = (h.query.get("lei") or [None])[0]
        return financials.comparison(app.db, nace, focus if focus and re.fullmatch(r"[A-Z0-9]{20}", focus) else None)

    @route("GET", r"/api/fulltext")
    def fulltext_search(h, m):
        q = (h.query.get("q") or [""])[0].strip()
        if len(q) < 2:
            return {"results": [], "pdftotext": fulltext.pdftotext_available()}
        get = lambda k: (h.query.get(k) or [None])[0]  # noqa: E731
        try:
            hits = fulltext.search(app.db, q, lei=get("lei"), nace=normalize_nace(get("nace")) if get("nace") else None,
                                   year_from=_int(get("from"), "from"), year_to=_int(get("to"), "to"))
        except sqlite3.OperationalError as err:  # malformed query reaching FTS5
            raise ApiError(400, f"Suchanfrage nicht verstanden: {err}") from None
        names = {}
        for hit in hits:
            if hit["lei"] and hit["lei"] not in names:
                names[hit["lei"]] = (app.db.company(hit["lei"]) or {}).get("name")
            hit["company"] = names.get(hit["lei"])
            hit["category_label"] = CATEGORY_LABELS.get(hit["category"], hit["category"])
        stats = app.db.one("SELECT COUNT(*) AS docs FROM doc_index WHERE status = 'ok'")
        return {"results": hits, "indexed": stats["docs"], "pdftotext": fulltext.pdftotext_available()}

    @route("GET", r"/api/overview")
    def overview(h, m):
        db = app.db
        stats = db.one("SELECT COUNT(*) AS documents, IFNULL(SUM(size), 0) AS bytes, "
                       "COUNT(DISTINCT CASE WHEN scope = 'company' THEN lei END) AS companies, "
                       "COUNT(DISTINCT CASE WHEN scope = 'industry' THEN nace END) AS industries FROM documents")
        stats["indexed"] = db.one("SELECT COUNT(*) AS n FROM doc_index WHERE status = 'ok'")["n"]
        stats["with_financials"] = db.one("SELECT COUNT(DISTINCT lei) AS n FROM financials")["n"]
        recent = db.query("SELECT d.id, d.lei, d.nace, d.category, d.fiscal_year, d.fy_label, d.title, d.size, "
                          "d.created_at, c.name AS company FROM documents d LEFT JOIN companies c ON c.lei = d.lei "
                          "ORDER BY d.id DESC LIMIT 8")
        for r in recent:
            r["category_label"] = CATEGORY_LABELS.get(r["category"], r["category"])
        gaps = []
        today = date.today()
        docs_by_lei: dict[str, list[dict]] = {}
        for d in db.query("SELECT d.lei, d.category, d.fiscal_year, c.name FROM documents d "
                          "JOIN companies c ON c.lei = d.lei WHERE d.scope = 'company'"):
            docs_by_lei.setdefault(d["lei"], []).append(d)
        for lei, docs in docs_by_lei.items():
            found = {d["fiscal_year"] for d in docs if d["fiscal_year"]}
            cov = compute_coverage(docs, final_window(found, app.settings.years, today))
            if cov["missing"]:
                gaps.append({"lei": lei, "name": docs[0]["name"], "covered": cov["covered"], "target": cov["target"],
                             "missing": cov["missing"]})
        gaps.sort(key=lambda g: (g["covered"], g["name"]))
        watch = db.query("SELECT c.lei, c.name, (SELECT MAX(d.fiscal_year) FROM documents d WHERE d.lei = c.lei "
                         "AND d.scope = 'company') AS latest FROM companies c WHERE c.watch = 1 ORDER BY c.name")
        nxt = app.jobs.next_auto_refresh()
        return {"stats": stats, "recent": recent, "gaps": gaps[:12],
                "active": db.query("SELECT id, kind, title, status, progress, stage FROM jobs "
                                   "WHERE status IN ('queued', 'running', 'cancelling') ORDER BY id LIMIT 8"),
                "watchlist": watch,
                "auto_refresh": {"days": app.settings.auto_refresh_days,
                                 "next": datetime.fromtimestamp(nxt, timezone.utc).isoformat() if nxt else None},
                "pdftotext": fulltext.pdftotext_available()}

    @route("GET", r"/api/jobs")
    def jobs(h, m):
        return {"jobs": app.db.jobs(limit=100)}

    @route("POST", r"/api/jobs")
    def job_create(h, m):
        body = h.json_body()
        kind = body.get("kind")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            raise ApiError(400, "params: JSON-Objekt erwartet")
        if kind not in ("company", "industry", "batch", "refresh", "universe", "index"):
            raise ApiError(400, "Unbekannter Auftragstyp")
        if kind == "company" and not (params.get("lei") or params.get("query")):
            raise ApiError(400, "Bitte ein Unternehmen wählen")
        if kind == "industry" and not normalize_nace(params.get("nace")):
            raise ApiError(400, "Bitte einen gültigen NACE-Code wählen")
        if kind == "batch" and (_int(params.get("limit"), "limit") or 50) > 500 and not params.get("confirm_large"):
            raise ApiError(400, "Mehr als 500 Unternehmen: bitte ausdrücklich bestätigen")
        return {"id": app.jobs.submit(kind, params, title=body.get("title"))}

    @route("GET", r"/api/jobs/(?P<job>\d+)")
    def job_detail(h, m):
        job = app.db.job(int(m["job"]))
        if not job:
            raise ApiError(404, "Auftrag nicht gefunden")
        after = _int((h.query.get("after") or [None])[0], "after", 0)
        return {"job": job, "events": app.db.job_events(job["id"], after=after)}

    @route("POST", r"/api/jobs/(?P<job>\d+)/cancel")
    def job_cancel(h, m):
        return {"ok": app.jobs.cancel(int(m["job"]))}

    @route("GET", r"/api/jobs/(?P<job>\d+)/stream")
    def job_stream(h, m):
        h.stream_job(int(m["job"]), _int((h.query.get("after") or [None])[0], "after", 0))

    @route("GET", r"/api/universe")
    def universe(h, m):
        stats = app.db.universe_stats()
        stats["by_country"] = [{**r, "name": COUNTRY_NAMES.get(r["country"] or "", r["country"])}
                               for r in stats["by_country"]]
        return stats

    @route("GET", r"/api/settings")
    def settings_get(h, m):
        return {"settings": app.settings.public_dict()}

    @route("PUT", r"/api/settings")
    def settings_put(h, m):
        body = h.json_body()
        try:
            changed = app.save_settings(body)
        except (ValueError, TypeError) as err:
            raise ApiError(400, f"Ungültiger Wert: {err}") from None
        return {"changed": changed, "settings": app.settings.public_dict()}

    # --- request handler --------------------------------------------------------------

    class Handler(BaseHTTPRequestHandler):
        server_version = "EU-Report-Portal"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep the console quiet; jobs log to the database
            pass

        def _allowed_host(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            port = self.server.server_address[1]
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
            allowed |= {h.lower() for h in app.settings.allowed_hosts}
            return host in allowed

        def _authorized(self) -> bool:
            token = app.settings.access_token
            if not token:
                return True
            header = self.headers.get("Authorization", "")
            given = header[7:] if header.startswith("Bearer ") else (self.query.get("token") or [""])[0]
            cookie = re.search(r"(?:^|;\s*)portal_token=([^;]+)", self.headers.get("Cookie", ""))
            expected = token.encode("utf-8")
            # compare_digest: the time taken does not reveal how many leading characters were right
            return hmac.compare_digest(given.encode("utf-8"), expected) or (
                cookie is not None and hmac.compare_digest(cookie.group(1).encode("utf-8"), expected))

        def _dispatch(self, method: str) -> None:
            parts = urlsplit(self.path)
            self.query = parse_qs(parts.query)
            path = parts.path
            try:
                if not self._allowed_host():
                    raise ApiError(421, "Unbekannter Host")
                if path == "/" or path.startswith("/static/"):
                    if method != "GET":
                        raise ApiError(405, "Methode nicht erlaubt")
                    return self.send_static("index.html" if path == "/" else path[len("/static/"):])
                if not path.startswith("/api/"):
                    raise ApiError(404, "Nicht gefunden")
                if not self._authorized():
                    raise ApiError(401, "Zugriffstoken fehlt oder ist falsch")
                if method in ("POST", "PUT", "PATCH", "DELETE"):
                    origin = self.headers.get("Origin")
                    if origin and urlsplit(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
                        raise ApiError(403, "Fremde Herkunft")
                    if method != "DELETE" and "application/json" not in self.headers.get("Content-Type", ""):
                        raise ApiError(415, "Nur JSON-Anfragen")
                for verb, pattern, fn in routes:
                    match = pattern.match(path)
                    if match and verb == method:
                        result = fn(self, match.groupdict())
                        if result is not None:
                            self.send_json(result)
                        return
                raise ApiError(404, "Unbekannter Endpunkt")
            except ApiError as err:
                self.send_json({"error": str(err)}, err.status)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as err:  # noqa: BLE001
                traceback.print_exc()
                self.send_json({"error": f"Interner Fehler: {err}"}, 500)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_PATCH(self):
            self._dispatch("PATCH")

        def do_DELETE(self):
            self._dispatch("DELETE")

        # --- helpers --------------------------------------------------------------------

        def json_body(self) -> dict:
            raw_length = (self.headers.get("Content-Length") or "0").strip()
            if not re.fullmatch(r"[0-9]{1,12}", raw_length):  # "-1" would block reading until the client hangs up
                raise ApiError(400, "Ungültige Content-Length")
            length = int(raw_length)
            if length > 1_000_000:
                raise ApiError(413, "Anfrage zu groß")
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                raise ApiError(400, "Ungültiges JSON") from None
            if not isinstance(data, dict):
                raise ApiError(400, "JSON-Objekt erwartet")
            return data

        def _headers(self, extra: dict | None = None) -> None:
            for key, value in {**SECURITY_HEADERS, **(extra or {})}.items():
                self.send_header(key, value)

        def send_json(self, payload, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._headers()
            self.end_headers()
            self.wfile.write(body)

        def send_static(self, name: str) -> None:
            path = (STATIC_DIR / name).resolve()
            if STATIC_DIR.resolve() not in path.parents or not path.is_file():
                raise ApiError(404, "Nicht gefunden")
            body = path.read_bytes()
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "text/javascript"):
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self._headers({"Content-Security-Policy": UI_CSP})
            self.end_headers()
            self.wfile.write(body)

        def send_text(self, text: str, filename: str, *, bom: bool = False) -> None:
            body = ("\ufeff" if bom else "").encode("utf-8") + text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
            self._headers()
            self.end_headers()
            self.wfile.write(body)

        def send_file(self, path, ctype: str, *, attachment: bool = False, sandbox: bool = False) -> None:
            size = path.stat().st_size
            disposition = "attachment" if attachment else "inline"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(path.name)}")
            extra = {"Content-Security-Policy": "sandbox"} if sandbox else {}
            self._headers(extra)
            self.end_headers()
            with path.open("rb") as fh:
                while chunk := fh.read(1 << 16):
                    self.wfile.write(chunk)

        def stream_job(self, job_id: int, after: int) -> None:
            if not app.db.job(job_id):
                raise ApiError(404, "Auftrag nicht gefunden")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self._headers()
            self.end_headers()
            self.close_connection = True
            last_beat = time.monotonic()
            while True:
                job = app.db.job(job_id)
                events = app.db.job_events(job_id, after=after, limit=200)
                for event in events:
                    after = event["id"]
                    self._sse("log", event)
                self._sse("job", job)
                if job["status"] in ("done", "failed", "cancelled") and not events:
                    self._sse("end", {"status": job["status"]})
                    return
                if time.monotonic() - last_beat > 15:
                    self.wfile.write(b": keep-alive\n\n")
                    last_beat = time.monotonic()
                self.wfile.flush()
                time.sleep(0.6)

        def _sse(self, name: str, payload) -> None:
            data = json.dumps(payload, ensure_ascii=False, default=str)
            self.wfile.write(f"event: {name}\ndata: {data}\n\n".encode("utf-8"))

    return Handler


def _company_summary(c: dict) -> dict:
    keys = ("lei", "name", "country", "isins", "website", "ir_url", "nace", "has_esef", "listed", "watch",
            "in_library", "eu")
    out = {k: c.get(k) for k in keys}
    out["country_name"] = COUNTRY_NAMES.get(c.get("country") or "", c.get("country"))
    return out


def _doc(d: dict) -> dict:
    out = {k: d.get(k) for k in ("id", "category", "fiscal_year", "fy_label", "period_end", "language", "title",
                                 "source", "source_url", "size", "mime", "lei", "created_at", "path")}
    out["category_label"] = CATEGORY_LABELS.get(d["category"], d["category"])
    out["meta"] = {k: v for k, v in (d.get("meta") or {}).items() if k in ("peer_name", "publisher", "doi", "license",
                                                                         "dataset", "rows", "flags", "via")}
    return out


def serve(app, host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    host = host or app.settings.host
    port = port if port is not None else app.settings.port
    if host not in ("127.0.0.1", "localhost", "::1") and not app.settings.access_token:
        raise SystemExit("Für andere Adressen als 127.0.0.1 muss access_token gesetzt sein (PORTAL_ACCESS_TOKEN).")
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server
