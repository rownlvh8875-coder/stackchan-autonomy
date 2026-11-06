import argparse
import asyncio
import json
from contextlib import AsyncExitStack
from pathlib import Path

from .decision import MockDecisionProvider, OpenAIDecisionProvider
from .engine import AutonomyEngine
from .models import Event, EventKind
from .robot import FakeRobotAdapter
from .settings import Settings, load_personality
from .simulation import simulate_mcp_robot
from .state_store import StateUnavailable


async def run(args) -> dict:
    settings = Settings.from_yaml(args.config) if args.config else Settings()
    async with AsyncExitStack() as stack:
        provider = (
            OpenAIDecisionProvider(settings) if args.mode == "cloud" else MockDecisionProvider()
        )
        if isinstance(provider, OpenAIDecisionProvider):
            stack.push_async_callback(provider.aclose)
        personality = load_personality(args.personality).instructions if args.personality else ()
        if args.mode == "mcp-sim":
            robot = await stack.enter_async_context(
                simulate_mcp_robot(history_size=settings.history_size)
            )
            history = robot.gateway.robot.history
        else:
            robot = FakeRobotAdapter(person_present=args.person, history_size=settings.history_size)
            history = robot.history
        engine = AutonomyEngine(robot, provider, settings, personality=personality)
        stack.push_async_callback(engine.aclose)
        try:
            if not await engine.actions.claim_control():
                return {"error": "control_busy"}
        except StateUnavailable:
            return {"error": "coordination_unavailable"}
        completed = 0
        if args.forever:
            await engine.run()
        else:
            kind = {
                "timer": EventKind.TIMER_OBSERVE,
                "touch": EventKind.TOUCH_TAP,
                "voice": EventKind.VOICE_REQUEST,
            }[args.event]
            for _ in range(args.cycles):
                await engine.step(Event(kind=kind, text=args.text or ""))
                completed += 1
                if engine.stopped:
                    break
        return {
            "mode": args.mode,
            "robot": "mcp-simulated" if args.mode == "mcp-sim" else "fake",
            "cycles": completed,
            "state": engine.state.value,
            "simulated_actions": len(history),
            "cloud_requests": getattr(getattr(provider, "usage", None), "requests", 0),
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="StackChan autonomy; physical control disabled")
    parser.add_argument("--mode", choices=("mock", "cloud", "mcp-sim"), default="mock")
    parser.add_argument("--cycles", type=int, default=3, help="bounded, immediate demo cycles")
    parser.add_argument("--forever", action="store_true", help="periodic observation scheduler")
    parser.add_argument("--person", action="store_true", help="inject simulated person presence")
    parser.add_argument("--event", choices=("timer", "touch", "voice"), default="timer")
    parser.add_argument("--text", help="explicit text request; not logged")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/robot.yaml") if Path("config/robot.yaml").exists() else None,
    )
    parser.add_argument(
        "--personality",
        type=Path,
        default=(
            Path("config/personality.yaml") if Path("config/personality.yaml").exists() else None
        ),
    )
    args = parser.parse_args(argv)
    if args.cycles < 1:
        parser.error("--cycles must be positive")
    try:
        summary = asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError):
        # Pydantic errors can contain input values; never print their raw message.
        parser.exit(2, "Configuration invalid or cloud prerequisites missing; see README.\n")
    if summary.get("error") == "control_busy":
        parser.exit(
            2, "Robot control is held by another process; wait for release or lease expiry.\n"
        )
    if summary.get("error") == "coordination_unavailable":
        parser.exit(2, "Coordination storage unavailable; no robot commands were sent.\n")
    print(json.dumps(summary, ensure_ascii=False))
    return 0
