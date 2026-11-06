from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from stackchan_autonomy.models import Decision, Event, EventKind, RobotCommand
from stackchan_autonomy.perception import Perception
from stackchan_autonomy.robot import FakeRobotAdapter
from stackchan_autonomy.settings import Settings, load_personality


def test_defaults_do_not_enable_external_effects(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = Settings()
    assert not config.cloud_enabled
    assert not config.image_transmission
    assert not config.audio_transmission
    assert not config.hardware_enabled
    assert config.dry_run
    assert config.observe_interval_s == 30


@pytest.mark.parametrize(
    "payload",
    [
        {"intent": "shell", "command": "rm -rf /"},
        {"intent": "look", "yaw_delta_deg": float("nan")},
        {"intent": "look", "yaw_delta_deg": float("inf")},
        {"intent": "look", "yaw_delta_deg": True},
        {"intent": "speak", "speech": "a" * 501},
    ],
)
def test_untrusted_decision_shape_is_rejected(payload):
    with pytest.raises(ValidationError):
        Decision.model_validate(payload)


def test_environment_overrides_yaml_and_secrets_are_hidden(monkeypatch, tmp_path):
    config = tmp_path / "robot.yaml"
    config.write_text("observe_interval_s: 45\n", encoding="utf-8")
    monkeypatch.setenv("STACKCHAN_OBSERVE_INTERVAL_S", "31")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-never-log")
    settings = Settings.from_yaml(config)
    assert settings.observe_interval_s == 31
    assert "test-secret-never-log" not in repr(settings)
    assert "test-secret-never-log" not in settings.model_dump_json()


def test_malformed_yaml_and_unsafe_limits_are_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("[one, two]", encoding="utf-8")
    with pytest.raises(ValueError):
        Settings.from_yaml(path)
    for data in (
        {"pitch_min": -1},
        {"yaw_max": 180},
        {"max_step_deg": 90},
        {"observe_interval_s": 0},
        {"pitch_min": 70, "pitch_max": 50},
    ):
        with pytest.raises(ValueError):
            Settings(**data)


def test_personality_file_has_korean_nonintrusive_instructions():
    personality = load_personality("config/personality.yaml")
    assert personality.language == "ko"
    assert len(personality.instructions) >= 4


async def test_fake_robot_capture_and_commands_are_observable():
    robot = FakeRobotAdapter(person_present=True)
    observation = await robot.capture()
    assert observation.person_present is True  # Explicit simulated label, not CV.
    assert Image.open(BytesIO(observation.image)).format == "PNG"
    await robot.execute(RobotCommand(kind="move", yaw=10, pitch=50))
    assert (await robot.status()).yaw == 10
    assert (await robot.status()).pitch == 50
    assert len(robot.history) == 1
    robot.connected = False
    with pytest.raises(ConnectionError):
        await robot.capture()


async def test_perception_change_gate_keeps_no_original_image():
    robot = FakeRobotAdapter()
    perception = Perception()
    first = perception.process(await robot.capture())
    second = perception.process(await robot.capture())
    robot.person_present = True
    third = perception.process(await robot.capture())
    assert first.scene_changed is True
    assert second.scene_changed is False
    assert third.scene_changed is True
    assert not any(isinstance(v, bytes) and len(v) > 1024 for v in vars(perception).values())


def test_stop_and_user_events_have_priority_over_timer():
    assert Event(kind=EventKind.USER_STOP).priority < Event(kind=EventKind.TOUCH_TAP).priority
    assert (
        Event(kind=EventKind.VOICE_REQUEST).priority < Event(kind=EventKind.TIMER_OBSERVE).priority
    )
