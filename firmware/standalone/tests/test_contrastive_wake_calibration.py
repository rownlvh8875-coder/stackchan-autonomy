"""Offline hard-negative calibration and contrastive policy regression."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
HARDNEG = ROOT / "fixtures" / "korean_heami_hardneg_20261120"


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    source = TOOLS / "experiment_contrastive_calibration.py"
    spec = importlib.util.spec_from_file_location("experiment_contrastive_calibration", source)
    assert spec is not None and spec.loader is not None
    imported = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(imported)
    return imported


def test_hard_negative_asset_hash_and_labels(module):
    rows = (HARDNEG / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 17
    for row in rows:
        expected, filename = row.split("  ", maxsplit=1)
        assert len(expected) == 64
        assert not filename.startswith("/") and ".." not in Path(filename).parts
        path = HARDNEG / filename
        assert path.is_file() and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    assert len(list(HARDNEG.rglob("*.wav"))) == 16
    with (HARDNEG / "hard-negative-calibration.json").open(encoding="utf-8") as source:
        manifest = json.load(source)
    assert len(manifest["labels"]) == 16
    assert all(
        row["label"] == "nonwake" and row["role"] == "calibration" for row in manifest["labels"]
    )
    bank, developer_probes = module.private_hardneg(HARDNEG)
    assert len(bank) == len(developer_probes) == 8
    assert len({row["id"] for row in bank + developer_probes}) == 16


def test_contrastive_never_changes_firmware_or_frozen_training_profile(module):
    assert module.NONWAKE_MARGIN == 2.0
    assert module.BANK_FIRST_N == 8
    assert module.DEVELOPMENT_NEG_PROBES == 8
    header = (ROOT / "core" / "offline_contrastive_wake.hpp").read_text(encoding="utf-8")
    policy = (ROOT / "tools" / "wake_contrastive_eval.cpp").read_text(encoding="utf-8")
    hold = (ROOT / "esp_app" / "main" / "app_main.cpp").read_text(encoding="utf-8")
    assert "kContrastiveNonwakeMargin = 2.0f" in header
    assert "offline_contrastive_wake(" in header
    assert "STACKCHAN_EXPERIMENTAL_WAKE_TRIM" not in hold
    assert "offline_contrastive_wake.hpp" not in hold
    assert "wake_contrastive_eval.cpp" not in hold
    assert "--calibration-negative" in policy
    assert "REJECTED_OFFLINE_CONTRASTIVE_TEST" in policy
    assert "UNVERIFIED_CALIBRATION_ONLY_CONTRASTIVE_WAKE" in policy


def test_cpp_false_accept_veto_host(tmp_path):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("g++ absent on this host; Linux CI supplies compiler")
    binary = tmp_path / "contrastive_policy"
    subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(ROOT / "core"),
            str(ROOT / "tests" / "offline_contrastive_wake_test.cpp"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        check=True,
        timeout=90,
    )
    done = subprocess.run([str(binary)], capture_output=True, text=True, check=True, timeout=25)
    assert "CONTRASTIVE_FAKE_FEATURE_POLICY_PASS" in done.stdout


def test_real_cpp_calibration_only_experiment(module):
    if not shutil.which("g++"):
        pytest.skip("g++ absent on this host; Linux CI runs the C++ integration")
    report = module.experiment(HARDNEG)
    assert report["status"] == "SYNTHETIC_CONTRASTIVE_CALIBRATION_ONLY"
    assert report["bank_old_calibration_nonwake"] == 10
    assert report["bank_new_nonwake"] == 8
    assert report["development_nonwake"] == 8
    assert report["development_wake"] == 5
    assert report["fixed_margin_ratio"] == 2.0
    assert not report["evaluation_files_opened"]
    assert not report["candidate_deployment_authorized"]
    assert not report["physical_robot_accessed"]
    for condition, evaluations in report["conditions"].items():
        original = evaluations["positive_profile_only"]
        veto = evaluations["contrastive_filter"]
        if "status" in original or "status" in veto:
            assert original == {"status": "fail_closed_without_counts"}
            assert veto == {"status": "fail_closed_without_counts"}
            continue
        assert veto["positive"]["accepted"] <= original["positive"]["accepted"]
        assert veto["negative"]["accepted"] <= original["negative"]["accepted"]
        assert veto["positive"]["total"] == 5
        assert veto["negative"]["total"] == 8
