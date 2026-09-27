"""Key figures from inline XBRL, full-text search, peer comparison, wrong-document handling and auto refresh."""

import io
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from portal import financials, fulltext
from portal.financials import derive, parse_number, values_from_report
from tests.fakeweb import COMPANY, PEER_FR, PEER_IT, ixbrl_bytes
from tests.test_pipeline import PipelineTestCase


class ParseNumberTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_number("5.663,8", "ixt4:num-comma-decimal", "6", None), 5_663_800_000)
        self.assertEqual(parse_number("5,663.8", "ixt4:num-dot-decimal", "6", None), 5_663_800_000)
        self.assertEqual(parse_number("79,7", "ixt:numcommadecimal", "6", "-"), -79_700_000)
        self.assertEqual(parse_number("1 234,5", "ixt:numspacecomma", "3", None), 1_234_500)
        self.assertEqual(parse_number("–", "ixt:fixed-zero", "6", None), 0.0)
        self.assertEqual(parse_number("9,45", None, None, None), 9.45)
        self.assertEqual(parse_number("1.234.567", None, None, None), 1_234_567)
        self.assertIsNone(parse_number("n/a", "ixt4:num-dot-decimal", "0", None))


class ExtractionTests(unittest.TestCase):
    def test_report_values(self):
        values = values_from_report([io.BytesIO(ixbrl_bytes(COMPANY["lei"], 2020))])
        self.assertAlmostEqual(values[("revenue", 2020)]["value"], 3_960_000_000)
        self.assertAlmostEqual(values[("revenue", 2019)]["value"], 3_720_000_000)   # prior-year comparative
        self.assertAlmostEqual(values[("net_income", 2020)]["value"], -79_700_000)  # sign="-"
        self.assertAlmostEqual(values[("eps", 2020)]["value"], -2.52)
        self.assertEqual(values[("revenue", 2020)]["currency"], "EUR")
        self.assertNotIn(("eps", 2019), values)

    def test_derive(self):
        table = {2024: {"revenue": 100.0, "ebit": 10.0, "net_income": 7.0, "operating_cash_flow": 12.0, "capex": 4.0,
                        "equity": 40.0, "total_assets": 100.0},
                 2025: {"revenue": 110.0, "ebit": 11.0, "net_income": 8.0, "operating_cash_flow": 13.0, "capex": -5.0,
                        "equity": 44.0, "total_assets": 110.0}}
        derive(table)
        self.assertAlmostEqual(table[2025]["revenue_growth"], 0.1)
        self.assertAlmostEqual(table[2025]["ebit_margin"], 0.1)
        self.assertAlmostEqual(table[2025]["fcf"], 8.0)          # capex sign does not matter
        self.assertAlmostEqual(table[2025]["equity_ratio"], 0.4)
        self.assertAlmostEqual(table[2025]["roe"], 8.0 / 42.0)   # on average equity
        self.assertNotIn("revenue_growth", table[2024])


class QueryTests(unittest.TestCase):
    def test_fts_query(self):
        self.assertEqual(fulltext.fts_query('Zölle "Lieferkette USA" Zoll*'), '"Zölle" "Lieferkette USA" "Zoll"*')
        self.assertEqual(fulltext.fts_query("Zölle OR Tarife"), '"Zölle" OR "Tarife"')
        self.assertEqual(fulltext.fts_query('a") OR (b NEAR c'), '"a" OR "b" "NEAR" "c"')
        self.assertIsNone(fulltext.fts_query('"" *'))

    def test_chunks(self):
        text = " ".join(["wort"] * 2000)
        parts = fulltext.chunks(text, 500)
        self.assertTrue(all(len(p) <= 500 for p in parts))
        self.assertEqual(sum(p.count("wort") for p in parts), 2000)


class FeaturePipelineTests(PipelineTestCase):
    def test_financials_comparison_and_search(self):
        job = self.run_company(include={"industry": True}, nace="28")
        self.assertEqual(job["summary"]["financial_years"], list(range(2019, 2026)))
        data = financials.table_for(self.app.db, COMPANY["lei"])
        revenue = next(m for m in data["metrics"] if m["key"] == "revenue")["values"]
        self.assertAlmostEqual(revenue["2020"], 3_960_000_000)             # as reported, not the restated 3,970
        self.assertEqual([(n["year"], n["metric"]) for n in data["restatements"]], [(2020, "revenue")])
        margin = next(m for m in data["metrics"] if m["key"] == "ebit_margin")["values"]
        self.assertAlmostEqual(margin["2020"], 0.03)
        csv_text = financials.csv_for(self.app.db, COMPANY["lei"], "de")
        self.assertIn("revenue;Umsatz;EUR;3720000000;3960000000", csv_text)

        cmp = financials.comparison(self.app.db, "28", COMPANY["lei"])
        self.assertEqual({r["lei"] for r in cmp["rows"]}, {COMPANY["lei"], PEER_IT["lei"], PEER_FR["lei"]})
        self.assertTrue(all(r["fiscal_year"] == 2025 for r in cmp["rows"]))
        self.assertIn("ebit_margin", cmp["median"])

        hits = fulltext.search(self.app.db, "Zölle")
        self.assertEqual({(h["lei"], h["fiscal_year"]) for h in hits if h["lei"] == COMPANY["lei"]},
                         {(COMPANY["lei"], 2024), (COMPANY["lei"], 2025)})
        self.assertIn(fulltext.MARK_START + "Zölle" + fulltext.MARK_END, hits[0]["snippet"])
        self.assertTrue(fulltext.search(self.app.db, "zoll*", lei=COMPANY["lei"], year_from=2025))
        self.assertFalse(fulltext.search(self.app.db, "Zölle", year_to=2023))

    def test_pdf_index_with_pdftotext(self):
        tool_dir = Path(tempfile.mkdtemp())
        tool = tool_dir / "pdftotext"
        tool.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write('Seite eins Auftragsbestand\\fSeite zwei Werkzeugmaschinen')\n")
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{tool_dir}{os.pathsep}{old_path}"
        try:
            self.run_company(include={"esef": False})
            hits = fulltext.search(self.app.db, "Werkzeugmaschinen", lei=COMPANY["lei"])
            self.assertEqual(len(hits), 10)          # one hit per annual-report PDF
            self.assertTrue(all(h["page"] == 2 for h in hits))
        finally:
            os.environ["PATH"] = old_path
            shutil.rmtree(tool_dir, ignore_errors=True)

    def test_wrong_document_is_replaced_by_alternate(self):
        self.run_company(include={"esef": False})
        docs = self.app.db.company_documents(COMPANY["lei"])
        wrong = next(d for d in docs if d["fiscal_year"] == 2024)
        self.assertTrue(wrong["source_url"].endswith("annual-report-2024-en.pdf"))
        self.app.library.absolute(wrong["path"]).unlink()
        self.app.db.delete_document(wrong["id"])
        self.app.db.block_url(wrong["source_url"], COMPANY["lei"], "test")
        self.run_company(include={"esef": False})
        replacement = next(d for d in self.app.db.company_documents(COMPANY["lei"]) if d["fiscal_year"] == 2024)
        self.assertTrue(replacement["source_url"].endswith("gb-2024-de.pdf"))

    def test_auto_refresh_schedule(self):
        runner = self.app.jobs
        self.assertIsNone(runner.maybe_auto_refresh(now=1_000_000))            # off by default
        self.app.settings.auto_refresh_days = 7
        first = runner.maybe_auto_refresh(now=1_000_000)
        self.assertIsNotNone(first)
        self.assertIsNone(runner.maybe_auto_refresh(now=1_000_000 + 6 * 86400))
        self.assertIsNotNone(runner.maybe_auto_refresh(now=1_000_000 + 7 * 86400))
        self.assertEqual(self.app.db.job(first)["kind"], "refresh")
        self.assertNotIn("state:last_auto_refresh", self.app.db.load_settings())


if __name__ == "__main__":
    unittest.main()
