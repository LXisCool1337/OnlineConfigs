"""ESEF annual financial reports from filings.xbrl.org.

Since financial year 2020 (2021 in member states that used the one-year deferral), every issuer on
an EU regulated market files its annual financial report in ESEF format: an XHTML document with
inline XBRL tags, packaged as a ZIP. filings.xbrl.org (XBRL International) collects these filings
from the national storage mechanisms and exposes them through a JSON:API.

The server-side filter syntax is not trusted blindly: every returned filing is checked against the
requested LEI, so a changed or ignored filter can never flood the library with other companies.
"""

from __future__ import annotations

import json
from urllib.parse import urljoin

from ..net import HttpError
from .base import Candidate

FORMATS = {
    "report": ("report_url", "esef_report", "xhtml", ("xhtml", "html", "xml")),
    "package": ("package_url", "esef_package", "zip", ("zip",)),
    "json": ("json_url", "esef_json", "json", ("json",)),
}


def fy_label(period_end: str) -> str:
    year = int(period_end[:4])
    return str(year) if period_end[5:10] == "12-31" else f"{year - 1}/{str(year)[2:]}"


class Esef:
    def __init__(self, ctx):
        self.ctx = ctx
        self.base = ctx.settings.esef_api.rstrip("/")

    def _get(self, url: str, params: dict | None = None) -> dict:
        return self.ctx.http.get_json(url, params=params,
                                      headers={"Accept": "application/vnd.api+json, application/json"})

    def filings(self, lei: str) -> list[dict]:
        """All filings of one issuer, newest period first, one entry per period (latest submission wins)."""
        rows: list[dict] = []
        entity_filter = json.dumps([{"name": "entity", "op": "has",
                                     "val": {"name": "identifier", "op": "eq", "val": lei}}], separators=(",", ":"))
        try:
            rows = self._collect(f"{self.base}/api/filings",
                                 {"filter": entity_filter, "include": "entity", "sort": "-period_end",
                                  "page[size]": 100}, lei)
        except HttpError as err:
            self.ctx.log("info", "ESEF-Filter nicht akzeptiert, nutze Entitäts-Abfrage", status=err.status)
        if not rows:
            rows = self._via_entity(lei)
        return self._latest_per_period(rows)

    def _collect(self, url: str, params: dict | None, lei: str, max_pages: int = 5) -> list[dict]:
        rows: list[dict] = []
        for _ in range(max_pages):
            payload = self._get(url, params)
            batch, foreign = self.parse(payload, lei)
            rows += batch
            if foreign and not batch:
                break  # the filter was ignored: stop instead of paging through everybody's filings
            nxt = (payload.get("links") or {}).get("next")
            if not nxt:
                break
            url, params = urljoin(self.base + "/", nxt), None
        return rows

    def _via_entity(self, lei: str) -> list[dict]:
        entity_filter = json.dumps([{"name": "identifier", "op": "eq", "val": lei}], separators=(",", ":"))
        try:
            payload = self._get(f"{self.base}/api/entities", {"filter": entity_filter})
        except HttpError:
            return []
        for entity in payload.get("data") or []:
            attrs = entity.get("attributes") or {}
            if attrs.get("identifier") != lei:
                continue
            related = (((entity.get("relationships") or {}).get("filings") or {}).get("links") or {}).get("related")
            url = urljoin(self.base + "/", related) if related else f"{self.base}/api/entities/{entity.get('id')}/filings"
            try:
                return self._collect(url, None, lei)
            except HttpError:
                return []
        return []

    def parse(self, payload: dict, lei: str) -> tuple[list[dict], int]:
        """Filings belonging to ``lei`` and the number of filings that belonged to someone else."""
        included = {(i.get("type"), str(i.get("id"))): i for i in payload.get("included") or []}
        rows, foreign = [], 0
        for item in payload.get("data") or []:
            attrs = item.get("attributes") or {}
            owner = None
            rel = ((item.get("relationships") or {}).get("entity") or {}).get("data")
            if isinstance(rel, dict):
                entity = included.get((rel.get("type"), str(rel.get("id"))))
                if entity:
                    owner = (entity.get("attributes") or {}).get("identifier")
            fxo = attrs.get("fxo_id") or ""
            if not owner and len(fxo) >= 20:
                owner = fxo[:20]
            period_end = (attrs.get("period_end") or "")[:10]
            if owner != lei or len(period_end) != 10:
                foreign += 1
                continue
            rows.append({
                "fxo_id": fxo,
                "period_end": period_end,
                "country": attrs.get("country"),
                "date_added": attrs.get("date_added") or attrs.get("added_time") or "",
                "report_url": self._abs(attrs.get("report_url")),
                "package_url": self._abs(attrs.get("package_url")),
                "json_url": self._abs(attrs.get("json_url")),
                "viewer_url": self._abs(attrs.get("viewer_url")),
                "errors": attrs.get("error_count"),
            })
        return rows, foreign

    def _abs(self, url: str | None) -> str | None:
        return urljoin(self.base + "/", url) if url else None

    @staticmethod
    def _latest_per_period(rows: list[dict]) -> list[dict]:
        best: dict[str, dict] = {}
        for row in rows:
            current = best.get(row["period_end"])
            if current is None or (row["date_added"], row["fxo_id"]) > (current["date_added"], current["fxo_id"]):
                if current is not None:
                    row = {**row, "superseded": current.get("superseded", []) + [current["fxo_id"]]}
                best[row["period_end"]] = row
        return sorted(best.values(), key=lambda r: r["period_end"], reverse=True)

    @staticmethod
    def candidates(filings: list[dict], formats: list[str], years: set[int] | None = None,
                   lei: str | None = None, category_override: str | None = None,
                   subdir: str = "") -> list[Candidate]:
        out = []
        for filing in filings:
            year = int(filing["period_end"][:4])
            if years is not None and year not in years:
                continue
            for fmt in formats:
                if fmt not in FORMATS:
                    continue
                key, category, ext, expect = FORMATS[fmt]
                url = filing.get(key)
                if not url:
                    continue
                if category_override:
                    category = f"{category_override}_{fmt}" if fmt != "report" else category_override
                out.append(Candidate(
                    url=url, category=category, source="esef", fiscal_year=year,
                    fy_label=fy_label(filing["period_end"]), period_end=filing["period_end"],
                    title=f"ESEF-Jahresfinanzbericht {fy_label(filing['period_end'])}", score=100.0,
                    ext=ext, expect=expect, lei=lei, subdir=subdir,
                    meta={"fxo_id": filing.get("fxo_id"), "viewer_url": filing.get("viewer_url"),
                          "country": filing.get("country")}))
        return out

    def issuers(self, max_pages: int = 1000, page_size: int = 200):
        """Yield (lei, name, country) for every ESEF filer (used to build the universe)."""
        url = f"{self.base}/api/filings"
        params: dict | None = {"include": "entity", "page[size]": page_size, "sort": "-date_added"}
        seen: set[str] = set()
        for _ in range(max_pages):
            self.ctx.check_cancel()
            payload = self._get(url, params)
            included = {(i.get("type"), str(i.get("id"))): i for i in payload.get("included") or []}
            for item in payload.get("data") or []:
                attrs = item.get("attributes") or {}
                rel = ((item.get("relationships") or {}).get("entity") or {}).get("data")
                entity = included.get((rel.get("type"), str(rel.get("id")))) if isinstance(rel, dict) else None
                eattrs = (entity or {}).get("attributes") or {}
                lei = eattrs.get("identifier") or (attrs.get("fxo_id") or "")[:20]
                if not lei or lei in seen:
                    continue
                seen.add(lei)
                yield lei, eattrs.get("name") or "", (attrs.get("country") or "").upper() or None
            nxt = (payload.get("links") or {}).get("next")
            if not nxt:
                break
            url, params = urljoin(self.base + "/", nxt), None
