"""Actual dormant port, pinned codec headers, host-only driver C ABI doubles."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
SDK = BASE / "tests/sdk_esp_codec_dev_1_6_2"


def test_pinned_codec_headers():
    proof = json.loads((SDK / "provenance.json").read_text())
    for name, expected in proof["files"].items():
        assert hashlib.sha256((SDK / name).read_bytes()).hexdigest() == expected


def test_sdk_bytes_survive_windows_git_checkout(tmp_path):
    git = shutil.which("git")
    if not git:
        pytest.skip("Git required for checkout conversion regression")
    repo = tmp_path / "repo"
    relative = Path("firmware/standalone/tests/sdk_esp_codec_dev_1_6_2")
    (repo / relative.parent).mkdir(parents=True)
    shutil.copytree(SDK, repo / relative)
    shutil.copyfile(BASE.parents[1] / ".gitattributes", repo / ".gitattributes")
    checkout = tmp_path / "checkout"
    commands = [
        [git, "-c", "core.autocrlf=true", "init", "--quiet", str(repo)],
        [git, "-C", str(repo), "-c", "core.autocrlf=true", "add", "--all"],
        [
            git,
            "-C",
            str(repo),
            "-c",
            "core.autocrlf=true",
            "checkout-index",
            "--all",
            "--prefix=" + checkout.as_posix() + "/",
        ],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    proof = json.loads((SDK / "provenance.json").read_text())
    for name, expected in proof["files"].items():
        assert hashlib.sha256((checkout / relative / name).read_bytes()).hexdigest() == expected


@pytest.fixture(scope="module")
def port_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("codec-io") / "codec"
    return _build_port(compiler, binary, BASE / "esp_app/main")


@pytest.fixture(scope="module")
def embedded_trial_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("embedded-mic-trial") / "embedded-mic-trial"
    return _build_port(compiler, binary, BASE / "esp_app/main", embedded_trial=True)


def _build_port(
    compiler, binary, app, *, embedded_trial=False, speaker_probe=False, conversation=False
):
    sources = [
        BASE / "tests/k151_codec_io_test.cpp",
        app / "k151_codec_port.cpp",
        app / "k151_bounded_i2s.cpp",
        app / "k151_mic_wake_trial.cpp",
        app / "k151_question_trial.cpp",
    ]
    command = [
        compiler,
        "-std=c++20",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-DCONFIG_CODEC_ES7210_SUPPORT=1",
        "-DCONFIG_CODEC_AW88298_SUPPORT=1",
    ]
    command += ["-isystem", str(SDK)]  # Unmodified vendor C anonymous unions.
    if speaker_probe:
        command += [
            "-DSTACKCHAN_K151_SPEAKER_PROBE=1",
            "-DSTACKCHAN_K151_SPEAKER_STOP_PROBE=1",
            "-I",
            str(BASE / "tests/lcd_io_doubles"),
        ]
        sources += [
            app / "k151_speaker_probe.cpp",
            app / "k151_speaker_stop_probe.cpp",
            app / "k151_install_hold.cpp",
        ]
    if conversation:
        command += ["-DSTACKCHAN_K151_CONVERSATION_IMAGE=1"]
    for directory in [
        BASE / "tests/codec_io_doubles",
        BASE / "tests/idf_partition_doubles",
        BASE / "resource_bench/main",
        BASE / "core",
        app,
    ]:
        command += ["-I", str(directory)]
    if embedded_trial:
        command += ["-DSTACKCHAN_TEST_EMBEDDED_MIC_TRIAL=1"]
        command += ["-I", str(BASE / "tests/sdk_esp_sr_2_4_7")]
        sources += [
            BASE / "tests/k151_wakenet_port_test.cpp",
            app / "k151_wakenet_port.cpp",
            app / "k151_model_assets.cpp",
            app / "k151_embedded_assets.cpp",
            app / "k151_mic_wake_trial_embedded.cpp",
        ]
    result = subprocess.run(
        command + [str(p) for p in sources] + ["-o", str(binary)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.fixture(scope="module")
def speaker_probe_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("speaker-probe") / "speaker"
    return _build_port(compiler, binary, BASE / "esp_app/main", speaker_probe=True)


@pytest.mark.parametrize(
    ("case", "outcome"),
    [
        ("playing", "screen_stop_and_standby_observed"),
        ("early", "screen_stop_before_playing"),
        ("host", "host_stopped"),
        ("no_touch", "completed_no_stop"),
        ("cue_not_sent", "screen_stop_timing_unverified"),
        ("write_fault", "cleanup_failed"),
        ("sticky_sws", "cleanup_failed"),
        ("sticky_sws_tx_active", "cleanup_failed"),
        ("cleanup", "cleanup_failed"),
    ],
)
def test_combined_speaker_stop_and_standby(speaker_probe_binary, case, outcome):
    import json

    process = subprocess.run(
        [str(speaker_probe_binary), f"speaker_probe_screen_stop_{case}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stderr
    wire = process.stdout.splitlines()[-1]
    assert len(wire.encode("ascii")) + 1 <= 512
    report = json.loads(wire)
    assert report["result"] == outcome
    assert report["speaker_probe"] == "K151_SPEAKER_STOP_V3"
    assert report["pcm_blocks"] == {"early": 0, "no_touch": 250, "write_fault": 2}.get(case, 3)
    assert report["dma_complete"] is (case == "no_touch")
    assert report["standby_confirmed"] is (
        case in {"playing", "host", "no_touch", "cue_not_sent", "cleanup"}
    )
    if case == "playing":
        assert report["sample_to_standby_us"] == 5_000
    else:
        assert report["sample_to_standby_us"] is None
    assert report["stop_diagnostic"] == {
        "screen_stop_sampled": case not in {"host", "no_touch"},
        "pcm_write_rejected": case == "write_fault",
        "cleanup_stage": {"sticky_sws": 20, "sticky_sws_tx_active": 2}.get(case, 0),
        "reset_latch_verified": case.startswith("sticky_sws"),
        "tx_idle_observed": case not in {"early", "sticky_sws_tx_active"},
        "sample_to_reset_idle_us": 5_000 if case == "sticky_sws" else None,
    }


@pytest.mark.parametrize(
    ("case", "stage"),
    [("settles", 0), ("timeout", 23), ("read_failure", 24)],
)
def test_host_stop_checks_switching_before_closing_i2s(speaker_probe_binary, case, stage):
    import json

    process = subprocess.run(
        [str(speaker_probe_binary), f"speaker_probe_screen_stop_host_switch_{case}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout.splitlines()[-1])
    assert report["result"] == ("cleanup_failed" if stage else "host_stopped")
    assert report["pcm_blocks"] == 5
    assert report["dma_complete"] is False
    assert report["standby_confirmed"] is (stage == 0)
    assert report["sample_to_standby_us"] is None
    assert report["stop_diagnostic"] == {
        "screen_stop_sampled": False,
        "pcm_write_rejected": False,
        "cleanup_stage": stage,
        "reset_latch_verified": stage != 0,
        "tx_idle_observed": True,
        "sample_to_reset_idle_us": None,
    }


@pytest.fixture(scope="module")
def conversation_audio_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    binary = tmp_path_factory.mktemp("conversation-audio") / "conversation"
    return _build_port(compiler, binary, BASE / "esp_app/main", conversation=True)


@pytest.mark.parametrize(
    "case",
    [
        "transient_uvls",
        "persistent_uvls",
        "unarmed",
        "stop_during_reply",
        "second_clean",
        "second_uvls",
        "second_sticky_switch",
    ],
)
def test_conversation_audio_capture_playback_and_return(conversation_audio_binary, case):
    result = subprocess.run(
        [str(conversation_audio_binary), f"conversation_audio_{case}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "ok",
        "settling_uvls",
        "stop_during_settling",
        "denied",
        "stop_before",
        "stop_write",
        "write_failure",
        "dma_failure",
        "mute_failure",
        "switch_settles",
        "switch_retained_without_codec_clock",
        "switching_after_tx_stop",
        "tx_stays_enabled_after_close",
        "standby_read_delivered_late",
        "stop_waiting_standby",
        "standby_clock_fault",
        "standby_status_read_failure",
        "standby_switch_read_failure",
        "standby_amplifier_request",
        "stop_setting_standby",
        "codec_open",
        "codec_ready",
        "tx_state",
        "volume",
        "clock_failure",
        "uvls_sample",
        "uvls_before_tx",
        "uvls_before_codec_init",
        "uvls_after_codec_init",
        "uvls_pre_tx_read_failed",
        "stop_on_pre_tx_status",
        "uvls_not_seen",
        "uvls_read_failed",
        "uvls_followup_clear",
        "uvls_followup_read_failed",
        "clock_and_release_failure",
        "paired",
        "release_failure",
        "write_and_release_failure",
    ],
)
def test_speaker_probe_runs_without_rx_and_uses_real_codec_guard(speaker_probe_binary, case):
    result = subprocess.run(
        [str(speaker_probe_binary), f"speaker_probe_{case}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mode",
    [
        "ok",
        "short",
        "overcount",
        "driver_fail",
        "clock_negative",
        "clock_backwards",
        "deadline",
        "base_lost",
        "denied",
        "invalid",
        "format_fail",
        "enable_fail",
        "disable_fail",
        "boundary",
        "reentrant",
        "write_ok",
        "write_short",
        "write_fail",
        "write_deadline",
        "halfduplex",
        "bad_rate",
        "bad_bits",
        "bad_channel",
        "bad_mask",
        "bad_mclk",
        "bad_type",
        "enable_unformatted",
        "read_unopened",
        "reformat_active",
        "reader_denied",
        "reader_bad_size",
        "null_open",
        "null_format",
        "null_enable",
        "null_read",
        "null_write",
        "info_fail",
        "tx_callback_failed",
        "duplex_board_wrong_pmic",
        "borrowed_bus_ok",
        "borrowed_bus_stop",
        "borrowed_bus_wrong",
        "borrowed_bus_unregistered",
        "borrowed_bus_bad_pmic",
        "borrowed_bus_busy",
        "duplex_board_wrong_mode",
        "duplex_board_stop_in_reset",
        "duplex_board_stop_after_release",
        "duplex_board_tx_enable_failure",
        "duplex_board_wrong_amp",
        "duplex_board_unmuted",
        "duplex_board_switch_active",
        "duplex_runtime_prepared_idle",
        "duplex_runtime_prepare_disable_failure",
        "duplex_runtime_wrong_evidence",
        "duplex_runtime_ok",
        "duplex_runtime_short_prime",
        "duplex_runtime_stop_at_prime",
        "duplex_runtime_close_tx_failure",
        "duplex_runtime_hold_playback",
        "ctrl_out_init_read",
        "ctrl_out_init_write",
        "ctrl_in_init_read",
        "ctrl_in_init_write",
        "ctrl_in_open_read",
        "ctrl_in_open_write",
        "ctrl_in_gain_read",
        "ctrl_in_gain_write",
        "ctrl_in_close_read",
        "ctrl_in_close_write",
        "ctrl_in_delete_read",
        "ctrl_in_delete_write",
        "release_rx",
        "release_tx",
        "release_both",
        "release_rx_info",
        "release_bus_live_error",
        "release_bus_freed_error",
        "ctrl_out_delete_read",
        "ctrl_out_delete_write",
        "mic_only_gates",
        "mic_only_board_bad_pmic",
        "mic_only_board_rails_off",
        "mic_only_board_bad_expander",
        "mic_only_board_input_pin",
        "mic_only_board_led_mode",
        "mic_only_board_read_error",
        "mic_only_board_write_error",
        "mic_only_board_bad_readback",
        "mic_only_board_stop_on_write",
        "mic_only_board_cleanup",
        "mic_only_board_cleanup_busy",
        "mic_only_board_already_held",
        "mic_only_peer",
        "mic_only_ok",
        "mic_only_output",
        "mic_only_short",
        "mic_only_revoke",
        "mic_only_stop_open",
        "mic_only_stop_read",
        "mic_only_release_latched",
        "mic_only_close_failure",
        "mic_only_wakenet",
        "mic_only_wakenet_late_stop",
        "mic_only_stop_before_read",
        "mic_only_trial_ok",
        "mic_only_trial_input_counts",
        "mic_only_trial_unread_counts_after_denial",
        "mic_only_trial_evidence",
        "mic_only_trial_owner",
        "mic_only_trial_format",
        "mic_only_trial_stop_before",
        "mic_only_trial_reset_fail",
        "mic_only_trial_stop_on_reset",
        "mic_only_trial_stop_on_open",
        "mic_only_trial_stop_in_read",
        "mic_only_trial_stop_in_detect",
        "mic_only_trial_revoke_in_detect",
        "mic_only_trial_stop_on_close",
        "mic_only_trial_stop_on_drop",
        "mic_only_trial_short",
        "mic_only_trial_clock_backwards",
        "mic_only_trial_slow_detect",
        "mic_only_trial_model_error",
        "mic_only_trial_close_fail",
        "mic_only_trial_delete_fail",
        "mic_only_trial_wall",
        "mic_only_trial_frame_cap",
        "mic_only_trial_live_low_memory",
        "mic_only_trial_live_fragmented",
        "mic_only_trial_live_bad_metrics",
        "mic_only_trial_stop_during_memory_check",
        "mic_only_trial_revoke_during_memory_check",
    ],
)
def test_actual_port_fault_boundaries(port_binary, mode):
    result = subprocess.run([str(port_binary), mode], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_firmware_mic_report_matches_host_contract(port_binary, monkeypatch):
    monkeypatch.syspath_prepend(str(BASE / "tools"))
    from wake_bench_trace import parse_mic_wake_trial_report

    command = subprocess.run(
        [str(port_binary), "mic_report"], capture_output=True, text=True, timeout=10
    )
    assert command.returncode == 0, command.stderr
    lines = command.stdout.splitlines()
    assert len(lines) == 6
    reports = [parse_mic_wake_trial_report(json.loads(line)) for line in lines]
    assert [r["result"] for r in reports] == [
        "detected",
        "not_detected",
        "stopped",
        "fault",
        "denied",
        "memory_denied",
    ]
    assert all(r["operating_admission"] is False for r in reports)
    assert [
        (r["frames_read"], r["all_zero_frames"], r["full_scale_samples"]) for r in reports[:2]
    ] == [(4, 1, 6), (4, 1, 6)]
    assert all("frames_read" not in r for r in reports[2:])
    for case, expected in (
        ("mic_only_trial_input_counts", reports[0]),
        ("mic_only_trial_stop_on_drop", reports[2]),
    ):
        trial = subprocess.run([str(port_binary), case], capture_output=True, text=True, timeout=10)
        assert trial.returncode == 0, trial.stderr
        assert parse_mic_wake_trial_report(json.loads(trial.stdout)) == expected


@pytest.mark.parametrize(
    ("case", "result", "frames", "stage"),
    [
        ("ok", "detected", 4, "complete"),
        ("bad_hash", "fault", None, "model_prepare"),
        ("memory", "memory_denied", None, "resident_memory"),
        ("short_read", "fault", None, "capture_read"),
        ("stop_in_detect", "stopped", None, "wake_input"),
    ],
)
def test_embedded_pack_to_mic_report(
    embedded_trial_binary, monkeypatch, case, result, frames, stage
):
    monkeypatch.syspath_prepend(str(BASE / "tools"))
    from wake_bench_trace import parse_mic_wake_trial_report

    trial = subprocess.run(
        [str(embedded_trial_binary), "mic_only_trial_chain_" + case],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert trial.returncode == 0, trial.stderr
    report = parse_mic_wake_trial_report(json.loads(trial.stdout))
    assert report["result"] == result
    assert report["mic_wake_trial"] == "MIC_WAKE_TRIAL_V4"
    assert report["stage"] == stage
    assert report["codec_cleanup_unverified"] is False
    assert report.get("frames_read") == frames
    if frames is not None:
        assert report["all_zero_frames"] == report["full_scale_samples"] == 0


@pytest.mark.parametrize(
    ("case", "result", "stage", "cleanup"),
    [
        ("trial_format", "fault", "input_format", False),
        ("trial_reset_fail", "fault", "model_reset", False),
        ("trial_stop_on_reset", "stopped", "model_reset", False),
        ("i2c_bus_fail", "fault", "i2c_bus", False),
        ("board_bad_pmic", "fault", "board_power", False),
        ("board_rails_off", "fault", "board_power", False),
        ("board_led_mode", "fault", "amplifier_reset", False),
        ("board_bad_readback", "fault", "amplifier_reset", False),
        ("board_cleanup_busy", "fault", "board_release", False),
        ("peer", "fault", "i2s_rx", False),
        ("codec_prepare_fail", "fault", "codec_prepare", False),
        ("codec_open_fail", "fault", "codec_open", False),
        ("codec_open_reg_error", "fault", "codec_open", False),
        ("codec_open_and_cleanup_error", "fault", "codec_open", True),
        ("trial_clock_backwards", "fault", "capture_clock", False),
        ("trial_short", "fault", "capture_read", False),
        ("trial_model_error", "fault", "wake_input", False),
        ("trial_delete_fail", "fault", "codec_release", True),
        ("trial_short_cleanup_bad", "fault", "capture_read", True),
    ],
)
def test_mic_trial_attributes_primary_and_cleanup(
    port_binary, monkeypatch, case, result, stage, cleanup
):
    monkeypatch.syspath_prepend(str(BASE / "tools"))
    from wake_bench_trace import parse_mic_wake_trial_report

    attempt = subprocess.run(
        [str(port_binary), "mic_only_" + case, "--report"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert attempt.returncode == 0, attempt.stderr
    report = parse_mic_wake_trial_report(json.loads(attempt.stdout))
    assert report["result"] == result and report["stage"] == stage
    assert report["codec_cleanup_unverified"] is cleanup
    assert "frames_read" not in report


@pytest.mark.parametrize(
    ("case", "result", "reason"),
    [
        ("invalid_start", "fault", "invalid_start"),
        ("clock_backwards", "fault", "clock_rollback"),
        ("transient_rollback", "fault", "clock_rollback"),
        ("poll_gap", "fault", "poll_gap_exceeded"),
        ("slow_detect", "fault", "poll_duration_exceeded"),
        ("window_overrun", "fault", "capture_window_exceeded"),
        ("poll_gap_boundary", "detected", None),
        ("poll_duration_boundary", "detected", None),
        ("window_boundary", "not_detected", None),
    ],
)
def test_k151_wake_clock_reason(port_binary, case, result, reason, monkeypatch):
    monkeypatch.syspath_prepend(str(BASE / "tools"))
    from wake_bench_trace import parse_mic_wake_trial_report

    attempt = subprocess.run(
        [str(port_binary), "mic_only_trial_" + case, "--report"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert attempt.returncode == 0, attempt.stderr
    report = parse_mic_wake_trial_report(json.loads(attempt.stdout))
    assert report["result"] == result
    assert report.get("clock_reason") == reason
    assert report["mic_wake_trial"] == "MIC_WAKE_TRIAL_V4"
    assert report["stage"] == ("capture_clock" if reason else "complete")
    assert ("frames_read" in report) is (reason is None)


@pytest.mark.parametrize(
    "case",
    [
        "endpoint",
        "no_wake",
        "wake_paced_deadline",
        "wake_cue_deadline",
        "wake_detect_at_deadline",
        "wake_detect_over_deadline",
        "no_memory",
        "bad_placement",
        "wall",
        "frame_cap",
        "stop_at_cue",
        "revoke",
        "short",
        "clock",
        "release_fail",
        "wake_tail",
        "tail_then_question",
        "interrupted_quiet",
        "quiet_timeout",
        "quiet_at_deadline",
        "handoff_stop",
        "handoff_short",
        "control_complete",
        "control_gate_stop",
        "control_stop_on_last_read",
        "control_short_read",
        "control_endpoint",
        "control_release_fail",
        "control_local_limit",
        "standard_gate_stop",
    ],
)
def test_question_after_verified_wake(port_binary, case, monkeypatch):
    attempt = subprocess.run(
        [str(port_binary), "mic_only_trial_question_" + case],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert attempt.returncode == 0, attempt.stderr
    deadline_progress = {
        "wake_paced_deadline": (486, 151, "none", "mic_read"),
        "wake_cue_deadline": (500, 155, "none", "mic_read"),
        "wake_detect_over_deadline": (500, 156, "detected", "model_return"),
    }
    if case in deadline_progress:
        monkeypatch.syspath_prepend(str(BASE / "tools"))
        from wake_bench_trace import parse_mic_wake_trial_report

        report = parse_mic_wake_trial_report(json.loads(attempt.stdout))
        assert report["mic_wake_trial"] == "MIC_WAKE_TRIAL_V4"
        assert report["clock_reason"] == "capture_window_exceeded"
        frames, calls, result, step = deadline_progress[case]
        assert report["deadline_progress"] == {
            "frames_read": frames,
            "model_calls": calls,
            "last_model_result": result,
            "last_poll_step": step,
        }


@pytest.mark.parametrize(
    "case", ["endpoint", "silence", "stop_after_speech", "deny", "stop_before"]
)
def test_question_only_with_real_capture_and_mock_codec(port_binary, case):
    attempt = subprocess.run(
        [str(port_binary), "mic_only_trial_question_direct_" + case],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert attempt.returncode == 0, attempt.stderr
    assert attempt.stdout.strip() == "question-only capture verified"


@pytest.mark.parametrize("operation", ["read_reg", "write_reg"])
def test_aw88298_two_byte_forwarding_negative_control(tmp_path, operation):
    """An actual one-byte truncation must fail the real-port AW88298 boundary."""
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    app = tmp_path / "app"
    app.mkdir()
    for name in [
        "k151_audio_hold_hooks.hpp",
        "k151_board_bus.hpp",
        "k151_codec_port.cpp",
        "k151_codec_port.hpp",
        "k151_bounded_i2s.cpp",
        "k151_bounded_i2s.hpp",
        "k151_codec_control.hpp",
        "k151_speaker_startup_stage.hpp",
        "k151_mic_reader.hpp",
        "k151_mic_only_evidence.hpp",
        "k151_mic_wake_trial.hpp",
        "k151_mic_wake_trial.cpp",
        "k151_mic_wake_memory.hpp",
        "k151_question_pcm.hpp",
        "k151_question_trial.cpp",
        "k151_question_trial.hpp",
        "k151_contract.hpp",
    ]:
        shutil.copyfile(BASE / "esp_app/main" / name, app / name)
    header = app / "k151_codec_control.hpp"
    source = header.read_text()
    if operation == "write_reg":
        original = "return record(base_->write_reg(base_, reg, len, data, size));"
    else:
        original = "p.base_->read_reg(p.base_, reg, len, data, size)"
    assert source.count(original) == 1
    header.write_text(source.replace(original, original.replace(", size)", ", 1)")))
    binary = _build_port(compiler, tmp_path / "codec", app)
    result = subprocess.run(
        [str(binary), "ok"], cwd=tmp_path, capture_output=True, text=True, timeout=10
    )
    assert result.returncode != 0, "truncated AW88298 register transfer escaped the fixture"
    assert "n==(out?2:1)" in result.stderr, result.stderr


@pytest.fixture(scope="module")
def control_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    folder = tmp_path_factory.mktemp("codec-control")
    obj = folder / "es7210.o"
    includes = ["-isystem", str(SDK), "-I", str(BASE / "tests/codec_io_doubles")]
    # Vendor C is compiled as C, unmodified, separately from strict owned C++.
    # Real IDF headers supply allocation declarations transitively; the tiny
    # no-hardware log double deliberately does not emulate that header tree.
    command = [compiler, "-x", "c", "-std=c11", "-O2", "-include", "stdlib.h", *includes]
    result = subprocess.run(
        command + ["-c", str(SDK / "es7210.c"), "-o", str(obj)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    binary = folder / "control"
    command = [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    command += includes + ["-I", str(BASE / "esp_app/main"), "-I", str(BASE / "core")]
    result = subprocess.run(
        command + [str(BASE / "tests/k151_codec_control_test.cpp"), str(obj), "-o", str(binary)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("mode", ["raw_read", "guard_read", "guard_write", "boundaries", "lost"])
def test_real_es7210_control_errors(control_binary, mode):
    result = subprocess.run([str(control_binary), mode], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def aw88298_startup_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    folder = tmp_path_factory.mktemp("aw88298-startup")
    includes = ["-isystem", str(SDK), "-I", str(BASE / "tests/codec_io_doubles")]
    objects = []
    for name in ("aw88298", "esp_codec_dev_vol"):
        obj = folder / f"{name}.o"
        result = subprocess.run(
            [
                compiler,
                "-x",
                "c",
                "-std=c11",
                "-O2",
                "-include",
                "stdlib.h",
                *includes,
                "-c",
                str(SDK / f"{name}.c"),
                "-o",
                str(obj),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr
        objects.append(str(obj))
    executable = folder / "aw88298-startup"
    result = subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            *includes,
            "-I",
            str(BASE / "esp_app/main"),
            "-I",
            str(BASE / "core"),
            str(BASE / "tests/k151_aw88298_muted_startup_test.cpp"),
            *objects,
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return executable


@pytest.mark.parametrize(
    "mode",
    [
        "raw",
        "held",
        "reset",
        "unknown_width",
        "read_failure",
        "readback_mismatch",
        "write_failure",
        "standby",
        "standby_mute_read_fail",
        "standby_mute_write_fail",
        "standby_power_write_fail",
        "standby_still_switching",
        "standby_after_fault",
    ],
)
def test_real_aw88298_startup_stays_quiet(aw88298_startup_binary, mode):
    result = subprocess.run(
        [str(aw88298_startup_binary), mode], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mode",
    [
        "start_low_volume",
        "start_uvls_clears_while_muted",
        "start_uvls_persists",
        "start_uvls_at_settle_boundary",
        "start_uvls_stop",
        "start_uvls_reasserts_before_amp",
        "start_uvls_reasserts_after_amp",
        "start_late_uvls_without_transient",
        "start_no_clock",
        "start_reference_missing",
        "start_clock_unstable",
        "start_early_switching",
        "start_clock_read_failure",
        "start_no_switching",
        "start_excess_gain",
        "start_fault",
        "start_mute_lost",
        "start_clock_lost_at_unmute",
        "start_revoked_initially",
        "start_revoked_at_i2s_readback",
        "start_i2s_readback_mismatch",
        "start_revoked_while_muted",
        "start_revoked_at_unmute",
        "start_clock_reversed",
        "start_frozen_clock",
    ],
)
def test_real_aw88298_guarded_low_volume_start(aw88298_startup_binary, mode):
    result = subprocess.run(
        [str(aw88298_startup_binary), mode], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("protection", ["8000", "4000", "0800", "0400", "0008", "0002", "400a"])
def test_real_aw88298_preserves_all_active_protection_bits_without_unmuting(
    aw88298_startup_binary, protection
):
    result = subprocess.run(
        [str(aw88298_startup_binary), "start_clock_protection", protection],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mode",
    [
        "uvls_observed",
        "uvls_already_in_standby",
        "uvls_no_budget",
        "uvls_other_protection",
        "uvls_switching",
        "uvls_stop_during_read",
        "uvls_clock_deadline",
        "uvls_clock_regression",
        "uvls_followup_no_budget",
        "uvls_followup_deadline",
        "uvls_followup_regression",
        "uvls_followup_stop",
        "uvls_followup_invalid_vdd",
    ],
)
def test_aw88298_bounds_vdd_and_followup_without_amplification(aw88298_startup_binary, mode):
    run = subprocess.run(
        [str(aw88298_startup_binary), mode], capture_output=True, text=True, timeout=10
    )
    assert run.returncode == 0, run.stderr
