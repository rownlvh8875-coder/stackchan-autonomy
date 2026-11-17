"""Fetch pinned public build inputs into a NEW scratch directory. Source preparation only."""

import argparse
import json
import subprocess
from pathlib import Path

from prepare_observer import ROOT, prepare


def clone(url, commit, destination):
    subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout", url, str(destination)], check=True
    )
    subprocess.run(["git", "-C", str(destination), "checkout", "--detach", commit], check=True)
    actual = subprocess.check_output(
        ["git", "-C", str(destination), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != commit:
        raise SystemExit("OBSERVER_SOURCE_PIN_MISMATCH")


def fetch(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise SystemExit("OBSERVER_NEW_DIRECTORY_REQUIRED")
    pins = json.loads((ROOT / "firmware/observer/dependencies.json").read_text())
    clone("https://github.com/m5stack/StackChan.git", pins["upstream"], destination)
    firmware = destination / "firmware"
    for repo in pins["repos"]:
        target = firmware / repo["path"]
        clone(repo["url"], repo["commit"], target)
        if "patch" in repo:
            data = (firmware / repo["patch"]).read_bytes().replace(b"\r\n", b"\n")
            command = ["git", "-C", str(target), "apply"]
            subprocess.run([*command, "--check", "-"], input=data, check=True)
            subprocess.run([*command, "-"], input=data, check=True)
    prepare(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination")
    fetch(parser.parse_args().destination)
