"""Host-only contrastive wake experiment. No formerly exposed eval WAVs.

Training negative bank: original 10 calibration nonwake + first 8 newly
synthesized near-word calibration clips; development probes: 5 original
calibration wake clips and remaining 8 new near-word clips. Human inference,
false-wakes/hour, and ESP32-S3 deployment are NOT tested.
"""

import argparse
import json
import tempfile
from pathlib import Path

from evaluate_synthetic_robustness import CONDITIONS, _write_pcm_wav, perturb
from experiment_wake_trim_calibration import (
    ROOT,
    _compile,
    _counts,
    _run,
    calibration_only_records,
)
from scfg_offline import validate_profile
from wake_corpus_audit import MAX_WAV_BYTES, _decode_canonical_wav, _read_bounded

HARDNEG = ROOT / "fixtures" / "korean_heami_hardneg_20261120"
OLD_PROFILE = (
    ROOT / "fixtures" / "korean_heami_fresh_holdout_20261120" / "robust_trim_aug_frozen.swk1"
)
BANK_FIRST_N = 8
NONWAKE_MARGIN = 2.0
DEVELOPMENT_NEG_PROBES = 8


def private_hardneg(path: Path) -> tuple[list[dict], list[dict]]:
    manifest = path / "hard-negative-calibration.json"
    data = json.loads(_read_bounded(manifest, 65536).decode("utf-8"))
    if set(data) != {"kind", "labels"} or data["kind"] != (
        "synthetic_heami_nonwake_calibration_only_v1"
    ):
        raise RuntimeError("invalid_synthetic_hardneg_plan")
    source = []
    for item in data["labels"]:
        if set(item) != {"file", "label", "role"} or (
            item["label"] != "nonwake" or item["role"] != "calibration"
        ):
            raise RuntimeError("not_a_calibration_negative")
        relative = Path(item["file"])
        if ".." in relative.parts or relative.is_absolute():
            raise RuntimeError("unsafe_training_path")
        wav = _read_bounded(path / relative, MAX_WAV_BYTES)
        source.append(
            {
                "id": relative.stem,
                "pcm": _decode_canonical_wav(wav),
            }
        )
    if len(source) != 16 or BANK_FIRST_N != 8:
        raise RuntimeError("incorrect_hardnegative_split")
    return source[:BANK_FIRST_N], source[BANK_FIRST_N:]


def experiment(hardneg: Path = HARDNEG, profile: Path = OLD_PROFILE) -> dict:
    if validate_profile(profile.read_bytes()) != 3:
        raise RuntimeError("unexpected_frozen_positive_profile")
    original = calibration_only_records()  # excludes evaluation folders
    new_bank, new_probe = private_hardneg(hardneg)

    with tempfile.TemporaryDirectory(prefix="stackchan-contrastive-host-") as tmp:
        folder = Path(tmp)
        baseline = folder / "baseline.exe"
        contrastive = folder / "contrastive.exe"
        _compile("wake_wav_eval.cpp", baseline, trim=True)
        _compile("wake_contrastive_eval.cpp", contrastive, trim=True)

        bank = original["negative"] + new_bank
        if len(bank) != 18 or len(new_probe) != DEVELOPMENT_NEG_PROBES:
            raise RuntimeError("invalid_development_inputs")
        bank_paths = []
        for item in bank:
            path = folder / f"bank_{item['id']}.wav"
            _write_pcm_wav(path, item["pcm"])
            bank_paths.extend(["--calibration-negative", str(path)])

        conditions = {}
        for condition in CONDITIONS:
            probes = []
            for source, flag in (
                (original["positive"], "--positive"),
                (new_probe, "--negative"),
            ):
                for item in source:
                    path = folder / f"{condition}_{item['id']}.wav"
                    _write_pcm_wav(path, perturb(item["pcm"], condition, item["id"]))
                    probes.extend([flag, str(path)])
            result = {}
            for name, executable, inputs in (
                ("positive_profile_only", baseline, probes),
                ("contrastive_filter", contrastive, bank_paths + probes),
            ):
                try:
                    response = _run(executable, [str(profile), *inputs])
                    if name == "contrastive_filter":
                        response = response.replace(
                            "UNVERIFIED_CALIBRATION_ONLY_CONTRASTIVE_WAKE",
                            "UNVERIFIED_USER_LABELED_WAKE_EVALUATION",
                            1,
                        )
                    result[name] = _counts(response)
                    if name == "contrastive_filter":
                        values = {}
                        for field in (
                            "min_wake_margin_ratio_x1000",
                            "max_false_wake_margin_ratio_x1000",
                        ):
                            matching = [
                                row for row in response.splitlines() if row.startswith(field + "=")
                            ]
                            if len(matching) != 1:
                                raise RuntimeError("missing_contrastive_margin_diagnostic")
                            values[field] = int(matching[0].split("=", 1)[1])
                        result[name]["development_margin_diagnostics"] = values
                except RuntimeError:
                    result[name] = {"status": "fail_closed_without_counts"}
            conditions[condition] = result

        return {
            "status": "SYNTHETIC_CONTRASTIVE_CALIBRATION_ONLY",
            "positive_profile_unchanged": True,
            "fixed_margin_ratio": NONWAKE_MARGIN,
            "bank_old_calibration_nonwake": len(original["negative"]),
            "bank_new_nonwake": len(new_bank),
            "development_wake": len(original["positive"]),
            "development_nonwake": len(new_probe),
            "some_phrases_exposed_in_prior_experiments": True,
            "evaluation_files_opened": False,
            "new_independent_human_evaluation": False,
            "original_firmware_modified": False,
            "physical_robot_accessed": False,
            "candidate_deployment_authorized": False,
            "conditions": conditions,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hardneg", type=Path, default=HARDNEG)
    args = parser.parse_args()
    try:
        data = experiment(args.hardneg)
        code = 0
    except (OSError, ValueError, RuntimeError):
        data = {
            "status": "CONTRASTIVE_CALIBRATION_REJECTED",
            "evaluation_files_opened": False,
            "candidate_deployment_authorized": False,
        }
        code = 2
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
