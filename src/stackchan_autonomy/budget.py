"""Restart-safe API reservations and aggregate metadata. No retry/refund on uncertainty."""

from contextlib import contextmanager
from dataclasses import dataclass

from .settings import Settings
from .state_store import SQLiteState, StateUnavailable, finite_time


@dataclass(frozen=True)
class BudgetUsage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0


class SQLiteRequestBudget:
    def __init__(self, settings: Settings):
        self.store = SQLiteState(settings.state_path)
        self.namespace = settings.budget_namespace
        self.require_existing = settings.budget_require_existing
        self.windows = (
            (60, settings.requests_per_minute),
            (3600, settings.requests_per_hour),
            (86400, settings.requests_per_day),
        )

    @contextmanager
    def _transaction(self):
        with self.store.transaction(existing=self.require_existing) as db:
            if (
                self.require_existing
                and db.execute(
                    "SELECT 1 FROM api_usage WHERE namespace=?", (self.namespace,)
                ).fetchone()
                is None
            ):
                raise StateUnavailable("budget was not initialized for this namespace")
            yield db

    def reserve(self, now: float) -> bool:
        now = finite_time(now)
        with self._transaction() as db:
            now = self.store.observed_time(db, "budget:" + self.namespace, now)
            db.execute(
                "DELETE FROM api_requests WHERE namespace=? AND at<=?",
                (self.namespace, now - 86400),
            )
            for duration, maximum in self.windows:
                count = db.execute(
                    "SELECT count(*) FROM api_requests WHERE namespace=? AND at>?",
                    (self.namespace, now - duration),
                ).fetchone()[0]
                if count >= maximum:
                    return False
            db.execute("INSERT INTO api_requests(namespace,at) VALUES(?,?)", (self.namespace, now))
            db.execute(
                "INSERT INTO api_usage VALUES(?,1,0,0,0) ON CONFLICT(namespace) "
                "DO UPDATE SET requests=requests+1",
                (self.namespace,),
            )
            return True

    def record_usage(self, *, input_tokens: int = 0, output_tokens: int = 0, failed: bool = False):
        if (
            any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens))
            or type(failed) is not bool
        ):
            raise ValueError("usage must contain nonnegative integer counters")
        with self._transaction() as db:
            db.execute(
                "INSERT INTO api_usage VALUES(?,0,?,?,?) ON CONFLICT(namespace) DO UPDATE SET "
                "input_tokens=input_tokens+excluded.input_tokens, "
                "output_tokens=output_tokens+excluded.output_tokens, failures=failures+excluded.failures",
                (self.namespace, input_tokens, output_tokens, int(failed)),
            )

    def snapshot(self) -> BudgetUsage:
        with self._transaction() as db:
            row = db.execute(
                "SELECT requests,input_tokens,output_tokens,failures FROM api_usage "
                "WHERE namespace=?",
                (self.namespace,),
            ).fetchone()
            return BudgetUsage(*row) if row else BudgetUsage()
