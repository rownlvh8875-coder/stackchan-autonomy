"""Generate Korean wake-phrase TTS examples with LOCAL Windows SAPI only.

Never uses a microphone, network, cloud TTS, hardware or live voice enrollment.
Every output is clearly synthetic, one installed voice, never personal speech.
Run only with explicit --output to a NEW private directory outside this repo.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

VOICE = "Microsoft Heami Desktop"
SCHEMA = "stackchan-private-wake-corpus-v1"
DEFAULT_WAKE_PHRASE = "조수"
SUPPORTED_WAKE_PHRASES = ("조수", "조수야")


def voice_plan(wake_phrase: str = DEFAULT_WAKE_PHRASE):
    """A new phrase requires NEW WAVs and a NEW acoustic profile."""
    if wake_phrase not in SUPPORTED_WAKE_PHRASES:
        raise ValueError("unsupported_wake_phrase")
    entries = [("enrollment", "wake", wake_phrase, 0)]
    entries += [("calibration", "wake", wake_phrase, rate) for rate in (-3, -2, -1, 1, 2)]
    entries += [
        ("calibration", "nonwake", phrase, rate)
        for phrase, rate in (
            ("조수야" if wake_phrase == "조수" else "조수", 0),
            ("조용히 해", -1),
            ("조수님", 2),
            ("주스야", -2),
            ("도와줘", 1),
            ("안녕", 0),
            ("지금 몇 시야", 1),
            ("조수석", -1),
            ("수고했어", 0),
            ("작업 시작해", 2),
        )
    ]
    entries += [("evaluation", "wake", wake_phrase, rate) for rate in (3, 4)]
    entries += [
        ("evaluation", "nonwake", phrase, rate)
        for phrase, rate in (
            ("조심해", 1),
            ("주스 줘", 2),
            ("저기요", 0),
            ("조수야" if wake_phrase == "조수" else "조선아", -2),
            ("준수야", 1),
            ("소주야", -1),
        )
    ]
    return entries


def _synthesize_raw(raw_dir: Path, specs: list[dict]) -> None:
    records = [
        {"text": spec["text"], "rate": spec["rate"], "path": str(raw_dir / (spec["name"] + ".wav"))}
        for spec in specs
    ]
    encoded = base64.b64encode(json.dumps(records, ensure_ascii=False).encode()).decode()
    ps_script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{
    $voice.SelectVoice('{VOICE}')
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
       24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
       [System.Speech.AudioFormat.AudioChannel]::Mono)
    $items = ConvertFrom-Json -InputObject ([System.Text.Encoding]::UTF8.GetString(
        [System.Convert]::FromBase64String('{encoded}')))
    foreach ($item in $items) {{
        $voice.Rate = [int]$item.rate
        $voice.Volume = 100
        $voice.SetOutputToWaveFile([string]$item.path, $format)
        try {{ $voice.Speak([string]$item.text) }}
        finally {{ $voice.SetOutputToNull() }}
    }}
}} finally {{ $voice.Dispose() }}
Write-Output 'LOCAL_KOREAN_SAPI_GENERATION_FINISHED'
"""
    command = base64.b64encode(ps_script.encode("utf-16le")).decode()
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
            capture_output=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("local_sapi_not_available") from exc
    if result.returncode != 0:
        raise ValueError("local_sapi_synthesis_failed")


def _canonicalize(raw: Path, output: Path) -> None:
    try:
        with wave.open(str(raw), "rb") as source:
            params = source.getparams()
            if (
                params.nchannels != 1
                or params.sampwidth != 2
                or params.framerate != 24000
                or params.comptype != "NONE"
                or not 2400 <= params.nframes <= 72000
            ):
                raise ValueError("unsupported_tts_wave_format")
            pcm = source.readframes(params.nframes)
        with output.open("xb") as destination:
            with wave.open(destination, "wb") as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(24000)
                target.writeframes(pcm)
    except (OSError, wave.Error) as exc:
        raise ValueError("invalid_synthesized_wav") from exc


def generate(output: Path, *, wake_phrase: str = DEFAULT_WAKE_PHRASE) -> dict:
    plan = voice_plan(wake_phrase)
    if os.name != "nt":
        raise ValueError("windows_sapi_required")
    repo = Path(__file__).resolve().parents[3]
    target = output.resolve()
    if target == repo or repo in target.parents:
        raise ValueError("private_output_must_be_outside_repo")
    if target.exists() or output.is_symlink():
        raise ValueError("output_directory_already_exists")

    output.mkdir(parents=False, mode=0o700, exist_ok=False)
    try:
        spec = []
        counts = {}
        for stage, label, phrase, rate in plan:
            key = f"{stage}_{label}"
            counts[key] = counts.get(key, 0) + 1
            number = counts[key]
            basename = f"{stage}_{label}_{number:02}"
            spec.append(
                {
                    "name": basename,
                    "stage": stage,
                    "label": label,
                    "text": phrase,
                    "rate": rate,
                    "session": "sapi_" + stage,
                    "file": f"{stage}/{basename}.wav",
                }
            )
        with tempfile.TemporaryDirectory(dir=output, prefix="sapi-raw-") as raw:
            _synthesize_raw(Path(raw), spec)
            for row in spec:
                path = output / row["file"]
                path.parent.mkdir(exist_ok=True)
                _canonicalize(Path(raw) / (row["name"] + ".wav"), path)
        corpus = {
            "schema": SCHEMA,
            "samples": [
                {
                    "id": row["name"],
                    "stage": row["stage"],
                    "label": row["label"],
                    "session": row["session"],
                    "file": row["file"],
                }
                for row in spec
            ],
        }
        manifest = output / "synthetic-sapi.wake-corpus.json"
        with manifest.open("x", encoding="utf-8") as dest:
            json.dump(corpus, dest, indent=2, ensure_ascii=False)
            dest.write("\n")
        return {
            "status": "LOCAL_SYNTHETIC_KOREAN_TTS_GENERATED",
            "voice": VOICE,
            "wake_phrase": wake_phrase,
            "counts": counts,
            "synthetic_only": True,
            "independent_speakers_or_sessions_proven": False,
            "actual_korean_recognition_accuracy_proven": False,
            "network_or_paid_api_used": False,
            "robot_or_microphone_accessed": False,
            "file_paths_printed": False,
        }
    except Exception:
        # Destination was newly created by us; no unrelated files are removed.
        shutil.rmtree(output, ignore_errors=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", required=True, type=Path, help="NEW private directory outside Git checkout"
    )
    parser.add_argument(
        "--wake-phrase", choices=SUPPORTED_WAKE_PHRASES, default=DEFAULT_WAKE_PHRASE
    )
    args = parser.parse_args(argv)
    try:
        report = generate(args.output, wake_phrase=args.wake_phrase)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "status": "KOREAN_TTS_GENERATION_FAILED",
                    "network_or_paid_api_used": False,
                    "robot_or_microphone_accessed": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
