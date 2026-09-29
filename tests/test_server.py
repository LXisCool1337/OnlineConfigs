"""HTTP API, live progress stream and security checks of the portal server."""

import http.client
import io
import json
import shutil
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

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
        resp, _ = self.request("GET", "/static/app.js")
        self.assertEqual(resp.status, 200)
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

    def test_06_input_validation(self):
        # A negative Content-Length used to block the handler until the client hung up.
        resp, _ = self.request("POST", "/api/jobs", headers={"Content-Type": "application/json",
                                                             "Content-Length": "-1"})
        self.assertEqual(resp.status, 400)
        self.json("POST", "/api/jobs", {"kind": "company", "params": ["x"]}, status=400)
        self.json("POST", "/api/jobs", {"kind": "batch", "params": {"limit": "viele"}}, status=400)
        self.json("GET", "/api/fulltext?q=Zoll&from=abc", status=400)
        self.json("GET", "/api/fulltext?q=Zoll*%20*")                         # stray "*" is no FTS5 error
        job_id = self.json("POST", "/api/jobs", {"kind": "index", "params": {}})["id"]
        self.json("GET", f"/api/jobs/{job_id}?after=x", status=400)
        self.json("PATCH", f"/api/companies/{COMPANY['lei']}", {"ir_url": ["https://x"]}, status=400)
        before = self.app.settings.contact_email
        self.json("PUT", "/api/settings", {"contact_email": "neu@example.org", "years": 99}, status=400)
        self.json("PUT", "/api/settings", {"contact_email": "a@b.org\r\nX-Evil: 1"}, status=400)
        self.assertEqual(self.app.settings.contact_email, before)             # nothing applied
        self.wait_for(job_id)

    def test_07_value_page(self):
        lei = COMPANY["lei"]
        companies = self.json("GET", "/api/value/companies")["companies"]
        self.assertEqual(companies[0]["lei"], lei)
        self.assertEqual(companies[0]["figure_years"], 7)
        view = self.json("GET", f"/api/companies/{lei}/value")
        self.assertEqual(view["years"], list(range(2019, 2026)))
        self.assertEqual([c["key"] for c in view["checks"]],
                         ["roe", "roic", "margin", "owner_earnings", "debt", "capex", "eps"])
        self.assertTrue(view["documents"])
        self.json("GET", "/api/companies/AAAAAAAAAAAAAAAAAAAA/value", status=404)

        self.json("POST", f"/api/companies/{lei}/figures", {"rows": "x"}, status=400)
        self.json("POST", f"/api/companies/{lei}/figures", {"rows": [{"metric": "roe", "fiscal_year": 2015,
                                                                      "value": 1}]}, status=400)
        self.json("POST", f"/api/companies/{lei}/figures", {"rows": [], "currency": "EURO"}, status=400)
        result = self.json("POST", f"/api/companies/{lei}/figures", {"millions": True, "rows": [
            {"metric": "revenue", "fiscal_year": 2015, "value": 2900, "page": "7"}]})
        self.assertEqual(result["imported"], 1)
        self.assertIn(2015, result["years"])
        self.assertIn(2015, result["origin"]["PDF"])

        resp, body = self.request("GET", "/")
        self.assertIn(b'data-tab="value"', body)


if __name__ == "__main__":
    unittest.main()
