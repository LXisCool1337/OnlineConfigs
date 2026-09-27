"""SQLite catalogue: companies, securities (the EU universe), documents, jobs and settings."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    lei TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    isins TEXT NOT NULL DEFAULT '[]',
    website TEXT,
    ir_url TEXT,
    nace TEXT,
    keywords TEXT,
    wikidata TEXT,
    industries TEXT NOT NULL DEFAULT '[]',
    has_esef INTEGER NOT NULL DEFAULT 0,
    listed INTEGER NOT NULL DEFAULT 0,
    watch INTEGER NOT NULL DEFAULT 0,
    meta TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS securities (
    isin TEXT PRIMARY KEY,
    lei TEXT,
    name TEXT,
    cfi TEXT,
    currency TEXT,
    mic TEXT,
    issuer_requested INTEGER,
    first_trade TEXT,
    termination TEXT,
    authority TEXT,
    source TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS securities_lei ON securities(lei);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    scope TEXT NOT NULL,
    lei TEXT,
    nace TEXT,
    category TEXT NOT NULL,
    fiscal_year INTEGER,
    fy_label TEXT,
    period_end TEXT,
    language TEXT,
    title TEXT,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    path TEXT,
    sha256 TEXT,
    size INTEGER,
    mime TEXT,
    score REAL,
    meta TEXT NOT NULL DEFAULT '{}',
    job_id INTEGER,
    created_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS documents_url
    ON documents(scope, source_url, IFNULL(lei, ''), IFNULL(nace, ''));
CREATE INDEX IF NOT EXISTS documents_lei ON documents(lei);
CREATE INDEX IF NOT EXISTS documents_nace ON documents(nace);
CREATE INDEX IF NOT EXISTS documents_sha ON documents(sha256);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    stage TEXT,
    parent_id INTEGER,
    created_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    summary TEXT NOT NULL DEFAULT '{}',
    error TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    ts TEXT,
    level TEXT,
    message TEXT,
    data TEXT
);
CREATE INDEX IF NOT EXISTS job_events_job ON job_events(job_id, id);
CREATE TABLE IF NOT EXISTS industry_sources (
    id INTEGER PRIMARY KEY,
    nace TEXT NOT NULL,
    name TEXT,
    url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(nace, url)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS company_fts USING fts5(
    lei UNINDEXED, name, isins, tokenize = 'unicode61 remove_diacritics 2'
);
"""

JSON_COLUMNS = {"isins", "industries", "meta", "params", "summary", "data"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key in JSON_COLUMNS & out.keys():
        if isinstance(out[key], str):
            try:
                out[key] = json.loads(out[key])
            except ValueError:
                pass
    return out


def _encode(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value


class Database:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- primitives --------------------------------------------------------------------

    def execute(self, sql: str, params=()) -> int:
        with self._lock:
            return self._conn.execute(sql, params).lastrowid

    def query(self, sql: str, params=()) -> list[dict]:
        with self._lock:
            return [_decode(r) for r in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        with self._lock:
            return _decode(self._conn.execute(sql, params).fetchone())

    @contextmanager
    def transaction(self):
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    # --- companies ---------------------------------------------------------------------

    def company(self, lei: str) -> dict | None:
        return self.one("SELECT * FROM companies WHERE lei = ?", (lei,))

    def upsert_company(self, data: dict) -> dict:
        """Merge ``data`` into the company row. Empty values never erase known ones."""
        lei = data["lei"]
        with self._lock:
            current = self.company(lei) or {"lei": lei, "name": data.get("name") or lei, "isins": [],
                                             "industries": [], "meta": {}}
            for key, value in data.items():
                if key == "isins":
                    current["isins"] = sorted(set(current.get("isins") or []) | set(value or []))
                elif key == "meta":
                    current["meta"] = {**(current.get("meta") or {}), **(value or {})}
                elif key in ("has_esef", "listed"):
                    current[key] = 1 if (value or current.get(key)) else 0
                elif value not in (None, "", []):
                    current[key] = value
            current["updated_at"] = now_iso()
            self._write_company(current)
            return current

    def update_company_fields(self, lei: str, fields: dict) -> dict | None:
        """Explicit edits from the UI; empty strings clear a field."""
        allowed = {"ir_url", "website", "nace", "keywords", "watch"}
        with self._lock:
            current = self.company(lei)
            if not current:
                return None
            for key, value in fields.items():
                if key in allowed:
                    current[key] = (1 if value else 0) if key == "watch" else (value or None)
            current["updated_at"] = now_iso()
            self._write_company(current)
            return current

    def _write_company(self, c: dict) -> None:
        cols = ["lei", "name", "country", "isins", "website", "ir_url", "nace", "keywords", "wikidata",
                "industries", "has_esef", "listed", "watch", "meta", "updated_at"]
        values = [_encode(c.get(k)) if k not in ("has_esef", "listed", "watch") else int(c.get(k) or 0)
                  for k in cols]
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{k} = excluded.{k}" for k in cols[1:])
        self._conn.execute(
            f"INSERT INTO companies ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(lei) DO UPDATE SET {updates}", values)
        self._conn.execute("DELETE FROM company_fts WHERE lei = ?", (c["lei"],))
        self._conn.execute("INSERT INTO company_fts (lei, name, isins) VALUES (?, ?, ?)",
                           (c["lei"], c.get("name") or "", " ".join(c.get("isins") or [])))

    def search_companies(self, text: str, limit: int = 20) -> list[dict]:
        tokens = re.findall(r"\w+", text or "", re.UNICODE)
        if not tokens:
            return []
        match = " ".join(f'"{t}"*' for t in tokens[:8])
        return self.query(
            "SELECT c.* FROM company_fts f JOIN companies c ON c.lei = f.lei "
            "WHERE company_fts MATCH ? ORDER BY c.listed DESC, bm25(company_fts) LIMIT ?", (match, limit))

    def company_by_isin(self, isin: str) -> dict | None:
        row = self.one("SELECT lei FROM securities WHERE isin = ? AND lei IS NOT NULL", (isin,))
        if row:
            return self.company(row["lei"])
        return self.one("SELECT * FROM companies WHERE isins LIKE ?", (f'%"{isin}"%',))

    def companies_with_nace(self, division: str, limit: int = 200) -> list[dict]:
        return self.query("SELECT * FROM companies WHERE substr(nace, 1, 2) = ? ORDER BY has_esef DESC, name "
                          "LIMIT ?", (division, limit))

    def library_companies(self) -> list[dict]:
        return self.query(
            "SELECT c.*, COUNT(d.id) AS documents, "
            "COUNT(DISTINCT CASE WHEN d.category IN ('annual_report', 'single_entity_statements', "
            "'esef_report', 'esef_package') THEN d.fiscal_year END) AS years "
            "FROM companies c JOIN documents d ON d.lei = c.lei AND d.scope = 'company' "
            "GROUP BY c.lei ORDER BY c.name")

    def library_industries(self) -> list[dict]:
        return self.query("SELECT nace, COUNT(*) AS documents, MAX(created_at) AS updated_at FROM documents "
                          "WHERE scope = 'industry' GROUP BY nace ORDER BY nace")

    # --- documents ---------------------------------------------------------------------

    def add_document(self, doc: dict) -> int | None:
        cols = ["scope", "lei", "nace", "category", "fiscal_year", "fy_label", "period_end", "language",
                "title", "source", "source_url", "path", "sha256", "size", "mime", "score", "meta", "job_id",
                "created_at"]
        doc = {**doc, "created_at": doc.get("created_at") or now_iso(), "meta": doc.get("meta") or {}}
        try:
            return self.execute(f"INSERT INTO documents ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                                [_encode(doc.get(c)) for c in cols])
        except sqlite3.IntegrityError:
            return None

    def document(self, doc_id: int) -> dict | None:
        return self.one("SELECT * FROM documents WHERE id = ?", (doc_id,))

    def find_document(self, scope: str, url: str, lei: str | None, nace: str | None) -> dict | None:
        return self.one("SELECT * FROM documents WHERE scope = ? AND source_url = ? AND IFNULL(lei, '') = ? "
                        "AND IFNULL(nace, '') = ?", (scope, url, lei or "", nace or ""))

    def find_by_hash(self, scope: str, sha256: str, lei: str | None, nace: str | None) -> dict | None:
        return self.one("SELECT * FROM documents WHERE scope = ? AND sha256 = ? AND IFNULL(lei, '') = ? "
                        "AND IFNULL(nace, '') = ?", (scope, sha256, lei or "", nace or ""))

    def company_documents(self, lei: str) -> list[dict]:
        return self.query("SELECT * FROM documents WHERE scope = 'company' AND lei = ? "
                          "ORDER BY fiscal_year DESC, category, language", (lei,))

    def industry_documents(self, nace: str) -> list[dict]:
        return self.query("SELECT * FROM documents WHERE scope = 'industry' AND nace = ? "
                          "ORDER BY category, fiscal_year DESC, title", (nace,))

    def delete_document(self, doc_id: int) -> None:
        self.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    # --- jobs --------------------------------------------------------------------------

    def create_job(self, kind: str, title: str, params: dict, parent_id: int | None = None,
                   status: str = "queued") -> int:
        return self.execute("INSERT INTO jobs (kind, title, params, status, parent_id, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (kind, title, _encode(params), status, parent_id, now_iso()))

    def job(self, job_id: int) -> dict | None:
        return self.one("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def jobs(self, limit: int = 50) -> list[dict]:
        return self.query("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))

    def claim_job(self) -> dict | None:
        with self._lock:
            row = self.one("SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1")
            if row:
                self._conn.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                                   (now_iso(), row["id"]))
                row["status"] = "running"
            return row

    def update_job(self, job_id: int, **values) -> None:
        if not values:
            return
        cols = ", ".join(f"{k} = ?" for k in values)
        self.execute(f"UPDATE jobs SET {cols} WHERE id = ?", [_encode(v) for v in values.values()] + [job_id])

    def requeue_interrupted(self) -> int:
        with self._lock:
            return self._conn.execute("UPDATE jobs SET status = 'queued' WHERE status IN ('running', 'cancelling')"
                                      ).rowcount

    def add_event(self, job_id: int, level: str, message: str, data: dict | None = None) -> int:
        return self.execute("INSERT INTO job_events (job_id, ts, level, message, data) VALUES (?, ?, ?, ?, ?)",
                            (job_id, now_iso(), level, message, _encode(data or {})))

    def job_events(self, job_id: int, after: int = 0, limit: int = 1000) -> list[dict]:
        return self.query("SELECT * FROM job_events WHERE job_id = ? AND id > ? ORDER BY id LIMIT ?",
                          (job_id, after, limit))

    # --- industry sources and settings -------------------------------------------------

    def industry_sources(self, division: str) -> list[dict]:
        return self.query("SELECT * FROM industry_sources WHERE (nace = ? OR nace = '*') AND enabled = 1 "
                          "ORDER BY id", (division,))

    def all_industry_sources(self) -> list[dict]:
        return self.query("SELECT * FROM industry_sources ORDER BY nace, id")

    def add_industry_source(self, nace: str, name: str, url: str) -> int | None:
        try:
            return self.execute("INSERT INTO industry_sources (nace, name, url) VALUES (?, ?, ?)", (nace, name, url))
        except sqlite3.IntegrityError:
            return None

    def delete_industry_source(self, source_id: int) -> None:
        self.execute("DELETE FROM industry_sources WHERE id = ?", (source_id,))

    def load_settings(self) -> dict:
        out = {}
        for row in self.query("SELECT key, value FROM settings"):
            try:
                out[row["key"]] = json.loads(row["value"])
            except ValueError:
                out[row["key"]] = row["value"]
        return out

    def save_settings(self, values: dict) -> None:
        with self.transaction():
            for key, value in values.items():
                self._conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                   (key, json.dumps(value, ensure_ascii=False)))

    # --- universe ----------------------------------------------------------------------

    def upsert_securities(self, rows: list[dict]) -> None:
        cols = ["isin", "lei", "name", "cfi", "currency", "mic", "issuer_requested", "first_trade", "termination",
                "authority", "source", "updated_at"]
        stamp = now_iso()
        with self.transaction():
            self._conn.executemany(
                f"INSERT INTO securities ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                f"ON CONFLICT(isin) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in cols[1:])}",
                [[r.get(c) if c != "updated_at" else stamp for c in cols] for r in rows])

    def universe_stats(self) -> dict:
        return {
            "companies": self.one("SELECT COUNT(*) AS n FROM companies")["n"],
            "listed": self.one("SELECT COUNT(*) AS n FROM companies WHERE listed = 1")["n"],
            "with_esef": self.one("SELECT COUNT(*) AS n FROM companies WHERE has_esef = 1")["n"],
            "securities": self.one("SELECT COUNT(*) AS n FROM securities")["n"],
            "by_country": self.query("SELECT country, COUNT(*) AS n FROM companies WHERE listed = 1 "
                                     "GROUP BY country ORDER BY n DESC"),
        }

    def universe_companies(self, countries: list[str] | None = None, esef_only: bool = False,
                           limit: int = 100000) -> list[dict]:
        sql = "SELECT * FROM companies WHERE listed = 1"
        params: list = []
        if countries:
            sql += f" AND country IN ({', '.join('?' for _ in countries)})"
            params += countries
        if esef_only:
            sql += " AND has_esef = 1"
        sql += " ORDER BY country, name LIMIT ?"
        return self.query(sql, params + [limit])
