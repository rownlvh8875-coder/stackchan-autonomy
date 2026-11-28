"""Run a locally approved K151 voice trial and recovery in a Windows console."""

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
    *,
    restore_present: Callable[[], bool] | None = None,
) -> bool:
    def observe_turn():
        deadline = now() + 120
        # Input buffered during setup or disconnect is not an observation.
        while now() < deadline and not present():
            if read_key() is None:
                break
        else:
            return False
        say(
            "로봇 화면의 한 턴 범위를 확인한 뒤 화면을 1초 눌렀다 떼세요. "
            "Say Hi StackChan이 나오면 호출어를 한 번 말하고, "
            "Say your question이 나오면 짧은 질문 한 문장을 말하세요."
        )
        say(
            "USB를 분리한 동안 로봇 답변과 Standby verified. Trial ended.를 확인하면 Y, 실패하면 N을 누르세요."
        )
        while now() < deadline and not present():
            key = read_key()
            if key in ("y", "Y"):
                return not present()
            if key in ("n", "N", "\x1b"):
                break
            sleep(0.25)
        return False

    return _run_usb_detached_trial(pair, present, observe_turn, say, now, sleep, restore_present)


def exercise_reboot_trial(
    pair: Callable[[], bool],
    present: Callable[[], bool],
    read_key: Callable[[], str | None],
    say: Callable[[str], None],
    now: Callable[[], float],
    sleep: Callable[[float], None],
    *,
    restore_present: Callable[[], bool] | None = None,
) -> bool:
    def confirm(message: str, seconds: int, key_to_confirm: str) -> bool:
        deadline = now() + seconds
        # Discard buffered input and use a distinct key for each observation.
        while now() < deadline and not present():
            if read_key() is None:
                break
        else:
            return False
        say(f"{message} 확인했으면 {key_to_confirm}, 실패하면 N을 누르세요.")
        while now() < deadline and not present():
            key = read_key()
            if key == key_to_confirm:
                return not present()
            if key in ("n", "N", "\x1b"):
                return False
            sleep(0.25)
        return False

    def observe_reboot():
        if not confirm(
            "TRIAL: ONE PAID TURN에서 앞면을 1초 눌렀다 떼세요. "
            "화면 안내에 맞춰 Hi StackChan과 짧은 질문을 한 번씩 말하세요. "
            "답변을 들은 뒤 Reboot ready. Power off and on. 표시를 확인하세요.",
            120,
            "1",
        ):
            return False
        next_allowed = now() + 60
        say(
            "USB를 분리한 상태로 로봇 전원을 껐다 켜세요. "
            "기존 분당 제한에 맞춰 60초 뒤 잠금 해제를 안내합니다. 중단하려면 N을 누르세요."
        )
        while now() < next_allowed:
            if present() or read_key() in ("n", "N", "\x1b"):
                return False
            sleep(0.25)
        if not confirm(
            "Enter your unlock code가 보이면 로봇 화면에서 저장한 코드를 입력하세요. "
            "TRIAL: TWO PAID TURNS가 나오면 앞면을 1초 눌렀다 떼고 "
            "예산 확인을 거쳐 Say Hi StackChan 대기 화면이 나오는지 확인하세요.",
            180,
            "2",
        ):
            return False
        if not confirm(
            "재부팅 뒤 첫 Hi StackChan과 질문을 한 번씩 말하세요. "
            "답변을 끝까지 듣고 Say Hi StackChan 대기로 돌아오는지 확인하세요.",
            120,
            "3",
        ):
            return False
        return confirm(
            "다시 Hi StackChan과 질문을 한 번씩 말하세요. "
            "로봇 답변 소리가 나는 동안 앞면을 한 번 터치하세요. "
            "소리가 멈추고 다시 재생되지 않는지 확인하세요.",
            120,
            "4",
        )

    return _run_usb_detached_trial(pair, present, observe_reboot, say, now, sleep, restore_present)


def _run_usb_detached_trial(pair, present, observe, say, now, sleep, restore_present):
    confirmed = False
    try:
        say("암호화 설정 도구를 여는 중입니다. 로봇에 표시된 잠금 코드는 로봇에서만 사용하세요.")
        if pair() is True:
            say("지금 로봇의 USB 케이블을 분리하세요.")
            if _wait_for(lambda: not present(), 20, now, sleep):
                confirmed = observe()
    except (OSError, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt):
        say("시험이 중단됐습니다.")
    finally:
        say("출고 펌웨어 복구를 위해 로봇을 같은 USB 포트에 다시 연결하세요.")
        reconnected = _wait_for(
            restore_present if restore_present is not None else present, 60, now, sleep
        )
    return confirmed and reconnected


def run_operator_paid_trial(
    paths: PaidTrialPaths,
    port: str,
    port_available: Callable[[str], bool],
    *,
    recover_only: bool = False,
    reboot_trial: bool = False,
    reuse_openai_env: Path | None = None,
    reuse_connected_wifi: bool = False,
) -> TrialResult:
    """Connect the existing ROM and SCPS tools. The caller checks port occupancy."""
    # The ROM adapter suppresses its output while invoking the port check.
    interactive_console = sys.platform == "win32" and sys.stdin.isatty() and sys.stdout.isatty()
    serial_number = None

    def k151_ports():
        from serial.tools.list_ports import comports

        return [item for item in comports() if (item.vid, item.pid) == (0x303A, 0x1001)]

    def available(selected):
        nonlocal serial_number
        if not interactive_console:
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
        if not recover_only:
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
        command = [
            sys.executable,
            str(Path(__file__).with_name("scps_usb_cli.py")),
            "--port",
            port,
            "--interactive",
            "--failure-receipt",
            str(paths.review_dir / "setup-failure.json"),
        ]
        if reuse_openai_env is not None:
            command.extend(["--reuse-openai-env", str(reuse_openai_env)])
        if reuse_connected_wifi:
            command.append("--reuse-connected-wifi")
        return subprocess.run(command, timeout=145, check=False).returncode == 0

    def read_key():
        import msvcrt

        return msvcrt.getwch() if msvcrt.kbhit() else None

    exercise = exercise_reboot_trial if reboot_trial else exercise_one_turn
    return run_rom_paid_trial(
        paths,
        port,
        available,
        None
        if recover_only
        else lambda: exercise(
            pair,
            present,
            read_key,
            lambda message: print(message, flush=True),
            time.monotonic,
            time.sleep,
            restore_present=lambda: present(port),
        ),
        recover_only=recover_only,
        reboot_trial=reboot_trial,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--execute", action="store_true", help="Run the approved trial")
    mode.add_argument("--recover", action="store_true", help="Resume only the approved restoration")
    parser.add_argument(
        "--reboot-trial", action="store_true", help="Use the separate 1+2-turn reboot trial review"
    )
    parser.add_argument("--port", required=True, help="Exact Windows COM port")
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--factory-ota1", type=Path, required=True)
    parser.add_argument("--pretrial-nvs", type=Path, required=True)
    parser.add_argument("--board-reference", type=Path, required=True)
    parser.add_argument(
        "--reuse-openai-env", type=Path, help="Read the API key from this local .env"
    )
    parser.add_argument(
        "--reuse-connected-wifi",
        action="store_true",
        help="Use the connected Windows Wi-Fi profile",
    )
    args = parser.parse_args(argv)
    if args.recover and (args.reuse_openai_env is not None or args.reuse_connected_wifi):
        parser.error("saved setup options apply only to --execute")
    if re.fullmatch(r"COM[1-9][0-9]*", args.port, re.IGNORECASE) is None:
        parser.error("the port must be a Windows COM name")
    paths = PaidTrialPaths(
        args.review_dir, args.app, args.factory_ota1, args.pretrial_nvs, args.board_reference
    )
    break_signal = getattr(signal, "SIGBREAK", None)
    if break_signal is not None:
        previous_handler = signal.signal(break_signal, signal.default_int_handler)
    try:
        result = run_operator_paid_trial(
            paths,
            args.port.upper(),
            _windows_port_available,
            recover_only=args.recover,
            reboot_trial=args.reboot_trial,
            reuse_openai_env=args.reuse_openai_env,
            reuse_connected_wifi=args.reuse_connected_wifi,
        )
    finally:
        if break_signal is not None:
            signal.signal(break_signal, previous_handler)
    print(
        json.dumps(
            {
                **asdict(result),
                "recovery_only": args.recover,
                **({"trial_scope": "reboot_trial"} if args.reboot_trial else {}),
                "factory_boot_requested": result.factory_boot_requested,
            }
        ),
        flush=True,
    )
    if result.recovery_failure is not None:
        return 3
    if not result.install_attempted:
        return 2
    return int(result.trial_failure is not None)


if __name__ == "__main__":
    raise SystemExit(main())
