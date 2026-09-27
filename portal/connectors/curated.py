"""Industry associations and public bodies: a curated start list per NACE division plus own sources.

Each source site is crawled lightly for publication pages; PDF links are scored for being an
industry report (facts & figures, market reports, statistics, outlooks) in the requested period.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..classify import classify_industry_link
from ..identifiers import nace_division
from .base import Candidate
from .crawler import SiteCrawler

PUBLICATION_HINTS = [
    ("publications", 6), ("publikationen", 6), ("veroffentlichungen", 6), ("publication", 5), ("reports", 5),
    ("report", 3), ("berichte", 5), ("studien", 5), ("studies", 5), ("statistics", 5), ("statistik", 5),
    ("statistiken", 5), ("facts and figures", 7), ("zahlen", 4), ("figures", 4), ("data", 2), ("daten", 2),
    ("market", 3), ("markt", 3), ("economic", 3), ("wirtschaft", 3), ("konjunktur", 4), ("outlook", 4),
    ("library", 3), ("mediathek", 3), ("downloads", 3), ("documents", 3), ("dokumente", 3), ("resources", 3),
    ("research", 3), ("analysen", 3), ("insights", 2), ("positions", 1), ("press", -1), ("presse", -1),
    ("events", -3), ("veranstaltungen", -3), ("jobs", -6), ("karriere", -6), ("career", -6), ("members", -2),
    ("mitglieder", -2), ("login", -6), ("shop", -4), ("datenschutz", -6), ("privacy", -6), ("impressum", -6),
]


def load_sources(path: str) -> dict[str, list[dict]]:
    file = Path(path)
    if not file.exists():
        return {}
    with file.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if not k.startswith("_")}


class Curated:
    def __init__(self, ctx):
        self.ctx = ctx

    def sources(self, nace: str) -> list[dict]:
        division = nace_division(nace)
        builtin = load_sources(self.ctx.settings.industry_sources_file)
        out = [dict(s, origin="Startliste") for s in builtin.get(division, []) + builtin.get("*", [])]
        out += [{"name": s["name"] or s["url"], "url": s["url"], "origin": "eigene Quelle"}
                for s in self.ctx.db.industry_sources(division)]
        seen, unique = set(), []
        for source in out:
            if source["url"] not in seen:
                seen.add(source["url"])
                unique.append(source)
        return unique

    def reports(self, nace: str, keywords: list[str], year_from: int, today: date | None = None) -> list[Candidate]:
        s = self.ctx.settings
        out: list[Candidate] = []
        for source in self.sources(nace):
            self.ctx.check_cancel()
            crawler = SiteCrawler(self.ctx, hints=PUBLICATION_HINTS, max_pages=int(source.get("max_pages", 25)),
                                  max_depth=2, use_sitemaps=False)
            found = crawler.crawl([source["url"]])
            ranked = []
            for url, infos in found.items():
                score, year = max((classify_industry_link(i, keywords, year_from, today) for i in infos),
                                  key=lambda r: r[0])
                if score >= 25:
                    info = max(infos, key=lambda i: len(i.anchor))
                    ranked.append(Candidate(url=url, category="association_report", source="curated",
                                            fiscal_year=year, title=info.anchor or url.rsplit("/", 1)[-1],
                                            score=score, subdir="associations",
                                            meta={"publisher": source["name"], "page": info.page_url,
                                                  "origin": source.get("origin")}))
            ranked.sort(key=lambda c: (c.score, c.fiscal_year or 0), reverse=True)
            self.ctx.log("info", f"{source['name']}: {crawler.pages_fetched} Seiten, {len(ranked)} passende PDFs")
            out += ranked[: s.curated_max_per_source]
        return out
