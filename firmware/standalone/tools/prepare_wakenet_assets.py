"""Pack locally supplied, pinned ESP-SR 2.4.7 public model files. No device I/O.

Format follows pinned esp-sr model/pack_model.py. Output uses exclusive creation;
never downloads, reads credentials, changes partitions or grants runtime consent.
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PIN = json.loads(
    (ROOT / "docs/validation/2026-11-20-k151-builtin-wakenet-preflight.json").read_text(
        encoding="utf-8"
    )
)
FILES = PIN["model"]["pack_contents"]["files"]
PACK_BYTES = PIN["model"]["pack"]["bytes"]
PACK_SHA256 = PIN["model"]["pack"]["sha256"]
MODEL_NAME = "wn9l_histackchan_tts3"


def build_pack(directory: Path) -> bytes:
    header = struct.pack("<I32sI", 1, MODEL_NAME.encode("ascii"), 3)
    data = bytearray()
    for file in FILES:
        path = directory / file["file"]
        if not path.is_file() or path.stat().st_size != file["bytes"]:
            raise ValueError("model file size rejected")
        with path.open("rb") as stream:
            content = stream.read(file["bytes"] + 1)
        if len(content) != file["bytes"] or hashlib.sha256(content).hexdigest() != file["sha256"]:
            raise ValueError("model file integrity rejected")
        if file["offset"] != 160 + len(data):
            raise ValueError("model file layout rejected")
        header += struct.pack("<32sII", file["file"].encode("ascii"), file["offset"], len(content))
        data.extend(content)
    pack = header + data
    if (
        len(header) != 160
        or len(pack) != PACK_BYTES
        or hashlib.sha256(pack).hexdigest() != PACK_SHA256
    ):
        raise ValueError("model pack integrity rejected")
    return pack


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        pack = build_pack(args.source)
        with args.out.open("xb") as output:
            output.write(pack)
        print(
            json.dumps(
                {
                    "status": "PACK_VERIFIED_NOT_PROVISIONED",
                    "bytes": len(pack),
                    "sha256": hashlib.sha256(pack).hexdigest(),
                    "model": MODEL_NAME,
                    "sdk": "2.4.7",
                    "install_authorized": False,
                    "device_assets_verified": False,
                },
                separators=(",", ":"),
            )
        )
        return 0
    except (OSError, ValueError):
        print("MODEL_PACK_REJECTED")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
