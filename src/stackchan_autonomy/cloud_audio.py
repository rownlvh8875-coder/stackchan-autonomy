"""Consent-gated OpenAI audio, persistent quota, bounded in-memory payloads."""

import asyncio
import time

from openai import AsyncOpenAI

from .audio import PCM16Audio, to_wav
from .budget import SQLiteRequestBudget
from .settings import Settings
from .state_store import StateUnavailable


class AudioUnavailable(RuntimeError):
    pass


class OpenAIAudioService:
    def __init__(self, settings: Settings, *, client: AsyncOpenAI | None = None, clock=time.time):
        self.settings = settings
        self._consent()
        if client is None and (settings.api_key is None or not settings.api_key.get_secret_value()):
            raise ValueError("audio cloud credentials required")
        self.client = (
            client.with_options(max_retries=0)
            if client is not None
            else AsyncOpenAI(
                api_key=settings.api_key.get_secret_value(),
                max_retries=0,
                timeout=settings.operation_timeout_s,
            )
        )
        self.budget = SQLiteRequestBudget(settings)
        self.clock = clock

    def _consent(self):
        if not self.settings.cloud_enabled or not self.settings.audio_transmission:
            raise PermissionError("cloud audio requires explicit consent")

    def _reserve(self, model):
        self._consent()
        if not model:
            raise ValueError("configure the audio model explicitly")
        try:
            if not self.budget.reserve(self.clock()):
                raise AudioUnavailable("shared audio budget exhausted")
        except StateUnavailable:
            raise AudioUnavailable("audio budget storage unavailable") from None

    def _failure(self):
        try:
            self.budget.record_usage(failed=True)
        except StateUnavailable:
            pass

    async def aclose(self):
        await self.client.close()

    async def transcribe(self, audio: PCM16Audio, *, language: str = "ko") -> str:
        if language != "ko":
            raise ValueError("this pipeline requires Korean")
        wav = to_wav(audio)
        self._reserve(self.settings.stt_model)
        try:
            async with asyncio.timeout(self.settings.operation_timeout_s):
                response = await self.client.audio.transcriptions.create(
                    model=self.settings.stt_model,
                    file=("request.wav", wav, "audio/wav"),
                    language="ko",
                    response_format="json",
                    timeout=self.settings.operation_timeout_s,
                )
            if (
                not isinstance(response.text, str)
                or not response.text.strip()
                or len(response.text) > 500
            ):
                raise AudioUnavailable("invalid transcription")
            return response.text
        except asyncio.CancelledError:
            raise
        except Exception:
            self._failure()
            raise AudioUnavailable("audio transcription unavailable") from None

    async def synthesize(self, text: str) -> PCM16Audio:
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            raise ValueError("invalid speech text")
        if not self.settings.tts_voice:
            raise ValueError("configure TTS voice explicitly")
        self._reserve(self.settings.tts_model)
        try:
            async with asyncio.timeout(self.settings.operation_timeout_s):
                async with self.client.audio.speech.with_streaming_response.create(
                    model=self.settings.tts_model,
                    voice=self.settings.tts_voice,
                    input=text,
                    response_format="pcm",
                    timeout=self.settings.operation_timeout_s,
                ) as response:
                    chunks = []
                    size = 0
                    async for chunk in response.iter_bytes(chunk_size=65536):
                        size += len(chunk)
                        if size > 1_440_000:
                            raise AudioUnavailable("TTS duration limit")
                        chunks.append(chunk)
            return PCM16Audio(pcm=b"".join(chunks), sample_rate=24000, channels=1)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._failure()
            raise AudioUnavailable("audio synthesis unavailable") from None
