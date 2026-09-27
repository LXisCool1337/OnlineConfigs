import io
import unittest
import zipfile

from portal.connectors.crawler import parse_html, registrable_domain
from portal.connectors.esef import Esef, fy_label
from portal.connectors.eurostat import jsonstat_rows, to_csv
from portal.connectors.firds import issuer_name, parse_fulins
from portal.connectors.gleif import parse_record
from portal.identifiers import EU_EEA
from tests.fakeweb import BOND_ISIN, COMPANY, DELISTED, ESEF, PEER_IT, PEER_US, esef_entity, firds_zip, gleif_record, jsonstat


class JsonStatTests(unittest.TestCase):
    def test_flatten(self):
        header, rows = jsonstat_rows(jsonstat())
        self.assertEqual(len(rows), 20)
        self.assertIn("geo_label", header)
        first = rows[0]
        self.assertEqual((first["geo"], first["time"], first["nace_r2"]), ("DE", "2016", "C28"))
        eu_2019 = next(r for r in rows if r["geo"] == "EU27_2020" and r["time"] == "2019")
        self.assertEqual(eu_2019["value"], 94.5)
        self.assertEqual(eu_2019["flag"], "p")
        self.assertTrue(to_csv(header, rows).startswith("freq,indic_bt,indic_bt_label"))

    def test_array_values(self):
        js = jsonstat()
        js["value"] = [js["value"][str(i)] for i in range(20)]
        js["status"] = {}
        _, rows = jsonstat_rows(js)
        self.assertEqual(len(rows), 20)


class FirdsTests(unittest.TestCase):
    def test_parse(self):
        with zipfile.ZipFile(io.BytesIO(firds_zip())) as zf:
            with zf.open(zf.namelist()[0]) as stream:
                records = parse_fulins(stream, EU_EEA, ("ES", "EP"))
        self.assertIn(COMPANY["isin"], records)
        self.assertIn(PEER_IT["isin"], records)
        self.assertNotIn(PEER_US["isin"], records)      # not an EU/EEA ISIN
        self.assertNotIn(BOND_ISIN, records)            # a bond, not a share
        company = records[COMPANY["isin"]]
        self.assertEqual((company["lei"], company["mic"], company["issuer_requested"]), (COMPANY["lei"], "XETR", 1))
        self.assertIsNone(company["termination"])
        self.assertTrue(records[DELISTED["isin"]]["termination"].startswith("2020"))

    def test_issuer_name(self):
        self.assertEqual(issuer_name("KRONES AG O.N."), "KRONES AG")
        self.assertEqual(issuer_name("SIEMENS AG NA O.N."), "SIEMENS AG")
        self.assertEqual(issuer_name("MUSTER PACKAGING SPA"), "MUSTER PACKAGING SPA")


class EsefTests(unittest.TestCase):
    def test_parse_keeps_only_requested_issuer(self):
        payload = {"data": [f for rows in ESEF.values() for f in rows],
                   "included": [esef_entity(COMPANY), esef_entity(PEER_IT)]}

        class Ctx:
            class settings:
                esef_api = "https://filings.xbrl.org"
        rows, foreign = Esef(Ctx()).parse(payload, COMPANY["lei"])
        self.assertEqual(len(rows), 7)
        self.assertEqual(foreign, 4)
        self.assertTrue(rows[0]["report_url"].startswith("https://filings.xbrl.org/esef/files/"))
        latest = Esef._latest_per_period(rows)
        self.assertEqual(len(latest), 6)
        corrected = next(r for r in latest if r["period_end"] == "2021-12-31")
        self.assertTrue(corrected["fxo_id"].endswith("-1"))

    def test_fy_label(self):
        self.assertEqual(fy_label("2024-12-31"), "2024")
        self.assertEqual(fy_label("2024-09-30"), "2023/24")


class GleifTests(unittest.TestCase):
    def test_parse_record(self):
        rec = parse_record(gleif_record(COMPANY))
        self.assertEqual((rec["lei"], rec["name"], rec["country"]), (COMPANY["lei"], COMPANY["name"], "DE"))


class CrawlerTests(unittest.TestCase):
    def test_links_with_context(self):
        html = ("<html lang='de'><head><title>Berichte</title><script>var a='<a href=x.pdf>';</script></head><body>"
                "<h2>Geschäftsberichte</h2><table><tr><td>2018</td><td><a href='/f/GB18.pdf'>PDF</a></td></tr>"
                "<tr><td>2017</td><td><a href='f/gb17.pdf' title='Geschäftsbericht 2017'><img alt='Icon'> PDF</a></td></tr>"
                "</table><select><option value='/f/ar2016.pdf'>2016</option></select>"
                "<button data-href='/f/ar2015.pdf'>Download</button></body></html>")
        links = {l.url: l for l in parse_html(html, "https://x.de/ir/berichte/")}
        self.assertIn("https://x.de/f/GB18.pdf", links)
        self.assertIn("https://x.de/ir/berichte/f/gb17.pdf", links)
        self.assertIn("https://x.de/f/ar2016.pdf", links)
        self.assertIn("https://x.de/f/ar2015.pdf", links)
        self.assertNotIn("https://x.de/ir/berichte/x.pdf", links)
        gb18 = links["https://x.de/f/GB18.pdf"]
        self.assertEqual(gb18.heading, "Geschäftsberichte")
        self.assertTrue(gb18.context_before.endswith("2018"))
        self.assertEqual(gb18.page_lang, "de")
        self.assertEqual(links["https://x.de/ir/berichte/f/gb17.pdf"].title, "Geschäftsbericht 2017")

    def test_registrable_domain(self):
        self.assertEqual(registrable_domain("ir.krones.com"), "krones.com")
        self.assertEqual(registrable_domain("www.example.co.uk"), "example.co.uk")
        self.assertEqual(registrable_domain("127.0.0.1:8080"), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
