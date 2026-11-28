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
    job = config["jobs"]["verify"]
    assert job["timeout-minutes"] == 20
    steps = job["steps"]
    linux = next(step for step in steps if step.get("name") == "Install Linux codec")
    assert linux["if"] == "runner.os == 'Linux'"
    run = linux["run"]
    assert "URIs: https://archive.ubuntu.com/ubuntu/" in run
    assert "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg" in run
    options = run.split("apt_options=(\n", 1)[1].split("\n)\n", 1)[0]
    assert [line.strip() for line in options.splitlines()] == [
        "-o Dir::Etc::sourcelist=/dev/null",
        '-o "Dir::Etc::sourceparts=$sources_dir"',
        "-o Acquire::Retries=3",
    ]
    commands = [line for line in run.splitlines() if line.startswith("sudo apt-get ")]
    assert commands == [
        'sudo apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update',
        'sudo apt-get "${apt_options[@]}" install --yes libopus0 libcjson-dev',
    ]
