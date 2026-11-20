"""Private session/persistence tests. All speech below is public synthetic replay.

Transforms are regression inputs, never counted as independent human evidence.
"""

import hashlib
import importlib
import io
import json
import wave
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
FIXTURE = BASE / "fixtures" / "korean_josu_sapi_20261120"


@pytest.fixture
def enroll(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE / "tools"))
    return importlib.import_module("pc_mic_enroll")


def test_memory_profile_score_matches_real_cpp(enroll, probe_exe):
    profile = (FIXTURE / "josu-20261120.swk1").read_bytes()
    wav = (FIXTURE / "evaluation" / "evaluation_wake_01.wav").read_bytes()
    score = enroll.score_wav(probe_exe, profile, wav)
    assert score["accepted"] and score["limit_q8"] == 1003
    with pytest.raises(enroll.EnrollmentError):
        enroll.score_wav(probe_exe, profile[:-1], wav)


def synthetic_capture(enroll):
    np = pytest.importorskip("numpy")
    from pc_mic_audio import analyze_48k

    counter = 0

    def capture(stage, label, index, prompt):
        nonlocal counter
        counter += 1
        if label == "quiet":
            raw = np.random.default_rng(counter).integers(-2, 3, 120000, dtype=np.int16)
            trimmed, diagnostic = analyze_48k(raw, np)
            assert trimmed is None
            return None, diagnostic, hashlib.sha256(raw.astype("<i2").tobytes()).digest()
        name = (
            "evaluation_wake_01.wav"
            if label == "wake"
            else f"evaluation_nonwake_{index % 6 + 1:02}.wav"
        )
        with wave.open(str(FIXTURE / "evaluation" / name), "rb") as source:
            raw = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(
                np.int32
            )
        # New noise per synthetic replay is NOT independent voice data.
        noise = np.random.default_rng(counter).normal(0, 12, len(raw))
        raw = np.clip(raw + noise, -32768, 32767).astype(np.int16)
        mic = np.concatenate(
            [np.zeros(9600, dtype=np.int16), np.repeat(raw, 2), np.zeros(9600, dtype=np.int16)]
        )
        trimmed, diag = analyze_48k(mic, np)
        assert trimmed is not None and not diag["quality_issues"]
        out = io.BytesIO()
        with wave.open(out, "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(24000)
            target.writeframes(trimmed.astype("<i2").tobytes())
        return out.getvalue(), diag, hashlib.sha256(mic.astype("<i2").tobytes()).digest()

    return capture


def test_registration_freezes_before_separate_evaluation_and_baseline_comparison(enroll, probe_exe):
    calls = []
    capture = synthetic_capture(enroll)

    def source(*args):
        calls.append(args[:3])
        return capture(*args)

    model, report = enroll.run_session(
        probe_exe, (FIXTURE / "josu-20261120.swk1").read_bytes(), source
    )
    assert model and model.startswith(b"SWK1\x03")
    assert report["status"] == "PC_SESSION_PASSED_NOT_K151_VALIDATION"
    assert report["personal"] == {
        "wake_accepted": 5,
        "wake_total": 5,
        "nonwake_accepted": 0,
        "nonwake_total": 10,
        "quiet_accepted": 0,
        "quiet_windows": 3,
    }
    assert report["baseline"]["wake_total"] == 5 and report["baseline"]["nonwake_total"] == 10
    assert report["quiet_quality_warning_windows"] == 0
    assert [s for s, _, _ in calls] == ["enrollment"] * 3 + ["calibration"] * 15 + [
        "evaluation"
    ] * 18
    assert report["raw_audio_saved"] is False and report["network_or_paid_api_used"] is False


def test_duplicate_recording_is_not_an_independent_sample(enroll, probe_exe):
    capture = synthetic_capture(enroll)
    sample = capture("enrollment", "wake", 0, "")
    with pytest.raises(enroll.EnrollmentError, match="duplicate_capture"):
        enroll.run_session(
            probe_exe, (FIXTURE / "josu-20261120.swk1").read_bytes(), lambda *args: sample
        )


@pytest.mark.parametrize("issue", ["CLIPPING", "CAPTURE_EDGE_ACTIVITY", "NO_SPEECH_ACTIVITY"])
def test_registration_rejects_bad_quality_before_feature_extraction(enroll, probe_exe, issue):
    with pytest.raises(enroll.EnrollmentError, match="capture_quality_rejected"):
        enroll.run_session(
            probe_exe,
            (FIXTURE / "josu-20261120.swk1").read_bytes(),
            lambda *args: (b"PRIVATE_AUDIO", {"quality_issues": [issue]}, bytes(32)),
        )


def test_failed_fresh_evaluation_never_returns_an_installable_profile(enroll, probe_exe):
    capture = synthetic_capture(enroll)

    def source(stage, label, index, prompt):
        if stage == "evaluation" and label == "wake" and index == 0:
            return capture(stage, "nonwake", 9, prompt)
        return capture(stage, label, index, prompt)

    model, report = enroll.run_session(
        probe_exe, (FIXTURE / "josu-20261120.swk1").read_bytes(), source
    )
    assert model is None and report["status"] == "PC_SESSION_FAILED_NEW_EVALUATION_REQUIRED"
    assert report["personal"]["wake_accepted"] < 5


def test_profile_output_is_new_ignored_file_only(enroll, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    private = root / ".local" / "josu" / "owner.swk1"
    model = (FIXTURE / "josu-20261120.swk1").read_bytes()
    enroll.save_private_profile(private, model, root)
    assert private.read_bytes() == model
    with pytest.raises(enroll.EnrollmentError):
        enroll.save_private_profile(private, model, root)
    with pytest.raises(enroll.EnrollmentError):
        enroll.save_private_profile(root / "public.swk1", model, root)
    assert not (root / "public.swk1").exists()


def test_symlink_output_directory_is_rejected(enroll, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / ".local" / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(enroll.EnrollmentError):
        enroll.save_private_profile(
            root / ".local" / "link" / "profile.swk1",
            (FIXTURE / "josu-20261120.swk1").read_bytes(),
            root,
        )
    assert list(outside.iterdir()) == []


def test_missing_explicit_record_permission_has_no_side_effects(enroll, tmp_path, capsys):
    assert enroll.main(["--output", str(tmp_path / "PRIVATE_PATH")]) == 2
    output = capsys.readouterr().out
    assert "PRIVATE_PATH" not in output
    assert json.loads(output)["status"] == "PC_ENROLLMENT_REJECTED"
    assert list(tmp_path.iterdir()) == []


def test_cancelled_prompt_never_records_or_saves(enroll, probe_exe, monkeypatch, capsys):
    monkeypatch.setattr(enroll, "select_microphone", lambda *args: (9, "fixture-identity"))
    monkeypatch.setattr("builtins.input", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    target = enroll.ROOT / ".local" / "cancelled-test-profile.swk1"
    assert not target.exists()
    assert (
        enroll.main(
            ["--enroll", "--probe-exe", str(probe_exe), "--device", "9", "--output", str(target)]
        )
        == 130
    )
    assert not target.exists() and "PC_ENROLLMENT_CANCELLED" in capsys.readouterr().out


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows CMD execution")
@pytest.mark.parametrize(
    "runner", ["build-pc-wake-probe.cmd", "run-josu-windows-mic.cmd", "enroll-josu-windows-mic.cmd"]
)
def test_windows_runners_help_has_no_build_or_record_side_effect(runner, tmp_path):
    import subprocess

    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(BASE / "tools" / runner), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0 and result.stdout and result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_failed_profile_sync_removes_the_new_file(enroll, tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / ".local" / "owner.swk1"

    def failed_sync(_):
        raise OSError("PRIVATE_DISK_DETAILS")

    monkeypatch.setattr("os.fsync", failed_sync)
    with pytest.raises(enroll.EnrollmentError, match="^private_profile_write_failed$"):
        enroll.save_private_profile(target, (FIXTURE / "josu-20261120.swk1").read_bytes(), root)
    assert not target.exists()


def test_interrupted_profile_sync_leaves_no_final_or_staging_file(enroll, tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / ".local" / "owner.swk1"

    def interrupted(_):
        raise KeyboardInterrupt

    monkeypatch.setattr("os.fsync", interrupted)
    with pytest.raises(KeyboardInterrupt):
        enroll.save_private_profile(target, (FIXTURE / "josu-20261120.swk1").read_bytes(), root)
    assert not target.exists()
    assert list((root / ".local").iterdir()) == []


def test_parent_replacement_cannot_redirect_profile_publication(enroll, tmp_path, monkeypatch):
    import os

    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = root / ".local" / "josu" / "owner.swk1"
    original_sync = os.fsync

    def swap_parent(fd):
        original_sync(fd)
        parent = target.parent
        try:
            parent.rename(parent.with_name("original"))
            parent.symlink_to(outside, target_is_directory=True)
        except OSError:
            return  # Windows directory handle must block rename.

    monkeypatch.setattr("os.fsync", swap_parent)
    try:
        enroll.save_private_profile(target, (FIXTURE / "josu-20261120.swk1").read_bytes(), root)
    except enroll.EnrollmentError:
        pass  # Fail closed is also acceptable.
    assert list(outside.iterdir()) == []


def test_parent_replacement_before_create_does_not_write_outside(enroll, tmp_path, monkeypatch):
    import os

    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = root / ".local" / "josu" / "owner.swk1"
    original_open = os.open
    swapped = False

    def intercepted(path, flags, *args, **kwargs):
        nonlocal swapped
        if flags & os.O_CREAT and not swapped:
            swapped = True
            try:
                target.parent.rename(target.parent.with_name("original"))
                target.parent.symlink_to(outside, target_is_directory=True)
            except OSError:
                pass  # Windows verified parent handles prohibit rename.
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("os.open", intercepted)
    try:
        enroll.save_private_profile(target, (FIXTURE / "josu-20261120.swk1").read_bytes(), root)
    except enroll.EnrollmentError:
        pass
    assert swapped and list(outside.iterdir()) == []


def test_duplicate_quiet_capture_cannot_count_as_fresh_windows(enroll, probe_exe):
    source = synthetic_capture(enroll)
    first_quiet = None

    def capture(stage, label, index, prompt):
        nonlocal first_quiet
        trial = source(stage, label, index, prompt)
        if label == "quiet":
            if first_quiet is None:
                first_quiet = trial
            return first_quiet
        return trial

    with pytest.raises(enroll.EnrollmentError, match="^duplicate_capture$"):
        enroll.run_session(probe_exe, (FIXTURE / "josu-20261120.swk1").read_bytes(), capture)


def test_frontend_passes_private_raw_digest_without_logging_it(
    enroll, probe_exe, monkeypatch, capsys
):
    import sys

    np = pytest.importorskip("numpy")

    class AudioDevice:
        descriptor = {
            "name": "Specific notebook microphone",
            "hostapi": 0,
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_low_input_latency": 0.01,
            "default_high_input_latency": 0.1,
            "default_low_output_latency": 0.0,
            "default_high_output_latency": 0.0,
            "default_samplerate": 48000.0,
        }

        def query_devices(self, index=None, kind=None):
            return [self.descriptor] if index is None else self.descriptor

        def query_hostapis(self, index):
            return {
                "name": "Windows WASAPI",
                "devices": [0],
                "default_input_device": 0,
                "default_output_device": -1,
            }

        def check_input_settings(self, **kwargs):
            assert kwargs == {"device": 0, "channels": 1, "samplerate": 48000, "dtype": "int16"}

        def rec(self, frames, **kwargs):
            assert frames == 120000 and kwargs == {
                "samplerate": 48000,
                "channels": 1,
                "device": 0,
                "dtype": "int16",
                "blocking": True,
            }
            return np.zeros((frames, 1), dtype=np.int16)

        def get_status(self):
            return False

    monkeypatch.setitem(sys.modules, "sounddevice", AudioDevice())
    monkeypatch.setattr("builtins.input", lambda _: "")

    def inspect_capture(probe, baseline, capture):
        wav, diagnostic, digest = capture("evaluation", "quiet", 0, "quiet")
        assert wav is None and diagnostic["quality_issues"] == ["NO_SPEECH_ACTIVITY"]
        assert digest == hashlib.sha256(bytes(240000)).digest()
        return None, {"status": "CAPTURE_BOUNDARY_EXERCISED"}

    monkeypatch.setattr(enroll, "run_session", inspect_capture)
    target = enroll.ROOT / ".local" / "capture-boundary-profile.swk1"
    assert (
        enroll.main(
            [
                "--enroll",
                "--probe-exe",
                str(probe_exe),
                "--device",
                "0",
                "--seconds",
                "2.5",
                "--output",
                str(target),
            ]
        )
        == 3
    )
    output = capsys.readouterr().out
    assert hashlib.sha256(bytes(240000)).hexdigest() not in output
    assert not target.exists()


@pytest.mark.parametrize("issue", ["CAPTURE_EDGE_ACTIVITY", "CLIPPING"])
@pytest.mark.parametrize("false_wake", [False, True])
def test_quiet_background_edge_is_scored_not_discarded(enroll, probe_exe, false_wake, issue):
    source = synthetic_capture(enroll)

    def capture(stage, label, index, prompt):
        if label != "quiet":
            return source(stage, label, index, prompt)
        wav, diagnostic, digest = source(stage, "wake" if false_wake else "nonwake", index, prompt)
        diagnostic["quality_issues"] = [issue]
        return wav, diagnostic, digest

    model, report = enroll.run_session(
        probe_exe, (FIXTURE / "josu-20261120.swk1").read_bytes(), capture
    )
    assert report["personal"]["quiet_windows"] == 3
    assert report["quiet_quality_warning_windows"] == 3
    if false_wake:
        assert model is None and report["personal"]["quiet_accepted"] > 0
        assert report["status"] == "PC_SESSION_FAILED_NEW_EVALUATION_REQUIRED"
    else:
        assert model is not None and report["personal"]["quiet_accepted"] == 0


def test_quiet_malformed_audio_is_not_silently_counted_as_correct_rejection(enroll, probe_exe):
    source = synthetic_capture(enroll)

    def capture(stage, label, index, prompt):
        if label != "quiet":
            return source(stage, label, index, prompt)
        return (
            b"PRIVATE_MALFORMED_AUDIO",
            {"quality_issues": ["CAPTURE_EDGE_ACTIVITY"]},
            hashlib.sha256(b"fresh").digest(),
        )

    with pytest.raises(enroll.EnrollmentError, match="^invalid_wave$"):
        enroll.run_session(probe_exe, (FIXTURE / "josu-20261120.swk1").read_bytes(), capture)


def test_quiet_valid_pcm_below_feature_floor_counts_as_rejection_not_io_failure(enroll, probe_exe):
    np = pytest.importorskip("numpy")
    source = synthetic_capture(enroll)

    def capture(stage, label, index, prompt):
        if label != "quiet":
            return source(stage, label, index, prompt)
        raw = np.random.default_rng(900 + index).integers(-2, 3, 24000, dtype=np.int16)
        out = io.BytesIO()
        with wave.open(out, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(24000)
            stream.writeframes(raw.astype("<i2").tobytes())
        return (
            out.getvalue(),
            {"quality_issues": ["CAPTURE_EDGE_ACTIVITY"]},
            hashlib.sha256(raw.tobytes()).digest(),
        )

    model, report = enroll.run_session(
        probe_exe, (FIXTURE / "josu-20261120.swk1").read_bytes(), capture
    )
    assert model is not None and report["personal"]["quiet_accepted"] == 0
    assert report["personal"]["quiet_windows"] == 3


def test_feature_bearing_nonwake_cannot_pass_on_inconsistent_null_score(
    enroll, probe_exe, monkeypatch
):
    source = synthetic_capture(enroll)
    real_score = enroll.score_wav
    current = {}

    def capture(stage, label, index, prompt):
        current.update(stage=stage, label=label)
        return source(stage, label, index, prompt)

    def inconsistent(probe, profile, wav):
        result = real_score(probe, profile, wav)
        if current.get("stage") == "evaluation" and current.get("label") == "nonwake":
            return dict(result, accepted=False, distance_q8=None)
        return result

    monkeypatch.setattr(enroll, "score_wav", inconsistent)
    with pytest.raises(enroll.EnrollmentError, match="^inconsistent_helper_feature$"):
        enroll.run_session(probe_exe, (FIXTURE / "josu-20261120.swk1").read_bytes(), capture)
