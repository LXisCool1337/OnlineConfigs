"""A small, polite site crawler that finds document links together with their context.

Stays on the start site(s), follows only links that look relevant (investor relations,
publications), honours robots.txt and crawl-delay, reads sitemaps, and caps pages per site.
Documents linked from these pages may live on other hosts (CDNs); they are returned but never crawled.
"""

from __future__ import annotations

import gzip
import heapq
import ipaddress
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

from ..classify import LinkInfo, fold
from ..net import BlockedByRobots, ContentError, HttpError, host_of

SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".css", ".js", ".mp4", ".mp3", ".mov",
            ".avi", ".zip", ".xls", ".xlsx", ".doc", ".docx", ".ppt", ".pptx", ".ics", ".vcf", ".xml", ".json",
            ".rss", ".woff", ".woff2", ".ttf", ".exe", ".dmg")
DOC_RE = re.compile(r"\.pdf(?:$|[?#])|[?&](?:format|type)=pdf", re.I)
ONCLICK_PDF = re.compile(r"['\"]([^'\"]+\.pdf[^'\"]*)['\"]", re.I)


def looks_like_document(url: str) -> bool:
    return bool(DOC_RE.search(url))


def registrable_domain(host: str) -> str:
    host = host.split(":")[0].lower().strip(".")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in ("co", "com", "org", "net", "gov", "ac", "or"):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


class LinkParser(HTMLParser):
    """Collects links with anchor text, the nearest heading and the text around them."""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.links: list[dict] = []
        self.text: list[str] = []
        self.length = 0
        self.heading = ""
        self.page_title = ""
        self.lang: str | None = None
        self._anchor: dict | None = None
        self._heading_tag: str | None = None
        self._heading_buf: list[str] = []
        self._in_title = False
        self._skip = 0

    def _push(self, data: str) -> None:
        self.text.append(data)
        self.length += len(data)

    def _add(self, href: str, title: str = "", text: str = "") -> None:
        href = (href or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            return
        url = urldefrag(urljoin(self.base, href))[0]
        if urlsplit(url).scheme not in ("http", "https"):
            return
        self.links.append({"url": url, "title": title, "anchor": text, "start": self.length, "end": self.length,
                           "heading": self.heading})

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"][:2].lower()
        elif tag == "base" and a.get("href"):
            self.base = urljoin(self.base, a["href"])
        if tag in ("script", "style", "noscript", "template", "svg"):
            self._skip += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading_tag, self._heading_buf = tag, []
        elif tag in ("a", "option") and (a.get("href") or (tag == "option" and looks_like_document(a.get("value", "")))):
            href = a.get("href") or a.get("value")
            self._anchor = {"href": href, "title": a.get("title") or a.get("aria-label") or "",
                            "start": self.length, "text": [], "heading": self.heading}
        elif tag == "img" and self._anchor is not None and a.get("alt"):
            self._anchor["text"].append(" " + a["alt"] + " ")
        for key in ("data-href", "data-url", "data-src", "data-file", "data-download"):
            if a.get(key) and looks_like_document(a[key]):
                self._add(a[key], a.get("title", ""))
        if a.get("onclick"):
            for match in ONCLICK_PDF.findall(a["onclick"]):
                self._add(match, a.get("title", ""))
        if tag in ("br", "p", "div", "li", "tr", "td", "th", "section", "article", "dd", "dt"):
            self._push(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template", "svg"):
            self._skip = max(0, self._skip - 1)
            return
        if tag == "title":
            self._in_title = False
        elif tag == self._heading_tag:
            self.heading = " ".join("".join(self._heading_buf).split())[:200]
            self._heading_tag = None
        elif tag in ("a", "option") and self._anchor is not None:
            anchor = self._anchor
            self._anchor = None
            url = urldefrag(urljoin(self.base, anchor["href"].strip()))[0]
            if urlsplit(url).scheme in ("http", "https"):
                self.links.append({"url": url, "title": anchor["title"],
                                   "anchor": " ".join("".join(anchor["text"]).split()),
                                   "start": anchor["start"], "end": self.length, "heading": anchor["heading"]})
        if tag in ("p", "div", "li", "tr", "td", "th"):
            self._push(" ")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.page_title += data
        if self._heading_tag:
            self._heading_buf.append(data)
        if self._anchor is not None:
            self._anchor["text"].append(data)
        self._push(data)

    def link_infos(self, page_url: str) -> list[LinkInfo]:
        full = "".join(self.text)
        out = []
        for link in self.links:
            before = " ".join(full[max(0, link["start"] - 240):link["start"]].split())
            after = " ".join(full[link["end"]:link["end"] + 120].split())
            out.append(LinkInfo(url=link["url"], anchor=link["anchor"], title=link["title"], context_before=before,
                                context_after=after, heading=link["heading"],
                                page_title=" ".join(self.page_title.split())[:200], page_url=page_url,
                                page_lang=self.lang))
        return out


def parse_html(html: str, url: str) -> list[LinkInfo]:
    parser = LinkParser(url)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed HTML: keep what was parsed
        pass
    return parser.link_infos(url)


class SiteCrawler:
    def __init__(self, ctx, *, hints: list[tuple[str, float]], max_pages: int, max_depth: int,
                 guess_paths: tuple[str, ...] = (), use_sitemaps: bool = True):
        self.ctx = ctx
        self.hints = [(fold(term), weight) for term, weight in hints]
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.guess_paths = guess_paths
        self.use_sitemaps = use_sitemaps
        self.pages_fetched = 0
        self.blocked: list[str] = []

    def priority(self, url: str, anchor: str = "") -> float:
        text = " " + fold(urlsplit(url).path + " " + urlsplit(url).query + " " + anchor) + " "
        return sum(weight for term, weight in self.hints if f" {term}" in text or (len(term) > 4 and term in text))

    def crawl(self, seeds: list[str]) -> dict[str, list[LinkInfo]]:
        """Crawl from ``seeds``; returns document URL -> every place it was linked from."""
        seeds = [s for s in dict.fromkeys(seeds) if s]
        domains = {registrable_domain(host_of(s)) for s in seeds}
        hosts = {host_of(s) for s in seeds}

        def on_site(url: str) -> bool:
            host = host_of(url)
            if host in hosts:
                return True
            hostname = host.split(":")[0]
            try:
                ipaddress.ip_address(hostname)
                return False  # IP-based sites: exact host:port only
            except ValueError:
                return registrable_domain(host) in domains

        frontier: list[tuple[float, int, str, int]] = []
        counter = 0
        queued: set[str] = set()
        via: dict[str, LinkInfo] = {}  # the link that led to a page, kept in case it turns out to be a PDF

        def push(url: str, depth: int, prio: float, info: LinkInfo | None = None) -> None:
            nonlocal counter
            url = urldefrag(url)[0]
            if url in queued or not on_site(url) or urlsplit(url).path.lower().endswith(SKIP_EXT):
                return
            queued.add(url)
            if info is not None:
                via[url] = info
            counter += 1
            heapq.heappush(frontier, (-prio, counter, url, depth))

        for seed in seeds:
            push(seed, 0, 100.0)
        for seed in seeds:
            base = f"{urlsplit(seed).scheme}://{urlsplit(seed).netloc}"
            for path in self.guess_paths:
                push(base + path, 1, 0.5)

        documents: dict[str, list[LinkInfo]] = {}
        if self.use_sitemaps:
            for seed in seeds[:2]:
                for info in self._sitemap_links(seed, on_site):
                    if looks_like_document(info.url):
                        documents.setdefault(info.url, []).append(info)
                    else:
                        prio = self.priority(info.url)
                        if prio >= 4:
                            push(info.url, 1, prio)

        while frontier and self.pages_fetched < self.max_pages:
            self.ctx.check_cancel()
            neg_prio, _, url, depth = heapq.heappop(frontier)
            try:
                resp = self.ctx.http.get(url, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.3",
                                         check_robots=True, max_bytes=4_000_000, html_only=True)
            except BlockedByRobots:
                self.blocked.append(url)
                continue
            except (HttpError, ContentError):
                continue
            self.pages_fetched += 1
            if resp.content_type == "application/pdf" or looks_like_document(resp.url):
                origin = via.get(url)
                info = LinkInfo(url=resp.url) if origin is None else LinkInfo(**{**origin.__dict__, "url": resp.url})
                documents.setdefault(resp.url, []).append(info)
                continue
            if "html" not in resp.content_type and "xml" not in resp.content_type:
                continue
            for info in parse_html(resp.text(), resp.url):
                if looks_like_document(info.url):
                    documents.setdefault(info.url, []).append(info)
                elif depth < self.max_depth:
                    prio = self.priority(info.url, info.anchor)
                    if prio > 0 and (depth == 0 or prio >= 2):
                        push(info.url, depth + 1, prio - depth, info)
        return documents

    def _sitemap_links(self, seed: str, on_site, max_files: int = 8, max_urls: int = 20000) -> list[LinkInfo]:
        parts = urlsplit(seed)
        origin = f"{parts.scheme}://{parts.netloc}"
        try:
            queue = self.ctx.http.sitemaps(seed) or [origin + "/sitemap.xml"]
        except HttpError:
            return []
        seen, found = set(), []
        while queue and len(seen) < max_files and len(found) < max_urls:
            sitemap = queue.pop(0)
            if sitemap in seen or not on_site(sitemap):
                continue
            seen.add(sitemap)
            try:
                resp = self.ctx.http.get(sitemap, accept="application/xml,text/xml;q=0.9,*/*;q=0.5",
                                         check_robots=True, max_bytes=20_000_000)
            except (HttpError, BlockedByRobots, ContentError):
                continue
            body = resp.body
            if body[:2] == b"\x1f\x8b":
                try:
                    body = gzip.decompress(body)
                except OSError:
                    continue
            try:
                root = ET.fromstring(body)
            except ET.ParseError:
                continue
            is_index = root.tag.endswith("sitemapindex")
            locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
            if is_index:
                locs.sort(key=lambda u: -self.priority(u))
                queue.extend(locs)
                continue
            for loc in locs:
                if looks_like_document(loc) or self.priority(loc) >= 4:
                    found.append(LinkInfo(url=loc, page_url=sitemap))
        return found
