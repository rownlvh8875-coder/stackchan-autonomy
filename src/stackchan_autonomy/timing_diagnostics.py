"""Opt-in bounded timings. Never collect arguments, paths, SQL or exception text.

Durations overlap: SQLite stages are nested in storage_operation. A slow worker
also includes OS descheduling; these numbers alone cannot identify physical I/O.
"""

import contextvars
import threading
import time
from collections import Counter, deque
from contextlib import contextmanager
from time import thread_time

from .sqlite_runtime import sqlite3

_probe = contextvars.ContextVar("stackchan_timing_probe", default=None)
_trace = contextvars.ContextVar("stackchan_storage_trace", default=None)
_label = contextvars.ContextVar("stackchan_timing_label", default="other")
_LABELS = frozenset({"lease_acquire", "lease_check", "lease_renew", "other"})
_SQL_STAGES = frozenset(
    {
        "sqlite_connect",
        "sqlite_begin",
        "sqlite_schema",
        "sqlite_body",
        "sqlite_commit",
        "sqlite_close",
    }
)


@contextmanager
def operation_label(label):
    token = _label.set(label if label in _LABELS else "other")
    try:
        yield
    finally:
        _label.reset(token)


class TimingProbe:
    def __init__(self):
        self._lock = threading.Lock()
        self._stages = {}
        self._operations = Counter()
        self._interruptions = deque(maxlen=16)
        self._interruption_count = 0
        self._loop_lag = 0.0
        self._loop_samples = 0
        self._monitor = None

    @contextmanager
    def collect(self):
        token = _probe.set(self)
        try:
            yield self
        finally:
            _probe.reset(token)

    def record(self, stage, elapsed):
        with self._lock:
            self._record(stage, elapsed)

    def _record(self, stage, elapsed):
        # Caller holds the probe lock.
        count, total, peak = self._stages.get(stage, (0, 0.0, 0.0))
        self._stages[stage] = (count + 1, total + max(0, elapsed), max(peak, elapsed))

    def interrupt(self, trace):
        with self._lock:
            stage, started = trace._phase
            now = time.perf_counter()
            completed = dict(trace._completed)
        self.note_interruption(
            trace.label,
            stage,
            now - trace.created,
            stage_elapsed=now - started,
            completed_stages=completed,
            commit=(trace, started) if stage == "sqlite_commit" else None,
        )

    def note_interruption(
        self, label, stage, elapsed, *, stage_elapsed=None, completed_stages=None, commit=None
    ):
        report = {
            "operation": label,
            "stage": stage,
            "elapsed_s": max(0, elapsed),
            "stage_elapsed_s": None if stage_elapsed is None else max(0, stage_elapsed),
        }
        if completed_stages is not None:
            report["completed_stages_s"] = completed_stages
        with self._lock:
            self._interruption_count += 1
            self._interruptions.append((report, commit))

    def start_loop_monitor(self, loop, *, interval_s=0.02):
        if self._monitor is not None or not 0.001 <= interval_s <= 1:
            raise ValueError("invalid timing monitor lifecycle or interval")

        def tick(expected):
            now = time.perf_counter()
            with self._lock:
                self._loop_lag = max(self._loop_lag, max(0, now - expected))
                self._loop_samples += 1
            expected = now + interval_s
            self._monitor = loop.call_later(interval_s, tick, expected)

        expected = time.perf_counter() + interval_s
        self._monitor = loop.call_later(interval_s, tick, expected)

    def stop_loop_monitor(self):
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None

    def snapshot(self):
        with self._lock:
            interrupted = []
            for report, commit in self._interruptions:
                item = dict(report)
                if "completed_stages_s" in item:
                    item["completed_stages_s"] = dict(item["completed_stages_s"])
                if commit is not None:
                    trace, started = commit
                    finished = trace._commit
                    item["commit_completion"] = (
                        dict(finished[1])
                        if finished is not None and finished[0] == started
                        else None
                    )
                interrupted.append(item)
            return {
                "stages": {
                    name: {"count": n, "total_s": total, "max_s": peak}
                    for name, (n, total, peak) in sorted(self._stages.items())
                },
                "operations": dict(self._operations),
                "interruption_count": self._interruption_count,
                "interruptions": interrupted,
                "loop_lag_max_s": self._loop_lag,
                "loop_samples": self._loop_samples,
            }


class StorageTrace:
    def __init__(self, probe):
        self.probe = probe
        self.label = _label.get()
        self.created = time.perf_counter()
        # The executor and event loop observe a single phase/timestamp pair.
        self._phase = "serial_wait", self.created
        self._completed = {}
        self._commit = None
        with probe._lock:
            probe._operations[self.label] += 1

    @property
    def stage(self):
        return self._phase[0]

    def advance(self, stage):
        with self.probe._lock:
            previous, started = self._phase
            now = time.perf_counter()
            self._phase = stage, now
            self._record("storage_" + previous, now - started)

    def _record(self, stage, elapsed):
        self._completed[stage] = self._completed.get(stage, 0.0) + max(0, elapsed)
        self.probe._record(stage, elapsed)

    def run(self, operation):
        self.advance("operation")
        token = _trace.set(self)
        try:
            return operation()
        finally:
            _trace.reset(token)
            self.advance("delivery")


def storage_trace():
    probe = _probe.get()
    return None if probe is None else StorageTrace(probe)


def control_deadline(label, stage, elapsed):
    """Capture post-return deadline failures, even if no timer cancellation ran."""
    probe = _probe.get()
    if probe is not None:
        probe.note_interruption(label if label in _LABELS else "other", stage, elapsed)


def _sqlite_completion(exc):
    if isinstance(exc, sqlite3.Error):
        code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
        return {
            sqlite3.SQLITE_BUSY: "busy",
            sqlite3.SQLITE_LOCKED: "locked",
            sqlite3.SQLITE_IOERR: "io_error",
            sqlite3.SQLITE_FULL: "full",
        }.get(code, "error")
    return "error"


@contextmanager
def sqlite_timing(stage):
    probe = _probe.get()
    if probe is None:
        yield
        return
    if stage not in _SQL_STAGES:
        raise ValueError("unknown diagnostic stage")
    trace = _trace.get()
    started = time.perf_counter()
    track_commit = trace is not None and stage == "sqlite_commit"
    cpu_started = thread_time() if track_commit else None
    outcome = "returned"
    if trace is not None:
        with probe._lock:
            previous = trace._phase
            trace._phase = stage, started
    try:
        yield
    except BaseException as exc:
        if track_commit:
            outcome = _sqlite_completion(exc)
        raise
    finally:
        elapsed = time.perf_counter() - started
        cpu_elapsed = max(0, thread_time() - cpu_started) if cpu_started is not None else None
        if trace is not None:
            with probe._lock:
                trace._phase = previous
                trace._record(stage, elapsed)
                if track_commit:
                    trace._commit = (
                        started,
                        {
                            "wall_s": max(0, elapsed),
                            "worker_cpu_s": cpu_elapsed,
                            "outcome": outcome,
                        },
                    )
        else:
            probe.record(stage, elapsed)
