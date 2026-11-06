"""Bounded, optional metadata memory. No raw text, media, credentials or commands."""

import time
from pathlib import Path

from .memory_store import MemoryStore, MemoryUnavailable
from .models import (
    EventKind,
    MemoryPreferences,
    MemoryRecord,
    MemorySnapshot,
    ObservedRobotState,
    RobotStatus,
)
from .state_store import finite_time


class Memory:
    def __init__(
        self,
        limit: int = 100,
        path: Path | None = None,
        *,
        resource: str = "stackchan:default",
        retention_s: float = 604800,
        clock=time.time,
    ):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise ValueError("invalid memory history bound")
        if not isinstance(resource, str) or not 1 <= len(resource) <= 200:
            raise ValueError("invalid memory resource")
        if not 60 <= finite_time(retention_s) <= 31536000:
            raise ValueError("invalid memory retention")
        self.limit, self.resource, self.retention_s, self.clock = (
            limit,
            resource,
            retention_s,
            clock,
        )
        self._store = MemoryStore(path, limit=limit, now=finite_time(clock()))
        try:
            self.snapshot()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _read(self, db, now: float) -> tuple[MemorySnapshot, float]:
        try:
            row = db.execute(
                "SELECT clock_at,last_spoken_at,last_greeting_at,robot,preferences "
                "FROM memory_profiles WHERE resource=?",
                (self.resource,),
            ).fetchone()
            now = finite_time(now)
            if row is None:
                snapshot = MemorySnapshot()
            else:
                now = max(now, finite_time(row[0]))
                snapshot = MemorySnapshot(
                    last_spoken_at=row[1],
                    last_greeting_at=row[2],
                    robot=ObservedRobotState.model_validate_json(row[3]) if row[3] else None,
                    preferences=MemoryPreferences.model_validate_json(row[4]),
                )
            if snapshot.preferences.minimum_speech_interval_s > self.retention_s:
                raise MemoryUnavailable("memory retention is shorter than speech preference")
            cutoff = now - self.retention_s
            db.execute(
                "DELETE FROM memory_history WHERE resource=? AND (at<? OR id NOT IN "
                "(SELECT id FROM memory_history WHERE resource=? ORDER BY id DESC LIMIT ?))",
                (self.resource, cutoff, self.resource, self.limit),
            )
            records = tuple(
                MemoryRecord(at=at, event=event, intent=intent, result=result)
                for at, event, intent, result in db.execute(
                    "SELECT at,event,intent,result FROM memory_history WHERE resource=? ORDER BY id",
                    (self.resource,),
                )
            )
            snapshot = MemorySnapshot(
                recent=records,
                preferences=snapshot.preferences,
                last_spoken_at=(
                    snapshot.last_spoken_at
                    if snapshot.last_spoken_at is not None and snapshot.last_spoken_at >= cutoff
                    else None
                ),
                last_greeting_at=(
                    snapshot.last_greeting_at
                    if snapshot.last_greeting_at is not None and snapshot.last_greeting_at >= cutoff
                    else None
                ),
                robot=snapshot.robot if snapshot.robot and snapshot.robot.at >= cutoff else None,
            )
        except (ValueError, TypeError):
            raise MemoryUnavailable("invalid memory metadata") from None
        self._write(db, snapshot, now)
        return snapshot, now

    def _write(self, db, snapshot, now):
        db.execute(
            "INSERT INTO memory_profiles VALUES(?,?,?,?,?,?) ON CONFLICT(resource) DO UPDATE SET "
            "clock_at=excluded.clock_at,last_spoken_at=excluded.last_spoken_at,"
            "last_greeting_at=excluded.last_greeting_at,robot=excluded.robot,"
            "preferences=excluded.preferences",
            (
                self.resource,
                now,
                snapshot.last_spoken_at,
                snapshot.last_greeting_at,
                snapshot.robot.model_dump_json() if snapshot.robot else None,
                snapshot.preferences.model_dump_json(),
            ),
        )

    def snapshot(self) -> MemorySnapshot:
        with self._store.transaction() as db:
            snapshot, _ = self._read(db, self.clock())
            return snapshot

    def recent(self) -> tuple[MemoryRecord, ...]:
        return self.snapshot().recent

    @property
    def last_spoken_at(self):
        return self.snapshot().last_spoken_at

    def record(
        self,
        at: float,
        event: EventKind,
        intent: str,
        result: str,
        *,
        status: RobotStatus | None = None,
        status_at: float | None = None,
    ) -> None:
        record = MemoryRecord(at=at, event=event, intent=intent, result=result)
        robot = (
            ObservedRobotState(
                at=at if status_at is None else status_at,
                connected=status.connected,
                yaw=status.yaw,
                pitch=status.pitch,
            )
            if status is not None
            else None
        )
        with self._store.transaction() as db:
            snapshot, now = self._read(db, max(finite_time(self.clock()), record.at))
            db.execute(
                "INSERT INTO memory_history(resource,at,event,intent,result) VALUES(?,?,?,?,?)",
                (self.resource, record.at, record.event.value, record.intent, record.result),
            )
            changes = {}
            if record.intent == "speak" and record.result == "executed":
                changes["last_spoken_at"] = max(record.at, snapshot.last_spoken_at or 0)
                if record.event == EventKind.PERSON_DETECTED:
                    changes["last_greeting_at"] = max(record.at, snapshot.last_greeting_at or 0)
            if robot is not None and (snapshot.robot is None or robot.at >= snapshot.robot.at):
                changes["robot"] = robot
            self._write(db, snapshot.model_copy(update=changes), now)
            self._read(db, now)

    def update_preferences(self, **changes) -> MemoryPreferences:
        with self._store.transaction() as db:
            snapshot, now = self._read(db, self.clock())
            preferences = MemoryPreferences.model_validate(
                snapshot.preferences.model_dump() | changes
            )
            if preferences.minimum_speech_interval_s > self.retention_s:
                raise ValueError("speech interval must fit within memory retention")
            self._write(db, snapshot.model_copy(update={"preferences": preferences}), now)
            return preferences

    def clear(self) -> None:
        with self._store.transaction() as db:
            db.execute("DELETE FROM memory_history WHERE resource=?", (self.resource,))
            db.execute("DELETE FROM memory_profiles WHERE resource=?", (self.resource,))

    def close(self) -> None:
        self._store.close()
