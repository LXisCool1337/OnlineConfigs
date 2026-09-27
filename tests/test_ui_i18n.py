"""Interface texts: every key the web UI uses exists in German and English, with the same placeholders."""

import json
import re
import unittest
from pathlib import Path

from portal.financials import DERIVED, METRICS
from portal.pipeline import CATEGORY_LABELS

STATIC = Path(__file__).resolve().parent.parent / "portal" / "static"
KEY = r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+"


def load(code: str) -> dict:
    def no_duplicates(pairs):
        keys = [k for k, _ in pairs]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise AssertionError(f"{code}.json: duplicate keys {sorted(dupes)}")
        return dict(pairs)
    return json.loads((STATIC / "i18n" / f"{code}.json").read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)


def sources() -> dict[str, str]:
    files = sorted((STATIC / "js").rglob("*.js"))
    return {str(p.relative_to(STATIC)): p.read_text(encoding="utf-8") for p in files}


def placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{([a-z_]+)\}", text))


class DictionaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.de = load("de")
        cls.en = load("en")
        cls.js = sources()
        cls.namespaces = {k.split(".")[0] for k in cls.de}

    def assertKeys(self, keys, where):
        missing = [k for k in keys if k not in self.de or k not in self.en]
        self.assertEqual(missing, [], f"missing in de/en ({where})")

    def test_same_keys_and_placeholders(self):
        self.assertEqual(sorted(set(self.de) - set(self.en)), [], "only in de.json")
        self.assertEqual(sorted(set(self.en) - set(self.de)), [], "only in en.json")
        for key in self.de:
            self.assertTrue(self.de[key].strip() and self.en[key].strip(), f"empty text: {key}")
            self.assertEqual(placeholders(self.de[key]), placeholders(self.en[key]), f"placeholders differ: {key}")

    def test_static_markup(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        keys = re.findall(r'data-i18n(?:-title|-aria|-placeholder)?="([^"]+)"', html)
        self.assertGreater(len(keys), 10)
        self.assertKeys(keys, "index.html")

    def test_literal_keys_in_scripts(self):
        """Every string literal that looks like a key is one - or the prefix of at least one."""
        checked = 0
        for name, text in self.js.items():
            for literal in re.findall(r'"([a-z][a-z0-9_]*\.[a-z0-9_.]*)"', text):
                if literal.split(".")[0] not in self.namespaces:
                    continue
                checked += 1
                if literal in self.de and literal in self.en:
                    continue
                prefix_ok = any(k.startswith(literal) for k in self.de) and literal.endswith((".", "_"))
                self.assertTrue(prefix_ok, f"{name}: unknown text key {literal!r}")
        self.assertGreater(checked, 300)

    def test_template_keys_in_scripts(self):
        """t(`step.${kind}.${key}`) and similar: each pattern matches at least one key."""
        for name, text in self.js.items():
            for template in re.findall(r"\bt\(`([^`]+)`", text):
                pattern = re.escape(template)
                pattern = re.sub(r"\\\$\\\{[^}]*\\\}", "[a-z0-9_]+", pattern)
                self.assertTrue(any(re.fullmatch(pattern, k) for k in self.de), f"{name}: no key for t(`{template}`)")

    def test_prefix_families_are_complete(self):
        jobs = self.js["js/jobs.js"]
        steps = {kind: re.findall(r'"([a-z_]+)"', body)
                 for kind, body in re.findall(r"(\w+): \[([^\]]*)\]", jobs.split("export const STEPS")[1].split("};")[0])}
        self.assertEqual(set(steps), {"company", "industry", "universe", "index"})
        self.assertKeys([f"step.{kind}.{key}" for kind, keys in steps.items() for key in keys], "steps")
        self.assertKeys([f"job.kind.{k}" for k in ("company", "industry", "batch", "refresh", "universe", "index")], "job kinds")
        self.assertKeys([f"job.status.{s}" for s in ("queued", "running", "cancelling", "done", "failed", "cancelled")],
                        "job status")
        self.assertKeys([f"step.status.{s}" for s in ("pending", "running", "done", "skipped", "failed")], "step status")
        pipeline = "".join((STATIC.parent / p).read_text(encoding="utf-8") for p in ("pipeline.py", "connectors/irsite.py"))
        reasons = set(re.findall(r'skipped="([a-z_]+)"', pipeline)) | set(re.findall(r'ctx\.skip\([^,]+, "([a-z_]+)"', pipeline))
        self.assertIn("deselected", reasons)
        self.assertKeys([f"skip.{r}" for r in reasons | {"not_needed", "not_selected"}], "skip reasons")
        self.assertKeys([f"cat.{c}" for c in CATEGORY_LABELS], "categories")
        self.assertKeys([f"metric.{m[0]}" for m in METRICS + DERIVED], "metrics")
        self.assertKeys([f"source.{s}" for s in ("esef", "irsite", "websearch", "manual", "eurostat", "openalex", "curated")],
                        "sources")
        diagnostics = (STATIC.parent / "diagnostics.py").read_text(encoding="utf-8")
        self.assertKeys([f"sources.name.{k}" for k in re.findall(r'\("([a-z]+)", f"', diagnostics)], "diagnostics")
        self.assertKeys([f"sources.state.{c}" for c in re.findall(r'code="([a-z_]+)"', diagnostics)], "diagnostics codes")
        server = (STATIC.parent / "server.py").read_text(encoding="utf-8")
        self.assertKeys([f"search.warning.{c}" for c in re.findall(r'"warning_code": "([a-z_]+)"', server)], "warnings")
        help_js = self.js["js/help.js"]
        terms = re.findall(r'^  \["([a-z_]+)", \{', help_js, re.M)
        self.assertGreater(len(terms), 20)
        self.assertKeys([f"term.{k}" for k in terms[:terms.index("missing_years")]], "glossary")
        self.assertKeys([f"faq.{k}" for k in terms[terms.index("missing_years"):]], "questions")
        routes = re.search(r"const ROUTES = \{([^}]*)\}", self.js["js/main.js"]).group(1)
        self.assertKeys([f"nav.{r.split(':')[0].strip()}" for r in routes.split(",")], "routes")

    def test_help_entries_have_both_languages(self):
        help_js = self.js["js/help.js"]
        self.assertEqual(help_js.count("\n    de: "), help_js.count("\n    en: "))


if __name__ == "__main__":
    unittest.main()
