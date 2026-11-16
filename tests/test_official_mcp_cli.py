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
