"""Create an unpopulated private wake corpus manifest, without recording audio.

Exclusive file creation at an explicitly supplied path; no device/network.
Example names are placeholders, not real recordings or verified labels.
"""

import argparse
import json
import os
from pathlib import Path

SCHEMA = "stackchan-private-wake-corpus-v1"


def template() -> dict:
    rows = []
    groups = (
        ("enrollment", "wake", 1, "enroll-session"),
        ("calibration", "wake", 5, "cal-session"),
        ("calibration", "nonwake", 10, "cal-session"),
        ("evaluation", "wake", 1, "eval-session"),
        ("evaluation", "nonwake", 1, "eval-session"),
    )
    for stage, label, count, session in groups:
        for i in range(1, count + 1):
            rows.append(
                {
                    "id": f"{stage}-{label}-{i:02}",
                    "stage": stage,
                    "label": label,
                    "session": session,
                    "file": f"{stage}/{label}-{i:02}.wav",
                }
            )
    return {"schema": SCHEMA, "samples": rows}


def create_private_template(output: Path) -> bool:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(output, flags, 0o600)
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(template(), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    except OSError:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new private *.wake-corpus.json; never overwritten",
    )
    args = parser.parse_args(argv)
    if create_private_template(args.output):
        print("PRIVATE_WAKE_CORPUS_TEMPLATE_CREATED; placeholder paths only; no audio recorded")
        return 0
    print("REJECTED_PRIVATE_TEMPLATE_CREATION; existing or inaccessible path")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
