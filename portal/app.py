"""Application container and background job runner."""

from __future__ import annotations

import threading
import time

from .config import UI_KEYS, Settings
from .connectors.base import Context, JobCancelled
from .db import Database, now_iso
from .net import HttpClient
from .pipeline import describe_error, run_job
from .storage import Library

JOB_TITLES = {
    "company": "Geschäftsberichte",
    "industry": "Branchenpaket",
    "batch": "Stapelauftrag",
    "refresh": "Beobachtungsliste aktualisieren",
    "universe": "Universum aktualisieren",
    "index": "Volltext und Kennzahlen aktualisieren",
}


class App:
    def __init__(self, settings: Settings, echo=None):
        self.settings = settings
        self.db = Database(settings.db_file)
        settings.apply(self.db.load_settings(), only=UI_KEYS)
        self.library = Library(settings.library_dir)
        self.http = HttpClient(settings)
        self.jobs = JobRunner(self, echo=echo)

    def context(self, job_id: int | None = None, echo=None, cancel_event=None) -> Context:
        return Context(self.settings, self.http, self.db, self.library, job_id=job_id, echo=echo,
                       cancel_event=cancel_event)

    def save_settings(self, values: dict) -> list[str]:
        changed = self.settings.apply(values, only=UI_KEYS)
        self.db.save_settings({key: getattr(self.settings, key) for key in UI_KEYS})
        return changed

    def close(self) -> None:
        self.jobs.stop()
        self.db.close()


class JobRunner:
    def __init__(self, app: App, echo=None):
        self.app = app
        self.echo = echo
        self._cancel: dict[int, threading.Event] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self, workers: int | None = None, scheduler: bool = False) -> None:
        requeued = self.app.db.requeue_interrupted()
        if requeued and self.echo:
            self.echo("info", f"{requeued} unterbrochene Aufträge wieder eingereiht", {})
        for i in range(workers or self.app.settings.job_workers):
            thread = threading.Thread(target=self._loop, name=f"job-worker-{i}", daemon=True)
            thread.start()
            self._threads.append(thread)
        if scheduler:
            thread = threading.Thread(target=self._schedule, name="scheduler", daemon=True)
            thread.start()
            self._threads.append(thread)

    def maybe_auto_refresh(self, now: float | None = None) -> int | None:
        """Queue a watchlist refresh when auto_refresh_days have passed since the last one."""
        days = int(self.app.settings.auto_refresh_days or 0)
        if days <= 0:
            return None
        now = now if now is not None else time.time()
        last = float(self.app.db.get_value("state:last_auto_refresh", 0) or 0)
        if now - last < days * 86400:
            return None
        self.app.db.set_value("state:last_auto_refresh", now)
        return self.submit("refresh", {"auto": True}, title="Automatische Aktualisierung der Beobachtungsliste")

    def next_auto_refresh(self) -> float | None:
        days = int(self.app.settings.auto_refresh_days or 0)
        if days <= 0:
            return None
        return float(self.app.db.get_value("state:last_auto_refresh", 0) or 0) + days * 86400

    def _schedule(self) -> None:
        while not self._stop.wait(60):
            try:
                self.maybe_auto_refresh()
            except Exception as err:  # noqa: BLE001 - the scheduler must keep running
                if self.echo:
                    self.echo("error", f"Planer: {err}", {})

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for event in self._cancel.values():
            event.set()

    def submit(self, kind: str, params: dict, title: str | None = None, parent_id: int | None = None) -> int:
        job_id = self.app.db.create_job(kind, title or JOB_TITLES.get(kind, kind), params, parent_id)
        self._wake.set()
        return job_id

    def cancel(self, job_id: int) -> bool:
        job = self.app.db.job(job_id)
        if not job:
            return False
        if job["status"] == "queued":
            self.app.db.update_job(job_id, status="cancelled", finished_at=now_iso())
            return True
        if job["status"] == "running":
            self._cancel.setdefault(job_id, threading.Event()).set()
            self.app.db.update_job(job_id, status="cancelling")
            return True
        return False

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.app.db.claim_job()
            if job is None:
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            self.run(job)

    def run(self, job: dict) -> dict:
        db = self.app.db
        job_id = job["id"]
        cancel = self._cancel.setdefault(job_id, threading.Event())
        ctx = self.app.context(job_id=job_id, echo=self.echo, cancel_event=cancel)
        started = time.monotonic()
        try:
            summary = run_job(ctx, job["kind"], job.get("params") or {}, self)
            summary["seconds"] = round(time.monotonic() - started, 1)
            db.update_job(job_id, status="done", progress=1.0, stage="Fertig", summary=summary,
                          finished_at=now_iso())
        except JobCancelled:
            ctx.log("warn", "Auftrag abgebrochen")
            db.update_job(job_id, status="cancelled", stage="Abgebrochen", finished_at=now_iso())
        except Exception as err:  # noqa: BLE001 - report every failure on the job itself
            message = describe_error(err)
            ctx.log("error", message.splitlines()[0], detail=message)
            db.update_job(job_id, status="failed", stage="Fehler", error=message, finished_at=now_iso())
        finally:
            self._cancel.pop(job_id, None)
        return db.job(job_id)

    def run_sync(self, kind: str, params: dict, title: str | None = None) -> dict:
        """Run a job in the calling thread (CLI and tests)."""
        job_id = self.app.db.create_job(kind, title or JOB_TITLES.get(kind, kind), params, status="running")
        self.app.db.update_job(job_id, started_at=now_iso())
        return self.run(self.app.db.job(job_id))
