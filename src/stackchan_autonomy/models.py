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


class MemoryRecord(StrictModel):
    at: float
    event: EventKind
    intent: Literal["idle", "look", "emote", "speak"]
    result: str


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
