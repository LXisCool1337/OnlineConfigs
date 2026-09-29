"""Key figures from ESEF reports: inline XBRL facts -> yearly metrics and derived ratios.

ESEF reports tag every number of the primary statements with the IFRS taxonomy, and each
report also carries the prior year as comparatives. Six ESEF reports (FY2020-2025) therefore
give seven years of figures. As-reported values win; a later restatement is kept as a note.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date

IX = "{http://www.xbrl.org/2013/inlineXBRL}"
XBRLI = "{http://www.xbrl.org/2003/instance}"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"

# key, German label, period type, unit kind, IFRS concepts in order of preference
METRICS = [
    ("revenue", "Umsatz", "duration", "money", ["ifrs-full:Revenue", "ifrs-full:RevenueFromContractsWithCustomers"]),
    ("gross_profit", "Bruttoergebnis", "duration", "money", ["ifrs-full:GrossProfit"]),
    ("ebit", "EBIT (operatives Ergebnis)", "duration", "money", ["ifrs-full:ProfitLossFromOperatingActivities"]),
    ("ebt", "Ergebnis vor Steuern", "duration", "money", ["ifrs-full:ProfitLossBeforeTax"]),
    ("net_income", "Jahresergebnis", "duration", "money", ["ifrs-full:ProfitLoss"]),
    ("net_income_parent", "davon Aktionäre", "duration", "money", ["ifrs-full:ProfitLossAttributableToOwnersOfParent"]),
    ("eps", "Ergebnis je Aktie", "duration", "per_share",
     ["ifrs-full:BasicEarningsLossPerShare", "ifrs-full:BasicAndDilutedEarningsLossPerShare"]),
    ("d_and_a", "Abschreibungen", "duration", "money",
     ["ifrs-full:DepreciationAndAmortisationExpense",
      "ifrs-full:DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss"]),
    ("operating_cash_flow", "Operativer Cashflow", "duration", "money",
     ["ifrs-full:CashFlowsFromUsedInOperatingActivities"]),
    ("capex", "Investitionen Sachanlagen", "duration", "money",
     ["ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"]),
    ("capex_intangibles", "Investitionen immat. Vermögen", "duration", "money",
     ["ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"]),
    ("dividends_paid", "Gezahlte Dividenden", "duration", "money",
     ["ifrs-full:DividendsPaidClassifiedAsFinancingActivities",
      "ifrs-full:DividendsPaidToEquityHoldersOfParentClassifiedAsFinancingActivities"]),
    ("total_assets", "Bilanzsumme", "instant", "money", ["ifrs-full:Assets"]),
    ("equity", "Eigenkapital", "instant", "money", ["ifrs-full:Equity"]),
    ("equity_parent", "Eigenkapital der Aktionäre", "instant", "money",
     ["ifrs-full:EquityAttributableToOwnersOfParent"]),
    ("cash", "Zahlungsmittel", "instant", "money", ["ifrs-full:CashAndCashEquivalents"]),
    ("liabilities", "Schulden", "instant", "money", ["ifrs-full:Liabilities"]),
]
DERIVED = [
    ("revenue_growth", "Umsatzwachstum", "pct"),
    ("ebit_margin", "EBIT-Marge", "pct"),
    ("net_margin", "Nettomarge", "pct"),
    ("fcf", "Free Cashflow", "money"),
    ("fcf_margin", "FCF-Marge", "pct"),
    ("equity_ratio", "Eigenkapitalquote", "pct"),
    ("roe", "Eigenkapitalrendite", "pct"),
]
LABELS = {m[0]: m[1] for m in METRICS} | {d[0]: d[1] for d in DERIVED}
UNITS = {m[0]: m[3] for m in METRICS} | {d[0]: d[2] for d in DERIVED}
ORDER = ["revenue", "revenue_growth", "gross_profit", "ebit", "ebit_margin", "ebt", "net_income", "net_income_parent",
         "net_margin", "eps", "d_and_a", "operating_cash_flow", "capex", "capex_intangibles", "fcf", "fcf_margin",
         "dividends_paid", "total_assets", "equity", "equity_parent", "equity_ratio", "roe", "cash", "liabilities"]
CONCEPTS = {concept: (key, kind, rank) for key, _l, kind, _u, concepts in METRICS
            for rank, concept in enumerate(concepts)}


@dataclass
class Context:
    dimensional: bool
    start: str | None
    end: str
    instant: bool


def parse_number(text: str, fmt: str | None, scale: str | None, sign: str | None) -> float | None:
    """Apply the inline-XBRL transformation named in ``format`` (dot or comma decimals, zero dash)."""
    f = (fmt or "").rsplit(":", 1)[-1].lower()
    t = (text or "").replace(" ", " ").replace(" ", " ").strip()
    if "zero" in f or f in ("fixed-empty", "nocontent") or t in ("-", "–", "—"):
        value = 0.0
    else:
        if not t:
            return None
        if f:
            comma_decimal = f.endswith("comma") or "comma-decimal" in f or "commadecimal" in f
        else:
            comma_decimal = bool(re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?|\d+,\d{1,2}", t))
        t = re.sub(r"[\s'’]", "", t)
        t = t.replace(".", "").replace(",", ".") if comma_decimal else t.replace(",", "")
        t = re.sub(r"[^\d.]", "", t)
        if not t or t.count(".") > 1:
            return None
        value = float(t)
    try:
        value *= 10 ** int(scale or 0)
    except ValueError:
        return None
    return -value if sign == "-" else value


def parse_ixbrl(stream) -> tuple[list[tuple], dict[str, Context], dict[str, str]]:
    """Stream-parse one inline-XBRL XHTML file: numeric facts, contexts and units."""
    facts, contexts, units = [], {}, {}
    keep = 0  # inside ix:header or an ix:nonFraction: do not clear yet
    for event, el in ET.iterparse(stream, events=("start", "end")):
        tag = el.tag
        if event == "start":
            if tag in (IX + "header", IX + "nonFraction"):
                keep += 1
            continue
        if tag == IX + "nonFraction":
            keep -= 1
            name = el.get("name") or ""
            if name in CONCEPTS and el.get(XSI_NIL) != "true":
                value = parse_number("".join(el.itertext()), el.get("format"), el.get("scale"), el.get("sign"))
                if value is not None:
                    facts.append((name, el.get("contextRef"), el.get("unitRef"), value))
        elif tag == XBRLI + "context":
            period = el.find(XBRLI + "period")
            if period is not None and el.get("id"):
                instant = period.findtext(XBRLI + "instant")
                dimensional = el.find(f"{XBRLI}entity/{XBRLI}segment") is not None or \
                    el.find(XBRLI + "scenario") is not None
                contexts[el.get("id")] = Context(dimensional, period.findtext(XBRLI + "startDate"),
                                                 (instant or period.findtext(XBRLI + "endDate") or "").strip()[:10],
                                                 instant is not None)
        elif tag == XBRLI + "unit":
            numerator = [m.text.strip() for m in el.iter(XBRLI + "measure") if m.text]
            if el.get("id"):
                units[el.get("id")] = "/".join(numerator)
        elif tag == IX + "header":
            keep -= 1
        if keep == 0:
            el.clear()
    return facts, contexts, units


def _days(start: str | None, end: str) -> int:
    try:
        return (date.fromisoformat(end[:10]) - date.fromisoformat((start or "")[:10])).days
    except ValueError:
        return -1


def _currency(unit: str) -> str:
    parts = [p.split(":")[-1] for p in unit.split("/")]
    return parts[0].upper() if parts and parts[0] else ""


def values_from_report(streams) -> dict[tuple[str, int], dict]:
    """(metric, fiscal year) -> {value, currency, concept, period_end} for one ESEF report."""
    best: dict[tuple[str, int], tuple] = {}
    for stream in streams:
        facts, contexts, units = parse_ixbrl(stream)
        for concept, context_ref, unit_ref, value in facts:
            ctx = contexts.get(context_ref or "")
            if ctx is None or ctx.dimensional or not ctx.end:
                continue
            key, kind, rank = CONCEPTS[concept]
            if kind == "instant" and not ctx.instant:
                continue
            if kind == "duration" and (ctx.instant or not 300 <= _days(ctx.start, ctx.end) <= 380):
                continue
            year = int(ctx.end[:4])
            current = best.get((key, year))
            if current is None or rank < current[0]:
                best[(key, year)] = (rank, value, _currency(units.get(unit_ref or "", "")), concept, ctx.end)
    return {k: {"value": v[1], "currency": v[2], "concept": v[3], "period_end": v[4]} for k, v in best.items()}


def report_streams(path, kind: str):
    """File objects for the XHTML files of a report (a single XHTML or the files inside an ESEF ZIP)."""
    if kind == "zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))
                     and "/reports/" in f"/{n.lower()}"]
            return [io.BytesIO(zf.read(n)) for n in names]
    return [open(path, "rb")]


def derive(values: dict[int, dict[str, float]]) -> None:
    """Add ratios in place: growth, margins, free cash flow, equity ratio, return on equity."""
    for year, v in values.items():
        prev = values.get(year - 1, {})
        rev = v.get("revenue")
        if rev:
            if prev.get("revenue"):
                v["revenue_growth"] = v["revenue"] / prev["revenue"] - 1
            if v.get("ebit") is not None:
                v["ebit_margin"] = v["ebit"] / rev
            if v.get("net_income") is not None:
                v["net_margin"] = v["net_income"] / rev
        if v.get("operating_cash_flow") is not None and v.get("capex") is not None:
            v["fcf"] = v["operating_cash_flow"] - abs(v["capex"]) - abs(v.get("capex_intangibles") or 0)
            if rev:
                v["fcf_margin"] = v["fcf"] / rev
        if v.get("equity") and v.get("total_assets"):
            v["equity_ratio"] = v["equity"] / v["total_assets"]
        # Profit and equity from the same group of owners: attributable to shareholders if both are
        # tagged, otherwise group totals (incl. minorities); the mix is only the last resort.
        for income_key, equity_key in (("net_income_parent", "equity_parent"), ("net_income", "equity"),
                                       ("net_income_parent", "equity")):
            if v.get(income_key) is not None and v.get(equity_key):
                base = (v[equity_key] + prev[equity_key]) / 2 if prev.get(equity_key) else v[equity_key]
                if base > 0:
                    v["roe"] = v[income_key] / base
                break


def extract(ctx, lei: str) -> dict:
    """Read all ESEF reports of ``lei`` in the library and store yearly metrics in the catalogue."""
    docs = ctx.db.query(
        "SELECT * FROM documents WHERE lei = ? AND category IN ('esef_report', 'peer_report', 'esef_package', "
        "'peer_report_package') AND path IS NOT NULL ORDER BY fiscal_year DESC, "
        "CASE WHEN category LIKE '%package' THEN 1 ELSE 0 END", (lei,))
    per_report: list[tuple[int, dict, dict]] = []
    seen_years: set[int] = set()
    for doc in docs:
        if doc["fiscal_year"] in seen_years:
            continue  # report and package of the same year carry the same facts
        path = ctx.library.absolute(doc["path"])
        if not path.exists():
            continue
        streams = []
        try:
            streams = report_streams(path, "zip" if doc["mime"] == "zip" else "xhtml")
            values = values_from_report(streams)
        except (ET.ParseError, zipfile.BadZipFile, OSError, ValueError) as err:
            ctx.log("warn", f"Kennzahlen: {_file_name(doc)} nicht lesbar ({err})")
            continue
        finally:
            for s in streams:
                s.close()
        if values:
            seen_years.add(doc["fiscal_year"])
            per_report.append((doc["fiscal_year"], doc, values))

    merged: dict[tuple[str, int], dict] = {}
    for report_year, doc, values in per_report:  # newest report first
        for (metric, year), item in values.items():
            entry = {**item, "doc_id": doc["id"], "as_reported": year == report_year}
            current = merged.get((metric, year))
            if current is None:
                merged[(metric, year)] = entry
            elif entry["as_reported"] and not current["as_reported"]:
                if current["value"] and abs(current["value"] - entry["value"]) > abs(entry["value"]) * 0.001:
                    entry["restated"] = current["value"]
                merged[(metric, year)] = entry

    table: dict[int, dict[str, float]] = {}
    for (metric, year), item in merged.items():
        table.setdefault(year, {})[metric] = item["value"]
    derive(table)
    currency = next((i["currency"] for (m, _y), i in merged.items() if m == "revenue" and i["currency"]), "")
    rows = []
    for year, values in table.items():
        for metric, value in values.items():
            item = merged.get((metric, year), {})
            rows.append((lei, year, metric, value, item.get("currency") or (currency if UNITS[metric] == "money" else ""),
                         item.get("period_end"), item.get("concept"), item.get("doc_id"), item.get("restated")))
    ctx.db.replace_financials(lei, rows)
    years = sorted(table)
    if years:
        ctx.log("ok", f"Kennzahlen aus {len(per_report)} ESEF-Berichten: {len(years)} Geschäftsjahre "
                      f"({years[0]}–{years[-1]})", lei=lei)
    return {"reports": len(per_report), "years": years}


def _file_name(doc: dict) -> str:
    return (doc.get("path") or "").rsplit("/", 1)[-1]


def table_for(db, lei: str) -> dict:
    """Financials of one company shaped for the UI: years, metric rows, currency, restatement notes."""
    rows = db.query("SELECT * FROM financials WHERE lei = ? ORDER BY fiscal_year", (lei,))
    years = sorted({r["fiscal_year"] for r in rows})
    by_metric: dict[str, dict] = {}
    currency = ""
    notes = []
    for r in rows:
        by_metric.setdefault(r["metric"], {})[str(r["fiscal_year"])] = r["value"]
        if r["metric"] == "revenue" and r["unit"]:
            currency = r["unit"]
        if r["restated"] is not None:
            notes.append({"year": r["fiscal_year"], "metric": r["metric"], "label": LABELS.get(r["metric"]),
                          "reported": r["value"], "restated": r["restated"]})
    metrics = [{"key": k, "label": LABELS[k], "unit": UNITS[k], "values": by_metric[k]} for k in ORDER if k in by_metric]
    return {"lei": lei, "years": years, "currency": currency, "metrics": metrics, "restatements": notes}


def csv_for(db, lei: str, style: str = "de") -> str:
    """CSV of all metrics; 'de' = semicolon and decimal comma (opens directly in German Excel)."""
    data = table_for(db, lei)
    sep = ";" if style == "de" else ","
    lines = [sep.join(["metric", "label", "unit"] + [str(y) for y in data["years"]])]
    for m in data["metrics"]:
        unit = data["currency"] if m["unit"] == "money" else ("%" if m["unit"] == "pct" else
                                                              f"{data['currency']}/Aktie")
        cells = []
        for y in data["years"]:
            v = m["values"].get(str(y))
            if v is None:
                cells.append("")
                continue
            v = v * 100 if m["unit"] == "pct" else v
            text = f"{v:.4f}".rstrip("0").rstrip(".") if m["unit"] != "money" else f"{v:.0f}"
            cells.append(text.replace(".", ",") if style == "de" else text)
        label = m["label"].replace(sep, " ")
        lines.append(sep.join([m["key"], label, unit] + cells))
    return "\n".join(lines) + "\n"


COMPARE_KEYS = ["revenue", "revenue_growth", "ebit_margin", "net_margin", "fcf_margin", "equity_ratio", "roe"]


def comparison(db, nace: str, focus_lei: str | None = None) -> dict:
    """Latest-year key figures of the industry's peers (and the focus company) side by side."""
    leis = [r["lei"] for r in db.query("SELECT DISTINCT lei FROM documents WHERE scope = 'industry' AND nace = ? "
                                       "AND category LIKE 'peer_report%' AND lei IS NOT NULL", (nace,))]
    if focus_lei and focus_lei not in leis:
        leis.insert(0, focus_lei)
    rows = []
    for lei in leis:
        latest = db.one("SELECT MAX(fiscal_year) AS y FROM financials WHERE lei = ? AND metric = 'revenue'", (lei,))
        company = db.company(lei) or {"name": lei}
        row = {"lei": lei, "name": company.get("name"), "country": company.get("country"),
               "focus": lei == focus_lei, "fiscal_year": latest["y"] if latest else None, "currency": ""}
        if row["fiscal_year"]:
            for r in db.query("SELECT metric, value, unit FROM financials WHERE lei = ? AND fiscal_year = ?",
                              (lei, row["fiscal_year"])):
                if r["metric"] in COMPARE_KEYS:
                    row[r["metric"]] = r["value"]
                if r["metric"] == "revenue":
                    row["currency"] = r["unit"]
        rows.append(row)
    median = {}
    for key in COMPARE_KEYS[1:]:
        values = sorted(r[key] for r in rows if r.get(key) is not None)
        if values:
            mid = len(values) // 2
            median[key] = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    return {"nace": nace, "rows": rows, "median": median,
            "metrics": [{"key": k, "label": LABELS[k], "unit": UNITS[k]} for k in COMPARE_KEYS]}
