import unittest
from datetime import date

from portal.classify import LinkInfo, classify_industry_link, classify_report_link, extract_years, score_report

TODAY = date(2026, 9, 27)


def guess(url, anchor="", **kw):
    return classify_report_link(LinkInfo(url=url, anchor=anchor, **kw), TODAY)


class ReportClassificationTests(unittest.TestCase):
    CASES = [
        # url, anchor, category, year, language
        ("https://x.de/media/gb-2019-de.pdf", "Geschäftsbericht 2019", "annual_report", 2019, "de"),
        ("https://x.de/media/annual-report-2019-en.pdf", "Annual Report 2019", "annual_report", 2019, "en"),
        ("https://x.de/media/hj-2025.pdf", "Halbjahresfinanzbericht 2025", "interim_report", 2025, None),
        ("https://x.fr/docs/URD_2021_FR.pdf", "Document d'enregistrement universel 2021", "annual_report", 2021, "fr"),
        ("https://x.se/arsredovisning-2020.pdf", "Års- och hållbarhetsredovisning 2020", "annual_report", 2020, "sv"),
        ("https://x.it/Relazione_finanziaria_annuale_2022.pdf", "Relazione finanziaria annuale 2022", "annual_report", 2022, "it"),
        ("https://x.nl/jaarverslag-2018.pdf", "Jaarverslag 2018", "annual_report", 2018, "nl"),
        ("https://x.es/informe-anual-2021.pdf", "Informe anual 2021", "annual_report", 2021, "es"),
        ("https://x.pl/raport-roczny-2021.pdf", "Skonsolidowany raport roczny 2021", "annual_report", 2021, "pl"),
        ("https://x.fi/vuosikertomus-2019.pdf", "Vuosikertomus 2019", "annual_report", 2019, "fi"),
        ("https://x.cz/vz-2020.pdf", "Výroční zpráva 2020", "annual_report", 2020, "cs"),
        ("https://x.de/nb-2024.pdf", "Nachhaltigkeitsbericht 2024", "sustainability_report", 2024, None),
        ("https://x.de/verg-2024.pdf", "Vergütungsbericht 2024", "remuneration_report", 2024, None),
        ("https://x.es/iar-2022.pdf", "Informe anual de remuneraciones 2022", "remuneration_report", 2022, "es"),
        ("https://x.pl/raport-polroczny-2021.pdf", "Raport półroczny 2021", "interim_report", 2021, None),
        ("https://x.de/ja-2019.pdf", "Jahresabschluss der Beispiel AG 2019 (HGB)", "single_entity_statements", 2019, "de"),
        ("https://x.de/einladung-hv-2026.pdf", "Einladung zur Hauptversammlung 2026", "agm", 2026, None),
        ("https://x.de/praes.pdf", "Präsentation zum Geschäftsbericht 2024", "presentation", 2024, "de"),
        ("https://x.com/uploads/2021/03/Annual-Report-2020.pdf", "Download", "annual_report", 2020, "en"),
        ("https://x.com/ar/AR19_EN.pdf", "", "annual_report", 2019, "en"),
        ("https://x.de/gb-2023-24.pdf", "Geschäftsbericht 2023/24", "annual_report", 2024, "de"),
        ("https://x.fr/rapport-annuel-2019.pdf", "Rapport annuel de 2019 (EN)", "annual_report", 2019, "en"),
    ]

    def test_cases(self):
        for url, anchor, category, year, lang in self.CASES:
            with self.subTest(anchor=anchor or url):
                g = guess(url, anchor)
                self.assertEqual(g.category, category)
                self.assertEqual(g.fiscal_year, year)
                if lang is not None:
                    self.assertEqual(g.language, lang)

    def test_fiscal_year_label(self):
        self.assertEqual(guess("https://x.de/gb.pdf", "Geschäftsbericht 2019/2020").fy_label, "2019/20")

    def test_generic_anchor_uses_row_context(self):
        g = guess("https://x.de/media/archiv/GB18.pdf", "PDF (4 MB)",
                  context_before="Jahr Download 2018", heading="Geschäftsberichte-Archiv")
        self.assertEqual((g.category, g.fiscal_year), ("annual_report", 2018))
        g = guess("https://x.de/files/doc123.pdf", "PDF", context_before="2017 Geschäftsbericht",
                  heading="Berichte")
        self.assertEqual((g.category, g.fiscal_year), ("annual_report", 2017))
        self.assertIn("from_context", g.flags)

    def test_summary_ranks_below_full_report(self):
        full = guess("https://x.de/gb-2024.pdf", "Geschäftsbericht 2024")
        short = guess("https://x.de/gb-2024-kurz.pdf", "Geschäftsbericht 2024 – Kurzfassung")
        self.assertGreater(score_report(full, ["de"]), score_report(short, ["de"]))

    def test_language_preference_ranks(self):
        en = guess("https://x.de/ar-2024-en.pdf", "Annual Report 2024")
        de = guess("https://x.de/gb-2024-de.pdf", "Geschäftsbericht 2024")
        self.assertGreater(score_report(en, ["en", "de"]), score_report(de, ["en", "de"]))
        self.assertGreater(score_report(de, ["de", "en"]), score_report(en, ["de", "en"]))

    def test_dates_are_not_fiscal_years(self):
        hits = extract_years("report 2021-03-15 annual 2020", 1990, 2027)
        self.assertEqual([h.year for h in hits if not h.date], [2020])


class IndustryClassificationTests(unittest.TestCase):
    def test_relevant_and_irrelevant(self):
        ok, year = classify_industry_link(LinkInfo("https://v.eu/f/b.pdf", anchor="Branchenbericht Maschinenbau 2024"),
                                          ["Maschinenbau"], 2016, TODAY)
        self.assertGreaterEqual(ok, 25)
        self.assertEqual(year, 2024)
        bad, _ = classify_industry_link(LinkInfo("https://v.eu/f/e.pdf", anchor="Einladung zur Mitgliederversammlung 2025"),
                                        [], 2016, TODAY)
        self.assertLess(bad, 25)
        old, _ = classify_industry_link(LinkInfo("https://v.eu/f/j.pdf", anchor="Jahresbericht 2012"), [], 2016, TODAY)
        self.assertLess(old, 25)


if __name__ == "__main__":
    unittest.main()
