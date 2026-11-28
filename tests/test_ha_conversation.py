"""Home Assistant's text transport and the shared speech/Responses request budget."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI
from test_gpt_chat import response_payload

from stackchan_autonomy.gpt_chat import GPTChat
from stackchan_autonomy.ha_voice import STT_MODEL, TTS_MODEL, VoiceDenied, VoiceRequests
from stackchan_autonomy.settings import Settings


def settings(**changes):
    values = {
        "cloud_enabled": True,
        "audio_transmission": True,
        "openai_model": "offline-model",
        "requests_per_minute": 6,
    } | changes
    return Settings(_env_file=None, OPENAI_API_KEY="fixture-key", **values)


@asynccontextmanager
async def agent(config, provider, *, clock=lambda: 100):
    from stackchan_autonomy.ha_conversation import create_app

    client = AsyncOpenAI(
        api_key="fixture-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
    )
    async with (
        GPTChat(config, client=client, clock=clock) as chat,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(chat)),
            base_url="http://127.0.0.1:10301",
        ) as peer,
    ):
        yield peer, chat


async def test_two_voice_turns_share_six_calls_and_keep_the_limit_after_restart():
    calls = []

    def reply(request):
        calls.append("gpt")
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        assert body["store"] is False and "tools" not in body
        assert body["input"] == [{"role": "user", "content": f"질문 {len(calls) // 3 + 1}"}]
        return httpx.Response(200, json=response_payload("모의 답변입니다."))

    async def transcribe(**_):
        calls.append("stt")

    @asynccontextmanager
    async def connect(**_):
        calls.append("tts")
        yield object()

    config = settings()
    audio = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(create=AsyncMock(side_effect=transcribe))
        ),
        realtime=SimpleNamespace(connect=Mock(side_effect=connect)),
    )
    async with VoiceRequests(config, audio, emit=lambda _: None, clock=lambda: 100) as voice:
        async with agent(config, reply) as (peer, chat):
            for text in ("질문 1", "질문 2"):
                await voice.transcribe(model=STT_MODEL)
                answer = await peer.post("/answer", json={"text": text})
                assert answer.status_code == 200
                assert answer.json() == {"answer": "모의 답변입니다."}
                async with voice.realtime(model=TTS_MODEL, websocket_connection_options={}):
                    pass
            assert chat.budget.snapshot().requests == 6

    def forbidden(_):
        pytest.fail("restart dispatched a paid request after the shared limit")

    async with VoiceRequests(config, audio, emit=lambda _: None, clock=lambda: 100) as restarted:
        with pytest.raises(VoiceDenied, match="HA_VOICE_BUDGET_EXHAUSTED"):
            await restarted.transcribe(model=STT_MODEL)
    async with agent(config, forbidden) as (peer, chat):
        denied = await peer.post("/answer", json={"text": "다음 질문"})
        assert (denied.status_code, denied.json()) == (429, {"error": "budget_exhausted"})
        assert chat.budget.snapshot().requests == 6
    assert calls == ["stt", "gpt", "tts"] * 2
    async with agent(
        config, lambda _: httpx.Response(200, json=response_payload()), clock=lambda: 160
    ) as (peer, chat):
        allowed = await peer.post("/answer", json={"text": "다음 분 질문"})
        assert allowed.status_code == 200
        assert chat.budget.snapshot().requests == 7


@pytest.mark.parametrize(
    "request_values",
    [
        {"json": {"text": "test"}, "headers": {"Host": "untrusted.example"}},
        {"json": {"text": "test"}, "headers": {"Origin": "http://127.0.0.1:10301"}},
        {"content": b'{"text":"test"}', "headers": {"Content-Type": "text/plain"}},
        {"json": {"text": "test", "model": "unapproved"}},
        {"json": {"text": "x" * 1201}},
        {"json": {"text": " "}},
        {"content": b" " * 16385, "headers": {"Content-Type": "application/json"}},
    ],
)
async def test_unaccepted_local_requests_do_not_spend(request_values):
    def forbidden(_):
        pytest.fail("invalid local request dispatched to OpenAI")

    async with agent(settings(), forbidden) as (peer, chat):
        response = await peer.post("/answer", **request_values)
        assert 400 <= response.status_code < 500
        assert chat.budget.snapshot().requests == 0


async def test_service_returns_fixed_failure_without_refund(caplog):
    canary = "offline-provider-exception-canary"

    def reply(_):
        return httpx.Response(500, json={"error": {"message": canary}})

    async with agent(settings(), reply) as (peer, chat):
        result = await peer.post("/answer", json={"text": "모의 질문"})
        assert (result.status_code, result.json()) == (502, {"error": "unavailable"})
        assert chat.budget.snapshot().requests == 1
    assert canary not in result.text and canary not in caplog.text


async def test_disconnected_question_waiting_for_gpt_never_dispatches_later():
    from stackchan_autonomy.ha_conversation import create_app

    started = asyncio.Event()
    finish_first = asyncio.Event()
    calls = []

    async def respond(request):
        calls.append(json.loads(request.content)["input"][-1]["content"])
        started.set()
        await finish_first.wait()
        return httpx.Response(200, json=response_payload())

    async with agent(settings(), respond) as (_, chat):
        first = asyncio.create_task(chat.ask("먼저 받은 질문", remember=False))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            events = iter(
                (
                    {"type": "http.request", "body": b'{"text":"queued"}', "more_body": False},
                    {"type": "http.disconnect"},
                )
            )

            async def receive():
                return next(events)

            await asyncio.wait_for(
                create_app(chat)(
                    {
                        "type": "http",
                        "method": "POST",
                        "path": "/answer",
                        "headers": [
                            (b"host", b"127.0.0.1:10301"),
                            (b"content-type", b"application/json"),
                        ],
                    },
                    receive,
                    AsyncMock(),
                ),
                timeout=1,
            )
        finally:
            finish_first.set()
            await first
        assert chat.budget.snapshot().requests == 1
    assert calls == ["먼저 받은 질문"]


@pytest.mark.parametrize(
    "changes",
    [
        {"cloud_enabled": False},
        {"audio_transmission": False},
        {"openai_model": None},
        {"requests_per_minute": 2},
        {"requests_per_hour": 2},
        {"requests_per_day": 2},
    ],
)
def test_launch_requires_opt_in_model_and_capacity_for_all_three_stages(changes):
    from stackchan_autonomy.ha_conversation import validate_config
    from stackchan_autonomy.ha_voice import VoiceDenied

    with pytest.raises(VoiceDenied, match="HA_GPT_CONFIG_REQUIRED"):
        validate_config(settings(**changes))
