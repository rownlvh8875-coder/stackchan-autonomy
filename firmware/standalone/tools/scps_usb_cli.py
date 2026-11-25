"""Explicit opt-in serial SCPS provisioning client (NOT a device flasher).

This command cannot work until a separately approved K151 firmware activates
the SCPS port, trusted LCD, sensor, and physical STOP. It is never run by CI
against hardware. An operator can explicitly reuse existing local credentials
after matching the device code. Secret values stay out of command arguments.
"""

from __future__ import annotations

import argparse
import getpass
import json
import warnings
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Protocol

from scps_reference import PcSession
from scps_saved_setup import load_connected_wifi, load_openai_key
from scps_usb_wire import Frame, Op, ScpsWireError, SerialLike, expect, write_one


class OperatorInputs(Protocol):
    def __call__(self, prompt: str) -> str: ...


def run_pairing(
    port: SerialLike,
    *,
    text_input: OperatorInputs = input,
    hidden_input: OperatorInputs = getpass.getpass,
    say: Callable[[str], None] = print,
    on_phase: Callable[[str], None] = lambda _phase: None,
    load_wifi: Callable[[], tuple[bytes, str] | None] | None = None,
    load_api_key: Callable[[], str | None] | None = None,
) -> bool:
    """One single attempt, no auto-retry, no recording of submitted secrets."""
    try:
        on_phase("device_hello")
        hello = expect(port, Op.DEVICE_HELLO, 20)
        on_phase("pc_hello")
        pc = PcSession(hello.payload)
        write_one(port, Frame(Op.PC_HELLO, pc.pc_hello))
        on_phase("display_ready")
        expect(port, Op.DISPLAY_READY, 20)

        on_phase("local_credentials")
        say("PC pairing code: " + pc.sas)
        say("Compare all eight digits with the K151's trusted physical LCD.")
        observed = text_input("Type the 8 digits shown on the K151 LCD: ").strip()
        if len(observed) != 8 or not observed.isdecimal() or observed != pc.sas:
            raise ScpsWireError("pairing codes do not match; canceled")
        saved_wifi = load_wifi() if load_wifi is not None else None
        with warnings.catch_warnings():
            # getpass warns before it falls back to reading with echo enabled.
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                if saved_wifi is None:
                    if load_wifi is not None:
                        say("Saved Windows Wi-Fi is unavailable. Enter Wi-Fi details locally.")
                    ssid = text_input("Wi-Fi SSID (visible): ").encode("utf-8")
                    password = hidden_input("Wi-Fi password (hidden): ")
                else:
                    ssid, password = saved_wifi
                api_key = load_api_key() if load_api_key is not None else None
                if api_key is None:
                    if load_api_key is not None:
                        say("The selected file has no usable API key. Enter it locally.")
                    api_key = hidden_input("OpenAI API key (hidden): ")
            except getpass.GetPassWarning:
                raise ScpsWireError("secure console input unavailable") from None
        # The device requires its own on-screen comparison and final head hold.
        sealed = pc.seal(ssid, password, api_key, observed, reviewed_locally=True)
        write_one(port, Frame(Op.SEALED, sealed))
        on_phase("pending_touch")
        expect(port, Op.PENDING_TOUCH, 20)

        on_phase("owner_confirmation")
        say("If all 8 digits match, hold the K151 screen for 1 second and release.")
        say("At FINAL APPROVAL, lightly touch the top of the head for 3 seconds, then lift.")
        expect(port, Op.COMPLETED, 120)
        say("Device reports one-time RAM setup complete. No credential file was saved.")
        return True
    except Exception:
        # Explicit best-effort abort only. It is not proof of delivery.
        try:
            write_one(port, Frame(Op.STOP))
        except (OSError, ValueError, ScpsWireError):
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="K151 SCPS encrypted USB setup (requires approved device UI)"
    )
    parser.add_argument("--port", required=True, help="Exact COM/tty port; never auto-discovered")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Explicitly acknowledge this opens the selected serial device",
    )
    parser.add_argument(
        "--reuse-openai-env", type=Path, help="Read the API key from this local .env"
    )
    parser.add_argument(
        "--reuse-connected-wifi",
        action="store_true",
        help="Use the connected Windows Wi-Fi profile",
    )
    parser.add_argument(
        "--failure-receipt", type=Path, help="Save only the fixed failure stage and reason locally"
    )
    args = parser.parse_args(argv)
    if not args.interactive:
        parser.error("--interactive is required; no automatic serial connection")
    # Import only when actually invoked. Existing project pins pyserial.
    try:
        import serial
    except ImportError as exc:
        parser.error("pyserial is required")
        raise AssertionError("unreachable") from exc

    phase = "serial_open"

    def set_phase(current: str) -> None:
        nonlocal phase
        phase = current

    try:
        port = serial.Serial(port=None, baudrate=115200, timeout=0.25, write_timeout=2)
        port.port = args.port
        port.dtr = port.rts = False
        with port:
            print(
                "로봇에 SETUP PRESENCE가 보이면 머리 윗면에 손가락을 가볍게 "
                "3초 대고 완전히 떼세요.",
                flush=True,
            )
            run_pairing(
                port,
                on_phase=set_phase,
                load_wifi=load_connected_wifi if args.reuse_connected_wifi else None,
                load_api_key=(
                    partial(load_openai_key, args.reuse_openai_env)
                    if args.reuse_openai_env
                    else None
                ),
            )
    except (ScpsWireError, ValueError, OSError, EOFError, serial.SerialException) as exc:
        # Do not print sensitive exception parameters or serial payloads.
        reason = "setup_rejected"
        if isinstance(exc, ScpsWireError):
            reason = exc.diagnostic
        elif isinstance(exc, (OSError, serial.SerialException)):
            reason = "serial_io"
        if args.failure_receipt is not None:
            try:
                with args.failure_receipt.open("x", encoding="utf-8") as receipt:
                    json.dump({"stage": phase, "reason": reason}, receipt)
            except OSError:
                print("Setup failure receipt could not be saved.")
        print(f"Pairing failed at {phase} ({reason}). Restart the local device before retry.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
