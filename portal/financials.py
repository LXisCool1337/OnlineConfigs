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
    # Balance sheet structure and the inputs of the value metrics
    ("noncurrent_assets", "Langfristige Vermögenswerte", "instant", "money", ["ifrs-full:NoncurrentAssets"]),
    ("current_assets", "Kurzfristige Vermögenswerte", "instant", "money", ["ifrs-full:CurrentAssets"]),
    ("noncurrent_liabilities", "Langfristige Schulden", "instant", "money", ["ifrs-full:NoncurrentLiabilities"]),
    ("current_liabilities", "Kurzfristige Schulden", "instant", "money", ["ifrs-full:CurrentLiabilities"]),
    ("pensions", "Pensionsrückstellungen", "instant", "money", ["ifrs-full:NoncurrentProvisionsForEmployeeBenefits"]),
    ("debt_noncurrent", "Finanzschulden langfristig", "instant", "money",
     ["ifrs-full:NoncurrentPortionOfNoncurrentBorrowings", "ifrs-full:LongtermBorrowings",
      "ifrs-full:NoncurrentFinancialLiabilities"]),
    ("debt_current", "Finanzschulden kurzfristig", "instant", "money",
     ["ifrs-full:CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings", "ifrs-full:ShorttermBorrowings",
      "ifrs-full:CurrentFinancialLiabilities"]),
    ("income_tax", "Ertragsteuern", "duration", "money", ["ifrs-full:IncomeTaxExpenseContinuingOperations"]),
    ("interest_expense", "Finanzaufwand", "duration", "money", ["ifrs-full:FinanceCosts"]),
]
DERIVED = [
    ("revenue_growth", "Umsatzwachstum", "pct"),
    ("ebit_margin", "EBIT-Marge", "pct"),
    ("net_margin", "Nettomarge", "pct"),
    ("fcf", "Free Cashflow", "money"),
    ("fcf_margin", "FCF-Marge", "pct"),
    ("owner_earnings", "Owner Earnings", "money"),
    ("equity_ratio", "Eigenkapitalquote", "pct"),
    ("roe", "Eigenkapitalrendite", "pct"),
    ("roic", "Rendite auf das investierte Kapital", "pct"),
    ("financial_debt", "Finanzschulden", "money"),
    ("net_cash", "Netto-Liquidität", "money"),
    ("debt_payback", "Schuldentilgung aus Gewinn", "years"),
    ("interest_coverage", "Zinsdeckung", "times"),
    ("capex_ratio", "Investitionen in % des Gewinns", "pct"),
]
LABELS = {m[0]: m[1] for m in METRICS} | {d[0]: d[1] for d in DERIVED}
UNITS = {m[0]: m[3] for m in METRICS} | {d[0]: d[2] for d in DERIVED}
ORDER = ["revenue", "revenue_growth", "gross_profit", "ebit", "ebit_margin", "ebt", "income_tax", "net_income",
         "net_income_parent", "net_margin", "eps", "d_and_a", "interest_expense", "interest_coverage",
         "operating_cash_flow", "capex", "capex_intangibles", "capex_ratio", "fcf", "fcf_margin", "owner_earnings",
         "dividends_paid", "total_assets", "noncurrent_assets", "current_assets", "cash", "equity", "equity_parent",
         "equity_ratio", "roe", "roic", "liabilities", "noncurrent_liabilities", "current_liabilities", "pensions",
         "debt_noncurrent", "debt_current", "financial_debt", "net_cash", "debt_payback"]
UNIT_LABELS = {"pct": "%", "years": "Jahre", "times": "x"}
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


def _invested_capital(v: dict) -> float | None:
    """Equity plus financial debt minus cash: the capital the operating business works with."""
    if v.get("equity") is None or v.get("cash") is None or (v.get("debt_noncurrent") is None
                                                           and v.get("debt_current") is None):
        return None
    return v["equity"] + abs(v.get("debt_noncurrent") or 0) + abs(v.get("debt_current") or 0) - v["cash"]


def derive(values: dict[int, dict[str, float]]) -> None:
    """Add ratios in place: growth, margins, free cash flow, owner earnings, returns and debt measures."""
    for year in sorted(values):
        v = values[year]
        prev = values.get(year - 1, {})
        capex = None
        if v.get("capex") is not None or v.get("capex_intangibles") is not None:
            capex = abs(v.get("capex") or 0) + abs(v.get("capex_intangibles") or 0)
        income = v.get("net_income")
        # Owner earnings (Buffett, letter 1986): earnings + depreciation/amortisation - capital expenditure.
        # Reports do not split maintenance from growth capex, so all of it counts (the conservative reading).
        if income is not None and v.get("d_and_a") is not None and capex is not None:
            v["owner_earnings"] = income + abs(v["d_and_a"]) - capex
        if capex is not None and income and income > 0:
            v["capex_ratio"] = capex / income
        if v.get("debt_noncurrent") is not None or v.get("debt_current") is not None:
            v["financial_debt"] = abs(v.get("debt_noncurrent") or 0) + abs(v.get("debt_current") or 0)
            if v.get("cash") is not None:
                v["net_cash"] = v["cash"] - v["financial_debt"]
            if income and income > 0:
                v["debt_payback"] = v["financial_debt"] / income
        if v.get("ebit") is not None and v.get("interest_expense"):
            v["interest_coverage"] = v["ebit"] / abs(v["interest_expense"])
        # ROIC: operating profit after tax on the invested capital (averaged with the prior year when known)
        invested = _invested_capital(v)
        if v.get("ebit") is not None and invested is not None and v.get("income_tax") is not None \
                and (v.get("ebt") or 0) > 0:
            rate = min(max(abs(v["income_tax"]) / v["ebt"], 0.0), 0.6)
            before = _invested_capital(prev)
            base = (invested + before) / 2 if before is not None else invested
            if base > 0:
                v["roic"] = v["ebit"] * (1 - rate) / base
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

    # Figures taken from PDF reports (import_manual) fill what ESEF does not cover; ESEF always wins.
    manual = 0
    for row in ctx.db.manual_financials(lei):
        key = (row["metric"], row["fiscal_year"])
        if key not in merged:
            merged[key] = {"value": row["value"], "currency": row["unit"] or "", "concept": row["source"],
                           "period_end": None, "doc_id": row["doc_id"], "as_reported": True}
            manual += 1

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
        extra = f" und {manual} Werten aus PDF-Berichten" if manual else ""
        ctx.log("ok", f"Kennzahlen aus {len(per_report)} ESEF-Berichten{extra}: {len(years)} Geschäftsjahre "
                      f"({years[0]}–{years[-1]})", lei=lei)
    return {"reports": len(per_report), "manual": manual, "years": years}


def import_manual(db, lei: str, rows: list[dict], *, currency: str = "EUR", millions: bool = False) -> int:
    """Store figures read from PDF reports: {metric, fiscal_year, value, report_year?, page?} per row.

    Only reported line items (METRICS) are accepted; ratios are always derived. With ``millions`` the
    money values are given in millions. ``report_year`` links the value to that year's annual report
    in the library, ``page`` is the page it was read from."""
    base = {m[0] for m in METRICS}
    cleaned = []
    for i, row in enumerate(rows, 1):
        metric = str(row.get("metric") or "").strip()
        if metric not in base:
            raise ValueError(f"Zeile {i}: unbekannte Kennzahl „{metric}“ (erlaubt: {', '.join(sorted(base))})")
        try:
            year = int(row["fiscal_year"])
            value = float(str(row["value"]).replace(" ", "").replace(",", ".")) if isinstance(row["value"], str) \
                else float(row["value"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Zeile {i}: Geschäftsjahr und Wert müssen Zahlen sein") from None
        if not 1990 <= year <= 2100 or value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"Zeile {i}: ungültiges Jahr oder ungültiger Wert")
        if millions and UNITS[metric] == "money":
            value *= 1_000_000
        page = str(row.get("page") or "").strip()[:20]
        doc = None
        if row.get("report_year"):
            doc = db.one("SELECT id FROM documents WHERE lei = ? AND scope = 'company' AND category IN "
                         "('annual_report', 'single_entity_statements') AND fiscal_year = ? ORDER BY id LIMIT 1",
                         (lei, int(row["report_year"])))
        unit = currency.upper() if UNITS[metric] in ("money", "per_share") else ""
        cleaned.append((lei, year, metric, value, unit, f"pdf:{page}" if page else "manuell",
                        doc["id"] if doc else None, page or None))
    db.replace_manual_financials(lei, cleaned)
    return len(cleaned)


def source_label(concept: str | None) -> str:
    if not concept:
        return "berechnet"
    if concept.startswith("pdf:"):
        return f"PDF S. {concept[4:]}"
    if concept == "manuell":
        return "manuell"
    return "ESEF"


def _file_name(doc: dict) -> str:
    return (doc.get("path") or "").rsplit("/", 1)[-1]


def table_for(db, lei: str) -> dict:
    """Financials of one company shaped for the UI: years, metric rows, currency, restatement notes."""
    rows = db.query("SELECT * FROM financials WHERE lei = ? ORDER BY fiscal_year", (lei,))
    years = sorted({r["fiscal_year"] for r in rows})
    by_metric: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    origin: dict[str, set] = {"ESEF": set(), "PDF": set()}
    currency = ""
    notes = []
    for r in rows:
        by_metric.setdefault(r["metric"], {})[str(r["fiscal_year"])] = r["value"]
        label = source_label(r["concept"])
        sources.setdefault(r["metric"], {})[str(r["fiscal_year"])] = label
        if label != "berechnet":
            origin["ESEF" if label == "ESEF" else "PDF"].add(r["fiscal_year"])
        if r["metric"] == "revenue" and r["unit"]:
            currency = r["unit"]
        if r["restated"] is not None:
            notes.append({"year": r["fiscal_year"], "metric": r["metric"], "label": LABELS.get(r["metric"]),
                          "reported": r["value"], "restated": r["restated"]})
    metrics = [{"key": k, "label": LABELS[k], "unit": UNITS[k], "values": by_metric[k], "sources": sources[k]}
               for k in ORDER if k in by_metric]
    return {"lei": lei, "years": years, "currency": currency, "metrics": metrics, "restatements": notes,
            "origin": {k: sorted(v) for k, v in origin.items()}}


def csv_for(db, lei: str, style: str = "de") -> str:
    """CSV of all metrics; 'de' = semicolon and decimal comma (opens directly in German Excel)."""
    data = table_for(db, lei)
    sep = ";" if style == "de" else ","
    lines = [sep.join(["metric", "label", "unit"] + [str(y) for y in data["years"]])]
    for m in data["metrics"]:
        unit = data["currency"] if m["unit"] == "money" else UNIT_LABELS.get(m["unit"], f"{data['currency']}/Aktie")
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


# --- balance sheet and value view (Buffett's rules of thumb) ---------------------------------

CHECK_YEARS = 5  # the checks judge the latest five fiscal years

# Each check: key, chart metric, title, rule text, reference line for the chart (None = no line).
VALUE_CHECKS = [
    ("roe", "roe", "Eigenkapitalrendite über 15 %",
     "Buffett sucht Unternehmen, die über Jahre mehr als 15 % auf das Eigenkapital verdienen, und zwar ohne "
     "hohe Schulden.", 0.15),
    ("roic", "roic", "Rendite auf das investierte Kapital über 15 %",
     "EBIT nach Steuern geteilt durch Eigenkapital plus Finanzschulden minus Zahlungsmittel. Hohe Werte "
     "unabhängig von der Finanzierung deuten auf einen Burggraben hin.", 0.15),
    ("margin", "ebit_margin", "Stabile operative Marge",
     "Ein dauerhafter Wettbewerbsvorteil zeigt sich in Margen, die kaum schwanken und nie negativ werden.", None),
    ("owner_earnings", "owner_earnings", "Owner Earnings in jedem Jahr positiv",
     "Jahresergebnis plus Abschreibungen minus Investitionen (Buffett 1986): das Geld, das den Eigentümern "
     "wirklich zufließt.", None),
    ("debt", "net_cash", "Wenig Schulden: höchstens 3 Jahresgewinne",
     "Wenig Schulden: Die Finanzschulden sollten aus drei bis vier Jahresgewinnen zurückgezahlt werden können. "
     "Das Diagramm zeigt Zahlungsmittel minus Finanzschulden.", None),
    ("capex", "capex_ratio", "Investitionen unter 50 % des Gewinns",
     "Ein Geschäft, das wenig Kapital für den Erhalt braucht, kann mehr ausschütten oder zu hohen Renditen "
     "reinvestieren.", 0.5),
    ("eps", "eps", "Gewinn je Aktie steigt beständig",
     "Ein wachsender Gewinn je Aktie über viele Jahre ist das Ergebnis eines guten Geschäfts mit fähigem "
     "Management.", None),
]
STATUS_LABELS = {"good": "erfüllt", "warn": "teilweise", "bad": "nicht erfüllt", "na": "keine Daten"}


def _pct(v: float) -> str:
    return f"{v * 100:.1f} %".replace(".", ",")


def _mio(v: float) -> str:
    return f"{v / 1e6:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + " Mio."


def _check(key: str, series: dict[str, list[tuple[int, float]]], latest: dict) -> tuple[str, str]:
    """(status, summary) of one Buffett check over the latest CHECK_YEARS years."""
    if key in ("roe", "roic"):
        vals = [v for _y, v in series[key]]
        if not vals:
            return "na", ""
        avg = sum(vals) / len(vals)
        status = "good" if avg >= 0.15 and min(vals) >= 0.10 else "warn" if avg >= 0.10 else "bad"
        return status, f"Ø {_pct(avg)}, niedrigster Wert {_pct(min(vals))}"
    if key == "margin":
        vals = [v for _y, v in series["ebit_margin"]]
        if len(vals) < 2:
            return "na", ""
        spread = max(vals) - min(vals)
        status = "bad" if min(vals) <= 0 else "good" if spread <= 0.05 else "warn"
        return status, f"{_pct(min(vals))} bis {_pct(max(vals))} (Spanne {spread * 100:.1f} Prozentpunkte)".replace(".", ",")
    if key == "owner_earnings":
        pairs = series["owner_earnings"]
        if not pairs:
            return "na", ""
        positive = sum(1 for _y, v in pairs if v > 0)
        income = sum(v for y, v in series["net_income"] if y in {p[0] for p in pairs})
        total = sum(v for _y, v in pairs)
        status = "good" if positive == len(pairs) else "warn" if total > 0 else "bad"
        share = f", {total / income * 100:.0f} % des Jahresergebnisses" if income > 0 else ""
        return status, f"{positive} von {len(pairs)} Jahren positiv, zusammen {_mio(total)}{share}"
    if key == "debt":
        if latest.get("financial_debt") is None:
            return "na", ""
        pension = f"; zusätzlich Pensionsrückstellungen {_mio(latest['pensions'])}" if latest.get("pensions") else ""
        if (latest.get("net_cash") or 0) > 0:
            return "good", f"mehr Zahlungsmittel als Finanzschulden ({_mio(latest['net_cash'])} netto){pension}"
        years = latest.get("debt_payback")
        if years is None:
            return "bad", "kein Gewinn, aus dem Schulden getilgt werden könnten" + pension
        status = "good" if years <= 3 else "warn" if years <= 5 else "bad"
        return status, f"Finanzschulden = {years:.1f} Jahresgewinne".replace(".", ",") + pension
    if key == "capex":
        vals = [v for _y, v in series["capex_ratio"]]
        if not vals:
            return "na", ""
        avg = sum(vals) / len(vals)
        status = "good" if avg <= 0.5 else "warn" if avg <= 1.0 else "bad"
        return status, f"Ø {_pct(avg)} des Jahresergebnisses"
    if key == "eps":
        pairs = series["eps"]
        if len(pairs) < 3:
            return "na", ""
        ups = sum(1 for (_a, x), (_b, y) in zip(pairs, pairs[1:]) if y > x)
        first, last = pairs[0], pairs[-1]
        span = last[0] - first[0]
        growth = ""
        if first[1] > 0 and last[1] > 0 and span > 0:
            growth = f", {((last[1] / first[1]) ** (1 / span) - 1) * 100:.1f} % pro Jahr".replace(".", ",")
        status = "good" if last[1] > first[1] and ups >= 0.7 * (len(pairs) - 1) else \
            "warn" if last[1] > first[1] else "bad"
        return status, f"{ups} von {len(pairs) - 1} Jahren gestiegen{growth}"
    return "na", ""


def _balance(values: dict[str, float]) -> dict | None:
    """Assets by how long they are tied up, capital by how long it stays: the golden balance sheet rule."""
    total = values.get("total_assets")
    if not total or values.get("equity") is None:
        return None
    cash = values.get("cash") or 0.0
    noncurrent = values.get("noncurrent_assets")
    if noncurrent is None and values.get("current_assets") is not None:
        noncurrent = total - values["current_assets"]
    if noncurrent is not None:
        assets = [("noncurrent_assets", "Langfristiges Vermögen", noncurrent),
                  ("current_other", "Vorräte, Forderungen, Sonstiges", total - noncurrent - cash),
                  ("cash", "Zahlungsmittel", cash)]
    else:
        assets = [("other_assets", "Übrige Vermögenswerte", total - cash), ("cash", "Zahlungsmittel", cash)]
    equity = values["equity"]
    long_debt, short_debt = values.get("noncurrent_liabilities"), values.get("current_liabilities")
    if long_debt is None and short_debt is not None:
        long_debt = total - equity - short_debt
    if short_debt is None and long_debt is not None:
        short_debt = total - equity - long_debt
    if long_debt is not None:
        capital = [("equity", "Eigenkapital", equity), ("noncurrent_liabilities", "Langfristige Schulden", long_debt),
                   ("current_liabilities", "Kurzfristige Schulden", short_debt)]
    else:
        capital = [("equity", "Eigenkapital", equity), ("liabilities", "Schulden", total - equity)]
    out = {"total": total, "assets": [{"key": k, "label": l, "value": v} for k, l, v in assets],
           "capital": [{"key": k, "label": l, "value": v} for k, l, v in capital]}
    if noncurrent and long_debt is not None:
        out["coverage"] = (equity + long_debt) / noncurrent  # > 1: long-term assets fully financed long-term
    return out


def value_view(db, lei: str) -> dict:
    """Everything the 'Bilanz & Value' page shows for one company, computed from the stored key figures."""
    data = table_for(db, lei)
    company = db.company(lei) or {"lei": lei, "name": lei}
    by = {m["key"]: {int(y): v for y, v in m["values"].items()} for m in data["metrics"]}
    years = data["years"]
    recent = years[-CHECK_YEARS:]
    series = {key: [(y, by[key][y]) for y in recent if y in by.get(key, {})]
              for key in ("roe", "roic", "ebit_margin", "owner_earnings", "net_income", "capex_ratio", "eps")}
    with_assets = [y for y in years if by.get("total_assets", {}).get(y)]
    year = with_assets[-1] if with_assets else (years[-1] if years else None)
    latest = {k: v[year] for k, v in by.items() if year in v} if year else {}
    before = {k: v[year - 1] for k, v in by.items() if year and year - 1 in v}

    checks = []
    for key, metric, title, rule, threshold in VALUE_CHECKS:
        status, summary = _check(key, series, latest)
        checks.append({"key": key, "metric": metric, "title": title, "rule": rule, "threshold": threshold,
                       "status": status, "status_label": STATUS_LABELS[status], "summary": summary})

    kpis = []
    for key in ("revenue", "net_income", "owner_earnings", "equity_ratio", "net_cash", "roe"):
        if key in latest:
            kpis.append({"key": key, "label": LABELS[key], "unit": UNITS[key], "value": latest[key],
                         "previous": before.get(key)})

    counts = {r["doc_id"]: r["n"] for r in db.query(
        "SELECT doc_id, COUNT(*) AS n FROM financials WHERE lei = ? AND doc_id IS NOT NULL GROUP BY doc_id", (lei,))}
    documents = [{"id": d["id"], "fiscal_year": d["fiscal_year"], "fy_label": d["fy_label"], "category": d["category"],
                  "title": d["title"], "language": d["language"], "size": d["size"], "mime": d["mime"],
                  "source": d["source"], "figures": counts.get(d["id"], 0)}
                 for d in db.company_documents(lei)]
    return {"lei": lei, "name": company.get("name"), "country": company.get("country"), "currency": data["currency"],
            "years": years, "check_years": recent, "year": year, "origin": data["origin"], "kpis": kpis,
            "balance": _balance(latest) if latest else None, "checks": checks, "metrics": data["metrics"],
            "documents": documents}
