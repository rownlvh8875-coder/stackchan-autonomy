"""Serve PC tools to the official AI; --gpt explicitly enables paid OpenAI text replies."""

import argparse
import asyncio
import getpass
import os
import sys
import warnings

from .observer_protocol import ObserverError
from .official_mcp import BridgeError, run_bridge, validate_endpoint
from .official_mcp_runtime import run_reconnecting


class _ArgumentsInvalid(Exception):
    pass


class _InputUnavailable(Exception):
    pass


class _PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error includes unrecognized arguments, possibly a token URL.
        raise _ArgumentsInvalid from None


def _message(code: str, *, error: bool = False):
    try:
        print(code, file=sys.stderr if error else sys.stdout, flush=True)
    except (OSError, ValueError):
        pass


def _endpoint_input() -> str:
    endpoint = os.environ.get("STACKCHAN_OFFICIAL_MCP_ENDPOINT")
    if endpoint:
        return endpoint
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            raise _InputUnavailable
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass("Official MCP endpoint (hidden input): ")
    except (EOFError, OSError, ValueError, getpass.GetPassWarning):
        raise _InputUnavailable from None


def _guidance(code):
    return {
        "PC_GPT_CONFIG_REQUIRED": "로컬 .env의 API 키·모델·cloud=true 설정을 확인하세요. 키 값은 공유하지 마세요.",
        "OFFICIAL_MCP_INVALID_ENDPOINT": "공식 앱에서 MCP 접속주소를 다시 복사한 뒤 실행하세요.",
        "OFFICIAL_MCP_SECRET_INPUT_UNAVAILABLE": "cmd 창에서 직접 실행하고 MCP 주소를 숨김 입력창에 넣어 주세요.",
        "OFFICIAL_MCP_AUTH_FAILED": "MCP 주소가 거부됐습니다. 앱의 현재 주소를 확인한 뒤 다시 실행하세요.",
        "OFFICIAL_MCP_TLS_FAILED": "보안 연결을 확인할 수 없습니다. PC 날짜와 네트워크 설정을 확인하세요.",
        "OFFICIAL_MCP_RATE_LIMITED": "서버의 연결 제한으로 중단했습니다. 제한이 해제된 뒤 다시 실행하세요.",
        "OFFICIAL_MCP_HANDSHAKE_FAILED": "서버가 연결을 허용하지 않았습니다. 앱의 MCP 설정을 확인하세요.",
        "OFFICIAL_MCP_REMOTE_REJECTED": "서버가 연결을 거부했습니다. 앱 설정을 확인한 뒤 다시 실행하세요.",
        "OFFICIAL_MCP_PROTOCOL_FAILED": "연결 규약 오류로 중단했습니다. 프로그램과 앱 버전을 확인하세요.",
        "OFFICIAL_MCP_ARGUMENTS_INVALID": "실행 옵션을 확인하세요. USB 관찰 모드와 --reconnect는 함께 사용할 수 없습니다.",
        "OFFICIAL_MCP_INITIALIZED": "PC 연결이 준비됐습니다.",
        "PC_GPT_BUDGET_EXHAUSTED": "GPT 요청 한도에 도달했습니다. 연결을 다시 해도 한도는 초기화되지 않습니다.",
    }.get(code)


def _reconnect_status(line):
    # The bridge supplies fixed markers only. Output failures must stop recovery.
    print(line, flush=True)
    message = _guidance(line)
    if line.startswith("OFFICIAL_MCP_RECONNECT_WAIT="):
        seconds = int(line.partition("=")[2])
        message = f"연결이 끊어졌습니다. {seconds}초 뒤 다시 연결합니다. 종료는 Ctrl+C입니다."
    if message:
        print(message, flush=True)


def _error(code, *, reconnect=False):
    _message(code, error=True)
    if reconnect and (message := _guidance(code)):
        _message(message, error=True)


async def _gpt_bridge(endpoint, settings, observer_port=None, observer_profile=None, *, emit=None):
    from .gpt_chat import GPTChat
    from .private_logging import private_library_logs

    report = emit if emit is not None else lambda line: print(line, flush=True)
    with private_library_logs():
        async with GPTChat(settings) as gpt:
            if observer_port is None:
                await run_bridge(endpoint, emit=report, gpt=gpt)
            else:
                from .observer_async import AsyncObserver

                async with AsyncObserver(observer_port, observer_profile) as observer:
                    await run_bridge(
                        endpoint,
                        emit=report,
                        gpt=gpt,
                        observer=observer,
                    )


async def _reconnecting_bridge(endpoint, settings=None):
    async def session(emit):
        if settings is None:
            await run_bridge(endpoint, emit=emit)
        else:
            # A new client/context each time; close/drain completes before the next dial.
            await _gpt_bridge(endpoint, settings, emit=emit)

    await run_reconnecting(session, emit=_reconnect_status)


def main(argv: list[str] | None = None) -> int:
    reconnect = False
    parser = _PrivateParser(description=__doc__)
    parser.add_argument(
        "--gpt",
        action="store_true",
        help="Enable paid GPT replies using local .env/environment configuration",
    )
    parser.add_argument(
        "--observer-port", help="Explicit native USB port of paired observer prototype"
    )
    parser.add_argument("--observer-profile", default=".local/observer/profile.json")
    parser.add_argument(
        "--reconnect",
        action="store_true",
        help="Recover temporary MCP disconnections without replaying GPT requests",
    )
    try:
        try:
            args = parser.parse_args(argv)
        except SystemExit as stopped:
            return 0 if stopped.code == 0 else 2
        reconnect = args.reconnect
        if args.observer_port and not args.gpt:
            raise _ArgumentsInvalid
        if args.observer_port and reconnect:
            raise _ArgumentsInvalid
        if args.gpt:
            from .gpt_chat import GPTChatError, validate_gpt_settings
            from .settings import Settings

            try:
                settings = Settings()
                validate_gpt_settings(settings)
                if args.observer_port and not settings.image_transmission:
                    _message("PC_OBSERVER_CONSENT_REQUIRED", error=True)
                    return 2
            except (ValueError, OSError, GPTChatError):
                _error("PC_GPT_CONFIG_REQUIRED", reconnect=reconnect)
                return 2
        endpoint = validate_endpoint(_endpoint_input())
        if reconnect:
            asyncio.run(_reconnecting_bridge(endpoint, settings if args.gpt else None))
        elif args.gpt:
            if args.observer_port:
                asyncio.run(
                    _gpt_bridge(endpoint, settings, args.observer_port, args.observer_profile)
                )
            else:
                asyncio.run(_gpt_bridge(endpoint, settings))
        else:
            asyncio.run(run_bridge(endpoint, emit=lambda line: print(line, flush=True)))
        return 0
    except _ArgumentsInvalid:
        _error("OFFICIAL_MCP_ARGUMENTS_INVALID", reconnect=reconnect)
        return 2
    except _InputUnavailable:
        _error("OFFICIAL_MCP_SECRET_INPUT_UNAVAILABLE", reconnect=reconnect)
        return 2
    except (KeyboardInterrupt, asyncio.CancelledError):
        _message("OFFICIAL_MCP_STOPPED")
        return 130
    except BridgeError as error:
        _error(error.code, reconnect=reconnect)
        return 2 if error.code == "OFFICIAL_MCP_INVALID_ENDPOINT" else 1
    except ObserverError as error:
        _message(error.code, error=True)
        return 1
    except Exception:
        _message("OFFICIAL_MCP_CONNECTION_FAILED", error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
