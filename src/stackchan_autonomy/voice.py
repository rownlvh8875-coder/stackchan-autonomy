"""Explicit-trigger voice composition. Real microphone/playback are never opened."""

import asyncio
import math
import struct
from collections import deque
from dataclasses import dataclass

from .audio import PCM16Audio, normalize_pcm, pcm_upload
from .cloud_audio import AudioUnavailable
from .models import ActionResult, Event, EventKind
from .opus_codec import encode_opus


class FakeMicrophone:
    physical = False

    def __init__(self):
        self.calls = 0

    async def record(self, *, duration_ms):
        if type(duration_ms) is not int or not 100 <= duration_ms <= 30000:
            raise ValueError("invalid recording duration")
        self.calls += 1
        return PCM16Audio(
            pcm=b"\0\0" * (16000 * duration_ms // 1000), sample_rate=16000, channels=1
        )


class FakeSpeechService:
    """Fixture ASR and synthetic tone TTS, not real language recognition/speech."""

    def __init__(self, transcript="안녕하세요"):
        self.transcript = transcript
        self.transcriptions = self.syntheses = 0

    async def transcribe(self, audio, *, language="ko"):
        if language != "ko" or not self.transcript.strip() or len(self.transcript) > 500:
            raise AudioUnavailable("invalid simulated transcript")
        self.transcriptions += 1
        return self.transcript

    async def synthesize(self, text):
        if not text.strip() or len(text) > 500:
            raise ValueError("invalid speech")
        self.syntheses += 1
        pcm = b"".join(
            struct.pack("<h", round(2000 * math.sin(2 * math.pi * 440 * i / 24000)))
            for i in range(9600)
        )
        return PCM16Audio(pcm=pcm, sample_rate=24000, channels=1)


@dataclass(frozen=True)
class PlaybackRecord:
    sample_rate: int
    channels: int
    frames: int
    opus_packets: int


class FakePlaybackAdapter:
    physical = False

    def __init__(self, *, opus=False, history_size=100):
        self.opus = opus
        self.calls = 0
        self.history = deque(maxlen=history_size)

    async def play_pcm(self, pcm, *, sample_rate, channels):
        audio = PCM16Audio(pcm=pcm, sample_rate=sample_rate, channels=channels)
        pcm_upload(audio)  # Exercise the actual /pcm payload contract without transport/auth.
        packets = await asyncio.to_thread(encode_opus, audio) if self.opus else None
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError
        self.calls += 1
        self.history.append(
            PlaybackRecord(
                sample_rate, channels, audio.frames, len(packets.frames) if packets else 0
            )
        )


class RecordedVoiceInput:
    def __init__(self, microphone, transcriber):
        if getattr(microphone, "physical", True):
            raise PermissionError("physical recording disabled")
        self.microphone = microphone
        self.transcriber = transcriber

    async def listen(self, *, language, duration_ms):
        if getattr(self.microphone, "physical", True):
            raise PermissionError("physical recording disabled")
        audio = await self.microphone.record(duration_ms=duration_ms)
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError
        text = await self.transcriber.transcribe(audio, language=language)
        return Event(kind=EventKind.VOICE_REQUEST, text=text)


class GatewayVoiceInput:
    """Gateway listen already performs STT; this is not a raw microphone recorder."""

    def __init__(self, adapter):
        self.adapter = adapter

    async def listen(self, *, language, duration_ms):
        if language != "ko":
            raise ValueError("Korean required")
        return await self.adapter.listen(
            duration_ms=duration_ms
        )  # Physical adapter remains blocked.


class SpeakingRobotAdapter:
    def __init__(self, robot, synthesizer, playback):
        if getattr(robot, "physical", True) or getattr(playback, "physical", True):
            raise PermissionError("physical voice playback disabled")
        self.robot = robot
        self.synthesizer = synthesizer
        self.playback = playback

    @property
    def physical(self):
        return self.robot.physical

    async def status(self):
        return await self.robot.status()

    async def capture(self):
        return await self.robot.capture()

    async def execute(self, command):
        if self.physical or getattr(self.playback, "physical", True):
            raise PermissionError("physical voice playback disabled")
        if command.kind == "speak":
            audio = await self.synthesizer.synthesize(command.speech)
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError
            audio = await asyncio.to_thread(normalize_pcm, audio)
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError
            await self.playback.play_pcm(
                audio.pcm, sample_rate=audio.sample_rate, channels=audio.channels
            )
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError
        await self.robot.execute(command)


class VoiceConversation:
    def __init__(self, engine, voice_input, settings):
        self.engine = engine
        self.voice_input = voice_input
        self.settings = settings
        self._lock = asyncio.Lock()

    async def _listen(self):
        record = asyncio.create_task(
            self.voice_input.listen(language="ko", duration_ms=self.settings.voice_capture_ms)
        )
        stop = asyncio.create_task(self.engine.stop_event.wait())
        try:
            await asyncio.wait([record, stop], return_when=asyncio.FIRST_COMPLETED)
            if self.engine.stopped:
                return None
            return record.result()
        finally:
            for task in (record, stop):
                if not task.done():
                    task.cancel()
            await asyncio.gather(record, stop, return_exceptions=True)

    async def handle(self, event):
        if event.priority == 0:
            return await self.engine.step(event)
        if self.engine.stopped:
            return ActionResult(code="stopped")
        if event.kind not in {EventKind.TOUCH_TAP, EventKind.TOUCH_STROKE, EventKind.VOICE_REQUEST}:
            return ActionResult(code="voice_trigger_required")
        if self._lock.locked():
            return ActionResult(code="voice_busy")
        async with self._lock:
            try:
                if not await self.engine.actions.claim_control():
                    return ActionResult(code="lease_busy")
                async with asyncio.timeout(self.settings.operation_timeout_s):
                    request = await self._listen()
                if request is None or self.engine.stopped:
                    return ActionResult(code="stopped")
                if request.kind != EventKind.VOICE_REQUEST or not request.text.strip():
                    raise AudioUnavailable("empty voice request")
                return await self.engine.step(request)
            except asyncio.CancelledError:
                raise
            except Exception:
                return ActionResult(code="voice_unavailable")
