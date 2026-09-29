"""Regression tests for concurrency, validation and error-handling fixes."""

import hashlib
import json
import shutil
import tempfile
import threading
import unittest
import zipfile
import zlib
from pathlib import Path

from portal import fulltext
from portal.app import App
from portal.config import Settings
from portal.financials import derive
from portal.net import ContentError, _decode_body, _retry_after
from portal.resolver import NotFound, Resolver, relevance
from portal.storage import Library
from tests.fakeweb import COMPANY, LOOKALIKE
from tests.test_pipeline import PipelineTestCase


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library = Library(self.tmp / "library")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reserve_hands_out_each_path_once(self):
        target = self.library.root / "2015" / "annual_report_2015.pdf"
        first = self.library.reserve(target)
        second = self.library.reserve(target)
        self.assertEqual(first, target)
        self.assertEqual(second.name, "annual_report_2015_2.pdf")
        self.library.release(first)                                   # download failed: path is free again
        self.assertEqual(self.library.reserve(target), target)

    def test_reserve_is_thread_safe(self):
        target = self.library.root / "x.pdf"
        paths, barrier = [], threading.Barrier(8)

        def grab():
            barrier.wait()
            paths.append(self.library.reserve(target))

        threads = [threading.Thread(target=grab) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(paths)), 8)

    def test_company_dir_survives_rename(self):
        company = {"lei": COMPANY["lei"], "name": "Beispiel Maschinenbau AG", "country": "DE"}
        folder = self.library.company_dir(company)
        folder.mkdir(parents=True)
        renamed = {**company, "name": "Beispiel Maschinenbau Aktiengesellschaft", "country": "AT"}
        self.assertEqual(self.library.company_dir(renamed), folder)

    def test_manifest_accepts_files_outside_the_folder(self):
        folder = self.library.root / "companies" / "DE" / "neu_X"
        other = self.library.root / "companies" / "DE" / "alt_X" / "2019" / "gb.pdf"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"%PDF-1.4")
        manifest = self.library.write_manifest(folder, {}, [{"path": self.library.relative(other)}])
        entry = json.loads(manifest.read_text())["documents"][0]
        self.assertEqual(entry["file"], "../alt_X/2019/gb.pdf")

    def test_parallel_exports_do_not_clash(self):
        folder = self.library.root / "companies" / "DE" / "firma_X"
        for i in range(20):
            (folder / f"{2000 + i}").mkdir(parents=True)
            (folder / f"{2000 + i}" / "report.pdf").write_bytes(b"%PDF-1.4 " + bytes(str(i), "ascii") * 50_000)
        errors = []

        def export():
            try:
                self.library.build_zip(folder, "firma")
            except Exception as err:  # noqa: BLE001
                errors.append(err)

        threads = [threading.Thread(target=export) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        with zipfile.ZipFile(self.library.exports_dir() / "firma.zip") as zf:
            self.assertIsNone(zf.testzip())
            self.assertEqual(len(zf.namelist()), 20)
        self.assertEqual([p.name for p in self.library.exports_dir().iterdir()], ["firma.zip"])


class SettingsValidationTests(unittest.TestCase):
    def test_control_characters_are_rejected(self):
        s = Settings()
        with self.assertRaises(ValueError):
            s.apply({"contact_email": "a@example.org\r\nX-Injected: 1"})
        with self.assertRaises(ValueError):
            s.apply({"brave_api_key": "key\nmore"})
        self.assertEqual((s.contact_email, s.brave_api_key), ("", ""))

    def test_invalid_value_changes_nothing(self):
        s = Settings()
        with self.assertRaises(ValueError) as caught:
            s.apply({"contact_email": "a@example.org", "years": "99"})
        self.assertIn("years", str(caught.exception))
        self.assertEqual((s.contact_email, s.years), ("", 10))

    def test_ranges_and_choices(self):
        s = Settings()
        for bad in ({"default_rate": "-1"}, {"default_rate": "nan"}, {"peers_max": "1000"},
                    {"search_provider": "google"}, {"esef_formats": "report, pdf"}, {"searxng_url": "file:///etc"}):
            with self.assertRaises(ValueError, msg=bad):
                s.apply(bad)
        self.assertEqual(s.apply({"esef_formats": "report, json", "search_provider": "searxng",
                                  "searxng_url": "https://searx.example"}),
                         ["esef_formats", "search_provider", "searxng_url"])

    def test_empty_number_field_keeps_value(self):
        s = Settings()
        self.assertEqual(s.apply({"years": "", "default_rate": " "}), [])
        self.assertEqual((s.years, s.default_rate), (10, 1.0))

    def test_stored_invalid_values_are_skipped(self):
        s = Settings()
        self.assertEqual(s.apply({"years": "500", "peers_max": "7"}, skip_invalid=True), ["peers_max"])
        self.assertEqual(s.years, 10)


class NetHelperTests(unittest.TestCase):
    def test_retry_after(self):
        self.assertEqual(_retry_after({"Retry-After": "7"}), 7.0)
        self.assertEqual(_retry_after({"Retry-After": "-5"}), 0.0)    # time.sleep(-5) would raise
        self.assertEqual(_retry_after({"Retry-After": "9999"}), 120.0)
        self.assertIsNone(_retry_after({"Retry-After": "nan"}))
        self.assertIsNone(_retry_after({"Retry-After": "soon"}))

    def test_decode_errors_become_content_errors(self):
        with self.assertRaises(ContentError):
            _decode_body(b"not gzip at all", "gzip", 1000)
        with self.assertRaises(ContentError):
            _decode_body(b"not deflate", "deflate", 1000)

    def test_deflate_is_bounded(self):
        bomb = zlib.compress(b"0" * 5_000_000)
        with self.assertRaises(ContentError):
            _decode_body(bomb, "deflate", 10_000)
        raw = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        body = raw.compress(b"hello") + raw.flush()
        self.assertEqual(_decode_body(body, "deflate", 100), b"hello")


class QueryAndFigureTests(unittest.TestCase):
    def test_fts_query_edge_cases(self):
        self.assertEqual(fulltext.fts_query("Zoll* *"), '"Zoll"*')              # was '"Zoll"**': FTS5 syntax error
        self.assertEqual(fulltext.fts_query("E-Mobilität COVID-19*"), '"E Mobilität" "COVID 19"*')
        self.assertIsNone(fulltext.fts_query("** --"))

    def test_roe_uses_matching_profit_and_equity(self):
        table = {2025: {"net_income": 10.0, "net_income_parent": 8.0, "equity": 100.0, "equity_parent": 80.0}}
        derive(table)
        self.assertAlmostEqual(table[2025]["roe"], 0.1)                      # 8 / 80, not 8 / 100
        table = {2025: {"net_income": 10.0, "net_income_parent": 8.0, "equity": 100.0}}
        derive(table)
        self.assertAlmostEqual(table[2025]["roe"], 0.1)                      # 10 / 100 (group totals)
        table = {2025: {"net_income_parent": 8.0, "equity": 100.0}}
        derive(table)
        self.assertAlmostEqual(table[2025]["roe"], 0.08)                     # last resort


class JobStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = App(Settings(library_dir=str(self.tmp / "library")))
        self.db = self.app.db

    def tearDown(self):
        self.app.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_claim_job(self):
        first = self.db.create_job("index", "a", {})
        second = self.db.create_job("index", "b", {})
        self.assertEqual(self.db.claim_job()["id"], first)
        self.assertEqual(self.db.claim_job()["id"], second)
        self.assertIsNone(self.db.claim_job())
        self.assertEqual(self.db.job(first)["status"], "running")

    def test_restart_keeps_cancelled_jobs_cancelled(self):
        running = self.db.create_job("index", "a", {}, status="running")
        cancelling = self.db.create_job("index", "b", {}, status="cancelling")
        self.assertEqual(self.db.requeue_interrupted(), 1)
        self.assertEqual(self.db.job(running)["status"], "queued")
        self.assertEqual(self.db.job(cancelling)["status"], "cancelled")

    def test_cancel_batch_cancels_queued_children(self):
        parent = self.db.create_job("batch", "Stapel", {}, status="done")
        children = [self.db.create_job("company", f"c{i}", {"lei": "x"}, parent_id=parent) for i in range(3)]
        running_child = self.db.create_job("company", "läuft", {}, parent_id=parent, status="running")
        self.assertTrue(self.app.jobs.cancel(parent))
        self.assertEqual({self.db.job(c)["status"] for c in children}, {"cancelled"})
        self.assertEqual(self.db.job(parent)["status"], "done")              # finished jobs stay finished
        self.assertEqual(self.db.job(running_child)["status"], "running")

    def test_cancel_finished_job_changes_nothing(self):
        done = self.db.create_job("index", "a", {}, status="done")
        self.assertFalse(self.app.jobs.cancel(done))
        self.assertEqual(self.db.job(done)["status"], "done")
        self.assertFalse(self.app.jobs.cancel(999_999))


class PipelineRobustnessTests(PipelineTestCase):
    def test_parallel_downloads_for_the_same_year(self):
        urls = "\n".join(f"2015: {self.web.base}/site/media/manuell-{c}.pdf" for c in "abcdef")
        self.run_company(urls=urls, include={"esef": False, "pdf": False})
        docs = [d for d in self.app.db.company_documents(COMPANY["lei"]) if d["fiscal_year"] == 2015]
        self.assertEqual(len(docs), 6)
        self.assertEqual(len({d["path"] for d in docs}), 6)
        for doc in docs:
            data = self.app.library.absolute(doc["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), doc["sha256"])

    def test_renamed_company_keeps_its_folder(self):
        self.run_company(include={"esef": False})
        folder = self.app.library.company_dir(self.app.db.company(COMPANY["lei"]))
        self.app.db.upsert_company({"lei": COMPANY["lei"], "name": "Beispiel Maschinenbau Aktiengesellschaft"})
        self.run_company(include={"esef": False}, urls=f"2014: {self.web.base}/site/media/gb-2014-de.pdf")
        company = self.app.db.company(COMPANY["lei"])
        self.assertEqual(self.app.library.company_dir(company), folder)
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(len(manifest["documents"]), len(self.app.db.company_documents(COMPANY["lei"])))
        self.assertTrue(all(not e["file"].startswith("..") for e in manifest["documents"]))

    def test_search_with_stray_asterisk(self):
        self.run_company(include={"pdf": False})
        self.assertTrue(fulltext.search(self.app.db, "Zoll* *", lei=COMPANY["lei"]))


class NameSearchTests(PipelineTestCase):
    def test_relevance(self):
        self.assertEqual(relevance("GEA Group Aktiengesellschaft", "GEA Group"), 3)   # legal form ignored
        self.assertEqual(relevance("GEA Group Holding GmbH", "gea group"), 2)
        self.assertEqual(relevance("Versorgungskasse der GEA Group AG", "GEA Group"), 1)
        self.assertEqual(relevance("GET GROUP", "GEA Group"), 0)                     # GLEIF fuzzy look-alike
        self.assertEqual(relevance("GE-GROUP S.R.L.", "GEA Group"), 0)

    def test_full_text_match_beats_fuzzy_lookalike(self):
        resolver = Resolver(self.app.context())
        results, _warning = resolver.search("Beispiel Maschinenbau")
        leis = [r["lei"] for r in results]
        self.assertEqual(leis[0], COMPANY["lei"])       # was missing: only fuzzy completions were asked
        self.assertIn(LOOKALIKE["lei"], leis)            # typo tolerance stays, ranked below
        self.assertEqual(resolver.resolve(query="Beispiel Maschinenbau")["lei"], COMPANY["lei"])

    def test_no_guessing_on_lookalikes(self):
        with self.assertRaises(NotFound) as caught:
            Resolver(self.app.context()).resolve(query="Gibt es nicht GmbH")
        self.assertIn("Ähnliche Namen", str(caught.exception))
        self.assertIsNone(self.app.db.company(LOOKALIKE["lei"]))


class ReportDiscoveryTests(unittest.TestCase):
    def cand(self, url, year, category="annual_report", source="irsite", score=70.0):
        from portal.connectors.base import Candidate
        return Candidate(url=url, category=category, source=source, fiscal_year=year, fy_label=str(year),
                         language="en", score=score)

    def test_url_pattern_fills_missing_years(self):
        from portal.pipeline import pattern_candidates
        found = [self.cand("https://cdn.example.com/-/media/ar/2025/annual-report-2025-en.pdf?rev=abc", 2025),
                 self.cand("https://www.example.com/agm/annual-report-2021-en.pdf", 2021),
                 self.cand("https://www.example.com/hv/jahresabschluss-2022.pdf", 2022, "single_entity_statements")]
        guesses = pattern_candidates(found, [2022, 2024])
        self.assertEqual([g.url for g in guesses], [
            "https://cdn.example.com/-/media/ar/2022/annual-report-2022-en.pdf",   # no ?rev= of another file
            "https://cdn.example.com/-/media/ar/2024/annual-report-2024-en.pdf",
            "https://www.example.com/agm/annual-report-2022-en.pdf",
            "https://www.example.com/agm/annual-report-2024-en.pdf"])
        self.assertTrue(all(g.source == "pattern" and g.score == 50.0 for g in guesses))
        self.assertEqual(pattern_candidates([self.cand("https://x.com/latest-report.pdf", 2025)], [2024]), [])

    def test_single_entity_statements_are_the_fallback(self):
        from portal.pipeline import select_company_candidates
        report = self.cand("https://x.com/annual-report-2022-en.pdf", 2022, source="pattern", score=50.0)
        hgb = self.cand("https://x.com/jahresabschluss-2022.pdf", 2022, "single_entity_statements")
        chosen = select_company_candidates([report, hgb], prefs=["en"], all_languages=False,
                                           include_sustainability=False)
        self.assertEqual([c.url for c in chosen], [report.url])
        self.assertEqual([a.url for a in chosen[0].alternates], [hgb.url])

    def test_parent_statements_are_not_the_annual_report(self):
        from datetime import date
        from portal.classify import LinkInfo, classify_report_link
        def category(anchor):
            return classify_report_link(LinkInfo(url="https://x.com/doc.pdf", anchor=anchor), date(2026, 9, 1)).category
        self.assertEqual(category("Agenda item 1 – Annual Financial Statements 2022 of GEA Group AG (German only)"),
                         "single_entity_statements")
        self.assertEqual(category("Annual Report and Annual Financial Statements 2022"), "annual_report")
        self.assertEqual(category("Consolidated Annual Financial Statements 2022"), "annual_report")
        self.assertEqual(category("Agenda item 1 | Annual Report 2021"), "annual_report")


if __name__ == "__main__":
    unittest.main()
