"""Install the built wheel independently and exercise offline CLI modes on any OS."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


def run(command, *, cwd, env):
    return subprocess.run(
        [str(arg) for arg in command],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    ).stdout


def verify_official_mcp(python, binaries, *, cwd, env):
    cli = binaries / ("stackchan-pc-mcp.exe" if os.name == "nt" else "stackchan-pc-mcp")
    run([cli, "--help"], cwd=cwd, env=env)
    run([cli, "--gpt", "--help"], cwd=cwd, env=env)
    run([cli, "--reconnect", "--help"], cwd=cwd, env=env)
    probe = textwrap.dedent("""
        import asyncio, hashlib, json
        from contextlib import asynccontextmanager, suppress
        from importlib.resources import files
        import httpx2 as httpx
        from openai import AsyncOpenAI
        from websockets.asyncio.client import connect
        from websockets.asyncio.server import serve
        import stackchan_autonomy.official_mcp as bridge
        from stackchan_autonomy.gpt_chat import GPTChat
        from stackchan_autonomy.settings import Settings

        async def main(gpt=None):
            reply = asyncio.get_running_loop().create_future()
            release = asyncio.Event()
            lines = []

            async def peer(socket):
                async def rpc(request_id, method, params):
                    await socket.send(json.dumps({"jsonrpc":"2.0", "id":request_id,
                                                  "method":method, "params":params}))
                    return json.loads(await socket.recv())
                try:
                    await rpc(1, "initialize", {"protocolVersion":"2024-11-05", "capabilities":{},
                                               "clientInfo":{"name":"wheel-probe", "version":"1"}})
                    await socket.send(json.dumps({"jsonrpc":"2.0", "method":"notifications/initialized"}))
                    listing = await rpc(2, "tools/list", {})
                    expected = ["stackchan_pc_connection_status", "stackchan_pc_soak_report_summary"]
                    if gpt is not None: expected.append("stackchan_gpt_reply")
                    assert [t["name"] for t in listing["result"]["tools"]] == expected
                    called = await rpc(3, "tools/call", {"name":"stackchan_pc_connection_status", "arguments":{}})
                    summary = await rpc(4, "tools/call", {"name":"stackchan_pc_soak_report_summary", "arguments":{}})
                    answer = None
                    if gpt is not None:
                        answer = await rpc(5, "tools/call", {"name":"stackchan_gpt_reply",
                                           "arguments":{"question":"설치 확인"}})
                    reply.set_result((called["result"]["structuredContent"],
                                      summary["result"]["structuredContent"], answer))
                    await release.wait()
                except Exception as error:
                    if not reply.done(): reply.set_exception(error)

            async with serve(peer, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                @asynccontextmanager
                async def local_only(uri, **kwargs):
                    assert uri == "wss://api.xiaozhi.me/mcp/?token=offline-wheel-check"
                    async with connect(f"ws://127.0.0.1:{port}", proxy=None, **kwargs) as socket:
                        yield socket
                bridge.connect = local_only
                task = asyncio.create_task(bridge.run_bridge(
                    "wss://api.xiaozhi.me/mcp/?token=offline-wheel-check", emit=lines.append, gpt=gpt))
                try:
                    result, summary, answer = await asyncio.wait_for(reply, 10)
                    assert result["call_count"] == 1 and result["robot_control_available"] is False
                    assert len(result["check_code"]) == 6
                    assert any(result["check_code"] in line for line in lines)
                    assert "PC_SOAK_REPORT_CALLED=1" in lines
                    assert summary["passed"] is True and summary["cycles"] == 83157
                    assert summary["wall_elapsed_s"] == 86400.047
                    assert summary["requested_duration_s"] == 86400.0
                    assert summary["restarts"] == summary["restoration_checks"] == 332
                    assert summary["python_traced_growth_bytes"] == 20697
                    assert summary["recorded_date"] == "2026-11-15"
                    assert summary["recorded_date_basis"] == "report_received"
                    assert summary["historical"] is True
                    assert summary["test_scope"] == "pc_fake_mock"
                    assert summary["time_mode"] == "wall_clock"
                    assert summary["robot_hardware_tested"] is False
                    if gpt is not None:
                        result = answer["result"]["structuredContent"]
                        assert result["answer"] == "설치된 GPT 경로 확인입니다."
                        assert result["provider"] == "openai_responses"
                        assert "PC_GPT_READY" in lines and "PC_GPT_CALLED=1" in lines
                        assert "PC_GPT_ANSWERED=1" in lines
                    else:
                        assert not any(line.startswith("PC_GPT_") for line in lines)
                finally:
                    task.cancel()
                    with suppress(asyncio.CancelledError, bridge.BridgeError): await task
                    release.set()
            raw = files("stackchan_autonomy").joinpath(
                "data", "windows-home-soak-24h-passed.json").read_bytes()
            return hashlib.sha256(raw).hexdigest()

        async def verify():
            digest = await main()
            sent = []
            def api(request):
                sent.append(json.loads(request.content))
                return httpx.Response(200, json={
                    "id":"resp_wheel", "object":"response", "created_at":0,
                    "model":"offline-wheel-model", "status":"completed",
                    "output":[{"id":"msg_wheel", "type":"message", "role":"assistant",
                               "status":"completed", "content":[{"type":"output_text",
                               "text":json.dumps({"answer":"설치된 GPT 경로 확인입니다."}),
                               "annotations":[]}]}],
                    "usage":{"input_tokens":4, "output_tokens":5, "total_tokens":9}})
            config = Settings(_env_file=None, cloud_enabled=True,
                              openai_model="offline-wheel-model")
            client = AsyncOpenAI(api_key="offline-wheel-key", max_retries=0,
                base_url="https://api.openai.com/v1",
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(api)))
            async with GPTChat(config, client=client) as chat:
                assert await main(chat) == digest
            assert len(sent) == 1 and sent[0]["store"] is False
            assert sent[0]["model"] == "offline-wheel-model"
            assert sent[0]["input"] == [{"role":"user", "content":"설치 확인"}]
            print(json.dumps({"official_mcp":True, "call_count":1,
                              "robot_control_available":False, "soak_summary":True,
                              "gpt_reply":True, "report_sha256":digest}))

        asyncio.run(verify())
    """)
    result = json.loads(run([python, "-I", "-c", probe], cwd=cwd, env=env))
    original = (
        Path(__file__).resolve().parents[1]
        / "docs/validation/2026-11-15-windows-home-soak-24h-passed.json"
    )
    if result != {
        "official_mcp": True,
        "call_count": 1,
        "robot_control_available": False,
        "soak_summary": True,
        "gpt_reply": True,
        "report_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
    }:
        raise RuntimeError("installed official MCP diagnostic failed its offline contract")
    print("Installed PC MCP CLI / connection + report + local SDK GPT reply: PASS", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, default=Path(".local/ci/dist"))
    parser.add_argument("--require-opus", action="store_true")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    wheels = list((project / args.wheel_dir).glob("stackchan_autonomy-*.whl"))
    if len(wheels) != 1:
        parser.error("build exactly one project wheel in --wheel-dir first")
    uv = shutil.which("uv")
    if uv is None:
        parser.error("uv is required")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("STACKCHAN_")
        and key
        not in {
            "OPENAI_API_KEY",
            "PYTHONPATH",
            "PYTHONHOME",
            "VIRTUAL_ENV",
            "UV_PROJECT",
            "UV_PROJECT_ENVIRONMENT",
        }
    }
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    with tempfile.TemporaryDirectory(prefix="stackchan wheel ") as directory:
        root = Path(directory)
        requirements = root / "requirements.txt"
        run(
            [
                uv,
                "export",
                "--frozen",
                "--no-dev",
                "--no-emit-project",
                "--output-file",
                requirements,
            ],
            cwd=project,
            env=env,
        )
        venv = root / "venv"
        run([uv, "venv", "--python", sys.executable, venv], cwd=root, env=env)
        binaries = venv / ("Scripts" if os.name == "nt" else "bin")
        python = binaries / ("python.exe" if os.name == "nt" else "python")
        cli = binaries / ("stackchan-autonomy.exe" if os.name == "nt" else "stackchan-autonomy")
        run(
            [uv, "pip", "install", "--python", python, "--require-hashes", "-r", requirements],
            cwd=root,
            env=env,
        )
        run(
            [uv, "pip", "install", "--python", python, "--no-deps", wheels[0].resolve()],
            cwd=root,
            env=env,
        )
        probe = run(
            [
                python,
                "-I",
                "-c",
                "import json,sys; from pathlib import Path; import stackchan_autonomy as m; "
                "from stackchan_autonomy.opus_codec import opus_available; "
                "assert Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()); "
                "print(json.dumps({'opus': opus_available()}))",
            ],
            cwd=root,
            env=env,
        )
        opus = json.loads(probe)["opus"]
        if args.require_opus and not opus:
            raise RuntimeError("required native libopus is unavailable in the installed wheel")
        modes = [("mock", False), ("mcp-sim", False), ("voice-sim", False)]
        if opus:
            modes.append(("voice-sim", True))
        else:
            print("SKIP native Opus smoke: trusted system libopus unavailable", flush=True)
        for index, (mode, use_opus) in enumerate(modes):
            child_env = env | {
                "STACKCHAN_STATE_PATH": str(root / f"state-{index}.sqlite3"),
                "STACKCHAN_CLOUD_ENABLED": "false",
                "STACKCHAN_AUDIO_TRANSMISSION": "false",
                "STACKCHAN_IMAGE_TRANSMISSION": "false",
                "STACKCHAN_HARDWARE_ENABLED": "false",
                "STACKCHAN_DRY_RUN": "true",
            }
            command = [cli, "--mode", mode, "--cycles", "1", "--event", "touch"]
            if use_opus:
                command.append("--opus")
            summary = json.loads(run(command, cwd=root, env=child_env))
            expected = {
                "mode": mode,
                "cycles": 1,
                "state": "IDLE",
                "simulated_actions": 1,
                "cloud_requests": 0,
            }
            if mode == "voice-sim":
                expected.update(audio_captures=1, audio_playbacks=1)
            if any(summary.get(key) != value for key, value in expected.items()):
                raise RuntimeError(f"installed {mode} CLI failed its offline smoke contract")
            if mode == "voice-sim" and bool(summary.get("opus_packets")) != use_opus:
                raise RuntimeError("installed voice CLI did not exercise the requested codec")
            print(json.dumps(summary), flush=True)
        memory_cli = binaries / ("stackchan-memory.exe" if os.name == "nt" else "stackchan-memory")
        memory_env = child_env | {
            "STACKCHAN_MEMORY_PATH": str(root / "memory.sqlite3"),
            "STACKCHAN_STATE_PATH": str(root / "memory-control.sqlite3"),
        }
        configured = json.loads(
            run(
                [
                    memory_cli,
                    "set",
                    "--automatic-speech",
                    "off",
                    "--minimum-speech-interval",
                    "600",
                ],
                cwd=root,
                env=memory_env,
            )
        )
        if configured["preferences"] != {
            "automatic_speech_enabled": False,
            "minimum_speech_interval_s": 600,
        }:
            raise RuntimeError("installed memory CLI did not persist preferences")

        def autonomy(*flags):
            return json.loads(run([cli, "--cycles", "1", *flags], cwd=root, env=memory_env))

        blocked = autonomy("--person")
        if blocked["simulated_actions"] != 0 or blocked["cloud_requests"] != 0:
            raise RuntimeError("installed engine ignored automatic speech preference")
        touched = autonomy("--event", "touch")
        if touched["simulated_actions"] != 1 or touched["cloud_requests"] != 0:
            raise RuntimeError("installed engine lost explicit interaction capability")
        run([memory_cli, "set", "--automatic-speech", "on"], cwd=root, env=memory_env)
        restarted = autonomy("--person")
        retained = json.loads(run([memory_cli, "show"], cwd=root, env=memory_env))
        if (
            restarted["simulated_actions"] != 0
            or restarted["cloud_requests"] != 0
            or retained["recent"][-1]["result"] != "speech_cooldown"
        ):
            raise RuntimeError("installed engine lost speech cooldown across process restart")
        cleared = json.loads(run([memory_cli, "clear"], cwd=root, env=memory_env))
        if cleared["recent"] or cleared["last_spoken_at"] is not None:
            raise RuntimeError("installed memory CLI did not clear scoped metadata")
        print("Optional memory CLI / persisted preferences / restart cooldown: PASS", flush=True)
        soak_cli = binaries / ("stackchan-soak.exe" if os.name == "nt" else "stackchan-soak")
        soak = json.loads(
            run(
                [
                    soak_cli,
                    "--cycles",
                    "30",
                    "--warmup-cycles",
                    "5",
                    "--restart-every",
                    "10",
                    "--virtual-step-s",
                    "30",
                ],
                cwd=root,
                env=env,
            )
        )
        if (
            not soak["passed"]
            or soak["cycles"] != 30
            or soak["virtual_elapsed_s"] != 900
            or soak["restarts"] != 2
            or soak["remaining_tasks"] != 0
            or soak["cloud_requests"] != 0
        ):
            raise RuntimeError("installed soak entry point failed the bounded offline contract")
        print("Isolated installed soak entry point / restart checks: PASS", flush=True)
        verify_official_mcp(python, binaries, cwd=root, env=env)
        print(
            run(
                [python, "-I", project / "scripts/reconnect_wheel_probe.py"], cwd=root, env=env
            ).strip(),
            flush=True,
        )
        observer_cli = binaries / (
            "stackchan-observe.exe" if os.name == "nt" else "stackchan-observe"
        )
        run([observer_cli, "--help"], cwd=root, env=env)
        # -I and a temporary cwd ensure the built package supplies every runtime module.
        print(
            run(
                [python, "-I", project / "scripts/observer_wheel_probe.py"], cwd=root, env=env
            ).strip(),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(error.stdout, file=sys.stderr)
        print(error.stderr, file=sys.stderr)
        raise SystemExit(error.returncode) from None
