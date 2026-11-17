"""Apply source-only observer patch to an exact official checkout; never install a device."""

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400"


def prepare(target):
    target = Path(target).resolve()
    head = subprocess.check_output(
        ["git", "-C", str(target), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != UPSTREAM:
        raise SystemExit("OBSERVER_UPSTREAM_MISMATCH")
    destination = target / "firmware/main/hal/pc_observer"
    if destination.exists():
        raise SystemExit("OBSERVER_DESTINATION_EXISTS")
    patch = ROOT / "firmware/observer/integration.patch"
    data = patch.read_bytes().replace(b"\r\n", b"\n")
    command = ["git", "-C", str(target), "apply"]
    camera_command = ["git", "-C", str(target / "firmware/xiaozhi-esp32"), "apply"]
    camera_data = (
        (ROOT / "firmware/observer/camera-access.patch").read_bytes().replace(b"\r\n", b"\n")
    )
    subprocess.run([*command, "--check", "-"], input=data, check=True)
    subprocess.run([*camera_command, "--check", "-"], input=camera_data, check=True)
    subprocess.run([*command, "-"], input=data, check=True)
    subprocess.run([*camera_command, "-"], input=camera_data, check=True)
    for directory in ("core", "esp"):
        shutil.copytree(ROOT / "firmware/observer" / directory, destination / directory)
    print("OBSERVER_SOURCE_PREPARED_NOT_APPROVED_FOR_INSTALLATION")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream")
    prepare(parser.parse_args().upstream)
