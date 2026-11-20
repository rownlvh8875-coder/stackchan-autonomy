"""Real portable C++ stream/session tests; synthetic PCM and fake external ports."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("C++20 host compiler required; Linux CI provides it")
    results = {}
    for name in ["stream_resampler", "native_wake_controller", "builtin_admission"]:
        binary = tmp_path_factory.mktemp(name) / name
        result = subprocess.run(
            [
                compiler,
                "-std=c++20",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pedantic",
                "-I",
                str(BASE / "core"),
                str(BASE / "tests" / (name + "_test.cpp")),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        results[name] = binary, result
    return results


@pytest.mark.parametrize(
    "case",
    [
        "admission_valid",
        "admission_default_closed",
        "admission_gates",
        "admission_epoch",
        "admission_cancel",
        "admission_reboot",
        "admission_fatal",
        "count_dc",
        "batch_reference",
        "anti_alias",
        "history_reset",
        "invalid_reset",
        "saturation",
        "turn",
        "cloud_off",
        "guard_stop",
        "guard_consent",
        "guard_speaker",
        "missing_model",
        "bad_format",
        "chunking",
        "large_chunk",
        "late_read_stop",
        "late_read_consent",
        "late_read_speaker",
        "late_detect_stop",
        "late_detect_consent",
        "late_detect_speaker",
        "io_failure",
        "model_error",
        "unknown_model_result",
        "close_failure",
        "reset_failure",
        "format_change",
        "gap",
        "clock_rollback",
        "resume_between_polls",
        "resume_in_read",
        "resume_in_detect",
        "first_read_format",
        "inactive_lifetime",
        "active_destruction",
    ],
)
def test_native_wake_case(built, case):
    dsp = {
        "count_dc",
        "batch_reference",
        "anti_alias",
        "history_reset",
        "invalid_reset",
        "saturation",
    }
    name = (
        "builtin_admission"
        if case.startswith("admission_")
        else ("stream_resampler" if case in dsp else "native_wake_controller")
    )
    binary, result = built[name]
    assert result.returncode == 0, result.stderr
    completed = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


def test_optimized_fir_discard_emits_zero_stores(tmp_path):
    """The real destructor must erase PCM even when no caller reads it again."""
    import platform
    import re

    compiler = shutil.which("g++")
    if not compiler or platform.machine().lower() not in {"x86_64", "amd64"}:
        pytest.skip("GCC x86-64 assembly check; functional DSP cases remain portable")
    source = tmp_path / "discard.cpp"
    assembly = tmp_path / "discard.s"
    source.write_text(
        '#include "stream_resampler.hpp"\n'
        'extern "C" void discard_fir(stackchan::standalone::StreamingPcm24To16* p) {'
        "p->~StreamingPcm24To16();}\n"
    )
    subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-S",
            "-I",
            str(BASE / "core"),
            str(source),
            "-o",
            str(assembly),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    text = assembly.read_text()
    body = text.split("discard_fir:", 1)[1].split(".size", 1)[0]
    # Inspect emitted code, not source text. Old ordinary fill compiles to ret.
    immediate_zero = re.search(r"mov[bw]\s+\$0,\s*(?:\d+)?\(", body)
    zero_registers = re.findall(r"xor[lq]\s+%(e[a-z]+),\s*%\1", body)
    word_alias = {"eax": "ax", "ebx": "bx", "ecx": "cx", "edx": "dx", "esi": "si", "edi": "di"}
    register_zero = any(
        re.search(r"movw\s+%" + word_alias[r] + r",\s*(?:\d+)?\(", body)
        for r in zero_registers
        if r in word_alias
    )
    assert immediate_zero or register_zero, body
