"""Every portal function run for Krones AG, checked against the reported figures in data/.

The sources are simulated (see tests/krones_scenario.py); the numbers are Krones' own.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from portal import financials, fulltext
from portal.app import App
from portal.resolver import Resolver
from tests.fakeweb import PEER_FR, PEER_IT, PEER_US, TODAY
from tests.krones_scenario import FIGURES, KRONES, KronesWeb, write_fake_pdftotext


class KronesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = KronesWeb().__enter__()
        cls.tmp = Path(tempfile.mkdtemp())
        sources = cls.tmp / "sources.json"
        sources.write_text(json.dumps({"28": [{"name": "Testverband", "url": f"{cls.web.base}/assoc/"}]}))
        cls.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{write_fake_pdftotext(cls.tmp).parent}{os.pathsep}{cls.old_path}"
        cls.app = App(cls.web.settings(str(cls.tmp / "library"), industry_sources_file=str(sources),
                                       search_provider="brave", brave_api_key="test"))
        cls.job = cls.app.jobs.run_sync("company", {
            "query": "DE0006335003", "today": TODAY, "nace": "28.29", "keywords": "Abfüllanlagen, Verpackungsmaschinen",
            "include": {"industry": True}})

    @classmethod
    def tearDownClass(cls):
        os.environ["PATH"] = cls.old_path
        cls.app.close()
        cls.web.__exit__(None, None, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def docs(self):
        return self.app.db.company_documents(KRONES["lei"])

    def test_01_search(self):
        resolver = Resolver(self.app.context())
        by_name, _ = resolver.search("Krones")
        by_isin, _ = resolver.search("DE0006335003")
        self.assertEqual(by_name[0]["lei"], KRONES["lei"])
        self.assertEqual(by_isin[0]["lei"], KRONES["lei"])

    def test_02_ten_years_of_reports(self):
        self.assertEqual(self.job["status"], "done", self.job.get("error"))
        coverage = self.job["summary"]["coverage"]
        self.assertEqual((coverage["years"], coverage["covered"]), (list(range(2016, 2026)), 10))
        pdfs = {d["fiscal_year"]: d for d in self.docs() if d["category"] == "annual_report"}
        self.assertEqual(sorted(pdfs), list(range(2016, 2026)))
        self.assertEqual(pdfs[2016]["source"], "websearch")                       # only findable by search
        self.assertTrue(pdfs[2018]["source_url"].endswith("Krones_Annual_Report_2018_EN.pdf"))  # sitemap only
        self.assertTrue(pdfs[2017]["source_url"].endswith("GB17.pdf"))            # archive row "2017 | PDF"
        self.assertTrue(pdfs[2019]["source_url"].endswith("geschaeftsbericht-2019-de.pdf"))  # EN link broken
        self.assertTrue(all(pdfs[y]["language"] == "en" for y in range(2020, 2026)))
        esef = sorted({d["fiscal_year"] for d in self.docs() if d["source"] == "esef"})
        self.assertEqual(esef, list(range(2020, 2026)))
        fetched = self.web.paths()
        for unwanted in ("halbjahresfinanzbericht-2026.pdf", "nachhaltigkeitsbericht-2025.pdf",
                         "verguetungsbericht-2025.pdf", "einladung-hv-2026.pdf", "GB15.pdf", "/krones/karriere/"):
            self.assertFalse([p for p in fetched if p.endswith(unwanted)], unwanted)

    def test_03_key_figures_match_reported_numbers(self):
        data = financials.table_for(self.app.db, KRONES["lei"])
        self.assertEqual(data["years"], list(range(2019, 2026)))   # 2019 from the FY2020 comparatives
        self.assertEqual(data["currency"], "EUR")
        values = {m["key"]: m["values"] for m in data["metrics"]}
        for year in range(2019, 2026):
            with self.subTest(year=year):
                self.assertAlmostEqual(values["revenue"][str(year)], FIGURES[year]["revenue"] * 1e6, delta=1)
                self.assertAlmostEqual(values["ebt"][str(year)], FIGURES[year]["ebt"] * 1e6, delta=1)
                self.assertAlmostEqual(values["net_income"][str(year)], FIGURES[year]["net_income"] * 1e6, delta=1)
                self.assertAlmostEqual(values["eps"][str(year)], FIGURES[year]["eps"], places=6)
        self.assertAlmostEqual(values["revenue_growth"]["2020"], 3322.7 / 3958.9 - 1, places=6)   # Covid year
        self.assertAlmostEqual(values["revenue"]["2025"] / values["revenue"]["2020"], 1.7046, places=3)  # "+70 %"
        self.assertLess(values["net_margin"]["2020"], 0)
        self.assertEqual(data["restatements"], [])
        csv_text = financials.csv_for(self.app.db, KRONES["lei"], "de")
        self.assertIn("eps;Ergebnis je Aktie;EUR/Aktie;0,3;-2,52;4,47;5,92;7,11;8,77;9,45", csv_text)

    def test_04_full_text(self):
        hits = fulltext.search(self.app.db, '"Auftragsbestand" 4.190,4', lei=KRONES["lei"])
        self.assertTrue(hits)
        self.assertEqual({h["fiscal_year"] for h in hits}, {2025})
        pdf_hits = [h for h in fulltext.search(self.app.db, "Auftragsbestand", lei=KRONES["lei"], limit=100)
                    if h["mime"] == "pdf"]
        self.assertEqual(len(pdf_hits), 10)
        self.assertTrue(all(h["page"] == 1 for h in pdf_hits))

    def test_05_industry_package_and_peers(self):
        industry = self.job["summary"]["industry"]
        self.assertEqual(industry["nace"], "28.29")
        docs = self.app.db.industry_documents("28.29")
        categories = {d["category"] for d in docs}
        self.assertTrue({"statistics", "study", "association_report", "peer_report"} <= categories)
        stats_query = next(q for p, q, _ua in self.web.requests if p == "/eurostat/data/sts_inpr_a")
        self.assertIn("nace_r2=C2829", stats_query)
        peers = {d["lei"] for d in docs if d["category"] == "peer_report"}
        self.assertEqual(peers, {PEER_IT["lei"], PEER_FR["lei"]})
        self.assertNotIn(PEER_US["lei"], peers)
        cmp = financials.comparison(self.app.db, "28.29", KRONES["lei"])
        krones_row = next(r for r in cmp["rows"] if r["lei"] == KRONES["lei"])
        self.assertTrue(krones_row["focus"])
        self.assertAlmostEqual(krones_row["net_margin"], 299.2 / 5663.8, places=6)

    def test_05b_progress_steps_for_the_checklist(self):
        """The nested industry run reports sub-steps, so the company checklist keeps its order."""
        events = self.app.db.job_events(self.job["id"])
        stages = [json.loads(e["data"]) if isinstance(e["data"], str) else e["data"] for e in events if e["level"] == "stage"]
        steps = [d["step"] for d in stages if d.get("step")]
        order = ["resolve", "enrich", "esef", "irsite", "websearch", "select", "download", "analyze", "industry"]
        self.assertEqual(list(dict.fromkeys(steps)), order)
        self.assertEqual(steps[steps.index("industry"):], ["industry"] * len(steps[steps.index("industry"):]))
        subs = [d["substep"] for d in stages if d.get("substep")]
        self.assertIn("industry.peers", subs)
        self.assertTrue(all(s.startswith("industry.") for s in subs))
        for e in events:
            data = json.loads(e["data"]) if isinstance(e["data"], str) else e["data"]
            if data and data.get("skipped") and data.get("step"):
                self.assertIn(data["step"], order)

    def test_06_wrong_document_is_replaced(self):
        wrong = next(d for d in self.docs() if d["fiscal_year"] == 2025 and d["category"] == "annual_report")
        self.app.library.absolute(wrong["path"]).unlink()
        self.app.db.delete_document(wrong["id"])
        self.app.db.block_url(wrong["source_url"], KRONES["lei"], "test")
        job = self.app.jobs.run_sync("company", {"lei": KRONES["lei"], "today": TODAY,
                                                 "include": {"esef": False, "websearch": False}})
        self.assertEqual(job["status"], "done", job.get("error"))
        replacement = next(d for d in self.docs() if d["fiscal_year"] == 2025 and d["category"] == "annual_report")
        self.assertTrue(replacement["source_url"].endswith("geschaeftsbericht-2025-de.pdf"))

    def test_07_export_and_manifest(self):
        company = self.app.db.company(KRONES["lei"])
        folder = self.app.library.company_dir(company)
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(manifest["company"]["isins"], ["DE0006335003"])
        zip_path = self.app.library.build_zip(folder, "krones")
        self.assertGreater(zip_path.stat().st_size, 10_000)

    def test_08_universe_and_batch(self):
        self.assertEqual(self.app.jobs.run_sync("universe", {"source": "firds"})["status"], "done")
        self.assertEqual(self.app.db.company_by_isin("DE0006335003")["lei"], KRONES["lei"])
        security = self.app.db.one("SELECT * FROM securities WHERE isin = 'DE0006335003'")
        self.assertEqual((security["mic"], security["issuer_requested"]), ("XETR", 1))
        batch = self.app.jobs.run_sync("batch", {"leis": [KRONES["lei"]], "include": {"pdf": False}})
        self.assertEqual(batch["summary"]["enqueued"], 1)


if __name__ == "__main__":
    unittest.main()
