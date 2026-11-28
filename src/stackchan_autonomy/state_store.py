"""Short, atomic SQLite transactions. No secrets or raw observations belong here."""

import math
from contextlib import contextmanager
from pathlib import Path

from .sqlite_runtime import WINDOWS_WAL, sqlite3
from .timing_diagnostics import sqlite_timing


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

    def keep_wal_open(self) -> sqlite3.Connection | None:
        """Retain the WAL across lease I/O until the owner drains its worker."""
        if not WINDOWS_WAL:
            return None
        db = None
        try:
            # The keeper has no active transactions. The serial storage worker
            # can start and close it on different executor threads.
            with sqlite_timing("sqlite_connect"):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                db = sqlite3.connect(
                    self.path, timeout=0.25, isolation_level=None, check_same_thread=False
                )
                db.execute("PRAGMA synchronous=FULL")
                mode = db.execute("PRAGMA journal_mode").fetchone()
                if mode != ("wal",) and db.execute("PRAGMA journal_mode=WAL").fetchone() != (
                    "wal",
                ):
                    raise StateUnavailable("coordination storage unavailable")
                # Switching journal mode alone does not attach this connection to the WAL.
                db.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
            return db
        except (sqlite3.Error, OSError):
            if db is not None:
                db.close()
            raise StateUnavailable("coordination storage unavailable") from None

    @contextmanager
    def transaction(self, *, existing: bool = False):
        db = None
        try:
            with sqlite_timing("sqlite_connect"):
                if existing:
                    db = sqlite3.connect(
                        self.path.as_uri() + "?mode=rw",
                        uri=True,
                        timeout=0.25,
                        isolation_level=None,
                    )
                else:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    db = sqlite3.connect(self.path, timeout=0.25, isolation_level=None)
                db.execute("PRAGMA synchronous=FULL")
            with sqlite_timing("sqlite_begin"):
                db.execute("BEGIN IMMEDIATE")
            if not existing:
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
                    with sqlite_timing("sqlite_schema"):
                        db.execute(statement)
            with sqlite_timing("sqlite_body"):
                yield db
            with sqlite_timing("sqlite_commit"):
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
                with sqlite_timing("sqlite_close"):
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
