import pytest


@pytest.fixture(autouse=True)
def isolated_coordination_state(monkeypatch, tmp_path):
    # Real CLI subprocesses inherit this path; no test spends another test's quota.
    monkeypatch.setenv("STACKCHAN_STATE_PATH", str(tmp_path / "autonomy.sqlite3"))
