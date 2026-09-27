"""Find and describe a company: search by name/ISIN/LEI, resolve to an LEI, enrich with website and industry."""

from __future__ import annotations

from .connectors.gleif import Gleif
from .connectors.wikidata import Wikidata
from .identifiers import EU_EEA, detect
from .net import HttpError


class NotFound(Exception):
    pass


class Resolver:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db
        self.gleif = Gleif(ctx)
        self.wikidata = Wikidata(ctx)

    def _mark(self, company: dict) -> dict:
        company = dict(company)
        company["eu"] = (company.get("country") or "") in EU_EEA
        docs = self.db.one("SELECT COUNT(*) AS n FROM documents WHERE scope = 'company' AND lei = ?", (company["lei"],))
        company["in_library"] = docs["n"] if docs else 0
        return company

    def search(self, query: str, limit: int = 15) -> tuple[list[dict], str | None]:
        """Local universe first, GLEIF online second. Returns (results, warning)."""
        kind, value = detect(query)
        results: dict[str, dict] = {}
        warning = None
        if kind == "isin":
            local = self.db.company_by_isin(value)
            if local:
                results[local["lei"]] = local
        elif kind == "lei":
            local = self.db.company(value)
            if local:
                results[local["lei"]] = local
        else:
            for row in self.db.search_companies(value, limit):
                results[row["lei"]] = row
        if len(results) < limit and (kind != "name" or len(value) >= 3):
            try:
                if kind == "isin":
                    remote = [r for r in [self.gleif.by_isin(value)] if r]
                    for r in remote:
                        r["isins"] = [value]
                elif kind == "lei":
                    remote = [r for r in [self.gleif.by_lei(value)] if r]
                else:
                    remote = self.gleif.search(value, limit=10)
                for rec in remote:
                    if rec["lei"] not in results:
                        known = self.db.company(rec["lei"])
                        results[rec["lei"]] = known or {**rec, "listed": 0, "has_esef": 0}
            except HttpError as err:
                warning = f"GLEIF nicht erreichbar ({err.status or 'Netzwerk'}); nur lokale Treffer."
        ranked = sorted(results.values(), key=lambda c: (not c.get("listed"), not c.get("has_esef"),
                                                         (c.get("country") or "") not in EU_EEA, c.get("name") or ""))
        return [self._mark(c) for c in ranked[:limit]], warning

    def resolve(self, query: str | None = None, lei: str | None = None) -> dict:
        if lei:
            company = self.db.company(lei)
            if company:
                return company
            try:
                record = self.gleif.by_lei(lei)
            except HttpError as err:
                raise NotFound(f"LEI {lei} unbekannt und GLEIF nicht erreichbar ({err})") from None
            if not record:
                raise NotFound(f"LEI {lei} nicht im GLEIF-Register")
            return self.db.upsert_company(record)
        if not query:
            raise NotFound("Kein Unternehmen angegeben")
        kind, value = detect(query)
        if kind == "lei":
            return self.resolve(lei=value)
        if kind == "isin":
            company = self.db.company_by_isin(value)
            if company:
                return company
            try:
                record = self.gleif.by_isin(value)
            except HttpError as err:
                raise NotFound(f"ISIN {value}: GLEIF nicht erreichbar ({err})") from None
            if not record:
                raise NotFound(f"Zu ISIN {value} ist im GLEIF-Register kein Emittent hinterlegt")
            return self.db.upsert_company({**record, "isins": [value], "listed": 1})
        results, _warning = self.search(value, limit=10)
        if not results:
            raise NotFound(f"Kein Unternehmen zu „{value}“ gefunden")
        best = results[0]
        if len(results) > 1:
            self.ctx.log("info", f"Mehrdeutiger Name, gewählt: {best['name']} ({best['lei']})",
                         alternatives=[f"{r['name']} ({r['lei']})" for r in results[1:5]])
        return self.db.upsert_company({k: v for k, v in best.items() if k not in ("eu", "in_library")})

    def enrich(self, company: dict) -> dict:
        """Add ISINs (GLEIF) and website/industries (Wikidata) where missing. Never fails the job."""
        update: dict = {"lei": company["lei"]}
        if not company.get("isins"):
            try:
                isins = self.gleif.isins(company["lei"])
                if isins:
                    update["isins"] = isins
                    update["listed"] = 1
            except HttpError as err:
                self.ctx.log("warn", f"GLEIF (ISINs) nicht erreichbar: {err}")
        if not company.get("website") or not company.get("industries"):
            try:
                info = self.wikidata.company(company["lei"], update.get("isins") or company.get("isins") or [])
                if info:
                    update.update({k: v for k, v in info.items() if k in ("wikidata", "website", "industries") and v})
                    if info.get("website") and not company.get("website"):
                        self.ctx.log("info", f"Website laut Wikidata: {info['website']}")
                else:
                    self.ctx.log("info", "Kein Wikidata-Eintrag gefunden")
            except HttpError as err:
                self.ctx.log("warn", f"Wikidata nicht erreichbar: {err}")
        return self.db.upsert_company(update)
