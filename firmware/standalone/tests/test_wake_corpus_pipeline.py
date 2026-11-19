"""Private corpus -> SWK1 calibration -> held-out evaluation without hardware."""

import importlib.util
import json
import math
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest


@pytest.fixture
def pipeline(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "tools" / "wake_corpus_pipeline.py"
    monkeypatch.syspath_prepend(str(source.parent))
    spec = importlib.util.spec_from_file_location("wake_corpus_pipeline", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_tone(path: Path, hz: float) -> None:
    pcm = b"".join(
        struct.pack("<h", int(9500 * math.sin(2 * math.pi * hz * i / 24000))) for i in range(24000)
    )
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24000)
        writer.writeframes(pcm)


@pytest.fixture
def private_manifest(tmp_path):
    samples = []
    roles = (
        ("enrollment", "wake", "session-enrol", 1),
        ("calibration", "wake", "session-cal", 5),
        ("calibration", "nonwake", "session-cal", 10),
        ("evaluation", "wake", "session-eval", 1),
        ("evaluation", "nonwake", "session-eval", 1),
    )
    index = 0
    for stage, label, session, count in roles:
        for _ in range(count):
            index += 1
            name = f"sample_{index:03}.wav"
            _write_tone(tmp_path / name, 320 + index * 12.7)
            samples.append(
                {
                    "id": f"sample-{index:03}",
                    "stage": stage,
                    "label": label,
                    "session": session,
                    "file": name,
                }
            )
    manifest = tmp_path / "user.wake-corpus.json"
    manifest.write_text(
        json.dumps({"schema": "stackchan-private-wake-corpus-v1", "samples": samples}),
        encoding="utf-8",
    )
    return manifest, samples


def test_check_only_requires_all_separate_groups(pipeline, private_manifest):
    manifest, samples = private_manifest
    output = manifest.parent / "new.swk1"
    report = pipeline.run_pipeline(manifest, output, check_only=True)
    assert report["status"] == "PRIVATE_CORPUS_READY_FOR_OFFLINE_TOOLCHAIN"
    assert report["counts"]["calibration_nonwake"] == 10
    assert not report["profile_created"]
    assert not report["independent_evaluation_run"]
    assert not report["actual_korean_wake_accuracy_proven"]
    assert not report["device_install_authorized"]
    assert not output.exists()
    assert len(list(manifest.parent.glob("*.wav"))) == len(samples)


def test_missing_evaluation_or_duplicate_pcm_is_rejected(pipeline, private_manifest):
    manifest, samples = private_manifest
    output = manifest.parent / "new.swk1"
    shortened = [s for s in samples if s["stage"] != "evaluation"]
    manifest.write_text(
        json.dumps({"schema": "stackchan-private-wake-corpus-v1", "samples": shortened})
    )
    with pytest.raises(pipeline.PipelineRejected, match="corpus_minimum_samples_missing"):
        pipeline.run_pipeline(manifest, output, check_only=True)
    manifest.write_text(
        json.dumps({"schema": "stackchan-private-wake-corpus-v1", "samples": samples})
    )
    duplicate = manifest.parent / samples[-1]["file"]
    duplicate.write_bytes((manifest.parent / samples[0]["file"]).read_bytes())
    with pytest.raises(pipeline.PipelineRejected, match="corpus_preflight_rejected"):
        pipeline.run_pipeline(manifest, output, check_only=True)
    assert not output.exists()


def test_private_profile_output_must_not_exist(pipeline, private_manifest):
    manifest, _ = private_manifest
    output = manifest.parent / "new.swk1"
    output.write_bytes(b"PRIVATE-EXISTING-PROFILE")
    with pytest.raises(pipeline.PipelineRejected, match="unsafe_or_existing_private_output"):
        pipeline.run_pipeline(manifest, output, check_only=True)
    assert output.read_bytes() == b"PRIVATE-EXISTING-PROFILE"


def test_quality_warnings_require_manual_review(pipeline, private_manifest):
    manifest, samples = private_manifest
    output = manifest.parent / "new.swk1"
    filename = manifest.parent / samples[0]["file"]
    original = filename.read_bytes()
    filename.write_bytes(original[:44] + struct.pack("<h", 32767) * 24000)
    with pytest.raises(pipeline.PipelineRejected, match="corpus_quality_warnings_require_review"):
        pipeline.run_pipeline(manifest, output, check_only=True)
    assert not output.exists()


def test_profile_inside_source_checkout_rejected(pipeline, private_manifest):
    manifest, _ = private_manifest
    source_checkout = Path(pipeline.__file__).resolve().parents[3]
    with pytest.raises(pipeline.PipelineRejected, match="unsafe_or_existing_private_output"):
        pipeline.run_pipeline(
            manifest, source_checkout / "unapproved-private.swk1", check_only=True
        )


def test_optional_cached_zig_uses_strictly_offline_toolchain(pipeline, monkeypatch):
    monkeypatch.setattr(
        pipeline.shutil,
        "which",
        lambda executable: "C:/Tools/uvx.exe" if executable == "uvx" else None,
    )
    assert pipeline._compiler_command(offline_zig=True) == [
        "C:/Tools/uvx.exe",
        "--offline",
        "--from",
        "ziglang==0.15.2",
        "python-zig",
        "c++",
    ]
    with pytest.raises(pipeline.PipelineRejected, match="gpp_compiler_unavailable"):
        pipeline._compiler_command(offline_zig=False)
    monkeypatch.setattr(pipeline.shutil, "which", lambda _name: None)
    with pytest.raises(pipeline.PipelineRejected, match="uvx_unavailable_for_cached_zig"):
        pipeline._compiler_command(offline_zig=True)


def test_compiler_unavailable_never_creates_profile(pipeline, private_manifest, monkeypatch):
    manifest, _ = private_manifest
    output = manifest.parent / "new.swk1"
    monkeypatch.setattr(pipeline.shutil, "which", lambda _name: None)
    with pytest.raises(pipeline.PipelineRejected, match="gpp_compiler_unavailable"):
        pipeline.run_pipeline(manifest, output)
    assert not output.exists()


def test_in_process_modified_wav_is_rejected(pipeline, private_manifest, monkeypatch):
    manifest, samples = private_manifest
    output = manifest.parent / "new.swk1"
    monkeypatch.setattr(pipeline.shutil, "which", lambda _name: "g++")

    def pretend_build(*_args):
        target = manifest.parent / samples[0]["file"]
        target.write_bytes(target.read_bytes() + b"changed")

    monkeypatch.setattr(pipeline, "_build", pretend_build)
    with pytest.raises(pipeline.PipelineRejected, match="private_inputs_changed"):
        pipeline.run_pipeline(manifest, output)
    assert not output.exists()


def test_bad_eval_denominators_prevent_profile_publication(pipeline, private_manifest, monkeypatch):
    manifest, _ = private_manifest
    output = manifest.parent / "new.swk1"
    monkeypatch.setattr(pipeline.shutil, "which", lambda _name: "g++")
    monkeypatch.setattr(pipeline, "_build", lambda *_: None)

    import scfg_offline

    binary = b"SWK1" + bytes([1]) + struct.pack("<H", 256) + bytes(832)
    fake_skw1 = binary + struct.pack("<I", scfg_offline.crc32(binary))

    def fake_call(_binary, args, _timeout):
        if "--output" in args:
            Path(args[args.index("--output") + 1]).write_bytes(fake_skw1)
            return "UNVERIFIED_PRIVATE_WAKE_PROFILE_WRITTEN\n"
        return (
            "UNVERIFIED_USER_LABELED_WAKE_EVALUATION\n"
            "positive_accepted=0/3\nnegative_accepted=0/1\n"
        )

    monkeypatch.setattr(pipeline, "_call", fake_call)
    with pytest.raises(pipeline.PipelineRejected, match="unexpected_evaluation_counts"):
        pipeline.run_pipeline(manifest, output)
    assert not output.exists()


def test_output_report_never_exposes_paths(pipeline, private_manifest, tmp_path):
    manifest, _ = private_manifest
    process = subprocess.run(
        [
            sys.executable,
            str(Path(pipeline.__file__)),
            str(manifest),
            "--output",
            str(tmp_path / "PRIVATE-OUTPUT.swk1"),
            "--check-only",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert process.returncode == 0
    assert str(tmp_path) not in process.stdout
    assert "PRIVATE-OUTPUT" not in process.stdout
    assert "sample_001.wav" not in process.stdout
    assert not json.loads(process.stdout)["device_install_authorized"]


def test_actual_cpp_pipeline_on_synthetic_tones(tmp_path, pipeline):
    """Linux CI executes the real C++ fixture, enrollment and evaluator."""
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("C++20 g++ unavailable; Linux CI compiles the integration")
    root = Path(__file__).resolve().parents[1]
    fixture_binary = tmp_path / "synthetic_gen"
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
            str(root / "core"),
            str(root / "tests" / "wake_wav_enroll_fixture.cpp"),
            "-o",
            str(fixture_binary),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    subprocess.run([str(fixture_binary), str(tmp_path)], check=True, timeout=30)

    rows = [("enrollment", "wake", "enrol-session", "template.wav")]
    rows += [("calibration", "wake", "cal-session", f"holdout_{i}.wav") for i in range(5)]
    rows += [("calibration", "nonwake", "cal-session", f"negative_{i}.wav") for i in range(10)]
    rows += [
        ("evaluation", "wake", "eval-session", "eval_positive.wav"),
        ("evaluation", "nonwake", "eval-session", "eval_negative.wav"),
    ]
    samples = [
        {
            "id": f"sample-{i:03}",
            "stage": stage,
            "label": label,
            "session": session,
            "file": filename,
        }
        for i, (stage, label, session, filename) in enumerate(rows, start=1)
    ]
    manifest = tmp_path / "PRIVATE.wake-corpus.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "stackchan-private-wake-corpus-v1",
                "samples": samples,
            }
        ),
        encoding="utf-8",
    )
    profile = tmp_path / "PRIVATE.swk1"
    original_wav = (tmp_path / "eval_positive.wav").read_bytes()
    report = pipeline.run_pipeline(manifest, profile)
    assert report["status"] == "UNVERIFIED_OFFLINE_PROFILE_AND_EVALUATION"
    assert report["evaluation_user_labeled_counts"]["positive"]["total"] == 1
    assert report["evaluation_user_labeled_counts"]["negative"]["total"] == 1
    assert report["profile_created"] and report["independent_evaluation_run"]
    assert not report["independent_recordings_proven"]
    assert not report["actual_korean_wake_accuracy_proven"]
    assert not report["device_install_authorized"]
    assert profile.read_bytes().startswith(b"SWK1")
    assert (tmp_path / "eval_positive.wav").read_bytes() == original_wav
    assert not list(tmp_path.glob("stackchan-wake-*"))
    with pytest.raises(pipeline.PipelineRejected, match="unsafe_or_existing_private_output"):
        pipeline.run_pipeline(manifest, profile)
