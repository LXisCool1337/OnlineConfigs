"""Optional web search (Brave Search API or a self-hosted SearXNG) to fill gaps.

Used for fiscal years that neither ESEF nor the IR website covered, and for industry reports.
Company hits are only accepted from the company's own domain or from known IR hosting services.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit

from ..classify import LinkInfo, classify_industry_link, classify_report_link, score_report
from ..identifiers import short_name
from ..net import HttpError, host_of
from .base import Candidate
from .crawler import looks_like_document, registrable_domain

REPORT_WORDS = {"de": "Geschäftsbericht", "en": "annual report", "fr": "rapport annuel", "nl": "jaarverslag",
                "it": "relazione finanziaria annuale", "es": "informe anual", "pt": "relatório e contas",
                "sv": "årsredovisning", "da": "årsrapport", "no": "årsrapport", "fi": "vuosikertomus",
                "pl": "raport roczny", "cs": "výroční zpráva", "sk": "výročná správa", "hu": "éves jelentés",
                "ro": "raport anual", "el": "ετήσια οικονομική έκθεση", "sl": "letno poročilo",
                "hr": "godišnje izvješće", "lt": "metinis pranešimas", "lv": "gada pārskats", "et": "aastaaruanne",
                "bg": "годишен доклад", "is": "ársskýrsla"}


class WebSearch:
    def __init__(self, ctx):
        self.ctx = ctx
        self.s = ctx.settings

    @property
    def enabled(self) -> bool:
        return (self.s.search_provider == "brave" and bool(self.s.brave_api_key)) or \
               (self.s.search_provider == "searxng" and bool(self.s.searxng_url))

    def search(self, query: str, count: int = 10) -> list[dict]:
        try:
            if self.s.search_provider == "brave":
                payload = self.ctx.http.get_json(self.s.brave_api, params={"q": query, "count": count},
                                                 headers={"X-Subscription-Token": self.s.brave_api_key})
                results = (payload.get("web") or {}).get("results") or []
                return [{"url": r.get("url"), "title": r.get("title") or "", "snippet": r.get("description") or ""}
                        for r in results if r.get("url")]
            if self.s.search_provider == "searxng":
                payload = self.ctx.http.get_json(self.s.searxng_url.rstrip("/") + "/search",
                                                 params={"q": query, "format": "json"})
                return [{"url": r.get("url"), "title": r.get("title") or "", "snippet": r.get("content") or ""}
                        for r in (payload.get("results") or [])[:count] if r.get("url")]
        except HttpError as err:
            self.ctx.log("warn", f"Websuche fehlgeschlagen: {err}")
        return []

    def _trusted(self, url: str, company: dict) -> bool:
        host = host_of(url).split(":")[0]
        own = {registrable_domain(host_of(u)) for u in (company.get("website"), company.get("ir_url")) if u}
        if registrable_domain(host) in own:
            return True
        if any(host == h or host.endswith("." + h) for h in self.s.search_trusted_hosts):
            return True
        token = short_name(company.get("name") or "").split(" ")[0].lower()
        return len(token) >= 4 and token in host

    def annual_reports(self, company: dict, years: list[int], prefs: list[str], today: date | None = None,
                       max_queries: int = 8) -> list[Candidate]:
        name = short_name(company.get("name") or "")
        out: list[Candidate] = []
        queries = 0
        for year in years:
            for lang in prefs[:2]:
                if queries >= max_queries:
                    return out
                word = REPORT_WORDS.get(lang, "annual report")
                queries += 1
                for hit in self.search(f'"{name}" {word} {year} filetype:pdf'):
                    url = hit["url"]
                    if not looks_like_document(url) or not self._trusted(url, company):
                        continue
                    info = LinkInfo(url=url, anchor=hit["title"], context_before=hit["snippet"][:160])
                    guess = classify_report_link(info, today)
                    if guess.category != "annual_report" or guess.fiscal_year != year:
                        continue
                    out.append(Candidate(url=url, category="annual_report", source="websearch", fiscal_year=year,
                                         fy_label=guess.fy_label, language=guess.language, title=hit["title"],
                                         score=score_report(guess, prefs) - 10, meta={"query_lang": lang}))
        return out

    def industry_reports(self, label_en: str, label_de: str, keywords: list[str], year_from: int,
                         limit: int = 10, today: date | None = None) -> list[Candidate]:
        queries = [f'"{label_en}" industry report Europe filetype:pdf',
                   f'"{label_de}" Branchenbericht filetype:pdf',
                   f'"{label_en}" market outlook {(today or date.today()).year - 1} filetype:pdf']
        queries += [f'"{kw}" industry report filetype:pdf' for kw in keywords[:2]]
        seen, out = set(), []
        for query in queries:
            for hit in self.search(query):
                url = hit["url"]
                if url in seen or not looks_like_document(url) or urlsplit(url).scheme != "https":
                    continue
                seen.add(url)
                info = LinkInfo(url=url, anchor=hit["title"], context_before=hit["snippet"][:160])
                score, year = classify_industry_link(info, keywords + [label_en, label_de], year_from, today)
                if score < 25:
                    continue
                out.append(Candidate(url=url, category="web_report", source="websearch", fiscal_year=year,
                                     title=hit["title"], score=score, subdir="web",
                                     meta={"query": query, "snippet": hit["snippet"][:300]}))
        out.sort(key=lambda c: c.score, reverse=True)
        return out[:limit]
