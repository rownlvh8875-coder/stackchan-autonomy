import asyncio
import json
import subprocess
import sys

import pytest

from stackchan_autonomy.decision import MockDecisionProvider
from stackchan_autonomy.engine import AutonomyEngine
from stackchan_autonomy.models import Event, EventKind
from stackchan_autonomy.robot import FakeRobotAdapter
from stackchan_autonomy.settings import Settings
from stackchan_autonomy.voice import (
    FakeMicrophone,
    FakePlaybackAdapter,
    FakeSpeechService,
    RecordedVoiceInput,
    SpeakingRobotAdapter,
    VoiceConversation,
)


def conversation(*, microphone=None, service=None):
    settings = Settings(cooldown_s=0, command_interval_s=0)
    service = service or FakeSpeechService(transcript="private-안녕하세요")
    microphone = microphone or FakeMicrophone()
    playback = FakePlaybackAdapter()
    robot = FakeRobotAdapter()
    engine = AutonomyEngine(
        SpeakingRobotAdapter(robot, service, playback), MockDecisionProvider(), settings
    )
    voice = VoiceConversation(engine, RecordedVoiceInput(microphone, service), settings)
    return voice, robot, microphone, service, playback


async def test_complete_voice_flow_uses_existing_safety_and_keeps_media_private(caplog):
    voice, robot, mic, service, playback = conversation()
    try:
        result = await voice.handle(Event(kind=EventKind.TOUCH_TAP))
        assert result.executed
        assert (mic.calls, service.transcriptions, service.syntheses, playback.calls) == (
            1,
            1,
            1,
            1,
        )
        assert robot.history[-1].kind == "speak"
        assert playback.history[-1].sample_rate == 16000
        assert playback.history[-1].channels == 1
        assert b"private-" not in voice.settings.state_path.read_bytes()
        assert "private-" not in caplog.text
    finally:
        await voice.engine.aclose()


async def test_timer_never_starts_recording_or_cloud_voice():
    voice, robot, mic, _, playback = conversation()
    try:
        result = await voice.handle(Event(kind=EventKind.TIMER_OBSERVE))
        assert result.code == "voice_trigger_required"
        assert mic.calls == playback.calls == 0
    finally:
        await voice.engine.aclose()


async def test_stop_during_capture_cancels_recording_without_synthesis_or_playback():
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class SlowMic(FakeMicrophone):
        async def record(self, *, duration_ms):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    voice, robot, _, service, playback = conversation(microphone=SlowMic())
    task = asyncio.create_task(voice.handle(Event(kind=EventKind.TOUCH_TAP)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        voice.engine.stop()
        assert (await asyncio.wait_for(task, 1)).code == "stopped"
        assert cancelled.is_set()
        assert service.syntheses == playback.calls == 0
        assert not robot.history
    finally:
        await voice.engine.aclose()


async def test_stop_during_tts_cancels_without_playback_and_no_task_leak():
    entered = asyncio.Event()

    class SlowTTS(FakeSpeechService):
        async def synthesize(self, text):
            entered.set()
            await asyncio.Event().wait()

    baseline = len(asyncio.all_tasks())
    voice, robot, _, _, playback = conversation(service=SlowTTS())
    task = asyncio.create_task(voice.handle(Event(kind=EventKind.TOUCH_TAP)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        voice.engine.stop()
        assert (await asyncio.wait_for(task, 1)).code == "stopped"
        assert playback.calls == 0 and not robot.history
    finally:
        await voice.engine.aclose()
    await asyncio.sleep(0)
    assert len(asyncio.all_tasks()) == baseline


async def test_duplicate_voice_request_is_busy_without_a_second_microphone():
    entered = asyncio.Event()

    class SlowMic(FakeMicrophone):
        async def record(self, *, duration_ms):
            self.calls += 1
            entered.set()
            await asyncio.Event().wait()

    voice, _, mic, _, _ = conversation(microphone=SlowMic())
    task = asyncio.create_task(voice.handle(Event(kind=EventKind.TOUCH_TAP)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        result = await voice.handle(Event(kind=EventKind.VOICE_REQUEST))
        assert result.code == "voice_busy"
        assert mic.calls == 1
        voice.engine.stop()
        await asyncio.wait_for(task, 1)
    finally:
        await voice.engine.aclose()


def test_unknown_physical_microphone_and_speaker_are_not_implicitly_enabled():
    class Physical:
        physical = True

    with pytest.raises(PermissionError):
        RecordedVoiceInput(Physical(), FakeSpeechService())
    with pytest.raises(PermissionError):
        SpeakingRobotAdapter(FakeRobotAdapter(), FakeSpeechService(), Physical())


def test_voice_cli_requires_explicit_trigger_and_does_not_open_a_mic():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "stackchan_autonomy",
            "--mode",
            "voice-sim",
            "--event",
            "touch",
            "--cycles",
            "1",
        ],
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["mode"] == "voice-sim"
    assert summary["audio_captures"] == summary["audio_playbacks"] == 1
    assert summary["cloud_requests"] == 0
    assert "안녕" not in result.stdout


async def test_lease_loss_while_listening_cancels_input_without_output():
    from stackchan_autonomy.control import ControlLease

    entered, cancelled = asyncio.Event(), asyncio.Event()
    now = [100.0]

    class SlowMic(FakeMicrophone):
        async def record(self, *, duration_ms):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    voice, robot, _, _, playback = conversation(microphone=SlowMic())
    voice.engine.actions.lease = ControlLease(
        voice.settings.state_path, voice.settings.control_resource, ttl_s=1.5, clock=lambda: now[0]
    )
    task = asyncio.create_task(voice.handle(Event(kind=EventKind.TOUCH_TAP)))
    try:
        await asyncio.wait_for(entered.wait(), 20)
        now[0] = 103
        assert (await asyncio.wait_for(task, 3)).code == "stopped"
        assert cancelled.is_set() and playback.calls == 0 and not robot.history
    finally:
        await voice.engine.aclose()


async def test_voice_input_timeout_cleans_up_recording_task():
    cancelled = asyncio.Event()

    class SlowMic(FakeMicrophone):
        async def record(self, *, duration_ms):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    voice, _, _, _, playback = conversation(microphone=SlowMic())
    voice.settings.operation_timeout_s = 0.02
    try:
        assert (await voice.handle(Event(kind=EventKind.TOUCH_TAP))).code == "voice_unavailable"
        assert cancelled.is_set() and playback.calls == 0
    finally:
        await voice.engine.aclose()


async def test_backend_swallowing_playback_cancel_cannot_record_a_completed_action():
    entered = asyncio.Event()

    class CancelSwallowing(FakePlaybackAdapter):
        async def play_pcm(self, pcm, *, sample_rate, channels):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return

    from stackchan_autonomy.models import RobotCommand

    robot = FakeRobotAdapter()
    speaking = SpeakingRobotAdapter(robot, FakeSpeechService(), CancelSwallowing())
    task = asyncio.create_task(speaking.execute(RobotCommand(kind="speak", speech="안녕")))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not robot.history


async def test_microphone_swallowing_cancel_cannot_send_audio_for_transcription():
    from stackchan_autonomy.audio import PCM16Audio

    entered = asyncio.Event()

    class SwallowingMic(FakeMicrophone):
        async def record(self, *, duration_ms):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return PCM16Audio(pcm=b"\0\0" * 160, sample_rate=16000, channels=1)

    voice, _, _, service, playback = conversation(microphone=SwallowingMic())
    task = asyncio.create_task(voice.handle(Event(kind=EventKind.TOUCH_TAP)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        voice.engine.stop()
        assert (await asyncio.wait_for(task, 1)).code == "stopped"
        assert service.transcriptions == 0 and playback.calls == 0
    finally:
        await voice.engine.aclose()


@pytest.mark.parametrize("via_event", [True, False])
async def test_disconnect_from_event_or_engine_fault_cancels_voice_recording(via_event):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class SlowMic(FakeMicrophone):
        async def record(self, *, duration_ms):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    voice, robot, _, _, playback = conversation(microphone=SlowMic())
    task = asyncio.create_task(voice.handle(Event(kind=EventKind.TOUCH_TAP)))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if via_event:
            await voice.handle(Event(kind=EventKind.DEVICE_DISCONNECTED))
        else:
            robot.connected = False
            await voice.engine.step(Event(kind=EventKind.TIMER_OBSERVE))
        assert voice.engine.stop_event.is_set()
        assert (await asyncio.wait_for(task, 1)).code == "stopped"
        assert cancelled.is_set() and playback.calls == 0
    finally:
        await voice.engine.aclose()


def test_optional_codec_runtime_failure_is_a_clear_cli_failure(monkeypatch, capsys):
    from stackchan_autonomy import cli, voice
    from stackchan_autonomy.opus_codec import OpusUnavailable

    monkeypatch.setattr(cli, "opus_available", lambda: True)

    def fail(audio):
        raise OpusUnavailable("private native details")

    monkeypatch.setattr(voice, "encode_opus", fail)
    with pytest.raises(SystemExit) as result:
        cli.main(["--mode", "voice-sim", "--event", "touch", "--cycles", "1", "--opus"])
    assert result.value.code == 2
    out = capsys.readouterr()
    assert "private native details" not in out.err
    assert "voice" in out.err.lower()
