"""GLEIF LEI register (api.gleif.org): legal name, country and ISIN-to-LEI mapping.

Every issuer with securities on an EU trading venue needs an LEI, so GLEIF is the reference
for "which company is this" across all EU markets. Free JSON:API, no key, 60 requests/minute.
"""

from __future__ import annotations

from ..identifiers import is_lei
from ..net import HttpError


def parse_record(rec: dict) -> dict:
    attrs = rec.get("attributes") or {}
    entity = attrs.get("entity") or {}
    legal = entity.get("legalAddress") or {}
    hq = entity.get("headquartersAddress") or {}
    name = (entity.get("legalName") or {}).get("name") or ""
    others = [n.get("name") for n in entity.get("otherNames") or [] if n.get("name")]
    return {
        "lei": attrs.get("lei") or rec.get("id"),
        "name": name,
        "country": (legal.get("country") or hq.get("country") or "").upper() or None,
        "meta": {
            "city": legal.get("city"),
            "hq_country": hq.get("country"),
            "legal_form": (entity.get("legalForm") or {}).get("id"),
            "entity_status": entity.get("status"),
            "other_names": others[:5],
            "gleif_registration": (attrs.get("registration") or {}).get("status"),
        },
    }


class Gleif:
    def __init__(self, ctx):
        self.ctx = ctx
        self.base = ctx.settings.gleif_api.rstrip("/")

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self.ctx.http.get_json(self.base + path, params=params,
                                      headers={"Accept": "application/vnd.api+json, application/json"})

    def by_lei(self, lei: str) -> dict | None:
        try:
            payload = self._get(f"/lei-records/{lei}")
        except HttpError as err:
            if err.status == 404:
                return None
            raise
        data = payload.get("data")
        return parse_record(data) if isinstance(data, dict) else None

    def by_leis(self, leis: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(leis), 100):
            chunk = [l for l in leis[i:i + 100] if is_lei(l)]
            if not chunk:
                continue
            payload = self._get("/lei-records", {"filter[lei]": ",".join(chunk), "page[size]": 100})
            out += [parse_record(r) for r in payload.get("data") or []]
        return out

    def by_isin(self, isin: str) -> dict | None:
        payload = self._get("/lei-records", {"filter[isin]": isin, "page[size]": 5})
        records = payload.get("data") or []
        return parse_record(records[0]) if records else None

    def isins(self, lei: str) -> list[str]:
        try:
            payload = self._get(f"/lei-records/{lei}/isins", {"page[size]": 200})
        except HttpError as err:
            if err.status == 404:
                return []
            raise
        return sorted({(r.get("attributes") or {}).get("isin") for r in payload.get("data") or []} - {None})

    def search(self, name: str, limit: int = 10) -> list[dict]:
        """Name search; returns parsed records (subsidiaries included, ranked by the caller).

        Full-text completions come first: they find names that contain the words ("GEA Group" ->
        "GEA Group Aktiengesellschaft"). Fuzzy completions compare whole names by edit distance and
        only add typo tolerance; on their own they return look-alikes such as "GET GROUP"."""
        leis: list[str] = []
        for endpoint, field in (("/autocompletions", "fulltext"), ("/fuzzycompletions", "entity.legalName")):
            if len(leis) >= limit:
                break
            try:
                payload = self._get(endpoint, {"field": field, "q": name})
            except HttpError:
                continue
            for item in payload.get("data") or []:
                rel = ((item.get("relationships") or {}).get("lei-records") or {}).get("data") or {}
                lei = rel.get("id") if isinstance(rel, dict) else None
                if lei and lei not in leis:
                    leis.append(lei)
        if leis:
            records = {r["lei"]: r for r in self.by_leis(leis[:2 * limit])}
            return [records[l] for l in leis if l in records]
        payload = self._get("/lei-records", {"filter[fulltext]": name, "page[size]": limit})
        return [parse_record(r) for r in payload.get("data") or []]
