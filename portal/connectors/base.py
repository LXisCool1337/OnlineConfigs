"""Shared types for connectors: the download candidate and the job context."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

# Sources whose URLs come from an official API; their files are fetched without a robots.txt check.
API_SOURCES = {"esef", "eurostat"}


class JobCancelled(Exception):
    pass


@dataclass
class Candidate:
    url: str
    category: str
    source: str
    fiscal_year: int | None = None
    fy_label: str | None = None
    period_end: str | None = None
    language: str | None = None
    title: str = ""
    score: float = 0.0
    ext: str = "pdf"
    expect: tuple = ("pdf",)
    lei: str | None = None          # owner of the document when it is not the job's company (peers)
    subdir: str = ""                # folder inside an industry package
    meta: dict = field(default_factory=dict)
    alternates: list = field(default_factory=list)  # next-best candidates, tried if this one fails


class Context:
    """Everything a connector or pipeline needs, bound to one job (or to none, for CLI helpers)."""

    def __init__(self, settings, http, db, library, job_id: int | None = None, echo=None,
                 cancel_event: threading.Event | None = None):
        self.settings = settings
        self.http = http
        self.db = db
        self.library = library
        self.job_id = job_id
        self.echo = echo
        self.cancel_event = cancel_event or threading.Event()
        self._range = (0.0, 1.0)
        self._last_progress = -1.0

    def log(self, level: str, message: str, **data) -> None:
        if self.job_id is not None:
            self.db.add_event(self.job_id, level, message, data)
        if self.echo:
            self.echo(level, message, data)

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled()

    @contextmanager
    def span(self, start: float, end: float):
        """Within the block, progress 0..1 maps to [start, end] of the current range."""
        previous = self._range
        lo, hi = previous
        self._range = (lo + (hi - lo) * start, lo + (hi - lo) * end)
        try:
            yield
        finally:
            self._range = previous

    def progress(self, fraction: float, stage: str | None = None) -> None:
        lo, hi = self._range
        value = round(lo + (hi - lo) * max(0.0, min(1.0, fraction)), 4)
        if self.job_id is None:
            return
        fields = {}
        if value != self._last_progress:
            fields["progress"] = value
            self._last_progress = value
        if stage:
            fields["stage"] = stage
        if fields:
            self.db.update_job(self.job_id, **fields)

    def stage(self, fraction: float, label: str) -> None:
        self.check_cancel()
        self.progress(fraction, label)
        self.log("stage", label)
