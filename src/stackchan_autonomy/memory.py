"""Bounded metadata only; never accepts images, audio, speech or model rationale."""

import sqlite3
from collections import deque
from pathlib import Path

from .models import EventKind, MemoryRecord


class Memory:
    def __init__(self, limit: int = 100, path: Path | None = None):
        self.limit = limit
        self._records: deque[MemoryRecord] = deque(maxlen=limit)
        self._db = sqlite3.connect(path) if path else None
        if self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS history ("
                "id INTEGER PRIMARY KEY, at REAL, event TEXT, intent TEXT, result TEXT)"
            )
            for at, event, intent, result in self._db.execute(
                "SELECT at,event,intent,result FROM (SELECT * FROM history ORDER BY id DESC LIMIT ?) "
                "ORDER BY id",
                (limit,),
            ):
                self._records.append(MemoryRecord(at=at, event=event, intent=intent, result=result))
        self.last_spoken_at = next(
            (
                r.at
                for r in reversed(self._records)
                if r.intent == "speak" and r.result == "executed"
            ),
            None,
        )

    def recent(self) -> tuple[MemoryRecord, ...]:
        return tuple(self._records)

    def record(self, at: float, event: EventKind, intent: str, result: str) -> None:
        record = MemoryRecord(at=at, event=event, intent=intent, result=result)
        self._records.append(record)
        if intent == "speak" and result == "executed":
            self.last_spoken_at = at
        if self._db:
            with self._db:
                self._db.execute(
                    "INSERT INTO history(at,event,intent,result) VALUES(?,?,?,?)",
                    (at, event.value, intent, result),
                )
                self._db.execute(
                    "DELETE FROM history WHERE id NOT IN "
                    "(SELECT id FROM history ORDER BY id DESC LIMIT ?)",
                    (self.limit,),
                )

    def close(self) -> None:
        if self._db:
            self._db.close()
            self._db = None
