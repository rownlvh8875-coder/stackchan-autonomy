"""Typed, closed contracts. Raw media/text never appear in model reprs."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class EventKind(str, Enum):
    USER_STOP = "USER_STOP"
    DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
    CLOUD_API_ERROR = "CLOUD_API_ERROR"
    VOICE_REQUEST = "VOICE_REQUEST"
    TOUCH_TAP = "TOUCH_TAP"
    TOUCH_STROKE = "TOUCH_STROKE"
    PERSON_DETECTED = "PERSON_DETECTED"
    SCENE_CHANGED = "SCENE_CHANGED"
    TIMER_OBSERVE = "TIMER_OBSERVE"
    IDLE_ANIMATION = "IDLE_ANIMATION"


class Event(StrictModel):
    kind: EventKind
    text: str = Field(default="", max_length=500, repr=False, exclude=True)

    @property
    def priority(self) -> int:
        if self.kind in {
            EventKind.USER_STOP,
            EventKind.DEVICE_DISCONNECTED,
            EventKind.CLOUD_API_ERROR,
        }:
            return 0
        if self.kind in {EventKind.VOICE_REQUEST, EventKind.TOUCH_TAP, EventKind.TOUCH_STROKE}:
            return 1
        if self.kind in {EventKind.PERSON_DETECTED, EventKind.SCENE_CHANGED}:
            return 2
        return 3 if self.kind == EventKind.TIMER_OBSERVE else 4


class Decision(StrictModel):
    intent: Literal["idle", "look", "emote", "speak"] = "idle"
    emotion: Literal["idle", "happy", "thinking", "sad", "surprised", "embarrassed"] = "idle"
    speech: str = Field(default="", max_length=500, repr=False)
    yaw_delta_deg: float = Field(default=0, strict=True)
    pitch_delta_deg: float = Field(default=0, strict=True)
    reason: str = Field(default="", max_length=300, repr=False)


class Observation(StrictModel):
    person_present: bool | None = None
    scene_changed: bool = True
    image: bytes | None = Field(default=None, repr=False, exclude=True, max_length=2_000_000)
    image_mime: Literal["image/png", "image/jpeg"] = "image/png"


class RobotStatus(StrictModel):
    connected: bool = True
    yaw: float = 0
    pitch: float = 45
    capabilities: frozenset[str] = frozenset({"capture", "move", "emote", "speak"})


class RobotCommand(StrictModel):
    kind: Literal["move", "emote", "speak"]
    yaw: float = 0
    pitch: float = 45
    emotion: str = "idle"
    speech: str = Field(default="", repr=False)


class ActionResult(StrictModel):
    executed: bool = False
    code: str = "idle"


ControlLossReason = Literal[
    "lease_invalid",
    "acquire_timeout",
    "check_timeout",
    "renew_timeout",
    "renew_rejected",
    "renew_error",
    "verification_cancelled",
    "verification_error",
]


class MemoryRecord(StrictModel):
    at: float = Field(ge=0, strict=True)
    event: EventKind
    intent: Literal["idle", "look", "emote", "speak"]
    result: Literal[
        "idle",
        "executed",
        "unsafe",
        "duplicate",
        "command_rate_limit",
        "hardware_disabled",
        "device_fault",
        "lease_busy",
        "queue_full",
        "stopped",
        "speech_cooldown",
        "automatic_speech_disabled",
        "cycle_unavailable",
        "unchanged",
        "cloud_error",
        "memory_unavailable",
    ]


class MemoryPreferences(StrictModel):
    automatic_speech_enabled: bool = Field(default=True, strict=True)
    minimum_speech_interval_s: float = Field(default=0, ge=0, le=86400, strict=True)


class ObservedRobotState(StrictModel):
    at: float = Field(ge=0, strict=True)
    connected: bool = Field(strict=True)
    yaw: float = Field(strict=True)
    pitch: float = Field(strict=True)


class MemorySnapshot(StrictModel):
    recent: tuple[MemoryRecord, ...] = ()
    preferences: MemoryPreferences = MemoryPreferences()
    last_spoken_at: float | None = Field(default=None, ge=0, strict=True)
    last_speech_guard_at: float | None = Field(default=None, ge=0, strict=True)
    last_greeting_at: float | None = Field(default=None, ge=0, strict=True)
    robot: ObservedRobotState | None = None


class DecisionContext(StrictModel):
    event: Event
    status: RobotStatus
    recent: tuple[MemoryRecord, ...] = ()
    personality: tuple[str, ...] = ()
    max_step_deg: float = 15


class State(str, Enum):
    BOOT = "BOOT"
    IDLE = "IDLE"
    OBSERVE = "OBSERVE"
    THINK = "THINK"
    VALIDATE = "VALIDATE"
    ACT = "ACT"
    COOLDOWN = "COOLDOWN"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
