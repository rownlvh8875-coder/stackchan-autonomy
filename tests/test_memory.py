import sqlite3
import subprocess
import sys

import pytest

from stackchan_autonomy.memory import Memory
from stackchan_autonomy.models import EventKind, RobotStatus


def legacy(path, result="executed"):
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE history(id INTEGER PRIMARY KEY, at REAL, event TEXT, "
            "intent TEXT, result TEXT)"
        )
        db.execute("INSERT INTO history VALUES(1,10,'PERSON_DETECTED','speak',?)", (result,))


def version1(path, *, invalid_history=False):
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE memory_schema(id INTEGER PRIMARY KEY,version INTEGER);"
            "INSERT INTO memory_schema VALUES(1,1);"
            "CREATE TABLE memory_profiles(resource TEXT PRIMARY KEY,clock_at REAL,"
            "last_spoken_at REAL,last_greeting_at REAL,robot TEXT,preferences TEXT);"
            "CREATE TABLE memory_history(id INTEGER PRIMARY KEY,resource TEXT,at REAL,"
            "event TEXT,intent TEXT,result TEXT);"
        )
        db.execute(
            "INSERT INTO memory_profiles VALUES('stackchan:default',20,10,10,NULL,?)",
            ('{"automatic_speech_enabled":true,"minimum_speech_interval_s":0}',),
        )
        if invalid_history:
            db.execute(
                "INSERT INTO memory_history VALUES(1,'stackchan:default',20,'TOUCH_TAP','speak',?)",
                ("invalid-private-result",),
            )


def test_legacy_history_migrates_only_into_default_resource(tmp_path):
    path = tmp_path / "memory.sqlite3"
    legacy(path)
    with Memory(path=path, resource="another", clock=lambda: 20) as other:
        assert other.recent() == ()
    with Memory(path=path, clock=lambda: 20) as memory:
        assert memory.recent()[0].event == EventKind.PERSON_DETECTED
        assert memory.last_spoken_at == 10
        assert memory.snapshot().last_greeting_at == 10
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version FROM memory_schema WHERE id=1").fetchone() == (2,)


def test_legacy_migration_preserves_speech_time_outside_new_history_limit(tmp_path):
    path = tmp_path / "legacy-small-limit.sqlite3"
    legacy(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO history VALUES(2,11,'TIMER_OBSERVE','idle','idle')")
        db.execute("INSERT INTO history VALUES(3,12,'TIMER_OBSERVE','idle','idle')")
    with Memory(limit=1, path=path, clock=lambda: 20) as memory:
        assert [record.at for record in memory.recent()] == [12]
        assert memory.last_spoken_at == 10
        assert memory.snapshot().last_greeting_at == 10


def test_successful_speech_time_survives_history_eviction_and_restart(tmp_path):
    path = tmp_path / "bounded.sqlite3"
    with Memory(limit=2, path=path, clock=lambda: 20) as memory:
        memory.record(10, EventKind.PERSON_DETECTED, "speak", "executed")
        for at in (11, 12, 13):
            memory.record(at, EventKind.TIMER_OBSERVE, "idle", "idle")
    with Memory(limit=2, path=path, clock=lambda: 20) as memory:
        assert [r.at for r in memory.recent()] == [12, 13]
        assert memory.last_spoken_at == 10


def test_retention_expires_metadata_and_rollback_cannot_restore_it(tmp_path):
    now = [20]
    with Memory(path=tmp_path / "ttl.sqlite3", retention_s=60, clock=lambda: now[0]) as memory:
        memory.update_preferences(automatic_speech_enabled=False)
        memory.record(10, EventKind.PERSON_DETECTED, "speak", "executed", status=RobotStatus())
        now[0] = 80
        snapshot = memory.snapshot()
        assert snapshot.recent == ()
        assert snapshot.last_spoken_at is None
        assert snapshot.last_greeting_at is None
        assert snapshot.robot is None
        assert snapshot.preferences.automatic_speech_enabled is False
        now[0] = 11
        memory.record(11, EventKind.TOUCH_TAP, "idle", "idle")
        assert memory.recent() == ()


def test_other_process_updates_are_visible_and_resources_stay_separate(tmp_path):
    path = tmp_path / "shared.sqlite3"
    with Memory(path=path, clock=lambda: 20) as memory:
        memory.record(10, EventKind.TIMER_OBSERVE, "idle", "idle")
        script = (
            "import sys; from pathlib import Path; from stackchan_autonomy.memory import Memory; "
            "from stackchan_autonomy.models import EventKind; "
            "m=Memory(path=Path(sys.argv[1]), clock=lambda:20); "
            "m.update_preferences(automatic_speech_enabled=False,minimum_speech_interval_s=600); "
            "m.record(15,EventKind.TOUCH_TAP,'speak','executed'); m.close()"
        )
        subprocess.run([sys.executable, "-c", script, str(path)], check=True, timeout=15)
        assert memory.last_spoken_at == 15
        assert memory.snapshot().preferences.minimum_speech_interval_s == 600
        assert memory.snapshot().preferences.automatic_speech_enabled is False
        assert len(memory.recent()) == 2
    with Memory(path=path, resource="other", clock=lambda: 20) as other:
        assert other.recent() == ()
        assert other.snapshot().preferences.automatic_speech_enabled is True


@pytest.mark.parametrize("at,result", [(10, "private-transcript"), (-1, "idle"), (True, "idle")])
def test_memory_rejects_untyped_metadata_without_persisting_it(tmp_path, at, result):
    path = tmp_path / "private.sqlite3"
    memory = Memory(path=path)
    try:
        with pytest.raises(ValueError):
            memory.record(at, EventKind.TOUCH_TAP, "idle", result)
        assert memory.recent() == ()
    finally:
        memory.close()
    assert b"private-transcript" not in path.read_bytes()


def test_preferences_are_typed_and_cannot_accept_text_or_cloud_authority(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    with Memory(path=path) as memory:
        for changes in (
            {"automatic_speech_enabled": "yes"},
            {"minimum_speech_interval_s": -1},
            {"minimum_speech_interval_s": float("inf")},
            {"cloud_enabled": True},
            {"speech": "private-transcript"},
        ):
            with pytest.raises(ValueError):
                memory.update_preferences(**changes)
        assert memory.snapshot().preferences.automatic_speech_enabled is True
    assert b"private-transcript" not in path.read_bytes()


def test_preference_interval_cannot_outlast_retained_speech_time():
    with Memory(retention_s=60) as memory:
        with pytest.raises(ValueError):
            memory.update_preferences(minimum_speech_interval_s=600)


def test_unknown_future_schema_fails_without_changing_existing_data(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE memory_schema(id INTEGER PRIMARY KEY, version INTEGER)")
        db.execute("INSERT INTO memory_schema VALUES(1,99)")
    before = path.read_bytes()
    with pytest.raises(OSError, match="memory"):
        Memory(path=path)
    assert path.read_bytes() == before


def test_live_reader_rejects_schema_changed_by_another_process(tmp_path):
    path = tmp_path / "changed-schema.sqlite3"
    with Memory(path=path) as memory:
        with sqlite3.connect(path) as db:
            db.execute("UPDATE memory_schema SET version=99")
        with pytest.raises(OSError, match="memory"):
            memory.snapshot()


def test_v1_migration_preserves_existing_speech_suppression(tmp_path):
    path = tmp_path / "version1.sqlite3"
    version1(path)
    with Memory(path=path, clock=lambda: 20) as memory:
        assert memory.last_spoken_at == 10
        assert memory.snapshot().last_speech_guard_at == 10
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version FROM memory_schema").fetchone() == (2,)


def test_v1_migration_and_retained_history_validation_are_one_transaction(tmp_path):
    path = tmp_path / "invalid-v1.sqlite3"
    version1(path, invalid_history=True)
    before = path.read_bytes()
    with pytest.raises(OSError):
        Memory(path=path, clock=lambda: 20)
    assert path.read_bytes() == before


def test_invalid_legacy_data_rolls_back_migration_without_removing_history(tmp_path):
    path = tmp_path / "legacy-invalid.sqlite3"
    legacy(path, result="private-transcript")
    with pytest.raises(OSError, match="memory"):
        Memory(path=path, clock=lambda: 20)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT result FROM history").fetchone() == ("private-transcript",)
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE name='memory_schema'").fetchone()
            is None
        )


def test_locked_storage_does_not_advance_in_memory_speech_time(tmp_path):
    path = tmp_path / "locked.sqlite3"
    memory = Memory(path=path, clock=lambda: 20)
    try:
        with sqlite3.connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            with pytest.raises(OSError, match="memory"):
                memory.record(10, EventKind.TOUCH_TAP, "speak", "executed")
        assert memory.last_spoken_at is None
    finally:
        memory.close()


def test_clear_only_removes_configured_resource_and_keeps_other_tables(tmp_path):
    path = tmp_path / "scoped.sqlite3"
    with Memory(path=path, clock=lambda: 20) as first:
        first.record(10, EventKind.TOUCH_TAP, "speak", "executed")
        with Memory(path=path, resource="other", clock=lambda: 20) as other:
            other.record(10, EventKind.TOUCH_TAP, "emote", "executed")
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE api_usage(requests INTEGER)")
                db.execute("INSERT INTO api_usage VALUES(7)")
            first.clear()
            assert first.recent() == ()
            assert first.last_spoken_at is None
            assert len(other.recent()) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT requests FROM api_usage").fetchone() == (7,)
