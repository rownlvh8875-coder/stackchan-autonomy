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
    # Controlled input-free probes only: GCC can zero a register then store its
    # low word, whereas Clang often emits a literal-zero store. Track aliases
    # and invalidation so an unrelated/overwritten zero register is not proof.
    aliases = {}
    for family, names in enumerate(
        [
            "rax eax ax al ah",
            "rbx ebx bx bl bh",
            "rcx ecx cx cl ch",
            "rdx edx dx dl dh",
            "rsi esi si sil",
            "rdi edi di dil",
            "rbp ebp bp bpl",
            "rsp esp sp spl",
            *[f"r{i} r{i}d r{i}w r{i}b" for i in range(8, 16)],
        ]
    ):
        for name in names.split():
            if name.endswith("h"):
                mask = 0xFF00
            elif name.endswith("l") or name.endswith("b"):
                mask = 0xFF
            elif len(name) == 2 or name.endswith("w"):
                mask = 0xFFFF
            else:
                mask = (1 << 64) - 1  # 32-bit register writes zero-extend on x86-64.
            aliases[name] = (family, mask)
    known_zero = {}
    for raw in assembly.lower().splitlines():
        line = raw.split("#", 1)[0].strip()
        if re.fullmatch(r"[a-z_]\w*:", line):
            known_zero.clear()
        match = re.match(r"(\w+)\s+(.+?),\s*(.+)$", line)
        if not match:
            if line.startswith("call"):
                known_zero.clear()
            continue
        op, dest, source = match.groups()
        if op == "mov" and re.match(r"(?:byte|word) ptr\b", dest):
            source_reg = aliases.get(source)
            if source == "0" or (
                source_reg and known_zero.get(source_reg[0], 0) & source_reg[1] == source_reg[1]
            ):
                return True
        dest_reg = aliases.get(dest)
        if dest_reg is None or op in {"cmp", "test"}:
            continue
        family, mask = dest_reg
        source_reg = aliases.get(source)
        is_zero = (op in {"xor", "sub"} and dest == source) or (
            op == "mov"
            and (
                source == "0"
                or (
                    source_reg and known_zero.get(source_reg[0], 0) & source_reg[1] == source_reg[1]
                )
            )
        )
        if is_zero:
            known_zero[family] = known_zero.get(family, 0) | mask
        else:
            known_zero[family] = 0
    return False


@pytest.mark.parametrize(
    "assembly,expected",
    [
        ("xor edx, edx\nmov WORD PTR [rax], dx", True),
        ("mov edx, 0\nmov BYTE PTR [rax], dl", True),
        ("xor edx, edx\nmov edx, 7\nmov WORD PTR [rax], dx", False),
        ("xor eax, eax\nmov WORD PTR [rax], dx", False),
        ("mov WORD PTR [rax], 7", False),
        ("xor dl, dl\nmov WORD PTR [rax], dx", False),
    ],
)
def test_zero_register_store_proof(assembly, expected):
    assert zero_store(assembly) is expected


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
    assembly = compile_assembly(tmp_path, SOURCE, CORE)
    assert zero_store(assembly), assembly


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
    assembly = compile_assembly(tmp_path, source, CORE)
    assert zero_store(assembly), assembly
