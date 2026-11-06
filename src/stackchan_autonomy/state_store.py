"""Short, atomic SQLite transactions. No secrets or raw observations belong here."""

import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class StateUnavailable(OSError):
    pass


def finite_time(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError("expected finite nonnegative wall time")
    return float(value)


class SQLiteState:
    def __init__(self, path: Path):
        if str(path) == ":memory:":
            raise ValueError("coordination requires a persistent file")
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def transaction(self):
        db = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=0.25, isolation_level=None)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            for statement in (
                "CREATE TABLE IF NOT EXISTS autonomy_clock (scope TEXT PRIMARY KEY, at REAL NOT NULL)",
                "CREATE TABLE IF NOT EXISTS control_leases (resource TEXT PRIMARY KEY, owner TEXT, "
                "generation INTEGER NOT NULL, expires_at REAL NOT NULL)",
                "CREATE TABLE IF NOT EXISTS api_requests (id INTEGER PRIMARY KEY, namespace TEXT NOT NULL, "
                "at REAL NOT NULL)",
                "CREATE INDEX IF NOT EXISTS api_requests_time ON api_requests(namespace, at)",
                "CREATE TABLE IF NOT EXISTS api_usage (namespace TEXT PRIMARY KEY, requests INTEGER NOT NULL, "
                "input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, failures INTEGER NOT NULL)",
            ):
                db.execute(statement)
            yield db
            db.commit()
        except (sqlite3.Error, OSError):
            if db is not None:
                db.rollback()
            raise StateUnavailable("coordination storage unavailable") from None
        except BaseException:
            if db is not None:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def observed_time(db, scope: str, now: float) -> float:
        now = finite_time(now)
        row = db.execute("SELECT at FROM autonomy_clock WHERE scope=?", (scope,)).fetchone()
        if row is not None:
            try:
                now = max(now, finite_time(row[0]))
            except ValueError:
                raise StateUnavailable("invalid persistent coordination clock") from None
        db.execute(
            "INSERT INTO autonomy_clock(scope,at) VALUES(?,?) ON CONFLICT(scope) "
            "DO UPDATE SET at=excluded.at",
            (scope, now),
        )
        return now
