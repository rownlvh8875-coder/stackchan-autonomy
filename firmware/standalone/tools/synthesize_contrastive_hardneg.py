"""Additional LOCAL Heami nonwake calibration data (no future evaluation).

Previous nonwake evaluation phrases may be repurposed into development data,
but are then exposed and MUST NOT be treated as independent validation again.
No microphone, device, paid API or cloud TTS is called.
"""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from synthesize_korean_wake_sapi import _canonicalize, _synthesize_raw

HARD_NEGATIVES = (
    ("조수연", -2),
    ("종수야", 0),
    ("조순아", 2),
    ("조우야", -3),
    ("조아야", 1),
    ("수지야", -1),
    ("조민아", 3),
    ("조정아", -2),
    ("조서야", 2),
    ("조씨야", -1),
    ("주수야", 0),
    ("조선아", 2),
    ("초소야", 3),
    ("조수영", 0),
    ("준수야", 0),
    ("조소야", 1),
)
assert all(phrase != "조수야" for phrase, _ in HARD_NEGATIVES)


def generate(output: Path) -> dict:
    if os.name != "nt":
        raise ValueError("windows_sapi_only")
    repo = Path(__file__).resolve().parents[3]
    resolved = output.resolve()
    if repo == resolved or repo in resolved.parents:
        raise ValueError("cannot_put_training_audio_in_repository")
    if output.exists() or output.is_symlink():
        raise ValueError("existing_directory_refused")
    output.mkdir(exist_ok=False)
    try:
        rows = [
            {
                "name": f"hard_negative_{i:02}",
                "text": phrase,
                "rate": rate,
                "file": f"calibration/hard_negative_{i:02}.wav",
            }
            for i, (phrase, rate) in enumerate(HARD_NEGATIVES, start=1)
        ]
        (output / "calibration").mkdir()
        with tempfile.TemporaryDirectory(prefix="sapi-raw-", dir=output) as temp:
            _synthesize_raw(Path(temp), rows)
            for row in rows:
                _canonicalize(
                    Path(temp) / f"{row['name']}.wav",
                    output / row["file"],
                )
        manifest = {
            "kind": "synthetic_heami_nonwake_calibration_only_v1",
            "labels": [
                {"file": row["file"], "label": "nonwake", "role": "calibration"} for row in rows
            ],
        }
        with (output / "hard-negative-calibration.json").open(
            "x", encoding="utf-8", newline="\n"
        ) as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
        return {
            "status": "PRIVATE_HARD_NEGATIVE_CALIBRATION_CREATED",
            "count": len(rows),
            "evaluation_examples_created": 0,
            "same_sapi_voice": True,
            "cloud_or_paid_api_used": False,
            "robot_or_microphone_accessed": False,
        }
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        report = generate(arguments.output)
        code = 0
    except (ValueError, OSError):
        report = {
            "status": "PRIVATE_HARD_NEGATIVE_GENERATION_REJECTED",
            "robot_or_microphone_accessed": False,
        }
        code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
