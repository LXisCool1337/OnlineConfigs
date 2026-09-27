"""ESMA FIRDS reference data: every share admitted to trading on an EU trading venue.

The weekly FULINS_E files (ISO 20022 auth.017 XML, zipped) list each equity instrument per trading
venue with ISIN, issuer LEI, CFI code and whether the issuer requested the admission. Filtering to
shares (CFI ES*/EP*) with an EU/EEA ISIN gives the universe of "all EU stocks".
"""

from __future__ import annotations

import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from pathlib import Path

from ..identifiers import EU_EEA, is_isin, is_lei
from ..net import HttpError

FULINS_E = re.compile(r"FULINS_E_(\d{8})_\d+of\d+\.zip$", re.I)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(elem, *path: str) -> str | None:
    node = elem
    for name in path:
        node = next((c for c in node if _local(c.tag) == name), None)
        if node is None:
            return None
    return (node.text or "").strip() or None


def parse_fulins(stream, countries: frozenset[str], cfi_prefixes: tuple[str, ...]) -> dict[str, dict]:
    """Stream-parse one FULINS XML file; returns ISIN -> aggregated security record."""
    out: dict[str, dict] = {}
    stack = []
    for event, elem in ET.iterparse(stream, events=("start", "end")):
        if event == "start":
            stack.append(elem)
            continue
        stack.pop()
        if _local(elem.tag) != "RefData":
            continue
        isin = _child_text(elem, "FinInstrmGnlAttrbts", "Id")
        cfi = _child_text(elem, "FinInstrmGnlAttrbts", "ClssfctnTp") or ""
        if isin and is_isin(isin) and isin[:2] in countries and cfi.startswith(cfi_prefixes):
            lei = _child_text(elem, "Issr")
            venue = next((c for c in elem if _local(c.tag) == "TradgVnRltdAttrbts"), None)
            mic = _child_text(venue, "Id") if venue is not None else None
            issuer_req = (_child_text(venue, "IssrReq") or "").lower() == "true" if venue is not None else False
            first = _child_text(venue, "FrstTradDt") if venue is not None else None
            term = _child_text(venue, "TermntnDt") if venue is not None else None
            rec = out.get(isin)
            if rec is None:
                rec = out[isin] = {
                    "isin": isin, "lei": lei if lei and is_lei(lei) else None,
                    "name": _child_text(elem, "FinInstrmGnlAttrbts", "FullNm"), "cfi": cfi,
                    "currency": _child_text(elem, "FinInstrmGnlAttrbts", "NtnlCcy"), "mic": mic,
                    "issuer_requested": 1 if issuer_req else 0, "first_trade": first, "termination": term,
                    "authority": _child_text(elem, "TechAttrbts", "RlvntCmptntAuthrty"), "source": "firds",
                    "_active": not term,
                }
            else:
                if issuer_req and not rec["issuer_requested"]:
                    rec["issuer_requested"], rec["mic"] = 1, mic
                if first and (not rec["first_trade"] or first < rec["first_trade"]):
                    rec["first_trade"] = first
                if not term:
                    rec["_active"] = True
                elif rec["termination"] and term > rec["termination"]:
                    rec["termination"] = term
        elem.clear()
        if stack:
            try:
                stack[-1].remove(elem)
            except ValueError:
                pass
    for rec in out.values():
        if rec.pop("_active"):
            rec["termination"] = None
    return out


def issuer_name(instrument_name: str | None) -> str:
    """'KRONES AG O.N.' -> 'KRONES AG' (FIRDS names describe the instrument, not the issuer)."""
    name = (instrument_name or "").strip()
    name = re.sub(r"\s+(O\.N\.|(?:NA|VNA|INH|INHABER|VZO|ST|STAMM)\b.*|NAMENS[- ]?AKTIEN.*|ORD(?:INARY)?\b.*|"
                  r"REGISTERED.*|BEARER.*|SHS\b.*|ACTIONS?\b.*|AZ\.?\s*ORD.*|EO\s*[\d,.-]+.*|DL\s*[\d,.-]+.*)$",
                  "", name, flags=re.I)
    return name.strip(" ,.-/") or (instrument_name or "")


class Firds:
    def __init__(self, ctx):
        self.ctx = ctx

    def latest_files(self, lookback_days: int = 21) -> list[str]:
        today = date.today()
        since = (today - timedelta(days=lookback_days)).isoformat()
        params = {"q": "*", "fq": f"publication_date:[{since}T00:00:00Z TO {today.isoformat()}T23:59:59Z]",
                  "wt": "json", "start": 0, "rows": 500}
        payload = self.ctx.http.get_json(self.ctx.settings.esma_firds_api, params=params)
        docs = (payload.get("response") or {}).get("docs") or []
        by_date: dict[str, list[str]] = {}
        for doc in docs:
            link = doc.get("download_link") or ""
            m = FULINS_E.search(doc.get("file_name") or link)
            if m and link:
                by_date.setdefault(m.group(1), []).append(link)
        if not by_date:
            return []
        return sorted(by_date[max(by_date)])

    def securities(self, countries: frozenset[str] | None = None, cfi_prefixes: tuple[str, ...] = ("ES", "EP")) -> dict:
        countries = countries or EU_EEA
        files = self.latest_files()
        if not files:
            raise HttpError(self.ctx.settings.esma_firds_api, 0, "keine aktuellen FULINS_E-Dateien gefunden")
        merged: dict[str, dict] = {}
        with tempfile.TemporaryDirectory() as tmp:
            for i, link in enumerate(files, 1):
                self.ctx.check_cancel()
                self.ctx.log("info", f"FIRDS-Datei {i}/{len(files)} laden", url=link)
                target = Path(tmp) / f"part{i}.zip"
                self.ctx.http.download(link, target, expect=("zip",), check_robots=False, max_bytes=2_000_000_000)
                with zipfile.ZipFile(target) as zf:
                    for member in zf.namelist():
                        if member.lower().endswith(".xml"):
                            with zf.open(member) as stream:
                                for isin, rec in parse_fulins(stream, countries, cfi_prefixes).items():
                                    merged.setdefault(isin, rec)
                target.unlink()
        return merged
