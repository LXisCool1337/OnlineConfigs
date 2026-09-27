"""Identifiers (ISIN, LEI), NACE helpers and country metadata for the EU/EEA universe."""

from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import DATA_DIR

EU = ("AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE",
      "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK")
EEA = ("IS", "LI", "NO")
EU_EEA = frozenset(EU + EEA)

COUNTRY_NAMES = {
    "AT": "Österreich", "BE": "Belgien", "BG": "Bulgarien", "CY": "Zypern", "CZ": "Tschechien",
    "DE": "Deutschland", "DK": "Dänemark", "EE": "Estland", "ES": "Spanien", "FI": "Finnland",
    "FR": "Frankreich", "GR": "Griechenland", "HR": "Kroatien", "HU": "Ungarn", "IE": "Irland",
    "IT": "Italien", "LT": "Litauen", "LU": "Luxemburg", "LV": "Lettland", "MT": "Malta",
    "NL": "Niederlande", "PL": "Polen", "PT": "Portugal", "RO": "Rumänien", "SE": "Schweden",
    "SI": "Slowenien", "SK": "Slowakei", "IS": "Island", "LI": "Liechtenstein", "NO": "Norwegen",
    "GB": "Vereinigtes Königreich", "CH": "Schweiz",
}

# Main reporting language per country (used for the "local" language preference).
COUNTRY_LANGUAGE = {
    "AT": "de", "BE": "nl", "BG": "bg", "CY": "el", "CZ": "cs", "DE": "de", "DK": "da", "EE": "et",
    "ES": "es", "FI": "fi", "FR": "fr", "GR": "el", "HR": "hr", "HU": "hu", "IE": "en", "IT": "it",
    "LT": "lt", "LU": "fr", "LV": "lv", "MT": "en", "NL": "nl", "PL": "pl", "PT": "pt", "RO": "ro",
    "SE": "sv", "SI": "sl", "SK": "sk", "IS": "is", "LI": "de", "NO": "no", "GB": "en", "CH": "de",
}

# Eurostat uses EL for Greece and UK for the United Kingdom.
EUROSTAT_GEO = {"GR": "EL", "GB": "UK"}

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
NACE_RE = re.compile(r"^(\d{2})(?:\.?(\d)(\d)?)?$")


def _digits(text: str) -> str:
    return "".join(str(int(ch, 36)) for ch in text)


def isin_check_digit(body: str) -> str:
    """Luhn check digit over the 11-character ISIN body (letters expanded to numbers)."""
    total = 0
    for i, ch in enumerate(reversed(_digits(body.upper()))):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def is_isin(text: str) -> bool:
    value = (text or "").strip().upper()
    return bool(ISIN_RE.match(value)) and isin_check_digit(value[:11]) == value[11]


def lei_check_digits(body: str) -> str:
    """ISO 17442 (ISO 7064 MOD 97-10) check digits for an 18-character LEI body."""
    return f"{98 - int(_digits(body.upper()) + '00') % 97:02d}"


def is_lei(text: str) -> bool:
    value = (text or "").strip().upper()
    return bool(LEI_RE.match(value)) and int(_digits(value)) % 97 == 1


def detect(query: str) -> tuple[str, str]:
    """Classify a search string as ('isin', ISIN), ('lei', LEI) or ('name', text)."""
    text = (query or "").strip()
    compact = re.sub(r"\s+", "", text).upper()
    if is_isin(compact):
        return "isin", compact
    if is_lei(compact):
        return "lei", compact
    return "name", text


def local_language(country: str | None) -> str | None:
    return COUNTRY_LANGUAGE.get((country or "").upper())


def language_preferences(prefs: list[str], country: str | None) -> list[str]:
    """Resolve "local" to the country's language and drop duplicates, keeping order."""
    out: list[str] = []
    for pref in prefs:
        code = local_language(country) if pref == "local" else pref.lower()
        if code and code not in out:
            out.append(code)
    return out or ["en"]


_TRAILING_LEGAL_FORMS = sorted(
    [
        "aktiengesellschaft", "ag & co. kgaa", "se & co. kgaa", "kgaa", "ag", "se", "s.e.", "sa", "s.a.",
        "n.v.", "nv", "sa/nv", "nv/sa", "s.p.a.", "spa", "plc", "p.l.c.", "oyj", "abp", "ab (publ)",
        "ab", "a/s", "asa", "as", "a.s.", "d.d.", "d.o.o.", "s.r.l.", "gmbh", "b.v.", "bv",
        "société anonyme", "societe anonyme", "public limited company", "limited", "ltd", "ltd.",
        "s.a.b.", "sgps", "s.g.p.s.",
    ],
    key=len,
    reverse=True,
)


def short_name(name: str) -> str:
    """'Krones Aktiengesellschaft' -> 'Krones' (used for web-search queries and matching)."""
    text = re.sub(r"\s+", " ", (name or "").strip())
    while True:
        low = text.lower()
        for form in _TRAILING_LEGAL_FORMS:
            if low.endswith(form) and len(low) > len(form) and low[-len(form) - 1] in " ,":
                text = text[: len(text) - len(form)].rstrip(" ,")
                break
        else:
            break
    return text or (name or "").strip()


# --- NACE Rev. 2 ------------------------------------------------------------------------

_SECTIONS = [
    ("A", 1, 3), ("B", 5, 9), ("C", 10, 33), ("D", 35, 35), ("E", 36, 39), ("F", 41, 43),
    ("G", 45, 47), ("H", 49, 53), ("I", 55, 56), ("J", 58, 63), ("K", 64, 66), ("L", 68, 68),
    ("M", 69, 75), ("N", 77, 82), ("O", 84, 84), ("P", 85, 85), ("Q", 86, 88), ("R", 90, 93),
    ("S", 94, 96), ("T", 97, 98), ("U", 99, 99),
]


def normalize_nace(code: str | None) -> str | None:
    """'28', '28.2', '28.29', 'C28', 'C2829' -> '28', '28.2', '28.29'; invalid -> None."""
    if not code:
        return None
    text = str(code).strip().upper().replace(" ", "")
    if text[:1].isalpha():
        text = text[1:]
    m = NACE_RE.match(text)
    if not m or nace_section(m.group(1)) is None:
        return None
    division, group, cls = m.groups()
    if group is None:
        return division
    return f"{division}.{group}{cls or ''}"


def nace_division(code: str) -> str:
    return code[:2]


def nace_section(code: str) -> str | None:
    try:
        division = int(str(code)[:2])
    except ValueError:
        return None
    for letter, lo, hi in _SECTIONS:
        if lo <= division <= hi:
            return letter
    return None


def eurostat_nace(code: str) -> str:
    """NACE code in Eurostat notation: '28' -> 'C28', '28.29' -> 'C2829'."""
    return f"{nace_section(code)}{code.replace('.', '')}"


@lru_cache(maxsize=1)
def nace_divisions() -> list[dict]:
    with (DATA_DIR / "nace_rev2.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def nace_label(code: str | None, lang: str = "de") -> str:
    if not code:
        return ""
    for row in nace_divisions():
        if row["code"] == nace_division(code):
            return row[lang]
    return ""
