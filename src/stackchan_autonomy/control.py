"""Cooperative local-host control lease. Generations do not fence a remote gateway."""

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .state_store import SQLiteState, StateUnavailable, finite_time


@dataclass(frozen=True)
class LeaseHandle:
    resource: str
    owner: str
    generation: int


class ControlLease:
    def __init__(self, path: Path, resource: str, *, ttl_s: float = 10, clock=time.time):
        if not resource.strip() or len(resource) > 200:
            raise ValueError("resource ID must be nonempty and at most 200 characters")
        if not 0.1 <= finite_time(ttl_s) <= 300:
            raise ValueError("lease TTL must be in 0.1..300 seconds")
        self.store = SQLiteState(path)
        self.resource = resource
        self.owner = uuid.uuid4().hex
        self._creator_pid = os.getpid()
        self.ttl_s = ttl_s
        self.clock = clock
        self.valid_until_monotonic: float | None = None

    def _time(self, db):
        return self.store.observed_time(db, "lease:" + self.resource, self.clock())

    def _ensure_process_identity(self):
        # A pre-fork object is a copy, not permission to act as its parent's owner.
        pid = os.getpid()
        if pid != self._creator_pid:
            self.owner = uuid.uuid4().hex
            self._creator_pid = pid

    def acquire(self) -> LeaseHandle | None:
        self.valid_until_monotonic = None
        self._ensure_process_identity()
        with self.store.transaction() as db:
            observed = time.monotonic()
            now = self._time(db)
            row = db.execute(
                "SELECT owner,generation,expires_at FROM control_leases WHERE resource=?",
                (self.resource,),
            ).fetchone()
            if row is not None and row[0] is not None and row[2] > now:
                if row[0] != self.owner:
                    return None
                generation = row[1]
            else:
                generation = 1 if row is None else row[1] + 1
            db.execute(
                "INSERT INTO control_leases(resource,owner,generation,expires_at) VALUES(?,?,?,?) "
                "ON CONFLICT(resource) DO UPDATE SET owner=excluded.owner, "
                "generation=excluded.generation, expires_at=excluded.expires_at",
                (self.resource, self.owner, generation, now + self.ttl_s),
            )
            self.valid_until_monotonic = observed + self.ttl_s
            return LeaseHandle(self.resource, self.owner, generation)

    def _matches(self, handle):
        self._ensure_process_identity()
        return handle.resource == self.resource and handle.owner == self.owner

    def check(self, handle: LeaseHandle) -> bool:
        self.valid_until_monotonic = None
        if not self._matches(handle):
            return False
        with self.store.transaction() as db:
            observed = time.monotonic()
            now = self._time(db)
            row = db.execute(
                "SELECT expires_at FROM control_leases WHERE resource=? AND owner=? "
                "AND generation=? AND expires_at>?",
                (self.resource, self.owner, handle.generation, now),
            ).fetchone()
            if row is None:
                return False
            try:
                remaining = finite_time(row[0]) - now
            except ValueError:
                raise StateUnavailable("invalid lease expiry") from None
            self.valid_until_monotonic = observed + remaining
            return True

    def renew(self, handle: LeaseHandle) -> bool:
        self.valid_until_monotonic = None
        if not self._matches(handle):
            return False
        with self.store.transaction() as db:
            observed = time.monotonic()
            now = self._time(db)
            cursor = db.execute(
                "UPDATE control_leases SET expires_at=? WHERE resource=? AND owner=? "
                "AND generation=? AND expires_at>?",
                (now + self.ttl_s, self.resource, self.owner, handle.generation, now),
            )
            if cursor.rowcount != 1:
                return False
            self.valid_until_monotonic = observed + self.ttl_s
            return True

    def release(self, handle: LeaseHandle) -> bool:
        self.valid_until_monotonic = None
        if not self._matches(handle):
            return False
        with self.store.transaction() as db:
            # Retain the generation so an expired/stale holder cannot erase a replacement.
            return (
                db.execute(
                    "UPDATE control_leases SET owner=NULL,expires_at=0 WHERE resource=? "
                    "AND owner=? AND generation=?",
                    (self.resource, self.owner, handle.generation),
                ).rowcount
                == 1
            )
