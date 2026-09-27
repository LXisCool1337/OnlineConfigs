import unittest

from portal.identifiers import (detect, eurostat_nace, is_isin, is_lei, language_preferences, nace_label,
                                nace_section, normalize_nace, short_name)


class IdentifierTests(unittest.TestCase):
    def test_isin_checksum(self):
        self.assertTrue(is_isin("DE0006335003"))   # Krones
        self.assertTrue(is_isin("US0378331005"))   # Apple
        self.assertFalse(is_isin("DE0006335004"))
        self.assertFalse(is_isin("DE000633500"))

    def test_lei_checksum(self):
        from portal.identifiers import lei_check_digits
        lei = "529900BSPMASCHINEN" + lei_check_digits("529900BSPMASCHINEN")
        self.assertTrue(is_lei(lei))
        self.assertFalse(is_lei(lei[:-1] + str((int(lei[-1]) + 1) % 10)))

    def test_detect(self):
        self.assertEqual(detect(" de0006335003 "), ("isin", "DE0006335003"))
        self.assertEqual(detect("Krones AG")[0], "name")

    def test_short_name(self):
        self.assertEqual(short_name("Krones Aktiengesellschaft"), "Krones")
        self.assertEqual(short_name("Muster Packaging S.p.A."), "Muster Packaging")
        self.assertEqual(short_name("Volvo AB (publ)"), "Volvo")
        self.assertEqual(short_name("SAP SE"), "SAP")
        self.assertEqual(short_name("AG"), "AG")

    def test_nace(self):
        self.assertEqual(normalize_nace("C2829"), "28.29")
        self.assertEqual(normalize_nace("28.2"), "28.2")
        self.assertEqual(normalize_nace("28"), "28")
        self.assertIsNone(normalize_nace("04"))
        self.assertIsNone(normalize_nace("abc"))
        self.assertEqual(nace_section("28"), "C")
        self.assertEqual(eurostat_nace("28.29"), "C2829")
        self.assertEqual(nace_label("28.29"), "Maschinenbau")

    def test_language_preferences(self):
        self.assertEqual(language_preferences(["en", "local"], "FR"), ["en", "fr"])
        self.assertEqual(language_preferences(["local", "en"], "IE"), ["en"])


if __name__ == "__main__":
    unittest.main()
