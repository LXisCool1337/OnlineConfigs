"""Check which data sources are reachable from this machine (firewalls, proxies, typos in settings)."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from .net import HttpError


def _probes(s) -> list[tuple[str, str]]:
    probes = [
        ("gleif", f"{s.gleif_api.rstrip('/')}/lei-records?page[size]=1"),
        ("esef", f"{s.esef_api.rstrip('/')}/api/filings?page[size]=1"),
        ("wikidata", f"{s.wikidata_sparql}?query=ASK%7B%7D&format=json"),
        ("eurostat", f"{s.eurostat_api.rstrip('/')}/data/sts_inpr_a?format=JSON&lang=EN&geo=DE&nace_r2=C28"
                     "&sinceTimePeriod=2024"),
        ("openalex", f"{s.openalex_api.rstrip('/')}/works?per-page=1"),
        ("esma", f"{s.esma_firds_api}?q=*&rows=0&wt=json"),
    ]
    if s.search_provider == "brave" and s.brave_api_key:
        probes.append(("brave", f"{s.brave_api}?q=annual%20report&count=1"))
    elif s.search_provider == "searxng" and s.searxng_url:
        probes.append(("searxng", f"{s.searxng_url.rstrip('/')}/search?q=annual%20report&format=json"))
    return probes


def _check(ctx, key: str, url: str) -> dict:
    headers = {"X-Subscription-Token": ctx.settings.brave_api_key} if key == "brave" else None
    start = time.monotonic()
    result = {"key": key, "url": url.split("?")[0]}
    try:
        resp = ctx.http.get(url, accept="application/json", headers=headers, timeout=12, retries=0,
                            max_bytes=3_000_000)
        result.update(code="ok", status=resp.status)
    except HttpError as err:
        if err.status:
            # The service answered, so the network path works; the request itself was refused.
            result.update(code="http_error", status=err.status, detail=err.reason[:160])
        elif "Tunnel connection failed: 40" in err.reason or "403" in err.reason:
            result.update(code="blocked", status=0, detail=err.reason[:160])
        else:
            result.update(code="unreachable", status=0, detail=err.reason[:160])
    result["ms"] = round((time.monotonic() - start) * 1000)
    return result


def check_sources(ctx) -> list[dict]:
    probes = _probes(ctx.settings)
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        return list(pool.map(lambda p: _check(ctx, *p), probes))
