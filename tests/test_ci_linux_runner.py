"""Prevent moving Linux runner tags and unbounded apt retries in offline CI."""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def test_ci_linux_runner_is_explicit_stable_target():
    config = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    matrix = config["jobs"]["verify"]["strategy"]["matrix"]
    assert matrix["os"] == ["ubuntu-24.04", "windows-latest"]
    assert matrix["python"] == ["3.11", "3.12"]


def test_codec_dependencies_have_bounded_network_retries():
    config = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = config["jobs"]["verify"]["steps"]
    linux = next(step for step in steps if step.get("name") == "Install Linux codec")
    assert linux["if"] == "runner.os == 'Linux'"
    assert "apt-get -o Acquire::Retries=3 update" in linux["run"]
    assert "apt-get -o Acquire::Retries=3 install --yes libopus0 libcjson-dev" in linux["run"]
