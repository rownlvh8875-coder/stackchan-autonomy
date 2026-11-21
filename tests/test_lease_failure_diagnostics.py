"""Failure reporting must preserve strict test outcomes and omit operation data."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_probe(tmp_path, outcome, *, unconditional=False):
    conftest = Path(__file__).with_name("conftest.py").read_text(encoding="utf-8")
    if unconditional:
        condition = 'report.when == "call" and report.failed and probe is not None'
        assert conftest.count(condition) == 1
        conftest = conftest.replace(condition, 'report.when == "call" and probe is not None')
    (tmp_path / "conftest.py").write_text(conftest, encoding="utf-8")
    (tmp_path / "test_probe.py").write_text(
        "import pytest\n"
        "from stackchan_autonomy.async_storage import AsyncStorage\n"
        "@pytest.mark.usefixtures('lease_timing_probe')\n"
        "async def test_probe():\n"
        "    storage = AsyncStorage()\n"
        "    try:\n"
        "        await storage.call(lambda: 'private-operation-data')\n"
        "    finally:\n"
        "        await storage.aclose()\n"
        "    "
        + {
            "fail": "assert False\n",
            "pass": "assert True\n",
            "skip": "pytest.skip('intentional')\n",
            "xfail": "pytest.xfail('intentional')\n",
        }[outcome],
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rP",
            "-s",
            "-o",
            "asyncio_mode=auto",
            "-o",
            "asyncio_default_fixture_loop_scope=function",
            "test_probe.py",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    reports = [
        json.loads(line.split("LEASE_TIMING_DIAGNOSTICS ", 1)[1])
        for line in result.stdout.splitlines()
        if line.startswith("LEASE_TIMING_DIAGNOSTICS ")
    ]
    return result, reports


@pytest.mark.parametrize("outcome", ["fail", "pass", "skip", "xfail"])
def test_opted_in_lease_timing_report(tmp_path, outcome):
    result, reports = _run_probe(tmp_path, outcome)
    fails = outcome == "fail"
    assert result.returncode == (1 if fails else 0), result.stdout + result.stderr
    assert len(reports) == int(fails), result.stdout + result.stderr
    if fails:
        timing = reports[0]["timing_diagnostics"]
        assert timing["operations"] == {"other": 1}
        assert timing["stages"]["storage_operation"]["count"] == 1
        assert "private-operation-data" not in json.dumps(reports)


def test_passing_report_negative_control_is_visible(tmp_path):
    result, reports = _run_probe(tmp_path, "pass", unconditional=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(reports) == 1, "an unconditional print escaped the success-case capture"
