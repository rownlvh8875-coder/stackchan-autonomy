"""Run the Home Assistant speech service against synthetic provider clients."""

import asyncio
import base64
import io
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from stackchan_autonomy.settings import Settings


@pytest.fixture(autouse=True)
def explicit_state_path(monkeypatch):
    monkeypatch.delenv("STACKCHAN_STATE_PATH", raising=False)


def config(tmp_path, **values):
    defaults = {
        "cloud_enabled": True,
        "audio_transmission": True,
        "api_key": "offline-fixture-key",
        "state_path": tmp_path / "ha-voice.sqlite3",
        "requests_per_minute": 1,
        "budget_namespace": "openai:ha-speech-test",
    }
    defaults.update(values)
    return Settings(_env_file=None, OPENAI_API_KEY=defaults.pop("api_key"), **defaults)


def client():
    connection = object()

    @asynccontextmanager
    async def connected(**kwargs):
        yield connection

    return SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(create=AsyncMock(return_value="fixture"))
        ),
        realtime=SimpleNamespace(connect=Mock(side_effect=connected)),
    )


async def test_stt_and_tts_share_the_same_persistent_reservations(tmp_path):
    from stackchan_autonomy.ha_voice import STT_MODEL, TTS_MODEL, VoiceDenied, VoiceRequests

    provider = client()
    reports = []
    settings = config(tmp_path)
    async with VoiceRequests(settings, provider, emit=reports.append, clock=lambda: 100) as first:
        assert await first.transcribe(model=STT_MODEL, file=io.BytesIO(b"fixture")) == "fixture"
    async with VoiceRequests(
        settings, provider, emit=reports.append, clock=lambda: 100
    ) as restarted:
        with pytest.raises(VoiceDenied, match="HA_VOICE_BUDGET_EXHAUSTED"):
            async with restarted.realtime(model=TTS_MODEL, websocket_connection_options={}):
                pytest.fail("restarted service bypassed the shared limit")
    provider.audio.transcriptions.create.assert_awaited_once()
    provider.realtime.connect.assert_not_called()
    assert reports == ["HA_VOICE_BUDGET_EXHAUSTED"]


async def test_parallel_tts_keeps_at_most_one_reservation_and_no_retry(tmp_path):
    from stackchan_autonomy.ha_voice import TTS_MODEL, VoiceDenied, VoiceRequests

    provider = client()
    async with VoiceRequests(config(tmp_path), provider, emit=lambda _: None) as requests:

        async def turn():
            async with requests.realtime(model=TTS_MODEL, websocket_connection_options={}):
                return True

        result = await asyncio.gather(turn(), turn(), return_exceptions=True)
    assert sum(value is True for value in result) == 1
    assert sum(isinstance(value, VoiceDenied) for value in result) == 1
    provider.realtime.connect.assert_called_once()


async def test_provider_failure_spends_and_does_not_log_private_error(tmp_path, caplog):
    from stackchan_autonomy.ha_voice import (
        STT_MODEL,
        VoiceDenied,
        VoiceRequests,
        private_voice_logs,
    )

    canary = "fixture transcript and authorization"
    provider = client()

    async def failure(**kwargs):
        logging.getLogger("wyoming_openai.handler").warning(canary)
        logging.getLogger("httpx").error(canary)
        raise RuntimeError(canary)

    provider.audio.transcriptions.create = AsyncMock(side_effect=failure)
    reports = []
    settings = config(tmp_path)
    with private_voice_logs():
        async with VoiceRequests(
            settings, provider, emit=reports.append, clock=lambda: 100
        ) as requests:
            with pytest.raises(VoiceDenied, match=r"^HA_VOICE_PROVIDER_FAILED$"):
                await requests.transcribe(model=STT_MODEL, file=io.BytesIO(b"fixture"))
        async with VoiceRequests(
            settings, provider, emit=reports.append, clock=lambda: 100
        ) as restarted:
            with pytest.raises(VoiceDenied, match=r"^HA_VOICE_BUDGET_EXHAUSTED$"):
                await restarted.transcribe(model=STT_MODEL, file=io.BytesIO(b"fixture"))
    assert canary not in caplog.text
    assert reports == ["HA_VOICE_PROVIDER_FAILED", "HA_VOICE_BUDGET_EXHAUSTED"]
    provider.audio.transcriptions.create.assert_awaited_once()


async def test_unusable_database_denies_both_provider_paths(tmp_path):
    from stackchan_autonomy.ha_voice import STT_MODEL, TTS_MODEL, VoiceDenied, VoiceRequests

    directory = tmp_path / "db-as-directory"
    directory.mkdir()
    provider = client()
    reports = []
    async with VoiceRequests(
        config(tmp_path, state_path=directory), provider, emit=reports.append
    ) as requests:
        with pytest.raises(VoiceDenied, match="HA_VOICE_STORAGE_UNAVAILABLE"):
            await requests.transcribe(model=STT_MODEL)
        with pytest.raises(VoiceDenied, match="HA_VOICE_STORAGE_UNAVAILABLE"):
            async with requests.realtime(model=TTS_MODEL, websocket_connection_options={}):
                pytest.fail("storage failure allowed a Realtime connection")
    provider.audio.transcriptions.create.assert_not_awaited()
    provider.realtime.connect.assert_not_called()
    assert reports == ["HA_VOICE_STORAGE_UNAVAILABLE"] * 2


@pytest.mark.parametrize(
    "changes",
    [
        {"cloud_enabled": False},
        {"audio_transmission": False},
        {"api_key": ""},
        {"state_path": "relative.sqlite3"},
    ],
)
def test_configuration_rejects_unapproved_dispatch_before_sdk_import(tmp_path, changes):
    from stackchan_autonomy.ha_voice import VoiceDenied, validate_config

    with pytest.raises(VoiceDenied, match="HA_VOICE_CONFIG_REQUIRED"):
        validate_config(config(tmp_path, **changes))
    assert not list(tmp_path.iterdir())


def test_startup_denial_emits_only_a_fixed_status(tmp_path, capsys, monkeypatch):
    from stackchan_autonomy import ha_voice

    settings = Mock(return_value=config(tmp_path, audio_transmission=False))
    monkeypatch.setattr(ha_voice, "Settings", settings)
    monkeypatch.setattr(ha_voice, "serve", Mock(side_effect=AssertionError("unexpected serve")))
    assert ha_voice.main([]) == 2
    assert capsys.readouterr().err.strip() == "HA_VOICE_CONFIG_REQUIRED"
    settings.assert_called_once_with(_env_file=None)
    ha_voice.serve.assert_not_called()


@pytest.mark.parametrize("args", [["--port", "private-value"], ["--unknown=private-value"]])
def test_argument_errors_do_not_echo_values(args, capsys):
    from stackchan_autonomy.ha_voice import main

    assert main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.strip() == "HA_VOICE_CONFIG_REQUIRED"


async def test_cancelled_request_spends_its_reservation(tmp_path):
    from stackchan_autonomy.ha_voice import STT_MODEL, VoiceDenied, VoiceRequests

    started = asyncio.Event()

    async def wait_for_cancel(**kwargs):
        started.set()
        await asyncio.Future()

    provider = client()
    provider.audio.transcriptions.create.side_effect = wait_for_cancel
    settings = config(tmp_path)
    async with VoiceRequests(settings, provider, emit=lambda _: None, clock=lambda: 100) as first:
        task = asyncio.create_task(first.transcribe(model=STT_MODEL))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    async with VoiceRequests(
        settings, provider, emit=lambda _: None, clock=lambda: 100
    ) as restarted:
        with pytest.raises(VoiceDenied, match="HA_VOICE_BUDGET_EXHAUSTED"):
            await restarted.transcribe(model=STT_MODEL)
    provider.audio.transcriptions.create.assert_awaited_once()


@pytest.fixture
async def wyoming_peer(tmp_path, caplog):
    pytest.importorskip("wyoming_openai")
    from wyoming.event import async_read_event, async_write_event
    from wyoming.server import AsyncTcpServer

    from stackchan_autonomy.ha_voice import VoiceRequests, handler_factory, private_voice_logs

    provider = client()
    reports = []
    caplog.set_level(logging.DEBUG)
    settings = config(tmp_path, requests_per_minute=2)
    async with VoiceRequests(
        settings, provider, emit=reports.append, clock=lambda: 100
    ) as requests:
        server = AsyncTcpServer("127.0.0.1", 0)
        await server.start(handler_factory(requests))
        try:
            (sock,) = server._server.sockets
            reader, writer = await asyncio.open_connection("127.0.0.1", sock.getsockname()[1])
            try:

                async def send(*events):
                    for event in events:
                        await asyncio.wait_for(async_write_event(event.event(), writer), timeout=5)

                async def receive():
                    return await asyncio.wait_for(async_read_event(reader), timeout=5)

                with private_voice_logs():
                    yield provider, requests, reports, send, receive
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()
            await server._server.wait_closed()


async def test_home_assistant_wyoming_event_sequence(wyoming_peer, caplog):
    from openai.types.audio import Transcription
    from wyoming.asr import Transcribe, Transcript
    from wyoming.audio import AudioChunk, AudioStart, AudioStop
    from wyoming.error import Error
    from wyoming.info import Describe, Info
    from wyoming.tts import Synthesize, SynthesizeVoice

    from stackchan_autonomy.ha_voice import STT_MODEL, TTS_MODEL

    provider, requests, reports, send, receive = wyoming_peer
    question = "모의 질문입니다."
    answer = "모의 답변입니다."
    pcm = b"\x00\x01" * 240
    provider.audio.transcriptions.create.return_value = Transcription(text=question)
    session_update, response_create = AsyncMock(), AsyncMock()

    class Realtime:
        session = SimpleNamespace(update=session_update)
        response = SimpleNamespace(create=response_create)

        async def __aiter__(self):
            yield SimpleNamespace(type="response.output_audio.delta", delta=base64.b64encode(pcm))
            yield SimpleNamespace(type="response.output_audio_transcript.done", transcript=answer)
            yield SimpleNamespace(
                type="response.done", response=SimpleNamespace(status="completed")
            )

    @asynccontextmanager
    async def connect(**kwargs):
        yield Realtime()

    provider.realtime.connect.side_effect = connect
    await send(Describe())
    info = Info.from_event(await receive())
    assert info.asr[0].models[0].languages == ["ko-KR"]
    voice = info.tts[0].voices[0]
    assert voice.languages == ["ko-KR"]
    await send(
        Transcribe(language="ko-KR"),
        AudioStart(rate=16_000, width=2, channels=1),
        AudioChunk(rate=16_000, width=2, channels=1, audio=pcm),
        AudioStop(),
    )
    assert (await receive()).type == "transcript-start"
    assert Transcript.from_event(await receive()).text == question
    assert (await receive()).type == "transcript-stop"
    transcription = provider.audio.transcriptions.create
    transcription.assert_awaited_once()
    assert transcription.call_args.kwargs["model"] == STT_MODEL
    assert transcription.call_args.kwargs["extra_body"]["languages"] == ["ko"]

    turn = Synthesize(text=answer, voice=SynthesizeVoice(name=voice.name, language="ko-KR"))
    await send(turn)
    start = AudioStart.from_event(await receive())
    assert (start.rate, start.width, start.channels) == (24_000, 2, 1)
    assert AudioChunk.from_event(await receive()).audio == pcm
    assert (await receive()).type == "audio-stop"
    provider.realtime.connect.assert_called_once()
    assert provider.realtime.connect.call_args.kwargs["model"] == TTS_MODEL
    assert (
        provider.realtime.connect.call_args.kwargs["websocket_connection_options"]["proxy"] is None
    )
    session_update.assert_awaited_once()
    response_create.assert_awaited_once()

    await send(turn)
    assert Error.from_event(await receive()).text == "HA_VOICE_REQUEST_FAILED"
    provider.realtime.connect.assert_called_once()
    budget = await requests.storage.call(requests.budget.snapshot)
    assert budget.requests == 2
    assert "HA_VOICE_BUDGET_EXHAUSTED" in reports
    assert question not in caplog.text
    assert answer not in caplog.text


@pytest.mark.parametrize("kind", ["provider_error", "long_audio", "long_text"])
async def test_wyoming_errors_are_sanitized_and_invalid_input_does_not_spend(wyoming_peer, kind):
    from wyoming.asr import Transcribe
    from wyoming.audio import AudioChunk, AudioStart, AudioStop
    from wyoming.error import Error
    from wyoming.tts import Synthesize

    provider, requests, reports, send, receive = wyoming_peer
    canary = "private mock transcription"
    provider.audio.transcriptions.create.side_effect = RuntimeError(canary)
    if kind == "long_text":
        await send(Synthesize(text="가" * 801))
    else:
        size = 16_000 * 2 * 8 + 2 if kind == "long_audio" else 480
        await send(
            Transcribe(language="ko-KR"),
            AudioStart(rate=16_000, width=2, channels=1),
            AudioChunk(rate=16_000, width=2, channels=1, audio=b"\x00" * size),
        )
        if kind == "provider_error":
            await send(AudioStop())

    assert Error.from_event(await receive()).text == "HA_VOICE_REQUEST_FAILED"
    budget = await requests.storage.call(requests.budget.snapshot)
    assert budget.requests == (1 if kind == "provider_error" else 0)
    assert reports[-1] == "HA_VOICE_REQUEST_FAILED"
    assert all(canary not in code for code in reports)
    provider.realtime.connect.assert_not_called()
