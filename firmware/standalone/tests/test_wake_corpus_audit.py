"""Synthetic corpus fixtures: no real voices, devices, network or secrets."""

import copy
import importlib.util
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def audit_module():
    tool = Path(__file__).resolve().parents[1] / "tools" / "wake_corpus_audit.py"
    spec = importlib.util.spec_from_file_location("wake_corpus_audit", tool)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_wav(hz=450.0, *, silence=False, stereo=False):
    count = 24000
    channels = 2 if stereo else 1
    data = b"".join(
        struct.pack(
            "<h",
            0 if silence else int(10500 * math.sin(2 * math.pi * hz * i / 24000)),
        )
        * channels
        for i in range(count)
    )
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        24000,
        24000 * 2 * channels,
        2 * channels,
        16,
        b"data",
        len(data),
    )
    return header + data


@pytest.fixture
def corpus(tmp_path):
    samples = []
    roles = [
        ("enrollment", "wake", 1, "session_enroll"),
        ("calibration", "wake", 5, "session_cal"),
        ("calibration", "nonwake", 10, "session_cal"),
        ("evaluation", "wake", 1, "session_eval"),
        ("evaluation", "nonwake", 1, "session_eval"),
    ]
    number = 0
    for stage, label, count, session in roles:
        for _ in range(count):
            number += 1
            filename = f"{stage}/{label}-{number:03}.wav"
            folder = tmp_path / stage
            folder.mkdir(exist_ok=True)
            (tmp_path / filename).write_bytes(make_wav(400 + number * 13.7))
            samples.append(
                {
                    "id": f"sample-{number:03}",
                    "stage": stage,
                    "label": label,
                    "session": session,
                    "file": filename,
                }
            )
    manifest = tmp_path / "private.wake-corpus.json"
    manifest.write_text(
        json.dumps({"schema": "stackchan-private-wake-corpus-v1", "samples": samples}),
        encoding="utf-8",
    )
    return manifest, samples


def update_manifest(manifest, samples):
    manifest.write_text(
        json.dumps({"schema": "stackchan-private-wake-corpus-v1", "samples": samples}),
        encoding="utf-8",
    )


def test_complete_corpus_readonly(audit_module, corpus):
    manifest, samples = corpus
    original = manifest.read_bytes()
    wave_original = (manifest.parent / samples[0]["file"]).read_bytes()
    result = audit_module.inspect_corpus(manifest)
    assert result["status"] == "CORPUS_STRUCTURALLY_SCREENED"
    assert result["total_files"] == 18
    assert result["counts"]["enrollment_wake"] == 1
    assert result["counts"]["calibration_wake"] == 5
    assert result["counts"]["calibration_nonwake"] == 10
    assert result["counts"]["evaluation_wake"] == 1
    assert result["counts"]["evaluation_nonwake"] == 1
    assert result["missing_minimum_groups"] == []
    assert not result["safe_to_install"]
    assert not result["recorded_audio_or_device_accessed"]
    assert not result["korean_wake_accuracy_proven"]
    assert not result["recording_independence_proven"]
    assert manifest.read_bytes() == original
    assert (manifest.parent / samples[0]["file"]).read_bytes() == wave_original


def test_no_final_test_data_rejected(audit_module, corpus):
    manifest, samples = corpus
    update_manifest(manifest, [s for s in samples if s["stage"] != "evaluation"])
    report = audit_module.inspect_corpus(manifest)
    assert report["status"] == "CORPUS_COUNTS_INCOMPLETE"
    assert "evaluation_wake" in report["missing_minimum_groups"]
    assert "evaluation_nonwake" in report["missing_minimum_groups"]
    assert not report["safe_to_install"]


def test_cross_stage_session_leakage_blocked(audit_module, corpus):
    manifest, samples = corpus
    altered = copy.deepcopy(samples)
    altered[-1]["session"] = "session_cal"
    update_manifest(manifest, altered)
    with pytest.raises(audit_module.CorpusError, match="declared_session_leakage"):
        audit_module.inspect_corpus(manifest)


def test_same_pcm_under_different_names_rejected(audit_module, corpus):
    manifest, samples = corpus
    first = manifest.parent / samples[0]["file"]
    second = manifest.parent / samples[-1]["file"]
    second.write_bytes(first.read_bytes())
    with pytest.raises(audit_module.CorpusError, match="exact_pcm_duplicate_across_corpus"):
        audit_module.inspect_corpus(manifest)


@pytest.mark.parametrize(
    "filename",
    [
        "../outside.wav",
        "/absolute.wav",
        "dir\\unsafe.wav",
        "voice.mp3",
        "bad/../../x.wav",
        "bad space.wav",
    ],
)
def test_unsafe_file_path_rejected(audit_module, corpus, filename):
    manifest, samples = corpus
    altered = copy.deepcopy(samples)
    altered[0]["file"] = filename
    update_manifest(manifest, altered)
    with pytest.raises(audit_module.CorpusError):
        audit_module.inspect_corpus(manifest)


def test_format_and_silence_rejected(audit_module, corpus):
    manifest, samples = corpus
    victim = manifest.parent / samples[0]["file"]
    victim.write_bytes(make_wav(silence=True))
    with pytest.raises(audit_module.CorpusError, match="wav_silence"):
        audit_module.inspect_corpus(manifest)
    victim.write_bytes(make_wav(stereo=True))
    with pytest.raises(audit_module.CorpusError, match="wav_format_not_24k"):
        audit_module.inspect_corpus(manifest)


def test_clipping_and_dc_warnings_are_not_accuracy_claims(audit_module, corpus):
    manifest, samples = corpus
    victim = manifest.parent / samples[0]["file"]
    raw = victim.read_bytes()
    victim.write_bytes(raw[:44] + struct.pack("<h", 32767) * 24000)
    report = audit_module.inspect_corpus(manifest)
    assert report["status"] == "CORPUS_STRUCTURALLY_SCREENED"
    assert report["screening_warnings"]["possible_clipping_over_1_percent"] == 1
    assert report["screening_warnings"]["large_dc_offset"] == 1
    assert not report["korean_wake_accuracy_proven"]


def test_truncated_wav_fails_closed(audit_module, corpus):
    manifest, samples = corpus
    victim = manifest.parent / samples[0]["file"]
    victim.write_bytes(victim.read_bytes()[:50])
    with pytest.raises(audit_module.CorpusError, match="wav_riff_length_mismatch"):
        audit_module.inspect_corpus(manifest)


def test_duplicate_manifest_keys_invalid(audit_module, corpus):
    manifest, _ = corpus
    manifest.write_text('{"schema":"one","schema":"two","samples":[]}')
    with pytest.raises(audit_module.CorpusError, match="duplicate_manifest_key"):
        audit_module.inspect_corpus(manifest)


def test_symlinked_audio_blocked_if_supported(audit_module, corpus):
    manifest, samples = corpus
    target = manifest.parent / samples[-1]["file"]
    link = target.with_name("link.wav")
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation unavailable on this OS")
    altered = copy.deepcopy(samples)
    altered[-1]["file"] = str(Path(altered[-1]["file"]).with_name("link.wav")).replace("\\", "/")
    update_manifest(manifest, altered)
    with pytest.raises(audit_module.CorpusError, match="symlink_not_allowed"):
        audit_module.inspect_corpus(manifest)


def test_cli_never_prints_private_paths(audit_module, corpus):
    manifest, _ = corpus
    cmd = [sys.executable, str(Path(audit_module.__file__)), str(manifest)]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert "CORPUS_STRUCTURALLY_SCREENED" in result.stdout
    assert str(manifest) not in result.stdout
    assert "sample-001" not in result.stdout
    assert not json.loads(result.stdout)["safe_to_install"]

    manifest.write_text("{}")
    bad = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
    assert bad.returncode == 2
    assert json.loads(bad.stdout)["status"] == "REJECTED_PRIVATE_WAKE_CORPUS"
    assert str(manifest) not in bad.stdout
