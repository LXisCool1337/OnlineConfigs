"""Annual-report PDFs from the company's own investor-relations website.

This is the main source for the years before ESEF (2016-2019) and for the designed PDF
version of later reports. Candidates are classified and ranked per fiscal year.
"""

from __future__ import annotations

import re
from datetime import date

from ..classify import classify_report_link, score_report
from .base import Candidate
from .crawler import SiteCrawler

IR_HINTS = [
    ("investor relations", 6), ("investor", 5), ("investors", 5), ("investoren", 5), ("relations", 2), ("ir", 2),
    ("annual report", 8), ("geschaftsbericht", 8), ("geschaeftsbericht", 8), ("jahresbericht", 6),
    ("financial reports", 7), ("finanzberichte", 7), ("finanzbericht", 6), ("berichte", 4), ("reports", 4),
    ("report", 2), ("publications", 4), ("publikationen", 4), ("veroffentlichungen", 4), ("archive", 3),
    ("archiv", 3), ("results", 2), ("ergebnisse", 2), ("downloads", 2), ("download center", 3),
    ("financial", 2), ("finanzen", 2), ("finanz", 2), ("shareholder", 2), ("aktionare", 2), ("aktie", 1),
    ("reporting", 3), ("rapport annuel", 8), ("rapports", 4), ("information financiere", 5),
    ("informations financieres", 5), ("documentation", 2), ("relazioni", 5), ("bilanci", 5),
    ("bilanci e relazioni", 7), ("informes", 4), ("informe anual", 8), ("jaarverslagen", 7), ("jaarverslag", 7),
    ("arsredovisningar", 7), ("arsredovisning", 7), ("rapporter", 4), ("julkaisut", 4), ("raporty", 4),
    ("raporty okresowe", 6), ("vuosikertomus", 7), ("financial information", 5), ("financial statements", 4),
    ("karriere", -6), ("career", -6), ("careers", -6), ("jobs", -6), ("produkte", -3), ("products", -3),
    ("blog", -3), ("shop", -6), ("login", -6), ("kontakt", -3), ("contact", -3), ("datenschutz", -6),
    ("privacy", -6), ("impressum", -6), ("imprint", -6), ("cookie", -6), ("newsroom", -1), ("event", -2),
]
IR_GUESS_PATHS = ("/investor-relations", "/investors", "/en/investor-relations", "/en/investors",
                  "/de/investor-relations", "/de/investoren", "/investoren", "/ir", "/en/ir", "/de/ir")

WANTED = {"annual_report", "single_entity_statements", "sustainability_report"}


GENERIC_TEXT = re.compile(r"(?i)pdf|download|herunterladen|öffnen|open|\d+(?:[.,]\d+)?\s*(?:mb|kb)|[()\[\]\s|·,-]")


def link_title(info, fy_label: str | None) -> str:
    """The link text, or heading plus year when the link only says 'PDF (4 MB)'."""
    text = info.anchor or info.title
    if text and len(GENERIC_TEXT.sub("", text)) >= 4:
        return text
    if info.heading:
        return f"{info.heading} – {fy_label}" if fy_label else info.heading
    return text or info.url.rsplit("/", 1)[-1]


class IrSite:
    def __init__(self, ctx):
        self.ctx = ctx

    def discover(self, company: dict, years: set[int], prefs: list[str], today: date | None = None) -> list[Candidate]:
        seeds = [u for u in (company.get("ir_url"), company.get("website")) if u]
        if not seeds:
            self.ctx.log("warn", "Keine Website/IR-Seite bekannt – bitte IR-URL angeben, sonst fehlen PDF-Berichte",
                         step="irsite", skipped="no_website")
            return []
        s = self.ctx.settings
        crawler = SiteCrawler(self.ctx, hints=IR_HINTS, max_pages=s.crawl_max_pages, max_depth=s.crawl_max_depth,
                              guess_paths=IR_GUESS_PATHS)
        found = crawler.crawl(seeds)
        self.ctx.log("info", f"IR-Website: {crawler.pages_fetched} Seiten gelesen, {len(found)} PDF-Links gefunden",
                     blocked_by_robots=len(crawler.blocked))
        out = []
        for url, infos in found.items():
            best = None
            for info in infos:
                guess = classify_report_link(info, today)
                ranked = (guess.category == "annual_report", score_report(guess, prefs))
                if best is None or ranked > best[0]:
                    best = (ranked, guess, info)
            _, guess, info = best
            if guess.category not in WANTED or guess.fiscal_year not in years:
                continue
            out.append(Candidate(
                url=url, category=guess.category, source="irsite", fiscal_year=guess.fiscal_year,
                fy_label=guess.fy_label, language=guess.language, title=link_title(info, guess.fy_label),
                score=score_report(guess, prefs),
                meta={"page": info.page_url, "flags": sorted(guess.flags), "strength": guess.strength}))
        return out
