"""Balance sheet and value view: Buffett metrics, figures from PDF reports, checks and the CLI import."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from portal import financials
from portal.__main__ import main
from portal.financials import _balance, _check, derive
from tests.fakeweb import COMPANY
from tests.test_pipeline import PipelineTestCase

# KSB Group, fiscal years 2024 and 2025 in € million (annual report 2025, pages 203-208)
KSB = {
    2024: {"revenue": 2965.2, "ebit": 244.2, "ebt": 231.2, "income_tax": 84.4, "net_income": 146.8, "d_and_a": 97.4,
           "capex": 135.0, "interest_expense": 33.1, "equity": 1335.4, "cash": 369.3, "debt_noncurrent": 37.8,
           "debt_current": 20.8, "total_assets": 2867.9},
    2025: {"revenue": 3034.7, "ebit": 252.1, "ebt": 241.1, "income_tax": 74.7, "net_income": 166.4, "d_and_a": 96.4,
           "capex": 153.8, "interest_expense": 27.8, "equity": 1391.2, "cash": 338.6, "debt_noncurrent": 39.0,
           "debt_current": 22.3, "total_assets": 2883.3, "noncurrent_assets": 969.2, "current_assets": 1914.1,
           "noncurrent_liabilities": 514.7, "current_liabilities": 977.4},
}


class BuffettMetricTests(unittest.TestCase):
    def setUp(self):
        self.table = {y: dict(v) for y, v in KSB.items()}
        derive(self.table)
        self.v = self.table[2025]

    def test_owner_earnings_and_capital_intensity(self):
        self.assertAlmostEqual(self.v["owner_earnings"], 166.4 + 96.4 - 153.8)    # 109.0
        self.assertAlmostEqual(self.v["capex_ratio"], 153.8 / 166.4)

    def test_debt_measures(self):
        self.assertAlmostEqual(self.v["financial_debt"], 61.3)
        self.assertAlmostEqual(self.v["net_cash"], 338.6 - 61.3)
        self.assertAlmostEqual(self.v["debt_payback"], 61.3 / 166.4)
        self.assertAlmostEqual(self.v["interest_coverage"], 252.1 / 27.8)

    def test_roic_on_average_invested_capital(self):
        rate = 74.7 / 241.1
        invested = ((1391.2 + 61.3 - 338.6) + (1335.4 + 58.6 - 369.3)) / 2
        self.assertAlmostEqual(self.v["roic"], 252.1 * (1 - rate) / invested)
        self.assertAlmostEqual(self.v["roic"], 0.163, places=3)

    def test_missing_inputs_give_no_ratio(self):
        table = {2025: {"ebit": 10.0, "equity": 50.0, "net_income": -3.0, "capex": 4.0}}
        derive(table)
        self.assertNotIn("roic", table[2025])             # no debt, cash or tax
        self.assertNotIn("capex_ratio", table[2025])      # loss year: ratio meaningless
        self.assertNotIn("owner_earnings", table[2025])   # no depreciation


class CheckTests(unittest.TestCase):
    def series(self, **values):
        base = {k: [] for k in ("roe", "roic", "ebit_margin", "owner_earnings", "net_income", "capex_ratio", "eps")}
        base.update({k: list(enumerate(v, 2021)) for k, v in values.items()})
        return base

    def test_return_thresholds(self):
        self.assertEqual(_check("roe", self.series(roe=[0.18, 0.2, 0.16]), {})[0], "good")
        self.assertEqual(_check("roe", self.series(roe=[0.2, 0.2, 0.08]), {})[0], "warn")   # one weak year
        self.assertEqual(_check("roe", self.series(roe=[0.05, 0.07]), {})[0], "bad")
        self.assertEqual(_check("roic", self.series(), {})[0], "na")

    def test_margin_owner_earnings_capex_eps(self):
        self.assertEqual(_check("margin", self.series(ebit_margin=[0.06, 0.08, 0.083]), {})[0], "good")
        self.assertEqual(_check("margin", self.series(ebit_margin=[0.02, 0.12]), {})[0], "warn")
        self.assertEqual(_check("margin", self.series(ebit_margin=[0.05, -0.01]), {})[0], "bad")
        status, text = _check("owner_earnings", self.series(owner_earnings=[5.0, -1.0, 6.0], net_income=[4.0, 4.0, 4.0]), {})
        self.assertEqual(status, "warn")
        self.assertIn("2 von 3 Jahren positiv", text)
        self.assertEqual(_check("capex", self.series(capex_ratio=[0.3, 0.4]), {})[0], "good")
        self.assertEqual(_check("capex", self.series(capex_ratio=[1.5, 1.2]), {})[0], "bad")
        status, text = _check("eps", self.series(eps=[53.34, 59.05, 86.83, 67.29, 80.31]), {})
        self.assertEqual(status, "good")
        self.assertIn("10,8 % pro Jahr", text)

    def test_debt(self):
        status, text = _check("debt", self.series(), {"financial_debt": 61.3e6, "net_cash": 277.3e6, "pensions": 455.2e6})
        self.assertEqual(status, "good")
        self.assertIn("Pensionsrückstellungen 455,2 Mio.", text)
        self.assertEqual(_check("debt", self.series(), {"financial_debt": 400.0, "net_cash": -300.0,
                                                        "debt_payback": 4.0})[0], "warn")
        self.assertEqual(_check("debt", self.series(), {"financial_debt": 400.0, "net_cash": -300.0})[0], "bad")

    def test_balance_structure(self):
        b = _balance(KSB[2025])
        self.assertEqual([p["key"] for p in b["assets"]], ["noncurrent_assets", "current_other", "cash"])
        self.assertAlmostEqual(sum(p["value"] for p in b["assets"]), 2883.3)
        self.assertAlmostEqual(sum(p["value"] for p in b["capital"]), 2883.3)
        self.assertAlmostEqual(b["coverage"], (1391.2 + 514.7) / 969.2)
        simple = _balance({"total_assets": 100.0, "equity": 40.0, "cash": 10.0})
        self.assertEqual([p["key"] for p in simple["capital"]], ["equity", "liabilities"])
        self.assertNotIn("coverage", simple)
        self.assertIsNone(_balance({"equity": 1.0}))


class ManualFigureTests(PipelineTestCase):
    def test_pdf_figures_fill_gaps_and_esef_wins(self):
        self.run_company(include={"pdf": False})                                  # ESEF: 2019-2025
        esef_revenue = self.app.db.one("SELECT value FROM financials WHERE lei = ? AND metric = 'revenue' "
                                       "AND fiscal_year = 2024", (COMPANY["lei"],))["value"]
        rows = [{"metric": "revenue", "fiscal_year": 2024, "value": "1", "page": "9"},          # ESEF has it
                {"metric": "revenue", "fiscal_year": 2016, "value": "3,000.5".replace(",", ""), "page": "12"},
                {"metric": "net_income", "fiscal_year": 2016, "value": 150, "page": "12"}]
        self.assertEqual(financials.import_manual(self.app.db, COMPANY["lei"], rows, millions=True), 3)
        financials.extract(self.app.context(), COMPANY["lei"])
        data = financials.table_for(self.app.db, COMPANY["lei"])
        revenue = next(m for m in data["metrics"] if m["key"] == "revenue")
        self.assertEqual(revenue["values"]["2024"], esef_revenue)
        self.assertEqual(revenue["values"]["2016"], 3_000_500_000)
        self.assertEqual(revenue["sources"]["2016"], "PDF S. 12")
        self.assertEqual(revenue["sources"]["2024"], "ESEF")
        margin = next(m for m in data["metrics"] if m["key"] == "net_margin")
        self.assertAlmostEqual(margin["values"]["2016"], 150 / 3000.5)
        self.assertEqual(data["origin"]["PDF"], [2016])
        # re-running the job keeps the imported figures
        self.run_company(include={"pdf": False})
        self.assertIn("2016", next(m for m in financials.table_for(self.app.db, COMPANY["lei"])["metrics"]
                                   if m["key"] == "revenue")["values"])

    def test_import_validation(self):
        db, lei = self.app.db, COMPANY["lei"]
        with self.assertRaises(ValueError):
            financials.import_manual(db, lei, [{"metric": "roe", "fiscal_year": 2020, "value": 0.1}])   # derived
        with self.assertRaises(ValueError):
            financials.import_manual(db, lei, [{"metric": "revenue", "fiscal_year": "x", "value": 1}])
        with self.assertRaises(ValueError):
            financials.import_manual(db, lei, [{"metric": "revenue", "fiscal_year": 2020, "value": "nan"}])
        self.assertEqual(db.manual_financials(lei), [])

    def test_value_view_and_cli_import(self):
        self.run_company(include={"esef": False})                                  # PDFs only, no figures
        view = financials.value_view(self.app.db, COMPANY["lei"])
        self.assertEqual(view["years"], [])
        self.assertEqual({c["status"] for c in view["checks"]}, {"na"})
        self.assertEqual(len(view["documents"]), 10)

        tmp = Path(tempfile.mkdtemp())
        csv = tmp / "figures.csv"
        lines = ["# test", "metric;fiscal_year;value;report_year;page"]
        for year, v in KSB.items():
            lines += [f"{k};{year};{val};{year};203" for k, val in v.items()]
        csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cfg = tmp / "portal.toml"
        cfg.write_text(f'library_dir = "{self.app.settings.library_dir}"\n')
        with redirect_stdout(io.StringIO()) as out:
            code = main(["--config", str(cfg), "import-figures", COMPANY["lei"], str(csv), "--millions"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn(f"{sum(len(v) for v in KSB.values())} Werte", out.getvalue())

        view = financials.value_view(self.app.db, COMPANY["lei"])
        self.assertEqual(view["years"], [2024, 2025])
        self.assertEqual(view["year"], 2025)
        checks = {c["key"]: c for c in view["checks"]}
        self.assertEqual(checks["debt"]["status"], "good")
        self.assertEqual(checks["roic"]["status"], "good")
        self.assertEqual(checks["roic"]["threshold"], 0.15)
        kpis = {k["key"]: k for k in view["kpis"]}
        self.assertAlmostEqual(kpis["owner_earnings"]["value"], 109.0e6)
        self.assertAlmostEqual(view["balance"]["coverage"], (1391.2 + 514.7) / 969.2)
        linked = [d for d in view["documents"] if d["figures"]]
        self.assertEqual({d["fiscal_year"] for d in linked}, {2024, 2025})      # figures linked to their report

        with redirect_stdout(io.StringIO()) as out:
            code = main(["--config", str(cfg), "import-figures", COMPANY["lei"], str(tmp / "missing.csv")])
        self.assertEqual(code, 1)
        self.assertIn("Import fehlgeschlagen", out.getvalue())


if __name__ == "__main__":
    unittest.main()
