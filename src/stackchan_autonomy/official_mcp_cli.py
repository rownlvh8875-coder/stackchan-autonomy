"""Serve PC tools to the official AI; --gpt explicitly enables paid OpenAI text replies."""

import argparse
import asyncio
import getpass
import os
import sys
import warnings

from .observer_protocol import ObserverError
from .official_mcp import BridgeError, run_bridge, validate_endpoint


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


async def _gpt_bridge(endpoint, settings, observer_port=None, observer_profile=None):
    from .gpt_chat import GPTChat
    from .private_logging import private_library_logs

    with private_library_logs():
        async with GPTChat(settings) as gpt:
            if observer_port is None:
                await run_bridge(endpoint, emit=lambda line: print(line, flush=True), gpt=gpt)
            else:
                from .observer_async import AsyncObserver

                async with AsyncObserver(observer_port, observer_profile) as observer:
                    await run_bridge(
                        endpoint,
                        emit=lambda line: print(line, flush=True),
                        gpt=gpt,
                        observer=observer,
                    )


def main(argv: list[str] | None = None) -> int:
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
    try:
        try:
            args = parser.parse_args(argv)
        except SystemExit as stopped:
            return 0 if stopped.code == 0 else 2
        if args.observer_port and not args.gpt:
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
                _message("PC_GPT_CONFIG_REQUIRED", error=True)
                return 2
        endpoint = validate_endpoint(_endpoint_input())
        if args.gpt:
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
        _message("OFFICIAL_MCP_ARGUMENTS_INVALID", error=True)
        return 2
    except _InputUnavailable:
        _message("OFFICIAL_MCP_SECRET_INPUT_UNAVAILABLE", error=True)
        return 2
    except (KeyboardInterrupt, asyncio.CancelledError):
        _message("OFFICIAL_MCP_STOPPED")
        return 130
    except BridgeError as error:
        _message(error.code, error=True)
        return 2 if error.code == "OFFICIAL_MCP_INVALID_ENDPOINT" else 1
    except ObserverError as error:
        _message(error.code, error=True)
        return 1
    except Exception:
        _message("OFFICIAL_MCP_CONNECTION_FAILED", error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
