"""Real Responses SDK, local HTTP transport and persistent budget; no paid calls."""

import asyncio
import importlib
import json

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI

from stackchan_autonomy.settings import Settings

PRIVATE = "private-question-or-key-no-echo"


def module():
    return importlib.import_module("stackchan_autonomy.gpt_chat")


def response_payload(answer="안녕하세요. GPT가 만든 답변입니다.", *, status="completed", text=None):
    return {
        "id": "resp_offline",
        "object": "response",
        "created_at": 0,
        "model": "account-selected-model",
        "status": status,
        "error": None,
        "incomplete_details": None,
        "output": [
            {
                "id": "msg_offline",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"answer": answer}) if text is None else text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
    }


def settings(tmp_path, **values):
    return Settings(
        _env_file=None,
        cloud_enabled=True,
        openai_model="account-selected-model",
        state_path=tmp_path / "budget.sqlite3",
        **values,
    )


def service(tmp_path, handler, *, clock=lambda: 0, **values):
    config = settings(tmp_path, **values)
    client = AsyncOpenAI(
        api_key=PRIVATE,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return module().GPTChat(config, client=client, clock=clock)


async def test_real_sdk_returns_structured_gpt_answer_and_private_bounded_request(tmp_path, caplog):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_payload())

    async with service(tmp_path, handler) as chat:
        result = await chat.ask("  한국어로 인사해 줘  ")
        usage = chat.budget.snapshot()
    assert result == {
        "service": "stackchan-gpt",
        "provider": "openai_responses",
        "model": "account-selected-model",
        "answer": "안녕하세요. GPT가 만든 답변입니다.",
        "robot_control_available": False,
    }
    (sent,) = requests
    assert sent["model"] == "account-selected-model"
    assert sent["input"] == [{"role": "user", "content": "한국어로 인사해 줘"}]
    assert sent["store"] is False and sent["max_output_tokens"] == 600
    assert sent["text"]["format"]["type"] == "json_schema"
    assert sent["text"]["format"]["strict"] is True
    assert sent["text"]["format"]["schema"]["additionalProperties"] is False
    assert "tools" not in sent and "input_image" not in json.dumps(sent)
    assert usage.requests == 1 and usage.input_tokens == 4 and usage.output_tokens == 5
    assert PRIVATE not in caplog.text and "한국어로 인사해 줘" not in caplog.text


async def test_only_three_successful_turns_are_kept_in_memory_and_restart_starts_empty(tmp_path):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content)["input"])
        return httpx.Response(200, json=response_payload(f"답변{len(requests)}"))

    async with service(tmp_path, handler, requests_per_minute=60) as chat:
        for i in range(5):
            await chat.ask(f"질문{i + 1}")
    assert requests[1] == [
        {"role": "user", "content": "질문1"},
        {"role": "assistant", "content": "답변1"},
        {"role": "user", "content": "질문2"},
    ]
    assert requests[4] == [
        {"role": "user", "content": "질문2"},
        {"role": "assistant", "content": "답변2"},
        {"role": "user", "content": "질문3"},
        {"role": "assistant", "content": "답변3"},
        {"role": "user", "content": "질문4"},
        {"role": "assistant", "content": "답변4"},
        {"role": "user", "content": "질문5"},
    ]
    async with service(tmp_path, handler, requests_per_minute=60) as restarted:
        await restarted.ask("새 질문")
        database = restarted.budget.store.path
    assert requests[-1] == [{"role": "user", "content": "새 질문"}]
    assert "질문1".encode() not in database.read_bytes()


@pytest.mark.parametrize("question", [None, b"bytes", " \n", "x" * 1201, "bad\x00", "bad\ud800"])
async def test_invalid_question_never_spends_a_reservation_or_calls_api(tmp_path, question):
    def forbidden(request):
        raise AssertionError("invalid input reached API")

    async with service(tmp_path, forbidden) as chat:
        with pytest.raises(module().GPTChatError, match="^PC_GPT_INVALID_QUESTION$"):
            await chat.ask(question)
        assert chat.budget.snapshot().requests == 0


@pytest.mark.parametrize(
    "failure",
    [
        "malformed",
        "untyped_block",
        "shape",
        "refusal",
        "incomplete",
        "empty",
        "long",
        "429",
        "500",
        "timeout",
    ],
)
async def test_failure_is_fixed_private_spent_and_not_retried(tmp_path, failure, caplog, capsys):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout(PRIVATE, request=request)
        if failure in {"429", "500"}:
            return httpx.Response(int(failure), json={"error": {"message": PRIVATE}})
        data = response_payload()
        if failure == "malformed":
            data = response_payload(text=PRIVATE)
        if failure == "untyped_block":
            data["output"][0]["content"] = [{"type": "unknown", "secret": PRIVATE}]
        if failure == "shape":
            data = response_payload(text=json.dumps({"answer": "ok", "secret": PRIVATE}))
        if failure == "refusal":
            data["output"][0]["content"] = [{"type": "refusal", "refusal": PRIVATE}]
        if failure == "incomplete":
            data["status"] = "incomplete"
        if failure == "empty":
            data = response_payload("  ")
        if failure == "long":
            data = response_payload("x" * 801)
        return httpx.Response(200, json=data)

    async with service(tmp_path, handler) as chat:
        with pytest.raises(module().GPTChatError, match="^PC_GPT_UNAVAILABLE$") as caught:
            await chat.ask(PRIVATE)
        assert chat.budget.snapshot().requests == 1
    assert calls == 1
    assert PRIVATE not in str(caught.value) + repr(caught.value) + caplog.text + str(
        capsys.readouterr()
    )


async def test_restart_does_not_refund_failed_requests(tmp_path):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": {"message": PRIVATE}})

    async with service(tmp_path, handler) as chat:
        with pytest.raises(module().GPTChatError):
            await chat.ask("실패 요청1")
        with pytest.raises(module().GPTChatError):
            await chat.ask("실패 요청2")
    async with service(tmp_path, handler) as restarted:
        with pytest.raises(module().GPTChatError, match="^PC_GPT_BUDGET_EXHAUSTED$"):
            await restarted.ask("거부 요청")
        assert restarted.budget.snapshot().requests == 2
    assert calls == 2


async def test_storage_failure_prevents_network_request(tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("blocked")
    config = settings(tmp_path)
    config.state_path = blocked / "budget.sqlite3"

    def forbidden(request):
        raise AssertionError("unreserved request reached API")

    client = AsyncOpenAI(
        api_key=PRIVATE,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(forbidden)),
    )
    async with module().GPTChat(config, client=client, clock=lambda: 0) as chat:
        with pytest.raises(module().GPTChatError, match="^PC_GPT_STORAGE_UNAVAILABLE$"):
            await chat.ask("저장 실패")


async def test_cancellation_spends_reservation_and_drains_without_retained_history(tmp_path):
    reached = asyncio.Event()

    async def handler(request):
        reached.set()
        await asyncio.Event().wait()

    chat = service(tmp_path, handler)
    async with chat:
        task = asyncio.create_task(chat.ask("취소 요청"))
        await asyncio.wait_for(reached.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert chat.budget.snapshot().requests == 1
    assert chat.client.is_closed()


@pytest.mark.parametrize("case", ["disabled", "no_model", "bad_model", "no_key"])
def test_real_client_requires_explicit_cloud_model_and_private_key(tmp_path, case):
    from pydantic import SecretStr

    config = settings(tmp_path)
    config.api_key = None if case == "no_key" else SecretStr(PRIVATE)
    if case == "disabled":
        config.cloud_enabled = False
    if case == "no_model":
        config.openai_model = None
    if case == "bad_model":
        config.openai_model = "model\n" + PRIVATE
    with pytest.raises(module().GPTChatError, match="^PC_GPT_CONFIG_REQUIRED$") as caught:
        module().GPTChat(config)
    assert PRIVATE not in str(caught.value)


async def test_real_client_ignores_api_base_url_override_and_disables_redirects(
    tmp_path, monkeypatch
):
    from pydantic import SecretStr

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/private")
    config = settings(tmp_path)
    config.api_key = SecretStr(PRIVATE)
    async with module().GPTChat(config) as chat:
        assert str(chat.client.base_url) == "https://api.openai.com/v1/"
        assert chat.client._client.follow_redirects is False
        assert chat.client.max_retries == 0


async def test_http_deadline_cancels_blocked_response_without_retry(tmp_path):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        await asyncio.Event().wait()

    async with service(tmp_path, handler, operation_timeout_s=0.05) as chat:
        with pytest.raises(module().GPTChatError, match="^PC_GPT_UNAVAILABLE$"):
            await asyncio.wait_for(chat.ask("시간초과"), 2)
        assert chat.budget.snapshot().requests == 1
    assert calls == 1


async def test_private_sdk_debug_handlers_cannot_echo_question_or_key(tmp_path, caplog):
    import io
    import logging

    stream = io.StringIO()
    logger = logging.getLogger("openai._base_client")
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        async with service(
            tmp_path, lambda request: httpx.Response(500, json={"error": {"message": PRIVATE}})
        ) as chat:
            with pytest.raises(module().GPTChatError):
                await chat.ask(PRIVATE)
        assert PRIVATE not in stream.getvalue() + caplog.text
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


async def test_slow_budget_io_runs_off_the_event_loop(tmp_path, monkeypatch):
    import threading

    entered, release = threading.Event(), threading.Event()
    async with service(
        tmp_path, lambda request: httpx.Response(200, json=response_payload())
    ) as chat:
        reserve = chat.budget.reserve

        def slow_reserve(now):
            entered.set()
            release.wait(2)
            return reserve(now)

        monkeypatch.setattr(chat.budget, "reserve", slow_reserve)
        task = asyncio.create_task(chat.ask("저장 대기"))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 1), 2)
            assert not task.done()
        finally:
            release.set()
        assert (await asyncio.wait_for(task, 2))["answer"] == "안녕하세요. GPT가 만든 답변입니다."
