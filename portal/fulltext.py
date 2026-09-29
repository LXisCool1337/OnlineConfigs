"""Full-text search across all downloaded reports (SQLite FTS5).

ESEF reports are XHTML and are always indexed. PDFs are indexed page by page when the
``pdftotext`` tool (poppler-utils) is installed; without it they are skipped and picked up
later by ``python -m portal index``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from html.parser import HTMLParser

CHUNK = 2500
MARK_START, MARK_END = "\u0002", "\u0003"
SKIP_TAGS = {"script", "style", "head", "ix:header", "noscript", "template"}


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag in ("p", "div", "tr", "li", "br", "h1", "h2", "h3", "h4", "td", "th", "section"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_text(path) -> str:
    parser = _TextParser()
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        while chunk := fh.read(1 << 20):
            parser.feed(chunk)
    parser.close()
    return " ".join("".join(parser.parts).split())


def chunks(text: str, size: int = CHUNK) -> list[str]:
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            space = text.rfind(" ", start + size // 2, end)
            end = space if space > start else end
        out.append(text[start:end].strip())
        start = end
    return [c for c in out if c]


def pdftotext_available() -> bool:
    return shutil.which("pdftotext") is not None


def pdf_pages(path) -> list[str] | None:
    tool = shutil.which("pdftotext")
    if not tool:
        return None
    result = subprocess.run([tool, "-enc", "UTF-8", "-q", str(path), "-"], capture_output=True, timeout=300)
    if result.returncode != 0:
        raise OSError(result.stderr.decode("utf-8", "replace")[:200] or f"pdftotext exit {result.returncode}")
    text = result.stdout.decode("utf-8", "replace")
    return [" ".join(page.split()) for page in text.split("\f")]


def index_document(db, library, doc: dict) -> str:
    """Extract and index one document; returns 'ok', 'empty', 'no_extractor' or 'error'."""
    try:
        path = library.absolute(doc["path"])  # PermissionError (an OSError) for a path outside the library
        if doc["mime"] in ("xhtml", "html"):
            pieces = [(None, c) for c in chunks(html_text(path))]
        elif doc["mime"] == "pdf":
            pages = pdf_pages(path)
            if pages is None:
                db.store_text(doc["id"], [], "no_extractor")
                return "no_extractor"
            pieces = []
            for number, page in enumerate(pages, 1):
                pieces += [(number, c) for c in chunks(page)]
        else:
            return "skipped"
    except (OSError, subprocess.SubprocessError, UnicodeError) as err:
        db.store_text(doc["id"], [], f"error: {err}"[:200])
        return "error"
    db.store_text(doc["id"], pieces, "ok" if pieces else "empty")
    return "ok" if pieces else "empty"


def index_pending(ctx, lei: str | None = None, nace: str | None = None) -> dict:
    counts: dict[str, int] = {}
    # PDFs stay pending until pdftotext is installed; without it, do not re-mark them on every run.
    docs = ctx.db.unindexed_documents(lei=lei, nace=nace, retry_no_extractor=pdftotext_available())
    for doc in docs:
        ctx.check_cancel()
        status = index_document(ctx.db, ctx.library, doc)
        counts[status] = counts.get(status, 0) + 1
    if docs:
        ctx.log("info", f"Volltext: {counts.get('ok', 0)} Dokumente indiziert"
                        + ("" if pdftotext_available() or not counts.get("no_extractor") else
                           f", {counts['no_extractor']} PDFs übersprungen (pdftotext nicht installiert)"))
    return counts


def fts_query(text: str) -> str | None:
    """User input -> safe FTS5 query: words AND-ed, "phrases" kept, word* as prefix, OR allowed.

    A token that the tokenizer splits into several words (E-Mobilität, COVID-19, 2024/25) becomes a
    phrase, so its parts must stand next to each other. A lone "*" or a doubled "**" never reaches FTS5.
    """
    parts = []
    for token in re.findall(r'"[^"]+"|\S+', text or ""):
        if token == "OR" and parts and parts[-1] != "OR":
            parts.append("OR")
            continue
        if token.startswith('"'):
            inner = " ".join(re.findall(r"\w+", token, re.UNICODE))
            if inner:
                parts.append(f'"{inner}"')
            continue
        words = re.findall(r"\w+", token, re.UNICODE)
        if words:
            parts.append(f'"{" ".join(words)}"' + ("*" if token.endswith("*") else ""))
    while parts and parts[-1] == "OR":
        parts.pop()
    return " ".join(parts) or None


def search(db, text: str, *, lei: str | None = None, nace: str | None = None, year_from: int | None = None,
           year_to: int | None = None, limit: int = 60) -> list[dict]:
    query = fts_query(text)
    if not query:
        return []
    sql = ("SELECT d.id, d.lei, d.nace, d.category, d.fiscal_year, d.fy_label, d.language, d.title, d.mime, "
           "t.page, snippet(doc_text, 0, char(2), char(3), ' … ', 24) AS snippet, bm25(doc_text) AS rank "
           "FROM doc_text t JOIN documents d ON d.id = t.doc_id WHERE doc_text MATCH ?")
    params: list = [query]
    if lei:
        sql += " AND d.lei = ?"
        params.append(lei)
    if nace:
        sql += " AND d.nace = ?"
        params.append(nace)
    if year_from:
        sql += " AND d.fiscal_year >= ?"
        params.append(int(year_from))
    if year_to:
        sql += " AND d.fiscal_year <= ?"
        params.append(int(year_to))
    sql += " ORDER BY rank LIMIT ?"
    params.append(int(limit))
    return db.query(sql, params)
