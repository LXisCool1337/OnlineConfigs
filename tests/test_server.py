"""HTTP API, live progress stream and security checks of the portal server."""

import http.client
import io
import json
import shutil
import tempfile
import threading
import time
import unittest
import re
import zipfile
from pathlib import Path

from portal import diagnostics
from portal.app import App
from portal.server import serve
from tests.fakeweb import COMPANY, TODAY, FakeWeb


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = FakeWeb().__enter__()
        cls.tmp = Path(tempfile.mkdtemp())
        sources = cls.tmp / "sources.json"
        sources.write_text("{}")
        cls.app = App(cls.web.settings(str(cls.tmp / "library"), industry_sources_file=str(sources)))
        cls.server = serve(cls.app, "127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.app.jobs.start(workers=1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.app.close()
        cls.web.__exit__(None, None, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        return resp, payload

    def json(self, method, path, body=None, headers=None, status=200):
        resp, payload = self.request(method, path, body, headers)
        self.assertEqual(resp.status, status, payload[:300])
        return json.loads(payload)

    def wait_for(self, job_id, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.json("GET", f"/api/jobs/{job_id}")["job"]
            if job["status"] in ("done", "failed", "cancelled"):
                return job
            time.sleep(0.3)
        self.fail("job did not finish")

    def test_01_ui_and_meta(self):
        resp, body = self.request("GET", "/")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"EU-Report-Portal", body)
        self.assertIn("script-src 'self'", resp.getheader("Content-Security-Policy"))
        resp, body = self.request("GET", "/static/js/main.js")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"import", body)
        for code in ("de", "en"):
            resp, body = self.request("GET", f"/static/i18n/{code}.json")
            self.assertEqual(resp.status, 200)
            self.assertIn("nav.company", json.loads(body))
        health = self.json("GET", "/api/health")
        self.assertTrue(health["version"])
        self.assertIn("pdftotext", health)
        self.assertTrue(health["library_dir"].endswith("library"))
        meta = self.json("GET", "/api/meta")
        self.assertEqual(len(meta["nace"]), 88)
        self.assertEqual(len(meta["countries"]), 30)

    def test_02_company_flow(self):
        results = self.json("GET", "/api/search?q=Beispiel")["results"]
        self.assertEqual(results[0]["lei"], COMPANY["lei"])
        by_isin = self.json("GET", f"/api/search?q={COMPANY['isin']}")["results"]
        self.assertEqual(by_isin[0]["lei"], COMPANY["lei"])
        self.json("POST", "/api/companies", {"lei": COMPANY["lei"]})
        self.json("PATCH", f"/api/companies/{COMPANY['lei']}", {"nace": "28.29", "watch": True})
        self.json("PATCH", f"/api/companies/{COMPANY['lei']}", {"ir_url": "ftp://x"}, status=400)

        job_id = self.json("POST", "/api/jobs", {"kind": "company", "params": {
            "lei": COMPANY["lei"], "today": TODAY, "include": {"industry": False}}})["id"]

        resp, stream = self.request("GET", f"/api/jobs/{job_id}/stream")
        self.assertEqual(resp.getheader("Content-Type"), "text/event-stream; charset=utf-8")
        self.assertIn(b"event: end", stream)
        self.assertIn("Abdeckung: 10/10".encode(), stream)
        job = self.wait_for(job_id)
        self.assertEqual(job["status"], "done", job.get("error"))
        # The UI builds its step checklist from stage events and skip notes.
        events = self.json("GET", f"/api/jobs/{job_id}")["events"]
        stages = [e["data"]["step"] for e in events if e["level"] == "stage" and "step" in (e.get("data") or {})]
        self.assertEqual(stages, ["resolve", "enrich", "esef", "irsite", "select", "download", "analyze"])
        skips = {e["data"]["step"]: e["data"]["skipped"] for e in events if (e.get("data") or {}).get("skipped")}
        self.assertEqual(skips, {"websearch": "not_needed"})   # all PDF years found on the website
        self.assertEqual(job["title"], COMPANY["name"])

        detail = self.json("GET", f"/api/companies/{COMPANY['lei']}")
        self.assertEqual(detail["company"]["nace"], "28.29")
        self.assertEqual(detail["coverage"]["covered"], 10)
        self.assertEqual(len(detail["documents"]), 22)

        pdf = next(d for d in detail["documents"] if d["category"] == "annual_report")
        resp, body = self.request("GET", f"/api/documents/{pdf['id']}/file")
        self.assertEqual((resp.status, resp.getheader("Content-Type")), (200, "application/pdf"))
        self.assertTrue(body.startswith(b"%PDF"))
        report = next(d for d in detail["documents"] if d["category"] == "esef_report")
        resp, _ = self.request("GET", f"/api/documents/{report['id']}/file")
        self.assertEqual(resp.getheader("Content-Security-Policy"), "sandbox")

        resp, body = self.request("GET", f"/api/companies/{COMPANY['lei']}/export")
        self.assertEqual(resp.status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            names = zf.namelist()
        self.assertEqual(len(names), 23)  # 22 documents + manifest.json
        self.assertTrue(any(n.endswith("manifest.json") for n in names))

        library = self.json("GET", "/api/library")
        self.assertEqual(library["companies"][0]["years"], 10)
        row = library["companies"][0]
        self.assertEqual((row["covered"], row["target"]), (10, 10))
        self.assertGreater(row["bytes"], 0)
        self.assertTrue(row["has_financials"])
        self.assertTrue(row["last_update"])
        self.assertEqual(library["watchlist"][0]["lei"], COMPANY["lei"])

    def test_03_security(self):
        resp, _ = self.request("GET", "/api/health", headers={"Host": "evil.example"})
        self.assertEqual(resp.status, 421)
        resp, _ = self.request("POST", "/api/jobs", body=None, headers={"Content-Type": "text/plain"})
        self.assertEqual(resp.status, 415)
        resp, _ = self.request("POST", "/api/jobs", {"kind": "company", "params": {"lei": COMPANY["lei"]}},
                               headers={"Origin": "https://evil.example"})
        self.assertEqual(resp.status, 403)
        resp, _ = self.request("GET", "/static/../config.py")
        self.assertEqual(resp.status, 404)
        resp, _ = self.request("GET", "/api/documents/999999/file")
        self.assertEqual(resp.status, 404)
        self.json("POST", "/api/jobs", {"kind": "shell", "params": {}}, status=400)
        self.json("POST", "/api/jobs", {"kind": "batch", "params": {"limit": 5000}}, status=400)

    def test_04_settings_and_token(self):
        data = self.json("PUT", "/api/settings", {"contact_email": "neu@example.org", "brave_api_key": "geheim",
                                                   "library_dir": "/etc"})
        self.assertEqual(data["settings"]["brave_api_key"], "********")
        self.assertNotEqual(self.app.settings.library_dir, "/etc")          # not editable from the UI
        self.assertIn("neu@example.org", self.app.http.user_agent)
        self.json("PUT", "/api/settings", {"brave_api_key": "********"})
        self.assertEqual(self.app.settings.brave_api_key, "geheim")          # masked value keeps the secret
        self.json("PUT", "/api/settings", {"contact_email": "test@example.org", "brave_api_key": ""})

        self.app.settings.access_token = "s3cret"
        try:
            resp, _ = self.request("GET", "/api/health")
            self.assertEqual(resp.status, 401)
            self.json("GET", "/api/health", headers={"Authorization": "Bearer s3cret"})
            self.json("GET", "/api/health?token=s3cret")
        finally:
            self.app.settings.access_token = ""

    def test_05_key_figures_search_overview(self):
        lei = COMPANY["lei"]
        data = self.json("GET", f"/api/companies/{lei}/financials")
        self.assertEqual(data["years"], list(range(2019, 2026)))
        self.assertEqual(data["currency"], "EUR")
        resp, body = self.request("GET", f"/api/companies/{lei}/financials.csv?style=de")
        self.assertEqual(resp.getheader("Content-Type"), "text/csv; charset=utf-8")
        self.assertTrue(body.startswith("\ufeff".encode("utf-8")))
        self.assertIn("revenue;Umsatz;EUR".encode(), body)
        self.json("POST", f"/api/companies/{lei}/financials", {})

        hits = self.json("GET", "/api/fulltext?q=Z%C3%B6lle")
        self.assertEqual(len(hits["results"]), 2)
        self.assertEqual(hits["results"][0]["company"], COMPANY["name"])
        self.assertEqual(self.json("GET", "/api/fulltext?q=%22%22%20*")["results"], [])

        compare = self.json("GET", f"/api/industries/28/compare?lei={lei}")
        self.assertEqual(compare["rows"][0]["lei"], lei)

        overview = self.json("GET", "/api/overview")
        self.assertEqual(overview["stats"]["companies"], 1)
        self.assertEqual(overview["stats"]["with_financials"], 1)
        self.assertEqual(overview["gaps"], [])
        self.assertEqual(overview["watchlist"][0]["latest"], 2025)

        report = next(d for d in self.json("GET", f"/api/companies/{lei}")["documents"]
                      if d["category"] == "esef_report" and d["fiscal_year"] == 2025)
        self.json("DELETE", f"/api/documents/{report['id']}?block=1")
        self.assertIn(report["source_url"], self.app.db.blocked_urls())
        detail = self.json("GET", f"/api/companies/{lei}")
        self.assertNotIn(report["id"], [d["id"] for d in detail["documents"]])
        data = self.json("GET", f"/api/companies/{lei}/financials")
        self.assertEqual(data["years"], list(range(2019, 2026)))  # 2025 still comes from the ESEF package

    def test_06_notes_sources_compare_excel(self):
        lei = COMPANY["lei"]
        self.assertEqual(self.json("GET", f"/api/companies/{lei}/notes")["text"], "")
        saved = self.json("PUT", f"/api/companies/{lei}/notes", {"text": "Auftragseingang prüfen"})
        self.assertTrue(saved["updated_at"])
        self.assertEqual(self.json("GET", f"/api/companies/{lei}")["notes"]["text"], "Auftragseingang prüfen")
        self.json("PUT", f"/api/companies/{lei}/notes", {"text": "x" * 100_001}, status=413)
        self.json("PUT", "/api/companies/00000000000000000000/notes", {"text": "x"}, status=404)

        sources = self.json("GET", "/api/diagnostics")["sources"]
        self.assertEqual({r["key"] for r in sources}, {"gleif", "esef", "wikidata", "eurostat", "openalex", "esma"})
        for row in sources:
            self.assertIn(row["code"], ("ok", "http_error"), row)   # the fake web answers every host
            self.assertGreaterEqual(row["ms"], 0)
        dead = diagnostics._check(self.app.context(), "gleif", "http://127.0.0.1:9/lei-records")
        self.assertEqual(dead["code"], "unreachable")

        data = self.json("GET", f"/api/compare?leis={lei},kaputt,{lei.lower()}")
        self.assertEqual([c["lei"] for c in data["companies"]], [lei])
        series = data["companies"][0]
        self.assertEqual(series["currency"], "EUR")
        revenue = next(m for m in series["metrics"] if m["key"] == "revenue")
        self.assertGreater(len(revenue["values"]), 3)
        self.assertEqual(data["rows"][0]["lei"], lei)
        self.assertIn("ebit_margin", data["median"])     # ratios only: amounts differ in currency
        self.json("GET", "/api/compare/export.xlsx", status=400)
        candidates = {c["lei"]: c for c in self.json("GET", "/api/compare/candidates")["companies"]}
        self.assertTrue(candidates[lei]["in_library"])
        self.assertEqual(candidates[lei]["latest"], 2025)

        for path, sheets in ((f"/api/companies/{lei}/financials.xlsx", ["Kennzahlen", "Dokumente", "Info"]),
                             (f"/api/compare/export.xlsx?leis={lei}", ["Übersicht"])):
            resp, body = self.request("GET", path)
            self.assertEqual(resp.status, 200, body[:200])
            self.assertEqual(resp.getheader("Content-Type"),
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.assertIn("attachment", resp.getheader("Content-Disposition"))
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                self.assertIsNone(zf.testzip())
                names = re.findall(r'<sheet name="([^"]+)"', zf.read("xl/workbook.xml").decode("utf-8"))
            self.assertEqual(names[:len(sheets)], sheets)


if __name__ == "__main__":
    unittest.main()
