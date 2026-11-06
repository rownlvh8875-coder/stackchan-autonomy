import json
import os
import sqlite3
import subprocess
import sys

import pytest

from stackchan_autonomy.budget import SQLiteRequestBudget
from stackchan_autonomy.control import ControlLease
from stackchan_autonomy.settings import Settings
from stackchan_autonomy.state_store import StateUnavailable


def config(**overrides):
    return Settings(requests_per_minute=2, requests_per_hour=3, requests_per_day=4, **overrides)


def test_only_one_holder_and_release_enables_next_generation(tmp_path):
    path = tmp_path / "state.sqlite3"
    first = ControlLease(path, "robot", ttl_s=10, clock=lambda: 100)
    other = ControlLease(path, "robot", ttl_s=10, clock=lambda: 100)
    handle = first.acquire()
    assert handle is not None
    assert first.check(handle)
    assert other.acquire() is None
    assert first.release(handle)
    replacement = other.acquire()
    assert replacement.generation > handle.generation
    assert not first.check(handle)
    assert not first.release(handle)
    assert other.check(replacement)


def test_expired_lease_cannot_renew_or_release_replacement(tmp_path):
    now = [100.0]
    path = tmp_path / "state.sqlite3"
    first = ControlLease(path, "robot", ttl_s=5, clock=lambda: now[0])
    second = ControlLease(path, "robot", ttl_s=5, clock=lambda: now[0])
    old = first.acquire()
    now[0] = 105
    assert not first.renew(old)
    new = second.acquire()
    assert new is not None
    assert new.generation > old.generation
    assert not first.renew(old)
    assert not first.release(old)
    assert second.check(new)


def test_renewal_extends_live_holder_and_resources_are_independent(tmp_path):
    now = [100.0]
    path = tmp_path / "state.sqlite3"
    first = ControlLease(path, "robot-a", ttl_s=5, clock=lambda: now[0])
    other = ControlLease(path, "robot-a", ttl_s=5, clock=lambda: now[0])
    independent = ControlLease(path, "robot-b", ttl_s=5, clock=lambda: now[0])
    held = first.acquire()
    assert independent.acquire() is not None
    now[0] = 104
    assert first.renew(held)
    now[0] = 106
    assert other.acquire() is None
    now[0] = 109
    assert other.acquire() is not None


def test_budget_survives_reconstruction_and_all_rolling_windows():
    settings = config()
    first = SQLiteRequestBudget(settings)
    assert first.reserve(0)
    assert first.reserve(1)
    second = SQLiteRequestBudget(settings)
    assert not second.reserve(2)
    assert second.reserve(61)
    assert not second.reserve(122)
    assert second.reserve(3602)
    assert not SQLiteRequestBudget(settings).reserve(7202)
    assert SQLiteRequestBudget(settings).reserve(86403)
    assert second.snapshot().requests == 5


def test_usage_metadata_survives_restart_without_media_or_dialogue():
    first = SQLiteRequestBudget(config())
    assert first.reserve(100)
    first.record_usage(input_tokens=12, output_tokens=3)
    first.record_usage(failed=True)
    usage = SQLiteRequestBudget(config()).snapshot()
    assert (usage.requests, usage.input_tokens, usage.output_tokens, usage.failures) == (
        1,
        12,
        3,
        1,
    )
    assert set(vars(usage)) == {"requests", "input_tokens", "output_tokens", "failures"}


def test_clock_rollback_does_not_reset_budget_or_release_a_holder(tmp_path):
    settings = config()
    budget = SQLiteRequestBudget(settings)
    assert budget.reserve(100)
    assert budget.reserve(101)
    assert not SQLiteRequestBudget(settings).reserve(0)
    now = [100.0]
    path = tmp_path / "lease.sqlite3"
    lease = ControlLease(path, "robot", ttl_s=10, clock=lambda: now[0])
    handle = lease.acquire()
    now[0] = 90
    assert lease.check(handle)
    assert ControlLease(path, "robot", ttl_s=10, clock=lambda: 90).acquire() is None


def test_unknown_state_or_database_lock_is_fail_closed(tmp_path):
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not sqlite")
    with pytest.raises(StateUnavailable):
        ControlLease(path, "robot").acquire()
    assert path.read_bytes() == b"not sqlite"


def test_database_busy_is_bounded_and_never_looks_like_ownership(tmp_path):
    path = tmp_path / "busy.sqlite3"
    lease = ControlLease(path, "robot")
    handle = lease.acquire()
    with sqlite3.connect(path, isolation_level=None) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(StateUnavailable):
                ControlLease(path, "other-robot").acquire()
        finally:
            db.rollback()
    assert lease.check(handle)


def test_corrupt_persistent_clock_is_unavailable_not_a_background_task_crash(tmp_path):
    path = tmp_path / "bad-clock.sqlite3"
    lease = ControlLease(path, "robot")
    handle = lease.acquire()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE autonomy_clock SET at='invalid'")
    with pytest.raises(StateUnavailable):
        lease.renew(handle)


def test_subprocess_lease_acquisition_has_exactly_one_winner(tmp_path):
    script = """
from stackchan_autonomy.control import ControlLease
import sys
print(int(ControlLease(sys.argv[1], 'robot', clock=lambda:100).acquire() is not None),flush=True)
"""
    path = tmp_path / "race.sqlite3"
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(6)
    ]
    try:
        results = [p.communicate(timeout=20) for p in processes]
        assert all(p.returncode == 0 for p in processes), results
        assert sum(int(out.strip()) for out, _ in results) == 1
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
            p.wait()


def test_budget_namespaces_are_explicitly_separate(monkeypatch):
    monkeypatch.delenv("STACKCHAN_BUDGET_NAMESPACE", raising=False)
    first = SQLiteRequestBudget(config(budget_namespace="shared"))
    second = SQLiteRequestBudget(config(budget_namespace="other"))
    assert first.reserve(100) and first.reserve(100)
    assert not first.reserve(100)
    assert second.reserve(100)


def test_subprocess_budget_race_cannot_overspend_shared_limit():
    settings = Settings(requests_per_minute=2, requests_per_hour=2, requests_per_day=2)
    script = """
from stackchan_autonomy.budget import SQLiteRequestBudget
from stackchan_autonomy.settings import Settings
print(int(SQLiteRequestBudget(Settings(requests_per_minute=2, requests_per_hour=2,
                                      requests_per_day=2)).reserve(100)), flush=True)
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(6)
    ]
    try:
        outputs = [p.communicate(timeout=20) for p in processes]
        assert all(p.returncode == 0 for p in processes), outputs
        assert sum(int(out.strip()) for out, _ in outputs) == 2
        assert SQLiteRequestBudget(settings).snapshot().requests == 2
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
            p.wait()


def test_subprocess_crash_retains_lease_until_expiry(tmp_path):
    path = tmp_path / "crash.sqlite3"
    script = """
import json,os,sys
from pathlib import Path
from stackchan_autonomy.control import ControlLease
held=ControlLease(Path(sys.argv[1]), 'robot', ttl_s=5, clock=lambda:100).acquire()
print(json.dumps({'generation':held.generation}),flush=True)
os._exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)], text=True, capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    old_generation = json.loads(result.stdout)["generation"]
    assert ControlLease(path, "robot", ttl_s=5, clock=lambda: 104).acquire() is None
    new = ControlLease(path, "robot", ttl_s=5, clock=lambda: 105).acquire()
    assert new.generation > old_generation


def test_request_reservation_survives_abrupt_process_exit():
    script = """
import os
from stackchan_autonomy.budget import SQLiteRequestBudget
from stackchan_autonomy.settings import Settings
assert SQLiteRequestBudget(Settings(requests_per_minute=1)).reserve(100)
os._exit(0)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=15)
    assert result.returncode == 0
    assert not SQLiteRequestBudget(Settings(requests_per_minute=1)).reserve(101)


@pytest.mark.skipif(
    not hasattr(os, "fork"), reason="fork unavailable; spawn races tested separately"
)
def test_fork_child_cannot_inherit_parent_ownership_or_mutate_parent_handle(tmp_path):
    script = """
import json,os,sys
from stackchan_autonomy.control import ControlLease
lease=ControlLease(sys.argv[1], 'robot', clock=lambda:100)
held=lease.acquire()
read,write=os.pipe()
pid=os.fork()
if pid==0:
    os.close(read)
    result={'check':lease.check(held),'acquire':lease.acquire() is not None,
            'renew':lease.renew(held),'release':lease.release(held)}
    os.write(write,json.dumps(result).encode())
    os.close(write)
    os._exit(0)
os.close(write)
data=json.loads(os.read(read,4096))
os.close(read)
_,status=os.waitpid(pid,0)
assert status==0
data['parent_still_owns']=lease.check(held)
print(json.dumps(data))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "fork.sqlite3")],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "check": False,
        "acquire": False,
        "renew": False,
        "release": False,
        "parent_still_owns": True,
    }


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_timestamps_do_not_disable_limits(value):
    with pytest.raises(ValueError):
        SQLiteRequestBudget(config()).reserve(value)
