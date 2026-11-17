"""Offline USB diagnostics. Prototype firmware installation requires separate approval."""

import json

from .observer import DEFAULT_PROFILE, ObserverClient, save_profile
from .observer_protocol import ObserverError
from .official_mcp_cli import _ArgumentsInvalid, _PrivateParser


def main(argv=None):
    parser = _PrivateParser(description=__doc__)
    parser.add_argument("operation", choices=["pair", "status", "capture"])
    parser.add_argument("--port", required=True)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--timeout-s", type=float, default=10)
    parser.add_argument("--accept-pairing", action="store_true")
    try:
        try:
            args = parser.parse_args(argv)
        except SystemExit as stop:
            return 0 if stop.code == 0 else 2
        if (args.operation == "pair") != args.accept_pairing:
            raise ObserverError("PC_OBSERVER_PAIRING_REQUIRED")
        with ObserverClient(
            args.port, args.profile, timeout_s=args.timeout_s, pairing=args.accept_pairing
        ) as client:
            if args.operation == "pair":
                save_profile(args.profile, client.hello.device_id)
                print("PC_OBSERVER_PAIRED")
            elif args.operation == "status":
                value = client.status().model_dump(exclude={"boot_id", "uptime_ms"})
                print(json.dumps(value))
            else:
                observation = client.capture()
                print(json.dumps(observation.public_metadata()))
        return 0
    except _ArgumentsInvalid:
        print("PC_OBSERVER_ARGUMENTS_INVALID")
        return 2
    except KeyboardInterrupt:
        print("PC_OBSERVER_STOPPED")
        return 130
    except ObserverError as error:
        print(error.code)
        return 1
    except Exception:
        print("PC_OBSERVER_UNAVAILABLE")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
