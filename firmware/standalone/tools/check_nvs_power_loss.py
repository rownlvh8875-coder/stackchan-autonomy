"""Run the pinned NVS SDK on synthetic RAM flash, with no device or credentials."""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

# Supply only the platform interfaces absent in the host compiler. The flash
# recovery logic, page management and ROM CRC implementation come from IDF.
HOST_HEADERS = {
    "sdkconfig.h": "#pragma once\n",
    "spi_flash_mmap.h": "#pragma once\n#define ESP_ERR_FLASH_OP_FAIL (ESP_ERR_FLASH_BASE + 1)\n",
    "esp_log.h": "#pragma once\n"
    + "".join(f"#define ESP_LOG{level}(...) ((void)0)\n" for level in "DVEWI"),
    "host_string.h": """\
#pragma once
#include <cstring>
#if __has_include(<bsd/string.h>)
#include <bsd/string.h>
#endif
inline std::size_t nvs_host_strlcpy(char* dest, const char* src, std::size_t capacity) {
  const std::size_t length = std::strlen(src);
  if (capacity) {
    const auto copied = length < capacity ? length : capacity - 1;
    std::memcpy(dest, src, copied);
    dest[copied] = 0;
  }
  return length;
}
#define strlcpy nvs_host_strlcpy
""",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idf", type=Path, required=True)
    parser.add_argument("--page-source", type=Path, required=True)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    executable = shutil.which(args.cxx)
    if not executable:
        parser.error("a host C++ compiler is required")
    compiler = str(Path(executable).resolve())

    components = args.idf.resolve() / "components"
    nvs = components / "nvs_flash"
    sources = (
        "nvs_pagemanager.cpp",
        "nvs_storage.cpp",
        "nvs_types.cpp",
        "nvs_item_hash_list.cpp",
    )
    with tempfile.TemporaryDirectory(prefix="k151-nvs-") as directory:
        work = Path(directory)
        for name, contents in HOST_HEADERS.items():
            (work / name).write_text(contents, encoding="utf-8")
        crc = work / "crc.o"
        binary = work / "nvs_power_loss.exe"
        rom = components / "esp_rom"
        subprocess.run(
            [
                compiler,
                "-O2",
                "-x",
                "c",
                "-I",
                str(rom / "include"),
                "-c",
                str(rom / "linux/esp_rom_crc.c"),
                "-o",
                str(crc),
            ],
            check=True,
            timeout=90,
        )
        includes = [
            work,
            nvs / "include",
            nvs / "private_include",
            nvs / "src",
            components / "esp_common/include",
            rom / "include",
            BASE / "core",
        ]
        subprocess.run(
            [
                compiler,
                "-std=c++20",
                "-O2",
                # The TEE allocator header uses libc malloc on the host.
                "-DESP_TEE_BUILD=1",
                "-DNO_DEBUG_STORAGE",
                "-include",
                str(work / "host_string.h"),
                *(flag for include in includes for flag in ("-I", str(include))),
                str(BASE / "tests/k151_nvs_power_loss_test.cpp"),
                str(args.page_source.resolve()),
                *(str(nvs / "src" / source) for source in sources),
                str(crc),
                "-o",
                str(binary),
            ],
            check=True,
            timeout=90,
        )
        return subprocess.run([str(binary)], check=False, timeout=60).returncode


if __name__ == "__main__":
    raise SystemExit(main())
