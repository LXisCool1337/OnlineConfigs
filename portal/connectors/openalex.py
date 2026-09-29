"""Open-access industry studies from OpenAlex (reports and papers with a free PDF)."""

from __future__ import annotations

from ..net import HttpError
from .base import Candidate


class OpenAlex:
    def __init__(self, ctx):
        self.ctx = ctx
        self.base = ctx.settings.openalex_api.rstrip("/")

    def studies(self, query: str, year_from: int, limit: int) -> list[Candidate]:
        s = self.ctx.settings
        filters = ["is_oa:true", f"from_publication_date:{year_from}-01-01"]
        if s.openalex_types:
            filters.append(f"type:{s.openalex_types}")
        params = {"search": query, "filter": ",".join(filters), "per-page": min(max(limit * 2, 10), 100),
                  "sort": "relevance_score:desc"}
        if s.contact_email:
            params["mailto"] = s.contact_email  # OpenAlex "polite pool"
        try:
            payload = self.ctx.http.get_json(f"{self.base}/works", params=params)
        except HttpError as err:
            self.ctx.log("warn", f"OpenAlex nicht erreichbar: {err}")
            return []
        out = []
        for work in payload.get("results") or []:
            best = work.get("best_oa_location") or {}
            pdf = best.get("pdf_url") or ((work.get("open_access") or {}).get("oa_url") or "")
            if not pdf or not (pdf.lower().endswith(".pdf") or best.get("pdf_url")):
                continue
            authors = [((a.get("author") or {}).get("display_name")) for a in (work.get("authorships") or [])[:3]]
            source = (best.get("source") or {}).get("display_name")
            out.append(Candidate(
                url=pdf, category="study", source="openalex", fiscal_year=work.get("publication_year"),
                title=work.get("display_name") or work.get("title") or pdf, score=float(len(out) * -1),
                subdir="studies",
                meta={"doi": work.get("doi"), "openalex": work.get("id"), "type": work.get("type"),
                      "license": best.get("license"), "authors": [a for a in authors if a], "venue": source,
                      "landing_page": best.get("landing_page_url")}))
            if len(out) >= limit:
                break
        return out
