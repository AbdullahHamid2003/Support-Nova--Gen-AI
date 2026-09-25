"""Background processing: a bounded thread pool runs the complaint pipeline off the request path
(POST /complaints returns 202 immediately; the UI polls pipeline progress). A periodic monitor
refreshes SLA states. For multi-instance deployments the same entry points can be driven by an
external queue (REDIS_URL) - the in-process pool is the default."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy import select

from supportnova.core.config import get_settings
from supportnova.core.logging import get_logger
from supportnova.database.base import session_scope
from supportnova.database.models import Complaint
from supportnova.services.pipeline import PipelineOptions, process_complaint

log = get_logger(__name__)


class Worker:
    def __init__(self) -> None:
        self._pool: ThreadPoolExecutor | None = None
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._inflight: dict[int, Future[dict[str, object]]] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        settings = get_settings()
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=max(1, settings.background_workers), thread_name_prefix="pipeline")
        if self._monitor is None:
            self._stop.clear()
            self._monitor = threading.Thread(target=self._monitor_loop, name="sla-monitor", daemon=True)
            self._monitor.start()

    def stop(self) -> None:
        self._stop.set()
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None
        self._monitor = None

    def submit(self, complaint_id: int, options: PipelineOptions | None = None) -> None:
        if self._pool is None:
            self.start()
        assert self._pool is not None
        with self._lock:
            current = self._inflight.get(complaint_id)
            if current is not None and not current.done():
                return
            self._inflight[complaint_id] = self._pool.submit(process_complaint, complaint_id, options)

    def requeue_stuck(self) -> int:
        """Crash recovery: complaints left queued/processing are processed again on startup."""
        with session_scope() as db:
            ids = db.execute(select(Complaint.id).where(Complaint.processing_stage.notin_(["completed", "failed"]),
                                                        Complaint.status.in_(["New", "Processing"]),
                                                        Complaint.source != "evaluation")).scalars().all()
        for cid in ids:
            self.submit(cid, PipelineOptions(trigger="recovery"))
        return len(ids)

    def _monitor_loop(self) -> None:
        interval = max(10, get_settings().sla_monitor_interval_seconds)
        while not self._stop.wait(interval):
            try:
                from supportnova.services.rules import rule_service
                from supportnova.services.sla import refresh_all
                with session_scope() as db:
                    refresh_all(db, rule_service.matrix(db))
            except Exception:  # pragma: no cover - monitor must never die
                log.exception("SLA monitor iteration failed")
                time.sleep(1)


worker = Worker()
