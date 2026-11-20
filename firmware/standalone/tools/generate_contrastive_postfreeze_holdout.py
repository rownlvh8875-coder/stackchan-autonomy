"""New host-only Heami TTS holdout AFTER fixed contrastive code commit a59e7be.

No old evaluation WAVs used. Same speaker/model; not human or independent
room/recording evidence. Never uploads or records microphones.
"""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from synthesize_korean_wake_sapi import _canonicalize, _synthesize_raw

# New nonwake phrases are different from all old hard-negative calibration
# and all previous evaluation words; positive rates are new variants.
POST_FREEZE = (
    ("wake", "조수야", -4),
    ("wake", "조수야", -7),
    ("wake", "조수야", 7),
    ("wake", "조수야", 8),
    ("nonwake", "철수야", 0),
    ("nonwake", "종수아", -1),
    ("nonwake", "조수현", 2),
    ("nonwake", "조수빈", -2),
    ("nonwake", "조성아", 1),
    ("nonwake", "조우진", -3),
    ("nonwake", "조희야", 3),
    ("nonwake", "조도야", -4),
    ("nonwake", "주연아", 4),
    ("nonwake", "주사야", -5),
    ("nonwake", "조영아", 5),
    ("nonwake", "초수연", -6),
)


def generate(destination: Path) -> dict:
    if os.name != "nt":
        raise ValueError("local_windows_sapi_required")
    repo = Path(__file__).resolve().parents[3]
    resolved = destination.resolve()
    if resolved == repo or repo in resolved.parents:
        raise ValueError("private_corpus_must_be_outside_checkout")
    if destination.exists() or destination.is_symlink():
        raise ValueError("existing_destination_refused")

    destination.mkdir(exist_ok=False)
    try:
        (destination / "evaluation").mkdir()
        records = [
            {
                "name": f"contrast_eval_{i:02}",
                "text": phrase,
                "rate": rate,
                "id": f"contrast-eval-{i:02}",
                "label": label,
                "stage": "evaluation",
                "session": "new_Heami_synth_after_a59e7be",
                "file": f"evaluation/contrast_eval_{i:02}.wav",
            }
            for i, (label, phrase, rate) in enumerate(POST_FREEZE, start=1)
        ]
        with tempfile.TemporaryDirectory(dir=destination, prefix="sapi-raw-") as raw:
            _synthesize_raw(Path(raw), records)
            for row in records:
                _canonicalize(
                    Path(raw) / f"{row['name']}.wav",
                    destination / row["file"],
                )
        with (destination / "post-freeze.wake-corpus.json").open(
            "x", encoding="utf-8", newline="\n"
        ) as stream:
            json.dump(
                {
                    "schema": "stackchan-private-wake-corpus-v1",
                    "samples": [
                        {key: row[key] for key in ("id", "stage", "label", "session", "file")}
                        for row in records
                    ],
                },
                stream,
                ensure_ascii=False,
                indent=2,
            )
        return {
            "status": "SYNTHETIC_HEAMI_POST_FREEZE_HOLDOUT_CREATED",
            "wake": 4,
            "nonwake": 12,
            "voice_source": "Windows Heami SAPI",
            "different_human_speakers": False,
            "actual_recognition_accuracy_proven": False,
            "robot_accessed": False,
            "paid_api_used": False,
        }
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = generate(args.output)
        code = 0
    except (ValueError, OSError):
        result = {"status": "SYNTHETIC_HOLDOUT_REJECTED", "robot_accessed": False}
        code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
