"""Host-only 1D CNN MFCC experiment tests. No real voice or robot."""

import hashlib
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
TOOLS = BASE / "tools"
MODEL = BASE / "fixtures" / "korean_heami_conv_kws_20261120" / "conv-kws-frozen.skwc"
MODEL_SHA = "3ed5d2aad7b933b62045c1c45e054a202bdf1b81da2fe7bd3dbd5bcd52c26cb5"


@pytest.fixture
def synth_trainer(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    source = TOOLS / "train_synthetic_conv_kws.py"
    spec = importlib.util.spec_from_file_location(source.stem, source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_model_crc_and_hardware_hold(synth_trainer):
    payload = MODEL.read_bytes()
    assert len(payload) == 1423
    assert payload[:5] == b"SKWC1"
    assert hashlib.sha256(payload).hexdigest() == MODEL_SHA
    from zlib import crc32

    assert int.from_bytes(payload[-4:], "little") == crc32(payload[:-4])

    core = (BASE / "core" / "offline_conv_kws.hpp").read_text(encoding="utf-8")
    hold = (BASE / "esp_app" / "main" / "app_main.cpp").read_text(encoding="utf-8")
    assert "kConvKwsEpochs = 650" in core
    assert "kConvKwsStep = 0.30f" in core
    assert "kConvKwsL2 = 0.004f" in core
    assert "offline_conv_kws.hpp" not in hold
    assert "wake_conv_train.cpp" not in hold
    assert "wake_conv_eval.cpp" not in hold
    assert "SKWC1" not in hold


def test_training_sources_include_only_prior_calibration_examples(synth_trainer):
    rows = synth_trainer.training_sources()
    assert len(rows) == 32
    assert sum(row["label"] == "wake" for row in rows) == 6
    assert sum(row["label"] == "nonwake" for row in rows) == 26
    assert len(synth_trainer.CONDITIONS_TRAIN) == 5
    assert synth_trainer.EXPECTED_AUG == {"wake": 30, "nonwake": 130}


def _compile(compiler, source, binary):
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
            str(binary),
        ],
        check=True,
        capture_output=True,
        timeout=110,
    )


def test_cpp_fake_features_and_corrupted_model_fail_closed(tmp_path):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("Linux CI g++; Windows checks Python/static contracts")
    binary = tmp_path / "fake_conv"
    _compile(compiler, BASE / "tests" / "offline_conv_kws_test.cpp", binary)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=35)
    assert "OFFLINE_TINY_CONV_KWS_FAKE_FEATURE_PASS" in result.stdout


def test_cpp_trainer_exercises_only_known_synthetic_development_data(synth_trainer, tmp_path):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("Linux CI g++; Windows checks Python/static contracts")
    train_cpp = tmp_path / "conv_train"
    eval_cpp = tmp_path / "conv_eval"
    _compile(compiler, TOOLS / "wake_conv_train.cpp", train_cpp)
    _compile(compiler, TOOLS / "wake_conv_eval.cpp", eval_cpp)
    model_path = tmp_path / "model.skwc"
    report = synth_trainer.train(train_cpp, eval_cpp, model_path)
    assert report["status"] == "FROZEN_SYNTHETIC_TINY_CNN_TRAINING"
    assert report["model_bytes"] == 1423
    assert report["training_base_wake_clips"] == 6
    assert report["training_base_nonwake_clips"] == 26
    assert report["training_augmented_wake_examples"] == 30
    assert report["training_augmented_nonwake_examples"] == 130
    assert not report["previous_evaluation_wavs_opened"]
    assert not report["device_install_authorized"]
    assert not report["real_human_accuracy_proven"]
    assert model_path.is_file() and model_path.read_bytes()[:5] == b"SKWC1"
    with pytest.raises(synth_trainer.SyntheticTrainRejected):
        synth_trainer.train(train_cpp, eval_cpp, model_path)  # no overwrite
