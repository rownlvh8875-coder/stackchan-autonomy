import asyncio
import json

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI

from stackchan_autonomy.audio import PCM16Audio
from stackchan_autonomy.cloud_audio import AudioUnavailable, OpenAIAudioService
from stackchan_autonomy.settings import Settings


def service(handler, **overrides):
    settings = Settings(
        cloud_enabled=True,
        audio_transmission=True,
        stt_model="configured-stt",
        tts_model="configured-tts",
        tts_voice="configured-voice",
        **overrides,
    )
    client = AsyncOpenAI(
        api_key="not-a-real-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return OpenAIAudioService(settings, client=client), client


async def test_actual_sdk_stt_uses_in_memory_wav_and_korean():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"text": "안녕하세요"})

    voice, client = service(handler)
    async with client:
        result = await voice.transcribe(
            PCM16Audio(pcm=b"\0\0" * 1600, sample_rate=16000, channels=1)
        )
    assert result == "안녕하세요"
    body = requests[0].content
    assert requests[0].url.path == "/v1/audio/transcriptions"
    assert b"RIFF" in body and b"audio/wav" in body and b"configured-stt" in body
    assert b'name="language"\r\n\r\nko' in body
    assert voice.budget.snapshot().requests == 1


async def test_actual_sdk_tts_streams_documented_pcm_format():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=b"\0\0" * 2400, headers={"Content-Type": "audio/pcm"})

    voice, client = service(handler)
    async with client:
        audio = await voice.synthesize("안녕하세요")
    assert (audio.frames, audio.sample_rate, audio.channels) == (2400, 24000, 1)
    assert bodies == [
        {
            "input": "안녕하세요",
            "model": "configured-tts",
            "voice": "configured-voice",
            "response_format": "pcm",
        }
    ]


@pytest.mark.parametrize("case", ["server", "timeout", "bad_transcript", "bad_pcm", "oversized"])
async def test_audio_errors_are_bounded_private_and_do_not_retry(case, caplog):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if case == "timeout":
            await asyncio.Event().wait()
        if case == "server":
            return httpx.Response(500, json={"error": {"message": "private-secret-audio"}})
        if case == "bad_transcript":
            return httpx.Response(200, json={"text": ""})
        return httpx.Response(200, content=b"x" if case == "bad_pcm" else b"\0" * (1_440_000 + 2))

    voice, client = service(handler, operation_timeout_s=0.05)
    async with client:
        with pytest.raises(AudioUnavailable):
            if case in {"bad_pcm", "oversized"}:
                await voice.synthesize("private-secret-audio")
            else:
                await voice.transcribe(PCM16Audio(pcm=b"\0\0" * 160, sample_rate=16000, channels=1))
    assert calls == 1
    assert voice.budget.snapshot().requests == 1
    assert "private-secret-audio" not in caplog.text


async def test_stt_and_tts_share_persistent_budget_and_renewed_consent():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "안녕"})

    voice, client = service(handler, requests_per_minute=1)
    async with client:
        await voice.transcribe(PCM16Audio(pcm=b"\0\0" * 160, sample_rate=16000, channels=1))
        with pytest.raises(AudioUnavailable):
            await voice.synthesize("안녕")
        voice.settings.audio_transmission = False
        with pytest.raises(PermissionError):
            await voice.transcribe(PCM16Audio(pcm=b"\0\0" * 160, sample_rate=16000, channels=1))
    assert calls == 1


def test_audio_cloud_is_disabled_without_explicit_consent():
    with pytest.raises(PermissionError):
        OpenAIAudioService(Settings())


async def test_injected_sdk_default_retries_cannot_exceed_one_budget_reservation():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": {"message": "private error"}})

    settings = Settings(cloud_enabled=True, audio_transmission=True, stt_model="configured-stt")
    client = AsyncOpenAI(
        api_key="not-real", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    voice = OpenAIAudioService(settings, client=client)
    async with client:
        with pytest.raises(AudioUnavailable):
            await voice.transcribe(PCM16Audio(pcm=b"\0\0" * 160, sample_rate=16000, channels=1))
    assert calls == 1
    assert voice.budget.snapshot().requests == 1
