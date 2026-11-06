import asyncio
import json
from collections import deque

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI

from stackchan_autonomy.decision import MockDecisionProvider, OpenAIDecisionProvider
from stackchan_autonomy.memory import Memory
from stackchan_autonomy.models import (
    Decision,
    DecisionContext,
    Event,
    EventKind,
    Observation,
    RobotStatus,
)
from stackchan_autonomy.safety import RequestBudget, SafetyPolicy, UnsafeDecision
from stackchan_autonomy.settings import Settings


def context(kind=EventKind.PERSON_DETECTED):
    return DecisionContext(event=Event(kind=kind), status=RobotStatus())


@pytest.mark.parametrize(
    "decision,status",
    [
        (Decision(intent="look", yaw_delta_deg=16), RobotStatus()),
        (Decision(intent="look", pitch_delta_deg=-10), RobotStatus(pitch=6)),
        (Decision(intent="look", yaw_delta_deg=5), RobotStatus(yaw=89)),
        (Decision(intent="idle", speech="hidden action"), RobotStatus()),
        (Decision(intent="speak", speech="hello", yaw_delta_deg=1), RobotStatus()),
        (Decision(intent="speak", speech=""), RobotStatus()),
        (Decision(intent="emote", emotion="happy", speech="compound"), RobotStatus()),
    ],
)
def test_unsafe_and_compound_actions_never_produce_commands(decision, status):
    with pytest.raises(UnsafeDecision):
        SafetyPolicy(Settings()).plan(decision, status)


def test_motor_targets_are_absolute_and_conservative():
    commands = SafetyPolicy(Settings()).plan(
        Decision(intent="look", yaw_delta_deg=10, pitch_delta_deg=-5),
        RobotStatus(yaw=20, pitch=50),
    )
    assert len(commands) == 1
    assert commands[0].yaw == 30
    assert commands[0].pitch == 45


def test_sliding_budgets_reserve_failed_requests_and_recover():
    budget = RequestBudget(Settings(requests_per_minute=2, requests_per_hour=3, requests_per_day=4))
    assert budget.reserve(0)
    assert budget.reserve(1)
    assert not budget.reserve(2)
    assert budget.reserve(61)
    assert not budget.reserve(122)  # hourly bound
    assert budget.reserve(3602)
    assert not budget.reserve(7202)  # daily bound
    assert budget.reserve(86403)
    assert budget.total == 5
    assert len(budget.timestamps) <= 4


async def test_mock_ai_responds_to_simulated_person_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    decision = await MockDecisionProvider().decide(Observation(person_present=True), context())
    assert decision.intent == "speak"
    assert "안녕" in decision.speech


def test_memory_persists_only_bounded_metadata(tmp_path):
    path = tmp_path / "memory.sqlite"
    memory = Memory(limit=2, path=path)
    for i in range(5):
        memory.record(i, EventKind.TOUCH_TAP, "speak", "executed")
    assert len(memory.recent()) == 2
    assert memory.last_spoken_at == 4
    memory.close()
    reloaded = Memory(limit=2, path=path)
    assert [r.at for r in reloaded.recent()] == [3, 4]
    assert reloaded.last_spoken_at == 4
    reloaded.close()


def response_payload(output, *, status="completed"):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "model": "account-selected-model",
        "status": status,
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "metadata": {},
        "output": output,
        "parallel_tool_calls": False,
        "temperature": 1,
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1,
        "usage": {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
    }


def message(text):
    return [
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }
    ]


def provider_with_transport(handler, **overrides):
    settings = Settings(cloud_enabled=True, openai_model="account-selected-model", **overrides)
    client = AsyncOpenAI(
        api_key="not-a-real-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return OpenAIDecisionProvider(settings, client=client), client


async def test_real_sdk_responses_request_is_structured_and_private():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=response_payload(
                message(
                    '{"intent":"emote","emotion":"happy","speech":"",'
                    '"yaw_delta_deg":0,"pitch_delta_deg":0,"reason":"scene"}'
                )
            ),
        )

    provider, client = provider_with_transport(handler)
    async with client:
        result = await provider.decide(Observation(image=b"private-image"), context())
    assert result.intent == "emote"
    request = requests[0]
    assert request["model"] == "account-selected-model"
    assert request["store"] is False
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert request["text"]["format"]["schema"]["additionalProperties"] is False
    assert "private-image" not in json.dumps(request)
    assert "input_image" not in json.dumps(request)
    assert provider.usage.input_tokens == 4
    assert provider.usage.output_tokens == 5


@pytest.mark.parametrize(
    "case",
    [
        "malformed",
        "refusal",
        "incomplete",
        "rate_limit",
        "server_error",
        "timeout",
        "unsupported",
        "null",
    ],
)
async def test_cloud_failures_are_idle_without_retry_or_private_logging(case, caplog):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if case == "timeout":
            raise httpx.ReadTimeout("private-utterance-secret", request=request)
        if case in {"rate_limit", "server_error"}:
            return httpx.Response(
                429 if case == "rate_limit" else 500,
                json={"error": {"message": "private-utterance-secret"}},
            )
        if case == "refusal":
            output = [
                {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "refusal", "refusal": "private-utterance-secret"}],
                }
            ]
        else:
            text = {
                "malformed": "bad json",
                "unsupported": '{"intent":"delete"}',
                "null": "null",
            }.get(case, '{"intent":"speak","speech":"hello"}')
            output = message(text)
        return httpx.Response(
            200,
            json=response_payload(
                output, status="incomplete" if case == "incomplete" else "completed"
            ),
        )

    provider, client = provider_with_transport(handler)
    async with client:
        result = await provider.decide(Observation(), context())
    assert result.intent == "idle"
    assert calls == 1
    assert "private-utterance-secret" not in caplog.text


async def test_cloud_disabled_and_budget_do_not_send_requests():
    replies = deque([httpx.Response(200, json=response_payload(message('{"intent":"idle"}')))])
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return replies[0]

    provider, client = provider_with_transport(handler, requests_per_minute=1)
    async with client:
        await provider.decide(Observation(), context())
        result = await provider.decide(Observation(), context())
    assert result.intent == "idle"
    assert calls == 1
    with pytest.raises(ValueError):
        OpenAIDecisionProvider(Settings(cloud_enabled=False))


async def test_provider_enforces_wall_timeout_even_with_a_stalled_transport():
    async def handler(request):
        await asyncio.Event().wait()

    provider, client = provider_with_transport(handler, operation_timeout_s=0.02)
    async with client:
        result = await asyncio.wait_for(provider.decide(Observation(), context()), timeout=1)
    assert result.intent == "idle"
    assert not provider.last_succeeded


async def test_image_is_only_included_with_explicit_transmission_setting():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_payload(message('{"intent":"idle"}')))

    provider, client = provider_with_transport(handler, image_transmission=True)
    async with client:
        await provider.decide(Observation(image=b"fixture", image_mime="image/png"), context())
    image = requests[0]["input"][0]["content"][1]
    assert image["type"] == "input_image"
    assert image["image_url"] == "data:image/png;base64,Zml4dHVyZQ=="


async def test_provider_recreation_cannot_reset_persistent_budget():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=response_payload(message('{"intent":"idle"}')))

    first, client = provider_with_transport(handler, requests_per_minute=1)
    async with client:
        await first.decide(Observation(), context())
    replacement, client = provider_with_transport(handler, requests_per_minute=1)
    async with client:
        decision = await replacement.decide(Observation(), context())
    assert calls == 1
    assert decision.intent == "idle"
    persisted = replacement.budget.snapshot()
    assert (persisted.requests, persisted.input_tokens, persisted.output_tokens) == (1, 4, 5)


async def test_budget_storage_failure_sends_no_http_and_logs_no_private_path(tmp_path):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=response_payload(message('{"intent":"idle"}')))

    provider, client = provider_with_transport(handler)
    provider.settings.state_path.write_bytes(b"invalid sqlite")
    async with client:
        result = await provider.decide(Observation(), context())
    assert result.intent == "idle"
    assert calls == 0
