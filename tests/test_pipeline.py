"""End-to-end runs of the pipelines against the fake internet in tests/fakeweb.py."""

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from portal.app import App
from tests.fakeweb import COMPANY, PEER_FR, PEER_IT, PEER_US, TODAY, FakeWeb


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.web = FakeWeb().__enter__()
        self.tmp = Path(tempfile.mkdtemp())
        sources = self.tmp / "sources.json"
        sources.write_text(json.dumps({"28": [{"name": "Testverband", "url": f"{self.web.base}/assoc/"}]}))
        self.app = App(self.web.settings(str(self.tmp / "library"), industry_sources_file=str(sources)))

    def tearDown(self):
        self.app.close()
        self.web.__exit__(None, None, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_company(self, **params):
        base = {"query": COMPANY["isin"], "today": TODAY}
        job = self.app.jobs.run_sync("company", {**base, **params})
        self.assertEqual(job["status"], "done", job.get("error"))
        return job


class CompanyJobTests(PipelineTestCase):
    def test_ten_years_with_industry_package(self):
        job = self.run_company(include={"industry": True}, nace="28", keywords="Verpackungsmaschinen")
        coverage = job["summary"]["coverage"]
        self.assertEqual(coverage["years"], list(range(2016, 2026)))
        self.assertEqual((coverage["covered"], coverage["missing"]), (10, []))

        docs = self.app.db.company_documents(COMPANY["lei"])
        pdfs = {d["fiscal_year"]: d for d in docs if d["category"] == "annual_report"}
        self.assertEqual(sorted(pdfs), list(range(2016, 2026)))
        languages = {y: d["language"] for y, d in pdfs.items()}
        self.assertEqual(languages, {2016: "de", 2017: "en", 2018: "de", 2019: "de", 2020: "en", 2021: "en",
                                     2022: "de", 2023: "en", 2024: "en", 2025: "en"})
        self.assertTrue(pdfs[2024]["source_url"].endswith("/annual-report-2024-en.pdf"))   # not the short version
        self.assertTrue(pdfs[2023]["source_url"].startswith(self.web.cdn_base))              # PDF on another host
        self.assertTrue(pdfs[2017]["source_url"].endswith("Annual_Report_2017_EN.pdf"))     # only in the sitemap
        self.assertTrue(pdfs[2019]["source_url"].endswith("gb-2019-de.pdf"))                # EN link was broken

        esef = [d for d in docs if d["source"] == "esef"]
        self.assertEqual(sorted({d["fiscal_year"] for d in esef}), list(range(2020, 2026)))
        self.assertEqual(len(esef), 12)
        report_2021 = next(d for d in esef if d["fiscal_year"] == 2021 and d["category"] == "esef_report")
        self.assertIn("/2021-12-31/1/", report_2021["source_url"])                           # corrected filing wins

        for doc in docs:
            data = self.app.library.absolute(doc["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), doc["sha256"])
        manifest = json.loads((self.app.library.company_dir(self.app.db.company(COMPANY["lei"]))
                               / "manifest.json").read_text())
        self.assertEqual(len(manifest["documents"]), 22)
        self.assertEqual(manifest["coverage"]["covered"], 10)

        paths = self.web.paths()
        self.assertFalse([p for p in paths if "/intern/" in p], "robots.txt must be respected")
        for unwanted in ("GB12.pdf", "hj-2025.pdf", "nb-2024.pdf", "verguetung-2024.pdf", "praesentation-gb-2024.pdf",
                         "einladung-hv-2026.pdf", "katalog-2024.pdf", "/site/karriere/"):
            self.assertFalse([p for p in paths if p.endswith(unwanted)], unwanted)
        self.assertTrue(all("test@example.org" in ua for _p, _q, ua in self.web.requests))

        industry = self.app.db.industry_documents("28")
        by_cat = {}
        for d in industry:
            by_cat.setdefault(d["category"], []).append(d)
        self.assertEqual(len(by_cat["statistics"]), 1)
        self.assertEqual(len(by_cat["study"]), 1)
        assoc = sorted(Path(d["source_url"]).name for d in by_cat["association_report"])
        self.assertEqual(assoc, ["branchenbericht-2024.pdf", "konjunktur-herbst-2025.pdf",
                                 "maschinenbau-in-zahlen-2023.pdf"])
        self.assertEqual(sorted(d["lei"] for d in by_cat["peer_report"]), sorted([PEER_IT["lei"], PEER_FR["lei"]]))
        self.assertNotIn(PEER_US["lei"], {d["lei"] for d in industry})
        csv_text = self.app.library.absolute(by_cat["statistics"][0]["path"]).read_text()
        self.assertIn("EU27_2020", csv_text)
        stats_query = next(q for p, q, _ua in self.web.requests if p == "/eurostat/data/sts_inpr_a")
        self.assertIn("nace_r2=C28", stats_query)
        self.assertIn("geo=DE", stats_query)

    def test_rerun_downloads_nothing_new(self):
        self.run_company()
        before = len(self.app.db.company_documents(COMPANY["lei"]))
        job = self.run_company()
        self.assertEqual(len(self.app.db.company_documents(COMPANY["lei"])), before)
        self.assertEqual(job["summary"]["downloads"], {"exists": 22})

    def test_esef_filter_ignored_by_server(self):
        self.web.esef_mode = "ignore_filter"
        self.run_company(include={"pdf": False})
        docs = self.app.db.company_documents(COMPANY["lei"])
        self.assertEqual(len(docs), 12)
        self.assertTrue(all(COMPANY["lei"] in d["source_url"] for d in docs))

    def test_esef_filter_rejected_uses_entity_route(self):
        self.web.esef_mode = "reject_filter"
        self.run_company(include={"pdf": False})
        self.assertEqual(len(self.app.db.company_documents(COMPANY["lei"])), 12)

    def test_websearch_fills_gap(self):
        self.app.settings.search_provider = "brave"
        self.app.settings.brave_api_key = "test-key"
        job = self.run_company(include={"pdf": False})
        docs = self.app.db.company_documents(COMPANY["lei"])
        web = [d for d in docs if d["source"] == "websearch"]
        self.assertEqual([(d["fiscal_year"], Path(d["source_url"]).name) for d in web], [(2016, "GB16.pdf")])
        self.assertIn(2016, [r["year"] for r in job["summary"]["coverage"]["rows"] if r["pdf"]])
        queries = [q for p, q, _ua in self.web.requests if p == "/brave"]
        self.assertTrue(queries and "2019" in queries[0])

    def test_manual_url_with_year(self):
        url = f"{self.web.base}/site/media/extra-bericht.pdf"
        self.run_company(include={"pdf": False, "esef": False}, urls=f"2016: {url}")
        docs = self.app.db.company_documents(COMPANY["lei"])
        self.assertEqual([(d["fiscal_year"], d["source"]) for d in docs], [(2016, "manual")])

    def test_unknown_company_fails_cleanly(self):
        job = self.app.jobs.run_sync("company", {"query": "Gibt es nicht GmbH", "today": TODAY})
        self.assertEqual(job["status"], "failed")
        self.assertIn("Kein Unternehmen", job["error"])


class UniverseAndBatchTests(PipelineTestCase):
    def test_universe_and_batch(self):
        job = self.app.jobs.run_sync("universe", {"source": "esef"})
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["summary"]["issuers"], 3)
        job = self.app.jobs.run_sync("universe", {"source": "firds"})
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["summary"]["securities"], 3)
        stats = self.app.db.universe_stats()
        self.assertEqual((stats["companies"], stats["with_esef"]), (3, 3))
        self.assertEqual(self.app.db.company_by_isin(COMPANY["isin"])["lei"], COMPANY["lei"])
        self.assertEqual([c["lei"] for c in self.app.db.search_companies("beispiel masch")], [COMPANY["lei"]])

        job = self.app.jobs.run_sync("batch", {"countries": ["DE"], "esef_only": True, "limit": 10,
                                                "include": {"pdf": False}})
        self.assertEqual(job["summary"]["enqueued"], 1)
        queued = self.app.db.claim_job()
        self.assertEqual(queued["params"]["lei"], COMPANY["lei"])
        queued["params"]["today"] = TODAY
        result = self.app.jobs.run(queued)
        self.assertEqual(result["status"], "done", result.get("error"))
        self.assertEqual(result["parent_id"], job["id"])


class IndustryJobTests(PipelineTestCase):
    def test_industry_only_with_manual_peer(self):
        job = self.app.jobs.run_sync("industry", {"nace": "C28", "keywords": "Verpackung", "peers": PEER_IT["isin"],
                                                   "today": TODAY})
        self.assertEqual(job["status"], "done", job.get("error"))
        docs = self.app.db.industry_documents("28")
        peers = [d for d in docs if d["category"] == "peer_report"]
        self.assertEqual([d["lei"] for d in peers], [PEER_IT["lei"]])
        zip_path = self.app.library.build_zip(self.app.library.industry_dir("28"), "branche")
        self.assertTrue(zip_path.exists())

    def test_invalid_nace(self):
        job = self.app.jobs.run_sync("industry", {"nace": "4", "today": TODAY})
        self.assertEqual(job["status"], "failed")


if __name__ == "__main__":
    unittest.main()
