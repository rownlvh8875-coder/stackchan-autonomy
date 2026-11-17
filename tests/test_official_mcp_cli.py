"""Secret input and exit behavior of the operator-facing standalone command."""

import importlib
import io
import os
import subprocess
import sys
import warnings

import pytest

ENDPOINT = "wss://api.xiaozhi.me/mcp/?token=synthetic-cli-secret"


def cli_module():
    return importlib.import_module("stackchan_autonomy.official_mcp_cli")


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


class ConsoleInput(io.StringIO):
    def isatty(self):
        return True


def test_help_does_not_request_secret_or_start_a_connection(monkeypatch, capsys):
    module = cli_module()
    monkeypatch.delenv("STACKCHAN_OFFICIAL_MCP_ENDPOINT", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert module.main(["--help"]) == 0
    assert "--help" in output(capsys)


def test_unknown_arguments_cannot_echo_a_pasted_endpoint(monkeypatch, capsys):
    module = cli_module()
    monkeypatch.delenv("STACKCHAN_OFFICIAL_MCP_ENDPOINT", raising=False)
    assert module.main([ENDPOINT]) == 2
    observed = output(capsys)
    assert "synthetic-cli-secret" not in observed
    assert "api.xiaozhi.me" not in observed
    assert "Traceback" not in observed


def test_noninteractive_input_fails_without_echo_fallback(monkeypatch, capsys):
    module = cli_module()
    monkeypatch.delenv("STACKCHAN_OFFICIAL_MCP_ENDPOINT", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(ENDPOINT))

    def forbidden_prompt(*args, **kwargs):
        raise AssertionError("getpass must not fall back to reading a pipe")

    monkeypatch.setattr(module.getpass, "getpass", forbidden_prompt)
    assert module.main([]) == 2
    assert "synthetic-cli-secret" not in output(capsys)


def test_interactive_secret_is_forwarded_without_being_printed(monkeypatch, capsys):
    module = cli_module()
    monkeypatch.delenv("STACKCHAN_OFFICIAL_MCP_ENDPOINT", raising=False)
    monkeypatch.setattr(sys, "stdin", ConsoleInput())
    monkeypatch.setattr(module.getpass, "getpass", lambda prompt: ENDPOINT)

    async def connected(endpoint, *, emit):
        assert endpoint == ENDPOINT
        emit("OFFICIAL_MCP_CONNECTED")
        emit("PC_CHECK_CODE=123456")

    monkeypatch.setattr(module, "run_bridge", connected)
    assert module.main([]) == 0
    observed = output(capsys)
    assert "123456" in observed
    assert "synthetic-cli-secret" not in observed


@pytest.mark.parametrize("failure", ["eof", "warning"])
def test_hidden_input_failure_never_degrades_to_secret_echo(monkeypatch, capsys, failure):
    module = cli_module()
    monkeypatch.delenv("STACKCHAN_OFFICIAL_MCP_ENDPOINT", raising=False)
    monkeypatch.setattr(sys, "stdin", ConsoleInput())

    def unavailable(prompt):
        if failure == "eof":
            raise EOFError("synthetic-cli-secret")
        warnings.warn("synthetic-cli-secret", module.getpass.GetPassWarning)
        return ENDPOINT

    monkeypatch.setattr(module.getpass, "getpass", unavailable)
    assert module.main([]) == 2
    assert "synthetic-cli-secret" not in output(capsys)


def test_invalid_environment_value_fails_before_external_dial(monkeypatch, capsys):
    module = cli_module()
    core = importlib.import_module("stackchan_autonomy.official_mcp")
    monkeypatch.setenv("STACKCHAN_OFFICIAL_MCP_ENDPOINT", ENDPOINT.replace("wss:", "ws:"))

    def forbidden_dial(*args, **kwargs):
        raise AssertionError("invalid endpoint reached network boundary")

    monkeypatch.setattr(core, "connect", forbidden_dial)
    assert module.main([]) == 2
    assert "synthetic-cli-secret" not in output(capsys)


def test_app_dotenv_cannot_supply_a_bridge_endpoint(monkeypatch, capsys, tmp_path):
    module = cli_module()
    (tmp_path / ".env").write_text("STACKCHAN_OFFICIAL_MCP_ENDPOINT=" + ENDPOINT)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STACKCHAN_OFFICIAL_MCP_ENDPOINT", raising=False)
    monkeypatch.setenv("STACKCHAN_CLOUD_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unused-key")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert module.main([]) == 2
    observed = output(capsys)
    assert "synthetic-cli-secret" not in observed
    assert "synthetic-unused-key" not in observed


@pytest.mark.parametrize("kind", ["network", "interrupt"])
def test_failure_exit_is_fixed_and_contains_no_traceback(monkeypatch, capsys, kind):
    module = cli_module()
    monkeypatch.setenv("STACKCHAN_OFFICIAL_MCP_ENDPOINT", ENDPOINT)

    async def failure(endpoint, *, emit):
        if kind == "interrupt":
            raise KeyboardInterrupt
        raise RuntimeError("private failure at " + endpoint)

    monkeypatch.setattr(module, "run_bridge", failure)
    assert module.main([]) == (130 if kind == "interrupt" else 1)
    observed = output(capsys)
    assert "synthetic-cli-secret" not in observed
    assert "private failure" not in observed
    assert "Traceback" not in observed


def test_actual_module_rejects_secret_argv_without_argparse_echo():
    cli_module()
    environment = os.environ.copy()
    environment.pop("STACKCHAN_OFFICIAL_MCP_ENDPOINT", None)
    result = subprocess.run(
        [sys.executable, "-m", "stackchan_autonomy.official_mcp_cli", ENDPOINT],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "synthetic-cli-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize("missing", ["cloud", "model", "key", "invalid"])
def test_gpt_requires_local_configuration_before_prompt_or_dial(
    monkeypatch, tmp_path, capsys, missing
):
    module = cli_module()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STACKCHAN_CLOUD_ENABLED", "true" if missing != "cloud" else "false")
    monkeypatch.setenv(
        "STACKCHAN_OPENAI_MODEL",
        "account-selected-model" if missing != "invalid" else "bad\nsynthetic-private-key",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-key")
    if missing == "model":
        monkeypatch.delenv("STACKCHAN_OPENAI_MODEL")
    if missing == "key":
        monkeypatch.delenv("OPENAI_API_KEY")

    def forbidden(*args, **kwargs):
        raise AssertionError("unconfigured GPT reached hidden prompt")

    monkeypatch.setattr(module.getpass, "getpass", forbidden)
    assert module.main(["--gpt"]) == 2
    observed = output(capsys)
    assert "PC_GPT_CONFIG_REQUIRED" in observed
    assert "synthetic-private-key" not in observed


def test_gpt_reads_private_dotenv_and_closes_real_client_without_startup_api_call(
    monkeypatch, tmp_path, capsys
):
    module = cli_module()
    monkeypatch.chdir(tmp_path)
    for name in ["STACKCHAN_CLOUD_ENABLED", "STACKCHAN_OPENAI_MODEL", "OPENAI_API_KEY"]:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "STACKCHAN_CLOUD_ENABLED=true\nSTACKCHAN_OPENAI_MODEL=account-selected-model\nOPENAI_API_KEY=synthetic-private-key\n"
    )
    monkeypatch.setenv("STACKCHAN_OFFICIAL_MCP_ENDPOINT", ENDPOINT)
    seen = []

    async def connected(endpoint, *, emit, gpt):
        assert endpoint == ENDPOINT
        assert gpt.settings.openai_model == "account-selected-model"
        assert gpt.settings.api_key.get_secret_value() == "synthetic-private-key"
        seen.append(gpt)
        emit("PC_GPT_READY")

    monkeypatch.setattr(module, "run_bridge", connected)
    assert module.main(["--gpt"]) == 0
    assert len(seen) == 1 and seen[0].client.is_closed()
    assert seen[0].budget.snapshot().requests == 0
    observed = output(capsys)
    assert "PC_GPT_READY" in observed and "synthetic-private-key" not in observed


def test_gpt_help_never_loads_local_configuration_or_requests_secrets(
    monkeypatch, tmp_path, capsys
):
    module = cli_module()
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=synthetic-private-key\n")
    assert module.main(["--gpt", "--help"]) == 0
    observed = output(capsys)
    assert "--gpt" in observed and "synthetic-private-key" not in observed


def test_reconnect_keeps_endpoint_private_prompts_once_and_closes_each_gpt_client(
    monkeypatch, tmp_path, capsys
):
    from stackchan_autonomy.official_mcp_runtime import run_reconnecting

    module = cli_module()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STACKCHAN_OFFICIAL_MCP_ENDPOINT", raising=False)
    monkeypatch.setenv("STACKCHAN_CLOUD_ENABLED", "true")
    monkeypatch.setenv("STACKCHAN_OPENAI_MODEL", "offline-model")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-key")
    monkeypatch.setattr(sys, "stdin", ConsoleInput())
    prompts, clients = [], []

    def prompt(label):
        prompts.append(label)
        return ENDPOINT

    monkeypatch.setattr(module.getpass, "getpass", prompt)

    async def session(endpoint, *, emit, gpt):
        assert endpoint == ENDPOINT
        if clients:
            assert clients[-1].client.is_closed()
        clients.append(gpt)
        emit("OFFICIAL_MCP_INITIALIZED")
        if len(clients) == 1:
            raise module.BridgeError("OFFICIAL_MCP_REMOTE_CLOSED", retryable=True)

    async def sleep(seconds):
        assert seconds == 2 and clients[-1].client.is_closed()

    async def supervise(session, *, emit):
        await run_reconnecting(session, emit=emit, sleep=sleep)

    monkeypatch.setattr(module, "run_bridge", session)
    monkeypatch.setattr(module, "run_reconnecting", supervise, raising=False)
    assert module.main(["--gpt", "--reconnect"]) == 0
    assert len(prompts) == 1 and len(clients) == 2
    assert all(client.client.is_closed() for client in clients)
    observed = output(capsys)
    assert "OFFICIAL_MCP_RECONNECT_WAIT=2" in observed
    assert "synthetic-private-key" not in observed and "synthetic-cli-secret" not in observed


def test_reconnect_bad_configuration_stops_before_secret_prompt(monkeypatch, tmp_path, capsys):
    module = cli_module()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STACKCHAN_CLOUD_ENABLED", "false")
    monkeypatch.setattr(module, "_endpoint_input", lambda: pytest.fail("prompt reached"))
    assert module.main(["--gpt", "--reconnect"]) == 2
    assert "PC_GPT_CONFIG_REQUIRED" in output(capsys)


def test_reconnect_rejects_usb_observer_before_open_or_secret_prompt(monkeypatch, capsys):
    module = cli_module()
    monkeypatch.setattr(module, "_endpoint_input", lambda: pytest.fail("prompt reached"))
    assert module.main(["--gpt", "--reconnect", "--observer-port", "private-port"]) == 2
    observed = output(capsys)
    assert "OFFICIAL_MCP_ARGUMENTS_INVALID" in observed and "private-port" not in observed


def test_empty_observer_port_is_rejected_before_input_in_reconnect_mode(
    monkeypatch, tmp_path, capsys
):
    module = cli_module()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STACKCHAN_CLOUD_ENABLED", "true")
    monkeypatch.setenv("STACKCHAN_OPENAI_MODEL", "offline-model")
    monkeypatch.setenv("OPENAI_API_KEY", "private-key")
    monkeypatch.setattr(
        module, "_endpoint_input", lambda: pytest.fail("invalid mode reached secret input")
    )
    assert module.main(["--gpt", "--reconnect", "--observer-port", ""]) == 2
    assert "OFFICIAL_MCP_ARGUMENTS_INVALID" in output(capsys)


@pytest.mark.skipif(os.name != "nt", reason="Windows CMD launcher integration")
@pytest.mark.parametrize("prepared", [False, True])
def test_windows_launcher_from_other_directory_keeps_configuration_failure_visible(
    tmp_path, prepared
):
    import shutil
    import sysconfig
    import venv
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    project = tmp_path / "프로젝트 with spaces"
    project.mkdir()
    for name in ("README.md", "pyproject.toml", "uv.lock"):
        shutil.copy2(root / name, project / name)
    shutil.copytree(root / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (project / "scripts").mkdir()
    launcher = project / "scripts/start-gpt.cmd"
    shutil.copy2(root / "scripts/start-gpt.cmd", launcher)
    blocked = tmp_path / "deny-network"
    blocked.mkdir()
    marker = tmp_path / "unexpected-network"
    (blocked / "sitecustomize.py").write_text(
        "import os,socket\nfrom pathlib import Path\n"
        "def deny(*a,**kw):\n Path(os.environ['STACKCHAN_TEST_NETWORK_MARKER']).write_text('blocked')\n raise AssertionError('network-disabled')\n"
        "socket.socket.connect=deny\nsocket.socket.connect_ex=deny\nsocket.getaddrinfo=deny\n"
    )
    if prepared:
        venv.EnvBuilder(with_pip=False).create(project / ".venv")
    environment = os.environ.copy()
    environment.pop("UV_PROJECT_ENVIRONMENT", None)
    environment.update(
        STACKCHAN_CLOUD_ENABLED="false",
        OPENAI_API_KEY="private-launcher-key",
        STACKCHAN_OFFICIAL_MCP_ENDPOINT=ENDPOINT,
        STACKCHAN_TEST_NETWORK_MARKER=str(marker),
        UV_OFFLINE="true",
        UV_PYTHON_DOWNLOADS="never",
        UV_CACHE_DIR=str(tmp_path / "cold-cache"),
        PYTHONPATH=os.pathsep.join(
            [str(blocked), str(project / "src"), sysconfig.get_path("purelib")]
        ),
    )
    if prepared:
        # Prove the fixture is ready before the launcher hides import diagnostics.
        probe = subprocess.run(
            [
                str(project / ".venv/Scripts/python.exe"),
                "-c",
                "import stackchan_autonomy.official_mcp_cli",
            ],
            cwd=project,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert probe.returncode == 0, probe.stdout + probe.stderr
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(launcher)],
        cwd=tmp_path,
        env=environment,
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    assert result.returncode == 2
    code = "PC_GPT_CONFIG_REQUIRED" if prepared else "PC_PYTHON_ENV_REQUIRED"
    assert code in result.stdout + result.stderr
    assert "private-launcher-key" not in result.stdout + result.stderr
    assert "synthetic-cli-secret" not in result.stdout + result.stderr
    assert not marker.exists() and not (tmp_path / "cold-cache").exists()
