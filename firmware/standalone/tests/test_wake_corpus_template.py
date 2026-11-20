"""Private manifest skeleton generation never records audio or overwrites files."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def generator():
    path = Path(__file__).resolve().parents[1] / "tools" / "wake_corpus_template.py"
    spec = importlib.util.spec_from_file_location("wake_corpus_template", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skeleton_has_disjoint_groups_and_no_audio(generator):
    manifest = generator.template()
    assert manifest["schema"] == "stackchan-private-wake-corpus-v1"
    assert len(manifest["samples"]) == 18
    roles = [(s["stage"], s["label"]) for s in manifest["samples"]]
    assert roles.count(("enrollment", "wake")) == 1
    assert roles.count(("calibration", "wake")) == 5
    assert roles.count(("calibration", "nonwake")) == 10
    assert roles.count(("evaluation", "wake")) == 1
    assert roles.count(("evaluation", "nonwake")) == 1
    assert len({s["file"] for s in manifest["samples"]}) == 18
    sessions = {
        stage: {s["session"] for s in manifest["samples"] if s["stage"] == stage}
        for stage in ("enrollment", "calibration", "evaluation")
    }
    assert not sessions["enrollment"] & sessions["calibration"]
    assert not sessions["calibration"] & sessions["evaluation"]


def test_exclusive_private_template_creation(generator, tmp_path):
    target = tmp_path / "owner.wake-corpus.json"
    assert generator.create_private_template(target)
    content = target.read_bytes()
    assert json.loads(content)["schema"] == generator.SCHEMA
    if os.name == "posix":
        assert target.stat().st_mode & 0o077 == 0
    assert not generator.create_private_template(target)
    assert target.read_bytes() == content
    assert list(tmp_path.iterdir()) == [target]


def test_cli_does_not_echo_path_or_create_recordings(generator, tmp_path):
    target = tmp_path / "CONFIDENTIAL.wake-corpus.json"
    proc = subprocess.run(
        [sys.executable, str(Path(generator.__file__)), "--output", str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0
    assert "PRIVATE_WAKE_CORPUS_TEMPLATE_CREATED" in proc.stdout
    assert "CONFIDENTIAL" not in proc.stdout
    assert not list(tmp_path.rglob("*.wav"))
    again = subprocess.run(
        [sys.executable, str(Path(generator.__file__)), "--output", str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert again.returncode == 2
    assert "CONFIDENTIAL" not in again.stdout
