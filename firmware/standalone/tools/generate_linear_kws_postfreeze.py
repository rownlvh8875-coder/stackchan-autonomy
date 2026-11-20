"""Generate a NEW same-Heami TTS holdout AFTER linear model commit 80e280c.

Zero new training/calibration recordings are generated. No microphone,
cloud, paid API, ESP32-S3, NVS or robotics hardware is accessed.
"""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from synthesize_korean_wake_sapi import _canonicalize, _synthesize_raw

# Wake rates never used by training; negative phrases distinct from earlier
# explicitly committed calibration/evaluation word lists.
POST_FREEZE = (
    ("wake", "조수야", 9),
    ("wake", "조수야", 10),
    ("wake", "조수야!", 3),
    ("wake", "조수야?", 4),
    ("nonwake", "조이야", 0),
    ("nonwake", "조수미", -1),
    ("nonwake", "조명아", 2),
    ("nonwake", "조서연", -2),
    ("nonwake", "수아야", 1),
    ("nonwake", "고수야", -3),
    ("nonwake", "조상아", 3),
    ("nonwake", "수호야", -4),
    ("nonwake", "조시야", 4),
    ("nonwake", "조수한", -5),
    ("nonwake", "종이야", 5),
    ("nonwake", "초수아", -6),
)


def generate(folder: Path) -> dict:
    if os.name != "nt":
        raise ValueError("windows_sapi_required")
    repo = Path(__file__).resolve().parents[3]
    resolved = folder.resolve()
    if resolved == repo or repo in resolved.parents:
        raise ValueError("output_must_be_outside_git_checkout")
    if folder.exists() or folder.is_symlink():
        raise ValueError("existing_directory_refused")
    folder.mkdir(exist_ok=False)
    try:
        (folder / "evaluation").mkdir()
        items = [
            {
                "name": f"linear_eval_{i:02}",
                "id": f"linear-eval-{i:02}",
                "text": phrase,
                "rate": rate,
                "stage": "evaluation",
                "label": label,
                "session": "new_Heami_after_linear_model_commit",
                "file": f"evaluation/linear_eval_{i:02}.wav",
            }
            for i, (label, phrase, rate) in enumerate(POST_FREEZE, start=1)
        ]
        with tempfile.TemporaryDirectory(prefix="sapi-raw-", dir=folder) as tmp:
            _synthesize_raw(Path(tmp), items)
            for item in items:
                _canonicalize(
                    Path(tmp) / f"{item['name']}.wav",
                    folder / item["file"],
                )
        with (folder / "linear-postfreeze.wake-corpus.json").open(
            "x", encoding="utf-8", newline="\n"
        ) as out:
            json.dump(
                {
                    "schema": "stackchan-private-wake-corpus-v1",
                    "samples": [
                        {k: item[k] for k in ("id", "stage", "label", "session", "file")}
                        for item in items
                    ],
                },
                out,
                ensure_ascii=False,
                indent=2,
            )
        return {
            "status": "NEW_SYNTHETIC_LINEAR_KWS_HOLDOUT_CREATED",
            "wake": 4,
            "nonwake": 12,
            "single_Heami_synthetic_voice": True,
            "human_speaker_independence_proven": False,
            "microphone_or_robot_accessed": False,
            "cloud_or_paid_api_accessed": False,
        }
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = generate(args.output)
        code = 0
    except (OSError, ValueError):
        report = {
            "status": "SYNTHETIC_HOLDOUT_GENERATION_REJECTED",
            "robot_accessed": False,
        }
        code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
