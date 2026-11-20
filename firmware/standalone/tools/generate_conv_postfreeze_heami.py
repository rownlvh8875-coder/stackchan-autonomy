"""Create *new* Heami TTS holdout ONLY AFTER tiny-CNN freeze commit.

Same Windows SAPI voice, different phrases/prosody. No human-speaker or
room/environment independence and no hardware/paid API access.
"""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from synthesize_korean_wake_sapi import _canonicalize, _synthesize_raw

POST_FREEZE = (
    ("wake", "조수야", 3),
    ("wake", "조수야", 4),
    ("wake", "조수야!", 5),
    ("wake", "조수야?", 6),
    ("nonwake", "조종아", -2),
    ("nonwake", "조영수", -1),
    ("nonwake", "조차야", 0),
    ("nonwake", "조하야", 1),
    ("nonwake", "조세야", 2),
    ("nonwake", "고추야", -3),
    ("nonwake", "조씨요", 3),
    ("nonwake", "조시훈", -4),
    ("nonwake", "조병아", 4),
    ("nonwake", "준영아", -5),
    ("nonwake", "조수경", 5),
    ("nonwake", "좌수야", -6),
)


def generate(output: Path) -> dict:
    if os.name != "nt":
        raise ValueError("windows_sapi_only")
    checkout = Path(__file__).resolve().parents[3]
    path = output.resolve()
    if path == checkout or checkout in path.parents:
        raise ValueError("private_data_must_be_outside_git")
    if output.exists() or output.is_symlink():
        raise ValueError("existing_output_refused")
    output.mkdir(exist_ok=False)
    try:
        (output / "evaluation").mkdir()
        rows = [
            {
                "name": f"cnn_eval_{i:02}",
                "id": f"cnn-eval-{i:02}",
                "stage": "evaluation",
                "label": label,
                "session": "heami_after_cnn_frozen_commit_92a3796",
                "text": phrase,
                "rate": rate,
                "file": f"evaluation/cnn_eval_{i:02}.wav",
            }
            for i, (label, phrase, rate) in enumerate(POST_FREEZE, start=1)
        ]
        with tempfile.TemporaryDirectory(dir=output, prefix="raw-sapi-") as tmp:
            _synthesize_raw(Path(tmp), rows)
            for item in rows:
                _canonicalize(Path(tmp) / (item["name"] + ".wav"), output / item["file"])
        document = {
            "schema": "stackchan-private-wake-corpus-v1",
            "samples": [
                {key: item[key] for key in ("id", "stage", "label", "session", "file")}
                for item in rows
            ],
        }
        with (output / "cnn-postfreeze.wake-corpus.json").open(
            "x", encoding="utf-8", newline="\n"
        ) as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
        return {
            "status": "POST_FREEZE_SYNTHETIC_HEAMI_CNN_HOLDOUT_CREATED",
            "wake": 4,
            "nonwake": 12,
            "same_microsoft_heami_voice": True,
            "speaker_or_room_independence_proven": False,
            "robot_or_microphone_accessed": False,
            "network_or_paid_api_used": False,
        }
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = generate(args.output)
        status = 0
    except (OSError, ValueError):
        result = {
            "status": "REJECTED_POSTFREEZE_SYNTHETIC_CNN_HOLDOUT",
            "robot_or_microphone_accessed": False,
        }
        status = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
