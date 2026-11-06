"""Audited gateway contracts, independent of transport and physical permissions."""

import json
from typing import Literal

from mcp import types
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class MCPFailure(ConnectionError):
    """Fixed messages only; never include remote payloads."""


class GatewaySnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")
    connected: StrictBool
    initialized: StrictBool = False
    device_id: StrictStr | None = None
    session_id: StrictStr | None = None
    tools_count: StrictInt = 0
    tools: list[StrictStr] = Field(default_factory=list)


class HeadPose(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    yaw: float = Field(strict=True, ge=-90, le=90)
    pitch: float = Field(strict=True, ge=5, le=85)


class TouchState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    available: StrictBool
    zone0: StrictBool
    zone1: StrictBool
    zone2: StrictBool
    raw: StrictInt = Field(ge=0, le=255)
    last_event: Literal["idle", "tap", "stroke"]
    last_event_age_ms: StrictInt = Field(ge=-1)


class MotorAck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    servo_init_ok: StrictBool
    uart_num: StrictInt = Field(ge=0, le=2)
    yaw_pos: StrictInt = Field(ge=0, le=1023)
    pitch_pos: StrictInt = Field(ge=0, le=1023)
    yaw_motion_started: StrictInt = Field(ge=0, le=1)
    pitch_motion_started: StrictInt = Field(ge=0, le=1)


TOOL_MAP = {
    "pose": ("get_head_angles", "self.robot.get_head_angles"),
    "move": ("move_head", "self.robot.set_head_angles"),
    "capture": ("take_photo", "self.camera.take_photo"),
    "emote": ("set_avatar", "self.display.set_avatar"),
    "blink": ("set_blink", "self.display.set_blink"),
    "led": ("set_all_leds", "self.led.set_all"),
    "touch": ("get_touch_state", "self.touch.get_touch_state"),
    "speak": ("say", None),
    "listen": ("listen", None),
}


def json_payload(result: types.CallToolResult) -> dict:
    if result.isError:
        raise MCPFailure("gateway rejected request")
    chunks = [b.text for b in result.content if b.type == "text"]
    if not chunks or sum(map(len, chunks)) > 65536:
        raise MCPFailure("invalid gateway text envelope")
    try:
        payload = json.loads("\n".join(chunks))
    except (ValueError, TypeError):
        raise MCPFailure("invalid gateway JSON") from None
    if not isinstance(payload, dict):
        raise MCPFailure("gateway result must be an object")
    if "error" in payload and payload["error"] is not None:
        raise MCPFailure("gateway error envelope")
    for marker in ("ok", "available"):
        if marker in payload and type(payload[marker]) is not bool:
            raise MCPFailure("invalid gateway success marker")
    if payload.get("ok") is False:
        raise MCPFailure("gateway operation unsuccessful")
    return payload


def supports_tool(name: str, schema: dict) -> bool:
    """Reject schema drift rather than invent missing required arguments."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return False
    annotations = {"description", "title", "default", "examples"}
    if set(schema) - annotations - {"type", "properties", "required", "additionalProperties"}:
        return False
    if "additionalProperties" in schema and type(schema["additionalProperties"]) is not bool:
        return False
    props, required = schema.get("properties", {}), schema.get("required", [])
    if (
        not isinstance(props, dict)
        or not isinstance(required, list)
        or not all(isinstance(v, str) for v in required)
    ):
        return False
    expected = {
        "get_status": [],
        "get_head_angles": [],
        "get_touch_state": [],
        "move_head": ["yaw", "pitch"],
        "take_photo": ["question"],
        "set_avatar": ["face"],
        "set_blink": ["enabled"],
        "set_all_leds": ["r", "g", "b"],
        "say": ["text"],
        "listen": [],
    }
    if (
        name not in expected
        or set(required) != set(expected[name])
        or len(required) != len(set(required))
    ):
        return False

    def field(key, kind, minimum=None, maximum=None, *, enum=False):
        value = props.get(key)
        allowed = annotations | {"type"}
        if minimum is not None:
            allowed.add("minimum")
        if maximum is not None:
            allowed.add("maximum")
        if enum:
            allowed.add("enum")
        return (
            isinstance(value, dict)
            and not set(value) - allowed
            and value.get("type") == kind
            and (minimum is None or value.get("minimum") == minimum)
            and (maximum is None or value.get("maximum") == maximum)
        )

    if name == "move_head":
        speed = props.get("speed", {})
        if not isinstance(speed, dict) or set(speed) - annotations - {"type", "enum", "oneOf"}:
            return False
        variants = speed.get("oneOf", [speed])
        if not isinstance(variants, list):
            return False
        low_matches = 0
        for variant in variants:
            if not isinstance(variant, dict):
                return False
            if variant.get("type") == "integer":
                if set(variant) - annotations - {"type", "minimum", "maximum"}:
                    return False
                continue
            if (
                set(variant) - annotations - {"type", "enum"}
                or variant.get("type", "string") != "string"
                or not isinstance(variant.get("enum"), list)
            ):
                return False
            low_matches += "low" in variant["enum"]
        return (
            field("yaw", "integer", -90, 90)
            and field("pitch", "integer", 5, 85)
            and low_matches == 1
        )
    if name == "set_avatar":
        face = props.get("face", {})
        return (
            field("face", "string", enum=True)
            and isinstance(face.get("enum"), list)
            and {"idle", "happy"}.issubset(face["enum"])
        )
    if name == "set_blink":
        return field("enabled", "boolean")
    if name == "set_all_leds":
        return all(field(key, "integer", 0, 255) for key in ("r", "g", "b"))
    if name == "take_photo":
        return field("question", "string")
    if name == "say":
        return field("text", "string")
    if name == "listen":
        return (
            field("duration_ms", "integer", 100, 30000)
            and field("language", "string")
            and isinstance(props.get("motion"), dict)
            and field("motion", "string", enum=True)
            and "none" in props["motion"].get("enum", [])
        )
    return True
