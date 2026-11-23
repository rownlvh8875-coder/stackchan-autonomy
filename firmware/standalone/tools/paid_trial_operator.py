"""Run the owner-led part of a scoped K151 trial in a Windows console."""

import subprocess
import sys
import time
from collections.abc import Callable
from importlib import import_module
from pathlib import Path

from paid_trial_binding import PaidTrialPaths
from paid_trial_rom import run_rom_paid_trial
from paid_trial_sequence import TrialResult


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
