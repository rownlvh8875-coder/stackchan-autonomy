"""Versioned optional memory storage, independent of coordination and API quota."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import EventKind, MemoryRecord
from .state_store import finite_time


class MemoryUnavailable(OSError):
    pass


class MemoryStore:
    def __init__(self, path: Path | None, *, limit: int, now: float):
        self.path = Path(path).expanduser().resolve() if path is not None else None
        self._anchor = sqlite3.connect(":memory:", isolation_level=None) if path is None else None
        self.closed = False
        try:
            with self.transaction() as db:
                self._migrate(db, limit, now)
        except BaseException:
            self.close()
            raise

    @contextmanager
    def transaction(self):
        if self.closed:
            raise MemoryUnavailable("memory storage unavailable")
        db = None
        try:
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                db = sqlite3.connect(self.path, timeout=0.25, isolation_level=None)
            else:
                db = self._anchor
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except (sqlite3.Error, OSError):
            if db is not None:
                db.rollback()
            raise MemoryUnavailable("memory storage unavailable") from None
        except BaseException:
            if db is not None:
                db.rollback()
            raise
        finally:
            if self.path is not None and db is not None:
                db.close()

    @staticmethod
    def _migrate(db, limit, now):
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "memory_schema" in tables:
            rows = db.execute("SELECT id,version FROM memory_schema").fetchall()
            if rows != [(1, 1)]:
                raise MemoryUnavailable("unsupported memory schema")
            return
        if {"memory_history", "memory_profiles"} & tables:
            raise MemoryUnavailable("unversioned memory schema")
        legacy = []
        if "history" in tables:
            columns = {row[1] for row in db.execute("PRAGMA table_info(history)")}
            if columns != {"id", "at", "event", "intent", "result"}:
                raise MemoryUnavailable("unsupported legacy memory schema")
            try:
                legacy = [
                    MemoryRecord(at=at, event=event, intent=intent, result=result)
                    for at, event, intent, result in db.execute(
                        "SELECT at,event,intent,result FROM history ORDER BY id DESC LIMIT ?",
                        (limit,),
                    )
                ][::-1]
            except ValueError:
                raise MemoryUnavailable("invalid legacy memory metadata") from None
        db.execute("CREATE TABLE memory_schema(id INTEGER PRIMARY KEY, version INTEGER NOT NULL)")
        db.execute("INSERT INTO memory_schema VALUES(1,1)")
        db.execute(
            "CREATE TABLE memory_history(id INTEGER PRIMARY KEY, resource TEXT NOT NULL, "
            "at REAL NOT NULL, event TEXT NOT NULL, intent TEXT NOT NULL, result TEXT NOT NULL)"
        )
        db.execute("CREATE INDEX memory_history_scope ON memory_history(resource,id)")
        db.execute(
            "CREATE TABLE memory_profiles(resource TEXT PRIMARY KEY, clock_at REAL NOT NULL, "
            "last_spoken_at REAL, last_greeting_at REAL, robot TEXT, preferences TEXT NOT NULL)"
        )
        if legacy:
            now = max(now, *(finite_time(record.at) for record in legacy))
            spoken = [r.at for r in legacy if r.intent == "speak" and r.result == "executed"]
            greetings = [
                r.at
                for r in legacy
                if r.event == EventKind.PERSON_DETECTED
                and r.intent == "speak"
                and r.result == "executed"
            ]
            db.execute(
                "INSERT INTO memory_profiles VALUES(?,?,?,?,?,?)",
                (
                    "stackchan:default",
                    now,
                    max(spoken, default=None),
                    max(greetings, default=None),
                    None,
                    '{"automatic_speech_enabled":true,"minimum_speech_interval_s":0}',
                ),
            )
            db.executemany(
                "INSERT INTO memory_history(resource,at,event,intent,result) VALUES(?,?,?,?,?)",
                [("stackchan:default", r.at, r.event.value, r.intent, r.result) for r in legacy],
            )
        if "history" in tables:
            db.execute("DROP TABLE history")

    def close(self):
        if not self.closed and self._anchor is not None:
            self._anchor.close()
        self.closed = True
