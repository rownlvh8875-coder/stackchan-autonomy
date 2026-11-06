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
        self._initialized = False
        try:
            with self.transaction() as db:
                self._migrate(db, limit, now)
            self._initialized = True
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
            if self._initialized:
                self._check_version(db)
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
    def _check_version(db):
        if db.execute("SELECT id,version FROM memory_schema").fetchall() != [(1, 1)]:
            raise MemoryUnavailable("unsupported memory schema")

    @staticmethod
    def _migrate(db, limit, now):
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "memory_schema" in tables:
            MemoryStore._check_version(db)
            return
        if {"memory_history", "memory_profiles"} & tables:
            raise MemoryUnavailable("unversioned memory schema")
        legacy = []
        spoken_at = greeting_at = None
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

                def speech_time(event=None):
                    query = "SELECT at,event,intent,result FROM history WHERE intent='speak' AND result='executed'"
                    params = () if event is None else (event.value,)
                    if event is not None:
                        query += " AND event=?"
                    row = db.execute(query + " ORDER BY at DESC LIMIT 1", params).fetchone()
                    return (
                        MemoryRecord(at=row[0], event=row[1], intent=row[2], result=row[3]).at
                        if row
                        else None
                    )

                spoken_at = speech_time()
                greeting_at = speech_time(EventKind.PERSON_DETECTED)
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
            now = max(now, spoken_at or 0, greeting_at or 0)
            db.execute(
                "INSERT INTO memory_profiles VALUES(?,?,?,?,?,?)",
                (
                    "stackchan:default",
                    now,
                    spoken_at,
                    greeting_at,
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
