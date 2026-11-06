from typing import Protocol

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
