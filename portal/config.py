"""Portal settings.

Precedence, lowest to highest: defaults, ``portal.toml`` in the repository root,
``PORTAL_*`` environment variables, values saved from the web UI (stored in the database).
"""

from __future__ import annotations

import json
import math
import os
import re
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"

# Seconds between two requests to the same host. Everything not listed uses ``default_rate``.
DEFAULT_HOST_RATES = {
    "api.gleif.org": 1.0,            # GLEIF allows 60 requests per minute
    "filings.xbrl.org": 1.0,
    "query.wikidata.org": 2.0,
    "api.openalex.org": 0.2,
    "ec.europa.eu": 1.0,
    "registers.esma.europa.eu": 1.0,
    "firds.esma.europa.eu": 1.0,
    "api.search.brave.com": 1.1,     # Brave free plan: 1 query per second
}

# Hosts that commonly serve investor-relations PDFs for EU issuers; web-search hits
# outside the company's own domain are only accepted from these.
DEFAULT_TRUSTED_HOSTS = [
    "q4cdn.com",
    "eqs.com",
    "eqs-cockpit.com",
    "cision.com",
    "globenewswire.com",
    "nasdaq.com",
    "euronext.com",
]

# Settings that the web UI may change. Everything else is file/environment only.
UI_KEYS = (
    "contact_email",
    "years",
    "languages",
    "all_languages",
    "include_sustainability",
    "esef_formats",
    "search_provider",
    "brave_api_key",
    "searxng_url",
    "peers_max",
    "peer_years",
    "openalex_max",
    "curated_max_per_source",
    "default_rate",
    "auto_refresh_days",
)
SECRET_KEYS = ("brave_api_key", "access_token")

# Allowed ranges and values; checked for every source (file, environment, web UI).
LIMITS = {
    "years": (1, 30), "peers_max": (0, 100), "peer_years": (1, 10), "openalex_max": (0, 100),
    "curated_max_per_source": (0, 100), "auto_refresh_days": (0, 365), "default_rate": (0.0, 60.0),
    "port": (0, 65535), "timeout": (1.0, 600.0), "retries": (0, 10), "backoff_base": (0.0, 60.0),
    "max_file_mb": (1, 10_000), "crawl_max_pages": (1, 10_000), "crawl_max_depth": (0, 10),
    "job_workers": (1, 32), "download_workers": (1, 32),
}
CHOICES = {"search_provider": {"", "brave", "searxng"}, "esef_formats": {"report", "package", "json"}}
URL_KEYS = ("searxng_url", "gleif_api", "esef_api", "wikidata_sparql", "eurostat_api", "openalex_api",
            "esma_firds_api", "brave_api")
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class Settings:
    # Storage and web server
    library_dir: str = str(ROOT / "library")
    db_path: str = ""
    host: str = "127.0.0.1"
    port: int = 8765
    access_token: str = ""
    allowed_hosts: list[str] = field(default_factory=list)
    # Sent in the User-Agent; Wikidata and OpenAlex ask API users for a contact address.
    contact_email: str = ""
    # What a company job fetches
    years: int = 10
    languages: list[str] = field(default_factory=lambda: ["en", "local"])
    all_languages: bool = False
    include_sustainability: bool = False
    esef_formats: list[str] = field(default_factory=lambda: ["report", "package"])
    # Politeness and limits
    respect_robots: bool = True
    default_rate: float = 1.0
    host_rates: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_HOST_RATES))
    timeout: float = 60.0
    retries: int = 3
    backoff_base: float = 1.0
    max_file_mb: int = 300
    crawl_max_pages: int = 120
    crawl_max_depth: int = 3
    job_workers: int = 2
    download_workers: int = 3
    auto_refresh_days: int = 0  # 0 = off; otherwise the watchlist is refreshed every N days while serving
    # Optional web search to fill gaps (older PDFs, industry reports)
    search_provider: str = ""  # "", "brave" or "searxng"
    brave_api_key: str = ""
    searxng_url: str = ""
    search_trusted_hosts: list[str] = field(default_factory=lambda: list(DEFAULT_TRUSTED_HOSTS))
    # Industry package
    peers_max: int = 12
    peer_years: int = 1
    openalex_max: int = 15
    openalex_types: str = "report|article"
    curated_max_per_source: int = 10
    industry_sources_file: str = str(DATA_DIR / "industry_sources.json")
    eurostat_datasets_file: str = str(DATA_DIR / "eurostat_datasets.json")
    # Universe (all EU stocks); empty list means EU-27 plus EEA
    universe_countries: list[str] = field(default_factory=list)
    universe_cfi_prefixes: list[str] = field(default_factory=lambda: ["ES", "EP"])
    # Endpoints (overridable for mirrors and tests)
    gleif_api: str = "https://api.gleif.org/api/v1"
    esef_api: str = "https://filings.xbrl.org"
    wikidata_sparql: str = "https://query.wikidata.org/sparql"
    eurostat_api: str = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0"
    openalex_api: str = "https://api.openalex.org"
    esma_firds_api: str = "https://registers.esma.europa.eu/solr/esma_registers_firds_files/select"
    brave_api: str = "https://api.search.brave.com/res/v1/web/search"

    @property
    def db_file(self) -> Path:
        return Path(self.db_path) if self.db_path else Path(self.library_dir) / "portal.sqlite3"

    def public_dict(self) -> dict:
        """Settings for the UI, with secrets masked."""
        data = asdict(self)
        for key in SECRET_KEYS:
            data[key] = "********" if data.get(key) else ""
        return data

    def apply(self, values: dict, *, only: tuple[str, ...] | None = None, skip_invalid: bool = False) -> list[str]:
        """Apply overrides with type coercion and validation; returns the keys that changed.

        All values are checked before the first one is set, so an invalid value (ValueError) leaves the
        settings untouched. ``skip_invalid`` drops invalid values instead (used for stored UI values)."""
        known = {f.name for f in fields(self)}
        staged = {}
        for key, value in values.items():
            if key not in known or (only is not None and key not in only):
                continue
            if key in SECRET_KEYS and value == "********":
                continue  # masked value sent back unchanged by the UI
            try:
                staged[key] = _validate(key, _coerce(value, getattr(self, key)))
            except (ValueError, TypeError) as err:
                if not skip_invalid:
                    raise ValueError(f"{key}: {err}") from None
        changed = []
        for key, new in staged.items():
            if new != getattr(self, key):
                setattr(self, key, new)
                changed.append(key)
        return changed


def _validate(key: str, value):
    if key in LIMITS:
        lo, hi = LIMITS[key]
        if not (math.isfinite(value) and lo <= value <= hi):
            raise ValueError(f"erlaubt sind Werte von {lo} bis {hi}")
    if key in CHOICES:
        for item in value if isinstance(value, list) else [value]:
            if item not in CHOICES[key]:
                raise ValueError(f"„{item}“ ist nicht erlaubt ({', '.join(sorted(repr(c) for c in CHOICES[key]))})")
    texts = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    if any(CONTROL_CHARS.search(t) for t in texts):
        raise ValueError("Steuerzeichen (z. B. Zeilenumbrüche) sind nicht erlaubt")
    if key in URL_KEYS and value and not re.match(r"^https?://", value, re.I):
        raise ValueError("bitte vollständige URL mit http(s):// angeben")
    return value


def _coerce(value, default):
    if isinstance(value, str):
        text = value.strip()
        if isinstance(default, bool):
            return text.lower() in ("1", "true", "yes", "ja", "on")
        if isinstance(default, (int, float)) and not text:
            return default  # an emptied number field keeps the current value
        if isinstance(default, int):
            return int(text)
        if isinstance(default, float):
            return float(text)
        if isinstance(default, list):
            if text.startswith("["):
                return [str(v) for v in json.loads(text)]
            return [v.strip() for v in text.split(",") if v.strip()]
        if isinstance(default, dict):
            return json.loads(text) if text else {}
        return text
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    if isinstance(default, list):
        return [str(v) for v in (value or [])]
    if isinstance(default, dict):
        return dict(value or {})
    return "" if value is None else str(value)


def load_settings(config_file: str | Path | None = None, env: dict | None = None) -> Settings:
    settings = Settings()
    path = Path(config_file) if config_file else ROOT / "portal.toml"
    if path.exists():
        with path.open("rb") as fh:
            settings.apply(tomllib.load(fh))
    env = os.environ if env is None else env
    overrides = {}
    for f in fields(settings):
        key = "PORTAL_" + f.name.upper()
        if key in env:
            overrides[f.name] = env[key]
    settings.apply(overrides)
    return settings
