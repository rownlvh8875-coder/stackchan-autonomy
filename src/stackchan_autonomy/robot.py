from collections import deque
from io import BytesIO

from PIL import Image

from .models import Event, EventKind, Observation, RobotCommand, RobotStatus


class FakeRobotAdapter:
    """Deterministic simulation; labels are injected, never real person detection."""

    physical = False

    def __init__(self, *, person_present: bool = False, history_size: int = 100):
        self.connected = True
        self.person_present = person_present
        self.yaw = 0.0
        self.pitch = 45.0
        self.emotion = "idle"
        self.history: deque[RobotCommand] = deque(maxlen=history_size)

    async def status(self) -> RobotStatus:
        return RobotStatus(connected=self.connected, yaw=self.yaw, pitch=self.pitch)

    async def capture(self) -> Observation:
        if not self.connected:
            raise ConnectionError("device disconnected")
        stream = BytesIO()
        Image.new("RGB", (32, 32), "white" if self.person_present else "black").save(
            stream, format="PNG"
        )
        return Observation(person_present=self.person_present, image=stream.getvalue())

    def touch_event(self, *, stroke: bool = False) -> Event:
        return Event(kind=EventKind.TOUCH_STROKE if stroke else EventKind.TOUCH_TAP)

    async def execute(self, command: RobotCommand) -> None:
        if not self.connected:
            raise ConnectionError("device disconnected")
        if command.kind == "move":
            self.yaw, self.pitch = command.yaw, command.pitch
        elif command.kind == "emote":
            self.emotion = command.emotion
        self.history.append(command)
