"""Optional Home Assistant Core to Responses transport test with no paid calls."""

import asyncio
import importlib
import json
import shutil
import socket
from pathlib import Path

import pytest


async def test_real_home_assistant_registers_and_calls_stackchan_agent(tmp_path, monkeypatch):
    conversation = pytest.importorskip("homeassistant.components.conversation")
    import httpx2 as httpx
    from homeassistant import loader
    from homeassistant.bootstrap import async_from_config_dict
    from homeassistant.config_entries import SOURCE_USER
    from homeassistant.core import Context, HomeAssistant
    from openai import AsyncOpenAI
    from test_gpt_chat import response_payload
    from uvicorn import Config, Server

    from stackchan_autonomy.gpt_chat import GPTChat
    from stackchan_autonomy.ha_conversation import create_app
    from stackchan_autonomy.settings import Settings

    source = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "home_assistant"
        / "custom_components"
        / "stackchan_gpt"
    )
    shutil.copytree(source, tmp_path / "custom_components" / source.name)
    calls = []

    def answer(request):
        calls.append(json.loads(request.content)["input"])
        return httpx.Response(200, json=response_payload("한국어 답변인가요?"))

    settings = Settings(
        _env_file=None, cloud_enabled=True, openai_model="offline-model", requests_per_minute=3
    )
    client = AsyncOpenAI(
        api_key="synthetic-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)),
    )
    config = {"http": {"server_host": "127.0.0.1"}}
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    hass.config.skip_pip = True
    try:
        assert await async_from_config_dict(config, hass) is hass
        result = await hass.config_entries.flow.async_init(
            "stackchan_gpt", context={"source": SOURCE_USER}
        )
        assert result["type"] == "create_entry"
        entry = result["result"]
        await hass.async_block_till_done()
        agent_id = "conversation.stackchan_gpt"
        assert conversation.async_get_agent(hass, agent_id).supported_languages == ["ko", "ko-KR"]

        async with GPTChat(settings, client=client, clock=lambda: 100) as chat:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
                server = Server(Config(create_app(chat), access_log=False, log_config=None))
                serving = asyncio.create_task(server.serve(sockets=[listener]))
                try:
                    async with asyncio.timeout(5):
                        while not server.started:
                            await asyncio.sleep(0.01)
                    adapter = importlib.import_module(
                        "custom_components.stackchan_gpt.conversation"
                    )
                    monkeypatch.setattr(adapter, "ANSWER_URL", f"http://127.0.0.1:{port}/answer")
                    assert chat.budget.reserve(100)  # STT reservation
                    first = await conversation.async_converse(
                        hass, "모의 질문", None, Context(), language="ko-KR", agent_id=agent_id
                    )
                    assert first.response.speech["plain"]["speech"] == "한국어 답변인가요?"
                    assert not first.continue_conversation
                    assert chat.budget.reserve(100)  # TTS reservation

                    denied = await conversation.async_converse(
                        hass,
                        "다음 질문",
                        first.conversation_id,
                        Context(),
                        language="ko-KR",
                        agent_id=agent_id,
                    )
                    assert (
                        denied.response.speech["plain"]["speech"]
                        == "지금은 대화 사용량 한도에 도달했어요."
                    )
                    assert not denied.continue_conversation
                    assert chat.budget.snapshot().requests == 3
                    assert calls == [[{"role": "user", "content": "모의 질문"}]]
                finally:
                    server.should_exit = True
                    await serving
        assert await hass.config_entries.async_unload(entry.entry_id)
    finally:
        await hass.async_stop(force=True)
