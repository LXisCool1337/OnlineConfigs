"""Classify document links: document type, fiscal year and language, across all EU languages.

A link is judged on its own text first (anchor text, title attribute, file name). Only when that
says nothing about the document type does the surrounding text count (table row, heading), so an
archive table with rows like "2016 | PDF" under the heading "Geschäftsberichte" still works.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import unquote, urlsplit


def fold(text: str) -> str:
    """Lower-case, strip accents, unify separators: 'Geschäfts­bericht_2019.pdf' -> 'geschaftsbericht 2019 pdf'."""
    text = unquote(text or "").replace("­", "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    for src, dst in (("ß", "ss"), ("ł", "l"), ("ø", "o"), ("æ", "ae"), ("đ", "d"), ("þ", "th"), ("œ", "oe")):
        text = text.replace(src, dst)
    text = re.sub(r"[_\-–—+.,;:!?()\[\]{}|/\\'\"’‘`«»“”„&*#=~]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _terms(items):
    """Fold patterns once; short ones (<= 4 chars) must match whole words."""
    out = []
    for item in items:
        term, rest = (item[0], item[1:]) if isinstance(item, tuple) else (item, ())
        folded = fold(term)
        whole = len(folded) <= 4
        rx = re.compile(r"(?<![a-z0-9])" + re.escape(folded) + r"(?![a-z0-9])") if whole else None
        out.append((folded, rx, *rest))
    return out


def _find(terms, text: str):
    for entry in terms:
        folded, rx = entry[0], entry[1]
        if (rx.search(text) if rx else folded in text):
            yield entry


# (term, language, strength) - strength 3 = clearly the annual report, 2 = likely, 1 = weak
ANNUAL = _terms([
    ("annual report", "en", 3), ("annual financial report", "en", 3), ("integrated report", "en", 3),
    ("integrated annual report", "en", 3), ("annual and sustainability report", "en", 3),
    ("universal registration document", "en", 3), ("registration document", "en", 2),
    ("report and accounts", "en", 3), ("annual accounts", "en", 2), ("form 20-f", "en", 3),
    ("form 10-k", "en", 3), ("consolidated financial statements", "en", 2), ("financial statements", "en", 2),
    ("annual review", "en", 1),
    ("geschäftsbericht", "de", 3), ("geschaeftsbericht", "de", 3), ("geschäfts- und nachhaltigkeitsbericht", "de", 3),
    ("jahresbericht", "de", 3), ("jahresfinanzbericht", "de", 3), ("integrierter bericht", "de", 3),
    ("konzernabschluss", "de", 2), ("konzernlagebericht", "de", 2), ("finanzbericht", "de", 2),
    ("jahresabschluss", "de", 2),
    ("rapport annuel", "fr", 3), ("rapport financier annuel", "fr", 3), ("document d'enregistrement universel", "fr", 3),
    ("document de référence", "fr", 3), ("rapport intégré", "fr", 3), ("comptes consolidés", "fr", 2),
    ("comptes annuels", "fr", 2), ("états financiers", "fr", 2), ("rapport de gestion", "fr", 2),
    ("jaarverslag", "nl", 3), ("jaarrapport", "nl", 3), ("geïntegreerd verslag", "nl", 3), ("jaarrekening", "nl", 2),
    ("relazione finanziaria annuale", "it", 3), ("relazione annuale", "it", 3), ("bilancio integrato", "it", 3),
    ("relazione e bilancio", "it", 3), ("bilancio consolidato", "it", 2),
    ("informe anual", "es", 3), ("informe financiero anual", "es", 3), ("informe integrado", "es", 3),
    ("memoria anual", "es", 3), ("cuentas anuales", "es", 2), ("informe de gestión", "es", 2),
    ("relatório anual", "pt", 3), ("relatório e contas", "pt", 3), ("relatório integrado", "pt", 3),
    ("relatório de gestão", "pt", 2), ("contas consolidadas", "pt", 2),
    ("årsredovisning", "sv", 3), ("års- och hållbarhetsredovisning", "sv", 3), ("årsberättelse", "sv", 3),
    ("årsrapport", "da", 3), ("årsregnskab", "da", 2), ("årsberetning", "no", 3), ("ársskýrsla", "is", 3),
    ("vuosikertomus", "fi", 3), ("tilinpäätös", "fi", 2), ("toimintakertomus", "fi", 2),
    ("raport roczny", "pl", 3), ("sprawozdanie finansowe", "pl", 2), ("sprawozdanie zarządu", "pl", 2),
    ("výroční zpráva", "cs", 3), ("výročná správa", "sk", 3), ("éves jelentés", "hu", 3), ("éves beszámoló", "hu", 3),
    ("raport anual", "ro", 3), ("raportul anual", "ro", 3), ("situații financiare", "ro", 2),
    ("годишен доклад", "bg", 3), ("годишен финансов отчет", "bg", 3),
    ("ετήσια οικονομική έκθεση", "el", 3), ("ετήσια έκθεση", "el", 3), ("ετήσια χρηματοοικονομική έκθεση", "el", 3),
    ("letno poročilo", "sl", 3), ("godišnje izvješće", "hr", 3), ("godišnji izvještaj", "hr", 3),
    ("metinis pranešimas", "lt", 3), ("metinė ataskaita", "lt", 3), ("gada pārskats", "lv", 3),
    ("aastaaruanne", "et", 3), ("majandusaasta aruanne", "et", 3),
])

# File-name abbreviations such as GB2019.pdf, AR19_EN.pdf, URD-2021.pdf
SHORT_REPORT = re.compile(r"(?<![a-z0-9])(gb|ar|jb|jfb|urd|ddr|afr|rfa)\s?((?:19|20)\d{2}|\d{2})(?![0-9])")
SHORT_LANG = {"gb": "de", "jb": "de", "jfb": "de", "urd": "fr", "ddr": "fr", "rfa": "fr", "ar": "en", "afr": "en"}

INTERIM = _terms([
    "half year", "half yearly", "halfyear", "semi annual", "halbjahr", "zwischenbericht", "zwischenmitteilung",
    "quartalsmitteilung", "quartalsbericht", "quartalsfinanzbericht", "quarterly", "quarter", "interim",
    "semestriel", "semestrale", "semestral", "trimestriel", "trimestrale", "trimestral", "delårsrapport",
    "halvårsrapport", "halvårsredovisning", "kvartalsrapport", "osavuosikatsaus", "puolivuosikatsaus",
    "halfjaar", "kwartaal", "półroczny", "kwartalny", "pololetní", "polročná", "féléves", "semestrial",
    "first half", "premier semestre", "primo semestre", "primer semestre", "nine months", "neun monate",
    "9m", "6m", "3m", "h1", "q1", "q2", "q3", "q4",
])
SUSTAINABILITY = _terms([
    "nachhaltigkeit", "sustainability", "sustainable", "nichtfinanziell", "non-financial", "csr", "esg",
    "responsibility report", "verantwortung", "développement durable", "extra-financière", "dpef",
    "duurzaamheid", "sostenibilità", "non finanziaria", "sostenibilidad", "no financiera", "sustentabilidade",
    "hållbarhet", "bæredygtighed", "bærekraft", "vastuullisuus", "yritysvastuu", "zrównoważon", "udržitelnost",
    "fenntarthatóság", "climate", "klima", "tcfd", "umweltbericht", "umwelterklärung", "gri",
])
REMUNERATION = _terms([
    "vergütungsbericht", "verguetungsbericht", "remuneration", "compensation report", "rémunération", "remuneratie",
    "remunerazione", "remuneraciones", "remunerações", "ersättning", "vederlag", "lønnsrapport", "palkitsemis",
    "wynagrodzeń", "odměňování",
])
GOVERNANCE = _terms([
    "corporate governance", "erklärung zur unternehmensführung", "entsprechenserklärung", "gouvernement d'entreprise",
    "governo societario", "gobierno corporativo", "governo das sociedades", "bolagsstyrning", "selskabsledelse",
    "eierstyring", "governance report", "governance statement",
])
AGM = _terms([
    "hauptversammlung", "einladung", "tagesordnung", "general meeting", "agm", "egm", "assemblée générale",
    "assemblea", "junta general", "årsstämma", "bolagsstämma", "generalforsamling", "yhtiökokous",
    "walne zgromadzenie", "valná hromada", "közgyűlés", "adunarea generală", "notice of meeting", "proxy",
    "stimmrecht", "gegenantrag", "algemene vergadering", "aandeelhoudersvergadering",
])
PRESENTATION = _terms([
    "presentation", "präsentation", "praesentation", "slides", "roadshow", "factsheet", "fact sheet",
    "capital markets day", "investor day", "webcast", "conference call", "earnings call", "analyst", "analysten",
    "transcript", "handout",
])
PRESS = _terms([
    "press release", "pressemitteilung", "presseinformation", "communiqué", "comunicato", "nota de prensa",
    "pressmeddelande", "corporate news", "ad hoc", "ad-hoc", "tiedote", "persbericht", "komunikat",
])
SINGLE_ENTITY = _terms([
    "jahresabschluss der", "jahresabschluss und lagebericht der", "einzelabschluss", "hgb", "parent company",
    "separate financial statements", "comptes sociaux", "enkelvoudige", "bilancio separato", "bilancio d'esercizio",
    "bilancio di esercizio", "cuentas anuales individuales", "moderbolag", "moderselskab", "emoyhtiö",
])
# German issuers publish the parent's HGB statements as "Annual Financial Statements" (often "DE only"),
# next to the group's annual report. Only a sign of single-entity statements when nothing says "annual
# report" (strength 3) or "consolidated".
SINGLE_ENTITY_WEAK = _terms(["annual financial statements", "de only", "german only", "nur deutsch"])
GROUP = _terms(["consolidated", "konzern", "consolides", "consolidato", "consolidadas", "geconsolideerde"])
SUMMARY = _terms([
    "kurzbericht", "kurzfassung", "summary", "highlights", "auszug", "extract", "excerpt", "magazine", "magazin",
    "letter to shareholders", "aktionärsbrief", "brief an die aktionäre", "at a glance", "auf einen blick",
    "short version", "abridged", "brochure", "broschüre",
])
CHAPTER = _terms([
    "chapter", "kapitel", "section", "abschnitt", "lagebericht", "konzernabschluss", "anhang", "notes",
    "management report", "financial statements", "bestätigungsvermerk", "auditor",
])
FULL = _terms(["gesamt", "komplett", "vollständig", "vollversion", "full", "complete", "entire", "integral",
               "completo", "completa"])

LANG_CODES = {"de", "en", "fr", "nl", "it", "es", "pt", "sv", "da", "fi", "pl", "cs", "sk", "hu", "ro", "bg",
              "el", "sl", "hr", "lt", "lv", "et", "no", "is"}
LANG3 = {"deu": "de", "ger": "de", "eng": "en", "fra": "fr", "fre": "fr", "ita": "it", "spa": "es", "esp": "es",
         "nld": "nl", "dut": "nl", "swe": "sv", "dan": "da", "fin": "fi", "pol": "pl", "por": "pt", "nor": "no",
         "ces": "cs", "cze": "cs", "hun": "hu", "ron": "ro", "rum": "ro"}
LANG_WORDS = {"english": "en", "englisch": "en", "anglais": "en", "inglese": "en", "ingles": "en",
              "engelsk": "en", "engelska": "en", "deutsch": "de", "german": "de", "allemand": "de",
              "tedesco": "de", "francais": "fr", "french": "fr", "franzosisch": "fr", "italiano": "it",
              "italian": "it", "espanol": "es", "spanish": "es", "castellano": "es", "nederlands": "nl",
              "dutch": "nl", "svenska": "sv", "swedish": "sv", "dansk": "da", "danish": "da", "norsk": "no",
              "suomi": "fi", "finnish": "fi", "polski": "pl", "portugues": "pt", "portuguese": "pt",
              "cestina": "cs", "magyar": "hu"}
_LANG_TOKEN = re.compile(r"(?:^|[/_\-.\s(\[])([a-z]{2,3})(?=$|[/_\-.\s)\]])")
_LANG_WORD = re.compile(r"(?<![a-z])(" + "|".join(LANG_WORDS) + r")(?![a-z])")

YEAR_SPAN = re.compile(r"(?<!\d)((?:19|20)\d{2})\s?(/|-|–|_|\\)\s?((?:19|20)\d{2}|\d{2})(?!\d)")
YEAR_ONE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
DATE_AFTER = re.compile(r"[-/._](0[1-9]|1[0-2])(?:[-/._]|$)")
DATE_BEFORE = re.compile(r"(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-]$")


@dataclass
class LinkInfo:
    url: str
    anchor: str = ""
    title: str = ""
    context_before: str = ""
    context_after: str = ""
    heading: str = ""
    page_title: str = ""
    page_url: str = ""
    page_lang: str | None = None


@dataclass
class Guess:
    category: str = "other"
    strength: int = 0
    fiscal_year: int | None = None
    fy_label: str | None = None
    year_weight: float = 0.0
    language: str | None = None
    flags: set = field(default_factory=set)


@dataclass
class YearHit:
    year: int
    label: str
    pos: int
    span: bool
    date: bool


def extract_years(text: str, lo: int, hi: int) -> list[YearHit]:
    raw = unquote(text or "").lower()
    hits, taken = [], []
    for m in YEAR_SPAN.finditer(raw):
        a, sep, b = int(m.group(1)), m.group(2), m.group(3)
        end = int(b) if len(b) == 4 else (a // 100) * 100 + int(b)
        if end != a + 1 or not lo <= end <= hi:
            continue
        if sep in "-_" and re.match(r"[-_./]\d{1,2}(?!\d)", raw[m.end():]):
            continue  # a date such as 2011-12-31, not the fiscal year 2011/12
        hits.append(YearHit(end, f"{a}/{str(end)[2:]}", m.start(), True, False))
        taken.append(m.span())
    for m in YEAR_ONE.finditer(raw):
        if any(s <= m.start() < e for s, e in taken):
            continue
        year = int(m.group(1))
        if not lo <= year <= hi:
            continue
        is_date = bool(DATE_AFTER.match(raw, m.end())) or bool(DATE_BEFORE.search(raw[max(0, m.start() - 6):m.start()]))
        hits.append(YearHit(year, str(year), m.start(), False, is_date))
    folded = fold(text)
    for m in SHORT_REPORT.finditer(folded):
        value = m.group(2)
        year = int(value) if len(value) == 4 else 2000 + int(value)
        if lo <= year <= hi and not any(h.year == year for h in hits):
            hits.append(YearHit(year, str(year), 10_000 + m.start(), False, False))
    hits.sort(key=lambda h: h.pos)
    return hits


def pick_year(fields: list[tuple[str, float, bool]], lo: int, hi: int) -> tuple[int | None, str | None, float]:
    """``fields`` = (text, weight, nearest_last). Returns (year, label, weight) of the best evidence."""
    best = (None, None, 0.0)
    for text, weight, nearest_last in fields:
        hits = [h for h in extract_years(text, lo, hi)]
        if not hits:
            continue
        good = [h for h in hits if not h.date] or hits
        hit = good[-1] if nearest_last else good[0]
        spans = [h for h in good if h.span]
        if spans and not nearest_last:
            hit = spans[0]
        w = weight * (0.3 if hit.date else 1.0) + (0.5 if hit.span else 0.0)
        if w > best[2]:
            best = (hit.year, hit.label, w)
    return best


_PAREN_CODE = re.compile(r"[(\[]\s*([a-z]{2,3})\s*[)\]]")
_UPPER_CODE = re.compile(r"(?<![A-Za-z])([A-Z]{2,3})(?![A-Za-z])")


def _lang_code(token: str) -> str | None:
    token = token.lower()
    code = LANG3.get(token, token)
    if code not in LANG_CODES:
        return None
    return code


def detect_language(info: LinkInfo, term_lang: str | None) -> str | None:
    """Explicit markers beat keyword language; directory names and page language come last."""
    path = unquote(urlsplit(info.url).path)
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = _LANG_WORD.search(fold(" ".join((info.anchor, info.title, stem))))
    if m:
        return LANG_WORDS[m.group(1)]
    tokens = [t for t in re.split(r"[-_.\s]+", stem.lower()) if t]
    for token in tokens[-1:] + tokens[:1]:
        # Only the first or last file-name token: inside names "de" is usually a preposition.
        if len(token) in (2, 3) and _lang_code(token):
            return _lang_code(token)
    for text in (info.anchor, info.title):
        # In running text only "(EN)", "[de]" or a bare upper-case "DE" count: "de" and "en" are also words.
        for token in _PAREN_CODE.findall(text.lower()) + _UPPER_CODE.findall(text):
            if _lang_code(token):
                return _lang_code(token)
    if term_lang:
        return term_lang
    directories = path.lower().rsplit("/", 1)[0] + "/"
    for source in (directories, urlsplit(info.page_url).path.lower() + "/" if info.page_url else ""):
        for token in _LANG_TOKEN.findall(source):
            if len(token) == 2 and _lang_code(token):
                return _lang_code(token)
    return info.page_lang if info.page_lang in LANG_CODES else None


def _annual_strength(text: str) -> tuple[int, str | None]:
    strength, lang = 0, None
    for folded, _rx, term_lang, term_strength in _find(ANNUAL, text):
        if term_strength > strength:
            strength, lang = term_strength, term_lang
    return strength, lang


def classify_report_link(info: LinkInfo, today: date | None = None) -> Guess:
    """Classify a link found on an investor-relations page."""
    today = today or date.today()
    parts = urlsplit(info.url)
    path = unquote(parts.path)
    filename = path.rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    primary = fold(" ".join((info.anchor, info.title, stem)))
    context = fold(" ".join((info.heading, info.context_before[-90:], info.page_title)))

    guess = Guess()
    strength, term_lang = _annual_strength(primary)
    short = SHORT_REPORT.search(fold(stem))
    if strength < 2 and short:
        strength, term_lang = 2, term_lang or SHORT_LANG.get(short.group(1))
    has = {name: any(True for _ in _find(terms, primary)) for name, terms in (
        ("interim", INTERIM), ("remuneration", REMUNERATION), ("governance", GOVERNANCE), ("agm", AGM),
        ("presentation", PRESENTATION), ("press", PRESS), ("sustainability", SUSTAINABILITY),
        ("single", SINGLE_ENTITY), ("single_weak", SINGLE_ENTITY_WEAK), ("group", GROUP))}
    if strength == 0 and not any(v for k, v in has.items() if k not in ("single_weak", "group")):
        # The link text is generic ("PDF", "Download", "2016"): fall back to the surrounding text.
        strength, term_lang = _annual_strength(context)
        strength = max(0, strength - 1) if strength == 3 else strength
        has = {name: any(True for _ in _find(terms, context)) for name, terms in (
            ("interim", INTERIM), ("remuneration", REMUNERATION), ("governance", GOVERNANCE), ("agm", AGM),
            ("presentation", PRESENTATION), ("press", PRESS), ("sustainability", SUSTAINABILITY),
            ("single", SINGLE_ENTITY), ("single_weak", SINGLE_ENTITY_WEAK), ("group", GROUP))}
        if strength or any(v for k, v in has.items() if k not in ("single_weak", "group")):
            guess.flags.add("from_context")

    if has["interim"]:
        guess.category = "interim_report"
    elif has["remuneration"]:
        guess.category = "remuneration_report"
    elif has["governance"] and strength < 3:
        guess.category = "governance_report"
    elif has["agm"]:
        guess.category = "agm"
    elif has["presentation"]:
        guess.category = "presentation"
    elif has["press"]:
        guess.category = "press_release"
    elif has["sustainability"] and strength < 3:
        guess.category = "sustainability_report"
    elif (has["single"] or (has["single_weak"] and strength < 3 and not has["group"])) \
            and not any(True for _ in _find(FULL, primary)):
        guess.category = "single_entity_statements"
    elif strength > 0:
        guess.category = "annual_report"
    guess.strength = strength

    if any(True for _ in _find(SUMMARY, primary)):
        guess.flags.add("summary")
    if strength == 3 and any(True for _ in _find(CHAPTER, primary)):
        # "Geschäftsbericht 2019 – Konzernabschluss" is a chapter unless it says "complete"
        if not any(True for _ in _find(FULL, primary)):
            guess.flags.add("chapter")
    if any(True for _ in _find(FULL, primary)):
        guess.flags.add("full")

    directories = path.rsplit("/", 1)[0]
    year, label, weight = pick_year([
        (info.anchor, 5.0, False), (info.title, 5.0, False), (stem, 4.0, False),
        (info.context_before[-160:], 3.0, True), (info.heading, 2.0, False),
        (info.context_after[:60], 1.5, False), (directories, 1.0, False), (info.page_title, 1.0, False),
    ], 1990, today.year + 1)
    guess.fiscal_year, guess.fy_label, guess.year_weight = year, label, weight
    guess.language = detect_language(info, term_lang)
    return guess


def score_report(guess: Guess, prefs: list[str]) -> float:
    """Rank candidates for the same fiscal year (higher is better)."""
    score = {3: 60.0, 2: 40.0, 1: 20.0}.get(guess.strength, 0.0)
    score += min(guess.year_weight, 5.5) * 4
    if guess.language in prefs:
        score += max(12 - 5 * prefs.index(guess.language), 2)
    elif guess.language is None:
        score += 3
    if "summary" in guess.flags:
        score -= 30
    if "chapter" in guess.flags:
        score -= 15
    if "full" in guess.flags:
        score += 5
    if "from_context" in guess.flags:
        score -= 5
    return round(score, 1)


# --- industry documents ------------------------------------------------------------------

INDUSTRY_TERMS = _terms([
    ("facts and figures", 30), ("facts & figures", 30), ("zahlen und fakten", 30), ("in zahlen", 30),
    ("in figures", 30), ("key figures", 20), ("kennzahlen", 20), ("industry report", 30), ("branchenbericht", 30),
    ("branchenreport", 30), ("marktbericht", 30), ("market report", 30), ("market outlook", 30),
    ("economic report", 30), ("wirtschaftsbericht", 30), ("statistical report", 30), ("statistik", 20),
    ("statistics", 20), ("statistical", 20), ("outlook", 20), ("ausblick", 15), ("konjunktur", 20),
    ("survey", 15), ("umfrage", 15), ("barometer", 20), ("monitor", 10), ("trends", 15), ("studie", 15),
    ("study", 15), ("annual report", 20), ("jahresbericht", 20), ("review", 10), ("report", 10),
    ("bericht", 10), ("overview", 8), ("white paper", 8), ("position paper", 5), ("analysis", 10),
    ("analyse", 10), ("data", 5), ("rapport", 10), ("relazione", 10), ("informe", 10), ("rapporto", 10),
])
INDUSTRY_NEGATIVE = _terms([
    "press release", "pressemitteilung", "agenda", "tagesordnung", "invitation", "einladung", "programme",
    "anmeldung", "registration form", "application form", "membership", "mitgliedschaft", "satzung", "statutes",
    "bylaws", "privacy", "datenschutz", "impressum", "terms and conditions", "agb", "cookie", "newsletter",
    "flyer", "karriere", "career", "vacancy", "job offer", "price list", "preisliste", "logo",
])


def classify_industry_link(info: LinkInfo, keywords: list[str], year_from: int,
                           today: date | None = None) -> tuple[float, int | None]:
    """Relevance score (>= 25 means worth downloading) and publication year of an industry document."""
    today = today or date.today()
    filename = unquote(urlsplit(info.url).path).rsplit("/", 1)[-1]
    primary = fold(" ".join((info.anchor, info.title, filename.rsplit(".", 1)[0])))
    context = fold(" ".join((info.heading, info.context_before[-80:], info.page_title)))
    score = 0.0
    matched = [w for _f, _rx, w in _find(INDUSTRY_TERMS, primary)]
    score += max(matched, default=0) + 2 * (len(matched) - 1 if matched else 0)
    if not matched:
        score += max((w for _f, _rx, w in _find(INDUSTRY_TERMS, context)), default=0) * 0.5
    if any(True for _ in _find(INDUSTRY_NEGATIVE, primary)):
        score -= 40
    text = primary + " " + context
    hits = sum(1 for kw in keywords if kw and fold(kw) in text)
    score += min(hits * 10, 30)
    year, _label, _w = pick_year([
        (info.anchor, 5.0, False), (info.title, 5.0, False), (filename, 4.0, False),
        (info.context_before[-120:], 3.0, True), (info.heading, 2.0, False), (info.context_after[:60], 1.5, False),
    ], 1990, today.year + 1)
    if year is not None:
        if year < year_from:
            score -= 50
        else:
            score += 5 + max(0, 5 - (today.year - year))
    return score, year
