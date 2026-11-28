"""Use real host-side PSA and production pairing code with synthetic credentials."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

host_exe = os.getenv("STACKCHAN_SCPS_PSA_HOST_EXE")
if not host_exe:
    pytest.skip("native PSA pairing test binary was not supplied", allow_module_level=True)
pytest.importorskip("cryptography")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from scps_reference import PcSession  # noqa: E402


@pytest.mark.parametrize(
    "case", ["normal", "maximum", "tampered", "expired", "stop", "unconfirmed"]
)
async def test_real_cpp_device_and_python_pc_agree_on_pairing(case, tmp_path):
    executable = Path(host_exe).resolve(strict=True)
    device = await asyncio.create_subprocess_exec(
        str(executable),
        case,
        cwd=tmp_path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        hello = await asyncio.wait_for(device.stdout.readline(), 8)
        pc = PcSession(bytes.fromhex(hello.decode("ascii")))
        device.stdin.write(pc.pc_hello.hex().encode("ascii") + b"\n")
        await device.stdin.drain()
        sas = await asyncio.wait_for(device.stdout.readline(), 8)
        assert sas.strip().decode("ascii") == pc.sas

        if case == "maximum":
            ssid, password, key = b"Z" * 32, "A" * 64, "z" * 220
        else:
            ssid, password, key = (
                b"scps-test-network",
                "scps-test-passphrase",
                "scps-test-token-only",
            )
        sealed = pc.seal(ssid, password, key, sas.strip().decode("ascii"), True)
        if case == "tampered":
            sealed = sealed[:-1] + bytes([sealed[-1] ^ 1])
        output, errors = await asyncio.wait_for(
            device.communicate(sealed.hex().encode("ascii") + b"\n"), 8
        )
        assert device.returncode == 0
        assert not errors
        expected = b"accepted once" if case in ("normal", "maximum") else b"rejected"
        assert output.strip() == expected
    finally:
        if device.returncode is None:
            device.kill()
            await device.wait()
