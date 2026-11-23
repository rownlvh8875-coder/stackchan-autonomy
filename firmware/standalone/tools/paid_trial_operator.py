"""Run a locally approved K151 one-turn trial and recovery in a Windows console."""

import argparse
import json
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from importlib import import_module
from pathlib import Path

from paid_trial_binding import PaidTrialPaths
from paid_trial_rom import run_rom_paid_trial
from paid_trial_sequence import TrialResult


def _windows_port_available(port: str) -> bool:
    from serial import win32

    # Take an exclusive handle to test ownership without configuring DTR/RTS.
    handle = win32.CreateFile(
        "\\\\.\\" + port,
        win32.GENERIC_READ | win32.GENERIC_WRITE,
        0,
        None,
        win32.OPEN_EXISTING,
        win32.FILE_ATTRIBUTE_NORMAL,
        None,
    )
    return handle != win32.INVALID_HANDLE_VALUE and bool(win32.CloseHandle(handle))


def _wait_for(predicate, seconds, now, sleep) -> bool:
    deadline = now() + seconds
    while now() < deadline:
        if predicate():
            return True
        sleep(0.25)
    return False


def exercise_one_turn(
    pair: Callable[[], bool],
    present: Callable[[], bool],
    read_key: Callable[[], str | None],
    say: Callable[[str], None],
    now: Callable[[], float],
    sleep: Callable[[float], None],
) -> bool:
    def observe_turn():
        say(
            "로봇 화면의 한 턴 범위를 확인한 뒤 화면을 1초 눌렀다 떼세요. "
            "Say Hi StackChan이 나오면 호출어를 한 번 말하고, "
            "Say your question이 나오면 짧은 질문 한 문장을 말하세요."
        )
        say(
            "USB를 분리한 동안 로봇 답변과 Standby verified. Trial ended.를 확인하면 Y, 실패하면 N을 누르세요."
        )
        deadline = now() + 120
        while now() < deadline and not present():
            key = read_key()
            if key in ("y", "Y"):
                return not present()
            if key in ("n", "N", "\x1b"):
                break
            sleep(0.25)
        return False

    confirmed = False
    try:
        say("암호화 설정 도구를 여는 중입니다. 연결이 되면 다음 안내가 표시됩니다.")
        if pair() is True:
            say("지금 로봇의 USB 케이블을 분리하세요.")
            if _wait_for(lambda: not present(), 20, now, sleep):
                confirmed = observe_turn()
    except (OSError, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt):
        say("한 턴 시험이 중단됐습니다.")
    finally:
        say("출고 펌웨어 복구를 위해 로봇을 같은 USB 포트에 다시 연결하세요.")
        reconnected = _wait_for(present, 60, now, sleep)
    return confirmed and reconnected


def run_operator_paid_trial(
    paths: PaidTrialPaths, port: str, port_available: Callable[[str], bool]
) -> TrialResult:
    """Connect the existing ROM and SCPS tools. The caller checks port occupancy."""
    serial_number = None

    def k151_ports():
        from serial.tools.list_ports import comports

        return [item for item in comports() if (item.vid, item.pid) == (0x303A, 0x1001)]

    def available(selected):
        nonlocal serial_number
        if sys.platform != "win32" or not sys.stdin.isatty() or not sys.stdout.isatty():
            return False
        matches = [item for item in k151_ports() if item.device.casefold() == selected.casefold()]
        if len(matches) != 1 or not matches[0].serial_number:
            return False
        observed = matches[0].serial_number.casefold()
        if serial_number is not None and serial_number != observed:
            return False
        if port_available(selected) is not True:
            return False
        # Missing pairing dependencies must be detected before the trial image is written.
        import_module("scps_reference")
        serial_number = observed
        return True

    def present(selected=None):
        return any(
            item.serial_number
            and item.serial_number.casefold() == serial_number
            and (selected is None or item.device.casefold() == selected.casefold())
            for item in k151_ports()
        )

    def pair():
        if not _wait_for(lambda: present(port), 15, time.monotonic, time.sleep):
            return False
        return (
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("scps_usb_cli.py")),
                    "--port",
                    port,
                    "--interactive",
                ],
                timeout=145,
                check=False,
            ).returncode
            == 0
        )

    def read_key():
        import msvcrt

        return msvcrt.getwch() if msvcrt.kbhit() else None

    return run_rom_paid_trial(
        paths,
        port,
        available,
        lambda: exercise_one_turn(
            pair,
            present,
            read_key,
            lambda message: print(message, flush=True),
            time.monotonic,
            time.sleep,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--port", required=True, help="Exact Windows COM port")
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--factory-ota1", type=Path, required=True)
    parser.add_argument("--pretrial-nvs", type=Path, required=True)
    parser.add_argument("--board-reference", type=Path, required=True)
    args = parser.parse_args(argv)
    if re.fullmatch(r"COM[1-9][0-9]*", args.port, re.IGNORECASE) is None:
        parser.error("the port must be a Windows COM name")
    paths = PaidTrialPaths(
        args.review_dir, args.app, args.factory_ota1, args.pretrial_nvs, args.board_reference
    )
    break_signal = getattr(signal, "SIGBREAK", None)
    if break_signal is not None:
        previous_handler = signal.signal(break_signal, signal.default_int_handler)
    try:
        result = run_operator_paid_trial(paths, args.port.upper(), _windows_port_available)
    finally:
        if break_signal is not None:
            signal.signal(break_signal, previous_handler)
    print(
        json.dumps({**asdict(result), "factory_boot_requested": result.factory_boot_requested}),
        flush=True,
    )
    if result.recovery_failure is not None:
        return 3
    if not result.install_attempted:
        return 2
    return int(result.trial_failure is not None)


if __name__ == "__main__":
    raise SystemExit(main())
