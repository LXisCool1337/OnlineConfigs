"""Wikidata SPARQL: official website and industry of an issuer, and listed peers in the same industry.

Only identifiers that passed ISIN/LEI/QID validation are ever placed into a query string.
"""

from __future__ import annotations

import re

from ..identifiers import EU_EEA, is_isin, is_lei

ENTITY = "http://www.wikidata.org/entity/"
QID_RE = re.compile(r"^Q\d+$")


def _value(binding: dict, key: str) -> str | None:
    return (binding.get(key) or {}).get("value")


def _qid(uri: str | None) -> str | None:
    if uri and uri.startswith(ENTITY):
        return uri[len(ENTITY):]
    return None


class Wikidata:
    def __init__(self, ctx):
        self.ctx = ctx
        self.endpoint = ctx.settings.wikidata_sparql

    def _query(self, sparql: str) -> list[dict]:
        payload = self.ctx.http.get_json(self.endpoint, params={"query": sparql, "format": "json"},
                                         headers={"Accept": "application/sparql-results+json"}, timeout=70)
        return (payload.get("results") or {}).get("bindings") or []

    def company(self, lei: str, isins: list[str]) -> dict | None:
        """Website, industries and QID for an issuer found by LEI (P1278) or ISIN (P946)."""
        clauses = []
        if is_lei(lei):
            clauses.append(f'{{ ?item wdt:P1278 "{lei}" . }}')
        good_isins = [i for i in isins if is_isin(i)][:20]
        if good_isins:
            values = " ".join(f'"{i}"' for i in good_isins)
            clauses.append(f"{{ VALUES ?isinv {{ {values} }} ?item wdt:P946 ?isinv . }}")
        if not clauses:
            return None
        sparql = f"""
SELECT ?item ?itemLabel ?website ?industry ?industryLabel WHERE {{
  {" UNION ".join(clauses)}
  OPTIONAL {{ ?item wdt:P856 ?website . }}
  OPTIONAL {{ ?item wdt:P452 ?industry . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "de,en". }}
}} LIMIT 60"""
        rows = self._query(sparql)
        if not rows:
            return None
        qid = _qid(_value(rows[0], "item"))
        websites = sorted({_value(r, "website") for r in rows if _value(r, "website") and _qid(_value(r, "item")) == qid},
                          key=lambda w: (not w.startswith("https"), len(w)))
        industries = {}
        for r in rows:
            ind = _qid(_value(r, "industry"))
            if ind and _qid(_value(r, "item")) == qid:
                industries[ind] = _value(r, "industryLabel") or ind
        return {
            "wikidata": qid,
            "label": _value(rows[0], "itemLabel"),
            "website": websites[0] if websites else None,
            "industries": [{"qid": k, "label": v} for k, v in industries.items()],
        }

    def peers(self, industry_qids: list[str], exclude_lei: str | None = None, limit: int = 200) -> list[dict]:
        """Listed companies (with LEI and ISIN) sharing one of the industries, restricted to the EU/EEA."""
        qids = [q for q in industry_qids if QID_RE.match(q)][:10]
        if not qids:
            return []
        values = " ".join(f"wd:{q}" for q in qids)
        sparql = f"""
SELECT DISTINCT ?item ?itemLabel ?lei ?isin ?cc WHERE {{
  VALUES ?ind {{ {values} }}
  ?item wdt:P452 ?ind ; wdt:P1278 ?lei ; wdt:P946 ?isin .
  OPTIONAL {{ ?item wdt:P17 ?country . ?country wdt:P297 ?cc . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "de,en". }}
}} LIMIT {int(limit)}"""
        out: dict[str, dict] = {}
        for r in self._query(sparql):
            lei = (_value(r, "lei") or "").upper()
            isin = (_value(r, "isin") or "").upper()
            country = (_value(r, "cc") or isin[:2]).upper()
            if not is_lei(lei) or lei == exclude_lei or country not in EU_EEA:
                continue
            entry = out.setdefault(lei, {"lei": lei, "name": _value(r, "itemLabel") or lei, "country": country,
                                         "isins": [], "wikidata": _qid(_value(r, "item"))})
            if is_isin(isin) and isin not in entry["isins"]:
                entry["isins"].append(isin)
        return list(out.values())
