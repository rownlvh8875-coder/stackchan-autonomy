"""Source-only K151 go/no-go report never approves installing firmware."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "readiness_snapshot.py"


def load_module():
    spec = importlib.util.spec_from_file_location("readiness_snapshot", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readiness_source_gate_is_not_install_approval():
    result = load_module().inspect_readiness(ROOT)
    assert result["source_checks_all_pass"]
    assert result["status"] == "NOT_APPROVED_FOR_DEVICE_INSTALLATION"
    assert len(result["physical_proofs_not_verified_here"]) >= 10
    assert result["install_authorized"] is False
    assert result["hardware_accessed"] is False
    assert result["firmware_or_ota_modified"] is False


def test_readiness_rejects_missing_invariants(tmp_path):
    module = load_module()
    assert module.inspect_readiness(ROOT)["source_checks_all_pass"]
    fake = tmp_path / "fake"
    (fake / "core").mkdir(parents=True)
    (fake / "esp_app/main").mkdir(parents=True)
    (fake / "esp_app/NOT_APPROVED_FOR_DEVICE_INSTALLATION.txt").write_text("hold")
    for name in (
        "core/k151_output_evidence.hpp",
        "core/audio_memory_admission.hpp",
        "esp_app/main/k151_codec_port.cpp",
        "esp_app/main/app_main.cpp",
    ):
        (fake / name).write_text("not a real firmware", encoding="utf-8")
    report = module.inspect_readiness(fake)
    assert report["status"] == "BLOCKED_SOURCE_REGRESSION"
    assert report["install_authorized"] is False
    assert not report["source_checks_all_pass"]


def test_readiness_cli_does_not_expose_private_paths():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    report = json.loads(completed.stdout)
    assert report["status"] == "NOT_APPROVED_FOR_DEVICE_INSTALLATION"
    assert report["api_or_network_accessed"] is False
    assert "C:\\Users" not in completed.stdout
    assert completed.stderr == ""


def test_readiness_missing_source_is_not_success(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report["install_authorized"] is False
    assert report["status"] == "SOURCE_UNAVAILABLE"
