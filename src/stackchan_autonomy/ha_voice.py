"""Run a locally admitted Korean Wyoming speech service for Home Assistant."""

import argparse
import asyncio
import logging
import sys
import time
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from functools import partial
from importlib.metadata import version
from types import SimpleNamespace

from .async_storage import AsyncStorage, finish_cleanup
from .budget import SQLiteRequestBudget
from .settings import Settings

STT_MODEL = "gpt-transcribe"
TTS_MODEL = "gpt-realtime-2.1-mini"
OPENAI_URL = "https://api.openai.com/v1"
MAX_QUESTION_SECONDS = 8
MAX_ANSWER_CHARS = 800


class VoiceDenied(Exception):
    pass


class VoiceArgumentParser(argparse.ArgumentParser):
    def error(self, message: str):
        raise VoiceDenied("HA_VOICE_CONFIG_REQUIRED") from None


def validate_config(settings: Settings) -> str:
    key = settings.api_key.get_secret_value() if settings.api_key else ""
    if (
        not settings.cloud_enabled
        or not settings.audio_transmission
        or not settings.state_path.is_absolute()
        or not key
        or len(key) > 8192
        or any(not 33 <= ord(char) <= 126 for char in key)
    ):
        raise VoiceDenied("HA_VOICE_CONFIG_REQUIRED")
    return key


@contextmanager
def private_voice_logs():
    # This command owns its process. Upstream logs include text even at INFO,
    # and exception messages can include a request or transcript.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


class VoiceRequests:
    def __init__(
        self,
        settings: Settings,
        client,
        *,
        emit: Callable[[str], None],
        clock: Callable[[], float] = time.time,
    ):
        validate_config(settings)
        self.client = client
        self.emit = emit
        self.clock = clock
        self.budget = SQLiteRequestBudget(settings)
        self.storage = AsyncStorage()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.storage.aclose()

    def deny(self, code: str):
        self.emit(code)
        raise VoiceDenied(code) from None

    async def reserve(self):
        try:
            admitted = await self.storage.call(self.budget.reserve, self.clock())
        except (OSError, RuntimeError, ValueError):
            self.deny("HA_VOICE_STORAGE_UNAVAILABLE")
        if not admitted:
            self.deny("HA_VOICE_BUDGET_EXHAUSTED")

    async def transcribe(self, *, model, **kwargs):
        if model != STT_MODEL:
            self.deny("HA_VOICE_INPUT_REJECTED")
        await self.reserve()
        try:
            return await self.client.audio.transcriptions.create(model=model, **kwargs)
        except Exception:
            self.deny("HA_VOICE_PROVIDER_FAILED")

    @asynccontextmanager
    async def realtime(self, *, model, websocket_connection_options):
        if model != TTS_MODEL:
            self.deny("HA_VOICE_INPUT_REJECTED")
        await self.reserve()
        try:
            async with self.client.realtime.connect(
                model=model,
                websocket_connection_options={**websocket_connection_options, "proxy": None},
            ) as connection:
                yield connection
        except Exception:
            self.deny("HA_VOICE_PROVIDER_FAILED")


def handler_factory(requests: VoiceRequests):
    from wyoming.error import Error
    from wyoming_openai import OpenAIBackend, OpenAIEventHandler
    from wyoming_openai.compatibility import (
        create_asr_programs,
        create_info,
        create_tts_programs,
        create_tts_voices,
    )

    languages = ["ko-KR"]
    asr = create_asr_programs([STT_MODEL], [], OPENAI_URL, languages)
    voices = create_tts_voices(
        [TTS_MODEL],
        [],
        ["alloy"],
        OPENAI_URL,
        languages,
        openai_realtime_models=[TTS_MODEL],
        official_openai=True,
    )
    info = create_info(asr, create_tts_programs(voices, tts_streaming_models=[]))

    # Expose only the paid entry points used by this profile. No unguarded
    # Speech API, transcription realtime, model lookup, or auto-discovery.
    stt = SimpleNamespace(
        backend=OpenAIBackend.OPENAI,
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=requests.transcribe)),
    )
    tts = SimpleNamespace(realtime=SimpleNamespace(connect=requests.realtime))

    class PrivateHandler(OpenAIEventHandler):
        pcm_bytes = 0
        sample_rate = 0

        async def write_event(self, event):
            if Error.is_type(event.type):
                # The Home Assistant peer must get a failure, even when the
                # provider supplied a message containing private text.
                requests.emit("HA_VOICE_REQUEST_FAILED")
                event = Error(text="HA_VOICE_REQUEST_FAILED").event()
            await super().write_event(event)

        async def handle_event(self, event):
            if not self.accept(event):
                await self.write_event(Error(text="HA_VOICE_INPUT_REJECTED").event())
                return False
            return await super().handle_event(event)

        def accept(self, event) -> bool:
            if event.type == "audio-start":
                rate = event.data.get("rate")
                if (
                    self.sample_rate
                    or type(rate) is not int
                    or not 8_000 <= rate <= 48_000
                    or event.data.get("width") != 2
                    or event.data.get("channels") != 1
                ):
                    return False
                self.sample_rate = rate
                self.pcm_bytes = 0
            elif event.type == "audio-chunk":
                payload = event.payload or b""
                if (
                    not self.sample_rate
                    or not payload
                    or len(payload) % 2
                    or event.data.get("rate") != self.sample_rate
                    or event.data.get("width") != 2
                    or event.data.get("channels") != 1
                ):
                    return False
                self.pcm_bytes += len(payload)
                return self.pcm_bytes <= self.sample_rate * 2 * MAX_QUESTION_SECONDS
            elif event.type == "audio-stop":
                self.sample_rate = 0
            elif event.type == "synthesize":
                text = event.data.get("text")
                return isinstance(text, str) and 0 < len(text) <= MAX_ANSWER_CHARS
            return event.type in {
                "describe",
                "select-program",
                "transcribe",
                "audio-start",
                "audio-stop",
            }

    return partial(
        PrivateHandler,
        info=info,
        stt_client=stt,
        tts_client=tts,
        stt_extra_body={"languages": ["ko"]},
        tts_realtime_models=[TTS_MODEL],
        tts_concurrent_requests=1,
    )


async def serve(settings: Settings, port: int):
    key = validate_config(settings)
    try:
        # The separate review environment uses these inspected upstream APIs.
        if version("wyoming-openai") != "0.9.1" or version("wyoming") != "1.11.0":
            raise VoiceDenied("HA_VOICE_DEPENDENCIES_REQUIRED")
        from openai import AsyncOpenAI, DefaultAsyncHttpxClient
        from wyoming.server import AsyncTcpServer
    except ImportError:
        raise VoiceDenied("HA_VOICE_DEPENDENCIES_REQUIRED") from None

    def emit(code: str):
        print(code, flush=True)

    http = DefaultAsyncHttpxClient(follow_redirects=False, trust_env=False)
    async with AsyncOpenAI(
        api_key=key,
        base_url=OPENAI_URL,
        websocket_base_url="wss://api.openai.com/v1",
        http_client=http,
        max_retries=0,
        timeout=settings.operation_timeout_s,
    ) as client:
        async with VoiceRequests(settings, client, emit=emit) as requests:
            # Verify the persistent store before accepting Wyoming clients.
            try:
                await requests.storage.call(requests.budget.snapshot)
            except (OSError, RuntimeError, ValueError):
                raise VoiceDenied("HA_VOICE_STORAGE_UNAVAILABLE") from None
            factory = handler_factory(requests)
            server = AsyncTcpServer("127.0.0.1", port)
            emit("HA_VOICE_STARTING")
            try:
                await server.run(factory)
            finally:
                await finish_cleanup(asyncio.create_task(server.stop()))


def main(argv: list[str] | None = None) -> int:
    parser = VoiceArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=10300)
    try:
        args = parser.parse_args(argv)
        if not 1 <= args.port <= 65535:
            raise VoiceDenied("HA_VOICE_CONFIG_REQUIRED")
        settings = Settings(_env_file=None)
        validate_config(settings)
    except (VoiceDenied, ValueError, OSError):
        print("HA_VOICE_CONFIG_REQUIRED", file=sys.stderr)
        return 2
    try:
        with private_voice_logs():
            asyncio.run(serve(settings, args.port))
    except KeyboardInterrupt:
        return 130
    except VoiceDenied as denied:
        print(str(denied), file=sys.stderr)
        return 1
    except Exception:
        print("HA_VOICE_SERVICE_FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
