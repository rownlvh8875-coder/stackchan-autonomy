"""No external network: use 127.0.0.1 to verify C++ HTTP body interoperability."""

import http.client
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


class _FixtureHandler(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        count = int(self.headers["Content-Length"])
        assert 0 < count < 400000
        body = self.rfile.read(count)
        media = self.headers.get("Content-Type", "")
        if self.path == "/v1/audio/transcriptions":
            assert media.startswith("multipart/form-data; boundary=K151SpeechBoundary20261119")
            assert body.startswith(b"--K151SpeechBoundary20261119\r\n")
            wav = body[body.index(b"RIFF") :][:4844]
            assert wav[8:12] == b"WAVE"
            assert int.from_bytes(wav[24:28], "little") == 24000
            assert int.from_bytes(wav[40:44], "little") == 4800
            assert body.endswith(b"--K151SpeechBoundary20261119--\r\n")
            answer = json.dumps({"text": "안녕하세요"}).encode()
            reply_media = "application/json"
        else:
            assert media == "application/json"
            data = json.loads(body)
            if self.path == "/v1/responses":
                assert data["store"] is False and data["stream"] is False
                assert data["max_output_tokens"] == 400
                assert "안녕하세요" in data["input"]
                answer = json.dumps({"status": "completed", "output": []}).encode()
                reply_media = "application/json"
            elif self.path == "/v1/audio/speech":
                assert data["response_format"] == "pcm"
                assert data["stream_format"] == "audio"
                answer = b"\x00\x80\xff\x7f"
                reply_media = "application/octet-stream"
            else:
                self.send_error(404)
                return
        self.seen.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", reply_media)
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)

    def log_message(self, _format, *_args):
        pass  # Do not log audio or text requests.


def test_openai_wire_loopback(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ not available")
    root = Path(__file__).resolve().parents[1]
    exe = tmp_path / "wire_fixture"
    subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(root / "core"),
            str(root / "tests" / "http_wire_fixture.cpp"),
            "-o",
            str(exe),
        ],
        check=True,
        timeout=90,
    )
    lines = subprocess.run(
        [str(exe), str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout.splitlines()
    assert int(lines[1]) == (tmp_path / "stt.bin").stat().st_size
    _FixtureHandler.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    runner = threading.Thread(target=server.serve_forever, daemon=True)
    runner.start()
    try:
        for endpoint, file, media in (
            ("/v1/audio/transcriptions", "stt.bin", lines[0]),
            ("/v1/responses", "responses.json", "application/json"),
            ("/v1/audio/speech", "speech.json", "application/json"),
        ):
            client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            client.request(
                "POST", endpoint, body=(tmp_path / file).read_bytes(),
                headers={"Content-Type": media},
            )
            reply = client.getresponse()
            assert reply.status == 200 and reply.read()
            client.close()
        assert _FixtureHandler.seen == [
            "/v1/audio/transcriptions",
            "/v1/responses",
            "/v1/audio/speech",
        ]
    finally:
        server.shutdown()
        server.server_close()
        runner.join(timeout=3)
