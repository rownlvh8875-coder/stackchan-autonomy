"""Install the built wheel independently and exercise offline CLI modes on any OS."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command, *, cwd, env):
    return subprocess.run(
        [str(arg) for arg in command],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    ).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, default=Path(".local/ci/dist"))
    parser.add_argument("--require-opus", action="store_true")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    wheels = list((project / args.wheel_dir).glob("stackchan_autonomy-*.whl"))
    if len(wheels) != 1:
        parser.error("build exactly one project wheel in --wheel-dir first")
    uv = shutil.which("uv")
    if uv is None:
        parser.error("uv is required")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("STACKCHAN_")
        and key
        not in {
            "OPENAI_API_KEY",
            "PYTHONPATH",
            "PYTHONHOME",
            "VIRTUAL_ENV",
            "UV_PROJECT",
            "UV_PROJECT_ENVIRONMENT",
        }
    }
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    with tempfile.TemporaryDirectory(prefix="stackchan wheel ") as directory:
        root = Path(directory)
        requirements = root / "requirements.txt"
        run(
            [
                uv,
                "export",
                "--frozen",
                "--no-dev",
                "--no-emit-project",
                "--output-file",
                requirements,
            ],
            cwd=project,
            env=env,
        )
        venv = root / "venv"
        run([uv, "venv", "--python", sys.executable, venv], cwd=root, env=env)
        binaries = venv / ("Scripts" if os.name == "nt" else "bin")
        python = binaries / ("python.exe" if os.name == "nt" else "python")
        cli = binaries / ("stackchan-autonomy.exe" if os.name == "nt" else "stackchan-autonomy")
        run(
            [uv, "pip", "install", "--python", python, "--require-hashes", "-r", requirements],
            cwd=root,
            env=env,
        )
        run(
            [uv, "pip", "install", "--python", python, "--no-deps", wheels[0].resolve()],
            cwd=root,
            env=env,
        )
        probe = run(
            [
                python,
                "-I",
                "-c",
                "import json,sys; from pathlib import Path; import stackchan_autonomy as m; "
                "from stackchan_autonomy.opus_codec import opus_available; "
                "assert Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()); "
                "print(json.dumps({'opus': opus_available()}))",
            ],
            cwd=root,
            env=env,
        )
        opus = json.loads(probe)["opus"]
        if args.require_opus and not opus:
            raise RuntimeError("required native libopus is unavailable in the installed wheel")
        modes = [("mock", False), ("mcp-sim", False), ("voice-sim", False)]
        if opus:
            modes.append(("voice-sim", True))
        else:
            print("SKIP native Opus smoke: trusted system libopus unavailable", flush=True)
        for index, (mode, use_opus) in enumerate(modes):
            child_env = env | {
                "STACKCHAN_STATE_PATH": str(root / f"state-{index}.sqlite3"),
                "STACKCHAN_CLOUD_ENABLED": "false",
                "STACKCHAN_AUDIO_TRANSMISSION": "false",
                "STACKCHAN_IMAGE_TRANSMISSION": "false",
                "STACKCHAN_HARDWARE_ENABLED": "false",
                "STACKCHAN_DRY_RUN": "true",
            }
            command = [cli, "--mode", mode, "--cycles", "1", "--event", "touch"]
            if use_opus:
                command.append("--opus")
            summary = json.loads(run(command, cwd=root, env=child_env))
            expected = {
                "mode": mode,
                "cycles": 1,
                "state": "IDLE",
                "simulated_actions": 1,
                "cloud_requests": 0,
            }
            if mode == "voice-sim":
                expected.update(audio_captures=1, audio_playbacks=1)
            if any(summary.get(key) != value for key, value in expected.items()):
                raise RuntimeError(f"installed {mode} CLI failed its offline smoke contract")
            if mode == "voice-sim" and bool(summary.get("opus_packets")) != use_opus:
                raise RuntimeError("installed voice CLI did not exercise the requested codec")
            print(json.dumps(summary), flush=True)
        memory_cli = binaries / ("stackchan-memory.exe" if os.name == "nt" else "stackchan-memory")
        memory_env = child_env | {
            "STACKCHAN_MEMORY_PATH": str(root / "memory.sqlite3"),
            "STACKCHAN_STATE_PATH": str(root / "memory-control.sqlite3"),
        }
        configured = json.loads(
            run(
                [
                    memory_cli,
                    "set",
                    "--automatic-speech",
                    "off",
                    "--minimum-speech-interval",
                    "600",
                ],
                cwd=root,
                env=memory_env,
            )
        )
        if configured["preferences"] != {
            "automatic_speech_enabled": False,
            "minimum_speech_interval_s": 600,
        }:
            raise RuntimeError("installed memory CLI did not persist preferences")

        def autonomy(*flags):
            return json.loads(run([cli, "--cycles", "1", *flags], cwd=root, env=memory_env))

        blocked = autonomy("--person")
        if blocked["simulated_actions"] != 0 or blocked["cloud_requests"] != 0:
            raise RuntimeError("installed engine ignored automatic speech preference")
        touched = autonomy("--event", "touch")
        if touched["simulated_actions"] != 1 or touched["cloud_requests"] != 0:
            raise RuntimeError("installed engine lost explicit interaction capability")
        run([memory_cli, "set", "--automatic-speech", "on"], cwd=root, env=memory_env)
        restarted = autonomy("--person")
        retained = json.loads(run([memory_cli, "show"], cwd=root, env=memory_env))
        if (
            restarted["simulated_actions"] != 0
            or restarted["cloud_requests"] != 0
            or retained["recent"][-1]["result"] != "speech_cooldown"
        ):
            raise RuntimeError("installed engine lost speech cooldown across process restart")
        cleared = json.loads(run([memory_cli, "clear"], cwd=root, env=memory_env))
        if cleared["recent"] or cleared["last_spoken_at"] is not None:
            raise RuntimeError("installed memory CLI did not clear scoped metadata")
        print("Optional memory CLI / persisted preferences / restart cooldown: PASS", flush=True)
        soak_cli = binaries / ("stackchan-soak.exe" if os.name == "nt" else "stackchan-soak")
        soak = json.loads(
            run(
                [
                    soak_cli,
                    "--cycles",
                    "30",
                    "--warmup-cycles",
                    "5",
                    "--restart-every",
                    "10",
                    "--virtual-step-s",
                    "30",
                ],
                cwd=root,
                env=env,
            )
        )
        if (
            not soak["passed"]
            or soak["cycles"] != 30
            or soak["virtual_elapsed_s"] != 900
            or soak["restarts"] != 2
            or soak["remaining_tasks"] != 0
            or soak["cloud_requests"] != 0
        ):
            raise RuntimeError("installed soak entry point failed the bounded offline contract")
        print("Isolated installed soak entry point / restart checks: PASS", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(error.stdout, file=sys.stderr)
        print(error.stderr, file=sys.stderr)
        raise SystemExit(error.returncode) from None
