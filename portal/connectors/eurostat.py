"""Official industry statistics from Eurostat (JSON-stat API), filtered by NACE code and country.

Dataset codes live in portal/data/eurostat_datasets.json so they can be changed without code
changes (Eurostat renames datasets from time to time, e.g. for the NACE Rev. 2.1 switch).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ..identifiers import EUROSTAT_GEO, eurostat_nace, nace_section
from ..net import ContentError, HttpError


def load_datasets(path: str) -> list[dict]:
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def jsonstat_rows(js: dict) -> tuple[list[str], list[dict]]:
    """Flatten a JSON-stat 2.0 dataset into rows (one per observation) with codes and labels."""
    ids, sizes, dims = js["id"], js["size"], js["dimension"]
    categories = []
    for dim in ids:
        cat = dims[dim].get("category") or {}
        index = cat.get("index")
        if isinstance(index, list):
            codes = list(index)
        elif isinstance(index, dict):
            codes = [None] * len(index)
            for code, pos in index.items():
                codes[pos] = code
        else:
            codes = list((cat.get("label") or {}).keys())
        categories.append((codes, cat.get("label") or {}))
    values = js.get("value") or {}
    items = values.items() if isinstance(values, dict) else enumerate(values)
    status = js.get("status") or {}
    rows = []
    for flat, value in items:
        if value is None:
            continue
        flat = int(flat)
        coords, rest = [], flat
        for size in reversed(sizes):
            coords.append(rest % size)
            rest //= size
        coords.reverse()
        row = {}
        for i, dim in enumerate(ids):
            codes, labels = categories[i]
            code = codes[coords[i]]
            row[dim] = code
            if dim not in ("time", "freq"):
                row[f"{dim}_label"] = labels.get(code, code)
        row["value"] = value
        flag = status.get(str(flat)) if isinstance(status, dict) else (status[flat] if flat < len(status) else None)
        row["flag"] = flag or ""
        rows.append(row)
    header = []
    for dim in ids:
        header.append(dim)
        if dim not in ("time", "freq"):
            header.append(f"{dim}_label")
    header += ["value", "flag"]
    rows.sort(key=lambda r: tuple(str(r.get(d)) for d in ids))
    return header, rows


def to_csv(header: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


class Eurostat:
    def __init__(self, ctx):
        self.ctx = ctx
        self.base = ctx.settings.eurostat_api.rstrip("/")

    def datasets_for(self, nace: str) -> list[dict]:
        section = nace_section(nace)
        return [d for d in load_datasets(self.ctx.settings.eurostat_datasets_file)
                if not d.get("sections") or section in d["sections"]]

    def request_url(self, spec: dict, nace: str, countries: list[str], since: int) -> tuple[str, list]:
        geos = ["EU27_2020"] + [EUROSTAT_GEO.get(c, c) for c in countries if c]
        params: list[tuple[str, str]] = [("format", "JSON"), ("lang", "EN"),
                                         (spec.get("nace_dim", "nace_r2"), eurostat_nace(nace))]
        params += [("geo", g) for g in dict.fromkeys(geos)]
        params.append(("sinceTimePeriod", str(since)))
        for key, value in (spec.get("params") or {}).items():
            for v in value if isinstance(value, list) else [value]:
                params.append((key, str(v)))
        return f"{self.base}/data/{spec['code']}", params

    def fetch(self, spec: dict, nace: str, countries: list[str], since: int) -> dict | None:
        """Returns {'url', 'label', 'raw', 'csv', 'rows'} or None if the dataset is unavailable."""
        url, params = self.request_url(spec, nace, countries, since)
        try:
            resp = self.ctx.http.get(url, params=params, accept="application/json", max_bytes=60_000_000,
                                     timeout=120)
            js = resp.json()
        except HttpError as err:
            self.ctx.log("warn", f"Eurostat {spec['code']}: nicht verfügbar (HTTP {err.status or 'Netzwerk'})",
                         url=err.url)
            return None
        except (ContentError, ValueError) as err:
            self.ctx.log("warn", f"Eurostat {spec['code']}: unlesbare Antwort ({err})")
            return None
        if "error" in js or "id" not in js:
            self.ctx.log("warn", f"Eurostat {spec['code']}: {js.get('error') or 'unerwartetes Format'}")
            return None
        header, rows = jsonstat_rows(js)
        if not rows:
            self.ctx.log("info", f"Eurostat {spec['code']}: keine Werte für NACE {nace}")
            return None
        return {"url": resp.url, "label": js.get("label") or spec.get("label_de") or spec["code"],
                "updated": js.get("updated"), "raw": resp.body, "csv": to_csv(header, rows), "rows": len(rows)}
