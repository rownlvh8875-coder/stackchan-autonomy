"""Create a FRESH synthetic Korean Heami evaluation set after recipe freeze.

Host Windows SAPI only, never training. Creates no enrollment or calibration
WAVs. This same-TTS holdout is not independent-speaker field evidence.
"""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from synthesize_korean_wake_sapi import _canonicalize, _synthesize_raw

NEW_HELDOUT = (
    ("wake", "조수야", -6),
    ("wake", "조수야", -5),
    ("wake", "조수야", 5),
    ("wake", "조수야", 6),
    ("nonwake", "조수연", 0),
    ("nonwake", "조슈아", -1),
    ("nonwake", "조숙아", 1),
    ("nonwake", "주수야", 2),
    ("nonwake", "도수야", -2),
    ("nonwake", "조수영", 3),
    ("nonwake", "초수야", -3),
    ("nonwake", "조수지", 4),
    ("nonwake", "조용하자", -4),
    ("nonwake", "준수야", 5),
    ("nonwake", "소주야", -5),
    ("nonwake", "수야", 0),
)


def create_fresh_holdout(directory: Path) -> dict:
    if os.name != "nt":
        raise ValueError("windows_local_tts_required")
    repo = Path(__file__).resolve().parents[3]
    resolved = directory.resolve()
    if resolved == repo or repo in resolved.parents:
        raise ValueError("private_holdout_cannot_be_in_repo")
    if directory.exists() or directory.is_symlink():
        raise ValueError("existing_holdout_refused")
    directory.mkdir(exist_ok=False)
    try:
        records = []
        for i, (label, text, rate) in enumerate(NEW_HELDOUT):
            records.append(
                {
                    "id": f"fresh-eval-{i + 1:02}",
                    "name": f"fresh_{i + 1:02}",
                    "text": text,
                    "rate": rate,
                    "stage": "evaluation",
                    "label": label,
                    "session": "new_sapi_eval_after_recipe_freeze",
                    "file": f"evaluation/fresh_{i + 1:02}.wav",
                }
            )
        (directory / "evaluation").mkdir()
        with tempfile.TemporaryDirectory(prefix="raw-sapi-", dir=directory) as raw:
            _synthesize_raw(Path(raw), records)
            for row in records:
                _canonicalize(
                    Path(raw) / f"{row['name']}.wav",
                    directory / row["file"],
                )
        manifest = {
            "schema": "stackchan-private-wake-corpus-v1",
            "samples": [
                {key: row[key] for key in ("id", "stage", "label", "session", "file")}
                for row in records
            ],
        }
        with (directory / "fresh-evaluation.wake-corpus.json").open(
            "x", encoding="utf-8", newline="\n"
        ) as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
        return {
            "status": "NEW_LOCAL_SYNTHETIC_HELDOUT_CREATED",
            "wake": 4,
            "nonwake": 12,
            "all_same_windows_heami_speaker": True,
            "independent_human_voice_accuracy_proven": False,
            "robot_mic_accessed": False,
            "cloud_tts_or_openai_used": False,
            "evaluate_after_freeze_only": True,
        }
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = create_fresh_holdout(args.output)
        code = 0
    except (ValueError, OSError):
        report = {"status": "FRESH_LOCAL_TTS_FAILED", "device_install_authorized": False}
        code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
