from typing import Protocol

from .audio import PCM16Audio
from .models import Decision, DecisionContext, Event, Observation, RobotCommand, RobotStatus


class RobotAdapter(Protocol):
    async def status(self) -> RobotStatus: ...
    async def capture(self) -> Observation: ...
    async def execute(self, command: RobotCommand) -> None: ...


class DecisionProvider(Protocol):
    async def decide(self, observation: Observation, context: DecisionContext) -> Decision: ...


class VoiceInput(Protocol):
    """Phase 5: explicit request only, never a perpetual microphone task."""

    async def listen(self, *, language: str, duration_ms: int) -> Event: ...


class PlaybackAdapter(Protocol):
    """Phase 5: caller must normalize PCM format before gateway playback."""

    async def play_pcm(self, pcm: bytes, *, sample_rate: int, channels: int) -> None: ...


class Microphone(Protocol):
    async def record(self, *, duration_ms: int) -> PCM16Audio: ...


class SpeechTranscriber(Protocol):
    async def transcribe(self, audio: PCM16Audio, *, language: str = "ko") -> str: ...


class SpeechSynthesizer(Protocol):
    async def synthesize(self, text: str) -> PCM16Audio: ...
