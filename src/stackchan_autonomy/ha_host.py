"""Start the managed Assist workers with a provisioned budget and host credential."""

import asyncio
import os
import sys
from pathlib import Path

from pydantic import SecretStr

from . import ha_voice
from .budget import SQLiteRequestBudget
from .settings import Settings
from .state_store import StateUnavailable


def load_key() -> SecretStr:
    directory = Path(os.environ.get("CREDENTIALS_DIRECTORY", ""))
    if not directory.is_absolute():
        raise ha_voice.VoiceDenied("HA_HOST_CONFIG_REQUIRED")
    with (directory / "openai-key").open("rb") as credential:
        raw = credential.read(8195)
    if len(raw) == 8195:
        raise ha_voice.VoiceDenied("HA_HOST_CONFIG_REQUIRED")
    return SecretStr(raw.rstrip(b"\r\n").decode("ascii"))


def initialize_budget(settings: Settings):
    creating = settings.model_copy(update={"budget_require_existing": False})
    budget = SQLiteRequestBudget(creating)
    try:
        # First setup is explicit. There is no overwrite or initialization on boot.
        with budget.store.path.open("xb"):
            pass
        budget.record_usage()
    except OSError:
        raise StateUnavailable("budget could not be initialized") from None


async def run_worker(role: str, settings: Settings):
    if role == "voice":
        ha_voice.validate_config(settings)
    else:
        from . import ha_conversation

        ha_conversation.validate_config(settings)
    await asyncio.to_thread(SQLiteRequestBudget(settings).snapshot)
    if role == "check":
        print("HA_HOST_READY")
    elif role == "voice":
        await ha_voice.serve(settings, 10300)
    else:
        await ha_conversation.serve(settings)


def main(argv: list[str] | None = None) -> int:
    parser = ha_voice.VoiceArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("initialize-budget", "check", "voice", "conversation"))
    try:
        role = parser.parse_args(argv).role
        settings = Settings(_env_file=None)
        if not settings.state_path.is_absolute():
            raise ha_voice.VoiceDenied("HA_HOST_CONFIG_REQUIRED")
        if role == "initialize-budget":
            initialize_budget(settings)
            print("HA_HOST_BUDGET_INITIALIZED")
            return 0
        settings = settings.model_copy(
            update={"api_key": load_key(), "budget_require_existing": True}
        )
        with ha_voice.private_voice_logs():
            asyncio.run(run_worker(role, settings))
    except StateUnavailable:
        print("HA_HOST_BUDGET_UNAVAILABLE", file=sys.stderr)
        return 2
    except (ValueError, OSError, ha_voice.VoiceDenied) as exc:
        if isinstance(exc, ha_voice.VoiceDenied) and str(exc) in {
            "HA_VOICE_STORAGE_UNAVAILABLE",
            "HA_VOICE_DEPENDENCIES_REQUIRED",
        }:
            print(str(exc), file=sys.stderr)
        else:
            print("HA_HOST_CONFIG_REQUIRED", file=sys.stderr)
        return 2
    except (SystemExit, Exception) as exc:
        if isinstance(exc, SystemExit) and exc.code == 0:
            return 0
        print("HA_HOST_WORKER_FAILED", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
