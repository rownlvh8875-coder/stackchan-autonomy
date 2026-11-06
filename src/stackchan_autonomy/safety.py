"""All decisions are data. No eval, shell, firmware, or arbitrary MCP tool access."""

from collections import deque

from .models import Decision, RobotCommand, RobotStatus
from .settings import Settings


class UnsafeDecision(ValueError):
    pass


class SafetyPolicy:
    def __init__(self, settings: Settings):
        self.settings = settings

    def plan(self, decision: Decision, status: RobotStatus) -> list[RobotCommand]:
        # Revalidate even when a provider used model_construct/model_copy.
        decision = Decision.model_validate(decision.model_dump())
        motion = decision.yaw_delta_deg != 0 or decision.pitch_delta_deg != 0
        speech = bool(decision.speech.strip())
        expression = decision.emotion != "idle"
        if not status.connected:
            raise UnsafeDecision("disconnected")
        if decision.intent == "idle":
            if motion or speech or expression:
                raise UnsafeDecision("nonempty idle")
            return []
        if decision.intent == "look":
            if speech or expression:
                raise UnsafeDecision("compound action disabled")
            if not motion:
                return []
            s = self.settings
            if max(abs(decision.yaw_delta_deg), abs(decision.pitch_delta_deg)) > s.max_step_deg:
                raise UnsafeDecision("slew limit")
            yaw, pitch = (
                status.yaw + decision.yaw_delta_deg,
                status.pitch + decision.pitch_delta_deg,
            )
            if not (s.yaw_min <= yaw <= s.yaw_max and s.pitch_min <= pitch <= s.pitch_max):
                raise UnsafeDecision("angle envelope")
            commands = [RobotCommand(kind="move", yaw=yaw, pitch=pitch)]
        elif decision.intent == "emote":
            if speech or motion:
                raise UnsafeDecision("compound action disabled")
            commands = [RobotCommand(kind="emote", emotion=decision.emotion)]
        else:
            if motion or expression or not speech:
                raise UnsafeDecision("invalid speech or compound action")
            commands = [RobotCommand(kind="speak", speech=decision.speech)]
        if any(command.kind not in status.capabilities for command in commands):
            raise UnsafeDecision("unsupported capability")
        return commands


class RequestBudget:
    """Explicit in-memory utility; cloud runtime uses budget.SQLiteRequestBudget."""

    def __init__(self, settings: Settings):
        self.windows = (
            (60, settings.requests_per_minute),
            (3600, settings.requests_per_hour),
            (86400, settings.requests_per_day),
        )
        self.timestamps: deque[float] = deque()
        self.total = 0

    def reserve(self, now: float) -> bool:
        while self.timestamps and self.timestamps[0] <= now - 86400:
            self.timestamps.popleft()
        if any(
            sum(t > now - duration for t in self.timestamps) >= maximum
            for duration, maximum in self.windows
        ):
            return False
        self.timestamps.append(now)
        self.total += 1
        return True
