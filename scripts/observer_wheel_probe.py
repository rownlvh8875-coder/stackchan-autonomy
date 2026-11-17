"""Isolated installed-wheel probe: synthetic serial/SDK paths, no device or API calls."""

import asyncio
import hashlib
import io
import json
import socket
import struct
import tempfile
import threading
import zlib
from pathlib import Path

import httpx2 as httpx
from openai import AsyncOpenAI
from PIL import Image

from stackchan_autonomy.gpt_chat import GPTChat
from stackchan_autonomy.observer import ObserverClient, save_profile
from stackchan_autonomy.settings import Settings


def packet(kind, nonce, body):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    prefix = struct.pack("!4sBBH16sI", b"SCOB", 1, kind, 0, nonce, len(body))
    return prefix + struct.pack("!I", zlib.crc32(prefix + body)) + body


def probe():
    boot = "11" * 16
    device = "aabbccddeeff"
    stream = io.BytesIO()
    Image.new("RGB", (16, 12), "blue").save(stream, format="JPEG")
    jpeg = stream.getvalue()
    left, right = socket.socketpair()
    left.settimeout(0.05)
    right.settimeout(5)
    errors = []

    def peer():
        try:
            for command in (1, 3):
                wire = b""
                while len(wire) < 32:
                    part = right.recv(32 - len(wire))
                    if not part:
                        raise ValueError
                    wire += part
                _, _, kind, _, nonce, length, _ = struct.unpack("!4sBBH16sII", wire)
                payload = b""
                while len(payload) < length:
                    payload += right.recv(length - len(payload))
                assert kind == command and wire + payload == packet(kind, nonce, payload)
                if kind == 1:
                    right.sendall(
                        packet(
                            0x81,
                            nonce,
                            {
                                "contract_version": 1,
                                "firmware": "unofficial-observer-prototype",
                                "upstream": "28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400",
                                "read_only": True,
                                "boot_id": boot,
                                "device_id": device,
                                "capabilities": ["status", "snapshot"],
                            },
                        )
                    )
                else:
                    assert payload == bytes.fromhex(boot)
                    right.sendall(
                        packet(
                            0x83,
                            nonce,
                            {
                                "boot_id": boot,
                                "uptime_ms": 1000,
                                "touch": None,
                                "imu": None,
                                "head_pose": None,
                                "pose_verified": False,
                                "image_id": nonce.hex(),
                                "captured_ms": 990,
                                "width": 16,
                                "height": 12,
                                "byte_count": len(jpeg),
                                "sha256": hashlib.sha256(jpeg).hexdigest(),
                            },
                        )
                        + packet(0x84, nonce, jpeg)
                    )
        except Exception as error:
            errors.append(error)
        finally:
            right.close()

    class Link:
        def read(self, n):
            try:
                return left.recv(min(n, 13))
            except socket.timeout:
                return b""

        def write(self, data):
            left.sendall(data)
            return len(data)

        def close(self):
            left.close()

    thread = threading.Thread(target=peer, daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory() as folder:
        profile = Path(folder) / "pair.json"
        save_profile(profile, device)
        with ObserverClient(
            "synthetic-port", profile, transport_factory=lambda p: Link()
        ) as client:
            observation = client.capture()
        thread.join(5)
        assert not errors and not thread.is_alive()

        async def sdk():
            sent = []

            def handler(request):
                sent.append(json.loads(request.content))
                return httpx.Response(
                    200,
                    json={
                        "id": "resp_probe",
                        "object": "response",
                        "created_at": 0,
                        "model": "offline-model",
                        "status": "completed",
                        "output": [
                            {
                                "id": "msg_probe",
                                "type": "message",
                                "role": "assistant",
                                "status": "completed",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": '{"answer":"합성 사진 확인입니다."}',
                                        "annotations": [],
                                    }
                                ],
                            }
                        ],
                    },
                )

            config = Settings(
                _env_file=None,
                cloud_enabled=True,
                image_transmission=True,
                openai_model="offline-model",
                state_path=Path(folder) / "quota.sqlite3",
            )
            api = AsyncOpenAI(
                api_key="synthetic-key",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )
            async with GPTChat(config, client=api) as chat:
                answer = await chat.observe("무엇이 보여?", observation)
                assert answer["answer"] == "합성 사진 확인입니다." and chat._history == []
            assert len(sent) == 1 and sent[0]["store"] is False
            assert "input_image" in str(sent) and boot not in str(sent) and device not in str(sent)

        asyncio.run(sdk())
    print("Installed observer / synthetic serial + image SDK: PASS")


if __name__ == "__main__":
    probe()
