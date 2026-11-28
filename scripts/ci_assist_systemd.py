"""Rehearse the Assist units under the disposable Linux CI machine's systemd."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROLES = ("voice", "conversation")
KEY = "synthetic-systemd-fixture"


def command(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=40)


def systemctl(*args, check=True):
    return command("systemctl", *args, check=check).stdout.strip()


def wait_for(description, predicate):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {description}")


def worker(role):
    from stackchan_autonomy import ha_host, ha_voice
    from stackchan_autonomy.budget import SQLiteRequestBudget

    async def serve(settings, *_):
        assert settings.api_key.get_secret_value() == KEY
        assert settings.budget_require_existing
        budget = SQLiteRequestBudget(settings)
        admitted = sum(budget.reserve(100) for _ in range(6)) if role == "voice" else 0
        marker = settings.state_path.with_name(role + ".json")
        pending = marker.with_suffix(".tmp")
        pending.write_text(json.dumps({"pid": os.getpid(), "admitted": admitted}))
        pending.replace(marker)
        await asyncio.Event().wait()

    if role == "voice":
        ha_voice.serve = serve
    else:
        from stackchan_autonomy import ha_conversation

        ha_conversation.serve = serve
    return ha_host.main([role])


def rehearse(root: Path, uid: int, gid: int):
    if (
        os.getuid() != 0
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or uid <= 0
        or gid <= 0
        or root.parent != Path("/opt")
        or not root.name.startswith("stackchan-assist-ci.")
    ):
        raise SystemExit("Expected the disposable Linux CI test directory and worker account")

    name = root.name
    unit_dir = Path("/run/systemd/system")
    state = Path("/var/lib") / name
    database = state / "budget.sqlite3"
    target = name + ".target"
    template = name + "@.service"
    services = {role: f"{name}@{role}.service" for role in ROLES}
    source = Path(__file__).resolve().parents[1] / "config/home_assistant/systemd"
    credential = root / "openai-key"
    settings = root / "settings.env"
    fixture = root / "worker.py"
    python = root / "venv/bin/python"

    credential.write_text(KEY)
    credential.chmod(0o600)
    settings.write_text(
        (source / "settings.env.example")
        .read_text()
        .replace("=false", "=true")
        .replace("STACKCHAN_OPENAI_MODEL=\n", "STACKCHAN_OPENAI_MODEL=synthetic-model\n")
        .replace("/var/lib/stackchan-assist/", f"{state}/")
    )
    shutil.copyfile(__file__, fixture)
    service_text = (
        (source / "stackchan-assist@.service")
        .read_text()
        .replace("User=stackchan-assist", f"User={uid}")
        .replace("Group=stackchan-assist", f"Group={gid}")
        .replace("stackchan-assist", name)
        .replace(f"/etc/{name}/settings.env", str(settings))
        .replace(f"/etc/{name}/openai-key", str(credential))
        .replace(
            "/opt/stackchan/venv-%i/bin/python -B -m stackchan_autonomy.ha_host %i",
            f"{python} -B {fixture} worker %i",
        )
    )

    def ready(role, previous=0):
        marker = state / (role + ".json")

        def current():
            if not marker.is_file():
                return None
            report = json.loads(marker.read_text())
            actual = systemctl("show", "-p", "MainPID", "--value", services[role])
            if report["pid"] != previous and str(report["pid"]) == actual:
                return report
            return None

        return wait_for(f"{role} worker readiness", current)

    def provision():
        result = command(
            "systemd-run",
            "--pipe",
            "--collect",
            "-p",
            f"User={uid}",
            "-p",
            f"Group={gid}",
            "-p",
            f"StateDirectory={name}",
            "-p",
            "StateDirectoryMode=0700",
            "-p",
            "UMask=0077",
            "-p",
            f"EnvironmentFile={settings}",
            str(python),
            "-B",
            "-m",
            "stackchan_autonomy.ha_host",
            "initialize-budget",
        )
        assert result.stdout.strip() == "HA_HOST_BUDGET_INITIALIZED"

    if state.exists() or any((unit_dir / unit).exists() for unit in (target, template)):
        raise SystemExit("Test paths must start empty")
    try:
        provision()
        (unit_dir / template).write_text(service_text + "RestrictAddressFamilies=AF_UNIX\n")
        (unit_dir / target).write_text(
            (source / "stackchan-assist.target").read_text().replace("stackchan-assist", name)
        )
        systemctl("enable", "--runtime", "--now", target)
        assert systemctl("is-enabled", target) == "enabled-runtime"
        assert (unit_dir / "multi-user.target.wants" / target).is_symlink()
        initial = {role: ready(role) for role in ROLES}
        assert initial["voice"]["admitted"] == 6
        print("PASS boot target registered and both synthetic workers started", flush=True)

        systemctl("kill", "--kill-whom=main", "--signal=SIGKILL", services["voice"])
        restarted = ready("voice", initial["voice"]["pid"])
        assert restarted["admitted"] == 0
        assert int(systemctl("show", "-p", "NRestarts", "--value", services["voice"])) >= 1
        print("PASS worker auto-restarted with its original budget limit", flush=True)

        systemctl("restart", target)
        assert ready("voice", restarted["pid"])["admitted"] == 0
        ready("conversation", initial["conversation"]["pid"])
        systemctl("stop", target)
        for unit in services.values():
            assert systemctl("is-active", unit, check=False) == "inactive"
        print("PASS target restarted and stopped both workers", flush=True)

        saved = database.with_suffix(".held")
        database.rename(saved)
        systemctl("reset-failed", *services.values())
        systemctl("start", target)
        for unit in services.values():
            wait_for(
                f"{unit} storage failure",
                lambda: systemctl("show", "-p", "ActiveState", "--value", unit) == "failed",
            )
            assert systemctl("show", "-p", "ExecMainStatus", "--value", unit) == "2"
            assert systemctl("show", "-p", "NRestarts", "--value", unit) == "0"
        assert not database.exists()
        systemctl("stop", target)
        saved.rename(database)
        systemctl("reset-failed", *services.values())
        systemctl("start", target)
        assert ready("voice", restarted["pid"])["admitted"] == 0
        ready("conversation", initial["conversation"]["pid"])
        print("PASS lost budget stopped both workers and restoring it kept the limit", flush=True)
    except Exception:
        diagnostic = command(
            "journalctl",
            "--no-pager",
            "-n",
            "50",
            "-u",
            services["voice"],
            "-u",
            services["conversation"],
            check=False,
        )
        print(diagnostic.stdout, file=sys.stderr)
        raise
    finally:
        systemctl("disable", "--runtime", "--now", target, check=False)
        systemctl("stop", *services.values(), check=False)
        for unit in (target, template):
            (unit_dir / unit).unlink(missing_ok=True)
        systemctl("daemon-reload")
        if state.exists():
            shutil.rmtree(state)


if __name__ == "__main__":
    if sys.argv[1] == "worker":
        raise SystemExit(worker(sys.argv[2]))
    rehearse(Path(sys.argv[1]).resolve(), int(sys.argv[2]), int(sys.argv[3]))
