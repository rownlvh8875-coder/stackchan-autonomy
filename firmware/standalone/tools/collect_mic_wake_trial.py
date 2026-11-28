"""Receive one authorized K151 trial. Keep fixed counts and discard raw serial bytes."""

import argparse
import json
import re
import time
from pathlib import Path

from wake_bench_trace import parse_mic_wake_trial_report

SCOPE = "ONE_MIC_WAKE_TRIAL_AND_OTA1_RESTORE"
QUESTION_SCOPE = "ONE_MIC_QUESTION_TRIAL_AND_OTA1_RESTORE"
WAKE_ONLY_CONTROL_SCOPE = "ONE_WAKE_ONLY_CONTROL_AND_OTA1_RESTORE"
QUESTION_ONLY_SCOPE = "ONE_QUESTION_ONLY_TRIAL_AND_OTA1_RESTORE"
QUESTION_PROTOCOL = "MIC_QUESTION_TRIAL_V1"
QUESTION_ONLY_PROTOCOL = "MIC_QUESTION_ONLY_TRIAL_V1"
SILENT_TX_SCOPE = "ONE_SILENT_TX_PROBE_AND_OTA1_RESTORE"
SILENT_TX_PROTOCOL = "K151_SILENT_TX_V1"
SPEAKER_SCOPE = "ONE_SYNTHETIC_SPEAKER_PROBE_AND_OTA1_RESTORE"
SPEAKER_PROTOCOL = "K151_SPEAKER_V1"
SPEAKER_STARTUP_PROTOCOL = "K151_SPEAKER_V2"
SPEAKER_CLOCK_PROTOCOL = "K151_SPEAKER_V3"
SPEAKER_PROTECTION_PROTOCOL = "K151_SPEAKER_V4"
SPEAKER_VDD_PROTOCOL = "K151_SPEAKER_V5"
SPEAKER_STANDBY_UVLS_PROTOCOL = "K151_SPEAKER_V6"
SPEAKER_RESET_UVLS_PROTOCOL = "K151_SPEAKER_V7"
SPEAKER_VDD_FOLLOWUP_PROTOCOL = "K151_SPEAKER_V8"
SPEAKER_SETTLING_PROTOCOL = "K151_SPEAKER_V9"
SPEAKER_CLEANUP_PROTOCOL = "K151_SPEAKER_V10"
SPEAKER_STANDBY_CHECK_PROTOCOL = "K151_SPEAKER_V11"
SPEAKER_MUTE_SETTLE_PROTOCOL = "K151_SPEAKER_V12"
SPEAKER_AMP_OFF_PROTOCOL = "K151_SPEAKER_V13"
SPEAKER_STOP_PROTOCOL = "K151_SPEAKER_STOP_V1"
SPEAKER_STOP_PROGRESS_PROTOCOL = "K151_SPEAKER_STOP_V2"
SPEAKER_STOP_SHUTDOWN_PROTOCOL = "K151_SPEAKER_STOP_V3"
SPEAKER_STOP_PROGRESS_PROTOCOLS = {SPEAKER_STOP_PROGRESS_PROTOCOL, SPEAKER_STOP_SHUTDOWN_PROTOCOL}
SPEAKER_STOP_PROTOCOLS = {SPEAKER_STOP_PROTOCOL, *SPEAKER_STOP_PROGRESS_PROTOCOLS}
SPEAKER_STOP_SCOPE = "ONE_SYNTHETIC_SPEAKER_SCREEN_STOP_AND_OTA1_RESTORE"
SPEAKER_STOP_MODE = "SYNTHETIC_SPEAKER_SCREEN_STOP"
SPEAKER_AUTO_STOP_SCOPE = "ONE_SYNTHETIC_SPEAKER_AUTOMATIC_STOP_AND_OTA1_RESTORE"
SPEAKER_AUTO_STOP_MODE = "SYNTHETIC_SPEAKER_AUTOMATIC_STOP"
SPEAKER_AUTO_STOP_KIND = "REVIEW_ONLY_SPEAKER_AUTO_STOP_V3"
SPEAKER_STOP_CUE = "SPEAKER_STOP_ARMED"
SPEAKER_STOP_PROGRESS_CUE = "SPEAKER_STOP_PLAYING"
SPEAKER_STOP_OK = "screen_stop_and_standby_observed"
SPEAKER_STOP_BLOCKS = 250
SPEAKER_CHALLENGES = {
    SPEAKER_PROTOCOL: "WAIT_SPEAKER_LOCAL_START",
    SPEAKER_STARTUP_PROTOCOL: "WAIT_SPEAKER_STARTUP_LOCAL_START",
    SPEAKER_CLOCK_PROTOCOL: "WAIT_SPEAKER_CLOCK_LOCAL_START",
    SPEAKER_PROTECTION_PROTOCOL: "WAIT_SPEAKER_PROTECTION_LOCAL_START",
    SPEAKER_VDD_PROTOCOL: "WAIT_SPEAKER_VDD_LOCAL_START",
    SPEAKER_STANDBY_UVLS_PROTOCOL: "WAIT_SPEAKER_STANDBY_UVLS_LOCAL_START",
    SPEAKER_RESET_UVLS_PROTOCOL: "WAIT_SPEAKER_RESET_UVLS_LOCAL_START",
    SPEAKER_VDD_FOLLOWUP_PROTOCOL: "WAIT_SPEAKER_VDD_FOLLOWUP_LOCAL_START",
    SPEAKER_SETTLING_PROTOCOL: "WAIT_SPEAKER_SETTLING_LOCAL_START",
    SPEAKER_CLEANUP_PROTOCOL: "WAIT_SPEAKER_CLEANUP_LOCAL_START",
    SPEAKER_STANDBY_CHECK_PROTOCOL: "WAIT_SPEAKER_STANDBY_CHECK_LOCAL_START",
    SPEAKER_MUTE_SETTLE_PROTOCOL: "WAIT_SPEAKER_MUTE_SETTLE_LOCAL_START",
    SPEAKER_AMP_OFF_PROTOCOL: "WAIT_SPEAKER_AMP_OFF_LOCAL_START",
    SPEAKER_STOP_PROTOCOL: "WAIT_SPEAKER_SCREEN_STOP_START",
    SPEAKER_STOP_PROGRESS_PROTOCOL: "WAIT_SPEAKER_SCREEN_STOP_PROGRESS_START",
    SPEAKER_STOP_SHUTDOWN_PROTOCOL: "WAIT_SPEAKER_SCREEN_STOP_SHUTDOWN_START",
}
SPEAKER_REVIEW_KINDS = {
    SPEAKER_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V1",
    SPEAKER_STARTUP_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V2",
    SPEAKER_CLOCK_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V3",
    SPEAKER_PROTECTION_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V4",
    SPEAKER_VDD_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V5",
    SPEAKER_STANDBY_UVLS_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V6",
    SPEAKER_RESET_UVLS_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V7",
    SPEAKER_VDD_FOLLOWUP_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V8",
    SPEAKER_SETTLING_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V9",
    SPEAKER_CLEANUP_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V10",
    SPEAKER_STANDBY_CHECK_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V11",
    SPEAKER_MUTE_SETTLE_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V12",
    SPEAKER_AMP_OFF_PROTOCOL: "REVIEW_ONLY_SPEAKER_PROBE_V13",
    SPEAKER_STOP_PROTOCOL: "REVIEW_ONLY_SPEAKER_STOP_V1",
    SPEAKER_STOP_PROGRESS_PROTOCOL: "REVIEW_ONLY_SPEAKER_STOP_V2",
    SPEAKER_STOP_SHUTDOWN_PROTOCOL: "REVIEW_ONLY_SPEAKER_STOP_V3",
}
SILENT_TX_RESULTS = {
    "denied",
    "stopped",
    "channel_failed",
    "preload_failed",
    "callback_failed",
    "enable_failed",
    "timeout",
    "invalid_event",
    "clock_fault",
    "cleanup_failed",
    "two_descriptors_observed",
}
SPEAKER_RESULTS = {
    "denied",
    "stopped",
    "codec_prepare_failed",
    "clock_fault",
    "amplifier_start_failed",
    "transfer_failed",
    "mute_confirmation_failed",
    "cleanup_failed",
    "dma_and_mute_observed",
}
SPEAKER_STARTUP_STAGES = {
    "audio_guard",
    "admission",
    "codec_open",
    "codec_ready",
    "i2s_tx_state",
    "volume",
    "muted_admission",
    "clock_origin",
    "standby_readback",
    "clock_enable",
    "wait_clock",
    "mute_readback",
    "amplifier_enable",
    "wait_switching",
    "attenuation",
    "pre_unmute_status",
    "unmute",
    "post_unmute_status",
}
SPEAKER_CLOCK_WAIT_EXITS = {
    "admission_lost",
    "timer_regressed",
    "startup_deadline",
    "poll_limit",
    "status_read_failed",
    "protection_active",
    "early_switching",
}
SPEAKER_CLOCK_WAIT_SAMPLES = {
    "unobserved",
    "reference_missing",
    "pll_unlocked",
    "internal_unstable",
    "stable",
}
SPEAKER_SETTLING_PENDING_STAGES = {"wait_clock", "mute_readback", "pre_amplifier_status"}
SPEAKER_SETTLING_READY_STAGES = {
    "none",
    "amplifier_enable",
    "wait_switching",
    "attenuation",
    "pre_unmute_status",
    "unmute",
    "post_unmute_status",
}
SPEAKER_PROTECTION_FLAGS = {
    "ovp2",
    "undervoltage",
    "boost_overcurrent",
    "ovp",
    "amplifier_overcurrent",
    "overtemperature",
}
WIRE_LIMIT = 512
QUESTION_BEFORE_CUE = {"not_run", "memory_denied", "prepare_failed", "open_failed", "quiet_timeout"}
QUESTION_AFTER_CUE = {"no_endpoint", "endpoint"}
QUESTION_ANY_TIME = {"stopped", "clock_fault", "read_failed", "release_failed"}
CLEAN_QUESTION_RESULTS = {
    "not_run",
    "stopped",
    "memory_denied",
    "endpoint",
    "no_endpoint",
    "quiet_timeout",
}


def validate_question_report(record, *, cue_seen, wake=None):
    result = record.get("result")
    cleanup = record.get("codec_cleanup_unverified")
    protocol = QUESTION_PROTOCOL if wake is not None else QUESTION_ONLY_PROTOCOL
    cue_results = QUESTION_AFTER_CUE if cue_seen else QUESTION_BEFORE_CUE
    if (
        set(record)
        != {"mic_question_trial", "result", "codec_cleanup_unverified", "operating_admission"}
        or record.get("mic_question_trial") != protocol
        or record.get("operating_admission") is not False
        or type(cleanup) is not bool
        or not isinstance(result, str)
        or result not in QUESTION_ANY_TIME | cue_results
        or (cleanup and result in CLEAN_QUESTION_RESULTS)
    ):
        raise ValueError("Invalid question trial report")
    if wake is None:
        if result == "not_run":
            raise ValueError("The question-only trial has no wake stage")
    elif wake["mic_wake_trial"] not in (
        "MIC_WAKE_TRIAL_V2",
        "MIC_WAKE_TRIAL_V3",
        "MIC_WAKE_TRIAL_V4",
    ) or (wake["result"] == "detected") != (result != "not_run"):
        raise ValueError("Invalid preceding wake result")
    return record


def _validate_stop_shutdown(record):
    detail = record.get("stop_diagnostic")
    flags = {
        "screen_stop_sampled",
        "pcm_write_rejected",
        "reset_latch_verified",
        "tx_idle_observed",
    }
    if (
        not isinstance(detail, dict)
        or set(detail) != flags | {"cleanup_stage", "sample_to_reset_idle_us"}
        or any(type(detail[key]) is not bool for key in flags)
        or type(detail["cleanup_stage"]) is not int
        or not 0 <= detail["cleanup_stage"] <= 25
        or (detail["reset_latch_verified"] and detail["cleanup_stage"] == 0)
        or (
            record["result"] == SPEAKER_STOP_OK
            and (
                not detail["screen_stop_sampled"]
                or not detail["tx_idle_observed"]
                or detail["cleanup_stage"] != 0
                or detail["reset_latch_verified"]
                or detail["pcm_write_rejected"]
            )
        )
    ):
        raise ValueError("Invalid speaker STOP shutdown evidence")
    delta = detail["sample_to_reset_idle_us"]
    if delta is not None and (
        record["result"] != "cleanup_failed"
        or record["standby_confirmed"]
        or record["pcm_blocks"] == 0
        or record["dma_complete"]
        or type(delta) is not int
        or not 0 <= delta <= 10_000_000
        or not (
            detail["screen_stop_sampled"]
            and detail["reset_latch_verified"]
            and detail["tx_idle_observed"]
        )
        or detail["pcm_write_rejected"]
    ):
        raise ValueError("Reset timing requires a verified fallback and idle TX")


def validate_output_report(record, *, speaker, speaker_protocol=SPEAKER_PROTOCOL):
    if speaker and speaker_protocol in SPEAKER_STOP_PROGRESS_PROTOCOLS:
        fields = {
            "speaker_probe",
            "result",
            "pcm_blocks",
            "dma_complete",
            "standby_confirmed",
            "sample_to_standby_us",
            "operating_admission",
        }
        result = record.get("result")
        blocks = record.get("pcm_blocks")
        dma = record.get("dma_complete")
        quiet = record.get("standby_confirmed")
        delta = record.get("sample_to_standby_us")
        shutdown_report = speaker_protocol == SPEAKER_STOP_SHUTDOWN_PROTOCOL
        if shutdown_report:
            fields.add("stop_diagnostic")
        if (
            set(record) != fields
            or record.get("speaker_probe") != speaker_protocol
            or record.get("operating_admission") is not False
            or type(blocks) is not int
            or not 0 <= blocks <= SPEAKER_STOP_BLOCKS
            or type(dma) is not bool
            or type(quiet) is not bool
            or (dma and blocks != SPEAKER_STOP_BLOCKS)
            or result
            not in (
                SPEAKER_STOP_OK,
                "completed_no_stop",
                "screen_stop_before_playing",
                "screen_stop_after_queue",
                "screen_stop_timing_unverified",
                "host_stopped",
                "clock_fault",
                "preparation_failed",
                "amplifier_start_failed",
                "transfer_failed",
                "cleanup_failed",
            )
            or (result == "completed_no_stop" and not (dma and quiet))
            or (
                result == SPEAKER_STOP_OK
                and (
                    blocks == 0
                    or dma
                    or not quiet
                    or type(delta) is not int
                    or not 0 <= delta <= 10_000_000
                )
            )
            or (result != SPEAKER_STOP_OK and delta is not None)
        ):
            raise ValueError("Invalid speaker STOP progress")
        if shutdown_report:
            _validate_stop_shutdown(record)
        return record
    if speaker and speaker_protocol == SPEAKER_STOP_PROTOCOL:
        result = record.get("result")
        delta = record.get("sample_to_standby_us")
        if (
            set(record)
            != {"speaker_probe", "result", "sample_to_standby_us", "operating_admission"}
            or record.get("speaker_probe") != SPEAKER_STOP_PROTOCOL
            or record.get("operating_admission") is not False
            or result
            not in (
                SPEAKER_STOP_OK,
                "no_playing_stop",
                "preparation_failed",
                "amplifier_start_failed",
                "transfer_failed",
                "cleanup_failed",
            )
            or (
                result == SPEAKER_STOP_OK
                and (type(delta) is not int or not 0 <= delta <= 10_000_000)
            )
            or (result != SPEAKER_STOP_OK and delta is not None)
        ):
            raise ValueError("Invalid speaker STOP diagnostic result")
        return record
    field, protocol, results = (
        ("speaker_probe", speaker_protocol, SPEAKER_RESULTS)
        if speaker
        else ("tx_dma_probe", SILENT_TX_PROTOCOL, SILENT_TX_RESULTS)
    )
    result = record.get("result")
    expected_fields = {field, "result", "operating_admission"}
    amp_off_report = speaker and speaker_protocol == SPEAKER_AMP_OFF_PROTOCOL
    mute_settle_report = amp_off_report or (
        speaker and speaker_protocol == SPEAKER_MUTE_SETTLE_PROTOCOL
    )
    detailed_standby = mute_settle_report or (
        speaker and speaker_protocol == SPEAKER_STANDBY_CHECK_PROTOCOL
    )
    cleanup_report = detailed_standby or (speaker and speaker_protocol == SPEAKER_CLEANUP_PROTOCOL)
    settling_report = cleanup_report or (speaker and speaker_protocol == SPEAKER_SETTLING_PROTOCOL)
    followup_report = settling_report or (
        speaker and speaker_protocol == SPEAKER_VDD_FOLLOWUP_PROTOCOL
    )
    reset_report = followup_report or (speaker and speaker_protocol == SPEAKER_RESET_UVLS_PROTOCOL)
    standby_report = reset_report or (speaker and speaker_protocol == SPEAKER_STANDBY_UVLS_PROTOCOL)
    vdd_report = standby_report or (speaker and speaker_protocol == SPEAKER_VDD_PROTOCOL)
    protection_report = vdd_report or (speaker and speaker_protocol == SPEAKER_PROTECTION_PROTOCOL)
    clock_report = protection_report or (speaker and speaker_protocol == SPEAKER_CLOCK_PROTOCOL)
    if clock_report or (speaker and speaker_protocol == SPEAKER_STARTUP_PROTOCOL):
        expected_fields.add("startup_stage")
    if clock_report:
        expected_fields.update(("clock_wait_exit", "clock_wait_last"))
    if protection_report:
        expected_fields.add("protection")
    if followup_report:
        expected_fields.add("vdd")
    elif vdd_report:
        expected_fields.update(
            ("uvls_after_clock_us", "vdd_after_uvls_us", "startup_vdd", "startup_vdd_mv")
        )
    if standby_report:
        expected_fields.add("standby_uvls")
    if reset_report:
        expected_fields.add("reset_uvls")
    if settling_report:
        expected_fields.add("settling_uvls")
    if cleanup_report:
        expected_fields.add("end")
    if (
        set(record) != expected_fields
        or record.get(field) != protocol
        or record.get("operating_admission") is not False
        or not isinstance(result, str)
        or result not in results
    ):
        raise ValueError("Invalid output diagnostic result")
    if cleanup_report:
        end = record["end"]
        last_stage = (
            25 if amp_off_report else 24 if mute_settle_report else 20 if detailed_standby else 11
        )
        if (
            not isinstance(end, list)
            or len(end) != 2
            or any(type(value) is not int for value in end)
            or not 0 <= end[0] <= 2
            or not 0 <= end[1] <= last_stage
            or (detailed_standby and end[1] == 3)
        ):
            raise ValueError("Invalid speaker end checkpoint")
        progress, failure = end
        if result == "cleanup_failed":
            if failure == 0:
                raise ValueError("Speaker cleanup failure missing its checkpoint")
        elif not (mute_settle_report and result == "stopped" and end == [1, 21]):
            expected = {"dma_and_mute_observed": 2, "mute_confirmation_failed": 1}.get(result, 0)
            if progress != expected or (expected == 2 and failure != 0):
                raise ValueError("Speaker playback progress contradicts result")
    if "startup_stage" in expected_fields:
        stage = record["startup_stage"]
        if not isinstance(stage, str):
            raise ValueError("Invalid speaker startup checkpoint")
        if result == "amplifier_start_failed":
            allowed = SPEAKER_STARTUP_STAGES
        elif result == "cleanup_failed":
            allowed = SPEAKER_STARTUP_STAGES | {"none"}
        else:
            allowed = {"none"}
        if standby_report and result in ("amplifier_start_failed", "cleanup_failed"):
            allowed = allowed | {"i2s_enable"}
            if settling_report:
                allowed.add("pre_amplifier_status")
        if stage not in allowed:
            raise ValueError("Invalid speaker startup checkpoint")
    if clock_report:
        reason, sample = record["clock_wait_exit"], record["clock_wait_last"]
        if record["startup_stage"] == "wait_clock":
            if (
                not isinstance(reason, str)
                or reason not in SPEAKER_CLOCK_WAIT_EXITS
                or not isinstance(sample, str)
                or sample not in SPEAKER_CLOCK_WAIT_SAMPLES
            ):
                raise ValueError("Invalid speaker clock wait diagnostic")
        elif (reason, sample) != ("none", "none"):
            raise ValueError("Unexpected speaker clock wait diagnostic")
    if protection_report:
        flags = record["protection"]
        if (
            not isinstance(flags, dict)
            or flags.keys() != SPEAKER_PROTECTION_FLAGS
            or any(type(value) is not bool for value in flags.values())
        ):
            raise ValueError("Invalid speaker protection diagnostic")
        active = any(flags.values())
        if record["startup_stage"] == "wait_clock":
            protection_stop = record["clock_wait_exit"] == "protection_active"
            if active != protection_stop or (active and record["clock_wait_last"] == "unobserved"):
                raise ValueError("Speaker protection disagrees with the clock wait result")
        elif active and record["startup_stage"] not in {
            "pre_amplifier_status",
            "wait_switching",
            "pre_unmute_status",
            "post_unmute_status",
        }:
            raise ValueError("Unexpected speaker protection diagnostic")
    if vdd_report:
        if followup_report:
            vdd = record["vdd"]
            if not isinstance(vdd, list) or len(vdd) != 6:
                raise ValueError("Invalid speaker VDD follow-up observation")
            elapsed, delay, state, mv, followup_uvls, followup_delay = vdd
        else:
            elapsed, delay = record["uvls_after_clock_us"], record["vdd_after_uvls_us"]
            state, mv = record["startup_vdd"], record["startup_vdd_mv"]
        if any(type(value) is not int for value in (elapsed, delay, mv)) or not isinstance(
            state, str
        ):
            raise ValueError("Invalid speaker VDD observation")
        uvls = record["startup_stage"] == "wait_clock" and record["protection"]["undervoltage"]
        if standby_report:
            standby_uvls = record["standby_uvls"]
            if (uvls and type(standby_uvls) is not bool) or (not uvls and standby_uvls is not None):
                raise ValueError("Invalid speaker standby UVLS observation")
        if reset_report:
            reset = record["reset_uvls"]
            if not isinstance(reset, list) or len(reset) != 3:
                raise ValueError("Invalid speaker reset UVLS observations")
            before_tx, before_init, after_init = reset
            if uvls:
                if (before_tx is not None and type(before_tx) is not bool) or any(
                    type(sample) is not bool for sample in (before_init, after_init)
                ):
                    raise ValueError("Invalid speaker reset UVLS observations")
            elif any(sample is not None for sample in reset):
                raise ValueError("Unexpected speaker reset UVLS observations")
        if not uvls:
            if (elapsed, delay, state, mv) != (-1, -1, "not_requested", 0):
                raise ValueError("Unexpected speaker VDD observation")
        elif (
            not 0 <= elapsed < 100_000
            or state
            not in ("skipped", "not_seen", "read_failed", "invalid", "reset_value", "sampled")
            or (state == "sampled" and not 0 < mv <= 6025)
            or (state != "sampled" and mv != 0)
            or (
                delay != -1
                if state in ("skipped", "not_seen")
                else not 0 <= delay < 100_000 - elapsed
            )
            or (
                state != "skipped" and (elapsed > 70_000 or sum(record["protection"].values()) != 1)
            )
        ):
            raise ValueError("Invalid speaker VDD observation")
        if followup_report and (
            type(followup_delay) is not int
            or (
                followup_delay != -1
                if followup_uvls is None
                else type(followup_uvls) is not bool
                or state != "sampled"
                or not 0 <= followup_delay < 100_000 - elapsed - delay
            )
        ):
            raise ValueError("Invalid speaker VDD follow-up observation")
    if settling_report:
        settling = record["settling_uvls"]
        if (
            not isinstance(settling, list)
            or len(settling) != 2
            or any(type(value) is not int for value in settling)
        ):
            raise ValueError("Invalid speaker settling observation")
        first, ready = settling
        stage = record["startup_stage"]
        if first == -1:
            valid = ready == -1
        elif 0 <= first < 2000:
            valid = (ready == -1 and stage in SPEAKER_SETTLING_PENDING_STAGES) or (
                2000 <= ready < 100_000 and stage in SPEAKER_SETTLING_READY_STAGES
            )
        else:
            valid = False
        if not valid:
            raise ValueError("Invalid speaker settling observation")
        if uvls and (elapsed < first or (state != "skipped" and elapsed < 2000)):
            raise ValueError("Speaker VDD observation precedes the clock protection stop")
    return record


def _validate_auto_stop_mode(auto_stop, speaker, speaker_protocol):
    if auto_stop and not (speaker and speaker_protocol == SPEAKER_STOP_SHUTDOWN_PROTOCOL):
        raise ValueError("Automatic STOP requires the V3 speaker STOP diagnostic")


def receive_once(
    port,
    announce,
    *,
    announce_question=None,
    wake_only_control=False,
    question_only=False,
    silent_tx=False,
    speaker=False,
    speaker_protocol=SPEAKER_PROTOCOL,
    auto_stop=False,
    before_start=lambda: None,
    clock=time.monotonic,
):
    _validate_auto_stop_mode(auto_stop, speaker, speaker_protocol)
    question_mode = announce_question is not None
    output_only = silent_tx or speaker
    if (wake_only_control or question_only) and not question_mode:
        raise ValueError("Trial requires a question-phase cue")
    if sum((wake_only_control, question_only, silent_tx, speaker)) > 1 or (
        output_only and question_mode
    ):
        raise ValueError("Select a single trial mode")
    if speaker:
        challenge = SPEAKER_CHALLENGES[speaker_protocol]
    elif silent_tx:
        challenge = "WAIT_SILENT_TX_LOCAL_START"
    elif question_only:
        challenge = "WAIT_QUESTION_ONLY_START"
        question_cue = "QUESTION_ONLY_NOW"
    elif wake_only_control:
        challenge = "WAIT_WAKE_ONLY_CONTROL"
        question_cue = "QUIET_OBSERVATION_NOW"
    else:
        challenge = "WAIT_QUESTION_LOCAL_START" if question_mode else "WAIT_LOCAL_START"
        question_cue = "QUESTION_NOW"
    next_hello = clock()
    deadline = next_hello + 15
    waiting_replies = 0
    accepted_nonce = None
    started = listening = complete = False
    report = question_report = None
    question_cued = speaker_stop_armed = speaker_stop_cued = False
    auto_stop_attempted = auto_stop_sent = False
    pending = bytearray()
    try:
        while clock() < deadline:
            if not started and clock() >= next_hello:
                if port.write(b"HELLO\n") != len(b"HELLO\n"):
                    raise ValueError("Incomplete challenge request")
                waiting_replies += 1
                next_hello = clock() + 0.5
            pending.extend(port.read_until(expected=b"\n", size=WIRE_LIMIT))
            if len(pending) > WIRE_LIMIT or (
                len(pending) == WIRE_LIMIT and not pending.endswith(b"\n")
            ):
                raise ValueError("Serial record exceeded the fixed wire limit")
            if not pending.endswith(b"\n"):
                continue
            try:
                record = json.loads(pending)
            except (UnicodeError, ValueError):
                continue
            finally:
                pending.clear()
            if not isinstance(record, dict):
                continue
            marker = record.get("mic_trial")
            if marker in (
                "WAIT_LOCAL_START",
                "WAIT_QUESTION_LOCAL_START",
                "WAIT_WAKE_ONLY_CONTROL",
                "WAIT_QUESTION_ONLY_START",
                "WAIT_SILENT_TX_LOCAL_START",
                *SPEAKER_CHALLENGES.values(),
            ):
                nonce = record.get("nonce")
                if (
                    marker != challenge
                    or not waiting_replies
                    or set(record) != {"mic_trial", "nonce", "wait_ms"}
                    or record.get("wait_ms") != 60000
                    or not isinstance(nonce, str)
                    or re.fullmatch(r"[0-9A-F]{8}", nonce) is None
                    or nonce == "00000000"
                ):
                    raise ValueError("Invalid or repeated local challenge")
                waiting_replies -= 1
                if started:
                    if nonce != accepted_nonce:
                        raise ValueError("Diagnostic restarted after START")
                    continue
                start = f"START {nonce}\n".encode("ascii")
                before_start()
                accepted_nonce = nonce
                started = True
                if port.write(start) != len(start):
                    raise ValueError("Incomplete START")
                deadline = clock() + 12
            elif marker == "LISTEN_NOW":
                if (
                    not started
                    or question_only
                    or output_only
                    or listening
                    or report is not None
                    or set(record) != {"mic_trial", "operating_admission"}
                    or record["operating_admission"] is not False
                ):
                    raise ValueError("Unexpected listening marker")
                listening = True
                announce()
            elif marker == SPEAKER_STOP_CUE:
                if (
                    not speaker
                    or speaker_protocol not in SPEAKER_STOP_PROTOCOLS
                    or not started
                    or speaker_stop_armed
                    or report is not None
                    or set(record) != {"mic_trial", "operating_admission"}
                    or record["operating_admission"] is not False
                ):
                    raise ValueError("Unexpected speaker STOP cue")
                speaker_stop_armed = True
                if speaker_protocol == SPEAKER_STOP_PROTOCOL:
                    speaker_stop_cued = True
                    announce()
            elif marker == SPEAKER_STOP_PROGRESS_CUE:
                if (
                    not speaker
                    or speaker_protocol not in SPEAKER_STOP_PROGRESS_PROTOCOLS
                    or not speaker_stop_armed
                    or speaker_stop_cued
                    or set(record) != {"mic_trial", "operating_admission"}
                    or record["operating_admission"] is not False
                ):
                    raise ValueError("Unexpected speaker STOP playback cue")
                speaker_stop_cued = True
                # A USB task cue can complete after the output task's failure report.
                if report is None:
                    if auto_stop:
                        auto_stop_attempted = True
                        if port.write(b"STOP\n") != len(b"STOP\n"):
                            raise ValueError("Incomplete automatic STOP")
                        auto_stop_sent = True
                    else:
                        announce()
            elif marker in ("QUESTION_NOW", "QUIET_OBSERVATION_NOW", "QUESTION_ONLY_NOW"):
                if (
                    not question_mode
                    or marker != question_cue
                    or not started
                    or (not question_only and not listening)
                    or question_cued
                    or report is not None
                    or question_report is not None
                    or set(record) != {"mic_trial", "operating_admission"}
                    or record["operating_admission"] is not False
                ):
                    raise ValueError("Unexpected question marker")
                question_cued = True
                announce_question()
            elif "tx_dma_probe" in record or "speaker_probe" in record:
                if not output_only or not started or report is not None:
                    raise ValueError("Unexpected or repeated output result")
                report = validate_output_report(
                    record, speaker=speaker, speaker_protocol=speaker_protocol
                )
                reset_timing = report.get("stop_diagnostic", {}).get("sample_to_reset_idle_us")
                if report["result"] == SPEAKER_STOP_OK or reset_timing is not None:
                    if not speaker_stop_cued:
                        raise ValueError("Speaker STOP preceded the armed window")
                    if auto_stop_attempted:
                        raise ValueError("Speaker STOP timing overlaps automatic USB STOP")
            elif "mic_wake_trial" in record:
                if output_only or question_only or not started or report is not None:
                    raise ValueError("Unexpected or repeated trial result")
                report = parse_mic_wake_trial_report(record)
                if report["result"] in {"detected", "not_detected"} and not listening:
                    raise ValueError("Capture result preceded the listening marker")
            elif "mic_question_trial" in record:
                if (
                    not started
                    or not question_mode
                    or (not question_only and report is None)
                    or question_report is not None
                ):
                    raise ValueError("Unexpected or repeated question report")
                question_report = validate_question_report(
                    record, cue_seen=question_cued, wake=report
                )
            elif marker == "HOLD_UNTIL_RESET":
                if (
                    (not question_only and report is None)
                    or (question_mode and question_report is None)
                    or set(record) != {"mic_trial", "operating_admission"}
                    or (record["operating_admission"] is not False)
                ):
                    raise ValueError("Trial did not finish with a verified result")
                complete = True
                if question_only:
                    return question_report
                if auto_stop:
                    return report | {"automatic_stop_sent": auto_stop_sent}
                return {"wake": report, "question": question_report} if question_mode else report
        raise TimeoutError("Trial deadline elapsed")
    finally:
        if started and not complete and not auto_stop_attempted:
            try:
                port.write(b"STOP\n")
            except OSError:
                pass


def verified_port(
    directory,
    *,
    question=False,
    wake_only_control=False,
    question_only=False,
    silent_tx=False,
    speaker=False,
    speaker_protocol=SPEAKER_PROTOCOL,
    auto_stop=False,
):
    _validate_auto_stop_mode(auto_stop, speaker, speaker_protocol)
    if sum((question, wake_only_control, question_only, silent_tx, speaker)) > 1:
        raise ValueError("Select a single trial mode")

    def record(name):
        return json.loads((directory / name).read_text(encoding="utf-8-sig"))

    manifest = record("review-manifest.json")
    approved = record("approval.json")
    installed = record("install-verified.json")
    digest = manifest["image_sha256"]
    port = manifest["port"]
    protocol = QUESTION_ONLY_PROTOCOL if question_only else QUESTION_PROTOCOL
    if silent_tx or speaker:
        if speaker:
            speaker_stop = speaker_protocol in SPEAKER_STOP_PROTOCOLS
            scope = SPEAKER_STOP_SCOPE if speaker_stop else SPEAKER_SCOPE
            operator_mode = SPEAKER_STOP_MODE if speaker_stop else "SYNTHETIC_SPEAKER_ONLY"
            protocol = speaker_protocol
            expected_kind = SPEAKER_REVIEW_KINDS[protocol]
            if auto_stop:
                scope = SPEAKER_AUTO_STOP_SCOPE
                operator_mode = SPEAKER_AUTO_STOP_MODE
                expected_kind = SPEAKER_AUTO_STOP_KIND
            if any(item.get("operator_mode") != operator_mode for item in (manifest, approved)):
                raise ValueError("Synthetic speaker mode must be explicitly scoped")
        else:
            scope = SILENT_TX_SCOPE
            protocol = SILENT_TX_PROTOCOL
            expected_kind = "REVIEW_ONLY_SILENT_TX_PROBE_V1"
        review_id = directory.name
        if any(item.get("review_id") != review_id for item in (manifest, approved, installed)):
            raise ValueError("Output approval and installation must refer to this review")
    elif question_only:
        scope = QUESTION_ONLY_SCOPE
        expected_kind = "REVIEW_ONLY_QUESTION_ONLY_TRIAL_V1"
    elif wake_only_control:
        scope = WAKE_ONLY_CONTROL_SCOPE
        expected_kind = "REVIEW_ONLY_WAKE_ONLY_CONTROL_V1"
    elif question:
        scope = QUESTION_SCOPE
        expected_kind = "REVIEW_ONLY_MIC_QUESTION_TRIAL_V1"
    else:
        scope = SCOPE
        expected_kind = None
    if expected_kind and not (
        manifest.get("kind") == expected_kind
        and manifest.get("scope") == scope
        and manifest.get("expected_protocol") == protocol
    ):
        raise ValueError("Review manifest for the selected trial mode is required")
    if not (
        re.fullmatch(r"[0-9a-f]{64}", digest)
        and re.fullmatch(r"COM[1-9][0-9]*", port)
        and approved.get("approved") is True
        and approved.get("scope") == scope
        and approved.get("image_sha256") == installed.get("image_sha256") == digest
        and installed.get("independent_verify_passed") is True
        and installed.get("offset") == 0x510000
        and installed.get("port") == port
    ):
        raise ValueError("Scoped approval and verified install are required")
    return port, digest


def open_port(serial, name, *, clock=time.monotonic, wait=time.sleep):
    deadline = clock() + 6
    while clock() < deadline:
        port = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=1)
        port.port = name
        port.dtr = port.rts = False
        try:
            port.open()
        except serial.SerialException:
            port.close()
            wait(0.15)
        else:
            return port
    raise TimeoutError("USB port did not return")


def _auto_stop_passed(report):
    detail = report["stop_diagnostic"]
    return (
        report["automatic_stop_sent"]
        and report["result"] == "host_stopped"
        and 0 < report["pcm_blocks"] < SPEAKER_STOP_BLOCKS
        and not report["dma_complete"]
        and report["standby_confirmed"]
        and not detail["screen_stop_sampled"]
        and not detail["pcm_write_rejected"]
        and detail["cleanup_stage"] == 0
        and not detail["reset_latch_verified"]
        and detail["tx_idle_observed"]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--question", action="store_true")
    mode.add_argument("--wake-only-control", action="store_true")
    mode.add_argument("--question-only", action="store_true")
    mode.add_argument("--silent-tx", action="store_true")
    mode.add_argument("--speaker", action="store_true")
    parser.add_argument("--speaker-protocol", choices=SPEAKER_CHALLENGES, default=SPEAKER_PROTOCOL)
    parser.add_argument("--auto-stop", action="store_true")
    args = parser.parse_args()
    if not args.speaker and args.speaker_protocol != SPEAKER_PROTOCOL:
        parser.error("--speaker-protocol requires --speaker")
    try:
        port_name, digest = verified_port(
            args.review_dir,
            question=args.question,
            wake_only_control=args.wake_only_control,
            question_only=args.question_only,
            silent_tx=args.silent_tx,
            speaker=args.speaker,
            speaker_protocol=args.speaker_protocol,
            auto_stop=args.auto_stop,
        )
        intent = args.review_dir / "mic-receive-intent.json"
        if intent.exists():
            raise ValueError("A START was already attempted")

        def reserve():
            with intent.open("x", encoding="utf-8") as file:
                json.dump({"image_sha256": digest}, file)

        import serial

        def cue_question():
            if args.wake_only_control:
                print("질문 없이 잠시 조용히 기다려 주세요.", flush=True)
            else:
                print("지금 짧은 질문을 한 번 말하고 잠시 기다려 주세요.", flush=True)

        if args.speaker:
            print("SPEAKER_PREPARE", flush=True)
        port = open_port(serial, port_name)
        try:
            cue = {
                SPEAKER_STOP_PROTOCOL: SPEAKER_STOP_CUE,
                SPEAKER_STOP_PROGRESS_PROTOCOL: SPEAKER_STOP_PROGRESS_CUE,
                SPEAKER_STOP_SHUTDOWN_PROTOCOL: SPEAKER_STOP_PROGRESS_CUE,
            }.get(args.speaker_protocol, "지금 Hi StackChan을 한 번 말해 주세요.")
            report = receive_once(
                port,
                lambda: print(cue, flush=True),
                before_start=reserve,
                announce_question=(
                    cue_question
                    if args.question or args.wake_only_control or args.question_only
                    else None
                ),
                wake_only_control=args.wake_only_control,
                question_only=args.question_only,
                silent_tx=args.silent_tx,
                speaker=args.speaker,
                speaker_protocol=args.speaker_protocol,
                auto_stop=args.auto_stop,
            )
        finally:
            port.close()
        if args.auto_stop:
            result_file = "speaker-auto-stop-result.json"
        elif args.speaker:
            result_file = "speaker-result.json"
        else:
            result_file = "tx-dma-result.json" if args.silent_tx else "mic-result.json"
        with (args.review_dir / result_file).open("x", encoding="utf-8") as file:
            json.dump(report, file)
        print(json.dumps(report))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, KeyboardInterrupt):
        print("Diagnostic stopped or denied. Check the reviewed restore procedure.")
        return 1
    if args.auto_stop:
        return int(not _auto_stop_passed(report))
    expected = (
        SPEAKER_STOP_OK
        if args.speaker_protocol in SPEAKER_STOP_PROTOCOLS
        else "dma_and_mute_observed"
    )
    return int(args.speaker and report["result"] != expected)


if __name__ == "__main__":
    raise SystemExit(main())
