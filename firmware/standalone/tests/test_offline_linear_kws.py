"""Host-only tiny discriminative MFCC model training & deployment guards."""

import hashlib
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
TOOLS = BASE / "tools"
MODEL = BASE / "fixtures" / "korean_heami_linear_kws_20261120" / "linear-kws-training-frozen.skwl"

# Model is synthetic-data only and must be committed BEFORE any new holdout
# recordings are generated. It must never be inserted into ESP-IDF firmware.
PINNED_SYNTHETIC_MODEL_SHA256 = "4aa5c14fad637790aa33b0c512bd55ad64283aae34b13a9e78ae02247b981788"


@pytest.fixture
def trainer(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    source = TOOLS / "train_synthetic_linear_kws.py"
    spec = importlib.util.spec_from_file_location("train_synthetic_linear_kws", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_training_sources_exclude_prior_evaluation(trainer, monkeypatch):
    read = trainer._read_bounded
    touched = []

    def check_path(path, limit):
        value = Path(path)
        assert "evaluation" not in value.parts
        touched.append(value)
        return read(path, limit)

    monkeypatch.setattr(trainer, "_read_bounded", check_path)
    sources = trainer.training_sources()
    assert len(sources) == 32
    assert sum(item["label"] == "wake" for item in sources) == 6
    assert sum(item["label"] == "nonwake" for item in sources) == 26
    assert all("evaluation" not in path.parts for path in touched)


def test_frozen_synthetic_linear_model_sha_and_hardware_isolation():
    assert MODEL.is_file()
    assert MODEL.stat().st_size == 847
    payload = MODEL.read_bytes()
    assert payload[:5] == b"SKWL1"
    assert hashlib.sha256(payload).hexdigest() == PINNED_SYNTHETIC_MODEL_SHA256
    assert len(payload) == 847
    hold = (BASE / "esp_app" / "main" / "app_main.cpp").read_text(encoding="utf-8")
    assert "offline_linear_kws" not in hold
    assert "wake_linear_train" not in hold
    assert "wake_linear_eval" not in hold
    assert "SKWL1" not in hold


def _compile(compiler: str, source: Path, output: Path) -> None:
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
            str(BASE / "core"),
            str(source),
            "-o",
            str(output),
        ],
        check=True,
        capture_output=True,
        timeout=100,
    )


def test_native_cpp_fake_feature_model_is_well_formed(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("Linux CI provides g++20; Windows static only")
    binary = tmp_path / "fake_linear_unit"
    _compile(compiler, BASE / "tests" / "offline_linear_kws_test.cpp", binary)
    run = subprocess.run([str(binary)], text=True, capture_output=True, check=True, timeout=30)
    assert "OFFLINE_LINEAR_KWS_FAKE_FEATURE_TEST_PASS" in run.stdout


def test_real_cpp_training_stays_offline_and_separates_old_eval(tmp_path, trainer):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("Linux CI provides g++20; Windows static only")
    learner = tmp_path / "linear_train"
    evaluator = tmp_path / "linear_eval"
    _compile(compiler, TOOLS / "wake_linear_train.cpp", learner)
    _compile(compiler, TOOLS / "wake_linear_eval.cpp", evaluator)
    output = tmp_path / "fresh_model.skwl"
    result = trainer.fit_synthetic(learner, evaluator, output)
    assert result["status"] == "FROZEN_SYNTHETIC_LINEAR_MFCC_TRAINING"
    assert output.read_bytes()[:5] == b"SKWL1"
    assert result["model_bytes"] == 847
    assert result["source_wake_utterances"] == 6
    assert result["source_nonwake_utterances"] == 26
    assert result["augmented_wake_examples"] == 30
    assert result["augmented_nonwake_examples"] == 130
    assert not result["previous_evaluation_wavs_opened"]
    assert not result["human_accuracy_proven"]
    assert not result["robot_or_paid_api_accessed"]
    assert not result["install_authorized"]

    repeated = subprocess.run(
        [str(learner), str(tmp_path / "missing.tsv"), str(output)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert repeated.returncode == 2
    assert output.stat().st_size == 847
