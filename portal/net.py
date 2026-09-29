"""Polite HTTP client: per-host throttling, retries with backoff, robots.txt and streaming downloads."""

from __future__ import annotations

import gzip
import hashlib
import http.client
import io
import json
import math
import os
import random
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import __version__

PRODUCT = "EU-Report-Portal"
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class HttpError(Exception):
    def __init__(self, url: str, status: int = 0, reason: str = ""):
        label = f"HTTP {status}" if status else "Netzwerkfehler"
        super().__init__(f"{label}: {reason} <{url}>" if reason else f"{label} <{url}>")
        self.url, self.status, self.reason = url, status, reason


class BlockedByRobots(Exception):
    def __init__(self, url: str):
        super().__init__(f"robots.txt erlaubt keinen Abruf: {url}")
        self.url = url


class ContentError(Exception):
    """The response is not what was expected (wrong type, too large, empty)."""


@dataclass
class Response:
    url: str
    status: int
    headers: dict
    body: bytes

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    def text(self) -> str:
        charset = None
        m = re.search(r"charset=([\w.:-]+)", self.headers.get("content-type", ""), re.I)
        if m:
            charset = m.group(1)
        else:
            m = re.search(rb"<meta[^>]+charset=[\"']?([\w.:-]+)", self.body[:4096], re.I)
            if m:
                charset = m.group(1).decode("ascii", "ignore")
        for enc in (charset, "utf-8"):
            if not enc:
                continue
            try:
                return self.body.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
        return self.body.decode("cp1252", errors="replace")

    def json(self):
        return json.loads(self.body.decode("utf-8-sig"))


@dataclass
class Download:
    url: str
    path: Path
    size: int
    sha256: str
    kind: str
    content_type: str


def sniff(head: bytes, content_type: str = "") -> str:
    """Identify a payload by its first bytes: pdf, zip, gzip, xhtml, html, xml, json, csv or other."""
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    if head.startswith(b"%PDF-") or b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    low = head.lstrip().lower()
    if low.startswith(b"<?xml"):
        return "xhtml" if b"<html" in low else "xml"
    if low.startswith(b"<!doctype html") or low.startswith(b"<html"):
        return "html"
    if low[:1] in (b"{", b"["):
        return "json"
    if "csv" in content_type:
        return "csv"
    return "other"


def _retry_after(headers) -> float | None:
    value = headers.get("Retry-After") if headers else None
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError):
            return None
    if not math.isfinite(seconds):
        return None
    return max(0.0, min(seconds, 120.0))  # time.sleep() refuses negative values


def _read_capped(resp, limit: int, *, truncate: bool = False) -> bytes:
    chunks, size = [], 0
    while True:
        chunk = resp.read(1 << 16)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            if truncate:
                chunks.append(chunk[: len(chunk) - (size - limit)])
                break
            raise ContentError(f"Antwort größer als {limit // 1_000_000} MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _inflate(raw: bytes, wbits: int, limit: int) -> bytes:
    return zlib.decompressobj(wbits).decompress(raw, limit + 1)  # bounded: no deflate bomb


def _decode_body(raw: bytes, encoding: str, limit: int) -> bytes:
    encoding = (encoding or "").lower()
    try:
        if encoding in ("gzip", "x-gzip"):
            data = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(limit + 1)
        elif encoding == "deflate":
            try:
                data = _inflate(raw, zlib.MAX_WBITS, limit)
            except zlib.error:
                data = _inflate(raw, -zlib.MAX_WBITS, limit)  # raw deflate without zlib header
        else:
            return raw
    except (OSError, EOFError, zlib.error) as err:
        raise ContentError(f"Antwort nicht dekomprimierbar ({encoding}): {err}") from None
    if len(data) > limit:
        raise ContentError(f"Antwort größer als {limit // 1_000_000} MB")
    return data


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower().rsplit("@", 1)[-1]


class HttpClient:
    def __init__(self, settings, opener=None):
        self.s = settings
        self.robots_agent = PRODUCT
        self._opener = opener or urllib.request.build_opener()
        self._guard = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._next_slot: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._robots_locks: dict[str, threading.Lock] = {}
        self.stats = {"requests": 0, "bytes": 0}

    def _count(self, key: str, amount: int) -> None:
        with self._guard:  # updated from several download threads at once
            self.stats[key] += amount

    @property
    def user_agent(self) -> str:
        contact = self.s.contact_email.strip() or "contact-not-configured"
        return f"{PRODUCT}/{__version__} (research tool; contact: {contact})"

    # --- throttling -------------------------------------------------------------------

    def _interval(self, netloc: str, scheme: str) -> float:
        hostname = netloc.split(":")[0] if netloc.count(":") == 1 else netloc
        rates = self.s.host_rates or {}
        interval = None
        for key in (netloc, hostname):
            if key in rates:
                interval = float(rates[key])
                break
        if interval is None:
            for key, value in rates.items():
                if hostname.endswith("." + key):
                    interval = float(value)
                    break
        if interval is None:
            interval = float(self.s.default_rate)
        rp = self._robots.get(f"{scheme}://{netloc}")
        if rp is not None:
            delay = rp.crawl_delay(self.robots_agent)
            if delay:
                interval = max(interval, min(float(delay), 30.0))
        return interval

    def _wait_turn(self, url: str) -> None:
        parts = urllib.parse.urlsplit(url)
        netloc = parts.netloc.lower()
        with self._guard:
            lock = self._host_locks.setdefault(netloc, threading.Lock())
        with lock:
            now = time.monotonic()
            slot = self._next_slot.get(netloc, 0.0)
            if slot > now:
                time.sleep(slot - now)
            self._next_slot[netloc] = time.monotonic() + self._interval(netloc, parts.scheme)

    def _backoff(self, attempt: int, retry_after: float | None) -> None:
        if retry_after is not None:
            time.sleep(retry_after)
        else:
            time.sleep(self.s.backoff_base * (2 ** attempt) + random.uniform(0, self.s.backoff_base / 2))

    # --- requests ---------------------------------------------------------------------

    def _open(self, url: str, *, headers: dict | None = None, data: bytes | None = None,
              method: str = "GET", timeout: float | None = None, check_robots: bool = False):
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            raise HttpError(url, 0, "nur http(s) erlaubt")
        if check_robots and not self.allowed(url):
            raise BlockedByRobots(url)
        hdrs = {"User-Agent": self.user_agent, "Accept-Language": "en, de;q=0.8, *;q=0.5"}
        hdrs.update(headers or {})
        attempt = 0
        while True:
            self._wait_turn(url)
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            try:
                resp = self._opener.open(req, timeout=timeout or self.s.timeout)
                self._count("requests", 1)
                return resp
            except urllib.error.HTTPError as err:
                retry_after = _retry_after(err.headers)
                try:
                    detail = err.read(300).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001 - best effort only
                    detail = ""
                err.close()
                if err.code in RETRY_STATUS and attempt < self.s.retries:
                    self._backoff(attempt, retry_after)
                    attempt += 1
                    continue
                raise HttpError(url, err.code, " ".join((err.reason or "", detail)).strip()[:300]) from None
            except (urllib.error.URLError, http.client.HTTPException, socket.timeout, TimeoutError,
                    ConnectionError, ssl.SSLError) as err:
                reason = str(getattr(err, "reason", err))
                # A proxy that refuses the tunnel is a policy decision; retrying will not help.
                if "Tunnel connection failed: 40" in reason or attempt >= self.s.retries:
                    raise HttpError(url, 0, reason) from None
                self._backoff(attempt, None)
                attempt += 1

    def get(self, url: str, *, params: dict | list | None = None, accept: str = "*/*",
            headers: dict | None = None, check_robots: bool = False, max_bytes: int = 30_000_000,
            timeout: float | None = None, html_only: bool = False) -> Response:
        if params:
            query = urllib.parse.urlencode(params, doseq=True, quote_via=urllib.parse.quote)
            url = f"{url}{'&' if '?' in url else '?'}{query}"
        hdrs = {"Accept": accept, "Accept-Encoding": "gzip"}
        hdrs.update(headers or {})
        with self._open(url, headers=hdrs, check_robots=check_robots, timeout=timeout) as resp:
            final = resp.geturl()
            if check_robots and final != url and not self.allowed(final):
                raise BlockedByRobots(final)
            header_map = {k.lower(): v for k, v in resp.headers.items()}
            ctype = header_map.get("content-type", "").lower()
            if html_only and ctype and not any(t in ctype for t in ("html", "xml", "text/plain")):
                return Response(final, resp.status, header_map, b"")
            raw = _read_capped(resp, max_bytes, truncate=html_only)
        body = _decode_body(raw, header_map.get("content-encoding", ""), max_bytes)
        self._count("bytes", len(raw))
        return Response(final, resp.status, header_map, body)

    def get_json(self, url: str, *, params=None, headers: dict | None = None, timeout: float | None = None):
        return self.get(url, params=params, accept="application/json", headers=headers, timeout=timeout).json()

    def download(self, url: str, dest: Path, *, expect: tuple[str, ...] | None = ("pdf",),
                 check_robots: bool = True, max_bytes: int | None = None) -> Download:
        """Stream ``url`` to ``dest``; verifies type by magic bytes and returns size and SHA-256."""
        limit = max_bytes or self.s.max_file_mb * 1024 * 1024
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        for attempt in range(2):
            try:
                with self._open(url, headers={"Accept": "*/*", "Accept-Encoding": "identity"},
                                check_robots=check_robots) as resp:
                    final = resp.geturl()
                    if check_robots and final != url and not self.allowed(final):
                        raise BlockedByRobots(final)
                    declared = resp.headers.get("Content-Length", "")
                    if declared.isdigit() and int(declared) > limit:
                        raise ContentError(f"Datei zu groß ({int(declared) // 1_048_576} MB)")
                    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    digest, size, head = hashlib.sha256(), 0, b""
                    with open(tmp, "wb") as fh:
                        while True:
                            chunk = resp.read(1 << 16)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > limit:
                                raise ContentError(f"Datei größer als {limit // 1_048_576} MB")
                            if len(head) < 8192:
                                head += chunk[: 8192 - len(head)]
                            digest.update(chunk)
                            fh.write(chunk)
                if size == 0:
                    raise ContentError("leere Datei")
                kind = sniff(head, ctype)
                if expect and kind not in expect:
                    raise ContentError(f"unerwarteter Inhalt: {kind} ({ctype or 'ohne Content-Type'})")
                os.replace(tmp, dest)
                self._count("bytes", size)
                return Download(final, dest, size, digest.hexdigest(), kind, ctype)
            except (http.client.IncompleteRead, ConnectionError, socket.timeout, TimeoutError) as err:
                if attempt == 1:
                    raise HttpError(url, 0, f"Übertragung abgebrochen: {err}") from None
            finally:
                tmp.unlink(missing_ok=True)
        raise HttpError(url, 0, "Download fehlgeschlagen")

    # --- robots.txt -------------------------------------------------------------------

    def _robots_for(self, origin: str) -> urllib.robotparser.RobotFileParser:
        with self._guard:
            lock = self._robots_locks.setdefault(origin, threading.Lock())
        with lock:
            rp = self._robots.get(origin)
            if rp is not None:
                return rp
            rp = urllib.robotparser.RobotFileParser(origin + "/robots.txt")
            try:
                resp = self.get(origin + "/robots.txt", accept="text/plain", max_bytes=500_000, timeout=20)
                rp.parse(resp.text().splitlines())
            except HttpError as err:
                if err.status in (401, 403):
                    rp.disallow_all = True
                elif 400 <= err.status < 500:
                    rp.allow_all = True       # no robots.txt: everything allowed
                else:
                    rp.disallow_all = True    # server error or unreachable: do not crawl
            except ContentError:
                rp.allow_all = True
            rp.modified()
            self._robots[origin] = rp
            return rp

    def allowed(self, url: str) -> bool:
        if not self.s.respect_robots:
            return True
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return False
        rp = self._robots_for(f"{parts.scheme}://{parts.netloc.lower()}")
        return rp.can_fetch(self.robots_agent, url)

    def sitemaps(self, url: str) -> list[str]:
        parts = urllib.parse.urlsplit(url)
        rp = self._robots_for(f"{parts.scheme}://{parts.netloc.lower()}")
        return list(rp.site_maps() or [])
