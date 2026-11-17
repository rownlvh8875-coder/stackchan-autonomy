"""Actual SDK/MCP paths with synthetic image and local transport only."""

import asyncio
import base64
import io
import json
import time

import httpx2 as httpx
import pytest
from PIL import Image
from test_gpt_chat import response_payload, service
from test_observer import BOOT, DEVICE, metadata, picture
from test_official_mcp import bridge_module, initialize, local_endpoint, request

from stackchan_autonomy.observer_protocol import ObserverError, Snapshot, VerifiedObservation


def observation(*, age=0):
    nonce = bytes(range(16))
    jpeg = picture()
    return VerifiedObservation.validate(
        jpeg,
        Snapshot.model_validate(metadata(nonce, jpeg)),
        nonce=nonce,
        boot_id=BOOT,
        received_at=time.monotonic() - age,
    )


async def test_image_sdk_request_is_private_bounded_and_separate_from_text_history(
    tmp_path, caplog
):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=response_payload("사진을 확인했습니다."))

    async with service(tmp_path, handler, image_transmission=True, requests_per_minute=60) as chat:
        await chat.ask("첫 질문")
        before = list(chat._history)
        result = await chat.observe("무엇이 보여?", observation())
        assert chat._history == before
        await chat.ask("다음 질문")
        assert chat.budget.snapshot().requests == 3
    body = sent[1]
    content = body["input"][0]["content"]
    assert len(body["input"]) == 1 and len(content) == 2
    assert content[0]["type"] == "input_text" and "무엇이 보여?" in content[0]["text"]
    assert content[1]["type"] == "input_image"
    uploaded = base64.b64decode(content[1]["image_url"].split(",", 1)[1])
    with Image.open(io.BytesIO(uploaded)) as decoded:
        assert decoded.size == (16, 12) and not decoded.getexif()
    assert body["store"] is False and "tools" not in body
    assert BOOT not in str(body) and DEVICE not in str(body)
    assert "input_image" not in str(sent[2]) and "무엇이 보여?" not in str(sent[2])
    assert result["answer"] == "사진을 확인했습니다."
    assert (
        result["robot_control_available"] is False and result["source"] == "usb_observer_prototype"
    )
    assert "무엇이 보여?" not in caplog.text and "base64," not in caplog.text


@pytest.mark.parametrize("consent,age", [(False, 0), (True, 11)])
async def test_no_consent_or_stale_capture_never_reserves_quota(tmp_path, consent, age):
    def forbidden(request):
        pytest.fail("unexpected API request")

    async with service(tmp_path, forbidden, image_transmission=consent) as chat:
        with pytest.raises(ObserverError):
            await chat.observe("질문", observation(age=age))
        assert chat.budget.snapshot().requests == 0


async def test_forged_observation_revalidated_before_quota(tmp_path):
    item = observation()
    async with service(
        tmp_path, lambda r: pytest.fail("API called"), image_transmission=True
    ) as chat:
        with pytest.raises(ObserverError):
            VerifiedObservation(b"not jpeg", item.metadata, item.received_at)
        assert chat.budget.snapshot().requests == 0


async def test_upload_removes_exif_device_metadata_and_trailing_data(tmp_path):
    image = Image.new("RGB", (16, 12), "orange")
    exif = Image.Exif()
    exif[0x010E] = "PRIVATE-DEVICE-SERIAL"
    stream = io.BytesIO()
    image.save(stream, format="JPEG", exif=exif)
    raw = stream.getvalue() + b"PRIVATE-TRAILING-DATA"
    nonce = bytes(range(16))
    item = VerifiedObservation.validate(
        raw, Snapshot.model_validate(metadata(nonce, raw)), nonce=nonce, boot_id=BOOT
    )
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=response_payload())

    async with service(tmp_path, handler, image_transmission=True) as chat:
        await chat.observe("사진 설명", item)
    url = sent[0]["input"][0]["content"][1]["image_url"]
    uploaded = base64.b64decode(url.split(",", 1)[1])
    assert b"PRIVATE" not in uploaded and uploaded.endswith(b"\xff\xd9")
    with Image.open(io.BytesIO(uploaded)) as decoded:
        assert decoded.size == (16, 12) and not decoded.getexif()


async def test_mcp_cancellation_during_capture_suppresses_upload(monkeypatch, tmp_path):
    module = bridge_module()
    entered, release = asyncio.Event(), asyncio.Event()

    class Provider:
        async def capture(self):
            entered.set()
            await release.wait()
            return observation()

    async def peer(socket):
        await initialize(socket)
        await socket.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "stackchan_gpt_observe", "arguments": {"question": "설명"}},
                }
            )
        )
        await entered.wait()
        await socket.send(
            json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 2}}
            )
        )
        await asyncio.sleep(0.05)
        release.set()
        result = json.loads(await socket.recv())
        assert "error" in result or result["result"]["isError"]
        return await request(
            socket, 3, "tools/call", {"name": "stackchan_pc_connection_status", "arguments": {}}
        )

    async with service(
        tmp_path, lambda r: pytest.fail("cancelled image uploaded"), image_transmission=True
    ) as chat:
        async with local_endpoint(module, monkeypatch, peer, gpt=chat, observer=Provider()) as (
            _,
            result,
            lines,
        ):
            await asyncio.wait_for(result, 5)
            assert chat.budget.snapshot().requests == 0
            assert "PC_OBSERVE_ANSWERED=1" not in lines


def test_observer_cli_requires_gpt_and_consent_before_endpoint_prompt(monkeypatch, capsys):
    from stackchan_autonomy import official_mcp_cli as cli

    monkeypatch.setenv("STACKCHAN_CLOUD_ENABLED", "true")
    monkeypatch.setenv("STACKCHAN_OPENAI_MODEL", "offline-model")
    monkeypatch.setenv("OPENAI_API_KEY", "offline-key")
    monkeypatch.setenv("STACKCHAN_IMAGE_TRANSMISSION", "false")
    monkeypatch.setattr(cli, "_endpoint_input", lambda: pytest.fail("endpoint requested"))
    assert cli.main(["--observer-port", "private-port"]) == 2
    assert capsys.readouterr().err == "OFFICIAL_MCP_ARGUMENTS_INVALID\n"
    assert cli.main(["--gpt", "--observer-port", "private-port"]) == 2
    assert capsys.readouterr().err == "PC_OBSERVER_CONSENT_REQUIRED\n"


async def test_real_mcp_image_tool_and_markers(monkeypatch, tmp_path):
    module = bridge_module()

    class Provider:
        calls = 0

        async def capture(self):
            self.calls += 1
            return observation()

    provider = Provider()

    def handler(request):
        assert "input_image" in str(json.loads(request.content))
        return httpx.Response(200, json=response_payload("합성 사진 시험 답변입니다."))

    async def peer(socket):
        await initialize(socket)
        listing = await request(socket, 2, "tools/list", {})
        tools = listing["result"]["tools"]
        assert len(tools) == 4 and tools[-1]["name"] == "stackchan_gpt_observe"
        failed = await request(
            socket,
            3,
            "tools/call",
            {"name": "stackchan_gpt_observe", "arguments": {"question": " "}},
        )
        assert failed["result"]["isError"] is True and provider.calls == 0
        return await request(
            socket,
            4,
            "tools/call",
            {"name": "stackchan_gpt_observe", "arguments": {"question": "앞에 무엇이 있어?"}},
        )

    async with service(tmp_path, handler, image_transmission=True) as gpt:
        async with local_endpoint(module, monkeypatch, peer, gpt=gpt, observer=provider) as (
            _,
            result,
            lines,
        ):
            reply = await asyncio.wait_for(result, 5)
            assert reply["result"]["structuredContent"]["answer"] == "합성 사진 시험 답변입니다."
            assert provider.calls == 1
            assert "PC_OBSERVE_ANSWERED=1" in lines
            assert BOOT not in str(lines) and "base64" not in str(lines)


async def test_cancelled_serial_open_finishes_worker_and_closes(tmp_path):
    import threading

    from stackchan_autonomy.observer_async import AsyncObserver

    entered, release = threading.Event(), threading.Event()

    class Client:
        closed = False

        def __enter__(self):
            entered.set()
            release.wait(2)
            return self

        def close(self):
            self.closed = True

    client = Client()
    provider = AsyncObserver("port", client=client)
    task = asyncio.create_task(provider.__aenter__())
    while not entered.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.closed and not provider.worker.pending
