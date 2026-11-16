"""Serve a read-only PC check tool to the official AI; physical control is unavailable."""

import argparse
import asyncio
import getpass
import os
import sys
import warnings

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


def main(argv: list[str] | None = None) -> int:
    parser = _PrivateParser(description=__doc__)
    try:
        try:
            parser.parse_args(argv)
        except SystemExit as stopped:
            return 0 if stopped.code == 0 else 2
        endpoint = validate_endpoint(_endpoint_input())
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
    except Exception:
        _message("OFFICIAL_MCP_CONNECTION_FAILED", error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
