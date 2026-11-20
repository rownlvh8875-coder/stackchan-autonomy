"""Opt-in bounded timings. Never collect arguments, paths, SQL or exception text.

Durations overlap: SQLite stages are nested in storage_operation. A slow worker
also includes OS descheduling; these numbers alone cannot identify physical I/O.
"""

import contextvars
import threading
import time
from collections import Counter, deque
from contextlib import contextmanager

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
            count, total, peak = self._stages.get(stage, (0, 0.0, 0.0))
            self._stages[stage] = (count + 1, total + max(0, elapsed), max(peak, elapsed))

    def interrupt(self, trace):
        self.note_interruption(trace.label, trace.stage, time.perf_counter() - trace.created)

    def note_interruption(self, label, stage, elapsed):
        with self._lock:
            self._interruption_count += 1
            self._interruptions.append(
                {
                    "operation": label,
                    "stage": stage,
                    "elapsed_s": max(0, elapsed),
                }
            )

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
            return {
                "stages": {
                    name: {"count": n, "total_s": total, "max_s": peak}
                    for name, (n, total, peak) in sorted(self._stages.items())
                },
                "operations": dict(self._operations),
                "interruption_count": self._interruption_count,
                "interruptions": list(self._interruptions),
                "loop_lag_max_s": self._loop_lag,
                "loop_samples": self._loop_samples,
            }


class StorageTrace:
    def __init__(self, probe):
        self.probe = probe
        self.label = _label.get()
        self.created = self.mark = time.perf_counter()
        self.stage = "serial_wait"
        with probe._lock:
            probe._operations[self.label] += 1

    def advance(self, stage):
        now = time.perf_counter()
        self.probe.record("storage_" + self.stage, now - self.mark)
        self.stage, self.mark = stage, now

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


@contextmanager
def sqlite_timing(stage):
    probe = _probe.get()
    if probe is None:
        yield
        return
    if stage not in _SQL_STAGES:
        raise ValueError("unknown diagnostic stage")
    trace = _trace.get()
    previous = trace.stage if trace is not None else None
    if trace is not None:
        trace.stage = stage
    started = time.perf_counter()
    try:
        yield
    finally:
        probe.record(stage, time.perf_counter() - started)
        if trace is not None:
            trace.stage = previous
