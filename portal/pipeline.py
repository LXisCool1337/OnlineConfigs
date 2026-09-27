"""Job pipelines: company reports (10 years), industry package, batch runs and universe sync.

Every step is idempotent: documents already in the catalogue (same source URL or same SHA-256)
are skipped, so a job can be re-run or resumed at any time to fill gaps.
"""

from __future__ import annotations

import hashlib
import re
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from . import financials, fulltext
from .classify import LinkInfo, classify_report_link
from .connectors.base import API_SOURCES, Candidate
from .connectors.curated import Curated
from .connectors.esef import Esef
from .connectors.eurostat import Eurostat
from .connectors.firds import Firds, issuer_name
from .connectors.gleif import Gleif
from .connectors.irsite import IrSite
from .connectors.openalex import OpenAlex
from .connectors.websearch import WebSearch
from .connectors.wikidata import Wikidata
from .identifiers import EU_EEA, is_lei, language_preferences, nace_label, normalize_nace
from .net import BlockedByRobots, ContentError, HttpError
from .resolver import NotFound, Resolver
from .storage import slugify

ANNUAL_CATEGORIES = {"annual_report", "single_entity_statements"}
ESEF_CATEGORIES = {"esef_report", "esef_package", "esef_json"}
DEFAULT_INCLUDE = {"esef": True, "pdf": True, "websearch": True, "sustainability": None, "industry": False}
DEFAULT_INDUSTRY = {"statistics": True, "studies": True, "associations": True, "peers": True, "websearch": True}

CATEGORY_LABELS = {
    "annual_report": "Geschäftsbericht (PDF)",
    "single_entity_statements": "Jahresabschluss Einzelgesellschaft",
    "sustainability_report": "Nachhaltigkeitsbericht",
    "esef_report": "ESEF-Bericht (XHTML)",
    "esef_package": "ESEF-Paket (ZIP)",
    "esef_json": "ESEF-Daten (xBRL-JSON)",
    "statistics": "Statistik (Eurostat)",
    "study": "Studie (Open Access)",
    "association_report": "Verbands-/Behördenbericht",
    "web_report": "Bericht (Websuche)",
    "peer_report": "Wettbewerber-Bericht (ESEF)",
    "peer_report_package": "Wettbewerber-Paket (ESEF)",
    "peer_report_json": "Wettbewerber-Daten (ESEF)",
}


def today_from(params: dict) -> date:
    value = params.get("today")
    return date.fromisoformat(value) if value else date.today()


def year_window(n: int, today: date) -> list[int]:
    """Candidate fiscal years: the last n completed years plus the current one (non-calendar FYs)."""
    return list(range(today.year - n, today.year + 1))


def final_window(found: set[int], n: int, today: date) -> list[int]:
    last = today.year if today.year in found else today.year - 1
    return list(range(last - n + 1, last + 1))


def compute_coverage(docs: list[dict], window: list[int]) -> dict:
    pdf = {d["fiscal_year"] for d in docs if d["category"] in ANNUAL_CATEGORIES}
    esef = {d["fiscal_year"] for d in docs if d["category"] in ESEF_CATEGORIES}
    rows = [{"year": y, "pdf": y in pdf, "esef": y in esef} for y in window]
    missing = [y for y in window if y not in pdf and y not in esef]
    return {"years": window, "rows": rows, "covered": len(window) - len(missing), "target": len(window),
            "missing": missing}


def _split(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in re.split(r"[,;\n]+", str(value)) if v.strip()]


def parse_manual_urls(value, today: date) -> list[Candidate]:
    """Lines of 'URL' or '2017: URL' / '2017=URL' added by the user."""
    out = []
    for line in _split(value) if not isinstance(value, str) else [l for l in str(value).splitlines() if l.strip()]:
        m = re.match(r"^\s*((?:19|20)\d{2})\s*[:=]\s*(\S+)\s*$", line)
        year, url = (int(m.group(1)), m.group(2)) if m else (None, line.strip())
        if not re.match(r"^https?://", url, re.I):
            continue
        guess = classify_report_link(LinkInfo(url=url), today)
        category = guess.category if guess.category in ("sustainability_report", "single_entity_statements") \
            else "annual_report"
        out.append(Candidate(url=url, category=category, source="manual", fiscal_year=year or guess.fiscal_year,
                             fy_label=str(year) if year else guess.fy_label, language=guess.language,
                             title="Manuell hinzugefügt", score=1000.0, expect=("pdf", "xhtml", "html", "zip")))
    return out


def _dedupe(cands: list[Candidate]) -> list[Candidate]:
    best: dict[str, Candidate] = {}
    for c in cands:
        if c.url not in best or c.score > best[c.url].score:
            best[c.url] = c
    return list(best.values())


def select_company_candidates(cands: list[Candidate], *, prefs: list[str], all_languages: bool,
                              include_sustainability: bool) -> list[Candidate]:
    """One ESEF filing and the best PDF per fiscal year (optionally one per preferred language)."""
    chosen: list[Candidate] = []
    by_year: dict[int | None, list[Candidate]] = defaultdict(list)
    for c in _dedupe(cands):
        by_year[c.fiscal_year].append(c)
    for year, items in by_year.items():
        taken = set()
        for c in sorted((i for i in items if i.source == "esef"), key=lambda c: -c.score):
            if c.category not in taken:
                chosen.append(c)
                taken.add(c.category)
        manual = [i for i in items if i.source == "manual"]
        chosen += manual
        if year is None:
            continue
        annual = sorted((i for i in items if i.category == "annual_report" and i.source != "esef"
                         and i.source != "manual"), key=lambda c: -c.score)
        if not annual:
            annual = sorted((i for i in items if i.category == "single_entity_statements" and i.source != "manual"),
                            key=lambda c: -c.score)
        if annual and not any(m.category in ANNUAL_CATEGORIES for m in manual):
            if all_languages:
                picked = False
                for lang in prefs:
                    group = [a for a in annual if a.language == lang]
                    if group:
                        group[0].alternates = group[1:4]
                        chosen.append(group[0])
                        picked = True
                if not picked:
                    annual[0].alternates = annual[1:4]
                    chosen.append(annual[0])
            else:
                annual[0].alternates = annual[1:4]
                chosen.append(annual[0])
        if include_sustainability:
            sustain = sorted((i for i in items if i.category == "sustainability_report"), key=lambda c: -c.score)
            if sustain:
                sustain[0].alternates = sustain[1:3]
                chosen.append(sustain[0])
    return chosen


# --- downloading --------------------------------------------------------------------------

def company_filename(c: Candidate) -> str:
    year = c.fiscal_year or "ohne-jahr"
    label = (c.fy_label or str(year)).replace("/", "-")
    lang = f"_{c.language}" if c.language and c.source != "esef" else ""
    return f"{year}/{c.category}_{label}{lang}.{c.ext}"


def industry_filename(c: Candidate) -> str:
    if c.category.startswith("peer_report"):
        return f"{c.subdir}/{c.fiscal_year or 'o-j'}_{c.category}.{c.ext}"
    return f"{c.subdir or c.category}/{c.fiscal_year or 'o-j'}_{slugify(c.title, 70)}.{c.ext}"


def _fetch_one(ctx, cand: Candidate, *, scope: str, base_dir: Path, lei: str | None, nace: str | None,
               name_for) -> dict:
    owner = cand.lei or lei
    errors = []
    for attempt in [cand] + list(cand.alternates):
        if ctx.cancelled():
            return {"status": "cancelled", "candidate": cand}
        existing = ctx.db.find_document(scope, attempt.url, owner, nace)
        if existing:
            return {"status": "exists", "candidate": attempt, "doc": existing}
        dest = ctx.library.unique(base_dir / name_for(attempt))
        try:
            dl = ctx.http.download(attempt.url, dest, expect=attempt.expect,
                                   check_robots=attempt.source not in API_SOURCES)
        except BlockedByRobots as err:
            errors.append(str(err))
            ctx.log("warn", "Übersprungen (robots.txt)", url=attempt.url)
            continue
        except (HttpError, ContentError) as err:
            errors.append(str(err))
            ctx.log("warn", f"Download fehlgeschlagen: {err}", url=attempt.url)
            continue
        duplicate = ctx.db.find_by_hash(scope, dl.sha256, owner, nace)
        if duplicate:
            dest.unlink(missing_ok=True)
            return {"status": "duplicate", "candidate": attempt, "doc": duplicate}
        doc = {
            "scope": scope, "lei": owner, "nace": nace, "category": attempt.category,
            "fiscal_year": attempt.fiscal_year, "fy_label": attempt.fy_label, "period_end": attempt.period_end,
            "language": attempt.language, "title": attempt.title, "source": attempt.source,
            "source_url": attempt.url, "path": ctx.library.relative(dl.path), "sha256": dl.sha256, "size": dl.size,
            "mime": dl.kind, "score": attempt.score, "meta": {**attempt.meta, "final_url": dl.url},
            "job_id": ctx.job_id,
        }
        doc_id = ctx.db.add_document(doc)
        if doc_id is None:
            dest.unlink(missing_ok=True)
            return {"status": "exists", "candidate": attempt}
        doc["id"] = doc_id
        size = f"{dl.size / 1_048_576:.1f} MB" if dl.size >= 1_048_576 else f"{max(1, round(dl.size / 1024))} KB"
        ctx.log("ok", f"Gespeichert: {CATEGORY_LABELS.get(attempt.category, attempt.category)} "
                      f"{attempt.fy_label or attempt.fiscal_year or ''} ({size})".replace("  ", " "),
                doc_id=doc_id, url=attempt.url)
        return {"status": "ok", "candidate": attempt, "doc": doc}
    return {"status": "failed", "candidate": cand, "errors": errors}


def download_many(ctx, cands: list[Candidate], *, scope: str, base_dir: Path, lei: str | None = None,
                  nace: str | None = None, name_for=company_filename) -> dict:
    counts: dict[str, int] = defaultdict(int)
    results = []
    if not cands:
        return {"counts": {}, "results": []}
    workers = max(1, int(ctx.settings.download_workers))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="download") as pool:
        futures = [pool.submit(_fetch_one, ctx, c, scope=scope, base_dir=base_dir, lei=lei, nace=nace,
                               name_for=name_for) for c in cands]
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                result = fut.result()
            except Exception as err:  # noqa: BLE001 - one broken file must not stop the job
                result = {"status": "failed", "errors": [repr(err)]}
                ctx.log("error", f"Unerwarteter Fehler beim Download: {err!r}")
            counts[result["status"]] += 1
            results.append(result)
            ctx.progress(i / len(futures))
    ctx.check_cancel()
    return {"counts": dict(counts), "results": results}


# --- company job ---------------------------------------------------------------------------

def run_company(ctx, params: dict, runner=None) -> dict:
    s = ctx.settings
    today = today_from(params)
    n = max(1, min(int(params.get("years") or s.years), 30))
    include = {**DEFAULT_INCLUDE, **(params.get("include") or {})}
    if include["sustainability"] is None:
        include["sustainability"] = s.include_sustainability
    resolver = Resolver(ctx)

    ctx.stage(0.01, "Unternehmen auflösen (GLEIF-Register)")
    company = resolver.resolve(query=params.get("query"), lei=params.get("lei"))
    overrides = {k: params[k] for k in ("ir_url", "website", "nace", "keywords") if params.get(k)}
    if overrides.get("nace"):
        overrides["nace"] = normalize_nace(overrides["nace"]) or company.get("nace")
    if overrides:
        company = ctx.db.update_company_fields(company["lei"], overrides) or company
    if ctx.job_id is not None:
        ctx.db.update_job(ctx.job_id, title=f"{company['name']} – Geschäftsberichte")
    ctx.log("info", f"Unternehmen: {company['name']} · LEI {company['lei']} · {company.get('country') or '?'}")

    ctx.stage(0.04, "Stammdaten anreichern (ISIN, Website, Branche)")
    company = resolver.enrich(company)
    prefs = language_preferences(params.get("languages") or s.languages, company.get("country"))
    window = year_window(n, today)
    years = set(window)
    cands: list[Candidate] = []

    if include["esef"]:
        ctx.stage(0.08, "ESEF-Jahresfinanzberichte suchen (filings.xbrl.org)")
        try:
            filings = Esef(ctx).filings(company["lei"])
            ctx.log("info", f"ESEF: {len(filings)} Berichtsperioden gefunden",
                    periods=[f["period_end"] for f in filings])
            if filings:
                company = ctx.db.upsert_company({"lei": company["lei"], "has_esef": 1, "listed": 1})
            cands += Esef.candidates(filings, params.get("esef_formats") or s.esef_formats, years)
        except HttpError as err:
            ctx.log("warn", f"ESEF-Quelle nicht erreichbar: {err}")

    if include["pdf"]:
        ctx.stage(0.15, "IR-Website nach PDF-Geschäftsberichten durchsuchen")
        cands += IrSite(ctx).discover(company, years, prefs, today)

    cands += parse_manual_urls(params.get("urls"), today)

    have = {c.fiscal_year for c in cands if c.category in ANNUAL_CATEGORIES}
    esef_years = {c.fiscal_year for c in cands if c.source == "esef"}
    # Years without any document first (usually the pre-ESEF ones), then years that only lack the PDF.
    missing = sorted((y for y in range(today.year - n, today.year) if y not in have),
                     key=lambda y: (y in esef_years, -y))
    search = WebSearch(ctx)
    if include["websearch"] and missing:
        if search.enabled:
            ctx.stage(0.4, f"Websuche für fehlende PDF-Jahre: {', '.join(map(str, missing))}")
            cands += search.annual_reports(company, missing, prefs, today)
        else:
            ctx.log("info", "Websuche nicht konfiguriert (Einstellungen) – Lücken bleiben offen",
                    missing=missing)

    ctx.stage(0.45, "Beste Quelle je Geschäftsjahr auswählen")
    blocked = ctx.db.blocked_urls()
    if blocked:
        skipped = [c for c in cands if c.url in blocked]
        cands = [c for c in cands if c.url not in blocked]
        if skipped:
            ctx.log("info", f"{len(skipped)} als falsch markierte Links übersprungen")
    chosen = select_company_candidates(cands, prefs=prefs,
                                       all_languages=bool(params.get("all_languages", s.all_languages)),
                                       include_sustainability=bool(include["sustainability"]))
    found = {c.fiscal_year for c in chosen if c.fiscal_year}
    window = final_window(found, n, today)
    chosen = [c for c in chosen if c.fiscal_year in window or c.source == "manual"]

    ctx.stage(0.5, f"{len(chosen)} Dokumente herunterladen")
    base_dir = ctx.library.company_dir(company)
    with ctx.span(0.5, 0.85 if include["industry"] else 0.92):
        dl = download_many(ctx, chosen, scope="company", base_dir=base_dir, lei=company["lei"])

    ctx.stage(0.86 if include["industry"] else 0.93, "Kennzahlen aus ESEF auslesen und Volltext indizieren")
    figures = financials.extract(ctx, company["lei"])
    indexed = fulltext.index_pending(ctx, lei=company["lei"])

    docs = ctx.db.company_documents(company["lei"])
    coverage = compute_coverage(docs, window)
    ctx.library.write_manifest(base_dir, {
        "company": {k: company.get(k) for k in ("lei", "name", "country", "isins", "website", "ir_url", "nace")},
        "coverage": coverage}, docs)
    missing_text = ", ".join(map(str, coverage["missing"])) or "keine"
    ctx.log("summary", f"Abdeckung: {coverage['covered']}/{coverage['target']} Geschäftsjahre "
                       f"({coverage['years'][0]}–{coverage['years'][-1]}), fehlend: {missing_text}")
    if coverage["missing"]:
        ctx.log("hint", "Für fehlende Jahre: IR-URL der Berichts-Archivseite eintragen, Websuche aktivieren "
                        "oder PDF-Links manuell ergänzen (Format: 2017: https://…)")
    summary = {"lei": company["lei"], "name": company["name"], "coverage": coverage, "downloads": dl["counts"],
               "candidates": len(cands), "languages": prefs, "financial_years": figures["years"],
               "indexed": indexed}

    if include["industry"]:
        nace = normalize_nace(params.get("nace") or company.get("nace"))
        if nace:
            ctx.stage(0.9, "Branchenpaket zusammenstellen")
            with ctx.span(0.9, 0.99):
                summary["industry"] = run_industry(ctx, {
                    "nace": nace, "keywords": params.get("keywords") or company.get("keywords"),
                    "country": company.get("country"), "company_lei": company["lei"], "years": n,
                    "peers": params.get("peers"), "include_industry": params.get("include_industry"),
                    "today": params.get("today")})
        else:
            ctx.log("warn", "Kein NACE-Code gesetzt – Branchenreports übersprungen. Bitte Branche wählen.")
    return summary


# --- industry job --------------------------------------------------------------------------

def _topic(label_en: str) -> str:
    text = re.sub(r"^(manufacture of|other|activities of)\s+", "", label_en, flags=re.I)
    return re.sub(r"\b(n\.e\.c\.|except.*)$", "", text, flags=re.I).strip(" ,;")


def find_peers(ctx, nace: str, company: dict | None, manual) -> list[dict]:
    s = ctx.settings
    peers: dict[str, dict] = {}
    resolver = Resolver(ctx)
    for item in _split(manual):
        try:
            peer = resolver.resolve(query=item)
            peers[peer["lei"]] = {**peer, "via": "manuell"}
        except NotFound as err:
            ctx.log("warn", f"Wettbewerber „{item}“: {err}")
    qids = [i["qid"] for i in (company or {}).get("industries") or [] if i.get("qid")]
    if qids:
        try:
            for peer in Wikidata(ctx).peers(qids, exclude_lei=(company or {}).get("lei")):
                stored = ctx.db.upsert_company({**peer, "listed": 1})
                peers.setdefault(peer["lei"], {**stored, "via": "Wikidata-Branche"})
        except HttpError as err:
            ctx.log("warn", f"Wikidata (Wettbewerber) nicht erreichbar: {err}")
    for row in ctx.db.companies_with_nace(nace[:2]):
        peers.setdefault(row["lei"], {**row, "via": "gleicher NACE-Code"})
    peers.pop((company or {}).get("lei"), None)
    ranked = sorted(peers.values(), key=lambda p: (p["via"] != "manuell", not p.get("has_esef"), p.get("name") or ""))
    return ranked[: s.peers_max]


def store_statistics(ctx, nace: str, spec: dict, data: dict, base_dir: Path) -> str:
    existing = ctx.db.find_document("industry", data["url"], None, nace)
    if existing:
        return "exists"
    folder = base_dir / "statistics"
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / f"eurostat_{spec['code']}.csv"
    raw_path = folder / f"eurostat_{spec['code']}.json"
    csv_bytes = data["csv"].encode("utf-8")
    csv_path.write_bytes(csv_bytes)
    raw_path.write_bytes(data["raw"])
    ctx.db.add_document({
        "scope": "industry", "nace": nace, "category": "statistics", "title": f"Eurostat {spec['code']}: {data['label']}",
        "source": "eurostat", "source_url": data["url"], "path": ctx.library.relative(csv_path),
        "sha256": hashlib.sha256(csv_bytes).hexdigest(), "size": len(csv_bytes), "mime": "csv",
        "meta": {"dataset": spec["code"], "rows": data["rows"], "updated": data.get("updated"),
                 "raw_file": ctx.library.relative(raw_path)}, "job_id": ctx.job_id})
    ctx.log("ok", f"Statistik gespeichert: {spec['code']} ({data['rows']} Werte)")
    return "ok"


def run_industry(ctx, params: dict, runner=None) -> dict:
    s = ctx.settings
    today = today_from(params)
    nace = normalize_nace(params.get("nace"))
    if not nace:
        raise ValueError("Ungültiger oder fehlender NACE-Code (z. B. 28 oder 28.29)")
    n = max(1, min(int(params.get("years") or s.years), 30))
    year_from = today.year - n
    include = {**DEFAULT_INDUSTRY, **(params.get("include_industry") or {})}
    label_de, label_en = nace_label(nace, "de"), nace_label(nace, "en")
    keywords = _split(params.get("keywords"))
    country = (params.get("country") or "").upper() or None
    company = ctx.db.company(params["company_lei"]) if params.get("company_lei") else None
    if ctx.job_id is not None and not company:
        ctx.db.update_job(ctx.job_id, title=f"Branche NACE {nace} – {label_de}")
    ctx.log("info", f"Branche NACE {nace}: {label_de} · Zeitraum ab {year_from}")
    base_dir = ctx.library.industry_dir(nace)
    relevance = keywords + [label_de, _topic(label_en)]
    cands: list[Candidate] = []
    stats = defaultdict(int)

    if include["statistics"]:
        ctx.stage(0.02, "Amtliche Statistik (Eurostat)")
        eurostat = Eurostat(ctx)
        for spec in eurostat.datasets_for(nace):
            ctx.check_cancel()
            data = eurostat.fetch(spec, nace, [country] if country else [], year_from)
            if data:
                stats[store_statistics(ctx, nace, spec, data, base_dir)] += 1

    if include["studies"]:
        ctx.stage(0.2, "Open-Access-Studien (OpenAlex)")
        topic = " ".join(keywords[:3]) or _topic(label_en)
        cands += OpenAlex(ctx).studies(f"{topic} industry market", year_from, s.openalex_max)

    if include["associations"]:
        ctx.stage(0.3, "Verbands- und Behördenpublikationen")
        cands += Curated(ctx).reports(nace, relevance, year_from, today)

    search = WebSearch(ctx)
    if include["websearch"] and search.enabled:
        ctx.stage(0.5, "Websuche nach Branchenreports")
        cands += search.industry_reports(_topic(label_en), label_de, keywords, year_from, limit=10, today=today)

    if include["peers"]:
        ctx.stage(0.55, "Wettbewerber ermitteln und ESEF-Berichte laden")
        peers = find_peers(ctx, nace, company, params.get("peers"))
        ctx.log("info", f"{len(peers)} Wettbewerber", peers=[f"{p['name']} ({p['via']})" for p in peers])
        esef = Esef(ctx)
        for peer in peers:
            ctx.check_cancel()
            try:
                filings = esef.filings(peer["lei"])[: max(1, s.peer_years)]
            except HttpError as err:
                ctx.log("warn", f"ESEF für {peer['name']} nicht erreichbar: {err}")
                continue
            if filings:
                ctx.db.upsert_company({"lei": peer["lei"], "has_esef": 1})
            for c in Esef.candidates(filings, ["report"], lei=peer["lei"], category_override="peer_report",
                                     subdir=f"peers/{slugify(peer['name'], 40)}_{peer['lei']}"):
                c.title = f"{peer['name']} – ESEF-Bericht {c.fy_label}"
                c.meta["peer_name"] = peer["name"]
                c.meta["via"] = peer["via"]
                cands.append(c)

    blocked = ctx.db.blocked_urls()
    cands = [c for c in cands if c.url not in blocked]
    ctx.stage(0.7, f"{len(cands)} Branchendokumente herunterladen")
    with ctx.span(0.7, 0.92):
        dl = download_many(ctx, cands, scope="industry", base_dir=base_dir, nace=nace, name_for=industry_filename)
    ctx.stage(0.93, "Kennzahlen der Wettbewerber auslesen, Volltext indizieren")
    for lei in sorted({c.lei for c in cands if c.lei}):
        financials.extract(ctx, lei)
    if company:
        financials.extract(ctx, company["lei"])
    fulltext.index_pending(ctx, nace=nace)
    docs = ctx.db.industry_documents(nace)
    ctx.library.write_manifest(base_dir, {"industry": {"nace": nace, "label_de": label_de, "label_en": label_en,
                                                       "keywords": keywords}}, docs)
    by_category: dict[str, int] = defaultdict(int)
    for d in docs:
        by_category[d["category"]] += 1
    ctx.log("summary", f"Branchenpaket NACE {nace}: {len(docs)} Dokumente",
            by_category=dict(by_category))
    return {"nace": nace, "label": label_de, "documents": len(docs), "by_category": dict(by_category),
            "downloads": dl["counts"], "statistics": dict(stats)}


# --- batch, refresh and universe -----------------------------------------------------------

def run_batch(ctx, params: dict, runner=None) -> dict:
    if runner is None:
        raise ValueError("Stapelaufträge brauchen den Job-Runner")
    leis = [l for l in _split(params.get("leis")) if is_lei(l)]
    if leis:
        companies = [ctx.db.company(l) or {"lei": l, "name": l} for l in leis]
    else:
        companies = ctx.db.universe_companies([c.upper() for c in _split(params.get("countries"))],
                                              bool(params.get("esef_only")), int(params.get("limit") or 50))
    child = {k: params[k] for k in ("years", "include", "languages", "include_industry") if k in params}
    for c in companies:
        ctx.check_cancel()
        runner.submit("company", {**child, "lei": c["lei"]}, title=f"{c['name']} – Geschäftsberichte",
                      parent_id=ctx.job_id)
    ctx.log("summary", f"{len(companies)} Unternehmensaufträge eingereiht")
    return {"enqueued": len(companies)}


def run_refresh(ctx, params: dict, runner=None) -> dict:
    watched = ctx.db.query("SELECT lei, name FROM companies WHERE watch = 1 ORDER BY name")
    return run_batch(ctx, {**params, "leis": [w["lei"] for w in watched]}, runner) if watched else {"enqueued": 0}


def run_universe(ctx, params: dict, runner=None) -> dict:
    s = ctx.settings
    source = params.get("source") or "esef"
    countries = frozenset(c.upper() for c in (s.universe_countries or [])) or EU_EEA
    if source == "esef":
        ctx.stage(0.02, "ESEF-Emittenten von filings.xbrl.org laden")
        count = 0
        batch = []
        for lei, name, country in Esef(ctx).issuers(max_pages=int(params.get("max_pages") or 1000)):
            if not is_lei(lei) or (country and country not in countries):
                continue
            batch.append({"lei": lei, "name": name or lei, "country": country, "has_esef": 1, "listed": 1})
            if len(batch) >= 200:
                with ctx.db.transaction():
                    for row in batch:
                        ctx.db.upsert_company(row)
                count += len(batch)
                batch = []
                ctx.log("info", f"{count} Emittenten übernommen")
        with ctx.db.transaction():
            for row in batch:
                ctx.db.upsert_company(row)
        count += len(batch)
        ctx.log("summary", f"Universum (ESEF): {count} Emittenten")
        return {"source": "esef", "issuers": count}
    if source == "firds":
        ctx.stage(0.02, "ESMA FIRDS: aktuelle Aktien-Referenzdaten laden (große Dateien)")
        securities = Firds(ctx).securities(countries, tuple(s.universe_cfi_prefixes))
        ctx.stage(0.7, f"{len(securities)} Aktien speichern")
        ctx.db.upsert_securities(list(securities.values()))
        by_lei: dict[str, list[dict]] = defaultdict(list)
        for sec in securities.values():
            if sec.get("lei") and not sec.get("termination"):
                by_lei[sec["lei"]].append(sec)
        new = [lei for lei in by_lei if not ctx.db.company(lei)]
        names = {}
        if new and params.get("gleif_names", True):
            ctx.stage(0.8, f"Namen für {len(new)} neue Emittenten bei GLEIF abfragen")
            try:
                names = {r["lei"]: r for r in Gleif(ctx).by_leis(new)}
            except HttpError as err:
                ctx.log("warn", f"GLEIF nicht erreichbar, nutze FIRDS-Namen: {err}")
        with ctx.db.transaction():
            for lei, secs in by_lei.items():
                record = names.get(lei) or {"name": issuer_name(secs[0]["name"]), "country": secs[0]["isin"][:2]}
                ctx.db.upsert_company({"lei": lei, "name": record["name"], "country": record.get("country"),
                                       "isins": sorted(s["isin"] for s in secs), "listed": 1,
                                       "meta": record.get("meta") or {}})
        ctx.log("summary", f"Universum (FIRDS): {len(securities)} Aktien von {len(by_lei)} Emittenten")
        return {"source": "firds", "securities": len(securities), "issuers": len(by_lei)}
    raise ValueError(f"Unbekannte Universumsquelle: {source}")


def run_index(ctx, params: dict, runner=None) -> dict:
    """Maintenance: index all pending documents and recompute key figures for every issuer with ESEF reports."""
    ctx.stage(0.05, "Volltext indizieren")
    indexed = fulltext.index_pending(ctx, lei=params.get("lei"))
    ctx.stage(0.6, "Kennzahlen neu berechnen")
    leis = [r["lei"] for r in ctx.db.query(
        "SELECT DISTINCT lei FROM documents WHERE lei IS NOT NULL AND category IN ('esef_report', 'peer_report', "
        "'esef_package', 'peer_report_package')" + (" AND lei = ?" if params.get("lei") else ""),
        (params["lei"],) if params.get("lei") else ())]
    for lei in leis:
        ctx.check_cancel()
        financials.extract(ctx, lei)
    ctx.log("summary", f"Volltext: {indexed.get('ok', 0)} neu indiziert · Kennzahlen für {len(leis)} Emittenten")
    return {"indexed": indexed, "financials": len(leis)}


PIPELINES = {
    "index": run_index,
    "company": run_company,
    "industry": run_industry,
    "batch": run_batch,
    "refresh": run_refresh,
    "universe": run_universe,
}


def run_job(ctx, kind: str, params: dict, runner=None) -> dict:
    if kind not in PIPELINES:
        raise ValueError(f"Unbekannter Auftragstyp: {kind}")
    return PIPELINES[kind](ctx, params, runner)


def describe_error(err: BaseException) -> str:
    if isinstance(err, (NotFound, ValueError)):
        return str(err)
    return f"{type(err).__name__}: {err}\n" + "".join(traceback.format_exception(err)[-3:])
