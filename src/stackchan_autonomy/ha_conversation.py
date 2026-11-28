"""Serve protected GPT answers to the Home Assistant conversation entity on loopback."""

import asyncio
import json
import sys

from openai import AsyncOpenAI, DefaultAsyncHttpxClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from uvicorn import Config, Server

from .gpt_chat import GPTChat, GPTChatError, validate_gpt_settings
from .ha_voice import OPENAI_URL, VoiceArgumentParser, VoiceDenied, private_voice_logs
from .ha_voice import validate_config as validate_voice_config
from .settings import Settings

PORT = 10301
MAX_BODY_BYTES = 16_384
ERRORS = {
    "PC_GPT_INVALID_QUESTION": (400, "invalid_input"),
    "PC_GPT_BUDGET_EXHAUSTED": (429, "budget_exhausted"),
    "PC_GPT_STORAGE_UNAVAILABLE": (503, "storage_unavailable"),
}


def validate_config(settings: Settings) -> str:
    try:
        key = validate_voice_config(settings)
        validate_gpt_settings(settings, require_key=False)
        if (
            min(settings.requests_per_minute, settings.requests_per_hour, settings.requests_per_day)
            < 3
        ):
            raise VoiceDenied("HA_GPT_CONFIG_REQUIRED")
    except (VoiceDenied, GPTChatError):
        raise VoiceDenied("HA_GPT_CONFIG_REQUIRED") from None
    return key


def error(status: int, code: str):
    return JSONResponse({"error": code}, status_code=status)


async def answer_while_connected(request: Request, chat: GPTChat, text):
    answering = asyncio.create_task(chat.ask(text, remember=False))
    # The request body is already consumed, so the next ASGI event is disconnect.
    disconnected = asyncio.create_task(request.receive())
    try:
        await asyncio.wait({answering, disconnected}, return_when=asyncio.FIRST_COMPLETED)
        if not disconnected.done():
            return answering.result()
    finally:
        answering.cancel()
        disconnected.cancel()
        await asyncio.gather(answering, disconnected, return_exceptions=True)


def create_app(chat: GPTChat):
    async def answer(request: Request):
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if "origin" in request.headers or media_type != "application/json":
            return error(400, "invalid_input")
        body = bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        return error(413, "invalid_input")
                    body.extend(chunk)
            payload = json.loads(body)
        except (ValueError, RecursionError, ClientDisconnect, TimeoutError):
            return error(400, "invalid_input")
        if not isinstance(payload, dict) or set(payload) != {"text"}:
            return error(400, "invalid_input")
        try:
            result = await answer_while_connected(request, chat, payload["text"])
        except GPTChatError as exc:
            return error(*ERRORS.get(exc.code, (502, "unavailable")))
        if result is None:
            return error(499, "client_disconnected")
        return JSONResponse({"answer": result["answer"]}, headers={"Cache-Control": "no-store"})

    return Starlette(
        routes=[Route("/answer", answer, methods=["POST"])],
        middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])],
    )


async def serve(settings: Settings):
    key = validate_config(settings)
    client = AsyncOpenAI(
        api_key=key,
        base_url=OPENAI_URL,
        max_retries=0,
        timeout=settings.operation_timeout_s,
        http_client=DefaultAsyncHttpxClient(follow_redirects=False, trust_env=False),
    )
    async with GPTChat(settings, client=client) as chat:
        # Check durable storage before accepting Home Assistant requests.
        await asyncio.to_thread(chat.budget.snapshot)
        server = Server(
            Config(
                create_app(chat),
                host="127.0.0.1",
                port=PORT,
                access_log=False,
                log_config=None,
                proxy_headers=False,
                ws="none",
                limit_concurrency=16,
                timeout_graceful_shutdown=5,
            )
        )
        print("HA_GPT_STARTING", flush=True)
        await server.serve()


def main(argv: list[str] | None = None) -> int:
    parser = VoiceArgumentParser(description=__doc__)
    try:
        parser.parse_args(argv)
        settings = Settings(_env_file=None)
        validate_config(settings)
    except (VoiceDenied, ValueError, OSError):
        print("HA_GPT_CONFIG_REQUIRED", file=sys.stderr)
        return 2
    try:
        with private_voice_logs():
            asyncio.run(serve(settings))
    except KeyboardInterrupt:
        return 130
    except (Exception, SystemExit):
        print("HA_GPT_SERVICE_FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
