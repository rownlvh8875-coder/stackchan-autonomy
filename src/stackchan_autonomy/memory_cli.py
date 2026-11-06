"""Explicit metadata/preferences management; never starts a robot or cloud provider."""

import argparse
from pathlib import Path

from .memory import Memory
from .settings import Settings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="show retained metadata and preferences")
    commands.add_parser("clear", help="clear this resource's memory and preferences")
    update = commands.add_parser("set", help="explicitly update typed preferences")
    update.add_argument("--automatic-speech", choices=("on", "off"))
    update.add_argument("--minimum-speech-interval", help="minimum seconds, 0..86400")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_yaml(args.config) if args.config else Settings()
        if settings.memory_path is None:
            parser.exit(2, "Set STACKCHAN_MEMORY_PATH to enable optional persistent memory.\n")
        changes = {}
        if args.command == "set":
            if args.automatic_speech is not None:
                changes["automatic_speech_enabled"] = args.automatic_speech == "on"
            if args.minimum_speech_interval is not None:
                changes["minimum_speech_interval_s"] = float(args.minimum_speech_interval)
            if not changes:
                parser.exit(2, "Choose at least one preference to set.\n")
        with Memory(
            settings.history_size,
            settings.memory_path,
            resource=settings.control_resource,
            retention_s=settings.memory_retention_s,
        ) as memory:
            if args.command == "set":
                memory.update_preferences(**changes)
            elif args.command == "clear":
                memory.clear()
            print(memory.snapshot().model_dump_json())
    except OSError:
        parser.exit(2, "Memory storage unavailable; no robot commands were sent.\n")
    except (ValueError, TypeError):
        parser.exit(2, "Memory settings or preferences invalid; see MEMORY.md.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
