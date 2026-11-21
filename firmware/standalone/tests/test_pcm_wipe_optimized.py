"""Check that discarded PCM is still overwritten at -O2, including rejection."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1] / "core"


def compile_assembly(tmp_path, source, include):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++20 compiler required")
    path = tmp_path / "erase.cpp"
    path.write_text(source)
    asm = tmp_path / "erase.s"
    result = subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-O2",
            "-S",
            "-masm=intel",
            "-I",
            str(include),
            "-I",
            str(CORE),
            str(path),
            "-o",
            str(asm),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return asm.read_text()


def zero_store(assembly):
    return re.search(r"\bmov\w*\s+(?:BYTE|WORD) PTR[^\n]*,\s*0\b", assembly, re.I) is not None


SOURCE = """
#include <algorithm>
#include <array>
#include "audio_wipe.hpp"
extern "C" void discard_pcm() {
  std::array<int16_t,8> pcm{};
  stackchan::standalone::ScopedPcmWipe clear{pcm};
  pcm.fill(123);
}
"""


def test_scoped_wipe_survives_optimization(tmp_path):
    assert zero_store(compile_assembly(tmp_path, SOURCE, CORE))


def test_ordinary_fill_negative_control_is_elided(tmp_path):
    # Same destructor with an ordinary fill must demonstrate the test's value.
    header = (
        (CORE / "audio_wipe.hpp")
        .read_text()
        .replace(
            "~ScopedPcmWipe() { wipe_pcm(pcm_); }",
            "~ScopedPcmWipe() { std::fill(pcm_.begin(), pcm_.end(), 0); }",
        )
    )
    assert "std::fill(pcm_.begin()" in header
    (tmp_path / "audio_wipe.hpp").write_text(header)
    assert not zero_store(compile_assembly(tmp_path, SOURCE, tmp_path))


def test_invalid_frame_wipe_survives_optimization(tmp_path):
    source = """
    #include <array>
    #include "pcm_frame.hpp"
    extern "C" bool reject_pcm() {
      std::array<int16_t,8> pcm{};
      pcm.fill(123);
      return stackchan::standalone::extract_k151_mic0({},pcm);
    }
    """
    assert zero_store(compile_assembly(tmp_path, source, CORE))
